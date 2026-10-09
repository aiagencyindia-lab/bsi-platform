# Slice 57 findings: the Brand SERP page says when the budget has no room for the weekly audit

## 1. What was built

The weekly SERP sweep's budget check moved into one shared helper, and the audits API now returns its answer:

- `packages/core/bsi_core/scheduling.py` gains `SERP_JOB_MICROS = 40_000` (moved from the worker) and `serp_budget_fits(s, org_id)`. The helper counts the org's `audit_serp` jobs that are queued or running, reserves one 40,000-micro estimate for each plus one for the next job, and calls `budget_fits`, which fails closed outside the org's tenant session and takes the org's advisory transaction lock.
- `queue_due_serp_audits()` (apps/workers/bsi_workers/worker.py) calls the helper in place of its inline count and check, with the same meaning.
- `GET /v1/brands/{id}/audits/serp` returns `budget_room: bool` from the same helper, so the request takes the org's lock as the sweep does; `TENANT` commits, and the lock is released, before the response.

The web regenerated `openapi.json` and `schema.d.ts`. `serpSchedule` (apps/web/src/lib/format.ts) gains `budgetRoom` and an optional `jobStatus`; the budget is checked last, after archived, no domain, not configured and the 3-failure pause. With no room, and the brand's own audit neither queued nor running, the line reads:

- "Audited automatically once a week; today the daily budget has no room for a Brand SERP audit, so a due audit waits until there is room. The budget resets at midnight UTC."

The line does not say the brand is skipped: `budget_room` is computed whether or not the brand is due. While the brand's own audit is queued or running, `due_serp_audits()` excludes the brand, so the line stays "Audited automatically once a week." The page passes `budget_room` and `job?.status` from the response it already fetches.

This is the third case slice 55 left out of scope (the page read "weekly" while the sweep skipped a due brand for budget). No migration, no new route; the dev DB is not touched.

Spec: docs/superpowers/specs/2026-10-08-slice57-serp-budget-skip-design.md (rulings R1–R10 and a correction to R3, as the user approved it at `5a3295e`; R14–R17 added by this docs commit). Plan: docs/superpowers/plans/2026-10-08-slice57-serp-budget-skip.md (Tasks 1 and 2; R11–R13 applied in `a62b051`). Merged via PR #114 (https://github.com/aiagencyindia-lab/bsi-platform/pull/114), main `7101fcd`.

**Code**:
- packages/core/bsi_core/scheduling.py: `SERP_JOB_MICROS`, `serp_budget_fits`.
- apps/workers/bsi_workers/worker.py: imports both; the sweep calls the helper; the ponytail comment says "the press takes no lock".
- apps/api/bsi_api/schemas.py and apps/api/bsi_api/routers/audits.py: `budget_room`.
- tests/integration/test_api_serp.py: `test_get_reports_budget_room` (boundaries $0.04 and $0.03, then a queued job on another brand of the org at $0.04 and $0.08); the empty-body test expects `budget_room: True`; backend 1776 → 1777.
- apps/web/openapi.json and apps/web/src/lib/schema.d.ts: generated (+6 −1 and +2).
- apps/web/src/lib/format.ts and apps/web/src/lib/format.test.ts: `serpSchedule` and its cases; web stays at 76.
- apps/web/src/app/(app)/b/[id]/serp/page.tsx.

**User decisions**, as the ledger records them:
- "User decision (2026-10-08): classification bounded, said first in chat; full spec + plan + SDD process kept."
- "User decision (2026-10-08): approach A (budget_room boolean on the audits response; one shared serp_budget_fits() helper in bsi_core used by the sweep and the router; SERP_JOB_MICROS moves to bsi_core) over B (headroom and estimate numbers for the web to compare) and C (the web reads /v1/ops; misses the waiting-job margin)."
- "User decision (2026-10-08): Section 1 (backend) approved with option (i): the helper calls budget_fits, so the API request takes the org's advisory xact lock, over (ii) a lock-free split of budget_fits."
- "User decision (2026-10-08): Sections 2 (web) and 3 (tests) approved."
- "User decision (2026-10-08): switch to Opus 5.5 now for the proof, spec and everything after."
- "User decision (2026-10-08): finding 1 fixed by option 2 (keep budget_room; the web hides the line while the brand's own job is queued or running; copy reworded so it never claims a skip; schema comment corrected; one more test case) over option 1 (budget_room = not due or fits via due_serp_audits() in the API) and option 3 (both)."
- "User decision (2026-10-08): spec 5a3295e approved ("go ahead", then "Approve, write plan")."
- "User decision (2026-10-08): execution subagent-driven."
- "User decision (2026-10-08): run Task 2 in parallel with Task 1 ("deploy different agent for each task simultaneously"), option A (own worktree, vitest-only steps first, cherry-pick after Task 1) over B (sequential)."
- "User decision (2026-10-08): finishing option 2 (push and create a PR). Pushed slice57-serp-budget-skip at 2b70b15; PR #114 opened against main (body checked: banned-word grep empty; rulings named as the spec R1-R10 + correction, the plan R11-R13, the ledger R14-R17)."
- "User decision (2026-10-08): "check ci then merge". PR #114 merged as 7101fcd; remote branch deleted; local branch kept (used by the bsi-wt/slice57 worktree)."

