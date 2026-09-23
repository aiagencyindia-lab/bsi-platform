"""Per-competitor metrics, deltas and the change feed (PRD F07)."""

from datetime import UTC, datetime, timedelta

import pytest
from bsi_core import models as m
from bsi_core.competitors import (
    _DONE,
    CITING_DOMAINS,
    EVIDENCE_CAP,
    MIN_PROMPTS,
    MIN_SHIFT,
    _deltas,
    _moved,
    entity_deltas,
    entity_metrics,
    owner_of,
    visibility_changes,
)
from bsi_core.db import tenant_session
from bsi_core.metrics import (
    DELTA_METRICS,
    Filters,
    _entities,
    _where,
    brand_metrics,
    brand_sov,
    delta,
    rate,
    wilson,
)
from sqlalchemy import delete, event, select, text, update


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
    o2(p1): Nike listed @3 neutral; cites shop.adidas.co.in, notadidas.com
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
                _cite(org, o2, "notadidas.com"),
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
    # Cited on a subdomain of adidas.co.in in o2 only; notadidas.com
    # (also o2) is not a subdomain of adidas.com.
    assert adidas["citation_rate"] == _r(1, 5)
    assert owner_of("notadidas.com", ["nike.com"], ["adidas.com"]) == (
        "third_party"
    )
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
    for k in DELTA_METRICS:
        assert got[k] == bm[k], k
    assert got["avg_position"] == bm["avg_position"]
    # Answers naming Nike: o1 (nike.com, forbes.com) and o2
    # (shop.adidas.co.in, notadidas.com), one answer each.
    assert got["citing_domains"] == [
        {"domain": "forbes.com", "answers": 1, "owner": "third_party"},
        {"domain": "nike.com", "answers": 1, "owner": "brand"},
        {"domain": "notadidas.com", "answers": 1, "owner": "third_party"},
        {"domain": "shop.adidas.co.in", "answers": 1, "owner": "rival"},
    ]


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


def _answers(owner, org, bid, prompt_id, when, n):
    """n done answers on one prompt with requested_at = when, inserted
    directly (make_observation cannot set the time)."""
    with owner() as s, s.begin():
        locale = s.scalars(
            select(m.Locale).where(m.Locale.brand_id == bid)
        ).first()
        engine = s.scalars(select(m.Engine).order_by(m.Engine.code)).first()
        job = s.scalars(
            select(m.Job).where(m.Job.brand_id == bid, m.Job.kind == "run")
        ).first()
        if job is None:
            job = m.Job(org_id=org.id, brand_id=bid, scheduled_slot=when)
            s.add(job)
            s.flush()
        obs = [
            m.Observation(
                org_id=org.id,
                brand_id=bid,
                job_id=job.id,
                prompt_id=prompt_id,
                engine_id=engine.id,
                locale_id=locale.id,
                sample_index=i,
                scheduled_slot=when.replace(minute=0, second=0, microsecond=0),
                status="done",
                requested_at=when,
            )
            for i in range(n)
        ]
        s.add_all(obs)
        s.flush()
        return [o.id for o in obs]


def _prompt(owner, org, bid, text_):
    with owner() as s, s.begin():
        locale = s.scalars(
            select(m.Locale).where(m.Locale.brand_id == bid)
        ).first()
        p = m.Prompt(
            org_id=org.id, brand_id=bid, locale_id=locale.id, text=text_
        )
        s.add(p)
        s.flush()
        return p.id


NOW = datetime.now(UTC) + timedelta(minutes=1)
BEFORE_AT = NOW - timedelta(days=20)
AFTER_AT = NOW - timedelta(days=5)


