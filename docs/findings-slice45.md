# Slice 45 findings: an index on serp_audit (brand_id, fetched_at)

## 1. What was built

Migration 0026 adds `ix_serp_audit_brand_fetched` on `serp_audit (brand_id, fetched_at)`, the index the slice 44 final review deferred; the `SerpAudit` model declares it too. It serves `due_serp_audits()` and the Brand SERP drop detector (brand and a `fetched_at` range); the Brand SERP API uses its `brand_id` part. No behaviour changes; no query-plan change is claimed (dev holds 12 rows).

Spec: docs/superpowers/specs/2026-10-07-slice45-serp-audit-index-design.md (rulings R1–R3 and the correction to R1 in the spec as approved; R4, made before approval but after the approved text, and R5–R6 added to it by these docs commits; R7 was made while fixing these docs). Plan: docs/superpowers/plans/2026-10-07-slice45-serp-audit-index.md (Task 1). Merged via PR #92 (https://github.com/aiagencyindia-lab/bsi-platform/pull/92), main `17925a5`.

**Code**: migrations/versions/0026_serp_audit_brand_index.py (new); packages/core/bsi_core/models.py (`SerpAudit.__table_args__` gains the `Index`); packages/core/bsi_core/alerts.py (the `ponytail:` comment in `detect_serp_drop`); tests/integration/test_serp_audit.py (one test, 31 → 32 items).

**User decisions**, as the ledger records them:
- "User decisions (2026-10-07): the user asked "Add the index on serp_audit brand_id"; columns (brand_id, fetched_at) (over (brand_id, kind, fetched_at), or brand_id alone), after approaches written in chat; the short design approved in chat."
- "User decision (not a ruling): 2026-10-07, re-asked after the spec review's Minor 4 showed the reason against brand_id alone was overstated (the Brand SERP API sorts in memory under any of the three indexes), the user chose again "(brand_id, fetched_at)"."

**Results** (quoted from the ledger):
- "Task 1: implementer af272f922bc3d031e, commit 01552c9 (trailer Opus 5.5 checked); report: red 1 failed 31 passed (assert [] == [...]), green 32 passed, gate exit 0, gate-task1.txt 1747 passed, 2 deselected, 2 warnings, coverage 100%."
- "Controller gates on 01552c9: backend gate exit 0, 1747 passed, 2 deselected, 2 warnings in 201.43s (0:03:21); web gate exit 0, Tests  49 passed (49), Compiled successfully."
- "CI run 37523571621: success, 1747 passed, 2 deselected, 2 warnings in 148.64s (0:02:28); web Compiled successfully. PR #92 merged by the controller after the user said "go ahead" to "Should I merge PR #92?" (2026-10-07)."
- "Gates on main 17925a5 after merge: backend 1747 passed, 2 deselected, 2 warnings in 209.36s (0:03:29); web Tests  49 passed (49)."

**Reviews**, as the ledger records them:
- "Spec review (a213f1603bfb53277, c52eff4): 0 Critical, 1 Important, 3 Minor."
- "Spec re-review (a213f1603bfb53277, 8eb6f9e): "All findings addressed? Yes"; 1 new Minor (the Proof section's "the edits above ... are the ones it used" said to be false after the rewording)."
- "Plan review (a0c358bc10d65c032, a6112a2): "Ready to execute? Yes"; 0 Critical, 0 Important, 1 Minor."
- "Task 1: task review (afcc920ba4ca5b2c5, a6112a2..01552c9): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 3 Minor. ⚠️ items resolved by the controller: the report holds the red and green lines; bsi_test reads 0026 now, as expected during the branch (R2's cost applies until merge); the gate shows "182 files left unchanged"."
- "Final review (acaddb4811bd2ff4f, 0a09f4d..01552c9): "Ready to merge? Yes"; 0 Critical, 0 Important, 2 Minor; every deferred minor triaged "no fix" before merge."

**Commits** (`git log --oneline --reverse 0a09f4d..17925a5^2`, oldest first):

| Commit | Subject |
|---|---|
| c52eff4 | docs(spec): slice 45, an index on serp_audit (brand_id, fetched_at) |
| 8eb6f9e | docs(spec): slice 45 review fixes (R3) |
| a6112a2 | docs(plan): slice 45, the serp_audit index |
| 01552c9 | feat(db): index serp_audit by brand and fetch time |

## 2. Live check

None: the index changes no result (spec, "Live check"). The dev database was migrated from 0024 to 0025 on 2026-10-07 at the user's request ("Migrate dev to 0025"; recorded in the controller's memory, not in a repo doc) and read 0025 when these docs were fixed; migrating it to 0026 is asked separately.

## 3. Rulings and deferred minors

Every `Ruling:` line in the ledger, verbatim:

