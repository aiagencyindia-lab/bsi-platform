# Slice 69: Dependabot for the CI Actions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dependabot checks the actions in `.github/workflows/` weekly and opens a PR when a newer version of a pinned ref exists.

**Architecture:** One new file, `.github/dependabot.yml`, with a single `updates` entry for the `github-actions` ecosystem, directory `/`, weekly. Nothing else in the repo changes. Before the PR, a YAML structure check and both local gates; after the merge, the controller observes Dependabot's first run on `main` (spec §5), which no task can do.

**Tech Stack:** GitHub Dependabot version updates (`version: 2`); Ruby 2.6's `YAML.safe_load` for the local structure check (Ruby is at `/usr/bin/ruby`).

**Spec:** `docs/superpowers/specs/2026-10-13-slice69-dependabot-actions-design.md`

## Global Constraints

- Branch `slice69`, worktree `/Users/vineet/Downloads/ADK/bsi-wt/slice69`, base main 0ff9343. The shell cwd resets after every command: prefix each with `cd /Users/vineet/Downloads/ADK/bsi-wt/slice69 &&`.
- Create only `.github/dependabot.yml`, with exactly the content in Task 1 Step 2. No workflow, setting or other file changes (spec §4, §7).
- The config watches the `github-actions` ecosystem only: no `uv` or `npm` entries, no `groups`, `commit-message`, `labels`, `reviewers` or other schedule (spec §3, §7).
- No repository setting changes: Dependabot security updates and alerts stay as they are; no auto-merge (spec §7).
- Before any pytest run, the pre-check runs as its own command and its raw output is saved to a file (Task 2, Step 1 text). Two pytests of this repo deadlock on `bsi_test`.
- Every commit is gated on the banned-word grep (the exact command is in Task 1, Step 4); never bypass it by hand. The words are listed in `tests/unit/test_recommend_copy.py` (`FORBIDDEN`).
- No live checks, no database migration, no worker, no model or DataForSEO spend. GitHub API use is read-only apart from the PR the controller opens (spec §6.6).
- Prettier is not in the gate; never run it. Never read, list, grep or source `.env`. No `rm`. No heredoc file writes. On a refused tool call, report BLOCKED.
- Commit trailer for implementer commits: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A key typo (`package_ecosystem`, `github_actions`, `interval: Weekly`) makes Dependabot reject or ignore the file, and nothing local would show it. Pinned by Task 1 Step 3's structure check, which compares the parsed file to the exact expected structure, and by the controller's post-merge observation (spec §5).
2. A wrong `directory` (for example `/.github/workflows`) is a valid key with the wrong value. Pinned by Task 1 Step 3 (the expected structure requires `"/"`).
3. YAML indentation that parses but nests `schedule` outside the `updates` entry. Pinned by Task 1 Step 3 (the comparison is on the whole parsed structure, not on key presence).
4. The file landing anywhere but `.github/dependabot.yml` (for example the repo root, or a different name): GitHub's "Configuring Dependabot version updates" page says to check `dependabot.yml` in to the `.github` directory. Pinned by Task 1 Step 3's path and Step 4's `--stat` check.
5. The local gates do not read the file, so a green gate proves only that nothing else changed. Pinned by Task 2 (both gates unchanged) and stated in spec §5; the post-merge run is the only observation of the config itself.

---

### Task 1: Create the Dependabot config

**Files:**
- Create: `.github/dependabot.yml`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: one commit on `slice69` adding `.github/dependabot.yml`; Task 2 runs the gates on it and the controller opens the PR from it.

- [ ] **Step 1: Confirm the starting state**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice69 && git status --short && ls -a .github && (test -e .github/dependabot.yml && echo present || echo absent)`
Expected: no modified tracked files; `.github` lists only `.`, `..` and `workflows`; `absent`.

- [ ] **Step 2: Create the file**

Create `.github/dependabot.yml` with the Write tool, with exactly this content (seven lines, ending with a newline):

```yaml
# Dependabot opens a PR when an action used in .github/workflows has a newer release.
version: 2
updates:
  - package-ecosystem: github-actions
    directory: "/"
    schedule:
      interval: weekly
