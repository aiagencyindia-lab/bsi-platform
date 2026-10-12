# Slice 66 design: the three open deferred minors of slice 62

Classification: architectural, said first in chat on 2026-10-13, before the first question: six dated notes in historical findings files, which the skill would call bounded, but this project gives every slice a spec and a plan ("brainstorm + spec even for small changes"), and slice 62, the previous docs-only slice, took the same path. Session model Fable 5.1 (the user's `/model` during slice 65; said at the start of this brainstorm); reviewer dispatches pass `model: opus`; controller commits carry the Fable 5.1 trailer.

## Context

After slices 62 to 65, every deferred minor of findings 47 to 65 is closed except three in docs/findings-slice62.md §3, which no slice had scoped. Lines as at main 752a234:

- docs/findings-slice62.md:115: the shared won't-fix text slice 62 put under findings-slice48:78, findings-slice50:72 and findings-slice51:80 lists "chat approvals, ledger quotes, or a count from an offline run", but 48:78 also names the classification line and 51:80 the proof directory, and 48:78 names no count for "the merged PR's CI run" to attach to.
- docs/findings-slice62.md:116: the two quoted warning texts drop the messages' final period (in five slice 62 notes: findings-slice57:159, findings-slice59:131 and :139, findings-slice60:140 and :148).
- docs/findings-slice62.md:117: findings-slice60.md and findings-slice61.md point at findings-slice62.md for the current lines, "which must list them". The two Corrections (findings-slice60:152, findings-slice61:110) point at findings-slice62's mapping (lines 9 to 11, eleven targets, as at main 929ae35), which lists every line the two corrected paragraphs (findings-slice60 line 150, findings-slice61 line 108) cite, not every line those §3 sections cite elsewhere; all eleven are unchanged at main 752a234. Slice 63's notes since moved one row of findings-slice62's table (lines 17 to 39: 60:144 → 60:147) and four lines of its open list (line 41: 49:109 → 110, 60:142 → 143, 60:143 → 145, 61:104 → 105).

The slice changes docs only: six dated notes in four findings files; no code, no migration, no API change, no spend, no live check. Backend 1811 and web 93 are unchanged.

User decisions (2026-10-13), with the approaches text shown in chat before each choice:
1. Scope: exactly these three ("yes" to the understanding note).
2. 62:115: a dated note under each of the three lines, saying what that line raises (A), over one Correction paragraph in findings-slice62 only (B).
3. 62:116: one Correction under 62:116 with the two exact messages and the five notes named (A), over a note under each of the five (B).
4. 62:117: a closed note plus a full re-map table in findings-slice66 §1 (A), over a pointer-only note (B).
5. Execution: controller-written, docs-PR style (A), over subagent-driven as slice 62 (B): the notes are dated notes in `docs/findings-*.md`, which the controller writes in every docs PR, and the harness has refused subagent `Write`s to those files. The branch gets an Opus 5.5 docs review, one fix commit and a scoped re-review.
6. Sections 1 and 2 each approved after their text was shown in chat ("yes"); the plan-mode file recording the design approved (ExitPlanMode).
7. After the spec review (findings I1 and I2, both verified by the controller against findings-slice62 lines 7 to 11, the two Corrections and the slice 48 spec): notes 1 to 3 say the repo states the classification line, chat approvals and ledger quotes but cannot check them, and note 6 closes 62:117 on the mapping, not the table, naming the moved table row and the four moved open-list lines ("yes" to the revised texts). With it, the 62:117 Context bullet, PR 2's re-map scope and the Evidence re-map were widened to the mapping targets and the open list, and both gates were re-run.
8. After the spec re-review (finding N1, verified by the controller: findings-slice60 §3 also cites 57:153, 58:127 and 59:127 outside its corrected paragraph, none in the mapping): note 6 says the mapping listed every line the two corrected paragraphs (findings-slice60 line 150, findings-slice61 line 108) cite ("yes" to the revised note 6).

Standing rule since 2026-10-13 (the user's "go with A fix it that time"): a reviewer's Minor in a file the slice touches is fixed in that round's fix commit, never deferred.

## Section 1 — The notes

Form: `  - Note (2026-10-13, slice 66): …` as a sub-bullet under the minor's list item, the form slice 62's own notes used for notes landing in the slice's own PR; `Correction (…)` for 62:116. Historical text is never edited. Where the minor is already followed by its slice 62 note (48:78, 50:72, 51:80), the new note goes after that note, so the notes read in date order.

1. findings-slice48.md, after the slice 62 note under line 78: `correction to the slice 62 note: this line names the classification line (the slice 48 spec, line 13), the chat approvals and the ledger quotes, which the repo states but cannot check, since the chat and the ledger are not in it; it names no count, so the merged PR's CI run is not its record.`
2. findings-slice50.md, after the slice 62 note under line 72: `correction to the slice 62 note: this line names the chat approvals, which the repo states as ledger quotes but cannot check, and the backend count "1753 passed, 2 deselected", whose record is the merged PR's CI run.`
3. findings-slice51.md, after the slice 62 note under line 80: `correction to the slice 62 note: this line names the proof directory (written only by the controller, not in the repo), the chat approvals, which the repo states as ledger quotes but cannot check, and the backend count, whose record is the merged PR's CI run.`
4. findings-slice62.md, after line 115: `closed: per-line notes under findings-slice48 line 78, findings-slice50 line 72 and findings-slice51 line 80 say what each line raises.`
5. findings-slice62.md, after line 116 (a Correction): ``the two messages end with a period: "Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead." and "The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead." The five findings notes from slice 62 that quote them without it (findings-slice57 line 159, findings-slice59 lines 131 and 139, findings-slice60 lines 140 and 148, as at main 752a234) are otherwise accurate.`` The texts are as pytest prints them (gate66-backend.txt lines 34 and 38). The slice 62 spec and plan carry the same period-less quotes; they are historical records and out of scope.
6. findings-slice62.md, after line 117: `closed: the mapping above (lines 9 to 11) listed every line the two corrected paragraphs (findings-slice60 line 150, findings-slice61 line 108) cite, as at main 929ae35, and all eleven targets are unchanged at main 752a234; slice 63's notes moved one table row (60:144 → 60:147) and four open-list lines (49:109 → 110, 60:142 → 143, 60:143 → 145, 61:104 → 105), which findings-slice66.md §1 maps.`

The exact texts are in The change below. The notes shift later lines: findings-slice48 from line 80, findings-slice50 from line 74, findings-slice51 from line 82, and findings-slice62 by one, two and three from line 116; a `git grep` for those files' line numbers in the `NN:LL` and `findings-sliceNN line LL` forms finds, below the inserts, only the historical `48:81` in findings-slice59 lines 63 and 114 and the slice 59 spec line 10, already stale since slice 62's note moved that line; above the inserts, "findings-slice48 lines 13 and 77".

## Section 2 — Proof, reviews, the docs PR, out of scope

- Proof: a fresh scratchpad copy of main 752a234 (`proof66`); the six notes applied by `notes66.py`, which asserts each anchor occurs once and places the note as Section 1 says. `git diff --numstat` shows +6/−0 over the four files (1, 1, 1, 3); no line is removed; the banned-word grep over the added lines prints nothing. Both gates pass on the copy (docs do not feed them): backend 1811 passed, 2 deselected, 2 warnings, metrics coverage 100.00%, `ruff format --check` (185 files already formatted), `ruff check` and `mypy` clean, with the `lsof` cwd check of running pytests inside the gate command, its result ("no pytest running") and the gate's exit status written into the saved file; web `npm run gate` exits 0 with 93 vitest, exit status saved too. Outputs saved beside the proof as `gate66-backend.txt` and `gate66.txt`, each headed with its UTC run time (the notes carry the user's local date, 2026-10-13 IST); both ran after the revised notes of decision 7 were applied; decision 8 then changed one note's text in findings-slice62.md only, which neither gate reads. No mutants: there is no behaviour to pin.
- Reviews (decision 5): this spec gets an Opus 5.5 review and a scoped re-review, then the user's approval; the plan one review; then the controller applies the plan's blocks on the branch and commits, and the branch gets an Opus 5.5 docs review, one fix commit and a scoped re-review. Minors in touched files are fixed in that fix commit (the standing rule).
- PR 1 (the slice): the six notes, this spec and the plan. PR 2 (docs): findings-slice66.md with the re-map (every row of findings-slice62's table at lines 17 to 39, every target of its mapping at lines 9 to 11, and every line of its open list at line 41 → its line at main 752a234, each checked by matching the line's text at 929ae35 to its position now: 23 table rows with one moved, eleven mapping targets all unchanged, seven open-list lines with four moved), the new positions of findings-slice62's §3 lines after the three notes (115, 117, 119 for the minors; 116, 118, 120 for the notes), the plan's "Changes made during execution" and README rows.
- Out of scope: the five warning-text notes themselves (corrected once, decision 3); any code; any other findings file.

## The change

Generated from the proof (a scratchpad copy of main 752a234 with the notes applied) with `git diff`, over the four files:

```diff
diff --git a/docs/findings-slice48.md b/docs/findings-slice48.md
index e4187a2..37160da 100644
--- a/docs/findings-slice48.md
+++ b/docs/findings-slice48.md
@@ -77,6 +77,7 @@ Every `minor (deferred)` line in the ledger, verbatim:
 
 - "minor (deferred): spec review minor 6, the classification line, the chat approvals and the ledger quotes cannot be checked from the repo (R2)."
   - Note (2026-10-12, slice 62): won't-fix: what this line names (chat approvals, ledger quotes, or a count from an offline run) left no record in the repo to check against; the merged PR's CI run is the record of its gates.
+  - Note (2026-10-13, slice 66): correction to the slice 62 note: this line names the classification line (the slice 48 spec, line 13), the chat approvals and the ledger quotes, which the repo states but cannot check, since the chat and the ledger are not in it; it names no count, so the merged PR's CI run is not its record.
 - "Task 1: minor (deferred): a host the pattern passes but the API refuses (an IP address, walkaroo., www.walkaroo) lands on the error page, not an inline message; the user chose this (browser pattern over catch-and-note)."
   - Note (2026-10-08, after slice 54, PR #108): fixed; a 422 or 409 from the add-domain post now redirects to the Brand SERP page with a note, reversing the browser-pattern decision above with the user's approval of the slice 54 design (docs/findings-slice54.md §1). Two simultaneous submits still reach the error page through the unique-constraint 500 (R2 above).
 - "Task 1: minor (deferred): a missing brand_id becomes the string "null" and posts to /brands/null/domains; the hidden field always sets it, and runSerpAudit has the same pattern."
diff --git a/docs/findings-slice50.md b/docs/findings-slice50.md
index a360768..ac75ae7 100644
--- a/docs/findings-slice50.md
+++ b/docs/findings-slice50.md
@@ -71,5 +71,6 @@ Every `minor (deferred)` line in the ledger, verbatim:
 
 - "minor (deferred): spec review minor 5, the chat approvals and the backend count "1753 passed, 2 deselected" cannot be checked from the repo offline (R1)."
   - Note (2026-10-12, slice 62): won't-fix: what this line names (chat approvals, ledger quotes, or a count from an offline run) left no record in the repo to check against; the merged PR's CI run is the record of its gates.
+  - Note (2026-10-13, slice 66): correction to the slice 62 note: this line names the chat approvals, which the repo states as ledger quotes but cannot check, and the backend count "1753 passed, 2 deselected", whose record is the merged PR's CI run.
 - "Task 1: minor (deferred): the api long-path test checks the logged text's length (200) but not its content, so a wrong slice offset in the guard's log alone would pass; the seg long-value test checks the content through the shared shown() (plan-mandated)."
   - Note (2026-10-08, after slice 51, PR #104): fixed; the test now uses a path with a double quote and asserts the exact logged text (docs/findings-slice51.md §1).
diff --git a/docs/findings-slice51.md b/docs/findings-slice51.md
index 6521b64..49213f9 100644
--- a/docs/findings-slice51.md
+++ b/docs/findings-slice51.md
@@ -79,5 +79,6 @@ Every `minor (deferred)` line in the ledger, verbatim:
 
 - "minor (deferred): spec review notes, the proof directory being written only by the controller, the chat approvals and the backend count cannot be checked from the repo offline (R2)."
   - Note (2026-10-12, slice 62): won't-fix: what this line names (chat approvals, ledger quotes, or a count from an offline run) left no record in the repo to check against; the merged PR's CI run is the record of its gates.
+  - Note (2026-10-13, slice 66): correction to the slice 62 note: this line names the proof directory (written only by the controller, not in the repo), the chat approvals, which the repo states as ledger quotes but cannot check, and the backend count, whose record is the merged PR's CI run.
 - "minor (deferred): final review minor 1, the long-path test's toHaveBeenCalledWith matches any console.error call, not call 0; expect(log).toHaveBeenCalledTimes(1) would pin it; the guard logs once today (R7)."
   - Note (2026-10-08, after slice 52, PR #106): fixed; the long-path test asserts `toHaveBeenCalledTimes(1)` before its `toHaveBeenCalledWith` (docs/findings-slice52.md §1).
diff --git a/docs/findings-slice62.md b/docs/findings-slice62.md
index 6a3eeec..b64e40b 100644
--- a/docs/findings-slice62.md
+++ b/docs/findings-slice62.md
@@ -113,5 +113,8 @@ Every `Ruling:` line in the ledger, verbatim (R1 and R2 were copied into the led
 Every `minor (deferred)` line in the ledger, verbatim:
 
 - "Task 1: minor (deferred): the shared won't-fix text under 48:78, 50:72 and 51:80 lists "chat approvals, ledger quotes, or a count from an offline run", but 48:78 also names the classification line and 51:80 the proof directory, and 48:78 names no count for "the merged PR's CI run" to attach to (plan-mandated wording, no wrong fact)."
+  - Note (2026-10-13, slice 66): closed: per-line notes under findings-slice48 line 78, findings-slice50 line 72 and findings-slice51 line 80 say what each line raises.
 - "Task 1: minor (deferred): the two quoted warning texts drop the messages' final period (plan-mandated, cosmetic)."
+  - Correction (2026-10-13, slice 66): the two messages end with a period: "Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead." and "The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead." The five findings notes from slice 62 that quote them without it (findings-slice57 line 159, findings-slice59 lines 131 and 139, findings-slice60 lines 140 and 148, as at main 752a234) are otherwise accurate.
 - "Final review: minor (deferred): findings-slice60.md and findings-slice61.md point at findings-slice62.md for the current lines; that file arrives with the post-merge docs PR, which must list them."
+  - Note (2026-10-13, slice 66): closed: the mapping above (lines 9 to 11) listed every line the two corrected paragraphs (findings-slice60 line 150, findings-slice61 line 108) cite, as at main 929ae35, and all eleven targets are unchanged at main 752a234; slice 63's notes moved one table row (60:144 → 60:147) and four open-list lines (49:109 → 110, 60:142 → 143, 60:143 → 145, 61:104 → 105), which findings-slice66.md §1 maps.
```

## Evidence

Proof directory: a fresh scratchpad detached worktree of main 752a234 (`proof66`), written only by the controller through `notes66.py` (assert-counted anchors). Checks run on it: `git diff --numstat` = `1 0`, `1 0`, `1 0`, `3 0` over findings-slice48, 50, 51 and 62; `git diff -U0 | grep -c '^-[^-]'` = 0 (no line removed); the banned-word grep over `+` lines exits 1 (clean). Saved gate outputs: `gate66-backend.txt` (run 2026-10-12T19:40:03Z: "lsof check: no pytest running", 1811 passed, 2 deselected, 2 warnings, coverage 100.00%, "gate exit 0") and `gate66.txt` (run 2026-10-12T19:43:40Z: 93 passed, "gate exit 0"), both on the copy with the revised notes applied.

Re-map of findings-slice62's table (lines 17 to 39 as at main 752a234, rows as at main 929ae35 → line at 752a234), by matching each row's line text: 48:78 → 78; 50:72 → 72; 51:80 → 80; 54:79 → 79; 55:117 → 117; 55:119 → 119; 55:123 → 123; 56:141 → 141; 56:153 → 153; 56:155 → 155; 56:157 → 157; 57:158 → 158; 57:165 → 165; 58:125 → 125; 58:127 → 127; 59:120 → 120; 59:130 → 130; 59:138 → 138; 59:144 → 144; 59:146 → 146; 60:139 → 139; 60:144 → 147; 61:101 → 101. Mapping targets (lines 9 to 11), all unchanged: 57:156, 57:158, 57:160, 59:120, 59:130, 59:138, 59:144, 56:141, 56:153, 56:155, 56:157. Open list (line 41): 49:108 → 108, 49:109 → 110, 60:141 → 141, 60:142 → 143, 60:143 → 145, 61:103 → 103, 61:104 → 105. The three slice 66 notes under 48:78, 50:72 and 51:80 go after those lines, so the rows themselves do not move.

## Departures from the section text shown in chat

- Section 1 items 1 to 3 and 6 are the texts approved after the spec review (decision 7), not the first chat texts.
- Section 1 in chat said each note sits "under" its line; where a slice 62 note already follows the line (48:78, 50:72, 51:80), the new note goes after that note, so the notes read in date order. The plan-mode file said "after line 78" and so on; the same precision applies.

## Rulings

Ruling: R1. Decided: the spec review's five minors are applied in the second spec commit alongside decision 7: the Context opens "After slices 62 to 65 …" (slice 62 closed most of the earlier minors; the redirect and /tmp/null minors closed within their own slices); the backend gate is re-run with the `lsof` result and both gates' exit statuses written into the saved files; Section 1 item 5 carries the diff's exact text and cites gate66-backend.txt; the line-shift statement names all four files and the grep that found nothing citing the shifted lines; the Correction says "five findings notes from slice 62" and Section 1 notes the slice 62 spec and plan carry the same quotes, out of scope. Found by: the spec reviewer (Opus 5.5), 2026-10-13. Why: an overstated opener, two provenance gaps, a text that drifted from its diff, a statement covering one file of four, and a phrase with two readings, all mine. Cost if wrong: none to behaviour. How named: this spec and chat.

Ruling: R2. Decided: the spec re-review's four minors are applied in the third spec commit alongside decision 8 (finding N1): Section 1 item 5 cites gate66-backend.txt lines 34 and 38 and is delimited with double backticks so its inner backticks render; the line-shift statement names the three historical `48:81` citations below the inserts and quotes "findings-slice48 lines 13 and 77" in full; decision 7 now names the Context bullet, the PR 2 scope, the Evidence additions and the web gate re-run that came with it, which R1 and decision 7 had left out; the Evidence says decision 8 changed one note's text only, which the gates do not read. This commit also carries the decision 8 texts (note 6 in Section 1, the Context bullet, the diff block), decision 8 itself and this ruling. Found by: the spec re-reviewer (Opus 5.5), 2026-10-13; N1 and the `48:81` citations verified by the controller. Why: a wrong line citation, a false "finds nothing", a decision and a ruling that named only part of their commit, and a code span with inner backticks, all mine. Cost if wrong: none to behaviour. How named: this spec and chat.

## Out of scope

- The five warning-text notes themselves and the slice 62 spec and plan that carry the same quotes; any code; any other findings file.

## Docs follow-ups

- findings-slice66.md with the re-map table and the shifted findings-slice62 §3 line numbers; README rows for the spec, plan and findings.
