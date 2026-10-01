# Slice 31 findings: a per-token rate limit on the public share-link routes

## 1. What was built

The open item "The public routes are not rate-limited" (recorded twice in docs/findings-slice15.md §3) is closed for one process: the two public routes, `GET /v1/r/{token}` and `GET /v1/r/{token}.pdf`, now share one budget of 60 requests per 60-second window per share token, then answer `429` with `Retry-After`.

**Code**:
- apps/api/bsi_api/ratelimit.py (new): `MAX_KEYS = 10_000` and `TokenLimiter(limit, window, clock=time.monotonic)` with `check(key) -> int | None`. The rule: a fixed window per key, state `_seen: dict[str, tuple[int, int]]` (`{key: (window_index, count)}`) under a `threading.Lock`, `window_index = int(now // window)`. A key with no entry, or with a stored window index `!=` the current one, starts again at count 0. Under the limit the call counts and `check` returns `None`; at the limit it returns `ceil((index + 1) * window - now)`, the whole seconds until the window ends (at least 1), and does not count the call. When `_seen` holds more than `MAX_KEYS` keys, entries from other windows are dropped before the check (a soft cap; `MAX_KEYS` is read at call time). The docstring carries the ponytail note: per-process state, so N workers allow N times the limit; Redis or an edge limiter (PRD) if that matters.
- apps/api/bsi_api/routers/public.py: `PUBLIC_LIMIT = 60` and `PUBLIC_WINDOW_SECONDS = 60` beside `NO_STORE`; `_limit(token, request)` calls `request.app.state.public_limiter.check(token)` and on a wait raises `Problem(429, "Too many requests", headers={"Retry-After": str(wait)})`. Both routes take `request: Request` and call `_limit` as their first line, before `_run` (R1), so path validation still runs first and a malformed token gets its single 422 and is never counted.
- apps/api/bsi_api/problems.py: `Problem` takes `headers: dict[str, str] | None = None` (stored as `.headers`, `{}` when None); `_response` merges them after `X-Request-Id`; the `Problem` handler passes `exc.headers`. The 429 has the 404's problem shape plus `Retry-After`.
- apps/api/bsi_api/main.py: `create_app()` sets `app.state.public_limiter = TokenLimiter(public.PUBLIC_LIMIT, public.PUBLIC_WINDOW_SECONDS)` right after `problems.install(app)`, so each app (and each test's fresh app) has its own limiter.
- apps/web/src/app/r/[token]/pdf/route.ts: before the `!upstream.ok` → 502 branch, an upstream 429 returns `plain("Too many requests", 429)` (`content-type: text/plain`, `cache-control: no-store`) and copies `retry-after` when the upstream sends one. `publicApi` and `error.tsx` are unchanged: the share page shows `error.tsx` on a 429.
- Unchanged: the keyed routes, `/healthz`, `_run`, PDF rendering, the schemas, `openapi.json`, `schema.d.ts` (the 429 is not declared), the other exception handlers.

**Tests**:
- tests/unit/test_ratelimit.py (new, a fake clock): `test_a_key_gets_its_budget_then_waits_until_the_window_ends`, `test_the_wait_rounds_up_to_a_whole_second`, `test_expired_keys_are_dropped_past_the_cap`, with the spec's values (20 s left at t=1000, 1 at t=1019.5, only "c" kept with `MAX_KEYS` patched to 1).
- tests/integration/test_api_reports.py: `test_public_routes_are_rate_limited_per_token`, with `TokenLimiter(2, 60, lambda: 1_000.0)` imported inside the function (R5): two tokens, page 200, PDF 200, then page 429 with the problem shape, `Retry-After` "20" and the matching `X-Request-Id`; the other token's page is 200.
- apps/web/src/app/r/[token]/pdf/route.test.ts: "API 429 passes through with its Retry-After" (`retry-after: 17`).

Results, as the Task 1 report records them:
- Step 2 (red, on the unchanged code): tests/unit/test_ratelimit.py stopped at collection with "ImportError: cannot import name 'ratelimit' from 'bsi_api'" (`1 error in 0.06s`); tests/integration/test_api_reports.py gave `1 failed, 13 passed, 2 warnings in 4.77s` (test_public_routes_are_rate_limited_per_token, `E       ModuleNotFoundError: No module named 'bsi_api.ratelimit'`).
- Step 4 (green, the two files): `17 passed, 2 warnings in 5.25s`; the malformed-token check printed `422 1`.
- Step 5 (backend gate, from `gate-task1.txt`; the exit code is the `gate exit 0` the step printed): ruff format "171 files left unchanged"; ruff check "All checks passed!"; ruff format --check "171 files already formatted"; mypy "Success: no issues found in 29 source files"; pytest "1558 passed, 2 deselected, 2 warnings in 169.45s (0:02:49)" (the 2 known third-party warnings: fastapi/testclient.py `StarletteDeprecationWarning` and the starlette/testclient.py anyio `BlockingPortal` `DeprecationWarning`); `bsi_core.metrics` coverage 100% ("Required test coverage of 100% reached. Total coverage: 100.00%"). The banned-word grep over the staged diff had no match.

Results, as the Task 2 report records them:
- Step 2 (red, on the current route): `Tests  1 failed | 5 passed (6)`, "AssertionError: expected 502 to be 429 // Object.is equality".
- Step 4 (green): `Tests  6 passed (6)`.
- Step 5 (web gate, from `gate-task2.txt`; the step printed `web gate exit 0`): typecheck and lint passed with no output; vitest `Test Files  6 passed (6)`, `Tests  43 passed (43)`; `next build` compiled and generated 6/6 static pages; gen:check clean (no schema change). The banned-word grep over the diff had no match.

**Commits** (`git log --oneline --reverse main..HEAD`, oldest first):

| Commit | Subject |
|---|---|
| 94661f3 | docs: slice 31 spec, per-token rate limit on the public routes |
| d47247a | docs: slice 31 spec review fixes (R1-R3) |
| 3d09a15 | docs: slice 31 spec, scope the lint and type claims |
| 4a7d63c | docs: slice 31 spec, mypy sentence (R4) |
| 10ac562 | docs: slice 31 plan |
| 2a036b8 | docs: slice 31 plan review fixes (R5, R6) |
| 5cf4e6c | docs: slice 31 plan re-review fixes (R7) |
| 56d2c38 | feat(api): per-token rate limit on the public routes |
| 4214137 | feat(web): the PDF proxy passes a 429 through with Retry-After |
| (this commit) | docs: slice 31 findings, index and notes |

## 2. Live check on dev

Not yet run. The controller runs it after merge with the user's approval (spec §2: a free, read-only check against a shared run on dev); results are recorded here then.

## 3. Deferred and untested

From the task reviews (ledger lines tagged `minor (deferred)`):
- "Task 1: minor (deferred): ratelimit.py:34-37 (plan-mandated): once more than MAX_KEYS keys are live in one window, eviction drops nothing and every later check rebuilds the dict under the lock (O(n) per request, bounded by one window); upgrade path: evict only when the window index changes, or note the cost in the ponytail comment"
- "Task 1: minor (deferred): tests/unit/test_ratelimit.py:39 asserts on the private `limiter._seen` (brief-mandated white-box eviction test)"
- "Task 1: minor (deferred): the reported test output carries the 2 known third-party warnings (fastapi testclient StarletteDeprecationWarning; starlette testclient anyio BlockingPortal DeprecationWarning), pre-existing"
- "Task 2: minor (deferred): route.ts 429 branch: no test covers an upstream 429 without a retry-after header (the `if (retry)` false path); the API always sends it; the brief asks for one case"
- "Task 2: minor (deferred): the upstream body is not cancelled on the 429 path, consistent with the existing 404 and 502 paths"

Parked: none. The ledger has no parked lines.

Rulings (spec `## Rulings`, quoted in full):
- **R1: the limiter check is called at the top of each route body, not as a dependency.** Decided: `_limit(token, request)` as the first line of both routes, which gain `request: Request`; the user chose this over keeping the dependency with a doubled 422 `errors` list, or a dependency reading `request.path_params`. Found by the spec review of 94661f3 (a dependency with its own `token: Token` makes FastAPI report a malformed token's pattern error twice). Why: the public routes' 422 must stay as today, and the route body only runs for a valid token. Cost if wrong: two routes carry one extra parameter and call. Asked in chat.
- **R2: the clock is `time.monotonic` and a key resets on a different window index.** Decided: default `clock=time.monotonic` and the `!=` comparison; the user chose this over `time.time` with `!=`, or leaving the wall clock and the "earlier window" rule. Found by the spec review of 94661f3 (a backward wall-clock step could leave a key blocked past its window). Why: matches rivals.py's injectable clock and cannot step. Cost if wrong: windows are not aligned to wall-clock minutes, which nothing needs. Asked in chat.
- **R3: the spec review's six minor points were applied.** Decided: `publicApi`'s 404/422 path named; the existing test's request count corrected to 9 (at most 6 on one token); the integration test's in-function import and the test counts spelled out; `_seen`, the call-time read of `MAX_KEYS` and its soft-cap nature stated; `max(1, …)` dropped since `ceil` of a positive remainder is already at least 1, and the t=1019.5 example described as rounding up; "other two items"; the live check worded for a window boundary. Found by the spec review of 94661f3. Why: accuracy and completeness for the plan writer; no design change beyond R1 and R2. Cost if wrong: none. Named in chat when made.
- **R4: the mypy sentence says the gate type-checks none of apps/api.** Decided: reword the sentence so the two by-path mypy results are not read as gate coverage. Found by the re-review of 3d09a15. Why: accuracy. Cost if wrong: none. Named in chat when made.
- **R5: the integration test uses a fixed clock and asserts `Retry-After` is exactly 20.** Decided: `TokenLimiter(2, 60, lambda: 1_000.0)` in `test_public_routes_are_rate_limited_per_token`, replacing the live clock and the 1–60 range; the user chose this over a 3600-second window with the live clock, or leaving the spec's text. Found by the plan review of 10ac562: with the live monotonic clock, a 60-second window boundary can pass between the first and third request (about 0.1–0.3% of runs), resetting the count and returning 200. Why: a deterministic test in the shared suite and CI. Cost if wrong: the integration test no longer exercises the real clock, which the unit tests do not either (they use a fake clock); the live check does. Asked in chat.
- **R6: the plan review's other four points were applied.** Decided: the unit file's red step expects `ImportError: cannot import name 'ratelimit' from 'bsi_api'`; all three tasks grep added lines (staged for Task 1, since two files are new; the new findings file directly), and Task 3 names the two pre-existing matches in findings-slice15; the self-review lists each task's own gate run and the red-step wording as departures. Found by the plan review of 10ac562. Why: accuracy of the expected results and of the checks. Cost if wrong: none. Named in chat when made.
- **R7: the plan re-review's three points were applied.** Decided: the banned-word grep is defined once in the plan's Global Constraints and the three task steps refer to it (the R6 edit had written the words into three step lines); the sentence about the existing test's request count is back on its parent bullet, out of the R5 note; Task 1 Step 5 spells out the six paths. Found by the plan re-review of 2a036b8. Why: the three points were regressions from the R6 commit. Cost if wrong: none. Named in chat when made.
- **R8: commit 5cf4e6c goes into execution unreviewed.** (Title: writer's own wording.) Decided: commit 5cf4e6c (the plan's R7 fixes) goes into execution unreviewed. Found by the controller, offering a stop after two plan review rounds; the user chose "disclose and proceed". Why: the commit changes no code block, only three grep step lines, a Global Constraints line, a path list, and the spec's moved sentence and R7 entry. Cost if wrong: an unreviewed wording commit in the plan. Asked in chat.
  - The ledger line, as recorded: "Ruling: R8 — Decided: commit 5cf4e6c (the plan's R7 fixes) goes into execution unreviewed. Found by: the controller, offering a stop after two plan review rounds; the user chose "disclose and proceed". Why: the commit changes no code block, only three grep step lines, a Global Constraints line, a path list, and the spec's moved sentence and R7 entry. Cost if wrong: an unreviewed wording commit in the plan. Asked in chat."
- **R9: every slice 31 commit carries the session's trailer.** (Title: writer's own wording.) Decided: every slice 31 commit carries the session's trailer, "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>", including commits written by Opus 5.5 subagents. Found by the Task 2 implementer's concern. Why: the plan's Global Constraint binds the trailer to the latest session reminder, and the session runs on Fable 5.1. Cost if wrong: a trailer naming the orchestrating model rather than the writing one. Named in chat when made.
  - The ledger line, as recorded: "Ruling: R9 — Decided: every slice 31 commit carries the session's trailer, "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>", including commits written by Opus 5.5 subagents. Found by: the Task 2 implementer's concern. Why: the plan's Global Constraint binds the trailer to the latest session reminder, and the session runs on Fable 5.1. Cost if wrong: a trailer naming the orchestrating model rather than the writing one. Named in chat when made."

Out of scope (spec):
- The other two items (webhook signing, "-es" folding): later slices.
- Per-IP limits (needs the reader's IP forwarded by Next, or an edge limiter), limits on the keyed routes, `X-RateLimit-*` headers, declaring the 429 in OpenAPI, caching rendered PDFs, and shared limiter state across processes (Redis).
- A dedicated 429 message on the share page.

Carried forward from docs/findings-slice30.md §3 ("Carried forward from docs/findings-slice29.md §3"), still open:
- The judge-agreement question, waiting on the user.

Untested: the limiter under concurrent requests (the lock is read in review, not exercised by a test); an unknown token's budget (it counts under its own key, pinned by no test).
