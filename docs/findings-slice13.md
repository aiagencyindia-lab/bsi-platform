# Findings: slice 13 — alerts

## 1. What was built

**Schema.** Migration 0016 adds the tenant table `alert` (type, subject, title, JSON detail, the window, and delivery state: `delivered_at`, `delivery_attempts`, `next_attempt_at`, `last_error`) with row-level security, a dedupe index, a list index and a partial delivery index. `brand` gains `alerts_scanned_at` and `webhook_url`. Two SECURITY DEFINER functions list the work: `due_alert_scans()` (active brands not scanned for a day, never-scanned first) and `due_alert_deliveries()` (up to 100 undelivered alerts that are due, on active brands with a webhook).

**Detectors.** `packages/core/bsi_core/alerts.py` has three detectors over rolling windows. `mention_drop` fires when the 7-day mention-rate delta is labelled "decrease" and is at least 15 points. `competitor_shift` turns each entry of the 14-day visibility change feed into an alert. `new_source` fires for a third-party domain first cited in the last 7 days in at least 5 answers, and only when the brand's earliest done answer is at least 14 days old, a full window before the current one (see §2). A subject alerts once per window. `scan` inserts the new alerts and marks them for delivery only when the brand has a webhook; `payload` builds the JSON body, with `text` equal to the title for Slack.

**Fetch POST.** `crawl.http_fetch` takes `method`, `body` and `content_type`. Redirects are followed for GET only; a 3xx to a POST is returned as is. The SSRF guard, the pinned connection, the 30 s deadline and the 512 KiB cap are unchanged.

**Worker.** `scan_due_alerts()` scans each due brand inline and stamps it from the database clock. `deliver_due_alerts()` POSTs each due alert with no session open, then records success, or the error and the next attempt: 1 minute, 5 minutes, 30 minutes, 2 hours, then give up after the fifth failure. Both run once a minute after `queue_due_rival_crawls()`, each in its own try block.

**API.** `GET /v1/brands/{id}/alerts` lists alerts newest first (limit 1–200, default 50). `POST /v1/brands/{id}/alerts/scan` scans at once and returns the count created; it does not move the daily stamp. `PATCH` on the brand accepts `webhook_url`: HTTPS only, a public hostname, port 443 or none, no user info, up to 2,000 characters; null clears it.

**Web.** A new Alerts tab has a webhook form (Save, Clear), a "Scan now" button and a table of alerts: type, title, window, evidence links to prompts and answers, and the delivery state (delivered, pending n/5, failed with the error, or a dash when there is no webhook).

## 2. Live check

