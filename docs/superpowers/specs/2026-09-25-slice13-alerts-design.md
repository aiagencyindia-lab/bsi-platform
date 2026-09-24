# Slice 13 design: alerts (PRD F15, alerts only)

## Context

PRD F15 covers alerts, reports and agency mode. The repo has no users, no email or Slack, and no report rendering. Brainstorming with the user fixed the scope for slice 13 to alerts. Reports and agency mode are later slices.

Decisions approved in chat:

- **Three alert types**, each computed over rolling windows of stored observations, so nothing fires on a single observation:
  1. `mention_drop`: the brand's 7-day mention-rate delta carries the "decrease" label and the drop is at least 15 percentage points.
  2. `competitor_shift`: an entry in the existing visibility change feed, which already requires 10 or more moved prompts and a significant pooled delta.
  3. `new_source`: a third-party domain first cited in the last 7 days, in at least 5 answers. The count stands in for the PRD's authority threshold; the repo has no authority score.
- **Channels:** alerts are stored and listed on a new Alerts tab. A brand may set one HTTPS webhook URL; each new alert is POSTed to it as JSON with bounded retries. Slack incoming webhooks work through this. There is no email.
- **Cadence:** each brand is scanned once a day, using the same due-stamp pattern as the weekly recommendation refresh. A subject alerts once per rolling window. Webhooks fire per alert at once. Digest mode is deferred.
- **Preferences** are per brand, because there are no users.

Codebase facts the design rests on:

- `metrics.brand_deltas(s, brand_id, f, days, to)` returns before/after windows, a `comparable` flag and Newcombe deltas whose `label` is one of increase, decrease, no significant change, insufficient data.
- `competitors.visibility_changes(s, brand_id, f, days, to)` returns the feed entries with competitor id, direction, before/after rates, prompt ids and up to 20 observation ids.
- `citations.sources` labels a domain brand, rival or third_party from `domain.host` and active competitors' domains, with `matching.is_owned`.
- `crawl.http_fetch` is GET-only. Its SSRF guard checks scheme and port, resolves the host, requires every address to be public, pins the connection to that address with SNI and a Host header, and bounds time to 30 s and the body to 512 KiB.
- The worker's `main()` loop runs, once a minute, `run_due_schedules`, `close_due_impact_windows`, `refresh_due_recommendations`, `queue_due_crawl_audits` and `queue_due_rival_crawls`, each in its own try block. Due lists come from SECURITY DEFINER functions called from `system_session()`; per-brand work runs in `tenant_session(org_id)`; stamps use the database clock.
- No transaction may be open during an HTTP call. Tests prove this with a `pg_stat_activity` probe.

Planning ran on Fable 5.1 with the user's approval. Implementers and reviewers run on Opus 5.5 only.

## Design

### 1. Data

Migration `0016_alerts.py`:

- Table `alert`. Columns: `id`, `created_at`, `org_id` (as in earlier migrations), `brand_id` (FK brand), `type` (CHECK over `mention_drop`, `competitor_shift`, `new_source`), `subject_key`, `title`, `detail` jsonb default `{}`, `window_from` and `window_to` (timestamptz, not null), `delivered_at` (nullable), `delivery_attempts` (int, default 0), `next_attempt_at` (nullable; NULL means not for delivery), `last_error` (nullable text).
- Indexes: `(brand_id, type, subject_key, window_to DESC)` for dedupe; `(brand_id, created_at DESC)` for the list; a partial index on `next_attempt_at` where `delivered_at IS NULL AND next_attempt_at IS NOT NULL` for delivery.
- Row-level security with the `_protect()` helper copied into the migration, as every tenant table has.
- `brand.alerts_scanned_at` (timestamptz, nullable) and `brand.webhook_url` (text, nullable).
- `due_alert_scans()`: active brands whose stamp is NULL or older than one day, NULLS FIRST. `due_alert_deliveries()`: undelivered alerts with `next_attempt_at <= now()` whose brand is active and has a webhook, limit 100. Both SECURITY DEFINER with the same grants as `due_recommendation_refreshes()`.
- There is no delivery-log table. Attempts, the next attempt time and the last error live on the alert row. A log table is added only when a second channel or a per-attempt audit needs it.

