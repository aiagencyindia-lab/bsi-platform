# Slice 22 Backed Missing Words Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Suggest a missing word only when the product's own data backs it and more than half of the ranking titles use it.

**Architecture:**
- `missing` gains `backing=None`. Rule 1: when given, a word's stem must be in `_allowed_stems("", backing, [])`. Rule 2, always on: a word must be in at least `max(MIN_TITLES, len(titles) // 2 + 1)` titles.
- `run_products` stores the product's keyword, description, category and attribute values as `p["backing"]`. It passes that to `missing` and reuses it in `rule_check`'s `allowed`.
- All code is in `packages/core/bsi_core/products.py`. There is no schema, API, prompt or web change.

**Tech Stack:** Python 3.13, SQLAlchemy 2, pydantic 2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-slice22-backed-missing-words-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice22-backed-missing-words`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB, the network or the worker loop.
- **Shared test DB:** tests use `bsi_test`, which is shared. Run `pgrep -fl pytest` first, and never run two suites at once.
- **Tool refusals:** if a tool refuses, stop and report BLOCKED. Do not work around it.
- **Lint and types:** ruff line length is 80, and RUF001 rejects a literal curly apostrophe. `mypy --strict` runs over `packages/core/bsi_core`.
- **Rule 1:** the backing set is `_allowed_stems("", backing, [])`. Rule 1 is off when `backing` is `None`.
- **Rule 2:** a word must be in at least `max(MIN_TITLES, len(titles) // 2 + 1)` titles, with or without `backing`. `MIN_TITLES` stays 2.
- **Unchanged:** `search_query`, `titles_prompt`, `keep_present`, `drop_stores`, `TITLES_PARSE`, the cache-hit rule, `rule_check`, `_allowed_stems`, `rewrite_prompt`, the schema, the API and the web app.
- **Banned words:** copy (comments, fixtures) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat` or `certain`.
- **Backend gate:** `uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100`
- **Commit trailer:** the `Co-Authored-By` line from the latest session reminder.

## Changes to existing tests that the spec implies

| Test | Change | Task |
|---|---|---|
| `_seed` (integration helper) | gains `description=None`, passed to every `m.Product` it creates | 2 |
| `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` | seeds with `description="Summer sandal"`; expected values unchanged | 2 |
| `RIVAL_TITLES` and `test_rival_brands_models_and_competitors_are_not_missing_words` | 3 titles; seeds with `description="Summer sandal, an alternative to Crocs and Teva Hurricane"`; expected value and comment unchanged | 2 |

The 7 existing `missing` unit tests are not edited. They pass no `backing`, use 2 or 3 titles, and keep their values under rule 2.

## File map

| File | Responsibility |
|---|---|
| `packages/core/bsi_core/products.py` | the `NOISE_WORDS` comment, `missing(backing=)` and rule 2, the `run_products` wiring |
| `tests/unit/test_products.py` | 7 new `missing` unit tests |
| `tests/integration/test_products_run.py` | `_seed(description=)`, the two reworked fixtures, 2 new run tests |
| docs | `docs/findings-slice22.md`, `docs/README.md`, the spec's `## Rulings`, this plan's changes section |

---

### Task 1: The two rules in `missing`

**Files:**
- Modify: `packages/core/bsi_core/products.py`: the comment above `NOISE_WORDS` (lines 327-332) and `missing` (lines 494-530).
- Test: `tests/unit/test_products.py` (append at the end of the file).

**Interfaces:**
- Consumes: `_allowed_stems(original: str, allowed: Sequence[str], brand_names: Sequence[str]) -> frozenset[str]` (products.py:374, unchanged).
- Produces: `missing(product_title: str, titles: Sequence[str], brand_names: Sequence[str], exclude: Sequence[str] = (), keyword: str = "", backing: Sequence[str] | None = None) -> list[str]`

- [ ] **Step 1: Write the failing tests.** Append to `tests/unit/test_products.py`:

```python
# Ranking titles stored in dev's keyword_search (slice 22 spec).
WS = [
    "Women's Double Strap Footbed Sandals",
    "Women's Footbed Slide Sandals, Wide Width Available",
    "Men's and Women's Unisex Baya II Slide Sandals",
    "Women's Faux Suede Thong Footbed Sandals",
    "Women's Asymmetric Strap Footbed Sandals, Wide Width Available",
]
KS = [
    "MIA - Lolli (Toddler/Little Kid)",
    "Josmo - Cars Lighted Sandal (Toddler/Little Kid)",
    "Naturino - Flower Mountain Nazca 2 Junior (Little Kid)",
    "Teva - Toachi Hydratrek (Toddler/Little Kid/Big Kid)",
    "Josmo - Spiderman Sandals (Toddler/Little Kid)",
]
KSH = [
    "Nike A'Two A'ja Wilson Big Kids' Basketball Shoes",
    "Nike Free Ride Little Kids' Running Shoes",
    "Nike Woodside 2 High Big Kids' Boots",
    "Nike Manoa 17 Big Kids' Boots",
    "Nike Air Max 270 Big Kids' Shoes",
]
B = ["BSOAgentTestBrand"]
WSB = [
    "women sandals",
    "Flat sandal with a cushioned footbed",
    "Sandals",
    "7",
    "tan",
]


def test_missing_needs_backing_and_more_than_half_the_titles():
    assert missing(
        "BSOAgentTestBrand Women Sandal Tan",
        WS,
        B,
        keyword="women sandals",
        backing=WSB,
    ) == ["footbed"]


def test_missing_drops_an_unbacked_size_marker():
    assert missing(
        "BSOAgentTestBrand Boys Sandal Blue",
        KS,
        B,
        keyword="kids sandals",
        backing=[
            "kids sandals",
            "Lightweight EVA sandal with a hook-and-loop strap",
            "Sandals",
            "3",
            "blue",
        ],
    ) == ["kid"]


def test_missing_drops_a_different_product_type():
    assert (
        missing(
            "BSOAgentTestBrand Kids Sports Shoe Black",
            KSH,
            B,
            keyword="kids shoes",
            backing=[
                "kids shoes",
                "Breathable mesh running shoe for school and play",
                "Shoes",
                "4",
                "black",
            ],
        )
        == []
    )


def test_missing_with_empty_backing_suggests_nothing():
    assert (
        missing(
            "BSOAgentTestBrand Women Sandal Tan",
            WS,
            B,
            keyword="women sandals",
            backing=[],
        )
        == []
    )


def test_missing_needs_more_than_half_the_titles_without_backing():
    # Before slice 22: footbed, available, slide, strap, wide, width.
    assert missing(
        "BSOAgentTestBrand Women Sandal Tan", WS, B, keyword="women sandals"
    ) == ["footbed"]


def test_missing_needs_more_than_half_the_titles_even_when_backed():
    # strap, wide and width are backed but in only 2 of the 5 titles.
    assert missing(
        "BSOAgentTestBrand Women Sandal Tan",
        WS,
        B,
        keyword="women sandals",
        backing=[*WSB, "adjustable strap, wide width"],
    ) == ["footbed"]


def test_missing_backing_folds_es_plurals():
    assert missing(
        "Titan Analog Dial",
        ["Titan Men Watch", "Fossil Men Watch"],
        ["Titan"],
        keyword="men watches",
        backing=["men watches"],
    ) == ["men", "watch"]
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/unit/test_products.py -k "needs_backing or unbacked_size or different_product_type or empty_backing or more_than_half or es_plurals"`

Expected: 7 failed. Six fail with `TypeError: missing() got an unexpected keyword argument 'backing'`. `test_missing_needs_more_than_half_the_titles_without_backing` fails because the result is `['footbed', 'available', 'slide', 'strap', 'wide', 'width']`.

- [ ] **Step 3: Replace the comment above `NOISE_WORDS`.** In `packages/core/bsi_core/products.py`, replace the last two lines of the comment:

```python
# size, hair color); toddler/youth/infant are not listed, and "kid" from
# "Little Kid" is still suggested.
```

with:

```python
# size, hair color); toddler/youth/infant are not listed: since slice 22
# missing() suggests such a word only when the product's data backs it.
```

- [ ] **Step 4: Implement the two rules.** Replace the whole `missing` function with:

```python
def missing(
    product_title: str,
    titles: Sequence[str],
    brand_names: Sequence[str],
    exclude: Sequence[str] = (),
    keyword: str = "",
    backing: Sequence[str] | None = None,
) -> list[str]:
    """Words of the ranking titles the product title lacks, compared by
    stem (fold): at least 3 characters, not a number, not a stopword or
    a colour/size word (NOISE_STEMS), not a stem of the brand's names or
    of `exclude` (rival brands, models, competitor names) unless it is a
    stem of the product's keyword. When `backing` is given (the product's
    keyword, description, category and attribute values), only a stem of
    it, as _allowed_stems folds it (rule 1). In more than half of the
    titles and at least MIN_TITLES (rule 2). The first surface form seen
    is reported; by title count, then stem; MAX_MISSING."""
    have = (
        fold_set(product_title)
        | _brand_stems(brand_names)
        | (_brand_stems(exclude) - _brand_stems([keyword]))
    )
    # ponytail: stems match exactly apart from the -es singular
    # ("cushioned" does not back "cushion"); a product with no
    # description, category or attributes gets only words of its keyword;
    # a colour or size word in the attributes is still skipped
    # (NOISE_STEMS); a backed word in only 2 of 5 titles is not suggested.
    backed = None if backing is None else _allowed_stems("", backing, [])
    need = max(MIN_TITLES, len(titles) // 2 + 1)
    counts: Counter[str] = Counter()
    surface: dict[str, str] = {}
    for title in titles:
        here: set[str] = set()
        for tok in tokens(title):
            if len(tok) < 3 or tok.isdigit() or tok in STOPWORDS:
                continue
            stem = _stem(tok)
            if stem in have or stem in NOISE_STEMS:
                continue
            if backed is not None and stem not in backed:
                continue
            here.add(stem)
            surface.setdefault(stem, tok)
        counts.update(here)
    ranked = sorted(
        (s for s, n in counts.items() if n >= need),
        key=lambda s: (-counts[s], s),
    )
    return [surface[s] for s in ranked[:MAX_MISSING]]
```

- [ ] **Step 5: Run the `missing` tests to see them pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/unit/test_products.py -k missing`

Expected: 14 passed (the 7 existing `missing` tests and the 7 new ones).

- [ ] **Step 6: Run the backend gate** (Global Constraints). Expected: ruff and mypy clean, all tests pass, metrics coverage 100%. Record the pass count and the names of any warnings.

- [ ] **Step 7: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests/unit/test_products.py && git commit -m "fix(products): a missing word needs product backing and more than half the titles" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `run_products` passes the backing, and the run tests

**Files:**
- Modify: `packages/core/bsi_core/products.py`: the missing-words loop (lines 1028-1049) and the `rule_check(...)` call (lines 1064-1075) in `run_products`.
- Test: `tests/integration/test_products_run.py`: `_seed` (line 132), `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` (defined at line 179; its `_seed` call is at line 184), `RIVAL_TITLES` and the rival test (lines 465-505), and 2 new tests after the rival test.

**Interfaces:**
- Consumes: `missing(..., keyword: str = "", backing: Sequence[str] | None = None) -> list[str]` from Task 1.
- Produces: `_seed(owner, org, bid, n, description=None)` (test helper).

- [ ] **Step 1: `_seed` gains a description.** Replace `_seed` with:

```python
def _seed(owner, org, bid, n, description=None):
    with owner() as s, s.begin():
        for i in range(n):
            s.add(
                m.Product(
                    org_id=org.id,
                    brand_id=bid,
                    external_id=f"W-{i}",
                    title=f"Walkaroo Boys Sandal {i}",
                    description=description,
                    source="csv",
                )
            )
```

- [ ] **Step 2: The two existing fixtures.**
  - In `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked`, change `_seed(owner, org, bid, 3)` to `_seed(owner, org, bid, 3, description="Summer sandal")`. Change nothing else in that test.
  - Replace `RIVAL_TITLES` with:

```python
RIVAL_TITLES = [
    ("Teva Hurricane Summer Sandals", "Teva", "Hurricane"),
    ("Crocs Teva Hurricane Summer Slides", "Teva", "Hurricane"),
    ("Crocs Summer Sandals", "", ""),
]
```

  - In `test_rival_brands_models_and_competitors_are_not_missing_words`, change `_seed(owner, org, bid, 1)` to:

```python
    _seed(
        owner,
        org,
        bid,
        1,
        description="Summer sandal, an alternative to Crocs and Teva Hurricane",
    )
```

  Leave its comment ("Without the exclusions: ["summer", "crocs", "hurricane", "teva"].") and its assertion (`["summer"]`) as they are.

- [ ] **Step 3: Write the 2 new failing tests.** Insert right after `test_rival_brands_models_and_competitors_are_not_missing_words`:

```python
BACKED_TITLES = [
    "Kids Summer Sandals Lightweight",
    "Boys Summer Sandals Lightweight",
]


def _backed_run(owner, make_org, make_brand, rewrite):
    """One product described as a summer sandal; both ranking titles also
    say "Lightweight", which its data does not back."""
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1, description="Summer sandal for daily wear")
    answer = "Picks: " + "; ".join(BACKED_TITLES) + "."
    engine = FakeEngine(
        [
            EngineResult(
                "ok", raw={"text": answer}, model="fake-1", cost_micros=35_000
            )
        ]
    )
    gen = _generator(
        titles=[
            {"title": t, "domain": "", "brand": "", "model": ""}
            for t in BACKED_TITLES
        ],
        rewrite=rewrite,
    )
    _, rows, _searches = _run(owner, org, bid, gen, engine)
    return rows[0]


