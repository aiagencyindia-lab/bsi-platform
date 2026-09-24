"""Content-gap clusters (PRD F11): clusters, the gap rule, the brief."""

import hashlib
import uuid
from collections import Counter, defaultdict
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from bsi_core import models as m
from bsi_core.competitors import _entities_and_hosts, owner_of
from bsi_core.db import tenant_session
from bsi_core.gaps import (
    _BASE,
    _FROM,
    EVIDENCE_CAP,
    LINKS_CAP,
    NOTE,
    PAGE_TYPES,
    QUERIES_CAP,
    SOURCES_CAP,
    brief,
    clusters,
    unlabelled,
)
from bsi_core.metrics import Filters, _where, prompt_metrics, rate
from bsi_core.recommend import CONTENT_REASONS
from sqlalchemy import event, select, text, update
from sqlalchemy.orm import Session


def _mention(org, obs, etype, eid, pos=1):
    return m.Mention(
        org_id=org.id,
        observation_id=obs,
        entity_type=etype,
        entity_id=eid,
        position=pos,
        rec_status="mentioned",
        sentiment="neutral",
    )


@pytest.fixture
def scene(owner, make_org, make_brand, make_observation):
    """Brand Nike (nike.com); active rivals Adidas (adidas.co.in) and
    Puma; suggested Bata. Prompts (intent, topic) and answers as
    (brand present, rivals named, absence reason, cites):

    gap cluster (comparison, running shoes): 2 prompts x 4 answers
      "nike vs adidas": absent 3/4 (2 dominance naming Adidas, 1 not_retrieved
        naming only Bata, which is suggested); present answer cites
        https://nike.com/run (owned)
      "best running shoe brand": absent 3/4 (dominance, naming Adidas);
        absent answers cite forbes.com and shop.adidas.co.in
      -> absent 6/8, rival_absent 5, reasons {competitor_dominance: 5,
         not_retrieved: 1}: GAP
    winning (informational, sizing): "shoe size chart" 4/4 present
    mixed (recommendation, kids): "kids shoes" absent 1/4 (dominance)
    unlabelled: "old prompt" (no intent/topic) absent 3/3 dominance, Adidas
    Bata is named on two gap answers but is suggested -> never a rival; Puma
    is active but never named.
    """
    org = make_org()
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host="nike.com"))
        ad = m.Competitor(
            org_id=org.id, brand_id=bid, name="Adidas", domains=["adidas.co.in"]
        )
        pu = m.Competitor(org_id=org.id, brand_id=bid, name="Puma")
        ba = m.Competitor(
            org_id=org.id, brand_id=bid, name="Bata", status="suggested"
        )
        s.add_all([ad, pu, ba])
        s.flush()
        ids = SimpleNamespace(
            org=org, brand=bid, adidas=ad.id, puma=pu.id, bata=ba.id
        )

    def prompt(text, intent, topic, rows):
        first = make_observation(org, bid, status="done", text=text)
        with owner() as s, s.begin():
            pid = s.get(m.Observation, first).prompt_id
            s.execute(
                update(m.Prompt)
                .where(m.Prompt.id == pid)
                .values(intent=intent, topic=topic)
            )
        obs = [first] + [
            make_observation(
                org, bid, status="done", prompt_id=pid, sample_index=i
            )
            for i in range(1, len(rows))
        ]
        with owner() as s, s.begin():
            for oid, (present, rivals, reason, cites) in zip(
                obs, rows, strict=True
            ):
                s.add(
                    m.Extraction(
                        org_id=org.id,
                        observation_id=oid,
                        pipeline_version="2",
                        model_used="t",
                        brand_mentioned=present,
                        absence_reason=reason,
                    )
                )
                if present:
                    s.add(_mention(org, oid, "brand", bid))
                for k, rid in enumerate(rivals, 2):
                    s.add(_mention(org, oid, "competitor", rid, k))
                for pos, (url, domain, owned) in enumerate(cites, 1):
                    s.add(
                        m.Citation(
                            org_id=org.id,
                            observation_id=oid,
                            url=url,
                            domain=domain,
                            position=pos,
                            is_brand_owned=owned,
                        )
                    )
        return pid, obs

    A, B = ids.adidas, ids.bata  # Puma is active but never named
    forbes = ("https://forbes.com/x", "forbes.com", False)
    adi = ("https://shop.adidas.co.in/y", "shop.adidas.co.in", False)
    own = ("https://nike.com/run", "nike.com", True)
    ids.vs, ids.vs_obs = prompt(
        "nike vs adidas",
        "comparison",
        "running shoes",
        [
            (True, [A], None, [own]),
            (False, [A], "competitor_dominance", [forbes]),
            (False, [A, B], "competitor_dominance", [forbes, adi]),
            (False, [B], "not_retrieved", []),
        ],
    )
    ids.best, ids.best_obs = prompt(
        "best running shoe brand",
        "comparison",
        "running shoes",
        [
            (True, [], None, []),
            (False, [A], "competitor_dominance", [forbes]),
            (False, [A], "competitor_dominance", [adi]),
            (False, [A], "competitor_dominance", [forbes]),
        ],
    )
    ids.size, _ = prompt(
        "shoe size chart", "informational", "sizing", [(True, [], None, [])] * 4
    )
    ids.kids, _ = prompt(
        "kids shoes",
        "recommendation",
        "kids",
        [
            (True, [A], None, []),
            (True, [], None, []),
            (True, [], None, []),
            (False, [A], "competitor_dominance", []),
        ],
    )
    ids.old, _ = prompt(
        "old prompt", None, None, [(False, [A], "competitor_dominance", [])] * 3
    )
    ids.add = prompt  # tests add prompts to the same brand
    return ids


