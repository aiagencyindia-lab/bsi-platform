# Slice 7: Citation Intelligence and Crawlability Audit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the operator a per-domain view of who the engine cites (with gap detection), and an automatic audit of the brand's own site whose failing checks become `fix_crawlability` recommendations.

**Architecture:** Citations are one read-only SQL module over rows that already exist, served by one endpoint and one page. The crawl audit is a new job kind (`audit_crawl`) the existing worker claims, a pure `audit_domain()` function fed by an injected fetch callable, one tenant table (`site_audit`), a weekly due-function like `due_recommendation_refreshes()`, and a fifth recommendation rule. No model calls anywhere in this slice.

**Tech Stack:** Python 3.13, SQLAlchemy 2 + psycopg 3 + Alembic, FastAPI, `httpx` (already installed; declared now), stdlib `urllib.robotparser` / `html.parser` / `xml.etree`; Next.js 15 App Router (server components only), `openapi-typescript`; pytest, ruff, mypy --strict, vitest.

**Spec:** `docs/superpowers/specs/2026-09-23-slice7-citations-and-crawlability-design.md`

## Global Constraints

- Every new tenant table: `org_id`, ENABLE + FORCE RLS via `_protect()` (copy from `migrations/versions/0009_recommendations_and_tasks.py:33-41`), listed in `TENANT_TABLES` and populated in the `org_b` fixture (`tests/integration/test_rls.py`).
- Every new id-bearing route: a row in `CASES` (`tests/integration/test_isolation.py:95`) plus an owner-path test that gets a 2xx.
- Cross-tenant work only through SECURITY DEFINER functions called from `system_session()`.
- **No transaction open while fetching** (same rule as model calls).
- Tests never touch the network: the fetch is an injected callable.
- Constants in `models.py` generate CHECK constraints; migrations spell values out literally; `test_constraints.py` compares the live constraint to the constant.
- Recommendation copy: no word from `FORBIDDEN` in `tests/unit/test_recommend_copy.py`, and every body contains the literal `Metric to watch:`.
- Frontend computes no statistic, interval or priority; Server Components and server actions only; types are generated (`npm run gen`, then `git add`, then `npm run gate`).
- Line length 80 (ruff). `bsi_core.metrics` stays at 100% line coverage.
- Commit subjects are conventional; every commit ends with a blank line then `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Every command starts with `cd /Users/vineet/Downloads/ADK/bsi-platform &&` (the shell's cwd resets). The gate:
  ```bash
  cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100
  cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate
  ```
- Branch: `slice7-audits` (already exists, holds the spec commit).

---

## File structure

| File | Responsibility |
|---|---|
| `packages/core/bsi_core/citations.py` (new) | `sources()`: per-domain citation aggregates; `source_type()` heuristic |
| `packages/core/bsi_core/crawl.py` (new) | `Response`, `Fetch`, `Check`, `Audit`, `audit_domain()`, `http_fetch()`, `BOTS`, severity/expected tables |
| `packages/core/bsi_core/models.py` | `SiteAudit` model; `REC_TYPES` gains `fix_crawlability` |
| `migrations/versions/0012_site_audit_and_crawlability.py` (new) | `site_audit` table + RLS, `due_crawl_audits()`, five-value `ck_recommendation_type` |
| `packages/core/bsi_core/scheduling.py` | `enqueue_job()` (moved out of the API so the worker can queue) |
| `packages/core/bsi_core/recommend.py` | `_crawl` rule, `crawl_copy`, `FEASIBILITY["fix_crawlability"]`, `generate` calls the rule |
| `apps/workers/bsi_workers/worker.py` | dispatch by kind, `run_crawl_audit`, `queue_due_crawl_audits`, main loop |
| `apps/api/bsi_api/routers/citations.py` (new) | `GET /brands/{id}/citations` |
| `apps/api/bsi_api/routers/audits.py` (new) | `POST /brands/{id}/audits/crawl`, `GET /brands/{id}/audits/crawl` |
| `apps/api/bsi_api/routers/runs.py` | `queue_suggestion` delegates to `enqueue_job` |
| `apps/api/bsi_api/routers/recommendations.py` | `NO_IMPACT` gains `fix_crawlability` |
| `apps/api/bsi_api/schemas.py` | `RivalOut`, `SourceOut`, `CheckOut`, `SiteAuditOut`, `QueuedOut` |
| `apps/api/bsi_api/main.py` | register the two routers |
| `apps/web/src/app/(app)/b/[id]/citations/page.tsx` (new) | Citations tab |
| `apps/web/src/app/(app)/b/[id]/site/{page.tsx,actions.ts}` (new) | Site tab + "Run audit now" |
| `apps/web/src/app/(app)/b/[id]/layout.tsx`, `lib/format.ts`, `lib/types.ts` | tabs, `KIND`, type aliases |
| `docs/findings-slice7.md`, `docs/README.md` | findings and the index |

---

### Task 1: Citation sources query

**Files:**
- Create: `packages/core/bsi_core/citations.py`
- Test: `tests/unit/test_citations_source_type.py`, `tests/integration/test_citations.py`

**Interfaces:**
- Consumes: `metrics.Filters`, `metrics._where` (`packages/core/bsi_core/metrics.py:67-100`), `matching.is_owned`, `recommend._rival_domains` (`recommend.py:166`).
- Produces: `sources(s: Session, brand_id: uuid.UUID, f: Filters) -> list[dict[str, Any]]` with keys `domain, owner, source_type, answers, prompts, first_seen, last_seen, brand_named, rivals, gap, observation_ids`; `source_type(domain: str, owner: str) -> str`; constants `OWNERS = ("brand", "rival", "third_party")`, `SOURCE_TYPES = ("vendor", "video", "community", "review", "other")`, `EVIDENCE_CAP = 20`.

- [ ] **Step 1: Write the failing unit test for the heuristic**

`tests/unit/test_citations_source_type.py`:

```python
import pytest
from bsi_core.citations import SOURCE_TYPES, source_type


@pytest.mark.parametrize(
    ("domain", "owner", "expected"),
    [
        ("nike.com", "brand", "vendor"),
        ("adidas.co.in", "rival", "vendor"),
        ("youtube.com", "third_party", "video"),
        ("m.youtube.com", "third_party", "video"),
        ("reddit.com", "third_party", "community"),
        ("quora.com", "third_party", "community"),
        ("english.stackexchange.com", "third_party", "community"),
        ("runrepeat.com", "third_party", "other"),
        ("reviews.in", "third_party", "review"),
        ("g2.com", "third_party", "review"),
        ("trustpilot.com", "third_party", "review"),
        ("forbes.com", "third_party", "other"),
        # A vendor is a vendor even if its name says "review".
        ("shoereview.com", "rival", "vendor"),
    ],
)
def test_source_type_heuristic(domain, owner, expected):
    assert source_type(domain, owner) == expected
    assert expected in SOURCE_TYPES
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_citations_source_type.py`
Expected: `ModuleNotFoundError: No module named 'bsi_core.citations'`

- [ ] **Step 3: Write the integration test**

`tests/integration/test_citations.py`:

```python
"""Per-domain citation intelligence over the slice-6 fixture world."""

import pytest
from bsi_core import models as m
from bsi_core.citations import sources
from bsi_core.db import tenant_session
from bsi_core.metrics import Filters
from sqlalchemy import select

from tests.integration.test_recommend import _mention, world  # noqa: F401


@pytest.fixture
def cited(owner, world):  # noqa: F811
    """The world, plus what the audit needs that the rules did not.

    nike.com becomes a declared brand domain, and Bata, a second active
    rival, is named in one forbes.com-citing answer. forbes.com is then
    the one gap: two rivals named, the brand never.
    """
    with owner() as s, s.begin():
        s.add(
            m.Domain(
                org_id=world.org.id, brand_id=world.brand, host="nike.com"
            )
        )
        bata = m.Competitor(
            org_id=world.org.id, brand_id=world.brand, name="Bata"
        )
        s.add(bata)
        s.flush()
        forbes_obs = s.scalars(
            select(m.Citation.observation_id)
            .where(m.Citation.domain == "forbes.com")
            .order_by(m.Citation.observation_id)
        ).first()
        s.add(_mention(world.org, forbes_obs, "competitor", bata.id))
    return world


def by_domain(w, f=Filters()):
    with tenant_session(w.org.id) as s:
        return {r["domain"]: r for r in sources(s, w.brand, f)}


def test_every_cited_domain_is_listed_most_cited_first(cited):
    with tenant_session(cited.org.id) as s:
        rows = sources(s, cited.brand, Filters())
    assert [r["domain"] for r in rows] == [
        "forbes.com",  # 5 answers
        "adidas.co.in",  # 5
        "blog.com",  # 4
        "four.com",  # 4
        "nike.com",  # 2
        "rare.com",  # 2
    ]
    assert [r["answers"] for r in rows] == [5, 5, 4, 4, 2, 2]


def test_gap_needs_two_rivals_and_no_brand(cited):
    rows = by_domain(cited)
    forbes = rows["forbes.com"]
    assert (forbes["brand_named"], forbes["prompts"]) == (0, 2)
    assert forbes["rivals"] == [
        {"name": "Adidas", "answers": 5},
        {"name": "Bata", "answers": 1},
    ]
    assert forbes["gap"] is True
    # blog.com: the brand is named in 3 of its 4 answers.
    assert rows["blog.com"]["brand_named"] == 3
    assert rows["blog.com"]["rivals"] == [{"name": "Adidas", "answers": 1}]
    assert rows["blog.com"]["gap"] is False
    # four.com: brand never named, but only one rival -> not a gap.
    assert rows["four.com"]["brand_named"] == 0
    assert rows["four.com"]["gap"] is False
    assert {r["gap"] for d, r in rows.items() if d != "forbes.com"} == {
        False
    }


def test_owner_is_read_live_from_declared_domains(cited):
    rows = by_domain(cited)
    assert (rows["nike.com"]["owner"], rows["nike.com"]["source_type"]) == (
        "brand",
        "vendor",
    )
    assert rows["adidas.co.in"]["owner"] == "rival"
    assert rows["forbes.com"]["owner"] == "third_party"
    assert rows["forbes.com"]["source_type"] == "other"


