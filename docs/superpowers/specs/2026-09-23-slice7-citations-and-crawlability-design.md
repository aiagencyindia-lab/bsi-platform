# Slice 7 design: citation intelligence and the crawlability audit

## Context

Slices 1–6 measure a brand in AI answers and turn the evidence into
recommendations. Two PRD audits can be built without a paid provider or
a model call, and the user chose them for the first audits slice:

- **Citation intelligence (F06).** Run 1 already holds 1,104 citations
  over 247 domains, but the only view is per answer, and the only use
  is the `pursue_citation_source` rule. The PR manager's question —
  which sites the engine cites for my category, and which of them
  never lead to me — has no page. Decision: **stored data only**, no
  fetching of cited pages (their URLs are Vertex redirects; no title is
  kept).
- **Crawlability audit (F10).** Nothing examines the brand's own site.
  Decisions: **homepage plus site files** per brand domain (no page
  crawl, no Playwright); **on demand and weekly**; **one
  `fix_crawlability` recommendation per failing check**, accepted
  tasks do not measure impact.

Nothing here spends money: citations are SQL over existing rows, and
the audit is a handful of HTTP fetches with no model.

## Design

### A. Citation intelligence — read-only SQL, one endpoint, one page

No new table. One query in `bsi_core/citations.py`, `sources(s,
brand_id, f: Filters)`, grouped by `citation.domain` over the brand's
done observations, using `metrics._where` for the base and the filters
so the page agrees with the Citation-rate tile beside it. (It differs
from `recommend._citations`, which also requires active prompts: a
retired prompt's citations still belong in the audit.) Per domain:

| Field | Meaning |
|---|---|
| `domain`, `owner` | `brand` if `is_brand_owned`; `rival` if `is_owned(domain, competitor.domains)`; else `third_party` |
| `source_type` | heuristic from the domain, labelled as such: `video` (youtube, vimeo), `community` (reddit, quora, stackexchange), `review` (host contains "review", g2, capterra, trustpilot, mouthshut), `vendor` (brand- or rival-owned), else `other`. One dict in `citations.py`. |
| `answers`, `prompts` | distinct citing observations / prompts |
| `first_seen`, `last_seen` | min/max `observation.requested_at` |
| `brand_named` | citing answers that mention the brand |
| `rivals` | `[{name, answers}]` of active competitors named in citing answers, most first (same shape as `_rivals`) |
| `gap` | `brand_named == 0 and len(rivals) >= 2` — PRD F06's definition |
| `observation_ids` | for evidence links (capped at 20, most recent) |

Sorted by `answers` desc, then domain. `Filters` gets no new fields.

**API.** `GET /v1/brands/{id}/citations` → `list[SourceOut]` in
`schemas.py`, router `routers/citations.py`, accepts the same
`locale_id`/date query params as `/metrics`. Foreign brand → 404 via
`brand_or_404`. No writes.

**Web.** New tab **Citations** at `b/[id]/citations/page.tsx`: the
`Filters` form plus a `?gap=1` checkbox and `?sort=answers|prompts|last_seen`;
a table with domain, type tag, owner tag, answers, prompts, brand named,
rivals (names), last seen, and a "gap" tag; each row links its top
observations (`/o/{oid}`) like the recommendations page. The page
computes nothing: sort and filter only.

### B. Crawlability audit — a job kind, a table, a rule

**Fetching.** `bsi_core/crawl.py`. Declare `httpx>=0.28` in
`packages/core/pyproject.toml` (already installed transitively). The
fetch is one injected callable, `Fetch = Callable[[str, str], Response]`
with `(url, user_agent)`, so tests never touch the network — the same
discipline as model calls. The real one: `httpx.Client(timeout=15,
follow_redirects=True, headers={"User-Agent": ua})`, body capped at
512 KiB, every exception folded into a `Response(status=0, body="",
error=repr(e))`. Fetches are sequential with a 0.5 s pause.

**Checks** — `audit_domain(host, fetch) -> list[Check]`, pure and unit
tested from canned responses. `Check(code, ok, severity, observed,
expected, url)`. For one domain, in this order:

| Code | Fetch | Fails when |
|---|---|---|
| `home_unreachable` | `https://{host}/` with a browser UA | status not 2xx (then the on-page checks are skipped) |
| `title_missing`, `description_missing`, `h1_missing`, `canonical_missing`, `org_schema_missing` | same body | tag absent; JSON-LD lacks `"@type": "Organization"`. Parsed with `html.parser` (a small `HTMLParser` subclass collecting head tags, first h1, `ld+json` scripts) |
| `bot_blocked:{bot}` for GPTBot, OAI-SearchBot, ClaudeBot, Claude-SearchBot, PerplexityBot, Google-Extended, Googlebot, Bingbot | `/robots.txt` once | `urllib.robotparser` says the bot may not fetch `/`. A missing robots.txt passes (allow-all). |
| `bot_ua_blocked:{bot}` for the same eight | `/` once per bot UA | status 401/403/429/5xx while the browser UA got 2xx — CDN bot blocking, PRD F10 |
| `sitemap_missing`, `sitemap_invalid` | robots `Sitemap:` lines, else `/sitemap.xml` | not 2xx; or root element is neither `urlset` nor `sitemapindex` (`xml.etree`, `defusedxml` not needed: no entity expansion on a tree we only inspect the root of) |
| `llms_missing` | `/llms.txt` | not 2xx. Severity low; expected text says the file is unofficial |

Severity: `high` for `bot_blocked`/`bot_ua_blocked`/`home_unreachable`,
`medium` for sitemap and `org_schema_missing`, `low` for the rest.
Eleven fetches per domain at most.

**Table** `site_audit` — migration **0012**, with `_protect()` copied
from 0009: `id, created_at, org_id, brand_id (FK), job_id (FK, nullable),
domain, checks JSONB, fetches int`. One row per domain per run; latest =
max `created_at` per `(brand_id, domain)`. Bodies are not stored;
`observed` holds a truncated excerpt (≤ 300 chars). Add to
`TENANT_TABLES` and the `org_b` fixture in `test_rls.py`.

**Job.** Kind `audit_crawl`, `JOB_ESTIMATES["audit_crawl"] = 0`. Move
the queueing upsert out of `routers/runs.py:queue_suggestion` into
`bsi_core/scheduling.py:enqueue_job(s, org_id, brand_id, kind, params)`
so the worker can queue too; `queue_suggestion` calls it. Worker
`process_job` becomes a dispatch dict `{kind: runner}` (replacing the
bare `else:` at `apps/workers/bsi_workers/worker.py:301`);
`run_crawl_audit(org_id, brand_id, fetch)` reads the brand's `domain`
rows, audits each, and inserts one `site_audit` row per domain in one
tenant transaction. **No transaction is open while fetching**, same rule
as model calls. A brand with no domains finishes `done` with 0 rows.

**Weekly.** SECURITY DEFINER `due_crawl_audits()` in 0012: active
brands having ≥ 1 domain whose latest `site_audit.created_at` is null or
older than 7 days, ordered oldest first. `worker.queue_due_crawl_audits()`
calls `enqueue_job` per row inside the 60-second block, one `try` per
brand, after `refresh_due_recommendations`. Because the job unique key is
`(brand, kind, hour)`, a pass that repeats within the hour is a no-op.
The `site_audit` row itself is the stamp — no column on `brand`.

**API.** `routers/audits.py`, prefix `/brands/{brand_id}/audits`:
`POST /crawl` → 202 `{job_id, status_url, status}` via `queue_suggestion`
semantics (409 on archived brand); `GET /crawl` → `list[SiteAuditOut]`,
the latest row per domain, each with its checks. Both go in
`test_isolation.CASES` with an owner-path positive control.

**Recommendation type `fix_crawlability`.**
- `REC_TYPES` gains it; migration 0012 recreates `ck_recommendation_type`
  with the five values; `test_constraints` already compares the live
  constraint to the constant.
- `recommend._crawl(s, brand_id, brand)`: latest audit per domain, one
  `Candidate` per failing check, `subject_key = f"{domain}:{code}"`,
  evidence `{domain, code, observed, expected, url, audit_id}`.
  **reach 1.0, pressure = severity weight (high 1.0, medium 0.5, low
  0.2), `FEASIBILITY` 0.8** — like `add_competitor`, nothing measures
  these against answers, and the docstring says so. A fixed check
  disappears from the next audit, so `refresh()` deletes its open row.
- `crawl_copy(domain, check)` returns title/body from a per-code
  template table; every body ends with a "Metric to watch:" line (the
  check on the next weekly audit, then the brand's citation rate).
  `test_recommend_copy.CASES` gains one entry per code family so the
  forbidden-word scan covers them.
- `NO_IMPACT` gains `fix_crawlability`; `KIND` in `format.ts` gains
  "Site fix". `top_by_type` now has five types; unchanged code.

**Web.** New tab **Site** at `b/[id]/site/page.tsx`: a "Run audit now"
server-action form (`actions.ts` posts `/audits/crawl` and redirects),
then per domain a card: when it ran, fetch count, and a table of checks
with a pass/fail mark, severity tag, observed and expected. Empty state
explains that the weekly pass will run it, or to click.

### Testing

- Unit: `test_crawl.py` — every check from canned responses, both
  passing and failing, including robots wildcard groups, a
  `sitemapindex`, JSON-LD in an array, a body over the cap, a fetch
  that raises. Mutation-check: flipping a UA in the bot list fails a test.
- Unit: `test_citations_source_type.py` — the heuristic map, including
  `www.` and subdomains via `normalize_domain`/`is_owned`.
- Integration: `test_citations.py` — a fixture world (reuse
  `test_recommend.py`'s) where one domain is cited by answers naming two
  rivals and never the brand (`gap` true), one is brand-owned, one has
  one rival (not a gap); check counts, first/last seen, and that the
  locale filter changes the counts. Mutation: set two rivals to one and
  the gap assertion fails.
- Integration: `test_crawl_audit.py` — worker runs `audit_crawl` with a
  fake fetch, one `site_audit` row per domain, `done` with 0 cost; a
  brand without domains → `done`, no rows; a raising fetch → the check
  fails, the job still completes; `due_crawl_audits()` due-not-due at 6
  vs 8 days (backdate with an owner `UPDATE`), archived brands skipped;
  `queue_due_crawl_audits()` idempotent within the hour.
- Integration: `test_recommend.py` — a failing `bot_blocked:GPTBot`
  yields one `fix_crawlability` with pressure 1.0, priority 0.8; a
  passing rerun removes it via `refresh()`; accept → task with
  `measures_impact=False`.
- `test_rls.py` and `test_isolation.py` updated as above; `alembic
  check` clean; both gates; `npm run gen` then `git add` before
  `npm run gate`.

### Live check (no spend)

Run the audit on Run 1's brand domain and on one real domain known to
block GPTBot, read the Site tab and the Citations tab, then clear
`site_audit`, `recommendation`, `task` and `job` rows so the dev tables
stay clean. Record in `docs/findings-slice7.md`: how many of the 247
domains are gaps, the source-type split, and what the audit found.

## Files touched

- new: `packages/core/bsi_core/{citations.py, crawl.py}`,
  `migrations/versions/0012_site_audit_and_crawlability.py`,
  `apps/api/bsi_api/routers/{citations.py, audits.py}`,
  `apps/web/src/app/(app)/b/[id]/{citations,site}/…`,
  `tests/unit/{test_crawl.py, test_citations_source_type.py}`,
  `tests/integration/{test_citations.py, test_crawl_audit.py}`,
  `docs/findings-slice7.md`
- edit: `models.py` (`SiteAudit`, `REC_TYPES`), `recommend.py` (`_crawl`,
  `crawl_copy`, `FEASIBILITY`, `generate`), `scheduling.py`
  (`enqueue_job`), `worker.py` (dispatch, `run_crawl_audit`,
  `queue_due_crawl_audits`, main loop), `routers/runs.py`
  (`queue_suggestion` → `enqueue_job`), `routers/recommendations.py`
  (`NO_IMPACT`), `schemas.py`, `main.py` (routers), `packages/core/
  pyproject.toml` (httpx), `apps/web/src/lib/{format.ts,types.ts}`,
  `b/[id]/layout.tsx` (two tabs), `openapi.json` + `schema.d.ts`
  (generated), `test_rls.py`, `test_isolation.py`,
  `test_recommend_copy.py`, `docs/README.md`.

## Out of scope, by decision

- Fetching cited pages (titles, on-page mentions): the URLs are Vertex
  redirects and it would mean fetching 247 third-party domains per brand.
- A sitemap page sample or a rendered crawl (Playwright). The PRD's
  500–50,000-page crawl is a later slice on top of `audit_domain`.
- Entity consistency (F08) beyond the `org_schema_missing` check, the
  brand SERP audit (F09, needs a licensed provider), and the URL
  optimizer (F11, needs model spend).
- An authority estimate per source: no licensed metric.

## Risks

| Risk | Mitigation |
|---|---|
| A brand domain that is slow or hangs stalls the worker | 15 s timeout per fetch, ≤ 11 fetches per domain; the job's 10-minute stale rule fails it rather than blocking the loop |
| Bot-UA checks read as a false block on a CDN that challenges every UA | `bot_ua_blocked` only fails when the browser UA got 2xx from the same URL |
| `robotparser` misreads unusual robots.txt | The check records the parsed decision and the raw rule lines in `observed`, so a wrong reading is visible on the Site tab |
| The `source_type` heuristic mislabels a domain | Labelled a heuristic in the API and the page; wrong labels affect a tag, not a metric |
| Five types in `top_by_type` crowd the overview differently | The overview keeps k=3; the shortlist is still one per type in priority order, so a low-severity site fix cannot outrank a citation source |