@pytest.fixture
def feed(owner, make_org, make_brand):
    """12 prompts x 10 answers per window (n=10 so a 0.1 shift exists).

    A: before 0/10 everywhere; after 10/10 on q00..q10 (11 prompts), 0/10
       on q11  -> up on 11 prompts, pooled 0/110 -> 110/110: qualifies.
    B: after 10/10 on q00..q08 (9 prompts)  -> count rule fails.
    C: before 4/10, after 5/10 on q00..q09 (10 prompts, shift exactly
       MIN_SHIFT) -> pooled 40/100 -> 50/100: delta() says
       "no significant change" (the test computes it, not the fixture).
       (1/10 -> 2/10 would NOT do: 10/100 -> 20/100 is just significant.)
    Citations: every before answer on q00 cites old.com; after answers
    naming A on q00 cite old.com and new.com.
    """
    org = make_org()
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        cs = [
            m.Competitor(org_id=org.id, brand_id=bid, name=n)
            for n in ("A", "B", "C")
        ]
        s.add_all(cs)
        s.flush()
        ca, cb, cc = (c.id for c in cs)
    prompts = [_prompt(owner, org, bid, f"q{i:02d}") for i in range(12)]
    before = {p: _answers(owner, org, bid, p, BEFORE_AT, 10) for p in prompts}
    after = {p: _answers(owner, org, bid, p, AFTER_AT, 10) for p in prompts}
    ment = []
    cites = []
    for i, p in enumerate(prompts):
        if i < 11:
            ment += [_mention(org, o, "competitor", ca) for o in after[p]]
        if i < 9:
            ment += [_mention(org, o, "competitor", cb, 2) for o in after[p]]
        if i < 10:
            ment += [
                _mention(org, o, "competitor", cc, 3) for o in before[p][:4]
            ]
            ment += [
                _mention(org, o, "competitor", cc, 3) for o in after[p][:5]
            ]
    cites += [_cite(org, o, "old.com") for o in before[prompts[0]]]
    cites += [
        _cite(org, o, d)
        for o in after[prompts[0]]
        for d in ("old.com", "new.com")
    ]
    with owner() as s, s.begin():
        s.add_all(ment + cites)
    return (
        org,
        bid,
        {
            "a": ca,
            "b": cb,
            "c": cc,
            "prompts": prompts,
            "before": before,
            "after": after,
        },
    )


def changes(org, bid, days=14, to=NOW, **kw):
    with tenant_session(org.id) as s:
        return visibility_changes(s, bid, Filters(**kw), days, to)


def test_feed_constants():
    assert (MIN_PROMPTS, MIN_SHIFT, EVIDENCE_CAP) == (10, 0.10, 20)


def test_one_answer_at_n_10_is_min_shift():
    # 5/10 - 4/10 is 0.0999... in floats; it must still count.
    assert _moved(4, 10, 5, 10) == "up"
    assert _moved(2, 10, 3, 10) == "up"
    assert _moved(5, 10, 4, 10) == "down"
    assert _moved(4, 10, 4, 10) is None


def test_only_the_qualifying_competitor_gets_an_entry(owner, feed):
    org, bid, ids = feed
    # Three of A's after answers on q00 are later, newest first.
    late = ids["after"][ids["prompts"][0]][:3]
    with owner() as s, s.begin():
        for i, o in enumerate(late):
            s.execute(
                update(m.Observation)
                .where(m.Observation.id == o)
                .values(requested_at=AFTER_AT + timedelta(hours=3 - i))
            )
        code = s.scalars(select(m.Engine).order_by(m.Engine.code)).first().code
    got = changes(org, bid)
    assert (got["comparable"], got["reason"], got["prompts"]) == (
        True,
        None,
        12,
    )
    assert [(c["name"], c["direction"]) for c in got["changes"]] == [
        ("A", "up")
    ]
    a = got["changes"][0]
    assert a["competitor_id"] == ids["a"]
    assert a["before"] == rate(0, 110)
    assert a["after"] == rate(110, 110)
    assert a["delta"] == delta(rate(0, 110), rate(110, 110))
    assert a["delta"]["label"] == "increase"
    assert len(a["prompts"]) == 11
    assert all(
        p["before"] == rate(0, 10) and p["after"] == rate(10, 10)
        for p in a["prompts"]
    )
    assert [p["text"] for p in a["prompts"]] == [f"q{i:02d}" for i in range(11)]
    assert a["engines"] == [code]
    assert a["new_citing_domains"] == ["new.com"]  # old.com was cited before
    assert len(a["observation_ids"]) == EVIDENCE_CAP
    assert a["observation_ids"][:3] == late  # most recent first
    assert set(a["observation_ids"]) <= {
        o for p in ids["prompts"][:11] for o in ids["after"][p]
    }


