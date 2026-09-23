"""Content-gap clusters (PRD F11): clusters, the gap rule, the brief."""

from types import SimpleNamespace

import pytest
from bsi_core import models as m
from bsi_core.db import tenant_session
from bsi_core.gaps import (
    EVIDENCE_CAP,
    NOTE,
    PAGE_TYPES,
    brief,
    clusters,
    unlabelled,
)
from bsi_core.metrics import Filters, rate
from sqlalchemy import select, update


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
    assert b == brief(gap, "Nike")  # brief is pure and stored on the row
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
