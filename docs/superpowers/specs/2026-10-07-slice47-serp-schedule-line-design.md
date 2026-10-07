# Slice 47 design: the Brand SERP page says whether the brand is audited weekly

## Context

Codebase facts: main `872b849`, checked 2026-10-07.

Slice 43 added one muted sentence to the Brand SERP page (`apps/web/src/app/(app)/b/[id]/serp/page.tsx`), "Audited automatically once a week.", shown for every brand. The weekly sweep, `due_serp_audits()` (migration 0024), only considers a brand whose `status` is `'active'` and which has at least one row in `domain`. So the sentence is untrue for a brand with no declared domain, which slice 43 deferred as a minor (findings-slice43 §3, R10), and also for an archived brand.

Brand status: `brand.status` defaults to `'active'`; the API sets `'archived'` (`DELETE /brands/{id}`) and no other value. There is no database constraint on the column. An archived brand's pages still render (`brand_or_404` does not filter on status). Dev has 5 brands, all `active`. Domains are declared through the API (`/brands/{id}/domains`); the web app has no screen for them.

Classification: **bounded** by the brainstorming skill's test (one existing page), said as the first line of the first brainstorming reply with the session model (Opus 5.5). The user's process asks for a spec and plan even for small changes, so the full process is followed.

Decisions approved in chat (2026-10-07), each after approaches with trade-offs and a recommendation written in a chat message:
1. The web page decides, from `/brands/{id}` and `/brands/{id}/domains`; over an `auto_audit` field on `GET /brands/{id}/audits/serp` (an API change and regenerated types), or deleting the sentence for every brand.
2. A brand that is not audited weekly gets a line saying why; over hiding the sentence, or one generic line with no reason.

Design Section 1 (the three lines, archived checked first) and Section 2 (helper, page fetches, one vitest with four cases) were each shown in chat and approved.

Out of scope: the page still says "weekly" for an active brand with a domain that the sweep skips:
- when the DataForSEO login or password is empty, `queue_due_serp_audits()` queues nothing; the web app cannot see the worker's configuration;
- after 3 failed `audit_serp` jobs in the last 7 days (`due_serp_audits()`, migration 0024);
- while the org's daily budget has no room for the job (`queue_due_serp_audits()` skips the brand until there is).

## Design

The page shows exactly one line where the fixed sentence was:

| Brand | Line |
|---|---|
| `status` is not `active` | "Not audited automatically: the brand is archived." |
| active, no declared domain | "Not audited automatically: the brand has no declared domain." |
| active, at least one domain | "Audited automatically once a week." |

Archived is checked first: an archived brand with no domain gets the archived reason. Any status other than `active` gets the archived line; the only other value ever written is `'archived'`, and no test pins another value to it (R3). Everything else on the page is unchanged.

The page fetches the audits, the brand and its domains in one `Promise.all`. The layout already fetches `/brands/{id}`, so that request is made twice per render; no caching is added.

As a diff against main `872b849` (generated from the proof below):

