# Slice 27 findings: keyword words out of the rewrite's missing list, and lost original words restored

## 1. What was built

Two model behaviours from slice 26's probes were open (docs/findings-slice26.md §4, Out of scope): the rewrite writing both "kids" and "kid" when a product's keyword and a missing word share a stem, and the rewrite dropping an original word such as "Casual". Both changes are deterministic code in `packages/core/bsi_core/products.py`; no migration, API, web, CSV or prompt-wording change, and no model call or probe (spec §3).

**Prompt filter.** `_not_in_keyword(p: dict[str, Any]) -> list[str]` (line 943), directly before `rewrite_prompt`, returns the product's `missing` words without those whose `fold_set` stems are in its keyword; the keyword stems come from `_allowed_stems("", [keyword], [])`, which also folds an "-es" keyword word to its singular ("men watches" leaves out "watch"). `rewrite_prompt` (line 951) now passes `[{**p, "missing": _not_in_keyword(p)} for p in products]` to `_product_lines` (line 963), which leaves out an empty value, so a product whose missing words are all in its keyword gets no `"missing"` key. `missing()`, the stored `missing_keywords`, the Missing keywords column, the CSV and `rule_check`'s `allowed` are unchanged.

**Restore.** `_restore(original, words, brand_names) -> list[str]` (line 685), directly before `_drop_repeats`, puts back each original-title word whose tokens `dropped()` reports as lost, right after the first title word sharing a stem with the nearest earlier original word still there (at the start if none). `rule_check` (line 724) calls it right after the R1/R2 fallback and before the repeat step (line 759: `title = " ".join(_restore(original, title.split(), brand_names))`), so a restored word cannot bring back a repeat. The status rules are unchanged in code; a restored title differs from the suggestion, so it is `adjusted` with empty dropped words.

**Docstring** (`rule_check`): gains "an original-title word the suggestion lost is put back (_restore);" before the repeat step, and the Status sentence now begins: "review" if the final title lost any of the original's words (after the restore, only the repeat step or the trim can cut one), else "pass" …

**Tests** (`tests/unit/test_products.py`):
- `test_rule_check_trims_to_150_at_a_word_boundary` (line 291): original "Plain"; now `adjusted` with lost `[]`, and the title is "Plain " plus the start of the suggestion (comment: "The lost "Plain" is restored at the start, then the trim applies.").
- New `test_rule_check_trim_can_still_lose_a_restored_word` (line 303): original "w59 Plain" gives `("review", ["w59", "plain"], 149)` for status, lost and length.
- `test_rule_check_drops_a_word_that_repeats_an_earlier_token` (line 450), the Red Tape case: `("Red Tape Boots Shoes", "adjusted", [])`.
- New `test_rule_check_repeat_step_can_drop_a_restored_hyphenated_word` (line 464): `("Walkaroo Anti Boys Sandal", "review", ["skid"])` (passes on main too; it pins the ceiling).
- New `test_rule_check_restore_does_not_bring_back_a_repeat` (line 474): "Walkaroo Anti-Skid Sandal" and "Walkaroo Casual Sandal Wear", both `adjusted` with `[]`.
- `test_rule_check_does_not_count_a_removed_repeat` (line 485), the repeat-plus-lost-word case: `("Walkaroo Boys Kids Sandal", "adjusted", [])`, comment "A repeat plus a lost word: the word is restored.".
- `test_rule_check_flags_dropped_words_for_review` renamed `test_rule_check_restores_dropped_words` (line 535): `("Brown Mens Casual Sandal Shoes", "adjusted", [])` and `("Navy Men Flip Flop Slipper", "adjusted", [])`.
- `test_rule_check_strips_a_connector_the_trim_leaves_at_the_end` (line 558): the original is "w0", so nothing is restored ahead of the cut.
- New `test_rewrite_prompt_leaves_keyword_words_out_of_missing` (line 594): "kids sandals" with ["kid", "summer"] gives `"missing": ["summer"]`; "men watches" with ["men", "watch", "analog"] gives `"missing": ["analog"]`; missing ["kid"] alone gives no `"missing"` key.

