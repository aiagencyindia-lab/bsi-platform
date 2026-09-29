# Slice 20 design: product titles, not store names

## Context

Slice 19 deferred ruling R5 (docs/findings-slice19.md §3): the titles-parse step stores store names as product titles. On dev, the search for `kids sandals` stored "Zappos.com" and "ShopWSS.com", so `missing` returned `com`, and LC-01 and LC-02 carry "…Sandal Com Kids".

Exploration on 2026-09-29 read the `titles` column of the 8 `keyword_search` rows written that day. Observed:

| Keyword | Stored titles |
|---|---|
| kids sandals | Famous Footwear, Zappos.com, Next USA, Journeys Kidz, ShopWSS.com |
| kids shoes | Famous Footwear, ShopWSS, Kids Foot Locker, Shoe City, Shoe Carnival |
| men shoes | Zappos, DSW (Designer Shoe Warehouse), Shoe Carnival, Shoe Sensation, Shoe City |
| men flip flops | REEF, Olukai, Oofos, Tradehome Shoes, Walmart.com |
| men sandals | Arizona, Gizeh Essentials, Z/1 Classic, Original Universal, Newport H2 |
| kids slippers | Kids' Classic Slipper, Classic Cozzzy Slippers, Unfurgettable Vegan Suede Clogs, Kids Lanner Ridge II Slipper, Kids Riley Shimmer Slipper |
| women sandals | none |
| women slippers | none |

Four searches stored only store or brand names, two stored nothing, two stored product names. "Com" is one symptom of that. *Inferred*, not observed: the query `"{keyword} buy online"` makes the engine answer with where to shop. The answer text is not stored (not in `keyword_search`, not under `RAW_STORE_DIR`), so the cause of the two empty results is unknown.

Classification, said in chat as the first line of the first brainstorming reply: **bounded** — a quality fix confined to the titles-parse step in `bsi_core/products.py` (prompt wording, a domain filter on parsed titles, one stopword), with no schema, API or UI change. The scope then grew, by the user's choice, to include the query wording; it is still a change to one existing flow in one file. By the user's standing rule it gets a spec, a plan and the full review cycle.

Decisions approved in chat (brainstorming on Fable 5.1, 2026-09-29). Sections 2 and 3 had their design text in chat before their approval. Section 1 (query and cache) did not: its approval was asked without its own text, and its query wording and cache rule had appeared only in the approaches message (found in the slice 20 audit):

- **Scope:** the parse fix plus the query wording.
- **Locale:** stays out of the query text; it is its own later slice.
- **Approach A with the narrowed filter:** reword the query, keep the two-step parse, filter store names in code, add `com` to `STOPWORDS`, and count a cached row as a hit only when its query matches. Rejected: B, a fixed answer format parsed with a regex (saves about 1,500 micros per search; a format slip gives zero titles); C, a second search when too few titles remain (about double the cost for most keywords).
- **The filter rule:** a title is dropped when it equals the store's name ("REEF" from reef.com) or contains the store's full domain ("ShopWSS.com"). A title that only contains the store's name is kept, so "Zappos Kids Sandal" survives when zappos.com is cited. The rejected rule was "drop a title that contains the store's name".

Codebase facts the design rests on (read on 2026-09-29, `main` = `3f303b1`):

