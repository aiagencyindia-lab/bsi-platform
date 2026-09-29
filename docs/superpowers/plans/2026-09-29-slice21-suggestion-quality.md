# Slice 21 Product-Suggestion Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop over-excluding generic words, drop size and colour noise from missing words, and remove words the rewrite invents.

**Architecture:**
- The parse asks for models without the product type.
- `missing` gains a keyword guard on its exclusions and a `NOISE_STEMS` filter.
- Stored titles carry a parse version (`TITLES_PARSE = 2`) that the cache checks.
- `rule_check` gains an `allowed` list and drops suggestion words whose stems come from nowhere.
- All code is in `packages/core/bsi_core/products.py`. There is no schema, API or web change.

**Tech Stack:** Python 3.13, SQLAlchemy 2, pydantic 2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-slice21-suggestion-quality-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB, the network or the worker loop.
- **Shared test DB:** tests use `bsi_test`, which is shared. Run `pgrep -fl pytest` first, and never run two suites at once.
- **Lint and types:** ruff line length is 80, and RUF001 rejects a literal curly apostrophe. `mypy --strict` runs over `packages/core/bsi_core`.
- **Prompt sentence:** the new `titles_prompt` sentence is exactly: "For each title also give its brand and its model or product-line name without the product type (for example "Taye 2.0", not "Taye 2.0 Sneaker"), each as written in the title, else an empty string."
- **`NOISE_WORDS`** is exactly: white, black, blue, red, green, pink, grey, gray, brown, navy, beige, tan, silver, gold, purple, orange, yellow, cream, multi, multicolor, color, colour, size, little, big.
- **`FUNCTION_WORDS`** is exactly: and, for, with, of, the, a, an, in, on, to, by, or.
- **`TITLES_PARSE`** is `2`.
- **Banned words:** copy (prompts, fixtures) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat` or `certain`.
- **Commit trailer:** the `Co-Authored-By` line from the latest session reminder.

## Changes to existing tests that the spec implies

| Test | Change | Task |
|---|---|---|
| `test_keep_present_drops_titles_absent_from_the_text` (unit) | expected title gains `"parse": 2` | 1 |
| every stored-title dict with `"model": ""` in `tests/integration/test_products_run.py` (the exact assertions in `test_one_search_…`, `test_an_error_search_…`, `test_a_search_under_the_old_query_…`, `test_store_names_…`, and the seeds of `test_a_fresh_search_…` and `test_a_search_under_the_old_query_…`) | gains `"parse": 2` | 1 |
| `test_a_row_parsed_without_brand_is_redone` | renamed `test_a_row_parsed_before_parse_2_is_redone`; seed has brand and model keys but no `parse`; expected title gains `"parse": 2` | 1 |
| the eight named `rule_check` unit tests | pass `allowed=` with the words their suggestions add; expected values unchanged | 2 |
| `test_a_failed_search_is_stored_and_the_run_goes_on` | expected suggestion `"Walkaroo Kids Sandals"` | 2 |

## File map

| File | Responsibility |
|---|---|
| `packages/core/bsi_core/products.py` | `NOISE_WORDS`/`NOISE_STEMS`, `TITLES_PARSE`, `FUNCTION_WORDS`, `missing(keyword=)`, `keep_present`, `titles_prompt`, `rule_check(allowed=)`, `run_products` |
| `tests/unit/test_products.py` | new and updated unit tests |
| `tests/integration/test_products_run.py` | parse-version fixtures, the renamed cache test, the invented-word run |
| docs | `docs/findings-slice21.md`, `docs/README.md`, the spec's Rulings, this plan's changes section |

---

### Task 1: Missing words: keyword guard, noise filter, model prompt and parse version

**Files:**
- Modify: `packages/core/bsi_core/products.py`: constants near `STOPWORDS`/`TOP_TITLES`; `missing`; `keep_present`; `titles_prompt`; the cache generator in `run_products`; and the `missing(...)` call in `run_products`.
- Test: `tests/unit/test_products.py`, `tests/integration/test_products_run.py`

**Interfaces:**
- Produces:
  - `missing(product_title: str, titles: Sequence[str], brand_names: Sequence[str], exclude: Sequence[str] = (), keyword: str = "") -> list[str]`
  - `keep_present(...) -> list[dict[str, Any]]`, where each dict has `title`, `domain`, `brand`, `model`, `parse`
  - `NOISE_WORDS`, `NOISE_STEMS`, `TITLES_PARSE`

- [ ] **Step 1: Write the failing unit tests.** In `tests/unit/test_products.py`, add `"parse": 2,` after `"model": "",` in `test_keep_present_drops_titles_absent_from_the_text`'s expected dict, and add:

```python
def test_titles_prompt_asks_for_the_model_without_the_product_type():
    tp = titles_prompt("kids sandals", "answer text", ["amazon.in"])
    assert "without the product type" in tp


