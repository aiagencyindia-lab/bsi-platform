"""Audits of the brand's own site. Only the crawlability audit so far."""

import uuid
from typing import Any

from bsi_core import models as m
from fastapi import APIRouter
from sqlalchemy import select

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
    # DISTINCT ON with id as the tie-break: two audits for the same
    # domain can share a created_at (two inserts in quick succession),
    # so ordering by created_at alone isn't a stable pick of one row.
    return list(
        c.s.scalars(
            select(m.SiteAudit)
            .join(
                m.Domain,
                (m.Domain.brand_id == m.SiteAudit.brand_id)
                & (m.Domain.host == m.SiteAudit.domain),
            )
            .where(m.SiteAudit.brand_id == brand_id)
            .order_by(
                m.SiteAudit.domain,
                m.SiteAudit.created_at.desc(),
                m.SiteAudit.id.desc(),
            )
            .distinct(m.SiteAudit.domain)
        )
    )
