# Slice 44 findings: the Brand SERP drop alert (PRD F15)

## 1. What was built

A `serp_drop` alert, labelled "Brand SERP drop". The daily alert scan compares a brand's stored Brand SERP pages and fires when the brand's own-site organic results on two later pages are both below a baseline page, the three pages at least a day apart and with the same query and locale.

Spec: docs/superpowers/specs/2026-10-06-slice44-serp-drop-alert-design.md (rulings R1–R4 written before the merge, R5–R7 added by this docs commit). Plan: docs/superpowers/plans/2026-10-06-slice44-serp-drop-alert.md (Tasks 1–3). Merged via PR #90 (https://github.com/aiagencyindia-lab/bsi-platform/pull/90), main `b58f646`.

**Code**:
- migrations/versions/0025_serp_drop_alert.py: `ck_alert_type` gains `serp_drop`; the downgrade deletes `serp_drop` alerts, then restores the three old types.
- packages/core/bsi_core/models.py: `ALERT_TYPES` gains `serp_drop`; the `subject_key` comment names `<kind>:<country>:<language>`.
- packages/core/bsi_core/reports.py: `ALERT_LABEL["serp_drop"] = "Brand SERP drop"`.
- packages/core/bsi_core/alerts.py: `SERP_GAP = timedelta(days=1)`, `serp_copy`, `detect_serp_drop` (the fourth entry of `DETECTORS`), and updated module and `is_duplicate` docstrings.
- apps/web: `ALERT_KIND["serp_drop"]` and its test; the alerts page's explanation names "a single Google page", and a `serp_drop` row links to the Brand SERP page.
- tests/integration/test_alerts.py: 15 new tests (18 test items).

**User decisions**, as the ledger records them:
- "User decisions (brainstorming, 2026-10-06), each after approaches written in chat: own-site share drops (over page features, or page turnover); two pages in a row at least a day apart (over a confirming re-run, or averages); the own-site count falls (over a 15-point share drop, or the site leaving page one); a fourth detector in the daily scan (over a check after each job, or a separate feed). Sections 1, 2 and 3 approved, each shown in chat first."
- "User decision (not a ruling): 2026-10-06, after the spec review's M3 (a brand rename makes pages of different queries one series), the user chose "Same query only": only pages with the latest page's query are compared, like the locale rule."
- "User decision (not a ruling): 2026-10-06, re-asked after the spec review's I3 showed the facts behind it were wrong (every good page on dev has 0 own-site results; the earliest weekly alert for Walkaroo is 2026-10-26, not 2026-10-19), the user chose again "None this slice": no live check in slice 44."
- "User decision (not a ruling): 2026-10-06, after the re-review's Minor 2 (the title calls the middle page "the page before", which is not always the page directly before), the user chose "previous page compared": the title ends "(<n> of <m> on the previous page compared)", and the detector's docstring says "confirmed by an earlier page"."

**Results** (quoted from the ledger):
- "Task 1: implementer ae9e6ad519e1abe6c, commit 3279e70 (trailer Opus 5.5 checked); report: red 2 failed 32 passed (IntegrityError ck_alert_type; KeyError 'serp_drop'), green 34 passed, gate exit 0, gate-task1.txt 1730 passed, 2 deselected, 2 warnings, coverage 100%."
- "Task 2: implementer a604833a51713c66e, commit 621e804 (trailer Opus 5.5 checked); report: red 1 error (ImportError detect_serp_drop; the red run was repeated once to capture the error line, disclosed), green 50 passed, gate exit 0, gate-task2.txt 1746 passed, 2 deselected, 2 warnings, coverage 100%."
- "Task 3: implementer a68a6fc93ca6542d4, commit 01c8612 (trailer Opus 5.5 checked); report: vitest red 1 failed | 27 passed (28) on "ALERT_KIND labels every alert type", web gate exit 0, Tests 49 passed (49), Compiled successfully. Departure disclosed: staged the files and ran the grep before a commit command without its own git add; the same three files."
- "Controller gates on 01c8612: backend gate exit 0, 1746 passed, 2 deselected, 2 warnings in 289.12s (0:04:49), mypy Success; web gate exit 0, Tests  49 passed (49), Compiled successfully."
- "CI run 37514507785: success, 1746 passed, 2 deselected, 2 warnings in 144.70s (0:02:24); web Compiled successfully. PR #90 merged by the controller after the user said "go ahead" to "Should I merge PR #90?" (2026-10-07)."
- "Gates on main b58f646 after merge: backend 1746 passed, 2 deselected, 2 warnings in 247.60s (0:04:07); web Tests  49 passed (49)."

