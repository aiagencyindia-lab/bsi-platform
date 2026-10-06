# Slice 45 design: an index on serp_audit (brand_id, fetched_at)

## Context

Codebase facts: main `0a09f4d`, checked 2026-10-07.

`serp_audit` (migration 0023) has its primary key and an index on `org_id`, and none on `brand_id`. Three reads filter it by brand:
- `due_serp_audits()` (migration 0024): a brand's error-free pages fetched in the last 7 days, counted by kind. Its SQL comment names an index on `(brand_id, kind, fetched_at)` as the upgrade.
- `detect_serp_drop` (packages/core/bsi_core/alerts.py): a brand's error-free pages fetched before `to`, ordered by `fetched_at` then `id`, newest first. Its `ponytail:` comment notes it loads every page of the brand.
- `GET /brands/{id}/audits/serp` (apps/api/bsi_api/routers/audits.py): a brand's latest page per (country, language, kind), ordered by those columns before `fetched_at`.

Dev holds 12 rows. The slice 44 final review deferred the missing index (findings-slice44 §3, R7).

Classification: **bounded** — one new migration adding an index to an existing table, with no change to behaviour or interfaces. It was the first line of the first brainstorming reply, with the session model (Opus 5.5). The user's process asks for a spec and plan even for small changes, so this file exists.

Decisions approved in chat (2026-10-07), each after approaches with trade-offs and a recommendation written in a chat message:
1. The index covers `(brand_id, fetched_at)`: it serves the drop detector (brand, `fetched_at < to`, newest first, up to its `id` tie-break) and `due_serp_audits()` (brand and a 7-day `fetched_at` range); the Brand SERP API sorts by country, language and kind before `fetched_at`, so it uses only the `brand_id` part, as it would with any of the options. Over `brand_id` alone (the two `fetched_at` filters and the detector's order stay in memory), or `(brand_id, kind, fetched_at)` (no read filters by kind). First asked with an overstated reason against `brand_id` alone ("every query would still sort or range on `fetched_at` in memory"), then asked again after the spec review with the facts above.
2. The short design was approved in chat.

## Design

migrations/versions/0026_serp_audit_brand_index.py (new):

```python
"""ix_serp_audit_brand_fetched on serp_audit (brand_id, fetched_at)

Replaces the upgrade migration 0024's due_serp_audits() comment named,
(brand_id, kind, fetched_at), without kind: no read filters by kind. It
serves due_serp_audits() and the Brand SERP drop detector (brand and a
fetched_at range); the Brand SERP page's API uses its brand_id part
(slice 45).
"""

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_serp_audit_brand_fetched", "serp_audit", ["brand_id", "fetched_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_serp_audit_brand_fetched", table_name="serp_audit")
```

packages/core/bsi_core/models.py, as a diff against main `0a09f4d`:

```diff
@@ -637,4 +637,5 @@ class SerpAudit(Tenant, Base):
     __table_args__ = (
         CheckConstraint(_in("kind", SERP_KINDS), name="ck_serp_audit_kind"),
+        Index("ix_serp_audit_brand_fetched", "brand_id", "fetched_at"),
     )
 
```

packages/core/bsi_core/alerts.py:

```diff
@@ -222,6 +222,7 @@ def detect_serp_drop(
     so a renamed brand or a new locale starts a new series.
     """
-    # ponytail: loads every page of the brand; weekly pages stay few. Add
-    # a lookback window if the table grows.
+    # ponytail: loads every page of the brand (the filter is served by
+    # ix_serp_audit_brand_fetched); add a lookback window if a brand's
+    # pages grow many.
     rows = s.scalars(
         select(m.SerpAudit)
```

No behaviour changes: the three reads return the same rows. With 12 rows on dev, Postgres reads the whole table whatever indexes exist, so this slice claims no query-plan change.

## Testing

tests/integration/test_serp_audit.py gains one test (31 → 32 items):

```python
def test_serp_audit_is_indexed_by_brand_and_fetch_time(owner):
    with owner() as s:
        found = s.scalars(
            text(
                "SELECT indexdef FROM pg_indexes WHERE tablename = "
                "'serp_audit' AND indexname = 'ix_serp_audit_brand_fetched'"
            )
        ).all()
    assert found == [
        "CREATE INDEX ix_serp_audit_brand_fetched ON public.serp_audit "
        "USING btree (brand_id, fetched_at)"
    ]
    (index,) = [
        i
        for i in m.SerpAudit.__table__.indexes
        if i.name == "ix_serp_audit_brand_fetched"
    ]
    assert [c.name for c in index.columns] == ["brand_id", "fetched_at"]
```

Expected gates: backend `1747 passed, 2 deselected` (1746 on main plus 1) with metrics coverage at 100%; web 49, unchanged (the web app is not touched).

### Proof

Run 2026-10-07 in the scratchpad on a copy of main's backend, against the shared test database (R2). The edits above and the test are the ones it used.

- Red, main's code with the new test: `1 failed, 31 passed`, the failure `assert [] == ['CREATE INDE... fetched_at)']`.
- Green, patched: `32 passed`.
- The migration: up to 0026 (the index exists), down to 0025 (it does not), up and down again; bsi_test was left at 0025.
- `ruff check`, `ruff format --check` and `mypy --strict` pass on the patched files.

Each change below fails the test:

| Mutant | Change | Failed | Failing test |
|---|---|---|---|
| M1 | no migration 0026 | 1 | `test_serp_audit_is_indexed_by_brand_and_fetch_time` |
| M2 | migration index on (fetched_at, brand_id) | 1 | `test_serp_audit_is_indexed_by_brand_and_fetch_time` |
| M3 | migration index on brand_id only | 1 | `test_serp_audit_is_indexed_by_brand_and_fetch_time` |
| M4 | no `Index` on the model | 1 | `test_serp_audit_is_indexed_by_brand_and_fetch_time` |
| M5 | model `Index` on (fetched_at, brand_id) | 1 | `test_serp_audit_is_indexed_by_brand_and_fetch_time` |

## Rulings

Quoted from the ledger:

> Ruling: R1. Decided: the index is named ix_serp_audit_brand_fetched and built by a plain CREATE INDEX inside the migration's transaction, not CONCURRENTLY; the migration 0024 SQL comment that names the missing index is left as written (that migration has already run), and 0026's docstring says it is that index. Found by: the controller, writing the design. Why: the table holds 12 rows on dev; CONCURRENTLY cannot run inside alembic's transaction. Cost if wrong: on a large production table the CREATE INDEX would lock writes to serp_audit while it builds. How named: in chat in the approved design, 2026-10-07.

> Ruling: R2. Decided: the proof ran in a scratch copy of main's backend against the shared test database bsi_test, so the test session applied migration 0026 for real; afterwards the proof ran it down to 0025, up and down again through alembic, and read alembic_version (0025) and the index count (0). Found by: the controller, setting up the proof. Why: it exercises the migration file itself, as slices 43 and 44 did. Cost if wrong: bsi_test left at 0026 would break test sessions on main until downgraded. How named: in chat, 2026-10-07, after the proof run.

> Ruling: R3. Decided: the spec review's other findings are fixed: migration 0026's docstring no longer calls this the index 0024's comment named (that was (brand_id, kind, fetched_at)); it says this index replaces that upgrade, without kind (Important 1, my error, and R1's last clause is corrected below); the deferral is credited to slice 44's review only (Minor 2); the alerts.py comment says the index serves this filter rather than that the pages are found through it (Minor 3); the Decisions text gives the corrected per-query facts (Minor 4). Found by: the spec reviewer (Opus 5.5), 2026-10-07. Why: each is a wrong or overstated statement. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the review.

> Correction to R1 (2026-10-07, from the spec review): 0026's docstring does not say it is the index 0024's comment named; 0024 named (brand_id, kind, fetched_at), and 0026 replaces that upgrade without kind.

Rulings made after this spec's text was approved or alongside its approval (added by the post-merge docs commits), quoted from the ledger:

> Ruling: R4. Decided: the re-review's new Minor is not applied: the spec stays as committed at 8eb6f9e. Found by: the spec re-reviewer (Opus 5.5), 2026-10-07. Why: the proof was re-run on the reworded text before the spec was regenerated (proof.py modified 01:13:23, its green run written 01:13:52, the full table 01:15:19, all 2026-10-07; the scratch copy holds "Replaces the upgrade" and "the filter is served by"), its ruff check and format check ran on the new text, and the controller re-ran mypy --strict on it afterwards ("Success: no issues found in 31 source files"); the reviewer could not see the run. Cost if wrong: none to behaviour. How named: in chat, 2026-10-07, after the re-review.

> Ruling: R5. Decided: the plan review's Minor (the plan drops the spec's expected "web 49, unchanged" gate without listing it as a departure) is left in the plan; the controller runs the web gate itself before the finishing menu, as for every slice. Found by: the plan reviewer (Opus 5.5), 2026-10-07. Why: the task touches no web file, and a plan edit would need another review round. Cost if wrong: a reader of the plan alone does not see the web gate. How named: in chat, 2026-10-07, before the execution choice.

> Ruling: R6. Decided: no final fix wave; the final review's two Minors are deferred: the test pins Postgres 16's exact indexdef text, schema-qualified (1), and the plain CREATE INDEX blocks writes while it builds, R1's accepted cost (2). Found by: the final reviewer (Opus 5.5), 2026-10-07. Why: "Ready to merge? Yes"; the exact text is what lets the column-order mutants fail, and the project pins pgvector/pgvector:pg16; the table is tiny. Cost if wrong: the test needs updating if the schema or Postgres's output format changes; a long write block if the table were ever large when migrated. How named: in chat, 2026-10-07, at the finishing menu.

## Deferred minors

Deferred minors found during execution (added by the post-merge docs commit), quoted from the ledger:

- "minor (deferred): plan review minor, the plan does not list dropping the spec's web gate as a departure (R5)."
- "Task 1: minor (deferred): the gate's 2 warnings are the known third-party Starlette/anyio deprecation warnings, present on main."
- "Task 1: minor (deferred): the 0026 docstring's first sentence is hard to parse (plan- and spec-mandated wording)."
- "Task 1: minor (deferred): the alerts.py comment says the filter is served by the index; the index serves brand_id and the fetched_at range, not error IS NULL or the id tie-break (plan-mandated wording)."
- "minor (deferred): final review minor 1, the index test matches Postgres 16's exact schema-qualified indexdef text (R6)."
- "minor (deferred): final review minor 2, the plain CREATE INDEX blocks writes to serp_audit while it builds (R1, R6)."

## Live check

None: the index changes no result. Migrating dev to 0026 is asked separately after the merge.
