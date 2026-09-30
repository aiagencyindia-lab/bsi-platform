# Slice 25 Raw Samples Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store, on each product row, the three keyword-prompt sample lists its `choose_keywords` call received and the rewrite call's title before `rule_check`, so live checks stop inferring them.

**Architecture:**
- Migration `0021` adds `product.keyword_samples` (JSONB) and `product.raw_title` (text). `Product` gains the two ORM columns.
- `run_products` writes `keyword_samples` in its first per-batch UPDATE (every product in the batch) and `raw_title` in its second (products with a keyword); the R13 `cleared` dict also nulls `raw_title`.
- Database-only: no API, web, CSV, prompt or copy change.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, Postgres 16 (JSONB), pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-slice25-raw-samples-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice25-raw-samples`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB, the network or the worker loop. Never call a model. Never run `alembic` against anything but the test DB (the test suite runs it itself).
- **Shared test DB:** tests use `bsi_test`, which is shared. Run `pgrep -fl pytest` first, and never run two suites at once. Run the full suite only once, in the gate step; write its pytest output to a file in the workspace directory and read the file rather than running it again.
- **Tool refusals:** if a tool refuses, stop and report BLOCKED. Do not work around it.
- **Lint and types:** ruff line length is 80, and RUF001 rejects a literal curly apostrophe (write `\u2019`). `mypy --strict` runs over `packages/core/bsi_core`.
- **Names:** the rewrite step's local is `title_in`; `raw` already names the model JSON in `run_products` and is not reused.
- **Unchanged:** `ProductOut`, `EXPORT_COLUMNS`, the Products page, `apps/web/openapi.json`, `apps/web/src/lib/schema.d.ts` (no `npm run gen`), every prompt, `rule_check`, `choose_keywords`, `_clean`, `test_rls.py`, `test_isolation.py`, `tests/unit`.
- **Banned words:** copy (comments, fixtures) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat` or `certain`.
- **Backend gate:** `uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100`
- **Commit trailer:** the `Co-Authored-By` line from the latest session reminder.

## Changes to existing tests that the spec implies

| Test | Change | Task |
|---|---|---|
| `_generator` (integration helper, line 54) | gains `skip_rewrite=()` | 2 |
| `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` (line 180) | two new assertions | 2 |
| `test_a_product_whose_keyword_drops_loses_its_old_suggestion` (line 741) | seeds `raw_title="Old raw"`, two new assertions | 2 |

## File map

| File | Responsibility |
|---|---|
| `migrations/versions/0021_product_raw.py` | the two columns |
| `packages/core/bsi_core/models.py` | `Product.keyword_samples`, `Product.raw_title` |
| `packages/core/bsi_core/products.py` | `run_products` writes |
| `tests/integration/test_products_run.py` | round-trip test, `skip_rewrite`, 2 extended and 1 new run test |
| docs | `docs/findings-slice25.md`, `docs/README.md`, `docs/findings-slice24.md` hashes, `docs/findings-slice23.md` note, the spec's Rulings, this plan's changes section |

---

### Task 1: Migration 0021 and the ORM columns

**Files:**
- Create: `migrations/versions/0021_product_raw.py`
- Modify: `packages/core/bsi_core/models.py`: `Product`, after the `dropped_words` column (line 555).
- Test: `tests/integration/test_products_run.py`: one new test after `test_the_database_accepts_review_and_rejects_an_unknown_status` (lines 846-863; the next test starts at line 866).

**Interfaces:**
- Consumes (unchanged): `m.Product`, the `owner`, `make_org`, `make_brand` fixtures, `_seed`, `select`, `JSONB` (already imported in `models.py` line 21).
- Produces: `Product.keyword_samples: Mapped[list[list[str]] | None]` (JSONB) and `Product.raw_title: Mapped[str | None]`; migration revision `"0021"`.

- [ ] **Step 1: Write the failing test.** Append to `tests/integration/test_products_run.py`, after `test_the_database_accepts_review_and_rejects_an_unknown_status`:

```python
def test_keyword_samples_round_trip(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    samples = [
        ["kids sandals", "men\u2019s chappals"],
        [],
        ["b\u00fcbchen sandalen"],
    ]
    with owner() as s, s.begin():
        s.add(
            m.Product(
                org_id=org.id,
                brand_id=bid,
                external_id="W-0",
                title="Walkaroo Boys Sandal",
                source="csv",
                keyword_samples=samples,
                raw_title="Kids Sandals \u2014 Summer",
            )
        )
    with owner() as s:
        p = s.scalars(select(m.Product)).one()
        assert p.keyword_samples == samples
        assert p.raw_title == "Kids Sandals \u2014 Summer"
```

- [ ] **Step 2: Run it to see it fail.** `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/integration/test_products_run.py -k round_trip 2>&1 | tail -5`
Expected: FAIL with `TypeError: 'keyword_samples' is an invalid keyword argument for Product`.

- [ ] **Step 3: The migration.** Create `migrations/versions/0021_product_raw.py`:

```python
"""product.keyword_samples and product.raw_title (slice 25)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product",
        sa.Column("keyword_samples", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.add_column("product", sa.Column("raw_title", sa.Text()))


def downgrade() -> None:
    op.drop_column("product", "raw_title")
    op.drop_column("product", "keyword_samples")
```

- [ ] **Step 4: The ORM columns.** In `packages/core/bsi_core/models.py`, directly after the `dropped_words` column of `Product` (line 555), add:

```python
    # The three keyword-prompt sample lists choose_keywords received
    # (after _clean), and the rewrite call's title before rule_check
    # (slice 25). Read with psql; not exposed by the API.
    keyword_samples: Mapped[list[list[str]] | None] = mapped_column(JSONB)
    raw_title: Mapped[str | None]
```

- [ ] **Step 5: Run the test to see it pass.** Same command as Step 2. Expected: `1 passed`. (The conftest runs `alembic upgrade head` on the test DB, so the new migration is exercised here.)

- [ ] **Step 6: Lint and types.** `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy`
Expected: no errors; ruff reformats nothing (report it if it does).

- [ ] **Step 7: Commit.**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add migrations/versions/0021_product_raw.py packages/core/bsi_core/models.py tests/integration/test_products_run.py && git commit -m "feat(products): keyword_samples and raw_title columns (migration 0021)" -m "Co-Authored-By: <trailer from the session reminder>"
```

---

### Task 2: `run_products` writes the samples and the raw title

**Files:**
- Modify: `packages/core/bsi_core/products.py`: the per-product keyword loop (lines 1054-1064), the first UPDATE and its `cleared` dict (lines 1066-1090), the rewrite write loop (lines 1225-1253).
- Test: `tests/integration/test_products_run.py`: `_generator` (lines 54-129), `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` (180-229), `test_a_product_whose_keyword_drops_loses_its_old_suggestion` (741-767), one new test after it.

**Interfaces:**
- Consumes: `Product.keyword_samples`, `Product.raw_title` from Task 1; `choose_keywords`, `rule_check`, `update`, `tenant_session` (unchanged).
- Produces: `p["samples"]: list[list[str]]` and `p["raw_title"]: str | None` on the batch dicts; `_generator(..., skip_rewrite=())`.

- [ ] **Step 1: `_generator` gains `skip_rewrite`.** Change the signature to

```python
def _generator(
    owner=None,
    fail_on=None,
    keywords=None,
    by_index=None,
    titles=None,
    rewrite=None,
    skip_rewrite=(),
):
```

and in the rewrite branch (the final `else:`), change `for i in indexes` to `for i in indexes if i not in skip_rewrite`, so the body becomes:

```python
        else:
            body = {
                "products": [
                    {
                        "index": i,
                        "title": rewrite
                        or "Walkaroo Kids Summer Sandals Sandals",
                        "bullets": ["Light", "Washable", "Soft", "Extra"],
                    }
                    for i in indexes
                    if i not in skip_rewrite
                ]
            }
```

- [ ] **Step 2: Extend the two existing tests.** In `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked`, after `assert p.suggested_bullets == ["Light", "Washable", "Soft"]`, add:

```python
    # Slice 25: the samples choose_keywords saw and the raw rewrite.
    assert p.keyword_samples == [["kids sandals", "walkaroo kids"]] * 3
    assert p.raw_title == "Walkaroo Kids Summer Sandals Sandals"
```

In `test_a_product_whose_keyword_drops_loses_its_old_suggestion`, add `raw_title="Old raw",` to the seeded `m.Product(...)` after `dropped_words=["x"],`, and after `assert p.dropped_words is None` add:

```python
    assert p.raw_title is None
    assert p.keyword_samples == [["walkaroo sandals"]] * 3
