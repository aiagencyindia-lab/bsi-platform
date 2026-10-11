# Slice 59 findings: the behaviour minors (web and API)

## 1. What was built

The first of four slices from "fix every item" (2026-10-09): the behaviour bugs left in the deferred lists of slices 47–58.

- **POST /brands/{id}/domains** (apps/api/bsi_api/routers/brands.py): an archived brand gets `409 "Brand is archived"` ("Archived brands accept no new domains."); the duplicate check is one `INSERT … ON CONFLICT (brand_id, host) DO NOTHING RETURNING`, so two simultaneous submits of the same host give one 201 and one 409 instead of a 500; `DomainIn.host` uses the existing `Host` type, capped at 200 characters.
- **The SERP schedule facts** (packages/core/bsi_core/scheduling.py, apps/api/bsi_api/routers/audits.py): `budget_fits(..., *, lock=True)` takes the org's advisory lock only when asked, and the Brand SERP GET passes `lock=False`, so the page no longer waits on it (its answer is a best-effort snapshot); `serp_due(s, brand_id)` mirrors migration 0024's `due_serp_audits()` for one brand, and `latest_serp` returns it; the docstring names every field and `failed or 0` became `failed`.
- **The web** (apps/web/src): every form value used in an API path goes through `formSeg(form, name)`, which refuses a missing or non-text field instead of sending `"null"`, in 22 server actions across 10 files, and a source scan forbids the old `String(form.get(...))` pattern for path values (`…_id`, `type`, a field named by a variable); body fields still use `String(form.get(...))`; `addDomain` tells the two 409s apart, with a new note "Not added: the brand is archived."; `serpSchedule` says "Not audited automatically: the brand is not active." for a status other than active or archived, and shows the budget note only when the brand is due.
- **Test helpers**: the shared `_wait_until_blocked` (tests/integration/test_api_recommendations.py) clears Postgres's per-transaction activity snapshot before each poll and counts only this database; before, it passed by timing only.

No migration; the dev database is not touched. Backend 1777 → 1796; web 80 → 88.

This closes the deferred minors (line numbers as at main f1a8ad4, before these notes) at findings-slice54.md lines 77 and 79 (and its note at 80), findings-slice48.md 81, findings-slice47.md 83, findings-slice57.md 155 (slice 57's decision 4, reversed here) and 157 (slice 57's decision 2, reversed here), and findings-slice55.md 121 and 122; a dated note now sits under each (one note, under the existing note at 80, covers 54:79). Still open, and assigned to later slices: the test-hardening items (slice 60), the slice 56 probe script (61) and the docs-only items (62).

Spec: docs/superpowers/specs/2026-10-09-slice59-behaviour-minors-design.md (rulings R1–R8 and a correction to R6, as the user approved it at `5b35d10`). Plan: docs/superpowers/plans/2026-10-09-slice59-behaviour-minors.md (Tasks 1–3; R9 applied in `7635a6c`). R10 and R11 were made after the final review and R12 and R13 after the docs review; all four are quoted from the ledger below. Merged via PR #118 (https://github.com/aiagencyindia-lab/bsi-platform/pull/118), main `f1a8ad4`.

