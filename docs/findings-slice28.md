# Slice 28 findings: tests for the slice 24 seed

## 1. What was built

Three seed cases that docs/findings-slice24.md §3 (Untested) listed, carried forward through docs/findings-slice27.md §3, are now pinned by integration tests. Tests only: no production file changed, including packages/core/bsi_core/products.py and the `# ponytail:` comment above `key_map`; `test_an_error_search_is_not_reused` is unchanged.

**Helper** (`tests/integration/test_products_run.py`, line 413): `_fresh_row(owner, org, bid, titles, days=1)` becomes `_fresh_row(owner, org, bid, titles, days=1, keyword="kids sandals", error=None)`. The row's `keyword` and `query` (`products.search_query(keyword)`) come from `keyword`, and the row gets `error=error`. The defaults keep the existing callers' rows unchanged.

**Tests**, after `test_a_row_the_lookup_rejects_is_not_seeded`; each seeds one product ("Walkaroo Boys Sandal 0"):
- `test_an_error_row_is_not_seeded` (line 514): a fresh "kids sandals" row with titles `[]` and error "429 quota"; the vote is `["kid sandal"]`. Expected: `rows[0].keyword == "kid sandal"`, one search for "kid sandal", 2 `keyword_search` rows. Pins the seed's own `error.is_(None)` filter.
- `test_the_newest_cached_spelling_wins` (line 527): two fresh valid rows sharing the key "kid sandal", "kids sandals" 1 day old and "kid sandals" 2 days old; the vote is `["kid sandal"]`. Expected: `rows[0].keyword == "kids sandals"`, no search, 2 rows. Pins `searched_at.desc()`.
- `test_a_non_first_keyword_adopts_a_cached_spelling` (line 540): a fresh "kids sandals" row; the vote is `["boys sandals", "kid sandal"]`. Expected: `rows[0].keywords == ["boys sandals", "kids sandals"]`, `rows[0].keyword == "boys sandals"`, one search for "boys sandals", 2 rows. Pins the seed's use for every keyword, not only the first.

