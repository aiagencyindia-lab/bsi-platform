# Slice 24 design: one cached search per keyword phrase across runs

## Context

Slice 23's dev re-check (docs/findings-slice23.md §3, job `ec137947`) searched "mens flip flops" for LC-05 although a row for "men flip flops" existed: the `keyword_search` cache is keyed by the exact keyword string, so two spellings of one phrase cost two grounded searches (about $0.04 each). Within one run, `run_products`' run-wide `key_map` already merges spellings by `keyword_key` (the stemmed phrase, "men flip flop"), so "mens sandal" and "men sandals" share one search in the same run. Across runs nothing merges them.

On dev the brand has 20 `keyword_search` rows for 12 distinct keys. The duplicate pairs are kids sandal/sandals, kids shoe/shoes, kids slipper/slippers, men sandals/mens sandal, men shoe/shoes, women sandals/womens sandal, women slipper/slippers and men/mens flip flops.

Classification, said in chat as the first line of the first brainstorming reply: **architectural** — "the cache key is shared by the `keyword_search` table's unique constraint, the cache lookup in `run_products` and the run-wide `key_map`, so changing it may need a migration and touches stored data; and your rule is a spec even for small changes." (The design that followed needs no migration and no table change.)

Decisions approved in chat (brainstorming on Fable 5.1, 2026-09-30). Sections 1 and 2 each had their design text in chat before their approval:

- **Spelling:** when a fresh cached search exists under another spelling of the same phrase, the product's stored keyword takes the cached spelling. Rejected: keeping the run's own spelling while reusing the titles.
- **Approach A:** seed `key_map` from the cache at the start of each run. Rejected: B, a key column with migration 0021, a backfill that merges dev's duplicate rows and the same spelling adoption on top; C, matching by key at lookup time per batch, with the spelling adoption written separately.

Codebase facts (main `17488e0`, checked 2026-09-30):

- `keyword_search` is unique on `(brand_id, keyword)` (`uq_keyword_search_brand_keyword`). The insert in `run_products` upserts on that constraint.
- `run_products` opens one tenant session at the start to read the brand, its competitors and its products, then sets `key_map: dict[str, str] = {}` and loops over batches. Each product's `keywords` are `[key_map.setdefault(keyword_key(k), k) for k in fitted]`, and `p["keyword"]` is the first of them.
- Per batch, the lookup selects the brand's `KeywordSearch` rows whose `keyword` is in the batch's keywords, `searched_at > fresh_after` (`now - SEARCH_TTL_DAYS` days; `SEARCH_TTL_DAYS` = 7) and `error IS NULL`, and keeps a row only if `row.query == search_query(row.keyword)` and every stored title has `parse == TITLES_PARSE`. That last test is written inline in the lookup's generator expression.
- `keyword_key("kid sandal") == keyword_key("kids sandals") == "kid sandal"`; `keyword_key("mens flip flops") == keyword_key("men flip flops") == "men flip flop"`; `keyword_key("men's slippers") == "men slipper"`; `keyword_key("man slippers") == "man slipper"`.
- In `tests/integration/test_products_run.py`, `_fresh_row(owner, org, bid, titles)` writes a `KeywordSearch` row for "kids sandals" with the current query and `searched_at` one day ago; it is called by 2 tests. `test_a_fresh_search_is_reused_and_a_stale_one_redone` writes its own row 6 days old with a `parse: 2` title, runs, then updates the row's age. The fake generator's default keywords are `["kids sandals", "walkaroo kids"]`, and `keywords=[...]` overrides them for every product.
- On dev, the fresh valid row for the flip-flop key is "mens flip flops" (searched 2026-09-30, `parse` present); the "men flip flops" row (2026-09-29) has no `parse` key.

## Design

All code changes are in `packages/core/bsi_core/products.py`. No migration, schema, API, prompt or web change.

### 1. Seeding `key_map` from the cache

New helper, next to `search_query`:

```python
def _current(row: m.KeywordSearch) -> bool:
    """A cache row the run can use: the current query wording and every
    title parsed by the current titles_prompt (TITLES_PARSE). Age and
    errors are checked in SQL."""
    return row.query == search_query(row.keyword) and all(
        t.get("parse") == TITLES_PARSE for t in row.titles
    )
```

The per-batch lookup's inline test (`if row.query == search_query(row.keyword) and all(...)`) becomes `if _current(row)`; its SQL is unchanged.

In `run_products`, the run-start session also loads the brand's fresh valid rows, newest first, and `key_map` is seeded from them instead of starting empty:

```python
        # One keyword string per key for the whole run, so plural and
        # possessive variants share one search and one cache row. Seeded
        # from the brand's fresh cache rows (newest first), so a phrase
        # keeps its cached spelling across runs and its search is reused.
        # ponytail: spellings that do not share a key ("man slippers")
        # are not merged; rows under an old spelling stay once stale;
        # loads every fresh valid row of the brand (at most KEYWORD_CAP
        # per run over SEARCH_TTL_DAYS).
        key_map: dict[str, str] = {}
        with tenant_session(org_id) as s:
            for row in s.scalars(
                select(m.KeywordSearch)
                .where(
                    m.KeywordSearch.brand_id == brand_id,
                    m.KeywordSearch.searched_at > fresh_after,
                    m.KeywordSearch.error.is_(None),
                )
                .order_by(m.KeywordSearch.searched_at.desc())
            ):
                if _current(row):
                    key_map.setdefault(keyword_key(row.keyword), row.keyword)
```

(The plan may place this inside the existing run-start session rather than a second one; either way it runs once per run, before the first batch, with no model call in between.)

- What follows without further code: a product whose voted keyword shares a key with a seeded row gets the cached spelling in `p["keyword"]` and `p["keywords"]`; the per-batch lookup then hits on the exact string; no grounded search runs; the stored `keywords` list uses cached spellings.
- Only rows the lookup would accept are seeded (fresh, no error, current query, current parse), so a stale spelling never wins. If two valid rows share a key, the newest spelling is used (`order_by ... desc()` with `setdefault`).
- Unchanged: the `keyword_search` table and its unique constraint, the lookup's SQL, the insert and its upsert, `keyword_key`, `SEARCH_MICROS`, `KEYWORD_CAP`, R10's budget check.
- Known ceilings (in the comment above): spellings that do not share a key ("man slippers" against "men slippers") are not merged; rows under an old spelling stay in the table once stale, nothing deletes them; the seed query loads every fresh valid row for the brand, at most `KEYWORD_CAP` (100) per run over `SEARCH_TTL_DAYS`.

### 2. Testing

Integration, `tests/integration/test_products_run.py`:

- `_fresh_row(owner, org, bid, titles, days=1)` gains `days`, the row's age; callers that do not pass it are unchanged.
- New test, a cached spelling is adopted: `_seed(owner, org, bid, 1)`; `_fresh_row(owner, org, bid, [{"title": "Kids Sandals for Boys Summer", "domain": "amazon.in", "brand": "", "model": "", "parse": 2}])`; `gen = _generator(keywords=["kid sandal"])`; `engine = FakeEngine()`. After `_run`: `rows[0].keyword == "kids sandals"`, `rows[0].keywords == ["kids sandals"]`, `engine.prompts == []`, `len(searches) == 1`.
- New test, a stale row's spelling is not adopted: the same, with `_fresh_row(..., days=8)`. After `_run`: `rows[0].keyword == "kid sandal"`, `rows[0].keywords == ["kid sandal"]`, `engine.prompts == [(products.search_query("kid sandal"), "IN", "en")]`, `len(searches) == 2`.
- The existing cache tests (`test_a_fresh_search_is_reused_and_a_stale_one_redone`, `test_a_search_under_the_old_query_is_redone`, `test_a_row_parsed_before_parse_2_is_redone`, `test_a_row_with_no_titles_is_a_hit`, `test_plural_variants_share_one_search`) keep their values: each seeds and votes the same spelling, or no row.

Unit: no new unit test. `_current` is covered through the cache tests, and the seeding is run-level behaviour.

Copy: no prompt changes; the new fixtures and comments are checked against `FORBIDDEN` in `tests/unit/test_recommend_copy.py`.

### 3. Dev re-check

Run by the controller only with the user's OK at that point, by the live-check pattern (the worker loop is never started).

- Expected cost: about 6,000 micros ($0.006): 4 flash-lite calls (3 keyword samples and 1 rewrite) and no grounded search, because every one of the 10 products' keys has a fresh valid row (*inferred* from the stored rows; slice 23's re-check measured 5,800 for the same 4 calls plus one search).
- Each keyword whose key has no fresh valid row adds one grounded search with its parse call, about 38,000 micros.
- Writes: the job, 10 product rows, `api_key.last_used_at`; no `keyword_search` row if no search runs.
- Expected, *inferred*, to be compared with what is observed: LC-05's keyword is "mens flip flops" (the fresh valid row's spelling); the other 9 keywords are unchanged; 0 `keyword_search` rows written; `keyword_search` still has 20 rows.

## Rulings

None yet. Rulings made during execution are added here with their R-number.

## Out of scope

- Deleting stale duplicate rows.
- A key column on `keyword_search`, and any migration.
- Spellings that do not share a `keyword_key`.
- The deferred minors in docs/findings-slice23.md §4.
