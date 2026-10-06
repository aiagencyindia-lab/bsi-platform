# Slice 46 design: the SERP sweep counts waiting SERP jobs against the budget

## Context

Codebase facts: main `95d32ad`, checked 2026-10-07.

`queue_due_serp_audits()` (apps/workers/bsi_workers/worker.py, slice 43) checks each due brand with `budget_fits(s, org_id, 0, extra_micros=SERP_JOB_MICROS)`. `budget_fits` (packages/core/bsi_core/scheduling.py) counts today's recorded spend (`job.cost_micros` of non-run jobs created today, plus observations) and pending observations. A queued or running `audit_serp` job has recorded no cost yet, so it is not counted: within one sweep every brand of an org is checked against the same room, and an org with room for two $0.04 estimates and five due brands gets five jobs. The extra jobs fail as `budget` when `process_job` claims them, costing each brand a day and one of its three weekly attempts. The slice 43 final review deferred this (findings-slice43 §3, R10).

Classification: **bounded** — one existing function and its tests, no interface change. It was the first line of the first brainstorming reply, with the session model (Opus 5.5). The user's process asks for a spec and plan even for small changes, so this file exists.

Decisions approved in chat (2026-10-07), after approaches with trade-offs and a recommendation written in a chat message: count the org's waiting `audit_serp` jobs before each brand; over a running total kept inside one sweep (misses jobs waiting from earlier sweeps or "Run audit now"), or changing `budget_fits` to count every waiting job (a function the scheduler, the API and the worker share). The short design was approved in chat.

## Design

apps/workers/bsi_workers/worker.py, as a diff against main `95d32ad`:

```diff
@@ -838,6 +838,8 @@ def queue_due_serp_audits() -> int:
       a week;
     - a brand is skipped, with no job, while its org's budget has no
-      room for the job's estimate. It stays due and is queued once
-      there is room; process_job checks the budget again at claim time.
+      room for the job's estimate plus one estimate for each of the
+      org's audit_serp jobs still queued or running (those have
+      recorded no cost yet). It stays due and is queued once there is
+      room; process_job checks the budget again at claim time.
 
     ponytail: every due brand is queued in one sweep and jobs run one at
@@ -859,5 +861,15 @@ def queue_due_serp_audits() -> int:
         try:
             with tenant_session(org_id) as s:
-                if not budget_fits(s, org_id, 0, extra_micros=SERP_JOB_MICROS):
+                # ponytail: a "Run audit now" press committed between this
+                # count and the budget lock is missed; process_job's claim
+                # check still catches it. Lock first if that ever matters.
+                waiting = s.scalar(
+                    select(func.count()).where(
+                        m.Job.kind == "audit_serp",
+                        m.Job.status.in_(("queued", "running")),
+                    )
+                )
+                extra = SERP_JOB_MICROS * ((waiting or 0) + 1)
+                if not budget_fits(s, org_id, 0, extra_micros=extra):
                     continue
                 enqueue_job(
```

- Each brand's tenant session counts the org's `audit_serp` jobs that are `queued` or `running` (row-level security limits the count to the org) and asks `budget_fits` for room for that many estimates plus the brand's own.
- Each brand's job is committed before the next brand's check, so jobs queued earlier in the same sweep are counted, and so are jobs from earlier sweeps, a "Run audit now" press, and a job being run.
- Done and failed jobs are not counted: their cost is already in `job.cost_micros`.
- Unchanged: `budget_fits`, the API, `process_job` and its claim-time check.
- The ponytail comment names the one gap (R1).

## Testing

tests/integration/test_serp_audit.py gains a `_budget` helper and three tests (6 test items, 32 → 38):

