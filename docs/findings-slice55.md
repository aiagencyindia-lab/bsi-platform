# Slice 55 findings: the Brand SERP page says why the weekly sweep skips a brand

## 1. What was built

`GET /v1/brands/{id}/audits/serp` now returns two more fields on `SerpAuditsOut` (`apps/api/bsi_api/schemas.py`), filled in `latest_serp` (`apps/api/bsi_api/routers/audits.py`):

- `serp_configured: bool` is true when the API process's DataForSEO login and password are both set. This is the expression `queue_due_serp_audits()` tests before it reads `due_serp_audits()`.
- `failed_7d: int` counts failed `audit_serp` jobs for the brand created in the last 7 days. The count runs on the DB clock in the tenant session after `brand_or_404`, mirroring the last predicate of `due_serp_audits()` (migration 0024). The API returns the raw count.

The web app regenerated `openapi.json` and `schema.d.ts`. `serpSchedule(status, domains, configured, failed7d)` (`apps/web/src/lib/format.ts`) gains two lines, checked in this order: archived, no domain, not configured, three or more failures, weekly. The two new lines:

- "Not audited automatically: the SERP provider is not configured."
- "Not audited automatically: N audits failed in the last 7 days; the sweep tries again once fewer than 3 remain in that window."

The threshold `SERP_MAX_FAILURES = 3` lives in format.ts only. The Brand SERP page passes the two values from the `/audits/serp` response it already fetched.

