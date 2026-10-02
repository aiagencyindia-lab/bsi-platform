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
- After the mutation run the lock test was revised by the user's choice (R2), and after the spec review of ff6f76b its `finally` block was changed by the user's choice (R5).

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
            if t.ident is not None:
                t.join(5)
    assert sorted(results, key=str) == [20, None]
```

How it reads: the limit is 1 and the clock is fixed at t=1000 (the window [960, 1020), 20 s left). The first thread's check reads count 0 and parks inside `__setitem__`, still holding the lock. The second thread's check must wait on the lock, so after 0.2 s it is still alive and `get` has been called once. After the release the first check returns `None` and the second reads count 1 and returns 20. The `finally` sets the event so a failing run cannot hang; each wait is capped at 5 s. It joins only threads that were started (`t.ident is not None`), so a failure of the first assertion, before the second thread starts, shows that assertion and not a `RuntimeError` from joining an unstarted thread (R5).

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

Run on 2026-10-02 with pytest on scratch copies of apps/api/bsi_api outside the repo, one change each; the two test files (the repo's files plus the two tests above) in a separate scratch folder; `PYTHONPATH=<copy>:.` with `-p no:cacheprovider -p tests.conftest --rootdir .`. Before each run `bsi_api.ratelimit.__file__` and `bsi_api.routers.public.__file__` printed the scratch copy's paths.

Each copy was run once against both test files together (20 tests: 5 in the unit file, 15 in the integration file):

| Copy | Change | Result | The failing test |
|---|---|---|---|
| base | none | `20 passed` | none |
| M1 | `with self._lock:` replaced by `if True:` | `1 failed, 19 passed` | the lock test, `assert (True and 2 == 1)` |
| M2 | the lock held only around the write at line 47 | `1 failed, 19 passed` | the lock test, `assert (True and 2 == 1)` |
| M3 | `_limit` after `_run` in both routes | `1 failed, 19 passed` | the unknown-token test, `assert 404 == 429` |
| M4 | the lock held around the sweep and the read only; the limit check and the write outside it | `1 failed, 19 passed` | the lock test, `assert (True and 2 == 1)` |
| M5 | `_limit` after `_run` in the PDF route only | `1 failed, 19 passed` | the unknown-token test, `assert 404 == 429` |
| M6 | `_limit` after `_run` in the page route only | `1 failed, 19 passed` | the unknown-token test, `assert 404 == 429` |

- So on every mutant the 18 older tests and the other new test passed, and before this slice nothing in the two files pinned the lock or the placement of `_limit`.
- `assert (True and 2 == 1)`: the second thread was alive and had already read.
- Repeat runs of the unit file alone (5 tests), 20 per copy: base `5 passed` in 20 of 20; M1, M2 and M4 `1 failed, 4 passed` in 20 of 20, the lock test each time.
- The first version of the lock test, approved in chat as Section 1, parked the first thread inside `get` and counted `get` calls. It failed on M1 and M2 (`assert (True and 2 == 1)`) but passed on M4 in 20 of 20 runs: with the lock released after the read, the first thread writes before the second runs. The version above replaced it (R2).
- M4, M5 and M6 were added to the table approved in chat (R3).
- The failure path behind R5, run once, on the unit file alone, on a seventh mutant (M7, the eighth copy) whose write is `self._seen.update({key: (index, count + 1)})` (which does not go through `__setitem__`): the lock test fails with `AssertionError: assert False` at `seen.writing.wait(5)`, after the 5 s wait, and no `RuntimeError`.
- ruff check and ruff format --check are clean on both scratch test files.

### Counts

tests/unit/test_ratelimit.py 4 → 5 tests; tests/integration/test_api_reports.py 14 → 15 collected; backend 1572 → 1574. The plan re-collects the backend baseline before it states its expected totals.

### Known limits

- The lock test replaces the private `_seen` with a dict subclass and relies on `check` reading with `.get` and writing with item assignment. A `check` rewritten to read or write another way needs the test rewritten with it. Asserting on `_seen` follows the two existing tests.
- A passing run of the lock test waits 0.2 s (the second thread's join).
- On a mutant, the lock test fails only if the second thread reaches its read within that 0.2 s. On a heavily loaded machine it might not, and the mutant would pass that run. The unchanged code cannot fail this way: its second thread is blocked on the lock, so it is alive and `reads` is 1.
- A correct limiter that reads `_seen` with `get` once more outside the lock (a lock-free fast path) makes `reads` 2 and fails the lock test.
- The lock test shows that two checks on one key do not interleave between the read and the write. It does not put the limiter under load, and it does not test the sweep under concurrency.
- The unknown-token test uses a fixed clock, like the existing rate-limit test (slice 31 R5).

### Copy

The new comments, docstring and test names are checked against `FORBIDDEN` in tests/unit/test_recommend_copy.py by a grep of the diff.

## Process and docs

- Branch `slice36-limiter-tests`; spec reviewer (Opus 5.5); plan by writing-plans (one task, both tests, one commit); one implementer and its task review; final whole-branch review; at most one fix wave and one scoped re-review; PR; merge on the user's go-ahead.
- Post-merge docs: a dated note (original kept) for the "Untested" line, docs/findings-slice31.md:132, naming both tests and pointing here; it goes directly after line 134 (the slice 35 note nested under line 133's note), as a bullet at line 133's indent. Two rows in docs/README.md, a spec row then a plan row, directly after line 224 (the slice 35 plan row). No findings file of its own: this spec and the PR description carry the results.
- No live check: a test-only change touches no running system. No model calls and no spend.
- Subagents are dispatched with `model: "opus"` while the session is on Fable 5.1.

## Rulings

- **R1: commits carry the Fable 5.1 trailer.** Decided: slice 36 commits end with "Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>", the trailer the latest attribution reminder names; if a later reminder names another, a new ruling records the switch. Found by the controller, on the attribution reminder that came with the user's model switch. Why: the process binds the trailer to the latest session reminder. Cost if wrong: a trailer naming the orchestrating model on commits written by Opus 5.5 subagents. Named in chat when made.
- **R2: the lock test parks on the write and counts reads.** Decided: `Parked.__setitem__` parks and `Parked.get` counts, replacing the Section 1 version that parked inside `get`; the user chose this over keeping the approved test with M4 recorded as a gap. Found by the controller's mutation run (M4 passed the approved test in 20 of 20 runs). Why: M4 is the race the lock exists to prevent, and the revised test fails on M1, M2 and M4 in every run. Cost if wrong: the test depends on both the read and the write going through the dict's `get` and `__setitem__`. Asked in chat.
- **R3: the mutation table has three mutants more than the one approved.** Decided: M4 (lock around the read only), M5 and M6 (`_limit` moved in one route only) were added to the Section 2 table (M1, M2, M3 and the unchanged copy). Found by the controller, during the mutation run. Why: weak tests were caught by extra mutants in slices 34 and 35. Cost if wrong: none; more evidence, no design change beyond R2. Named in chat when made.
- **R4: the spec review's Important point and wording points were applied.** Decided: every copy was rerun against both test files and the proof table states each run's result and failing test (it had a column saying the older tests in the two files passed, but M1, M2 and M4 had run only the unit file and M5 and M6 only the integration file); the table's rows are in number order with one phrasing; two known limits are added (a mutant can pass a run on a loaded machine; a lock-free extra read fails the test); the post-merge docs name docs/README.md and both insertion points; `Parked.get` stays without type hints (the review's optional point; not a lint error, since ANN is not selected and mypy covers packages/core only). Found by the spec review of ff6f76b. Why: no claim wider than what was run, and nothing for the plan writer to guess. Cost if wrong: none. Named in chat when made.
- **R5: the lock test joins only started threads.** Decided: `if t.ident is not None:` before `t.join(5)` in the `finally` block; the user chose this over leaving the test as approved with the misleading error recorded as a known limit. Found by the spec review of ff6f76b (if `assert seen.writing.wait(5)` fails, the second thread was never started and joining it raises `RuntimeError`, hiding the assertion). Why: a failing run shows the real assertion. Cost if wrong: one more line in the test. Asked in chat.
- **R6: the re-review's minor was applied.** Decided: the proof's last run is described as the seventh mutant (M7, the eighth copy), run on the unit file alone (it had said "a seventh copy", written without counting base, and named no test file). Found by the re-review of 8aed9a5. Why: accuracy. Cost if wrong: none. Named in chat when made.
- **R7: the plan review's five points were applied to the plan.** Decided: the plan states the trailer line itself (it had said "the `Co-Authored-By` line from the latest session reminder", which an Opus 5.5 subagent would read as its own reminder, against R1), and its self-review states R1 as written; the 20-run repeat check has its own `pgrep` step; Step 4 stops if the scratch folder already exists; the departures list gains the `base` row replaced by Step 3's run on the repo's code; a `ruff format` change in Step 5 re-runs the banned-word grep. Found by the plan review of 08cc18b (1 Important, 4 Minor). Why: nothing for the executing subagent to guess, and no trailer switch without a ruling. Cost if wrong: none. Named in chat when made.
- **R8: the plan's trailer line has no override.** Decided: the sentence "If the task brief names a different trailer, the brief wins." is removed from the plan's Global Constraints; a trailer switch needs a new ruling and a plan edit. Found by the plan re-review of b0f92ab (the sentence, added by the R7 commit, let a brief switch the trailer with no ruling, against R1 and R7's own reason). Why: R1 stays the only rule. Cost if wrong: none. Named in chat when made.
- **R9: the plan's self-review names R8.** Decided: the plan's "Rulings applied to this plan" line lists R8 and R9 after R1 and R7 (R8 edited the plan, and the line had not been updated with it). Found by the plan re-review of d89c727. Why: the line lists every ruling that changed the plan. Cost if wrong: none. Named in chat when made.
- **R10: a comma on the plan's rulings line, with no further review round.** Decided: the plan's "Rulings applied to this plan" line gets the comma after R1's parenthesis that the R9 commit dropped, and names R10; this commit goes into execution unreviewed; the user chose this over leaving the comma out, or a fifth plan review round. Found by the plan re-review of 25e5227, whose verdict was "Plan ready for execution? Yes". Why: punctuation only; no step, command or code block changes. Cost if wrong: an unreviewed one-line wording commit in the plan. Asked in chat.
- **R11: commits from execution on carry the Opus 5.5 trailer.** Decided: the plan's trailer line and Step 6 name "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>", the trailer the latest attribution reminder names; the slice 36 spec and plan commits (ff6f76b, 8aed9a5, 98dc25f, 08cc18b, b0f92ab, d89c727, 25e5227, 77f1ccb) keep the Fable 5.1 trailer; this commit carries Opus 5.5 and goes into execution unreviewed. Found by the controller, on a new attribution reminder after the execution choice, with the session moved to Opus 5.5. Why: R1 and R8 require a ruling and a plan edit for a switch. Cost if wrong: mixed trailers within one branch. Named in chat when made.
  - The ledger line, as recorded: "Ruling: R11 — Decided: commits from execution on carry "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; the plan's trailer line and Step 6 edited in 8619ac7; the earlier slice 36 commits keep Fable 5.1. Found by: the controller, on a new attribution reminder after the execution choice. Why: R1 and R8 require a ruling and a plan edit for a switch. Cost if wrong: mixed trailers within one branch. How named: named in chat when made."
- **R12: subagent dispatches leave out the `model` parameter.** Decided: from execution on, subagents are dispatched with no `model` parameter (until now `model: "opus"`). Found by the controller, with the session now on Opus 5.5. Why: memory rule "omit the Agent model param on Opus". Cost if wrong: none; both give Opus 5.5. Named in chat when made.
  - The ledger line, as recorded: "Ruling: R12 — Decided: subagent dispatches leave out the `model` parameter. Found by: the controller, with the session on Opus 5.5. Why: memory rule "omit the Agent model param on Opus". Cost if wrong: none; both give Opus 5.5. How named: named in chat when made."
- **R13: the implementer's process departures stand with no fix round.** (Title: writer's own wording.) The ledger line, as recorded: "Task 1: Ruling: R13 — Decided: the implementer's process departures stand with no fix round: `COLUMNS=200` on the three mutant runs (the brief's expected FAILED lines include the ` - assert ...` reason, which pytest only prints at a wider width), and for m1 `pgrep -fl pytest` in the same Bash call as the import check rather than on its own (it printed nothing). Found by: the implementer's report and the task review's ⚠️ item. Why: neither changes what was run or its result; no pytest overlapped. Cost if wrong: one m1 run whose pgrep check shared a call; the brief's command misses the reason text unless the width is set. How named: named in chat when made."
- **R14: one fix wave, docs only, after the final review.** (Title: writer's own wording.) The ledger line, as recorded: "Ruling: R14 — Decided: one fix wave, docs only: R13 and R14 appended to the spec's Rulings; a "Changes made during execution" section added to the plan (the commit, the results, the `COLUMNS=200` note for Step 4, R11–R14, the task and final reviews); the final review's third minor and the three Task 1 minors stay deferred. Found by: the final review (Minors 1 and 2). Why: rulings must outlive the ledger, and the plan's Step 4 command does not print the expected reason text without the width; the controller does not commit fixes. Cost if wrong: one more docs commit on the branch. How named: named in chat when made."
- **R15: the fix-wave commit stands although three markers were written with a heredoc.** (Title: writer's own wording.) The ledger line, as recorded: "Ruling: R15 — Decided: e2e649b stands; no redo of the three heredoc-written markers. Found by: the fixer's own report. Why: each was an exact single-match string swap in a markdown file, the content is what the Edit tool would have produced, and the scoped re-review checks the content. Cost if wrong: a broken brief constraint left in place, disclosed. How named: named in chat when made."
- **R16: the plan's rulings line is completed after merge.** (Title: writer's own wording.) The ledger line, as recorded: "Fix wave: parked — the plan's "Rulings applied to this plan" line stops at R11 although R14 edited the plan (R9's reason: "the line lists every ruling that changed the plan") — Ruling: R16 — Decided: no second fix wave; the post-merge docs commit adds R14 (and R16) to that line. Found by: the fix-wave re-review. Why: the process allows one fix wave. Cost if wrong: the plan's self-review line is incomplete until the post-merge docs commit. How named: named in chat when made." Applied in the post-merge docs commit, which adds R14 and R16 to that line (writer's own wording).
- **R17: R15 is not on the plan's rulings line.** Decided: the post-merge docs commit's addition of R15 to the plan's "Rulings applied to this plan" line is undone, and the line names R14, R16 and R17; the plan's closing bullet and R16's last sentence say the same; the review's four minors are applied (the findings note names the "Untested" line, describes M4 as the lock held around the sweep and the read only, and is punctuated; the plan marks two sentences as the writer's). Found by the review of d765531 (1 Important: R16 named R14 and R16, not R15, and R15 changed nothing in the plan, which is R9's test for the line). Why: no claim wider than its source. Cost if wrong: none. Named in chat when made.

## Out of scope

- Any change to `TokenLimiter` or the public routes.
- The limiter under load from many threads or processes; the sweep under concurrency; shared limiter state across processes (slice 31's out-of-scope list).
- An unknown token on a real clock, and a live check.
