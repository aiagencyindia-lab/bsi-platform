# Slice 29 design: a product run deletes the brand's stale keyword_search rows

## Context

Codebase facts: main `13d54fe`, checked 2026-10-01.

The open item "Stale duplicate `keyword_search` rows: rows under an old spelling stay in the table" is carried from docs/findings-slice24.md §3 (a known ceiling of the slice 24 seed) through docs/findings-slice27.md §3 to docs/findings-slice28.md §3 (its "still open" list and its Out of scope list). On 2026-10-01 the user had the 11 such rows on dev deleted by hand (docs/superpowers/specs/2026-10-01-keyword-search-cleanup-design.md); the code still leaves them behind. The user asked for the code fix.

Facts read before the approaches (packages/core/bsi_core/products.py, `run_products`; the tests in tests/integration/test_products_run.py):
- Only `run_products` reads `keyword_search`: the run-start seed of `key_map` and the per-batch cache lookup. Both need `searched_at > fresh_after` (`fresh_after = now - timedelta(days=SEARCH_TTL_DAYS)`), so a stale row is never read. The API's `DELETE /v1/brands/{id}/products` (`clear`) deletes a brand's rows through a tenant session, so the app role may delete them. No web page, API route or migration reads the table.
- A stale row under the same spelling is overwritten by the upsert on `uq_keyword_search_brand_keyword` when that keyword is searched again; no run removes a stale row under any other spelling, or under a keyword no product uses any more.
- One existing test counts a stale row that the change deletes: `test_a_stale_row_spelling_is_not_adopted` (`assert len(searches) == 2`). `test_a_fresh_search_is_reused_and_a_stale_one_redone` keeps its count of 1 (same spelling, overwritten or deleted and re-inserted).

Classification, said in chat as the first line of the first brainstorming reply: **architectural** — "This makes every product run delete stored `keyword_search` rows, which changes what the cache holds for later runs, so it touches stored data and not just logic. Your rule is a spec and plan either way."

