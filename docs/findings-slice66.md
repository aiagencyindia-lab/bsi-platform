# Slice 66 findings: the three open deferred minors of slice 62

## 1. What was built

Slice 66 closes the three deferred minors that slice 62 left open (docs/findings-slice62.md lines 115 to 117, as at main 752a234) with six dated notes in PR #132: 6 lines added, none removed, no historical text edited, no code. With them, no deferred minor from findings 47 to 66 is open. The brainstorm, proof, spec and plan ran on Fable 5.1; the session switched to Opus 5.5 (the user's `/model`) before execution, so the notes commit and this docs PR carry the Opus 5.5 trailer (R5). The controller wrote the notes (decision 5), and an Opus 5.5 docs review approved the branch with no findings.

- **62:115, the shared won't-fix sentence: closed.** Notes under findings-slice48:78, findings-slice50:72 and findings-slice51:80 (each after the slice 62 note) say what each line raises: the repo states the classification line (the slice 48 spec, line 13), the chat approvals and the ledger quotes but cannot check them, since the chat and the ledger are not in it; the backend counts' record is the merged PRs' CI runs; 48:78 names no count. A note under 62:115 points at them.
- **62:116, the dropped final period: corrected.** A Correction under 62:116 gives both pytest warning texts with their period and names the five findings notes that quote them without it (findings-slice57 line 159, findings-slice59 lines 131 and 139, findings-slice60 lines 140 and 148). The slice 62 spec and plan carry the same quotes and stay as they are (historical, out of scope).
- **62:117, the "current lines" pointer: closed.** A note under 62:117 says the mapping at findings-slice62 lines 9 to 11 listed every line the two corrected paragraphs (findings-slice60 line 150 and findings-slice61 line 108 at main 752a234) cite, that all eleven targets are unchanged, and that slice 63 moved one table row and four open-list lines. The re-map below is the list that note points at.

**Re-map** of every line findings-slice62 lists (its numbers are as at main 929ae35), to main 752a234, each found by matching the line's text at 929ae35. 41 lines: 23 table rows, 11 mapping targets, 7 open-list lines; 5 moved, all by slice 63's notes:

| List | At 929ae35 | At 752a234 | Table label |
|---|---|---|---|
| table (lines 17 to 39) | 48:78 | 48:78 | Unverifiable |
| table (lines 17 to 39) | 50:72 | 50:72 | Unverifiable |
| table (lines 17 to 39) | 51:80 | 51:80 | Unverifiable |
| table (lines 17 to 39) | 54:79 | 54:79 | Docs wording |
| table (lines 17 to 39) | 55:117 | 55:117 | Docs wording |
| table (lines 17 to 39) | 55:119 | 55:119 | Docs wording |
| table (lines 17 to 39) | 55:123 | 55:123 | Process |
| table (lines 17 to 39) | 56:141 | 56:141 | Docs wording |
| table (lines 17 to 39) | 56:153 | 56:153 | Docs wording |
| table (lines 17 to 39) | 56:155 | 56:155 | Docs wording |
| table (lines 17 to 39) | 56:157 | 56:157 | Docs wording |
| table (lines 17 to 39) | 57:158 | 57:158 | 2 warnings |
| table (lines 17 to 39) | 57:165 | 57:165 | Process |
| table (lines 17 to 39) | 58:125 | 58:125 | Process |
| table (lines 17 to 39) | 58:127 | 58:127 | Process |
| table (lines 17 to 39) | 59:120 | 59:120 | Double seg() |
| table (lines 17 to 39) | 59:130 | 59:130 | 2 warnings |
| table (lines 17 to 39) | 59:138 | 59:138 | 2 warnings |
| table (lines 17 to 39) | 59:144 | 59:144 | Double seg() |
| table (lines 17 to 39) | 59:146 | 59:146 | Process |
| table (lines 17 to 39) | 60:139 | 60:139 | 2 warnings |
| table (lines 17 to 39) | 60:144 | 60:147 | 2 warnings |
| table (lines 17 to 39) | 61:101 | 61:101 | Process |
| mapping (lines 9 to 11) | 57:156 | 57:156 | — |
| mapping (lines 9 to 11) | 57:158 | 57:158 | — |
| mapping (lines 9 to 11) | 57:160 | 57:160 | — |
| mapping (lines 9 to 11) | 59:120 | 59:120 | — |
| mapping (lines 9 to 11) | 59:130 | 59:130 | — |
| mapping (lines 9 to 11) | 59:138 | 59:138 | — |
| mapping (lines 9 to 11) | 59:144 | 59:144 | — |
| mapping (lines 9 to 11) | 56:141 | 56:141 | — |
| mapping (lines 9 to 11) | 56:153 | 56:153 | — |
| mapping (lines 9 to 11) | 56:155 | 56:155 | — |
| mapping (lines 9 to 11) | 56:157 | 56:157 | — |
| open list (line 41) | 49:108 | 49:108 | — |
| open list (line 41) | 49:109 | 49:110 | — |
| open list (line 41) | 60:141 | 60:141 | — |
| open list (line 41) | 60:142 | 60:143 | — |
| open list (line 41) | 60:143 | 60:145 | — |
| open list (line 41) | 61:103 | 61:103 | — |
| open list (line 41) | 61:104 | 61:105 | — |

