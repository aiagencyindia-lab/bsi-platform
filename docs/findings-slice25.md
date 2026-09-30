# Slice 25 findings: store the raw keyword samples and the raw rewrite

## 1. What was built

The findings for slices 23 and 24 marked every statement about which keyword sample offered a stored keyword, or which words the rule check removed, as *inferred*, because `run_products` kept neither the sample lists nor the rewrite call's title (spec, Context). Each product row now stores both for its latest run. They are read with psql; no API, web, CSV, prompt or copy change.

**Migration.** `migrations/versions/0021_product_raw.py` (`revision = "0021"`, `down_revision = "0020"`) adds two nullable columns to `product`: `keyword_samples` (JSONB) and `raw_title` (text). The downgrade drops `raw_title`, then `keyword_samples`. No constraint, index or `_protect` call; the table already has RLS from 0019.

**ORM.** `Product` (`packages/core/bsi_core/models.py`) gains, after `dropped_words`, `keyword_samples: Mapped[list[list[str]] | None] = mapped_column(JSONB)` (line 559) and `raw_title: Mapped[str | None]` (line 560), with a three-line comment above them.

**Where `run_products` writes them** (`packages/core/bsi_core/products.py`):
- Keyword step: `p["samples"] = [sm.get(i, []) for sm in samples]` (line 1055), the three sample lists after `_clean`, is what `choose_keywords` receives. The first per-batch UPDATE writes `keyword_samples=p["samples"]` (line 1090) for every product in the batch, a product that ends with no keyword included.
- Rewrite step: `title_in = item.title.strip() if item else ""`, `p["raw_title"] = title_in or None`, `suggestion = title_in or p["title"]` (lines 1230-1232; `suggestion` has the same value as before). The second UPDATE writes `raw_title=p["raw_title"]` (line 1250).
- R13: the `cleared` dict gains `"raw_title": None` (line 1079), so a product that loses its keyword loses its old raw rewrite with its old suggestion.

**Tests** (`tests/integration/test_products_run.py`):
- `_generator` (line 54) gains `skip_rewrite=()`: product indexes left out of the rewrite body (line 125). Callers that do not pass it are unchanged.
- `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` (line 182) also asserts `p.keyword_samples == [["kids sandals", "walkaroo kids"]] * 3` and `p.raw_title == "Walkaroo Kids Summer Sandals Sandals"` (lines 224-225); the checked `suggested_title` is "Walkaroo Kids Summer Sandals".
- `test_a_product_whose_keyword_drops_loses_its_old_suggestion` (line 746) seeds `raw_title="Old raw"` and also asserts `p.raw_title is None` and `p.keyword_samples == [["walkaroo sandals"]] * 3` (lines 774-775).
- New, `test_a_product_without_a_rewrite_keeps_its_title_and_no_raw_title` (line 778): `_generator(skip_rewrite={0})`; asserts `job.status == "done"`, `raw_title is None`, `suggested_title == "Walkaroo Boys Sandal 0"`, `(rule_check, dropped_words) == ("pass", [])`, `suggested_bullets == []` and the uniform `keyword_samples`.
- New, `test_keyword_samples_round_trip` (line 891): writes `keyword_samples` with a non-ASCII entry and an empty inner list, and `raw_title="Kids Sandals — Summer"`, through the `owner` fixture, and reads both back equal in a new session.
- TDD evidence, as the task reports record it:
  - Task 1 RED: `TypeError: 'keyword_samples' is an invalid keyword argument for Product`, 1 failed, 28 deselected. GREEN: 1 passed, 28 deselected.
  - Task 2 RED: 3 failed, 27 deselected; the rewrite-checked and no-rewrite tests on `assert None == ([['kids sandals', 'walkaroo kids']] * 3)`, the drops test on `assert 'Old raw' is None`. GREEN: 3 passed, 27 deselected. The product-run file: 30 passed.
- Backend gate (Task 2, 05ad185), as the ledger records it: "1544 passed, 2 deselected, 2 warnings (StarletteDeprecationWarning, anyio BlockingPortal alias), coverage 100%". The gate file holds only the pytest output (§3, the first Task 2 minor); the controller ran the rest at 05ad185: `uv run ruff check .` "All checks passed!"; `uv run ruff format --check .` "169 files already formatted"; `uv run mypy` "Success: no issues found in 29 source files".

**Commits** (`git log --oneline main..HEAD`, oldest first):

| Commit | Subject |
|---|---|
| 469c64e | docs: slice 25 design spec |
| 67ddf00 | docs: slice 25 spec review fixes |
| ec48b30 | docs: slice 25 spec: failed-batch note covers every step |
| a952344 | docs: slice 25 implementation plan |
| 42fec76 | docs: slice 25 plan review fixes |
| bf5ced4 | feat(products): keyword_samples and raw_title columns (migration 0021) |
| 05ad185 | feat(products): store the keyword samples and the raw rewrite |
| (this commit) | docs: slice 25 findings, index and hashes |

## 2. Live check on dev

Not yet run. The controller migrates dev and runs it after the user approves each; results are recorded here then.

## 3. Deferred and untested

From the task reviews (ledger lines tagged `minor (deferred)`):
- Task 1: the Edit tool decodes `\u` escapes into literal characters; the final diff has escapes only (process note for later tasks, not a code defect).
- Task 2: the gate file records only pytest output; in the plan's Step 9 command `> gate-task2.txt` applies to the last command of the `&&` chain, so ruff and mypy results are not in the file. Future gates should redirect the whole chain.
- Task 2: the gate output has 2 warnings (StarletteDeprecationWarning about httpx; anyio BlockingPortal DeprecationWarning), third-party and pre-existing.
- Task 2: no test covers a product absent from one keyword sample (a `[]` entry in `keyword_samples` via `sm.get(i, [])`); the tests assert uniform samples only.

Parked: none. The ledger has no parked lines.

Rulings (the ledger records one, in its preflight section; also in the spec's `## Rulings`):
- **R1: Task 2's gate output goes to the plan's workspace directory.** Decided: Task 2's gate output goes to `.superpowers/sdd/2026-09-30-slice25-raw-samples/gate-task2.txt`, not `.superpowers/sdd/gate-task2.txt` (the path in the plan's Task 2 Step 9). Found by the controller's preflight scan of the plan. Why: the plan's Global Constraints name the workspace directory, and the skill keeps each plan's artifacts in its own directory. Cost if wrong: none (a git-ignored scratch path).

Carried forward (still open):
- Stale duplicate `keyword_search` rows: rows under an old spelling stay in the table; nothing deletes them (docs/findings-slice24.md §3, ceilings and Out of scope).
- The slice 24 seed's untested cases (docs/findings-slice24.md §3, Untested): no test pins the seed's `error.is_(None)` filter on its own; newest-wins between two valid rows that share a key; adoption of a non-first keyword.
- The judge-agreement question, waiting on the user.

Out of scope (spec):
- Exposing `keyword_samples` or `raw_title` through the API, the Products tab or `export.csv`.
- Storing `backing`, the raw model JSON, the untrimmed bullets, or any history across runs.
- Deleting stale duplicate `keyword_search` rows; the seed's untested filters; the judge-agreement labels.
- The deferred minors in docs/findings-slice23.md §4 and docs/findings-slice24.md §3.
