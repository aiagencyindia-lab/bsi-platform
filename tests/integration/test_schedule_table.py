from datetime import UTC, datetime, timedelta

import pytest
from bsi_core import models as m
from bsi_core.db import system_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _add(owner, org, brand_id, **kw):
    fields = {
        "cadence": "daily",
        "hour_utc": 3,
        "next_run_at": datetime.now(UTC) - timedelta(minutes=1),
    } | kw
    with owner() as s, s.begin():
        sched = m.Schedule(org_id=org.id, brand_id=brand_id, **fields)
        s.add(sched)
    return sched.id


def test_due_schedules_lists_every_tenants_due_rows(
    owner, make_org, make_brand
):
    a, b = make_org("A"), make_org("B")
    later = datetime.now(UTC) + timedelta(hours=1)
    a_due = _add(owner, a, make_brand(a, "A1"))
    _add(owner, a, make_brand(a, "A2"), next_run_at=later)
    b_due = _add(owner, b, make_brand(b, "B1"))
    _add(owner, b, make_brand(b, "B2"), status="paused")

    with system_session() as s:
        rows = s.execute(text("SELECT * FROM due_schedules()")).all()
        visible = s.execute(text("SELECT count(*) FROM schedule")).scalar()

    assert {tuple(r) for r in rows} == {(a_due, a.id), (b_due, b.id)}
    assert visible == 0


@pytest.mark.parametrize(
    ("bad", "check"),
    [
        ({"cadence": "hourly"}, "ck_schedule_cadence"),
        ({"hour_utc": 24}, "ck_schedule_hour"),
        ({"samples": 0}, "ck_schedule_samples"),
        ({"status": "x"}, "ck_schedule_status"),
    ],
)
def test_schedule_checks(owner, make_org, make_brand, bad, check):
    org = make_org()
    with pytest.raises(IntegrityError, match=check):
        _add(owner, org, make_brand(org), **bad)


def test_one_schedule_per_brand(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _add(owner, org, bid)
    with pytest.raises(IntegrityError):
        _add(owner, org, bid)