def test_feed_reports_its_window(feed):
    org, bid, _ = feed
    window = {
        "before_from": NOW - timedelta(days=28),
        "split": NOW - timedelta(days=14),
        "to": NOW,
    }
    assert changes(org, bid)["window"] == window
    # Also when it returns early.
    few = changes(org, bid, days=3)
    assert few["reason"] is not None
    assert few["window"]["split"] == NOW - timedelta(days=3)


def test_the_count_rule_and_the_pooled_test_both_gate(feed):
    org, bid, _ids = feed
    names = {c["name"] for c in changes(org, bid)["changes"]}
    assert "B" not in names  # 9 prompts moved: below MIN_PROMPTS
    assert "C" not in names  # 10 moved by exactly MIN_SHIFT, but pooled:
    assert delta(rate(40, 100), rate(50, 100))["label"] == (
        "no significant change"
    )


def test_direction_down_and_filters(owner, feed):
    org, bid, ids = feed
    # to = NOW - 5d: after = [NOW-19d, NOW-5d) is empty (BEFORE_AT is
    # NOW-20d, AFTER_AT is NOW-5d, not < to); before = [NOW-33d, NOW-19d)
    # holds BEFORE_AT -> no prompt has answers in both windows.
    got = changes(org, bid, days=14, to=NOW - timedelta(days=5))
    assert got["prompts"] == 0
    assert got["reason"] == "fewer than 10 prompts with answers in both windows"
    assert got["changes"] == []
    only = changes(org, bid, prompt_ids=ids["prompts"][:5])
    assert only["prompts"] == 5 and only["changes"] == []
    # Move A's mentions from the after answers to the before answers on
    # q00..q10: A goes 10/10 -> 0/10 there, so it moves down.
    with owner() as s, s.begin():
        s.execute(delete(m.Mention).where(m.Mention.entity_id == ids["a"]))
        s.add_all(
            [
                _mention(org, o, "competitor", ids["a"])
                for p in ids["prompts"][:11]
                for o in ids["before"][p]
            ]
        )
    got = changes(org, bid)
    assert [(c["name"], c["direction"]) for c in got["changes"]] == [
        ("A", "down")
    ]
    a = got["changes"][0]
    assert a["before"] == rate(110, 110)
    assert a["after"] == rate(0, 110)
    assert a["delta"] == delta(rate(110, 110), rate(0, 110))
    assert a["delta"]["label"] == "decrease"
    assert len(a["prompts"]) == 11
    # No after answer names A, so there is no after-window evidence.
    assert (a["engines"], a["new_citing_domains"], a["observation_ids"]) == (
        [],
        [],
        [],
    )


def test_mixed_pipeline_versions_are_not_comparable(owner, feed):
    org, bid, ids = feed
    first_before = ids["prompts"][0]
    obs_before = ids["before"][first_before][0]
    obs_after = ids["after"][first_before][0]
    with owner() as s, s.begin():
        s.add_all(
            [
                m.Extraction(
                    org_id=org.id,
                    observation_id=obs_before,
                    pipeline_version="1",
                    model_used="x",
                    brand_mentioned=False,
                ),
                m.Extraction(
                    org_id=org.id,
                    observation_id=obs_after,
                    pipeline_version="2",
                    model_used="x",
                    brand_mentioned=False,
                ),
            ]
        )
    got = changes(org, bid)
    assert got["comparable"] is False
    assert got["reason"] == (
        "windows use different pipeline versions ['1', '2']; "
        "re-extract the older window"
    )
    assert got["changes"] == []
    with tenant_session(org.id) as s:
        d = entity_deltas(s, bid, Filters(), 14, NOW)
    assert (d["comparable"], d["reason"], d["deltas"]) == (
        False,
        got["reason"],
        None,
    )


