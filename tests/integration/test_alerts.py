"""Alerts: detectors, dedupe, scan, and the due functions."""

from datetime import UTC, datetime, timedelta

from bsi_core import models as m
from bsi_core.alerts import (
    DROP_DAYS,
    NEW_SOURCE_MIN_ANSWERS,
    SOURCE_DAYS,
    detect_competitor_shift,
    detect_mention_drop,
    detect_new_source,
    is_duplicate,
    scan,
)
from bsi_core.db import system_session, tenant_session
from bsi_core.metrics import Filters, brand_deltas
from sqlalchemy import func, select, text, update

from tests.integration.test_competitors import (  # noqa: F401
    NOW,
    _answers,
    _cite,
    _mention,
    _prompt,
    feed,
)


def due_scans():
    with system_session() as s:
        return [
            r[0]
            for r in s.execute(text("SELECT brand_id FROM due_alert_scans()"))
        ]


def due_deliveries():
    with system_session() as s:
        return [
            r[0]
            for r in s.execute(
                text("SELECT alert_id FROM due_alert_deliveries()")
            )
        ]


def _alert(owner, org, bid, **kw):
    """One stored alert; keyword arguments override the defaults."""
    now = datetime.now(UTC)
    row = {
        "type": "new_source",
        "subject_key": "x.com",
        "title": "t",
        "window_from": now - timedelta(days=7),
        "window_to": now,
        **kw,
    }
    with owner() as s, s.begin():
        a = m.Alert(org_id=org.id, brand_id=bid, **row)
        s.add(a)
        s.flush()
        return a.id


def test_a_never_scanned_active_brand_is_due(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    other = make_brand(org, "Archived")
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand).where(m.Brand.id == other).values(status="archived")
        )
    assert due_scans() == [bid]


def test_a_brand_is_due_a_scan_again_after_a_day(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    for hours, due in ((20, []), (25, [bid])):
        with owner() as s, s.begin():
            s.execute(
                update(m.Brand)
                .where(m.Brand.id == bid)
                .values(
                    alerts_scanned_at=func.now()
                    - func.make_interval(0, 0, 0, 0, hours)
                )
            )
        assert due_scans() == due


def test_deliveries_are_due_only_with_a_webhook_and_a_past_attempt_time(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    past = func.now() - func.make_interval(0, 0, 0, 0, 0, 1)
    future = func.now() + func.make_interval(0, 0, 0, 0, 1)
    a_due = _alert(owner, org, bid, next_attempt_at=past)
    _alert(owner, org, bid, next_attempt_at=future)
    _alert(owner, org, bid, next_attempt_at=None)
    _alert(owner, org, bid, next_attempt_at=past, delivered_at=func.now())
    assert due_deliveries() == []  # no webhook yet
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand)
            .where(m.Brand.id == bid)
            .values(webhook_url="https://hooks.example.com/x")
        )
    assert due_deliveries() == [a_due]


def test_alert_rows_are_tenant_scoped(owner, make_org, make_brand):
    a, b = make_org("A"), make_org("B")
    aid = _alert(owner, a, make_brand(a))
    _alert(owner, b, make_brand(b))
    with tenant_session(a.id) as s:
        assert s.scalars(select(m.Alert.id)).all() == [aid]


def _brand_mentions(owner, org, obs_ids):
    """The brand named in every one of these answers."""
    with owner() as s, s.begin():
        bid = s.scalar(
            select(m.Observation.brand_id).where(m.Observation.id == obs_ids[0])
        )
        s.add_all([_mention(org, o, "brand", bid) for o in obs_ids])


def _drop_scene(owner, make_org, make_brand, before_k, after_k, n=50):
    """One prompt, n answers per 7-day window; the brand is named in
    before_k of the before answers and after_k of the after answers."""
    org = make_org()
    bid = make_brand(org, "Nike")
    p = _prompt(owner, org, bid, "best shoes")
    before = _answers(owner, org, bid, p, NOW - timedelta(days=10), n)
    after = _answers(owner, org, bid, p, NOW - timedelta(days=3), n)
    if before_k:
        _brand_mentions(owner, org, before[:before_k])
    if after_k:
        _brand_mentions(owner, org, after[:after_k])
    return org, bid


