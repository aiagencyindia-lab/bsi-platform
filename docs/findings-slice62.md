# Slice 62 findings: the docs sweep

## 1. What was built

Slice 62, the last of the four "fix every item" slices (59 behaviour, 60 test hardening, 61 the probe script, 62 this sweep), closes 23 of the 30 open deferred minors in docs/findings-slice47.md to findings-slice61.md with dated notes directly under each, and adds two dated corrections after paragraphs that cite stale line numbers. No historical text is edited and no code changed. Afterwards 70 of the 77 deferred minors are closed; the seven still open are test work the user chose to leave for a later slice (spec decision 1).

The line numbers below are as at main `929ae35` (after the notes), which is what the corrections in findings-slice60 §3 and findings-slice61 §3 point here for. They move again whenever a later note is inserted above them; cite a minor by its quoted text where that matters.

**Closed in this slice** (23):

| Minor (as at main 929ae35) | Group | Closed as |
|---|---|---|
| 48:78 | Unverifiable | won't-fix |
| 50:72 | Unverifiable | won't-fix |
| 51:80 | Unverifiable | won't-fix |
| 54:79 | Docs wording | closed |
| 55:117 | Docs wording | won't-fix |
| 55:119 | Docs wording | won't-fix |
| 55:123 | Process | closed |
| 56:141 | Docs wording | won't-fix |
| 56:153 | Docs wording | closed |
| 56:155 | Docs wording | closed |
| 56:157 | Docs wording | closed |
| 57:158 | 2 warnings | won't-fix |
| 57:165 | Process | closed |
| 58:125 | Process | closed |
| 58:127 | Process | closed |
| 59:120 | Double seg() | won't-fix, by design |
| 59:130 | 2 warnings | won't-fix |
| 59:138 | 2 warnings | won't-fix |
| 59:144 | Double seg() | won't-fix, by design |
| 59:146 | Process | done |
| 60:139 | 2 warnings | won't-fix |
| 60:144 | 2 warnings | won't-fix |
| 61:101 | Process | closed |

**Still open** (7, all test work): 49:108, 49:109, 60:141, 60:142, 60:143, 61:103, 61:104. They are the scan's `QUERIES` exemption and `src/app`-only scope (slice 49), the formSeg scan's receiver shapes, `signedIn()` pinning nothing yet and the `audit()` fixture default (slice 60), and the probe's refusal on a raw directory alone and its untested `raw_dir` wiring (slice 61).

Facts the notes rest on, each checked by the spec and final reviewers: docs PR #113 (merge 77da2e7) added findings-slice56.md and put departure 7 (with R4) and departures 11 and 12 into the slice 56 plan's "Changes made during execution"; docs PR #119 (merge a026e65) carried findings-slice59.md, its dated notes and README rows; findings-slice54 §1 names the reversal of the slice 48 decision; `formSeg()` returns `seg(value)` and the path scan accepts one `seg()` call or a named query string per `${}`; the two warnings are Starlette's httpx deprecation (raised from starlette/testclient.py with `stacklevel=2`, so attributed to FastAPI's testclient.py) and anyio's `BlockingPortal` alias deprecation (from starlette/testclient.py).

Spec: docs/superpowers/specs/2026-10-12-slice62-docs-sweep-design.md (commits 760aa78, 48348d4, 88648f7, c2f81c7; decisions 1 to 4, rulings R1 and R2). Plan: docs/superpowers/plans/2026-10-12-slice62-docs-sweep.md (commits ce3d60c, 2c04739; R3). R4 was made at execution. Merged via PR #124 (https://github.com/aiagencyindia-lab/bsi-platform/pull/124), main `929ae35`.

**Change**: eleven `docs/findings-slice*.md` files (48, 50, 51, 54, 55, 56, 57, 58, 59, 60, 61), 27 insertions (25 non-blank: 23 notes and 2 corrections, plus 2 blank separators), 0 deletions. Backend 1810 and web 91, unchanged.