Run at 2026-09-24 20:58 UTC (the detectors' `to`), read-only on dev: the detectors ran in a tenant session that was rolled back, so nothing was written. Dev was still at migration 0015. No webhook was set, the scan route was not called, and the worker was not started.

| Detector | Result on Run 1 |
|---|---|
| `new_source` (before the baseline guard) | `detect_new_source` returned 54 candidates. Top: youtube.com (41 answers), forbes.com (29), wearetto.com (23), starkidz.co.in (22). |
| `competitor_shift` | 0 |
| `mention_drop` | Could not run on dev (see below). |

**What this shows:**
- **Every cited domain looked "new".** Run 1's 100 answers all fall between 2026-09-19 and 2026-09-22, inside the 7-day window, so every domain's first citation was inside it too. The scan route was not called, so no alerts were stored or posted; a first scan with a webhook would have queued all 54.
- **Fix: `new_source` now needs a full window of history.** It returns nothing unless the brand's earliest done answer is at or before `to` minus 14 days. One older answer is not enough: it would only delay the flood. This was not re-run on dev; as a consequence of the code, Run 1's earliest answer is 2026-09-19 09:17 UTC, so new-source alerts stay off for it until 2026-10-03 09:17 UTC, and by then the 7-day window holds no Run 1 answers unless new runs happen.
- **`mention_drop` needs migration 0016 to run.** The ORM loads the brand with its new columns, and `brand_deltas` reads the brand, so the query fails on a database at 0015. Run 1 has 0 answers before the 7-day window, so the result would be "insufficient data" and no alert.
- **Dev must be upgraded to 0016 before the merged code runs there**, as with every migration.

## 3. Deferred / decisions

From the spec:
- The daily scan runs inline in the worker loop, not as a job. A slow tenant delays the minute loop.
- No delivery-log table; only the last error is kept on the alert.
- Alerts created before a webhook is set are never delivered, even after the webhook is set.
- `new_source` fires at 5 answers; there is no authority score. One popular prompt can make it noisy.
- A 15-point floor applies on top of the significance label, so small brands may never get a mention-drop alert.
- No webhook signing; a consumer cannot authenticate the sender.
- `http_fetch` gained method and body; a guard regression would affect crawling too.
- Slack renders only `text`; the rest of the JSON is for other consumers.

Rulings during the build:
- Ruling 1: the list index on `(brand_id, created_at)` was added; the plan had dropped it. Cost if wrong: one unused index.
- Ruling 2: there is no alembic drift test; the reviewer checked the model against the migration by reading. Cost if wrong: drift shows up only on a future autogenerate.
- Ruling 3: a scan test was renamed so its name no longer promises a re-fire it does not test; the re-fire rule is tested by `test_is_duplicate_matches_only_a_younger_alert_of_the_same_subject`. Cost if wrong: none.
- Ruling 4: indexes are ascending, not `DESC` as the spec wrote; a btree scans backwards. Cost if wrong: none measurable.
- Ruling 5: the isolation tests do not count org B's alerts after cross-tenant requests. Cost if wrong: a write leak on the alert routes would go unasserted.
- Ruling 6: an exception inside `deliver_due_alerts` is not counted as an attempt, so that alert retries every minute. Cost if wrong: a poisoned alert retries forever and takes one of the 100 slots.
- Ruling 7: delivery runs inline, up to 100 POSTs of up to 30 s each; two worker processes could post twice. Cost if wrong: a slow webhook stalls the minute loop.
- Ruling 8: a 422 from the webhook PATCH shows the generic error page, not a field message. Cost if wrong: an operator sees an error page for a private host.
- Ruling 9: the live check ran the detectors in a rolled-back session instead of calling the scan route, which writes and needs 0016. Cost if wrong: the route and dedupe were not exercised on real data; the tests cover them.
- Ruling 10: alert copy is plain strings, checked by a separate forbidden-word test. Cost if wrong: alert titles have no "Metric to watch" line (the spec does not require one).
- Ruling 11 (amended after the review): the baseline is a full window of history. `new_source` returns nothing unless the brand's earliest done answer is at or before `to` minus 14 days; one old answer only delayed the flood (Run 1 would have flooded again from about 2026-09-26 09:17 UTC). Cost if wrong: a new brand gets no new-source alerts for its first 14 days of history.
- Ruling 12: final-review minor 3 stays deferred under Ruling 7. One slow webhook with N due alerts costs up to N x 30 s in one pass. Cost if wrong: a dead webhook with many due alerts delays every tenant's schedule checks.
- Clearing the webhook stops pending deliveries: `PATCH {"webhook_url": null}` sets `next_attempt_at` to null on the brand's undelivered alerts, so they are not posted to a URL set later. A POST already in flight is handled too: if it fails, the worker re-reads the brand's webhook under a row lock and, if it is still cleared when the attempt is recorded, records the attempt and error but sets no next attempt.
- Ruling 13: a delivery that fails after the webhook was cleared mid-POST is given up rather than rescheduled (fixed in code, not documented as a caveat). Cost if wrong: one extra locking read per failed delivery.
- Ruling 14: one narrow case remains. If, during a single in-flight POST of up to 30 s, the operator clears the webhook and then sets a new URL before the worker records the failure, the alert is rescheduled and later posted to the new URL. Accepted, not fixed. Cost if wrong: one alert reaches a webhook set moments after the old one was cleared.
- Scans of one brand are serialised by a transaction advisory lock (`alert-scan:<brand_id>`), so a manual scan and the daily scan cannot both pass the dedupe and insert twice.
- The webhook POST sends the user agent `bsi-platform-alerts/1.0`, not the browser user agent.

Minor items deferred from the task reviews:
- No test that `due_alert_deliveries()` skips archived brands.
- No test of the never-scanned-first order in `due_alert_scans()`.
- `new_source` evidence keeps the 20 lowest answer ids, not the 20 most recent; prompt ids are capped separately. This matters only above 20 citing answers.
- No test that a suggested competitor's domain still counts as a new source.
- `http_fetch`'s `method` is a plain string, not limited to GET and POST.
- No test that Content-Type is absent when none is given.
- No worker test that the daily scan marks alerts for delivery only when the brand has a webhook.
- No test that one brand's failed scan leaves the others scanned and itself unstamped.
- The worker's `Poster` protocol sits among the constants (cosmetic).
- The webhook validator lets empty user info through (`https://@host/`); the host is still checked, and `http_fetch` checks it again at send time.
- No API test for scanning a brand with a webhook, or for the 2,000-character limit.
- Evidence links all read "prompt" or "answer", so they share accessible names.
- The "/5" in the delivery column repeats `MAX_DELIVERY_ATTEMPTS` by hand.
- The web page's `delivery()` and `ids()` helpers have no tests.

## 4. Not covered by tests
- The Alerts page rendering (the web app has no component tests).
- The migration downgrade, which was checked by reading only.
- No delivery was tried against a real webhook endpoint (Slack or other); delivery is tested only with a fake fetch. Slack compatibility rests on the documented `text` field only.
- No test runs two scans concurrently; the advisory lock was checked by reading and by the sequential scan tests, which run as `bsi_app` under RLS.