def test_mention_drop_fires_on_a_significant_drop_of_15_points(
    owner, make_org, make_brand
):
    org, bid = _drop_scene(owner, make_org, make_brand, 40, 20)  # 80% -> 40%
    with tenant_session(org.id) as s:
        found = detect_mention_drop(s, bid, NOW)
    assert len(found) == 1
    c = found[0]
    assert (c.type, c.subject_key) == ("mention_drop", "mention_rate")
    assert c.window_to == NOW and c.window_from == NOW - timedelta(days=7)
    assert c.detail["before"]["value"] == 0.8
    assert c.detail["after"]["value"] == 0.4
    assert c.title.startswith("Mention rate fell 40.0 points")


def test_mention_drop_needs_both_the_label_and_the_floor(
    owner, make_org, make_brand
):
    # The floor alone: 100/200 -> 75/200 is a significant "decrease" but
    # only 12.5 points. Assert the label, so the case really tests the floor.
    org, bid = _drop_scene(owner, make_org, make_brand, 100, 75, n=200)
    with tenant_session(org.id) as s:
        d = brand_deltas(s, bid, Filters(), DROP_DAYS, NOW)
        assert d["deltas"]["mention_rate"]["label"] == "decrease"
        assert detect_mention_drop(s, bid, NOW) == []
    # The label alone: 5/10 -> 3/10 is 20 points but not significant.
    org, bid = _drop_scene(owner, make_org, make_brand, 5, 3, n=10)
    with tenant_session(org.id) as s:
        d = brand_deltas(s, bid, Filters(), DROP_DAYS, NOW)
        assert d["deltas"]["mention_rate"]["label"] != "decrease"
        assert detect_mention_drop(s, bid, NOW) == []


def test_an_exact_15_point_drop_counts(owner, make_org, make_brand):
    # 60% -> 45% of 200: float subtraction gives -0.14999999999999997.
    org, bid = _drop_scene(owner, make_org, make_brand, 120, 90, n=200)
    with tenant_session(org.id) as s:
        d = brand_deltas(s, bid, Filters(), DROP_DAYS, NOW)
        assert d["deltas"]["mention_rate"]["label"] == "decrease"
        assert len(detect_mention_drop(s, bid, NOW)) == 1


def test_mention_drop_is_silent_when_windows_are_not_comparable(
    owner, make_org, make_brand
):
    org, bid = _drop_scene(owner, make_org, make_brand, 40, 20)
    with owner() as s, s.begin():
        obs = s.scalars(
            select(m.Observation.id).where(m.Observation.brand_id == bid)
        ).all()
        s.add_all(
            m.Extraction(
                org_id=org.id,
                observation_id=o,
                pipeline_version="1" if i % 2 else "2",
                model_used="none",
                brand_mentioned=False,
            )
            for i, o in enumerate(obs)
        )
    with tenant_session(org.id) as s:
        assert detect_mention_drop(s, bid, NOW) == []


def test_competitor_shift_yields_one_candidate_per_feed_entry(feed):  # noqa: F811
    org, bid, ids = feed
    with tenant_session(org.id) as s:
        found = detect_competitor_shift(s, bid, NOW)
    assert [(c.type, c.subject_key) for c in found] == [
        ("competitor_shift", f"{ids['a']}:up")
    ]
    c = found[0]
    assert c.detail["competitor_id"] == ids["a"]
    assert len(c.detail["prompt_ids"]) == 11
    assert 0 < len(c.detail["observation_ids"]) <= 20
    assert (
        c.title == "A was named more often on 11 prompts over the last 14 days"
    )


def _source_scene(owner, make_org, make_brand):
    """Nike (nike.com), rival Adidas (adidas.com). One prompt; answers in
    the last 7 days cite: forbes.com x6 (new), nike.com x6, adidas.com x6,
    few.com x(min-1), old.com x6 (also cited 30 days ago)."""
    org = make_org()
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host="nike.com"))
        s.add(
            m.Competitor(
                org_id=org.id,
                brand_id=bid,
                name="Adidas",
                domains=["adidas.com"],
            )
        )
    p = _prompt(owner, org, bid, "best shoes")
    old = _answers(owner, org, bid, p, NOW - timedelta(days=30), 1)
    recent = _answers(owner, org, bid, p, NOW - timedelta(days=2), 6)
    cites = [_cite(org, old[0], "old.com")]
    for d in ("forbes.com", "nike.com", "adidas.com", "old.com"):
        cites += [_cite(org, o, d) for o in recent]
    cites += [
        _cite(org, o, "few.com") for o in recent[: NEW_SOURCE_MIN_ANSWERS - 1]
    ]
    with owner() as s, s.begin():
        s.add_all(cites)
    return org, bid, recent


