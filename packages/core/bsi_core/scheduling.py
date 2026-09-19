"""Shared run enqueue, and the scheduler that uses it."""

import uuid
from datetime import datetime

from sqlalchemy import func, literal, select, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from . import models as m


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
