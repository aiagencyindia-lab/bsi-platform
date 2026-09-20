from datetime import UTC, datetime, timedelta

import bsi_workers.worker as worker
import pytest
from bsi_core import models as m
from bsi_core.providers.base import EngineResult, ParsedAnswer
from bsi_core.scheduling import run_schedule
from bsi_core.storage import LocalRawStore
from bsi_workers.worker import (
    process_one,
    reset_stale,
    run_due_schedules,
    tick,
)
from sqlalchemy import func, select, text, update

OK = EngineResult(
    "ok",
    raw={"x": 1},
    model="fake-1",
    model_version="v1",
    params={"country": "IN"},
    cost_micros=123,
)
RETRY = EngineResult("retryable", error="429 quota", model="fake-1")
FATAL = EngineResult("fatal", error="400 bad", model="fake-1")


class FakeAdapter:
    code = "gemini"

    def __init__(self, *results):
        self.results = list(results)
        self.prompts = []

    def query(self, prompt, country, language):
        self.prompts.append((prompt, country, language))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def parse(self, raw):
        return ParsedAnswer("", [])

    def cost(self, raw):
        return 0

    def health(self):
        return True

    def rate_budget(self):
        return 60


class NoExtract:
    def prepare(self, org_id, obs_id):
        return None

    def write(self, s, obs, prepared):
        pass


no_extract = NoExtract()


@pytest.fixture
def queued(make_org, make_brand, make_observation):
    org = make_org()
    return org, make_observation(org, make_brand(org), status="queued")


def load(owner, obs_id):
    with owner() as s:
        return s.get(m.Observation, obs_id)


def make_due(owner, obs_id):
    with owner() as s, s.begin():
        s.execute(
            update(m.Observation)
            .where(m.Observation.id == obs_id)
            .values(next_attempt_at=func.now())
        )


def test_ok_path(owner, queued):
    org, obs_id = queued
    adapter = FakeAdapter(OK)
    assert process_one(adapter, LocalRawStore(), no_extract) is True
    obs = load(owner, obs_id)
    assert (obs.status, obs.model, obs.cost_micros) == ("done", "fake-1", 123)
    assert obs.params == {"country": "IN"} and obs.completed_at
    assert LocalRawStore().get(obs.raw_uri, org.id) == {"x": 1}
    assert adapter.prompts == [("best shoes", "IN", "en")]
    assert process_one(adapter, LocalRawStore(), no_extract) is False


def test_retryable_backs_off_then_fails_after_three(owner, queued):
    _, obs_id = queued
    adapter = FakeAdapter(RETRY, RETRY, RETRY)
    store = LocalRawStore()
    assert process_one(adapter, store, no_extract)
    obs = load(owner, obs_id)
    assert (obs.status, obs.attempts, obs.error) == ("retry", 1, "429 quota")
    with owner() as s:
        still_future = s.scalar(
            select(m.Observation.next_attempt_at > func.now()).where(
                m.Observation.id == obs_id
            )
        )
    assert still_future is True
    assert process_one(adapter, store, no_extract) is False  # not due yet
    for _ in range(2):
        make_due(owner, obs_id)
        assert process_one(adapter, store, no_extract)
    obs = load(owner, obs_id)
    assert (obs.status, obs.attempts) == ("failed", 3)


def wait_seconds(owner, obs_id):
    with owner() as s:
        return s.scalar(
            select(
                func.extract(
                    "epoch", m.Observation.next_attempt_at - func.now()
                )
            ).where(m.Observation.id == obs_id)
        )


def test_backoff_outlasts_a_per_minute_quota_window(owner, queued):
    # Vertex quotas reset per minute; 2 s then 4 s gave up after ~6 s.
    _, obs_id = queued
    adapter = FakeAdapter(RETRY, RETRY)
    process_one(adapter, LocalRawStore(), no_extract)
    first = wait_seconds(owner, obs_id)
    make_due(owner, obs_id)
    process_one(adapter, LocalRawStore(), no_extract)
    second = wait_seconds(owner, obs_id)
    assert 12 <= first <= 18  # 15 s +-20% jitter
    assert 48 <= second <= 72  # 60 s +-20% jitter
    assert first + second > 60


def test_archived_brand_is_not_queried(client, owner, queued):
    org, obs_id = queued
    brand_id = load(owner, obs_id).brand_id
    client.delete(f"/v1/brands/{brand_id}", headers=org.headers)
    adapter = FakeAdapter()  # any engine call would pop from an empty list
    assert process_one(adapter, LocalRawStore(), no_extract) is True
    obs = load(owner, obs_id)
    assert (obs.status, obs.error) == ("failed", "brand archived")
    assert adapter.prompts == []


def test_retry_then_success(owner, queued):
    _, obs_id = queued
    adapter = FakeAdapter(RETRY, OK)
    process_one(adapter, LocalRawStore(), no_extract)
    make_due(owner, obs_id)
    process_one(adapter, LocalRawStore(), no_extract)
    obs = load(owner, obs_id)
    assert (obs.status, obs.error) == ("done", None)


def test_fatal_fails_immediately(owner, queued):
    _, obs_id = queued
    process_one(FakeAdapter(FATAL), LocalRawStore(), no_extract)
    obs = load(owner, obs_id)
    assert (obs.status, obs.attempts) == ("failed", 1)


