# Slice 37 design: an on-demand Brand SERP audit (PRD F09, first slice)

## Context

Codebase facts: main `5a127bf`, checked 2026-10-02.

PRD F09 (docs/inputs/prd-brand-search-intelligence-platform.md:313-317, priority P1): "for `[brand]` and `[brand] reviews` in each target locale, classify first-page results (official, social, review, news, competitor, negative, video, image, Knowledge Panel, sitelinks, AI Overview), compute SERP ownership share, and produce a Brand SERP Health Report with findings." Acceptance: "report generated weekly; classification accuracy ≥ 0.9 on benchmark." The PRD allows SERP data only from licensed providers (line 707) and names DataForSEO as primary and SerpApi as fallback (line 695). Its data model has `serp_result` with one row per result (line 599), and its route table lists `/brands/{id}/audits` for "site, entity, serp, crawlability" (line 661). The user chose "F09 SERP audit" from the next-step list.

Facts read before the approaches:
- apps/api/bsi_api/routers/audits.py (47 lines) has `POST` and `GET /brands/{brand_id}/audits/crawl`; its docstring says "Only the crawlability audit so far." The POST returns `queue_suggestion(c, brand_id, "audit_crawl", {})` (routers/runs.py:32), which answers 409 for an archived brand and enqueues one job per brand, kind and hour (`enqueue_job`, scheduling.py:239).
- apps/workers/bsi_workers/worker.py: `JOB_ESTIMATES` (lines 117-127) gates the known job kinds; `process_job` (line 944) checks `budget_fits(s, org_id, 0, extra_micros=estimate)` for a non-zero estimate, dispatches through a `runners` dict of lambdas, and finishes with `_finish_job(org_id, job_id, "done", None, meter.micros)`. On an exception it records `getattr(e, "cost_micros", 0)`. `_Meter.micros` counts only the model calls made through it, so a paid plain-HTTP call is recorded as 0 on success unless the runner adds to it.
- `run_crawl_audit` (worker.py:351-413) reads the brand in one short `tenant_session`, fetches with no session open, and writes its rows in a second `tenant_session`.
- packages/core/bsi_core/crawl.py `http_fetch(url, user_agent, *, method, body, content_type, cap, raw, headers, …)` never raises, returns `Response(status, body, error, truncated)` with no response headers, caps the body at 512 KB unless `cap=` is passed, and accepts a POST with a JSON body and an `Authorization` header to a public https host (only `host`, `user-agent` and `accept-encoding` are pinned).
- packages/core/bsi_core/models.py: `Locale` (`brand_id`, `country`, `language`; no primary flag), `Domain` (`brand_id`, `host`, `is_primary`), `Competitor` (`domains: list[str]`, `status`). `SiteAudit` keeps its checks in a JSONB list. The head migration is 0022. Each migration that creates a tenant table carries its own copy of `_protect(table)` (RLS ENABLE and FORCE, the `tenant` policy, the grant to `bsi_app`).
- packages/core/bsi_core/matching.py: `normalize_domain(value)` (lower-cases, drops scheme, path, port and a leading `www.`) and `is_owned(domain, hosts)` (equal to a host or a subdomain of one).
- packages/core/bsi_core/config.py: `Settings` has no credential fields today; the Gemini credentials come from the Google SDK's own environment variables.
- A brand with no locale: the product run uses IN/en (routers/products.py:157, products.py:1010).
- apps/web/src/app/(app)/b/[id]/site/ has `page.tsx` (a Server Component reading `/brands/{id}/audits/crawl`) and `actions.ts` (`runAudit`, a server action that POSTs and redirects with `?queued=`). The brand nav in `layout.tsx` is a hard-coded row of links.

