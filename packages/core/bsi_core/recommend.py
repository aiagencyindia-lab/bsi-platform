"""Recommendations: deterministic rules over a brand's stored evidence.

Rules decide what to recommend and templates decide how it reads. No model
is called, so nothing here can drift into promising an outcome; the
templates are tested for that directly.

Priority is reach x pressure x feasibility, every part stored beside the
product so the weighting is visible (PRD F12):

- reach: the share of the brand's answers the action touches, counted
  in one unit - done answers on active prompts - so a gap on a single
  prompt can outrank a thin citation spread over two. add_competitor is
  the exception: a suggested rival has no mentions to count, so its
  reach is the share of the three suggestion answers that named it;
- pressure: what is at stake there - the share of the relevant answers
  naming a rival, or the size of a gap waiting to be confirmed,
  depending on the type. add_competitor has nothing to measure, so it
  is 1.0 and priority there is reach x feasibility; fix_crawlability
  joins add_competitor as a judged, not measured, type: reach is 1.0
  and pressure is the check's severity weight. fix_entity is judged the
  same way.
- feasibility: how cheaply the operator can act, per type, below.

create_content is keyed per (intent, topic) gap cluster for labelled
prompts and per prompt for prompts not yet labelled.
"""

import hashlib
import logging
import re
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import groupby
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import delete, func, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from . import entity
from . import models as m
from .crawl import expected, family
from .matching import is_owned
from .metrics import Filters, prompt_metrics
from .pages import WEIGHTS_VERSION
from .rivals import slug_words, topic_words
from .suggest import ANSWERS

log = logging.getLogger("bsi.recommend")

# Confirming a competitor or scheduling samples takes minutes; content
# takes weeks; outreach takes weeks and depends on someone else.
FEASIBILITY = {
    "add_competitor": 0.9,
    "sample_more": 1.0,
    # A robots or head-tag change is minutes of work once someone with
    # site access is found; that person is the cost.
    "fix_crawlability": 0.8,
    # Markup is minutes of work; a Wikidata edit needs sources and can
    # be reverted by its editors.
    "fix_entity": 0.7,
    # Editing a page that exists is less work than writing one.
    "optimize_page": 0.6,
    "create_content": 0.4,
    # Writing content, as create_content; the rival's move is the prompt.
    "respond_to_rival_content": 0.4,
    "pursue_citation_source": 0.3,
}
# Nothing measures a site check against answers, so pressure is the
# check's severity, stated as a weight the operator can see.
PRESSURE_BY_SEVERITY = {"high": 1.0, "medium": 0.5, "low": 0.2}
# 3 recommended 72 citation sources on an 80-answer brand, burying every
# content gap; 5 halves that (findings-slice6 section 3).
MIN_CITING_ANSWERS = 5
MIN_COMPETITOR_EVIDENCE = 2
# More samples than this is a change to sampling, not a task.
SAMPLE_MORE_WITHIN = 10
CONTENT_REASONS = ("competitor_dominance", "not_retrieved")
# Below this AI Citability Score a scored page is worth a task.
PAGE_SCORE_THRESHOLD = 70
# Rival pages count as new for this long after first_seen_at.
RIVAL_DAYS = 14
# Five or more new rival pages on a topic is a full-pressure signal.
RIVAL_PAGES_SATURATION = 5
RIVAL_PAGES_CAP = 10


@dataclass
class Candidate:
    type: str
    subject_key: str
    title: str
    body: str
    evidence: dict[str, Any]
    reach: float
    pressure: float

    @property
    def feasibility(self) -> float:
        return FEASIBILITY[self.type]

    @property
    def priority(self) -> float:
        return round(self.reach * self.pressure * self.feasibility, 4)


def names(items: list[str]) -> str:
    """The first three, joined as a sentence would."""
    top = items[:3]
    if len(top) < 2:
        return "".join(top)
    return ", ".join(top[:-1]) + " and " + top[-1]


def citation_copy(
    brand: str, domain: str, k: int, rivals: list[str]
) -> tuple[str, str]:
    named = f" Those answers name {names(rivals)} instead." if rivals else ""
    return (
        f"Earn coverage on {domain}",
        f"{domain} is cited in {k} answers that do not mention {brand}."
        f"{named} Answer engines draw on it for these prompts. "
        f"Metric to watch: {brand}'s mention rate on the prompts that "
        "cite it.",
    )