def rows(ids, **kw):
    with tenant_session(ids.org.id) as s:
        return {c["key"]: c for c in clusters(s, ids.brand, Filters(**kw))}


def test_cluster_numbers_and_order(scene):
    got = rows(scene)
    assert list(got) == [
        "cluster:comparison:running shoes",  # spread 2/8 - 6/8 = -0.5
        "cluster:recommendation:kids",  # 3/4 - 2/4 = +0.25
        "cluster:informational:sizing",  # top_rival None -> last
    ]
    gap = got["cluster:comparison:running shoes"]
    assert (gap["intent"], gap["topic"], gap["n"]) == (
        "comparison",
        "running shoes",
        8,
    )
    assert gap["brand"] == rate(2, 8)
    assert (gap["absent"], gap["rival_absent"]) == (6, 5)
    assert gap["reasons"] == {"competitor_dominance": 5, "not_retrieved": 1}
    assert [(r["name"], r["answers"]) for r in gap["rivals"]] == [("Adidas", 6)]
    assert gap["top_rival"] == {
        "name": "Adidas",
        "competitor_id": scene.adidas,
        **rate(6, 8),
    }
    assert gap["spread"] == pytest.approx(2 / 8 - 6 / 8)
    assert gap["cited"] == rate(1, 8)
    assert gap["sources"] == [
        {"domain": "forbes.com", "answers": 4, "owner": "third_party"},
        {"domain": "shop.adidas.co.in", "answers": 2, "owner": "rival"},
        {"domain": "nike.com", "answers": 1, "owner": "brand"},
    ]
    assert gap["brand_urls"] == ["https://nike.com/run"]
    # Worst prompt first: both 3/4 absent -> tie broken by text.
    assert [(p["text"], p["n"], p["absent"]) for p in gap["prompts"]] == [
        ("best running shoe brand", 4, 3),
        ("nike vs adidas", 4, 3),
    ]
    assert gap["gap"] is True and gap["brief"] is not None
    win = got["cluster:informational:sizing"]
    assert win["brand"] == rate(4, 4) and win["top_rival"] is None
    assert (
        win["spread"] is None and win["gap"] is False and win["brief"] is None
    )
    mixed = got["cluster:recommendation:kids"]
    assert (mixed["absent"], mixed["gap"]) == (1, False)
    assert (
        "cluster:None:None" not in got
    )  # the unlabelled prompt is not a cluster


def test_gap_rule_edges(scene, owner):
    # kids: make it absent 2/4 with rivals -> 2*2 >= 4 -> gap.
    with owner() as s, s.begin():
        oid = s.scalars(
            select(m.Observation.id)
            .where(m.Observation.prompt_id == scene.kids)
            .order_by(m.Observation.sample_index)
        ).all()[1]
        s.execute(
            m.Mention.__table__.delete().where(
                m.Mention.observation_id == oid,
                m.Mention.entity_type == "brand",
            )
        )
        s.add(_mention(scene.org, oid, "competitor", scene.adidas, 2))
        s.execute(
            update(m.Extraction)
            .where(m.Extraction.observation_id == oid)
            .values(brand_mentioned=False, absence_reason="not_retrieved")
        )
    got = rows(scene)["cluster:recommendation:kids"]
    assert got["absent"] == 2 and got["gap"] is True
    # A cluster whose top reason is category_mismatch is not a gap.
    with owner() as s, s.begin():
        s.execute(
            update(m.Extraction)
            .where(
                m.Extraction.observation_id.in_(scene.best_obs + scene.vs_obs)
            )
            .values(absence_reason="category_mismatch")
        )
    assert rows(scene)["cluster:comparison:running shoes"]["gap"] is False


