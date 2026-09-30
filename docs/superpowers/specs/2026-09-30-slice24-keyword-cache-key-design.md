# Slice 24 design: one cached search per keyword phrase across runs

## Context

Slice 23's dev re-check (docs/findings-slice23.md §3, job `ec137947`) searched "mens flip flops" for LC-05 although a row for "men flip flops" existed: the `keyword_search` cache is keyed by the exact keyword string, so two spellings of one phrase cost two grounded searches (about $0.04 each). Within one run, `run_products`' run-wide `key_map` already merges spellings by `keyword_key` (the stemmed phrase, "men flip flop"), so "mens sandal" and "men sandals" share one search in the same run. Across runs nothing merges them.

On dev the brand has 20 `keyword_search` rows for 13 distinct keys (counted from a read-only query on 2026-09-30). The 7 duplicate pairs are kids shoe/shoes, kids slipper/slippers, men sandals/mens sandal, men shoe/shoes, women sandals/womens sandal, women slipper/slippers and men/mens flip flops; the 6 single rows are boys sandal, boys shoe, girls sandal, kids sandals, men slipper and navy flip flops. (An earlier count in chat said 20 rows for 12 keys and 8 pairs, one of them kids sandal/sandals; there is no "kids sandal" row.)

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
        # loads every fresh valid row of the brand (every distinct
        # keyword searched in SEARCH_TTL_DAYS days); a cached spelling
        # with a brand token can be adopted, since drop_brand_terms runs
        # on the voted spelling first.
        key_map: dict[str, str] = {}
        with tenant_session(org_id) as s:
            for cached in s.scalars(
                select(m.KeywordSearch)
                .where(
                    m.KeywordSearch.brand_id == brand_id,
                    m.KeywordSearch.searched_at > fresh_after,
                    m.KeywordSearch.error.is_(None),
                )
                .order_by(
                    m.KeywordSearch.searched_at.desc(),
                    m.KeywordSearch.keyword,
                )
            ):
                if _current(cached):
                    key_map.setdefault(
                        keyword_key(cached.keyword), cached.keyword
                    )
