# Slice 48 design: an add-domain form on the Brand SERP page

## Context

Codebase facts: main `5d6326f`, checked 2026-10-07.

Slice 47 made the Brand SERP page (`apps/web/src/app/(app)/b/[id]/serp/page.tsx`) say "Not audited automatically: the brand has no declared domain." for an active brand with no domain. Its final review deferred a minor: the line names a fix the web app gives no way to make, since no web page calls the domains API (findings-slice47 §3, R7).

`POST /v1/brands/{id}/domains` (`apps/api/bsi_api/routers/brands.py`, `create_domain`) takes `{"host", "is_primary"}`. The host is normalized and must be a public host name (422 otherwise); a host already declared for the brand is 409. On success it re-flags the brand's citations (`reflag_citations`). `is_primary` is stored but read nowhere. A brand with a declared domain becomes eligible for the weekly Brand SERP audit (`due_serp_audits()`, migration 0024; paid DataForSEO searches) and the weekly site audit. Once it has a domain, a brand is due as soon as one of its two query kinds has no error-free page in the last 7 days, no `audit_serp` job was created in the last day or is still queued or running, and fewer than 3 failed in 7 days; so, while the worker runs with DataForSEO credentials and budget room, its first audit can be queued at the next sweep (every 60 s).

The web app's existing write pattern is a server action that calls `api()` and then `redirect()` (the webhook form, `apps/web/src/app/(app)/b/[id]/alerts/actions.ts`); `api()` throws on a non-2xx answer other than 401/404, which the `(app)` error page shows.

Classification: **bounded** (an existing page and an existing API route), said as the first line of the first brainstorming reply with the session model (Opus 5.5). The user's process asks for a spec and plan even for small changes, so the full process is followed.

Decisions approved in chat (2026-10-07), each after approaches with trade-offs and a recommendation written in a chat message:
1. An add-domain form on the Brand SERP page; over naming the API route in the line, or a full domains screen (list, add, remove, primary).
2. A warning by the form and no separate confirmation note; over the warning plus a "Domain added." note, or no warning.

Design Section 1 (when the form shows, its field, button and warning, what Add does, errors) and Section 2 (the action, the page condition, two action tests) were each shown in chat and approved.

## Design

The form shows only when the brand is `active` and has no declared domain, which is exactly when the schedule line says "Not audited automatically: the brand has no declared domain.". It sits under that line:

- a text field `host`, `required`, `placeholder="example.com"`, `aria-label="Domain"`;
- a button "Add domain";
- a muted line: "Adding a domain starts the weekly Brand SERP audit: paid Google searches, counted against the daily budget. The first can run within minutes."

`addDomain` (a new server action in `serp/actions.ts`) trims the host, sends `POST /v1/brands/{id}/domains` with `{"host": "<trimmed>"}` (no `is_primary`, so the API's default `false` applies), and redirects to `/b/{id}/serp` with no note. The reloaded page has one domain, so the schedule line reads "Audited automatically once a week." and the form is gone.

A refused host (422) or a duplicate (409; only a race, since the form shows with no domains) makes `api()` throw before the redirect, and the `(app)` error page shows the status and the API's message, as for the webhook form. `redirect()` is not inside a try/catch.

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
@@ -37,6 +37,25 @@ export default async function Serp({
         )}
       </form>
       <p className="muted">{serpSchedule(brand.status, domains.length)}</p>
+      {brand.status === "active" && domains.length === 0 && (
+        <>
+          <form action={addDomain} className="row">
+            <input type="hidden" name="brand_id" value={id} />
+            <input
+              name="host"
+              required
+              placeholder="example.com"
+              aria-label="Domain"
+            />
+            <button>Add domain</button>
+          </form>
+          <p className="muted">
+            Adding a domain starts the weekly Brand SERP audit: paid Google
+            searches, counted against the daily budget. The first can run within
+            minutes.
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

No test covers the page's form condition (`brand.status === "active" && domains.length === 0`); it is page wiring, as in slice 47 (R2 there). Expected gates: web 52 vitest (50 on main plus 2), lint, typecheck and build pass; backend unchanged at `1753 passed, 2 deselected`.

### Proof

Run 2026-10-07 in the scratchpad on a copy of main's `apps/web` (`git archive`), with the repo's `node_modules` linked.

- Red, main's code with the new test file: `Tests  2 failed (2)`, both `TypeError: addDomain is not a function`.
- Green, patched: the test file gives `Tests  2 passed (2)`; typecheck, lint, test (`Tests  52 passed (52)`) and build (`Compiled successfully`) exit 0. The gate's last step, `gen:check`, was not run: the copy holds only `apps/web` and has no `scripts/export_openapi.py`. No API file changes.
- Prettier is not in the gate. Main's `page.tsx` passes `prettier --check`; the new warning paragraph is wrapped as Prettier wraps it, and all three changed files pass.

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

## Deferred minors

None yet.

## Live check

Optional, asked first: on dev, open the Brand SERP page of a brand with no domain, add a domain and see the line change. It writes a `domain` row (and re-flags that brand's citations) and `api_key.last_used_at`; if the worker were running it could then queue a paid SERP audit, so the worker stays stopped. Removing the domain afterwards needs `DELETE /v1/brands/{id}/domains/{domain_id}`.
