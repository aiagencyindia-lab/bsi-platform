# Slice 40 SERP Code On Bad Cost Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A DataForSEO answer that carries a provider error code keeps that code when its cost is bad, recording cost 0 (for example `paused` with cost 5 is `paused`, cost 0, not `json`); a success with a bad cost is still `json`.

**Architecture:** All behaviour is in `packages/core/bsi_core/providers/dataforseo.py`: a new `_error_micros` helper (a bad cost is 0), and `_parse` reads the error code before it converts the cost. `_refused`, the worker, schema, API and web app are unchanged.

**Tech Stack:** Python 3.13, pytest.

**Spec:** `docs/superpowers/specs/2026-10-03-slice40-serp-code-on-bad-cost-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice40-serp-code-on-bad-cost`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB (`bsi`), the network, the worker loop, DataForSEO or a model: every test uses the file's fake `Fetch`.
- **Shared test DB:** run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own before every pytest run; if it prints a running pytest, stop and wait. Never run two suites at once. Run the full backend suite only in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal: read the file and repeat the edit.)
- **Writing files:** use the Edit or Write tools; never a shell heredoc or zsh `echo` to write files, including commit messages written to files. Never run `rm`.
- **Lint and types:** ruff line length 80, target py313, rules E F I B UP RUF; `mypy --strict` covers `packages/core/bsi_core`.
- **Banned words:** copy (code, comments, docstrings, labels, test names) never contains the words listed in `FORBIDDEN` in tests/unit/test_recommend_copy.py.
- **Banned-word grep:** `cd /Users/vineet/Downloads/ADK/bsi-platform && git diff --cached -U0 | grep '^+' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'`, run after staging. Expected: no match (grep exits 1 and prints nothing).
- **Backend gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform && { uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task<N>.txt 2>&1; echo "gate exit $?"`. If `ruff format .` changed a file, re-stage it, re-run the banned-word grep, and say so in the report.
- **`<workspace>`:** the path given in your task brief (the plan's directory under the git-ignored `.superpowers/sdd/`); if none is given, stop and ask.
- **Commit trailer:** exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (spec R4). Use this line even if your own session reminder names another model.
- **Baseline counts** (collected 2026-10-03 on main `ae34ae6`): backend `1681 passed, 2 deselected`; tests/unit/test_dataforseo.py 65; web 48 vitest (the web app is not touched). After Task 1: test_dataforseo.py 77, backend `1693 passed, 2 deselected` (1681 + 12; computed, not yet run).

## File map

| File | Responsibility | Task |
|---|---|---|
| `packages/core/bsi_core/providers/dataforseo.py` | `_error_micros`; `_parse` reads the code before the cost; its docstring | 1 |
| `tests/unit/test_dataforseo.py` | two tests renamed with new expectations; ten new cases | 1 |

---

### Task 1: an error answer keeps its code on a bad cost

**Files:**
- Modify: `packages/core/bsi_core/providers/dataforseo.py:102-152`
- Test: `tests/unit/test_dataforseo.py:294-301`

**Interfaces:**
- Consumes: the file's existing `body(items=None, cost=0.004, status=20000, task_status=20000) -> str` (it writes `cost` at both the top level and the task), `Fetch`, `_serp(fetch, ...)`, `BAD_COSTS = [1.000001, 1e12, -0.004, float("nan"), True, False]`, `SerpPage(items, cost_micros, error)`, `Response(status, body, ...)`; in the adapter, `_micros(cost: object) -> int` (raises `ValueError` on a bad cost), `_code`, `_status`, `UNREADABLE`.
- Produces: `_error_micros(cost: object) -> int` (`_micros(cost)`, or 0 when it raises `ValueError`). `serp()` and `_refused` keep their signatures; `serp()` never raises.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_dataforseo.py`, replace

```python
def test_a_refused_answer_with_a_cost_out_of_range_is_http():
    raw = body(cost=5, task_status=40210)
    assert _serp(Fetch(Response(402, raw))) == SerpPage([], 0, "http")
```

with

```python
def test_a_refused_answer_with_a_bad_cost_keeps_its_code():
    raw = body(cost=5, task_status=40210)
    assert _serp(Fetch(Response(402, raw))) == SerpPage([], 0, "funds")
```

Then replace the file's last test

```python
def test_a_top_level_error_with_a_cost_out_of_range_is_json():
    raw = json.dumps({"status_code": 40100, "cost": 5, "tasks": None})
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "json")
```

with

```python
def test_a_top_level_error_with_a_bad_cost_keeps_its_code():
    raw = json.dumps({"status_code": 40100, "cost": 5, "tasks": None})
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "auth")


@pytest.mark.parametrize("cost", BAD_COSTS)
def test_a_task_error_with_a_bad_cost_keeps_its_code(cost):
    raw = body(cost=cost, task_status=40201)
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "paused")


def test_a_top_level_error_with_tasks_and_a_bad_cost_keeps_its_code():
    raw = body(cost=5, status=40100)
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "auth")


def test_a_bad_task_status_with_a_bad_cost_is_json():
    raw = body(cost=5, task_status=[1, 2])
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "json")


def test_a_top_level_error_keeps_a_readable_cost():
    raw = json.dumps({"status_code": 40100, "cost": 0.004, "tasks": None})
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 4_000, "auth")


def test_a_task_error_keeps_the_tasks_cost():
    doc = json.loads(body(task_status=40201))
    doc["cost"] = 0
    page = _serp(Fetch(Response(200, json.dumps(doc))))
    assert page == SerpPage([], 4_000, "paused")


def test_a_task_error_with_an_infinite_cost_keeps_its_code():
    raw = body(cost=1e400, task_status=40201)
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "paused")


def test_a_refused_top_level_error_with_a_bad_cost_keeps_its_code():
    raw = json.dumps({"status_code": 40100, "cost": 5, "tasks": None})
    assert _serp(Fetch(Response(401, raw))) == SerpPage([], 0, "auth")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && COLUMNS=200 uv run pytest -q -p no:cacheprovider tests/unit/test_dataforseo.py 2>&1 | grep -E "^FAILED|passed|failed"`
Expected: a line starting with `11 failed, 66 passed` (pytest appends the time). The FAILED lines are `test_a_refused_answer_with_a_bad_cost_keeps_its_code`, `test_a_top_level_error_with_a_bad_cost_keeps_its_code`, the 6 `test_a_task_error_with_a_bad_cost_keeps_its_code` cases (`1.000001`, `1000000000000.0`, `-0.004`, `nan`, `True`, `False`), `test_a_top_level_error_with_tasks_and_a_bad_cost_keeps_its_code`, `test_a_task_error_with_an_infinite_cost_keeps_its_code` and `test_a_refused_top_level_error_with_a_bad_cost_keeps_its_code`. (`test_a_bad_task_status_with_a_bad_cost_is_json`, `test_a_top_level_error_keeps_a_readable_cost` and `test_a_task_error_keeps_the_tasks_cost` pass on main: they pin behaviour main already has.) Paste the output into the report.

- [ ] **Step 3: Write the implementation**

In `packages/core/bsi_core/providers/dataforseo.py`, make four replacements.

1. Replace

```python
    return round(cost * 1_000_000)
```

with

```python
    return round(cost * 1_000_000)


def _error_micros(cost: object) -> int:
    """The cost of an answer that carries an error code: a bad cost is 0,
    so the code is kept."""
    try:
        return _micros(cost)
    except ValueError:
        return 0
```

2. Replace

```python
    """The page in a decoded response. Raises on an undocumented shape
    until the task's cost is read; after that, returns `json` with it."""
```

with

```python
    """The page in a decoded response. Raises on an undocumented shape,
    or on a success whose cost is bad. An error answer keeps its code; a
    bad cost there is 0. An unreadable item returns `json` with the cost."""
```

3. Replace

```python
        return SerpPage(cost_micros=_micros(doc.get("cost")), error=error)
```

with

```python
        return SerpPage(cost_micros=_error_micros(doc.get("cost")), error=error)
```

4. Replace

```python
    task = tasks[0]
    cost = _micros(task.get("cost"))
    # The top-level status first, then the task's (spec, The adapter).
    error = _code(top)
    if error is None:
        status = _status(task.get("status_code"))
        if status is None:
            return SerpPage(cost_micros=cost, error="json")
        error = _code(status)
    if error is not None:
        return SerpPage(cost_micros=cost, error=error)
```

with

```python
    task = tasks[0]
    # The top-level status first, then the task's (spec, The adapter).
    error = _code(top)
    if error is None:
        status = _status(task.get("status_code"))
        error = "json" if status is None else _code(status)
    if error is not None:
        return SerpPage(
            cost_micros=_error_micros(task.get("cost")), error=error
        )
    cost = _micros(task.get("cost"))  # a bad cost on a success raises: json
```

- [ ] **Step 4: Run the tests to verify they pass**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_dataforseo.py tests/integration/test_serp_audit.py 2>&1 | tail -1`
Expected: a line starting with `88 passed` (77 in test_dataforseo.py plus test_serp_audit.py's 11, which use the default cost of $0.004).

- [ ] **Step 5: Mutation check (red evidence for the task error path)**

With the Edit tool, temporarily change the line `            cost_micros=_error_micros(task.get("cost")), error=error` in `packages/core/bsi_core/providers/dataforseo.py` to `            cost_micros=_micros(task.get("cost")), error=error`, run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own, then `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_dataforseo.py 2>&1 | tail -1`. Expected: a line starting with `9 failed, 68 passed`. Then restore the line to `            cost_micros=_error_micros(task.get("cost")), error=error` with the Edit tool and confirm with `cd /Users/vineet/Downloads/ADK/bsi-platform && grep -c 'cost_micros=_error_micros(task.get("cost")), error=error' packages/core/bsi_core/providers/dataforseo.py` (expected `1`). Record both outputs in the report.

- [ ] **Step 6: Banned-word grep, then the backend gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/providers/dataforseo.py tests/unit/test_dataforseo.py`. Run the banned-word grep (expected: no match). Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own, then the Backend gate with `<N>` = 1. Expected: `gate exit 0`; `gate-task1.txt` shows `1693 passed, 2 deselected`, mypy `Success`, and the metrics coverage line at 100%. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the two staged files, plus the untracked `.DS_Store` and `packages/.DS_Store` that were there before this slice).

