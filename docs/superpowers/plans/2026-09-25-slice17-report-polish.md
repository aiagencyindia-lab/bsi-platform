# Slice 17 Report Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve the report PDF from the web app's own domain, print readable labels instead of raw codes in report documents, and add an Intent column to the SEO content-gaps table.

**Architecture:** A Next.js Route Handler at `/r/{token}/pdf` proxies the API's `/v1/r/{token}.pdf` server-side, so both PDF links become relative. In `bsi_core/reports.py`, one `label()` helper (with a three-entry owner map) formats the codes the builders print, the SEO gap table gains an Intent column, and `METHODOLOGY_VERSION` becomes `"2"`. Stored runs are untouched.

**Tech Stack:** Next.js 15 App Router (Route Handler), vitest; Python 3.13, pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-slice17-report-polish-design.md`

## Global Constraints

- Repo root is `/Users/vineet/Downloads/ADK/bsi-platform`; the shell's cwd resets after every command, so every command starts with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- Do NOT edit `tests/conftest.py` or create databases; never touch the dev DB, the network or the worker loop. Tests use the shared `bsi_test` DB; check `pgrep -fl pytest` first and never run two suites at once.
- ruff line length 80; `mypy --strict` over `packages/core/bsi_core`.
- Token pattern `^[A-Za-z0-9_-]{20,64}$`; malformed → 404 without calling the API; API 404/422 → 404; any other failure → 502 with no detail; success passes through `Content-Type` and `Content-Disposition` and sets `Cache-Control: no-store`. No error body names the product or the API host. The request to the API sends no Authorization header and no cookie.
- Both PDF links are the relative `/r/{token}/pdf`. `API_URL` stays only in `lib/api.ts` and the login action.
  (amended during execution: also the route — see Changes made during execution)
- `label()`: `OWNER_LABEL = {"brand": "Own site", "rival": "Competitor", "third_party": "Third party"}`; otherwise underscores → spaces and capitalise the first letter; `""` → `""`.
- Labels apply only in the builders (new runs). Stored runs are never rewritten. `METHODOLOGY_VERSION = "2"`.
- SEO "Content gaps" columns: `Intent, Topic, Prompts, Brand mention rate, Top rival`.
- Copy: no report string may contain `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat`, `certain`.
- Commit trailer: the `Co-Authored-By` line from the latest session reminder (Opus 5.5 during execution).

---

## File map

| File | Responsibility |
|---|---|
| `apps/web/src/app/r/[token]/pdf/route.ts` | the same-origin PDF proxy |
| `apps/web/src/app/r/[token]/pdf/route.test.ts` | its tests |
| `apps/web/src/app/r/[token]/page.tsx`, `apps/web/src/app/(app)/b/[id]/reports/page.tsx` | relative PDF links |
| `apps/web/src/components/ReportBody.test.tsx` | `pdfHref` rendered as given |
| `packages/core/bsi_core/reports.py` | `label()`, `OWNER_LABEL`, relabelled cells, Intent column, version bump |
| `tests/unit/test_reports.py`, `tests/integration/test_reports.py` | tests |
| `docs/findings-slice17.md`, `docs/README.md`, the spec's Rulings, the plan's changes section | docs |

---

### Task 1: Same-origin PDF route and relative links

**Files:**
- Create: `apps/web/src/app/r/[token]/pdf/route.ts`, `apps/web/src/app/r/[token]/pdf/route.test.ts`
- Modify: `apps/web/src/app/r/[token]/page.tsx` (drop `API_URL`; `pdfHref`), `apps/web/src/app/(app)/b/[id]/reports/page.tsx` (drop `API_URL`; the PDF link), `apps/web/src/components/ReportBody.test.tsx` (the `pdfHref` literal)

**Interfaces:**
- Produces: `GET /r/{token}/pdf` on the web app. Consumes `API_URL` from `@/lib/api` and the API's `/v1/r/{token}.pdf`.

- [ ] **Step 1: Write the failing tests**

Create `apps/web/src/app/r/[token]/pdf/route.test.ts`:

```ts
import { afterEach, expect, test, vi } from "vitest";