def test_brief_fields(scene):
    gap = rows(scene)["cluster:comparison:running shoes"]
    b = gap["brief"]
    assert b == brief(gap)  # brief is pure and stored on the row
    assert b["target_queries"] == ["best running shoe brand", "nike vs adidas"]
    assert b["page_type"] == PAGE_TYPES["comparison"] == "comparison page"
    assert b["structure"][0].startswith("H1")
    assert any("best running shoe brand" in h for h in b["structure"])
    assert b["competitors"] == ["Adidas"]
    assert b["sources"] == [
        {"domain": "forbes.com", "answers": 4, "owner": "third_party"},
        {"domain": "shop.adidas.co.in", "answers": 2, "owner": "rival"},
    ]
    assert b["internal_links"] == ["https://nike.com/run"]
    assert set(b["evidence"]["prompt_ids"]) == {str(scene.vs), str(scene.best)}
    assert len(b["evidence"]["observation_ids"]) == 6
    assert b["note"] == NOTE
    assert b["prompts_total"] == 2


def test_evidence_is_capped(scene, owner, make_observation):
    for i in range(4, 4 + EVIDENCE_CAP):
        oid = make_observation(
            scene.org,
            scene.brand,
            status="done",
            prompt_id=scene.vs,
            sample_index=i,
        )
        with owner() as s, s.begin():
            s.add(
                m.Extraction(
                    org_id=scene.org.id,
                    observation_id=oid,
                    pipeline_version="2",
                    model_used="t",
                    brand_mentioned=False,
                    absence_reason="competitor_dominance",
                )
            )
            s.add(_mention(scene.org, oid, "competitor", scene.adidas))
    b = rows(scene)["cluster:comparison:running shoes"]["brief"]
    assert len(b["evidence"]["observation_ids"]) == EVIDENCE_CAP


def test_filters_narrow_clusters(scene):
    got = rows(scene, prompt_ids=[scene.vs])
    assert list(got) == ["cluster:comparison:running shoes"]
    assert got["cluster:comparison:running shoes"]["n"] == 4


def test_engine_filter_narrows_clusters(scene, owner):
    # engine is shared, not tenant data: the row is removed afterwards.
    with owner() as s, s.begin():
        other = m.Engine(code="other", provider="x", default_model="x")
        s.add(other)
        s.flush()
        s.execute(
            update(m.Observation)
            .where(m.Observation.id.in_(scene.vs_obs[:2]))
            .values(engine_id=other.id)
        )
    try:
        got = rows(scene, engine="other")
        assert list(got) == ["cluster:comparison:running shoes"]
        gap = got["cluster:comparison:running shoes"]
        assert (gap["n"], gap["absent"]) == (2, 1)
        assert gap["brand"] == rate(1, 2)
        rest = rows(scene, engine="gemini")["cluster:comparison:running shoes"]
        assert (rest["n"], rest["absent"]) == (6, 5)
    finally:
        with owner() as s, s.begin():
            s.execute(text("TRUNCATE organization CASCADE"))
            s.execute(
                m.Engine.__table__.delete().where(m.Engine.code == "other")
            )


def test_unlabelled_counts_active_prompts_missing_a_label(scene, owner):
    with tenant_session(scene.org.id) as s:
        assert unlabelled(s, scene.brand) == 1
    with owner() as s, s.begin():
        s.execute(
            update(m.Prompt)
            .where(m.Prompt.id == scene.old)
            .values(status="paused")
        )
    with tenant_session(scene.org.id) as s:
        assert unlabelled(s, scene.brand) == 0


def test_every_intent_has_a_page_type():
    assert set(PAGE_TYPES) == set(m.INTENTS)


def test_how_to_heading_reads_with_a_noun_topic():
    c = {
        "intent": "problem-based",
        "topic": "kids shoes",
        "prompts": [{"prompt_id": 1, "text": "why do kids shoes wear out"}],
        "rivals": [],
        "sources": [],
        "brand_urls": [],
        "absent_obs": [],
    }
    assert brief(c)["structure"][0] == "H1: kids shoes: problems and fixes"


def test_evidence_is_newest_across_the_cluster(scene, owner):
    # Backdate every answer of the prompt whose UUID sorts first, so a
    # per-prompt ordering would put its (older) answers first.
    first = min(scene.vs, scene.best)
    with owner() as s, s.begin():
        s.execute(
            update(m.Observation)
            .where(m.Observation.prompt_id == first)
            .values(requested_at=m.Observation.requested_at - timedelta(days=1))
        )
        absent = scene.vs_obs[1:] + scene.best_obs[1:]
        newest = (
            s.execute(
                select(m.Observation.id)
                .where(m.Observation.id.in_(absent))
                .order_by(
                    m.Observation.requested_at.desc(), m.Observation.id.desc()
                )
            )
            .scalars()
            .all()
        )
    b = rows(scene)["cluster:comparison:running shoes"]["brief"]
    assert b["evidence"]["observation_ids"] == [str(o) for o in newest]


