# Slice 26 Removed-Repeat Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `rule_check` returns `pass` instead of `adjusted` when the only change it made to the suggestion is removing repeated words.

**Architecture:** The repeat-removal loop inside `rule_check` moves into a helper, `_drop_repeats`. `rule_check` uses it for the title, and compares its final title with both the suggestion and the suggestion with only its repeats removed. Everything else in `rule_check`, and the rewrite prompt, stays as it is.

**Tech Stack:** Python 3.13, pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-slice26-rewrite-plural-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice26-rewrite-plural`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB, the network or the worker loop. Never call a model.
- **Shared test DB:** tests use `bsi_test`, which is shared. Run `pgrep -fl pytest` first, and never run two suites at once. Run the full suite only once, in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory; read the file rather than running it again.
- **Tool refusals:** if a tool refuses, stop and report BLOCKED. Do not work around it.
- **Lint and types:** ruff line length is 80, and RUF001 rejects a literal curly apostrophe. `mypy --strict` runs over `packages/core/bsi_core`.
- **Unchanged:** `rewrite_prompt` and every other prompt, `run_products`, `dropped`, the migrations and models, the API, the web app, `tests/integration`.
- **Banned words:** copy (comments, fixtures, docs) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat` or `certain`.
- **Backend gate:** `{ uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task1.txt 2>&1`
- **Commit trailer:** the `Co-Authored-By` line from the latest session reminder.

## Changes to existing tests that the spec implies

| Test | Change | Task |
|---|---|---|
| `test_rule_check_removes_repeated_tokens` (tests/unit/test_products.py line 260) | expected status `"adjusted"` becomes `"pass"` | 1 |
| `test_rule_check_drops_a_word_that_repeats_an_earlier_token` (line 441), first case only | expected status `"adjusted"` becomes `"pass"` | 1 |

## File map

| File | Responsibility |
|---|---|
| `packages/core/bsi_core/products.py` | `_drop_repeats`; `rule_check` uses it and its status rule and docstring change |
| `tests/unit/test_products.py` | the two changed expectations and one new test |
| docs | `docs/findings-slice26.md`, `docs/README.md`, a dated note in `docs/findings-slice25.md`, the spec's Rulings, this plan's changes section |

---

### Task 1: `_drop_repeats` and the status rule

**Files:**
- Modify: `packages/core/bsi_core/products.py`: a new helper right before `def rule_check(` (line 685); inside `rule_check`, the docstring's Status sentence, the inline repeat loop, and the last `return`.
- Test: `tests/unit/test_products.py`: lines 260-267 and 441-444, and a new test after `test_rule_check_drops_a_word_that_repeats_an_earlier_token` (which ends at line 451).

**Interfaces:**
- Consumes (unchanged): `fold_set(text) -> frozenset[str]`, `_strip_connectors`, `Sequence` (imported at products.py line 20).
- Produces: `_drop_repeats(words: Sequence[str]) -> list[str]`, private to `products.py`.

- [ ] **Step 1: Change the two test expectations.** In `test_rule_check_removes_repeated_tokens`, change the expected tuple's `"adjusted",` to `"pass",`. In `test_rule_check_drops_a_word_that_repeats_an_earlier_token`, change only the first assertion's `== ("Walkaroo Kids-Sandal", "adjusted", [])` to `== ("Walkaroo Kids-Sandal", "pass", [])`; the Red Tape assertion is unchanged.

- [ ] **Step 2: Write the new test**, right after `test_rule_check_drops_a_word_that_repeats_an_earlier_token`:

```python
def test_rule_check_does_not_count_a_removed_repeat():
    lc = ["BSOAgentTestBrand"]
    assert rule_check(
        "BSOAgentTestBrand Boys Sandal Blue",
        "BSOAgentTestBrand Blue Kid Sandals Boys Sandal",
        lc,
        allowed=["kids sandals", "kid"],
    ) == ("BSOAgentTestBrand Blue Kid Sandals Boys", "pass", [])
    assert rule_check(
        "BSOAgentTestBrand Men Flip Flop Navy",
        "BSOAgentTestBrand Navy Mens Flip Flops Flip Flop",
        lc,
        allowed=["mens flip flops"],
    ) == ("BSOAgentTestBrand Navy Mens Flip Flops", "pass", [])
    # A repeat plus an unbacked word is still an adjustment.
    assert rule_check(
        "Walkaroo Kids Shoes", "Walkaroo Kids Shoes Shoes Sale", ["Walkaroo"]
    ) == ("Walkaroo Kids Shoes", "adjusted", [])
    # A repeat plus a lost word is still flagged for review.
    assert rule_check(
        "Walkaroo Boys Sandal",
        "Walkaroo Kids Sandal Sandal",
        ["Walkaroo"],
        allowed=["kids sandals"],
    ) == ("Walkaroo Kids Sandal", "review", ["boys"])
```

