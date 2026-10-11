# Slice 60 findings: test hardening (the deferred test-only minors)

## 1. What was built

Slice 60 closes the deferred test-only minors from slices 49, 55, 57, 58 and 59, the second of the four "fix every item" slices (59 behaviour, 60 test hardening, 61 the slice 56 probe script, 62 the docs sweep). No production behaviour changed. Two production files changed in form only: `format.ts` exports the budget sentence as `BUDGET_NOTE` (the same text), and `api.ts` logs "API form value missing or not text" for a form field that is missing or not text.

By group (findings line numbers are as at main a026e65):

- **A, serp_due edges (59:126).** Seven new rows in `test_serp_due_agrees_with_due_serp_audits`, each asserted against the Python mirror and the SQL function: both kinds a minute inside and outside the week, a done job a minute inside and outside the day, a running job 8 days old, three failures a minute inside and outside the week.
- **B and C, thread helpers (59:122, 59:123, 59:127 in part, 59:128).** A new non-test module `tests/integration/threads.py` holds `wait_until_blocked` (moved from `test_api_recommendations.py`, now public) and `run_in_thread`, whose `result()` joins with a 5-second timeout and re-raises the thread's own exception. Five tests use it, each joins in a `finally`, and the importers no longer reach into a test module for a private name.
- **D (59:121, 59:124).** The archived 409's detail is asserted; the host cap is asserted to apply to the input as sent (a 208-character scheme host that normalizes to 196 gets 422 on `host`).
- **E (55:119, 57:163).** `_audit` and `_aged` write `func.now() - ago`, so the test timestamps and the comparisons inside `serp_due` and `due_serp_audits()` share one clock. `_configured` builds one `Settings` with `daily_budget_usd=2.0` and patches both `audits.get_settings` and `scheduling.get_settings`, so `budget_room` no longer reads the developer's `.env`.
- **F, the page test (58:119, 58:120, 58:121, 58:124, 58:125, 58:126, 58:127).** The cookie mock checks the cookie name, `BASE` comes from `API_URL`, `render()` checks the three URLs and the Bearer header on every case, `BUDGET_NOTE` replaces two copies of the sentence, `serp()` takes overrides, and three new cases pin an unconfigured provider, three failed audits, and the audit cards (with budget room on a due brand).
- **G and H (59:130, 59:131).** The formSeg scan accepts any receiver name, either quote style and the `as string` cast; the log text is changed and the three tests that asserted the old text assert the new one.

Three items closed without the change the spec first listed, or against an earlier note:

- **49:102** closes as already guarded: main's first path scan fails on a block comment holding an unclosed backtick, because its literal check needs the whole first argument to be one literal. Mutant M10 shows this on main and on the patched scan, so the planned comment strip was dropped (spec decision 5) and no code changed.
- **57:160** is moot: slice 59 (PR #118) replaced `serpSchedule`'s `jobStatus` parameter with `serp_due`, so the `null` case that slice 58 added is gone with it.
- **57:153** had a note saying slice 58's page test fixed it. It did not close the `budget_room` half: a constant `false` passed every page case until this slice's audit-cards case (M11). A correction is added under that note (spec decision 8, R3).

Also, spec R7 and its correction: a plan-review finding (wrong, as the re-review showed) led the spec and plan to add a second `loc` assertion the test already had. R7 was withdrawn with a dated correction in both documents and the code never carried it.

Counts: backend 1796 → 1803 (seven rows; every other backend change edits an existing test); the five changed backend files 104 → 111 collected and passing; web vitest 88 → 91 (three page cases). The mutants below killed what the spec said they would, and `DAILY_BUDGET_USD=0.01` fails main's `test_get_is_empty_before_any_audit` where the patched test passes: the slice's only red run.

Spec: docs/superpowers/specs/2026-10-11-slice60-test-hardening-design.md (commits c2255cf, 5361684, b8d743d; rulings R1–R7 and the correction to R7). Plan: docs/superpowers/plans/2026-10-11-slice60-test-hardening.md (commits d44e39a, 1b894d3, 4ad818e; its R7, the same withdrawn ruling, the correction to R7 and R8). R9 was made at execution and R10 at the docs review. Merged via PR #120 (https://github.com/aiagencyindia-lab/bsi-platform/pull/120), main `fe851aa`.

**Code**:
- tests/integration/threads.py: new.
- tests/integration/test_api_crud.py, test_api_recommendations.py, test_recommend.py, test_budget.py, test_api_serp.py: the helpers, the joins in `finally`, the new assertions and rows.
- apps/web/src/app/(app)/b/[id]/serp/page.test.tsx, apps/web/src/lib/api-paths.test.ts, api.test.ts, format.test.ts, apps/web/src/app/(app)/b/[id]/serp/actions.test.ts: the page test, the scan, the log assertions, the cookie mock, `BUDGET_NOTE`.
- apps/web/src/lib/format.ts (the exported constant) and apps/web/src/lib/api.ts (the log text): the only production files. 13 files, +355 −174.
- Backend 1796 → 1803, web 88 → 91.

**User decisions**, as the ledger records them:
- "User decision: scope, item H, approach 2, sections 1-6 and decisions 5-8 are recorded in the spec's "User decisions" list (1-8)."
- "User decision: spec approved, then "approved, write the plan" (the user's literal words), after the spec review rounds (commits c2255cf, 5361684, b8d743d)."
- "User decision: execution method "approved, subagent-driven" (the user's literal words), after the plan review (commits d44e39a, 1b894d3, 4ad818e)."
- "Finishing: User decision: finishing menu answered "2 PR" (the user's literal words) after the controller ran both gates in the worktree (backend 1803 passed, 2 deselected, 2 warnings, coverage 100%; web 91 passed, build, gen:check clean)."
- "Finishing: User decision: "check ci then merge" (the user's literal words) after PR #120 was opened."
- "User decision (2026-10-11, spec decision 1): Scope as listed above, including 57:160 and excluding 49:105/106 and 57:153. (The 57:160 moot finding came after this approval and was reported in Section 5 before its approval. 57:153 moved into scope by decision 8, after the spec review showed it was not already closed.)"
- "User decision (2026-10-11, spec decision 2): Item H included in slice 60, over pushing it to slice 62 or won't-fix."
- "User decision (2026-10-11, spec decision 3): Approach 2 (shared helpers for the two repeated shapes, then one edit per item), over patching each item in place and over a `locked_holder` fixture."
- "User decision (2026-10-11, spec decision 4): Sections 1 to 6 each approved with "yes" after their text was shown in chat."
- "User decision (2026-10-11, spec decision 5): After mutant M10: 49:102 dropped and closed as already guarded, over keeping a block-comment strip no mutant distinguishes."
- "User decision (2026-10-11, spec decision 6): After the proof: the budget lock test keeps the proof's shape without the `done` Event (R2), over restoring the Event as Section 1 had said."
- "User decision (2026-10-11, spec decision 7): After the spec review (finding 4): `signedIn()` in api.test.ts gets the same name-checking cookie mock as the page test, over scoping the 58:124 note to page.test.tsx."
- "User decision (2026-10-11, spec decision 8): After the spec re-review (finding 2): 57:153 counts as closed by this slice's audit-cards case (R3), over leaving it to slice 62; the fact behind decision 1 ("already closed by slice 58") was wrong."
- "Docs: User decision (2026-10-11): after two docs review rounds, "Fix, stop" over "Stop now" and "Fix, re-review" (the user's chosen option, from the three the controller offered)."

**Results** (selected ledger lines, quoted; in the ledger only: the header lines, the pre-flight scan, and the "Docs:" lines that record the docs commits):
- "Task 1: implementer (Opus 5.5, agent af90ca4b2c7d1c826) DONE_WITH_CONCERNS: commit abb57de (BASE 4ad818e). Report: task-1-report.md. Red `1 failed, 2 warnings` (budget_room False != True), green `1 passed`, five files `111 passed, 2 warnings`, ruff 185 files formatted / All checks passed / mypy 31 files clean. Controller checked: one commit, 6 files (+192 -135), trailer Opus 5.5, tree clean apart from .DS_Store."
- "Task 1: implementer concerns (observations, no action): M5's summary reads `1 failed, 2 warnings` where the brief's column says `1 failed`; for M1-M3 the pytest summary does not show which of the two assertions (API or SQL) failed."
- "Task 1: complete (commits 4ad818e..abb57de, review clean)"
- "Task 2: implementer (Opus 5.5, agent a8d60b8845f8817ce) DONE: commit ace7efe (BASE abb57de). Report: task-2-report.md. vitest `Tests  91 passed (91)`, typecheck/eslint/build clean, gen:check no diff, formSeg count 28, M6-M11 each fail the tests the brief names, full backend `1803 passed, 2 deselected, 2 warnings`, metrics coverage 100%. Process note from the implementer: a grep filter hid M6's Tests line in a batch; re-run alone gave `7 failed | 26 passed (33)`."
- "Task 2: complete (commits abb57de..ace7efe, review clean)"
- "Final review: no fix wave needed."
- "Finishing: PR #120 opened (https://github.com/aiagencyindia-lab/bsi-platform/pull/120), head slice60-test-hardening at ace7efe, base main a026e65. bind_pr refused: the session's checkout origin is another repository, so the PR is not bound to the PR bar. CI not checked (waiting for the user to say "check ci then merge"). Ledger and worktree kept until the docs PR merges."
- "Finishing: CI run 38160283117 on ace7efe: gates pass (4m58s); backend 1803 passed, 2 deselected, 2 warnings; web 91 passed; build compiled. PR #120 merged with a merge commit, main now fe851aa. Remote branch slice60-test-hardening already deleted (git ls-remote --heads origin printed nothing). Local main fast-forwarded. Worktree and ledger kept for the docs PR."

**Mutation table** (the spec's proof; the implementers' own runs matched it, and M6 to M11 were re-run by the Task 2 implementer):

| Mutant | Change | Result |
|---|---|---|
| M1 | `SERP_AUDIT_DAYS = 6` in the Python mirror (SQL keeps 7) | killed: both kinds a minute inside the week, three failures a minute inside the week (2 failed, 28 passed in test_api_serp.py) |
| M2 | `SERP_RETRY_DAYS = 2` in the Python mirror (SQL keeps 1) | killed: a done job a minute outside the day (1 failed, 29 passed) |
| M3 | `serp_due` drops the queued-or-running clause | killed: a queued job, a running job 8 days ago (2 failed, 28 passed) |
| M4 | the crud race test's thread runs `1 / 0` | the failure is `ZeroDivisionError: division by zero` at the test's own line, not KeyError 'response' (1 failed) |
| M5 | the Brand SERP GET passes `lock=True` to `serp_budget_fits` | killed: `AssertionError: the thread did not finish within 5.0 s` (1 failed) |
| M6 | `api()` reads cookie `bsi_key_x` | killed: all 7 page cases (7 failed); api.test.ts's 26 tests pass, see the spec's Section 4 |
| M11 | the page passes a constant `false` for `budget_room` | killed: each audit gets a card (1 failed, 6 passed); before R3 the same mutant passed all 7 |
| M7 | `serpSchedule` checks the budget before the failure pause | killed: three failed audits outrank the budget note (1 failed, 6 passed) |
| M8 | `serpSchedule` checks the budget before "not configured" | killed: an unconfigured provider outranks the budget note, three failed audits outrank the budget note (2 failed, 5 passed) |
| M9 | a server action adds `String(fd.get('brand_id'))` and `form.get("type") as string` | killed: server actions read path values with formSeg() (1 failed, 1 passed); main's scan passes the same plant |
| M10 | a server action adds `` /* see api(`/brands */ `` and a template whose `${id}` skips `seg()` | killed by test 1 on this scan and on main's (1 failed, 1 passed each): already guarded, hence decision 5 |

**Reviews**, as the ledger records them:
- "Review verdict: spec review round 1 (Opus 5.5): Request changes; one Important (budget_room constant false survived the page tests), five minors. Fixed in 5361684."
- "Review verdict: spec re-review (Opus 5.5): Approve with minors (R2 wording, decision 1 vs 57:153). Fixed in b8d743d."
- "Review verdict: plan review (Opus 5.5): Approve with minors, one Important (M4 row named the wrong frame). Fixed in 1b894d3."
- "Review verdict: plan re-review (Opus 5.5): Request changes on one Important, which was the reviewer's own wrong finding 4; R7 duplicated an assertion. Withdrawn by Correction to R7 in 4ad818e; the reviewer's other checks passed."
- "Task 1: Review verdict: task reviewer (Opus 5.5, agent a12d2e064df130d3f) Spec compliant; Task quality Approved; no Critical, no Important. One cannot-verify item (that test_get_is_empty_before_any_audit calls _configured) resolved by the controller with a grep of the worktree: the test body calls `_configured(monkeypatch)`."
- "Task 2: Review verdict: task reviewer (Opus 5.5, agent a059af60c7aaa76f2) Spec compliant; Task quality Approved; no Critical, no Important. Cannot-verify items: (1) the implementer's M9/M10 side notes about main's scan, which the controller's own proof had shown (main's formSeg scan passed a file planted with `String(fd.get('brand_id'))` and `form.get("type") as string`, and main's first scan failed on the block-comment plant); (2) gen:check left no diff, which the clean `git status` after the commit supports."
- "Final review: Review verdict: final whole-branch reviewer (Opus 5.5, agent afef97d7b3a517c05) over 4ad818e..ace7efe: Ready to merge Yes; no Critical, no Important. Compared every +/- line with the spec's diff: 529 lines each side, identical once sorted. Two minors (run_in_thread is a second public name for one constructor; a timed-out daemon thread keeps running on a path where the test already failed, the R6 trade). All six deferred minors triaged "fine to defer". The reviewer ran no gate (this repo's pytest was running)."
- "Docs: Review verdict: docs review of b4f0cb1 (Opus 5.5, agent a3df4cd4232d5543d): Changes needed; one Important (findings-slice60.md and the spec's Out of scope list named 57:155 and 57:158 as still open, but slice 59 closed both; findings-slice57.md lines 156 and 159 say so); five minors (the M10 cell's backslash inside a code span, "see Section 4" meant the spec's, the Results header named dispatch lines that do not exist, the plan section said both task reviews compared the diff with the spec's, the 59:130 note omitted the member-expression receiver). Counts, the commit table, the mutation table, the 21 note placements and all 45 quotes verified."
- "Docs: Review verdict: docs re-review of b4f0cb1..1fd5a7d (Opus 5.5, agent a3df4cd4232d5543d): Approve with minors; all six earlier findings fixed as worded (the reviewer re-checked findings-slice57.md lines 157 and 160 itself); the verbatim check passes both ways (46 quotes); one new minor: the Results header names one ledger-only "Docs:" line but the ledger has two unquoted ones."

**Commits** (`git log --oneline --reverse a026e65..fe851aa^2`, oldest first):

| Commit | Subject |
|---|---|
| c2255cf | docs(spec): slice 60 test hardening design |
| 5361684 | docs(spec): slice 60 spec review round 1 (R3-R6, decision 7) |
| b8d743d | docs(spec): slice 60 re-review minors (R2 wording, decision 8) |
| d44e39a | docs(plan): slice 60 test hardening implementation plan |
| 1b894d3 | docs(plan): slice 60 plan review round 1 (R7 loc assertion, R8 wording) |
| 4ad818e | docs(plan): withdraw R7 (duplicate loc assertion); Correction to R7 in spec and plan |
| abb57de | test(backend): shared thread helpers, serp_due edge rows on the DB clock, the missing assertions |
| ace7efe | test(web): the page test pins every schedule input and renders the cards; name-checking cookie mocks; a spelling-independent formSeg scan |

CI (2026-10-11): PR run 38160283117 on ace7efe completed success (backend 1803 passed, 2 deselected, 2 warnings; web 91 passed; build compiled). The push run on main after the merge was not checked.

## 2. Live check

None: nothing user-visible changed, and the slice spent nothing (no Gemini, no DataForSEO, no worker).

## 3. Rulings and deferred minors

Every `Ruling:` and `Correction to R` line in the ledger, verbatim (R1–R8 and the corrections were copied into the ledger from the spec and plan at execution; the plan's R7 and its correction are worded for the plan and are the same withdrawn ruling as the spec's):

> Ruling: R9. Decided: the final whole-branch review is dispatched on the code range 4ad818e..ace7efe (two commits, 13 files), with the merge-base package (a026e65..ace7efe, 173 KB, mostly the spec and plan) also written but not handed over. Why: the six docs commits were reviewed in four spec and plan review rounds, and the final reviewer reads the spec and plan itself. Cost if wrong: the final reviewer would not see the docs diff, which has its own reviews. How named: this ledger.

> Ruling: R1. Decided: `_job`'s `minutes` argument stays as it is; only `_audit` and `_aged` move to the DB clock. Found by: the controller, writing the proof. Why: Section 2's text said the `_job(minutes=...)` offsets would become timedeltas, but `minutes` sets `scheduled_slot`, which `serp_due` and `due_serp_audits()` never read; the offsets only keep the rows distinct. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R2. Decided: test_budget.py's lock test drops the `done` Event: `assert t.is_alive()` while blocked and, after release, the verdict from `t.result()` asserted True (the join moved into `finally` by R4). Found by: the controller, writing the proof; confirmed by the user (decision 6). Why: the Event duplicated `is_alive()`, and `result()` pins the verdict the old test never checked. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R3. Decided: the audit-cards case also asserts the plain weekly line, that the budget note is absent, the mapped `timeout` text and that the failed card has no "Ownership: 0 of 0" line; 57:153 moves from "already closed" to closed by this slice. Found by: the spec reviewer (Opus 5.5), 2026-10-11, findings 1 and 5. Why: the spec claimed 58:127 closed and 57:153 already closed, but no case pinned `budget_room` true on a brand that reaches the budget check, so a constant `false` passed all 7 page cases (reproduced); and Section 4 said the error branch was pinned when only "Failed: " was. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R4. Decided: the budget lock test and the no-wait test join in their `finally` blocks (`verdict = t.result()`; a second `t.result()` after the rollback). Found by: the spec reviewer, finding 2. Why: Section 1 said no thread outlives a test even when an assert fails, and those two tests did not do that. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R5. Decided: the dated note under 59:127 says the KeyError half is fixed and the 5-second judgement is kept by decision (Section 1), not fixed. Found by: the spec reviewer, finding 3. Why: the closure list claimed the whole item. Cost if wrong: none. How named: this spec and chat.

> Ruling: R6. Decided: the `result()`-in-`finally` shape stays, with Section 1 saying what is reported when both the assert and `result()` raise. Found by: the spec reviewer, finding 6. Why: the shape trades a clearer first message for a join that always happens; stating the trade is enough. Cost if wrong: a less direct failure message. How named: this spec and chat.

> Ruling: R7. Decided: the host-cap test's scheme post also asserts `errors[0]["loc"][-1] == "host"`, as Section 3 says; the diff above is regenerated from the proof with it (test_api_crud.py still 19 passed). Found by: the plan reviewer (Opus 5.5), 2026-10-11, finding 4. Why: Section 3 promised the `loc` assertion and the proof's diff had it only on the 201-character post. Cost if wrong: none to behaviour. How named: this spec, the plan and chat.

> Correction to R7 (2026-10-11): withdrawn. The plan re-review found that the proof's diff already asserted `loc` on the scheme post (main's existing `loc` line follows the 201-character post, and the new block was inserted before it), so R7 duplicated an assertion. The diff above is back to the form the user approved. The reviewer's finding 4 was wrong, and the controller repeated it without checking the proof first.

