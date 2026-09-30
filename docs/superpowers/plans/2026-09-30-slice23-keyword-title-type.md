# Slice 23 Keyword Title Type Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Search the audience plus the title's product type ("men flip flops") when a product's title and category name different types, and search a colour or size keyword only when no keyword without one names the title's type and none can be built.

**Architecture:**
- `title_first` puts a built keyword first: the first keyword's audience plus the title's type. It uses a new helper `_type_word`, which holds the lines `fit_rank` uses today to find a keyword's category word, and a closed `AUDIENCE_WORDS` list.
- `drop_noise_terms` removes keywords that contain a colour or size word.
- `choose_keywords` does one product's whole keyword choice and falls back to the unfiltered samples when the product would otherwise have no keyword, or (Task 4, Ruling R2) when the guarded result's first keyword names a type the title does not and the unfiltered result's names one it does. `run_products` calls it.
- All code is in `packages/core/bsi_core/products.py`. There is no prompt, schema, API or web change.

**Tech Stack:** Python 3.13, SQLAlchemy 2, pydantic 2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-slice23-keyword-title-type-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice23-keyword-title-type`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB, the network or the worker loop. Never call a model.
- **Shared test DB:** tests use `bsi_test`, which is shared. Run `pgrep -fl pytest` first, and never run two suites at once.
- **Tool refusals:** if a tool refuses, stop and report BLOCKED. Do not work around it.
- **Lint and types:** ruff line length is 80, and RUF001 rejects a literal curly apostrophe. `mypy --strict` runs over `packages/core/bsi_core`.
- **`AUDIENCE_WORDS`** is exactly: men, women, kids, boys, girls, unisex, baby.
- **Unchanged:** `keyword_prompt` and every other prompt, `vote`, `drop_brand_terms`, `keyword_key`, the run-wide `key_map`, `NOISE_WORDS`, the cache-hit rule, `missing`, `rule_check`, the schema, the API and the web app. `fit_rank` keeps its behaviour and its docstring.
- **Banned words:** copy (comments, fixtures) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat` or `certain`.
- **Backend gate:** `uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100`
- **Commit trailer:** the `Co-Authored-By` line from the latest session reminder.

## Changes to existing tests that the spec implies

None. The three `fit_rank` tests, the three `vote` tests, the `drop_brand_terms` test and every existing integration test keep their values.

## From the spec review (for findings §4)

The last spec re-review approved the spec and left two minor notes. Task 3 records both in findings §4:

- `title_first`'s audience exclusion applies to the other keywords, not to the first. If the model's first keyword is itself an audience-word phrase ("casual men"), `title_first` returns the keywords as given and `fit_rank` searches it as today. The spec's last ceiling covers this loosely; "including the first keyword" would make it exact.
- `types` removes audience stems but not colour stems, so in `choose_keywords`' unfiltered fallback a phrase such as "flip flop navy" counts as title-fitting. The colour stays out of the built keyword (`ok - NOISE_STEMS`): "men slippers", "flip flop navy" and "cushioned flip flops" give "men flip flop".

## File map

| File | Responsibility |
|---|---|
| `packages/core/bsi_core/products.py` | `_type_word`, `fit_rank` using it, `AUDIENCE_WORDS`/`AUDIENCE_STEMS`, `title_first`, `drop_noise_terms`, `choose_keywords`, the `NOISE_WORDS` comment, the keyword step in `run_products` |
| `tests/unit/test_products.py` | new unit tests for the four new functions |
| `tests/integration/test_products_run.py` | 1 new run test |
| docs | `docs/findings-slice23.md`, `docs/README.md`, the spec's Rulings, this plan's changes section |

---

### Task 1: The built fallback: `_type_word` and `title_first`

**Files:**
- Modify: `packages/core/bsi_core/products.py`: `fit_rank` (lines 459-491) and the lines right after it.
- Test: `tests/unit/test_products.py` (the import list at lines 8-32, and new tests appended at the end of the file).

**Interfaces:**
- Consumes (all in `products.py`, unchanged): `fold`, `fold_set`, `tokens`, `keyword_key`, `_stem`, `CATEGORY_CUTS`, `STOPWORDS`, `NOISE_STEMS`, `MAX_KEYWORDS`.
- Produces:
  - `_type_word(keyword: str) -> str | None`
  - `AUDIENCE_WORDS: frozenset[str]`, `AUDIENCE_STEMS: frozenset[str]`
  - `title_first(keywords: Sequence[str], title: str) -> list[str]`

- [ ] **Step 1: Write the failing tests.** In `tests/unit/test_products.py`, add `_type_word` and `title_first` to the names imported from `bsi_core.products`, each in its sorted position: `_type_word` right after `TitleSet` (it sorts first among the functions), and `title_first` right after `search_query`. Then append at the end of the file:

```python
T = "BSOAgentTestBrand Men Flip Flop Navy"
W = "Walkaroo Boys Sandal 0"
CASUAL = "BSOAgentTestBrand Men Casual Sandal Brown"


def test_type_word_is_the_category_word_fit_rank_reads():
    keywords = (
        "men slippers",
        "slippers for men",
        "men slip on shoes",
        "for",
        "",
    )
    assert [_type_word(k) for k in keywords] == [
        "slipper",
        "slipper",
        "shoe",
        "for",
        None,
    ]


def test_title_first_builds_the_audience_plus_the_title_type():
    assert title_first(["men slippers", "cushioned flip flops"], T) == [
        "men flip flops",
        "men slippers",
        "cushioned flip flops",
    ]
    assert title_first(["slippers for men", "daily wear flip flops"], T) == [
        "men flip flops",
        "slippers for men",
        "daily wear flip flops",
    ]


def test_title_first_uses_an_offered_keyword_in_its_own_spelling():
    assert title_first(
        ["men slippers", "cushioned flip flops", "mens flip flops"], T
    ) == ["mens flip flops", "men slippers", "cushioned flip flops"]


def test_title_first_leaves_the_keywords_when_it_cannot_build():
    # The first keyword fits the title.
    assert title_first(
        ["kids slippers", "kids flip flops"],
        "BSOAgentTestBrand Kids Slipper Grey",
    ) == ["kids slippers", "kids flip flops"]
    # No keyword fits the title.
    assert title_first(
        ["men slippers", "cushioned slippers"],
        "BSOAgentTestBrand Men Thong Navy",
    ) == ["men slippers", "cushioned slippers"]
    # No audience word.
    assert title_first(["slippers", "flip flops"], T) == [
        "slippers",
        "flip flops",
    ]
    assert title_first([], T) == []


def test_title_first_caps_at_max_keywords():
    assert title_first(
        ["men slippers", "a", "b", "c", "cushioned flip flops"], T
    ) == ["men flip flops", "men slippers", "a", "b", "c"]


def test_title_first_keeps_audience_words_out_of_the_type():
    assert title_first(["kids slippers", "boys sandals"], W) == [
        "kids sandals",
        "kids slippers",
        "boys sandals",
    ]
    assert title_first(["kids slippers", "sandals for boys"], W) == [
        "kids sandals",
        "kids slippers",
        "sandals for boys",
    ]


def test_title_first_keeps_only_words_every_fitting_keyword_shares():
    assert title_first(
        ["men floaters", "casual sandals", "floater sandals"], CASUAL
    ) == ["men sandals", "men floaters", "casual sandals", "floater sandals"]
    # ponytail ceiling: with one fitting keyword its style word stays.
    assert title_first(["men floaters", "casual sandals"], CASUAL) == [
        "men casual sandals",
        "men floaters",
        "casual sandals",
    ]


def test_title_first_ignores_a_keyword_that_fits_only_by_an_audience_word():
    assert title_first(["kids slippers", "slippers boys"], W) == [
        "kids slippers",
        "slippers boys",
    ]
    assert title_first(
        ["men slippers", "cushioned flip flops", "casual men"], T
    ) == [
        "men flip flops",
        "men slippers",
        "cushioned flip flops",
        "casual men",
    ]


def test_title_first_builds_nothing_for_two_title_types():
    assert title_first(
        ["men slippers", "flip flops", "men thongs"], "X Men Flip Flop Thong"
    ) == ["men slippers", "flip flops", "men thongs"]


def test_title_first_never_builds_in_a_colour_word():
    assert title_first(["men slippers", "navy flip flops"], T) == [
        "men flip flops",
        "men slippers",
        "navy flip flops",
    ]
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/unit/test_products.py -k "type_word or title_first"`

Expected: an error while collecting `tests/unit/test_products.py`, `ImportError: cannot import name '_type_word' from 'bsi_core.products'`.

- [ ] **Step 3: Move `fit_rank`'s category-word lines into `_type_word`.** In `packages/core/bsi_core/products.py`, insert this function between the `CATEGORY_CUTS` line and `def fit_rank`:

```python
def _type_word(keyword: str) -> str | None:
    """The keyword's category word: the last folded word before its
    first CATEGORY_CUTS token, or its last folded word if nothing folds
    before the cut; None if nothing folds."""
    words = fold(keyword)
    if not words:
        return None
    toks = tokens(keyword)
    cut = next((i for i, t in enumerate(toks) if t in CATEGORY_CUTS), len(toks))
    head = fold(" ".join(toks[:cut]))
    return (head or words)[-1]
```

Then, in `fit_rank`, replace its loop:

```python
    for k in keywords:
        words = fold(k)
        if not words:
            continue
        toks = tokens(k)
        cut = next(
            (i for i, t in enumerate(toks) if t in CATEGORY_CUTS), len(toks)
        )
        head = fold(" ".join(toks[:cut]))
        word = (head or words)[-1]
        if word in in_title:
            first.append(k)
        elif word in in_other:
            second.append(k)
    return first + second
```

with:

```python
    for k in keywords:
        word = _type_word(k)
        if word is None:
            continue
        if word in in_title:
            first.append(k)
        elif word in in_other:
            second.append(k)
    return first + second
```

Leave `fit_rank`'s signature and docstring as they are.

- [ ] **Step 4: Add `AUDIENCE_WORDS` and `title_first`.** Insert right after `fit_rank`, before `def missing`:

