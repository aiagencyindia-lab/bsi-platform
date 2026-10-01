# Slice 31 Public Rate Limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each share token gets 60 requests per 60-second window across the two public routes; past that the API answers 429 with `Retry-After`, and the web PDF proxy passes the 429 through.

**Architecture:** A `TokenLimiter` (fixed window, in process, under a lock) in a new `apps/api/bsi_api/ratelimit.py`, built once per app in `create_app()` and stored on `app.state`; the two routes in `routers/public.py` call `_limit(token, request)` first; `Problem` gains optional headers so the 429 carries `Retry-After` in the API's usual problem shape. The Next proxy maps an upstream 429 to a plain-text 429 with `Retry-After` copied.

**Tech Stack:** Python 3.13, FastAPI, pytest (shared `bsi_test` DB for the integration test); TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-10-01-slice31-public-rate-limit-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`. In zsh a variable holding several paths is not split into words; pass paths literally.
- **Branch:** `slice31-public-rate-limit`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB, the network or the worker loop. Never call a model.
- **Unchanged:** the keyed routes, `/healthz`, `_run`, PDF rendering, the schemas, `openapi.json`, `schema.d.ts`, the other exception handlers, `apps/web/src/lib/api.ts`, `apps/web/src/app/r/error.tsx`, the existing tests' expectations (only additions).
- **Shared test DB:** run `pgrep -fl pytest` first, and never run two suites at once. Run the full backend suite only once, in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal: read the file and repeat the edit.)
- **Writing files:** never use a shell heredoc or zsh `echo` to write files; use the Edit or Write tools.
- **Lint and types:** ruff line length is 80 (the Backend gate runs `ruff format .` first); RUF001 rejects a literal curly apostrophe. The gate's mypy covers only `packages/core/bsi_core`; apps/api is not type-checked by the gate.
- **Banned words:** copy (code, comments, docstrings, test names, fixtures, response bodies, docs) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat` or `certain` (`FORBIDDEN` in tests/unit/test_recommend_copy.py).
- **Banned-word grep:** `grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'`, run on added lines only (`git diff -U0 | grep '^+' | <the grep>`, or `git diff --cached -U0` after staging; a new file is grepped directly). Expected: no match.
- **Backend gate:** `{ uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task1.txt 2>&1; echo "gate exit $?"` (the echo prints to the terminal, not to a file).
- **Web gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate > <workspace>/gate-task2.txt 2>&1; echo "web gate exit $?"`.
- **Commit trailer:** the `Co-Authored-By` line from the latest session reminder.

## File map

| File | Responsibility |
|---|---|
| `apps/api/bsi_api/ratelimit.py` (new) | `MAX_KEYS`, `TokenLimiter` |
| `apps/api/bsi_api/problems.py` | `Problem.headers`; `_response(..., headers)`; the `Problem` handler passes them |
| `apps/api/bsi_api/main.py` | `app.state.public_limiter` |
| `apps/api/bsi_api/routers/public.py` | `PUBLIC_LIMIT`, `PUBLIC_WINDOW_SECONDS`, `_limit`, the two routes' first line |
| `tests/unit/test_ratelimit.py` (new) | the limiter's window, rounding and eviction |
| `tests/integration/test_api_reports.py` | the per-token 429 on the public routes |
| `apps/web/src/app/r/[token]/pdf/route.ts` | the 429 branch |
| `apps/web/src/app/r/[token]/pdf/route.test.ts` | the 429 case |
| docs | `docs/findings-slice31.md`, dated updates in `docs/findings-slice15.md` §3, `docs/README.md`, the spec's Rulings, this plan's changes section |

---

### Task 1: The limiter in the API

**Files:** Create `apps/api/bsi_api/ratelimit.py`, `tests/unit/test_ratelimit.py`. Modify `apps/api/bsi_api/problems.py` (lines ~12–44, 47–50), `apps/api/bsi_api/main.py` (imports, `create_app`), `apps/api/bsi_api/routers/public.py` (imports, after `NO_STORE`, the two routes), `tests/integration/test_api_reports.py` (append one test).

**Interfaces:**
- Produces: `bsi_api.ratelimit.TokenLimiter(limit: int, window: int, clock: Callable[[], float] = time.monotonic)` with `check(key: str) -> int | None`; `bsi_api.ratelimit.MAX_KEYS = 10_000`; `Problem(status, title, detail="", errors=None, headers=None)` with `.headers: dict[str, str]`; `app.state.public_limiter`; `public.PUBLIC_LIMIT = 60`, `public.PUBLIC_WINDOW_SECONDS = 60`.
- Consumes: `_scene(owner, make_org, make_brand)` and the `client` fixture (a fresh `TestClient(create_app())` per test; `client.app` is the FastAPI app) in tests/integration/test_api_reports.py.

- [ ] **Step 1: Write the failing tests.** Create `tests/unit/test_ratelimit.py` with exactly:

```python
from bsi_api import ratelimit
from bsi_api.ratelimit import TokenLimiter