```python
def _budget(owner, org, usd):
    with owner() as s, s.begin():
        s.execute(
            update(m.Organization)
            .where(m.Organization.id == org.id)
            .values(daily_budget_usd=Decimal(usd))
        )


def test_one_sweep_queues_no_more_serp_jobs_than_the_budget_has_room_for(
    configured, owner, make_org, make_brand
):
    org = make_org()
    for name in ("A", "B", "C"):
        _declared(owner, org, make_brand(org, name))
    _budget(owner, org, "0.08")  # room for two $0.04 estimates
    assert worker.queue_due_serp_audits() == 2
    assert len(_serp_jobs(owner)) == 2


@pytest.mark.parametrize("status", ["queued", "running"])
def test_a_waiting_serp_job_takes_budget_room(
    configured, owner, make_org, make_brand, status
):
    org = make_org()
    other = make_brand(org, "Other")  # no domain, so never due
    _job(owner, org, other, "audit_serp", status)
    bid = _declared(owner, org, make_brand(org))
    _budget(owner, org, "0.04")
    assert worker.queue_due_serp_audits() == 0
    _budget(owner, org, "0.08")
    assert worker.queue_due_serp_audits() == 1
    assert bid in {j.brand_id for j in _serp_jobs(owner)}


@pytest.mark.parametrize("which", ["other-org", "other-kind", "done"])
def test_other_jobs_take_no_serp_budget_room(
    configured, owner, make_org, make_brand, which
):
    org = make_org()
    _declared(owner, org, make_brand(org))
    if which == "other-org":
        elsewhere = make_org("B")
        _job(owner, elsewhere, make_brand(elsewhere), "audit_serp", "queued")
    elif which == "other-kind":
        _job(owner, org, make_brand(org, "Other"), "audit_crawl", "queued")
    else:
        _job(owner, org, make_brand(org, "Other"), "audit_serp", "done")
    _budget(owner, org, "0.04")
    assert worker.queue_due_serp_audits() == 1
```

The existing `test_the_sweep_skips_a_brand_while_the_budget_has_no_room` is unchanged and still passes. Expected gates: backend `1753 passed, 2 deselected` (1747 on main plus 6) with metrics coverage at 100%; web 49, unchanged (the web app is not touched).

### Proof

Run 2026-10-07 in the scratchpad on a copy of main's backend, against the shared test database (at 0026, main's head; no migration in this slice). The edit and the tests above are the ones it used.

- Red, main's code with the new tests: `3 failed, 35 passed` (the three that need waiting jobs counted).
- Green, patched: `38 passed`.
- `ruff check` and `ruff format` pass on the patched files.

Each change below fails at least one test:

| Mutant | Change | Failed | Failing tests |
|---|---|---|---|
| M1 | the count is ignored (one estimate per brand, as on main) | 3 | `test_a_waiting_serp_job_takes_budget_room[queued]`, `test_a_waiting_serp_job_takes_budget_room[running]`, `test_one_sweep_queues_no_more_serp_jobs_than_the_budget_has_room_for` |
| M2 | only `queued` jobs are counted | 1 | `test_a_waiting_serp_job_takes_budget_room[running]` |
| M3 | jobs of every kind are counted | 1 | `test_other_jobs_take_no_serp_budget_room[other-kind]` |
| M4 | jobs of every status are counted | 1 | `test_other_jobs_take_no_serp_budget_room[done]` |
| M5 | the brand's own estimate is left out | 4 | `test_a_waiting_serp_job_takes_budget_room[queued]`, `test_a_waiting_serp_job_takes_budget_room[running]`, `test_one_sweep_queues_no_more_serp_jobs_than_the_budget_has_room_for`, `test_the_sweep_skips_a_brand_while_the_b` |

No mutant covers another org's jobs (R2).

## Rulings

Quoted from the ledger:

> Ruling: R1. Decided: the waiting-job count runs before budget_fits takes the org's advisory lock, and a "Run audit now" press (which takes no lock) committed in that gap is not counted; a ponytail comment names this and the upgrade (lock first). Found by: the controller, writing the design. Why: process_job re-checks the budget when it claims the job, so a missed job costs at most one budget failure, as on main. Cost if wrong: in that rare race one extra job can be queued past the budget and fail at claim time. How named: in chat in the approved design, 2026-10-07.

> Ruling: R2. Decided: no mutant covers "another org's waiting jobs are not counted"; the count runs in the org's tenant session, so row-level security, not the sweep's code, excludes them, and the test test_other_jobs_take_no_serp_budget_room[other-org] pins the behaviour. Found by: the controller, running the proof. Why: a mutant would have to disable row-level security, outside this change. Cost if wrong: none to behaviour; the test still fails if the count ever ran outside the tenant session. How named: in chat, 2026-10-07, after the proof run.

## Deferred minors

None yet.

## Live check

None: dev has one brand with a domain due at a time, so the over-queueing case cannot be reproduced there without making up data.