```python
# Never part of a built keyword's type words (slice 23 spec §2).
AUDIENCE_WORDS = frozenset("men women kids boys girls unisex baby".split())
AUDIENCE_STEMS = frozenset(_stem(w) for w in AUDIENCE_WORDS)


# ponytail: the audience is whatever is left of the first keyword, in
# the model's spelling ("men house slippers" -> "men house flip flops",
# "mens slippers" -> "mens flip flops"); audience-then-type order suits
# English; with one title-fitting keyword a style word the title has too
# is kept ("men casual sandals"); title-fitting keywords that name two
# different title types share no word, so nothing is built;
# AUDIENCE_WORDS is closed and English only; observed on footwear only;
# it depends on the model's first keyword being the audience plus the
# category's type; a title word that is not a product type can count as
# one, since the rule only checks that a keyword's type word is in the
# title and is not an audience word.
def title_first(keywords: Sequence[str], title: str) -> list[str]:
    """When the first keyword names a type the title does not, and
    other keywords name one it does, put the first keyword's audience
    plus the title's type first ("men slippers" and "cushioned flip
    flops" for "Men Flip Flop Navy" -> "men flip flops"); an offered
    keyword with the same key is used in its own spelling. Otherwise
    the keywords as given. At most MAX_KEYWORDS."""
    if not keywords:
        return []
    in_title = fold_set(title)
    word = _type_word(keywords[0])
    if word is None or word in in_title:
        return list(keywords)
    types = in_title - AUDIENCE_STEMS
    fits = [k for k in keywords if _type_word(k) in types]
    if not fits:
        return list(keywords)
    audience = [
        t
        for t in tokens(keywords[0])
        if len(t) > 1 and _stem(t) != word and t not in STOPWORDS
    ]
    ok = in_title - {_stem(t) for t in audience}
    ok = ok - AUDIENCE_STEMS - NOISE_STEMS
    for k in fits:
        ok &= fold_set(k)
    kind = [t for t in tokens(fits[0]) if _stem(t) in ok]
    if not audience or not kind:
        return list(keywords)
    built = " ".join([*audience, *kind])
    key = keyword_key(built)
    first = next((k for k in keywords if keyword_key(k) == key), built)
    rest = [k for k in keywords if keyword_key(k) != key]
    return [first, *rest][:MAX_KEYWORDS]
```

- [ ] **Step 5: Run the keyword tests to see them pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/unit/test_products.py -k "type_word or title_first or fit_rank or vote or drop_brand"`

Expected: 17 passed (the 10 new tests, the 3 `fit_rank` tests, the 3 `vote` tests and the `drop_brand_terms` test).

- [ ] **Step 6: Run the backend gate** (Global Constraints). If `ruff check` reports the import list as unsorted (I001), run `uv run ruff check --fix tests/unit/test_products.py` and re-run the gate. Expected: ruff and mypy clean, all tests pass, metrics coverage 100%. Record the pass count and the names of any warnings.

- [ ] **Step 7: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests/unit/test_products.py && git commit -m "feat(products): build the audience plus the title's type as a keyword" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The guard, `choose_keywords` and the run

**Files:**
- Modify: `packages/core/bsi_core/products.py`: the comment above `NOISE_WORDS` (lines 327-332), the lines after `drop_brand_terms` (line 453), the lines after `title_first`, and the keyword lines in `run_products` (`ranked = vote(...)` and `fitted = fit_rank(...)`, lines 907-913 before Task 1).
- Test: `tests/unit/test_products.py` (import list, new tests at the end), `tests/integration/test_products_run.py` (1 new test at the end).

**Interfaces:**
- Consumes: `title_first(keywords: Sequence[str], title: str) -> list[str]` from Task 1; `vote`, `drop_brand_terms`, `fit_rank`, `fold_set`, `NOISE_STEMS` (unchanged).
- Produces:
  - `drop_noise_terms(keywords: Sequence[str]) -> list[str]`
  - `choose_keywords(samples: Sequence[Sequence[str]], brand_names: Sequence[str], title: str, category: str | None, description: str | None) -> list[str]`

- [ ] **Step 1: Write the failing unit tests.** In `tests/unit/test_products.py`, add `choose_keywords` and `drop_noise_terms` to the names imported from `bsi_core.products`, each in its sorted position: `choose_keywords` right after `_type_word`, and `drop_noise_terms` right after `drop_brand_terms`. Then append at the end of the file (`T`, `W` and `B` already exist at module level, from Task 1 and slice 22):

```python
def test_drop_noise_terms_removes_colour_and_size_keywords():
    assert drop_noise_terms(
        ["men slippers", "navy flip flops", "men flip flop navy"]
    ) == ["men slippers"]
    assert drop_noise_terms(["navy flip flops", "blue flip flops"]) == []
    assert drop_noise_terms(
        ["free size slippers", "little kids sandals", "kids sandals"]
    ) == ["kids sandals"]


# Probe 4's samples for LC-05 (slice 23 spec).
S4 = [
    [
        "men slippers",
        "men flip flop navy",
        "navy flip flops",
        "cushioned flip flops",
        "daily use flip flop",
    ],
    ["men slippers", "men flip flops", "navy flip flops", "cushioned slippers"],
    [
        "men slippers",
        "men flip flops",
        "navy flip flops",
        "cushioned flip flops",
    ],
]


def test_choose_keywords_searches_the_audience_plus_the_title_type():
    assert choose_keywords(
        S4, B, T, "Slippers", "Cushioned flip flop for daily use"
    ) == [
        "men flip flops",
        "cushioned flip flops",
        "daily use flip flop",
        "men slippers",
        "cushioned slippers",
    ]


def test_choose_keywords_one_all_colour_sample_brings_no_colour_back():
    samples = [
        ["navy flip flops"],
        ["navy flip flops", "men slippers"],
        ["men slippers", "men flip flops"],
    ]
    assert choose_keywords(samples, B, T, "Slippers", None) == [
        "men flip flops",
        "men slippers",
    ]


def test_choose_keywords_falls_back_when_the_product_has_no_other_keyword():
    # Every keyword has a colour.
    assert choose_keywords(
        [["navy flip flops", "blue flip flops"]], B, T, "Slippers", None
    ) == ["navy flip flops", "blue flip flops"]
    # Only a brand phrase is left after the guard.
    assert choose_keywords(
        [["walkaroo sandals", "navy sandals"]], ["Walkaroo"], W, None, None
    ) == ["navy sandals"]
    assert choose_keywords([], B, T, None, None) == []


def test_choose_keywords_an_audience_word_keyword_does_not_stop_the_build():
    assert choose_keywords(
        [["kids slippers", "boys sandals", "slippers boys"]] * 3,
        ["Walkaroo"],
        W,
        None,
        None,
    ) == ["kids sandals", "boys sandals", "slippers boys"]
