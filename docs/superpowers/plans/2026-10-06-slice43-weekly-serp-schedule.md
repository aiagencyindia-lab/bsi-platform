# Slice 43 Weekly Brand SERP Schedule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The worker queues a Brand SERP audit weekly for every active brand with a declared domain, retries a failure once a day at most, stops after three failed jobs in a week, and queues nothing without credentials or budget room.

**Architecture:** Migration 0024 adds one `SECURITY DEFINER` SQL function, `due_serp_audits()`, that lists the due brands. `queue_due_serp_audits()` in the worker reads it once a minute and queues the existing `audit_serp` job. The Brand SERP page gains one sentence.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, Postgres 16, pytest; Next.js 15 for the one page line.

**Spec:** `docs/superpowers/specs/2026-10-06-slice43-weekly-serp-schedule-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice43-weekly-serp-schedule`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB (`bsi`), the network, the worker loop, DataForSEO or a model: every test uses fakes. Never run `alembic` by hand: the test session applies migrations to `bsi_test` itself.
- **Shared test DB:** run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own before every pytest run; if it prints a running pytest, stop and wait. Run the full backend suite only in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal.)
- **Writing files:** use the Edit or Write tools; never a shell heredoc or zsh `echo` to write files. Never run `rm`.
- **Lint and types:** ruff line length 80, target py313, rules E F I B UP RUF; `mypy --strict` covers `packages/core/bsi_core`.
- **Banned words:** copy (code, comments, docstrings, test names) never contains the words listed in `FORBIDDEN` in tests/unit/test_recommend_copy.py.
- **Banned-word grep (must block the commit):** `cd /Users/vineet/Downloads/ADK/bsi-platform && ! { git diff --cached -U0 | grep '^+' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'; }`, run after staging. Expected: exit 0 and no output.
- **Backend gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform && { uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task<N>.txt 2>&1; echo "gate exit $?"`. If `ruff format .` changed a file, re-stage it and say so.
- **Web gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate > <workspace>/gate-web.txt 2>&1; echo "gate exit $?"`.
- **`<workspace>`:** the path given in your task brief; if none is given, stop and ask.
- **Commit trailer:** exactly `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- **Baseline counts** (main `dbcb2df`): backend `1708 passed, 2 deselected`; tests/integration/test_serp_audit.py has 11 tests; web 49 vitest. After Task 1: the file has 25 test items, backend `1722 passed, 2 deselected`. After Task 2: 31 test items, backend `1728 passed, 2 deselected`. (Backend totals computed, not yet run.) Task 3 changes no count.

## File map

| File | Responsibility | Task |
|---|---|---|
| `migrations/versions/0024_due_serp_audits.py` (new) | `due_serp_audits()`: which brands are due | 1 |
| `tests/integration/test_serp_audit.py` | the due-rule tests and their helpers; the sweep tests | 1, 2 |
| `apps/workers/bsi_workers/worker.py` | `queue_due_serp_audits()` and its call in the worker loop | 2 |
| `apps/web/src/app/(app)/b/[id]/serp/page.tsx` | the "Audited automatically once a week." sentence | 3 |

---

### Task 1: `due_serp_audits()` lists the due brands

**Files:**
- Create: `migrations/versions/0024_due_serp_audits.py`
- Test: `tests/integration/test_serp_audit.py`

**Interfaces:**
- Consumes: the test file's existing imports (`m`, `pytest`, `text`, `select`, `update`, `Decimal`, `worker`, `_job`, `_load_job`, `Fetch`, `body`, `Response`) and helpers (`_settings`, `configured`, `_run`, `_rows`); the fixtures `owner`, `make_org`, `make_brand`; the tables `brand`, `domain`, `serp_audit` and `job`.
- Produces: the SQL function `due_serp_audits()` returning `(brand_id uuid, org_id uuid)`, executable by `bsi_app`; the test helpers `_page(owner, org, bid, kind, days_ago=0, error=None, results=())`, `_old_job(owner, org, bid, status, hours, kind="audit_serp")`, `_declared(owner, org, bid)` (adds a domain, returns `bid`), `due()` (the due brand ids, in order) and `_serp_jobs(owner)` (the `audit_serp` jobs, oldest first; first used in Task 2).

- [ ] **Step 1: Write the failing tests**

In `tests/integration/test_serp_audit.py`:

1. Replace

```python
from datetime import UTC, datetime
```

with

```python
from datetime import UTC, datetime, timedelta
```

2. Replace

```python
from bsi_core.crawl import Response
```

with

```python
from bsi_core.crawl import Response
from bsi_core.db import system_session
```

3. Add this block after the file's last line, separated from it by two blank lines:

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_serp_audit.py 2>&1 | tail -1`
Expected: a line starting with `14 failed, 11 passed`. The failures are `UndefinedFunction: function due_serp_audits() does not exist`.

- [ ] **Step 3: Write the migration**

Create `migrations/versions/0024_due_serp_audits.py` with the Write tool:

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

- [ ] **Step 4: Run the tests to verify they pass**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_serp_audit.py 2>&1 | tail -1`
Expected: a line starting with `25 passed`. The test session applies migration 0024 to `bsi_test` itself.

- [ ] **Step 5: Banned-word grep, then the backend gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add migrations/versions/0024_due_serp_audits.py tests/integration/test_serp_audit.py`. Run the banned-word grep (expected: exit 0, no output). Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own, then the Backend gate with `<N>` = 1. Expected: `gate exit 0`; `gate-task1.txt` shows `1722 passed, 2 deselected`, mypy `Success`, metrics coverage 100%. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the two staged files plus the untracked `.DS_Store` and `packages/.DS_Store`).

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add migrations/versions/0024_due_serp_audits.py tests/integration/test_serp_audit.py && git commit -m "feat(db): due_serp_audits() lists the brands due a SERP audit

