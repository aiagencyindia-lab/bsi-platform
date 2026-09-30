# Slice 24 Keyword Cache Key Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse one cached grounded search for every spelling of a keyword phrase across runs, and give the product the cached spelling.

**Architecture:**
- `_current(row)` holds the cache-validity test (current query wording, current parse version) that the per-batch lookup already applies inline.
- At the start of each run, `run_products` seeds its run-wide `key_map` from the brand's fresh valid `keyword_search` rows, newest first. The existing spelling merge then makes every product adopt the cached spelling, so the exact-string lookup hits and no duplicate search runs.
- All code is in `packages/core/bsi_core/products.py`. No migration, schema, API, prompt or web change.

**Tech Stack:** Python 3.13, SQLAlchemy 2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-slice24-keyword-cache-key-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice24-keyword-cache-key`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB, the network or the worker loop. Never call a model.
- **Shared test DB:** tests use `bsi_test`, which is shared. Run `pgrep -fl pytest` first, and never run two suites at once. Run the full suite only once, in the gate step; write its pytest output to a file in the workspace directory and read the file rather than running it again.
- **Tool refusals:** if a tool refuses, stop and report BLOCKED. Do not work around it.
- **Lint and types:** ruff line length is 80, and RUF001 rejects a literal curly apostrophe. `mypy --strict` runs over `packages/core/bsi_core`.
- **The seed's loop variable is `cached`, not `row`:** `run_products` later declares `row: dict[str, Any]` in the same function scope, and `mypy --strict` rejects a second `row` of another type.
- **Unchanged:** the `keyword_search` table and `uq_keyword_search_brand_keyword`, the per-batch lookup's SQL, the insert and its upsert, `keyword_key`, `search_query`, `TITLES_PARSE`, `SEARCH_TTL_DAYS`, `SEARCH_MICROS`, `KEYWORD_CAP`, every prompt, the schema, the API and the web app.
- **Banned words:** copy (comments, fixtures) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat` or `certain`.
- **Backend gate:** `uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100`
- **Commit trailer:** the `Co-Authored-By` line from the latest session reminder.

## Changes to existing tests that the spec implies

| Test | Change | Task |
|---|---|---|
| `_fresh_row` (integration helper, line 408) | gains `days=1`, the row's age | 1 |

The 5 existing cache tests (`test_a_fresh_search_is_reused_and_a_stale_one_redone`, `test_a_search_under_the_old_query_is_redone`, `test_a_row_parsed_before_parse_2_is_redone`, `test_a_row_with_no_titles_is_a_hit`, `test_plural_variants_share_one_search`) are not edited and keep their values.

## File map

| File | Responsibility |
|---|---|
| `packages/core/bsi_core/products.py` | `_current`, the lookup using it, the seeded `key_map` in `run_products` |
| `tests/integration/test_products_run.py` | `_fresh_row(days=)`, 3 new run tests |
| docs | `docs/findings-slice24.md`, `docs/README.md`, the spec's Rulings, this plan's changes section |

---

### Task 1: `_current` and the seeded `key_map`

**Files:**
- Modify: `packages/core/bsi_core/products.py`: after `search_query` (line 870-876); the per-batch lookup's generator expression (lines 1078-1081); the `key_map` lines in `run_products` (lines 990-992).
- Test: `tests/integration/test_products_run.py`: `_fresh_row` (line 408), and 3 new tests after `test_a_row_with_no_titles_is_a_hit` (line 444-451).

**Interfaces:**
- Consumes (unchanged): `search_query(keyword) -> str`, `TITLES_PARSE`, `keyword_key(keyword) -> str`, `m.KeywordSearch`, `tenant_session`, `fresh_after` (defined before the `try` in `run_products`).
- Produces: `_current(row: m.KeywordSearch) -> bool`.

- [ ] **Step 1: `_fresh_row` gains an age.** Replace the helper with:

