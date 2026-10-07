# Slice 49 API Path Values Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every value interpolated into an `api()`/`publicApi()` path goes through `seg()`, and `api()`/`publicApi()` refuse a path `fetch` would not send as written.

**Architecture:** `apps/web/src/lib/api.ts` gains `seg(value)` (letters, digits, `-`, `_` only; otherwise a log line and `notFound()`) and `sendAsWritten(path)` (the parsed path plus query must equal the path; otherwise a log line and `notFound()`), called first in `api()` and `publicApi()`. The 28 call-site files wrap each interpolated value in `seg()`. A source-scan test fails if a value in an `src/app` path template skips `seg()`.

**Tech Stack:** Next.js 15 App Router (Server Components, server actions), TypeScript, vitest 3, Node 22.

**Spec:** `docs/superpowers/specs/2026-10-07-slice49-api-path-guard-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&` (or `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web &&` for npm and npx).
- **Branch:** `slice49-api-path-guard`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB (`bsi`), the network, the worker loop or DataForSEO. Never run `alembic` by hand. No backend file changes in this slice; do not run pytest.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal.)
- **Writing files:** use the Edit or Write tools; never a shell heredoc or zsh `echo` to write files. Never run `rm`.
- **Paths:** many paths contain `(app)` and `[id]`; quote them in every shell command.
- **Frontend:** Server Components and server actions only; do not add a Route Handler. Never call `redirect()` inside try/catch. Do not change any `redirect()` target. Do not run `npm run gen` other than through the gate's `gen:check` (no API change). Do not run Prettier on any file (the plan's code is already formatted as intended).
- **Banned words:** copy (code, comments, test names) never contains the words listed in `FORBIDDEN` in tests/unit/test_recommend_copy.py.
- **Banned-word grep (must block the commit):** `cd /Users/vineet/Downloads/ADK/bsi-platform && ! { git diff --cached -U0 | grep '^+' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'; }`, run after staging. Expected: exit 0 and no output.
- **Web gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate > <workspace>/gate-task<N>.txt 2>&1; echo "gate exit $?"` (N = the task number).
- **`<workspace>`:** the path given in your task brief; if none is given, stop and ask.
- **Commit trailer:** exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Baseline counts** (main `c45a729`): web `Tests  52 passed (52)`. After Task 1: 70 (api.test.ts 21). After Task 2: 71 (api-paths.test.ts 1).

## File map

| File | Responsibility | Task |
|---|---|---|
| `apps/web/src/lib/api.ts` | `sendAsWritten`, `seg`, the guard calls in `api()` and `publicApi()` | 1 |
| `apps/web/src/lib/api.test.ts` | guard and `seg` tests | 1 |
| `apps/web/src/lib/api-paths.test.ts` (new) | the source-scan test | 2 |
| the 28 files under `apps/web/src/app` listed in Task 2 | `seg()` on each interpolated value | 2 |

---

### Task 1: the guard and seg()

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Test: `apps/web/src/lib/api.test.ts`

**Interfaces:**
- Consumes: `notFound` (already imported in api.ts from `next/navigation`).
- Produces: `export function seg(value: string): string` in `@/lib/api` (Task 2 imports it); `api()` and `publicApi()` keep their signatures.

- [ ] **Step 1: Write the failing tests**

In `apps/web/src/lib/api.test.ts`:

1. Replace

```ts
const { publicApi } = await import("./api");
```

   with

```ts
const { api, publicApi, seg } = await import("./api");
const { cookies } = await import("next/headers");
```

2. Replace

```ts
afterEach(() => vi.unstubAllGlobals());
```

   with

```ts
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const signedIn = () =>
  vi.mocked(cookies).mockResolvedValue({
    get: () => ({ value: "bsi_key_1" }),
  } as never);
```

3. Replace

```ts
  expect(init).toEqual({ cache: "no-store" });
});
```

   with

```ts
  expect(init).toEqual({ cache: "no-store" });
});

test.each([
  "/brands/../x",
  "/brands/./x",
  "/brands/%2e%2E/x",
  "/brands/..\\x",
  "/brands/x#y",
  "/brands/x y",
  "/brands/x?",
  "/brands/x?a=b'c",
])("api refuses %s without calling the API", async (path) => {
  signedIn();
  const log = vi.spyOn(console, "error").mockImplementation(() => {});
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(api(path)).rejects.toThrow("NOT_FOUND");
  expect(fetchMock).not.toHaveBeenCalled();
  expect(log).toHaveBeenCalledWith("API path refused", path);
});

