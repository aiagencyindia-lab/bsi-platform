from datetime import UTC, datetime, timedelta

import bsi_workers.worker as worker
import pytest
from bsi_core import models as m
from bsi_core.db import system_session
from bsi_core.impact import close_window
from bsi_core.providers.base import EngineResult, ParsedAnswer
from bsi_core.scheduling import run_schedule
from bsi_core.storage import LocalRawStore
from bsi_core.suggest import LABEL_JOB_MICROS
from bsi_workers.worker import (
    close_due_impact_windows,
    process_one,
    refresh_due_recommendations,
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


def test_ok_path_stores_the_search_query_count(owner, queued):
    _, obs_id = queued
    result = EngineResult("ok", raw={"x": 1}, model="fake-1", search_queries=3)
    process_one(FakeAdapter(result), LocalRawStore(), no_extract)
    assert load(owner, obs_id).search_queries == 3


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


def _job(owner, org, brand_id, kind, status, minutes=0, **kw):
    with owner() as s, s.begin():
        job = m.Job(
            org_id=org.id,
            brand_id=brand_id,
            kind=kind,
            scheduled_slot=datetime.now(UTC) + timedelta(minutes=minutes),
            status=status,
            **kw,
        )
        s.add(job)
        s.flush()
    return job.id


def test_claim_job_takes_one_queued_non_run_job(owner, make_org, make_brand):
    from bsi_core.db import system_session

    org = make_org()
    bid = make_brand(org)
    _job(owner, org, bid, "run", None)
    _job(owner, org, bid, "run", "queued", minutes=1)
    _job(owner, org, bid, "suggest_competitors", None, minutes=2)
    wanted = _job(owner, org, bid, "suggest_prompts", "queued", minutes=3)

    with system_session() as s:
        first = s.execute(text("SELECT * FROM claim_job()")).all()
    with system_session() as s:
        second = s.execute(text("SELECT * FROM claim_job()")).all()

    assert [tuple(r) for r in first] == [(wanted, org.id, "suggest_prompts")]
    assert second == []
    with owner() as s:
        claimed = s.get(m.Job, wanted)
        assert claimed.status == "running"
        assert claimed.started_at is not None


def test_claim_job_fails_stale_running_jobs(owner, make_org, make_brand):
    from bsi_core.db import system_session

    org = make_org()
    bid = make_brand(org)
    stale = _job(
        owner,
        org,
        bid,
        "suggest_prompts",
        "running",
        started_at=datetime.now(UTC) - timedelta(minutes=11),
    )

    with system_session() as s:
        rows = s.execute(text("SELECT * FROM claim_job()")).all()

    assert rows == []
    with owner() as s:
        job = s.get(m.Job, stale)
    assert (job.status, job.error) == ("failed", "stale")


def _spender(cost=700):
    """A fake generator and embedder that report what they spend."""
    calls = []

    def generator(prompt, schema, temperature):
        calls.append("generate")
        return "{}", cost, "fake-model"

    def embedder(texts):
        calls.append("embed")
        return [[1.0] for _ in texts], 55

    return calls, generator, embedder


def _load_job(owner, job_id):
    with owner() as s:
        return s.get(m.Job, job_id)


def test_a_queued_prompts_job_runs_and_is_marked_done(
    monkeypatch, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    job_id = _job(
        owner, org, bid, "suggest_prompts", "queued", params={"count": 3}
    )
    calls, generator, embedder = _spender()
    seen = []

    def fake(org_id, brand_id, count, gen, emb):
        seen.append((org_id, brand_id, count))
        gen("p", None, 1.0)
        emb(["a"])
        return f"suggested:{count}"

    monkeypatch.setattr(worker, "suggest_prompts", fake)
    assert worker.process_job(FakeAdapter(), generator, embedder) is True
    assert seen == [(org.id, bid, 3)]
    assert calls == ["generate", "embed"]
    job = _load_job(owner, job_id)
    assert (job.status, job.error, job.cost_micros) == ("done", None, 755)
    assert worker.process_job(FakeAdapter(), generator, embedder) is False


def test_a_label_job_labels_only_unlabelled_prompts_and_adds_none(
    owner, make_org, make_brand, make_observation
):
    import json

    org = make_org()
    bid = make_brand(org)
    a = make_observation(org, bid, status="done", text="alpha")
    make_observation(org, bid, status="done", text="beta")
    with owner() as s, s.begin():
        pa = s.get(m.Observation, a).prompt_id
        s.execute(
            update(m.Prompt)
            .where(m.Prompt.id == pa)
            .values(intent="informational", topic="done")
        )
    job_id = _job(owner, org, bid, "label_prompts", "queued")
    seen = []

    def generator(prompt, schema, temperature):
        seen.append(prompt)
        return (
            json.dumps(
                {
                    "prompts": [
                        {
                            "text": "beta",
                            "intent": "comparison",
                            "topic": " Sizing ",
                        }
                    ]
                }
            ),
            700,
            "fake",
        )

    def embedder(texts):
        # prompt.embedding is vector(768): the shared _spender's [1.0]
        # vectors would not fit the column.
        return [[0.0] * 767 + [1.0] for _ in texts], 55

    assert worker.process_job(FakeAdapter(), generator, embedder) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.error) == ("done", None)
    assert job.cost_micros == 700 + 55
    assert len(seen) == 1 and "beta" in seen[0]
    assert "alpha" not in seen[0]  # alpha is labelled already
    with owner() as s:
        rows = {
            p.text: p
            for p in s.scalars(select(m.Prompt).where(m.Prompt.brand_id == bid))
        }
    assert len(rows) == 2  # nothing generated
    assert (rows["beta"].intent, rows["beta"].topic) == ("comparison", "sizing")
    assert rows["alpha"].topic == "done"
    assert (
        rows["alpha"].embedding is not None
        and rows["beta"].embedding is not None
    )


def test_an_over_budget_label_job_fails_without_calling_the_model(
    owner, make_org, make_brand
):
    from decimal import Decimal

    assert worker.JOB_ESTIMATES["label_prompts"] == LABEL_JOB_MICROS == 10_000
    org = make_org()
    bid = make_brand(org)
    # A $0.01 cap is exactly one estimate; 1 micro already spent tips it.
    _job(owner, org, bid, "suggest_prompts", "done", cost_micros=1)
    job_id = _job(owner, org, bid, "label_prompts", "queued")
    with owner() as s, s.begin():
        s.execute(
            update(m.Organization)
            .where(m.Organization.id == org.id)
            .values(daily_budget_usd=Decimal("0.01"))
        )
    calls, generator, embedder = _spender()
    assert worker.process_job(FakeAdapter(), generator, embedder) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.error, job.cost_micros) == ("failed", "budget", 0)
    assert calls == []


