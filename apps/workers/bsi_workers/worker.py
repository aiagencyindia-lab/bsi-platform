"""Queue worker: claim an observation, query the engine, store, extract."""

import logging
import random
import time
import uuid
from datetime import timedelta
from typing import Any, Protocol

from bsi_core import models as m
from bsi_core.config import get_settings
from bsi_core.db import system_session, tenant_session
from bsi_core.extraction import Extractor
from bsi_core.impact import close_window
from bsi_core.judge import JUDGE_PRICES, JUDGES, generate
from bsi_core.providers.base import EngineAdapter
from bsi_core.providers.gemini import GeminiGroundingAdapter
from bsi_core.scheduling import budget_fits, run_schedule
from bsi_core.storage import LocalRawStore, RawStore
from bsi_core.suggest import (
    COMPETITOR_JOB_MICROS,
    EMBED_PRICES,
    PROMPT_JOB_MICROS,
    embed,
    suggest_competitors,
    suggest_prompts,
)
from sqlalchemy import func, text
from sqlalchemy.orm import Session

log = logging.getLogger("bsi.worker")
MAX_ATTEMPTS = 3
# Wait before attempt 2 and 3. Vertex quotas reset per minute, so the two
# waits together must outlast one window; jitter spreads out a burst.
BACKOFF_SECONDS = (15, 60)
JITTER = 0.2
STALE_RESET_SECONDS = 300
SCHEDULE_CHECK_SECONDS = 60
# What a suggestion job reserves before it spends (spec §5).
JOB_ESTIMATES = {
    "suggest_prompts": PROMPT_JOB_MICROS,
    "suggest_competitors": COMPETITOR_JOB_MICROS,
}


class ExtractorLike(Protocol):
    def prepare(self, org_id: uuid.UUID, obs_id: uuid.UUID) -> Any: ...

    def write(self, s: Session, obs: m.Observation, prepared: Any) -> None: ...


def _claim() -> tuple[uuid.UUID, uuid.UUID] | None:
    with system_session() as s:
        row = s.execute(
            text("SELECT observation_id, org_id FROM claim_observation()")
        ).first()
    return (row.observation_id, row.org_id) if row else None


def reset_stale() -> int:
    with system_session() as s:
        return int(s.execute(text("SELECT reset_stale_running()")).scalar_one())


def run_due_schedules() -> int:
    """Run the due schedules; returns how many ran.

    One schedule's failure never stops the others. Listing them can
    raise (a dead DB); main() logs that and carries on.
    """
    with system_session() as s:
        due = s.execute(
            text("SELECT schedule_id, org_id FROM due_schedules()")
        ).all()
    ran = 0
    for schedule_id, org_id in due:
        try:
            result = run_schedule(org_id, schedule_id)
            log.info("schedule %s: %s", schedule_id, result)
            ran += result is not None
        except Exception:
            log.exception("schedule %s failed", schedule_id)
    return ran


def close_due_impact_windows() -> int:
    """Measure every task whose window has closed; returns how many.

    One task's failure never stops the others, as with schedules.
    """
    with system_session() as s:
        due = s.execute(
            text("SELECT task_id, org_id FROM due_impact_windows()")
        ).all()
    closed = 0
    for task_id, org_id in due:
        try:
            label = close_window(org_id, task_id)
            log.info("task %s impact: %s", task_id, label)
            closed += label is not None
        except Exception:
            log.exception("task %s impact failed", task_id)
    return closed


def _record_failure(
    org_id: uuid.UUID, obs_id: uuid.UUID, error: str, retryable: bool
) -> None:
    with tenant_session(org_id) as s:
        obs = s.get_one(m.Observation, obs_id)
        obs.attempts += 1
        obs.error = error[:2000]
        if retryable and obs.attempts < MAX_ATTEMPTS:
            wait = BACKOFF_SECONDS[obs.attempts - 1]
            wait *= random.uniform(1 - JITTER, 1 + JITTER)
            obs.status = "retry"
            obs.next_attempt_at = func.now() + timedelta(seconds=wait)
        else:
            obs.status = "failed"
            obs.completed_at = func.now()


def process_one(
    adapter: EngineAdapter, store: RawStore, extractor: ExtractorLike
) -> bool:
    claimed = _claim()
    if claimed is None:
        return False
    obs_id, org_id = claimed
    try:
        with tenant_session(org_id) as s:
            obs = s.get_one(m.Observation, obs_id)
            archived = s.get_one(m.Brand, obs.brand_id).status == "archived"
            prompt = s.get_one(m.Prompt, obs.prompt_id).text
            locale = s.get_one(m.Locale, obs.locale_id)
            country, language = locale.country, locale.language
        if archived:  # archived after enqueue: don't spend on it
            _record_failure(org_id, obs_id, "brand archived", retryable=False)
            return True
        # The engine query and the judge (inside prepare) both run with no
        # transaction open. The row stays 'running' until the final write,
        # so a crash in between is recovered by reset_stale().
        result = adapter.query(prompt, country, language)
        if result.kind != "ok" or result.raw is None:
            _record_failure(
                org_id,
                obs_id,
                result.error or "empty result",
                result.kind == "retryable",
            )
            return True
        with tenant_session(org_id) as s:
            obs = s.get_one(m.Observation, obs_id)
            obs.raw_uri = store.put(org_id, obs_id, result.raw)
            obs.model = result.model
            obs.model_version = result.model_version
            obs.params = result.params
            obs.cost_micros = result.cost_micros
            obs.search_queries = result.search_queries
        prepared = extractor.prepare(org_id, obs_id)
        with tenant_session(org_id) as s:
            obs = s.get_one(m.Observation, obs_id)
            extractor.write(s, obs, prepared)
            obs.status = "done"
            obs.error = None
            obs.completed_at = func.now()
    except Exception as e:  # one bad row must never stop the loop
        log.exception("observation %s failed", obs_id)
        _record_failure(org_id, obs_id, repr(e), retryable=True)
    return True


