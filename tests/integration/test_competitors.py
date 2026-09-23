"""Per-competitor metrics, deltas and the change feed (PRD F07)."""

import pytest
from bsi_core import models as m
from bsi_core.competitors import (
    entity_metrics,
)
from bsi_core.db import tenant_session
from bsi_core.metrics import Filters, brand_metrics, rate, wilson


def _mention(org, obs, etype, eid, pos=1, rec="mentioned", sent="neutral"):
    return m.Mention(
        org_id=org.id,
        observation_id=obs,
        entity_type=etype,
        entity_id=eid,
        position=pos,
        rec_status=rec,
        sentiment=sent,
    )


def _cite(org, obs, domain, owned=False):
    return m.Citation(
        org_id=org.id,
        observation_id=obs,
        url="u",
        domain=domain,
        position=1,
        is_brand_owned=owned,
    )


@pytest.fixture
def scene(owner, make_org, make_brand, make_observation):
    """5 done answers over 3 prompts, 1 failed. Brand Nike (nike.com),
    rivals Adidas (adidas.com, adidas.co.in) and Puma (no domains),
    suggested Bata (must not appear).

    o1(p1): Nike recommended @1 positive; Adidas @2 negative;
            cites nike.com (owned), forbes.com
    o2(p1): Nike listed @3 neutral; cites shop.adidas.co.in
    o3(p2): Adidas recommended @1 positive; Puma @2 neutral;
            cites forbes.com, reddit.com
    o4(p2): nobody; cites forbes.com
    o5(p3): Puma @1 negative; cites bata.com
    o6(p3): failed
    """
    org = make_org()
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host="nike.com"))
        ad = m.Competitor(
            org_id=org.id,
            brand_id=bid,
            name="Adidas",
            domains=["adidas.com", "adidas.co.in"],
        )
        pu = m.Competitor(org_id=org.id, brand_id=bid, name="Puma")
        ba = m.Competitor(
            org_id=org.id, brand_id=bid, name="Bata", status="suggested"
        )
        s.add_all([ad, pu, ba])
        s.flush()
        c_ad, c_pu, c_ba = ad.id, pu.id, ba.id
    o1 = make_observation(org, bid, status="done", text="p1")
    with owner() as s:
        p1 = s.get(m.Observation, o1).prompt_id
    o2 = make_observation(org, bid, status="done", prompt_id=p1, sample_index=1)
    o3 = make_observation(org, bid, status="done", text="p2")
    with owner() as s:
        p2 = s.get(m.Observation, o3).prompt_id
    o4 = make_observation(org, bid, status="done", prompt_id=p2, sample_index=1)
    o5 = make_observation(org, bid, status="done", text="p3")
    with owner() as s:
        p3 = s.get(m.Observation, o5).prompt_id
    make_observation(org, bid, status="failed", prompt_id=p3, sample_index=1)
    with owner() as s, s.begin():
        s.add_all(
            [
                _mention(org, o1, "brand", bid, 1, "recommended", "positive"),
                _mention(
                    org, o1, "competitor", c_ad, 2, "mentioned", "negative"
                ),
                _mention(org, o2, "brand", bid, 3, "listed"),
                _mention(
                    org, o3, "competitor", c_ad, 1, "recommended", "positive"
                ),
                _mention(org, o3, "competitor", c_pu, 2),
                _mention(
                    org, o5, "competitor", c_pu, 1, "mentioned", "negative"
                ),
                _mention(org, o5, "competitor", c_ba, 2),
                _cite(org, o1, "nike.com", True),
                _cite(org, o1, "forbes.com"),
                _cite(org, o2, "shop.adidas.co.in"),
                _cite(org, o3, "forbes.com"),
                _cite(org, o3, "reddit.com"),
                _cite(org, o4, "forbes.com"),
                _cite(org, o5, "bata.com"),
            ]
        )
    return org, bid, {"adidas": c_ad, "puma": c_pu, "bata": c_ba, "p1": p1}


def rows(org, bid, **kw):
    with tenant_session(org.id) as s:
        return {r["name"]: r for r in entity_metrics(s, bid, Filters(**kw))}


def _r(k, n):
    return rate(k, n)


