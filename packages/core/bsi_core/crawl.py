"""Crawlability audit of a brand's own site (PRD F10, the cheap part).

Homepage plus site files only: robots.txt, the first sitemap, llms.txt,
and the homepage fetched once as a browser and once per AI bot. Every
check is derived from canned responses in tests; the network is behind
one injected callable, as model calls are.
"""

import json
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, NamedTuple
from urllib import robotparser

import httpx

BROWSER_UA = "Mozilla/5.0 (compatible; BSI-Audit/1.0)"
BOTS = (
    "GPTBot",
    "OAI-SearchBot",
    "ClaudeBot",
    "Claude-SearchBot",
    "PerplexityBot",
    "Google-Extended",
    "Googlebot",
    "Bingbot",
)
BODY_CAP = 512 * 1024
OBSERVED_CAP = 300
PAUSE_SECONDS = 0.5
TIMEOUT_SECONDS = 15
# Statuses a CDN uses to turn a bot away. A timeout (status 0) is not
# counted: it is as likely our side.
BLOCKED = {401, 403, 429}


@dataclass
class Response:
    status: int
    body: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


Fetch = Callable[[str, str], Response]


@dataclass
class Check:
    code: str
    ok: bool
    severity: str  # high | medium | low
    observed: str
    expected: str
    url: str


class Audit(NamedTuple):
    checks: list[Check]
    fetches: int


SEVERITY = {
    "home_unreachable": "high",
    "bot_blocked": "high",
    "bot_ua_blocked": "high",
    "sitemap_missing": "medium",
    "sitemap_invalid": "medium",
    "org_schema_missing": "medium",
    "title_missing": "low",
    "description_missing": "low",
    "h1_missing": "low",
    "canonical_missing": "low",
    "llms_missing": "low",
}
EXPECTED = {
    "home_unreachable": "The homepage answers 2xx to a browser user agent.",
    "bot_blocked": "robots.txt lets this crawler fetch the homepage.",
    "bot_ua_blocked": "The homepage answers this crawler's user agent as "
    "it answers a browser.",
    "sitemap_missing": "A sitemap listed in robots.txt, or /sitemap.xml, "
    "answers 2xx.",
    "sitemap_invalid": "The sitemap's root element is <urlset> or "
    "<sitemapindex>.",
    "org_schema_missing": "The homepage carries JSON-LD with an "
    "Organization type.",
    "title_missing": "The homepage has a <title>.",
    "description_missing": "The homepage has a meta description.",
    "h1_missing": "The homepage has an <h1>.",
    "canonical_missing": "The homepage declares a canonical URL.",
    "llms_missing": "/llms.txt answers 2xx. The file is an unofficial "
    "convention; its absence costs nothing today.",
}


def family(code: str) -> str:
    return code.split(":", 1)[0]


def severity(code: str) -> str:
    return SEVERITY[family(code)]


def expected(code: str) -> str:
    return EXPECTED[family(code)]


def http_fetch(url: str, user_agent: str) -> Response:
    """The real fetch. Never raises: an error is a Response with status 0.

    ponytail: reads the whole body before capping; stream it if a site
    ever serves a homepage large enough to matter.
    """
    try:
        with httpx.Client(
            timeout=TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
        ) as client:
            r = client.get(url)
        return Response(r.status_code, r.text[:BODY_CAP])
    except Exception as e:
        return Response(0, "", repr(e))


class _Head(HTMLParser):
    """Collects what the on-page checks look at, and nothing else."""

    def __init__(self) -> None:
        super().__init__()
        self.title: str | None = None
        self.description: str | None = None
        self.canonical: str | None = None
        self.h1: str | None = None
        self.ld: list[str] = []
        self._in: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "title":
            self._in = "title"
            self.title = self.title or ""
        elif tag == "meta" and a.get("name", "").lower() == "description":
            self.description = a.get("content", "")
        elif tag == "link" and "canonical" in a.get("rel", "").lower().split():
            self.canonical = a.get("href", "")
        elif tag == "h1" and self.h1 is None:
            self._in = "h1"
            self.h1 = ""
        elif tag == "script" and a.get("type", "").lower() == (
            "application/ld+json"
        ):
            self._in = "ld"
            self.ld.append("")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("title", "h1", "script"):
            self._in = None

    def handle_data(self, data: str) -> None:
        if self._in == "title" and self.title is not None:
            self.title += data
        elif self._in == "h1" and self.h1 is not None:
            self.h1 += data
        elif self._in == "ld":
            self.ld[-1] += data