```python
def _fresh_row(owner, org, bid, titles, days=1):
    with owner() as s, s.begin():
        s.add(
            m.KeywordSearch(
                org_id=org.id,
                brand_id=bid,
                keyword="kids sandals",
                query=products.search_query("kids sandals"),
                titles=titles,
                searched_at=datetime.now(UTC) - timedelta(days=days),
            )
        )
```

- [ ] **Step 2: Write the failing tests.** Insert right after `test_a_row_with_no_titles_is_a_hit`:

```python
CACHED_TITLE = {
    "title": "Kids Sandals for Boys Summer",
    "domain": "amazon.in",
    "brand": "",
    "model": "",
    "parse": 2,
}


def test_a_cached_spelling_is_adopted_and_its_search_reused(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    _fresh_row(owner, org, bid, [CACHED_TITLE])
    engine = FakeEngine()
    # "kid sandal" and "kids sandals" share the key "kid sandal".
    gen = _generator(keywords=["kid sandal"])
    _, rows, searches = _run(owner, org, bid, gen, engine)
    assert rows[0].keyword == "kids sandals"
    assert rows[0].keywords == ["kids sandals"]
    assert engine.prompts == [] and len(searches) == 1


def test_a_stale_row_spelling_is_not_adopted(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    _fresh_row(owner, org, bid, [CACHED_TITLE], days=8)
    engine = FakeEngine()
    gen = _generator(keywords=["kid sandal"])
    _, rows, searches = _run(owner, org, bid, gen, engine)
    assert rows[0].keyword == "kid sandal"
    assert rows[0].keywords == ["kid sandal"]
    assert engine.prompts == [(products.search_query("kid sandal"), "IN", "en")]
    assert len(searches) == 2


def test_a_row_the_lookup_rejects_is_not_seeded(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    _fresh_row(owner, org, bid, [{**CACHED_TITLE, "parse": 1}])
    engine = FakeEngine()
    gen = _generator(keywords=["kid sandal"])
    _, rows, searches = _run(owner, org, bid, gen, engine)
    assert rows[0].keyword == "kid sandal"
    assert engine.prompts == [(products.search_query("kid sandal"), "IN", "en")]
    assert len(searches) == 2
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/integration/test_products_run.py -k "cached_spelling or stale_row_spelling or lookup_rejects"`

Expected: 1 failed, 2 passed. `test_a_cached_spelling_is_adopted_and_its_search_reused` fails with `AssertionError: assert 'kid sandal' == 'kids sandals'`: today nothing adopts the cached spelling, so "kid sandal" is searched. The other two pass already, because today's behaviour is what they assert; they pin that the seeding does not adopt a stale or rejected row.

- [ ] **Step 4: Add `_current`.** Insert right after `search_query` (before `titles_prompt`):

```python
def _current(row: m.KeywordSearch) -> bool:
    """A cache row the run can use: the current query wording and every
    title parsed by the current titles_prompt (TITLES_PARSE). Age and
    errors are checked in SQL."""
    return row.query == search_query(row.keyword) and all(
        t.get("parse") == TITLES_PARSE for t in row.titles
    )
```

- [ ] **Step 5: The lookup uses it.** In `run_products`' per-batch lookup, replace:

```python
                    # a row from an older query wording, or parsed by an
                    # older titles_prompt (TITLES_PARSE), is searched again
                    if row.query == search_query(row.keyword)
                    and all(t.get("parse") == TITLES_PARSE for t in row.titles)
```

with:

```python
                    # a row from an older query wording, or parsed by an
                    # older titles_prompt (TITLES_PARSE), is searched again
                    if _current(row)
```

- [ ] **Step 6: Seed `key_map`.** In `run_products`, replace:

```python
        # One keyword string per key for the whole run, so plural and
        # possessive variants share one search and one cache row.
        key_map: dict[str, str] = {}
```

with:

```python
        # One keyword string per key for the whole run, so plural and
        # possessive variants share one search and one cache row. Seeded
        # from the brand's fresh cache rows (newest first), so a phrase
        # keeps its cached spelling across runs and its search is reused.
        # ponytail: spellings that do not share a key ("man slippers")
        # are not merged; rows under an old spelling stay once stale;
        # loads every fresh valid row of the brand (every distinct
        # keyword searched in SEARCH_TTL_DAYS days); a cached spelling
        # with a brand token can be adopted, since drop_brand_terms runs
        # on the voted spelling first.
        key_map: dict[str, str] = {}
        with tenant_session(org_id) as s:
            for cached in s.scalars(
                select(m.KeywordSearch)
                .where(
                    m.KeywordSearch.brand_id == brand_id,
                    m.KeywordSearch.searched_at > fresh_after,
                    m.KeywordSearch.error.is_(None),
                )
                .order_by(
                    m.KeywordSearch.searched_at.desc(),
                    m.KeywordSearch.keyword,
                )
            ):
                if _current(cached):
                    key_map.setdefault(
                        keyword_key(cached.keyword), cached.keyword
                    )
```

This is a second, short tenant session right after the run-start one closes; no model call runs between them.

- [ ] **Step 7: Run the product-run tests to see them pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/integration/test_products_run.py`

Expected: 28 passed (the 25 existing tests and the 3 new ones).

- [ ] **Step 8: Check the seed is what makes the test pass.**
  1. Copy the file outside the repo: `cd /Users/vineet/Downloads/ADK/bsi-platform && cp packages/core/bsi_core/products.py /private/tmp/claude-501/-Users-vineet-Downloads-ADK-brand-search-optimization/57875675-70cf-46e9-a368-f0f1091f1ba0/scratchpad/slice24-products-backup.py`.
  2. In the seed loop, change `if _current(cached):` to `if False:`.
  3. Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && pgrep -fl pytest; uv run pytest -q tests/integration/test_products_run.py -k cached_spelling`. Expected: 1 failed, `assert 'kid sandal' == 'kids sandals'`.
  4. Restore the file from that copy (`cd /Users/vineet/Downloads/ADK/bsi-platform && cp /private/tmp/claude-501/-Users-vineet-Downloads-ADK-brand-search-optimization/57875675-70cf-46e9-a368-f0f1091f1ba0/scratchpad/slice24-products-backup.py packages/core/bsi_core/products.py`). Do not re-type the line.
  5. Run the same test again. Expected: 1 passed.
  6. Run `cd /Users/vineet/Downloads/ADK/bsi-platform && git diff --stat`. Expected: only `packages/core/bsi_core/products.py` and `tests/integration/test_products_run.py`.

- [ ] **Step 9: Run the backend gate** (Global Constraints). Expected: ruff and mypy clean, all tests pass, metrics coverage 100%. Record the pass count and the names of any warnings.

- [ ] **Step 10: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/products.py tests/integration/test_products_run.py && git commit -m "feat(products): reuse one cached search per keyword phrase across runs" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Docs: findings, index, rulings, plan changes

**Files:**
- Create: `docs/findings-slice24.md`. The Write tool refuses to let a subagent create a new `.md` file. Before dispatching this task, the controller asks the user, then creates a one-line stub (`# Slice 24 findings: one cached search per keyword phrase across runs`) for the implementer to fill with Edit.
- Modify: `docs/README.md` (three rows after the slice 23 rows), the spec's `## Rulings`, and this plan's `## Changes made during execution`.

- [ ] **Step 1: Findings.** Fill `docs/findings-slice24.md` in the style of `docs/findings-slice23.md`, with three sections:
  - `## 1. What was built`: `_current`, the lookup using it, the seeded `key_map` (what is loaded, the order, what follows), the tests, the gate result as Task 1 recorded it, and a commit table from `git log --oneline main..HEAD` with a "(this commit)" row.
  - `## 2. Live check on dev`: exactly "Not yet run. The controller runs it after the user approves; results are recorded here then."
  - `## 3. Deferred and untested`: every line tagged `minor (deferred…)` and every `parked` line in the ledger not marked fixed; the accepted gap that no test pins the seed's `error.is_(None)` filter on its own (an error row with an empty title list passes `_current`); two seed cases no test covers, which the spec reviewer noted and the spec does not list (newest-wins between two valid rows, and adoption of a non-first keyword); the spec's known ceilings (§1); and its Out of scope list.
