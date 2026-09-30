# Slice 26 findings: a removed repeat no longer counts as an adjustment

## 1. What was built

Slice 25's live check stored the rewrite call's raw titles: all 10 ended with the original title's type word or its plural after a form of it earlier in the title, `rule_check` removed the repeat each time, and every status was `adjusted` (docs/findings-slice25.md §2). The rewrite prompt is unchanged; only `rule_check`'s status changes (spec §1). No migration, API, web, CSV, prompt or copy change.

**Helper.** `_drop_repeats(words: Sequence[str]) -> list[str]` (`packages/core/bsi_core/products.py`, line 685), directly before `rule_check`, holds the loop that used to be inline in `rule_check`: it keeps each word unless its `fold_set` stems overlap an earlier kept word's stems (punctuation-only words are kept).

**Status rule** (`rule_check`, line 699):
- The inline loop is now `title = " ".join(_strip_connectors(_drop_repeats(title.split())))` (line 732).
- The last return computes `plain = " ".join(_drop_repeats(suggestion.split()))` (line 741) and returns `"pass"` when `title in (suggestion, plain)`, else `"adjusted"`. A lost original word still gives `review`.
- The docstring's Status sentence now reads: "review" if the final title lost any of the original's words, else "pass" if it equals the suggestion or the suggestion with only its repeats removed (_drop_repeats), else "adjusted".

**Tests** (`tests/unit/test_products.py`):
- `test_rule_check_removes_repeated_tokens` (line 260): the expected status for `rule_check("Walkaroo Kids Shoes", "Walkaroo Kids Shoes Shoes", BRAND)` is now `"pass"` (was `"adjusted"`).
- `test_rule_check_drops_a_word_that_repeats_an_earlier_token` (line 441): the first case ("Walkaroo Kids-Sandal Sandal") now expects `"pass"`; the Red Tape case is unchanged.
- New, `test_rule_check_does_not_count_a_removed_repeat` (line 455): the LC-01 pattern gives `("BSOAgentTestBrand Blue Kid Sandals Boys", "pass", [])`; the LC-05 pattern gives `("BSOAgentTestBrand Navy Mens Flip Flops", "pass", [])`; a repeat plus an unbacked word gives `("Walkaroo Kids Shoes", "adjusted", [])`; a repeat plus a lost word gives `("Walkaroo Kids Sandal", "review", ["boys"])`.
- TDD evidence, as the Task 1 report records it: RED 3 failed, 89 deselected, each on `'adjusted' != 'pass'` (lines 261, 442, 457); GREEN 3 passed, 89 deselected. The product unit and integration files: 122 passed.
- Backend gate (Task 1, 9a0a537), from `gate-task1.txt` (the whole chain redirected): ruff format "169 files left unchanged"; ruff check "All checks passed!"; ruff format --check "169 files already formatted"; mypy "Success: no issues found in 29 source files"; pytest "1545 passed, 2 deselected, 2 warnings" (the warnings: `StarletteDeprecationWarning` from fastapi/testclient.py:1, using `httpx` with `starlette.testclient`; `DeprecationWarning` from starlette/testclient.py:53, the `anyio.abc.BlockingPortal` alias); `bsi_core.metrics` coverage 100% ("Required test coverage of 100% reached. Total coverage: 100.00%"). 1545 is main's 1544 plus the new test (ledger).

**Commits** (`git log --oneline --reverse main..HEAD`, oldest first):

