# Slice 67: Remove the Two Pytest Warnings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The backend gate ends `1811 passed, 2 deselected` with no warnings summary.

**Architecture:** Two dependency declarations and a re-lock. `apps/api/pyproject.toml` gains the floor `starlette>=1.7` (its 1.7.0 `TestClient` no longer evaluates the deprecated `anyio.abc.BlockingPortal` alias). The root dev group gains `httpx2>=2.13` (`starlette.testclient` warns whenever `httpx2` is not importable). `uv lock` records starlette 1.7.0 and httpx2 2.13.1 with its dependencies. No Python, TypeScript or test file changes.

**Tech Stack:** uv workspace (Python 3.13), fastapi 0.141.1 (unchanged), starlette 1.6.0 → 1.7.0, httpx2 2.13.1 (new, dev only), httpx 0.28.1 (unchanged).

**Spec:** `docs/superpowers/specs/2026-10-13-slice67-dependency-upgrade-design.md`

## Global Constraints

- Branch `slice67`, worktree `/Users/vineet/Downloads/ADK/bsi-wt/slice67`, base main 555d90d. The shell cwd resets after every command: prefix each with `cd /Users/vineet/Downloads/ADK/bsi-wt/slice67 &&`.
- Edit only `apps/api/pyproject.toml`, `pyproject.toml` and (by `uv lock`) `uv.lock`. No other file changes. No `filterwarnings` is added (spec §3).
- fastapi stays at 0.141.1; `httpx` 0.28.1 stays declared in `packages/core/pyproject.toml` and the dev group; `bsi_core/crawl.py` and `bsi_core/judge.py` are not touched (spec §7).
- `uv lock` is run plain: no `--upgrade`, no `--upgrade-package`. The expected lock delta is exactly starlette 1.6.0→1.7.0 and the additions httpx2 2.13.1, httpcore2 2.13.1, truststore 0.10.4, httpx2-jsfetch 1.0 (spec §4).
- Before any pytest run, the pre-check runs as its own command (Task 2, Step 1 text). Two pytests of this repo deadlock on `bsi_test`.
- Every commit is gated on the banned-word grep (the exact command is in Task 1, Step 7); never bypass it by hand. The words are listed in `tests/unit/test_recommend_copy.py` (`FORBIDDEN`).
- No live checks, no database migration, no worker, no model or DataForSEO spend (spec §6.4).
- Prettier is not in the gate; never run it. Never read, list, grep or source `.env`. No `rm`. No heredoc file writes. On a refused tool call, report BLOCKED.
- Commit trailer for implementer commits: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. CI installs with plain `uv sync` (`.github/workflows/ci.yml:43`), so a lockfile that is out of step with the pyprojects would silently re-resolve there. Pinned by Task 1, Step 5 (`uv lock --check` exits 0).
2. The lock must move only the five packages the spec names; any other `Updated`/`Added` line means `uv lock` did more than the floor and the dev dependency asked. Pinned by Task 1, Step 4 (the `git diff -U0 uv.lock` name/version grep).
3. `httpx2` must not shadow `httpx` for `bsi_core`: `tests/unit/test_http_fetch.py` and `tests/unit/test_dataforseo.py` drive `http_fetch` with `httpx.MockTransport`, and those tests must still pass with both packages installed. Pinned by Task 2, Step 2 (full backend gate, which runs them).
4. starlette 1.7.0 is the API's production starlette too (spec §1); whatever changed between 1.6.0 and 1.7.0 beyond the TestClient fix must not break an existing API test. Pinned by Task 2, Step 2 (full backend gate, `1811 passed`).
5. The web gate must be unaffected by a backend-only change (`openapi.json`/`schema.d.ts` do not change because no route changed). Pinned by Task 2, Step 3 (`npm run gate`, 93 vitest, build green, `gen:check` clean).

---

### Task 1: Declare the floor and the dev dependency, re-lock

