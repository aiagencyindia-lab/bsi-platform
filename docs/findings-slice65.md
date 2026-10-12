# Slice 65 findings: the two open deferred minors of slice 64

## 1. What was built

Slice 65 closes the two deferred minors that slice 64 left open (docs/findings-slice64.md lines 102 and 103, as at main a456260) by two test edits in PR #130. No product code, migration, API or generated file changed; no live check and no spend. The session ran on Fable 5.1 from the first design question (the user's `/model`); the spec, plan and docs commits carry its trailer, and every dispatch (implementer and reviewers) ran on Opus 5.5.

- **64:102, `! as string`: fixed.** The formSeg scan's variable-key branch is `\bString\([^\n]*?\.get\(\w+\)!?(?:\s+as\s+string)?\)`, so `String(form.get(k)! as string)` fails the scan (M1: green on main, red patched) along with the bare, `!` and `as string` shapes (M2 to M4, red on both). Still not caught, out of scope: `!as string` with no space (Prettier normalises it), `as unknown as string`, `as string | null`, `as String`, `.get( k )` with spaces; `\s+` can cross a newline, which only fails safe.
- **64:103, the bare file name: fixed.** In `test_a_rerun_refuses_to_start_while_outputs_exist`, the `results` case expects `str(engine_probe.OUT)` (the relative `eval/results/engine_probe_v0.json`, since the test `chdir`s to `tmp_path`) and both cases assert `f"exist: {named};" in str(refused.value)`: each case leaves one path, so the two delimiters pin its whole text (decision 5, after the spec review found that the plain substring still passed a refusal naming `data/eval/results/engine_probe_v0.json`). M10 (a prefix directory) is green on main and red patched in `[results]` only; M5 (`p.name`) fails `[raw]` on main and both cases patched; M6 to M9 keep slice 64's outcomes.

Counts: backend 1811 and web 93, unchanged (no test added or removed); tests/unit/test_engine_probe.py 21; api-paths.test.ts 2. Of the ten mutants, M1 and M10 are green on main and red patched; M5 is green-to-red for the `results` case alone; M2 to M4 and M6 to M9 fail on main and patched alike.

Line numbers: the notes this docs PR adds move findings-slice64.md's later lines: its two minors now sit at 64:102 and 64:104, and its closing "Still open" sentence moves down two lines, with a dated note under it saying the two are closed.

Spec: docs/superpowers/specs/2026-10-12-slice65-test-minors-design.md (commits 7ebedb3, fb72895, d67a289; decisions 1 to 5, rulings R1 and R2). Plan: docs/superpowers/plans/2026-10-12-slice65-test-minors.md (commits 01024ee, 49b1f85; R3). Merged via PR #130 (https://github.com/aiagencyindia-lab/bsi-platform/pull/130), main `bd03813`.

**Code**:
- apps/web/src/lib/api-paths.test.ts: the formSeg test's comment and `RAW`.
- tests/unit/test_engine_probe.py: the `results` case's `named` and the anchored assert both cases share.
- 2 files, +6 −5.

**User decisions**, as the ledger records them:

- "User decision (2026-10-12): scope is exactly the two open deferred minors of findings-slice64 (lines 102 and 103 as at main a456260), nothing else; line 101 (the closed /tmp/null minor) stays as it is ("yes" to the understanding note)."
- "User decision (2026-10-12): session model set to Fable 5.1 by `/model claude-fable-5-1` before the first design question; dispatches pass `model: opus`."
- "User decision (2026-10-12): 64:102 widened suffix `!?(?:\s+as\s+string)?` (A), over a won't-fix note (B)."
- "User decision (2026-10-12): 64:103 `named = str(engine_probe.OUT)` (A), over comparing the whole refusal message (B) and a won't-fix note (C)."
- "User decision (2026-10-12): Sections 1 and 2 each approved after their text was shown in chat ("yes"); the plan-mode file recording the design approved (ExitPlanMode)."
- "User decision (2026-10-12): after the spec review, anchor the final assert in both branches as `exist: {named};` (A), over keeping the substring and listing prefix directories as out of scope (B)."
- "User decision (2026-10-12): spec approved ("approved, write the plan")."
- "User decision (2026-10-12): execution subagent-driven ("Yes, subagent-driven")."
- "User decision (2026-10-12): finishing menu answered "2 PR", after the controller ran both gates on add4bd7."
- "User decision (2026-10-12): "check ci then merge" after PR 130 was opened."
- "User decision (2026-10-12): "yes, start the docs PR"."
- "User decision (2026-10-12): after two docs review rounds, "Stop now" over "Re-review" (the user's chosen option, from the two the controller offered; the second round left nothing to fix)."

**Results** (selected ledger lines, quoted; in the ledger only: the header and Context line, the section headings, the pre-flight scan, the ⚠️ resolution line and the "Docs:" lines):

