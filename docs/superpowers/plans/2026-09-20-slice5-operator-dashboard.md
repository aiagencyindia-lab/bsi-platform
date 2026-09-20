# Slice 5: Operator Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Next.js operator dashboard over the existing API: brand overview, per-prompt table with evidence drill-down, ops and spend, and hand-labelling of judge verdicts.

**Architecture:** `apps/web` (Next.js 15, App Router) renders everything in Server Components that fetch FastAPI server-side; the API key lives in an httpOnly cookie and never reaches the browser, so there is no CORS. The frontend never computes a metric: every rate, interval, delta and label comes from `bsi_core`. Four small API additions feed it.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, Alembic, pytest. Node 22, Next.js 15, React 19, TypeScript, vitest, eslint, `openapi-typescript` (types only).

**Spec:** `docs/superpowers/specs/2026-09-20-slice5-operator-dashboard-design.md`

## Global Constraints

- Repo root is `/Users/vineet/Downloads/ADK/bsi-platform`. **The shell's working directory resets between commands: start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.** Branch: `slice5-operator-dashboard`.
- **TDD, with evidence:** write the failing test first and **paste the failing test output into your report** before implementing.
- Backend gate, after every task:
  `uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100`
- Frontend gate, after every task from Task 3 on:
  `cd apps/web && npm run typecheck && npm run lint && npm test && npm run build && npm run gen:check`
- `bsi_core/metrics.py` stays at **100% line coverage**. `mypy --strict` covers `packages/core/bsi_core`. Ruff line length is 80.
- Tests never call Vertex. No clock-freezing: backdate rows with an owner `UPDATE`.
- Every tenant table gets `org_id`, ENABLE **and** FORCE row-level security, and the policy used in migration `0006`. A cross-tenant id returns 404; a cross-tenant list returns `200 []`.
- Application code gets sessions only through `tenant_session(org_id)` (in routes: `c: Ctx = TENANT`).
- The frontend computes no metric, interval or significance label. Sorting and formatting are allowed.
- No new runtime dependencies beyond: `next`, `react`, `react-dom`, `server-only`. No chart library, no Tailwind, no component library, no Playwright.
- Commits: conventional subject, a blank line, then `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Two deliberate simplifications of the spec: one `globals.css` instead of CSS modules (eight small pages), and `error.tsx` shows the message in dev and the digest in production, with the problem and request id logged server-side (Next strips server error messages in production builds).

## File Structure

```
apps/api/bsi_api/routers/metrics.py        modify  response models; GET prompts/metrics
apps/api/bsi_api/routers/observations.py   modify  typed detail, answer_text(), search_queries
apps/api/bsi_api/routers/ops.py            create  GET /v1/ops
apps/api/bsi_api/routers/labels.py         create  labels/next, PUT label
apps/api/bsi_api/main.py                   modify  include the two routers
packages/core/bsi_core/metrics.py          modify  _entities(), prompt_metrics()
packages/core/bsi_core/models.py           modify  REC_STATUSES, Observation.search_queries, RecLabel
packages/core/bsi_core/providers/base.py   modify  EngineResult.search_queries
packages/core/bsi_core/providers/gemini.py modify  search_queries(raw)
packages/core/bsi_core/scheduling.py       modify  spent_and_pending(), ops_summary()
apps/workers/bsi_workers/worker.py         modify  store search_queries
migrations/versions/0008_search_queries_and_labels.py   create
scripts/export_openapi.py, scripts/backfill_search_queries.py   create
scripts/export_rec_labels.py               modify  --from-db
apps/web/                                  create  (layout in Task 3)
```

---

### Task 1: Typed metric and observation responses, answer text

`/metrics`, `/sov`, `/deltas` and `GET /observations/{id}` return `dict[str, Any]`, so generated TypeScript types would be `any`. Add response models with **no behaviour change**, and add the answer `text` to the observation detail.

**Files:**
- Modify: `apps/api/bsi_api/routers/metrics.py`, `apps/api/bsi_api/routers/observations.py`
- Test: `tests/integration/test_api_typed.py` (create)

**Interfaces:**
- Produces: OpenAPI schemas `MetricsOut`, `SovOut`, `DeltasOut`, `ObservationDetail`, `Rate`; `answer_text(obs: m.Observation, org_id: uuid.UUID) -> str | None` in `observations.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_api_typed.py
import json
from pathlib import Path

import pytest
from bsi_core.providers.gemini import GeminiGroundingAdapter

RAW = json.loads(Path("tests/fixtures/gemini_min.json").read_text())


@pytest.mark.parametrize(
    "path",
    [
        "/v1/brands/{brand_id}/metrics",
        "/v1/brands/{brand_id}/sov",
        "/v1/brands/{brand_id}/deltas",
        "/v1/observations/{observation_id}",
    ],
)
def test_dashboard_responses_are_typed(client, path):
    spec = client.get("/openapi.json").json()
    ok = spec["paths"][path]["get"]["responses"]["200"]
    assert "$ref" in ok["content"]["application/json"]["schema"]


