import uuid
from datetime import UTC, datetime
from typing import Any

from bsi_core import models as m
from bsi_core.config import get_settings
from bsi_core.extraction import PIPELINE_VERSION
from bsi_core.metrics import (
    Filters,
    brand_deltas,
    brand_metrics,
    brand_sov,
    failed_count,
    prompt_metrics,
)
from bsi_core.scheduling import days_to_accumulate
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from ..deps import TENANT, Ctx, brand_or_404
from ..problems import Problem
from ..schemas import DeltasOut, MetricsOut, PromptMetricsOut, SovOut

router = APIRouter(prefix="/brands/{brand_id}", tags=["metrics"])


def filters(
    engine: str | None = None,
    locale_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    prompt_ids: list[uuid.UUID] | None = Query(None),
) -> Filters:
    return Filters(engine, locale_id, date_from, date_to, prompt_ids)


@router.get("/metrics", response_model=MetricsOut)
def get_metrics(
    brand_id: uuid.UUID, f: Filters = Depends(filters), c: Ctx = TENANT
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    return _flag(dict(filters=f, **brand_metrics(c.s, brand_id, f)))


def _flag(window: dict[str, Any]) -> dict[str, Any]:
    """Mark recommendation_rate experimental, per the settings flag."""
    window["recommendation_rate"] = {
        **window["recommendation_rate"],
        "experimental": get_settings().rec_rate_experimental,
    }
    return window


def window_end(f: Filters) -> datetime:
    """The end of the compared windows. Window routes refuse date_from:
    days and date_to set both windows."""
    if f.date_from is not None:
        raise Problem(
            422, "date_from is not allowed", "days and date_to set the windows"
        )
    return f.date_to or datetime.now(UTC)


@router.get("/deltas", response_model=DeltasOut)
def get_deltas(
    brand_id: uuid.UUID,
    days: int = Query(7, ge=1, le=90),
    f: Filters = Depends(filters),
    c: Ctx = TENANT,
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    out = brand_deltas(c.s, brand_id, f, days, window_end(f))
    for w in ("before", "after"):
        _flag(out[w])
    return out


@router.get("/sov", response_model=SovOut)
def get_sov(
    brand_id: uuid.UUID, f: Filters = Depends(filters), c: Ctx = TENANT
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    return {
        "filters": f,
        "entities": brand_sov(c.s, brand_id, f),
        "n_failed": failed_count(c.s, brand_id, f),
        "pipeline_version": PIPELINE_VERSION,
        "computed_at": datetime.now(UTC),
    }


@router.get("/prompts/metrics", response_model=list[PromptMetricsOut])
def get_prompt_metrics(
    brand_id: uuid.UUID, f: Filters = Depends(filters), c: Ctx = TENANT
) -> list[dict[str, Any]]:
    brand_or_404(c, brand_id)
    rows = prompt_metrics(c.s, brand_id, f)
    # One schedule lookup for the whole table: `needs_days` is the same
    # projection as `needs_samples`, expressed in this brand's cadence.
    sch = c.s.scalars(
        select(m.Schedule).where(m.Schedule.brand_id == brand_id)
    ).first()
    for row in rows:
        needs = row["needs_samples"]
        row["needs_days"] = (
            days_to_accumulate(needs - row["n"], sch.cadence, sch.samples)
            if sch is not None and needs is not None
            else None
        )
    return rows