**Reviews**, as the ledger records them:
- "Spec review (ac4276b16901f2691, b47492a): 0 Critical, 3 Important, 7 Minor."
- "Spec re-review (ac4276b16901f2691, 0af3c70): "All findings addressed? Yes"; 3 new Minor."
- "Plan review (a8ce26d4916f0a951, dee54b0): "Ready to execute? Yes"; 0 Critical, 0 Important, 2 Minor."
- "Task 1: task review (a70bd55c332f4ad9e, 893fc26..3279e70): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 2 Minor. ⚠️ items resolved by the controller: the report holds the red and green lines; bsi_test reads 0025 and the dev DB bsi reads 0024 (alembic_version)."
- "Task 2: task review (a259cea5c95f8eab7, 3279e70..621e804): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 3 Minor. ⚠️ items resolved by the controller: the report holds the ImportError, "1 error" and "50 passed" lines; the mutant table is the spec's proof evidence, not re-run (plan departure 5)."
- "Task 3: task review (a1badcb174169eb3f, 621e804..01c8612): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 1 Minor. ⚠️ items resolved by the controller: the report holds the red run, the grep exit and the post-commit status; the build lists /b/[id]/serp."
- "Final review (a60f6db7e4fbc9d55, ae465d3..01c8612): "Ready to merge? Yes"; 0 Critical, 0 Important, 4 Minor; every deferred minor triaged "no fix" before merge."

**Commits** (`git log --oneline --reverse ae465d3..b58f646^2`, oldest first):

| Commit | Subject |
|---|---|
| b47492a | docs(spec): slice 44, the Brand SERP drop alert |
| 0af3c70 | docs(spec): slice 44 review fixes: same-query series, boundary tests, corrected dates (R3) |
| 2eda4fb | docs(spec): slice 44 title names the previous page compared; R4 |
| dee54b0 | docs(plan): slice 44, the Brand SERP drop alert |
| 893fc26 | docs(plan): slice 44 plan review fixes (R6) |
| 3279e70 | feat(alerts): the serp_drop alert type |
| 621e804 | feat(alerts): detect a Brand SERP drop in the daily scan |
| 01c8612 | feat(web): label the Brand SERP drop alert and link its page |

## 2. Live check

None in this slice (spec, "Live check"; the user's decision 6). No good page stored on dev has an own-site result, so none can be a baseline. With weekly pages only, the earliest real alert for Walkaroo is 2026-10-26, and only if the worker runs the weekly audits and Google shows walkaroo.in on a page from 2026-10-12 on. A check is a separate, later decision with its own approval, and it may show only "no alert".

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim:

> Ruling: R1. Decided: the red step is the whole test module failing at import (`ImportError: cannot import name 'detect_serp_drop'`), not each new test failing on its own; the per-rule red evidence is the mutation table, where each of 13 mutants fails at least one named test. Found by: the controller, running the proof. Why: the new tests import the new detector, so on main's code the module cannot load. Cost if wrong: the red step shows only that the code is missing, not that each test checks something; the mutants cover that. How named: in chat, 2026-10-06, after the proof run.

> Ruling: R2. Decided: the proof ran in a scratch copy of main's backend against the shared test database bsi_test, so the test session applied migration 0025 for real; afterwards the proof ran the migration down to 0024, up and down again through alembic, and read alembic_version (0024) and ck_alert_type. Found by: the controller, setting up the proof. Why: it exercises the migration file itself, as slice 43's R7 did. Cost if wrong: bsi_test left at 0025 would break test sessions on main until downgraded. How named: in chat, 2026-10-06, after the proof run.

> Ruling: R3. Decided: the spec review's other findings are fixed in the spec and the proof: the PRD section is F15, not F09, and the alert's window is its pages (I1); tests and mutants are added for the "fetched before `to`" filter, the exact one-day gap, the language part of the locale and a recovery followed by a new drop, and the table's claim is limited to what it covers (I2); the earliest-alert date and the dev facts are corrected (I3); the spec's diffs carry full hunks (M1); the module docstring, the `is_duplicate` docstring and the `subject_key` comment in models.py are updated (M2); "the page before them" is reworded as the baseline (M4); the scan test parses the stored time instead of comparing a string (M5); the bad-type assertion matches `ck_alert_type` (M6); "pairs" is defined and the two-page case moves to its own test (M7). Found by: the spec reviewer (Opus 5.5), 2026-10-06. Why: each is a wrong or incomplete statement or a test gap, not a design choice. Cost if wrong: none to behaviour beyond the added tests. How named: in chat, 2026-10-06, after the review.

> Ruling: R4. Decided: the re-review's other two Minors: R1's "13 mutants" gets a correction note (1); the mutation table is sorted by mutant number, and the alerts page's "daily over rolling windows" stays as it is, since the spec defines this alert's window as its run of pages (3). Found by: the spec re-reviewer (Opus 5.5), 2026-10-06. Why: a stale count and a cosmetic order; the page wording is still true. Cost if wrong: none to behaviour. How named: in chat, 2026-10-06, after the re-review.

> Ruling: R5. Decided: the plan was verified by applying Tasks 1 and 2 step by step to a fresh scratch copy of main's backend and running each step against bsi_test (Task 1 red 2 failed 32 passed, green 34 passed; Task 2 red 1 error, green 50 passed; finished files equal the proof's), then running migration 0025 down to 0024 by alembic. A first verification run aborted midway and left bsi_test at 0025, which made the next run's Task 1 red show 33 errors; the controller downgraded and re-ran. Task 3's vitest and web gate steps were not run before execution. Found by: the controller, verifying the plan. Why: the plan's code is generated from the proof, and each step's expected output is checked by running it. Cost if wrong: Task 3's red step could differ from the plan; the implementer reports it. How named: in chat, 2026-10-06, before the plan commit.

