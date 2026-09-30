# Slice 28 design: tests for the slice 24 seed

## Context

Codebase facts: main `465327b`, checked 2026-10-01.

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
- Red checks, on scratch copies outside the repo: each mutation is made in its own copy of packages/core/bsi_core, and the edited test file sits in a separate folder with no `bsi_core` in it (pytest puts a test file's folder on `sys.path`, so a copy next to it would shadow main's code). Each run is `PYTHONPATH=<copy folder>:. uv run pytest -q -p no:cacheprovider -p tests.conftest --rootdir . <scratch test file>`, from the repo root, where `<copy folder>` is the directory that contains the copied `bsi_core/`: the copy comes first on `sys.path`, `.` resolves `tests.integration.test_worker`, and `-p tests.conftest` loads the fixtures. The mutations: (1) delete `m.KeywordSearch.error.is_(None),` from the seed query only (not the per-batch lookup): only `test_an_error_row_is_not_seeded` fails; (2) change the seed's `searched_at.desc()` to `.asc()`: only `test_the_newest_cached_spelling_wins` fails; (3) in `run_products`, replace `key_map.setdefault(keyword_key(k), k) for k in fitted` with `key_map.setdefault(keyword_key(k), k) if n == 0 else k for n, k in enumerate(fitted)` (the first keyword goes through `key_map`; the others stay as voted): only `test_a_non_first_keyword_adopts_a_cached_spelling` fails. Green: all three pass against main's code (`PYTHONPATH=. …`, same flags). An expected value that turns out wrong goes to the user, not into the test.
- Docs: docs/findings-slice28.md (what was built, red and green results, rulings, deferred); a dated "Update" under the Untested items in docs/findings-slice24.md §3, under its Task 1 minor on the order rule (`.desc()` now pinned; the secondary sort key still unpinned, R1), and under the carried-forward seed item in docs/findings-slice27.md §3 (originals kept); README rows for the spec, plan and findings.
- Copy: the new test names, fixture values and comments are checked against `FORBIDDEN` in tests/unit/test_recommend_copy.py.
- No live check: no behaviour changes, so no spend and no dev write.
- Gates: both gates, run by the controller before the finishing menu.

## Rulings

- **R1: the seed's keyword tie-break is out of scope.** Decided: no test for two rows with the same `searched_at`, where the seed's second sort key, `keyword`, picks the spelling. Found by the controller writing the spec (it was not raised in chat). Why: findings-slice24 does not list it, and all real rows written in one run share one `searched_at` only when they are different keys. Cost if wrong: the tie-break stays unpinned. Named in chat when made.
  - Correction to R1's Why (2026-10-01): findings-slice24 does list it (§3, the Task 1 minor: "dropping `.desc()` or the secondary sort key would fail no test"), found by the spec review of 5bccb92. The reason that holds: `run_products` cannot produce the tie, since one run gives every search the same `searched_at` but writes one spelling per key, and separate runs get different times; only a hand-inserted row can tie. The choice was asked again with the corrected fact, with two other options (a fourth test pinned by a `keyword.desc()` mutation; ordering the seed by `searched_at` only, a production change), and the user kept it out of scope. The Task 1 minor gets a dated update: `.desc()` is pinned, the secondary key is not.
