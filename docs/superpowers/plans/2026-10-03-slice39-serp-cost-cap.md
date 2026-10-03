# Slice 39 SERP Cost Cap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The DataForSEO adapter accepts a call's cost only as a plain number from 0 to $1 (a bool, a negative number, anything above $1, infinity or NaN makes the call `json`, or `http` on a non-2xx answer, with cost 0), so no provider cost can overflow the Integer `cost_micros` columns; the `tick` comment describes the stale paths accurately.

**Architecture:** One function, `_micros` in `packages/core/bsi_core/providers/dataforseo.py`, raises `ValueError` on a bad cost; the existing `UNREADABLE` handlers in `serp()` and `_refused` turn that into `json` / `http` with cost 0. The worker, schema, API and web app are unchanged; only a comment in `apps/workers/bsi_workers/worker.py` changes.

**Tech Stack:** Python 3.13, pytest.

**Spec:** `docs/superpowers/specs/2026-10-03-slice39-serp-cost-cap-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice39-serp-cost-cap`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB (`bsi`), the network, the worker loop, DataForSEO or a model: every test uses the file's fake `Fetch`.
- **Shared test DB:** run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own before every pytest run; if it prints a running pytest, stop and wait. Never run two suites at once. Run the full backend suite only in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal: read the file and repeat the edit.)
- **Writing files:** use the Edit or Write tools; never a shell heredoc or zsh `echo` to write files, including commit messages written to files. Never run `rm`.
- **Lint and types:** ruff line length 80, target py313, rules E F I B UP RUF; `mypy --strict` covers `packages/core/bsi_core`.
- **Banned words:** copy (code, comments, docstrings, labels, test names) never contains the words listed in `FORBIDDEN` in tests/unit/test_recommend_copy.py.
- **Banned-word grep:** `cd /Users/vineet/Downloads/ADK/bsi-platform && git diff --cached -U0 | grep '^+' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'`, run after staging. Expected: no match (grep exits 1 and prints nothing).
- **Backend gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform && { uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task<N>.txt 2>&1; echo "gate exit $?"`. If `ruff format .` changed a file, re-stage it, re-run the banned-word grep, and say so in the report.
- **`<workspace>`:** the path given in your task brief (the plan's directory under the git-ignored `.superpowers/sdd/`); if none is given, stop and ask.
- **Commit trailer:** exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (spec R5). Use this line even if your own session reminder names another model.
- **Baseline counts** (collected 2026-10-03 on main `363a334`): backend `1668 passed, 2 deselected`; tests/unit/test_dataforseo.py 52; web 48 vitest (the web app is not touched). After Task 1: test_dataforseo.py 65, backend `1681 passed, 2 deselected` (1668 + 13; computed, not yet run).

## File map

| File | Responsibility | Task |
|---|---|---|
| `packages/core/bsi_core/providers/dataforseo.py` | `MAX_COST_USD`, the bounded `_micros` | 1 |
| `tests/unit/test_dataforseo.py` | the bad, at-cap, non-number, missing, refused and top-level cost tests | 1 |
| `apps/workers/bsi_workers/worker.py` | the `tick` comment (its own commit) | 1 |

---

### Task 1: the adapter caps the cost of one call; the `tick` comment

**Files:**
- Modify: `packages/core/bsi_core/providers/dataforseo.py:90-91`
- Modify: `apps/workers/bsi_workers/worker.py:1177-1178`
- Test: `tests/unit/test_dataforseo.py`

**Interfaces:**
- Consumes: the file's existing `body(items=None, cost=0.004, status=20000, task_status=20000) -> str`, `Fetch`, `_serp(fetch, country="IN", login="me", password="pw")`, `SerpPage(items, cost_micros, error)`, `Response(status, body, error=None, truncated=False)` (from `bsi_core.crawl`), and `UNREADABLE` in the adapter (it already contains `ValueError`).
- Produces: `MAX_COST_USD = 1`; `_micros(cost: object) -> int`, which returns 0 for a missing or non-number cost and raises `ValueError` for a bool, a negative number or one above `MAX_COST_USD`. `serp()` keeps its signature and never raises.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_dataforseo.py`, replace the file's last two lines

```python
    page = _serp(Fetch(Response(200, json.dumps(doc))))
    assert page == SerpPage([], 4_000, "json")
```

with those two lines followed by the new tests:

```python
    page = _serp(Fetch(Response(200, json.dumps(doc))))
    assert page == SerpPage([], 4_000, "json")


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

- [ ] **Step 2: Run the tests to verify they fail**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && COLUMNS=200 uv run pytest -q -p no:cacheprovider tests/unit/test_dataforseo.py 2>&1 | grep -E "^FAILED|passed|failed"`
Expected: `7 failed, 58 passed`. The FAILED lines are `test_a_bad_cost_is_json` for `1.000001`, `1000000000000.0`, `-0.004`, `True` and `False`, plus `test_a_refused_answer_with_a_cost_out_of_range_is_http` and `test_a_top_level_error_with_a_cost_out_of_range_is_json`. (The `nan` case, the at-cap case, the non-number cases and the missing case pass on main: they pin behaviour main already has.) Paste the output into the report.

- [ ] **Step 3: Write the implementation**

In `packages/core/bsi_core/providers/dataforseo.py`, replace

```python
def _micros(cost: object) -> int:
    return round(cost * 1_000_000) if isinstance(cost, int | float) else 0
```

with

```python
MAX_COST_USD = 1  # per call; the expected price is about $0.004


def _micros(cost: object) -> int:
    """The cost in micros. A missing or non-number cost is 0. A bool, a
    negative number, or one above MAX_COST_USD raises ValueError."""
    if isinstance(cost, bool):
        raise ValueError("cost is a bool")
    if not isinstance(cost, int | float):
        return 0
    if not 0 <= cost <= MAX_COST_USD:
        raise ValueError("cost out of range")
    return round(cost * 1_000_000)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run `pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_dataforseo.py tests/integration/test_serp_audit.py 2>&1 | tail -1`
Expected: `76 passed` (65 in test_dataforseo.py plus test_serp_audit.py's 11, which use the default cost of $0.004).

- [ ] **Step 5: Mutation check (red evidence for the cap)**

With the Edit tool, temporarily change the line `    if not 0 <= cost <= MAX_COST_USD:` in `packages/core/bsi_core/providers/dataforseo.py` to `    if not 0 <= cost:`, run `pgrep -fl pytest` on its own, then `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_dataforseo.py 2>&1 | tail -1`. Expected: `4 failed, 61 passed`. Then restore the line to `    if not 0 <= cost <= MAX_COST_USD:` with the Edit tool and confirm with `cd /Users/vineet/Downloads/ADK/bsi-platform && grep -c "    if not 0 <= cost <= MAX_COST_USD:" packages/core/bsi_core/providers/dataforseo.py` (expected `1`). Record both outputs in the report.

- [ ] **Step 6: Banned-word grep, then the backend gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/providers/dataforseo.py tests/unit/test_dataforseo.py`. Run the banned-word grep (expected: no match). Run `pgrep -fl pytest` on its own, then the Backend gate with `<N>` = 1. Expected: `gate exit 0`; `gate-task1.txt` shows `1681 passed, 2 deselected`, mypy `Success`, and the metrics coverage line at 100%. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the two staged files, plus the untracked `.DS_Store` and `packages/.DS_Store` that were there before this slice).

