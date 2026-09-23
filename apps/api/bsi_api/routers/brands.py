import uuid
from typing import Annotated, Any, Literal

from bsi_core import models as m
from bsi_core.matching import is_public_hostname, normalize_domain
from fastapi import APIRouter, Response
from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from ..deps import TENANT, Ctx, brand_or_404, child_or_404
from ..problems import Problem
from .runs import queue_suggestion

router = APIRouter(prefix="/brands", tags=["brands"])

# Capped because every one of these flows into paid model input.
Short = Annotated[str, Field(max_length=200)]


def _public_host(value: str) -> str:
    """Normalized, and a name the crawl audit may fetch (422 otherwise)."""
    host = normalize_domain(value)
    if not is_public_hostname(host):
        raise ValueError(f"{host!r} is not a public host name")
    return host


Host = Annotated[Short, AfterValidator(_public_host)]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class BrandIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    aliases: list[Short] = Field(default_factory=list, max_length=20)
    category: Short | None = None


# PATCH fields default to None when omitted, but only nullable columns accept
# an explicit null; the others fail validation (422) instead of the database.
class BrandPatch(BaseModel):
    name: str = Field(None, min_length=1, max_length=200)
    aliases: list[Short] = Field(None, max_length=20)
    category: Short | None = None


class BrandOut(Out):
    name: str
    aliases: list[str]
    category: str | None
    status: str


class CompetitorIn(BaseModel):
    name: Short = Field(min_length=1)
    aliases: list[Short] = Field(default_factory=list, max_length=20)
    domains: list[Host] = Field(default_factory=list)


class CompetitorPatch(BaseModel):
    name: Short = Field(None, min_length=1)
    aliases: list[Short] = Field(None)
    domains: list[Host] = Field(None)
    # Confirming a suggestion is the only status move the API offers.
    status: Literal["active"] = Field(None)


class CompetitorOut(Out):
    name: str
    aliases: list[str]
    domains: list[str]
    status: str
    evidence: int | None


class ClusterOut(BaseModel):
    # NULL for prompts no suggestion job has labelled yet: they are a
    # group of their own rather than dropped, so the count adds up.
    intent: str | None
    topic: str | None
    active: int
    suggested: int
    paused: int


class DomainIn(BaseModel):
    host: Annotated[str, AfterValidator(_public_host)] = Field(min_length=3)
    is_primary: bool = False


class DomainOut(Out):
    host: str
    is_primary: bool


def _patch(row: object, body: BaseModel) -> None:
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)


@router.get("", response_model=list[BrandOut])
def list_brands(c: Ctx = TENANT) -> list[m.Brand]:
    return list(c.s.scalars(select(m.Brand).order_by(m.Brand.created_at)))


@router.post("", response_model=BrandOut, status_code=201)
def create_brand(body: BrandIn, c: Ctx = TENANT) -> m.Brand:
    ws = c.s.scalars(select(m.Workspace).limit(1)).one()
    brand = m.Brand(org_id=c.org_id, workspace_id=ws.id, **body.model_dump())
    c.s.add(brand)
    c.s.flush()
    c.s.add(
        m.Locale(
            org_id=c.org_id, brand_id=brand.id, country="IN", language="en"
        )
    )
    c.s.flush()
    c.s.refresh(brand)
    return brand


@router.get("/{brand_id}", response_model=BrandOut)
def get_brand(brand_id: uuid.UUID, c: Ctx = TENANT) -> m.Brand:
    return brand_or_404(c, brand_id)


@router.patch("/{brand_id}", response_model=BrandOut)
def patch_brand(
    brand_id: uuid.UUID, body: BrandPatch, c: Ctx = TENANT
) -> m.Brand:
    brand = brand_or_404(c, brand_id)
    _patch(brand, body)
    return brand


@router.delete("/{brand_id}", status_code=204)
def archive_brand(brand_id: uuid.UUID, c: Ctx = TENANT) -> Response:
    brand_or_404(c, brand_id).status = "archived"
    return Response(status_code=204)