class Clock:
    def __init__(self, at: float = 1_000.0) -> None:
        self.at = at

    def __call__(self) -> float:
        return self.at


def test_a_key_gets_its_budget_then_waits_until_the_window_ends():
    clock = Clock(1_000.0)
    limiter = TokenLimiter(2, 60, clock)
    assert limiter.check("a") is None
    assert limiter.check("a") is None
    # The window [960, 1020) has 20 s left.
    assert limiter.check("a") == 20
    assert limiter.check("b") is None
    clock.at = 1_020.0
    assert limiter.check("a") is None


def test_the_wait_rounds_up_to_a_whole_second():
    limiter = TokenLimiter(1, 60, Clock(1_019.5))
    assert limiter.check("a") is None
    assert limiter.check("a") == 1


def test_expired_keys_are_dropped_past_the_cap(monkeypatch):
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 1)
    clock = Clock(1_000.0)
    limiter = TokenLimiter(1, 60, clock)
    assert limiter.check("a") is None
    assert limiter.check("b") is None
    clock.at = 1_060.0
    assert limiter.check("c") is None
    assert list(limiter._seen) == ["c"]
```

Then append to `tests/integration/test_api_reports.py` (after its last line, separated by two blank lines):

```python
def test_public_routes_are_rate_limited_per_token(
    client, owner, make_org, make_brand
):
    from bsi_api.ratelimit import TokenLimiter

    org, bid = _scene(owner, make_org, make_brand)
    client.app.state.public_limiter = TokenLimiter(2, 60, lambda: 1_000.0)
    tok, other = (
        client.post(
            f"/v1/brands/{bid}/reports/{t}/runs", headers=org.headers
        ).json()["share_token"]
        for t in ("agency", "cmo")
    )
    assert client.get(f"/v1/r/{tok}").status_code == 200
    assert client.get(f"/v1/r/{tok}.pdf").status_code == 200
    r = client.get(f"/v1/r/{tok}")
    assert r.status_code == 429
    body = r.json()
    assert body["title"] == "Too many requests" and body["status"] == 429
    assert body["detail"] == "" and body["errors"] == []
    # A fixed clock: the window [960, 1020) has 20 s left (R5).
    assert r.headers["retry-after"] == "20"
    assert r.headers["x-request-id"] == body["request_id"]
    assert "nike" not in r.text.lower()
    # Another token has its own budget.
    assert client.get(f"/v1/r/{other}").status_code == 200
```

- [ ] **Step 2: Run them to see them fail.** `pgrep -fl pytest` (expect nothing), then `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_ratelimit.py`: expected a collection error (`ImportError: cannot import name 'ratelimit' from 'bsi_api'`; the file's first import is `from bsi_api import ratelimit`). Then `uv run pytest -q tests/integration/test_api_reports.py`: expected `1 failed, 13 passed` with `test_public_routes_are_rate_limited_per_token` failing on `ModuleNotFoundError`. If a result differs, stop and report it; do not change a test's expected values.

- [ ] **Step 3: Write the code.**

Create `apps/api/bsi_api/ratelimit.py` with exactly:

```python
"""A fixed-window request counter for the public routes."""

import math
import threading
import time
from collections.abc import Callable

# Keys kept before expired entries are dropped on the next check.
MAX_KEYS = 10_000


