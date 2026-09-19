from datetime import timedelta
from types import SimpleNamespace

import pytest
from bsi_core import models as m
from bsi_core import scheduling
from sqlalchemy import func, select, update


def _setup(owner, make_org, make_brand, prompts=("active", "active"), **sched):
    """An org, a brand with prompts, and a schedule due 2 hours ago."""
    org = make_org()
    bid = make_brand(org)
    with owner() as s, s.begin():
        locale = s.scalars(select(m.Locale).where(m.Locale.brand_id == bid))
        loc_id = locale.one().id
        for i, status in enumerate(prompts):
            s.add(
                m.Prompt(
                    org_id=org.id,
                    brand_id=bid,
                    locale_id=loc_id,
                    text=f"prompt {i}",
                    status=status,
                )
            )
        fields = {"cadence": "daily", "hour_utc": 3, "samples": 2} | sched
        sch = m.Schedule(
            org_id=org.id,
            brand_id=bid,
            next_run_at=func.now() - timedelta(hours=2),
            **fields,
        )
        s.add(sch)
    return org, bid, sch.id


def _state(owner, sid):
    with owner() as s:
        sch = s.get_one(m.Schedule, sid)
        now = s.scalar(select(func.now()))
        queued = s.scalar(
            select(func.count()).where(
                m.Observation.brand_id == sch.brand_id,
                m.Observation.status == "queued",
            )
        )
        return sch, now, queued


def _set_next(owner, sid, value):
    with owner() as s, s.begin():
        s.execute(
            update(m.Schedule)
            .where(m.Schedule.id == sid)
            .values(next_run_at=value)
        )


def test_due_schedule_enqueues_and_advances(owner, make_org, make_brand):
    org, bid, sid = _setup(owner, make_org, make_brand)
    before, _, _ = _state(owner, sid)

    assert scheduling.run_schedule(org.id, sid) == "enqueued:4"

    sch, now, queued = _state(owner, sid)
    assert queued == 4
    with owner() as s:
        slots = s.scalars(
            select(m.Observation.scheduled_slot).where(
                m.Observation.brand_id == bid
            )
        ).all()
        want = s.scalar(select(func.date_trunc("hour", before.next_run_at)))
    assert set(slots) == {want}
    assert sch.next_run_at > now
    assert sch.last_run_at is not None
    assert sch.last_result == "enqueued:4"


def _archive(owner, bid):
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand).where(m.Brand.id == bid).values(status="archived")
        )


@pytest.mark.parametrize(
    ("case", "result"),
    [
        ("archived", "skipped:brand_archived"),
        ("no_prompts", "skipped:no_active_prompts"),
        ("budget", "skipped:budget"),
    ],
)
def test_skips_still_advance(
    owner, make_org, make_brand, monkeypatch, case, result
):
    prompts = ("paused",) if case == "no_prompts" else ("active", "active")
    org, bid, sid = _setup(owner, make_org, make_brand, prompts=prompts)
    if case == "archived":
        _archive(owner, bid)
    if case == "budget":  # $0.10 fits 2 observations; the run needs 4
        monkeypatch.setattr(
            scheduling,
            "get_settings",
            lambda: SimpleNamespace(
                daily_budget_usd=0.1, obs_cost_estimate_micros=50_000
            ),
        )

    assert scheduling.run_schedule(org.id, sid) == result

    sch, now, queued = _state(owner, sid)
    assert queued == 0
    assert sch.next_run_at > now
    assert sch.last_result == result


def test_not_due_is_untouched(owner, make_org, make_brand):
    org, _, sid = _setup(owner, make_org, make_brand)
    _set_next(owner, sid, func.now() + timedelta(hours=1))
    before, _, _ = _state(owner, sid)

    assert scheduling.run_schedule(org.id, sid) is None

    sch, _, queued = _state(owner, sid)
    assert queued == 0
    assert sch.next_run_at == before.next_run_at
    assert sch.last_run_at is None
    assert sch.last_result is None


def test_paused_is_not_run(owner, make_org, make_brand):
    org, _, sid = _setup(owner, make_org, make_brand, status="paused")

    assert scheduling.run_schedule(org.id, sid) is None

    sch, _, queued = _state(owner, sid)
    assert queued == 0
    assert sch.last_result is None


def test_crash_and_rerun_queues_nothing_new(owner, make_org, make_brand):
    org, _, sid = _setup(owner, make_org, make_brand)
    old, _, _ = _state(owner, sid)
    assert scheduling.run_schedule(org.id, sid) == "enqueued:4"

    _set_next(owner, sid, old.next_run_at)
    assert scheduling.run_schedule(org.id, sid) == "enqueued:0"

    _, _, queued = _state(owner, sid)
    assert queued == 4


def test_stale_schedule_runs_once_then_jumps_ahead(owner, make_org, make_brand):
    org, _, sid = _setup(owner, make_org, make_brand)
    _set_next(owner, sid, func.now() - timedelta(days=10))
    old, _, _ = _state(owner, sid)

    assert scheduling.run_schedule(org.id, sid) == "enqueued:4"

    sch, now, queued = _state(owner, sid)
    assert queued == 4
    assert now < sch.next_run_at <= now + timedelta(days=1)
    assert (sch.next_run_at - old.next_run_at) % timedelta(days=1) == (
        timedelta(0)
    )
