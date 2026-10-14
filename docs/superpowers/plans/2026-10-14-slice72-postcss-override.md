# Slice 72: Next's postcss overridden to 8.5.28 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a scoped npm `overrides` entry that moves Next's pinned postcss from 8.4.31 to 8.5.28 in `apps/web`. This targets Dependabot alerts 1 to 4. Nothing else changes.

**Architecture:** Two npm commands in `apps/web/` change `package.json` (a 5-line `overrides` block) and `package-lock.json` (two entries). A lock-delta script, written from this plan into the git-ignored plan workspace, checks the lock's SHA-256 against the proof and every entry against a named allow-list. `npm ls`, `npm audit` and a `package.json` diff check confirm the result. Then both local gates run. After the merge the controller checks that the alerts read `fixed` (spec §5), which no task can do.

**Tech Stack:** npm 10.9.8, Node v22.23.0, Next.js 15.5.27, postcss 8.5.28; Python 3.13 (the repo's `.venv`) for the check script.

**Spec:** `docs/superpowers/specs/2026-10-14-slice72-postcss-override-design.md`

## Global Constraints

- **Branch and base.** Branch `slice72-postcss-override`, worktree `/Users/vineet/Downloads/ADK/bsi-wt/slice72`, base main 52aac7e.
- **Working directory.** The shell cwd resets after every command, so prefix each with `cd /Users/vineet/Downloads/ADK/bsi-wt/slice72 &&` (or `…/slice72/apps/web &&`). The exceptions are Task 1 Step 4, which starts in the plan workspace W, and Task 2 Steps 1 and 3, which start in `/Users/vineet/Downloads/ADK/bsi-platform`.
- **What may change.** Only `apps/web/package.json` and `apps/web/package-lock.json`, and only through `npm ci` followed by `npm pkg set overrides.next.postcss=8.5.28` and `npm install --no-fund`, run in `apps/web/`. Never edit either file by hand. No source file changes (spec §4).
- **Target state** (spec §4):
  - Next's postcss is 8.5.28.
  - `node_modules/next` stays 15.5.27.
  - The root entry, `node_modules/next`, every `node_modules/@next/*` entry and `node_modules/vite` are byte-identical to main's.
  - No postcss entry is below 8.5.23.
- **Lock hash.** The patched lock's SHA-256 must be `14238de8f0184d6e11aa66e9bbae6f228f418085959c3fdc6a0450044d4acdd4` (spec §4). If `lockdelta72.py` exits 1 for any reason, stop and report BLOCKED; do not commit. The user decides.
- **Out of scope** (spec §7): Next 16, mako, the braces chain, postcss 8.5.30 or a range, and vite's own postcss. No repository settings.
- **Pytest pre-check.** Before any pytest run, the pre-check runs as its own command and its raw output is saved to a file (Task 2 Step 1 text). Two pytests of this repo deadlock on `bsi_test`.
- **Banned words.** Every commit is gated on the banned-word grep; the exact command is in Task 1 Step 6. Never bypass it by hand. The words are listed in `tests/unit/test_recommend_copy.py` (`FORBIDDEN`).
- **No spend, no outside writes.** No live checks against the app, no database migration, no worker, no model or DataForSEO spend. GitHub writes are made only by the controller: this slice's PRs and their merges.
- **Tool rules.** Prettier is not in the gate; never run it. Never read, list, grep or source `.env`. No `rm`. No heredoc file writes. On a refused tool call, report BLOCKED.
- **Exit codes** are captured from the command itself: save raw output to a file, echo the exit code, then filter. Never take an exit code after a pipe.
- **Commit trailer** for implementer commits: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Registry drift.** postcss 8.5.28's own dependencies are ranges, so a release published after the proof could change the lock. Pinned by Task 1 Step 4: the SHA-256 check prints `OTHER sha256` and the task stops.
2. **Next or a `@next/*` binary moving with the override.** Pinned by Task 1 Step 4 (`FROZEN-OK 'node_modules/next' 15.5.27`, and any `@next/*` change prints `OTHER frozen-changed`).
3. **npm ignoring the scoped override,** leaving Next on 8.4.31. Pinned by Task 1 Step 4 (`POSTCSS-OK` for both copies) and Step 5 (`npm ls` shows `postcss@8.5.28 overridden` under `next@15.5.27 overridden`; the audit has zero hits for the four advisories).
4. **The build or tests breaking under the newer postcss.** Pinned by Task 2 Step 4: the web gate runs typecheck, lint, 93 tests, build and `gen:check`.
5. **`package.json` differing from the reviewed diff,** for example a different key order or version. Pinned by Task 1 Step 5: the `git diff -- apps/web/package.json` added lines must be exactly the six shown.

---

### Task 1: Apply the override and check it

**Files:**
- Modify (by npm only): `apps/web/package.json`, `apps/web/package-lock.json`
- Create (git-ignored, in the plan workspace): `.superpowers/sdd/2026-10-14-slice72-postcss-override/lockdelta72.py`, `lock-main.json`, and the saved outputs named below

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: one commit on `slice72-postcss-override` changing the two files. Task 2 runs the gates on it.

The plan workspace is `/Users/vineet/Downloads/ADK/bsi-wt/slice72/.superpowers/sdd/2026-10-14-slice72-postcss-override/` (W below). Under subagent-driven development the controller creates it before dispatching Task 1. Under executing-plans, create it first with `mkdir -p` on that path; it is git-ignored.

- [ ] **Step 1: Confirm the starting state and install main's tree**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice72 && git status --short && git merge-base --is-ancestor 52aac7e HEAD && echo "base ok" && grep -c '"overrides"' apps/web/package.json`
Expected: no modified tracked files; `base ok`; `0`.

Then: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice72/apps/web && npm ci --no-audit --no-fund > /dev/null 2>&1; echo "npm ci exit $?"; npm -v; node -v`
Expected: `npm ci exit 0`, `10.9.8`, `v22.23.0`.

- [ ] **Step 2: Write the lock-delta script and save main's lockfile**

Create `W/lockdelta72.py` with the Write tool, exactly:

```python
"""Slice 72 lock-delta check: main lock vs patched lock (exit 1 on any surprise)."""

import hashlib
import json
import sys

ADDED = {"node_modules/next/node_modules/postcss": "8.5.28"}
REMOVED = {"node_modules/postcss": "8.4.31"}
CHANGED: dict[str, tuple[str, str]] = {}
FROZEN_EXACT = ("", "node_modules/next", "node_modules/vite")
FROZEN_PREFIX = "node_modules/@next/"
POSTCSS_FLOOR = (8, 5, 23)
PROOF_SHA256 = "14238de8f0184d6e11aa66e9bbae6f228f418085959c3fdc6a0450044d4acdd4"

A = json.load(open(sys.argv[1]))
B = json.load(open(sys.argv[2]))
a, b = A["packages"], B["packages"]
ok = bad = 0


def other(msg):
    global bad
    bad += 1
    print("OTHER", msg)


sha = hashlib.sha256(open(sys.argv[2], "rb").read()).hexdigest()
if sha == PROOF_SHA256:
    print("SHA256-OK", sha)
else:
    other(f"sha256 {sha} != proof {PROOF_SHA256}")

top = [k for k in set(A) | set(B) if k != "packages" and A.get(k) != B.get(k)]
if top:
    other(f"top-level keys changed {sorted(top)}")

for k in sorted(set(a) | set(b)):
    va, vb = a.get(k), b.get(k)
    frozen = k in FROZEN_EXACT or k.startswith(FROZEN_PREFIX)
    if va == vb:
        if k in FROZEN_EXACT:
            print("FROZEN-OK", repr(k), (va or {}).get("version"))
        continue
    if frozen:
        other(f"frozen-changed {k!r}")
    elif vb is None:
        good = REMOVED.get(k) == va.get("version")
        ok += good
        print("OK   " if good else "OTHER", "removed", repr(k), va.get("version"))
        bad += not good
    elif va is None:
        good = ADDED.get(k) == vb.get("version")
        ok += good
        print("OK   " if good else "OTHER", "added", repr(k), vb.get("version"))
        bad += not good
    else:
        vers = (va.get("version"), vb.get("version"))
        good = vers[0] != vers[1] and CHANGED.get(k) == vers
        ok += good
        print("OK   " if good else "OTHER", "changed", repr(k), vers)
        bad += not good

for k, v in b.items():
    if k == "node_modules/postcss" or k.endswith("/node_modules/postcss"):
        ver = tuple(int(x) for x in v["version"].split(".")[:3])
        if ver < POSTCSS_FLOOR:
            other(f"postcss below 8.5.23 at {k!r}: {v['version']}")
        else:
            print("POSTCSS-OK", repr(k), v["version"])

expected = len(ADDED) + len(REMOVED) + len(CHANGED)
if ok != expected:
    other(f"expected {expected} OK rows, got {ok}")
print(f"ok={ok} other={bad}")
sys.exit(1 if bad else 0)
```

Then save main's lockfile: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice72 && git show 52aac7e:apps/web/package-lock.json > .superpowers/sdd/2026-10-14-slice72-postcss-override/lock-main.json && shasum -a 256 .superpowers/sdd/2026-10-14-slice72-postcss-override/lock-main.json`
Expected: `9702766ff08ab3b34fbcc3657a0e0c8ce499821dc96766e1094b793aef1e6f99`.

- [ ] **Step 3: Run the two npm commands, saved**

Run:

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice72/apps/web && { echo "# task-1-patch  $(date -u +%Y-%m-%dT%H:%M:%SZ)  npm $(npm -v)  node $(node -v)  cmds: npm pkg set overrides.next.postcss=8.5.28 ; npm install --no-fund"; npm pkg set overrides.next.postcss=8.5.28; echo "npm pkg set exit $?"; npm install --no-fund > ../../.superpowers/sdd/2026-10-14-slice72-postcss-override/task-1-install.raw 2>&1; echo "npm install exit $?"; grep -E 'added|removed|changed' ../../.superpowers/sdd/2026-10-14-slice72-postcss-override/task-1-install.raw; } > ../../.superpowers/sdd/2026-10-14-slice72-postcss-override/task-1-patch.txt 2>&1; cat ../../.superpowers/sdd/2026-10-14-slice72-postcss-override/task-1-patch.txt; cd /Users/vineet/Downloads/ADK/bsi-wt/slice72 && git diff --stat
```

Expected:
- `npm pkg set exit 0` and `npm install exit 0`.
- A line starting `added 1 package, removed 1 package`.
- The stat shows `apps/web/package-lock.json | 56` and `apps/web/package.json | 5`, `2 files changed, 33 insertions(+), 28 deletions(-)`.

- [ ] **Step 4: Run the lock-delta check, saved**

Run:

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice72/.superpowers/sdd/2026-10-14-slice72-postcss-override && { echo "# task-1-lockdelta  $(date -u +%Y-%m-%dT%H:%M:%SZ)  cmd: python -I lockdelta72.py lock-main.json <patched lock>"; /Users/vineet/Downloads/ADK/bsi-platform/.venv/bin/python -I lockdelta72.py lock-main.json /Users/vineet/Downloads/ADK/bsi-wt/slice72/apps/web/package-lock.json; echo "lockdelta exit $?"; } > task-1-lockdelta.txt 2>&1; cat task-1-lockdelta.txt
```

Expected, exactly, after the header line:

```
SHA256-OK 14238de8f0184d6e11aa66e9bbae6f228f418085959c3fdc6a0450044d4acdd4
FROZEN-OK '' None
FROZEN-OK 'node_modules/next' 15.5.27
OK    added 'node_modules/next/node_modules/postcss' 8.5.28
OK    removed 'node_modules/postcss' 8.4.31
FROZEN-OK 'node_modules/vite' 7.3.6
POSTCSS-OK 'node_modules/next/node_modules/postcss' 8.5.28
POSTCSS-OK 'node_modules/vite/node_modules/postcss' 8.5.28
ok=2 other=0
lockdelta exit 0
```

If it prints any `OTHER` line or a non-zero exit, stop and report BLOCKED with the whole file; do not commit.

- [ ] **Step 5: Confirm the tree, the advisories and the package.json diff, saved**

Run:

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice72/apps/web && W=../../.superpowers/sdd/2026-10-14-slice72-postcss-override && { echo "# task-1-checks  $(date -u +%Y-%m-%dT%H:%M:%SZ)"; npm ls postcss next vite --all > $W/task-1-npm-ls.raw 2>&1; echo "npm ls exit $?"; grep -E 'next@|postcss@|vite@7.3.6$' $W/task-1-npm-ls.raw; npm audit --json > $W/task-1-audit.json 2>/dev/null; echo "npm audit exit $? (non-zero is expected: the braces-chain entries remain)"; /Users/vineet/Downloads/ADK/bsi-platform/.venv/bin/python -I -c "import json,sys; d=json.load(open(sys.argv[1])); print('vulnerable packages:', sorted(d['vulnerabilities'])); raw=open(sys.argv[1]).read(); print('target GHSA hits:', sum(raw.count(t) for t in ['GHSA-qx2v-qp2m-jg93','GHSA-6g55-p6wh-862q','GHSA-r28c-9q8g-f849','GHSA-fxqj-rqcc-2cmp']))" $W/task-1-audit.json; echo "## package.json added lines"; git diff -- package.json > $W/task-1-package-json.diff; echo "git diff exit $?"; grep '^+' $W/task-1-package-json.diff; } > $W/task-1-checks.txt 2>&1; cat $W/task-1-checks.txt
```

Expected:
- `npm ls exit 0`. The ls lines include `+-- next@15.5.27 overridden` with `` | `-- postcss@8.5.28 overridden `` under it, and `+-- vite@7.3.6` with `` | `-- postcss@8.5.28 `` under it. No `postcss@8.4.31` appears.
- `npm audit exit 1`.
- `vulnerable packages: ['@next/eslint-plugin-next', 'braces', 'eslint-config-next', 'fast-glob', 'micromatch']`.
- `target GHSA hits: 0`.
- `git diff exit 0`. The added lines are exactly:

```
+++ b/apps/web/package.json
+  },
+  "overrides": {
+    "next": {
+      "postcss": "8.5.28"
+    }
```

Any other result: stop and report BLOCKED; do not commit.

- [ ] **Step 6: Commit, gated on the lock check and the banned-word grep**

Run:

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice72 && grep -qx 'lockdelta exit 0' .superpowers/sdd/2026-10-14-slice72-postcss-override/task-1-lockdelta.txt && git add apps/web/package.json apps/web/package-lock.json && ! { git diff --cached -U0 | grep '^+' | grep -v -F 'Banned-word grep (must block the commit)' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1([^0-9]|$)|top spot|dominat|certain'; } && git commit -q -m "build(web): override Next's postcss to 8.5.28

npm pkg set overrides.next.postcss=8.5.28 and npm install in apps/web.
Moves the postcss copy Next 15.5.27 pins (8.4.31) to 8.5.28, the
package of Dependabot alerts 1 to 4 (their state is checked after
merge). Next stays 15.5.27; the override goes when Next moves to
16.3 or later.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git log --oneline -1 && git status --short && git diff --stat HEAD~1..HEAD
```

Expected:
- One new commit.
- `git status --short` prints nothing.
- The stat shows the two files with 33 insertions and 28 deletions.

The leading `grep -qx 'lockdelta exit 0'` refuses to stage anything unless Step 4 passed. If it, or the banned-word grep, stops the command, report BLOCKED with the output. The lockfile's integrity hashes are base64 and could in principle contain a banned substring.

---

### Task 2: Run both local gates

**Files:**
- None modified. Read-only verification.

**Interfaces:**
- Consumes: the Task 1 commit on `slice72-postcss-override`.
- Produces: two gate output files and two pre-check files in W.

Save every output in W with shell redirection (`> file 2>&1`), never a heredoc. If pytest makes no progress for more than about 6 minutes (the gate normally takes 2 to 4), check the test database with `docker ps`. If it is down, stop and report BLOCKED. Do not kill processes.

- [ ] **Step 1: Pre-check, as its own command, saved**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && { echo "# precheck-before-backend-gate  $(date -u +%Y-%m-%dT%H:%M:%SZ)  slice72 HEAD $(git -C /Users/vineet/Downloads/ADK/bsi-wt/slice72 rev-parse --short HEAD)"; n=0; for p in $(pgrep -f 'bin/pytest|-m pytest'); do [ "$p" = "$$" ] && continue; c=$(lsof -p $p 2>/dev/null | awk '$4=="cwd"{print $NF}'); echo "pytest $p cwd $c"; case "$c" in /Users/vineet/Downloads/ADK/bsi-platform*|/Users/vineet/Downloads/ADK/bsi-wt/*|*/scratchpad/proof*|*/scratchpad/scratch*|*/scratchpad/plancheck*|*/scratchpad/fixproof*) n=1;; esac; done; [ $n = 0 ] && echo "no pytest of this repo running" || echo "WAIT"; } > /Users/vineet/Downloads/ADK/bsi-wt/slice72/.superpowers/sdd/2026-10-14-slice72-postcss-override/task-2-precheck-backend.txt; cat /Users/vineet/Downloads/ADK/bsi-wt/slice72/.superpowers/sdd/2026-10-14-slice72-postcss-override/task-2-precheck-backend.txt
```

Expected: the last line is `no pytest of this repo running`. A pytest whose cwd is `…/invoice-processing` does not block. If it is `WAIT`, wait about a minute and run the whole command again; never start pytest while it says `WAIT`.

- [ ] **Step 2: Backend gate, saved**

Run (the worktree has no `.venv` yet; `uv sync` creates it from the lock):

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice72 && { echo "# task-2-backend-gate  $(date -u +%Y-%m-%dT%H:%M:%SZ)  HEAD $(git rev-parse --short HEAD)  pre-check: see task-2-precheck-backend.txt"; uv sync -q && uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; echo "gate exit $?"; } > .superpowers/sdd/2026-10-14-slice72-postcss-override/task-2-backend-gate.txt 2>&1; grep -E 'files already formatted|All checks passed|Success: no issues|^TOTAL|passed|gate exit' .superpowers/sdd/2026-10-14-slice72-postcss-override/task-2-backend-gate.txt; echo "warning hits: $(grep -c -i warning .superpowers/sdd/2026-10-14-slice72-postcss-override/task-2-backend-gate.txt)"
```

