# Slice 64 findings: the four open deferred minors of slice 63

## 1. What was built

Slice 64 closes the four deferred minors that slice 63 left open (docs/findings-slice63.md lines 140 to 143, as at main ac26289): two by test changes in PR #128, two by dated notes in this docs PR. No product code, migration, API or generated file changed; no live check and no spend.

- **63:140, `encoded()` strictness: won't-fix** (decision 2). The file-wide match is the scan's safety margin: another appearance of an exempt name outside a whole-line comment fails the scan, naming the file and the interpolated expression, and renaming the local query variable (with its `QUERIES` entry) or the unrelated one clears it. Nothing hits it today.
- **63:141, Step 0 paraphrased: closed.** A process observation about how slice 63's Task 1 report recorded Step 0; nothing in the repo to change. Task 1's vitest, typecheck and lint runs showed the npm dependencies working, and Task 2's pytest the uv ones.
- **63:142, the unused `raw`: fixed.** `test_a_rerun_refuses_to_start_while_outputs_exist` builds each case's output and expected text (`named`) inside its own `left` branch; `raw` exists only in the `raw` branch, and the trailing conditional is gone. The setup, the client guard, the assertions and the parametrize ids are unchanged; M4 to M7 fail the same case on main's test and on the refactored one.
- **63:143, `as string`: fixed.** The formSeg scan's variable-key branch is `\bString\([^\n]*?\.get\(\w+\)(?:!|\s+as\s+string)?\)`, so `String(form.get(k) as string)` fails the scan (M1: green on main, red patched), as `String(form.get(k)!)` and `String(form.get(k))` still do (M2, M3). Stated limits: `\s+` can cross a newline, which only fails safe; `!` together with `as string`, `as unknown as string`, `as string | null`, `as String` and `.get( k )` are not caught.

Counts: backend 1811 and web 93, unchanged (no test added or removed); tests/unit/test_engine_probe.py 21; api-paths.test.ts 2. Of the seven mutants, M1 is the one row green on main and red patched; M2 to M7 fail on main and patched alike.

Line numbers: the notes this docs PR adds move findings-slice63.md's later lines: the four minors now sit at 63:140, 63:142, 63:144 and 63:146, and its closing "Still open" sentence moves down four lines, with a dated note under it saying the four are closed.

Spec: docs/superpowers/specs/2026-10-12-slice64-test-minors-design.md (commits eb3cc74, 80e74b5, e73c074; decisions 1 to 4, rulings R1 and R2). Plan: docs/superpowers/plans/2026-10-12-slice64-test-minors.md (commits b3f5dbd, 6b59e46; R3). Merged via PR #128 (https://github.com/aiagencyindia-lab/bsi-platform/pull/128), main `d5402d2`.

**Code**:
- tests/unit/test_engine_probe.py: the `left` branches of the refusal test.
- apps/web/src/lib/api-paths.test.ts: the formSeg test's comment and `RAW`.
- 2 files, +9 −8.

**User decisions**, as the ledger records them:

- "User decision (2026-10-12): scope is exactly the four open deferred minors of findings-slice63 (lines 140 to 143 as at main ac26289), nothing else; line 139 (closed by R4 of slice 63) stays as it is ("Yes, exactly these four, nothing else")."
- "User decision (2026-10-12): 63:140 kept strict and closed with a won't-fix note (A), over loosening the match to skip string literals and property access (B)."
- "User decision (2026-10-12): 63:142 refactored to build raw and the expected text inside each branch (A), over a won't-fix note (B)."
- "User decision (2026-10-12): Sections 1 to 3 each approved after their text was shown in chat ("Yes, Section N approved")."
- "User decision (2026-10-12): spec approved ("approved, write the plan")."
- "User decision (2026-10-12): execution subagent-driven ("Subagent-driven:")."
- "User decision (2026-10-12): finishing menu answered "2 PR", after the controller ran both gates on 4eaa534 (backend 1811 passed, 2 deselected, 2 warnings, coverage 100%; web gate exit 0, 93 tests)."
- "User decision (2026-10-12): "check ci then merge" after PR 128 was opened."
- "User decision (2026-10-12): "yes, start the docs PR"."

**Results** (selected ledger lines, quoted; in the ledger only: the header and Context line, the section headings, the pre-flight scan, the ⚠️ resolution line and the "Docs:" lines):