def test_only_backed_words_are_missing_and_kept(owner, make_org, make_brand):
    p = _backed_run(
        owner, make_org, make_brand, "Walkaroo Boys Summer Sandal 0"
    )
    assert p.missing_keywords == ["summer"]
    assert (p.suggested_title, p.rule_check) == (
        "Walkaroo Boys Summer Sandal 0",
        "pass",
    )


def test_the_rewrite_cannot_add_an_unbacked_ranking_word(
    owner, make_org, make_brand
):
    p = _backed_run(
        owner, make_org, make_brand, "Walkaroo Boys Lightweight Summer Sandal 0"
    )
    assert p.missing_keywords == ["summer"]
    assert (p.suggested_title, p.rule_check) == (
        "Walkaroo Boys Summer Sandal 0",
        "adjusted",
    )
```

- [ ] **Step 4: Run the product-run tests to see the new ones fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/integration/test_products_run.py`

Expected: 2 failed, the rest passed. Both new tests fail on their first assertion, `['lightweight', 'summer'] == ['summer']`: without the backing, "lightweight" is a missing word. (Their tuple assertions are not reached. Had they been, the second test would show `('Walkaroo Boys Lightweight Summer Sandal 0', 'pass')`, because "Lightweight" is then allowed.)

The two reworked tests pass already: without the backing, "summer" is still the only word that clears the exclusions and rule 2.

