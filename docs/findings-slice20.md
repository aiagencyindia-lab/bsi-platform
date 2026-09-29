# Findings: slice 20 — product titles, not store names

## 1. What was built

The fix for slice 19's deferred ruling R5 (findings-slice19 §2 and §3): the titles-parse step stored store names ("Zappos.com", "ShopWSS.com") as product titles, so `missing` suggested "com" and the rewrite put it into LC-01 and LC-02. All code changes are in `packages/core/bsi_core/products.py`. No schema, API or web change.

**`search_query(keyword)`** returns `f"{keyword}: popular products to buy online, with each product's full title"`. `run_products` calls it in place of the inline `f"{keyword} buy online"`. Country and language still go to `adapter.query` as before; the query text has no locale in it.

**The cache-hit check.** The `titles_by_kw.update(...)` generator now keeps a cached row only when `row.query == search_query(row.keyword)` and every stored title has a `brand` key (`all("brand" in t for t in row.titles)`, so a row with no titles counts as a hit), on top of the existing brand, keyword, freshness and `error IS NULL` (slice 18 R9) filters. A row from the old wording, or one parsed before titles carried brand and model, is treated as absent: its keyword is searched again and the existing upsert overwrites the row. So the first run after the query change searched every keyword again, and the 8 new-query rows written by the first live check (§2) lack the `brand` key, so the next run searches those keywords again.

**`titles_prompt`.** Its first line is now `The text below answers the search {search_query(keyword)!r}.`, replacing "…a search for 'kids sandals' buy online." The rules gain one sentence: "A product title names one product; never list a store, retailer, marketplace or brand name on its own."

**`drop_stores(titles, domains)`** runs on the parsed title list before `keep_present`, so the cap of 5 applies to the titles that survive. Order is kept. The known domains for a title are its own domain plus the cited domains, each through `matching.normalize_domain`, skipping empty results. A title is dropped when, for any known domain `d`, its letters and digits joined equal `d`'s name (`d.split(".")[0]`) or its joined form (`zappos.com` → `zapposcom`), or `d` has a dot and is a substring of the casefolded title. So "REEF" (reef.com), "Famous Footwear" (famousfootwear.com) and "Buy at ShopWSS.com" are dropped, and "Zappos Kids Sandal" with zappos.com cited, "Amazon Essentials Sandal" (domain `amazon`, no dot) and "Crocs Classic Clog" are kept. The ceiling is a `# ponytail:` comment: a subdomain's name is its first label (`shop.nike.com` → `shop`), and a store named unlike its domain ("Journeys Kidz", journeys.com) is not caught and is left to the prompt; a unit test pins that case as kept.

**The `com` stopword.** `STOPWORDS` gains `com`, so `missing` never suggests it and `dropped` never reports it.

**Extension after the first live check: rival brand and model names (spec §5).** The first live check (§2) showed `missing` suggesting rival brand and model words, because it excluded only the brand's own names. So:
- **Brand and model per title.** `TitleItem` gains `brand: str = ""` and `model: str = ""`. `titles_prompt` gains the sentence "For each title also give its brand and its model or product-line name, each as written in the title, else an empty string." and its JSON line is now `'Return JSON {"titles": [{"title": ..., "domain": ..., "brand": ..., "model": ...}]}.\n'`.
- **`_named_in(value, title)`**, used by `keep_present` for `brand` and `model`, returns the stripped value only when it has tokens and all of them are in the title's tokens; otherwise `""`. So the parse cannot add an exclusion the title does not name ("Nike" for "Teva Original Universal Sandals" is stored as `""`). Each stored title is now `{"title", "domain", "brand", "model"}` in the existing `keyword_search.titles` JSON; no schema change.
- **`missing(product_title, titles, brand_names, exclude=())`**: the `have` set is now `fold_set(product_title) | _brand_stems([*brand_names, *exclude])`, so a ranking-title word whose stem is among the excluded names' stems is not counted.
- **Competitors.** `run_products` loads `rivals`, the `name` and `aliases` of every `competitor` row of the brand (`suggested` ones included), in the same tenant session that loads the brand. Per product, `exclude` is `rivals` plus every non-empty `brand` and `model` of that keyword's ranking titles.
- **The ceiling** is a `# ponytail:` comment at the `missing` call: a generic word in a model ("Classic") is excluded for that keyword, and one in a competitor's name or alias for every keyword.
- **Ruling R2** (spec `## Rulings`): `test_a_search_under_the_old_query_is_redone` seeds its titles with `brand` and `model` keys, so only the query-wording condition can force its re-search.

