# Slice 22 findings: missing words backed by product data

## 1. What was built

This slice targets three problems that slice 21's live check recorded (findings-slice21 §2):
- Category drift: "Boots" for the LC-03 and LC-09 shoes, and "Slide" for the LC-06 sandal.
- Retailer phrasing: LC-10 got the missing words footbed, available, slide, strap, wide, width.
- Size markers: "Toddler" for LC-01 and LC-02.

All code changes are in `packages/core/bsi_core/products.py`. No schema, API or web change.

**`missing(..., backing=None)`.** `missing` gains `backing: Sequence[str] | None = None` and two rules:
- Rule 1, backing. When `backing` is not `None`, a ranking-title token is skipped unless its stem is in `_allowed_stems("", backing, [])`. The check sits beside the `have` and `NOISE_STEMS` checks. When `backing` is `None`, rule 1 is off.
- Rule 2, more than half the titles. A word must be in at least `max(MIN_TITLES, len(titles) // 2 + 1)` titles (2 of 2, 2 of 3, 3 of 4, 3 of 5). It replaces `n >= MIN_TITLES` and applies with or without `backing`. `MIN_TITLES` stays 2.
- The docstring names both rules. A `# ponytail:` comment above `backed = …` carries the four known ceilings (§3).

**`run_products`.** The missing-words loop stores `p["backing"] = [p["keyword"], p["description"] or "", p["category"] or "", *(str(v) for v in (p["attributes"] or {}).values())]` and passes `backing=p["backing"]` to `missing`. The `rule_check` call now takes `allowed=[*p["backing"], *p["missing"]]`: the same texts as before, in a different order. So a ranking word that is not backed is neither a missing word nor allowed, and if the rewrite adds it on its own, `rule_check` drops it (status `adjusted`).

**The `NOISE_WORDS` comment.** Its last clause now reads "toddler/youth/infant are not listed: since slice 22 missing() suggests such a word only when the product's data backs it."

**Tests.**
- `tests/unit/test_products.py`: 7 new `missing` tests with the fixtures `WS`, `KS`, `KSH`, `B` and `WSB` (the dev titles and product data from the spec). `WS` with `WSB` gives `["footbed"]`; `KS` with its backing gives `["kid"]`; `KSH` with its backing gives `[]`; `backing=[]` gives `[]`; rule 2 alone gives `["footbed"]`; rule 2 over a backed word gives `["footbed"]`; the Titan "men watches" case gives `["men", "watch"]`. The 7 existing `missing` tests are unchanged.
- `tests/integration/test_products_run.py`:
  - `_seed` gains `description=None`.
  - `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` seeds `description="Summer sandal"`; its expected values are unchanged.
  - The rival test seeds `description="Summer sandal, an alternative to Crocs and Teva Hurricane"`, and `RIVAL_TITLES` is now 3 titles. Its expected value `["summer"]` and its comment are unchanged.
  - New: `BACKED_TITLES`, the helper `_backed_run`, `test_only_backed_words_are_missing_and_kept` and `test_the_rewrite_cannot_add_an_unbacked_ranking_word`.
- TDD evidence, as the tasks recorded it:
  - Task 1 RED: 7 failed (6 `TypeError` on `backing`, 1 with the six-word list). GREEN: `-k missing` 14 passed.
  - Task 2 RED: 2 failed, 22 passed (both on `['lightweight', 'summer'] == ['summer']`). GREEN: 24 product-run tests passed.
  - Task 2's R5 re-proof: with `for n in (c.name, *c.aliases)` changed to `for n in (c.name,)`, the rival test failed with `['summer', 'crocs']`. It passed after `products.py` was restored from the backup, and `git diff --stat` showed only the 2 files.
- Backend gate:
  - Task 1 (4a53c61): ruff and mypy clean; 1518 passed, 2 deselected, 2 warnings; metrics coverage 100%.
  - Task 2 (5be232a): ruff and mypy clean; 1520 passed, 2 deselected (the `live`-marked tests, deselected by pyproject addopts "-m 'not live'"), 2 warnings; metrics coverage 100%.
  - The 2 warnings in both runs: `StarletteDeprecationWarning` (fastapi/testclient.py:1) and the anyio `BlockingPortal` alias `DeprecationWarning` (starlette/testclient.py:53).
  - The controller ran `uv run pytest -q tests/integration/test_products_run.py tests/unit/test_products.py` at 5be232a: 97 passed in 7.22s. The controller's own full gates run at finishing.

**Commits** (`git log --oneline main..HEAD`, oldest first):

