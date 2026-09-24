"""Competitor intelligence: per-entity metrics, deltas, change feed,
rival site crawls."""

import uuid
from typing import Any

from bsi_core.competitors import (
    entity_deltas,
    entity_metrics,
    visibility_changes,
)
from bsi_core.metrics import Filters
from bsi_core.rivals import site_changes
from fastapi import APIRouter, Depends, Query

from ..deps import TENANT, Ctx, brand_or_404
from ..schemas import (
    ChangesOut,
    EntityDeltasOut,
    EntityMetricsOut,
    QueuedOut,
    SiteChangesOut,
)
from .metrics import _flag, filters, window_end
from .runs import queue_suggestion

router = APIRouter(prefix="/brands/{brand_id}", tags=["competitors"])


@router.get("/competitors/metrics", response_model=list[EntityMetricsOut])
def get_entity_metrics(
    brand_id: uuid.UUID, f: Filters = Depends(filters), c: Ctx = TENANT
) -> list[dict[str, Any]]:
    brand_or_404(c, brand_id)
    return [_flag(r) for r in entity_metrics(c.s, brand_id, f)]


@router.get("/competitors/deltas", response_model=EntityDeltasOut)
def get_entity_deltas(
    brand_id: uuid.UUID,
    days: int = Query(7, ge=1, le=90),
    f: Filters = Depends(filters),
    c: Ctx = TENANT,
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    out = entity_deltas(c.s, brand_id, f, days, window_end(f))
    for w in ("before", "after"):
        out[w]["entities"] = [_flag(r) for r in out[w]["entities"]]
    return out


@router.get("/competitors/changes", response_model=ChangesOut)
def get_changes(
    brand_id: uuid.UUID,
    days: int = Query(14, ge=1, le=90),
    f: Filters = Depends(filters),
    c: Ctx = TENANT,
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    return visibility_changes(c.s, brand_id, f, days, window_end(f))


@router.post("/competitors/crawl", status_code=202, response_model=QueuedOut)
def queue_rival_crawl(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    return queue_suggestion(c, brand_id, "crawl_rivals", {})


@router.get("/competitors/site-changes", response_model=SiteChangesOut)
def get_site_changes(
    brand_id: uuid.UUID,
    days: int = Query(14, ge=1, le=90),
    f: Filters = Depends(filters),
    c: Ctx = TENANT,
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    return site_changes(c.s, brand_id, days, window_end(f))