- [ ] **Step 2: README rows** for the spec, the plan and the findings, in the slice 23 rows' format:
  - spec: "Design spec: one cached search per keyword phrase across runs — the run's spelling merge is seeded from the brand's fresh cache rows, so a product adopts the cached spelling and its search is reused; no migration."
  - plan: "Implementation plan, Tasks 1–2, with the changes made during execution."
  - findings: "Results: what was built, the live check on dev (not yet run), and what is deferred or untested."
- [ ] **Step 3: Rulings.** Copy each ledger ruling into the spec's `## Rulings` in the slice 23 format (Decided / Found by / Why / Cost if wrong). If there are none, replace "None yet. Rulings made during execution are added here with their R-number." with "None."
- [ ] **Step 4: Plan changes.** List every deviation from Tasks 1–2 in this plan's changes section.
- [ ] **Step 5: Coverage check.** Run a scripted grep over the ledger for every ruling, every line tagged `minor (deferred…)` and every `parked` line. Print which of the findings, the spec or this plan's changes section covers each. Report and fix misses.
- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add docs && git commit -m "docs: slice 24 findings, index and rulings" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review

- **Spec coverage:**

  | Spec part | Covered by |
  |---|---|
  | §1 `_current`, and the lookup using it | Task 1 Steps 4–5 |
  | §1 the seed query (fresh, no error, newest first, keyword tie-break) and `key_map.setdefault` | Task 1 Step 6 |
  | §1 the `# ponytail:` comment and its ceilings | Task 1 Step 6 |
  | §1 unchanged items | Global Constraints |
  | §2 `_fresh_row(days=)` | Task 1 Step 1 |
  | §2 the three integration tests | Task 1 Step 2 |
  | §2 the 5 existing cache tests unchanged | "Changes to existing tests" |
  | §2 copy check | Global Constraints |
  | §3 dev re-check | the controller, after Task 2, with the user's OK |
  | Gates | Task 1 and the controller |

- **§2 values, word for word against the spec:**
  - The cached title dict, "kid sandal" as the generator's keywords, `keyword == "kids sandals"`, `keywords == ["kids sandals"]`, `engine.prompts == []`, `len(searches) == 1`.
  - The stale row at `days=8`: `keyword == "kid sandal"`, `keywords == ["kid sandal"]`, one prompt for `search_query("kid sandal")`, `len(searches) == 2`.
  - The parse-1 row: `keyword == "kid sandal"`, one prompt for `search_query("kid sandal")`, `len(searches) == 2`.
- **Traced by hand** (the spec reviewer traced the same paths):
  - Fresh case: the seed maps "kid sandal" → "kids sandals"; `choose_keywords([["kid sandal"]] * 3, ...)` gives `["kid sandal"]`; `key_map.setdefault` returns "kids sandals"; the lookup hits the 1-day parse-2 row with the current query; no search.
  - 8-day case: the seed loads nothing (the SQL age filter); "kid sandal" is searched and inserted beside the "kids sandals" row.
  - Parse-1 case: the row is loaded but `_current` is False, so nothing is seeded; same as the 8-day case from there.
  - Step 3's expected failure: today `key_map` starts empty, so the product keeps "kid sandal" and the first assertion fails with `'kid sandal' == 'kids sandals'`. The other two tests assert today's behaviour and pass.
  - Step 8's `if False:` check: the seed loads the row but never adds it, so the first test fails as in Step 3.
- **Counts:** the integration file collects 25 tests today (`pytest --collect-only`), so 28 after this task.
- **Checked by running code.** The controller built scratch copies of `products.py` and the integration test file from this plan's code blocks, outside the repo, and ran them (the test DB is the shared `bsi_test`; `pgrep` showed no other run):
  - `ruff check` and `ruff format --diff` clean on the patched `products.py`; the patched test file formats without change; `mypy --strict` on the patched file: no issues.
  - The patched integration file against the patched module: 28 passed.
  - Step 3 on today's module: 1 failed (`AssertionError: assert 'kid sandal' == 'kids sandals'`), 2 passed.
  - Step 8 with `if False:`: the same 1 failed, 2 passed.
