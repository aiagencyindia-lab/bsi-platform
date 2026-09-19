from datetime import UTC, datetime, timedelta

import pytest
from bsi_core import models as m
from bsi_core.db import tenant_session
from bsi_core.metrics import Filters, brand_metrics, brand_sov, failed_count
from sqlalchemy import select


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
    assert got["pipeline_version"] == "1"
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