- [ ] **Step 5: Implement the wiring.** In `run_products`, in the loop `for i, p in enumerate(kept):` that computes the missing words, add the `p["backing"]` list after `ranking = …` and pass it to `missing`:

```python
            for i, p in enumerate(kept):
                p["index"] = i
                ranking = titles_by_kw.get(p["keyword"], [])
                p["backing"] = [
                    p["keyword"],
                    p["description"] or "",
                    p["category"] or "",
                    *(str(v) for v in (p["attributes"] or {}).values()),
                ]
                p["missing"] = missing(
                    p["title"],
                    [t["title"] for t in ranking],
                    names,
                    # ponytail: a generic word in a model ("Classic") is
                    # excluded for this keyword, and one in a competitor's
                    # name or alias for every keyword that does not contain
                    # it (spec §1).
                    exclude=[
                        *rivals,
                        *(
                            v
                            for t in ranking
                            for v in (t.get("brand"), t.get("model"))
                            if v
                        ),
                    ],
                    keyword=p["keyword"],
                    backing=p["backing"],
                )
```

Then, in the `rule_check(...)` call, replace the `allowed=[…]` argument with:

```python
                        allowed=[*p["backing"], *p["missing"]],
```

- [ ] **Step 6: Run the product-run tests to see them pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/integration/test_products_run.py`

Expected: all passed.

- [ ] **Step 7: Re-prove slice 20's R5 check.**
  1. Copy `packages/core/bsi_core/products.py` to the session scratchpad, a path outside the repo: `cd /Users/vineet/Downloads/ADK/bsi-platform && cp packages/core/bsi_core/products.py /private/tmp/claude-501/-Users-vineet-Downloads-ADK-brand-search-optimization/57875675-70cf-46e9-a368-f0f1091f1ba0/scratchpad/slice22-products-backup.py`.
  2. Change `for n in (c.name, *c.aliases)` to `for n in (c.name,)` in `run_products`.
  3. Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_products_run.py -k rival_brands`. Expected: 1 failed, with "crocs" in the missing words (`['summer', 'crocs']`).
  4. Restore `products.py` from that copy (`cd /Users/vineet/Downloads/ADK/bsi-platform && cp /private/tmp/claude-501/-Users-vineet-Downloads-ADK-brand-search-optimization/57875675-70cf-46e9-a368-f0f1091f1ba0/scratchpad/slice22-products-backup.py packages/core/bsi_core/products.py`). Do not re-type the line.
  5. Run the same test again. Expected: 1 passed.
  6. Run `cd /Users/vineet/Downloads/ADK/bsi-platform && git diff --stat`. Expected: only `packages/core/bsi_core/products.py` and `tests/integration/test_products_run.py`.