**User decisions**, as the ledger records them:
- "User decision (2026-10-09): "fix every item" (after the slice 58 summary listed the behaviour minors and the deferred list)."
- "User decision (2026-10-09): classification architectural, said first in chat; split into four slices, behaviour first (59 behaviour, 60 test hardening, 61 probe script, 62 docs sweep with the three won't-fix items), over two slices or one."
- "User decision (2026-10-09): the POST /domains race: A (INSERT ... ON CONFLICT (brand_id, host) DO NOTHING RETURNING, 409 when no row) over B (catch IntegrityError on flush) and C (a global IntegrityError handler)."
- "User decision (2026-10-09): the missing form id: A (a formSeg(form, name) helper at every call site, the source scan forbids the old pattern) over B (the serp actions only) and C (seg() refusing "null")."
- "User decision (2026-10-09): the 422 note: A (cap DomainIn.host at 200 like Host, keep one note) over B (per-cause notes) and C (reword only)."
- "User decision (2026-10-09): archived brands: A (POST /domains returns 409 like the audits POST) over B (leave it) and C (every write route)."
- "User decision (2026-10-09): other statuses: A (archived reads archived; any other non-active status reads "not active") over B (a DB check constraint, migration 0027) and C (leave it)."
- "User decision (2026-10-09): due brands only, reversing slice 57 decision 4: A (the API returns serp_due, a Python mirror of migration 0024 for one brand; the note only when due) over B (call due_serp_audits() from the API) and C (keep decision 4)."
- "User decision (2026-10-09): the lock, reversing slice 57 decision 2: A (the lock-free split, lock=False from the page) over B (SET LOCAL lock_timeout) and C (keep it)."
- "User decision (2026-10-09): Sections 1, 2, 3 and 4 approved as shown in chat."
- "User decision (2026-10-09): spec 5b35d10 approved ("go ahead", then "Approve, write plan" over a third review and changes)."
- "User decision (2026-10-11): execution subagent-driven."
- "User decision (2026-10-11): finishing option 2 (push and create a PR). Pushed slice59-behaviour-minors at 0cf8b9b; PR opened against main (body checked: banned-word grep empty; rulings named as the spec R1-R8 + correction to R6, the plan R9, the ledger R10-R11)."
- "User decision (2026-10-11): "check ci then merge". PR #118 merged (merge commit in the next line's check); remote branch deleted (by the controller if gh left it); local branch kept (used by the bsi-wt/slice59 worktree)."
- "User decision (2026-10-11): after two docs review rounds, "Fix, re-review" over "Fix, stop" and "Stop now"."

**Results** (selected ledger lines, quoted; in the ledger only: the header lines — title, spec, branch and base, session model — the section headings, the dispatch lines, the pre-flight-scan lines and the workspace-kept line):
- "Task 1: implementer DONE (commit 4c96793; RED 3 failed, 16 passed; GREEN crud 19, recommendations 12, recommend 36, isolation 74 passed; M1-M3 killed as in the plan; openapi.json +1; ruff, mypy clean; no concerns)"
- "Task 1: cannot-verify resolved: the banned-word grep over git show -U0 4c96793 printed nothing (controller ran it); the trailer is the Opus 5.5 line; the pasted outputs match the plan's Expected lines."
- "Task 1: complete (commits 7635a6c..4c96793, review clean)"
- "Task 2: implementer DONE (commit a1d6513; RED 16 failed, 21 passed; GREEN 84 passed across 4 files (serp 23, budget 14); 12 mutants killed as in the plan; gen openapi +7 -2, schema.d.ts +9 -3; typecheck clean; vitest 80 passed (80); ruff, mypy clean; banned grep empty (controller re-ran it on the commit); trailer Opus 5.5 (controller checked); no concerns)"
- "Task 2: cannot-verify resolved: the banned-word grep over a1d6513 printed nothing and the trailer is the Opus 5.5 line (controller ran both); the RED/GREEN, mutation, typecheck and vitest outputs are the implementer's pasted lines, matching the plan's Expected lines."
- "Task 2: complete (commits 4c96793..a1d6513, review clean)"
- "Task 3: implementer DONE (commit a5a0b1b; RED Tests 10 failed | 78 passed (88); GREEN 88 passed (88); 7 mutants killed as in the plan; npm run gate clean (typecheck, lint, 88 passed, build, gen:check no diff); backend gate 184 files already formatted, All checks passed!, mypy no issues in 31 files, 1796 passed, 2 deselected, 2 warnings, coverage 100%; banned grep empty and trailer Opus 5.5 (controller checked); no concerns)"
- "Task 3: cannot-verify resolved: that "a queued audit hides the budget note" depends on serp_due is shown by mutant M16 (the page passing true for serp_due), which that test kills; the mutants' outcomes are the implementer's pasted Tests lines, matching the plan's."
- "Task 3: complete (commits a1d6513..a5a0b1b, review clean)"
- "Controller gates (2026-10-11) on a5a0b1b: backend ruff format (184 files left unchanged), ruff check All checks passed!, ruff format --check 184 files already formatted, mypy Success: no issues found in 31 source files, pytest 1796 passed, 2 deselected, 2 warnings in 176.46s, metrics coverage 100.00%; web npm run gate exit 0 (Test Files 9 passed (9), Tests 88 passed (88), Compiled successfully); git status clean. (Two pytest processes were running, both with cwd invoice-processing, another project.)"
- "Final review: fix wave DONE (commit 0cf8b9b; ruff, mypy clean; pytest test_budget.py + test_api_serp.py 37 passed; vitest page.test.tsx 4 passed; typecheck clean)"
- "Final review: complete (d7e97d3..0cf8b9b; 1 fix wave, 0 residual findings)"
- "Controller gates (2026-10-11) on 0cf8b9b: ruff format --check 184 files already formatted, ruff check All checks passed!, mypy Success: no issues found in 31 source files, pytest 1796 passed, 2 deselected, 2 warnings in 202.43s, metrics coverage 100.00%; web npm run gate exit 0 (Test Files 9 passed (9), Tests 88 passed (88), Compiled successfully); git status clean."
- "CI (2026-10-11) on 0cf8b9b: completed success (1796 passed, 2 deselected, 2 warnings; Tests 88 passed (88); Compiled successfully)."
- "Merge (2026-10-11): PR #118 merged as f1a8ad4; main fast-forwarded to f1a8ad4; gh pr merge left the remote branch (1 head), so the controller deleted it with git push --delete (0 heads after)."

