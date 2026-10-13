# Slice 68: CI Actions Bump — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The CI log of `.github/workflows/ci.yml` has no Node.js deprecation lines and no "Node.js 20 is deprecated" annotation, with the gates' results unchanged.

**Architecture:** Three `uses:` values in the one workflow file move to action releases built for Node 24: `actions/checkout@v7`, `actions/setup-node@v7`, `astral-sh/setup-uv@v10.3.0` (exact tag, because setup-uv publishes no major tags past v7). A comment above the setup-uv line says why it is pinned differently. Nothing else in the workflow changes. The proof is the slice's own PR's CI run (spec §3 decision 1), checked by the controller before merge with the commands in spec §5.

**Tech Stack:** GitHub Actions on `ubuntu-latest`; `actions/checkout` v4 → v7, `actions/setup-node` v4 → v7, `astral-sh/setup-uv` v5 → v10.3.0. No Python, TypeScript or dependency changes.

**Spec:** `docs/superpowers/specs/2026-10-13-slice68-ci-actions-bump-design.md`

## Global Constraints

- Branch `slice68`, worktree `/Users/vineet/Downloads/ADK/bsi-wt/slice68`, base main f6b9964. The shell cwd resets after every command: prefix each with `cd /Users/vineet/Downloads/ADK/bsi-wt/slice68 &&`.
- Edit only `.github/workflows/ci.yml`: three `uses:` values and one comment line. No `with:` block, `run:` step, trigger, service or step order changes (spec §4, §7).
- Pins are exactly `actions/checkout@v7`, `actions/setup-node@v7`, `astral-sh/setup-uv@v10.3.0`. No commit-SHA pins (spec §7).
- No `workflow_dispatch` or other trigger is added (spec §7).
- Before any pytest run, the pre-check runs as its own command and its raw output is saved to a file (Task 2, Step 1 text). Two pytests of this repo deadlock on `bsi_test`.
- Every commit is gated on the banned-word grep (the exact command is in Task 1, Step 4); never bypass it by hand. The words are listed in `tests/unit/test_recommend_copy.py` (`FORBIDDEN`).
- No live checks, no database migration, no worker, no model or DataForSEO spend. GitHub API use is read-only apart from the PR the controller opens (spec §6.4).
- Prettier is not in the gate; never run it. Never read, list, grep or source `.env`. No `rm`. No heredoc file writes. On a refused tool call, report BLOCKED.
- Commit trailer for implementer commits: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A typo in a `uses:` value (`v10.3.0` versus a non-existent `v10`) fails the job at its first step with "Unable to resolve action". Pinned by Task 1, Step 2's byte-for-byte replace blocks and Step 3's `git diff` check against the spec's §4 hunks; observed on the PR's run (spec §5 criterion 3).
2. setup-uv v10's `enable-cache: auto` would disable caching on some events; the workflow keeps `enable-cache: true` explicitly. Pinned by Task 1, Step 3 (the `with:` lines are unchanged in the diff).
3. setup-node v5+ auto-caches when `package.json` has a `packageManager` field; `apps/web/package.json` has none, and the workflow's `cache: npm` with `cache-dependency-path` stays. Pinned by Task 1, Step 3 (unchanged `with:` block) and by the PR's run passing `npm ci` (spec §5 criterion 4).
4. A YAML indentation slip in the inserted comment line breaks the workflow file. Pinned by Task 1, Step 2's replace block (the comment carries the same six-space indent as the `- uses:` line it precedes) and Step 3's diff check.
5. The local gates do not exercise the workflow at all, so a green local run proves only that nothing else changed. Pinned by Task 2 (both gates unchanged) and stated plainly in spec §5; the PR's run is the only observation of the change itself.

---

### Task 1: Bump the three action pins

**Files:**
- Modify: `.github/workflows/ci.yml:27`, `:40`, `:53` (line numbers as at main f6b9964)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: one commit on `slice68` whose diff equals spec §4; Task 2 runs the gates on it and the controller opens the PR from it.

