# Slice 42 Deferred Minors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `http_fetch`'s timeout message reports the deadline actually in force; a test drives a real `httpx.ReadTimeout` through `http_fetch` into `serp()`; the worker's `SERP_JOB_MICROS` comment states the observed price.

**Architecture:** `crawl._TIMED_OUT` (a module constant) becomes `_timed_out(limit)`, called at the three timeout sites with the deadline `http_fetch` already resolves; two new http_fetch tests, one new adapter test; a comment-only worker change.

**Tech Stack:** Python 3.13, pytest, httpx.

**Spec:** `docs/superpowers/specs/2026-10-05-slice42-deferred-minors-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice42-deferred-minors`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB (`bsi`), the network, the worker loop, DataForSEO or a model: every test uses fakes or a mock transport.
- **Shared test DB:** run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own before every pytest run; if it prints a running pytest, stop and wait. Run the full backend suite only in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal.)
- **Writing files:** use the Edit or Write tools; never a shell heredoc or zsh `echo` to write files. Never run `rm`.
- **Lint and types:** ruff line length 80, target py313, rules E F I B UP RUF; `mypy --strict` covers `packages/core/bsi_core`.
- **Banned words:** copy (code, comments, docstrings, test names) never contains the words listed in `FORBIDDEN` in tests/unit/test_recommend_copy.py.
- **Banned-word grep (must block the commit):** `cd /Users/vineet/Downloads/ADK/bsi-platform && ! { git diff --cached -U0 | grep '^+' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'; }`, run after staging. Expected: exit 0 and no output.
- **Backend gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform && { uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task<N>.txt 2>&1; echo "gate exit $?"`. If `ruff format .` changed a file, re-stage it and say so.
- **`<workspace>`:** the path given in your task brief; if none is given, stop and ask.
- **Commit trailer:** exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (spec R3).
- **Baseline counts** (collected 2026-10-05 on main `afc5126`): backend `1704 passed, 2 deselected`; tests/unit/test_http_fetch.py 56, tests/unit/test_dataforseo.py 85. After Task 1: test_http_fetch.py 59, backend `1707 passed, 2 deselected`. After Task 2: test_dataforseo.py 86, backend `1708 passed, 2 deselected`. (Backend totals computed, not yet run.) The web app is not touched.

## File map

| File | Responsibility | Task |
|---|---|---|
| `packages/core/bsi_core/crawl.py` | `_timed_out(limit)` replaces `_TIMED_OUT`; its three call sites | 1 |
| `tests/unit/test_http_fetch.py` | the in-stream and the two pre-send deadline-message tests | 1 |
| `tests/unit/test_dataforseo.py` | the end-to-end `ReadTimeout` test and its imports | 2 |
| `apps/workers/bsi_workers/worker.py` | the `SERP_JOB_MICROS` comment | 2 |

---

### Task 1: the timeout message reports the deadline in force

**Files:**
- Modify: `packages/core/bsi_core/crawl.py:227-228`, `:293`, `:304`, `:341`
- Test: `tests/unit/test_http_fetch.py`

**Interfaces:**
- Consumes: the test file's `server(handler)`, `ok`, `dns(table)`, `PUBLIC`, `itertools`, `httpx`, `pytest`; in crawl.py, `Response`, `DEADLINE_SECONDS`, and `limit` (resolved near the top of `http_fetch` from `deadline_seconds`).
- Produces: `_timed_out(limit: float) -> Response` with error `f"timeout: over the {limit:g} s deadline"`; `_TIMED_OUT` no longer exists (nothing outside crawl.py used it).

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_http_fetch.py`:

1. Replace

```python
def test_a_transport_error_is_a_response_not_an_exception():
```

with

```python
def test_a_fetch_reports_its_own_deadline(monkeypatch):
    # As the 30 s test above, with a 60 s deadline of this fetch's own.
    clock = itertools.count(0.0, 1.0)
    monkeypatch.setattr("bsi_core.crawl.time.monotonic", lambda: next(clock))

    def drip():
        while True:
            yield b"x"

    t = server(lambda q: httpx.Response(200, content=drip()))
    r = http_fetch(
        "https://nike.com/",
        "UA",
        resolve=dns({"nike.com": [PUBLIC]}),
        transport=t,
        deadline_seconds=60,
    )
    assert (r.status, r.body) == (0, "")
    assert r.error == "timeout: over the 60 s deadline"


@pytest.mark.parametrize(
    "clock",
    [
        [0.0, 61.0],  # out of time before the lookup
        [0.0, 1.0, 61.0],  # out of time after the lookup, before sending
    ],
)
def test_a_timeout_before_sending_reports_its_own_deadline(monkeypatch, clock):
    readings = iter(clock + [61.0] * 10)
    monkeypatch.setattr("bsi_core.crawl.time.monotonic", lambda: next(readings))
    t = server(ok)
    r = http_fetch(
        "https://nike.com/",
        "UA",
        resolve=dns({"nike.com": [PUBLIC]}),
        transport=t,
        deadline_seconds=60.0,
    )
    assert r.error == "timeout: over the 60 s deadline"
    assert t.seen == []


def test_a_transport_error_is_a_response_not_an_exception():
```

- [ ] **Step 2: Run the tests to verify they fail**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && COLUMNS=200 uv run pytest -q -p no:cacheprovider tests/unit/test_http_fetch.py 2>&1 | grep -E "^FAILED|passed|failed"`
Expected: a line starting with `3 failed, 56 passed`. The FAILED lines are `test_a_fetch_reports_its_own_deadline` and the two `test_a_timeout_before_sending_reports_its_own_deadline` cases (each gets "timeout: over the 30 s deadline"). Paste the output into the report.

- [ ] **Step 3: Write the implementation**

In `packages/core/bsi_core/crawl.py`:

1. Replace

```python
_REDIRECTS_REFUSED = "too many redirects"
_TIMED_OUT = f"timeout: over the {DEADLINE_SECONDS} s deadline"
```

with

```python
_REDIRECTS_REFUSED = "too many redirects"


def _timed_out(limit: float) -> Response:
    """The Response for a fetch past its deadline of `limit` seconds."""
    return Response(0, "", f"timeout: over the {limit:g} s deadline")
```

2. Replace every occurrence (three; use the Edit tool's replace_all) of

```python
return Response(0, "", _TIMED_OUT)
```

with

```python
return _timed_out(limit)
```

Then confirm `cd /Users/vineet/Downloads/ADK/bsi-platform && grep -c "_TIMED_OUT" packages/core/bsi_core/crawl.py` prints `0` (grep exits 1 on no match; that is expected) and `cd /Users/vineet/Downloads/ADK/bsi-platform && grep -c "return _timed_out(limit)" packages/core/bsi_core/crawl.py` prints `3`.

- [ ] **Step 4: Run the tests to verify they pass**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_http_fetch.py tests/unit/test_dataforseo.py 2>&1 | tail -1`
Expected: a line starting with `144 passed` (59 + 85).

- [ ] **Step 5: Mutation check (red evidence)**

With the Edit tool, temporarily change `f"timeout: over the {limit:g} s deadline"` in `packages/core/bsi_core/crawl.py` to `f"timeout: over the {DEADLINE_SECONDS:g} s deadline"`, run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own, then `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_http_fetch.py 2>&1 | tail -1`. Expected: a line starting with `3 failed, 56 passed`. Restore it with the Edit tool and confirm `cd /Users/vineet/Downloads/ADK/bsi-platform && grep -c 'over the {limit:g} s deadline' packages/core/bsi_core/crawl.py` prints `1`. Record both outputs.

- [ ] **Step 6: Banned-word grep, then the backend gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/crawl.py tests/unit/test_http_fetch.py`. Run the banned-word grep (expected: exit 0, no output). Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own, then the Backend gate with `<N>` = 1. Expected: `gate exit 0`; `gate-task1.txt` shows `1707 passed, 2 deselected`, mypy `Success`, metrics coverage 100%. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the two staged files plus the untracked `.DS_Store` and `packages/.DS_Store`).

- [ ] **Step 7: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/crawl.py tests/unit/test_http_fetch.py && git commit -m "fix(core): the timeout message reports the deadline in force

_TIMED_OUT was built once from DEADLINE_SECONDS, so a fetch with its
own deadline_seconds (the SERP call's 120 s) said 30 s. _timed_out()
uses the deadline the fetch resolved; the default text is unchanged.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: an end-to-end ReadTimeout test; the SERP_JOB_MICROS comment

**Files:**
- Test: `tests/unit/test_dataforseo.py:1-5`, `:157-159`
- Modify: `apps/workers/bsi_workers/worker.py:118-119`

**Interfaces:**
- Consumes: the real `bsi_core.crawl.http_fetch` (its `resolve=` and `transport=` keywords) and its status-0 `repr(e)` error; the test file's `_serp(fetch, ...)`, `SerpPage`; `serp()`'s `ReadTimeout` branch and `TIMEOUT_MICROS = 2_000`.
- Produces: nothing new.

- [ ] **Step 1: Write the test**

In `tests/unit/test_dataforseo.py`:

1. Replace

```python
import base64
import json

import pytest
from bsi_core.crawl import Response
```

with

```python
import base64
import json
from functools import partial

import httpx
import pytest
from bsi_core.crawl import Response, http_fetch
```

2. Replace

```python
def test_a_read_timeout_is_timeout_with_the_expected_cost():
    resp = Response(0, error="ReadTimeout('The read operation timed out')")
    assert _serp(Fetch(resp)) == SerpPage([], 2_000, "timeout")
```

with

```python
def test_a_read_timeout_is_timeout_with_the_expected_cost():
    resp = Response(0, error="ReadTimeout('The read operation timed out')")
    assert _serp(Fetch(resp)) == SerpPage([], 2_000, "timeout")


def test_a_real_read_timeout_from_http_fetch_is_timeout():
    # A real httpx.ReadTimeout through the real http_fetch into serp().
    def slow(request):
        raise httpx.ReadTimeout("The read operation timed out", request=request)

    fetch = partial(
        http_fetch,
        resolve=lambda host, port: ["93.184.216.34"],
        transport=httpx.MockTransport(slow),
    )
    assert _serp(fetch) == SerpPage([], 2_000, "timeout")
```

- [ ] **Step 2: Run it**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_dataforseo.py 2>&1 | tail -1`
Expected: a line starting with `86 passed`. This test passes on main: it pins behaviour main already has, so its red evidence is Step 3.

- [ ] **Step 3: Mutation check (red evidence)**

With the Edit tool, temporarily change `return Response(0, "", repr(e))` in `packages/core/bsi_core/crawl.py` to `return Response(0, "", f"error {e!r}")`, run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own, then `cd /Users/vineet/Downloads/ADK/bsi-platform && COLUMNS=200 uv run pytest -q -p no:cacheprovider tests/unit/test_dataforseo.py tests/unit/test_http_fetch.py 2>&1 | grep -E "^FAILED|passed|failed"`. Expected: a line starting with `1 failed, 144 passed`; the FAILED line is `test_a_real_read_timeout_from_http_fetch_is_timeout`. Restore it with the Edit tool and confirm `cd /Users/vineet/Downloads/ADK/bsi-platform && grep -c 'return Response(0, "", repr(e))' packages/core/bsi_core/crawl.py` prints `1`. Record both outputs.

- [ ] **Step 4: The worker comment**

In `apps/workers/bsi_workers/worker.py`:

1. Replace

```python
# Kept from 5 locales x 2 queries x $0.004 (a live page plus AI Overview
# loading); with one locale it overestimates, which fails closed.
```

with

```python
# A SERP audit is 2 calls at the observed $0.002 (2026-10-05), 4,000
# micros; 40,000 is kept as a 10x margin, which fails closed.
```

Then `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff check apps/workers/bsi_workers/worker.py && uv run ruff format --check apps/workers/bsi_workers/worker.py` (expected: `All checks passed!` and `1 file already formatted`).

- [ ] **Step 5: Banned-word grep, then the backend gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add tests/unit/test_dataforseo.py apps/workers/bsi_workers/worker.py`. Run the banned-word grep (expected: exit 0, no output). Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own, then the Backend gate with `<N>` = 2. Expected: `gate exit 0`; `gate-task2.txt` shows `1708 passed, 2 deselected`, mypy `Success`, metrics coverage 100%. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the two staged files plus the two `.DS_Store` files).

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add tests/unit/test_dataforseo.py apps/workers/bsi_workers/worker.py && git commit -m "test(core): a real ReadTimeout through http_fetch into serp()

Pins the repr-based error shape serp() matches on. The SERP_JOB_MICROS
comment now states the observed \$0.002 per call and the 10x margin.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (plan vs spec)

- Spec coverage: the timeout message → Task 1 Step 3; the worker comment → Task 2 Step 4; Tests → Task 1 Step 1 and Task 2 Step 1 (identical to the spec's diffs); Proof → the spec's scratch run, with mutant m1 repeated in Task 1 Step 5 and m4 in Task 2 Step 3; Copy → each task's banned-word grep, now blocking the commit. Docs: this plan, two docs/README.md rows and five dated notes in the slice 41 spec are committed by the controller with the plan; post-merge docs are controller work.
- Departures from the spec:
  1. The code changes are replace blocks generated from the scratch proof's verified pairs, not the spec's unified diffs; the result is the same files. Step 3's second replacement uses replace_all over three occurrences of the same text.
  2. Two tasks (crawl and its tests; the adapter test and the worker comment), each with its own commit; the spec sets no task boundaries.
  3. Only m1 and m4 are repeated in execution; m2, m3, m5 and m6 are the spec's evidence.
  4. The commit messages are the plan's wording.
  5. Per-task counts (1707 after Task 1) are the plan's arithmetic; the spec gives only 1708.
  6. The banned-word grep is written to block the commit (`! { … }`), as the user's process now requires; earlier plans' greps only reported.
  7. The header offers superpowers:executing-plans as well as subagent-driven-development (the template's wording).
- Rulings applied: the spec's R1–R6, and R7 (the plan review's wording points).
- Placeholders: `<workspace>` and `<N>`.
- Type consistency: `_timed_out(limit: float) -> Response` in Task 1; Task 2 relies only on `http_fetch`'s existing `resolve=`/`transport=` keywords and `repr(e)` error.

## Changes made during execution

- Task 1: commit b90397e; Task 2: commit 6c03876 (each task review says "✅ Spec compliant"; Task 2's implementer edited the worker comment before Step 2 instead of after Step 3, disclosed, no effect). Merged via PR #84 (main `09b62a7`).
- Implementer gates: gate-task1.txt `1707 passed, 2 deselected, 2 warnings in 192.30s (0:03:12)`; gate-task2.txt `1708 passed, 2 deselected, 2 warnings in 166.11s (0:02:46)`. Controller gates on 6c03876: `1708 passed, 2 deselected, 2 warnings in 169.18s (0:02:49)`, web `Tests  49 passed (49)`. CI: `gates` passed in 4m25s with `1708 passed, 2 deselected, 2 warnings in 145.86s (0:02:25)`. Gates on main after merge: `1708 passed, 2 deselected, 2 warnings in 349.93s (0:05:49)`; web `Tests  49 passed (49)`.
- Reviews, as the ledger records them:
  - "Plan review (ae84599358966be15, e5fcd99): "Ready to execute? With fixes"; 0 Critical, 0 Important, 5 Minor; R7 applied Minors 1-3 and 5 (9bee914), Minor 4 left (departure 4)."
  - "Task 1: task review (aaf69ae49d847296a, 9bee914..b90397e): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 2 Minor; ⚠️ items (gate/red/mutant from the report; the trailer; the 2 third-party warnings)."
  - "Task 2: task review (ae37c2bf079b16018, b90397e..6c03876): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 2 Minor; ⚠️ items (counts, mutant, gate, crawl.py restore — from the report)."
  - "Final review (ae27c97b6686f8b2a, afc5126..6c03876): "Ready to merge? Yes"; 0 Critical, 0 Important, 1 Minor; deferred-minor triage: all 4 "Not needed before merge"; a spy confirmed each pre-send case hits its own site (crawl.py:297, 308)."
- Rulings from execution: R8, in the spec's Rulings. The five deferred minors are quoted in the spec's "Deferred minors" section.
