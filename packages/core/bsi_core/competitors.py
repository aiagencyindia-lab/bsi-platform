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
    delta,
    rate,
    window_versions,
)
from .rivals import feed_evidence

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


def _entities_and_hosts(
    s: Session, brand_id: uuid.UUID
) -> tuple[list[tuple[uuid.UUID, str, str]], dict[uuid.UUID, list[str]]]:
    """metrics._entities (the brand, then its active competitors) and each
    one's declared domains (the brand's `domain` rows, a competitor's
    `domains` column), from one read of the competitors: a competitor
    activated mid-request is in both or in neither."""
    brand = s.get_one(m.Brand, brand_id)
    competitors = s.scalars(
        select(m.Competitor)
        .where(
            m.Competitor.brand_id == brand_id,
            m.Competitor.status == "active",
        )
        .order_by(m.Competitor.created_at, m.Competitor.name)
    ).all()
    hosts = {
        brand_id: list(
            s.scalars(
                select(m.Domain.host).where(m.Domain.brand_id == brand_id)
            )
        )
    } | {c.id: list(c.domains) for c in competitors}
    entities = [(brand.id, brand.name, "brand")] + [
        (c.id, c.name, "competitor") for c in competitors
    ]
    return entities, hosts


def entity_metrics(
    s: Session, brand_id: uuid.UUID, f: Filters
) -> list[dict[str, Any]]:
    """One row for the brand and one per active competitor, best mention
    rate first (brand wins ties, then name). A fixed number of queries,
    whatever the number of competitors: each grouped by entity."""
    where, params = _where(brand_id, f)
    entities, hosts = _entities_and_hosts(s, brand_id)
    brand_hosts = hosts[brand_id]
    rival_hosts = [
        h for eid, hs in hosts.items() if eid != brand_id for h in hs
    ]
    # One read of the competitors serves every number below: the hosts,
    # the rows and the sov total all see the same active set.
    pairs = [(eid, h) for eid, _, _ in entities for h in hosts.get(eid, [])]
    p = {
        **params,
        "eids": [eid for eid, _, _ in entities],
        "etypes": [etype for _, _, etype in entities],
        "peids": [eid for eid, _ in pairs],
        "phosts": [h for _, h in pairs],
    }
    base = f"WHERE {where} AND {_DONE}"
    # A mention names its entity by (type, id), as the brand row joins it.
    naming = (
        "JOIN mention mn ON mn.observation_id = o.id "
        "JOIN unnest(CAST(:eids AS uuid[]), CAST(:etypes AS text[])) "
        "AS e(id, type) ON mn.entity_id = e.id AND mn.entity_type = e.type "
    )
    tot = s.execute(
        text(
            "SELECT count(*) AS n, count(DISTINCT o.prompt_id) AS prompts "
            f"FROM observation o {base}"
        ),
        p,
    ).one()
    # A mention is unique per (observation, entity): a count of mention
    # rows is a count of answers naming the entity.
    stats = {
        r.entity_id: r
        for r in s.execute(
            text(f"""
            SELECT mn.entity_id,
              count(*) AS k_mention,
              count(*) FILTER (WHERE mn.rec_status = 'recommended') AS k_rec,
              count(DISTINCT o.prompt_id) AS prompts_cov,
              avg(mn.position) AS avg_pos,
              count(*) FILTER (WHERE mn.sentiment = 'positive') AS k_pos,
              count(*) FILTER (WHERE mn.sentiment = 'negative') AS k_neg
            FROM observation o {naming}{base}
            GROUP BY mn.entity_id"""),
            p,
        )
    }
    # The domain routes re-compute citation.is_brand_owned whenever a
    # brand domain is added or removed, so from then on the Overview
    # flag and k_cit agree.
    # Host match as matching.is_owned: equal, or a dot then the host.
    # No LIKE, so "_" or "%" in a host is not a wildcard.
    k_cit: dict[uuid.UUID, int] = dict(
        s.execute(
            text(
                "SELECT h.eid, count(DISTINCT o.id) FROM observation o "
                "JOIN citation c ON c.observation_id = o.id "
                "JOIN unnest(CAST(:peids AS uuid[]), CAST(:phosts AS text[])) "
                "AS h(eid, host) ON c.domain = h.host "
                "OR right(c.domain, length(h.host) + 1) = '.' || h.host "
                f"{base} GROUP BY h.eid"
            ),
            p,
        )
        .tuples()
        .all()
    )
    cited: dict[uuid.UUID, list[Any]] = {}
    for c in s.execute(
        text(f"""
        SELECT entity_id, domain, answers FROM (
          SELECT mn.entity_id, c.domain, count(DISTINCT o.id) AS answers,
            row_number() OVER (
              PARTITION BY mn.entity_id
              ORDER BY count(DISTINCT o.id) DESC, c.domain) AS rn
          FROM citation c JOIN observation o ON o.id = c.observation_id
          {naming}{base}
          GROUP BY mn.entity_id, c.domain) t
        WHERE rn <= {CITING_DOMAINS} ORDER BY entity_id, rn"""),
        p,
    ):
        cited.setdefault(c.entity_id, []).append(c)
    sov_total = sum(r.k_mention for r in stats.values())
    rows: list[dict[str, Any]] = []
    for eid, name, etype in entities:
        r = stats.get(eid)
        k = r.k_mention if r else 0
        pos = rate(r.k_pos if r else 0, k)
        neg = rate(r.k_neg if r else 0, k)
        rows.append(
            {
                "entity_id": eid,
                "name": name,
                "type": etype,
                "mention_rate": rate(k, tot.n),
                "recommendation_rate": rate(r.k_rec if r else 0, tot.n),
                "citation_rate": rate(k_cit.get(eid, 0), tot.n),
                "prompt_coverage": rate(r.prompts_cov if r else 0, tot.prompts),
                "sov": rate(k, sov_total),
                "avg_position": {
                    "value": float(r.avg_pos)
                    if r and r.avg_pos is not None
                    else None,
                    "n_mentioned": k,
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
                    for c in cited.get(eid, [])
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
    return {
        "before": {"from": start, "to": mid, "entities": before},
        "after": {"from": mid, "to": to, "entities": after},
        "comparable": comparable,
        "reason": reason,
        "deltas": _deltas(before, after) if comparable else None,
    }


def _deltas(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Per after-window entity, `delta` of each DELTA_METRICS rate. An
    entity missing from `before` (a competitor activated between the two
    entity_metrics reads) is compared with a zero-count rate over the
    before window's done answers."""
    by_id = {r["entity_id"]: r for r in before}
    n = before[0]["mention_rate"]["n"] if before else 0
    zero = {k: rate(0, n) for k in DELTA_METRICS}
    return {
        r["entity_id"]: {
            k: delta(by_id.get(r["entity_id"], zero)[k], r[k])
            for k in DELTA_METRICS
        }
        for r in after
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


def _shift(k1: int, nb: int, k2: int, na: int) -> float:
    # Rounded: 3/10 - 2/10 is 0.0999... in floats, and a one-answer
    # shift at n=10 must count as MIN_SHIFT.
    return round(k2 / na - k1 / nb, 9)


def _moved(k1: int, nb: int, k2: int, na: int) -> str | None:
    """ "up", "down" or None: did one prompt move by >= MIN_SHIFT?"""
    shift = _shift(k1, nb, k2, na)
    if shift >= MIN_SHIFT:
        return "up"
    if -shift >= MIN_SHIFT:
        return "down"
    return None


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
        "window": {"before_from": start, "split": mid, "to": to},
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
            direction = _moved(k1, nb, k2, na)
            if direction is not None:
                moved[direction].append(
                    (pid, _shift(k1, nb, k2, na), k1, nb, k2, na)
                )
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
    site = feed_evidence(
        s, brand_id, sorted({e["competitor_id"] for e in entries}), mid, to
    )
    for e in entries:
        e.update(site[e["competitor_id"]])
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
