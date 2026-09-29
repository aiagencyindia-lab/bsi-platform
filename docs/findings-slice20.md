# Findings: slice 20 — product titles, not store names

## 1. What was built

The fix for slice 19's deferred ruling R5 (findings-slice19 §2 and §3): the titles-parse step stored store names ("Zappos.com", "ShopWSS.com") as product titles, so `missing` suggested "com" and the rewrite put it into LC-01 and LC-02. All code changes are in `packages/core/bsi_core/products.py`. No schema, API or web change.

**`search_query(keyword)`** returns `f"{keyword}: popular products to buy online, with each product's full title"`. `run_products` calls it in place of the inline `f"{keyword} buy online"`. Country and language still go to `adapter.query` as before; the query text has no locale in it.

**The cache-hit check.** The `titles_by_kw.update(...)` generator now keeps a cached row only when `row.query == search_query(row.keyword)`, on top of the existing brand, keyword, freshness and `error IS NULL` (slice 18 R9) filters. A row from the old wording is treated as absent: its keyword is searched again and the existing upsert overwrites the row. So the first run after this change searches every keyword again.

**`titles_prompt`.** Its first line is now `The text below answers the search {search_query(keyword)!r}.`, replacing "…a search for 'kids sandals' buy online." The rules gain one sentence: "A product title names one product; never list a store, retailer, marketplace or brand name on its own."

**`drop_stores(titles, domains)`** runs on the parsed title list before `keep_present`, so the cap of 5 applies to the titles that survive. Order is kept. The known domains for a title are its own domain plus the cited domains, each through `matching.normalize_domain`, skipping empty results. A title is dropped when, for any known domain `d`, its letters and digits joined equal `d`'s name (`d.split(".")[0]`) or its joined form (`zappos.com` → `zapposcom`), or `d` has a dot and is a substring of the casefolded title. So "REEF" (reef.com), "Famous Footwear" (famousfootwear.com) and "Buy at ShopWSS.com" are dropped, and "Zappos Kids Sandal" with zappos.com cited, "Amazon Essentials Sandal" (domain `amazon`, no dot) and "Crocs Classic Clog" are kept. The ceiling is a `# ponytail:` comment: a subdomain's name is its first label (`shop.nike.com` → `shop`), and a store named unlike its domain ("Journeys Kidz", journeys.com) is not caught and is left to the prompt; a unit test pins that case as kept.

**The `com` stopword.** `STOPWORDS` gains `com`, so `missing` never suggests it and `dropped` never reports it.

**Tests.**
- `tests/unit/test_products.py`: `search_query`'s exact text; `titles_prompt` names the new query, no longer says "buy online." and has the store rule; `drop_stores` over the spec's seven dropped cases (one parametrized call each) and five kept cases (one call); order around a dropped title; `missing` never suggests `com`.
- `tests/unit/test_recommend_copy.py`: `PRODUCT_CASES` gains `search_query("kids shoes")`.
- `tests/integration/test_products_run.py`: the three engine-prompt assertions use `search_query(...)`; the fresh-reuse test seeds `query=search_query("kids sandals")`; new `test_a_search_under_the_old_query_is_redone` (a fresh row with `"kids sandals buy online"` is searched again and overwritten); new `test_store_names_are_not_stored_as_titles` ("Zappos.com" with domain zappos.com and "Kids Classic Sandal" stores only "Kids Classic Sandal"), using a new `titles=` parameter on `_generator`. By Ruling R1 (spec `## Rulings`), `test_an_error_search_is_not_reused` seeds its error row with `query=search_query("kids sandals")`, so it tests slice 18's R9 on its own: with `error IS NULL` removed, it fails.
- Backend gate after Task 2: 1486 passed, with the 2 pre-existing library deprecation warnings.

**Commits** (`git log --oneline main..HEAD`, oldest first):

| Commit | Subject |
|---|---|
| 283517a | docs: slice 20 spec (product titles, not store names) |
| bea71d6 | docs: slice 20 spec review fixes |
| dc05e46 | docs: slice 20 spec: correct the cited slice 18/19 cost figures |
| 1ec6ace | docs: slice 20 implementation plan |
| 9a0c966 | docs: slice 20 plan review fixes |
| 2452a9a | docs: slice 20 plan: name the first failing assertion |
| cad40aa | feat(products): ask the grounded search for products; redo old-query rows |
| a63f707 | fix(products): drop store names from parsed titles; com is a stopword |
| 19fa5f8 | docs: slice 20 findings, index and rulings |
| (this commit) | test: slice 20 final review: the R9 test seeds the new query (R1) |

## 2. Live check on dev

Not yet run. The controller runs it after the user approves; results are recorded here then.

## 3. Deferred and untested

From the task reviews:
- A cited domain with a dot is matched as a substring of the title (spec §2 asks for this). So a short cited domain such as `t.co`, or a title that starts with a marketplace domain ("Amazon.in Exclusive Kids Sandal" with amazon.in cited), would be dropped. To watch in the live check.
- The parametrized `drop_stores` drop cases in `tests/unit/test_products.py` have no `ids=`, so a failure is reported as `title0-domains0` and so on.
- `com` in `STOPWORDS` also affects `dropped()`, but only the `missing()` side is tested; spec §3 asks only for `missing`.
- Task 1's report did not name its 2 test warnings. The controller checked them: they are pre-existing library deprecations (Starlette's `TestClient` and anyio's `BlockingPortal`), the same as on `main`.

Untested against real answers:
- Whether the new query wording returns product titles rather than stores, and whether LC-01 and LC-02 lose "Com", is known only after the live check (§2). The unit and integration tests use fixed judge output.
- `drop_stores`'s citation-domain path is covered only by unit tests: the integration test's `FakeEngine` always cites `amazon.in`, so it covers a title's own domain.

Out of scope (spec):
- Locale in the query text, and enforcing the locale on results.
- Storing the grounded answer text.
- Seeding the run-wide key map from cached rows; `-es` plural folding; the side-by-side connectors case; `drop_brand_terms` comparing stems (all in findings-slice19 §3).
- Any schema, API or web change.
