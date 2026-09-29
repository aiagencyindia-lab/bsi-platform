# Slice 20 Product Titles, Not Store Names Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Grounded title searches return product titles, store names never reach `missing`, and no "Com" appears in suggestions.

**Architecture:** A new `search_query(keyword)` replaces the inline `"{keyword} buy online"`. A cached `keyword_search` row is a hit only when its stored `query` equals the new query. `titles_prompt` names the new query and forbids store names. A new `drop_stores` filter runs on the parsed titles before `keep_present`, and `STOPWORDS` gains `com`. All code is in `packages/core/bsi_core/products.py`; there is no schema, API or web change.

**Tech Stack:** Python 3.13, SQLAlchemy 2, pydantic 2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-slice20-product-titles-not-stores-design.md`

## Global Constraints

- Repo root is `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- Do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB, the network or the worker loop.
- Tests use the shared `bsi_test` DB. Run `pgrep -fl pytest` first, and never run two suites at once.
- ruff: line length 80, and RUF001 rejects a literal curly apostrophe. `mypy --strict` runs over `packages/core/bsi_core`.
- `search_query(keyword)` returns exactly `f"{keyword}: popular products to buy online, with each product's full title"`. The apostrophe is a straight `'`.
- The new `titles_prompt` sentence is exactly "A product title names one product; never list a store, retailer, marketplace or brand name on its own."
- Copy (prompts, queries, fixtures) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat` or `certain`.
- No schema, API or web change, so there is no `npm run gen`.
- Commit trailer: the `Co-Authored-By` line from the latest session reminder.

## Changes to existing tests that the spec implies

| Test | Change | Task |
|---|---|---|
| `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` (integration) | the engine prompt is `products.search_query("kids sandals")` | 1 |
| `test_an_error_search_is_not_reused` (integration) | the engine prompt is `products.search_query("kids sandals")`; its seeded `query="q"` row stays | 1 |
| `test_plural_variants_share_one_search` (integration) | the engine prompt is `products.search_query("mens sandal")` | 1 |
| `test_a_fresh_search_is_reused_and_a_stale_one_redone` (integration) | the fresh row is seeded with `query=products.search_query("kids sandals")` instead of `"q"` | 1 |
| `PRODUCT_CASES` (`tests/unit/test_recommend_copy.py`) | imports `search_query` and gains `search_query("kids shoes")` | 1 |

The rows seeded in `test_isolation.py`, `test_api_products.py` and `test_rls.py` stay as they are: `run_products` never reads them.

## File map

| File | Responsibility |
|---|---|
| `packages/core/bsi_core/products.py` | `search_query`, the cache-hit check, `titles_prompt`, `drop_stores`, `STOPWORDS` |
| `tests/unit/test_products.py` | `search_query`, `drop_stores`, `titles_prompt` and `missing` cases |
| `tests/unit/test_recommend_copy.py` | `PRODUCT_CASES` |
| `tests/integration/test_products_run.py` | query assertions, cache tests, the store-name run |
| docs | `docs/findings-slice20.md`, `docs/README.md`, the spec's Rulings, this plan's changes section |

---

### Task 1: The new query, the cache-hit check and the prompt's first line

**Files:**
- Modify: `packages/core/bsi_core/products.py`: add `search_query` next to `titles_prompt` (around line 624); change `titles_prompt`; change the cache generator (lines 797–809) and the query line (line 823)
- Test: `tests/unit/test_products.py`, `tests/unit/test_recommend_copy.py`, `tests/integration/test_products_run.py`

**Interfaces:**
- Produces: `search_query(keyword: str) -> str`, used by `run_products`, `titles_prompt` and the tests.

- [ ] **Step 1: Write the failing unit tests.** In `tests/unit/test_products.py`, add `search_query` to the `from bsi_core.products import (...)` list in alphabetical order (after `rule_check`), then add:

```python
def test_search_query_asks_for_products_with_full_titles():
    assert search_query("kids sandals") == (
        "kids sandals: popular products to buy online, "
        "with each product's full title"
    )


def test_titles_prompt_names_the_new_query_and_forbids_stores():
    tp = titles_prompt("kids sandals", "answer text", ["amazon.in"])
    assert search_query("kids sandals") in tp
    assert "buy online." not in tp
    assert (
        "never list a store, retailer, marketplace or brand name on its own"
        in tp
    )