**Tests.**
- `tests/unit/test_products.py`: `search_query`'s exact text; `titles_prompt` names the new query, no longer says "buy online." and has the store rule; `drop_stores` over the spec's seven dropped cases (one parametrized call each) and five kept cases (one call); order around a dropped title; `missing` never suggests `com`.
- `tests/unit/test_recommend_copy.py`: `PRODUCT_CASES` gains `search_query("kids shoes")`.
- `tests/integration/test_products_run.py`: the three engine-prompt assertions use `search_query(...)`; the fresh-reuse test seeds `query=search_query("kids sandals")`; new `test_a_search_under_the_old_query_is_redone` (a fresh row with `"kids sandals buy online"` is searched again and overwritten); new `test_store_names_are_not_stored_as_titles` ("Zappos.com" with domain zappos.com and "Kids Classic Sandal" stores only "Kids Classic Sandal"), using a new `titles=` parameter on `_generator`. By Ruling R1 (spec `## Rulings`), `test_an_error_search_is_not_reused` seeds its error row with `query=search_query("kids sandals")`, so it tests slice 18's R9 on its own: with `error IS NULL` removed, it fails.
- Backend gate after Task 2: 1486 passed, with the 2 pre-existing library deprecation warnings.
- Extension (Task 4), `tests/unit/test_products.py`: `test_keep_present_drops_titles_absent_from_the_text` now expects `"brand": ""` and `"model": ""`; new tests for `keep_present` keeping a brand and model named in the title ("Teva" / "Hurricane XLT 2"), blanking a brand not in the title (`""` / "Original Universal") and storing `""` / `""` without the keys; `missing` with `exclude=["Teva", "Hurricane XLT 2", "Original Universal"]` gives `["kids"]`, and without `exclude` contains `teva`; `titles_prompt` asks for brand and model.
- Extension (Task 4), `tests/integration/test_products_run.py`: the four exact stored-title assertions gain `"brand": ""` and `"model": ""`; the fresh-reuse test and (R2) the old-query test seed titles with the keys; new helper `_fresh_row`; new `test_a_row_parsed_without_brand_is_redone` (searched again, and the new titles carry `brand` and `model`), `test_a_row_with_no_titles_is_a_hit` (the engine is not called) and `test_rival_brands_models_and_competitors_are_not_missing_words` (`missing_keywords == ["summer"]`; before the run changes it failed with `["summer", "crocs", "hurricane", "teva"]`).
- Backend gate after Task 4: 1494 passed, with the same 2 library deprecation warnings.

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
| 9ecbb33 | test: slice 20 final review: the R9 test seeds the new query (R1) |
| 10765f8 | docs: slice 20 audit fixes (section-approval record, stale reasons) |
| 8129e17 | docs: slice 20 plan: name the R1 commit |
| 509b2bf | docs: slice 20 plan: fix the R1 bullet's table reference |
| e6f95a8 | docs: slice 20 spec: exclude rival brand and model names (extension) |
| f0f8e80 | docs: slice 20 spec extension review fixes |
| 8fc0ba5 | docs: slice 20 spec: correct the first live check's spend sentence |
| 78789a6 | docs: slice 20 plan: Tasks 4-5 for the rival brand and model extension |
| 78dd56b | docs: slice 20 extension plan review fixes; ruling R2 in the spec |
| dbd9328 | docs: slice 20 extension plan: re-review fixes (sources, R2 check, self-review) |
| 42300cc | fix(products): keep rival brands, models and competitors out of missing words |
| (this commit) | docs: slice 20 extension findings and first live check |

## 2. Live check on dev

**First live check** (before the extension), run with the user's OK ("Live check, then merge"), with the steps of spec §4. Observed (controller's ledger and a read-only query after the job):
- Job `d73eaefa`, done in about 1 min 51 s, `cost_micros = 313,103` (about $0.31; spec §4 estimated 306,000). The project's model spend tally went from $9.9377 to about $10.25 of the $15 cap.
- 8 new-query searches, each storing 5 titles (`jsonb_array_length(titles) = 5` on all 8 rows); 0 errors; 0 store names among the stored titles.
- LC-01 and LC-02 no longer carry "Com".
- New problem: `missing` suggested rival brand and model words, because it excluded only the brand's own names: LC-01 and LC-02 got "Teva Hurricane XLT", LC-03 "Big Nike Boots", LC-06 "Birkenstock". This led to the extension (§1, spec §5).
- "Gender Inclusive" (LC-08) and "Color" (LC-05) were also suggested. They are generic attribute words, which spec §5 keeps as missing words when 2 or more titles use them.
- LC-05's keyword was "navy flip flops"; `rule_check` gave `review`, with `men` dropped. The keyword vote choosing a colour phrase is out of scope (spec).
- One stored title carries answer commentary: "Teva Psyclone (Top overall recommendation for kids' sandals)". Out of scope (spec).
- Writes: the job row, 10 `product` rows, 8 `keyword_search` rows, `api_key.last_used_at` (10:30:37 UTC). The 11 rows under the old query were untouched. Worker and API stopped afterwards; 0 jobs queued.