> Ruling: R7. Decided: the host-cap test's scheme post also asserts `errors[0]["loc"][-1] == "host"`, as the spec's Section 3 says; the proof, the spec's diff and Task 1's blocks were regenerated with it. Found by: the plan reviewer (Opus 5.5), 2026-10-11, finding 4. Why: the spec prose promised the `loc` assertion and the proof's diff had it only on the 201-character post. Cost if wrong: none to behaviour. How named: the spec, this plan and chat.

> Correction to R7 (2026-10-11): withdrawn. The plan re-review found that main already asserts `loc` after the 201-character post and the proof's block 4 inserted the scheme post before that line, so the scheme post was asserting `loc` all along; R7 added the same assertion a second time. The proof, the spec's diff and Task 1's blocks are back to their d44e39a form (one `loc` assertion after each 422). The reviewer's finding 4 was wrong, and the controller repeated it without checking the proof first.

> Ruling: R8. Decided: the plan review's other minors are fixed in a second plan commit: the M4 row names the real frames (the `wait_until_blocked` assertion first, then the ZeroDivisionError raised from `t.result()` in the `finally`, pointing at the mutated lambda line) and the `1 failed, 2 warnings` summary; M7 and M10 are given as fenced blocks with plain backticks; the Global Constraints line on generated files says `gen:check` runs inside the gate and must report no diff; Task 2 Step 2 gains the command that counts the 28 `formSeg(` sites. Found by: the plan reviewer (Opus 5.5), 2026-10-11, findings 1, 2, 3 and 5; finding 1 reproduced by the controller. Why: a wrong Expected line, two mutant edits an implementer could mistype, a constraint that contradicted a step, and a number no step produced, all mine. Cost if wrong: none to behaviour. How named: this plan and chat.