```diff
diff --git a/apps/web/src/app/(app)/b/[id]/serp/page.tsx b/apps/web/src/app/(app)/b/[id]/serp/page.tsx
--- a/apps/web/src/app/(app)/b/[id]/serp/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/serp/page.tsx
@@ -3,12 +3,13 @@ import {
   auditNote,
   ownershipText,
   serpError,
+  serpSchedule,
   serpStatus,
   typeCounts,
   usd,
   type Params,
 } from "@/lib/format";
-import type { SerpAudits } from "@/lib/types";
+import type { Brand, Domain, SerpAudits } from "@/lib/types";
 import { runSerpAudit } from "./actions";
 
 export default async function Serp({
@@ -20,7 +21,11 @@ export default async function Serp({
 }) {
   const { id } = await params;
   const sp = await searchParams;
-  const { job, audits } = await api<SerpAudits>(`/brands/${id}/audits/serp`);
+  const [{ job, audits }, brand, domains] = await Promise.all([
+    api<SerpAudits>(`/brands/${id}/audits/serp`),
+    api<Brand>(`/brands/${id}`),
+    api<Domain[]>(`/brands/${id}/domains`),
+  ]);
   const status = serpStatus(job);
   return (
     <>
@@ -31,7 +36,7 @@ export default async function Serp({
           <span className="muted">{auditNote(sp.queued)}</span>
         )}
       </form>
-      <p className="muted">Audited automatically once a week.</p>
+      <p className="muted">{serpSchedule(brand.status, domains.length)}</p>
       {status && <p className="muted">{status}</p>}
       {audits.length === 0 && (
         <p className="muted">
diff --git a/apps/web/src/lib/format.test.ts b/apps/web/src/lib/format.test.ts
--- a/apps/web/src/lib/format.test.ts
+++ b/apps/web/src/lib/format.test.ts
@@ -19,6 +19,7 @@ import {
   REPORT_TYPE,
   reportNote,
   serpError,
+  serpSchedule,
   serpStatus,
   typeCounts,
   usd,
@@ -259,6 +260,17 @@ test("serpStatus shows a run in progress or a failure, else nothing", () => {
   expect(serpStatus({ status: "done", error: null })).toBeNull();
 });
 
+test("serpSchedule says whether the weekly sweep audits the brand", () => {
+  const weekly = "Audited automatically once a week.";
+  const noDomain =
+    "Not audited automatically: the brand has no declared domain.";
+  const archived = "Not audited automatically: the brand is archived.";
+  expect(serpSchedule("active", 1)).toBe(weekly);
+  expect(serpSchedule("active", 0)).toBe(noDomain);
+  expect(serpSchedule("archived", 0)).toBe(archived);
+  expect(serpSchedule("archived", 2)).toBe(archived);
+});
+
 test("ownershipText gives the count and a whole percentage", () => {
   expect(ownershipText(3, 10)).toBe("3 of 10 (30%)");
   expect(ownershipText(1, 3)).toBe("1 of 3 (33%)");
diff --git a/apps/web/src/lib/format.ts b/apps/web/src/lib/format.ts
--- a/apps/web/src/lib/format.ts
+++ b/apps/web/src/lib/format.ts
@@ -187,6 +187,17 @@ export const serpStatus = (
         ? `Last audit failed: ${serpError(job.error)}`
         : null;
 
+/**
+ * The Brand SERP page's schedule line. due_serp_audits() (migration 0024)
+ * only considers active brands with at least one declared domain.
+ */
+export const serpSchedule = (status: string, domains: number) =>
+  status !== "active"
+    ? "Not audited automatically: the brand is archived."
+    : domains === 0
+      ? "Not audited automatically: the brand has no declared domain."
+      : "Audited automatically once a week.";
+
 /** "3 of 10 (30%)"; no percentage when the page has no organic results. */
 export const ownershipText = (owned: number, organic: number) =>
   organic === 0
diff --git a/apps/web/src/lib/types.ts b/apps/web/src/lib/types.ts
--- a/apps/web/src/lib/types.ts
+++ b/apps/web/src/lib/types.ts
@@ -10,6 +10,7 @@ export type Prompt = S["PromptOut"];
 export type Observation = S["ObservationOut"];
 export type ObservationDetail = S["ObservationDetail"];
 export type Competitor = S["CompetitorOut"];
+export type Domain = S["DomainOut"];
 export type Ops = S["OpsOut"];
 export type LabelQueue = S["LabelQueue"];
 export type LabelResult = S["LabelResult"];
```

The helper's comment departs from the Section 2 text ("mirrors due_serp_audits()"), which overstated it (R1).

## Testing

`apps/web/src/lib/format.test.ts` gains `serpSchedule says whether the weekly sweep audits the brand` (in the diff above), with four cases: active with 1 domain, active with 0, archived with 0, archived with 2. No test covers the page's wiring (R2). Expected gates: web 50 vitest (49 on main plus 1), lint, typecheck and build pass; backend unchanged at `1753 passed, 2 deselected` (no backend file is touched).

### Proof

Run 2026-10-07 in the scratchpad on a copy of main's `apps/web` (`git archive`), with the repo's `node_modules` linked.

