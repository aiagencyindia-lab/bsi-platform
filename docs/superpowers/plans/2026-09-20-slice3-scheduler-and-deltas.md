# Slice 3: Scheduler and deltas — implementation plan

**Spec:** `docs/superpowers/specs/2026-09-20-slice3-scheduler-and-deltas-design.md`. It wins on any conflict with this plan.

**Branch:** `slice3-scheduler-and-deltas` (off `main` at `1b4d28b`).

**Process:** each task has one implementer, then one task review. The ledger is at `.superpowers/sdd/2026-09-20-slice3-scheduler-and-deltas/progress.md`.

## Global rules

- **Test first.** Write the tests, run them, and **paste the failing output into the task report** before implementing. Then paste the passing output.
- **Gate** at the end of every task:

  ```bash
  uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100
  ```

- **Code standards:**
  - `bsi_core.metrics` stays at 100% line coverage, with no `pragma: no cover`.
  - mypy is strict over `bsi_core`.
  - Ruff line length is 80.
- **Tests:**
  - Tests never call Vertex. The live check in Task 9 is the only paid work.
  - There is no clock-freezing library. Pass `now` into pure functions, backdate rows with an owner `UPDATE`, and read the database clock with `func.now()`.
- **Environment:**
  - Always `cd /Users/vineet/Downloads/ADK/bsi-platform`; the shell's working directory resets between commands.
  - Never use `gcloud` or `bq`.
- **Commits:** conventional subjects. End each message with a **blank line** and then the `Co-Authored-By:` line from the current session's attribution reminder. Don't push.

## File map

| File | Tasks |
|---|---|
| `migrations/versions/0006_schedule.py` (new) | 1 |
| `packages/core/bsi_core/models.py` | 1 |
| `packages/core/bsi_core/scheduling.py` (new) | 2, 4, 5 |
| `packages/core/bsi_core/config.py` | 4 |
| `apps/api/bsi_api/routers/runs.py` | 2, 3 |
| `apps/api/bsi_api/routers/schedules.py` (new), `apps/api/bsi_api/main.py` | 7 |
| `apps/workers/bsi_workers/worker.py` | 6 |
| `packages/core/bsi_core/metrics.py` | 8 |
| `apps/api/bsi_api/routers/metrics.py` | 9 |
| `tests/integration/test_rls.py`, `test_isolation.py` | 1, 7, 9 |
| `docs/findings-slice3.md` (new), `docs/README.md` | 9 |

---

## Task 1: Migration 0006, the `Schedule` model and `due_schedules()`

**Model** (`models.py`, after `Job`):

```python
class Schedule(Tenant, Base):
    __tablename__ = "schedule"
    brand_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("brand.id"), unique=True
    )
    cadence: Mapped[str]
    hour_utc: Mapped[int]
    samples: Mapped[int] = mapped_column(server_default="2")
    status: Mapped[str] = mapped_column(server_default="active")
    next_run_at: Mapped[datetime] = mapped_column(TSZ)
    last_run_at: Mapped[datetime | None] = mapped_column(TSZ)
    last_result: Mapped[str | None]
    __table_args__ = (
        CheckConstraint(
            "cadence IN ('daily', 'every_3_days', 'weekly')",
            name="ck_schedule_cadence",
        ),
        CheckConstraint(
            "hour_utc BETWEEN 0 AND 23", name="ck_schedule_hour"
        ),
        CheckConstraint(
            "samples BETWEEN 1 AND 10", name="ck_schedule_samples"
        ),
        CheckConstraint(
            "status IN ('active', 'paused')", name="ck_schedule_status"
        ),
    )
```

Follow the existing `Observation` check-constraint style. Match `models.py` exactly: the same `TSZ` helper and the same name convention.

**Migration** `0006_schedule.py` (`revision = "0006"`, `down_revision = "0005"`):
1. `op.create_table("schedule", …)` mirroring the model: columns, FKs, the unique `brand_id` and the four checks. Autogenerate is fine as a starting point, but `alembic check` must then report no drift.
2. Row-level security, the same as 0002's `_policy`:

   ```python
   SETTING = "NULLIF(current_setting('app.org_id', true), '')::uuid"
   op.execute("ALTER TABLE schedule ENABLE ROW LEVEL SECURITY")
   op.execute("ALTER TABLE schedule FORCE ROW LEVEL SECURITY")
   op.execute(
       f"CREATE POLICY tenant ON schedule "
       f"USING (org_id = {SETTING}) WITH CHECK (org_id = {SETTING})"
   )
   op.execute(
       "GRANT SELECT, INSERT, UPDATE, DELETE ON schedule TO bsi_app"
   )
   ```