def test_entity_deltas_mirror_brand_deltas(feed):
    org, bid, ids = feed
    with tenant_session(org.id) as s:
        got = entity_deltas(s, bid, Filters(), 14, NOW)
    assert got["comparable"] is True and got["reason"] is None
    assert got["before"]["from"] == NOW - timedelta(days=28)
    assert (
        got["before"]["to"] == got["after"]["from"] == NOW - timedelta(days=14)
    )
    assert got["after"]["to"] == NOW
    a_before = next(r for r in got["before"]["entities"] if r["name"] == "A")
    a_after = next(r for r in got["after"]["entities"] if r["name"] == "A")
    assert a_before["mention_rate"] == rate(0, 120)
    assert a_after["mention_rate"] == rate(110, 120)
    d = got["deltas"][ids["a"]]
    assert set(d) == set(DELTA_METRICS)
    assert d["mention_rate"] == delta(rate(0, 120), rate(110, 120))
    assert d["prompt_coverage"] == delta(rate(0, 12), rate(11, 12))
    # An entity with no mentions in either window still has a delta row.
    assert got["deltas"][bid]["mention_rate"]["label"] == (
        "no significant change"
    )


def test_deltas_entity_missing_from_before_uses_zero_count():
    """A competitor activated between the two entity_metrics reads is in
    after but not before: it gets deltas against rate(0, n), n being the
    before window's done-answer count."""
    brand, rival = "brand-id", "rival-id"

    def row(eid, k, n):
        return {"entity_id": eid, **{key: rate(k, n) for key in DELTA_METRICS}}

    before = [row(brand, 2, 10)]
    after = [row(brand, 3, 10), row(rival, 6, 10)]
    out = _deltas(before, after)
    assert out[rival] == {
        k: delta(rate(0, 10), rate(6, 10)) for k in DELTA_METRICS
    }
    assert out[brand] == {
        k: delta(rate(2, 10), rate(3, 10)) for k in DELTA_METRICS
    }
    # No before rows at all: n is 0.
    assert _deltas([], after)[rival] == {
        k: delta(rate(0, 0), rate(6, 10)) for k in DELTA_METRICS
    }


def _hosts(s, brand_id):
    """Declared domains per entity: the brand's `domain` rows, each active
    competitor's `domains` column."""
    out = {
        brand_id: list(
            s.scalars(
                select(m.Domain.host).where(m.Domain.brand_id == brand_id)
            )
        )
    }
    for c in s.scalars(
        select(m.Competitor).where(
            m.Competitor.brand_id == brand_id, m.Competitor.status == "active"
        )
    ):
        out[c.id] = list(c.domains)
    return out


