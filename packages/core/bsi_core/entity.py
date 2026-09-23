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
# /about, /company, or either under a locale segment like /en-US/.
_ABOUT_PATH = re.compile(
    r"/(?:[a-z]{2}(?:[-_][a-z]{2})?/)?(?:about|company)", re.IGNORECASE
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
    "wikidata_missing": "Wikidata holds an item for the brand whose "
    f"official website is a declared domain. {SIGNAL}",
    "wikidata_name_mismatch": "The Wikidata item's English label reads as "
    f"the brand's name or a declared alias. {SIGNAL}",
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


def _norm(s: str) -> str:
    """Casefold, keep letters and digits: "Acme, Inc." == "acme inc"."""
    return "".join(ch for ch in s.casefold() if ch.isalnum())


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


def _home_rows(
    body: str, url: str, host: str, names: set[str], hosts: Sequence[str]
) -> tuple[list[Row], list[str]]:
    """The home-page rows, and the sameAs URLs for the social comparison."""
    head = Head()
    head.feed(body)
    nodes = _ld_nodes(head.ld)
    rows: list[Row] = []
    same_as: list[str] = []
    orgs = [n for n in nodes if _types(n) & ORG_TYPES]
    # A named node over a nested stub like WebSite.publisher {"@id": ...}.
    named = [
        n for n in orgs if isinstance(n.get("name"), str) and n["name"].strip()
    ]
    org = next(iter(named or orgs), None)
    # No Organization at all is crawl's org_schema_missing, not ours.
    if org is not None:
        name = org.get("name")
        name = name.strip() if isinstance(name, str) else ""
        rows.append(
            ("org_name_mismatch", _norm(name) in names, name or "absent", url)
        )
        urls = _strings(org.get("url"))
        rows.append(
            (
                "org_url_mismatch",
                any(_owned(u, hosts) for u in urls),
                urls[0] if urls else "absent",
                url,
            )
        )
        logos = _strings(org.get("logo"))
        rows.append(
            (
                "org_logo_missing",
                bool(logos),
                logos[0] if logos else "absent",
                url,
            )
        )
        same_as = _strings(org.get("sameAs"))
        rows.append(
            (
                "org_sameas_missing",
                bool(same_as),
                ", ".join(same_as) or "absent",
                url,
            )
        )
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
            any(n in _norm(title) for n in names),
            title or "absent",
            url,
        )
    )
    about = next((h for h in head.links if _about(h, url, host)), None)
    rows.append(
        (
            "about_missing",
            about is not None,
            urljoin(url, about)
            if about is not None
            else f"no /about or /company link among {len(head.links)} links",
            url,
        )
    )
    return rows, same_as


def _social(url: str) -> str | None:
    """A profile URL as lowercase host + path, or None if it is not on a
    tracked network. x.com is twitter.com."""
    try:
        p = urlsplit(url if "://" in url else f"https://{url}")
        host = (p.hostname or "").removeprefix("www.")
    except ValueError:
        return None
    host = "twitter.com" if host == "x.com" else host
    path = p.path.rstrip("/").lower()
    return f"{host}{path}" if host in _SOCIAL_HOSTS and path else None


_LIST_PROPS = ("P856", *SOCIAL_PROPS)


def _sparql_query(ids: Sequence[str]) -> str:
    """One row per item: English label, a logo count, and each listed
    property's values joined by tabs. ids must already be Q-ids."""
    lists = " ".join(
        f'(GROUP_CONCAT(DISTINCT STR(?{p}_); separator="\\t") AS ?{p})'
        for p in _LIST_PROPS
    )
    optionals = " ".join(
        f"OPTIONAL {{ ?item wdt:{p} ?{p}_ }}" for p in ("P154", *_LIST_PROPS)
    )
    values = " ".join(f"wd:{q}" for q in ids)
    return (
        "SELECT ?item (SAMPLE(?l) AS ?label) "
        f"(COUNT(DISTINCT ?P154_) AS ?P154) {lists} "
        f"WHERE {{ VALUES ?item {{ {values} }} "
        'OPTIONAL { ?item rdfs:label ?l FILTER(LANG(?l) = "en") } '
        f"{optionals} }} GROUP BY ?item"
    )


def _items(body: str) -> dict[str, dict[str, Any]]:
    """QID -> label, logo count and property value lists, from the answer."""
    out = {}
    for b in json.loads(body)["results"]["bindings"]:
        qid = b["item"]["value"].rsplit("/", 1)[1]
        out[qid] = {
            "label": str(b.get("label", {}).get("value", "")),
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
    names: set[str],
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
    labels = {h["id"]: str(h.get("label", "")) for h in hits}
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
    # a page on the same domain, so an item whose site is the domain root
    # wins over the search order.
    verified = [
        (qid, [v for v in items[qid]["P856"] if _owned(v, hosts)])
        for qid in ids
        if qid in items
    ]
    verified = [(qid, sites) for qid, sites in verified if sites]
    match = next(
        (qid for qid, sites in verified if any(map(_is_root, sites))),
        verified[0][0] if verified else None,
    )
    if match is None:
        seen = ", ".join(f"{qid} {labels[qid]}" for qid in ids)
        return [("wikidata_missing", False, f"candidates: {seen}", human_url)]
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
            _norm(label) in names,
            f"{match}: {label or 'no English label'}",
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
    names = {_norm(n) for n in (brand_name, *aliases)} - {""}

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
        rows, same_as = _home_rows(home.body, home_url, host, names, hosts)
    site_social = {s for u in same_as if (s := _social(u))}
    try:
        rows += _wikidata_rows(get, host, brand_name, names, hosts, site_social)
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