def test_a_failing_job_records_the_error_and_keeps_its_cost(
    monkeypatch, owner, make_org, make_brand
):
    from bsi_core.judge import JudgeFailed

    org = make_org()
    bid = make_brand(org)
    job_id = _job(owner, org, bid, "suggest_prompts", "queued", cost_micros=100)

    def boom(*args):
        raise JudgeFailed(ValueError("brand is archived"), 900)

    monkeypatch.setattr(worker, "suggest_prompts", boom)
    _, generator, embedder = _spender()
    assert worker.process_job(FakeAdapter(), generator, embedder) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.cost_micros) == ("failed", 1000)
    assert "brand is archived" in job.error


def test_a_job_failed_mid_flight_keeps_its_status(
    monkeypatch, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    job_id = _job(owner, org, bid, "suggest_prompts", "queued")

    def flip(org_id, brand_id, count, gen, emb):
        gen("p", None, 1.0)
        with owner() as s, s.begin():
            s.execute(
                update(m.Job)
                .where(m.Job.id == job_id)
                .values(status="failed", error="stale")
            )
        return "suggested:1"

    monkeypatch.setattr(worker, "suggest_prompts", flip)
    _, generator, embedder = _spender()
    assert worker.process_job(FakeAdapter(), generator, embedder) is True
    job = _load_job(owner, job_id)
    # The status is left alone, but the money it spent is still real and
    # has to stay visible to the budget guards.
    assert (job.status, job.error) == ("failed", "stale")
    assert job.cost_micros == 700


def test_an_over_budget_job_fails_without_calling_the_model(
    monkeypatch, owner, make_org, make_brand
):
    from decimal import Decimal

    org = make_org()
    bid = make_brand(org)
    job_id = _job(owner, org, bid, "suggest_prompts", "queued")
    with owner() as s, s.begin():
        s.execute(
            update(m.Organization)
            .where(m.Organization.id == org.id)
            .values(daily_budget_usd=Decimal("0.01"))
        )

    def never(*args):
        raise AssertionError("the model must not be called")

    monkeypatch.setattr(worker, "suggest_prompts", never)
    calls, generator, embedder = _spender()
    assert worker.process_job(FakeAdapter(), generator, embedder) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.error, job.cost_micros) == ("failed", "budget", 0)
    assert calls == []


def test_an_unknown_kind_fails_the_job_instead_of_the_loop(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    job_id = _job(owner, org, bid, "suggest_haircuts", "queued")
    _, generator, embedder = _spender()
    assert worker.process_job(FakeAdapter(), generator, embedder) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.error) == ("failed", "unknown kind")


def test_tick_prefers_a_job_over_a_queued_observation(
    monkeypatch, owner, make_org, make_brand, make_observation
):
    org = make_org()
    bid = make_brand(org)
    obs_id = make_observation(org, bid, status="queued")
    job_id = _job(owner, org, bid, "suggest_competitors", "queued")
    seen = []

    def fake(org_id, brand_id, adapter, gen):
        seen.append(brand_id)
        gen("p", None, 0.0)
        return "suggested:2"

    monkeypatch.setattr(worker, "suggest_competitors", fake)
    _, generator, embedder = _spender()
    # An empty adapter: an observation query would pop from an empty list.
    assert (
        tick(
            FakeAdapter(),
            LocalRawStore(),
            no_extract,
            generator=generator,
            embedder=embedder,
        )
        is True
    )
    assert seen == [bid]
    assert _load_job(owner, job_id).status == "done"
    assert load(owner, obs_id).status == "queued"


