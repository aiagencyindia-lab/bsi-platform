# Slice 27 Overlap Filter and Word Restore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The rewrite prompt stops listing missing words that are already in the product's keyword, and `rule_check` puts back any original-title word the model dropped.

**Architecture:** Two private helpers in `products.py`: `_not_in_keyword` filters the rewrite prompt's `missing` field (folding "-es" plurals with `_allowed_stems`), and `_restore` re-inserts lost original words in `rule_check`, right after the R1/R2 fallback and before the repeat step. `missing()`, the stored missing list, the API, the web app and the CSV are unchanged.

**Tech Stack:** Python 3.13, pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-slice27-overlap-restore-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice27-overlap-restore`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB, the network or the worker loop. Never call a model.
- **Shared test DB:** tests use `bsi_test`, which is shared. Run `pgrep -fl pytest` first, and never run two suites at once. Run the full suite only once, in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory; read the file rather than running it again.
- **Tool refusals:** if a tool refuses, stop and report BLOCKED. Do not work around it.
- **Lint and types:** ruff line length is 80, and RUF001 rejects a literal curly apostrophe. `mypy --strict` runs over `packages/core/bsi_core`.
- **Unchanged:** `missing()`, `dropped()`, `_drop_repeats`, `run_products`, every prompt's wording, the migrations and models, the API, the web app, `EXPORT_COLUMNS`.
- **Banned words:** copy (comments, fixtures, docs) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat` or `certain`.
- **Backend gate:** `{ uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task1.txt 2>&1`
- **Commit trailer:** the `Co-Authored-By` line from the latest session reminder.

## Changes to existing tests that the spec implies

| Test | Change | Task |
|---|---|---|
| `test_rule_check_trims_to_150_at_a_word_boundary` (tests/unit/test_products.py line 291) | `adjusted`, lost `[]`, "Plain " prefix | 1 |
| `test_rule_check_drops_a_word_that_repeats_an_earlier_token` (line 441), Red Tape case | `("Red Tape Boots Shoes", "adjusted", [])` | 1 |
| `test_rule_check_does_not_count_a_removed_repeat` (line 455), last case and its comment | `("Walkaroo Boys Kids Sandal", "adjusted", [])` | 1 |
| `test_rule_check_flags_dropped_words_for_review` (line 505) | renamed `test_rule_check_restores_dropped_words`, restored values | 1 |
| `test_rule_check_strips_a_connector_the_trim_leaves_at_the_end` (line 527) | original "w0" | 1 |
| `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` (tests/integration/test_products_run.py line 182) | suggested title, status and comment | 1 |
| `test_a_failed_search_is_stored_and_the_run_goes_on` (line 650) | suggested title | 1 |

## File map

| File | Responsibility |
|---|---|
| `packages/core/bsi_core/products.py` | `_restore`, `_not_in_keyword`, `rule_check`'s restore line and docstring, `rewrite_prompt`'s missing field |
| `tests/unit/test_products.py` | the changed rule_check tests and four new tests |
| `tests/integration/test_products_run.py` | two changed expectations |
| docs | `docs/findings-slice27.md`, `docs/README.md`, the spec's Rulings, this plan's changes section |

---

### Task 1: The prompt filter and the word restore

**Files:**
- Modify: `packages/core/bsi_core/products.py`: a new `_restore` right before `def _drop_repeats(` (line 685); in `rule_check` (line 699) the docstring and the line before the repeat step (line 732); a new `_not_in_keyword` right before `def rewrite_prompt(` (line 915); `rewrite_prompt`'s `_product_lines` call.
- Test: `tests/unit/test_products.py`, `tests/integration/test_products_run.py` (the tests in the table above, and four new tests).

**Interfaces:**
- Consumes (unchanged): `dropped`, `tokens`, `fold_set`, `_allowed_stems`, `_drop_repeats`, `_strip_connectors`, `_product_lines`, `Sequence`, `Any`.
- Produces: `_restore(original: str, words: Sequence[str], brand_names: Sequence[str]) -> list[str]` and `_not_in_keyword(p: dict[str, Any]) -> list[str]`, both private.

