# Slice 28 Seed Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three integration tests pin the slice 24 seed's error filter, its newest-first order, and its use for every keyword, not only the first.

**Architecture:** Tests only. `_fresh_row` in tests/integration/test_products_run.py gains `keyword=` and `error=` parameters with defaults that keep today's rows; three tests follow `test_a_row_the_lookup_rejects_is_not_seeded`. No production code changes. Each test is shown red against a matching mutation of the seed on a scratch copy, and green against main's code.

**Tech Stack:** Python 3.13, pytest, SQLAlchemy 2 (the shared `bsi_test` database).

**Spec:** `docs/superpowers/specs/2026-10-01-slice28-seed-tests-design.md`

## Global Constraints

- **Repo root:** `/Users/vineet/Downloads/ADK/bsi-platform`. The shell's cwd resets after every command, so start every command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&`.
- **Branch:** `slice28-seed-tests`. Never check out, switch, reset or stash.
- **Off limits:** do NOT edit `tests/conftest.py` or create databases. Never touch the dev DB, the network or the worker loop. Never call a model.
- **Unchanged:** `packages/core/bsi_core/products.py` (including the `# ponytail:` comment above `key_map`), every other production file, and `test_an_error_search_is_not_reused`.
- **Shared test DB:** tests use `bsi_test`, which is shared. Run `pgrep -fl pytest` first, and never run two suites at once. Run the full suite only once, in the gate step, redirecting the whole gate chain's output to a file in the plan's workspace directory; read the file rather than running it again.
- **Tool refusals:** if a tool refuses, stop and report BLOCKED. Do not work around it.
- **Writing files:** never use a shell heredoc or zsh `echo` to write files; use the Edit or Write tools.
- **Lint:** ruff line length is 80.
- **Banned words:** copy (test names, fixtures, comments, docs) never contains `guarantee`, `will rank`, `will appear`, `will be recommended`, `ensure`, `boost`, `#1`, `top spot`, `dominat` or `certain` (`FORBIDDEN` in tests/unit/test_recommend_copy.py).
- **Backend gate:** `{ uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100; } > <workspace>/gate-task1.txt 2>&1`
- **Commit trailer:** the `Co-Authored-By` line from the latest session reminder.

## File map

| File | Responsibility |
|---|---|
| `tests/integration/test_products_run.py` | `_fresh_row`'s two new parameters and the three new tests |
| `<workspace>/red/` (gitignored, not committed) | the scratch test file and the three mutated copies of `bsi_core` for the red checks |
| docs | `docs/findings-slice28.md`, dated updates in `docs/findings-slice24.md` and `docs/findings-slice27.md`, `docs/README.md`, the spec's Rulings, this plan's changes section |

---

### Task 1: The helper and the three seed tests

**Files:**
- Modify: `tests/integration/test_products_run.py` (`_fresh_row` at about line 413; insert after `test_a_row_the_lookup_rejects_is_not_seeded`, before `test_the_rewrite_cannot_add_an_invented_word` at about line 511)
- Scratch (not committed): `<workspace>/red/t/test_seed_red.py`, `<workspace>/red/m1/bsi_core/`, `<workspace>/red/m2/bsi_core/`, `<workspace>/red/m3/bsi_core/`

**Interfaces:**
- Consumes: `_seed(owner, org, bid, n)`, `_generator(keywords=...)`, `_run(owner, org, bid, generator, engine)` returning `(job, rows, searches)`, `FakeEngine` (its `.prompts` list of `(query, country, language)`), `CACHED_TITLE`, `products.search_query(keyword)`; fixtures `owner`, `make_org`, `make_brand` from tests/conftest.py.
- Produces: `_fresh_row(owner, org, bid, titles, days=1, keyword="kids sandals", error=None)`.

- [ ] **Step 1: Widen `_fresh_row`.** In tests/integration/test_products_run.py, replace exactly this text (found once):

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

with:

```python
def _fresh_row(
    owner, org, bid, titles, days=1, keyword="kids sandals", error=None
):
    with owner() as s, s.begin():
        s.add(
            m.KeywordSearch(
                org_id=org.id,
                brand_id=bid,
                keyword=keyword,
                query=products.search_query(keyword),
                titles=titles,
                error=error,
                searched_at=datetime.now(UTC) - timedelta(days=days),
            )
        )
```

