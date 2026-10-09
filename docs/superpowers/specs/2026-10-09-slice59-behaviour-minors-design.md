# Slice 59 design: the behaviour minors (web and API)

Classification: architectural, said first in chat on 2026-10-09: "fix every item" spans the web app, the API, the tests, the probe script and the docs, so it was decomposed first. This is the first of four slices. Session model Opus 5.5 throughout.

## Context

The open deferred minors from slices 47–58 were grouped in chat on 2026-10-09: behaviour (web and API), test hardening, the slice 56 probe script, docs, and three that cannot be fixed (chat approvals cannot be verified from the repo). This slice fixes the behaviour group:

- 54:73: two simultaneous submits of the same domain give a 500 (both pass the duplicate SELECT; the second INSERT hits the `(brand_id, host)` unique constraint and nothing catches the IntegrityError).
- 48:79: a missing `brand_id` becomes `"null"` (`String(form.get("brand_id"))`), passes `seg()`, and reaches the API as `/brands/null/…`; the explorer found the pattern in about 20 server actions in 11 files.
- 54:75: one note covers every 422; and `DomainIn.host` has no length cap, unlike the `Host` type (200) used elsewhere.
- 47:80: `serpSchedule` calls any non-active status "archived".
- 57:152: the budget note shows for a brand that is not due (decision 4 of slice 57, reversed here).
- 57:154: the SERP page's GET takes the org's advisory lock with no timeout (decision 2 of slice 57, reversed here).
- 55:121 and 55:122: a redundant `failed or 0` and a `latest_serp` docstring that names only two of its fields.
- New, found while exploring: an archived brand still accepts new domains (`brand_or_404` does not check status).

