# Slice 33 "-es" Plural Folding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `rivals._stem` folds `-es` plurals after ch, sh, x, ss and zz (watches → watch, glasses → glass) and keeps `-ss` words whole (glass stays glass), so titles, repeats, keyword keys and rival-page slugs meet their singulars; `_allowed_stems` keeps its one-sided set, with its docstring corrected.

**Architecture:** One shared helper changes (`rivals._stem`, 16 direct calls across `rivals.py` and `products.py`); everything else picks it up. Tests pin the new stems, the named limits, and three two-sided product cases the old one-sided patch could not pass, plus one case pinning what the kept set still does. Two docstrings in `products.py` are brought up to date. No schema, API or web change.

**Tech Stack:** Python 3.13, pytest (unit tests only; no database needed by the new tests, but the gate runs the full suite on the shared `bsi_test` DB).

**Spec:** `docs/superpowers/specs/2026-10-01-slice33-es-folding-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`. In zsh a variable holding several paths is not split into words; pass paths literally.
- **Branch:** `slice33-es-folding`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB, the network or the worker loop. Never call a model.
- **Unchanged:** every `_stem` caller's own code (`fold`, `keyword_key`, `missing`, `rule_check`, `_not_in_keyword`, `rivals._words`, …); `_allowed_stems`' body and `es` set (R1); `NOISE_WORDS`, `AUDIENCE_WORDS`; the existing tests' expectations except the one rewrite this plan names.
- **Shared test DB:** run `pgrep -fl pytest` first, and never run two suites at once. Run the full backend suite only once per task, in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory.
- **Tool refusals:** if any tool refuses, stop and report BLOCKED. Do not switch tools or work around it. (The Edit tool's "read the file first" precondition is not a refusal: read the file and repeat the edit.)
- **Writing files:** never use a shell heredoc or zsh `echo` to write files; use the Edit or Write tools.
- **Lint and types:** ruff line length is 80 (the Backend gate runs `ruff format .` first); RUF001 rejects a literal curly apostrophe. The gate's mypy covers `packages/core/bsi_core`, which includes both files this plan changes.
- **Banned words:** copy (code, comments, docstrings, test names, fixtures, response bodies, docs) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat` or `certain` (`FORBIDDEN` in tests/unit/test_recommend_copy.py).
- **Banned-word grep:** `grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1|top spot|dominat|certain'`, run on added lines only (`git diff --cached -U0 | grep '^+' | <the grep>` after staging). Expected: no match.
- **Backend gate:** `{ uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-taskN.txt 2>&1; echo "gate exit $?"` (the echo prints to the terminal, not to a file).
- **Commit trailer:** the `Co-Authored-By` line from the latest session reminder.
- **Baseline counts** (collected 2026-10-01 on `5e95b88`): backend `1566 passed, 2 deselected` (plus the 2 known third-party warnings); tests/unit/test_rivals.py 32; tests/unit/test_products.py 96.

## File map

| File | Responsibility |
|---|---|
| `packages/core/bsi_core/rivals.py` | `_ES`; the new `_stem` |
| `tests/unit/test_rivals.py` | `test_stem_folds_plurals` (rewrites the old stem test) |
| `tests/unit/test_products.py` | four new cases: `keyword_key`, the echo repeat, `missing` on an `-es` title, lenses backing |
| `packages/core/bsi_core/products.py` | two docstrings (`fold`, `_allowed_stems`) |

---

### Task 1: the stem rule and its tests

**Files:**
- Modify: `packages/core/bsi_core/rivals.py:50-55` (`_stem`)
- Test: `tests/unit/test_rivals.py:525-535`, `tests/unit/test_products.py` (append)

**Interfaces:**
- Consumes: nothing new. `keyword_key`, `missing` and `rule_check` are already imported at the top of tests/unit/test_products.py; `_stem` at the top of tests/unit/test_rivals.py.
- Produces: `rivals._stem` with the five-ending `-es` rule and the `-ss` keep; `rivals._ES`.

- [ ] **Step 1: Rewrite the stem test and add the four product cases**

In `tests/unit/test_rivals.py`, replace

```python
def test_stem_drops_one_trailing_s_on_longer_words():
    assert [
        _stem(w) for w in ("sneakers", "shoes", "kids", "bus", "glass")
    ] == [
        "sneaker",
        "shoe",
        "kid",
        "bus",
        "glas",
    ]
```

with

```python
def test_stem_folds_plurals():
    # caches, mousses and quizzes pin the named limits (spec R2).
    words = (
        "sneakers shoes kids bus glass watches dishes boxes dresses "
        "glasses quizzes sizes caches mousses"
    )
    assert [_stem(w) for w in words.split()] == [
        "sneaker",
        "shoe",
        "kid",
        "bus",
        "glass",
        "watch",
        "dish",
        "box",
        "dress",
        "glass",
        "quizz",
        "size",
        "cach",
        "mouss",
    ]
```

Append at the end of `tests/unit/test_products.py`:

```python


def test_keyword_key_folds_es_plurals():
    assert keyword_key("men watches") == keyword_key("men watch") == "men watch"
    assert keyword_key("kids shoes") == "kid shoe"


def test_rule_check_removes_an_es_plural_repeat():
    assert rule_check(
        "Zara Summer Dress", "Zara Summer Dress Dresses", ["Zara"]
    ) == ("Zara Summer Dress", "pass", [])


def test_missing_folds_an_es_plural_in_the_title():
    assert missing(
        "Titan Analog Dial Watches",
        ["Titan Men Watch", "Fossil Men Watch"],
        ["Titan"],
        keyword="men watches",
        backing=["men watches"],
    ) == ["men"]


def test_lenses_still_back_lens_for_allowed_text():
    # The one-sided set in _allowed_stems stays (spec R1).
    assert rule_check(
        "Acme Daily", "Acme Daily Lens", ["Acme"], allowed=["contact lenses"]
    ) == ("Acme Daily Lens", "pass", [])
```

- [ ] **Step 2: Run the two files to verify the new expectations fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q -p no:cacheprovider tests/unit/test_rivals.py tests/unit/test_products.py 2>&1 | tail -6`
Expected: `4 failed, 128 passed` — `test_stem_folds_plurals` (`'watche'` where `'watch'` is expected), `test_keyword_key_folds_es_plurals` (`'men watche' == 'men watch'`), `test_rule_check_removes_an_es_plural_repeat` (the tuple's status is `'adjusted'`, not `'pass'`), `test_missing_folds_an_es_plural_in_the_title` (`['men', 'watch'] == ['men']`). `test_lenses_still_back_lens_for_allowed_text` passes already.

- [ ] **Step 3: The new `_stem`**

In `packages/core/bsi_core/rivals.py`, replace

```python
def _stem(word: str) -> str:
    """Drop one trailing s on words longer than three characters, so
    sneakers/sneaker and kids/kid meet. ponytail: crude on purpose (glass
    -> glas on both sides, which still matches); a real stemmer is the
    upgrade path if topic words start missing slugs."""
    return word[:-1] if len(word) > 3 and word.endswith("s") else word
```

with

```python
# -es after these endings is a plural marker: watches, dishes, boxes,
# dresses, quizzes. Not after a plain z (sizes -> size).
_ES = ("ches", "shes", "xes", "sses", "zzes")


def _stem(word: str) -> str:
    """Fold plurals: drop "es" after ch, sh, x, ss or zz on words longer
    than four characters (watches -> watch, glasses -> glass), keep a
    word ending in ss (glass stays glass), else drop one trailing s on
    words longer than three characters (shoes -> shoe, kids -> kid).
    ponytail: suffix rules, not a stemmer; -ies stays as is (hoodies ->
    hoodie, accessories -> accessorie); a real stemmer is the upgrade
    path if topic words start missing slugs."""
    if len(word) > 4 and word.endswith(_ES):
        return word[:-2]
    if word.endswith("ss"):
        return word
    return word[:-1] if len(word) > 3 and word.endswith("s") else word
```

- [ ] **Step 4: Run the two files to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q -p no:cacheprovider tests/unit/test_rivals.py tests/unit/test_products.py 2>&1 | tail -3`
Expected: `132 passed` (32 + 100).

- [ ] **Step 5: Banned-word grep, then the backend gate**

Stage the three files (`git add packages/core/bsi_core/rivals.py tests/unit/test_rivals.py tests/unit/test_products.py`) and run the banned-word grep from Global Constraints on `git diff --cached -U0`. Expected: no match. Then run the Backend gate from Global Constraints with `gate-task1.txt`. Expected: `gate exit 0`; the file ends with `1570 passed, 2 deselected` (1566 + 4) and the metrics coverage line at 100%. (`ruff format .` may reflow the new test code; if it changed a file, re-stage it.)

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/rivals.py tests/unit/test_rivals.py tests/unit/test_products.py && git commit -m "feat(rivals): fold -es plurals in _stem

Drop es after ch, sh, x, ss or zz (watches -> watch, glasses -> glass)
and keep -ss words whole (glass stays glass); otherwise one trailing s
as before. Every caller picks it up: titles, repeats, keyword keys and
rival-page slugs now meet their singulars. caches, mousses and quizzes
are pinned as named limits.

<trailer>"
```

---

### Task 2: the two docstrings in `products.py`

**Files:**
- Modify: `packages/core/bsi_core/products.py:351-356` (`fold`), `:379-384` (`_allowed_stems`)

**Interfaces:**
- Consumes: `rivals._stem` from Task 1.
- Produces: nothing; docstrings only.

- [ ] **Step 1: Edit the two docstrings**

In `packages/core/bsi_core/products.py`, replace

```python
    """The text's tokens without 1-letter ones (the s of "men's"), each
    with one trailing s dropped (rivals._stem): sandals and sandal, mens
    and men meet. ponytail: crude on purpose; irregular plurals (feet)
    do not fold. The one place to swap in a real lemmatiser."""
```

with (the third line is exactly 80 characters, which ruff accepts)

```python
    """The text's tokens without 1-letter ones (the s of "men's"), each
    plural-folded by rivals._stem: sandals and sandal, mens and men,
    watches and watch meet. ponytail: crude on purpose; irregular plurals (feet)
    do not fold. The one place to swap in a real lemmatiser."""
```

Replace

```python
    ponytail: rivals._stem drops only one "s"; this patches -es for
    allowed words only."""
```

with

```python
    ponytail: rivals._stem folds -es only after ch, sh, x, ss and zz;
    this also folds -oes, -ses and -thes (lenses, clothes, potatoes) for
    allowed words only."""
```

- [ ] **Step 2: Check the module still imports and the two files still pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q -p no:cacheprovider tests/unit/test_products.py 2>&1 | tail -1`
Expected: `100 passed` (docstrings change no behaviour; this guards against a broken string literal).

- [ ] **Step 3: Banned-word grep, then the backend gate**

Stage the file (`git add packages/core/bsi_core/products.py`) and run the banned-word grep on `git diff --cached -U0`. Expected: no match. Then the Backend gate with `gate-task2.txt`. Expected: `gate exit 0`; `1570 passed, 2 deselected`.

- [ ] **Step 4: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py && git commit -m "docs(products): fold and _allowed_stems docstrings follow the new _stem

<trailer>"
```

---

## Self-review (plan vs spec)

- Spec coverage: §1 → Task 1 Step 3; §2's `_allowed_stems`/`fold` docstrings → Task 2; §2's tests → Task 1 Step 1; §2's expected counts (test_rivals.py 32, test_products.py +4, backend 1566 → 1570) → Steps 2, 4 and 5; §3 (docs, live check) is post-merge controller work.
- Departures from the spec, listed:
  1. Spec §3 says "two tasks (rivals, then products)" and §2 lists the four product tests under "`products.py` and the tests". The plan puts all five tests in Task 1 with the `_stem` change, because the three two-sided product cases depend only on `_stem`: placed in Task 2 they could never fail first (Task 1 would already have made them pass), so Task 2 would have no red step. Task 2 is the two docstrings only.
  2. The rivals test gains a one-line comment naming the limit pins (R2) and the lenses test a comment naming R1; the spec gives neither.
  3. The stem test builds its word list from one string split on spaces; the spec says "as one list" and names the words and expectations, which the plan uses exactly.
  4. Task 2 Step 2 runs test_products.py as a smoke check; the spec names no test for the docstrings.
- Placeholder scan: none (`<trailer>` is the Global Constraints' commit-trailer rule, `<workspace>` the SDD workspace path the task brief supplies).
- Type consistency: `_stem(word: str) -> str` unchanged in signature; `_ES` is a module-level tuple of `str`; the tests use the already-imported names.
