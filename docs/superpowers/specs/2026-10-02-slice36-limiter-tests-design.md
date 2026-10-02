# Slice 36 design: tests for the rate limiter's lock and an unknown token's budget

## Context

Codebase facts: main `b63ebe6`, checked 2026-10-02.

docs/findings-slice31.md:132 records the gap: "Untested: the limiter under concurrent requests (the lock is read in review, not exercised by a test); an unknown token's budget (it counts under its own key, pinned by no test)." No other docs line carries it forward (grep of docs for "concurrent requests" and "unknown token's budget": that line, the slice 31 plan's template text, and the slice 35 spec's own references). The user chose "Rate-limiter tests" from the next-step list.

Facts read before the approaches:
- `TokenLimiter.check` (apps/api/bsi_api/ratelimit.py:28-48) reads the clock at line 31, outside the lock. Lines 33-48 run inside `with self._lock:`: the sweep, the read `self._seen.get(key, (index, 0))` (line 41), the limit check, and the write `self._seen[key] = (index, count + 1)` (line 47).
- apps/api/bsi_api/routers/public.py: both routes call `_limit(token, request)` as their first line, before `_run(token)` (lines 64-65 and 84-85), so a well-formed token with no run is counted under its own key before the lookup answers 404.
- tests/unit/test_ratelimit.py (61 lines, 4 tests) is single-threaded. It has a `Clock` class with a settable `at`, and two tests already assert on the private `limiter._seen`.
- tests/integration/test_api_reports.py (246 lines, 8 test functions, 14 collected) has `test_public_routes_are_rate_limited_per_token`, which uses only real share tokens with `TokenLimiter(2, 60, lambda: 1_000.0)` imported inside the function, and `_generic_404(r)`. The file's one unknown-token request (`/v1/r/unknown-token-unknown-token-x`, line 217) is a single 404 that reaches no limit.

Classification: **bounded** — two tests added to two existing files, no production change; the flows under test already exist to read. The user's process rule asks for a spec even for small changes, so this file exists.

Decisions approved in chat (brainstorming on Fable 5.1, 2026-10-02), each after approaches with trade-offs, the facts above and a recommendation in a chat message:
- The lock test forces the interleaving (over a thread hammer, which a lock-free mutant passes on most runs under the GIL, and over both).
- One slice with both tests (over two slices, and over the lock test alone).
- Design Sections 1 and 2; the text of each was in chat before its approval question.
- After the mutation run the lock test was revised by the user's choice (R2).

## Design

### Test 1: the lock

tests/unit/test_ratelimit.py gains `import threading` as its first line (followed by a blank line, before `from bsi_api import ratelimit`), and, appended after `test_the_sweep_runs_once_per_window`:

```python
class Parked(dict):
    """A _seen whose writes park, so a test can hold a check between its
    read and its write."""

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0
        self.writing = threading.Event()
        self.release = threading.Event()

    def get(self, key, default=None):
        self.reads += 1
        return super().get(key, default)

    def __setitem__(self, key, value) -> None:
        self.writing.set()
        self.release.wait(5)
        super().__setitem__(key, value)


def test_checks_on_one_key_do_not_interleave():
    limiter = TokenLimiter(1, 60, Clock(1_000.0))
    seen = limiter._seen = Parked()
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(limiter.check("a")))
        for _ in range(2)
    ]
    try:
        threads[0].start()
        assert seen.writing.wait(5)
        threads[1].start()
        threads[1].join(0.2)
        # The first check holds the lock from its read to its write, so
        # the second has not read yet.
        assert threads[1].is_alive() and seen.reads == 1
    finally:
        seen.release.set()
        for t in threads:
            t.join(5)
    assert sorted(results, key=str) == [20, None]
```

How it reads: the limit is 1 and the clock is fixed at t=1000 (the window [960, 1020), 20 s left). The first thread's check reads count 0 and parks inside `__setitem__`, still holding the lock. The second thread's check must wait on the lock, so after 0.2 s it is still alive and `get` has been called once. After the release the first check returns `None` and the second reads count 1 and returns 20. The `finally` sets the event so a failing run cannot hang; each wait is capped at 5 s.

### Test 2: an unknown token's budget

tests/integration/test_api_reports.py, appended after `test_public_routes_are_rate_limited_per_token`:

```python
def test_an_unknown_token_has_its_own_budget(
    client, owner, make_org, make_brand
):
    from bsi_api.ratelimit import TokenLimiter

    org, bid = _scene(owner, make_org, make_brand)
    client.app.state.public_limiter = TokenLimiter(2, 60, lambda: 1_000.0)
    tok = client.post(
        f"/v1/brands/{bid}/reports/agency/runs", headers=org.headers
    ).json()["share_token"]
    unknown = "unknown-token-unknown-token-x"
    _generic_404(client.get(f"/v1/r/{unknown}"))
    _generic_404(client.get(f"/v1/r/{unknown}.pdf"))
    # Counted before the lookup: the third request never reaches it.
    r = client.get(f"/v1/r/{unknown}")
    assert r.status_code == 429
    assert r.headers["retry-after"] == "20"
    # A real token is not charged for the unknown one.
    assert client.get(f"/v1/r/{tok}").status_code == 200
```

How it reads: the same setup as the existing rate-limit test (a limit of 2, a fixed clock). The unknown token's page and PDF each get the generic 404 and each count; the third request gets 429 with `Retry-After: 20`; a real token's page still returns 200.

