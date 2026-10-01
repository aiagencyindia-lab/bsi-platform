"""Share links: a report run by its token, no API key.

The only cross-tenant read is report_run_by_token(); the run itself is
loaded through a tenant session, so RLS stays in force. The PDF is
rendered after the session closes."""

import re
import uuid
from typing import Annotated

from bsi_core import models as m
from bsi_core.db import system_session, tenant_session
from bsi_core.pdf import render_pdf
from bsi_core.reports import Document
from fastapi import APIRouter, Path, Request, Response
from sqlalchemy import text

from ..problems import Problem
from ..schemas import ReportRunOut

router = APIRouter(prefix="/r", tags=["public"])

Token = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{20,64}$")]
NO_STORE = {"Cache-Control": "no-store"}
# One budget per share token across both public routes (slice 31).
PUBLIC_LIMIT = 60
PUBLIC_WINDOW_SECONDS = 60


def _limit(token: str, request: Request) -> None:
    """429 with Retry-After once a token has used its window's budget.
    Called first in each route, after path validation, so a malformed
    token is never counted."""
    wait = request.app.state.public_limiter.check(token)
    if wait is not None:
        raise Problem(
            429, "Too many requests", headers={"Retry-After": str(wait)}
        )


def _run(token: str) -> m.ReportRun:
    with system_session() as s:
        row = s.execute(
            text("SELECT run_id, org_id FROM report_run_by_token(:t)"),
            {"t": token},
        ).first()
    if row is None:
        raise Problem(404, "Not found")
    with tenant_session(uuid.UUID(str(row.org_id))) as s:
        run = s.get(m.ReportRun, row.run_id)
        # Revoked or re-shared between the token lookup and this read.
        if run is None or run.share_token != token:
            raise Problem(404, "Not found")
        s.expunge(run)
    return run


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "brand"


@router.get("/{token}.pdf")
def public_pdf(token: Token, request: Request) -> Response:
    _limit(token, request)
    run = _run(token)
    doc = Document.model_validate(run.document)
    pdf = render_pdf(doc)
    # The stored brand name: a later rename keeps the old run's filename.
    filename = f"{_slug(doc.brand)}-{run.type}-{run.period_to:%Y-%m-%d}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            **NO_STORE,
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/{token}", response_model=ReportRunOut)
def public_run(
    token: Token, request: Request, response: Response
) -> m.ReportRun:
    _limit(token, request)
    run = _run(token)
    response.headers.update(NO_STORE)
    return run
