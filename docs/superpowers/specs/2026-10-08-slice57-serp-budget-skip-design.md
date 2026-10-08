# Slice 57 design: the Brand SERP page says when the weekly sweep skips a brand for budget

Classification: bounded, said first in chat on 2026-10-08, before the first question; the user's standing rule still runs the full spec, plan and subagent process. Session model Fable 5.1 for the brainstorm and the approaches; Opus 5.5 from the proof on (the user switched on 2026-10-08).

## Context

Slice 55 gave `GET /v1/brands/{id}/audits/serp` the fields `serp_configured` and `failed_7d`, and `serpSchedule` (apps/web/src/lib/format.ts) names two of the three reasons `queue_due_serp_audits()` (apps/workers/bsi_workers/worker.py) skips an active brand with a domain. The third, an org budget with no room, was left out (findings-slice55.md: "The third, an org budget with no room, is still not shown"; findings-slice47.md: "An org budget with no room still reads "weekly"."), so the page reads "Audited automatically once a week." while the sweep `continue`s past the brand with no job and no log.

The slice 55 spec gave its reason for leaving budget out: it "is computed live under the org's advisory lock and would flicker; the Ops page already shows spend." This slice answers both halves. The lock: the user chose to take it in the API request too (decision 2 below), so the field is the sweep's own budget check. The flicker: the check can change within a day, and the note says so ("today", "the budget resets at midnight UTC"). The field is computed for every brand, due or not, so the note says what waits rather than that the brand is skipped (decision 4).