@router.get("/{brand_id}/competitors", response_model=list[CompetitorOut])
def list_competitors(
    brand_id: uuid.UUID,
    status: Literal["suggested", "active"] | None = None,
    c: Ctx = TENANT,
) -> list[m.Competitor]:
    brand_or_404(c, brand_id)
    q = select(m.Competitor).where(m.Competitor.brand_id == brand_id)
    if status is not None:
        q = q.where(m.Competitor.status == status)
    return list(c.s.scalars(q.order_by(m.Competitor.created_at)))


@router.post(
    "/{brand_id}/competitors", response_model=CompetitorOut, status_code=201
)
def create_competitor(
    brand_id: uuid.UUID, body: CompetitorIn, c: Ctx = TENANT
) -> m.Competitor:
    brand_or_404(c, brand_id)
    row = m.Competitor(org_id=c.org_id, brand_id=brand_id, **body.model_dump())
    c.s.add(row)
    c.s.flush()
    return row


@router.patch(
    "/{brand_id}/competitors/{competitor_id}", response_model=CompetitorOut
)
def patch_competitor(
    brand_id: uuid.UUID,
    competitor_id: uuid.UUID,
    body: CompetitorPatch,
    c: Ctx = TENANT,
) -> m.Competitor:
    row: m.Competitor = child_or_404(c, m.Competitor, brand_id, competitor_id)
    _patch(row, body)
    return row


@router.delete("/{brand_id}/competitors/{competitor_id}", status_code=204)
def delete_competitor(
    brand_id: uuid.UUID, competitor_id: uuid.UUID, c: Ctx = TENANT
) -> Response:
    c.s.delete(child_or_404(c, m.Competitor, brand_id, competitor_id))
    return Response(status_code=204)


@router.get("/{brand_id}/domains", response_model=list[DomainOut])
def list_domains(brand_id: uuid.UUID, c: Ctx = TENANT) -> list[m.Domain]:
    brand_or_404(c, brand_id)
    q = select(m.Domain).where(m.Domain.brand_id == brand_id)
    return list(c.s.scalars(q.order_by(m.Domain.created_at)))


@router.post("/{brand_id}/domains", response_model=DomainOut, status_code=201)
def create_domain(
    brand_id: uuid.UUID, body: DomainIn, c: Ctx = TENANT
) -> m.Domain:
    brand_or_404(c, brand_id)
    q = select(m.Domain).where(
        m.Domain.brand_id == brand_id, m.Domain.host == body.host
    )
    if c.s.scalars(q).first():
        raise Problem(409, "Domain already exists", body.host)
    row = m.Domain(
        org_id=c.org_id,
        brand_id=brand_id,
        host=body.host,
        is_primary=body.is_primary,
    )
    c.s.add(row)
    c.s.flush()
    return row


@router.delete("/{brand_id}/domains/{domain_id}", status_code=204)
def delete_domain(
    brand_id: uuid.UUID, domain_id: uuid.UUID, c: Ctx = TENANT
) -> Response:
    c.s.delete(child_or_404(c, m.Domain, brand_id, domain_id))
    return Response(status_code=204)


@router.post("/{brand_id}/competitors/suggest", status_code=202)
def suggest_competitors(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    return queue_suggestion(c, brand_id, "suggest_competitors", {})


@router.get("/{brand_id}/clusters", response_model=list[ClusterOut])
def list_clusters(brand_id: uuid.UUID, c: Ctx = TENANT) -> list[Any]:
    brand_or_404(c, brand_id)
    counts = [
        func.count().filter(m.Prompt.status == s).label(s)
        for s in ("active", "suggested", "paused")
    ]
    q = (
        select(m.Prompt.intent, m.Prompt.topic, *counts)
        # Archived prompts are counted in no column, so grouping them
        # would show phantom 0/0/0 rows.
        .where(m.Prompt.brand_id == brand_id, m.Prompt.status != "archived")
        .group_by(m.Prompt.intent, m.Prompt.topic)
        # NULL intents sort last within a count, which is where an
        # unlabelled group belongs.
        .order_by(counts[0].desc(), m.Prompt.intent, m.Prompt.topic)
    )
    return list(c.s.execute(q).all())
