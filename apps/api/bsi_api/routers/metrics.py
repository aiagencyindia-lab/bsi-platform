import uuid
from datetime import UTC, datetime
from typing import Any

from bsi_core.config import get_settings
from bsi_core.extraction import PIPELINE_VERSION
from bsi_core.metrics import (
    Filters,
    brand_deltas,
    brand_metrics,
    brand_sov,
    failed_count,
)
from fastapi import APIRouter, Depends, Query

from ..deps import TENANT, Ctx, brand_or_404
from ..problems import Problem

router = APIRouter(prefix="/brands/{brand_id}", tags=["metrics"])


def filters(
    engine: str | None = None,
    locale_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    prompt_ids: list[uuid.UUID] | None = Query(None),
) -> Filters:
    return Filters(engine, locale_id, date_from, date_to, prompt_ids)


@router.get("/metrics")
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


@router.get("/deltas")
def get_deltas(
    brand_id: uuid.UUID,
    days: int = Query(7, ge=1, le=90),
    f: Filters = Depends(filters),
    c: Ctx = TENANT,
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    if f.date_from is not None:
        raise Problem(
            422, "date_from is not allowed", "days and date_to set the windows"
        )
    out = brand_deltas(c.s, brand_id, f, days, f.date_to or datetime.now(UTC))
    for w in ("before", "after"):
        _flag(out[w])
    return out


@router.get("/sov")
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
