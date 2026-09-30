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
| 0530ecc | docs: slice 24 findings, index and rulings |
| 20c907b | docs: slice 24 findings wording fixes |
| fb0bfb1 | docs: slice 24 findings: final-review minors |
| e315b44 | docs: slice 24 live check |

## 2. Live check on dev

Run on 2026-09-30 by the controller at fb0bfb1, with the user's OK ("yes, do the docs commit, then run the dev re-check"). Dev was at migration 0020; no migration was needed.

- Pre-check (read-only): no worker or uvicorn process; 0 queued or running jobs; 7 prior `product_run` jobs totalling 1,637,567 micros; `keyword_search` had 20 rows for the brand. Product keywords before the run: LC-01/02 kids sandals, LC-03/09 kids shoes, LC-04 kids slippers, LC-05 mens flip flops, LC-06 men sandals, LC-07 women slippers, LC-08 men shoes, LC-10 women sandals.
- The API was started in the background. `POST /v1/brands/34db213a-f484-4991-a969-c52cfa5e1c10/products/run` returned HTTP 202 and queued job `a53737aa-f39f-446d-a9e9-87e646be1915`. The API was then stopped (background task exit 144, expected). Exactly 1 job was queued, and `process_job` was run once (it printed `True`).
- Job `a53737aa`: status done, error null, `cost_micros = 6,407` (the estimate was about 6,000), created 12:36:08, started 12:36:21 UTC (2026-09-30).
- No grounded search ran: 0 `keyword_search` rows were searched in the last 30 minutes, and `keyword_search` still has 20 rows.
- Afterwards: 0 queued or running jobs, and no worker or uvicorn process.

**Per product** (observed by read-only queries after the job):

| Product | Keyword | Keywords | Missing words | Suggested title | Status |
|---|---|---|---|---|---|
| LC-01 | kids sandals | kids sandals, kids eva sandals, lightweight sandals, hook-and-loop sandals, boys sandals | kid | BSOAgentTestBrand Blue Kid Sandals Boys | adjusted |
| LC-02 | kids sandals | kids sandals, soft sandals, kids padded sandals, girls sandals, padded sandals | kid | BSOAgentTestBrand Pink Kid Sandals Girls | adjusted |
| LC-03 | kids shoes | kids shoes, kids running shoes, breathable shoes, mesh shoes, sports shoes | (none) | BSOAgentTestBrand Black Kids Sports Shoe | adjusted |
| LC-04 | kids slippers | kids slippers, anti-skid slippers, daily wear slippers, daily slippers, kids flip flops | (none) | BSOAgentTestBrand Grey Kids Slippers | adjusted |
| LC-05 | mens flip flops | mens flip flops, cushioned flip flops, flip flops, men slippers, daily wear slippers | (none) | BSOAgentTestBrand Navy Mens Flip Flops | adjusted |
| LC-06 | men sandals | men sandals, men casual sandals, floater sandals, adjustable sandals, casual sandals | (none) | BSOAgentTestBrand Brown Men Sandals Casual | adjusted |
| LC-07 | women slippers | women slippers, casual slippers, soft strap slippers, comfortable slippers, soft slippers | (none) | BSOAgentTestBrand Beige Women Slippers Casual | adjusted |
| LC-08 | men shoes | men shoes, men running shoes, lace-up shoes, cushioned shoes, sports shoes | (none) | BSOAgentTestBrand Grey Men Sports Shoe | adjusted |
| LC-09 | kids shoes | kids shoes, kids school shoes, velcro shoes, durable shoes, boys shoes | kids | BSOAgentTestBrand Black Kids School Shoe Boys | adjusted |
| LC-10 | women sandals | women sandals, flat sandals, cushioned sandals, women flat sandals, casual sandals | footbed | BSOAgentTestBrand Tan Women Sandals Footbed | adjusted |

**Against spec §3's *inferred* expectations:** all match.
- LC-05's keyword is "mens flip flops".
- The other 9 keywords are unchanged.
- 0 `keyword_search` rows were written, and `keyword_search` still has 20 rows.
- No stored `keywords` list contains a colour or size word (a read-only regex query over `product.keywords` returned 0 products).
- Cost 6,407 micros against the estimate of about 6,000.

