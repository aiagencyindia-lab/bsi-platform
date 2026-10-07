# Slice 48 design: an add-domain form on the Brand SERP page

## Context

Codebase facts: main `5d6326f`, checked 2026-10-07.

Slice 47 made the Brand SERP page (`apps/web/src/app/(app)/b/[id]/serp/page.tsx`) say "Not audited automatically: the brand has no declared domain." for an active brand with no domain. Its final review deferred a minor: the line names a fix the web app gives no way to make, since no web page adds a domain; they are declared only through the API (findings-slice47 §3, R7).

`POST /v1/brands/{id}/domains` (`apps/api/bsi_api/routers/brands.py`, `create_domain`) takes `{"host", "is_primary"}`. The host is normalized and must be a public host name (422 otherwise); a host already declared for the brand is 409. On success it re-flags the brand's citations (`reflag_citations`). `is_primary` is stored but read nowhere. A brand with a declared domain becomes eligible for the weekly Brand SERP audit (`due_serp_audits()`, migration 0024; paid DataForSEO searches) and the weekly site audit. Once it has a domain, a brand is due as soon as one of its two query kinds has no error-free page in the last 7 days, no `audit_serp` job was created in the last day or is still queued or running, and fewer than 3 failed in 7 days; so, while the worker runs with DataForSEO credentials and budget room, its first audit can be queued at the next sweep (every 60 s).

The web app's existing write pattern is a server action that calls `api()` and then `redirect()` (the webhook form, `apps/web/src/app/(app)/b/[id]/alerts/actions.ts`); `api()` logs and throws on a non-2xx answer other than 401/404, and the `(app)` error page shows the thrown error; in production Next replaces a server action's error message with a generic one plus a digest (the problem and its request id stay in the web server log). A 422 from the API carries its reasons in `errors[]` and no `detail`, so `api()`'s message is only `422 Validation failed (request …)`.

Classification: **bounded** (an existing page and an existing API route), said as the first line of the first brainstorming reply with the session model (Opus 5.5). The user's process asks for a spec and plan even for small changes, so the full process is followed.

Decisions approved in chat (2026-10-07), each after approaches with trade-offs and a recommendation written in a chat message:
1. An add-domain form on the Brand SERP page; over naming the API route in the line, or a full domains screen (list, add, remove, primary).
2. A warning by the form and no separate confirmation note; over the warning plus a "Domain added." note, or no warning.
3. After the spec review showed the error page does not show the API's reason (the fact behind Section 1's error behaviour), re-asked: a browser `pattern` that refuses a host with no dot; over catching the error and returning with a note, or leaving it as is.
4. After the spec review: a visible label and the warning linked with `aria-describedby`; over `aria-label` only.

Design Section 1 (when the form shows, its field, button and warning, what Add does, errors) and Section 2 (the action, the page condition, two action tests) were each shown in chat and approved. After the spec review, the revised Section 1 (visible label, pattern, the reworded warning, the corrected error behaviour) was shown in chat and approved again.

## Design

The form shows only when the brand is `active` and has no declared domain, which is exactly when the schedule line says "Not audited automatically: the brand has no declared domain.". It sits under that line:

- a visible label "Domain" (`<label htmlFor="host">`) and a text field `id="host"`, `name="host"`, `required`, `pattern=".*\..*"` with `title="A domain name such as example.com"`, `placeholder="example.com"`, `aria-describedby="host-cost"`;
- a button "Add domain";
- a muted line, `id="host-cost"`: "Adding a domain lets the weekly Brand SERP audit run for this brand: paid Google searches, counted against the daily budget. The first can run within minutes."

