"""Recommendations: generate from evidence, then accept or dismiss."""

import uuid
from typing import Literal

from bsi_core import models as m
from bsi_core.recommend import refresh, top_by_type
from fastapi import APIRouter
from sqlalchemy import select

from ..deps import TENANT, Ctx, brand_or_404, child_or_404
from ..problems import Problem
from ..schemas import DismissIn, RecommendationOut, TaskOut

router = APIRouter(prefix="/brands/{brand_id}", tags=["recommendations"])
# Mention rate is the impact metric; these cannot move it. Confirming a
# competitor changes share of voice, and more samples change only whether
# a prompt separates, so their tasks get no window. A site fix changes
# what an engine *can* read, not what it says within a window.
NO_IMPACT = {"add_competitor", "sample_more", "fix_crawlability"}


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
                # generate()'s tie order, so the page matches it.
                m.Recommendation.type,
                m.Recommendation.subject_key,
                m.Recommendation.created_at,
                m.Recommendation.id,
            )
        )
    )


def _open(c: Ctx, brand_id: uuid.UUID, rec_id: uuid.UUID) -> m.Recommendation:
    # child_or_404 first, so a foreign id still 404s rather than blocking
    # on a lock for a row RLS would hide anyway. Then lock and re-read: a
    # racing accept/dismiss on the same row waits here, and under READ
    # COMMITTED sees the committed status once the lock is released, so
    # only one of two concurrent requests gets past this check.
    rec: m.Recommendation = child_or_404(c, m.Recommendation, brand_id, rec_id)
    c.s.refresh(rec, with_for_update=True)
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


@router.get("/recommendations/top", response_model=list[RecommendationOut])
def top_recommendations(
    brand_id: uuid.UUID, c: Ctx = TENANT
) -> list[m.Recommendation]:
    """The overview's shortlist: the best open recommendation of each type,
    then the next best, up to three."""
    brand_or_404(c, brand_id)
    return top_by_type(_listed(c, brand_id, "open"))


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
        measures_impact=rec.type not in NO_IMPACT,
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