- [ ] **Step 2: Add the three tests.** Replace exactly this text (found once; it is the end of `test_a_row_the_lookup_rejects_is_not_seeded` and the start of the next test):

```python
    assert len(searches) == 2


def test_the_rewrite_cannot_add_an_invented_word(owner, make_org, make_brand):
```

with:

```python
    assert len(searches) == 2


def test_an_error_row_is_not_seeded(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    _fresh_row(owner, org, bid, [], error="429 quota")
    engine = FakeEngine()
    gen = _generator(keywords=["kid sandal"])
    _, rows, searches = _run(owner, org, bid, gen, engine)
    assert rows[0].keyword == "kid sandal"
    assert engine.prompts == [(products.search_query("kid sandal"), "IN", "en")]
    assert len(searches) == 2


def test_the_newest_cached_spelling_wins(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    _fresh_row(owner, org, bid, [CACHED_TITLE])
    _fresh_row(owner, org, bid, [CACHED_TITLE], days=2, keyword="kid sandals")
    engine = FakeEngine()
    gen = _generator(keywords=["kid sandal"])
    _, rows, searches = _run(owner, org, bid, gen, engine)
    assert rows[0].keyword == "kids sandals"
    assert engine.prompts == [] and len(searches) == 2


def test_a_non_first_keyword_adopts_a_cached_spelling(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _seed(owner, org, bid, 1)
    _fresh_row(owner, org, bid, [CACHED_TITLE])
    engine = FakeEngine()
    gen = _generator(keywords=["boys sandals", "kid sandal"])
    _, rows, searches = _run(owner, org, bid, gen, engine)
    assert rows[0].keywords == ["boys sandals", "kids sandals"]
    assert rows[0].keyword == "boys sandals"
    assert engine.prompts == [
        (products.search_query("boys sandals"), "IN", "en")
    ]
    assert len(searches) == 2


def test_the_rewrite_cannot_add_an_invented_word(owner, make_org, make_brand):
```

- [ ] **Step 3: Green.** `pgrep -fl pytest` (expect nothing), then run:

`cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_products_run.py`

