"""The URL optimizer (PRD F11): score a page against a gap cluster."""

import uuid
from datetime import UTC, datetime
from typing import Any

from bsi_core import models as m
from bsi_core.gaps import clusters
from bsi_core.metrics import Filters
from fastapi import APIRouter
from sqlalchemy import select

from ..deps import TENANT, Ctx, brand_or_404, child_or_404
from ..problems import Problem
from ..schemas import PageAuditOut, PageOptimizeIn, QueuedOut
from .runs import queue_suggestion

router = APIRouter(prefix="/brands/{brand_id}/pages", tags=["pages"])


@router.post("/optimize", status_code=202, response_model=QueuedOut)
def optimize(
    brand_id: uuid.UUID, body: PageOptimizeIn, c: Ctx = TENANT
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    keys = {r["key"] for r in clusters(c.s, brand_id, Filters())}
    if body.cluster_key not in keys:
        raise Problem(
            422, "Unknown cluster", f"No cluster {body.cluster_key!r}."
        )
    # A full timestamp, not the hour: every request is its own job.
    return queue_suggestion(
        c,
        brand_id,
        "optimize_url",
        {"url": body.url, "cluster_key": body.cluster_key},
        slot=datetime.now(UTC),
    )


@router.get("", response_model=list[PageAuditOut])
def list_audits(
    brand_id: uuid.UUID, cluster_key: str | None = None, c: Ctx = TENANT
) -> list[m.PageAudit]:
    """The latest audit per (cluster, url), newest first; failed fetches
    included."""
    brand_or_404(c, brand_id)
    latest = (
        select(m.PageAudit)
        .where(m.PageAudit.brand_id == brand_id)
        .order_by(
            m.PageAudit.cluster_key,
            m.PageAudit.url,
            m.PageAudit.created_at.desc(),
            m.PageAudit.id.desc(),
        )
        .distinct(m.PageAudit.cluster_key, m.PageAudit.url)
    )
    if cluster_key is not None:
        latest = latest.where(m.PageAudit.cluster_key == cluster_key)
    rows = list(c.s.scalars(latest))
    rows.sort(key=lambda a: (a.created_at, a.id), reverse=True)
    return rows


@router.get("/{audit_id}", response_model=PageAuditOut)
def get_audit(
    brand_id: uuid.UUID, audit_id: uuid.UUID, c: Ctx = TENANT
) -> m.PageAudit:
    audit: m.PageAudit = child_or_404(c, m.PageAudit, brand_id, audit_id)
    return audit