- `run_products` builds the query inline: `query = f"{keyword} buy online"`.
- Cached rows are loaded by the `titles_by_kw.update(...)` generator, whose select filters `brand_id`, `keyword IN (…)`, `searched_at > fresh_after` and `error IS NULL` (slice 18 R9); then `new = [k for k in ordered if k not in titles_by_kw]`.
- `titles_prompt`'s first line is `f"The text below answers a search for {keyword!r} buy online.\n"`.
- `matching.normalize_domain(value)` casefolds, strips a scheme, path, query, user part, port, a leading `www.` and a trailing dot.
- A `keyword_search` row's `cost_micros` is the search plus its parse call. Slice 19 estimated $0.27–$0.38 at 37,500 per search; its 8-search run measured 308,958, close to 8 × 37,500 + 6,000 = 306,000.
- Nothing outside `run_products` reads `keyword_search.query`; the API only deletes rows.
- A search result is written with `INSERT … ON CONFLICT (uq_keyword_search_brand_keyword) DO UPDATE`, which overwrites `query`, `titles`, `model`, `cost_micros`, `error` and `searched_at`.
- After a search: `parsed = adapter.parse(result.raw)`; `domains = sorted({d for _, d in parsed.citations if d})`; the judge is called with `titles_prompt(keyword, parsed.text, domains)` and `TitleSet`; `row["titles"] = keep_present([...], parsed.text)`.
- `keep_present(titles, text)` keeps titles found verbatim in the text, lowercases domains and caps at `TOP_TITLES = 5`.
- `GeminiGroundingAdapter.parse` normalises citation hosts with `normalize_domain`.
- `products.tokens(text)` is `[a-z0-9]+` over the casefolded text.
- `STOPWORDS` is used by `missing` (tokens of 3 or more characters) and `dropped`.

## Design

All code changes are in `packages/core/bsi_core/products.py`.

### 1. Query and cache

- New `search_query(keyword: str) -> str` returns `f"{keyword}: popular products to buy online, with each product's full title"`. `run_products` calls it in place of the inline f-string.
- Country and language still go to `adapter.query` as now. The query text is locale-free.
- A cached row is a hit only when `row.query == search_query(row.keyword)`. The check is a condition in the `titles_by_kw.update(...)` generator, on the rows the existing select returns. A row that fails it is treated as absent: its keyword stays in `new`, is searched, and the existing upsert overwrites the row.
- Unchanged: `SEARCH_TTL_DAYS`, R9, `KEYWORD_CAP`, the R10 budget check, `SEARCH_MICROS`, the `keyword_search` schema.
- Cost effect: the first run after this change searches every keyword again, because no existing row has the new query.

### 2. Parsing the answer

- `titles_prompt`'s first line names the new query: `f"The text below answers the search {search_query(keyword)!r}.\n"`. The rest keeps its current rules and gains this sentence: "A product title names one product; never list a store, retailer, marketplace or brand name on its own."
- New `drop_stores(titles: list[dict[str, Any]], domains: Sequence[str]) -> list[dict[str, Any]]`, called on the parsed list before `keep_present`, so the cap of 5 applies to what survives. Order is kept.
  - Each title is read as `str(t.get("title") or "")` and its domain as `str(t.get("domain") or "")`, as `keep_present` reads them.
  - Known domains for a title: its own domain plus `domains` (the citation domains), each passed through `matching.normalize_domain`; empty results are skipped.
  - For a known domain `d`: its **name** is `d.split(".")[0]`; its **joined form** is `"".join(tokens(d))` (`zappos.com` → `zapposcom`).
  - The title's **squashed form** is `"".join(tokens(title))`.
  - The title is dropped when, for any known domain, the squashed form equals the name or the joined form, or `d` contains a `.` and is a substring of the casefolded title. A domain without a dot ("amazon", "x" — the field is free model text) is only compared by name, so "Amazon Essentials Sandal" is kept.
  - Known ceiling, stated in a code comment: a subdomain gives its first label as the name (`shop.nike.com` → `shop`); a store whose name differs from its domain ("Journeys Kidz", journeys.com) is not caught and is left to the prompt.
- `STOPWORDS` gains `com`. No other ending is added. This affects `missing` (a `com` token is never suggested) and `dropped` (a `com` token in an original title is never reported as dropped).
- Unchanged: `keep_present`, `missing`, `dropped`, `rule_check`, `rewrite_prompt`, `keyword_prompt`, the stored shape of `titles`.
- When 0 or 1 titles survive, nothing new happens: `missing` needs a stem in at least `MIN_TITLES = 2` titles, so it returns `[]` and the rewrite gets the keyword only.