`tests/integration/test_products_run.py`:
- `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` (line 182): suggested title "Walkaroo Boys Kids Summer Sandals", `(rule_check, dropped_words) == ("adjusted", [])`, `raw_title` unchanged; the comment now says the rule check puts "boys" back after "Walkaroo".
- `test_a_failed_search_is_stored_and_the_run_goes_on` (line 650): suggested title "Walkaroo Boys Kids Sandals".

TDD evidence, as the Task 1 report records it: RED (the two product test files, before the code change) 8 failed, 118 passed; GREEN 126 passed.

Backend gate (Task 1, b21919b), from `gate-task1.txt` (the whole chain redirected; the file records no exit code; the ledger records "gate exit 0" and the Task 1 report says the chain "exited 0"): ruff format "169 files left unchanged"; ruff check "All checks passed!"; ruff format --check "169 files already formatted"; mypy "Success: no issues found in 29 source files"; pytest "1549 passed, 2 deselected, 2 warnings" (the warnings: `StarletteDeprecationWarning` from fastapi/testclient.py:1, using `httpx` with `starlette.testclient`; `DeprecationWarning` from starlette/testclient.py:53, the `anyio.abc.BlockingPortal` alias); `bsi_core.metrics` coverage 100% ("Required test coverage of 100% reached. Total coverage: 100.00%").

**Commits** (`git log --oneline --reverse main..HEAD`, oldest first):

| Commit | Subject |
|---|---|
| dc540ed | docs: slice 27 design spec |
| 81bba86 | docs: slice 27 spec review fixes |
| be12ea5 | docs: slice 27 spec: title lengths and the restore line |
| 691b075 | docs: slice 27 implementation plan |
| 31a4683 | docs: slice 27 spec: the repeat step can also lose a restored word |
| b2fe6cb | docs: slice 27 plan review fixes |
| b21919b | feat(products): restore dropped words; keep keyword words out of the rewrite's missing list |
| ae747b5 | docs: slice 27 findings, index and notes |
| (this commit) | docs: slice 27 findings: final-review fixes |

## 2. Live check on dev

Not yet run. The controller runs it after the user approves; results are recorded here then.

## 3. Deferred and untested

From the task reviews (ledger lines tagged `minor (deferred)`):
- "Task 1: minor (deferred): _not_in_keyword calls _allowed_stems("", [keyword], []) only for its -es folding; the empty original and brand arguments make the intent harder to read (the spec approved this reuse)."
- "Task 1: minor (deferred): _restore calls dropped() again although rule_check calls it at the end; negligible cost for titles of a few words."
- "Task 1: minor (deferred): _restore has no direct unit test; it is covered only through rule_check (start insertion, a consecutive run, a hyphenated anchor, a duplicate lost word)."
- "Task 2: minor (deferred): findings-slice27 §1 puts "(line 964)" after `_product_lines`, but the call opens at products.py:963 (964 holds the list comprehension)."
  - Fixed in this fix wave.
- "Task 2: minor (deferred): findings-slice27 §1 attributes "exit 0" to gate-task1.txt, which records no exit code (it comes from the ledger and task-1-report.md)."
  - Fixed in this fix wave.
- "Task 2: minor (deferred): findings-slice27 §3's ceilings leave out spec §2's "Consumers are unchanged in code (...)" sentence and the "dev's original titles are 34 to 44 characters ..." clause, without marking the omission."
- "Task 2: minor (deferred): the Untested bullet for "a lost number or stopword is not restored" does not mention that test_dropped_ignores_stopwords_brand_numbers_and_short_tokens pins the mechanism (dropped() skipping "3" and "for")."
- "Task 2: minor (deferred): the plan's final-review bullet also covers "no fix wave so far" in one bullet; it needs updating after the final review."
  - Fixed in this fix wave.

