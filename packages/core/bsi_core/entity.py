"""Entity consistency audit of a brand's own site (PRD F08, first cut).

Does the brand's schema.org Organization name it the way the operator
does, link its profiles, and point at its own domain? Does Wikidata hold a
domain-verified item that agrees? The truth is the brand record: name,
aliases and declared domains; everything else is agreement between
sources. Like crawl.py, the network is one injected callable.
"""

import json
import logging
import re
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

from bsi_core.crawl import (
    BROWSER_UA,
    OBSERVED_CAP,
    Audit,
    Check,
    Fetch,
    Head,
    Response,
)
from bsi_core.matching import is_owned, normalize_domain

log = logging.getLogger("bsi.entity")

SIGNAL = "This is an optimisation signal, not a promised outcome."
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
# One SPARQL row per candidate: wbgetentities returns every claim, and ten
# large items overflow http_fetch's body cap (findings-slice8 section 3).
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
_QID = re.compile(r"Q[0-9]+")
# /about, /aboutus, /company, or any under a locale segment like /en-US/;
# the keyword ends its segment or goes on after -, _ or . (/about-us,
# /about.html), so /aboutique and /companyname are not About pages.
_ABOUT_PATH = re.compile(
    r"/(?:[a-z]{2}(?:[-_][a-z]{2})?/)?"
    r"(?:about(?:-?us)?|company)(?:[-_.][^/]*)?(?:/|\Z)",
    re.IGNORECASE,
)
WIKIDATA_UA = (
    "bsi-platform/0.1 entity-audit "
    "(+https://github.com/aiagencyindia-lab/bsi-platform)"
)
# schema.org Organization and the subtypes a brand site plausibly uses.
ORG_TYPES = frozenset(
    {
        "Organization",
        "Corporation",
        "LocalBusiness",
        "OnlineBusiness",
        "NGO",
        "EducationalOrganization",
        "GovernmentOrganization",
        "SportsOrganization",
        "MedicalOrganization",
    }
)
SEVERITY = {
    "org_name_mismatch": "high",
    "org_url_mismatch": "medium",
    "org_logo_missing": "medium",
    "org_sameas_missing": "medium",
    "website_schema_missing": "low",
    "title_brand_missing": "medium",
    "about_missing": "low",
    "about_unreachable": "medium",
    "about_brand_missing": "low",
    "wikidata_missing": "low",
    "wikidata_name_mismatch": "medium",
    "wikidata_logo_missing": "low",
    "social_links_conflict": "medium",
}
EXPECTED = {
    "org_name_mismatch": "The Organization name reads as the brand's name "
    f"or a declared alias. {SIGNAL}",
    "org_url_mismatch": "The Organization url is on a declared brand "
    f"domain. {SIGNAL}",
    "org_logo_missing": f"The Organization declares a logo. {SIGNAL}",
    "org_sameas_missing": "The Organization lists the brand's official "
    f"profiles in sameAs. {SIGNAL}",
    "website_schema_missing": "The homepage carries a WebSite node in "
    f"JSON-LD. {SIGNAL}",
    "title_brand_missing": "The homepage title contains the brand's name "
    f"or a declared alias. {SIGNAL}",
    "about_missing": "The homepage links an About or Company page on the "
    f"same host. {SIGNAL}",
    "about_unreachable": "The About page the homepage links answers with "
    f"a 2xx status. {SIGNAL}",
    "about_brand_missing": "The About page's title or first h1 contains "
    f"the brand's name or a declared alias. {SIGNAL}",
    "wikidata_missing": "Wikidata holds an item for the brand whose "
    f"official website is a declared domain. {SIGNAL}",
    "wikidata_name_mismatch": "The Wikidata item's English (or default) "
    f"label reads as the brand's name or a declared alias. {SIGNAL}",
    "wikidata_logo_missing": "The Wikidata item has a logo image (P154). "
    f"{SIGNAL}",
    "social_links_conflict": "The social profiles in the site's sameAs and "
    f"on the Wikidata item are the same. {SIGNAL}",
}
FAMILIES = frozenset(SEVERITY)
# Wikidata property -> the profile URL it stands for (host + path).
# YouTube is left out: sites link youtube.com/@handle while Wikidata's
# P2397 holds youtube.com/channel/<id>, so the two never compare equal.
SOCIAL_PROPS = {
    "P2002": "twitter.com/{}",
    "P2013": "facebook.com/{}",
    "P2003": "instagram.com/{}",
    "P4264": "linkedin.com/company/{}",
}
_SOCIAL_HOSTS = {p.split("/", 1)[0] for p in SOCIAL_PROPS.values()}

