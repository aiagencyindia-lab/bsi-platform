"""Crawlability audit of a brand's own site (PRD F10, the cheap part).

Homepage plus site files only: robots.txt, the first sitemap, llms.txt,
and the homepage fetched once as a browser and once per AI bot. Every
check is derived from canned responses in tests; the network is behind
one injected callable, as model calls are.
"""

import ipaddress
import json
import re
import socket
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, NamedTuple
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from bsi_core.matching import is_owned, normalize_domain

# A real desktop Chrome: bot-managed sites answer a bot-like UA 403,
# which would blind the audit to its own baseline.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
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
BODY_CAP_BYTES = 512 * 1024  # decoded bytes kept per fetch
OBSERVED_CAP = 300
PAUSE_SECONDS = 0.5
PHASE_TIMEOUT_SECONDS = 15  # connect, each read
DEADLINE_SECONDS = 30  # the whole fetch, every redirect hop included
MAX_REDIRECTS = 5
_REDIRECTS = {301, 302, 303, 307, 308}
_DEFAULT_PORT = {"http": 80, "https": 443}
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


class _Refused(Exception):
    """A URL the fetch will not touch; the message says why."""


def _resolve(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _public_ip(
    host: str, port: int, resolve: Callable[[str, int], list[str]]
) -> str:
    """The address to connect to. Every address the name resolves to must
    be globally routable, or one lookup could pass the check and the next
    land inside."""
    try:
        ips = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            ips = resolve(host, port)
        except OSError as e:
            raise _Refused(f"{host} does not resolve") from e
    if not ips:
        raise _Refused(f"{host} does not resolve")
    for ip in ips:
        addr = ipaddress.ip_address(ip)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        if not addr.is_global:
            raise _Refused(f"{ip} is not a public address")
    return ips[0]


def _decode(body: bytes, charset: str | None) -> str:
    try:
        return body.decode(charset or "utf-8", "replace")
    except LookupError:  # a charset Python does not know
        return body.decode("utf-8", "replace")


_TIMED_OUT = f"timeout: over the {DEADLINE_SECONDS} s deadline"


# SECURITY: this is the SSRF guard (docs/findings-slice7.md §5.8). Every
# hop is checked and pinned: http(s) on the default port only, every
# resolved address public, the connection made to the checked address
# (never a second lookup), redirects followed by hand and re-checked.
def http_fetch(
    url: str,
    user_agent: str,
    *,
    resolve: Callable[[str, int], list[str]] = _resolve,
    transport: httpx.BaseTransport | None = None,
) -> Response:
    """The real fetch. Never raises: an error is a Response with status 0,
    and a URL it will not fetch has error "refused: <reason>".

    ponytail: httpx decodes gzip a network chunk at a time, so one chunk
    can inflate to ~1000x its size (~64 MiB) before the cap applies.
    Decode by hand with zlib max_length if that memory ever matters.
    """
    deadline = time.monotonic() + DEADLINE_SECONDS
    try:
        # trust_env=False: an environment proxy would do its own lookup.
        with httpx.Client(transport=transport, trust_env=False) as client:
            for _ in range(MAX_REDIRECTS + 1):
                parts = urlsplit(url)
                scheme = parts.scheme
                if scheme not in _DEFAULT_PORT:
                    raise _Refused(f"scheme {scheme or 'missing'}")
                try:
                    port = parts.port
                except ValueError as e:
                    raise _Refused("bad port") from e
                if port not in (None, _DEFAULT_PORT[scheme]):
                    raise _Refused(f"port {port}")
                if not parts.hostname:
                    raise _Refused("no host")
                host = parts.hostname.encode("idna").decode("ascii")
                ip = _public_ip(host, _DEFAULT_PORT[scheme], resolve)
                netloc = f"[{ip}]" if ":" in ip else ip
                target = urlunsplit(
                    (scheme, netloc, parts.path or "/", parts.query, "")
                )
                # sni_hostname: TLS SNI and certificate checks use the name.
                ext = {"sni_hostname": host} if scheme == "https" else {}
                left = deadline - time.monotonic()
                if left <= 0:
                    return Response(0, "", _TIMED_OUT)
                with client.stream(
                    "GET",
                    target,
                    headers={"Host": host, "User-Agent": user_agent},
                    extensions=ext,
                    timeout=max(0.0, min(PHASE_TIMEOUT_SECONDS, left)),
                ) as r:
                    location = r.headers.get("location")
                    if r.status_code in _REDIRECTS and location:
                        url = urljoin(url, location)
                        continue
                    body = bytearray()
                    for chunk in r.iter_bytes():
                        body += chunk
                        if time.monotonic() > deadline:
                            return Response(0, "", _TIMED_OUT)
                        if len(body) >= BODY_CAP_BYTES:
                            break
                    data = bytes(body[:BODY_CAP_BYTES])
                    return Response(
                        r.status_code, _decode(data, r.charset_encoding)
                    )
            raise _Refused("too many redirects")
    except _Refused as e:
        return Response(0, "", f"refused: {e}")
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
            if "Organization" in _types(parsed):
                return True
        except (ValueError, RecursionError):
            # A malformed or pathologically nested ld+json block fails
            # this one check; it must not take the rest of the audit
            # down with it.
            continue
    return False


def _root_tag(body: str) -> str:
    """The sitemap's root element name: the first start tag decides.

    http_fetch keeps only the first BODY_CAP_BYTES bytes, so a large
    sitemap arrives cut off mid-element. The whole capped body is fed to
    the parser; feed() queues a later parse error as an event instead of
    raising it, and the root's start event is read first. close() is
    never called, so an unterminated or malformed tail after the root no
    longer matters. Entity expansion (billion laughs) is bounded by
    expat's own amplification limits (expat >= 2.4), not by stopping at
    the root.
    """
    parser: ET.XMLPullParser[ET.Element] = ET.XMLPullParser(events=("start",))
    try:
        parser.feed(body)
        for event in parser.read_events():
            element = event[-1]
            if isinstance(element, ET.Element):
                return str(element.tag).rsplit("}", 1)[-1]
    except ET.ParseError as e:
        return f"unparseable: {e}"
    return "none"


def _clip(s: str) -> str:
    return s.strip()[:OBSERVED_CAP]


def _robots_lines(robots: str) -> Iterator[tuple[str, str, str]]:
    """(key, value, line) for every `key: value` line, comment removed."""
    for raw in robots.splitlines():
        line = raw.split("#", 1)[0].strip()
        key, colon, value = line.partition(":")
        if colon:
            yield key.strip().lower(), value.strip(), line


def _token(agent: str) -> str:
    """RFC 9309 product token: `*`, or the leading [A-Za-z_-] run."""
    return "*" if agent == "*" else re.sub(r"[^A-Za-z_-].*", "", agent).lower()


def _robots_groups(robots: str) -> list[tuple[set[str], list[str]]]:
    """(product tokens, lines) per RFC 9309 group. A user-agent line after
    a rule starts a new group; blank lines, comments and other keys
    (sitemap, host, crawl-delay) do not affect grouping; rules before the
    first user-agent line belong to nobody."""
    groups: list[tuple[set[str], list[str]]] = []
    after_rule = True
    for key, value, line in _robots_lines(robots):
        if key == "user-agent":
            if after_rule:
                groups.append((set(), []))
                after_rule = False
            groups[-1][0].add(_token(value))
            groups[-1][1].append(line)
        elif key in ("allow", "disallow") and groups:
            groups[-1][1].append(line)
            after_rule = True
    return groups


def _matches(pattern: str, path: str) -> bool:
    """RFC 9309 §2.2.3: `*` is any sequence, a trailing `$` ends the path."""
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = ".*".join(map(re.escape, body.split("*")))
    return re.match(regex + (r"\Z" if anchored else ""), path) is not None


def _decisive_rule(robots: str, path: str) -> str | None:
    """The rule line that decides `path`: the longest matching pattern,
    Allow on a tie. None when no rule matches (allowed)."""
    best: str | None = None
    rank = (-1, False)
    for key, value, line in _robots_lines(robots):
        if key in ("allow", "disallow") and value and _matches(value, path):
            mine = (len(value.encode()), key == "allow")
            if mine > rank:
                best, rank = line, mine
    return best


def robots_allows(robots: str, path: str = "/") -> bool:
    """Whether the Allow/Disallow lines in `robots` let a crawler fetch
    `path`. Group selection happens before; this sees one bot's rules."""
    rule = _decisive_rule(robots, path)
    return rule is None or rule.lower().startswith("allow")


def _bot_verdict(
    groups: list[tuple[set[str], list[str]]], bot: str
) -> tuple[bool, str]:
    """(allowed, evidence) for the homepage. Every group naming the bot is
    merged; failing that, every `*` group; failing that, no rules."""
    token = bot.lower()
    used = [ls for ts, ls in groups if token in ts] or [
        ls for ts, ls in groups if "*" in ts
    ]
    lines = [line for ls in used for line in ls]
    text = "\n".join(lines)
    allowed = robots_allows(text)
    if not lines:
        return allowed, "no matching group"
    if len(text) <= OBSERVED_CAP:
        return allowed, text
    # Too long to show whole: the user-agent lines that matched and the
    # deciding rule are all the verdict rests on; failing that, the rule.
    rule = _decisive_rule(text, "/")
    agents = [
        line
        for key, value, line in _robots_lines(text)
        if key == "user-agent" and _token(value) in (token, "*")
    ]
    short = "\n".join(agents + ([rule] if rule else []))
    if len(short) <= OBSERVED_CAP:
        return allowed, short
    return allowed, rule or "no rule matches /"


def _owned_sitemap(host: str, url: str) -> bool:
    """True if `url` is an http(s) URL on `host` or a subdomain of it.

    Guards against a robots.txt `Sitemap:` line pointing the audit's
    fetch, and the dashboard's rendered link, at an arbitrary or
    non-http(s) target (e.g. `javascript:...`).
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    return is_owned(normalize_domain(parts.hostname), [host])


def audit_domain(host: str, fetch: Fetch, *, pause: float = 0.0) -> Audit:
    """Every check for one host. Skipped checks are not emitted: on-page
    and bot-UA checks need a reachable homepage, sitemap_invalid needs a
    sitemap."""
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
    groups = _robots_groups(robots.body) if robots.ok else []
    for bot in BOTS:
        if robots.ok:
            allowed, observed = _bot_verdict(groups, bot)
        elif robots.status == 0 or robots.status >= 500:
            # RFC 9309 §2.3.1.4: unreachable means assume full disallow.
            allowed = False
            why = robots.error or f"HTTP {robots.status}"
            observed = (
                f"robots.txt unreachable ({why}): RFC 9309 reads that "
                "as disallow all"
            )
        else:  # §2.3.1.3: unavailable (4xx) means no restrictions
            allowed, observed = True, f"no robots.txt (HTTP {robots.status})"
        add(f"bot_blocked:{bot}", allowed, observed, robots_url)

    # With no browser baseline a bot's answer means nothing: skip them.
    for bot in BOTS if home.ok else ():
        r = get(home_url, bot)
        blocked = r.status in BLOCKED or r.status >= 500
        add(
            f"bot_ua_blocked:{bot}",
            not blocked,
            r.error or f"HTTP {r.status}",
            home_url,
        )

    default_sitemap = f"https://{host}/sitemap.xml"
    declared = (
        [v for k, v, _ in _robots_lines(robots.body) if k == "sitemap"]
        if robots.ok
        else []
    )
    owned = [u for u in declared if _owned_sitemap(host, u)]
    # ponytail: the first owned sitemap; the rest (and any off-host or
    # non-http(s) entries) are unread.
    sm_url = owned[0] if owned else default_sitemap
    sm = get(sm_url)
    add("sitemap_missing", sm.ok, sm.error or f"HTTP {sm.status}", sm_url)
    if sm.ok:
        root = _root_tag(sm.body)
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