test("api sends a path with a query string as written", async () => {
  signedIn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("{}", { status: 200 })),
  );
  const path = "/brands/1eb6c00a-4b18-4512-b515-dd1d8039511f/sov?days=14";
  await api(path);
  expect(vi.mocked(fetch).mock.calls[0][0]).toBe(
    `http://localhost:8000/v1${path}`,
  );
});

test("publicApi refuses a dot segment", async () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(publicApi("/r/..")).rejects.toThrow("NOT_FOUND");
  expect(fetchMock).not.toHaveBeenCalled();
});

test("seg returns a UUID, a report type and a share token unchanged", () => {
  for (const v of [
    "1eb6c00a-4b18-4512-b515-dd1d8039511f",
    "cmo",
    "Ab3_-xYz9Ab3_-xYz9Ab3",
  ]) {
    expect(seg(v)).toBe(v);
  }
});

test.each(["", "..", "a/b", "a%2Fb", "a?b", "a#b", "a b"])(
  "seg refuses %j",
  (value) => {
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => seg(value)).toThrow("NOT_FOUND");
    expect(log).toHaveBeenCalledWith("API path value refused", value);
  },
);
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/api.test.ts 2>&1 | grep -E "^ +Tests "`
Expected: `Tests  17 failed | 4 passed (21)`.

- [ ] **Step 3: Write the implementation**

In `apps/web/src/lib/api.ts`:

1. Replace

```ts

/** Server-side call to /v1. The key comes from the httpOnly cookie. */
```

   with

```ts

// ponytail: a backstop for anything a call site misses. It refuses dot
// segments in any spelling, '\', '#' and anything the URL parser would
// re-encode; a '/', '%2F' or '?' inside a value passes it, and seg() at each
// call site refuses those.
function sendAsWritten(path: string) {
  const u = new URL(path, "http://api.invalid");
  if (u.pathname + u.search === path) return;
  console.error("API path refused", path);
  notFound();
}

/** One path segment from a route param, form field or API value. */
export function seg(value: string): string {
  if (/^[A-Za-z0-9_-]+$/.test(value)) return value;
  console.error("API path value refused", value);
  notFound();
}

