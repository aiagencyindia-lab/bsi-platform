# Slice 71 follow-up: reset the redirect mock after each api test — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `vi.mocked(redirect).mockReset();` to `apps/web/src/lib/api.test.ts`'s `afterEach`. On vitest 5, a `mockImplementationOnce` that a test queued but never used would otherwise fire in the next test; this reset clears it. Nothing else changes.

**Architecture:** One exact edit adds two comment lines and one call after the existing `cookies` reset. The file's tests are run on their own, then both local gates. The web suite stays at 93 tests in 9 files.

**Tech Stack:** vitest 5.0.4, TypeScript, npm 10.9.8, Node v22.23.0.

**Spec:** `docs/superpowers/specs/2026-10-14-slice71-restore-fix-design.md`

## Global Constraints

- **Branch:** `slice71-restore-fix`, worktree `/Users/vineet/Downloads/ADK/bsi-wt/slice71fix`, base main 40aa797.
- **cwd:** the shell cwd resets after every command, so prefix each command with `cd /Users/vineet/Downloads/ADK/bsi-wt/slice71fix &&` (or `…/slice71fix/apps/web &&`). The exceptions are Task 2 Steps 1 and 3, which start in `/Users/vineet/Downloads/ADK/bsi-platform`.
- **Scope:** change only `apps/web/src/lib/api.test.ts`, and only by the exact edit in Task 1 Step 2. No production code, config, dependency or other test file changes. The web suite stays at 93 tests in 9 files (spec §4).
- **Out of scope:** `actions.test.ts`, any global `mockReset`, `restoreMocks` or `clearMocks` setting, and a guard test (spec §7).
- **Pytest pre-check:** before any pytest run, the pre-check runs as its own command and its raw output is saved to a file (Task 2 Step 1 text). Two pytests of this repo deadlock on `bsi_test`.
- **Banned words:** every commit is gated on the banned-word grep (the exact command is in Task 1 Step 4); never bypass it by hand. The words are listed in `tests/unit/test_recommend_copy.py` (`FORBIDDEN`).
- **No spend:** no live checks against the app, no database migration, no worker, no model or DataForSEO spend. GitHub writes are made only by the controller: this slice's PR and its merge.
- **Tool rules:** Prettier is not in the gate; never run it. Never read, list, grep or source `.env`. No `rm`. No heredoc file writes. On a refused tool call, report BLOCKED.
- **Commit trailer** for implementer commits: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **The reset breaks the `/login` test's own once-impl.** That test queues a throwing once-impl and uses it within the test, after the previous `afterEach` has run, so the reset must leave it working. Pinned by Task 1 Step 3 (`28 passed (28)`, which includes that test).
2. **The edit lands outside the `afterEach`, or twice.** Pinned by Task 1 Step 2: the Edit tool's exact `old_string` matches once. Step 3 then shows the diff adds exactly those 3 lines.
3. **Another file or line changes.** Pinned by Task 1 Step 3 (the diffstat shows one file, 3 insertions) and Step 4 (`git status --short` empty after the commit).
4. **A typecheck or lint failure from the new line,** for example `redirect` not being typed as a mock. Pinned by Task 2 Step 4 (the web gate runs `tsc` and ESLint).
5. **The suite count changes.** Pinned by Task 2 Step 4 (`Test Files  9 passed (9)`, `Tests  93 passed (93)`).

---

### Task 1: Add the redirect reset

**Files:**
- Modify: `apps/web/src/lib/api.test.ts` (the `afterEach`, lines 22–28 as at main 40aa797)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: one commit on `slice71-restore-fix`, which Task 2 gates.

The plan workspace is `/Users/vineet/Downloads/ADK/bsi-wt/slice71fix/.superpowers/sdd/2026-10-14-slice71-restore-fix/` (W below). Under subagent-driven development the controller creates it before dispatching Task 1. Under executing-plans, create it first with `mkdir -p` on that path (it is git-ignored).

- [ ] **Step 1: Confirm the starting state and install**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice71fix && git status --short && git merge-base --is-ancestor 40aa797 HEAD && echo "base ok" && grep -c "mockReset" apps/web/src/lib/api.test.ts`
Expected: no modified tracked files; `base ok`; `1` (only the `cookies` reset).

Then: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice71fix/apps/web && npm ci --no-audit --no-fund > /dev/null 2>&1; echo "npm ci exit $?"`
Expected: `npm ci exit 0`.

- [ ] **Step 2: Make the edit**

Use the Edit tool on `/Users/vineet/Downloads/ADK/bsi-wt/slice71fix/apps/web/src/lib/api.test.ts` with this `old_string`:

```ts
  vi.mocked(cookies).mockReset();
});
```

and this `new_string`:

