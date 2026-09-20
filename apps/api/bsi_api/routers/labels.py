"""Hand labels for mentions, to score the judge against."""

import uuid
from typing import Any, Literal

from bsi_core import models as m
from bsi_core.metrics import rate
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from ..deps import TENANT, Ctx, brand_or_404
from ..problems import Problem
from .metrics import Rate
from .observations import answer_text

router = APIRouter(tags=["labels"])

# Keep in step with models.REC_STATUSES; a Literal gives the 422 and the
# TypeScript union for free.
RecStatus = Literal["recommended", "listed", "mentioned", "negative"]


class LabelItem(BaseModel):
    observation_id: uuid.UUID
    entity_id: uuid.UUID
    entity_type: str
    entity_name: str
    evidence_sentence: str | None
    text: str | None


class LabelQueue(BaseModel):
    item: LabelItem | None
    labelled: int
    remaining: int
    agreement: Rate


class LabelIn(BaseModel):
    label: RecStatus


class LabelResult(BaseModel):
    label: str
    judge: str
    agrees: bool


def _mentions(brand_id: uuid.UUID) -> Any:
    """Mentions in the brand's done observations, joined to their label."""
    return (
        select(m.Mention, m.RecLabel)
        .join(m.Observation, m.Observation.id == m.Mention.observation_id)
        .outerjoin(
            m.RecLabel,
            (m.RecLabel.observation_id == m.Mention.observation_id)
            & (m.RecLabel.entity_id == m.Mention.entity_id),
        )
        .where(
            m.Observation.brand_id == brand_id,
            m.Observation.status == "done",
        )
    )


@router.get("/brands/{brand_id}/labels/next", response_model=LabelQueue)
def next_label(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    brand = brand_or_404(c, brand_id)
    # ponytail: next_label loads every mention of the brand to count and
    # pick. Fine for hundreds of labels; move the counts into SQL past
    # ~10k mentions.
    rows = c.s.execute(
        _mentions(brand_id).order_by(
            m.Observation.requested_at, m.Observation.id, m.Mention.position
        )
    ).all()
    done = [(mn, lb) for mn, lb in rows if lb is not None]
    todo = [mn for mn, lb in rows if lb is None]

    # A mentioned competitor can be deleted later (DELETE .../competitors/
    # {id} hard-deletes; Mention.entity_id has no FK, being polymorphic
    # over brand/competitor), leaving a mention that points at nothing.
    # Resolve names up front and drop those: an unlabellable mention must
    # not block the queue, and must not count as work still to do.
    comp_ids = {mn.entity_id for mn in todo if mn.entity_type == "competitor"}
    comp_names: dict[uuid.UUID, str] = {}
    if comp_ids:
        comp_names = dict(
            c.s.execute(
                select(m.Competitor.id, m.Competitor.name).where(
                    m.Competitor.id.in_(comp_ids)
                )
            ).all()
        )
    todo = [
        mn
        for mn in todo
        if mn.entity_type == "brand" or mn.entity_id in comp_names
    ]

    item = None
    if todo:
        mn = todo[0]
        name = (
            brand.name
            if mn.entity_type == "brand"
            else comp_names[mn.entity_id]
        )
        obs = c.s.get_one(m.Observation, mn.observation_id)
        item = {
            "observation_id": mn.observation_id,
            "entity_id": mn.entity_id,
            "entity_type": mn.entity_type,
            "entity_name": name,
            "evidence_sentence": mn.evidence_sentence,
            "text": answer_text(obs, c.org_id),
        }
    agree = sum(1 for mn, lb in done if lb.label == mn.rec_status)
    return {
        "item": item,
        "labelled": len(done),
        "remaining": len(todo),
        "agreement": rate(agree, len(done)),
    }


@router.put(
    "/observations/{observation_id}/labels/{entity_id}",
    response_model=LabelResult,
)
def put_label(
    observation_id: uuid.UUID,
    entity_id: uuid.UUID,
    body: LabelIn,
    c: Ctx = TENANT,
) -> dict[str, Any]:
    mention = c.s.scalars(
        select(m.Mention).where(
            m.Mention.observation_id == observation_id,
            m.Mention.entity_id == entity_id,
        )
    ).first()
    if mention is None:  # includes another tenant's: RLS hides it
        raise Problem(404, "Not found")
    c.s.execute(
        insert(m.RecLabel)
        .values(
            org_id=c.org_id,
            observation_id=observation_id,
            entity_type=mention.entity_type,
            entity_id=entity_id,
            label=body.label,
        )
        .on_conflict_do_update(
            index_elements=["observation_id", "entity_id"],
            set_={"label": body.label},
        )
    )
    return {
        "label": body.label,
        "judge": mention.rec_status,
        "agrees": body.label == mention.rec_status,
    }