/** Server-side call to /v1. The key comes from the httpOnly cookie. */
```

2. Replace

```ts
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
```

   with

```ts
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  sendAsWritten(path);
```

3. Replace

```ts
export async function publicApi<T>(path: string): Promise<T> {
```

   with

```ts
export async function publicApi<T>(path: string): Promise<T> {
  sendAsWritten(path);
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/api.test.ts 2>&1 | grep -E "^ +Tests |FAIL"`
Expected: `Tests  21 passed (21)` and no `FAIL` line.

- [ ] **Step 5: Banned-word grep, then the web gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/api.ts apps/web/src/lib/api.test.ts`. Run the banned-word grep (expected: exit 0, no output). Run the Web gate with N=1. Expected: `gate exit 0`; `gate-task1.txt` shows `Tests  70 passed (70)` and `Compiled successfully`, and the file has no `API path refused` or `API path value refused` line.

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/api.ts apps/web/src/lib/api.test.ts && git commit -m "feat(web): api() refuses a path fetch would not send as written; add seg()

api() and publicApi() now refuse a path whose parsed form differs from
what was written (dot segments, a backslash, a fragment, anything the
URL parser re-encodes), and seg() admits one path segment of letters,
digits, '-' and '_'. Both log and show the not-found page.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: seg() on every value in an API path

**Files:**
- Create: `apps/web/src/lib/api-paths.test.ts`
- Modify (28): `apps/web/src/app/(app)/b/[id]/alerts/actions.ts`, `apps/web/src/app/(app)/b/[id]/alerts/page.tsx`, `apps/web/src/app/(app)/b/[id]/citations/page.tsx`, `apps/web/src/app/(app)/b/[id]/clusters/actions.ts`, `apps/web/src/app/(app)/b/[id]/clusters/page.tsx`, `apps/web/src/app/(app)/b/[id]/competitors/actions.ts`, `apps/web/src/app/(app)/b/[id]/competitors/page.tsx`, `apps/web/src/app/(app)/b/[id]/label/actions.ts`, `apps/web/src/app/(app)/b/[id]/label/page.tsx`, `apps/web/src/app/(app)/b/[id]/layout.tsx`, `apps/web/src/app/(app)/b/[id]/page.tsx`, `apps/web/src/app/(app)/b/[id]/pages/page.tsx`, `apps/web/src/app/(app)/b/[id]/products/actions.ts`, `apps/web/src/app/(app)/b/[id]/products/page.tsx`, `apps/web/src/app/(app)/b/[id]/prompts/[pid]/page.tsx`, `apps/web/src/app/(app)/b/[id]/prompts/page.tsx`, `apps/web/src/app/(app)/b/[id]/recommendations/actions.ts`, `apps/web/src/app/(app)/b/[id]/recommendations/page.tsx`, `apps/web/src/app/(app)/b/[id]/reports/actions.ts`, `apps/web/src/app/(app)/b/[id]/reports/page.tsx`, `apps/web/src/app/(app)/b/[id]/serp/actions.ts`, `apps/web/src/app/(app)/b/[id]/serp/page.tsx`, `apps/web/src/app/(app)/b/[id]/site/actions.ts`, `apps/web/src/app/(app)/b/[id]/site/page.tsx`, `apps/web/src/app/(app)/b/[id]/tasks/actions.ts`, `apps/web/src/app/(app)/b/[id]/tasks/page.tsx`, `apps/web/src/app/(app)/o/[oid]/page.tsx`, `apps/web/src/app/r/[token]/page.tsx`

**Interfaces:**
- Consumes: `seg` from `@/lib/api` (Task 1).
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

Create `apps/web/src/lib/api-paths.test.ts` with exactly:

```ts
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { expect, test } from "vitest";

// Query strings built by URLSearchParams, which encodes them already.
const QUERIES = new Set(["q", "dq", "wq", "feedQuery", "apiQuery(sp)"]);
const APP = join(__dirname, "..", "app");
const CALL = /\b(?:api|publicApi)(?:<[^(`]*>)?\(\s*/g;
// The whole first argument is one literal, followed by "," or ")".
const LITERAL = /^(`[^`]*`|"[^"]*"|'[^']*')\s*[,)]/;
const PATH = /\b(?:api|publicApi)(?:<[^(`]*>)?\(\s*`([^`]*)`/g;

/** True for exactly one seg(...) call: its "(" closes at the last character. */
const isSeg = (expr: string) => {
  if (!expr.startsWith("seg(")) return false;
  let depth = 0;
  for (let i = 3; i < expr.length; i++) {
    if (expr[i] === "(") depth += 1;
    if (expr[i] === ")") depth -= 1;
    if (depth === 0) return i === expr.length - 1;
  }
  return false;
};

test("every value in an API path goes through seg()", () => {
  const files = readdirSync(APP, { recursive: true, encoding: "utf8" }).filter(
    (f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f),
  );
  const bad: string[] = [];
  let templates = 0;
  for (const f of files) {
    const code = readFileSync(join(APP, f), "utf8")
      .split("\n")
      .filter((line) => !/^\s*(\/\/|\/\*|\*)/.test(line))
      .join("\n");
    for (const m of code.matchAll(CALL)) {
      if (!LITERAL.test(code.slice(m.index + m[0].length))) {
        bad.push(`${f}: path is not one literal`);
      }
    }
    for (const [, path] of code.matchAll(PATH)) {
      templates += 1;
      for (const [, expr] of path.matchAll(/\$\{([^}]*)\}/g)) {
        if (!isSeg(expr) && !QUERIES.has(expr)) bad.push(`${f}: \${${expr}}`);
      }
    }
  }
  expect(templates).toBeGreaterThanOrEqual(40);
  expect(bad).toEqual([]);
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/api-paths.test.ts 2>&1 | grep -E "^ +Tests "`
Expected: `Tests  1 failed (1)` (the failure lists every unwrapped value).

- [ ] **Step 3: Wrap the values**

Apply the blocks below in order, file by file. Each "Replace" text occurs exactly once in its file at the moment you apply it.

#### `apps/web/src/app/(app)/b/[id]/alerts/actions.ts`

1. Replace

```ts
import { api } from "@/lib/api";
```

   with

```ts
import { api, seg } from "@/lib/api";
```

2. Replace

```ts
  await api(`/brands/${id}`, {
```

   with

```ts
  await api(`/brands/${seg(id)}`, {
```

3. Replace

```ts
  const r = await api<{ created: number }>(`/brands/${id}/alerts/scan`, {
```

   with

```ts
  const r = await api<{ created: number }>(`/brands/${seg(id)}/alerts/scan`, {
```

#### `apps/web/src/app/(app)/b/[id]/alerts/page.tsx`

1. Replace

```tsx
import { api } from "@/lib/api";
```

   with

```tsx
import { api, seg } from "@/lib/api";
```

2. Replace

```tsx
    api<Brand>(`/brands/${id}`),
    api<Alert[]>(`/brands/${id}/alerts`),
```

   with

```tsx
    api<Brand>(`/brands/${seg(id)}`),
    api<Alert[]>(`/brands/${seg(id)}/alerts`),
```

#### `apps/web/src/app/(app)/b/[id]/citations/page.tsx`

1. Replace

```tsx
import { api } from "@/lib/api";
```

   with

