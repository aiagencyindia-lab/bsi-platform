"""Audits of the brand: its own site's crawlability, and its Google
first pages (the Brand SERP audit)."""

import uuid
from datetime import timedelta
from typing import Any

from bsi_core import models as m
from bsi_core.config import get_settings
from bsi_core.scheduling import serp_budget_fits, serp_due
from fastapi import APIRouter
from sqlalchemy import func, select

from ..deps import TENANT, Ctx, brand_or_404
from ..schemas import QueuedOut, SerpAuditsOut, SiteAuditOut
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


@router.post("/serp", status_code=202, response_model=QueuedOut)
def queue_serp(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    return queue_suggestion(c, brand_id, "audit_serp", {})


@router.get("/serp", response_model=SerpAuditsOut)
def latest_serp(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    """The Brand SERP page's data: the latest page per (kind, country,
    language), an error row included; the latest audit_serp job, so a
    failure that wrote no rows (no credentials, budget, stale) still
    shows; whether the API process has DataForSEO credentials; the failed
    audit_serp jobs in the last 7 days; whether the org's budget has room
    for an audit (without the org's lock: this request writes nothing);
    and whether the weekly sweep would queue the brand now (serp_due)."""
    brand_or_404(c, brand_id)
    audits = list(
        c.s.scalars(
            select(m.SerpAudit)
            .where(m.SerpAudit.brand_id == brand_id)
            .order_by(
                m.SerpAudit.country,
                m.SerpAudit.language,
                m.SerpAudit.kind,
                m.SerpAudit.fetched_at.desc(),
                m.SerpAudit.id.desc(),
            )
            .distinct(
                m.SerpAudit.country, m.SerpAudit.language, m.SerpAudit.kind
            )
        )
    )
    job = c.s.scalars(
        select(m.Job)
        .where(m.Job.brand_id == brand_id, m.Job.kind == "audit_serp")
        .order_by(m.Job.created_at.desc(), m.Job.id.desc())
        .limit(1)
    ).first()
    # The last predicate of due_serp_audits() (migration 0024), on the
    # DB clock: failed audit_serp jobs created in the last 7 days.
    failed = c.s.scalar(
        select(func.count())
        .select_from(m.Job)
        .where(
            m.Job.brand_id == brand_id,
            m.Job.kind == "audit_serp",
            m.Job.status == "failed",
            m.Job.created_at > func.now() - timedelta(days=7),
        )
    )
    settings = get_settings()
    return {
        "job": job,
        "audits": audits,
        "serp_configured": bool(
            settings.dataforseo_login
            and settings.dataforseo_password.get_secret_value()
        ),
        "failed_7d": failed,
        "budget_room": serp_budget_fits(c.s, c.org_id, lock=False),
        "serp_due": serp_due(c.s, brand_id),
    }
