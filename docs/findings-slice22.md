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
| 68dbe67 | docs: slice 22 findings: final-review minors |
| 6177f1e | docs: slice 22 rulings R1-R2 and last coverage items |
| (this commit) | docs: slice 22 live check and last touch-ups |

## 2. Live check on dev

Run on 2026-09-29 by the controller at 6177f1e, with the user's OK ("run the dev re-check first"). Dev was at migration 0020; no migration was needed.

- Pre-check: no worker or uvicorn running, 0 queued or running jobs, 5 prior `product_run` jobs totalling 1,587,958 micros.
- The API was started in the background. `POST /v1/brands/34db213a-f484-4991-a969-c52cfa5e1c10/products/run` returned HTTP 202 and queued job `d75feb1d-5c24-42f0-b88d-8b6578e4bb73`. The API was then stopped (background task exit 144, expected). Exactly 1 job was queued, and `process_job` was run once (it printed `True`). The worker loop was not started.
- Job `d75feb1d`: status done, error null, `cost_micros = 5,819`, created 17:53:51, started 17:53:58 UTC.
- No grounded search ran: 0 `keyword_search` rows were searched in the last 30 minutes, and all 8 keywords were cached. The keywords are the same 8 as slice 21's check.
- Afterwards: 0 queued or running jobs, and no worker or uvicorn process.

**Per product** (observed by read-only queries after the job):

| Product | Keyword | Missing words | Suggested title | Status | Dropped words |
|---|---|---|---|---|---|
| LC-01 | kids sandals | kid | BSOAgentTestBrand Blue Kid Sandals Boys | adjusted | (none) |
| LC-02 | kids sandals | kid | BSOAgentTestBrand Pink Kid Sandals Girls | adjusted | (none) |
| LC-03 | kids shoes | (none) | BSOAgentTestBrand Black Kids Sports Shoe | adjusted | (none) |
| LC-04 | kids slippers | (none) | BSOAgentTestBrand Grey Kids Slippers | adjusted | (none) |
| LC-05 | navy flip flops | (none) | BSOAgentTestBrand Navy Flip Flop Men | adjusted | (none) |
| LC-06 | men sandals | (none) | BSOAgentTestBrand Brown Men Casual Sandal | adjusted | (none) |
| LC-07 | women slippers | (none) | BSOAgentTestBrand Beige Women Casual Slipper | adjusted | (none) |
| LC-08 | men shoes | (none) | BSOAgentTestBrand Grey Men Sports Shoe | adjusted | (none) |
| LC-09 | kids shoes | kids | BSOAgentTestBrand Black Kids School Shoe Boys | adjusted | (none) |
| LC-10 | women sandals | footbed | BSOAgentTestBrand Tan Women Sandal Footbed | adjusted | (none) |

**Against spec §3's *inferred* expectations:** all 10 match (LC-01/02 kid, LC-09 kids, LC-10 footbed, none for LC-03..LC-08).

**Observations.**
- All 10 statuses are `adjusted` (the stored title differs from the rewrite's suggestion), with 0 dropped words. The raw rewrite is not stored, so which words `rule_check` removed is *inferred* only (unbacked or repeated words).
- LC-05 was `review` (dropped "men") in slice 21's check. It is now `adjusted`, with "Men" kept.
- No suggestion contains Boots, Slide, Toddler, Available, Wide or Width.

**Spend:** about $10.87 + $0.0058 ≈ $10.88 of the $15 cap.

**Writes:** the job row, 10 product rows and `api_key.last_used_at`. No `keyword_search` writes.

## 3. Deferred and untested

From the task reviews:
- Task 1: the gate output carries 2 third-party warnings (StarletteDeprecationWarning from fastapi/testclient.py; DeprecationWarning from starlette/testclient.py:53, the anyio BlockingPortal alias). They are pre-existing on main, not caused by this diff. Fix outside this slice (filterwarnings entry or dependency bump).
- Task 1: the `missing` docstring's "In more than half of the titles and at least MIN_TITLES (rule 2)." is a sentence fragment. It is the plan's text.
- Task 2: the rival test's comment (tests/integration/test_products_run.py:510, "Without the exclusions: [...]") now also depends on the seeded description backing crocs, teva and hurricane, and does not say so. The brief kept the comment unchanged.
- Task 2: the gate output carries the same 2 third-party warnings as Task 1's. They are not from this diff.
- Task 3: findings-slice22.md:37 gives Task 1's Starlette warning location as `fastapi/testclient.py:1`; ledger line 27 has no line number; task-1-report.md does say `:1`.
- Task 3: findings-slice22.md:64 drops the ledger's "(see Task 1's minor)" (progress.md:36); meaning kept.

From the final whole-branch review:
- duplicate ranking titles count twice toward rule 2 (products.py:523-536; `["X Summer", "X Summer", "Y Other"]` with backing ["summer"] gives ["summer"]); pre-existing with `n >= MIN_TITLES`; dedupe with dict.fromkeys(titles) if stored titles are seen to repeat.
- findings-slice22.md's commit table ends at "(this commit)" (dbb5d82) and lacks 01dbca7 "docs: slice 22 plan changes: the findings Untested list"; add the row with the live-check docs edit. Fixed in 68dbe67.
- docs/README.md's slice 22 spec row says "with the rulings made during the build", but the spec's ## Rulings reads "None." (wording copied from the slice 21 row). Fixed in 68dbe67; the spec now has Rulings R1 and R2, so the row says "with the rulings made during the build" again.
- spec §3's inferred LC-09 "kids" looks odd to the reviewer, on the premise that the product title already says "Kids". Controller check (read-only dev query): LC-09's title is "BSOAgentTestBrand Boys School Shoe Black" (no "Kids"; LC-03's is "BSOAgentTestBrand Kids Sports Shoe Black"), so the premise does not hold for LC-09; compare with what the live check observes.
- plan:545 says the commit table "gains the rows dbb5d82 and 01dbca7"; dbb5d82 was relabelled from "(this commit)", and the new "(this commit)" row is not mentioned. Fixed in 6177f1e: the plan's changes section now says so.

From the re-review of 6177f1e:
- findings §3's two "Fixed in this commit: ..." notes added by 6177f1e (R1's, requested; the plan:545 bullet's, not requested but accurate) must become "Fixed in 6177f1e" at the next commit (the live-check docs, if run). Fixed in this commit.
- the parked bullets cite 68dbe67's findings line numbers (:67, :67-68, :72-73), which 6177f1e shifted; they follow the ledger text as asked. Fixed in this commit: each parked bullet now says "(line numbers as at 68dbe67)".

Parked (with rulings):
- (line numbers as at 68dbe67) findings-slice22.md:67 adds "(line numbers as at dbb5d82)" to the Task 3 minors; true for `:64`, false for `:37` (at dbb5d82 line 37 is blank; the Starlette warning line is 35) — Ruling R1: the doc line is wrong and should be corrected, but the skill allows no second fix wave; it is surfaced to the user at finishing as a one-line docs fix (drop the qualifier, keeping the ledger text) — cost if wrong: one findings bullet cites a wrong line number until fixed. Fixed in 6177f1e: the qualifier is removed.
- (line numbers as at 68dbe67) findings-slice22.md:67-68 and :72-73 carry text beyond the ledger lines (the "(line numbers as at dbb5d82)" prefixes; " Fixed in this commit." suffixes, which are accurate) — Ruling R2: the suffixes stand as accurate status notes; the prefix goes with the item above — cost if wrong: two bullets are not word-for-word ledger text.

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