def test_deltas_keep_the_from_key(client, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    body = client.get(f"/v1/brands/{bid}/deltas", headers=org.headers).json()
    assert {"from", "to"} <= set(body["before"])
    assert body["before"]["recommendation_rate"]["experimental"] is True


def test_observation_detail_carries_the_answer_text(
    client, make_org, make_brand, make_observation
):
    org = make_org()
    oid = make_observation(org, make_brand(org), raw=RAW, status="done")
    body = client.get(f"/v1/observations/{oid}", headers=org.headers).json()
    assert body["text"] == GeminiGroundingAdapter().parse(RAW).text
    assert body["text"]


def test_observation_without_a_payload_has_no_text(
    client, make_org, make_brand, make_observation
):
    org = make_org()
    oid = make_observation(org, make_brand(org), status="queued")
    body = client.get(f"/v1/observations/{oid}", headers=org.headers).json()
    assert body["text"] is None and body["extraction"] is None
```

- [ ] **Step 2: Run them; confirm they fail**

Run: `uv run pytest tests/integration/test_api_typed.py -q`
Expected: the four parametrized cases fail on `assert "$ref" in ...`; the text tests fail with `KeyError: 'text'`.

- [ ] **Step 3: Add the metric models** to `metrics.py` (above the routes) and set `response_model=` on the three routes. Return values stay as they are.

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Rate(BaseModel):
    value: float | None
    n: int
    ci_low: float
    ci_high: float


class RecRate(Rate):
    experimental: bool


class AvgPosition(BaseModel):
    value: float | None
    n_mentioned: int


class FiltersOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # a Filters dataclass
    engine: str | None
    locale_id: uuid.UUID | None
    date_from: datetime | None
    date_to: datetime | None
    prompt_ids: list[uuid.UUID] | None


class Window(BaseModel):
    mention_rate: Rate
    recommendation_rate: RecRate
    citation_rate: Rate
    prompt_coverage: Rate
    sov: Rate
    avg_position: AvgPosition
    n_failed: int
    pipeline_versions: list[str]
    pipeline_version: str
    computed_at: datetime


class MetricsOut(Window):
    filters: FiltersOut


class DeltaWindow(Window):
    from_: datetime = Field(alias="from")
    to: datetime


class Delta(BaseModel):
    value: float | None
    ci_low: float | None
    ci_high: float | None
    label: Literal[
        "increase", "decrease", "no significant change", "insufficient data"
    ]


class DeltasOut(BaseModel):
    before: DeltaWindow
    after: DeltaWindow
    comparable: bool
    reason: str | None
    deltas: dict[str, Delta] | None


class SovEntity(BaseModel):
    entity_id: uuid.UUID
    name: str
    type: Literal["brand", "competitor"]
    mentions: int
    share: float | None
    ci_low: float
    ci_high: float


class SovOut(BaseModel):
    filters: FiltersOut
    entities: list[SovEntity]
    n_failed: int
    pipeline_version: str
    computed_at: datetime
```

Routes become `@router.get("/metrics", response_model=MetricsOut)`, `("/deltas", response_model=DeltasOut)`, `("/sov", response_model=SovOut)`.

- [ ] **Step 4: Type the observation detail** in `observations.py`. Replace `_columns` and the dict-building body of `get_observation` with models read from the ORM rows. Match each field's nullability to `m.Extraction`, `m.Mention`, `m.Citation` in `models.py`.

```python
from bsi_core.providers.gemini import GeminiGroundingAdapter

_ORM = ConfigDict(from_attributes=True)


class ExtractionOut(BaseModel):
    model_config = _ORM
    pipeline_version: str
    model_used: str | None
    brand_mentioned: bool | None
    position: int | None
    rec_status: str | None
    sentiment: str | None
    sentiment_conf: float | None
    context: str | None
    absence_reason: str | None
    parsed: dict[str, Any]
    cost_micros: int


class MentionOut(BaseModel):
    model_config = _ORM
    entity_type: str
    entity_id: uuid.UUID
    position: int
    rec_status: str
    sentiment: str
    evidence_sentence: str | None


class CitationOut(BaseModel):
    model_config = _ORM
    url: str
    domain: str
    position: int
    is_brand_owned: bool


class ObservationDetail(ObservationOut):
    params: dict[str, Any]
    text: str | None
    extraction: ExtractionOut | None
    mentions: list[MentionOut]
    citations: list[CitationOut]


def answer_text(obs: m.Observation, org_id: uuid.UUID) -> str | None:
    if obs.raw_uri is None:
        return None
    # ponytail: one engine today; choose the adapter by engine code when
    # a second one exists.
    raw = LocalRawStore().get(obs.raw_uri, org_id)
    return GeminiGroundingAdapter().parse(raw).text
```

`get_observation` keeps its three queries and returns:

```python
    return {
        **ObservationOut.model_validate(obs).model_dump(),
        "params": obs.params,
        "text": answer_text(obs, c.org_id),
        "extraction": ex,
        "mentions": list(mentions),
        "citations": list(citations),
    }
```

with `@router.get("/{observation_id}", response_model=ObservationDetail)`.

- [ ] **Step 5: Run the new tests, then the whole gate.** Expected: all pass; the existing API tests prove nothing changed shape. If an existing test fails on a field's nullability, fix the model, not the test.

- [ ] **Step 6: Commit** — `feat(api): type the metric and observation responses; add answer text`

---

### Task 2: Per-prompt metrics

**Files:**
- Modify: `packages/core/bsi_core/metrics.py`, `apps/api/bsi_api/routers/metrics.py`
- Test: `tests/integration/test_metrics.py` (append), `tests/integration/test_api_typed.py` (append)

**Interfaces:**
- Consumes: `_where`, `rate`, `Filters`, `Rate` model from Task 1.
- Produces: `prompt_metrics(s: Session, brand_id: uuid.UUID, f: Filters) -> list[dict[str, Any]]`; `GET /v1/brands/{brand_id}/prompts/metrics` → `list[PromptMetricsOut]`. Each row: `prompt_id, text, intent, topic, n, brand: Rate, entities: [EntityRate], top_competitor: EntityRate | None, spread: float | None, separated: bool`. `EntityRate` = `Rate` + `entity_id, name, type`.

`separated` is true when the brand's interval and the top competitor's do not overlap: the prompt tells the two apart at this sample size.

- [ ] **Step 1: Write the failing tests** (append to `test_metrics.py`; the `scene` fixture is documented at its top: p1 has o1 brand+c1 and o2 brand; p2 has o3 c1+c2, o4 nobody, o5 failed).

```python
def test_prompt_metrics(scene):
    org, bid, p2 = scene
    with tenant_session(org.id) as s:
        rows = {r["text"]: r for r in prompt_metrics(s, bid, Filters())}
    p1 = rows["p1"]
    assert (p1["n"], p1["brand"]["value"]) == (2, 1.0)
    assert p1["top_competitor"]["name"] == "Adidas"
    assert p1["top_competitor"]["value"] == 0.5
    assert p1["spread"] == 0.5 and p1["separated"] is False
    assert [e["name"] for e in p1["entities"]] == ["Nike", "Adidas", "Puma"]
    r2 = rows["p2"]
    assert r2["prompt_id"] == p2 and r2["n"] == 2  # the failed one is out
    assert r2["brand"]["value"] == 0.0 and r2["spread"] == -0.5


def test_prompt_metrics_without_competitors(
    make_org, make_brand, make_observation
):
    org = make_org()
    bid = make_brand(org)
    make_observation(org, bid, status="done")
    with tenant_session(org.id) as s:
        (row,) = prompt_metrics(s, bid, Filters())
    assert row["top_competitor"] is None and row["spread"] is None
    assert row["separated"] is False


def test_prompt_metrics_separates_clear_winners(
    owner, make_org, make_brand, make_observation
):
    org = make_org()
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        comp = m.Competitor(org_id=org.id, brand_id=bid, name="Adidas")
        s.add(comp)
    first = make_observation(org, bid, status="done", text="p")
    with owner() as s:
        pid = s.get(m.Observation, first).prompt_id
    ids = [first] + [
        make_observation(org, bid, status="done", prompt_id=pid, sample_index=i)
        for i in range(1, 12)
    ]
    with owner() as s, s.begin():
        s.add_all(
            m.Mention(
                org_id=org.id,
                observation_id=o,
                entity_type="brand",
                entity_id=bid,
                position=1,
                rec_status="mentioned",
                sentiment="neutral",
            )
            for o in ids
        )
    with tenant_session(org.id) as s:
        (row,) = prompt_metrics(s, bid, Filters())
    assert row["separated"] is True  # 12/12 against 0/12
```

Add `prompt_metrics` to the file's import from `bsi_core.metrics`. Append to `test_api_typed.py`:

```python
def test_prompt_metrics_endpoint(client, make_org, make_brand, make_observation):
    a, b = make_org("A"), make_org("B")
    bid = make_brand(a)
    make_observation(a, bid, status="done")
    url = f"/v1/brands/{bid}/prompts/metrics"
    (row,) = client.get(url, headers=a.headers).json()
    assert row["n"] == 1 and row["brand"]["value"] == 0.0
    assert client.get(url, headers=b.headers).status_code == 404
```

- [ ] **Step 2: Run; confirm they fail** with `ImportError: cannot import name 'prompt_metrics'` and a 404/405 on the endpoint.

- [ ] **Step 3: Implement in `metrics.py`.** First lift the entity list out of `brand_sov` so both functions share it:

```python
def _entities(s: Session, brand_id: uuid.UUID) -> list[tuple[uuid.UUID, str, str]]:
    """The brand, then its active competitors: who the metrics measure."""
    brand = s.get_one(m.Brand, brand_id)
    competitors = s.scalars(
        select(m.Competitor)
        .where(
            m.Competitor.brand_id == brand_id,
            m.Competitor.status == "active",
        )
        .order_by(m.Competitor.created_at, m.Competitor.name)
    ).all()
    return [(brand.id, brand.name, "brand")] + [
        (c.id, c.name, "competitor") for c in competitors
    ]
```

`brand_sov` now starts its entity handling with `entities = _entities(s, brand_id)`. Then:

```python
def prompt_metrics(
    s: Session, brand_id: uuid.UUID, f: Filters
) -> list[dict[str, Any]]:
    """Mention rate per prompt for the brand and each active competitor.

    A mention is unique per (observation, entity), so a mention count is
    the number of answers that named the entity.
    """
    where, params = _where(brand_id, f)
    prompts = s.execute(
        text(
            "SELECT o.prompt_id, p.text, p.intent, p.topic, count(*) AS n "
            "FROM observation o JOIN prompt p ON p.id = o.prompt_id "
            f"WHERE {where} AND o.status = 'done' "
            "GROUP BY o.prompt_id, p.text, p.intent, p.topic "
            "ORDER BY p.text, o.prompt_id"
        ),
        params,
    ).all()
    counts: dict[tuple[uuid.UUID, uuid.UUID], int] = {
        (pid, eid): k
        for pid, eid, k in s.execute(
            text(
                "SELECT o.prompt_id, mn.entity_id, count(*) FROM mention mn "
                "JOIN observation o ON o.id = mn.observation_id "
                f"WHERE {where} AND o.status = 'done' "
                "GROUP BY o.prompt_id, mn.entity_id"
            ),
            params,
        ).tuples()
    }
    entities = _entities(s, brand_id)
    rows = []
    for p in prompts:
        rates = [
            {
                "entity_id": eid,
                "name": name,
                "type": etype,
                **rate(counts.get((p.prompt_id, eid), 0), p.n),
            }
            for eid, name, etype in entities
        ]
        brand, rivals = rates[0], rates[1:]
        top = max(rivals, key=lambda r: r["value"], default=None)
        rows.append(
            {
                "prompt_id": p.prompt_id,
                "text": p.text,
                "intent": p.intent,
                "topic": p.topic,
                "n": p.n,
                "brand": brand,
                "entities": rates,
                "top_competitor": top,
                "spread": brand["value"] - top["value"] if top else None,
                "separated": bool(top)
                and (
                    brand["ci_low"] > top["ci_high"]
                    or brand["ci_high"] < top["ci_low"]
                ),
            }
        )
    return rows
```

(`p.n >= 1` for every row, so `value` is never `None` here. `max` keeps the first of equal rivals, which is creation order.) If `mypy --strict` objects to the arithmetic on the `rate()` union, build the spread from the raw counts instead: `(k_brand - k_top) / p.n`.

- [ ] **Step 4: Add the endpoint** to `routers/metrics.py`:

```python
class EntityRate(Rate):
    entity_id: uuid.UUID
    name: str
    type: Literal["brand", "competitor"]


class PromptMetricsOut(BaseModel):
    prompt_id: uuid.UUID
    text: str
    intent: str | None
    topic: str | None
    n: int
    brand: EntityRate
    entities: list[EntityRate]
    top_competitor: EntityRate | None
    spread: float | None
    separated: bool


@router.get("/prompts/metrics", response_model=list[PromptMetricsOut])
def get_prompt_metrics(
    brand_id: uuid.UUID, f: Filters = Depends(filters), c: Ctx = TENANT
) -> list[dict[str, Any]]:
    brand_or_404(c, brand_id)
    return prompt_metrics(c.s, brand_id, f)
```

- [ ] **Step 5: Run the tests and the gate.** The coverage flag must still report 100% for `bsi_core.metrics`.

- [ ] **Step 6: Commit** — `feat(metrics): per-prompt mention rates for the brand and its rivals`

---

### Task 3: `apps/web` scaffold, API wrapper, generated types, login, brand list

**Files (all created, under `apps/web/` unless noted):**
`package.json`, `tsconfig.json`, `next.config.ts`, `eslint.config.mjs`, `.env.example`, `openapi.json` (generated), `src/lib/schema.d.ts` (generated), `src/lib/types.ts`, `src/lib/api.ts`, `src/lib/format.ts`, `src/lib/format.test.ts`, `src/app/globals.css`, `src/app/layout.tsx`, `src/app/error.tsx`, `src/app/not-found.tsx`, `src/app/login/page.tsx`, `src/app/login/actions.ts`, `src/app/page.tsx`; repo root: `scripts/export_openapi.py`, `.gitignore`.

**Interfaces:**
- Produces: `api<T>(path, init?) : Promise<T>`, `COOKIE`, `API_URL` (`src/lib/api.ts`); `pct`, `ciText`, `pts`, `usd`, `apiQuery`, `highlight` (`src/lib/format.ts`); type aliases in `src/lib/types.ts`; CSS classes in `globals.css`.

- [ ] **Step 1: Project files**

`.gitignore` (repo root) gains: `apps/web/node_modules/`, `apps/web/.next/`, `apps/web/next-env.d.ts`, `apps/web/.env.local`.

```python
# scripts/export_openapi.py
"""Write the API's OpenAPI document. usage: export_openapi.py OUT.json"""

import json
import sys
from pathlib import Path

from bsi_api.main import app

Path(sys.argv[1]).write_text(
    json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
)
```

```json
// apps/web/package.json
{
  "name": "bsi-web",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "typecheck": "tsc --noEmit",
    "lint": "eslint .",
    "test": "vitest run",
    "gen": "cd ../.. && uv run python scripts/export_openapi.py apps/web/openapi.json && cd apps/web && openapi-typescript openapi.json -o src/lib/schema.d.ts",
    "gen:check": "npm run gen && git diff --exit-code -- openapi.json src/lib/schema.d.ts"
  },
  "dependencies": {
    "next": "^15.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "server-only": "^0.0.1"
  },
  "devDependencies": {
    "@eslint/eslintrc": "^3.0.0",
    "@types/node": "^22.0.0",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "eslint": "^9.0.0",
    "eslint-config-next": "^15.0.0",
    "openapi-typescript": "^7.0.0",
    "typescript": "^5.6.0",
    "vitest": "^3.0.0"
  }
}
```

(Remove the `//` comment line; JSON has none.)

```json
// apps/web/tsconfig.json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "strict": true,
    "noEmit": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "esModuleInterop": true,
    "jsx": "preserve",
    "incremental": true,
    "skipLibCheck": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

```ts
// apps/web/next.config.ts
import type { NextConfig } from "next";

const config: NextConfig = {};
export default config;
```

```js
// apps/web/eslint.config.mjs
import { FlatCompat } from "@eslint/eslintrc";

const compat = new FlatCompat({ baseDirectory: import.meta.dirname });

export default [
  { ignores: [".next/**", "next-env.d.ts", "src/lib/schema.d.ts"] },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
];
```

`apps/web/.env.example`: `API_URL=http://localhost:8000`

Run: `cd apps/web && npm install && npm run gen`. Commit `package-lock.json`, `openapi.json` and `src/lib/schema.d.ts`.

- [ ] **Step 2: Write the failing format tests**

```ts
// apps/web/src/lib/format.test.ts
import { expect, test } from "vitest";
import { apiQuery, ciText, highlight, pct, pts, usd } from "./format";

test("pct", () => {
  expect(pct(0.4167)).toBe("41.7%");
  expect(pct(null)).toBe("—");
});

test("ciText carries the interval and n", () => {
  const r = { value: 0.5, n: 60, ci_low: 0.377, ci_high: 0.623 };
  expect(ciText(r)).toBe("37.7%–62.3% · n=60");
  expect(ciText({ ...r, value: null, n: 0 })).toBe("no data · n=0");
});

test("pts signs the change", () => {
  expect(pts(0.052)).toBe("+5.2 pts");
  expect(pts(-0.1)).toBe("-10.0 pts");
  expect(pts(null)).toBe("—");
});

test("usd from micros", () => expect(usd(7_353_200)).toBe("$7.3532"));

test("apiQuery keeps known filters and makes dates UTC instants", () => {
  const q = apiQuery({ engine: "gemini", date_from: "2026-09-01", x: "1" });
  expect(q).toBe("?engine=gemini&date_from=2026-09-01T00%3A00%3A00Z");
  expect(apiQuery({ engine: "" })).toBe("");
  expect(apiQuery({ days: "14", date_from: "2026-09-01" }, ["days"], ["date_from"]))
    .toBe("?days=14");
});

test("highlight marks evidence sentences in order", () => {
  const parts = highlight("A. Nike is best. B.", ["Nike is best.", "gone"]);
  expect(parts).toEqual([
    { text: "A. ", hit: false },
    { text: "Nike is best.", hit: true },
    { text: " B.", hit: false },
  ]);
});
```

Run: `npm test`. Expected: FAIL, `Cannot find module './format'`.

- [ ] **Step 3: Implement `format.ts`**

```ts
// apps/web/src/lib/format.ts
export type Rate = {
  value: number | null;
  n: number;
  ci_low: number;
  ci_high: number;
};
export type Params = Record<string, string | string[] | undefined>;

export const pct = (v: number | null | undefined) =>
  v == null ? "—" : `${(v * 100).toFixed(1)}%`;

export const ciText = (r: Rate) =>
  r.value == null
    ? `no data · n=${r.n}`
    : `${pct(r.ci_low)}–${pct(r.ci_high)} · n=${r.n}`;

export const pts = (v: number | null | undefined) =>
  v == null ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)} pts`;

export const usd = (micros: number) => `$${(micros / 1e6).toFixed(4)}`;

const FILTERS = ["engine", "locale_id", "date_from", "date_to"];

/** The API query string for the page's filters. `<input type=date>`
 * gives a bare date; the API wants an instant, so midnight UTC. */
export function apiQuery(
  sp: Params,
  extra: string[] = [],
  drop: string[] = [],
): string {
  const q = new URLSearchParams();
  for (const k of [...FILTERS, ...extra]) {
    const v = sp[k];
    if (typeof v !== "string" || !v || drop.includes(k)) continue;
    q.set(k, /^\d{4}-\d{2}-\d{2}$/.test(v) ? `${v}T00:00:00Z` : v);
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function highlight(text: string, sentences: string[]) {
  const spans = sentences
    .map((s) => [text.indexOf(s), s.length] as const)
    .filter(([i]) => i >= 0)
    .sort((a, b) => a[0] - b[0]);
  const out: { text: string; hit: boolean }[] = [];
  let at = 0;
  for (const [i, len] of spans) {
    if (i < at) continue;
    if (i > at) out.push({ text: text.slice(at, i), hit: false });
    out.push({ text: text.slice(i, i + len), hit: true });
    at = i + len;
  }
  if (at < text.length) out.push({ text: text.slice(at), hit: false });
  return out;
}
```

Run `npm test`; expected PASS.

- [ ] **Step 4: API wrapper and types**

```ts
// apps/web/src/lib/api.ts
import "server-only";
import { cookies } from "next/headers";
import { notFound, redirect } from "next/navigation";

export const API_URL = process.env.API_URL ?? "http://localhost:8000";
export const COOKIE = "bsi_key";

/** Server-side call to /v1. The key comes from the httpOnly cookie. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const key = (await cookies()).get(COOKIE)?.value;
  if (!key) redirect("/login");
  const res = await fetch(`${API_URL}/v1${path}`, {
    ...init,
    cache: "no-store",
    headers: { ...init.headers, Authorization: `Bearer ${key}` },
  });
  if (res.status === 401) redirect("/login");
  if (res.status === 404) notFound();
  if (!res.ok) {
    const p = await res.json().catch(() => ({}));
    const rid = res.headers.get("x-request-id");
    // Next strips server error messages in production; keep them in the log.
    console.error("API problem", res.status, path, rid, p);
    throw new Error(
      `${res.status} ${p.title ?? res.statusText}` +
        `${p.detail ? `: ${p.detail}` : ""} (request ${rid})`,
    );
  }
  return res.status === 204 ? (undefined as T) : res.json();
}
```

```ts
// apps/web/src/lib/types.ts
import type { components } from "./schema";

type S = components["schemas"];
export type Brand = S["BrandOut"];
export type Metrics = S["MetricsOut"];
export type Deltas = S["DeltasOut"];
export type Sov = S["SovOut"];
export type PromptMetrics = S["PromptMetricsOut"];
export type Observation = S["ObservationOut"];
export type ObservationDetail = S["ObservationDetail"];
```

- [ ] **Step 5: Shell, login, brand list**

```css
/* apps/web/src/app/globals.css */
:root {
  --bg: #fafaf9; --surface: #fff; --text: #1c1917; --muted: #78716c;
  --line: #e7e5e4; --accent: #1d4ed8; --up: #15803d; --down: #b91c1c;
  --mark: #fef08a; --radius: 6px;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
  font: 14px/1.5 system-ui, sans-serif; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
nav { display: flex; gap: 16px; align-items: center; padding: 12px 24px;
  background: var(--surface); border-bottom: 1px solid var(--line); }
nav .grow { flex: 1; }
main { max-width: 1100px; margin: 0 auto; padding: 24px; }
h1 { font-size: 20px; margin: 0 0 16px; } h2 { font-size: 15px; margin: 24px 0 8px; }
.muted { color: var(--muted); } .up { color: var(--up); } .down { color: var(--down); }
.tag { font-size: 11px; border: 1px solid var(--line); border-radius: 99px;
  padding: 0 6px; color: var(--muted); }
.tiles { display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }
.card { background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 16px; }
.tile .value { font-size: 28px; font-weight: 600; }
.bar { position: relative; height: 6px; background: var(--line);
  border-radius: 3px; margin: 8px 0; }
.bar > i { position: absolute; top: 0; bottom: 0; background: var(--accent);
  opacity: .35; border-radius: 3px; }
.bar > b { position: absolute; top: -3px; width: 2px; height: 12px;
  background: var(--accent); }
table { width: 100%; border-collapse: collapse; background: var(--surface);
  border: 1px solid var(--line); }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line);
  vertical-align: top; }
th { font-weight: 600; white-space: nowrap; }
tr.low td { color: var(--muted); }
form.filters, .row { display: flex; gap: 8px; align-items: end; flex-wrap: wrap; }
label { display: grid; gap: 2px; font-size: 12px; color: var(--muted); }
input, select, button { font: inherit; padding: 6px 8px;
  border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface); }
button { cursor: pointer; } button.primary { background: var(--accent);
  color: #fff; border-color: var(--accent); }
.answer { white-space: pre-wrap; } mark { background: var(--mark); }
.error { color: var(--down); }
```

```tsx
// apps/web/src/app/layout.tsx
import type { ReactNode } from "react";
import Link from "next/link";
import { logout } from "./login/actions";
import "./globals.css";

export const metadata = { title: "BSI operator" };

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav>
          <strong>BSI</strong>
          <Link href="/">Brands</Link>
          <Link href="/ops">Ops</Link>
          <span className="grow" />
          <form action={logout}>
            <button>Sign out</button>
          </form>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
```

```tsx
// apps/web/src/app/error.tsx
"use client";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="card">
      <h1>Something went wrong</h1>
      <p className="error">{error.message}</p>
      {error.digest && (
        <p className="muted">
          Digest {error.digest}. The problem and its request id are in the
          web server log.
        </p>
      )}
      <button onClick={reset}>Try again</button>
    </div>
  );
}
```

```tsx
// apps/web/src/app/not-found.tsx
export default function NotFound() {
  return <h1>Not found</h1>;
}
```

```ts
// apps/web/src/app/login/actions.ts
"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { API_URL, COOKIE } from "@/lib/api";

