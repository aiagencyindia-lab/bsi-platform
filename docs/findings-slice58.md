# Slice 58 findings: a render test for the Brand SERP page

## 1. What was built

A new vitest, `apps/web/src/app/(app)/b/[id]/serp/page.test.tsx`, renders the Brand SERP page (an async Server Component) through the real `api()` and `seg()`. `fetch` is stubbed per URL (any other URL gets a 500, so a wrong path fails loudly), and Next's `server-only`, `next/headers` and `next/navigation` are mocked as `actions.test.ts` and `api.test.ts` already do. The test awaits the page, renders it with `renderToStaticMarkup` and checks the markup by substring, in four cases:

1. Active, no domain: the three URLs fetched with `Authorization: Bearer bsi_key_1`, the no-domain line, and the add-domain form with its label, `pattern`, `aria-describedby` and the cost paragraph's id.
2. Active, one domain, no budget room, `?domain=exists`: the budget note and the domain note, and no form.
3. Active, one domain, audit queued: the weekly line, no budget note, "Audit in progress".
4. Archived: the archived line and no form.

Five test-only fixes ride along: a `jobStatus = null` case and the `domainNote` import order in `format.test.ts`; in `api.test.ts`, the guard cases pin the `console.error` count, the `publicApi` dot-segment test asserts its log line, and `afterEach` resets the cookie mock. No production code changed and nothing was installed.

This closes the page-render gap recorded as slice 47 R2 in part: the three fetches, `brand.status`, `domains.length` and `job?.status` are pinned; `budget_room`, `serp_configured` and `failed_7d` only one way: against a constant `true`, a constant `false`, and a constant of 3 or more, respectively, since every case that reaches those checks has the fixture's values (false, true, 0) (a deferred minor below, as corrected twice). It also closes 47's line 79, slice 48 R3 (the form's condition and attributes), slice 54 M4 (the domain note's placement) and slice 57 R3 with its correction (M9 and M13), and the deferred minors 57 (`jobStatus = null`), 54:72, 52:64, 49:103 and 49:104. Dated notes now sit under each of those lines. Still not rendered by any test: the per-audit cards (a deferred minor below).

Spec: docs/superpowers/specs/2026-10-09-slice58-serp-page-render-test-design.md (rulings R1–R4, as the user approved it at `112de4b`). Plan: docs/superpowers/plans/2026-10-09-slice58-serp-page-render-test.md (Task 1; R5 applied in `f7ec76e`). R6 was made after the final review and is quoted from the ledger below. Merged via PR #116 (https://github.com/aiagencyindia-lab/bsi-platform/pull/116), main `0b6ce94`.

**Code**:
- apps/web/src/app/(app)/b/[id]/serp/page.test.tsx: new, four cases.
- apps/web/src/lib/format.test.ts: the import order; one `expect` for `jobStatus = null`.
- apps/web/src/lib/api.test.ts: `afterEach` resets the cookie mock; `toHaveBeenCalledTimes(1)` in the guard cases; the `publicApi` log assertion.
- Web 76 → 80; backend 1777, unchanged.

