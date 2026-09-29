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

Decisions approved in chat (brainstorming on Fable 5.1, 2026-09-29). Each design section's text was shown in chat before its approval:

- **Scope:** the parse fix plus the query wording.
- **Locale:** stays out of the query text; it is its own later slice.
- **Approach A with the narrowed filter:** reword the query, keep the two-step parse, filter store names in code, add `com` to `STOPWORDS`, and count a cached row as a hit only when its query matches. Rejected: B, a fixed answer format parsed with a regex (saves about 1,500 micros per search; a format slip gives zero titles); C, a second search when too few titles remain (about double the cost for most keywords).
- **The filter is narrower than the slice 19 note** ("equal or contain their own domain"): a title that only contains the store's name is kept, so "Crocs Classic Clog" from crocs.com survives.

Codebase facts the design rests on (read on 2026-09-29, `main` = `3f303b1`):

- `run_products` builds the query inline: `query = f"{keyword} buy online"`.
- Cached rows are loaded with `keyword IN (…)`, `searched_at > fresh_after` and `error IS NULL` (slice 18 R9), then `new = [k for k in ordered if k not in titles_by_kw]`.
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
- A cached row is a hit only when `row.query == search_query(row.keyword)`. The check is done in Python on the rows the existing select returns. A row that fails it is treated as absent: its keyword stays in `new`, is searched, and the existing upsert overwrites the row.
- Unchanged: `SEARCH_TTL_DAYS`, R9, `KEYWORD_CAP`, the R10 budget check, `SEARCH_MICROS`, the `keyword_search` schema.
- Cost effect: the first run after this change searches every keyword again, because no existing row has the new query.

### 2. Parsing the answer

- `titles_prompt` keeps its current rules and gains this sentence: "A product title names one product; never list a store, retailer, marketplace or brand name on its own."
- New `drop_stores(titles: list[dict[str, Any]], domains: Sequence[str]) -> list[dict[str, Any]]`, called on the parsed list before `keep_present`, so the cap of 5 applies to what survives. Order is kept.
  - Known domains for a title: its own `domain` field plus `domains` (the citation domains). Each is stripped, lowercased and has a leading `www.` removed; empty ones are skipped.
  - For a known domain `d`: its **name** is `d.split(".")[0]`; its **joined form** is `"".join(tokens(d))` (`zappos.com` → `zapposcom`).
  - The title's **squashed form** is `"".join(tokens(title))`.
  - The title is dropped when, for any known domain, the squashed form equals the name or the joined form, or `d` is a substring of the casefolded title.
  - Known ceiling, stated in a code comment: a subdomain gives its first label as the name (`shop.nike.com` → `shop`); a store whose name differs from its domain ("Journeys Kidz", journeys.com) is not caught and is left to the prompt.
- `STOPWORDS` gains `com`. No other ending is added.
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
- `drop_stores` keeps, in order:
  - `{"title": "Crocs Classic Clog", "domain": "crocs.com"}`
  - `{"title": "Kids Lanner Ridge II Slipper", "domain": ""}`
  - `{"title": "Journeys Kidz", "domain": "journeys.com"}`
- `titles_prompt("kids sandals", "answer text", ["amazon.in"])` contains "never list a store, retailer, marketplace or brand name on its own".
- `missing("Blue Sandal", ["Zappos com sandal", "ShopWSS com sandal"], [])` does not contain `com`.

Unit, `tests/unit/test_recommend_copy.py`: `PRODUCT_CASES` gains `search_query("kids shoes")`.

Integration, `tests/integration/test_products_run.py`:

- The three assertions on the engine prompt use `search_query(...)`'s text: for `kids sandals` (twice) and `mens sandal`.
- New: a fresh, error-free cached row whose `query` is `"kids sandals buy online"` is searched again; afterwards the row's `query` is the new text and its `titles` are the new result.
- New: a fresh, error-free cached row whose `query` is `search_query("kids sandals")` is a hit; the engine is not called.
- New: a run whose judge returns the titles "Zappos.com" (domain zappos.com) and "Kids Classic Sandal" (both present in the answer text) stores only "Kids Classic Sandal".
- Existing tests that seed a cached row to be a hit seed it with the new query.
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
| Grounded searches | 8 | 37,500 | 300,000 |
| Title parse calls | 8 | 1,500 | 12,000 |
| Keyword calls (3 samples, 1 batch) | 3 | 1,500 | 4,500 |
| Rewrite call | 1 | 1,500 | 1,500 |
| Total | | | 318,000 (about $0.32) |

  With 10 distinct keywords: 10 × 39,000 + 6,000 = 396,000 (about $0.40). Spend would go from $9.9377 to between about $10.26 and $10.34 of the $15 cap.
- Reported as observed: per keyword, how many stored titles are products and how many are stores; whether LC-01 and LC-02 still carry "Com"; the job's cost.
- The slice does not promise product titles for every keyword. If the new wording still returns stores, findings record the counts.

## Rulings

None yet. Rulings made during execution are added here with their R-number.

## Out of scope

- Locale in the query text, and enforcing the locale on results.
- Storing the grounded answer text.
- Seeding the run-wide key map from cached rows; `-es` plural folding; the side-by-side connectors case; `drop_brand_terms` comparing stems (all in findings-slice19 §3).
- Any schema, API or web change.
