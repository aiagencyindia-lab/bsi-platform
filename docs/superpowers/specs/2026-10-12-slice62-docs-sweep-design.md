# Slice 62 design: the docs sweep (closing the open deferred minors)

Classification: architectural, said first in chat on 2026-10-12, before the first question: a docs-only slice, but it spans eleven findings files and three won't-fix decisions, and this project gives every slice a spec and a plan. Session model Opus 5.5 throughout.

## Context

"Fix every item" (user, 2026-10-09) was split into four slices: 59 behaviour, 60 test hardening, 61 the slice 56 probe script (all merged; main be24258) and 62, this docs sweep, which the split said would also close the three items that cannot be checked from the repo as won't-fix.

An inventory at main be24258 (an exploration read of docs/findings-slice47.md to findings-slice61.md, spot-checked by the controller) found 92 lines containing "minor (deferred)": 14 are the ledger heading "Every `minor (deferred)` line in the ledger, verbatim:" and one (53:55) says there are none, leaving 77 minors, 47 with a closing dated note and 30 open:

| Kind | Count | Lines (as at main be24258) |
|---|---|---|
| Unverifiable | 3 | 48:78, 50:72, 51:80 |
| Docs wording | 7 | 54:79, 55:117, 55:118, 56:141, 56:152, 56:153, 56:154 |
| Process observations | 11 | 55:121, 57:158, 57:164, 58:125, 58:126, 59:129, 59:136, 59:142, 60:139, 60:143, 61:101 (five are the "2 warnings": 57:158, 59:129, 59:136, 60:139, 60:143) |
| Code | 2 | 59:120, 59:141 (the double `seg()` after `formSeg()`) |
| Test | 7 | 49:108, 49:109, 60:140, 60:141, 60:142, 61:102, 61:103 |

Two facts the inventory corrected: the first won't-fix item is 48:78, not 48:76 as the 2026-10-11 handoff said (line 76 is the ledger heading, already at main a026e65); and three later findings lines cite line numbers that dated notes have since moved (60:139 and 60:145 use numbers as at main a026e65; 61:105 as at main e2b2b8b).

User decisions (2026-10-12), with the approaches text shown in chat before each:
1. The seven test minors stay open, named as open test work for a later slice; slice 62 stays docs-only. Over folding them into slice 62 (a proof, mutants and a code PR) and over closing them as won't-fix.
2. The double `seg()` (59:120, 59:141): won't-fix, by design, over leaving them open for a later code slice.
3. The "2 warnings" (five minors): name both warnings and close as won't-fix, over two `filterwarnings` lines in pyproject.toml and over naming them and leaving them open.
4. Sections 1 to 3 each approved ("Yes, go on" for 1 and 2, "Yes, write the spec" for 3) after their text was shown in chat. Section 2's text said "16 minors"; the count is 13 (seven docs lines, five process observations and 59:142), corrected in chat before Section 3's approval.

The rule every note follows, as in earlier slices: a historical doc is never edited; a dated note goes on its own line directly under the minor, after any existing note, and a paragraph with stale line numbers gets a dated correction after it.

## Section 1 — The won't-fix closures (10 minors)

