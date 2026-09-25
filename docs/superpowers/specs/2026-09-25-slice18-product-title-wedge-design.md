# Slice 18 design: product-title wedge (F16)

## Context

F16 (PRD §F16, flow §5.7) is a P0 and the reason the project started: the ADK demo's loop of finding a generic shopper keyword, searching for the titles that already rank for it, comparing them with the brand's own titles and rewriting the titles. Nothing of it exists in bsi-platform yet: no product table, no import, no rewrite. This slice ports the loop as a brand-scoped Products tab.

Classification: **architectural**. It is a new subsystem (product catalogue, import, batch run, rewrite), not a change to an existing flow. This was not said in chat before the first brainstorming question, as the process requires; it was first written in the plan file during brainstorming (found in the slice 18 audit, 2026-09-26).

Decisions approved in chat (brainstorming on Fable 5.1, 2026-09-25). Brainstorming had four design sections: 1 data model (§1 below), 2 import (§2), 3 the run (§3), and 4 API, web, export and tests (§4–§6). Sections 2–4 were shown in chat before each approval; section 1 was approved without its text being shown in chat first; after the slice 18 audit its text was shown in chat and the user approved it as built (2026-09-26). The live check (§7) was part of the plan approved in plan mode, not a separate design section:

- **Ingest:** CSV upload and Google Merchant feed URL. Shopify OAuth is deferred: it needs a partner app, client secrets, a callback Route Handler and token storage, a slice of its own.
- **Top-ranking titles:** the platform's grounded Gemini engine (`gemini-2.5-flash` with Google Search, prompt `"<keyword> buy online"`), parsed by flash-lite. This is what the ADK `search_results` agent does. A licensed SERP provider (Google Shopping and organic, as the PRD wants) can replace it later at the `keyword_search` seam without touching products or the run.
- **Export:** an API CSV endpoint plus a **second Route Handler** at `app/(app)/b/[id]/products/export.csv/route.ts`, approved by the user. It is the first authenticated Route Handler.
- **Spend:** one grounded search per distinct rank-1 keyword, not per product. The run cap is 1,000 products, the PRD's figure. The budget guard runs in the worker.
- **Data model, approach A:** the latest result lives on the product row; a `keyword_search` table caches the comparison set per keyword; runs are `job` rows. Rejected: a full history (`product_run` + `product_result`: two more RLS tables for a view the PRD never asks for) and emitting suggestions as recommendations (1,000 cards, impact windows that don't apply, no CSV).

Codebase facts the design rests on:

- `Job` (`models.py`) has `kind`, `status`, `params`, `error`, `cost_micros`, `started_at`; there is no CHECK on `kind`. The worker's `JOB_ESTIMATES` dict (`worker.py`) is the list of kinds; `process_job` claims a job through `claim_job()`, checks `budget_fits(s, org_id, 0, extra_micros=estimate)` in a short tenant session, wraps the adapter and generator in `_Meter`, calls the runner with no transaction open, and `_finish_job` adds the metered micros. Runners raise `JudgeFailed(e, spent)` so money spent before a failure is recorded. The API never checks the budget; `runs.queue_suggestion` just queues.
- `judge.generate(prompt, schema, temperature)` calls `extract_model` (`gemini-3.5-flash-lite`) with a JSON response schema and returns `(json_text, cost_micros, model)`. `suggest.py` injects it as `Generator = Callable[[str, type[BaseModel], float], tuple[str, int, str]]`, so tests never spend.
- `GeminiGroundingAdapter.query(prompt, country, language)` returns an `EngineResult` (`kind`, `raw`, `cost_micros`, `model`); `providers.gemini.parse(raw)` gives `ParsedAnswer(text, citations=[(url, domain)])`. Grounding metadata carries source domains, not product titles: the titles must come from the answer text.
- `crawl.http_fetch(url, ua, *, cap, raw)` never raises, has a 30 s deadline, and `rivals.parse_sitemap` streams XML with `XMLPullParser`, strips namespaces with `tag.rsplit("}", 1)[-1]`, and inflates gzip under the cap. `SITEMAP_FETCH = partial(http_fetch, cap=..., raw=True)`.
- Migration template: `0017_reports.py` copies `_protect(table)` (index, ENABLE + FORCE RLS, policy `tenant`, grant to `bsi_app`) and `_row_columns()` (`id`, `created_at`, `org_id`, `brand_id`). Names: `ck_{table}_{column}`, `uq_{table}_{cols}`, `ix_{table}_{purpose}`. Models are `class X(Tenant, Base)`; there is no `updated_at`.
- `tests/integration/test_rls.py` fails unless every table with `org_id` is in `TENANT_TABLES` and seeded by `org_b`. `tests/integration/test_isolation.py` replays every `CASES` row against org B's "Secret" rows and requires a 404 with no "Secret" in the body.
- Web: a brand tab is `page.tsx` (Server Component, `api<T>()` calls in `Promise.all`) plus `actions.ts` (`"use server"`, `redirect(\`…?queued=<status>\`)`) plus a `*Note()` helper built on the private `note()` in `lib/format.ts`. Tabs are hard-coded `<Link>`s in `b/[id]/layout.tsx`. No file upload exists; `next.config.ts` is empty, so Server Actions have the default 1 MB body limit. `app/r/[token]/pdf/route.ts` and its test are the Route Handler template. `api()` never returns the raw `Response`.
- `FORBIDDEN` in `tests/unit/test_recommend_copy.py`: guarantee, will rank, will appear, will be recommended, ensure, boost, #1, top spot, dominat, certain. The ban applies to our fixed wording only; stored text is exempt (slice 15 and 16 rulings).

## Design

### 1. Data model (migration 0019, `models.py`)

`product` — one row per catalogue item.

| Column | Type | Notes |
|---|---|---|
| `brand_id` | uuid FK brand | |
| `external_id` | text | the feed's `g:id`, the CSV's `id` column, else the URL, else `sha1(title)` |
| `title` | text | required |
| `description` | text, null | |
| `attributes` | JSONB dict | `{"color": "blue", "size": "10"}`, keys lowercased |
| `url` | text, null | |
| `price` | text, null | kept as given, e.g. `1299.00 INR` |
| `category` | text, null | |
| `source` | text | `csv` or `feed`; `ck_product_source` |
| `imported_at` | timestamptz | `now()` on every upsert |
| `keyword` | text, null | the voted rank-1 generic keyword |
| `keywords` | text[], null | the ranked keywords after dropping brand terms |
| `missing_keywords` | text[], null | |
| `suggested_title` | text, null | |
| `suggested_bullets` | text[], null | |
| `rule_check` | text, null | `pass` or `adjusted`; `ck_product_rule_check` |
| `job_id` | uuid FK job, null | the run that wrote the result columns |
| `result_at` | timestamptz, null | |

`uq_product_brand_external (brand_id, external_id)`; `ix_product_list (brand_id, title)`. `MAX_PRODUCTS = 1_000` per brand is enforced in code, not the DB. Where the same `external_id` appears twice in one import batch, the last row wins (`upsert` collapses the batch by id before the insert, since Postgres rejects an `ON CONFLICT` that touches one row twice).

`keyword_search` — one row per (brand, keyword): the cached comparison set and the SERP seam.

| Column | Type | Notes |
|---|---|---|
| `brand_id` | uuid FK brand | |
| `keyword` | text | |
| `query` | text | the string sent to the engine |
| `titles` | JSONB list | `[{"title": …, "domain": …}]`, at most `TOP_TITLES = 5` |
| `model` | text | |
| `cost_micros` | int | engine plus parse |
| `searched_at` | timestamptz | |
| `error` | text, null | a failed search is stored so the run proceeds |

`uq_keyword_search_brand_keyword (brand_id, keyword)`. A row younger than `SEARCH_TTL_DAYS = 7` with no error is reused; an older one, or one that stored an error, is re-searched and overwritten (R9).

Both tables get `_protect()`, an entry in `TENANT_TABLES` and rows in the `org_b` fixture. No brand columns and no `due_*()` function: nothing is scheduled in this slice. `models.py` gains `PRODUCT_SOURCES = ("csv", "feed")` and `RULE_CHECKS = ("pass", "adjusted")`, used by both the CHECKs and the migration (copied, as 0017 does).

Jobs: kind `product_run`, `params = {"locale": {"country", "language"}, "product_count"}`; kind `import_feed`, `params = {"url"}`. Both are added to `JOB_ESTIMATES` and `runners`.

### 2. Import (`bsi_core/products.py`, `routers/products.py`, worker)

**CSV** is synchronous: no network, so it runs inside the request.

- `POST /v1/brands/{id}/products/import/csv`. The body is raw `text/csv`, taken as a `bytes` parameter (`Body(media_type="text/csv")`) and decoded as `utf-8-sig`, so a leading BOM is ignored; no multipart dependency. `CSV_MAX_BYTES = 4 MiB`; a larger body is 413.
- `parse_csv(text) -> (rows, skipped)` uses `csv.DictReader`. Header names are matched case-insensitively after stripping. `title` is required; `id`, `description`, `attributes`, `url` or `link`, `price`, `category` are optional; every other column becomes an `attributes` entry keyed by the lowercased header. An `attributes` cell is split on `;` then `:` (`Size: 10; Color: Blue` → `{"size": "10", "color": "blue"}`); a fragment without `:` is dropped. A row with an empty title is skipped and counted. `external_id` falls back as in §1.
- `upsert(s, org_id, brand_id, rows, source) -> (created, updated)` is one `INSERT … ON CONFLICT (brand_id, external_id) DO UPDATE` on the catalogue columns and `imported_at` only; the result columns are kept, so a re-import never wipes suggestions. Before writing it counts existing products plus new external ids; above `MAX_PRODUCTS` it raises `CatalogueCap`, and the route answers 422 `"Catalogue cap is 1,000 products"` with nothing written.
- Response `ImportOut {created, updated, skipped, total}`.
- Web: a form with `<input type="file" name="csv" accept=".csv,text/csv" required>`; the `importCsv` server action reads `form.get("csv")` as a `File` and sends `await file.text()` as the body with `Content-Type: text/csv`. `next.config.ts` gains `experimental: { serverActions: { bodySizeLimit: "4mb" } }`. Redirect to `?queued=imported&n=<total>`.

**Google Merchant feed** is a network fetch, so it is a job, like `audit_crawl`.

- `POST /v1/brands/{id}/products/import/feed` with `FeedIn {url}`; the URL must start with `http://` or `https://` (422 otherwise). Queues `import_feed` with `slot=now()` through `queue_suggestion` and returns `QueuedOut`.
- Worker `run_import_feed(org_id, brand_id, job_id, params, fetch=http_fetch, feed_fetch=None)`. It fetches with `FEED_FETCH = partial(http_fetch, cap=FEED_CAP_BYTES, raw=True)`, `FEED_CAP_BYTES = 8 MiB`, when `fetch` is the default `http_fetch` (a test passes its own `fetch`). A fetch that is not `ok` raises `RuntimeError(f"fetch {status}: {error}")`, so the job fails with `error = repr(e)[:2000]`, e.g. `RuntimeError('fetch 404: …')`.
- `parse_feed(body: bytes) -> (rows, truncated_note)` streams with `XMLPullParser`, strips namespaces, inflates gzip under the cap, and reads RSS `<item>` and Atom `<entry>`: `g:id` → `external_id`, `title`, `description`, `link` → `url`, `g:price`, `g:product_type` else `g:google_product_category` → `category`, and `g:brand`, `g:color`, `g:size`, `g:material`, `g:gender`, `g:age_group`, `g:condition` into `attributes`. Malformed or truncated XML yields what was read before the fault, with a note: `malformed` when the parser raises or the root element never closes (R5), `truncated` when gzip inflation hits `FEED_CAP_BYTES`, `gzip error` when the gzip stream is corrupt. A body cut by the fetch cap is marked `truncated` by `run_import_feed` (from `Response.truncated`), not by `parse_feed`.
- Then one tenant session runs the same `upsert`; `CatalogueCap` fails the job with `error = "cap"`. A truncated or cut feed imports what was read and the job finishes `done`. Its note goes in the worker's summary line (`created:… updated:… note:…`), not in `job.error`, which stays NULL on every successful job (R2). The tab therefore shows such an import as `done` (R11).

### 3. The run (`bsi_core/products.py` pure functions, worker `run_products`)

`POST /v1/brands/{id}/products/run` queues one `product_run` job over all the brand's products, 422 `"No products to run"` if there are none, `slot=now()` so every request is its own job. Locale = the brand's first locale by `created_at`. `JOB_ESTIMATES["product_run"] = PRODUCT_JOB_MICROS = 20_000` covers the keyword phase; the runner re-checks the budget before each batch's grounded searches.

The runner reads the brand and its products ordered by `result_at NULLS FIRST, title, id`, so products never run, or run longest ago, go first, and then runs steps 1 to 6 for one batch of `BATCH = 20` products before it starts the next (R12). It reads and writes in short tenant sessions, with no transaction open during any model call. Before every batch after the first, if more than `PRODUCT_JOB_SECONDS = 480` seconds have passed since the run started, it stops: the job finishes `done`, its summary line reads `out of time after {done} of {total} products`, and the next run continues with the oldest results. The time budget keeps a run under `claim_job()`'s 10-minute stale cutoff, as `RIVAL_JOB_SECONDS` does for the rival crawl. `run_products(org_id, job_id, brand_id, params, generator, adapter, now, clock=time.monotonic)` is the orchestration; `clock` is injectable for tests; every step below it is a pure function.

1. **Keywords.** One flash-lite call per batch at `KEYWORD_TEMPERATURE = 0.4`, `SAMPLES = 3` times. The prompt is the ADK keyword prompt ported to JSON: per product, up to `MAX_KEYWORDS = 5` keywords shoppers would type to find it, lowercase, generic first (rank 1 is the shortest phrase naming the audience plus the category, e.g. `kids shoes`), one keyword per entry. Schema `KeywordSet {products: [{index, keywords: [str]}]}`. `vote(samples) -> list[str]` per product: rank 1 is the keyword most often at rank 1 across the samples, ties broken by sample order; the rest is the union in first-seen order, capped at 5. `drop_brand_terms(keywords, brand_names)` removes any keyword whose tokens include a token of the brand name or an alias, and any keyword with no tokens at all (e.g. `""` or `"!!!"`), so a tokenless keyword can never become rank 1. If nothing survives the product gets `keyword = NULL`, `keywords = []` and is skipped by the later steps; the same write sets `missing_keywords`, `suggested_title`, `suggested_bullets` and `rule_check` to NULL, `job_id` to this job and `result_at` to now, so a product never shows an earlier run's suggestion without a keyword (R13). `keyword` and `keywords` are written for the whole batch before its searches.
2. **Search.** Per batch: the batch's distinct rank-1 keywords that this run has not already looked up, ordered by product count then keyword. The run keeps the comparison sets it has looked up (`titles_by_kw`) across batches, so a keyword is looked up once per run. Keywords with a `keyword_search` row younger than 7 days and with `error IS NULL` are reused; a row that stored an error is searched again and overwritten (R9). The run searches at most `KEYWORD_CAP = 100` new keywords; once it has, later keywords get no search, and their products get `missing_keywords = []` and still get a rewrite. In the same short tenant session that reads the cache, `budget_fits(s, org_id, 0, extra_micros=spent + n_new * SEARCH_MICROS)`, where `spent` is this job's spend so far (R10: `job.cost_micros` is only written when the job finishes, so without it the check would not see that spend) with `SEARCH_MICROS = 45_000` (35,000 grounding plus tokens plus the parse call); if it fails the job finishes `failed` with `error = "budget"`, and the batches already written and this batch's keywords stay. For each new keyword: `adapter.query(f"{keyword} buy online", country, language)`; if `kind != "ok"` the row stores `error` and `titles = []`. Otherwise `titles_prompt(keyword, text, domains)` (R8) goes to flash-lite at temperature 0 with schema `TitleSet {titles: [{title, domain}]}`, asking only for product titles that appear verbatim in the text, at most 5, with the seller's domain when the text names it. `keep_present(titles, text)` drops any title not found in the text (case-insensitive, whitespace-collapsed). The row is upserted with `searched_at = now`.
3. **Missing keywords.** `missing(product_title, titles, brand_names) -> list[str]`: tokens of the top titles (lowercase, letters and digits only, at least 3 characters, not in `STOPWORDS`, not a pure number, not a brand token) that appear in at least `MIN_TITLES = 2` of the titles and not in the product's title. Ordered by the number of titles containing them, then alphabetically; capped at `MAX_MISSING = 8`. No model call.
4. **Rewrite.** One flash-lite call per batch at temperature 0 with schema `RewriteSet {products: [{index, title, bullets: [str]}]}`. For each product it gets the title, brand name, `keyword`, `missing_keywords`, description and attributes, and is asked for a title of at most 150 characters that keeps the brand name where the original had it, works the keyword and the missing terms in naturally, repeats no word, and three short description bullets. Products with `keyword = NULL` are excluded from the call.
5. **Rule check.** `rule_check(original, suggestion, brand_names) -> (title, status)` fixes deterministically instead of retrying, at the token level (R7): it first prepends the brand name if the original contained it and the suggestion lost it; then it walks the words left to right and drops any word that shares a token (case-insensitive) with an earlier kept word, keeping the original spelling of the kept words, so `Kids-Sandal Sandal` and `Red Tape Tape Shoes` both lose the repeat; a punctuation-only word has no tokens and is always kept; finally it trims to `MAX_TITLE_CHARS = 150` at the last word boundary. `status = "pass"` when nothing changed, else `"adjusted"`. Every stored suggestion therefore satisfies the PRD's rule check (no duplicate tokens, brand preserved, length) by construction; the badge shows when the model needed help. Bullets are capped at 3 and each at 200 characters.
6. **Write.** `suggested_title`, `suggested_bullets`, `missing_keywords`, `rule_check`, `job_id`, `result_at` per batch.

A model failure raises `JudgeFailed`; the job fails with its cost recorded and the batches already written stay, suggestions included (partial results). For 1,000 products: 50 batches × 3 samples + 50 rewrite calls = 200 flash-lite calls, plus at most 100 grounded and 100 parse calls, about $3.6. That takes about 20 to 30 minutes, so a run stops at `PRODUCT_JOB_SECONDS` and a large catalogue finishes over several runs (R12), each continuing with the oldest results; the PRD's 45 minutes is the whole catalogue's budget.

### 4. API (`routers/products.py`, prefix `/brands/{brand_id}/products`)

Literal routes are declared first. All take `c: Ctx = TENANT` and call `brand_or_404`.

| Route | Response | Notes |
|---|---|---|
| `GET /` | `list[ProductOut]` | order `title, id`; `limit` 1..1000, default 1000 |
| `GET /export.csv` | `text/csv` | `Content-Disposition: attachment; filename="products-{brand_id}.csv"`. Columns `external_id, url, title, keyword, missing_keywords, suggested_title, suggested_bullets, rule_check`; the list columns are `|`-joined. `export_rows(products)` builds the rows; the route writes them with `csv.writer` into a `StringIO`. Any cell that starts with `=`, `+`, `-`, `@`, a tab or a CR gets a leading `'` so a spreadsheet does not run it as a formula (R6); a list is joined before the check. |
| `GET /runs` | `ProductRunsOut {jobs: [ProductJobOut], done, total}` | the last 20 jobs of kinds `product_run` and `import_feed` (`id, kind, status, error, cost_micros, created_at, started_at`); `done` = products whose `job_id` is the latest `product_run`'s id, `total` = all products |
| `POST /import/csv` | `ImportOut`, 201 | §2 |
| `POST /import/feed` | `QueuedOut`, 202 | §2 |
| `POST /run` | `QueuedOut`, 202 | §3 |
| `DELETE /` | 204 | deletes the brand's `product` and `keyword_search` rows |

`ProductOut` has every column of §1 plus `id` and `created_at`. Every id-taking route gets a `CASES` row in `test_isolation.py`; the `other` fixture seeds `Product(title="Secret", external_id="secret-1")` and `KeywordSearch(keyword="secret")`.

### 5. Web (`app/(app)/b/[id]/products/`)

- `layout.tsx` gains the `Products` tab link after Reports.
- `page.tsx` fetches the brand, `GET /products` and `GET /products/runs` in parallel. Top: the CSV form, the feed URL form (`<input type="url" name="url" required>`), the Run button and the Clear button (`confirm` is not available in a Server Component form, so Clear is a plain button labelled "Clear products"). A status line from the latest job: `Run in progress: {done} of {total} products` while `running`, `Last run: done` / `Last run failed: {error}` otherwise; `Feed import: {status}` for the latest `import_feed`, with ` ({error})` appended only when that job failed; a truncated feed finishes `done` with no error (R2), so it reads `Feed import: done` (R11). Then the table: Title, Keyword, Missing keywords, Suggested title, Check (a `tag` span with `pass` or `adjusted`), or `No products yet.` when empty. A "Download CSV" link to `/b/{id}/products/export.csv` when there are products. Titles and URLs are rendered as text; the URL becomes a link only when it is http(s), through the existing rule.
- `actions.ts`: `importCsv`, `importFeed`, `runProducts`, `clearProducts`; each redirects to `/b/{id}/products?queued=<status>`. `importCsv` also appends `&n=<total>`.
- `format.ts`: `PRODUCT_NOTES` and `productNote(status)`: `imported` → "Imported.", `queued`/`running` → "Queued; the worker runs it within a minute.", `done` → "Done.", `failed` → "Failed; see the status line.", `cleared` → "Products cleared.", `empty` → "No products to run.", and (R1) `nofile` → "Choose a CSV file first.", `cap` → "Catalogue cap is 1,000 products; nothing was imported.". `importCsv` redirects with `nofile` when no file was chosen and maps an API 422 to `cap`; `runProducts` maps an API 422 to `empty`. The page appends `n` to the imported note as ` {n} products in the catalogue.`
- `export.csv/route.ts`, the second Route Handler: validates the brand id as a UUID first (404 otherwise, without reading the cookie), then reads the `bsi_key` cookie (a redirect to `/login` through Next's `redirect()`, which answers 307, when missing; R4), fetches `${API_URL}/v1/brands/{id}/products/export.csv` with `Authorization: Bearer`, `cache: "no-store"` and `AbortSignal.timeout(30_000)`; copies `content-type` and `content-disposition`, adds `cache-control: no-store`, streams the body with status 200. Upstream 401 → the same 307 redirect to `/login`; 404 → 404 "Not found"; any other non-ok or a thrown fetch → 502 "Export unavailable".
- `types.ts`: `Product = S["ProductOut"]`, `ProductRuns = S["ProductRunsOut"]`. Run `npm run gen` after the API lands and commit `openapi.json` and `schema.d.ts`.

### 6. Testing

Unit, `tests/unit/test_products.py`:

- `parse_csv`: header aliases (`Title`, `LINK`, `Id`) map; an `attributes` cell `Size: 10; Color: Blue` becomes `{"size": "10", "color": "blue"}`; an unknown column `material` becomes an attribute; a row with an empty title is skipped and counted; `external_id` falls back to `id`, then `url`, then `sha1(title)`.
- `parse_feed`: an RSS feed with two items gives two rows with `g:id`, `link`, `g:price`, `g:product_type` and `g:color` mapped; an Atom feed with one entry gives one row; a gzip-compressed feed parses; a feed cut mid-item yields the complete items and a note.
- `vote`: samples `[["kids shoes", "running shoes"], ["kids shoes"], ["running shoes", "kids shoes"]]` give rank 1 `kids shoes`; a three-way tie gives the first sample's rank 1; the union keeps first-seen order and is capped at 5.
- `drop_brand_terms`: with brand names `("Walkaroo", "WKR")`, `["walkaroo sandals", "kids sandals"]` becomes `["kids sandals"]`; an empty result is allowed; tokenless keywords are dropped (`["", "!!!", "kids shoes"]` becomes `["kids shoes"]`).
- `missing`: with the product title `Walkaroo Boys Sandal Blue` and titles `[Kids Sandals for Boys Summer Sandal, Boys Summer Sandals Lightweight, Summer Sandals Kids]`, the result is `["sandals", "summer", "kids"]`: tokens are compared exactly, so `sandal` in the product title does not cover `sandals`; `sandals` and `summer` appear in 3 titles and `kids` in 2, and `boys` is already in the title. Brand tokens and stopwords never appear; the cap is 8.
- `rule_check`: `Walkaroo Kids Shoes Shoes` → `Walkaroo Kids Shoes`, `adjusted`; original `Walkaroo Boys Sandal` with suggestion `Boys Summer Sandal` → `Walkaroo Boys Summer Sandal`, `adjusted`; a 160-character suggestion is trimmed at a word boundary to at most 150, `adjusted`; an unchanged suggestion is `pass`. Under R7: `Walkaroo Kids-Sandal Sandal` → `Walkaroo Kids-Sandal`, `adjusted`; original `Red Tape Boots` with suggestion `Tape Shoes` and brand `Red Tape` → `Red Tape Shoes`, `adjusted`; `Walkaroo - Sandal | Kids` stays unchanged, `pass` (punctuation-only words are kept).
- `keep_present`: a title absent from the text is dropped; matching ignores case and repeated whitespace.
- `export_rows`: lists are `|`-joined; `None` becomes an empty string.

Copy: `PRODUCT_CASES` in `tests/unit/test_recommend_copy.py` holds every string of `PRODUCT_NOTES`, the badge labels and the empty-state and status-line wording; the banned-word test runs over it. Test fixtures avoid the banned words.

Integration, `tests/integration/test_api_products.py`: a CSV import round trip (`created`, then `updated` on re-import with the result columns untouched); the cap returns 422 and writes nothing; a 5 MiB body is 413; the feed route queues an `import_feed` job and rejects `ftp://`; `POST /run` is 422 with no products and 202 with one; the export has the header row and `|`-joined lists; `DELETE` empties both tables; every request records nothing in `pg_stat_activity` as idle in transaction.

Integration, `tests/integration/test_products_run.py`, with a fake generator and adapter (never the network): keywords are written per batch (21 products → two keyword writes); two products sharing a keyword cause one search; a `keyword_search` row 6 days old is reused and one 8 days old is re-searched; a failing `budget_fits` finishes the job `failed` with `error = "budget"` and keeps the keywords; a suggestion with a repeated token is stored `adjusted`; a `JudgeFailed` in the second batch leaves the first batch's results, suggestions included, and fails the job with the cost recorded; the adapter and generator never see an open transaction (the `pg_stat_activity` probe). Under R12 and R13: a run whose clock passes `PRODUCT_JOB_SECONDS` after the first batch writes 20 of 41 products and returns `out of time after 20 of 41 products`; a second run starts with the products that have no result; a product whose keywords are all brand terms loses its earlier suggestion. `test_worker.py`: `process_job` dispatches `product_run` and `import_feed`.

`test_rls.py` and `test_isolation.py`: both tables and every route as in §1 and §4.

Web: `format.test.ts` covers `productNote` for every status and `undefined`; `export.csv/route.test.ts` covers the missing cookie, a bad id, a 200 with copied headers, a 404 and a 502, modelled on `pdf/route.test.ts`.

### 7. Live check

After the user's OK to migrate dev to 0019: import about ten products by CSV for `BSOAgentTestBrand`, `POST /run`, run one job through the documented single-job path (never `worker.main()` or `tick()`), then view the tab on a production build and download the CSV. Expected spend about $0.15 (a few keywords). Every API-key request writes `api_key.last_used_at`; the run writes `product`, `keyword_search` and `job`. Record the observed spend and the writes in findings.

## Rulings

Made during execution (the controller's ledger). Each gives what was decided, why, and the cost if it is wrong.

- **R1.** The web notes gain `nofile` and `cap`, and the actions map an API 422 to `cap` (import) or `empty` (run). Why: the spec's note list had no path for a missing file or the cap, so the user would have seen the error page. Cost if wrong: two extra note strings.
- **R2.** A cut or truncated feed's note goes into the job's summary (the worker log), not `job.error`. Why: §2 said `done` with `error = "truncated"`, but `_finish_job(..., "done", None, ...)` writes `error = NULL` on every success, and changing that touches every job kind. Cost if wrong: the tab cannot show "truncated"; a later slice can add a result column.
- **R3.** `keep_present` lowercases domains. Why: the spec was silent, and `normalize_domain` gives lowercase hosts. Cost if wrong: none visible.
- **R4.** The export route redirects with Next's `redirect()` (307), not the literal 302 §5 named. Why: the app's other auth redirects use `redirect()`. Cost if wrong: a status code in one test.
- **R5.** `parse_feed` tracks whether the root element closed (as `parse_sitemap` does) and sets the note `malformed` when it did not. Why: `XMLPullParser.feed` never raises on incomplete input, so the plan's code returned no note for a cut feed and failed its own test. Cost if wrong: none; the spec requires the note.
- **R6.** `export_rows` neutralises CSV formula injection: a cell starting with `=`, `+`, `-`, `@`, a tab or a CR gets a leading apostrophe (OWASP). Why: suggested titles come from a model fed competitor titles, and the file is opened in Excel. Cost if wrong: a legitimate title starting with `-` shows a leading `'` in the CSV. (It also applies to `external_id` and `url`; see findings §3.)
- **R7.** `rule_check` guarantees no duplicate *tokens* (the PRD acceptance criterion; §3 step 5): prepend the brand first (when the original had it and the suggestion lost it), then walk the words and drop any word that shares a token with an earlier kept word; punctuation-only words stay. Why: the plan's word-level dedupe let `Kids-Sandal Sandal` and `Red Tape Tape Shoes` through. Cost if wrong: a hyphenated word that partly overlaps an earlier one is dropped whole (`Sandal Kids-Sandal` loses `Kids`), shown as `adjusted`.
- **R8.** The titles-parse prompt is `titles_prompt(keyword, text, domains)`, as the plan and code have it; §3 step 2's `parse_titles_prompt(text)` is updated to match. Why: the name and inputs in the code are the ones built and tested. Cost if wrong: none.
- **R9.** The `keyword_search` freshness filter reuses only rows with `error IS NULL`; an error row is searched again on the next run. Why: §3's cache is for comparison sets and a stored error is not one; a 429 would otherwise blank a keyword for a week. Cost if wrong: a keyword that fails every time spends one grounded call per run.
- **R10.** The search-phase budget check passes `extra_micros = spent + len(new) * SEARCH_MICROS`. Why: `job.cost_micros` is written only at `_finish_job`, so the keyword phase's spend was invisible to `budget_fits` and a 1,000-product run could pass the cap. Cost if wrong: an org near its cap gets `budget` slightly earlier.
- **R11.** `feedLine` stays as built: it shows an error only on a failed job. Why: under R2 a truncated feed finishes `done` with `error = NULL`, so there is no error on a done job to show, and widening the condition would be dead code; §2's "so the tab can show it" is replaced by R2. Cost if wrong: a partial feed import looks complete on the tab (already accepted by R2).
- **R12.** `run_products` works one batch at a time (keywords, searches, rewrite, write) over products ordered by `result_at NULLS FIRST, title, id`, and starts no batch after `PRODUCT_JOB_SECONDS = 480` (an injectable `clock`); the summary then reads `out of time after {done} of {total} products` and the job finishes `done`. The budget check and `KEYWORD_CAP` move into the batch loop, counted across the run. Why: a 1,000-product run takes about 20 to 30 minutes, which outlives `claim_job()`'s 10-minute stale cutoff (the stale reset would hand the job back to the queue while it runs) and blocks the worker loop; `RIVAL_JOB_SECONDS` set the precedent. Cost if wrong: a large catalogue needs several Run clicks to finish, and results within one catalogue can come from different runs. (The tab shows an out-of-time run as `Last run: done`; see findings §3.)
- **R13.** When a product's keyword becomes NULL, the same write clears `missing_keywords`, `suggested_title`, `suggested_bullets` and `rule_check` and sets `job_id` and `result_at`. Why: otherwise the product would keep an earlier run's suggestion with no keyword beside it, and under R12's ordering it would be picked first on every run. Cost if wrong: none.

## Out of scope

- Shopify OAuth ingest and pushing titles to Shopify as drafts (PRD Phase 2).
- A licensed SERP provider for Google Shopping and organic results; the seam is `keyword_search`.
- Choosing a subset of products or a locale per run in the UI; a run works through all products in the brand's first locale, oldest results first, until its time budget (R12).
- A history of past suggestions.
- Storing the feed URL on the brand for a scheduled refresh.
- The marketplace check (PRD Phase 2).