**User decisions**, as the ledger records them:
- "User decision (2026-10-12, spec decision 1): The seven test minors stay open, named as open test work for a later slice; slice 62 stays docs-only. Over folding them into slice 62 (a proof, mutants and a code PR) and over closing them as won't-fix."
- "User decision (2026-10-12, spec decision 2): The double `seg()` (59:120, 59:141): won't-fix, by design, over leaving them open for a later code slice."
- "User decision (2026-10-12, spec decision 3): The "2 warnings" (five minors): name both warnings and close as won't-fix, over two `filterwarnings` lines in pyproject.toml and over naming them and leaving them open."
- "User decision (2026-10-12, spec decision 4): Sections 1 to 3 each approved ("Yes, go on" for 1 and 2, "Yes, write the spec" for 3) after their text was shown in chat. Section 2's text said "16 minors"; the count is 13 (seven docs lines, five process observations and 59:142), corrected in chat before Section 3's approval."
- "User decision (2026-10-12): spec approved with "approved, write the plan" (the user's literal words) after the spec review rounds (commits 760aa78, 48348d4, 88648f7, c2f81c7)."
- "User decision (2026-10-12): execution method "approved, subagent-driven" (the user's literal words) after the plan review (commits ce3d60c, 2c04739)."
- "Finishing: User decision (2026-10-12): finishing menu answered "2 PR" (the user's literal words) after the controller ran both gates in the worktree (backend 1810 passed, 2 deselected, 2 warnings, coverage 100%; web 91 passed, build, gen:check clean; 185 files formatted)."
- "Finishing: User decision (2026-10-12): "check ci then merge" (the user's literal words) after PR #124 was opened."

**Results** (selected ledger lines, quoted; in the ledger only: the header lines, the pre-flight scan, the classification line, and the "Docs:" lines that record the docs commits):
- "Task 1: implementer (Opus 5.5, agent afa3bc469bc4d31a5) DONE_WITH_CONCERNS: commit 2b8220e (BASE 2c04739). Report: task-1-report.md. Count 77/30 before, 77/7 after (the seven test lines); 11 files changed, 27 insertions, 0 deletions, 25 non-blank; ruff, mypy clean; backend 1810 passed, 2 deselected, 2 warnings, coverage 100%; web 91 passed, build compiled, gen:check exit 0 (re-run alone because the zsh PIPESTATUS echo printed blank)."
- "Task 1: complete (commits 2c04739..2b8220e, review clean)"
- "Final review: no fix wave needed."
- "Finishing: PR #124 opened from slice62-docs-sweep at 2b8220e, base main be24258. CI not checked (waiting for the user). Ledger and worktree kept until the docs PR merges."
- "Finishing: CI run 38195596230 on 2b8220e: gates pass (3m14s); backend 1810 passed, 2 deselected, 2 warnings; web 91 passed; build compiled. PR #124 merged with a merge commit (MERGED 929ae35); git ls-remote --heads origin slice62-docs-sweep printed nothing; local main fast-forwarded."

**Reviews**, as the ledger records them:
- "Review verdict (2026-10-12): spec review of 760aa78 (Opus 5.5): Request changes; one Important (the 56:152 and 56:153 notes said won't-fix for work docs PR #113 had done; confirmed by the controller in the slice 56 plan), five minors; fixed in 48348d4 (R1) and 88648f7 (the banned-word pattern named by reference, after the controller had bypassed the gate for that line by hand in 48348d4)."
- "Review verdict (2026-10-12): scoped spec re-review of 760aa78..88648f7 (Opus 5.5): Approve with minors (two wording minors); fixed in c2f81c7 (R2)."
- "Review verdict (2026-10-12): plan review of ce3d60c (Opus 5.5): Approve with minors (19 blocks reproduced the spec's diff; counts and diff checks held; the removed-line check could not see removals; Review Focus 1 overstated); fixed in 2c04739 (R3)."
- `Task 1: Review verdict (2026-10-12): task reviewer (Opus 5.5, agent a6e2e17cc7d3895b5) Spec compliant (all 19 blocks verbatim; every note directly under its minor; no line removed); Task quality Approved; no Critical, no Important; every cited fact checked against its source. Cannot-verify item (the commit trailer) checked by the controller: `git show 2b8220e` ends with "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>".`
- "Final review: Review verdict (2026-10-12): final whole-branch reviewer (Opus 5.5, agent ad3480f19534234e6) over 2c04739..2b8220e: Ready to merge Yes; no Critical, no Important; the commit equals the spec's proof diff; 77 minors, 7 open (the test lines); every note's facts checked; one minor (findings-slice60 and findings-slice61 point at findings-slice62.md, which arrives with the docs PR); both deferred minors triaged "fine to defer"."

