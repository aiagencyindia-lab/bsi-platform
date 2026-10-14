# Slice 70: next 15.5.27, sharp 0.35.5, source-map-js 1.2.2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Dependabot alerts 10 to 13 by moving `apps/web` to next 15.5.27, sharp 0.35.5 and source-map-js 1.2.2, and nothing else.

**Architecture:** Two npm commands in `apps/web/` change `package.json` (one line) and `package-lock.json` (38 entries). A lock-delta script, written into the git-ignored plan workspace from this plan, checks that only the allowed entries moved and that the target versions are met; `npm ls` and `npm audit --omit=dev` confirm the four advisories are gone and the postcss ones remain. Then both local gates. After the merge the controller checks the alerts read `fixed` (spec §5), which no task can do.

**Tech Stack:** npm 10.9.8, Node v22.23.0, Next.js 15.5.27; Python 3.13 (the repo's `.venv`) for the check scripts.

**Spec:** `docs/superpowers/specs/2026-10-14-slice70-security-patch-bumps-design.md`

## Global Constraints

- Branch `slice70`, worktree `/Users/vineet/Downloads/ADK/bsi-wt/slice70`, base main 108a82a. The shell cwd resets after every command: prefix each with `cd /Users/vineet/Downloads/ADK/bsi-wt/slice70 &&` (or `…/slice70/apps/web &&`).
- Change only `apps/web/package.json` and `apps/web/package-lock.json`, and only through the two commands `npm install next@15.5.27` and `npm update sharp source-map-js`, run in `apps/web/`. Never edit either file by hand (spec §4).
- Target versions: next 15.5.27, sharp 0.35.5, source-map-js 1.2.2; `node_modules/postcss` stays 8.4.31 (spec §4).
- If the lock-delta check FAILs (a target version differs, for example a newer sharp 0.35.x or source-map-js 1.2.x published since the spec, or any OTHER entry), stop and report BLOCKED; do not commit. The user decides (spec §4).
- Out of scope: postcss, next 16, vitest, tinypool, mako, and Dependabot PRs 140, 141, 144, 145; no repository settings (spec §7).
- Before any pytest run, the pre-check runs as its own command and its raw output is saved to a file (Task 2, Step 1 text). Two pytests of this repo deadlock on `bsi_test`.
- Every commit is gated on the banned-word grep (the exact command is in Task 1, Step 6); never bypass it by hand. The words are listed in `tests/unit/test_recommend_copy.py` (`FORBIDDEN`).
- No live checks against the app, no database migration, no worker, no model or DataForSEO spend. GitHub writes only by the controller: this slice's PR, its merge, and closing comments on PRs 139, 142, 146 (spec §6).
- Prettier is not in the gate; never run it. Never read, list, grep or source `.env`. No `rm`. No heredoc file writes. On a refused tool call, report BLOCKED.
- Commit trailer for implementer commits: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Registry drift: `npm update` takes the newest sharp 0.35.x and source-map-js 1.2.x; a release published after the spec changes the lockfile. Pinned by Task 1 Step 4 (the lock-delta target check FAILs and the task stops).
2. A transitive package outside the three moving with them (npm re-resolving something else). Pinned by Task 1 Step 4 (any changed entry outside the scoped allow-list is OTHER and FAILs).
3. A same-version package re-resolved to a different tarball. Pinned by Task 1 Step 4 (a changed `resolved` or `integrity` is OTHER and FAILs).
4. Next 15.5.27 breaking the app: build, typecheck, a server action, a route handler. Pinned by Task 2 Step 4 (the web gate: typecheck, lint, 93 tests, build, `gen:check`).
5. The postcss scope creeping in (for example `npm audit fix`). Pinned by Task 1 Step 4 (postcss must stay 8.4.31) and Step 5 (the audit must still list the four postcss advisories).

---

### Task 1: Apply the three bumps and check them

**Files:**
- Modify (by npm only): `apps/web/package.json`, `apps/web/package-lock.json`
- Create (git-ignored, plan workspace): `.superpowers/sdd/2026-10-14-slice70-security-patch-bumps/lockdelta70.py`, `lock-main.json`, and the saved outputs named below

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: one commit on `slice70` changing the two files; Task 2 runs the gates on it.

The plan workspace is `/Users/vineet/Downloads/ADK/bsi-wt/slice70/.superpowers/sdd/2026-10-14-slice70-security-patch-bumps/` (W below). Under subagent-driven development it already exists; under executing-plans create it first with `mkdir -p` on that path (it is git-ignored).

- [ ] **Step 1: Confirm the starting state and install**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice70 && git status --short && git rev-parse --short main && grep -n '"next"' apps/web/package.json`
Expected: no modified tracked files; `108a82a`; `"next": "^15.0.0",`.

Then: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice70/apps/web && npm ci > /dev/null 2>&1; echo "npm ci exit $?"; npm -v; node -v`
Expected: `npm ci exit 0`, `10.9.8`, `v22.23.0`.

- [ ] **Step 2: Write the lock-delta script and save main's lockfile**

Create `W/lockdelta70.py` with the Write tool, exactly:

```python
"""List every package-lock entry whose version changed, appeared or disappeared.

Usage: lockdelta70.py OLD_LOCK NEW_LOCK
Versions are compared for every entry (the root entry is skipped); an entry whose
version is unchanged but whose resolved or integrity changed is OTHER. A version
change is allowed for next, sharp, source-map-js, or any package
under @next/, @img/ or @emnapi/ (a scoped allow-list); anything else is OTHER.
Exits 1 if any OTHER entry exists, or if the three target versions are not met.
"""

import json
import sys

old = json.load(open(sys.argv[1]))["packages"]
new = json.load(open(sys.argv[2]))["packages"]

ALLOWED_NAMES = {"next", "sharp", "source-map-js"}
ALLOWED_SCOPES = ("@next/", "@img/", "@emnapi/")
TARGETS = {"node_modules/next": "15.5.27", "node_modules/sharp": "0.35.5",
           "node_modules/source-map-js": "1.2.2"}
KEEP = {"node_modules/postcss": "8.4.31"}


def name_of(path: str) -> str:
    return path.split("node_modules/")[-1]


def allowed(path: str) -> bool:
    n = name_of(path)
    return n in ALLOWED_NAMES or n.startswith(ALLOWED_SCOPES)


rows = []
for path in sorted(set(old) | set(new)):
    if path == "":
        continue
    a = old.get(path, {}).get("version")
    b = new.get(path, {}).get("version")
    if a != b:
        rows.append((path, a or "-", b or "-", "allowed" if allowed(path) else "OTHER"))
    elif any(old.get(path, {}).get(k) != new.get(path, {}).get(k)
             for k in ("resolved", "integrity")):
        # Same version but a different tarball: never allowed.
        rows.append((path, a or "-", b or "-", "OTHER (resolved/integrity changed)"))

for r in rows:
    print(" | ".join(r))
other = [r for r in rows if r[3].startswith("OTHER")]
print(f"changed entries: {len(rows)}; OTHER: {len(other)}")

ok = not other
for path, want in {**TARGETS, **KEEP}.items():
    got = new.get(path, {}).get("version")
    flag = "ok" if got == want else "MISMATCH"
    print(f"{path}: {got} (want {want}) {flag}")
    ok &= got == want
print("lockdelta", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
```

Then save main's lockfile: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice70 && git show main:apps/web/package-lock.json > .superpowers/sdd/2026-10-14-slice70-security-patch-bumps/lock-main.json && wc -c < .superpowers/sdd/2026-10-14-slice70-security-patch-bumps/lock-main.json`
Expected: a byte count over 200000.

- [ ] **Step 3: Run the two npm commands, saved**

Run:

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice70/apps/web && { echo "# task-1-patch  $(date -u +%Y-%m-%dT%H:%M:%SZ)  npm $(npm -v)  node $(node -v)"; npm install next@15.5.27 > ../../.superpowers/sdd/2026-10-14-slice70-security-patch-bumps/task-1-install.log 2>&1; echo "npm install next@15.5.27 exit $?"; npm update sharp source-map-js > ../../.superpowers/sdd/2026-10-14-slice70-security-patch-bumps/task-1-update.log 2>&1; echo "npm update sharp source-map-js exit $?"; } > ../../.superpowers/sdd/2026-10-14-slice70-security-patch-bumps/task-1-patch.txt; cat ../../.superpowers/sdd/2026-10-14-slice70-security-patch-bumps/task-1-patch.txt; cd /Users/vineet/Downloads/ADK/bsi-wt/slice70 && git diff --stat && git diff apps/web/package.json
```

Expected: both exit lines end `exit 0`; the stat shows `apps/web/package-lock.json | 322` and `apps/web/package.json | 2`, `2 files changed, 162 insertions(+), 162 deletions(-)`; the `package.json` diff changes exactly `"next": "^15.0.0",` to `"next": "^15.5.27",`.

- [ ] **Step 4: Run the lock-delta check, saved**

Run:

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice70/.superpowers/sdd/2026-10-14-slice70-security-patch-bumps && { echo "# task-1-lockdelta  $(date -u +%Y-%m-%dT%H:%M:%SZ)"; /Users/vineet/Downloads/ADK/bsi-platform/.venv/bin/python -I lockdelta70.py lock-main.json /Users/vineet/Downloads/ADK/bsi-wt/slice70/apps/web/package-lock.json; echo "lockdelta exit $?"; } > task-1-lockdelta.txt 2>&1; tail -7 task-1-lockdelta.txt
```

Expected, exactly:

```
changed entries: 38; OTHER: 0
node_modules/next: 15.5.27 (want 15.5.27) ok
node_modules/sharp: 0.35.5 (want 0.35.5) ok
node_modules/source-map-js: 1.2.2 (want 1.2.2) ok
node_modules/postcss: 8.4.31 (want 8.4.31) ok
lockdelta PASS
lockdelta exit 0
```

If it prints `lockdelta FAIL`, a `MISMATCH`, any `OTHER` row or a non-zero exit, stop and report BLOCKED with the whole file; do not commit.

- [ ] **Step 5: Confirm the versions and the advisories, saved**

Run:

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice70/apps/web && { echo "# task-1-npm-ls-and-audit  $(date -u +%Y-%m-%dT%H:%M:%SZ)"; npm ls next sharp source-map-js postcss --all 2>&1; echo "npm ls exit $?"; npm audit --omit=dev --json > ../../.superpowers/sdd/2026-10-14-slice70-security-patch-bumps/task-1-audit.json 2>/dev/null; echo "npm audit exit $? (non-zero is expected: the postcss advisories remain)"; echo "## advisories (npm audit --omit=dev)"; /Users/vineet/Downloads/ADK/bsi-platform/.venv/bin/python -I -c "import json,sys; a=json.load(open(sys.argv[1])); print('\n'.join(sorted({v2['url'].rsplit('/',1)[-1]+' '+n for n,v in a.get('vulnerabilities',{}).items() for v2 in v.get('via',[]) if isinstance(v2,dict) and v2.get('url')})))" ../../.superpowers/sdd/2026-10-14-slice70-security-patch-bumps/task-1-audit.json; } > ../../.superpowers/sdd/2026-10-14-slice70-security-patch-bumps/task-1-npm-ls-and-audit.txt 2>&1; cat ../../.superpowers/sdd/2026-10-14-slice70-security-patch-bumps/task-1-npm-ls-and-audit.txt
```

Expected: `npm ls` shows `next@15.5.27` with `postcss@8.4.31`, `source-map-js@1.2.2` and `sharp@0.35.5` under it, then `npm ls exit 0`; `npm audit exit 1` (npm audit exits non-zero whenever any advisory remains); the advisories section lists exactly these four lines and nothing else:

```
GHSA-6g55-p6wh-862q postcss
GHSA-fxqj-rqcc-2cmp postcss
GHSA-qx2v-qp2m-jg93 postcss
GHSA-r28c-9q8g-f849 postcss
```

(GHSA-68fv-2mgg-jv7q, GHSA-wq5f-xc86-pv6w, GHSA-4jqv-mc3x-m676 and GHSA-mcj8-r9mp-w47p must be absent.) Any other result: stop and report BLOCKED; do not commit.

- [ ] **Step 6: Commit, gated on the banned-word grep**

Run:

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice70 && git add apps/web/package.json apps/web/package-lock.json && ! { git diff --cached -U0 | grep '^+' | grep -v -F 'Banned-word grep (must block the commit)' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1([^0-9]|$)|top spot|dominat|certain'; } && git commit -q -m "build(web): next 15.5.27, sharp 0.35.5, source-map-js 1.2.2

npm install next@15.5.27 and npm update sharp source-map-js in
apps/web. Closes Dependabot alerts 10 to 13; postcss stays 8.4.31.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git log --oneline -1 && git status --short && git diff --stat main..HEAD -- apps/
```

Expected: one new commit; `git status --short` prints nothing; the stat limited to `apps/` shows the two files with 162 insertions and 162 deletions. If the banned-word grep blocks the commit, report BLOCKED with its output; the lockfile's integrity hashes are base64 and could in principle contain a banned substring.
  - Note (2026-10-14, after slice 70, PR #148): the commit's message was later reworded, at the user's choice, to "Moves each package to the patched version of Dependabot alerts 10 to 13 (confirmed after merge)"; the commit became f89087a with the same tree (docs/findings-slice70.md).

---

### Task 2: Run both local gates

**Files:**
- None modified. Read-only verification.

**Interfaces:**
- Consumes: the Task 1 commit on `slice70`.
- Produces: two gate output files and two pre-check files in the plan workspace (W).

Save every output in W with shell redirection (`> file 2>&1`), never a heredoc. If pytest makes no progress for more than about 6 minutes (the gate normally takes 2 to 4), check the test database with `docker ps`; if it is down, stop and report BLOCKED. Do not kill processes.

- [ ] **Step 1: Pre-check, as its own command, saved**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && { echo "# precheck-before-backend-gate  $(date -u +%Y-%m-%dT%H:%M:%SZ)  slice70 HEAD $(git -C /Users/vineet/Downloads/ADK/bsi-wt/slice70 rev-parse --short HEAD)"; n=0; for p in $(pgrep -f 'bin/pytest|-m pytest'); do [ "$p" = "$$" ] && continue; c=$(lsof -p $p 2>/dev/null | awk '$4=="cwd"{print $NF}'); echo "pytest $p cwd $c"; case "$c" in /Users/vineet/Downloads/ADK/bsi-platform*|/Users/vineet/Downloads/ADK/bsi-wt/*|*/scratchpad/proof*|*/scratchpad/scratch*|*/scratchpad/plancheck*) n=1;; esac; done; [ $n = 0 ] && echo "no pytest of this repo running" || echo "WAIT"; } > /Users/vineet/Downloads/ADK/bsi-wt/slice70/.superpowers/sdd/2026-10-14-slice70-security-patch-bumps/task-2-precheck-backend.txt; cat /Users/vineet/Downloads/ADK/bsi-wt/slice70/.superpowers/sdd/2026-10-14-slice70-security-patch-bumps/task-2-precheck-backend.txt
```

Expected: the last line is `no pytest of this repo running` (a pytest with cwd `…/invoice-processing` does not block). If it is `WAIT`, wait about a minute and run the whole command again; never start pytest while it says `WAIT`.

- [ ] **Step 2: Backend gate, saved**

Run (the worktree has no `.venv` yet; `uv sync` creates it from the lock):

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice70 && { echo "# task-2-backend-gate  $(date -u +%Y-%m-%dT%H:%M:%SZ)  HEAD $(git rev-parse --short HEAD)  pre-check: see task-2-precheck-backend.txt"; uv sync -q && uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; echo "gate exit $?"; } > .superpowers/sdd/2026-10-14-slice70-security-patch-bumps/task-2-backend-gate.txt 2>&1; grep -E 'files already formatted|All checks passed|Success: no issues|^TOTAL|passed|gate exit' .superpowers/sdd/2026-10-14-slice70-security-patch-bumps/task-2-backend-gate.txt; echo "warning hits: $(grep -c -i warning .superpowers/sdd/2026-10-14-slice70-security-patch-bumps/task-2-backend-gate.txt)"
```

Expected, in order: `185 files already formatted`; `All checks passed!`; `Success: no issues found in 31 source files`; `TOTAL … 100%`; `1811 passed, 2 deselected in <time>`; `gate exit 0`; `warning hits: 0`.

- [ ] **Step 3: Pre-check again, saved**

Run the Step 1 command with both occurrences of `task-2-precheck-backend.txt` changed to `task-2-precheck-web.txt` and the header word `backend` changed to `web`. Expected: `no pytest of this repo running`.

- [ ] **Step 4: Web gate, saved**

`node_modules` already holds the Task 1 install.

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice70/apps/web && { echo "# task-2-web-gate  $(date -u +%Y-%m-%dT%H:%M:%SZ)  HEAD $(git rev-parse --short HEAD)  pre-check: see task-2-precheck-web.txt"; npm run gate; echo "gate exit $?"; } > ../../.superpowers/sdd/2026-10-14-slice70-security-patch-bumps/task-2-web-gate.txt 2>&1; sed 's/\x1b\[[0-9;]*m//g' ../../.superpowers/sdd/2026-10-14-slice70-security-patch-bumps/task-2-web-gate.txt | grep -E 'Tests +[0-9]+ passed|Compiled|gate exit|Next.js 15'
```

Expected: a `Next.js 15.5.27` banner line from the build, `Tests  93 passed (93)`, `✓ Compiled successfully`, `gate exit 0`.

- [ ] **Step 5: Confirm nothing changed**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice70 && git status --short`
Expected: empty.

---

## Plan self-review

1. **Spec coverage:** §4 (the two commands, the `package.json` change, the 38-entry delta, postcss unchanged, the drift stop rule) → Task 1 Steps 3 and 4 and Global Constraints; §5's pre-PR checks (npm ls, audit, lock delta, both gates) → Task 1 Steps 4 and 5 and Task 2; §5's reproducibility, mutations and Dependabot comparison are spec-stage proof outputs, not repeated at execution; §5's after-merge criterion and §6.4, §6.5 (the PR, CI, merge, alert states, closing PRs 139, 142, 146) are the controller's finishing steps; §6.6 and §7 → Global Constraints; §8 → the findings doc.
2. **Placeholder scan:** none.
3. **Type consistency:** the script in Step 2 is byte-identical to the spec-stage `lockdelta70.py` that produced `04-lockdelta.txt`; its target and keep values match spec §4.
4. **Review Focus:** five lines, each pinned to a step.

**Departures from the spec:** two. First, spec §6.3 says the §5 checks run "on the committed branch"; Steps 4 and 5 run them on the working tree just before Step 6 commits exactly those two files, so the commit records the bytes the checks read; Task 2's gates, the controller's own gate run before the PR (the process's finishing step) and CI on the PR then run on the commit itself. Second, the spec's lock-delta script lived in the session scratchpad; this plan embeds the same script in Task 1 Step 2 so the implementer writes it into the git-ignored plan workspace (the scratchpad was wiped once in slice 68). The plan check ran the plan's commands on a fresh copy of main and compared the resulting `package.json` and `package-lock.json` byte for byte with the spec's scratch copy (`scratch70`); its output is proof output `11-plancheck70.txt`, and the findings doc quotes it.

## Changes made during execution

- Task 1 ran as written (commit 20646c2): both npm commands exited 0, the lock delta passed with 38 entries, and the committed files were byte-identical to the spec's scratch copy; its review was clean.
- Task 2 ran as written; its review raised two Minors: the Next.js `serverActions` notice (not a defect, R1) and no 15.5.25 build to compare against, which the controller closed by comparing a saved 15.5.25 build of the same app code (R2: same 24 routes and render types; sizes differ only).
- The final review asked that the commit message not claim the alerts closed before the merge; at the user's choice the controller reworded it, and 20646c2 became f89087a with the same tree.
- PR 148 merged as 136e5dd; alerts 10 to 13 read `fixed` 7 seconds later, and Dependabot closed PRs 139, 142 and 146 itself.
