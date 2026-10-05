# Slice 43 findings: the weekly Brand SERP schedule (PRD F09)

## 1. What was built

The worker now queues a Brand SERP audit once a week for every active brand with a declared domain. Before this slice the audit ran only when the operator pressed "Run audit now". The "Brand SERP change" alert is slice 44.

Spec: docs/superpowers/specs/2026-10-06-slice43-weekly-serp-schedule-design.md (rulings R1–R6 written before the merge, R7–R10 added by this docs commit). Plan: docs/superpowers/plans/2026-10-06-slice43-weekly-serp-schedule.md (Tasks 1–3). Merged via PR #86 (https://github.com/aiagencyindia-lab/bsi-platform/pull/86), main `af2ec9c`.

**Code**:
- migrations/versions/0024_due_serp_audits.py: `due_serp_audits()`, a `SECURITY DEFINER` function returning `(brand_id, org_id)`. A brand is due when it is active, has a declared domain, lacks an error-free page for one of the two query kinds in 7 days, has no `audit_serp` job created in the last 24 hours, has no `audit_serp` job queued or running, and has fewer than 3 failed `audit_serp` jobs in 7 days.
- apps/workers/bsi_workers/worker.py: `queue_due_serp_audits()`, called once a minute from `main()` after the rival-crawl sweep. It returns 0 without DataForSEO credentials (R1), and skips a brand, creating no job, while `budget_fits(s, org_id, 0, extra_micros=SERP_JOB_MICROS)` says the org has no room.
- apps/web `/b/[id]/serp`: one muted sentence, "Audited automatically once a week."
- tests/integration/test_serp_audit.py: 17 new tests (20 test items).

**User decisions** (asked in chat, recorded in the ledger as decisions, not rulings):
- "User decision (not a ruling): 2026-10-06, after the controller found that a brand is created before its domains, the user chose "Require a domain": a fifth due condition, the brand has at least one declared domain."
- "User decision (not a ruling): 2026-10-06, after the spec review's finding 1 (a failure that repeats makes a brand due every day with no end), the user chose "Cap at 3 failures a week": a brand is not due once it has 3 failed audit_serp jobs in the last 7 days."
- "User decision (not a ruling): 2026-10-06, after the spec review's finding 2 (a budget failure is retried at the same time of day), the user chose "Check budget in the sweep": the sweep skips a brand, creating no job, when budget_fits() says the job's estimate does not fit."

**Results** (quoted from the ledger):
- "Task 1: implementer a97620975024bea4c, commit b069bd7; report: red 14 failed 11 passed (UndefinedFunction), green 25 passed, gate exit 0, gate-task1.txt 1722 passed, 2 deselected, 2 warnings, coverage 100%."
- "Task 2: implementer ade870839fa0afe1b, commit 9d30d14 (trailer Opus 5.5 checked); report: red 6 failed 25 passed (AttributeError), green 31 passed, gate exit 0, gate-task2.txt 1728 passed, 2 deselected, 2 warnings, coverage 100%."
- "Task 3: implementer a00a98821c7913e0b, commit 8c231d1; report: web gate exit 0, Tests 49 passed (49), Compiled successfully."
- "Controller gates on 8c231d1: backend gate exit 0, 1728 passed, 2 deselected, 2 warnings in 498.98s (0:08:18), mypy Success, coverage 100%; web gate exit 0, Tests  49 passed (49), Compiled successfully."
- "CI run 37375333423: success, 1728 passed, 2 deselected, 2 warnings in 157.90s (0:02:37); web Compiled successfully. PR #86 merged by the controller after the user chose "Merge, then docs PR" (2026-10-06)."
- "Gates on main af2ec9c after merge: backend 1728 passed, 2 deselected, 2 warnings in 533.14s (0:08:53); web Tests  49 passed (49)."

