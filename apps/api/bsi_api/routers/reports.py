"""Reports: cadence per type, manual runs, the archive, share links."""

import uuid
from datetime import UTC, datetime
from typing import Literal

from bsi_core import models as m
from bsi_core.reports import WEEKLY_DAYS, definition, generate, new_token
from fastapi import APIRouter, Query, Response
from sqlalchemy import select

from ..deps import TENANT, Ctx, brand_or_404, child_or_404
from ..schemas import CadenceIn, ReportOut, ReportRunListOut, ReportRunOut

router = APIRouter(prefix="/brands/{brand_id}/reports", tags=["reports"])

ReportType = Literal["cmo", "seo", "content", "pr", "agency"]

# The /runs routes come before /{type}: a Literal path parameter rejects
# "runs" with a 422 instead of falling through to the next route.


@router.get("", response_model=list[ReportOut])
def list_reports(
    brand_id: uuid.UUID, c: Ctx = TENANT
) -> list[dict[str, object]]:
    brand_or_404(c, brand_id)
    rows = {
        r.type: r
        for r in c.s.scalars(
            select(m.Report).where(m.Report.brand_id == brand_id)
        )
    }
    return [
        {
            "type": t,
            "cadence": rows[t].cadence if t in rows else "off",
            "generated_at": rows[t].generated_at if t in rows else None,
        }
        for t in m.REPORT_TYPES
    ]


@router.get("/runs", response_model=list[ReportRunListOut])
def list_runs(
    brand_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    c: Ctx = TENANT,
) -> list[m.ReportRun]:
    brand_or_404(c, brand_id)
    q = (
        select(m.ReportRun)
        .where(m.ReportRun.brand_id == brand_id)
        .order_by(m.ReportRun.created_at.desc(), m.ReportRun.id)
        .limit(limit)
    )
    return list(c.s.scalars(q))


@router.get("/runs/{run_id}", response_model=ReportRunOut)
def get_run(
    brand_id: uuid.UUID, run_id: uuid.UUID, c: Ctx = TENANT
) -> m.ReportRun:
    run: m.ReportRun = child_or_404(c, m.ReportRun, brand_id, run_id)
    return run


@router.post("/runs/{run_id}/share", response_model=ReportRunOut)
def share_run(
    brand_id: uuid.UUID, run_id: uuid.UUID, c: Ctx = TENANT
) -> m.ReportRun:
    run: m.ReportRun = child_or_404(c, m.ReportRun, brand_id, run_id)
    run.share_token = new_token()
    return run


@router.delete("/runs/{run_id}/share", status_code=204)
def revoke_run(
    brand_id: uuid.UUID, run_id: uuid.UUID, c: Ctx = TENANT
) -> Response:
    run: m.ReportRun = child_or_404(c, m.ReportRun, brand_id, run_id)
    run.share_token = None
    return Response(status_code=204)


@router.put("/{type}", response_model=ReportOut)
def set_cadence(
    brand_id: uuid.UUID, type: ReportType, body: CadenceIn, c: Ctx = TENANT
) -> m.Report:
    brand_or_404(c, brand_id)
    rep = definition(c.s, c.org_id, brand_id, type)
    if rep.cadence == "off" and body.cadence != "off":
        # Due at once: the first scheduled run follows within a minute.
        rep.generated_at = None
    rep.cadence = body.cadence
    return rep


@router.post("/{type}/runs", status_code=201, response_model=ReportRunOut)
def run_now(
    brand_id: uuid.UUID, type: ReportType, c: Ctx = TENANT
) -> m.ReportRun:
    """Generate now, with the weekly window. SQL only, so it runs inline.
    Does not stamp report.generated_at: an operator's click must not
    defer the scheduled run."""
    brand_or_404(c, brand_id)
    return generate(
        c.s,
        c.org_id,
        brand_id,
        type,
        days=WEEKLY_DAYS,
        to=datetime.now(UTC),
        source="manual",
    )
