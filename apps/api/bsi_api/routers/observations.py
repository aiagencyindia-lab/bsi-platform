import uuid
from datetime import datetime
from typing import Any

from bsi_core import models as m
from bsi_core.providers.gemini import GeminiGroundingAdapter
from bsi_core.storage import LocalRawStore
from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from ..deps import TENANT, Ctx, get_or_404
from ..problems import Problem

router = APIRouter(prefix="/observations", tags=["observations"])


class ObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    brand_id: uuid.UUID
    prompt_id: uuid.UUID
    sample_index: int
    scheduled_slot: datetime
    status: str
    attempts: int
    error: str | None
    model: str | None
    model_version: str | None
    cost_micros: int
    requested_at: datetime
    completed_at: datetime | None


@router.get("", response_model=list[ObservationOut])
def list_observations(
    brand_id: uuid.UUID | None = None,
    prompt_id: uuid.UUID | None = None,
    status: str | None = None,
    engine: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    c: Ctx = TENANT,
) -> list[m.Observation]:
    q = select(m.Observation)
    if brand_id:
        q = q.where(m.Observation.brand_id == brand_id)
    if prompt_id:
        q = q.where(m.Observation.prompt_id == prompt_id)
    if status:
        q = q.where(m.Observation.status == status)
    if engine:
        q = q.join(m.Engine, m.Engine.id == m.Observation.engine_id).where(
            m.Engine.code == engine
        )
    q = q.order_by(m.Observation.requested_at.desc(), m.Observation.id)
    return list(c.s.scalars(q.limit(limit).offset(offset)))


_ORM = ConfigDict(from_attributes=True)


class ExtractionOut(BaseModel):
    model_config = _ORM
    pipeline_version: str
    model_used: str
    brand_mentioned: bool
    position: int | None
    rec_status: str | None
    sentiment: str | None
    sentiment_conf: float | None
    context: str
    absence_reason: str | None
    parsed: dict[str, Any]
    cost_micros: int


class MentionOut(BaseModel):
    model_config = _ORM
    entity_type: str
    entity_id: uuid.UUID
    position: int
    rec_status: str
    sentiment: str
    evidence_sentence: str | None


class CitationOut(BaseModel):
    model_config = _ORM
    url: str
    domain: str
    position: int
    is_brand_owned: bool


class ObservationDetail(ObservationOut):
    params: dict[str, Any]
    text: str | None
    extraction: ExtractionOut | None
    mentions: list[MentionOut]
    citations: list[CitationOut]


def answer_text(obs: m.Observation, org_id: uuid.UUID) -> str | None:
    if obs.raw_uri is None:
        return None
    # ponytail: one engine today; choose the adapter by engine code when
    # a second one exists.
    raw = LocalRawStore().get(obs.raw_uri, org_id)
    return GeminiGroundingAdapter().parse(raw).text


@router.get("/{observation_id}", response_model=ObservationDetail)
def get_observation(
    observation_id: uuid.UUID, c: Ctx = TENANT
) -> dict[str, Any]:
    obs = get_or_404(c.s, m.Observation, observation_id)
    ex = c.s.scalars(
        select(m.Extraction).where(m.Extraction.observation_id == obs.id)
    ).first()
    mentions = c.s.scalars(
        select(m.Mention)
        .where(m.Mention.observation_id == obs.id)
        .order_by(m.Mention.position)
    )
    citations = c.s.scalars(
        select(m.Citation)
        .where(m.Citation.observation_id == obs.id)
        .order_by(m.Citation.position)
    )
    return {
        **ObservationOut.model_validate(obs).model_dump(),
        "params": obs.params,
        "text": answer_text(obs, c.org_id),
        "extraction": ex,
        "mentions": list(mentions),
        "citations": list(citations),
    }


@router.get("/{observation_id}/raw")
def get_raw(observation_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    obs = get_or_404(c.s, m.Observation, observation_id)
    if obs.raw_uri is None:
        raise Problem(404, "No raw payload", "The observation has not run yet.")
    return LocalRawStore().get(obs.raw_uri, c.org_id)