- [ ] **Step 3: Run the three tests to see them fail.** `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/unit/test_products.py -k "removes_repeated_tokens or repeats_an_earlier_token or removed_repeat" 2>&1 | tail -8`
Expected: 3 failed. `test_rule_check_removes_repeated_tokens` and `test_rule_check_drops_a_word_that_repeats_an_earlier_token` on `'adjusted' != 'pass'` (or the tuple comparison showing it); `test_rule_check_does_not_count_a_removed_repeat` on its first assertion (`'adjusted'` where `'pass'` is expected).

- [ ] **Step 4: The helper.** In `packages/core/bsi_core/products.py`, directly before `def rule_check(`, add:

```python
def _drop_repeats(words: Sequence[str]) -> list[str]:
    """The words without any whose folded stems repeat an earlier kept
    word's stems (punctuation-only words are kept)."""
    seen: set[str] = set()
    kept: list[str] = []
    for word in words:
        stems = fold_set(word)
        if stems & seen:
            continue
        seen |= stems
        kept.append(word)
    return kept


```

- [ ] **Step 5: Use it in `rule_check`.** Replace the inline loop

```python
    seen: set[str] = set()
    kept: list[str] = []
    for word in title.split():
        stems = fold_set(word)
        if stems & seen:
            continue
        seen |= stems
        kept.append(word)
    title = " ".join(_strip_connectors(kept))
```

with

```python
    title = " ".join(_strip_connectors(_drop_repeats(title.split())))
```

and replace the last line

```python
    return title, ("pass" if title == suggestion else "adjusted"), []
```

with

```python
    plain = " ".join(_drop_repeats(suggestion.split()))
    return title, ("pass" if title in (suggestion, plain) else "adjusted"), []
```

- [ ] **Step 6: The docstring's Status sentence.** In `rule_check`'s docstring, replace

```
    "review" if the final title lost any of the original's words, else
    "adjusted" if it differs from the suggestion, else "pass"."""
```

with

```
    "review" if the final title lost any of the original's words, else
    "pass" if it equals the suggestion or the suggestion with only its
    repeats removed (_drop_repeats), else "adjusted"."""
```

- [ ] **Step 7: Run the three tests to see them pass.** Same command as Step 3. Expected: `3 passed`.

- [ ] **Step 8: Run the unit file and the product-run file.** `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/unit/test_products.py tests/integration/test_products_run.py 2>&1 | tail -3`
Expected: 122 passed (92 unit items: the 91 on main plus the new test; 30 integration). Report the number.

- [ ] **Step 9: Backend gate** (the Global Constraints command, workspace `.superpowers/sdd/2026-09-30-slice26-rewrite-plural/`); then `tail -5` the file and `grep -E "files (left unchanged|already formatted)|All checks passed|Success: no issues"` it.
Expected: ruff and mypy clean; 1545 passed (1544 on main plus the new test), 2 deselected, the 2 known third-party warnings; metrics coverage 100%. Report the exact counts.

- [ ] **Step 10: Commit.**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests/unit/test_products.py && git commit -m "feat(products): a removed repeat is not an adjustment" -m "Co-Authored-By: <trailer from the session reminder>"
```

---

### Task 2: Docs

**Files:**
- Create: `docs/findings-slice26.md` (the controller creates a one-line stub first; the subagent fills it with Edit).
- Modify: `docs/README.md` (three rows after the slice 25 rows), `docs/findings-slice25.md` §2 (a dated note), the spec's `## Rulings`, this plan's `## Changes made during execution`.

- [ ] **Step 1: Findings.** Fill `docs/findings-slice26.md` in the style of `docs/findings-slice25.md`, with sections:
  - `## 1. What was built`: `_drop_repeats`, the status rule and docstring, the two changed test expectations and the new test, the gate result as Task 1 recorded it, and a commit table from `git log --oneline --reverse main..HEAD` (oldest first, as in findings-slice25.md §1) with a "(this commit)" row.
  - `## 2. Probes`: probe 1 and probe 2 as recorded in the spec's Appendix A2 (calls, costs, pass/fail, the example raw titles), and why the prompt route was not built (the spec's decisions list); the probes' total, 11,211 + 6,757 = 17,968 micros, and the spend so far, about $10.97 of the $15 cap (spec §3).
  - `## 3. Live check on dev`: exactly "Not yet run. The controller runs it after the user approves; results are recorded here then."
  - `## 4. Deferred and untested`: every line tagged `minor (deferred…)` and every `parked` line in the ledger, quoted as recorded; "Parked: none" if none; the spec's Out of scope list; and the "Carried forward (still open)" items from docs/findings-slice25.md §3 that are still open.