Line numbers after this slice: in findings-slice62 the three minors now sit at lines 115, 117 and 119 with their notes at 116, 118 and 120; findings-slice48, 50 and 51 each grow by one line from 80, 74 and 82. Nothing in the repo cites those shifted lines except the historical `48:81` in findings-slice59 lines 63 and 114 and the slice 59 spec line 10, already stale since slice 62. This docs PR also adds a dated note under findings-slice65's closing "Still open" sentence, which named the three as open.

Spec: docs/superpowers/specs/2026-10-13-slice66-docs-minors-design.md (commits da1dfe3, 451e0cb, 41c2fc0, 905eaa5, 01a0a95; decisions 1 to 9, rulings R1 to R4 and a Correction to R2). Plan: docs/superpowers/plans/2026-10-13-slice66-docs-minors.md (commits 82d8ea5, 3bf7dbf; its own R1, quoted in the ledger as "R1 (plan)"). R5 and R6 were made at execution. Merged via PR #132 (https://github.com/aiagencyindia-lab/bsi-platform/pull/132), main `5722d4b`.

**User decisions**, as the ledger records them:

- "User decision (2026-10-13): scope is exactly the three open deferred minors of findings-slice62 §3 (lines 115 to 117 as at main 752a234) ("yes" to the understanding note)."
- "User decision (2026-10-13): 62:115 closed by a dated note under each of findings-slice48:78, 50:72 and 51:80 (A), over one Correction in findings-slice62 only (B)."
- "User decision (2026-10-13): 62:116 closed by one Correction under 62:116 with the two exact messages (A), over a note under each of the five (B)."
- "User decision (2026-10-13): 62:117 closed by a note plus a full re-map in findings-slice66 §1 (A), over a pointer-only note (B)."
- "User decision (2026-10-13): execution controller-written, docs-PR style (A), over subagent-driven (B)."
- "User decision (2026-10-13): Sections 1 and 2 each approved after their text was shown in chat ("yes"); the plan-mode file approved (ExitPlanMode)."
- "User decision (2026-10-13): after the spec review, revised notes 1 to 3 and 6 ("yes", decision 7)."
- "User decision (2026-10-13): after the re-review, revised note 6 naming the two corrected paragraphs ("yes", decision 8)."
- "User decision (2026-10-13): after the second re-review, note 6 dates those line numbers "at main 752a234" ("yes", decision 9)."
- "User decision (2026-10-13): spec approved ("approved, write the plan")."
- "User decision (2026-10-13): session model switched to Opus 5.5 by `/model claude-opus-5-5`; plan approved ("Yes, go ahead")."
- "User decision (2026-10-13): finishing menu answered "2 PR", after the controller ran both gates on 3f7bdd8."
- "User decision (2026-10-13): "check ci then merge" after PR 132 was opened."
- "User decision (2026-10-13): "yes, start the docs PR"."

