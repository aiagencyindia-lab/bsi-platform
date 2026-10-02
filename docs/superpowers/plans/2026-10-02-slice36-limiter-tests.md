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
- **Commit trailer:** exactly `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` (spec R1: the controller's latest session reminder names it). Use this line even if your own session reminder names another model. If the task brief names a different trailer, the brief wins.
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

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
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
- Rulings applied to this plan: the spec's R1 (slice 36 commits carry the Fable 5.1 trailer; a new ruling records any switch) and R7 (the plan review's five points), in the spec's Rulings section.
- Placeholders: `<workspace>` and `<scratchpad>` (paths the task brief supplies), `<m>` (the copy name in Step 4's loop).
- Type consistency: `TokenLimiter(limit, window, clock)` and `check(key) -> int | None`, as in apps/api/bsi_api/ratelimit.py; `Clock` as defined at the top of the unit test file; `_generic_404(r)` and `_scene(owner, make_org, make_brand)` as used in tests/integration/test_api_reports.py.
