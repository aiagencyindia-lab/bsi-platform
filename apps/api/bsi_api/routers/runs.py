import uuid
from datetime import UTC, datetime
from typing import Any

from bsi_core import models as m
from bsi_core.scheduling import active_prompts, enqueue_run, hour_slot
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update

from ..deps import TENANT, Ctx, brand_or_404, get_or_404
from ..problems import Problem

router = APIRouter(prefix="/brands/{brand_id}/runs", tags=["runs"])
jobs_router = APIRouter(prefix="/jobs", tags=["runs"])
STATUSES = ("queued", "running", "retry", "fetched", "done", "failed")
PENDING = ("queued", "running", "retry", "fetched")


class RunIn(BaseModel):
    # A misspelt field would otherwise silently fall back to the defaults.
    model_config = ConfigDict(extra="forbid")
    samples: int = Field(2, ge=1, le=10)
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
    brand_id: uuid.UUID, body: RunIn | None = None, c: Ctx = TENANT
) -> dict[str, Any]:
    if brand_or_404(c, brand_id).status == "archived":
        raise Problem(409, "Brand is archived", "Archived brands are not run.")
    body = body or RunIn()
    if not active_prompts(c.s, brand_id):
        raise Problem(422, "No active prompts", "Add a prompt before running.")
    slot = hour_slot(datetime.now(UTC))
    job, enqueued = enqueue_run(c.s, c.org_id, brand_id, body.samples, slot)

    requeued = 0
    if body.retry_failed:
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
    return {
        "job_id": job.id,
        "status_url": f"/v1/jobs/{job.id}",
        "enqueued": enqueued,
        "requeued": requeued,
    }


@router.get("")
def list_runs(brand_id: uuid.UUID, c: Ctx = TENANT) -> list[dict[str, Any]]:
    brand_or_404(c, brand_id)
    q = select(m.Job).where(m.Job.brand_id == brand_id)
    jobs = c.s.scalars(q.order_by(m.Job.scheduled_slot.desc()).limit(50))
    return [_job_view(c, j) for j in jobs]


@jobs_router.get("/{job_id}")
def get_job(job_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    return _job_view(c, get_or_404(c.s, m.Job, job_id))
