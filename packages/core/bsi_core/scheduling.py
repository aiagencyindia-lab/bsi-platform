"""Shared run enqueue, and the scheduler that uses it."""

import uuid
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any

from sqlalchemy import func, literal, select, text, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from . import models as m
from .config import get_settings
from .db import tenant_session
from .metrics import rate

CADENCE_DAYS = {"daily": 1, "every_3_days": 3, "weekly": 7}
DEFAULT_SAMPLES = 2
# Active prompts per organization, by plan (spec §5).
PLAN_LIMITS = {"starter": 100, "pro": 500, "agency": 2_000}
DEFAULT_LIMIT = PLAN_LIMITS["starter"]  # an unknown plan is Starter


def first_run(now: datetime, hour_utc: int) -> datetime:
    """The next hour_utc:00 UTC strictly after now."""
    now = now.astimezone(UTC)
    run = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    return run if run > now else run + timedelta(days=1)


def hour_slot(t: datetime) -> datetime:
    """The UTC hour containing t: the slot every run in that hour shares."""
    return t.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


# Days one run of each cadence covers. An unknown cadence raises rather
# than guessing, as the price tables do; the CHECK constraint keeps the
# column to these three.
_CADENCE_DAYS = {"daily": 1, "every_3_days": 3, "weekly": 7}


def days_to_accumulate(needed: int, cadence: str, samples: int) -> int:
    """Calendar days for `needed` more samples at this cadence.

    A partial run still costs a whole run, so this rounds up.
    """
    if needed <= 0:
        return 0
    runs = ceil(needed / samples)
    return runs * _CADENCE_DAYS[cadence]


def advance(next_run_at: datetime, cadence: str, now: datetime) -> datetime:
    """Add the cadence interval until the result is after now (no backfill).

    Always adds at least one interval: call it only once a run is due.
    """
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
               FILTER (WHERE o.requested_at >= day.start), 0)
      -- Scalar: a join would be fanned out by the extraction join above.
      + (SELECT coalesce(sum(j.cost_micros), 0) FROM job j, day
         WHERE j.kind <> 'run' AND j.created_at >= day.start) AS spent,
      count(*) FILTER (
        WHERE o.status IN ('queued', 'running', 'retry')) AS pending
    FROM observation o
    LEFT JOIN extraction e ON e.observation_id = o.id
    CROSS JOIN day
    """
)


def spent_and_pending(s: Session, org_id: uuid.UUID) -> tuple[int, int]:
    """Today's spend in micros and the observations still to run.

    Scoped by row-level security: call it in the org's tenant session.
    """
    # Fail closed, as budget_fits and check_active_limit do: outside the
    # org's tenant session row-level security hides every row, so this
    # would silently report zero spend and zero pending.
    tenant = s.scalar(text("SELECT current_setting('app.org_id', true)"))
    if tenant != str(org_id):
        raise RuntimeError(
            "spent_and_pending must run in the org's tenant session"
        )
    spent, pending = s.execute(_SPENT_AND_PENDING).one()
    return int(spent), int(pending)


def budget_micros(s: Session, org_id: uuid.UUID) -> int:
    """The org's daily cap in micros: its own override, else the setting."""
    override = s.get_one(m.Organization, org_id).daily_budget_usd
    budget = get_settings().daily_budget_usd if override is None else override
    return round(float(budget) * 1_000_000)


def budget_fits(
    s: Session, org_id: uuid.UUID, n_obs: int, extra_micros: int = 0
) -> bool:
    """True if n_obs more observations fit in the org's budget for today.

    extra_micros is spend about to be made outside the observations, such
    as a suggestion job's estimate.

    Call inside the org's tenant transaction. The advisory lock is held to
    the end of that transaction, so two schedules of one org can't both
    pass on the same headroom.
    """
    # Fail closed: outside the org's tenant session row-level security
    # hides every row, the sums would be zero and anything would fit.
    tenant = s.scalar(text("SELECT current_setting('app.org_id', true)"))
    if tenant != str(org_id):
        raise RuntimeError("budget_fits must run in the org's tenant session")
    s.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:org))"),
        {"org": str(org_id)},
    )
    # Row-level security scopes this to the org (unlike spend.db_micros).
    spent, pending = spent_and_pending(s, org_id)
    settings = get_settings()
    cap = budget_micros(s, org_id)
    # A paid attempt that then fails records no cost; the estimate's
    # headroom absorbs it.
    estimate = settings.obs_cost_estimate_micros
    return bool(spent + extra_micros + (pending + n_obs) * estimate <= cap)


def check_active_limit(
    s: Session, org_id: uuid.UUID, adding: int
) -> tuple[int, int] | None:
    """(current, limit) when `adding` active prompts would exceed the
    organization's plan, else None.

    Call inside the org's tenant transaction: row-level security scopes
    the count, and the advisory lock - the same one the budget takes -
    is held to the end of it, so two concurrent activations cannot both
    pass on the same headroom.
    """
    # Fail closed, as budget_fits does: the count below is scoped by
    # row-level security, so a session set to another org would count
    # the wrong prompts.
    tenant = s.scalar(text("SELECT current_setting('app.org_id', true)"))
    if tenant != str(org_id):
        raise RuntimeError("check_active_limit needs the org's session")
    s.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:org))"),
        {"org": str(org_id)},
    )
    plan = s.get_one(m.Organization, org_id).plan
    limit = PLAN_LIMITS.get(plan, DEFAULT_LIMIT)
    current = (
        s.scalar(select(func.count()).where(m.Prompt.status == "active")) or 0
    )
    return (current, limit) if current + adding > limit else None


