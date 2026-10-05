# Slice 41 SERP Timeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A DataForSEO live call waits up to 120 s; a call that times out on read is recorded as `timeout` at 4,000 micros with a page label; an audit covers one locale so it stays under `claim_job()`'s 10 minutes.

**Architecture:** `crawl.http_fetch` gains optional `deadline_seconds` and `phase_seconds` (defaults unchanged for every other caller); the DataForSEO adapter passes 120 s for both and maps a status-0 `ReadTimeout` to `timeout`; the worker's `MAX_SERP_LOCALES` becomes 1; the web app labels `timeout`.

**Tech Stack:** Python 3.13, pytest, httpx; TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-10-05-slice41-serp-timeout-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice41-serp-timeout`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB (`bsi`), the network, the worker loop, DataForSEO or a model: every test uses fakes or a mock transport.
- **Shared test DB:** run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own before every pytest run; if it prints a running pytest, stop and wait. Never run two suites at once. Run the full backend suite only in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal: read the file and repeat the edit.)
- **Writing files:** use the Edit or Write tools; never a shell heredoc or zsh `echo` to write files, including commit messages written to files. Never run `rm`.
- **Lint and types:** ruff line length 80, target py313, rules E F I B UP RUF; `mypy --strict` covers `packages/core/bsi_core`.
- **Banned words:** copy (code, comments, docstrings, labels, test names) never contains the words listed in `FORBIDDEN` in tests/unit/test_recommend_copy.py.
- **Banned-word grep:** `cd /Users/vineet/Downloads/ADK/bsi-platform && git diff --cached -U0 | grep '^+' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'`, run after staging. Expected: no match (grep exits 1 and prints nothing).
- **Backend gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform && { uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task<N>.txt 2>&1; echo "gate exit $?"`. If `ruff format .` changed a file, re-stage it, re-run the banned-word grep, and say so in the report.
- **Web gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate > <workspace>/web-task<N>.txt 2>&1; echo "web gate exit $?"`.
- **`<workspace>`:** the path given in your task brief (the plan's directory under the git-ignored `.superpowers/sdd/`); if none is given, stop and ask.
- **Commit trailer:** exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (spec R4). Use this line even if your own session reminder names another model.
- **Baseline counts** (collected 2026-10-05 on main `d049be7`): backend `1693 passed, 2 deselected`; tests/unit/test_http_fetch.py 53, tests/unit/test_dataforseo.py 77, tests/integration/test_serp_audit.py 11; web 48 vitest (whole suite). After Task 1: test_http_fetch.py 56, backend `1696 passed, 2 deselected`. After Task 2: test_dataforseo.py 85, test_serp_audit.py 11, backend `1704 passed, 2 deselected`. After Task 3: web 49. (Backend totals computed, not yet run.)

## File map

| File | Responsibility | Task |
|---|---|---|
| `packages/core/bsi_core/crawl.py` | `http_fetch`'s `deadline_seconds` and `phase_seconds`; its docstring | 1 |
| `tests/unit/test_http_fetch.py` | three tests: own phase, own deadline, plain 15 s phase | 1 |
| `packages/core/bsi_core/providers/dataforseo.py` | `SERP_TIMEOUT_SECONDS`, `TIMEOUT_MICROS`, `SerpFetch`'s new parameters, the `timeout` branch | 2 |
| `apps/workers/bsi_workers/worker.py` | `MAX_SERP_LOCALES = 1` and its comment; the `SERP_JOB_MICROS` comment; the `tick` docstring | 2 |
| `tests/unit/test_dataforseo.py` | the timeout-kwargs test, the read-timeout test, the six-case status-0 test | 2 |
| `tests/integration/test_serp_audit.py` | the locale-cap test renamed to one locale | 2 |
| `apps/web/src/lib/format.ts`, `apps/web/src/lib/format.test.ts` | the `timeout` label and its test | 3 |

---

### Task 1: `http_fetch` takes its own deadline and phase timeout

**Files:**
- Modify: `packages/core/bsi_core/crawl.py:235-320`
- Test: `tests/unit/test_http_fetch.py`

**Interfaces:**
- Consumes: the test file's `server(handler)`, `ok`, `dns(table)`, `fetch(url, table=None, handler=ok)`, `PUBLIC`, the `hang` fixture; in crawl.py, `DEADLINE_SECONDS`, `PHASE_TIMEOUT_SECONDS`, `DNS_TIMEOUT_SECONDS`.
- Produces: `http_fetch(url, user_agent, *, ..., headers=None, deadline_seconds: float | None = None, phase_seconds: float | None = None) -> Response`. `None` means the module constant, read at call time. Task 2 passes both.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_http_fetch.py`:

1. Replace

```python
def test_each_request_timeout_is_capped_by_the_time_left(monkeypatch):
```

with

```python
def test_a_fetch_can_ask_for_its_own_phase_timeout():
    t = server(ok)
    r = http_fetch(
        "https://nike.com/",
        "UA",
        resolve=dns({"nike.com": [PUBLIC]}),
        transport=t,
        deadline_seconds=120,
        phase_seconds=40,
    )
    assert r.status == 200
    assert set(t.seen[0].extensions["timeout"].values()) == {40.0}


def test_a_plain_fetch_keeps_the_15_s_phase_timeout():
    r, seen = fetch("https://nike.com/", {"nike.com": [PUBLIC]})
    assert r.status == 200
    assert set(seen[0].extensions["timeout"].values()) == {15.0}


def test_each_request_timeout_is_capped_by_the_time_left(monkeypatch):
```

2. Replace

```python
def test_an_abandoned_lookup_still_queued_never_runs(monkeypatch, hang):
```

with

```python
def test_a_fetch_can_ask_for_its_own_deadline(monkeypatch, hang):
    # The 10 s lookup wait is cut to this fetch's 0.2 s deadline.
    monkeypatch.setattr("bsi_core.crawl.DNS_TIMEOUT_SECONDS", 10)
    t = server(ok)
    start = time.monotonic()
    r = http_fetch(
        "https://nike.com/",
        "UA",
        resolve=hang,
        transport=t,
        deadline_seconds=0.2,
    )
    assert time.monotonic() - start < 1
    assert r.error == "refused: nike.com did not resolve in time"
    assert t.seen == []


def test_an_abandoned_lookup_still_queued_never_runs(monkeypatch, hang):
```

- [ ] **Step 2: Run the tests to verify they fail**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && COLUMNS=200 uv run pytest -q -p no:cacheprovider tests/unit/test_http_fetch.py 2>&1 | grep -E "^FAILED|passed|failed"`
Expected: a line starting with `2 failed, 54 passed` (pytest appends the time). The FAILED lines are `test_a_fetch_can_ask_for_its_own_phase_timeout` and `test_a_fetch_can_ask_for_its_own_deadline` (each a TypeError: unexpected keyword argument). `test_a_plain_fetch_keeps_the_15_s_phase_timeout` passes on main: it pins the default. Paste the output into the report.

- [ ] **Step 3: Write the implementation**

In `packages/core/bsi_core/crawl.py`, make four replacements.

1. Replace

```python
    inflates past `cap`. The 30 s deadline covers resolving,
    connecting, sending and reading on every hop; a lookup waits at most
    DNS_TIMEOUT_SECONDS or the time left, whichever is less.
```

with

```python
    inflates past `cap`. The deadline (DEADLINE_SECONDS unless
    `deadline_seconds` is given) covers resolving, connecting, sending and
    reading on every hop; a lookup waits at most DNS_TIMEOUT_SECONDS or the
    time left, whichever is less.
```

2. Replace

```python
    headers: Mapping[str, str] | None = None,
) -> Response:
    """The real fetch. Never raises: an error is a Response with status 0,
```

with

```python
    headers: Mapping[str, str] | None = None,
    deadline_seconds: float | None = None,
    phase_seconds: float | None = None,
) -> Response:
    """The real fetch. Never raises: an error is a Response with status 0,
```

3. Replace

```python
    Accept-Encoding are always the pinned ones.
    """
    deadline = time.monotonic() + DEADLINE_SECONDS
```

with

```python
    Accept-Encoding are always the pinned ones. `deadline_seconds` and
    `phase_seconds` replace DEADLINE_SECONDS and PHASE_TIMEOUT_SECONDS for
    this fetch.
    """
    limit = DEADLINE_SECONDS if deadline_seconds is None else deadline_seconds
    phase = PHASE_TIMEOUT_SECONDS if phase_seconds is None else phase_seconds
    deadline = time.monotonic() + limit
```

4. Replace

```python
timeout=httpx.Timeout(min(PHASE_TIMEOUT_SECONDS, left)),
```

with

```python
timeout=httpx.Timeout(min(phase, left)),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_http_fetch.py 2>&1 | tail -1`
Expected: a line starting with `56 passed`.

- [ ] **Step 5: Mutation check (red evidence for the phase parameter)**

With the Edit tool, temporarily change `timeout=httpx.Timeout(min(phase, left)),` in `packages/core/bsi_core/crawl.py` to `timeout=httpx.Timeout(min(PHASE_TIMEOUT_SECONDS, left)),`, run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own, then `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_http_fetch.py 2>&1 | tail -1`. Expected: a line starting with `1 failed, 55 passed`. Restore the line with the Edit tool and confirm with `cd /Users/vineet/Downloads/ADK/bsi-platform && grep -c "timeout=httpx.Timeout(min(phase, left))," packages/core/bsi_core/crawl.py` (expected `1`). Record both outputs in the report.

- [ ] **Step 6: Banned-word grep, then the backend gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/crawl.py tests/unit/test_http_fetch.py`. Run the banned-word grep (expected: no match). Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own, then the Backend gate with `<N>` = 1. Expected: `gate exit 0`; `gate-task1.txt` shows `1696 passed, 2 deselected`, mypy `Success`, and the metrics coverage line at 100%. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the two staged files, plus the untracked `.DS_Store` and `packages/.DS_Store` that were there before this slice).

- [ ] **Step 7: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/crawl.py tests/unit/test_http_fetch.py && git commit -m "feat(core): http_fetch takes its own deadline and phase timeout

deadline_seconds and phase_seconds override DEADLINE_SECONDS and
PHASE_TIMEOUT_SECONDS for one fetch; every caller that passes neither
keeps the 30 s deadline and 15 s phase.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: the SERP call waits 120 s; a read timeout is `timeout`; one locale

**Files:**
- Modify: `packages/core/bsi_core/providers/dataforseo.py`
- Modify: `apps/workers/bsi_workers/worker.py:117-120`, `:1168-1170`
- Test: `tests/unit/test_dataforseo.py`, `tests/integration/test_serp_audit.py`

**Interfaces:**
- Consumes: Task 1's `http_fetch(..., deadline_seconds=..., phase_seconds=...)`; the unit test file's `body()`, `Fetch` (records `(url, user_agent, kwargs)` per call), `_serp(fetch, ...)`, `SerpPage(items, cost_micros, error)`, `Response(status, body="", error=None, truncated=False)`; the integration file's `configured`, `owner`, `make_org`, `make_brand` fixtures and `_job`, `_run`, `_rows`, `_load_job`.
- Produces: `SERP_TIMEOUT_SECONDS = 120`, `TIMEOUT_MICROS = 4_000`, error code `timeout` (Task 3 labels it), `MAX_SERP_LOCALES = 1`.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_dataforseo.py`:

1. Replace

```python
def test_an_http_failure_is_http(response):
    assert _serp(Fetch(response)) == SerpPage([], 0, "http")
```

with

```python
def test_an_http_failure_is_http(response):
    assert _serp(Fetch(response)) == SerpPage([], 0, "http")


def test_the_call_waits_for_the_serp_timeout():
    fetch = Fetch(Response(200, body()))
    _serp(fetch)
    [(_, _, kw)] = fetch.calls
    assert (kw["deadline_seconds"], kw["phase_seconds"]) == (120, 120)


def test_a_read_timeout_is_timeout_with_the_expected_cost():
    resp = Response(0, error="ReadTimeout('The read operation timed out')")
    assert _serp(Fetch(resp)) == SerpPage([], 4_000, "timeout")


@pytest.mark.parametrize(
    "error",
    [
        "ConnectTimeout('timed out')",
        "WriteTimeout('timed out')",
        "PoolTimeout('timed out')",
        "ConnectError('boom')",
        "refused: nike.com does not resolve",
        "timeout: over the 30 s deadline",
    ],
)
def test_other_status_0_failures_are_http(error):
    assert _serp(Fetch(Response(0, error=error))) == SerpPage([], 0, "http")
```

In `tests/integration/test_serp_audit.py`:

1. Replace

```python
def test_only_the_first_five_locales_are_audited(
```

with

```python
def test_only_the_first_locale_is_audited(
```

2. Replace

```python
    assert len(fetch.calls) == 10 and len(_rows(owner, bid)) == 10
    job = _load_job(owner, job_id)
    assert (job.status, job.cost_micros) == ("done", 40_000)
```

with

```python
    assert len(fetch.calls) == 2 and len(_rows(owner, bid)) == 2
    job = _load_job(owner, job_id)
    assert (job.status, job.cost_micros) == ("done", 8_000)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && COLUMNS=200 uv run pytest -q -p no:cacheprovider tests/unit/test_dataforseo.py tests/integration/test_serp_audit.py 2>&1 | grep -E "^FAILED|passed|failed"`
Expected: a line starting with `3 failed, 93 passed`. The FAILED lines are `test_the_call_waits_for_the_serp_timeout`, `test_a_read_timeout_is_timeout_with_the_expected_cost` and `test_only_the_first_locale_is_audited`. The 6 `test_other_status_0_failures_are_http` cases pass on main: they pin existing behaviour. Paste the output into the report.

- [ ] **Step 3: Write the implementation**

In `packages/core/bsi_core/providers/dataforseo.py`, make three replacements.

1. Replace

```python
        headers: Mapping[str, str] | None = None,
    ) -> Response: ...
```

with

```python
        headers: Mapping[str, str] | None = None,
        deadline_seconds: float | None = None,
        phase_seconds: float | None = None,
    ) -> Response: ...
```

2. Replace

```python
SERP_CAP_BYTES = 4 * 1024 * 1024
```

with

```python
SERP_CAP_BYTES = 4 * 1024 * 1024
SERP_TIMEOUT_SECONDS = 120  # DataForSEO's advice for live SERP calls
TIMEOUT_MICROS = 4_000  # one call's expected price, about $0.004
```

3. Replace

```python
        headers={"Authorization": f"Basic {token}"},
    )
    if not resp.ok:
        return _refused(resp)
```

with

```python
        headers={"Authorization": f"Basic {token}"},
        deadline_seconds=SERP_TIMEOUT_SECONDS,
        phase_seconds=SERP_TIMEOUT_SECONDS,
    )
    if not resp.ok:
        if resp.status == 0 and (resp.error or "").startswith("ReadTimeout"):
            # Sent but not answered in time: the provider may bill it.
            return SerpPage(cost_micros=TIMEOUT_MICROS, error="timeout")
        return _refused(resp)
```

In `apps/workers/bsi_workers/worker.py`, make two replacements.

1. Replace

```python
# 5 locales x 2 queries x $0.004 (a live page plus AI Overview loading).
SERP_JOB_MICROS = 40_000
MAX_SERP_LOCALES = 5
```

with

```python
# Kept from 5 locales x 2 queries x $0.004 (a live page plus AI Overview
# loading); with one locale it overestimates, which fails closed.
SERP_JOB_MICROS = 40_000
# One locale: 2 calls of up to ~240 s each (a 120 s read, then up to a
# 120 s body read before the deadline check) stay under claim_job()'s
# 10 minutes, assuming a quick connect and send and headers in one read.
MAX_SERP_LOCALES = 1
```

2. Replace

```python
    A job is claimed before an observation: jobs are rare, user-facing
    and about a minute long, so a 9,000-observation run must not delay
    one for hours.
```

with

```python
    A job is claimed before an observation: jobs are rare, user-facing
    and at most a few minutes long (a SERP audit up to about 8), so a
    9,000-observation run must not delay one for hours.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_dataforseo.py tests/integration/test_serp_audit.py 2>&1 | tail -1`
Expected: a line starting with `96 passed` (85 + 11).

- [ ] **Step 5: Mutation check (red evidence for the timeout branch)**

With the Edit tool, temporarily change `(resp.error or "").startswith("ReadTimeout")` in `packages/core/bsi_core/providers/dataforseo.py` to `(resp.error or "").startswith("NoSuchError")`, run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own, then `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_dataforseo.py 2>&1 | tail -1`. Expected: a line starting with `1 failed, 84 passed`. Restore the text with the Edit tool and confirm with `cd /Users/vineet/Downloads/ADK/bsi-platform && grep -c 'startswith("ReadTimeout")' packages/core/bsi_core/providers/dataforseo.py` (expected `1`). Record both outputs in the report.

- [ ] **Step 6: Banned-word grep, then the backend gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/providers/dataforseo.py apps/workers/bsi_workers/worker.py tests/unit/test_dataforseo.py tests/integration/test_serp_audit.py`. Run the banned-word grep (expected: no match). Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own, then the Backend gate with `<N>` = 2. Expected: `gate exit 0`; `gate-task2.txt` shows `1704 passed, 2 deselected`, mypy `Success`, and the metrics coverage line at 100%. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the four staged files plus the two untracked `.DS_Store` files).

- [ ] **Step 7: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/providers/dataforseo.py apps/workers/bsi_workers/worker.py tests/unit/test_dataforseo.py tests/integration/test_serp_audit.py && git commit -m "fix(core): wait 120 s for a SERP call; record a read timeout

The DataForSEO call passes deadline_seconds and phase_seconds of 120
(DataForSEO's advice). A status-0 ReadTimeout is recorded as timeout
at 4,000 micros, the expected price; other status-0 failures stay
http at cost 0. An audit covers one locale so it stays under
claim_job()'s 10 minutes.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: the page labels `timeout`

**Files:**
- Modify: `apps/web/src/lib/format.ts:162`
- Test: `apps/web/src/lib/format.test.ts:232-239`

**Interfaces:**
- Consumes: Task 2's error code `timeout`; `serpError(code)` and `SERP_ERRORS` in format.ts.
- Produces: the label `"the SERP provider took too long to answer"`.

- [ ] **Step 1: Write the failing test**

In `apps/web/src/lib/format.test.ts`, replace

```ts
  expect(serpError("paused")).toBe(
    "the SERP provider paused the account; contact its support",
  );
});
```

with

```ts
  expect(serpError("paused")).toBe(
    "the SERP provider paused the account; contact its support",
  );
});

