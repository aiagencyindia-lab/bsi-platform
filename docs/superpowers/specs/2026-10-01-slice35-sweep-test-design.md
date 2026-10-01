# Slice 35 design: a unit test for the rate limiter's once-per-window sweep

## Context

Codebase facts: main `14254db`, checked 2026-10-01.

docs/findings-slice31.md records the gap three times: the parked ledger line at line 89 ("Fix wave: parked — no unit test pins R10 (sweep at most once per window): reverting to a sweep on every check passes all 3 unit tests …"), its copy inside R13 at line 119, and the note at line 132: "Note (2026-10-01, after merge, R13): also untested: the once-per-window sweep (R10); reverting to a sweep on every check would pass all three unit tests." docs/findings-slice32.md:97 and docs/findings-slice33.md:82 carry it forward: "The once-per-window sweep (slice 31 R10) has no unit test." The user asked for "a unit test for the rate limiter sweep".

Facts read before the approaches:
- `TokenLimiter.check` (apps/api/bsi_api/ratelimit.py:28-48). Lines 34-40: `if len(self._seen) > MAX_KEYS and self._swept != index:` rebuilds `self._seen` as a new dict holding only the current window's entries, then sets `self._swept = index`. `_swept` starts at -1. `MAX_KEYS` is read from the module at call time.
- tests/unit/test_ratelimit.py (39 lines, 3 tests) has a `Clock` class with a settable `at`, and `test_expired_keys_are_dropped_past_the_cap`, which patches `ratelimit.MAX_KEYS` to 1 with `monkeypatch` and asserts on the private `limiter._seen`.
- Checked in memory on 2026-10-01 against the real module and a mutant with `and self._swept != index` removed (a sweep on every check past the cap): the three existing tests pass on both; the first version of the identity shape (the same test as below, but with the check of "d" at t=1000 and no first-sweep assertion) gives `(True, True, ['e'])` on the real code and `(False, True, ['e'])` on the mutant, the three values being the same-window identity, the next-window non-identity and the final keys; a backward-clock shape (checks of "a" and "b" at t=1000, "c" at t=1060, "x" and "y" at t=1000 again, then "d" at t=1060) ends with `['d']` on both, because moving the clock back changes the window index and the real limiter sweeps again; asserting `_swept` after three checks at t=1000 gives 16 on both.