vi.mock("server-only", () => ({}));
vi.mock("next/headers", () => ({ cookies: vi.fn() }));
vi.mock("next/navigation", () => ({ notFound: vi.fn(), redirect: vi.fn() }));

const { GET } = await import("./route");

const TOKEN = "abcdefghijklmnopqrstuvwxyz0123456789-_ab";
const call = (token: string) =>
  GET(new Request(`http://web.test/r/${token}/pdf`), {
    params: Promise.resolve({ token }),
  });

afterEach(() => vi.unstubAllGlobals());

test("streams the API's PDF with its headers and no auth", async () => {
  const fetchMock = vi.fn(
    async () =>
      new Response("%PDF-1.4 fake", {
        status: 200,
        headers: {
          "content-type": "application/pdf",
          "content-disposition": 'attachment; filename="nike-cmo-2026-09-25.pdf"',
        },
      }),
  );
  vi.stubGlobal("fetch", fetchMock);
  const res = await call(TOKEN);
  expect(res.status).toBe(200);
  expect(await res.text()).toBe("%PDF-1.4 fake");
  expect(res.headers.get("content-type")).toBe("application/pdf");
  expect(res.headers.get("content-disposition")).toBe(
    'attachment; filename="nike-cmo-2026-09-25.pdf"',
  );
  expect(res.headers.get("cache-control")).toBe("no-store");
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe(`http://localhost:8000/v1/r/${TOKEN}.pdf`);
  expect(init).toEqual({ cache: "no-store" });
});

test("a malformed token is 404 and the API is never called", async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  for (const bad of ["short", "has.dot.aaaaaaaaaaaaaaaaaaaa", "a".repeat(65)]) {
    const res = await call(bad);
    expect(res.status).toBe(404);
    expect(await res.text()).toBe("Not found");
  }
  expect(fetchMock).not.toHaveBeenCalled();
});

test.each([404, 422])("API %i becomes 404", async (status) => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status })));
  const res = await call(TOKEN);
  expect(res.status).toBe(404);
  expect(await res.text()).toBe("Not found");
});

test("API 500 and a throwing fetch become 502 with no detail", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 500 })));
  let res = await call(TOKEN);
  expect(res.status).toBe(502);
  expect(await res.text()).toBe("Report unavailable");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => {
      throw new Error("ECONNREFUSED http://api.internal:8000");
    }),
  );
  res = await call(TOKEN);
  expect(res.status).toBe(502);
  expect(await res.text()).toBe("Report unavailable");
});
```

In `apps/web/src/components/ReportBody.test.tsx`, change the `pdfHref` literal on the first test from `"http://localhost:8000/v1/r/t.pdf"` to `"/r/t/pdf"` and the matching expectation to `'href="/r/t/pdf"'`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm test`
Expected: the route test file fails to import `./route` (module not found); the ReportBody change passes already (it renders whatever it is given).

- [ ] **Step 3: Implement the route and the links**

Create `apps/web/src/app/r/[token]/pdf/route.ts`:

```ts
import { API_URL } from "@/lib/api";

// The only Route Handler in the app: it proxies the API's public PDF so
// the client never sees the API host and the API can stay internal.
// Same token rule as the API; a bad token never reaches it.
const TOKEN = /^[A-Za-z0-9_-]{20,64}$/;

const plain = (body: string, status: number) =>
  new Response(body, {
    status,
    headers: { "content-type": "text/plain", "cache-control": "no-store" },
  });

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ token: string }> },
) {
  const { token } = await params;
  if (!TOKEN.test(token)) return plain("Not found", 404);
  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/v1/r/${token}.pdf`, {
      cache: "no-store",
    });
  } catch {
    return plain("Report unavailable", 502);
  }
  if (upstream.status === 404 || upstream.status === 422) {
    return plain("Not found", 404);
  }
  if (!upstream.ok) return plain("Report unavailable", 502);
  const headers = new Headers({ "cache-control": "no-store" });
  for (const name of ["content-type", "content-disposition"]) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new Response(upstream.body, { status: 200, headers });
}
```

`lib/api.ts` has `import "server-only"`, which the test mocks; the route imports only `API_URL` from it, and Next's own server-only guard is satisfied because Route Handlers run on the server. `API_URL` is evaluated when the server process starts (`process.env.API_URL` at module load), not at build time, which is what the spec's "read at request time" is protecting against; the findings state it as "at server start".

In `apps/web/src/app/r/[token]/page.tsx`: change the import to `import { publicApi } from "@/lib/api";` and the `pdfHref` to `` pdfHref={`/r/${encodeURIComponent(token)}/pdf`} ``.

In `apps/web/src/app/(app)/b/[id]/reports/page.tsx`: change the import to `import { api } from "@/lib/api";` and the PDF anchor to `` <a href={`/r/${r.share_token}/pdf`}>PDF</a> ``.

- [ ] **Step 4: Run the web gate**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate`
Expected: PASS (typecheck, lint, vitest incl. the four new tests, build, gen:check with no diff). Confirm with `grep -rn "API_URL" src` that only `lib/api.ts` and `app/login/actions.ts` remain.