Migration 0024. An active brand with a declared domain is due when a
query kind has no error-free page in 7 days, unless an audit_serp job
was created in the last day, one is waiting, or three have failed in
the 7 days.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: the worker queues the due audits

**Files:**
- Modify: `apps/workers/bsi_workers/worker.py` (a new function before `_record_failure`; four lines in `main()` after the rival-crawl sweep)
- Test: `tests/integration/test_serp_audit.py`

**Interfaces:**
- Consumes: Task 1's `due_serp_audits()` and the test helpers `_declared`, `due`, `_serp_jobs`, `_page`, `_old_job`; in worker.py the existing `get_settings`, `system_session`, `tenant_session`, `text`, `budget_fits`, `enqueue_job`, `SERP_JOB_MICROS` and `log`.
- Produces: `queue_due_serp_audits() -> int`, the number of jobs queued in this call.

- [ ] **Step 1: Write the failing tests**

In `tests/integration/test_serp_audit.py`, add this block after the file's last line, separated from it by two blank lines:

```python
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

- [ ] **Step 2: Run the tests to verify they fail**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_serp_audit.py 2>&1 | tail -1`
Expected: a line starting with `6 failed, 25 passed`. The failures are `AttributeError: module 'bsi_workers.worker' has no attribute 'queue_due_serp_audits'`.

- [ ] **Step 3: Write the implementation**

In `apps/workers/bsi_workers/worker.py`:

1. Replace

```python
def _record_failure(
```

with

```python
def queue_due_serp_audits() -> int:
    """Queue a Brand SERP audit for every brand due one; returns how many.

    Like queue_due_crawl_audits, one brand's failure never stops the
    others. Unlike it:
    - a queued job makes its brand not due, so a second call returns 0;
    - with no DataForSEO credentials nothing is queued: each due
      brand's job would fail as serp_not_configured, up to three times
      a week;
    - a brand is skipped, with no job, while its org's budget has no
      room for the job's estimate. It stays due and is queued once
      there is room; process_job checks the budget again at claim time.

    ponytail: every due brand is queued in one sweep and jobs run one at
    a time ahead of observations; spread the audits across the week when
    there are a few hundred brands.
    """
    settings = get_settings()
    if not (
        settings.dataforseo_login
        and settings.dataforseo_password.get_secret_value()
    ):
        return 0
    with system_session() as s:
        due = s.execute(
            text("SELECT brand_id, org_id FROM due_serp_audits()")
        ).all()
    queued = 0
    for brand_id, org_id in due:
        try:
            with tenant_session(org_id) as s:
                if not budget_fits(s, org_id, 0, extra_micros=SERP_JOB_MICROS):
                    continue
                enqueue_job(
                    s,
                    org_id,
                    brand_id,
                    "audit_serp",
                    {},
                    requeue_failed=False,
                )
            queued += 1
        except Exception:
            log.exception("brand %s serp audit queue failed", brand_id)
    return queued


def _record_failure(
```