Row = tuple[str, bool, str, str]  # code, ok, observed, url


def _words(s: str) -> tuple[str, ...]:
    """Casefolded runs of letters and digits, apostrophes dropped:
    "Café-Noir!" -> café, noir; "McDonald's" -> mcdonalds."""
    return tuple(re.findall(r"[^\W_]+", re.sub("['\u2019]", "", s.casefold())))


def _norm(s: str) -> str:
    """Casefold, keep letters and digits: "Acme, Inc." == "acmeinc"."""
    return "".join(ch for ch in s.casefold() if ch.isalnum())


# Han, Hiragana, Katakana (with half-width) and Thai are written without
# spaces between words, so a name in them is matched as a substring.
_NO_SPACES = re.compile(
    "[\u0e00-\u0e7f\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]"
)


# Trailing words a registered name adds to the brand's: "Nike, Inc.",
# "Acme Pvt. Ltd.", "Acme Private Limited".
LEGAL_SUFFIXES = frozenset(
    "inc incorporated ltd limited llc gmbh corp corporation plc co pvt "
    "private ag sa".split()
)


def _legal_words(s: str) -> tuple[str, ...]:
    """_words after dropping trailing legal-suffix words; one word always
    stays, so a brand called "Co" is still "co"."""
    words = _words(s)
    while len(words) > 1 and words[-1] in LEGAL_SUFFIXES:
        words = words[:-1]
    return words


def _legal_name(s: str) -> str:
    """The legal-suffix-free name as one string: "Acme, Inc." == "acme".
    For the name checks only: a title is matched as written."""
    return "".join(_legal_words(s))


def _names_in(text: str, names: set[str]) -> bool:
    """Whether some name's words appear as a whole-word run in text:
    "Go" is in "Go - the app" but not in "Google Search". A name in a
    script without spaces ("索尼") is a substring test instead."""
    words = _words(text)
    for name in names:
        if _NO_SPACES.search(name):
            if _norm(name) in _norm(text):
                return True
        elif n := _words(name):
            if any(
                words[i : i + len(n)] == n
                for i in range(len(words) - len(n) + 1)
            ):
                return True
    return False


def _nodes(doc: object) -> Iterator[dict[str, Any]]:
    """Every JSON object in a JSON-LD document, @graph included."""
    if isinstance(doc, dict):
        yield doc
        for v in doc.values():
            yield from _nodes(v)
    elif isinstance(doc, list):
        for v in doc:
            yield from _nodes(v)