**Reviews**, as the ledger records them:
- "Plan review (aa8f10bf79af1addd, 9f7793a): "Ready to execute? Yes"; 0 Critical, 0 Important, 3 Minor."
- "Task 1: task review (aa2a29b8913e6364b, b909f82..b069bd7): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 3 Minor. ⚠️ item (red/green/gate from the report) resolved by the controller: the report holds the red and green last lines and the UndefinedFunction failure, and gate-task1.txt's tail reads 1722 passed, 2 deselected, 2 warnings, 100% coverage."
- "Task 2: task review (acdbe6a072d4b46c9, b069bd7..9d30d14): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 2 Minor. ⚠️ item (the sweep counts a brand whose enqueue_job hit an existing job in the same hour slot) resolved by the controller as not a gap: a job in the current hour's slot blocks the brand through condition 4 unless it was created over 24 hours before that slot, and the API's audit_serp route queues with the default slot (this hour); the only effect would be a log count."
- "Task 3: task review (a5c2ecd9bcc4f3d0c, 9d30d14..8c231d1): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 1 Minor. ⚠️ items resolved by the controller: the commit's trailer reads "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" (git log); the banned-word grep's exit is in the report, and the one added line has none of the words."
- "Final review (a9ae9f028735e746c, dbcb2df..8c231d1): "Ready to merge? Yes"; 0 Critical, 0 Important, 2 Minor; every deferred minor triaged "no fix" before merge. Its "could not check" (the owning role needs BYPASSRLS, or condition 3 sees no pages) was checked by the controller on dev: bsi_owner has rolbypassrls t (and is superuser); bsi_app is NOBYPASSRLS. Production GCP is not built (sub-project 9)."

**Commits** (`git log --oneline --reverse dbcb2df..af2ec9c^2`, oldest first):

| Commit | Subject |
|---|---|
| 956d436 | docs(spec): slice 43, the weekly Brand SERP schedule |
| c03c3c7 | docs(spec): slice 43 review fixes: failure cap, budget check in the sweep, test bodies |
| 3b5ed34 | docs(spec): slice 43 re-review minors N1-N7 (R6) |
| 9f7793a | docs(plan): slice 43, the weekly Brand SERP schedule |
| b909f82 | docs(plan): slice 43 commit trailer follows the session model (R9) |
| b069bd7 | feat(db): due_serp_audits() lists the brands due a SERP audit |
| 9d30d14 | feat(worker): queue the weekly Brand SERP audits |
| 8c231d1 | feat(web): the Brand SERP page says the audit is weekly |

## 2. Live check

Not run yet. It is asked for separately (spec, "Live check"): migrate dev to 0024 (ask first), call `queue_due_serp_audits()` once, then `process_job` once per queued job with a `serp_fetch` wrapper that prints only statuses, codes, costs, item counts and latency; the worker loop is never started. Expected, *inferred*: `BSOAgentTestBrand` `34db213a` is due and Walkaroo is not due until 2026-10-12; 1 job, 2 searches, about $0.004.

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim:

> Ruling: R1. Decided: queue_due_serp_audits() returns 0 without reading the due list when the DataForSEO login or password is empty. Found by: the controller, while reading run_serp_audit during brainstorming (a job with no credentials fails as serp_not_configured and writes no rows, so the brand stays due). Why: otherwise every active brand gets one serp_not_configured failed job a day, forever. Cost if wrong: a missing-credentials setup is silent in the job list; "Run audit now" still reports it. How named: in chat in the Section 2 design text, 2026-10-06, and approved with Section 2.

> Ruling: R2. Decided: three of the 15 new tests are parametrized over two values (job status failed/done; job status queued/running; missing login/password), so the suite gains 18 test items and the expected backend count is 1726, not the plan file's "1708 + 14". Found by: the controller, writing the scratch proof. Why: each value is a separate rule a mutant can break (M7 and M8 each fail exactly one of the two credential cases). Cost if wrong: none to behaviour; a count in the approved plan file is superseded. How named: in chat, 2026-10-06, after the proof run.

> Ruling: R3. Decided: the scratch proof installed due_serp_audits() in the shared test database bsi_test through a proof-only pytest plugin and dropped it at the end of each session; the count of functions of that name was read as 0 afterwards. Found by: the controller, setting up the proof. Why: tests/conftest.py applies the repo's migrations, and a scratch copy cannot add migration 0024 to them. Cost if wrong: a leftover function would make migration 0024's CREATE FUNCTION fail in the test session. How named: in chat, 2026-10-06, after the proof run.