export async function login(_prev: string | undefined, form: FormData) {
  const key = String(form.get("key") ?? "").trim();
  let status: number;
  try {
    // Not api(): a 401 here is an answer, not a reason to redirect.
    const res = await fetch(`${API_URL}/v1/brands`, {
      headers: { Authorization: `Bearer ${key}` },
      cache: "no-store",
    });
    status = res.status;
  } catch {
    return `Cannot reach the API at ${API_URL}.`;
  }
  if (status === 401) return "That key was not accepted.";
  if (status !== 200) return `The API answered ${status}.`;
  (await cookies()).set(COOKIE, key, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 30,
  });
  redirect("/");
}

export async function logout() {
  (await cookies()).delete(COOKIE);
  redirect("/login");
}
```

```tsx
// apps/web/src/app/login/page.tsx
"use client";

import { useActionState } from "react";
import { login } from "./actions";

export default function Login() {
  const [error, action, pending] = useActionState(login, undefined);
  return (
    <form action={action} className="card" style={{ maxWidth: 420 }}>
      <h1>Sign in</h1>
      <label>
        API key
        <input name="key" type="password" required autoFocus />
      </label>
      {error && <p className="error">{error}</p>}
      <p>
        <button className="primary" disabled={pending}>
          Sign in
        </button>
      </p>
    </form>
  );
}
```

```tsx
// apps/web/src/app/page.tsx
import Link from "next/link";
import { api } from "@/lib/api";
import type { Brand } from "@/lib/types";

