# Slice 3: Scheduler and deltas — design

- **Date:** 2026-09-20
- **Status:** Draft for review
- **Builds on:** slice 1 (`2026-09-19-slice1-measurement-core-design.md`), slice 2 (`2026-09-19-slice2-cost-and-trust-design.md`), `docs/findings-slice1.md`, `docs/findings-slice2.md`
- **PRD modules touched:** F03 (monitoring pipeline: cadence, idempotent slots), F05 (metrics honesty: deltas and "no significant change"), §10.5 (per-tenant daily budget)

## 1. Why this slice exists

Runs happen only when someone calls `POST /runs`, and metrics answer
"what is the rate now", not "did it change". The PRD's core promise
(F05) is numbers a brand can compare week over week, with deltas that
say "no significant change" unless the change clears the interval.

Two things block that:
1. **Nothing runs on a cadence.** F03 wants daily runs (every 3 days on
   Starter).
2. **Nothing compares two windows.** `brand_metrics` gives one window's
   rates and intervals, but no difference, no significance and no check
   that both windows were measured the same way.

Once runs fire unattended, a third problem follows: the worker has no
spend cap. Slice 2's guard covers scripts only.

### 1.1 Decisions made (user, 2026-09-20)

| # | Question | Decision |
|---|---|---|
| D1 | What makes a delta significant? | The 95% Newcombe interval for the difference of two proportions (method 10, Wilson-based) excludes zero. |
| D2 | How do schedules express time? | A cadence plus an hour of day in UTC. No time zones. |
| D3 | How does a daily budget behave? | Per tenant, all-or-nothing at enqueue: a scheduled run that doesn't fit is skipped whole, and the reason is recorded. |
| D4 | What if two windows used different pipeline versions? | "Not comparable": both windows' values are returned, with no delta and a reason. Versions are read from the stored extraction rows. |

Also adopted from slice 2 (§1.2 there, and `findings-slice2.md` §3):
the default is **2 samples per prompt** (design C).

### 1.2 Out of scope

- Time zones, and backfill of runs missed while the worker was down.
- A per-organization budget override, and budgets on on-demand runs.
- The `metric_daily` mart and nightly pre-aggregation.
- Per-competitor deltas and the competitor change feed (F07).
- Alerts (F15). Deltas are built so alerts can consume them later.
- Removing the legacy judge; it is still the eval baseline.
- Making the Gemini adapter's client setup thread-safe. The worker is
  single-threaded.

## 2. Schedules

### 2.1 Table `schedule` (migration 0006)

One schedule per brand. The engine is fixed to Gemini today, so there
is no `engine_id`.

| Column | Type | Rule |
|---|---|---|
| id, created_at, org_id | Tenant mixin | as every tenant table |
| brand_id | uuid FK brand | **unique** |
| cadence | text | CHECK in `daily`, `every_3_days`, `weekly` |
| hour_utc | int | CHECK 0–23 |
| samples | int | CHECK 1–10, default 2 |
| status | text | CHECK in `active`, `paused`; default `active` |
| next_run_at | timestamptz | not null |
| last_run_at | timestamptz | null until the first run |
| last_result | text | e.g. `enqueued:40`, `skipped:budget`, `skipped:no_active_prompts`, `skipped:brand_archived` |

Tenancy follows migration 0002: ENABLE and FORCE row-level security with
the same `tenant` policy. The grant to `bsi_app` must be **explicit**,
because 0002's `GRANT … ON ALL TABLES` only covered tables that existed
then.

### 2.2 Finding due schedules across tenants

`due_schedules()` returns `(schedule_id, org_id)` for every active
schedule with `next_run_at <= now()`. It is `SECURITY DEFINER` with
`SET search_path = public`, EXECUTE is revoked from PUBLIC and granted
to `bsi_app`, exactly like `claim_observation()`. It takes no row locks:
they would be released when its transaction ends, before the schedule
is processed. Locking happens in §2.4 instead.

### 2.3 Time arithmetic

- `first_run(now, hour_utc)`: the next time at `hour_utc:00` UTC that is
  after `now`.
- `advance(next_run_at, cadence, now)`: add the cadence interval (1, 3
  or 7 days) until the result is after `now`. Missed runs are **not**
  backfilled; a worker that was down for two days runs once, then moves on.