- [ ] **Step 5: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add "apps/web/src/app/r/[token]/pdf" "apps/web/src/app/r/[token]/page.tsx" "apps/web/src/app/(app)/b/[id]/reports/page.tsx" apps/web/src/components/ReportBody.test.tsx && git commit -q -F - <<'EOF'
feat(web): serve the report PDF from the app's own domain

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 2: Readable labels, the Intent column, methodology v2

**Files:**
- Modify: `packages/core/bsi_core/reports.py` (`METHODOLOGY_VERSION`, new `OWNER_LABEL` and `label()`, cells in `_task_rows`, `build_cmo`, `build_seo`, `build_pr`)
- Test: `tests/unit/test_reports.py` (append), `tests/integration/test_reports.py` (update the assertions named below)

**Interfaces:**
- Produces: `reports.OWNER_LABEL`, `reports.label(code: str) -> str`, `METHODOLOGY_VERSION == "2"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_reports.py` (add `label` and `METHODOLOGY_VERSION` to the `bsi_core.reports` import; `METHODOLOGY_VERSION` may already be imported):

```python
def test_label_reads_codes_as_words():
    assert label("third_party") == "Third party"
    assert label("brand") == "Own site"
    assert label("rival") == "Competitor"
    assert label("impact_measured") == "Impact measured"
    assert label("insufficient_data") == "Insufficient data"
    assert label("h1_missing") == "H1 missing"
    assert label("problem-based") == "Problem-based"
    assert label("high") == "High"
    assert label("") == ""


def test_methodology_is_v2():
    assert METHODOLOGY_VERSION == "2"
```