def test_missing_never_excludes_a_keyword_word():
    titles = ["Kids Chase Sandal", "Kids Paley Sandal"]
    exclude = ["Kids Chase", "Kids Paley"]
    assert missing(
        "Boys Sandal", titles, ["X"], exclude=exclude, keyword="kids sandals"
    ) == ["kids"]
    assert missing("Boys Sandal", titles, ["X"], exclude=exclude) == []


def test_missing_skips_colour_and_size_words():
    titles = [
        "Taye Sneaker - Little Kid White",
        "Artie Sneaker - Little Kid White",
    ]
    got = missing("Black Kids Sports Shoe", titles, ["BSOAgentTestBrand"])
    assert got == ["sneaker"]


def test_dropped_still_flags_a_lost_colour():
    assert dropped("Black Shoe", "Shoe", []) == ["black"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_products.py -q`
Expected failures:
- The `keep_present` test fails on the missing `parse` key.
- The prompt test fails because the sentence is absent.
- The keyword test fails with `TypeError: missing() got an unexpected keyword argument 'keyword'`.
- The noise test fails with `['little', 'sneaker', 'white']`.

`test_dropped_still_flags_a_lost_colour` already passes: it pins behaviour that must not change.

- [ ] **Step 3: Implement the pure parts.** In `products.py`, after `STOPWORDS`, add:

```python
# missing() never suggests these (slice 21 spec §2). ponytail: English
# and closed; a real colour phrase ("white sneakers") is never suggested;
# a noise word is skipped even when it is in the keyword; outside
# footwear some are product words (cream, gold, silver, orange, plus
# size, hair color); toddler/youth/infant are not listed, and "kid" from
# "Little Kid" is still suggested.
NOISE_WORDS = frozenset(
    "white black blue red green pink grey gray brown navy beige tan silver "
    "gold purple orange yellow cream multi multicolor color colour size "
    "little big".split()
)
NOISE_STEMS = frozenset(_stem(w) for w in NOISE_WORDS)
```

Next to `TOP_TITLES`, add:

```python
# Stored titles carry this; a cached row parsed by an older prompt is
# searched again. ponytail: a bump re-searches every keyword (~$0.04).
TITLES_PARSE = 2
```

Change `missing` to:

```python
def missing(
    product_title: str,
    titles: Sequence[str],
    brand_names: Sequence[str],
    exclude: Sequence[str] = (),
    keyword: str = "",
) -> list[str]:
    """Words of the ranking titles the product title lacks, compared by
    stem (fold): at least 3 characters, not a number, not a stopword or
    a colour/size word (NOISE_STEMS), not a stem of the brand's names or
    of `exclude` (rival brands, models, competitor names) unless it is a
    stem of the product's keyword, in at least MIN_TITLES titles. The
    first surface form seen is reported; by title count, then stem;
    MAX_MISSING."""
    have = (
        fold_set(product_title)
        | _brand_stems(brand_names)
        | (_brand_stems(exclude) - _brand_stems([keyword]))
    )
```

In the loop, change `if stem in have:` to `if stem in have or stem in NOISE_STEMS:`. Leave the rest of the body unchanged.

In `keep_present`:
- Change the return annotation and the `out` annotation to `list[dict[str, Any]]`.
- Add `"parse": TITLES_PARSE,` after the `"model"` entry.
- In the docstring, replace the final "." after "(_named_in)" with "; each carries the parse version (TITLES_PARSE)."

In `titles_prompt`, replace the three lines from `"on its own. For each title also give its brand and its model or "` through `"string.\n"` with:

```python
        "on its own. For each title also give its brand and its model or "
        "product-line name without the product type (for example "
        '"Taye 2.0", not "Taye 2.0 Sneaker"), each as written in the '
        "title, else an empty string.\n"
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_products.py tests/unit/test_recommend_copy.py -q`
Expected: all pass.

- [ ] **Step 5: Write the failing integration changes.** In `tests/integration/test_products_run.py`:
1. After every `"model": "",` line and inside the one-line dict `{"title": "Kids Classic Sandal", "domain": "", "brand": "", "model": ""}`, add `"parse": 2`. This covers the exact assertions and the seeds of `test_a_fresh_search_is_reused_and_a_stale_one_redone` and `test_a_search_under_the_old_query_is_redone`.
2. Rename `test_a_row_parsed_without_brand_is_redone` to `test_a_row_parsed_before_parse_2_is_redone`, and change its seed to slice 20's shape (brand and model keys, no `parse`):

```python
    _fresh_row(
        owner,
        org,
        bid,
        [{"title": "Old Sandals", "domain": "", "brand": "", "model": ""}],
    )
```

Its expected first title keeps the `"parse": 2` from item 1.

- [ ] **Step 6: Run them to verify the renamed test fails**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest tests/integration/test_products_run.py -q`

Expected: `test_a_row_parsed_before_parse_2_is_redone` fails, because the row is still a hit under the old brand-key rule, so `len(engine.prompts) == 1` is false. The other tests pass: `keep_present` already writes `parse`, and seeds with `parse: 2` also have `brand`.

- [ ] **Step 7: Implement the run changes.** In the cache generator, replace the brand-key condition and its comment with:

```python
                    # a row from an older query wording, or parsed by an
                    # older titles_prompt (TITLES_PARSE), is searched again
                    if row.query == search_query(row.keyword)
                    and all(t.get("parse") == TITLES_PARSE for t in row.titles)
```

In the `missing(...)` call, add `keyword=p["keyword"],` after the `exclude=[...]` argument. Replace the `ponytail:` comment above that call (three lines today) with exactly these four lines at the same indent:

```python
                    # ponytail: a generic word in a model ("Classic") is
                    # excluded for this keyword, and one in a competitor's
                    # name or alias for every keyword that does not contain
                    # it (spec §1).
```

- [ ] **Step 8: Run the integration and unit files**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest tests/integration/test_products_run.py tests/unit/test_products.py tests/unit/test_recommend_copy.py -q`
Expected: all pass, including `test_a_row_with_no_titles_is_a_hit` and the idle-in-transaction probe.

Then check the parse condition:
1. Temporarily delete the `and all(t.get("parse") == TITLES_PARSE for t in row.titles)` clause.
2. Run `test_a_row_parsed_before_parse_2_is_redone` and confirm it fails.
3. Restore the clause, and confirm `git diff` shows only the intended changes.

- [ ] **Step 9: Gate and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100`

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests && git commit -m "fix(products): keyword guard, colour/size noise and parse version for missing words" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The rule check drops invented words

**Files:**
- Modify: `packages/core/bsi_core/products.py`: add `FUNCTION_WORDS` near `CONNECTORS`, add `_allowed_stems`, change `rule_check`, and change the `rule_check(...)` call in `run_products`.
- Test: `tests/unit/test_products.py`, `tests/integration/test_products_run.py`

**Interfaces:**
- Consumes: `missing` as it is after Task 1; `run_products` sets `p["missing"]` before the rewrite.
- Produces: `rule_check(original: str, suggestion: str, brand_names: Sequence[str], allowed: Sequence[str] = ()) -> tuple[str, str, list[str]]`.

- [ ] **Step 1: Write the failing unit tests.** In `tests/unit/test_products.py`, add:

```python
def test_rule_check_drops_an_invented_word():
    assert rule_check(
        "BSOAgentTestBrand Brown Men Casual Sandal",
        "BSOAgentTestBrand Brown Boys Casual Sandal Men",
        ["BSOAgentTestBrand"],
        allowed=["men sandals"],
    ) == ("BSOAgentTestBrand Brown Casual Sandal Men", "adjusted", [])


def test_rule_check_keeps_a_keyword_word():
    assert rule_check(
        "BSOAgentTestBrand Blue Boys Sandal",
        "BSOAgentTestBrand Blue Boys Sandal Kids",
        ["BSOAgentTestBrand"],
        allowed=["kids sandals"],
    ) == ("BSOAgentTestBrand Blue Boys Sandal Kids", "pass", [])


def test_rule_check_keeps_function_words_and_numbers():
    assert rule_check(
        "Walkaroo Sandal 3",
        "Walkaroo Sandal for Kids 3",
        ["Walkaroo"],
        allowed=["kids sandals"],
    ) == ("Walkaroo Sandal for Kids 3", "pass", [])


def test_rule_check_drops_an_invented_promotional_word():
    assert rule_check(
        "Walkaroo Sandal",
        "Walkaroo Sandal Sale",
        ["Walkaroo"],
        allowed=["kids sandals"],
    ) == ("Walkaroo Sandal", "adjusted", [])


def test_rule_check_allows_the_singular_of_an_es_plural():
    assert rule_check(
        "Titan Analog Dial",
        "Titan Analog Dial Watch",
        ["Titan"],
        allowed=["men watches"],
    ) == ("Titan Analog Dial Watch", "pass", [])


def test_rule_check_allows_attribute_words():
    assert rule_check(
        "Walkaroo Sandal",
        "Walkaroo Leather Sandal",
        ["Walkaroo"],
        allowed=["kids sandals", "Leather"],
    ) == ("Walkaroo Leather Sandal", "pass", [])
```

Then update the eight named tests so that each `rule_check` call passes `allowed=`. Expected values stay unchanged.
- `test_rule_check_restores_the_brand_the_original_had`: both calls get `allowed=["Summer"]`.
- `test_rule_check_passes_an_unchanged_suggestion`: `allowed=["Summer"]`.
- `test_rule_check_drops_a_word_that_repeats_an_earlier_token`: the second call gets `allowed=["Shoes"]`.
- `test_rule_check_keeps_punctuation_only_words`: `allowed=["Kids"]`.
- `test_rule_check_flags_dropped_words_for_review`: the first call gets `allowed=["Shoes"]`, the second `allowed=["Slipper"]`.
- `test_short_stopwords_are_not_flagged_as_dropped`: the `rule_check` call gets `allowed=["Piece"]`.
- `test_rule_check_trims_to_150_at_a_word_boundary` and `test_rule_check_strips_a_connector_the_trim_leaves_at_the_end`: `allowed=[" ".join(words)]`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_products.py -q`
Expected: every call that passes `allowed=` fails with `TypeError: rule_check() got an unexpected keyword argument 'allowed'`.

- [ ] **Step 3: Implement.** In `products.py`, after `CONNECTORS`, add:

```python
# rule_check keeps these even when the rewrite adds them.
FUNCTION_WORDS = frozenset(
    {"and", "for", "with", "of", "the", "a", "an", "in", "on", "to", "by", "or"}
)


def _allowed_stems(
    original: str, allowed: Sequence[str], brand_names: Sequence[str]
) -> frozenset[str]:
    """Stems a suggestion word may come from: the original title, the
    allowed texts (keyword, missing words, the product's description,
    category and attribute values), the brand's names; plus, for an
    allowed token ending in "es", its singular ("watches" -> watch).
    ponytail: rivals._stem drops only one "s"; this patches -es for
    allowed words only."""
    text = " ".join(allowed)
    es = {_stem(t[:-2]) for t in tokens(text) if len(t) > 3 and t.endswith("es")}
    return (
        fold_set(original)
        | fold_set(text)
        | _brand_stems(brand_names)
        | frozenset(es)
    )
```

ruff format wraps the `es =` line over three lines; accept its layout.

Change `rule_check`'s signature to `(original: str, suggestion: str, brand_names: Sequence[str], allowed: Sequence[str] = ())`, and add to its docstring: "a word whose stems come from none of the original title, `allowed` or the brand's names is dropped (function words and numbers are kept) right after the brand step;". After the brand-prepend `if` block, insert:

```python
    ok = _allowed_stems(original, allowed, brand_names)
    title = " ".join(
        w
        for w in title.split()
        if not (stems := fold_set(w))
        or stems & ok
        or all(t in FUNCTION_WORDS or t.isdigit() for t in tokens(w))
    )
```

In `run_products`, change the `rule_check(p["title"], suggestion, names)` call to:

```python
                    title, status, lost = rule_check(
                        p["title"],
                        suggestion,
                        names,
                        allowed=[
                            p["keyword"],
                            *p["missing"],
                            p["description"] or "",
                            p["category"] or "",
                            *(str(v) for v in (p["attributes"] or {}).values()),
                        ],
                    )
```

- [ ] **Step 4: Run the unit tests**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_products.py -q`
Expected: all pass.

- [ ] **Step 5: Write the integration changes.** In `tests/integration/test_products_run.py`:
1. Give `_generator` a `rewrite=None` parameter, placed after `titles=None`. In its rewrite branch, change `"title": "Walkaroo Kids Summer Sandals Sandals",` to `"title": rewrite or "Walkaroo Kids Summer Sandals Sandals",`.
2. In `test_a_failed_search_is_stored_and_the_run_goes_on`, change the expected suggestion to `"Walkaroo Kids Sandals"`.
3. Add after `test_a_row_with_no_titles_is_a_hit`:

```python
def test_the_rewrite_cannot_add_an_invented_word(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    gen = _generator(rewrite="Walkaroo Boys Toddler Sandal Kids")
    _, rows, _searches = _run(owner, org, bid, gen)
    assert (rows[0].suggested_title, rows[0].rule_check) == (
        "Walkaroo Boys Sandal Kids",
        "adjusted",
    )
```

- [ ] **Step 6: Run the integration file**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest tests/integration/test_products_run.py -q`
Expected: all pass.

Then check the call site:
1. Temporarily change the `run_products` call's `allowed=[...]` to `allowed=[p["keyword"]]`.
2. Run `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` and confirm it fails: "Summer", a missing word, would be dropped.
3. Restore the call, and confirm `git diff` shows only the intended changes.

- [ ] **Step 7: Gate and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100`

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests && git commit -m "fix(products): the rule check drops words the rewrite invents" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Docs: findings, index, rulings, plan changes

**Files:**
- Create: `docs/findings-slice21.md`
- Modify: `docs/README.md` (three rows after the slice 20 rows), the spec's `## Rulings`, and this plan's `## Changes made during execution`

- [ ] **Step 1: Findings.** Write `docs/findings-slice21.md` in the style of `docs/findings-slice20.md`, with three sections:
  - `## 1. What was built`: the constants, `missing(keyword=)`, the noise filter, the parse version, `rule_check(allowed=)`, and a commit table from `git log --oneline main..HEAD` with a "(this commit)" row.
  - `## 2. Live check on dev`: exactly "Not yet run. The controller runs it after the user approves; results are recorded here then."
  - `## 3. Deferred and untested`: every `minor (deferred)` and `parked` ledger line not marked fixed, the spec's known ceilings, and its Out of scope list.
- [ ] **Step 2: README rows** for the spec, the plan and the findings, in the slice 20 rows' format:
  - spec: "Design spec: product-suggestion quality after slice 20's second live check — the parse asks for models without the product type, a keyword guard on exclusions, colour and size words never suggested, a parse version on cached titles, and the rule check dropping words the rewrite invents; with the rulings made during the build."
  - plan: "Implementation plan, Tasks 1–3, with the changes made during execution."
  - findings: "Results: what was built, the live check on dev (not yet run), and what is deferred or untested."
- [ ] **Step 3: Rulings.** Copy each ledger ruling into the spec in the slice 20 format (Decided / Found by / Why / Cost if wrong). If there are none, replace "None yet. Rulings made during execution are added here with their R-number." with "None."
- [ ] **Step 4: Plan changes.** List every deviation from Tasks 1–3 in this plan's changes section.
- [ ] **Step 5: Coverage check.** Run a scripted grep over the ledger for every ruling ID, every `minor (deferred)` line and every `parked` line. Print which of findings, the spec or this plan's changes section covers each. Report and fix misses.
- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add docs && git commit -m "docs: slice 21 findings, index and rulings" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review

- **Spec coverage:**

  | Spec part | Covered by |
  |---|---|
  | §1: prompt sentence, `missing(keyword=)` guard, `run_products` passing the keyword, `TITLES_PARSE` in `keep_present` and in the cache, return annotation | Task 1 |
  | §2: `NOISE_WORDS`/`NOISE_STEMS`, `missing` only | Task 1 |
  | §3: `rule_check(allowed=)`, allowed stems with the `-es` rule, `FUNCTION_WORDS` and numbers, the step's position, `run_products` passing keyword, missing, description, category and attribute values | Task 2 |
  | §4: unit and integration tests | Tasks 1 and 2 |
  | §5: dev re-check | the controller, after Task 3 |
  | Gates | the controller |

- **§4 values, word for word:**
  - `titles_prompt` contains "without the product type".
  - The Chase/Paley call gives `["kids"]` with `keyword` and `[]` without it.
  - The Taye/Artie call gives `["sneaker"]`.
  - `dropped("Black Shoe", "Shoe", [])` gives `["black"]`.
  - The three original `rule_check` cases (LC-06 "Boys" dropped and `adjusted`; Blue Boys "Kids" kept and `pass`; "for Kids 3" `pass`).
  - The Sale case gives `adjusted`.
  - The Titan "watches"/"Watch" case gives `pass`.
  - The Leather case gives `pass`.
  - The eight named tests with `allowed`.
  - The `keep_present` expectation gains `parse`.
  - The stored-title assertions and the two seeds gain `parse`.
  - The no-parse-key test.
  - The failed-search expected title.
  - The Toddler run: `"Walkaroo Boys Sandal Kids"` and `adjusted`.
- **Traced by hand:**
  - Toddler run:
    - The seed "Walkaroo Boys Sandal 0" has keyword "kids sandals" and missing `["summer"]`.
    - "Toddler" has no allowed stem, so it is dropped. The "0" is ignored by `dropped`, so the result is `adjusted`.
  - Default rewrite in `test_one_search_…`:
    - The suggestion "Walkaroo Kids Summer Sandals Sandals" keeps every word, since "Summer" is a missing word.
    - The repeat check drops the second "Sandals", which leaves "Walkaroo Kids Summer Sandals".
    - The original's "Boys" is lost, so the status stays `review` with `["boys"]`.
  - Failed-search test:
    - Its missing list is `[]`, so "Summer" is dropped and the title is "Walkaroo Kids Sandals".
    - That test asserts only the title.
  - `_allowed_stems` for "men watches": "watches" gives `watch`. For "glasses", "glas" equals `_stem("glass")`.
  - The seeded products have no description, category or attributes, so `p["description"] or ""` and the related fallbacks give `""`.
  - The spec reviewer checked every named existing test with a local copy of this design.
- **Fixtures vs banned words:** the fixtures use Chase, Paley, Taye, Artie, Titan Analog Dial Watch, Leather, Sale, Toddler and Old Sandals. None is a banned word, and neither is the new prompt sentence.
- **Types:**
  - `_brand_stems` takes `Sequence[str]`, and `[keyword]` fits.
  - `keep_present` returns `list[dict[str, Any]]`, so its int `parse` passes mypy.
  - `_allowed_stems` returns `frozenset[str]`.
  - `rule_check`'s new parameter defaults to `()`.
- **Every place this plan departs from the spec's text:**
  1. The spec names no helper; the plan adds `_allowed_stems`.
  2. The spec names neither test, and the plan names them `test_a_row_parsed_before_parse_2_is_redone` (renamed) and `test_the_rewrite_cannot_add_an_invented_word`.
  3. `test_dropped_still_flags_a_lost_colour` passes before Task 1. It pins behaviour that must not change, so it is never seen failing.
  4. Task 1 Step 8 and Task 2 Step 6 add delete-and-see-it-fail checks that the spec does not ask for.
  5. Task 1 and Task 2 each run the backend gate. The controller also runs both gates.
  6. More tests are never seen failing, because each task implements before it edits the integration file: the integration `"parse": 2` assertions (Task 1), `test_the_rewrite_cannot_add_an_invented_word` and the failed-search test's new expected title (Task 2). The delete-and-fail checks in Task 1 Step 8 and Task 2 Step 6 cover the parse condition and the `missing` part of `allowed`.
  7. `keyword=p["keyword"]` in `run_products`'s `missing` call has no integration test; the unit test pins the guard in `missing`. The spec asks for none.
  8. The `NOISE_WORDS` comment carries spec §2's ceiling in shortened wording; the spec's text is the reference.

## Changes made during execution

- Task 1 went as written (commit 24c5726), with these differences (from task-1-report.md):
  - ruff format split the one-line `Kids Classic Sandal` dict in `tests/integration/test_products_run.py` over several lines once `"parse": 2` was added (line length 80). Task 1 does not mention this wrap.
  - Step 8's parse-clause check restored the file from a scratchpad copy rather than re-typing the clause; a grep confirmed the clause was back.
  - The implementer ran the full suite a second time, after the gate and not alongside another run, only to read the 2 warning names.
  - The integration `"parse": 2` assertions were written after the implementation (plan departure 6), so they were never seen failing on their own.
- Task 2 went as written (commit 4e3f668), with these differences (from task-2-report.md):
  - ruff format wrapped the `es =` line in `_allowed_stems` over three lines, as the plan expected. It also wrapped the `rewrite or "Walkaroo Kids Summer Sandals Sandals"` line in `tests/integration/test_products_run.py` over two lines, which the plan does not mention.
  - `test_the_rewrite_cannot_add_an_invented_word` and the failed-search test's new expected title were written after the implementation (plan departure 6), so they were never seen failing on their own. The call-site check in Step 6 covers the wiring.
  - Step 6's call-site check restored `products.py` from a scratchpad backup; `git diff --stat` then showed only the three intended files.
  - The report names only one of the gate's 2 warnings. The implementer captured only the tail of the output and did not run the suite again.
- Task 3 (commit 1e10fa4): the spec's `## Rulings` is "None.", because the ledger records no rulings. The Write tool refused to let a subagent create `docs/findings-slice21.md`, so the controller created it as a one-line stub. The implementer then filled it with the Edit tool.
- Task 3 fix round 1 (commit a1e3bba): findings §1 states the gate warnings as each run observed them; "targets" replaces "fixes" before §2; the findings title style; and the `ponytail:` comment attribution.
- Ruling R1, from the final whole-branch review (this commit): `rule_check` falls back to the original title when the invented-word step leaves no word. This goes beyond Task 2 and spec §3; the spec now records it. New unit tests: `test_rule_check_falls_back_to_the_original_when_every_word_is_invented` (seen failing first), plus two pins, `test_missing_skips_a_noise_word_even_in_the_keyword` and `test_rule_check_allows_glass_for_glasses`.
