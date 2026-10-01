# Slice 31 design: a per-token rate limit on the public share-link routes

## Context

Codebase facts: main `7c5b227`, checked 2026-10-01.

The second of the four smaller items the user ordered on 2026-10-01 (labels, rate limits, webhook signing, "-es" folding). docs/findings-slice15.md §3 records the gap twice: "The public routes are not rate-limited; the tokens are 256-bit (`token_urlsafe(32)`). Cost: nothing stops a client hammering the PDF route, which renders on every request." and "No rate limiting on the public routes. Cost: a client can request the PDF route without limit, and each request renders a PDF."

Facts read before the approaches (an Explore agent on Opus 5.5, then direct reads of the files named):
- The public routes are `GET /v1/r/{token}` and `GET /v1/r/{token}.pdf` in apps/api/bsi_api/routers/public.py. Both call `_run(token)`: a `system_session` lookup through `report_run_by_token()` and a `tenant_session` read of the run (two queries). The PDF route then calls `render_pdf`, a pure function with no cache; findings-slice15 §2 measured about 0.02–0.06 s per PDF. The token path pattern is `^[A-Za-z0-9_-]{20,64}$` (422 on mismatch). A miss raises `Problem(404, "Not found")`, which `problems._response` renders as `application/problem+json` with an `X-Request-Id` header; `_response` accepts no other headers.
- The API never sees a reader's IP: readers go browser → Next → API, and neither `publicApi` (apps/web/src/lib/api.ts) nor the PDF proxy (apps/web/src/app/r/[token]/pdf/route.ts) sends any header (the proxy's test asserts `init` has no `headers`). The proxy maps upstream 404/422 to a plain-text 404, any other non-OK status to a plain-text 502 "Report unavailable", and copies only `content-type` and `content-disposition`. `publicApi` throws on any non-OK status, which lands in apps/web/src/app/r/error.tsx ("This report could not be loaded. Please try again in a moment." with a Try again button).
- Nothing to build on: no limiter library, no Redis (`uv.lock` has none of limits, slowapi, fastapi-limiter, redis, cachetools), one uvicorn process (`uv run uvicorn bsi_api.main:app --port 8000`, no workers flag). `public_pdf` is a sync `def`, so it runs in the threadpool. The test client is a fresh `create_app()` per test (tests/conftest.py).
- Conventions: tunables are module constants patched with `monkeypatch.setattr`. The PRD asks for `429` with `Retry-After` (and `X-RateLimit-*` headers per API key) and per-IP limits at the edge (Cloud Armor) later.

Classification, said in chat as the first line of the first brainstorming reply: **architectural** — "rate limiting adds a new layer in front of the public routes, with nothing in the repo to build on (no limiter, no middleware beyond request IDs, no Redis), and the choice of where it lives (API or Next proxy) changes how the two tiers fit together. So: questions, approaches, a sectioned design, a spec, then a plan."

Decisions approved in chat (brainstorming on Fable 5.1, 2026-10-01, in plan mode; every subagent on Opus 5.5). Each decision had 2–3 approaches with trade-offs and a recommendation in a chat message before its question:
- Home and key: A, in the API, per share token (over B, per client IP with Next forwarding `X-Forwarded-For`; and C, a Next middleware on `/r`). The user chose A.
- Budget: 1, one shared budget of 60 requests per 60-second window per token, page and PDF together (over separate budgets, or PDF only). The user chose 1.
- What a reader sees: 1, the proxy passes the 429 through with `Retry-After` and the page keeps `error.tsx` (over a dedicated 429 message, or no web change). The user chose 1.
Each design section's text was in chat before its approval question; the user approved Section 1 and Section 2, and with Section 2 the local live check. The user then approved the plan-mode plan.

## Design

### 1. The limiter in the API

New module apps/api/bsi_api/ratelimit.py:

```python
MAX_KEYS = 10_000

class TokenLimiter:
    def __init__(self, limit: int, window: int, clock: Callable[[], float] = time.time) -> None
    def check(self, key: str) -> int | None
```

- Fixed window per key. State is `{key: (window_index, count)}` under a `threading.Lock`; `window_index = int(now // window)` with `now = clock()`. A key with no entry, or an entry from an earlier window, starts at count 1. Under the limit the count increments and `check` returns `None` (the call counts). At the limit it returns the whole seconds until the window ends, `max(1, ceil((index + 1) * window - now))`, and does not count the call.
- When the dict holds more than `MAX_KEYS` keys, entries from earlier windows are dropped before the check.
- Docstring: "At most `limit` checks per `window` seconds for each key, counted in this process. ponytail: per-process state, so N workers allow N times the limit; Redis or an edge limiter (PRD) if that matters."

