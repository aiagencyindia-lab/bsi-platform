"""Visibility metrics. Every rate carries its sample size and a Wilson CI."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from math import sqrt
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import models as m


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def rate(k: int, n: int) -> dict[str, float | int | None]:
    low, high = wilson(k, n)
    return {
        "value": k / n if n else None,
        "n": n,
        "ci_low": low,
        "ci_high": high,
    }


@dataclass
class Filters:
    engine: str | None = None
    locale_id: uuid.UUID | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    prompt_ids: list[uuid.UUID] | None = None


def _where(brand_id: uuid.UUID, f: Filters) -> tuple[str, dict[str, Any]]:
    """One filter builder for every metric, so the numbers always agree.

    Only fixed SQL fragments are joined here; all values are bound.
    """
    clauses = ["o.brand_id = :brand_id"]
    params: dict[str, Any] = {"brand_id": brand_id}
    if f.engine is not None:
        clauses.append(
            "o.engine_id = (SELECT id FROM engine WHERE code = :engine)"
        )
        params["engine"] = f.engine
    if f.locale_id is not None:
        clauses.append("o.locale_id = :locale_id")
        params["locale_id"] = f.locale_id
    if f.date_from is not None:
        clauses.append("o.requested_at >= :date_from")
        params["date_from"] = f.date_from
    if f.date_to is not None:
        clauses.append("o.requested_at < :date_to")
        params["date_to"] = f.date_to
    if f.prompt_ids:
        clauses.append("o.prompt_id = ANY(:prompt_ids)")
        params["prompt_ids"] = f.prompt_ids
    return " AND ".join(clauses), params


def brand_sov(
    s: Session, brand_id: uuid.UUID, f: Filters
) -> list[dict[str, Any]]:
    where, params = _where(brand_id, f)
    counts: dict[uuid.UUID, int] = dict(
        s.execute(
            text(
                "SELECT mn.entity_id, count(*) FROM mention mn "
                "JOIN observation o ON o.id = mn.observation_id "
                f"WHERE {where} AND o.status = 'done' GROUP BY mn.entity_id"
            ),
            params,
        )
        .tuples()
        .all()
    )
    brand = s.get_one(m.Brand, brand_id)
    competitors = s.scalars(
        select(m.Competitor)
        .where(m.Competitor.brand_id == brand_id)
        .order_by(m.Competitor.created_at, m.Competitor.name)
    ).all()
    entities = [(brand.id, brand.name, "brand")]
    entities += [(c.id, c.name, "competitor") for c in competitors]
    total = sum(counts.get(eid, 0) for eid, _, _ in entities)
    rows = []
    for eid, name, etype in entities:
        k = counts.get(eid, 0)
        r = rate(k, total)
        rows.append(
            {
                "entity_id": eid,
                "name": name,
                "type": etype,
                "mentions": k,
                "share": r["value"],
                "ci_low": r["ci_low"],
                "ci_high": r["ci_high"],
            }
        )
    return rows


def brand_metrics(
    s: Session, brand_id: uuid.UUID, f: Filters
) -> dict[str, Any]:
    from .extraction import PIPELINE_VERSION

    where, params = _where(brand_id, f)
    done = "o.status = 'done'"
    row = s.execute(
        text(f"""
        SELECT
          count(*) FILTER (WHERE {done}) AS n,
          count(*) FILTER (WHERE o.status = 'failed') AS n_failed,
          count(*) FILTER (WHERE {done} AND bm.id IS NOT NULL) AS k_mention,
          count(*) FILTER (
            WHERE {done} AND bm.rec_status = 'recommended') AS k_rec,
          count(*) FILTER (WHERE {done} AND EXISTS (
            SELECT 1 FROM citation c
            WHERE c.observation_id = o.id AND c.is_brand_owned)) AS k_cit,
          count(DISTINCT o.prompt_id) FILTER (WHERE {done}) AS prompts,
          count(DISTINCT o.prompt_id) FILTER (
            WHERE {done} AND bm.id IS NOT NULL) AS prompts_cov,
          avg(bm.position) FILTER (WHERE {done}) AS avg_pos
        FROM observation o
        LEFT JOIN mention bm
          ON bm.observation_id = o.id AND bm.entity_type = 'brand'
        WHERE {where}"""),
        params,
    ).one()
    sov = brand_sov(s, brand_id, f)
    sov_total = sum(r["mentions"] for r in sov)
    return {
        "mention_rate": rate(row.k_mention, row.n),
        "recommendation_rate": rate(row.k_rec, row.n),
        "citation_rate": rate(row.k_cit, row.n),
        "prompt_coverage": rate(row.prompts_cov, row.prompts),
        "sov": rate(sov[0]["mentions"], sov_total),
        "avg_position": {
            "value": float(row.avg_pos) if row.avg_pos is not None else None,
            "n_mentioned": row.k_mention,
        },
        "n_failed": row.n_failed,
        "pipeline_version": PIPELINE_VERSION,
        "computed_at": datetime.now(UTC),
    }