def content_copy(
    brand: str,
    prompt: str,
    absent: int,
    n: int,
    reason: str,
    rivals: list[str],
) -> tuple[str, str]:
    if reason == "not_retrieved":
        why = (
            f"the extractor reports {brand} was not retrieved at all, which "
            "points at missing or hard-to-find content rather than "
            "competition"
        )
    else:
        led = f" ({names(rivals)})" if rivals else ""
        why = f"the extractor attributes this to answers led by rivals{led}"
    return (
        f"Publish content that answers “{prompt}”",
        f"{brand} is absent from {absent} of {n} answers to this prompt; "
        f"{why}. Metric to watch: {brand}'s mention rate on this prompt.",
    )


def cluster_copy(
    brand: str,
    intent: str,
    topic: str,
    page_type: str,
    worst: list[str],
    absent: int,
    n: int,
    rivals: list[str],
) -> tuple[str, str]:
    asks = " and ".join(f"“{q}”" for q in worst[:2])
    led = f" Rivals named in this cluster: {names(rivals)}." if rivals else ""
    # ponytail: first-letter rule; every PAGE_TYPES value reads right by it.
    art = "an" if page_type[0] in "aeiou" else "a"
    return (
        f"Publish {art} {page_type} for {topic} ({intent})",
        f"{brand} is absent from {absent} of {n} answers in this cluster, "
        f"led by {asks}.{led} {art.capitalize()} {page_type} that answers "
        "these prompts directly gives engines something of the brand's "
        "own to retrieve. "
        f"Metric to watch: {brand}'s mention rate on the cluster's prompts.",
    )


def _last_segment(url: str) -> str:
    u = urlsplit(url)
    segs = [p for p in u.path.split("/") if p]
    return segs[-1] if segs else (u.hostname or url)


def rival_content_copy(
    brand: str,
    topic: str,
    intent: str,
    page_type: str,
    pages_by_rival: list[tuple[str, list[str]]],
    n: int,
    brand_rate: float | None,
    top_rival: tuple[str, float | None] | None,
    gap: bool,
) -> tuple[str, str]:
    """A competitor published on a topic where the brand is behind."""
    k = sum(len(urls) for _, urls in pages_by_rival)
    rivals = [name for name, _ in pages_by_rival]
    if len(rivals) == 1:
        plural = "s" if k != 1 else ""
        title = f"{rivals[0]} published {k} new {topic} page{plural}"
    else:
        title = f"{k} new {topic} pages from {names(rivals)}"
    moves = " ".join(
        f"{name} published {len(urls)} "
        f"new page{'s' if len(urls) != 1 else ''}: "
        + ", ".join(_last_segment(u) for u in urls[:3])
        + "."
        for name, urls in pages_by_rival
    )
    if gap or brand_rate is None or top_rival is None:
        standing = f"This cluster is a content gap for {brand}."
    else:
        name, rate_ = top_rival
        theirs = f"{rate_:.0%}" if rate_ is not None else "—"
        standing = (
            f"{brand} is named in {brand_rate:.0%} of {n} answers; "
            f"{name} in {theirs}."
        )
    # ponytail: first-letter rule; every PAGE_TYPES value reads right by it.
    art = "an" if page_type[0] in "aeiou" else "a"
    return (
        title,
        f"{moves} {standing} Publish {art} {page_type} on {topic} that "
        "answers these prompts directly, so engines have something of the "
        "brand's own to retrieve alongside the rival's. "
        f"Metric to watch: {brand}'s mention rate on the {topic} cluster.",
    )


def page_copy(
    brand: str,
    url: str,
    topic: str,
    n_prompts: int,
    score: int,
    suggestions: dict[str, list[dict[str, Any]]],
) -> tuple[str, str]:
    u = urlsplit(url)
    where = f"{u.hostname}{u.path if u.path != '/' else ''}"
    steps = [
        s["text"]
        for key in ("add", "rewrite", "evidence_to_add")
        for s in suggestions.get(key, [])
    ][:3]
    first = f" First steps: {' '.join(steps)}" if steps else ""
    return (
        f"Improve {where} for {topic}",
        f"{url} scores {score}/100 on the AI Citability Score "
        f"({WEIGHTS_VERSION}) against the {topic} cluster.{first} "
        f"Metric to watch: {brand}'s mention rate on the cluster's "
        f"{n_prompts} prompts.",
    )