Provider facts, read from DataForSEO's documentation on 2026-10-02:
- `POST https://api.dataforseo.com/v3/serp/google/organic/live/advanced`; the body is a JSON array of tasks; fields `keyword`, `location_code`, `language_code`, `device` (default `desktop`), `depth` (default 10), `load_async_ai_overview`.
- Live mode is priced at "$0.002" per SERP of 10 results; `load_async_ai_overview` adds one base price. The docs: with it false "you will only obtain `ai_overview` items from cache".
- The response has `status_code`, `cost`, and `tasks[].result[].items[]`; each item has a `type` (`organic`, `knowledge_graph`, `ai_overview`, `video`, `images`, `top_stories`, `people_also_ask`, `paid`, …). An organic item has `rank_absolute`, `domain`, `url`, `title`, `description`, and `links` (sitelinks).
- Status codes: 20000 "Ok."; 40102 "No Search Results."; 40100 not authorized; 40200 and 40210 payment and balance; 40202 rate limit. The API answers HTTP 200 for most internal errors.
- Authentication is HTTP Basic with the API login and an auto-generated API password from the dashboard's API Access tab.
- `GET https://api.dataforseo.com/v3/serp/google/locations/{country}` is free and returns items with `location_code`, `location_name`, `country_iso_code`, `location_type`; the United States is 2840 at type "Country".
- Not confirmed: a minimum deposit, a free credit, and a sandbox host. The pricing and auth pages read do not state them.

Classification: **architectural** — a new external provider, a new table, a new job kind, new routes and a new page; there is no existing SERP flow to change.

Decisions approved in chat (brainstorming on Fable 5.1, 2026-10-02), each after approaches with trade-offs, the facts above and a recommendation in a chat message:
1. Provider: DataForSEO (over SerpApi, and over fixtures with no provider chosen).
2. Scope: an on-demand audit end to end (over adapter and storage only, and over all of F09 at once).
3. Classification: rules only; an unmatched organic result is `other`; `negative` is not produced in this slice (over a model step for the unmatched results, and over a model for everything).
4. Ownership share: organic results on the brand's own hosts ÷ all organic first-page results, unweighted (over counting social results as owned, and over position weights).
5. Request profile: desktop, with `load_async_ai_overview` on (over mobile, loading off, and both devices).
6. Design Sections 1–3; the text of each was in chat before its approval question. Section 1's approval included one `serp_audit` row per page with the results in JSONB, a departure from the PRD's per-result `serp_result`.

## Design

### Settings and credentials

packages/core/bsi_core/config.py gains two fields, `dataforseo_login: str = ""` and `dataforseo_password: str = ""`; `.env.example` gains `DATAFORSEO_LOGIN=` and `DATAFORSEO_PASSWORD=`. The values are used only to build the `Authorization: Basic …` header. They are never logged, stored or returned by a route.

### The adapter

New packages/core/bsi_core/providers/dataforseo.py:

```python
@dataclass
class SerpItem:
    position: int      # rank_absolute; 0 when the provider gives none
    item_type: str     # the provider's `type`
    url: str           # "" when the item has none
    domain: str
    title: str
    sitelinks: bool    # an organic item with a non-empty `links`


@dataclass
class SerpPage:
    items: list[SerpItem]
    cost_micros: int = 0
    error: str | None = None


def serp(
    query: str, country: str, language: str, *, login: str, password: str,
    fetch: SerpFetch = http_fetch,
) -> SerpPage: ...
```

- It never raises. `SerpFetch` is a Protocol for the keyword form of `http_fetch` the adapter uses (`method`, `body`, `content_type`, `cap`, `headers`), so tests pass a fake.
- With `login` or `password` empty it returns `SerpPage([], 0, "serp_not_configured")` and makes no call.
- Location: `GET /v3/serp/google/locations/{country lower-cased}`; the item with `location_type == "Country"` gives the `location_code`. Results are cached in a module dict per country for the life of the process. A failed lookup (HTTP failure, bad JSON, status other than 20000, no Country item) returns error `location`, and is not cached.
- Search: `POST /v3/serp/google/organic/live/advanced` with one task: `{"keyword": query, "location_code": code, "language_code": language, "device": "desktop", "depth": 10, "load_async_ai_overview": true}`.
- Both calls go through `fetch` with user agent `SERP_UA = "bsi-platform-serp/1.0"`, `content_type="application/json"` on the POST, the Basic header, and `cap=SERP_CAP_BYTES = 4 * 1024 * 1024`.
- `cost_micros = round(cost * 1_000_000)` from the task's `cost` (the top-level `cost` when the task has none), also on an error response that reports one.
- Errors, as short codes: `http` (fetch error or a status outside 2xx), `truncated` (the capped body was cut), `json` (unparseable, or not the documented shape), `auth` (40100), `funds` (40200, 40210), `rate` (40202), `provider_<code>` for any other status that is neither 20000 nor 40102. 40102 is a success with no items.
- The raw response is not stored.