```tsx
import { api, seg } from "@/lib/api";
```

2. Replace

```tsx
  let rows = await api<Source[]>(`/brands/${id}/citations${apiQuery(sp)}`);
```

   with

```tsx
  let rows = await api<Source[]>(`/brands/${seg(id)}/citations${apiQuery(sp)}`);
```

#### `apps/web/src/app/(app)/b/[id]/clusters/actions.ts`

1. Replace

```ts
import { api } from "@/lib/api";
```

   with

```ts
import { api, seg } from "@/lib/api";
```

2. Replace

```ts
  const job = await api<Queued>(`/brands/${id}/prompts/label`, {
```

   with

```ts
  const job = await api<Queued>(`/brands/${seg(id)}/prompts/label`, {
```

3. Replace

```ts
  const job = await api<Queued>(`/brands/${id}/pages/optimize`, {
```

   with

```ts
  const job = await api<Queued>(`/brands/${seg(id)}/pages/optimize`, {
```

#### `apps/web/src/app/(app)/b/[id]/clusters/page.tsx`

1. Replace

```tsx
import { api } from "@/lib/api";
```

   with

```tsx
import { api, seg } from "@/lib/api";
```

2. Replace

```tsx
  const data = await api<Clusters>(`/brands/${id}/clusters/gaps${apiQuery(sp)}`);
```

   with

```tsx
  const data = await api<Clusters>(`/brands/${seg(id)}/clusters/gaps${apiQuery(sp)}`);
```

#### `apps/web/src/app/(app)/b/[id]/competitors/actions.ts`

1. Replace

```ts
import { api } from "@/lib/api";
```

   with

```ts
import { api, seg } from "@/lib/api";
```

2. Replace

```ts
  const job = await api<Queued>(`/brands/${id}/competitors/crawl`, {
```

   with

```ts
  const job = await api<Queued>(`/brands/${seg(id)}/competitors/crawl`, {
```

#### `apps/web/src/app/(app)/b/[id]/competitors/page.tsx`

1. Replace

```tsx
import { api } from "@/lib/api";
```

   with

```tsx
import { api, seg } from "@/lib/api";
```

2. Replace

```tsx
    api<EntityMetrics[]>(`/brands/${id}/competitors/metrics${q}`),
    api<EntityDeltas>(`/brands/${id}/competitors/deltas${wq}`),
    api<Changes>(`/brands/${id}/competitors/changes${feedQuery}`),
    api<SiteChanges>(`/brands/${id}/competitors/site-changes${feedQuery}`),
```

   with

```tsx
    api<EntityMetrics[]>(`/brands/${seg(id)}/competitors/metrics${q}`),
    api<EntityDeltas>(`/brands/${seg(id)}/competitors/deltas${wq}`),
    api<Changes>(`/brands/${seg(id)}/competitors/changes${feedQuery}`),
    api<SiteChanges>(`/brands/${seg(id)}/competitors/site-changes${feedQuery}`),
```

#### `apps/web/src/app/(app)/b/[id]/label/actions.ts`

1. Replace

```ts
import { api } from "@/lib/api";
```

   with

```ts
import { api, seg } from "@/lib/api";
```

2. Replace

```ts
    `/observations/${get("observation_id")}/labels/${get("entity_id")}`,
```

   with

```ts
    `/observations/${seg(get("observation_id"))}/labels/${seg(get("entity_id"))}`,
```

#### `apps/web/src/app/(app)/b/[id]/label/page.tsx`

1. Replace

```tsx
import { api } from "@/lib/api";
```

   with

```tsx
import { api, seg } from "@/lib/api";
```

2. Replace

```tsx
  const q = await api<LabelQueue>(`/brands/${id}/labels/next`);
```

   with

```tsx
  const q = await api<LabelQueue>(`/brands/${seg(id)}/labels/next`);
```

#### `apps/web/src/app/(app)/b/[id]/layout.tsx`

1. Replace

```tsx
import { api } from "@/lib/api";
```

   with

```tsx
import { api, seg } from "@/lib/api";
```

2. Replace

```tsx
  const brand = await api<Brand>(`/brands/${id}`);
```

   with

```tsx
  const brand = await api<Brand>(`/brands/${seg(id)}`);
```

#### `apps/web/src/app/(app)/b/[id]/page.tsx`

1. Replace

```tsx
import { api } from "@/lib/api";
```

   with

```tsx
import { api, seg } from "@/lib/api";
```

2. Replace

```tsx
    api<Metrics>(`/brands/${id}/metrics${q}`),
    api<Deltas>(`/brands/${id}/deltas${dq}`),
    api<Sov>(`/brands/${id}/sov${q}`),
    api<Recommendation[]>(`/brands/${id}/recommendations/top`),
```

   with