Results, as the Task 1 report records them:
- Step 3 (green, the whole edited file): `33 passed in 25.26s`.
- Step 5 (red, one scratch copy of `bsi_core` per mutation, run with `-k` for the three tests): m1 (the seed query's `error.is_(None)` removed) `1 failed, 2 passed, 30 deselected`, failing only `test_an_error_row_is_not_seeded`; m2 (`.desc()` to `.asc()`) `1 failed, 2 passed, 30 deselected`, failing only `test_the_newest_cached_spelling_wins`; m3 (only the first keyword through `key_map`) `1 failed, 2 passed, 30 deselected`, failing only `test_a_non_first_keyword_adopts_a_cached_spelling`. Green on main's code (`PYTHONPATH=.`): `3 passed, 30 deselected`.
- Step 6 (backend gate, from `gate-task1.txt`; the exit code is the `gate exit 0` the step printed): ruff format "169 files left unchanged"; ruff check "All checks passed!"; ruff format --check "169 files already formatted"; mypy "Success: no issues found in 29 source files"; pytest "1552 passed, 2 deselected, 2 warnings" (the known third-party warnings: `StarletteDeprecationWarning` from fastapi/testclient.py:1 and the anyio `BlockingPortal` `DeprecationWarning` from starlette/testclient.py:53); `bsi_core.metrics` coverage 100% ("Required test coverage of 100% reached. Total coverage: 100.00%").

**Commits** (`git log --oneline --reverse main..HEAD`, oldest first):

| Commit | Subject |
|---|---|
| 5bccb92 | docs: slice 28 spec, tests for the slice 24 seed |
| d86f733 | docs: slice 28 spec review fixes |
| 1f74c2e | docs: slice 28 spec, copy folder wording |
| 814ce16 | docs: slice 28 plan |
| 1040504 | docs: slice 28 plan review fixes |
| b30923f | docs: slice 28 plan re-review fixes |
| 50a3649 | test: pin the slice 24 seed's error filter, order and non-first keywords |
| 0b4ff59 | docs: slice 28 findings, index and notes |
| 780b7d1 | docs: slice 28 final review fixes |

## 2. Live check on dev

None: the slice adds tests only and changes no behaviour, so there is no spend and no dev write (spec §2).

## 3. Deferred and untested

From the task reviews (ledger lines tagged `minor (deferred)`):
- "Task 1: minor (deferred): tests/integration/test_products_run.py:537 combines two checks in one assert (`assert engine.prompts == [] and len(searches) == 2`); a failure will not show which half failed; the sibling tests use separate asserts; the brief mandates this text verbatim"
  - Correction (from the final review; the ledger line stays as the record, R9): the file already joins checks with `and` at lines 264, 293, 459, 484 and 694 (484 in the same seed group), so not all sibling tests use separate asserts.
- "Task 2: minor (deferred): docs/findings-slice27.md:129, the new update ends "(R1)" (plan-mandated text); that file also holds slice 27's own R1 and the cleanup spec's quoted R1, so the bare "(R1)" is ambiguous; suggested "(slice 28 spec, R1)""
  - Fixed in the fix wave (R7). The update is at line 138 of that file.
- "Task 2: minor (deferred): docs/findings-slice28.md:58 paraphrases the stale-rows carried-forward item ("no run removes them" for "nothing deletes them") and gives "the one-off dev cleanup of 2026-10-01" without the IST zone, where the source reads "2026-10-01 IST (2026-09-30 about 20:20 UTC)""
  - Note (2026-10-01, after merge, R11): this item moved; at merge (a4f1d3f) it was at line 78, in §3 under "Carried forward".
- "Task 2: minor (deferred): docs/findings-slice28.md:9, "each seeds one product" clashes with the doc's term "the seed"; "each creates one product" reads more clearly"

From the final whole-branch review (ledger lines tagged `minor (deferred)`):
- "Final: minor (deferred): findings-slice28 §3 and the plan's changes section are incomplete until a final docs commit: §3 quotes only Task 1's deferred minor (the three Task 2 minors were ledgered after 0b4ff59), and the changes section has no final-review or fix-wave bullet; ledger line "post-merge docs commit" should read pre-merge for these"
  - Fixed in the fix wave (R10).
  - Note (2026-10-01, after merge, R11): fixed before merge, in 780b7d1.
- "Final: minor (deferred): Task 1's deferred minor says "the sibling tests use separate asserts", but test_products_run.py already joins checks with `and` at lines 264, 293, 459, 484 and 694 (484 in the same seed group); no code fix"
  - No fix; the correction is noted beside the Task 1 minor above (R9).

The final review's triage, as recorded: "Final triage of the deferred minors: Task 1 :537 joined assert — leave deferred; Task 2 findings-slice27.md:129 bare "(R1)" — fix before merge ("(slice 28 spec, R1)"); Task 2 findings-slice28.md:58 paraphrase/date — leave deferred; Task 2 findings-slice28.md:9 "seeds" — leave deferred"

From the fix wave's scoped re-review (recorded after merge, R10 and R11). The result, as recorded: "Fix wave re-review (a2ecc422a355defc4, 0b4ff59..780b7d1): "All findings addressed: Yes"; new breakage 2 Minor, 0 Critical, 0 Important; 2 out-of-scope observations."
- "Fix wave: parked — findings-slice28.md:44-45 and R8 at :67 quote the ledger pointer "findings-slice28.md:58" for the stale-rows item, now at :78, with no note giving the new line (unlike :129→138 at :43) — Ruling: R11 — there is no second fix wave; record the new line in the post-merge docs commit — cost if wrong: one stale line pointer until then"
  - Note (2026-10-01, after merge, R11): at merge (a4f1d3f) the stale-rows item was at line 78 of this file, in §3 under "Carried forward"; R8 names it by section.
- "Fix wave: parked — plan :235 still quotes "go into the post-merge docs commit" and findings :49 says only "Fixed in the fix wave (R10)", with no note that the final-review and fix-wave bullets landed before merge — Ruling: R11 — same: note it in the post-merge docs commit — cost if wrong: a reader may think those bullets came after merge"
  - Note (2026-10-01, after merge, R11): the plan's final-review and fix-wave bullets and this section's Task 2 and Final quotes landed before merge, in 780b7d1; after merge came this block, R11–R14, the §1 row's hash (780b7d1), the dated notes marked "after merge", the plan's "(780b7d1)" fill, its Task 2 note and its "Fix-wave re-review" bullet, and the README ruling range.
- "Fix wave: minor (deferred): out of scope: the R9 correction at findings-slice28.md:41 lists five `and` asserts (264, 293, 459, 484, 694); the file has more (e.g. 213, 226, 272, 292, 318, 364, 442, 706); accurate, not complete"
- "Fix wave: minor (deferred): out of scope: spec R7/R8 wording departs slightly from ledger lines 36-37 (R7 says §3 where the ledger says :129; R8 names spots by section, not :58/:9); disclosed in the fix-wave ledger line; R7–R10 in findings §3 have no "ledger line, as recorded" quote beside them, unlike R6"

Parked: none. The ledger has no parked lines.
  - Correction (2026-10-01, after merge): the fix wave's re-review led to the two parked lines quoted above.

Rulings (spec `## Rulings`, quoted in full):
- **R1: the seed's keyword tie-break is out of scope.** Decided: no test for two rows with the same `searched_at`, where the seed's second sort key, `keyword`, picks the spelling. Found by the controller writing the spec (it was not raised in chat). Why: findings-slice24 does not list it, and all real rows written in one run share one `searched_at` only when they are different keys. Cost if wrong: the tie-break stays unpinned. Named in chat when made.
  - Correction to R1's Why (2026-10-01): findings-slice24 does list it (§3, the Task 1 minor: "dropping `.desc()` or the secondary sort key would fail no test"), found by the spec review of 5bccb92. The reason that holds: `run_products` cannot produce the tie, since one run gives every search the same `searched_at` but writes one spelling per key, and separate runs get different times; only a hand-inserted row can tie. The choice was asked again with the corrected fact, with two other options (a fourth test pinned by a `keyword.desc()` mutation; ordering the seed by `searched_at` only, a production change), and the user kept it out of scope. The Task 1 minor gets a dated update: `.desc()` is pinned, the secondary key is not.
- **R2: the spec review's three minor points were applied.** Decided: give mutation 3's exact replacement line, spell out the red-check setup, and add the main commit anchor and the copy line. Found by the spec review of 5bccb92. Why: a plan writer would otherwise guess; no design change. Cost if wrong: none. Named in chat when made.
- **R3: the spec re-review's minor point was applied.** Decided: say `<copy folder>` is the directory that contains the copied `bsi_core/`. Found by the re-review of d86f733. Why: it could be read as the copy itself. Cost if wrong: none. Named in chat when made.
- **R4: the plan review's seven minor points were applied.** Decided: in the plan, list m3's two-line split and the exit-code step as departures, add the deselected counts, record the gate's exit code from the tool result, give the insertion point, quote the findings-slice27 heading exactly, stop on a changed Step 3 count, and give each findings-slice24 sub-bullet its own update. Found by the plan review of 814ce16. Why: wording and clarity; no design change. Cost if wrong: none. Named in chat when made.
- **R5: the plan re-review's three points were applied.** Decided: Task 2 Step 4 adds new rulings after the last one (R4's fix had left "after R3"); the self-review's red counts include "30 deselected"; Task 1 Step 6 prints the gate's exit code with `echo "gate exit $?"` after the redirect. Found by the re-review of 1040504. Why: the first was a regression from R4's fix, the others record what a run prints. Cost if wrong: none. Named in chat when made.
- **R6: the plan's "Verified before committing" red counts were left unchanged.** Decided: the plan's record "1 failed, 2 passed, 30 deselected" stays as written. Found by the plan re-review of b30923f, which asked whether it was observed or inferred; decided before execution. Why: the controller's verification run printed exactly that for m1, m2 and m3 (observed). Cost if wrong: one overstated line in the plan's self-review. Named in chat when made.
  - The ledger line, as recorded: "Ruling: R6 — the plan re-review of b30923f asked whether the plan's "Verified before committing" record "1 failed, 2 passed, 30 deselected" was observed or inferred; it is left unchanged — the controller's verification run printed exactly that for m1, m2 and m3 (observed) — cost if wrong: one overstated line in the plan's self-review. Named in chat when made (before execution)."