Decisions approved in chat (brainstorming on Opus 5.5, 2026-10-01). The approaches (A: at run start, delete all the brand's stale rows; B: delete stale rows whose key matches a keyword this run uses, under another spelling; C: also delete fresh rows that lose to a newer spelling) were written in a chat message with trade-offs and a recommendation; the user chose A. Each design section's text was in chat before its approval question; the user approved Section 1 and Section 2.

## Design

### 1. The code change

In `run_products`, in the tenant session that loads the seed (the one opened just before `key_map` is filled), before the seed's `select`:

```python
s.execute(
    delete(m.KeywordSearch).where(
        m.KeywordSearch.brand_id == brand_id,
        m.KeywordSearch.searched_at <= fresh_after,
    )
)
```

- `<=` is the exact complement of the readers' `searched_at > fresh_after`: a row is either readable or deleted, never both.
- It deletes every row of this brand past `SEARCH_TTL_DAYS`, whatever its spelling, error or parse version. Other brands' rows and fresh rows are not touched.
- It runs once per run, before any model call, in a short session that commits on exit; no transaction is open during a model call. A run that fails later still leaves its stale rows deleted, which is harmless.
- `delete` is imported from `sqlalchemy` (the import line today is `from sqlalchemy import func, select, update`).
- The `# ponytail:` comment above `key_map`: "rows under an old spelling stay once stale" is replaced by a note that stale rows are deleted at run start, and that a fresh row under a losing spelling stays until it goes stale (it is not used meanwhile, since the seed keeps the newest current spelling).
- The `run_products` docstring gains one clause: the run first deletes the brand's stale `keyword_search` rows.
- Unchanged: the job's summary string, the seed, the per-batch lookup, the upsert, `SEARCH_TTL_DAYS`, the `clear` route, the API, the web app. No migration.

### 2. Tests, docs, live check

Tests, in tests/integration/test_products_run.py:
- New `test_a_run_deletes_the_brands_stale_rows`: one product (`_seed`) voting `keywords=["kid sandal"]`; rows: a fresh "kids sandals" row (1 day old, `CACHED_TITLE`), a stale "kid sandals" row (8 days, another spelling of the same key), a stale "boys sandal" row (8 days, a keyword no product uses), and a stale "kids sandals" row (8 days) for a second brand in the same org (`other = make_brand(org, "Paragon")`, `_fresh_row(owner, org, other, [CACHED_TITLE], days=8)`). `_run` returns every brand's rows, so the check splits them by brand. Expected: this brand's rows are exactly "kids sandals"; the second brand's stale row is still there; `rows[0].keyword == "kids sandals"`; `engine.prompts == []`.
- Changed `test_a_stale_row_spelling_is_not_adopted`: `assert len(searches) == 2` becomes a check that the only row left is the new "kid sandal" row (the stale "kids sandals" row is deleted). Its other asserts are unchanged.
- Red: on main's code the new test fails (the stale rows remain), and so does the changed test. Green: both pass with the change. Verified on scratch copies by the plan.
- Copy: the new test's names, fixture values and comments are checked against `FORBIDDEN` in tests/unit/test_recommend_copy.py.

Docs: docs/findings-slice29.md; dated updates, originals kept, under: the open "Stale duplicate `keyword_search` rows" item in docs/findings-slice27.md §3 and in docs/findings-slice28.md §3's "still open" list (fixed in code by slice 29); docs/findings-slice28.md §3's Out of scope line "Deleting old-spelling `keyword_search` rows in code"; the docs/findings-slice24.md §3 ceiling "Rows under an old spelling stay in the table once stale; nothing deletes them" and its Out of scope line "Deleting stale duplicate rows."; README rows for the spec, the plan and the findings.

Live check: none in this slice. No dev row is stale until 2026-10-06 13:10 UTC (18:40 IST), so a run before then deletes nothing; a run between then and 2026-10-07 09:27 UTC deletes 8 rows (the 7 plural keywords and "navy flip flops") and re-searches 7 keywords (about 7 × 38,000 + 4 × 1,650 = 272,600 micros, about $0.27: about 38,000 per grounded search with its parse call, and about 1,650 per flash-lite call, of which a batch of up to 20 products makes 4, 3 keyword samples and 1 rewrite; the slice 24 dev re-check, job a53737aa, cost 6,407 micros with no search, docs/findings-slice24.md §2; the slice 21 dev re-check, job f9de4eb9, cost 310,292 micros for 8 searches, about 37,960 each after its 4 flash-lite calls, docs/findings-slice21.md §2); a run after that deletes all 9 and re-searches 8 (about 310,600 micros, about $0.31).

Correction to the Section 2 chat text (2026-10-01): it said a run after 2026-10-06 13:10 UTC "would delete 8 rows but also re-search 8 keywords"; until "mens flip flops" goes stale at 2026-10-07 09:27 UTC it re-searches 7. The choice (no live check in this slice) does not depend on it.

Correction to the Section 2 chat text's cost (2026-10-01): it said "about 8 × 38,000 plus about 16 × 1,650 micros, roughly $0.33"; the flash-lite calls are 4 per batch, not 2 per keyword (found by the spec review of 2a24492, R1), so the costs are as above. A check is a separate, later decision with its own approval.

Gates: both, run by the controller before the finishing menu.

## Rulings

- **R1: the spec review's six points were applied.** Decided: name docs/findings-slice28.md §3 (both lines) and docs/findings-slice24.md's Out of scope line in the docs list; "no run removes" for "stays for good"; "not used … newest current spelling" in the planned comment; the second brand's setup and a by-brand check in the new test; the corrected live-check cost with its source. Found by the spec review of 2a24492. Why: accuracy and completeness; no design change. Cost if wrong: none. Named in chat when made.
- **R2: the spec re-review's minor point was applied.** Decided: cite job f9de4eb9 for the 38,000-per-search figure. Found by the re-review of 1d23c56. Why: R1 named only the flash-lite figure's source. Cost if wrong: none. Named in chat when made.
- **R3: the plan review's two minor points were applied.** Decided: in the plan, the seed comment's last line is joined (no one-word `# start;` line), and Task 2 places the findings-slice27 update as the last sub-bullet of its item, after the quoted cleanup rulings. Found by the plan review of 3878067. Why: tidiness and a clear placement; no design change. Cost if wrong: none. Named in chat when made.
- **R4: the plan's rulings step gives no fixed ruling range.** Decided: Task 2 Step 4 adds only ledger rulings the spec does not already hold, matched by R-number (commit 41c6880). Found by the plan re-review of 63a93fa. Why: its fixed range ("holds R1–R2") had gone stale when R3 was added. Cost if wrong: none. Named in chat when made.
- **R5: an added ruling ends as the ledger records it.** Decided: Task 2 Step 4 ends each added ruling as the ledger records it, usually "Named in chat when made." (commit 38a732c); applied without a further re-review, by the user's choice (option 1). Found by the plan re-review of 41c6880. Why: the change was one phrase in a docs step, applied without re-review by the user's choice. Cost if wrong: an unreviewed one-phrase change to a docs step. Named in chat when made.
- **R6: commit b15aaaf was accepted after a Write refusal.** Decided: accept commit b15aaaf although the Task 2 implementer continued after a Write refusal instead of reporting BLOCKED. Found by the Task 2 implementer's report (its concern 1). Why: it used the Edit tool the dispatch named, it disclosed the refusal, and the content still goes through the Task 2 review; the user chose this (option 1) when asked. Cost if wrong: a refusal handled without stopping first. Named in chat when made.
- **R7: the one fix wave completes the docs.** Decided: the one fix wave fixes both Important findings and R5's Why, quotes the Task 2 and Final deferred lines and the triage in findings §3, adds final-review and fix-wave bullets to the plan, puts R6–R8 in the spec and findings §3, and sets the README range to R1–R8; the fix wave's re-review result goes into the post-merge docs commit. Found by the final review of 13d54fe..b15aaaf. Why: the final review asked for these before merge, and the controller does not commit fixes. Cost if wrong: the re-review result is recorded only after merge. Named in chat when made.
- **R8: three minors stay deferred.** Decided: leave the docstring clause's position (products.py:999-1000), the "readable or deleted" wording in docs/findings-slice29.md §1, and the Task 1 cutoff-test minor as they are. Found by the Task 1 review and the final review; triaged by the final review. Why: cosmetic, matching the spec, and out of scope respectively, per the final review's triage. Cost if wrong: two small wording points and an untested boundary stay. Named in chat when made.
  - Note (2026-10-01, after merge, R9): the "Found by" text of R6–R8 is derived, not ledger text: R6 from the ledger's Task 2 concern (1), R7 from the final review, R8 from the Task 1 review and the final review.
- **R9: the fix wave's re-review minors were parked for the post-merge docs commit.** Decided: no second fix wave; in the post-merge docs commit, the stray "(R7)" on the plan's commit-table clause is corrected by a dated note, and the derivation of R6–R8's "Found by" text is recorded. Found by the scoped re-review of b15aaaf..1d11cb5. Why: the process allows one fix wave, and the controller does not fix findings on the branch. Cost if wrong: an overstated citation and an unstated derivation until the post-merge docs commit. Named in chat when made; recorded here after merge.
- **R10: the post-merge docs commit gets one review only.** Decided: this commit records the re-review result, R9 and R10, and gets one review; anything that review finds goes into the PR description, not another commit. Found by the controller after the slice 28 post-merge loop. Why: to avoid a loop that regenerates a ruling per round. Cost if wrong: a last finding lives in the PR description rather than the docs. Named in chat when made; recorded here after merge.

## Out of scope

- A test of a row exactly at the cutoff (`searched_at == fresh_after`): the tests run through the worker, which does not take `now`.
- Deleting fresh rows under a losing spelling (approach C).
- Any change to the seed, the lookup, the upsert, `SEARCH_TTL_DAYS`, the `clear` route, the job summary, or the schema.
- The live check (§2).
