# Slice 43 design: the weekly Brand SERP schedule (PRD F09)

## Context

Codebase facts: main `dbcb2df`, checked 2026-10-06.

PRD F09's acceptance criterion is "report generated weekly". Today the Brand SERP audit runs only when the operator presses "Run audit now" (`POST /brands/{id}/audits/serp`, which queues an `audit_serp` job). This slice makes the worker queue that job weekly. The "Brand SERP change" alert is slice 44: it needs stored weekly pages to compare, and the 2026-10-05 live check (findings-slice37 §2) saw the same query return 0/3 and then 1/6 ownership 20 minutes apart, so its rule is designed later against the pages this slice stores.

Facts the design rests on:
- apps/workers/bsi_workers/worker.py: `queue_due_crawl_audits()` and `queue_due_rival_crawls()` already queue weekly jobs. Each reads a `SECURITY DEFINER` SQL function (`due_crawl_audits()`, migration 0012; `due_rival_crawls()`, migration 0015) in a system session, because the worker's role `bsi_app` is subject to row-level security and cannot read across organisations. Each calls `enqueue_job(..., requeue_failed=False)`, one job per (brand, kind, hour). The worker loop calls them at most once a minute.
- `run_serp_audit()` writes one `serp_audit` row per query, error rows included, and then fails the job if every row has an error. With no DataForSEO credentials it raises `SerpFailed("serp_not_configured", 0)` and writes no rows. A `budget` failure writes no rows. A job that `claim_job()` fails as `stale` after 10 minutes can still write its rows when the attempt finishes late (`_finish_job` discards only the outcome).
- Failures that repeat on every run: packages/core/bsi_core/providers/dataforseo.py knows one location (`LOCATIONS = {"IN": "India"}`), so a brand whose first locale is another country fails as `location` each time at no cost; a paused, unfunded or wrongly authenticated account fails every brand at no cost; a timeout is recorded at `TIMEOUT_MICROS` = 2,000 micros a call.
- `process_job()` checks the daily budget when it claims the job (`JOB_ESTIMATES["audit_serp"]` = `SERP_JOB_MICROS` = 40,000 micros). The budget is per UTC day and observations still to run count against it (packages/core/bsi_core/scheduling.py, `budget_fits`). Two calls were observed to cost $0.002 each on 2026-10-05 (4,000 micros an audit).
- apps/api/bsi_api/routers/brands.py: a brand is created by `POST /brands`; its domains are added afterwards by `POST /brands/{id}/domains`. `classify()` (packages/core/bsi_core/serp.py) types a result `official` only when its host matches a declared domain.
- `serp_audit` has its primary key and an index on `org_id` (migration 0023), and none on `brand_id`. The dev database holds 10 rows.

Classification: **architectural** — a new weekly schedule adds a recurring spend path to the worker. It was said in chat before the first brainstorming question, after the brainstorming skill loaded and the context reads; one line of progress text came before it, so it was not the first line of the first reply.

Decisions approved in chat (brainstorming on Opus 5.5, then Fable 5.1 after the session model changed, 2026-10-06), each after approaches with trade-offs and a recommendation written in a chat message before the question:
1. Two slices: the schedule (this one), then the alert; over one slice, or the alert first.
2. Every active brand is audited automatically; over a per-brand opt-in, or only brands with an active measurement schedule.
3. A daily retry: due until a good page exists, with at most one attempt a day; over an hourly retry, or one attempt a week whatever the result.
4. A SQL function plus a worker sweep; over extending the `schedule` table, or a timestamp column on `brand`.
5. A brand needs at least one declared domain; over leaving the rule as first approved, or waiting a day after the brand is created. This was asked after Section 1 was approved: the controller found while writing this spec that a brand exists before its domains, so the approved rule would audit a new brand within a minute and class its own site `other` for a week.
6. At most three failures a week: a brand is not due once it has 3 failed `audit_serp` jobs in the last 7 days; over leaving the daily retry unbounded, or skipping brands whose first locale is not India. Asked after the spec review's finding 1.
7. The sweep checks the budget before it queues and creates no job when the estimate does not fit; over leaving a `budget` failure to the 24-hour rule, or exempting `budget` failures from the rules. Asked after the spec review's finding 2.