def _old_entity_metrics(s, brand_id, f):
    """entity_metrics as it was at be83002 (2 queries per entity, host
    match by LIKE): the reference the grouped rewrite must equal."""
    where, params = _where(brand_id, f)
    hosts = _hosts(s, brand_id)
    brand_hosts = hosts[brand_id]
    rival_hosts = [
        h for eid, hs in hosts.items() if eid != brand_id for h in hs
    ]
    sov = {r["entity_id"]: r for r in brand_sov(s, brand_id, f)}
    sov_total = sum(r["mentions"] for r in sov.values())
    rows = []
    for eid, name, etype in _entities(s, brand_id):
        p = {
            **params,
            "eid": eid,
            "etype": etype,
            "domains": hosts.get(eid, []),
        }
        r = s.execute(
            text(f"""
            SELECT
              count(*) AS n,
              count(*) FILTER (WHERE mn.id IS NOT NULL) AS k_mention,
              count(*) FILTER (WHERE mn.rec_status = 'recommended') AS k_rec,
              count(*) FILTER (WHERE EXISTS (
                SELECT 1 FROM citation c
                WHERE c.observation_id = o.id AND EXISTS (
                  SELECT 1 FROM unnest(CAST(:domains AS text[])) d
                  WHERE c.domain = d OR c.domain LIKE '%.' || d))) AS k_cit,
              count(DISTINCT o.prompt_id) AS prompts,
              count(DISTINCT o.prompt_id) FILTER (
                WHERE mn.id IS NOT NULL) AS prompts_cov,
              avg(mn.position) AS avg_pos,
              count(*) FILTER (WHERE mn.sentiment = 'positive') AS k_pos,
              count(*) FILTER (WHERE mn.sentiment = 'negative') AS k_neg
            FROM observation o
            LEFT JOIN mention mn ON mn.observation_id = o.id
              AND mn.entity_type = :etype AND mn.entity_id = :eid
            WHERE {where} AND {_DONE}"""),
            p,
        ).one()
        cited = s.execute(
            text(
                "SELECT c.domain, count(DISTINCT o.id) AS answers "
                "FROM citation c "
                "JOIN observation o ON o.id = c.observation_id "
                "JOIN mention mn ON mn.observation_id = o.id "
                "  AND mn.entity_type = :etype AND mn.entity_id = :eid "
                f"WHERE {where} AND {_DONE} "
                "GROUP BY c.domain ORDER BY answers DESC, c.domain "
                f"LIMIT {CITING_DOMAINS}"
            ),
            p,
        ).all()
        pos = rate(r.k_pos, r.k_mention)
        neg = rate(r.k_neg, r.k_mention)
        rows.append(
            {
                "entity_id": eid,
                "name": name,
                "type": etype,
                "mention_rate": rate(r.k_mention, r.n),
                "recommendation_rate": rate(r.k_rec, r.n),
                "citation_rate": rate(r.k_cit, r.n),
                "prompt_coverage": rate(r.prompts_cov, r.prompts),
                "sov": rate(
                    sov.get(eid, {"mentions": 0})["mentions"], sov_total
                ),
                "avg_position": {
                    "value": float(r.avg_pos)
                    if r.avg_pos is not None
                    else None,
                    "n_mentioned": r.k_mention,
                },
                "sentiment": {
                    "positive": pos,
                    "negative": neg,
                    "index": (
                        pos["value"] - neg["value"]
                        if pos["value"] is not None and neg["value"] is not None
                        else None
                    ),
                },
                "citing_domains": [
                    {
                        "domain": c.domain,
                        "answers": c.answers,
                        "owner": owner_of(c.domain, brand_hosts, rival_hosts),
                    }
                    for c in cited
                ],
            }
        )
    rows.sort(
        key=lambda r: (
            -(r["mention_rate"]["value"] or -1.0),
            r["type"] != "brand",
            r["name"],
        )
    )
    return rows


RIVALS = {
    "Adidas": ["adidas.com", "adidas.co.in"],
    "Puma": ["puma.com"],
    "Reebok": [],
    "Asics": ["asics.com"],
    "Mizuno": ["mizuno.com"],
    "Fila": ["fila.com"],
}
DOMAINS = [
    "nike.com",
    "shop.nike.com",
    "adidas.com",
    "xadidas.com",  # not adidas.com's: no dot before the host
    "eu.puma.com",
    "forbes.com",
    "reddit.com",
    "asics.com",
    "bata.com",
    "store.adidas.co.in",
]


def _big_scene(owner, make_org, make_brand, make_observation, rivals):
    """3 prompts x 6 done answers, 1 failed; the brand plus `rivals` active
    competitors from RIVALS and a suggested Bata. Mentions, rec status,
    sentiment, positions and citations vary by a fixed pattern."""
    org = make_org()
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host="nike.com"))
        cs = [
            m.Competitor(org_id=org.id, brand_id=bid, name=n, domains=d)
            for n, d in list(RIVALS.items())[:rivals]
        ] + [
            m.Competitor(
                org_id=org.id,
                brand_id=bid,
                name="Bata",
                domains=["bata.com"],
                status="suggested",
            )
        ]
        s.add_all(cs)
        s.flush()
        entities = [("brand", bid)] + [("competitor", c.id) for c in cs]
    obs, prompts = [], []
    for p in range(3):
        o = make_observation(org, bid, status="done", text=f"q{p}")
        with owner() as s:
            prompts.append(s.get(m.Observation, o).prompt_id)
        obs.append(o)
        obs += [
            make_observation(
                org, bid, status="done", prompt_id=prompts[-1], sample_index=i
            )
            for i in range(1, 6)
        ]
    make_observation(
        org, bid, status="failed", prompt_id=prompts[0], sample_index=6
    )
    rows = []
    for i, o in enumerate(obs):
        for j, (etype, eid) in enumerate(entities):
            if (i * (j + 2) + j) % (j + 3) < 2:
                rows.append(
                    _mention(
                        org,
                        o,
                        etype,
                        eid,
                        1 + (i + j) % 4,
                        ("recommended", "mentioned", "listed")[(i + j) % 3],
                        ("positive", "neutral", "negative")[(i * j) % 3],
                    )
                )
        for d in {
            DOMAINS[i % 10],
            DOMAINS[(i * 3 + 1) % 10],
            *([DOMAINS[(i * 7 + 2) % 10]] if i % 2 else []),
        }:
            rows.append(_cite(org, o, d))
    with owner() as s, s.begin():
        s.add_all(rows)
    return org, bid, prompts