### 2.4 Running a schedule

`run_schedule(org_id, schedule_id)` does everything in **one**
`tenant_session` transaction:

1. Lock the row (`SELECT … FOR UPDATE`) and read `now()` from the
   database. Return without changes unless the schedule is active and
   `next_run_at <= now`. This matters: without the re-check, a second
   worker that listed the schedule before the first one advanced it
   would enqueue a *future* slot, which is a real second paid run.
2. Decide:
   - brand archived → `skipped:brand_archived`;
   - no active prompts → `skipped:no_active_prompts`;
   - budget doesn't fit (§3) → `skipped:budget`;
   - otherwise enqueue with `slot = next_run_at` truncated to the hour.
3. **Always** set `last_run_at = now`, `last_result`, and
   `next_run_at = advance(...)`, skips included. Otherwise a skipped
   schedule would fire again every minute.

Idempotency comes from the existing unique keys: job
`(brand_id, kind, scheduled_slot)` and observation
`(prompt_id, engine_id, scheduled_slot, sample_index)`. Because the
slot comes from `next_run_at`, not the clock, a crash after enqueue but
before commit re-enqueues the same slot as a no-op.

A scheduled run and an on-demand run in the same UTC hour share one job
and one set of observations. That's intended: they measure the same
thing.

### 2.5 Shared enqueue

The job upsert and the `INSERT … SELECT generate_series` enqueue move
from `routers/runs.py` into `bsi_core.scheduling`:

- `active_prompts(s, brand_id) -> int`
- `enqueue_run(s, org_id, brand_id, samples, slot) -> (Job, int)`

The router keeps its 409 (archived) and 422 (no active prompts) checks
and `retry_failed`. The on-demand slot stays the current UTC hour.

### 2.6 Worker

`run_due_schedules()` lists due schedules through `system_session()` and
calls `run_schedule` for each, catching errors per schedule so one bad
schedule can't block other tenants. `main()` calls it every 60 seconds,
next to the existing stale-row reset.

## 3. Daily budget

`budget_fits(s, org_id, n_obs) -> bool`, called inside the schedule's
tenant transaction:

1. Take `pg_advisory_xact_lock(hashtext(org_id))`, so two schedules of
   the same organization can't both pass on the same headroom.
2. **Spent today:** `observation.cost_micros + extraction.cost_micros`
   for observations whose `requested_at` falls on the current UTC day.
   `requested_at` is set when a worker claims the row, which is when
   money is spent. Row-level security scopes the sum to the tenant.
3. **Committed:** observations still `queued`, `running` or `retry`,
   times the per-observation estimate.
4. Fits iff `spent + committed + n_obs × estimate ≤ cap`.

Settings:
- `daily_budget_usd = 2.0` per organization.
- `obs_cost_estimate_micros = 50_000`, above the measured cost of an
  answer that searched ($0.0456) plus the judge ($0.0008).

Known under-count: a paid attempt that then fails records no cost. The
estimate's headroom absorbs it.

The budget blocks **scheduled** runs only. An on-demand run is a
deliberate human action; it counts toward the day's spend but is never
refused.

## 4. API

| Method | Path | Behaviour |
|---|---|---|
| PUT | `/v1/brands/{id}/schedule` | Create or replace (upsert on `brand_id`). Body: `cadence`, `hour_utc`, `samples` (default 2), `status` (default `active`); unknown fields rejected. 409 for an archived brand. Always recomputes `next_run_at = first_run(now, hour_utc)`. |
| GET | `/v1/brands/{id}/schedule` | The schedule, including `next_run_at`, `last_run_at`, `last_result`. 404 if none. |
| DELETE | `/v1/brands/{id}/schedule` | Remove it. 204. |
| GET | `/v1/brands/{id}/deltas` | §5. Query: `days` (1–90, default 7), plus the existing `engine`, `locale_id`, `prompt_ids` and `date_to` filters. `date_from` is rejected with 422, because the windows define it. |

`POST /runs` keeps its shape; its `samples` default changes from 3 to 2.
A cross-tenant brand id returns 404 on every route, as everywhere else.

## 5. Deltas

### 5.1 Windows