- [ ] **Step 1: Test edits.** Make these replacements, each exactly once.

In `tests/unit/test_products.py`, replace

```python
        "Plain", " ".join(words), BRAND, allowed=[" ".join(words)]
    )
    assert status == "review" and lost == ["plain"]
    assert len(fixed) <= 150
    assert fixed == " ".join(words)[: len(fixed)]
    assert not fixed.endswith(" ") and fixed.split()[-1] in words
```

with

```python
        "Plain", " ".join(words), BRAND, allowed=[" ".join(words)]
    )
    # The lost "Plain" is restored at the start, then the trim applies.
    assert status == "adjusted" and lost == []
    assert len(fixed) <= 150
    assert fixed.removeprefix("Plain ") == " ".join(words)[: len(fixed) - 6]
    assert not fixed.endswith(" ") and fixed.split()[-1] in words


def test_rule_check_trim_can_still_lose_a_restored_word():
    words = [f"w{i}" for i in range(60)]
    fixed, status, lost = rule_check(
        "w59 Plain", " ".join(words), BRAND, allowed=[" ".join(words)]
    )
    assert (status, lost, len(fixed)) == ("review", ["w59", "plain"], 149)
```

In `tests/unit/test_products.py`, replace

```python
    ) == (
        "Red Tape Shoes",
        "review",
        ["boots"],
    )
```

with

```python
    ) == (
        "Red Tape Boots Shoes",
        "adjusted",
        [],
    )


def test_rule_check_repeat_step_can_drop_a_restored_hyphenated_word():
    # "Anti" is kept first, so the restored "Anti-Skid" repeats it and is
    # dropped again: a spec ceiling, the same result as before the restore.
    assert rule_check(
        "Walkaroo Boys Anti-Skid Sandal",
        "Walkaroo Anti Boys Sandal",
        ["Walkaroo"],
    ) == ("Walkaroo Anti Boys Sandal", "review", ["skid"])


def test_rule_check_restore_does_not_bring_back_a_repeat():
    assert rule_check(
        "Walkaroo Anti-Skid Sandal", "Walkaroo Anti Sandal", ["Walkaroo"]
    ) == ("Walkaroo Anti-Skid Sandal", "adjusted", [])
    assert rule_check(
        "Walkaroo Casual Sandal Casual Wear",
        "Walkaroo Sandal Wear",
        ["Walkaroo"],
    ) == ("Walkaroo Casual Sandal Wear", "adjusted", [])
```

In `tests/unit/test_products.py`, replace

```python
    # A repeat plus a lost word is still flagged for review.
    assert rule_check(
        "Walkaroo Boys Sandal",
        "Walkaroo Kids Sandal Sandal",
        ["Walkaroo"],
        allowed=["kids sandals"],
    ) == ("Walkaroo Kids Sandal", "review", ["boys"])
```

with

```python
    # A repeat plus a lost word: the word is restored.
    assert rule_check(
        "Walkaroo Boys Sandal",
        "Walkaroo Kids Sandal Sandal",
        ["Walkaroo"],
        allowed=["kids sandals"],
    ) == ("Walkaroo Boys Kids Sandal", "adjusted", [])
```

In `tests/unit/test_products.py`, replace

```python
def test_rule_check_flags_dropped_words_for_review():
    assert rule_check(
        "Men Casual Sandal Brown",
        "Brown Mens Sandal Shoes",
        BRAND,
        allowed=["Shoes"],
    ) == ("Brown Mens Sandal Shoes", "review", ["casual"])
    assert rule_check(
        "Men Flip Flop Navy", "Navy Men Slipper", BRAND, allowed=["Slipper"]
    ) == (
        "Navy Men Slipper",
        "review",
        ["flip", "flop"],
    )
```

with

