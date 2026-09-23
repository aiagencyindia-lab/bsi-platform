"""Entity consistency audit of a brand's own site (PRD F08, first cut).

Does the brand's schema.org Organization name it the way the operator
does, link its profiles, and point at its own domain? Does Wikidata hold a
domain-verified item that agrees? The truth is the brand record: name,
aliases and declared domains; everything else is agreement between
sources. Like crawl.py, the network is one injected callable.
"""

import json
import time
from collections.abc import Iterator, Sequence
from typing import Any
from urllib.parse import urljoin, urlsplit

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

SIGNAL = "This is an optimisation signal, not a promised outcome."
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
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
        and p.path.lower().startswith(("/about", "/company"))
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
    org = next((n for n in nodes if _types(n) & ORG_TYPES), None)
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
    if home.ok:
        rows, _same_as = _home_rows(home.body, home_url, host, names, hosts)
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
