# Slice 39 design: the DataForSEO adapter caps the cost of one call

## Context

Codebase facts: main `363a334`, checked 2026-10-03.

Open issue from slice 38 (docs/findings-slice37.md line 81, note of 2026-10-03): a very large provider cost would overflow the Integer `cost_micros` columns of `serp_audit` and `job`, so the failure could not be recorded; a later `claim_job()` fails the job as `stale` after 10 minutes, and the run's spend is never added to `job.cost_micros`, which both budget guards read. The user asked to "start the cost cap slice".

Facts read before the approaches:
- packages/core/bsi_core/providers/dataforseo.py:90-91: `_micros(cost)` returns `round(cost * 1_000_000)` for any int or float, with no bound; a bool is an int, so `true` counts as 1,000,000 micros and a negative cost gives negative micros (deferred minor "Task 2: minor (deferred): dataforseo.py:62 a bool cost (true) is counted as 1,000,000 micros; a negative cost gives negative micros", findings-slice37 line 80). `_micros` is called only in `_parse`: line 120 (the top-level cost when there are no tasks) and line 122 (the task's cost).
- apps/workers/bsi_workers/worker.py `run_serp_audit` adds each page's cost to `spent` and `meter.micros` and writes it to `serp_audit.cost_micros`; `_finish_job` adds the run's spend (`meter.micros` on success, worker.py:1138; `SerpFailed.cost_micros`, which is `run_serp_audit`'s `spent` (0 before any call, worker.py:1003), on failure, worker.py:1066, 1069, 1152) to `job.cost_micros`. Both columns are `sa.Integer` (largest value 2,147,483,647 micros, about $2,147). A same-hour requeue reuses the job row and leaves its `cost_micros` alone, so a retry accumulates (packages/core/bsi_core/scheduling.py:251-253).
- An infinite cost already makes `_micros` raise (`OverflowError`); `serp()` returns `json` with cost 0 (`test_an_infinite_cost_is_json`), and on a non-2xx answer `_refused` returns `http` with cost 0 (slice 38 spec: "an unreadable cost (`_micros` raises)").
- The audit runs on demand only (queued only from apps/api/bsi_api/routers/audits.py), at most `MAX_SERP_LOCALES` × 2 = 10 calls per attempt. The expected price is about $0.004 per call, *inferred* from the published live price of $0.002 per page plus one base price for AI Overview loading (findings-slice37 line 59); the real cost per call is still unconfirmed (findings-slice37 line 71).
- apps/workers/bsi_workers/worker.py:1177-1178, the `tick` comment, says "A row whose failure could not be recorded stays 'running'; reset_stale() hands it back after 10 minutes." `reset_stale()` calls `reset_stale_running()` (migrations 0002, 0004), which touches only observations: it retries one whose `requested_at` is over 10 minutes old, or fails it on its third attempt. The next `claim_job()` fails a job `running` for over 10 minutes as `stale` (migration 0007).

Classification: **bounded** — one function in the existing adapter, its unit tests, and one comment; said in chat as the first line of the first brainstorming reply. The user's process rule asks for a spec even for small changes, so this file exists.

Decisions approved in chat (brainstorming on Fable 5.1, then Opus 5.5 from the spec on, 2026-10-03), each after approaches with trade-offs, the facts above and a recommendation written in a chat message before the question:
1. A cost above the cap is unreadable: error `json` (or `http` on a non-2xx answer), cost 0, as an infinite cost is today (R1), over clamping to the cap, or widening the columns to BigInteger.
2. The cap is $1 per call (R2), over $0.04 or $100.
3. A bool or negative cost is unreadable too (R3), over the cap alone, or also rejecting a missing or non-number cost.
4. The `tick` comment is fixed as its own commit in the code PR; the two slice 38 docs nits go in the post-merge docs PR (R4), over leaving all three, or putting all three in the code PR.
5. Design Sections 1 and 2, the text of each in chat before its approval question.
6. After the spec review of 7664abd: the `tick` comment's precise four-line wording (R8), over the approved three lines, or a pointer to the migrations.
7. After the spec review of 7664abd: the bad-cost test is named `test_a_bad_cost_is_json` (R9), over splitting out the bools, or keeping `test_a_cost_out_of_range_is_json`.

## Design

### The adapter

packages/core/bsi_core/providers/dataforseo.py: the diff below replaces lines 90-91 of main `363a334`; `MAX_COST_USD` goes directly above `_micros` (the exact change the plan applies):

```diff
-def _micros(cost: object) -> int:
-    return round(cost * 1_000_000) if isinstance(cost, int | float) else 0
+MAX_COST_USD = 1  # per call; the expected price is about $0.004
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
- A bool (`true` or `false`), a negative number, a number above $1, infinity and NaN raise `ValueError` (infinity raised `OverflowError` before; NaN raised `ValueError` at `round()` before; the outcome is the same, since both are in `UNREADABLE`).
- On a 2xx answer, `serp()` catches the raise and returns `json`, cost 0, no items. On a non-2xx answer, `_refused` catches it and returns `http`, cost 0.
- A body that carries a provider error code and a bad cost loses the code (for example a `paused` answer with cost 5 becomes `json`, or `http` on a non-2xx answer), as with an infinite cost today.
  - Note (2026-10-03, slice 40): closed: an error answer now keeps its code and records cost 0 when its cost is bad; a success with a bad cost is still `json` (docs/superpowers/specs/2026-10-03-slice40-serp-code-on-bad-cost-design.md, R1).
- The largest cost one call can record is 1,000,000 micros, so one attempt of a 10-call job records at most 10,000,000 micros. The job row accumulates across same-hour requeues (scheduling.py:251-253), so overflowing `job.cost_micros` would take 215 full attempts in one hour (2,147,483,647 / 10,000,000 = 214.7; R2). No worker, schema, API or web change; no migration.

### The `tick` comment

apps/workers/bsi_workers/worker.py, its own commit (R8):

```diff
-        # A row whose failure could not be recorded stays 'running';
-        # reset_stale() hands it back after 10 minutes.
+        # A row whose failure could not be recorded stays 'running':
+        # reset_stale() retries an observation (or fails it on its
+        # third attempt) once it is over 10 minutes old; the next
+        # claim_job() fails a job running over 10 minutes as 'stale'.
```

### Tests

Appended to tests/unit/test_dataforseo.py, using its `body()`, `Fetch` and `_serp` helpers:

```python
BAD_COSTS = [1.000001, 1e12, -0.004, float("nan"), True, False]


@pytest.mark.parametrize("cost", BAD_COSTS)
def test_a_bad_cost_is_json(cost):
    raw = body(cost=cost)
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "json")


def test_a_cost_at_the_cap_is_kept():
    page = _serp(Fetch(Response(200, body(cost=1))))
    assert (page.error, page.cost_micros) == (None, 1_000_000)


@pytest.mark.parametrize("cost", [None, "0.004", [1]])
def test_a_non_number_cost_is_zero(cost):
    page = _serp(Fetch(Response(200, body(cost=cost))))
    assert (page.error, page.cost_micros) == (None, 0)
    assert page.items


def test_a_missing_cost_is_zero():
    doc = json.loads(body())
    del doc["tasks"][0]["cost"]
    page = _serp(Fetch(Response(200, json.dumps(doc))))
    assert (page.error, page.cost_micros) == (None, 0)
    assert page.items


def test_a_refused_answer_with_a_cost_out_of_range_is_http():
    raw = body(cost=5, task_status=40210)
    assert _serp(Fetch(Response(402, raw))) == SerpPage([], 0, "http")


def test_a_top_level_error_with_a_cost_out_of_range_is_json():
    raw = json.dumps({"status_code": 40100, "cost": 5, "tasks": None})
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "json")
```

13 new cases; the file goes from 52 to 65. Existing tests are unchanged; `test_an_infinite_cost_is_json` and the zero-cost cases keep pinning infinity and the lower end. `BAD_COSTS` and the non-number and missing cases go through the task-level call (line 122); the top-level call (line 120) is pinned only for an above-cap cost, by `test_a_top_level_error_with_a_cost_out_of_range_is_json`; both calls go through the same `_micros`. No worker test: the worker is unchanged, and the adapter can no longer hand it a cost above 1,000,000 micros.

- Note (2026-10-03, after slice 40, PR #80): `test_a_top_level_error_with_a_cost_out_of_range_is_json` is now `test_a_top_level_error_with_a_bad_cost_keeps_its_code` and expects `auth`, not `json`; `test_a_refused_answer_with_a_cost_out_of_range_is_http` is now `test_a_refused_answer_with_a_bad_cost_keeps_its_code` and expects `funds`, not `http`; on the error paths both calls now go through `_error_micros` (which calls `_micros` and turns a bad cost into 0), and only a success's cost goes through `_micros` directly (docs/superpowers/specs/2026-10-03-slice40-serp-code-on-bad-cost-design.md, R1, R9, R11).

### Proof

Run 2026-10-03 in the scratchpad (copies of `packages/core/bsi_core` imported via `PYTHONPATH`, each run's `bsi_core.providers.dataforseo.__file__` checked to be the copy; the test file is the repo's plus the block above):

| Code | Result | Failing tests |
|---|---|---|
| main (`363a334`) | `7 failed, 58 passed` | `BAD_COSTS` `1.000001`, `1e12`, `-0.004`, `True`, `False`; the refused-answer case; the top-level-error case |
| patched | `65 passed` | — |
| m1: upper bound removed (`0 <= cost`) | `4 failed, 61 passed` | `1.000001`, `1e12`; the refused-answer case; the top-level-error case |
| m2: cap exclusive (`cost < MAX_COST_USD`) | `1 failed, 64 passed` | `test_a_cost_at_the_cap_is_kept` |
| m3: `MAX_COST_USD = 10` | `3 failed, 62 passed` | `1.000001`; the refused-answer case; the top-level-error case |
| m4: lower bound removed (`cost <= MAX_COST_USD`) | `1 failed, 64 passed` | `-0.004` |
| m5: bool check replaced by `pass` | `2 failed, 63 passed` | `True`, `False` |
| m6: a non-number cost raises instead of returning 0 | `4 failed, 61 passed` | the 3 `test_a_non_number_cost_is_zero` cases; `test_a_missing_cost_is_zero` |

`test_a_cost_at_the_cap_is_kept`, the non-number cases and the missing case pass on main (they pin existing behaviour against m2 and m6). The `nan` case passes on main and fails on no mutant tried: `round()` rejects NaN even when a range check lets it through. `mypy --strict` on the patched module: no issues; `ruff check` and `ruff format --check` on the patched module and the test file: pass. The web code is unchanged.

### Docs

- Code PR: this spec, the plan, and two README rows (spec, plan).
- Post-merge docs PR: a dated note under findings-slice37 line 81 (the cost is capped at $1 a call; also cites slice 38 R11) and under line 80 (the bool and negative cases are closed) and line 86 (a missing and a non-numeric cost are now tested); a dated note on the slice 38 spec's open-findings line that lists "a bool or negative cost"; slice 38 R11 marked as the writer's summary; the plan's "Changes made during execution". No findings file.

### Out of scope

- No live check: nothing here can be seen without a paid DataForSEO call, and the account is paused.
- A missing or non-numeric cost still records 0 (decision 3); a large cost the provider really charged is not counted by the budget guards (decision 1; the failure is now recorded on the row and the job).
- The other open adapter findings: a bool or float rank, a top-level `40102` with no tasks, tests where both levels carry errors.

## Rulings

- **R1: a cost above the cap is unreadable.** Decided: `_micros` raises above the cap, so the call is `json` (`http` on a non-2xx answer) with cost 0; the user chose this over clamping to the cap, or BigInteger columns. Found by: the brainstorm. Why: matches the existing infinity rule, no migration; the audit has no schedule, so a bad cost cannot repeat on its own. Cost if wrong: a cost the provider really charged above $1 is missing from the budget guards. Asked in chat.
- **R2: the cap is $1 per call.** Decided: `MAX_COST_USD = 1`; the user chose this over $0.04 or $100. Found by: the brainstorm. Why: 250× the expected price; one attempt of a 10-call job records at most $10, and overflowing `job.cost_micros` would take 215 full same-hour attempts. Cost if wrong: a real price above $1 a call makes every audit fail as `json`. Asked in chat.
- **R3: a bool or negative cost is unreadable.** Decided: `_micros` accepts only a plain number from 0 to the cap; the user chose this over the cap alone, or also rejecting a missing or non-number cost. Found by: the brainstorm (deferred minor, findings-slice37 line 80). Why: a negative cost would lower recorded spend; `true` would record $1. Cost if wrong: none known; no documented response has a bool or negative cost. Asked in chat.
- **R4: the leftovers.** Decided: the `tick` comment is fixed as its own commit in the code PR; slice 38 R11's marking and the findings-slice37 line 81 citation go in the post-merge docs PR; the user chose this over leaving all three, or putting all three in the code PR. Found by: the handoff's open issues 2 and 3. Why: the comment describes the overflow path this slice closes; docs nits belong with the docs. Cost if wrong: none. Asked in chat.
- **R5: the session switched to Opus 5.5.** Decided: from the spec on, commits carry "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" (the latest attribution reminder), and subagents are dispatched with no `model` parameter. Found by: the controller, when the user ran `/model claude-opus-5-5` after Section 2. Why: the memory rules bind the trailer to the latest reminder and omit the param on Opus. Cost if wrong: none. Named in chat when made.
- **R6: a test pins a missing or non-number cost as 0.** Decided: `test_a_non_number_cost_is_zero` (`None`, `"0.004"`, `[1]`) and `test_a_missing_cost_is_zero`, with mutant m6 in the proof; the file goes to 65. Found by: the spec review of 7664abd (Important 1: a mutant raising on a non-number passed all 60 tests). Why: R3's chosen behaviour had no pinning test. Cost if wrong: none. Named in chat when made.
- **R7: the spec review's accuracy points.** Decided: the $0.004 price is stated as *inferred* (spec and code comment, "the expected price is about $0.004"); the 10,000,000-micro bound is per attempt, with same-hour accumulation stated; `_finish_job`'s spend is named for both outcomes; `float("nan")` joins `BAD_COSTS`, and the proof states it fails on no mutant tried; the diff's placement is stated; the top-level path's coverage is stated. Found by: the spec review of 7664abd (Minors 1, 2, 3, 5, 6, 8). Why: no claim wider than its source. Cost if wrong: none. Named in chat when made.
- **R8: the precise `tick` comment.** Decided: the four-line wording in "The `tick` comment"; the user chose this over the approved three lines, or a pointer to the migrations. Found by: the spec review of 7664abd (Minor 4). Why: the comment's job is accuracy. Cost if wrong: none. Asked in chat.
- **R9: the bad-cost test name.** Decided: `test_a_bad_cost_is_json`; the user chose this over splitting out the bools, or keeping `test_a_cost_out_of_range_is_json`. Found by: the spec review of 7664abd (Minor 7). Why: true for every case, including bools and NaN. Cost if wrong: none. Asked in chat.
- **R10: the re-review's one minor was applied, with no further re-review.** Decided: the facts bullet says `SerpFailed.cost_micros` is `run_serp_audit`'s `spent` "(0 before any call, worker.py:1003)". Found by: the re-review of cf43eeb (Minor 1, optional; verdict "Ready for the user's review? Yes"). Why: the early `serp_not_configured` raise passes a literal 0. Cost if wrong: none; wording only, the recorded amount is the same. Named in chat when made.
- **R11: the plan review's six minors were applied.** Decided: the adapter commit message says infinity and NaN already gave `json`; the plan's departures list names Step 2's repeat of the proof's main row; every `pgrep` command carries the `cd` prefix; expected pytest lines read "a line starting with"; the README spec row uses a straight apostrophe; the plan's Interfaces line names NaN and infinity among the costs that raise (the docstring stays as this spec has it). Found by: the plan review of aee7bf1 (0 Critical, 0 Important, 6 Minor; "Ready to execute? With fixes"). Why: no overstated commit message, and every command and expected output as the implementer sees it. Cost if wrong: none; wording only. Named in chat when made.
- **R12: no fix wave after the final review.** (Added after merge.) The ledger line, as recorded: "Ruling: R12 — Decided: no fix wave after the final review; Minor 1 (docstring NaN) stays deferred, Minor 2 goes into the post-merge docs PR as the spec plans, Minor 3 is accepted behaviour already in the spec, and the Task 1 deferred minor needs no fix. Found by: the final review ("Ready to merge? Yes", 3 Minor). Why: none is a code defect; Minor 1 would reverse R11's choice to keep the spec's docstring. Cost if wrong: the docstring omits NaN until a later slice touches the file. How named: named in chat when made."
- **R13: how the post-merge docs mark slice 38 R11.** (Added after merge.) The ledger line, as recorded: "Ruling: R13 — Decided: slice 38 R11 is marked as the writer's summary with no ledger quote, because that ledger was deleted after PR #75 merged and PR #75's description holds no R11 ledger line; the findings-slice37 line 81 citation of R11 is a new dated note, not an edit of the old note. Found by: the controller, writing the post-merge docs. Why: dated notes keep the earlier text as it was merged. Cost if wrong: R11's wording cannot be checked against its ledger line. How named: named in chat when made (this ledger line was added after the docs review of c0a2593 found it missing)."
- **R14: the docs review's fixes.** (Added after merge.) The ledger line, as recorded: "Ruling: R14 — Decided: one fix commit: R13 and R14 ledger lines quoted in the spec (Important 1); the findings-slice37 note says the cap is per call and names the 215-attempt job total (Minor 1); the plan's "no departures" is attributed to the implementer's report and the task review (Minor 2); slice 38's unrecorded R12 is left out of this slice's scope and named in the docs PR description (Minor 3); the "After merge" section goes into the docs PR description (Minor 4); then one scoped re-review. Found by: the docs review of c0a2593. Why: every ruling quotes its ledger line, and no claim wider than its source. Cost if wrong: one more commit; slice 38 R12 stays recorded only in PR #75's description. How named: named in chat when made."
  - Note (2026-10-03, after PR #77): slice 38's R12 is now recorded in the slice 38 spec, as the writer's summary sourced from PR #75's description.
- **R15: a third docs round, by the user's choice.** (Added after merge.) The ledger line, as recorded: "Ruling: R15 — Decided: a third docs round: one commit adds "of a 10-call job" to the findings-slice37 overflow note, R15 is quoted in the spec and the README range becomes R1–R15; then one scoped re-review; the user chose this over stopping with the minor in the docs PR description. Found by: the re-review of 48ce55a ("Ready to merge? Yes"; 1 optional Minor: "215 full attempts" holds only for a 10-call job). Why: the note's figure is exact only with its basis. Cost if wrong: one more commit and review. How named: asked in chat."

## Deferred minors

Quoted verbatim from the ledger (deleted after this slice's docs PR merges):

- "Task 1: minor (deferred): the implementer's report quotes "1681 passed, 2 deselected, 2 warnings" without naming the 2 warnings (third-party deprecations, pre-existing, gate-task1.txt:30-36)"
- "Final: minor (deferred): dataforseo.py:93-94 the `_micros` docstring lists bool, negative and above MAX_COST_USD but not NaN (kept as the spec has it, R11)"
  - Note (2026-10-03, branch micros-docstring-nan): closed: the docstring now names NaN ("A bool, a negative number, NaN, or one above MAX_COST_USD raises ValueError."); the user chose this wording over also naming infinity (+infinity is "above MAX_COST_USD"; -infinity is a negative number).
- "Final: minor (deferred): plan line 299 "Changes made during execution" still reads "(Filled in after execution.)"; the spec assigns it to the post-merge docs PR, with the findings-slice37 notes for lines 80, 81 and 86"
- "Final: minor (deferred): a task with a provider error code and a bad cost loses the code (e.g. paused with cost 5 becomes json); named and accepted in the spec (Behaviour bullet 4)"
  - Note (2026-10-03, slice 40): closed: an error answer now keeps its code and records cost 0 when its cost is bad; a success with a bad cost is still `json` (docs/superpowers/specs/2026-10-03-slice40-serp-code-on-bad-cost-design.md, R1).

Writer's note: the plan's "Changes made during execution" section is at plan line 212; "plan line 299" is the final reviewer's reference.