**Results** (selected ledger lines, quoted; in the ledger only: the header and Context line, the section headings and the "Docs:" lines):

- "Task 1: Step 1 applied the four blocks by script (each occurred once); Step 2 first run 33 ok, 1 FAIL (the plan's line-9 expectation, R6); after R6 the check prints ALL OK."
- "Task 1: Step 3 commit 3f7bdd8 (BASE 3bf7dbf): the six notes, +6/-0 over four findings files, banned grep clean, Opus 5.5 trailer (R5)."
- "Task 1: Step 4 on 3f7bdd8: pre-check (its own command) listed pytest 8878 and 8879 with cwd invoice-processing, none of this repo; backend 1811 passed, 2 deselected, 2 warnings, coverage 100%, ruff and mypy clean, gate exit 0; both warning texts found once with the final period; web gate 93 tests, gate exit 0 (gate66-branch-backend.txt, gate66-branch-web.txt)."
- "Task 1: complete (commits 3bf7dbf..3f7bdd8, docs review clean; no fix commit needed)."
- "Finishing: branch slice66-docs-minors pushed; PR https://github.com/aiagencyindia-lab/bsi-platform/pull/132 opened against main (head 3f7bdd8); CI not checked yet."
- "Finishing: CI run 38303089520 on 3f7bdd8: gates pass (3m45s). PR 132 merged with a merge commit, 5722d4b (main); git ls-remote --heads origin slice66-docs-minors printed nothing (remote branch deleted); local main fast-forwarded."

**Reviews**, as the ledger records them:

- "Review verdict (2026-10-13): spec review (Opus 5.5) of da1dfe3: not ready; I1 important (note 6 closed 62:117 on the table, not the mapping the pointers name; the open list's four moved lines unmentioned) and I2 important (note 1 said the repo holds no record of the classification line, which the slice 48 spec line 13 holds), both verified by the controller; five minors."
- "Review verdict (2026-10-13): spec re-review (Opus 5.5) of 451e0cb: I1, I2 and the five minors resolved; N1 important (note 6's "every line §3 cites" overstated the mapping; findings-slice60 §3 also cites 57:153, 58:127 and 59:127), verified by the controller; four minors."
- "Review verdict (2026-10-13): second spec re-review (Opus 5.5) of 41c2fc0: N1 to N5 resolved except part of N4; four minors, one (M3) changing note 6's text: its line numbers 150 and 108 sat after "as at main 929ae35", where they were 147 and 106, verified by the controller."
- "Review verdict (2026-10-13): third spec re-review (Opus 5.5) of 905eaa5: M1 to M4 resolved, diff block identical to the proof; two minors (the Proof bullet named only decision 8; the two Out of scope bullets disagreed)."
- "Review verdict (2026-10-13): 01a0a95 (the R4 wording commit) was not reviewed; disclosed in chat."
- "Review verdict (2026-10-13): plan review (Opus 5.5) of 82d8ea5: Revise; I1 important (the pre-check's `pgrep -f 'python -m pytest'` cannot see a `uv run pytest`, and ran inside the gate it should precede), verified live by the controller; four minors; the four blocks reproduce the spec's diff."
- "Review verdict (2026-10-13): 3bf7dbf (the plan's R1 fix commit) was not reviewed; disclosed in chat."
- "Review verdict (2026-10-13): docs review (Opus 5.5) of 752a234..3f7bdd8: Approve; no important or minor findings; all six notes verified against the repo (the slice 48 spec line 13, the ledger quotes, the CI counts as the findings quote them, both warning texts with periods in gate66-branch-backend.txt lines 37 and 41, the five quoting notes, the mapping and its eleven targets, the five moved lines); three observations, no fix: the trailer differs from the plan (covered by R5), note 6 points at findings-slice66.md which arrives with the docs PR (decision 4), and gh returned 404 for the CI runs."

