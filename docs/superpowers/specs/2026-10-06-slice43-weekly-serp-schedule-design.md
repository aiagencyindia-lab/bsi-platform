# Slice 43 design: the weekly Brand SERP schedule (PRD F09)

## Context

Codebase facts: main `dbcb2df`, checked 2026-10-06.

PRD F09's acceptance criterion is "report generated weekly". Today the Brand SERP audit runs only when the operator presses "Run audit now" (`POST /brands/{id}/audits/serp`, which queues an `audit_serp` job). This slice makes the worker queue that job weekly. The "Brand SERP change" alert is slice 44: it needs stored weekly pages to compare, and the 2026-10-05 live check (findings-slice37 §2) saw the same query return 0/3 and then 1/6 ownership 20 minutes apart, so its rule is designed later against the pages this slice stores.

Facts the design rests on:
- apps/workers/bsi_workers/worker.py: `queue_due_crawl_audits()` and `queue_due_rival_crawls()` already queue weekly jobs. Each reads a `SECURITY DEFINER` SQL function (`due_crawl_audits()`, migration 0012; `due_rival_crawls()`, migration 0015) in a system session, because the worker's role `bsi_app` is subject to row-level security and cannot read across organisations. Each calls `enqueue_job(..., requeue_failed=False)`, one job per (brand, kind, hour). The worker loop calls them once a minute.
- `run_serp_audit()` writes one `serp_audit` row per query, error rows included, and then fails the job if every row has an error. With no DataForSEO credentials it raises `SerpFailed("serp_not_configured", 0)` and writes no rows; a `budget` or `stale` failure writes no rows either.
- `process_job()` checks the daily budget when it claims the job (`JOB_ESTIMATES["audit_serp"]` = 40,000 micros). Two calls were observed to cost $0.002 each on 2026-10-05 (4,000 micros an audit).
- apps/api/bsi_api/routers/brands.py: a brand is created by `POST /brands`; its domains are added afterwards by `POST /brands/{id}/domains`. `classify()` (packages/core/bsi_core/serp.py) types a result `official` only when its host matches a declared domain.
- `serp_audit` has one index, on `org_id` (migration 0023). The dev database holds 10 rows.

Classification: **architectural** — a new weekly schedule adds a recurring spend path to the worker. It was said in chat before the first brainstorming question, after the brainstorming skill loaded and the context reads; one line of progress text came before it, so it was not the first line of the first reply.

Decisions approved in chat (brainstorming on Opus 5.5, then Fable 5.1 after the session model changed, 2026-10-06), each after approaches with trade-offs and a recommendation written in a chat message before the question:
1. Two slices: the schedule (this one), then the alert; over one slice, or the alert first.
2. Every active brand is audited automatically; over a per-brand opt-in, or only brands with an active measurement schedule.
3. A daily retry: due until a good page exists, with at most one attempt a day; over an hourly retry, or one attempt a week whatever the result.
4. A SQL function plus a worker sweep; over extending the `schedule` table, or a timestamp column on `brand`.
5. A brand needs at least one declared domain; over leaving the rule as first approved, or waiting a day after the brand is created. This was asked after Section 1 was approved: the controller found while writing this spec that a brand exists before its domains, so the approved rule would audit a new brand within a minute and class its own site `other` for a week.

Design Sections 1, 2 and 3 were approved in chat, the text of each shown before its approval question. Plan mode was on from the middle of the brainstorm, so the approved design was also saved to a plan file and approved there. That plan file predates decision 5 and ruling R2: it lists four conditions and "1708 + 14" tests.

## Design

### Migration 0024: `due_serp_audits()`

A new file, migrations/versions/0024_due_serp_audits.py. It creates one function and no table, column or index, so tests/integration/test_rls.py and test_isolation.py need no new rows:

```python
"""due_serp_audits(): the weekly Brand SERP audit (slice 43, PRD F09)"""

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

AUDIT_DAYS = 7
RETRY_DAYS = 1
KINDS = 2  # len(models.SERP_KINDS): brand, reviews


def upgrade() -> None:
    op.execute(f"""
        CREATE FUNCTION due_serp_audits()
        RETURNS TABLE(brand_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          -- Due when a brand with a declared domain (without one its
          -- own site cannot be recognised) has a query kind with no
          -- error-free page in the window, unless an audit_serp job was
          -- created in the last day or one is still waiting: a failure
          -- is retried once a day at most.
          -- ponytail: serp_audit is scanned by brand_id; add an index on
          -- (brand_id, kind, fetched_at) when the table grows.
          SELECT b.id, b.org_id FROM brand b
          WHERE b.status = 'active'
            AND EXISTS (SELECT 1 FROM domain d WHERE d.brand_id = b.id)
            AND (SELECT count(DISTINCT a.kind) FROM serp_audit a
                 WHERE a.brand_id = b.id AND a.error IS NULL
                   AND a.fetched_at
                       > now() - make_interval(days => {AUDIT_DAYS})) < {KINDS}
            AND NOT EXISTS (
              SELECT 1 FROM job j
              WHERE j.brand_id = b.id AND j.kind = 'audit_serp'
                AND (j.created_at > now() - make_interval(days => {RETRY_DAYS})
                     OR j.status IN ('queued', 'running')))
          ORDER BY b.id
        $$""")
    op.execute("REVOKE ALL ON FUNCTION due_serp_audits() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_serp_audits() TO bsi_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION due_serp_audits()")
```

A brand is due when all five hold:
1. It is active.
2. It has at least one declared domain (decision 5).
3. Fewer than two of the query kinds (`brand`, `reviews`) have a row with no error fetched in the last 7 days.
4. No `audit_serp` job for it was created in the last 24 hours, whatever the job's status.
5. No `audit_serp` job for it is `queued` or `running`, however old. Without this, a worker that is down for over a day would stack a second job for the brand.

Consequences:
- A manual audit counts: after "Run audit now" on a Tuesday, the next automatic audit is the following Tuesday.
- A partial success (one query failed) leaves the brand due; the retry a day later re-runs both queries.
- A good page with zero results counts as a page; only an error makes it count as missing.
- Locale is ignored: good pages from an old locale still count in the week after a brand's first locale changes.
- A brand with no domain is audited only by "Run audit now". A domain added later to a brand that already has one is picked up at the next weekly audit.
- A failure on `budget` is retried a day later, at about the same time of day.
- The order is by brand id. Every due brand is queued in the same sweep, so "oldest first" would change nothing.
- `serp_audit` is scanned by `brand_id`; the function's comment names an index on `(brand_id, kind, fetched_at)` as the upgrade.

### The worker sweep

apps/workers/bsi_workers/worker.py, as a diff against main `dbcb2df`:

```diff
@@ -828,4 +828,44 @@ def queue_due_crawl_audits() -> int:
 
 
+def queue_due_serp_audits() -> int:
+    """Queue a Brand SERP audit for every brand due one; returns how many.
+
+    Same contract as queue_due_crawl_audits, with one difference: with
+    no DataForSEO credentials nothing is queued. The job would fail as
+    serp_not_configured and write no rows, so every active brand would
+    get one failed job a day.
+
+    ponytail: every due brand is queued in one sweep and jobs run one at
+    a time ahead of observations; spread the audits across the week when
+    there are a few hundred brands.
+    """
+    settings = get_settings()
+    if not (
+        settings.dataforseo_login
+        and settings.dataforseo_password.get_secret_value()
+    ):
+        return 0
+    with system_session() as s:
+        due = s.execute(
+            text("SELECT brand_id, org_id FROM due_serp_audits()")
+        ).all()
+    queued = 0
+    for brand_id, org_id in due:
+        try:
+            with tenant_session(org_id) as s:
+                enqueue_job(
+                    s,
+                    org_id,
+                    brand_id,
+                    "audit_serp",
+                    {},
+                    requeue_failed=False,
+                )
+            queued += 1
+        except Exception:
+            log.exception("brand %s serp audit queue failed", brand_id)
+    return queued
+
+
 def _record_failure(
     org_id: uuid.UUID, obs_id: uuid.UUID, error: str, retryable: bool
@@ -1225,4 +1265,8 @@ def main() -> None:
             except Exception:
                 log.exception("queue_due_rival_crawls failed")
+            try:
+                log.info("queued %d serp audits", queue_due_serp_audits())
+            except Exception:
+                log.exception("queue_due_serp_audits failed")
             try:
                 log.info("scanned %d brands for alerts", scan_due_alerts())
```