`models.py` gains `Alert`, `ALERT_TYPES` and the two brand columns. `alert` joins `TENANT_TABLES` and the `org_b` fixture in the RLS tests; the CHECK gets a constraint test.

### 2. Detection (`bsi_core/alerts.py`)

Constants: `DROP_DAYS = 7`, `DROP_MIN_PTS = 0.15`, `SHIFT_DAYS = 14`, `SOURCE_DAYS = 7`, `NEW_SOURCE_MIN_ANSWERS = 5`. Evidence lists are capped at `citations.EVIDENCE_CAP` (20).

Each detector is `(s, brand_id, to) -> list[Candidate]`, where `Candidate` is a frozen dataclass of type, subject_key, title, detail, window_from and window_to. `to` is injected so tests are deterministic.

- **mention_drop.** From `brand_deltas(days=7)`: fire only when the windows are comparable, the mention-rate label is "decrease", and the delta value is at most −0.15. Subject `mention_rate`. Detail holds the before and after rates and the delta. The window is the after window.
- **competitor_shift.** One candidate per feed entry from `visibility_changes(days=14)`. Subject `<competitor_id>:<direction>`. Detail holds competitor id and name, direction, before and after rates, delta, prompt ids and observation ids. The window is split to `to`.
- **new_source.** One SQL statement with bound `brand`, `from`, `to` and `min`. A domain's first citation is the earliest `requested_at` over all done answers before `to`, so a domain seen a year ago is never new. The domain qualifies when that first citation falls in `[from, to)` and at least `min` distinct answers cite it inside the window. Observation and prompt id arrays are capped at 20. Brand-owned and rival domains are dropped afterwards with `matching.is_owned` against the brand's hosts and the active competitors' domains. Subject is the domain.

**Dedupe.** A candidate is skipped when an alert exists with the same brand, type and subject whose `window_to` is later than the candidate's `window_from`. Windows of one type have one length, so this is exactly "the previous alert is younger than the window".

**Copy.** Three templates, for example "Mention rate fell 18.0 points over the last 7 days (52.0% to 34.0%)", "Adidas was named more often on 11 prompts over the last 14 days", "forbes.com was cited in 6 answers, the first time in the last 7 days". The cases join `tests/unit/test_recommend_copy.py`, so the forbidden-word rule applies to alert titles too.

**`scan(s, org_id, brand_id, to, *, deliver)`** runs the detectors, drops deduped candidates, inserts the rest with `next_attempt_at = now()` when `deliver` is true and NULL otherwise, flushes and returns the new rows. An alert created while the brand has no webhook is never delivered later, even if a webhook is set afterwards.

**`payload(alert, brand_name)`** returns id, type, brand_id, brand, title, `text` (equal to the title, which is what a Slack incoming webhook renders), subject_key, window_from, window_to, created_at and detail. It is serialised with `json.dumps(default=str)`.

### 3. Outbound POST

`crawl.http_fetch` gains keyword-only `method` (default GET), `body` and `content_type`. The request uses the method and body, and a Content-Type header when given. Redirects are followed only for GET; a POST that receives a 3xx returns it as a non-ok response. Nothing in the guard changes: scheme and port checks, public-address requirement, pinned connection with SNI, deadline and body cap apply to POST as to GET.

### 4. Worker

- **`scan_due_alerts()`** sits beside `refresh_due_recommendations`. It reads the due brands through `due_alert_scans()`, and for each one, inside `tenant_session(org_id)`, reads `webhook_url`, calls `scan` with `to = now`, and stamps `alerts_scanned_at` from the database clock. One brand's failure never stops the others. It runs inline rather than as a job because it is SQL-only, costs nothing and takes well under a second per brand.
- **`deliver_due_alerts(fetch=http_fetch)`** reads due alert ids through `due_alert_deliveries()`. For each alert: a tenant session reads the alert and the brand's name and webhook URL, builds the payload, and closes. The POST runs with no session open. A second tenant session then increments `delivery_attempts` and records either success (`delivered_at`, `next_attempt_at` NULL, `last_error` NULL) or failure (`last_error` from the response's error or "HTTP <status>", cut to 2,000 characters). After a failure, `next_attempt_at` is now plus the backoff for that attempt: 1 minute, 5 minutes, 30 minutes, 2 hours. After the fifth failed attempt `next_attempt_at` becomes NULL and the alert is given up, with `last_error` kept. A refused URL, for example one whose host resolves to a private address, walks the same schedule; five attempts bound it. One alert's failure never stops the others, and the function never raises.
- `main()` calls `scan_due_alerts()` and then `deliver_due_alerts()` in the minute block after `queue_due_rival_crawls()`, each in its own try block.