def _types(node: object) -> set[str]:
    """Every @type in a JSON-LD document, including inside @graph."""
    found: set[str] = set()
    if isinstance(node, dict):
        t = node.get("@type")
        if isinstance(t, str):
            found.add(t)
        elif isinstance(t, list):
            found.update(x for x in t if isinstance(x, str))
        for v in node.values():
            found |= _types(v)
    elif isinstance(node, list):
        for v in node:
            found |= _types(v)
    return found


def _has_org(scripts: list[str]) -> bool:
    for script in scripts:
        try:
            parsed: Any = json.loads(script)
        except ValueError:
            continue
        if "Organization" in _types(parsed):
            return True
    return False


def _clip(s: str) -> str:
    return s.strip()[:OBSERVED_CAP]


def _group_lines(robots: str, bot: str) -> str:
    """The robots.txt groups that name this bot or *, for `observed`."""
    out: list[str] = []
    agents: list[str] = []
    keep = False
    for line in robots.splitlines():
        key, _, value = line.partition(":")
        if key.strip().lower() == "user-agent":
            agents.append(value.strip().lower())
            keep = any(a in (bot.lower(), "*") for a in agents)
            if keep:
                out.append(line.strip())
            continue
        if line.strip() == "":
            agents = []
            continue
        if keep:
            out.append(line.strip())
    return "\n".join(out)


def audit_domain(host: str, fetch: Fetch, *, pause: float = 0.0) -> Audit:
    """Every check for one host. Skipped checks are not emitted: on-page
    checks need a reachable homepage, sitemap_invalid needs a sitemap."""
    checks: list[Check] = []
    fetches = 0

    def get(url: str, ua: str = BROWSER_UA) -> Response:
        nonlocal fetches
        if fetches and pause:
            time.sleep(pause)
        fetches += 1
        return fetch(url, ua)

    def add(code: str, ok: bool, observed: str, url: str) -> None:
        checks.append(
            Check(
                code, ok, severity(code), _clip(observed), expected(code), url
            )
        )

    home_url = f"https://{host}/"
    home = get(home_url)
    add(
        "home_unreachable",
        home.ok,
        home.error or f"HTTP {home.status}",
        home_url,
    )
    if home.ok:
        head = _Head()
        head.feed(home.body)
        for code, value in (
            ("title_missing", head.title),
            ("description_missing", head.description),
            ("h1_missing", head.h1),
            ("canonical_missing", head.canonical),
        ):
            add(
                code, bool(value and value.strip()), value or "absent", home_url
            )
        add(
            "org_schema_missing",
            _has_org(head.ld),
            f"{len(head.ld)} ld+json block(s)",
            home_url,
        )

    robots_url = f"https://{host}/robots.txt"
    robots = get(robots_url)
    rp = robotparser.RobotFileParser()
    if robots.ok:
        rp.parse(robots.body.splitlines())
    else:
        rp.parse([])  # no file: everything is allowed
    for bot in BOTS:
        allowed = rp.can_fetch(bot, home_url)
        observed = (
            _group_lines(robots.body, bot) if robots.ok else "no robots.txt"
        )
        add(
            f"bot_blocked:{bot}",
            allowed,
            observed or "no matching group",
            robots_url,
        )

    for bot in BOTS:
        r = get(home_url, bot)
        blocked = home.ok and (r.status in BLOCKED or r.status >= 500)
        add(
            f"bot_ua_blocked:{bot}",
            not blocked,
            r.error or f"HTTP {r.status}",
            home_url,
        )

    default_sitemap = f"https://{host}/sitemap.xml"
    sitemaps = (
        (rp.site_maps() or [default_sitemap])
        if robots.ok
        else [default_sitemap]
    )
    sm_url = sitemaps[0]  # ponytail: the first listed; the rest are unread
    sm = get(sm_url)
    add("sitemap_missing", sm.ok, sm.error or f"HTTP {sm.status}", sm_url)
    if sm.ok:
        try:
            root = ET.fromstring(sm.body).tag.rsplit("}", 1)[-1]
        except ET.ParseError as e:
            root = f"unparseable: {e}"
        add(
            "sitemap_invalid",
            root in ("urlset", "sitemapindex"),
            f"root <{root}>",
            sm_url,
        )

    llms_url = f"https://{host}/llms.txt"
    llms = get(llms_url)
    add("llms_missing", llms.ok, llms.error or f"HTTP {llms.status}", llms_url)
    return Audit(checks, fetches)
