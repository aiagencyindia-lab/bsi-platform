# Slice 34 Axes Length-Guard Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pin `rivals._stem`'s `len(word) > 4` guard on the `-es` rule with a named unit test (`axes → axe`, `shes → she`).

**Architecture:** One test function added to tests/unit/test_rivals.py; no production code changes. The test passes on the current code; the evidence that it pins the guard is a mutation run on a scratch copy of `bsi_core` (guard changed to `> 3`), where the new test fails and the existing tests do not.

**Tech Stack:** Python 3.13, pytest (unit test; no database).

**Spec:** `docs/superpowers/specs/2026-10-01-slice34-axes-guard-test-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice34-axes-guard-test`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB, the network or the worker loop. Never call a model. Do NOT change any file under `packages/` in the repo (the mutation run uses a copy outside the repo).
- **Shared test DB:** run `pgrep -fl pytest` first; if it prints a running pytest, stop and wait for it to finish before running yours. Never run two suites at once. Run the full backend suite only once, in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal: read the file and repeat the edit.)
- **Writing files:** never use a shell heredoc or zsh `echo` to write files; use the Edit or Write tools. Scratch copies go under the session scratchpad given in the task brief, never inside the repo.
- **Lint and types:** ruff line length is 80 (the Backend gate runs `ruff format .` first).
- **Banned words:** copy (code, comments, test names) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat` or `certain` (`FORBIDDEN` in tests/unit/test_recommend_copy.py).
- **Banned-word grep:** `grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'`, run on added lines only (`git diff --cached -U0 | grep '^+' | <the grep>` after staging). Expected: no match.
- **Backend gate:** `{ uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task1.txt 2>&1; echo "gate exit $?"` (the echo prints to the terminal).
- **Commit trailer:** the `Co-Authored-By` line from the latest session reminder.
- **Baseline counts** (collected 2026-10-01 on main `02f3592`): backend `1570 passed, 2 deselected` (plus the 2 known third-party warnings); tests/unit/test_rivals.py 32.

## File map

| File | Responsibility |
|---|---|
| `tests/unit/test_rivals.py` | `test_stem_es_rule_skips_four_letter_words` |

---

### Task 1: the length-guard test

**Files:**
- Test: `tests/unit/test_rivals.py` (insert after `test_stem_folds_plurals`, which ends at line 546)

**Interfaces:**
- Consumes: `_stem`, already imported at the top of tests/unit/test_rivals.py.
- Produces: nothing for later tasks.

- [ ] **Step 1: Add the test**

In `tests/unit/test_rivals.py`, replace

```python
        "cach",
        "mouss",
    ]


def test_slug_words_reads_the_path_only():
```

with

```python
        "cach",
        "mouss",
    ]


def test_stem_es_rule_skips_four_letter_words():
    # The -es rule needs more than four characters: axes and shes fall
    # through to the one-s rule (axe, she), not ax and sh.
    assert [_stem(w) for w in ("axes", "shes")] == ["axe", "she"]


def test_slug_words_reads_the_path_only():
```

- [ ] **Step 2: Run the test file on the real code**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own first (if it prints a running pytest, wait), then: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q -p no:cacheprovider tests/unit/test_rivals.py 2>&1 | tail -1`
Expected: `33 passed`. (The behaviour already exists, so there is no red run on the real code; Step 3 is the red evidence.)

- [ ] **Step 3: Mutation run (red evidence)**

Run `cd /Users/vineet/Downloads/ADK/bsi-platform && mkdir -p <scratchpad>/s34mut/pkg && cp -R /Users/vineet/Downloads/ADK/bsi-platform/packages/core/bsi_core <scratchpad>/s34mut/pkg/` (the copy is outside the repo; `mkdir` and `cp` are allowed, only heredoc and `echo` file writes are not; run it once, on a fresh `s34mut`). In the copy's `rivals.py`, use the Edit tool to change the one line `    if len(word) > 4 and word.endswith(_ES):` to `    if len(word) > 3 and word.endswith(_ES):`. Then run, with the copy first on the path:

first `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest` on its own (if it prints a running pytest, wait for it to finish), then `cd /Users/vineet/Downloads/ADK/bsi-platform && PYTHONPATH=<scratchpad>/s34mut/pkg:. uv run pytest -q -p no:cacheprovider tests/unit/test_rivals.py tests/unit/test_products.py 2>&1 | grep -E "^FAILED|At index|passed|failed"`

Expected: `1 failed, 132 passed`; the failure is `test_stem_es_rule_skips_four_letter_words` with `At index 0 diff: 'ax' != 'axe'`. If the grep does not show the `At index` line, read the failure block in the full output. Record the command and output in the report. (Before this test existed, the same mutant gave `132 passed`: spec, Design.)

- [ ] **Step 4: Banned-word grep, then the backend gate**

Stage the file (`git add tests/unit/test_rivals.py`) and run the banned-word grep on `git diff --cached -U0`. Expected: no match. Then the Backend gate with `gate-task1.txt`. Expected: `gate exit 0`; `1571 passed, 2 deselected` (1570 + 1) and the metrics coverage line at 100%.

- [ ] **Step 5: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add tests/unit/test_rivals.py && git commit -m "test(rivals): pin the -es rule's length guard

axes and shes fall through to the one-s rule (axe, she). With the guard
changed to > 3 this test fails, and the other tests in test_rivals.py
and test_products.py still pass.

<trailer>"
```

---

## Self-review (plan vs spec)

- Spec coverage: the test (Design, first bullet) → Step 1; the proof (Design, third bullet) → Steps 2–3; counts → Steps 2 and 4; copy → Step 4. Process and docs are controller work after merge.
- Departures from the spec: the mutation run uses the existing test files rather than the test in a separate folder (the test is now in the repo); the spec's run reported the test alone and the two files separately, Step 3 reports them together (`1 failed, 132 passed`), so "the existing tests still pass on the mutant" is read from that line (133 tests, one failure) rather than from a separate run. The spec's ruff check on the test is covered by the Step 4 gate.
- Rulings applied to this plan: R2 (the plan review's five points) and R3 (the `cd` prefix on the standalone commands), in the spec's Rulings section.
- Placeholders: `<trailer>` (the Global Constraints' commit-trailer rule), `<workspace>` and `<scratchpad>` (paths the task brief supplies).
- Type consistency: `_stem(word: str) -> str`, already imported.
