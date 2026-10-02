# Slice 37 design: an on-demand Brand SERP audit (PRD F09, first slice)

## Context

Codebase facts: main `5a127bf`, checked 2026-10-02.

PRD F09 (docs/inputs/prd-brand-search-intelligence-platform.md:313-317, priority P1): "for `[brand]` and `[brand] reviews` in each target locale, classify first-page results (official, social, review, news, competitor, negative, video, image, Knowledge Panel, sitelinks, AI Overview), compute SERP ownership share, and produce a Brand SERP Health Report with findings." Acceptance: "report generated weekly; classification accuracy ≥ 0.9 on benchmark." The PRD allows SERP data only from licensed providers (line 707) and names DataForSEO as primary and SerpApi as fallback (line 695). Its data model has `serp_result` with one row per result (line 599), and its route table lists `/brands/{id}/audits` for "site, entity, serp, crawlability" (line 661). The user chose "F09 SERP audit" from the next-step list.

Facts read before the approaches:
- apps/api/bsi_api/routers/audits.py (47 lines) has `POST` and `GET /brands/{brand_id}/audits/crawl`; its docstring says "Only the crawlability audit so far." The POST returns `queue_suggestion(c, brand_id, "audit_crawl", {})` (routers/runs.py:32), which answers 409 for an archived brand and enqueues one job per brand, kind and hour (`enqueue_job`, scheduling.py:239); a failed job is requeued by a new request in the same hour, a done one is not.
- apps/workers/bsi_workers/worker.py: `JOB_ESTIMATES` (lines 117-127) gates the known job kinds; `process_job` (line 944) checks `budget_fits(s, org_id, 0, extra_micros=estimate)` for a non-zero estimate, dispatches through a `runners` dict of lambdas, and finishes with `_finish_job(org_id, job_id, "done", None, meter.micros)`. On an exception it records `getattr(e, "cost_micros", 0)` and ignores `meter.micros`; the job's error is "budget" for `OverBudget`, "cap" for `CatalogueCap`, and `repr(e)[:2000]` otherwise (lines 1003-1018). `_Meter.micros` counts only the model calls made through it. `process_job`'s `fetch` parameter is `Fetch = Callable[[str, str], Response]` (crawl.py:70), the two-argument GET form; webhook delivery takes a separate `Poster` protocol (worker.py:103-113).
- `run_crawl_audit` (worker.py:351-413) reads the brand in one short `tenant_session`, fetches with no session open, and writes its rows in a second `tenant_session`. `run_products` wraps its work so that any failure re-raises with the spend (`except Exception as e: raise JudgeFailed(e, spent) from e`, products.py:1321-1324).
- `claim_job()` fails a job still running after 10 minutes as `stale` (migration 0007).
- packages/core/bsi_core/crawl.py `http_fetch(url, user_agent, *, method, body, content_type, cap, raw, headers, …)` never raises, returns `Response(status, body, error, truncated)` with no response headers, caps the body at 512 KB unless `cap=` is passed, has a 30-second deadline per fetch (`DEADLINE_SECONDS`), and accepts a POST with a JSON body and an `Authorization` header to a public https host (only `host`, `user-agent` and `accept-encoding` are pinned). A GET follows redirects and sends caller headers on every hop; a POST never follows a redirect.
- packages/core/bsi_core/models.py: `Locale` (`brand_id`, `country`, `language`; no primary flag), `Domain` (`brand_id`, `host`, `is_primary`), `Competitor` (`domains: list[str]`, `status` `suggested` or `active`). `SiteAudit` keeps its checks in a JSONB list. The head migration is 0022. `job.kind` has no CHECK constraint. Migrations 0009, 0012, 0014, 0015, 0016, 0017 and 0019 each carry their own copy of `_protect(table)` (the `org_id` index, RLS ENABLE and FORCE, the `tenant` policy, the grant to `bsi_app`).
- Brand creation adds one locale, IN/en (routers/brands.py:159-163); no route adds or edits locales. A brand with no locale: the product run uses IN/en (routers/products.py:157, products.py:1010).
- packages/core/bsi_core/matching.py: `normalize_domain(value)` (lower-cases, drops scheme, path, query, port and a leading `www.`; it does not drop a `#fragment`) and `is_owned(domain, hosts)` (equal to a host or a subdomain of one).
- packages/core/bsi_core/competitors.py: `owner_of` and `_entities_and_hosts` classify hosts with **active** competitors only. Suggested competitors' domains come from the model (suggest.py:179-183).
- packages/core/bsi_core/config.py: `Settings` has no credential fields today; the Gemini credentials come from the Google SDK's own environment variables.
- apps/web/src/app/(app)/b/[id]/site/ has `page.tsx` (a Server Component reading `/brands/{id}/audits/crawl`) and `actions.ts` (`runAudit`, a server action that POSTs and redirects with `?queued=`). The Products page shows the latest job's state ("Run in progress", "Last run failed: …", "Last run: done") from `jobs` in its API response (products/page.tsx:8-16). The brand nav in `layout.tsx` is a hard-coded row of links. Page types are aliases of the generated schema in apps/web/src/lib/types.ts.