```

In `tests/unit/test_recommend_copy.py`, change the import line to:

```python
from bsi_core.products import (
    keyword_prompt,
    rewrite_prompt,
    search_query,
    titles_prompt,
)
```

and add `search_query("kids shoes"),` to the `PRODUCT_CASES += [...]` list after `titles_prompt("kids shoes", "", []),`.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_products.py tests/unit/test_recommend_copy.py -q`
Expected: collection fails with `ImportError: cannot import name 'search_query'`.

- [ ] **Step 3: Implement `search_query` and the prompt.** In `products.py`, add this directly above `def titles_prompt`:

```python
def search_query(keyword: str) -> str:
    """The grounded search that should list products, not stores."""
    return (
        f"{keyword}: popular products to buy online, "
        "with each product's full title"
    )
```

Replace `titles_prompt`'s body with:

```python
    return (
        f"The text below answers the search {search_query(keyword)!r}.\n"
        f"List up to {TOP_TITLES} distinct product titles that appear "
        "verbatim in the text, in the order they appear, each with the "
        "seller's domain when the text names it (else an empty string). "
        "Do not invent titles or shorten them. A product title names one "
        "product; never list a store, retailer, marketplace or brand name "
        "on its own.\n"
        f"Known source domains: {', '.join(domains) or 'none'}\n"
        'Return JSON {"titles": [{"title": ..., "domain": ...}]}.\n'
        f"Text:\n{text}"
    )
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_products.py tests/unit/test_recommend_copy.py -q`
Expected: all pass.

- [ ] **Step 5: Write the failing integration changes.** In `tests/integration/test_products_run.py`:

1. In `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` and `test_an_error_search_is_not_reused`, replace
   `assert engine.prompts == [("kids sandals buy online", "IN", "en")]`
   with:

```python
    assert engine.prompts == [
        (products.search_query("kids sandals"), "IN", "en")
    ]
```

2. In `test_plural_variants_share_one_search`, the same change for `"mens sandal"`:

```python
    assert engine.prompts == [
        (products.search_query("mens sandal"), "IN", "en")
    ]
```

3. In `test_a_fresh_search_is_reused_and_a_stale_one_redone`, change the seeded row's `query="q",` to `query=products.search_query("kids sandals"),`.

4. Add after `test_an_error_search_is_not_reused`:

```python
def test_a_search_under_the_old_query_is_redone(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    with owner() as s, s.begin():
        s.add(
            m.KeywordSearch(
                org_id=org.id,
                brand_id=bid,
                keyword="kids sandals",
                query="kids sandals buy online",
                titles=[{"title": "Cached Summer Sandals", "domain": "c"}],
                searched_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
    engine = FakeEngine()
    _, _rows, searches = _run(owner, org, bid, _generator(), engine)
    query = products.search_query("kids sandals")
    assert engine.prompts == [(query, "IN", "en")]
    assert len(searches) == 1 and searches[0].query == query
    assert searches[0].titles == [
        {"title": "Kids Sandals for Boys Summer", "domain": "amazon.in"},
        {"title": "Boys Summer Sandals Lightweight", "domain": ""},
    ]
```

- [ ] **Step 6: Run them to verify the new test fails**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest tests/integration/test_products_run.py -q`
Expected: the three prompt assertions and `test_a_search_under_the_old_query_is_redone` fail, because the run still sends `"kids sandals buy online"` and reuses the old row. `test_a_fresh_search_is_reused_and_a_stale_one_redone` passes.

- [ ] **Step 7: Implement the query and the cache check in `run_products`.** Replace the cache generator's body so a row must also match the query:

```python
            with tenant_session(org_id) as s:
                titles_by_kw.update(
                    (row.keyword, list(row.titles))
                    for row in s.scalars(
                        select(m.KeywordSearch).where(
                            m.KeywordSearch.brand_id == brand_id,
                            m.KeywordSearch.keyword.in_(ordered),
                            m.KeywordSearch.searched_at > fresh_after,
                            # R9: an error row is searched again
                            m.KeywordSearch.error.is_(None),
                        )
                    )
                    # a row from an older query wording is searched again
                    if row.query == search_query(row.keyword)
                )