def test_seen_range_and_evidence_links(cited):
    forbes = by_domain(cited)["forbes.com"]
    assert forbes["first_seen"] <= forbes["last_seen"]
    assert len(forbes["observation_ids"]) == 5
    # Every linked answer really cites the domain.
    with tenant_session(cited.org.id) as s:
        citing = set(
            s.scalars(
                select(m.Citation.observation_id).where(
                    m.Citation.domain == "forbes.com"
                )
            )
        )
    assert set(forbes["observation_ids"]) <= citing


def test_filters_apply(cited):
    only_present = by_domain(cited, Filters(prompt_ids=[cited.present]))
    assert only_present["forbes.com"]["answers"] == 1
    assert only_present["forbes.com"]["prompts"] == 1
    assert "four.com" not in only_present  # cited on `dominated` only


def test_empty_brand_gives_empty_list(make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    with tenant_session(org.id) as s:
        assert sources(s, bid, Filters()) == []
```

- [ ] **Step 4: Run the integration test to see it fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_citations.py`
Expected: `ModuleNotFoundError: No module named 'bsi_core.citations'`

- [ ] **Step 5: Implement `citations.py`**

```python
"""Citation intelligence: who the engine cites, per domain (PRD F06).

Read-only SQL over the citations already stored. Nothing here fetches a
cited page: the stored URL is a Vertex redirect and no title is kept.
"""

import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from . import models as m
from .matching import is_owned
from .metrics import Filters, _where
from .recommend import _rival_domains

OWNERS = ("brand", "rival", "third_party")
SOURCE_TYPES = ("vendor", "video", "community", "review", "other")
# ponytail: a keyword heuristic, labelled as such in the API. A licensed
# source classifier would replace this table, not the callers.
_KEYWORDS = {
    "video": ("youtube", "vimeo"),
    "community": ("reddit", "quora", "stackexchange"),
    "review": ("review", "g2.com", "capterra", "trustpilot", "mouthshut"),
}
EVIDENCE_CAP = 20


def source_type(domain: str, owner: str) -> str:
    if owner != "third_party":
        return "vendor"
    for kind, words in _KEYWORDS.items():
        if any(w in domain for w in words):
            return kind
    return "other"


def sources(
    s: Session, brand_id: uuid.UUID, f: Filters
) -> list[dict[str, Any]]:
    """One row per cited domain, most cited first.

    Uses metrics._where so the page agrees with the citation-rate tile:
    every done answer counts, whatever its prompt's status. `gap` is PRD
    F06's definition - two or more active rivals named in the citing
    answers, the brand never.
    """
    where, params = _where(brand_id, f)
    base = (
        "FROM citation c JOIN observation o ON o.id = c.observation_id "
        f"WHERE {where} AND o.status = 'done'"
    )
    totals = s.execute(
        text(
            "SELECT c.domain, count(DISTINCT o.id) AS answers, "
            "count(DISTINCT o.prompt_id) AS prompts, "
            "min(o.requested_at) AS first_seen, "
            "max(o.requested_at) AS last_seen, "
            "count(DISTINCT o.id) FILTER (WHERE EXISTS ("
            "  SELECT 1 FROM mention mn WHERE mn.observation_id = o.id "
            "  AND mn.entity_type = 'brand')) AS brand_named "
            f"{base} GROUP BY c.domain "
            "ORDER BY count(DISTINCT o.id) DESC, c.domain"
        ),
        params,
    ).all()
    if not totals:
        return []
    rivals: dict[str, list[dict[str, Any]]] = {}
    for domain, name, k in s.execute(
        text(
            "SELECT c.domain, cp.name, count(DISTINCT o.id) "
            "FROM citation c JOIN observation o ON o.id = c.observation_id "
            "JOIN mention mn ON mn.observation_id = o.id "
            "  AND mn.entity_type = 'competitor' "
            "JOIN competitor cp ON cp.id = mn.entity_id "
            "  AND cp.status = 'active' "
            f"WHERE {where} AND o.status = 'done' "
            "GROUP BY c.domain, cp.name ORDER BY c.domain, 3 DESC, 2"
        ),
        params,
    ).all():
        rivals.setdefault(domain, []).append({"name": name, "answers": k})
    evidence: dict[str, list[uuid.UUID]] = {}
    for domain, oid, _ in s.execute(
        text(
            f"SELECT DISTINCT c.domain, o.id, o.requested_at {base} "
            "ORDER BY c.domain, o.requested_at DESC, o.id"
        ),
        params,
    ).all():
        ids = evidence.setdefault(domain, [])
        if len(ids) < EVIDENCE_CAP:
            ids.append(oid)
    hosts = list(
        s.scalars(select(m.Domain.host).where(m.Domain.brand_id == brand_id))
    )
    rival_hosts = _rival_domains(s, brand_id)
    out = []
    for r in totals:
        owner = (
            "brand"
            if is_owned(r.domain, hosts)
            else "rival"
            if is_owned(r.domain, rival_hosts)
            else "third_party"
        )
        named = rivals.get(r.domain, [])
        out.append(
            {
                "domain": r.domain,
                "owner": owner,
                "source_type": source_type(r.domain, owner),
                "answers": r.answers,
                "prompts": r.prompts,
                "first_seen": r.first_seen,
                "last_seen": r.last_seen,
                "brand_named": r.brand_named,
                "rivals": named,
                "gap": r.brand_named == 0 and len(named) >= 2,
                "observation_ids": evidence.get(r.domain, []),
            }
        )
    return out
```

- [ ] **Step 6: Run both tests until green**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_citations_source_type.py tests/integration/test_citations.py`
Expected: all pass. If `test_every_cited_domain_is_listed_most_cited_first` disagrees on tie order, the ORDER BY is `count DESC, c.domain`: `adidas.co.in` < `forbes.com` alphabetically, so the expected list must be `["adidas.co.in", "forbes.com", "blog.com", "four.com", "nike.com", "rare.com"]` — fix the **test** to that order (the fixture docstring says both are cited five times).

- [ ] **Step 7: Mutation check the gap rule**

Temporarily change `len(named) >= 2` to `>= 1`; run `tests/integration/test_citations.py::test_gap_needs_two_rivals_and_no_brand`; expected FAIL on `four.com`. Restore.

- [ ] **Step 8: Gate and commit**

Run the backend gate. Then:

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/citations.py tests/unit/test_citations_source_type.py tests/integration/test_citations.py && git commit -q -F - <<'EOF'
feat(core): per-domain citation sources with gap detection

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 2: `GET /brands/{id}/citations`

**Files:**
- Create: `apps/api/bsi_api/routers/citations.py`
- Modify: `apps/api/bsi_api/schemas.py` (append), `apps/api/bsi_api/main.py:7-18,39-52`, `tests/integration/test_isolation.py:95-138`, `apps/web/src/lib/types.ts`
- Test: `tests/integration/test_api_citations.py`
- Generated: `apps/web/openapi.json`, `apps/web/src/lib/schema.d.ts`

**Interfaces:**
- Consumes: `citations.sources`, `metrics.filters` dependency (`apps/api/bsi_api/routers/metrics.py:27-34`).
- Produces: `SourceOut` / `RivalOut` schemas; route `GET /v1/brands/{brand_id}/citations` → `list[SourceOut]`.

- [ ] **Step 1: Write the failing API test**

`tests/integration/test_api_citations.py`:

```python
from tests.integration.test_citations import cited  # noqa: F401
from tests.integration.test_recommend import world  # noqa: F401


def test_citations_endpoint_lists_domains(client, cited):  # noqa: F811
    r = client.get(
        f"/v1/brands/{cited.brand}/citations", headers=cited.org.headers
    )
    assert r.status_code == 200, r.text
    rows = {x["domain"]: x for x in r.json()}
    forbes = rows["forbes.com"]
    assert forbes["gap"] is True
    assert forbes["owner"] == "third_party"
    assert forbes["rivals"][0] == {"name": "Adidas", "answers": 5}
    assert len(forbes["observation_ids"]) == 5
    assert forbes["first_seen"] and forbes["last_seen"]


def test_citations_endpoint_honours_filters(client, cited):  # noqa: F811
    r = client.get(
        f"/v1/brands/{cited.brand}/citations?prompt_ids={cited.present}",
        headers=cited.org.headers,
    )
    assert {x["domain"] for x in r.json()} == {
        "blog.com",
        "forbes.com",
        "adidas.co.in",
    }


def test_unknown_brand_is_404(client, make_org):
    org = make_org()
    r = client.get(
        "/v1/brands/00000000-0000-0000-0000-000000000000/citations",
        headers=org.headers,
    )
    assert r.status_code == 404
```

Check how `world`'s org exposes headers: `make_org` returns a `SimpleNamespace` with `headers` (see `tests/conftest.py:57`). If the attribute is named differently, use that name.

- [ ] **Step 2: Run it to see it fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_api_citations.py`
Expected: 404s / assertion failures because the route does not exist.

- [ ] **Step 3: Add the schemas**

Append to `apps/api/bsi_api/schemas.py`:

```python
class RivalOut(BaseModel):
    name: str
    answers: int


class SourceOut(BaseModel):
    """One cited domain. `source_type` is a keyword heuristic."""

    domain: str
    owner: Literal["brand", "rival", "third_party"]
    source_type: Literal["vendor", "video", "community", "review", "other"]
    answers: int
    prompts: int
    first_seen: datetime
    last_seen: datetime
    brand_named: int
    rivals: list[RivalOut]
    gap: bool
    observation_ids: list[uuid.UUID]
```

(`Literal`, `datetime`, `uuid` are already imported in `schemas.py`; if not, add them.)

- [ ] **Step 4: Write the router**

`apps/api/bsi_api/routers/citations.py`:

```python
"""Citation intelligence: which domains the engine cites for the brand."""

import uuid
from typing import Any

from bsi_core.citations import sources
from bsi_core.metrics import Filters
from fastapi import APIRouter, Depends

from ..deps import TENANT, Ctx, brand_or_404
from ..schemas import SourceOut
from .metrics import filters

router = APIRouter(prefix="/brands/{brand_id}", tags=["citations"])


@router.get("/citations", response_model=list[SourceOut])
def list_citations(
    brand_id: uuid.UUID, f: Filters = Depends(filters), c: Ctx = TENANT
) -> list[dict[str, Any]]:
    brand_or_404(c, brand_id)
    return sources(c.s, brand_id, f)
```

Register it in `apps/api/bsi_api/main.py`: add `citations,` to the import tuple and `citations.router,` to the loop.

- [ ] **Step 5: Isolation row**

Append to `CASES` in `tests/integration/test_isolation.py`:

```python
    ("GET", "/v1/brands/{b}/citations", None),
```

- [ ] **Step 6: Run the tests**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_api_citations.py tests/integration/test_isolation.py`
Expected: PASS.

- [ ] **Step 7: Regenerate types, add the alias, gate**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gen
```
Add to `apps/web/src/lib/types.ts`: `export type Source = S["SourceOut"];`
Then `git add apps/web/openapi.json apps/web/src/lib/schema.d.ts apps/web/src/lib/types.ts`, run both gates.

- [ ] **Step 8: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add -A && git commit -q -F - <<'EOF'
feat(api): GET /brands/{id}/citations

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 3: Citations tab

**Files:**
- Create: `apps/web/src/app/(app)/b/[id]/citations/page.tsx`
- Modify: `apps/web/src/app/(app)/b/[id]/layout.tsx:18-24`

**Interfaces:**
- Consumes: `Source` type, `api<T>`, `apiQuery`, `Filters` component (`apps/web/src/components/Filters.tsx`), `Params`.
- Produces: the page only.

- [ ] **Step 1: Add the tab**

In `layout.tsx`, after the Prompts link:
```tsx
        <Link href={`/b/${id}/citations`}>Citations</Link>
```

- [ ] **Step 2: Write the page**

`apps/web/src/app/(app)/b/[id]/citations/page.tsx`:

```tsx
import Link from "next/link";
import { Filters } from "@/components/Filters";
import { api } from "@/lib/api";
import { apiQuery, type Params } from "@/lib/format";
import type { Source } from "@/lib/types";

// Sort keys the page offers; the API already orders by answers.
const KEYS: Record<string, (r: Source) => number> = {
  answers: (r) => r.answers,
  prompts: (r) => r.prompts,
  last_seen: (r) => Date.parse(r.last_seen),
};

export default async function Citations({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  let rows = await api<Source[]>(`/brands/${id}/citations${apiQuery(sp)}`);
  const gapOnly = sp.gap === "1";
  if (gapOnly) rows = rows.filter((r) => r.gap);
  const sort = typeof sp.sort === "string" && sp.sort in KEYS ? sp.sort : "answers";
  const dir = sp.dir === "asc" ? 1 : -1;
  const key = KEYS[sort];
  rows.sort((a, b) => (key(a) - key(b)) * dir || a.domain.localeCompare(b.domain));
  const head = (k: string, label: string) => {
    const q = new URLSearchParams();
    for (const [n, v] of Object.entries(sp)) if (typeof v === "string") q.set(n, v);
    q.set("sort", k);
    q.set("dir", sort === k && dir === -1 ? "asc" : "desc");
    return <Link href={`?${q}`}>{label}</Link>;
  };
  const gaps = rows.filter((r) => r.gap).length;
  return (
    <>
      <Filters sp={sp} />
      <form method="get" className="filters">
        {Object.entries(sp).map(([n, v]) =>
          typeof v === "string" && n !== "gap" ? (
            <input key={n} type="hidden" name={n} value={v} />
          ) : null,
        )}
        <label>
          <input type="checkbox" name="gap" value="1" defaultChecked={gapOnly} />{" "}
          Gaps only
        </label>
        <button>Apply</button>
      </form>
      <p className="muted">
        {rows.length} domains · {gaps} gaps (cite two or more rivals, never the
        brand) · source type is a keyword guess
      </p>
      {rows.length === 0 && <p>No citations for these filters.</p>}
      {rows.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Domain</th>
              <th>Type</th>
              <th>{head("answers", "Answers")}</th>
              <th>{head("prompts", "Prompts")}</th>
              <th>Brand named</th>
              <th>Rivals named</th>
              <th>{head("last_seen", "Last seen")}</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.domain}>
                <td>
                  {r.domain}{" "}
                  {r.owner !== "third_party" && <span className="tag">{r.owner}</span>}{" "}
                  {r.gap && <span className="tag down">gap</span>}
                </td>
                <td>{r.source_type}</td>
                <td>{r.answers}</td>
                <td>{r.prompts}</td>
                <td>{r.brand_named}</td>
                <td>{r.rivals.map((x) => `${x.name} (${x.answers})`).join(", ")}</td>
                <td>{r.last_seen.slice(0, 10)}</td>
                <td>
                  {r.observation_ids.slice(0, 3).map((o, i) => (
                    <span key={o}>
                      {i > 0 && " · "}
                      <Link href={`/o/${o}`}>{i + 1}</Link>
                    </span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
```

- [ ] **Step 3: Gate**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate`. Expected: exit 0, zero warnings. If ESLint complains about the `||` sort expression, split it into an `if`.

- [ ] **Step 4: Look at it**

Start the API (`uv run uvicorn bsi_api.main:app --port 8000`, env sourced) and `npm run dev`; log in with the Run 1 key (`bsi_d4bffda8357293d18944a77797e4a98920431e91d97bfc577a81b2b3d69fc0b3`), open `/b/34db213a-f484-4991-a969-c52cfa5e1c10/citations`, tick "Gaps only", sort by prompts. Confirm the table renders and evidence links open `/o/…`. Stop both servers.

- [ ] **Step 5: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add -A && git commit -q -F - <<'EOF'
feat(web): Citations tab with gap filter

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 4: `crawl.py` — the checks, from canned responses

**Files:**
- Create: `packages/core/bsi_core/crawl.py`
- Modify: `packages/core/pyproject.toml:5-13` (add `"httpx>=0.28",`), then `uv sync`
- Test: `tests/unit/test_crawl.py`

**Interfaces:**
- Produces:
  - `@dataclass Response(status: int, body: str = "", error: str | None = None)`
  - `Fetch = Callable[[str, str], Response]` — `(url, user_agent)`
  - `@dataclass Check(code: str, ok: bool, severity: str, observed: str, expected: str, url: str)`
  - `class Audit(NamedTuple): checks: list[Check]; fetches: int`
  - `audit_domain(host: str, fetch: Fetch, *, pause: float = 0.0) -> Audit`
  - `http_fetch(url: str, user_agent: str) -> Response`
  - `BOTS: tuple[str, ...]`, `BROWSER_UA: str`, `PAUSE_SECONDS = 0.5`, `SEVERITY: dict[str, str]`, `EXPECTED: dict[str, str]`, `severity(code) -> str`, `expected(code) -> str`, `family(code) -> str` (the part before `:`).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_crawl.py`:

```python
"""audit_domain from canned responses. Nothing here touches the network."""

import pytest
from bsi_core.crawl import (
    BOTS,
    BROWSER_UA,
    Response,
    audit_domain,
    expected,
    family,
    severity,
)

HOME = """<html><head><title>Nike</title>
<meta name="description" content="Shoes">
<link rel="canonical" href="https://nike.com/">
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[{"@type":["Organization","Brand"],"name":"Nike"}]}
</script></head><body><h1>Nike</h1></body></html>"""

ROBOTS_OPEN = "User-agent: *\nDisallow:\nSitemap: https://nike.com/sm.xml\n"
ROBOTS_BLOCK = (
    "User-agent: *\nDisallow: /private\n\n"
    "User-agent: GPTBot\nUser-agent: ClaudeBot\nDisallow: /\n"
)
SITEMAP = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://nike.com/</loc></url></urlset>'
INDEX = '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://nike.com/a.xml</loc></sitemap></sitemapindex>'


def site(pages, *, blocked_uas=()):
    """A fetch over a dict of path -> Response; records every call."""
    calls = []

    def fetch(url, ua):
        calls.append((url, ua))
        path = url.split("nike.com", 1)[1] or "/"
        if path == "/" and ua in blocked_uas:
            return Response(403, "blocked")
        return pages.get(path, Response(404, ""))

    fetch.calls = calls
    return fetch


GOOD = {
    "/": Response(200, HOME),
    "/robots.txt": Response(200, ROBOTS_OPEN),
    "/sm.xml": Response(200, SITEMAP),
    "/llms.txt": Response(200, "# Nike"),
}


def codes(audit, ok):
    return sorted(c.code for c in audit.checks if c.ok is ok)


def test_a_healthy_site_passes_every_check():
    audit = audit_domain("nike.com", site(GOOD))
    assert codes(audit, False) == []
    assert set(codes(audit, True)) >= {
        "home_unreachable",
        "title_missing",
        "description_missing",
        "h1_missing",
        "canonical_missing",
        "org_schema_missing",
        "sitemap_missing",
        "sitemap_invalid",
        "llms_missing",
        *[f"bot_blocked:{b}" for b in BOTS],
        *[f"bot_ua_blocked:{b}" for b in BOTS],
    }
    # 1 home + 1 robots + 8 bot UAs + 1 sitemap + 1 llms.txt
    assert audit.fetches == 12


def test_fetch_count_and_order_are_deterministic():
    fetch = site(GOOD)
    audit_domain("nike.com", fetch)
    urls = [u for u, _ in fetch.calls]
    assert urls[0] == "https://nike.com/"
    assert fetch.calls[0][1] == BROWSER_UA
    assert urls[1] == "https://nike.com/robots.txt"
    assert urls[2:10] == ["https://nike.com/"] * 8
    assert [ua for _, ua in fetch.calls[2:10]] == list(BOTS)
    assert urls[10] == "https://nike.com/sm.xml"  # from the robots Sitemap line
    assert urls[11] == "https://nike.com/llms.txt"


def test_robots_groups_block_named_bots_only():
    pages = {**GOOD, "/robots.txt": Response(200, ROBOTS_BLOCK)}
    audit = audit_domain("nike.com", site(pages))
    assert codes(audit, False) == [
        "bot_blocked:ClaudeBot",
        "bot_blocked:GPTBot",
        "sitemap_missing",  # no Sitemap line and /sitemap.xml is 404
    ]
    blocked = next(c for c in audit.checks if c.code == "bot_blocked:GPTBot")
    assert "Disallow: /" in blocked.observed
    assert blocked.severity == "high"
    assert blocked.url == "https://nike.com/robots.txt"


def test_missing_robots_allows_every_bot():
    pages = {k: v for k, v in GOOD.items() if k != "/robots.txt"}
    pages["/sitemap.xml"] = Response(200, INDEX)
    audit = audit_domain("nike.com", site(pages))
    assert codes(audit, False) == []
    urls = [u for u, _ in site(pages).calls]  # fresh fetch: no calls yet
    assert urls == []


def test_cdn_blocking_only_counts_when_the_browser_got_through():
    audit = audit_domain(
        "nike.com", site(GOOD, blocked_uas=("PerplexityBot", "Bingbot"))
    )
    assert codes(audit, False) == [
        "bot_ua_blocked:Bingbot",
        "bot_ua_blocked:PerplexityBot",
    ]
    down = {**GOOD, "/": Response(503, "")}
    audit = audit_domain("nike.com", site(down, blocked_uas=BOTS))
    # Home is down for everyone: that is home_unreachable, not eight
    # CDN blocks, and the on-page checks are skipped.
    assert codes(audit, False) == ["home_unreachable"]
    assert "title_missing" not in codes(audit, True)


def test_on_page_checks_fail_individually():
    bare = "<html><head></head><body><p>hi</p></body></html>"
    audit = audit_domain("nike.com", site({**GOOD, "/": Response(200, bare)}))
    assert codes(audit, False) == [
        "canonical_missing",
        "description_missing",
        "h1_missing",
        "org_schema_missing",
        "title_missing",
    ]


def test_org_schema_is_found_in_a_plain_object_and_a_list():
    plain = HOME.replace(
        '{"@context":"https://schema.org","@graph":[{"@type":["Organization","Brand"],"name":"Nike"}]}',
        '{"@type":"Organization","name":"Nike"}',
    )
    listed = HOME.replace(
        '{"@context":"https://schema.org","@graph":[{"@type":["Organization","Brand"],"name":"Nike"}]}',
        '[{"@type":"WebSite"},{"@type":"Organization"}]',
    )
    for body in (plain, listed):
        audit = audit_domain("nike.com", site({**GOOD, "/": Response(200, body)}))
        assert "org_schema_missing" not in codes(audit, False)
    broken = HOME.replace('"name":"Nike"', '"name":')  # invalid JSON
    audit = audit_domain("nike.com", site({**GOOD, "/": Response(200, broken)}))
    assert "org_schema_missing" in codes(audit, False)


def test_sitemap_index_is_valid_and_junk_is_not():
    pages = {**GOOD, "/sm.xml": Response(200, INDEX)}
    assert codes(audit_domain("nike.com", site(pages)), False) == []
    pages = {**GOOD, "/sm.xml": Response(200, "<html>not a sitemap</html>")}
    audit = audit_domain("nike.com", site(pages))
    assert codes(audit, False) == ["sitemap_invalid"]
    pages = {**GOOD, "/sm.xml": Response(200, "<<<")}
    assert codes(audit_domain("nike.com", site(pages)), False) == [
        "sitemap_invalid"
    ]


def test_a_fetch_error_is_a_failed_check_not_an_exception():
    def fetch(url, ua):
        return Response(0, "", "ConnectError('boom')")

    audit = audit_domain("nike.com", fetch)
    assert codes(audit, False) == ["home_unreachable"]
    home = audit.checks[0]
    assert "ConnectError" in home.observed


def test_observed_is_capped_and_body_over_the_cap_still_parses():
    long_title = "<title>" + "x" * 5000 + "</title>"
    body = HOME.replace("<title>Nike</title>", long_title)
    audit = audit_domain("nike.com", site({**GOOD, "/": Response(200, body)}))
    assert all(len(c.observed) <= 300 for c in audit.checks)
    assert "title_missing" not in codes(audit, False)


def test_llms_txt_is_low_severity_and_says_unofficial():
    pages = {k: v for k, v in GOOD.items() if k != "/llms.txt"}
    audit = audit_domain("nike.com", site(pages))
    llms = next(c for c in audit.checks if c.code == "llms_missing")
    assert (llms.ok, llms.severity) == (False, "low")
    assert "unofficial" in llms.expected


@pytest.mark.parametrize(
    ("code", "sev"),
    [
        ("home_unreachable", "high"),
        ("bot_blocked:GPTBot", "high"),
        ("bot_ua_blocked:Bingbot", "high"),
        ("sitemap_missing", "medium"),
        ("sitemap_invalid", "medium"),
        ("org_schema_missing", "medium"),
        ("title_missing", "low"),
        ("llms_missing", "low"),
    ],
)
def test_severity_and_expected_are_defined_for_every_code(code, sev):
    assert severity(code) == sev
    assert expected(code)
    assert family("bot_blocked:GPTBot") == "bot_blocked"


def test_pause_is_applied_between_fetches(monkeypatch):
    slept = []
    monkeypatch.setattr("bsi_core.crawl.time.sleep", slept.append)
    audit_domain("nike.com", site(GOOD), pause=0.5)
    assert slept == [0.5] * 11  # between 12 fetches
```

- [ ] **Step 2: Run to see them fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_crawl.py`
Expected: `ModuleNotFoundError: No module named 'bsi_core.crawl'`

- [ ] **Step 3: Declare httpx and write `crawl.py`**

In `packages/core/pyproject.toml` add `"httpx>=0.28",` to `dependencies`, then `cd /Users/vineet/Downloads/ADK/bsi-platform && uv sync`.

`packages/core/bsi_core/crawl.py`:

```python
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


def _types(node: Any) -> set[str]:
    """Every @type in a JSON-LD document, including inside @graph."""
    found: set[str] = set()
    if isinstance(node, dict):
        t = node.get("@type")
        found.update([t] if isinstance(t, str) else t or [])
        for v in node.values():
            found |= _types(v)
    elif isinstance(node, list):
        for v in node:
            found |= _types(v)
    return found


def _has_org(scripts: list[str]) -> bool:
    for script in scripts:
        try:
            if "Organization" in _types(json.loads(script)):
                return True
        except ValueError:
            continue
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
            if out and not agents:  # a new group after rules
                pass
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
            Check(code, ok, severity(code), _clip(observed), expected(code), url)
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
            add(code, bool(value and value.strip()), value or "absent", home_url)
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
        add(f"bot_blocked:{bot}", allowed, observed or "no matching group", robots_url)

    for bot in BOTS:
        r = get(home_url, bot)
        blocked = home.ok and (r.status in BLOCKED or r.status >= 500)
        add(
            f"bot_ua_blocked:{bot}",
            not blocked,
            r.error or f"HTTP {r.status}",
            home_url,
        )

    sitemaps = (rp.site_maps() or [f"https://{host}/sitemap.xml"]) if robots.ok else [f"https://{host}/sitemap.xml"]
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
```

Tidy the two over-long lines (`sitemaps = …`, the `add(f"bot_blocked…` call) to fit 80 columns; `ruff format` will wrap most of it. In `_group_lines`, delete the no-op `if out and not agents: pass` branch.

- [ ] **Step 4: Run the tests**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_crawl.py`
Expected: all pass. Likely fixes:
- `test_missing_robots_allows_every_bot`: with no robots.txt the code fetches `/sitemap.xml` — the test's `pages` provides it. If `rp.parse([])` still reports disallow, call `rp.allow_all = True` instead.
- `test_fetch_count_and_order…`: the home is fetched first, then robots, then eight bot UAs, then the sitemap, then llms — matching the implementation order above.
- `test_pause…`: 12 fetches → 11 pauses.

- [ ] **Step 5: Mutation check**

Temporarily remove `"Bingbot"` from `BOTS`; `test_a_healthy_site_passes_every_check` must fail on the fetch count (11 ≠ 12) and `test_fetch_count_and_order…` on the UA list. Restore.

- [ ] **Step 6: Gate and commit**

Run the backend gate (mypy strict covers `bsi_core`; fix any `Any`-typing complaints on `_types`). Then:

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/pyproject.toml uv.lock packages/core/bsi_core/crawl.py tests/unit/test_crawl.py && git commit -q -F - <<'EOF'
feat(core): crawlability checks for a brand domain

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 5: `site_audit` table, `due_crawl_audits()`, fifth recommendation type

**Files:**
- Create: `migrations/versions/0012_site_audit_and_crawlability.py`
- Modify: `packages/core/bsi_core/models.py:38-44` (`REC_TYPES`), append `SiteAudit` after `Task`
- Modify: `tests/integration/test_rls.py:10-28` and the `org_b` fixture; `tests/integration/test_constraints.py` (no change needed — it is parametrized over `REC_TYPES`)
- Test: `tests/integration/test_crawl_audit.py` (the due-function part; the worker part is Task 6)

**Interfaces:**
- Produces: `m.SiteAudit(org_id, brand_id, job_id | None, domain, checks: list[dict], fetches: int)`; SQL `due_crawl_audits() RETURNS TABLE(brand_id uuid, org_id uuid)`; `REC_TYPES` includes `"fix_crawlability"`.

- [ ] **Step 1: Model changes**

In `models.py`, `REC_TYPES`:
```python
REC_TYPES = (
    "pursue_citation_source",
    "create_content",
    "add_competitor",
    "sample_more",
    "fix_crawlability",
)
```
Append after `Task`:
```python
class SiteAudit(Tenant, Base):
    """One crawlability audit of one brand domain; the latest row per
    domain is what the Site tab and the fix_crawlability rule read."""

    __tablename__ = "site_audit"
    brand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("brand.id"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("job.id"))
    domain: Mapped[str]
    checks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default="[]"
    )
    fetches: Mapped[int] = mapped_column(server_default="0")
    __table_args__ = (
        Index("ix_site_audit_latest", "brand_id", "domain", "created_at"),
    )
```

- [ ] **Step 2: Write the migration**

`migrations/versions/0012_site_audit_and_crawlability.py`:

```python
"""site_audit table, due_crawl_audits(), fix_crawlability rec type"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"
OLD_TYPES = "'pursue_citation_source', 'create_content', 'add_competitor', 'sample_more'"
NEW_TYPES = OLD_TYPES + ", 'fix_crawlability'"
AUDIT_DAYS = 7


def _protect(table: str) -> None:
    op.create_index(f"ix_{table}_org_id", table, ["org_id"])
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant ON {table} "
        f"USING (org_id = {SETTING}) WITH CHECK (org_id = {SETTING})"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO bsi_app")


def _rec_type_check(values: str) -> None:
    op.drop_constraint("ck_recommendation_type", "recommendation")
    op.create_check_constraint(
        "ck_recommendation_type", "recommendation", f"type IN ({values})"
    )


def upgrade() -> None:
    op.create_table(
        "site_audit",
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
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column(
            "checks",
            postgresql.JSONB(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("fetches", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["brand_id"], ["brand.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["job.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_site_audit_latest",
        "site_audit",
        ["brand_id", "domain", "created_at"],
    )
    _protect("site_audit")
    op.execute(f"""
        CREATE FUNCTION due_crawl_audits()
        RETURNS TABLE(brand_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          SELECT b.id, b.org_id FROM brand b
          LEFT JOIN (SELECT a.brand_id, max(a.created_at) AS last
                     FROM site_audit a GROUP BY a.brand_id) a
            ON a.brand_id = b.id
          WHERE b.status = 'active'
            AND EXISTS (SELECT 1 FROM domain d WHERE d.brand_id = b.id)
            AND (a.last IS NULL
                 OR a.last <= now() - make_interval(days => {AUDIT_DAYS}))
          ORDER BY a.last NULLS FIRST, b.id
        $$""")
    op.execute("REVOKE ALL ON FUNCTION due_crawl_audits() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_crawl_audits() TO bsi_app")
    _rec_type_check(NEW_TYPES)


def downgrade() -> None:
    _rec_type_check(OLD_TYPES)
    op.execute("DROP FUNCTION due_crawl_audits()")
    op.drop_index("ix_site_audit_latest", table_name="site_audit")
    op.drop_table("site_audit")
```

Check the FK column type name for `organization` matches 0009 (it uses `sa.ForeignKeyConstraint(["org_id"], ["organization.id"])`); copy exactly what 0009 does for its `org_id` FK.

- [ ] **Step 3: Apply and check**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && uv run alembic upgrade head && uv run alembic check
```
Expected: `No new upgrade operations detected.` If `alembic check` wants an index or type tweak, align the migration to the model (not the other way round).

- [ ] **Step 4: RLS fixture and table list**

In `tests/integration/test_rls.py`, append `"site_audit",` to `TENANT_TABLES`, and in the `org_b` fixture's final `with owner() as s, s.begin():` block (after the `m.Task(...)` add) add:

```python
        s.add(
            m.SiteAudit(
                org_id=b.id,
                brand_id=bid,
                domain="b.com",
                checks=[{"code": "llms_missing", "ok": False}],
            )
        )
```

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_rls.py tests/integration/test_constraints.py`
Expected: PASS (the constraints test now sees five types in both places).

- [ ] **Step 5: Due-function tests**

`tests/integration/test_crawl_audit.py` (first half; Task 6 appends the worker tests):

```python
"""The crawl audit: what is due, and what the worker stores."""

from datetime import UTC, datetime, timedelta

from bsi_core import models as m
from bsi_core.db import system_session
from sqlalchemy import func, select, text, update


def _domain(owner, org, bid, host="nike.com"):
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host=host))


def _audit(owner, org, bid, days_ago, host="nike.com"):
    with owner() as s, s.begin():
        a = m.SiteAudit(org_id=org.id, brand_id=bid, domain=host, checks=[])
        s.add(a)
        s.flush()
        s.execute(
            update(m.SiteAudit)
            .where(m.SiteAudit.id == a.id)
            .values(
                created_at=func.now() - func.make_interval(0, 0, 0, days_ago)
            )
        )


def due():
    with system_session() as s:
        return [
            r[0]
            for r in s.execute(text("SELECT brand_id FROM due_crawl_audits()"))
        ]


def test_a_brand_with_domains_and_no_audit_is_due(owner, make_org, make_brand):
    org = make_org()
    bare = make_brand(org, "NoDomains")
    bid = make_brand(org, "Nike")
    _domain(owner, org, bid)
    assert due() == [bid]
    assert bare not in due()


def test_due_again_after_seven_days(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _domain(owner, org, bid)
    _audit(owner, org, bid, 6)
    assert due() == []
    _audit(owner, org, bid, 8)  # an older row does not make it due...
    assert due() == []  # ...the latest row is what counts
    with owner() as s, s.begin():
        s.execute(
            update(m.SiteAudit).values(
                created_at=func.now() - func.make_interval(0, 0, 0, 8)
            )
        )
    assert due() == [bid]


def test_archived_brands_are_never_due(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _domain(owner, org, bid)
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand).where(m.Brand.id == bid).values(status="archived")
        )
    assert due() == []


def test_due_serves_every_tenant_oldest_first(owner, make_org, make_brand):
    a = make_org("A")
    b = make_org("B")
    ba = make_brand(a)
    bb = make_brand(b)
    _domain(owner, a, ba)
    _domain(owner, b, bb)
    _audit(owner, a, ba, 30)
    assert due() == [bb, ba]  # never-audited first, then the oldest
```

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_crawl_audit.py`
Expected: PASS. (If `make_brand` needs the second positional as name — it does: `_make(org, name="Acme", …)`.)

- [ ] **Step 6: Mutation check the boundary**

Redefine the function in `bsi_test` with `days => 5` (see the 0011 session for the `psql` incantation, against `-d bsi_test`), run `test_due_again_after_seven_days`, expect FAIL at 6 days; then restore with `days => 7` **in `bsi_test`** (an `alembic downgrade/upgrade` targets the dev database, not the test one).

- [ ] **Step 7: Gate and commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add migrations/versions/0012_site_audit_and_crawlability.py packages/core/bsi_core/models.py tests/integration/test_rls.py tests/integration/test_crawl_audit.py && git commit -q -F - <<'EOF'
feat(db): site_audit table, due_crawl_audits(), fix_crawlability type

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 6: The `audit_crawl` job in the worker

**Files:**
- Modify: `packages/core/bsi_core/scheduling.py` (add `enqueue_job`), `apps/api/bsi_api/routers/runs.py:28-71` (`queue_suggestion` delegates), `apps/workers/bsi_workers/worker.py:41-44,273-318,315-343`
- Test: `tests/integration/test_crawl_audit.py` (append), `tests/integration/test_worker.py` (unchanged; must still pass)

**Interfaces:**
- Consumes: `crawl.audit_domain`, `crawl.http_fetch`, `crawl.Fetch`, `crawl.PAUSE_SECONDS`, `m.SiteAudit`.
- Produces: `scheduling.enqueue_job(s, org_id, brand_id, kind, params, slot=None) -> m.Job`; `worker.run_crawl_audit(org_id, brand_id, job_id, fetch) -> int` (domains audited); `worker.queue_due_crawl_audits() -> int`; `worker.process_job(adapter, generator, embedder, fetch=http_fetch)`; `worker.tick(..., fetch=http_fetch)`; `JOB_ESTIMATES["audit_crawl"] = 0`.

- [ ] **Step 1: Append the failing worker tests**

Append to `tests/integration/test_crawl_audit.py`:

```python
import bsi_workers.worker as worker
from bsi_core.crawl import Response
from bsi_core.scheduling import enqueue_job
from bsi_core.db import tenant_session
from tests.integration.test_worker import FakeAdapter, _job, _load_job, _spender


def _fake_fetch(pages=None):
    calls = []

    def fetch(url, ua):
        calls.append(url)
        return (pages or {}).get(url, Response(200, "<title>x</title>"))

    fetch.calls = calls
    return fetch


def test_audit_job_stores_one_row_per_domain(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _domain(owner, org, bid, "nike.com")
    _domain(owner, org, bid, "nike.in")
    job_id = _job(owner, org, bid, "audit_crawl", "queued")
    _, generator, embedder = _spender()
    fetch = _fake_fetch()
    assert worker.process_job(FakeAdapter(), generator, embedder, fetch=fetch)
    job = _load_job(owner, job_id)
    assert (job.status, job.error, job.cost_micros) == ("done", None, 0)
    with owner() as s:
        rows = s.scalars(
            select(m.SiteAudit).order_by(m.SiteAudit.domain)
        ).all()
    assert [(r.domain, r.job_id) for r in rows] == [
        ("nike.com", job_id),
        ("nike.in", job_id),
    ]
    assert rows[0].fetches == 12 and len(rows[0].checks) >= 20
    assert {c["code"] for c in rows[0].checks} >= {"home_unreachable"}
    # Everything the page needs is in the JSON, no dataclass leaked.
    assert set(rows[0].checks[0]) == {
        "code", "ok", "severity", "observed", "expected", "url"
    }
    assert fetch.calls[0] == "https://nike.com/"
    assert due() == []  # audited: not due again for a week


def test_a_brand_without_domains_finishes_with_no_rows(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    job_id = _job(owner, org, bid, "audit_crawl", "queued")
    _, generator, embedder = _spender()
    fetch = _fake_fetch()
    assert worker.process_job(FakeAdapter(), generator, embedder, fetch=fetch)
    assert _load_job(owner, job_id).status == "done"
    assert fetch.calls == []
    with owner() as s:
        assert s.scalars(select(m.SiteAudit)).all() == []


def test_a_raising_fetch_fails_the_check_not_the_job(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _domain(owner, org, bid)
    job_id = _job(owner, org, bid, "audit_crawl", "queued")
    _, generator, embedder = _spender()

    def fetch(url, ua):
        return Response(0, "", "ConnectError('down')")

    assert worker.process_job(FakeAdapter(), generator, embedder, fetch=fetch)
    assert _load_job(owner, job_id).status == "done"
    with owner() as s:
        row = s.scalars(select(m.SiteAudit)).one()
    home = next(c for c in row.checks if c["code"] == "home_unreachable")
    assert home["ok"] is False and "ConnectError" in home["observed"]


def test_no_transaction_is_open_while_fetching(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _domain(owner, org, bid)
    _job(owner, org, bid, "audit_crawl", "queued")
    _, generator, embedder = _spender()
    seen = []

    def fetch(url, ua):
        with owner() as s:
            seen.append(
                s.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE state = 'idle in transaction' "
                        "AND application_name = current_setting("
                        "'application_name')"
                    )
                )
            )
        return Response(200, "")

    worker.process_job(FakeAdapter(), generator, embedder, fetch=fetch)
    assert seen and set(seen) == {0}


def test_queue_due_crawl_audits_is_idempotent_within_the_hour(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _domain(owner, org, bid)
    assert worker.queue_due_crawl_audits() == 1
    assert worker.queue_due_crawl_audits() == 1  # counted, but no new row
    with owner() as s:
        jobs = s.scalars(select(m.Job).where(m.Job.kind == "audit_crawl")).all()
    assert len(jobs) == 1 and jobs[0].status == "queued"


def test_enqueue_job_requeues_only_a_failed_job(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    with tenant_session(org.id) as s:
        first = enqueue_job(s, org.id, bid, "audit_crawl", {})
        first_id, slot = first.id, first.scheduled_slot
    with owner() as s, s.begin():
        s.execute(
            update(m.Job).where(m.Job.id == first_id).values(status="done")
        )
    with tenant_session(org.id) as s:
        again = enqueue_job(s, org.id, bid, "audit_crawl", {}, slot=slot)
        assert (again.id, again.status) == (first_id, "done")
    with owner() as s, s.begin():
        s.execute(
            update(m.Job)
            .where(m.Job.id == first_id)
            .values(status="failed", error="x")
        )
    with tenant_session(org.id) as s:
        again = enqueue_job(s, org.id, bid, "audit_crawl", {"k": 1}, slot=slot)
        assert (again.status, again.error, again.params) == (
            "queued", None, {"k": 1}
        )
```

The `pg_stat_activity` probe: `application_name` may be empty for every connection, which makes the count include the probe's own session (which is *in* a transaction while querying). If `seen` comes back non-zero for that reason, change the probe to count `state = 'idle in transaction'` rows whose `pid <> pg_backend_pid()` — that is the exact intent.

- [ ] **Step 2: Run to see them fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_crawl_audit.py`
Expected: failures — `process_job()` has no `fetch` kwarg; `enqueue_job` and `queue_due_crawl_audits` do not exist; an `audit_crawl` job fails as "unknown kind".

- [ ] **Step 3: `enqueue_job` in core; `queue_suggestion` delegates**

In `packages/core/bsi_core/scheduling.py` add (imports `pg_insert` and `select` already exist there; `hour_slot` too):

```python
def enqueue_job(
    s: Session,
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    kind: str,
    params: dict[str, Any],
    slot: datetime | None = None,
) -> m.Job:
    """Find or create this hour's job for the brand and kind.

    One job per (brand, kind, hour), except that a failed job is requeued
    with the new params: one failure must not lock the caller out for the
    hour. Its cost_micros is left alone, so a retry accumulates. Used by
    the API for suggestions and audits, and by the worker's weekly pass.
    """
    slot = slot or hour_slot(datetime.now(UTC))
    s.execute(
        pg_insert(m.Job)
        .values(
            org_id=org_id,
            brand_id=brand_id,
            kind=kind,
            scheduled_slot=slot,
            status="queued",
            params=params,
        )
        .on_conflict_do_update(
            index_elements=["brand_id", "kind", "scheduled_slot"],
            set_={"status": "queued", "error": None, "params": params},
            where=m.Job.status == "failed",
        )
    )
    return s.scalars(
        select(m.Job).where(
            m.Job.brand_id == brand_id,
            m.Job.kind == kind,
            m.Job.scheduled_slot == slot,
        )
    ).one()
```

In `apps/api/bsi_api/routers/runs.py`, `queue_suggestion` becomes:

```python
def queue_suggestion(
    c: Ctx, brand_id: uuid.UUID, kind: str, params: dict[str, Any]
) -> dict[str, Any]:
    """Queue this hour's job for the brand; 409 on an archived brand."""
    if brand_or_404(c, brand_id).status == "archived":
        raise Problem(409, "Brand is archived", "Archived brands are not run.")
    job = enqueue_job(c.s, c.org_id, brand_id, kind, params)
    # status lets a caller tell "queued your work" from "already done
    # this hour", which is the same 202 either way.
    return {
        "job_id": job.id,
        "status_url": f"/v1/jobs/{job.id}",
        "status": job.status,
    }
```
Import `enqueue_job` from `bsi_core.scheduling`; drop the now-unused `pg_insert` import if nothing else in the file uses it (`ruff` will say).

- [ ] **Step 4: Worker changes**

In `apps/workers/bsi_workers/worker.py`:

Imports:
```python
from bsi_core.crawl import PAUSE_SECONDS, Fetch, audit_domain, http_fetch
from bsi_core.scheduling import budget_fits, enqueue_job, run_schedule
from dataclasses import asdict
```

`JOB_ESTIMATES` gains `"audit_crawl": 0,  # HTTP only: no model, no spend`.

Add after `refresh_due_recommendations`:

```python
def run_crawl_audit(
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    job_id: uuid.UUID,
    fetch: Fetch = http_fetch,
) -> int:
    """Audit every declared domain of the brand; returns how many.

    Fetching happens with no transaction open, as model calls do; the
    rows are written together at the end.
    """
    with tenant_session(org_id) as s:
        hosts = list(
            s.scalars(
                select(m.Domain.host)
                .where(m.Domain.brand_id == brand_id)
                .order_by(m.Domain.created_at, m.Domain.host)
            )
        )
    audits = [
        (host, audit_domain(host, fetch, pause=PAUSE_SECONDS))
        for host in hosts
    ]
    with tenant_session(org_id) as s:
        for host, audit in audits:
            s.add(
                m.SiteAudit(
                    org_id=org_id,
                    brand_id=brand_id,
                    job_id=job_id,
                    domain=host,
                    checks=[asdict(c) for c in audit.checks],
                    fetches=audit.fetches,
                )
            )
    return len(audits)


def queue_due_crawl_audits() -> int:
    """Queue an audit for every brand due one; returns how many.

    Idempotent within the hour: enqueue_job's unique key makes a repeat a
    no-op. One brand's failure never stops the others.
    """
    with system_session() as s:
        due = s.execute(
            text("SELECT brand_id, org_id FROM due_crawl_audits()")
        ).all()
    queued = 0
    for brand_id, org_id in due:
        try:
            with tenant_session(org_id) as s:
                enqueue_job(s, org_id, brand_id, "audit_crawl", {})
            queued += 1
        except Exception:
            log.exception("brand %s audit queue failed", brand_id)
    return queued
```

`process_job` signature and body: add `fetch: Fetch = http_fetch` as a keyword parameter and replace the `if kind == "suggest_prompts": … else: …` block with:

```python
    runners: dict[str, Callable[[], Any]] = {
        "suggest_prompts": lambda: suggest_prompts(
            org_id,
            brand_id,
            int(params.get("count", 0)),
            meter.generate,
            meter.embed,
        ),
        "suggest_competitors": lambda: suggest_competitors(
            org_id, brand_id, meter, meter.generate
        ),
        "audit_crawl": lambda: run_crawl_audit(
            org_id, brand_id, job_id, fetch
        ),
    }
    try:
        result = runners[kind]()
        log.info("job %s: %s", job_id, result)
        _finish_job(org_id, job_id, "done", None, meter.micros)
```
(`Callable` from `collections.abc`.) Keep the `except` exactly as it is. The earlier `if kind not in JOB_ESTIMATES` guard stays; `runners` and `JOB_ESTIMATES` must have the same keys — add a one-line assertion at module level after both are defined: `assert set(JOB_ESTIMATES) == {"suggest_prompts", "suggest_competitors", "audit_crawl"}` is overkill; instead let `test_an_unknown_kind_fails_the_job…` keep guarding the estimate table and add a `# keep in step with JOB_ESTIMATES` comment on `runners`.

`tick(...)` gains `fetch: Fetch = http_fetch` and passes it: `process_job(adapter, generator, embedder, fetch=fetch)`.

`main()` loop, after the `refresh_due_recommendations` block:
```python
            try:
                log.info("queued %d crawl audits", queue_due_crawl_audits())
            except Exception:
                log.exception("queue_due_crawl_audits failed")
```

- [ ] **Step 5: Run the tests**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_crawl_audit.py tests/integration/test_worker.py tests/integration/test_api_suggest.py tests/integration/test_runs.py`
Expected: PASS. Existing suggestion tests prove the `queue_suggestion` refactor kept its behaviour (failed job requeued, cost kept: `test_api_suggest.py:93-101`).

- [ ] **Step 6: Gate and commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add -A && git commit -q -F - <<'EOF'
feat(worker): run and queue crawl audits

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 7: `POST` and `GET /brands/{id}/audits/crawl`

**Files:**
- Create: `apps/api/bsi_api/routers/audits.py`
- Modify: `apps/api/bsi_api/schemas.py` (append), `apps/api/bsi_api/main.py`, `tests/integration/test_isolation.py` (two rows), `apps/web/src/lib/types.ts`
- Test: `tests/integration/test_api_audits.py`

**Interfaces:**
- Consumes: `runs.queue_suggestion`, `m.SiteAudit`.
- Produces: `QueuedOut(job_id, status_url, status)`, `CheckOut`, `SiteAuditOut(id, domain, created_at, fetches, job_id, checks: list[CheckOut])`; routes `POST /v1/brands/{id}/audits/crawl` (202) and `GET /v1/brands/{id}/audits/crawl` → `list[SiteAuditOut]` (latest per domain, ordered by domain).

- [ ] **Step 1: Failing tests**

`tests/integration/test_api_audits.py`:

```python
from bsi_core import models as m
from sqlalchemy import func, select, update

from tests.integration.test_crawl_audit import _audit, _domain


def test_post_queues_an_audit_job(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    r = client.post(f"/v1/brands/{bid}/audits/crawl", headers=org.headers)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["status_url"] == f"/v1/jobs/{body['job_id']}"
    with owner() as s:
        job = s.get(m.Job, body["job_id"])
    assert (job.kind, job.brand_id) == ("audit_crawl", bid)
    # Same hour, same job.
    again = client.post(f"/v1/brands/{bid}/audits/crawl", headers=org.headers)
    assert again.json()["job_id"] == body["job_id"]


def test_post_on_an_archived_brand_is_409(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand).where(m.Brand.id == bid).values(status="archived")
        )
    r = client.post(f"/v1/brands/{bid}/audits/crawl", headers=org.headers)
    assert r.status_code == 409


def test_get_returns_the_latest_audit_per_domain(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _domain(owner, org, bid, "nike.com")
    _audit(owner, org, bid, 10, "nike.com")
    with owner() as s, s.begin():
        s.add(
            m.SiteAudit(
                org_id=org.id,
                brand_id=bid,
                domain="nike.com",
                fetches=12,
                checks=[
                    {
                        "code": "llms_missing",
                        "ok": False,
                        "severity": "low",
                        "observed": "HTTP 404",
                        "expected": "x",
                        "url": "https://nike.com/llms.txt",
                    }
                ],
            )
        )
        s.add(m.SiteAudit(org_id=org.id, brand_id=bid, domain="nike.in"))
    r = client.get(f"/v1/brands/{bid}/audits/crawl", headers=org.headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [x["domain"] for x in rows] == ["nike.com", "nike.in"]
    assert rows[0]["fetches"] == 12
    assert rows[0]["checks"][0]["code"] == "llms_missing"
    assert rows[1]["checks"] == []


def test_get_is_empty_before_any_audit(client, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    r = client.get(f"/v1/brands/{bid}/audits/crawl", headers=org.headers)
    assert r.json() == []
```

- [ ] **Step 2: Run to see them fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_api_audits.py`
Expected: 404s (no route).

- [ ] **Step 3: Schemas**

Append to `schemas.py`:

```python
class QueuedOut(BaseModel):
    job_id: uuid.UUID
    status_url: str
    status: str


class CheckOut(BaseModel):
    code: str
    ok: bool
    severity: Literal["high", "medium", "low"]
    observed: str
    expected: str
    url: str


class SiteAuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    domain: str
    created_at: datetime
    fetches: int
    job_id: uuid.UUID | None
    checks: list[CheckOut]
```

- [ ] **Step 4: Router**

`apps/api/bsi_api/routers/audits.py`:

```python
"""Audits of the brand's own site. Only the crawlability audit so far."""

import uuid
from typing import Any

from bsi_core import models as m
from fastapi import APIRouter
from sqlalchemy import func, select

from ..deps import TENANT, Ctx, brand_or_404
from ..schemas import QueuedOut, SiteAuditOut
from .runs import queue_suggestion

router = APIRouter(prefix="/brands/{brand_id}/audits", tags=["audits"])


@router.post("/crawl", status_code=202, response_model=QueuedOut)
def queue_crawl(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    return queue_suggestion(c, brand_id, "audit_crawl", {})


@router.get("/crawl", response_model=list[SiteAuditOut])
def latest_crawl(brand_id: uuid.UUID, c: Ctx = TENANT) -> list[m.SiteAudit]:
    """The latest audit of each of the brand's domains."""
    brand_or_404(c, brand_id)
    latest = (
        select(
            m.SiteAudit.domain, func.max(m.SiteAudit.created_at).label("at")
        )
        .where(m.SiteAudit.brand_id == brand_id)
        .group_by(m.SiteAudit.domain)
        .subquery()
    )
    return list(
        c.s.scalars(
            select(m.SiteAudit)
            .join(
                latest,
                (m.SiteAudit.domain == latest.c.domain)
                & (m.SiteAudit.created_at == latest.c.at),
            )
            .where(m.SiteAudit.brand_id == brand_id)
            .order_by(m.SiteAudit.domain)
        )
    )
```

Register `audits` in `main.py` (import tuple and loop). Add both isolation rows:

```python
    ("POST", "/v1/brands/{b}/audits/crawl", None),
    ("GET", "/v1/brands/{b}/audits/crawl", None),
```

- [ ] **Step 5: Run, regenerate, gate**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_api_audits.py tests/integration/test_isolation.py`
Then `cd apps/web && npm run gen`; add to `types.ts`: `export type SiteAudit = S["SiteAuditOut"];` and `export type Queued = S["QueuedOut"];`; `git add` the generated files; run both gates.

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add -A && git commit -q -F - <<'EOF'
feat(api): queue and read the crawl audit

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 8: The `fix_crawlability` rule and copy

**Files:**
- Modify: `packages/core/bsi_core/recommend.py:35-45` (`FEASIBILITY`), copy functions area (~line 129), builders (~line 327), `generate` (~line 364); `apps/api/bsi_api/routers/recommendations.py:19` (`NO_IMPACT`); `apps/web/src/lib/format.ts:75-80` (`KIND`)
- Test: `tests/unit/test_recommend_copy.py`, `tests/integration/test_recommend.py` (append), `tests/integration/test_api_recommendations.py` (append)

**Interfaces:**
- Consumes: `m.SiteAudit`, `crawl.family`, `crawl.expected`.
- Produces: `crawl_copy(brand: str, domain: str, check: dict[str, Any]) -> tuple[str, str]`; `_crawl(s, brand_id, brand) -> list[Candidate]`; `FEASIBILITY["fix_crawlability"] = 0.8`; `PRESSURE_BY_SEVERITY = {"high": 1.0, "medium": 0.5, "low": 0.2}`.

- [ ] **Step 1: Copy tests first**

In `tests/unit/test_recommend_copy.py` import `crawl_copy` and add to `CASES`:

```python
    crawl_copy(
        "Nike",
        "nike.com",
        {
            "code": "bot_blocked:GPTBot",
            "observed": "User-agent: GPTBot\nDisallow: /",
            "expected": "robots.txt lets this crawler fetch the homepage.",
            "url": "https://nike.com/robots.txt",
            "severity": "high",
        },
    ),
    crawl_copy(
        "Nike",
        "nike.com",
        {
            "code": "sitemap_missing",
            "observed": "HTTP 404",
            "expected": "x",
            "url": "https://nike.com/sitemap.xml",
            "severity": "medium",
        },
    ),
    crawl_copy(
        "Nike",
        "nike.com",
        {
            "code": "llms_missing",
            "observed": "HTTP 404",
            "expected": "x",
            "url": "https://nike.com/llms.txt",
            "severity": "low",
        },
    ),
```

And one direct test:

```python
def test_crawl_copy_names_the_bot_and_the_file():
    title, body = crawl_copy(
        "Nike",
        "nike.com",
        {
            "code": "bot_ua_blocked:ClaudeBot",
            "observed": "HTTP 403",
            "expected": "x",
            "url": "https://nike.com/",
            "severity": "high",
        },
    )
    assert "ClaudeBot" in title and "nike.com" in title
    assert "HTTP 403" in body and "https://nike.com/" in body
```

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_recommend_copy.py` → ImportError.

- [ ] **Step 2: Integration tests**

Append to `tests/integration/test_recommend.py`:

```python
def _site_audit(owner, w, checks):
    with owner() as s, s.begin():
        s.add(
            m.Domain(org_id=w.org.id, brand_id=w.brand, host="nike.com")
        )
        s.add(
            m.SiteAudit(
                org_id=w.org.id, brand_id=w.brand, domain="nike.com",
                checks=checks,
            )
        )


def _check(code, ok, severity):
    return {
        "code": code, "ok": ok, "severity": severity,
        "observed": "o", "expected": "e", "url": "https://nike.com/",
    }


def test_each_failing_check_is_one_crawl_recommendation(owner, world):
    _site_audit(
        owner,
        world,
        [
            _check("bot_blocked:GPTBot", False, "high"),
            _check("sitemap_missing", False, "medium"),
            _check("llms_missing", False, "low"),
            _check("title_missing", True, "low"),
        ],
    )
    recs = {
        k: c for k, c in found(world).items() if k[0] == "fix_crawlability"
    }
    assert set(recs) == {
        ("fix_crawlability", "nike.com:bot_blocked:GPTBot"),
        ("fix_crawlability", "nike.com:sitemap_missing"),
        ("fix_crawlability", "nike.com:llms_missing"),
    }
    gpt = recs[("fix_crawlability", "nike.com:bot_blocked:GPTBot")]
    # Nothing measures a site fix against answers: reach is 1.0 and
    # pressure is the severity weight. 1.0 x 1.0 x 0.8.
    assert (gpt.reach, gpt.pressure, gpt.feasibility, gpt.priority) == (
        1.0, 1.0, 0.8, 0.8
    )
    assert recs[("fix_crawlability", "nike.com:sitemap_missing")].priority == 0.4
    assert recs[("fix_crawlability", "nike.com:llms_missing")].priority == 0.16
    assert gpt.evidence["domain"] == "nike.com"
    assert gpt.evidence["code"] == "bot_blocked:GPTBot"
    assert "audit_id" in gpt.evidence


def test_only_the_latest_audit_per_domain_counts(owner, world):
    _site_audit(owner, world, [_check("sitemap_missing", False, "medium")])
    with owner() as s, s.begin():
        s.execute(
            update(m.SiteAudit).values(
                created_at=func.now() - func.make_interval(0, 0, 0, 1)
            )
        )
        s.add(
            m.SiteAudit(
                org_id=world.org.id, brand_id=world.brand, domain="nike.com",
                checks=[_check("sitemap_missing", True, "medium")],
            )
        )
    assert not [k for k in found(world) if k[0] == "fix_crawlability"]


def test_a_fixed_check_disappears_on_refresh(owner, world):
    _site_audit(owner, world, [_check("llms_missing", False, "low")])
    with tenant_session(world.org.id) as s:
        refresh(s, world.org.id, world.brand)
    with owner() as s, s.begin():
        s.execute(
            update(m.SiteAudit).values(
                checks=[_check("llms_missing", True, "low")]
            )
        )
    with tenant_session(world.org.id) as s:
        refresh(s, world.org.id, world.brand)
        left = s.scalars(
            select(m.Recommendation).where(
                m.Recommendation.type == "fix_crawlability"
            )
        ).all()
    assert left == []
```

(`func` needs importing in that test module: `from sqlalchemy import func, select, update`.)

Append to `tests/integration/test_api_recommendations.py`, near the existing `add_competitor` no-impact test (`:60`):

```python
def test_a_crawl_task_measures_no_impact(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host="nike.com"))
        s.add(
            m.SiteAudit(
                org_id=org.id, brand_id=bid, domain="nike.com",
                checks=[{
                    "code": "llms_missing", "ok": False, "severity": "low",
                    "observed": "HTTP 404", "expected": "e",
                    "url": "https://nike.com/llms.txt",
                }],
            )
        )
    recs = client.post(
        f"/v1/brands/{bid}/recommendations/generate", headers=org.headers
    ).json()
    rec = next(r for r in recs if r["type"] == "fix_crawlability")
    task = client.post(
        f"/v1/brands/{bid}/recommendations/{rec['id']}/accept",
        headers=org.headers,
    ).json()
    assert task["measures_impact"] is False
```

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_recommend.py tests/integration/test_api_recommendations.py` → the new tests fail.

- [ ] **Step 3: Implement**

In `recommend.py`:

```python
from .crawl import expected, family  # top of file, with the other imports

FEASIBILITY = {
    "add_competitor": 0.9,
    "sample_more": 1.0,
    # A robots or head-tag change is minutes of work once someone with
    # site access is found; that person is the cost.
    "fix_crawlability": 0.8,
    "create_content": 0.4,
    "pursue_citation_source": 0.3,
}
# Nothing measures a site check against answers, so pressure is the
# check's severity, stated as a weight the operator can see.
PRESSURE_BY_SEVERITY = {"high": 1.0, "medium": 0.5, "low": 0.2}
```

Copy, after `sample_copy`:

```python
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
```

Rule, after `_sampling`:

```python
def _crawl(s: Session, brand_id: uuid.UUID, brand: str) -> list[Candidate]:
    """One candidate per failing check in each domain's latest audit."""
    rows = s.execute(
        text(
            "SELECT DISTINCT ON (domain) id, domain, checks FROM site_audit "
            "WHERE brand_id = :brand ORDER BY domain, created_at DESC, id"
        ),
        {"brand": brand_id},
    ).all()
    out = []
    for audit_id, domain, checks in rows:
        for check in checks:
            if check["ok"]:
                continue
            title, body = crawl_copy(brand, domain, check)
            out.append(
                Candidate(
                    "fix_crawlability",
                    f"{domain}:{check['code']}",
                    title,
                    body,
                    {**check, "domain": domain, "audit_id": str(audit_id)},
                    # Not measured against answers; see PRESSURE_BY_SEVERITY.
                    1.0,
                    PRESSURE_BY_SEVERITY[check["severity"]],
                )
            )
    return out
```

In `generate`, add `+ _crawl(s, brand_id, brand)` to the list the other four builders feed. Update the module docstring's `reach`/`pressure` bullets to mention that `fix_crawlability` joins `add_competitor` as a judged, not measured, type.

`routers/recommendations.py`: `NO_IMPACT = {"add_competitor", "sample_more", "fix_crawlability"}` and extend the comment: a site fix changes what an engine *can* read, not what it says within a window.

`apps/web/src/lib/format.ts` `KIND`: add `fix_crawlability: "Site fix",`.

- [ ] **Step 4: Run everything**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_recommend_copy.py tests/unit/test_recommend_top.py tests/integration/test_recommend.py tests/integration/test_api_recommendations.py`
Expected: PASS. Then the full backend gate and `npm run gate`.

- [ ] **Step 5: Mutation check**

Set `PRESSURE_BY_SEVERITY["medium"]` to `0.6`; `test_each_failing_check_is_one_crawl_recommendation` must fail on `0.4`. Restore.

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add -A && git commit -q -F - <<'EOF'
feat(recommend): fix_crawlability, one per failing site check

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 9: Site tab

**Files:**
- Create: `apps/web/src/app/(app)/b/[id]/site/page.tsx`, `apps/web/src/app/(app)/b/[id]/site/actions.ts`
- Modify: `apps/web/src/app/(app)/b/[id]/layout.tsx` (add the tab after Citations)

**Interfaces:**
- Consumes: `SiteAudit` type, `api<T>`.

- [ ] **Step 1: Action**

`actions.ts`:

```ts
"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";

export async function runAudit(form: FormData) {
  const id = String(form.get("brand_id"));
  await api(`/brands/${id}/audits/crawl`, { method: "POST" });
  redirect(`/b/${id}/site?queued=1`);
}
```

- [ ] **Step 2: Page**

`page.tsx`:

```tsx
import { api } from "@/lib/api";
import type { Params } from "@/lib/format";
import type { SiteAudit } from "@/lib/types";
import { runAudit } from "./actions";

export default async function Site({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const audits = await api<SiteAudit[]>(`/brands/${id}/audits/crawl`);
  return (
    <>
      <form action={runAudit} className="row">
        <input type="hidden" name="brand_id" value={id} />
        <button className="primary">Run audit now</button>
        {sp.queued === "1" && (
          <span className="muted">Queued; the worker runs it within a minute.</span>
        )}
      </form>
      {audits.length === 0 && (
        <p className="muted">
          No audit yet. The worker audits every brand with a declared domain
          weekly, or run one now.
        </p>
      )}
      {audits.map((a) => {
        const failing = a.checks.filter((c) => !c.ok).length;
        return (
          <div className="card" key={a.id} style={{ marginTop: 12 }}>
            <div className="row">
              <strong>{a.domain}</strong>
              <span className="muted">
                {a.created_at.slice(0, 16).replace("T", " ")} UTC · {a.fetches}{" "}
                fetches · {failing} failing
              </span>
            </div>
            <table>
              <thead>
                <tr>
                  <th></th>
                  <th>Check</th>
                  <th>Severity</th>
                  <th>Observed</th>
                  <th>Expected</th>
                </tr>
              </thead>
              <tbody>
                {a.checks.map((c) => (
                  <tr key={c.code} className={c.ok ? undefined : "low"}>
                    <td className={c.ok ? "up" : "down"}>{c.ok ? "✓" : "✗"}</td>
                    <td>
                      <a href={c.url}>{c.code}</a>
                    </td>
                    <td>
                      <span className="tag">{c.severity}</span>
                    </td>
                    <td>
                      <code style={{ whiteSpace: "pre-wrap" }}>{c.observed}</code>
                    </td>
                    <td className="muted">{c.expected}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      })}
    </>
  );
}
```

Add the tab in `layout.tsx` after Citations: `<Link href={`/b/${id}/site`}>Site</Link>`.

- [ ] **Step 3: Gate and look**

`cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate` → exit 0. Then start API, worker (`uv run python -m bsi_workers`, env sourced) and `npm run dev`; on the Run 1 brand, add a domain if none exists (the wizard or `POST /domains`), open `/b/…/site`, click **Run audit now**, wait a minute, reload: one card per domain with checks. Stop the servers.

- [ ] **Step 4: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add -A && git commit -q -F - <<'EOF'
feat(web): Site tab with the crawl audit and a run button

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
EOF
```

---

### Task 10: Live check, findings, docs index

**Files:**
- Create: `docs/findings-slice7.md`
- Modify: `docs/README.md` (a "Slice 7" section like the others)

- [ ] **Step 1: Citations on Run 1**

With the API up and the Run 1 key, `GET /v1/brands/34db213a-f484-4991-a969-c52cfa5e1c10/citations`. Record: domain count, how many are gaps, the source-type split, the top ten by answers, and how many of the top ten name the brand at all. Compare the gap count with the number of `pursue_citation_source` recommendations `generate()` would produce (call it read-only through a script, not `refresh`).

- [ ] **Step 2: Audit two real domains**

Run `audit_domain` from a script against the Run 1 brand's declared domain and against one well-known domain that blocks GPTBot in robots.txt (check a candidate's `/robots.txt` in the browser first; several large publishers do). Record fetch counts, elapsed seconds, and every failing check. This is HTTP only: no spend.

- [ ] **Step 3: Clean the dev tables**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && docker compose exec -T db psql -U bsi_owner -d bsi -c "DELETE FROM task; DELETE FROM recommendation; DELETE FROM site_audit; DELETE FROM job WHERE kind = 'audit_crawl';"
```
and confirm all four counts are 0. Remove any domain you added to Run 1 for the check.

- [ ] **Step 4: Write `docs/findings-slice7.md`**

Sections: what was measured and how (with the exact commands), the citation table numbers, the audit results per domain with elapsed time, what the rule produced on the failing checks and where `fix_crawlability` landed in `top_by_type`, known gaps (source-type heuristic, first sitemap only, no page crawl, `bot_ua_blocked` cannot tell a CDN challenge from a hard block, a failing audit job re-queues hourly), and spend (unchanged: $9.2762).

Add a "Slice 7: citation intelligence and the crawlability audit" section to `docs/README.md` with the spec, this plan and the findings, in the same table format as slice 6.

- [ ] **Step 5: Final gate, push, PR**

Run both gates; `git add -A`; commit `docs: slice 7 findings`; push `slice7-audits`; open the PR with `GH_TOKEN=$(gh auth token -u aiagencyindia-lab) gh pr create --repo aiagencyindia-lab/bsi-platform …`, its body ending with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Watch CI with `gh pr checks <n> --watch` and read the run log to confirm both gates ran. **Do not merge**: the user merges.

---

## Self-review

- **Spec coverage.** Citation fields, sort, filters, endpoint, page: Tasks 1–3. Fetch callable, checks table, severities, fetch budget (11 in the spec, 12 here — the spec undercounted: home + robots + 8 bot UAs + sitemap + llms = 12; the spec's number is corrected in the findings): Task 4. Table, RLS, due function, rec-type constraint: Task 5. Job kind, dispatch, no-transaction rule, weekly queueing, idempotence: Task 6. API and isolation: Tasks 2, 7. Rule, weights, copy, `NO_IMPACT`, `KIND`: Task 8. Site tab: Task 9. Live check and findings: Task 10.
- **Placeholders.** None; every step carries code or an exact command.
- **Type consistency.** `Fetch(url, ua) -> Response` everywhere; `Audit(checks, fetches)`; `Check` fields `code, ok, severity, observed, expected, url` match `CheckOut` and the JSON the rule reads; `enqueue_job(s, org_id, brand_id, kind, params, slot=None)` in Tasks 6–7; `run_crawl_audit(org_id, brand_id, job_id, fetch)`; `SourceOut` fields match `sources()` keys.
