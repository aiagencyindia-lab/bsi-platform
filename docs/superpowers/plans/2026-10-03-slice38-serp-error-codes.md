# Slice 38 SERP Error Codes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The DataForSEO adapter reads the provider's error code from a non-2xx answer, knows codes 40104 (`unverified`) and 40201 (`paused`), and only accepts a plain integer from 0 to 99999 as a status; the page labels the two new codes.

**Architecture:** All behaviour is in `packages/core/bsi_core/providers/dataforseo.py`: a `_status` check, a reordered task-status read in `_parse`, and a `_refused` function for non-2xx answers. The worker and API pass the code through unchanged; the web app gains two labels in `SERP_ERRORS`.

**Tech Stack:** Python 3.13, pytest; TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-10-03-slice38-serp-error-codes-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice38-serp-error-codes`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB (`bsi`), the network, the worker loop, DataForSEO or a model: every test uses the file's fake `Fetch`.
- **Shared test DB:** run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own before every pytest run; if it prints a running pytest, stop and wait. Never run two suites at once. Run the full backend suite only in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal: read the file and repeat the edit.)
- **Writing files:** use the Edit or Write tools; never a shell heredoc or zsh `echo` to write files, including commit messages written to files. Never run `rm`.
- **Lint and types:** ruff line length 80, target py313, rules E F I B UP RUF; `mypy --strict` covers `packages/core/bsi_core`.
- **Banned words:** copy (code, comments, docstrings, labels, test names) never contains the words listed in `FORBIDDEN` in tests/unit/test_recommend_copy.py.
- **Banned-word grep:** `cd /Users/vineet/Downloads/ADK/bsi-platform && git diff --cached -U0 | grep '^+' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'`, run after staging. Expected: no match (grep exits 1 and prints nothing).
- **Backend gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform && { uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task<N>.txt 2>&1; echo "gate exit $?"`. If `ruff format .` changed a file, re-stage it, re-run the banned-word grep, and say so in the report.
- **Web gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate > <workspace>/web-task<N>.txt 2>&1; echo "web gate exit $?"`.
- **`<workspace>`:** the path given in your task brief (the plan's directory under the git-ignored `.superpowers/sdd/`); if none is given, stop and ask.
- **Commit trailer:** exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (spec R1). Use this line even if your own session reminder names another model.
- **Baseline counts** (collected 2026-10-03 on main `54775b6`): backend `1643/1645 tests collected (2 deselected)`; tests/unit/test_dataforseo.py 27; web 47 vitest. After Task 1: test_dataforseo.py 52, backend `1668 passed, 2 deselected`. After Task 2: web 48, backend unchanged at 1668.

## File map

| File | Responsibility | Task |
|---|---|---|
| `packages/core/bsi_core/providers/dataforseo.py` | `MAX_STATUS`, `_status`, the two new `ERRORS` codes, the task-status read in `_parse`, `_refused` | 1 |
| `tests/unit/test_dataforseo.py` | two `ERROR_CODES` rows; the non-2xx, bad-status, range and missing-status tests | 1 |
| `apps/web/src/lib/format.ts` | the `unverified` and `paused` labels | 2 |
| `apps/web/src/lib/format.test.ts` | one test for the two labels | 2 |

---

### Task 1: the adapter reads error codes from non-2xx answers

**Files:**
- Modify: `packages/core/bsi_core/providers/dataforseo.py`
- Test: `tests/unit/test_dataforseo.py`

**Interfaces:**
- Consumes: the file's existing `ERRORS`, `_code`, `_micros`, `_item`, `_parse`, `UNREADABLE`, `SerpPage`, `Response` (from `..crawl`; `.ok` is 2xx, `.body` the decoded text, `.truncated` the cap flag).
- Produces: error codes `unverified` and `paused` (Task 2 labels them); `MAX_STATUS = 99_999`; `_status(value: object) -> int | None`; `_refused(resp: Response) -> SerpPage`. `serp()` keeps its signature and never raises.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_dataforseo.py`, replace

```python
    (40202, "rate"),
    (50000, "provider_50000"),
]
```

with

```python
    (40202, "rate"),
    (40104, "unverified"),
    (40201, "paused"),
    (50000, "provider_50000"),
]
```

Then replace the file's last two lines

```python
    raw = "[" * 200_000 + "]" * 200_000
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "json")
```

with those two lines followed by the new tests:

```python
    raw = "[" * 200_000 + "]" * 200_000
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "json")