> Ruling: R4. Decided: the spec review's findings 3, 4, 5 and 6 are fixed in the spec: the 16 test bodies are printed in the spec and the red run is stated to have run without the proof plugin (3); "a stale failure writes no rows" is corrected, since a job failed as stale can still write its rows when it finishes late (4); the sweep's docstring lists its real differences from the crawl sweep (5); the SQL comment and the facts say serp_audit has no index on brand_id and is scanned whole (6). Found by: the spec reviewer (Opus 5.5), 2026-10-06. Why: each is a wrong or uncheckable statement, not a design choice. Cost if wrong: none to behaviour; the docstring and SQL comment are text. How named: in chat, 2026-10-06, after the review.

> Ruling: R5. Decided: the spec review's findings 7, 8, 9 and 10 are left as they are and recorded in the spec: KINDS = 2 stays hard-coded in the migration with its comment (7); no tests are added for a manual audit through the route, locale, a later domain, the per-brand try/except or the main() wiring, and no mutants are added for the tests that have none (8); "Run audit now" pressed in a later hour than a queued scheduled job can create a second job, about $0.004 (9); a competitor declared after the first automatic audit is classed other until the next weekly audit (10). Found by: the spec reviewer (Opus 5.5), 2026-10-06. Why: 7 cannot import models from a migration; 8 matches how the two existing sweeps are tested; 9 and 10 are small, and 10 does not change the ownership share. Cost if wrong: a third query kind would need the migration's number changed by hand; a regression in the untested paths would not be caught; one extra audit's spend; a week of other where competitor was right. How named: in chat, 2026-10-06, after the review.

> Ruling: R6. Decided: the scoped re-review's seven minors (N1 to N7) are fixed in the spec and the proof: the sweep docstring says a job without credentials would fail up to three times a week, not once a day (N1); the KINDS sentence gives the real reason and remedy, a new migration and a change to run_serp_audit's query pair (N2); test_good_pages_for_both_queries_this_week_are_not_due writes pages that have a result, so test_a_good_page_with_no_results_counts differs from it (N3); the README row no longer says three times a week at most (N4); "Run audit now" stacking is stated for a queued or running job (N5); two consequences are added, that fixing the cause does not lift the cap and that an org whose budget is under the estimate is never audited automatically (N6); three failed manual audits must be in different hours to count as three (N7). The fix commit is not re-reviewed. Found by: the scoped re-reviewer (Opus 5.5), 2026-10-06. Why: each is an inaccurate or missing statement; none changes a rule the user chose. Cost if wrong: none to behaviour; one docstring and one test's fixture change. How named: in chat, 2026-10-06, after the re-review.

> Ruling: R7. Decided: the plan's steps are verified in a scratch copy of the repo's alembic.ini, migrations and tests, run with the repo's Python, so tests/conftest.py applies migration 0024 to the shared test database bsi_test for real; afterwards the controller downgrades bsi_test to 0023 by alembic and reads alembic_version and pg_proc to confirm. Found by: the controller, planning the plan's verification. Why: the spec's proof installed the function through a plugin and never ran the migration file; this runs its upgrade and its downgrade. Cost if wrong: bsi_test left at 0024 would make every test session on main fail to locate the revision until it is downgraded. How named: in chat, 2026-10-06, before the verification ran.

> Ruling: R8. Decided: the plan review's three minors are left: the Consumes lists of Tasks 1 and 2 name some helpers the task does not use and omit some it does (1); Task 3 has no git status check (2); the commit trailer stays "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" for every commit although the implementers run on Opus 5.5 (3). Found by: the plan reviewer (Opus 5.5), 2026-10-06. Why: 1 and 2 change nothing an implementer does, since every name is already in the file; for 3 the user's standing rule is that the trailer is whatever the latest attribution reminder names, and that is Fable 5.1. Cost if wrong: commits credit a model that did not write the code. How named: in chat, 2026-10-06, with the plan review's result.