### Data model

Migration 0023 creates one tenant table, `serp_audit`: one row per query × locale × run.

| Column | Type | Meaning |
|---|---|---|
| `id`, `created_at`, `org_id` | as every tenant table | |
| `brand_id` | uuid, FK brand.id | |
| `job_id` | uuid null, FK job.id | the job that wrote it |
| `kind` | varchar, CHECK in (`brand`, `reviews`) | which of the two queries |
| `query` | varchar | the text searched |
| `country`, `language` | varchar | the locale used |
| `device` | varchar, server default `desktop` | |
| `results` | JSONB, server default `[]` | one entry per stored item: `position`, `item_type`, `result_type`, `url`, `domain`, `title`, `sitelinks` |
| `fetched_at` | timestamptz, server default now() | |
| `cost_micros` | integer, server default 0 | |
| `error` | varchar null | the adapter's error code; `results` is `[]` |

- Index `ix_serp_audit_latest` on (`brand_id`, `kind`, `country`, `language`, `fetched_at`).
- `_protect("serp_audit")`, copied into the migration as the others do.
- `SerpAudit(Tenant, Base)` in models.py; `"serp_audit"` in `TENANT_TABLES` and one row in the `org_b` fixture (tests/integration/test_rls.py).
- Departure from the PRD's `serp_result` (one row per result), approved with Section 1: a page is read and written whole, and a failed query still has a row. SQL across individual results is harder; nothing in this slice or the planned alert needs it.

### Classification and ownership

New packages/core/bsi_core/serp.py (pure functions; the first matching rule wins):

```python
# Provider item type -> our type; an organic item is decided by its host.
ITEM_TYPES = {
    "knowledge_graph": "knowledge_panel",
    "ai_overview": "ai_overview",
    "top_stories": "news",
    "video": "video",
    "images": "image",
}
VIDEO_HOSTS = ("youtube.com",)
# ponytail: x.com is listed beside twitter.com; entity._social folds one
# into the other for profile URLs, a host test needs both.
SOCIAL_HOSTS = (
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
)
REVIEW_HOSTS = (
    "trustpilot.com",
    "mouthshut.com",
    "glassdoor.com",
    "glassdoor.co.in",
    "ambitionbox.com",
    "consumercomplaints.in",
    "sitejabber.com",
    "g2.com",
)


def classify(
    item_type: str, url: str, own: Iterable[str], rivals: Iterable[str]
) -> str | None:
    """Our result type for one provider item; None = not stored."""
    if item_type in ITEM_TYPES:
        return ITEM_TYPES[item_type]
    if item_type != "organic":
        return None
    host = normalize_domain(url)
    if is_owned(host, VIDEO_HOSTS):
        return "video"
    if is_owned(host, [normalize_domain(h) for h in own]):
        return "official"
    if is_owned(host, [normalize_domain(h) for h in rivals]):
        return "competitor"
    if is_owned(host, SOCIAL_HOSTS):
        return "social"
    if is_owned(host, REVIEW_HOSTS):
        return "review"
    return "other"


def ownership(results: Iterable[Mapping[str, Any]]) -> tuple[int, int]:
    """(official organic results, all organic results)."""
    organic = [r for r in results if r.get("item_type") == "organic"]
    owned = sum(r.get("result_type") == "official" for r in organic)
    return owned, len(organic)
```