def competitor_copy(name: str, evidence: int) -> tuple[str, str]:
    return (
        f"Confirm {name} as a competitor",
        f"{name} appeared in {evidence} of the {ANSWERS} answers used to "
        "suggest competitors but is not yet measured: until it is "
        "confirmed it is left out of share of voice and every rival rate. "
        "Metric to watch: share of voice, which then includes it.",
    )


def sample_copy(
    brand: str, prompt: str, n: int, needs: int, rival: str
) -> tuple[str, str]:
    more = needs - n
    return (
        f"Take {more} more sample{'s' if more != 1 else ''} of “{prompt}”",
        f"At n={n} this prompt cannot yet tell {brand} apart from {rival}; "
        f"if the observed rates hold, it can at about n={needs}. This is a "
        "projection from current rates and moves as they do. Metric to "
        "watch: whether this prompt separates.",
    )


_CRAWL_TITLES = {
    "home_unreachable": "{domain} does not answer",
    "bot_blocked": "{domain} blocks {bot} in robots.txt",
    "bot_ua_blocked": "{domain} turns {bot} away",
    "sitemap_missing": "{domain} has no sitemap",
    "sitemap_invalid": "The sitemap on {domain} is not a sitemap",
    "org_schema_missing": "{domain} declares no Organization",
    "title_missing": "The {domain} homepage has no title",
    "description_missing": "The {domain} homepage has no description",
    "h1_missing": "The {domain} homepage has no H1",
    "canonical_missing": "The {domain} homepage has no canonical",
    "llms_missing": "{domain} has no llms.txt",
}


def crawl_copy(
    brand: str, domain: str, check: dict[str, Any]
) -> tuple[str, str]:
    code = str(check["code"])
    bot = code.split(":", 1)[1] if ":" in code else ""
    title = _CRAWL_TITLES[family(code)].format(domain=domain, bot=bot)
    body = (
        f"The weekly audit of {check['url']} observed: {check['observed']}. "
        f"Expected: {expected(code)} "
        f"An engine that cannot read {brand}'s own pages has only other "
        "sites to describe it from. "
        "Metric to watch: this check on the next weekly audit, then the "
        "citation rate."
    )
    return title, body


_ENTITY_TITLES = {
    "org_name_mismatch": "Fix the Organization name on {domain}",
    "org_url_mismatch": "Point the Organization url on {domain} at "
    "{brand}'s domain",
    "org_logo_missing": "Add a logo to the Organization on {domain}",
    "org_sameas_missing": "List {brand}'s profiles in sameAs on {domain}",
    "website_schema_missing": "{domain} declares no WebSite",
    "title_brand_missing": "The {domain} homepage title omits {brand}",
    "about_missing": "The {domain} homepage links no About page",
    "about_unreachable": "The About page on {domain} does not answer",
    "about_brand_missing": "The About page on {domain} does not name {brand}",
    "wikidata_missing": "Create or claim {brand}'s Wikidata item",
    "wikidata_name_mismatch": "Wikidata names {brand} differently",
    "wikidata_logo_missing": "Add a logo to {brand}'s Wikidata item",
    "social_links_conflict": "Align social profiles between {domain} and "
    "Wikidata",
}


def entity_copy(
    brand: str, domain: str, check: dict[str, Any]
) -> tuple[str, str]:
    fam = family(str(check["code"]))
    title = _ENTITY_TITLES[fam].format(domain=domain, brand=brand)
    body = (
        f"The weekly audit of {check['url']} observed: {check['observed']}. "
        f"Expected: {entity.EXPECTED[fam]} "
        "Engines resolve a brand to one entity by agreement between its "
        "site markup and public knowledge sources; a disagreement makes "
        f"{brand} harder to identify and cite. "
        "Metric to watch: this check on the next weekly audit, then the "
        "mention rate."
    )
    return title, body


_RIVALS = (
    "FROM mention mn JOIN competitor cp ON cp.id = mn.entity_id "
    "WHERE mn.observation_id = ANY(:obs) AND mn.entity_type = 'competitor' "
    "AND cp.status = 'active'"
)