- **R7: the bare "(R1)" in docs/findings-slice27.md was made "(slice 28 spec, R1)".** Decided: change the end of the slice 28 update in docs/findings-slice27.md §3 to "(slice 28 spec, R1)", departing from the plan's mandated Task 2 Step 2 text. Found by the Task 2 review (a deferred minor), which the final review's triage marked fix before merge. Why: that file already holds slice 27's R1 and the cleanup spec's quoted R1, the ambiguity cleanup ruling R13 was made to fix. Cost if wrong: one departure from plan text. Named in chat when made.
- **R8: three deferred minors stay deferred.** Decided: leave the joined assert at tests/integration/test_products_run.py:537, the paraphrase and date in docs/findings-slice28.md §3's stale-rows item, and "each seeds one product" in its §1 as they are. Found by the Task 1 and Task 2 reviews; triaged by the final review. Why: per the final review's triage: house style and a listed plan departure, accurate wording that points to its source, and a literal description of `_seed`. Cost if wrong: three small wording or style points stay. Named in chat when made.
- **R9: Task 1's ledger minor keeps its "separate asserts" claim, corrected beside it.** Decided: no fix for the final review's minor that Task 1's ledger minor wrongly says "the sibling tests use separate asserts"; the ledger line stays as the record, and docs/findings-slice28.md §3 quotes the final review's correction next to it. Found by the final review. Why: the ledger is a record, not a doc to rewrite. Cost if wrong: a slightly wrong claim stays in the quoted ledger line, corrected beside it. Named in chat when made.
- **R10: the one fix wave also completes the docs.** Decided: the fix wave quotes every Task 2 and Final `minor (deferred)` line in findings §3, gives the plan's changes section bullets for the Task 2 review, the final review and the fix wave, adds R7–R10 to this spec and findings §3, and updates the README spec row's ruling range; the fix wave's re-review result goes into the post-merge docs commit. Found by the final review (findings §3 and the plan's changes section were incomplete). Why: the final review asked for these before merge, and a controller commit is not allowed. Cost if wrong: the re-review result is recorded only after merge. Named in chat when made.
- **R11: the fix wave's re-review minors are parked for the post-merge docs commit.** Decided: no second fix wave; the two new minors the re-review found in the fix diff (the ledger pointer "findings-slice28.md:58" for the stale-rows item, which moved; and no note that the final-review and fix-wave bullets landed before merge) are recorded in the post-merge docs commit. Found by the scoped re-review of 0b4ff59..780b7d1. Why: the process allows one fix wave, and the controller does not fix findings on the branch. Cost if wrong: a stale line pointer and a missing note until the post-merge docs commit. Named in chat when made; recorded here after merge.
- **R12: the post-merge docs review's points 1, 3 and 4 were applied; point 2 was not.** Decided: fill the plan's stale "(this commit)" with 780b7d1, correct the list of what came after merge, and add notes in place beside the moved pointer and the "Fixed in the fix wave" line and in the plan's Task 2 bullet; keep R11's "Named in chat when made", since the controller named R11 in chat when it parked the two minors. Found by the review of 227470f. Why: accuracy and in-place notes, as the earlier :129→138 note did. Cost if wrong: none. Named in chat when made.
- **R13: the post-merge re-review's three minor points were applied.** Decided: complete the list of what came after merge (without "only"), restore the original "Fixed in the fix wave (R10)." line with a separate dated note, date the "after merge" notes, and record the post-merge review, R11's chat naming, R12 and R13 in the ledger. Found by the re-review of f19f2e9. Why: accuracy and the dated-note convention. Cost if wrong: none. Named in chat when made.
- **R14: the post-merge review results are quoted in the plan.** Decided: quote the three post-merge review result lines from the ledger in the plan's re-review bullet. Found by the re-review of b1a2d54. Why: the changes section quotes review results as recorded. Cost if wrong: none. Named in chat when made.