**Files:**
- Modify: `apps/api/pyproject.toml:5`
- Modify: `pyproject.toml:16`
- Regenerate: `uv.lock` (by `uv lock`; never edited by hand)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: a committed `uv.lock` with starlette 1.7.0 and httpx2 2.13.1 that Task 2's gates run against.

- [ ] **Step 1: Confirm the starting state**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice67 && git status --short && uv run python -c "import starlette; print(starlette.__version__)" && (uv run python -c "import httpx2" 2>&1 | tail -1)`
Expected: no modified tracked files; `1.6.0`; `ModuleNotFoundError: No module named 'httpx2'`.

- [ ] **Step 2: Apply the two replace blocks**

Each block replaces exactly one occurrence. Apply with the Edit tool (old string → new string), byte for byte.

`apps/api/pyproject.toml` — replace:

```toml
dependencies = ["bsi-core", "fastapi>=0.115", "uvicorn>=0.30"]
```

with:

```toml
# starlette>=1.7: TestClient no longer imports the deprecated
# anyio.abc.BlockingPortal alias.
dependencies = ["bsi-core", "fastapi>=0.115", "starlette>=1.7", "uvicorn>=0.30"]
```

`pyproject.toml` — replace:

```toml
dev = ["pytest>=8", "pytest-cov>=5", "httpx>=0.27", "ruff>=0.6", "mypy>=1.11"]
```

with:

```toml
# httpx2: starlette.testclient warns unless it is installed.
dev = [
    "pytest>=8",
    "pytest-cov>=5",
    "httpx>=0.27",
    "httpx2>=2.13",
    "ruff>=0.6",
    "mypy>=1.11",
]
```

Then run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice67 && git diff --stat`
Expected: two files changed, `apps/api/pyproject.toml` with 4 lines (3 added, 1 removed) and `pyproject.toml` with 10 lines (9 added, 1 removed); git pads the names and adds a `2 files changed, 12 insertions(+), 2 deletions(-)` line.

- [ ] **Step 3: Re-lock, plain**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice67 && uv lock`
Expected output, in this order:

```
Resolved 65 packages in <time>
Added httpcore2 v2.13.1
Added httpx2 v2.13.1
Added httpx2-jsfetch v1.0
Updated starlette v1.6.0 -> v1.7.0
Added truststore v0.10.4
```

If any other `Added`, `Updated` or `Removed` line appears, stop and report it; do not commit.

- [ ] **Step 4: Check the lock delta is exactly the five packages**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice67 && git diff -U0 uv.lock | grep -E '^[-+](name|version) '`
Expected, exactly these lines:

```
+name = "httpcore2"
+version = "2.13.1"
+name = "httpx2"
+version = "2.13.1"
+name = "httpx2-jsfetch"
+version = "1.0"
-version = "1.6.0"
+version = "1.7.0"
+name = "truststore"
+version = "0.10.4"
```

- [ ] **Step 5: Sync and confirm the lock agrees with the pyprojects**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice67 && uv sync && uv lock --check && uv run python -c "import starlette, httpx, httpx2; print(starlette.__version__, httpx.__version__, httpx2.__version__)"`
Expected: `uv lock --check` prints `Resolved 65 packages` and exits 0; the last line is `1.7.0 0.28.1 2.13.1`.

- [ ] **Step 6: Pre-check, then the short red/green check**

First, as its own command:

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && n=0; for p in $(pgrep -f 'bin/pytest|-m pytest'); do [ "$p" = "$$" ] && continue; c=$(lsof -p $p 2>/dev/null | awk '$4=="cwd"{print $NF}'); echo "pytest $p cwd $c"; case "$c" in /Users/vineet/Downloads/ADK/bsi-platform*|/Users/vineet/Downloads/ADK/bsi-wt/*|*/scratchpad/proof*) n=1;; esac; done; [ $n = 0 ] && echo "no pytest of this repo running" || echo "WAIT"
```

Expected: `no pytest of this repo running` (a pytest with cwd `…/invoice-processing` does not block). If it prints `WAIT`, wait and re-run; do not proceed.

