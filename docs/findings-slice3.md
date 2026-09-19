# Slice 3 findings: scheduler and deltas

Date: 2026-09-20. Branch `slice3-scheduler-and-deltas`. The live numbers
come from one run of the real API and worker against Vertex (org
"Slice3 check", 5 prompts x 2 samples). The statistical numbers come from
the Task 8 review's Monte Carlo study, recorded in the SDD ledger
`.superpowers/sdd/2026-09-20-slice3-scheduler-and-deltas/progress.md`.

**Headline: the scheduler works unattended and the budget stops it.** A
daily schedule was picked up within one second of the worker starting,
enqueued and finished 10 of 10 observations with no retries, advanced
itself 24 hours, and enqueued nothing on the next pass. With the daily
budget lowered below the run's estimate, the same due schedule recorded
`skipped:budget` and queued nothing.

**Headline caveat: a delta label is weaker than it looks.** Five
proportion metrics at 95% each give about a 23% chance that at least one
is labelled `increase` or `decrease` when nothing has changed (section
3). Treat a single significant label as a prompt to look, never as a
finding.

## 1. What shipped

- `schedule` table: one row per brand (cadence, `hour_utc`, samples,
  status, `next_run_at`, `last_run_at`, `last_result`), under row-level
  security like every other tenant table.
- `PUT`/`GET`/`DELETE /v1/brands/{id}/schedule`. `PUT` always recomputes
  `next_run_at`, so re-activating a paused schedule cannot fire a stale
  run. 409 for an archived brand.
- `run_schedule()`: claims the schedule row `FOR UPDATE`, re-checks that
  it is due, enqueues a run, advances `next_run_at`, and records
  `last_result` (`enqueued:n`, `skipped:paused`, `skipped:archived`,
  `skipped:no_prompts`, `skipped:budget`).
- Per-organization daily budget, all-or-nothing at enqueue, under a
  per-org advisory lock. Default `DAILY_BUDGET_USD=2`.
- The worker checks for due schedules every 60 s alongside its queue
  loop.
- `POST /runs` and schedules default to **2 samples** (slice 2's design
  C), down from 3.
- `brand_deltas()` and `GET /v1/brands/{id}/deltas`: two windows, a
  Newcombe (1998, method 10) difference interval and a label per
  proportion metric, and a refusal to compare mixed pipeline versions.
- `/metrics` gained `pipeline_versions` (the distinct versions in the
  window); the old scalar `pipeline_version` stays.

## 2. Live check (org "Slice3 check", 2026-09-19 21:25 UTC)

5 prompts from `eval/run1.json`, daily schedule at `hour_utc=3`,
`next_run_at` backdated by one minute with an owner `UPDATE`.

| Observation | Value |
|---|---|
| Worker started | 21:25:45 UTC |
| Schedule picked up | 21:25:46 UTC (under 1 s; the budget is 60 s) |
| `last_result` | `enqueued:10` |
| Observations | **10 of 10 `done`**, 0 failed, 0 retries |
| Run duration | 2m56s (21:25:46 to 21:28:42) |
| `next_run_at` after the run | 2026-09-20 21:24:39 UTC (in the future) |
| Second pass | `ran 0 due schedules`, repeatedly; still 1 job |
| Engine cost per observation | $0.0104-$0.0441, total $0.1917 |
| Judge cost | $0.0065 over the 10 |
| **Total for the run** | **$0.1983**, or $0.0198 per observation |
| Answers that cited anything | 2 of 10 (14 citations) |
| Mentions extracted | 22 |

`next_run_at` advances from the slot that was claimed, not from the wall
clock, so a backdated schedule lands 24 h after the backdated time
(21:24:39), not 24 h after the run.

### Budget skip

The worker was restarted with `DAILY_BUDGET_USD=0.01` and `next_run_at`
backdated again. The next pass logged `schedule ...: skipped:budget`, and:

- `last_result = skipped:budget`;
- `next_run_at` still advanced, to 2026-09-20 21:30:40 UTC: a skip is not
  a retry;
- job count unchanged at 1, observation count unchanged at 10. Nothing
  was queued, so nothing was spent.

### `GET /deltas?days=1`

Exactly the spec section 8 expectation: the run sits in the after window,
the before window is empty, every label is `insufficient data`.

- after: `mention_rate` n=10, `prompt_coverage` n=5, `sov` n=22, all
  values 0.0 (the test brand is fictional and was never named);
  `pipeline_versions: ["2"]`.
- before: n=0 everywhere, `pipeline_versions: []`.
- `comparable: true`, `reason: null`, all five deltas
  `{"value": null, "ci_low": null, "ci_high": null, "label":
  "insufficient data"}`.
- `recommendation_rate` carries `experimental: true` in both windows, as
  `/metrics` does. The delta entry itself is not flagged.

### Spend

| | Ledger | DB since `spend_since` |
|---|---|---|
| Before | $6.714150 | $0.095353 |
| After | $6.714150 | $0.293606 |

The whole check cost **$0.198253**, against the $0.47 approved. The
ledger is untouched, as it should be: worker runs are counted from
observation rows, not from ledger entries.