def test_every_entity_field_is_k_over_n(scene):
    org, bid, _ids = scene
    got = rows(org, bid)
    assert set(got) == {"Nike", "Adidas", "Puma"}  # Bata is suggested
    nike, adidas, puma = got["Nike"], got["Adidas"], got["Puma"]
    assert (nike["type"], adidas["type"]) == ("brand", "competitor")
    # 5 done answers; Adidas named in o1, o3; recommended in o3.
    assert adidas["mention_rate"] == _r(2, 5)
    assert adidas["recommendation_rate"] == _r(1, 5)
    # Cited on a subdomain of adidas.co.in in o2 only.
    assert adidas["citation_rate"] == _r(1, 5)
    # Prompts with done answers: p1, p2, p3; Adidas named on p1, p2.
    assert adidas["prompt_coverage"] == _r(2, 3)
    # Mentions in total: Nike 2, Adidas 2, Puma 2 (Bata's is not counted).
    assert adidas["sov"] == _r(2, 6)
    assert adidas["avg_position"] == {"value": 1.5, "n_mentioned": 2}
    assert adidas["sentiment"]["positive"] == _r(1, 2)
    assert adidas["sentiment"]["negative"] == _r(1, 2)
    assert adidas["sentiment"]["index"] == pytest.approx(0.0)
    # Domains cited in answers naming Adidas (o1, o3), most answers first.
    assert adidas["citing_domains"] == [
        {"domain": "forbes.com", "answers": 2, "owner": "third_party"},
        {"domain": "nike.com", "answers": 1, "owner": "brand"},
        {"domain": "reddit.com", "answers": 1, "owner": "third_party"},
    ]
    assert puma["mention_rate"] == _r(2, 5)
    assert puma["citation_rate"] == _r(0, 5)  # no domains declared
    assert puma["sentiment"]["index"] == pytest.approx(-0.5)
    assert puma["citing_domains"] == [
        {"domain": "bata.com", "answers": 1, "owner": "third_party"},
        {"domain": "forbes.com", "answers": 1, "owner": "third_party"},
        {"domain": "reddit.com", "answers": 1, "owner": "third_party"},
    ]
    low, high = wilson(2, 5)
    assert adidas["mention_rate"]["ci_low"] == pytest.approx(low)
    assert adidas["mention_rate"]["ci_high"] == pytest.approx(high)


def test_brand_row_agrees_with_brand_metrics(scene):
    org, bid, _ = scene
    got = rows(org, bid)["Nike"]
    with tenant_session(org.id) as s:
        bm = brand_metrics(s, bid, Filters())
    for k in (
        "mention_rate",
        "recommendation_rate",
        "citation_rate",
        "prompt_coverage",
        "sov",
    ):
        assert got[k] == bm[k], k
    assert got["avg_position"] == bm["avg_position"]
    assert got["citing_domains"][0] == {
        "domain": "forbes.com",
        "answers": 1,
        "owner": "third_party",
    }
    assert {d["domain"] for d in got["citing_domains"]} == {
        "forbes.com",
        "nike.com",
        "shop.adidas.co.in",
    }
    rival = next(
        d for d in got["citing_domains"] if d["domain"] == "shop.adidas.co.in"
    )
    assert rival["owner"] == "rival"


def test_rows_sort_by_mention_rate_brand_first_on_ties(scene):
    org, bid, _ = scene
    with tenant_session(org.id) as s:
        names = [r["name"] for r in entity_metrics(s, bid, Filters())]
    # Nike 2/5, Adidas 2/5, Puma 2/5: brand first, then by name.
    assert names == ["Nike", "Adidas", "Puma"]


def test_filters_apply(scene):
    org, bid, ids = scene
    got = rows(org, bid, prompt_ids=[ids["p1"]])
    assert got["Adidas"]["mention_rate"] == _r(1, 2)
    assert got["Puma"]["mention_rate"] == _r(0, 2)
    assert got["Puma"]["avg_position"] == {"value": None, "n_mentioned": 0}
    assert got["Puma"]["sentiment"]["index"] is None
    assert got["Puma"]["citing_domains"] == []


def test_no_answers_gives_empty_rates(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Nike")
    got = rows(org, bid)
    assert list(got) == ["Nike"]
    assert got["Nike"]["mention_rate"] == _r(0, 0)
    assert got["Nike"]["sov"]["value"] is None