- [ ] **Step 1: Confirm the starting state**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice68 && git status --short && grep -n -E '^\s*- uses:' .github/workflows/ci.yml`
Expected: no modified tracked files, and exactly these three lines:

```
27:      - uses: actions/checkout@v4
40:      - uses: astral-sh/setup-uv@v5
53:      - uses: actions/setup-node@v4
```

- [ ] **Step 2: Apply the three replace blocks**

Each block replaces exactly one occurrence in `.github/workflows/ci.yml`. Apply with the Edit tool (old string → new string), byte for byte, including the six leading spaces.

Block 1 — replace:

```yaml
      - uses: actions/checkout@v4
```

with:

```yaml
      - uses: actions/checkout@v7
```

Block 2 — replace:

```yaml
      - uses: astral-sh/setup-uv@v5
```

with:

```yaml
      # setup-uv publishes no major tags past v7; pin the exact release.
      - uses: astral-sh/setup-uv@v10.3.0
```

Block 3 — replace:

```yaml
      - uses: actions/setup-node@v4
```

with:

```yaml
      - uses: actions/setup-node@v7
```

- [ ] **Step 3: Check the diff is exactly the spec's**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice68 && git diff --stat && git diff -U0 .github/workflows/ci.yml | grep -E '^[-+][^-+]'`
Expected: `1 file changed, 4 insertions(+), 3 deletions(-)` for `.github/workflows/ci.yml`, and exactly these changed lines, in this order:

```
-      - uses: actions/checkout@v4
+      - uses: actions/checkout@v7
-      - uses: astral-sh/setup-uv@v5
+      # setup-uv publishes no major tags past v7; pin the exact release.
+      - uses: astral-sh/setup-uv@v10.3.0
-      - uses: actions/setup-node@v4
+      - uses: actions/setup-node@v7
```

Then: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice68 && grep -c -E 'with:|enable-cache: true|node-version: "22"|cache: npm|cache-dependency-path: apps/web/package-lock.json' .github/workflows/ci.yml`
Expected: `6` (two `with:` lines and the four unchanged inputs). If any number or line differs, stop and report BLOCKED with the output; do not commit.

- [ ] **Step 4: Commit, gated on the banned-word grep**

Run:

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice68 && git add .github/workflows/ci.yml && ! { git diff --cached -U0 | grep '^+' | grep -v -F 'Banned-word grep (must block the commit)' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1([^0-9]|$)|top spot|dominat|certain'; } && git commit -q -m "ci: checkout@v7, setup-node@v7, setup-uv@v10.3.0 (Node 24 builds)

The node20 builds of these actions make the runner print Node 24
deprecation lines and a Node 20 annotation on every run. setup-uv has
no major tag past v7, so it is pinned to its exact release.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git log --oneline -1 && git status --short
```

Expected: one new commit; `git status --short` prints nothing.

---

### Task 2: Run both local gates

**Files:**
- None modified. Read-only verification that nothing outside the workflow changed.

**Interfaces:**
- Consumes: the Task 1 commit on `slice68`.
- Produces: two gate output files and two pre-check files in the plan workspace, quoted in the ledger and the findings doc.

Save every output in `/Users/vineet/Downloads/ADK/bsi-wt/slice68/.superpowers/sdd/2026-10-13-slice68-ci-actions-bump/` with shell redirection (`> file 2>&1`), never a heredoc.

