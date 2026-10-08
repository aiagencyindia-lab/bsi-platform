# Slice 51 findings: the guard's long-path log test checks the logged text

## 1. What was built

The test `api logs a long refused path quoted, capped and with its length` in `apps/web/src/lib/api.test.ts` now sends the path `/brands/x#"` followed by 500 `y`s and asserts a log call with the exact arguments: `"API path refused"`, then the opening quote, `/brands/x#`, an escaped quote and 187 `y`s (200 characters, no closing quote), then `path.length`. It replaces `expect.any(String)` plus a length check. Four mutants of the guard's log line that passed the old test now fail (a cut from the wrong end, the cap applied before quoting, the tail kept and quoted, the escaping of a double quote dropped). Still not caught, as the spec states: dropping the escaping of control characters, escaping changes only for paths over 200 characters that this path does not exercise, and lone surrogates. This fixes the slice 50 deferred minor (findings-slice50 §3, the Task 1 minor; R4). Test only: no code change; web stays at 73.

Spec: docs/superpowers/specs/2026-10-07-slice51-guard-log-content-test-design.md (R1 entered in `5b53d24`, R2 in `b37e39b`, the Correction to R2 and R3 in `1333e8c`, R4 in `26e3c5f`, the version the user approved; R5, R6 and R7 added by the first post-merge docs commit, R8 and R9 by the docs-review fix commits). Plan: docs/superpowers/plans/2026-10-07-slice51-guard-log-content-test.md (Task 1). Merged via PR #104 (https://github.com/aiagencyindia-lab/bsi-platform/pull/104), main `ad330b6`.

**Code**: apps/web/src/lib/api.test.ts (one test).

**User decisions**, as the ledger records them:
- "User decisions (2026-10-07): the user asked "Fix the guard long-path test content deferred minor"; approach "Exact literal" (over recomputing JSON.stringify(path).slice(0, 200) in the test, or won't-fix), after approaches written in chat; Section 1 and Section 2 approved in chat."
- "User decision (2026-10-07, after the spec re-review): "Add a '"'" to the long-path test (path /brands/x#" followed by 500 y's; the expected text is the opening quote, /brands/x#, an escaped quote and 187 y's), over correcting the wording only, after approaches written in chat."
- "User decision (2026-10-07): after "go ahead" and the confirming question, "Approve, write plan" approved the spec as it stood at 26e3c5f (including that unreviewed commit)."
- "User decision (2026-10-07): execution "Subagent-driven"."

**Results** (quoted from the ledger):
- "Task 1: implementer aa693ecc7bed81c98, commit fc14c2a (trailer Opus 5.5 checked); report: Step 2 Tests 23 passed (23) with no failing run first (a passing test made stricter); gate exit 0, gate-task1.txt Tests  73 passed (73), Compiled successfully, no refusal line, gen:check no diff; controller check: api.test.ts is byte-identical to the proof and api.ts is unchanged."
- "Controller gates on fc14c2a: backend gate exit 0, 1753 passed, 2 deselected, 2 warnings in 176.02s (0:02:56), mypy Success, metrics coverage 100%; web gate exit 0, Tests  73 passed (73), Compiled successfully, no refusal line."
- "PR opened for slice51-guard-log-content-test on head fc14c2a after the user chose "Push and create a Pull Request" at the finishing menu (2026-10-08)."
- "CI run 37670695791: success on fc14c2a, 1753 passed, 2 deselected, 2 warnings in 109.67s (0:01:49); web Tests  73 passed (73), Compiled successfully."
- "PR #104 merged by the controller after the user said "go ahead" to "Should I merge PR #104?" (2026-10-08); merge commit ad330b6; local main fast-forwarded to ad330b6; branch deleted on GitHub and locally."
- "Gates on main ad330b6 after merge: backend 1753 passed, 2 deselected, 2 warnings in 205.31s (0:03:25), coverage 100%; web Tests  73 passed (73), Compiled successfully."