```tsx
    api<Metrics>(`/brands/${seg(id)}/metrics${q}`),
    api<Deltas>(`/brands/${seg(id)}/deltas${dq}`),
    api<Sov>(`/brands/${seg(id)}/sov${q}`),
    api<Recommendation[]>(`/brands/${seg(id)}/recommendations/top`),
```

#### `apps/web/src/app/(app)/b/[id]/pages/page.tsx`

1. Replace

```tsx
import { api } from "@/lib/api";
```

   with

```tsx
import { api, seg } from "@/lib/api";
```

2. Replace

```tsx
  const audits = await api<PageAudit[]>(`/brands/${id}/pages`);
```

   with

```tsx
  const audits = await api<PageAudit[]>(`/brands/${seg(id)}/pages`);
```

#### `apps/web/src/app/(app)/b/[id]/products/actions.ts`

1. Replace

```ts
import { api } from "@/lib/api";
```

   with

```ts
import { api, seg } from "@/lib/api";
```

2. Replace

```ts
    r = await api<ImportResult>(`/brands/${id}/products/import/csv`, {
```

   with

```ts
    r = await api<ImportResult>(`/brands/${seg(id)}/products/import/csv`, {
```

3. Replace

```ts
  const job = await api<Queued>(`/brands/${id}/products/import/feed`, {
```

   with

```ts
  const job = await api<Queued>(`/brands/${seg(id)}/products/import/feed`, {
```

4. Replace

```ts
    job = await api<Queued>(`/brands/${id}/products/run`, { method: "POST" });
```

   with

```ts
    job = await api<Queued>(`/brands/${seg(id)}/products/run`, { method: "POST" });
```

5. Replace

```ts
  await api(`/brands/${id}/products`, { method: "DELETE" });
```

   with

```ts
  await api(`/brands/${seg(id)}/products`, { method: "DELETE" });
```

#### `apps/web/src/app/(app)/b/[id]/products/page.tsx`

1. Replace

```tsx
import { api } from "@/lib/api";
```

   with

```tsx
import { api, seg } from "@/lib/api";
```

2. Replace

```tsx
    api<Product[]>(`/brands/${id}/products`),
    api<ProductRuns>(`/brands/${id}/products/runs`),
```

   with

```tsx
    api<Product[]>(`/brands/${seg(id)}/products`),
    api<ProductRuns>(`/brands/${seg(id)}/products/runs`),
```

#### `apps/web/src/app/(app)/b/[id]/prompts/[pid]/page.tsx`

1. Replace

```tsx
import { api } from "@/lib/api";
```

   with

```tsx
import { api, seg } from "@/lib/api";
```

2. Replace

```tsx
    api<Observation[]>(`/observations?brand_id=${id}&prompt_id=${pid}&limit=200`),
    api<Prompt[]>(`/brands/${id}/prompts`),
```

   with

```tsx
    api<Observation[]>(`/observations?brand_id=${seg(id)}&prompt_id=${seg(pid)}&limit=200`),
    api<Prompt[]>(`/brands/${seg(id)}/prompts`),
```

#### `apps/web/src/app/(app)/b/[id]/prompts/page.tsx`

1. Replace

```tsx
import { api } from "@/lib/api";
```

   with

```tsx
import { api, seg } from "@/lib/api";
```

2. Replace

```tsx
    `/brands/${id}/prompts/metrics${apiQuery(sp)}`,
```

   with

```tsx
    `/brands/${seg(id)}/prompts/metrics${apiQuery(sp)}`,
```

#### `apps/web/src/app/(app)/b/[id]/recommendations/actions.ts`

1. Replace

```ts
import { api } from "@/lib/api";
```

   with

```ts
import { api, seg } from "@/lib/api";
```

2. Replace

```ts
const rec = (form: FormData) =>
  `/brands/${brand(form)}/recommendations/${String(form.get("rec_id"))}`;
```

   with

```ts
const rec = (form: FormData) => String(form.get("rec_id"));
```

3. Replace

```ts
  await api(`/brands/${brand(form)}/recommendations/generate`, {
```

   with

```ts
  await api(`/brands/${seg(brand(form))}/recommendations/generate`, {
```

4. Replace

```ts
  await api(`${rec(form)}/accept`, { method: "POST" });
```

   with

```ts
  await api(
    `/brands/${seg(brand(form))}/recommendations/${seg(rec(form))}/accept`,
    { method: "POST" },
  );
```

5. Replace

```ts
  await api(`${rec(form)}/dismiss`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason: String(form.get("reason") ?? "") }),
  });
```

   with