def test_new_source_needs_min_answers_first_seen_in_window_third_party(
    owner, make_org, make_brand
):
    org, bid, recent = _source_scene(owner, make_org, make_brand)
    with tenant_session(org.id) as s:
        found = detect_new_source(s, bid, NOW)
    assert [(c.type, c.subject_key) for c in found] == [
        ("new_source", "forbes.com")
    ]
    c = found[0]
    assert c.detail["domain"] == "forbes.com" and c.detail["answers"] == 6
    assert sorted(c.detail["observation_ids"]) == sorted(recent)
    assert c.window_from == NOW - timedelta(days=SOURCE_DAYS)
    assert c.title == (
        "forbes.com was cited in 6 answers, the first time in the last 7 days"
    )


def test_new_source_needs_a_baseline_before_the_window(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Nike")
    p = _prompt(owner, org, bid, "best shoes")
    recent = _answers(owner, org, bid, p, NOW - timedelta(days=2), 6)
    with owner() as s, s.begin():
        s.add_all(_cite(org, o, "forbes.com") for o in recent)
    with tenant_session(org.id) as s:
        assert detect_new_source(s, bid, NOW) == []  # no history yet
    _answers(owner, org, bid, p, NOW - timedelta(days=30), 1)
    with tenant_session(org.id) as s:
        found = detect_new_source(s, bid, NOW)
    assert [c.subject_key for c in found] == ["forbes.com"]


def test_scan_inserts_and_dedupes_within_the_window(
    owner, make_org, make_brand
):
    org, bid, _ = _source_scene(owner, make_org, make_brand)
    with tenant_session(org.id) as s:
        rows = scan(s, org.id, bid, NOW, deliver=False)
        assert [r.subject_key for r in rows] == ["forbes.com"]
        assert rows[0].next_attempt_at is None
    with tenant_session(org.id) as s:
        assert scan(s, org.id, bid, NOW, deliver=False) == []  # same window
        assert scan(s, org.id, bid, NOW + timedelta(days=3), deliver=True) == []
    # Later answers citing forbes.com again: it is not new any more.
    later = NOW + timedelta(days=8)
    p = _prompt(owner, org, bid, "another")
    again = _answers(owner, org, bid, p, later - timedelta(days=1), 6)
    with owner() as s, s.begin():
        s.add_all(_cite(org, o, "forbes.com") for o in again)
    with tenant_session(org.id) as s:
        assert (
            scan(s, org.id, bid, later, deliver=False) == []
        )  # not new any more
    with owner() as s:
        assert s.scalar(select(func.count(m.Alert.id))) == 1


def test_scan_marks_alerts_for_delivery_only_with_a_webhook(
    owner, make_org, make_brand
):
    org, bid, _ = _source_scene(owner, make_org, make_brand)
    with tenant_session(org.id) as s:
        (row,) = scan(s, org.id, bid, NOW, deliver=True)
        aid = row.id
    with owner() as s:
        a = s.get(m.Alert, aid)
    assert a.next_attempt_at is not None and a.delivered_at is None


def test_is_duplicate_matches_only_a_younger_alert_of_the_same_subject(
    owner, make_org, make_brand
):
    org, bid, _ = _source_scene(owner, make_org, make_brand)
    with tenant_session(org.id) as s:
        (c,) = detect_new_source(s, bid, NOW)
        assert not is_duplicate(s, bid, c)
        scan(s, org.id, bid, NOW, deliver=False)
        assert is_duplicate(s, bid, c)
    with owner() as s, s.begin():
        s.execute(update(m.Alert).values(window_to=NOW - timedelta(days=8)))
    with tenant_session(org.id) as s:
        assert not is_duplicate(s, bid, c)