| Commit | Subject |
|---|---|
| a4037ab | docs: slice 26 design spec |
| b104b69 | docs: slice 26 spec: the probe reads category too |
| 40895d6 | docs: slice 26 spec review fixes |
| 6376dc9 | docs: slice 26 spec: citation and repeat definition |
| 7f69544 | docs: slice 26 spec: probe 1 result and approach C |
| f16ff8c | docs: slice 26 spec review fixes (approach C) |
| ab7265c | docs: slice 26 spec: honest status after probe 2 |
| da64f08 | docs: slice 26 spec review fixes (status design) |
| 86d9636 | docs: slice 26 implementation plan |
| f4427be | docs: slice 26 plan review fixes |
| f7d215f | docs: slice 26 plan: list the carried-forward items as a departure |
| 9a0a537 | feat(products): a removed repeat is not an adjustment |
| e8b2589 | docs: slice 26 findings, index and notes |
| ce2ef77 | docs: slice 26 findings: final-review minors |
| 7a55220 | docs: slice 26 findings: section 4 lead-in |
| d241a8e | docs: slice 26 process audit corrections |
| 92c3efc | docs: slice 26 audit corrections: review fixes |
| (this commit) | docs: slice 26 live check |

## 2. Probes

Two probes of a prompt change ran on 2026-09-30, each with the user's OK, before anything was built (spec Appendix A2). A scratch script outside the repo read the brand and dev's 10 products with read-only queries, called `judge.generate(prompt, RewriteSet, 0.0)`, and ran each raw title through `rule_check` as `run_products` would. No database writes and no job.

- **Probe 1** (6 calls, 11,211 micros, estimate about 10,000; the model reported `gemini-3.5-flash-lite`): 3 calls with the current prompt, 3 with the first-proposed keep-rule sentence. **Failed.** Baseline: singular/plural repeats in 10, 9 and 10 of 10 titles, so the probe was conclusive. The new sentence: 10 of 10 titles repeated in call 4 (the model wrote the original type word first and appended the keyword, for example "BSOAgentTestBrand Blue Kid Sandal Boys Kids Sandals"); 0 of 10 in calls 5 and 6, but call 6 gave LC-07 `review` (the raw title "BSOAgentTestBrand Beige Women Slippers" dropped "Casual"). Non-sandal products behaved like the sandal products. Temperature 0.0 did not make the calls repeatable.
- **Probe 2** (approach C: the Appendix A1 sentence plus a per-product `swaps` list from a scratch copy of `form_swaps`; 3 calls, 6,757 micros, estimate about 5,000 to 6,000; the model reported `gemini-3.5-flash-lite`; baseline from probe 1): **Failed.** Call 1: no repeats, but LC-06 ("BSOAgentTestBrand Brown Men Sandals") and LC-07 ("BSOAgentTestBrand Beige Slippers for Women") were `review`, both dropping "Casual". Calls 2 and 3: LC-01 and LC-02 repeated "kids kid" (the keyword and the missing word, for example "BSOAgentTestBrand Blue Boys Sandals kids kid") and were `adjusted`; the other 8 were `pass`. The model also appended lower-case words ("kids", "men", "footbed").

Why the prompt route was not built (spec, decisions list): after probe 2 failed, the goal was asked again, because the fact behind "clean raw rewrite" (that a prompt change could reach it reliably) had turned out wrong. The user chose "Honest status, code only" over one more prompt fix with probe 3, and over stopping the slice. For the repeat scope, the user chose any word removed only because it repeats an earlier word's stem, over singular/plural repeats only (under which LC-05's "Flip Flops Flip Flop" stays `adjusted`).

Probe cost: 11,211 + 6,757 = 17,968 micros. Spend so far is about $10.97 of the $15 cap (spec §3).

## 3. Live check on dev