- [ ] **Step 7: Commit the adapter change**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/providers/dataforseo.py tests/unit/test_dataforseo.py && git commit -m "fix(core): cap the DataForSEO cost of one call at \$1

A bool, a negative number, a cost above MAX_COST_USD, infinity or
NaN now makes the call json (http on a non-2xx answer) with cost 0,
so no provider cost can overflow the Integer cost_micros columns.
A missing or non-number cost still records 0.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 8: Fix the `tick` comment**

In `apps/workers/bsi_workers/worker.py`, replace

```python
        # A row whose failure could not be recorded stays 'running';
        # reset_stale() hands it back after 10 minutes.
```

with

```python
        # A row whose failure could not be recorded stays 'running':
        # reset_stale() retries an observation (or fails it on its
        # third attempt) once it is over 10 minutes old; the next
        # claim_job() fails a job running over 10 minutes as 'stale'.
```

Then run `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff check apps/workers/bsi_workers/worker.py && uv run ruff format --check apps/workers/bsi_workers/worker.py` (expected: `All checks passed!` and `1 file already formatted`). Stage with `cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/workers/bsi_workers/worker.py`, run the banned-word grep (expected: no match), and confirm `cd /Users/vineet/Downloads/ADK/bsi-platform && git diff --cached --stat` lists only `apps/workers/bsi_workers/worker.py`, 4 insertions and 2 deletions.

- [ ] **Step 9: Commit the comment**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/workers/bsi_workers/worker.py && git commit -m "docs(workers): describe the stale paths in tick's comment

reset_stale() only touches observations; a job left running is
failed as stale by the next claim_job().

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (plan vs spec)

- Spec coverage: The adapter (`MAX_COST_USD` directly above `_micros`, the bounded `_micros`, its docstring and comment) → Task 1 Step 3, whose replace block produces exactly the file the spec's diff produces (checked by applying both to main's file in scratch); The `tick` comment (R8) → Task 1 Step 8, its own commit (R4); Tests → Task 1 Step 1 (the appended block is identical to the spec's); Proof → the spec's scratch run, with mutant m1 repeated in Task 1 Step 5; Copy → each commit's banned-word grep. Docs: this plan and the two README rows are committed by the controller with the plan; the post-merge docs are controller work. No live check (spec, Out of scope).
- Departures from the spec:
  1. The adapter change is a replace block, not the spec's unified diff; the result is the same file.
  2. Only mutant m1 is repeated during execution (Task 1 Step 5); m2–m6 are the spec's evidence and are not re-run.
  3. Task 1 Step 4 also runs tests/integration/test_serp_audit.py, which the spec mentions only as unaffected.
  4. The adapter change and the comment are one task with two commits; the spec says only that the comment is its own commit.
  5. The comment commit has no backend gate of its own (ruff check and format on the file only); the controller runs both gates before the finishing menu.
  6. The commit messages are the plan's wording; the spec does not give them.
  7. The header offers superpowers:executing-plans as well as subagent-driven-development (the template's wording); the controller uses subagent-driven execution.
- Rulings applied to this plan: the spec's R5 (the Opus 5.5 trailer), R8 (the comment's wording) and R9 (the test name).
- Placeholders: `<workspace>` (the plan's directory under the git-ignored `.superpowers/sdd/`, supplied in the task brief) and `<N>` (the task number).
- Type consistency: `_micros(cost: object) -> int`, `MAX_COST_USD = 1` and `SerpPage(items, cost_micros, error)` as used in the implementation and the tests.

## Changes made during execution

(Filled in after execution.)
