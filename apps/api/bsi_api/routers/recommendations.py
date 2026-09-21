"""Recommendations: generate from evidence, then accept or dismiss."""

import uuid
from typing import Literal

from bsi_core import models as m
from bsi_core.recommend import refresh
from fastapi import APIRouter
from sqlalchemy import select

from ..deps import TENANT, Ctx, brand_or_404, child_or_404
from ..problems import Problem
from ..schemas import DismissIn, RecommendationOut, TaskOut

router = APIRouter(prefix="/brands/{brand_id}", tags=["recommendations"])


def _listed(c: Ctx, brand_id: uuid.UUID, status: str) -> list[m.Recommendation]:
    return list(
        c.s.scalars(
            select(m.Recommendation)
            .where(
                m.Recommendation.brand_id == brand_id,
                m.Recommendation.status == status,
            )
            .order_by(
                m.Recommendation.priority.desc(),
                m.Recommendation.created_at,
                m.Recommendation.id,
            )
        )
    )


def _open(c: Ctx, brand_id: uuid.UUID, rec_id: uuid.UUID) -> m.Recommendation:
    rec: m.Recommendation = child_or_404(c, m.Recommendation, brand_id, rec_id)
    if rec.status != "open":
        raise Problem(409, "Recommendation is not open", f"It is {rec.status}.")
    return rec


@router.post(
    "/recommendations/generate", response_model=list[RecommendationOut]
)
def generate_recommendations(
    brand_id: uuid.UUID, c: Ctx = TENANT
) -> list[m.Recommendation]:
    brand_or_404(c, brand_id)
    refresh(c.s, c.org_id, brand_id)
    return _listed(c, brand_id, "open")


@router.get("/recommendations", response_model=list[RecommendationOut])
def list_recommendations(
    brand_id: uuid.UUID,
    status: Literal["open", "accepted", "dismissed"] = "open",
    c: Ctx = TENANT,
) -> list[m.Recommendation]:
    brand_or_404(c, brand_id)
    return _listed(c, brand_id, status)


@router.post(
    "/recommendations/{rec_id}/accept",
    response_model=TaskOut,
    status_code=201,
)
def accept(brand_id: uuid.UUID, rec_id: uuid.UUID, c: Ctx = TENANT) -> m.Task:
    rec = _open(c, brand_id, rec_id)
    rec.status = "accepted"
    task = m.Task(
        org_id=c.org_id,
        brand_id=brand_id,
        recommendation_id=rec.id,
        title=rec.title,
        prompt_ids=[uuid.UUID(p) for p in rec.evidence.get("prompt_ids", [])],
    )
    c.s.add(task)
    c.s.flush()
    return task


@router.post(
    "/recommendations/{rec_id}/dismiss", response_model=RecommendationOut
)
def dismiss(
    brand_id: uuid.UUID, rec_id: uuid.UUID, body: DismissIn, c: Ctx = TENANT
) -> m.Recommendation:
    rec = _open(c, brand_id, rec_id)
    rec.status, rec.dismiss_reason = "dismissed", body.reason
    return rec