def _rivals(s: Session, obs: list[uuid.UUID]) -> tuple[list[str], float]:
    """Active rivals named in these answers, most often first, and the
    share of the answers that name at least one."""
    rows = s.execute(
        text(
            "SELECT cp.name, count(DISTINCT mn.observation_id) "
            f"{_RIVALS} GROUP BY cp.name ORDER BY 2 DESC, 1"
        ),
        {"obs": obs},
    ).all()
    named = s.scalar(
        text(f"SELECT count(DISTINCT mn.observation_id) {_RIVALS}"),
        {"obs": obs},
    )
    return [r[0] for r in rows], (named or 0) / len(obs)


def _rival_domains(s: Session, brand_id: uuid.UUID) -> list[str]:
    """Domains declared on the brand's active competitors.

    Suggested (unconfirmed) competitors are excluded, same as everywhere
    else in the platform.
    """
    rows = s.scalars(
        select(m.Competitor.domains).where(
            m.Competitor.brand_id == brand_id,
            m.Competitor.status == "active",
        )
    ).all()
    return [d for domains in rows for d in domains]


def _citations(
    s: Session,
    brand_id: uuid.UUID,
    brand: str,
    total: int,
    rival_domains: list[str],
) -> list[Candidate]:
    rows = s.execute(
        text(
            "SELECT c.domain, array_agg(DISTINCT o.id) AS obs, "
            "array_agg(DISTINCT o.prompt_id) AS prompts "
            "FROM citation c "
            "JOIN observation o ON o.id = c.observation_id "
            "JOIN prompt p ON p.id = o.prompt_id "
            "WHERE o.brand_id = :brand AND o.status = 'done' "
            "AND p.status = 'active' AND NOT c.is_brand_owned "
            "AND NOT EXISTS (SELECT 1 FROM mention mn "
            "  WHERE mn.observation_id = o.id "
            "  AND mn.entity_type = 'brand') "
            "GROUP BY c.domain HAVING count(DISTINCT o.id) >= :min "
            "ORDER BY count(DISTINCT o.id) DESC, c.domain"
        ),
        {"brand": brand_id, "min": MIN_CITING_ANSWERS},
    ).all()
    out = []
    for row in rows:
        # Only catches domains a rival has declared: adidas.com stays
        # invisible to this check until someone adds it to that
        # competitor's domains. Not guessed from the rival's name - a
        # false match would hide a real publisher, which is worse than
        # a visible miss the operator can correct.
        if is_owned(row.domain, rival_domains):
            continue
        obs = sorted(row.obs, key=str)
        rivals, pressure = _rivals(s, obs)
        title, body = citation_copy(brand, row.domain, len(obs), rivals)
        out.append(
            Candidate(
                "pursue_citation_source",
                row.domain,
                title,
                body,
                {
                    "domain": row.domain,
                    "observation_ids": [str(o) for o in obs],
                    "prompt_ids": sorted(str(p) for p in row.prompts),
                    "rivals": rivals,
                },
                len(obs) / total,
                pressure,
            )
        )
    return out


def _content(
    s: Session, brand_id: uuid.UUID, brand: str, total: int
) -> list[Candidate]:
    """Per-prompt rule for prompts without labels; labelled prompts are
    handled per cluster by `_content_clusters`."""
    rows = s.execute(
        text(
            "SELECT o.prompt_id, p.text, o.id, "
            "EXISTS (SELECT 1 FROM mention mn "
            "  WHERE mn.observation_id = o.id "
            "  AND mn.entity_type = 'brand') AS present, "
            "e.absence_reason "
            "FROM observation o "
            "JOIN prompt p ON p.id = o.prompt_id "
            "LEFT JOIN extraction e ON e.observation_id = o.id "
            "WHERE o.brand_id = :brand AND o.status = 'done' "
            "AND p.status = 'active' "
            "AND (p.intent IS NULL OR p.topic IS NULL) "
            "ORDER BY p.text, o.prompt_id, o.requested_at, o.id"
        ),
        {"brand": brand_id},
    ).all()
    out = []
    for pid, group in groupby(rows, key=lambda r: r.prompt_id):
        answers = list(group)
        absent = [r for r in answers if not r.present]
        if not absent or len(absent) * 2 < len(answers):
            continue
        reasons = Counter(r.absence_reason for r in absent if r.absence_reason)
        if not reasons:
            continue
        reason = reasons.most_common(1)[0][0]
        if reason not in CONTENT_REASONS:
            continue
        obs = [r.id for r in absent]
        rivals, pressure = _rivals(s, obs)
        title, body = content_copy(
            brand, answers[0].text, len(absent), len(answers), reason, rivals
        )
        out.append(
            Candidate(
                "create_content",
                str(pid),
                title,
                body,
                {
                    "prompt_ids": [str(pid)],
                    "observation_ids": [str(o) for o in obs],
                    "reason": reason,
                    "absent": len(absent),
                    "n": len(answers),
                },
                len(obs) / total,
                pressure,
            )
        )
    return out