User decisions (2026-10-09), with the approaches text shown in chat before each:
1. "fix every item" split into four slices, behaviour first (59 behaviour, 60 test hardening, 61 probe script, 62 docs sweep with the three won't-fix items), over two slices or one.
2. The race: A, `INSERT … ON CONFLICT (brand_id, host) DO NOTHING RETURNING`, 409 when no row comes back, over B (catch IntegrityError on flush) and C (a global IntegrityError handler).
3. The missing id: A, one `formSeg(form, name)` helper used at every call site, with the source scan forbidding the old pattern, over B (the serp actions only) and C (`seg()` refusing "null").
4. The 422 note: A, cap `DomainIn.host` at 200 like `Host` and keep the one note, over B (per-cause notes, needing `api()` to expose the 422 body) and C (reword only).
5. Archived brands: A, `POST /domains` returns 409 like the audits POST, over B (leave it) and C (every write route).
6. Other statuses: A, archived reads archived and any other non-active status reads "not active", over B (a database check constraint, migration 0027) and C (leave it).
7. Due brands only (reversing slice 57 decision 4): A, the API returns `serp_due`, computed in Python for one brand mirroring migration 0024, and the note shows only when due, over B (calling `due_serp_audits()` from the API) and C (keep decision 4).
8. The lock (reversing slice 57 decision 2): A, the lock-free split (`lock=False` from the page), over B (`SET LOCAL lock_timeout`) and C (keep it).
9. Sections 1 to 4 approved as shown in chat.

## Section 1 — `POST /brands/{id}/domains`

- An archived brand gets `409 "Brand is archived"` ("Archived brands accept no new domains."), the title the runs and schedules routes use; nothing is written.
- The duplicate check is one statement: `pg_insert(m.Domain).values(...).on_conflict_do_nothing(index_elements=["brand_id", "host"]).returning(m.Domain)`; no row back means 409 "Domain already exists". Two simultaneous submits give one 201 and one 409. The conflict target is exactly the unique constraint, so any other integrity error still surfaces.
- `DomainIn.host` becomes `Host = Field(min_length=3)`, so it is capped at 200 like the other host fields.

## Section 2 — The SERP schedule facts

- `budget_fits(..., *, lock=True)` takes the org's advisory lock only when asked; `serp_budget_fits(..., *, lock=True)` passes it through. Every existing caller keeps the default; only `latest_serp` passes `lock=False`, since the page writes nothing.
- `serp_due(s, brand_id)` in `bsi_core/scheduling.py` mirrors `due_serp_audits()`'s five predicates for one brand in its tenant session, on the DB clock, with the 0024 constants named (`SERP_AUDIT_DAYS`, `SERP_RETRY_DAYS`, `SERP_KINDS`, `SERP_MAX_FAILURES`). The sweep still calls `due_serp_audits()`.
- `latest_serp` returns `serp_due`; `SerpAuditsOut` gains it; the docstring names every field; `failed or 0` becomes `failed`.

## Section 3 — The web

- `formSeg(form, name)` in `lib/api.ts`: a string field goes through `seg()`; a missing or non-text field logs `"API form value missing"` with the quoted name and calls `notFound()`. Every form value used in a path goes through it (R3): `brand_id` in 11 action files, plus `task_id`, `rec_id`, `run_id`, `type`, `observation_id` and `entity_id`. API templates keep `${seg(…)}`, which the existing path scan requires.
- `api-paths.test.ts` gains a scan: no `String(form.get("…_id"))`, `String(form.get("type"))` or `seg(String(` under `src/app`.
- `addDomain` maps `409 Domain already exists` to `?domain=exists` and `409 Brand is archived` to `?domain=archived` ("Not added: the brand is archived."); any other 409 is rethrown.
- `serpSchedule(status, domains, configured, failed7d, budgetRoom, due)`: archived; any other non-active status ("Not audited automatically: the brand is not active."); no domain; not configured; the failure pause; `due && !budgetRoom` gives the budget note; otherwise weekly. `due` replaces `jobStatus`, because `serp_due` is already false while the brand's own audit is queued or running. The page passes `serp_due`.

## Section 4 — Testing and evidence

Backend (1777 → 1792):
- `test_api_crud.py`: an archived brand gets the 409 and no row; a 200-character host passes and a 201-character one gets a 422; a simultaneous duplicate is a 409, not a 500, with one row (R1).
- `test_api_serp.py`: `serp_due` for nine cases (nothing recent, archived, no domain, one kind this week, both kinds this week, a job today, a queued job, two failures, three failures), each also asserting that `due_serp_audits()` agrees (R6); the GET returns while another transaction holds the org's lock; the empty response expects `serp_due: false`.
- `test_budget.py`: `lock=False` gives the same verdict and still fails closed; the default waits for the org's lock (R5).
- `test_api_recommendations.py`: the shared `_wait_until_blocked` helper clears the activity snapshot before each poll (R2).

Web (80 → 88): `formSeg` (three tests), the source scan, `addDomain` (archived note, other 409 rethrown, missing `brand_id` for both serp actions), the `domainNote` archived line, the reworked `serpSchedule` cases, and the page fixture's `serp_due`.

No migration; the dev database stays at 0026. No live check (the page render test covers the new lines; any dev API call writes `api_key.last_used_at`); one is offered at the finishing menu.

## The change

Generated from the proof (a scratchpad copy of main d7e97d3 with the change applied); the generated openapi.json (+8 −2) and schema.d.ts (+9 −3) hunks are omitted.

```diff
--- a/apps/api/bsi_api/routers/audits.py
+++ b/apps/api/bsi_api/routers/audits.py
@@ -7,7 +7,7 @@
 
 from bsi_core import models as m
 from bsi_core.config import get_settings
-from bsi_core.scheduling import serp_budget_fits
+from bsi_core.scheduling import serp_budget_fits, serp_due
 from fastapi import APIRouter
 from sqlalchemy import func, select
 
@@ -58,9 +58,13 @@
 
 @router.get("/serp", response_model=SerpAuditsOut)
 def latest_serp(brand_id: uuid.UUID, c: Ctx = TENANT) -> dict[str, Any]:
-    """The latest page per (kind, country, language), an error row
-    included, and the latest audit_serp job so a failure that wrote no
-    rows (no credentials, budget, stale) still shows."""
+    """The Brand SERP page's data: the latest page per (kind, country,
+    language), an error row included; the latest audit_serp job, so a
+    failure that wrote no rows (no credentials, budget, stale) still
+    shows; whether the API process has DataForSEO credentials; the failed
+    audit_serp jobs in the last 7 days; whether the org's budget has room
+    for an audit (without the org's lock: this request writes nothing);
+    and whether the weekly sweep would queue the brand now (serp_due)."""
     brand_or_404(c, brand_id)
     audits = list(
         c.s.scalars(
@@ -104,6 +108,7 @@
             settings.dataforseo_login
             and settings.dataforseo_password.get_secret_value()
         ),
-        "failed_7d": failed or 0,
-        "budget_room": serp_budget_fits(c.s, c.org_id),
+        "failed_7d": failed,
+        "budget_room": serp_budget_fits(c.s, c.org_id, lock=False),
+        "serp_due": serp_due(c.s, brand_id),
     }
--- a/apps/api/bsi_api/routers/brands.py
+++ b/apps/api/bsi_api/routers/brands.py
@@ -8,6 +8,7 @@
 from fastapi import APIRouter, Response
 from pydantic import AfterValidator, BaseModel, ConfigDict, Field
 from sqlalchemy import func, select, update
+from sqlalchemy.dialects.postgresql import insert as pg_insert
 
 from ..deps import TENANT, Ctx, brand_or_404, child_or_404
 from ..problems import Problem
@@ -131,7 +132,7 @@
 
 
 class DomainIn(BaseModel):
-    host: Annotated[str, AfterValidator(_public_host)] = Field(min_length=3)
+    host: Host = Field(min_length=3)
     is_primary: bool = False
 
 
@@ -253,20 +254,27 @@
 def create_domain(
     brand_id: uuid.UUID, body: DomainIn, c: Ctx = TENANT
 ) -> m.Domain:
-    brand_or_404(c, brand_id)
-    q = select(m.Domain).where(
-        m.Domain.brand_id == brand_id, m.Domain.host == body.host
+    if brand_or_404(c, brand_id).status == "archived":
+        raise Problem(
+            409, "Brand is archived", "Archived brands accept no new domains."
+        )
+    # One statement, so two simultaneous submits of the same host give one
+    # 201 and one 409: the second waits on the (brand_id, host) unique
+    # index and then inserts nothing, where a SELECT first would let both
+    # through to a unique violation (a 500).
+    row = c.s.scalar(
+        pg_insert(m.Domain)
+        .values(
+            org_id=c.org_id,
+            brand_id=brand_id,
+            host=body.host,
+            is_primary=body.is_primary,
+        )
+        .on_conflict_do_nothing(index_elements=["brand_id", "host"])
+        .returning(m.Domain)
     )
-    if c.s.scalars(q).first():
+    if row is None:
         raise Problem(409, "Domain already exists", body.host)
-    row = m.Domain(
-        org_id=c.org_id,
-        brand_id=brand_id,
-        host=body.host,
-        is_primary=body.is_primary,
-    )
-    c.s.add(row)
-    c.s.flush()
     reflag_citations(c.s, brand_id)
     return row
 
--- a/apps/api/bsi_api/schemas.py
+++ b/apps/api/bsi_api/schemas.py
@@ -471,6 +471,9 @@
     # spend: while it is False the sweep skips the brand, if it is due,
     # with no job. The brand's own waiting audit_serp job counts too.
     budget_room: bool
+    # Whether the weekly sweep would queue the brand now (serp_due, which
+    # mirrors due_serp_audits()); the page's budget note needs it true.
+    serp_due: bool
 
 
 class PageOptimizeIn(BaseModel):
--- a/apps/web/src/app/(app)/b/[id]/alerts/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/alerts/actions.ts
@@ -1,10 +1,10 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api, seg } from "@/lib/api";
+import { api, formSeg, seg } from "@/lib/api";
 
 export async function setWebhook(form: FormData) {
-  const id = String(form.get("brand_id"));
+  const id = formSeg(form, "brand_id");
   const value = String(form.get("webhook_url") ?? "").trim();
   const clear = form.get("clear") === "1" || value === "";
   // Not trimmed: the API rejects surrounding whitespace, and a trimmed
@@ -24,7 +24,7 @@
 }
 
 export async function scanNow(form: FormData) {
-  const id = String(form.get("brand_id"));
+  const id = formSeg(form, "brand_id");
   const r = await api<{ created: number }>(`/brands/${seg(id)}/alerts/scan`, {
     method: "POST",
   });
--- a/apps/web/src/app/(app)/b/[id]/clusters/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/clusters/actions.ts
@@ -1,11 +1,11 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api, seg } from "@/lib/api";
+import { api, formSeg, seg } from "@/lib/api";
 import type { Queued } from "@/lib/types";
 
 export async function labelPrompts(form: FormData) {
-  const id = String(form.get("brand_id"));
+  const id = formSeg(form, "brand_id");
   const job = await api<Queued>(`/brands/${seg(id)}/prompts/label`, {
     method: "POST",
   });
@@ -14,7 +14,7 @@
 }
 
 export async function optimizeUrl(form: FormData) {
-  const id = String(form.get("brand_id"));
+  const id = formSeg(form, "brand_id");
   const job = await api<Queued>(`/brands/${seg(id)}/pages/optimize`, {
     method: "POST",
     headers: { "Content-Type": "application/json" },
--- a/apps/web/src/app/(app)/b/[id]/competitors/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/competitors/actions.ts
@@ -1,11 +1,11 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api, seg } from "@/lib/api";
+import { api, formSeg, seg } from "@/lib/api";
 import type { Queued } from "@/lib/types";
 
 export async function crawlRivals(form: FormData) {
-  const id = String(form.get("brand_id"));
+  const id = formSeg(form, "brand_id");
   const job = await api<Queued>(`/brands/${seg(id)}/competitors/crawl`, {
     method: "POST",
   });
--- a/apps/web/src/app/(app)/b/[id]/label/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/label/actions.ts
@@ -1,19 +1,21 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api, seg } from "@/lib/api";
+import { api, formSeg, seg } from "@/lib/api";
 import type { LabelResult } from "@/lib/types";
 
 export async function saveLabel(form: FormData) {
-  const get = (k: string) => String(form.get(k));
+  const brand = formSeg(form, "brand_id");
+  const observation = formSeg(form, "observation_id");
+  const entity = formSeg(form, "entity_id");
   const r = await api<LabelResult>(
-    `/observations/${seg(get("observation_id"))}/labels/${seg(get("entity_id"))}`,
+    `/observations/${seg(observation)}/labels/${seg(entity)}`,
     {
       method: "PUT",
       headers: { "Content-Type": "application/json" },
-      body: JSON.stringify({ label: get("label") }),
+      body: JSON.stringify({ label: String(form.get("label")) }),
     },
   );
   const q = new URLSearchParams({ you: r.label, judge: r.judge });
-  redirect(`/b/${get("brand_id")}/label?${q}`);
+  redirect(`/b/${brand}/label?${q}`);
 }
--- a/apps/web/src/app/(app)/b/[id]/products/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/products/actions.ts
@@ -1,7 +1,7 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api, seg } from "@/lib/api";
+import { api, formSeg, seg } from "@/lib/api";
 import type { ImportResult, Queued } from "@/lib/types";
 
 const back = (id: string, status: string, extra = "") =>
@@ -13,7 +13,7 @@
 const is422 = (e: unknown) => e instanceof Error && e.message.startsWith("422 ");
 
 export async function importCsv(form: FormData) {
-  const id = String(form.get("brand_id"));
+  const id = formSeg(form, "brand_id");
   const file = form.get("csv");
   if (!(file instanceof File) || file.size === 0) return back(id, "nofile");
   let r: ImportResult;
@@ -31,7 +31,7 @@
 }
 
 export async function importFeed(form: FormData) {
-  const id = String(form.get("brand_id"));
+  const id = formSeg(form, "brand_id");
   const url = String(form.get("url") ?? "").trim();
   const job = await api<Queued>(`/brands/${seg(id)}/products/import/feed`, {
     method: "POST",
@@ -42,7 +42,7 @@
 }
 
 export async function runProducts(form: FormData) {
-  const id = String(form.get("brand_id"));
+  const id = formSeg(form, "brand_id");
   let job: Queued;
   try {
     job = await api<Queued>(`/brands/${seg(id)}/products/run`, { method: "POST" });
@@ -54,7 +54,7 @@
 }
 
 export async function clearProducts(form: FormData) {
-  const id = String(form.get("brand_id"));
+  const id = formSeg(form, "brand_id");
   await api(`/brands/${seg(id)}/products`, { method: "DELETE" });
   back(id, "cleared");
 }
--- a/apps/web/src/app/(app)/b/[id]/recommendations/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/recommendations/actions.ts
@@ -1,10 +1,10 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api, seg } from "@/lib/api";
+import { api, formSeg, seg } from "@/lib/api";
 
-const brand = (form: FormData) => String(form.get("brand_id"));
-const rec = (form: FormData) => String(form.get("rec_id"));
+const brand = (form: FormData) => formSeg(form, "brand_id");
+const rec = (form: FormData) => formSeg(form, "rec_id");
 
 export async function generate(form: FormData) {
   await api(`/brands/${seg(brand(form))}/recommendations/generate`, {
--- a/apps/web/src/app/(app)/b/[id]/reports/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/reports/actions.ts
@@ -1,14 +1,14 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api, seg } from "@/lib/api";
+import { api, formSeg, seg } from "@/lib/api";
 
 const back = (id: string, status: string) =>
   redirect(`/b/${id}/reports?queued=${status}`);
 
 export async function setCadence(form: FormData) {
-  const id = String(form.get("brand_id"));
-  const type = String(form.get("type"));
+  const id = formSeg(form, "brand_id");
+  const type = formSeg(form, "type");
   await api(`/brands/${seg(id)}/reports/${seg(type)}`, {
     method: "PUT",
     headers: { "Content-Type": "application/json" },
@@ -18,15 +18,15 @@
 }
 
 export async function generateNow(form: FormData) {
-  const id = String(form.get("brand_id"));
-  const type = String(form.get("type"));
+  const id = formSeg(form, "brand_id");
+  const type = formSeg(form, "type");
   await api(`/brands/${seg(id)}/reports/${seg(type)}/runs`, { method: "POST" });
   back(id, "generated");
 }
 
 export async function share(form: FormData) {
-  const id = String(form.get("brand_id"));
-  const run = String(form.get("run_id"));
+  const id = formSeg(form, "brand_id");
+  const run = formSeg(form, "run_id");
   await api(`/brands/${seg(id)}/reports/runs/${seg(run)}/share`, {
     method: "POST",
   });
@@ -34,8 +34,8 @@
 }
 
 export async function revoke(form: FormData) {
-  const id = String(form.get("brand_id"));
-  const run = String(form.get("run_id"));
+  const id = formSeg(form, "brand_id");
+  const run = formSeg(form, "run_id");
   await api(`/brands/${seg(id)}/reports/runs/${seg(run)}/share`, {
     method: "DELETE",
   });
@@ -43,7 +43,7 @@
 }
 
 export async function setBranding(form: FormData) {
-  const id = String(form.get("brand_id"));
+  const id = formSeg(form, "brand_id");
   const field = (k: string) => {
     const v = String(form.get(k) ?? "").trim();
     return v === "" ? null : v;
--- a/apps/web/src/app/(app)/b/[id]/serp/actions.test.ts
+++ b/apps/web/src/app/(app)/b/[id]/serp/actions.test.ts
@@ -4,9 +4,14 @@
 const cookieStore = { get: vi.fn() };
 vi.mock("next/headers", () => ({ cookies: vi.fn(async () => cookieStore) }));
 const redirect = vi.fn();
-vi.mock("next/navigation", () => ({ notFound: vi.fn(), redirect }));
+vi.mock("next/navigation", () => ({
+  notFound: () => {
+    throw new Error("NOT_FOUND");
+  },
+  redirect,
+}));
 
-const { addDomain } = await import("./actions");
+const { addDomain, runSerpAudit } = await import("./actions");
 
 const ID = "1eb6c00a-4b18-4512-b515-dd1d8039511f";
 const form = (host: string) => {
@@ -58,12 +63,24 @@
   vi.spyOn(console, "error").mockImplementation(() => {});
   vi.stubGlobal(
     "fetch",
-    vi.fn(async () => new Response("{}", { status: 409 })),
+    vi.fn(async () =>
+      Response.json({ title: "Domain already exists" }, { status: 409 }),
+    ),
   );
   await addDomain(form("walkaroo.in"));
   expect(redirect).toHaveBeenCalledWith(`/b/${ID}/serp?domain=exists`);
 });
 
+test("addDomain rethrows a 409 with any other title", async () => {
+  vi.spyOn(console, "error").mockImplementation(() => {});
+  vi.stubGlobal(
+    "fetch",
+    vi.fn(async () => new Response("{}", { status: 409 })),
+  );
+  await expect(addDomain(form("walkaroo.in"))).rejects.toThrow(/^409/);
+  expect(redirect).not.toHaveBeenCalled();
+});
+
 test("addDomain does not redirect when the API fails", async () => {
   vi.spyOn(console, "error").mockImplementation(() => {});
   vi.stubGlobal(
@@ -73,3 +90,30 @@
   await expect(addDomain(form("walkaroo.in"))).rejects.toThrow(/^500/);
   expect(redirect).not.toHaveBeenCalled();
 });
+
+test("addDomain shows a note when the brand is archived", async () => {
+  vi.stubGlobal(
+    "fetch",
+    vi.fn(async () =>
+      Response.json({ title: "Brand is archived" }, { status: 409 }),
+    ),
+  );
+  vi.spyOn(console, "error").mockImplementation(() => {});
+  await addDomain(form("walkaroo.in"));
+  expect(redirect).toHaveBeenCalledWith(`/b/${ID}/serp?domain=archived`);
+});
+
+test.each([
+  ["addDomain", addDomain],
+  ["runSerpAudit", runSerpAudit],
+])("%s refuses a form with no brand_id without calling the API", async (_, action) => {
+  const fetchMock = vi.fn();
+  vi.stubGlobal("fetch", fetchMock);
+  const log = vi.spyOn(console, "error").mockImplementation(() => {});
+  const f = new FormData();
+  f.set("host", "walkaroo.in");
+  await expect(action(f)).rejects.toThrow("NOT_FOUND");
+  expect(fetchMock).not.toHaveBeenCalled();
+  expect(redirect).not.toHaveBeenCalled();
+  expect(log).toHaveBeenCalledWith("API form value missing", '"brand_id"');
+});
--- a/apps/web/src/app/(app)/b/[id]/serp/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/serp/actions.ts
@@ -1,11 +1,11 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api, seg } from "@/lib/api";
+import { api, formSeg, seg } from "@/lib/api";
 import type { Queued } from "@/lib/types";
 
 export async function runSerpAudit(form: FormData) {
-  const id = String(form.get("brand_id"));
+  const id = formSeg(form, "brand_id");
   const job = await api<Queued>(`/brands/${seg(id)}/audits/serp`, {
     method: "POST",
   });
@@ -14,10 +14,11 @@
 }
 
 export async function addDomain(form: FormData) {
-  const id = String(form.get("brand_id"));
+  const id = formSeg(form, "brand_id");
   const host = String(form.get("host") ?? "").trim();
-  // api() throws `${status} ${title}…`; a 422 (host refused) or 409
-  // (already declared) becomes a note on the page, not the error page.
+  // api() throws `${status} ${title}…`; a 422 (host refused) or a 409
+  // (already declared, or the brand archived) becomes a note on the page,
+  // not the error page.
   let code = "";
   try {
     await api(`/brands/${seg(id)}/domains`, {
@@ -28,7 +29,8 @@
   } catch (e) {
     const msg = e instanceof Error ? e.message : "";
     if (msg.startsWith("422 ")) code = "refused";
-    else if (msg.startsWith("409 ")) code = "exists";
+    else if (msg.startsWith("409 Domain already exists")) code = "exists";
+    else if (msg.startsWith("409 Brand is archived")) code = "archived";
     else throw e;
   }
   redirect(`/b/${id}/serp${code ? `?domain=${code}` : ""}`);
--- a/apps/web/src/app/(app)/b/[id]/serp/page.test.tsx
+++ b/apps/web/src/app/(app)/b/[id]/serp/page.test.tsx
@@ -35,12 +35,14 @@
 const serp = (
   budget_room: boolean,
   job: SerpAudits["job"] = null,
+  serp_due = true,
 ): SerpAudits => ({
   job,
   audits: [],
   serp_configured: true,
   failed_7d: 0,
   budget_room,
+  serp_due,
 });
 
 afterEach(() => {
@@ -115,7 +117,8 @@
 
 test("a queued audit hides the budget note", async () => {
   const { html } = await render({
-    serp: serp(false, { status: "queued", error: null }),
+    // The brand's own queued audit makes it not due (due_serp_audits()).
+    serp: serp(false, { status: "queued", error: null }, false),
     brand: brand("active"),
     domains: [DOMAIN],
   });
--- a/apps/web/src/app/(app)/b/[id]/serp/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/serp/page.tsx
@@ -23,7 +23,7 @@
   const { id } = await params;
   const sp = await searchParams;
   const [
-    { job, audits, serp_configured, failed_7d, budget_room },
+    { job, audits, serp_configured, failed_7d, budget_room, serp_due },
     brand,
     domains,
   ] =
@@ -49,7 +49,7 @@
           serp_configured,
           failed_7d,
           budget_room,
-          job?.status,
+          serp_due,
         )}
       </p>
       {domainNote(sp.domain) && (
--- a/apps/web/src/app/(app)/b/[id]/site/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/site/actions.ts
@@ -1,11 +1,11 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api, seg } from "@/lib/api";
+import { api, formSeg, seg } from "@/lib/api";
 import type { Queued } from "@/lib/types";
 
 export async function runAudit(form: FormData) {
-  const id = String(form.get("brand_id"));
+  const id = formSeg(form, "brand_id");
   const job = await api<Queued>(`/brands/${seg(id)}/audits/crawl`, {
     method: "POST",
   });
--- a/apps/web/src/app/(app)/b/[id]/tasks/actions.ts
+++ b/apps/web/src/app/(app)/b/[id]/tasks/actions.ts
@@ -1,10 +1,10 @@
 "use server";
 
 import { redirect } from "next/navigation";
-import { api, seg } from "@/lib/api";
+import { api, formSeg, seg } from "@/lib/api";
 
 export async function updateTask(form: FormData) {
-  const id = String(form.get("brand_id"));
+  const id = formSeg(form, "brand_id");
   const body: Record<string, unknown> = {
     owner: String(form.get("owner") ?? "") || null,
     due_date: String(form.get("due_date") ?? "") || null,
@@ -12,7 +12,7 @@
   };
   const status = form.get("status");
   if (status) body.status = String(status);
-  await api(`/brands/${seg(id)}/tasks/${seg(String(form.get("task_id")))}`, {
+  await api(`/brands/${seg(id)}/tasks/${seg(formSeg(form, "task_id"))}`, {
     method: "PATCH",
     headers: { "Content-Type": "application/json" },
     body: JSON.stringify(body),
--- a/apps/web/src/lib/api-paths.test.ts
+++ b/apps/web/src/lib/api-paths.test.ts
@@ -48,3 +48,18 @@
   expect(templates).toBeGreaterThanOrEqual(40);
   expect(bad).toEqual([]);
 });
+
+test("server actions read path values with formSeg()", () => {
+  // String(form.get(...)) turns a missing field into "null", which seg()
+  // passes; formSeg() refuses it.
+  const RAW = /String\(form\.get\("(?:[a-z_]*_id|type)"\)\)|seg\(String\(/g;
+  const files = readdirSync(APP, { recursive: true, encoding: "utf8" }).filter(
+    (f) => /\.tsx?$/.test(f) && !/\.test\.tsx?$/.test(f),
+  );
+  const bad = files.flatMap((f) =>
+    [...readFileSync(join(APP, f), "utf8").matchAll(RAW)].map(
+      (m) => `${f}: ${m[0]}`,
+    ),
+  );
+  expect(bad).toEqual([]);
+});
--- a/apps/web/src/lib/api.test.ts
+++ b/apps/web/src/lib/api.test.ts
@@ -9,7 +9,7 @@
   redirect: vi.fn(),
 }));
 
-const { api, publicApi, seg } = await import("./api");
+const { api, formSeg, publicApi, seg } = await import("./api");
 const { cookies } = await import("next/headers");
 
 const stub = (status: number) =>
@@ -141,3 +141,27 @@
   expect(logged.startsWith('"a\\n')).toBe(true);
   expect(logged).not.toContain("\n");
 });
+
+test("formSeg returns a form field that seg() accepts", () => {
+  const f = new FormData();
+  f.set("brand_id", "1eb6c00a-4b18-4512-b515-dd1d8039511f");
+  expect(formSeg(f, "brand_id")).toBe("1eb6c00a-4b18-4512-b515-dd1d8039511f");
+});
+
+test("formSeg refuses a missing field instead of sending \"null\"", () => {
+  const log = vi.spyOn(console, "error").mockImplementation(() => {});
+  expect(() => formSeg(new FormData(), "brand_id")).toThrow("NOT_FOUND");
+  expect(log).toHaveBeenCalledTimes(1);
+  expect(log).toHaveBeenCalledWith("API form value missing", '"brand_id"');
+});
+
+test("formSeg refuses a file field and a value seg() refuses", () => {
+  const log = vi.spyOn(console, "error").mockImplementation(() => {});
+  const f = new FormData();
+  f.set("csv", new Blob(["x"]));
+  f.set("brand_id", "a/b");
+  expect(() => formSeg(f, "csv")).toThrow("NOT_FOUND");
+  expect(() => formSeg(f, "brand_id")).toThrow("NOT_FOUND");
+  expect(log).toHaveBeenCalledWith("API form value missing", '"csv"');
+  expect(log).toHaveBeenCalledWith("API path value refused", '"a/b"', 3);
+});
--- a/apps/web/src/lib/api.ts
+++ b/apps/web/src/lib/api.ts
@@ -21,6 +21,16 @@
   notFound();
 }
 
+/** A path segment from a server action's form field. A missing or
+ * non-text field is refused (String(null) would send "null"), and the
+ * value then goes through seg(). */
+export function formSeg(form: FormData, name: string): string {
+  const value = form.get(name);
+  if (typeof value === "string") return seg(value);
+  console.error("API form value missing", shown(name));
+  notFound();
+}
+
 /** One path segment from a route param, form field or API value. */
 export function seg(value: string): string {
   if (/^[A-Za-z0-9_-]+$/.test(value)) return value;
--- a/apps/web/src/lib/format.test.ts
+++ b/apps/web/src/lib/format.test.ts
@@ -100,6 +100,7 @@
   expect(domainNote("exists")).toBe(
     "Not added: that domain is already declared for this brand.",
   );
+  expect(domainNote("archived")).toBe("Not added: the brand is archived.");
   expect(domainNote(undefined)).toBeNull();
   expect(domainNote("constructor")).toBeNull();
 });
@@ -283,29 +284,30 @@
     `Not audited automatically: ${n} audits failed in the last 7 days; the sweep tries again once fewer than 3 remain in that window.`;
   const noBudget =
     "Audited automatically once a week; today the daily budget has no room for a Brand SERP audit, so a due audit waits until there is room. The budget resets at midnight UTC.";
-  expect(serpSchedule("active", 1, true, 1, true)).toBe(weekly);
-  expect(serpSchedule("active", 1, true, 2, true)).toBe(weekly);
-  expect(serpSchedule("active", 1, true, 3, true)).toBe(failed(3));
-  expect(serpSchedule("active", 1, true, 5, true)).toBe(failed(5));
-  expect(serpSchedule("active", 1, false, 0, true)).toBe(unconfigured);
-  // Not configured outranks the failure pause.
-  expect(serpSchedule("active", 1, false, 3, true)).toBe(unconfigured);
-  expect(serpSchedule("active", 0, false, 3, true)).toBe(noDomain);
-  expect(serpSchedule("archived", 1, false, 3, true)).toBe(archived);
-  expect(serpSchedule("archived", 0, true, 0, true)).toBe(archived);
-  expect(serpSchedule("active", 1, true, 2, false)).toBe(noBudget);
-  // A job row with a NULL status is neither queued nor running.
-  expect(serpSchedule("active", 1, true, 0, false, null)).toBe(noBudget);
-  expect(serpSchedule("active", 1, true, 0, false, "done")).toBe(noBudget);
-  expect(serpSchedule("active", 1, true, 0, false, "failed")).toBe(noBudget);
-  // The brand's own waiting job counts against the budget: no note.
-  expect(serpSchedule("active", 1, true, 0, false, "queued")).toBe(weekly);
-  expect(serpSchedule("active", 1, true, 0, false, "running")).toBe(weekly);
+  const inactive = "Not audited automatically: the brand is not active.";
+  expect(serpSchedule("active", 1, true, 1, true, true)).toBe(weekly);
+  expect(serpSchedule("active", 1, true, 2, true, true)).toBe(weekly);
+  expect(serpSchedule("active", 1, true, 3, true, false)).toBe(failed(3));
+  expect(serpSchedule("active", 1, true, 5, true, false)).toBe(failed(5));
+  expect(serpSchedule("active", 1, false, 0, true, true)).toBe(unconfigured);
+  // Not configured outranks the failure pause.
+  expect(serpSchedule("active", 1, false, 3, true, false)).toBe(unconfigured);
+  expect(serpSchedule("active", 0, false, 3, true, false)).toBe(noDomain);
+  expect(serpSchedule("archived", 1, false, 3, true, false)).toBe(archived);
+  expect(serpSchedule("archived", 0, true, 0, true, false)).toBe(archived);
+  // A status other than active or archived is not called archived.
+  expect(serpSchedule("paused", 1, true, 0, true, false)).toBe(inactive);
+  expect(serpSchedule("", 1, true, 0, false, false)).toBe(inactive);
+  // The budget note needs a due brand and no room.
+  expect(serpSchedule("active", 1, true, 2, false, true)).toBe(noBudget);
+  expect(serpSchedule("active", 1, true, 0, false, false)).toBe(weekly);
+  expect(serpSchedule("active", 1, true, 0, true, true)).toBe(weekly);
   // Every other reason outranks the budget.
-  expect(serpSchedule("active", 1, true, 3, false)).toBe(failed(3));
-  expect(serpSchedule("active", 1, false, 0, false)).toBe(unconfigured);
-  expect(serpSchedule("active", 0, true, 0, false)).toBe(noDomain);
-  expect(serpSchedule("archived", 1, true, 0, false)).toBe(archived);
+  expect(serpSchedule("active", 1, true, 3, false, true)).toBe(failed(3));
+  expect(serpSchedule("active", 1, false, 0, false, true)).toBe(unconfigured);
+  expect(serpSchedule("active", 0, true, 0, false, true)).toBe(noDomain);
+  expect(serpSchedule("archived", 1, true, 0, false, true)).toBe(archived);
+  expect(serpSchedule("paused", 1, true, 0, false, true)).toBe(inactive);
 });
 
 test("ownershipText gives the count and a whole percentage", () => {
--- a/apps/web/src/lib/format.ts
+++ b/apps/web/src/lib/format.ts
@@ -110,6 +110,7 @@
   refused:
     "Not added: enter a public domain name such as example.com, not an IP address.",
   exists: "Not added: that domain is already declared for this brand.",
+  archived: "Not added: the brand is archived.",
 };
 
 const LABEL_QUEUED = "Queued; the worker labels them within a minute.";
@@ -206,10 +207,8 @@
  * stops after SERP_MAX_FAILURES failed jobs in 7 days; the sweep itself
  * queues nothing without DataForSEO credentials, and skips a due brand
  * while the org's budget has no room for the audit (serp_budget_fits).
- * budgetRoom is computed whether or not the brand is due, so the budget
- * note never says the brand is skipped, and is left out while the
- * brand's own audit is queued or running (due_serp_audits() then
- * excludes the brand, so the sweep checks no budget for it).
+ * due is the API's serp_due, the sweep's own predicates for this brand,
+ * so the budget note shows only for a brand the sweep would queue now.
  */
 export const serpSchedule = (
   status: string,
@@ -217,19 +216,21 @@
   configured: boolean,
   failed7d: number,
   budgetRoom: boolean,
-  jobStatus?: string | null,
+  due: boolean,
 ) =>
-  status !== "active"
+  status === "archived"
     ? "Not audited automatically: the brand is archived."
-    : domains === 0
-      ? "Not audited automatically: the brand has no declared domain."
-      : !configured
-        ? "Not audited automatically: the SERP provider is not configured."
-        : failed7d >= SERP_MAX_FAILURES
-          ? `Not audited automatically: ${failed7d} audits failed in the last 7 days; the sweep tries again once fewer than ${SERP_MAX_FAILURES} remain in that window.`
-          : !budgetRoom && jobStatus !== "queued" && jobStatus !== "running"
-            ? "Audited automatically once a week; today the daily budget has no room for a Brand SERP audit, so a due audit waits until there is room. The budget resets at midnight UTC."
-            : "Audited automatically once a week.";
+    : status !== "active"
+      ? "Not audited automatically: the brand is not active."
+      : domains === 0
+        ? "Not audited automatically: the brand has no declared domain."
+        : !configured
+          ? "Not audited automatically: the SERP provider is not configured."
+          : failed7d >= SERP_MAX_FAILURES
+            ? `Not audited automatically: ${failed7d} audits failed in the last 7 days; the sweep tries again once fewer than ${SERP_MAX_FAILURES} remain in that window.`
+            : due && !budgetRoom
+              ? "Audited automatically once a week; today the daily budget has no room for a Brand SERP audit, so a due audit waits until there is room. The budget resets at midnight UTC."
+              : "Audited automatically once a week.";
 
 /** "3 of 10 (30%)"; no percentage when the page has no organic results. */
 export const ownershipText = (owned: number, organic: number) =>
--- a/packages/core/bsi_core/scheduling.py
+++ b/packages/core/bsi_core/scheduling.py
@@ -22,6 +22,11 @@
 # A SERP audit is 2 calls at the observed $0.002 (2026-10-05), 4,000
 # micros; 40,000 is kept as a 10x margin, which fails closed.
 SERP_JOB_MICROS = 40_000
+# due_serp_audits()'s constants (migration 0024), which serp_due mirrors.
+SERP_AUDIT_DAYS = 7
+SERP_RETRY_DAYS = 1
+SERP_KINDS = 2
+SERP_MAX_FAILURES = 3
 
 
 def first_run(now: datetime, hour_utc: int) -> datetime:
@@ -110,26 +115,34 @@
 
 
 def budget_fits(
-    s: Session, org_id: uuid.UUID, n_obs: int, extra_micros: int = 0
+    s: Session,
+    org_id: uuid.UUID,
+    n_obs: int,
+    extra_micros: int = 0,
+    *,
+    lock: bool = True,
 ) -> bool:
     """True if n_obs more observations fit in the org's budget for today.
 
     extra_micros is spend about to be made outside the observations, such
     as a suggestion job's estimate.
 
-    Call inside the org's tenant transaction. The advisory lock is held to
-    the end of that transaction, so two schedules of one org can't both
-    pass on the same headroom.
+    Call inside the org's tenant transaction. With lock (the default) the
+    org's advisory lock is held to the end of that transaction, so two
+    schedules of one org can't both pass on the same headroom. A caller
+    that writes nothing passes lock=False and never waits; its answer can
+    differ from a writer's only while that writer holds the lock.
     """
     # Fail closed: outside the org's tenant session row-level security
     # hides every row, the sums would be zero and anything would fit.
     tenant = s.scalar(text("SELECT current_setting('app.org_id', true)"))
     if tenant != str(org_id):
         raise RuntimeError("budget_fits must run in the org's tenant session")
-    s.execute(
-        text("SELECT pg_advisory_xact_lock(hashtext(:org))"),
-        {"org": str(org_id)},
-    )
+    if lock:
+        s.execute(
+            text("SELECT pg_advisory_xact_lock(hashtext(:org))"),
+            {"org": str(org_id)},
+        )
     # Row-level security scopes this to the org (unlike spend.db_micros).
     spent, pending = spent_and_pending(s, org_id)
     settings = get_settings()
@@ -140,14 +153,16 @@
     return bool(spent + extra_micros + (pending + n_obs) * estimate <= cap)
 
 
-def serp_budget_fits(s: Session, org_id: uuid.UUID) -> bool:
+def serp_budget_fits(
+    s: Session, org_id: uuid.UUID, *, lock: bool = True
+) -> bool:
     """True if one more audit_serp job fits in the org's budget for today,
     counting one estimate for each of the org's audit_serp jobs still
     queued or running (those have recorded no cost yet).
 
-    The weekly sweep's check, and the Brand SERP page's budget note. Like
-    budget_fits, which it calls, it takes the org's advisory lock to the end
-    of the transaction.
+    The weekly sweep's check (with the org's advisory lock, as budget_fits
+    takes it) and the Brand SERP page's budget note (lock=False: the page
+    writes nothing).
     """
     # Row-level security scopes the count to the org; budget_fits fails
     # closed outside the org's tenant session.
@@ -158,9 +173,61 @@
         )
     )
     extra = SERP_JOB_MICROS * ((waiting or 0) + 1)
-    return budget_fits(s, org_id, 0, extra_micros=extra)
+    return budget_fits(s, org_id, 0, extra_micros=extra, lock=lock)
 
 
+def serp_due(s: Session, brand_id: uuid.UUID) -> bool:
+    """True if the weekly sweep would queue a Brand SERP audit for the brand
+    now: due_serp_audits()'s predicates (migration 0024) for one brand, on
+    the DB clock. The brand is active and has a domain; fewer than
+    SERP_KINDS kinds have an error-free page fetched in SERP_AUDIT_DAYS; no
+    audit_serp job was created in SERP_RETRY_DAYS or is queued or running;
+    fewer than SERP_MAX_FAILURES failed in SERP_AUDIT_DAYS.
+
+    Run in the org's tenant session: row-level security hides another
+    org's brand, which then reads as not due. The sweep itself still calls
+    due_serp_audits(); tests compare the two.
+    """
+    week = func.now() - timedelta(days=SERP_AUDIT_DAYS)
+    day = func.now() - timedelta(days=SERP_RETRY_DAYS)
+    jobs = (m.Job.brand_id == brand_id, m.Job.kind == "audit_serp")
+    kinds = (
+        select(func.count(func.distinct(m.SerpAudit.kind)))
+        .where(
+            m.SerpAudit.brand_id == brand_id,
+            m.SerpAudit.error.is_(None),
+            m.SerpAudit.fetched_at > week,
+        )
+        .scalar_subquery()
+    )
+    recent = (
+        select(m.Job.id)
+        .where(
+            *jobs,
+            (m.Job.created_at > day) | m.Job.status.in_(("queued", "running")),
+        )
+        .exists()
+    )
+    failed = (
+        select(func.count())
+        .select_from(m.Job)
+        .where(*jobs, m.Job.status == "failed", m.Job.created_at > week)
+        .scalar_subquery()
+    )
+    domain = select(m.Domain.id).where(m.Domain.brand_id == brand_id).exists()
+    due = s.scalar(
+        select(m.Brand.id).where(
+            m.Brand.id == brand_id,
+            m.Brand.status == "active",
+            domain,
+            kinds < SERP_KINDS,
+            ~recent,
+            failed < SERP_MAX_FAILURES,
+        )
+    )
+    return due is not None
+
+
 def check_active_limit(
     s: Session, org_id: uuid.UUID, adding: int
 ) -> tuple[int, int] | None:
--- a/tests/integration/test_api_crud.py
+++ b/tests/integration/test_api_crud.py
@@ -1,6 +1,13 @@
+import threading
+import uuid
+
 import pytest
+from bsi_core import models as m
+from sqlalchemy import func, select, update
 
+from tests.integration.test_api_recommendations import _wait_until_blocked
 
+
 def test_health_needs_no_key(client):
     assert client.get("/healthz").json() == {"status": "ok"}
 
@@ -190,3 +197,75 @@
     )
     assert r.status_code == 200
     assert r.json()["category"] is None
+
+
+def test_an_archived_brand_accepts_no_new_domain(
+    client, owner, make_org, make_brand
+):
+    org = make_org()
+    bid = make_brand(org)
+    with owner() as s, s.begin():
+        s.execute(
+            update(m.Brand).where(m.Brand.id == bid).values(status="archived")
+        )
+    base = f"/v1/brands/{bid}/domains"
+    r = client.post(base, headers=org.headers, json={"host": "acme.com"})
+    assert r.status_code == 409, r.text
+    assert r.json()["title"] == "Brand is archived"
+    assert client.get(base, headers=org.headers).json() == []
+
+
+def test_a_host_is_capped_at_200_characters(client, make_org, make_brand):
+    org = make_org()
+    base = f"/v1/brands/{make_brand(org)}/domains"
+    at_cap = "a" * 196 + ".com"
+    r = client.post(base, headers=org.headers, json={"host": at_cap})
+    assert r.status_code == 201, r.text
+    r = client.post(base, headers=org.headers, json={"host": "a" + at_cap})
+    assert r.status_code == 422, r.text
+    assert r.json()["errors"][0]["loc"][-1] == "host"
+
+
+def test_a_simultaneous_duplicate_domain_is_409_not_500(
+    client, owner, make_org, make_brand
+):
+    """A first submit that has inserted the host and not yet committed: the
+    second must wait on the unique index, then see the row and get 409,
+    never a raw unique violation as a 500 (and never two rows)."""
+    org = make_org()
+    bid = make_brand(org)
+    holder = owner()
+    holder.begin()
+    holder.add(m.Domain(org_id=org.id, brand_id=bid, host="acme.com"))
+    holder.flush()
+    result: dict[str, object] = {}
+
+    def post() -> None:
+        result["response"] = client.post(
+            f"/v1/brands/{bid}/domains",
+            headers=org.headers,
+            json={"host": "acme.com"},
+        )
+
+    t = threading.Thread(target=post)
+    t.start()
+    try:
+        assert _wait_until_blocked(holder), (
+            "the POST never waited on the uncommitted row; the test would "
+            "pass whether or not the insert handles the conflict"
+        )
+        holder.commit()
+        t.join(timeout=5)
+        assert not t.is_alive()
+    finally:
+        holder.close()
+    response = result["response"]
+    assert response.status_code == 409, response.text
+    assert response.json()["title"] == "Domain already exists"
+    with owner() as s:
+        rows = s.scalar(
+            select(func.count())
+            .select_from(m.Domain)
+            .where(m.Domain.brand_id == uuid.UUID(str(bid)))
+        )
+    assert rows == 1
--- a/tests/integration/test_api_recommendations.py
+++ b/tests/integration/test_api_recommendations.py
@@ -195,10 +195,15 @@
     (wait_event='transactionid'); the query text it shows alongside a
     blocked backend is not reliable (it can lag behind the statement
     actually stuck), so filter on the wait state, not the query text.
+
+    Postgres caches the activity statistics for the rest of a transaction,
+    so each poll clears that snapshot first; otherwise a request that
+    connects after the first poll is never seen.
     """
     my_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar()
     end = time.monotonic() + deadline
     while time.monotonic() < end:
+        holder.execute(text("SELECT pg_stat_clear_snapshot()"))
         waiting = holder.execute(
             text(
                 "SELECT count(*) FROM pg_stat_activity "
--- a/tests/integration/test_api_serp.py
+++ b/tests/integration/test_api_serp.py
@@ -1,10 +1,13 @@
+import threading
 from datetime import UTC, datetime, timedelta
 from decimal import Decimal
 
+import pytest
 from bsi_api.routers import audits
 from bsi_core import models as m
 from bsi_core.config import Settings
-from sqlalchemy import update
+from bsi_core.db import system_session
+from sqlalchemy import text, update
 
 from tests.integration.test_worker import _job
 
@@ -109,6 +112,7 @@
         "serp_configured": True,
         "failed_7d": 0,
         "budget_room": True,
+        "serp_due": False,  # no declared domain
     }
 
 
@@ -262,3 +266,98 @@
     r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
     assert r.status_code == 200, r.text
     assert r.json()["failed_7d"] == 1
+
+
+def _due_in_sql(bid):
+    """Whether due_serp_audits() (the sweep's own query) returns the brand."""
+    with system_session() as s:
+        due = s.execute(text("SELECT brand_id FROM due_serp_audits()"))
+        return bid in {row[0] for row in due}
+
+
+def _arrange(owner, org, bid, case):
+    if case != "no domain":
+        with owner() as s, s.begin():
+            s.add(m.Domain(org_id=org.id, brand_id=bid, host="walkaroo.in"))
+    if case == "archived":
+        with owner() as s, s.begin():
+            s.execute(
+                update(m.Brand)
+                .where(m.Brand.id == bid)
+                .values(status="archived")
+            )
+    if case in ("one kind this week", "both kinds this week"):
+        _audit(owner, org, bid, "brand", 60)
+    if case == "both kinds this week":
+        _audit(owner, org, bid, "reviews", 60)
+    if case == "a job today":
+        _job(owner, org, bid, "audit_serp", "done")
+    if case == "a queued job":
+        _aged(
+            owner,
+            _job(owner, org, bid, "audit_serp", "queued"),
+            timedelta(days=2),
+        )
+    if case in ("two failures", "three failures"):
+        n = 3 if case == "three failures" else 2
+        for i in range(n):
+            job = _job(owner, org, bid, "audit_serp", "failed", minutes=-i)
+            _aged(owner, job, timedelta(days=2))
+
+
+@pytest.mark.parametrize(
+    ("case", "expected"),
+    [
+        ("nothing recent", True),
+        ("archived", False),
+        ("no domain", False),
+        ("one kind this week", True),
+        ("both kinds this week", False),
+        ("a job today", False),
+        ("a queued job", False),
+        ("two failures", True),
+        ("three failures", False),
+    ],
+)
+def test_serp_due_agrees_with_due_serp_audits(
+    client, owner, make_org, make_brand, monkeypatch, case, expected
+):
+    _configured(monkeypatch)
+    org = make_org()
+    bid = make_brand(org)
+    _arrange(owner, org, bid, case)
+    r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
+    assert r.status_code == 200, r.text
+    assert r.json()["serp_due"] is expected
+    assert _due_in_sql(bid) is expected
+
+
+def test_the_page_does_not_wait_on_the_orgs_budget_lock(
+    client, owner, make_org, make_brand, monkeypatch
+):
+    _configured(monkeypatch)
+    org = make_org()
+    bid = make_brand(org)
+    holder = owner()
+    holder.begin()
+    holder.execute(
+        text("SELECT pg_advisory_xact_lock(hashtext(:org))"),
+        {"org": str(org.id)},
+    )
+    result: dict[str, object] = {}
+
+    def get() -> None:
+        result["response"] = client.get(
+            f"/v1/brands/{bid}/audits/serp", headers=org.headers
+        )
+
+    t = threading.Thread(target=get)
+    t.start()
+    t.join(timeout=5)
+    try:
+        assert not t.is_alive(), "the GET waited on the org's advisory lock"
+    finally:
+        holder.rollback()
+        holder.close()
+        t.join()
+    assert result["response"].status_code == 200
--- a/tests/integration/test_budget.py
+++ b/tests/integration/test_budget.py
@@ -1,3 +1,4 @@
+import threading
 from datetime import UTC, datetime, timedelta
 from decimal import Decimal
 from types import SimpleNamespace
@@ -6,9 +7,11 @@
 from bsi_core import models as m
 from bsi_core import scheduling
 from bsi_core.db import system_session, tenant_session
-from sqlalchemy import func, update
+from sqlalchemy import func, text, update
 
+from tests.integration.test_api_recommendations import _wait_until_blocked
 
+
 @pytest.fixture(autouse=True)
 def budget(monkeypatch):
     # $0.20 cap, 50,000 micros per observation: 4 observations fit.
@@ -195,3 +198,43 @@
     org = make_org()
     assert fits(org, 3, extra_micros=50_000)
     assert not fits(org, 3, extra_micros=50_001)
+
+
+def test_lock_false_gives_the_same_verdict_and_still_fails_closed(make_org):
+    a, b = make_org("A"), make_org("B")
+    for n, expected in ((4, True), (5, False)):
+        with tenant_session(a.id) as s:
+            assert scheduling.budget_fits(s, a.id, n, lock=False) is expected
+        assert fits(a, n) is expected
+    with system_session() as s, pytest.raises(RuntimeError, match="tenant"):
+        scheduling.budget_fits(s, a.id, 1, lock=False)
+    with tenant_session(a.id) as s, pytest.raises(RuntimeError, match="tenant"):
+        scheduling.budget_fits(s, b.id, 1, lock=False)
+
+
+def test_the_default_check_waits_for_the_orgs_lock(owner, make_org):
+    """Writers keep serializing: budget_fits takes the org's advisory lock
+    unless told not to, so it waits while another transaction holds it."""
+    org = make_org()
+    holder = owner()
+    holder.begin()
+    holder.execute(
+        text("SELECT pg_advisory_xact_lock(hashtext(:org))"),
+        {"org": str(org.id)},
+    )
+    done = threading.Event()
+
+    def check() -> None:
+        fits(org, 1)
+        done.set()
+
+    t = threading.Thread(target=check)
+    t.start()
+    try:
+        assert _wait_until_blocked(holder), "budget_fits did not wait"
+        assert not done.is_set()
+    finally:
+        holder.rollback()
+        holder.close()
+    t.join(timeout=5)
+    assert done.is_set()
```

## Evidence

Proof directory: a fresh scratchpad copy of main d7e97d3 (`proof59-1791531885`), written only by the controller.

- Red, main's code with the new tests: backend 15 failed, 36 passed in the three changed test files (the race test fails with `500 Internal error`); web 10 failed, 78 passed.
- Green, patched: `ruff format --check` (184 files), `ruff check`, `mypy` (31 source files) clean; the full backend suite 1792 passed, 2 deselected, metrics coverage 100.00%; vitest 88 passed; typecheck and eslint clean; the build compiled. `gen:check` runs at execution.
- While proving the race test, the red run first showed the POST stuck yet unseen by `_wait_until_blocked`: Postgres caches activity statistics for a transaction, so a poll that starts before the request connects never sees it. That is R2.
- A process slip during the proof: one of the controller's scripts wrote an empty file at /tmp/x; it was removed at once.

Mutations, each applied alone to the patched copy and reverted (backend: test_api_crud.py, test_api_serp.py and test_budget.py; web: the whole vitest run):

| # | Mutation | Result |
|---|---|---|
| M1 | no archived check | killed: test_an_archived_brand_accepts_no_new_domain (1 failed, 50 passed, 2 warnings) |
| M2 | no ON CONFLICT | killed: test_a_simultaneous_duplicate_domain_is_409_not_500; test_competitors_and_domains (2 failed, 49 passed, 2 warnings) |
| M3 | no host cap | killed: test_a_host_is_capped_at_200_characters (1 failed, 50 passed, 2 warnings) |
| M4 | serp_due ignores status | killed: test_serp_due_agrees_with_due_serp_audits[archived-False] (1 failed, 50 passed, 2 warnings) |
| M5 | serp_due ignores the domain | killed: test_get_is_empty_before_any_audit; test_serp_due_agrees_with_due_serp_audits[no (2 failed, 49 passed, 2 warnings) |
| M6 | serp_due ignores this week's audits | killed: test_serp_due_agrees_with_due_serp_audits[both (1 failed, 50 passed, 2 warnings) |
| M7 | serp_due ignores recent jobs | killed: test_serp_due_agrees_with_due_serp_audits[a (2 failed, 49 passed, 2 warnings) |
| M8 | serp_due ignores failures | killed: test_serp_due_agrees_with_due_serp_audits[three (1 failed, 50 passed, 2 warnings) |
| M9 | the page takes the lock | killed: test_the_page_does_not_wait_on_the_orgs_budget_lock (1 failed, 50 passed, 2 warnings) |
| M10 | budget_fits always locks | killed: test_the_page_does_not_wait_on_the_orgs_budget_lock (1 failed, 50 passed, 2 warnings) |
| M11 | one action reads the id raw | killed: server actions read path values with formSeg() (1 failed, 87 passed (88)) |
| M12 | formSeg sends a missing field | killed: addDomain refuses a form with no brand_id without calling the API; formSeg refuses a file field and a value seg() refuses; formSeg refuses a missing field instead of sending "null"; runSerpAudit refuses a form with no brand_id without calling the API (4 failed, 84 passed (88)) |
| M13 | every 409 means exists | killed: addDomain rethrows a 409 with any other title; addDomain shows a note when the brand is archived (2 failed, 86 passed (88)) |
| M14 | any non-active status reads archived | killed: serpSchedule says whether the weekly sweep audits the brand (1 failed, 87 passed (88)) |
| M15 | the budget note ignores due | killed: a queued audit hides the budget note; serpSchedule says whether the weekly sweep audits the brand (2 failed, 86 passed (88)) |
| M16 | the page passes true for serp_due | killed: a queued audit hides the budget note (1 failed, 87 passed (88)) |
| M17 | budget_fits never locks | killed by `test_the_default_check_waits_for_the_orgs_lock` (1 failed, 13 passed (test_budget.py)); before that test existed, this mutant survived the whole backend suite (1791 passed) |

## Rulings

Ruling: R1. Decided: the race test holds the conflicting row in an uncommitted owner transaction and waits until the POST blocks on it (the pattern of test_concurrent_accept_returns_409_not_500), instead of the two barrier-released threads Section 1 described. Found by: the controller, writing the proof. Why: the holder makes the race happen every run; two threads only make it likely. Cost if wrong: none to behaviour. How named: this spec and chat.

Ruling: R2. Decided: the shared `_wait_until_blocked` helper in test_api_recommendations.py runs `SELECT pg_stat_clear_snapshot()` before each poll. Found by: the controller, the proof's red run. Why: Postgres caches pg_stat_activity for the rest of a transaction, so a request that connects after the first poll is never seen; the helper had passed by timing only. Cost if wrong: one line in a test helper outside this slice's files. How named: this spec and chat.

Ruling: R3. Decided: `formSeg` covers every form value used in a path, not only `…_id` names: also `type` (reports) and label's `observation_id`, `entity_id` and redirect `brand_id`; the scan forbids `String(form.get("…_id"))`, `String(form.get("type"))` and `seg(String(`. Found by: the controller, reading the action files. Why: the same `String(null)` bug reaches the same paths through those names. Cost if wrong: a few more call sites than decision 3 named. How named: this spec and chat.

Ruling: R4. Decided: the existing "already declared" action test now stubs the API's real 409 title, and a new test shows any other 409 is rethrown. Found by: the controller, the proof's green run (the old stub's untitled 409 is now rethrown by design). Why: the stub did not match what the API sends. Cost if wrong: none to behaviour. How named: this spec and chat.

Ruling: R5. Decided: a test that the default `budget_fits` waits for the org's lock is added. Found by: the controller, mutation M17 (never lock) surviving the whole backend suite. Why: this slice makes the lock optional, so nothing else would notice the writers losing it. Cost if wrong: one test. How named: this spec and chat.

Ruling: R6. Decided: each `serp_due` case also asserts that `due_serp_audits()` returns the brand exactly when `serp_due` is true. Found by: the controller, writing the proof. Why: it ties the Python mirror to the SQL, so drift between them fails a test. Cost if wrong: none. How named: this spec and chat.

Ruling: R7. Decided: actions.test.ts's `notFound` mock throws `NOT_FOUND`, as api.test.ts's does. Found by: the controller, writing the missing-id tests. Why: a `notFound` that returns would let `formSeg` fall through to the fetch. Cost if wrong: none. How named: this spec and chat.

## Out of scope

- Slices 60 (test hardening), 61 (the probe script) and 62 (the docs sweep).
- Archived-brand refusal on other write routes (decision 5, option C).
- Per-cause 422 notes (decision 4, option B).

## Docs follow-ups

- Dated notes under 54:73, 48:79, 54:75 and its slice 54 note line 76, 47:80, 57:152 and slice 57's decision 4, 57:154 and slice 57's decision 2 and R6, 55:121 and 55:122.

## Deferred

- minor (deferred): API templates in the actions keep `${seg(id)}` after `formSeg`, so each value is checked twice; the existing path scan requires `seg()` in every template.