**Results** (selected ledger lines, quoted; the dispatch, pre-flight-scan and workspace lines are in the ledger only):
- "Task 1: cannot-verify resolved: the exact user-visible line is Task 2's format.ts (checked in Task 2's review); the brand's own waiting job making budget_room False is handled by Task 2's jobStatus hide rule (spec decision 4, R8, R9). Both are Task 2 scope, not gaps in Task 1."
- "Task 2: cannot-verify resolved: the banned-word grep over git show -U0 2ce5478 printed nothing (controller ran it); typecheck, npm run gate and Step 7 pending in phase 2."
- "Task 1: implementer DONE (commit dcf8a19; RED 2 failed, 7 passed; GREEN 59 passed; M1-M6 killed as in the proof; gen +6 -1 / +2; ruff, mypy clean; no concerns)"
- "Task 2: phase 1 implementer DONE (commit aea40f6 on slice57-web; RED 1 failed, 29 passed (30); GREEN 30 passed (30); M7, M8, M10-M12 killed (1 failed, 75 passed (76)); M9, M13 survived (76 passed); typecheck, gate, Step 7 skipped per R14; concern: the failing test name per mutant was not recorded)"
- "Task 1: complete (commits a62b051..dcf8a19, review clean)"
- "Task 2: cherry-picked aea40f6 onto slice57-serp-budget-skip as 2ce5478 (same patch, checked by diff); phase 2 sent to the Task 2 implementer (typecheck, npm run gate, Step 7 full backend gate in the slice worktree; no new commit)"
- "Task 2: phase 2 implementer DONE (no new commit): typecheck no error; npm run gate exit 0 (lint no warnings, Tests 76 passed (76), Compiled successfully, gen:check no diff); full backend gate 1777 passed, 2 deselected, 2 warnings (known Starlette/anyio), metrics coverage 100.00%; pgrep empty before the run."
- "Task 2: complete (commits dcf8a19..2ce5478 on the slice branch, cherry-picked from aea40f6; review clean)"
- "Final review: fix wave DONE (commit 2b70b15; 59 passed, 2 warnings; ruff, mypy clean)"
- "Final review: complete (77da2e7..2b70b15; 1 fix wave, 0 residual findings)"
- "Controller gates (2026-10-08) on 2b70b15: backend ruff format (184 files left unchanged), ruff check All checks passed!, ruff format --check 184 files already formatted, mypy Success: no issues found in 31 source files, pytest 1777 passed, 2 deselected, 2 warnings in 206.21s, metrics coverage 100.00%; web npm run gate exit 0 (Test Files 8 passed (8), Tests 76 passed (76), Compiled successfully, gen:check no diff); git status clean."
- "CI (2026-10-08) on 2b70b15: completed success (1777 passed, 2 deselected, 2 warnings; Tests 76 passed (76); Compiled successfully)."
- "User decision (2026-10-08): "check ci then merge". PR #114 merged as 7101fcd; remote branch deleted; local branch kept (used by the bsi-wt/slice57 worktree)."
- "Correction to the merge line (2026-10-08): the remote branch was not deleted by gh pr merge (it stopped at the local-branch error); the controller deleted origin/slice57-serp-budget-skip with git push --delete, and ls-remote then showed 0 heads."

**How it ran**: Task 2 ran at the same time as Task 1, in a second worktree on a temporary branch, and its commit was cherry-picked onto the slice branch with the same patch (R14). The proof directory for the spec was rebuilt once, after the spec review (`proof57b-1791477789`).