```ts
  await api(
    `/brands/${seg(brand(form))}/recommendations/${seg(rec(form))}/dismiss`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: String(form.get("reason") ?? "") }),
    },
  );
```

#### `apps/web/src/app/(app)/b/[id]/recommendations/page.tsx`

1. Replace

```tsx
import { api } from "@/lib/api";
```

   with

```tsx
import { api, seg } from "@/lib/api";
```

2. Replace

```tsx
  const recs = await api<Recommendation[]>(`/brands/${id}/recommendations`);
```

   with

```tsx
  const recs = await api<Recommendation[]>(`/brands/${seg(id)}/recommendations`);
```

#### `apps/web/src/app/(app)/b/[id]/reports/actions.ts`

1. Replace

```ts
import { api } from "@/lib/api";
```

   with

```ts
import { api, seg } from "@/lib/api";
```

2. Replace

```ts
  await api(`/brands/${id}/reports/${type}`, {
```

   with

```ts
  await api(`/brands/${seg(id)}/reports/${seg(type)}`, {
```

3. Replace

```ts
  await api(`/brands/${id}/reports/${type}/runs`, { method: "POST" });
```

   with

```ts
  await api(`/brands/${seg(id)}/reports/${seg(type)}/runs`, { method: "POST" });
```

4. Replace

```ts
  await api(`/brands/${id}/reports/runs/${run}/share`, { method: "POST" });
```

   with

```ts
  await api(`/brands/${seg(id)}/reports/runs/${seg(run)}/share`, {
    method: "POST",
  });
```

5. Replace

```ts
  await api(`/brands/${id}/reports/runs/${run}/share`, { method: "DELETE" });
```

   with

```ts
  await api(`/brands/${seg(id)}/reports/runs/${seg(run)}/share`, {
    method: "DELETE",
  });
```

6. Replace

```ts
  await api(`/brands/${id}`, {
```

   with

```ts
  await api(`/brands/${seg(id)}`, {
```

#### `apps/web/src/app/(app)/b/[id]/reports/page.tsx`

1. Replace

```tsx
import { api } from "@/lib/api";
```

   with

```tsx
import { api, seg } from "@/lib/api";
```

2. Replace

```tsx
    api<Brand>(`/brands/${id}`),
    api<Report[]>(`/brands/${id}/reports`),
    api<ReportRun[]>(`/brands/${id}/reports/runs`),
```

   with

```tsx
    api<Brand>(`/brands/${seg(id)}`),
    api<Report[]>(`/brands/${seg(id)}/reports`),
    api<ReportRun[]>(`/brands/${seg(id)}/reports/runs`),
```

#### `apps/web/src/app/(app)/b/[id]/serp/actions.ts`

1. Replace

```ts
import { api } from "@/lib/api";
```

   with

```ts
import { api, seg } from "@/lib/api";
```

2. Replace

```ts
  const job = await api<Queued>(`/brands/${id}/audits/serp`, {
```

   with

```ts
  const job = await api<Queued>(`/brands/${seg(id)}/audits/serp`, {
```

3. Replace

```ts
  await api(`/brands/${id}/domains`, {
```

   with

```ts
  await api(`/brands/${seg(id)}/domains`, {
```

#### `apps/web/src/app/(app)/b/[id]/serp/page.tsx`

1. Replace

```tsx
import { api } from "@/lib/api";
```

   with

```tsx
import { api, seg } from "@/lib/api";
```

2. Replace

```tsx
    api<SerpAudits>(`/brands/${id}/audits/serp`),
    api<Brand>(`/brands/${id}`),
    api<Domain[]>(`/brands/${id}/domains`),
```

   with

```tsx
    api<SerpAudits>(`/brands/${seg(id)}/audits/serp`),
    api<Brand>(`/brands/${seg(id)}`),
    api<Domain[]>(`/brands/${seg(id)}/domains`),
```

#### `apps/web/src/app/(app)/b/[id]/site/actions.ts`

1. Replace

```ts
import { api } from "@/lib/api";
```

   with

```ts
import { api, seg } from "@/lib/api";
```

2. Replace

```ts
  const job = await api<Queued>(`/brands/${id}/audits/crawl`, {
```

   with

```ts
  const job = await api<Queued>(`/brands/${seg(id)}/audits/crawl`, {
```

#### `apps/web/src/app/(app)/b/[id]/site/page.tsx`

1. Replace

```tsx
import { api } from "@/lib/api";
```

   with

```tsx
import { api, seg } from "@/lib/api";
```

2. Replace

```tsx
  const audits = await api<SiteAudit[]>(`/brands/${id}/audits/crawl`);
```

   with

```tsx
  const audits = await api<SiteAudit[]>(`/brands/${seg(id)}/audits/crawl`);
```

