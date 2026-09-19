from datetime import UTC, datetime, timedelta

import pytest
from bsi_core import models as m
from bsi_core.providers.base import EngineResult, ParsedAnswer
from bsi_core.storage import LocalRawStore
from bsi_workers.worker import process_one, reset_stale
from sqlalchemy import func, select, update

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


def no_extract(s, obs):
    pass


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

    def bad_extract(s, obs):
        raise RuntimeError("boom")

    assert process_one(FakeAdapter(OK), LocalRawStore(), bad_extract)
    assert load(owner, obs_id).status == "retry"
    make_due(owner, obs_id)
    assert process_one(
        FakeAdapter(ValueError("x")), LocalRawStore(), no_extract
    )
    obs = load(owner, obs_id)
    assert (obs.status, obs.attempts) == ("retry", 2)


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
    assert load(owner, obs_id).status == "retry"


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