**User decisions**, as the ledger records them:
- "User decision (2026-10-09): "Deferred minors, including that no test renders the Brand SERP page" chosen as the next item."
- "User decision (2026-10-09): classification architectural, said first in chat (no test renders an App Router page today)."
- "User decision (2026-10-09): scope A (one Brand SERP page-render test plus the five test-only web minors 57:155, 54:72, 52:64, 49:103, 49:104) over B (A plus the behaviour minors) and C (all 35 open minors)."
- "User decision (2026-10-09): harness H1 (real api(), fetch stubbed per URL, Next mocked as actions.test.ts does, renderToStaticMarkup) over H2 (vi.mock("@/lib/api")) and H3 (a shared src/test/ render helper)."
- "User decision (2026-10-09): Section 1 approved; the plan-mode plan approved via ExitPlanMode."
- "User decision (2026-10-09): "go ahead with fable": the proof and spec written on Fable 5.1 (spec and plan commits carry the Fable trailer)."
- "User decision (2026-10-09): Section 1 re-asked (a brand with no domain can never show the budget line): (a) four cases over (b) three cases."
- "User decision (2026-10-09): Sections 2 (minors) and 3 (evidence) approved."
- "User decision (2026-10-09): spec 112de4b approved ("go ahead", then "Approve, write plan")."
- "User decision (2026-10-09): execution subagent-driven."
- "User decision (2026-10-09): session model switched to Opus 5.5 by the user's /model command (after Task 1's review; the controller was on Fable 5.1 until here)."
- "User decision (2026-10-09): finishing option 2 (push and create a PR). Pushed slice58-serp-page-render-test at 836d0a3; PR opened against main (body checked: banned-word grep empty; rulings named as the spec R1-R4, the plan R5, the ledger R6)."
- "User decision (2026-10-09): after two docs review rounds, "Fix, re-review" over "Fix, stop" and "Stop now"."
- "User decision (2026-10-09): after the third docs round, "Fix, stop" over "Stop now" and "Fix, re-review"."

**Results** (selected ledger lines, quoted; in the ledger only: the header lines — title, spec, branch and base, session model — the dispatch lines and the pre-flight-scan lines):
- "Task 1: implementer DONE_WITH_CONCERNS (commit 836d0a3; web 80 passed (80); typecheck, eslint clean; npm run gate passed; M1-M7 killed as in the proof (M6 10 failed); concern: Step 7's pytest gave 1 failed, 1110 passed, 666 errors because the bsi_test DB on :5433 closed connections mid-run and docker ps hung; ruff and mypy passed; the implementer touched neither Docker nor the DB; Step 7 needs a rerun)"
- "Task 1: cannot-verify resolved: the commit trailer is "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" after a blank line (controller ran git log -1 --format=%B 836d0a3); the mutation results stand on the implementer's pasted Tests lines, which match the proof's; Step 7 (backend gate) stays open until the :5433 database is back."
- "Task 1: blocked on the environment: the Postgres container on :5433 is down (nc: closed; docker ps gives no output in 8 s while Docker Desktop's backend runs); the user was asked to restart Docker Desktop; Step 7 reruns after that, and must name any failing test."
- "Environment (2026-10-09): the user restarted Docker Desktop ("done"); the controller ran docker compose up -d in bsi-platform (bsi-platform-db-1 running) and a select 1 on bsi_test succeeded; the earlier pytest pid 99112 was invoice-processing's (cwd), not this repo's. Step 7 rerun sent to the Task 1 implementer."
- "Task 1: Step 7 rerun DONE (no new commit): 184 files already formatted; All checks passed!; Success: no issues found in 31 source files; 1777 passed, 2 deselected, 2 warnings in 151.54s; metrics coverage 100.00%; pgrep empty before the run."
- "Task 1: complete (commits f7ec76e..836d0a3, review clean)"
- "Final review: complete (d6f2703..836d0a3; no fix wave, 0 residual findings)"
- "Controller gates (2026-10-09) on 836d0a3: backend ruff format (184 files left unchanged), ruff check All checks passed!, ruff format --check 184 files already formatted, mypy Success: no issues found in 31 source files, pytest 1777 passed, 2 deselected, 2 warnings in 128.73s, metrics coverage 100.00%; web npm run gate exit 0 (Test Files 9 passed (9), Tests 80 passed (80), Compiled successfully); git status clean."
- "PR #116 opened (2026-10-09). User decision (2026-10-09): "go ahead" to "Should I merge PR #116?" (CI not checked: the user did not ask). PR #116 merged as 0b6ce94; gh pr merge stopped at the local-branch error (worktree), so the controller deleted origin/slice58-serp-page-render-test with git push --delete; ls-remote then showed 0 heads; local branch kept (used by the bsi-wt/slice58 worktree)."
- "CI (2026-10-09), checked after the merge at the user's request: PR run 37897194619 on 836d0a3 completed success (1777 passed, 2 deselected, 2 warnings; Tests 80 passed (80); Compiled successfully); push run 37897260364 on main 0b6ce94 completed success (same counts)."