def _cluster_candidate(
    c: dict[str, Any], key: str, brand: str, total: int
) -> Candidate:
    b = c["brief"]
    title, body = cluster_copy(
        brand,
        c["intent"],
        c["topic"],
        b["page_type"],
        b["target_queries"],
        c["absent"],
        c["n"],
        b["competitors"],
    )
    if key != c["key"]:
        title += " (new prompts)"
    return Candidate(
        "create_content",
        key,
        title,
        body,
        {
            # The brief once: its inner evidence is these two keys.
            **{k: v for k, v in b.items() if k != "evidence"},
            "prompt_ids": b["evidence"]["prompt_ids"],
            "observation_ids": b["evidence"]["observation_ids"],
            "cluster": {"intent": c["intent"], "topic": c["topic"]},
            "reason": c["reason"],
            "absent": c["absent"],
            "n": c["n"],
        },
        c["absent"] / total,
        c["rival_absent"] / c["absent"],
    )


def _content_clusters(
    s: Session,
    brand_id: uuid.UUID,
    brand: str,
    total: int,
    rows: list[dict[str, Any]],
) -> list[Candidate]:
    """One candidate per gap cluster of labelled prompts (PRD F11).

    A decided (accepted or dismissed) cluster is never raised again. Its
    prompts that no decided rec covers yet get their own candidate, keyed
    `<cluster key>:+<hash of those prompts>`, when they alone are a gap,
    even if the cluster as a whole no longer is.
    """
    from .gaps import clusters  # gaps imports CONTENT_REASONS from here

    decided = s.execute(
        select(m.Recommendation.subject_key, m.Recommendation.evidence).where(
            m.Recommendation.brand_id == brand_id,
            m.Recommendation.type == "create_content",
            m.Recommendation.status.in_(("accepted", "dismissed")),
            m.Recommendation.subject_key.startswith("cluster:"),
        )
    ).all()
    out = []
    for c in rows:
        key = c["key"]
        # Exact follow-up keys only: a topic may itself contain ":+".
        plus = re.compile(re.escape(key) + r":\+[0-9a-f]{8}")
        mine = [ev for k, ev in decided if k == key or plus.fullmatch(k)]
        if not mine:
            if c["gap"]:
                out.append(_cluster_candidate(c, key, brand, total))
            continue
        # Decided: only the new prompts count, whether or not the whole
        # cluster is still a gap.
        covered = {p for ev in mine for p in ev.get("prompt_ids", [])}
        new = sorted({str(p["prompt_id"]) for p in c["prompts"]} - covered)
        if not new:
            continue
        sub = next(
            r
            for r in clusters(
                s, brand_id, Filters(prompt_ids=[uuid.UUID(p) for p in new])
            )
            if r["key"] == key
        )
        if sub["gap"]:
            h = hashlib.sha1(",".join(new).encode()).hexdigest()[:8]
            out.append(_cluster_candidate(sub, f"{key}:+{h}", brand, total))
    return out


def _rival_pages(s: Session, brand_id: uuid.UUID) -> Sequence[Row[Any]]:
    """New (non-baseline) pages of active competitors seen in the last
    RIVAL_DAYS, newest first. One statement; values bound."""
    return s.execute(
        text(
            "SELECT p.competitor_id, c.name, p.url, p.first_seen_at "
            "FROM rival_page p JOIN competitor c ON c.id = p.competitor_id "
            "WHERE p.brand_id = :b AND c.status = 'active' "
            "  AND NOT p.baseline "
            "  AND p.first_seen_at >= now() - make_interval(days => :days) "
            "ORDER BY p.first_seen_at DESC, p.url"
        ),
        {"b": brand_id, "days": RIVAL_DAYS},
    ).all()