```

- [ ] **Step 3: Write the new test**, after `test_a_product_whose_keyword_drops_loses_its_old_suggestion`:

```python
def test_a_product_without_a_rewrite_keeps_its_title_and_no_raw_title(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    gen = _generator(skip_rewrite={0})
    job, rows, _searches = _run(owner, org, bid, gen)
    assert job.status == "done"
    p = rows[0]
    assert p.raw_title is None
    assert p.suggested_title == "Walkaroo Boys Sandal 0"
    assert (p.rule_check, p.dropped_words) == ("pass", [])
    assert p.suggested_bullets == []
    assert p.keyword_samples == [["kids sandals", "walkaroo kids"]] * 3
```

- [ ] **Step 4: Run the three tests to see them fail.** `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/integration/test_products_run.py -k "rewrite_is_checked or loses_its_old_suggestion or without_a_rewrite" 2>&1 | tail -8`
Expected: 3 failed, each on its `assert p.keyword_samples == ...` line (`None == [...]`), because nothing writes the column yet.

- [ ] **Step 5: Keyword step.** In `run_products`, replace the per-product loop

```python
            for i, p in enumerate(batch):
                fitted = choose_keywords(
                    [sm.get(i, []) for sm in samples],
                    names,
                    p["title"],
                    p["category"],
                    p["description"],
                )
```

with

```python
            for i, p in enumerate(batch):
                p["samples"] = [sm.get(i, []) for sm in samples]
                fitted = choose_keywords(
                    p["samples"],
                    names,
                    p["title"],
                    p["category"],
                    p["description"],
                )
```

In the `cleared` dict add `"raw_title": None,` after `"dropped_words": None,`. In the first UPDATE's `.values(...)` add `keyword_samples=p["samples"],` after `keywords=p["keywords"],`.

- [ ] **Step 6: Rewrite step.** Replace

```python
                    item = rewrites.get(i)
                    suggestion = (item.title.strip() if item else "") or p[
                        "title"
                    ]
```

with

```python
                    item = rewrites.get(i)
                    title_in = item.title.strip() if item else ""
                    p["raw_title"] = title_in or None
                    suggestion = title_in or p["title"]
```

and in the second UPDATE's `.values(...)` add `raw_title=p["raw_title"],` after `suggested_title=title,`.

- [ ] **Step 7: Run the three tests to see them pass.** Same command as Step 4. Expected: `3 passed`.

- [ ] **Step 8: Run the product-run file.** `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/integration/test_products_run.py 2>&1 | tail -3`
Expected: 30 passed (28 on main, plus Task 1's round-trip test and this task's new test). Report the number.

- [ ] **Step 9: Backend gate**, output to a file:

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100 > .superpowers/sdd/gate-task2.txt 2>&1; tail -5 .superpowers/sdd/gate-task2.txt
```
Expected: all passed (1542 on main plus the new tests), coverage 100%, the 2 pre-existing third-party warnings. Report the exact counts.

- [ ] **Step 10: Commit.**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests/integration/test_products_run.py && git commit -m "feat(products): store the keyword samples and the raw rewrite" -m "Co-Authored-By: <trailer from the session reminder>"
```

---

### Task 3: Docs

**Files:**
- Create: `docs/findings-slice25.md` (the controller creates a one-line stub first; the subagent fills it with Edit).
- Modify: `docs/README.md` (three rows after the slice 24 rows, lines 190-192), `docs/findings-slice24.md` lines 48 and 103, `docs/findings-slice23.md` line 197, the spec's `## Rulings`, this plan's `## Changes made during execution`.

- [ ] **Step 1: Findings.** Fill `docs/findings-slice25.md` in the style of `docs/findings-slice24.md`, with three sections:
  - `## 1. What was built`: the migration, the two columns, where `run_products` writes them, the tests, the gate result as Task 2 recorded it, and a commit table from `git log --oneline main..HEAD` with a "(this commit)" row.
  - `## 2. Live check on dev`: exactly "Not yet run. The controller migrates dev and runs it after the user approves each; results are recorded here then."
  - `## 3. Deferred and untested`: every line tagged `minor (deferred…)` and every `parked` line in the ledger not marked fixed, quoted as recorded; "Parked: none" if none; the spec's Out of scope list; carried forward from slice 24 §3: the stale duplicate `keyword_search` rows, the seed's untested `error.is_(None)` filter and newest-wins, adoption of a non-first keyword; the judge-agreement question (141 labels, 51% agreement, κ 0.20, waiting on the user).
- [ ] **Step 2: README rows** for the spec, the plan and the findings, in the slice 24 rows' format.
- [ ] **Step 3: Slice 24 hashes.** In `docs/findings-slice24.md`, replace "(this commit)" with "e315b44" on line 48 (the commit table) and line 103 ("recorded in §2 (this commit)").
- [ ] **Step 4: Slice 23 note.** In `docs/findings-slice23.md`, under line 197 "- Storing the raw keyword samples or the raw rewrite." add the nested bullet "  - Done in slice 25." The line itself is not edited.
- [ ] **Step 5: Rulings.** The spec's `## Rulings` stays "None." unless the ledger records one; if it does, add it in the slice 23 format (Decided / Found by / Why / Cost if wrong) and quote it in full in findings §3.
- [ ] **Step 6: Plan changes.** Fill this plan's `## Changes made during execution` from the ledger: one bullet per task, quoting departures as recorded.
- [ ] **Step 7: Grep** the four docs files for the banned words; expected: no match.
- [ ] **Step 8: Commit** `git add docs && git commit -m "docs: slice 25 findings, index and hashes" -m "Co-Authored-By: <trailer>"`.

---

## Self-review against the spec

- §1 storage: Task 1 (migration, ORM), Task 2 Steps 5-6 (writes, `cleared`, `title_in`). The failed-batch note in §1 describes existing behaviour and needs no code.
- §2 testing: Task 1 Step 1 (round trip), Task 2 Steps 1-3 (`skip_rewrite`, the two extended tests, the new test). Unchanged list matches Global Constraints.
- §3 dev migration and re-check: controller work after execution, each after the user's OK; not a task.
- §4 docs: Task 3.
- Departures from the spec: none.
- Placeholders: none (the `<trailer>` is a per-session value, as in slice 24's plan).
- Type consistency: `title_in`, `p["samples"]`, `p["raw_title"]`, `skip_rewrite` used consistently.

## Changes made during execution

(filled by Task 3 from the ledger)
