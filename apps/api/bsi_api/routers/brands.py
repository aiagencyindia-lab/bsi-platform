import uuid

from bsi_core import models as m
from bsi_core.matching import normalize_domain
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..deps import Ctx, brand_or_404, child_or_404, ctx
from ..problems import Problem

router = APIRouter(prefix="/brands", tags=["brands"])


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class BrandIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    category: str | None = None


class BrandPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    aliases: list[str] | None = Field(None, max_length=20)
    category: str | None = None


class BrandOut(Out):
    name: str
    aliases: list[str]
    category: str | None
    status: str


class CompetitorIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    domains: list[str] = Field(default_factory=list)


class CompetitorPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    aliases: list[str] | None = None
    domains: list[str] | None = None


class CompetitorOut(Out):
    name: str
    aliases: list[str]
    domains: list[str]


class DomainIn(BaseModel):
    host: str = Field(min_length=3)
    is_primary: bool = False


class DomainOut(Out):
    host: str
    is_primary: bool


def _patch(row: object, body: BaseModel) -> None:
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value)


@router.get("", response_model=list[BrandOut])
def list_brands(c: Ctx = Depends(ctx)) -> list[m.Brand]:
    return list(c.s.scalars(select(m.Brand).order_by(m.Brand.created_at)))


@router.post("", response_model=BrandOut, status_code=201)
def create_brand(body: BrandIn, c: Ctx = Depends(ctx)) -> m.Brand:
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
def get_brand(brand_id: uuid.UUID, c: Ctx = Depends(ctx)) -> m.Brand:
    return brand_or_404(c, brand_id)


@router.patch("/{brand_id}", response_model=BrandOut)
def patch_brand(
    brand_id: uuid.UUID, body: BrandPatch, c: Ctx = Depends(ctx)
) -> m.Brand:
    brand = brand_or_404(c, brand_id)
    _patch(brand, body)
    return brand


@router.delete("/{brand_id}", status_code=204)
def archive_brand(brand_id: uuid.UUID, c: Ctx = Depends(ctx)) -> Response:
    brand_or_404(c, brand_id).status = "archived"
    return Response(status_code=204)


@router.get("/{brand_id}/competitors", response_model=list[CompetitorOut])
def list_competitors(
    brand_id: uuid.UUID, c: Ctx = Depends(ctx)
) -> list[m.Competitor]:
    brand_or_404(c, brand_id)
    q = select(m.Competitor).where(m.Competitor.brand_id == brand_id)
    return list(c.s.scalars(q.order_by(m.Competitor.created_at)))


@router.post(
    "/{brand_id}/competitors", response_model=CompetitorOut, status_code=201
)
def create_competitor(
    brand_id: uuid.UUID, body: CompetitorIn, c: Ctx = Depends(ctx)
) -> m.Competitor:
    brand_or_404(c, brand_id)
    data = body.model_dump()
    data["domains"] = [normalize_domain(d) for d in data["domains"]]
    row = m.Competitor(org_id=c.org_id, brand_id=brand_id, **data)
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
    c: Ctx = Depends(ctx),
) -> m.Competitor:
    row: m.Competitor = child_or_404(c, m.Competitor, brand_id, competitor_id)
    _patch(row, body)
    if body.domains is not None:
        row.domains = [normalize_domain(d) for d in body.domains]
    return row


@router.delete("/{brand_id}/competitors/{competitor_id}", status_code=204)
def delete_competitor(
    brand_id: uuid.UUID, competitor_id: uuid.UUID, c: Ctx = Depends(ctx)
) -> Response:
    c.s.delete(child_or_404(c, m.Competitor, brand_id, competitor_id))
    return Response(status_code=204)


@router.get("/{brand_id}/domains", response_model=list[DomainOut])
def list_domains(brand_id: uuid.UUID, c: Ctx = Depends(ctx)) -> list[m.Domain]:
    brand_or_404(c, brand_id)
    q = select(m.Domain).where(m.Domain.brand_id == brand_id)
    return list(c.s.scalars(q.order_by(m.Domain.created_at)))


@router.post("/{brand_id}/domains", response_model=DomainOut, status_code=201)
def create_domain(
    brand_id: uuid.UUID, body: DomainIn, c: Ctx = Depends(ctx)
) -> m.Domain:
    brand_or_404(c, brand_id)
    host = normalize_domain(body.host)
    q = select(m.Domain).where(
        m.Domain.brand_id == brand_id, m.Domain.host == host
    )
    if c.s.scalars(q).first():
        raise Problem(409, "Domain already exists", host)
    row = m.Domain(
        org_id=c.org_id,
        brand_id=brand_id,
        host=host,
        is_primary=body.is_primary,
    )
    c.s.add(row)
    c.s.flush()
    return row


@router.delete("/{brand_id}/domains/{domain_id}", status_code=204)
def delete_domain(
    brand_id: uuid.UUID, domain_id: uuid.UUID, c: Ctx = Depends(ctx)
) -> Response:
    c.s.delete(child_or_404(c, m.Domain, brand_id, domain_id))
    return Response(status_code=204)