**Mutation table**: the spec's 22 mutants (M1–M22), each killed in the proof and again in its task's own run; M17 ("budget_fits never locks") survived the whole backend suite until R5's test was added. The table with the failing tests is in the spec; its M15 and M16 rows name the test "a queued audit hides the budget note", which R10 renamed "a brand that is not due shows no budget note".

**Reviews**, as the ledger records them:
- "Review verdict (2026-10-09): spec review of dee2dc6 (Opus 5.5): Changes needed (1 important: stale findings line citations; 7 minors: action-file count, the scan missed String(form.get(k)), serp_due test gaps behind R6, SERP_KINDS shadowing, red-count wording, cut test ids, _wait_until_blocked counted other databases; 1 nit); fixed in 0e80589 (R8)."
- "Review verdict (2026-10-09): scoped spec re-review of dee2dc6..0e80589 (Opus 5.5): Approved with minors (7 of 8 addressed; Section 1 still cited old line numbers; R6 overclaimed; table order); fixed in 5b35d10 (correction to R6), unreviewed."
- "Review verdict (2026-10-09): plan review of 5717476 (Opus 5.5): Approved with minors (mechanics byte-identical; 4 minors: Task 1 leaves openapi.json stale, Task 2 leaves the web typecheck red, departure 2 wording, the live-check offer not named); fixed in 7635a6c (R9) after simulating Tasks 1 and 2 on a fresh copy."
- "Review verdict (2026-10-11): Task 1 task review of 7635a6c..4c96793 (Opus 5.5): Spec compliant; Task quality Approved; 0 critical, 0 important, 4 minor."
- "Review verdict (2026-10-11): Task 2 task review of 4c96793..a1d6513 (Opus 5.5): Spec compliant (serp_due checked predicate by predicate against migration 0024; every other budget caller keeps lock=True; generated files hold only the expected changes); Task quality Approved; 0 critical, 0 important, 4 minor."
- "Review verdict (2026-10-11): Task 3 task review of a1d6513..a5a0b1b (Opus 5.5): Spec compliant (every converted form field is always submitted by its page's form; the scan matches nothing legitimate; the 409 titles match brands.py); Task quality Approved; 0 critical, 0 important, 4 minor."
- "Review verdict (2026-10-11): final whole-branch review of d7e97d3..a5a0b1b (Opus 5.5): Ready to merge Yes; 0 critical, 0 important, 4 minor; every deferred minor triaged as not blocking."
- "Review verdict (2026-10-11): scoped re-review of the final fix wave a5a0b1b..0cf8b9b (Opus 5.5): All findings addressed (both ADDRESSED; no new breakage); out-of-scope note: page.test.tsx has lines over 80 columns, which is not a rule for TSX (ruff's limit is Python's; eslint passes; Prettier is not in the gate), so no action."
- "Review verdict (2026-10-11): docs review of 926fb71 (Opus 5.5): Approved with minors (all 63 quotes match the ledger; code claims true at f1a8ad4; 5 minors and a nit: the Results header omits the workspace-kept line and section headings; the README says nine minors closed where it is eight plus the archived-brand gap; the 48:81 note and §1 overstate formSeg and the scan (path values only); two unbacked claims (the other project's database, the live check 'not taken'); line numbers lack a reference point; the spec's M15/M16 rows name the test before R10's rename)."
- "Review verdict (2026-10-11): docs re-review of 383afeb (Opus 5.5): All findings addressed (all 6 ADDRESSED; both new quotes exact; R1-R12 range true; 2 nits: §1 names R10 and R11 as made after the final review but not R12; the line-number note sits mid-sentence)."
- Docs re-review of the R13 fix: see the docs PR.