### 3. Testing

Unit, `tests/unit/test_products.py`:

- `search_query("kids sandals") == "kids sandals: popular products to buy online, with each product's full title"`.
- `drop_stores` drops, with `domains=[]` unless stated:
  - `{"title": "Famous Footwear", "domain": "famousfootwear.com"}`
  - `{"title": "Zappos.com", "domain": "zappos.com"}`
  - `{"title": "REEF", "domain": "reef.com"}`
  - `{"title": "Kids Foot Locker", "domain": "www.kidsfootlocker.com"}`
  - `{"title": "Zappos.com", "domain": ""}` with `domains=["zappos.com"]`
  - `{"title": "Buy at ShopWSS.com", "domain": "shopwss.com"}`
  - `{"title": "Zappos", "domain": "https://www.zappos.com/kids"}` (the domain is normalised first)
- `drop_stores` keeps, in order:
  - `{"title": "Crocs Classic Clog", "domain": "crocs.com"}`
  - `{"title": "Zappos Kids Sandal", "domain": ""}` with `domains=["zappos.com"]`
  - `{"title": "Amazon Essentials Sandal", "domain": "amazon"}`
  - `{"title": "Kids Lanner Ridge II Slipper", "domain": ""}`
  - `{"title": "Journeys Kidz", "domain": "journeys.com"}` — the documented ceiling, commented as such in the test so a later fix knows to flip it.
- `titles_prompt("kids sandals", "answer text", ["amazon.in"])` contains `search_query("kids sandals")`, does not contain "buy online.", and contains "never list a store, retailer, marketplace or brand name on its own".
- `missing("Blue Sandal", ["Zappos com sandal", "ShopWSS com sandal"], [])` does not contain `com`.

Unit, `tests/unit/test_recommend_copy.py`: `search_query` is imported, and `PRODUCT_CASES` gains `search_query("kids shoes")`.

Integration, `tests/integration/test_products_run.py`:

- The three assertions on the engine prompt use `search_query(...)`'s text: in `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` and `test_an_error_search_is_not_reused` (`kids sandals`), and in `test_plural_variants_share_one_search` (`mens sandal`).
- `test_a_fresh_search_is_reused_and_a_stale_one_redone` seeds its fresh row with `query=search_query("kids sandals")` instead of `"q"`, so it stays a hit. It is the test that a new-query row is a hit; no separate test is added.
- The other rows seeded with `query="q"` or a "buy online" query (`test_isolation.py`, `test_api_products.py`, `test_rls.py`) stay as they are: `run_products` never reads them.
- `test_an_error_search_is_not_reused` seeds its error row with `query=products.search_query("kids sandals")` (R1), so only the `error IS NULL` filter makes the run search it again.
- New: a fresh, error-free cached row whose `query` is `"kids sandals buy online"` is searched again; afterwards the row's `query` is the new text and its `titles` are the new result.
- New: a run whose judge returns the titles "Zappos.com" (domain zappos.com) and "Kids Classic Sandal" stores only "Kids Classic Sandal". This needs a `titles=` parameter on the test file's `_generator` (its titles body is fixed today) and a `FakeEngine` whose answer text contains both titles. `FakeEngine.parse` always cites `amazon.in`, so this test covers the title's own-domain path; the citation path is covered by the unit tests.
- The "idle in transaction" probe keeps covering the search step; session handling does not change.

Gates: the backend gate and `npm run gate`, run by the controller.

### 4. Dev re-check

Run only with the user's OK, asked at that point.

- No migration; dev stays at 0020. The worker stays stopped.
- Steps: queue one `product_run` for the brand's 10 products, confirm exactly one job is queued, run `process_job` once.
- Writes: the job row, 10 `product` rows, up to 10 `keyword_search` rows, `api_key.last_used_at`.
- Cost estimate, derived:

| Item | Count | Each (micros) | Total (micros) |
|---|---|---|---|
| Grounded searches, parse call included | 8 | 37,500 | 300,000 |
| Keyword calls (3 samples, 1 batch) | 3 | 1,500 | 4,500 |
| Rewrite call | 1 | 1,500 | 1,500 |
| Total | | | 306,000 (about $0.31) |

  Slice 19's 8-search run measured 308,958 against the same arithmetic. With 10 distinct keywords: 10 × 37,500 + 6,000 = 381,000 (about $0.38). *Inferred:* asking for full titles may lengthen the answer and the parse input a little, so the per-search figure may rise. Spend would go from $9.9377 to between about $10.24 and $10.32 of the $15 cap.
- Reported as observed: per keyword, how many stored titles are products and how many are stores; whether LC-01 and LC-02 still carry "Com"; the job's cost.
- The slice does not promise product titles for every keyword. If the new wording still returns stores, findings record the counts.

### 5. Extension after the first live check: rival brand and model names

The first dev live check (job `d73eaefa`, 2026-09-29, `cost_micros = 313,103`, which took the project's model spend tally from $9.9377 to about $10.25 of the $15 cap) removed store names: its 8 searches each stored 5 titles, all of them product names. But `missing` then suggested rival brand and model words from those titles, observed: LC-01 and LC-02 got "Teva Hurricane XLT", LC-03 "Big Nike Boots", LC-06 "Birkenstock". `missing` excludes only the brand's own name. The user chose to fix this in slice 20 before merge. Findings §2 records the full run in the docs task.

Classification, said in chat as the first line of the reply that re-opened brainstorming: **bounded**. This extends slice 20's existing `missing` step in `products.py` so it drops rival brand and model words, with no schema, API or UI change.

Decisions approved in chat (brainstorming on Opus 5.5, 2026-09-29). Sections A, B and C each had their design text in chat before their approval:

- **Scope:** exclude rival brand names and model or product-line names. Generic shopper words still count, including attribute words such as "Gender Inclusive" or "Color" when 2 or more titles use them.
- **Approach A:** the parse step returns each title's brand and model. Rejected: B, the title's generic part only (a model the parse misses in one title still counts); C, dropping each title's first word (misses model names, drops real first words).

This overrides §2's "Unchanged" line for `keep_present`, `missing` and the stored shape of `titles`, and adds a second condition to §1's cache hit.

**A. The parse step returns brand and model**

- `TitleItem` gains `brand: str = ""` and `model: str = ""`.
- `titles_prompt` gains the sentence "For each title also give its brand and its model or product-line name, each as written in the title, else an empty string." Its JSON shape becomes `{"titles": [{"title": ..., "domain": ..., "brand": ..., "model": ...}]}`.
- `keep_present` also carries `brand` and `model`: each is kept, as the stripped string the model wrote, only when `tokens(value)` is non-empty and every one of them is in `tokens(title)` (`tokens` is `[a-z0-9]+` over the casefolded text, so "XLT-2" matches "XLT 2"); otherwise it is stored as `""`. A value whose token set equals the title's token set is stored as `""` (Ruling R4). A value with no letters or digits is `""`. Each stored title is `{"title", "domain", "brand", "model"}` in the existing `keyword_search.titles` JSON. No schema change.
- Unchanged: `drop_stores`, `search_query`, `rewrite_prompt`, one parse call per search.

**B. What `missing` leaves out, and the cache**

- `missing(product_title, titles, brand_names, exclude=())` gains `exclude: Sequence[str]`: its `have` set becomes `fold_set(product_title) | _brand_stems([*brand_names, *exclude])`, so a ranking-title word whose stem is among the excluded names' stems is not counted, exactly as the brand's own stems are not.
- `run_products` builds `exclude` per product, in the loop that calls `missing`, from `titles_by_kw.get(p["keyword"], [])`: every non-empty `t.get("brand")` and `t.get("model")`, plus the `name` and `aliases` of every `competitor` row of the brand. Including `suggested` (unconfirmed) competitors is deliberate: leaving a rival's name out of a suggestion is harmless. The competitors are loaded once, with `select(m.Competitor).where(m.Competitor.brand_id == brand_id)`, in the same tenant session that loads the brand.
- Known ceiling, stated in a code comment: a generic word inside a model name is excluded for that keyword (model "Classic" for "Crocs Kids' Classic Slipper" stops "classic" being suggested), and a generic word in a competitor's name or alias is excluded for every keyword.
- A cached row is a hit only when its `query` equals `search_query(row.keyword)` (§1) and every stored title has a `brand` key. A row with no titles counts as a hit. The rows written before this extension lack the key: the 8 new-query rows written by the first live check each hold 5 titles, so all 8 keywords are searched again.
- Unchanged: `MIN_TITLES`, `MAX_MISSING`, `STOPWORDS`, `rule_check`, `rewrite_prompt`.

**C. Testing**

Unit, `tests/unit/test_products.py`:

- `keep_present([{"title": "Teva Hurricane XLT 2 Sandals - Kids'", "domain": "", "brand": "Teva", "model": "Hurricane XLT 2"}], text)`, with the title in `text`, stores `brand` "Teva" and `model` "Hurricane XLT 2".
- `keep_present([{"title": "Teva Original Universal Sandals", "domain": "", "brand": "Nike", "model": "Original Universal"}], text)`, with the title in `text`, stores `brand` `""` and `model` "Original Universal".
- `keep_present` given a title without `brand` or `model` keys stores `""` for both.
- For the title "Teva Hurricane XLT 2 Sandals", present in `text`: `keep_present` stores `model` `""` for model "-" (no letters or digits), "XLT-2" for model "XLT-2" (tokens match across punctuation), and `""` for model "Teva Hurricane XLT 2 Sandals", the whole title (Ruling R4).
- With `titles = ["Teva Hurricane XLT 2 Sandals - Kids'", "Teva Hurricane XLT 2 Sandals - Toddlers'", "Teva Original Universal Sandals - Kids'"]`: `missing("Blue Boys Sandal", titles, ["BSOAgentTestBrand"], exclude=["Teva", "Hurricane XLT 2", "Original Universal"]) == ["kids"]`, and the same call without `exclude` contains `teva`.
- `titles_prompt(...)` contains "For each title also give its brand and its model or product-line name".
- The existing `test_keep_present_drops_titles_absent_from_the_text` expects `"brand": ""` and `"model": ""` in its stored title.

Integration, `tests/integration/test_products_run.py`:

- New: the parse returns "Teva Hurricane Summer Sandals" and "Teva Hurricane Summer Slides" (brand "Teva", model "Hurricane") and "Crocs Summer Sandals" and "Crocs Classic Summer Sandals" (brand and model empty), all present in the answer text; the brand has a `suggested` `competitor` row named "Deckers" with alias "Crocs" (Ruling R5). The product's `missing_keywords == ["summer"]` (without the extension it would be `["summer", "crocs", "hurricane", "teva"]`).
- New: a fresh, error-free row whose `query` is `search_query("kids sandals")` but whose titles have no `brand` key is searched again, and afterwards the row's titles carry `brand` and `model`.
- New: a fresh, error-free row whose `query` is `search_query("kids sandals")` and whose `titles` is `[]` is a hit: the engine is not called.
- `test_a_fresh_search_is_reused_and_a_stale_one_redone` seeds its titles with `brand` and `model` keys so the row stays a hit.
- `test_a_search_under_the_old_query_is_redone` seeds its titles with `brand` and `model` keys, so only the query-wording condition can force its re-search (Ruling R2).
- Every exact assertion on stored titles gains `"brand": ""` and `"model": ""` (the default fake parse returns neither): in `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked`, `test_an_error_search_is_not_reused`, `test_a_search_under_the_old_query_is_redone` and `test_store_names_are_not_stored_as_titles`.

Gates: the backend gate and `npm run gate`, run by the controller.

**Second dev live check.** Under the user's earlier OK ("live check, then merge"), with the steps of §4. The 8 keywords are searched again (today's rows lack `brand`). Cost, derived: 8 × 37,500 + 6,000 = 306,000 micros (about $0.31); 10 × 37,500 + 6,000 = 381,000 (about $0.38) with 10 keywords. *Inferred:* asking for brand and model lengthens the parse output a little, so the per-search figure may rise. Spend would go from about $10.25 to about $10.56–$10.63 of the $15 cap. Writes: the job row, 10 `product` rows, up to 10 `keyword_search` rows, `api_key.last_used_at`. Reported as observed: per product, whether its missing words or suggestion still carry a rival brand or model word. Findings §2 records both live checks.

