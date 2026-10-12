# Slice 61 findings: the slice 56 engine probe's deferred minors

## 1. What was built

Slice 61 closes six deferred minors of slice 56's engine probe (five in the script and its tests, one config comment) (findings-slice56.md lines 142 to 146 and 150, as at main e2b2b8b), the third of the four "fix every item" slices (59 behaviour, 60 test hardening, 61 the probe script, 62 the docs sweep). The probe ran once on 2026-10-08; it was not run in this slice and nothing was spent.

- **145, a re-run.** `existing_outputs()` names the results file and any model's raw directory that already exist, and `main()` exits with `SystemExit` naming them, right after the ledger-floor check and before it reads the prompts, builds a client or makes a call. The results file is tracked in git, so in the canonical checkout a re-run needs the slice 56 record moved first. The results keep `probe_spend_micros` (the cumulative total the stop uses) and gain `run_spend_micros` (this run's recorded tries).
- **144, an unexpected error.** `run()` gains `except Exception:` after the `Stop` and `SpendCapReached` branches: it writes the partial results with `stopped: "error"` and re-raises. `report()` reads the ledger inside `try`/`except (ValueError, KeyError)`, so a line that is not valid JSON or a probe row without `micros` gives `null` spend numbers instead of losing the results (spec decision 4); the test covers the invalid-JSON line, and the row without `micros` is handled by the same `except` but untested. A JSON value that is not an object, or a null `micros`, still raises there and loses them (R2); `spend.record` writes neither.
- **142, 143, 146, the tests.** Seven new tests in `tests/unit/test_engine_probe.py`: `probe_costs` ignoring a row with no `kind`; the per-call fields, asserted in full for a call with search queries (`searched`, `queries`, `cost`, `tokens_in`, `tokens_out` as candidates plus thoughts, `brands` as distinct entities) and for `searched` and `queries` on a call without them; the unexpected-error and malformed-ledger paths; `existing_outputs`; and `main()` refusing, with a minimal `eval/run1.json` present so a client build fails the test (R1). A shared `_recorder` closes the ledger file it writes, so the file passes under `-W error`.
- **150, the comment.** The `obs_cost_estimate_micros` comment in `packages/core/bsi_core/config.py` names the measured mean, 30,039.5 micros; the value (50,000) is unchanged.

Counts: tests/unit/test_engine_probe.py 13 → 20; backend 1803 → 1810; web 91, unchanged. Five tests fail against main's script (the red run): four of the new ones and the modified stop test; nine mutants each fail the test meant for them.

Spec: docs/superpowers/specs/2026-10-11-slice61-engine-probe-hardening-design.md (commits 6433690, e7cf9ba, 3a4a083; decisions 1 to 4, rulings R1 and R2). Plan: docs/superpowers/plans/2026-10-11-slice61-engine-probe-hardening.md (commits 723aad2, d1c6b4a; R3). R4 was made at execution and R5 at the docs review. Merged via PR #122 (https://github.com/aiagencyindia-lab/bsi-platform/pull/122), main `63cd214`.

**Code**:
- scripts/engine_probe.py: the module docstring, `existing_outputs`, `report(..., before)` with the ledger tolerance, `run()` (`before`, the error branch, its docstring), the refusal in `main()`.
- tests/unit/test_engine_probe.py: imports, `FakeAdapter`, `_recorder`, `ENTITIES`, `_call`, seven new tests, the stop test.
- packages/core/bsi_core/config.py: one comment.
- 3 files, +234 −17.

**User decisions**, as the ledger records them:
- "User decision (2026-10-11, spec decision 1): Item 145, a re-run: refuse by default (the probe exits before spending when the results file or a model's raw directory exists; the report gains `run_spend_micros` beside the cumulative `probe_spend_micros`), over a per-run output and over documenting the overwrite only."
- "User decision (2026-10-11, spec decision 2): Item 144, an unexpected exception: write the partial results with `stopped: "error"` and re-raise, over continuing as a failed call and over documenting only."
- "User decision (2026-10-11, spec decision 3): Sections 1 to 4 each approved ("Yes, go on" for 1 to 3, "Yes, write the spec" for 4) after their text was shown in chat."
- "User decision (2026-10-11, spec decision 4): After the spec review (finding 1, 2026-10-12): a malformed ledger line is tolerated in `report()` (the spend fields become `null`, the partial results are still written, then the exception re-raises), over narrowing the claim for item 144 to two of its three causes."
- "User decision (2026-10-12): spec approved with "approved, write the plan" (the user's literal words) after the spec review rounds (commits 6433690, e7cf9ba, 3a4a083)."
- "User decision (2026-10-12): execution method "approved, subagent-driven" (the user's literal words) after the plan review (commits 723aad2, d1c6b4a)."
- "Finishing: User decision (2026-10-12): finishing menu answered "2 PR" (the user's literal words) after the controller ran both gates in the worktree (backend 1810 passed, 2 deselected, 2 warnings, coverage 100%; web 91 passed, build, gen:check clean)."
- "Finishing: User decision (2026-10-12): "check ci then merge" (the user's literal words) after PR #122 was opened."
- "Docs: User decision (2026-10-12): after two docs review rounds, "Fix, stop" over "Stop now" and "Fix, re-review" (the user's chosen option, from the three the controller offered)."

