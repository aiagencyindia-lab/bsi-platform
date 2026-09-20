"""Suggestion jobs with injected fakes. Nothing here calls Vertex."""

import json
from math import cos, sin

import pytest
from bsi_core import models as m
from bsi_core.db import tenant_session
from bsi_core.judge import JudgeFailed
from bsi_core.providers.base import EngineResult, ParsedAnswer
from bsi_core.suggest import (
    EMBED_PRICES,
    MAX_BACKFILL,
    embed,
    suggest_competitors,
    suggest_prompts,
)
from sqlalchemy import select


def vec(angle: float) -> list[float]:
    """A 768-dim unit vector at a known angle: cosine is cos(a - b)."""
    return [cos(angle), sin(angle)] + [0.0] * 766


class FakeGen:
    """(prompt, schema, temperature) -> (json, cost, model)."""

    def __init__(self, *replies: tuple[str, int]) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, type, float]] = []

    def __call__(self, prompt, schema, temperature):
        self.calls.append((prompt, schema, temperature))
        text, cost = self.replies.pop(0)
        return text, cost, "fake-model"


class FakeEmbed:
    def __init__(self, angles: dict[str, float], cost: int = 7) -> None:
        self.angles = angles
        self.cost = cost
        self.calls: list[list[str]] = []

    def __call__(self, texts):
        self.calls.append(list(texts))
        return [vec(self.angles[t]) for t in texts], self.cost


class FakeAdapter:
    code = "fake"

    def __init__(self, *answers: str | None) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[str, str, str]] = []

    def query(self, prompt, country, language, **kw):
        self.calls.append((prompt, country, language))
        answer = self.answers.pop(0)
        if answer is None:
            return EngineResult("fatal", error="boom", model="fake")
        return EngineResult(
            "ok", raw={"text": answer}, model="fake", cost_micros=50_000
        )

    def parse(self, raw):
        return ParsedAnswer(text=raw["text"], citations=[])


def prompt_json(*items: tuple[str, str, str]) -> str:
    return json.dumps(
        {"prompts": [{"text": t, "intent": i, "topic": p} for t, i, p in items]}
    )


def competitor_json(*items: tuple[str, str]) -> str:
    return json.dumps(
        {"competitors": [{"name": n, "domain": d} for n, d in items]}
    )