Provider facts, read from DataForSEO's documentation on 2026-10-02:
- `POST https://api.dataforseo.com/v3/serp/google/organic/live/advanced`; the body is a JSON array of tasks; fields `keyword`, `location_code` or `location_name` ("full name of search engine location"), `language_code`, `device` (default `desktop`), `depth` (default 10), `load_async_ai_overview`.
- Live mode is priced at "$0.002" per SERP of 10 results, "up to 6 seconds on average"; `load_async_ai_overview` adds one base price. The docs: with it false "you will only obtain `ai_overview` items from cache".
- The response has a top-level `status_code` and `cost`, and `tasks[]`, each with its own `status_code`, `cost` and `result[].items[]`; each item has a `type` (`organic`, `featured_snippet`, `knowledge_graph`, `ai_overview`, `video`, `images`, `top_stories`, `people_also_ask`, `paid`, …). An organic item has `rank_absolute`, `domain`, `url`, `title`, `description`, and `links` (sitelinks).
- Status codes: 20000 "Ok."; 40102 "No Search Results."; 40100 not authorized; 40200 and 40210 payment and balance; 40202 rate limit. The API answers HTTP 200 for most internal errors, and HTTP 401, 402, 404 and 500 for some.
- Authentication is HTTP Basic with the API login and an auto-generated API password from the dashboard's API Access tab.
- Not confirmed, to be checked at the live check: that `location_name` "India" is the exact accepted name; the latency of a live call with `load_async_ai_overview` on (the design assumes it finishes inside `http_fetch`'s 30-second deadline); which level, top or task, carries each error's status code. Also not confirmed, and not needed by the design: a minimum deposit, a free credit, and a sandbox host.

Classification: **architectural** — a new external provider, a new table, a new job kind, new routes and a new page; there is no existing SERP flow to change.

Decisions approved in chat (brainstorming on Fable 5.1, 2026-10-02), each after approaches with trade-offs, the facts above and a recommendation in a chat message:
1. Provider: DataForSEO (over SerpApi, and over fixtures with no provider chosen).
2. Scope: an on-demand audit end to end (over adapter and storage only, and over all of F09 at once).
3. Classification: rules only; an unmatched organic result is `other`; `negative` is not produced in this slice (over a model step for the unmatched results, and over a model for everything).
4. Ownership share: organic results on the brand's own hosts ÷ all organic first-page results, unweighted (over counting social results as owned, and over position weights).
5. Request profile: desktop, with `load_async_ai_overview` on (over mobile, loading off, and both devices).
6. Design Sections 1–3; the text of each was in chat before its approval question. Section 1's approval included one `serp_audit` row per page with the results in JSONB, a departure from the PRD's per-result `serp_result`.
7. After the spec review of 166a560, three points were re-asked and decided by the user: a static country table in place of the location lookup (R4); active competitors only (R5); the page shows the latest job's status (R6).

## Design

### Settings and credentials

packages/core/bsi_core/config.py gains two fields, `dataforseo_login: str = ""` and `dataforseo_password: SecretStr = SecretStr("")`; `.env.example` gains `DATAFORSEO_LOGIN=` and `DATAFORSEO_PASSWORD=`. The values are used only to build the `Authorization: Basic …` header. They are never logged, stored or returned by a route. `run_serp_audit` reads them from `get_settings()`.

### The adapter

New packages/core/bsi_core/providers/dataforseo.py:

```python
@dataclass
class SerpItem:
    position: int      # rank_absolute; 0 when the provider gives none
    item_type: str     # the provider's `type`
    url: str           # "" when the item has none
    domain: str        # "" when the item has none
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
- With `login` or `password` empty it returns `SerpPage([], 0, "serp_not_configured")` and makes no call. This check comes first, before the country check.
- Location: `LOCATIONS = {"IN": "India"}`, a dict from the locale's country (upper-cased) to the provider's `location_name`. A country not in it returns error `location` and makes no call. There is no lookup call (R4).
- Search: one `POST /v3/serp/google/organic/live/advanced` with one task: `{"keyword": query, "location_name": name, "language_code": language, "device": "desktop", "depth": 10, "load_async_ai_overview": true}`. The adapter makes no GET, so the credentials are never sent on a request that follows redirects.
- The call goes through `fetch` with user agent `SERP_UA = "bsi-platform-serp/1.0"`, `content_type="application/json"`, the Basic header, and `cap=SERP_CAP_BYTES = 4 * 1024 * 1024`.
- Status: the top-level `status_code` is read first, then `tasks[0].status_code`; each is mapped by the same table.
- `cost_micros = round(cost * 1_000_000)` from the task's `cost` (the top-level `cost` when there is no task), also on an error response that reports one. A call that fails before a body is parsed (a timeout, an HTTP failure) has an unknown cost and is recorded as 0.
- Errors, as short codes: `http` (fetch error or an HTTP status outside 2xx), `truncated` (the capped body was cut), `json` (unparseable, or not the documented shape), `auth` (40100), `funds` (40200, 40210), `rate` (40202), `provider_<code>` for any other status that is neither 20000 nor 40102. 40102 is a success with no items.
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
| `device` | varchar, server default `desktop` | always `desktop` in this slice; kept so mobile needs no migration |
| `results` | JSONB, server default `[]` | one entry per stored item: `position`, `item_type`, `result_type`, `url`, `domain`, `title`, `sitelinks` |
| `fetched_at` | timestamptz, not null | set by the worker when `serp()` returns, also for an error that made no call |
| `cost_micros` | integer, server default 0 | |
| `error` | varchar null | the adapter's error code; `results` is `[]` |

- No index beyond the `org_id` index `_protect` creates: a brand has a few rows per audit.
- `_protect("serp_audit")`, copied into the migration as the seven migrations above do.
- `SerpAudit(Tenant, Base)` in models.py; `"serp_audit"` in `TENANT_TABLES` and one row in the `org_b` fixture (tests/integration/test_rls.py).
- Departure from the PRD's `serp_result` (one row per result), approved with Section 1: a page is read and written whole, and a failed query still has a row. SQL across individual results is harder; nothing in this slice or the planned alert needs it.

### Classification and ownership

New packages/core/bsi_core/serp.py (pure functions; the first matching rule wins):

```python
# Provider item type -> our type.
ITEM_TYPES = {
    "knowledge_graph": "knowledge_panel",
    "ai_overview": "ai_overview",
    "top_stories": "news",
    "video": "video",
    "images": "image",
}
# Decided by host, in classify()'s order.
HOSTED = ("organic", "featured_snippet")
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
    item_type: str, host: str, own: Iterable[str], rivals: Iterable[str]
) -> str | None:
    """Our result type for one provider item; None = not stored. `host`
    is the item's domain, or its URL when the provider gives no domain."""
    if item_type in ITEM_TYPES:
        return ITEM_TYPES[item_type]
    if item_type not in HOSTED:
        return None
    host = normalize_domain(host)
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

