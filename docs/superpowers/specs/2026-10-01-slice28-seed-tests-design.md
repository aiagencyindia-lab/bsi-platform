# Slice 28 design: tests for the slice 24 seed

## Context

Slice 24 seeds `run_products`' run-wide `key_map` from the brand's fresh valid `keyword_search` rows, newest first (packages/core/bsi_core/products.py, the block above `for batch in _batches(products)`). docs/findings-slice24.md §3 (Untested) lists three seed cases no test pins, carried forward through docs/findings-slice27.md §3:
- The seed's own `error.is_(None)` filter. An error row with an empty title list passes `_current` (`all()` over no titles is true), so the SQL filter is what keeps it out of the seed. `test_an_error_search_is_not_reused` votes the exact spelling "kids sandals", so it passes with the seed's error filter removed.
- Newest-wins between two valid rows that share a key: every seed test has one cached row.
- Adoption by a non-first keyword: every seed test votes one keyword.

A probe before the design (read-only, no model call): `choose_keywords([["boys sandals", "kid sandal"]] * 3, ["Walkaroo"], "Walkaroo Boys Sandal 0", None, None)` returns `["boys sandals", "kid sandal"]`; their keys are "boy sandal" and "kid sandal".

Classification, said in chat as the first line of the first brainstorming reply: **bounded** — "this adds tests to the existing `run_products` seed in `tests/integration/test_products_run.py`, with no production code change. Your rule is a spec and plan even for small changes, so I'll still write both and run them through subagent-driven development."

Decisions approved in chat (brainstorming on Opus 5.5, 2026-10-01). The approaches (A: three integration tests; B: a pure `seed_key_map` helper with unit tests; C: only the error-filter test) were written in a chat message with trade-offs and a recommendation; the user chose A. Each design section's text was in chat before its approval question; the user approved Section 1 and Section 2.

## Design

### 1. The three tests

In tests/integration/test_products_run.py, directly after `test_a_row_the_lookup_rejects_is_not_seeded`. Each uses `_seed(owner, org, bid, 1)` (one product, "Walkaroo Boys Sandal 0"), `FakeEngine`, `_generator` and `_run`.

**`test_an_error_row_is_not_seeded`**
- A fresh row (1 day old) "kids sandals" with titles `[]` and error "429 quota"; the vote is `keywords=["kid sandal"]`.
- Expected: `rows[0].keyword == "kid sandal"`; `engine.prompts == [(search_query("kid sandal"), "IN", "en")]`; 2 `keyword_search` rows (the untouched error row and the new "kid sandal" row).
- Pins: the seed's own `error.is_(None)`. Without it the error row is seeded, the product takes "kids sandals", and the search goes out under that spelling.

**`test_the_newest_cached_spelling_wins`**
- Two fresh valid rows with `CACHED_TITLE`: "kids sandals" 1 day old and "kid sandals" 2 days old (both key "kid sandal"); the vote is `keywords=["kid sandal"]`.
- Expected: `rows[0].keyword == "kids sandals"`; `engine.prompts == []`; 2 rows.
- Pins: `searched_at.desc()`. The older spelling sorts first alphabetically, so oldest-first or keyword-only ordering gives "kid sandals".

**`test_a_non_first_keyword_adopts_a_cached_spelling`**
- A fresh "kids sandals" row with `CACHED_TITLE`; the vote is `keywords=["boys sandals", "kid sandal"]`.
- Expected: `rows[0].keywords == ["boys sandals", "kids sandals"]`; `rows[0].keyword == "boys sandals"`; `engine.prompts == [(search_query("boys sandals"), "IN", "en")]`; 2 rows.
- Pins: the seed applies to every keyword, not only the searched first one.

### 2. Helper, red checks, docs

- `_fresh_row(owner, org, bid, titles, days=1)` becomes `_fresh_row(owner, org, bid, titles, days=1, keyword="kids sandals", error=None)`; the query is `products.search_query(keyword)` and the row gets `error=error`. The defaults keep today's rows unchanged, so the existing callers do not change. `test_an_error_search_is_not_reused` keeps its own inline row.
- No production change: packages/core/bsi_core/products.py is not touched, including the `# ponytail:` comment above `key_map`.
- Red checks, on a scratch copy of `bsi_core` with the test file in its own folder: (1) delete `m.KeywordSearch.error.is_(None),` from the seed query only (not the per-batch lookup): only `test_an_error_row_is_not_seeded` fails; (2) change the seed's `searched_at.desc()` to `.asc()`: only `test_the_newest_cached_spelling_wins` fails; (3) apply the seed only to the first keyword, keeping the others as voted: only `test_a_non_first_keyword_adopts_a_cached_spelling` fails. Green: all three pass against main's code. An expected value that turns out wrong goes to the user, not into the test.
- Docs: docs/findings-slice28.md (what was built, red and green results, rulings, deferred); a dated "Update" under the Untested items in docs/findings-slice24.md §3 and under the carried-forward seed item in docs/findings-slice27.md §3 (originals kept); README rows for the spec, plan and findings.
- No live check: no behaviour changes, so no spend and no dev write.
- Gates: both gates, run by the controller before the finishing menu.

## Rulings

- **R1: the seed's keyword tie-break is out of scope.** Decided: no test for two rows with the same `searched_at`, where the seed's second sort key, `keyword`, picks the spelling. Found by the controller writing the spec (it was not raised in chat). Why: findings-slice24 does not list it, and all real rows written in one run share one `searched_at` only when they are different keys. Cost if wrong: the tie-break stays unpinned. Named in chat when made.

## Out of scope

- Any change to the seed, the cache lookup or `products.py`.
- The seed's keyword tie-break between two rows with the same `searched_at`.
- Rewriting `test_an_error_search_is_not_reused` to use `_fresh_row`.
- Deleting old-spelling `keyword_search` rows in code (the open item in docs/findings-slice27.md §3).