```ts
  vi.mocked(cookies).mockReset();
  // On vitest 5, restoreAllMocks keeps a once-impl a test queued but never
  // used; reset redirect so it cannot fire in the next test.
  vi.mocked(redirect).mockReset();
});
```

- [ ] **Step 3: Run the file's tests and check the diff, saved**

Run:

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice71fix/apps/web && { echo "# task-1-api-test  $(date -u +%Y-%m-%dT%H:%M:%SZ)  cmd: npx vitest run src/lib/api.test.ts (raw output in task-1-api-test.raw)"; npx vitest run src/lib/api.test.ts > ../../.superpowers/sdd/2026-10-14-slice71-restore-fix/task-1-api-test.raw 2>&1; echo "vitest exit $?"; sed 's/\x1b\[[0-9;]*m//g' ../../.superpowers/sdd/2026-10-14-slice71-restore-fix/task-1-api-test.raw | grep -E 'RUN +v|Tests +[0-9]|FAIL'; echo "## diff"; git diff --stat; git diff -U0 | grep -E '^[+-]' ; } > ../../.superpowers/sdd/2026-10-14-slice71-restore-fix/task-1-api-test.txt 2>&1; cat ../../.superpowers/sdd/2026-10-14-slice71-restore-fix/task-1-api-test.txt
```

Expected: `vitest exit 0`, `RUN  v5.0.4 …`, `Tests  28 passed (28)`, and no `FAIL` line. The diffstat shows `apps/web/src/lib/api.test.ts | 3 +++` and `1 file changed, 3 insertions(+)`. The `-U0` lines are exactly:

```
--- a/apps/web/src/lib/api.test.ts
+++ b/apps/web/src/lib/api.test.ts
+  // On vitest 5, restoreAllMocks keeps a once-impl a test queued but never
+  // used; reset redirect so it cannot fire in the next test.
+  vi.mocked(redirect).mockReset();
```

Any other result: stop and report BLOCKED; do not commit.

- [ ] **Step 4: Commit, gated on the check and the banned-word grep**

Run:

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice71fix && grep -qx 'vitest exit 0' .superpowers/sdd/2026-10-14-slice71-restore-fix/task-1-api-test.txt && git add apps/web/src/lib/api.test.ts && ! { git diff --cached -U0 | grep '^+' | grep -v -F 'Banned-word grep (must block the commit)' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1([^0-9]|$)|top spot|dominat|certain'; } && git commit -q -m "test(web): reset the redirect mock after each api test

On vitest 5, restoreAllMocks no longer drops a mockImplementationOnce
that a test queued but never used, and the default clearMocks keeps it
too, so it would fire in the next test. Reset the module-level redirect
mock in api.test.ts's afterEach.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git log --oneline -1 && git status --short && git diff --stat HEAD~1..HEAD
```

Expected: one new commit; `git status --short` prints nothing; the stat shows `apps/web/src/lib/api.test.ts | 3 +++`. The leading `grep -qx 'vitest exit 0'` refuses to stage anything unless Step 3 passed. If it or the banned-word grep stops the command, report BLOCKED with the output.

---

### Task 2: Run both local gates

**Files:**
- None modified. Read-only verification.

**Interfaces:**
- Consumes: the Task 1 commit on `slice71-restore-fix`.
- Produces: two gate output files and two pre-check files in W.

Save every output in W with shell redirection (`> file 2>&1`), never a heredoc. If pytest makes no progress for more than about 6 minutes (the gate normally takes 2 to 4), check the test database with `docker ps`; if it is down, stop and report BLOCKED. Do not kill processes.