| Commit | Subject |
|---|---|
| 1bed2fe | docs: slice 22 spec (missing words backed by product data) |
| 99d231a | docs: slice 22 spec review fixes (both rules, -es backing, rival test fixtures, named tests) |
| 3edfc50 | docs: slice 22 spec: R5's exact check, two new integration tests |
| c13f226 | docs: slice 22 implementation plan |
| 6aea5df | docs: slice 22 plan review fixes |
| c9187ba | docs: slice 22 plan: scratchpad backup path, blank line |
| 21f9566 | docs: slice 22 plan: cd before the backup commands |
| f44bacd | docs: slice 22 plan: cd before git diff --stat |
| 4a53c61 | fix(products): a missing word needs product backing and more than half the titles |
| 5be232a | fix(products): the run passes the product's data as backing for missing words |
| dbb5d82 | docs: slice 22 findings, index and rulings |
| 01dbca7 | docs: slice 22 plan changes: the findings Untested list |
| (this commit) | docs: slice 22 findings: final-review minors |

## 2. Live check on dev

Not yet run. The controller runs it after the user approves; results are recorded here then.

## 3. Deferred and untested

From the task reviews:
- Task 1: the gate output carries 2 third-party warnings (StarletteDeprecationWarning from fastapi/testclient.py; DeprecationWarning from starlette/testclient.py:53, the anyio BlockingPortal alias). They are pre-existing on main, not caused by this diff. Fix outside this slice (filterwarnings entry or dependency bump).
- Task 1: the `missing` docstring's "In more than half of the titles and at least MIN_TITLES (rule 2)." is a sentence fragment. It is the plan's text.
- Task 2: the rival test's comment (tests/integration/test_products_run.py:510, "Without the exclusions: [...]") now also depends on the seeded description backing crocs, teva and hurricane, and does not say so. The brief kept the comment unchanged.
- Task 2: the gate output carries the same 2 third-party warnings as Task 1's. They are not from this diff.
- Task 3 (line numbers as at dbb5d82): findings-slice22.md:37 gives Task 1's Starlette warning location as `fastapi/testclient.py:1`; ledger line 27 has no line number; task-1-report.md does say `:1`.
- Task 3 (line numbers as at dbb5d82): findings-slice22.md:64 drops the ledger's "(see Task 1's minor)" (progress.md:36); meaning kept.

From the final whole-branch review:
- duplicate ranking titles count twice toward rule 2 (products.py:523-536; `["X Summer", "X Summer", "Y Other"]` with backing ["summer"] gives ["summer"]); pre-existing with `n >= MIN_TITLES`; dedupe with dict.fromkeys(titles) if stored titles are seen to repeat.
- findings-slice22.md's commit table ends at "(this commit)" (dbb5d82) and lacks 01dbca7 "docs: slice 22 plan changes: the findings Untested list"; add the row with the live-check docs edit. Fixed in this commit.
- docs/README.md's slice 22 spec row says "with the rulings made during the build", but the spec's ## Rulings reads "None." (wording copied from the slice 21 row). Fixed in this commit.
- spec §3's inferred LC-09 "kids" looks odd to the reviewer, on the premise that the product title already says "Kids". Controller check (read-only dev query): LC-09's title is "BSOAgentTestBrand Boys School Shoe Black" (no "Kids"; LC-03's is "BSOAgentTestBrand Kids Sports Shoe Black"), so the premise does not hold for LC-09; compare with what the live check observes.

Untested:
- The two reworked integration tests were never seen failing: their fixtures changed, but their expected values pass both before and after the wiring (plan departure 4). The R5 re-proof shows the rival test still fails when the alias exclusion is removed.
- A description also goes to `fit_rank` and `rewrite_prompt`. No step checks this on its own; only the product-run tests and the gate cover it (plan departure 14).
- The tests use fixed judge output, so they do not show which words the rules leave for real answers. The dev re-check (§2) is where that is observed.

Known ceilings (spec §1, in the `# ponytail:` comment in `missing`):
- Stems must match exactly, apart from the "-es" singular: "cushioned" does not back "cushion".
- A product with no description, category or attributes gets only words of its keyword.
- A colour or size word in the attributes ("blue") is still not suggested, because `NOISE_STEMS` is checked too.
- A word the product data backs but only 2 of 5 titles use is not suggested.

Out of scope (spec):
- The keyword vote choosing a colour phrase ("navy flip flops").
- Near-matches and synonyms between a ranking-title word and the product data.
- The deferred minors in docs/findings-slice21.md §3.