> Ruling: R1. Decided: the index is named ix_serp_audit_brand_fetched and built by a plain CREATE INDEX inside the migration's transaction, not CONCURRENTLY; the migration 0024 SQL comment that names the missing index is left as written (that migration has already run), and 0026's docstring says it is that index. Found by: the controller, writing the design. Why: the table holds 12 rows on dev; CONCURRENTLY cannot run inside alembic's transaction. Cost if wrong: on a large production table the CREATE INDEX would lock writes to serp_audit while it builds. How named: in chat in the approved design, 2026-10-07.

> Ruling: R2. Decided: the proof ran in a scratch copy of main's backend against the shared test database bsi_test, so the test session applied migration 0026 for real; afterwards the proof ran it down to 0025, up and down again through alembic, and read alembic_version (0025) and the index count (0). Found by: the controller, setting up the proof. Why: it exercises the migration file itself, as slices 43 and 44 did. Cost if wrong: bsi_test left at 0026 would break test sessions on main until downgraded. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R3. Decided: the spec review's other findings are fixed: migration 0026's docstring no longer calls this the index 0024's comment named (that was (brand_id, kind, fetched_at)); it says this index replaces that upgrade, without kind (Important 1, my error, and R1's last clause is corrected below); the deferral is credited to slice 44's review only (Minor 2); the alerts.py comment says the index serves this filter rather than that the pages are found through it (Minor 3); the Decisions text gives the corrected per-query facts (Minor 4). Found by: the spec reviewer (Opus 5.5), 2026-10-07. Why: each is a wrong or overstated statement. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the review.

> Ruling: R4. Decided: the re-review's new Minor is not applied: the spec stays as committed at 8eb6f9e. Found by: the spec re-reviewer (Opus 5.5), 2026-10-07. Why: the proof was re-run on the reworded text before the spec was regenerated (proof.py modified 01:13:23, its green run written 01:13:52, the full table 01:15:19, all 2026-10-07; the scratch copy holds "Replaces the upgrade" and "the filter is served by"), its ruff check and format check ran on the new text, and the controller re-ran mypy --strict on it afterwards ("Success: no issues found in 31 source files"); the reviewer could not see the run. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the re-review.

> Ruling: R5. Decided: the plan review's Minor (the plan drops the spec's expected "web 49, unchanged" gate without listing it as a departure) is left in the plan; the controller runs the web gate itself before the finishing menu, as for every slice. Found by: the plan reviewer (Opus 5.5), 2026-10-07. Why: the task touches no web file, and a plan edit would need another review round. Cost if wrong: a reader of the plan alone does not see the web gate. How named: in chat, 2026-10-07, before the execution choice.

> Ruling: R6. Decided: no final fix wave; the final review's two Minors are deferred: the test pins Postgres 16's exact indexdef text, schema-qualified (1), and the plain CREATE INDEX blocks writes while it builds, R1's accepted cost (2). Found by: the final reviewer (Opus 5.5), 2026-10-07. Why: "Ready to merge? Yes"; the exact text is what lets the column-order mutants fail, and the project pins pgvector/pgvector:pg16; the table is tiny. Cost if wrong: the test needs updating if the schema or Postgres's output format changes; a long write block if the table were ever large when migrated. How named: in chat, 2026-10-07, at the finishing menu.

> Ruling: R7. Decided: the docs review's findings are fixed: R4 is quoted in the spec as a ruling made before approval but not in the approved text, and the findings and README say so (1); the dev-state clause names its source: the controller migrated dev from 0024 to 0025 at the user's request on 2026-10-07 ("Migrate dev to 0025"; recorded in memory, not in a repo doc) and dev read 0025 when these docs were fixed (2); the plan's execution section nests the quotes under their headings (3). Found by: the docs reviewer (Opus 5.5, a69a1b5912bdf04b6), 2026-10-07. Why: (1) and (2) were wrong or unsourced statements; (3) is cosmetic. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, before the fix commit.

The correction, verbatim:

> Correction to R1 (2026-10-07, from the spec review): 0026's docstring does not say it is the index 0024's comment named; 0024 named (brand_id, kind, fetched_at), and 0026 replaces that upgrade without kind.

Every `minor (deferred)` line in the ledger, verbatim:

- "minor (deferred): plan review minor, the plan does not list dropping the spec's web gate as a departure (R5)."
- "Task 1: minor (deferred): the gate's 2 warnings are the known third-party Starlette/anyio deprecation warnings, present on main."
- "Task 1: minor (deferred): the 0026 docstring's first sentence is hard to parse (plan- and spec-mandated wording)."
- "Task 1: minor (deferred): the alerts.py comment says the filter is served by the index; the index serves brand_id and the fetched_at range, not error IS NULL or the id tie-break (plan-mandated wording)."
- "minor (deferred): final review minor 1, the index test matches Postgres 16's exact schema-qualified indexdef text (R6)."
- "minor (deferred): final review minor 2, the plain CREATE INDEX blocks writes to serp_audit while it builds (R1, R6)."