3. The cross-tenant listing function:

   ```python
   op.execute("""
       CREATE FUNCTION due_schedules()
       RETURNS TABLE(schedule_id uuid, org_id uuid)
       LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
         SELECT s.id, s.org_id FROM schedule s
         WHERE s.status = 'active' AND s.next_run_at <= now()
         ORDER BY s.next_run_at
       $$""")
   op.execute("REVOKE ALL ON FUNCTION due_schedules() FROM PUBLIC")
   op.execute("GRANT EXECUTE ON FUNCTION due_schedules() TO bsi_app")
   ```

4. `downgrade()`: `DROP FUNCTION due_schedules()`, then `op.drop_table("schedule")`.

**Tests:**
- `tests/integration/test_rls.py`:
  - add `"schedule"` to `TENANT_TABLES`;
  - add a schedule row to the `org_b` fixture: `m.Schedule(org_id=b.id, brand_id=bid, cadence="daily", hour_utc=3, next_run_at=datetime.now(UTC))`.
  - The existing tests then prove that the new table is isolated and that the list matches the schema.
- New `tests/integration/test_schedule_table.py`:
  - `test_due_schedules_lists_every_tenants_due_rows`: org A has one due schedule and one future schedule; org B has one due schedule and one paused schedule. `system_session()` + `SELECT * FROM due_schedules()` returns exactly the two due rows. A plain `SELECT count(*) FROM schedule` in that same session returns 0.
  - `test_schedule_checks`: bad `cadence`, `hour_utc` 24, `samples` 0 and `status` `'x'` each raise `IntegrityError` when inserted through the owner session.
  - `test_one_schedule_per_brand`: a second schedule for the same brand raises `IntegrityError`.

**Expected red:** `AttributeError: module 'bsi_core.models' has no attribute 'Schedule'`, or the RLS list test failing.

**Also run, with output in the report:**

```bash
OWNER_DATABASE_URL=postgresql+psycopg://bsi_owner:owner@localhost:5433/bsi_test uv run alembic check
OWNER_DATABASE_URL=postgresql+psycopg://bsi_owner:owner@localhost:5433/bsi_test uv run alembic downgrade 0005
OWNER_DATABASE_URL=postgresql+psycopg://bsi_owner:owner@localhost:5433/bsi_test uv run alembic upgrade head
uv run alembic upgrade head   # dev DB
```

**Commit:** `feat(db): schedule table with RLS and due_schedules() (0006)`

---

## Task 2: Move the enqueue into `bsi_core.scheduling`

This is a pure refactor. The proof is that `tests/integration/test_runs.py` passes **unchanged**.

New `packages/core/bsi_core/scheduling.py`:

```python
"""Shared run enqueue, and the scheduler that uses it."""

import uuid
from datetime import datetime

from sqlalchemy import func, literal, select, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from . import models as m


def active_prompts(s: Session, brand_id: uuid.UUID) -> int:
    return s.scalar(
        select(func.count()).where(
            m.Prompt.brand_id == brand_id, m.Prompt.status == "active"
        )
    ) or 0


def enqueue_run(
    s: Session,
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    samples: int,
    slot: datetime,
) -> tuple[m.Job, int]:
    """Find or create the slot's job and queue every active prompt x sample.

    Idempotent: the job and observation unique keys make a repeat a no-op.
    Returns the job and how many observations were newly queued.
    """
```

- The body is lines 56–129 of `routers/runs.py`, moved verbatim: the engine lookup, the job upsert and re-select, and the `generate_series` enqueue.
- Keep the 8,192-row comment.
- `retry_failed` stays in the router, after `enqueue_run` returns. The order doesn't matter: the insert never touches failed rows, and the requeue only touches failed rows.

`routers/runs.py::create_run` becomes: the 409 check, `if not active_prompts(...)` for the 422, the slot as before, `job, enqueued = enqueue_run(...)`, the `retry_failed` block, then the same response. Remove the imports that become unused.