```

- [ ] **Step 2: Write the failing integration test.** Append at the end of `tests/integration/test_products_run.py`:

```python
def test_the_searched_keyword_has_the_title_type_and_no_colour(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    engine = FakeEngine()
    gen = _generator(
        keywords=["kids slippers", "blue sandals", "strap sandals"]
    )
    job, rows, _searches = _run(owner, org, bid, gen, engine)
    assert job.status == "done"
    # "kids slippers" names a type the title ("Walkaroo Boys Sandal 0")
    # does not, so its audience joins the title's type; "blue sandals" is
    # dropped as a colour keyword.
    assert rows[0].keyword == "kids sandals"
    assert rows[0].keywords == ["kids sandals", "strap sandals"]
    assert engine.prompts == [
        (products.search_query("kids sandals"), "IN", "en")
    ]
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/unit/test_products.py -k "drop_noise or choose_keywords"`

Expected: an error while collecting `tests/unit/test_products.py`, `ImportError: cannot import name 'choose_keywords' from 'bsi_core.products'`.

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/integration/test_products_run.py -k searched_keyword_has`

Expected: 1 failed, with `AssertionError: assert 'blue sandals' == 'kids sandals'`: today the first title-fitting keyword is searched, and "kids slippers" is dropped because the seed has no category or description.

- [ ] **Step 4: Update the `NOISE_WORDS` comment.** In `packages/core/bsi_core/products.py`, replace the six comment lines above `NOISE_WORDS`:

```python
# missing() never suggests these (slice 21 spec §2). ponytail: English
# and closed; a real colour phrase ("white sneakers") is never suggested;
# a noise word is skipped even when it is in the keyword; outside
# footwear some are product words (cream, gold, silver, orange, plus
# size, hair color); toddler/youth/infant are not listed: since slice 22
# missing() suggests such a word only when the product's data backs it.
```

with:

```python
# missing() never suggests these (slice 21 spec §2), and the keyword
# choice drops keywords that contain them (slice 23 spec §1). ponytail:
# English and closed; a real colour phrase ("white sneakers") is never
# suggested; a noise word is skipped even when it is in the keyword;
# outside footwear some are product words (cream, gold, silver, orange,
# plus size, hair color); toddler/youth/infant are not listed: since
# slice 22 missing() suggests such a word only when the product's data
# backs it.
```

- [ ] **Step 5: Add `drop_noise_terms`.** Insert right after `drop_brand_terms`, before the `CATEGORY_CUTS` comment:

```python
# ponytail: a real colour or size phrase that shoppers type ("white
# sneakers", "little kids sandals", "big kids shoes") is searched only
# when the product has no other fitting keyword (choose_keywords);
# outside footwear some are product words (gold, cream, plus size);
# English only.
def drop_noise_terms(keywords: Sequence[str]) -> list[str]:
    """Keep a keyword only if none of its stems is a colour or size
    word (NOISE_STEMS)."""
    return [k for k in keywords if not fold_set(k) & NOISE_STEMS]
```

- [ ] **Step 6: Add `choose_keywords`.** Insert right after `title_first`, before `def missing`:

```python
def choose_keywords(
    samples: Sequence[Sequence[str]],
    brand_names: Sequence[str],
    title: str,
    category: str | None,
    description: str | None,
) -> list[str]:
    """One product's keywords, the searched one first: the vote over
    the samples without colour and size keywords, without brand terms,
    the title's type first (title_first), then fit_rank. If that leaves
    nothing, the same over the samples as given."""

    def pick(lists: Sequence[Sequence[str]]) -> list[str]:
        ranked = drop_brand_terms(vote(lists), brand_names)
        return fit_rank(
            title_first(ranked, title), title, category, description
        )

    return pick([drop_noise_terms(s) for s in samples]) or pick(samples)
```

- [ ] **Step 7: Call it from `run_products`.** Replace:

```python
                ranked = vote([sm.get(i, []) for sm in samples])
                fitted = fit_rank(
                    drop_brand_terms(ranked, names),
                    p["title"],
                    p["category"],
                    p["description"],
                )
```

with:

```python
                fitted = choose_keywords(
                    [sm.get(i, []) for sm in samples],
                    names,
                    p["title"],
                    p["category"],
                    p["description"],
                )
```

Leave the `p["keywords"] = [...]` and `p["keyword"] = ...` lines that follow as they are.

- [ ] **Step 8: Run the tests to see them pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/unit/test_products.py tests/integration/test_products_run.py`

Expected: 113 passed (88 unit, 25 integration).

- [ ] **Step 9: Check that the guard is wired.** (Step 3's failure, `'blue sandals' == 'kids sandals'`, already shows the build is not wired before Step 7.)
  1. Copy the file to the session scratchpad, a path outside the repo: `cd /Users/vineet/Downloads/ADK/bsi-platform && cp packages/core/bsi_core/products.py /private/tmp/claude-501/-Users-vineet-Downloads-ADK-brand-search-optimization/57875675-70cf-46e9-a368-f0f1091f1ba0/scratchpad/slice23-products-backup.py`.
  2. In `choose_keywords`, change `return pick([drop_noise_terms(s) for s in samples]) or pick(samples)` to `return pick(samples)`.
  3. Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_products_run.py -k searched_keyword_has`. Expected: 1 failed on the `keywords` assertion, with `At index 1 diff: 'blue sandals' != 'strap sandals'` (the list is `['kids sandals', 'blue sandals', 'strap sandals']`).
  4. Restore the file from that copy (`cd /Users/vineet/Downloads/ADK/bsi-platform && cp /private/tmp/claude-501/-Users-vineet-Downloads-ADK-brand-search-optimization/57875675-70cf-46e9-a368-f0f1091f1ba0/scratchpad/slice23-products-backup.py packages/core/bsi_core/products.py`). Do not re-type the line.
  5. Run the same test again. Expected: 1 passed.
  6. Run `cd /Users/vineet/Downloads/ADK/bsi-platform && git diff --stat`. Expected: only `packages/core/bsi_core/products.py`, `tests/unit/test_products.py` and `tests/integration/test_products_run.py`.

- [ ] **Step 10: Run the backend gate** (Global Constraints). If `ruff check` reports the import list as unsorted (I001), run `uv run ruff check --fix tests/unit/test_products.py` and re-run the gate. Expected: ruff and mypy clean, all tests pass, metrics coverage 100%. Record the pass count and the names of any warnings.

- [ ] **Step 11: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests/unit/test_products.py tests/integration/test_products_run.py && git commit -m "feat(products): the keyword choice drops colour keywords and searches the title's type" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Docs: findings, index, rulings, plan changes

**Files:**
- Create: `docs/findings-slice23.md`. The Write tool refuses to let a subagent create a new `.md` file. Before dispatching this task, the controller asks the user, then creates a one-line stub (`# Slice 23 findings: the searched keyword when title and category disagree`) for the implementer to fill with Edit.
- Modify: `docs/README.md` (three rows after the slice 22 rows), the spec's `## Rulings`, and this plan's `## Changes made during execution`.

- [ ] **Step 1: Findings.** Fill `docs/findings-slice23.md` in the style of `docs/findings-slice22.md`, with four sections:
  - `## 1. What was built`: `_type_word` and `fit_rank` using it, `AUDIENCE_WORDS`, `title_first`, `drop_noise_terms`, `choose_keywords`, the `run_products` call, the `NOISE_WORDS` comment, the tests, the gate results as each task recorded them, and a commit table from `git log --oneline main..HEAD` with a "(this commit)" row.
  - `## 2. The probes`: the four probes exactly as the spec's "The probes" section records them (the sentence each added, its cost, the LC-05 table, the other 9 products, and "What the probes show"), including the two prompt wordings that were tried and dropped and the corrected count (10 of 12, not 11 of 12).
  - `## 3. Live check on dev`: exactly "Not yet run. The controller runs it after the user approves; results are recorded here then."
  - `## 4. Deferred and untested`: every `minor (deferred)` and `parked` ledger line not marked fixed, the two notes in this plan's "From the spec review" section, the spec's known ceilings (§1 and §2), and its Out of scope list.
- [ ] **Step 2: README rows** for the spec, the plan and the findings, in the slice 22 rows' format:
  - spec: "Design spec: the searched keyword when a product's title and category name different types — colour and size keywords are dropped before the vote, and the first keyword's audience joins the title's type (\"men flip flops\"); with the four probes of the keyword prompt and the rulings made during the build."
  - plan: "Implementation plan, Tasks 1–3, with the changes made during execution."
  - findings: "Results: what was built, the four probes, the live check on dev (not yet run), and what is deferred or untested."
- [ ] **Step 3: Rulings.** Copy each ledger ruling into the spec's `## Rulings` in the slice 22 format (Decided / Found by / Why / Cost if wrong). If there are none, replace "None yet. Rulings made during execution are added here with their R-number." with "None."
- [ ] **Step 4: Plan changes.** List every deviation from Tasks 1–3 in this plan's changes section.
- [ ] **Step 5: Coverage check.** Run a scripted grep over the ledger for every ruling ID, every line tagged `minor (deferred…)` and every `parked` line. Print which of the findings, the spec or this plan's changes section covers each. Report and fix misses.
- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add docs && git commit -m "docs: slice 23 findings, index and rulings" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The wrong-type fallback (Ruling R2)

Added after the final whole-branch review. The spec's §1, §2, §3 and Rulings (R2) are the requirements.

**Files:**
- Modify: `packages/core/bsi_core/products.py`: the `audience` list (Step 3) and the `kind` line (Step 3b) in `title_first`, `choose_keywords` (Step 4), and the `ponytail:` comments above `drop_noise_terms` and `title_first` (Step 4b).
- Test: `tests/unit/test_products.py` (new tests at the end).
- Docs: `docs/findings-slice23.md`, this plan's changes section. The spec already holds R2 and R3.

**Interfaces:**
- Consumes: `_type_word`, `title_first`, `drop_noise_terms`, `fold_set` (unchanged names and signatures).
- Produces: `choose_keywords` with the same signature and the spec's new behaviour.

- [ ] **Step 1: Write the failing tests.** Append at the end of `tests/unit/test_products.py` (`T` and `B` exist):

```python
def test_title_first_never_takes_a_colour_from_the_first_keyword():
    assert title_first(["men navy slippers", "navy flip flops"], T) == [
        "men flip flops",
        "men navy slippers",
        "navy flip flops",
    ]


def test_title_first_prefers_a_plural_spelling_of_the_type():
    assert title_first(
        ["men slippers", "men flip flop navy", "navy flip flops"], T
    ) == [
        "men flip flops",
        "men slippers",
        "men flip flop navy",
        "navy flip flops",
    ]
    # ponytail ceiling: with no plural title fit the type stays singular.
    assert title_first(["men slippers", "men flip flop navy"], T)[0] == (
        "men flip flop"
    )


def test_choose_keywords_falls_back_when_the_guard_leaves_the_wrong_type():
    # Every title-fitting keyword has a colour: the guarded vote would
    # search the category's type ("men slippers").
    assert choose_keywords(
        [["men slippers", "navy flip flops", "cushioned slippers"]] * 3,
        B,
        T,
        "Slippers",
        None,
    ) == [
        "men flip flops",
        "navy flip flops",
        "men slippers",
        "cushioned slippers",
    ]
    # A category fit alone keeps the guarded result.
    assert choose_keywords(
        [["men slippers", "navy slippers"]],
        B,
        "X Men Thong Navy",
        "Slippers",
        None,
    ) == ["men slippers"]
    # No colour in a keyword built on the unfiltered path.
    assert choose_keywords(
        [["men navy slippers", "navy flip flops", "cushioned slippers"]],
        B,
        T,
        None,
        None,
    ) == ["men flip flops", "navy flip flops"]
```

- [ ] **Step 2: Run the tests to see them fail.** Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/unit/test_products.py -k "colour_from_the_first or wrong_type or plural_spelling"`. Expected: 3 failed. The first `title_first` test gets `['men navy flip flops', 'men navy slippers', 'navy flip flops']`; the plural test gets `'men flip flop'` first; the `choose_keywords` test fails on its first assertion with `['men slippers', 'cushioned slippers']`.

- [ ] **Step 3: The audience.** In `title_first`, replace:

```python
        if len(t) > 1 and _stem(t) != word and t not in STOPWORDS
    ]