Design Sections 1, 2 and 3 were approved in chat, the text of each shown before its approval question. Plan mode was on from the middle of the brainstorm, so the approved design was also saved to a plan file and approved there. That plan file predates decisions 5, 6 and 7 and the count correction below: it lists four conditions and "1708 + 14" tests.

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
MAX_FAILURES = 3  # failed audit_serp jobs in AUDIT_DAYS


def upgrade() -> None:
    op.execute(f"""
        CREATE FUNCTION due_serp_audits()
        RETURNS TABLE(brand_id uuid, org_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
          -- Due when a brand with a declared domain (without one its
          -- own site cannot be recognised) has a query kind with no
          -- error-free page in the window, unless an audit_serp job was
          -- created in the last day or one is still waiting: a failure
          -- is retried once a day at most, and not at all once
          -- {MAX_FAILURES} jobs have failed in the window.
          -- ponytail: serp_audit has no index on brand_id, so each
          -- brand's count scans the table; add an index on
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
            AND (SELECT count(*) FROM job j
                 WHERE j.brand_id = b.id AND j.kind = 'audit_serp'
                   AND j.status = 'failed'
                   AND j.created_at
                       > now() - make_interval(days => {AUDIT_DAYS}))
                < {MAX_FAILURES}
          ORDER BY b.id
        $$""")
    op.execute("REVOKE ALL ON FUNCTION due_serp_audits() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION due_serp_audits() TO bsi_app")


def downgrade() -> None:
    op.execute("DROP FUNCTION due_serp_audits()")