export default async function Brands() {
  const brands = await api<Brand[]>("/brands");
  return (
    <>
      <h1>Brands</h1>
      {brands.length === 0 && <p className="muted">No brands in this org.</p>}
      <ul>
        {brands.map((b) => (
          <li key={b.id}>
            <Link href={`/b/${b.id}`}>{b.name}</Link>
          </li>
        ))}
      </ul>
    </>
  );
}
```

- [ ] **Step 6: Verify in the real app.** Start the API (`uv run uvicorn bsi_api.main:app --port 8000`) and `npm run dev`. Create a key with `uv run python scripts/seed.py "Web check"`. Confirm: `/` redirects to `/login`; a wrong key shows "That key was not accepted."; the right key lands on the brand list; in the browser's dev tools the `bsi_key` cookie is HttpOnly; Sign out returns to `/login`.

- [ ] **Step 7: Both gates, then commit** — `feat(web): scaffold the operator dashboard with key login`

---

### Task 4: Brand overview page

**Files:**
- Create: `apps/web/src/components/Tile.tsx`, `apps/web/src/components/Filters.tsx`, `apps/web/src/app/b/[id]/layout.tsx`, `apps/web/src/app/b/[id]/page.tsx`

**Interfaces:**
- Consumes: `api`, `apiQuery`, `pct`, `ciText`, `pts`, types from Task 3; `/metrics`, `/deltas`, `/sov`.
- Produces: `<Tile>`, `<CiBar>`, `<Filters>` for Task 5.

- [ ] **Step 1: Components**

```tsx
// apps/web/src/components/Tile.tsx
import { ciText, pct, pts, type Rate } from "@/lib/format";
import type { Deltas } from "@/lib/types";

type Delta = NonNullable<Deltas["deltas"]>[string];

/** A 0-1 track with the interval shaded and the point estimate marked. */
export function CiBar({ r }: { r: Rate }) {
  if (r.value == null) return <div className="bar" />;
  return (
    <div className="bar" title={ciText(r)}>
      <i
        style={{
          left: `${r.ci_low * 100}%`,
          width: `${(r.ci_high - r.ci_low) * 100}%`,
        }}
      />
      <b style={{ left: `${r.value * 100}%` }} />
    </div>
  );
}

export function Tile({
  title,
  r,
  delta,
  days,
  tag,
}: {
  title: string;
  r: Rate;
  delta?: Delta;
  days: number;
  tag?: string;
}) {
  const tone =
    delta?.label === "increase" ? "up" : delta?.label === "decrease" ? "down" : "muted";
  return (
    <div className="card tile">
      <div>
        {title} {tag && <span className="tag">{tag}</span>}
      </div>
      <div className="value">{pct(r.value)}</div>
      <CiBar r={r} />
      <div className="muted">
        {r.value == null ? "No completed observations in this window" : ciText(r)}
      </div>
      {delta && (
        <div className={tone}>
          {delta.label === "increase" || delta.label === "decrease"
            ? `${pts(delta.value)} vs previous ${days} days`
            : delta.label}
        </div>
      )}
    </div>
  );
}
```

```tsx
// apps/web/src/components/Filters.tsx
import type { Params } from "@/lib/format";

const one = (v: Params[string]) => (typeof v === "string" ? v : "");

/** A plain GET form: the filters live in the URL with no client code.
 * ponytail: no locale picker; a locale_id in the URL is still honoured.
 * Add one when a brand has two locales. */
export function Filters({ sp, days }: { sp: Params; days?: boolean }) {
  return (
    <form className="filters" method="get">
      <label>
        Engine
        <select name="engine" defaultValue={one(sp.engine)}>
          <option value="">All</option>
          <option value="gemini">Gemini</option>
        </select>
      </label>
      <label>
        From
        <input type="date" name="date_from" defaultValue={one(sp.date_from)} />
      </label>
      <label>
        To
        <input type="date" name="date_to" defaultValue={one(sp.date_to)} />
      </label>
      {days && (
        <label>
          Compare days
          <input
            type="number"
            name="days"
            min={1}
            max={90}
            defaultValue={one(sp.days) || "7"}
          />
        </label>
      )}
      {one(sp.locale_id) && (
        <input type="hidden" name="locale_id" value={one(sp.locale_id)} />
      )}
      <button>Apply</button>
    </form>
  );
}
```

- [ ] **Step 2: Brand layout and page**

```tsx
// apps/web/src/app/b/[id]/layout.tsx
import type { ReactNode } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Brand } from "@/lib/types";

export default async function BrandLayout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const brand = await api<Brand>(`/brands/${id}`);
  return (
    <>
      <h1>{brand.name}</h1>
      <div className="row" style={{ marginBottom: 16 }}>
        <Link href={`/b/${id}`}>Overview</Link>
        <Link href={`/b/${id}/prompts`}>Prompts</Link>
        <Link href={`/b/${id}/label`}>Label</Link>
      </div>
      {children}
    </>
  );
}
```

```tsx
// apps/web/src/app/b/[id]/page.tsx
import { Filters } from "@/components/Filters";
import { Tile } from "@/components/Tile";
import { api } from "@/lib/api";
import { apiQuery, pct, type Params } from "@/lib/format";
import type { Deltas, Metrics, Sov } from "@/lib/types";