```

and replace `query = f"{keyword} buy online"` with `query = search_query(keyword)`.

- [ ] **Step 8: Run the integration file and the unit files to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest tests/integration/test_products_run.py tests/unit/test_products.py tests/unit/test_recommend_copy.py -q`
Expected: all pass.

- [ ] **Step 9: Lint and type-check**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy`
Expected: no errors.

- [ ] **Step 10: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests && git commit -m "feat(products): ask the grounded search for products; redo old-query rows"
```

---

### Task 2: Drop store names from parsed titles; `com` is a stopword

**Files:**
- Modify: `packages/core/bsi_core/products.py`: import `normalize_domain`; `STOPWORDS` (line 318); add `drop_stores` after `keep_present` (around line 557); wrap the parsed list in `run_products` (lines 845–851)
- Test: `tests/unit/test_products.py`, `tests/integration/test_products_run.py`

**Interfaces:**
- Consumes: `search_query` (Task 1), used only by the tests.
- Produces: `drop_stores(titles: list[dict[str, Any]], domains: Sequence[str]) -> list[dict[str, Any]]`.

- [ ] **Step 1: Write the failing unit tests.** In `tests/unit/test_products.py`, add `import pytest` to the imports if it is missing, and add `drop_stores` to the `from bsi_core.products import (...)` list in alphabetical order (after `drop_brand_terms`). Then add:

```python
@pytest.mark.parametrize(
    ("title", "domains"),
    [
        ({"title": "Famous Footwear", "domain": "famousfootwear.com"}, []),
        ({"title": "Zappos.com", "domain": "zappos.com"}, []),
        ({"title": "REEF", "domain": "reef.com"}, []),
        ({"title": "Kids Foot Locker", "domain": "www.kidsfootlocker.com"}, []),
        ({"title": "Zappos.com", "domain": ""}, ["zappos.com"]),
        ({"title": "Buy at ShopWSS.com", "domain": "shopwss.com"}, []),
        ({"title": "Zappos", "domain": "https://www.zappos.com/kids"}, []),
    ],
)
def test_drop_stores_drops_a_store_name(title, domains):
    assert drop_stores([title], domains) == []


def test_drop_stores_keeps_product_titles_in_order():
    titles = [
        {"title": "Crocs Classic Clog", "domain": "crocs.com"},
        {"title": "Zappos Kids Sandal", "domain": ""},
        {"title": "Amazon Essentials Sandal", "domain": "amazon"},
        {"title": "Kids Lanner Ridge II Slipper", "domain": ""},
        # The documented ceiling: a store named unlike its domain is left
        # to the prompt. A later fix that catches it flips this case.
        {"title": "Journeys Kidz", "domain": "journeys.com"},
    ]
    assert drop_stores(titles, ["zappos.com"]) == titles


def test_missing_never_suggests_com():
    got = missing("Blue Sandal", ["Zappos com sandal", "ShopWSS com sandal"], [])
    assert "com" not in got
```

The one list call covers the spec's kept cases: `domains=["zappos.com"]` is what "Zappos Kids Sandal" needs, and none of the other four matches zappos.com. If ruff wraps the `Kids Foot Locker` or `missing` line, accept its formatting.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_products.py -q`
Expected: collection fails with `ImportError: cannot import name 'drop_stores'`.

- [ ] **Step 3: Implement.** In `products.py`, add `from .matching import normalize_domain` to the relative imports in alphabetical order (after `from .judge import JudgeFailed`). Change `STOPWORDS` to:

```python
STOPWORDS = frozenset(
    "and for the with from your our this that are you all any buy online "
    "free shop shopping sale offer offers price prices deal deals off "
    "new a an in of on to by at or com".split()
)
```

Add after `keep_present`:

```python
def drop_stores(
    titles: list[dict[str, Any]], domains: Sequence[str]
) -> list[dict[str, Any]]:
    """Titles that are not a store: a title is dropped when its letters
    and digits, joined, equal a known domain's name or joined form
    ("Famous Footwear" = famousfootwear.com, "Zappos.com" = zappos.com),
    or it contains a known dotted domain ("Buy at ShopWSS.com"). Known
    domains are the title's own plus the cited ones, normalised. Order
    kept. ponytail: a subdomain's name is its first label (shop.nike.com
    -> "shop"), and a store named unlike its domain ("Journeys Kidz",
    journeys.com) is left to titles_prompt; a store list would catch it."""
    cited = [normalize_domain(d) for d in domains]
    out: list[dict[str, Any]] = []
    for t in titles:
        title = str(t.get("title") or "")
        squashed = "".join(tokens(title))
        low = title.casefold()
        own = normalize_domain(str(t.get("domain") or ""))
        if not any(
            squashed in (d.split(".")[0], "".join(tokens(d)))
            or ("." in d and d in low)
            for d in (own, *cited)
            if d
        ):
            out.append(t)
    return out
```