```python
def test_rule_check_restores_dropped_words():
    assert rule_check(
        "Men Casual Sandal Brown",
        "Brown Mens Sandal Shoes",
        BRAND,
        allowed=["Shoes"],
    ) == ("Brown Mens Casual Sandal Shoes", "adjusted", [])
    # A replaced product type ends up as both types (spec ceiling).
    assert rule_check(
        "Men Flip Flop Navy", "Navy Men Slipper", BRAND, allowed=["Slipper"]
    ) == (
        "Navy Men Flip Flop Slipper",
        "adjusted",
        [],
    )
```

In `tests/unit/test_products.py`, replace

```python
    words = [f"w{i}" for i in range(39)] + ["for", "tail", "end"]
    fixed, _status, _lost = rule_check(
        "Plain", " ".join(words), BRAND, allowed=[" ".join(words)]
    )
```

with

```python
    words = [f"w{i}" for i in range(39)] + ["for", "tail", "end"]
    # The original "w0" is kept, so nothing is restored ahead of the cut.
    fixed, _status, _lost = rule_check(
        "w0", " ".join(words), BRAND, allowed=[" ".join(words)]
    )
```

In `tests/unit/test_products.py`, replace

```python
    assert "Keep every word" in rewrite_prompt("Walkaroo", [])
```

with

```python
    assert "Keep every word" in rewrite_prompt("Walkaroo", [])


def test_rewrite_prompt_leaves_keyword_words_out_of_missing():
    rp = rewrite_prompt(
        "Walkaroo",
        [
            {
                "index": 0,
                "title": "Walkaroo Boys Sandal",
                "keyword": "kids sandals",
                "missing": ["kid", "summer"],
            },
            {
                "index": 1,
                "title": "Titan Analog Dial",
                "keyword": "men watches",
                "missing": ["men", "watch", "analog"],
            },
        ],
    )
    assert '"missing": ["summer"]' in rp
    assert '"missing": ["analog"]' in rp
    rp = rewrite_prompt(
        "Walkaroo",
        [
            {
                "index": 0,
                "title": "Walkaroo Boys Sandal",
                "keyword": "kids sandals",
                "missing": ["kid"],
            }
        ],
    )
    assert '"missing"' not in rp
```

In `tests/integration/test_products_run.py`, replace

```python
    assert p.suggested_title == "Walkaroo Kids Summer Sandals"
    # "Walkaroo Boys Sandal 0" rewritten as "…Kids Summer Sandals" loses
    # "boys", so the suggestion is flagged for review.
    assert (p.rule_check, p.dropped_words) == ("review", ["boys"])
```

with

```python
    assert p.suggested_title == "Walkaroo Boys Kids Summer Sandals"
    # "Walkaroo Boys Sandal 0" rewritten as "…Kids Summer Sandals" loses
    # "boys"; the rule check puts it back after "Walkaroo".
    assert (p.rule_check, p.dropped_words) == ("adjusted", [])
```

In `tests/integration/test_products_run.py`, replace

```python
    assert rows[0].suggested_title == "Walkaroo Kids Sandals"
```

with

```python
    assert rows[0].suggested_title == "Walkaroo Boys Kids Sandals"
```

- [ ] **Step 2: Run the changed and new tests to see them fail.** `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/unit/test_products.py tests/integration/test_products_run.py 2>&1 | grep -E "^FAILED|passed|failed"`
Expected: 8 failed, 118 passed. The failing tests: `test_rule_check_trims_to_150_at_a_word_boundary`, `test_rule_check_drops_a_word_that_repeats_an_earlier_token`, `test_rule_check_restore_does_not_bring_back_a_repeat`, `test_rule_check_does_not_count_a_removed_repeat`, `test_rule_check_restores_dropped_words`, `test_rewrite_prompt_leaves_keyword_words_out_of_missing`, `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked`, `test_a_failed_search_is_stored_and_the_run_goes_on`. Two new tests and one edited test pass already, as they pin behaviour this slice keeps: `test_rule_check_trim_can_still_lose_a_restored_word`, `test_rule_check_repeat_step_can_drop_a_restored_hyphenated_word` and `test_rule_check_strips_a_connector_the_trim_leaves_at_the_end`.