2. Replace

```python
                log.exception("queue_due_rival_crawls failed")
```

with

```python
                log.exception("queue_due_rival_crawls failed")
            try:
                log.info("queued %d serp audits", queue_due_serp_audits())
            except Exception:
                log.exception("queue_due_serp_audits failed")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/integration/test_serp_audit.py 2>&1 | tail -1`
Expected: a line starting with `31 passed`.

- [ ] **Step 5: Banned-word grep, then the backend gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/workers/bsi_workers/worker.py tests/integration/test_serp_audit.py`. Run the banned-word grep (expected: exit 0, no output). Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own, then the Backend gate with `<N>` = 2. Expected: `gate exit 0`; `gate-task2.txt` shows `1728 passed, 2 deselected`, mypy `Success`, metrics coverage 100%. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the two staged files plus the untracked `.DS_Store` and `packages/.DS_Store`).

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/workers/bsi_workers/worker.py tests/integration/test_serp_audit.py && git commit -m "feat(worker): queue the weekly Brand SERP audits

queue_due_serp_audits() queues an audit_serp job for each brand
due_serp_audits() lists, once a minute. Nothing is queued without
DataForSEO credentials, and a brand is skipped with no job while its
org's budget has no room for the job's estimate.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: the Brand SERP page says the audit is weekly

**Files:**
- Modify: `apps/web/src/app/(app)/b/[id]/serp/page.tsx`

**Interfaces:**
- Consumes: nothing from Tasks 1 and 2.
- Produces: one static sentence; no data, no test.

- [ ] **Step 1: Add the sentence**

In `apps/web/src/app/(app)/b/[id]/serp/page.tsx`:

Replace

```tsx
      </form>
```

with

```tsx
      </form>
      <p className="muted">Audited automatically once a week.</p>
```

- [ ] **Step 2: The web gate**

Run the Web gate. Expected: `gate exit 0`; `gate-web.txt` shows `Tests  49 passed (49)` and `Compiled successfully`.

- [ ] **Step 3: Banned-word grep, then commit**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add "apps/web/src/app/(app)/b/[id]/serp/page.tsx"`. Run the banned-word grep (expected: exit 0, no output). Then:

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add "apps/web/src/app/(app)/b/[id]/serp/page.tsx" && git commit -m "feat(web): the Brand SERP page says the audit is weekly

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review (plan vs spec)

- Spec coverage: Migration 0024 → Task 1 Step 3; the six conditions' tests → Task 1 Step 1; the worker sweep and the loop call → Task 2 Step 3; the sweep tests → Task 2 Step 1; the page sentence → Task 3 Step 1; expected gates → Task 2 Step 5 and Task 3 Step 2; Copy → each task's banned-word grep. The live check and the post-merge docs are controller work after the merge.
- Testing check, name by name: the 17 tests printed in the spec's Testing section are in Task 1 Step 1 (12 tests, 14 items) and Task 2 Step 1 (5 tests, 6 items), with the same bodies.
- Departures from the spec:
  1. The code changes are replace blocks generated from the scratch proof's verified pairs, not the spec's unified diffs; the result is the same files.
  2. Three tasks, each with its own commit; the spec sets no task boundaries.
  3. The spec prints the new tests as one block; the plan splits it before `test_the_sweep_queues_one_job_per_due_brand_once`. The helper `_serp_jobs` arrives in Task 1 and is first used in Task 2, so the finished file matches the spec's block.
  4. Per-task counts (25 items and 1722 after Task 1) are the plan's arithmetic; the spec gives only 31 and 1728.
  5. The spec's mutation table is not repeated in execution: each task has a true red step.
  6. The commit messages are the plan's wording.
  7. The header offers superpowers:executing-plans as well as subagent-driven-development (the template's wording).
- Fixtures and copy: the fixture values (`walkaroo.in`, `B0`–`B2`, `"q"`, `"timeout"`) and the page sentence contain no banned word.
- Placeholders: `<workspace>` and `<N>`.
- Type consistency: `due()` returns a list of brand ids in Task 1 and is compared to lists in Task 2; `_serp_jobs(owner)` returns `Job` rows; `queue_due_serp_audits() -> int` in Task 2's tests and implementation.

## Changes made during execution

(Filled in by the post-merge docs commit.)