def active_prompts(s: Session, brand_id: uuid.UUID) -> int:
    return (
        s.scalar(
            select(func.count()).where(
                m.Prompt.brand_id == brand_id, m.Prompt.status == "active"
            )
        )
        or 0
    )


def _brand_micros(prompts: int, samples: int, runs_per_day: float) -> float:
    return (
        prompts
        * samples
        * runs_per_day
        * get_settings().obs_cost_estimate_micros
    )


def daily_cost_preview(
    s: Session, org_id: uuid.UUID, brand_id: uuid.UUID
) -> dict[str, Any]:
    """Advisory estimate of a day's spend for one brand and its whole org.

    Call inside the org's tenant session: row-level security scopes both
    queries. Nothing is refused on it - budget_fits still decides at
    enqueue time, off the same estimate and the same budget.
    """
    own = s.scalars(
        select(m.Schedule).where(m.Schedule.brand_id == brand_id)
    ).one_or_none()
    samples = DEFAULT_SAMPLES if own is None else own.samples
    # A brand with no active schedule still runs on demand: one a day.
    # ponytail: a paused schedule contributes its samples at one run a day.
    runs = (
        1 / CADENCE_DAYS[own.cadence]
        if own is not None and own.status == "active"
        else 1.0
    )
    prompts = active_prompts(s, brand_id)
    brand_micros = _brand_micros(prompts, samples, runs)

    # One count per active schedule: a handful of brands per org.
    org_micros = sum(
        _brand_micros(
            active_prompts(s, sch.brand_id),
            sch.samples,
            1 / CADENCE_DAYS[sch.cadence],
        )
        for sch in s.scalars(
            select(m.Schedule).where(m.Schedule.status == "active")
        )
    )
    if own is None or own.status != "active":
        org_micros += brand_micros
    cap = budget_micros(s, org_id)
    return {
        "brand": {
            "active_prompts": prompts,
            "samples": samples,
            "runs_per_day": round(runs, 4),
            "est_daily_usd": round(brand_micros / 1_000_000, 4),
        },
        "org": {"est_daily_usd": round(org_micros / 1_000_000, 4)},
        "budget_usd": round(cap / 1_000_000, 4),
        "fits": org_micros <= cap,
    }


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


def run_schedule(org_id: uuid.UUID, schedule_id: uuid.UUID) -> str | None:
    """Run one due schedule; returns last_result, or None if it wasn't due.

    One transaction: lock the row, re-check it is due by the DB clock,
    enqueue or skip, then always advance next_run_at.
    """
    with tenant_session(org_id) as s:
        sch = s.get(m.Schedule, schedule_id, with_for_update=True)
        now = s.scalars(select(func.now())).one()
        if sch is None or sch.status != "active" or sch.next_run_at > now:
            return None
        brand = s.get_one(m.Brand, sch.brand_id)
        prompts = active_prompts(s, sch.brand_id)
        if brand.status == "archived":
            result = "skipped:brand_archived"
        elif not prompts:
            result = "skipped:no_active_prompts"
        elif not budget_fits(s, org_id, prompts * sch.samples):
            result = "skipped:budget"
        else:
            slot = hour_slot(sch.next_run_at)
            _, n = enqueue_run(s, org_id, sch.brand_id, sch.samples, slot)
            result = f"enqueued:{n}"
        sch.last_run_at = now
        sch.last_result = result
        sch.next_run_at = advance(sch.next_run_at, sch.cadence, now)
        return result


_SCHEDULE = (
    "brand_id",
    "cadence",
    "hour_utc",
    "samples",
    "status",
    "next_run_at",
    "last_run_at",
    "last_result",
)


def ops_summary(s: Session, org_id: uuid.UUID) -> dict[str, Any]:
    """What the operator page shows. Call in the org's tenant session."""
    spent, pending = spent_and_pending(s, org_id)
    queue = dict(
        s.execute(
            select(m.Observation.status, func.count()).group_by(
                m.Observation.status
            )
        )
        .tuples()
        .all()
    )
    searched, known = s.execute(
        text(
            "SELECT count(*) FILTER (WHERE search_queries > 0), "
            "count(search_queries) FROM observation "
            "WHERE status = 'done' "
            "AND requested_at >= now() - interval '7 days'"
        )
    ).one()
    failures = s.scalars(
        select(m.Observation)
        .where(m.Observation.status == "failed")
        .order_by(m.Observation.requested_at.desc())
        .limit(20)
    ).all()
    schedules = s.execute(
        select(m.Schedule, m.Brand.name)
        .join(m.Brand, m.Brand.id == m.Schedule.brand_id)
        .order_by(m.Schedule.next_run_at)
    ).all()
    estimate = get_settings().obs_cost_estimate_micros
    return {
        "spent_micros": spent,
        "pending": pending,
        "budget_micros": budget_micros(s, org_id),
        # Same headroom expression as budget_fits, computed once here so
        # the frontend never re-derives it.
        "committed_micros": spent + pending * estimate,
        "queue": queue,
        "searched": rate(searched, known),
        "failures": failures,
        "schedules": [
            {"brand_name": name, **{c: getattr(row, c) for c in _SCHEDULE}}
            for row, name in schedules
        ],
    }