> Ruling: R10. Decided: the docs re-review's minor is fixed in a third docs commit: findings §1's Results header says the ledger-only lines are the header lines, the pre-flight scan and the "Docs:" lines that record the docs commits, and the findings quote the docs re-review verdict, the "Fix, stop" decision and this ruling; the README row says R1–R10. No further review, as the user chose "Fix, stop"; the PR body says this commit is unreviewed. Found by: the docs re-reviewer (Opus 5.5), 2026-10-11. Why: the header named one ledger-only line where the ledger had two, and the re-review's own verdict was not yet quoted. Cost if wrong: none to behaviour; the commit is unreviewed. How named: ledger and chat.

Every `minor (deferred)` line in the ledger, verbatim:

- "Task 1: minor (deferred): none carried. The reviewer's two minors are the known "2 warnings" (already out of scope, slice 62: 57:157, 59:125, 59:129) and the same exception being raised twice from `t.result()` in the no-wait test when the GET itself raises (accepted trade-off, spec R6)."
- "Task 2: minor (deferred): the formSeg scan's receiver is a bare `\w+`, so `String((await req.formData()).get("brand_id"))`, `String(this.form.get("brand_id"))`, a template-literal key and a trailing `!` are not matched (the spec scopes the scan to the four forms it lists)."
- "Task 2: minor (deferred): `signedIn()` in api.test.ts pins nothing yet (M6 passes its 26 tests); the spec says so (Section 4, decision 7)."
- "Task 2: minor (deferred): `audit()` in page.test.tsx defaults to owned 1 / organic 1 with `results: []`, so a future case using the default unchanged would render "Ownership: 1 of 1" with no rows."
- "Task 2: minor (deferred): the backend gate prints "2 warnings" (the known Starlette/anyio warnings; slice 62 per the spec's Out of scope)."

Not slice 60 deferred minors, and still open: the "2 warnings" (also at 57:157, 59:125 and 59:129), and 59:120 and 59:132 (`${seg(id)}` after `formSeg`): out of scope here, slice 62. The spec's Out of scope list also names 57:155 and 57:158, which slice 59 had already closed (the notes under those lines in findings-slice57.md say so); the spec carries a dated correction.