def _rival_content(
    s: Session,
    brand_id: uuid.UUID,
    brand: str,
    total: int,
    rows: list[dict[str, Any]],
) -> list[Candidate]:
    """One candidate per cluster where the brand is behind and a rival
    published matching pages in the last RIVAL_DAYS (spec slice 16)."""
    from .gaps import PAGE_TYPES  # gaps imports CONTENT_REASONS from here

    pages = [(r, slug_words(r.url)) for r in _rival_pages(s, brand_id)]
    if not pages:
        return []
    out = []
    for c in rows:
        behind = c["gap"] or (c["spread"] is not None and c["spread"] < 0)
        words = topic_words(c["topic"])
        if not behind or not words:
            continue
        matched = [r for r, slug in pages if words <= slug]
        if not matched:
            continue
        by_rival: dict[str, list[str]] = {}
        for r in matched:
            by_rival.setdefault(r.name, []).append(r.url)
        top = c["top_rival"]
        title, body = rival_content_copy(
            brand,
            c["topic"],
            c["intent"],
            PAGE_TYPES[c["intent"]],
            list(by_rival.items()),
            c["n"],
            c["brand"]["value"],
            (top["name"], top["value"]) if top else None,
            c["gap"],
        )
        out.append(
            Candidate(
                "respond_to_rival_content",
                f"rival:{c['key']}",
                title,
                body,
                {
                    "prompt_ids": [str(p["prompt_id"]) for p in c["prompts"]],
                    "observation_ids": [str(o) for o in c["absent_obs"]],
                    "cluster": {"intent": c["intent"], "topic": c["topic"]},
                    "cluster_key": c["key"],
                    "n": c["n"],
                    "spread": c["spread"],
                    "gap": c["gap"],
                    "pages": [
                        {
                            "competitor_id": str(r.competitor_id),
                            "name": r.name,
                            "url": r.url,
                            "first_seen_at": r.first_seen_at.isoformat(),
                        }
                        for r in matched[:RIVAL_PAGES_CAP]
                    ],
                    "pages_total": len(matched),
                },
                c["n"] / total,
                min(len(matched) / RIVAL_PAGES_SATURATION, 1.0),
            )
        )
    return out


def _competitors(s: Session, brand_id: uuid.UUID) -> list[Candidate]:
    rows = s.scalars(
        select(m.Competitor)
        .where(
            m.Competitor.brand_id == brand_id,
            m.Competitor.status == "suggested",
            m.Competitor.evidence >= MIN_COMPETITOR_EVIDENCE,
        )
        .order_by(m.Competitor.evidence.desc(), m.Competitor.name)
    ).all()
    out = []
    for c in rows:
        evidence = c.evidence or 0
        title, body = competitor_copy(c.name, evidence)
        out.append(
            Candidate(
                "add_competitor",
                str(c.id),
                title,
                body,
                {"competitor_id": str(c.id), "evidence": evidence},
                # Reach is the share of the suggestion answers naming the
                # rival, not of the brand's monitored answers: a suggested
                # rival has no mentions to count. ponytail: an honest
                # proxy off 3 answers; measure it against the brand's own
                # answers if the shortlist ever needs finer ordering.
                min(evidence / ANSWERS, 1.0),
                # Nothing measures what confirming a rival is worth, and
                # a made-up number would just re-weight reach.
                1.0,
            )
        )
    return out


def _sampling(
    s: Session,
    brand_id: uuid.UUID,
    brand: str,
    active: set[uuid.UUID],
    total: int,
) -> list[Candidate]:
    out = []
    for row in prompt_metrics(s, brand_id, Filters()):
        needs, n, top = row["needs_samples"], row["n"], row["top_competitor"]
        if (
            row["prompt_id"] not in active
            or row["separated"]
            or needs is None
            or top is None
            or not 0 < needs - n <= SAMPLE_MORE_WITHIN
        ):
            continue
        title, body = sample_copy(brand, row["text"], n, needs, top["name"])
        out.append(
            Candidate(
                "sample_more",
                str(row["prompt_id"]),
                title,
                body,
                {
                    "prompt_ids": [str(row["prompt_id"])],
                    "n": n,
                    "needs_samples": needs,
                },
                n / total,
                abs(row["spread"] or 0.0),
            )
        )
    return out


_WIKI_ITEM = re.compile(r"/wiki/(Q[0-9]+)\Z")


