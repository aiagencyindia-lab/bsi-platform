# Slice 50 findings: the refusal log lines are quoted, capped and give the length

## 1. What was built

`apps/web/src/lib/api.ts` gains a module-private `shown(text) = JSON.stringify(text).slice(0, 200)`; the guard logs `("API path refused", shown(path), path.length)` and `seg` logs `("API path value refused", shown(value), value.length)`, so `seg("a/b")` logs `API path value refused "a/b" 3`. `JSON.stringify` escapes `\`, `"` and the C0 control characters, so a refusal is one line in a plain terminal; the cap is 200 UTF-16 code units, and the full length shows a cut (U+007F, U+0085, U+2028 and U+2029 stay unescaped; a cut can end inside an escape or split a surrogate pair). What is refused, the `notFound()` after it and the `"API problem"` log are unchanged. This fixes the slice 49 deferred minor (findings-slice49 §3, R11). Web only.

Spec: docs/superpowers/specs/2026-10-07-slice50-refusal-log-cap-design.md (R1, R2 and the Correction to R1 entered in `7261182`, the version the user approved; R3, from the plan review, and R4, from the final review, added by the first post-merge docs commit; R5 and R6, from the docs reviews, by the docs-review fix commits). Plan: docs/superpowers/plans/2026-10-07-slice50-refusal-log-cap.md (Task 1). Merged via PR #102 (https://github.com/aiagencyindia-lab/bsi-platform/pull/102), main `eeecd0b`.

**Code**: apps/web/src/lib/api.ts (`shown`, the two log lines); apps/web/src/lib/api.test.ts (the guard and `seg` refusal asserts; two new long-value tests). Web 71 → 73.

**User decisions**, as the ledger records them:
- "User decisions (2026-10-07): the user asked "Fix the refusal log length cap deferred minor"; approach "Quote + cap + length" (over logging the length only, or won't-fix), after approaches written in chat; Section 1 and Section 2 approved in chat."
- "User decision (2026-10-07, after the spec review): "Add the test" for the guard's own capped log line (over stating it as untested), after approaches written in chat; web 72 -> 73."
- "User decision (2026-10-07): after "go ahead" and the confirming question, "Approve, write plan" approved the spec as it stood at 7261182."
- "User decision (2026-10-07): execution "Subagent-driven"."

**Results** (quoted from the ledger):
- "Task 1: implementer a2134b4b98115cf55 reported NEEDS_CONTEXT: the brief lacked the Global Constraints, because the controller's append script failed with a Python f-string error; the controller appended them and resumed the implementer."
- "Task 1: implementer a2134b4b98115cf55 (resumed), commit 08645d3 (trailer Opus 5.5 checked); report: red Tests 17 failed | 6 passed (23), green Tests 23 passed (23); gate exit 0, gate-task1.txt Tests  73 passed (73), Compiled successfully, no refusal line, gen:check no diff; controller check: api.ts and api.test.ts are byte-identical to the rebuilt proof (s50b)."
- "Controller gates on 08645d3: backend gate exit 0, 1753 passed, 2 deselected, 2 warnings in 205.70s (0:03:25), mypy Success, metrics coverage 100%; web gate exit 0, Tests  73 passed (73), Compiled successfully, no refusal line."
- "PR opened for slice50-refusal-log-cap on head 08645d3 after the user chose "Push and create a Pull Request" at the finishing menu (2026-10-07)."
- "PR #102's description first said R1–R3 are quoted in the spec; the spec quotes R1, R2 and the Correction to R1 only; corrected through gh api PATCH (2026-10-07)."
- "CI run 37620460567: success on 08645d3, 1753 passed, 2 deselected, 2 warnings in 109.18s (0:01:49); web Tests  73 passed (73), Compiled successfully."
- "PR #102 merged by the controller after the user said "go ahead" to "Should I merge PR #102?" (2026-10-07); merge commit eeecd0b; local main fast-forwarded to eeecd0b; branch deleted on GitHub and locally."
- "Gates on main eeecd0b after merge (exact): backend 1753 passed, 2 deselected, 2 warnings in 341.40s (0:05:41), coverage 100%; web Tests  73 passed (73), Compiled successfully."

