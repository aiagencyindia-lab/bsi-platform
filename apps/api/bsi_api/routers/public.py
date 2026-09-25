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
from fastapi import APIRouter, Path, Response
from sqlalchemy import text

from ..problems import Problem
from ..schemas import ReportRunOut

router = APIRouter(prefix="/r", tags=["public"])

Token = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{20,64}$")]
NO_STORE = {"Cache-Control": "no-store"}


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
def public_pdf(token: Token) -> Response:
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
def public_run(token: Token, response: Response) -> m.ReportRun:
    run = _run(token)
    response.headers.update(NO_STORE)
    return run