```

A brand is due when all six hold:
1. It is active.
2. It has at least one declared domain (decision 5).
3. Fewer than two of the query kinds (`brand`, `reviews`) have a row with no error fetched in the last 7 days.
4. No `audit_serp` job for it was created in the last 24 hours, whatever the job's status.
5. No `audit_serp` job for it is `queued` or `running`, however old. Without this, a worker that is down for over a day would stack a second job for the brand.
6. Fewer than 3 `audit_serp` jobs for it that were created in the last 7 days have failed (decision 6).

Consequences:
- A manual audit counts: after "Run audit now" on a Tuesday, the next automatic audit is the following Tuesday. A failed manual audit counts toward condition 6 too: three failed manual audits in three different hours (presses in one hour reuse one job row) pause the automatic audit until the oldest of them is 7 days old.
- A partial success (one query failed) finishes the job as `done` and leaves the brand due; the retry a day later re-runs both queries. Condition 6 counts failed jobs only, so a partial success that repeats is retried every day: 2 calls, about $0.004 a day at the observed price.
- A failure that repeats on every run (a first locale other than India, a paused or unfunded account, timeouts) settles at about 3 failed jobs a week per brand. If each call of each failed job is a billed timeout, that is 6 calls, about $0.012 a week per brand at the observed price.
- A good page with zero results counts as a page; only an error makes it count as missing.
- Locale is ignored: good pages from an old locale still count in the week after a brand's first locale changes.
- A brand with no domain is audited only by "Run audit now". A domain added later to a brand that already has one is picked up at the next weekly audit, and so is a competitor declared after an audit: until then its results are typed `other` where `competitor` would be right (the ownership share does not use that type).
- "Run audit now" is not held back by these conditions. Pressed in a later hour than a scheduled job that is still queued or running, it creates a second job for the brand, about $0.004.
- The order is by brand id. Every due brand is offered to the same sweep, so "oldest first" would change nothing.
- `serp_audit` has no index on `brand_id`, so each brand's page count scans the table; the function's comment names an index on `(brand_id, kind, fetched_at)` as the upgrade.
- `KINDS = 2` repeats `len(models.SERP_KINDS)` by hand: the function's text is fixed when the migration runs. A third kind needs a new migration that replaces the function, and a change to `run_serp_audit()`'s query pair.
- Fixing the cause does not lift the cap: after a paused or unfunded account is fixed, a brand that reached three failures stays not due until its oldest failure is 7 days old, up to about 5 days. "Run audit now" is not held back.
- An org whose daily budget is under the job's estimate ($0.04) is never audited automatically: the sweep's check never passes, no job is created and nothing shows it. Each sweep still opens one short transaction per due brand of that org.

### The worker sweep

apps/workers/bsi_workers/worker.py, as a diff against main `dbcb2df`:

```diff
@@ -828,4 +828,51 @@ def queue_due_crawl_audits() -> int:
 
 
+def queue_due_serp_audits() -> int:
+    """Queue a Brand SERP audit for every brand due one; returns how many.
+
+    Like queue_due_crawl_audits, one brand's failure never stops the
+    others. Unlike it:
+    - a queued job makes its brand not due, so a second call returns 0;
+    - with no DataForSEO credentials nothing is queued: each due
+      brand's job would fail as serp_not_configured, up to three times
+      a week;
+    - a brand is skipped, with no job, while its org's budget has no
+      room for the job's estimate. It stays due and is queued once
+      there is room; process_job checks the budget again at claim time.
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
+                if not budget_fits(s, org_id, 0, extra_micros=SERP_JOB_MICROS):
+                    continue
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
@@ -1225,4 +1272,8 @@ def main() -> None:
             except Exception:
                 log.exception("queue_due_rival_crawls failed")
+            try:
+                log.info("queued %d serp audits", queue_due_serp_audits())
+            except Exception:
+                log.exception("queue_due_serp_audits failed")
             try:
                 log.info("scanned %d brands for alerts", scan_due_alerts())
```

The sweep follows `queue_due_crawl_audits()`, with three differences that its docstring lists:
- A second call in the same hour returns 0, because the job the first call queued makes the brand not due (condition 5). The crawl sweep counts the brand again.
- With an empty login or password it returns 0 without reading the due list (R1).
- It calls `budget_fits(s, org_id, 0, extra_micros=SERP_JOB_MICROS)` in the org's tenant session and skips the brand, creating no job, when the estimate does not fit (decision 7). The brand stays due, so the next sweep tries again; the check takes the org's advisory lock for that short transaction and spends nothing. `process_job()` still checks the budget when it claims the job, so a job queued with room can still fail as `budget` if the room is gone by then; that failure falls under conditions 4 and 6.

Unchanged: `run_serp_audit()`, `SERP_JOB_MICROS`, `MAX_SERP_LOCALES`, the API routes and schemas (no `npm run gen`). A scheduled job and a manual one look the same in the `job` table.

The first sweep after the merge queues every due brand at once. Jobs run one at a time, ahead of observations; a SERP job's two calls were observed to take 9.27 s and 13.13 s on 2026-10-05, and a job can take about 8 minutes at worst. Spreading audits across the week is left out, with a `ponytail:` comment naming it.

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

Seventeen tests are appended to tests/integration/test_serp_audit.py; three are parametrized over two values, so the suite gains 20 test items. No test makes a network call. The file's imports gain `timedelta` and `system_session`:

```python
def _page(owner, org, bid, kind, days_ago=0, error=None, results=()):
    with owner() as s, s.begin():
        s.add(
            m.SerpAudit(
                org_id=org.id,
                brand_id=bid,
                kind=kind,
                query="q",
                country="IN",
                language="en",
                results=list(results),
                fetched_at=datetime.now(UTC) - timedelta(days=days_ago),
                error=error,
            )
        )


def _old_job(owner, org, bid, status, hours, kind="audit_serp"):
    """A job created `hours` ago, in its own slot."""
    return _job(
        owner,
        org,
        bid,
        kind,
        status,
        minutes=-60 * hours,
        created_at=datetime.now(UTC) - timedelta(hours=hours),
    )


def _declared(owner, org, bid):
    """Give the brand a domain: only a brand with one is ever due."""
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host="walkaroo.in"))
    return bid


def due():
    with system_session() as s:
        return [
            r[0]
            for r in s.execute(text("SELECT brand_id FROM due_serp_audits()"))
        ]


def _serp_jobs(owner):
    with owner() as s:
        return list(
            s.scalars(
                select(m.Job)
                .where(m.Job.kind == "audit_serp")
                .order_by(m.Job.created_at, m.Job.id)
            )
        )


def test_a_brand_with_no_pages_and_no_jobs_is_due(owner, make_org, make_brand):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    assert due() == [bid]


def test_a_brand_with_no_domain_is_not_due_until_one_is_declared(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    assert due() == []
    _declared(owner, org, bid)
    assert due() == [bid]


def test_good_pages_for_both_queries_this_week_are_not_due(
    owner, make_org, make_brand
):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    _page(owner, org, bid, "brand", 6, results=[{"position": 1}])
    _page(owner, org, bid, "reviews", 6, results=[{"position": 1}])
    assert due() == []


def test_due_again_once_the_pages_are_over_seven_days_old(
    owner, make_org, make_brand
):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    _page(owner, org, bid, "brand", 8)
    _page(owner, org, bid, "reviews", 6)
    assert due() == [bid]  # one page is too old
    _page(owner, org, bid, "brand", 6)
    assert due() == []
    with owner() as s, s.begin():
        s.execute(
            update(m.SerpAudit).values(
                fetched_at=datetime.now(UTC) - timedelta(days=8)
            )
        )
    assert due() == [bid]


def test_one_good_page_and_one_failed_page_is_due(owner, make_org, make_brand):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    _page(owner, org, bid, "brand")
    _page(owner, org, bid, "brand")  # two pages of one kind are one kind
    assert due() == [bid]
    _page(owner, org, bid, "reviews", error="timeout")
    assert due() == [bid]  # an error page is not a page
    _page(owner, org, bid, "reviews")
    assert due() == []


def test_a_good_page_with_no_results_counts(owner, make_org, make_brand):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    _page(owner, org, bid, "brand", results=[])
    _page(owner, org, bid, "reviews", results=[])
    assert due() == []


@pytest.mark.parametrize("status", ["failed", "done"])
def test_a_job_in_the_last_day_blocks_whatever_its_status(
    owner, make_org, make_brand, status
):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    job_id = _old_job(owner, org, bid, status, 23)
    assert due() == []
    with owner() as s, s.begin():
        s.execute(
            update(m.Job)
            .where(m.Job.id == job_id)
            .values(created_at=datetime.now(UTC) - timedelta(hours=25))
        )
    assert due() == [bid]


@pytest.mark.parametrize("status", ["queued", "running"])
def test_a_waiting_job_blocks_however_old(owner, make_org, make_brand, status):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    job_id = _old_job(owner, org, bid, status, 72)
    assert due() == []
    with owner() as s, s.begin():
        s.execute(
            update(m.Job).where(m.Job.id == job_id).values(status="failed")
        )
    assert due() == [bid]


def test_three_failed_jobs_in_a_week_stop_the_retries(
    owner, make_org, make_brand
):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    first = _old_job(owner, org, bid, "failed", 30)
    _old_job(owner, org, bid, "failed", 60)
    _old_job(owner, org, bid, "done", 90)  # only failures count
    _old_job(owner, org, bid, "failed", 100, kind="audit_crawl")
    assert due() == [bid]
    _old_job(owner, org, bid, "failed", 120)
    assert due() == []
    with owner() as s, s.begin():
        s.execute(
            update(m.Job)
            .where(m.Job.id == first)
            .values(created_at=datetime.now(UTC) - timedelta(days=8))
        )
    assert due() == [bid]  # two failures left in the window


def test_a_job_of_another_kind_does_not_block(owner, make_org, make_brand):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    _old_job(owner, org, bid, "done", 1, kind="audit_crawl")
    _old_job(owner, org, bid, "queued", 2, kind="crawl_rivals")
    assert due() == [bid]


def test_archived_brands_are_never_due_for_a_serp_audit(
    owner, make_org, make_brand
):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand).where(m.Brand.id == bid).values(status="archived")
        )
    assert due() == []


def test_due_serves_every_tenant_in_brand_id_order(owner, make_org, make_brand):
    a = make_org("A")
    b = make_org("B")
    brands = [
        _declared(owner, org, make_brand(org, f"B{i}"))
        for i in range(3)
        for org in (a, b)
    ]
    assert due() == sorted(brands)


def test_the_sweep_queues_one_job_per_due_brand_once(
    configured, owner, make_org, make_brand
):
    a = make_org("A")
    b = make_org("B")
    brands = {
        _declared(owner, a, make_brand(a)),
        _declared(owner, b, make_brand(b)),
    }
    assert worker.queue_due_serp_audits() == 2
    assert worker.queue_due_serp_audits() == 0  # a job is waiting
    jobs = _serp_jobs(owner)
    assert {j.brand_id for j in jobs} == brands and len(jobs) == 2
    assert all((j.status, j.params) == ("queued", {}) for j in jobs)


def test_the_sweep_retries_a_failed_audit_after_a_day_not_before(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    assert worker.queue_due_serp_audits() == 1
    (job,) = _serp_jobs(owner)
    with owner() as s, s.begin():
        s.execute(
            update(m.Job)
            .where(m.Job.id == job.id)
            .values(status="failed", error="timeout")
        )
    assert worker.queue_due_serp_audits() == 0
    assert [(j.id, j.status) for j in _serp_jobs(owner)] == [(job.id, "failed")]
    with owner() as s, s.begin():
        s.execute(
            update(m.Job)
            .where(m.Job.id == job.id)
            .values(
                created_at=datetime.now(UTC) - timedelta(hours=25),
                scheduled_slot=datetime.now(UTC) - timedelta(hours=25),
            )
        )
    assert worker.queue_due_serp_audits() == 1
    assert [(j.brand_id, j.status) for j in _serp_jobs(owner)] == [
        (bid, "failed"),
        (bid, "queued"),
    ]


def test_the_sweep_skips_a_brand_while_the_budget_has_no_room(
    configured, owner, make_org, make_brand
):
    org = make_org()
    _declared(owner, org, make_brand(org))

    def budget(usd):
        with owner() as s, s.begin():
            s.execute(
                update(m.Organization)
                .where(m.Organization.id == org.id)
                .values(daily_budget_usd=Decimal(usd))
            )

    budget("0.03")  # under the job's $0.04 estimate
    assert worker.queue_due_serp_audits() == 0
    assert _serp_jobs(owner) == []  # no job, so the brand stays due
    budget("0.04")
    assert worker.queue_due_serp_audits() == 1
    assert [j.status for j in _serp_jobs(owner)] == ["queued"]


@pytest.mark.parametrize(
    "missing", [{"login": ""}, {"password": ""}], ids=["login", "password"]
)
def test_the_sweep_queues_nothing_without_credentials(
    monkeypatch, owner, make_org, make_brand, missing
):
    monkeypatch.setattr(worker, "get_settings", _settings(**missing))
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    assert due() == [bid]
    assert worker.queue_due_serp_audits() == 0
    assert _serp_jobs(owner) == []


def test_a_swept_job_stores_the_pages_and_the_brand_is_no_longer_due(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = _declared(owner, org, make_brand(org, "Walkaroo"))
    assert worker.queue_due_serp_audits() == 1
    assert _run(Fetch(Response(200, body()))) is True
    (job,) = _serp_jobs(owner)
    assert (job.status, job.error) == ("done", None)
    assert [(r.kind, r.error) for r in _rows(owner, bid)] == [
        ("brand", None),
        ("reviews", None),
    ]
    # Not due for a week, even once the job is over a day old.
    with owner() as s, s.begin():
        s.execute(
            update(m.Job)
            .where(m.Job.id == job.id)
            .values(created_at=datetime.now(UTC) - timedelta(hours=25))
        )
    assert due() == []
```

Expected gates: backend `1728 passed, 2 deselected` (1708 on main plus 20) with metrics coverage at 100%; web 49 vitest, unchanged.

Not tested (R5): a manual audit through the route followed by the sweep (the conditions read the `job` table, where a manual job and a scheduled one are the same); locale; a domain or competitor declared later; the sweep's per-brand `try/except`; the `main()` wiring. The two existing sweeps are tested the same way.

### Proof

Run 2026-10-06 in the scratchpad on copies of main's files, against the shared test database (R3). The edit pairs, the migration text and the tests in this spec are the ones the run used.

- Red, main's code with the new tests and without the proof plugin, so `due_serp_audits()` did not exist: `20 failed, 11 passed` (the 11 are the file's existing tests).
- Green, patched, with the plugin: `31 passed`.
- `ruff check` and `ruff format --check` pass on the patched worker, the test file and the migration file.
- Not run in the proof: the migration file through alembic (the function's SQL was installed by the proof-only plugin from the same text), `mypy` (it covers `packages/core` only, which this slice does not touch), and the web gate.

Each rule has a mutant that fails a test. Each row is one run of the 31 tests with one change:

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
| M3c | condition 4: the retry wait is 7 days | 6 | `test_a_job_in_the_last_day_blocks_whatever_its_status[done]`, `test_a_job_in_the_last_day_blocks_whatever_its_status[failed]`, `test_a_waiting_job_blocks_however_old[queued]`, `test_a_waiting_job_blocks_however_old[running]`, `test_the_sweep_retries_a_failed_audit_after_a_day_not_before`, `test_three_failed_jobs_in_a_week_stop_the_retries` |
| M4 | condition 5 dropped: an old waiting job does not block | 2 | `test_a_waiting_job_blocks_however_old[queued]`, `test_a_waiting_job_blocks_however_old[running]` |
| M5 | no ORDER BY | 1 | `test_due_serves_every_tenant_in_brand_id_order` |
| M10 | condition 6 dropped: no failure cap (the limit is 1000) | 1 | `test_three_failed_jobs_in_a_week_stop_the_retries` |
| M10a | condition 6: the limit is 4 | 1 | `test_three_failed_jobs_in_a_week_stop_the_retries` |
| M10b | condition 6: jobs of every status count | 1 | `test_three_failed_jobs_in_a_week_stop_the_retries` |
| M10c | condition 6: failed jobs of every kind count | 1 | `test_three_failed_jobs_in_a_week_stop_the_retries` |
| M10d | condition 6: no 7-day window | 1 | `test_three_failed_jobs_in_a_week_stop_the_retries` |
| M6 | R1 dropped: the sweep queues without credentials | 2 | `test_the_sweep_queues_nothing_without_credentials[login]`, `test_the_sweep_queues_nothing_without_credentials[password]` |
| M11 | the sweep's budget check dropped | 1 | `test_the_sweep_skips_a_brand_while_the_budget_has_no_room` |
| M11a | the sweep's budget check passes an estimate of 0 | 1 | `test_the_sweep_skips_a_brand_while_the_budget_has_no_room` |
| M7 | R1: only the login is checked | 1 | `test_the_sweep_queues_nothing_without_credentials[password]` |
| M8 | R1: only the password is checked | 1 | `test_the_sweep_queues_nothing_without_credentials[login]` |

No mutant fails `test_a_brand_with_no_pages_and_no_jobs_is_due`, `test_good_pages_for_both_queries_this_week_are_not_due`, `test_a_good_page_with_no_results_counts`, `test_the_sweep_queues_one_job_per_due_brand_once` or `test_a_swept_job_stores_the_pages_and_the_brand_is_no_longer_due` (R5).

## Rulings

Quoted from the ledger:

> Ruling: R1. Decided: queue_due_serp_audits() returns 0 without reading the due list when the DataForSEO login or password is empty. Found by: the controller, while reading run_serp_audit during brainstorming (a job with no credentials fails as serp_not_configured and writes no rows, so the brand stays due). Why: otherwise every active brand gets one serp_not_configured failed job a day, forever. Cost if wrong: a missing-credentials setup is silent in the job list; "Run audit now" still reports it. How named: in chat in the Section 2 design text, 2026-10-06, and approved with Section 2.

> Ruling: R2. Decided: three of the 15 new tests are parametrized over two values (job status failed/done; job status queued/running; missing login/password), so the suite gains 18 test items and the expected backend count is 1726, not the plan file's "1708 + 14". Found by: the controller, writing the scratch proof. Why: each value is a separate rule a mutant can break (M7 and M8 each fail exactly one of the two credential cases). Cost if wrong: none to behaviour; a count in the approved plan file is superseded. How named: in chat, 2026-10-06, after the proof run.

> Ruling: R3. Decided: the scratch proof installed due_serp_audits() in the shared test database bsi_test through a proof-only pytest plugin and dropped it at the end of each session; the count of functions of that name was read as 0 afterwards. Found by: the controller, setting up the proof. Why: tests/conftest.py applies the repo's migrations, and a scratch copy cannot add migration 0024 to them. Cost if wrong: a leftover function would make migration 0024's CREATE FUNCTION fail in the test session. How named: in chat, 2026-10-06, after the proof run.

> Ruling: R4. Decided: the spec review's findings 3, 4, 5 and 6 are fixed in the spec: the 16 test bodies are printed in the spec and the red run is stated to have run without the proof plugin (3); "a stale failure writes no rows" is corrected, since a job failed as stale can still write its rows when it finishes late (4); the sweep's docstring lists its real differences from the crawl sweep (5); the SQL comment and the facts say serp_audit has no index on brand_id and is scanned whole (6). Found by: the spec reviewer (Opus 5.5), 2026-10-06. Why: each is a wrong or uncheckable statement, not a design choice. Cost if wrong: none to behaviour; the docstring and SQL comment are text. How named: in chat, 2026-10-06, after the review.

> Ruling: R5. Decided: the spec review's findings 7, 8, 9 and 10 are left as they are and recorded in the spec: KINDS = 2 stays hard-coded in the migration with its comment (7); no tests are added for a manual audit through the route, locale, a later domain, the per-brand try/except or the main() wiring, and no mutants are added for the tests that have none (8); "Run audit now" pressed in a later hour than a queued scheduled job can create a second job, about $0.004 (9); a competitor declared after the first automatic audit is classed other until the next weekly audit (10). Found by: the spec reviewer (Opus 5.5), 2026-10-06. Why: 7 cannot import models from a migration; 8 matches how the two existing sweeps are tested; 9 and 10 are small, and 10 does not change the ownership share. Cost if wrong: a third query kind would need the migration's number changed by hand; a regression in the untested paths would not be caught; one extra audit's spend; a week of other where competitor was right. How named: in chat, 2026-10-06, after the review.

> Ruling: R6. Decided: the scoped re-review's seven minors (N1 to N7) are fixed in the spec and the proof: the sweep docstring says a job without credentials would fail up to three times a week, not once a day (N1); the KINDS sentence gives the real reason and remedy, a new migration and a change to run_serp_audit's query pair (N2); test_good_pages_for_both_queries_this_week_are_not_due writes pages that have a result, so test_a_good_page_with_no_results_counts differs from it (N3); the README row no longer says three times a week at most (N4); "Run audit now" stacking is stated for a queued or running job (N5); two consequences are added, that fixing the cause does not lift the cap and that an org whose budget is under the estimate is never audited automatically (N6); three failed manual audits must be in different hours to count as three (N7). The fix commit is not re-reviewed. Found by: the scoped re-reviewer (Opus 5.5), 2026-10-06. Why: each is an inaccurate or missing statement; none changes a rule the user chose. Cost if wrong: none to behaviour; one docstring and one test's fixture change. How named: in chat, 2026-10-06, after the re-review.

> Correction to R2 and R4 (2026-10-06, after the proof was re-run with the failure cap and the sweep's budget check): there are 17 new tests, not R2's 15 or R4's 16; three are parametrized over two values, so the suite gains 20 test items and the expected backend count is 1728, not R2's 1726.

> Correction to R1 and R5 (2026-10-06, from the re-review): with the failure cap, a brand without credentials would fail up to three times a week, not R1's "one serp_not_configured failed job a day, forever"; and a migration can import the models (migrations/env.py does), so R5's reason for finding 7 is wrong: KINDS is a number because the function's text is fixed when the migration runs, and a third kind needs a new migration, not this number changed by hand.

Rulings made after this spec was approved (added by the post-merge docs commit), quoted from the ledger:

> Ruling: R7. Decided: the plan's steps are verified in a scratch copy of the repo's alembic.ini, migrations and tests, run with the repo's Python, so tests/conftest.py applies migration 0024 to the shared test database bsi_test for real; afterwards the controller downgrades bsi_test to 0023 by alembic and reads alembic_version and pg_proc to confirm. Found by: the controller, planning the plan's verification. Why: the spec's proof installed the function through a plugin and never ran the migration file; this runs its upgrade and its downgrade. Cost if wrong: bsi_test left at 0024 would make every test session on main fail to locate the revision until it is downgraded. How named: in chat, 2026-10-06, before the verification ran.

> Ruling: R8. Decided: the plan review's three minors are left: the Consumes lists of Tasks 1 and 2 name some helpers the task does not use and omit some it does (1); Task 3 has no git status check (2); the commit trailer stays "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" for every commit although the implementers run on Opus 5.5 (3). Found by: the plan reviewer (Opus 5.5), 2026-10-06. Why: 1 and 2 change nothing an implementer does, since every name is already in the file; for 3 the user's standing rule is that the trailer is whatever the latest attribution reminder names, and that is Fable 5.1. Cost if wrong: commits credit a model that did not write the code. How named: in chat, 2026-10-06, with the plan review's result.

> Ruling: R9. Decided: the commit trailer for slice 43's commits becomes "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; the plan's Global Constraints and its three commit messages are changed to it before execution, and the three earlier spec and plan commits keep their Fable 5.1 trailer. This supersedes part 3 of R8. Found by: the controller, when the attribution reminder changed to Opus 5.5 after the execution choice (2026-10-06). Why: the user's standing rule is that the trailer is whatever the latest attribution reminder names. Cost if wrong: the slice's commits credit a different model from the docs commits. How named: in chat, 2026-10-06, before Task 1. The plan edit is text-only (four lines) and is not re-reviewed; disclosed here and in chat.

> Ruling: R10. Decided: no final fix wave; the final review's two minors are deferred: one sweep checks each brand's budget against the same room, because a queued job spends nothing yet, so an org with several due brands can get more jobs queued than its budget fits, and the extra ones fail as budget at claim time and count toward the cap (1); the page sentence is untrue for a brand with no declared domain (2, already the spec's deferred minor). Found by: the final reviewer (Opus 5.5), 2026-10-06. Why: the review is "Ready to merge? Yes" with no Critical or Important finding; (1) spends nothing extra, since process_job re-checks the budget; (2) is a copy change to approved design text, which the user decides. Cost if wrong: on a tight budget a brand can lose a day and one of its three weekly attempts; a brand with no domain shows a sentence that does not apply to it. How named: in chat, 2026-10-06, at the finishing menu.

## Deferred minors

- The page sentence "Audited automatically once a week." is also shown for a brand with no declared domain, which the sweep skips. Found by the controller while writing this spec; not fixed, because the sentence is static copy approved before decision 5.
- The spec review's findings 7, 8, 9 and 10, left as R5 records.
- `test_a_good_page_with_no_results_counts` and `test_good_pages_for_both_queries_this_week_are_not_due` differ only in their fixtures; no mutant tells them apart (re-review N3).
- The commit that applies R6 was not re-reviewed.

## Live check (after merge, ask first)

Migrate dev to 0024 (ask first), call `queue_due_serp_audits()` once, then `process_job` once per queued job with a `serp_fetch` wrapper that prints only statuses, codes, costs, item counts and latency. The worker loop is never started. Expected, *inferred*: one brand is due (`BSOAgentTestBrand` `34db213a`, the only test brand with a domain); Walkaroo has good pages from 2026-10-05 and is not due until 2026-10-12; 1 job, 2 searches, about $0.004.
