import uuid
from datetime import UTC, datetime
from typing import Any

from bsi_core import models as m
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..deps import Ctx, brand_or_404, ctx, get_or_404
from ..problems import Problem

router = APIRouter(prefix="/brands/{brand_id}/runs", tags=["runs"])
jobs_router = APIRouter(prefix="/jobs", tags=["runs"])
STATUSES = ("queued", "running", "retry", "fetched", "done", "failed")
PENDING = ("queued", "running", "retry", "fetched")


class RunIn(BaseModel):
    samples: int = Field(3, ge=1, le=10)
    retry_failed: bool = False


def _job_view(c: Ctx, job: m.Job) -> dict[str, Any]:
    q = (
        select(m.Observation.status, func.count())
        .where(m.Observation.job_id == job.id)
        .group_by(m.Observation.status)
    )
    counts = {status: n for status, n in c.s.execute(q).all()}
    view: dict[str, Any] = {s: counts.get(s, 0) for s in STATUSES}
    pending = sum(view[s] for s in PENDING)
    return {
        "id": job.id,
        "brand_id": job.brand_id,
        "scheduled_slot": job.scheduled_slot,
        "status": "running" if pending else "done",
        "total": sum(view.values()),
        **view,
    }


@router.post("", status_code=202)
def create_run(
    brand_id: uuid.UUID, body: RunIn | None = None, c: Ctx = Depends(ctx)
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    samples = (body or RunIn()).samples
    prompts = c.s.scalars(
        select(m.Prompt).where(
            m.Prompt.brand_id == brand_id, m.Prompt.status == "active"
        )
    ).all()
    if not prompts:
        raise Problem(422, "No active prompts", "Add a prompt before running.")
    engine = c.s.scalars(
        select(m.Engine).where(m.Engine.code == "gemini")
    ).one()
    slot = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)

    c.s.execute(
        pg_insert(m.Job)
        .values(org_id=c.org_id, brand_id=brand_id, scheduled_slot=slot)
        .on_conflict_do_nothing()
    )
    job = c.s.scalars(
        select(m.Job).where(
            m.Job.brand_id == brand_id,
            m.Job.kind == "run",
            m.Job.scheduled_slot == slot,
        )
    ).one()

    requeued = 0
    if (body or RunIn()).retry_failed:
        result = c.s.execute(
            update(m.Observation)
            .where(
                m.Observation.job_id == job.id,
                m.Observation.status == "failed",
            )
            .values(
                status="queued",
                attempts=0,
                error=None,
                next_attempt_at=None,
            )
        )
        requeued = result.rowcount or 0

    rows = [
        {
            "org_id": c.org_id,
            "brand_id": brand_id,
            "job_id": job.id,
            "prompt_id": p.id,
            "engine_id": engine.id,
            "locale_id": p.locale_id,
            "sample_index": i,
            "scheduled_slot": slot,
        }
        for p in prompts
        for i in range(samples)
    ]
    inserted = c.s.execute(
        pg_insert(m.Observation)
        .values(rows)
        .on_conflict_do_nothing()
        .returning(m.Observation.id)
    ).all()
    return {
        "job_id": job.id,
        "status_url": f"/v1/jobs/{job.id}",
        "enqueued": len(inserted),
        "requeued": requeued,
    }


@router.get("")
def list_runs(
    brand_id: uuid.UUID, c: Ctx = Depends(ctx)
) -> list[dict[str, Any]]:
    brand_or_404(c, brand_id)
    q = select(m.Job).where(m.Job.brand_id == brand_id)
    jobs = c.s.scalars(q.order_by(m.Job.scheduled_slot.desc()).limit(50))
    return [_job_view(c, j) for j in jobs]


@jobs_router.get("/{job_id}")
def get_job(job_id: uuid.UUID, c: Ctx = Depends(ctx)) -> dict[str, Any]:
    return _job_view(c, get_or_404(c.s, m.Job, job_id))