def _ld_nodes(scripts: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for script in scripts:
        try:
            out.extend(_nodes(json.loads(script)))
        except (ValueError, RecursionError):
            continue  # one bad block must not hide the others
    return out


def _types(node: dict[str, Any]) -> set[str]:
    t = node.get("@type")
    if isinstance(t, str):
        return {t}
    if isinstance(t, list):
        return {x for x in t if isinstance(x, str)}
    return set()


def _strings(value: object) -> list[str]:
    """A schema.org value given as a string, an object with url or @id,
    or a list of either."""
    out = []
    for x in value if isinstance(value, list) else [value]:
        if isinstance(x, dict):
            x = x.get("url") or x.get("@id")
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    return out


def _owned(url: str, hosts: Sequence[str]) -> bool:
    return is_owned(normalize_domain(url), [normalize_domain(h) for h in hosts])


def _about(href: str, home_url: str, host: str) -> bool:
    try:
        p = urlsplit(urljoin(home_url, href))
        own = normalize_domain(p.hostname or "") == normalize_domain(host)
    except ValueError:
        return False
    return (
        p.scheme in ("http", "https")
        and own
        and _ABOUT_PATH.match(p.path) is not None
    )


def _org(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    orgs = [n for n in nodes if _types(n) & ORG_TYPES]
    # A named node over a nested stub like WebSite.publisher {"@id": ...}.
    named = [
        n for n in orgs if isinstance(n.get("name"), str) and n["name"].strip()
    ]
    return next(iter(named or orgs), None)


def _org_rows(
    org: dict[str, Any], url: str, legal: set[str], hosts: Sequence[str]
) -> tuple[list[Row], list[str]]:
    """The four org_* rows for the page at url, and the node's sameAs."""
    raw = org.get("name")
    name = raw.strip() if isinstance(raw, str) else ""
    if raw is not None and not isinstance(raw, str):
        name_obs = f"not a string ({type(raw).__name__})"
    else:
        name_obs = name or "absent"
    urls = _strings(org.get("url"))

    def owned(u: str) -> bool:
        # Only a root-relative url ("/", "/en/") is on the page's host;
        # "evil.net" or "//evil.net" must keep its own host.
        if u.startswith("/") and not u.startswith("//"):
            u = urljoin(url, u)
        try:
            return _owned(u, hosts)
        except ValueError:
            return False

    logos = _strings(org.get("logo"))
    same_as = _strings(org.get("sameAs"))
    rows: list[Row] = [
        (
            "org_name_mismatch",
            _legal_name(name) in legal,
            name_obs,
            url,
        ),
        (
            "org_url_mismatch",
            any(owned(u) for u in urls),
            urls[0] if urls else "absent",
            url,
        ),
        ("org_logo_missing", bool(logos), logos[0] if logos else "absent", url),
        (
            "org_sameas_missing",
            bool(same_as),
            ", ".join(same_as) or "absent",
            url,
        ),
    ]
    return rows, same_as


def _home_rows(
    body: str,
    url: str,
    host: str,
    names: set[str],
    legal: set[str],
    hosts: Sequence[str],
) -> tuple[list[Row], list[str], str | None, bool]:
    """The home-page rows, the sameAs URLs for the social comparison, the
    About URL (or None) and whether an Organization node was found.
    names are the brand names and aliases for the title, legal their
    _legal_name forms for the Organization name."""
    head = Head()
    head.feed(body)
    nodes = _ld_nodes(head.ld)
    rows: list[Row] = []
    same_as: list[str] = []
    org = _org(nodes)
    # No Organization at all is crawl's org_schema_missing, not ours.
    if org is not None:
        rows, same_as = _org_rows(org, url, legal, hosts)
    rows.append(
        (
            "website_schema_missing",
            any("WebSite" in _types(n) for n in nodes),
            f"{len(head.ld)} ld+json block(s)",
            url,
        )
    )
    title = (head.title or "").strip()
    rows.append(
        (
            "title_brand_missing",
            _names_in(title, names),
            title or "absent",
            url,
        )
    )
    about = next((h for h in head.links if _about(h, url, host)), None)
    about_url = urljoin(url, about) if about is not None else None
    rows.append(
        (
            "about_missing",
            about_url is not None,
            about_url
            or f"no /about or /company link among {len(head.links)} links",
            url,
        )
    )
    return rows, same_as, about_url, org is not None


def _about_rows(
    r: Response,
    url: str,
    needles: set[str],
    legal: set[str],
    hosts: Sequence[str],
    want_org: bool,
) -> tuple[list[Row], list[str]]:
    """The About page's rows, plus its Organization's rows and sameAs when
    want_org (the homepage had no Organization node)."""
    if not r.ok:
        return [
            ("about_unreachable", False, r.error or f"HTTP {r.status}", url)
        ], []
    head = Head()
    head.feed(r.body)
    # One space per whitespace run: a multi-line h1 reads as one line.
    title = " ".join((head.title or "").split())
    h1 = " ".join((head.h1 or "").split())
    rows: list[Row] = [
        ("about_unreachable", True, f"HTTP {r.status}", url),
        (
            "about_brand_missing",
            _names_in(title, needles) or _names_in(h1, needles),
            f"title: {title or 'absent'}; h1: {h1 or 'absent'}",
            url,
        ),
    ]
    org = _org(_ld_nodes(head.ld)) if want_org else None
    if org is None:
        return rows, []
    org_rows, same_as = _org_rows(org, url, legal, hosts)
    return org_rows + rows, same_as


def _social(url: str) -> str | None:
    """A profile URL as lowercase host + path, or None if it is not on a
    tracked network. x.com is twitter.com; www., m. and mobile. hosts are
    the plain one."""
    try:
        p = urlsplit(url if "://" in url else f"https://{url}")
        host = re.sub(r"^(?:www|m|mobile)\.", "", p.hostname or "")
    except ValueError:
        return None
    host = "twitter.com" if host == "x.com" else host
    path = p.path.rstrip("/").lower()
    return f"{host}{path}" if host in _SOCIAL_HOSTS and path else None


_LIST_PROPS = ("P856", *SOCIAL_PROPS)


def _sparql_query(ids: Sequence[str]) -> str:
    """One row per item: English and mul ("default for all languages")
    labels, a logo count, and each listed property's values joined by
    tabs. ids must already be Q-ids."""
    lists = " ".join(
        f'(GROUP_CONCAT(DISTINCT STR(?{p}_); separator="\\t") AS ?{p})'
        for p in _LIST_PROPS
    )
    optionals = " ".join(
        f"OPTIONAL {{ ?item wdt:{p} ?{p}_ }}" for p in ("P154", *_LIST_PROPS)
    )
    values = " ".join(f"wd:{q}" for q in ids)
    return (
        "SELECT ?item (SAMPLE(?en_) AS ?label) (SAMPLE(?mul_) AS ?mul) "
        f"(COUNT(DISTINCT ?P154_) AS ?P154) {lists} "
        f"WHERE {{ VALUES ?item {{ {values} }} "
        'OPTIONAL { ?item rdfs:label ?en_ FILTER(LANG(?en_) = "en") } '
        'OPTIONAL { ?item rdfs:label ?mul_ FILTER(LANG(?mul_) = "mul") } '
        f"{optionals} }} GROUP BY ?item"
    )


def _items(body: str) -> dict[str, dict[str, Any]]:
    """QID -> label, logo count and property value lists, from the answer."""
    out = {}
    for b in json.loads(body)["results"]["bindings"]:
        qid = b["item"]["value"].rsplit("/", 1)[1]
        out[qid] = {
            # English, else the mul label many items now carry instead.
            "label": str(
                b.get("label", {}).get("value", "")
                or b.get("mul", {}).get("value", "")
            ),
            "P154": int(b["P154"]["value"]),
            **{
                # An aggregate with no values is left out of the row.
                p: [v for v in b.get(p, {}).get("value", "").split("\t") if v]
                for p in _LIST_PROPS
            },
        }
    return out


def _is_root(url: str) -> bool:
    return urlsplit(url if "://" in url else f"https://{url}").path in ("", "/")


def _wikidata_rows(
    get: Callable[[str, str], Response],
    host: str,
    brand_name: str,
    legal: set[str],
    hosts: Sequence[str],
    site_social: set[str],
) -> list[Row]:
    """Raises ValueError, TypeError, AttributeError or KeyError on an
    answer of the wrong shape; the caller skips every Wikidata row then."""
    q = quote(brand_name, safe="")
    search_url = (
        f"{WIKIDATA_API}?action=wbsearchentities&search={q}"
        "&language=en&type=item&limit=10&format=json"
    )
    human_url = f"https://www.wikidata.org/w/index.php?search={q}"
    r = get(search_url, WIKIDATA_UA)
    if not r.ok:
        log.warning(
            "wikidata search failed: host=%s status=%s error=%s",
            host,
            r.status,
            r.error,
        )
        return []
    hits = json.loads(r.body)["search"]
    labels = {h["id"]: str(h.get("label") or "no label") for h in hits}
    # The ids go into a SPARQL query: anything but a Q-id stays out.
    ids = [i for i in labels if isinstance(i, str) and _QID.fullmatch(i)]
    if not ids:
        return [("wikidata_missing", False, "no search results", human_url)]
    query = quote(_sparql_query(ids), safe="")
    r = get(f"{WIKIDATA_SPARQL}?format=json&query={query}", WIKIDATA_UA)
    if not r.ok:
        log.warning(
            "wikidata query failed: host=%s status=%s error=%s",
            host,
            r.status,
            r.error,
        )
        return []
    items = _items(r.body)
    # A name search finds namesakes; only an item whose official website
    # (P856) is a declared domain is the brand. A product's item can list
    # a page on the domain, and a project's a subdomain, so the best site
    # wins: exact host at the root, exact host, subdomain root, subdomain.
    # Ties keep search order. A subdomain can host someone else's project
    # (a governance wiki), so a subdomain-only item must also be named
    # for the brand; an exact-host item always wins over it.
    exact = {normalize_domain(h) for h in hosts}

    def rank(v: str) -> int:
        return (normalize_domain(v) not in exact) * 2 + (not _is_root(v))

    ranked = [
        (min(rank(v) for v in sites), qid)
        for qid in ids
        if qid in items
        and (sites := [v for v in items[qid]["P856"] if _owned(v, hosts)])
    ]
    named = [
        (k, qid)
        for k, qid in ranked
        if k < 2 or _legal_name(items[qid]["label"]) in legal
    ]
    match = min(named, key=lambda t: t[0])[1] if named else None
    if match is None:
        seen = ", ".join(f"{qid} {labels[qid]}" for qid in ids)
        obs = f"candidates: {seen}"
        if ranked:
            sub = min(ranked, key=lambda t: t[0])[1]
            obs += (
                f"; {sub} {labels[sub]} is only on a "
                "subdomain and its label does not name the brand"
            )
        return [("wikidata_missing", False, obs, human_url)]
    item = items[match]
    label = item["label"]
    page = f"https://www.wikidata.org/wiki/{match}"
    wd_social = {
        s
        for prop, fmt in SOCIAL_PROPS.items()
        for v in item[prop]
        if (s := _social(fmt.format(v)))
    }
    only_wd = sorted(wd_social - site_social)
    only_site = sorted(site_social - wd_social)
    if wd_social and site_social:
        conflict = bool(only_wd or only_site)
        social_obs = (
            f"on Wikidata only: {', '.join(only_wd) or 'none'}; "
            f"on site only: {', '.join(only_site) or 'none'}"
            if conflict
            else f"{len(wd_social)} profiles agree"
        )
    else:
        # One side lists no profiles: sameAs_missing or Wikidata's own
        # gap covers it, so it is not a conflict.
        conflict = False
        social_obs = (
            f"nothing to compare: {len(wd_social)} on Wikidata, "
            f"{len(site_social)} on site"
        )
    return [
        ("wikidata_missing", True, f"{match}: {label}", page),
        (
            "wikidata_name_mismatch",
            _legal_name(label) in legal,
            f"{match}: {label or 'no English (or default) label'}",
            page,
        ),
        ("wikidata_logo_missing", item["P154"] > 0, match, page),
        ("social_links_conflict", not conflict, social_obs, page),
    ]


def audit_entity(
    host: str,
    brand_name: str,
    aliases: Sequence[str],
    hosts: Sequence[str],
    fetch: Fetch,
    *,
    pause: float = 0.0,
) -> Audit:
    """Every entity check for one host. Skipped checks are not emitted:
    home rows need a reachable homepage, org rows an Organization node."""
    fetches = 0
    names = {brand_name, *aliases}
    legal = {_legal_name(n) for n in (brand_name, *aliases)} - {""}
    # The About page may use the registered name: "About Acme Ltd".
    about_names = names | {" ".join(_legal_words(n)) for n in names}

    def get(url: str, ua: str) -> Response:
        nonlocal fetches
        # Always follows audit_domain's fetches to the same host, so it
        # pauses before its first fetch too.
        if pause:
            time.sleep(pause)
        fetches += 1
        return fetch(url, ua)

    home_url = f"https://{host}/"
    home = get(home_url, BROWSER_UA)
    rows: list[Row] = []
    same_as: list[str] = []
    if home.ok:
        rows, same_as, about_url, has_org = _home_rows(
            home.body, home_url, host, names, legal, hosts
        )
        if about_url is not None:
            more, about_same = _about_rows(
                get(about_url, BROWSER_UA),
                about_url,
                about_names,
                legal,
                hosts,
                not has_org,
            )
            rows += more
            same_as = same_as or about_same
    site_social = {s for u in same_as if (s := _social(u))}
    try:
        rows += _wikidata_rows(get, host, brand_name, legal, hosts, site_social)
    except (ValueError, TypeError, AttributeError, KeyError) as e:
        # An answer of the wrong shape: skip, as for a non-2xx.
        log.warning("unreadable wikidata answer: host=%s error=%r", host, e)
    checks = [
        Check(
            code,
            ok,
            SEVERITY[code],
            observed.strip()[:OBSERVED_CAP],
            EXPECTED[code],
            url,
        )
        for code, ok, observed, url in rows
    ]
    return Audit(checks, fetches)