Expected, in order: `185 files already formatted`; `All checks passed!`; `Success: no issues found in 31 source files`; `TOTAL … 100%`; `1811 passed, 2 deselected in <time>`; `gate exit 0`; `warning hits: 0`.

- [ ] **Step 3: Pre-check again, saved**

Run the Step 1 command with both occurrences of `task-2-precheck-backend.txt` changed to `task-2-precheck-web.txt`, and the header word `backend` changed to `web`. Expected: `no pytest of this repo running`.

- [ ] **Step 4: Web gate, saved**

`node_modules` already holds the Task 1 install.

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice72/apps/web && { echo "# task-2-web-gate  $(date -u +%Y-%m-%dT%H:%M:%SZ)  HEAD $(git rev-parse --short HEAD)  pre-check: see task-2-precheck-web.txt"; npm run gate; echo "gate exit $?"; } > ../../.superpowers/sdd/2026-10-14-slice72-postcss-override/task-2-web-gate.txt 2>&1; sed 's/\x1b\[[0-9;]*m//g' ../../.superpowers/sdd/2026-10-14-slice72-postcss-override/task-2-web-gate.txt | grep -E 'RUN +v|Test Files|Tests +[0-9]+|Compiled|gate exit|Next.js 15'
```

Expected: `RUN  v5.0.4 …`, `Test Files  9 passed (9)`, `Tests  93 passed (93)`, a `Next.js 15.5.27` banner line from the build, `✓ Compiled successfully`, and `gate exit 0`. The gate ends with `npm run gen:check`, so `gate exit 0` also means `gen:check` is clean.

- [ ] **Step 5: Confirm nothing changed**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice72 && git status --short`
Expected: empty.

