# Slice 8: Entity Consistency Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Check each declared brand domain for a consistent entity: the brand's schema.org Organization markup, its homepage title and About link, and a domain-verified Wikidata item. Failing checks become `fix_entity` recommendations.

**Architecture:** A new pure module `bsi_core/entity.py` returns the same `Audit`/`Check` shapes as `crawl.py`. `run_crawl_audit` runs it after `audit_domain` for each host and stores both check lists in one `site_audit` row. The existing `_crawl` rule routes entity families to the new `fix_entity` type. Migration 0013 only widens the rec-type constraint.

**Tech Stack:** Python 3.13, stdlib `html.parser`/`json`/`urllib.parse`, the existing SSRF-guarded `crawl.http_fetch`, SQLAlchemy 2, Alembic, FastAPI/pydantic 2, pytest, Next.js (one constant).

**Spec:** `docs/superpowers/specs/2026-09-23-slice8-entity-consistency-design.md`

## Global Constraints

- Repo root `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command: start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- Branch `slice8-entity-consistency` (already exists, spec committed).
- Tests never touch the network: every fetch is an injected `Fetch = Callable[[url, user_agent], Response]`.
- No transaction may be open during any fetch (proved by `test_no_transaction_is_open_while_fetching`).
- Every `entity.EXPECTED` string ends with exactly: `This is an optimisation signal, not a promised outcome.`
- Recommendation copy must not contain any of: guarantee, will rank, will appear, will be recommended, ensure, boost, #1, top spot, dominat, certain (`tests/unit/test_recommend_copy.py` `FORBIDDEN`). The copy must contain "Metric to watch:".
- Wikidata user agent, exactly: `bsi-platform/0.1 entity-audit (+https://github.com/aiagencyindia-lab/bsi-platform)`.
- `FEASIBILITY["fix_entity"] = 0.7`; reach 1.0; pressure from `PRESSURE_BY_SEVERITY = {"high": 1.0, "medium": 0.5, "low": 0.2}`.
- ruff line length 80; `mypy --strict` covers `packages/core/bsi_core`.
- Commit trailer, exactly: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- The gate, run at the end of every task (both lines must pass):
  ```bash
  cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100
  cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate
  ```
  Two pytest warnings (starlette TestClient / anyio) are pre-existing; ignore them.

## File map

| File | Responsibility |
|---|---|
| `packages/core/bsi_core/crawl.py` | `_Head` → public `Head`, gains `links` |
| `packages/core/bsi_core/entity.py` (new) | `audit_entity`, constants, home-page and Wikidata checks |
| `packages/core/bsi_core/models.py` | `REC_TYPES` gains `fix_entity` |
| `packages/core/bsi_core/recommend.py` | `FEASIBILITY`, `_ENTITY_TITLES`, `entity_copy`, `_crawl` routing |
| `migrations/versions/0013_fix_entity_rec_type.py` (new) | widen `ck_recommendation_type` |
| `apps/api/bsi_api/routers/recommendations.py` | `NO_IMPACT` gains `fix_entity` |
| `apps/api/bsi_api/schemas.py` | `CheckOut.severity` tolerates unknown values |
| `apps/workers/bsi_workers/worker.py` | `run_crawl_audit` also runs `audit_entity` |
| `apps/web/src/lib/format.ts` | `KIND.fix_entity = "Entity fix"` |
| `tests/unit/test_entity.py` (new) | all entity checks from canned responses |
| `tests/unit/test_recommend_copy.py`, `tests/integration/test_recommend.py`, `test_api_recommendations.py`, `test_api_audits.py`, `test_crawl_audit.py` | extended |
| `docs/findings-slice8.md` (new), `docs/README.md` | live results, index |

---

### Task 1: `crawl.Head` and the home-page entity checks

**Files:**
- Modify: `packages/core/bsi_core/crawl.py` (class `_Head` at ~L313; its use in `audit_domain` at ~L574)
- Create: `packages/core/bsi_core/entity.py`
- Test: `tests/unit/test_entity.py`

**Interfaces:**
- Consumes: `crawl.BROWSER_UA`, `crawl.OBSERVED_CAP`, `crawl.Audit`, `crawl.Check`, `crawl.Fetch`, `crawl.Response`, `matching.is_owned`, `matching.normalize_domain`.
- Produces: `crawl.Head` (attrs `title`, `description`, `canonical`, `h1`, `ld: list[str]`, `links: list[str]`); `entity.audit_entity(host: str, brand_name: str, aliases: Sequence[str], hosts: Sequence[str], fetch: Fetch, *, pause: float = 0.0) -> Audit`; `entity.SEVERITY: dict[str, str]`, `entity.EXPECTED: dict[str, str]`, `entity.FAMILIES: frozenset[str]`, `entity.SIGNAL: str`, `entity.WIKIDATA_UA: str`. In this task `audit_entity` does the home page only (1 fetch); Task 2 adds Wikidata.

- [ ] **Step 1: Promote `_Head` to `Head` and collect links**

In `crawl.py`, rename the class `_Head` to `Head` and the one call `head = _Head()` in `audit_domain` to `head = Head()`. Change its docstring and add a `links` list and an `a` branch:

```python
class Head(HTMLParser):
    """Collects what the on-page checks look at, and nothing else.

    Public: entity.py reads the same homepage fields plus the links."""

    def __init__(self) -> None:
        super().__init__()
        self.title: str | None = None
        self.description: str | None = None
        self.canonical: str | None = None
        self.h1: str | None = None
        self.ld: list[str] = []
        self.links: list[str] = []
        self._in: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
        elif tag == "title":
            ...  # the rest of the existing chain, unchanged
```

Keep every other branch exactly as it is.

- [ ] **Step 2: Write the failing unit tests for the home-page checks**

Create `tests/unit/test_entity.py`:

```python
"""audit_entity from canned responses. Nothing here touches the network."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest
from bsi_core import crawl, entity
from bsi_core.crawl import BROWSER_UA, Response
from bsi_core.entity import (
    EXPECTED,
    FAMILIES,
    SEVERITY,
    SIGNAL,
    WIKIDATA_UA,
    audit_entity,
)

HOME_CODES = {
    "org_name_mismatch",
    "org_url_mismatch",
    "org_logo_missing",
    "org_sameas_missing",
    "website_schema_missing",
    "title_brand_missing",
    "about_missing",
}
ORG = {
    "@type": "Organization",
    "name": "Acme, Inc.",
    "url": "https://www.acme.com/",
    "logo": {"@type": "ImageObject", "url": "https://acme.com/logo.png"},
    "sameAs": [
        "https://x.com/AcmeHQ",
        "https://www.linkedin.com/company/acme/",
    ],
}
SITE = {"@type": "WebSite", "url": "https://acme.com/"}


def home(
    org=ORG,
    extra=(SITE,),
    title="Acme | Rockets",
    links=('<a href="/about-us">About</a>',),
):
    graph = [n for n in (org, *extra) if n is not None]
    ld = json.dumps({"@context": "https://schema.org", "@graph": graph})
    return (
        f"<html><head><title>{title}</title>"
        f'<script type="application/ld+json">{ld}</script></head>'
        f"<body>{''.join(links)}</body></html>"
    )


def org_home(drop=(), **kv):
    org = {k: v for k, v in {**ORG, **kv}.items() if k not in drop}
    return Response(200, home(org=org))


def fetcher(home_resp=None, search=None, entities=None):
    """A fetch that answers the homepage and the two Wikidata calls."""
    calls = []

    def fetch(url, ua):
        calls.append((url, ua))
        if url == "https://acme.com/":
            return home_resp or Response(200, home())
        action = parse_qs(urlsplit(url).query).get("action", [""])[0]
        if action == "wbsearchentities":
            return search or Response(200, json.dumps({"search": []}))
        if action == "wbgetentities":
            return entities or Response(200, json.dumps({"entities": {}}))
        raise AssertionError(f"unexpected fetch {url}")

    fetch.calls = calls
    return fetch


def run(fetch, name="Acme", aliases=("Acme Inc",), pause=0.0):
    return audit_entity(
        "acme.com", name, list(aliases), ["acme.com"], fetch, pause=pause
    )


def verdicts(audit):
    return {c.code: c.ok for c in audit.checks}


def home_verdicts(audit):
    return {k: v for k, v in verdicts(audit).items() if k in HOME_CODES}


def test_a_consistent_homepage_passes_every_home_check():
    f = fetcher()
    a = run(f)
    assert home_verdicts(a) == dict.fromkeys(HOME_CODES, True)
    assert f.calls[0] == ("https://acme.com/", BROWSER_UA)
    about = next(c for c in a.checks if c.code == "about_missing")
    assert about.observed == "https://acme.com/about-us"


@pytest.mark.parametrize(
    ("code", "resp"),
    [
        ("org_name_mismatch", org_home(name="Acme Rockets Ltd")),
        ("org_url_mismatch", org_home(url="https://acme-shop.net/")),
        ("org_logo_missing", org_home(drop=("logo",))),
        ("org_sameas_missing", org_home(sameAs=[])),
        ("website_schema_missing", Response(200, home(extra=()))),
        ("title_brand_missing", Response(200, home(title="Rockets"))),
        (
            "about_missing",
            Response(
                200, home(links=('<a href="https://other.com/about">x</a>',))
            ),
        ),
    ],
)
def test_each_home_check_fails_alone(code, resp):
    got = home_verdicts(run(fetcher(home_resp=resp)))
    assert {k for k, ok in got.items() if not ok} == {code}


def test_observed_values_name_what_was_found():
    a = run(fetcher(home_resp=org_home(name="Acme Rockets Ltd", drop=("url",))))
    obs = {c.code: c.observed for c in a.checks}
    assert obs["org_name_mismatch"] == "Acme Rockets Ltd"
    assert obs["org_url_mismatch"] == "absent"


def test_names_normalise_case_punctuation_and_unicode():
    org = {**ORG, "name": "CAFÉ NOIR!"}
    f = fetcher(home_resp=Response(200, home(org=org, title="café-noir shop")))
    got = verdicts(run(f, name="Café Noir", aliases=()))
    assert got["org_name_mismatch"] and got["title_brand_missing"]


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://www.acme.com/", True),
        ("http://acme.com", True),
        ("https://shop.acme.com/x", True),
        ("https://acme.com.evil.net/", False),
        ("", False),
    ],
)
def test_org_url_must_be_a_declared_domain(url, ok):
    got = verdicts(run(fetcher(home_resp=org_home(url=url))))
    assert got["org_url_mismatch"] is ok


@pytest.mark.parametrize(
    ("logo", "ok"),
    [
        ("https://acme.com/l.png", True),
        ({"@id": "https://acme.com/#logo"}, True),
        ([{"url": "https://acme.com/l.png"}], True),
        ("", False),
        ([], False),
        ({"@type": "ImageObject"}, False),
    ],
)
def test_logo_accepts_every_schema_org_shape(logo, ok):
    got = verdicts(run(fetcher(home_resp=org_home(logo=logo))))
    assert got["org_logo_missing"] is ok


def test_sameas_may_be_a_single_string():
    got = verdicts(run(fetcher(home_resp=org_home(sameAs="https://x.com/a"))))
    assert got["org_sameas_missing"]


@pytest.mark.parametrize("kind", ["Corporation", ["Organization", "Brand"]])
def test_organization_subtypes_count(kind):
    got = home_verdicts(run(fetcher(home_resp=org_home(**{"@type": kind}))))
    assert got == dict.fromkeys(HOME_CODES, True)


def test_no_organization_skips_the_org_rows_only():
    got = verdicts(run(fetcher(home_resp=Response(200, home(org=None)))))
    assert not [c for c in got if c.startswith("org_")]
    assert {"website_schema_missing", "title_brand_missing"} <= set(got)
    assert "about_missing" in got


def test_a_malformed_block_does_not_hide_a_good_one():
    body = home().replace(
        "<script", '<script type="application/ld+json">{bad</script><script', 1
    )
    got = home_verdicts(run(fetcher(home_resp=Response(200, body))))
    assert got == dict.fromkeys(HOME_CODES, True)


def test_an_unreachable_homepage_emits_no_home_rows():
    a = run(fetcher(home_resp=Response(500, "")))
    assert not home_verdicts(a)


@pytest.mark.parametrize(
    ("href", "ok"),
    [
        ("/about", True),
        ("about-us", True),
        ("https://www.acme.com/Company/team", True),
        ("https://other.com/about", False),
        ("mailto:hello@acme.com", False),
        ("http://[::1", False),
    ],
)
def test_about_link_must_stay_on_the_brand_host(href, ok):
    resp = Response(200, home(links=(f'<a href="{href}">x</a>',)))
    assert verdicts(run(fetcher(home_resp=resp)))["about_missing"] is ok


def test_constants_are_consistent():
    assert set(EXPECTED) == set(SEVERITY) == FAMILIES
    assert set(SEVERITY.values()) <= {"high", "medium", "low"}
    assert all(v.endswith(SIGNAL) for v in EXPECTED.values())
    assert SIGNAL == "This is an optimisation signal, not a promised outcome."
    # The rule routes by family: entity and crawl must never share one.
    assert not FAMILIES & set(crawl.SEVERITY)
    assert len(FAMILIES) == 11
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_entity.py -q`
Expected: FAIL at import, `ModuleNotFoundError: No module named 'bsi_core.entity'`.

- [ ] **Step 4: Create `entity.py` with the constants and home-page checks**

```python
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
            ("org_logo_missing", bool(logos), logos[0] if logos else "absent", url)
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
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_entity.py tests/unit/test_crawl.py -q`
Expected: all pass. If a case fails, fix the code, not the expectation, unless the expectation contradicts the spec.

- [ ] **Step 6: Run the gate, then commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/crawl.py packages/core/bsi_core/entity.py tests/unit/test_entity.py && git commit -m "feat(entity): home-page entity checks over schema.org Organization

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Wikidata checks

**Files:**
- Modify: `packages/core/bsi_core/entity.py`
- Test: `tests/unit/test_entity.py`

**Interfaces:**
- Consumes: Task 1's `entity.py` (`_norm`, `_strings`, `_owned`, `Row`, `get`, `_home_rows` returning `(rows, same_as)`).
- Produces: `audit_entity` now makes 2 or 3 fetches (home, search, getentities only when search returned ids) and emits `wikidata_missing`, and, only when an item matches, `wikidata_name_mismatch`, `wikidata_logo_missing`, `social_links_conflict`. `entity.SOCIAL_PROPS: dict[str, str]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_entity.py`:

```python
def claims(props):
    return {
        p: [
            {"mainsnak": {"snaktype": "value", "datavalue": {"value": v}}}
            for v in vals
        ]
        for p, vals in props.items()
    }


MATCH_PROPS = {
    "P856": ["http://www.acme.com"],
    "P154": ["Acme logo.svg"],
    "P2002": ["AcmeHQ"],
    "P4264": ["acme"],
}


def item(label="Acme Inc", drop=(), **props):
    p = {k: v for k, v in {**MATCH_PROPS, **props}.items() if k not in drop}
    return {"labels": {"en": {"value": label}}, "claims": claims(p)}


IMPOSTOR = item(label="Acme", P856=["https://acme.org/"])
SEARCH = Response(
    200,
    json.dumps(
        {"search": [{"id": "Q1", "label": "Acme"}, {"id": "Q2", "label": "Acme Inc"}]}
    ),
)


def ents(match=None, **more):
    body = {"Q1": IMPOSTOR, "Q2": match or item(), **more}
    return Response(200, json.dumps({"entities": body}))


def wiki(**kw):
    """A fetcher with a domain-verified Wikidata match by default."""
    kw.setdefault("search", SEARCH)
    kw.setdefault("entities", ents())
    return fetcher(**kw)


WIKI_CODES = {
    "wikidata_missing",
    "wikidata_name_mismatch",
    "wikidata_logo_missing",
    "social_links_conflict",
}


def test_a_consistent_brand_passes_every_check():
    f = wiki()
    a = run(f)
    assert verdicts(a) == dict.fromkeys(SEVERITY, True)
    assert a.fetches == 3
    assert [ua for _, ua in f.calls] == [BROWSER_UA, WIKIDATA_UA, WIKIDATA_UA]
    search = parse_qs(urlsplit(f.calls[1][0]).query)
    assert search["action"] == ["wbsearchentities"]
    assert search["search"] == ["Acme"]
    got = parse_qs(urlsplit(f.calls[2][0]).query)
    assert got["ids"] == ["Q1|Q2"]
    assert got["props"] == ["labels|claims"]
    obs = {c.code: (c.observed, c.url) for c in a.checks}
    # The impostor comes first in search order; its P856 is acme.org.
    assert obs["wikidata_missing"] == (
        "Q2: Acme Inc",
        "https://www.wikidata.org/wiki/Q2",
    )
    assert obs["social_links_conflict"][0] == "2 profiles agree"


@pytest.mark.parametrize(
    ("code", "kw"),
    [
        ("wikidata_name_mismatch", {"entities": ents(item(label="Acme Rockets"))}),
        ("wikidata_logo_missing", {"entities": ents(item(drop=("P154",)))}),
        ("social_links_conflict", {"entities": ents(item(P2002=["acme_x"]))}),
    ],
)
def test_each_wikidata_check_fails_alone(code, kw):
    got = verdicts(run(wiki(**kw)))
    assert {k for k, ok in got.items() if not ok} == {code}


def test_no_domain_verified_candidate_is_wikidata_missing_only():
    a = run(wiki(entities=ents(item(P856=["https://acme.org"]))))
    got = {k: v for k, v in verdicts(a).items() if k in WIKI_CODES}
    assert got == {"wikidata_missing": False}
    miss = next(c for c in a.checks if c.code == "wikidata_missing")
    assert miss.observed == "candidates: Q1 Acme, Q2 Acme Inc"
    assert miss.url == "https://www.wikidata.org/w/index.php?search=Acme"


def test_empty_search_is_missing_without_a_second_call():
    f = wiki(search=Response(200, json.dumps({"search": []})))
    a = run(f)
    got = {c.code: (c.ok, c.observed) for c in a.checks if c.code in WIKI_CODES}
    assert got == {"wikidata_missing": (False, "no search results")}
    assert a.fetches == 2


@pytest.mark.parametrize(
    ("kw", "fetches"),
    [
        ({"search": Response(500, "")}, 2),
        ({"search": Response(0, "", "ConnectError('x')")}, 2),
        ({"search": Response(200, "<html>")}, 2),
        ({"search": Response(200, json.dumps({"error": {"code": "x"}}))}, 2),
        ({"search": Response(200, json.dumps({"search": [{"x": 1}]}))}, 2),
        ({"entities": Response(503, "")}, 3),
        ({"entities": Response(200, "not json")}, 3),
        ({"entities": ents(item(), Q1=[])}, 3),
    ],
)
def test_an_unreadable_wikidata_answer_skips_its_checks(kw, fetches):
    a = run(wiki(**kw))
    assert not WIKI_CODES & set(verdicts(a))
    assert a.fetches == fetches
    assert HOME_CODES <= set(verdicts(a))  # the home rows still stand


def test_wikidata_runs_when_the_homepage_is_down():
    a = run(wiki(home_resp=Response(500, "")))
    assert set(verdicts(a)) == WIKI_CODES
    assert a.fetches == 3


@pytest.mark.parametrize(
    ("same_as", "props", "observed"),
    [
        (
            [*ORG["sameAs"], "https://instagram.com/acme"],
            {},
            "on Wikidata only: none; on site only: instagram.com/acme",
        ),
        (
            ORG["sameAs"],
            {"P2013": ["Acme"]},
            "on Wikidata only: facebook.com/acme; on site only: none",
        ),
    ],
)
def test_social_conflict_in_each_direction(same_as, props, observed):
    a = run(wiki(home_resp=org_home(sameAs=same_as), entities=ents(item(**props))))
    c = next(c for c in a.checks if c.code == "social_links_conflict")
    assert (c.ok, c.observed) == (False, observed)


@pytest.mark.parametrize(
    ("same_as", "drop"),
    [
        (["https://en.wikipedia.org/wiki/Acme"], ()),
        (ORG["sameAs"], ("P2002", "P4264")),
    ],
)
def test_no_conflict_when_one_side_has_no_socials(same_as, drop):
    f = wiki(home_resp=org_home(sameAs=same_as), entities=ents(item(drop=drop)))
    c = next(c for c in run(f).checks if c.code == "social_links_conflict")
    assert c.ok
    assert c.observed.startswith("nothing to compare")


def test_pause_is_taken_before_every_fetch(monkeypatch):
    sleeps = []
    monkeypatch.setattr(entity.time, "sleep", sleeps.append)
    run(wiki(), pause=0.5)
    assert sleeps == [0.5, 0.5, 0.5]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_entity.py -q`
Expected: the new tests FAIL (no Wikidata rows; `fetches == 1`). Task 1's tests still pass.

- [ ] **Step 3: Add the Wikidata code to `entity.py`**

Change the imports to `from collections.abc import Callable, Iterator, Sequence` and `from urllib.parse import quote, urljoin, urlsplit`. Add after `FAMILIES`:

```python
# Wikidata property -> the profile URL it stands for (host + path).
SOCIAL_PROPS = {
    "P2002": "twitter.com/{}",
    "P2013": "facebook.com/{}",
    "P2003": "instagram.com/{}",
    "P4264": "linkedin.com/company/{}",
    "P2397": "youtube.com/channel/{}",
}
_SOCIAL_HOSTS = {p.split("/", 1)[0] for p in SOCIAL_PROPS.values()}
```

Add these helpers before `audit_entity`:

```python
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


def _values(item: dict[str, Any], prop: str) -> list[str]:
    """The string values of one Wikidata claim."""
    out = []
    for claim in item.get("claims", {}).get(prop, []):
        value = claim["mainsnak"].get("datavalue", {}).get("value")
        if isinstance(value, str):
            out.append(value)
    return out


def _wikidata_rows(
    get: Callable[[str, str], Response],
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
        return []
    hits = json.loads(r.body)["search"]
    labels = {h["id"]: str(h.get("label", "")) for h in hits}
    ids = list(labels)
    if not ids:
        return [("wikidata_missing", False, "no search results", human_url)]
    r = get(
        f"{WIKIDATA_API}?action=wbgetentities&ids={quote('|'.join(ids))}"
        "&props=labels%7Cclaims&languages=en&format=json",
        WIKIDATA_UA,
    )
    if not r.ok:
        return []
    entities = json.loads(r.body)["entities"]
    # A name search finds namesakes; only an item whose official website
    # (P856) is a declared domain is the brand.
    match = next(
        (
            qid
            for qid in ids
            if any(_owned(v, hosts) for v in _values(entities[qid], "P856"))
        ),
        None,
    )
    if match is None:
        seen = ", ".join(f"{qid} {labels[qid]}" for qid in ids)
        return [("wikidata_missing", False, f"candidates: {seen}", human_url)]
    item = entities[match]
    label = str(item.get("labels", {}).get("en", {}).get("value", ""))
    page = f"https://www.wikidata.org/wiki/{match}"
    wd_social = {
        s
        for prop, fmt in SOCIAL_PROPS.items()
        for v in _values(item, prop)
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
        ("wikidata_logo_missing", bool(_values(item, "P154")), match, page),
        ("social_links_conflict", not conflict, social_obs, page),
    ]
```

In `audit_entity`, replace the block from `rows: list[Row] = []` to the end of the `if home.ok:` with:

```python
    rows: list[Row] = []
    same_as: list[str] = []
    if home.ok:
        rows, same_as = _home_rows(home.body, home_url, host, names, hosts)
    site_social = {s for u in same_as if (s := _social(u))}
    try:
        rows += _wikidata_rows(get, brand_name, names, hosts, site_social)
    except (ValueError, TypeError, AttributeError, KeyError):
        pass  # an answer of the wrong shape: skip, as for a non-2xx
```

Check the observed text for the all-pass case by hand: site `x.com/AcmeHQ` → `twitter.com/acmehq`, `linkedin.com/company/acme/` → `linkedin.com/company/acme`; Wikidata `twitter.com/AcmeHQ` → `twitter.com/acmehq`, `linkedin.com/company/acme`. Two agree.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_entity.py -q`
Expected: all pass.

- [ ] **Step 5: Run the gate, then commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/entity.py tests/unit/test_entity.py && git commit -m "feat(entity): domain-verified Wikidata checks and social comparison

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The `fix_entity` recommendation type

**Files:**
- Modify: `packages/core/bsi_core/models.py:39-45` (`REC_TYPES`)
- Create: `migrations/versions/0013_fix_entity_rec_type.py`
- Modify: `packages/core/bsi_core/recommend.py` (`FEASIBILITY` ~L46, after `crawl_copy` ~L169, `_crawl` ~L408, module docstring ~L17)
- Modify: `apps/api/bsi_api/routers/recommendations.py:20` (`NO_IMPACT`)
- Modify: `apps/web/src/lib/format.ts:75-81` (`KIND`)
- Test: `tests/unit/test_recommend_copy.py`, `tests/integration/test_recommend.py`, `tests/integration/test_api_recommendations.py`

**Interfaces:**
- Consumes: `entity.FAMILIES`, `entity.EXPECTED`, `entity.SEVERITY` (Task 1).
- Produces: `recommend.entity_copy(brand: str, domain: str, check: dict[str, Any]) -> tuple[str, str]`; rec type `"fix_entity"` with `subject_key = f"{domain}:{code}"`.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_recommend_copy.py`, add `from bsi_core import entity` and `entity_copy` to the `bsi_core.recommend` import, then after the `CASES += [...crawl...]` block add:

```python
CASES += [
    entity_copy(
        "Nike",
        "nike.com",
        {
            "code": code,
            "observed": "Q42: Nikey",
            "expected": "x",
            "url": "https://nike.com/",
            "severity": sev,
        },
    )
    for code, sev in entity.SEVERITY.items()
]


def test_entity_copy_names_the_brand_domain_and_evidence():
    title, body = entity_copy(
        "Nike",
        "nike.com",
        {
            "code": "org_name_mismatch",
            "observed": "Nikey Inc",
            "expected": "x",
            "url": "https://nike.com/",
            "severity": "high",
        },
    )
    assert "nike.com" in title
    assert "Nikey Inc" in body and "https://nike.com/" in body
    assert entity.EXPECTED["org_name_mismatch"] in body
    assert "mention rate" in body
```

In `tests/integration/test_recommend.py`, after `test_an_unrecognized_check_is_skipped_not_fatal`, add:

```python
def test_each_failing_entity_check_is_one_entity_recommendation(owner, world):
    _site_audit(
        owner,
        world,
        [
            _check("org_name_mismatch", False, "high"),
            _check("social_links_conflict", False, "medium"),
            _check("wikidata_missing", False, "low"),
            _check("about_missing", True, "low"),
            _check("llms_missing", False, "low"),
        ],
    )
    recs = found(world)
    ent = {k: c for k, c in recs.items() if k[0] == "fix_entity"}
    codes = ("org_name_mismatch", "social_links_conflict", "wikidata_missing")
    assert set(ent) == {("fix_entity", f"nike.com:{c}") for c in codes}
    # Judged, not measured: reach 1.0 x severity weight x 0.7.
    assert [ent[("fix_entity", f"nike.com:{c}")].priority for c in codes] == [
        0.7,
        0.35,
        0.14,
    ]
    name = ent[("fix_entity", "nike.com:org_name_mismatch")]
    assert (name.reach, name.pressure, name.feasibility) == (1.0, 1.0, 0.7)
    assert name.evidence["code"] == "org_name_mismatch"
    assert name.evidence["domain"] == "nike.com"
    # Crawl checks in the same row still route to fix_crawlability.
    assert ("fix_crawlability", "nike.com:llms_missing") in recs
    assert ("fix_entity", "nike.com:llms_missing") not in recs
```

In `tests/integration/test_api_recommendations.py`, replace `test_a_crawl_task_measures_no_impact` with a parametrised version:

```python
@pytest.mark.parametrize(
    ("code", "rtype"),
    [("llms_missing", "fix_crawlability"), ("wikidata_missing", "fix_entity")],
)
def test_a_site_task_measures_no_impact(
    client, owner, make_org, make_brand, code, rtype
):
    org = make_org()
    bid = make_brand(org)
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host="nike.com"))
        s.add(
            m.SiteAudit(
                org_id=org.id,
                brand_id=bid,
                domain="nike.com",
                checks=[
                    {
                        "code": code,
                        "ok": False,
                        "severity": "low",
                        "observed": "HTTP 404",
                        "expected": "e",
                        "url": "https://nike.com/llms.txt",
                    }
                ],
            )
        )
    recs = client.post(
        f"/v1/brands/{bid}/recommendations/generate", headers=org.headers
    ).json()
    rec = next(r for r in recs if r["type"] == rtype)
    task = client.post(
        f"/v1/brands/{bid}/recommendations/{rec['id']}/accept",
        headers=org.headers,
    ).json()
    assert task["measures_impact"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_recommend_copy.py tests/integration/test_recommend.py tests/integration/test_api_recommendations.py -q`
Expected: FAIL. `ImportError: cannot import name 'entity_copy'` for the copy test; the others fail once that is fixed, because no `fix_entity` rec is produced.

- [ ] **Step 3: Widen the type in the model and the database**

`models.py` `REC_TYPES`: append `"fix_entity",` after `"fix_crawlability",`.

Create `migrations/versions/0013_fix_entity_rec_type.py`:

```python
"""fix_entity rec type"""

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

OLD_TYPES = (
    "'pursue_citation_source', 'create_content', "
    "'add_competitor', 'sample_more', 'fix_crawlability'"
)
NEW_TYPES = OLD_TYPES + ", 'fix_entity'"


def _rec_type_check(values: str) -> None:
    op.drop_constraint("ck_recommendation_type", "recommendation")
    op.create_check_constraint(
        "ck_recommendation_type", "recommendation", f"type IN ({values})"
    )


def upgrade() -> None:
    _rec_type_check(NEW_TYPES)


def downgrade() -> None:
    op.execute(
        "DELETE FROM task WHERE recommendation_id IN "
        "(SELECT id FROM recommendation WHERE type = 'fix_entity')"
    )
    op.execute("DELETE FROM recommendation WHERE type = 'fix_entity'")
    _rec_type_check(OLD_TYPES)
```

`tests/conftest.py` upgrades `bsi_test` to head at session start, and `test_constraints.py` already checks `ck_recommendation_type` against `m.REC_TYPES`, so it now covers the sixth value.

- [ ] **Step 4: Route entity families in the rule**

In `recommend.py`:

1. Imports: change `from .crawl import expected, family` to keep it, and add `from . import entity` below `from . import models as m`.
2. `FEASIBILITY`: after `"fix_crawlability": 0.8,` add:
   ```python
       # Markup is minutes of work; a Wikidata edit needs sources and can
       # be reverted by its editors.
       "fix_entity": 0.7,
   ```
3. Module docstring: after "...pressure is the check's severity weight." add the sentence " fix_entity is judged the same way."
4. After `crawl_copy`, add:

```python
_ENTITY_TITLES = {
    "org_name_mismatch": "Fix the Organization name on {domain}",
    "org_url_mismatch": "Point the Organization url on {domain} at "
    "{brand}'s domain",
    "org_logo_missing": "Add a logo to the Organization on {domain}",
    "org_sameas_missing": "List {brand}'s profiles in sameAs on {domain}",
    "website_schema_missing": "{domain} declares no WebSite",
    "title_brand_missing": "The {domain} homepage title omits {brand}",
    "about_missing": "The {domain} homepage links no About page",
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
```

5. In `_crawl`, replace the body of `for check in checks:` with:

```python
        for check in checks:
            if check["ok"]:
                continue
            code = check["code"]
            fam = family(code)
            if fam in entity.FAMILIES:
                kind, copy = "fix_entity", entity_copy
            elif fam in _CRAWL_TITLES:
                kind, copy = "fix_crawlability", crawl_copy
            else:
                kind = ""
            if not kind or check["severity"] not in PRESSURE_BY_SEVERITY:
                log.warning(
                    "skipping unrecognized site check: brand=%s domain=%s "
                    "code=%s",
                    brand,
                    domain,
                    code,
                )
                continue
            title, body = copy(brand, domain, check)
            out.append(
                Candidate(
                    kind,
                    f"{domain}:{check['code']}",
                    title,
                    body,
                    {**check, "domain": domain, "audit_id": str(audit_id)},
                    # Not measured against answers; see PRESSURE_BY_SEVERITY.
                    1.0,
                    PRESSURE_BY_SEVERITY[check["severity"]],
                )
            )
```

Update `_crawl`'s docstring first line to "One candidate per failing check (crawl or entity) in each domain's latest audit." If mypy complains that `copy` may be unbound, annotate before the `if`: `copy: Callable[[str, str, dict[str, Any]], tuple[str, str]]` with `from collections.abc import Callable, Sequence`.

- [ ] **Step 5: API and web labels**

`apps/api/bsi_api/routers/recommendations.py`: `NO_IMPACT = {"add_competitor", "sample_more", "fix_crawlability", "fix_entity"}` and extend the comment above it with "An entity fix likewise changes what an engine can match, not an answer within a window."

`apps/web/src/lib/format.ts` `KIND`: after `fix_crawlability: "Site fix",` add `fix_entity: "Entity fix",`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_recommend_copy.py tests/integration/test_recommend.py tests/integration/test_api_recommendations.py tests/integration/test_constraints.py -q`
Expected: all pass.

- [ ] **Step 7: Round-trip the migration on the dev database**

The dev `recommendation` table is empty, so the downgrade deletes nothing.

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && uv run alembic upgrade head && uv run alembic downgrade 0012 && uv run alembic upgrade head && uv run alembic current
```
Expected: last line shows `0013 (head)`.

- [ ] **Step 8: Run the gate, then commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/models.py packages/core/bsi_core/recommend.py migrations/versions/0013_fix_entity_rec_type.py apps/api/bsi_api/routers/recommendations.py apps/web/src/lib/format.ts tests/unit/test_recommend_copy.py tests/integration/test_recommend.py tests/integration/test_api_recommendations.py && git commit -m "feat(recommend): fix_entity recommendations from entity checks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Run the entity audit in the worker; tolerate unknown severities in the API

**Files:**
- Modify: `apps/workers/bsi_workers/worker.py` (imports ~L14; `run_crawl_audit` ~L141-186)
- Modify: `apps/api/bsi_api/schemas.py` (`CheckOut` ~L204; imports ~L13)
- Test: `tests/integration/test_crawl_audit.py`, `tests/integration/test_api_audits.py`

**Interfaces:**
- Consumes: `entity.audit_entity` (Tasks 1–2), `crawl.Audit`.
- Produces: `site_audit.checks` rows hold crawl then entity checks; `fetches` is their sum.

- [ ] **Step 1: Update and add the failing worker tests**

In `tests/integration/test_crawl_audit.py`:

1. `test_audit_job_stores_one_row_per_domain`: replace `assert rows[0].fetches == 12 and len(rows[0].checks) >= 20` with:
   ```python
    # 12 crawl fetches, then the entity audit: the homepage and a Wikidata
    # search whose HTML answer is unreadable, so no Wikidata rows.
    assert rows[0].fetches == 14 and len(rows[0].checks) >= 20
    codes = {c["code"] for c in rows[0].checks}
    # "<title>x</title>" names no Acme and links nothing; no JSON-LD.
    assert {"title_brand_missing", "about_missing"} <= codes
    assert not {c for c in codes if c.startswith(("org_n", "wikidata"))}
   ```
2. `test_production_pauses_between_fetches`: change `assert sleeps == [0.25] * 11` to:
   ```python
    # 11 between the 12 crawl fetches, then one before each of the two
    # entity fetches.
    assert sleeps == [0.25] * 13
   ```
3. Add after `test_one_domain_crashing_keeps_the_others_rows`:

```python
def test_an_entity_crash_keeps_the_crawl_checks(
    monkeypatch, owner, make_org, make_brand
):
    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "audit_entity", boom)
    org = make_org()
    bid = make_brand(org)
    _domain(owner, org, bid)
    job_id = _job(owner, org, bid, "audit_crawl", "queued")
    _, generator, embedder = _spender()
    fetch = _fake_fetch()
    assert worker.process_job(FakeAdapter(), generator, embedder, fetch=fetch)
    assert _load_job(owner, job_id).status == "done"
    with owner() as s:
        (row,) = s.scalars(select(m.SiteAudit)).all()
    assert row.fetches == 12
    assert "home_unreachable" in {c["code"] for c in row.checks}
    assert "title_brand_missing" not in {c["code"] for c in row.checks}


def test_the_entity_audit_gets_the_brand_record(
    monkeypatch, owner, make_org, make_brand
):
    seen = []

    def spy(host, name, aliases, hosts, fetch, *, pause):
        seen.append((host, name, list(aliases), sorted(hosts)))
        return worker.Audit([], 0)

    monkeypatch.setattr(worker, "audit_entity", spy)
    org = make_org()
    bid = make_brand(org, "Nike", aliases=("Nike Inc",))
    _domain(owner, org, bid, "nike.com")
    _domain(owner, org, bid, "nike.in")
    _job(owner, org, bid, "audit_crawl", "queued")
    _, generator, embedder = _spender()
    worker.process_job(FakeAdapter(), generator, embedder, fetch=_fake_fetch())
    assert sorted(seen) == [
        ("nike.com", "Nike", ["Nike Inc"], ["nike.com", "nike.in"]),
        ("nike.in", "Nike", ["Nike Inc"], ["nike.com", "nike.in"]),
    ]
```

In `tests/integration/test_api_audits.py`, add:

```python
def test_an_unknown_stored_severity_reads_as_low(
    client, owner, make_org, make_brand
):
    """The rule skips it; the page must still render, not 500."""
    org = make_org()
    bid = make_brand(org)
    _domain(owner, org, bid, "nike.com")
    with owner() as s, s.begin():
        s.add(
            m.SiteAudit(
                org_id=org.id,
                brand_id=bid,
                domain="nike.com",
                checks=[
                    {
                        "code": "llms_missing",
                        "ok": False,
                        "severity": "weird",
                        "observed": "HTTP 404",
                        "expected": "x",
                        "url": "https://nike.com/llms.txt",
                    }
                ],
            )
        )
    r = client.get(f"/v1/brands/{bid}/audits/crawl", headers=org.headers)
    assert r.status_code == 200, r.text
    assert r.json()[0]["checks"][0]["severity"] == "low"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/integration/test_crawl_audit.py tests/integration/test_api_audits.py -q`
Expected: FAIL: fetches 12 ≠ 14, sleeps 11 ≠ 13, `worker` has no attribute `audit_entity`, and the severity test returns 500 (or raises a validation error).

- [ ] **Step 3: Wire the entity audit into `run_crawl_audit`**

Imports in `worker.py`:
```python
from bsi_core.crawl import PAUSE_SECONDS, Audit, Fetch, audit_domain, http_fetch
from bsi_core.entity import audit_entity
```

Replace the first `with tenant_session(org_id) as s:` block and the `for host in hosts:` loop with:

```python
    with tenant_session(org_id) as s:
        brand = s.get_one(m.Brand, brand_id)
        name, aliases = brand.name, list(brand.aliases)
        hosts = list(
            s.scalars(
                select(m.Domain.host)
                .where(m.Domain.brand_id == brand_id)
                .order_by(m.Domain.created_at, m.Domain.host)
            )
        )
    audits = []
    for host in hosts:
        # One host crashing must not lose the others' rows. A crawl crash
        # stores nothing, so the domain stays due.
        try:
            crawl = audit_domain(host, fetch, pause=PAUSE_SECONDS)
        except Exception:
            log.exception("brand %s: audit of %s failed", brand_id, host)
            continue
        # The entity checks ride along; their crash must not cost the
        # crawl checks.
        try:
            ent = audit_entity(
                host, name, aliases, hosts, fetch, pause=PAUSE_SECONDS
            )
        except Exception:
            log.exception("brand %s: entity audit of %s failed", brand_id, host)
            ent = Audit([], 0)
        audits.append(
            (
                host,
                Audit(crawl.checks + ent.checks, crawl.fetches + ent.fetches),
            )
        )
```

Update the docstring's first line to "Audit every declared domain of the brand (crawl and entity checks); returns how many." The write block below is unchanged.

- [ ] **Step 4: Tolerate unknown severities in `CheckOut`**

In `schemas.py`, import `field_validator` from pydantic and change `CheckOut`:

```python
class CheckOut(BaseModel):
    code: str
    ok: bool
    severity: Literal["high", "medium", "low"]
    observed: str
    expected: str
    url: str

    @field_validator("severity", mode="before")
    @classmethod
    def _known_severity(cls, v: object) -> object:
        # A stored severity outside the set (edited data, a future rename)
        # reads as low: the rule already skips it, the page must not 500.
        return v if v in ("high", "medium", "low") else "low"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/integration/test_crawl_audit.py tests/integration/test_api_audits.py tests/integration/test_isolation.py -q`
Expected: all pass, including `test_no_transaction_is_open_while_fetching` (it now also sees the entity fetches).

- [ ] **Step 6: Run the gate, then commit**

The web gate's `gen:check` should report no OpenAPI change (a before-validator does not alter the schema). If it does differ: `cd apps/web && npm run gen && git add src/lib/schema.d.ts && npm run gate`.

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/workers/bsi_workers/worker.py apps/api/bsi_api/schemas.py tests/integration/test_crawl_audit.py tests/integration/test_api_audits.py && git commit -m "feat(worker): run the entity audit with each crawl audit

CheckOut also reads an unknown stored severity as low instead of 500.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Live check, findings and docs index

**Files:**
- Create: scratchpad script (not committed), `docs/findings-slice8.md`
- Modify: `docs/README.md` (add a Slice 8 section after Slice 7, ~L79)

**Interfaces:**
- Consumes: `entity.audit_entity`, `crawl.http_fetch`, `crawl.audit_domain`, `recommend.entity_copy`.
- Produces: documentation only.

- [ ] **Step 1: Run `audit_entity` against real domains (no DB, no spend)**

Write this to the session scratchpad as `live_entity.py` and run it with `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run python <scratchpad>/live_entity.py`:

```python
from bsi_core.crawl import http_fetch
from bsi_core.entity import audit_entity

CASES = [
    # (host, brand name, aliases): pick brands likely to have a Wikidata
    # item with P856 on this host; swap for another if the home page
    # refuses a browser user agent.
    ("mozilla.org", "Mozilla", ["Mozilla Foundation", "Mozilla Corporation"]),
    ("python.org", "Python Software Foundation", ["Python"]),
    # A brand that should not be on Wikidata.
    ("example.com", "Acme Rocket Widgets Pvt", []),
]
for host, name, aliases in CASES:
    a = audit_entity(host, name, aliases, [host], http_fetch, pause=0.5)
    print(f"\n== {host} ({name}) fetches={a.fetches}")
    for c in a.checks:
        print(f"  {'ok ' if c.ok else 'FAIL'} {c.severity:6} {c.code:24} {c.observed}")
```

Expected: every case completes; at least one domain-verified QID appears (`wikidata_missing ok … Qnnn: …`); `example.com` shows `wikidata_missing FAIL` with candidates or "no search results". If a brand you picked has no P856 on that host, try another well-known brand whose Wikidata item lists its site (e.g. `wikimedia.org`/"Wikimedia Foundation", `apache.org`/"Apache Software Foundation") until one matches; record every attempt. Confirm afterwards that dev tables are still empty:

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && docker compose exec -T db psql -U bsi_owner -d bsi -tAc "select (select count(*) from recommendation),(select count(*) from task),(select count(*) from site_audit)"
```
Expected: `0|0|0`.

- [ ] **Step 2: Write `docs/findings-slice8.md`**

Follow the shape of `docs/findings-slice7.md`: a header paragraph (date 2026-09-23, branch `slice8-entity-consistency`, sources: a direct `audit_entity()` call against the real domains above, plain HTTP, no model, no spend, nothing written to the dev database), then:

1. **What was measured, and how** — the script above.
2. **Results** — per domain, a table of every check with ok/fail, severity and observed value, copied from the script output (no invented values).
3. **What the matching did** — which QID matched and why (its P856), which candidates were rejected.
4. **Where `fix_entity` lands** — priorities 0.7 / 0.35 / 0.14 vs `fix_crawlability` 0.8 / 0.4 / 0.16, so a high entity finding sits just under a high crawl finding and above a medium one.
5. **Deferred, by decision** — About page not fetched; description not compared; logo URL not fetched; Wikipedia text unread; Product/Article/BreadcrumbList schema unchecked; Wikidata search repeated per declared domain, so a two-domain brand gets two `wikidata_missing` recs; only five social properties, `x.com` the only host alias; a brand whose item lacks P856 reads as `wikidata_missing` (safe direction); `/aboutique`-style paths count as an About link (prefix match); cadence is weekly, the PRD asks monthly.
6. **Spend** — unchanged ($9.2762 of $15).

- [ ] **Step 3: Add the Slice 8 section to `docs/README.md`**

After the Slice 7 table, insert:

```markdown
## Slice 8: entity consistency audit

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-23-slice8-entity-consistency-design.md](superpowers/specs/2026-09-23-slice8-entity-consistency-design.md) | Design spec: schema.org Organization, homepage title and About-link checks, a domain-verified Wikidata match with a social-profile comparison, run inside the crawl audit, and a `fix_entity` recommendation type. |
| [superpowers/plans/2026-09-23-slice8-entity-consistency.md](superpowers/plans/2026-09-23-slice8-entity-consistency.md) | Implementation plan, Tasks 1–5. |
| [findings-slice8.md](findings-slice8.md) | Results: a live `audit_entity()` run against real domains with every check, which Wikidata candidates matched and why, where `fix_entity` ranks against `fix_crawlability`, and what is deferred. |
```

- [ ] **Step 4: Run the gate, then commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add docs/findings-slice8.md docs/README.md && git commit -m "docs: slice 8 findings and index

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After the tasks

Whole-branch review, one fix wave, scoped re-review (per `subagent-driven-development`), then `finishing-a-development-branch`: push, open the PR with `GH_TOKEN=$(gh auth token -u aiagencyindia-lab) gh pr create …` (body ends with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`), `gh pr checks N --watch`, read the run log (`gh run view <id> --log | grep -E "passed|Compiled|gen:check"`). Merge only when the user says so.