def test_brief_sources_put_third_party_first(scene, owner):
    # shop.adidas.co.in (rival) now out-cites forbes.com (third party).
    with owner() as s, s.begin():
        for oid in (scene.vs_obs[1], scene.best_obs[1], scene.best_obs[3]):
            s.add(
                m.Citation(
                    org_id=scene.org.id,
                    observation_id=oid,
                    url="https://shop.adidas.co.in/z",
                    domain="shop.adidas.co.in",
                    position=9,
                    is_brand_owned=False,
                )
            )
    gap = rows(scene)["cluster:comparison:running shoes"]
    assert [x["domain"] for x in gap["sources"]] == [
        "shop.adidas.co.in",
        "forbes.com",
        "nike.com",
    ]
    assert gap["brief"]["sources"] == [
        {"domain": "forbes.com", "answers": 4, "owner": "third_party"},
        {"domain": "shop.adidas.co.in", "answers": 5, "owner": "rival"},
    ]


def test_reason_tie_breaks_by_name(scene, owner):
    # 3 vs 3: the prompt counted first gets the name that sorts last.
    first, second = sorted([scene.vs, scene.best])
    obs = {scene.vs: scene.vs_obs[1:], scene.best: scene.best_obs[1:]}
    with owner() as s, s.begin():
        for pid, reason in (
            (first, "not_retrieved"),
            (second, "category_mismatch"),
        ):
            s.execute(
                update(m.Extraction)
                .where(m.Extraction.observation_id.in_(obs[pid]))
                .values(absence_reason=reason)
            )
    gap = rows(scene)["cluster:comparison:running shoes"]
    assert gap["reasons"] == {"not_retrieved": 3, "category_mismatch": 3}
    assert gap["reason"] == "category_mismatch"


def test_cluster_counts_match_prompt_metrics(scene):
    with tenant_session(scene.org.id) as s:
        per_prompt = prompt_metrics(s, scene.brand, Filters())
    got = rows(scene)
    for key, c in got.items():
        ps = [
            p
            for p in per_prompt
            if f"cluster:{p['intent']}:{p['topic']}" == key
        ]
        assert c["n"] == sum(p["n"] for p in ps)
        present = sum(round(p["brand"]["value"] * p["n"]) for p in ps)
        assert c["n"] - c["absent"] == present


def _only_bata_on_absent_answers(scene, owner):
    """Absent answers name only Bata (suggested), so no active rival."""
    absent = scene.vs_obs[1:] + scene.best_obs[1:]
    with owner() as s, s.begin():
        s.execute(
            m.Mention.__table__.delete().where(
                m.Mention.observation_id.in_(absent),
                m.Mention.entity_type == "competitor",
            )
        )
        for oid in absent:
            s.add(_mention(scene.org, oid, "competitor", scene.bata, 2))


def test_a_gap_needs_no_rival(scene, owner):
    # Majority-absent with a content reason is a gap even when no absent
    # answer names an active rival (user decision; matches the old
    # per-prompt rule).
    _only_bata_on_absent_answers(scene, owner)
    gap = rows(scene)["cluster:comparison:running shoes"]
    assert (gap["absent"], gap["rival_absent"]) == (6, 0)
    assert gap["top_rival"]["name"] == "Adidas"  # the present answer
    assert gap["gap"] is True and gap["brief"] is not None


from bsi_core.recommend import generate, refresh  # noqa: E402


def found(ids):
    with tenant_session(ids.org.id) as s:
        return {(c.type, c.subject_key): c for c in generate(s, ids.brand)}


def test_a_rivalless_gap_rec_has_zero_pressure(scene, owner):
    _only_bata_on_absent_answers(scene, owner)
    c = found(scene)[("create_content", "cluster:comparison:running shoes")]
    assert (c.pressure, c.priority) == (0.0, 0.0)


def test_one_content_rec_per_gap_cluster_and_per_prompt_only_when_unlabelled(
    scene,
):
    recs = found(scene)
    content = {k: c for k, c in recs.items() if k[0] == "create_content"}
    assert set(content) == {
        ("create_content", "cluster:comparison:running shoes"),
        ("create_content", str(scene.old)),  # unlabelled: per-prompt rule
    }
    c = content[("create_content", "cluster:comparison:running shoes")]
    # total = 8 + 4 + 4 + 3 = 19 done answers on active prompts.
    assert (c.reach, c.pressure, c.feasibility) == (
        pytest.approx(6 / 19),
        pytest.approx(5 / 6),
        0.4,
    )
    assert c.priority == round(6 / 19 * 5 / 6 * 0.4, 4)
    assert c.title == "Publish a comparison page for running shoes (comparison)"
    assert "Adidas" in c.body and "Metric to watch:" in c.body
    ev = c.evidence
    assert ev["cluster"] == {"intent": "comparison", "topic": "running shoes"}
    assert (ev["reason"], ev["absent"], ev["n"]) == (
        "competitor_dominance",
        6,
        8,
    )
    assert set(ev["prompt_ids"]) == {str(scene.vs), str(scene.best)}
    assert len(ev["observation_ids"]) == 6
    assert ev["page_type"] == "comparison page" and ev["internal_links"] == [
        "https://nike.com/run"
    ]
    assert ev["competitors"] == ["Adidas"]