```

with:

```python
        if len(t) > 1
        and _stem(t) != word
        and t not in STOPWORDS
        and _stem(t) not in NOISE_STEMS
    ]
```

- [ ] **Step 3b: The plural spelling.** In `title_first`, replace:

```python
    kind = [t for t in tokens(fits[0]) if _stem(t) in ok]
```

with:

```python
    # The plural spelling of a type word when any title-fitting keyword
    # has it ("men flip flop navy" and "navy flip flops" -> "flip flops").
    plural = {_stem(t): t for k in fits for t in tokens(k) if t != _stem(t)}
    kind = [plural.get(_stem(t), t) for t in tokens(fits[0]) if _stem(t) in ok]
```

- [ ] **Step 4: `choose_keywords`.** Replace its docstring and body (keep the signature) with the spec's §1 code block: the new docstring, `pick` unchanged, then `in_title`, `fits`, `guarded`, `raw` and the return line.

- [ ] **Step 4b: The two `ponytail:` comments.** Above `drop_noise_terms`, replace:

```python
# ponytail: a real colour or size phrase that shoppers type ("white
# sneakers", "little kids sandals", "big kids shoes") is searched only
# when the product has no other fitting keyword (choose_keywords);
# outside footwear some are product words (gold, cream, plus size);
# English only.
```

with:

```python
# ponytail: a real colour or size phrase that shoppers type ("white
# sneakers", "little kids sandals", "big kids shoes") is searched only
# when no keyword without one names the title's type and none can be
# built (choose_keywords); outside footwear some are product words
# (gold, cream, plus size); English only.
```

Above `title_first`, replace the first two lines:

```python
# ponytail: the audience is whatever is left of the first keyword, in
# the model's spelling ("men house slippers" -> "men house flip flops",
```

with:

```python
# ponytail: the audience is whatever is left of the first keyword after
# its colour and size words, in the model's spelling ("men house
# slippers" -> "men house flip flops",
```

and, at the end of that comment, replace `# title and is not an audience word.` with:

```python
# title and is not an audience word; a type word stays singular when no
# title-fitting keyword spells it in the plural ("men flip flop navy"
# alone -> "men flip flop"); choose_keywords' wrong-type fallback uses
# fit_rank's rule, so a title audience word counts as a type there.
```

ruff format leaves comments as written; keep each line at 80 characters or fewer.

- [ ] **Step 5: Run the product tests.** Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/unit/test_products.py tests/integration/test_products_run.py`. Expected: 116 passed (91 unit, 25 integration).

- [ ] **Step 6: Run the backend gate** (Global Constraints). Expected: ruff and mypy clean, all tests pass, metrics coverage 100%. Record the pass count and the names of any warnings.

- [ ] **Step 7: Docs.** Ledger lines are quoted as recorded; where one is now fixed or untrue, append a note after it rather than editing it.
  - `docs/findings-slice23.md` §1: describe the wrong-type fallback, the audience change and the two comment changes; add Task 4's TDD evidence and gate result under "Tests"; in the commit table replace the "(this commit)" row with `5737187`, add rows for `b0c0cb0` and for the spec-review commit that adds R3, and a new "(this commit)" row; change "placed after `fit_rank`" (§1, `title_first`) to "defined after `fit_rank` in the file" (final review, Minor 3).
  - Findings §4: the rulings list holds R1, R2 and R3 (retitle its heading so it no longer says only "from the Task 3 review"); after the Task 1 minor on the audience taking a colour, append "Fixed by R2: the audience leaves out colour and size words." and correct its ending (the unfiltered path also runs when the guard leaves the wrong type); after the Task 2 minor on the fallback building a colour, append "Fixed by R2." and correct its premise: the fallback runs when the filtered samples leave no fitting keyword, and (R2) when they leave the wrong type (final review, Minor 2); after the Task 2 minor on the missing test, append "Fixed by Task 4's tests."; after the spec-review note in §4 that says colour stems are not removed from `types` (its example gives "men flip flop"), append that R2 makes that unfiltered path reachable whenever the guard leaves the wrong type (R3); list the §1 and §2 ceilings as the spec now states them.
  - This plan's changes section: one bullet for Task 4's execution (the spec change already has its own bullet).
  - Run the coverage script again: every line tagged `minor (deferred…)`, every `parked` line and every ruling in the ledger must be covered.

- [ ] **Step 8: Commit.**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests/unit/test_products.py docs && git commit -m "fix(products): search the title's type when the guard would leave the category's" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review

- **Spec coverage:**

  | Spec part | Covered by |
  |---|---|
  | §1 `drop_noise_terms` | Task 2 Step 5 |
  | §1 the wrong-type fallback in `choose_keywords` (R2) | Task 4 Step 4 |
  | §2 the audience without colour and size words (R2); the plural spelling (R3); the comments (R3) | Task 4 Steps 3, 3b and 4b |
  | §1 `choose_keywords`, the per-product fallback | Task 2 Step 6 |
  | §1 `run_products` calling `choose_keywords` | Task 2 Step 7 |
  | §1 the `NOISE_WORDS` comment's new clause | Task 2 Step 4 |
  | §1 known ceilings in a `# ponytail:` comment | Task 2 Step 5 |
  | §2 `_type_word`, `fit_rank` calling it with unchanged behaviour | Task 1 Step 3 |
  | §2 `AUDIENCE_WORDS`, `AUDIENCE_STEMS`, `title_first` | Task 1 Step 4 |
  | §2 known ceilings in a `# ponytail:` comment | Task 1 Step 4 |
  | §3 unit tests | Task 1 Step 1 (`_type_word`, `title_first`), Task 2 Step 1 (`drop_noise_terms`, `choose_keywords`) |
  | §3 the integration test | Task 2 Step 2 |
  | §3 copy check | Global Constraints; fixtures listed below |
  | §4 dev re-check | the controller, after Task 3, with the user's OK |
  | Gates | Tasks 1–2 and the controller |