- "Task 1: implementer (Opus 5.5) DONE, commit add4bd7 (BASE 49b1f85); Step 2 vitest 2 passed and pytest 21 passed; all 10 mutants matched their Expected lines; ruff, mypy, typecheck, lint clean; backend gate 1811 passed, 2 deselected, 2 warnings, coverage 100%; web gate exit 0, 93 tests; self-reported departures: test output filtered with grep/sed (lines pasted verbatim), typecheck and lint re-run to /dev/null for exit codes, blocks and mutants read from the brief by script."
- "Task 1: complete (commits 49b1f85..add4bd7, review clean)"
- "Final review: no fix wave (nothing to fix)."
- "Finishing: both gates run by the controller on add4bd7 (started during the final review, which asked for no change): backend 1811 passed, 2 deselected, 2 warnings, coverage 100%, ruff and mypy clean (gate65-final-backend.txt, 09:26:23Z); web gate exit 0, 93 tests (gate65-final-web.txt, 09:30:08Z)."
- "Finishing: branch slice65-test-minors pushed; PR https://github.com/aiagencyindia-lab/bsi-platform/pull/130 opened against main (head add4bd7); CI not checked yet."
- "Finishing: CI run 38230629499 on add4bd7: gates pass (3m36s). PR 130 merged with a merge commit, bd03813 (main); git ls-remote --heads origin slice65-test-minors printed nothing (remote branch deleted); local main fast-forwarded."

**Mutation table** (the spec's Evidence; the implementer's run of the patched column matched it):

| # | Minor | Mutation | main's tests | patched tests |
|---|---|---|---|---|
| M1 | 64:102 | serp actions `const k = "brand_id"; const id = String(form.get(k)! as string);` | green | red: path values are read with formSeg() |
| M2 | 64:102 | `const k = "brand_id"; const id = String(form.get(k));` | red: same test | red: same test |
| M3 | 64:102 | `const k = "brand_id"; const id = String(form.get(k)!);` | red: same test | red: same test |
| M4 | 64:102 | `const k = "brand_id"; const id = String(form.get(k) as string);` | red: same test | red: same test |
| M5 | 64:103 | `main()` joins `p.name` in place of `str(p)` | red: [raw] only | red: [raw] and [results] |
| M6 | 64:103 | `main()` raw path `"experiment" / "engine"` | red: [raw] | red: [raw] |
| M7 | 64:103 | `existing_outputs(OUT, raw_dir, MODELS[:1])` | red: [raw] | red: [raw] |
| M8 | 64:103 | `existing_outputs(OUT, Path("nowhere"), MODELS)` | red: [raw] | red: [raw] |
| M9 | 64:103 | `existing_outputs(Path("nowhere"), raw_dir, MODELS)` | red: [results] | red: [results] |
| M10 | 64:103 | `main()` joins `str(Path("data") / p)` (a prefix directory; review probe X2) | green | red: [results] |