### No production change

No file under apps/ or packages/ changes. No frontend, schema or migration change.

### Proof: the mutation run

Run on 2026-10-02 with pytest on scratch copies of apps/api/bsi_api outside the repo, one change each; the two test files (the repo's files plus the new tests) in a separate scratch folder; `PYTHONPATH=<copy>:.` with `-p no:cacheprovider -p tests.conftest --rootdir .`. Before each run `bsi_api.ratelimit.__file__` (and for M3, M5, M6 `bsi_api.routers.public.__file__`) printed the scratch path.

| Copy | Change | Lock test (above) | Unknown-token test | Older tests in the two files |
|---|---|---|---|---|
| base | none | passed, 20 of 20 runs | passed | passed |
| M1 | `with self._lock:` replaced by `if True:` | failed, 20 of 20 | not run with this lock test | passed |
| M2 | the lock held only around the write at line 47 | failed, 20 of 20 | not run with this lock test | passed |
| M4 | the lock held around the sweep and the read only; the limit check and the write outside it | failed, 20 of 20 | not run | passed |
| M3 | `_limit` after `_run` in both routes | not run with this lock test | failed | passed |
| M5 | `_limit` after `_run` in the PDF route only | not run | failed | passed |
| M6 | `_limit` after `_run` in the page route only | not run | failed | passed |

- Every lock-test failure reads `assert (True and 2 == 1)`: the second thread was alive and had already read. Each of the 20 runs per copy ran tests/unit/test_ratelimit.py's five tests: `5 passed` on base, `1 failed, 4 passed` on M1, M2 and M4.
- Every unknown-token failure reads `assert 404 == 429`. M3 ran both files (`1 failed, 19 passed`, with the first version of the lock test, below); M5 and M6 ran the integration file (`1 failed, 14 passed` each). On base both files gave `20 passed` (with the first version of the lock test).
- The first version of the lock test, approved in chat as Section 1, parked the first thread inside `get` and counted `get` calls. It failed on M1 and M2 (`assert (True and 2 == 1)`) but passed on M4 in 20 of 20 runs: with the lock released after the read, the first thread writes before the second runs. The version above replaced it (R2).
- M4, M5 and M6 were added to the table approved in chat (R3).
- ruff check and ruff format --check are clean on both scratch test files.

### Counts

tests/unit/test_ratelimit.py 4 → 5 tests; tests/integration/test_api_reports.py 14 → 15 collected; backend 1572 → 1574. The plan re-collects the backend baseline before it states its expected totals.

### Known limits

- The lock test replaces the private `_seen` with a dict subclass and relies on `check` reading with `.get` and writing with item assignment. A `check` rewritten to read or write another way needs the test rewritten with it. Asserting on `_seen` follows the two existing tests.
- A passing run of the lock test waits 0.2 s (the second thread's join).
- The lock test shows that two checks on one key do not interleave between the read and the write. It does not put the limiter under load, and it does not test the sweep under concurrency.
- The unknown-token test uses a fixed clock, like the existing rate-limit test (slice 31 R5).

### Copy

The new comments, docstring and test names are checked against `FORBIDDEN` in tests/unit/test_recommend_copy.py by a grep of the diff.

## Process and docs

- Branch `slice36-limiter-tests`; spec reviewer (Opus 5.5); plan by writing-plans (one task, both tests, one commit); one implementer and its task review; final whole-branch review; at most one fix wave and one scoped re-review; PR; merge on the user's go-ahead.
- Post-merge docs: a dated note (original kept) under the "Untested" line, docs/findings-slice31.md:132, naming both tests and pointing here. Two README rows, a spec row then a plan row, directly after the slice 35 plan row. No findings file of its own: this spec and the PR description carry the results.
- No live check: a test-only change touches no running system. No model calls and no spend.
- Subagents are dispatched with `model: "opus"` while the session is on Fable 5.1.

## Rulings

- **R1: commits carry the Fable 5.1 trailer.** Decided: slice 36 commits end with "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>", the trailer the latest attribution reminder names; if a later reminder names another, a new ruling records the switch. Found by the controller, on the attribution reminder that came with the user's model switch. Why: the process binds the trailer to the latest session reminder. Cost if wrong: a trailer naming the orchestrating model on commits written by Opus 5.5 subagents. Named in chat when made.
- **R2: the lock test parks on the write and counts reads.** Decided: `Parked.__setitem__` parks and `Parked.get` counts, replacing the Section 1 version that parked inside `get`; the user chose this over keeping the approved test with M4 recorded as a gap. Found by the controller's mutation run (M4 passed the approved test in 20 of 20 runs). Why: M4 is the race the lock exists to prevent, and the revised test fails on M1, M2 and M4 in every run. Cost if wrong: the test depends on both the read and the write going through the dict's `get` and `__setitem__`. Asked in chat.
- **R3: the mutation table has three mutants more than the one approved.** Decided: M4 (lock around the read only), M5 and M6 (`_limit` moved in one route only) were added to the Section 2 table (M1, M2, M3 and the unchanged copy). Found by the controller, during the mutation run. Why: weak tests were caught by extra mutants in slices 34 and 35. Cost if wrong: none; more evidence, no design change beyond R2. Named in chat when made.

## Out of scope

- Any change to `TokenLimiter` or the public routes.
- The limiter under load from many threads or processes; the sweep under concurrency; shared limiter state across processes (slice 31's out-of-scope list).
- An unknown token on a real clock, and a live check.