> Ruling: R6. Decided: both plan-review Minors are fixed: Task 1 Step 2 names the second failure as `KeyError: 'serp_drop'` in `test_every_alert_type_has_a_report_label` (the verification output shows it at line 359), and the plan quotes R5 instead of only naming it. Found by: the plan reviewer (Opus 5.5), 2026-10-06. Why: a wrong failure reason would mislead an implementer checking the red step; an unquoted ruling label points nowhere. Cost if wrong: none to behaviour. How named: in chat, 2026-10-06, after the plan review.

> Ruling: R7. Decided: no final fix wave. The final review's Minor 1 (the ledger's "After merge" date said 2026-10-19) is fixed in the ledger, which is not code; Minors 2–4 are deferred: no index on serp_audit.brand_id and every good page loaded per scan (2); only the newest page's locale per kind is judged, which matters only if MAX_SERP_LOCALES is raised (3); stored fetched_at uses a space rather than "T" (4). Found by: the final reviewer (Opus 5.5), 2026-10-07. Why: "Ready to merge? Yes" with no Critical or Important finding; 2 is about 100 pages a brand a year today, 3 has no effect at one locale, 4 parses with fromisoformat and was the spec's choice. Cost if wrong: slower daily scans once brands or pages grow; a second locale's drops missed if locales are raised without changing the loop; a webhook consumer needing strict ISO 8601. How named: in chat, 2026-10-07, at the finishing menu.

The correction, verbatim:

> Correction to R1 (2026-10-06, from the re-review): after the spec review's fixes there are 17 mutants, not 13; each fails at least one named test.

Every `minor (deferred)` line in the ledger, verbatim:

- "Task 1: minor (deferred): the gate's 2 warnings are the known third-party Starlette/anyio deprecation warnings, present on main."
- "Task 1: minor (deferred): test_the_alert_type_check_accepts_serp_drop asserts `_alert(...)`'s return value is truthy; the real check is that the insert does not raise."
- "Task 2: minor (deferred): the gate's 2 warnings are the known third-party Starlette/anyio deprecation warnings, present on main."
- "Task 2: minor (deferred): pages with the same fetched_at are ordered by id (a UUID), an arbitrary but stable pick; only same-timestamp pages are affected."
- "Task 3: minor (deferred): the report says +8/-1; the diff is +7/-1."
- "minor (deferred): final review minor 2, no index on serp_audit.brand_id and detect_serp_drop loads every good page of the brand per scan (R7)."
- "minor (deferred): final review minor 3, only the newest page's locale per kind is judged; revisit if MAX_SERP_LOCALES is raised (R7)."
- "minor (deferred): final review minor 4, stored detail fetched_at is "YYYY-MM-DD HH:MM:SS+00:00", not strict ISO 8601 (R7)."