Saved gate outputs: `gate65-backend.txt` (run 2026-10-12T08:17:39Z, after decision 5's edit) and `gate65.txt` (run 2026-10-12T08:09:59Z, before it; valid as Section 2 explains), both on the patched proof copy. The table is the run after decision 5's edit; `mutate65.out` holds only that run, and its M1 to M9 rows equal the first run's as recorded in spec commit 7ebedb3.

**Reviews**, as the ledger records them:

- "Review verdict (2026-10-12): spec review (Opus 5.5) of 7ebedb3: approve after a small fix; no critical or important; finding 1 minor (the substring assert still passed a prefixed directory, reproduced by the controller), finding 2 minor (no whole-test green-to-red mutant for 64:103), finding 3 nit (`!as string` with no space not caught, unlisted)."
- "Review verdict (2026-10-12): spec scoped re-review (Opus 5.5) of fb72895: all three findings resolved and verified by probes; diff identity and saved outputs confirmed; one nit ("M1 to M9 kept their first-run outcomes" not checkable from mutate65.out, which holds only the second run)."
- "Review verdict (2026-10-12): d67a289 (the R2 wording commit) was not reviewed; disclosed in chat."
- "Review verdict (2026-10-12): plan review (Opus 5.5) of 01024ee: Approve with minors; all three blocks reproduce the spec's diff, index hashes included; all ten mutants reproduced on patched and main's tests; one nit (M5's failure order)."
- "Review verdict (2026-10-12): Task 1 task review (Opus 5.5) of 49b1f85..add4bd7: spec ✅, task quality Approved; no critical, important or minor; the commit's Opus 5.5 trailer checked; one ⚠️ item (the mutant and gate results are the report's pasted lines)."
- "Review verdict (2026-10-12): final whole-branch review (Opus 5.5) of a456260..add4bd7: ready to merge (Yes); no critical, important or minor; the code commit's blob hashes match the spec's diff; no deferred minors to triage; it declined to open the proof's saved gate files (the branch-head gates supersede them)."
- "Review verdict (2026-10-12): docs review (Opus 5.5) of b21a7a8: Changes needed; one important (findings §3 said no deferred minor from findings 47 to 64 stays open, but findings-slice62 §3 holds three deferred minors, lines 115 to 117 as at main bd03813, with no closing note anywhere; checked by the controller) and one minor in three parts (the plan's Changes said the task review had "no findings" though it had one ⚠️ item; it omitted the implementer's first departure, `uv sync` and `npm ci` in one call joined by `;`; and it dropped the report's qualifier that FAILED lines were cut at the test id and vitest's leading whitespace dropped). All 26 quotes, the line numbers, the notes, the code claims, the tables, the trailers and the README rows verified; CI facts unverifiable by the reviewer (gh 404)."
- "Review verdict (2026-10-12): docs re-review (Opus 5.5) of b21a7a8..c31b9cd: both findings addressed (the slice 62 minors checked at bd03813, the plan's Changes against the task report); quote check both ways passes (22 required lines, 28 quotes); README range R1–R4 matches; R4 names every change the commit made; no new findings."

**Commits** (`git log --oneline --reverse a456260..bd03813^2`, oldest first):

| Commit | Subject |
|---|---|
| 7ebedb3 | docs: slice 65 spec, the two open deferred minors of slice 64 |
| fb72895 | docs: slice 65 spec, spec review fixes (decision 5, R1) |
| d67a289 | docs: slice 65 spec, re-review wording (R2) |
| 01024ee | docs: slice 65 plan, the two open deferred minors of slice 64 |
| 49b1f85 | docs: slice 65 plan, plan review nit (R3) |
| add4bd7 | test: formSeg scan catches "! as string"; probe refusal test pins the named path |

CI (2026-10-12): PR run 38230629499 on add4bd7, check `gates` passed (3m36s). The push run on main after the merge was not checked.

## 2. Live check

None: the slice changes tests and docs only; nothing was called and nothing was spent.

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim (R1 and R2 were copied into the ledger from the spec, R3 from the plan, when it was created):

> Ruling: R1. Decided: the spec review's findings 2 and 3 are applied in the second spec commit alongside decision 5 (finding 1): M10, the prefix-directory mutant, is added as the whole-test green-to-red proof for 64:103; `String(form.get(k)!as string)` (no space after `!`, which Prettier normalises away) is listed as not caught under Out of scope; Section 1 drops the overstated "requires the path main() names" for the anchored assert's exact effect. Found by: the spec reviewer (Opus 5.5), 2026-10-12; finding 1 reproduced by the controller in the proof. Why: a substring claim wider than what it pinned, a proof that showed only a per-case change, and an unlisted miss, all mine. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R2. Decided: the spec re-review's one nit is applied as wording in a third spec commit, without a further review: the Evidence paragraph says `mutate65.out` holds only the second run and that its M1 to M9 rows equal the first run's as recorded in spec commit 7ebedb3, in place of "kept their first-run outcomes", which the saved files alone could not show. Found by: the spec re-reviewer (Opus 5.5), 2026-10-12, verdict all three findings resolved and verified by probes. Why: a claim resting on a run the saved output no longer holds, mine. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R3. Decided: the plan review's one nit is fixed in a second plan commit: M5's Expected line lists `[results]` before `[raw]`, the order pytest's `-rf` prints them in (the parametrize order), so a pasted line matches word for word. Found by: the plan reviewer (Opus 5.5), 2026-10-12, verdict Approve with minors (all three blocks reproduce the spec's diff, index hashes included; all ten mutants' Expected lines reproduced on the patched tests, and the main's-tests column too). Why: a failure list in the wrong order, mine. Cost if wrong: none to behaviour. How named: this plan and chat.

> Ruling: R4. Decided: the docs review's two findings are fixed in a second docs commit: findings §3's closing sentence says only what the sources show (the two findings-slice64 minors closed, none added, findings-slice63 §3 covering 47 to 61 and its own four closed by slice 64) and names findings-slice62's three deferred minors (lines 115 to 117 as at main bd03813) as open and outside this slice's scope, which the user set as exactly the two; the plan's Changes say the task review approved with no critical, important or minor finding and that its one ⚠️ item was resolved by the controller, list the implementer's four departures including `uv sync` and `npm ci` in one call, and carry the report's qualifier on the pasted lines; the README findings row's ruling range becomes R1–R4 in this same commit; the findings quote this verdict and ruling. Found by: the docs reviewer (Opus 5.5), 2026-10-12; the slice 62 minors checked by the controller. Why: a closing claim wider than its sources and three loose paraphrases, all mine. Cost if wrong: none to behaviour; findings-slice62's three minors stay open and unlisted elsewhere until a slice takes them. How named: ledger and chat.

Deferred minors: none. The task review and the final review recorded no `minor (deferred)` line, so the ledger holds none to quote.

Still open: the two minors of findings-slice64 are closed and this slice adds none; findings-slice63 §3 says none of findings 47 to 61 stays open, and its own four minors were closed by slice 64. Not covered by any of that: findings-slice62 §3's three deferred minors (lines 115 to 117 as at main bd03813; the shared won't-fix wording, the warning texts' dropped final period, and the "current lines" pointer) have no closing note and stay open; they are outside this slice's scope (decision 1).

Note (2026-10-13, after slice 66, PR #132): findings-slice62's three deferred minors (lines 115 to 117) are closed by slice 66 (docs/findings-slice66.md).