In `tests/integration/test_reports.py`:
- `test_cmo_opening_agrees_with_brand_deltas`: `"Methodology v1 · pipeline v"` → `"Methodology v2 · pipeline v"`.
- `test_cmo_sections_agree_with_the_dashboard_functions`: the sources expectation becomes `[x["domain"], label(x["owner"]), str(x["answers"]), str(x["prompts"])]` (import `label` from `bsi_core.reports`), plus one literal check so the test cannot pass vacuously: `assert src.rows[0][1] == "Third party"` (forbes.com is the scene's top source); the Tasks row becomes `["Pitch forbes.com", "Priya", "Impact measured", "Improved", "+0.20 [+0.10, +0.30] increase"]`.
- `test_seo_sections`: the Site audit row becomes `["nike.com", "Llms txt", "Low", "404 (expected 200)"]`. Its "Content gaps" section stays a paragraph (the scene has no labelled prompts); the gap table is covered by the new test below.
- `test_pr_sections`: the mix rows become `["Neutral", "3", fmt_rate(rate(3, 4))]` and `["Negative", "1", fmt_rate(rate(1, 4))]`.

Add to `tests/integration/test_reports.py` (it already imports `_prompt`, `_answers`, `_mention` from `test_competitors` and has `_scene`; add `from sqlalchemy import update` if absent and `_table`/`_section` exist):

```python
def test_seo_gap_table_has_an_intent_column(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    # Two labelled prompts with the same topic and different intents, the
    # brand absent on every answer, so both clusters are gaps.
    with owner() as s, s.begin():
        cid = s.scalars(
            select(m.Competitor.id).where(m.Competitor.brand_id == bid)
        ).first()
    for intent in ("commercial", "problem-based"):
        p = _prompt(owner, org, bid, f"{intent} kids shoes")
        with owner() as s, s.begin():
            s.execute(
                update(m.Prompt)
                .where(m.Prompt.id == p)
                .values(intent=intent, topic="kids shoes")
            )
        obs = _answers(owner, org, bid, p, NOW - timedelta(days=1), 4)
        with owner() as s, s.begin():
            for o in obs:
                s.add(
                    m.Extraction(
                        org_id=org.id,
                        observation_id=o,
                        pipeline_version="2",
                        model_used="t",
                        brand_mentioned=False,
                        absence_reason="competitor_dominance",
                    )
                )
                s.add(_mention(org, o, "competitor", cid))
    with tenant_session(org.id) as s:
        doc = build_seo(s, s.get_one(m.Brand, bid), 7, NOW)
    gaps = _table(doc, "Content gaps")
    assert gaps.columns == [
        "Intent",
        "Topic",
        "Prompts",
        "Brand mention rate",
        "Top rival",
    ]
    assert sorted((r[0], r[1]) for r in gaps.rows) == [
        ("Commercial", "kids shoes"),
        ("Problem-based", "kids shoes"),
    ]
```

Check first how the existing `_scene` inserts `Extraction` rows (it may not; the test_gaps scene does) and mirror the field names exactly; if `_scene`'s answers have no `Extraction` rows, the two new prompts still form their own clusters because `gaps.clusters` only needs done observations plus extraction/mention rows for the new prompts.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_reports.py tests/integration/test_reports.py`
Expected: FAIL: `ImportError: cannot import name 'label'` in the unit file; the integration assertions fail on the old raw cells.

- [ ] **Step 3: Implement**

In `packages/core/bsi_core/reports.py`:

- `METHODOLOGY_VERSION = "2"` (update the comment above it: v2 = readable labels and the SEO Intent column).
- After `ALERT_LABEL`:

```python
# Client-facing wording for source owners; every other code reads as
# words by the rule in label().
OWNER_LABEL = {
    "brand": "Own site",
    "rival": "Competitor",
    "third_party": "Third party",
}


def label(code: str) -> str:
    """A stored code as words: underscores become spaces and the first
    letter is capitalised, so no per-code table goes stale."""
    if code in OWNER_LABEL:
        return OWNER_LABEL[code]
    words = code.replace("_", " ")
    return words[:1].upper() + words[1:]
```

- `_task_rows`: `t.status` → `label(t.status)`; `t.impact_label or "—"` → `label(t.impact_label) if t.impact_label else "—"`.
- `build_cmo` `src_rows`: `x["owner"]` → `label(x["owner"])`.
- `build_seo` `src_rows`: `x["owner"]` → `label(x["owner"])`; `audit_rows`: `str(c.get("code", ""))` → `label(str(c.get("code", "")))` and `str(c.get("severity", ""))` → `label(str(c.get("severity", "")))`; `gap_rows`: prepend `label(c["intent"])` to each row and change the table columns to `["Intent", "Topic", "Prompts", "Brand mention rate", "Top rival"]`.
- `build_pr` `mix_rows`: `r.sentiment` → `label(r.sentiment)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_reports.py tests/integration/test_reports.py tests/integration/test_api_reports.py`
Expected: PASS, including `test_copy_never_promises` over every builder.

- [ ] **Step 5: Lint and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy && uv run pytest -q` (full suite once; ~1371 + new).

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/reports.py tests/unit/test_reports.py tests/integration/test_reports.py && git commit -q -F - <<'EOF'
feat(reports): readable labels, SEO Intent column, methodology v2

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Docs

**Files:**
- Create: `docs/findings-slice17.md`
- Modify: `docs/README.md` (a "## Slice 17: report polish" section after slice 16's, same table format), the spec's `## Rulings` (every ruling from the ledger, in order), the plan's end (`## Changes made during execution`)

- [ ] **Step 1: Write the findings skeleton**

`docs/findings-slice17.md` with the four sections used by slices 15–16: `## 1. What was built` (the route, the relative links, `label()`/`OWNER_LABEL`, the relabelled cells, the Intent column, `METHODOLOGY_VERSION = "2"`; `git log --oneline main..HEAD`), `## 2. Live check` (heading + "Run by the controller on dev before the finishing menu; filled in below." + empty `| Check | Result |` table), `## 3. Deferred / decisions` (from the spec's out-of-scope list; the frontend rule now allows this one Route Handler; stored runs keep v1 wording; plus every "minor (deferred)" line from the ledger with its cost), `## 4. Not covered by tests` (the new labels and Intent column on real dev data — no new run is generated; the Route Handler under a real Next server, exercised only by the live check).

- [ ] **Step 2: Run both gates**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100
```
```bash
cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate
```

- [ ] **Step 3: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add docs/findings-slice17.md docs/README.md docs/superpowers/specs/2026-09-25-slice17-report-polish-design.md docs/superpowers/plans/2026-09-25-slice17-report-polish.md && git commit -q -F - <<'EOF'
docs: slice 17 findings, index and rulings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Verification (orchestrator, after the final review)

1. Both gates as in Task 3 step 2.
2. Live check on dev, read-only (no migration needed; no new rows): start the API on :8000 and a production build of the web app (`npm run build && npx next start -p 3001`); read the five stored share tokens with `docker compose exec -T db psql -U bsi_owner -d bsi -tAc "select type, share_token from report_run order by created_at"`; for each, `curl -s -o /tmp/x.pdf -D - -w '%{http_code}\n' localhost:3001/r/$TOKEN/pdf` → 200, `%PDF-`, `content-disposition` filename, `cache-control: no-store`; `curl -s localhost:3001/r/$TOKEN | grep -o 'href="/r/[^"]*/pdf"'`; `/r/short/pdf` and `/r/unknown-token-unknown-token-xyz/pdf` → 404 bodies "Not found" with no product name. Record in findings §2 as observed. Stop both servers.
3. Update the process memory: the frontend rule is now "Server Components, server actions, and the one Route Handler `app/r/[token]/pdf/route.ts`".
4. Finishing menu before pushing; PR with `GH_TOKEN=$(gh auth token -u aiagencyindia-lab)`; merge only on the user's say-so.

## Changes made during execution

Deviations from the text above, as recorded in the execution ledger (`.superpowers/sdd/2026-09-25-slice17-report-polish/progress.md`) and the Task 1 report; the spec's Rulings section gives the reasons where a ruling covers the change.

- Task 1: `apps/web/vitest.config.ts` gained an `@` → `src` alias (spec ruling 3); the file map did not list it.
- Task 1: the route test reads the call as `vi.mocked(fetch).mock.calls[0]` instead of `fetchMock.mock.calls[0]`, because `vi.fn(async () => …)` infers a no-argument mock and the destructuring failed `tsc` (TS2493); this is the pattern `src/lib/api.test.ts` already uses, and the assertions are unchanged (Task 1 report; no spec ruling).
- Task 1: `API_URL` also appears in the new route, so the Global Constraint "`API_URL` stays only in `lib/api.ts` and the login action" was amended to include the route, and Step 4's grep expectation with it (spec ruling 4).
- Task 2: two tests the plan did not list, the `generate` test in `tests/integration/test_reports.py` and the manual-run test in `tests/integration/test_api_reports.py`, changed their `methodology_version` literal from `"1"` to `"2"` (spec ruling 5).
- Task 2: the integration tests assert `Third party` and `Llms txt`/`Low` as this plan's text specifies; this differs from the spec §2 example cells (`Own site`, `H1 missing`), not from the plan (spec ruling 6).
- Final review: the SEO "Page citability" Cluster cell reads `{label(intent)} · {topic}` through a new `cluster_label()` instead of the raw cluster key, with a unit test and the integration assertion moved to `Commercial · shoes` (spec ruling 7).
- Final review: the PDF route's upstream fetch passes `signal: AbortSignal.timeout(30_000)`, so a hung API becomes the existing 502, and the route test checks the signal (spec ruling 8).