Out of scope (spec):
- Any change to the seed, the cache lookup or `products.py`.
- The seed's keyword tie-break between two rows with the same `searched_at` (R1).
- Rewriting `test_an_error_search_is_not_reused` to use `_fresh_row`.
- Deleting old-spelling `keyword_search` rows in code (the open item in docs/findings-slice27.md §3).
  - Update 2026-10-01 (slice 29): done in slice 29.

Carried forward from docs/findings-slice27.md §3 ("Carried forward from docs/findings-slice26.md §4 (still open):"), still open:
- Stale duplicate `keyword_search` rows: rows under an old spelling stay in the table; no run removes them (docs/findings-slice24.md §3, ceilings and Out of scope). `DELETE /v1/brands/{id}/products` deletes a brand's rows, and the one-off dev cleanup of 2026-10-01 removed 11; the code is unchanged, so later runs can leave old spellings behind again (docs/findings-slice27.md §3 has the correction and the update in full).
  - Update 2026-10-01 (slice 29): fixed in code by slice 29.
- The judge-agreement question, waiting on the user.

The third carried-forward item, "The slice 24 seed's untested cases", is pinned by this slice (§1), except the secondary sort key below.

Untested: the seed's secondary sort key (`keyword`) for two rows with the same `searched_at` (R1).