## Rulings

- **R1: `test_an_error_search_is_not_reused` seeds the new query.** Decided: its error row is seeded with `query=products.search_query("kids sandals")` instead of `query="q"`. Why: §1 keeps slice 18's R9 (an error row is searched again) unchanged, and this is the only test of R9; with `query="q"` the new query check alone forces the search again, so deleting `m.KeywordSearch.error.is_(None)` would pass every test. Found by the final whole-branch review (controller ruling, 2026-09-29). This overrides the §3 line and the plan line that said this row stays as it is. Cost if wrong: one test line. §3 above is updated.

- **R2: `test_a_search_under_the_old_query_is_redone` seeds titles with brand and model keys.** Decided: its seeded row's titles carry `"brand": ""` and `"model": ""`. Found by the plan review of the extension (controller ruling, 2026-09-29). Why: once a row without a `brand` key is searched again, that test's seeded row is redone by the brand condition alone, so deleting the query-wording condition would pass every test (the same gap R1 closed for R9). It adds to §5 C's list. Cost if wrong: one test fixture.

- **R3: findings §2 takes every product's results from the ledger.** Decided: the docs task records each product's missing words and suggested title from the ledger line "Live check 1 per-product results", not only the examples the plan's Task 5 Step 2 names (it omitted LC-09's "Big Nike Boots"). Found by the plan re-review of the extension (controller ruling, 2026-09-29), applied in the Task 5 brief instead of another plan commit. Cost if wrong: one findings line.