REFUSED = [
    (401, 40100, "auth"),
    (402, 40210, "funds"),
    (403, 40104, "unverified"),
    (429, 40202, "rate"),
    (403, 50301, "provider_50301"),
]


@pytest.mark.parametrize(("http", "status", "code"), REFUSED)
def test_a_refused_answer_is_its_providers_code(http, status, code):
    raw = json.dumps({"status_code": status, "cost": 0, "tasks": None})
    assert _serp(Fetch(Response(http, raw))) == SerpPage([], 0, code)


def test_a_refused_answer_keeps_a_task_code_and_its_cost():
    raw = body(task_status=40210)
    assert _serp(Fetch(Response(402, raw))) == SerpPage([], 4_000, "funds")


@pytest.mark.parametrize(
    "response",
    [
        Response(403, "{}"),
        Response(401, "<html>Unauthorized</html>"),
        Response(403, body()),
        Response(401, body(status=40100)[:30], truncated=True),
        Response(403, body(task_status=[1, 2])),
    ],
)
def test_a_refused_answer_without_a_code_is_http(response):
    assert _serp(Fetch(response)) == SerpPage([], 0, "http")


@pytest.mark.parametrize("status", [[1, 2], True, 100_000, -1])
def test_a_bad_task_status_is_json_and_keeps_the_cost(status):
    raw = body(task_status=status)
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 4_000, "json")


@pytest.mark.parametrize("status", [True, 100_000])
def test_a_bad_top_level_status_is_json(status):
    raw = body(status=status)
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 0, "json")


def test_a_top_level_error_wins_over_a_bad_task_status():
    raw = body(status=40100, task_status=[1, 2])
    assert _serp(Fetch(Response(200, raw))) == SerpPage([], 4_000, "auth")


@pytest.mark.parametrize(
    ("status", "code"), [(0, "provider_0"), (99_999, "provider_99999")]
)
def test_the_status_range_ends_are_codes(status, code):
    page = _serp(Fetch(Response(200, body(task_status=status))))
    assert page == SerpPage([], 4_000, code)


def test_a_task_without_a_status_is_json_and_keeps_the_cost():
    doc = json.loads(body())
    del doc["tasks"][0]["status_code"]
    page = _serp(Fetch(Response(200, json.dumps(doc))))
    assert page == SerpPage([], 4_000, "json")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first (if it prints a running pytest, wait), then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_dataforseo.py 2>&1 | tail -1`
Expected: `17 failed, 35 passed`. The failures are the 4 new `ERROR_CODES` cases, the 5 `test_a_refused_answer_is_its_providers_code` cases, `test_a_refused_answer_keeps_a_task_code_and_its_cost`, the 4 `test_a_bad_task_status_is_json_and_keeps_the_cost` cases, the 2 `test_a_bad_top_level_status_is_json` cases and `test_a_task_without_a_status_is_json_and_keeps_the_cost`.

- [ ] **Step 3: Change the adapter**

Make these six replacements in `packages/core/bsi_core/providers/dataforseo.py`, in order:

1. Replace

```python
ERRORS = {40100: "auth", 40200: "funds", 40210: "funds", 40202: "rate"}
```

with

```python
ERRORS = {
    40100: "auth",
    40104: "unverified",
    40200: "funds",
    40201: "paused",
    40202: "rate",
    40210: "funds",
}
MAX_STATUS = 99_999  # documented codes have five digits
```
2. Replace

```python
def _micros(cost: object) -> int:
```

with

```python
def _status(value: object) -> int | None:
    """A provider status code, or None: only a plain integer (not a
    bool) from 0 to MAX_STATUS counts, so a stored error stays short."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= MAX_STATUS else None


def _micros(cost: object) -> int:
```
3. Replace

```python
    """The page in a decoded response; raises on an undocumented shape."""
    if not isinstance(doc, dict):
        raise ValueError("not an object")
    top = doc["status_code"]
    if not isinstance(top, int):
        raise ValueError("status_code is not a number")
```

with

```python
    """The page in a decoded response. Raises on an undocumented shape
    until the task's cost is read; after that, returns `json` with it."""
    if not isinstance(doc, dict):
        raise ValueError("not an object")
    top = _status(doc["status_code"])
    if top is None:
        raise ValueError("status_code is not a status")
