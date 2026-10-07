# Slice 46 findings: the SERP sweep counts waiting SERP jobs against the budget

## 1. What was built

`queue_due_serp_audits()` (apps/workers/bsi_workers/worker.py) counts the org's `audit_serp` jobs that are queued or running, in the org's tenant session, and asks `budget_fits` for room for one $0.04 estimate per waiting job plus the brand's own. Jobs queued earlier in the same sweep, in earlier sweeps, or by "Run audit now" now take room. This fixes the slice 43 deferred minor (findings-slice43 §3, R10), which the spec review found overstated: on main an extra job failed at claim time only when other spend that day had used the room, since a finished SERP job records about $0.004. The sweep is now stricter than the claim check: on a tight budget a brand is skipped, stays due, and is queued a minute or so later.

Spec: docs/superpowers/specs/2026-10-07-slice46-serp-sweep-budget-design.md (rulings R1–R4 and both corrections to R1 in the spec as approved; R5 added to it by these docs commits). Plan: docs/superpowers/plans/2026-10-07-slice46-serp-sweep-budget.md (Task 1). Merged via PR #94 (https://github.com/aiagencyindia-lab/bsi-platform/pull/94), main `b0dcc6b`.

**Code**: apps/workers/bsi_workers/worker.py (`queue_due_serp_audits`: the waiting-job count, the `extra` estimate, the docstring bullet, a `ponytail:` comment on the race); tests/integration/test_serp_audit.py (`_budget` and three tests, 6 items, 32 → 38).

**User decisions**, as the ledger records them:
- "User decisions (2026-10-07): the user asked "Fix the SERP sweep budget minor"; approach "Count waiting SERP jobs" (over a running total per sweep, or changing budget_fits), after approaches written in chat; the short design approved in chat."
- "User decision (not a ruling): 2026-10-07, re-asked after the spec review's Important 2 showed the problem was overstated (on main an extra job fails at claim only when other spend that day has used the room, since a finished SERP job records about $0.004, not the $0.04 estimate; and the fix reserves the full estimate for each waiting job, about 10x its observed cost), the user chose again "Keep the fix"."

**Results** (quoted from the ledger):
- "Task 1: implementer aaffbe7cbbba4117e, commit 42e1a01 (trailer Opus 5.5 checked); report: red 3 failed 35 passed (the three expected tests), green 38 passed, gate exit 0, gate-task1.txt 1753 passed, 2 deselected, 2 warnings, coverage 100%."
- "Controller gates on 42e1a01: backend gate exit 0, 1753 passed, 2 deselected, 2 warnings in 197.26s (0:03:17); web gate exit 0, Tests  49 passed (49), Compiled successfully."
- "CI run 37585894591: success, 1753 passed, 2 deselected, 2 warnings in 151.98s (0:02:31); web Compiled successfully. PR #94 merged by the controller after the user said "go ahead" to "Should I merge PR #94?" (2026-10-07)."
- "Gates on main b0dcc6b after merge: backend 1753 passed, 2 deselected, 2 warnings in 284.42s (0:04:44); web Tests  49 passed (49)."

**Reviews**, as the ledger records them:
- "Spec review (a407d31a0279a0c01, e36a242): 0 Critical, 2 Important, 4 Minor."
- "Spec re-review (a407d31a0279a0c01, e3352df): Important 1, Important 2 and Minors 1–3 addressed, Minor 4 stated as a limitation; 1 new Important (N1: the upgrade path named only half of what closes the race) and 1 new Minor (N2: the Design section points at R1 "as corrected")."
- "Plan review (ae25cd6fea1341d78, b53a329): "Ready to execute? Yes"; 0 findings."
- "Task 1: task review (a74119f4fde487dc1, b53a329..42e1a01): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 3 Minor. ⚠️ items resolved by the controller: the report holds the red and green lines; the mutation table is the spec's evidence (plan departure 2); the web gate is run by the controller before the menu (plan departure 4)."
- "Final review (a4fc92584de3223a2, 95d32ad..42e1a01): "Ready to merge? Yes"; 0 Critical, 0 Important, 2 Minor; every deferred minor triaged "no fix" before merge."

**Commits** (`git log --oneline --reverse 95d32ad..b0dcc6b^2`, oldest first):

