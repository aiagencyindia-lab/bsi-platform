from datetime import UTC, datetime, timedelta

import pytest
from bsi_core import models as m
from bsi_core.db import tenant_session
from bsi_core.metrics import (
    DELTA_METRICS,
    Filters,
    brand_deltas,
    brand_metrics,
    brand_sov,
    failed_count,
)
from sqlalchemy import func, select, update


@pytest.fixture
def scene(owner, make_org, make_brand, make_observation):
    """4 done observations over 2 prompts, 1 failed.

    o1(p1): brand recommended @1, c1, owned citation
    o2(p1): brand listed @3
    o3(p2): c1, c2
    o4(p2): nobody          o5(p2): failed
    """
    org = make_org()
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        comps = [
            m.Competitor(org_id=org.id, brand_id=bid, name=n)
            for n in ("Adidas", "Puma")
        ]
        s.add_all(comps)
        s.flush()
        c1, c2 = comps[0].id, comps[1].id
    o1 = make_observation(org, bid, status="done", text="p1")
    with owner() as s:
        p1 = s.get(m.Observation, o1).prompt_id
    o2 = make_observation(org, bid, status="done", prompt_id=p1, sample_index=1)
    o3 = make_observation(org, bid, status="done", text="p2")
    with owner() as s:
        p2 = s.get(m.Observation, o3).prompt_id
    make_observation(org, bid, status="done", prompt_id=p2, sample_index=1)
    make_observation(org, bid, status="failed", prompt_id=p2, sample_index=2)

    def mention(obs, etype, eid, pos, rec="mentioned"):
        return m.Mention(
            org_id=org.id,
            observation_id=obs,
            entity_type=etype,
            entity_id=eid,
            position=pos,
            rec_status=rec,
            sentiment="neutral",
        )

    with owner() as s, s.begin():
        s.add_all(
            [
                mention(o1, "brand", bid, 1, "recommended"),
                mention(o1, "competitor", c1, 2),
                mention(o2, "brand", bid, 3, "listed"),
                mention(o3, "competitor", c1, 1),
                mention(o3, "competitor", c2, 2),
                m.Citation(
                    org_id=org.id,
                    observation_id=o1,
                    url="u",
                    domain="nike.com",
                    position=1,
                    is_brand_owned=True,
                ),
                m.Citation(
                    org_id=org.id,
                    observation_id=o3,
                    url="u",
                    domain="x.com",
                    position=1,
                    is_brand_owned=False,
                ),
            ]
        )
    return org, bid, p2


def metrics(org, bid, **kw):
    with tenant_session(org.id) as s:
        return brand_metrics(s, bid, Filters(**kw))


def test_rates(scene):
    org, bid, _ = scene
    got = metrics(org, bid)
    assert (got["mention_rate"]["value"], got["mention_rate"]["n"]) == (0.5, 4)
    assert got["recommendation_rate"]["value"] == 0.25
    assert got["citation_rate"]["value"] == 0.25
    assert (got["prompt_coverage"]["value"], got["prompt_coverage"]["n"]) == (
        0.5,
        2,
    )
    assert got["avg_position"] == {"value": 2.0, "n_mentioned": 2}
    assert got["n_failed"] == 1
    assert got["pipeline_version"] == "2"
    assert got["pipeline_versions"] == []  # the scene has no extraction rows
    with tenant_session(org.id) as s:
        assert failed_count(s, bid, Filters()) == 1
    low, high = got["mention_rate"]["ci_low"], got["mention_rate"]["ci_high"]
    assert low == pytest.approx(0.150, abs=1e-3)
    assert high == pytest.approx(0.850, abs=1e-3)


def test_sov(scene):
    org, bid, _ = scene
    with tenant_session(org.id) as s:
        rows = brand_sov(s, bid, Filters())
    assert [(r["name"], r["type"], r["mentions"]) for r in rows] == [
        ("Nike", "brand", 2),
        ("Adidas", "competitor", 2),
        ("Puma", "competitor", 1),
    ]
    assert rows[0]["share"] == pytest.approx(0.4)
    assert metrics(org, bid)["sov"]["value"] == pytest.approx(0.4)
    assert metrics(org, bid)["sov"]["n"] == 5


def test_filters(scene):
    org, bid, p2 = scene
    only_p2 = metrics(org, bid, prompt_ids=[p2])
    assert (only_p2["mention_rate"]["value"], only_p2["mention_rate"]["n"]) == (
        0.0,
        2,
    )
    assert metrics(org, bid, engine="gemini")["mention_rate"]["n"] == 4
    assert metrics(org, bid, engine="nope")["mention_rate"]["n"] == 0
    with tenant_session(org.id) as s:
        locale = s.scalars(select(m.Locale)).one().id
    assert metrics(org, bid, locale_id=locale)["mention_rate"]["n"] == 4


