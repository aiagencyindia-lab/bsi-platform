import uuid
from typing import Literal

from bsi_core import models as m
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..deps import Ctx, brand_or_404, child_or_404, ctx
from ..problems import Problem

router = APIRouter(prefix="/brands/{brand_id}/prompts", tags=["prompts"])
MAX_BULK = 5000


class PromptIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class PromptPatch(BaseModel):
    status: Literal["active", "paused"]


class PromptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    text: str
    source: str
    status: str


@router.get("", response_model=list[PromptOut])
def list_prompts(brand_id: uuid.UUID, c: Ctx = Depends(ctx)) -> list[m.Prompt]:
    brand_or_404(c, brand_id)
    q = select(m.Prompt).where(m.Prompt.brand_id == brand_id)
    return list(c.s.scalars(q.order_by(m.Prompt.created_at)))


@router.post("", response_model=list[PromptOut], status_code=201)
def create_prompts(
    brand_id: uuid.UUID,
    body: PromptIn | list[PromptIn],
    c: Ctx = Depends(ctx),
) -> list[m.Prompt]:
    brand_or_404(c, brand_id)
    items = body if isinstance(body, list) else [body]
    if not 1 <= len(items) <= MAX_BULK:
        raise Problem(422, "Validation failed", f"1 to {MAX_BULK} prompts")
    locale = c.s.scalars(
        select(m.Locale).where(m.Locale.brand_id == brand_id).limit(1)
    ).one()
    rows = [
        m.Prompt(
            org_id=c.org_id,
            brand_id=brand_id,
            locale_id=locale.id,
            text=item.text.strip(),
        )
        for item in items
    ]
    c.s.add_all(rows)
    c.s.flush()
    return rows


@router.patch("/{prompt_id}", response_model=PromptOut)
def patch_prompt(
    brand_id: uuid.UUID,
    prompt_id: uuid.UUID,
    body: PromptPatch,
    c: Ctx = Depends(ctx),
) -> m.Prompt:
    row: m.Prompt = child_or_404(c, m.Prompt, brand_id, prompt_id)
    row.status = body.status
    return row