## 3. Delta semantics and their limits

`d = p1 - p2` (after minus before), with a 95% Newcombe method-10
interval built from each window's Wilson bounds. `increase` if the lower
bound is above 0, `decrease` if the upper bound is below 0, otherwise
`no significant change`; `insufficient data` if either window is empty.
`avg_position` gets no delta: it is not a proportion.

Verified in Task 8: method 10 reproduces Newcombe 1998 Table II to within
4e-5, and swapping the bounds fails the tests.

Monte Carlo over about 2.6M draws (Task 8 review):

- **Coverage** of the nominal 95% interval: 94.1-99.8%. Conservative as p
  approaches 0 or 1; marginally anti-conservative at p = 0.5, a known
  method-10 aberration.
- **False-significant rate per metric, with no true change: 0.2-6.1%**,
  depending on p and n.
- Across the five metrics that get deltas, that is **about 23%** (worst
  case 27%) chance of at least one false label per comparison. This is
  what spec section 5.4 claims, now measured.

The stated limitations (spec section 5.4), all still true:

- Windows filter on claim time, so a boundary can split a run that is
  still draining. A schedule that fires near the boundary lands part of
  its run in each window.
- The two windows share prompts, so their samples are not independent.
  Newcombe assumes they are.
- `sov` counts mentions, which cluster within an answer, so its interval
  is too narrow and its false-significant rate is the worst of the five.
- No multiple-comparison correction is applied. The 23% above is the
  price.
- `recommendation_rate` is still experimental (slice 2, ruling R10), so
  its delta inherits that doubt.

Mixed pipeline versions across the two windows are refused: both windows'
values are returned with `deltas: null`, `comparable: false` and a reason
naming the versions. The fix is `scripts/reextract.py` on the older
window.

## 4. Cost of a daily schedule versus the budget

Cost per observation, measured: **$0.0198** in this check, **$0.0219**
over slice 2's 102 grounded answers. Take $0.022 as the planning figure.

| Brand size (prompts) | Observations/day at 2 samples | Cost/day | Cost/30 days |
|---|---|---|---|
| 5 | 10 | $0.22 | $6.60 |
| 20 | 40 | $0.88 | $26 |
| 50 | 100 | $2.20 | $66 |

Against the **$2/org/day** default:

- A 5-prompt brand uses about 11% of the budget; nine such brands fit.
- A 45-prompt organization is at the limit: 90 observations at $0.022 is
  $1.98.
- That headroom depends on the grounded share. Slice 2 measured $0.046
  per *searched* answer against $0.0125 unsearched, and only 26-33% of
  answers search (2 of 10 here). If grounding rose to 100%, $2 would buy
  about 43 observations, roughly 21 prompts: half the current ceiling.
  The budget default should be revisited if the grounded share moves.
- The budget is all-or-nothing per scheduled run: a run that would cross
  the line is skipped whole, not truncated. An organization with more
  than about 90 observations of daily schedules will therefore skip runs
  rather than partially complete them.

## 5. Known behaviour and defects

- **A schedule that always raises never advances.** `run_schedule` does
  its work in one transaction, so a failure rolls back the advance as
  well. The worker logs the exception and retries that schedule every
  60 s, indefinitely, with no alert. It does not block other schedules
  (proved in Task 6). Until alerts land, the only signal is
  `last_result` on `GET /schedule` staying stale.
- **Pipeline versions sort lexically** in the comparability reason, so a
  future `'10'` would print before `'2'`. Cosmetic only: comparability is
  a set-size test, not an ordering.
- **No time zones (D2).** `hour_utc` is UTC. A customer who wants 9am
  local must convert, and will drift by an hour across daylight saving.
- The per-org advisory lock serialises budget checks across the whole
  organization. Fine at this scale; it would become a queue at hundreds
  of schedules firing on the same hour.
- Deferred test coverage from Task 5, verified by hand instead: skip
  ordering, the stale-slot assertion, the cross-org id case.

## 6. Follow-ups

- **Time zones.** Store an IANA zone per schedule and compute the slot in
  it, so "9am local" survives daylight saving (D2 deferred this).
- **Backfill.** There is no way to run a schedule for a missed day. A
  worker down for a day silently loses that day's observations; the delta
  windows then compare unequal amounts of data with no warning that they
  do.
- **Per-organization budget override.** `DAILY_BUDGET_USD` is one global
  setting. A paying tenant and a trial tenant need different ceilings;
  the column belongs on `organization`.
- **Competitor change feed.** The deltas endpoint answers "did my numbers
  move"; nobody yet answers "which competitor moved, and in which
  prompts". That needs per-entity deltas and a diff of the entity set
  between windows.
- **Alerts.** Nothing watches `last_result`. A schedule can skip or fail
  forever unnoticed. When alerts land they must require *persistence*
  across runs, not a single significant label: section 3 says about one
  in four comparisons will produce one by chance.
- **A delta for `avg_position`.** Excluded because it is not a
  proportion. A rank-based test would cover the metric customers ask
  about first.