**Commits** (`git log --oneline --reverse be24258..929ae35^2`, oldest first):

| Commit | Subject |
|---|---|
| 760aa78 | docs(spec): slice 62 docs sweep design |
| 48348d4 | docs(spec): slice 62 spec review round 1 (R1) |
| 88648f7 | docs(spec): slice 62 spec names the banned-word pattern by reference |
| c2f81c7 | docs(spec): slice 62 spec re-review minors (R2) |
| ce3d60c | docs(plan): slice 62 docs sweep implementation plan |
| 2c04739 | docs(plan): slice 62 plan review fixes (R3) |
| 2b8220e | docs: close 23 open deferred minors with dated notes; correct two stale citations |

CI (2026-10-12): PR run 38195596230 on 2b8220e completed success (backend 1810 passed, 2 deselected, 2 warnings; web 91 passed; build compiled). The push run on main after the merge was not checked.

## 2. Live check

None: nothing user-visible changed and nothing was spent.

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim (R1 and R2 were copied into the ledger from the spec, R3 from the plan, when it was created):

> Ruling: R1. Decided: the spec review's findings are fixed in a second spec commit, with the proof rebuilt: the 56:152 and 56:153 notes say "closed: done in docs PR #113" and name what the slice 56 plan's "Changes made during execution" says, instead of "won't-fix"; the 54:79 note cites findings-slice54 §1 as the primary record and drops line numbers; 61:101 gets its own note (a scratchpad script, not a report); the double-`seg()` notes say "every `${}` in an API path is one `seg()` call or a named query string"; the counts say 25 non-blank lines (27 with two blank separators) and the evidence names the banned-word pattern. Found by: the spec reviewer (Opus 5.5), 2026-10-12. Why: two notes contradicted what main already held, one pointed at a secondary record, one described the wrong kind of artefact, one overstated the scan, and a count and a check did not reproduce, all mine. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R2. Decided: the re-review's two minors are fixed in a fourth spec commit: Section 3's check (4) says the pattern is the one in the plans for slices 55 to 61 (not every plan), and its PR bullet says 25 non-blank inserted lines; R1's "the evidence names the banned-word pattern" is read as "refers to", since 88648f7 replaced the quoted pattern with a reference. Found by: the spec re-reviewer (Opus 5.5), 2026-10-12, verdict Approve with minors (the regenerated diff reproduced: 77 minors, 7 open, 27 added lines, 25 non-blank). Why: an overstated "every plan", a count left in its old form, and a ruling that described the commit before it was reworded, all mine. Cost if wrong: none to behaviour. How named: this spec and chat.

> Ruling: R3. Decided: the plan review's two minors are fixed in a second plan commit: Step 3's removed-line check uses the `git diff --numstat` deletion total (the old `grep -c '^-[^-]'` could not see a removed bullet or blank line), and Review Focus 1 says the count catches a note under a closed or non-minor line while the verbatim blocks guard which open minor it sits under. Found by: the plan reviewer (Opus 5.5), 2026-10-12, verdict Approve with minors (all 19 blocks reproduced the spec's diff; both counts and the diff checks held). Why: a check that could not fail on what it was for, and an overstated claim about placement, both mine. Cost if wrong: none to behaviour. How named: this plan and chat.

> Ruling: R4. Decided: the final whole-branch review is dispatched on the docs-sweep commit 2c04739..2b8220e (eleven findings files), with the merge-base package also written but not handed over. Why: the six spec and plan commits had their own reviews, and the final reviewer reads the spec and plan itself. Cost if wrong: the final reviewer would not see the spec and plan diff, which has its own reviews. How named: this ledger and chat.

Every `minor (deferred)` line in the ledger, verbatim:

- "Task 1: minor (deferred): the shared won't-fix text under 48:78, 50:72 and 51:80 lists "chat approvals, ledger quotes, or a count from an offline run", but 48:78 also names the classification line and 51:80 the proof directory, and 48:78 names no count for "the merged PR's CI run" to attach to (plan-mandated wording, no wrong fact)."
- "Task 1: minor (deferred): the two quoted warning texts drop the messages' final period (plan-mandated, cosmetic)."
- "Final review: minor (deferred): findings-slice60.md and findings-slice61.md point at findings-slice62.md for the current lines; that file arrives with the post-merge docs PR, which must list them."