def _due_and_not_due(owner, org, bid):
    now = datetime.now(UTC)
    with owner() as s, s.begin():
        for title, ago in (("due", 15), ("open window", 1)):
            s.add(
                m.Task(
                    org_id=org.id,
                    brand_id=bid,
                    title=title,
                    status="done",
                    done_at=now - timedelta(days=ago),
                    window_days=14,
                )
            )


def test_close_due_impact_windows_serves_every_tenant(
    owner, make_org, make_brand
):
    for name in ("A", "B"):
        org = make_org(name)
        _due_and_not_due(owner, org, make_brand(org))
    assert close_due_impact_windows() == 2
    with owner() as s:
        rows = s.scalars(select(m.Task).order_by(m.Task.title)).all()
    # No observations anywhere, so each measured task honestly reports it.
    assert [(t.title, t.impact_label) for t in rows] == [
        ("due", "insufficient_data"),
        ("due", "insufficient_data"),
        ("open window", None),
        ("open window", None),
    ]


def test_a_task_without_impact_gets_no_window(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    with owner() as s, s.begin():
        t = m.Task(
            org_id=org.id,
            brand_id=bid,
            title="confirm Puma",
            status="done",
            done_at=datetime.now(UTC) - timedelta(days=30),
            window_days=14,
            measures_impact=False,
        )
        s.add(t)
        s.flush()
        tid = t.id
    with system_session() as s:
        due = s.execute(text("SELECT task_id FROM due_impact_windows()"))
        assert tid not in {r[0] for r in due}
    assert close_due_impact_windows() == 0
    assert close_window(org.id, tid) is None
    with owner() as s:
        t = s.get(m.Task, tid)
        assert (t.status, t.impact_label) == ("done", None)


def test_one_failing_impact_window_does_not_block_the_rest(
    monkeypatch, owner, make_org, make_brand
):
    for name in ("A", "B"):
        org = make_org(name)
        _due_and_not_due(owner, org, make_brand(org))
    real, calls = worker.close_window, []

    def flaky(org_id, task_id):
        calls.append(task_id)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real(org_id, task_id)

    monkeypatch.setattr(worker, "close_window", flaky)
    assert close_due_impact_windows() == 1
    assert len(calls) == 2


def _suggested_rival(owner, org, bid, name="Puma", evidence=2):
    """A suggested competitor is enough evidence for one recommendation."""
    with owner() as s, s.begin():
        s.add(
            m.Competitor(
                org_id=org.id,
                brand_id=bid,
                name=name,
                status="suggested",
                evidence=evidence,
            )
        )


def test_refresh_due_recommendations_serves_every_tenant(
    owner, make_org, make_brand
):
    ids = []
    for name in ("A", "B"):
        org = make_org(name)
        bid = make_brand(org)
        _suggested_rival(owner, org, bid)
        ids.append(bid)
    # Never refreshed, so both are due.
    assert refresh_due_recommendations() == 2
    with owner() as s:
        recs = s.scalars(select(m.Recommendation)).all()
        stamps = s.scalars(
            select(m.Brand.recs_refreshed_at).where(m.Brand.id.in_(ids))
        ).all()
    assert sorted(r.brand_id for r in recs) == sorted(ids)
    assert all(t is not None for t in stamps)
    # Stamped, so the next pass leaves them alone.
    assert refresh_due_recommendations() == 0


def test_a_brand_is_due_again_after_a_week(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _suggested_rival(owner, org, bid)
    assert refresh_due_recommendations() == 1
    for days, due in ((6, 0), (8, 1)):
        with owner() as s, s.begin():
            s.execute(
                update(m.Brand)
                .where(m.Brand.id == bid)
                .values(
                    recs_refreshed_at=func.now()
                    - func.make_interval(0, 0, 0, days)
                )
            )
        assert refresh_due_recommendations() == due


def test_an_archived_brand_is_never_refreshed(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _suggested_rival(owner, org, bid)
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand).where(m.Brand.id == bid).values(status="archived")
        )
    assert refresh_due_recommendations() == 0
    with owner() as s:
        assert s.scalars(select(m.Recommendation)).all() == []


def test_one_failing_refresh_does_not_block_the_rest(
    monkeypatch, owner, make_org, make_brand
):
    for name in ("A", "B"):
        org = make_org(name)
        _suggested_rival(owner, org, make_brand(org))
    real, calls = worker.refresh, []

    def flaky(s, org_id, brand_id):
        calls.append(brand_id)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real(s, org_id, brand_id)

    monkeypatch.setattr(worker, "refresh", flaky)
    assert refresh_due_recommendations() == 1
    assert len(calls) == 2
    with owner() as s:
        # The failed brand kept its null stamp, so it stays due.
        stamps = s.scalars(select(m.Brand.recs_refreshed_at)).all()
    assert sorted(t is None for t in stamps) == [False, True]
