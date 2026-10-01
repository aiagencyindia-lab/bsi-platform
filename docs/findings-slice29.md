# Slice 29 findings: a product run deletes the brand's stale keyword_search rows

## 1. What was built

The open item "Stale duplicate `keyword_search` rows", carried from docs/findings-slice24.md §3 through docs/findings-slice27.md §3 to docs/findings-slice28.md §3, is fixed in code: each product run now deletes the brand's stale rows at its start.

**Code** (`packages/core/bsi_core/products.py`, `run_products`):
- A `DELETE` before the seed (line 1064): `delete(m.KeywordSearch).where(m.KeywordSearch.brand_id == brand_id, m.KeywordSearch.searched_at <= fresh_after)`, run in the tenant session that loads the seed of `key_map`, before the seed's `select`. The `<=` cutoff is the exact complement of the readers' `searched_at > fresh_after`, so a row is either readable or deleted. Only this brand's rows past `SEARCH_TTL_DAYS` go, whatever their spelling, error or parse version; the session commits on exit, before any model call.
- `delete` joins the `sqlalchemy` import (`from sqlalchemy import delete, func, select, update`).
- A two-line comment above the `DELETE`: stale rows are never read (the seed and the lookup need `searched_at > fresh_after`), so the run deletes them.
- The `# ponytail:` comment above `key_map`: "rows under an old spelling stay once stale" becomes "a fresh row under a losing spelling stays until it goes stale (not used meanwhile; the seed keeps the newest current spelling), and stale rows are deleted at run start".
- The `run_products` docstring gains "First deletes the brand's stale keyword_search rows."
- Unchanged: the seed, the per-batch lookup, the upsert, `SEARCH_TTL_DAYS`, the job's summary string, the `clear` route, the API, the web app, the migrations and models.

**Tests** (`tests/integration/test_products_run.py`):
- New `test_a_run_deletes_the_brands_stale_rows` (line 501): one product voting `["kid sandal"]`; a fresh "kids sandals" row (1 day old), a stale "kid sandals" row (8 days, another spelling of the same key), a stale "boys sandal" row (8 days, a keyword no product uses), and a stale "kids sandals" row (8 days) for a second brand, "Paragon", in the same org. Expected: `rows[0].keyword == "kids sandals"`, `engine.prompts == []`, and `sorted((r.brand_id == bid, r.keyword) for r in searches) == [(False, "kids sandals"), (True, "kids sandals")]`: this brand keeps only its fresh row, and the other brand's stale row stays.
- Changed `test_a_stale_row_spelling_is_not_adopted` (line 487): `assert len(searches) == 2` becomes `assert [r.keyword for r in searches] == ["kid sandal"]` (the stale "kids sandals" row is deleted). Its other asserts are unchanged.