def test_empty_window_has_null_values_and_full_interval(scene):
    org, bid, _ = scene
    past = datetime.now(UTC) - timedelta(days=2)
    got = metrics(org, bid, date_from=past - timedelta(days=1), date_to=past)
    assert got["mention_rate"] == {
        "value": None,
        "n": 0,
        "ci_low": 0.0,
        "ci_high": 1.0,
    }
    assert got["avg_position"] == {"value": None, "n_mentioned": 0}
    assert got["sov"]["value"] is None


@pytest.fixture
def windows(owner, make_org, make_brand, make_observation):
    """4 done observations on one prompt: 2 backdated 36h, 2 just now.

    Returns a factory taking the older window's pipeline version.
    """
    org = make_org()
    bid = make_brand(org, "Nike")
    obs = [make_observation(org, bid, status="done", text="q1")]
    with owner() as s:
        pid = s.get(m.Observation, obs[0]).prompt_id
    obs += [
        make_observation(org, bid, status="done", prompt_id=pid, sample_index=i)
        for i in (1, 2, 3)
    ]

    def _make(before_version: str):
        with owner() as s, s.begin():
            s.execute(
                update(m.Observation)
                .where(m.Observation.id.in_(obs[:2]))
                .values(requested_at=func.now() - timedelta(hours=36))
            )
            s.add_all(
                m.Extraction(
                    org_id=org.id,
                    observation_id=o,
                    pipeline_version=before_version if i < 2 else "2",
                    model_used="x",
                    brand_mentioned=i != 1,
                )
                for i, o in enumerate(obs)
            )
            s.add_all(
                m.Mention(
                    org_id=org.id,
                    observation_id=o,
                    entity_type="brand",
                    entity_id=bid,
                    position=1,
                    rec_status="recommended",
                    sentiment="neutral",
                )
                for i, o in enumerate(obs)
                if i != 1
            )
        return org, bid

    return _make


def deltas(org, bid, days=1):
    with tenant_session(org.id) as s:
        return brand_deltas(
            s, bid, Filters(), days, datetime.now(UTC) + timedelta(minutes=1)
        )


def test_brand_deltas_compares_windows(windows):
    org, bid = windows("2")
    got = deltas(org, bid)
    assert got["before"]["mention_rate"]["n"] == 2
    assert got["after"]["mention_rate"]["n"] == 2
    assert got["before"]["from"] < got["before"]["to"] == got["after"]["from"]
    assert got["comparable"] is True
    assert got["reason"] is None
    assert got["after"]["pipeline_versions"] == ["2"]
    assert {k: got["deltas"][k]["label"] for k in DELTA_METRICS} == {
        "mention_rate": "no significant change",
        "recommendation_rate": "no significant change",
        "citation_rate": "no significant change",
        "prompt_coverage": "no significant change",
        "sov": "no significant change",
    }
    assert got["deltas"]["mention_rate"]["value"] == pytest.approx(0.5)


def test_brand_deltas_refuses_mixed_versions(windows):
    org, bid = windows("1")
    got = deltas(org, bid)
    assert got["comparable"] is False
    assert got["deltas"] is None
    assert "'1', '2'" in got["reason"]
    assert got["before"]["pipeline_versions"] == ["1"]


def test_suggested_competitor_is_not_measured(owner, scene):
    """A guess with a mention row must not move the customer's numbers."""
    org, bid, _ = scene
    with owner() as s, s.begin():
        comp = m.Competitor(
            org_id=org.id, brand_id=bid, name="Reebok", status="suggested"
        )
        s.add(comp)
        s.flush()
        obs = s.scalars(
            select(m.Observation).where(m.Observation.status == "done")
        ).first()
        s.add(
            m.Mention(
                org_id=org.id,
                observation_id=obs.id,
                entity_type="competitor",
                entity_id=comp.id,
                position=9,
                rec_status="mentioned",
                sentiment="neutral",
            )
        )
    with tenant_session(org.id) as s:
        rows = brand_sov(s, bid, Filters())
    assert [(r["name"], r["mentions"]) for r in rows] == [
        ("Nike", 2),
        ("Adidas", 2),
        ("Puma", 1),
    ]
    assert rows[0]["share"] == pytest.approx(0.4)
    assert metrics(org, bid)["sov"]["value"] == pytest.approx(0.4)
