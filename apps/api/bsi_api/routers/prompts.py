import uuid
from typing import Any, Literal

from bsi_core import models as m
from bsi_core.scheduling import check_active_limit, daily_cost_preview
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..deps import TENANT, Ctx, brand_or_404, child_or_404
from ..problems import Problem
from .runs import queue_suggestion

router = APIRouter(prefix="/brands/{brand_id}/prompts", tags=["prompts"])
MAX_BULK = 5000


def _within_plan(c: Ctx, adding: int) -> None:
    if adding <= 0:  # an over-limit org can still re-activate or pause
        return
    over = check_active_limit(c.s, c.org_id, adding)
    if over is not None:
        current, limit = over
        raise Problem(
            409, "Plan limit reached", f"{current} + {adding} > {limit}"
        )


class PromptIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


Status = Literal["suggested", "active", "paused", "archived"]


class PromptPatch(BaseModel):
    status: Status


class BulkPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_BULK)
    status: Status


class SuggestIn(BaseModel):
    # A misspelt field would otherwise silently fall back to the default.
    model_config = ConfigDict(extra="forbid")
    # The worker only casts params["count"] to int, so this is the one
    # place the bound is enforced: a negative count would pay for a call
    # asking the model for "-1 prompts".
    count: int = Field(50, ge=0, le=100)


class PromptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    text: str
    source: str
    status: str
    intent: str | None
    topic: str | None


@router.get("", response_model=list[PromptOut])
def list_prompts(
    brand_id: uuid.UUID,
    status: Status | None = None,
    intent: str | None = None,
    c: Ctx = TENANT,
) -> list[m.Prompt]:
    brand_or_404(c, brand_id)
    q = select(m.Prompt).where(m.Prompt.brand_id == brand_id)
    if status is not None:
        q = q.where(m.Prompt.status == status)
    if intent is not None:
        q = q.where(m.Prompt.intent == intent)
    return list(c.s.scalars(q.order_by(m.Prompt.created_at)))


@router.post("", response_model=list[PromptOut], status_code=201)
def create_prompts(
    brand_id: uuid.UUID,
    body: PromptIn | list[PromptIn],
    c: Ctx = TENANT,
) -> list[m.Prompt]:
    brand_or_404(c, brand_id)
    items = body if isinstance(body, list) else [body]
    if not 1 <= len(items) <= MAX_BULK:
        raise Problem(422, "Validation failed", f"1 to {MAX_BULK} prompts")
    _within_plan(c, len(items))  # these rows are created active
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
    c: Ctx = TENANT,
) -> m.Prompt:
    row: m.Prompt = child_or_404(c, m.Prompt, brand_id, prompt_id)
    if body.status == "active" and row.status != "active":
        _within_plan(c, 1)
    row.status = body.status
    return row


@router.patch("")
def patch_prompts(
    brand_id: uuid.UUID, body: BulkPatch, c: Ctx = TENANT
) -> dict[str, Any]:
    brand_or_404(c, brand_id)
    ids = set(body.ids)
    rows = list(
        c.s.scalars(
            select(m.Prompt).where(
                m.Prompt.brand_id == brand_id, m.Prompt.id.in_(ids)
            )
        )
    )
    # An id of another brand - even of this same org - is simply absent.
    if len(rows) != len(ids):
        raise Problem(404, "Not found", "Every id must belong to this brand.")
    if body.status == "active":
        _within_plan(c, sum(r.status != "active" for r in rows))
    for row in rows:
        row.status = body.status
    return {
        "updated": len(rows),
        "cost_preview": daily_cost_preview(c.s, c.org_id, brand_id),
    }


@router.post("/suggest", status_code=202)
def suggest(
    brand_id: uuid.UUID, body: SuggestIn | None = None, c: Ctx = TENANT
) -> dict[str, Any]:
    body = body or SuggestIn()
    return queue_suggestion(
        c, brand_id, "suggest_prompts", {"count": body.count}
    )


@router.post("/label", status_code=202)
def label(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    """Label and embed prompts that lack intent, topic or embedding."""
    return queue_suggestion(c, brand_id, "label_prompts", {})
