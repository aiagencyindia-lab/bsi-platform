# Slice 39 design: the DataForSEO adapter caps the cost of one call

## Context

Codebase facts: main `363a334`, checked 2026-10-03.

Open issue from slice 38 (docs/findings-slice37.md line 81, note of 2026-10-03): a very large provider cost would overflow the Integer `cost_micros` columns of `serp_audit` and `job`, so the failure could not be recorded; a later `claim_job()` fails the job as `stale` after 10 minutes, and the run's spend is never added to `job.cost_micros`, which both budget guards read. The user asked to "start the cost cap slice".

Facts read before the approaches:
- packages/core/bsi_core/providers/dataforseo.py:90-91: `_micros(cost)` returns `round(cost * 1_000_000)` for any int or float, with no bound; a bool is an int, so `true` counts as 1,000,000 micros and a negative cost gives negative micros (deferred minor "Task 2: minor (deferred): dataforseo.py:62 a bool cost (true) is counted as 1,000,000 micros; a negative cost gives negative micros", findings-slice37 line 80). `_micros` is called only in `_parse`: line 120 (the top-level cost when there are no tasks) and line 122 (the task's cost).
- apps/workers/bsi_workers/worker.py `run_serp_audit` adds each page's cost to `spent` and `meter.micros` and writes it to `serp_audit.cost_micros`; `_finish_job` adds `spent` to `job.cost_micros`. Both columns are `sa.Integer` (largest value 2,147,483,647 micros, about $2,147).
- An infinite cost already makes `_micros` raise (`OverflowError`); `serp()` returns `json` with cost 0 (`test_an_infinite_cost_is_json`), and on a non-2xx answer `_refused` returns `http` with cost 0 (slice 38 spec: "an unreadable cost (`_micros` raises)").
- The audit runs on demand only, at most `MAX_SERP_LOCALES` × 2 = 10 calls per job. The published price is $0.004 per call ($0.002 per page plus $0.002 for AI Overview loading).
- apps/workers/bsi_workers/worker.py:1177-1178, the `tick` comment, says "A row whose failure could not be recorded stays 'running'; reset_stale() hands it back after 10 minutes." `reset_stale()` calls `reset_stale_running()` (migrations 0002, 0004), which touches only observations; a job still `running` after 10 minutes is failed as `stale` by `claim_job()` (migration 0007).

Classification: **bounded** — one function in the existing adapter, its unit tests, and one comment; said in chat as the first line of the first brainstorming reply. The user's process rule asks for a spec even for small changes, so this file exists.

Decisions approved in chat (brainstorming on Fable 5.1, then Opus 5.5 from the spec on, 2026-10-03), each after approaches with trade-offs, the facts above and a recommendation written in a chat message before the question:
1. A cost above the cap is unreadable: error `json` (or `http` on a non-2xx answer), cost 0, as an infinite cost is today (R1), over clamping to the cap, or widening the columns to BigInteger.
2. The cap is $1 per call (R2), over $0.04 or $100.
3. A bool or negative cost is unreadable too (R3), over the cap alone, or also rejecting a missing or non-number cost.
4. The `tick` comment is fixed as its own commit in the code PR; the two slice 38 docs nits go in the post-merge docs PR (R4), over leaving all three, or putting all three in the code PR.
5. Design Sections 1 and 2, the text of each in chat before its approval question.

## Design

### The adapter

packages/core/bsi_core/providers/dataforseo.py, as a diff against main `363a334` (the exact change the plan applies):

```diff
-def _micros(cost: object) -> int:
-    return round(cost * 1_000_000) if isinstance(cost, int | float) else 0
+MAX_COST_USD = 1  # per call; the published price is $0.004
+
+
+def _micros(cost: object) -> int:
+    """The cost in micros. A missing or non-number cost is 0. A bool, a
+    negative number, or one above MAX_COST_USD raises ValueError."""
+    if isinstance(cost, bool):
+        raise ValueError("cost is a bool")
+    if not isinstance(cost, int | float):
+        return 0
+    if not 0 <= cost <= MAX_COST_USD:
+        raise ValueError("cost out of range")
+    return round(cost * 1_000_000)
```

Behaviour:
- A cost from 0 to $1 inclusive is recorded as before. A missing or non-number cost (a string, null, a list) is still 0.
- A bool (`true` or `false`), a negative number, a number above $1, infinity and NaN raise `ValueError` (infinity raised `OverflowError` before; the outcome is the same, since both are in `UNREADABLE`).
- On a 2xx answer, `serp()` catches the raise and returns `json`, cost 0, no items. On a non-2xx answer, `_refused` catches it and returns `http`, cost 0.
- A body that carries a provider error code and a bad cost loses the code (for example a `paused` answer with cost 5 becomes `json`, or `http` on a non-2xx answer), as with an infinite cost today.
- The largest cost one call can record is 1,000,000 micros, so a 10-call job records at most 10,000,000 micros, far below 2,147,483,647. No worker, schema, API or web change; no migration.

### The `tick` comment

apps/workers/bsi_workers/worker.py, its own commit:

```diff
-        # A row whose failure could not be recorded stays 'running';
-        # reset_stale() hands it back after 10 minutes.
+        # A row whose failure could not be recorded stays 'running':
+        # reset_stale() hands an observation back after 10 minutes,
+        # and claim_job() fails a job as 'stale' after 10 minutes.
```

### Tests

Appended to tests/unit/test_dataforseo.py, using its `body()`, `Fetch` and `_serp` helpers:

```python
BAD_COSTS = [1.000001, 1e12, -0.004, True, False]


@pytest.mark.parametrize("cost", BAD_COSTS)
def test_a_cost_out_of_range_is_json(cost):
    raw = body(cost=cost)
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "json")


def test_a_cost_at_the_cap_is_kept():
    page = _serp(Fetch(Response(200, body(cost=1))))
    assert (page.error, page.cost_micros) == (None, 1_000_000)


def test_a_refused_answer_with_a_cost_out_of_range_is_http():
    raw = body(cost=5, task_status=40210)
    assert _serp(Fetch(Response(402, raw))) == SerpPage([], 0, "http")


def test_a_top_level_error_with_a_cost_out_of_range_is_json():
    raw = json.dumps({"status_code": 40100, "cost": 5, "tasks": None})
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "json")
```

8 new cases; the file goes from 52 to 60. Existing tests are unchanged; `test_an_infinite_cost_is_json` and the zero-cost cases keep pinning infinity and the lower end. No worker test: the worker is unchanged, and the adapter can no longer hand it a cost above 1,000,000 micros.

### Proof

Run 2026-10-03 in the scratchpad (copies of `packages/core/bsi_core` imported via `PYTHONPATH`, each run's `bsi_core.providers.dataforseo.__file__` checked to be the copy; the test file is the repo's plus the block above):

| Code | Result | Failing tests |
|---|---|---|
| main (`363a334`) | `7 failed, 53 passed` | the 5 `BAD_COSTS` cases; the refused-answer case; the top-level-error case |
| patched | `60 passed` | — |
| m1: upper bound removed (`0 <= cost`) | `4 failed, 56 passed` | `1.000001`, `1e12`; the refused-answer case; the top-level-error case |
| m2: cap exclusive (`cost < MAX_COST_USD`) | `1 failed, 59 passed` | `test_a_cost_at_the_cap_is_kept` |
| m3: `MAX_COST_USD = 10` | `3 failed, 57 passed` | `1.000001`; the refused-answer case; the top-level-error case |
| m4: lower bound removed (`cost <= MAX_COST_USD`) | `1 failed, 59 passed` | `-0.004` |
| m5: bool check replaced by `pass` | `2 failed, 58 passed` | `True`, `False` |

`test_a_cost_at_the_cap_is_kept` passes on main (it pins the cap's edge against m2). `mypy --strict` on the patched module: no issues; `ruff check` and `ruff format --check` on the patched module and the test file: pass. The web code is unchanged.

### Docs

- Code PR: this spec, the plan, and two README rows (spec, plan).
- Post-merge docs PR: a dated note under findings-slice37 line 81 (the cost is capped at $1 a call; also cites slice 38 R11) and under line 80 (the bool and negative cases are closed); a dated note on the slice 38 spec's open-findings line that lists "a bool or negative cost"; slice 38 R11 marked as the writer's summary; the plan's "Changes made during execution". No findings file.

### Out of scope

- No live check: nothing here can be seen without a paid DataForSEO call, and the account is paused.
- A missing or non-numeric cost still records 0 (decision 3); a large cost the provider really charged is not counted by the budget guards (decision 1; the failure is now recorded on the row and the job).
- The other open adapter findings: a bool or float rank, a top-level `40102` with no tasks, tests where both levels carry errors.

## Rulings

- **R1: a cost above the cap is unreadable.** Decided: `_micros` raises above the cap, so the call is `json` (`http` on a non-2xx answer) with cost 0; the user chose this over clamping to the cap, or BigInteger columns. Found by: the brainstorm. Why: matches the existing infinity rule, no migration; the audit has no schedule, so a bad cost cannot repeat on its own. Cost if wrong: a cost the provider really charged above $1 is missing from the budget guards. Asked in chat.
- **R2: the cap is $1 per call.** Decided: `MAX_COST_USD = 1`; the user chose this over $0.04 or $100. Found by: the brainstorm. Why: 250× the published price; a 10-call job records at most $10, and overflowing `job.cost_micros` would take over 200 same-hour requeues. Cost if wrong: a real price above $1 a call makes every audit fail as `json`. Asked in chat.
- **R3: a bool or negative cost is unreadable.** Decided: `_micros` accepts only a plain number from 0 to the cap; the user chose this over the cap alone, or also rejecting a missing or non-number cost. Found by: the brainstorm (deferred minor, findings-slice37 line 80). Why: a negative cost would lower recorded spend; `true` would record $1. Cost if wrong: none known; no documented response has a bool or negative cost. Asked in chat.
- **R4: the leftovers.** Decided: the `tick` comment is fixed as its own commit in the code PR; slice 38 R11's marking and the findings-slice37 line 81 citation go in the post-merge docs PR; the user chose this over leaving all three, or putting all three in the code PR. Found by: the handoff's open issues 2 and 3. Why: the comment describes the overflow path this slice closes; docs nits belong with the docs. Cost if wrong: none. Asked in chat.
- **R5: the session switched to Opus 5.5.** Decided: from the spec on, commits carry "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" (the latest attribution reminder), and subagents are dispatched with no `model` parameter. Found by: the controller, when the user ran `/model claude-opus-5-5` after Section 2. Why: the memory rules bind the trailer to the latest reminder and omit the param on Opus. Cost if wrong: none. Named in chat when made.