**Mutation table** (the spec's proof; each implementer's own run matched it):

| Mutant | Change | Result |
|---|---|---|
| M1 | `latest_serp` returns `budget_room: True` | killed: test_get_reports_budget_room |
| M2 | waiting jobs not counted | killed: the API test and 3 sweep tests |
| M3 | the next job not counted | killed: the API test and 4 sweep tests |
| M4 | only running jobs wait | killed: the API test and 2 sweep tests |
| M5 | the helper reserves one observation | killed: the API test and 7 sweep tests |
| M6 | the sweep ignores the helper | killed: 4 sweep tests |
| M7 | the web drops the budget reason | killed: vitest |
| M8 | the web inverts the budget reason | killed: vitest |
| M9 | the page passes `true` for `budget_room` | survived (deferred, R3) |
| M10 | the web drops the hide rule | killed: vitest |
| M11 | the web hides only while queued | killed: vitest |
| M12 | the web hides only while running | killed: vitest |
| M13 | the page does not pass `job?.status` | survived (deferred, R3 and its correction) |

**Reviews**, as the ledger records them:
- "Review verdict (2026-10-08): spec review of 300b700: Changes needed (1 important: the budget line shows for brands the sweep is not skipping; 3 minors: worker ponytail comment, Limits lock wait, stale findings lines)."
- "Review verdict (2026-10-08): scoped spec re-review of 300b700..6fafce6: Approved with minors (all four findings resolved; 2 new minors: overstated hide reason, decision 4 wording)."
- "Review verdict (2026-10-08): plan review of 8515ac4: Approved with minors (3 minors: full backend gate not a step, worktree not named, R7 docs notes not in departures); fixed in a62b051."
- "Review verdict (2026-10-08): Task 1 task review of a62b051..dcf8a19: Spec compliant; Task quality Approved; 0 critical, 0 important, 2 minor."
- "Review verdict (2026-10-08): Task 2 phase 1 task review of a62b051..aea40f6: Spec compliant; Task quality Approved; 0 critical, 0 important, 2 minor."
- "Review verdict (2026-10-08): final whole-branch review of 77da2e7..2ce5478: Ready to merge Yes; 0 critical, 0 important, 3 minor; all 6 deferred minors triaged as not blocking."
- "Review verdict (2026-10-08): scoped re-review of the final fix wave 2ce5478..2b70b15: All findings addressed (R15 finding ADDRESSED; no new breakage; no out-of-scope observations)."
- "Review verdict (2026-10-08): docs review of 23d460c: Approved with minors (55 quotes match the ledger byte for byte; facts, notes, tables, links and banned-word grep pass; 2 minors: R17's 'above' points the wrong way in the spec; Results is a selection without saying so)."
- Docs re-review: see the docs PR.

**Commits** (`git log --oneline --reverse 77da2e7..7101fcd^2`, oldest first):

| Commit | Subject |
|---|---|
| 300b700 | docs(spec): slice 57 design, the Brand SERP page says when the sweep skips for budget |
| 6fafce6 | docs(spec): slice 57 review fixes, option 2 copy and hide rule (R4-R8) |
| 5a3295e | docs(spec): slice 57 re-review fixes (R9, R10) |
| 8515ac4 | docs(plan): slice 57 implementation plan, generated from the proof |
| a62b051 | docs(plan): slice 57 plan review fixes (R11-R13) |
| dcf8a19 | feat: serp_budget_fits in core; the sweep and the audits response share it |
| 2ce5478 | feat(web): the Brand SERP schedule line notes when the budget has no room |
| 2b70b15 | docs(core): serp_budget_fits' docstring names the page's budget note (R15) |

## 2. Live check

None: the spec names none, and any authenticated GET writes `api_key.last_used_at`. Dev is not touched.

## 3. Rulings and deferred minors

Every `Ruling:` and `Correction to R` line in the ledger, verbatim (R1–R13 and the correction to R3 were copied into the ledger from the spec and plan when it was created):

> Ruling: R1. Decided: the API test sets budgets at the boundaries ($0.04 True, $0.03 False, then with one queued audit_serp job on another brand of the org $0.04 False, $0.08 True) instead of the $0.05/$0.09 in the approved plan. Found by: the controller, writing the proof. Why: the plan's values also kill M1 to M5, but only boundary values pin the exact threshold (a SERP_JOB_MICROS of 45,000 passes at $0.05 and fails at $0.04), and the other-brand job shows the count is org-wide, as the sweep's is. Cost if wrong: one test's numbers. How named: this spec and chat.

