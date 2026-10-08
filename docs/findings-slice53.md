# Slice 53 findings: the slice 49 and slice 50 spec mutation tables render

## 1. What was built

Docs only. The mutation tables in `docs/superpowers/specs/2026-10-07-slice49-api-path-guard-design.md` (rows 946–960, 15 rows) and `docs/superpowers/specs/2026-10-07-slice50-refusal-log-cap-design.md` (rows 137–142, 6 rows) held a bare `|` inside each Result cell, the vitest summary such as `` `8 failed | 14 passed (22)` ``, so GitHub split the cell and rendered an extra column. Each is now `\|`, as the slice 51 spec already wrote it (lines 57–64). One replacement per row: 21 insertions, 21 deletions, one byte per row; line endings and trailing newlines unchanged. Every table row in both ranges, headers included, has 5 unescaped pipes (4 columns), counted by the implementer's script and again by the reviewer with awk. This fixes the "Docs rendering" item in the slice 51 handoff; no findings file recorded it as a deferred minor. The two specs' bullet lists (slice 49 around line 937, slice 50 around line 128) keep a bare `|` because a bullet is not a table cell.

Bounded path: no spec or plan file. The design was approved in chat on 2026-10-08 and lives in the Claude plan file `/Users/vineet/.claude/plans/let-s-do-item-1-2-3-playful-duckling.md`, outside the repo. Merged via PR #107 (https://github.com/aiagencyindia-lab/bsi-platform/pull/107), merge commit `1418714`; main `0c1ad47` after the three slice PRs.

**Docs**: the two spec files above.

**User decisions**, as the ledger records them:
- "User decision (2026-10-08 02:45 UTC): the slice 47 weekly-line minor is deferred (architectural: needs a new API field); items 1, 2 and 3b proceed as slices 52, 53, 54."
- "User decision (2026-10-08 02:45 UTC): designs for all three approved in chat (bounded path, no spec file); three branches, three PRs, three parallel implementer agents."
- "User decision (2026-10-08 02:53 UTC): finishing menu option 2, push and create a PR, for all three slices."
- "User decision (2026-10-08 02:55 UTC): merge."
- "User decision (2026-10-08 02:58 UTC): the controller writes the slices 52-54 findings docs in this session (Fable 5.1) after the harness refused the subagent's file write; an Opus 5.5 reviewer reviews them as usual."

**Results** (quoted from the ledger):
- "Task 1: implementer DONE 2026-10-08 02:46 UTC, commit b482f57 (2 files, 21 rows, per-row pipe count 5, banned-word grep clean, docs only)."
- "Controller banned-word grep 2026-10-08 02:49 UTC on b482f57: clean (exit 1 from grep, nothing matched). No web or backend gate: docs only, both trees byte-identical to main."
- "Pushed and opened PR #107 2026-10-08 02:54 UTC (body passed the banned-word grep)."
- "PR #107 merged 2026-10-08 02:55 UTC, merge commit 1418714; main now 0c1ad47."

CI was not checked by the controller before the merge; the user said "go ahead" to the merge question without asking for it.

**Reviews**, as the ledger records them:
- "Task 1: task review 2026-10-08 02:47 UTC: spec compliance pass, quality Approved, no findings (reviewer counted 5 unescaped pipes per row on lines 944-960 and 135-142 independently; hunks @@ -946,15 and @@ -137,6; one byte per row). Cannot-verify items resolved by controller: GitHub rendering is checked once the PR exists; the banned-word grep is re-run by the controller at the finishing gates."
- No separate final whole-branch review (R1 below).
- Docs review: see the docs PR.

**Commits** (`git log --oneline 3b8d2cd..b482f57`):

| Commit | Subject |
|---|---|
| b482f57 | docs: escape pipes in the slice 49 and slice 50 mutation tables |

## 2. Live check

None: docs only. Dev is not touched.

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim:

> Ruling: R1. Decided: no separate final whole-branch review for slice 53; the branch is one commit, so the task review package (review-3b8d2cd..b482f57.diff) already is the whole-branch diff. Found by: controller, at completion. Why: a duplicate review seat on a 21-byte docs diff the reviewer verified independently. Cost if wrong: a rendering defect reaches the PR; GitHub's rendering is checked on the PR. How named: quoted in chat.

> Ruling: R2. Decided: one docs PR covers slices 52, 53 and 54 (three findings files, README rows, dated notes under the fixed minors in findings-slice51 and findings-slice48), with one review round instead of three separate docs PRs. Found by: controller, after the three merges. Why: the three slices were planned, built and merged together; one PR keeps one review loop and one merge. Cost if wrong: a problem in one findings file holds up all three; the PR can be split if the review asks. How named: quoted in chat. (2026-10-08 02:55 UTC)

There is no `Correction to R` line in the ledger.

There is no `minor (deferred)` line in the ledger.