In apps/api/bsi_api/routers/public.py:
- Constants `PUBLIC_LIMIT = 60` and `PUBLIC_WINDOW_SECONDS = 60` beside `NO_STORE`.
- A dependency `_limited(token: Token, request: Request) -> None` that calls `request.app.state.public_limiter.check(token)` and, on a wait, raises `Problem(429, "Too many requests", headers={"Retry-After": str(wait)})`.
- Both routes get `dependencies=[Depends(_limited)]`, so page and PDF share one budget per token. A malformed token fails path validation (422) before the dependency runs, so it is never counted. An unknown token counts under its own key and still costs only the 404 lookup.

In apps/api/bsi_api/main.py, `create_app()` sets `app.state.public_limiter = TokenLimiter(public.PUBLIC_LIMIT, public.PUBLIC_WINDOW_SECONDS)` right after `problems.install(app)`. The test fixture builds a fresh app per test, so no limiter state leaks between tests.

In apps/api/bsi_api/problems.py: `Problem.__init__` gains `headers: dict[str, str] | None = None` (stored as `self.headers`, `{}` when None); `_response` gains `headers: dict[str, str] | None = None` and merges them after `X-Request-Id` (`{"X-Request-Id": rid, **(headers or {})}`); the `Problem` handler passes `exc.headers`. So the 429 has the 404's shape (`title` "Too many requests", `status` 429, empty `detail` and `errors`, `request_id`) plus `Retry-After`.

Unchanged: the keyed routes, `/healthz`, `_run`, PDF rendering, the schemas, `openapi.json` and `schema.d.ts` (the 429 is not declared; out of scope), the other exception handlers.

### 2. The web side, tests, docs, live check

- apps/web/src/app/r/[token]/pdf/route.ts: before the generic `!upstream.ok` → 502 branch, `upstream.status === 429` returns `plain("Too many requests", 429)` with the upstream `retry-after` header copied when present (so `content-type: text/plain` and `cache-control: no-store` as the other plain responses). `publicApi` and `error.tsx` are unchanged: a 429 is `!res.ok`, throws, and the reader sees `error.tsx`.
- Tests:
  - New tests/unit/test_ratelimit.py with a fake clock: `TokenLimiter(2, 60)` at t=1000 allows "a" twice, then returns 20 (the window [960, 1020) has 20 s left), still allows "b", and allows "a" again at t=1020; `TokenLimiter(1, 60)` at t=1019.5 returns 1 on the second call (the wait is at least one second); with `ratelimit.MAX_KEYS` patched to 1, after "a" and "b" at t=1000 a check of "c" at t=1060 leaves only "c" in `_seen`.
  - New `test_public_routes_are_rate_limited_per_token` in tests/integration/test_api_reports.py: `_scene`, then `client.app.state.public_limiter = TokenLimiter(2, 60)`; two runs posted (agency, cmo) for two tokens; page 200, PDF 200, then page 429 with `title` "Too many requests", `status` 429, empty `detail` and `errors`, `Retry-After` between 1 and 60, `X-Request-Id` equal to the body's `request_id`, and no "nike" in the body; the other token's page is 200. The existing `test_public_page_and_pdf_follow_the_token` makes about 7 requests, under the default 60, and is unchanged.
  - apps/web/src/app/r/[token]/pdf/route.test.ts: one case, an upstream 429 with `retry-after: 17` becomes a 429 "Too many requests" with `retry-after: 17` and `cache-control: no-store`.
  - Red and green, checked on scratch copies outside the repo on 2026-10-01: on main's code the unit file fails at collection (`bsi_api.ratelimit` does not exist) and the new integration test fails with `ModuleNotFoundError` (`1 failed, 13 passed` for that file); with the change the two files give `17 passed`; ruff format and `mypy --strict` are clean on the changed modules (ruff check's only hits on the scratch copy are the repo's own `apps/api/**` B008 ignores, in untouched files). The proxy test gives `1 failed | 5 passed` ("expected 502 to be 429") against the current route and `6 passed` with the change.
  - Copy: the new strings, test names, fixtures and comments are checked against `FORBIDDEN` in tests/unit/test_recommend_copy.py by a grep of the diff.
- Docs: docs/findings-slice31.md; dated updates (originals kept) under both quoted lines in docs/findings-slice15.md §3; README rows for the spec, the plan and the findings.
- Live check (approved with Section 2): dev holds 5 shared `report_run` rows (checked read-only on 2026-10-01). After merge, start uvicorn against dev, request `/v1/r/{token}` 61 times with curl using one of those tokens, and expect the 61st to be a 429 with `Retry-After`; stop uvicorn. The requests use no API key (so `api_key.last_used_at` is not written) and the public route only reads. Writes: none. Spend: none. Recorded in findings §2.
- Gates: both, run by the controller before the finishing menu.

## Rulings

None.

## Out of scope

- The other three items (webhook signing, "-es" folding): later slices.
- Per-IP limits (needs the reader's IP forwarded by Next, or an edge limiter), limits on the keyed routes, `X-RateLimit-*` headers, declaring the 429 in OpenAPI, caching rendered PDFs, and shared limiter state across processes (Redis).
- A dedicated 429 message on the share page.