```

- [ ] **Step 3: Run the structure check, saved**

The output goes to the plan workspace, `.superpowers/sdd/2026-10-13-slice69-dependabot-actions/` in the worktree. Under subagent-driven development that directory already exists (created at skill start by `scripts/sdd-workspace`); under executing-plans create it first with `mkdir -p /Users/vineet/Downloads/ADK/bsi-wt/slice69/.superpowers/sdd/2026-10-13-slice69-dependabot-actions` (the path is git-ignored).

Run:

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice69 && { echo "# task-1-structure-check  $(date -u +%Y-%m-%dT%H:%M:%SZ)  HEAD $(git rev-parse --short HEAD) plus the uncommitted .github/dependabot.yml"; ruby -ryaml -e 'd = YAML.safe_load(File.read(".github/dependabot.yml")); e = {"version" => 2, "updates" => [{"package-ecosystem" => "github-actions", "directory" => "/", "schedule" => {"interval" => "weekly"}}]}; puts "parsed: #{d.inspect}"; if d == e then puts "structure check PASS"; exit 0 else puts "structure check FAIL"; exit 1 end'; echo "check exit $?"; } > .superpowers/sdd/2026-10-13-slice69-dependabot-actions/task-1-structure-check.txt 2>&1; cat .superpowers/sdd/2026-10-13-slice69-dependabot-actions/task-1-structure-check.txt
```

Expected: a `# task-1-structure-check …` header line, then exactly:

```
parsed: {"version"=>2, "updates"=>[{"package-ecosystem"=>"github-actions", "directory"=>"/", "schedule"=>{"interval"=>"weekly"}}]}
structure check PASS
check exit 0
```

If it prints `structure check FAIL` or a non-zero exit, stop and report BLOCKED with the output; do not commit.

- [ ] **Step 4: Commit, gated on the banned-word grep**