---

## Plan self-review

1. **Spec coverage.**
   - §4 (`npm ci`, the two commands, the `package.json` change, the two-entry delta, the frozen entries, the postcss floor, the SHA-256 stop rule) → Task 1 Steps 1 to 5 and Global Constraints.
   - §5's pre-PR checks (`npm ls`, `npm audit`, the lock check, both gates) → Task 1 Steps 4 and 5, and Task 2.
   - §5's reproducibility runs, tamper mutants, floor mutant and CSS comparison are spec-stage proof outputs and are not repeated at execution.
   - §6.3 (`npm ls`, `npm audit`, `lockdelta72.py`, the `package.json` diff) → Task 1 Steps 4 and 5.
   - §6.4 and §6.5 (the PR, CI, merge, alert states) are the controller's finishing steps. §6.6 and §7 → Global Constraints.
2. **Placeholder scan:** none.
3. **Consistency:** the script in Task 1 Step 2 is byte-identical to the spec-stage `lockdelta72.py` that produced `04-lockdelta.txt`. Step 4's Expected is that file's output after its header.
4. **Review Focus:** five lines, each pinned to a step.

**Departures from the spec:** one. Spec §6.3 says the §5 checks run "on the branch". Task 1 Steps 4 and 5 run them on the working tree just before Step 6 commits exactly those two files, so the commit records the bytes the checks read. Task 2's gates, the controller's own gate run before the PR, and CI on the PR then run on the commit itself.

The plan check ran Task 1's own blocks from the committed plan on a fresh copy of main:
- Step 1's `npm ci` line;
- Step 2's script and lock save;
- Steps 3 to 5.

It did not run Step 1's state check, Step 6, or Task 2. It then compared the resulting `package.json` and `package-lock.json` byte for byte with the spec's proof copy (`scratch72-proof`). Its output, headed with the plan file's SHA-256, is proof output `14-plancheck72.txt`, and the findings doc quotes its result lines.

## Changes made during execution
