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
| `test_an_error_search_is_not_reused` (integration) | the engine prompt is `products.search_query("kids sandals")`; its seeded error row uses `query=products.search_query("kids sandals")` (Ruling R1) | 1 |
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

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_products.py tests/unit/test_recommend_copy.py -q`
Expected: only `test_titles_prompt_names_the_new_query_and_forbids_stores` fails, on `search_query("kids sandals") in tp`, because `titles_prompt` still uses the old wording.

Then replace `titles_prompt`'s body with:

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

- [ ] **Step 1: Write the failing unit tests.** In `tests/unit/test_products.py`, add `import pytest` as the first line of the second import block, directly before `from bsi_core.products import (` (the file has no `import pytest` today), and add `drop_stores` to the `from bsi_core.products import (...)` list in alphabetical order (after `drop_brand_terms`). Then add:

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


def test_drop_stores_keeps_order_around_a_dropped_title():
    crocs = {"title": "Crocs Classic Clog", "domain": "crocs.com"}
    reef = {"title": "REEF", "domain": "reef.com"}
    lanner = {"title": "Kids Lanner Ridge II Slipper", "domain": ""}
    assert drop_stores([crocs, reef, lanner], []) == [crocs, lanner]


def test_missing_never_suggests_com():
    got = missing("Blue Sandal", ["Zappos com sandal", "ShopWSS com sandal"], [])
    assert "com" not in got
```

The one list call covers the spec's kept cases: `domains=["zappos.com"]` is what "Zappos Kids Sandal" needs, and none of the other four matches zappos.com. If ruff wraps the `Kids Foot Locker` or `missing` line, accept its formatting.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_products.py -q`
Expected: collection fails with `ImportError: cannot import name 'drop_stores'`.

- [ ] **Step 3: Implement `drop_stores`.** In `products.py`, add `from .matching import normalize_domain` to the relative imports in alphabetical order (after `from .judge import JudgeFailed`). Add after `keep_present`:

```python
def drop_stores(
    titles: list[dict[str, Any]], domains: Sequence[str]
) -> list[dict[str, Any]]:
    """Titles that are not a store: a title is dropped when its letters
    and digits, joined, equal a known domain's name or joined form
    ("Famous Footwear" = famousfootwear.com, "Zappos.com" = zappos.com),
    or it contains a known dotted domain ("Buy at ShopWSS.com"). Known
    domains are the title's own plus the cited ones, normalised. Order
    kept."""
    # ponytail: a subdomain's name is its first label (shop.nike.com ->
    # "shop"), and a store named unlike its domain ("Journeys Kidz",
    # journeys.com) is left to titles_prompt; a store list would catch it.
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

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_products.py -q`
Expected: only `test_missing_never_suggests_com` fails, returning `['com']`.

- [ ] **Step 4: Make `com` a stopword and verify the unit tests pass.** Change `STOPWORDS` to:

```python
STOPWORDS = frozenset(
    "and for the with from your our this that are you all any buy online "
    "free shop shopping sale offer offers price prices deal deals off "
    "new a an in of on to by at or com".split()
)
```

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
                if titles is not None
                else [
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
- [ ] **Step 3: Rulings.** Copy the rulings from the ledger into the spec, each with what was decided, why, and the cost if wrong. Update any spec text a ruling changed. If there are none, replace "None yet. Rulings made during execution are added here with their R-number." with "None."
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
  | §3 gates (backend and `npm run gate`) | The controller, after Task 3 |
  | §3 idle-in-transaction probe | Unchanged: `drop_stores` adds no model call or session, so the existing probe test still expects its current count |
  | §2 0 or 1 surviving titles | No code: `missing` already needs `MIN_TITLES = 2` |
  | §4 dev re-check | The controller, after Task 3 |

- **Spec §3 values, word for word:**
  - `search_query("kids sandals")` exact text.
  - The spec's seven dropped cases and five kept cases, all verbatim.
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
  2. `test_drop_stores_keeps_order_around_a_dropped_title` (Crocs Classic Clog, REEF, Kids Lanner Ridge II Slipper gives the first and third) is not in spec §3. It tests the spec's "Order is kept" around a dropped title.
  3. Edge case not in the spec: a known domain that normalises to something starting with `.` (e.g. `.com`) has an empty name, so an empty title would be dropped. `keep_present` drops empty titles anyway, so what gets stored does not change.
  4. The spec's new integration test for the old query is named here `test_a_search_under_the_old_query_is_redone`, and the store-name test `test_store_names_are_not_stored_as_titles`. The spec gives no names.
  5. Task 2 Step 6 checks the failing case by temporarily removing the call. The integration test is written after the implementation, because the unit tests drive `drop_stores` first.
  6. The docstrings and code comments are the plan's own wording. The ceiling is a `# ponytail:` comment, as the spec says; its content (subdomain first label; store named unlike its domain) is the spec's.
  7. Task 1 Step 3 and Task 2 Steps 3–4 are split so that the `titles_prompt` test and the `com` test each fail for their own reason before their change lands.

---

## Extension: rival brand and model names (spec §5)

Added after the first dev live check. Tasks 1–3 are done; Tasks 4 and 5 implement spec §5. The Global Constraints above apply, plus:

- The new `titles_prompt` sentence is exactly "For each title also give its brand and its model or product-line name, each as written in the title, else an empty string."
- The prompt's JSON line becomes exactly `'Return JSON {"titles": [{"title": ..., "domain": ..., "brand": ..., "model": ...}]}.\n'`.

### Task 4: Brand and model per title; `missing` leaves them and competitors out

**Files:**
- Modify: `packages/core/bsi_core/products.py`: `missing` (around line 452), `keep_present` (around line 546), `TitleItem` (around line 599), `titles_prompt` (around line 662), `run_products` (brand load around line 741, cache generator around line 838, the `missing` loop around line 922)
- Test: `tests/unit/test_products.py`, `tests/integration/test_products_run.py`

**Interfaces:**
- Consumes: `search_query`, `drop_stores`, `keep_present`, `missing` as they are after Tasks 1–2.
- Produces: `missing(product_title: str, titles: Sequence[str], brand_names: Sequence[str], exclude: Sequence[str] = ()) -> list[str]`; `keep_present` returns dicts with keys `title`, `domain`, `brand`, `model`; `TitleItem.brand: str = ""`, `TitleItem.model: str = ""`.

- [ ] **Step 1: Write the failing unit tests.** In `tests/unit/test_products.py`, change the expected value in `test_keep_present_drops_titles_absent_from_the_text` to:

```python
    assert keep_present(titles, text) == [
        {
            "title": "Kids Sandals for Boys",
            "domain": "amazon.in",
            "brand": "",
            "model": "",
        }
    ]
```

and add:

```python
TEVA_KIDS = "Teva Hurricane XLT 2 Sandals - Kids'"


def test_keep_present_keeps_a_brand_and_model_named_in_the_title():
    got = keep_present(
        [
            {
                "title": TEVA_KIDS,
                "domain": "",
                "brand": "Teva",
                "model": "Hurricane XLT 2",
            }
        ],
        f"Try the {TEVA_KIDS} today.",
    )
    assert (got[0]["brand"], got[0]["model"]) == ("Teva", "Hurricane XLT 2")


def test_keep_present_blanks_a_brand_not_in_the_title():
    title = "Teva Original Universal Sandals"
    got = keep_present(
        [
            {
                "title": title,
                "domain": "",
                "brand": "Nike",
                "model": "Original Universal",
            }
        ],
        f"See {title}.",
    )
    assert (got[0]["brand"], got[0]["model"]) == ("", "Original Universal")


def test_keep_present_without_brand_or_model_keys_stores_empty():
    got = keep_present([{"title": "Kids Sandal", "domain": ""}], "Kids Sandal")
    assert (got[0]["brand"], got[0]["model"]) == ("", "")


TEVA_TITLES = [
    TEVA_KIDS,
    "Teva Hurricane XLT 2 Sandals - Toddlers'",
    "Teva Original Universal Sandals - Kids'",
]


def test_missing_leaves_out_excluded_brand_and_model_words():
    exclude = ["Teva", "Hurricane XLT 2", "Original Universal"]
    got = missing(
        "Blue Boys Sandal", TEVA_TITLES, ["BSOAgentTestBrand"], exclude=exclude
    )
    assert got == ["kids"]
    assert "teva" in missing("Blue Boys Sandal", TEVA_TITLES, ["BSOAgentTestBrand"])


def test_titles_prompt_asks_for_brand_and_model():
    tp = titles_prompt("kids sandals", "answer text", ["amazon.in"])
    assert (
        "For each title also give its brand and its model or product-line name"
        in tp
    )
```

Accept ruff's wrapping of any line over 80 columns.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_products.py -q`
Expected: the changed `keep_present` test and the three new `keep_present` tests fail on the missing `brand`/`model` keys (`KeyError` or a dict mismatch); `test_missing_leaves_out_excluded_brand_and_model_words` fails with `TypeError: missing() got an unexpected keyword argument 'exclude'`; `test_titles_prompt_asks_for_brand_and_model` fails on the missing sentence.

- [ ] **Step 3: Implement the pure functions.** In `products.py`, change `missing` to:

```python
def missing(
    product_title: str,
    titles: Sequence[str],
    brand_names: Sequence[str],
    exclude: Sequence[str] = (),
) -> list[str]:
    """Words of the ranking titles the product title lacks, compared by
    stem (fold): at least 3 characters, not a number, not a stopword, not
    a stem of the brand's names or of `exclude` (rival brands, models and
    competitor names), in at least MIN_TITLES titles. The first surface
    form seen is reported; by title count, then stem; MAX_MISSING."""
    have = fold_set(product_title) | _brand_stems([*brand_names, *exclude])
```

(the rest of the body is unchanged). Add above `keep_present`:

```python
def _named_in(value: Any, title: str) -> str:
    """value, stripped, when it has a token and all its tokens are in the
    title's tokens; else "". Keeps the parse from inventing exclusions."""
    v = str(value or "").strip()
    toks = tokens(v)
    return v if toks and set(toks) <= set(tokens(title)) else ""
```

and change `keep_present`'s docstring and append line to:

```python
    """Only titles found verbatim in the answer text (case and
    whitespace ignored), at most TOP_TITLES, domains lowercased; brand
    and model kept only when named in the title (_named_in)."""
```

```python
            out.append(
                {
                    "title": title,
                    "domain": domain,
                    "brand": _named_in(t.get("brand"), title),
                    "model": _named_in(t.get("model"), title),
                }
            )
```

Change `TitleItem` to:

```python
class TitleItem(BaseModel):
    title: str
    domain: str = ""
    brand: str = ""
    model: str = ""
```

In `titles_prompt`, change the lines from `"on its own.\n"` to the JSON line to:

```python
        "on its own. For each title also give its brand and its model or "
        "product-line name, each as written in the title, else an empty "
        "string.\n"
        f"Known source domains: {', '.join(domains) or 'none'}\n"
        'Return JSON {"titles": [{"title": ..., "domain": ..., '
        '"brand": ..., "model": ...}]}.\n'
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest tests/unit/test_products.py tests/unit/test_recommend_copy.py -q`
Expected: all pass.

- [ ] **Step 5: Write the failing integration changes.** In `tests/integration/test_products_run.py`:

1. In `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked`, `test_an_error_search_is_not_reused` and `test_a_search_under_the_old_query_is_redone`, change the expected stored titles to:

```python
    assert searches[0].titles == [
        {
            "title": "Kids Sandals for Boys Summer",
            "domain": "amazon.in",
            "brand": "",
            "model": "",
        },
        {
            "title": "Boys Summer Sandals Lightweight",
            "domain": "",
            "brand": "",
            "model": "",
        },
    ]
```

2. In `test_store_names_are_not_stored_as_titles`, change the expected value to:

```python
    assert searches[0].titles == [
        {"title": "Kids Classic Sandal", "domain": "", "brand": "", "model": ""}
    ]
```

3. In `test_a_fresh_search_is_reused_and_a_stale_one_redone`, change the seeded titles to:

```python
                titles=[
                    {
                        "title": "Cached Summer Sandals",
                        "domain": "c",
                        "brand": "",
                        "model": "",
                    }
                ],
```

4. In `test_a_search_under_the_old_query_is_redone`, change the seeded titles the same way (Ruling R2), so only the query-wording condition can force its re-search:

```python
                titles=[
                    {
                        "title": "Cached Summer Sandals",
                        "domain": "c",
                        "brand": "",
                        "model": "",
                    }
                ],
```

5. Add after `test_store_names_are_not_stored_as_titles`:

```python
def _fresh_row(owner, org, bid, titles):
    with owner() as s, s.begin():
        s.add(
            m.KeywordSearch(
                org_id=org.id,
                brand_id=bid,
                keyword="kids sandals",
                query=products.search_query("kids sandals"),
                titles=titles,
                searched_at=datetime.now(UTC) - timedelta(days=1),
            )
        )


def test_a_row_parsed_without_brand_is_redone(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    _fresh_row(owner, org, bid, [{"title": "Old Sandals", "domain": ""}])
    engine = FakeEngine()
    _, _rows, searches = _run(owner, org, bid, _generator(), engine)
    assert len(engine.prompts) == 1 and len(searches) == 1
    assert searches[0].titles[0] == {
        "title": "Kids Sandals for Boys Summer",
        "domain": "amazon.in",
        "brand": "",
        "model": "",
    }


def test_a_row_with_no_titles_is_a_hit(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    _fresh_row(owner, org, bid, [])
    engine = FakeEngine()
    _, rows, _searches = _run(owner, org, bid, _generator(), engine)
    assert engine.prompts == [] and rows[0].missing_keywords == []


RIVAL_TITLES = [
    ("Teva Hurricane Summer Sandals", "Teva", "Hurricane"),
    ("Teva Hurricane Summer Slides", "Teva", "Hurricane"),
    ("Crocs Summer Sandals", "", ""),
    ("Crocs Classic Summer Sandals", "", ""),
]


def test_rival_brands_models_and_competitors_are_not_missing_words(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    with owner() as s, s.begin():
        # (changed by R5) name="Deckers", aliases=["Crocs"], so "crocs"
        # is reached only through an alias.
        s.add(
            m.Competitor(
                org_id=org.id,
                brand_id=bid,
                name="Deckers",
                aliases=["Crocs"],
                status="suggested",
            )
        )
    answer = "Picks: " + "; ".join(t for t, _b, _m in RIVAL_TITLES) + "."
    engine = FakeEngine(
        [
            EngineResult(
                "ok", raw={"text": answer}, model="fake-1", cost_micros=35_000
            )
        ]
    )
    gen = _generator(
        titles=[
            {"title": t, "domain": "", "brand": b, "model": mo}
            for t, b, mo in RIVAL_TITLES
        ]
    )
    _, rows, _searches = _run(owner, org, bid, gen, engine)
    # Without the exclusions: ["summer", "crocs", "hurricane", "teva"].
    assert rows[0].missing_keywords == ["summer"]
```

- [ ] **Step 6: Run them to verify the new tests fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest tests/integration/test_products_run.py -q`
Expected (with Step 3 in place, before Step 7): `test_a_row_parsed_without_brand_is_redone` fails (`engine.prompts == []`: the row is still a hit) and `test_rival_brands_models_and_competitors_are_not_missing_words` fails with `['summer', 'crocs', 'hurricane', 'teva']`; the others pass.

- [ ] **Step 7: Implement the run changes.** In `run_products`, after `names = [brand.name, *brand.aliases]`, add:

```python
            rivals = [
                n
                for c in s.scalars(
                    select(m.Competitor).where(
                        m.Competitor.brand_id == brand_id
                    )
                )
                for n in (c.name, *c.aliases)
            ]
```

In the cache generator, replace the trailing condition with:

```python
                    # a row from an older query wording, or parsed before
                    # titles carried brand and model, is searched again
                    if row.query == search_query(row.keyword)
                    and all("brand" in t for t in row.titles)
```

In the `missing` loop, replace the call with:

```python
                ranking = titles_by_kw.get(p["keyword"], [])
                p["missing"] = missing(
                    p["title"],
                    [t["title"] for t in ranking],
                    names,
                    # ponytail: a generic word in a model ("Classic") is
                    # excluded for this keyword, and one in a competitor's
                    # name or alias for every keyword.
                    exclude=[
                        *rivals,
                        *(
                            v
                            for t in ranking
                            for v in (t.get("brand"), t.get("model"))
                            if v
                        ),
                    ],
                )
```

- [ ] **Step 8: Run the integration file and the unit files to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest tests/integration/test_products_run.py tests/unit/test_products.py tests/unit/test_recommend_copy.py -q`
Expected: all pass, including `test_no_transaction_is_open_during_model_calls` (the competitors load in the existing session). Then check R2: temporarily delete the `row.query == search_query(row.keyword) and` clause from the cache condition, run `test_a_search_under_the_old_query_is_redone`, see it fail, restore the line, and confirm `git diff` shows only the intended changes.

- [ ] **Step 9: Gate and commit**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100`

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests && git commit -m "fix(products): keep rival brands, models and competitors out of missing words"
```

---

### Task 5: Docs: both live checks, the extension, plan changes

**Files:**
- Modify: `docs/findings-slice20.md` (§1, §2, §3), `docs/README.md` (the three slice 20 rows' descriptions), the spec's `## Rulings` (only if the ledger records a new ruling), this plan's `## Changes made during execution`

- [ ] **Step 1: Findings §1.** Add the extension (brand and model per title, `_named_in`, `missing`'s `exclude`, competitors, the second cache condition, Ruling R2) to §1's description, update its cache-hit paragraph and its Tests list, change the "(this commit)" row to `509b2bf`, and add every commit from `git log --oneline 509b2bf..HEAD` plus a "(this commit)" row.
- [ ] **Step 2: Findings §2.** Replace the placeholder with the first live check. Sources: the ledger lines that start "Live check (user OK" and "Live check 1 per-product results", and spec §5's first paragraph. Record: job id `d73eaefa`, `cost_micros = 313,103`, about 1 min 51 s, spend $9.9377 → about $10.25; 8 searches with 5 titles each, 0 errors, 0 store names; LC-01 and LC-02 lost "Com"; the rival-name problem with the observed titles (LC-01/LC-02 "Teva Hurricane XLT", LC-03 "Big Nike Boots", LC-06 "Birkenstock"); "Gender Inclusive" (LC-08) and "Color" (LC-05) recorded as generic attribute words, which spec §5 keeps; LC-05's keyword "navy flip flops" with `review` and dropped `men`; the commentary title; the writes (job, 10 product rows, 8 `keyword_search` rows, `api_key.last_used_at`); 11 old-query rows untouched; worker and API stopped, 0 queued. End §2 with exactly "Second live check: not yet run. The controller runs it after this task; results are recorded here then."
- [ ] **Step 3: Findings §3.** Add every `minor (deferred)` and `parked` ledger line that the ledger does not mark fixed and that is not yet in §3 (fixed ones: the Task 1 R9 minor, fixed by R1; the Task 3 plan-changes minor, fixed by the final fix wave; both `parked` lines, fixed by the audit fix), plus spec §5's two ceilings, that competitor aliases are untested (the rival test's competitor has none), and the two new Out of scope items.
- [ ] **Step 4: README.** Update the three slice 20 rows so they mention the rival brand and model exclusion; the plan row says "Tasks 1–5", and the findings row says both live checks (the second not yet run).
- [ ] **Step 5: Plan changes.** Add the extension's deviations from Tasks 4–5 to this plan's changes section.
- [ ] **Step 6: Coverage check.** Adapt the script in `.superpowers/sdd/2026-09-29-slice20-product-titles-not-stores/task-3-report.md` (its Step 5 section) and run it over the ledger `.superpowers/sdd/2026-09-29-slice20-product-titles-not-stores/progress.md`: for every ruling ID (R1, R2), every `minor (deferred)` line and every `parked` line, print which of `docs/findings-slice20.md`, the spec and this plan's changes section contains its key phrase. A ledger item marked fixed counts as covered when the spec or plan records the fix. Report and fix misses.
- [ ] **Step 7: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add docs && git commit -m "docs: slice 20 extension findings and first live check"
```

### Extension self-review

- **Spec §5 coverage:**

  | Spec §5 part | Covered by |
  |---|---|
  | A: `TitleItem`, prompt sentence and JSON, `keep_present` with `_named_in` | Task 4 Step 3 |
  | B: `missing(exclude)`, the exclude list, competitors, second cache condition, ceiling comment | Task 4 Steps 3 and 7 |
  | C: unit tests | Task 4 Step 1 |
  | C: integration tests | Task 4 Step 5 |
  | Ruling R2 (old-query test seed) | Task 4 Step 5 item 4 and the Step 8 check |
  | Gates | The controller, after Task 5 |
  | Second live check | The controller, after Task 5 |
  | Findings §2 record | Task 5 Step 2 |

- **§5 C values, word for word:**
  - The two `keep_present` cases: "Teva" / "Hurricane XLT 2", then `""` / "Original Universal".
  - The no-keys case gives `""` / `""`.
  - The `missing` call with `exclude=["Teva", "Hurricane XLT 2", "Original Universal"]` gives `["kids"]`, and without it the result contains `teva`.
  - The prompt sentence.
  - The changed `test_keep_present_drops_titles_absent_from_the_text`.
  - The rival run gives `["summer"]`, and the comment carries `["summer", "crocs", "hurricane", "teva"]`.
  - A no-`brand` row is redone and its new titles carry `brand` and `model`.
  - A `[]` row is a hit.
  - The four named exact assertions gain the keys.
  - The reuse test seeds the keys.
  - The old-query test seeds the keys (R2).
- **Traced by hand:**
  - `_named_in("Hurricane XLT 2", TEVA_KIDS)`: the tokens are hurricane, xlt, 2, and all of them are in the title's tokens, so it is kept.
  - `_named_in("Nike", "Teva Original Universal Sandals")` gives `""`.
  - The `missing` values were confirmed by the spec reviewer with the real functions.
  - In the rival run:
    - `drop_stores` keeps all 4 titles (the own domain is `""`, amazon.in is cited, and no title contains "amazon").
    - `keep_present` finds each title in `answer`.
    - Brand and model survive `_named_in`.
    - The competitor (changed by R5: name "Deckers", alias "Crocs") is `suggested`, which exercises the deliberate inclusion, and "crocs" is excluded only through the alias.
  - The `[]` row: `all(...)` over `[]` is True, so it is a hit. Because it has no titles, `missing` returns `[]`.
- **Fixtures vs banned words:** the fixtures use Teva, Hurricane, XLT, Original Universal, Crocs, Classic, Summer, Slides, Picks, Old Sandals. None is a banned word. The prompt sentence has none either.
- **Types:**
  - `_named_in` returns `str`, and `keep_present` still returns `list[dict[str, str]]`.
  - `exclude` is `Sequence[str]`. The generator only yields truthy values, and `t.get` on `dict[str, Any]` is `Any`. `rivals` is `list[str]`.
- **Every place this plan departs from spec §5's text:**
  1. The spec names no helper. The plan adds `_named_in` for the token check.
  2. The tests `test_a_row_parsed_without_brand_is_redone`, `test_a_row_with_no_titles_is_a_hit` and `test_rival_brands_models_and_competitors_are_not_missing_words`, and the helper `_fresh_row`, are the plan's names.
  3. The `keep_present` unit tests put each title inside a longer answer string. The spec says only "with the title in `text`".
  4. The rival test's competitor is `status="suggested"`, with name "Deckers" and alias "Crocs" (changed by R5; spec §5 C now says the same).
  5. The ceiling comment sits at the `missing` call in `run_products`, not in `missing`'s docstring. The docstring names `exclude`'s contents.
  6. `test_a_row_with_no_titles_is_a_hit` is never seen failing: it passes before and after Step 7. It pins spec §5 B's "a row with no titles counts as a hit", so an implementation that also requires non-empty titles would fail it.
  7. Ruling R2: `test_a_search_under_the_old_query_is_redone`'s seed gains `brand` and `model` keys (Step 5 item 4). Spec §5 C now lists it.
  8. Task 4 Step 9 runs the backend gate inside the task; the controller also runs both gates after Task 5, as spec §5 C says.

## Changes made during execution

- Task 1 went as written (commit cad40aa).
- Task 2 went as written (commit a63f707), with two differences:
  - ruff wrapped the `missing(...)` call in `test_missing_never_suggests_com` across three lines, which Task 2 allows. The `Kids Foot Locker` line was not wrapped.
  - Step 6's check without the filter replaced `drop_stores(` in `run_products` with an identity `(lambda x, _d: x)(` rather than with its first argument, and restored the file from a backup copy. The effect is the same: the test failed with "Zappos.com" stored, and the restored diff has only the intended call.
- Task 3 (commit 19fa5f8): the spec's Rulings section was "None.", because the ledger recorded no rulings at that point (the preflight scan was clean). Two process differences:
  - `docs/findings-slice20.md` and the task report were written with a shell heredoc, because the Write tool refused to create `.md` files from a subagent.
  - The Step 5 coverage grep excluded `R9`, because the ledger's R9 is slice 18's ruling.
- Ruling R1 (final whole-branch review): `test_an_error_search_is_not_reused` seeds its error row with `query=products.search_query("kids sandals")` instead of `query="q"`, so it tests slice 18's R9 on its own again. This overrides the table row's original "stays" (the row now states R1's seed); the spec's §3 and `## Rulings` are updated. Checked by deleting `m.KeywordSearch.error.is_(None)` in `products.py`: the test failed, and passed again once the line was restored. Commit: 9ecbb33, "test: slice 20 final review: the R9 test seeds the new query (R1)" (listed in findings-slice20 §1).
- **Slice 20 audit (docs only).** The spec's line on section approvals now says Section 1 was approved without its own text in chat; spec §3's reason for the rows left unchanged is now only that `run_products` never reads them; this plan's changes-table row for `test_an_error_search_is_not_reused` states R1's seed instead of old and new state together.
- Task 4 went as written (commit 42300cc), with three differences (from task-4-report.md):
  - ruff wrapped one line over 80 columns in `tests/unit/test_products.py` (the `missing(...)` call with `exclude=`), which Task 4 allows.
  - Step 6's failure for `test_a_row_parsed_without_brand_is_redone` read `assert (0 == 1)` on `len(engine.prompts)`, rather than the plan's `engine.prompts == []`. Same meaning: no search was made, so the row was still a hit.
  - Step 8's R2 check backed up `products.py` to the scratchpad, deleted the clause, saw the test fail, and restored the file from the backup rather than re-typing the line; the re-run passed and `git diff --stat` showed only the 3 intended files.
- Task 5 (docs), with two differences:
  - Ruling R3: findings §2 records every product's missing words and suggested title from the ledger line "Live check 1 per-product results" (LC-09's "Big Nike Boots" included), not only the examples Step 2 names. The spec's `## Rulings` gains R3, because the ledger records it as a ruling.
  - Step 6's coverage check also covers R3.
- Ruling R4 (final whole-branch review of the extension): `_named_in` returns `""` when the value's token set equals the title's, so a brand or model that is the whole title excludes nothing. Test-first: the new unit test `test_keep_present_model_named_in_title_edge_cases` failed on its R4 case before the guard and passed after. Spec §5 A, §5 C and `## Rulings` are updated. Commit: 1079f38.
- Ruling R5 (final whole-branch review of the extension): `test_rival_brands_models_and_competitors_are_not_missing_words` seeds its competitor as `name="Deckers", aliases=["Crocs"], status="suggested"`. Checked by changing `for n in (c.name, *c.aliases)` to `for n in (c.name,)` in `products.py`: the test failed with "crocs" in the missing words, and passed again once the file was restored from a backup. Spec §5 C and `## Rulings` are updated. Commit: 1079f38.
- Ruling R6 (second live check's pre-check): the competitor-alias ceiling is accepted for the second live check and before merge. The dev brand's competitor Campus has alias "Campus Shoes", so "shoe" and "shoes" are excluded for every keyword of that brand; excluding only active competitors would not help, because Campus is active. Recorded in findings §3 and the spec's `## Rulings`. No code change.
- **Second live check docs (docs only).** Findings §2 records the second live check (job `89facf99`) and the user's decision to merge and take suggestion quality to slice 21; §3 gains R6's ceiling, R4's limit and the second check's three problems as slice 21 scope; the spec's R3 gains a "Why:" part and R6 is added; the three Task 4 lines above that named the competitor "Crocs" are marked "(changed by R5)". Task 5's minor that Task 4's difference 3 ("rather than re-typing the line") is barely a deviation is left as written.