Classification: **bounded** — one test added to an existing file, no production change; the flow under test (`TokenLimiter.check`'s once-per-window sweep) already exists to read. The user's process rule asks for a spec even for small changes, so this file exists.

Process note (2026-10-01): the controller's first brainstorming reply was only a question, with no classification line, no session model and no approaches in chat, and it then asked for approval of a design it had not shown; the user's two answers were therefore given blind. The controller said so in its next message, gave the classification, the session model (Fable 5.1, planning only; subagents on Opus 5.5 with `model: "opus"`), the approaches with the facts above, and the design text, and re-asked both questions. One option in the first question was also described wrongly (the backward-clock shape was said to detect the regression; the in-memory run shows it does not).

Decision approved in chat (re-asked, brainstorming on Fable 5.1, 2026-10-01), after three approaches with trade-offs, the facts above and a recommendation in a chat message: the identity check (over the backward-clock shape, shown not to distinguish the mutant; and asserting `_swept`, which passes on the mutant). The design text was in chat before its approval question; the user approved it. After the spec review of 622a081 the test was strengthened by the user's choice (R1): the clock moves inside the window before the same-window check, and the first sweep is asserted.

## Design

- tests/unit/test_ratelimit.py, appended after `test_expired_keys_are_dropped_past_the_cap`:

```python
def test_the_sweep_runs_once_per_window(monkeypatch):
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 1)
    clock = Clock(1_000.0)
    limiter = TokenLimiter(1, 60, clock)
    assert limiter.check("a") is None
    assert limiter.check("b") is None
    # Two keys are past the cap, so the next check sweeps: a new dict.
    before = limiter._seen
    assert limiter.check("c") is None
    assert limiter._seen is not before
    # Later in the same window a check must not rebuild the dict again.
    seen = limiter._seen
    clock.at = 1_010.0
    assert limiter.check("d") is None
    assert limiter._seen is seen
    # The next window sweeps once more and keeps only its own keys.
    clock.at = 1_060.0
    assert limiter.check("e") is None
    assert limiter._seen is not seen
    assert list(limiter._seen) == ["e"]
```

- How it reads: at t=1000 (window index 16, the window [960, 1020)) the checks of "a" and "b" leave two keys, more than `MAX_KEYS` (1), so the check of "c" sweeps: `_seen` becomes a new dict (both keys are in window 16 and stay) and `_swept` becomes 16; the test asserts the dict changed. At t=1010, still window 16, the check of "d" must leave the dict the same object. At t=1060 (index 17) the check of "e" sweeps again: a new dict, holding only "e".
- No production change.
- Proof, checked on 2026-10-01 with pytest on scratch copies outside the repo (a copy of apps/api/bsi_api with line 34 changed to `if len(self._seen) > MAX_KEYS:`; the test above in a separate folder with its own `Clock`): on main's code `1 passed in 0.01s`; on the mutant `1 failed in 0.03s` at `assert limiter._seen is seen` (`AssertionError: assert {'a': (16, 1), 'b': (16, 1), 'c': (16, 1), 'd': (16, 1)} is {'a': (16, 1), 'b': (16, 1), 'c': (16, 1)}`); the existing tests/unit/test_ratelimit.py gives `3 passed` on the mutant and `3 passed` on main, so before this test nothing pinned the rule. The mutant run imported the scratch copy (`bsi_api.ratelimit.__file__` printed the scratch path). ruff check and ruff format --check are clean on the test, and no line is over 80 characters.
- Other variants, run in memory on 2026-10-01 against this test (the module source exec'd with one change each; no pytest): a sweep keyed on the clock time instead of the window index fails at the same-window assertion (it passed the first version of this test, where all same-window checks ran at t=1000); `_swept` assigned before the rebuild condition (the first sweep skipped) fails at the first-sweep assertion; `_swept` never assigned fails at the same-window assertion; a limiter that never sweeps fails at the first-sweep assertion; a limiter that sweeps once ever fails at the next-window assertion. The real code passes.
- Counts: tests/unit/test_ratelimit.py 3 → 4; backend 1571 → 1572.
- Known limit: the test compares object identity on the private `_seen`, so it relies on the sweep rebuilding the dict. A sweep rewritten to delete keys in place would need this test rewritten with it. Asserting on `_seen` follows the existing eviction test (a deferred minor in docs/findings-slice31.md §3).
- Copy: the new comment and test name are checked against `FORBIDDEN` in tests/unit/test_recommend_copy.py by a grep of the diff.

## Process and docs

- Branch `slice35-sweep-test`; spec reviewer (Opus 5.5); plan by writing-plans (one task); one implementer and its task review; final whole-branch review; PR; merge on the user's go-ahead.
- Post-merge docs: dated notes (originals kept) under docs/findings-slice31.md lines 89 and 132 (the parked line and the "also untested" note), and under the carried-forward lines docs/findings-slice32.md:97 and docs/findings-slice33.md:82, each pointing here; the copy of the parked line inside R13 (line 119) is a quoted ruling and gets no note. The "Untested" line itself (line 131: the limiter under concurrent requests; an unknown token's budget) gets no note, since both of its items stay untested; the note under line 132 covers only the sweep. Two README rows, a spec row then a plan row, directly after the slice 34 plan row. No findings file of its own: this spec and the PR description carry the results.
- No live check: a test-only change touches no running system.
- Commits carry the trailer the latest attribution reminder names (Fable 5.1 when this spec was written; the plan's task brief names the one current at execution).
- The backend baseline (1571 passed, 2 deselected; collected on main `14254db`) is re-collected by the plan before it states its expected totals.

## Rulings

- **R1: the test moves the clock inside the window and asserts the first sweep.** Decided: `clock.at = 1_010.0` before the check of "d", and `_seen` captured after "b" with `assert limiter._seen is not before` after "c"; the user chose both changes over the mid-window clock alone, or leaving the test as first approved. Found by the spec review of 622a081 (all four same-window checks ran at t=1000, so a sweep keyed on the clock time instead of the window index passed; nothing asserted that the check of "c" swept, so a variant that skips the first sweep passed). Why: the in-memory table showed the version with both changes is the only one that fails on every variant tried. Cost if wrong: five more lines (four of code, one comment), and the first-sweep assertion pins the cap rule as well as the once-per-window rule. Asked in chat.
- **R2: the spec review's other points were applied.** Decided: the backward-clock shape and the point at which `_swept` was read are stated exactly in Context; the proof paragraph describes the strengthened test and lists the other variants as in-memory runs; the docs plan says the "Untested" line (131) gets no note and its two items stay untested; the trailer line names the reminder current when the spec was written; the plan re-collects the backend baseline. Found by the spec review of 622a081. Why: accuracy for the plan writer. Cost if wrong: none. Named in chat when made.
- **R3: the re-review's two minors were applied.** Decided: R1's cost line says five more lines (it had said three, written without counting); Context says the `(True, True, ['e'])` tuple came from the first version of the shape and names its three values. Found by the re-review of 38a1c93. Why: accuracy. Cost if wrong: none. Named in chat when made.
- **R4: the plan review's two minors were applied to the plan.** Decided: the commit message says "With two keys past the cap, the next check sweeps into a new dict" (it had said "The third check past the cap", but the check of "c" is the first past the cap); Step 3 checks with `grep -c` that the `_swept` guard is gone from the scratch copy and still present in the repo's file before the mutant run. Found by the plan review of 66f6558. Why: no inaccurate sentence in history, and a stale scratch copy shows itself before the run. Cost if wrong: none. Named in chat when made.
- **R5: the plan's commit message is reflowed.** Decided: the body's second sentence is reflowed, so the body's four lines are 68, 70, 66 and 44 characters (the R4 rewording had left a 15-character line, "again. With the"); the wording is unchanged; the user chose a third plan review round over disclosing the point and proceeding. Found by the plan re-review of 9ce6ead. Why: a cleaner message in history. Cost if wrong: none. Asked in chat.
- **R6: R5's wording is exact.** Decided: R5 says that the body's second sentence was reflowed and gives the four line lengths (it had said "the message's last two sentences wrap as four even lines", but the body has two sentences, only the second was rewrapped, and the fourth line is 44 characters); the user chose a fourth plan review round over disclosing the point and proceeding. Found by the plan re-review of 1d08e6a. Why: a ruling states exactly what was done. Cost if wrong: none. Asked in chat.
- **R7: commits from execution on carry the Opus 5.5 trailer.** (Title: writer's own wording.) The ledger line, as recorded: "Ruling: R7 — Decided: commits from execution on carry "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; the slice 35 spec and plan commits (622a081, 38a1c93, 64c7a18, 66f6558, 9ce6ead, 1d08e6a, 8ea1c7f) keep the Fable 5.1 trailer. Found by: the controller, on a new attribution reminder naming Opus 5.5 after the execution choice. Why: the plan binds the trailer to the latest session reminder. Cost if wrong: mixed trailers within one branch. How named: named in chat when made."
- **R8: subagent dispatches pass `model: "opus"`.** (Title: writer's own wording.) The ledger line, as recorded: "Ruling: R8 — Decided: subagent dispatches pass `model: "opus"`. Found by: the controller, when the latest model notice still said Fable 5.1. Why: memory rule "pass model opus when the session is on another model". Cost if wrong: none; the session then moved to Opus 5.5, where passing "opus" gives the same model as omitting it. How named: named in chat when made."

## Out of scope

- The limiter under concurrent requests, and an unknown token's budget (both listed as untested in docs/findings-slice31.md §3); any change to `TokenLimiter`.