- [ ] **Step 8: Run the backend gate** (Global Constraints). Expected: ruff and mypy clean, all tests pass, metrics coverage 100%. Record the pass count and the names of any warnings.

- [ ] **Step 9: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests/integration/test_products_run.py && git commit -m "fix(products): the run passes the product's data as backing for missing words" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Docs: findings, index, rulings, plan changes

**Files:**
- Create: `docs/findings-slice22.md`. The Write tool refuses to let a subagent create a new `.md` file. Before dispatching this task, the controller asks the user, then creates a one-line stub (`# Slice 22 findings: missing words backed by product data`) for the implementer to fill with Edit.
- Modify: `docs/README.md` (three rows after the slice 21 rows), the spec (a new `## Rulings` section before `## Out of scope`), and this plan's `## Changes made during execution`.

- [ ] **Step 1: Findings.** Fill `docs/findings-slice22.md` in the style of `docs/findings-slice21.md`, with three sections:
  - `## 1. What was built`: the two rules, the `run_products` wiring, the `NOISE_WORDS` comment, the gate results as each task recorded them, and a commit table from `git log --oneline main..HEAD` with a "(this commit)" row.
  - `## 2. Live check on dev`: exactly "Not yet run. The controller runs it after the user approves; results are recorded here then."
  - `## 3. Deferred and untested`: every `minor (deferred)` and `parked` ledger line not marked fixed, the spec's known ceilings, and its Out of scope list.
