"""Content gaps (PRD F11, the gap half): (intent, topic) clusters of active
prompts, the brand's standing in each, and a model-free brief for the
clusters the brand is losing. Read-only SQL over stored answers."""

import uuid
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from . import models as m
from .competitors import _entities_and_hosts, owner_of
from .metrics import Filters, _where, rate
from .recommend import CONTENT_REASONS

EVIDENCE_CAP = 20
SOURCES_CAP = 10
LINKS_CAP = 10
NOTE = (
    "Page type and structure are templates by intent, not a judgement of "
    "the site."
)
PAGE_TYPES = {
    "comparison": "comparison page",
    "alternative": "alternatives page",
    "recommendation": "best-of round-up",
    "informational": "guide",
    "commercial": "category page",
    "transactional": "product page",
    "problem-based": "how-to",
    "persona-specific": "solution page",
    "industry-specific": "solution page",
    "geographic": "local page",
}
# Heading templates per page type; {q} rows repeat once per prompt.
STRUCTURES = {
    "comparison page": [
        "H1: {topic}: how the options compare",
        "H2: {q}",
        "H2: Side-by-side table",
        "H2: Sources and evidence",
        "H2: FAQ",
    ],
    "alternatives page": [
        "H1: Alternatives for {topic}",
        "H2: {q}",
        "H2: How to choose",
        "H2: Sources and evidence",
    ],
    "best-of round-up": [
        "H1: Best {topic}",
        "H2: Our picks",
        "H2: {q}",
        "H2: How we chose",
        "H2: Sources and evidence",
    ],
    "guide": [
        "H1: {topic}: a guide",
        "H2: {q}",
        "H2: Sources and evidence",
        "H2: FAQ",
    ],
    "category page": ["H1: {topic}", "H2: {q}", "H2: Products", "H2: FAQ"],
    "product page": ["H1: {topic}", "H2: {q}", "H2: Specifications", "H2: FAQ"],
    "how-to": [
        "H1: {topic}: problems and fixes",
        "H2: {q}",
        "H2: Step by step",
        "H2: Sources and evidence",
    ],
    "solution page": [
        "H1: {topic}",
        "H2: {q}",
        "H2: Who it is for",
        "H2: Sources and evidence",
    ],
    "local page": [
        "H1: {topic}",
        "H2: {q}",
        "H2: Locations and availability",
        "H2: FAQ",
    ],
}
_BASE = (
    "o.status = 'done' AND p.status = 'active' "
    "AND p.intent IS NOT NULL AND p.topic IS NOT NULL"
)
_FROM = "FROM observation o JOIN prompt p ON p.id = o.prompt_id"


def unlabelled(s: Session, brand_id: uuid.UUID) -> int:
    return int(
        s.scalar(
            select(func.count())
            .select_from(m.Prompt)
            .where(
                m.Prompt.brand_id == brand_id,
                m.Prompt.status == "active",
                (m.Prompt.intent.is_(None)) | (m.Prompt.topic.is_(None)),
            )
        )
        or 0
    )


def brief(c: dict[str, Any], brand: str) -> dict[str, Any]:
    """The model-free content brief for a gap cluster.

    `brand` is unused; it is kept for the interface.
    """
    page_type = PAGE_TYPES[c["intent"]]
    queries = [p["text"] for p in c["prompts"]]
    structure: list[str] = []
    for h in STRUCTURES[page_type]:
        if "{q}" in h:
            structure += [h.format(q=q) for q in queries]
        else:
            structure.append(h.format(topic=c["topic"]))
    return {
        "target_queries": queries,
        "page_type": page_type,
        "structure": structure,
        "competitors": [r["name"] for r in c["rivals"]],
        # Third-party domains first (stable: keeps answers-desc within each).
        "sources": sorted(
            (x for x in c["sources"] if x["owner"] != "brand"),
            key=lambda x: x["owner"] != "third_party",
        ),
        "internal_links": c["brand_urls"],
        "evidence": {
            "prompt_ids": [str(p["prompt_id"]) for p in c["prompts"]],
            "observation_ids": [str(o) for o in c["absent_obs"]],
        },
        "note": NOTE,
    }