**Commits** (`git log --oneline --reverse 752a234..5722d4b^2`, oldest first):

| Commit | Subject |
|---|---|
| da1dfe3 | docs: slice 66 spec, the three open deferred minors of slice 62 |
| 451e0cb | docs: slice 66 spec, spec review fixes (decision 7, R1) |
| 41c2fc0 | docs: slice 66 spec, re-review fixes (decision 8, R2) |
| 905eaa5 | docs: slice 66 spec, second re-review fixes (decision 9, R3) |
| 01a0a95 | docs: slice 66 spec, third re-review wording (R4) |
| 82d8ea5 | docs: slice 66 plan, the three open deferred minors of slice 62 |
| 3bf7dbf | docs: slice 66 plan, plan review fixes (R1) |
| 3f7bdd8 | docs: close the three open deferred minors of slice 62 with dated notes |

CI (2026-10-13): PR run 38303089520 on 3f7bdd8, check `gates` passed (3m45s). The push run on main after the merge was not checked.

## 2. Live check

None: the slice changes docs only; nothing was called and nothing was spent.

## 3. Rulings and deferred minors

Every `Ruling:` and `Correction` line in the ledger, verbatim, in ledger order (R1 to R4 and the Correction to R2 were copied into the ledger from the spec, the plan's R1 from the plan, when it was created; R5 and R6 were made at execution):

> Ruling: R1. Decided: the spec review's five minors are applied in the second spec commit alongside decision 7: the Context opens "After slices 62 to 65 …" (slice 62 closed most of the earlier minors; the redirect and /tmp/null minors closed within their own slices); the backend gate is re-run with the `lsof` result and both gates' exit statuses written into the saved files; Section 1 item 5 carries the diff's exact text and cites gate66-backend.txt; the line-shift statement names all four files and the grep that found nothing citing the shifted lines; the Correction says "five findings notes from slice 62" and Section 1 notes the slice 62 spec and plan carry the same quotes, out of scope. Found by: the spec reviewer (Opus 5.5), 2026-10-13. Why: an overstated opener, two provenance gaps, a text that drifted from its diff, a statement covering one file of four, and a phrase with two readings, all mine. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R2. Decided: the spec re-review's four minors are applied in the third spec commit alongside decision 8 (finding N1): Section 1 item 5 cites gate66-backend.txt lines 34 and 38 and is delimited with double backticks so its inner backticks render; the line-shift statement names the three historical `48:81` citations below the inserts and quotes "findings-slice48 lines 13 and 77" in full; decision 7 now names the Context bullet, the PR 2 scope, the Evidence additions and the web gate re-run that came with it, which R1 and decision 7 had left out; the Evidence says decision 8 changed one note's text only, which the gates do not read. This commit also carries the decision 8 texts (note 6 in Section 1, the Context bullet, the diff block), decision 8 itself and this ruling. Found by: the spec re-reviewer (Opus 5.5), 2026-10-13; N1 and the `48:81` citations verified by the controller. Why: a wrong line citation, a false "finds nothing", a decision and a ruling that named only part of their commit, and a code span with inner backticks, all mine. Cost if wrong: none to behaviour. How named: this spec and chat.

> Correction to R2 (2026-10-13): R2 says "the Evidence says decision 8 changed one note's text only"; that sentence went into Section 2's Proof bullet, and the Evidence section's closing sentence was left unqualified until the fourth spec commit. R2 and decision 7 also left unnamed the edit 451e0cb made to the Out of scope bullet ("and the slice 62 spec and plan that carry the same quotes").

> Ruling: R3. Decided: the second re-review's three wording minors are applied in the fourth spec commit alongside decision 9 (finding M3): the Departures bullet says items 1 to 3 are decision 7's texts and item 6 decision 8's, adjusted by decision 9; the Evidence's closing sentence says the gates ran on the decision 7 texts and that decisions 8 and 9 changed note 6 only, which the gates do not read; the Correction to R2 above names R2's misplaced sentence and the unnamed Out of scope edit. This commit also carries the decision 9 text (note 6 in Section 1 and the diff block), decision 9 itself, the Correction to R2 and this ruling; nothing else changes. Found by: the second spec re-reviewer (Opus 5.5), 2026-10-13; M3 verified by the controller. Why: a stale departure, a ruling that placed a change in the wrong section, an unqualified provenance sentence and an unnamed edit, all mine. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R4. Decided: the third re-review's two minors are applied in the fifth spec commit, without a further review: Section 2's Proof bullet says decisions 8 and 9 (not 8 alone) changed note 6 after the gates ran, matching the Evidence; Section 2's Out of scope bullet names the slice 62 spec and plan, matching the `## Out of scope` section (the Correction to R2's "Out of scope bullet" means that section's). Nothing else changes in this commit. Found by: the third spec re-reviewer (Opus 5.5), 2026-10-13. Why: two sentences left behind by the decision 9 edit, mine. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R1 (plan). Decided: the plan review's important finding and four minors are fixed in a second plan commit: Step 4's pytest pre-check runs as its own command before the gate, matches `bin/pytest|-m pytest` (a `uv run pytest` never shows `python -m pytest`; checked by the controller with a live `uv run pytest --co`, which the old pattern missed and the new one listed with its cwd), prints every match's cwd, and stops when any cwd is a checkout of this repo (main, any bsi-wt worktree, any scratchpad proof copy, all sharing bsi_test); the Global Constraints say the same; Review Focus 4 points at Step 4 and Step 4 greps both warning texts; Step 2 item 4 compares each moved line's and each mapping target's text at 929ae35 with its stated line at 752a234 and names the slice 48 spec's path; Step 2 item 3 says the positions are matched by text and gives the post-insert lines. Found by: the plan reviewer (Opus 5.5), 2026-10-13. Why: a guard pattern that could not see the process it guards, a check inside the run it should precede, and four imprecise check descriptions, all mine. Cost if wrong: none to behaviour; a wrong pre-check could let two pytests share bsi_test and deadlock. How named: this plan and chat.

> Ruling: R5. Decided: the plan's Global Constraint and Step 3 name the Fable 5.1 trailer for the controller's commits; from the user's switch to Opus 5.5 the controller's commits carry the Opus 5.5 trailer, the session's actual model, and reviewer dispatches omit the Agent model param. Why: the trailer records which model made the commit, and the plan was written before the switch. Cost if wrong: one commit trailer naming the other model. How named: ledger and chat.

> Ruling: R6. Decided: the plan's Step 2 item 4 expects findings-slice62 line 9 to start `- findings-slice60 §3`; at main 752a234 line 9 is the mapping's heading ("The two corrected paragraphs, mapped to main `929ae35`:") and lines 10 and 11 are its two bullets, so note 6's "lines 9 to 11" is right and the plan's expectation is wrong; the check script checks the heading at 9 and the bullets at 10 and 11, and the plan is not edited (its "Changes made during execution" will say so). Found by: the controller's Step 2 run (one FAIL). Why: a check line I wrote from memory of the reviewer's report, not from the file. Cost if wrong: none to behaviour; the notes are unchanged. How named: ledger and chat.

Deferred minors: none. Under the user's rule of 2026-10-13 (minors found in touched files are fixed in the slice), no review produced a `minor (deferred)` line, and the docs review had no finding.

Still open: no deferred minor from findings 47 to 66. A scripted scan of findings-slice47.md to findings-slice66.md for `minor (deferred)` list items with no dated note or Correction directly after them finds two, both closed in their own file's §3: findings-slice63 line 139 (closed by that slice's R4) and findings-slice64 line 101 (closed in that file's closing sentence). The last three open ones, findings-slice62 lines 115 to 117, are closed above.