Per product, as observed (missing words as stored; the suggested title as recorded in the ledger, which gives only its end; rule check status):

| Product | Keyword | Missing words | Suggested title (end) | Status |
|---|---|---|---|---|
| LC-01 | kids sandals | teva, kids, hurricane, xlt | "…Blue Boys Sandal Teva Hurricane XLT Kids" | adjusted |
| LC-02 | kids sandals | teva, kids, hurricane, xlt | "…Pink Girls Sandal Teva Hurricane XLT Kids" | adjusted |
| LC-03 | kids shoes | big, nike, boots | "…Black Kids Sports Shoe Big Nike Boots" | pass |
| LC-04 | kids slippers | (none) | "…Grey Kids Slipper" | pass |
| LC-05 | navy flip flops | color | "…Navy Flip Flop Color" | review (dropped `men`) |
| LC-06 | men sandals | birkenstock | "…Brown Men Casual Sandal Birkenstock" | pass |
| LC-07 | women slippers | (none) | (not recorded) | pass |
| LC-08 | men shoes | gender, inclusive, sneaker | "…Grey Men Sports Shoe Gender Inclusive Sneaker" | pass |
| LC-09 | kids shoes | kids, big, nike, boots | "…Black Boys School Shoe Big Nike Boots Kids" | adjusted |
| LC-10 | women sandals | jelly | "…Tan Women Sandal Jelly" | pass |

Second live check: not yet run. The controller runs it after this task; results are recorded here then.

## 3. Deferred and untested

From the task reviews:
- A cited domain with a dot is matched as a substring of the title (spec §2 asks for this). So a short cited domain such as `t.co`, or a title that starts with a marketplace domain ("Amazon.in Exclusive Kids Sandal" with amazon.in cited), would be dropped. To watch in the live check.
- The parametrized `drop_stores` drop cases in `tests/unit/test_products.py` have no `ids=`, so a failure is reported as `title0-domains0` and so on.
- `com` in `STOPWORDS` also affects `dropped()`, but only the `missing()` side is tested; spec §3 asks only for `missing`.
- Task 1's report did not name its 2 test warnings. The controller checked them: they are pre-existing library deprecations (Starlette's `TestClient` and anyio's `BlockingPortal`), the same as on `main`.
- Competitor aliases are untested: the rival test's competitor has only a name, so dropping `*c.aliases` from `rivals` in `run_products` passes every test.
- `_named_in`'s edge cases are untested: a value with no letters or digits becoming `""`, and "XLT-2" matching "XLT 2".

Known ceilings (spec §5, stated in the `# ponytail:` comment at the `missing` call):
- A generic word inside a model name is excluded for that keyword: model "Classic" for "Crocs Kids' Classic Slipper" stops "classic" being suggested.
- A generic word in a competitor's name or alias is excluded for every keyword.

Untested against real answers:
- The first live check (§2) observed product titles, not stores, for all 8 searches, and LC-01 and LC-02 without "Com". Whether the missing words and suggestions still carry a rival brand or model word after the extension is known only after the second live check. The unit and integration tests use fixed judge output.
- `drop_stores`'s citation-domain path is covered only by unit tests: the integration test's `FakeEngine` always cites `amazon.in`, so it covers a title's own domain.

Out of scope (spec):
- Locale in the query text, and enforcing the locale on results.
- Storing the grounded answer text.
- Seeding the run-wide key map from cached rows; `-es` plural folding; the side-by-side connectors case; `drop_brand_terms` comparing stems (all in findings-slice19 §3).
- Any schema, API or web change.
- The keyword vote choosing a colour phrase (LC-05 got "navy flip flops" in the first live check).
- Answer commentary kept inside a verbatim title ("Teva Psyclone (Top overall recommendation for kids' sandals)").