This fixes two of the three cases the slice 47 spec left out of scope (the page still said "weekly" when credentials were missing or after three failures in 7 days). The third, an org budget with no room, is still not shown, and the flag describes the API process's settings, not the worker's when the two differ (both spec, Out of scope). No migration, no new route; the dev DB is not touched.
  - Note (2026-10-08, after slice 57, PR #114): the third case is now noted: with no budget room, the line adds that a due audit waits until there is room, except while the brand's own audit is queued or running (docs/findings-slice57.md §1). The settings limit stands.

Spec: docs/superpowers/specs/2026-10-08-slice55-serp-schedule-reasons-design.md (R1 entered in `a790162`, the version the user approved; R2–R7 added by these docs commits). Plan: docs/superpowers/plans/2026-10-08-slice55-serp-schedule-reasons.md (Tasks 1 and 2; R3 applied in `3dd90ff`). Merged via PR #110 (https://github.com/aiagencyindia-lab/bsi-platform/pull/110), main `08f8da5`.

**Code**:
- apps/api/bsi_api/schemas.py: the two fields.
- apps/api/bsi_api/routers/audits.py: the count and the configured flag.
- tests/integration/test_api_serp.py: three new tests; the empty-body test patches settings and expects both fields; backend 1753 → 1756.
- apps/web/openapi.json and apps/web/src/lib/schema.d.ts: generated.
- apps/web/src/lib/format.ts: `serpSchedule`.
- apps/web/src/lib/format.test.ts: the `serpSchedule` test grows to 9 cases; web stays at 76.
- apps/web/src/app/(app)/b/[id]/serp/page.tsx.

**User decisions**, as the ledger records them:
- "User decision (2026-10-08): "what next?" -> slice 47 weekly line chosen over the tiny-minors sweep, backlog work and stopping, after approaches written in chat."
- "User decision (2026-10-08): approach A (serp_configured flag + failed_7d count on the audits response) over B (count only) and C (one computed reason incl. budget), after approaches with trade-offs written in chat."
- "User decision (2026-10-08): Section 1 (API) approved as shown in chat; raw count returned, the 3-failure threshold stays in the web (the boolean alternative was offered and not chosen)."
- "User decision (2026-10-08): Section 2 (web) approved as shown in chat: precedence archived -> no domain -> not configured -> failures -> weekly; copy as written."
- "User decision (2026-10-08): Section 3 (tests, mutation table M1-M6) approved as shown in chat; a page-render test was offered and not chosen."
- "User decision (2026-10-08): Section 4 approved as shown in chat: architectural path, no live check, dev untouched, findings docs controller-written on the session model as a STANDING RULE (to be recorded in memory)."
- "User decision (2026-10-08): plan-mode plan (the spec draft) approved via ExitPlanMode."
- "User decision (2026-10-08 03:21 UTC): I1 copy (a), interpolate the count and the threshold: 'Not audited automatically: <N> audits failed in the last 7 days; the sweep tries again once fewer than 3 remain in that window.', re-asked because the fact behind the Section 2 approval was wrong; over (b) static wording and (c) keep."
- "User decision (2026-10-08 03:31 UTC): 'go ahead' on the spec confirmed with one question as 'Approve, write plan' (spec at a790162)."
- "User decision (2026-10-08 03:31 UTC): the plan draft (Tasks 1-2, M1-M8) approved via ExitPlanMode; the scratchpad proof, generated blocks and the docs/superpowers/plans copy follow."
- "User decision (2026-10-08 03:44 UTC): execution 'Subagent-Driven' over inline."
- "User decision (2026-10-08 03:47 UTC): session model switched to Opus 5.5 by the user's /model command."
- "User decision (2026-10-08 08:08 UTC): 'Push and create a Pull Request then ci check and merge' (finishing option 2, plus an explicit instruction to check CI and merge without a separate merge question)."

**Results** (quoted from the ledger):
- "Task 1: implementer DONE_WITH_CONCERNS 2026-10-08 03:47 UTC, commit f4e056c (5 files, +149/-5): red '4 failed, 4 passed, 2 warnings' (each AttributeError get_settings); green '8 passed, 2 warnings'; M1 1 failed, M2 2 failed, M3 1 failed, M4 1 failed, M7 1 failed, M8 1 failed (each '... 7 passed' or '6 passed'); npm run gen: openapi.json +11/-1, schema.d.ts +4; ruff '104 files already formatted', 'All checks passed!'; mypy 'no issues found in 31 source files'."
- "Task 2: implementer DONE_WITH_CONCERNS 2026-10-08 03:50 UTC, commit 78eff0e (3 files): red '1 failed, 29 passed (30)' with TS2554 in typecheck; green '30 passed (30)', typecheck clean; M5 and M6 each fail the serpSchedule test; web gate: typecheck and lint exit 0, 'Tests 76 passed (76)', build 'Compiled successfully', gen:check exit 0 no diff."
- "Controller web gate 2026-10-08 03:52 UTC on 78eff0e: npm run gate exit 0: typecheck, lint pass; 'Test Files 8 passed (8)', 'Tests 76 passed (76)'; build 'Compiled successfully'; gen:check no diff; git status clean afterwards."
- "Controller backend gate 2026-10-08 03:57 UTC on 78eff0e: ruff format --check '182 files already formatted', ruff check 'All checks passed!', mypy 'no issues found in 31 source files'; pytest '1756 passed, 2 deselected, 2 warnings in 335.52s (0:05:35)' (main had 1753: +3 new tests); bsi_core.metrics coverage 100%."
- "Pushed and opened PR #110 2026-10-08 08:09 UTC on 78eff0e (body passed the banned-word grep). CI check started (one gh pr checks --watch, per the user's instruction)."
- "CI run 37747924971 2026-10-08 08:14 UTC: success on 78eff0e, gates pass 4m32s; '1756 passed, 2 deselected, 2 warnings in 155.75s (0:02:35)'; web 'Tests 76 passed (76)', 'Compiled successfully'."
- "PR #110 merged by the controller 2026-10-08 08:14 UTC per the user's 'Push and create a Pull Request then ci check and merge'; merge commit 08f8da5; main fast-forwarded; worktree bsi-wt/slice55 removed; branch deleted locally and on GitHub."

The implementers' concerns, two each, as the ledger records them: Task 1's green re-run overlapped a pytest of another project (invoice-processing, not `bsi_test`) and passed; Task 1 staged the implemented file before its mutants so `git checkout --` restored from the index (R4); Task 2 left a stray file `/tmp/null` holding typecheck output, outside the repo (left in place; the user is to be asked); Task 2 re-checked the lint and gen:check exit codes with `$?` after zsh printed an empty PIPESTATUS (both 0).

**Mutation table** (proof run, then each implementer's own run; every mutant caught):

| Mutant | Change | Failing test |
|---|---|---|
| M1 | count without `status == "failed"` | the 7-day count test |
| M2 | count without the 7-day window | the count test and the window boundary test |
| M3 | count without `kind == "audit_serp"` | the count test |
| M4 | `serp_configured` from the login only | the configured test (login set, password empty) |
| M5 | `>` in place of `>=` in the web threshold | `serpSchedule("active", 1, true, 3)` |
| M6 | failures branch before not-configured | `serpSchedule("active", 1, false, 3)` |
| M7 | count without the `brand_id` filter | the count test (a second brand of the same org) |
| M8 | `serp_configured` from the password only | the configured test (login empty, password set) |

**Reviews**, as the ledger records them:
- "Spec review 2026-10-08 03:20 UTC on 9f234be: 'Spec ready? No'; 1 Critical (C1: no serpSchedule case catches M6, needs ('active',1,false,3)), 4 Important (I1: failures copy wrong when failed_7d > 3 and the 'oldest failure ages out' claim is false; I2: test_get_is_empty_before_any_audit's serp_configured is not deterministic since Settings reads .env and conftest sets no DATAFORSEO_*; I3: no case or mutant for a dropped brand_id filter, org_b is hidden by RLS anyway, needs a same-org second brand and M7; I4: _job sets scheduled_slot not created_at, so every job's age needs an update(), distinct minutes per job, and the boundary job changes the expected count), 5 Minor"
- "Spec re-review 2026-10-08 03:23 UTC on a790162: 'Spec ready? Yes'; 10 of 10 findings ADDRESSED; R1 verbatim; templates match for 3 and 5; M1-M8 each caught; 0 new Critical/Important; 2 nits, 1 out-of-scope note."
- "Plan review 2026-10-08 03:42 UTC on 928912b: 'Ready to execute? No'; 0 Critical, 2 Important (I1 append block lacks the two leading blank lines; I2 no npm ci/uv sync step), 5 Minor"
- "Plan re-review 2026-10-08 03:43 UTC on 3dd90ff: 'Ready to execute? Yes'; 6 of 6 ADDRESSED, m5 noted only; 0 new findings"
- "Task 1: task review 2026-10-08 03:49 UTC: spec compliance pass"; "quality Approved; 0 Critical, 0 Important, 2 Minor."
- "Task 2: task review 2026-10-08 03:52 UTC: spec compliance pass"; "quality Approved, 0 findings."
- "Final whole-branch review 2026-10-08 03:53 UTC on 3dd90ff..78eff0e: 'Ready to merge? Yes'; 0 Critical, 0 Important, 2 Minor; count query matches 0024 exactly and runs under RLS after brand_or_404; serp_configured matches the worker's expression; no leak (deployment-wide boolean, already inferable from serp_not_configured); schedule line and serpStatus cannot contradict; all 5 deferred minors triaged stay-deferred."
- Docs review: see the docs PR.

**Commits** (`git log --oneline --reverse b077924..08f8da5^2`, oldest first):

| Commit | Subject |
|---|---|
| 9f234be | docs(spec): slice 55, the Brand SERP page says why the weekly sweep skips a brand |
| a790162 | docs(spec): slice 55 review fixes (R1) and the interpolated failures line |
| 928912b | docs(plan): slice 55, schedule reasons on the Brand SERP page |
| 3dd90ff | docs(plan): slice 55 review fixes (R3): blank lines before the appended tests, Step 0 installs, departures 6-7 |
| f4e056c | feat(api): serp_configured and failed_7d on the Brand SERP audits response |
| 78eff0e | feat(web): the Brand SERP schedule line says why the sweep skips the brand |

## 2. Live check

None: the spec names none (on dev, `serp_configured` would be true and Walkaroo's `failed_7d` 0, and any authenticated GET writes `api_key.last_used_at`). Dev is not touched.

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim:

> Ruling: R1. Decided: the spec review's other findings are fixed in the spec: a serpSchedule case ('active', 1, false, 3) -> not configured catches M6 (C1); test_get_is_empty_before_any_audit patches audits.get_settings and expects serp_configured true (I2); the count test adds failed audit_serp jobs on a second brand of the same org and a mutant M7 'count without the brand_id filter' (I3); every job's created_at is set by update() with a distinct minutes per job, the main case expects 3 and the window boundary is its own test expecting 1 of 2 jobs (I4); types.ts gains the fields through npm run gen, not by hand (m1); the boundary proves the window exists, not > versus >= (m2); an empty-login, set-password case expects false (m3); the (…, 5) case is written in full (m4); the test module imports the audits router (m5). Found by: the spec reviewer (Opus 5.5), 2026-10-08. Why: a test gap, two nondeterministic or ambiguous test designs, and loose wording of mine. Cost if wrong: none to behaviour. How named: quoted in chat. (2026-10-08 03:21 UTC)

> Ruling: R2. Decided: the spec re-review's two nits and one out-of-scope note need no spec change: the Section 3 web list uses shorthand ('weekly', 'not configured') for lines whose exact string appears once above it (nit 1); the plan, not the spec, lists which existing format.test.ts calls gain the two arguments, including the replaced ('archived', 2) call (nit 2); the boundary test sets created_at from Python time and compares against DB now(), so it stays deterministic while clock skew is under a minute (the Docker DB clock runs about 4 ms behind the host) (note). All three are deferred minors for the findings. Found by: the spec re-reviewer (Opus 5.5), 2026-10-08. Why: none changes behaviour or a test outcome. Cost if wrong: a plan that forgets the ('archived', 2) call fails typecheck, which the plan's scratch run catches. How named: quoted in chat. (2026-10-08 03:23 UTC)

> Ruling: R3. Decided: the plan review's findings are fixed in a second plan commit: the appended tests block is preceded by two blank lines, as the proof applied it (the generator had stripped them) (I1); a Step 0 installs the worktree's dependencies (uv sync; cd apps/web && npm ci) before Task 1 (I2); the openapi.json figure reads '+11 or +12 lines; report what you see' (m1); departures 6 (comments in SerpAuditsOut) and 7 (the variable is named settings, not s) are declared (m2, m3); departure 4 says eslint-neutral, not ruff/eslint-neutral (m4); the boundary test's Python-clock-versus-DB-clock margin is already a deferred minor from the spec re-review (m5). Found by: the plan reviewer (Opus 5.5), 2026-10-08. Why: a generator defect that would fail the format gate, a missing setup step, and undeclared departures of mine. Cost if wrong: none to behaviour. How named: quoted in chat. (2026-10-08 03:42 UTC)

> Ruling: R4. Decided: the plan's mutation steps restore a mutated file with `git checkout -- <file>`, which restores HEAD and would wipe the task's uncommitted implementation; the implementer's departure (stage the implemented file first, so checkout restores from the index) is accepted for Task 1, and Task 2's dispatch carries the same instruction (stage format.ts after Step 4, before the mutants). Found by: the Task 1 implementer (Opus 5.5), 2026-10-08, reported as a concern. Why: a plan defect of mine; the proof ran mutants from a snapshot, not git, so it never hit this. Cost if wrong: none to behaviour; a later implementer following the plan literally would lose work and have to reapply the blocks. How named: quoted in chat. (2026-10-08 03:47 UTC)

> Ruling: R5. Decided: no final fix wave: final review Minor 1 (`failed or 0` is redundant) is the existing Task 1 deferred minor; Minor 2 (the latest_serp docstring still names only job and audits) is deferred, since schemas.py comments explain both new fields; all five earlier deferred minors stay deferred as the final reviewer triaged them. Found by: the final reviewer (Opus 5.5), 2026-10-08. Why: 'Ready to merge? Yes' with no Critical or Important finding. Cost if wrong: a reader of the router's docstring alone misses the two fields. How named: quoted in chat. (2026-10-08 03:53 UTC)

> Ruling: R6. Decided: the docs review's findings are fixed in a second docs commit: findings 1 quotes the omitted user decision (the plan draft approved via ExitPlanMode) (Important 1); the plan's execution note limits the byte-identical claim to the files the blocks produce, says the generated files hold exactly the two properties, and says no other departure was reported rather than that none occurred (Important 2); findings 1 names both concerns of each implementer and says the user is to be asked about /tmp/null (Minor 3); the findings-slice47 note moves from between the R3 and R4 quotes to an indented note under the section 1 paragraph and says the credentials are as the API process sees them (Minor 4); findings 1 names the second out-of-scope item, a flag describing the worker's settings when they differ from the API's (Minor 5); the README row says two of the slice 47 out-of-scope cases (Minor 6); findings 1 quotes the PR-opened ledger line (Minor 7). Found by: the docs reviewer (Opus 5.5), 2026-10-08. Why: an omission and overstatements of mine. Cost if wrong: none to behaviour. How named: quoted in chat. (2026-10-08 08:18 UTC)

> Ruling: R7. Decided: the docs re-review's one Minor is fixed in a third docs commit: findings line 19 says the later rulings were added by these docs commits (R2 to R7, counting this one), and R7 is quoted in findings 3 and the spec with the README ranges moved to R1-R7; no further review, as the user chose 'Fix, stop' when offered a stop after two docs review rounds. Found by: the docs re-reviewer (Opus 5.5), 2026-10-08. Why: a stale range of mine once R6 entered the spec. Cost if wrong: none to behaviour; the fix commit is unreviewed and disclosed in the PR body. How named: quoted in chat. (2026-10-08 08:20 UTC)

There is no `Correction to R` line in the ledger.

Every `minor (deferred)` line in the ledger, verbatim:

- "minor (deferred): spec re-review nit 1, the Section 3 web list says 'asserting the exact strings' but uses shorthand for lines whose string appears once above (R2)."
  - Note (2026-10-12, slice 62): won't-fix: the slice 55 spec is historical and is not edited; the shorthand names strings spelled out once above in the same list, as the line says.
- "minor (deferred): spec re-review nit 2, Section 3 does not say that the existing format.test.ts calls at lines 281-283, including ('archived', 2), gain the two new arguments; the plan lists them (R2)."
  - Note (2026-10-12, slice 62): won't-fix: the slice 55 spec is historical and is not edited; as the line says, the plan lists those calls, and the plan is what was executed.
- "minor (deferred): spec re-review note, the window boundary test sets created_at from Python's datetime.now(UTC) and compares against DB now(); deterministic while clock skew is under a minute (R2)."
  - Note (2026-10-11, after slice 60, PR #120): fixed: `_audit` and `_aged` in test_api_serp.py write `func.now() - ago`, so this test and every serp_due test use the DB clock (docs/findings-slice60.md §1).
- "Task 1: minor (deferred): the Task 1 report describes Step 0's npm ci output ('its tail was the npm audit notice') instead of pasting it; every other summary line is pasted."
  - Note (2026-10-12, slice 62): closed: a process observation about a git-ignored report; nothing in the repo to change, and that workspace is no longer kept.
- "Task 1: minor (deferred): `failed or 0` in routers/audits.py is redundant, since count() never returns NULL; harmless, and it is the plan's text (plan departure 2)."
  - Note (2026-10-11, after slice 59, PR #118): fixed: the line is now `failed` (docs/findings-slice59.md §1).
- "Final review: minor (deferred): the latest_serp docstring (apps/api/bsi_api/routers/audits.py) still describes only job and audits; the two new fields are explained in schemas.py comments (R5)."
  - Note (2026-10-11, after slice 59, PR #118): fixed: the docstring names every field of the response (docs/findings-slice59.md §1).
