from datetime import UTC, datetime, timedelta, timezone

import pytest
from bsi_core.scheduling import (
    advance,
    days_to_accumulate,
    first_run,
    hour_slot,
)


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=UTC)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (at(20, 5, 30), at(20, 6)),  # before the hour
        (at(20, 6), at(21, 6)),  # at the hour: strictly after
        (at(20, 6, 1), at(21, 6)),  # after the hour
    ],
)
def test_first_run(now, expected):
    assert first_run(now, 6) == expected


def test_first_run_across_midnight():
    assert first_run(at(20, 23, 30), 0) == at(21, 0)


@pytest.mark.parametrize(
    ("cadence", "days"), [("daily", 1), ("every_3_days", 3), ("weekly", 7)]
)
def test_advance_each_cadence(cadence, days):
    now = at(20, 6, 1)
    assert advance(at(20, 6), cadence, now) == at(20, 6) + timedelta(days)


def test_advance_skips_missed_slots_without_backfill():
    # Three intervals in the past: land on the first future point.
    now = at(20, 7)
    assert advance(at(11, 6), "every_3_days", now) == at(23, 6)


def test_first_run_uses_utc_whatever_zone_now_is_in():
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime(2026, 9, 20, 10, 0, tzinfo=ist)  # 04:30 UTC
    assert first_run(now, 6) == datetime(2026, 9, 20, 6, 0, tzinfo=UTC)


def test_hour_slot_truncates_in_utc_not_the_session_zone():
    # A DB session in Asia/Kolkata returns 08:30+05:30 for 03:00 UTC;
    # truncating that locally would give 02:30 UTC and a different job.
    ist = timezone(timedelta(hours=5, minutes=30))
    due = datetime(2026, 9, 20, 8, 30, tzinfo=ist)
    assert hour_slot(due) == datetime(2026, 9, 20, 3, 0, tzinfo=UTC)
    assert hour_slot(at(20, 3, 59)) == at(20, 3)


def test_days_to_accumulate_counts_runs_not_calendar_days():
    # 30 more samples at 3 per daily run = 10 runs = 10 days.
    assert days_to_accumulate(30, "daily", 3) == 10
    # The same 10 runs on a slower cadence take proportionally longer.
    assert days_to_accumulate(30, "every_3_days", 3) == 30
    assert days_to_accumulate(30, "weekly", 3) == 70
    # A partial run still costs a whole run.
    assert days_to_accumulate(31, "daily", 3) == 11


def test_days_to_accumulate_is_zero_when_nothing_is_needed():
    assert days_to_accumulate(0, "daily", 3) == 0
    assert days_to_accumulate(-5, "daily", 3) == 0


def test_days_to_accumulate_refuses_an_unknown_cadence():
    with pytest.raises(KeyError):
        days_to_accumulate(30, "hourly", 3)