Expected: `33 passed` (the file's 30 tests and the 3 new ones). If the count or any result differs, stop and report it; do not change a test's expected values.

- [ ] **Step 4: Build the red-check copies.** In `<workspace>/red/`: copy `tests/integration/test_products_run.py` to `<workspace>/red/t/test_seed_red.py` (a folder with no `bsi_core` in it), and copy `packages/core/bsi_core` to each of `<workspace>/red/m1/bsi_core`, `<workspace>/red/m2/bsi_core` and `<workspace>/red/m3/bsi_core` (`mkdir -p` and `cp -R` are fine; they copy, they do not write text). Then make one edit in each copy's `products.py` with the Edit tool (each old string is found once in the copy). The m1 code blocks sit inside a list, so drop their 4-space list indent: in the file, the `m.KeywordSearch` lines start at column 21 (20 spaces) and `)` and `.order_by(` at 16 spaces. The m2 and m3 strings start with 20 spaces:
  - m1 (the seed's error filter; the per-batch lookup keeps its own): replace

    ```python
                        m.KeywordSearch.searched_at > fresh_after,
                        m.KeywordSearch.error.is_(None),
                    )
                    .order_by(
    ```

    with

    ```python
                        m.KeywordSearch.searched_at > fresh_after,
                    )
                    .order_by(
    ```
  - m2 (the order): replace `                    m.KeywordSearch.searched_at.desc(),` with `                    m.KeywordSearch.searched_at.asc(),`
  - m3 (the first keyword only): replace `                    key_map.setdefault(keyword_key(k), k) for k in fitted` with `                    key_map.setdefault(keyword_key(k), k) if n == 0 else k` followed by a new line `                    for n, k in enumerate(fitted)`

- [ ] **Step 5: Red.** For each of m1, m2, m3, run from the repo root (one at a time):

`cd /Users/vineet/Downloads/ADK/bsi-platform && PYTHONPATH=<workspace>/red/m1:. uv run pytest -q -p no:cacheprovider -p tests.conftest --rootdir . <workspace>/red/t/test_seed_red.py -k "error_row_is_not_seeded or newest_cached_spelling or non_first_keyword"`

(with `m2`, then `m3`, in place of `m1`). Expected:
  - m1: `1 failed, 2 passed, 30 deselected`; the failure is `test_an_error_row_is_not_seeded` (`'kids sandals' == 'kid sandal'`).
  - m2: `1 failed, 2 passed, 30 deselected`; the failure is `test_the_newest_cached_spelling_wins` (`'kid sandals' == 'kids sandals'`).
  - m3: `1 failed, 2 passed, 30 deselected`; the failure is `test_a_non_first_keyword_adopts_a_cached_spelling` (`['boys sandals', 'kid sandal']`).

  Then the same command with `PYTHONPATH=.` (main's code): `3 passed, 30 deselected`. If any result differs, stop and report it; do not change a test's expected values.

- [ ] **Step 6: Gate.** `pgrep -fl pytest` (expect nothing), then the Backend gate from Global Constraints, once, with `; echo "gate exit $?"` appended after the redirect (it prints to the terminal, not to a file), and record the printed exit code (the output file holds none). Expected: `gate exit 0`, `1552 passed, 2 deselected`, metrics coverage 100%, and the 2 known third-party warnings. Grep the diff (`git diff`) for the banned words: no match.

- [ ] **Step 7: Commit.** `git add tests/integration/test_products_run.py && git commit -m "test: pin the slice 24 seed's error filter, order and non-first keywords" -m "<trailer>"`. The `<workspace>/red/` copies are not committed (the workspace is gitignored).

---

### Task 2: Docs

**Files:**
- Create: `docs/findings-slice28.md` (the controller creates a one-line stub first; the subagent fills it with Edit).
- Modify: `docs/findings-slice24.md` §3, `docs/findings-slice27.md` §3, `docs/README.md`, the spec's `## Rulings`, this plan's `## Changes made during execution`.

- [ ] **Step 1: Findings.** Fill `docs/findings-slice28.md` in the style of `docs/findings-slice27.md`, with sections:
  - `## 1. What was built`: the `_fresh_row` parameters, the three tests and what each pins; the Step 3 GREEN count, the Step 5 RED and GREEN results and the Step 6 gate result and exit code as the Task 1 report records them; and a commit table from `git log --oneline --reverse main..HEAD` with a "(this commit)" row.
  - `## 2. Live check on dev`: exactly "None: the slice adds tests only and changes no behaviour, so there is no spend and no dev write (spec §2)."
  - `## 3. Deferred and untested`: every line tagged `minor (deferred…)` and every `parked` line in the ledger, quoted as recorded ("Parked: none" if none); the spec's rulings R1–R5 quoted in full, plus any the ledger records; the spec's Out of scope list; the items under "Carried forward from docs/findings-slice26.md §4 (still open):" in docs/findings-slice27.md §3 that are still open; and "Untested: the seed's secondary sort key (`keyword`) for two rows with the same `searched_at` (R1)."
- [ ] **Step 2: Dated updates, originals kept.** Add a sub-bullet starting "Update 2026-10-01 (slice 28):" under each of:
  - docs/findings-slice24.md §3, the Task 1 minor that begins "Task 1: the spec §1 order rule": `.desc()` is now pinned by `test_the_newest_cached_spelling_wins`; the secondary sort key is still unpinned (docs/superpowers/specs/2026-10-01-slice28-seed-tests-design.md, R1).
  - docs/findings-slice24.md §3, the Untested bullet "An accepted gap: no test pins the seed's `error.is_(None)` filter on its own": pinned by `test_an_error_row_is_not_seeded`.
  - docs/findings-slice24.md §3, the Untested sub-bullet "Newest-wins between two valid rows that share a key": pinned by `test_the_newest_cached_spelling_wins` (its own update).
  - docs/findings-slice24.md §3, the Untested sub-bullet "Adoption of a non-first keyword": pinned by `test_a_non_first_keyword_adopts_a_cached_spelling` (its own update).
  - docs/findings-slice27.md §3, the carried-forward bullet "The slice 24 seed's untested cases": all three pinned by slice 28 (docs/findings-slice28.md); the secondary sort key stays unpinned (R1).
- [ ] **Step 3: README rows** for the spec, the plan and the findings, after the row for `superpowers/specs/2026-10-01-keyword-search-cleanup-design.md`, in the slice 27 rows' format.
- [ ] **Step 4: Rulings.** The spec's `## Rulings` holds R1–R5. If the ledger records more rulings, add each after R5 in the same format (Decided / Found by / Why / Cost if wrong), and quote it in findings §3.
- [ ] **Step 5: Plan changes.** Fill this plan's `## Changes made during execution` from the ledger: one bullet per task, plus one each for the final review and any fix wave, quoting departures as recorded; the bullet for the commit that fills this section ends "(this commit)".
- [ ] **Step 6: Grep** the changed docs files (findings-slice28, findings-slice24, findings-slice27, README, the spec, this plan) for the banned words; expected: no match except this plan's own Global Constraints list.
- [ ] **Step 7: Commit** `git add docs && git commit -m "docs: slice 28 findings, index and notes" -m "<trailer>"`.

---

## Self-review against the spec

- §1 tests: Task 1 Step 2 has the three tests with the spec's setups and expected values, word for word (`rows[0].keyword`, `rows[0].keywords`, `engine.prompts`, 2 rows).
- §2 helper: Task 1 Step 1 (`keyword="kids sandals"`, `error=None` defaults; `search_query(keyword)`; `error=error`). `test_an_error_search_is_not_reused` is untouched (Global Constraints).
- §2 red checks: Task 1 Steps 4–5 (the spec's setup and its three mutations; m3 is the spec's replacement split over two lines, departure 7) and the green run on main's code.
- §2 docs: Task 2 Steps 1–3 (findings-slice28; the dated updates in findings-slice24 §3, including the Task 1 minor per R1, and findings-slice27 §3; README rows). §2 copy: Task 1 Step 6 and Task 2 Step 6. §2 no live check: findings §2 text. §2 gates: controller, before the finishing menu.
- Departures from the spec:
  1. Test code details the spec does not state: the `gen` variable, the `_, rows, searches` unpacking, `_fresh_row(owner, org, bid, [], error="429 quota")` and `_fresh_row(..., days=2, keyword="kid sandals")` calls, and test 2's two asserts joined with `and`.
  2. Step 3 runs the whole test file (33 passed), and Step 6 states the gate count (1552 = 1549 + 3); the spec names neither.
  3. The red checks are run by the Task 1 implementer inside the plan's workspace, and each run adds `-k` for the three tests; the spec says only "on scratch copies outside the repo".
  4. Task 1 Step 4 writes mutation m1 as a three-line replacement (the error line with its neighbours) so the old string is unique; the spec says "delete `m.KeywordSearch.error.is_(None),` from the seed query only".
  5. Findings §3 also carries the spec's Out of scope list and the slice 27 carried-forward items, and Task 2 also updates the spec's Rulings and this plan's changes section; spec §2's docs list names neither.
  6. Task 2 Step 2 adds dated updates under two more findings-slice24 Untested bullets (newest-wins and non-first) as well as the error-filter one; the spec says "under the Untested items" without naming them.
  7. Task 1 Step 4 writes m3's replacement over two lines (`... if n == 0 else k`, then `for n, k in enumerate(fitted)`); the spec gives it as one line. Same code.
  8. Task 1 Step 6 prints the gate's exit code with `echo "gate exit $?"` after the redirect; the spec does not say how the exit code is recorded.
- Verified before committing this plan: the Step 1, Step 2 and Step 4 replacements were applied, from this file's own code blocks, to scratch copies of main (each old string found exactly once). Main's code: 33 passed for the whole edited file; the three new tests pass. m1, m2 and m3 each gave `1 failed, 2 passed, 30 deselected`, failing only the test named in Step 5. ruff check and ruff format --check are clean on the edited test file.
- Placeholders: none (`<trailer>` and `<workspace>` are per-session values).
- Type consistency: `_fresh_row`'s signature is the same in Interfaces, Step 1 and Step 2.

## Changes made during execution

(Filled by Task 2 from the ledger.)