> Ruling: R2. Decided: `latest_serp`'s docstring is left unchanged, against the approved plan's "update the docstring sentence". Found by: the controller, writing the proof. Why: its sentence is about the latest job showing failures that wrote no rows, including a claim-time budget failure, which is still true; the new field is documented on `SerpAuditsOut`. Cost if wrong: one docstring sentence. How named: this spec and chat.

> Ruling: R3. Decided: M9 (the page passing a constant instead of `budget_room`) is accepted and deferred, not covered by a new test. Found by: the controller, mutation M9. Why: no test renders the Brand SERP page; slices 47 and 55 left the same gap for the other arguments, and a page-render harness is its own slice. Cost if wrong: a regression in one argument of one call goes uncaught by the gate. How named: this spec, Deferred, and chat.

> Correction to R3 (2026-10-08): the second proof adds M13 (the page not passing `job?.status`), which also survives; it is deferred on the same grounds.

Note (2026-10-09, after slice 58, PR #116): the Brand SERP page now has a render test (docs/findings-slice58.md §1); its cases kill M9 and M13.

> Ruling: R4. Decided: the spec no longer says "the page's verdict is the sweep's"; the field is the sweep's own check, but the sweep applies it only to due brands. Found by: the spec reviewer (finding 1). Why: it overstated what the page shows. Cost if wrong: none; a sentence. How named: this spec and chat.

> Ruling: R5. Decided: the worker's ponytail comment says "(the press takes no lock)" instead of "(the API takes no lock)". Found by: the spec reviewer (finding 2). Why: the GET now takes the org's lock; only the "Run audit now" press does not. Cost if wrong: one comment. How named: this spec and chat.

> Ruling: R6. Decided: Limits says a page load can wait on the org's advisory lock, with `SET LOCAL lock_timeout` as the upgrade; no timeout is added. Found by: the spec reviewer (finding 3). Why: every holder today is a short budget check; a timeout would be code for a wait nobody has seen. Cost if wrong: a slow Brand SERP page while some future long holder runs. How named: this spec and chat.

> Ruling: R7. Decided: the docs PR adds a dated note under the findings-slice47.md and findings-slice55.md lines that say the budget case is not shown. Found by: the spec reviewer (finding 4). Why: those lines become stale with this slice. Cost if wrong: two stale lines. How named: this spec and chat.

> Ruling: R8. Decided: the hide rule is a sixth `serpSchedule` parameter, `jobStatus?: string | null`, given `job?.status` by the page, not a boolean the page computes. Found by: the controller, writing the second proof. Why: the rule then lives in the tested function (M10 to M12 are killed); the page only passes a field through, as it does the others. Cost if wrong: an optional sixth argument. How named: this spec and chat.

> Ruling: R9. Decided: the reason for leaving the line out while the brand's own audit is queued or running is that `due_serp_audits()` then excludes the brand, in Section 2 and the format.ts comment, instead of "that job is what fills the room". Found by: the spec re-reviewer (new minor 1). Why: other brands' waiting jobs can fill the room too; the exclusion is what makes the sweep check no budget. Cost if wrong: one sentence and one comment. How named: this spec and chat.

> Ruling: R10. Decided: decision 4 names option 2's content first, then the options it was chosen over. Found by: the spec re-reviewer (new minor 2). Why: the old order read as if the content described option 3. Cost if wrong: none; wording. How named: this spec and chat.

> Ruling: R11. Decided: the full backend gate is a plan step (Task 2 Step 7), with its command and the expected `1777 passed, 2 deselected`. Found by: the plan reviewer (minor 1). Why: departure 3 named it, but no step ran it, so a literal implementer would skip it. Cost if wrong: one extra full run. How named: this plan and chat.

> Ruling: R12. Decided: Step 0 says who creates the worktree, from which branch, and the exact command. Found by: the plan reviewer (minor 2). Why: the implementer could not tell which branch to commit on. Cost if wrong: one line. How named: this plan and chat.

> Ruling: R13. Decided: the departures list says the spec's R7 docs notes have no task here and are left to the docs PR. Found by: the plan reviewer (minor 3). Why: the list is meant to name every departure. Cost if wrong: none; a list item. How named: this plan and chat.

> Ruling: R14. Decided: Task 2 runs now in a second worktree /Users/vineet/Downloads/ADK/bsi-wt/slice57-web on a temporary branch slice57-web from a62b051; there it does Steps 1-3, Step 4 with vitest only, Step 5 (vitest) and commits with the plan's commit command, skipping typecheck, the web gate and Step 7; after Task 1 is committed and its review is clean, the controller cherry-picks the Task 2 commit onto slice57-serp-budget-skip and the Task 2 implementer runs Step 4's typecheck, Step 6's gate and Step 7 in the slice worktree; each task keeps its own review. Found by: the user's instruction to run the tasks simultaneously. Why: one worktree's index cannot serve two agents' staging and git checkout restores; Task 2's typecheck and gate need Task 1's generated schema.d.ts; and two pytest runs on bsi_test deadlock. Cost if wrong: one cherry-pick and a second dispatch; if the cherry-pick conflicted, Task 2 would be re-applied from its blocks on the slice branch. How named: ledger and chat.

> Ruling: R15. Decided: serp_budget_fits' docstring (scheduling.py:148-149) says "the Brand SERP page's budget note" instead of "the Brand SERP page's reason when the sweep skips a brand"; one fix dispatch, then a scoped re-review. Found by: the final reviewer (minor 1). Why: the page shows the note whether or not the brand is due (spec decision 4, R4); the sentence came from the first proof and overstates what the page says. Cost if wrong: one docstring line and one review round. How named: ledger and chat.

> Ruling: R16. Decided: the docs PR also adds a dated note to the docs/README.md findings-slice55 row ("budget room still not shown"), alongside R7's two findings notes. Found by: the final reviewer (minor 2). Why: that row goes stale with this slice, the same as the two lines R7 names. Cost if wrong: one README row. How named: ledger and chat.

> Ruling: R17. Decided: the test-settings minor above is deferred, not fixed. Found by: the final reviewer (minor 3). Why: no environment that runs the gate sets a budget under $0.04, and pinning the org budget in that test would widen a one-line fix wave into test changes. Cost if wrong: a red test on a developer machine with a tiny DAILY_BUDGET_USD, fixed by one line in the test. How named: ledger and chat.

> Ruling: R18. Decided: the docs review's two minors are fixed in a second docs commit: in the spec, a bracketed note after the verbatim R17 line says the minor it names is the last item under Deferred; in the findings, the Results list also quotes the two cannot-verify-resolved lines and says it leaves out the dispatch, pre-flight-scan and workspace lines. Found by: the docs reviewer (Opus 5.5), 2026-10-08. Why: a verbatim copy whose pointer no longer holds in its new place, and a selection of mine presented without saying so. Cost if wrong: none to behaviour. How named: ledger and chat.

Every `minor (deferred)` line in the ledger, verbatim:

- "Spec: minor (deferred): no test renders the Brand SERP page, so passing a constant for `budget_room` (M9) or leaving out `job?.status` (M13) passes the gate (R3)."
  - Note (2026-10-09, after slice 58, PR #116): fixed by the page render test (docs/findings-slice58.md §1).
- "Spec: minor (deferred): the note shows for a brand that is not due (audited this week) whenever the org's budget is full; it is true there but says nothing about that brand (decision 4)."
- "Task 1: minor (deferred): every pytest summary shows "2 warnings" (the known Starlette/anyio warnings, present on main and in the proof runs); not introduced by this slice."
- "Task 1: minor (deferred): the Brand SERP GET now takes pg_advisory_xact_lock with no timeout for the rest of its transaction; accepted in the spec (decision 2, R6, SET LOCAL lock_timeout as the upgrade)."
- "Task 2: minor (deferred): no serpSchedule case passes jobStatus = null explicitly (ck_job_status allows NULL; null is neither queued nor running, so the code handles it); the test is as the plan wrote it."
  - Note (2026-10-09, after slice 58, PR #116): fixed: format.test.ts has the `null` case (docs/findings-slice58.md §1).
- "Task 2: minor (deferred): the phase 1 report recorded only the Tests line (1 failed, 75 passed (76)) for each killed web mutant, not the failing test's name."
- "Final review: minor (deferred): test_get_is_empty_before_any_audit's budget_room True assertion reads scheduling.get_settings() (the .env default $2.00 budget); a local .env with DAILY_BUDGET_USD under 0.04 would turn it red; the worktree has no .env and CI uses defaults (same shape as slice 55's serp_configured case)."