def test_grouped_metrics_equal_the_per_entity_path(
    owner, make_org, make_brand, make_observation
):
    org, bid, prompts = _big_scene(
        owner, make_org, make_brand, make_observation, rivals=4
    )
    for f in (Filters(), Filters(prompt_ids=prompts[:2])):
        with tenant_session(org.id) as s:
            old = _old_entity_metrics(s, bid, f)
            new = entity_metrics(s, bid, f)
        assert [r["name"] for r in new] == [r["name"] for r in old]
        assert len(new) == 5  # brand + 4 active; suggested Bata is not
        for a, b in zip(new, old, strict=True):
            assert a == b, a["name"]
        # The fixture exercises what it claims to.
        assert any(r["citation_rate"]["value"] for r in new)
        assert any(r["citing_domains"] for r in new)
    # Each entity cites a different top list on the unfiltered window, so
    # rows keyed to the wrong entity cannot compare equal by accident.
    with tenant_session(org.id) as s:
        cited = [r["citing_domains"] for r in entity_metrics(s, bid, Filters())]
    assert all(c for c in cited)
    assert all(a != b for i, a in enumerate(cited) for b in cited[i + 1 :])


def _statements(org, bid):
    seen = []

    def count(_conn, _cursor, statement, *_):
        seen.append(statement)

    with tenant_session(org.id) as s:
        bind = s.get_bind()
        event.listen(bind, "before_cursor_execute", count)
        try:
            entity_metrics(s, bid, Filters())
        finally:
            event.remove(bind, "before_cursor_execute", count)
    return seen


def _count_queries(org, bid):
    return len(_statements(org, bid))


def test_query_count_does_not_grow_with_rivals(
    owner, make_org, make_brand, make_observation
):
    one = _big_scene(owner, make_org, make_brand, make_observation, rivals=1)
    many = _big_scene(owner, make_org, make_brand, make_observation, rivals=6)
    few, lots = _count_queries(*one[:2]), _count_queries(*many[:2])
    assert few == lots <= 8, (few, lots)


def test_active_competitors_are_read_once(
    owner, make_org, make_brand, make_observation
):
    """Names and domains come from one read, so a competitor activated
    mid-request cannot be in the entity list without its hosts."""
    org, bid, _ = _big_scene(
        owner, make_org, make_brand, make_observation, rivals=2
    )
    reads = [q for q in _statements(org, bid) if "FROM competitor" in q]
    assert len(reads) == 1, reads


def test_host_with_underscore_is_not_a_wildcard(owner, scene):
    org, bid, ids = scene
    with owner() as s, s.begin():
        s.execute(
            update(m.Competitor)
            .where(m.Competitor.id == ids["puma"])
            .values(domains=["my_shop.com"])
        )
        o3 = s.scalars(
            select(m.Mention.observation_id).where(
                m.Mention.entity_id == ids["puma"]
            )
        ).first()
        s.add(_cite(org, o3, "www.myXshop.com"))
    assert rows(org, bid)["Puma"]["citation_rate"] == _r(0, 5)
