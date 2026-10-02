# Slice 37 Brand SERP Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An on-demand Brand SERP audit: for `{brand}` and `{brand} reviews` in each of the brand's locales, fetch Google's first page from DataForSEO, classify each result by rule, store one row per query, and show the rows with an ownership share on a new page.

**Architecture:** A pure classifier (`bsi_core/serp.py`) and a provider adapter that never raises (`bsi_core/providers/dataforseo.py`, one POST per query through `crawl.http_fetch`). A new worker job kind `audit_serp` reads the brand in a short session, calls the adapter with no session open, and writes `serp_audit` rows (one per query, results in JSONB). Two routes under `/brands/{id}/audits/serp` and a Server Component page modelled on the Site page.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, pydantic 2, FastAPI, pytest; Next.js 15 App Router, TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-10-02-slice37-serp-audit-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice37-serp-audit`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB (`bsi`), the network or the worker loop. Never call a model or the SERP provider: every test uses a fake fetch. Never run `alembic` by hand: the test session applies migrations to `bsi_test` itself.
- **Credentials:** never write a real login, password, key or token anywhere. Tests use the literal fakes `"me"` and `"pw"`.
- **Shared test DB:** run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own before every pytest run; if it prints a running pytest, stop and wait for it to finish before running yours. Never run two suites at once. Run the full backend suite only once per task, in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal: read the file and repeat the edit.)
- **Writing files:** never use a shell heredoc or zsh `echo` to write files; use the Edit or Write tools. Never run `rm`.
- **Lint and types:** ruff line length is 80, target py313, rules E F I B UP RUF. `mypy --strict` covers `packages/core/bsi_core` only. RUF001 rejects a literal curly apostrophe.
- **Banned words:** copy (code, comments, docstrings, labels, test names, fixture titles) never contains the words listed in `FORBIDDEN` in tests/unit/test_recommend_copy.py.
- **Banned-word grep:** `cd /Users/vineet/Downloads/ADK/bsi-platform && git diff --cached -U0 | grep '^+' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'`, run after staging. Expected: no match (grep exits 1 and prints nothing).
- **Backend gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform && { uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task<N>.txt 2>&1; echo "gate exit $?"` (the echo prints to the terminal). If `ruff format .` changed a file, re-stage it, re-run the banned-word grep, and say so in the report.
- **Web gate** (Tasks 5 and 6): `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate > <workspace>/web-task<N>.txt 2>&1; echo "web gate exit $?"`.
- **Frontend rules:** Server Components and server actions only; no new Route Handler; never call `redirect()` inside `try`/`catch`.
- **Commit trailer:** exactly `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` (spec R1: the controller's latest session reminder names it). Use this line even if your own session reminder names another model.
- **Baseline counts** (collected 2026-10-02 on main `5a127bf`): backend `1574 passed, 2 deselected` (plus the 2 known third-party warnings); web 43 vitest. Expected backend totals after each task: Task 1 `1598`, Task 2 `1622`, Task 3 `1623`, Task 4 `1633`, Task 5 `1640`, Task 6 `1640`; web after Task 6: 47.

## File map

| File | Responsibility | Task |
|---|---|---|
| `packages/core/bsi_core/config.py`, `.env.example` | the two DataForSEO settings | 1 |
| `packages/core/bsi_core/serp.py` (new) | `classify`, `ownership`, the host lists | 1 |
| `tests/unit/test_serp.py` (new) | the classification table, ownership | 1 |
| `packages/core/bsi_core/providers/dataforseo.py` (new) | `serp()`, `SerpItem`, `SerpPage`, `SerpFetch` | 2 |
| `tests/unit/test_dataforseo.py` (new) | the adapter over a fake fetch | 2 |
| `migrations/versions/0023_serp_audit.py` (new), `packages/core/bsi_core/models.py` | the `serp_audit` table and `SerpAudit` | 3 |
| `tests/integration/test_rls.py`, `tests/integration/test_serp_audit.py` (new) | tenancy lists; the kind check | 3 |
| `apps/workers/bsi_workers/worker.py` | `run_serp_audit`, `SerpFailed`, the job kind | 4 |
| `tests/integration/test_serp_audit.py` | the job through `process_job` | 4 |
| `apps/api/bsi_api/schemas.py`, `apps/api/bsi_api/routers/audits.py` | the two routes and their schemas | 5 |
| `tests/integration/test_api_serp.py` (new), `tests/integration/test_isolation.py` | route tests, isolation cases | 5 |
| `apps/web/openapi.json`, `apps/web/src/lib/schema.d.ts` | regenerated | 5 |
| `apps/web/src/lib/format.ts`, `format.test.ts`, `types.ts` | labels and helpers | 6 |
| `apps/web/src/app/(app)/b/[id]/serp/page.tsx`, `actions.ts` (new), `layout.tsx` | the page, the action, the nav link | 6 |

---

### Task 1: settings and the classifier

**Files:**
- Modify: `packages/core/bsi_core/config.py`
- Modify: `.env.example`
- Create: `packages/core/bsi_core/serp.py`
- Test: `tests/unit/test_serp.py` (new)

**Interfaces:**
- Consumes: `normalize_domain(value: str) -> str` and `is_owned(domain: str, hosts: Iterable[str]) -> bool` from `bsi_core.matching`.
- Produces: `Settings.dataforseo_login: str`, `Settings.dataforseo_password: SecretStr`; `bsi_core.serp.classify(item_type: str, host: str, own: Iterable[str], rivals: Iterable[str]) -> str | None`; `bsi_core.serp.ownership(results: Iterable[Mapping[str, Any]]) -> tuple[int, int]`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_serp.py`:

```python
import pytest
from bsi_core.serp import classify, ownership

OWN = ["walkaroo.in"]
RIVALS = ["bata.com", "www.campusshoes.com"]
CASES = [
    ("knowledge_graph", "", "knowledge_panel"),
    ("ai_overview", "", "ai_overview"),
    ("top_stories", "", "news"),
    ("video", "", "video"),
    ("images", "", "image"),
    ("organic", "https://www.youtube.com/watch?v=1", "video"),
    ("organic", "https://walkaroo.in/", "official"),
    ("organic", "https://shop.walkaroo.in/kids", "official"),
    ("organic", "https://www.bata.com/in/", "competitor"),
    ("organic", "https://campusshoes.com/x", "competitor"),
    ("organic", "https://x.com/walkaroo", "social"),
    ("organic", "https://in.linkedin.com/company/w", "social"),
    ("organic", "https://www.mouthshut.com/w-reviews", "review"),
    ("organic", "https://www.glassdoor.co.in/Reviews/w", "review"),
    ("organic", "https://www.amazon.in/walkaroo", "other"),
    ("organic", "https://notwalkaroo.in/", "other"),
    ("featured_snippet", "walkaroo.in", "official"),
    ("featured_snippet", "www.amazon.in", "other"),
    ("organic", "walkaroo.in", "official"),
    ("organic", "", "other"),
    ("people_also_ask", "", None),
    ("paid", "https://walkaroo.in/", None),
]


@pytest.mark.parametrize(("item_type", "host", "expected"), CASES)
def test_classify(item_type, host, expected):
    assert classify(item_type, host, OWN, RIVALS) == expected


def test_the_rule_order_is_video_then_own_then_rival():
    # A rival's YouTube channel is a video result.
    assert classify("organic", "https://youtube.com/@bata", OWN, RIVALS) == (
        "video"
    )
    # A host listed as both the brand's own and a rival's is the brand's.
    assert classify("organic", "walkaroo.in", OWN, ["walkaroo.in"]) == (
        "official"
    )
    # A social host in the rival list takes every result on that host.
    assert classify("organic", "x.com", OWN, ["x.com"]) == "competitor"


def test_ownership_counts_official_organic_results():
    rows = [
        {"item_type": "organic", "result_type": "official"},
        {"item_type": "organic", "result_type": "other"},
        {"item_type": "knowledge_graph", "result_type": "knowledge_panel"},
        {"item_type": "featured_snippet", "result_type": "official"},
    ]
    assert ownership(rows) == (1, 2)
    assert ownership([]) == (0, 0)
```

- [ ] **Step 2: Run the test to verify it fails**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first (if it prints a running pytest, wait), then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_serp.py 2>&1 | tail -3`
Expected: an error at collection, `ModuleNotFoundError: No module named 'bsi_core.serp'`.

- [ ] **Step 3: Write the classifier**

Create `packages/core/bsi_core/serp.py`:

```python
"""Brand SERP audit: classify a first-page item and count ownership."""

from collections.abc import Iterable, Mapping
from typing import Any

from .matching import is_owned, normalize_domain

# Provider item type -> our type.
ITEM_TYPES = {
    "knowledge_graph": "knowledge_panel",
    "ai_overview": "ai_overview",
    "top_stories": "news",
    "video": "video",
    "images": "image",
}
# Decided by host, in classify()'s order.
HOSTED = ("organic", "featured_snippet")
VIDEO_HOSTS = ("youtube.com",)
# ponytail: x.com is listed beside twitter.com; entity._social folds one
# into the other for profile URLs, a host test needs both.
SOCIAL_HOSTS = (
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
)
REVIEW_HOSTS = (
    "trustpilot.com",
    "mouthshut.com",
    "glassdoor.com",
    "glassdoor.co.in",
    "ambitionbox.com",
    "consumercomplaints.in",
    "sitejabber.com",
    "g2.com",
)


def classify(
    item_type: str, host: str, own: Iterable[str], rivals: Iterable[str]
) -> str | None:
    """Our result type for one provider item; None = not stored. `host`
    is the item's domain, or its URL when the provider gives no domain."""
    if item_type in ITEM_TYPES:
        return ITEM_TYPES[item_type]
    if item_type not in HOSTED:
        return None
    host = normalize_domain(host)
    if is_owned(host, VIDEO_HOSTS):
        return "video"
    if is_owned(host, [normalize_domain(h) for h in own]):
        return "official"
    if is_owned(host, [normalize_domain(h) for h in rivals]):
        return "competitor"
    if is_owned(host, SOCIAL_HOSTS):
        return "social"
    if is_owned(host, REVIEW_HOSTS):
        return "review"
    return "other"


def ownership(results: Iterable[Mapping[str, Any]]) -> tuple[int, int]:
    """(official organic results, all organic results)."""
    organic = [r for r in results if r.get("item_type") == "organic"]
    owned = sum(r.get("result_type") == "official" for r in organic)
    return owned, len(organic)
```

- [ ] **Step 4: Add the settings**

In `packages/core/bsi_core/config.py`, replace

```python
from pydantic import AwareDatetime
```

with

```python
from pydantic import AwareDatetime, SecretStr
```

and replace

```python
    impact_window_days: int = 14
```

with

```python
    impact_window_days: int = 14
    # Slice 37: the SERP provider's API login and password (the dashboard's
    # API Access tab). Empty = the Brand SERP audit is not configured.
    dataforseo_login: str = ""
    dataforseo_password: SecretStr = SecretStr("")
```

In `.env.example`, append these two lines at the end of the file:

```
DATAFORSEO_LOGIN=
DATAFORSEO_PASSWORD=
```

- [ ] **Step 5: Run the test to verify it passes**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_serp.py 2>&1 | tail -1`
Expected: `24 passed`.

- [ ] **Step 6: Banned-word grep, then the backend gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/serp.py packages/core/bsi_core/config.py .env.example tests/unit/test_serp.py`. Run the banned-word grep (expected: no match). Run `pgrep -fl pytest` on its own, then the Backend gate with `<N>` = 1. Expected: `gate exit 0`; `gate-task1.txt` shows `1598 passed, 2 deselected` and the metrics coverage line at 100%.

- [ ] **Step 7: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/serp.py packages/core/bsi_core/config.py .env.example tests/unit/test_serp.py && git commit -m "feat(core): SERP result classification and the provider settings

classify() types one first-page item by the provider's item type or by
its host (video, own, active rival, social, review site, other);
ownership() counts official organic results. Settings gain the
DataForSEO login and password, empty by default.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: the DataForSEO adapter

**Files:**
- Create: `packages/core/bsi_core/providers/dataforseo.py`
- Test: `tests/unit/test_dataforseo.py` (new)

**Interfaces:**
- Consumes: `bsi_core.crawl.http_fetch` and `bsi_core.crawl.Response(status: int, body: str = "", error: str | None = None, truncated: bool = False)` with its `.ok` property (2xx).
- Produces, all in `bsi_core.providers.dataforseo`:
  - `URL`, `SERP_UA = "bsi-platform-serp/1.0"`, `SERP_CAP_BYTES = 4 * 1024 * 1024`, `LOCATIONS = {"IN": "India"}`;
  - `SerpFetch` (Protocol: `(url, user_agent, *, method, body, content_type, cap, headers=None) -> Response`);
  - `SerpItem(position: int, item_type: str, url: str, domain: str, title: str, sitelinks: bool)`;
  - `SerpPage(items: list[SerpItem], cost_micros: int = 0, error: str | None = None)`;
  - `serp(query: str, country: str, language: str, *, login: str, password: str, fetch: SerpFetch = http_fetch) -> SerpPage`, which never raises.
- Produces for Task 4's tests, in `tests/unit/test_dataforseo.py`: `ITEMS`, `body(items=None, cost=0.004, status=20000, task_status=20000) -> str`, and `Fetch(*responses)` (records `calls` as `(url, user_agent, kwargs)`; repeats its last response).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_dataforseo.py`:

```python
import base64
import json

import pytest
from bsi_core.crawl import Response
from bsi_core.providers.dataforseo import (
    SERP_CAP_BYTES,
    SERP_UA,
    URL,
    SerpItem,
    SerpPage,
    serp,
)

ITEMS = [
    {"type": "knowledge_graph", "rank_absolute": 1, "title": "Walkaroo"},
    {
        "type": "organic",
        "rank_absolute": 2,
        "domain": "walkaroo.in",
        "url": "https://walkaroo.in/",
        "title": "Walkaroo footwear",
        "links": [{"type": "link_element", "url": "https://walkaroo.in/men"}],
    },
    {
        "type": "organic",
        "rank_absolute": 3,
        "domain": "www.amazon.in",
        "url": "https://www.amazon.in/walkaroo",
        "title": "Walkaroo on Amazon",
        "links": None,
    },
    {"type": "people_also_ask", "rank_absolute": 4},
]


def body(items=None, cost=0.004, status=20000, task_status=20000) -> str:
    """A response in the documented shape: one task, one result."""
    task = {
        "status_code": task_status,
        "cost": cost,
        "result": [{"items": ITEMS if items is None else items}],
    }
    return json.dumps({"status_code": status, "cost": cost, "tasks": [task]})


class Fetch:
    """A fake http_fetch: records each call, repeats its last response."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, user_agent, **kw):
        self.calls.append((url, user_agent, kw))
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


def _serp(fetch, country="IN", login="me", password="pw"):
    return serp(
        "walkaroo", country, "en", login=login, password=password, fetch=fetch
    )


def test_a_page_is_parsed_into_items():
    page = _serp(Fetch(Response(200, body())))
    assert (page.error, page.cost_micros) == (None, 4_000)
    assert page.items == [
        SerpItem(1, "knowledge_graph", "", "", "Walkaroo", False),
        SerpItem(
            2,
            "organic",
            "https://walkaroo.in/",
            "walkaroo.in",
            "Walkaroo footwear",
            True,
        ),
        SerpItem(
            3,
            "organic",
            "https://www.amazon.in/walkaroo",
            "www.amazon.in",
            "Walkaroo on Amazon",
            False,
        ),
        SerpItem(4, "people_also_ask", "", "", "", False),
    ]


def test_the_request_is_one_live_desktop_task_with_basic_auth():
    fetch = Fetch(Response(200, body()))
    _serp(fetch, country="in")
    [(url, user_agent, kw)] = fetch.calls
    assert (url, user_agent) == (URL, SERP_UA)
    assert kw["method"] == "POST"
    assert kw["content_type"] == "application/json"
    assert kw["cap"] == SERP_CAP_BYTES
    assert json.loads(kw["body"]) == [
        {
            "keyword": "walkaroo",
            "location_name": "India",
            "language_code": "en",
            "device": "desktop",
            "depth": 10,
            "load_async_ai_overview": True,
        }
    ]
    token = base64.b64encode(b"me:pw").decode()
    assert kw["headers"] == {"Authorization": f"Basic {token}"}


def test_no_search_results_is_a_success_with_no_items():
    task = {"status_code": 40102, "cost": 0.002, "result": None}
    raw = json.dumps({"status_code": 20000, "cost": 0.002, "tasks": [task]})
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 2_000, None)


ERROR_CODES = [
    (40100, "auth"),
    (40200, "funds"),
    (40210, "funds"),
    (40202, "rate"),
    (50000, "provider_50000"),
]


@pytest.mark.parametrize(("status", "code"), ERROR_CODES)
def test_a_top_level_error_status_is_its_code(status, code):
    raw = json.dumps({"status_code": status, "cost": 0, "tasks": None})
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, code)


@pytest.mark.parametrize(("status", "code"), ERROR_CODES)
def test_a_task_level_error_is_its_code_and_keeps_the_cost(status, code):
    page = _serp(Fetch(Response(200, body(task_status=status))))
    assert page == SerpPage([], 4_000, code)


@pytest.mark.parametrize(
    "response", [Response(0, error="timeout"), Response(500, "oops")]
)
def test_an_http_failure_is_http(response):
    assert _serp(Fetch(response)) == SerpPage([], 0, "http")


def test_a_cut_body_is_truncated():
    cut = Response(200, body()[:50], truncated=True)
    assert _serp(Fetch(cut)) == SerpPage([], 0, "truncated")


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        '{"tasks": []}',
        '{"status_code": 20000}',
        '{"status_code": "x"}',
    ],
)
def test_an_unreadable_body_is_json(raw):
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "json")


@pytest.mark.parametrize(("login", "password"), [("", "pw"), ("me", "")])
def test_missing_credentials_make_no_call(login, password):
    fetch = Fetch(Response(200, body()))
    # The credential check comes before the country check.
    page = _serp(fetch, country="US", login=login, password=password)
    assert page == SerpPage([], 0, "serp_not_configured")
    assert fetch.calls == []


def test_an_unknown_country_makes_no_call():
    fetch = Fetch(Response(200, body()))
    assert _serp(fetch, country="US") == SerpPage([], 0, "location")
    assert fetch.calls == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run `pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_dataforseo.py 2>&1 | tail -3`
Expected: an error at collection, `ModuleNotFoundError: No module named 'bsi_core.providers.dataforseo'`.

- [ ] **Step 3: Write the adapter**

Create `packages/core/bsi_core/providers/dataforseo.py`:

```python
"""DataForSEO: one live Google first page per call (slice 37, PRD F09).

serp() never raises: a failure is a SerpPage with a short error code.
Only a POST is made, so the Basic header never follows a redirect."""

import base64
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..crawl import Response, http_fetch

URL = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
SERP_UA = "bsi-platform-serp/1.0"
SERP_CAP_BYTES = 4 * 1024 * 1024
# ponytail: a static table of the provider's location names, one line
# per country as locales arrive; an unknown country is error "location".
LOCATIONS = {"IN": "India"}
OK, NO_RESULTS = 20000, 40102
ERRORS = {40100: "auth", 40200: "funds", 40210: "funds", 40202: "rate"}


class SerpFetch(Protocol):
    def __call__(
        self,
        url: str,
        user_agent: str,
        *,
        method: str,
        body: bytes,
        content_type: str,
        cap: int,
        headers: Mapping[str, str] | None = None,
    ) -> Response: ...


@dataclass
class SerpItem:
    position: int  # rank_absolute; 0 when the provider gives none
    item_type: str  # the provider's `type`
    url: str
    domain: str
    title: str
    sitelinks: bool  # an organic item with a non-empty `links`


@dataclass
class SerpPage:
    items: list[SerpItem] = field(default_factory=list)
    cost_micros: int = 0
    error: str | None = None


def _code(status: object) -> str | None:
    """None for a success status, else the short error code."""
    if status in (OK, NO_RESULTS):
        return None
    if isinstance(status, int) and status in ERRORS:
        return ERRORS[status]
    return f"provider_{status}"


def _micros(cost: object) -> int:
    return round(cost * 1_000_000) if isinstance(cost, int | float) else 0


def _item(raw: Mapping[str, Any]) -> SerpItem:
    rank = raw.get("rank_absolute")
    kind = str(raw.get("type") or "")
    return SerpItem(
        position=rank if isinstance(rank, int) else 0,
        item_type=kind,
        url=str(raw.get("url") or ""),
        domain=str(raw.get("domain") or ""),
        title=str(raw.get("title") or ""),
        sitelinks=kind == "organic" and bool(raw.get("links")),
    )


def _parse(doc: Any) -> SerpPage:
    """The page in a decoded response; raises on an undocumented shape."""
    if not isinstance(doc, dict):
        raise ValueError("not an object")
    top = doc["status_code"]
    if not isinstance(top, int):
        raise ValueError("status_code is not a number")
    tasks = doc.get("tasks") or []
    if not tasks:
        error = _code(top)
        if error is None:
            raise ValueError("no task")
        return SerpPage(cost_micros=_micros(doc.get("cost")), error=error)
    task = tasks[0]
    cost = _micros(task.get("cost"))
    # The top-level status first, then the task's (spec, The adapter).
    error = _code(top) or _code(task["status_code"])
    if error is not None:
        return SerpPage(cost_micros=cost, error=error)
    items = [
        _item(raw)
        for result in task.get("result") or []
        for raw in result.get("items") or []
    ]
    return SerpPage(items, cost)


def serp(
    query: str,
    country: str,
    language: str,
    *,
    login: str,
    password: str,
    fetch: SerpFetch = http_fetch,
) -> SerpPage:
    """Google's first page for `query` in one locale: desktop, live mode,
    with an asynchronously loaded AI Overview included."""
    if not login or not password:
        return SerpPage(error="serp_not_configured")
    location = LOCATIONS.get(country.upper())
    if location is None:
        return SerpPage(error="location")
    task = {
        "keyword": query,
        "location_name": location,
        "language_code": language,
        "device": "desktop",
        "depth": 10,
        "load_async_ai_overview": True,
    }
    token = base64.b64encode(f"{login}:{password}".encode()).decode()
    resp = fetch(
        URL,
        SERP_UA,
        method="POST",
        body=json.dumps([task]).encode(),
        content_type="application/json",
        cap=SERP_CAP_BYTES,
        headers={"Authorization": f"Basic {token}"},
    )
    if not resp.ok:
        return SerpPage(error="http")
    if resp.truncated:
        return SerpPage(error="truncated")
    try:
        return _parse(json.loads(resp.body))
    except (ValueError, TypeError, KeyError, AttributeError, IndexError):
        return SerpPage(error="json")
```

- [ ] **Step 4: Run the test to verify it passes**

Run `pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_dataforseo.py 2>&1 | tail -1`
Expected: `24 passed`.

- [ ] **Step 5: Banned-word grep, then the backend gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/providers/dataforseo.py tests/unit/test_dataforseo.py`. Run the banned-word grep (expected: no match). Run `pgrep -fl pytest` on its own, then the Backend gate with `<N>` = 2. Expected: `gate exit 0`; `gate-task2.txt` shows `1622 passed, 2 deselected`, mypy `Success`, and the metrics coverage line at 100%.

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/providers/dataforseo.py tests/unit/test_dataforseo.py && git commit -m "feat(core): a DataForSEO adapter for one live Google first page

serp() makes one POST through http_fetch (desktop, depth 10, AI
Overview loading on) and never raises: a failure is a SerpPage with a
short code (serp_not_configured, location, http, truncated, json, auth,
funds, rate, provider_<code>). The cost comes from the response.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: the `serp_audit` table

**Files:**
- Create: `migrations/versions/0023_serp_audit.py`
- Modify: `packages/core/bsi_core/models.py`
- Modify: `tests/integration/test_rls.py`
- Test: `tests/integration/test_serp_audit.py` (new)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `m.SERP_KINDS = ("brand", "reviews")`; `m.SerpAudit(org_id, brand_id, job_id=None, kind, query, country, language, device="desktop", results=[...], fetched_at, cost_micros=0, error=None)` on table `serp_audit`.

- [ ] **Step 1: Write the failing tests**

In `tests/integration/test_rls.py`, replace

```python
    "keyword_search",
]
```

with

```python
    "keyword_search",
    "serp_audit",
]
```

and replace

```python
        s.add(
            m.KeywordSearch(
                org_id=b.id, brand_id=bid, keyword="b sandals", query="b"
            )
        )
    return b
```

with

```python
        s.add(
            m.KeywordSearch(
                org_id=b.id, brand_id=bid, keyword="b sandals", query="b"
            )
        )
        s.add(
            m.SerpAudit(
                org_id=b.id,
                brand_id=bid,
                kind="brand",
                query="b",
                country="IN",
                language="en",
                fetched_at=datetime.now(UTC),
            )
        )
    return b
```

Create `tests/integration/test_serp_audit.py`:

```python
"""The Brand SERP audit: the table, and what the worker stores."""

from datetime import UTC, datetime

import pytest
from bsi_core import models as m
from sqlalchemy.exc import IntegrityError


def test_the_kind_is_checked(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    with pytest.raises(IntegrityError), owner() as s, s.begin():
        s.add(
            m.SerpAudit(
                org_id=org.id,
                brand_id=bid,
                kind="other",
                query="q",
                country="IN",
                language="en",
                fetched_at=datetime.now(UTC),
            )
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run `pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_rls.py tests/integration/test_serp_audit.py 2>&1 | tail -4`
Expected: failures and errors with `AttributeError: module 'bsi_core.models' has no attribute 'SerpAudit'`, and `test_tenant_table_list_matches_the_schema` failing because `serp_audit` is not a table yet.

- [ ] **Step 3: Write the migration**

Create `migrations/versions/0023_serp_audit.py`:

```python
"""serp_audit table (slice 37, PRD F09)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"


def _protect(table: str) -> None:
    op.create_index(f"ix_{table}_org_id", table, ["org_id"])
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant ON {table} "
        f"USING (org_id = {SETTING}) WITH CHECK (org_id = {SETTING})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO bsi_app")


def upgrade() -> None:
    op.create_table(
        "serp_audit",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("org_id", sa.Uuid(), nullable=False),
        sa.Column("brand_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid()),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("country", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column(
            "device", sa.String(), server_default="desktop", nullable=False
        ),
        sa.Column(
            "results",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "cost_micros", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("error", sa.String()),
        sa.CheckConstraint(
            "kind IN ('brand', 'reviews')", name="ck_serp_audit_kind"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    _protect("serp_audit")


def downgrade() -> None:
    op.drop_table("serp_audit")
```

- [ ] **Step 4: Write the model**

In `packages/core/bsi_core/models.py`, replace

```python
RULE_CHECKS = ("pass", "adjusted", "review")
```

with

```python
RULE_CHECKS = ("pass", "adjusted", "review")
SERP_KINDS = ("brand", "reviews")
```

Then, directly after the `KeywordSearch` class (it ends with the `__table_args__` holding `uq_keyword_search_brand_keyword`) and before the next class, add:

```python
class SerpAudit(Tenant, Base):
    """Google's first page for one brand query in one locale (slice 37,
    PRD F09); the latest row per (kind, country, language) is what the
    Brand SERP tab reads. A failed query is stored too (error set)."""

    __tablename__ = "serp_audit"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job.id"))
    kind: Mapped[str]
    query: Mapped[str]
    country: Mapped[str]
    language: Mapped[str]
    device: Mapped[str] = mapped_column(server_default="desktop")
    results: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default="[]"
    )
    fetched_at: Mapped[datetime] = mapped_column(TSZ)
    cost_micros: Mapped[int] = mapped_column(server_default="0")
    error: Mapped[str | None]
    __table_args__ = (
        CheckConstraint(_in("kind", SERP_KINDS), name="ck_serp_audit_kind"),
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run `pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_rls.py tests/integration/test_serp_audit.py 2>&1 | tail -1`
Expected: `9 passed` (8 in test_rls.py, 1 new), with the 2 known third-party warnings if the files use the client. The test session applies migration 0023 to `bsi_test` itself.

- [ ] **Step 6: Banned-word grep, then the backend gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add migrations/versions/0023_serp_audit.py packages/core/bsi_core/models.py tests/integration/test_rls.py tests/integration/test_serp_audit.py`. Run the banned-word grep (expected: no match). Run `pgrep -fl pytest` on its own, then the Backend gate with `<N>` = 3. Expected: `gate exit 0`; `gate-task3.txt` shows `1623 passed, 2 deselected` and the metrics coverage line at 100%.

- [ ] **Step 7: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add migrations/versions/0023_serp_audit.py packages/core/bsi_core/models.py tests/integration/test_rls.py tests/integration/test_serp_audit.py && git commit -m "feat(db): the serp_audit table (migration 0023)

One row per query, locale and run, with the page's results in JSONB,
the cost and an error code; tenant RLS as the other tenant tables.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: the `audit_serp` job

**Files:**
- Modify: `apps/workers/bsi_workers/worker.py`
- Test: `tests/integration/test_serp_audit.py` (extend)

**Interfaces:**
- Consumes: `classify` (Task 1); `serp`, `SerpFetch`, `SerpItem` (Task 2); `m.SerpAudit` (Task 3); `Settings` (Task 1); from Task 2's test module `ITEMS`, `body`, `Fetch`.
- Produces, in `bsi_workers.worker`: `SERP_JOB_MICROS = 40_000`, `MAX_SERP_LOCALES = 5`, `JOB_ESTIMATES["audit_serp"]`, `SerpFailed(code: str, cost_micros: int)` with `.code` and `.cost_micros`, `run_serp_audit(org_id, brand_id, job_id, meter, fetch=http_fetch) -> str`, and `process_job(..., *, fetch=http_fetch, serp_fetch=http_fetch)`. `tick` is unchanged.

- [ ] **Step 1: Write the failing tests**

In `tests/integration/test_serp_audit.py`, replace the import block

```python
from datetime import UTC, datetime

import pytest
from bsi_core import models as m
from sqlalchemy.exc import IntegrityError
```

with

```python
import json
from datetime import UTC, datetime
from decimal import Decimal

import bsi_workers.worker as worker
import pytest
from bsi_core import models as m
from bsi_core.config import Settings
from bsi_core.crawl import Response
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError

from tests.integration.test_worker import FakeAdapter, _job, _load_job, _spender
from tests.unit.test_dataforseo import ITEMS, Fetch, body

BATA = {
    "type": "organic",
    "rank_absolute": 5,
    "domain": "www.bata.com",
    "url": "https://www.bata.com/in/",
    "title": "Bata",
}


def _settings(login="me", password="pw"):
    return lambda: Settings(
        dataforseo_login=login, dataforseo_password=password
    )


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(worker, "get_settings", _settings())


def _run(fetch):
    _, generator, embedder = _spender()
    return worker.process_job(
        FakeAdapter(), generator, embedder, serp_fetch=fetch
    )


def _rows(owner, bid):
    with owner() as s:
        return list(
            s.scalars(
                select(m.SerpAudit)
                .where(m.SerpAudit.brand_id == bid)
                .order_by(
                    m.SerpAudit.country, m.SerpAudit.language, m.SerpAudit.kind
                )
            )
        )
```

and append these tests to the end of the file:

```python
def test_audit_serp_is_known_and_estimated():
    assert worker.JOB_ESTIMATES["audit_serp"] == worker.SERP_JOB_MICROS
    assert worker.SERP_JOB_MICROS == 40_000


def test_the_job_stores_one_classified_row_per_query(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host="walkaroo.in"))
        # A suggested competitor's domain is not used: amazon.in is "other".
        s.add(
            m.Competitor(
                org_id=org.id,
                brand_id=bid,
                name="Amazon",
                domains=["amazon.in"],
                status="suggested",
            )
        )
        s.add(
            m.Competitor(
                org_id=org.id, brand_id=bid, name="Bata", domains=["bata.com"]
            )
        )
    job_id = _job(owner, org, bid, "audit_serp", "queued")
    fetch = Fetch(Response(200, body([*ITEMS, BATA])))
    assert _run(fetch) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.error, job.cost_micros) == ("done", None, 8_000)
    rows = _rows(owner, bid)
    assert [
        (r.kind, r.query, r.country, r.language, r.device) for r in rows
    ] == [
        ("brand", "Walkaroo", "IN", "en", "desktop"),
        ("reviews", "Walkaroo reviews", "IN", "en", "desktop"),
    ]
    # People Also Ask (position 4) is not stored.
    assert [
        (x["position"], x["item_type"], x["result_type"], x["sitelinks"])
        for x in rows[0].results
    ] == [
        (1, "knowledge_graph", "knowledge_panel", False),
        (2, "organic", "official", True),
        (3, "organic", "other", False),
        (5, "organic", "competitor", False),
    ]
    assert rows[0].results[1] == {
        "position": 2,
        "item_type": "organic",
        "result_type": "official",
        "url": "https://walkaroo.in/",
        "domain": "walkaroo.in",
        "title": "Walkaroo footwear",
        "sitelinks": True,
    }
    for r in rows:
        assert (r.job_id, r.cost_micros, r.error) == (job_id, 4_000, None)
        assert r.fetched_at is not None
    assert [
        json.loads(kw["body"])[0]["keyword"] for _, _, kw in fetch.calls
    ] == [
        "Walkaroo",
        "Walkaroo reviews",
    ]


def test_a_partial_failure_keeps_both_rows_and_is_done(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    job_id = _job(owner, org, bid, "audit_serp", "queued")
    assert _run(Fetch(Response(200, body()), Response(500, "oops"))) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.error, job.cost_micros) == ("done", None, 4_000)
    brand, reviews = _rows(owner, bid)
    assert (brand.error, len(brand.results)) == (None, 3)
    assert (reviews.error, reviews.results, reviews.cost_micros) == (
        "http",
        [],
        0,
    )


def test_an_all_failed_run_keeps_its_rows_and_fails_with_the_code_and_cost(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    job_id = _job(owner, org, bid, "audit_serp", "queued")
    assert _run(Fetch(Response(200, body(task_status=40202)))) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.error, job.cost_micros) == ("failed", "rate", 8_000)
    assert [(r.error, r.cost_micros) for r in _rows(owner, bid)] == [
        ("rate", 4_000),
        ("rate", 4_000),
    ]


def test_a_failed_write_still_records_the_spend(
    monkeypatch, configured, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    job_id = _job(owner, org, bid, "audit_serp", "queued")
    # A value JSONB cannot store makes the write itself fail.
    monkeypatch.setattr(
        worker, "_serp_results", lambda *args: [{"bad": object()}]
    )
    assert _run(Fetch(Response(200, body()))) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.error, job.cost_micros) == (
        "failed",
        "error",
        8_000,
    )
    assert _rows(owner, bid) == []


def test_missing_credentials_fail_with_no_call_and_no_rows(
    monkeypatch, owner, make_org, make_brand
):
    monkeypatch.setattr(worker, "get_settings", _settings(password=""))
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    job_id = _job(owner, org, bid, "audit_serp", "queued")
    fetch = Fetch(Response(200, body()))
    assert _run(fetch) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.error, job.cost_micros) == (
        "failed",
        "serp_not_configured",
        0,
    )
    assert fetch.calls == [] and _rows(owner, bid) == []


def test_only_the_first_five_locales_are_audited(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")  # comes with IN/en
    with owner() as s, s.begin():
        for language in ("hi", "ta", "te", "bn", "mr", "gu"):
            s.add(
                m.Locale(
                    org_id=org.id, brand_id=bid, country="IN", language=language
                )
            )
    job_id = _job(owner, org, bid, "audit_serp", "queued")
    fetch = Fetch(Response(200, body()))
    assert _run(fetch) is True
    assert len(fetch.calls) == 10 and len(_rows(owner, bid)) == 10
    job = _load_job(owner, job_id)
    assert (job.status, job.cost_micros) == ("done", 40_000)


def test_a_brand_with_no_locale_uses_in_en(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    with owner() as s, s.begin():
        s.execute(delete(m.Locale).where(m.Locale.brand_id == bid))
    _job(owner, org, bid, "audit_serp", "queued")
    assert _run(Fetch(Response(200, body()))) is True
    assert [(r.country, r.language) for r in _rows(owner, bid)] == [
        ("IN", "en"),
        ("IN", "en"),
    ]


def test_no_transaction_is_open_during_the_calls(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _job(owner, org, bid, "audit_serp", "queued")
    seen = []

    def fetch(url, user_agent, **kw):
        with owner() as s:
            seen.append(
                s.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE state = 'idle in transaction' "
                        "AND pid <> pg_backend_pid()"
                    )
                )
            )
        return Response(200, body())

    assert _run(fetch) is True
    assert seen == [0, 0]


def test_an_over_budget_serp_job_fails_without_a_call(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    job_id = _job(owner, org, bid, "audit_serp", "queued")
    with owner() as s, s.begin():
        # $0.03 is under the job's $0.04 estimate.
        s.execute(
            update(m.Organization)
            .where(m.Organization.id == org.id)
            .values(daily_budget_usd=Decimal("0.03"))
        )
    fetch = Fetch(Response(200, body()))
    assert _run(fetch) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.error, job.cost_micros) == ("failed", "budget", 0)
    assert fetch.calls == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run `pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_serp_audit.py 2>&1 | tail -4`
Expected: `10 failed, 1 passed`. `test_audit_serp_is_known_and_estimated` fails with `KeyError: 'audit_serp'`; the others fail with `TypeError: process_job() got an unexpected keyword argument 'serp_fetch'`. The one pass is `test_the_kind_is_checked`.

- [ ] **Step 3: Add the job to the worker**

In `apps/workers/bsi_workers/worker.py`:

(a) Replace

```python
from bsi_core.providers.base import EngineAdapter
from bsi_core.providers.gemini import GeminiGroundingAdapter
```

with

```python
from bsi_core.providers.base import EngineAdapter
from bsi_core.providers.dataforseo import SerpFetch, SerpItem, serp
from bsi_core.providers.gemini import GeminiGroundingAdapter
```

and replace

```python
from bsi_core.scheduling import budget_fits, enqueue_job, run_schedule
```

with

```python
from bsi_core.scheduling import budget_fits, enqueue_job, run_schedule
from bsi_core.serp import classify
```

(b) Replace

```python
    "import_feed": 0,  # HTTP only: no model, no spend
}
```

with

```python
    "import_feed": 0,  # HTTP only: no model, no spend
    "audit_serp": SERP_JOB_MICROS,
}
```

and, directly above the comment line `# What a suggestion job reserves before it spends (spec §5).`, add this block, followed by two blank lines:

```python
# 5 locales x 2 queries x $0.004 (a live page plus AI Overview loading).
SERP_JOB_MICROS = 40_000
MAX_SERP_LOCALES = 5


class SerpFailed(RuntimeError):
    """An audit_serp job with no usable page; carries the short error
    code and everything the run spent."""

    def __init__(self, code: str, cost_micros: int) -> None:
        super().__init__(code)
        self.code = code
        self.cost_micros = cost_micros
```

(c) Directly above `def process_job(`, add this block, followed by two blank lines:

```python
def _serp_results(
    items: list[SerpItem], own: list[str], rivals: list[str]
) -> list[dict[str, Any]]:
    """The stored form of a page: each item with our result type; an
    item classify() does not type is dropped."""
    out = []
    for item in items:
        kind = classify(item.item_type, item.domain or item.url, own, rivals)
        if kind is not None:
            out.append(
                {
                    "position": item.position,
                    "item_type": item.item_type,
                    "result_type": kind,
                    "url": item.url,
                    "domain": item.domain,
                    "title": item.title,
                    "sitelinks": item.sitelinks,
                }
            )
    return out


def run_serp_audit(
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    job_id: uuid.UUID,
    meter: _Meter,
    fetch: SerpFetch = http_fetch,
) -> str:
    """Audit the brand's Google first pages: `{name}` and `{name} reviews`
    in each of its first MAX_SERP_LOCALES locales.

    The calls happen with no transaction open; the rows are written
    together at the end. Any failure after the first call leaves as
    SerpFailed with the run's spend, so the money is recorded either way.
    """
    settings = get_settings()
    login = settings.dataforseo_login
    password = settings.dataforseo_password.get_secret_value()
    if not login or not password:
        raise SerpFailed("serp_not_configured", 0)
    with tenant_session(org_id) as s:
        name = s.get_one(m.Brand, brand_id).name
        own = list(
            s.scalars(
                select(m.Domain.host).where(m.Domain.brand_id == brand_id)
            )
        )
        locales = [
            (country, language)
            for country, language in s.execute(
                select(m.Locale.country, m.Locale.language)
                .where(m.Locale.brand_id == brand_id)
                .order_by(m.Locale.created_at, m.Locale.id)
            )
        ] or [("IN", "en")]
        rivals = [
            domain
            for domains in s.scalars(
                select(m.Competitor.domains).where(
                    m.Competitor.brand_id == brand_id,
                    m.Competitor.status == "active",
                )
            )
            for domain in domains
        ]
    skipped = max(0, len(locales) - MAX_SERP_LOCALES)
    spent = 0
    rows: list[m.SerpAudit] = []
    try:
        for country, language in locales[:MAX_SERP_LOCALES]:
            for kind, query in (
                ("brand", name),
                ("reviews", f"{name} reviews"),
            ):
                page = serp(
                    query,
                    country,
                    language,
                    login=login,
                    password=password,
                    fetch=fetch,
                )
                spent += page.cost_micros
                meter.micros += page.cost_micros
                rows.append(
                    m.SerpAudit(
                        org_id=org_id,
                        brand_id=brand_id,
                        job_id=job_id,
                        kind=kind,
                        query=query,
                        country=country,
                        language=language,
                        results=_serp_results(page.items, own, rivals),
                        fetched_at=datetime.now(UTC),
                        cost_micros=page.cost_micros,
                        error=page.error,
                    )
                )
        with tenant_session(org_id) as s:
            s.add_all(rows)
    except Exception as e:
        raise SerpFailed("error", spent) from e
    failed = [row.error for row in rows if row.error]
    if len(failed) == len(rows):
        raise SerpFailed(failed[0], spent)
    return f"serp:{len(rows)} failed:{len(failed)} skipped_locales:{skipped}"
```

(d) In `process_job`, replace

```python
    *,
    fetch: Fetch = http_fetch,
) -> bool:
    """Run one claimed job. False = nothing was queued."""
```

with

```python
    *,
    fetch: Fetch = http_fetch,
    serp_fetch: SerpFetch = http_fetch,
) -> bool:
    """Run one claimed job. False = nothing was queued."""
```

replace

```python
        "import_feed": lambda: run_import_feed(
            org_id, brand_id, job_id, params, fetch
        ),
    }
```

with

```python
        "import_feed": lambda: run_import_feed(
            org_id, brand_id, job_id, params, fetch
        ),
        "audit_serp": lambda: run_serp_audit(
            org_id, brand_id, job_id, meter, serp_fetch
        ),
    }
```

and replace

```python
        elif isinstance(e, CatalogueCap):
            error = "cap"
        else:
```

with

```python
        elif isinstance(e, CatalogueCap):
            error = "cap"
        elif isinstance(e, SerpFailed):
            error = e.code
        else:
```

`tick` is not changed: the worker loop uses `process_job`'s default `serp_fetch`.

- [ ] **Step 4: Run the tests to verify they pass**

Run `pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_serp_audit.py tests/integration/test_worker.py 2>&1 | tail -1`
Expected: all passed, 0 failed (11 in test_serp_audit.py plus test_worker.py's existing tests).

- [ ] **Step 5: Banned-word grep, then the backend gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/workers/bsi_workers/worker.py tests/integration/test_serp_audit.py`. Run the banned-word grep (expected: no match). Run `pgrep -fl pytest` on its own, then the Backend gate with `<N>` = 4. Expected: `gate exit 0`; `gate-task4.txt` shows `1633 passed, 2 deselected` and the metrics coverage line at 100%.

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/workers/bsi_workers/worker.py tests/integration/test_serp_audit.py && git commit -m "feat(worker): the audit_serp job

run_serp_audit reads the brand in a short session, calls the provider
for the brand and reviews queries of up to five locales with no
transaction open, and writes one serp_audit row per query. A run with
no usable page fails with the provider's short code; any failure
carries the run's spend, so the job records it.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: the API routes

**Files:**
- Modify: `apps/api/bsi_api/schemas.py`
- Modify: `apps/api/bsi_api/routers/audits.py`
- Modify: `tests/integration/test_isolation.py`
- Test: `tests/integration/test_api_serp.py` (new)
- Regenerate: `apps/web/openapi.json`, `apps/web/src/lib/schema.d.ts`

**Interfaces:**
- Consumes: `m.SerpAudit` (Task 3); `ownership` (Task 1); `queue_suggestion(c, brand_id, kind, params)` from `routers/runs.py`; `brand_or_404`, `TENANT`, `Ctx` from `deps.py`.
- Produces: `POST /v1/brands/{brand_id}/audits/serp` → 202 `QueuedOut`; `GET /v1/brands/{brand_id}/audits/serp` → `SerpAuditsOut` `{"job": {"status", "error"} | null, "audits": [SerpAuditOut]}`; `SerpAuditOut` has `id, kind, query, country, language, device, fetched_at, cost_micros, error, results, owned, organic`; `SerpResultOut` has `position, item_type, result_type, url, domain, title, sitelinks`. The generated TypeScript names are `components["schemas"]["SerpAuditsOut"]` and `["SerpAuditOut"]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_api_serp.py`:

```python
from datetime import UTC, datetime, timedelta

from bsi_core import models as m
from sqlalchemy import update

from tests.integration.test_worker import _job

OFFICIAL = {
    "position": 1,
    "item_type": "organic",
    "result_type": "official",
    "url": "https://nike.com/",
    "domain": "nike.com",
    "title": "Nike",
    "sitelinks": True,
}
OTHER = {**OFFICIAL, "position": 2, "result_type": "other", "sitelinks": False}
PANEL = {
    "position": 3,
    "item_type": "knowledge_graph",
    "result_type": "knowledge_panel",
    "url": "",
    "domain": "",
    "title": "Nike",
    "sitelinks": False,
}


def _audit(owner, org, bid, kind, minutes_ago, results=(), error=None):
    with owner() as s, s.begin():
        s.add(
            m.SerpAudit(
                org_id=org.id,
                brand_id=bid,
                kind=kind,
                query="nike" if kind == "brand" else "nike reviews",
                country="IN",
                language="en",
                results=list(results),
                fetched_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
                cost_micros=4_000,
                error=error,
            )
        )


def test_post_queues_a_serp_audit_job(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    r = client.post(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert r.status_code == 202, r.text
    queued = r.json()
    assert queued["status"] == "queued"
    with owner() as s:
        job = s.get(m.Job, queued["job_id"])
    assert (job.kind, job.brand_id) == ("audit_serp", bid)
    # Same hour, same job.
    again = client.post(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert again.json()["job_id"] == queued["job_id"]


def test_post_on_an_archived_brand_is_409(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand).where(m.Brand.id == bid).values(status="archived")
        )
    r = client.post(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert r.status_code == 409


def test_get_is_empty_before_any_audit(client, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert r.status_code == 200, r.text
    assert r.json() == {"job": None, "audits": []}


def test_get_returns_the_latest_row_per_query_with_ownership(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _audit(owner, org, bid, "brand", 60, [OTHER])
    _audit(owner, org, bid, "brand", 5, [OFFICIAL, OTHER, PANEL])
    _audit(owner, org, bid, "reviews", 60, [OFFICIAL])
    # The latest reviews row is an error: it is shown, not the older one.
    _audit(owner, org, bid, "reviews", 5, error="rate")
    r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert r.status_code == 200, r.text
    brand, reviews = r.json()["audits"]
    assert (brand["kind"], brand["query"]) == ("brand", "nike")
    assert (brand["country"], brand["language"], brand["device"]) == (
        "IN",
        "en",
        "desktop",
    )
    assert (brand["owned"], brand["organic"]) == (1, 2)
    assert brand["cost_micros"] == 4_000 and brand["error"] is None
    assert brand["results"] == [OFFICIAL, OTHER, PANEL]
    assert (reviews["kind"], reviews["error"]) == ("reviews", "rate")
    assert (reviews["owned"], reviews["organic"]) == (0, 0)
    assert reviews["results"] == []


def test_get_reports_the_latest_audit_serp_job(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _job(owner, org, bid, "audit_crawl", "done", minutes=-120)
    _job(owner, org, bid, "audit_serp", "done", minutes=-60)
    newest = _job(
        owner, org, bid, "audit_serp", "failed", error="serp_not_configured"
    )
    with owner() as s, s.begin():
        # created_at orders the jobs; make the failed one the newest.
        s.execute(
            update(m.Job)
            .where(m.Job.id != newest, m.Job.brand_id == bid)
            .values(created_at=datetime.now(UTC) - timedelta(hours=1))
        )
    r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert r.json()["job"] == {
        "status": "failed",
        "error": "serp_not_configured",
    }
```

In `tests/integration/test_isolation.py`, replace

```python
    ("POST", "/v1/brands/{b}/audits/crawl", None),
    ("GET", "/v1/brands/{b}/audits/crawl", None),
```

with

```python
    ("POST", "/v1/brands/{b}/audits/crawl", None),
    ("GET", "/v1/brands/{b}/audits/crawl", None),
    ("POST", "/v1/brands/{b}/audits/serp", None),
    ("GET", "/v1/brands/{b}/audits/serp", None),
```

- [ ] **Step 2: Run the tests to verify they fail**

Run `pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_api_serp.py 2>&1 | tail -3`
Expected: `5 failed`; the first assertion to fail in each is a status code of 404 or 405 where 202, 409 or 200 was expected (the routes do not exist).

- [ ] **Step 3: Add the schemas**

In `apps/api/bsi_api/schemas.py`:

(a) Replace

```python
from bsi_core.reports import Document
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)
```

with

```python
from bsi_core.reports import Document
from bsi_core.serp import ownership
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
)
```

(b) Directly after the `SiteAuditOut` class (it ends with the line `    checks: list[CheckOut]`), add:

```python
class SerpResultOut(BaseModel):
    position: int
    item_type: str
    result_type: str
    url: str
    domain: str
    title: str
    sitelinks: bool


class SerpAuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    query: str
    country: str
    language: str
    device: str
    fetched_at: datetime
    cost_micros: int
    error: str | None
    results: list[SerpResultOut]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def owned(self) -> int:
        """Organic results on the brand's own hosts."""
        return ownership(r.model_dump() for r in self.results)[0]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def organic(self) -> int:
        """All organic results on the page."""
        return ownership(r.model_dump() for r in self.results)[1]


class SerpJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str | None
    error: str | None


class SerpAuditsOut(BaseModel):
    job: SerpJobOut | None
    audits: list[SerpAuditOut]
```

- [ ] **Step 4: Add the routes**

In `apps/api/bsi_api/routers/audits.py`, replace

```python
"""Audits of the brand's own site. Only the crawlability audit so far."""
```

with

```python
"""Audits of the brand: its own site's crawlability, and its Google
first pages (the Brand SERP audit)."""
```

replace

```python
from ..schemas import QueuedOut, SiteAuditOut
```

with

```python
from ..schemas import QueuedOut, SerpAuditsOut, SiteAuditOut
```

and append to the end of the file:

```python


@router.post("/serp", status_code=202, response_model=QueuedOut)
def queue_serp(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    return queue_suggestion(c, brand_id, "audit_serp", {})


@router.get("/serp", response_model=SerpAuditsOut)
def latest_serp(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    """The latest page per (kind, country, language), an error row
    included, and the latest audit_serp job so a failure that wrote no
    rows (no credentials, budget, stale) still shows."""
    brand_or_404(c, brand_id)
    audits = list(
        c.s.scalars(
            select(m.SerpAudit)
            .where(m.SerpAudit.brand_id == brand_id)
            .order_by(
                m.SerpAudit.country,
                m.SerpAudit.language,
                m.SerpAudit.kind,
                m.SerpAudit.fetched_at.desc(),
                m.SerpAudit.id.desc(),
            )
            .distinct(
                m.SerpAudit.country, m.SerpAudit.language, m.SerpAudit.kind
            )
        )
    )
    job = c.s.scalars(
        select(m.Job)
        .where(m.Job.brand_id == brand_id, m.Job.kind == "audit_serp")
        .order_by(m.Job.created_at.desc(), m.Job.id.desc())
        .limit(1)
    ).first()
    return {"job": job, "audits": audits}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run `pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_api_serp.py tests/integration/test_isolation.py tests/integration/test_api_audits.py 2>&1 | tail -1`
Expected: all passed, 0 failed.

- [ ] **Step 6: Regenerate the API types**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gen 2>&1 | tail -3`
Then: `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short apps/web && grep -c "SerpAuditsOut" apps/web/src/lib/schema.d.ts`
Expected: `apps/web/openapi.json` and `apps/web/src/lib/schema.d.ts` modified and nothing else under apps/web; the grep count is at least 1.

- [ ] **Step 7: Banned-word grep, then both gates**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/api/bsi_api/schemas.py apps/api/bsi_api/routers/audits.py tests/integration/test_api_serp.py tests/integration/test_isolation.py apps/web/openapi.json apps/web/src/lib/schema.d.ts`. Run the banned-word grep (expected: no match). Run `pgrep -fl pytest` on its own, then the Backend gate with `<N>` = 5. Expected: `gate exit 0`; `gate-task5.txt` shows `1640 passed, 2 deselected` and the metrics coverage line at 100%. Then the Web gate with `<N>` = 5. Expected: `web gate exit 0`; `web-task5.txt` shows `Tests  43 passed (43)` and `gen:check` leaves no diff (the generated files are staged, so `git diff --exit-code` passes).

- [ ] **Step 8: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/api/bsi_api/schemas.py apps/api/bsi_api/routers/audits.py tests/integration/test_api_serp.py tests/integration/test_isolation.py apps/web/openapi.json apps/web/src/lib/schema.d.ts && git commit -m "feat(api): queue and read the Brand SERP audit

POST /brands/{id}/audits/serp queues an audit_serp job. GET returns
the latest page per query and locale with its ownership counts, and
the latest audit_serp job's status and error.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: the Brand SERP page

**Files:**
- Modify: `apps/web/src/lib/format.ts`
- Modify: `apps/web/src/lib/format.test.ts`
- Modify: `apps/web/src/lib/types.ts`
- Modify: `apps/web/src/app/(app)/b/[id]/layout.tsx`
- Create: `apps/web/src/app/(app)/b/[id]/serp/page.tsx`
- Create: `apps/web/src/app/(app)/b/[id]/serp/actions.ts`

**Interfaces:**
- Consumes: the generated `components["schemas"]["SerpAuditsOut"]` and `["QueuedOut"]` (Task 5); `api<T>(path, init?)` from `@/lib/api`; `auditNote(status)` and `Params` from `@/lib/format`.
- Produces: `serpError(code)`, `serpStatus(job)`, `ownershipText(owned, organic)`, `typeCounts(results)` in `@/lib/format`; `SerpAudits` in `@/lib/types`; the route `/b/{id}/serp`.

- [ ] **Step 1: Write the failing tests**

In `apps/web/src/lib/format.test.ts`, add `ownershipText`, `serpError`, `serpStatus` and `typeCounts` to the import list from `"./format"` (the list is alphabetical, ignoring case; keep it so), and append to the end of the file:

```ts
test("serpError labels a known code and passes an unknown one through", () => {
  expect(serpError("auth")).toBe("the SERP provider rejected the login");
  expect(serpError("provider_50000")).toBe("provider_50000");
  expect(serpError("constructor")).toBe("constructor");
  expect(serpError(null)).toBe("");
});

test("serpStatus shows a run in progress or a failure, else nothing", () => {
  expect(serpStatus(null)).toBeNull();
  expect(serpStatus({ status: "queued", error: null })).toBe(
    "Audit in progress",
  );
  expect(serpStatus({ status: "running", error: null })).toBe(
    "Audit in progress",
  );
  expect(serpStatus({ status: "failed", error: "budget" })).toBe(
    "Last audit failed: the daily budget is used up",
  );
  expect(serpStatus({ status: "done", error: null })).toBeNull();
});

test("ownershipText gives the count and a whole percentage", () => {
  expect(ownershipText(3, 10)).toBe("3 of 10 (30%)");
  expect(ownershipText(1, 3)).toBe("1 of 3 (33%)");
  expect(ownershipText(0, 0)).toBe("0 of 0");
});

test("typeCounts lists result types, most frequent first", () => {
  const results = [
    { result_type: "other" },
    { result_type: "official" },
    { result_type: "other" },
    { result_type: "knowledge_panel" },
  ];
  expect(typeCounts(results)).toBe("other 2 · knowledge_panel 1 · official 1");
  expect(typeCounts([])).toBe("");
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/format.test.ts 2>&1 | tail -6`
Expected: the file fails; the four new tests fail with `serpError is not a function` (and the like for the other three), or the run reports the missing exports.

- [ ] **Step 3: Add the helpers**

In `apps/web/src/lib/format.ts`, directly above the line `// Display names for alert types.`, add:

```ts
// Why a SERP audit job or one of its queries failed.
const SERP_ERRORS: Record<string, string> = {
  serp_not_configured: "the SERP provider login is not set on the server",
  budget: "the daily budget is used up",
  stale: "the run took too long and was stopped",
  location: "this country is not supported yet",
  auth: "the SERP provider rejected the login",
  funds: "the SERP provider account has no balance",
  rate: "the SERP provider's rate limit was hit",
  http: "the SERP provider could not be reached",
  truncated: "the SERP provider's answer was too large",
  json: "the SERP provider's answer could not be read",
  error: "the audit crashed",
};

/** A label for a SERP error code; an unknown code is shown as is. */
export const serpError = (code: string | null | undefined) =>
  code == null
    ? ""
    : Object.hasOwn(SERP_ERRORS, code)
      ? SERP_ERRORS[code]
      : code;

/** The Brand SERP page's status line, from the latest audit_serp job. */
export const serpStatus = (
  job: { status?: string | null; error?: string | null } | null | undefined,
) =>
  !job
    ? null
    : job.status === "queued" || job.status === "running"
      ? "Audit in progress"
      : job.status === "failed"
        ? `Last audit failed: ${serpError(job.error)}`
        : null;

/** "3 of 10 (30%)"; no percentage when the page has no organic results. */
export const ownershipText = (owned: number, organic: number) =>
  organic === 0
    ? "0 of 0"
    : `${owned} of ${organic} (${Math.round((owned / organic) * 100)}%)`;

/** "other 2 · official 1": result types, most frequent first. */
export const typeCounts = (results: { result_type: string }[]) => {
  const counts = new Map<string, number>();
  for (const r of results) {
    counts.set(r.result_type, (counts.get(r.result_type) ?? 0) + 1);
  }
  return [...counts]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([type, n]) => `${type} ${n}`)
    .join(" · ");
};

```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/format.test.ts 2>&1 | tail -4`
Expected: the file passes, with 4 more tests than before this task.

- [ ] **Step 5: Add the type, the action, the page and the nav link**

In `apps/web/src/lib/types.ts`, replace

```ts
export type Queued = S["QueuedOut"];
```

with

```ts
export type Queued = S["QueuedOut"];
export type SerpAudits = S["SerpAuditsOut"];
```

Create `apps/web/src/app/(app)/b/[id]/serp/actions.ts`:

```ts
"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";
import type { Queued } from "@/lib/types";

export async function runSerpAudit(form: FormData) {
  const id = String(form.get("brand_id"));
  const job = await api<Queued>(`/brands/${id}/audits/serp`, {
    method: "POST",
  });
  // The API returns this hour's job, which may already be done.
  redirect(`/b/${id}/serp?queued=${encodeURIComponent(job.status)}`);
}
```

Create `apps/web/src/app/(app)/b/[id]/serp/page.tsx`:

```tsx
import { api } from "@/lib/api";
import {
  auditNote,
  ownershipText,
  serpError,
  serpStatus,
  typeCounts,
  usd,
  type Params,
} from "@/lib/format";
import type { SerpAudits } from "@/lib/types";
import { runSerpAudit } from "./actions";

export default async function Serp({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const { job, audits } = await api<SerpAudits>(`/brands/${id}/audits/serp`);
  const status = serpStatus(job);
  return (
    <>
      <form action={runSerpAudit} className="row">
        <input type="hidden" name="brand_id" value={id} />
        <button className="primary">Run audit now</button>
        {auditNote(sp.queued) && (
          <span className="muted">{auditNote(sp.queued)}</span>
        )}
      </form>
      {status && <p className="muted">{status}</p>}
      {audits.length === 0 && (
        <p className="muted">
          No audit yet. Run one to see Google&apos;s first page for the brand
          name and for its reviews.
        </p>
      )}
      {audits.map((a) => {
        const has = (type: string) =>
          a.results.some((r) => r.result_type === type);
        return (
          <div className="card" key={a.id} style={{ marginTop: 12 }}>
            <div className="row">
              <strong>{a.query}</strong>
              <span className="muted">
                {a.country}/{a.language} · {a.device} ·{" "}
                {a.fetched_at.slice(0, 16).replace("T", " ")} UTC ·{" "}
                {usd(a.cost_micros)}
              </span>
            </div>
            {a.error ? (
              <p className="down">Failed: {serpError(a.error)}</p>
            ) : (
              <>
                <p>
                  Ownership: {ownershipText(a.owned, a.organic)}
                  <span className="muted"> · {typeCounts(a.results)}</span>
                </p>
                <p className="muted">
                  Knowledge Panel: {has("knowledge_panel") ? "yes" : "no"} · AI
                  Overview: {has("ai_overview") ? "yes" : "no"}
                </p>
                <table>
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Type</th>
                      <th>Title</th>
                      <th>Host</th>
                      <th>Sitelinks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {a.results.map((r, i) => (
                      <tr key={`${r.position}-${i}`}>
                        <td>{r.position}</td>
                        <td>
                          <span className="tag">{r.result_type}</span>
                        </td>
                        <td>
                          {r.url.startsWith("https://") ||
                          r.url.startsWith("http://") ? (
                            <a
                              href={r.url}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {r.title || r.url}
                            </a>
                          ) : (
                            r.title
                          )}
                        </td>
                        <td className="muted">{r.domain}</td>
                        <td>{r.sitelinks ? "✓" : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        );
      })}
    </>
  );
}
```

In `apps/web/src/app/(app)/b/[id]/layout.tsx`, replace

```tsx
        <Link href={`/b/${id}/site`}>Site</Link>
```

with

```tsx
        <Link href={`/b/${id}/site`}>Site</Link>
        <Link href={`/b/${id}/serp`}>Brand SERP</Link>
```

- [ ] **Step 6: Banned-word grep, then both gates**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/format.ts apps/web/src/lib/format.test.ts apps/web/src/lib/types.ts "apps/web/src/app/(app)/b/[id]/layout.tsx" "apps/web/src/app/(app)/b/[id]/serp/page.tsx" "apps/web/src/app/(app)/b/[id]/serp/actions.ts"`. Run the banned-word grep (expected: no match). Run the Web gate with `<N>` = 6. Expected: `web gate exit 0`; `web-task6.txt` shows `Tests  47 passed (47)`, `Compiled successfully`, and the route `/b/[id]/serp` in the build's route list. Then run `pgrep -fl pytest` on its own and the Backend gate with `<N>` = 6. Expected: `gate exit 0`; `gate-task6.txt` shows `1640 passed, 2 deselected`. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` — expected: only the six staged files.

- [ ] **Step 7: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/format.ts apps/web/src/lib/format.test.ts apps/web/src/lib/types.ts "apps/web/src/app/(app)/b/[id]/layout.tsx" "apps/web/src/app/(app)/b/[id]/serp/page.tsx" "apps/web/src/app/(app)/b/[id]/serp/actions.ts" && git commit -m "feat(web): the Brand SERP page

A Run audit now button, a status line from the latest audit_serp job,
and one card per query and locale: ownership as a count and a
percentage, a count per result type, Knowledge Panel and AI Overview
presence, and the results table. A failed query shows its error label.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review (plan vs spec)

- Spec coverage:
  - Settings and credentials → Task 1 Step 4.
  - The adapter → Task 2.
  - Data model → Task 3.
  - Classification and ownership → Task 1.
  - The job → Task 4.
  - API → Task 5.
  - Web → Task 6.
  - Tests → each task's Step 1.
  - Copy → each task's banned-word grep.
  - The live check, the findings file, README rows and memory are controller work after merge.
- Departures from the spec:
  1. `serp.py` imports `from .matching import …` (inside the package); the spec's prototype imported `bsi_core.matching` from outside it.
  2. The adapter checks `resp.ok` before `resp.truncated`, so a failed HTTP status with a cut body is `http`; the spec lists the two codes without an order.
  3. `SerpItem.sitelinks` is true only for an item of type `organic`; the spec says "an organic item with a non-empty `links`", which this makes exact for other item types that carry `links`.
  4. The spec's test list has "a write failure still recording the spend"; Task 4 produces it by patching `_serp_results` to return a value JSONB cannot store, so the write itself fails.
  5. The spec's `process_job` runner passes `serp_fetch` positionally (`run_serp_audit(org_id, brand_id, job_id, meter, serp_fetch)`), as written there.
  6. The locale cap test asserts the count of calls and rows (10) and the job's cost (40,000), not which five locales were used: the seven locales share one `created_at`, so their order is by `id`.
  7. The spec's "a vitest for the page's formatting helpers" is four tests in `format.test.ts`; the page itself has no test, as the Site page has none.
  8. `GET` orders its rows by country, language, then kind (`brand` before `reviews`); the spec gives no order.
  9. `owned` and `organic` are pydantic computed fields on `SerpAuditOut`; the spec says only that they come from `ownership(results)`.
  10. The page shows each row's device and cost; the spec's card list has the query, country, language and fetch time.
- Rulings applied to this plan: the spec's R1 (the Fable 5.1 trailer; a switch needs a new ruling and a plan edit).
- Placeholders: `<workspace>` (the path the task brief supplies) and `<N>` (the task number in gate file names).
- Type consistency: `classify(item_type, host, own, rivals)` and `ownership(results)` are used with those signatures in Tasks 4 and 5; `serp(query, country, language, *, login, password, fetch)` and `SerpItem`'s six fields in Task 4; `m.SerpAudit`'s columns in Tasks 4 and 5; `Fetch(*responses)`, `body(...)` and `ITEMS` from Task 2's test module in Task 4; `SerpAuditsOut` in Tasks 5 and 6.