- Sitelinks are a flag on an organic result, not a type: an official result with sitelinks stays `official`.
- `negative` is not produced (decision 3). People Also Ask, related searches, ads and every other provider item type are not stored.
- `own` is the brand's `Domain.host` list; `rivals` is every competitor's `domains`, of any status, as the product run does.
- Ownership is computed when read, not stored. A page with no organic results is (0, 0), shown with no percentage.
- Prototype, run on 2026-10-02 in a scratch folder outside the repo against the repo's `bsi_core.matching`: an 18-case table (one case per rule, subdomain and `www.` variants, a look-alike host `notwalkaroo.in`, two unstored types) gave `18 cases, 0 wrong`; `ownership` gave `(1, 2)` for two organic results with one official plus a Knowledge Panel, and `(0, 0)` for an empty page; a rival's YouTube channel classified as `video`, and a host that is both the brand's own and a rival's as `official`. `ruff check` and `ruff format --check` were clean on the file. `mypy --strict` on the scratch file reported one error, the unresolved import of `bsi_core` from outside the package; it is to be re-run inside the package by the plan.

### The job

`JOB_ESTIMATES["audit_serp"] = SERP_JOB_MICROS = 40_000` and a `runners` entry `"audit_serp": lambda: run_serp_audit(org_id, brand_id, job_id, meter, fetch=…)` in worker.py. New `run_serp_audit`:

1. A short `tenant_session` reads the brand's name, its `Domain.host` list, its locales ordered by `created_at` (IN/en when it has none), and all competitors' domains.
2. With no session open, for each of the first `MAX_SERP_LOCALES = 5` locales it calls `serp()` for `{name}` (kind `brand`) and `{name} reviews` (kind `reviews`), and adds each page's `cost_micros` to `meter.micros`. Each stored item gets `result_type = classify(...)`; an item classified `None` is dropped.
3. A second `tenant_session` adds one `SerpAudit` row per query, failed ones included.
4. It returns a summary string naming the rows written, the failures, and any locales left out by the cap.

- The estimate covers 5 locales × 2 queries × $0.004. `budget_fits` checks it when the worker claims the job; over budget fails the job as `budget`, as today.
- Missing credentials: every query returns `serp_not_configured`, so no rows are written and the job fails as described next.
- If every query failed, the job raises `SerpFailed(first error code, cost_micros)`; `process_job` records the error code as the job's error and the cost carried. No rows are written when the error is `serp_not_configured`; for any other all-failed run the error rows are written first.
- If at least one query succeeded the job is `done`.
- Recommendations are not refreshed: no SERP-based rule exists yet.

### API

In apps/api/bsi_api/routers/audits.py:
- `POST /v1/brands/{brand_id}/audits/serp` → 202 `QueuedOut`, `queue_suggestion(c, brand_id, "audit_serp", {})`.
- `GET /v1/brands/{brand_id}/audits/serp` → `list[SerpAuditOut]`: the latest row per (`kind`, `country`, `language`) by `fetched_at` then `id`, with `owned` and `organic` from `ownership(results)`. A locale later removed from the brand still shows its last audit.
- `SerpAuditOut`: `id`, `kind`, `query`, `country`, `language`, `device`, `fetched_at`, `cost_micros`, `error`, `owned`, `organic`, `results: list[SerpResultOut]`.
- Both routes in `CASES` (tests/integration/test_isolation.py). `npm run gen`; `openapi.json` and `schema.d.ts` committed.
- The module docstring no longer says only the crawlability audit exists.

### Web

New apps/web/src/app/(app)/b/[id]/serp/ with `page.tsx` and `actions.ts`, modelled on the Site page; a "Brand SERP" link after "Site" in `layout.tsx`.
- "Run audit now" (a server action that POSTs, then redirects to `/b/{id}/serp?queued={status}`, with `redirect()` outside any `try`).
- One card per row: the query, country, language and fetch time; "Ownership: 3 of 10 (30%)" (no percentage for 0 of 0); a count per result type; whether a Knowledge Panel and an AI Overview were present; a table of position, type, title, host and a sitelinks mark.
- A row with an error shows the error's label in place of the table; the labels live in lib/format.ts. With no rows the page says no audit has run.
- Server Components and one server action; no new Route Handler.