def test_labelling_a_prompt_moves_it_from_prompt_rec_to_cluster_rec(
    scene, owner
):
    with tenant_session(scene.org.id) as s:
        refresh(s, scene.org.id, scene.brand)
        keys = set(
            s.scalars(
                select(m.Recommendation.subject_key).where(
                    m.Recommendation.type == "create_content"
                )
            )
        )
    assert str(scene.old) in keys
    with owner() as s, s.begin():
        s.execute(
            update(m.Prompt)
            .where(m.Prompt.id == scene.old)
            .values(intent="comparison", topic="running shoes")
        )
    with tenant_session(scene.org.id) as s:
        refresh(s, scene.org.id, scene.brand)
        rows_ = s.scalars(
            select(m.Recommendation).where(
                m.Recommendation.type == "create_content"
            )
        ).all()
    assert {r.subject_key for r in rows_} == {
        "cluster:comparison:running shoes"
    }
    cluster = rows_[0]
    assert cluster.evidence["n"] == 11 and cluster.evidence["absent"] == 9


@pytest.mark.parametrize("decision", ["accepted", "dismissed"])
def test_a_decided_prompt_rec_survives_labelling(scene, owner, decision):
    with tenant_session(scene.org.id) as s:
        refresh(s, scene.org.id, scene.brand)
    with owner() as s, s.begin():
        s.execute(
            update(m.Recommendation)
            .where(m.Recommendation.subject_key == str(scene.old))
            .values(status=decision)
        )
        s.execute(
            update(m.Prompt)
            .where(m.Prompt.id == scene.old)
            .values(intent="informational", topic="history")
        )
    with tenant_session(scene.org.id) as s:
        refresh(s, scene.org.id, scene.brand)
        statuses = dict(
            s.execute(
                select(
                    m.Recommendation.subject_key, m.Recommendation.status
                ).where(m.Recommendation.type == "create_content")
            ).all()
        )
    assert statuses[str(scene.old)] == decision
    assert (
        "cluster:informational:history" in statuses
    )  # 3/3 absent, Adidas named


def test_a_half_labelled_prompt_stays_per_prompt(scene, owner):
    # intent set, topic null: still unlabelled, so no cluster takes it.
    with owner() as s, s.begin():
        s.execute(
            update(m.Prompt)
            .where(m.Prompt.id == scene.old)
            .values(intent="comparison")
        )
    content = {k for k in found(scene) if k[0] == "create_content"}
    assert content == {
        ("create_content", "cluster:comparison:running shoes"),
        ("create_content", str(scene.old)),
    }
    got = rows(scene)
    assert got["cluster:comparison:running shoes"]["n"] == 8
    assert not any(
        str(scene.old) in c["brief"]["evidence"]["prompt_ids"]
        for c in got.values()
        if c["brief"]
    )
    assert all(c["topic"] is not None for c in got.values())


GAP = "cluster:comparison:running shoes"
LOSING = [(False, [], "competitor_dominance", [])] * 2


def _decide(scene, owner, status="accepted"):
    with tenant_session(scene.org.id) as s:
        refresh(s, scene.org.id, scene.brand)
    with owner() as s, s.begin():
        s.execute(
            update(m.Recommendation)
            .where(m.Recommendation.subject_key == GAP)
            .values(status=status)
        )


def _plus(*pids):
    h = hashlib.sha1(",".join(sorted(map(str, pids))).encode()).hexdigest()
    return f"{GAP}:+{h[:8]}"


def _cluster_recs(scene):
    return {k: c for k, c in found(scene).items() if k[1].startswith(GAP)}


@pytest.mark.parametrize("decision", ["accepted", "dismissed"])
def test_a_new_prompt_in_a_decided_cluster_gets_its_own_rec(
    scene, owner, decision
):
    _decide(scene, owner, decision)
    rivals = [(False, [scene.adidas], "competitor_dominance", [])]
    new, _ = scene.add("nike or adidas", "comparison", "running shoes", rivals)
    recs = _cluster_recs(scene)
    assert list(recs) == [("create_content", _plus(new))]
    c = recs[("create_content", _plus(new))]
    assert c.evidence["prompt_ids"] == [str(new)]
    assert (c.evidence["absent"], c.evidence["n"]) == (1, 1)
    assert c.evidence["target_queries"] == ["nike or adidas"]
    # total = 19 + 1; the new prompt's one absent answer names Adidas.
    assert (c.reach, c.pressure) == (pytest.approx(1 / 20), 1.0)
    assert "absent from 1 of 1 answers" in c.body


