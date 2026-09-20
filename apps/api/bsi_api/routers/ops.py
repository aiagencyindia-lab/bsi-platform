import uuid
from datetime import datetime
from typing import Any

from bsi_core.scheduling import ops_summary
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from ..deps import TENANT, Ctx
from ..schemas import Rate

router = APIRouter(prefix="/ops", tags=["ops"])


class FailureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    brand_id: uuid.UUID
    prompt_id: uuid.UUID
    error: str | None
    attempts: int
    requested_at: datetime


class ScheduleRow(BaseModel):
    brand_id: uuid.UUID
    brand_name: str
    cadence: str
    hour_utc: int
    samples: int
    status: str
    next_run_at: datetime
    last_run_at: datetime | None
    last_result: str | None


class OpsOut(BaseModel):
    spent_micros: int
    pending: int
    budget_micros: int
    committed_micros: int
    queue: dict[str, int]
    searched: Rate
    failures: list[FailureOut]
    schedules: list[ScheduleRow]


@router.get("", response_model=OpsOut)
def get_ops(c: Ctx = TENANT) -> dict[str, Any]:
    return ops_summary(c.s, c.org_id)