- [ ] **Step 3: Code edits.** Make these replacements in order, each exactly once.

In `packages/core/bsi_core/products.py`, replace

```python
def _drop_repeats(
```

with

```python
def _restore(
    original: str, words: Sequence[str], brand_names: Sequence[str]
) -> list[str]:
    """The words with each original-title word the suggestion lost put
    back, right after the nearest earlier original word that is still
    there (at the start if none)."""
    lost = set(dropped(original, " ".join(words), brand_names))
    out = list(words)
    if not lost:
        return out
    orig = original.split()
    for i, word in enumerate(orig):
        if not set(tokens(word)) & lost:
            continue
        pos = 0
        for prev in reversed(orig[:i]):
            stems = fold_set(prev)
            at = [n for n, w in enumerate(out) if stems and fold_set(w) & stems]
            if at:
                pos = at[0] + 1
                break
        out.insert(pos, word)
    return out


def _drop_repeats(
```

In `packages/core/bsi_core/products.py`, replace

```python
    title = " ".join(_strip_connectors(_drop_repeats(title.split())))
```

with

```python
    title = " ".join(_restore(original, title.split(), brand_names))
    title = " ".join(_strip_connectors(_drop_repeats(title.split())))
```

In `packages/core/bsi_core/products.py`, replace

```python
    the original title is used instead (Rulings R1 and R2);
```

with

```python
    the original title is used instead (Rulings R1 and R2);
    an original-title word the suggestion lost is put back (_restore);
```

In `packages/core/bsi_core/products.py`, replace

```python
    "review" if the final title lost any of the original's words, else
```

with

```python
    "review" if the final title lost any of the original's words (after
    the restore, only the repeat step or the trim can cut one), else
```

In `packages/core/bsi_core/products.py`, replace

```python
def rewrite_prompt(
```

with

```python
def _not_in_keyword(p: dict[str, Any]) -> list[str]:
    """The product's missing words without those whose stems are in its
    keyword: the rewrite adds the keyword anyway, so asking for both
    ("kids" and "kid") invites a repeat."""
    kw = _allowed_stems("", [p.get("keyword") or ""], [])
    return [m for m in p.get("missing") or [] if not fold_set(m) & kw]


def rewrite_prompt(
```

In `packages/core/bsi_core/products.py`, replace

```python
        + _product_lines(
            products, "keyword", "missing", "description", "attributes"
        )
```

with

```python
        + _product_lines(
            [{**p, "missing": _not_in_keyword(p)} for p in products],
            "keyword",
            "missing",
            "description",
            "attributes",
        )
```

- [ ] **Step 4: Run the two files to see them pass.** Same command as Step 2. Expected: 126 passed (the 122 items on main plus the four new tests).

- [ ] **Step 5: Backend gate** (the Global Constraints command, workspace `.superpowers/sdd/2026-09-30-slice27-overlap-restore/`); then `tail -5` the file and `grep -E "files (left unchanged|already formatted)|All checks passed|Success: no issues"` it.
Expected: ruff and mypy clean; 1549 passed (1545 on main plus the four new tests), 2 deselected, the 2 known third-party warnings; metrics coverage 100%. Report the exact counts.

- [ ] **Step 6: Commit.**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests/unit/test_products.py tests/integration/test_products_run.py && git commit -m "feat(products): restore dropped words; keep keyword words out of the rewrite's missing list" -m "Co-Authored-By: <trailer from the session reminder>"
```

---

### Task 2: Docs

**Files:**
- Create: `docs/findings-slice27.md` (the controller creates a one-line stub first; the subagent fills it with Edit).
- Modify: `docs/README.md` (three rows after the slice 26 rows), the spec's `## Rulings`, this plan's `## Changes made during execution`.

