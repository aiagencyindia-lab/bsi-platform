"""Audits of the brand's own site. Only the crawlability audit so far."""

import uuid
from typing import Any

from bsi_core import models as m
from fastapi import APIRouter
from sqlalchemy import func, select

from ..deps import TENANT, Ctx, brand_or_404
from ..schemas import QueuedOut, SiteAuditOut
from .runs import queue_suggestion

router = APIRouter(prefix="/brands/{brand_id}/audits", tags=["audits"])


@router.post("/crawl", status_code=202, response_model=QueuedOut)
def queue_crawl(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    return queue_suggestion(c, brand_id, "audit_crawl", {})


@router.get("/crawl", response_model=list[SiteAuditOut])
def latest_crawl(brand_id: uuid.UUID, c: Ctx = TENANT) -> list[m.SiteAudit]:
    """The latest audit of each of the brand's currently declared
    domains. A domain later removed from `domain` no longer surfaces
    its last audit."""
    brand_or_404(c, brand_id)
    latest = (
        select(m.SiteAudit.domain, func.max(m.SiteAudit.created_at).label("at"))
        .where(m.SiteAudit.brand_id == brand_id)
        .group_by(m.SiteAudit.domain)
        .subquery()
    )
    return list(
        c.s.scalars(
            select(m.SiteAudit)
            .join(
                latest,
                (m.SiteAudit.domain == latest.c.domain)
                & (m.SiteAudit.created_at == latest.c.at),
            )
            .join(
                m.Domain,
                (m.Domain.brand_id == m.SiteAudit.brand_id)
                & (m.Domain.host == m.SiteAudit.domain),
            )
            .where(m.SiteAudit.brand_id == brand_id)
            .order_by(m.SiteAudit.domain)
        )
    )
