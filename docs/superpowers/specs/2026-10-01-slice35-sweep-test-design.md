# Slice 35 design: a unit test for the rate limiter's once-per-window sweep

## Context

Codebase facts: main `14254db`, checked 2026-10-01.

docs/findings-slice31.md records the gap three times: the parked ledger line at line 89 ("Fix wave: parked — no unit test pins R10 (sweep at most once per window): reverting to a sweep on every check passes all 3 unit tests …"), its copy inside R13 at line 119, and the note at line 132: "Note (2026-10-01, after merge, R13): also untested: the once-per-window sweep (R10); reverting to a sweep on every check would pass all three unit tests." docs/findings-slice32.md:97 and docs/findings-slice33.md:82 carry it forward: "The once-per-window sweep (slice 31 R10) has no unit test." The user asked for "a unit test for the rate limiter sweep".

Facts read before the approaches:
- `TokenLimiter.check` (apps/api/bsi_api/ratelimit.py:28-48). Lines 34-40: `if len(self._seen) > MAX_KEYS and self._swept != index:` rebuilds `self._seen` as a new dict holding only the current window's entries, then sets `self._swept = index`. `_swept` starts at -1. `MAX_KEYS` is read from the module at call time.
- tests/unit/test_ratelimit.py (39 lines, 3 tests) has a `Clock` class with a settable `at`, and `test_expired_keys_are_dropped_past_the_cap`, which patches `ratelimit.MAX_KEYS` to 1 with `monkeypatch` and asserts on the private `limiter._seen`.
- Checked in memory on 2026-10-01 against the real module and a mutant with `and self._swept != index` removed (a sweep on every check past the cap): the three existing tests pass on both; the identity shape below gives `(True, True, ['e'])` on the real code and `(False, True, ['e'])` on the mutant; a backward-clock shape (keys added in an earlier window after a sweep, then a check in the later window) ends with `['d']` on both, because moving the clock back changes the window index and the real limiter sweeps again; asserting `_swept` gives 16 on both.

Classification: **bounded** — one test added to an existing file, no production change; the flow under test (`TokenLimiter.check`'s once-per-window sweep) already exists to read. The user's process rule asks for a spec even for small changes, so this file exists.

Process note (2026-10-01): the controller's first brainstorming reply was only a question, with no classification line, no session model and no approaches in chat, and it then asked for approval of a design it had not shown; the user's two answers were therefore given blind. The controller said so in its next message, gave the classification, the session model (Fable 5.1, planning only; subagents on Opus 5.5 with `model: "opus"`), the approaches with the facts above, and the design text, and re-asked both questions. One option in the first question was also described wrongly (the backward-clock shape was said to detect the regression; the in-memory run shows it does not).

Decision approved in chat (re-asked, brainstorming on Fable 5.1, 2026-10-01), after three approaches with trade-offs, the facts above and a recommendation in a chat message: the identity check (over the backward-clock shape, shown not to distinguish the mutant; and asserting `_swept`, which passes on the mutant). The design text was in chat before its approval question; the user approved it.

## Design

- tests/unit/test_ratelimit.py, appended after `test_expired_keys_are_dropped_past_the_cap`:

```python
def test_the_sweep_runs_once_per_window(monkeypatch):
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 1)
    clock = Clock(1_000.0)
    limiter = TokenLimiter(1, 60, clock)
    for key in "abc":
        assert limiter.check(key) is None
    # The third check swept (two keys were past the cap). A fourth in the
    # same window must not rebuild the dict again.
    seen = limiter._seen
    assert limiter.check("d") is None
    assert limiter._seen is seen
    clock.at = 1_060.0
    assert limiter.check("e") is None
    assert limiter._seen is not seen
    assert list(limiter._seen) == ["e"]
```

- How it reads: at t=1000 (window index 16) the checks of "a" and "b" leave two keys, more than `MAX_KEYS` (1), so the check of "c" sweeps (both keys are in window 16 and stay) and `_swept` becomes 16. The check of "d" is in the same window, so the dict must be the same object. At t=1060 (index 17) the check of "e" sweeps again: a new dict, holding only "e". The last two assertions also fail for a limiter that never sweeps, so the identity assertion cannot pass trivially.
- No production change.
- Proof, checked on 2026-10-01 with pytest on scratch copies outside the repo (a copy of apps/api/bsi_api with line 34 changed to `if len(self._seen) > MAX_KEYS:`; the test in a separate folder with its own `Clock`): on main's code `1 passed in 0.03s`; on the mutant `1 failed in 0.03s`, the failing assertion `limiter._seen is seen` (`AssertionError: assert {'a': (16, 1), 'b': (16, 1), 'c': (16, 1), 'd': (16, 1)} is {'a': (16, 1), 'b': (16, 1), 'c': (16, 1)}`); the existing tests/unit/test_ratelimit.py gives `3 passed` on the mutant and `3 passed` on main, so before this test nothing pinned the rule. The mutant run imported the scratch copy (`bsi_api.ratelimit.__file__` printed the scratch path). ruff check and ruff format --check are clean on the test.
- Counts: tests/unit/test_ratelimit.py 3 → 4; backend 1571 → 1572.
- Known limit: the test compares object identity on the private `_seen`, so it relies on the sweep rebuilding the dict. A sweep rewritten to delete keys in place would need this test rewritten with it. Asserting on `_seen` follows the existing eviction test (a deferred minor in docs/findings-slice31.md §3).
- Copy: the new comment and test name are checked against `FORBIDDEN` in tests/unit/test_recommend_copy.py by a grep of the diff.

## Process and docs

- Branch `slice35-sweep-test`; spec reviewer (Opus 5.5); plan by writing-plans (one task); one implementer and its task review; final whole-branch review; PR; merge on the user's go-ahead.
- Post-merge docs: dated notes (originals kept) under docs/findings-slice31.md lines 89 and 132 (the parked line and the "also untested" note), and under the carried-forward lines docs/findings-slice32.md:97 and docs/findings-slice33.md:82, each pointing here; the copy of the parked line inside R13 (line 119) is a quoted ruling and gets no note. Two README rows, a spec row then a plan row, directly after the slice 34 plan row. No findings file of its own: this spec and the PR description carry the results.
- No live check: a test-only change touches no running system.
- Commits carry the trailer the latest attribution reminder names.

## Rulings

None yet.

## Out of scope

- The limiter under concurrent requests, and an unknown token's budget (both listed as untested in docs/findings-slice31.md §3); any change to `TokenLimiter`.
