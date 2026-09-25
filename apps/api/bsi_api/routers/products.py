"""The product-title wedge (PRD F16): catalogue import, the run, export."""

import csv
import io
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from bsi_core import models as m
from bsi_core.products import (
    CSV_MAX_BYTES,
    EXPORT_COLUMNS,
    CatalogueCap,
    export_rows,
    parse_csv,
    upsert,
)
from fastapi import APIRouter, Body, Query, Response
from sqlalchemy import delete, func, select

from ..deps import TENANT, Ctx, brand_or_404
from ..problems import Problem
from ..schemas import FeedIn, ImportOut, ProductOut, ProductRunsOut, QueuedOut
from .runs import queue_suggestion

router = APIRouter(prefix="/brands/{brand_id}/products", tags=["products"])
RUN_KINDS = ("product_run", "import_feed")


def _count(c: Ctx, brand_id: uuid.UUID) -> int:
    return int(
        c.s.scalar(
            select(func.count())
            .select_from(m.Product)
            .where(m.Product.brand_id == brand_id)
        )
        or 0
    )


@router.get("", response_model=list[ProductOut])
def list_products(
    brand_id: uuid.UUID,
    limit: int = Query(1000, ge=1, le=1000),
    c: Ctx = TENANT,
) -> list[m.Product]:
    brand_or_404(c, brand_id)
    q = (
        select(m.Product)
        .where(m.Product.brand_id == brand_id)
        .order_by(m.Product.title, m.Product.id)
        .limit(limit)
    )
    return list(c.s.scalars(q))


@router.get("/export.csv")
def export_csv(brand_id: uuid.UUID, c: Ctx = TENANT) -> Response:
    brand_or_404(c, brand_id)
    q = (
        select(m.Product)
        .where(m.Product.brand_id == brand_id)
        .order_by(m.Product.title, m.Product.id)
    )
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(EXPORT_COLUMNS)
    writer.writerows(export_rows(c.s.scalars(q)))
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="products-{brand_id}.csv"'
            )
        },
    )


@router.get("/runs", response_model=ProductRunsOut)
def list_runs(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    jobs = list(
        c.s.scalars(
            select(m.Job)
            .where(m.Job.brand_id == brand_id, m.Job.kind.in_(RUN_KINDS))
            .order_by(m.Job.created_at.desc(), m.Job.id)
            .limit(20)
        )
    )
    latest = next((j for j in jobs if j.kind == "product_run"), None)
    done = 0
    if latest is not None:
        done = int(
            c.s.scalar(
                select(func.count())
                .select_from(m.Product)
                .where(
                    m.Product.brand_id == brand_id,
                    m.Product.job_id == latest.id,
                )
            )
            or 0
        )
    return {"jobs": jobs, "done": done, "total": _count(c, brand_id)}


@router.post("/import/csv", status_code=201, response_model=ImportOut)
def import_csv(
    brand_id: uuid.UUID,
    body: Annotated[bytes, Body(media_type="text/csv")],
    c: Ctx = TENANT,
) -> dict[str, int]:
    brand_or_404(c, brand_id)
    if len(body) > CSV_MAX_BYTES:
        raise Problem(413, "CSV too large", "The limit is 4 MiB.")
    rows, skipped = parse_csv(body.decode("utf-8-sig", errors="replace"))
    try:
        created, updated = upsert(c.s, c.org_id, brand_id, rows, "csv")
    except CatalogueCap as e:
        raise Problem(422, "Catalogue cap is 1,000 products", str(e)) from e
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "total": _count(c, brand_id),
    }


@router.post("/import/feed", status_code=202, response_model=QueuedOut)
def import_feed(
    brand_id: uuid.UUID, body: FeedIn, c: Ctx = TENANT
) -> dict[str, Any]:
    if not body.url.startswith(("http://", "https://")):
        raise Problem(422, "Only http(s) feed URLs", body.url[:200])
    return queue_suggestion(
        c,
        brand_id,
        "import_feed",
        {"url": body.url},
        slot=datetime.now(UTC),
    )


@router.post("/run", status_code=202, response_model=QueuedOut)
def run(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    total = _count(c, brand_id)
    if total == 0:
        raise Problem(422, "No products to run", "Import products first.")
    locale = c.s.scalars(
        select(m.Locale)
        .where(m.Locale.brand_id == brand_id)
        .order_by(m.Locale.created_at, m.Locale.id)
        .limit(1)
    ).first()
    country = locale.country if locale else "IN"
    language = locale.language if locale else "en"
    return queue_suggestion(
        c,
        brand_id,
        "product_run",
        {
            "locale": {"country": country, "language": language},
            "product_count": total,
        },
        slot=datetime.now(UTC),
    )


@router.delete("", status_code=204)
def clear(brand_id: uuid.UUID, c: Ctx = TENANT) -> Response:
    brand_or_404(c, brand_id)
    c.s.execute(
        delete(m.KeywordSearch).where(m.KeywordSearch.brand_id == brand_id)
    )
    c.s.execute(delete(m.Product).where(m.Product.brand_id == brand_id))
    return Response(status_code=204)