**Mutation table** (the spec's proof; the implementer's own run matched it):

| Mutant | Change | Result |
|---|---|---|
| M1 | the page passes `true` for `budget_room` | killed: the "with a domain and no room" case |
| M2 | the page drops `job?.status` | killed: the "queued audit" case |
| M3 | the domain note moved inside the form condition | killed: the "with a domain and no room" case |
| M4 | `brand.aliases.length` in place of `domains.length` | killed: the "no domain" case |
| M5 | the host input loses `pattern` | killed: the "no domain" case |
| M6 | `sendAsWritten` logs twice | killed: the 8 guard cases, the long-path test and the publicApi test |
| M7 | `publicApi` skips its guard | killed: the publicApi test (already killed on main, spec R3) |

**Reviews**, as the ledger records them:
- "Review verdict (2026-10-09): spec review of d3e91c5 (Opus 5.5): Approved with minors (6 minors: inventory count, deferral quotation, M7 proves nothing new, README pointer, 47:79 uncited, actions.test.ts mis-cited); fixed in 3be8092 (R3)."
- "Review verdict (2026-10-09): scoped spec re-review of d3e91c5..3be8092: Approved with minors (all 6 resolved; 2 nits: the inventory sentence contradicted itself, 'ruling' for a table row); fixed in 112de4b (R4)."
- "Review verdict (2026-10-09): plan review of 8121b21 (Opus 5.5): Approved with minors (mechanics byte-identical; 5 process minors); fixed in f7ec76e (R5)."
- "Review verdict (2026-10-09): Task 1 task review of f7ec76e..836d0a3 (Opus 5.5): Spec compliant (page.test.tsx byte-identical to the brief; added/removed lines identical to the spec's diff); Task quality Approved; 0 critical, 0 important, 4 minor."
- "Review verdict (2026-10-09): final whole-branch review of d6f2703..836d0a3 (Opus 5.5): Ready to merge Yes; 0 critical, 0 important, 4 minor; all 5 deferred minors triaged as not blocking."
- "Review verdict (2026-10-09): docs review of 6ed57b3 (Opus 5.5): Changes needed (1 important: findings §1 and the README row say slice 47 R2 is closed, but serp_configured and failed_7d are true and 0 in every case, so a constant for either still passes; 3 minors: the 48 R3 note says 'cost paragraph' where only its id is asserted; the Results header omits the header lines; two plan notes worded loosely). All 41 quotes match the ledger byte for byte."
- "Review verdict (2026-10-09): docs re-review of e217fe7 (Opus 5.5): Findings open (all 4 earlier findings addressed as worded; 1 new important: the partial-closure wording lists budget_room as pinned, but every case that reaches it has budget_room false, so a constant false still passes; 1 nit: nested parentheses in the Results header)."
- "Review verdict (2026-10-09): docs re-review of e217fe7..695f4fb (Opus 5.5): All findings addressed (both ADDRESSED; every quote matches the ledger; 1 new minor: the docs say serp_configured and failed_7d are not pinned, but cases 2 and 3 reach both checks, so a constant false or a failed_7d of 3 or more fails them; an understatement)."

**Commits** (`git log --oneline --reverse d6f2703..0b6ce94^2`, oldest first):

| Commit | Subject |
|---|---|
| d3e91c5 | docs(spec): slice 58 design, a render test for the Brand SERP page |
| 3be8092 | docs(spec): slice 58 review fixes (R3) |
| 112de4b | docs(spec): slice 58 re-review fixes (R4) |
| 8121b21 | docs(plan): slice 58 implementation plan, generated from the proof |
| f7ec76e | docs(plan): slice 58 plan review fixes (R5) |
| 836d0a3 | test(web): render the Brand SERP page; pin the guard log count and the publicApi log |