def _subject(domain: str, check: dict[str, Any]) -> str:
    """Brand-level Wikidata checks are keyed by brand or item, so every
    declared domain reporting the same gap shares one recommendation."""
    code = check["code"]
    if code == "wikidata_missing":
        return "wikidata:wikidata_missing"
    if code in ("wikidata_name_mismatch", "wikidata_logo_missing"):
        # ponytail: stored rows are free-form; no item page, no merge.
        if qid := _WIKI_ITEM.search(str(check.get("url", ""))):
            return f"wikidata:{qid[1]}:{code}"
    return f"{domain}:{code}"


def _crawl(s: Session, brand_id: uuid.UUID, brand: str) -> list[Candidate]:
    """One candidate per failing check (crawl or entity) in each domain's
    latest audit, except the brand-level Wikidata checks, which are merged
    across domains: one wikidata_missing per brand (none if any domain
    matched an item), one name or logo check per Wikidata item.

    Only domains still declared for the brand count: a removed domain's
    old audit must not keep producing recommendations.
    """
    rows = s.execute(
        text(
            "SELECT DISTINCT ON (a.domain) a.id, a.domain, a.checks "
            "FROM site_audit a "
            "JOIN domain d ON d.brand_id = a.brand_id "
            "  AND d.host = a.domain "
            "WHERE a.brand_id = :brand "
            "ORDER BY a.domain, a.created_at DESC, a.id DESC"
        ),
        {"brand": brand_id},
    ).all()
    out: dict[str, Candidate] = {}
    item_found = False
    for audit_id, domain, checks in rows:
        for check in checks:
            if check["ok"]:
                item_found |= check["code"] == "wikidata_missing"
                continue
            code = check["code"]
            fam = family(code)
            known = fam in entity.FAMILIES or fam in _CRAWL_TITLES
            if not known or check["severity"] not in PRESSURE_BY_SEVERITY:
                log.warning(
                    "skipping unrecognized site check: brand=%s domain=%s "
                    "code=%s",
                    brand,
                    domain,
                    code,
                )
                continue
            if fam in entity.FAMILIES:
                kind, copy = "fix_entity", entity_copy
            else:
                kind, copy = "fix_crawlability", crawl_copy
            key = _subject(domain, check)
            if key in out:
                # A merged Wikidata key repeats across domains; any other
                # repeat is a duplicate row in one audit, dropped.
                seen = out[key].evidence.get("domains", [domain])
                if domain not in seen:
                    seen.append(domain)
                continue
            evidence = {**check, "domain": domain, "audit_id": str(audit_id)}
            if key.startswith("wikidata:"):
                evidence["domains"] = [domain]
            title, body = copy(brand, domain, check)
            out[key] = Candidate(
                kind,
                key,
                title,
                body,
                evidence,
                # Not measured against answers; see PRESSURE_BY_SEVERITY.
                1.0,
                PRESSURE_BY_SEVERITY[check["severity"]],
            )
    if item_found:
        out.pop("wikidata:wikidata_missing", None)
    return list(out.values())


def _pages(
    s: Session, brand_id: uuid.UUID, brand: str, total: int
) -> list[Candidate]:
    """One candidate per (cluster, url) whose latest scored audit is below
    PAGE_SCORE_THRESHOLD. Failed fetches (score NULL) never count; the
    Pages tab shows them. Reach and evidence come from the audit row,
    captured when it was scored: no cluster query here."""
    rows = s.execute(
        text(
            "SELECT DISTINCT ON (a.cluster_key, a.url) a.id, a.url, "
            "a.cluster_key, a.score, a.suggestions, a.evidence "
            "FROM page_audit a "
            "WHERE a.brand_id = :brand AND a.score IS NOT NULL "
            "ORDER BY a.cluster_key, a.url, a.created_at DESC, a.id DESC"
        ),
        {"brand": brand_id},
    ).all()
    out = []
    for r in rows:
        if r.score >= PAGE_SCORE_THRESHOLD:
            continue
        ev = r.evidence or {}
        prompt_ids = list(ev.get("prompt_ids", []))
        observation_ids = list(ev.get("observation_ids", []))
        topic = (ev.get("cluster") or {}).get("topic") or r.cluster_key
        title, body = page_copy(
            brand, r.url, topic, len(prompt_ids), r.score, r.suggestions or {}
        )
        out.append(
            Candidate(
                "optimize_page",
                f"page:{r.cluster_key}:{r.url}",
                title,
                body,
                {
                    "page_audit_id": str(r.id),
                    "url": r.url,
                    "cluster_key": r.cluster_key,
                    "score": r.score,
                    "prompt_ids": prompt_ids,
                    "observation_ids": observation_ids,
                    "cluster": ev.get("cluster"),
                },
                len(observation_ids) / total,
                (100 - r.score) / 100,
            )
        )
    return out


