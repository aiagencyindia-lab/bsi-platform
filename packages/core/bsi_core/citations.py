"""Citation intelligence: who the engine cites, per domain (PRD F06).

Read-only SQL over the citations already stored. Nothing here fetches a
cited page: the stored URL is a Vertex redirect and no title is kept.
"""

import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import models as m
from .matching import is_owned
from .metrics import Filters, _where
from .recommend import _rival_domains

OWNERS = ("brand", "rival", "third_party")
SOURCE_TYPES = ("vendor", "video", "community", "review", "other")
# ponytail: a keyword heuristic, labelled as such in the API. A licensed
# source classifier would replace this table, not the callers.
_KEYWORDS = {
    "video": ("youtube", "vimeo"),
    "community": ("reddit", "quora", "stackexchange"),
    "review": ("review", "g2.com", "capterra", "trustpilot", "mouthshut"),
}
EVIDENCE_CAP = 20


def source_type(domain: str, owner: str) -> str:
    if owner != "third_party":
        return "vendor"
    for kind, words in _KEYWORDS.items():
        if any(w in domain for w in words):
            return kind
    return "other"


def sources(
    s: Session, brand_id: uuid.UUID, f: Filters
) -> list[dict[str, Any]]:
    """One row per cited domain, most cited first.

    Uses metrics._where so the page agrees with the citation-rate tile:
    every done answer counts, whatever its prompt's status. `gap` is PRD
    F06's definition - two or more active rivals named in the citing
    answers, the brand never, on a domain that is not itself rival- or
    brand-owned. A rival's own domain is not an outreach opportunity.
    """
    where, params = _where(brand_id, f)
    base = (
        "FROM citation c JOIN observation o ON o.id = c.observation_id "
        f"WHERE {where} AND o.status = 'done'"
    )
    totals = s.execute(
        text(
            "SELECT c.domain, count(DISTINCT o.id) AS answers, "
            "count(DISTINCT o.prompt_id) AS prompts, "
            "min(o.requested_at) AS first_seen, "
            "max(o.requested_at) AS last_seen, "
            "count(DISTINCT o.id) FILTER (WHERE EXISTS ("
            "  SELECT 1 FROM mention mn WHERE mn.observation_id = o.id "
            "  AND mn.entity_type = 'brand')) AS brand_named "
            f"{base} GROUP BY c.domain "
            "ORDER BY count(DISTINCT o.id) DESC, c.domain"
        ),
        params,
    ).all()
    if not totals:
        return []
    rivals: dict[str, list[dict[str, Any]]] = {}
    for domain, name, k in s.execute(
        text(
            "SELECT c.domain, cp.name, count(DISTINCT o.id) "
            "FROM citation c JOIN observation o ON o.id = c.observation_id "
            "JOIN mention mn ON mn.observation_id = o.id "
            "  AND mn.entity_type = 'competitor' "
            "JOIN competitor cp ON cp.id = mn.entity_id "
            "  AND cp.status = 'active' "
            f"WHERE {where} AND o.status = 'done' "
            "GROUP BY c.domain, cp.name ORDER BY c.domain, 3 DESC, 2"
        ),
        params,
    ).all():
        rivals.setdefault(domain, []).append({"name": name, "answers": k})
    evidence: dict[str, list[uuid.UUID]] = {}
    for domain, oid, _ in s.execute(
        text(
            f"SELECT DISTINCT c.domain, o.id, o.requested_at {base} "
            "ORDER BY c.domain, o.requested_at DESC, o.id"
        ),
        params,
    ).all():
        ids = evidence.setdefault(domain, [])
        if len(ids) < EVIDENCE_CAP:
            ids.append(oid)
    hosts = list(
        s.scalars(select(m.Domain.host).where(m.Domain.brand_id == brand_id))
    )
    rival_hosts = _rival_domains(s, brand_id)
    out = []
    for r in totals:
        owner = (
            "brand"
            if is_owned(r.domain, hosts)
            else "rival"
            if is_owned(r.domain, rival_hosts)
            else "third_party"
        )
        named = rivals.get(r.domain, [])
        out.append(
            {
                "domain": r.domain,
                "owner": owner,
                "source_type": source_type(r.domain, owner),
                "answers": r.answers,
                "prompts": r.prompts,
                "first_seen": r.first_seen,
                "last_seen": r.last_seen,
                "brand_named": r.brand_named,
                "rivals": named,
                "gap": (
                    owner == "third_party"
                    and r.brand_named == 0
                    and len(named) >= 2
                ),
                "observation_ids": evidence.get(r.domain, []),
            }
        )
    return out


def reflag_citations(s: Session, brand_id: uuid.UUID) -> int:
    """Recompute citation.is_brand_owned for one brand's answers from its
    declared domains as they are now; returns the rows changed.

    Host match as matching.is_owned: equal, or a dot then the host. No
    LIKE, so "_" or "%" in a host is not a wildcard.
    """
    owned = (
        "EXISTS (SELECT 1 FROM domain d WHERE d.brand_id = :b "
        "AND (c.domain = d.host "
        "OR right(c.domain, length(d.host) + 1) = '.' || d.host))"
    )
    res = s.execute(
        text(
            f"UPDATE citation c SET is_brand_owned = {owned} "
            "FROM observation o "
            "WHERE o.id = c.observation_id AND o.brand_id = :b "
            f"AND c.is_brand_owned IS DISTINCT FROM {owned}"
        ),
        {"b": brand_id},
    )
    return int(res.rowcount)  # type: ignore[attr-defined]