- Unverifiable (48:78, 50:72, 51:80): "won't-fix: what this line names (chat approvals, ledger quotes, or a count from an offline run) left no record in the repo to check against; the merged PR's CI run is the record of its gates."
- Double `seg()` (59:120; 59:141 adds "including `seg(formSeg(...))` in tasks/actions.ts"): "won't-fix, by design: `formSeg()` already calls `seg()`, and the second `seg()` in each API path template is deliberate defence in depth: it is cheap, returns an accepted value unchanged, and keeps the path scan a one-rule check (every `${}` in `api()` is one `seg()` call)."
- "2 warnings" (57:158, 59:129, 59:136, 60:143; 60:139 adds that its line numbers are as at main a026e65): the note names both upstream deprecations, copied from this session's pytest output: Starlette's "Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead" (from FastAPI's testclient.py) and anyio's "The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead" (from Starlette's testclient.py), and says removing them belongs to a dependency upgrade.

## Section 2 — The remaining closures (13 minors and 2 corrections)

- 54:79: closed, pointing at the note under findings-slice48 line 80 (2026-10-08, slice 54), which names the reversal and the user's approval of the slice 54 design; the chat approval itself cannot be checked (findings-slice48 line 78).
- 55:117 and 55:118: won't-fix; the slice 55 spec is historical and is not edited (117: the shorthand names strings spelled out once above; 118: the plan lists those calls and is what was executed).
- 56:141, 56:152 and 56:153: won't-fix; the slice 56 plan is historical and is not edited (141 records that M14 fails by a `JSONDecodeError` on the blank line; 152 and 153: R7 deferred them to slice 56's post-merge docs commit, and the line with R7 in findings-slice56 §3 is the record).
- 56:154: closed: findings-slice56.md exists since docs PR #113 (merge 77da2e7), so the config.py comment's citation resolves.
- 55:121, 57:164, 58:125, 58:126 and 61:101: closed as process observations about a git-ignored report; nothing in the repo to change, and that workspace is no longer kept.
- 59:142: done: findings-slice59.md, its dated notes and its README rows landed in docs PR #119 (merge a026e65).
- Corrections after findings-slice60 §3's open-list paragraph ("as at main a026e65") and findings-slice61 §3's closing line ("as at main e2b2b8b"), each pointing at findings-slice62.md for the current lines.
- The seven test minors get no note; findings-slice62.md names them as open.

## Section 3 — Testing and process

- No code changes, so no red run and no mutants. The proof is scripted: the notes are inserted by anchoring each on its minor's quoted text (each anchor asserted to occur once), and four checks run on the result: (1) a re-run of the inventory gives 77 minors with exactly 7 open, the seven test lines; (2) `diff -rq` against main touches only `docs/findings-slice*.md` (eleven files); (3) 25 lines are added (23 notes, 2 corrections); (4) the banned-word grep over added lines is empty.
- Two PRs, as usual: the slice PR with this spec, the plan and the 25 inserted lines; then the docs PR with findings-slice62.md, the README rows and the plan's execution notes, so the findings can quote the merge and CI lines.
- Both gates run before the finishing menu (no code changes, so the counts stay 1810 backend and 91 web); CI runs on each PR.

## The change

Generated from the proof (a scratchpad copy of main be24258's docs with the notes inserted), as a unified diff over the eleven findings files:

```diff
--- a/docs/findings-slice48.md
+++ b/docs/findings-slice48.md
@@ -76,6 +76,7 @@
 Every `minor (deferred)` line in the ledger, verbatim:
 
 - "minor (deferred): spec review minor 6, the classification line, the chat approvals and the ledger quotes cannot be checked from the repo (R2)."
+  - Note (2026-10-12, slice 62): won't-fix: what this line names (chat approvals, ledger quotes, or a count from an offline run) left no record in the repo to check against; the merged PR's CI run is the record of its gates.
 - "Task 1: minor (deferred): a host the pattern passes but the API refuses (an IP address, walkaroo., www.walkaroo) lands on the error page, not an inline message; the user chose this (browser pattern over catch-and-note)."
   - Note (2026-10-08, after slice 54, PR #108): fixed; a 422 or 409 from the add-domain post now redirects to the Brand SERP page with a note, reversing the browser-pattern decision above with the user's approval of the slice 54 design (docs/findings-slice54.md §1). Two simultaneous submits still reach the error page through the unique-constraint 500 (R2 above).
 - "Task 1: minor (deferred): a missing brand_id becomes the string "null" and posts to /brands/null/domains; the hidden field always sets it, and runSerpAudit has the same pattern."
--- a/docs/findings-slice50.md
+++ b/docs/findings-slice50.md
@@ -70,5 +70,6 @@
 Every `minor (deferred)` line in the ledger, verbatim:
 
 - "minor (deferred): spec review minor 5, the chat approvals and the backend count "1753 passed, 2 deselected" cannot be checked from the repo offline (R1)."
+  - Note (2026-10-12, slice 62): won't-fix: what this line names (chat approvals, ledger quotes, or a count from an offline run) left no record in the repo to check against; the merged PR's CI run is the record of its gates.
 - "Task 1: minor (deferred): the api long-path test checks the logged text's length (200) but not its content, so a wrong slice offset in the guard's log alone would pass; the seg long-value test checks the content through the shared shown() (plan-mandated)."
   - Note (2026-10-08, after slice 51, PR #104): fixed; the test now uses a path with a double quote and asserts the exact logged text (docs/findings-slice51.md §1).
--- a/docs/findings-slice51.md
+++ b/docs/findings-slice51.md
@@ -78,5 +78,6 @@
 Every `minor (deferred)` line in the ledger, verbatim:
 
 - "minor (deferred): spec review notes, the proof directory being written only by the controller, the chat approvals and the backend count cannot be checked from the repo offline (R2)."
+  - Note (2026-10-12, slice 62): won't-fix: what this line names (chat approvals, ledger quotes, or a count from an offline run) left no record in the repo to check against; the merged PR's CI run is the record of its gates.
 - "minor (deferred): final review minor 1, the long-path test's toHaveBeenCalledWith matches any console.error call, not call 0; expect(log).toHaveBeenCalledTimes(1) would pin it; the guard logs once today (R7)."
   - Note (2026-10-08, after slice 52, PR #106): fixed; the long-path test asserts `toHaveBeenCalledTimes(1)` before its `toHaveBeenCalledWith` (docs/findings-slice52.md §1).
--- a/docs/findings-slice54.md
+++ b/docs/findings-slice54.md
@@ -77,6 +77,7 @@
 - "Final review: minor (deferred): two simultaneous submits of the same host still give a 500 from the unique constraint and reach the error page (findings-slice48 R2); the domain is added anyway. The slice 54 findings must say so."
   - Note (2026-10-11, after slice 59, PR #118): fixed: a simultaneous duplicate now gets 409, through one INSERT … ON CONFLICT DO NOTHING (docs/findings-slice59.md §1).
 - "Final review: minor (deferred): this reverses the slice 48 user decision (browser pattern over catch-and-note, findings-slice48 lines 13 and 77, and line 5 says a refused host shows the error page); the slice 54 findings must name the reversal and the user decision that authorised it (the chat approval of the slice 54 design on 2026-10-08). The historical doc is not edited."
+  - Note (2026-10-12, slice 62): closed: the note under findings-slice48 line 80 (2026-10-08, slice 54) names the reversal and the user's approval of the slice 54 design; the chat approval itself cannot be checked from the repo (findings-slice48 line 78).
 - "Final review: minor (deferred): one note text covers every 422 cause (IP, no dot, whitespace-only after trim, over 200 characters); the copy names IPs specifically but is still correct advice for the rest."
   - Note (2026-10-08, docs review): "over 200 characters" is wrong; `DomainIn.host` (apps/api/bsi_api/routers/brands.py) has `min_length=3` and no upper cap, so a long host with a dot is accepted. The other causes stand.
   - Note (2026-10-11, after slice 59, PR #118): fixed: `DomainIn.host` is capped at 200 like the other host fields, so the one note covers every 422 the form can cause (docs/findings-slice59.md §1).
--- a/docs/findings-slice55.md
+++ b/docs/findings-slice55.md
@@ -115,10 +115,13 @@
 Every `minor (deferred)` line in the ledger, verbatim:
 
 - "minor (deferred): spec re-review nit 1, the Section 3 web list says 'asserting the exact strings' but uses shorthand for lines whose string appears once above (R2)."
+  - Note (2026-10-12, slice 62): won't-fix: the slice 55 spec is historical and is not edited; the shorthand names strings spelled out once above in the same list, as the line says.
 - "minor (deferred): spec re-review nit 2, Section 3 does not say that the existing format.test.ts calls at lines 281-283, including ('archived', 2), gain the two new arguments; the plan lists them (R2)."
+  - Note (2026-10-12, slice 62): won't-fix: the slice 55 spec is historical and is not edited; as the line says, the plan lists those calls, and the plan is what was executed.
 - "minor (deferred): spec re-review note, the window boundary test sets created_at from Python's datetime.now(UTC) and compares against DB now(); deterministic while clock skew is under a minute (R2)."
   - Note (2026-10-11, after slice 60, PR #120): fixed: `_audit` and `_aged` in test_api_serp.py write `func.now() - ago`, so this test and every serp_due test use the DB clock (docs/findings-slice60.md §1).
 - "Task 1: minor (deferred): the Task 1 report describes Step 0's npm ci output ('its tail was the npm audit notice') instead of pasting it; every other summary line is pasted."
+  - Note (2026-10-12, slice 62): closed: a process observation about a git-ignored report; nothing in the repo to change, and that workspace is no longer kept.
 - "Task 1: minor (deferred): `failed or 0` in routers/audits.py is redundant, since count() never returns NULL; harmless, and it is the plan's text (plan departure 2)."
   - Note (2026-10-11, after slice 59, PR #118): fixed: the line is now `failed` (docs/findings-slice59.md §1).
 - "Final review: minor (deferred): the latest_serp docstring (apps/api/bsi_api/routers/audits.py) still describes only job and audits; the two new fields are explained in schemas.py comments (R5)."
--- a/docs/findings-slice56.md
+++ b/docs/findings-slice56.md
@@ -139,6 +139,7 @@
 Every `minor (deferred)` line in the ledger, verbatim:
 
 - "minor (deferred): plan re-review N1, M14's proof cell does not say the mutant fails by a JSONDecodeError on the blank line (R6)."
+  - Note (2026-10-12, slice 62): won't-fix: the slice 56 plan is historical and is not edited; this line records what M14's cell leaves out (the mutant fails by a `JSONDecodeError` on the blank line).
 - "minor (deferred): plan re-review N2, the .get('kind', '') half of departure 10 is untested; a mutant reverting it to r['kind'] survives (R6)."
   - Note (2026-10-12, after slice 61, PR #122): fixed: `test_probe_costs_reads_only_engine_probe_entries` feeds a row with no `kind`; mutant M1 (`r["kind"]`) fails it with a `KeyError` (docs/findings-slice61.md §1).
 - "Task 1: minor (deferred): the per-call fields call() builds (searched, queries, brands, tokens) are never asserted; FakeAdapter returns no search_queries, so a mutant 'searched': True survives; mitigated for the probe run by an independent recount of searched from the saved raw responses before the pick is accepted."
@@ -150,7 +151,10 @@
 - "Task 1: minor (deferred): the stop test's monkeypatched record opens the ledger without closing it (a ResourceWarning under -W error); the text is the brief's."
   - Note (2026-10-12, after slice 61, PR #122): fixed: a shared `_recorder` writes the ledger inside a `with` block, and the test file passes under `-W error` (docs/findings-slice61.md §1).
 - "minor (deferred): addendum review M1, departure 7 still says Task 2 is 'not written now' and the plan no longer carries R4's text (R7)."
+  - Note (2026-10-12, slice 62): won't-fix: the slice 56 plan is historical and is not edited; R7 deferred this to slice 56's post-merge docs commit, and this line with R7 (findings-slice56 §3) is the record.
 - "minor (deferred): addendum review M2, departures 11 and 12 sit under Task 2, not in the plan's Departures list (R7)."
+  - Note (2026-10-12, slice 62): won't-fix: the slice 56 plan is historical and is not edited; R7 deferred this to slice 56's post-merge docs commit, and this line with R7 (findings-slice56 §3) is the record.
 - "minor (deferred): addendum review M3, the config.py comment cites findings-slice56, added by the docs PR after the code PR (R7)."
+  - Note (2026-10-12, slice 62): closed: findings-slice56.md exists since docs PR #113 (merge 77da2e7), so the config.py comment's citation resolves.
 - "Task 2: minor (deferred): the obs_cost_estimate_micros comment does not repeat the measured mean (30,039.5) it is computed from; the engine_model comment gives it as $0.0300."
   - Note (2026-10-12, after slice 61, PR #122): fixed: the comment names the measured mean, 30,039.5 micros (gemini-3.5-flash-lite in the probe); the value is unchanged (docs/findings-slice61.md §1).
--- a/docs/findings-slice57.md
+++ b/docs/findings-slice57.md
@@ -156,11 +156,13 @@
 - "Spec: minor (deferred): the note shows for a brand that is not due (audited this week) whenever the org's budget is full; it is true there but says nothing about that brand (decision 4)."
   - Note (2026-10-11, after slice 59, PR #118): fixed, reversing decision 4: the API returns `serp_due` and the note shows only for a brand the sweep would queue now (docs/findings-slice59.md §1).
 - "Task 1: minor (deferred): every pytest summary shows "2 warnings" (the known Starlette/anyio warnings, present on main and in the proof runs); not introduced by this slice."
+  - Note (2026-10-12, slice 62): won't-fix: the two warnings are upstream deprecations raised when the test client is imported: Starlette's "Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead" (from FastAPI's testclient.py) and anyio's "The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead" (from Starlette's testclient.py). Neither comes from this project's code; removing them belongs to a dependency upgrade.
 - "Task 1: minor (deferred): the Brand SERP GET now takes pg_advisory_xact_lock with no timeout for the rest of its transaction; accepted in the spec (decision 2, R6, SET LOCAL lock_timeout as the upgrade)."
   - Note (2026-10-11, after slice 59, PR #118): fixed, reversing decision 2: the GET reads the budget with `lock=False` and never waits (docs/findings-slice59.md §1).
 - "Task 2: minor (deferred): no serpSchedule case passes jobStatus = null explicitly (ck_job_status allows NULL; null is neither queued nor running, so the code handles it); the test is as the plan wrote it."
   - Note (2026-10-09, after slice 58, PR #116): fixed: format.test.ts has the `null` case (docs/findings-slice58.md §1).
   - Note (2026-10-11, after slice 60, PR #120): moot: slice 59 (PR #118) replaced `serpSchedule`'s `jobStatus` parameter with `serp_due`, so the `null` case is gone with it and nothing remains to add (docs/findings-slice60.md §1).
 - "Task 2: minor (deferred): the phase 1 report recorded only the Tests line (1 failed, 75 passed (76)) for each killed web mutant, not the failing test's name."
+  - Note (2026-10-12, slice 62): closed: a process observation about a git-ignored report; nothing in the repo to change, and that workspace is no longer kept.
 - "Final review: minor (deferred): test_get_is_empty_before_any_audit's budget_room True assertion reads scheduling.get_settings() (the .env default $2.00 budget); a local .env with DAILY_BUDGET_USD under 0.04 would turn it red; the worktree has no .env and CI uses defaults (same shape as slice 55's serp_configured case)."
   - Note (2026-10-11, after slice 60, PR #120): fixed: `_configured` in test_api_serp.py builds one `Settings` with `daily_budget_usd=2.0` and patches both `audits.get_settings` and `scheduling.get_settings`; with `DAILY_BUDGET_USD=0.01` in the environment main's test fails and the patched one passes (docs/findings-slice60.md §1).
--- a/docs/findings-slice58.md
+++ b/docs/findings-slice58.md
@@ -123,7 +123,9 @@
 - "Task 1: minor (deferred): the URL and Authorization assertions run in case 1 only; the other three cases would also get a 500 on a wrong URL but check no headers."
   - Note (2026-10-11, after slice 60, PR #120): fixed: `render()` asserts the three URLs and the Bearer header on every call (docs/findings-slice60.md §1).
 - "Task 1: minor (deferred): the report describes rather than pastes two Step 3 results (typecheck 'printed no error', eslint 'printed nothing') and the npm ci tail."
+  - Note (2026-10-12, slice 62): closed: a process observation about a git-ignored report; nothing in the repo to change, and that workspace is no longer kept.
 - "Task 1: minor (deferred): the implementer appended the Step 7 rerun section to its gitignored report with a cat >> heredoc, against the Global Constraint allowing a heredoc only for the commit message; self-reported; no code or tracked file affected."
+  - Note (2026-10-12, slice 62): closed: a process observation about a git-ignored report; nothing in the repo to change, and that workspace is no longer kept.
 - "Final review: minor (deferred): page.test.tsx's cookieStore.get returns the key for any cookie name, so a wrong cookie name in api() would pass; api.test.ts's signedIn() has the same blind spot."
   - Note (2026-10-11, after slice 60, PR #120): fixed for page.test.tsx: its cookie store returns the key only for `COOKIE` (mutant M6 fails all 7 page cases). `signedIn()` in api.test.ts got the same name check, but that file asserts no Authorization header, so the change pins nothing there yet (M6 passes its 26 tests) (docs/findings-slice60.md §1).
 - "Final review: minor (deferred): page.test.tsx's BUDGET copies the production string from format.ts, so a copy edit there means updating format.test.ts and this test."
--- a/docs/findings-slice59.md
+++ b/docs/findings-slice59.md
@@ -118,6 +118,7 @@
 Every `minor (deferred)` line in the ledger, verbatim:
 
 - "Spec: minor (deferred): API templates in the actions keep `${seg(id)}` after `formSeg`, so each value is checked twice; the existing path scan requires `seg()` in every template."
+  - Note (2026-10-12, slice 62): won't-fix, by design: `formSeg()` already calls `seg()`, and the second `seg()` in each API path template is deliberate defence in depth: it is cheap, returns an accepted value unchanged, and keeps the path scan a one-rule check (every `${}` in `api()` is one `seg()` call).
 - "Task 1: minor (deferred): the archived-brand test checks the 409 title but not the detail "Archived brands accept no new domains.""
   - Note (2026-10-11, after slice 60, PR #120): fixed: the test asserts the detail (docs/findings-slice60.md §1).
 - "Task 1: minor (deferred): the race test does not assert the thread is still alive after _wait_until_blocked, as test_recommend.py's sibling does."
@@ -127,6 +128,7 @@
 - "Task 1: minor (deferred): Host's max_length=200 applies to the raw input before _public_host normalizes it, as for every other Host field."
   - Note (2026-10-11, after slice 60, PR #120): fixed: `test_a_host_is_capped_at_200_characters` posts a 208-character scheme host (196 after normalization) and expects 422 on `host`, naming the cap as on the input as sent (docs/findings-slice60.md §1).
 - "Task 2: minor (deferred): every pytest summary shows "2 warnings", the known Starlette/anyio warnings present on main; the report does not name them."
+  - Note (2026-10-12, slice 62): won't-fix: the two warnings are upstream deprecations raised when the test client is imported: Starlette's "Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead" (from FastAPI's testclient.py) and anyio's "The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead" (from Starlette's testclient.py). Neither comes from this project's code; removing them belongs to a dependency upgrade.
 - "Task 2: minor (deferred): no serp_due case sits just inside or just outside the 1-day or 7-day windows, so a boundary slip on both the Python and SQL sides together would pass (slice 60 test hardening)."
   - Note (2026-10-11, after slice 60, PR #120): fixed: seven rows one minute inside and outside the 1-day and 7-day windows plus a running job 8 days old, on the DB clock (mutants M1, M2 and M3). A one-minute margin proves each window's length, not whether its edge is `>` or `>=` (docs/findings-slice60.md §1).
 - "Task 2: minor (deferred): test_the_page_does_not_wait_on_the_orgs_budget_lock judges the no-wait with a 5-second join, and a GET that raises in the thread fails with KeyError 'response'."
@@ -134,9 +136,12 @@
 - "Task 2: minor (deferred): test_budget.py imports the private _wait_until_blocked from test_api_recommendations (the plan's choice; matches the existing _job import from test_worker)."
   - Note (2026-10-11, after slice 60, PR #120): fixed: `wait_until_blocked` lives in tests/integration/threads.py and its four importers use it (docs/findings-slice60.md §1).
 - "Task 3: minor (deferred): the backend gate's "2 warnings" are not named in the report (the known Starlette/anyio warnings present on main)."
+  - Note (2026-10-12, slice 62): won't-fix: the two warnings are upstream deprecations raised when the test client is imported: Starlette's "Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead" (from FastAPI's testclient.py) and anyio's "The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead" (from Starlette's testclient.py). Neither comes from this project's code; removing them belongs to a dependency upgrade.
 - "Task 3: minor (deferred): the source scan is pinned to a parameter named form and double-quoted field names; fd.get(...), single quotes or `as string` would pass it."
   - Note (2026-10-11, after slice 60, PR #120): fixed for the three spellings it names: the scan accepts any receiver name, either quote style and the `as string` cast (mutant M9); other shapes (a call-expression receiver, a member-expression receiver such as `this.form`, a template-literal key, a trailing `!`) are a deferred minor in findings-slice60.md §3 (docs/findings-slice60.md §1).
 - "Task 3: minor (deferred): formSeg logs "API form value missing" for a File field, which is present but not text."
   - Note (2026-10-11, after slice 60, PR #120): fixed: the log reads "API form value missing or not text", and the three tests that asserted the old text assert the new one (docs/findings-slice60.md §1).
 - "Task 3: minor (deferred): seg(formSeg(...)) in tasks/actions.ts and seg(id) after formSeg elsewhere check each value twice (the spec's deferred minor; the path scan requires seg() in every template)."
+  - Note (2026-10-12, slice 62): won't-fix, by design: `formSeg()` already calls `seg()`, and the second `seg()` in each API path template, including `seg(formSeg(...))` in tasks/actions.ts, is deliberate defence in depth: it is cheap, returns an accepted value unchanged, and keeps the path scan a one-rule check (every `${}` in `api()` is one `seg()` call).
 - "Final review: minor (deferred): the docs follow-ups (dated notes, findings-slice59.md, README rows) are not on the branch; they belong to the post-merge docs PR."
+  - Note (2026-10-12, slice 62): done: findings-slice59.md, its dated notes and its README rows landed in docs PR #119 (merge a026e65).
--- a/docs/findings-slice60.md
+++ b/docs/findings-slice60.md
@@ -137,9 +137,13 @@
 Every `minor (deferred)` line in the ledger, verbatim:
 
 - "Task 1: minor (deferred): none carried. The reviewer's two minors are the known "2 warnings" (already out of scope, slice 62: 57:157, 59:125, 59:129) and the same exception being raised twice from `t.result()` in the no-wait test when the GET itself raises (accepted trade-off, spec R6)."
+  - Note (2026-10-12, slice 62): won't-fix: the two warnings are upstream deprecations raised when the test client is imported: Starlette's "Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead" (from FastAPI's testclient.py) and anyio's "The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead" (from Starlette's testclient.py). Neither comes from this project's code; removing them belongs to a dependency upgrade. The line numbers this line cites are as at main a026e65; later dated notes moved them, and findings-slice62.md lists the current lines.
 - "Task 2: minor (deferred): the formSeg scan's receiver is a bare `\w+`, so `String((await req.formData()).get("brand_id"))`, `String(this.form.get("brand_id"))`, a template-literal key and a trailing `!` are not matched (the spec scopes the scan to the four forms it lists)."
 - "Task 2: minor (deferred): `signedIn()` in api.test.ts pins nothing yet (M6 passes its 26 tests); the spec says so (Section 4, decision 7)."
 - "Task 2: minor (deferred): `audit()` in page.test.tsx defaults to owned 1 / organic 1 with `results: []`, so a future case using the default unchanged would render "Ownership: 1 of 1" with no rows."
 - "Task 2: minor (deferred): the backend gate prints "2 warnings" (the known Starlette/anyio warnings; slice 62 per the spec's Out of scope)."
+  - Note (2026-10-12, slice 62): won't-fix: the two warnings are upstream deprecations raised when the test client is imported: Starlette's "Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead" (from FastAPI's testclient.py) and anyio's "The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead" (from Starlette's testclient.py). Neither comes from this project's code; removing them belongs to a dependency upgrade.
 
 Not slice 60 deferred minors, and still open: the "2 warnings" (also at 57:157, 59:125 and 59:129), and 59:120 and 59:132 (`${seg(id)}` after `formSeg`): out of scope here, slice 62. The spec's Out of scope list also names 57:155 and 57:158, which slice 59 had already closed (the notes under those lines in findings-slice57.md say so); the spec carries a dated correction.
+
+Correction (2026-10-12, slice 62): the line numbers in the paragraph above are as at main a026e65; later dated notes moved them, and findings-slice62.md lists the current lines.
--- a/docs/findings-slice61.md
+++ b/docs/findings-slice61.md
@@ -99,7 +99,10 @@
 Every `minor (deferred)` line in the ledger, verbatim:
 
 - "Task 1: minor (deferred): the implementer wrote its block-applying helper script (a scratchpad apply.py outside the repo) with a shell heredoc, against the Global Constraint allowing a heredoc only for the commit message; self-reported; no tracked file affected."
+  - Note (2026-10-12, slice 62): closed: a process observation about a git-ignored report; nothing in the repo to change, and that workspace is no longer kept.
 - "Task 1: minor (deferred): test_a_rerun_refuses_to_start_while_outputs_exist creates only the results file, so main() is never tested refusing on a raw directory alone; existing_outputs is tested for that case on its own and M6 kills both tests."
 - `Final review: minor (deferred): no test checks the raw_dir wiring in main() (<raw_store_dir>/experiments/engine passed to existing_outputs); a mistyped path would skip the raw directories while the results file still triggers the refusal.`
 
 Still open from findings-slice56 and not in this slice: lines 141, 147, 148 and 149 (docs wording; line 149 is true now that findings-slice56.md exists), all slice 62.
+
+Correction (2026-10-12, slice 62): the line numbers in the line above are as at main e2b2b8b; later dated notes moved them, and findings-slice62.md lists the current lines.
```

## Evidence

Proof directory: a fresh scratchpad copy of main be24258's docs/ (`proof62-1791750562`), written only by the controller through an edit script anchored on quoted text.

- Before: 77 minors, 30 open. After: 77 minors, 7 open (49:108, 49:109, 60:141, 60:142, 60:143, 61:103, 61:104 in the patched files' numbering; the last five moved down one line because notes were inserted above them).
- `diff -rq`: findings-slice48, 50, 51, 54, 55, 56, 57, 58, 59, 60 and 61 differ; nothing else.
- 25 added lines; the banned-word grep over them prints nothing.

## Rulings

None yet.

## Out of scope

- The seven test minors (decision 1).
- Editing any historical spec, plan or findings text.
- A dependency upgrade for the two warnings.

## Docs follow-ups

- findings-slice62.md (listing the closures and the seven open test minors with their lines as at the merge), README rows for the spec, plan and findings, and the plan's "Changes made during execution", in the docs PR after the merge.
