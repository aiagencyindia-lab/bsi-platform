# Slice 29 Stale Rows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every product run deletes the brand's stale `keyword_search` rows at its start, so rows under old spellings or unused keywords no longer stay in the table.

**Architecture:** One `DELETE` in `run_products` (packages/core/bsi_core/products.py), in the tenant session that loads the seed, before the seed's `select`, with the readers' cutoff (`searched_at <= fresh_after`). A new integration test and one changed expectation in tests/integration/test_products_run.py. No migration.

**Tech Stack:** Python 3.13, SQLAlchemy 2, pytest (the shared `bsi_test` database).

**Spec:** `docs/superpowers/specs/2026-10-01-slice29-stale-rows-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice29-stale-rows`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB, the network or the worker loop. Never call a model.
- **Unchanged:** the seed, the per-batch lookup, the upsert, `SEARCH_TTL_DAYS`, the job's summary string, the `clear` route, the API, the web app, the migrations and models.
- **Shared test DB:** tests use `bsi_test`, which is shared. Run `pgrep -fl pytest` first, and never run two suites at once. Run the full suite only once, in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory; read the file rather than running it again.
- **Tool refusals:** if a tool refuses, stop and report BLOCKED. Do not work around it.
- **Writing files:** never use a shell heredoc or zsh `echo` to write files; use the Edit or Write tools.
- **Lint and types:** ruff line length is 80, and RUF001 rejects a literal curly apostrophe. `mypy --strict` runs over `packages/core/bsi_core`.
- **Banned words:** copy (code comments, docstrings, test names, fixtures, docs) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat` or `certain` (`FORBIDDEN` in tests/unit/test_recommend_copy.py).
- **Backend gate:** `{ uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task1.txt 2>&1; echo "gate exit $?"` (the echo prints to the terminal, not to a file).
- **Commit trailer:** the `Co-Authored-By` line from the latest session reminder.

## File map

| File | Responsibility |
|---|---|
| `packages/core/bsi_core/products.py` | the `delete` import, the `DELETE` before the seed, the seed comment, the `run_products` docstring |
| `tests/integration/test_products_run.py` | the changed expectation and the new test |
| docs | `docs/findings-slice29.md`, dated updates in `docs/findings-slice24.md`, `docs/findings-slice27.md` and `docs/findings-slice28.md`, `docs/README.md`, the spec's Rulings, this plan's changes section |

---

### Task 1: Delete stale rows at run start

**Files:**
- Modify: `packages/core/bsi_core/products.py` (import at line 26; docstring at about line 1000; the comment and the seed session at about lines 1047–1060)
- Test: `tests/integration/test_products_run.py` (`test_a_stale_row_spelling_is_not_adopted` at about line 487; the new test after it)

**Interfaces:**
- Consumes: `_seed`, `_fresh_row(owner, org, bid, titles, days=1, keyword="kids sandals", error=None)`, `CACHED_TITLE`, `_generator(keywords=...)`, `_run(...)` returning `(job, rows, searches)` with every brand's `keyword_search` rows, `FakeEngine`; fixtures `owner`, `make_org`, `make_brand(org, name)`.
- Produces: no new names outside the test file.

- [ ] **Step 1: Write the failing tests.** In tests/integration/test_products_run.py, replace exactly this text (found once; the end of `test_a_stale_row_spelling_is_not_adopted` and the start of the next test):

```python
    assert engine.prompts == [(products.search_query("kid sandal"), "IN", "en")]
    assert len(searches) == 2


def test_a_row_the_lookup_rejects_is_not_seeded(owner, make_org, make_brand):
```

with:

```python
    assert engine.prompts == [(products.search_query("kid sandal"), "IN", "en")]
    assert [r.keyword for r in searches] == ["kid sandal"]


def test_a_run_deletes_the_brands_stale_rows(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    other = make_brand(org, "Paragon")
    _seed(owner, org, bid, 1)
    _fresh_row(owner, org, bid, [CACHED_TITLE])
    _fresh_row(owner, org, bid, [CACHED_TITLE], days=8, keyword="kid sandals")
    _fresh_row(owner, org, bid, [CACHED_TITLE], days=8, keyword="boys sandal")
    _fresh_row(owner, org, other, [CACHED_TITLE], days=8)
    engine = FakeEngine()
    gen = _generator(keywords=["kid sandal"])
    _, rows, searches = _run(owner, org, bid, gen, engine)
    assert rows[0].keyword == "kids sandals"
    assert engine.prompts == []
    assert sorted((r.brand_id == bid, r.keyword) for r in searches) == [
        (False, "kids sandals"),
        (True, "kids sandals"),
    ]


def test_a_row_the_lookup_rejects_is_not_seeded(owner, make_org, make_brand):
```

- [ ] **Step 2: Run them to see them fail.** `pgrep -fl pytest` (expect nothing), then:

`cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_products_run.py -k "stale_row_spelling or deletes_the_brands_stale"`

Expected: `2 failed, 32 deselected`; `test_a_stale_row_spelling_is_not_adopted` fails on the row list (main keeps the stale "kids sandals" row) and `test_a_run_deletes_the_brands_stale_rows` fails on the sorted list (main keeps all four rows). If the result differs, stop and report it; do not change a test's expected values.

- [ ] **Step 3: Write the code.** In packages/core/bsi_core/products.py, make these four replacements (each old string is found once):

  1. Replace `from sqlalchemy import func, select, update` with `from sqlalchemy import delete, func, select, update`.
  2. Replace

  ```python
      keyword, missing keywords, rewrite, rule check, write. Stops before a
  ```

  with

  ```python
      keyword, missing keywords, rewrite, rule check, write. First
      deletes the brand's stale keyword_search rows. Stops before a
  ```

  3. Replace

  ```python
          # are not merged; rows under an old spelling stay once stale;
  ```

  with

  ```python
          # are not merged; a fresh row under a losing spelling stays
          # until it goes stale (not used meanwhile; the seed keeps the
          # newest current spelling), and stale rows are deleted at run start;
  ```

  4. Replace

  ```python
          key_map: dict[str, str] = {}
          with tenant_session(org_id) as s:
              for cached in s.scalars(
  ```

  with

  ```python
          key_map: dict[str, str] = {}
          with tenant_session(org_id) as s:
              # Stale rows are never read (the seed and the lookup need
              # searched_at > fresh_after), so the run deletes them.
              s.execute(
                  delete(m.KeywordSearch).where(
                      m.KeywordSearch.brand_id == brand_id,
                      m.KeywordSearch.searched_at <= fresh_after,
                  )
              )
              for cached in s.scalars(
  ```

  The code blocks in this step sit inside a list, so drop their 2-space list indent: in the file, the docstring line starts with 4 spaces, the comment lines and `key_map` with 8, and `s.execute(` with 12.

- [ ] **Step 4: Run them to see them pass.** `pgrep -fl pytest` (expect nothing), then:

`cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_products_run.py`

Expected: `34 passed` (the file's 33 tests and the new one). If the count or any result differs, stop and report it.

- [ ] **Step 5: Gate.** `pgrep -fl pytest` (expect nothing), then the Backend gate from Global Constraints, once. Expected: `gate exit 0`, `1553 passed, 2 deselected`, metrics coverage 100%, and the 2 known third-party warnings. Grep the diff (`git diff`) for the banned words: no match.

- [ ] **Step 6: Commit.** `git add packages/core/bsi_core/products.py tests/integration/test_products_run.py && git commit -m "feat(products): a run deletes the brand's stale keyword_search rows" -m "<trailer>"`.

---

### Task 2: Docs

**Files:**
- Create: `docs/findings-slice29.md` (the controller creates a one-line stub first; the subagent fills it with Edit).
- Modify: `docs/findings-slice24.md` §3, `docs/findings-slice27.md` §3, `docs/findings-slice28.md` §3, `docs/README.md`, the spec's `## Rulings`, this plan's `## Changes made during execution`.

- [ ] **Step 1: Findings.** Fill `docs/findings-slice29.md` in the style of `docs/findings-slice28.md`, with sections:
  - `## 1. What was built`: the `DELETE` before the seed (the brand, the `<=` cutoff, its session), the comment and docstring changes, the new and changed tests; the Step 2 RED, Step 4 GREEN and Step 5 gate results as the Task 1 report records them; and a commit table from `git log --oneline --reverse main..HEAD` with a "(this commit)" row.
  - `## 2. Live check on dev`: exactly "None in this slice (spec §2). No dev row is stale until 2026-10-06 13:10 UTC (18:40 IST); a check is a separate, later decision with its own approval."
  - `## 3. Deferred and untested`: every line tagged `minor (deferred…)` and every `parked` line in the ledger, quoted as recorded ("Parked: none" if none); the spec's rulings quoted in full, plus any the ledger records; the spec's Out of scope list; the items under "Carried forward from docs/findings-slice27.md §3" in docs/findings-slice28.md §3 that are still open (the stale-rows item is now fixed: say so instead of carrying it); and "Untested: a row exactly at the cutoff (`searched_at == fresh_after`); the tests run through the worker, which does not take `now`."
- [ ] **Step 2: Dated updates, originals kept.** Add a sub-bullet starting "Update 2026-10-01 (slice 29):" under each of:
  - docs/findings-slice24.md §3, the ceiling "Rows under an old spelling stay in the table once stale; nothing deletes them.": a product run now deletes the brand's stale rows at its start (docs/findings-slice29.md).
  - docs/findings-slice24.md §3, the Out of scope line "Deleting stale duplicate rows.": done in slice 29.
  - docs/findings-slice27.md §3, the item that begins "Stale duplicate `keyword_search` rows:", as the last sub-bullet of that item (after the quoted cleanup rulings, at the same 2-space indent as its other sub-bullets, not inside the rulings list): fixed in code by slice 29 (docs/findings-slice29.md).
  - docs/findings-slice28.md §3, the item that begins "Stale duplicate `keyword_search` rows:" (under "Carried forward"): fixed in code by slice 29.
  - docs/findings-slice28.md §3, the Out of scope line that begins "Deleting old-spelling `keyword_search` rows in code": done in slice 29.
- [ ] **Step 3: README rows** for the spec, the plan and the findings, after the row for `findings-slice28.md`, in the slice 28 rows' format; the spec row names its rulings' range.
- [ ] **Step 4: Rulings.** For each ruling the ledger records that the spec's `## Rulings` does not already hold (match by its R-number), add it after the spec's last ruling in the same format (Decided / Found by / Why / Cost if wrong, ending "Named in chat when made."). Quote every spec ruling in full in findings §3, and give the README spec row the spec's final ruling range.
- [ ] **Step 5: Plan changes.** Fill this plan's `## Changes made during execution` from the ledger: one bullet per task, quoting departures as recorded; the bullet for the commit that fills this section ends "(this commit)".
- [ ] **Step 6: Grep** the changed docs files (findings-slice29, findings-slice24, findings-slice27, findings-slice28, README, the spec, this plan) for the banned words; expected: no match except this plan's own Global Constraints list.
- [ ] **Step 7: Commit** `git add docs && git commit -m "docs: slice 29 findings, index and notes" -m "<trailer>"`.

---

## Self-review against the spec

- §1 code: Task 1 Step 3 (the import; the `DELETE` with `brand_id` and `searched_at <= fresh_after`, in the seed's session, before its `select`; the comment; the docstring clause). Unchanged items: Global Constraints.
- §2 tests: Task 1 Step 1 (the new test with the spec's four rows, the second brand made with `make_brand(org, "Paragon")`, the by-brand check; the changed assert). Red and green: Steps 2 and 4. Copy: Step 5 and Task 2 Step 6.
- §2 docs: Task 2 Steps 1–3 (findings-slice29; dated updates in findings-slice24 §3 (ceiling and Out of scope), findings-slice27 §3, findings-slice28 §3 (still-open item and Out of scope); README rows). §2 no live check: findings §2 text. §2 gates: controller, before the finishing menu.
- Departures from the spec:
  1. The seed comment's exact wording is the plan's ("not used meanwhile; the seed keeps the newest current spelling"), from the spec's "not used meanwhile, since the seed keeps the newest current spelling". The plan also adds a two-line comment above the `DELETE`.
  2. The docstring clause's wording is the plan's ("First deletes the brand's stale keyword_search rows.").
  3. The new test's check is `sorted((r.brand_id == bid, r.keyword) for r in searches)`; the spec says "the check splits them by brand".
  4. TDD order: the tests are written first and seen failing on the unchanged code (Step 2), then the code; the spec says red on main's code and green with the change.
  5. Step 4 runs the whole test file (34 passed) and Step 5 states the gate count (1553 = 1552 + 1); the spec names neither.
  6. Task 2 also updates the spec's Rulings and this plan's changes section, and findings §3 also carries the slice 28 carried-forward items; spec §2's docs list names neither.
- Verified before committing this plan: the replacements were applied, from this file's own code blocks, to scratch copies of main (each old string found exactly once). On main's code the two tests gave `2 failed, 32 deselected`; with the code change the whole file gave `34 passed`. ruff check, ruff format --check and `mypy --strict` (with the repo's config) are clean on the patched products.py and test file.
- Placeholders: none (`<trailer>` and `<workspace>` are per-session values).
- Type consistency: `_fresh_row`'s signature matches tests/integration/test_products_run.py at main.

## Changes made during execution

(Filled by Task 2 from the ledger.)