In `run_products`, wrap the parsed list:

```python
                    row["titles"] = keep_present(
                        drop_stores(
                            [
                                t.model_dump()
                                for t in TitleSet.model_validate_json(
                                    raw
                                ).titles
                            ],
                            domains,
                        ),
                        parsed.text,
                    )
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_products.py -q`
Expected: all pass.

- [ ] **Step 5: Write the failing integration test.** In `tests/integration/test_products_run.py`, give `_generator` a `titles=None` parameter:

```python
def _generator(
    owner=None, fail_on=None, keywords=None, by_index=None, titles=None
):
```

and change its titles branch to:

```python
        elif kind == "titles":
            body = {
                "titles": titles
                or [
                    {
                        "title": "Kids Sandals for Boys Summer",
                        "domain": "amazon.in",
                    },
                    {"title": "Boys Summer Sandals Lightweight", "domain": ""},
                    {"title": "Invented Sandal", "domain": "x"},
                ]
            }
```

Then add after `test_a_search_under_the_old_query_is_redone`:

```python
def test_store_names_are_not_stored_as_titles(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    answer = "Shop **Kids Classic Sandal** and more at Zappos.com."
    engine = FakeEngine(
        [
            EngineResult(
                "ok", raw={"text": answer}, model="fake-1", cost_micros=35_000
            )
        ]
    )
    gen = _generator(
        titles=[
            {"title": "Zappos.com", "domain": "zappos.com"},
            {"title": "Kids Classic Sandal", "domain": ""},
        ]
    )
    _, _rows, searches = _run(owner, org, bid, gen, engine)
    assert searches[0].titles == [
        {"title": "Kids Classic Sandal", "domain": ""}
    ]
```

- [ ] **Step 6: Run it to verify it fails, then passes**

Before Step 3 the test would store both titles, because `keep_present` finds "Zappos.com" in the answer. With Step 3 already in place, run it now and confirm it passes. Then confirm it fails without the filter: temporarily replace `drop_stores(...)` in `run_products` with its first argument, run the test, see it fail on the stored titles, and restore the call. Leave the working tree with `drop_stores` in place.

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest tests/integration/test_products_run.py -q`
Expected: all pass (with `drop_stores` restored).

- [ ] **Step 7: Lint and type-check**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests && git commit -m "fix(products): drop store names from parsed titles; com is a stopword"
```

---

### Task 3: Docs: findings, index, rulings, plan changes

**Files:**
- Create: `docs/findings-slice20.md`
- Modify: `docs/README.md` (three rows after the slice 19 rows), the spec's `## Rulings`, this plan's `## Changes made during execution`

- [ ] **Step 1: Findings.** Write `docs/findings-slice20.md` with three sections:
  - `## 1. What was built`: `search_query`, the cache-hit check, the `titles_prompt` changes, `drop_stores` and the `com` stopword, plus a commit table from `git log --oneline main..HEAD`.
  - `## 2. Live check on dev`: exactly "Not yet run. The controller runs it after the user approves; results are recorded here then."
  - `## 3. Deferred and untested`: every `minor (deferred)` ledger line in plain sentences, plus the spec's Out of scope.
