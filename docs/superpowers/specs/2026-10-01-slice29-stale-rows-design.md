# Slice 29 design: a product run deletes the brand's stale keyword_search rows

## Context

Codebase facts: main `13d54fe`, checked 2026-10-01.

The open item "Stale duplicate `keyword_search` rows: rows under an old spelling stay in the table" is carried from docs/findings-slice24.md §3 (a known ceiling of the slice 24 seed) to docs/findings-slice27.md §3. On 2026-10-01 the user had the 11 such rows on dev deleted by hand (docs/superpowers/specs/2026-10-01-keyword-search-cleanup-design.md); the code still leaves them behind. The user asked for the code fix.

Facts read before the approaches (packages/core/bsi_core/products.py, `run_products`; the tests in tests/integration/test_products_run.py):
- Only `run_products` reads `keyword_search`: the run-start seed of `key_map` and the per-batch cache lookup. Both need `searched_at > fresh_after` (`fresh_after = now - timedelta(days=SEARCH_TTL_DAYS)`), so a stale row is never read. The API's `DELETE /v1/brands/{id}/products` (`clear`) deletes a brand's rows through a tenant session, so the app role may delete them. No web page, API route or migration reads the table.
- A stale row under the same spelling is overwritten by the upsert on `uq_keyword_search_brand_keyword` when that keyword is searched again; a stale row under any other spelling, or under a keyword no product uses any more, stays for good.
- One existing test counts a stale row that the change deletes: `test_a_stale_row_spelling_is_not_adopted` (`assert len(searches) == 2`). `test_a_fresh_search_is_reused_and_a_stale_one_redone` keeps its count of 1 (same spelling, overwritten or deleted and re-inserted).

Classification, said in chat as the first line of the first brainstorming reply: **architectural** — "This makes every product run delete stored `keyword_search` rows, which changes what the cache holds for later runs, so it touches stored data and not just logic. Your rule is a spec and plan either way."

Decisions approved in chat (brainstorming on Opus 5.5, 2026-10-01). The approaches (A: at run start, delete all the brand's stale rows; B: delete stale rows whose key matches a keyword this run uses, under another spelling; C: also delete fresh rows that lose to a newer spelling) were written in a chat message with trade-offs and a recommendation; the user chose A. Each design section's text was in chat before its approval question; the user approved Section 1 and Section 2.

## Design

### 1. The code change

In `run_products`, in the tenant session that loads the seed (the one opened just before `key_map` is filled), before the seed's `select`:

```python
s.execute(
    delete(m.KeywordSearch).where(
        m.KeywordSearch.brand_id == brand_id,
        m.KeywordSearch.searched_at <= fresh_after,
    )
)
```

- `<=` is the exact complement of the readers' `searched_at > fresh_after`: a row is either readable or deleted, never both.
- It deletes every row of this brand past `SEARCH_TTL_DAYS`, whatever its spelling, error or parse version. Other brands' rows and fresh rows are not touched.
- It runs once per run, before any model call, in a short session that commits on exit; no transaction is open during a model call. A run that fails later still leaves its stale rows deleted, which is harmless.
- `delete` is imported from `sqlalchemy` (the import line today is `from sqlalchemy import func, select, update`).
- The `# ponytail:` comment above `key_map`: "rows under an old spelling stay once stale" is replaced by a note that stale rows are deleted at run start, and that a fresh row under a losing spelling stays until it goes stale (it is not read meanwhile, since the seed takes the newest spelling).
- The `run_products` docstring gains one clause: the run first deletes the brand's stale `keyword_search` rows.
- Unchanged: the job's summary string, the seed, the per-batch lookup, the upsert, `SEARCH_TTL_DAYS`, the `clear` route, the API, the web app. No migration.

### 2. Tests, docs, live check

Tests, in tests/integration/test_products_run.py:
- New `test_a_run_deletes_the_brands_stale_rows`: one product (`_seed`) voting `keywords=["kid sandal"]`; rows: a fresh "kids sandals" row (1 day old, `CACHED_TITLE`), a stale "kid sandals" row (8 days, another spelling of the same key), a stale "boys sandal" row (8 days, a keyword no product uses), and a stale "kids sandals" row (8 days) for a second brand in the same org. Expected: this brand's rows are exactly "kids sandals"; the second brand's stale row is still there; `rows[0].keyword == "kids sandals"`; `engine.prompts == []`.
- Changed `test_a_stale_row_spelling_is_not_adopted`: `assert len(searches) == 2` becomes a check that the only row left is the new "kid sandal" row (the stale "kids sandals" row is deleted). Its other asserts are unchanged.
- Red: on main's code the new test fails (the stale rows remain), and so does the changed test. Green: both pass with the change. Verified on scratch copies by the plan.
- Copy: the new test's names, fixture values and comments are checked against `FORBIDDEN` in tests/unit/test_recommend_copy.py.

Docs: docs/findings-slice29.md; dated updates, originals kept, under the open "Stale duplicate `keyword_search` rows" item in docs/findings-slice27.md §3 (fixed in code by slice 29) and under the docs/findings-slice24.md §3 ceiling "Rows under an old spelling stay in the table once stale; nothing deletes them"; README rows for the spec, the plan and the findings.

Live check: none in this slice. No dev row is stale until 2026-10-06 13:10 UTC (18:40 IST), so a run before then deletes nothing; a run between then and 2026-10-07 09:27 UTC deletes 8 rows (the 7 plural keywords and "navy flip flops") and re-searches 7 keywords (about 7 × 38,000 + 14 × 1,650 micros, about $0.29); a run after that deletes all 9 and re-searches 8 (about $0.33).

Correction to the Section 2 chat text (2026-10-01): it said a run after 2026-10-06 13:10 UTC "would delete 8 rows but also re-search 8 keywords"; until "mens flip flops" goes stale at 2026-10-07 09:27 UTC it re-searches 7. The choice (no live check in this slice) does not depend on it. A check is a separate, later decision with its own approval.

Gates: both, run by the controller before the finishing menu.

## Rulings

None.

## Out of scope

- A test of a row exactly at the cutoff (`searched_at == fresh_after`): the tests run through the worker, which does not take `now`.
- Deleting fresh rows under a losing spelling (approach C).
- Any change to the seed, the lookup, the upsert, `SEARCH_TTL_DAYS`, the `clear` route, the job summary, or the schema.
- The live check (§2).