- [ ] **Step 2: README rows** for the spec, the plan and the findings, in the slice 25 rows' format.
- [ ] **Step 3: Slice 25 note.** In `docs/findings-slice25.md` §2, under the bullet that contains "(slice 24's unrounded $10.9464 + $0.0066 = $10.9530)", add the nested bullet: "  - Correction (2026-09-30, slice 26): $10.9464 is the sum, before rounding, of slice 24's approximate figures ("about $10.94 + $0.0064", docs/findings-slice24.md §2), not an unrounded total." The bullet itself is not edited.
- [ ] **Step 4: Rulings.** The spec's `## Rulings` stays "None." unless the ledger records one; if it does, add it in the slice 25 spec's format (Decided / Found by / Why / Cost if wrong) and quote it in full in findings §4.
- [ ] **Step 5: Plan changes.** Fill this plan's `## Changes made during execution` from the ledger: one bullet per task, quoting departures as recorded.
- [ ] **Step 6: Grep** the changed docs files (findings-slice26, README, findings-slice25, the spec, this plan) for the banned words; expected: no match except this plan's own Global Constraints list.
- [ ] **Step 7: Commit** `git add docs && git commit -m "docs: slice 26 findings, index and notes" -m "Co-Authored-By: <trailer>"`.

---

## Self-review against the spec

- §1 status rule: Task 1 Steps 4-6. The docstring edit is §1's "The docstring's Status sentence says so".
- §2 testing: Task 1 Steps 1-2 (the two changed expectations, the new test with §1's four cases). Unchanged tests: Global Constraints.
- §3 live check: controller work after merge, with the user's OK; not a task. Docs: Task 2.
- Departures from the spec: (1) the new test's local `lc` and its two comments are the plan's; the spec names the test and its four cases, and the plan writes them as code; (2) the gate command redirects the whole chain (slice 25's deferred minor on the gate file), which the spec does not mention; (3) findings §3 is written before the live check as a placeholder, and the results are added after merge, while the spec lists the live check among the findings' contents; (4) Task 2 also updates the spec's `## Rulings` and this plan's changes section, and findings §4 also carries the spec's Out of scope list and the still-open slice 25 carried-forward items; spec §3's docs list names neither.
- Placeholders: none (the `<trailer>` and `<workspace>` are per-session values).
- Type consistency: `_drop_repeats(words: Sequence[str]) -> list[str]` used the same way in Steps 4-5.

## Changes made during execution

- Task 1 went as written (commit 9a0a537; review: spec ✅, quality Approved, 0 Critical, 0 Important, 2 Minor, both deferred and quoted in findings §4). As the ledger records it:
  - Implementer concern: "a suggestion whose only faults are a repeat and a trailing connector still gets adjusted (as the spec says: the connector strip counts)."
  - "⚠️ resolved by controller: RED: the controller's scratch run of the plan's test file against main's code (before dispatch) failed exactly these 3 tests (3 failed, 89 passed); 1545 = main's 1544 (post-merge gate after PR #47, aa62285) + the new test."
  - Controller note: "a Task 1 report stub was created pre-emptively against the process rule (stubs only when the plan says so or after a refusal, asking the user first); it was deleted before dispatch. The implementer creates its own report."
- Task 2 (e8b2589): "controller created the one-line stub docs/findings-slice26.md (the plan says so; uncommitted)", as Task 2's Files list says; the subagent filled it. The ledger records no ruling, so the spec's `## Rulings` stays "None." As the ledger records it:
  - "Task 2: review: spec ✅, quality Approved; 0 Critical, 0 Important, 3 Minor." All 3 Minor are deferred and quoted in findings §4.
  - "⚠️ resolved by controller: the per-call probe counts (baseline 10, 9, 10 of 10; first-proposed sentence 10, 0, 0; approach C 0, 2, 2 singular/plural repeats) match the probe scripts' printed output seen by the controller when the probes ran."
- Final review: "With fixes"; 0 Critical, 2 Important (findings §4 lacked the 3 Task 2 deferred minors; this section's Task 2 bullet lacked the Task 2 review result and the probe-count resolution), 3 Minor, deferred and quoted in findings §4; the 5 earlier deferred minors were all kept deferred. The fix wave is ce2ef77.
- After the fix wave's re-review: the controller changed findings §4's lead-in to "From the task reviews and the final review" (the re-reviewer's out-of-scope observation: it also covers the final-review lines) 7a55220; recorded as ruling R1 after the process audit.
- Process audit (after the finishing menu, 2026-09-30): the spacing consequence was put to the user ("Yes, pass"); R1 added to the spec's Rulings and findings §4; findings §5 lists the audit. No code or plan task changed (this commit).