**Reviews**, as the ledger records them:
- "Spec review (af3e879d99a9f5e90, 5b53d24): "Spec ready? Yes"; 0 Critical, 0 Important, 2 Minor."
- "Spec re-review (a9997b9f0e8348a43, b37e39b): "Spec ready? Yes"; 0 Critical, 0 Important, 1 Minor; the reviewer's shell commands were refused because the safety classifier gave no verdict, so it read the working-tree files instead of git; the branch had only spec commits, so its api.test.ts was main's."
- "Spec re-review (a894f91ae9e541d17, 1333e8c): "Spec ready? Yes"; 0 Critical, 0 Important, 4 Minor."
- "Plan review (a4ddf97913dab5850, 26e3c5f and c8a7f52): "Ready to execute? No"; 0 Critical, 1 Important, 2 Minor."
- "Plan re-review (ad35bb41ef105d741, ceebe45): "Ready to execute? Yes"; 0 Critical, 0 Important, 2 Minor."
- "Task 1: task review (ac16c57b45a3f0f20, ceebe45..fc14c2a): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 0 Minor. ⚠️ items resolved by the controller: the trailer is checked by git log -1; gate-task1.txt shows Tests  73 passed (73), Compiled successfully and no refusal line; api.test.ts is byte-identical to the proof (no Prettier change)."
- "Final review (a10688c75b844f448, b44c2ac..fc14c2a): "Ready to merge? Yes"; 0 Critical, 0 Important, 3 Minor; the deferred minor triaged "does not need fixing before merge"."
- "Docs review (afd1deb17561e8d50, 837cbdd): "Docs ready? Yes"; 0 Critical, 0 Important, 2 Minor."
- "Docs re-review (a1d40632dcaf76bbb, fb988bb): "Docs ready? Yes"; 0 Critical, 0 Important, 1 Minor."

**Commits** (`git log --oneline --reverse b44c2ac..ad330b6^2`, oldest first):

| Commit | Subject |
|---|---|
| 5b53d24 | docs(spec): slice 51, the guard's long-path log test checks the logged text |
| b37e39b | docs(spec): slice 51 review fixes (R2) |
| 1333e8c | docs(spec): slice 51 test path holds a double quote; M6; correction to R2 (R3) |
| 26e3c5f | docs(spec): slice 51 re-review wording and table fixes (R4) |
| c8a7f52 | docs(plan): slice 51, the guard's long-path log test checks the logged text |
| ceebe45 | docs(plan): slice 51 step 1 is one whole-run block (R5) |
| fc14c2a | test(web): the guard's long-path log test checks the logged text |

## 2. Live check

None: a test-only change (the spec names none). Dev is not touched.

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim:

> Ruling: R1. Decided: the proof's evidence is three mutants of the guard's log line that pass the old test and fail the new one: JSON.stringify(path).slice(-200) (M1), JSON.stringify(path.slice(0, 198)) (M4) and JSON.stringify(path.slice(-198)) (M5); Section 2 had also named path.slice(0, 200) (M2) and JSON.stringify(path).slice(1, 201) (M3) as passing the old test, but both already fail it through the short-path refusal cases, and the spec records them as such. Found by: the controller, running the proof. Why: Section 2's claim about M2 and M3 was wrong; the approach is unaffected, since the new literal still catches what the old test missed. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R2. Decided: the spec review's findings are fixed: the Context says the seg long-value test checks the logged text's length, opening characters and escaping, not its full content (Minor 1); the mutation table's M2 and M3 rows say the new count is the 8 short-path cases plus the long-path test (Minor 2); the spec states the reviewer's boundary that only a contrived length-dependent mutant (dropping the escaping only for paths over 200 characters) passes the new test, because the long path holds nothing JSON.stringify escapes; the optional notes that cannot be checked offline are a deferred minor. Found by: the spec reviewer (Opus 5.5, af3e879d99a9f5e90), 2026-10-07. Why: an overstatement and an unclear table row of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the spec review.