export default async function Overview({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const q = apiQuery(sp);
  // /deltas takes days and date_to; it refuses date_from.
  const dq = apiQuery(sp, ["days"], ["date_from"]);
  const [m, d, sov] = await Promise.all([
    api<Metrics>(`/brands/${id}/metrics${q}`),
    api<Deltas>(`/brands/${id}/deltas${dq}`),
    api<Sov>(`/brands/${id}/sov${q}`),
  ]);
  const days = Number(sp.days) || 7;
  const max = Math.max(...sov.entities.map((e) => e.share ?? 0), 0.0001);
  return (
    <>
      <Filters sp={sp} days />
      <h2>Visibility</h2>
      {!d.comparable && <p className="muted">Deltas hidden: {d.reason}</p>}
      <div className="tiles">
        <Tile title="Mention rate" r={m.mention_rate} days={days}
          delta={d.deltas?.mention_rate} />
        <Tile title="Recommendation rate" r={m.recommendation_rate} days={days}
          delta={d.deltas?.recommendation_rate}
          tag={m.recommendation_rate.experimental ? "experimental" : undefined} />
        <Tile title="Citation rate" r={m.citation_rate} days={days}
          delta={d.deltas?.citation_rate} />
        <Tile title="Share of voice" r={m.sov} days={days} delta={d.deltas?.sov} />
        <Tile title="Prompt coverage" r={m.prompt_coverage} days={days}
          delta={d.deltas?.prompt_coverage} />
      </div>
      <p className="muted">
        {m.n_failed} failed observations in this window · pipeline v
        {m.pipeline_version}
      </p>
      <h2>Share of voice</h2>
      <table>
        <tbody>
          {sov.entities.map((e) => (
            <tr key={e.entity_id}>
              <td style={{ width: 200 }}>
                {e.name} {e.type === "brand" && <span className="tag">you</span>}
              </td>
              <td>
                <div className="bar">
                  <i style={{ left: 0, width: `${((e.share ?? 0) / max) * 100}%`,
                    opacity: 1 }} />
                </div>
              </td>
              <td style={{ width: 220 }}>
                {pct(e.share)} · {e.mentions} mentions
                <div className="muted">
                  {pct(e.ci_low)}–{pct(e.ci_high)}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
```

- [ ] **Step 3: Verify against the API.** Sign in with the "Run 1" org's key (if it is lost, make a new key for that org in a Python shell as `tests/conftest.py: make_org` does, against the dev database). For the brand, compare the page to `curl -s -H "Authorization: Bearer $KEY" localhost:8000/v1/brands/$BID/metrics`: `mention_rate.value`, `n`, `ci_low`, `ci_high` must match the tile to the displayed precision. Set a From date, press Apply, confirm the URL carries `date_from` and the numbers change. Confirm the recommendation tile shows the *experimental* tag.

- [ ] **Step 4: Frontend gate, then commit** — `feat(web): brand overview with intervals, deltas and share of voice`

---

### Task 5: Prompt table, prompt detail, observation evidence

**Files:**
- Create: `apps/web/src/app/b/[id]/prompts/page.tsx`, `apps/web/src/app/b/[id]/prompts/[pid]/page.tsx`, `apps/web/src/app/o/[oid]/page.tsx`

**Interfaces:**
- Consumes: `GET /brands/{id}/prompts/metrics` (Task 2), `GET /observations?brand_id=&prompt_id=`, `GET /observations/{id}` with `text` (Task 1), `highlight`, `<Filters>`, `<CiBar>`.

- [ ] **Step 1: Prompt table.** Sorting is done here on the returned rows through `?sort=&dir=` links, so there is no client component.

```tsx
// apps/web/src/app/b/[id]/prompts/page.tsx
import Link from "next/link";
import { Filters } from "@/components/Filters";
import { CiBar } from "@/components/Tile";
import { api } from "@/lib/api";
import { apiQuery, ciText, pct, pts, type Params } from "@/lib/format";
import type { PromptMetrics } from "@/lib/types";

const LOW_N = 5; // below this the interval is too wide to read anything into

const KEYS: Record<string, (r: PromptMetrics) => number | null> = {
  n: (r) => r.n,
  brand: (r) => r.brand.value,
  top: (r) => r.top_competitor?.value ?? null,
  spread: (r) => r.spread,
};

export default async function Prompts({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const rows = await api<PromptMetrics[]>(
    `/brands/${id}/prompts/metrics${apiQuery(sp)}`,
  );
  const sort = typeof sp.sort === "string" && sp.sort in KEYS ? sp.sort : "spread";
  const dir = sp.dir === "asc" ? 1 : -1;
  const key = KEYS[sort];
  rows.sort((a, b) => {
    const [x, y] = [key(a), key(b)];
    if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
    return (x - y) * dir;
  });
  const head = (k: string, label: string) => {
    const q = new URLSearchParams();
    for (const [name, v] of Object.entries(sp))
      if (typeof v === "string" && v) q.set(name, v);
    q.set("sort", k);
    q.set("dir", sort === k && dir === -1 ? "asc" : "desc");
    return (
      <th>
        <Link href={`?${q}`}>
          {label}
          {sort === k ? (dir === -1 ? " ↓" : " ↑") : ""}
        </Link>
      </th>
    );
  };
  return (
    <>
      <Filters sp={sp} />
      <p className="muted">
        {rows.filter((r) => r.separated).length} of {rows.length} prompts
        separate the brand from its top rival (intervals do not overlap).
      </p>
      {rows.length === 0 && (
        <p className="muted">No completed observations in this window.</p>
      )}
      <table>
        <thead>
          <tr>
            <th>Prompt</th>
            <th>Intent</th>
            {head("n", "n")}
            {head("brand", "Brand")}
            {head("top", "Top rival")}
            {head("spread", "Spread")}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.prompt_id} className={r.n < LOW_N ? "low" : undefined}>
              <td>
                <Link href={`/b/${id}/prompts/${r.prompt_id}`}>{r.text}</Link>
                {r.topic && <div className="muted">{r.topic}</div>}
              </td>
              <td>{r.intent ?? "—"}</td>
              <td>{r.n}</td>
              <td title={ciText(r.brand)} style={{ minWidth: 140 }}>
                {pct(r.brand.value)}
                <CiBar r={r.brand} />
              </td>
              <td title={r.top_competitor ? ciText(r.top_competitor) : ""}
                style={{ minWidth: 140 }}>
                {r.top_competitor
                  ? `${r.top_competitor.name} ${pct(r.top_competitor.value)}`
                  : "—"}
                {r.top_competitor && <CiBar r={r.top_competitor} />}
              </td>
              <td>
                {pts(r.spread)}{" "}
                {r.separated && <span className="tag">separates</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
```

- [ ] **Step 2: Prompt detail**

```tsx
// apps/web/src/app/b/[id]/prompts/[pid]/page.tsx
import Link from "next/link";
import { api } from "@/lib/api";
import { usd } from "@/lib/format";
import type { Observation } from "@/lib/types";

export default async function PromptDetail({
  params,
}: {
  params: Promise<{ id: string; pid: string }>;
}) {
  const { id, pid } = await params;
  const rows = await api<Observation[]>(
    `/observations?brand_id=${id}&prompt_id=${pid}&limit=200`,
  );
  return (
    <>
      <h2>Observations for this prompt</h2>
      {rows.length === 0 && <p className="muted">None yet.</p>}
      <table>
        <thead>
          <tr>
            <th>Requested</th><th>Sample</th><th>Status</th><th>Model</th>
            <th>Cost</th><th>Error</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((o) => (
            <tr key={o.id}>
              <td>
                <Link href={`/o/${o.id}`}>
                  {o.requested_at.slice(0, 16).replace("T", " ")}
                </Link>
              </td>
              <td>{o.sample_index}</td>
              <td>{o.status}</td>
              <td>{o.model_version ?? o.model ?? "—"}</td>
              <td>{usd(o.cost_micros)}</td>
              <td className="error">{o.error}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
```

- [ ] **Step 3: Observation evidence page**

```tsx
// apps/web/src/app/o/[oid]/page.tsx
import Link from "next/link";
import { api } from "@/lib/api";
import { highlight, usd } from "@/lib/format";
import type { Brand, ObservationDetail } from "@/lib/types";

type Competitor = { id: string; name: string };

export default async function ObservationPage({
  params,
}: {
  params: Promise<{ oid: string }>;
}) {
  const { oid } = await params;
  const o = await api<ObservationDetail>(`/observations/${oid}`);
  const [brand, rivals] = await Promise.all([
    api<Brand>(`/brands/${o.brand_id}`),
    api<Competitor[]>(`/brands/${o.brand_id}/competitors`),
  ]);
  const names = new Map<string, string>([
    [brand.id, brand.name],
    ...rivals.map((c): [string, string] => [c.id, c.name]),
  ]);
  const evidence = o.mentions
    .map((m) => m.evidence_sentence)
    .filter((s): s is string => !!s);
  return (
    <>
      <p>
        <Link href={`/b/${o.brand_id}/prompts/${o.prompt_id}`}>← {brand.name}</Link>
      </p>
      <h1>Observation</h1>
      <p className="muted">
        {o.status} · {o.model_version ?? o.model} · engine {usd(o.cost_micros)}
        {o.extraction && ` + judge ${usd(o.extraction.cost_micros)}`}
      </p>
      {o.error && <p className="error">{o.error}</p>}
      <h2>Mentions</h2>
      {o.mentions.length === 0 && <p className="muted">Nobody was mentioned.</p>}
      <table>
        <tbody>
          {o.mentions.map((m) => (
            <tr key={m.entity_id}>
              <td>#{m.position}</td>
              <td>{names.get(m.entity_id) ?? m.entity_id}</td>
              <td>{m.rec_status}</td>
              <td>{m.sentiment}</td>
              <td className="muted">{m.evidence_sentence}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h2>Answer</h2>
      <div className="card answer">
        {o.text == null
          ? "No stored answer."
          : highlight(o.text, evidence).map((p, i) =>
              p.hit ? <mark key={i}>{p.text}</mark> : <span key={i}>{p.text}</span>,
            )}
      </div>
      <h2>Citations</h2>
      {o.citations.length === 0 && <p className="muted">None.</p>}
      <ol>
        {o.citations.map((c) => (
          <li key={c.position}>
            {c.domain} {c.is_brand_owned && <span className="tag">owned</span>}
          </li>
        ))}
      </ol>
    </>
  );
}
```

If `CompetitorOut` is in the generated schema, use `components["schemas"]["CompetitorOut"]` (add `export type Competitor = S["CompetitorOut"]` to `types.ts`) instead of the local `Competitor` type.

- [ ] **Step 4: Verify.** On the "Run 1" brand: the table lists prompts, default-sorted by spread; clicking a header flips the arrow and the order and keeps the date filter in the URL; a prompt opens its observations; an observation shows the answer with at least one highlighted sentence and the mention rows name the entities.

- [ ] **Step 5: Frontend gate, then commit** — `feat(web): prompt table with drill-down to the evidence`

---

### Task 6: Migration 0008 — `search_queries` and `rec_label`

Whether an answer actually searched is computed in `gemini.py` for pricing and then discarded. Store it. The same migration adds the label table for Task 8.

**Files:**
- Create: `migrations/versions/0008_search_queries_and_labels.py`, `scripts/backfill_search_queries.py`
- Modify: `packages/core/bsi_core/models.py`, `providers/base.py`, `providers/gemini.py`, `apps/workers/bsi_workers/worker.py`, `apps/api/bsi_api/routers/observations.py`
- Test: `tests/unit/test_gemini_adapter.py`, `tests/integration/test_worker.py`, `tests/integration/test_rls.py`, `tests/integration/test_constraints.py` (append to each)

**Interfaces:**
- Produces: `models.REC_STATUSES: tuple[str, ...]`; `models.RecLabel` (`observation_id`, `entity_type`, `entity_id`, `label`); `Observation.search_queries: int | None`; `EngineResult.search_queries: int | None`; `GeminiGroundingAdapter.search_queries(raw) -> int` (static); `ObservationOut.search_queries`.

- [ ] **Step 1: Failing tests**

```python
# tests/unit/test_gemini_adapter.py (append)
def test_search_queries_counts_the_queries_run():
    count = GeminiGroundingAdapter.search_queries
    meta = {"web_search_queries": ["a", "b"]}
    assert count({"candidates": [{"grounding_metadata": meta}]}) == 2
    assert count({"candidates": [{}]}) == 0 and count({}) == 0
```

```python
# tests/integration/test_worker.py (append)
def test_ok_path_stores_the_search_query_count(owner, queued):
    _, obs_id = queued
    result = EngineResult(
        "ok", raw={"x": 1}, model="fake-1", search_queries=3
    )
    process_one(FakeAdapter(result), LocalRawStore(), no_extract)
    assert load(owner, obs_id).search_queries == 3
```

```python
# tests/integration/test_constraints.py (append; use the file's existing
# imports and its way of expecting IntegrityError)
def test_rec_label_rejects_an_unknown_label(
    owner, make_org, make_brand, make_observation
):
    org = make_org()
    bid = make_brand(org)
    oid = make_observation(org, bid, status="done")
    with pytest.raises(IntegrityError), owner() as s, s.begin():
        s.add(
            m.RecLabel(
                org_id=org.id,
                observation_id=oid,
                entity_type="brand",
                entity_id=bid,
                label="brilliant",
            )
        )
```

In `test_rls.py`: add `"rec_label"` to `TENANT_TABLES`, and in the `org_b` fixture add one `m.RecLabel(org_id=b.id, observation_id=<the observation that fixture already creates for its mention>, entity_type="brand", entity_id=bid, label="listed")` to the same `add_all`. `test_tenant_table_list_matches_the_schema` fails until the migration exists; `test_fixture_populates_every_tenant_table` fails until the fixture row does.

Run the four files; paste the failures.

- [ ] **Step 2: Models** (`models.py`). Next to `INTENTS`:

```python
REC_STATUSES = ("recommended", "listed", "mentioned", "negative")
```

On `Observation`: `search_queries: Mapped[int | None]`. After `Citation`:

```python
class RecLabel(Tenant, Base):
    """A hand label for one mention, to score the judge against."""

    __tablename__ = "rec_label"
    observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("observation.id")
    )
    entity_type: Mapped[str]
    entity_id: Mapped[uuid.UUID]
    label: Mapped[str]
    __table_args__ = (
        UniqueConstraint("observation_id", "entity_id"),
        CheckConstraint(
            "label IN (" + ", ".join(f"'{x}'" for x in REC_STATUSES) + ")",
            name="ck_rec_label_label",
        ),
    )
```

- [ ] **Step 3: Migration**

```python
# migrations/versions/0008_search_queries_and_labels.py
"""observation.search_queries, and the rec_label table with its RLS"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column(
        "observation", sa.Column("search_queries", sa.Integer(), nullable=True)
    )
    op.create_table(
        "rec_label",
        sa.Column("observation_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
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
        sa.CheckConstraint(
            "label IN ('recommended', 'listed', 'mentioned', 'negative')",
            name="ck_rec_label_label",
        ),
        sa.ForeignKeyConstraint(["observation_id"], ["observation.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organization.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("observation_id", "entity_id"),
    )
    op.create_index("ix_rec_label_org_id", "rec_label", ["org_id"])
    op.execute("ALTER TABLE rec_label ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE rec_label FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant ON rec_label "
        f"USING (org_id = {SETTING}) WITH CHECK (org_id = {SETTING})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON rec_label TO bsi_app")


def downgrade() -> None:
    op.drop_table("rec_label")
    op.drop_column("observation", "search_queries")
```

Match the constraint and index names to what `0006`/`0007` produce (check `alembic check` below); `alembic check` does not diff CHECK constraints, so compare the label list to `REC_STATUSES` by eye.

Run: `uv run alembic upgrade head && uv run alembic check`. Expected: "No new upgrade operations detected."

- [ ] **Step 4: Adapter, result, worker, API**

`base.py`, on `EngineResult`: `search_queries: int | None = None`.

`gemini.py`: add the static method, use it in `cost()`, and set it on the ok result.

```python
    @classmethod
    def search_queries(cls, raw: dict[str, Any]) -> int:
        meta = cls._candidate(raw).get("grounding_metadata") or {}
        return len(meta.get("web_search_queries") or [])
```

In `cost()`, `queries = self.search_queries(raw)` replaces the inline `len(...)`. In `query()`, compute `search_queries = self.search_queries(raw)` inside the existing `try` that derives fields from `raw`, and pass `search_queries=search_queries` to the ok `EngineResult`.

`worker.py`, in `process_one` beside `obs.cost_micros = result.cost_micros`: `obs.search_queries = result.search_queries`.

`observations.py`, on `ObservationOut`: `search_queries: int | None`.

- [ ] **Step 5: Backfill script**

```python
# scripts/backfill_search_queries.py
"""Fill observation.search_queries from the stored raw payloads.

Owner-side and idempotent. usage: python scripts/backfill_search_queries.py
"""

from bsi_core import models as m
from bsi_core.db import owner_engine
from bsi_core.providers.gemini import GeminiGroundingAdapter
from bsi_core.storage import LocalRawStore
from sqlalchemy import select
from sqlalchemy.orm import Session

store, done = LocalRawStore(), 0
with Session(owner_engine()) as s, s.begin():
    rows = s.scalars(
        select(m.Observation).where(
            m.Observation.raw_uri.is_not(None),
            m.Observation.search_queries.is_(None),
        )
    )
    for obs in rows:
        raw = store.get(obs.raw_uri, obs.org_id)
        obs.search_queries = GeminiGroundingAdapter.search_queries(raw)
        done += 1
print(f"backfilled {done} observations")
```

Run it against the dev database (`uv run alembic upgrade head` first), then check: `SELECT count(*) FILTER (WHERE search_queries > 0), count(search_queries) FROM observation;` through a Python owner session. Record both numbers for the findings doc.

- [ ] **Step 6: Tests, backend gate, `cd apps/web && npm run gen`, frontend gate, commit** — `feat: store search query counts; add the rec_label table`

---

### Task 7: Ops endpoint and page

**Files:**
- Modify: `packages/core/bsi_core/scheduling.py`, `apps/api/bsi_api/main.py`
- Create: `apps/api/bsi_api/routers/ops.py`, `apps/web/src/app/ops/page.tsx`
- Test: `tests/integration/test_api_ops.py` (create)

**Interfaces:**
- Consumes: `_SPENT_AND_PENDING`, `budget_micros`, `metrics.rate`, `Observation.search_queries` (Task 6).
- Produces: `spent_and_pending(s) -> tuple[int, int]`, `ops_summary(s, org_id) -> dict[str, Any]`; `GET /v1/ops` → `OpsOut`.

- [ ] **Step 1: Failing test**

```python
# tests/integration/test_api_ops.py
from bsi_core import models as m
from sqlalchemy import update


def test_ops_reports_spend_queue_failures_and_search_rate(
    client, owner, make_org, make_brand, make_observation
):
    a, b = make_org("A"), make_org("B")
    bid = make_brand(a)
    searched = make_observation(a, bid, status="done")
    plain = make_observation(a, bid, status="done", text="p2")
    failed = make_observation(a, bid, status="failed", text="p3")
    make_observation(a, bid, status="queued", text="p4")
    make_observation(b, make_brand(b), status="queued")
    with owner() as s, s.begin():
        for oid, values in (
            (searched, {"cost_micros": 46_000, "search_queries": 2}),
            (plain, {"cost_micros": 13_000, "search_queries": 0}),
            (failed, {"error": "400 bad"}),
        ):
            s.execute(
                update(m.Observation)
                .where(m.Observation.id == oid)
                .values(**values)
            )
        s.add(
            m.Job(
                org_id=a.id, brand_id=bid, kind="prompts", cost_micros=1_000,
                scheduled_slot=s.get(m.Observation, searched).scheduled_slot,
            )
        )
    body = client.get("/v1/ops", headers=a.headers).json()
    assert body["spent_micros"] == 60_000  # 46k + 13k + the non-run job
    assert body["pending"] == 1
    assert body["budget_micros"] == 2_000_000
    assert body["queue"] == {"done": 2, "failed": 1, "queued": 1}
    assert (body["searched"]["value"], body["searched"]["n"]) == (0.5, 2)
    assert [f["error"] for f in body["failures"]] == ["400 bad"]
    assert body["schedules"] == []


def test_ops_is_scoped_to_the_caller(client, make_org):
    body = client.get("/v1/ops", headers=make_org().headers).json()
    assert body["spent_micros"] == 0 and body["queue"] == {}
    assert client.get("/v1/ops").status_code == 401
```

If `m.Job` needs other required fields, copy them from how `tests/integration/test_budget.py` builds a non-run job. Run; expected 404 on `/v1/ops`.

- [ ] **Step 2: Core.** In `scheduling.py`, give the shared query one entry point and use it in `budget_fits` (replacing its inline `s.execute(_SPENT_AND_PENDING).one()`):

```python
def spent_and_pending(s: Session) -> tuple[int, int]:
    """Today's spend in micros and the observations still to run.

    Scoped by row-level security: call it in the org's tenant session.
    """
    spent, pending = s.execute(_SPENT_AND_PENDING).one()
    return int(spent), int(pending)


def ops_summary(s: Session, org_id: uuid.UUID) -> dict[str, Any]:
    """What the operator page shows. Call in the org's tenant session."""
    from .metrics import rate

    spent, pending = spent_and_pending(s)
    queue = dict(
        s.execute(
            select(m.Observation.status, func.count()).group_by(
                m.Observation.status
            )
        )
        .tuples()
        .all()
    )
    searched, known = s.execute(
        text(
            "SELECT count(*) FILTER (WHERE search_queries > 0), "
            "count(search_queries) FROM observation "
            "WHERE status = 'done' "
            "AND requested_at >= now() - interval '7 days'"
        )
    ).one()
    failures = s.scalars(
        select(m.Observation)
        .where(m.Observation.status == "failed")
        .order_by(m.Observation.requested_at.desc())
        .limit(20)
    ).all()
    schedules = s.execute(
        select(m.Schedule, m.Brand.name)
        .join(m.Brand, m.Brand.id == m.Schedule.brand_id)
        .order_by(m.Schedule.next_run_at)
    ).all()
    return {
        "spent_micros": spent,
        "pending": pending,
        "budget_micros": budget_micros(s, org_id),
        "estimate_micros": get_settings().obs_cost_estimate_micros,
        "queue": queue,
        "searched": rate(searched, known),
        "failures": failures,
        "schedules": [
            {"brand_name": name, **{c: getattr(row, c) for c in _SCHEDULE}}
            for row, name in schedules
        ],
    }


_SCHEDULE = (
    "brand_id", "cadence", "hour_utc", "samples", "status",
    "next_run_at", "last_run_at", "last_result",
)
```

Define `_SCHEDULE` above `ops_summary`. Add any missing imports (`Any`, `func`, `select`). The import of `rate` is local to avoid a cycle if one appears; make it top-level if `mypy` and the tests are happy.

- [ ] **Step 3: Router**

```python
# apps/api/bsi_api/routers/ops.py
import uuid
from datetime import datetime
from typing import Any

from bsi_core.scheduling import ops_summary
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from ..deps import TENANT, Ctx
from .metrics import Rate

router = APIRouter(prefix="/ops", tags=["ops"])


class FailureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    brand_id: uuid.UUID
    prompt_id: uuid.UUID
    error: str | None
    attempts: int
    requested_at: datetime


class ScheduleRow(BaseModel):
    brand_id: uuid.UUID
    brand_name: str
    cadence: str
    hour_utc: int
    samples: int
    status: str
    next_run_at: datetime
    last_run_at: datetime | None
    last_result: str | None


class OpsOut(BaseModel):
    spent_micros: int
    pending: int
    budget_micros: int
    estimate_micros: int
    queue: dict[str, int]
    searched: Rate
    failures: list[FailureOut]
    schedules: list[ScheduleRow]


@router.get("", response_model=OpsOut)
def get_ops(c: Ctx = TENANT) -> dict[str, Any]:
    return ops_summary(c.s, c.org_id)
```

Register `ops.router` in `main.py`'s router tuple.

- [ ] **Step 4: Tests, backend gate, `npm run gen`.** Add `export type Ops = S["OpsOut"];` to `types.ts`.

- [ ] **Step 5: Page**

```tsx
// apps/web/src/app/ops/page.tsx
import Link from "next/link";
import { CiBar } from "@/components/Tile";
import { api } from "@/lib/api";
import { ciText, pct, usd } from "@/lib/format";
import type { Ops } from "@/lib/types";

export default async function OpsPage() {
  const o = await api<Ops>("/ops");
  const committed = o.spent_micros + o.pending * o.estimate_micros;
  const used = { value: Math.min(committed / o.budget_micros, 1), n: 0,
    ci_low: 0, ci_high: Math.min(o.spent_micros / o.budget_micros, 1) };
  return (
    <>
      <h1>Ops</h1>
      <div className="tiles">
        <div className="card tile">
          <div>Spend today (UTC)</div>
          <div className="value">{usd(o.spent_micros)}</div>
          <CiBar r={used} />
          <div className="muted">
            of {usd(o.budget_micros)} · {o.pending} pending ≈{" "}
            {usd(o.pending * o.estimate_micros)}
          </div>
        </div>
        <div className="card tile">
          <div>Answers that searched (7 days)</div>
          <div className="value">{pct(o.searched.value)}</div>
          <CiBar r={o.searched} />
          <div className="muted">{ciText(o.searched)}</div>
        </div>
        <div className="card tile">
          <div>Queue</div>
          {Object.entries(o.queue).map(([k, v]) => (
            <div key={k}>
              {k}: {v}
            </div>
          ))}
          {Object.keys(o.queue).length === 0 && <div className="muted">Empty</div>}
        </div>
      </div>
      <h2>Schedules</h2>
      {o.schedules.length === 0 && <p className="muted">None.</p>}
      <table>
        <tbody>
          {o.schedules.map((s) => (
            <tr key={s.brand_id}>
              <td><Link href={`/b/${s.brand_id}`}>{s.brand_name}</Link></td>
              <td>{s.cadence} at {s.hour_utc}:00 UTC × {s.samples}</td>
              <td>{s.status}</td>
              <td>next {s.next_run_at.slice(0, 16).replace("T", " ")}</td>
              <td className="muted">{s.last_result ?? "never run"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h2>Recent failures</h2>
      {o.failures.length === 0 && <p className="muted">None.</p>}
      <table>
        <tbody>
          {o.failures.map((f) => (
            <tr key={f.id}>
              <td>
                <Link href={`/o/${f.id}`}>
                  {f.requested_at.slice(0, 16).replace("T", " ")}
                </Link>
              </td>
              <td>{f.attempts} attempts</td>
              <td className="error">{f.error}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
```

The spend bar reuses `CiBar` as a plain meter: the marker is spend plus pending estimates, the shaded part is money already spent. This is a division for display, not a visibility metric.

- [ ] **Step 6: Verify** on the dev database after the Task 6 backfill: the searched rate shows a value with its interval; failures link to their observation.

- [ ] **Step 7: Both gates, commit** — `feat: ops summary endpoint and page`

---

### Task 8: Labelling

**Files:**
- Create: `apps/api/bsi_api/routers/labels.py`, `apps/web/src/app/b/[id]/label/page.tsx`, `apps/web/src/app/b/[id]/label/actions.ts`
- Modify: `apps/api/bsi_api/main.py`, `scripts/export_rec_labels.py`
- Test: `tests/integration/test_api_labels.py` (create)

**Interfaces:**
- Consumes: `m.RecLabel`, `REC_STATUSES` (Task 6), `answer_text` (Task 1), `metrics.Rate`.
- Produces: `GET /v1/brands/{brand_id}/labels/next` → `LabelQueue {item: LabelItem | None, labelled: int, remaining: int, agreement: Rate}`; `PUT /v1/observations/{observation_id}/labels/{entity_id}` body `{label}` → `LabelResult {label, judge, agrees}`.

**The queue never returns the judge's verdict.** It is revealed only by the PUT response, after the label is saved.

- [ ] **Step 1: Failing tests**

```python
# tests/integration/test_api_labels.py
import json
from pathlib import Path

import pytest
from bsi_core import models as m

RAW = json.loads(Path("tests/fixtures/gemini_min.json").read_text())


@pytest.fixture
def labelled_scene(owner, make_org, make_brand, make_observation):
    org = make_org()
    bid = make_brand(org, "Nike")
    oid = make_observation(org, bid, raw=RAW, status="done")
    with owner() as s, s.begin():
        s.add(
            m.Mention(
                org_id=org.id,
                observation_id=oid,
                entity_type="brand",
                entity_id=bid,
                position=1,
                rec_status="recommended",
                sentiment="positive",
                evidence_sentence="Nike is best.",
            )
        )
    return org, bid, oid


def test_queue_hides_the_verdict_then_put_reveals_it(client, labelled_scene):
    org, bid, oid = labelled_scene
    queue = client.get(f"/v1/brands/{bid}/labels/next", headers=org.headers).json()
    item = queue["item"]
    assert (item["observation_id"], item["entity_name"]) == (str(oid), "Nike")
    assert item["evidence_sentence"] == "Nike is best." and item["text"]
    assert "rec_status" not in item and "judge" not in item
    assert (queue["labelled"], queue["remaining"]) == (0, 1)

    url = f"/v1/observations/{oid}/labels/{bid}"
    put = client.put(url, json={"label": "listed"}, headers=org.headers)
    assert put.json() == {
        "label": "listed", "judge": "recommended", "agrees": False
    }
    again = client.put(url, json={"label": "recommended"}, headers=org.headers)
    assert again.json()["agrees"] is True  # relabelling overwrites

    queue = client.get(f"/v1/brands/{bid}/labels/next", headers=org.headers).json()
    assert queue["item"] is None
    assert (queue["labelled"], queue["remaining"]) == (1, 0)
    assert (queue["agreement"]["value"], queue["agreement"]["n"]) == (1.0, 1)


def test_labels_reject_bad_input_and_other_tenants(
    client, make_org, labelled_scene
):
    org, bid, oid = labelled_scene
    url = f"/v1/observations/{oid}/labels/{bid}"
    bad = client.put(url, json={"label": "brilliant"}, headers=org.headers)
    assert bad.status_code == 422
    missing = client.put(
        f"/v1/observations/{oid}/labels/{oid}",
        json={"label": "listed"},
        headers=org.headers,
    )
    assert missing.status_code == 404  # no such mention
    other = make_org("B")
    assert (
        client.put(url, json={"label": "listed"}, headers=other.headers)
    ).status_code == 404
    assert (
        client.get(f"/v1/brands/{bid}/labels/next", headers=other.headers)
    ).status_code == 404
```

Run; expected 404/405 on both routes.

- [ ] **Step 2: Router**

```python
# apps/api/bsi_api/routers/labels.py
"""Hand labels for mentions, to score the judge against."""

import uuid
from typing import Any, Literal

from bsi_core import models as m
from bsi_core.metrics import rate
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from ..deps import TENANT, Ctx, brand_or_404, get_or_404
from ..problems import Problem
from .metrics import Rate
from .observations import answer_text

router = APIRouter(tags=["labels"])

# Keep in step with models.REC_STATUSES; a Literal gives the 422 and the
# TypeScript union for free.
RecStatus = Literal["recommended", "listed", "mentioned", "negative"]


class LabelItem(BaseModel):
    observation_id: uuid.UUID
    entity_id: uuid.UUID
    entity_type: str
    entity_name: str
    evidence_sentence: str | None
    text: str | None


class LabelQueue(BaseModel):
    item: LabelItem | None
    labelled: int
    remaining: int
    agreement: Rate


class LabelIn(BaseModel):
    label: RecStatus


class LabelResult(BaseModel):
    label: str
    judge: str
    agrees: bool


def _mentions(brand_id: uuid.UUID) -> Any:
    """Mentions in the brand's done observations, joined to their label."""
    return (
        select(m.Mention, m.RecLabel)
        .join(m.Observation, m.Observation.id == m.Mention.observation_id)
        .outerjoin(
            m.RecLabel,
            (m.RecLabel.observation_id == m.Mention.observation_id)
            & (m.RecLabel.entity_id == m.Mention.entity_id),
        )
        .where(
            m.Observation.brand_id == brand_id,
            m.Observation.status == "done",
        )
    )


@router.get("/brands/{brand_id}/labels/next", response_model=LabelQueue)
def next_label(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
    brand = brand_or_404(c, brand_id)
    rows = c.s.execute(
        _mentions(brand_id).order_by(
            m.Observation.requested_at, m.Observation.id, m.Mention.position
        )
    ).all()
    done = [(mn, lb) for mn, lb in rows if lb is not None]
    todo = [mn for mn, lb in rows if lb is None]
    item = None
    if todo:
        mn = todo[0]
        name = (
            brand.name
            if mn.entity_type == "brand"
            else get_or_404(c.s, m.Competitor, mn.entity_id).name
        )
        obs = c.s.get_one(m.Observation, mn.observation_id)
        item = {
            "observation_id": mn.observation_id,
            "entity_id": mn.entity_id,
            "entity_type": mn.entity_type,
            "entity_name": name,
            "evidence_sentence": mn.evidence_sentence,
            "text": answer_text(obs, c.org_id),
        }
    agree = sum(1 for mn, lb in done if lb.label == mn.rec_status)
    return {
        "item": item,
        "labelled": len(done),
        "remaining": len(todo),
        "agreement": rate(agree, len(done)),
    }


@router.put(
    "/observations/{observation_id}/labels/{entity_id}",
    response_model=LabelResult,
)
def put_label(
    observation_id: uuid.UUID,
    entity_id: uuid.UUID,
    body: LabelIn,
    c: Ctx = TENANT,
) -> dict[str, Any]:
    mention = c.s.scalars(
        select(m.Mention).where(
            m.Mention.observation_id == observation_id,
            m.Mention.entity_id == entity_id,
        )
    ).first()
    if mention is None:  # includes another tenant's: RLS hides it
        raise Problem(404, "Not found")
    c.s.execute(
        insert(m.RecLabel)
        .values(
            org_id=c.org_id,
            observation_id=observation_id,
            entity_type=mention.entity_type,
            entity_id=entity_id,
            label=body.label,
        )
        .on_conflict_do_update(
            index_elements=["observation_id", "entity_id"],
            set_={"label": body.label},
        )
    )
    return {
        "label": body.label,
        "judge": mention.rec_status,
        "agrees": body.label == mention.rec_status,
    }
```

```
# ponytail: next_label loads every mention of the brand to count and pick.
# Fine for hundreds of labels; move the counts into SQL past ~10k mentions.
```

Put that comment above the `rows = ...` query. Remove the unused `func` import if ruff flags it. Register `labels.router` in `main.py`. Add a unit assertion to `test_api_labels.py` that the Literal and the constant agree:

```python
def test_label_vocabulary_matches_the_model():
    from typing import get_args

    from bsi_api.routers.labels import RecStatus

    assert get_args(RecStatus) == m.REC_STATUSES
```

- [ ] **Step 3: Tests, backend gate, `npm run gen`.** Add to `types.ts`: `export type LabelQueue = S["LabelQueue"]; export type LabelResult = S["LabelResult"];`

- [ ] **Step 4: Page and action.** No client component: four submit buttons post a server action, which redirects back with the result in the URL.

```ts
// apps/web/src/app/b/[id]/label/actions.ts
"use server";

import { redirect } from "next/navigation";
import { api } from "@/lib/api";
import type { LabelResult } from "@/lib/types";

export async function saveLabel(form: FormData) {
  const get = (k: string) => String(form.get(k));
  const r = await api<LabelResult>(
    `/observations/${get("observation_id")}/labels/${get("entity_id")}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: get("label") }),
    },
  );
  const q = new URLSearchParams({ you: r.label, judge: r.judge });
  redirect(`/b/${get("brand_id")}/label?${q}`);
}
```

```tsx
// apps/web/src/app/b/[id]/label/page.tsx
import { api } from "@/lib/api";
import { ciText, highlight, pct, type Params } from "@/lib/format";
import type { LabelQueue } from "@/lib/types";
import { saveLabel } from "./actions";

const LABELS = [
  ["recommended", "Recommended: endorsed as a good choice"],
  ["listed", "Listed: one option among several, no endorsement"],
  ["mentioned", "Mentioned: named in passing"],
  ["negative", "Negative: advised against"],
] as const;

export default async function Label({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Params>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const q = await api<LabelQueue>(`/brands/${id}/labels/next`);
  const item = q.item;
  return (
    <>
      <p className="muted">
        {q.labelled} labelled · {q.remaining} to go · judge agreement{" "}
        {pct(q.agreement.value)} ({ciText(q.agreement)})
      </p>
      {typeof sp.you === "string" && (
        <p className={sp.you === sp.judge ? "up" : "down"}>
          Last: you said {sp.you}, the judge said {sp.judge}.
        </p>
      )}
      {!item && <p>Nothing left to label for this brand.</p>}
      {item && (
        <>
          <h2>How does this answer treat {item.entity_name}?</h2>
          <form action={saveLabel} className="row">
            <input type="hidden" name="brand_id" value={id} />
            <input type="hidden" name="observation_id" value={item.observation_id} />
            <input type="hidden" name="entity_id" value={item.entity_id} />
            {LABELS.map(([value, help]) => (
              <button key={value} name="label" value={value} title={help}>
                {value}
              </button>
            ))}
          </form>
          <h2>Answer</h2>
          <div className="card answer">
            {item.text == null
              ? (item.evidence_sentence ?? "No stored answer.")
              : highlight(
                  item.text,
                  item.evidence_sentence ? [item.evidence_sentence] : [],
                ).map((p, i) =>
                  p.hit ? <mark key={i}>{p.text}</mark> : <span key={i}>{p.text}</span>,
                )}
          </div>
        </>
      )}
    </>
  );
}
```

- [ ] **Step 5: Export.** Extend `scripts/export_rec_labels.py`: with `--from-db "Org name"` it reads the table instead of the benchmark file and prints the same row shape (`observation_id`, `text`, `entities`, `expected`, `reviewed: true`), one row per labelled observation, keyed by entity **name** as `rec_labels_v0.jsonl` is. Keep the existing no-argument behaviour byte-for-byte.

```python
def from_db(org_name: str) -> None:
    from bsi_core import models as m
    from bsi_core.db import owner_engine
    from bsi_core.providers.gemini import GeminiGroundingAdapter
    from bsi_core.storage import LocalRawStore
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    with Session(owner_engine()) as s:
        org = s.scalars(
            select(m.Organization).where(m.Organization.name == org_name)
        ).one()
        labels = s.scalars(
            select(m.RecLabel)
            .where(m.RecLabel.org_id == org.id)
            .order_by(m.RecLabel.observation_id, m.RecLabel.created_at)
        ).all()
        by_obs: dict = {}
        for lb in labels:
            by_obs.setdefault(lb.observation_id, []).append(lb)
        for obs_id, rows in by_obs.items():
            obs = s.get_one(m.Observation, obs_id)
            raw = LocalRawStore().get(obs.raw_uri, org.id)
            entities, expected = [], {}
            for lb in rows:
                model = m.Brand if lb.entity_type == "brand" else m.Competitor
                e = s.get_one(model, lb.entity_id)
                entities.append(
                    {
                        "id": e.name,
                        "type": lb.entity_type,
                        "aliases": [e.name, *e.aliases],
                    }
                )
                expected[e.name] = lb.label
            print(
                json.dumps(
                    {
                        "observation_id": str(obs_id),
                        "text": GeminiGroundingAdapter().parse(raw).text,
                        "entities": entities,
                        "expected": expected,
                        "reviewed": True,
                    },
                    ensure_ascii=False,
                )
            )
```

Wrap the existing loop in `def from_benchmark() -> None:` and dispatch at the bottom: `from_db(sys.argv[2]) if sys.argv[1:2] == ["--from-db"] else from_benchmark()`. Update the docstring's usage line. If `tests/unit/test_eval_sets.py` checks `rec_labels_v0.jsonl`'s row shape, run the new output through the same check by hand and note the result.

- [ ] **Step 6: Verify.** On the "Run 1" brand: the label page shows an entity, the answer with the evidence highlighted, and **no verdict**; pressing a button shows "you said X, the judge said Y" and moves to the next mention; the counters move; `SELECT count(*) FROM rec_label` (owner session) went up by one; `uv run python scripts/export_rec_labels.py --from-db "Run 1"` prints one JSON row.

- [ ] **Step 7: Both gates, commit** — `feat: hand-label judge verdicts, blind, with an export`

---

### Task 9: Review, audit, findings, docs

- [ ] **Step 1: Whole-branch review.** Use superpowers:requesting-code-review over `main..slice5-operator-dashboard`. Fix what it confirms; re-run both gates.
- [ ] **Step 2: Audit against the spec,** section by section, and against this plan's Global Constraints. Specifically re-check: the key never appears in client bundles (`grep -r bsi_key apps/web/.next/static` finds nothing); every new route returns 404 or `[]` across tenants; `alembic check` is clean on `bsi` and `bsi_test`; `bsi_core.metrics` is at 100%.
- [ ] **Step 3: Run the spec's Verification section end to end** in the browser pane, including a second org's key seeing none of the first org's brands.
- [ ] **Step 4: Write `docs/findings-slice5.md`:** the searched-rate from the backfill; how many prompts separate the brand from its top rival on "Run 1" and at what n; labels added and judge agreement with its interval; known gaps (no locale picker, no sparklines, `next_label` loads all mentions, production error pages show a digest only, on-demand runs still have no budget check).
- [ ] **Step 5: Docs.** Add the plan and findings rows to `docs/README.md`; add an `apps/web` section to the repo README's setup commands (`cd apps/web && npm install && npm run dev`, `API_URL`). Commit — `docs: slice 5 findings and index`.
- [ ] **Step 6:** Use superpowers:finishing-a-development-branch.