For `days = d` and end `to` (`date_to`, or now):
- after = `[to − d, to)`
- before = `[to − 2d, to − d)`

Windows filter on `observation.requested_at`, like `/metrics`, so the
two endpoints agree. Each window is one `brand_metrics` call.

### 5.2 Significance (D1)

For each proportion metric, with p₁ the after rate and p₂ the before
rate, each with Wilson bounds (l, u), d = p₁ − p₂:

- lower = d − √((p₁ − l₁)² + (u₂ − p₂)²)
- upper = d + √((u₁ − p₁)² + (p₂ − l₂)²)

Label:
- `increase` if lower > 0;
- `decrease` if upper < 0;
- `no significant change` otherwise;
- `insufficient data` if either window has no observations.

Metrics with deltas: `mention_rate`, `recommendation_rate` (still
flagged experimental), `citation_rate`, `prompt_coverage`, `sov`.
`avg_position` gets none, because it isn't a proportion.

### 5.3 Comparability (D4)

`window_versions` lists the distinct `extraction.pipeline_version`
values among done observations in a window. `/metrics` gains a
`pipeline_versions` field with this list; the existing
`pipeline_version` field stays for compatibility.

The two windows are comparable iff together they use at most one
version. If not, the response has both windows' values, no deltas, and
`comparable: false` with the reason. The fix is to re-extract the older
window with `scripts/reextract.py`.

### 5.4 Stated limitations

These go in code comments and in the findings:
- Windows are by claim time, so a window boundary can split a run that
  is still draining.
- The windows share prompts, so their samples are not strictly
  independent; Newcombe assumes they are.
- `sov` counts mentions, which cluster within answers, so its interval
  is too narrow.
- Five metrics at 95% each give about a 23% chance that at least one is
  labelled significant when nothing changed.

## 6. Testing

- Unit: `first_run`, `advance`, and `delta` against Newcombe 1998
  Table II (e.g. 56/70 vs 48/80 → [0.0524, 0.3339]).
- Integration:
  - the new table in the row-level-security suite, and `due_schedules()`
    across two tenants;
  - budget arithmetic, including the day boundary and pending rows;
  - `run_schedule`: enqueue, each skip, not-due no-op, crash-and-rerun,
    and a stale `next_run_at`;
  - the worker serving two tenants with one failing schedule;
  - the schedule and deltas endpoints, with rows in the isolation suite;
  - deltas over backdated windows, including a mixed-version window.
- `bsi_core.metrics` stays at 100% line coverage.
- One live check through the real API and worker (§8).

## 7. Definition of done

1. A brand can have a schedule; the worker runs it at its UTC hour and
   advances it; paused, archived and no-prompt schedules skip and advance.
2. A scheduled run that would exceed the organization's daily budget is
   skipped whole and records `skipped:budget`.
3. `POST /runs` and schedules default to 2 samples.
4. `GET /deltas` returns both windows, a Newcombe interval and label per
   proportion metric, and refuses to compare mixed pipeline versions.
5. Gate green, including 100% coverage of `bsi_core.metrics`; the live
   check passes; `docs/findings-slice3.md` records the results.

## 8. Live check

About $0.47 at worst (10 observations). Create a brand with 5 prompts,
`PUT` a daily schedule, backdate its `next_run_at`, and start the API
and the real worker. Confirm:
- the worker picks it up within 60 seconds;
- 10 observations finish `done` and `last_result = enqueued:10`;
- `next_run_at` is in the future and a second pass enqueues nothing.

Then lower `DAILY_BUDGET_USD` below the run's estimate, backdate again,
and confirm `skipped:budget` with nothing queued. Finally `GET /deltas`
shows the run in the after window and "insufficient data" for the
empty before window.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Two workers run the same schedule | Row lock and due re-check (§2.4); unique slots make any duplicate enqueue a no-op |
| Budget raced by two schedules of one org | Per-org advisory lock (§3) |
| A schedule skips forever and no one notices | `last_result` on GET; alerts are a later slice |
| False "significant" labels | Stated in the response docs and findings (§5.4); alerts must require persistence |
| A pipeline change fakes a delta | Mixed versions are refused (§5.3) |
| Cost per observation is above the PRD target | Unchanged by this slice; the budget bounds daily exposure |