test("serpError labels a SERP call that timed out", () => {
  expect(serpError("timeout")).toBe(
    "the SERP provider took too long to answer",
  );
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/format.test.ts 2>&1 | grep -E "FAIL|Tests "`
Expected: `serpError labels a SERP call that timed out` fails (it receives `"timeout"`); the summary shows `1 failed`. Paste the output into the report.

- [ ] **Step 3: Write the implementation**

In `apps/web/src/lib/format.ts`, replace

```ts
  rate: "the SERP provider's rate limit was hit",
```

with

```ts
  rate: "the SERP provider's rate limit was hit",
  timeout: "the SERP provider took too long to answer",
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/format.test.ts 2>&1 | grep -E "Tests "`
Expected: `Tests  28 passed (28)` (27 existing tests in format.test.ts plus the new one).

- [ ] **Step 5: Banned-word grep, then the web gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/format.ts apps/web/src/lib/format.test.ts`. Run the banned-word grep (expected: no match). Run the Web gate with `<N>` = 3. Expected: `web gate exit 0`; `web-task3.txt` shows `Tests  49 passed (49)` and `Compiled successfully`, and `gen:check` shows no diff (no API change).

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/format.ts apps/web/src/lib/format.test.ts && git commit -m "feat(web): label a SERP call that timed out

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (plan vs spec)

- Spec coverage: `http_fetch` → Task 1 Step 3 (the four replace blocks, including the docstring wording of spec R7); the adapter → Task 2 Step 3; the worker (constant, comments, `tick` docstring) → Task 2 Step 3; the page → Task 3; Tests → Task 1 Step 1, Task 2 Step 1, Task 3 Step 1 (identical to the spec's blocks); Proof → the spec's scratch run, with mutants m5 (Task 1 Step 5) and m2 (Task 2 Step 5) repeated in the repo and the web label shown red and green in Task 3; Copy → each task's banned-word grep. Docs: this plan, the two docs/README.md rows and the three findings-slice37 notes are committed by the controller with the plan; the post-merge docs are controller work. The live check re-run comes after merge, asked first (spec, Docs).
- Departures from the spec:
  1. The code changes are replace blocks generated from the scratch proof's verified pairs, not the spec's unified diffs; the result is the same files.
  2. The work is split into three tasks (crawl; adapter and worker; web), each with its own commit; the spec does not set task boundaries.
  3. Only mutants m5 and m2 are repeated during execution; m1, m3, m4 and m6–m9 are the spec's evidence and are not re-run.
  4. Task 3's red and green runs and its web gate are the first time the web label is run (the spec says execution shows them).
  5. The commit messages are the plan's wording; the spec does not give them.
  6. The per-task backend counts (1696 after Task 1) are the plan's arithmetic; the spec gives only the final 1704.
  7. The header offers superpowers:executing-plans as well as subagent-driven-development (the template's wording); the controller uses subagent-driven execution.
- Rulings applied to this plan: the spec's R1–R9 (R3 in the renamed locale test, R9 in the findings note), R10 (the plan review's two wording points) and R11 (a third findings-slice37 note).
- Placeholders: `<workspace>` (the plan's directory under the git-ignored `.superpowers/sdd/`, supplied in the task brief) and `<N>` (the task number).
- Type consistency: `http_fetch(..., deadline_seconds: float | None = None, phase_seconds: float | None = None)` in Task 1 matches `SerpFetch` and the call in Task 2; the code `timeout` matches Task 3's label key.

## Changes made during execution

- Task 1: commit 7e726e0; Task 2: commit 5b39144; Task 3: commit db34fa4, each as planned (each task review says "✅ Spec compliant"). Then, after the user asked for the live check before merging: fix 1 a467d56 (`TIMEOUT_MICROS = 2_000`, R14), fix 2 facb108 (the `MAX_COST_USD` comment, R16), and docs commits 584be30 (the re-run note; R15 records that it also applied R13's two minors), 74e7621 (R16), 5a45934 (R17) and b00499e (R18). Merged via PR #82 (main `b0ed3a8`).
- Implementer gates: gate-task1.txt `1696 passed, 2 deselected, 2 warnings in 230.48s (0:03:50)`; gate-task2.txt `1704 passed, 2 deselected, 2 warnings in 261.28s (0:04:21)`; web-task3.txt `Tests  49 passed (49)`; fix 1 gate `1704 passed, 2 deselected, 2 warnings in 166.46s (0:02:46)`. Controller gates on 5a45934: `1704 passed, 2 deselected, 2 warnings in 218.89s (0:03:38)`, web `Tests  49 passed (49)`. CI on b00499e: `gates` passed in 4m17s with `1704 passed, 2 deselected, 2 warnings in 142.11s (0:02:22)`. Gates on main after merge: `1704 passed, 2 deselected, 2 warnings in 237.23s (0:03:57)`; web `Tests  49 passed (49)`.
- Reviews, as the ledger records them:
  - "Plan review (ab0e0f7a206ea4eb9, 840e66a): "Ready to execute? Yes"; 0 Critical, 0 Important, 3 Minor. R10 applied Minors 1-2 (b478e25); the user chose R11 for Minor 3."
  - "Task 1: task review (a88b560ab07501a65, 7c38281..7e726e0): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 3 Minor; 2 ⚠️ items (red/green/mutant/gate counts from the report; whether the 2 warnings are baseline)."
  - "Task 2: task review (ac1547ba2f28ff1b3, 7e726e0..5b39144): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 4 Minor; 1 ⚠️ item (red/green/mutant/gate counts and the banned-word grep from the report)."
  - "Task 3: task review (ab9fae35cf2625fce, 5b39144..db34fa4): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 1 Minor; ⚠️ items (red/green/web gate from the report; the banned-word grep; that the adapter sends 'timeout')."
  - "Final review (adadf2b9c0d8d306f, d049be7..db34fa4): "Ready to merge? Yes"; 0 Critical, 0 Important, 3 Minor; deferred-minor triage: all 7 "No" (none must be fixed before merge); the reviewer ran a real httpx.ReadTimeout through http_fetch into serp(): SerpPage([], 4000, 'timeout')."
  - "Fix 1 + docs review (aca8573b098807b40, db34fa4..584be30): "Ready to merge? With fixes"; 0 Critical, 0 Important, 5 Minor."
  - "Re-review (a5483b2df6e2f0931, 584be30..74e7621): "Ready to merge? Yes"; Minors 1, 2, 5 and three of 3's statements resolved; worker.py comment and R15 left by decision; 0 new findings."
  - "Diagnostic docs review (acf10e479e9cd64f5, 74e7621..5a45934): "Ready to merge? With fixes"; 1 Important (the note's "echoed the task as sent (India, location code 2356, google.com …)" is wider than its source: the echo has location_code and se_domain null and adds os windows; 2356 and google.com come from the result), 0 Minor."
  - "Re-review (a4acf1f472ccec68e, 5a45934..b00499e): "Ready to merge? Yes"; R18's finding resolved; 0 new findings; side note: the observation log said null where the keys are absent — corrected in the log."
- Rulings from planning and execution: R12–R18 (and R19 from the post-merge docs review), in the spec's Rulings. The twelve deferred minors are quoted in the spec's "Deferred minors" section.