- "Task 1: implementer (Opus 5.5) DONE, commit 4eaa534 (BASE 6b59e46); Step 2 21 passed and 2 passed; all 7 mutants matched their Expected lines; backend gate 1811 passed, 2 deselected, 2 warnings, coverage 100%; web gate exit 0, 93 tests; self-reported: a mistyped redirect created /tmp/null (29 bytes of typecheck output) outside the repo, which the controller inspected and deleted."
- "Task 1: complete (commits 6b59e46..4eaa534, review clean)"
- "Final review: no fix wave (nothing to fix)."
- "Finishing: branch slice64-test-minors pushed; PR https://github.com/aiagencyindia-lab/bsi-platform/pull/128 opened against main (head 4eaa534); CI not checked yet."
- "Finishing: CI run 38216445505 on 4eaa534: gates pass (5m0s). PR 128 merged with a merge commit, d5402d2 (main); git ls-remote --heads origin slice64-test-minors printed nothing (remote branch deleted); local main fast-forwarded."

**Mutation table** (the spec's Evidence; the implementer's run of the patched column matched it):

| # | Minor | Mutation | main's tests | patched tests |
|---|---|---|---|---|
| M1 | 63:143 | serp actions `const k = "brand_id"; const id = String(form.get(k) as string);` | green | red: path values are read with formSeg() |
| M2 | 63:143 | `const k = "brand_id"; const id = String(form.get(k)!);` | red: same test | red: same test |
| M3 | 63:143 | `const k = "brand_id"; const id = String(form.get(k));` | red: same test | red: same test |
| M4 | 63:142 | `main()` raw path `"experiment" / "engine"` | red: [raw] | red: [raw] |
| M5 | 63:142 | `existing_outputs(OUT, raw_dir, MODELS[:1])` | red: [raw] | red: [raw] |
| M6 | 63:142 | `existing_outputs(OUT, Path("nowhere"), MODELS)` | red: [raw] | red: [raw] |
| M7 | 63:142 | `existing_outputs(Path("nowhere"), raw_dir, MODELS)` | red: [results] | red: [results] |

**Reviews**, as the ledger records them:

- "Review verdict (2026-10-12): spec review (Opus 5.5) of eb3cc74: Approve with minors; no critical or important; five findings (the 63:141 note's npm/uv claim, the 63:140 note's overstatement, unsaved backend gate output, a fragment comment, the `\s+` newline crossing); diff identity and all seven mutant rows reproduced."
- "Review verdict (2026-10-12): spec scoped re-review (Opus 5.5) of 80e74b5: all five findings resolved, diff and evidence identity holds; one new minor (the claim that both gate outputs were re-run after the comment fix; only the backend one was)."
- "Review verdict (2026-10-12): e73c074 (the R2 wording commit) was not reviewed; disclosed in chat."
- "Review verdict (2026-10-12): plan review (Opus 5.5) of b3f5dbd: Approve with minors; all three blocks reproduce the spec's diff, index hashes included; all seven mutants' Expected lines reproduced; three items (path note, fragment rule, long subject)."
- "Review verdict (2026-10-12): Task 1 task review (Opus 5.5) of 6b59e46..4eaa534: spec ✅, task quality Approved; no critical or important; two minors; one ⚠️ item (the mutant and gate results are the report's claims; the report does not name the backend gate's 2 warnings)."
- "Review verdict (2026-10-12): final whole-branch review (Opus 5.5) of ac26289..4eaa534: ready to merge (Yes); no critical, important or new minor; the code commit's blob hashes match the spec's diff; the three deferred minors triaged all as not blocking the merge."
- "Review verdict (2026-10-12): docs review (Opus 5.5) of 7d4a958: Changes needed; one important (findings §1 called M1 "the one red-on-main row" though M1 is the only row green on main, reversing the table) and one minor (the Results header's "in the ledger only" list omits the Context line and the section headings); an observation that the ledger's "21 ledger lines quoted" counts only the required kinds (26 quotes in all); CI facts unverifiable by the reviewer (gh 404), supported by the merge commit's subject and parents; all 26 quotes, the notes (63:140 and 63:141 byte-identical to the spec's drafts but for the PR number), the line positions, the code claims, the tables and the README rows verified."

