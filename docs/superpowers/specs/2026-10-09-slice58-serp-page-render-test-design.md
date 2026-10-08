# Slice 58 design: a render test for the Brand SERP page, and the test-only web minors

Classification: architectural, said first in chat on 2026-10-09, before the first question: no test renders an App Router page today, so the harness is new. Session model Fable 5.1 for the brainstorm, the approaches, the proof and this spec (the user chose to stay on Fable for the proof and spec on 2026-10-09); implementation and reviews on Opus 5.5.

## Context

Five deferred items name one gap: no test renders the Brand SERP page (apps/web/src/app/(app)/b/[id]/serp/page.tsx). Slice 47 R2 (the page's wiring: three fetches and the `serpSchedule` arguments), slice 48 R3 (the add-domain form's condition and attributes), slice 54 M4 (the domain note rendered outside the form condition) and slice 57 R3 with its correction (M9, `budget_room` passed; M13, `job?.status` passed) were each deferred for the same reason, in each ruling's own words: 47 R2 and 48 R3 say "the repo has no tests for Server Component pages", 54 M4 "no test renders the page", 57 R3 "no test renders the Brand SERP page". The gate (tsc, eslint, vitest) catches none of those slips.

The repo already has what a page test needs: `renderToStaticMarkup` from react-dom/server is the pattern in src/components/ReportBody.test.tsx and RivalPages.test.tsx, and src/app/(app)/b/[id]/serp/actions.test.ts and src/lib/api.test.ts show the mocking (`server-only`, `next/headers`, `next/navigation`, a `fetch` stub; the `notFound` that throws `NOT_FOUND` is api.test.ts's). The page is an async function, so a test can await it and render the element. No DOM library is installed or needed.

An inventory of docs/findings-slice47.md to findings-slice57.md, read in chat on 2026-10-09 and not kept as a file, found 35 open deferred minors, about 11 of them test-only; the rest were fixed by later slices or are documentation items.

User decisions (2026-10-09), with the approaches text shown in chat before each:
1. Scope A, over B (A plus the behaviour minors 48:79, 47:80, 54:73, 54:75) and C (all 35 open minors): one page-render test, plus the five test-only web minors: 57:155 (no `jobStatus = null` case), 54:72 (`domainNote` import out of order), 52:64 (the `test.each` guard cases do not pin the `console.error` count), 49:103 (the `publicApi` dot-segment test asserts no log), 49:104 (`restoreAllMocks` leaves the cookie `mockResolvedValue`). No behaviour change.
2. Harness H1, over H2 (`vi.mock("@/lib/api")`, which skips `seg()` and the path guard) and H3 (a shared src/test/ render helper nothing else needs yet): the real `api()` with `fetch` stubbed per URL, Next mocked as actions.test.ts does.
3. Section 1 approved; then re-asked when the proof showed a fact behind it was wrong (a brand with no domain can never show the budget line, since "no declared domain" outranks the budget in `serpSchedule`): (a) four cases, over (b) three cases with no archived case and a weaker wiring check.
4. Sections 2 (the minors) and 3 (evidence) approved.

## Section 1 — The page-render test

New file apps/web/src/app/(app)/b/[id]/serp/page.test.tsx.

Setup, as in actions.test.ts and api.test.ts: `vi.mock("server-only")`; `vi.mock("next/headers")` with a cookie store whose `get` returns `bsi_key_1`; `vi.mock("next/navigation")` with `notFound` throwing `NOT_FOUND` and a `redirect` spy; then `const { default: Serp } = await import("./page")`.

A `render(data, sp)` helper stubs `fetch` with a map from the three URLs (`http://localhost:8000/v1/brands/{ID}/audits/serp`, `/brands/{ID}`, `/brands/{ID}/domains`) to `Response.json(body)`; any other URL gets a 500, so a wrong path fails as an API error. It records each call's URL and `Authorization` header, awaits `Serp({ params: Promise.resolve({ id: ID }), searchParams: Promise.resolve(sp) })`, and returns `renderToStaticMarkup(element)` with the calls. Fixtures are full typed objects: `brand(status)` with two aliases (so a page that counted aliases instead of domains shows), one `Domain`, and `serp(budget_room, job)` with no audits. A ponytail comment says the helper is factored out to src/test/ when a second page gets a test.

Four cases, all substring checks on the static markup:

1. Active, no domain, no room, no job, `sp = {}`: `fetch` received exactly the three URLs, each with `Authorization: Bearer bsi_key_1`; the markup has "Not audited automatically: the brand has no declared domain.", `<label for="host">Domain</label>`, `pattern=".*\..*"`, `aria-describedby="host-cost"`, `id="host-cost"` and "No audit yet". (47 R2: with `aliases.length` the line changes; 48 R3: the form's condition and attributes.)
2. Active, one domain, no room, no job, `sp = { domain: "exists" }`: the budget line, "Not added: that domain is already declared for this brand.", and no `id="host"`. (57 M9: `true` for `budget_room` gives the weekly line; 54 M4: a note inside the form condition vanishes once there is a domain.)
3. Active, one domain, no room, job queued: "Audited automatically once a week.", not the budget line, and "Audit in progress". (57 M13: without `job?.status` the budget line shows.)
4. Archived, no domain: "Not audited automatically: the brand is archived." and no `id="host"`.

## Section 2 — The test-only minors

- apps/web/src/lib/format.test.ts: `domainNote` moves above `crawlNote` in the import list (54:72); the `serpSchedule` test gains `("active", 1, true, 0, false, null)` → the budget line, with a comment that a NULL job status is neither queued nor running (57:155).
- apps/web/src/lib/api.test.ts: `afterEach` adds `vi.mocked(cookies).mockReset()` with a comment on why (49:104); the `test.each` guard cases gain `expect(log).toHaveBeenCalledTimes(1)` (52:64); `publicApi refuses a dot segment` keeps the spy and asserts `toHaveBeenCalledTimes(1)` and `toHaveBeenCalledWith("API path refused", '"/r/.."', 5)` (49:103).

No production code changes. Nothing is installed.

## Section 3 — Testing

- Red: this slice adds tests to code that is already right, so the new tests pass on main's code too (the proof ran them on a clean copy: 80 passed). The evidence that the tests bite is the mutation table below.
- Green: vitest 76 → 80 (four page cases; the `null` case is an `expect` inside an existing test), typecheck and eslint clean, `npm run gate` at execution. No backend change; the backend gate runs once before the finishing menu.
- No live check: nothing user-visible changes.

## The change

Generated from the proof (a scratchpad copy of main d6f2703 with the change applied):

```diff
--- a/apps/web/src/app/(app)/b/[id]/serp/page.test.tsx
+++ b/apps/web/src/app/(app)/b/[id]/serp/page.test.tsx
@@ -0,0 +1,135 @@
+import { renderToStaticMarkup } from "react-dom/server";
+import { afterEach, expect, test, vi } from "vitest";
+import type { Brand, Domain, SerpAudits } from "@/lib/types";
+import type { Params } from "@/lib/format";
+
+vi.mock("server-only", () => ({}));
+const cookieStore = { get: () => ({ value: "bsi_key_1" }) };
+vi.mock("next/headers", () => ({ cookies: vi.fn(async () => cookieStore) }));
+vi.mock("next/navigation", () => ({
+  notFound: () => {
+    throw new Error("NOT_FOUND");
+  },
+  redirect: vi.fn(),
+}));
+
+const { default: Serp } = await import("./page");
+
+const ID = "1eb6c00a-4b18-4512-b515-dd1d8039511f";
+const BASE = `http://localhost:8000/v1/brands/${ID}`;
+
+const brand = (status: string): Brand => ({
+  id: ID,
+  name: "Walkaroo",
+  status,
+  // Two aliases, so a page that counted aliases instead of domains shows.
+  aliases: ["Walkaroo", "WKR"],
+  category: null,
+  has_webhook_secret: false,
+  report_accent: null,
+  report_logo_url: null,
+  report_prepared_by: null,
+  webhook_url: null,
+});
+const DOMAIN: Domain = { id: ID, host: "walkaroo.in", is_primary: true };
+const serp = (
+  budget_room: boolean,
+  job: SerpAudits["job"] = null,
+): SerpAudits => ({
+  job,
+  audits: [],
+  serp_configured: true,
+  failed_7d: 0,
+  budget_room,
+});
+
+afterEach(() => {
+  vi.unstubAllGlobals();
+});
+
+// ponytail: the harness lives here while one page has a test; factor it
+// out to src/test/ when a second page gets one.
+/** Renders the page with the three API responses stubbed by URL; returns
+ * the markup and the (url, Authorization) pairs fetch received. */
+async function render(
+  data: { serp: SerpAudits; brand: Brand; domains: Domain[] },
+  sp: Params = {},
+) {
+  const bodies: Record<string, unknown> = {
+    [`${BASE}/audits/serp`]: data.serp,
+    [BASE]: data.brand,
+    [`${BASE}/domains`]: data.domains,
+  };
+  const calls: [string, string | undefined][] = [];
+  vi.stubGlobal(
+    "fetch",
+    vi.fn(async (url: string, init?: RequestInit) => {
+      const auth = (init?.headers as Record<string, string>)?.Authorization;
+      calls.push([url, auth]);
+      return url in bodies
+        ? Response.json(bodies[url])
+        : new Response("{}", { status: 500 });
+    }),
+  );
+  const element = await Serp({
+    params: Promise.resolve({ id: ID }),
+    searchParams: Promise.resolve(sp),
+  });
+  return { html: renderToStaticMarkup(element), calls };
+}
+
+const BUDGET =
+  "Audited automatically once a week; today the daily budget has no room for a Brand SERP audit, so a due audit waits until there is room. The budget resets at midnight UTC.";
+
+test("an active brand with no domain gets the no-domain line and the form", async () => {
+  const { html, calls } = await render({
+    serp: serp(false),
+    brand: brand("active"),
+    domains: [],
+  });
+  expect(calls.map(([url]) => url).sort()).toEqual(
+    [`${BASE}/audits/serp`, BASE, `${BASE}/domains`].sort(),
+  );
+  expect(calls.every(([, auth]) => auth === "Bearer bsi_key_1")).toBe(true);
+  expect(html).toContain(
+    "Not audited automatically: the brand has no declared domain.",
+  );
+  expect(html).toContain('<label for="host">Domain</label>');
+  expect(html).toContain('pattern=".*\\..*"');
+  expect(html).toContain('aria-describedby="host-cost"');
+  expect(html).toContain('id="host-cost"');
+  expect(html).toContain("No audit yet");
+});
+
+test("with a domain and no room, the budget note and the domain note show without the form", async () => {
+  const { html } = await render(
+    { serp: serp(false), brand: brand("active"), domains: [DOMAIN] },
+    { domain: "exists" },
+  );
+  expect(html).toContain(BUDGET);
+  expect(html).toContain(
+    "Not added: that domain is already declared for this brand.",
+  );
+  expect(html).not.toContain('id="host"');
+});
+
+test("a queued audit hides the budget note", async () => {
+  const { html } = await render({
+    serp: serp(false, { status: "queued", error: null }),
+    brand: brand("active"),
+    domains: [DOMAIN],
+  });
+  expect(html).toContain("Audited automatically once a week.");
+  expect(html).not.toContain(BUDGET);
+  expect(html).toContain("Audit in progress");
+});
+
+test("an archived brand gets no form", async () => {
+  const { html } = await render({
+    serp: serp(true),
+    brand: brand("archived"),
+    domains: [],
+  });
+  expect(html).toContain("Not audited automatically: the brand is archived.");
+  expect(html).not.toContain('id="host"');
+});
--- a/apps/web/src/lib/format.test.ts
+++ b/apps/web/src/lib/format.test.ts
@@ -5,8 +5,8 @@
   apiQuery,
   auditNote,
   ciText,
-  domainNote,
   crawlNote,
+  domainNote,
   droppedNote,
   highlight,
   KIND,
@@ -294,6 +294,8 @@
   expect(serpSchedule("archived", 1, false, 3, true)).toBe(archived);
   expect(serpSchedule("archived", 0, true, 0, true)).toBe(archived);
   expect(serpSchedule("active", 1, true, 2, false)).toBe(noBudget);
+  // A job row with a NULL status is neither queued nor running.
+  expect(serpSchedule("active", 1, true, 0, false, null)).toBe(noBudget);
   expect(serpSchedule("active", 1, true, 0, false, "done")).toBe(noBudget);
   expect(serpSchedule("active", 1, true, 0, false, "failed")).toBe(noBudget);
   // The brand's own waiting job counts against the budget: no note.
--- a/apps/web/src/lib/api.test.ts
+++ b/apps/web/src/lib/api.test.ts
@@ -21,6 +21,9 @@
 afterEach(() => {
   vi.unstubAllGlobals();
   vi.restoreAllMocks();
+  // restoreAllMocks keeps a vi.fn's mockResolvedValue; drop the cookie so
+  // a test that forgets signedIn() cannot inherit the previous one's.
+  vi.mocked(cookies).mockReset();
 });
 
 const signedIn = () =>
@@ -56,6 +59,7 @@
   vi.stubGlobal("fetch", fetchMock);
   await expect(api(path)).rejects.toThrow("NOT_FOUND");
   expect(fetchMock).not.toHaveBeenCalled();
+  expect(log).toHaveBeenCalledTimes(1);
   expect(log).toHaveBeenCalledWith(
     "API path refused",
     JSON.stringify(path),
@@ -91,11 +95,13 @@
 });
 
 test("publicApi refuses a dot segment", async () => {
-  vi.spyOn(console, "error").mockImplementation(() => {});
+  const log = vi.spyOn(console, "error").mockImplementation(() => {});
   const fetchMock = vi.fn();
   vi.stubGlobal("fetch", fetchMock);
   await expect(publicApi("/r/..")).rejects.toThrow("NOT_FOUND");
   expect(fetchMock).not.toHaveBeenCalled();
+  expect(log).toHaveBeenCalledTimes(1);
+  expect(log).toHaveBeenCalledWith("API path refused", '"/r/.."', 5);
 });
 
 test("seg returns a UUID, a report type and a share token unchanged", () => {
```

## Evidence

Proof directory: a fresh scratchpad copy of main d6f2703 (`proof58-1791484432`), written only by the controller.

- Green, patched: `npx vitest run` 80 passed (80); `npm run typecheck` no error; `npx eslint .` clean. `npm run gate` (build, gen:check) runs at execution.
- Clean code with the new tests: 80 passed (80), as Section 3 says.
- The first draft of case 1 asserted the budget line with no domain and failed on the proof (the markup showed the no-domain line); decision 3 re-asked the design and the four cases above are what the proof ran.

Mutations, each applied alone to the patched copy and reverted (whole vitest run):

| # | Mutation | Result |
|---|---|---|
| M1 | page passes true for budget_room | killed: with a domain and no room, the budget note and the domain note show without the form (1 failed) |
| M2 | page drops job?.status | killed: a queued audit hides the budget note (1 failed) |
| M3 | domainNote inside the form condition | killed: with a domain and no room, the budget note and the domain note show without the form (1 failed) |
| M4 | aliases.length in place of domains.length (both uses) | killed: an active brand with no domain gets the no-domain line and the form (1 failed) |
| M5 | host input loses pattern | killed: an active brand with no domain gets the no-domain line and the form (1 failed) |
| M6 | sendAsWritten logs twice | killed: the 8 `test.each` guard cases, the long-path test and the publicApi dot-segment test (10 failed) |
| M7 | publicApi skips the guard | killed: publicApi refuses a dot segment (1 failed); main's test already kills this one (the stubbed `fetch` returns undefined, so the call throws a TypeError), so it shows nothing new. The 49:103 log assertion is exercised by M6, which fails the publicApi test through `toHaveBeenCalledTimes(1)`. |

## Rulings

Ruling: R1. Decided: the proof's `render` helper returns the `fetch` calls as `(url, Authorization)` pairs and case 1 compares the sorted URL list, rather than asserting call order. Found by: the controller, writing the proof. Why: `Promise.all` starts the three fetches together; their order is not part of the page's contract. Cost if wrong: none to behaviour. How named: this spec and chat.

Ruling: R2. Decided: the spec's vitest count is 76 → 80, not the plan-mode draft's 77. Found by: the controller, the proof's green run. Why: four `test()` cases, not one; the draft counted the page test as one. Cost if wrong: none. How named: this spec and chat.

Ruling: R3. Decided: the spec review's six minors are fixed in a second spec commit: the inventory sentence no longer states a total (the chat reading gave 45, the reviewer's grep 46, and a plain grep cannot settle it); the deferral reason quotes each ruling's own words; the M7 row says main's test already kills it and that M6 exercises the new publicApi log assertion; the README clause is replaced by "no README row mentions the gap"; findings-slice47.md line 79 joins the docs follow-ups; api.test.ts is cited beside actions.test.ts for the throwing `notFound`. Found by: the spec reviewer (Opus 5.5), 2026-10-09. Why: an unverifiable count, a quotation that was true for two of four rulings, a mutant that proved nothing, a pointer at nothing, an omission, and a mis-citation, all mine. Cost if wrong: none to behaviour. How named: this spec and chat.

## Out of scope

- The behaviour minors: 48:79 (a missing `brand_id` posts to `/brands/null/domains`), 47:80 (a future status reads "archived"), 54:73 (a double submit reaches the error page), 54:75 (one note for every 422 cause), 57:152 (the budget note for a brand that is not due), 57:154 (no lock timeout on the GET).
- The backend, probe-script and docs-only minors from the inventory.
- A shared render helper (H3) and tests for the other seven pages of the same shape.

## Docs follow-ups

- Dated notes under the lines that record the gap: findings-slice47.md R2 and its deferred line 79 (R2's example is narrow: another array's `.length` would type-check; cases 2 and 3, with one domain and no audits, catch `audits.length` too), findings-slice48.md R3, findings-slice54.md M4 (the table row and the deferred line), findings-slice57.md R3 and its deferred line. No README row mentions the gap, so only the slice 58 rows are added.

## Deferred

- minor (deferred): the page test renders only the empty-audits branch; the per-audit cards (ownership, type counts, the results table) are rendered by no test.