def test_a_new_losing_prompt_is_raised_when_the_cluster_is_now_won(
    scene, owner, make_observation
):
    _decide(scene, owner)
    for i in range(4, 12):  # 8 winning answers on a covered prompt
        oid = make_observation(
            scene.org,
            scene.brand,
            status="done",
            prompt_id=scene.vs,
            sample_index=i,
        )
        with owner() as s, s.begin():
            s.add(_mention(scene.org, oid, "brand", scene.brand))
    new, _ = scene.add("nike or adidas", "comparison", "running shoes", LOSING)
    whole = rows(scene)[GAP]
    assert (whole["absent"], whole["n"], whole["gap"]) == (8, 18, False)
    recs = _cluster_recs(scene)
    assert list(recs) == [("create_content", _plus(new))]
    assert recs[("create_content", _plus(new))].evidence["prompt_ids"] == [
        str(new)
    ]


def test_a_decided_cluster_without_new_prompts_is_not_raised(scene, owner):
    _decide(scene, owner)
    assert _cluster_recs(scene) == {}


def test_a_new_prompt_the_brand_wins_is_not_raised(scene, owner):
    _decide(scene, owner)
    scene.add(
        "nike running", "comparison", "running shoes", [(True, [], None, [])]
    )
    assert _cluster_recs(scene) == {}


def test_accepting_the_new_prompt_rec_tasks_only_the_new_prompt(
    client, scene, owner
):
    _decide(scene, owner)
    new, _ = scene.add("nike or adidas", "comparison", "running shoes", LOSING)
    base = f"/v1/brands/{scene.brand}/recommendations"
    r = client.post(f"{base}/generate", headers=scene.org.headers)
    rec = next(x for x in r.json() if x["subject_key"] == _plus(new))
    t = client.post(f"{base}/{rec['id']}/accept", headers=scene.org.headers)
    assert t.status_code == 201, t.text
    assert t.json()["prompt_ids"] == [str(new)]
    # Its prompt is now decided too: nothing is raised for the cluster.
    assert _cluster_recs(scene) == {}


def test_a_second_new_prompt_replaces_the_open_rec(scene, owner):
    _decide(scene, owner)
    one, _ = scene.add("nike or adidas", "comparison", "running shoes", LOSING)

    def stored():
        with tenant_session(scene.org.id) as s:
            refresh(s, scene.org.id, scene.brand)
            return {
                r.subject_key: (r.status, r.evidence["prompt_ids"])
                for r in s.scalars(
                    select(m.Recommendation).where(
                        m.Recommendation.subject_key.startswith(GAP)
                    )
                )
            }

    first = stored()
    assert first[_plus(one)] == ("open", [str(one)])
    two, _ = scene.add("adidas or nike", "comparison", "running shoes", LOSING)
    assert _plus(one) != _plus(one, two)
    second = stored()
    assert set(second) == {GAP, _plus(one, two)}
    assert second[GAP] == first[GAP]  # the decided row is untouched
    assert second[GAP][0] == "accepted"
    assert sorted(second[_plus(one, two)][1]) == sorted([str(one), str(two)])