The final review triaged these 8 deferred minors: "Final review: Ready to merge "With fixes"; 0 Critical, 2 Important, 3 Minor (the same points as three Task 2 deferred minors), no code issues. Triage of the 8 earlier deferred minors: 5 keep deferred; fix before merge: the "(line 964)" reference, the "exit 0" attribution, and the plan's final-review bullet."

Parked: none. The ledger has no parked lines.

Rulings: none.

Ceilings (spec §2, approved):
- A replaced product type ends up as both types, `adjusted`: "Tape Shoes" for "Red Tape Boots" gives "Red Tape Boots Shoes"; "Navy Men Slipper" for "Men Flip Flop Navy" gives "Navy Men Flip Flop Slipper".
- The page, the API and the CSV no longer show which word the model dropped: a restored word shows as `adjusted` with an empty dropped list; only `raw_title` (read with psql, not exposed) shows it. `review` and a non-empty "dropped: …" note appear only when the trim cuts an original word or the repeat step drops a restored hyphenated word.
- Numbers and stopwords are never restored, because `dropped()` skips them: "Walkaroo Sandal" for "Walkaroo Sandal 2 Pack" gives "Walkaroo Sandal Pack"; a lost "for" stays lost.
- The anchor is the first title word sharing a stem with the nearest earlier original word, which can be a function word: "Look with Sandal" for "Sandal with Casual Look" gives "Look with Casual Sandal".
- The repeat step runs after the restore, so a restored hyphenated word whose other half is already earlier in the title is dropped again: "Walkaroo Anti Boys Sandal" for "Walkaroo Boys Anti-Skid Sandal" gives `review` with lost ["skid"] (the same result as on main).
- A restored word adds length, so the trim can cut words the model added at the end (such as the keyword) with status `adjusted` and no flag.

Out of scope (spec):
- Any change to `missing()`, the stored missing list, the UI or the CSV.
- Keeping `review` when the model replaced the product type (the approved ceiling).
- Any rewrite prompt wording change other than the `missing` field's content.
- The deferred items in docs/findings-slice26.md §4.

Carried forward from docs/findings-slice26.md §4 (still open):
- Stale duplicate `keyword_search` rows: rows under an old spelling stay in the table; nothing deletes them (docs/findings-slice24.md §3, ceilings and Out of scope).
- The slice 24 seed's untested cases (docs/findings-slice24.md §3, Untested): no test pins the seed's `error.is_(None)` filter on its own; newest-wins between two valid rows that share a key; adoption of a non-first keyword.
- The judge-agreement question, waiting on the user.

Untested (spec §2 examples no test pins; checked with grep against tests/unit/test_products.py and tests/integration/test_products_run.py):
- "BSOAgentTestBrand Beige Women Slippers" for "BSOAgentTestBrand Women Casual Slipper Beige" giving "BSOAgentTestBrand Beige Women Casual Slippers" (`test_rule_check_restores_dropped_words` pins a lost "Casual" with other titles).
- "BSOAgentTestBrand Brown Men Sandals" for "BSOAgentTestBrand Men Casual Sandal Brown" giving "BSOAgentTestBrand Brown Men Casual Sandals".
- A lost number or stopword is not restored ("Walkaroo Sandal 2 Pack" giving "Walkaroo Sandal Pack"; a lost "for").
- The function-word anchor ("Sandal with Casual Look" giving "Look with Casual Sandal").
- The page, API and CSV side of the "no longer show which word was dropped" ceiling: only the stored row is pinned (the integration test's `("adjusted", [])`); the consumers are unchanged in code.
- The trim cutting the keyword after a restore: `test_rule_check_trims_to_150_at_a_word_boundary` pins a restore that moves the cut (`adjusted`, lost `[]`) with synthetic words, not with a keyword at the end.