`addDomain` (a new server action in `serp/actions.ts`) trims the host, sends `POST /v1/brands/{id}/domains` with `{"host": "<trimmed>"}` (no `is_primary`, so the API's default `false` applies), and redirects to `/b/{id}/serp` with no note. The reloaded page has one domain, so the schedule line reads "Audited automatically once a week." and the form is gone.

The browser refuses a host with no dot (for example `walkaroo` or `localhost`) before sending, showing the field's `title`. The pattern is anchored by the browser, so `walkaroo.in` passes. A host it passes but the API refuses (for example an IP address, or `walkaroo.` and `www.walkaroo`, which the API normalizes to `walkaroo`; 422), or a duplicate, makes `api()` throw before the redirect, and the `(app)` error page shows a generic message with a digest in production, as for the webhook form. In development it shows `422 Validation failed (request …)` with no reason, `409 Domain already exists: <host> (request …)`, or `500 Internal error (request …)`. A duplicate needs a second submit: a later one (a stale tab) is a 409; two in the same moment can both pass the API's check, and the second insert fails the `(brand_id, host)` unique constraint as a 500. In both the domain was added, and reloading the page shows it. `redirect()` is not inside a try/catch.

Unchanged: `serpSchedule` and its three lines, "Run audit now", the status line and the audit cards. An archived brand gets no form.

As a diff against main `5d6326f` (generated from the proof below):

```diff
diff --git a/apps/web/src/app/(app)/b/[id]/serp/actions.test.ts b/apps/web/src/app/(app)/b/[id]/serp/actions.test.ts
new file mode 100644
--- /dev/null
+++ b/apps/web/src/app/(app)/b/[id]/serp/actions.test.ts
@@ -0,0 +1,55 @@
+import { afterEach, beforeEach, expect, test, vi } from "vitest";
+
+vi.mock("server-only", () => ({}));
+const cookieStore = { get: vi.fn() };
+vi.mock("next/headers", () => ({ cookies: vi.fn(async () => cookieStore) }));
+const redirect = vi.fn();
+vi.mock("next/navigation", () => ({ notFound: vi.fn(), redirect }));
+
+const { addDomain } = await import("./actions");
+
+const ID = "1eb6c00a-4b18-4512-b515-dd1d8039511f";
+const form = (host: string) => {
+  const f = new FormData();
+  f.set("brand_id", ID);
+  f.set("host", host);
+  return f;
+};
+
+beforeEach(() => cookieStore.get.mockReturnValue({ value: "bsi_key_1" }));
+afterEach(() => {
+  vi.unstubAllGlobals();
+  vi.restoreAllMocks();
+  redirect.mockClear();
+});
+
+test("addDomain posts the trimmed host, then returns to the page", async () => {
+  vi.stubGlobal(
+    "fetch",
+    vi.fn(async () => new Response("{}", { status: 201 })),
+  );
+  await addDomain(form("  walkaroo.in "));
+  expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
+  const [url, init] = vi.mocked(fetch).mock.calls[0];
+  expect(url).toBe(`http://localhost:8000/v1/brands/${ID}/domains`);
+  expect(init).toEqual({
+    method: "POST",
+    cache: "no-store",
+    headers: {
+      "Content-Type": "application/json",
+      Authorization: "Bearer bsi_key_1",
+    },
+    body: '{"host":"walkaroo.in"}',
+  });
+  expect(redirect).toHaveBeenCalledWith(`/b/${ID}/serp`);
+});
+
+test("addDomain does not redirect when the API refuses the host", async () => {
+  vi.spyOn(console, "error").mockImplementation(() => {});
+  vi.stubGlobal(
+    "fetch",
+    vi.fn(async () => new Response("{}", { status: 422 })),
+  );
+  await expect(addDomain(form("localhost"))).rejects.toThrow(/^422/);
+  expect(redirect).not.toHaveBeenCalled();
+});
diff --git a/apps/web/src/app/(app)/b/[id]/serp/actions.ts b/apps/web/src/app/(app)/b/[id]/serp/actions.ts
--- a/apps/web/src/app/(app)/b/[id]/serp/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/serp/actions.ts
@@ -12,3 +12,14 @@ export async function runSerpAudit(form: FormData) {
   // The API returns this hour's job, which may already be done.
   redirect(`/b/${id}/serp?queued=${encodeURIComponent(job.status)}`);
 }