User decisions (2026-10-08), with the approaches text shown in chat before each:
1. Approach A, over (B) returning headroom and estimate numbers for the web to compare and (C) the web reading `/v1/ops`, which misses the waiting-job margin: one `budget_room: bool` on the audits response, from one shared helper in `bsi_core` that the sweep also calls; `SERP_JOB_MICROS` moves to `bsi_core` because the API must not import the worker.
2. Section 1 (backend) approved with option (i): the helper calls `budget_fits`, so the API request takes the org's advisory transaction lock as the sweep does, over (ii) splitting `budget_fits` into a lock-free part.
3. Sections 2 (web) and 3 (tests) approved.
4. After the spec review (finding: the budget line showed for brands the sweep is not skipping, because the sweep checks the budget only for brands `due_serp_audits()` returns, and the brand's own waiting job counts against it), option 2 over (1) computing `budget_room = not due or fits` in the API through `due_serp_audits()` and (3) both: keep `budget_room`, reword the line so it never says the brand is skipped, and leave it out while the brand's own audit is queued or running.

## Section 1 — Backend

- `packages/core/bsi_core/scheduling.py` gains `SERP_JOB_MICROS = 40_000` (moved from the worker with its comment) and `serp_budget_fits(s, org_id)`: the count and the check the sweep ran inline, unchanged in meaning. It counts the org's `audit_serp` jobs that are queued or running (row-level security scopes the count; no brand filter, as before), reserves one estimate for each plus one for the next job, and returns `budget_fits(s, org_id, 0, extra_micros=...)`. `budget_fits` checks the tenant setting (fails closed) and takes `pg_advisory_xact_lock` for the rest of the transaction.
- The worker imports `SERP_JOB_MICROS` and `serp_budget_fits` from there; `JOB_ESTIMATES["audit_serp"]` and `worker.SERP_JOB_MICROS` (read by tests/integration/test_serp_audit.py) are unchanged. The sweep's count and check become `if not serp_budget_fits(s, org_id): continue`; the ponytail comment about the "Run audit now" race stays above it, with "(the API takes no lock)" now "(the press takes no lock)", since the GET takes it (R5).
- `SerpAuditsOut` (apps/api/bsi_api/schemas.py) gains `budget_room: bool`, commented as the sweep's check, which skips the brand only if it is due, and which counts the brand's own waiting job; `latest_serp` (apps/api/bsi_api/routers/audits.py) fills it with `serp_budget_fits(c.s, c.org_id)`. The route's tenant session (`TENANT`, deps.py) commits before the response, which releases the lock.
- `npm run gen` regenerates apps/web/openapi.json and apps/web/src/lib/schema.d.ts; the only change is the new required boolean `budget_room` on `SerpAuditsOut`.

Limits, stated: the field is the API process's view at request time; the sweep runs once a minute and decides again then. A page load can now wait on the org's advisory lock (`pg_advisory_xact_lock` has no timeout) while the worker holds it, which today is only for short budget checks; `SET LOCAL lock_timeout` is the upgrade if that ever matters (R6). The API and the worker read the same settings today (the slice 55 limit, unchanged). A queued job that later fails the claim-time budget check still shows through the latest job as before.

## Section 2 — Web

`serpSchedule` gains a fifth parameter `budgetRoom: boolean` and a sixth, `jobStatus?: string | null` (the latest audit_serp job's status). The budget is checked last, so archived, no domain, not configured and the failure pause all outrank it. With no room, and the brand's own audit neither queued nor running, the line reads:

> Audited automatically once a week; today the daily budget has no room for a Brand SERP audit, so a due audit waits until there is room. The budget resets at midnight UTC.

It never says the brand is skipped: `budget_room` is computed whether or not the brand is due. While the brand's own audit is queued or running, that job is what fills the room, so the line stays "Audited automatically once a week." (R8).

The Brand SERP page (apps/web/src/app/(app)/b/[id]/serp/page.tsx) destructures `budget_room` from the audits response it already fetches and passes it and `job?.status` on. No new fetch; `SerpAudits` in types.ts is generated.

## Section 3 — Testing

- `tests/integration/test_api_serp.py`: the empty-response test expects `"budget_room": True`; a new `test_get_reports_budget_room` sets the org's `daily_budget_usd` and reads the field: $0.04 gives True and $0.03 False (no waiting job, so one $0.04 estimate); after one queued `audit_serp` job on another brand of the org, $0.04 gives False and $0.08 True.
- `tests/integration/test_serp_audit.py` is unchanged; its sweep budget tests now exercise the moved code (mutations M2 to M6 below).
- `apps/web/src/lib/format.test.ts`: the existing `serpSchedule` cases pass `true`; new cases give the budget line with no job, a done job and a failed job, the weekly line while the job is queued or running, and each other reason outranking the budget.

## The change

Generated from the proof (the scratchpad copy of main 77da2e7 with the change applied); the generated openapi.json and schema.d.ts hunks are omitted.

```diff
--- a/packages/core/bsi_core/scheduling.py
+++ b/packages/core/bsi_core/scheduling.py
@@ -19,6 +19,9 @@
 # Active prompts per organization, by plan (spec §5).
 PLAN_LIMITS = {"starter": 100, "pro": 500, "agency": 2_000}
 DEFAULT_LIMIT = PLAN_LIMITS["starter"]  # an unknown plan is Starter
+# A SERP audit is 2 calls at the observed $0.002 (2026-10-05), 4,000
+# micros; 40,000 is kept as a 10x margin, which fails closed.
+SERP_JOB_MICROS = 40_000
 
 
 def first_run(now: datetime, hour_utc: int) -> datetime:
@@ -135,6 +138,27 @@
     # headroom absorbs it.
     estimate = settings.obs_cost_estimate_micros
     return bool(spent + extra_micros + (pending + n_obs) * estimate <= cap)
+
+
+def serp_budget_fits(s: Session, org_id: uuid.UUID) -> bool:
+    """True if one more audit_serp job fits in the org's budget for today,
+    counting one estimate for each of the org's audit_serp jobs still
+    queued or running (those have recorded no cost yet).
+
+    The weekly sweep's check, and the Brand SERP page's reason when the
+    sweep skips a brand. Like budget_fits, which it calls, it takes the
+    org's advisory lock to the end of the transaction.
+    """
+    # Row-level security scopes the count to the org; budget_fits fails
+    # closed outside the org's tenant session.
+    waiting = s.scalar(
+        select(func.count()).where(
+            m.Job.kind == "audit_serp",
+            m.Job.status.in_(("queued", "running")),
+        )
+    )
+    extra = SERP_JOB_MICROS * ((waiting or 0) + 1)
+    return budget_fits(s, org_id, 0, extra_micros=extra)
 
 
 def check_active_limit(
--- a/apps/workers/bsi_workers/worker.py
+++ b/apps/workers/bsi_workers/worker.py
@@ -55,7 +55,13 @@
     snapshot_domain,
     with_deadline,
 )
-from bsi_core.scheduling import budget_fits, enqueue_job, run_schedule
+from bsi_core.scheduling import (
+    SERP_JOB_MICROS,
+    budget_fits,
+    enqueue_job,
+    run_schedule,
+    serp_budget_fits,
+)
 from bsi_core.serp import classify
 from bsi_core.storage import LocalRawStore, RawStore
 from bsi_core.suggest import (
@@ -115,9 +121,6 @@
     ) -> Response: ...
 
 
-# A SERP audit is 2 calls at the observed $0.002 (2026-10-05), 4,000
-# micros; 40,000 is kept as a 10x margin, which fails closed.
-SERP_JOB_MICROS = 40_000
 # One locale: 2 calls of up to ~240 s each (a 120 s read, then up to a
 # 120 s body read before the deadline check) stay under claim_job()'s
 # 10 minutes, assuming a quick connect and send and headers in one read.
@@ -861,18 +864,11 @@
         try:
             with tenant_session(org_id) as s:
                 # ponytail: a "Run audit now" press committed after this
-                # count is missed (the API takes no lock); process_job's
+                # count is missed (the press takes no lock); process_job's
                 # claim check still catches it. To close the gap, the press
                 # and this sweep would both take the org's lock before
                 # counting.
-                waiting = s.scalar(
-                    select(func.count()).where(
-                        m.Job.kind == "audit_serp",
-                        m.Job.status.in_(("queued", "running")),
-                    )
-                )
-                extra = SERP_JOB_MICROS * ((waiting or 0) + 1)
-                if not budget_fits(s, org_id, 0, extra_micros=extra):
+                if not serp_budget_fits(s, org_id):
                     continue
                 enqueue_job(
                     s,
--- a/apps/api/bsi_api/schemas.py
+++ b/apps/api/bsi_api/schemas.py
@@ -467,6 +467,10 @@
     # Failed audit_serp jobs in the last 7 days; due_serp_audits()
     # (migration 0024) stops at 3. The web holds the threshold.
     failed_7d: int
+    # The sweep's own budget check (serp_budget_fits) on today's UTC
+    # spend: while it is False the sweep skips the brand, if it is due,
+    # with no job. The brand's own waiting audit_serp job counts too.
+    budget_room: bool
 
 
 class PageOptimizeIn(BaseModel):
--- a/apps/api/bsi_api/routers/audits.py
+++ b/apps/api/bsi_api/routers/audits.py
@@ -7,6 +7,7 @@
 
 from bsi_core import models as m
 from bsi_core.config import get_settings
+from bsi_core.scheduling import serp_budget_fits
 from fastapi import APIRouter
 from sqlalchemy import func, select
 
@@ -104,4 +105,5 @@
             and settings.dataforseo_password.get_secret_value()
         ),
         "failed_7d": failed or 0,
+        "budget_room": serp_budget_fits(c.s, c.org_id),
     }
--- a/apps/web/src/lib/format.ts
+++ b/apps/web/src/lib/format.ts
@@ -204,13 +204,19 @@
  * The Brand SERP page's schedule line. due_serp_audits() (migration 0024)
  * only considers active brands with at least one declared domain, and
  * stops after SERP_MAX_FAILURES failed jobs in 7 days; the sweep itself
- * queues nothing without DataForSEO credentials.
+ * queues nothing without DataForSEO credentials, and skips a due brand
+ * while the org's budget has no room for the audit (serp_budget_fits).
+ * budgetRoom is computed whether or not the brand is due, so the budget
+ * note never says the brand is skipped, and is left out while the
+ * brand's own audit is queued or running (that job counts against it).
  */
 export const serpSchedule = (
   status: string,
   domains: number,
   configured: boolean,
   failed7d: number,
+  budgetRoom: boolean,
+  jobStatus?: string | null,
 ) =>
   status !== "active"
     ? "Not audited automatically: the brand is archived."
@@ -220,7 +226,9 @@
         ? "Not audited automatically: the SERP provider is not configured."
         : failed7d >= SERP_MAX_FAILURES
           ? `Not audited automatically: ${failed7d} audits failed in the last 7 days; the sweep tries again once fewer than ${SERP_MAX_FAILURES} remain in that window.`
-          : "Audited automatically once a week.";
+          : !budgetRoom && jobStatus !== "queued" && jobStatus !== "running"
+            ? "Audited automatically once a week; today the daily budget has no room for a Brand SERP audit, so a due audit waits until there is room. The budget resets at midnight UTC."
+            : "Audited automatically once a week.";
 
 /** "3 of 10 (30%)"; no percentage when the page has no organic results. */
 export const ownershipText = (owned: number, organic: number) =>
--- a/apps/web/src/app/(app)/b/[id]/serp/page.tsx
+++ b/apps/web/src/app/(app)/b/[id]/serp/page.tsx
@@ -22,7 +22,11 @@
 }) {
   const { id } = await params;
   const sp = await searchParams;
-  const [{ job, audits, serp_configured, failed_7d }, brand, domains] =
+  const [
+    { job, audits, serp_configured, failed_7d, budget_room },
+    brand,
+    domains,
+  ] =
     await Promise.all([
       api<SerpAudits>(`/brands/${seg(id)}/audits/serp`),
       api<Brand>(`/brands/${seg(id)}`),
@@ -39,7 +43,14 @@
         )}
       </form>
       <p className="muted">
-        {serpSchedule(brand.status, domains.length, serp_configured, failed_7d)}
+        {serpSchedule(
+          brand.status,
+          domains.length,
+          serp_configured,
+          failed_7d,
+          budget_room,
+          job?.status,
+        )}
       </p>
       {domainNote(sp.domain) && (
         <p className="muted">{domainNote(sp.domain)}</p>
--- a/apps/web/src/lib/format.test.ts
+++ b/apps/web/src/lib/format.test.ts
@@ -281,16 +281,29 @@
     "Not audited automatically: the SERP provider is not configured.";
   const failed = (n: number) =>
     `Not audited automatically: ${n} audits failed in the last 7 days; the sweep tries again once fewer than 3 remain in that window.`;
-  expect(serpSchedule("active", 1, true, 1)).toBe(weekly);
-  expect(serpSchedule("active", 1, true, 2)).toBe(weekly);
-  expect(serpSchedule("active", 1, true, 3)).toBe(failed(3));
-  expect(serpSchedule("active", 1, true, 5)).toBe(failed(5));
-  expect(serpSchedule("active", 1, false, 0)).toBe(unconfigured);
+  const noBudget =
+    "Audited automatically once a week; today the daily budget has no room for a Brand SERP audit, so a due audit waits until there is room. The budget resets at midnight UTC.";
+  expect(serpSchedule("active", 1, true, 1, true)).toBe(weekly);
+  expect(serpSchedule("active", 1, true, 2, true)).toBe(weekly);
+  expect(serpSchedule("active", 1, true, 3, true)).toBe(failed(3));
+  expect(serpSchedule("active", 1, true, 5, true)).toBe(failed(5));
+  expect(serpSchedule("active", 1, false, 0, true)).toBe(unconfigured);
   // Not configured outranks the failure pause.
-  expect(serpSchedule("active", 1, false, 3)).toBe(unconfigured);
-  expect(serpSchedule("active", 0, false, 3)).toBe(noDomain);
-  expect(serpSchedule("archived", 1, false, 3)).toBe(archived);
-  expect(serpSchedule("archived", 0, true, 0)).toBe(archived);
+  expect(serpSchedule("active", 1, false, 3, true)).toBe(unconfigured);
+  expect(serpSchedule("active", 0, false, 3, true)).toBe(noDomain);
+  expect(serpSchedule("archived", 1, false, 3, true)).toBe(archived);
+  expect(serpSchedule("archived", 0, true, 0, true)).toBe(archived);
+  expect(serpSchedule("active", 1, true, 2, false)).toBe(noBudget);
+  expect(serpSchedule("active", 1, true, 0, false, "done")).toBe(noBudget);
+  expect(serpSchedule("active", 1, true, 0, false, "failed")).toBe(noBudget);
+  // The brand's own waiting job counts against the budget: no note.
+  expect(serpSchedule("active", 1, true, 0, false, "queued")).toBe(weekly);
+  expect(serpSchedule("active", 1, true, 0, false, "running")).toBe(weekly);
+  // Every other reason outranks the budget.
+  expect(serpSchedule("active", 1, true, 3, false)).toBe(failed(3));
+  expect(serpSchedule("active", 1, false, 0, false)).toBe(unconfigured);
+  expect(serpSchedule("active", 0, true, 0, false)).toBe(noDomain);
+  expect(serpSchedule("archived", 1, true, 0, false)).toBe(archived);
 });
 
 test("ownershipText gives the count and a whole percentage", () => {
--- a/tests/integration/test_api_serp.py
+++ b/tests/integration/test_api_serp.py
@@ -1,4 +1,5 @@
 from datetime import UTC, datetime, timedelta
+from decimal import Decimal
 
 from bsi_api.routers import audits
 from bsi_core import models as m
@@ -107,6 +108,7 @@
         "audits": [],
         "serp_configured": True,
         "failed_7d": 0,
+        "budget_room": True,
     }
 
 
@@ -179,6 +181,34 @@
         assert r.json()["serp_configured"] is expected, (login, password)
 
 
+def test_get_reports_budget_room(
+    client, owner, make_org, make_brand, monkeypatch
+):
+    """The sweep's own check: one $0.04 estimate for the next job plus
+    one for each audit_serp job still queued or running."""
+    _configured(monkeypatch)
+    org = make_org()
+    bid = make_brand(org)
+
+    def room(usd):
+        with owner() as s, s.begin():
+            s.execute(
+                update(m.Organization)
+                .where(m.Organization.id == org.id)
+                .values(daily_budget_usd=Decimal(usd))
+            )
+        r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
+        assert r.status_code == 200, r.text
+        return r.json()["budget_room"]
+
+    assert room("0.04") is True
+    assert room("0.03") is False
+    # A waiting job on another brand of the org counts too.
+    _job(owner, org, make_brand(org, name="Other"), "audit_serp", "queued")
+    assert room("0.04") is False
+    assert room("0.08") is True
+
+
 def test_get_counts_failed_audit_serp_jobs_in_7_days(
     client, owner, make_org, make_brand, monkeypatch
 ):
```

## Evidence

Proof directory: a fresh scratchpad copy of main 77da2e7 (`proof57b-1791477789`, made after the spec review; the first proof, `proof57-1791476994`, is superseded), written only by the controller.

- Red: main's code with the new tests. Backend `test_api_serp.py`: 2 failed (`test_get_is_empty_before_any_audit`, `test_get_reports_budget_room`), 7 passed. Web `format.test.ts`: 1 failed (`serpSchedule says whether the weekly sweep audits the brand`), 29 passed.
- Green, patched: `ruff format --check`, `ruff check`, `mypy` (31 source files) clean; `test_api_serp.py`, `test_serp_audit.py` and `test_budget.py`: 59 passed; web typecheck, lint, 76 vitest and build pass. `gen:check` cannot run in the copy (it needs git); `npm run gen` there changed only the `budget_room` lines.
- The full backend gate runs at execution.

Mutations, each applied alone to the patched copy and reverted (backend: test_api_serp.py and test_serp_audit.py; web: the whole vitest run):

| # | Mutation | Result |
|---|---|---|
| M1 | `latest_serp` returns `"budget_room": True` | killed: test_get_reports_budget_room |
| M2 | waiting jobs not counted (`extra = SERP_JOB_MICROS`) | killed: test_get_reports_budget_room and 3 sweep tests |
| M3 | the next job not counted (`* (waiting or 0)`) | killed: test_get_reports_budget_room and 4 sweep tests |
| M4 | only running jobs wait | killed: test_get_reports_budget_room and 2 sweep tests |
| M5 | the helper reserves one observation (`n_obs=1`) | killed: test_get_reports_budget_room and 7 sweep tests |
| M6 | the sweep ignores the helper (`if False:`) | killed: 4 sweep tests |
| M7 | the web drops the budget reason | killed: vitest |
| M8 | the web inverts the budget reason | killed: vitest |
| M9 | the page passes `true` instead of `budget_room` | survived: vitest 76 passed |
| M10 | the web drops the hide rule | killed: vitest |
| M11 | the web hides only while queued | killed: vitest |
| M12 | the web hides only while running | killed: vitest |
| M13 | the page does not pass `job?.status` | survived: vitest 76 passed |

In the first proof, M9 also passed tsc and eslint (one warning, unused `budget_room`, exit 0), so the gate passes.

## Rulings

Ruling: R1. Decided: the API test sets budgets at the boundaries ($0.04 True, $0.03 False, then with one queued audit_serp job on another brand of the org $0.04 False, $0.08 True) instead of the $0.05/$0.09 in the approved plan. Found by: the controller, writing the proof. Why: the plan's values also kill M1 to M5, but only boundary values pin the exact threshold (a SERP_JOB_MICROS of 45,000 passes at $0.05 and fails at $0.04), and the other-brand job shows the count is org-wide, as the sweep's is. Cost if wrong: one test's numbers. How named: this spec and chat.

Ruling: R2. Decided: `latest_serp`'s docstring is left unchanged, against the approved plan's "update the docstring sentence". Found by: the controller, writing the proof. Why: its sentence is about the latest job showing failures that wrote no rows, including a claim-time budget failure, which is still true; the new field is documented on `SerpAuditsOut`. Cost if wrong: one docstring sentence. How named: this spec and chat.

Ruling: R3. Decided: M9 (the page passing a constant instead of `budget_room`) is accepted and deferred, not covered by a new test. Found by: the controller, mutation M9. Why: no test renders the Brand SERP page; slices 47 and 55 left the same gap for the other arguments, and a page-render harness is its own slice. Cost if wrong: a regression in one argument of one call goes uncaught by the gate. How named: this spec, Deferred, and chat.

Correction to R3 (2026-10-08): the second proof adds M13 (the page not passing `job?.status`), which also survives; it is deferred on the same grounds.

Ruling: R4. Decided: the spec no longer says "the page's verdict is the sweep's"; the field is the sweep's own check, but the sweep applies it only to due brands. Found by: the spec reviewer (finding 1). Why: it overstated what the page shows. Cost if wrong: none; a sentence. How named: this spec and chat.

Ruling: R5. Decided: the worker's ponytail comment says "(the press takes no lock)" instead of "(the API takes no lock)". Found by: the spec reviewer (finding 2). Why: the GET now takes the org's lock; only the "Run audit now" press does not. Cost if wrong: one comment. How named: this spec and chat.

Ruling: R6. Decided: Limits says a page load can wait on the org's advisory lock, with `SET LOCAL lock_timeout` as the upgrade; no timeout is added. Found by: the spec reviewer (finding 3). Why: every holder today is a short budget check; a timeout would be code for a wait nobody has seen. Cost if wrong: a slow Brand SERP page while some future long holder runs. How named: this spec and chat.

Ruling: R7. Decided: the docs PR adds a dated note under the findings-slice47.md and findings-slice55.md lines that say the budget case is not shown. Found by: the spec reviewer (finding 4). Why: those lines become stale with this slice. Cost if wrong: two stale lines. How named: this spec and chat.

Ruling: R8. Decided: the hide rule is a sixth `serpSchedule` parameter, `jobStatus?: string | null`, given `job?.status` by the page, not a boolean the page computes. Found by: the controller, writing the second proof. Why: the rule then lives in the tested function (M10 to M12 are killed); the page only passes a field through, as it does the others. Cost if wrong: an optional sixth argument. How named: this spec and chat.

## Docs follow-ups

- findings-slice47.md and findings-slice55.md: a dated note under each line that says the budget case is not shown (R7).

## Out of scope

- Showing the amount of headroom (the Ops page shows spend).
- A worker whose settings differ from the API's.
- Closing the "Run audit now" race named in the sweep's ponytail comment.

## Deferred

- minor (deferred): no test renders the Brand SERP page, so passing a constant for `budget_room` (M9) or leaving out `job?.status` (M13) passes the gate (R3).
- minor (deferred): the note shows for a brand that is not due (audited this week) whenever the org's budget is full; it is true there but says nothing about that brand (decision 4).