**Red:** not applicable, since this is a refactor. Paste the green run of the **unchanged** `test_runs.py` and `test_full_flow.py`, and `git diff --stat tests/` showing no test changes.

**Commit:** `refactor(runs): share the enqueue through bsi_core.scheduling`

---

## Task 3: Default 2 samples per prompt

- `routers/runs.py`: `samples: int = Field(2, ge=1, le=10)`.
- `scripts/live_run.py:38`: `spec.get("samples", 2)`.
- Tests:
  - `test_runs.py::test_run_enqueues_prompts_times_samples`: 6 → 4, including the `(6, 6, …)` tuple.
  - `test_runs.py::test_new_prompt_joins_the_same_slot`: 3 → 2 and 9 → 6.
  - `test_full_flow.py`: 6 → 4 in the enqueued, done, `n` and list-length assertions, and `ci_low` for 4/4. Compute it with `wilson(4, 4)`; don't hard-code a guess.

**Red:** change the tests first; they fail on the old default.

**Commit:** `feat(runs): default to 2 samples per prompt (slice 2 design C)`

---

## Task 4: Time arithmetic and the daily budget

`config.py` gains:

```python
    # Slice 3: per-organization daily cap on scheduled runs (spec §3).
    daily_budget_usd: float = 2.0
    obs_cost_estimate_micros: int = 50_000
```

`scheduling.py` gains:

```python
CADENCE_DAYS = {"daily": 1, "every_3_days": 3, "weekly": 7}


def first_run(now: datetime, hour_utc: int) -> datetime:
    """The next hour_utc:00 UTC strictly after now."""


def advance(next_run_at: datetime, cadence: str, now: datetime) -> datetime:
    """Add the cadence interval until the result is after now (no backfill)."""


def budget_fits(s: Session, org_id: uuid.UUID, n_obs: int) -> bool:
    """True if n_obs more observations fit in the org's budget for today.

    Call inside the org's tenant transaction. The advisory lock is held to
    the end of that transaction, so two schedules of one org can't both
    pass on the same headroom.
    """
```

`budget_fits` SQL:
1. `SELECT pg_advisory_xact_lock(hashtext(:org))` with `org=str(org_id)`.
2. One statement for spend and pending:

   ```sql
   WITH day AS (
     SELECT date_trunc('day', now() AT TIME ZONE 'UTC')
            AT TIME ZONE 'UTC' AS start)
   SELECT
     coalesce(sum(o.cost_micros + coalesce(e.cost_micros, 0))
              FILTER (WHERE o.requested_at >= day.start), 0) AS spent,
     count(*) FILTER (
       WHERE o.status IN ('queued', 'running', 'retry')) AS pending
   FROM observation o
   LEFT JOIN extraction e ON e.observation_id = o.id
   CROSS JOIN day
   ```

   - The day boundary is computed in SQL, from the database clock.
   - Row-level security scopes the query to the organization. Don't reuse `spend.db_micros`: it uses the owner engine and sums every tenant.
3. `cap = round(settings.daily_budget_usd * 1_000_000)`, then return `spent + (pending + n_obs) * estimate <= cap`.
4. Add the comment: "A paid attempt that then fails records no cost; the estimate's headroom absorbs it."

**Tests:**
- New `tests/unit/test_scheduling.py`:
  - `first_run` before, at and after the hour, and across midnight (`hour_utc=0` at 23:30 gives the next day 00:00);
  - `advance` for each cadence;
  - `advance` from a `next_run_at` three intervals in the past, which lands on the first future point, not now + interval.