- [ ] **Step 7: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/providers/dataforseo.py tests/unit/test_dataforseo.py && git commit -m "fix(core): keep the provider error code when the cost is bad

_parse now reads the error code before it converts the cost. An
answer with a provider error code and a bad cost keeps the code and
records cost 0 (paused with cost 5 was json, now paused); a success
with a bad cost is still json. A readable cost is unchanged.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (plan vs spec)

- Spec coverage: The adapter (`_error_micros`, the reordered `_parse`, its docstring) → Task 1 Step 3, whose four replace blocks produce exactly the file the spec's diff produces (checked by applying both to main's file in scratch); Tests → Task 1 Step 1 (identical to the spec's blocks); Proof → the spec's scratch run, with the main row repeated in Step 2 and mutant m1 in Step 5; Copy → the banned-word grep. Docs: this plan, the two docs/README.md rows and the dated notes in the slice 39 spec are committed by the controller with the plan; the post-merge docs are controller work. No live check (spec, Out of scope).
- Departures from the spec:
  1. The adapter change is four replace blocks, not the spec's unified diff; the result is the same file.
  2. Only the proof table's main row (Task 1 Step 2) and mutant m1 (Task 1 Step 5) are repeated during execution; m2–m8 are the spec's evidence and are not re-run.
  3. Task 1 Step 4 also runs tests/integration/test_serp_audit.py, which the spec does not mention.
  4. The commit message is the plan's wording; the spec does not give it.
  5. The header offers superpowers:executing-plans as well as subagent-driven-development (the template's wording); the controller uses subagent-driven execution.
- Rulings applied to this plan: the spec's R2 (the one-line no-task return), R4 (the Opus 5.5 trailer) and R7 (the docstring).
- Placeholders: `<workspace>` (the plan's directory under the git-ignored `.superpowers/sdd/`, supplied in the task brief) and `<N>` (the task number).
- Type consistency: `_error_micros(cost: object) -> int`, `_micros(cost: object) -> int` and `SerpPage(items, cost_micros, error)` as used in the implementation and the tests.

## Changes made during execution

- Task 1: commit 3434fe4, as planned (the implementer's report gives every count the plan expects; the task review says "✅ Spec compliant"). Merged via PR #80 (main `e25e890`). Implementer gate (gate-task1.txt, read by the controller): backend `1693 passed, 2 deselected, 2 warnings in 246.48s (0:04:06)`, mypy `Success`, metrics coverage 100%. Controller gates on `3434fe4`: backend `1693 passed, 2 deselected, 2 warnings in 355.80s (0:05:55)`; web `Tests  48 passed (48)`. CI: `gates` passed in 3m10s with `1693 passed, 2 deselected, 2 warnings in 96.88s (0:01:36)`. Gates on main after merge: backend `1693 passed, 2 deselected, 2 warnings in 262.19s (0:04:22)`; web `Tests  48 passed (48)`.
- Reviews, as the ledger records them:
  - "Plan review (a5622079510ba2634, d27956b): "Ready to execute? Yes"; 0 Critical, 0 Important, 1 Minor (slice 39 spec line 116 names a test this slice renames)."
  - "Task 1: task review (ab3c849dcff45d77d, d27956b..3434fe4): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 2 Minor; 2 ⚠️ items (red/green/mutant/gate counts not re-run; banned-word grep checked by eye)."
  - "Final review (a93fa6901301210b9, ae34ae6..3434fe4): "Ready to merge? Yes"; 0 Critical, 0 Important, 3 Minor; deferred-minor triage: both Task 1 minors "no fix needed before merge"."
- Rulings from planning and execution: R9 and R10, in the spec's Rulings. The five deferred minors are quoted in the spec's "Deferred minors" section.