- **R2: the spec review's three minor points were applied.** Decided: give mutation 3's exact replacement line, spell out the red-check setup, and add the main commit anchor and the copy line. Found by the spec review of 5bccb92. Why: a plan writer would otherwise guess; no design change. Cost if wrong: none. Named in chat when made.
- **R3: the spec re-review's minor point was applied.** Decided: say `<copy folder>` is the directory that contains the copied `bsi_core/`. Found by the re-review of d86f733. Why: it could be read as the copy itself. Cost if wrong: none. Named in chat when made.
- **R4: the plan review's seven minor points were applied.** Decided: in the plan, list m3's two-line split and the exit-code step as departures, add the deselected counts, record the gate's exit code from the tool result, give the insertion point, quote the findings-slice27 heading exactly, stop on a changed Step 3 count, and give each findings-slice24 sub-bullet its own update. Found by the plan review of 814ce16. Why: wording and clarity; no design change. Cost if wrong: none. Named in chat when made.
- **R5: the plan re-review's three points were applied.** Decided: Task 2 Step 4 adds new rulings after the last one (R4's fix had left "after R3"); the self-review's red counts include "30 deselected"; Task 1 Step 6 prints the gate's exit code with `echo "gate exit $?"` after the redirect. Found by the re-review of 1040504. Why: the first was a regression from R4's fix, the others record what a run prints. Cost if wrong: none. Named in chat when made.
- **R6: the plan's "Verified before committing" red counts were left unchanged.** Decided: the plan's record "1 failed, 2 passed, 30 deselected" stays as written. Found by the plan re-review of b30923f, which asked whether it was observed or inferred; decided before execution. Why: the controller's verification run printed exactly that for m1, m2 and m3 (observed). Cost if wrong: one overstated line in the plan's self-review. Named in chat when made.
- **R7: the bare "(R1)" in docs/findings-slice27.md was made "(slice 28 spec, R1)".** Decided: change the end of the slice 28 update in docs/findings-slice27.md §3 to "(slice 28 spec, R1)", departing from the plan's mandated Task 2 Step 2 text. Found by the Task 2 review (a deferred minor), which the final review's triage marked fix before merge. Why: that file already holds slice 27's R1 and the cleanup spec's quoted R1, the ambiguity cleanup ruling R13 was made to fix. Cost if wrong: one departure from plan text. Named in chat when made.
- **R8: three deferred minors stay deferred.** Decided: leave the joined assert at tests/integration/test_products_run.py:537, the paraphrase and date in docs/findings-slice28.md §3's stale-rows item, and "each seeds one product" in its §1 as they are. Found by the Task 1 and Task 2 reviews; triaged by the final review. Why: per the final review's triage: house style and a listed plan departure, accurate wording that points to its source, and a literal description of `_seed`. Cost if wrong: three small wording or style points stay. Named in chat when made.
- **R9: Task 1's ledger minor keeps its "separate asserts" claim, corrected beside it.** Decided: no fix for the final review's minor that Task 1's ledger minor wrongly says "the sibling tests use separate asserts"; the ledger line stays as the record, and docs/findings-slice28.md §3 quotes the final review's correction next to it. Found by the final review. Why: the ledger is a record, not a doc to rewrite. Cost if wrong: a slightly wrong claim stays in the quoted ledger line, corrected beside it. Named in chat when made.
- **R10: the one fix wave also completes the docs.** Decided: the fix wave quotes every Task 2 and Final `minor (deferred)` line in findings §3, gives the plan's changes section bullets for the Task 2 review, the final review and the fix wave, adds R7–R10 to this spec and findings §3, and updates the README spec row's ruling range; the fix wave's re-review result goes into the post-merge docs commit. Found by the final review (findings §3 and the plan's changes section were incomplete). Why: the final review asked for these before merge, and a controller commit is not allowed. Cost if wrong: the re-review result is recorded only after merge. Named in chat when made.
- **R11: the fix wave's re-review minors are parked for the post-merge docs commit.** Decided: no second fix wave; the two new minors the re-review found in the fix diff (the ledger pointer "findings-slice28.md:58" for the stale-rows item, which moved; and no note that the final-review and fix-wave bullets landed before merge) are recorded in the post-merge docs commit. Found by the scoped re-review of 0b4ff59..780b7d1. Why: the process allows one fix wave, and the controller does not fix findings on the branch. Cost if wrong: a stale line pointer and a missing note until the post-merge docs commit. Named in chat when made; recorded here after merge.
- **R12: the post-merge docs review's points 1, 3 and 4 were applied; point 2 was not.** Decided: fill the plan's stale "(this commit)" with 780b7d1, correct the list of what came after merge, and add notes in place beside the moved pointer and the "Fixed in the fix wave" line and in the plan's Task 2 bullet; keep R11's "Named in chat when made", since the controller named R11 in chat when it parked the two minors. Found by the review of 227470f. Why: accuracy and in-place notes, as the earlier :129→138 note did. Cost if wrong: none. Named in chat when made.
- **R13: the post-merge re-review's three minor points were applied.** Decided: complete the list of what came after merge (without "only"), restore the original "Fixed in the fix wave (R10)." line with a separate dated note, date the "after merge" notes, and record the post-merge review, R11's chat naming, R12 and R13 in the ledger. Found by the re-review of f19f2e9. Why: accuracy and the dated-note convention. Cost if wrong: none. Named in chat when made.
- **R14: the post-merge review results are quoted in the plan.** Decided: quote the three post-merge review result lines from the ledger in the plan's re-review bullet. Found by the re-review of b1a2d54. Why: the changes section quotes review results as recorded. Cost if wrong: none. Named in chat when made.

## Out of scope

- Any change to the seed, the cache lookup or `products.py`.
- The seed's keyword tie-break between two rows with the same `searched_at` (R1).
- Rewriting `test_an_error_search_is_not_reused` to use `_fresh_row`.
- Deleting old-spelling `keyword_search` rows in code (the open item in docs/findings-slice27.md §3).
