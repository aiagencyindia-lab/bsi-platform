# Slice 36 Limiter Lock and Unknown-Token Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin two untested behaviours of the public share-route rate limit: `TokenLimiter.check` holds its lock from the read to the write, and an unknown token is counted under its own key.

**Architecture:** Two tests appended to two existing test files; no production code changes. Both pass on the current code; the evidence that they pin the behaviour is a mutation run on copies of `bsi_api` outside the repo, where exactly one new test fails per mutant and every other test in the two files still passes.

**Tech Stack:** Python 3.13, pytest, `threading` (unit test); FastAPI `TestClient` and the shared test database (integration test).

**Spec:** `docs/superpowers/specs/2026-10-02-slice36-limiter-tests-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice36-limiter-tests`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB, the network or the worker loop. Never call a model. Do NOT change any file under `apps/` or `packages/` in the repo (the mutation run uses copies outside the repo).
- **Shared test DB:** run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own before every pytest run; if it prints a running pytest, stop and wait for it to finish before running yours. Never run two suites at once. Run the full backend suite only once, in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal: read the file and repeat the edit.)
- **Writing files:** never use a shell heredoc or zsh `echo` to write files; use the Edit or Write tools. `mkdir` and `cp` for the scratch copies are allowed. Scratch copies go under the scratchpad path given in the task brief, never inside the repo. Never run `rm`.
- **Lint and types:** ruff line length is 80 (the Backend gate runs `ruff format .` first).
- **Banned words:** copy (code, comments, docstrings, test names) never contains the words listed in `FORBIDDEN` in tests/unit/test_recommend_copy.py.
- **Banned-word grep:** `cd /Users/vineet/Downloads/ADK/bsi-platform && git diff --cached -U0 | grep '^+' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'`, run after staging. Expected: no match (grep exits 1 and prints nothing).
- **Backend gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform && { uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task1.txt 2>&1; echo "gate exit $?"` (the echo prints to the terminal).
- **Commit trailer:** exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (spec R1 and R11: the controller's latest session reminder names it). Use this line even if your own session reminder names another model.
- **Baseline counts** (collected 2026-10-02 on `98dc25f`): backend `1572/1574 tests collected (2 deselected)`, so `1572 passed, 2 deselected` (plus the 2 known third-party warnings); tests/unit/test_ratelimit.py 4; tests/integration/test_api_reports.py 14; the two files together 18.

## File map

| File | Responsibility |
|---|---|
| `tests/unit/test_ratelimit.py` | `import threading`, the `Parked` helper, `test_checks_on_one_key_do_not_interleave` |
| `tests/integration/test_api_reports.py` | `test_an_unknown_token_has_its_own_budget` |

---

### Task 1: the lock test and the unknown-token test

**Files:**
- Test: `tests/unit/test_ratelimit.py` (a new first line; append after `test_the_sweep_runs_once_per_window`, the last test in the file)
- Test: `tests/integration/test_api_reports.py` (append after `test_public_routes_are_rate_limited_per_token`, the last test in the file)

**Interfaces:**
- Consumes: in the unit file, `TokenLimiter` (imported at the top) and the file's `Clock` class; in the integration file, `_scene` (imported at the top), the file's `_generic_404(r)` helper, and the fixtures `client`, `owner`, `make_org`, `make_brand`.
- Produces: nothing for later tasks.

- [ ] **Step 1: Add the lock test**

In `tests/unit/test_ratelimit.py`, replace the file's first line

```python
from bsi_api import ratelimit
```

with

```python
import threading

from bsi_api import ratelimit
```

Then replace the file's last two lines

```python
    assert limiter._seen is not seen
    assert list(limiter._seen) == ["e"]
```

with

```python
    assert limiter._seen is not seen
    assert list(limiter._seen) == ["e"]


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

- [ ] **Step 2: Add the unknown-token test**

In `tests/integration/test_api_reports.py`, replace the file's last two lines

```python
    # Another token has its own budget.
    assert client.get(f"/v1/r/{other}").status_code == 200
```

with

```python
    # Another token has its own budget.
    assert client.get(f"/v1/r/{other}").status_code == 200


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

- [ ] **Step 3: Run the two files on the real code**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first (if it prints a running pytest, wait), then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_ratelimit.py tests/integration/test_api_reports.py 2>&1 | tail -1`
Expected: `20 passed` (18 + 2), with the 2 known third-party warnings. (The behaviour already exists, so there is no red run on the real code; Step 4 is the red evidence.)

Then the repeat check on the unit file (no database). Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first (if it prints a running pytest, wait), then: `cd /Users/vineet/Downloads/ADK/bsi-platform && for i in $(seq 20); do uv run pytest -q -p no:cacheprovider tests/unit/test_ratelimit.py 2>&1 | tail -1 | sed 's/ in .*//'; done | sort | uniq -c`
Expected: one line, `20 5 passed`.

- [ ] **Step 4: Mutation run (red evidence)**

First check the folder is new: `cd /Users/vineet/Downloads/ADK/bsi-platform && ls <scratchpad>/s36mut` must fail with "No such file or directory"; if the folder exists, stop and report it. Then make three copies outside the repo: `cd /Users/vineet/Downloads/ADK/bsi-platform && mkdir -p <scratchpad>/s36mut/m1 <scratchpad>/s36mut/m3 <scratchpad>/s36mut/m4 && cp -R apps/api/bsi_api <scratchpad>/s36mut/m1/ && cp -R apps/api/bsi_api <scratchpad>/s36mut/m3/ && cp -R apps/api/bsi_api <scratchpad>/s36mut/m4/`

Edit the copies with the Edit tool, one change each:

- **M1** (the lock removed), in `<scratchpad>/s36mut/m1/bsi_api/ratelimit.py`: change the one line `        with self._lock:` to `        if True:`.
- **M4** (the lock around the sweep and the read only), in `<scratchpad>/s36mut/m4/bsi_api/ratelimit.py`: replace

```python
            start, count = self._seen.get(key, (index, 0))
            if start != index:
                count = 0
            if count >= self.limit:
                # now is inside the window, so this is at least 1.
                return math.ceil((index + 1) * self.window - now)
            self._seen[key] = (index, count + 1)
            return None
```

with (the first line unchanged, the other seven moved out of the `with` block by four spaces)

```python
            start, count = self._seen.get(key, (index, 0))
        if start != index:
            count = 0
        if count >= self.limit:
            # now is inside the window, so this is at least 1.
            return math.ceil((index + 1) * self.window - now)
        self._seen[key] = (index, count + 1)
        return None
```

- **M3** (`_limit` after `_run` in both routes), in `<scratchpad>/s36mut/m3/bsi_api/routers/public.py`: replace both occurrences (Edit with `replace_all`) of

```python
    _limit(token, request)
    run = _run(token)
```

with

```python
    run = _run(token)
    _limit(token, request)
```

Confirm the mutations are in the copies and not in the repo:
- `cd /Users/vineet/Downloads/ADK/bsi-platform && grep -c "with self._lock:" <scratchpad>/s36mut/m1/bsi_api/ratelimit.py <scratchpad>/s36mut/m4/bsi_api/ratelimit.py apps/api/bsi_api/ratelimit.py` — expected `0` for m1, `1` for m4, `1` for the repo.
- `cd /Users/vineet/Downloads/ADK/bsi-platform && grep -c "^        self._seen\[key\] = (index, count + 1)" <scratchpad>/s36mut/m4/bsi_api/ratelimit.py apps/api/bsi_api/ratelimit.py` — expected `1` for m4 (the write at eight spaces), `0` for the repo.
- `cd /Users/vineet/Downloads/ADK/bsi-platform && grep -A1 -c "^    run = _run(token)" <scratchpad>/s36mut/m3/bsi_api/routers/public.py && grep -A1 "^    run = _run(token)" <scratchpad>/s36mut/m3/bsi_api/routers/public.py` — expected: two matches, each followed by `    _limit(token, request)`.
- `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short apps packages` — expected: no output.

Then, for each of `m1`, `m4`, `m3` in turn (one at a time; `<m>` is the copy's name):

1. Confirm the copy is what Python imports: `cd /Users/vineet/Downloads/ADK/bsi-platform && PYTHONPATH=<scratchpad>/s36mut/<m>:. uv run python -c "import bsi_api.ratelimit as r, bsi_api.routers.public as p; print(r.__file__); print(p.__file__)"`. Expected: both paths under `<scratchpad>/s36mut/<m>/bsi_api/`.
2. Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own (if it prints a running pytest, wait).
3. Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && PYTHONPATH=<scratchpad>/s36mut/<m>:. uv run pytest -q -p no:cacheprovider tests/unit/test_ratelimit.py tests/integration/test_api_reports.py 2>&1 | grep -E "^FAILED|passed|failed"`

Expected:

| Copy | Result | The one FAILED line |
|---|---|---|
| m1 | `1 failed, 19 passed` | `test_checks_on_one_key_do_not_interleave - assert (True and 2 == 1)` |
| m4 | `1 failed, 19 passed` | `test_checks_on_one_key_do_not_interleave - assert (True and 2 == 1)` |
| m3 | `1 failed, 19 passed` | `test_an_unknown_token_has_its_own_budget - assert 404 == 429` |

Record every command and its output in the report. If a mutant gives any other result, stop and report it; do not change the tests.

- [ ] **Step 5: Banned-word grep, then the backend gate**

Stage both files (`cd /Users/vineet/Downloads/ADK/bsi-platform && git add tests/unit/test_ratelimit.py tests/integration/test_api_reports.py`) and run the banned-word grep from Global Constraints. Expected: no match. Then run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own (wait if a pytest is running), then the Backend gate from Global Constraints. Expected: `gate exit 0`; `gate-task1.txt` shows `1574 passed, 2 deselected` (1572 + 2) and the metrics coverage line at 100%. (`ruff format .` should change nothing; if it changed a test file, re-stage it, re-run the banned-word grep, and say so in the report.) Then `cd /Users/vineet/Downloads/ADK/bsi-platform && git status --short` — expected: only the two staged test files (`M  tests/integration/test_api_reports.py`, `M  tests/unit/test_ratelimit.py`).

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add tests/unit/test_ratelimit.py tests/integration/test_api_reports.py && git commit -m "test(api): pin the limiter's lock and an unknown token's budget

The lock test parks one check between its read and its write and
asserts a second check on the same key has not read yet. The other
test asserts an unknown share token is counted under its own key
before the lookup. With the lock removed, or moved off the write, the
first fails; with _limit after _run, the second fails; the older
tests in both files pass on each mutant.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review (plan vs spec)

- Spec coverage: Test 1 (Design) → Step 1, the code block identical to the spec's, with the `import threading` first line; Test 2 → Step 2, identical to the spec's; no production change → Global Constraints (Off limits) and the `git status` checks in Steps 4 and 5; the proof → Steps 3–4; counts (4 → 5; 14 → 15; 1572 → 1574) → Steps 3 and 5, with the baseline re-collected as the spec asks (Counts); copy → Step 5. Process and docs are controller work after merge.
- Departures from the spec:
  1. The mutation run repeats three of the spec's seven mutants: M1 and M4 for the lock test and M3 for the unknown-token test. M2, M5, M6 and M7 are not re-run; they are the spec's evidence. M1 is the plain removal, M4 is the mutant the first version of the lock test missed, and M3 moves `_limit` in both routes.
  2. The mutation run uses the repo's own test files against each copy (the tests are now in the repo), rather than scratch test files with `-p tests.conftest --rootdir .`.
  3. The 20-run repeat check is run on the real code only (Step 3); the spec also ran it on M1, M2 and M4.
  4. Step 4 adds grep checks that each mutation is in its copy and not in the repo, and a `git status` check; the spec records only the import-path check.
  5. Global Constraints adds "Never run `rm`": scratch copies are made once on a fresh folder.
  6. The spec's `base` row (an unchanged copy run through `PYTHONPATH`, `20 passed`) is replaced by Step 3's run of the two files on the repo's own code.
- Rulings applied to this plan: the spec's R1 (slice 36 commits carry the Fable 5.1 trailer; a new ruling records any switch), R7 (the plan review's five points), R8 (the trailer line has no override), R9 (this line names R8), R10 (a comma on this line), R11 (the trailer switches to Opus 5.5), R14 (the final review's fix wave), R16 (this line is completed after merge) and R17 (R15 is not on this line), in the spec's Rulings section.
- Placeholders: `<workspace>` and `<scratchpad>` (paths the task brief supplies), `<m>` (the copy name in Step 4's loop).
- Type consistency: `TokenLimiter(limit, window, clock)` and `check(key) -> int | None`, as in apps/api/bsi_api/ratelimit.py; `Clock` as defined at the top of the unit test file; `_generic_404(r)` and `_scene(owner, make_org, make_brand)` as used in tests/integration/test_api_reports.py.

## Changes made during execution

- Task 1: commit a9ebcb7 (`test(api): pin the limiter's lock and an unknown token's budget`). As the implementer's report records them:
  - Step 3, the two files on the real code: `20 passed, 2 warnings in 11.89s`. The 20-run repeat check: `20 5 passed`.
  - Step 4, mutant m1: `1 failed, 19 passed, 2 warnings in 5.88s`, FAILED line `FAILED tests/unit/test_ratelimit.py::test_checks_on_one_key_do_not_interleave - assert (True and 2 == 1)` (writer's summary: the `COLUMNS=200` re-run; the first run printed `1 failed, 19 passed, 2 warnings in 5.36s` and the FAILED line without its reason).
  - Mutant m4: `1 failed, 19 passed, 2 warnings in 6.62s`, FAILED line `FAILED tests/unit/test_ratelimit.py::test_checks_on_one_key_do_not_interleave - assert (True and 2 == 1)`.
  - Mutant m3: `1 failed, 19 passed, 2 warnings in 5.49s`, FAILED line `FAILED tests/integration/test_api_reports.py::test_an_unknown_token_has_its_own_budget - assert 404 == 429`.
  - Step 5, the gate's summary lines, as gate-task1.txt records them: "172 files left unchanged", "All checks passed!", "172 files already formatted", "Success: no issues found in 29 source files", "Required test coverage of 100% reached. Total coverage: 100.00%", "1574 passed, 2 deselected, 2 warnings in 183.25s (0:03:03)".
- Step 4 note (writer's summary, except the quote): the command as written prints the FAILED line without its ` - assert ...` reason when piped; the report: "pytest truncates the short summary to terminal width (80 when piped) and the node id leaves no room." The implementer re-ran with `COLUMNS=200` prefixed to see the expected text (R13).
- The implementer's other process departures, as the report lists them: "For m1, the import-path check and the `pgrep -fl pytest` were run in one Bash call (`...; pgrep -fl pytest; echo "pgrep exit $?"`) rather than pgrep on its own. For m4 and m3 pgrep ran on its own call. Every pgrep invocation also had `; echo "pgrep exit $?"` appended."; "The Step 4 grep checks were run together in one Bash call with `echo --N` separators; the mkdir/cp command used a shell variable for the scratch path and ended with `&& echo ok`."; "The banned-word grep had `; echo "grep exit $?"` appended."
- At execution start: R11 (commits from execution on carry the Opus 5.5 trailer) and R12 (subagent dispatches leave out the `model` parameter). During execution: R13 (the implementer's process departures stand with no fix round). After the final review: R14 (one fix wave, docs only). (The short labels are the writer's own wording.) All four are in the spec's Rulings section.
- The task review, as the ledger records it: "Task 1: task review (a8587453e43ea374d, 8619ac7..a9ebcb7): "✅ Spec compliant"; "Task quality: Approved"; 0 Critical, 0 Important, 3 Minor; 2 ⚠️ items." Its minors:
  - "tests/unit/test_ratelimit.py:107 `sorted(results, key=str) == [20, None]` relies on "20" < "None"; a plainer form would read better (the brief set the text verbatim)"
  - "tests/unit/test_ratelimit.py:66-82 `Parked.get` and `__setitem__` have no type hints; mypy does not cover tests"
  - "every reported run shows the 2 known third-party warnings (baseline), no action for this task"
- The final review, as the ledger records it: "Final review (ad4c9fd035b072360, b63ebe6..a9ebcb7): "Ready to merge? With fixes"; 0 Critical, 0 Important, 3 Minor." Its minors:
  - "spec Rulings section ends at R12; R13 is in the ledger only (fix: append R13 to the spec)"
  - "plan Step 4's expected FAILED lines with the ` - assert ...` reason need a wide terminal (`COLUMNS=200`); optional execution note in the plan"
  - "spec "Process and docs" line on `model: "opus"` describes only the Fable-session phase; R12 supersedes it from execution on; accurate as a conditional, no change needed"
- The final review's first two minors are fixed by this section and the spec's R13 and R14 (the writer's summary of R14). The final review's third minor and the three Task 1 minors stay deferred, per R14 and the final triage: "test_ratelimit.py:107 sorted(..., key=str): leave deferred"; "test_ratelimit.py:66-82 Parked without type hints: leave deferred"; "The 2 known third-party warnings: leave deferred".
- The fix wave, as the ledger records it: "Fix wave: fixer a8bdebd9d2fb2089c DONE_WITH_CONCERNS, commit e2e649b "docs: slice 36 final review fixes (R14)" (2 files, +23). Concern, as reported: "I added three of those markers with a `python3` heredoc script, not the Edit tool. The brief says no heredoc to write files.""
- R15, the ledger line, as recorded: "Ruling: R15 — Decided: e2e649b stands; no redo of the three heredoc-written markers. Found by: the fixer's own report. Why: each was an exact single-match string swap in a markdown file, the content is what the Edit tool would have produced, and the scoped re-review checks the content. Cost if wrong: a broken brief constraint left in place, disclosed. How named: named in chat when made."
- The fix wave's scoped re-review, as the ledger records it: "Fix wave re-review (a0943ac2c93704128, a9ebcb7..e2e649b): "All findings addressed: Yes"; "New breakage: 0 Critical, 0 Important, 1 Minor"; 4 out-of-scope observations." Its one new minor was parked (writer's reading): "Fix wave: parked — the plan's "Rulings applied to this plan" line stops at R11 although R14 edited the plan (R9's reason: "the line lists every ruling that changed the plan") — Ruling: R16 — Decided: no second fix wave; the post-merge docs commit adds R14 (and R16) to that line. Found by: the fix-wave re-review. Why: the process allows one fix wave. Cost if wrong: the plan's self-review line is incomplete until the post-merge docs commit. How named: named in chat when made."
- Its out-of-scope observations, recorded as deferred minors:
  - "Fix wave: minor (deferred): out of scope: progress.md line 3 says "rulings R1–R12 there"; the spec now holds R1–R14"
  - "Fix wave: minor (deferred): out of scope: the plan's final-review quote stops at "3 Minor."; the reviewer's suggested timing (post-merge docs commit) differs from R14's (a fix wave before merge); R14 governs"
  - "Fix wave: minor (deferred): out of scope: the spec's R13 and R14 quote the ledger line, unlike R1–R12's own prose form; follows the brief's "quote, not paraphrase""
  - "Fix wave: minor (deferred): out of scope: the fixer wrote three markers with a python3 heredoc, against the brief (R15); the resulting text is correct"
- After merge (PR #69, merge commit c7c4047), the post-merge docs commit applies R16: the self-review's rulings line now names R14 and R16, and R17 (writer's own wording). The four out-of-scope minors stay deferred (writer's own wording; the ledger tags each "minor (deferred)").