**Results** (selected ledger lines, quoted; in the ledger only: the header lines, the pre-flight scan, the classification line, and the "Docs:" lines that record the docs commits):
- "Task 1: implementer (Opus 5.5, agent afb4629ed339a3e40) DONE_WITH_CONCERNS: commit 62d9d1b (BASE d1c6b4a). Report: task-1-report.md. Red 5 failed, 15 passed (the five expected); green 20 passed with and without -W error; M1-M9 killed as the brief lists (M8 by the client guard); ruff, mypy clean; backend 1810 passed, 2 deselected, 2 warnings, coverage 100%; web 91 passed, typecheck, lint, build, gen:check passed."
- "Task 1: complete (commits d1c6b4a..62d9d1b, review clean)"
- "Final review: no fix wave needed."
- "Finishing: PR #122 opened (https://github.com/aiagencyindia-lab/bsi-platform/pull/122), head slice61-engine-probe-hardening at 62d9d1b, base main e2b2b8b. CI not checked (waiting for the user). Ledger and worktree kept until the docs PR merges."
- "Finishing: CI run 38168703166 on 62d9d1b: gates pass (4m14s); backend 1810 passed, 2 deselected, 2 warnings; web 91 passed; build compiled. PR #122 merged with a merge commit."
- "Finishing: PR #122's merge commit is 63cd214 (main); git ls-remote --heads origin slice61-engine-probe-hardening printed nothing (remote branch deleted); local main fast-forwarded."

**Mutation table** (the spec's proof; the implementer's run matched it):

| Mutant | Change | Result |
|---|---|---|
| M1 | `probe_costs` reads `r["kind"]` in place of `r.get("kind", "")` | killed: test_probe_costs_reads_only_engine_probe_entries (1 failed, 19 passed) |
| M2 | `call()` records `"searched": True` | killed: test_a_call_with_no_search_queries_is_not_searched (1 failed, 19 passed) |
| M3 | `tokens_out` drops the thoughts tokens | killed: test_a_call_records_what_was_searched_and_counted (1 failed, 19 passed) |
| M4 | `brands` counts every mention, not distinct entities | killed: test_a_call_records_what_was_searched_and_counted (1 failed, 19 passed) |
| M5 | the `except Exception` branch is removed | killed: the unexpected-error test and the malformed-ledger test (2 failed, 18 passed) |
| M6 | `existing_outputs` always returns `[]` | killed: the `existing_outputs` test and the refusal test (2 failed, 18 passed) |
| M7 | `run_spend_micros` is the cumulative total | killed: test_the_probe_stops_before_the_crossing_try (1 failed, 19 passed) |
| M8 | `main()` skips the refusal (`if False:`) | killed: test_a_rerun_refuses_to_start_while_outputs_exist (1 failed, 19 passed), by the client guard's `AssertionError` now that `run1.json` exists |
| M9 | `report()` does not tolerate an unreadable ledger | killed: test_partial_results_survive_a_malformed_ledger_line (1 failed, 19 passed) |

