"""Shared run enqueue, and the scheduler that uses it."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, literal, select, text, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from . import models as m
from .config import get_settings

CADENCE_DAYS = {"daily": 1, "every_3_days": 3, "weekly": 7}


def first_run(now: datetime, hour_utc: int) -> datetime:
    """The next hour_utc:00 UTC strictly after now."""
    run = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    return run if run > now else run + timedelta(days=1)


def advance(next_run_at: datetime, cadence: str, now: datetime) -> datetime:
    """Add the cadence interval until the result is after now (no backfill)."""
    step = timedelta(days=CADENCE_DAYS[cadence])
    run = next_run_at + step
    while run <= now:
        run += step
    return run


_SPENT_AND_PENDING = text(
    """
    WITH day AS (
      SELECT date_trunc('day', now() AT TIME ZONE 'UTC')
             AT TIME ZONE 'UTC' AS start)
    SELECT
      coalesce(sum(o.cost_micros + coalesce(e.cost_micros, 0))
               FILTER (WHERE o.requested_at >= day.start), 0) AS spent,
      count(*) FILTER (
        WHERE o.status IN ('queued', 'running', 'retry')) AS pending
    FROM observation o
    LEFT JOIN extraction e ON e.observation_id = o.id
    CROSS JOIN day
    """
)


def budget_fits(s: Session, org_id: uuid.UUID, n_obs: int) -> bool:
    """True if n_obs more observations fit in the org's budget for today.

    Call inside the org's tenant transaction. The advisory lock is held to
    the end of that transaction, so two schedules of one org can't both
    pass on the same headroom.
    """
    s.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:org))"),
        {"org": str(org_id)},
    )
    # Row-level security scopes this to the org (unlike spend.db_micros).
    spent, pending = s.execute(_SPENT_AND_PENDING).one()
    settings = get_settings()
    cap = round(settings.daily_budget_usd * 1_000_000)
    # A paid attempt that then fails records no cost; the estimate's
    # headroom absorbs it.
    estimate = settings.obs_cost_estimate_micros
    return bool(spent + (pending + n_obs) * estimate <= cap)


def active_prompts(s: Session, brand_id: uuid.UUID) -> int:
    return (
        s.scalar(
            select(func.count()).where(
                m.Prompt.brand_id == brand_id, m.Prompt.status == "active"
            )
        )
        or 0
    )


def enqueue_run(
    s: Session,
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    samples: int,
    slot: datetime,
) -> tuple[m.Job, int]:
    """Find or create the slot's job and queue every active prompt x sample.

    Idempotent: the job and observation unique keys make a repeat a no-op.
    Returns the job and how many observations were newly queued.
    """
    active = (m.Prompt.brand_id == brand_id, m.Prompt.status == "active")
    engine = s.scalars(select(m.Engine).where(m.Engine.code == "gemini")).one()

    s.execute(
        pg_insert(m.Job)
        .values(org_id=org_id, brand_id=brand_id, scheduled_slot=slot)
        .on_conflict_do_nothing()
    )
    job = s.scalars(
        select(m.Job).where(
            m.Job.brand_id == brand_id,
            m.Job.kind == "run",
            m.Job.scheduled_slot == slot,
        )
    ).one()

    # Built in the database: one VALUES row per observation hit Postgres's
    # 65,535 bind-parameter cap at 8,192 observations.
    sample = (
        func.generate_series(0, samples - 1).table_valued("n").render_derived()
    )
    rows = (
        select(
            m.Prompt.org_id,
            m.Prompt.brand_id,
            literal(job.id),
            m.Prompt.id,
            literal(engine.id),
            m.Prompt.locale_id,
            sample.c.n,
            literal(slot),
        )
        .join(sample, true())  # every active prompt x every sample index
        .where(*active)
    )
    inserted = s.execute(
        pg_insert(m.Observation)
        .from_select(
            [
                "org_id",
                "brand_id",
                "job_id",
                "prompt_id",
                "engine_id",
                "locale_id",
                "sample_index",
                "scheduled_slot",
            ],
            rows,
        )
        .on_conflict_do_nothing()
        .returning(m.Observation.id)
    ).all()
    return job, len(inserted)