- **§3 values, word for word against the spec:**
  - `drop_noise_terms`: `["men slippers"]`; `[]`; `["kids sandals"]`.
  - `_type_word`: `["slipper", "slipper", "shoe", "for", None]`.
  - `title_first`, 19 values in 16 cases (Task 4 adds 3: no colour from the first keyword; the plural spelling and its singular ceiling) (the two builds and the two "boys" cases hold 2 values each): the two builds; the offered spelling; first keyword fits; no keyword fits; no audience; empty; the cap; "boys sandals" and "sandals for boys"; shared words; the one-fit ceiling; only an audience word fits; a good fit with an audience-word fit; two title types; no colour built in.
  - `choose_keywords`, 9 values (Task 4 adds 3: the wrong-type fallback, a category fit alone, no colour on the unfiltered path): probe 4's samples; one all-colour sample; every keyword has a colour; only a brand phrase left; the audience-word keyword; no samples.
  - Integration: `keyword == "kids sandals"`, `keywords == ["kids sandals", "strap sandals"]`, one search for "kids sandals".
- **Checked by running code.** The spec reviewer checked the spec's 27 values before R2 (the R2 review checked all 30 after R2; Task 4's plural test adds 2) against its own copy of the functions (0 mismatches). The controller built scratch copies of the three files from this plan's code blocks, outside the repo, and ran them:
  - `ruff format --diff` and `ruff check` with the repo's config: no changes, all checks passed (after `ruff check --fix` sorted the import list).
  - `mypy --strict` on the patched `products.py`: no issues.
  - Task 1 Step 5's selection: 17 passed. The whole patched unit file: 88 passed.
  - The patched product-run file against the patched module: 25 passed.
  - Task 2 Step 3's integration failure, against today's module: `AssertionError: assert 'blue sandals' == 'kids sandals'`.
  - Task 2 Step 9's failure, with `return pick(samples)`: `At index 1 diff: 'blue sandals' != 'strap sandals'`.
  - Not run this way: the ImportError messages of Task 1 Step 2 and Task 2 Step 3, and the full gate.
- **Test count in Task 1 Step 5:** 10 new tests, 3 `fit_rank`, 3 `vote`, 1 `drop_brand_terms`.
- **Fixtures vs banned words:** men slippers, flip flops, cushioned, daily wear, daily use, thongs, floaters, casual sandals, boys sandals, strap sandals, blue sandals, navy, free size, little kids. None is a banned word.
- **Types:**
  - `_type_word` returns `str | None`; `_type_word(k) in types` is a membership test on `frozenset[str]` and accepts `None`.
  - `in_title`, `types` and `ok` are `frozenset[str]`; `ok &= fold_set(k)` keeps the type.
  - `title_first`, `drop_noise_terms` and `choose_keywords` return `list[str]`.
  - `pick` is annotated, so `mypy --strict` accepts the nested function.
- **Every place this plan departs from the spec's text:**
  1. The spec names no test. The plan names them: 10 tests in Task 1, 5 in Task 2, 1 integration test and 3 in Task 4.
  2. The plan groups several of the spec's test values into one test each (for example the four "cannot build" cases).
  3. The plan adds module-level test constants `T`, `W`, `CASUAL` and `S4`. The spec uses `T`, `W`, `B` and `S4` as names in its text; `B` exists since slice 22.
  4. Task order is the spec's §2 first, then §1, because `choose_keywords` (§1) calls `title_first` (§2).
  5. The spec puts `drop_noise_terms` "next to `drop_brand_terms`" and does not place the other functions. The plan places `_type_word` before `fit_rank`, and `AUDIENCE_WORDS`, `title_first` and `choose_keywords` after it.
  6. The two `# ponytail:` comments sit above `drop_noise_terms` and above `title_first`. Their wording is the plan's, shortened from the spec's ceiling lists. The spec's text is the reference.
  7. The `title_first` ponytail comment leaves out three things the spec's §2 ceilings have: the example "babies booties" with "baby shoes" (it keeps "mens slippers"), the examples "ladies", "gents" and "teens" for the closed `AUDIENCE_WORDS`, and "(10 of 12 LC-05 samples)".
  8. The `NOISE_WORDS` comment's new clause is the plan's wording. The spec gives its sense: "the keyword choice drops keywords that contain them too."
  9. Task 2 Step 9 adds a remove-and-see-it-fail check that the spec does not ask for.
  10. The new integration test is written before the code and is seen failing (Task 2 Step 3). The spec does not ask for that.
  11. Tasks 1, 2 and 4 each run the backend gate. The controller also runs both gates.
  12. Task 3's findings file has a section the earlier slices' findings do not: `## 2. The probes`. The live check becomes §3 and the deferred list §4.
  13. Task 3's findings file needs the user's OK and a controller-made stub, because of the Write tool's refusal for subagents.
  14. Task 3 records the spec re-review's two minor notes in findings §4. The spec does not contain them.
  15. The tests import the private helper `_type_word`, because the spec asks for a test of it.
  16. The new integration test also asserts `job.status == "done"` and carries a three-line comment. The spec's integration bullet lists neither.