#### `apps/web/src/app/(app)/b/[id]/tasks/actions.ts`

1. Replace

```ts
import { api } from "@/lib/api";
```

   with

```ts
import { api, seg } from "@/lib/api";
```

2. Replace

```ts
  await api(`/brands/${id}/tasks/${String(form.get("task_id"))}`, {
```

   with

```ts
  await api(`/brands/${seg(id)}/tasks/${seg(String(form.get("task_id")))}`, {
```

#### `apps/web/src/app/(app)/b/[id]/tasks/page.tsx`

1. Replace

```tsx
import { api } from "@/lib/api";
```

   with

```tsx
import { api, seg } from "@/lib/api";
```

2. Replace

```tsx
  const tasks = await api<Task[]>(`/brands/${id}/tasks`);
```

   with

```tsx
  const tasks = await api<Task[]>(`/brands/${seg(id)}/tasks`);
```

#### `apps/web/src/app/(app)/o/[oid]/page.tsx`

1. Replace

```tsx
import { api } from "@/lib/api";
```

   with

```tsx
import { api, seg } from "@/lib/api";
```

2. Replace

```tsx
  const o = await api<ObservationDetail>(`/observations/${oid}`);
```

   with

```tsx
  const o = await api<ObservationDetail>(`/observations/${seg(oid)}`);
```

3. Replace

```tsx
    api<Brand>(`/brands/${o.brand_id}`),
    api<Competitor[]>(`/brands/${o.brand_id}/competitors`),
```

   with

```tsx
    api<Brand>(`/brands/${seg(o.brand_id)}`),
    api<Competitor[]>(`/brands/${seg(o.brand_id)}/competitors`),
```

#### `apps/web/src/app/r/[token]/page.tsx`

1. Replace

```tsx
import { publicApi } from "@/lib/api";
```

   with

```tsx
import { publicApi, seg } from "@/lib/api";
```

2. Replace

```tsx
  publicApi<ReportRunDetail>(`/r/${encodeURIComponent((await params).token)}`);
```

   with

```tsx
  publicApi<ReportRunDetail>(`/r/${seg((await params).token)}`);
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/api-paths.test.ts src/lib/api.test.ts 2>&1 | grep -E "^ +Tests |FAIL"`
Expected: `Tests  22 passed (22)` and no `FAIL` line.

- [ ] **Step 5: Banned-word grep, then the web gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/api-paths.test.ts "apps/web/src/app"`. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git diff --cached --name-only | wc -l` (expected: `29`). Run the banned-word grep (expected: exit 0, no output). Run the Web gate with N=2. Expected: `gate exit 0`; `gate-task2.txt` shows `Tests  71 passed (71)` and `Compiled successfully`, and the file has no `API path refused` or `API path value refused` line. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the staged files plus the untracked `.DS_Store` and `packages/.DS_Store`).

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git commit -m "fix(web): every value in an API path goes through seg()

Route params, form fields and API values were put into API paths as
they came, so a '/', '%2F', '..' or '?' inside one could send the
request to another route. Each is now checked by seg(), and a source
scan test fails if a value in an src/app path template skips it.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (plan vs spec)