- New `tests/integration/test_budget.py`. Monkeypatch `bsi_core.scheduling.get_settings` with a `SimpleNamespace(daily_budget_usd=…, obs_cost_estimate_micros=…)`, the pattern in `test_api_v2.py`. Cases:
  - an empty org fits exactly up to the cap (equality fits; one more doesn't);
  - today's `done` observation cost plus its extraction cost counts;
  - a `done` observation whose `requested_at` was yesterday doesn't count (backdate it with an owner `UPDATE`);
  - `queued`, `running` and `retry` count as pending, and `failed` and `done` don't. Pass `status=` explicitly; the fixture default is `fetched`;
  - another org's spend doesn't count.

**Commit:** `feat(scheduling): cadence arithmetic and per-org daily budget`

---

## Task 5: `run_schedule`

```python
def run_schedule(org_id: uuid.UUID, schedule_id: uuid.UUID) -> str | None:
    """Run one due schedule; returns last_result, or None if it wasn't due.

    One transaction: lock the row, re-check it is due by the DB clock,
    enqueue or skip, then always advance next_run_at.
    """
    with tenant_session(org_id) as s:
        sch = s.get(m.Schedule, schedule_id, with_for_update=True)
        now = s.scalar(select(func.now()))
        if sch is None or sch.status != "active" or sch.next_run_at > now:
            return None
        brand = s.get_one(m.Brand, sch.brand_id)
        prompts = active_prompts(s, sch.brand_id)
        if brand.status == "archived":
            result = "skipped:brand_archived"
        elif not prompts:
            result = "skipped:no_active_prompts"
        elif not budget_fits(s, org_id, prompts * sch.samples):
            result = "skipped:budget"
        else:
            slot = sch.next_run_at.replace(minute=0, second=0, microsecond=0)
            _, n = enqueue_run(s, org_id, sch.brand_id, sch.samples, slot)
            result = f"enqueued:{n}"
        sch.last_run_at = now
        sch.last_result = result
        sch.next_run_at = advance(sch.next_run_at, sch.cadence, now)
        return result
```

This is the whole function. Keep the re-check: it's what stops a racing worker paying for a future slot (spec §2.4).

**Tests** (`tests/integration/test_scheduling.py`). Create schedules through the owner session with `next_run_at` in the past, relative to the DB clock.
- **Enqueue:** 2 active prompts × 2 samples gives `enqueued:4`. Four `queued` observations have `scheduled_slot` equal to the backdated `next_run_at` truncated to the hour. `next_run_at` is after now, and `last_run_at` is set.
- **Each skip:** archived brand, no active prompts (paused prompts only), and budget (monkeypatch a tiny `daily_budget_usd`). Each returns its `skipped:…` string, queues nothing, and **still advances** `next_run_at`.
- **Not due:** `next_run_at` in the future gives `None` and no changes. Paused gives `None`.
- **Crash-and-rerun:** run once, set `next_run_at` back to its old value with an owner `UPDATE`, run again. The result is `enqueued:0`, and the observation count is unchanged.
- **Stale:** `next_run_at` 10 days in the past on a daily schedule enqueues **once**, and `next_run_at` becomes the first future point.

**Commit:** `feat(scheduling): run a due schedule with lock, re-check and advance`

---

## Task 6: Worker

In `worker.py`:

```python
SCHEDULE_CHECK_SECONDS = 60


def run_due_schedules() -> int:
    """Run the due schedules; returns how many ran (see the code for
    the exact docstring: listing can raise, main() logs it)."""
    with system_session() as s:
        due = s.execute(
            text("SELECT schedule_id, org_id FROM due_schedules()")
        ).all()
    ran = 0
    for schedule_id, org_id in due:
        try:
            result = run_schedule(org_id, schedule_id)
            log.info("schedule %s: %s", schedule_id, result)
            ran += result is not None
        except Exception:
            log.exception("schedule %s failed", schedule_id)
    return ran
```

Match how `_claim()` opens `system_session()` and runs text SQL.

`main()` gains a sibling of the `reset_stale` block, with its own `last_schedule_check` and `SCHEDULE_CHECK_SECONDS`, wrapped in `try/except` with `log.exception`.

**Tests** (`tests/integration/test_worker.py`):
- `test_run_due_schedules_serves_every_tenant`: two orgs, each with a due schedule and an active prompt. The function returns 2, both have queued observations, and a second call returns 0.
- `test_one_failing_schedule_does_not_block_others`: monkeypatch `worker.run_schedule` to raise for one id and delegate to the real one otherwise. The other org is still served.

**Commit:** `feat(worker): run due schedules every minute`

---

## Task 7: Schedule API

New `apps/api/bsi_api/routers/schedules.py`, with `prefix="/brands/{brand_id}/schedule"`. Register it in `main.py` the way the other routers are.

```python
class ScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cadence: Literal["daily", "every_3_days", "weekly"]
    hour_utc: int = Field(ge=0, le=23)
    samples: int = Field(2, ge=1, le=10)
    status: Literal["active", "paused"] = "active"
```

- **PUT** `""`:
  - `brand_or_404`, then 409 `Problem` if the brand is archived.
  - Read `now` from the DB and set `next = first_run(now, body.hour_utc)`.
  - `pg_insert(m.Schedule).values(org_id, brand_id, next_run_at=next, **body.model_dump()).on_conflict_do_update(index_elements=["brand_id"], set_={...same fields...})`, then re-select.
  - Returns 200 with the view.
- **GET** `""`: `brand_or_404`, then 404 `Problem` if the brand has no schedule.
- **DELETE** `""`: 204, and 404 if none.
- **View:** `{brand_id, cadence, hour_utc, samples, status, next_run_at, last_run_at, last_result}`.

**Tests:**
- New `tests/integration/test_api_schedule.py`:
  - PUT creates, and a second PUT replaces it (one row, new values, `next_run_at` recomputed);
  - GET before any PUT returns 404;
  - DELETE returns 204, then GET returns 404;
  - an archived brand gets 409;
  - unknown fields, `hour_utc` 24 and cadence `hourly` each return 422;
  - `samples` defaults to 2;
  - `next_run_at` is after now, with minute and second 0 and hour = `hour_utc`.
- `tests/integration/test_isolation.py`:
  - add a schedule to org B in the `other` fixture;
  - add `CASES` for `GET`, `PUT` (`{"cadence": "weekly", "hour_utc": 1}`) and `DELETE` on `/v1/brands/{b}/schedule`;
  - in `test_org_b_data_is_untouched`, assert org B's schedule still exists with its original cadence.

**Commit:** `feat(api): brand schedule endpoints`

---

## Task 8: Deltas core (`metrics.py`, 100% coverage)

```python
def delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """95% Newcombe (method 10) interval for after - before, and a label.

    Assumes independent samples. Windows share prompts, so this is
    somewhat optimistic; for sov, mentions cluster within answers, which
    makes it more so. Across five metrics, expect about one false
    "significant" label in four comparisons when nothing changed.
    """
    p1, p2 = after["value"], before["value"]
    if p1 is None or p2 is None:
        return {"value": None, "ci_low": None, "ci_high": None,
                "label": "insufficient data"}
    d = p1 - p2
    low = d - math.hypot(p1 - after["ci_low"], before["ci_high"] - p2)
    high = d + math.hypot(after["ci_high"] - p1, p2 - before["ci_low"])
    label = ("increase" if low > 0 else "decrease" if high < 0
             else "no significant change")
    return {"value": d, "ci_low": low, "ci_high": high, "label": label}


def window_versions(
    s: Session, brand_id: uuid.UUID, f: Filters
) -> list[str]:
    """Distinct pipeline versions of the done observations in a window."""
```

- `window_versions` runs `SELECT DISTINCT e.pipeline_version FROM observation o JOIN extraction e ON e.observation_id = o.id WHERE {where} AND o.status = 'done' ORDER BY 1`, using `_where`.
- `brand_metrics` adds `"pipeline_versions": window_versions(s, brand_id, f)`.

```python
DELTA_METRICS = (
    "mention_rate", "recommendation_rate", "citation_rate",
    "prompt_coverage", "sov",
)


def brand_deltas(
    s: Session, brand_id: uuid.UUID, f: Filters, days: int, to: datetime
) -> dict[str, Any]:
    """Compare [to - days, to) with the `days` before it.

    Windows use claim time, like /metrics, so a boundary can split a run
    that is still draining.
    """
    mid, start = to - timedelta(days=days), to - timedelta(days=2 * days)
    before = brand_metrics(s, brand_id, replace(f, date_from=start, date_to=mid))
    after = brand_metrics(s, brand_id, replace(f, date_from=mid, date_to=to))
    versions = set(before["pipeline_versions"]) | set(after["pipeline_versions"])
    comparable = len(versions) <= 1
    return {
        "before": {"from": start, "to": mid, **before},
        "after": {"from": mid, "to": to, **after},
        "comparable": comparable,
        "reason": None if comparable else
            "windows use different pipeline versions "
            f"{sorted(versions)}; re-extract the older window",
        "deltas": {
            k: delta(before[k], after[k]) for k in DELTA_METRICS
        } if comparable else None,
    }
```

**Tests:**
- New `tests/unit/test_delta.py`, checking Newcombe 1998 Table II values with `rate()` inputs and `pytest.approx(abs=1e-3)`:

  | before | after | interval |
  |---|---|---|
  | 48/80 | 56/70 | [0.0524, 0.3339] |
  | 3/10 | 9/10 | [0.1705, 0.8090] |
  | 0/29 | 5/56 | [−0.0381, 0.1926] |
  | 0/10 | 10/10 | [0.6075, 1.0] |

  Also cover labels: `increase` (row 1), `decrease` (row 1 swapped), `no significant change` (row 3), and `insufficient data` (either side `rate(0, 0)`).
- `tests/integration/test_metrics.py`:
  - `test_rates` asserts `got["pipeline_versions"] == []`, since the scene has no extraction rows.
  - `test_brand_deltas_compares_windows`:
    - Put done observations in two backdated windows by setting `requested_at` with an owner `UPDATE`. Use distinct `sample_index` values for one prompt, because `make_observation` uses the current-hour slot.
    - Give each an extraction row with `pipeline_version="2"` (the insert pattern is in `test_spend.py`), and brand mentions as needed.
    - Assert both windows' `n`, `comparable is True`, and that each `DELTA_METRICS` key has a label.
  - `test_brand_deltas_refuses_mixed_versions`: one window's extraction is `"1"`. Assert `comparable is False`, `deltas is None`, and that the reason names both versions.
- **Coverage:** `--cov=bsi_core.metrics --cov-fail-under=100` must pass.

**Commit:** `feat(metrics): Newcombe deltas and pipeline-version comparability`

---

## Task 9: `GET /deltas`, live check and findings

In `routers/metrics.py`:

```python
@router.get("/deltas")
def get_deltas(
    brand_id: uuid.UUID,
    days: int = Query(7, ge=1, le=90),
    f: Filters = Depends(filters),
    c: Ctx = TENANT,
) -> dict[str, Any]:
```

- Respond 422 `Problem` if `f.date_from` is set: the windows define the start.
- `to = f.date_to or datetime.now(UTC)`.
- Call `brand_deltas`, then apply the same `experimental` overlay to `recommendation_rate` in both windows that `get_metrics` applies.

**Tests:**
- `test_api_v2.py` or a new file:
  - an empty brand returns 200 with `insufficient data` labels;
  - `date_from` returns 422;
  - `days=0` and `days=91` return 422.
- `test_isolation.py`: a `("GET", "/v1/brands/{b}/deltas", None)` case.

**Live check** (spec §8, about $0.47 at worst):
- Seed the org `"Slice3 check"`.
- Create a brand from the first 5 prompts of `eval/run1.json` through the API. Reuse `scripts/live_run.py`'s calls, or write a short script under `scripts/`.
- `PUT` a daily schedule, then backdate its `next_run_at` with an owner `UPDATE`.
- Start the API and the real worker, exporting `.env` first.
- Record:
  - the pickup time;
  - 10 of 10 observations `done`;
  - `last_result`;
  - the future `next_run_at`;
  - that a second pass enqueues nothing.
- Budget skip: restart the worker with `DAILY_BUDGET_USD=0.01`, backdate again, and confirm `skipped:budget` with nothing queued.
- `GET /deltas?days=1`: record the response.
- Stop the API and the worker, and confirm with `ps`. Record spend before and after in the report.

**`docs/findings-slice3.md`** covers:
- what shipped;
- the live-check numbers;
- budget behaviour;
- the delta semantics and their stated limits (spec §5.4);
- the cost of a daily schedule at 2 samples (prompts × 2 × measured cost per observation), compared with the budget default;
- follow-ups: time zones, backfill, per-org budget, the change feed and alerts.

Also add its row to `docs/README.md`, and add the plan's row there too.

**Commit:** `feat(api): deltas endpoint; slice 3 live check and findings`

---

## Definition of done

Spec §7, verified by a final whole-branch review, then one fix wave, then `superpowers:finishing-a-development-branch`. Merge with a **merge commit** so the hashes quoted in docs stay valid.