| Commit | Subject |
|---|---|
| e36a242 | docs(spec): slice 46, the SERP sweep counts waiting SERP jobs against the budget |
| e3352df | docs(spec): slice 46 review fixes: corrected facts, R1's race (R3) |
| 1a128e5 | docs(spec): slice 46 names both steps that close the race (R4) |
| b53a329 | docs(plan): slice 46, the SERP sweep budget |
| 42e1a01 | fix(worker): the SERP sweep counts waiting SERP jobs against the budget |

## 2. Live check

None (spec, "Live check"): reproducing an over-queued sweep on dev would need made-up data. No migration; dev is not touched.

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim:

> Ruling: R1. Decided: the waiting-job count runs before budget_fits takes the org's advisory lock, and a "Run audit now" press (which takes no lock) committed in that gap is not counted; a ponytail comment names this and the upgrade (lock first). Found by: the controller, writing the design. Why: process_job re-checks the budget when it claims the job, so a missed job costs at most one budget failure, as on main. Cost if wrong: in that rare race one extra job can be queued past the budget and fail at claim time. How named: in chat in the approved design, 2026-10-07.

> Ruling: R2. Decided: no mutant covers "another org's waiting jobs are not counted"; the count runs in the org's tenant session, so row-level security, not the sweep's code, excludes them, and the test test_other_jobs_take_no_serp_budget_room[other-org] pins the behaviour. Found by: the controller, running the proof. Why: a mutant would have to disable row-level security, outside this change. Cost if wrong: none to behaviour; the test still fails if the count ever ran outside the tenant session. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R3. Decided: the spec review's other findings are fixed: the ponytail comment and R1 now say a "Run audit now" press committed after the count is missed because the API takes no lock, and name the upgrade as making the press take the org's lock (Important 1; R1 is corrected below); the Context gives the corrected facts and states that the sweep becomes stricter than the claim check (Important 2); the README row no longer says "cannot" (Minor 1); the mutation table prints full test names (Minor 2); the spec names the other overlap: a job that finishes between the count and the budget read is counted twice, which fails closed (Minor 3). Minor 4 (the new _budget helper repeats the nested budget() of an existing test) is left: the existing test stays unchanged. Found by: the spec reviewer (Opus 5.5), 2026-10-07. Why: wrong or overstated statements; changing an existing test is outside this slice. Cost if wrong: none to behaviour; seven repeated test lines. How named: in chat, 2026-10-07, after the review.

> Ruling: R4. Decided: N1 is fixed: the ponytail comment and the Design bullet name both steps that close the race (the press takes the org's lock, and the sweep takes it before counting); N2 is left, since the Correction to R1 follows the quote. Found by: the spec re-reviewer (Opus 5.5), 2026-10-07. Why: N1 was an incomplete statement of mine in a code comment; N2 reads correctly as written. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the re-review.

> Ruling: R5. Decided: no final fix wave. Minor 1 (the spec's "Deferred minors: None yet." is stale, since spec-review Minor 4 was deferred before the spec's last commit) is fixed by the post-merge docs commit, which lists the deferred minors in the spec; Minor 2 (a second worker process running the sweep would race the same way as a press) is deferred: the deployment runs a single worker, and the upgrade the comment names (lock before counting) covers it too. Found by: the final reviewer (Opus 5.5), 2026-10-07. Why: "Ready to merge? Yes" with no Critical or Important finding. Cost if wrong: if workers are ever scaled out, two sweeps could each queue past the budget, caught at claim time. How named: in chat, 2026-10-07, at the finishing menu.

The corrections, verbatim:

> Correction to R1 (2026-10-07, from the spec review): the race is a press committed at any time after the waiting-job count, not only before the budget lock, because the API press takes no lock; "lock first" would not close it.

> Correction to R1 (2026-10-07, from the spec re-review): closing the race needs both the press taking the org's lock and the sweep taking that lock before it counts; the press taking the lock alone still leaves a gap.

Every `minor (deferred)` line in the ledger, verbatim:

- "minor (deferred): spec review minor 4, the new _budget test helper repeats the nested budget() in test_the_sweep_skips_a_brand_while_the_budget_has_no_room (R3)."
- "Task 1: minor (deferred): `(waiting or 0)` guards a count that is never NULL; it satisfies the Optional type of s.scalar (plan-mandated)."
- "Task 1: minor (deferred): the gate's 2 warnings are the known third-party Starlette/anyio deprecation warnings, present on main."
- "Task 1: minor (deferred): the count has no org_id filter; row-level security scopes it, and the other-org test pins that (R2)."
- "minor (deferred): final review minor 2, a second worker process running the sweep would race the same way as a press; the deployment runs one worker (R5)."
