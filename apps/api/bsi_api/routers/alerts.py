"""Alerts: what the daily scan found, and a manual scan."""

import uuid
from datetime import UTC, datetime

from bsi_core import models as m
from bsi_core.alerts import scan
from fastapi import APIRouter, Query
from sqlalchemy import select

from ..deps import TENANT, Ctx, brand_or_404
from ..schemas import AlertOut, ScanOut

router = APIRouter(prefix="/brands/{brand_id}/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(
    brand_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    c: Ctx = TENANT,
) -> list[m.Alert]:
    brand_or_404(c, brand_id)
    q = (
        select(m.Alert)
        .where(m.Alert.brand_id == brand_id)
        .order_by(m.Alert.created_at.desc(), m.Alert.id)
        .limit(limit)
    )
    return list(c.s.scalars(q))


@router.post("/scan", response_model=ScanOut)
def scan_now(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, int]:
    """Run the detectors now. SQL only, so it runs inline. It does not
    stamp alerts_scanned_at: an operator's click must not defer the daily
    pass."""
    brand = brand_or_404(c, brand_id)
    rows = scan(
        c.s,
        c.org_id,
        brand_id,
        datetime.now(UTC),
        deliver=brand.webhook_url is not None,
    )
    return {"created": len(rows)}
