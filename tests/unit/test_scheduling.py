from datetime import UTC, datetime, timedelta, timezone

import pytest
from bsi_core.scheduling import advance, first_run


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
