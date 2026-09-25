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


def _run(token: str) -> tuple[m.ReportRun, str]:
    with system_session() as s:
        row = s.execute(
            text("SELECT run_id, org_id FROM report_run_by_token(:t)"),
            {"t": token},
        ).first()
    if row is None:
        raise Problem(404, "Not found")
    with tenant_session(uuid.UUID(str(row.org_id))) as s:
        run = s.get(m.ReportRun, row.run_id)
        if run is None:
            raise Problem(404, "Not found")
        name = s.get_one(m.Brand, run.brand_id).name
        s.expunge(run)
    return run, name


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "brand"


@router.get("/{token}.pdf")
def public_pdf(token: Token) -> Response:
    run, name = _run(token)
    pdf = render_pdf(Document.model_validate(run.document))
    filename = f"{_slug(name)}-{run.type}-{run.period_to:%Y-%m-%d}.pdf"
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
    run, _ = _run(token)
    response.headers.update(NO_STORE)
    return run