> Ruling: R9. Decided: the commit trailer for slice 43's commits becomes "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; the plan's Global Constraints and its three commit messages are changed to it before execution, and the three earlier spec and plan commits keep their Fable 5.1 trailer. This supersedes part 3 of R8. Found by: the controller, when the attribution reminder changed to Opus 5.5 after the execution choice (2026-10-06). Why: the user's standing rule is that the trailer is whatever the latest attribution reminder names. Cost if wrong: the slice's commits credit a different model from the docs commits. How named: in chat, 2026-10-06, before Task 1. The plan edit is text-only (four lines) and is not re-reviewed; disclosed here and in chat.

> Ruling: R10. Decided: no final fix wave; the final review's two minors are deferred: one sweep checks each brand's budget against the same room, because a queued job spends nothing yet, so an org with several due brands can get more jobs queued than its budget fits, and the extra ones fail as budget at claim time and count toward the cap (1); the page sentence is untrue for a brand with no declared domain (2, already the spec's deferred minor). Found by: the final reviewer (Opus 5.5), 2026-10-06. Why: the review is "Ready to merge? Yes" with no Critical or Important finding; (1) spends nothing extra, since process_job re-checks the budget; (2) is a copy change to approved design text, which the user decides. Cost if wrong: on a tight budget a brand can lose a day and one of its three weekly attempts; a brand with no domain shows a sentence that does not apply to it. How named: in chat, 2026-10-06, at the finishing menu.

Made while writing these docs:

> Ruling: R11. Decided: the docs review's three minors are fixed: the findings say "17 new tests (20 test items)", the README's slice 43 spec row says R1–R10, and its plan row adds "with the changes made during execution". Found by: the docs reviewer (Opus 5.5, a8ccd65e1a09940c8), 2026-10-06. Why: each is a wrong or stale statement in the docs. Cost if wrong: none to behaviour. How named: in chat, 2026-10-06, before the fix commit.

The two corrections, verbatim:

> Correction to R2 and R4 (2026-10-06, after the proof was re-run with the failure cap and the sweep's budget check): there are 17 new tests, not R2's 15 or R4's 16; three are parametrized over two values, so the suite gains 20 test items and the expected backend count is 1728, not R2's 1726.

> Correction to R1 and R5 (2026-10-06, from the re-review): with the failure cap, a brand without credentials would fail up to three times a week, not R1's "one serp_not_configured failed job a day, forever"; and a migration can import the models (migrations/env.py does), so R5's reason for finding 7 is wrong: KINDS is a number because the function's text is fixed when the migration runs, and a third kind needs a new migration, not this number changed by hand.

Every `minor (deferred)` line in the ledger, verbatim:

- "minor (deferred): plan review minor 1, the Consumes lists of Tasks 1 and 2 do not match the names each task's tests use (R8)."
- "minor (deferred): plan review minor 2, Task 3 has no git status check (R8)."
- "Task 1: minor (deferred): the gate's 2 warnings are the known third-party Starlette/anyio deprecation warnings, present on main."
- "Task 1: minor (deferred): a NULL-status audit_serp job would neither block nor count as a failure; ck_job_status allows NULL, but enqueue_job always inserts audit_serp jobs as 'queued' and NULL is used by kind 'run' jobs, so no audit_serp job is NULL today."
- "Task 1: minor (deferred): _serp_jobs is unused until Task 2 (plan departure 3)."
- "Task 2: minor (deferred): the gate's 2 warnings are the known third-party Starlette/anyio deprecation warnings, present on main."
- "Task 2: minor (deferred): queued += 1 counts a brand whose enqueue_job hit an existing row in the same slot (on_conflict_do_nothing); log count only, and not reachable through the API's routes."
- "Task 3: minor (deferred): the sentence is untrue for a brand with no declared domain (already the spec's deferred minor)."
- "minor (deferred): final review minor 1, the sweep's budget check is per brand and does not count jobs queued earlier in the same sweep (R10)."
- "minor (deferred): final review minor 2, the page sentence is untrue for a brand with no declared domain (R10; the spec's deferred minor)."
