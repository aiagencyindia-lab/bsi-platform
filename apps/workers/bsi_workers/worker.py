"""Queue worker: claim an observation, query the engine, store, extract."""

import logging
import random
import time
import uuid
from collections.abc import Callable
from datetime import timedelta
from functools import partial

from bsi_core import models as m
from bsi_core.db import system_session, tenant_session
from bsi_core.extraction import extract, flash_lite_judge
from bsi_core.providers.base import EngineAdapter
from bsi_core.providers.gemini import GeminiGroundingAdapter
from bsi_core.storage import LocalRawStore, RawStore
from sqlalchemy import func, text
from sqlalchemy.orm import Session

log = logging.getLogger("bsi.worker")
MAX_ATTEMPTS = 3
# Wait before attempt 2 and 3. Vertex quotas reset per minute, so the two
# waits together must outlast one window; jitter spreads out a burst.
BACKOFF_SECONDS = (15, 60)
JITTER = 0.2
STALE_RESET_SECONDS = 300
ExtractFn = Callable[[Session, m.Observation], None]


def _claim() -> tuple[uuid.UUID, uuid.UUID] | None:
    with system_session() as s:
        row = s.execute(
            text("SELECT observation_id, org_id FROM claim_observation()")
        ).first()
    return (row.observation_id, row.org_id) if row else None


def reset_stale() -> int:
    with system_session() as s:
        return int(s.execute(text("SELECT reset_stale_running()")).scalar_one())


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
    adapter: EngineAdapter, store: RawStore, extract_fn: ExtractFn
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
        # The engine query runs outside any transaction; extraction below
        # (which may also call a model) runs inside the write transaction.
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
            obs.status = "fetched"
            s.flush()
            extract_fn(s, obs)
            obs.status = "done"
            obs.error = None
            obs.completed_at = func.now()
    except Exception as e:  # one bad row must never stop the loop
        log.exception("observation %s failed", obs_id)
        _record_failure(org_id, obs_id, repr(e), retryable=True)
    return True


def tick(
    adapter: EngineAdapter, store: RawStore, extract_fn: ExtractFn
) -> bool:
    """One loop step that never raises. False = idle/failed; caller sleeps."""
    try:
        return process_one(adapter, store, extract_fn)
    except Exception:
        # A row whose failure could not be recorded stays 'running';
        # reset_stale() hands it back after 10 minutes.
        log.exception("worker step failed")
        return False


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    adapter = GeminiGroundingAdapter()
    store = LocalRawStore()
    extract_fn = partial(
        extract, adapter=adapter, store=store, judge=flash_lite_judge
    )
    last_reset = -STALE_RESET_SECONDS
    while True:
        if time.monotonic() - last_reset >= STALE_RESET_SECONDS:
            try:
                log.info("reset %d stale rows", reset_stale())
            except Exception:
                log.exception("reset_stale failed")
            last_reset = time.monotonic()
        if not tick(adapter, store, extract_fn):
            time.sleep(1)