class _Meter:
    """Counts what one job spends, wrapping the work it is given.

    The suggestion jobs return only a summary string: `JudgeFailed`
    carries the cost of a failure, so a success has to be counted here.
    Unmetered adapter methods (`parse`) are delegated through.
    """

    def __init__(
        self, adapter: EngineAdapter, generator: Any, embedder: Any
    ) -> None:
        self.micros = 0
        self._adapter = adapter
        self._generator = generator
        self._embedder = embedder

    def __getattr__(self, name: str) -> Any:
        return getattr(self._adapter, name)

    def query(self, prompt: str, country: str, language: str) -> Any:
        result = self._adapter.query(prompt, country, language)
        self.micros += result.cost_micros
        return result

    def generate(self, prompt: str, schema: Any, temperature: float) -> Any:
        raw, cost, model = self._generator(prompt, schema, temperature)
        self.micros += cost
        return raw, cost, model

    def embed(self, texts: list[str]) -> Any:
        vectors, cost = self._embedder(texts)
        self.micros += cost
        return vectors, cost


def _claim_job() -> tuple[uuid.UUID, uuid.UUID, str] | None:
    with system_session() as s:
        row = s.execute(
            text("SELECT job_id, org_id, kind FROM claim_job()")
        ).first()
    return (row.job_id, row.org_id, row.kind) if row else None


def _finish_job(
    org_id: uuid.UUID,
    job_id: uuid.UUID,
    status: str,
    error: str | None,
    spent: int,
) -> None:
    """Record the outcome, unless someone else already moved the job.

    A stale job is failed by claim_job() while this attempt is still
    running; this attempt's outcome is then discarded, not written over
    whatever moved it. The spend is recorded either way: the money was
    real, and both budget guards read it from this column.
    """
    with tenant_session(org_id) as s:
        job = s.get(m.Job, job_id, with_for_update=True)
        if job is None:
            return
        job.cost_micros += spent
        if job.status != "running":
            log.warning("job %s moved mid-flight: discarding", job_id)
            return
        job.status = status
        job.error = error


def process_job(adapter: EngineAdapter, generator: Any, embedder: Any) -> bool:
    """Run one claimed suggestion job. False = nothing was queued."""
    claimed = _claim_job()
    if claimed is None:
        return False
    job_id, org_id, kind = claimed
    if kind not in JOB_ESTIMATES:
        _finish_job(org_id, job_id, "failed", "unknown kind", 0)
        return True
    with tenant_session(org_id) as s:
        job = s.get_one(m.Job, job_id)
        brand_id, params = job.brand_id, job.params
        fits = budget_fits(s, org_id, 0, extra_micros=JOB_ESTIMATES[kind])
    if not fits:
        _finish_job(org_id, job_id, "failed", "budget", 0)
        return True
    # Every model call below runs with no transaction open; the row stays
    # 'running' until the final write.
    meter = _Meter(adapter, generator, embedder)
    try:
        if kind == "suggest_prompts":
            result = suggest_prompts(
                org_id,
                brand_id,
                int(params.get("count", 0)),
                meter.generate,
                meter.embed,
            )
        else:
            result = suggest_competitors(
                org_id, brand_id, meter, meter.generate
            )
        log.info("job %s: %s", job_id, result)
        _finish_job(org_id, job_id, "done", None, meter.micros)
    except Exception as e:  # one bad job must never stop the loop
        log.exception("job %s failed", job_id)
        # repr(JudgeFailed) already carries the cause's message, so an
        # archived brand reads as such and is never retried.
        _finish_job(
            org_id,
            job_id,
            "failed",
            repr(e)[:2000],
            getattr(e, "cost_micros", 0),
        )
    return True


def tick(
    adapter: EngineAdapter,
    store: RawStore,
    extractor: ExtractorLike,
    *,
    generator: Any = generate,
    embedder: Any = embed,
) -> bool:
    """One loop step that never raises. False = idle/failed; caller sleeps.

    A job is claimed before an observation: jobs are rare, user-facing
    and about a minute long, so a 9,000-observation run must not delay
    one for hours.
    """
    try:
        return process_job(adapter, generator, embedder) or process_one(
            adapter, store, extractor
        )
    except Exception:
        # A row whose failure could not be recorded stays 'running';
        # reset_stale() hands it back after 10 minutes.
        log.exception("worker step failed")
        return False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    settings = get_settings()
    JUDGE_PRICES[settings.extract_model]  # unpriced judge: fail at start
    EMBED_PRICES[settings.embed_model]  # unpriced embedder: same
    adapter = GeminiGroundingAdapter()
    store = LocalRawStore()
    extractor = Extractor(adapter, store, JUDGES[settings.judge_mode])
    last_reset = -STALE_RESET_SECONDS
    last_schedule_check = -SCHEDULE_CHECK_SECONDS
    while True:
        if time.monotonic() - last_reset >= STALE_RESET_SECONDS:
            try:
                log.info("reset %d stale rows", reset_stale())
            except Exception:
                log.exception("reset_stale failed")
            last_reset = time.monotonic()
        if time.monotonic() - last_schedule_check >= SCHEDULE_CHECK_SECONDS:
            try:
                log.info("ran %d due schedules", run_due_schedules())
            except Exception:
                log.exception("run_due_schedules failed")
            try:
                log.info("closed %d impact windows", close_due_impact_windows())
            except Exception:
                log.exception("close_due_impact_windows failed")
            last_schedule_check = time.monotonic()
        if not tick(adapter, store, extractor):
            time.sleep(1)
