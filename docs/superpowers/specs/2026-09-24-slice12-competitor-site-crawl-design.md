# Slice 12 design: competitor site crawl (PRD F07, the rest)

## Context

Slice 9 built competitor intelligence from AI answers only: metrics, deltas, and a visibility change feed. It deferred PRD F07's third line: "Weekly crawl of competitor domains for new pages (sitemap diff) and new structured data". It also left F07's acceptance only partly met, because feed entries have prompts and engines but no evidence URLs. The feed is computed on read and is empty for Run 1 (all 100 answers fall inside 4 days).

Decisions made in brainstorming (all approved in chat):

- **Surface** = an own "Competitor site changes" section on the Competitors tab (shown even when the feed is empty), **plus** each feed entry carries that rival's new pages and new @types from its after window as evidence.
- **Crawl size** = a bounded sample per domain per week:
  - robots.txt;
  - the sitemap, following an index to at most 10 child sitemaps;
  - the homepage plus up to 10 newly listed pages, read for JSON-LD @types.
  - That is about 20–25 fetches per domain. No model spend.
- **Storage** = one row per rival URL (first seen, last seen) plus one crawl row per domain per run. A domain's first run is a baseline and never shows as new. Removals are not reported.
- **Live check** = a read-only script on Run 1's five competitor domains (adidas.co.in, bata.com, campusshoes.com, crocs.in, skechers.in). It writes nothing to dev.

Codebase facts that shape the design:

- `crawl.http_fetch` truncates at 512 KiB and still returns 2xx. It has no flag for this.
- Sitemap indexes are not followed today, and `<loc>` is never parsed (`_root_tag` only reads the root element).
- Gzipped `.xml.gz` served without Content-Encoding comes back as raw bytes.
- `_owned_sitemap`, `robots_allows`, `_robots_lines`, `Head`, `_types` and `BROWSER_UA` in `crawl.py` are reusable.
- `claim_job` fails a job still running after 10 minutes as stale.
- `competitor.domains` is a TEXT[]. The competitor DELETE route is a hard delete, so new foreign keys need `ON DELETE CASCADE`.

Spend so far is $9.2863 of $15, and this slice adds no model spend. Planning happens on Fable 5.1 or Opus 5.5. Implementers and reviewers run on Opus 5.5 only, with the model parameter omitted.

## Design

### A. Crawl and storage

New pure module `packages/core/bsi_core/rivals.py`, with an injected `Fetch` like `crawl.audit_domain`.

**`snapshot_domain(host, fetch, known: set[str], *, pause) -> Snapshot`**

1. Fetch robots.txt. Keep its `Sitemap:` lines only when `crawl._owned_sitemap(host, url)` accepts them; otherwise fall back to `https://{host}/sitemap.xml`.
2. Read the sitemap:
   - Follow a `<sitemapindex>` to at most `MAX_CHILD_SITEMAPS = 10` children.
   - Parse `<loc>`/`<lastmod>` with `xml.etree` iterparse, namespace-agnostic.
   - Keep only URLs on this host or its subdomains (`matching.is_owned`).
3. Fetch the homepage plus up to `MAX_NEW_PAGES = 10` URLs that are not in `known`, newest `<lastmod>` first (no lastmod goes last, then by URL). Read each page's JSON-LD @types with `crawl.Head` + `crawl._types`.

**Politeness.** Every page and sitemap fetch obeys the `*` group of the domain's robots.txt (via the existing group helpers plus `robots_allows`). A disallowed URL is recorded as skipped and never fetched. Fetches pause `PAUSE_SECONDS` between them, and use `BROWSER_UA`.

**Incomplete snapshots.** `complete=False` when:
- a body reaches the 512 KiB cap;
- a child sitemap fails;
- the index lists more than 10 children;
- a body looks like gzip without Content-Encoding (magic bytes `\x1f\x8b`);
- the sitemap is missing or invalid.

**Snapshot fields:** `urls: dict[url, lastmod|None]`, `pages: list[{url, types, status}]`, `domain_types: {type: first_url}`, `complete`, `errors: list[str]`, `fetches`, `skipped: list[url]`.

**Migration 0015** adds two tenant tables, each with `_protect()` copied from 0012: org_id index, ENABLE + FORCE RLS, a tenant policy, and grants to `bsi_app`.