### Tests

- Unit, tests/unit/test_serp.py: the classification table (one case per rule and the order cases above) and `ownership`.
- Unit, tests/unit/test_dataforseo.py: a fake `fetch` over fixture JSON written from the documented response shape: a page with mixed item types; 40102; each error code; bad JSON; an HTTP failure; a truncated body; missing credentials (no call made); the location lookup, its cache and its failure; the request body and the Basic header sent.
- Integration: the job through `process_job` with a fake fetch (rows written, classification applied, cost recorded on the job, a partial failure, an all-failed run, missing credentials, the locale cap, the IN/en default, and no transaction open during fetches by the existing `pg_stat_activity` probe); the two routes; the RLS and isolation entries.
- Web: a vitest for the page's formatting helper.
- No test calls the provider.

### Live check

After merge, with the user's go-ahead at each step:
- The user puts the DataForSEO login and password in `.env`; the controller does not handle the credentials.
- Dev is migrated to 0023 (asked first).
- One audit of dev's brand (1 locale, 2 queries), expected cost about $0.008, read from the rows' `cost_micros`. The API key request writes `api_key.last_used_at`.
- This is the first run of the adapter against a real response: the fixtures are written from the documentation. Parsing defects found here are fixed in a follow-up.
- Without an account the slice merges with the live check recorded as not run.

### Copy

New text (code, comments, labels, docs) is checked against `FORBIDDEN` in tests/unit/test_recommend_copy.py by a grep of the diff.

## Process and docs

- Branch `slice37-serp-audit`; spec reviewer (Opus 5.5); plan by writing-plans; subagent-driven execution with a task review per task and a final whole-branch review; at most one fix wave; PR; merge on the user's go-ahead.
- After merge: `docs/findings-slice37.md` (what was built, the live check, deferred and untested, rulings), README rows, memory.
- Subagents are dispatched with `model: "opus"` while the session is on Fable 5.1.

## Rulings

- **R1: commits carry the Fable 5.1 trailer.** Decided: slice 37 commits end with "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>", the trailer the latest attribution reminder names; a later reminder naming another needs a new ruling. Found by the controller, on the attribution reminder that came with the user's model switch. Why: the process binds the trailer to the latest session reminder. Cost if wrong: a trailer naming the orchestrating model on commits written by Opus 5.5 subagents. Named in chat when made.
- **R2: Section 2's cost sentence was corrected in chat.** Decided: the estimate is a constant 40,000 micros, covering 5 locales × 2 queries × $0.004; the Section 2 text shown in chat had a half-finished clause before it ("8,000 micros per locale × … no:"). Found by the controller, after the user had approved Section 2; stated at the top of the Section 3 message. Why: the approved text must say one thing. Cost if wrong: none; the figure approved and the figure here are the same. Named in chat when made.
- **R3: details settled while writing the spec.** Decided: 40102 "No Search Results" is a success with no items; adapter errors are the short codes listed above; the user agent is `bsi-platform-serp/1.0`; the response cap is 4 MB; a failed location lookup is error `location` and is not cached; `GET` shows the latest row per (`kind`, `country`, `language`) even for a locale since removed; an all-failed run raises `SerpFailed` and writes its error rows, except for `serp_not_configured`, which writes none; recommendations are not refreshed. Found by the controller, writing the spec. Why: Sections 1–3 left these open and the plan needs them fixed. Cost if wrong: each is a small change to one function. Named in chat when made.

## Out of scope

- The weekly schedule and a report section; the "Brand SERP change" alert; SERP-based recommendations.
- The `negative` type and the 0.9 accuracy benchmark.
- SerpApi as a fallback, with failover; retries and backoff on provider errors.
- Mobile results; matching social results to the brand's own profiles; brand aliases as extra queries.
- Storing the raw provider response; the queued (non-live) provider modes.