Run on 2026-09-30 by the controller on main at ef71baf (after PR #48 merged), with the user's OK ("run the live check").

- Pre-check (read-only): dev at migration 0021; no uvicorn, worker or pytest process; 0 queued or running jobs; `keyword_search` had 20 rows, the newest searched 2026-09-30 09:27:13 UTC; 9 prior `product_run` jobs totalling 1,650,561 micros; all 10 products had status `adjusted` (from slice 25's run).
- The API was started in the background. `POST /v1/brands/34db213a-f484-4991-a969-c52cfa5e1c10/products/run` returned HTTP 202 and queued job `375e6521-2071-4218-b6a8-c5fc53c340ef`. The API was then stopped (background task exit 144, as expected); exactly one job was queued. `process_job` ran once and returned `True`; the worker loop was not started.
- Job `375e6521`: status done, error null, `cost_micros = 6,545` (the spec's estimate was about 6,600), created 17:16:11, started 17:16:20 UTC.
- No grounded search ran: `keyword_search` still has 20 rows and its newest `searched_at` is still 2026-09-30 09:27:13.
- Writes observed: the job row, the 10 product rows, and `api_key.last_used_at` = 17:16:11 UTC. Afterwards: 0 queued or running jobs, no uvicorn or worker process; 10 `product_run` jobs totalling 1,657,106 micros. Spend is about $10.98 of the $15 cap ($10.9710 + $0.0065 = $10.9775).

**Per product** (observed by read-only queries after the job):

| Product | Keyword | Raw title | Suggested title | Status | Dropped |
|---|---|---|---|---|---|
| LC-01 | kids sandals | BSOAgentTestBrand Blue Kid Sandals Boys Sandal | BSOAgentTestBrand Blue Kid Sandals Boys | pass | (none) |
| LC-02 | kids sandals | BSOAgentTestBrand Pink Kid Sandals Girls Sandal | BSOAgentTestBrand Pink Kid Sandals Girls | pass | (none) |
| LC-03 | kids shoes | BSOAgentTestBrand Black Kids Sports Shoe | (same) | pass | (none) |
| LC-04 | kids slippers | BSOAgentTestBrand Grey Kids Slipper | (same) | pass | (none) |
| LC-05 | mens flip flops | BSOAgentTestBrand Navy Men Flip Flop | (same) | pass | (none) |
| LC-06 | men sandals | BSOAgentTestBrand Brown Men Casual Sandal | (same) | pass | (none) |
| LC-07 | women slippers | BSOAgentTestBrand Beige Women Casual Slipper | (same) | pass | (none) |
| LC-08 | men shoes | BSOAgentTestBrand Grey Men Sports Shoe | (same) | pass | (none) |
| LC-09 | kids shoes | BSOAgentTestBrand Black Kids Boys School Shoe | (same) | pass | (none) |
| LC-10 | women sandals | BSOAgentTestBrand Tan Women Footbed Sandal | (same) | pass | (none) |

All 10 keywords are the same as after slice 25's run (docs/findings-slice25.md §2).

What the stored values show:
- Observed: LC-01 and LC-02's raw titles repeat the type word ("Sandals" … "Sandal"); each suggested title is the raw title without the final "Sandal", and the status is `pass`. These two are the new rule at work: under slice 25's rule the same pair gave `adjusted` (docs/findings-slice25.md §2, the same raw titles).
- Observed: LC-03 to LC-10's raw titles have no repeat and equal their suggested titles, so they are `pass` under either rule. In this run the rewrite kept each title's own singular type word ("Sports Shoe", "Flip Flop") instead of adding the keyword's plural, unlike slice 25's run, where all 10 raw titles repeated it.
- *Inferred*: the rewrite call's output varies between runs (as in both probes), so how many products show the repeat, and so how many depend on the new rule, varies too.


## 4. Deferred and untested

From the task reviews and the final review (ledger lines tagged `minor (deferred)`):
- "Task 1: minor (deferred): no test pins the spacing-only case (a suggestion that differs only in spacing now gives pass because plain is re-joined with single spaces; spec §1 states it)."
- "Task 1: minor (deferred): a suggestion whose only faults are a repeat and a trailing connector still gives adjusted (plain is not connector-stripped; spec §1 states the connector strip counts)."
- "Task 2: minor (deferred): findings-slice26 §2's "Why the prompt route was not built" paragraph copies the spec's decisions list almost word for word without quotation marks."
- "Task 2: minor (deferred): the plan's Task 1 changes bullet opens "Task 1 went as written" and then lists a controller process note (the pre-emptive report stub)."
- "Task 2: minor (deferred): the README spec row describes pass as "the only change to the suggestion is removing words that repeat an earlier word's stem" and leaves out the spacing-only case."
- "Final review: minor (deferred): no test pins brand prepend plus a repeat, or trim plus a repeat, giving adjusted (title != plain there, but no assertion checks the plain comparison against a prepended brand)."
- "Final review: minor (deferred): pass also covers a rewrite that keeps the original singular and drops the keyword's plural (probe 1 call 4's pattern "Kid Sandal Boys Kids Sandals" -> "Kid Sandal Boys"), since _drop_repeats keeps the first form; follows from the approved "any repeat" scope; the spec does not spell it out; note it in the live-check read-back."
- "Final review: minor (deferred): when a product has no rewrite item, suggestion is the original title; an original title that itself repeats a stem used to give adjusted and now gives pass; consistent with the rule, not in the spec."

The final review triaged the 5 earlier deferred minors as "keep deferred": "Final review: Ready to merge "With fixes"; 0 Critical, 2 Important, 3 Minor; all 5 earlier deferred minors triaged "keep deferred"."

Parked: none. The ledger has no parked lines.

Rulings: none.

Correction (2026-09-30, after the process audit): the ledger now records one ruling, added after the audit; also in the spec's `## Rulings`:
- **R1: the findings §4 lead-in was fixed by the controller, not deferred.** Decided: after the final fix wave's re-review, the controller changed this section's lead-in to "From the task reviews and the final review" (7a55220) instead of deferring the re-reviewer's out-of-scope observation. Found by the final fix wave's implementer (a concern) and its re-review (an out-of-scope observation). Why: the lead-in under-described the 8 lines under it, and fixing it avoided a ninth deferred line. Cost if wrong: a process deviation (the skill allows one fix wave and no controller fixes); the change is docs wording only and was re-reviewed. The fix was noted in the ledger when made (as a note, not a ruling); it was named as a ruling in chat and in the ledger only after the process audit.

Out of scope (spec):
- Any change to `rewrite_prompt` (Appendix A1 was designed and probed, not built).
- Overlap between the keyword and the missing words (probe 2's "kids kid"), and the model's word dropping and lower-case appends seen in the probes.
- The deferred items in docs/findings-slice25.md §3.

Carried forward from docs/findings-slice25.md §3 (still open):
- Stale duplicate `keyword_search` rows: rows under an old spelling stay in the table; nothing deletes them (docs/findings-slice24.md §3, ceilings and Out of scope).
- The slice 24 seed's untested cases (docs/findings-slice24.md §3, Untested): no test pins the seed's `error.is_(None)` filter on its own; newest-wins between two valid rows that share a key; adoption of a non-first keyword.
- The judge-agreement question, waiting on the user.

## 5. Process audit

On 2026-09-30, after the finishing menu, the user asked "check if you have done all task correctly and follow each step" and then said "fix it". The audit found:
- After the single final fix wave and its re-review, the controller fixed the re-reviewer's out-of-scope observation itself (7a55220) instead of deferring it. Now recorded as ruling R1 (§4 and the spec).
- That fix-or-defer choice was not named as a ruling when made, and the finishing menu said there were no rulings and that every design choice was the user's.
- A consequence the spec review found (a suggestion that differs only in spacing gives `pass`) was written into spec §1 without asking the user. After the audit the user was asked and chose the recommended option, "Yes, pass (Recommended)"; the spec's decisions list records it.
- The user's "go ahead" after the request to review the spec was read as spec approval without a confirming question (the controller said so in chat).
- After the goal changed to the status fix, there was no approaches step (two or three ways with trade-offs); the status design went straight to its sections.
- Caught before any effect and disclosed at the time: a pre-created report stub (deleted before dispatch); an invalid red-step check whose scratch copy shadowed main's code (rerun correctly); a probe 2 draft that imported probe 1's script, whose top level makes six paid model calls (rewritten before it ran).

The controller's process notes in memory were updated with these points. No code changed.