class TokenLimiter:
    """At most `limit` checks per `window` seconds for each key, counted
    in this process. ponytail: per-process state, so N workers allow N
    times the limit; Redis or an edge limiter (PRD) if that matters."""

    def __init__(
        self,
        limit: int,
        window: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit, self.window, self.clock = limit, window, clock
        self._seen: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> int | None:
        """None when the key is under its limit (this call counts);
        otherwise the whole seconds until its window ends, at least 1."""
        now = self.clock()
        index = int(now // self.window)
        with self._lock:
            if len(self._seen) > MAX_KEYS:
                # A soft cap: keys seen in this window stay until the next.
                self._seen = {
                    k: v for k, v in self._seen.items() if v[0] == index
                }
            start, count = self._seen.get(key, (index, 0))
            if start != index:
                count = 0
            if count >= self.limit:
                # now is inside the window, so this is at least 1.
                return math.ceil((index + 1) * self.window - now)
            self._seen[key] = (index, count + 1)
            return None
```

In `apps/api/bsi_api/problems.py`, replace

```python
        errors: list[Any] | None = None,
    ) -> None:
        self.status, self.title = status, title
        self.detail, self.errors = detail, errors or []
```

with

```python
        errors: list[Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status, self.title = status, title
        self.detail, self.errors = detail, errors or []
        self.headers = headers or {}
```

then replace

```python
    errors: list[Any] | None = None,
) -> JSONResponse:
    rid = getattr(request.state, "request_id", "")
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        headers={"X-Request-Id": rid},
```

with

```python
    errors: list[Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    rid = getattr(request.state, "request_id", "")
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        headers={"X-Request-Id": rid, **(headers or {})},
```

then replace

```python
        return _response(request, exc.status, exc.title, exc.detail, exc.errors)
```

with

```python
        return _response(
            request, exc.status, exc.title, exc.detail, exc.errors, exc.headers
        )
```

In `apps/api/bsi_api/main.py`, replace `from . import problems` with

```python
from . import problems
from .ratelimit import TokenLimiter
```

and replace `    problems.install(app)` with

```python
    problems.install(app)
    app.state.public_limiter = TokenLimiter(
        public.PUBLIC_LIMIT, public.PUBLIC_WINDOW_SECONDS
    )
```

In `apps/api/bsi_api/routers/public.py`, replace `from fastapi import APIRouter, Path, Response` with `from fastapi import APIRouter, Path, Request, Response`; replace

```python
NO_STORE = {"Cache-Control": "no-store"}
```

with

```python
NO_STORE = {"Cache-Control": "no-store"}
# One budget per share token across both public routes (slice 31).
PUBLIC_LIMIT = 60
PUBLIC_WINDOW_SECONDS = 60


def _limit(token: str, request: Request) -> None:
    """429 with Retry-After once a token has used its window's budget.
    Called first in each route, after path validation, so a malformed
    token is never counted."""
    wait = request.app.state.public_limiter.check(token)
    if wait is not None:
        raise Problem(
            429, "Too many requests", headers={"Retry-After": str(wait)}
        )
```

then replace

```python
@router.get("/{token}.pdf")
def public_pdf(token: Token) -> Response:
    run = _run(token)
```

with

```python
@router.get("/{token}.pdf")
def public_pdf(token: Token, request: Request) -> Response:
    _limit(token, request)
    run = _run(token)
```

then replace

```python
@router.get("/{token}", response_model=ReportRunOut)
def public_run(token: Token, response: Response) -> m.ReportRun:
    run = _run(token)
```

with

```python
@router.get("/{token}", response_model=ReportRunOut)
def public_run(
    token: Token, request: Request, response: Response
) -> m.ReportRun:
    _limit(token, request)
    run = _run(token)
```

Each old string above appears exactly once in its file.

- [ ] **Step 4: Run them to see them pass.** `pgrep -fl pytest`, then `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_ratelimit.py tests/integration/test_api_reports.py`. Expected: `17 passed`. Then confirm a malformed token's 422 still carries one error: `uv run python -c "from fastapi.testclient import TestClient; from bsi_api.main import create_app; r = TestClient(create_app(), raise_server_exceptions=False).get('/v1/r/short'); print(r.status_code, len(r.json()['errors']))"` → `422 1`. If anything differs, stop and report it.

- [ ] **Step 5: Gate.** `pgrep -fl pytest`, then the Backend gate once. Expected: `gate exit 0`, `1558 passed, 2 deselected` (1554 + 3 unit + 1 integration), metrics coverage 100%, the 2 known third-party warnings. Stage the six files (`git add apps/api/bsi_api/ratelimit.py apps/api/bsi_api/problems.py apps/api/bsi_api/main.py apps/api/bsi_api/routers/public.py tests/unit/test_ratelimit.py tests/integration/test_api_reports.py`), then run the Banned-word grep from Global Constraints on `git diff --cached -U0 | grep '^+'`: no match (a plain `git diff` would skip the two new files).

- [ ] **Step 6: Commit.** `git add apps/api/bsi_api/ratelimit.py apps/api/bsi_api/problems.py apps/api/bsi_api/main.py apps/api/bsi_api/routers/public.py tests/unit/test_ratelimit.py tests/integration/test_api_reports.py && git commit -m "feat(api): per-token rate limit on the public routes" -m "<trailer>"`.

---

### Task 2: The web proxy passes a 429 through

**Files:** Modify `apps/web/src/app/r/[token]/pdf/route.ts` (the status mapping) and `apps/web/src/app/r/[token]/pdf/route.test.ts` (one new case).

**Interfaces:** Consumes the API's 429 (`Retry-After` header). Produces a plain-text 429 "Too many requests" with `cache-control: no-store` and `retry-after` copied when present.

- [ ] **Step 1: Write the failing test.** In `route.test.ts`, replace

```ts
test("API 500 and a throwing fetch become 502 with no detail", async () => {
```

with

```ts
test("API 429 passes through with its Retry-After", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response("{}", { status: 429, headers: { "retry-after": "17" } }),
    ),
  );
  const res = await call(TOKEN);
  expect(res.status).toBe(429);
  expect(await res.text()).toBe("Too many requests");
  expect(res.headers.get("retry-after")).toBe("17");
  expect(res.headers.get("cache-control")).toBe("no-store");
});

test("API 500 and a throwing fetch become 502 with no detail", async () => {
```

- [ ] **Step 2: Run it to see it fail.** `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run "src/app/r/[token]/pdf/route.test.ts"`. Expected: `1 failed | 5 passed` ("expected 502 to be 429").

- [ ] **Step 3: Write the code.** In `route.ts`, replace

```ts
  if (!upstream.ok) return plain("Report unavailable", 502);
```

with

```ts
  if (upstream.status === 429) {
    const res = plain("Too many requests", 429);
    const retry = upstream.headers.get("retry-after");
    if (retry) res.headers.set("retry-after", retry);
    return res;
  }
  if (!upstream.ok) return plain("Report unavailable", 502);
```

- [ ] **Step 4: Run it to see it pass.** The Step 2 command. Expected: `6 passed`.

- [ ] **Step 5: Web gate.** The Web gate from Global Constraints, once. Expected: `web gate exit 0`, vitest `43 passed` (42 + 1), typecheck, lint, build and `gen:check` clean (no API schema change). Run the Banned-word grep from Global Constraints on `git diff -U0 | grep '^+'`: no match.

- [ ] **Step 6: Commit.** `git add "apps/web/src/app/r/[token]/pdf/route.ts" "apps/web/src/app/r/[token]/pdf/route.test.ts" && git commit -m "feat(web): the PDF proxy passes a 429 through with Retry-After" -m "<trailer>"`.

---

### Task 3: Docs

**Files:** Create `docs/findings-slice31.md` (the controller creates a one-line stub first; fill it with Edit). Modify `docs/findings-slice15.md` §3, `docs/README.md`, the spec's `## Rulings`, this plan's `## Changes made during execution`.

- [ ] **Step 1: Findings.** Fill `docs/findings-slice31.md` in the style of `docs/findings-slice30.md`:
  - `## 1. What was built`: `TokenLimiter` and its rule, `_limit` in both routes, `Problem.headers`, the `app.state` wiring, the proxy's 429 branch; the Task 1 Step 2/4/5 and Task 2 Step 2/4/5 results as the task reports record them; a commit table from `git log --oneline --reverse main..HEAD` with a "(this commit)" row.
  - `## 2. Live check on dev`: exactly "Not yet run. The controller runs it after merge with the user's approval (spec §2: a free, read-only check against a shared run on dev); results are recorded here then."
  - `## 3. Deferred and untested`: every `minor (deferred…)` and `parked` ledger line, quoted as recorded ("Parked: none" if none); every spec ruling quoted in full; the spec's Out of scope list; the still-open items under "Carried forward" in docs/findings-slice30.md §3; and "Untested: the limiter under concurrent requests (the lock is read in review, not exercised by a test); an unknown token's budget (it counts under its own key, pinned by no test)."
- [ ] **Step 2: Dated updates, originals kept.** Add a sub-bullet starting "Update 2026-10-01 (slice 31):" under each of the two docs/findings-slice15.md §3 bullets that begin "The public routes are not rate-limited" and "No rate limiting on the public routes": the public routes now allow 60 requests per minute per share token, then 429 with `Retry-After` (docs/findings-slice31.md).
- [ ] **Step 3: README rows** for the spec, the plan and the findings, after the row for `findings-slice30.md`, in the slice 30 rows' format; the spec row names the spec's final ruling range.
- [ ] **Step 4: Rulings.** For each ruling the ledger records that the spec's `## Rulings` does not already hold (match by R-number), add it after the spec's last ruling, copying the ledger line's labelled fields (Decided / Found by / Why / Cost if wrong / how named); mark any field you had to write yourself as your own wording.
- [ ] **Step 5: Plan changes.** Fill this plan's `## Changes made during execution` from the ledger: one bullet per task, quoting departures and any tool refusals as recorded; the bullet for the commit that fills this section ends "(this commit)".
- [ ] **Step 6: Grep.** Run the Banned-word grep from Global Constraints on `git diff -U0 docs | grep '^+'` (before staging) and directly on docs/findings-slice31.md (a new file); expected: no match. (docs/findings-slice15.md already holds two matches on lines 68 and 125, from before this slice; they are not added lines.)
- [ ] **Step 7: Commit** `git add docs && git commit -m "docs: slice 31 findings, index and notes" -m "<trailer>"`.

---

## Self-review against the spec

- §1 limiter: Task 1 Step 3 (`ratelimit.py` as specified: `_seen`, lock, `time.monotonic`, `!=`, `ceil`, soft `MAX_KEYS`; `_limit` first in both routes per R1; `app.state` wiring; `Problem.headers` and `_response` merge). Unchanged items: Global Constraints.
- §2 tests: Task 1 Step 1 (the three unit cases with the spec's values; the integration test with the in-function import, two tokens, the 429 shape); Task 2 Step 1 (the proxy case). Red/green: Task 1 Steps 2/4, Task 2 Steps 2/4. Copy grep: Task 1 Step 5, Task 2 Step 5, Task 3 Step 6.
- §2 web: Task 2 Step 3. §2 docs: Task 3 Steps 1–3. §2 live check: after merge, by the controller with the user's approval; findings §2 placeholder. §2 gates: the controller before the finishing menu (the tasks run them once each as evidence).
- Departures from the spec:
  1. Task 1 Step 4 adds a one-line check that a malformed token's 422 still has one error entry; the spec states the property but names no check.
  2. Test and comment wording the spec does not state: the `Clock` helper, the comment "The window [960, 1020) has 20 s left.", the test names, "Another token has its own budget.", the `_limit` docstring, the two inline comments in `ratelimit.py`, the proxy test's name.
  3. The implementation order is TDD (tests seen failing first); the spec records red/green on scratch only.
  4. Task 2's web gate expectation (43 vitest tests) and Task 1's gate count (1558) are the plan's arithmetic.
  5. Task 3 also updates the spec's Rulings and this plan's changes section, adds a findings §2 placeholder and an "Untested" line, and carries the slice 30 carried-forward items; the spec's docs list names none of these.
  6. Each task runs its own gate once as evidence (Task 1 the Backend gate, Task 2 the Web gate); the spec names only the controller's run before the finishing menu.
  7. The exact error text expected at each red step is the plan's wording.
  8. The integration test uses a fixed clock, `TokenLimiter(2, 60, lambda: 1_000.0)`, and asserts `Retry-After` is exactly 20; the spec says `TokenLimiter(2, 60)` and 1–60 (R5: a live clock can straddle a window boundary).
- Verified before committing this plan (2026-10-01, re-run after R5 and R6 with the fixed-clock test): every replacement in Tasks 1 and 2 was applied, from this file's own code blocks and inline strings, to scratch copies of main (each old string found exactly once). Python on main's code: the unit file fails at import and tests/integration/test_api_reports.py gives `1 failed, 13 passed` (`ModuleNotFoundError`); with the change the two files give `17 passed`, a malformed token gives `422 1`, ruff check and ruff format --check are clean on the four changed modules and both test files, and `mypy --strict` with the repo config, run by path, is clean on ratelimit.py and problems.py. Web: the proxy test gives `1 failed | 5 passed` against the current route.ts and `6 passed` with the change.
- Placeholders: only `<workspace>` and `<trailer>`.
- Type consistency: `TokenLimiter(limit, window, clock)` and `check(key) -> int | None` are the same in Interfaces, Step 3 and the tests; `Problem(..., headers=...)` matches `_limit`.

## Changes made during execution

- Before execution: the ledger records R8, "Decided: commit 5cf4e6c (the plan's R7 fixes) goes into execution unreviewed", the user's choice ("disclose and proceed"); Task 3 Step 4 added it to the spec's Rulings.
- Task 1 (56d2c38): went as written. The ledger records: "report: Step 2 unit ImportError at collection, integration 1 failed, 13 passed (ModuleNotFoundError); Step 4 17 passed, 422 1; Step 5 gate exit 0, 1558 passed, 2 deselected, metrics 100%, 2 known warnings; banned-word grep no match; ruff format changed no files"; the review "✅ Spec compliant; Task quality: Approved; 0 Critical, 0 Important, 3 Minor", all three deferred (quoted in docs/findings-slice31.md §3); and one controller check, "⚠️ resolved by controller: the 56d2c38 commit trailer is "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>" (git log -1 --format=%B before the review); the red/green/gate runs are the report's record". No departures and no tool refusals.
- Task 2 (4214137): went as written; the implementer reported DONE_WITH_CONCERNS. The ledger records: "report: Step 2 1 failed | 5 passed ("expected 502 to be 429"); Step 4 6 passed; Step 5 web gate exit 0, Tests 43 passed (43), typecheck/lint/build/gen:check passed; banned-word grep no match; concern: the trailer names Fable 5.1 while the subagent's own reminder names Opus 5.5". R9 rules on that concern (every slice 31 commit carries the session's Fable 5.1 trailer); Task 3 Step 4 added it to the spec's Rulings. The review "✅ Spec compliant; Task quality: Approved; 0 Critical, 0 Important, 2 Minor", both deferred (quoted in docs/findings-slice31.md §3); and one controller check, "⚠️ resolved by controller: the red/green/web-gate runs are the report's record (the controller re-runs the web gate before the finishing menu); the banned-word check is the report's, and the reviewer's own read of the added lines found none". No departures and no tool refusals.
- Task 3: the controller created the one-line stub `docs/findings-slice31.md` before dispatch, as this plan says. Findings filled, the two dated updates in docs/findings-slice15.md §3, the three README rows (spec range R1–R9), R8 and R9 added to the spec's Rulings (titles marked as the writer's own wording), and this section. No tool refusals. (f8035ad)
- Final review: the ledger records "Final review (a9ba853b5ddcce6fa, 7c5b227..f8035ad): "Ready to merge? With fixes"; 0 Critical, 2 Important, 3 Minor." and the triage "Final triage of the deferred minors: Task 1 O(n) sweep — fix before merge (Important 1, R10); Task 1 private _seen — leave deferred; Task 1 warnings — leave deferred; Task 2 no-retry-after test — leave deferred; Task 2 body not cancelled — leave deferred; Task 3 R5→R3 — fix before merge; Task 3 Before-execution bullet — leave deferred; Task 3 went-as-written — leave deferred; Task 3 nike clause — fix before merge". The two Important lines, the three final minors and the triage are quoted in docs/findings-slice31.md §3.
- Fix wave (R10, R11, R12): ratelimit.py sweeps at most once per window index (`self._swept`), a departure from spec §1 (R10; the spec's §1 carries a dated note); findings §1 says so; findings §3 quotes Task 3's four deferred minors, the final review's lines and triage, and R10–R12; findings line 17 cites R3 for the in-function import and names the "nike" check; R10–R12 added to the spec's Rulings (titles marked as the writer's own wording); the README spec row reads R1–R12. The commit carries the Opus 5.5 trailer (R12). No tool refusals. (ab8bc72)
- Fix-wave re-review, recorded after merge of PR #59 (main bd4a63d), as recorded: "Fix wave re-review (aef0258500db42a8a, f8035ad..ab8bc72): "All findings addressed: Yes"; new breakage 4 Minor, 0 Critical, 0 Important; 2 out-of-scope observations." Its four new minors are parked under R13 (two ledger lines) and its two out-of-scope observations recorded without a ruling; all are quoted in docs/findings-slice31.md §3, which also holds the live check (§2). Post-merge docs and R13 (this commit).