```

(The plan may place this inside the existing run-start session rather than a second one; either way it runs once per run, before the first batch, with no model call in between. The loop variable is `cached`, not `row`: `run_products` later declares `row: dict[str, Any]` in the same function scope, and mypy --strict rejects a second `row` of another type.)

- What follows without further code: a product whose voted keyword shares a key with a seeded row gets the cached spelling in `p["keyword"]` and `p["keywords"]`; the per-batch lookup then hits on the exact string; no grounded search runs; the stored `keywords` list uses cached spellings.
- Only rows the lookup would accept are seeded (fresh, no error, current query, current parse), so a stale spelling never wins. If two valid rows share a key, the newest spelling is used, and among rows with the same `searched_at` (one run writes every row with the same `now`) the first by keyword string (`order_by(searched_at.desc(), keyword)` with `setdefault`).
- A fresh valid row with no titles is a hit today (slice 20 §5 B); with the seeding, every spelling of its phrase adopts it, so a phrase whose search came back empty is not searched again under another spelling within the TTL.
- Unchanged: the `keyword_search` table and its unique constraint, the lookup's SQL, the insert and its upsert, `keyword_key`, `SEARCH_MICROS`, `KEYWORD_CAP`, R10's budget check.
- Known ceilings (in the comment above): spellings that do not share a key ("man slippers" against "men slippers") are not merged; rows under an old spelling stay in the table once stale, nothing deletes them; the seed query loads every fresh valid row for the brand, that is every distinct keyword the brand searched in the last `SEARCH_TTL_DAYS` days (bounded by the products per brand, `MAX_PRODUCTS`, since only first keywords are searched); `drop_brand_terms` runs on the voted spelling before `key_map`, so a cached spelling that contains a brand token (a "crocs sandals" row from before "Crocs" became an alias) can be adopted by a voted "croc sandals" within the TTL.

### 2. Testing

Integration, `tests/integration/test_products_run.py`:

- `_fresh_row(owner, org, bid, titles, days=1)` gains `days`, the row's age; callers that do not pass it are unchanged.
- New test, a cached spelling is adopted: `_seed(owner, org, bid, 1)`; `_fresh_row(owner, org, bid, [{"title": "Kids Sandals for Boys Summer", "domain": "amazon.in", "brand": "", "model": "", "parse": 2}])`; `gen = _generator(keywords=["kid sandal"])`; `engine = FakeEngine()`. After `_run`: `rows[0].keyword == "kids sandals"`, `rows[0].keywords == ["kids sandals"]`, `engine.prompts == []`, `len(searches) == 1`.
- New test, a stale row's spelling is not adopted: the same, with `_fresh_row(..., days=8)`. After `_run`: `rows[0].keyword == "kid sandal"`, `rows[0].keywords == ["kid sandal"]`, `engine.prompts == [(products.search_query("kid sandal"), "IN", "en")]`, `len(searches) == 2`.
- New test, a row the lookup would reject is not seeded: the same as the first new test, but the row's title has `"parse": 1`. After `_run`: `rows[0].keyword == "kid sandal"`, `engine.prompts == [(products.search_query("kid sandal"), "IN", "en")]`, `len(searches) == 2`.
- The existing cache tests (`test_a_fresh_search_is_reused_and_a_stale_one_redone`, `test_a_search_under_the_old_query_is_redone`, `test_a_row_parsed_before_parse_2_is_redone`, `test_a_row_with_no_titles_is_a_hit`, `test_plural_variants_share_one_search`) keep their values: each seeds and votes the same spelling, or no row.

Unit: no new unit test. `_current` is covered through the cache tests, and the seeding is run-level behaviour.

Copy: no prompt changes; the new fixtures and comments are checked against `FORBIDDEN` in `tests/unit/test_recommend_copy.py`.

### 3. Dev re-check

Run by the controller only with the user's OK at that point, by the live-check pattern (the worker loop is never started).

- Expected cost: about 6,000 micros ($0.006): 4 flash-lite calls (3 keyword samples and 1 rewrite) and no grounded search, because every one of the 10 products' keys has a fresh valid row (*inferred* from the stored rows; slice 23's re-check measured 5,800 for the same 4 calls plus one search).
- Each keyword whose key has no fresh valid row adds one grounded search with its parse call, about 38,000 micros.
- Writes: the job, 10 product rows, `api_key.last_used_at`; no `keyword_search` row if no search runs.
- Which dev row would be seeded per key, from a read-only query run on 2026-09-30 (fresh, no error, current query and parse): kid sandal → "kids sandals"; kid shoe → "kids shoes"; kid slipper → "kids slippers"; men flip flop → "mens flip flops"; men sandal → "men sandals"; men shoe → "men shoes"; navy flip flop → "navy flip flops"; women sandal → "women sandals"; women slipper → "women slippers". The other 11 rows ("kids shoe", "kids slipper", "mens sandal", "womens sandal", "women slipper", "boys sandal", "boys shoe", "girls sandal", "men slipper", "men shoe" and "men flip flops") fail the current-query test (the 10 from 2026-09-25) or the parse test ("men flip flops", 2026-09-29 11:23, current query but no `parse` key), and "men shoe" also has an error, so none is seeded: 9 seeded rows plus 11 others make the 20. These expectations lapse at 2026-10-06 13:10 UTC, when the 7 plural rows searched on 2026-09-29 13:10 go stale ("navy flip flops", searched at the same time, is no product's first keyword; "mens flip flops" lasts until 2026-10-07 09:27).
- Expected, *inferred* from that, to be compared with what is observed: LC-05's keyword is "mens flip flops"; the other 9 keywords are unchanged; 0 `keyword_search` rows written; `keyword_search` still has 20 rows.
- What the re-check shows: no regression and a low cost. It cannot tell this slice from main, because in slice 23's re-check the model already voted every cached spelling, LC-05's included; only the integration tests show the adoption. A different result would appear only if the model voted another spelling on the day (for example "men flip flops"), in which case main would run a search and this slice would not.

## Rulings

None.

## Out of scope

- Deleting stale duplicate rows.
- A key column on `keyword_search`, and any migration.
- Spellings that do not share a `keyword_key`.
- The deferred minors in docs/findings-slice23.md §4.