- **R4: a brand or model that is the whole title is stored as `""`.** Decided: `_named_in(value, title)` returns `""` when the value's token set equals the title's token set. Found by the final whole-branch review of the extension (controller ruling, 2026-09-29). Why: a brand or model that is the whole title would exclude every generic word of the keyword. Cost if wrong: one guard; a title that is only its brand keeps no exclusion.

- **R5: the rival integration test reaches "crocs" only through an alias.** Decided: `test_rival_brands_models_and_competitors_are_not_missing_words` seeds its competitor as `name="Deckers", aliases=["Crocs"], status="suggested"`. Found by the final whole-branch review of the extension (controller ruling, 2026-09-29). Why: with the competitor named "Crocs", deleting `*c.aliases` from the exclusion would pass every test. Cost if wrong: one fixture.

## Out of scope

- Locale in the query text, and enforcing the locale on results.
- Storing the grounded answer text.
- Seeding the run-wide key map from cached rows; `-es` plural folding; the side-by-side connectors case; `drop_brand_terms` comparing stems (all in findings-slice19 §3).
- Any schema, API or web change.
- The keyword vote choosing a colour phrase (LC-05 got "navy flip flops" in the first live check).
- Answer commentary kept inside a verbatim title ("Teva Psyclone (Top overall recommendation for kids' sandals)").