- [ ] **Step 2: README rows** for the spec, the plan and the findings, in the slice 21 rows' format:
  - spec: "Design spec: missing words backed by product data after slice 21's live check — a missing word must be backed by the product's keyword, description, category or attribute values and appear in more than half of the ranking titles; with the rulings made during the build."
  - plan: "Implementation plan, Tasks 1–3, with the changes made during execution."
  - findings: "Results: what was built, the live check on dev (not yet run), and what is deferred or untested."
- [ ] **Step 3: Rulings.** Add a `## Rulings` section to the spec, before `## Out of scope`. Copy each ledger ruling into it in the slice 21 format (Decided / Found by / Why / Cost if wrong). If there are none, the section reads "None."
- [ ] **Step 4: Plan changes.** List every deviation from Tasks 1–3 in this plan's changes section.
- [ ] **Step 5: Coverage check.** Run a scripted grep over the ledger for every ruling ID, every `minor (deferred)` line and every `parked` line. Print which of the findings, the spec or this plan's changes section covers each. Report and fix misses.
- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add docs && git commit -m "docs: slice 22 findings, index and rulings" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review

- **Spec coverage:**

  | Spec part | Covered by |
  |---|---|
  | §1 Rule 1: `backing=None`, `_allowed_stems("", backing, [])`, the check beside `have`/`NOISE_STEMS`, off when `None` | Task 1 Step 4 |
  | §1 Rule 2: `max(MIN_TITLES, len(titles) // 2 + 1)`, replacing `n >= MIN_TITLES`, always on | Task 1 Step 4 |
  | §1 `run_products`: `p["backing"]` in the first loop, reused as `allowed=[*p["backing"], *p["missing"]]` | Task 2 Step 5 |
  | §1 comments: `missing` docstring names both rules; `NOISE_WORDS` comment's last clause; the `# ponytail:` ceilings (four) | Task 1 Steps 3–4 |
  | §1 Unchanged list | Global Constraints |
  | §2 unit tests (7 new; 7 existing untouched) | Task 1 Steps 1–2, 5 |
  | §2 integration: `_seed(description=None)`, test 1's description, the rival rework, the R5 re-proof, 2 new tests, the `fit_rank`/`rewrite_prompt` note | Task 2 Steps 1–7 (the `fit_rank`/`rewrite_prompt` note only through Step 6 and the gate; departure 14) |
  | §2 copy check | Global Constraints; fixtures listed below |
  | §3 dev re-check | the controller, after Task 3, with the user's OK |
  | Gates | Tasks 1–2 and the controller |