The sweep is a copy of `queue_due_crawl_audits()` with the credentials check added (R1). Unlike the crawl sweep, a second call in the same hour returns 0: the job the first call queued makes the brand not due (condition 5).

Unchanged: `run_serp_audit()`, `SERP_JOB_MICROS`, `MAX_SERP_LOCALES`, the API routes and schemas (no `npm run gen`). A scheduled job and a manual one look the same in the `job` table.

The first sweep after the merge queues every due brand at once. Jobs run one at a time, ahead of observations; a SERP job was observed to take about 22 seconds (9.27 s and 13.13 s for its two calls on 2026-10-05) and can take about 8 minutes at worst. Spreading audits across the week is left out, with a `ponytail:` comment naming it.

### The Brand SERP page

apps/web/src/app/(app)/b/[id]/serp/page.tsx:

```diff
@@ -32,4 +32,5 @@ export default async function Serp({
         )}
       </form>
+      <p className="muted">Audited automatically once a week.</p>
       {status && <p className="muted">{status}</p>}
       {audits.length === 0 && (
```

The sentence is copy only: no new data and no test. It was the controller's addition, approved with Section 2. It is shown for every brand, including one with no domain, which is not audited automatically (see "Deferred minors").

## Testing

Fifteen tests are appended to tests/integration/test_serp_audit.py; three are parametrized over two values, so the suite gains 18 test items (R2). No test makes a network call. The file's imports gain `timedelta` and `system_session`.

1. `test_a_brand_with_no_pages_and_no_jobs_is_due`
2. `test_a_brand_with_no_domain_is_not_due_until_one_is_declared`
3. `test_good_pages_for_both_queries_this_week_are_not_due`
4. `test_due_again_once_the_pages_are_over_seven_days_old`
5. `test_one_good_page_and_one_failed_page_is_due`
6. `test_a_good_page_with_no_results_counts`
7. `test_a_job_in_the_last_day_blocks_whatever_its_status`
8. `test_a_waiting_job_blocks_however_old`
9. `test_a_job_of_another_kind_does_not_block`
10. `test_archived_brands_are_never_due_for_a_serp_audit`
11. `test_due_serves_every_tenant_in_brand_id_order`
12. `test_the_sweep_queues_one_job_per_due_brand_once`
13. `test_the_sweep_retries_a_failed_audit_after_a_day_not_before`
14. `test_the_sweep_queues_nothing_without_credentials`
15. `test_a_swept_job_stores_the_pages_and_the_brand_is_no_longer_due`

Expected gates: backend `1726 passed, 2 deselected` (1708 on main plus 18) with metrics coverage at 100%; web 49 vitest, unchanged.

### Proof

Run 2026-10-06 in the scratchpad on copies of main's files, against the shared test database (R3). The edit pairs, the migration text and the tests in this spec are the ones the run used.

