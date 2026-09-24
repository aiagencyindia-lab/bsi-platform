"""Competitor site crawl (PRD F07): a weekly snapshot of each active
competitor's declared domains (sitemap URLs plus a small page sample
read for JSON-LD @types), and the changes between snapshots.

snapshot_domain is pure: the caller passes the fetch (the SSRF-guarded
crawl.http_fetch in production), as crawl.audit_domain does."""

import json
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

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
    return sorted(found)


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
            continue
        read += 1
        r = get(url)
        if not r.ok:
            snap.complete = False
            snap.errors.append(f"sitemap {url}: {r.error or r.status}")
            continue
        kind, locs, clean = parse_sitemap(r.body)
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
