"""Alerts: detectors, dedupe, scan, and the due functions."""

from datetime import UTC, datetime, timedelta

from bsi_core import models as m
from bsi_core.db import system_session, tenant_session
from sqlalchemy import func, select, text, update


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