- The caller passes `item.domain or item.url`: the provider's `domain` field avoids `normalize_domain`'s gap on a URL with a fragment and no path.
- A featured snippet is stored and typed by its host like an organic result, but it is not an organic result, so `ownership` does not count it (decision 4).
- Sitelinks are a flag on an organic result, not a type: an official result with sitelinks stays `official`.
- `negative` is not produced (decision 3). People Also Ask, related searches, ads and every other provider item type are not stored.
- `own` is the brand's `Domain.host` list; `rivals` is the `domains` of the brand's **active** competitors (R5), as `competitors.owner_of` uses.
- A brand's own YouTube channel is `video`: the host rules cannot tell whose channel or profile a page is. A social host listed in either domain list classifies every result on that host by that list, the other party's profile included: with `instagram.com` among a competitor's domains every Instagram result is `competitor`, and among the brand's own hosts every one is `official` and counts as owned.
- Ownership is computed when read, not stored. A page with no organic results is (0, 0), shown with no percentage.
- Prototype, run on 2026-10-02 in a scratch folder outside the repo against the repo's `bsi_core.matching`: a 22-case table (one case per rule; subdomain and `www.` variants; a look-alike host `notwalkaroo.in`; a bare domain and an empty host; two featured snippets; two unstored types) gave `22 cases, 0 wrong`; `ownership` gave `(1, 2)` for two organic results with one official plus a Knowledge Panel, and `(0, 0)` for an empty page; a rival's YouTube channel classified as `video`, and a host that is both the brand's own and a rival's as `official`. `ruff check` and `ruff format --check` were clean on the file. `mypy --strict` on the scratch file reported one error, the unresolved import of `bsi_core` from outside the package; the plan re-runs it inside the package.

