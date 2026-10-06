# Slice 45 design: an index on serp_audit (brand_id, fetched_at)

## Context

Codebase facts: main `0a09f4d`, checked 2026-10-07.

`serp_audit` (migration 0023) has its primary key and an index on `org_id`, and none on `brand_id`. Three reads filter it by brand:
- `due_serp_audits()` (migration 0024): a brand's error-free pages fetched in the last 7 days, counted by kind. Its SQL comment names the missing index as the upgrade.
- `detect_serp_drop` (packages/core/bsi_core/alerts.py): a brand's error-free pages fetched before `to`, newest first. Its `ponytail:` comment notes it loads every page of the brand.
- `GET /brands/{id}/audits/serp` (apps/api/bsi_api/routers/audits.py): a brand's latest page per (country, language, kind).

Dev holds 12 rows. The slice 43 and 44 reviews deferred the missing index (findings-slice43 §3, findings-slice44 §3).

Classification: **bounded** — one new migration adding an index to an existing table, with no change to behaviour or interfaces. It was the first line of the first brainstorming reply, with the session model (Opus 5.5). The user's process asks for a spec and plan even for small changes, so this file exists.

Decisions approved in chat (2026-10-07), after approaches with trade-offs and a recommendation written in a chat message: the index covers `(brand_id, fetched_at)`; over `(brand_id, kind, fetched_at)` (the upgrade 0024's comment named; no query filters by kind), or `brand_id` alone (every query would still sort or range on `fetched_at` in memory). The short design was approved in chat.

## Design

migrations/versions/0026_serp_audit_brand_index.py (new):

```python
"""ix_serp_audit_brand_fetched on serp_audit (brand_id, fetched_at)

The index migration 0024's due_serp_audits() comment named. It serves
the reads that filter serp_audit by brand: due_serp_audits(), the Brand
SERP drop detector and the Brand SERP page's API (slice 45).
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
+    # ponytail: loads every page of the brand, found through
+    # ix_serp_audit_brand_fetched; add a lookback window if a brand's
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

## Deferred minors

None yet.

## Live check

None: the index changes no result. Migrating dev to 0026 is asked separately after the merge.