**Commits** (`git log --oneline --reverse ac26289..d5402d2^2`, oldest first):

| Commit | Subject |
|---|---|
| eb3cc74 | docs: slice 64 spec, the four open deferred minors of slice 63 |
| 80e74b5 | docs: slice 64 spec, spec review fixes (R1) |
| e73c074 | docs: slice 64 spec, re-review wording (R2) |
| b3f5dbd | docs: slice 64 plan, the four open deferred minors of slice 63 |
| 6b59e46 | docs: slice 64 plan, plan review minors (R3) |
| 4eaa534 | test: probe refusal builds each case in its branch; formSeg scan catches "as string" |

CI (2026-10-12): PR run 38216445505 on 4eaa534, check `gates` passed (5m0s). The push run on main after the merge was not checked.

## 2. Live check

None: the slice changes tests and docs only; nothing was called and nothing was spent.

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim (R1 and R2 were copied into the ledger from the spec, R3 from the plan, when it was created):

> Ruling: R1. Decided: the spec review's five findings are applied in a second spec commit, without a design change: the 63:141 draft note says Task 1's steps showed the npm dependencies working and Task 2's pytest the uv ones; the 63:140 draft note says the scan names the interpolated expression (not the matched name), skips whole-line comments, and is cleared by renaming the local query variable with its QUERIES entry or the unrelated one; the backend gate's output is saved as `gate64-backend.txt` and Section 3 names both saved outputs; the raw-case comment starts "Uses the last model"; `\s+` is kept and its newline crossing is stated as a fail-safe ceiling, with the cast shapes still not caught listed. Found by: the spec reviewer (Opus 5.5), 2026-10-12. Why: two overstated notes, an unsaved output, a fragment comment and an unstated ceiling, all mine. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R2. Decided: the spec re-review's one minor is applied as wording in a third spec commit, without a further review: Section 3 says only `gate64-backend.txt` was run again after the comment fix, and `gate64.txt` is the web gate from before it (the fix touched only tests/unit/test_engine_probe.py, which the web gate does not read). Found by: the spec re-reviewer (Opus 5.5), 2026-10-12, verdict all five first-review findings resolved, diff and evidence identity holds. Why: a re-run claim wider than what was run, mine. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R3. Decided: the plan review's three items are fixed in a second plan commit: Step 3 says the mutant texts are fragments replaced as text, spells out both restore commands in full, and limits the `apps/web/src/` path note to M1 to M3 (M4 to M7 name `scripts/engine_probe.py`); Step 4's commit subject is shortened. Found by: the plan reviewer (Opus 5.5), 2026-10-12, verdict Approve with minors (all three blocks reproduce the spec's diff, index hashes included; all seven mutants' Expected lines reproduced). Why: a path note that read as covering every mutant, a placeholder restore path, an unstated fragment rule and a long subject, all mine. Cost if wrong: none to behaviour. How named: this plan and chat.

> Ruling: R4. Decided: the docs review's two findings are fixed in a second docs commit: §1 says M1 is the one row green on main and red patched, and M2 to M7 fail on main and patched alike; the Results header's "in the ledger only" list names the header and Context line, the section headings, the pre-flight scan, the ⚠️ resolution line and the "Docs:" lines; the findings quote this verdict and ruling; the ledger's next Docs line states the quote counts as required lines and all quotes. Found by: the docs reviewer (Opus 5.5), 2026-10-12. Why: a sentence that reversed the table's meaning and an incomplete list, both mine. Cost if wrong: none to behaviour. How named: ledger and chat.

Every `minor (deferred)` line in the ledger, verbatim:

- "Task 1: minor (deferred): the implementer's mistyped redirect wrote a stray /tmp/null outside the repo (self-reported; deleted by the controller after checking its contents); no tracked file affected."
- "Task 1: minor (deferred): the RAW variable-key branch allows `!` or `as string` but not both, so `String(x.get(k)! as string)` is not matched (the brief's regex; the spec lists `!` with `as string` as not caught)."
- "Task 1: minor (deferred): in the results case the expected text is the bare file name `engine_probe_v0.json`, so the assert passes whatever directory the refusal names (unchanged by this slice; the brief's block; M7 still fails [results])."

Still open: the four minors of findings-slice63 are closed. Of the three above, the `/tmp/null` one is closed (the controller deleted the file after checking it); the other two stay open.