Then: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice67 && uv run pytest -q tests/integration/test_transactions.py -p no:cacheprovider`
Expected: `2 passed in <time>` and **no** `warnings summary` section. (On main the same command ends `2 passed, 2 warnings`; spec §5, output `01`.)

- [ ] **Step 7: Commit, gated on the banned-word grep**

Run:

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice67 && git add apps/api/pyproject.toml pyproject.toml uv.lock && ! { git diff --cached -U0 | grep '^+' | grep -v -F 'Banned-word grep (must block the commit)' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1([^0-9]|$)|top spot|dominat|certain'; } && git commit -q -m "build: starlette>=1.7 and httpx2 so the test client stops warning

starlette 1.7.0 drops the deprecated anyio.abc.BlockingPortal alias;
httpx2 is what starlette.testclient asks for. No code changes.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git log --oneline -1
```

Expected: one new commit; `git status --short` shows nothing modified.

---

### Task 2: Run both gates

**Files:**
- None modified. Read-only verification of the Task 1 commit.

**Interfaces:**
- Consumes: the Task 1 commit on `slice67`.
- Produces: the two gate outputs quoted in the ledger (backend ending `1811 passed, 2 deselected`, no warnings; web 93 vitest, build green).

- [ ] **Step 1: Pre-check, as its own command**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && n=0; for p in $(pgrep -f 'bin/pytest|-m pytest'); do [ "$p" = "$$" ] && continue; c=$(lsof -p $p 2>/dev/null | awk '$4=="cwd"{print $NF}'); echo "pytest $p cwd $c"; case "$c" in /Users/vineet/Downloads/ADK/bsi-platform*|/Users/vineet/Downloads/ADK/bsi-wt/*|*/scratchpad/proof*) n=1;; esac; done; [ $n = 0 ] && echo "no pytest of this repo running" || echo "WAIT"
```

Expected: `no pytest of this repo running`. On `WAIT`, wait and re-run.

- [ ] **Step 2: Backend gate**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice67 && uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100`
Expected, in order: `185 files already formatted`; `All checks passed!`; `Success: no issues found in 31 source files`; coverage `TOTAL … 100%`; final line `1811 passed, 2 deselected in <time>`; the string `warning` appears nowhere in the output. Report the final line and the absence of a warnings summary verbatim.

- [ ] **Step 3: Web gate**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice67/apps/web && npm run gate`
Expected: typecheck, lint, test (`Tests  93 passed`), build and `gen:check` all pass; exit 0. If `node_modules` is missing, run `cd /Users/vineet/Downloads/ADK/bsi-wt/slice67/apps/web && npm ci` first.

- [ ] **Step 4: Confirm nothing changed**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice67 && git status --short`
Expected: empty (the web build writes only ignored paths).

---

## Plan self-review

1. **Spec coverage:** §4 (the change) → Task 1 Steps 2-3; §4 lock delta → Task 1 Step 4; §5's green observation → Task 1 Step 6 and Task 2 Step 2; §6 (verification) → Task 2; §3 and §7 (no filterwarnings, no fastapi bump, no crawl/judge change) → Global Constraints. §8 (handoff note) is a docs item for the findings doc, not a task.
2. **Placeholder scan:** none.
3. **Type consistency:** no code types; the version strings 1.7.0, 2.13.1, 0.10.4 and 1.0 match the spec's §4 table, and 0.28.1 (httpx, unchanged) matches spec §2.
4. **Review Focus:** five lines, each pinned to a step.

**Departures from the spec:** none. The replace blocks were applied by script to a fresh detached copy of main and the resulting `apps/api/pyproject.toml`, `pyproject.toml` and (after `uv lock`) `uv.lock` compared byte-identical to the proof worktree's patched state; the check's output is saved as proof output `10-plancheck.txt` and the findings doc quotes it.

## Changes made during execution

(filled in by the docs PR)
