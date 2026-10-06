# Slice 45 serp_audit Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migration 0026 adds `ix_serp_audit_brand_fetched` on `serp_audit (brand_id, fetched_at)`, declared on the model too.

**Architecture:** One Alembic migration creating one index; a matching `Index` in `SerpAudit.__table_args__`; a comment update in `detect_serp_drop`; one test reading `pg_indexes` and the model.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, Postgres 16, pytest.

**Spec:** `docs/superpowers/specs/2026-10-07-slice45-serp-audit-index-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice45-serp-audit-index`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB (`bsi`), the network or the worker loop. Never run `alembic` by hand: the test session applies migrations to `bsi_test` itself.
- **Shared test DB:** run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own before every pytest run; if it prints a running pytest, stop and wait. Run the full backend suite only in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal.)
- **Writing files:** use the Edit or Write tools; never a shell heredoc or zsh `echo` to write files. Never run `rm`.
- **Lint and types:** ruff line length 80, target py313, rules E F I B UP RUF; `mypy --strict` covers `packages/core/bsi_core`.
- **Banned words:** copy (code, comments, docstrings, test names) never contains the words listed in `FORBIDDEN` in tests/unit/test_recommend_copy.py.
- **Banned-word grep (must block the commit):** `cd /Users/vineet/Downloads/ADK/bsi-platform && ! { git diff --cached -U0 | grep '^+' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'; }`, run after staging. Expected: exit 0 and no output.
- **Backend gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform && { uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task1.txt 2>&1; echo "gate exit $?"`. If `ruff format .` changed a file, re-stage it and say so.
- **`<workspace>`:** the path given in your task brief; if none is given, stop and ask.
- **Commit trailer:** exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Baseline counts** (main `0a09f4d`): backend `1746 passed, 2 deselected`; tests/integration/test_serp_audit.py 31 test items. After Task 1: 32 items, backend `1747 passed, 2 deselected` (computed, not yet run). The web app is not touched.

## File map

| File | Responsibility | Task |
|---|---|---|
| `migrations/versions/0026_serp_audit_brand_index.py` (new) | creates and drops `ix_serp_audit_brand_fetched` | 1 |
| `packages/core/bsi_core/models.py` | `SerpAudit.__table_args__` declares the index | 1 |
| `packages/core/bsi_core/alerts.py` | the `ponytail:` comment in `detect_serp_drop` | 1 |
| `tests/integration/test_serp_audit.py` | the index test | 1 |

---

### Task 1: the serp_audit (brand_id, fetched_at) index

**Files:**
- Create: `migrations/versions/0026_serp_audit_brand_index.py`
- Modify: `packages/core/bsi_core/models.py`, `packages/core/bsi_core/alerts.py`
- Test: `tests/integration/test_serp_audit.py`

**Interfaces:**
- Consumes: the test file's existing imports `text` and `m` and the `owner` fixture; `Index` is already imported in models.py.
- Produces: index `ix_serp_audit_brand_fetched` on `serp_audit (brand_id, fetched_at)`, in the database (revision 0026) and on `m.SerpAudit.__table__.indexes`.

- [ ] **Step 1: Write the failing test**

In `tests/integration/test_serp_audit.py`, add this block after the file's last line, separated from it by two blank lines:

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

- [ ] **Step 2: Run the tests to verify it fails**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_serp_audit.py 2>&1 | tail -1`
Expected: a line starting with `1 failed, 31 passed`; the failure is `assert [] == ['CREATE INDE... fetched_at)']`.

- [ ] **Step 3: Write the implementation**

1. Create `migrations/versions/0026_serp_audit_brand_index.py` with the Write tool:

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

2. In `packages/core/bsi_core/models.py`, replace

```python
        CheckConstraint(_in("kind", SERP_KINDS), name="ck_serp_audit_kind"),
    )
```

with

```python
        CheckConstraint(_in("kind", SERP_KINDS), name="ck_serp_audit_kind"),
        Index("ix_serp_audit_brand_fetched", "brand_id", "fetched_at"),
    )
```

3. In `packages/core/bsi_core/alerts.py`, replace

```python
    # ponytail: loads every page of the brand; weekly pages stay few. Add
    # a lookback window if the table grows.
```

with

```python
    # ponytail: loads every page of the brand (the filter is served by
    # ix_serp_audit_brand_fetched); add a lookback window if a brand's
    # pages grow many.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_serp_audit.py 2>&1 | tail -1`
Expected: a line starting with `32 passed`. The test session applies migration 0026 to `bsi_test` itself.

- [ ] **Step 5: Banned-word grep, then the backend gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add migrations/versions/0026_serp_audit_brand_index.py packages/core/bsi_core/models.py packages/core/bsi_core/alerts.py tests/integration/test_serp_audit.py`. Run the banned-word grep (expected: exit 0, no output). Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own, then the Backend gate. Expected: `gate exit 0`; `gate-task1.txt` shows `1747 passed, 2 deselected`, mypy `Success`, metrics coverage 100%. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the four staged files plus the untracked `.DS_Store` and `packages/.DS_Store`).

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add migrations/versions/0026_serp_audit_brand_index.py packages/core/bsi_core/models.py packages/core/bsi_core/alerts.py tests/integration/test_serp_audit.py && git commit -m "feat(db): index serp_audit by brand and fetch time

Migration 0026 adds ix_serp_audit_brand_fetched on (brand_id,
fetched_at), declared on the SerpAudit model too.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (plan vs spec)

- Spec coverage: the migration, the model `Index` and the `alerts.py` comment → Step 3; the test → Step 1; expected gates → Step 5.
- Departures from the spec:
  1. The code changes are whole-line replace blocks generated from the scratch proof's verified edits, not the spec's unified diffs; the result is the same files.
  2. The spec's mutation table is not repeated in execution.
  3. The commit message is the plan's wording.
  4. The header offers superpowers:executing-plans as well as subagent-driven-development (the template's wording).
- Verified before execution (2026-10-07): Steps 1–4 were applied to a fresh scratch copy of main and run against bsi_test: Step 2 `1 failed, 31 passed`, Step 4 `32 passed`; the finished files equal the spec's proof copies; bsi_test was then returned to 0025 through alembic. The gate (Step 5) was not run before execution.
- Fixtures and copy: the index name, test name and comment contain no banned word.
- Placeholders: `<workspace>`.

## Changes made during execution

(Filled in by the post-merge docs commit.)