## 2. Live check

None: nothing user-visible changed.

## 3. Rulings and deferred minors

Every `Ruling:` and `Correction to R` line in the ledger, verbatim (R1–R5 were copied into the ledger from the spec and plan when it was created):

> Ruling: R1. Decided: the proof's `render` helper returns the `fetch` calls as `(url, Authorization)` pairs and case 1 compares the sorted URL list, rather than asserting call order. Found by: the controller, writing the proof. Why: `Promise.all` starts the three fetches together; their order is not part of the page's contract. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R2. Decided: the spec's vitest count is 76 → 80, not the plan-mode draft's 77. Found by: the controller, the proof's green run. Why: four `test()` cases, not one; the draft counted the page test as one. Cost if wrong: none. How named: this spec and chat.

> Ruling: R3. Decided: the spec review's six minors are fixed in a second spec commit: the inventory sentence no longer states a total (the chat reading gave 45, the reviewer's grep 46, and a plain grep cannot settle it); the deferral reason quotes each ruling's own words; the M7 row says main's test already kills it and that M6 exercises the new publicApi log assertion; the README clause is replaced by "no README row mentions the gap"; findings-slice47.md line 79 joins the docs follow-ups; api.test.ts is cited beside actions.test.ts for the throwing `notFound`. Found by: the spec reviewer (Opus 5.5), 2026-10-09. Why: an unverifiable count, a quotation that was true for two of four rulings, a mutant that proved nothing, a pointer at nothing, an omission, and a mis-citation, all mine. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R4. Decided: the re-review's two nits are fixed in a third spec commit: the inventory sentence reads "35 open deferred minors: about 11 test-only, the rest behaviour or documentation items", and the deferral sentence says "in each record's own words", since the 54 M4 quote is a mutation-table row, not a ruling. Found by: the spec re-reviewer (Opus 5.5), 2026-10-09. Why: a sentence that contradicted itself and a label that was wrong for one of four quotes, both mine. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R5. Decided: the plan review's five minors are fixed in a second plan commit: Step 0 switches the main checkout to main before `worktree add`; Step 4's restore commands are written out with the page path quoted; the cwd constraint allows `apps/web`, `pgrep` and the controller's worktree command; departure 3 no longer calls Step 7 a departure; departure 4 says the docs follow-ups go to the docs PR. Found by: the plan reviewer (Opus 5.5), 2026-10-09. Why: a step that would stop, a restore that zsh would refuse (letting the next mutant start on a mutated file), a constraint the steps did not meet, and two untrue or missing departure lines, all mine. Cost if wrong: none to behaviour. How named: this plan and chat.

> Ruling: R6. Decided: no final fix wave: final-review minors 1 (cookie name ignored) and 2 (BUDGET copied) are deferred; minor 3 (exact markup strings; no assertion on React's action serialisation or the injected script) and minor 4 (the harness's generic part when it moves to src/test/) are observations with no change. Found by: the final reviewer (Opus 5.5), 2026-10-09. Why: 'Ready to merge? Yes' with no Critical or Important finding; minor 1 is pre-existing in api.test.ts and belongs with a change there, and minor 2 is the stronger check the plan's 'do not adjust a test to pass' rule chose. Cost if wrong: a cookie-name slip in api() passes both test files; a copy edit to the budget line fails two tests instead of one. How named: ledger and chat.