def clusters(
    s: Session, brand_id: uuid.UUID, f: Filters
) -> list[dict[str, Any]]:
    where, params = _where(brand_id, f)
    brand = s.get_one(m.Brand, brand_id).name
    _, hosts = _entities_and_hosts(s, brand_id)
    brand_hosts = hosts[brand_id]
    rival_hosts = [h for e, hs in hosts.items() if e != brand_id for h in hs]
    answers = s.execute(
        text(
            "SELECT p.intent, p.topic, o.prompt_id, p.text, o.id, "
            "o.requested_at, "
            "EXISTS (SELECT 1 FROM mention mn WHERE mn.observation_id = o.id "
            "  AND mn.entity_type = 'brand') AS present, "
            "EXISTS (SELECT 1 FROM mention mn JOIN competitor cp "
            "  ON cp.id = mn.entity_id WHERE mn.observation_id = o.id "
            "  AND mn.entity_type = 'competitor' AND cp.status = 'active') "
            "  AS rival, "
            "EXISTS (SELECT 1 FROM citation c WHERE c.observation_id = o.id "
            "  AND c.is_brand_owned) AS cited, "
            "e.absence_reason "
            f"{_FROM} LEFT JOIN extraction e ON e.observation_id = o.id "
            f"WHERE {where} AND {_BASE} "
            "ORDER BY p.intent, p.topic, o.prompt_id, o.requested_at DESC, o.id"
        ),
        params,
    ).all()
    rivals = s.execute(
        text(
            "SELECT p.intent, p.topic, cp.id, cp.name, "
            "count(DISTINCT o.id) AS answers "
            "FROM mention mn JOIN competitor cp ON cp.id = mn.entity_id "
            "JOIN observation o ON o.id = mn.observation_id "
            "JOIN prompt p ON p.id = o.prompt_id "
            f"WHERE {where} AND {_BASE} AND mn.entity_type = 'competitor' "
            "AND cp.status = 'active' "
            "GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 5 DESC, 4"
        ),
        params,
    ).all()
    sources = s.execute(
        text(
            "SELECT p.intent, p.topic, c.domain, "
            "count(DISTINCT o.id) AS answers "
            "FROM citation c JOIN observation o ON o.id = c.observation_id "
            "JOIN prompt p ON p.id = o.prompt_id "
            f"WHERE {where} AND {_BASE} "
            "GROUP BY 1, 2, 3 ORDER BY 1, 2, 4 DESC, 3"
        ),
        params,
    ).all()
    urls = s.execute(
        text(
            "SELECT DISTINCT p.intent, p.topic, c.url "
            "FROM citation c JOIN observation o ON o.id = c.observation_id "
            "JOIN prompt p ON p.id = o.prompt_id "
            f"WHERE {where} AND {_BASE} AND c.is_brand_owned ORDER BY 1, 2, 3"
        ),
        params,
    ).all()
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for r in answers:
        c = by_key.setdefault(
            (r.intent, r.topic),
            {
                "n": 0,
                "present": 0,
                "cited": 0,
                "rival_absent": 0,
                "reasons": Counter(),
                "prompts": {},
                "absent_obs": [],
            },
        )
        c["n"] += 1
        c["present"] += r.present
        c["cited"] += r.cited
        p = c["prompts"].setdefault(
            r.prompt_id,
            {"prompt_id": r.prompt_id, "text": r.text, "n": 0, "absent": 0},
        )
        p["n"] += 1
        if not r.present:
            p["absent"] += 1
            c["absent_obs"].append((r.requested_at, r.id))
            c["rival_absent"] += r.rival
            if r.absence_reason:
                c["reasons"][r.absence_reason] += 1
    riv: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in rivals:
        riv[(r.intent, r.topic)].append(
            {"competitor_id": r.id, "name": r.name, "answers": r.answers}
        )
    src: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in sources:
        src[(r.intent, r.topic)].append(
            {
                "domain": r.domain,
                "answers": r.answers,
                "owner": owner_of(r.domain, brand_hosts, rival_hosts),
            }
        )
    lnk: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in urls:
        lnk[(r.intent, r.topic)].append(r.url)
    out = []
    for (intent, topic), c in by_key.items():
        n, absent = c["n"], c["n"] - c["present"]
        top = riv[(intent, topic)][:1]
        top_rival = (
            {
                "name": top[0]["name"],
                "competitor_id": top[0]["competitor_id"],
                **rate(top[0]["answers"], n),
            }
            if top
            else None
        )
        b = rate(c["present"], n)
        reasons = dict(c["reasons"])
        # Top reason: highest count, ties broken by reason name.
        reason = (
            min(reasons, key=lambda k: (-reasons[k], k)) if reasons else None
        )
        gap = (
            absent * 2 >= n
            and c["rival_absent"] >= 1
            and reason in CONTENT_REASONS
        )
        row: dict[str, Any] = {
            "intent": intent,
            "topic": topic,
            "key": f"cluster:{intent}:{topic}",
            "prompts": sorted(
                c["prompts"].values(),
                key=lambda p: (-(p["absent"] / p["n"]), p["text"]),
            ),
            "n": n,
            "brand": b,
            "absent": absent,
            "rival_absent": c["rival_absent"],
            "reasons": reasons,
            "reason": reason,
            "rivals": riv[(intent, topic)],
            "top_rival": top_rival,
            "spread": (b["value"] - top_rival["value"]) if top_rival else None,
            "cited": rate(c["cited"], n),
            "sources": src[(intent, topic)][:SOURCES_CAP],
            "brand_urls": lnk[(intent, topic)][:LINKS_CAP],
            "gap": gap,
            # The cluster's newest absent answers (id breaks ties), capped:
            # the brief's evidence.
            "absent_obs": [i for _, i in sorted(c["absent_obs"], reverse=True)][
                :EVIDENCE_CAP
            ],
        }
        row["brief"] = brief(row, brand) if gap else None
        out.append(row)
    out.sort(
        key=lambda r: (
            r["spread"] is None,
            r["spread"] or 0.0,
            -r["n"],
            r["key"],
        )
    )
    return out