# The oracle for the grouped-query rewrite: clusters() as it was before
# it, verbatim but for the name and today's brief(row) (the brand name it
# read only for the old brief(row, brand) is dropped).
def _old_clusters(
    s: Session, brand_id: uuid.UUID, f: Filters
) -> list[dict[str, Any]]:
    where, params = _where(brand_id, f)
    _, hosts = _entities_and_hosts(s, brand_id)
    brand_hosts = hosts[brand_id]
    rival_hosts = [h for e, hs in hosts.items() if e != brand_id for h in hs]
    answers = s.execute(
        text(
            "SELECT p.intent, p.topic, o.prompt_id, p.text, o.id, "
            "o.requested_at, "
            "EXISTS (SELECT 1 FROM mention mn WHERE mn.observation_id = o.id "
            "  AND mn.entity_type = 'brand') AS present, "
            "EXISTS (SELECT 1 FROM mention mn JOIN competitor cp "
            "  ON cp.id = mn.entity_id WHERE mn.observation_id = o.id "
            "  AND mn.entity_type = 'competitor' AND cp.status = 'active') "
            "  AS rival, "
            "EXISTS (SELECT 1 FROM citation c WHERE c.observation_id = o.id "
            "  AND c.is_brand_owned) AS cited, "
            "e.absence_reason "
            f"{_FROM} LEFT JOIN extraction e ON e.observation_id = o.id "
            f"WHERE {where} AND {_BASE} "
            "ORDER BY p.intent, p.topic, o.prompt_id, o.requested_at DESC, o.id"
        ),
        params,
    ).all()
    rivals = s.execute(
        text(
            "SELECT p.intent, p.topic, cp.id, cp.name, "
            "count(DISTINCT o.id) AS answers "
            "FROM mention mn JOIN competitor cp ON cp.id = mn.entity_id "
            "JOIN observation o ON o.id = mn.observation_id "
            "JOIN prompt p ON p.id = o.prompt_id "
            f"WHERE {where} AND {_BASE} AND mn.entity_type = 'competitor' "
            "AND cp.status = 'active' "
            "GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 5 DESC, 4"
        ),
        params,
    ).all()
    sources = s.execute(
        text(
            "SELECT p.intent, p.topic, c.domain, "
            "count(DISTINCT o.id) AS answers "
            "FROM citation c JOIN observation o ON o.id = c.observation_id "
            "JOIN prompt p ON p.id = o.prompt_id "
            f"WHERE {where} AND {_BASE} "
            "GROUP BY 1, 2, 3 ORDER BY 1, 2, 4 DESC, 3"
        ),
        params,
    ).all()
    urls = s.execute(
        text(
            "SELECT DISTINCT p.intent, p.topic, c.url "
            "FROM citation c JOIN observation o ON o.id = c.observation_id "
            "JOIN prompt p ON p.id = o.prompt_id "
            f"WHERE {where} AND {_BASE} AND c.is_brand_owned ORDER BY 1, 2, 3"
        ),
        params,
    ).all()
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for r in answers:
        c = by_key.setdefault(
            (r.intent, r.topic),
            {
                "n": 0,
                "present": 0,
                "cited": 0,
                "rival_absent": 0,
                "reasons": Counter(),
                "prompts": {},
                "absent_obs": [],
            },
        )
        c["n"] += 1
        c["present"] += r.present
        c["cited"] += r.cited
        p = c["prompts"].setdefault(
            r.prompt_id,
            {"prompt_id": r.prompt_id, "text": r.text, "n": 0, "absent": 0},
        )
        p["n"] += 1
        if not r.present:
            p["absent"] += 1
            c["absent_obs"].append((r.requested_at, r.id))
            c["rival_absent"] += r.rival
            if r.absence_reason:
                c["reasons"][r.absence_reason] += 1
    riv: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rivals:
        riv[(r.intent, r.topic)].append(
            {"competitor_id": r.id, "name": r.name, "answers": r.answers}
        )
    src: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in sources:
        src[(r.intent, r.topic)].append(
            {
                "domain": r.domain,
                "answers": r.answers,
                "owner": owner_of(r.domain, brand_hosts, rival_hosts),
            }
        )
    lnk: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in urls:
        lnk[(r.intent, r.topic)].append(r.url)
    out = []
    for (intent, topic), c in by_key.items():
        n, absent = c["n"], c["n"] - c["present"]
        top = riv[(intent, topic)][:1]
        top_rival = (
            {
                "name": top[0]["name"],
                "competitor_id": top[0]["competitor_id"],
                **rate(top[0]["answers"], n),
            }
            if top
            else None
        )
        b = rate(c["present"], n)
        reasons = dict(c["reasons"])
        # Top reason: highest count, ties broken by reason name.
        reason = (
            min(reasons, key=lambda k: (-reasons[k], k)) if reasons else None
        )
        # No rival required (user decision): such gaps get pressure 0.
        # n >= 1, so absent * 2 >= n implies absent >= 1, which keeps
        # recommend's rival_absent / absent defined.
        gap = absent * 2 >= n and reason in CONTENT_REASONS
        row: dict[str, Any] = {
            "intent": intent,
            "topic": topic,
            "key": f"cluster:{intent}:{topic}",
            "prompts": sorted(
                c["prompts"].values(),
                key=lambda p: (-(p["absent"] / p["n"]), p["text"]),
            ),
            "n": n,
            "brand": b,
            "absent": absent,
            "rival_absent": c["rival_absent"],
            "reasons": reasons,
            "reason": reason,
            "rivals": riv[(intent, topic)],
            "top_rival": top_rival,
            "spread": (b["value"] - top_rival["value"]) if top_rival else None,
            "cited": rate(c["cited"], n),
            "sources": src[(intent, topic)][:SOURCES_CAP],
            "brand_urls": lnk[(intent, topic)][:LINKS_CAP],
            "gap": gap,
            # The cluster's newest absent answers (id breaks ties), capped:
            # the brief's evidence.
            "absent_obs": [i for _, i in sorted(c["absent_obs"], reverse=True)][
                :EVIDENCE_CAP
            ],
        }
        row["brief"] = brief(row) if gap else None
        out.append(row)
    out.sort(
        key=lambda r: (
            r["spread"] is None,
            r["spread"] or 0.0,
            -r["n"],
            r["key"],
        )
    )
    return out