**Reviews**, as the ledger records them:
- "Review verdict (2026-10-12): spec review of 6433690 (Opus 5.5): Request changes; one Important (item 144's third cause, a malformed ledger line, still lost the partial results; reproduced by the controller), six minors; fixed in e7cf9ba (decision 4, R1)."
- "Review verdict (2026-10-12): scoped spec re-review of 6433690..e7cf9ba (Opus 5.5): Approve with minors (three: the tolerance's coverage, a null spend number on a run that finishes normally, the mutant re-run sentence); fixed in 3a4a083 (R2)."
- "Review verdict (2026-10-12): plan review of 723aad2 (Opus 5.5): Approve with minors (all 17 blocks byte-identical to the spec's diff; red run, green runs and nine mutants reproduced; two wording minors); fixed in d1c6b4a (R3)."
- "Task 1: Review verdict (2026-10-12): task reviewer (Opus 5.5, agent acd979501a2594132) Spec compliant (all 17 blocks present, nothing extra); Task quality Approved; no Critical, no Important; four minors (the heredoc breach already recorded; the known "2 warnings"; the refusal test covers the results file only; the documented narrow ledger tolerance, spec R2). Cannot-verify item (the probe was never run, no network call) checked by the controller: the worktree has no data/experiments directory and eval/ is unchanged."
- `Final review: Review verdict (2026-10-12): final whole-branch reviewer (Opus 5.5, agent aeca7b437a701b18f) over d1c6b4a..62d9d1b: Ready to merge Yes; no Critical, no Important; the three files byte-identical to the spec's proof diff; one minor (no test checks that main() passes <raw_store_dir>/experiments/engine to existing_outputs), which overlaps the deferred refusal-test minor; both deferred minors triaged "fine to defer".`
- "Docs: Review verdict (2026-10-12): docs review of cfd03d4 (Opus 5.5, agent af26f9366b6f682f0): Changes needed; three Important (findings §1 called five red tests 'new' though one is the modified stop test; the 144 note credited the module docstring with a limit only the spec states; the 143 note said both call() tests assert the whole result, but the no-search test asserts only searched and queries) and three minors (M9 credited for the micros-less row, which no test feeds; the 145 note did not point at the two deferred refusal minors; 'six script-side' though one item is a config comment). All 26 quotes, the counts, the commit and mutation tables and the note placements verified."
- "Docs: Review verdict (2026-10-12): docs re-review of cfd03d4..773a48c (Opus 5.5, agent af26f9366b6f682f0): Approve with minors; all six findings fixed as worded; only the two slice 61 README rows changed; the verbatim check passes both ways (29 quotes); two minors: the §1 counts sentence runs the red list into the mutant count, and R5 quotes a replacement phrase that differs from the one written ("five in the script and its tests, one config comment")."

**Commits** (`git log --oneline --reverse e2b2b8b..63cd214^2`, oldest first):

| Commit | Subject |
|---|---|
| 6433690 | docs(spec): slice 61 engine probe hardening design |
| e7cf9ba | docs(spec): slice 61 spec review round 1 (decision 4, R1) |
| 3a4a083 | docs(spec): slice 61 spec re-review minors (R2) |
| 723aad2 | docs(plan): slice 61 engine probe hardening implementation plan |
| d1c6b4a | docs(plan): slice 61 plan review fixes (R3) |
| 62d9d1b | fix(probe): refuse a re-run over earlier outputs, report this run's spend, keep partial results on any error |

CI (2026-10-12): PR run 38168703166 on 62d9d1b completed success (backend 1810 passed, 2 deselected, 2 warnings; web 91 passed; build compiled). The push run on main after the merge was not checked.

## 2. Live check

None: the probe script was not run (the worktree had no `data/experiments` directory after the task), nothing was called, and nothing was spent.

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim (R1 and R2 were copied into the ledger from the spec, R3 from the plan, when it was created):

> Ruling: R1. Decided: the spec review's findings 2 to 6 are applied as wording and test fixes in a second spec commit: `run()`'s docstring names the three write paths; the module docstring says a failing write replaces the original error (kept as `__context__`) and that the spend numbers are `null` on an unreadable ledger; the refusal test writes a minimal `eval/run1.json` so the client guard is reachable; the mypy claim says what it covers; Section 1 says a re-run in the canonical checkout means moving the tracked slice 56 record. Found by: the spec reviewer (Opus 5.5), 2026-10-12. Why: a docstring that named two paths of three, a guard that could not be reached, a gate claim wider than its coverage, and two behaviours that were true but undocumented, all mine. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R2. Decided: the re-review's three minors are applied as documentation, not as a wider catch: the spec and the module docstring say what the tolerance covers (a line that is not valid JSON, or a probe row without `micros`) and that a null spend number in any results means the ledger could not be read, including on a run that finished without an error; the Evidence sentence says all nine mutants were re-run. Found by: the spec re-reviewer (Opus 5.5), 2026-10-12. Why: a catch of `(ValueError, KeyError)` leaves a non-object JSON line or a null `micros` to raise again, and `spend.record` never writes either; widening it or re-raising on the normal path would change the behaviour the user chose in decision 4. Cost if wrong: for those two shapes the partial results are still lost, as documented. How named: this spec and chat.