Results, as the Task 1 report records them:
- Step 2 (red, on the unchanged code, `-k "stale_row_spelling or deletes_the_brands_stale"`): `2 failed, 32 deselected in 6.71s`. The changed test failed with `assert ['kids sandals', 'kid sandal'] == ['kid sandal']` (its assertion lines come from a rerun of that test alone, `1 failed, 33 deselected in 1.94s`, because the first run's output was cut); the new test failed with "At index 1 diff: (True, 'boys sandal') != (True, 'kids sandals')" and "Left contains 2 more items". Both failed as expected: the unchanged code kept the stale rows.
- Step 4 (green, the whole test file): `34 passed in 17.57s`.
- Step 5 (backend gate, from `gate-task1.txt`; the exit code is the `gate exit 0` the step printed): ruff format "169 files left unchanged"; ruff check "All checks passed!"; ruff format --check "169 files already formatted"; mypy "Success: no issues found in 29 source files"; pytest "1553 passed, 2 deselected, 2 warnings in 203.44s (0:03:23)" (the 2 known third-party warnings: the fastapi/starlette testclient `StarletteDeprecationWarning` about httpx and the anyio `BlockingPortal` `DeprecationWarning`); `bsi_core.metrics` coverage 100% ("Required test coverage of 100% reached. Total coverage: 100.00%"). The banned-word grep over `git diff` had no match.

**Commits** (`git log --oneline --reverse main..HEAD`, oldest first):

| Commit | Subject |
|---|---|
| 2a24492 | docs: slice 29 spec, delete stale keyword_search rows |
| 1d23c56 | docs: slice 29 spec review fixes |
| 750bf7d | docs: slice 29 spec, search cost source |
| 3878067 | docs: slice 29 plan |
| 63a93fa | docs: slice 29 plan review fixes |
| 41c6880 | docs: slice 29 plan, rulings step without a fixed range |
| 38a732c | docs: slice 29 plan, ruling ending as recorded |
| f61c9d5 | feat(products): a run deletes the brand's stale keyword_search rows |
| (this commit) | docs: slice 29 findings, index and notes |

## 2. Live check on dev

None in this slice (spec §2). No dev row is stale until 2026-10-06 13:10 UTC (18:40 IST); a check is a separate, later decision with its own approval.

## 3. Deferred and untested

From the task reviews (ledger lines tagged `minor (deferred)`):
- "Task 1: minor (deferred): no test covers a row exactly at the cutoff (`searched_at == fresh_after`); the spec rules it out of scope because the tests run through the worker, which does not take `now`"

Parked: none. The ledger has no parked lines.

Rulings (spec `## Rulings`, quoted in full):
- **R1: the spec review's six points were applied.** Decided: name docs/findings-slice28.md §3 (both lines) and docs/findings-slice24.md's Out of scope line in the docs list; "no run removes" for "stays for good"; "not used … newest current spelling" in the planned comment; the second brand's setup and a by-brand check in the new test; the corrected live-check cost with its source. Found by the spec review of 2a24492. Why: accuracy and completeness; no design change. Cost if wrong: none. Named in chat when made.
- **R2: the spec re-review's minor point was applied.** Decided: cite job f9de4eb9 for the 38,000-per-search figure. Found by the re-review of 1d23c56. Why: R1 named only the flash-lite figure's source. Cost if wrong: none. Named in chat when made.
- **R3: the plan review's two minor points were applied.** Decided: in the plan, the seed comment's last line is joined (no one-word `# start;` line), and Task 2 places the findings-slice27 update as the last sub-bullet of its item, after the quoted cleanup rulings. Found by the plan review of 3878067. Why: tidiness and a clear placement; no design change. Cost if wrong: none. Named in chat when made.
- **R4: the plan's rulings step gives no fixed ruling range.** Decided: Task 2 Step 4 adds only ledger rulings the spec does not already hold, matched by R-number (commit 41c6880). Found by the plan re-review of 63a93fa. Why: its fixed range ("holds R1–R2") had gone stale when R3 was added. Cost if wrong: none. Named in chat when made.
  - The ledger line, as recorded: "Ruling: R4 — Task 2 Step 4 no longer gives a fixed ruling range ("holds R1–R2" had gone stale when R3 was added); it adds only ledger rulings the spec does not already hold, matched by R-number (commit 41c6880) — found by the plan re-review of 63a93fa — cost if wrong: none. Named in chat when made."
- **R5: an added ruling ends as the ledger records it.** Decided: Task 2 Step 4 ends each added ruling as the ledger records it, usually "Named in chat when made." (commit 38a732c); applied without a further re-review, by the user's choice (option 1). Found by the plan re-review of 41c6880. Why: the ledger records no reason beyond the finding itself. Cost if wrong: an unreviewed one-phrase change to a docs step. Named in chat when made.
  - The ledger line, as recorded: "Ruling: R5 — Task 2 Step 4 ends each added ruling as the ledger records it, usually "Named in chat when made." (commit 38a732c); applied without a further re-review, by the user's choice (option 1) — found by the plan re-review of 41c6880 — cost if wrong: an unreviewed one-phrase change to a docs step. Named in chat when made."

Out of scope (spec):
- A test of a row exactly at the cutoff (`searched_at == fresh_after`): the tests run through the worker, which does not take `now`.
- Deleting fresh rows under a losing spelling (approach C).
- Any change to the seed, the lookup, the upsert, `SEARCH_TTL_DAYS`, the `clear` route, the job summary, or the schema.
- The live check (§2).

Carried forward from docs/findings-slice28.md §3 ("Carried forward from docs/findings-slice27.md §3"), still open:
- The judge-agreement question, waiting on the user.

The other carried-forward item, "Stale duplicate `keyword_search` rows", is fixed in code by this slice (§1); a fresh row under a losing spelling still stays until it goes stale (approach C, out of scope).

Untested: a row exactly at the cutoff (`searched_at == fresh_after`); the tests run through the worker, which does not take `now`.