**Reviews**, as the ledger records them:
- "Spec review (abaf5a03f31a8dfdb, c5abbd6): "Spec ready? Yes"; 0 Critical, 0 Important, 6 Minor."
- "Spec re-review (a207c2739f349dbd6, 7261182): "Spec ready? Yes"; 0 Critical, 0 Important, 1 Minor (noted only, no change needed). The reviewer worked in its own new directory and reported a stray /tmp/null holding tsc output; the controller looked at it (empty) and removed it."
- "Note (2026-10-07): the line above says /tmp/null was empty; it held 29 bytes, the npm script header "> typecheck" and "> tsc --noEmit", and was removed after that was seen."
- "Plan review (ab86501954b7a3d30, d51944a): "Ready to execute? Yes"; 0 Critical, 0 Important, 3 Minor."
- "Task 1: task review (aeda51a1c7222e82c, d51944a..08645d3): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 2 Minor. ⚠️ items resolved by the controller: the trailer is checked by git log -1; gate-task1.txt shows Tests  73 passed (73), Compiled successfully and no refusal line; the report holds the RED and GREEN lines; both files are byte-identical to the rebuilt proof."
- "Final review (abdfc26968fa43d67, be011d5..08645d3): "Ready to merge? Yes"; 0 Critical, 0 Important, 2 Minor; both deferred minors triaged "does not need fixing before merge"."
- "Docs review (a6462c0907b1bf8e2, 7a5a214): "Docs ready? No"; 0 Critical, 1 Important, 2 Minor."
- "Docs re-review (a7148395d07f8da65, 11a06c8): "Docs ready? Yes"; 0 Critical, 0 Important, 3 Minor."

**Commits** (`git log --oneline --reverse be011d5..eeecd0b^2`, oldest first):

| Commit | Subject |
|---|---|
| c5abbd6 | docs(spec): slice 50, the refusal log lines are quoted, capped and give the length |
| 7261182 | docs(spec): slice 50 review fixes: guard test, escape facts, citations (R1, R2) |
| d51944a | docs(plan): slice 50, quoted and capped refusal logs |
| 08645d3 | fix(web): refusal logs are quoted, capped and give the length |

## 2. Live check

None: the spec names none (the change is two log lines, driven by the tests with a spied `console.error`). No migration; dev is not touched.

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim:

> Ruling: R1. Decided: the spec review's wording findings are fixed: "always one line" becomes "C0 control characters escaped" in the spec and in the shown() comment, which also says "200 UTF-16 code units", and the spec states that U+2028, U+2029, NEL and DEL stay unescaped and a cut can split a surrogate pair (Minors 1 and 3); the route-param encoding claim cites slice 49's observation on Next 15.5.25 (findings-slice49 §1) (Minor 4); "two tests" becomes "two parameterised tests (15 cases)" (Minor 6); Minor 5 (chat approvals and the backend count cannot be checked offline) is left. Found by: the spec reviewer (Opus 5.5, abaf5a03f31a8dfdb), 2026-10-07. Why: overstated or loose statements of mine, one in a code comment. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the spec review.

> Ruling: R2. Decided: the proof was rebuilt in a fresh scratch directory (s50b) from main plus the spec's diff plus the new guard test, and red, the six mutants and the gate steps were re-run there; the first proof directory (s50) is not used again. Found by: the controller, after the spec review: the reviewer worked in s50 (its own report says so), and afterwards s50 had no git history, the api50.green snapshot was gone and two unknown files (orig.ts, spec.diff) were present. Why: a proof must come from a directory only the controller has written. Cost if wrong: none; s50b's api.ts matched s50's byte for byte before the comment change. How named: in chat, 2026-10-07, after the rebuild.