**Observations.**
- As spec §3 says, this result cannot tell the slice from main (the model voted every cached spelling); it shows no regression and a low cost.
- All 10 `rule_check` statuses are `adjusted` (slice 23's re-check: 4 adjusted, 6 pass). *Inferred*: the rewrite call varies between runs.
- The stored `keywords` lists differ from slice 23's in their later entries (the model's other keywords vary between runs; *inferred*).

**Spend:** about $10.94 + $0.0064 ≈ $10.95 of the $15 cap.

**Writes:** the job row, 10 product rows and `api_key.last_used_at`. No `keyword_search` writes.

## 3. Deferred and untested

From the task reviews (ledger lines tagged `minor (deferred)`):
- Task 1: the spec §1 order rule (newest valid row wins; with equal searched_at the first keyword string) has no test; dropping `.desc()` or the secondary sort key would fail no test (test_products_run.py:454-510).
  - Note (not ledger text; from the final review): the range is test_products_run.py:454-503. The new tests end at line 503, and line 506 starts `test_the_rewrite_cannot_add_an_invented_word`.
- Task 1: the gate output carries 2 third-party warnings (StarletteDeprecationWarning from fastapi/testclient.py:1; DeprecationWarning from starlette/testclient.py:53, the anyio BlockingPortal alias); pre-existing on main; not caused by this diff.

From the final whole-branch review (ledger lines tagged `minor (deferred)`):
- findings §3's first bullet (and the ledger's Task 1 minor it quotes) cites test_products_run.py:454-510; the new tests end at line 503 and line 506 starts test_the_rewrite_cannot_add_an_invented_word. Controller: the ledger line is a record and stays; the findings get a note after the quoted line.
  - Corrected in fb0bfb1 (note above): the range is 454-503.
- the spec's §1 prose says the run-start session loads the seed while its parenthetical allows a second session; plan departure 3 records the choice (a second session). Spec wording only.
- the live check is not yet run; findings §2 and the README row say so; they must be updated if it runs before merge.
  - Run on 2026-09-30, recorded in §2 (e315b44).

Parked: none. The ledger has no parked lines.

Rulings: none. The ledger records no ruling.

Untested:
- An accepted gap: no test pins the seed's `error.is_(None)` filter on its own. An error row with an empty title list passes `_current`, so the SQL filter is what keeps it out of the seed.
- Two seed cases that the spec reviewer noted and the spec does not list (plan, Task 2 Step 1):
  - Newest-wins between two valid rows that share a key. This is the gap in the first Task 1 minor above.
  - Adoption of a non-first keyword: in the three new tests each product has one keyword (`["kid sandal"]`), so none shows a seeded spelling taken by a product's second or later keyword.
- The tests use fixed model output, so they do not show which spellings real samples give. The dev re-check (§2) is where that is observed.

Known ceilings, spec §1 (in the `# ponytail:` comment above `key_map`, in shorter wording):
- Spellings that do not share a key ("man slippers" against "men slippers") are not merged.
- Rows under an old spelling stay in the table once stale; nothing deletes them.
  - Correction to "nothing deletes them" (2026-10-01): `DELETE /v1/brands/{id}/products` (`clear` in apps/api/bsi_api/routers/products.py) deletes every `keyword_search` row of the brand along with its products. No run removes an old spelling on its own.
- The seed query loads every fresh valid row for the brand, that is every distinct keyword the brand searched in the last `SEARCH_TTL_DAYS` days (bounded by the products per brand, `MAX_PRODUCTS`, since only first keywords are searched).
- `drop_brand_terms` runs on the voted spelling before `key_map`, so a cached spelling that contains a brand token (a "crocs sandals" row from before "Crocs" became an alias) can be adopted by a voted "croc sandals" within the TTL.

Out of scope (spec):
- Deleting stale duplicate rows.
- A key column on `keyword_search`, and any migration.
- Spellings that do not share a `keyword_key`.
- The deferred minors in docs/findings-slice23.md §4.