- **Fixtures vs banned words:** "Kids Sandals for Boys Summer", "kid sandal", "kids sandals", "amazon.in". None is a banned word.
- **Types:**
  - `_current(row: m.KeywordSearch) -> bool`: `str == str` and `all(...)` are `bool`.
  - `row.titles` is `list[dict[str, Any]]`, so `t.get("parse")` type-checks.
  - The seed's loop variable is `cached`, so no clash with the later `row: dict[str, Any]`.
  - `s.scalars(select(m.KeywordSearch)...)` yields `m.KeywordSearch`.
  - `key_map.setdefault(str, str)` returns `str`.
- **Line lengths:** every code line in this plan is at most 80 characters, checked; the `setdefault(...)` call is split as the formatter would split it.
- **Every place this plan departs from the spec's text:**
  1. The spec names no test. The plan names the three: `test_a_cached_spelling_is_adopted_and_its_search_reused`, `test_a_stale_row_spelling_is_not_adopted`, `test_a_row_the_lookup_rejects_is_not_seeded`.
  2. The plan adds a module-level constant `CACHED_TITLE` for the title dict the spec writes inline.
  3. The spec allows the seed inside the existing run-start session or a second one; the plan uses a second, short session right after it.
  4. Task 1 Step 8 adds a disable-and-see-it-fail check that the spec does not ask for.
  5. Two of the three new tests pass before the implementation (Step 3), because they assert today's behaviour; the spec does not say which tests are seen failing.
  6. Task 1 runs the backend gate; the controller also runs both gates.
  7. Task 2's findings §3 lists the accepted test gap (the seed's error filter) and the two untested seed cases, which the spec does not list.
  8. Task 2's findings file needs the user's OK and a controller-made stub, because of the Write tool's refusal for subagents.
  9. The spec's §1 says the lookup's inline test "becomes `if _current(row)`"; the plan keeps the two comment lines above it as they are.
  10. The first new test carries a comment (`# "kid sandal" and "kids sandals" share the key "kid sandal".`) and builds `engine` before `gen`; the spec has neither.

## Changes made during execution

- Task 1 went as written (commit e077bea), with one difference (from the ledger): "Step 8.3's `-k cached_spelling` test was run twice on the same code (the first run's `tail` cut off the assertion line; the second showed `assert 'kid sandal' == 'kids sandals'`). Otherwise as the brief; ruff rewrapped nothing."
- Task 2: findings §3 also has three items Step 1 does not name: "Parked: none" and an "Untested" item (the tests use fixed model output), both in the style of findings-slice23 §4, and "Rulings: none". Findings §1 also records the controller's own run of the product-run file at e077bea (28 passed), from the ledger.
- No rulings were made during Tasks 1–2; the spec's `## Rulings` says "None."
- Task 2 fix round 1 (commit "docs: slice 24 findings wording fixes"), after the Task 2 review (approved, 4 Minor; 3 fixed in this round): the findings' ceilings header says the `# ponytail:` comment holds them "in shorter wording"; this section no longer lists the controller-made stub, which plan departure 8 provides for; "Rulings: none" is no longer attributed to slice 23's style; the findings commit table names 0530ecc and has a new "(this commit)" row.
- Final whole-branch review (approved, 0 Critical, 0 Important, 3 Minor, all deferred). Commit "docs: slice 24 findings: final-review minors" (approved by the user): findings §3 lists the 3 final-review minors as the ledger records them, adds a note after the quoted Task 1 minor that its range is test_products_run.py:454-503 (the ledger line stays as recorded), and the findings commit table names 20c907b and has a new "(this commit)" row.
- Note (final review, process note, not a finding; ledger text): "implementers and reviewers ran with `model: opus` passed explicitly because the session was on Fable 5.1; the memory rule says "omit Agent model param", written when the session ran on Opus. The intent (Opus 5.5 only) was met; to be confirmed with the user."