> Ruling: R7. Decided: the docs review's findings are fixed in a second docs commit: findings §1 and the README row say slice 47 R2 is closed in part (the fetches, brand.status, domains.length, budget_room, job?.status) and name the two arguments still unpinned, recorded as a new deferred minor; the 48 R3 note and §1 case 1 say 'the cost paragraph's id'; the Results header names the header lines it leaves out; the plan's Step 0 bullet says 'as planned' and the byte-identical claim names the brief and the spec's diff. Found by: the docs reviewer (Opus 5.5), 2026-10-09. Why: an overstated closure and three loose claims, all mine. Cost if wrong: none to behaviour. How named: ledger and chat.

> Correction to R7 (2026-10-09): budget_room is pinned one way only: the page passing a constant true fails case 2, a constant false passes every case (only cases 2 and 3 reach the budget check, and both have budget_room false). Slice 47 R2 is closed for the fetches, brand.status, domains.length and job?.status; budget_room is pinned against true only; serp_configured and failed_7d are not pinned.

> Ruling: R8. Decided: the re-review's findings are fixed in a third docs commit: findings §1 says budget_room is pinned against true only, and quotes the Correction to R7 and the corrected deferred minor in §3, replacing the 'no Correction to R line' sentence; the Results header uses a dash instead of nested parentheses and names the title line too. Found by: the docs re-reviewer (Opus 5.5), 2026-10-09. Why: my R7 wording repeated the overstatement it set out to fix, for one argument. Cost if wrong: none to behaviour. How named: ledger and chat.

> Correction to R7 (2026-10-09, second): serp_configured and failed_7d are pinned one way, like budget_room: a constant false for serp_configured, or a constant failed_7d of 3 or more, fails cases 2 and 3; only constants equal to the fixture's values (true; anything below 3) still pass.

> Ruling: R9. Decided: findings §1 says serp_configured is pinned against a constant false and failed_7d against a constant of 3 or more, and quotes the second Correction to R7 in §3; the README row is unchanged (it already names the correction to R7). No further review, as the user chose "Fix, stop"; the PR body says this commit is unreviewed. Found by: the docs re-reviewer (Opus 5.5), 2026-10-09. Why: my Correction to R7 understated the test for two arguments. Cost if wrong: none to behaviour; the commit is unreviewed. How named: ledger and chat.

Every `minor (deferred)` line in the ledger, verbatim:

- "Spec: minor (deferred): the page test renders only the empty-audits branch; the per-audit cards (ownership, type counts, the results table) are rendered by no test."
- "Task 1: minor (deferred): page.test.tsx hard-codes http://localhost:8000 as api.test.ts:209 already does; building BASE from the exported API_URL would survive an API_URL set in the vitest environment (none is today)."
- "Task 1: minor (deferred): the URL and Authorization assertions run in case 1 only; the other three cases would also get a 500 on a wrong URL but check no headers."
- "Task 1: minor (deferred): the report describes rather than pastes two Step 3 results (typecheck 'printed no error', eslint 'printed nothing') and the npm ci tail."
- "Task 1: minor (deferred): the implementer appended the Step 7 rerun section to its gitignored report with a cat >> heredoc, against the Global Constraint allowing a heredoc only for the commit message; self-reported; no code or tracked file affected."
- "Final review: minor (deferred): page.test.tsx's cookieStore.get returns the key for any cookie name, so a wrong cookie name in api() would pass; api.test.ts's signedIn() has the same blind spot."
- "Final review: minor (deferred): page.test.tsx's BUDGET copies the production string from format.ts, so a copy edit there means updating format.test.ts and this test."
- "Docs review: minor (deferred): page.test.tsx's serp() fixture sets serp_configured true and failed_7d 0 in every case, so the page passing a constant for either argument still passes; slice 47 R2 is closed only for the fetches, brand.status, domains.length, budget_room and job?.status."
- "Docs review: minor (deferred): corrected: page.test.tsx's serp() fixture sets serp_configured true and failed_7d 0 in every case, and every case that reaches the budget check has budget_room false, so the page passing a constant for serp_configured or failed_7d, or a constant false for budget_room, still passes (Correction to R7)."