> Ruling: R3. Decided: the spec is updated for the user's "Add a '"'" decision: the Design gives the new path and expected text, the mutation table adds M6 (the guard's log line with the escaping of a double quote dropped: passes the old test, fails the new one) and re-runs M1 to M5 on the new path with the same results, and the boundary sentence now says that a mutant dropping the escaping of control characters (which no test path holds) still passes. Found by: the controller, running the updated proof. Why: the spec must describe the test as changed and its remaining gap. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R4. Decided: the second spec re-review's four minors are fixed: the boundary sentence names the open gaps it found (dropping the escaping of control characters; changing escaping only for paths over 200 characters in a way this path does not exercise, such as dropping backslash escaping only for long paths; lone surrogates) (Minor 1); a note after the quoted Correction to R2 says the sentence it refers to was replaced in R3 (Minor 2); "re-run on the new path" becomes "re-run with the updated test" (Minor 3); the "|" inside the mutation table's cells is escaped so the table renders (Minor 4). Found by: the spec re-reviewer (Opus 5.5, a894f91ae9e541d17), 2026-10-07. Why: incomplete or loose statements of mine and a rendering fault. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the re-review.

> Ruling: R5. Decided: the plan review's findings are fixed: Step 1's three blocks, one of which deleted a line by replacing it with an empty block (an Edit-tool implementer would leave a blank line that no gate step catches), become one block covering the whole changed run of 8 lines, replaced by 7 (Important 1); departure 1 says so (Minor 1); the "byte-identical" claim now holds under both readings of a block, with and without its trailing newline, as checked on a fresh copy (Minor 2). Found by: the plan reviewer (Opus 5.5, a4ddf97913dab5850), 2026-10-07. Why: a plan step that could be applied two ways, one of them wrong. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the plan review.

> Ruling: R6. Decided: the plan re-review's two minors need no change: the plan cites R5, which is in the ledger and is added to the spec by the post-merge docs commit, as plan-review rulings were in slice 50 (Minor 1); Step 1's one-item numbered list is cosmetic (Minor 2). No further plan review. Found by: the plan re-reviewer (Opus 5.5, ad35bb41ef105d741), 2026-10-07. Why: neither is wrong for execution. Cost if wrong: a reader of the plan before the docs PR cannot find R5 in the spec. How named: in chat, 2026-10-07, after the plan re-review.

> Ruling: R7. Decided: no final fix wave. Minor 1 (toHaveBeenCalledWith matches any console.error call, and the removed line had pinned call 0) is deferred; Minor 2 (the spec's Design line nests backticks inside backticks, so it renders broken) is fixed by the post-merge docs commit; Minor 3 (the hunk header) needs no action. Found by: the final reviewer (Opus 5.5, a10688c75b844f448), 2026-10-07. Why: "Ready to merge? Yes" with no Critical or Important finding. Cost if wrong: a second, matching console.error call elsewhere in the guard's path would let the test pass even if the first call were wrong (the guard logs once today). How named: in chat, 2026-10-07, before the gates and the finishing menu.

> Ruling: R8. Decided: the docs review's two minors are fixed: findings §1 says the test "asserts a log call with the exact arguments", not "the guard's exact log call", since toHaveBeenCalledWith matches any call (the R7 minor) (Minor 1); its source citation reads "(findings-slice50 §3, the Task 1 minor; R4)" (Minor 2). Found by: the docs reviewer (Opus 5.5, afd1deb17561e8d50), 2026-10-08. Why: an overstatement and a loose citation of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-08, before the fix commit.

> Ruling: R9. Decided: the docs re-review's Minor 1 is fixed: the plan's last execution note says "the first post-merge docs commit" fixed the spec Design line's nested backticks, as the findings and spec now name it; no further review, as the user chose "Fix, stop" when offered a stop after two docs review rounds. Found by: the docs re-reviewer (Opus 5.5, a1d40632dcaf76bbb), 2026-10-08. Why: an unqualified name once two post-merge docs commits exist. Cost if wrong: none to behaviour; the fix commit is unreviewed. How named: in chat, 2026-10-08, before the fix commit.

Every `Correction to R` line, verbatim:

> Correction to R2 (2026-10-07, from the spec re-review): "only a contrived length-dependent mutant ... passes the new test" is false: a guard log line that stops escaping a double quote or control characters, for paths of any length, also passed all tests, since no test path held either; the spec's own sentence says "such as" and is true.

Every `minor (deferred)` line in the ledger, verbatim:

- "minor (deferred): spec review notes, the proof directory being written only by the controller, the chat approvals and the backend count cannot be checked from the repo offline (R2)."
- "minor (deferred): final review minor 1, the long-path test's toHaveBeenCalledWith matches any console.error call, not call 0; expect(log).toHaveBeenCalledTimes(1) would pin it; the guard logs once today (R7)."
  - Note (2026-10-08, after slice 52, PR #106): fixed; the long-path test asserts `toHaveBeenCalledTimes(1)` before its `toHaveBeenCalledWith` (docs/findings-slice52.md §1).