- **§2 values, word for word against the spec:**
  - Both rules, `WS` + `WSB` → `["footbed"]`.
  - `KS`, backing "kids sandals", "Lightweight EVA sandal with a hook-and-loop strap", "Sandals", "3", "blue" → `["kid"]`.
  - `KSH`, backing "kids shoes", "Breathable mesh running shoe for school and play", "Shoes", "4", "black" → `[]`.
  - `backing=[]` → `[]`.
  - Rule 2 alone → `["footbed"]` (was `["footbed", "available", "slide", "strap", "wide", "width"]`).
  - `[*WSB, "adjustable strap, wide width"]` → `["footbed"]`.
  - Titan / "men watches" → `["men", "watch"]`.
  - Test 1: `description="Summer sandal"`; `["summer"]`, "Walkaroo Kids Summer Sandals", `review`, `["boys"]` unchanged.
  - Rival: description "Summer sandal, an alternative to Crocs and Teva Hurricane"; the three titles as in the spec; `["summer"]`; comment unchanged.
  - R5: `for n in (c.name, *c.aliases)` → `for n in (c.name,)` fails with "crocs"; restored from a backup.
  - New tests: description "Summer sandal for daily wear"; titles "Kids Summer Sandals Lightweight" and "Boys Summer Sandals Lightweight"; keyword "kids sandals" (the fake generator's default); rewrite "Walkaroo Boys Summer Sandal 0" → `["summer"]`, same title, `pass`; rewrite "Walkaroo Boys Lightweight Summer Sandal 0" → `["summer"]`, "Walkaroo Boys Summer Sandal 0", `adjusted`.
- **Checked by running code.** Every value above was checked against a scratchpad copy of the two rules (outside the repo) by the controller and by the spec reviewer. The expected failure messages in Task 1 Step 2 and Task 2 Step 4 come from the current code: `missing` without rule 2 on `WS`, and `['lightweight', 'summer']` for the backed titles without rule 1 (counts 2 each, sorted by stem).
- **Other integration tests.** Every other `missing_keywords` assertion is `[]` or `None`. Both rules only make `missing` stricter, so those cannot change. `test_the_rewrite_cannot_add_an_invented_word` keeps its title "Walkaroo Boys Sandal Kids" and `adjusted`: its missing list becomes `[]` (the seed has no description), but its rewrite "Walkaroo Boys Toddler Sandal Kids" has no "Summer", and "Toddler" is dropped as before. `test_a_failed_search_is_stored_and_the_run_goes_on` keeps "Walkaroo Kids Sandals": it has no titles, so its missing list was `[]` already (plan reviewer).
- **Fixtures vs banned words:** Summer sandal, alternative, Crocs, Teva Hurricane, daily wear, Lightweight, the dev titles, Titan, Fossil, adjustable strap, wide width. None is a banned word.
- **Types:**
  - `backing: Sequence[str] | None = None`.
  - `_allowed_stems("", backing, [])` takes `Sequence[str]` twice and returns `frozenset[str]`.
  - `backed` is `frozenset[str] | None`, and `need` is an `int`.
  - `p` is `dict[str, Any]`, so `p["backing"]` needs no annotation.
- **Every place this plan departs from the spec's text:**
  1. The spec names no new unit or integration test. The plan names them: 7 `test_missing_*` unit tests, `test_only_backed_words_are_missing_and_kept` and `test_the_rewrite_cannot_add_an_unbacked_ranking_word`.
  2. The plan adds a test helper `_backed_run` and a fixture `BACKED_TITLES`, which the spec does not name.
  3. The spec uses `WS`, `KS`, `KSH`, `B` and `WSB` as names in its text. The plan makes them module-level constants in `tests/unit/test_products.py`.
  4. Two reworked integration tests are never seen failing (Task 2 Step 4): their fixtures change, but their expected values pass both before and after the wiring. The R5 re-proof (Task 2 Step 7) shows the rival test still fails when the alias exclusion is removed.
  5. Tasks 1 and 2 each run the backend gate. The controller also runs both gates.
  6. The spec has no `## Rulings` section. Task 3 adds one.
  7. Task 3's findings file needs the user's OK and a controller-made stub, because of the Write tool's refusal for subagents.
  8. The `# ponytail:` comment sits above `backed = …` inside `missing`. The spec says only "in a `# ponytail:` comment".
  9. The `missing` docstring's wording is the plan's. The spec says only that it "names both rules".
  10. The `NOISE_WORDS` comment's new last clause is the plan's wording. The spec gives its sense: "such a word is now suggested only when the product data backs it."
  11. Comments and a docstring the spec does not give: the unit-test header comment ("# Ranking titles stored in dev's keyword_search (slice 22 spec)."), the two unit-test comments ("Before slice 22: …" and "strap, wide and width are backed but in only 2 of the 5 titles."), and `_backed_run`'s docstring.
  12. The spec has no docs section. Task 3's README rows and the content of `findings-slice22.md` are the plan's, in the slice 21 format.
  13. Task 2 Step 7 expects the R5 break to give exactly `['summer', 'crocs']`. The spec says only that the test "fails with "crocs" in the missing words".
  14. The spec's note that a description also goes to `fit_rank` and `rewrite_prompt` (with no other expected value changing) has no step of its own. Only the full product-run test run in Task 2 Step 6 and the gate check it.

## Changes made during execution

- Task 1 went as written (commit 4a53c61). Its report lists no departures from the brief.
- Task 2 went as written (commit 5be232a), with these differences (from task-2-report.md):
  - The line numbers had shifted after Task 1: the missing-words loop was at 1040 and the `rule_check` call at 1076, not 1028-1049 and 1064-1075 as the File list says. The implementer found both regions by their text.
  - The multi-line edits were made with a short Python replace script with exact-match asserts (each old block had to occur exactly once).
- Task 3: the controller created the `docs/findings-slice22.md` stub after the user approved it in chat ("yes, create the stub"), as Task 3 says (plan departure 7). The implementer filled it with the Edit tool. Findings §3 also has an "Untested" list (plan departures 4 and 14, fixed judge output), which Step 1 does not name, in the style of findings-slice21 §3.
- No rulings were made during Tasks 1–3. Rulings R1 and R2 came later, from the re-review of the final-review fix wave (below).
- Final whole-branch review: ready to merge, 0 Critical, 0 Important, 4 Minor (all deferred in the ledger). A docs-only fix wave after it:
  - `findings-slice22.md` §3 gains a "From the final whole-branch review:" list with the 4 minors, and the 2 Task 3 review minors under "From the task reviews:".
  - The findings commit table gains the rows dbb5d82 and 01dbca7.
  - The README's slice 22 spec row now says "no rulings were made during the build".
  - No code change: the duplicate-titles minor and the LC-09 note stay deferred.
- Last coverage items, a docs commit approved by the user after the scoped re-review of the fix wave above (commit 68dbe67), which parked 2 items with Rulings R1 and R2 and found 1 new minor:
  - R1: the "(line numbers as at dbb5d82)" qualifier is removed from the 2 Task 3 minors in findings §3.
  - findings §3 gains a "Parked (with rulings):" list (R1, R2) and the plan:545 minor in the final-review list.
  - The spec's `## Rulings` now holds R1 and R2 instead of "None.", so the README's slice 22 spec row says "with the rulings made during the build" again, and the bullet above on rulings holds for Tasks 1–3 only.
  - The plan:545 minor, corrected here: in the findings commit table, `dbb5d82` was relabelled from "(this commit)", `01dbca7` was added, and a new "(this commit)" row was added.
  - The "Fixed in this commit." notes that 68dbe67 added to 2 final-review minors in findings §3 now say "Fixed in 68dbe67.", so they stay accurate after this commit.
- Live check and last touch-ups, a docs commit after the controller ran the dev re-check with the user's OK (job `d75feb1d`, at 6177f1e):
  - findings §2 records the live check in place of "Not yet run", and the README's slice 22 findings row says "(run on 2026-09-29)".
  - The 2 re-review minors of 6177f1e, applied and listed in findings §3: the two "Fixed in this commit: …" notes that 6177f1e added now read "Fixed in 6177f1e: …", and the parked bullets, which keep the ledger's line references, now say "(line numbers as at 68dbe67)".
  - The findings commit table relabels 6177f1e and adds a new "(this commit)" row.