- **`rival_crawl`** (one row per (competitor, domain) per finished run):
  - Columns: `id, created_at, org_id, brand_id, competitor_id FK ON DELETE CASCADE, job_id, domain, complete bool, urls_seen int, new_urls int, fetches int, errors JSONB '[]', types JSONB '{}'` (the domain's @types → first URL, this run).
  - Index `(brand_id, competitor_id, domain, created_at)`.
- **`rival_page`** (one row per rival URL):
  - Columns: `id, created_at, org_id, brand_id, competitor_id FK ON DELETE CASCADE, domain, url, first_seen_at, last_seen_at, baseline bool, types TEXT[] NULL`.
  - Unique `(competitor_id, url)`, and an index on `(brand_id, competitor_id, first_seen_at)`.
- **`due_rival_crawls()`** is a SECURITY DEFINER function (search_path public; REVOKE from PUBLIC; GRANT to bsi_app). It returns `(brand_id, org_id)` for active brands with any active competitor having a declared domain whose latest `rival_crawl` is missing or older than 7 days. Never-crawled domains come first, then the oldest, then brand id.
- ORM models `RivalCrawl` and `RivalPage` go in `models.py`. Both tables are added to `TENANT_TABLES` and the `org_b` fixture.

**Upsert.**
- New URLs are inserted with `first_seen_at = last_seen_at = now()`, `baseline = (no earlier rival_crawl for this competitor+domain)`, and `types` from the sample.
- Known URLs get `last_seen_at = now()`, and their `types` are set when they were sampled this run.
- Writes go in chunks of `UPSERT_CHUNK = 2_000` rows, under the 65,535-bind-parameter limit.

### B. Job and schedule

- **Job kind `crawl_rivals`**, params `{}`, with `JOB_ESTIMATES["crawl_rivals"] = 0` (HTTP only). The runner `run_rival_crawl(org_id, brand_id, job_id, fetch)` lives in `apps/workers/bsi_workers/worker.py`, next to `run_crawl_audit`.
  1. **Session 1 (read, then closed).** Read the due (competitor, domain) pairs for the brand (active competitors only; no crawl in 7 days; oldest first) and the known URL set per competitor (`url` column only).
  2. **No transaction open.** Run `snapshot_domain` per domain. A crash is logged and stores nothing, so the domain stays due.
  3. **Session 2 (write).** Write the `rival_crawl` rows and the chunked `rival_page` upserts.
- **Time budget: `RIVAL_JOB_SECONDS = 420`.** A fetch wrapper refuses fetches after the deadline. A domain cut short is not stored and stays due for the next hourly pass. This stays under `claim_job`'s 10-minute stale cutoff.
- **Scheduling.** `queue_due_rival_crawls()` runs in `main()` next to `queue_due_crawl_audits()`, each in its own try/except, and uses `enqueue_job(..., "crawl_rivals", {}, requeue_failed=False)`.
- **Manual trigger:** `POST /v1/brands/{id}/competitors/crawl` → 202 `QueuedOut` via `queue_suggestion` (409 for an archived brand).
- **Edge cases:**
  - robots.txt disallows `/` → a `rival_crawl` row with `complete=false` and an error, and no pages.
  - Unreachable host → a row with the error.
  - Suggested competitors and competitors without domains are never crawled.

### C. Changes and feed evidence — `rivals.site_changes`, `competitors.visibility_changes`

**`rivals.site_changes(s, brand_id, days=14, to=None) -> dict`** is a fixed number of grouped statements. Its output:

- `window {from, to}`.
- `competitors`: one row per active competitor, ordered by `new_pages_total` desc, then name. Each row has:
  - `competitor_id`, `name`;
  - `new_pages_total`;
  - `new_pages`: `baseline=false`, `first_seen_at` in `[to−days, to)`, newest first, capped at 20, each `{url, first_seen_at, types}`;
  - `new_types`: @types in this window's `rival_crawl.types` for the competitor that appear in none of its earlier crawls (baseline crawls count as earlier), each `{type, url}`;
  - `crawls`: the latest crawl per declared domain, `{domain, crawled_at, complete, urls_seen, errors}`.

**Feed evidence.** Each `visibility_changes` entry gains `new_pages: list[str]` (capped at 20) and `new_types: list[str]`, limited to that competitor and to the entry's after window `[split, to)`. They come from **one** extra grouped statement for the whole feed. Update the slice-9 statement-count test to the new fixed count.

**Not treated as a change:** removed URLs, lastmod updates on known URLs, and the baseline run.

**No new recommendation type.** Turning site changes into actions needs topic matching; that is deferred.

### D. API and web

**Routes** (in `apps/api/bsi_api/routers/competitors.py`):
- `POST /brands/{id}/competitors/crawl` → 202.
- `GET /brands/{id}/competitors/site-changes?days=14` (1–90) → `SiteChangesOut`. It uses `window_end()`, which refuses `date_from`.

**Schemas:** `SiteChangesOut`, `RivalChangesOut`, `NewPageOut`, `NewTypeOut`, `RivalCrawlStatusOut`. `ChangeOut` gains `new_pages: list[str] = []` and `new_types: list[str] = []`.

**Isolation:** add `CASES` rows for both routes, plus owner-2xx tests. Then `npm run gen` and stage `openapi.json` and `schema.d.ts`.

**Web:** `apps/web/src/app/(app)/b/[id]/competitors/page.tsx` plus a new `actions.ts`.
- New section "Competitor site changes (last 14 days)":
  - a "Crawl competitor sites now" button (server action → `?queued=`) and `crawlNote` in `format.ts` with a vitest case;
  - one card per competitor:
    - a status line per domain (date · URL count · complete, or the error or "incomplete");
    - the new-page count, and up to 20 URLs (links only when http(s), with `rel="noreferrer"`) with @type tags;
    - "New structured data:" as tags linking to the first URL;
  - an empty-state message.
- Feed cards gain "New pages on their site: N" and "New structured data: …" lines when those are non-empty.
- Server Components only. No sorting or statistics in the frontend.

### E. Testing and live check

- **`tests/unit/test_rivals.py`** (fake fetch, no network):
  - urlset parsing, and an index with children;
  - children capped at 10 → incomplete; off-host `<loc>` dropped; a foreign `Sitemap:` line ignored;
  - 512 KiB cap → incomplete; gzip bytes → incomplete;
  - sampling: ≤ 10 unknown URLs, newest lastmod first; homepage always fetched;
  - robots-disallowed URLs skipped and never fetched; robots `Disallow: /` → no pages;
  - @types read, including `@graph`;
  - the deadline wrapper refuses fetches past the budget.
- **`tests/integration/test_rival_crawl.py`** (via `process_job` with a fake fetch):
  - the first run is a baseline with no new pages;
  - the second run turns added URLs into new pages, and a new @type into a new type;
  - a crash stores nothing and leaves the domain due; a budget-cut domain is not stored;
  - no transaction is open during fetches (`pg_stat_activity`);
  - `due_rival_crawls()`: due after 7 days; only active competitors with domains; archived brands excluded; idempotent within the hour;
  - deleting a competitor cascades to its rows;
  - chunked writes (lower the chunk size in the test).
- **`test_competitors.py`:** feed entries carry `new_pages`/`new_types` only for their competitor and after-window; update the statement count.
- **`test_api_competitors.py`:**
  - crawl route returns 202, and 409 on an archived brand;
  - site-changes shape, ordering, `days` validation, and `date_from` refusal.
- **RLS and isolation** for both tables and routes.
- **Web:** a `crawlNote` vitest case, then `npm run gate`.
- **Live check (no model spend; real HTTP):** `scripts/snapshot_rival.py <host>` runs `snapshot_domain` with `known=set()` and prints URL count, complete, errors, sampled page types and fetches. It writes nothing. Run it on the five Run 1 domains and record the results in `docs/findings-slice12.md`, plus a line in `docs/README.md`.

### Files

- **New:** `packages/core/bsi_core/rivals.py`, `migrations/versions/0015_rival_crawl.py`, `scripts/snapshot_rival.py`, `apps/web/src/app/(app)/b/[id]/competitors/actions.ts`, `tests/unit/test_rivals.py`, `tests/integration/test_rival_crawl.py`, `docs/findings-slice12.md`, and the spec and plan under `docs/superpowers/`.
- **Changed:** `models.py`, `competitors.py`, `worker.py`, `routers/competitors.py`, `schemas.py`, `competitors/page.tsx`, `lib/format.ts` (+test), `lib/types.ts`, the generated types, `test_rls.py`, `test_isolation.py`, `test_competitors.py`, `test_api_competitors.py`, `docs/README.md`.

### Out of scope, by decision

- recommendations from site changes;
- topic-matching rival pages to clusters;
- removed URLs and lastmod changes;
- storing or alerting on feed entries (F15);
- resolving Vertex redirect URLs;
- unzipping gzip sitemaps.

### Risks

- Bot protection (403 or challenge pages) on rival sitemaps is recorded as an error; the live check will show how common it is.
- A sampled index gives lower-bound counts whenever `complete=false`.
- Rival pages are fetched with a browser UA while obeying the `*` robots group.