- Red, main's code with the new tests: `18 failed, 11 passed` (the 11 are the file's existing tests).
- Green, patched: `29 passed`.
- `ruff check` and `ruff format --check` pass on the patched worker, the test file and the migration file.
- Not run in the proof: the migration file through alembic (the function's SQL was installed by a proof-only plugin from the same text), `mypy` (it covers `packages/core` only, which this slice does not touch), and the web gate.

Each rule has a mutant that fails a test:

| Mutant | Change | Failed | Failing tests |
|---|---|---|---|
| M1 | condition 1 dropped: archived brands are listed | 1 | `test_archived_brands_are_never_due_for_a_serp_audit` |
| M9 | condition 2 dropped: a brand with no domain is listed | 1 | `test_a_brand_with_no_domain_is_not_due_until_one_is_declared` |
| M2a | condition 3: an error page counts as a page | 1 | `test_one_good_page_and_one_failed_page_is_due` |
| M2b | condition 3: rows are counted, not distinct kinds | 1 | `test_one_good_page_and_one_failed_page_is_due` |
| M2c | condition 3: no 7-day window | 1 | `test_due_again_once_the_pages_are_over_seven_days_old` |
| M2d | condition 3: one good kind is enough | 2 | `test_due_again_once_the_pages_are_over_seven_days_old`, `test_one_good_page_and_one_failed_page_is_due` |
| M3a | condition 4 dropped: no 24-hour rule | 3 | `test_a_job_in_the_last_day_blocks_whatever_its_status[done]`, `test_a_job_in_the_last_day_blocks_whatever_its_status[failed]`, `test_the_sweep_retries_a_failed_audit_after_a_day_not_before` |
| M3b | conditions 4 and 5: a job of any kind blocks | 1 | `test_a_job_of_another_kind_does_not_block` |
| M3c | condition 4: the retry wait is 7 days | 5 | `test_a_job_in_the_last_day_blocks_whatever_its_status[done]`, `test_a_job_in_the_last_day_blocks_whatever_its_status[failed]`, `test_a_waiting_job_blocks_however_old[queued]`, `test_a_waiting_job_blocks_however_old[running]`, `test_the_sweep_retries_a_failed_audit_after_a_day_not_before` |
| M4 | condition 5 dropped: an old waiting job does not block | 2 | `test_a_waiting_job_blocks_however_old[queued]`, `test_a_waiting_job_blocks_however_old[running]` |
| M5 | no ORDER BY | 1 | `test_due_serves_every_tenant_in_brand_id_order` |
| M6 | R1 dropped: the sweep queues without credentials | 2 | `test_the_sweep_queues_nothing_without_credentials[login]`, `test_the_sweep_queues_nothing_without_credentials[password]` |
| M7 | R1: only the login is checked | 1 | `test_the_sweep_queues_nothing_without_credentials[password]` |
| M8 | R1: only the password is checked | 1 | `test_the_sweep_queues_nothing_without_credentials[login]` |

## Rulings

Quoted from the ledger:

> Ruling: R1. Decided: queue_due_serp_audits() returns 0 without reading the due list when the DataForSEO login or password is empty. Found by: the controller, while reading run_serp_audit during brainstorming (a job with no credentials fails as serp_not_configured and writes no rows, so the brand stays due). Why: otherwise every active brand gets one serp_not_configured failed job a day, forever. Cost if wrong: a missing-credentials setup is silent in the job list; "Run audit now" still reports it. How named: in chat in the Section 2 design text, 2026-10-06, and approved with Section 2.

> Ruling: R2. Decided: three of the 15 new tests are parametrized over two values (job status failed/done; job status queued/running; missing login/password), so the suite gains 18 test items and the expected backend count is 1726, not the plan file's "1708 + 14". Found by: the controller, writing the scratch proof. Why: each value is a separate rule a mutant can break (M7 and M8 each fail exactly one of the two credential cases). Cost if wrong: none to behaviour; a count in the approved plan file is superseded. How named: in chat, 2026-10-06, after the proof run.

> Ruling: R3. Decided: the scratch proof installed due_serp_audits() in the shared test database bsi_test through a proof-only pytest plugin and dropped it at the end of each session; the count of functions of that name was read as 0 afterwards. Found by: the controller, setting up the proof. Why: tests/conftest.py applies the repo's migrations, and a scratch copy cannot add migration 0024 to them. Cost if wrong: a leftover function would make migration 0024's CREATE FUNCTION fail in the test session. How named: in chat, 2026-10-06, after the proof run.

## Deferred minors

- The page sentence "Audited automatically once a week." is also shown for a brand with no declared domain, which the sweep skips. Found by the controller while writing this spec; not fixed, because the sentence is static copy approved before decision 5.

## Live check (after merge, ask first)

Migrate dev to 0024 (ask first), call `queue_due_serp_audits()` once, then `process_job` once per queued job with a `serp_fetch` wrapper that prints only statuses, codes, costs, item counts and latency. The worker loop is never started. Expected, *inferred*: one brand is due (`BSOAgentTestBrand` `34db213a`, the only test brand with a domain); Walkaroo has good pages from 2026-10-05 and is not due until 2026-10-12; 1 job, 2 searches, about $0.004.
