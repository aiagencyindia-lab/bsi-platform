"""Competitor site crawl (PRD F07): a weekly snapshot of each active
competitor's declared domains (sitemap URLs plus a small page sample
read for JSON-LD @types), and the changes between snapshots.

snapshot_domain is pure: the caller passes the fetch (the SSRF-guarded
crawl.http_fetch in production), as crawl.audit_domain does."""

import json
import time
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.orm import Session

from .crawl import (
    BROWSER_UA,
    Fetch,
    Head,
    Response,
    _owned_sitemap,
    _robots_groups,
    _robots_lines,
    _types,
    robots_allows,
)

# The root sitemap plus up to 10 children of an index.
MAX_SITEMAP_FETCHES = 11
MAX_NEW_PAGES = 10
MAX_URL_CHARS = 2_048  # the sitemap protocol's limit
MAX_TYPE_CHARS = 200


class OutOfTime(Exception):
    """The job's time budget ran out mid-domain; nothing is stored."""


def with_deadline(
    fetch: Fetch,
    seconds: float,
    clock: Callable[[], float] = time.monotonic,
) -> Fetch:
    """`fetch`, refusing any call made after `seconds` from now."""
    end = clock() + seconds

    def bounded(url: str, ua: str) -> Response:
        if clock() > end:
            raise OutOfTime(url)
        return fetch(url, ua)

    return bounded


def parse_sitemap(
    body: str,
) -> tuple[str, list[tuple[str, str | None]], bool]:
    """(root tag, [(loc, lastmod)], closed cleanly). A body cut at the
    fetch cap, gzip bytes, or malformed XML is not clean; whatever was
    read before the fault is still returned. Namespaces are ignored, so
    only <loc>/<lastmod> directly under a <url>/<sitemap> entry count
    (an image sitemap's <image:loc> sits deeper)."""
    parser: ET.XMLPullParser[ET.Element] = ET.XMLPullParser(
        events=("start", "end")
    )
    root = ""
    closed = False
    depth = 0  # root = 1, entry = 2, entry field = 3
    locs: list[tuple[str, str | None]] = []
    loc: str | None = None
    lastmod: str | None = None
    try:
        parser.feed(body)
        for ev in parser.read_events():
            event, el = ev[0], ev[-1]
            if not isinstance(el, ET.Element):
                continue
            tag = str(el.tag).rsplit("}", 1)[-1]
            if event == "start":
                depth += 1
                root = root or tag
                continue
            if depth == 3 and tag == "loc":
                loc = (el.text or "").strip()
            elif depth == 3 and tag == "lastmod":
                lastmod = (el.text or "").strip() or None
            elif depth == 2:
                if loc:
                    locs.append((loc, lastmod))
                loc = lastmod = None
                el.clear()
            elif depth == 1:
                closed = True
            depth -= 1
    except ET.ParseError:
        closed = False
    return root or "none", locs, closed


@dataclass
class Snapshot:
    urls: dict[str, str | None] = field(default_factory=dict)
    pages: list[dict[str, Any]] = field(default_factory=list)
    domain_types: dict[str, str] = field(default_factory=dict)
    complete: bool = True
    errors: list[str] = field(default_factory=list)
    fetches: int = 0
    skipped: list[str] = field(default_factory=list)


def _page_types(body: str) -> list[str]:
    head = Head()
    head.feed(body)
    found: set[str] = set()
    for script in head.ld:
        try:
            found |= _types(json.loads(script))
        except (ValueError, RecursionError):
            continue
    return sorted(
        t for t in found if len(t) <= MAX_TYPE_CHARS and "\x00" not in t
    )


def _newest_first(urls: dict[str, str | None], fresh: list[str]) -> list[str]:
    """lastmod descending (ties by URL descending), then undated URLs in
    URL order. ponytail: lastmod compared as a string; ISO 8601 dates of
    one precision sort right, mixed precisions only roughly."""
    dated = [u for u in fresh if urls[u]]
    dated.sort(key=lambda u: (urls[u] or "", u), reverse=True)
    return dated + sorted(u for u in fresh if not urls[u])