## Changes made during execution

- Task 4 was added after the final whole-branch review, by Ruling R2 (spec §1, §2, §3 and Rulings). The review of that spec change (b0c0cb0) found R2's side effects (a colour keyword searched or stored; a singular type word on a close variant of probe 4). The controller accepted them as ceilings (Ruling R3) and fixed the texts that R2 had made untrue: the Goal and Architecture lines above, Task 4's Files and Step 7, the two `ponytail:` comments in a new Step 4b, and the self-review (c93232d). The re-review of c93232d showed that a plural-spelling rule does help on probe 4's unfiltered samples, so R3 was revised to add it: Task 4 Step 3b and a third test (53a3646). Values were checked by the controller on scratch copies outside the repo: ruff and mypy --strict clean; with R2 and the plural rule, the current unit file plus Task 4's 3 tests 91 passed and the product-run file 25 passed; Task 4's 3 tests fail on the branch (3 failed).

- Task 1 went as written (commit 23eb548), with one difference (from the ledger): the full suite was run twice. The first run's output was cut off, so it lacked both warning names; the pytest re-run (with the shared-DB `pgrep` check first) recorded them. No code changed between the two runs. task-1-report.md words it differently: the gate's `tail -15` cut off the first warning's name. ruff did not re-wrap anything, and I001 did not fire.
- Task 2 went as written (commit d072568). The ledger records "No departures; ruff changed nothing", and task-2-report.md says "no departures from the brief".
- A plan fact found in preflight (ledger, preflight scan) and handled at dispatch, not a Task 2 deviation: Task 2's line numbers in the Files list were taken before Task 1 (`run_products` "907-913 before Task 1"); the Task 2 dispatch said to find the regions by their text.
- Task 3: the controller created the `docs/findings-slice23.md` stub after the user approved it in chat ("yes, create the stub"), as Task 3 says (plan departure 13). The implementer filled it with the Edit tool. Findings §4 also has two lists Step 1 does not name, in the style of findings-slice22 §3: "Parked: none" and an "Untested" list (the tests use fixed model output).
- No rulings were made during Tasks 1–2. Ruling R1 came from the Task 3 review (below).
- Task 3 fix round 1 (commit "docs: slice 23 ruling R1 (README spec row) and plan record fixes"), after the Task 3 review (0 Critical, 1 Important (plan-mandated), 3 Minor):
  - R1: the README's slice 23 spec row ends at "…with the four probes of the keyword prompt."; the rulings clause of Task 3 Step 2's wording is dropped. The spec's `## Rulings` records R1 instead of "None.", and findings §4 lists it under "Rulings".
  - The 3 Minors fix this section: Task 1's double run in the ledger's wording; the pre-Task-1 line numbers moved out of Task 2's differences; the remark on how Step 9's one-line edit was made removed (Step 9 names no method).
  - The findings commit table: the first findings commit row is now `0ea1a26`, and a new "(this commit)" row was added.
- Task 4 (commit "fix(products): search the title's type when the guard would leave the category's"): its code steps went as written: Steps 3, 3b, 4 and 4b applied word for word; RED 3 failed with the messages Step 2 expects; Step 5 116 passed; backend gate 1539 passed, 2 deselected, 2 warnings (the same two), ruff changed nothing, mypy clean, metrics 100%. Differences: the findings commit table lists every commit in `main..HEAD` (b0c0cb0, c93232d, 53a3646, 4ed4f16), not only b0c0cb0 and the R3 commit, since its heading says it is that log; findings §4 also gains the two Task 3 deferred minors, which the ledger records after 5737187 and no doc held; R3's first reading is quoted beside the revised one.
- Task 4 fix round 1 (commit "docs: slice 23 findings quote R2 and R3 as recorded"), after the Task 4 review (approved; 2 Minor): findings §4 now quotes the ledger's "Ruling R2:", "Ruling R3:" and "Ruling R3 revised:" lines in full, with spec-derived text moved to sub-bullets labelled "Note (not ledger text)"; the Task 2 minor's correction states R2's condition exactly (the unfiltered result is tried, and used only if its first keyword names a type the title does, or if the filtered result is empty), and the Task 1 minor's note says "is also tried"; the commit table and the Task 4 gate line name 0d99220.
- Task 4 fix round 2 (commit "docs: slice 23 findings quote R1 as recorded"), from the fix round 1 re-review's out-of-scope note: findings §4 now quotes the ledger's "Task 3: Ruling R1:" line (progress.md:46) in full, and the Task 3 round's entry is kept as a sub-bullet labelled "Note (not ledger text…)"; the commit table names 9e8504f.
