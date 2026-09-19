import uuid
from datetime import datetime
from typing import Literal

from bsi_core import models as m
from bsi_core.scheduling import first_run
from fastapi import APIRouter, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..deps import TENANT, Ctx, brand_or_404
from ..problems import Problem

router = APIRouter(prefix="/brands/{brand_id}/schedule", tags=["schedule"])


class ScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cadence: Literal["daily", "every_3_days", "weekly"]
    hour_utc: int = Field(ge=0, le=23)
    samples: int = Field(2, ge=1, le=10)
    status: Literal["active", "paused"] = "active"


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    brand_id: uuid.UUID
    cadence: str
    hour_utc: int
    samples: int
    status: str
    next_run_at: datetime
    last_run_at: datetime | None
    last_result: str | None


def _get_or_404(c: Ctx, brand_id: uuid.UUID) -> m.Schedule:
    brand_or_404(c, brand_id)
    q = select(m.Schedule).where(m.Schedule.brand_id == brand_id)
    row = c.s.scalars(q).one_or_none()
    if row is None:
        raise Problem(404, "Not found")
    return row


@router.put("", response_model=ScheduleOut)
def put_schedule(
    brand_id: uuid.UUID, body: ScheduleIn, c: Ctx = TENANT
) -> m.Schedule:
    if brand_or_404(c, brand_id).status == "archived":
        raise Problem(409, "Brand is archived", "Archived brands are not run.")
    now = c.s.scalars(select(func.now())).one()
    fields = {**body.model_dump(), "next_run_at": first_run(now, body.hour_utc)}
    # last_run_at/last_result are left alone: that run still happened.
    c.s.execute(
        pg_insert(m.Schedule)
        .values(org_id=c.org_id, brand_id=brand_id, **fields)
        .on_conflict_do_update(index_elements=["brand_id"], set_=fields)
    )
    return c.s.scalars(
        select(m.Schedule).where(m.Schedule.brand_id == brand_id)
    ).one()


@router.get("", response_model=ScheduleOut)
def get_schedule(brand_id: uuid.UUID, c: Ctx = TENANT) -> m.Schedule:
    return _get_or_404(c, brand_id)


@router.delete("", status_code=204)
def delete_schedule(brand_id: uuid.UUID, c: Ctx = TENANT) -> Response:
    c.s.delete(_get_or_404(c, brand_id))
    return Response(status_code=204)