> Ruling: R3. Decided: the plan review's two minors are fixed in a second plan commit: Step 5's `git diff --stat` check carries the worktree `cd` prefix, and M6 says the `return` line becomes `return []` with the docstring kept. Found by: the plan reviewer (Opus 5.5), 2026-10-12, verdict Approve with minors (all 17 blocks byte-identical to the spec's diff; the red run, green runs and nine mutants reproduced). Why: a command that would run in the wrong directory under the plan's own cwd rule, and a mutant edit with two readings, both mine. Cost if wrong: none to behaviour. How named: this plan and chat.

> Ruling: R4. Decided: the final whole-branch review is dispatched on the code range d1c6b4a..62d9d1b (one commit, three files), with the merge-base package also written but not handed over. Why: the five docs commits had their own spec and plan reviews, and the final reviewer reads the spec and plan itself. Cost if wrong: the final reviewer would not see the docs diff, which has its own reviews. How named: this ledger and chat.

> Ruling: R5. Decided: the docs review's six findings are fixed in a second docs commit: §1 says five tests fail red, four new and the modified stop test; the 143 note and §1 say one test asserts the whole result with search queries and another asserts `searched` and `queries` without them; the 144 note credits M9 for the invalid-JSON case only, says the micros-less row is handled but untested, and attributes the remaining limit to the spec (R2), not the docstring; the 145 note points at the two deferred refusal minors in findings-slice61 §3; 'six script-side' becomes 'five script-side minors and one config comment' in §1 and the README spec row; the findings quote this verdict and ruling. Found by: the docs reviewer (Opus 5.5), 2026-10-12. Why: three false statements and three loose ones, all mine. Cost if wrong: none to behaviour. How named: ledger and chat.

> Correction to R5 (2026-10-12): R5's fixes landed in two commits, not one: 1f07c0f holds the findings, notes and spec-row edits, and 25a7a76 the README findings row's R1–R5, because the controller's edit script stopped when its range pattern matched an earlier slice's row too and the commit ran without that edit. The second fix was anchored on the slice 61 row's link prefix.

> Correction to R5 (2026-10-12, second): R5 says 'six script-side' becomes 'five script-side minors and one config comment'; the phrase written in findings §1 and the README spec row is 'five in the script and its tests, one config comment'. The fix stands as written; R5's quotation of it was wrong. Under the user's "Fix, stop" choice, the commit that quotes this line, the re-review verdict and that decision, and adds a semicolon to the §1 counts sentence, is unreviewed.

Every `minor (deferred)` line in the ledger, verbatim:

- "Task 1: minor (deferred): the implementer wrote its block-applying helper script (a scratchpad apply.py outside the repo) with a shell heredoc, against the Global Constraint allowing a heredoc only for the commit message; self-reported; no tracked file affected."
  - Note (2026-10-12, slice 62): closed: a process observation about a scratchpad script outside the repo; nothing in the repo to change.
- "Task 1: minor (deferred): test_a_rerun_refuses_to_start_while_outputs_exist creates only the results file, so main() is never tested refusing on a raw directory alone; existing_outputs is tested for that case on its own and M6 kills both tests."
  - Note (2026-10-12, after slice 63, PR #126): fixed: the test is parametrized; its `raw` case leaves only a raw model directory (docs/findings-slice63.md §1).
- `Final review: minor (deferred): no test checks the raw_dir wiring in main() (<raw_store_dir>/experiments/engine passed to existing_outputs); a mistyped path would skip the raw directories while the results file still triggers the refusal.`
  - Note (2026-10-12, after slice 63, PR #126): fixed: the `raw` case uses the last model and asserts the full path, so a wrong raw path, a cut-down model list or a substituted directory fails it (M17 to M19, docs/findings-slice63.md §1).

Still open from findings-slice56 and not in this slice: lines 141, 147, 148 and 149 (docs wording; line 149 is true now that findings-slice56.md exists), all slice 62.

Correction (2026-10-12, slice 62): the line numbers in the line above are as at main e2b2b8b; later dated notes moved them, and findings-slice62.md lists the current lines.