### The job

In worker.py: `JOB_ESTIMATES["audit_serp"] = SERP_JOB_MICROS = 40_000`; `process_job` gains a keyword `serp_fetch: SerpFetch = http_fetch` (the existing `fetch: Fetch` stays the two-argument GET form) and a `runners` entry `"audit_serp": lambda: run_serp_audit(org_id, brand_id, job_id, meter, serp_fetch)`; `tick` is unchanged: the worker loop uses the default, and tests call `process_job` directly. New `run_serp_audit`:

0. If the login or the password in `get_settings()` is empty, it raises `SerpFailed("serp_not_configured", 0)` before reading anything: no call, no rows.
1. A short `tenant_session` reads the brand's name, its `Domain.host` list, its locales ordered by `created_at` (IN/en when it has none), and its active competitors' domains.
2. With no session open, for each of the first `MAX_SERP_LOCALES = 5` locales it calls `serp()` for `{name}` (kind `brand`) and `{name} reviews` (kind `reviews`), adds each page's `cost_micros` to `meter.micros`, and notes the time as that row's `fetched_at`. Each item gets `result_type = classify(...)`; an item classified `None` is dropped.
3. A second `tenant_session` adds one `SerpAudit` row per query, failed ones included; then, if every query failed, it raises `SerpFailed(first error code, total spend)`.
4. It returns a summary string naming the rows written, the failures, and any locales left out by the cap.

- `SerpFailed(code, cost_micros)` is a `RuntimeError` carrying `code` and the run's **total** spend. Steps 2 and 3 are wrapped so that any other exception (a failed write, for example) re-raises as `SerpFailed("error", total spend)` with the cause chained, as `run_products` does with `JudgeFailed`; the money is recorded either way.
- `process_job`'s error mapping gains a branch: for `SerpFailed` the job's error is `e.code`.
- The estimate covers 5 locales × 2 queries × $0.004. `budget_fits` checks it when the worker claims the job; over budget fails the job as `budget`, as today. The default daily budget is $2.00, so the estimate is 2% of it.
- Worst-case duration: 10 calls at up to about 45 seconds each (the 30-second deadline is checked after a chunk, and a read may wait 15 seconds; worker.py:85-86 says "one fetch of up to ~45 s") is about 450 seconds, inside `claim_job`'s 10-minute stale rule.
- The locale cap, the IN/en default and the `device` column are forward-looking: every brand has exactly one locale today.
- A run with at least one successful query is `done`. A `done` job is not requeued within its hour, so a partly failed audit can be rerun in the next hour; a `failed` one can be rerun at once.
- Recommendations are not refreshed: no SERP-based rule exists yet.

