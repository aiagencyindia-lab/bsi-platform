"""Competitor intelligence (PRD F07): per-entity metrics, deltas and a
visibility change feed. Read-only SQL over stored answers; every number
shares metrics._where so it agrees with the Overview tiles."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import models as m
from .matching import is_owned
from .metrics import (
    Filters,
    _entities,
    _where,
    brand_sov,
    rate,
)
from .recommend import _rival_domains

DELTA_METRICS = (
    "mention_rate",
    "recommendation_rate",
    "citation_rate",
    "prompt_coverage",
    "sov",
)
CITING_DOMAINS = 5
MIN_PROMPTS = 10
MIN_SHIFT = 0.10
EVIDENCE_CAP = 20

_DONE = "o.status = 'done'"


def owner_of(
    domain: str, brand_hosts: list[str], rival_hosts: list[str]
) -> str:
    if is_owned(domain, brand_hosts):
        return "brand"
    if is_owned(domain, rival_hosts):
        return "rival"
    return "third_party"


def _hosts(s: Session, brand_id: uuid.UUID) -> dict[uuid.UUID, list[str]]:
    """Declared domains per entity: the brand's `domain` rows, each active
    competitor's `domains` column."""
    out = {
        brand_id: list(
            s.scalars(
                select(m.Domain.host).where(m.Domain.brand_id == brand_id)
            )
        )
    }
    for c in s.scalars(
        select(m.Competitor).where(
            m.Competitor.brand_id == brand_id, m.Competitor.status == "active"
        )
    ):
        out[c.id] = list(c.domains)
    return out


def entity_metrics(
    s: Session, brand_id: uuid.UUID, f: Filters
) -> list[dict[str, Any]]:
    """One row for the brand and one per active competitor, best mention
    rate first (brand wins ties, then name)."""
    where, params = _where(brand_id, f)
    hosts = _hosts(s, brand_id)
    brand_hosts = hosts[brand_id]
    rival_hosts = _rival_domains(s, brand_id)
    sov = {r["entity_id"]: r for r in brand_sov(s, brand_id, f)}
    sov_total = sum(r["mentions"] for r in sov.values())
    rows: list[dict[str, Any]] = []
    for eid, name, etype in _entities(s, brand_id):
        p = {
            **params,
            "eid": eid,
            "etype": etype,
            "domains": hosts.get(eid, []),
        }
        r = s.execute(
            text(f"""
            SELECT
              count(*) AS n,
              count(*) FILTER (WHERE mn.id IS NOT NULL) AS k_mention,
              count(*) FILTER (WHERE mn.rec_status = 'recommended') AS k_rec,
              count(*) FILTER (WHERE EXISTS (
                SELECT 1 FROM citation c
                WHERE c.observation_id = o.id AND EXISTS (
                  SELECT 1 FROM unnest(CAST(:domains AS text[])) d
                  WHERE c.domain = d OR c.domain LIKE '%.' || d))) AS k_cit,
              count(DISTINCT o.prompt_id) AS prompts,
              count(DISTINCT o.prompt_id) FILTER (
                WHERE mn.id IS NOT NULL) AS prompts_cov,
              avg(mn.position) AS avg_pos,
              count(*) FILTER (WHERE mn.sentiment = 'positive') AS k_pos,
              count(*) FILTER (WHERE mn.sentiment = 'negative') AS k_neg
            FROM observation o
            LEFT JOIN mention mn ON mn.observation_id = o.id
              AND mn.entity_type = :etype AND mn.entity_id = :eid
            WHERE {where} AND {_DONE}"""),
            p,
        ).one()
        cited = s.execute(
            text(
                "SELECT c.domain, count(DISTINCT o.id) AS answers "
                "FROM citation c "
                "JOIN observation o ON o.id = c.observation_id "
                "JOIN mention mn ON mn.observation_id = o.id "
                "  AND mn.entity_type = :etype AND mn.entity_id = :eid "
                f"WHERE {where} AND {_DONE} "
                "GROUP BY c.domain ORDER BY answers DESC, c.domain "
                f"LIMIT {CITING_DOMAINS}"
            ),
            p,
        ).all()
        pos = rate(r.k_pos, r.k_mention)
        neg = rate(r.k_neg, r.k_mention)
        rows.append(
            {
                "entity_id": eid,
                "name": name,
                "type": etype,
                "mention_rate": rate(r.k_mention, r.n),
                "recommendation_rate": rate(r.k_rec, r.n),
                "citation_rate": rate(r.k_cit, r.n),
                "prompt_coverage": rate(r.prompts_cov, r.prompts),
                "sov": rate(sov[eid]["mentions"], sov_total),
                "avg_position": {
                    "value": float(r.avg_pos)
                    if r.avg_pos is not None
                    else None,
                    "n_mentioned": r.k_mention,
                },
                "sentiment": {
                    "positive": pos,
                    "negative": neg,
                    # Computed here so the page computes nothing.
                    "index": (
                        pos["value"] - neg["value"]
                        if pos["value"] is not None and neg["value"] is not None
                        else None
                    ),
                },
                "citing_domains": [
                    {
                        "domain": c.domain,
                        "answers": c.answers,
                        "owner": owner_of(c.domain, brand_hosts, rival_hosts),
                    }
                    for c in cited
                ],
            }
        )
    rows.sort(
        key=lambda r: (
            -(r["mention_rate"]["value"] or -1.0),
            r["type"] != "brand",
            r["name"],
        )
    )
    return rows


def entity_deltas(
    s: Session, brand_id: uuid.UUID, f: Filters, days: int, to: datetime
) -> list[dict[str, Any]]:
    raise NotImplementedError  # Task 2


def visibility_changes(
    s: Session,
    brand_id: uuid.UUID,
    f: Filters,
    days: int = 14,
    to: datetime | None = None,
) -> list[dict[str, Any]]:
    raise NotImplementedError  # Task 2
