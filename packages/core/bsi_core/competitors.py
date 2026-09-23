"""Competitor intelligence (PRD F07): per-entity metrics, deltas and a
visibility change feed. Read-only SQL over stored answers; every number
shares metrics._where so it agrees with the Overview tiles."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import models as m
from .matching import is_owned
from .metrics import (
    DELTA_METRICS,
    Filters,
    _entities,
    _where,
    brand_sov,
    delta,
    rate,
    window_versions,
)

CITING_DOMAINS = 5
MIN_PROMPTS = 10
MIN_SHIFT = 0.10
EVIDENCE_CAP = 20

_DONE = "o.status = 'done'"
_FEW = "fewer than 10 prompts with answers in both windows"


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
    rival_hosts = [
        h for eid, hs in hosts.items() if eid != brand_id for h in hs
    ]
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
        # k_cit matches the entity's declared hosts as they are now. The
        # Overview tile counts citation.is_brand_owned, set at extraction,
        # so the brand's citation_rate here can differ from it after a
        # brand domain changes, until the answers are re-extracted.
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


def _windows(days: int, to: datetime) -> tuple[datetime, datetime]:
    return to - timedelta(days=2 * days), to - timedelta(days=days)


def _comparable(
    s: Session, brand_id: uuid.UUID, before: Filters, after: Filters
) -> tuple[bool, str | None]:
    versions = set(window_versions(s, brand_id, before)) | set(
        window_versions(s, brand_id, after)
    )
    if len(versions) <= 1:
        return True, None
    return False, (
        "windows use different pipeline versions "
        f"{sorted(versions)}; re-extract the older window"
    )


def entity_deltas(
    s: Session, brand_id: uuid.UUID, f: Filters, days: int, to: datetime
) -> dict[str, Any]:
    """Compare [to - days, to) with the `days` before it, per entity.
    Same windows and comparability rule as metrics.brand_deltas."""
    start, mid = _windows(days, to)
    fb = replace(f, date_from=start, date_to=mid)
    fa = replace(f, date_from=mid, date_to=to)
    before = entity_metrics(s, brand_id, fb)
    after = entity_metrics(s, brand_id, fa)
    comparable, reason = _comparable(s, brand_id, fb, fa)
    by_id = {r["entity_id"]: r for r in before}
    return {
        "before": {"from": start, "to": mid, "entities": before},
        "after": {"from": mid, "to": to, "entities": after},
        "comparable": comparable,
        "reason": reason,
        "deltas": {
            r["entity_id"]: {
                k: delta(by_id[r["entity_id"]][k], r[k]) for k in DELTA_METRICS
            }
            for r in after
        }
        if comparable
        else None,
    }


def _per_prompt(
    s: Session, brand_id: uuid.UUID, f: Filters
) -> tuple[
    dict[uuid.UUID, tuple[str, int]], dict[tuple[uuid.UUID, uuid.UUID], int]
]:
    """(prompt -> (text, n done answers), (prompt, entity) -> k) in a window."""
    where, params = _where(brand_id, f)
    prompts = {
        pid: (txt, n)
        for pid, txt, n in s.execute(
            text(
                "SELECT o.prompt_id, p.text, count(*) FROM observation o "
                "JOIN prompt p ON p.id = o.prompt_id "
                f"WHERE {where} AND {_DONE} GROUP BY o.prompt_id, p.text"
            ),
            params,
        ).tuples()
    }
    counts = {
        (pid, eid): k
        for pid, eid, k in s.execute(
            text(
                "SELECT o.prompt_id, mn.entity_id, count(*) FROM mention mn "
                "JOIN observation o ON o.id = mn.observation_id "
                f"WHERE {where} AND {_DONE} AND mn.entity_type = 'competitor' "
                "GROUP BY o.prompt_id, mn.entity_id"
            ),
            params,
        ).tuples()
    }
    return prompts, counts


def visibility_changes(
    s: Session,
    brand_id: uuid.UUID,
    f: Filters,
    days: int = 14,
    to: datetime | None = None,
) -> dict[str, Any]:
    """Competitors that gained or lost >= MIN_SHIFT on >= MIN_PROMPTS
    prompts between the two windows, with a significant pooled change."""
    to = to or datetime.now(UTC)
    start, mid = _windows(days, to)
    fb = replace(f, date_from=start, date_to=mid)
    fa = replace(f, date_from=mid, date_to=to)
    comparable, reason = _comparable(s, brand_id, fb, fa)
    pb, kb = _per_prompt(s, brand_id, fb)
    pa, ka = _per_prompt(s, brand_id, fa)
    shared = [pid for pid in pa if pid in pb]
    out: dict[str, Any] = {
        "comparable": comparable,
        "reason": reason,
        "prompts": len(shared),
        "changes": [],
    }
    if not comparable:
        return out
    if len(shared) < MIN_PROMPTS:
        out["reason"] = _FEW
        return out
    where_b, params_b = _where(brand_id, fb)
    cited_before = set(
        s.scalars(
            text(
                "SELECT DISTINCT c.domain FROM citation c "
                "JOIN observation o ON o.id = c.observation_id "
                f"WHERE {where_b} AND {_DONE}"
            ),
            params_b,
        )
    )
    entries = []
    for cid, name, etype in _entities(s, brand_id):
        if etype != "competitor":
            continue
        moved: dict[str, list[tuple[uuid.UUID, float, int, int, int, int]]] = {
            "up": [],
            "down": [],
        }
        for pid in shared:
            (_, nb), (_, na) = pb[pid], pa[pid]
            k1, k2 = kb.get((pid, cid), 0), ka.get((pid, cid), 0)
            # Rounded: 3/10 - 2/10 is 0.0999... in floats, and a
            # one-answer shift at n=10 must count as MIN_SHIFT.
            shift = round(k2 / na - k1 / nb, 9)
            if shift >= MIN_SHIFT:
                moved["up"].append((pid, shift, k1, nb, k2, na))
            elif -shift >= MIN_SHIFT:
                moved["down"].append((pid, shift, k1, nb, k2, na))
        for direction, rows in moved.items():
            if len(rows) < MIN_PROMPTS:
                continue
            before = rate(sum(r[2] for r in rows), sum(r[3] for r in rows))
            after = rate(sum(r[4] for r in rows), sum(r[5] for r in rows))
            d = delta(before, after)
            if d["label"] != ("increase" if direction == "up" else "decrease"):
                continue
            rows.sort(key=lambda r: (-abs(r[1]), pa[r[0]][0]))
            pids = [r[0] for r in rows]
            entries.append(
                {
                    "competitor_id": cid,
                    "name": name,
                    "direction": direction,
                    "before": before,
                    "after": after,
                    "delta": d,
                    "prompts": [
                        {
                            "prompt_id": pid,
                            "text": pa[pid][0],
                            "before": rate(k1, nb),
                            "after": rate(k2, na),
                        }
                        for pid, _, k1, nb, k2, na in rows
                    ],
                    **_evidence(s, brand_id, fa, cid, pids, cited_before),
                }
            )
    entries.sort(key=lambda e: (-abs(e["delta"]["value"]), e["name"]))
    out["changes"] = entries
    return out


def _evidence(
    s: Session,
    brand_id: uuid.UUID,
    fa: Filters,
    cid: uuid.UUID,
    pids: list[uuid.UUID],
    cited_before: set[str],
) -> dict[str, Any]:
    """After-window answers on the moved prompts that name the competitor:
    their engines, newly cited domains, and up to EVIDENCE_CAP ids."""
    where, params = _where(brand_id, replace(fa, prompt_ids=pids))
    p = {**params, "cid": cid}
    naming = (
        "JOIN mention mn ON mn.observation_id = o.id "
        "AND mn.entity_type = 'competitor' AND mn.entity_id = :cid "
        f"WHERE {where} AND {_DONE}"
    )
    engines = list(
        s.scalars(
            text(
                "SELECT DISTINCT e.code FROM observation o "
                "JOIN engine e ON e.id = o.engine_id "
                f"{naming} ORDER BY 1"
            ),
            p,
        )
    )
    domains = [
        d
        for (d,) in s.execute(
            text(
                "SELECT c.domain FROM citation c "
                f"JOIN (SELECT o.id FROM observation o {naming}) a "
                "ON a.id = c.observation_id GROUP BY c.domain "
                "ORDER BY count(DISTINCT c.observation_id) DESC, c.domain"
            ),
            p,
        ).tuples()
        if d not in cited_before
    ]
    ids = list(
        s.scalars(
            text(
                f"SELECT o.id FROM observation o {naming} "
                f"ORDER BY o.requested_at DESC, o.id LIMIT {EVIDENCE_CAP}"
            ),
            p,
        )
    )
    return {
        "engines": engines,
        "new_citing_domains": domains,
        "observation_ids": ids,
    }
