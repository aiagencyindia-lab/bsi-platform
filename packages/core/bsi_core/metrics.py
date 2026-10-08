"""Visibility metrics. Every rate carries its sample size and a Wilson CI."""

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from math import hypot, sqrt
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
    # The exact bound is 0 at k=0 and 1 at k=n; float rounding misses it.
    low = 0.0 if k == 0 else max(0.0, centre - half)
    high = 1.0 if k == n else min(1.0, centre + half)
    return (low, high)


def rate(k: int, n: int) -> dict[str, float | int | None]:
    low, high = wilson(k, n)
    return {
        "value": k / n if n else None,
        "n": n,
        "ci_low": low,
        "ci_high": high,
    }


def samples_to_separate(
    k_brand: int, k_rival: int, n: int, cap: int = 1000
) -> int | None:
    """Smallest sample size whose Wilson intervals no longer overlap.

    A projection, not a measurement: it assumes the rates observed in
    `n` hold as more samples arrive. It answers "how many samples would
    this prompt need before it could tell these two apart", which at
    small `n` is usually far more than the operator expects.

    Separation is checked in both directions, as `separated` is, so a
    rival being detectably ahead counts. None when the observed rates
    are equal (no sample size separates them) or when the answer is
    past `cap`.
    """
    if n <= 0:
        return None
    p_brand, p_rival = k_brand / n, k_rival / n
    if p_brand == p_rival:
        return None
    for size in range(n, cap + 1):
        low_b, high_b = wilson(round(p_brand * size), size)
        low_r, high_r = wilson(round(p_rival * size), size)
        if low_b > high_r or high_b < low_r:
            return size
    return None


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


def _entities(
    s: Session, brand_id: uuid.UUID
) -> list[tuple[uuid.UUID, str, str]]:
    """The brand, then its active competitors: who the metrics measure."""
    brand = s.get_one(m.Brand, brand_id)
    competitors = s.scalars(
        select(m.Competitor)
        .where(
            m.Competitor.brand_id == brand_id,
            m.Competitor.status == "active",
        )
        .order_by(m.Competitor.created_at, m.Competitor.name)
    ).all()
    return [(brand.id, brand.name, "brand")] + [
        (c.id, c.name, "competitor") for c in competitors
    ]


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
    entities = _entities(s, brand_id)
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


def prompt_metrics(
    s: Session, brand_id: uuid.UUID, f: Filters
) -> list[dict[str, Any]]:
    """Mention rate per prompt for the brand and each active competitor.

    A mention is unique per (observation, entity), so a mention count is
    the number of answers that named the entity.
    """
    where, params = _where(brand_id, f)
    prompts = s.execute(
        text(
            "SELECT o.prompt_id, p.text, p.intent, p.topic, count(*) AS n "
            "FROM observation o JOIN prompt p ON p.id = o.prompt_id "
            f"WHERE {where} AND o.status = 'done' "
            "GROUP BY o.prompt_id, p.text, p.intent, p.topic "
            "ORDER BY p.text, o.prompt_id"
        ),
        params,
    ).all()
    counts: dict[tuple[uuid.UUID, uuid.UUID], int] = {
        (pid, eid): k
        for pid, eid, k in s.execute(
            text(
                "SELECT o.prompt_id, mn.entity_id, count(*) FROM mention mn "
                "JOIN observation o ON o.id = mn.observation_id "
                f"WHERE {where} AND o.status = 'done' "
                "GROUP BY o.prompt_id, mn.entity_id"
            ),
            params,
        ).tuples()
    }
    entities = _entities(s, brand_id)
    rows = []
    for p in prompts:
        ks = [counts.get((p.prompt_id, eid), 0) for eid, _, _ in entities]
        rates: list[dict[str, Any]] = [
            {
                "entity_id": eid,
                "name": name,
                "type": etype,
                **rate(k, p.n),
            }
            for (eid, name, etype), k in zip(entities, ks, strict=True)
        ]
        k_brand, k_rivals = ks[0], ks[1:]
        brand, rivals = rates[0], rates[1:]
        top_i = max(range(len(rivals)), key=lambda i: k_rivals[i], default=None)
        top: dict[str, Any] | None = None
        spread: float | None = None
        if top_i is not None:
            top = rivals[top_i]
            spread = (k_brand - k_rivals[top_i]) / p.n
        rows.append(
            {
                "prompt_id": p.prompt_id,
                "text": p.text,
                "intent": p.intent,
                "topic": p.topic,
                "n": p.n,
                "brand": brand,
                "entities": rates,
                "top_competitor": top,
                "spread": spread,
                "needs_samples": (
                    samples_to_separate(k_brand, k_rivals[top_i], p.n)
                    if top_i is not None
                    else None
                ),
                "separated": top is not None
                and (
                    brand["ci_low"] > top["ci_high"]
                    or brand["ci_high"] < top["ci_low"]
                ),
            }
        )
    return rows