- [ ] **Step 1: Pre-check, as its own command, saved**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && { echo "# precheck-before-backend-gate  $(date -u +%Y-%m-%dT%H:%M:%SZ)  slice71fix HEAD $(git -C /Users/vineet/Downloads/ADK/bsi-wt/slice71fix rev-parse --short HEAD)"; n=0; for p in $(pgrep -f 'bin/pytest|-m pytest'); do [ "$p" = "$$" ] && continue; c=$(lsof -p $p 2>/dev/null | awk '$4=="cwd"{print $NF}'); echo "pytest $p cwd $c"; case "$c" in /Users/vineet/Downloads/ADK/bsi-platform*|/Users/vineet/Downloads/ADK/bsi-wt/*|*/scratchpad/proof*|*/scratchpad/scratch*|*/scratchpad/plancheck*|*/scratchpad/fixproof*) n=1;; esac; done; [ $n = 0 ] && echo "no pytest of this repo running" || echo "WAIT"; } > /Users/vineet/Downloads/ADK/bsi-wt/slice71fix/.superpowers/sdd/2026-10-14-slice71-restore-fix/task-2-precheck-backend.txt; cat /Users/vineet/Downloads/ADK/bsi-wt/slice71fix/.superpowers/sdd/2026-10-14-slice71-restore-fix/task-2-precheck-backend.txt
```

Expected: the last line is `no pytest of this repo running`. A pytest whose cwd is `…/invoice-processing` does not block. If the last line is `WAIT`, wait about a minute and run the whole command again; never start pytest while it says `WAIT`.

- [ ] **Step 2: Backend gate, saved**

Run (the worktree has no `.venv` yet; `uv sync` creates it from the lock):

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice71fix && { echo "# task-2-backend-gate  $(date -u +%Y-%m-%dT%H:%M:%SZ)  HEAD $(git rev-parse --short HEAD)  pre-check: see task-2-precheck-backend.txt"; uv sync -q && uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; echo "gate exit $?"; } > .superpowers/sdd/2026-10-14-slice71-restore-fix/task-2-backend-gate.txt 2>&1; grep -E 'files already formatted|All checks passed|Success: no issues|^TOTAL|passed|gate exit' .superpowers/sdd/2026-10-14-slice71-restore-fix/task-2-backend-gate.txt; echo "warning hits: $(grep -c -i warning .superpowers/sdd/2026-10-14-slice71-restore-fix/task-2-backend-gate.txt)"
```

Expected, in order: `185 files already formatted`; `All checks passed!`; `Success: no issues found in 31 source files`; `TOTAL … 100%`; `1811 passed, 2 deselected in <time>`; `gate exit 0`; `warning hits: 0`.

- [ ] **Step 3: Pre-check again, saved**

Run the Step 1 command with both occurrences of `task-2-precheck-backend.txt` changed to `task-2-precheck-web.txt`, and the header word `backend` changed to `web`. Expected: `no pytest of this repo running`.

- [ ] **Step 4: Web gate, saved**

`node_modules` already holds Task 1's install.

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice71fix/apps/web && { echo "# task-2-web-gate  $(date -u +%Y-%m-%dT%H:%M:%SZ)  HEAD $(git rev-parse --short HEAD)  pre-check: see task-2-precheck-web.txt"; npm run gate; echo "gate exit $?"; } > ../../.superpowers/sdd/2026-10-14-slice71-restore-fix/task-2-web-gate.txt 2>&1; sed 's/\x1b\[[0-9;]*m//g' ../../.superpowers/sdd/2026-10-14-slice71-restore-fix/task-2-web-gate.txt | grep -E 'RUN +v|Test Files|Tests +[0-9]+|Compiled|gate exit|Next.js 15'
```

Expected: `RUN  v5.0.4 …`, `Test Files  9 passed (9)`, `Tests  93 passed (93)`, a `Next.js 15.5.27` banner line from the build, `✓ Compiled successfully`, and `gate exit 0`. The gate ends with `npm run gen:check`, so `gate exit 0` also means `gen:check` is clean.

- [ ] **Step 5: Confirm nothing changed**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice71fix && git status --short`
Expected: empty.

---

## Plan self-review

1. **Spec coverage:**
   - §4 (the edit, only api.test.ts, 93 tests) → Task 1 Steps 2 and 3, and Global Constraints.
   - §5's red, green and m3 runs are spec-stage proof outputs and are not repeated at execution. §5's planned gates → Task 2.
   - §6.3 (PR, CI, merge) is the controller's finishing step. §6.4 and §7 → Global Constraints.
2. **Placeholder scan:** none.
3. **Consistency:** Step 2's `new_string` produces the spec §4 diff. The plan check applied it to a fresh copy of main and compared the file byte for byte with the spec's proof copy (`fixproof`).
4. **Review Focus:** five lines, each pinned to a step.

**Departures from the spec:** none. Spec §5's red, green and m3 runs are proof made before this plan, with a scratch test that is not part of the change, and §5 plans only the two local gates at execution. Task 1 also runs the real change's file, which gives `28 passed (28)` as in spec §5's "Real change" row.

## Changes made during execution

- Task 1 ran as written (commit 38a54b1): `vitest exit 0`, `Tests  28 passed (28)`, and the committed file was byte-identical to the spec's proof copy; its review was clean.
- Task 2's first run was blocked: the test database container had exited (`Exited (255)`, cause unknown) and the backend gate errored on `Connection refused`. After the user ran `docker compose up -d db` and Postgres recovered, a fresh implementer re-ran Task 2 from Step 1: backend `1811 passed, 2 deselected`, web `Tests  93 passed (93)`.
- Task 2's review raised one Minor (the report's concern that Steps 3 and 4 ran together, which the file times disprove); the implementer appended a correction in fix round 1, and a scoped re-review found it addressed.
- The final review found nothing. PR 152 merged as df9f977.
