"""Request context: API key -> organization -> tenant session."""

import hashlib
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from bsi_core import models as m
from bsi_core.db import system_session, tenant_session
from fastapi import Depends, Header
from sqlalchemy import text
from sqlalchemy.orm import Session

from .problems import Problem


@dataclass
class Ctx:
    org_id: uuid.UUID
    s: Session


def org_from_key(authorization: str | None = Header(None)) -> uuid.UUID:
    if not authorization or not authorization.startswith("Bearer "):
        raise Problem(401, "Missing API key")
    digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
    with system_session() as s:
        org_id = s.execute(
            text("SELECT resolve_api_key(:h)"), {"h": digest}
        ).scalar()
    if org_id is None:
        raise Problem(401, "Unknown or expired API key")
    return uuid.UUID(str(org_id))


def ctx(org_id: uuid.UUID = Depends(org_from_key)) -> Iterator[Ctx]:
    with tenant_session(org_id) as s:
        yield Ctx(org_id, s)


# Routes take `c: Ctx = TENANT`. scope="function" commits before the
# response is sent; the default request scope commits afterwards, so a
# failed commit reached the client as a success and the write was lost.
TENANT = Depends(ctx, scope="function")


def get_or_404(s: Session, model: type[Any], id_: uuid.UUID) -> Any:
    # RLS hides other tenants' rows, so a cross-tenant id is simply absent.
    row = s.get(model, id_)
    if row is None:
        raise Problem(404, "Not found")
    return row


def brand_or_404(c: Ctx, brand_id: uuid.UUID) -> m.Brand:
    brand: m.Brand = get_or_404(c.s, m.Brand, brand_id)
    return brand


def child_or_404(
    c: Ctx, model: type[Any], brand_id: uuid.UUID, id_: uuid.UUID
) -> Any:
    brand_or_404(c, brand_id)
    row = get_or_404(c.s, model, id_)
    if row.brand_id != brand_id:
        raise Problem(404, "Not found")
    return row