> Ruling: R3. Decided: the plan review's three minors need no change: Step 1's first block opens the new guard test and the file's existing "});" closes it, which applies exactly (Minor 1); the "byte-identical to the proof" claim could not be checked by the reviewer, who was kept out of the scratchpad, but it confirmed the plan gives the spec's diff (Minor 2); the one placeholder is defined (Minor 3). No re-review: the plan is unchanged. Found by: the plan reviewer (Opus 5.5, ab86501954b7a3d30), 2026-10-07. Why: no statement is wrong. Cost if wrong: an implementer might pause on the open block; the brief's exact blocks still apply. How named: in chat, 2026-10-07, after the plan review.

> Ruling: R4. Decided: no final fix wave. Minor 1 (the api long-path test checks the length, not the content) is the already deferred Task 1 minor; Minor 2 (the plan's "Changes made during execution" still says "None yet.") is done by the post-merge docs commit, as in every slice. Found by: the final reviewer (Opus 5.5, abdfc26968fa43d67), 2026-10-07. Why: "Ready to merge? Yes" with no Critical or Important finding, and both deferred minors triaged "does not need fixing before merge". Cost if wrong: a wrong slice offset in the guard's log alone would go unnoticed by the tests. How named: in chat, 2026-10-07, before the gates and the finishing menu.

> Ruling: R5. Decided: the docs review's findings are fixed: the findings and the plan quote the ledger's Note correcting "/tmp/null was empty" right after the spec re-review line (Important 1); the plan's sub-list heading becomes "Execution, gates and CI, as the ledger records them" (Minor 1); the findings say R1, R2 and the Correction to R1 entered in 7261182, "the version the user approved" (Minor 2). Found by: the docs reviewer (Opus 5.5, a6462c0907b1bf8e2), 2026-10-07. Why: a quoted statement the ledger marks as wrong, and two inexact phrasings of mine. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, before the fix commit.

> Ruling: R6. Decided: the docs re-review's three minors are fixed: the findings credit R3 and R4 to the first post-merge docs commit and R5 and R6 to the docs-review fix commits (Minor 1); the spec says the second deferred minor was added by the first post-merge docs commit, 7a5a214 (Minor 2); the findings' and the plan's reviews lists quote the docs review and re-review lines (Minor 3); no further review, as the user chose "Fix, stop" when offered a stop after two docs review rounds. Found by: the docs re-reviewer (Opus 5.5, a7148395d07f8da65), 2026-10-07. Why: incomplete or ambiguous statements of mine. Cost if wrong: none to behaviour; the fix commit is unreviewed. How named: in chat, 2026-10-07, before the fix commit.

Every `Correction to R` line, verbatim:

> Correction to R1 (2026-10-07, from the controller's check before the spec edit): the route-param encoding claim is recorded in the slice 49 spec's Context ("Next passes route params to the page still percent-encoded"), not in findings-slice49 §1, and it names no Next version; the spec cites that.

Every `minor (deferred)` line in the ledger, verbatim:

- "minor (deferred): spec review minor 5, the chat approvals and the backend count "1753 passed, 2 deselected" cannot be checked from the repo offline (R1)."
  - Note (2026-10-12, slice 62): won't-fix: what this line names (chat approvals, ledger quotes, or a count from an offline run) left no record in the repo to check against; the merged PR's CI run is the record of its gates.
  - Note (2026-10-13, slice 66): correction to the slice 62 note: this line names the chat approvals, which the repo states as ledger quotes but cannot check, and the backend count "1753 passed, 2 deselected", whose record is the merged PR's CI run.
- "Task 1: minor (deferred): the api long-path test checks the logged text's length (200) but not its content, so a wrong slice offset in the guard's log alone would pass; the seg long-value test checks the content through the shared shown() (plan-mandated)."
  - Note (2026-10-08, after slice 51, PR #104): fixed; the test now uses a path with a double quote and asserts the exact logged text (docs/findings-slice51.md §1).
