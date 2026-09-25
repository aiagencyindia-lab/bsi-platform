# Findings: slice 18 — product-title wedge (F16)

## 1. What was built

**Tables (migration `0019_products.py`, `models.py`).** `product` holds one row per catalogue item: the catalogue columns (`external_id`, `title`, `description`, `attributes`, `url`, `price`, `category`, `source`, `imported_at`) and the latest result columns (`keyword`, `keywords`, `missing_keywords`, `suggested_title`, `suggested_bullets`, `rule_check`, `job_id`, `result_at`). Its constraints are `ck_product_source` (`csv`, `feed`), `ck_product_rule_check` (`pass`, `adjusted`) and `uq_product_brand_external`, with the index `ix_product_list (brand_id, title)`. `keyword_search` holds one row per (brand, keyword): the cached comparison set (`query`, `titles`, `model`, `cost_micros`, `searched_at`, `error`) under `uq_keyword_search_brand_keyword`. Both tables have `_protect()` (org index, ENABLE + FORCE RLS, the `tenant` policy and the `bsi_app` grants), are in `TENANT_TABLES` and are seeded in the `org_b` and isolation fixtures. `models.py` gains `PRODUCT_SOURCES` and `RULE_CHECKS`.

**`bsi_core/products.py`.** Parsing: `parse_csv` (case-insensitive headers, `attributes` cells, unknown columns as attributes, an empty title skipped and counted), `parse_feed` (RSS `<item>` and Atom `<entry>`, namespaces stripped, gzip inflated, a note of `malformed` when the root never closes, ruling R5) and `export_rows` (`|`-joined lists, formula cells neutralised, ruling R6). `upsert(s, org_id, brand_id, rows, source)` is one `INSERT … ON CONFLICT ON CONSTRAINT uq_product_brand_external` that rewrites only the catalogue columns, raises `CatalogueCap` above `MAX_PRODUCTS = 1_000` before any write, and keeps the last row when one batch repeats an `external_id`. Run steps, all pure: `vote`, `drop_brand_terms` (tokenless keywords dropped too), `missing`, `rule_check` (token-level, ruling R7), `keep_present` (domains lowercased, ruling R3), the schemas `KeywordSet`, `TitleSet`, `RewriteSet` and the prompts `keyword_prompt`, `titles_prompt` (the spec's `parse_titles_prompt`, ruling R8) and `rewrite_prompt`. The orchestration is `run_products(org_id, job_id, brand_id, params, generator, adapter, now=None)`: keywords per batch of 20 (three samples, voted), one grounded search per distinct rank-1 keyword (at most 100, fresh for 7 days, error rows re-searched, ruling R9), missing keywords, the rewrite call, the rule check, and a write per batch. The search phase checks the budget with this job's keyword spend included (ruling R10) and raises `OverBudget` when it does not fit.

**Job kinds (`worker.py`).** `product_run` (estimate `PRODUCT_JOB_MICROS = 20_000`) runs `run_products`; `import_feed` (estimate 0) runs `run_import_feed(org_id, brand_id, job_id, params, fetch=http_fetch, feed_fetch=None)`, which fetches the feed with `FEED_FETCH` (8 MiB cap) and no transaction open, parses it and upserts. `process_job` maps `OverBudget` to error `budget` and `CatalogueCap` to `cap`. A cut feed finishes `done`; its note is in the worker's summary line, not on the job (ruling R2).

**API routes (`routers/products.py`, prefix `/v1/brands/{brand_id}/products`).** `GET` (list), `GET /export.csv` (`Content-Disposition: attachment; filename="products-{brand_id}.csv"`), `GET /runs` (the last 20 `product_run` and `import_feed` jobs, plus `done` and `total`), `POST /import/csv` (raw `text/csv` body decoded as `utf-8-sig`; 413 above 4 MiB; 422 at the cap with nothing written), `POST /import/feed` (422 for a non-http(s) URL; queues `import_feed`), `POST /run` (422 with no products; queues `product_run` in the brand's first locale) and `DELETE` (removes the brand's `product` and `keyword_search` rows). `openapi.json` and `schema.d.ts` are regenerated. Every route has a `CASES` row in `test_isolation.py` except `POST /import/csv`, which has its own 404 test.

**Products tab (`app/(app)/b/[id]/products/`).** A tab link after Reports; `page.tsx` with the CSV form, the feed URL form, Run and Clear products, a run status line, a feed status line, the results table (Title, Keyword, Missing keywords, Suggested title, Check) and a "Download CSV" link. `actions.ts` has `importCsv`, `importFeed`, `runProducts` and `clearProducts`; an API 422 becomes the note `cap` on import and `empty` on run (ruling R1). `format.ts` has `PRODUCT_NOTES` and `productNote()`, with `nofile` and `cap` added (ruling R1). `next.config.ts` raises the Server Action body limit to `4mb`.

**Second Route Handler (`app/(app)/b/[id]/products/export.csv/route.ts`).** The web app now has two Route Handlers; this is the first authenticated one. `GET` returns a plain 404 `Not found` for a brand id that is not a UUID, without calling the API. A missing `bsi_key` cookie redirects to `/login` through Next's `redirect()`, which answers 307 (ruling R4). Otherwise it fetches the API export with `Authorization: Bearer`, `cache: "no-store"` and a 30 s timeout. An upstream 401 redirects to `/login`, an upstream 404 becomes a plain 404, and any other non-ok status or a thrown fetch becomes a plain 502 `Export unavailable`. On success it streams the body with `content-type`, `content-disposition` and `cache-control: no-store`. The comment in `app/r/[token]/pdf/route.ts` now names both handlers.

**Commits** (`git log --oneline main..HEAD`, oldest first, before this one):

| Commit | Subject |
|---|---|
| d1d8ff4 | docs: slice 18 spec, product-title wedge (F16) |
| 79d0b3b | docs: slice 18 implementation plan, product-title wedge |
| a686545 | feat(products): product and keyword_search tables (migration 0019) |
| 0f55f44 | feat(products): parse CSV and Merchant feeds; export rows |
| 78fb225 | feat(products): keyword vote, missing keywords, rule check and prompts |
| 6411ede | fix(products): drop tokenless keywords; rule check removes repeated tokens |
| f7747f7 | feat(api): products import, run, export and clear routes |
| f1a7960 | feat(worker): product_run and import_feed jobs |
| d89077f | fix(products): re-search error rows; count keyword spend in the budget |
| bc88442 | feat(web): Products tab with CSV and feed import, run and results |
| 66f328a | feat(web): same-origin products CSV download route |

## 2. Live check on dev

Not yet run. The controller runs it after the user approves migrating dev to 0019; results are recorded here then.

## 3. Deferred and untested

Out of scope (spec):
- Shopify OAuth ingest, and pushing titles to Shopify as drafts (PRD Phase 2).
- A licensed SERP provider for Google Shopping and organic results; the seam is `keyword_search`.
- Choosing a subset of products or a locale per run in the UI; the run covers all products in the brand's first locale.
- A history of past suggestions.
- Storing the feed URL on the brand for a scheduled refresh.
- The marketplace check (PRD Phase 2).

Decisions with a cost (rulings, spec `## Rulings`):
- A cut feed's note is not stored on the job (R2, R11). It is only in the worker's summary line, so the tab shows a truncated feed import as `done`. Cost: a partial import looks complete on the tab.
- The R6 apostrophe applies to every export cell, `external_id` and `url` included. An id such as `-123` exports as `'-123`, so an edited export re-imported creates a new product. Cost: a duplicate product on that path.
- A keyword whose search fails every time is searched again on every run (R9). Cost: one grounded call per run for that keyword.

Import and parsing:
- With duplicate CSV headers (e.g. `url` and `link`), an empty later cell overwrites the earlier value.
- In an Atom feed, `<id>` and `g:id` collide once namespaces are stripped; the first one wins.
- Feed rows without a title are dropped and not counted; the CSV parser counts them as skipped.
- The CSV body is decoded with `errors="replace"`, so a cp1252 file is garbled without a warning.
- The 4 MiB CSV cap is checked after the whole body is read; a real limit needs the ingress.
- `POST /import/feed` checks the URL scheme before the brand, so another org's brand with an `ftp://` URL gets 422, not 404. No data leaks, since the 422 does not depend on the brand.
- `run_import_feed`: the transport truncation note overwrites `parse_feed`'s note; a clean feed logs `note:None`; `feed_fetch` is never passed and `job_id` is unused; the choice of `FEED_FETCH` relies on `fetch is http_fetch`.
- No tests for the gzip-error and gzip-cap `truncated` branches of `parse_feed`, nor for `run_import_feed`'s truncation and note path.

The run and its pure steps:
- The run covers all products in the brand's first locale.
- `keep_present` matches titles as substrings, so a title that is a prefix of a longer one in the text is kept. It does not dedupe titles either, so one title repeated in the text can reach `MIN_TITLES = 2`.
- `STOPWORDS` is a short English list, and tokens are ASCII-only (`[a-z0-9]+`), so Devanagari or accented titles give no tokens.
- A multi-word brand is matched as a subset of tokens, not as a phrase.
- `vote` does not normalise case or whitespace; `run_products` cleans keywords before voting.
- `rule_check('Boys Sandal', '')` returns `('', 'pass')`; the run falls back to the original title.
- Under R7 a hyphenated word that partly repeats an earlier word is dropped whole (`Sandal Kids-Sandal` loses `Kids`), shown as `adjusted`.
- A product left out of the rewrite reply is stored with its original title, `rule_check = "pass"` and no bullets, which makes the badge misleading.
- The prompts quote values with `{x!r}`, the `titles_prompt` wording is awkward, and the rewrite prompt does not state the 200-character bullet cap (the cap is applied in code).
- The local `products` list in `run_products` shadows the module name.
- `keep_present`'s test does not check case-insensitivity.
- No test of a rewrite-phase failure in batch two keeping batch one's suggestions (the keyword-phase failure is tested).
- `test_product_kinds_are_known_and_estimated` checks the estimates only; dispatch is covered in `test_products_run.py`.

API tests:
- `GET /runs` is untested with `done > 0` or with an `import_feed` job; the idle-in-transaction probe covers import and export only.

Web:
- `is422` in the web actions keys on the `"422 "` message prefix that `api()` builds.
- `importFeed` has no 422 catch, so an `ftp://` URL (which `type="url"` accepts) lands on the error page. A CSV over 4 MB hits Next's body limit first and also gets no note.
- The file and URL inputs have no `aria-label`; the URL input has only a placeholder.
- The ` products in the catalogue.` suffix is not in `PRODUCT_CASES`.
- `Last run failed: ` with a null error leaves a trailing colon.
- `statusLine`, `feedLine` and `is422` have no tests.
- `formNoValidate` on Clear does nothing, and Clear deletes in one click with no confirmation (the spec accepts this).
- The page and its forms have not been rendered against a live API; only typecheck and build cover them until the live check.
- Export route tests: the upstream-404 test checks the status only, not the body or content type; the mocked `redirect` returns `undefined`, so a dropped `return` before `redirect()` would still pass; the 30 s `AbortSignal` also covers the streamed body, as in the PDF route.

Test output:
- Full-suite runs print two unnamed warnings (the same two seen since Task 1; slice 17 recorded two pre-existing starlette/anyio warnings).
- The isolation "Secret" rows are seeded in Task 1 and read by Task 4's `CASES`.