Run:

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice69 && git add .github/dependabot.yml && ! { git diff --cached -U0 | grep '^+' | grep -v -F 'Banned-word grep (must block the commit)' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1([^0-9]|$)|top spot|dominat|certain'; } && git commit -q -m "ci: Dependabot version updates for the workflow actions

One weekly check of the actions in .github/workflows, so the exact-tag
setup-uv pin and the floating checkout and setup-node majors get bump
PRs. No other ecosystem, grouping or setting.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git log --oneline -1 && git status --short && git diff --stat main..HEAD -- .github/
```

Expected: one new commit; `git status --short` prints nothing; the stat (limited to `.github/`, since the branch also carries the spec and plan commits) shows `.github/dependabot.yml | 7 +++++++` and `1 file changed, 7 insertions(+)`.

---

### Task 2: Run both local gates

**Files:**
- None modified. Read-only verification that nothing outside the new file changed.

**Interfaces:**
- Consumes: the Task 1 commit on `slice69`.
- Produces: two gate output files and two pre-check files in the plan workspace, quoted in the ledger and the findings doc.

Save every output in `/Users/vineet/Downloads/ADK/bsi-wt/slice69/.superpowers/sdd/2026-10-13-slice69-dependabot-actions/` with shell redirection (`> file 2>&1`), never a heredoc. Under subagent-driven development that directory is the plan workspace, created at skill start by `scripts/sdd-workspace`; under executing-plans create it first with `mkdir -p /Users/vineet/Downloads/ADK/bsi-wt/slice69/.superpowers/sdd/2026-10-13-slice69-dependabot-actions` (the path is git-ignored).

If pytest makes no progress for more than about 6 minutes (the gate normally takes 2 to 4), check the test database with `docker ps`; if it is down, stop and report BLOCKED. Do not kill processes.

- [ ] **Step 1: Pre-check, as its own command, saved**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && { echo "# precheck-before-backend-gate  $(date -u +%Y-%m-%dT%H:%M:%SZ)  slice69 HEAD $(git -C /Users/vineet/Downloads/ADK/bsi-wt/slice69 rev-parse --short HEAD)"; n=0; for p in $(pgrep -f 'bin/pytest|-m pytest'); do [ "$p" = "$$" ] && continue; c=$(lsof -p $p 2>/dev/null | awk '$4=="cwd"{print $NF}'); echo "pytest $p cwd $c"; case "$c" in /Users/vineet/Downloads/ADK/bsi-platform*|/Users/vineet/Downloads/ADK/bsi-wt/*|*/scratchpad/proof*|*/scratchpad/scratch*|*/scratchpad/plancheck*) n=1;; esac; done; [ $n = 0 ] && echo "no pytest of this repo running" || echo "WAIT"; } > /Users/vineet/Downloads/ADK/bsi-wt/slice69/.superpowers/sdd/2026-10-13-slice69-dependabot-actions/task-2-precheck-backend.txt; cat /Users/vineet/Downloads/ADK/bsi-wt/slice69/.superpowers/sdd/2026-10-13-slice69-dependabot-actions/task-2-precheck-backend.txt
```

Expected: the last line is `no pytest of this repo running` (a pytest with cwd `…/invoice-processing` does not block). If it is `WAIT`, wait about a minute and run the whole command again; never start pytest while it says `WAIT`.

- [ ] **Step 2: Backend gate, saved**

Run (the worktree has no `.venv` yet; `uv sync` creates it from the lock):

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice69 && { echo "# task-2-backend-gate  $(date -u +%Y-%m-%dT%H:%M:%SZ)  HEAD $(git rev-parse --short HEAD)  pre-check: see task-2-precheck-backend.txt"; uv sync -q && uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; echo "gate exit $?"; } > .superpowers/sdd/2026-10-13-slice69-dependabot-actions/task-2-backend-gate.txt 2>&1; grep -E 'files already formatted|All checks passed|Success: no issues|^TOTAL|passed|gate exit' .superpowers/sdd/2026-10-13-slice69-dependabot-actions/task-2-backend-gate.txt; echo "warning hits: $(grep -c -i warning .superpowers/sdd/2026-10-13-slice69-dependabot-actions/task-2-backend-gate.txt)"
```

Expected, in order: `185 files already formatted`; `All checks passed!`; `Success: no issues found in 31 source files`; `TOTAL … 100%`; `1811 passed, 2 deselected in <time>`; `gate exit 0`; `warning hits: 0`.

- [ ] **Step 3: Pre-check again, saved**

Run the Step 1 command with both occurrences of `task-2-precheck-backend.txt` changed to `task-2-precheck-web.txt` and the header word `backend` changed to `web`. Expected: `no pytest of this repo running`.

- [ ] **Step 4: Web gate, saved**

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice69/apps/web && (test -d node_modules || npm ci --silent > /dev/null 2>&1) && { echo "# task-2-web-gate  $(date -u +%Y-%m-%dT%H:%M:%SZ)  HEAD $(git rev-parse --short HEAD)  pre-check: see task-2-precheck-web.txt"; npm run gate; echo "gate exit $?"; } > ../../.superpowers/sdd/2026-10-13-slice69-dependabot-actions/task-2-web-gate.txt 2>&1; sed 's/\x1b\[[0-9;]*m//g' ../../.superpowers/sdd/2026-10-13-slice69-dependabot-actions/task-2-web-gate.txt | grep -E 'Tests +[0-9]+ passed|Compiled|gate exit'
```

Expected: `Tests  93 passed (93)`, `✓ Compiled successfully`, `gate exit 0`.

- [ ] **Step 5: Confirm nothing changed**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice69 && git status --short`
Expected: empty.

---

## Plan self-review

1. **Spec coverage:** §4 (the change) → Task 1 Step 2; §5's pre-PR checks (the structure check; both local gates) → Task 1 Step 3 and Task 2; §6.1 and §6.2 → Task 2; §6.3 → Task 1 Step 3; §5's post-merge criteria and §6.4, §6.5 (the PR, its CI and merge, and the first Dependabot run) are the controller's finishing steps, not tasks, because only a merge to `main` lets Dependabot read the file; §6.6 and §7 → Global Constraints; §8 (handoff) → the findings doc, a docs-PR item.
2. **Placeholder scan:** none.
3. **Type consistency:** no code; the file content matches spec §4's block, and Step 3's expected structure matches spec §5's literal.
4. **Review Focus:** five lines, each pinned to a step or to the post-merge observation.

**Departures from the spec:** one. Spec §5 describes the structure check as a script (`check69.rb`); Task 1 Step 3 runs the same comparison as a `ruby -ryaml -e` one-liner, so the implementer needs no file from the scratchpad (slice 68 lost its scratchpad mid-slice). The expected structure and the PASS/FAIL lines are the same, and Step 3 saves its output with a UTC header and exit status, as spec §6.3 asks; the spec's mutant run (`interval: monthly`, FAIL, exit 1) is saved as proof output `02b-structure-check-mutant.txt`. The create block was applied by script to a fresh detached copy of main 0ff9343 and the resulting `.github/dependabot.yml` compared byte-identical to the spec's scratch copy (`scratch69`); the check's output is saved as proof output `05-plancheck69.txt` and the findings doc quotes it.
  - Note (2026-10-14, after slice 69, PR #138): correction: spec §5 says only "the check script" and does not name `check69.rb`, which was the script's name in the scratchpad (docs/findings-slice69.md, R3).

## Changes made during execution

- Task 1 ran as written (commit aa4d53b); its review was clean.
- Task 2 ran as written; its review raised two Minors, closed by R1 (the Next.js `serverActions` notice) and R2 (report wording, recorded in the ledger).
- The final review's two docs Minors went to the docs PR as dated notes (R3); its recommendation added a stricter `Checking if` check to the post-merge observation (R4).
- After the merge (PR 138, 35fe8b3), no github_actions run came in about 80 minutes of polling. The user enabled the repository's dependency graph, a setting outside spec §7, after which Dependabot security updates and alerts also read enabled, and then clicked "Check for updates" on the GitHub Actions entry. The first github_actions run followed at 2026-10-13T20:08:00Z and met every criterion.
- The same change brought seven open Dependabot security-update PRs (139 to 142, 144 to 146; 143 closed) for npm and uv dependencies, outside this slice's scope; the slice did not touch them.
