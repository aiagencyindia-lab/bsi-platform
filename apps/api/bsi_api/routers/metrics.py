import uuid
from datetime import UTC, datetime
from typing import Any

from bsi_core.extraction import PIPELINE_VERSION
from bsi_core.metrics import Filters, brand_metrics, brand_sov, failed_count
from fastapi import APIRouter, Depends, Query

from ..deps import Ctx, brand_or_404, ctx

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
    brand_id: uuid.UUID, f: Filters = Depends(filters), c: Ctx = Depends(ctx)
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    return {"filters": f, **brand_metrics(c.s, brand_id, f)}


@router.get("/sov")
def get_sov(
    brand_id: uuid.UUID, f: Filters = Depends(filters), c: Ctx = Depends(ctx)
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    return {
        "filters": f,
        "entities": brand_sov(c.s, brand_id, f),
        "n_failed": failed_count(c.s, brand_id, f),
        "pipeline_version": PIPELINE_VERSION,
        "computed_at": datetime.now(UTC),
    }
