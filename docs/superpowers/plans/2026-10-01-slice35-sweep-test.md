# Slice 35 Once-Per-Window Sweep Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin `TokenLimiter`'s once-per-window sweep (slice 31 R10) with a named unit test.

**Architecture:** One test function appended to tests/unit/test_ratelimit.py; no production code changes. The test passes on the current code; the evidence that it pins the rule is a mutation run on a copy of `bsi_api` outside the repo (the `and self._swept != index` guard removed), where the new test fails and the three existing tests still pass.

**Tech Stack:** Python 3.13, pytest (unit test; no database).

**Spec:** `docs/superpowers/specs/2026-10-01-slice35-sweep-test-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice35-sweep-test`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB, the network or the worker loop. Never call a model. Do NOT change any file under `apps/` or `packages/` in the repo (the mutation run uses a copy outside the repo).
- **Shared test DB:** run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own before every pytest run; if it prints a running pytest, stop and wait for it to finish before running yours. Never run two suites at once. Run the full backend suite only once, in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal: read the file and repeat the edit.)
- **Writing files:** never use a shell heredoc or zsh `echo` to write files; use the Edit or Write tools. `mkdir` and `cp` for the scratch copy are allowed. Scratch copies go under the scratchpad path given in the task brief, never inside the repo.
- **Lint and types:** ruff line length is 80 (the Backend gate runs `ruff format .` first).
- **Banned words:** copy (code, comments, test names) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat` or `certain` (`FORBIDDEN` in tests/unit/test_recommend_copy.py).
- **Banned-word grep:** `cd /Users/vineet/Downloads/ADK/bsi-platform && git diff --cached -U0 | grep '^+' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'`, run after staging. Expected: no match (grep exits 1 and prints nothing).
- **Backend gate:** `cd /Users/vineet/Downloads/ADK/bsi-platform && { uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task1.txt 2>&1; echo "gate exit $?"` (the echo prints to the terminal).
- **Commit trailer:** the `Co-Authored-By` line from the latest session reminder.
- **Baseline counts** (collected 2026-10-01 on `64c7a18`): backend `1571/1573 tests collected (2 deselected)`, so `1571 passed, 2 deselected` (plus the 2 known third-party warnings); tests/unit/test_ratelimit.py 3.

## File map

| File | Responsibility |
|---|---|
| `tests/unit/test_ratelimit.py` | `test_the_sweep_runs_once_per_window` |

---

### Task 1: the once-per-window sweep test

**Files:**
- Test: `tests/unit/test_ratelimit.py` (append after `test_expired_keys_are_dropped_past_the_cap`, the last test in the file)

**Interfaces:**
- Consumes: `ratelimit`, `TokenLimiter` (both imported at the top of the file) and the file's `Clock` class.
- Produces: nothing for later tasks.

- [ ] **Step 1: Add the test**

In `tests/unit/test_ratelimit.py`, replace the file's last two lines

```python
    assert limiter.check("c") is None
    assert list(limiter._seen) == ["c"]
```

with

```python
    assert limiter.check("c") is None
    assert list(limiter._seen) == ["c"]


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

- [ ] **Step 2: Run the test file on the real code**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first (if it prints a running pytest, wait), then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_ratelimit.py 2>&1 | tail -1`
Expected: `4 passed`. (The behaviour already exists, so there is no red run on the real code; Step 3 is the red evidence.)

- [ ] **Step 3: Mutation run (red evidence)**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && mkdir -p <scratchpad>/s35mut/pkg && cp -R /Users/vineet/Downloads/ADK/bsi-platform/apps/api/bsi_api <scratchpad>/s35mut/pkg/` (the copy is outside the repo; run it once, on a fresh `s35mut`). In the copy's `ratelimit.py` (`<scratchpad>/s35mut/pkg/bsi_api/ratelimit.py`), use the Edit tool to change the one line `            if len(self._seen) > MAX_KEYS and self._swept != index:` to `            if len(self._seen) > MAX_KEYS:`.

Confirm the copy is what Python imports: `cd /Users/vineet/Downloads/ADK/bsi-platform && PYTHONPATH=<scratchpad>/s35mut/pkg:. uv run python -c "import bsi_api.ratelimit as r; print(r.__file__)"`. Expected: the path under `<scratchpad>/s35mut/pkg/bsi_api/`. Confirm the mutation is in that copy: `cd /Users/vineet/Downloads/ADK/bsi-platform && grep -c "self._swept != index" <scratchpad>/s35mut/pkg/bsi_api/ratelimit.py`. Expected: `0` (grep exits 1); the repo's own file still has it (`cd /Users/vineet/Downloads/ADK/bsi-platform && grep -c "self._swept != index" apps/api/bsi_api/ratelimit.py` prints `1`).

Then run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own (if it prints a running pytest, wait), then: `cd /Users/vineet/Downloads/ADK/bsi-platform && PYTHONPATH=<scratchpad>/s35mut/pkg:. uv run pytest -q -p no:cacheprovider tests/unit/test_ratelimit.py 2>&1 | grep -E "^FAILED|^>|passed|failed"`

Expected: `1 failed, 3 passed`; the failure is `test_the_sweep_runs_once_per_window` at `assert limiter._seen is seen`. If the grep does not show the `>` line, read the failure block in the full output. Record the commands and output in the report. (Before this test existed, the same mutant gave `3 passed`: spec, Design.)

- [ ] **Step 4: Banned-word grep, then the backend gate**

Stage the file (`cd /Users/vineet/Downloads/ADK/bsi-platform && git add tests/unit/test_ratelimit.py`) and run the banned-word grep from Global Constraints. Expected: no match. Then run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own (wait if a pytest is running), then the Backend gate from Global Constraints. Expected: `gate exit 0`; `gate-task1.txt` shows `1572 passed, 2 deselected` (1571 + 1) and the metrics coverage line at 100%. (`ruff format .` should change nothing; if it changed the test file, re-stage it.)

- [ ] **Step 5: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add tests/unit/test_ratelimit.py && git commit -m "test(api): pin the limiter's once-per-window sweep

With two keys past the cap, the next check sweeps into a new dict; a
later check in the same window leaves it alone; the next window sweeps
again. With the _swept guard removed this test fails and the other
three tests in test_ratelimit.py still pass.

<trailer>"
```

---

## Self-review (plan vs spec)

- Spec coverage: the test (Design, first bullet) → Step 1, the code block identical to the spec's; the proof → Steps 2–3; counts (3 → 4; 1571 → 1572) → Steps 2 and 4, with the baseline re-collected as the spec asks (Process and docs); copy → Step 4. Process and docs are controller work after merge.
- Departures from the spec:
  1. The mutation run uses the repo's own test file against the copy, rather than the test in a separate folder with its own `Clock` (the test is now in the repo); so the result is one line, `1 failed, 3 passed`, where the spec reported the new test (`1 failed`) and the existing file (`3 passed`) separately.
  2. Step 3 adds an import-path check before the mutant run; the spec records the same check as part of its proof.
  3. The spec's in-memory "other variants" are not re-run; they are the spec's evidence, and the plan's one mutant is the pytest proof the spec asks execution to repeat.
- Rulings applied to this plan: R4 (the plan review's two minors) and R5 (the commit message reflowed), in the spec's Rulings section.
- Placeholders: `<trailer>` (the Global Constraints' commit-trailer rule), `<workspace>` and `<scratchpad>` (paths the task brief supplies).
- Type consistency: `TokenLimiter(limit, window, clock)` and `check(key) -> int | None`, as in apps/api/bsi_api/ratelimit.py; `Clock` as defined at the top of the test file.