- Red, main's code with the new test: `1 failed | 28 passed (29)` in `format.test.ts`; the failing test is the new one.
- Green, patched: `npm run gate` passes typecheck, lint, test (`Tests  50 passed (50)`) and build (`Compiled successfully`); its last step, `gen:check`, could not run in the scratch copy, which holds only `apps/web` (`scripts/export_openapi.py` is missing). No API file changes; `gen:check` runs in the web gate on the branch (R5).
- Prettier is not in the gate. `format.test.ts` already fails `prettier --check` on main; the added lines are not in Prettier's diff.

Each change below fails the new test (`1 failed | 28 passed (29)`):

| Mutant | Change |
|---|---|
| M1 | the status check is dropped |
| M2 | the domain check is dropped |
| M3 | the two checks are swapped (domain first) |
| M4 | `domains === 0` becomes `domains <= 1` |

## Rulings

Quoted from the ledger:

> Ruling: R1. Decided: the helper's comment says "due_serp_audits() (migration 0024) only considers active brands with at least one declared domain" instead of the Section 2 text "mirrors due_serp_audits()". Found by: the controller, running the proof. Why: due_serp_audits() also has recency and job conditions, so "mirrors" overstated what the helper does. Cost if wrong: none to behaviour; comment wording only. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R2. Decided: no test covers the page's wiring (the three fetches and the arguments passed to serpSchedule); the vitest and the mutation table cover the helper only. Found by: the controller, running the proof. Why: the repo has no tests for Server Component pages, and adding a page-test harness is outside this slice; tsc pins the argument types. Cost if wrong: a wiring slip (for example passing aliases.length) would ship unnoticed by the gate. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R3. Decided: spec review Minor 1 is fixed by stating in the spec that any status other than active gets the archived line (only 'archived' is ever written), with no added test; Minor 2 is fixed by naming the two other cases where the page still says weekly (three failed audit_serp jobs in 7 days, and an org budget with no room) next to the missing-credentials case; Minor 3 (R2's example is narrow) is left. Found by: the spec reviewer (Opus 5.5), 2026-10-07. Why: Minor 1 and 2 were unstated or incomplete statements; a test pinning "paused" to the archived line would pin a wrong label for a status nobody writes; Minor 3 is accurate as written. Cost if wrong: if another brand status is ever added, its page says "archived" until the helper is changed. How named: in chat, 2026-10-07, after the spec review.

> Ruling: R4. Decided: spec re-review Minor 1 is fixed: the spec's Design paragraph says "the only other value ever written is 'archived'" instead of "only 'archived' is ever written", and R3's same wording is corrected by a Correction to R3 line. Found by: the spec re-reviewer (Opus 5.5), 2026-10-07. Why: 'active' is also written, as the column default, so the old wording was loose. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the re-review.

> Correction to R3 (2026-10-07, from the spec re-review): "only 'archived' is ever written" means the only value other than 'active' (the column default) ever written is 'archived'.

> Ruling: R5. Decided: the spec's Proof is corrected to say the scratch run's npm run gate passed typecheck, lint, test and build but its last step, gen:check, could not run there (the copy holds only apps/web, so scripts/export_openapi.py is missing); the plan's Step 2 expected output adds the "Failed Tests 1" banner line that its grep also prints; the plan records that its verification ran the same four steps. Found by: the controller, verifying the plan on a fresh copy of main. Why: the Proof listed the gate's passing lines without saying its last step failed in the scratch copy, and Step 2's expected output was incomplete. Cost if wrong: none to behaviour; gen:check runs in the implementer's web gate on the branch, where the backend exists. How named: in chat, 2026-10-07, after verifying the plan.

## Deferred minors

Quoted from the ledger:

- "minor (deferred): spec review minor 3, R2's cost line names aliases.length as the example; passing another array's .length (for example audits.length) would also type-check (R3)."

## Live check

Optional, asked first: dev's brands are all active; three have no domain, so their Brand SERP page would show the no-domain line. Viewing it needs uvicorn and `next dev`, and each page view authenticates with the API key, which writes `api_key.last_used_at`.