def test_a_raising_adapter_or_extractor_never_stops_the_loop(owner, queued):
    _, obs_id = queued

    class BadExtract(NoExtract):
        def prepare(self, org_id, obs_id):
            raise RuntimeError("boom")

    bad_extract = BadExtract()

    assert process_one(FakeAdapter(OK), LocalRawStore(), bad_extract)
    assert load(owner, obs_id).status == "retry"
    make_due(owner, obs_id)
    assert process_one(
        FakeAdapter(ValueError("x")), LocalRawStore(), no_extract
    )
    obs = load(owner, obs_id)
    assert (obs.status, obs.attempts) == ("retry", 2)


def test_worker_prepares_between_transactions(owner, queued):
    _, obs_id = queued
    from sqlalchemy import text

    seen = []

    class Watching(NoExtract):
        def prepare(self, org_id, obs_id):
            with owner() as s:
                seen.append(
                    s.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE usename = 'bsi_app' "
                            "AND datname = current_database() "
                            "AND state LIKE 'idle in transaction%'"
                        )
                    )
                )
                obs = s.get(m.Observation, obs_id)
                seen.append((obs.status, obs.raw_uri is not None))
            return None

    assert process_one(FakeAdapter(OK), LocalRawStore(), Watching())
    assert seen == [0, ("running", True)]
    assert load(owner, obs_id).status == "done"


def test_stale_running_rows_are_reset(owner, queued):
    _, obs_id = queued
    with owner() as s, s.begin():
        s.execute(
            update(m.Observation)
            .where(m.Observation.id == obs_id)
            .values(
                status="running",
                requested_at=datetime.now(UTC) - timedelta(minutes=11),
            )
        )
    assert reset_stale() == 1
    obs = load(owner, obs_id)
    assert obs.status == "retry"
    assert obs.attempts == 1


def test_stale_running_rows_fail_after_third_attempt(owner, queued):
    _, obs_id = queued
    with owner() as s, s.begin():
        s.execute(
            update(m.Observation)
            .where(m.Observation.id == obs_id)
            .values(
                status="running",
                attempts=2,
                requested_at=datetime.now(UTC) - timedelta(minutes=11),
            )
        )
    assert reset_stale() == 1
    obs = load(owner, obs_id)
    assert obs.status == "failed"
    assert obs.attempts == 3


def test_worker_serves_every_tenant(
    owner, make_org, make_brand, make_observation
):
    ids = []
    for name in ("A", "B"):
        org = make_org(name)
        ids.append(make_observation(org, make_brand(org), status="queued"))
    adapter = FakeAdapter(OK, OK)
    while process_one(adapter, LocalRawStore(), no_extract):
        pass
    assert {load(owner, i).status for i in ids} == {"done"}


def test_tick_survives_claim_failure(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(worker, "_claim", boom)
    assert tick(FakeAdapter(), LocalRawStore(), no_extract) is False


def test_tick_survives_failure_recording_failure(monkeypatch, owner, queued):
    _, obs_id = queued

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(worker, "_record_failure", boom)
    assert tick(FakeAdapter(FATAL), LocalRawStore(), no_extract) is False
    assert load(owner, obs_id).status == "running"


def _due_schedule(owner, make_org, make_brand, name):
    """An org with a brand, one active prompt and a schedule due now."""
    org = make_org(name)
    bid = make_brand(org)
    with owner() as s, s.begin():
        loc = s.scalars(select(m.Locale).where(m.Locale.brand_id == bid))
        s.add(
            m.Prompt(
                org_id=org.id,
                brand_id=bid,
                locale_id=loc.one().id,
                text="best shoes",
                status="active",
            )
        )
        sch = m.Schedule(
            org_id=org.id,
            brand_id=bid,
            cadence="daily",
            hour_utc=3,
            next_run_at=func.now() + timedelta(days=1),
        )
        s.add(sch)
    with owner() as s, s.begin():
        s.execute(
            text(
                "UPDATE schedule SET next_run_at = now() - interval '1 hour'"
                " WHERE id = :id"
            ),
            {"id": sch.id},
        )
    return sch.id, bid


def _queued(owner, bid):
    with owner() as s:
        return s.scalar(
            select(func.count()).where(
                m.Observation.brand_id == bid,
                m.Observation.status == "queued",
            )
        )


def test_run_due_schedules_serves_every_tenant(owner, make_org, make_brand):
    bids = [_due_schedule(owner, make_org, make_brand, n)[1] for n in "AB"]
    assert run_due_schedules() == 2
    assert [_queued(owner, b) for b in bids] == [2, 2]
    assert run_due_schedules() == 0


def test_one_failing_schedule_does_not_block_others(
    monkeypatch, owner, make_org, make_brand
):
    bad, _ = _due_schedule(owner, make_org, make_brand, "A")
    _, good_bid = _due_schedule(owner, make_org, make_brand, "B")

    def flaky(org_id, schedule_id):
        if schedule_id == bad:
            raise RuntimeError("boom")
        return run_schedule(org_id, schedule_id)

    monkeypatch.setattr(worker, "run_schedule", flaky)
    assert run_due_schedules() == 1
    assert _queued(owner, good_bid) == 2