**Commits** (`git log --oneline --reverse d7e97d3..f1a8ad4^2`, oldest first):

| Commit | Subject |
|---|---|
| aa3bc15 | docs(spec): slice 59 design, the behaviour minors |
| dee2dc6 | docs(spec): slice 59 mutation table names the failing web tests |
| 0e80589 | docs(spec): slice 59 review fixes (R8) |
| 5b35d10 | docs(spec): slice 59 re-review fixes (correction to R6, current line numbers, table order) |
| 5717476 | docs(plan): slice 59 implementation plan, generated from the proof |
| 7635a6c | docs(plan): slice 59 plan review fixes (R9) |
| 4c96793 | fix(api): POST /domains refuses archived brands, caps the host, and returns 409 on a concurrent duplicate |
| a1d6513 | feat: serp_due on the Brand SERP audits response; the page reads the budget without the org's lock |
| a5a0b1b | fix(web): formSeg for form ids, the archived and not-active lines, and the budget note only for a due brand |
| 0cf8b9b | docs: budget_fits' lock-free answer is a best-effort snapshot; the page test's name says what it checks (R10) |

## 2. Live check

None was run: the finishing menu's option 2 (push and create a PR) was chosen, and any dev API call writes `api_key.last_used_at`. Dev is not touched.

## 3. Rulings and deferred minors

Every `Ruling:` and `Correction to R` line in the ledger, verbatim (R1–R9 and the correction to R6 were copied into the ledger from the spec and plan when it was created):

> Ruling: R1. Decided: the race test holds the conflicting row in an uncommitted owner transaction and waits until the POST blocks on it (the pattern of test_concurrent_accept_returns_409_not_500), instead of the two barrier-released threads Section 1 described. Found by: the controller, writing the proof. Why: the holder makes the race happen every run; two threads only make it likely. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R2. Decided: the shared `_wait_until_blocked` helper in test_api_recommendations.py runs `SELECT pg_stat_clear_snapshot()` before each poll. Found by: the controller, the proof's red run. Why: Postgres caches pg_stat_activity for the rest of a transaction, so a request that connects after the first poll is never seen; the helper had passed by timing only. Cost if wrong: one line in a test helper outside this slice's files. How named: this spec and chat.

> Ruling: R3. Decided: `formSeg` covers every form value used in a path, not only `…_id` names: also `type` (reports) and label's `observation_id`, `entity_id` and redirect `brand_id`; the scan forbids `String(form.get("…_id"))`, `String(form.get("type"))` and `seg(String(`. Found by: the controller, reading the action files. Why: the same `String(null)` bug reaches the same paths through those names. Cost if wrong: a few more call sites than decision 3 named. How named: this spec and chat.