def failed_count(s: Session, brand_id: uuid.UUID, f: Filters) -> int:
    """Failed-observation count, shared by `brand_metrics` and `/sov`."""
    where, params = _where(brand_id, f)
    return int(
        s.execute(
            text(
                "SELECT count(*) FROM observation o "
                f"WHERE {where} AND o.status = 'failed'"
            ),
            params,
        ).scalar_one()
    )


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
          AND bm.entity_id = o.brand_id
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
        "n_failed": failed_count(s, brand_id, f),
        "pipeline_versions": window_versions(s, brand_id, f),
        "pipeline_version": PIPELINE_VERSION,
        "computed_at": datetime.now(UTC),
    }


def window_versions(s: Session, brand_id: uuid.UUID, f: Filters) -> list[str]:
    """Distinct pipeline versions of the done observations in a window."""
    where, params = _where(brand_id, f)
    return list(
        s.scalars(
            text(
                "SELECT DISTINCT e.pipeline_version FROM observation o "
                "JOIN extraction e ON e.observation_id = o.id "
                f"WHERE {where} AND o.status = 'done' ORDER BY 1"
            ),
            params,
        ).all()
    )


def window_models(s: Session, brand_id: uuid.UUID, f: Filters) -> list[str]:
    """Distinct engine models of the done observations in a window; a
    NULL model is unknown and does not count."""
    where, params = _where(brand_id, f)
    return list(
        s.scalars(
            text(
                "SELECT DISTINCT o.model FROM observation o "
                f"WHERE {where} AND o.status = 'done' "
                "AND o.model IS NOT NULL ORDER BY 1"
            ),
            params,
        ).all()
    )


def comparability(
    versions: set[str], models: set[str]
) -> tuple[bool, str | None]:
    """Two windows compare only on one pipeline version and one engine
    model; the pipeline reason comes first because it names a fix."""
    if len(versions) > 1:
        return False, (
            "windows use different pipeline versions "
            f"{sorted(versions)}; re-extract the older window"
        )
    if len(models) > 1:
        return False, f"windows use different engine models {sorted(models)}"
    return True, None


def delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """95% Newcombe (method 10) interval for after - before, and a label.

    Assumes independent samples. Windows share prompts, so this is
    somewhat optimistic; for sov, mentions cluster within answers, which
    makes it more so. Across five metrics, expect about one false
    "significant" label in four comparisons when nothing changed.
    """
    p1, p2 = after["value"], before["value"]
    if p1 is None or p2 is None:
        return {
            "value": None,
            "ci_low": None,
            "ci_high": None,
            "label": "insufficient data",
        }
    d = p1 - p2
    low = d - hypot(p1 - after["ci_low"], before["ci_high"] - p2)
    high = d + hypot(after["ci_high"] - p1, p2 - before["ci_low"])
    label = (
        "increase"
        if low > 0
        else "decrease"
        if high < 0
        else "no significant change"
    )
    return {"value": d, "ci_low": low, "ci_high": high, "label": label}


DELTA_METRICS = (
    "mention_rate",
    "recommendation_rate",
    "citation_rate",
    "prompt_coverage",
    "sov",
)


def brand_deltas(
    s: Session, brand_id: uuid.UUID, f: Filters, days: int, to: datetime
) -> dict[str, Any]:
    """Compare [to - days, to) with the `days` before it.

    Windows use claim time, like /metrics, so a boundary can split a run
    that is still draining. Any date_from/date_to on f is replaced: days
    and to define both windows.
    """
    mid, start = to - timedelta(days=days), to - timedelta(days=2 * days)
    fb = replace(f, date_from=start, date_to=mid)
    fa = replace(f, date_from=mid, date_to=to)
    before = brand_metrics(s, brand_id, fb)
    after = brand_metrics(s, brand_id, fa)
    versions = set(before["pipeline_versions"]) | set(
        after["pipeline_versions"]
    )
    models = set(window_models(s, brand_id, fb)) | set(
        window_models(s, brand_id, fa)
    )
    comparable, reason = comparability(versions, models)
    return {
        "before": {"from": start, "to": mid, **before},
        "after": {"from": mid, "to": to, **after},
        "comparable": comparable,
        "reason": reason,
        "deltas": {k: delta(before[k], after[k]) for k in DELTA_METRICS}
        if comparable
        else None,
    }