- [ ] **Step 1: Pre-check, as its own command, saved**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && { echo "# precheck-before-backend-gate  $(date -u +%Y-%m-%dT%H:%M:%SZ)  slice68 HEAD $(git -C /Users/vineet/Downloads/ADK/bsi-wt/slice68 rev-parse --short HEAD)"; n=0; for p in $(pgrep -f 'bin/pytest|-m pytest'); do [ "$p" = "$$" ] && continue; c=$(lsof -p $p 2>/dev/null | awk '$4=="cwd"{print $NF}'); echo "pytest $p cwd $c"; case "$c" in /Users/vineet/Downloads/ADK/bsi-platform*|/Users/vineet/Downloads/ADK/bsi-wt/*|*/scratchpad/proof*|*/scratchpad/scratch*) n=1;; esac; done; [ $n = 0 ] && echo "no pytest of this repo running" || echo "WAIT"; } > /Users/vineet/Downloads/ADK/bsi-wt/slice68/.superpowers/sdd/2026-10-13-slice68-ci-actions-bump/task-2-precheck-backend.txt; cat /Users/vineet/Downloads/ADK/bsi-wt/slice68/.superpowers/sdd/2026-10-13-slice68-ci-actions-bump/task-2-precheck-backend.txt
```

Expected: the last line is `no pytest of this repo running` (a pytest with cwd `…/invoice-processing` does not block). If it is `WAIT`, wait about a minute and run the whole command again; never start pytest while it says `WAIT`.

- [ ] **Step 2: Backend gate, saved**

Run (the worktree has no `.venv` yet; `uv sync` creates it from the lock):

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice68 && { echo "# task-2-backend-gate  $(date -u +%Y-%m-%dT%H:%M:%SZ)  HEAD $(git rev-parse --short HEAD)  pre-check: see task-2-precheck-backend.txt"; uv sync -q && uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; echo "gate exit $?"; } > .superpowers/sdd/2026-10-13-slice68-ci-actions-bump/task-2-backend-gate.txt 2>&1; grep -E 'files already formatted|All checks passed|Success: no issues|^TOTAL|passed|gate exit' .superpowers/sdd/2026-10-13-slice68-ci-actions-bump/task-2-backend-gate.txt; echo "warning hits: $(grep -c -i warning .superpowers/sdd/2026-10-13-slice68-ci-actions-bump/task-2-backend-gate.txt)"
```

Expected, in order: `185 files already formatted`; `All checks passed!`; `Success: no issues found in 31 source files`; `TOTAL … 100%`; `1811 passed, 2 deselected in <time>`; `gate exit 0`; `warning hits: 0`.

- [ ] **Step 3: Pre-check again, saved**

Run the Step 1 command with both occurrences of `task-2-precheck-backend.txt` changed to `task-2-precheck-web.txt` and the header word `backend` changed to `web`. Expected: `no pytest of this repo running`.

- [ ] **Step 4: Web gate, saved**

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice68/apps/web && (test -d node_modules || npm ci --silent > /dev/null 2>&1) && { echo "# task-2-web-gate  $(date -u +%Y-%m-%dT%H:%M:%SZ)  HEAD $(git rev-parse --short HEAD)  pre-check: see task-2-precheck-web.txt"; npm run gate; echo "gate exit $?"; } > ../../.superpowers/sdd/2026-10-13-slice68-ci-actions-bump/task-2-web-gate.txt 2>&1; sed 's/\x1b\[[0-9;]*m//g' ../../.superpowers/sdd/2026-10-13-slice68-ci-actions-bump/task-2-web-gate.txt | grep -E 'Tests +[0-9]+ passed|Compiled|gate exit'
```

Expected: `Tests  93 passed (93)`, `✓ Compiled successfully`, `gate exit 0`.

- [ ] **Step 5: Confirm nothing changed**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice68 && git status --short`
Expected: empty.

---

## Plan self-review

1. **Spec coverage:** §4 (the change) → Task 1 Steps 2-3; §5's pre-PR checks (diff equals §4; both local gates) → Task 1 Step 3 and Task 2; §5's PR-run criteria and §6.3 (the merge) are the controller's finishing steps, not tasks, because only the PR triggers the workflow (decision 1); §7 (out of scope) → Global Constraints.
2. **Placeholder scan:** none.
3. **Type consistency:** no code; the three pins match spec §4's diff and the comment text is identical to it.
4. **Review Focus:** five lines, each pinned to a step or to the PR-run criterion that observes it.

**Departures from the spec:** none. The replace blocks were applied by script to a fresh detached copy of main f6b9964 and the resulting `.github/workflows/ci.yml` compared byte-identical to the spec's scratch copy (`scratch68`); the check's output is saved as proof output `16-plancheck68.txt` and the findings doc quotes it.

## Changes made during execution

(filled in by the docs PR)
