# Slice 52 findings: the guard's long-path log test pins one console.error call

## 1. What was built

The test `api logs a long refused path quoted, capped and with its length` in `apps/web/src/lib/api.test.ts` now asserts `expect(log).toHaveBeenCalledTimes(1)` before its `toHaveBeenCalledWith`. Before, `toHaveBeenCalledWith` matched any `console.error` call, so a second or duplicated refusal log line passed. Two mutants of `sendAsWritten` in `apps/web/src/lib/api.ts` now fail with `expected "error" to be called 1 times, but got 2 times`: an extra `console.error("x")` after the refusal log (M1) and the refusal log called twice with identical arguments (M2). M2 was also run against the old test and passed it; M1 was run only against the new test (it would pass the old one too, since `toHaveBeenCalledWith` matches any call, but that was not measured). The spy is created inside the test (`api.test.ts:68`) and the file's `afterEach` restores all mocks, so the count cannot leak between tests. This fixes the slice 51 deferred minor (findings-slice51 §3, the final review minor 1; R7). Test only: no code change; web stays at 73.

Bounded path: no spec or plan file in the repo. The design was approved in chat on 2026-10-08 and lives in the Claude plan file `/Users/vineet/.claude/plans/let-s-do-item-1-2-3-playful-duckling.md`, outside the repo. Merged via PR #106 (https://github.com/aiagencyindia-lab/bsi-platform/pull/106), merge commit `278b6cd`; main `0c1ad47` after the three slice PRs.

**Code**: apps/web/src/lib/api.test.ts (one line).

**User decisions**, as the ledger records them:
- "User decision (2026-10-08 02:45 UTC): the slice 47 weekly-line minor is deferred (architectural: needs a new API field); items 1, 2 and 3b proceed as slices 52, 53, 54."
- "User decision (2026-10-08 02:45 UTC): designs for all three approved in chat (bounded path, no spec file); three branches, three PRs, three parallel implementer agents."
- "User decision (2026-10-08 02:53 UTC): finishing menu option 2, push and create a PR, for all three slices."
- "User decision (2026-10-08 02:55 UTC): merge."
- "User decision (2026-10-08 02:58 UTC): the controller writes the slices 52-54 findings docs in this session (Fable 5.1) after the harness refused the subagent's file write; an Opus 5.5 reviewer reviews them as usual."

**Results** (quoted from the ledger):
- "Task 1: implementer DONE 2026-10-08 02:47 UTC, commit 27f8088 (api.test.ts 23 passed before and after; web suite 73 passed; typecheck, lint, build pass; gen:check skipped, needs backend; M1 and M2 both fail the pinned test with 'expected "error" to be called 1 times, but got 2 times')."
- "Controller web gate 2026-10-08 02:49 UTC on 27f8088: typecheck, lint pass; Test Files 8 passed (8), Tests 73 passed (73); build Compiled successfully. gen:check skipped (needs the backend; no API change). Backend gate not run: the branch touches only apps/web/src/lib/api.test.ts, so the backend is byte-identical to main (1753 passed, 2 deselected)."
- "Pushed and opened PR #106 2026-10-08 02:54 UTC (body passed the banned-word grep)."
- "PR #106 merged 2026-10-08 02:55 UTC, merge commit 278b6cd; main now 0c1ad47."

CI was not checked by the controller before the merge; the ledger records the user's answer to the merge question as "merge" and holds no CI line.

**Mutation table** (from the implementer's report):

| Mutant | Change | Result | Failing |
|---|---|---|---|
| M1 | a second `console.error("x")` after the refusal log in `sendAsWritten` | `1 failed \| 22 passed (23)` | the long-path test |
| M2 | the refusal log called twice with identical arguments | old test `23 passed (23)`; new test `1 failed \| 22 passed (23)` | the long-path test |

**Reviews**, as the ledger records them:
- "Task 1: task review 2026-10-08 02:48 UTC: spec compliance pass, quality Approved, no findings (one line at api.test.ts:73; spy created at :68, afterEach restores mocks at :21-24; M1 and M2 messages quoted in vitest format). Cannot-verify items resolved by controller: the gates are re-run by the controller at finishing."
- No separate final whole-branch review (R1 below).
- Docs review: see the docs PR.

**Commits** (`git log --oneline 3b8d2cd..27f8088`):

| Commit | Subject |
|---|---|
| 27f8088 | test(web): pin the long-path guard log test to one console.error call |

## 2. Live check

None: a test-only change. Dev is not touched.

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim:

> Ruling: R1. Decided: no separate final whole-branch review for slice 52; the branch is one commit, so the task review package (review-3b8d2cd..27f8088.diff) already is the whole-branch diff and a second review would read the identical file. Found by: controller, at completion. Why: a duplicate review seat on a one-line diff. Cost if wrong: a defect the task reviewer missed in one line reaches the PR; the user's own PR review still stands. How named: quoted in chat.

> Ruling: R2. Decided: one docs PR covers slices 52, 53 and 54 (three findings files, README rows, dated notes under the fixed minors in findings-slice51 and findings-slice48), with one review round instead of three separate docs PRs. Found by: controller, after the three merges. Why: the three slices were planned, built and merged together; one PR keeps one review loop and one merge. Cost if wrong: a problem in one findings file holds up all three; the PR can be split if the review asks. How named: quoted in chat. (2026-10-08 02:55 UTC)

> Ruling: R3. Decided: the docs commit for slices 52-54 carries the trailer Co-Authored-By: Claude Fable 5.1, not Opus 5.5, because the controller wrote those docs on this Fable 5.1 session under the user's decision; the standing Opus 5.5 trailer rule covers work done on Opus. Found by: controller, right after the first commit (a9fecfd, trailer Opus 5.5) and before any push; amended to d2ca0a6. Why: an Opus trailer on Fable-written text would overstate who wrote it. Cost if wrong: an attribution line; no behaviour. How named: quoted in chat. (2026-10-08 03:00 UTC)

> Ruling: R4. Decided: the docs review's findings are fixed in a second docs commit: slice 54 findings 1 no longer says a host over 200 characters gets a 422 (DomainIn.host has only min_length=3; the final-review minor that said so is quoted verbatim in findings 3 with a note that the cap does not exist) (Important 1); the whitespace-only case says the browser pattern already stops it unless the entry holds a dot (Minor 1); slice 53 says the bare pipe cut the Result cell and dropped the Failing text, not that it added a column (Minor 2); the three findings say the ledger records the merge decision as 'merge', without quoting chat words (Minor 3); slice 53 drops 'with awk' and says the rendering fault was raised in the chat handoff, not in a repo file (Minor 4); slice 52 says M2 was run against the old test and M1 was not (Minor 5); slice 54 says the live check was offered in the plan file and the user did not ask for one (Minor 6). Found by: the docs reviewer (Opus 5.5), 2026-10-08. Why: a false claim and overstatements of mine. Cost if wrong: none to behaviour. How named: quoted in chat. (2026-10-08 03:04 UTC)

There is no `Correction to R` line in the ledger.

Every `minor (deferred)` line in the ledger, verbatim:

- "Task 1: minor (deferred): the short-path refusal tests in api.test.ts (the test.each guard cases) do not pin the console.error call count either, so M1 (an extra log line) only fails the long-path test."