def snapshot_domain(
    host: str, fetch: Fetch, known: set[str], *, pause: float = 0.0
) -> Snapshot:
    """One competitor domain: robots.txt, its sitemaps (an index followed
    to MAX_SITEMAP_FETCHES in all), the homepage and up to MAX_NEW_PAGES
    URLs not in `known`, newest <lastmod> first. Every fetch after
    robots.txt obeys its `*` group. Raises OutOfTime from a bounded
    fetch; never raises otherwise."""
    snap = Snapshot()

    def get(url: str) -> Response:
        if snap.fetches and pause:
            time.sleep(pause)
        snap.fetches += 1
        return fetch(url, BROWSER_UA)

    robots = get(f"https://{host}/robots.txt")
    if robots.status == 0 or robots.status >= 500:
        snap.complete = False
        snap.errors.append(
            f"robots.txt unavailable ({robots.error or robots.status}): "
            "nothing crawled"
        )
        return snap
    rules = ""
    sitemaps: list[str] = []
    if robots.ok:
        rules = "\n".join(
            line
            for agents, lines in _robots_groups(robots.body)
            if "*" in agents
            for line in lines
        )
        sitemaps = [
            v
            for k, v, _ in _robots_lines(robots.body)
            if k == "sitemap" and _owned_sitemap(host, v)
        ]

    def allowed(url: str) -> bool:
        parts = urlsplit(url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        return robots_allows(rules, path)

    if not allowed("/"):
        snap.complete = False
        snap.errors.append("robots.txt disallows / for *: nothing crawled")
        return snap

    queue = sitemaps or [f"https://{host}/sitemap.xml"]
    seen: set[str] = set()
    read = 0
    while queue:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        if read == MAX_SITEMAP_FETCHES:
            snap.complete = False
            snap.errors.append(
                f"sitemap: more than {MAX_SITEMAP_FETCHES} sitemap files; "
                "the rest were not read"
            )
            break
        if not allowed(url):
            snap.skipped.append(url)
            snap.complete = False
            snap.errors.append(f"sitemap {url}: disallowed by robots.txt")
            continue
        read += 1
        r = get(url)
        if not r.ok:
            snap.complete = False
            snap.errors.append(f"sitemap {url}: {r.error or r.status}")
            continue
        kind, locs, clean = parse_sitemap(r.body)
        ok = [
            (loc, mod)
            for loc, mod in locs
            if len(loc) <= MAX_URL_CHARS and "\x00" not in loc
        ]
        if len(ok) < len(locs):
            snap.errors.append(
                f"sitemap {url}: {len(locs) - len(ok)} URLs dropped "
                "(too long or invalid)"
            )
        locs = ok
        if not clean:
            snap.complete = False
            snap.errors.append(f"sitemap {url}: cut off or not XML")
        if kind == "sitemapindex":
            queue += [loc for loc, _ in locs if _owned_sitemap(host, loc)]
        elif kind != "urlset":  # a soft-404 page, a feed, garbage
            snap.complete = False
            if clean:
                snap.errors.append(f"sitemap {url}: not a sitemap (<{kind}>)")
        else:
            for loc, lastmod in locs:
                if _owned_sitemap(host, loc):  # any on-host http(s) URL
                    snap.urls[loc] = lastmod

    fresh = [u for u in snap.urls if u not in known]
    targets = [f"https://{host}/"]
    for u in _newest_first(snap.urls, fresh):
        if len(targets) > MAX_NEW_PAGES:
            break
        if allowed(u):
            targets.append(u)
        else:
            snap.skipped.append(u)
    for url in targets:
        r = get(url)
        types = _page_types(r.body) if r.ok else []
        snap.pages.append({"url": url, "types": types, "status": r.status})
        for t in types:
            snap.domain_types.setdefault(t, url)
    return snap


NEW_PAGES_CAP = 20

# Pages first seen in [start, end), not on a baseline crawl, newest first
# and capped per competitor; total is the uncapped count.
_NEW_PAGES = (
    "SELECT competitor_id, url, first_seen_at, types, total FROM ("
    "  SELECT competitor_id, url, first_seen_at, types, "
    "    row_number() OVER (PARTITION BY competitor_id "
    "      ORDER BY first_seen_at DESC, url) AS n, "
    "    count(*) OVER (PARTITION BY competitor_id) AS total "
    "  FROM rival_page WHERE brand_id = :brand "
    "  AND competitor_id = ANY(:cids) AND NOT baseline "
    "  AND first_seen_at >= :start AND first_seen_at < :end) x "
    f"WHERE n <= {NEW_PAGES_CAP} ORDER BY competitor_id, n"
)

# @types first seen in [start, end) for a competitor, across its domains,
# on a crawl that is not a baseline. A type any earlier crawl had (or
# whose earliest crawl was a baseline) is not new. url and base come from
# the earliest crawl, ties broken by id.
_NEW_TYPES = (
    "SELECT competitor_id, type, url FROM ("
    "  SELECT r.competitor_id, t.key AS type, "
    "    (array_agg(t.value #>> '{}' ORDER BY r.created_at, r.id))[1] AS url,"
    "    min(r.created_at) AS first_at, "
    "    (array_agg(r.baseline ORDER BY r.created_at, r.id))[1] AS base "
    "  FROM rival_crawl r CROSS JOIN LATERAL jsonb_each(r.types) AS t "
    "  WHERE r.brand_id = :brand AND r.competitor_id = ANY(:cids) "
    "  GROUP BY r.competitor_id, t.key) f "
    "WHERE NOT base AND first_at >= :start AND first_at < :end "
    "ORDER BY competitor_id, type"
)


def feed_evidence(
    s: Session,
    brand_id: uuid.UUID,
    cids: list[uuid.UUID],
    start: datetime,
    end: datetime,
) -> dict[uuid.UUID, dict[str, list[str]]]:
    """Per competitor: pages first seen in [start, end) (not baseline,
    newest first, capped) and @types first seen there. Two statements."""
    out: dict[uuid.UUID, dict[str, list[str]]] = {
        c: {"new_pages": [], "new_types": []} for c in cids
    }
    if not cids:
        return out
    p = {"brand": brand_id, "cids": cids, "start": start, "end": end}
    for r in s.execute(text(_NEW_PAGES), p):
        out[r.competitor_id]["new_pages"].append(r.url)
    for r in s.execute(text(_NEW_TYPES), p):
        out[r.competitor_id]["new_types"].append(r.type)
    return out


def site_changes(
    s: Session,
    brand_id: uuid.UUID,
    days: int = 14,
    to: datetime | None = None,
) -> dict[str, Any]:
    """Every active competitor with its new pages, new @types and each
    declared domain's latest crawl, over [to - days, to). Ordered by new
    pages, then name. Four statements."""
    to = to or datetime.now(UTC)
    start = to - timedelta(days=days)
    out: dict[str, Any] = {
        "window": {"start": start, "to": to},
        "competitors": [],
    }
    rivals = s.execute(
        text(
            "SELECT id, name FROM competitor "
            "WHERE brand_id = :brand AND status = 'active' "
            "ORDER BY name, id"
        ),
        {"brand": brand_id},
    ).all()
    if not rivals:
        return out
    cids = [r.id for r in rivals]
    p = {"brand": brand_id, "cids": cids, "start": start, "end": to}
    pages: dict[uuid.UUID, list[dict[str, Any]]] = {c: [] for c in cids}
    totals: dict[uuid.UUID, int] = dict.fromkeys(cids, 0)
    for r in s.execute(text(_NEW_PAGES), p):
        totals[r.competitor_id] = int(r.total)
        pages[r.competitor_id].append(
            {
                "url": r.url,
                "first_seen_at": r.first_seen_at,
                "types": list(r.types or []),
            }
        )
    types: dict[uuid.UUID, list[dict[str, str]]] = {c: [] for c in cids}
    for r in s.execute(text(_NEW_TYPES), p):
        types[r.competitor_id].append({"type": r.type, "url": r.url})
    crawls: dict[uuid.UUID, list[dict[str, Any]]] = {c: [] for c in cids}
    for r in s.execute(
        text(
            "SELECT DISTINCT ON (r.competitor_id, r.domain) r.competitor_id, "
            "r.domain, r.created_at, r.complete, r.urls_seen, r.errors "
            "FROM rival_crawl r JOIN competitor c ON c.id = r.competitor_id "
            "  AND r.domain = ANY(c.domains) "
            "WHERE r.brand_id = :brand AND r.competitor_id = ANY(:cids) "
            "ORDER BY r.competitor_id, r.domain, r.created_at DESC, r.id DESC"
        ),
        p,
    ):
        crawls[r.competitor_id].append(
            {
                "domain": r.domain,
                "crawled_at": r.created_at,
                "complete": r.complete,
                "urls_seen": r.urls_seen,
                "errors": list(r.errors),
            }
        )
    rows = [
        {
            "competitor_id": r.id,
            "name": r.name,
            "new_pages_total": totals[r.id],
            "new_pages": pages[r.id],
            "new_types": types[r.id],
            "crawls": crawls[r.id],
        }
        for r in rivals
    ]
    rows.sort(key=lambda x: (-x["new_pages_total"], x["name"]))
    out["competitors"] = rows
    return out