def generate(s: Session, brand_id: uuid.UUID) -> list[Candidate]:
    """Every recommendation the brand's evidence supports, best first.

    Call in the brand's tenant session; row-level security scopes every
    query here.
    """
    brand = s.get_one(m.Brand, brand_id).name
    active = set(
        s.scalars(
            select(m.Prompt.id).where(
                m.Prompt.brand_id == brand_id, m.Prompt.status == "active"
            )
        )
    )
    # Reach's denominator: every done answer on an active prompt.
    total = s.scalar(
        select(func.count())
        .select_from(m.Observation)
        .join(m.Prompt, m.Prompt.id == m.Observation.prompt_id)
        .where(
            m.Observation.brand_id == brand_id,
            m.Observation.status == "done",
            m.Prompt.status == "active",
        )
    )
    found = _competitors(s, brand_id) + _crawl(s, brand_id, brand)
    if total:
        from .gaps import clusters  # gaps imports CONTENT_REASONS from here

        rows = clusters(s, brand_id, Filters())
        rival_domains = _rival_domains(s, brand_id)
        found += [
            *_citations(s, brand_id, brand, total, rival_domains),
            *_content(s, brand_id, brand, total),
            *_content_clusters(s, brand_id, brand, total, rows),
            *_rival_content(s, brand_id, brand, total, rows),
            *_pages(s, brand_id, brand, total),
            *_sampling(s, brand_id, brand, active, total),
        ]
    return sorted(found, key=lambda c: (-c.priority, c.type, c.subject_key))


_REFRESHED = (
    "title",
    "body",
    "evidence",
    "reach",
    "pressure",
    "feasibility",
    "priority",
)


def refresh(s: Session, org_id: uuid.UUID, brand_id: uuid.UUID) -> int:
    """Store the brand's recommendations; returns how many the evidence
    supports.

    Open rows are refreshed in place. Accepted and dismissed rows are left
    exactly as they are: regeneration never undoes a decision. Open rows
    the evidence no longer supports are removed.
    """
    found = generate(s, brand_id)
    if found:
        stmt = insert(m.Recommendation).values(
            [
                {
                    "org_id": org_id,
                    "brand_id": brand_id,
                    "type": c.type,
                    "subject_key": c.subject_key,
                    "title": c.title,
                    "body": c.body,
                    "evidence": c.evidence,
                    "reach": c.reach,
                    "pressure": c.pressure,
                    "feasibility": c.feasibility,
                    "priority": c.priority,
                }
                for c in found
            ]
        )
        s.execute(
            stmt.on_conflict_do_update(
                index_elements=["brand_id", "type", "subject_key"],
                set_={k: stmt.excluded[k] for k in _REFRESHED},
                where=m.Recommendation.status == "open",
            )
        )
    # One statement, with status = 'open' in its WHERE: if a dismiss or
    # accept holds the row, Postgres re-checks the condition after the
    # lock wait and leaves the decided row alone.
    stale = delete(m.Recommendation).where(
        m.Recommendation.brand_id == brand_id,
        m.Recommendation.status == "open",
    )
    if found:
        keep = [(c.type, c.subject_key) for c in found]
        stale = stale.where(
            tuple_(m.Recommendation.type, m.Recommendation.subject_key).not_in(
                keep
            )
        )
    s.execute(stale)
    return len(found)


def top_by_type(
    ranked: Sequence[m.Recommendation], k: int = 3
) -> list[m.Recommendation]:
    """The shortlist: the best of each type first, then the next best.

    `ranked` must already be in priority order. Priority compares well
    within a type, where reach and pressure mean the same thing, but only
    loosely across types, where feasibility is a judgement. Taking the top
    k overall lets one type crowd out the rest - on the slice-1 brand,
    citations held all ten top places at every feasibility weighting short
    of one that flooded the top with content instead.
    """
    firsts: list[m.Recommendation] = []
    rest: list[m.Recommendation] = []
    seen: set[str] = set()
    for rec in ranked:
        (rest if rec.type in seen else firsts).append(rec)
        seen.add(rec.type)
    return (firsts + rest)[:k]