### API

In apps/api/bsi_api/routers/audits.py:
- `POST /v1/brands/{brand_id}/audits/serp` → 202 `QueuedOut`, `queue_suggestion(c, brand_id, "audit_serp", {})`.
- `GET /v1/brands/{brand_id}/audits/serp` → `SerpAuditsOut`: `{"job": SerpJobOut | null, "audits": list[SerpAuditOut]}` (R6).
  - `job` is the brand's latest `audit_serp` job by `created_at`: `status` and `error`.
  - `audits` is the latest row per (`kind`, `country`, `language`) by `fetched_at`, with `owned` and `organic` from `ownership(results)`. The latest row is shown even when it is an error and an older row succeeded: the page shows the current state, not the last good one. A locale later removed from the brand still shows its last audit.
- `SerpAuditOut`: `id`, `kind`, `query`, `country`, `language`, `device`, `fetched_at`, `cost_micros`, `error`, `owned`, `organic`, `results: list[SerpResultOut]`. `SerpResultOut`: `position`, `item_type`, `result_type`, `url`, `domain`, `title`, `sitelinks`.
- Both routes in `CASES` (tests/integration/test_isolation.py). `npm run gen`; `openapi.json` and `schema.d.ts` committed.
- The module docstring no longer says only the crawlability audit exists.

### Web

New apps/web/src/app/(app)/b/[id]/serp/ with `page.tsx` and `actions.ts`, modelled on the Site page; a "Brand SERP" link after "Site" in `layout.tsx`; `SerpAudits` in lib/types.ts.
- "Run audit now" (a server action that POSTs, then redirects to `/b/{id}/serp?queued={status}`, with `redirect()` outside any `try`).
- A status line from `job`, in the Products page's manner: in progress (queued or running), "Last audit failed: {label}", or nothing extra when done. The labels for job errors (`serp_not_configured`, `budget`, `stale`, and the adapter's codes) live in lib/format.ts; an unknown error shows as is.
- One card per audit row: the query, country, language and fetch time; "Ownership: 3 of 10 (30%)" (no percentage for 0 of 0); a count per result type; whether a Knowledge Panel and an AI Overview were present; a table of position, type, title, host and a sitelinks mark.
- A row with an error shows the error's label in place of the table. With no rows the page says no audit has run.
- Server Components and one server action; no new Route Handler.

### Tests