@pytest.fixture
def brand(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Nike", aliases=("Nike India",))
    return org, bid


def add_prompt(owner, org, bid, text, **kw):
    with owner() as s, s.begin():
        locale = s.scalars(
            select(m.Locale).where(m.Locale.brand_id == bid)
        ).first()
        row = m.Prompt(
            org_id=org.id,
            brand_id=bid,
            locale_id=locale.id,
            text=text,
            **kw,
        )
        s.add(row)
        s.flush()
        return row.id


def prompts(org):
    with tenant_session(org.id) as s:
        return list(s.scalars(select(m.Prompt).order_by(m.Prompt.created_at)))


def competitors(org):
    with tenant_session(org.id) as s:
        return list(s.scalars(select(m.Competitor).order_by(m.Competitor.name)))


# --- prompts ---------------------------------------------------------


def test_generation_writes_labelled_rows(brand):
    org, bid = brand
    texts = [f"best kids shoes {n}" for n in range(5)]
    gen = FakeGen(
        (
            prompt_json(*[(t, "commercial", "school shoes") for t in texts]),
            6_000,
        )
    )
    emb = FakeEmbed({t: i * 0.5 for i, t in enumerate(texts)})

    assert suggest_prompts(org.id, bid, 4, gen, emb) == "suggested:4"

    # 25% more than asked for, at temperature 1.0.
    assert gen.calls[0][2] == 1.0
    assert "Write 5 distinct prompts" in gen.calls[0][0]
    rows = prompts(org)
    assert [r.text for r in rows] == texts[:4]
    assert {r.source for r in rows} == {"generated"}
    assert {r.status for r in rows} == {"suggested"}
    assert {(r.intent, r.topic) for r in rows} == {
        ("commercial", "school shoes")
    }
    assert all(r.embedding is not None for r in rows)


def test_near_duplicate_of_existing_is_dropped(brand, owner):
    org, bid = brand
    add_prompt(
        owner,
        org,
        bid,
        "top shoes for children",
        intent="commercial",
        topic="school shoes",
        embedding=vec(0.0),
    )
    # 0.2 rad from the stored vector: cosine 0.980, above 0.92.
    # 1.0 rad away: cosine 0.540, well below it.
    gen = FakeGen(
        (
            prompt_json(
                ("best shoes for kids", "commercial", "school shoes"),
                ("how do I clean sneakers", "problem-based", "cleaning"),
            ),
            6_000,
        )
    )
    emb = FakeEmbed(
        {"best shoes for kids": 0.2, "how do I clean sneakers": 1.0}
    )

    assert suggest_prompts(org.id, bid, 2, gen, emb) == "suggested:1"
    assert [r.text for r in prompts(org)] == [
        "top shoes for children",
        "how do I clean sneakers",
    ]


def test_count_zero_backfills_and_inserts_nothing(brand, owner):
    org, bid = brand
    add_prompt(owner, org, bid, "best shoes for kids")
    gen = FakeGen(
        (prompt_json(("best shoes for kids", "commercial", "sizing")), 900)
    )
    emb = FakeEmbed({"best shoes for kids": 0.3})

    assert suggest_prompts(org.id, bid, 0, gen, emb) == "suggested:0"

    assert len(gen.calls) == 1  # the label call only, no generation
    row = prompts(org)[0]
    assert (row.intent, row.topic, row.source) == (
        "commercial",
        "sizing",
        "manual",
    )
    assert row.embedding is not None


def test_archived_brand_raises_before_any_model_call(brand, owner):
    org, bid = brand
    with owner() as s, s.begin():
        s.get(m.Brand, bid).status = "archived"
    gen = FakeGen()
    emb = FakeEmbed({})

    with pytest.raises(JudgeFailed) as e:
        suggest_prompts(org.id, bid, 5, gen, emb)

    assert e.value.cost_micros == 0
    assert gen.calls == []
    assert emb.calls == []


def test_invalid_json_raises_with_the_cost_and_writes_nothing(brand):
    org, bid = brand
    gen = FakeGen(("not json at all", 6_000))

    with pytest.raises(JudgeFailed) as e:
        suggest_prompts(org.id, bid, 5, gen, FakeEmbed({}))

    assert e.value.cost_micros == 6_000
    assert prompts(org) == []


# --- competitors -----------------------------------------------------


def test_competitors_merge_with_evidence_counts(brand):
    org, bid = brand
    adapter = FakeAdapter("answer one", "answer two", "answer three")
    gen = FakeGen(
        (competitor_json(("Aretto", "wearetto.com"), ("Bata", "bata.com")), 10),
        (
            competitor_json(
                ("Aretto", "https://wearetto.com/kids"),
                ("Bubblegummers", "www.bata.com"),
            ),
            10,
        ),
        (competitor_json(("Aretto", "wearetto.com"), ("Nike", "nike.com")), 10),
    )

    assert suggest_competitors(org.id, bid, adapter, gen) == "suggested:2"

    assert len(adapter.calls) == 3
    assert adapter.calls[0][1:] == ("IN", "en")
    rows = competitors(org)
    assert [(r.name, r.domains, r.evidence, r.status) for r in rows] == [
        ("Aretto", ["wearetto.com"], 3, "suggested"),
        ("Bata", ["bata.com"], 2, "suggested"),
    ]


def test_one_failed_answer_still_produces_a_result(brand):
    org, bid = brand
    adapter = FakeAdapter("answer one", None, "answer three")
    gen = FakeGen(
        (competitor_json(("Aretto", "wearetto.com")), 10),
        (competitor_json(("Aretto", "wearetto.com")), 10),
    )

    assert suggest_competitors(org.id, bid, adapter, gen) == "suggested:1"
    assert competitors(org)[0].evidence == 2


def test_all_three_answers_failing_raises(brand):
    org, bid = brand
    adapter = FakeAdapter(None, None, None)
    gen = FakeGen()

    with pytest.raises(JudgeFailed) as e:
        suggest_competitors(org.id, bid, adapter, gen)

    assert e.value.cost_micros == 0
    assert competitors(org) == []


def test_rerun_does_not_duplicate_a_suggested_competitor(brand, owner):
    org, bid = brand
    with owner() as s, s.begin():
        s.add(
            m.Competitor(
                org_id=org.id,
                brand_id=bid,
                name="Aretto",
                domains=["wearetto.com"],
                status="suggested",
                evidence=3,
            )
        )
    adapter = FakeAdapter("a", "b", "c")
    gen = FakeGen(
        *[
            (
                competitor_json(
                    ("Aretto", "wearetto.com"), ("Bata", "bata.com")
                ),
                10,
            )
        ]
        * 3
    )

    assert suggest_competitors(org.id, bid, adapter, gen) == "suggested:1"
    assert [(r.name, r.evidence) for r in competitors(org)] == [
        ("Aretto", 3),
        ("Bata", 3),
    ]


# --- embed -----------------------------------------------------------


class FakeClient:
    """Stands in for genai.Client: records each batch it is given."""

    def __init__(self, token_counts: list[float | None]) -> None:
        self.counts = token_counts
        self.batches: list[list[str]] = []
        self.models = self

    def embed_content(self, *, model, contents, config):
        from google.genai import types

        self.batches.append(list(contents))
        assert config.task_type == "SEMANTIC_SIMILARITY"
        assert config.output_dimensionality == 768
        return types.EmbedContentResponse(
            embeddings=[
                types.ContentEmbedding(
                    values=[0.1] * 768,
                    statistics=(
                        None
                        if self.counts[0] is None
                        else types.ContentEmbeddingStatistics(
                            token_count=self.counts[0]
                        )
                    ),
                )
                for _ in contents
            ]
        )


def test_embed_batches_and_prices_the_tokens():
    texts = [f"prompt number {n}" for n in range(150)]
    client = FakeClient([12.0])

    vectors, cost = embed(texts, client=client)

    assert [len(b) for b in client.batches] == [100, 50]
    assert len(vectors) == 150 and len(vectors[0]) == 768
    price = EMBED_PRICES["gemini-embedding-001"]
    assert cost == round(150 * 12 * price)


def test_embed_falls_back_to_a_character_estimate():
    text = "a" * 30  # 30 // 3 = 10 tokens
    _, cost = embed([text], client=FakeClient([None]))
    assert cost == round(10 * EMBED_PRICES["gemini-embedding-001"])


def test_embed_raises_for_an_unpriced_model(monkeypatch):
    from bsi_core.config import get_settings

    monkeypatch.setattr(
        get_settings(), "embed_model", "no-such-model", raising=True
    )
    with pytest.raises(KeyError):
        embed(["hi"], client=FakeClient([1.0]))


def test_label_backfill_is_capped_per_job(brand, owner):
    # Unbounded, a big backlog would be sent in one call, truncate the
    # reply and re-spend on every rerun. Each job drains one batch.
    org, bid = brand
    texts = [f"kids shoe question {i}" for i in range(MAX_BACKFILL + 5)]
    for text in texts:
        add_prompt(owner, org, bid, text)
    gen = FakeGen(
        (
            prompt_json(
                *((t, "commercial", "sizing") for t in texts[:MAX_BACKFILL])
            ),
            900,
        )
    )
    emb = FakeEmbed(dict.fromkeys(texts, 0.3))

    assert suggest_prompts(org.id, bid, 0, gen, emb) == "suggested:0"

    asked = gen.calls[0][0]
    assert sum(t in asked for t in texts) == MAX_BACKFILL
    labelled = [p for p in prompts(org) if p.intent is not None]
    assert len(labelled) == MAX_BACKFILL
