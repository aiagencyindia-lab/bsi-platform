# Slice 24 findings: one cached search per keyword phrase across runs

## 1. What was built

This slice targets the second grounded search that slice 23's dev re-check ran for LC-05: "mens flip flops" was searched although a row for "men flip flops" existed, because the `keyword_search` cache is keyed by the exact keyword string (spec, Context). A run now starts its spelling merge from the brand's fresh cache rows, so a product adopts the cached spelling and the cached search is reused.

All code changes are in `packages/core/bsi_core/products.py`. No migration, schema, API, prompt or web change.

**`_current`.** `_current(row: m.KeywordSearch) -> bool` (products.py:878), placed right after `search_query`. It returns True when the row's `query` equals `search_query(row.keyword)` and every stored title has `parse == TITLES_PARSE`. Its docstring says age and errors are checked in SQL.

**The lookup using it.** The per-batch lookup's inline test (`row.query == search_query(row.keyword) and all(...)`) is now `if _current(row)` (products.py:1114). The comment above it and the lookup's SQL are unchanged.

**The seeded `key_map`.** In `run_products`, `key_map` still starts as `{}` (products.py:1009) and is then filled in a second, short `tenant_session`, right after the run-start session and before the first batch:
- What is loaded: the brand's `KeywordSearch` rows with `searched_at > fresh_after` and `error IS NULL`; of these, only the rows where `_current(cached)` holds are used (products.py:1023).
- The order: `searched_at` descending, then `keyword`, with `key_map.setdefault(keyword_key(cached.keyword), cached.keyword)`, so the newest valid spelling of a key wins, and among rows with the same `searched_at` the first by keyword string.
- The loop variable is `cached`, not `row` (`run_products` later declares `row: dict[str, Any]`).
- What follows without further code: a product whose voted keyword shares a key with a seeded row gets the cached spelling in `keyword` and `keywords`; the per-batch lookup then hits on the exact string, and no grounded search runs.
- The comment above `key_map` now says it is seeded from the brand's fresh cache rows, and a `# ponytail:` comment carries the spec §1 ceilings (§3 below).

**Tests** (`tests/integration/test_products_run.py`):
- `_fresh_row(owner, org, bid, titles, days=1)` (line 408) gains `days`, the row's age; its existing callers pass no `days` and are unchanged.
- A module constant `CACHED_TITLE` (line 454) holds the title dict the three new tests share.
- `test_a_cached_spelling_is_adopted_and_its_search_reused` (line 463): a fresh "kids sandals" row, the generator's keywords `["kid sandal"]`; asserts `keyword == "kids sandals"`, `keywords == ["kids sandals"]`, `engine.prompts == []` and one `keyword_search` row.
- `test_a_stale_row_spelling_is_not_adopted` (line 479): the same row 8 days old; asserts `keyword == "kid sandal"`, `keywords == ["kid sandal"]`, one prompt for `search_query("kid sandal")` and two `keyword_search` rows.
- `test_a_row_the_lookup_rejects_is_not_seeded` (line 493): the row's title has `"parse": 1`; asserts `keyword == "kid sandal"`, one prompt for `search_query("kid sandal")` and two `keyword_search` rows.
- The 5 existing cache tests are unchanged and pass. No unit test was added.
- TDD evidence, as Task 1 recorded it:
  - RED (Step 3): `AssertionError: assert 'kid sandal' == 'kids sandals'`, 1 failed, 2 passed, 25 deselected. The stale-row and rejected-row tests pass before the change because they assert today's behaviour.
  - GREEN (Step 7): the product-run file, 28 passed.
  - Step 8: with `if _current(cached):` changed to `if False:`, the first new test failed with `AssertionError: assert 'kid sandal' == 'kids sandals'` (1 failed, 27 deselected); after `products.py` was restored from the scratchpad copy it passed (1 passed, 27 deselected), and `git diff --stat` listed only the 2 expected files.
- Backend gate (Task 1, e077bea): ruff format left 168 files unchanged; ruff check "All checks passed"; ruff format --check "168 files already formatted"; mypy "Success, no issues found in 29 source files"; pytest 1542 passed, 2 deselected, 2 warnings; metrics coverage 100%. The 2 warnings: `StarletteDeprecationWarning` (fastapi/testclient.py:1) and the anyio `BlockingPortal` alias `DeprecationWarning` (starlette/testclient.py:53).
- The controller also ran the product-run file at e077bea: 28 passed in 26.03s.

**Commits** (`git log --oneline main..HEAD`, oldest first):

| Commit | Subject |
|---|---|
| 750c369 | docs: slice 24 spec (one cached search per keyword phrase across runs) |
| 35139b4 | docs: slice 24 spec review fixes (loop variable, tie-break, seeded rows per key, tests, ceilings) |
| d6e2720 | docs: slice 24 spec: dev row and key counts reconciled |
| a407454 | docs: slice 24 spec: which test the men flip flops row fails |
| a48bce8 | docs: slice 24 implementation plan |
| 421e89c | docs: slice 24 plan review fixes |
| e077bea | feat(products): reuse one cached search per keyword phrase across runs |
| (this commit) | docs: slice 24 findings, index and rulings |

## 2. Live check on dev

Not yet run. The controller runs it after the user approves; results are recorded here then.

## 3. Deferred and untested

From the task reviews (ledger lines tagged `minor (deferred)`):
- Task 1: the spec §1 order rule (newest valid row wins; with equal searched_at the first keyword string) has no test; dropping `.desc()` or the secondary sort key would fail no test (test_products_run.py:454-510).
- Task 1: the gate output carries 2 third-party warnings (StarletteDeprecationWarning from fastapi/testclient.py:1; DeprecationWarning from starlette/testclient.py:53, the anyio BlockingPortal alias); pre-existing on main; not caused by this diff.

Parked: none. The ledger has no parked lines.

Rulings: none. The ledger records no ruling.

Untested:
- An accepted gap: no test pins the seed's `error.is_(None)` filter on its own. An error row with an empty title list passes `_current`, so the SQL filter is what keeps it out of the seed.
- Two seed cases that the spec reviewer noted and the spec does not list (plan, Task 2 Step 1):
  - Newest-wins between two valid rows that share a key. This is the gap in the first Task 1 minor above.
  - Adoption of a non-first keyword: in the three new tests each product has one keyword (`["kid sandal"]`), so none shows a seeded spelling taken by a product's second or later keyword.
- The tests use fixed model output, so they do not show which spellings real samples give. The dev re-check (§2) is where that is observed.

Known ceilings, spec §1 (in the `# ponytail:` comment above `key_map`):
- Spellings that do not share a key ("man slippers" against "men slippers") are not merged.
- Rows under an old spelling stay in the table once stale; nothing deletes them.
- The seed query loads every fresh valid row for the brand, that is every distinct keyword the brand searched in the last `SEARCH_TTL_DAYS` days (bounded by the products per brand, `MAX_PRODUCTS`, since only first keywords are searched).
- `drop_brand_terms` runs on the voted spelling before `key_map`, so a cached spelling that contains a brand token (a "crocs sandals" row from before "Crocs" became an alias) can be adopted by a voted "croc sandals" within the TTL.

Out of scope (spec):
- Deleting stale duplicate rows.
- A key column on `keyword_search`, and any migration.
- Spellings that do not share a `keyword_key`.
- The deferred minors in docs/findings-slice23.md §4.
