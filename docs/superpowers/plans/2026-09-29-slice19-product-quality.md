# Slice 19 Product-Title Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the four quality problems slice 18's live check found: plural echo, ill-fitting keywords that pull the title, unprompted dropped words, and keywords too specific to share a search.

**Architecture:** One shared word-folding function (`fold`, built on `rivals._stem`) is used by `missing`, `rule_check`'s repeat check, a new `dropped` check, keyword normalisation and a new fit check. `rule_check` gains a third status, `review`, with the dropped words stored in a new `product.dropped_words` column (migration 0020). The keyword and rewrite prompts are tightened.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, pydantic 2, FastAPI; Next.js 15, vitest.

**Spec:** `docs/superpowers/specs/2026-09-29-slice19-product-quality-design.md`

## Global Constraints

- Repo root is `/Users/vineet/Downloads/ADK/bsi-platform`; the shell's cwd resets after every command, so every command starts with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- Do NOT edit `tests/conftest.py` or create databases; never touch the dev DB, the network or the worker loop. Tests use the shared `bsi_test` DB; check `pgrep -fl pytest` first and never run two suites at once.
- ruff line length 80; `mypy --strict` over `packages/core/bsi_core`.
- `fold(text)` = `tokens(text)` without 1-letter tokens, each through `rivals._stem` (imported, not copied).
- `rule_check(original, suggestion, brand_names) -> (title, status, dropped_words)`; status `review` if `dropped_words`, else `adjusted` if the title changed, else `pass`.
- Trailing connectors removed after the repeat check: `and`, `with`, `for`, `&`, `-`, `|`.
- Migration `0020`: `ck_product_rule_check` = `rule_check IS NULL OR rule_check IN ('pass','adjusted','review')`; nullable `product.dropped_words text[]`; downgrade maps `review` → `adjusted`.
- `EXPORT_COLUMNS` gains a last column `dropped_words`.
- Copy (notes, badges, prompts) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat`, `certain`. Fixtures avoid them too.
- After an API change: `npm run gen` in `apps/web`; commit `openapi.json` and `schema.d.ts`.
- Commit trailer: the `Co-Authored-By` line from the latest session reminder.

## Changes to existing tests that the spec implies

The spec lists the new expected values. These existing tests change as a consequence and are updated in the task named:

| Test | Change | Task |
|---|---|---|
| `test_export_rows_joins_lists_and_blanks_none`, `test_export_rows_neutralises_formula_cells` (unit) | fake products gain `dropped_words`; `EXPORT_COLUMNS` and rows gain a last column | 1 |
| `test_list_and_export` (API) | header and rows gain `dropped_words` | 1 |
| `test_missing_keywords_need_two_titles_and_skip_present_tokens` | expected `["summer", "kids"]` (spec §4) | 2 |
| every `rule_check` unit test | 3-tuple; trim and Red Tape cases become `review` (spec §4) | 2 |
| `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` (integration) | `missing_keywords == ["summer"]`; `rule_check == "review"`; `dropped_words == ["boys"]` ("Walkaroo Boys Sandal 0" rewritten as "Walkaroo Kids Summer Sandals" loses "boys") | 2 |

## File map

| File | Responsibility |
|---|---|
| `migrations/versions/0020_product_review.py` | the CHECK and the column |
| `packages/core/bsi_core/models.py` | `RULE_CHECKS`, `Product.dropped_words` |
| `packages/core/bsi_core/products.py` | `fold`, `fold_set`, `missing`, `dropped`, `rule_check`, `keyword_key`, `vote`, `fit_rank`, prompts, `run_products`, `EXPORT_COLUMNS` |
| `apps/api/bsi_api/schemas.py` | `ProductOut.dropped_words` |
| `apps/web/src/lib/format.ts`, `products/page.tsx` | `droppedNote`, the Check cell |
| tests | `tests/unit/test_products.py`, `tests/unit/test_recommend_copy.py`, `tests/integration/test_products_run.py`, `tests/integration/test_api_products.py`, `apps/web/src/lib/format.test.ts` |
| docs | `docs/findings-slice19.md`, `docs/README.md`, spec Rulings, this plan's changes section |

---

### Task 1: Migration 0020, the model, the API field and the export column

**Files:**
- Create: `migrations/versions/0020_product_review.py`
- Modify: `packages/core/bsi_core/models.py` (`RULE_CHECKS`, `Product`)
- Modify: `apps/api/bsi_api/schemas.py` (`ProductOut`)
- Modify: `packages/core/bsi_core/products.py` (`EXPORT_COLUMNS`)
- Test: `tests/integration/test_products_run.py`, `tests/unit/test_products.py`, `tests/integration/test_api_products.py`

**Interfaces:**
- Produces: `m.RULE_CHECKS == ("pass", "adjusted", "review")`; `m.Product.dropped_words: list[str] | None`; `ProductOut.dropped_words`; `EXPORT_COLUMNS[-1] == "dropped_words"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/integration/test_products_run.py` (add `import pytest` and `from sqlalchemy.exc import IntegrityError` to the imports):

```python
def test_the_database_accepts_review_and_rejects_an_unknown_status(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    with owner() as s, s.begin():
        s.execute(
            update(m.Product).values(
                rule_check="review", dropped_words=["casual"]
            )
        )
    with owner() as s:
        p = s.scalars(select(m.Product)).one()
        assert (p.rule_check, p.dropped_words) == ("review", ["casual"])
    with pytest.raises(IntegrityError):
        with owner() as s, s.begin():
            s.execute(update(m.Product).values(rule_check="maybe"))
```

In `tests/unit/test_products.py`:
- in `test_export_rows_joins_lists_and_blanks_none`, add `dropped_words=["casual"]` to `p` and `dropped_words=None` to `q`; append `"dropped_words"` to the expected `EXPORT_COLUMNS` list; append `"casual"` to the first expected row and `""` to the second;
- in `test_export_rows_neutralises_formula_cells`, add `dropped_words=None` to `p`.

In `tests/integration/test_api_products.py` `test_list_and_export`:
- set `p.rule_check = "review"` and add `p.dropped_words = ["casual"]`;
- after the list call add `assert r.json()[0]["dropped_words"] == ["casual"]` and `assert r.json()[1]["dropped_words"] is None`;
- expected header: `"external_id,url,title,keyword,missing_keywords," "suggested_title,suggested_bullets,rule_check,dropped_words"`;
- expected line 1 ends `"Light|Washable,review,casual"`; line 2 becomes `"W-2,,Walkaroo Kids Shoe,,,,,,"`.

- [ ] **Step 2: Run to see them fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/unit/test_products.py tests/integration/test_products_run.py tests/integration/test_api_products.py 2>&1 | tail -5`
Expected: FAIL (no `dropped_words` attribute / column; CHECK rejects `review`).

- [ ] **Step 3: Model and migration**

`models.py`: `RULE_CHECKS = ("pass", "adjusted", "review")`, and in `Product` after `rule_check`:

```python
    # Original-title words the suggestion lost (plurals folded); set
    # whenever rule_check is "review" (slice 19).
    dropped_words: Mapped[list[str] | None]
```

`migrations/versions/0020_product_review.py` (copy 0018's drop/create CHECK pattern):

```python
"""product.rule_check gains 'review'; product.dropped_words (slice 19)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

OLD = ("pass", "adjusted")
NEW = ("pass", "adjusted", "review")


def _check(values: tuple[str, ...]) -> str:
    return (
        "rule_check IS NULL OR rule_check IN ("
        + ", ".join(f"'{v}'" for v in values)
        + ")"
    )


def upgrade() -> None:
    op.drop_constraint("ck_product_rule_check", "product", type_="check")
    op.create_check_constraint("ck_product_rule_check", "product", _check(NEW))
    op.add_column(
        "product", sa.Column("dropped_words", postgresql.ARRAY(sa.Text()))
    )


def downgrade() -> None:
    op.execute(
        "UPDATE product SET rule_check = 'adjusted' WHERE rule_check = 'review'"
    )
    op.drop_column("product", "dropped_words")
    op.drop_constraint("ck_product_rule_check", "product", type_="check")
    op.create_check_constraint("ck_product_rule_check", "product", _check(OLD))
```

If `op.create_check_constraint` produces a different constraint name than `ck_product_rule_check` (a naming convention on the metadata), follow exactly what `0018_*.py` does for `ck_recommendation_type`.

- [ ] **Step 4: API field and export column**

`schemas.py` `ProductOut`, after `rule_check: str | None`: `dropped_words: list[str] | None`.

`products.py` `EXPORT_COLUMNS`: append `"dropped_words"` as the last entry.

- [ ] **Step 5: Run the tests, regenerate types, gate, commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_products.py tests/integration/test_products_run.py tests/integration/test_api_products.py tests/integration/test_rls.py 2>&1 | tail -3`
Expected: PASS.

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gen`
Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy && uv run pytest -q 2>&1 | tail -2`

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add migrations/versions/0020_product_review.py packages/core/bsi_core/models.py packages/core/bsi_core/products.py apps/api/bsi_api/schemas.py tests apps/web/openapi.json apps/web/src/lib/schema.d.ts && git commit -m "feat(products): review status and dropped_words (migration 0020)"
```

---

### Task 2: Word folding, `missing`, `dropped`, `rule_check`, and the run writes `dropped_words`

**Files:**
- Modify: `packages/core/bsi_core/products.py`
- Test: `tests/unit/test_products.py`, `tests/unit/test_recommend_copy.py`, `tests/integration/test_products_run.py`

**Interfaces:**
- Consumes: `m.Product.dropped_words` (Task 1); `rivals._stem`.
- Produces: `fold(text: str) -> list[str]`; `fold_set(text: str) -> frozenset[str]`; `CONNECTORS: frozenset[str]`; `dropped(original: str, suggestion: str, brand_names: Sequence[str]) -> list[str]`; `rule_check(original, suggestion, brand_names) -> tuple[str, str, list[str]]`; `missing` unchanged in signature.

- [ ] **Step 1: Write the failing unit tests**

In `tests/unit/test_products.py` add `dropped` and `fold` to the `from bsi_core.products import (...)` list, then:

```python
def test_fold_drops_one_letter_tokens_and_trailing_s():
    assert fold("Men's Sandals") == ["men", "sandal"]
    assert fold("Flip-Flops") == ["flip", "flop"]


def test_rule_check_folds_plurals_and_strips_a_trailing_connector():
    assert rule_check(
        "Walkaroo Boys Sandal Blue",
        "Walkaroo Blue Boys Sandal And Sandals",
        BRAND,
    ) == ("Walkaroo Blue Boys Sandal", "adjusted", [])


def test_rule_check_flags_dropped_words_for_review():
    assert rule_check(
        "Men Casual Sandal Brown", "Brown Mens Sandal Shoes", BRAND
    ) == ("Brown Mens Sandal Shoes", "review", ["casual"])
    assert rule_check("Men Flip Flop Navy", "Navy Men Slipper", BRAND) == (
        "Navy Men Slipper",
        "review",
        ["flip", "flop"],
    )


def test_dropped_ignores_stopwords_brand_numbers_and_short_tokens():
    assert dropped("Walkaroo Boys Sandal 3 for x", "Walkaroo Sandal", BRAND) == [
        "boys"
    ]
```

Change these existing tests:
- `test_missing_keywords_need_two_titles_and_skip_present_tokens`: expected `["summer", "kids"]`.
- `test_rule_check_removes_repeated_tokens`: expected `("Walkaroo Kids Shoes", "adjusted", [])`.
- `test_rule_check_restores_the_brand_the_original_had`: `("Walkaroo Boys Summer Sandal", "adjusted", [])` and `("Boys Summer Sandal", "pass", [])`.
- `test_rule_check_trims_to_150_at_a_word_boundary`: `fixed, status, lost = rule_check(...)`; `assert status == "review" and lost == ["plain"]`; the title assertions stay.
- `test_rule_check_passes_an_unchanged_suggestion`: `("Walkaroo Boys Summer Sandal", "pass", [])`.
- `test_rule_check_drops_a_word_that_repeats_an_earlier_token`: `("Walkaroo Kids-Sandal", "adjusted", [])` and `("Red Tape Shoes", "review", ["boots"])`.
- `test_rule_check_keeps_punctuation_only_words`: `("Walkaroo - Sandal | Kids", "pass", [])`.

- [ ] **Step 2: Integration test changes**

In `tests/integration/test_products_run.py`:
- `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked`: replace the comment and assertion on `missing_keywords` with

```python
    # Stems fold plurals: "sandals" matches the product's "sandal", so only
    # "summer" is in both ranking titles and absent from the product.
    assert p.missing_keywords == ["summer"]
```

  and replace `assert p.rule_check == "adjusted"` with

```python
    # "Walkaroo Boys Sandal 0" rewritten as "…Kids Summer Sandals" loses
    # "boys", so the suggestion is flagged for review.
    assert (p.rule_check, p.dropped_words) == ("review", ["boys"])
```

- `test_a_product_whose_keyword_drops_loses_its_old_suggestion`: seed also `dropped_words=["x"]`, and add `assert p.dropped_words is None`.

- [ ] **Step 3: Run to see them fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/unit/test_products.py tests/integration/test_products_run.py 2>&1 | tail -5`
Expected: FAIL (`fold`/`dropped` not importable; 2-tuples).

- [ ] **Step 4: Implement**

In `products.py` add `from .rivals import _stem` to the imports, and after `brand_tokens`:

```python
def fold(text: str) -> list[str]:
    """The text's tokens without 1-letter ones (the s of "men's"), each
    with one trailing s dropped (rivals._stem): sandals and sandal, mens
    and men meet. ponytail: crude on purpose; irregular plurals (feet)
    do not fold. The one place to swap in a real lemmatiser."""
    return [_stem(t) for t in tokens(text) if len(t) > 1]


def fold_set(text: str) -> frozenset[str]:
    return frozenset(fold(text))


def _brand_stems(brand_names: Sequence[str]) -> frozenset[str]:
    return frozenset(_stem(t) for t in brand_tokens(brand_names))


# Removed from the end of a fixed title: "Sandal And" -> "Sandal".
CONNECTORS = frozenset({"and", "with", "for", "&", "-", "|"})
```

Replace `missing`:

```python
def missing(
    product_title: str, titles: Sequence[str], brand_names: Sequence[str]
) -> list[str]:
    """Words of the ranking titles the product title lacks, compared by
    stem (fold): at least 3 characters, not a number, not a stopword or a
    brand stem, in at least MIN_TITLES titles. The first surface form
    seen is reported; by title count, then stem; MAX_MISSING."""
    have = fold_set(product_title) | _brand_stems(brand_names)
    counts: Counter[str] = Counter()
    surface: dict[str, str] = {}
    for title in titles:
        here: set[str] = set()
        for tok in tokens(title):
            if len(tok) < 3 or tok.isdigit() or tok in STOPWORDS:
                continue
            stem = _stem(tok)
            if stem in have:
                continue
            here.add(stem)
            surface.setdefault(stem, tok)
        counts.update(here)
    ranked = sorted(
        (s for s, n in counts.items() if n >= MIN_TITLES),
        key=lambda s: (-counts[s], s),
    )
    return [surface[s] for s in ranked[:MAX_MISSING]]
```

Add `dropped` before `rule_check`:

```python
def dropped(
    original: str, suggestion: str, brand_names: Sequence[str]
) -> list[str]:
    """The original title's words whose stem is not in the suggestion:
    stopwords, brand stems, pure numbers and 1-letter tokens ignored;
    lowercased, in original order, without repeats."""
    have = fold_set(suggestion) | _brand_stems(brand_names)
    out: list[str] = []
    for tok in tokens(original):
        if len(tok) < 2 or tok.isdigit() or tok in STOPWORDS:
            continue
        if _stem(tok) not in have and tok not in out:
            out.append(tok)
    return out
```

Replace `rule_check`:

```python
def rule_check(
    original: str, suggestion: str, brand_names: Sequence[str]
) -> tuple[str, str, list[str]]:
    """(title, status, dropped_words). Fixes rather than retries: the
    brand is prepended if the original had it and the suggestion lost it;
    a word that repeats an earlier word's stem is dropped whole
    (punctuation-only words are kept); trailing CONNECTORS are removed;
    the title is trimmed to MAX_TITLE_CHARS at a word boundary. Status:
    "review" if the final title lost any of the original's words, else
    "adjusted" if it differs from the suggestion, else "pass"."""
    title = suggestion
    brand = _brand_in(original, brand_names)
    if brand and _brand_in(title, [brand]) is None:
        title = f"{brand} {title}".strip()
    seen: set[str] = set()
    kept: list[str] = []
    for word in title.split():
        stems = fold_set(word)
        if stems & seen:
            continue
        seen |= stems
        kept.append(word)
    while kept and kept[-1].casefold() in CONNECTORS:
        kept.pop()
    title = " ".join(kept)
    if len(title) > MAX_TITLE_CHARS:
        cut = title[: MAX_TITLE_CHARS + 1]
        space = cut.rfind(" ")
        title = cut[:space].rstrip() if space > 0 else title[:MAX_TITLE_CHARS]
    lost = dropped(original, title, brand_names)
    if lost:
        return title, "review", lost
    return title, ("pass" if title == suggestion else "adjusted"), []
```

In `run_products`:
- R13's `cleared` dict gains `"dropped_words": None`;
- the rewrite write: `title, status, lost = rule_check(p["title"], suggestion, names)` and `.values(...)` gains `dropped_words=lost`.

- [ ] **Step 5: Run the tests**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_products.py tests/unit/test_recommend_copy.py tests/integration/test_products_run.py 2>&1 | tail -3`
Expected: PASS.

- [ ] **Step 6: Gate and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy && uv run pytest -q 2>&1 | tail -2`

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests && git commit -m "feat(products): fold plurals; flag dropped words for review"
```

---

### Task 3: The keyword step — key-based vote, run-wide key map, fit check and prompts

**Files:**
- Modify: `packages/core/bsi_core/products.py` (`keyword_key`, `_display`, `vote`, `fit_rank`, `keyword_prompt`, `rewrite_prompt`, `run_products`)
- Test: `tests/unit/test_products.py`, `tests/integration/test_products_run.py`

**Interfaces:**
- Consumes: `fold`, `fold_set`, `_stem` (Task 2).
- Produces: `keyword_key(keyword: str) -> str`; `vote(samples) -> list[str]` (display forms, one per key); `fit_rank(keywords: Sequence[str], title: str, category: str | None, description: str | None) -> list[str]`.

- [ ] **Step 1: Write the failing unit tests**

Add `fit_rank` and `keyword_key` to the imports in `tests/unit/test_products.py`, then:

```python
def test_vote_groups_plural_and_possessive_variants():
    samples = [["men's sandals"], ["mens sandal"], ["men flip flops"]]
    assert vote(samples) == ["men sandals", "men flip flops"]
    assert keyword_key("men's sandals") == keyword_key("mens sandal")


def test_fit_rank_prefers_the_title_then_category_and_drops_misfits():
    title, category = "Men Flip Flop Navy", "Slippers"
    assert fit_rank(["men slippers", "men flip flops"], title, category, None) == [
        "men flip flops",
        "men slippers",
    ]
    assert fit_rank(["men slippers"], title, category, None) == ["men slippers"]
    assert fit_rank(["kids shoes"], title, category, None) == []


def test_prompts_ask_for_plural_kids_keywords_and_kept_words():
    kp = keyword_prompt("Walkaroo", [])
    assert "kids" in kp and "plural" in kp
    assert "Keep every word" in rewrite_prompt("Walkaroo", [])
```

The existing `vote` tests (`test_vote_picks_the_most_frequent_rank_one`, `test_vote_ties_go_to_the_first_sample_and_cap_at_five`) must keep passing unchanged.

- [ ] **Step 2: Write the failing integration test**

In `tests/integration/test_products_run.py`, give `_generator` a `by_index=None` parameter and use it in the keywords branch: `"keywords": (by_index or {}).get(i) or keywords or ["kids sandals", "walkaroo kids"]`. Then:

```python
def test_plural_variants_share_one_search(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    with owner() as s, s.begin():
        for suffix in ("A", "B"):
            s.add(
                m.Product(
                    org_id=org.id,
                    brand_id=bid,
                    external_id=f"S-{suffix}",
                    title=f"Walkaroo Men Sandal {suffix}",
                    source="csv",
                )
            )
    engine = FakeEngine()
    gen = _generator(by_index={0: ["mens sandal"], 1: ["men sandals"]})
    job, rows, searches = _run(owner, org, bid, gen, engine)
    assert job.status == "done"
    assert engine.prompts == [("mens sandal buy online", "IN", "en")]
    assert len(searches) == 1
    assert [p.keyword for p in rows] == ["mens sandal", "mens sandal"]
```

- [ ] **Step 3: Run to see them fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/unit/test_products.py tests/integration/test_products_run.py 2>&1 | tail -5`
Expected: FAIL (`fit_rank`/`keyword_key` not importable; two searches).

- [ ] **Step 4: Implement**

In `products.py`, after `_clean` (move `_clean` above `vote` if needed so `_display` can use it):

```python
_POSSESSIVE = re.compile(r"['’]s\b")


def _display(keyword: str) -> str:
    """The keyword as stored and searched: lowercased, whitespace
    collapsed, possessive 's removed ("men's sandals" -> "men sandals")."""
    return _clean(_POSSESSIVE.sub("", keyword.casefold()))


def keyword_key(keyword: str) -> str:
    """Keywords with the same key are the same shopper phrase: plural,
    possessive and mens/men variants meet ("men sandal")."""
    return " ".join(_stem(t) for t in tokens(_display(keyword)))
```

Replace `vote`:

```python
def vote(samples: Sequence[Sequence[str]]) -> list[str]:
    """One product's ranked keywords from SAMPLES ranked lists, compared
    by keyword_key: rank 1 is the key most often at rank 1 (ties: sample
    order), then the other keys in first-seen order; each key shown in
    its first surface form (_display); at most MAX_KEYWORDS."""
    keyed = [
        [(key, k) for k in sample if (key := keyword_key(k))]
        for sample in samples
    ]
    firsts = [s[0][0] for s in keyed if s]
    if not firsts:
        return []
    counts = Counter(firsts)
    top = max(firsts, key=lambda k: (counts[k], -firsts.index(k)))
    shown: dict[str, str] = {}
    for sample_keys in keyed:
        for key, k in sample_keys:
            shown.setdefault(key, _display(k))
    order = [top]
    for sample_keys in keyed:
        for key, _k in sample_keys:
            if key not in order:
                order.append(key)
    return [shown[key] for key in order[:MAX_KEYWORDS]]
```

Add `fit_rank` after `drop_brand_terms`:

```python
def fit_rank(
    keywords: Sequence[str],
    title: str,
    category: str | None,
    description: str | None,
) -> list[str]:
    """Keywords whose category word (the last word) names this product:
    first those whose category stem is in the title, then those whose
    stem is only in the category or description; others are dropped, so
    a flip flop is never searched as "men slippers" when a title fit
    exists, and never as "kids shoes" at all."""
    in_title = fold_set(title)
    in_other = fold_set(category or "") | fold_set(description or "")
    first: list[str] = []
    second: list[str] = []
    for k in keywords:
        words = fold(k)
        if not words:
            continue
        if words[-1] in in_title:
            first.append(k)
        elif words[-1] in in_other:
            second.append(k)
    return first + second
```

Replace the two prompts:

```python
def keyword_prompt(brand: str, products: Sequence[dict[str, Any]]) -> str:
    """The ADK keyword-finding prompt, one call per batch, JSON out."""
    return (
        "You find the keywords shoppers type when looking for products "
        f"like these from the brand {brand!r}.\n"
        f"For each product give up to {MAX_KEYWORDS} keywords, lowercase, "
        "generic first. Rank 1 is a broad shopper phrase: the audience "
        "plus the product's own category, in the plural (for example "
        '"kids sandals", "men flip flops", "women slippers"). Use "kids" '
        'for children\'s products, not "boys" or "girls". Never replace '
        "the product's type with a different one. More specific phrases "
        "come after rank 1. Never include the brand name. One keyword per "
        "entry. Given the same products, choose the same rank 1.\n"
        'Return JSON {"products": [{"index": <index>, '
        '"keywords": [...]}, ...]} with one entry per input index.\n'
        "Products:\n"
        + _product_lines(products, "description", "attributes", "category")
    )
```

```python
def rewrite_prompt(brand: str, products: Sequence[dict[str, Any]]) -> str:
    return (
        f"Rewrite each product title for the brand {brand!r}.\n"
        "Keep every word of the original title (you may reorder them); "
        "add the keyword and the missing terms naturally; never change "
        "the product type; repeat no word; no keyword stuffing. Each new "
        f"title is at most {MAX_TITLE_CHARS} characters and keeps the "
        "brand name if the original has it. Also give "
        f"{MAX_BULLETS} short description bullet points.\n"
        'Return JSON {"products": [{"index": <index>, "title": ..., '
        '"bullets": [...]}, ...]} with one entry per input index.\n'
        "Products:\n"
        + _product_lines(
            products, "keyword", "missing", "description", "attributes"
        )
    )
```

In `run_products`, before the batch loop add `key_map: dict[str, str] = {}` (with a comment: one keyword string per key for the whole run, so variants share one search and one cache row). Replace the per-product keyword block with:

```python
            for i, p in enumerate(batch):
                ranked = vote([sm.get(i, []) for sm in samples])
                fitted = fit_rank(
                    drop_brand_terms(ranked, names),
                    p["title"],
                    p["category"],
                    p["description"],
                )
                p["keywords"] = [
                    key_map.setdefault(keyword_key(k), k) for k in fitted
                ]
                p["keyword"] = p["keywords"][0] if p["keywords"] else None
```

- [ ] **Step 5: Run the tests**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_products.py tests/unit/test_recommend_copy.py tests/integration/test_products_run.py 2>&1 | tail -3`
Expected: PASS. Every existing run test's products are titled "Walkaroo Boys Sandal N" with keyword "kids sandals", whose category word "sandals" fits the title, so their expected values do not change.

- [ ] **Step 6: Gate and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100 2>&1 | tail -2`

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests && git commit -m "feat(products): key-based keyword vote, shared searches and a fit check"
```

---

### Task 4: The tab shows `review` and the dropped words

**Files:**
- Modify: `apps/web/src/lib/format.ts`, `apps/web/src/lib/format.test.ts`
- Modify: `apps/web/src/app/(app)/b/[id]/products/page.tsx` (the Check cell)
- Modify: `tests/unit/test_recommend_copy.py` (`PRODUCT_CASES`)

**Interfaces:**
- Consumes: `Product.dropped_words` (generated type, Task 1).
- Produces: `droppedNote(words: string[] | null | undefined): string | null`.

- [ ] **Step 1: Write the failing test**

In `apps/web/src/lib/format.test.ts`, add `droppedNote` to the import list and:

```ts
test("droppedNote lists the words a suggestion lost", () => {
  expect(droppedNote(["casual", "school"])).toBe("dropped: casual, school");
  expect(droppedNote([])).toBeNull();
  expect(droppedNote(null)).toBeNull();
  expect(droppedNote(undefined)).toBeNull();
});
```

- [ ] **Step 2: Run to see it fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npx vitest run src/lib/format.test.ts 2>&1 | tail -4`
Expected: FAIL (`droppedNote` not exported).

- [ ] **Step 3: Implement**

Append to `format.ts`:

```ts
/** The original-title words a suggestion lost (rule_check "review"). */
export const droppedNote = (words: string[] | null | undefined) =>
  words && words.length > 0 ? `dropped: ${words.join(", ")}` : null;
```

In `page.tsx` import `droppedNote` from `@/lib/format` and replace the Check cell with:

```tsx
                <td>
                  {p.rule_check && <span className="tag">{p.rule_check}</span>}
                  {droppedNote(p.dropped_words) && (
                    <div className="muted">{droppedNote(p.dropped_words)}</div>
                  )}
                </td>
```

In `tests/unit/test_recommend_copy.py` `PRODUCT_CASES`, add `"review"` and `"dropped: "` after `"adjusted"`.

- [ ] **Step 4: Run the web gate and the copy test**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform/apps/web && npm run gate 2>&1 | tail -6`
Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_recommend_copy.py 2>&1 | tail -2`
Expected: both pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/web/src/lib/format.ts apps/web/src/lib/format.test.ts "apps/web/src/app/(app)/b/[id]/products/page.tsx" tests/unit/test_recommend_copy.py && git commit -m "feat(web): show the review status and dropped words"
```

---

### Task 5: Docs — findings, index, rulings, plan changes

**Files:**
- Create: `docs/findings-slice19.md`
- Modify: `docs/README.md` (three rows after the slice 18 rows), the spec's `## Rulings`, this plan (`## Changes made during execution`)

- [ ] **Step 1: Findings.** `docs/findings-slice19.md`: `## 1. What was built` (the functions, migration 0020, API/export/tab changes, a commit table from `git log --oneline main..HEAD`); `## 2. Live check on dev` with exactly "Not yet run. The controller runs it after the user approves migrating dev to 0020; results are recorded here then."; `## 3. Deferred and untested` with every `minor (deferred)` ledger line in plain sentences plus the spec's Out of scope.
- [ ] **Step 2: README rows** for the spec, the plan and the findings, in the slice 18 rows' format.
- [ ] **Step 3: Rulings** from the ledger into the spec, each with what was decided, why and the cost if wrong; update any spec text a ruling changed.
- [ ] **Step 4: Plan changes** section listing every deviation from these tasks.
- [ ] **Step 5: Coverage check.** A scripted grep of the new docs for every ledger ruling ID and every `minor (deferred)` line's key phrase; report the misses and fix them.
- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add docs && git commit -m "docs: slice 19 findings, index and rulings"
```

---

## Self-review

- **Spec coverage:** §1 → Task 2 (fold, missing, repeat check, connectors); §2 → Task 1 (migration, model, API, export) and Task 2 (`dropped`, 3-tuple, run writes, R13) and Task 4 (tab); §3 → Task 3 (prompts, key vote, key map, fit check); §4 tests → the test steps of Tasks 1–4; §5 dev re-check → the controller after Task 5.
- **Spec §4 values, word for word:** `fold("Men's Sandals") == ["men", "sandal"]`, `fold("Flip-Flops") == ["flip", "flop"]` (Task 2); `missing(...) == ["summer", "kids"]` (Task 2); the three new `rule_check` cases and the two changed ones (Task 2); `vote(...) == ["men sandals", "men flip flops"]` (Task 3); the three `fit_rank` cases (Task 3); "kids", "plural", "Keep every word" (Task 3); `review` and `dropped:` in `PRODUCT_CASES` (Task 4); one search for `mens sandal`/`men sandals` (Task 3); `review` + `dropped_words` stored and R13 clearing (Task 2); API and export (Task 1); CHECK accepts `review` and rejects an unknown value (Task 1).
- **Traced by hand:** `dropped("Walkaroo Boys Sandal 3 for x", "Walkaroo Sandal", BRAND) == ["boys"]` (walkaroo brand, 3 a number, for a stopword, x one letter); the trim case's original "Plain" is absent from the w-words, so `review`/`["plain"]`; "Walkaroo Blue Boys Sandal And Sandals" → Sandals repeats sandal, trailing And stripped → `adjusted`, nothing dropped; the integration product "Walkaroo Boys Sandal 0" vs "Walkaroo Kids Summer Sandals" loses only "boys" ("0" is one character).
- **Existing vote tests:** `keyword_key` keeps 1-letter tokens (it strips the possessive first), so the `["a", "b", "c"]` tie test still groups each letter as its own key.
- **Fixtures vs banned words:** sandal, flip, flop, casual, boots, summer, Walkaroo, Red Tape — none banned. The new prompts contain none of the banned words.
- **Types:** `rule_check` returns 3 values everywhere (Task 2 updates the only non-test caller); `vote` still returns `list[str]`; `fit_rank`'s signature matches its one caller.

## Changes made during execution

- **Ruling R1 (Task 3).** `keyword_key` is `" ".join(_stem(t) for t in tokens(_display(k)))`, as Task 3's code already had it: the possessive is stripped first and 1-letter tokens are kept. The spec's §3 text (`" ".join(fold(k))`) was the one that changed; the task code did not. The preflight scan found the mismatch before Task 3 was dispatched, and R1 was appended to Task 3's brief.
- **Ruling R2 (Task 2, fix round 1, commit 95f62ca).** Task 2's code stripped trailing connectors before the 150-character trim only, so a trimmed title could end in "for" or "and". A helper `_strip_connectors(words)` was added, and `rule_check` now calls it before the trim and again on the trimmed title's words. Status and `dropped` still run on the final title.
- **The trim-connector test (Task 2, fix round 1).** New test `test_rule_check_strips_a_connector_the_trim_leaves_at_the_end` in `tests/unit/test_products.py`, which also imports `CONNECTORS`. The ruling's example used 46 words plus "for", which joins to 173 characters, so the cut would never land on "for". The test uses 39 words instead: `"w0 … w38 for"` is 149 characters and `" tail"` would pass 150, so the cut lands just after "for". It asserts `len(fixed) <= 150` and that the last word is not in `CONNECTORS`.
- **RUF001 escape (Task 3).** The plan's `_POSSESSIVE = re.compile(r"['’]s\b")` fails ruff RUF001 (the curly apostrophe U+2019 is ambiguous). It is written as `r"['’]s\b"`; `re` reads `’` in a str pattern, so the regex is the same. The implementer checked `_display("Men’s Sandals") == "men sandals"` and re-ran ruff, mypy and the unit files afterwards; the full suite was not re-run after this one-line change.
- **Tasks 1 and 4.** No deviation reported. Task 1 kept the plan's `type_="check"` on the constraint drop, which 0018 omits; it makes no difference on Postgres. Task 4 kept the plan's snippet that calls `droppedNote` twice per row.
