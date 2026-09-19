import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from bsi_core.providers.gemini import GeminiGroundingAdapter
from google.genai import errors

RAW = json.loads(Path("tests/fixtures/gemini_min.json").read_text())


def adapter_with(behaviour):
    client = SimpleNamespace(models=SimpleNamespace(generate_content=behaviour))
    return GeminiGroundingAdapter(client=client, model="gemini-2.5-flash")


def test_parse_joins_text_and_reads_real_hosts():
    answer = GeminiGroundingAdapter(client=object()).parse(RAW)
    assert answer.text == (
        "For kids, Nike and Adidas are popular. Puma is also listed."
    )
    assert [d for _, d in answer.citations] == ["nike.com", "runrepeat.com"]
    assert answer.citations[0][0].endswith("/AAA")


def test_parse_survives_empty_payload():
    answer = GeminiGroundingAdapter(client=object()).parse({})
    assert (answer.text, answer.citations) == ("", [])


def test_cost_counts_tokens_and_the_grounded_prompt():
    # Gemini 2.5 Flash: 10 * 0.30 + (100 + 20) * 2.50 = 303 for tokens,
    # plus $35 per 1,000 grounded prompts = 35_000 once per grounded answer.
    adapter = GeminiGroundingAdapter(client=object(), model="gemini-2.5-flash")
    assert adapter.cost(RAW) == 35_303
    ungrounded = {"usage_metadata": RAW["usage_metadata"]}
    assert adapter.cost(ungrounded) == 303


def test_default_engine_is_gemini_3_8_flash_priced_per_search_query():
    adapter = GeminiGroundingAdapter(client=object())
    # min fixture: 10 in, 100 out + 20 thinking, 1 search query.
    # 10 * 1.50 + 120 * 7.50 = 915 for tokens, plus 14_000 per query.
    assert adapter.cost(RAW) == 14_915


def test_per_query_cost_scales_with_query_count():
    adapter = GeminiGroundingAdapter(client=object(), model="gemini-3.8-flash")
    raw = {
        "usage_metadata": {"prompt_token_count": 0},
        "candidates": [
            {"grounding_metadata": {"web_search_queries": ["a", "b", "c"]}}
        ],
    }
    assert adapter.cost(raw) == 42_000


def test_ungrounded_answer_has_text_no_citations_and_token_only_cost():
    # gemini-3.8-flash may answer without searching even with the tool set.
    raw = json.loads(Path("tests/fixtures/gemini_ungrounded.json").read_text())
    adapter = GeminiGroundingAdapter(client=object(), model="gemini-3.8-flash")
    answer = adapter.parse(raw)
    assert len(answer.text) > 100 and answer.citations == []
    u = raw["usage_metadata"]
    tokens_out = u.get("candidates_token_count", 0) + u.get(
        "thoughts_token_count", 0
    )
    assert adapter.cost(raw) == round(
        u.get("prompt_token_count", 0) * 1.50 + tokens_out * 7.50
    )


def test_unpriced_model_fails_instead_of_guessing():
    response = SimpleNamespace(model_dump=lambda **_: RAW)
    client = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **_: response)
    )
    result = GeminiGroundingAdapter(client=client, model="gemini-9").query(
        "q", "IN", "en"
    )
    assert result.kind == "fatal"
    assert "gemini-9" in result.error


def test_query_ok():
    response = SimpleNamespace(model_dump=lambda **_: RAW)
    result = adapter_with(lambda **_: response).query("q", "IN", "en")
    assert result.kind == "ok"
    assert result.raw == RAW
    assert result.cost_micros == 35_303
    assert result.model_version == "gemini-2.5-flash"
    assert result.params["country"] == "IN"


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (errors.ClientError(429, {"error": {"message": "quota"}}), "retryable"),
        (errors.ServerError(503, {"error": {"message": "down"}}), "retryable"),
        (errors.ClientError(400, {"error": {"message": "bad"}}), "fatal"),
        (TimeoutError("slow"), "retryable"),
    ],
)
def test_query_never_raises(exc, kind):
    def boom(**_):
        raise exc

    result = adapter_with(boom).query("q", "IN", "en")
    assert result.kind == kind
    assert result.error


def test_query_never_raises_on_malformed_payload():
    bad_raw = {
        **RAW,
        "usage_metadata": {
            **RAW["usage_metadata"],
            "prompt_token_count": "ten",
        },
    }
    response = SimpleNamespace(model_dump=lambda **_: bad_raw)
    result = adapter_with(lambda **_: response).query("q", "IN", "en")
    assert result.kind == "fatal"
    assert result.error


@pytest.mark.parametrize("name", ["kids_shoes", "crm"])
def test_parse_recorded_payloads(name):
    raw = json.loads(Path(f"tests/fixtures/gemini_{name}.json").read_text())
    adapter = GeminiGroundingAdapter(client=object())
    answer = adapter.parse(raw)
    assert len(answer.text) > 100
    assert answer.citations
    assert all("." in d and "/" not in d for _, d in answer.citations)
    assert "vertexaisearch" not in {d for _, d in answer.citations}
    queries = raw["candidates"][0]["grounding_metadata"]["web_search_queries"]
    assert adapter.cost(raw) >= 14_000 * len(queries) > 0


def test_ungrounded_query_sends_no_tools_and_prepends_context():
    seen = {}

    def generate(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            model_dump=lambda **_: {
                "usage_metadata": {
                    "prompt_token_count": 10,
                    "candidates_token_count": 10,
                }
            }
        )

    result = adapter_with(generate).query(
        "best kids shoes", "IN", "en", grounded=False, context="Sources: a.com"
    )
    assert result.kind == "ok"
    assert seen["config"].tools is None
    assert seen["contents"] == "Sources: a.com\n\nbest kids shoes"
    assert (result.params["grounded"], result.params["tools"]) == (False, [])
    assert result.cost_micros == 28  # 10 * 0.30 + 10 * 2.50; no grounding


def test_grounded_query_is_unchanged_by_default():
    seen = {}

    def generate(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(model_dump=lambda **_: RAW)

    result = adapter_with(generate).query("q", "IN", "en")
    assert seen["contents"] == "q"
    assert len(seen["config"].tools) == 1
    assert (result.params["grounded"], result.params["tools"]) == (
        True,
        ["google_search"],
    )