> Ruling: R4. Decided: the existing "already declared" action test now stubs the API's real 409 title, and a new test shows any other 409 is rethrown. Found by: the controller, the proof's green run (the old stub's untitled 409 is now rethrown by design). Why: the stub did not match what the API sends. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R5. Decided: a test that the default `budget_fits` waits for the org's lock is added. Found by: the controller, mutation M17 (never lock) surviving the whole backend suite. Why: this slice makes the lock optional, so nothing else would notice the writers losing it. Cost if wrong: one test. How named: this spec and chat.

> Ruling: R6. Decided: each `serp_due` case also asserts that `due_serp_audits()` returns the brand exactly when `serp_due` is true. Found by: the controller, writing the proof. Why: it ties the Python mirror to the SQL, so drift between them fails a test. Cost if wrong: none. How named: this spec and chat.

> Ruling: R7. Decided: actions.test.ts's `notFound` mock throws `NOT_FOUND`, as api.test.ts's does. Found by: the controller, writing the missing-id tests. Why: a `notFound` that returns would let `formSeg` fall through to the fetch. Cost if wrong: none. How named: this spec and chat.

> Ruling: R8. Decided: the spec review's findings are fixed in the proof and the spec: the docs follow-ups cite the findings lines as they are at main d7e97d3 (the slice 58 notes had moved every cited minor); the count is 22 server actions in 10 files; the scan also forbids `String(form.get(k))`, which label used; four serp_due cases cover the error filter, the distinct count and both 7-day windows (mutants M18 to M21); the constant is `SERP_KIND_COUNT = len(m.SERP_KINDS)`, not a second `SERP_KINDS`; `_wait_until_blocked` counts only this database's backends; the red counts name the three files with new tests; the mutation table gives full test ids; the race test drops a redundant `uuid.UUID(str(bid))`. Found by: the spec reviewer (Opus 5.5), 2026-10-09. Why: stale citations, wrong counts, a scan narrower than its claim, a test gap behind R6's claim, a shadowed name, and wording, all mine. Cost if wrong: none to behaviour. How named: this spec and chat.

> Correction to R6 (2026-10-09): the cases catch a predicate dropped or loosened (mutants M4 to M8 and M18 to M21), not every drift: they do not tell a running job from a queued one, a SERP_AUDIT_DAYS between 3 and 7, or a SERP_RETRY_DAYS of 1 or 2; boundary ages and a running-job case belong to slice 60 (test hardening).

> Ruling: R9. Decided: the plan review's four minors are fixed in a second plan commit: Task 1 runs `npm run gen` and commits `apps/web/openapi.json` (its host cap adds `"maxLength": 200`); Task 2's Expected reads +7 −2 for openapi.json against Task 1; the page test's fixture blocks move into Task 2 with a typecheck and a vitest run, so no commit leaves the web typecheck red; departure 2 says which test files each task's mutants run; departure 3 names the live-check offer as the controller's. Found by: the plan reviewer (Opus 5.5), 2026-10-09; the first two checked by simulating Task 1 alone and then Task 2 on a fresh copy. Why: a commit that would fail gen:check and one that would fail the web typecheck, and two loose departure lines, all mine. Cost if wrong: none to behaviour. How named: this plan and chat.

> Ruling: R10. Decided: one fix wave for final-review minors 1 and 2: budget_fits' docstring says the lock-free answer is a best-effort snapshot (a job finishing between its statements can be counted twice; workers record costs without the lock), instead of "can differ from a writer's only while that writer holds the lock"; page.test.tsx's "a queued audit hides the budget note" is renamed "a brand that is not due shows no budget note". Found by: the final reviewer (Opus 5.5), 2026-10-11; the docstring claim checked against the worker's unlocked cost write. Why: an overstated docstring and a test name that no longer describes what the test checks, both mine. Cost if wrong: two lines and one review round. How named: ledger and chat.

> Ruling: R11. Decided: final-review minor 3 (the 200-character cap refuses pasted URLs over 200 characters that used to normalize to a host, and host names of 201-253 characters) is accepted, not changed. Found by: the final reviewer (Opus 5.5), 2026-10-11. Why: the user chose the cap (decision 4); stored rows are unaffected, the refused note's advice still fits, and every other Host field already caps the same way. Cost if wrong: a user pasting a very long URL sees the refused note and must paste the bare domain. How named: ledger and chat.

> Ruling: R12. Decided: the docs review's findings are fixed in a second docs commit: the Results header also names the workspace-kept line and the section headings; the README row says the eight deferred behaviour minors and the archived-brand gap; the 48:81 note and §1 say every form value used in an API path goes through formSeg and the scan forbids the old pattern for path values; the database clause about the other project's pytest runs is cut; §2 says no live check was run and the finishing menu's option 2 was chosen; §1 gives its line numbers as at main f1a8ad4, before these notes; the mutation paragraph notes R10's rename of the test the spec's M15 and M16 rows name. Found by: the docs reviewer (Opus 5.5), 2026-10-11. Why: an omission, a miscount, three overstatements and two unbacked claims, all mine. Cost if wrong: none to behaviour. How named: ledger and chat.

> Ruling: R13. Decided: the docs re-review's two nits are fixed in a third docs commit: §1 says R10 and R11 were made after the final review and R12 and R13 after the docs review, all quoted from the ledger; the line-number note moves to read "the deferred minors (line numbers as at main f1a8ad4, before these notes) at findings-slice54.md lines 77 …"; the README range becomes R1–R13. Found by: the docs re-reviewer (Opus 5.5), 2026-10-11. Why: an incomplete sentence and an awkward insertion, both mine. Cost if wrong: none to behaviour. How named: ledger and chat.

Every `minor (deferred)` line in the ledger, verbatim:

- "Spec: minor (deferred): API templates in the actions keep `${seg(id)}` after `formSeg`, so each value is checked twice; the existing path scan requires `seg()` in every template."
- "Task 1: minor (deferred): the archived-brand test checks the 409 title but not the detail "Archived brands accept no new domains.""
  - Note (2026-10-11, after slice 60, PR #120): fixed: the test asserts the detail (docs/findings-slice60.md §1).
- "Task 1: minor (deferred): the race test does not assert the thread is still alive after _wait_until_blocked, as test_recommend.py's sibling does."
  - Note (2026-10-11, after slice 60, PR #120): fixed: the race test asserts `t.is_alive()` after `wait_until_blocked`, as its siblings do (docs/findings-slice60.md §1).
- "Task 1: minor (deferred): if client.post raises in the race test's thread the test fails with KeyError 'response', and a failed blocked-assert leaves the thread running past holder.close()."
  - Note (2026-10-11, after slice 60, PR #120): fixed: `ThreadHandle.result()` re-raises the thread's own exception (mutant M4 shows `ZeroDivisionError`, not a KeyError), and the test closes the holder and joins the thread in a `finally` (docs/findings-slice60.md §1).
- "Task 1: minor (deferred): Host's max_length=200 applies to the raw input before _public_host normalizes it, as for every other Host field."
  - Note (2026-10-11, after slice 60, PR #120): fixed: `test_a_host_is_capped_at_200_characters` posts a 208-character scheme host (196 after normalization) and expects 422 on `host`, naming the cap as on the input as sent (docs/findings-slice60.md §1).
- "Task 2: minor (deferred): every pytest summary shows "2 warnings", the known Starlette/anyio warnings present on main; the report does not name them."
- "Task 2: minor (deferred): no serp_due case sits just inside or just outside the 1-day or 7-day windows, so a boundary slip on both the Python and SQL sides together would pass (slice 60 test hardening)."
  - Note (2026-10-11, after slice 60, PR #120): fixed: seven rows one minute inside and outside the 1-day and 7-day windows plus a running job 8 days old, on the DB clock (mutants M1, M2 and M3). A one-minute margin proves each window's length, not whether its edge is `>` or `>=` (docs/findings-slice60.md §1).
- "Task 2: minor (deferred): test_the_page_does_not_wait_on_the_orgs_budget_lock judges the no-wait with a 5-second join, and a GET that raises in the thread fails with KeyError 'response'."
  - Note (2026-10-11, after slice 60, PR #120): partly fixed: the KeyError half is fixed (`result()` re-raises the thread's own exception); the 5-second judgement stays by decision, since CI runs under load (spec Section 1, R5) (docs/findings-slice60.md §1).
- "Task 2: minor (deferred): test_budget.py imports the private _wait_until_blocked from test_api_recommendations (the plan's choice; matches the existing _job import from test_worker)."
  - Note (2026-10-11, after slice 60, PR #120): fixed: `wait_until_blocked` lives in tests/integration/threads.py and its four importers use it (docs/findings-slice60.md §1).
- "Task 3: minor (deferred): the backend gate's "2 warnings" are not named in the report (the known Starlette/anyio warnings present on main)."
- "Task 3: minor (deferred): the source scan is pinned to a parameter named form and double-quoted field names; fd.get(...), single quotes or `as string` would pass it."
  - Note (2026-10-11, after slice 60, PR #120): fixed for the three spellings it names: the scan accepts any receiver name, either quote style and the `as string` cast (mutant M9); other shapes (a call-expression receiver, a member-expression receiver such as `this.form`, a template-literal key, a trailing `!`) are a deferred minor in findings-slice60.md §3 (docs/findings-slice60.md §1).
- "Task 3: minor (deferred): formSeg logs "API form value missing" for a File field, which is present but not text."
  - Note (2026-10-11, after slice 60, PR #120): fixed: the log reads "API form value missing or not text", and the three tests that asserted the old text assert the new one (docs/findings-slice60.md §1).
- "Task 3: minor (deferred): seg(formSeg(...)) in tasks/actions.ts and seg(id) after formSeg elsewhere check each value twice (the spec's deferred minor; the path scan requires seg() in every template)."
- "Final review: minor (deferred): the docs follow-ups (dated notes, findings-slice59.md, README rows) are not on the branch; they belong to the post-merge docs PR."