- [ ] **Step 2: README rows** for the spec, the plan and the findings, in the slice 19 rows' format.
- [ ] **Step 3: Rulings.** Copy the rulings from the ledger into the spec, each with what was decided, why, and the cost if wrong. Update any spec text a ruling changed. If there are none, the section keeps "None yet." replaced by "None."
- [ ] **Step 4: Plan changes.** List every deviation from these tasks in this plan's changes section.
- [ ] **Step 5: Coverage check.** Run a scripted grep of the new docs for every ledger ruling ID and every `minor (deferred)` line's key phrase. Report the misses and fix them.
- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add docs && git commit -m "docs: slice 20 findings, index and rulings"
```

---

## Self-review

- **Spec coverage:**

  | Spec section | Where it is covered |
  |---|---|
  | §1 `search_query` | Task 1 |
  | §1 cache check | Task 1 |
  | §2 `titles_prompt` first line and sentence | Task 1 |
  | §2 `drop_stores` and its wiring | Task 2 |
  | §2 `com` stopword | Task 2 |
  | §3 unit tests | Tasks 1–2 |
  | §3 copy case | Task 1 |
  | §3 integration tests | Tasks 1–2 |
  | §4 dev re-check | The controller, after Task 3 |

- **Spec §3 values, word for word:**
  - `search_query("kids sandals")` exact text.
  - The seven dropped cases (the spec's six plus the normalised URL) and the five kept cases, all verbatim.
  - `titles_prompt("kids sandals", "answer text", ["amazon.in"])`: contains `search_query(...)`, does not contain "buy online.", and contains the store rule.
  - `missing("Blue Sandal", ["Zappos com sandal", "ShopWSS com sandal"], [])` does not contain `com`.
  - `PRODUCT_CASES` gains `search_query("kids shoes")`.
  - The three named prompt assertions.
  - The reuse test seeds `search_query("kids sandals")`.
  - The old-query row (`"kids sandals buy online"`) is searched again, with the new `query` and titles.
  - The Zappos.com / Kids Classic Sandal run stores only "Kids Classic Sandal".
- **Traced by hand:**
  - "Zappos" with domain `https://www.zappos.com/kids`: `normalize_domain` gives zappos.com, whose name `zappos` equals the squashed title, so it is dropped.
  - "Zappos Kids Sandal" with zappos.com cited: `zapposkidssandal` equals neither `zappos` nor `zapposcom`, and zappos.com is not in the title, so it is kept.
  - "Amazon Essentials Sandal" with domain `amazon`: no dot means no substring test, and the name `amazon` does not equal the squashed title, so it is kept.
  - The existing integration titles:
    - "Invented Sandal" (domain `x`) passes `drop_stores` and is dropped by `keep_present`, as before.
    - "Kids Sandals for Boys Summer" is compared with amazon.in, whose name `amazon` does not match, so it is kept.
    - So `test_one_search_…` still stores its two titles.
  - The Task 2 integration answer contains both "Kids Classic Sandal" and "Zappos.com", so without `drop_stores` both would be stored. The test tells the two cases apart.
  - `missing`: without `com` in `STOPWORDS`, `com` is in 2 titles and is returned; with it, the result is `[]`.
  - The `titles_prompt` first line reprs the query with double quotes (it contains `'`). `search_query(...) in tp` checks the unquoted text, which is a substring, so it holds.
- **Fixtures vs banned words:** the fixtures use Zappos, ShopWSS, REEF, Famous Footwear, Kids Foot Locker, Crocs, Amazon Essentials, Journeys Kidz, Lanner Ridge, and "Shop … and more at". None is a banned word. The query and the prompt sentence contain none.
- **Types:**
  - `drop_stores` returns `list[dict[str, Any]]`, which `keep_present` accepts.
  - `normalize_domain` takes and returns `str`.
  - `search_query` is `str -> str` everywhere.
- **Every place this plan's code departs from the spec text:**
  1. The spec's five kept cases are tested in one call with `domains=["zappos.com"]` rather than one call per title. The spec gives `domains=["zappos.com"]` only for "Zappos Kids Sandal"; the other four are unaffected by that domain, as traced above. The seven dropped cases are one call each, as the spec lists them.
  2. The spec says "each passed through `matching.normalize_domain`; empty results are skipped". The code also skips an empty *own* domain, which is the same rule applied to the title's own field.
  3. Edge case not in the spec: a known domain that normalises to something starting with `.` (e.g. `.com`) has an empty name, so an empty title would be dropped. `keep_present` drops empty titles anyway, so what gets stored does not change.
  4. The spec's new integration test for the old query is named here `test_a_search_under_the_old_query_is_redone`, and the store-name test `test_store_names_are_not_stored_as_titles`. The spec gives no names.
  5. Task 2 Step 6 checks the failing case by temporarily removing the call. The integration test is written after the implementation, because the unit tests drive `drop_stores` first.
  6. The docstrings and code comments are the plan's own wording. The spec requires only the ceiling comment's content (subdomain first label; store named unlike its domain).

## Changes made during execution

None yet.