### 5. API

- New router `alerts.py` under `/brands/{brand_id}`:
  - `GET /alerts?limit=50` (1 to 200) returns alerts newest first, then by id. A foreign brand returns 404.
  - `POST /alerts/scan` runs `scan` inline with `to = now` and returns `{created: n}`. It does not stamp `alerts_scanned_at`, so the daily scan still runs.
- `AlertOut` exposes every alert column; `ScanOut` has `created`.
- `BrandPatch.webhook_url` is optional and nullable, so an explicit null clears it. The validator accepts only `https`, a hostname that passes `is_public_hostname`, port 443 or none, no userinfo, and at most 2,000 characters. `BrandOut` returns it.
- Isolation tests get rows for both alert routes with a foreign alert in the fixture.

### 6. Web

- An Alerts tab in the brand layout.
- The page is a Server Component. At the top: a form with a URL input (`type="url"`, pattern `https://.*`), Save and Clear, and a "Scan now" form. Feedback uses `?queued=` with an `alertNote()` helper built on `note()`. Below: a table with a type tag, the title, the window, evidence links (prompt ids link to the prompt page, observation ids to the observation page, a domain is plain text because it is not an http(s) URL) and a delivery column reading delivered, pending n/5, failed with the last error, or a dash when there is no webhook.
- Server actions: `setWebhook` PATCHes `{webhook_url}` or null; `scanNow` POSTs the scan.
- `ALERT_KIND` and `alertNote` in `format.ts` with vitest cases; `Alert` in `types.ts`; regenerated `openapi.json` and `schema.d.ts` committed.

### 7. Testing

- Unit: `payload` shape; copy templates through the forbidden-word cases; three `http_fetch` POST tests (body and Content-Type sent with the pinned Host; a 302 on POST makes one request and returns 302; a private host is refused for POST).
- Integration, with seeded observations at explicit `requested_at` values and a fixed `to`: each detector's fire and no-fire cases (threshold, incomparable windows, brand and rival domains skipped, an old domain is not new); dedupe within a window and re-fire after it; `next_attempt_at` set only with a webhook.
- Worker: a brand is due again after a day (backdated through the database clock); every tenant is served; the payload is POSTed and the alert marked delivered; the backoff schedule then give-up; a refused host is recorded; no transaction is open during the POST; one failing delivery does not block the rest.
- API: list order and limit; scan count; webhook validation cases; null clears. RLS and isolation rows.

### 8. Live check

Read-only for dev: with the API running the branch, `POST /alerts/scan` on Run 1, then `GET /alerts`. Run 1's 100 answers fall inside 4 days, so the feed is empty and `competitor_shift` stays quiet; `mention_drop` and `new_source` are reported as observed. The worker is not started.

## Rulings

Each is listed to the user with its cost if wrong.

- **Inline daily scan, not a job.** Cost: a slow tenant delays the minute loop; convert to a job later.
- **No delivery-log table.** Cost: no per-attempt audit; only the last error is kept.
- **Alerts created before a webhook is set are never delivered.** Cost: a user who sets the URL later expects yesterday's alerts and does not get them.
- **`new_source` fires at 5 answers, with no authority score.** Cost: noisy alerts from one popular prompt; raise the constant or require two distinct prompts.
- **A 15-point floor on top of the significance label.** Cost: small brands may never alert; silence, not noise.
- **No webhook signing.** Cost: a consumer cannot authenticate the sender; add an HMAC header later.
- **`http_fetch` gains method and body.** Cost: a guard regression would affect crawling; the existing fetch tests cover the guard.
- **Slack renders only `text`.** The rest of the JSON is for other consumers.

## Out of scope

Reports, PDF, share links, white-label, agency mode, email, per-user preferences, digest mode, negative-mention clusters, Brand SERP alerts, citation authority.