```
4. Replace

```python
    # The top-level status first, then the task's (spec, The adapter).
    error = _code(top) or _code(task["status_code"])
```

with

```python
    # The top-level status first, then the task's (spec, The adapter).
    error = _code(top)
    if error is None:
        status = _status(task.get("status_code"))
        if status is None:
            return SerpPage(cost_micros=cost, error="json")
        error = _code(status)
```
5. Replace

```python
def serp(
    query: str,
```

with

```python
def _refused(resp: Response) -> SerpPage:
    """A non-2xx answer: the provider's error code from its body when it
    has one; otherwise `http`. `truncated` is not consulted: a cut body
    fails to decode, which is also `http`."""
    try:
        page = _parse(json.loads(resp.body))
    except UNREADABLE:
        return SerpPage(error="http")
    if page.error in (None, "json"):
        return SerpPage(error="http")
    return SerpPage(cost_micros=page.cost_micros, error=page.error)


def serp(
    query: str,
```
6. Replace

```python
    if not resp.ok:
        return SerpPage(error="http")
```

with

```python
    if not resp.ok:
        return _refused(resp)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run `pgrep -fl pytest` on its own first, then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_dataforseo.py tests/integration/test_serp_audit.py 2>&1 | tail -1`
Expected: all passed, 0 failed (52 in test_dataforseo.py plus test_serp_audit.py's 11; its partial-failure test still gets `http` from a 500 with body "oops").

- [ ] **Step 5: Mutation check (red evidence for the guard)**

Show that the new non-2xx path is what the tests pin. With the Edit tool, temporarily change the line `        return _refused(resp)` in `packages/core/bsi_core/providers/dataforseo.py` back to `        return SerpPage(error="http")`, run `pgrep -fl pytest` on its own, then `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_dataforseo.py 2>&1 | tail -1`. Expected: `6 failed, 46 passed`. Then restore the line to `        return _refused(resp)` with the Edit tool and confirm with `cd /Users/vineet/Downloads/ADK/bsi-platform && grep -c "        return _refused(resp)" packages/core/bsi_core/providers/dataforseo.py` (expected `1`). Record both outputs in the report.

- [ ] **Step 6: Banned-word grep, then the backend gate**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/providers/dataforseo.py tests/unit/test_dataforseo.py`. Run the banned-word grep (expected: no match). Run `pgrep -fl pytest` on its own, then the Backend gate with `<N>` = 1. Expected: `gate exit 0`; `gate-task1.txt` shows `1668 passed, 2 deselected`, mypy `Success`, and the metrics coverage line at 100%. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the two staged files, plus the untracked `.DS_Store` and `packages/.DS_Store` that were there before this slice).

- [ ] **Step 7: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/providers/dataforseo.py tests/unit/test_dataforseo.py && git commit -m "fix(core): read DataForSEO error codes from non-2xx answers

A non-2xx answer whose body carries a provider error code now gets
that code (401/40100 is auth, 403/40104 unverified) instead of http;
40104 and 40201 (paused) are mapped; a status counts only as a plain
integer from 0 to 99999; the top-level code still wins over the
task's.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: the page labels the two new codes

**Files:**
- Modify: `apps/web/src/lib/format.ts`
- Test: `apps/web/src/lib/format.test.ts`

**Interfaces:**
- Consumes: the error codes `unverified` and `paused` from Task 1; the existing `SERP_ERRORS` table and `serpError(code)` in `format.ts` (already imported in `format.test.ts`).
- Produces: nothing for later tasks.

- [ ] **Step 1: Write the failing test**

In `apps/web/src/lib/format.test.ts`, replace

```ts
  expect(serpError(null)).toBe("");
});
```

with

```ts
  expect(serpError(null)).toBe("");
});

test("serpError labels an unverified or paused provider account", () => {
  expect(serpError("unverified")).toBe(
    "the SERP provider account is not verified",
  );
  expect(serpError("paused")).toBe(
    "the SERP provider paused the account; contact its support",
  );
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/format.test.ts 2>&1 | grep -E "AssertionError|FAIL|Tests "`
Expected: 1 failed: `serpError labels an unverified or paused provider account`, expecting "the SERP provider account is not verified" and receiving "unverified".

- [ ] **Step 3: Add the labels**

In `apps/web/src/lib/format.ts`, replace

```ts
  auth: "the SERP provider rejected the login",
```

with

```ts
  auth: "the SERP provider rejected the login",
  unverified: "the SERP provider account is not verified",
  paused: "the SERP provider paused the account; contact its support",
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/format.test.ts 2>&1 | tail -4`
Expected: the file passes, 0 failed.

- [ ] **Step 5: Banned-word grep, then both gates**

Stage: `cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/format.ts apps/web/src/lib/format.test.ts`. Run the banned-word grep (expected: no match). Run the Web gate with `<N>` = 2. Expected: `web gate exit 0`; `web-task2.txt` shows `Tests  48 passed (48)` and `Compiled successfully`; `gen:check` leaves no diff (no API change). Then run `pgrep -fl pytest` on its own and the Backend gate with `<N>` = 2. Expected: `gate exit 0`; `gate-task2.txt` shows `1668 passed, 2 deselected`. Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` (expected: the two staged files, plus the untracked `.DS_Store` and `packages/.DS_Store` that were there before this slice).

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/format.ts apps/web/src/lib/format.test.ts && git commit -m "feat(web): label an unverified or paused SERP provider account

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (plan vs spec)

- Spec coverage: The adapter (`_status`, `MAX_STATUS`, the two codes, the task-status read after the top-level code, `_refused`, the docstrings) → Task 1 Step 3, whose six replacements produce exactly the file the spec's diff produces (checked by applying both to main's file in scratch); The page → Task 2 Step 3; Tests → Task 1 Step 1 (`ERROR_CODES` rows and the appended block, identical to the spec's) and Task 2 Step 1; Proof → the spec's scratch run; Task 1 Step 5 repeats mutant m1 in the repo; Copy → each task's banned-word grep. No live check (spec). Docs after merge are controller work.
- Departures from the spec:
  1. The adapter change is written as six replace blocks, not the spec's unified diff; the result is the same file.
  2. Only mutant m1 is repeated during execution (Task 1 Step 5); m2–m11 are the spec's evidence and are not re-run.
  3. The web test's text (`serpError labels an unverified or paused provider account`, two `expect` calls) is the plan's wording; the spec says only "one test that `serpError("unverified")` and `serpError("paused")` return the two labels".
  4. Task 1 Step 4 also runs tests/integration/test_serp_audit.py, which the spec mentions only as unchanged.
  5. The header offers superpowers:executing-plans as well as subagent-driven-development (the template's wording); the spec's Process section names subagent-driven execution, which the controller uses.
- Rulings applied to this plan: the spec's R1 (the Opus 5.5 trailer) and R8 (the plan review's five points).
- Placeholders: `<workspace>` (the plan's directory under the git-ignored `.superpowers/sdd/`, supplied in the task brief) and `<N>` (the task number).
- Type consistency: `_status(value: object) -> int | None`, `_refused(resp: Response) -> SerpPage` and `SerpPage(items, cost_micros, error)` as used in both blocks; the codes `unverified` and `paused` match between Task 1's `ERRORS` and Task 2's labels.

## Changes made during execution

- Task 1: commit 3a423ad. Task 2: commit 99c8f4f. Merged via PR #74 (main `da1ea9c`). Controller gates on `99c8f4f`: backend `1668 passed, 2 deselected, 2 warnings in 182.25s (0:03:02)`, metrics coverage 100%; web `Tests  48 passed (48)`. CI: `gates` passed in 4m11s with `1668 passed, 2 deselected, 2 warnings in 136.47s (0:02:16)`. Gates on main after merge: backend `1668 passed, 2 deselected, 2 warnings in 181.57s (0:03:01)`; web `Tests  48 passed (48)`.
- Reviews, as the ledger records them:
  - "Task 1: task review (ae44927e2f7592000, 49b740a..3a423ad): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 2 Minor; 1 ⚠️ item (the commit message and trailer from the report only; mutants m2-m11 not re-run, as the brief asks)."
  - "Task 2: task review (aab16b51588ca05b8, 3a423ad..99c8f4f): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 1 Minor; 1 ⚠️ item (gate outputs and red/green runs from the report only)."
  - "Final review (a73fbbd03bed267dc, 54775b6..99c8f4f): "Ready to merge? Yes"; 0 Critical, 0 Important, 3 Minor; deferred-minor triage: all three "leave deferred"."
- Deferred minors, as the ledger records them (the final review triaged the three task minors "leave deferred"; its own three were left by R9):
  - "Task 1: minor (deferred): the report quotes "1668 passed, 2 deselected" without the 2 known third-party warnings that the same gate line shows (fastapi/starlette testclient deprecations)"
  - "Task 1: minor (deferred): a non-2xx body with a top-level error code but an unreadable task (e.g. {"status_code":40100,"tasks":"abc"} on a 401) gives `http`, not the top-level code; follows the spec's wording ("every other non-2xx answer gives http"); no test pins it"
  - "Task 2: minor (deferred): the backend gate output carries the 2 known third-party warnings (fastapi/starlette testclient deprecations), not caused by this diff"
  - "Final: minor (deferred): docs/findings-slice37.md:11 lists the adapter's error codes without `unverified` and `paused`, and :96 says a non-2xx call "records 0" (a non-2xx body with a code now records the body's cost); the spec's post-merge list does not name these lines"
  - "Final: minor (deferred): dataforseo.py:154 `_refused` takes the cost from an untrusted non-2xx body; a huge cost (1e12 gives 10**18 micros) would overflow the Integer cost_micros column and fail the run as `error`; same as the 2xx path; a large cost is not yet in the open cost finding"
  - "Final: minor (deferred): no test sets error codes at both levels on a non-2xx answer (behaviour correct by probe; listed in the spec's Out of scope)"
- The ruling made during execution, as the ledger records it (also in the spec's Rulings): "Ruling: R9 — Decided: no fix wave; the post-merge docs add dated notes to findings-slice37.md lines 11 and 96, add "a large cost, now also on non-2xx answers" to the open cost finding, and record the unreadable-tasks case; the both-levels test stays out of scope. Found by: the final review (3 Minor, "Ready to merge? Yes"). Why: none is a code defect; the docs notes keep findings-slice37 accurate. Cost if wrong: a large provider cost stays unbounded until a later slice. How named: named in chat when made."
- After merge, per R9, docs/findings-slice37.md gained dated notes on its error-code list, its "Disproved" line, the bool-cost, unbounded-code and unknown-cost minors, and the parked R18 entry in §3 (writer's summary). The post-merge docs review then found that a very large cost would also overflow `job.cost_micros`, so the job's failure could not be recorded (R10; writer's reading of worker.py).