+
+export async function addDomain(form: FormData) {
+  const id = String(form.get("brand_id"));
+  const host = String(form.get("host") ?? "").trim();
+  await api(`/brands/${id}/domains`, {
+    method: "POST",
+    headers: { "Content-Type": "application/json" },
+    body: JSON.stringify({ host }),
+  });
+  redirect(`/b/${id}/serp`);
+}
diff --git a/apps/web/src/app/(app)/b/[id]/serp/page.tsx b/apps/web/src/app/(app)/b/[id]/serp/page.tsx
--- a/apps/web/src/app/(app)/b/[id]/serp/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/serp/page.tsx
@@ -10,7 +10,7 @@ import {
   type Params,
 } from "@/lib/format";
 import type { Brand, Domain, SerpAudits } from "@/lib/types";
-import { runSerpAudit } from "./actions";
+import { addDomain, runSerpAudit } from "./actions";
 
 export default async function Serp({
   params,
@@ -37,6 +37,29 @@ export default async function Serp({
         )}
       </form>
       <p className="muted">{serpSchedule(brand.status, domains.length)}</p>
+      {brand.status === "active" && domains.length === 0 && (
+        <>
+          <form action={addDomain} className="row">
+            <input type="hidden" name="brand_id" value={id} />
+            <label htmlFor="host">Domain</label>
+            <input
+              id="host"
+              name="host"
+              required
+              pattern=".*\..*"
+              title="A domain name such as example.com"
+              placeholder="example.com"
+              aria-describedby="host-cost"
+            />
+            <button>Add domain</button>
+          </form>
+          <p className="muted" id="host-cost">
+            Adding a domain lets the weekly Brand SERP audit run for this brand:
+            paid Google searches, counted against the daily budget. The first
+            can run within minutes.
+          </p>
+        </>
+      )}
       {status && <p className="muted">{status}</p>}
       {audits.length === 0 && (
         <p className="muted">
```

## Testing

New `apps/web/src/app/(app)/b/[id]/serp/actions.test.ts` (in the diff above), with the mocks of the existing products CSV route test (`server-only`, `next/headers` cookies, `next/navigation` redirect, a stubbed `fetch`):

- `addDomain posts the trimmed host, then returns to the page`: for `"  walkaroo.in "`, `fetch` is called once with `http://localhost:8000/v1/brands/<id>/domains` and exactly `method: "POST"`, `cache: "no-store"`, headers `Content-Type: application/json` and `Authorization: Bearer bsi_key_1`, body `{"host":"walkaroo.in"}`; `redirect` is called with `/b/<id>/serp`.
- `addDomain does not redirect when the API refuses the host`: with a 422 answer, `addDomain` rejects with a message starting `422` and `redirect` is not called. The test silences `console.error`, which `api()` calls on every non-2xx answer, and `afterEach` restores it (R1).

No test covers the page's form condition (`brand.status === "active" && domains.length === 0`) or its attributes (R3). Expected gates: web 52 vitest (50 on main plus 2), lint, typecheck and build pass; backend unchanged at `1753 passed, 2 deselected`.

### Proof

Run 2026-10-07 in the scratchpad on a copy of main's `apps/web` (`git archive`), with the repo's `node_modules` linked.

- Red, main's code with the new test file: `Tests  2 failed (2)`, both `TypeError: addDomain is not a function`.
- Green, patched (re-run after the spec review's changes): the test file gives `Tests  2 passed (2)`; typecheck, lint, test (`Tests  52 passed (52)`) and build (`Compiled successfully`) exit 0. The gate's last step, `gen:check`, was not run: the copy holds only `apps/web` and has no `scripts/export_openapi.py`. No API file changes.
- Prettier is not in the gate. Main's `page.tsx` passes `prettier --check`; the new code is written as Prettier writes it, and all three changed files pass.
- The pattern, checked in Node with the `v` flag browsers use (`^(?:.*\..*)$`): `walkaroo` false, `localhost` false, `walkaroo.in` true, `127.0.0.1` true (left to the API).

Each change below fails one of the two tests (`Tests  1 failed | 1 passed (2)`):

| Mutant | Change | Failing test |
|---|---|---|
| M1 | the host is not trimmed | `addDomain posts the trimmed host, then returns to the page` |
| M2 | the path is `/brands/${id}/domain` | `addDomain posts the trimmed host, then returns to the page` |
| M3 | the redirect goes to `/b/${id}` | `addDomain posts the trimmed host, then returns to the page` |
| M4 | no `Content-Type` header | `addDomain posts the trimmed host, then returns to the page` |
| M5 | the redirect runs before the API call | `addDomain does not redirect when the API refuses the host` |

## Rulings

Quoted from the ledger:

> Ruling: R1. Decided: the error test silences console.error with vi.spyOn (api() logs every non-2xx answer) and afterEach calls vi.restoreAllMocks(); neither was in the Section 2 text. Found by: the controller, running the proof. Why: the gate's test output stays free of a logged "API problem" line, and the spy does not leak into other tests. Cost if wrong: an unexpected console.error in that test would be hidden. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R2. Decided: the spec review's other findings are fixed: the spec states what a refused host shows (production: a generic error with a digest, the API problem in the web server log; development: "422 Validation failed (request …)" with no reason, since the 422 carries its reasons in errors[] and no detail) (Important 1); "no web page adds a domain" replaces "no web page calls the domains API" (Minor 1); a later duplicate submit is a 409 and a same-moment double submit is a 500 from the unique constraint, both after the domain was added (Minor 2); the warning says "lets the weekly Brand SERP audit run for this brand" instead of "starts" (Minor 3); the live check removes the domain before the worker next starts and names the delete's re-flag (Minor 5); the untested page condition is its own ruling, R3 (Minor 7). Minor 6 (chat-only claims) is left. Found by: the spec reviewer (Opus 5.5, a862091404531fe1d), 2026-10-07. Why: wrong or overstated statements of mine. Cost if wrong: none to behaviour beyond the warning's wording. How named: in chat, 2026-10-07, after the spec review.

> Ruling: R3. Decided: no test covers the page's form condition (brand.status === "active" && domains.length === 0) or its attributes (label, pattern, aria-describedby); the action tests cover addDomain only. Found by: the spec reviewer (Minor 7) and the controller. Why: the repo has no tests for Server Component pages; the condition is the case serpSchedule's test pins for the no-domain line. Cost if wrong: a wiring slip (the form shown for an archived brand, or hidden for a no-domain brand, or a dropped pattern) would ship unnoticed by the gate. How named: in chat, 2026-10-07, after the spec review.

> Ruling: R4. Decided: the spec re-review's minors are fixed: the Design names walkaroo. and www.walkaroo as hosts the pattern passes and the API refuses (Minor 1); the error text gives the development message for each cause (422, 409, 500) (Minor 2); the live check keeps the worker's conditions (credentials, budget room) and says an active brand with no domain (Minor 3); the Context records that the revised Section 1 was shown and approved (Minor 4). Found by: the spec re-reviewer (Opus 5.5, a5fdc2e90f6b2c82c), 2026-10-07. Why: incomplete statements of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the re-review.

> Ruling: R5. Decided: the plan review's three minors are fixed: Step 2 names "a Failed Tests 2 banner" instead of quoting its dashes (Minor 1); Step 5 says the gate file, not its stdout, has no API problem line (Minor 2); departure 2 adds the spec's Prettier check (Minor 3). Found by: the plan reviewer (Opus 5.5, a5ed8116671076bb7), 2026-10-07. Why: inexact statements of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the plan review.

## Deferred minors

Quoted from the ledger:

- "minor (deferred): spec review minor 6, the classification line, the chat approvals and the ledger quotes cannot be checked from the repo (R2)."

## Live check

Optional, asked first: on dev, open the Brand SERP page of an active brand with no domain, add a domain and see the line change. It writes a `domain` row (and re-flags that brand's citations) and `api_key.last_used_at`; with a domain the brand becomes due, so the worker stays stopped, and the domain is removed with `DELETE /v1/brands/{id}/domains/{domain_id}` (which re-flags the citations again) before the worker next starts; otherwise, with DataForSEO credentials and budget room, its first sweep queues a paid SERP audit.