@pytest.fixture
def big(scene, owner, make_observation):
    """The scene plus: Puma owns puma.com and is named; a rival tie in
    (informational, care); null absence reasons in (transactional,
    stores); brand, rival and third-party citations, two owned hosts; a
    paused prompt and an unfinished answer, which no cluster counts."""
    with owner() as s, s.begin():
        s.execute(
            update(m.Competitor)
            .where(m.Competitor.id == scene.puma)
            .values(domains=["puma.com"])
        )
    A, P, B = scene.adidas, scene.puma, scene.bata
    forbes = ("https://forbes.com/x", "forbes.com", False)
    reddit = ("https://reddit.com/r", "reddit.com", False)
    puma = ("https://puma.com/a", "puma.com", False)
    trail = ("https://nike.com/trail", "nike.com", True)
    www = ("https://www.nike.com/x", "www.nike.com", True)
    scene.add(
        "puma vs nike",
        "comparison",
        "trail",
        [
            (False, [P, A], None, [puma, forbes]),
            (False, [P], "not_retrieved", [trail]),
            (True, [A], None, [trail, www]),
        ],
    )
    scene.add(
        "trail shoe care",
        "informational",
        "care",
        [
            (False, [A, P], "competitor_dominance", [reddit]),
            (False, [P, A], "competitor_dominance", [forbes]),
            (True, [], None, [reddit]),
        ],
    )
    scene.add(
        "where to buy nike",
        "transactional",
        "stores",
        [(False, [B], None, [www]), (False, [], None, [])],
    )
    paused, _ = scene.add(
        "paused one", "comparison", "trail", [(False, [A], None, [puma])]
    )
    with owner() as s, s.begin():
        s.execute(
            update(m.Prompt)
            .where(m.Prompt.id == paused)
            .values(status="paused")
        )
    make_observation(
        scene.org,
        scene.brand,
        status="fetched",
        prompt_id=scene.vs,
        sample_index=9,
    )
    return scene


def _same(ids, f):
    with tenant_session(ids.org.id) as s:
        new = clusters(s, ids.brand, f)
    with tenant_session(ids.org.id) as s:
        old = _old_clusters(s, ids.brand, f)
    assert new == old
    return new


def test_clusters_match_the_old_queries_on_the_scene(scene):
    assert len(_same(scene, Filters())) == 3
    assert len(_same(scene, Filters(prompt_ids=[scene.vs]))) == 1


def test_clusters_match_the_old_queries_on_a_bigger_scene(big):
    got = _same(big, Filters())
    assert len(got) >= 6
    care = next(c for c in got if c["topic"] == "care")
    assert [r["answers"] for r in care["rivals"]] == [2, 2]  # a tie
    assert _same(big, Filters(prompt_ids=[big.vs, big.size]))


def _statements(ids):
    seen = []

    def count(_conn, _cursor, statement, *_):
        seen.append(statement)

    with tenant_session(ids.org.id) as s:
        bind = s.get_bind()
        event.listen(bind, "before_cursor_execute", count)
        try:
            clusters(s, ids.brand, Filters())
        finally:
            event.remove(bind, "before_cursor_execute", count)
    return seen


def test_statement_count_does_not_grow_with_clusters(scene):
    few = len(_statements(scene))
    for i in range(3):
        scene.add(
            f"extra {i}",
            "commercial",
            f"topic {i}",
            [(False, [scene.adidas], "competitor_dominance", [])],
        )
    many = len(_statements(scene))
    assert few == many <= 6, (few, many)


def test_brief_queries_are_capped_and_evidence_is_stored_once(scene):
    rows_ = [(False, [scene.adidas], "competitor_dominance", [])]
    pids = [
        scene.add(f"boots {i:02}", "commercial", "boots", rows_)[0]
        for i in range(QUERIES_CAP + 1)
    ]
    b = rows(scene)["cluster:commercial:boots"]["brief"]
    assert len(b["target_queries"]) == QUERIES_CAP == 20
    assert b["target_queries"][0] == "boots 00"  # worst first, then text
    assert b["prompts_total"] == QUERIES_CAP + 1
    assert (
        sum(h.startswith("H2: boots ") for h in b["structure"]) == QUERIES_CAP
    )
    c = found(scene)[("create_content", "cluster:commercial:boots")]
    assert "evidence" not in c.evidence
    assert sorted(c.evidence["prompt_ids"]) == sorted(map(str, pids))
    assert len(c.evidence["observation_ids"]) == QUERIES_CAP  # EVIDENCE_CAP
    assert c.evidence["prompts_total"] == QUERIES_CAP + 1