- Spec coverage: `sendAsWritten`, `seg`, and the calls in `api()`/`publicApi()` → Task 1 Step 3; the guard and `seg` tests → Task 1 Step 1; the 28 call-site files → Task 2 Step 3; the scan test → Task 2 Step 1; the expected web gate (71) → Task 2 Step 5.
- Departures from the spec:
  1. The work is split into two tasks (the spec has no tasks); Task 1's gate expects 70, Task 2's 71.
  2. The code changes are a new file plus replace blocks generated by script from the scratch proof's final files (each widened until it occurs once), not the spec's unified diff; the result is the same files.
  3. The spec's mutation table and Prettier check are not repeated in execution.
  4. The commit messages are the plan's wording.
  5. The spec's expected backend gate (`1753 passed, 2 deselected`, unchanged) is not a plan step; the controller runs it before the finishing menu.
  6. The spec's optional live check (page views only, asked first) is not a plan step; the controller asks the user after merge.
  7. The header offers superpowers:executing-plans as well as subagent-driven-development (the template's wording).
- Verified before execution (2026-10-07): both tasks were applied mechanically from this plan's blocks (parsed from this file) to a fresh scratch copy of main's `apps/web`: Task 1 Step 2 `Tests  17 failed | 4 passed (21)`, Step 4 `Tests  21 passed (21)`, then typecheck, lint, test (`Tests  70 passed (70)`) and build exit 0; Task 2 Step 2 `Tests  1 failed (1)`, 28 files wrapped, Step 4 `Tests  22 passed (22)`, then typecheck, lint, test (`Tests  71 passed (71)`) and build exit 0, with no refusal line in either output; all 31 finished files are byte-identical to the spec's proof copies. The gate's `gen:check` step was not run there (the copy has no backend).
- Placeholders: `<workspace>`, `<N>`.

## Changes made during execution

- Task 1: commit c44ac3f; Task 2: commit 4660364; both task reviews say "✅ Spec compliant" and "Task quality: Approved"; no fix rounds. All 31 files are byte-identical to the spec's proof copies. Merged via PR #100 (main `e3b3f61`).
- Gates and CI, as the ledger records them:
  - "Task 1: implementer abb1354587c39f771, commit c44ac3f (trailer Opus 5.5 checked); report: red Tests 17 failed | 4 passed (21), green Tests 21 passed (21); gate exit 0, gate-task1.txt Tests  70 passed (70), Compiled successfully, no refusal line, gen:check no diff; controller check: api.ts and api.test.ts are byte-identical to the spec's proof copies."
  - "Task 2: implementer a2d9fd3db78da39ab, commit 4660364 (trailer Opus 5.5 checked); report: red Tests 1 failed (1), green Tests 22 passed (22) with api.test.ts; staged 29; gate exit 0, gate-task2.txt Tests  71 passed (71), Compiled successfully, no refusal line, gen:check no diff; controller check: all 31 slice files are byte-identical to the spec's proof copies."
  - "Controller gates on 4660364: backend gate exit 0, 1753 passed, 2 deselected, 2 warnings in 235.68s (0:03:55), mypy Success, metrics coverage 100%; web gate exit 0, Tests  71 passed (71), Compiled successfully, no refusal line."
  - "PR opened for slice49-api-path-guard on head 4660364 after the user chose "Push and create a Pull Request" at the finishing menu (2026-10-07)."
  - "CI run 37614186076: success on 4660364, 1753 passed, 2 deselected, 2 warnings in 129.64s (0:02:09); web Tests  71 passed (71), Compiled successfully."
  - "PR #100 merged by the controller after the user said "go ahead" to "Should I merge PR #100?" (2026-10-07); merge commit e3b3f61; local main fast-forwarded to e3b3f61; branch deleted on GitHub and locally."
  - "Gates on main e3b3f61 after merge: backend 1753 passed, 2 deselected, 2 warnings in 256.79s (0:04:16), coverage 100%; web Tests  71 passed (71), Compiled successfully."
- Reviews, as the ledger records them:
  - "Spec review (ad3141fc576bdde33, 6a55903): "Spec ready? No"; 0 Critical, 3 Important, 6 Minor."
  - "Spec review (a015dcf18c3d22bd2, c2253d5): "Spec ready? No"; 0 Critical, 1 Important, 7 Minor."
  - "Spec re-review (a698f8d3a147689af, ef3b796): "Spec ready? No"; 0 Critical, 1 Important, 2 Minor."
  - "Spec re-review (a63daf67355d2d13a, 9daba5a): "Spec ready? No"; 0 Critical, 1 Important (a regression: the R5 comment reverted), 2 Minor."
  - "Spec re-review (a0abfd1c7e77ff3bb, 90ee504): "Spec ready? Yes" once Minor 1 is recorded; 0 Critical, 0 Important, 2 Minor."
  - "Plan review (adbe523df7912402a, 23c1ae8 and 761252f): "Ready to execute? Yes"; 0 Critical, 0 Important, 3 Minor."
  - "Plan re-review (acc9e70f6a69ca2f7, 718b8df): "Ready to execute? Yes"; 0 Critical, 0 Important, 2 Minor."
  - "Task 1: task review (a43a23dfe41844d65, d5edba8..c44ac3f): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 2 Minor. ⚠️ items resolved by the controller: the trailer is checked by git log -1 (Co-Authored-By: Claude Opus 5.5); gate-task1.txt shows Tests  70 passed (70), Compiled successfully and no refusal line; the report holds the RED and GREEN lines; api.ts and api.test.ts are byte-identical to the proof."
  - "Task 2: task review (a1ab877d3884b5e50, c44ac3f..4660364): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 2 Minor. ⚠️ items resolved by the controller: the trailer is checked by git log -1; gate-task2.txt shows Tests  71 passed (71), Compiled successfully and no refusal line; the report holds the RED and GREEN lines; all 31 slice files are byte-identical to the proof."
  - "Final review (a9f3c63a8276cb04c, c45a729..4660364): "Ready to merge? Yes"; 0 Critical, 0 Important, 3 Minor; every deferred minor triaged "Not before merge"."
- R11 (made after the final review) is quoted in the spec's "Rulings" section and in docs/findings-slice49.md §3, with every deferred minor.