- [ ] **Step 1: Findings.** Fill `docs/findings-slice27.md` in the style of `docs/findings-slice26.md`, with sections:
  - `## 1. What was built`: `_not_in_keyword` and `_restore`, where each runs, the docstring change, the changed and new tests, the RED and GREEN counts as the Task 1 report records them (Step 2: 8 failed, 118 passed; Step 4: 126 passed), the gate result as Task 1 recorded it, and a commit table from `git log --oneline --reverse main..HEAD` with a "(this commit)" row.
  - `## 2. Live check on dev`: exactly "Not yet run. The controller runs it after the user approves; results are recorded here then."
  - `## 3. Deferred and untested`: every line tagged `minor (deferred…)` and every `parked` line in the ledger, quoted as recorded; "Parked: none" if none; the rulings recorded in the ledger (or "Rulings: none."); the spec's ceilings (§2) and Out of scope list; the "Carried forward (still open)" items from docs/findings-slice26.md §4 that are still open; and an "Untested" list naming the spec §2 examples no test pins.
- [ ] **Step 2: README rows** for the spec, the plan and the findings, in the slice 26 rows' format.
- [ ] **Step 3: Rulings.** The spec's `## Rulings` stays "None." unless the ledger records one; if it does, keep "None." and add a dated correction note followed by the ruling in the slice 26 spec's format (Decided / Found by / Why / Cost if wrong), quoted in full in findings §3.
- [ ] **Step 4: Plan changes.** Fill this plan's `## Changes made during execution` from the ledger: one bullet per task, plus one each for the final review and any fix wave, quoting departures as recorded; the bullet for the commit that fills this section ends "(this commit)".
- [ ] **Step 5: Grep** the changed docs files (findings-slice27, README, the spec, this plan) for the banned words; expected: no match except this plan's own Global Constraints list.
- [ ] **Step 6: Commit** `git add docs && git commit -m "docs: slice 27 findings, index and notes" -m "Co-Authored-By: <trailer>"`.

---

## Self-review against the spec

- §1 prompt filter: Task 1 Step 3 (`_not_in_keyword` with `_allowed_stems`, the `_product_lines` call). Test: `test_rewrite_prompt_leaves_keyword_words_out_of_missing`.
- §2 restore: Task 1 Step 3 (`_restore`, the restore line before the repeat step, the docstring). Tests: the §3 list, including `test_rule_check_restore_does_not_bring_back_a_repeat` and `test_rule_check_trim_can_still_lose_a_restored_word`.
- §3 testing: Task 1 Step 1 covers every test §3 lists, with its values and comment changes.
- §4 live check: controller work after merge, with the user's OK; not a task. Docs: Task 2.
- Departures from the spec: (1) the new tests' fixture titles and comments beyond what §3 names are the plan's ("Titan Analog Dial" as the second prompt-test product; the first prompt-test product "Walkaroo Boys Sandal"; the comments "The lost "Plain" is restored at the start, then the trim applies.", "A replaced product type ends up as both types (spec ceiling).", "The original "w0" is kept, so nothing is restored ahead of the cut.", the hyphen test's comment, and the integration comment "…loses "boys"; the rule check puts it back after "Walkaroo"."; (2) the docstring's new wording is the plan's (the spec says the docstring "gains the restore step and says `review` now means an original word was lost by the trim or the repeat step"); (3) Task 2 also updates the spec's Rulings and this plan's changes section, and findings §3 also carries the spec's ceilings and the slice 26 carried-forward items; spec §4's docs list names neither; (4) findings §2 is written before the live check as a placeholder; (5) the docstring says only the repeat step or the trim can lose a word after the restore, matching the spec's corrected §2.
- Verified before committing this plan: the Step 1 and Step 3 edits were applied to scratch copies of main (each replacement found exactly once). The edited tests against main's code gave 8 failed and 118 passed (the list in Step 2); against the patched code, 126 passed (re-verified after the plan review's changes). ruff check, ruff format and `mypy --strict` are clean on the patched products.py and the two test files.
- Placeholders: none (the `<trailer>` and `<workspace>` are per-session values).
- Type consistency: `_restore` and `_not_in_keyword` are used with the signatures in Interfaces.

## Changes made during execution

(filled by Task 2 from the ledger)