- Unit, tests/unit/test_serp.py: the classification table (one case per rule and the order cases above) and `ownership`.
- Unit, tests/unit/test_dataforseo.py: a fake `fetch` over fixture JSON written from the documented response shape: a page with mixed item types; 40102; each error code at the top level and at the task level; bad JSON; an HTTP failure; a truncated body; missing credentials (no call made); an unknown country (no call made); the request body, the user agent and the Basic header sent.
- Integration: the job through `process_job` with a fake `serp_fetch` (rows written, classification applied with active competitors only, cost recorded on the job, a partial failure, an all-failed run with its rows and the job's error code and cost, a write failure still recording the spend, missing credentials with no rows, the locale cap, the IN/en default, and no transaction open during fetches by the existing `pg_stat_activity` probe); the two routes including the `job` field; the RLS and isolation entries.
- Web: a vitest for the page's formatting helpers.
- Fixture titles avoid the words in `FORBIDDEN`.
- No test calls the provider.

### Live check

After merge, with the user's go-ahead at each step:
- The user puts the DataForSEO login and password in `.env`; the controller does not handle the credentials.
- Dev is migrated to 0023 (asked first).
- One audit of dev's brand (1 locale, 2 queries), expected cost about $0.008, read from the rows' `cost_micros`. The API key request writes `api_key.last_used_at`.
- This is the first run of the adapter against a real response: the fixtures are written from the documentation. It also checks the three unconfirmed provider facts the design depends on (`location_name` "India", the call's latency against the 30-second deadline, the status-code levels). Parsing defects found here are fixed in a follow-up.
- Without an account the slice merges with the live check recorded as not run.

### Copy

New text (code, comments, labels, docs) is checked against `FORBIDDEN` in tests/unit/test_recommend_copy.py by a grep of the diff.

## Departures from the PRD

- `serp_audit` with JSONB results, not `serp_result` rows (line 599); approved with Section 1.
- "sitelinks" (line 315) is a flag on a result, not a result type.
- `negative` (line 315) is not produced; decision 3.
- The provider credentials are in `.env` and `Settings`, not "Secret Manager" (line 707): production GCP is not built.
- One provider with no fallback, retries, backoff or circuit breaker (lines 223, 695).

## Process and docs

- Branch `slice37-serp-audit`; spec reviewer (Opus 5.5); plan by writing-plans; subagent-driven execution with a task review per task and a final whole-branch review; at most one fix wave; PR; merge on the user's go-ahead.
- After merge: `docs/findings-slice37.md` (what was built, the live check, deferred and untested, rulings), README rows, memory.
- Subagents are dispatched with `model: "opus"` while the session is on Fable 5.1.

## Rulings

- **R1: commits carry the Fable 5.1 trailer.** Decided: slice 37 commits end with "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>", the trailer the latest attribution reminder names; a later reminder naming another needs a new ruling. Found by the controller, on the attribution reminder that came with the user's model switch. Why: the process binds the trailer to the latest session reminder. Cost if wrong: a trailer naming the orchestrating model on commits written by Opus 5.5 subagents. Named in chat when made.
- **R2: Section 2's cost sentence was corrected in chat.** Decided: the estimate is a constant 40,000 micros, covering 5 locales × 2 queries × $0.004; the Section 2 text shown in chat had a half-finished clause before it ("8,000 micros per locale × … no:"). Found by the controller, after the user had approved Section 2; stated at the top of the Section 3 message. Why: the approved text must say one thing. Cost if wrong: none; the figure approved and the figure here are the same. Named in chat when made.
- **R3: details settled while writing the spec.** Decided: 40102 "No Search Results" is a success with no items; adapter errors are the short codes listed above; the user agent is `bsi-platform-serp/1.0`; the response cap is 4 MB; `GET` shows the latest row per (`kind`, `country`, `language`) even for a locale since removed; an all-failed run raises `SerpFailed` and writes its error rows; missing credentials write none; recommendations are not refreshed. (As first written, R3 also covered the location lookup's failure, which R4 removed.) Found by the controller, writing the spec. Why: Sections 1–3 left these open and the plan needs them fixed. Cost if wrong: each is a small change to one function. Named in chat when made.
- **R4: a static country table replaces the location lookup.** Decided: `LOCATIONS = {"IN": "India"}` sent as `location_name`; an unknown country is error `location`; no `GET /locations` call and no cache; the password is a `SecretStr`; the user chose this over keeping the lookup with a larger cap and a change to `http_fetch` that drops caller headers when a redirect changes host. Found by the spec review of 166a560 (the lookup returns every location in a country and may exceed the cap; it is a GET carrying the Basic header, and `http_fetch` sends caller headers on every redirect hop; every brand has one locale, IN/en). Why: it removes a call, a cache, a failure mode and the credential exposure. Cost if wrong: a new country is a one-line change; "India" as the exact `location_name` is unconfirmed until the live check. Asked in chat.
- **R5: active competitors only.** Decided: `rivals` is the `domains` of the brand's active competitors; the user chose this over competitors of any status. Found by the spec review of 166a560: Section 2's reason, "as in the product run", was wrong (the product run collects competitors' names and aliases, not domains), `competitors.owner_of` uses active competitors only, and a model-suggested domain such as amazon.in would label every result on that host `competitor`. The choice was re-asked because the fact behind it was wrong. Why: matches the rule citations use. Cost if wrong: a real rival still at "suggested" shows as `other` until activated. Asked in chat.
- **R6: the page shows the latest job's status.** Decided: `GET /audits/serp` returns `{job, audits}` and the page shows a status line as the Products page does; missing credentials still write no rows; the user chose this over always writing error rows, and over both. Found by the spec review of 166a560 (a job that fails for missing credentials, budget or staleness writes no rows, so the page would say no audit has run). Why: one mechanism covers every job failure. Cost if wrong: the response is an object, not a list, and the route has one more query. Asked in chat.
- **R7: the spec review's other points were applied.** Decided:
  - `run_serp_audit` wraps its fetch and write steps and re-raises any failure as `SerpFailed` with the run's total spend; `process_job` maps `SerpFailed` to its code (the spec had left both to be guessed, and a failed write would have recorded a cost of 0).
  - `process_job` takes `serp_fetch: SerpFetch = http_fetch`; the credentials are read from `get_settings()` in `run_serp_audit`.
  - The adapter reads the top-level `status_code` first, then the task's.
  - A call that fails before a body is parsed has an unknown cost, recorded as 0; the 30-second deadline assumption and the worst-case duration are stated.
  - `classify` takes the provider's `domain`, with the URL as the fallback.
  - A featured snippet is stored and typed by host, and is not counted in `ownership`.
  - `fetched_at` is set by the worker per call.
  - `ix_serp_audit_latest` is dropped.
  - The cap, the default locale and `device` are described as forward-looking.
  - The PRD departures are listed in their own section.
  - `SerpResultOut`'s fields, lib/types.ts, the status-line labels and the fixture-title rule are stated.
  - The latest row is shown even when it is an error.
  - A `done` job is not requeued within its hour.
  - The facts about `_protect` and `process_job`'s error mapping are stated exactly.
  Found by the spec review of 166a560 (Important 1–3, 8, 9; Minor 10–19). Why: nothing for the plan writer to guess, and no spend lost on a failure. Cost if wrong: none beyond the items themselves. Named in chat when made.
- **R8: the re-review's seven minors were applied.** Decided: `tick` is unchanged; the worst-case duration is about 450 seconds (it had said 300, taking 30 seconds per call where a fetch can run about 45); `run_serp_audit` checks the credentials itself before reading anything, and the adapter checks them before the country, so a missing credential never leaves mixed error rows; the `run_products` citation points at the wrap (products.py:1321-1324), not its docstring; the status-code level is in the list of unconfirmed provider facts; the prose says a social host in either domain list takes every result on that host; `fetched_at` is not null and set for no-call errors too. Found by the re-review of bf07932 (finding 9 partly addressed; new findings A–G, all Minor). Why: accuracy, and nothing for the plan writer to guess. Cost if wrong: none. Named in chat when made.
- **R9: the plan review's points were applied to the plan; the trailer stays Fable 5.1.** Decided: the plan keeps "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>": the controller's latest attribution reminder still names Fable 5.1 (the reviewer's own session reminder named Opus 5.5, which the plan already tells an implementer to disregard). The six minors are applied: two red-step failure reasons are stated exactly, and the job-status test asserts the status code; the departures list drops a non-departure and names five small additions; Task 1's commit message says "rival", not "active rival"; Task 6 says the workspace is git-ignored; one test line is wrapped. Found by the plan review of d18b12a (1 Important, 6 Minor). Why: accuracy; R1 is checked against the controller's reminder, not a subagent's. Cost if wrong: none. Named in chat when made.

## Out of scope

- The weekly schedule; a report section and the Health Report's findings; the "Brand SERP change" alert; SERP-based recommendations.
- The `negative` type and the 0.9 accuracy benchmark.
- SerpApi as a fallback, with failover; retries, backoff and circuit breakers on provider errors.
- Mobile results; countries other than IN; matching social and video results to the brand's own profiles; brand aliases as extra queries.
- Storing the raw provider response; the queued (non-live) provider modes; a longer fetch deadline.
