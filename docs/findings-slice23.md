# Slice 23 findings: the searched keyword when title and category disagree

## 1. What was built

This slice targets LC-05 ("BSOAgentTestBrand Men Flip Flop Navy", category "Slippers"), which got the searched keyword "navy flip flops" in 3 of the 4 live checks on record (spec, Context). The target is the audience plus the type named in the title ("men flip flops"), the same shape as the other 9 dev products.

All code changes are in `packages/core/bsi_core/products.py`. No prompt, schema, API or web change.

**`_type_word`, and `fit_rank` using it.** `fit_rank`'s lines that find a keyword's category word moved into `_type_word(keyword) -> str | None`, placed between `CATEGORY_CUTS` and `fit_rank`. It returns the last folded word before the keyword's first `CATEGORY_CUTS` token, or the keyword's last folded word if nothing folds before the cut, and `None` if nothing folds. `fit_rank`'s loop calls it; its signature, docstring and behaviour are unchanged, and its 3 tests pass.

**`AUDIENCE_WORDS` and `title_first`.** `AUDIENCE_WORDS` is men, women, kids, boys, girls, unisex, baby; `AUDIENCE_STEMS` holds their stems. `title_first(keywords, title)`, defined after `fit_rank` in the file, acts only when the first keyword's type word is not in the title and another keyword is title-fitting (its type word is in the title and is not an audience stem). It then puts first the first keyword's audience plus the title's type ("men slippers" and "cushioned flip flops" for "Men Flip Flop Navy" give "men flip flops"). The type words are the tokens of the first title-fitting keyword whose stems are in the title, in every title-fitting keyword, and not an audience stem of the first keyword, not in `AUDIENCE_STEMS` and not in `NOISE_STEMS`. An offered keyword with the same key is used in its own spelling. Otherwise the keywords are returned as given. The result is at most `MAX_KEYWORDS`. A `# ponytail:` comment above it carries the known ceilings, in the plan's shorter wording (§4).

**`drop_noise_terms`.** Placed after `drop_brand_terms`. It keeps a keyword only if none of its stems is in `NOISE_STEMS`. A `# ponytail:` comment above it carries the §1 ceilings.

**`choose_keywords`.** Placed after `title_first`, before `missing`. It is the whole keyword choice for one product: an inner `pick` runs `vote`, `drop_brand_terms`, `title_first` and `fit_rank`, first over the samples with `drop_noise_terms` applied to each, and only if that leaves nothing, over the samples as given (the per-product fallback). Task 4 adds a second fallback (below).

**Task 4: the wrong-type fallback (Ruling R2) and the plural spelling (Ruling R3).** Added after the final whole-branch review (Important 1): when every title-fitting keyword had a colour word, the guard removed them all before `title_first`, and `fit_rank` searched the category's type (LC-05's title, category "Slippers", samples `[["men slippers", "navy flip flops", "cushioned slippers"]] * 3` gave "men slippers"; main gave "navy flip flops").
- `choose_keywords` (products.py:601-605) now computes the guarded result first and returns it when its first keyword's type word (`_type_word`) is in the title. Otherwise it computes the result over the samples as given, and returns that when its first keyword's type word is in the title, or when the guarded result is empty; else the guarded result. The regression case now gives "men flip flops", built by `title_first` from "navy flip flops". The docstring says the same.
- `title_first`'s audience leaves out `NOISE_STEMS` words (products.py:557), so "men navy slippers" and "navy flip flops" build "men flip flops", not "men navy flip flops".
- `title_first` spells each built type word in the plural when any title-fitting keyword has that plural (products.py:565): "men slippers", "men flip flop navy" and "navy flip flops" build "men flip flops". With no plural title fit the type word stays singular ("men flip flop").
- The two `# ponytail:` comments changed. Above `drop_noise_terms`: a colour or size phrase is searched only "when no keyword without one names the title's type and none can be built". Above `title_first`: the audience is what is left of the first keyword "after its colour and size words", and two new ceilings at its end (the singular type word; the wrong-type fallback uses `fit_rank`'s rule, so a title audience word counts as a type there).

**`run_products`.** The `ranked = vote(...)` and `fitted = fit_rank(...)` lines are replaced by one `fitted = choose_keywords([sm.get(i, []) for sm in samples], names, p["title"], p["category"], p["description"])` call. The `p["keywords"]` and `p["keyword"]` lines are unchanged, as are `vote`, `drop_brand_terms`, `keyword_key`, the run-wide `key_map` and every prompt.

**The `NOISE_WORDS` comment.** Its first sentence now reads "missing() never suggests these (slice 21 spec §2), and the keyword choice drops keywords that contain them (slice 23 spec §1)." The rest of the comment is unchanged (re-wrapped). The `NOISE_WORDS` values are unchanged.

**Tests.**
- `tests/unit/test_products.py`, Task 1: module constants `T`, `W` and `CASUAL`, and 10 new tests: `test_type_word_is_the_category_word_fit_rank_reads` and 9 `title_first` tests (the two builds, the offered spelling, the cases where nothing is built, the cap, audience words kept out of the type, shared words, a keyword that fits only by an audience word, two title types, no colour built in).
- `tests/unit/test_products.py`, Task 2: the constant `S4` (probe 4's samples for LC-05) and 5 new tests: `test_drop_noise_terms_removes_colour_and_size_keywords` and 4 `choose_keywords` tests (probe 4's samples, one all-colour sample, the fallback when the product has no other keyword, an audience-word keyword).
- `tests/unit/test_products.py`, Task 4: 3 new tests: `test_title_first_never_takes_a_colour_from_the_first_keyword`, `test_title_first_prefers_a_plural_spelling_of_the_type` (with the singular ceiling) and `test_choose_keywords_falls_back_when_the_guard_leaves_the_wrong_type` (the regression case, a category fit alone, no colour built on the unfiltered path).
- The existing `fit_rank`, `vote` and `drop_brand_terms` tests are unchanged and pass.
- `tests/integration/test_products_run.py`: 1 new test, `test_the_searched_keyword_has_the_title_type_and_no_colour`. One seeded product ("Walkaroo Boys Sandal 0", no description or category), fake keywords `["kids slippers", "blue sandals", "strap sandals"]`; it asserts `keyword == "kids sandals"`, `keywords == ["kids sandals", "strap sandals"]` and one search for "kids sandals". No existing integration test changed.
- TDD evidence, as the tasks recorded it:
  - Task 1 RED: `ImportError: cannot import name '_type_word' from 'bsi_core.products'`, 1 error during collection. GREEN: 17 passed, 66 deselected.
  - Task 2 RED: `ImportError: cannot import name 'choose_keywords' from 'bsi_core.products'` (unit); `AssertionError: assert 'blue sandals' == 'kids sandals'`, 1 failed, 24 deselected (integration). GREEN: 113 passed.
  - Task 2 Step 9: with `return pick(samples)` in `choose_keywords`, the new integration test failed with `At index 1 diff: 'blue sandals' != 'strap sandals'`. It passed after `products.py` was restored from the scratchpad backup, and `git diff --stat` showed only the 3 expected files.
  - Task 4 RED: 3 failed, 88 deselected: `At index 0 diff: 'men navy flip flops' != 'men flip flops'`; `At index 0 diff: 'men flip flop' != 'men flip flops'`; `At index 0 diff: 'men slippers' != 'men flip flops'` (the `choose_keywords` test, on its first assertion). GREEN: product unit and integration files, 116 passed.
- Backend gate:
  - Task 1 (23eb548): ruff and mypy clean; 1530 passed, 2 deselected, 2 warnings; metrics coverage 100%.
  - Task 2 (d072568): ruff and mypy clean; 1536 passed, 2 deselected, 2 warnings; metrics coverage 100%.
  - Task 4 (0d99220): ruff and mypy clean; 1539 passed, 2 deselected, 2 warnings; metrics coverage 100%.
  - The 2 warnings in all three runs: `StarletteDeprecationWarning` (fastapi/testclient.py:1) and the anyio `BlockingPortal` alias `DeprecationWarning` (starlette/testclient.py:53).
  - The controller's own full gates run at finishing.

**Commits** (`git log --oneline main..HEAD`, oldest first):

| Commit | Subject |
|---|---|
| 8bf9538 | docs: slice 23 spec (the searched keyword when title and category disagree) |
| a8e23b7 | docs: slice 23 spec review fixes (per-product fallback, type-word rules, costs, tests) |
| 055564d | docs: slice 23 spec: audience filter on title-fitting keywords, two ceilings |
| c9d682c | docs: slice 23 implementation plan |
| cc9b670 | docs: slice 23 plan review fixes |
| 23eb548 | feat(products): build the audience plus the title's type as a keyword |
| d072568 | feat(products): the keyword choice drops colour keywords and searches the title's type |
| 0ea1a26 | docs: slice 23 findings, index and rulings |
| 5737187 | docs: slice 23 ruling R1 (README spec row) and plan record fixes |
| b0c0cb0 | docs: slice 23 ruling R2 (wrong-type fallback) in the spec, and plan Task 4 |
| c93232d | docs: slice 23 ruling R3 (R2's side effects as ceilings) and Task 4 review fixes |
| 53a3646 | docs: slice 23 ruling R3 revised: plural spelling for the built type; review text fixes |
| 4ed4f16 | docs: slice 23 R3 cost, Task 4 files and coverage row, changes bullet |
| 0d99220 | fix(products): search the title's type when the guard would leave the category's |
| 9e8504f | docs: slice 23 findings quote R2 and R3 as recorded |
| (this commit) | docs: slice 23 findings quote R1 as recorded |

## 2. The probes

As the spec's "The probes" section records them.

Each probe: the 10 dev products read from dev read-only, `keyword_prompt` called `SAMPLES` (3) times through `judge.generate` at `KEYWORD_TEMPERATURE`, then the current `vote`, `drop_brand_terms` and `fit_rank` applied in a scratch script. No database writes, no job, no worker, no repo edits. Probes 2 to 4 added one sentence to the prompt text inside the scratch script, after the rank-1 sentence.

| Probe | Sentence added | Cost (micros) |
|---|---|---|
| 1 | none (today's prompt) | 4,415 |
| 2 | "When the title names a different product type from the category, rank 1 uses the type named in the title (a "Men Flip Flop Navy" in the category "Slippers" is "men flip flops")." | 4,367 |
| 3 | the same sentence with the example (a "Women Clog Black" in the category "Sandals" is "women clogs") | 5,099 |
| 4 | "Always include the audience plus the product type named in the title as one keyword, even when the category names a different type (a "Women Clog Black" in the category "Sandals" includes "women clogs")." | 4,845 |

Total 18,726 micros; spend about $10.90 of the $15 cap.

Two prompt wordings were tried and dropped: the sentence of probes 2 and 3 (probe 3 with the neutral example) and the sentence of probe 4. A first Section 1 of the design (the prompt sentence) was approved and then withdrawn, with the user's OK, after probes 2 to 4 (spec, Context). The prompt is not changed.

Observed for LC-05:

| Probe | Rank 1 in samples 1, 2, 3 | Samples offering "men flip flops" | After `vote` and `fit_rank`, first keyword |
|---|---|---|---|
| 1 | men slippers, men slippers, men slippers | 2 of 3 | men flip flops |
| 2 | men slippers, men flip flops, men flip flops | 3 of 3 | men flip flops |
| 3 | men slippers, men slippers, men slippers | 3 of 3 (one as "mens flip flops") | men flip flops |
| 4 | men slippers, men slippers, men slippers | 2 of 3 | men flip flop navy |

Observed for the other 9 products: the same rank 1 in all 3 samples of every probe, and the same first keyword after `fit_rank` in all four probes (kids sandals ×2, kids shoes ×2, kids slippers, men sandals, men shoes, women slippers, women sandals).

What the probes show:

- The model's first keyword for LC-05 is the audience plus the *category's* type: "men slippers" in 10 of 12 samples. (An earlier count in chat and in the approved plan said 11 of 12; the table above gives 10.) The prompt asks for "the audience plus the product's own category".
- The colour keyword is not the model's first choice. `fit_rank` puts keywords whose type is in the title ahead of "men slippers", so the searched keyword is the first title-fitting keyword that `vote` kept.
- In probe 4, "men flip flops" was offered in 2 of 3 samples and still cut: `vote` keeps `MAX_KEYWORDS` (5) keys, the top key and then the others in first-seen order, so sample 1's list took the places.
- Probe 2's gain came from the example being LC-05 itself; with a neutral example (probe 3) rank 1 did not change.
- Probe 4's sentence made the model echo titles: "men flip flop navy" (LC-05, sample 1) and "kids slipper grey" (LC-04, all 3 samples).
- *Inferred*: in the real runs that gave "navy flip flops", the model did not offer "men flip flops", or `vote` cut it. The raw samples of those runs were not stored. LC-05's stored list after slice 22's check is "navy flip flops", "mens casual flip flops", "daily wear flip flops", "men slippers", "cushioned slippers".

## 3. Live check on dev

Not yet run. The controller runs it after the user approves; results are recorded here then.

## 4. Deferred and untested

From the task reviews:
- Task 1: the `ponytail:` comment above `title_first` leaves out the spec's "babies booties"/"baby shoes" example and the "ladies", "gents", "teens" note; it is the plan's wording (plan departure 7).
- Task 1: the audience takes any leftover word of the first keyword, a colour included ("men navy slippers" would build "men navy flip flops"); the colour test covers a colour only in a title-fitting keyword. The guard in `choose_keywords` (Task 2) removes such keywords before `title_first`, except in the unfiltered fallback `pick(samples)`, which runs only when the filtered samples leave no keyword.
  - Fixed by R2: the audience leaves out colour and size words. Correction to the ending above: the unfiltered path is also tried when the guard leaves the wrong type (R2).
- Task 1: the gate output carries 2 third-party warnings (StarletteDeprecationWarning from fastapi's test client; DeprecationWarning, the anyio BlockingPortal alias, from starlette's test client); pre-existing on main; not caused by this diff.
- Task 2: in the unfiltered fallback `pick(samples)` (products.py:584), `title_first` can build a colour into a keyword no sample offered: `choose_keywords([['men navy slippers', 'navy flip flops']], ['Brand'], 'Brand Men Flip Flop', None, None)` returns `['men navy flip flops', 'navy flip flops']`. The reviewer labelled it plan-mandated. Only when every keyword has a noise word; the result is a colour keyword either way. Possible fixes (both spec changes, the user's call): audience only from `AUDIENCE_STEMS`, or skip `title_first` in the fallback.
  - Fixed by R2. The example now returns `['men flip flops', 'navy flip flops']`. Correction to the premise above (final review, Minor 2): the fallback runs whenever the filtered samples leave no fitting keyword (not only when every keyword has a noise word). Since R2, the unfiltered result is also tried when the filtered result's first keyword names a type the title does not; it is used only if its own first keyword names a type the title does, or if the filtered result is empty. products.py:584 is now products.py:601-605.
- Task 2: no unit test covers `title_first` on the fallback path (test_products.py:1036-1047 has only fallback inputs where nothing is built).
  - Fixed by Task 4's tests.
- Task 3: plan:643 quotes task-2-report.md "no departures from the brief" out of its ruff context (task-2-report.md:71); the report's departures section (task-2-report.md:74-75) says "None."
- Task 3: plan:645 (unchanged line) says findings §4 "also has two lists Step 1 does not name"; findings §4 now has a third, "Rulings" (mentioned in the fix-round bullet at plan:648).

Parked: none. The ledger has no parked lines.

Rulings (R1 from the Task 3 review; R2 and R3 from the final whole-branch review and the reviews of the spec change; the spec's Rulings has each in full):
- Task 3: Ruling R1: the README's slice 23 spec row ends at "…with the four probes of the keyword prompt." (the rulings clause is dropped), departing from the plan's Step 2 wording — Found by the Task 3 review — Why: the row must not claim rulings the spec does not hold; dropping the clause stays true whatever the spec's Rulings holds, while "(none)" would become false once this ruling itself is recorded — Cost if wrong: the row no longer points readers to the spec's Rulings section. Because this is a ruling, the spec's Rulings records R1 (replacing "None.").
  - Note (not ledger text; the Task 3 round's entry, kept): the README's slice 23 spec row ends at "…with the four probes of the keyword prompt." (the rulings clause is dropped), departing from the plan's Step 2 wording — Ruling R1: the row must not claim rulings the spec does not hold; dropping the clause stays true whatever the spec's Rulings holds, while "(none)" would become false once this ruling itself is recorded — cost if wrong: the row no longer points readers to the spec's Rulings section. Fixed in 5737187: the row is changed, and the spec's Rulings records R1 (replacing "None.").
- Ruling R2: fix the final review's Important 1 with option (b), not fix (a): `choose_keywords` keeps the guarded path, and uses the unguarded path instead when the guarded result's first keyword names a type the title does not and the unguarded result's first keyword names one the title does; `title_first`'s audience also leaves out `NOISE_STEMS` words — Found by the final whole-branch review (Important 1) and the Task 2 review (fallback colour minor) — Why: the user asked for the regression fixed without fix (a)'s singular "men flip flop" on probe 4's samples; (b) keeps probe 4's "men flip flops" and every other simulated value, and gives "men flip flops" for the regression case (main: "navy flip flops"; branch: "men slippers") — Cost if wrong: in that case the stored `keywords` list keeps colour keywords after the searched one (e.g. "navy flip flops"), because the unguarded vote is used.
  - Note (not ledger text): the review of the R2 spec change found further side effects; the spec's R2 lists them in its Cost if wrong, and R3 accepts them as ceilings. Done in 0d99220 (Task 4).
- Ruling R3: R2's side effects are accepted as ceilings — no further code for (a) colour keywords stored when the fallback is used, (b) a colour keyword that names the title's type searched ahead of a category-only keyword when nothing can be built (as on main), (c) a singular type word when the only title fit is singular (main: "men flip flop navy") — Found by the R2 spec/plan review — Why: in each case the searched keyword names the title's type, the slice's target, and gives the same type as main; the plural rule helps only when some title fit is plural — Cost if wrong: LC-05 can search "navy flip flops" or "men flip flop" on a run where the model offers no colour-free plural flip-flop keyword.
  - Note (not ledger text; from the ledger's R3 re-review line): this first reading was revised (next entry). Its Why was wrong: the singular type word comes from the first title-fitting keyword being singular, not the only one.
- Ruling R3 revised: add the plural-spelling rule to `title_first` (a type word takes its plural spelling when any title-fitting keyword has it); (a) colour keywords stored, (b) a colour keyword naming the title's type searched when nothing can be built, (c) singular when no title fit has the plural, stay ceilings. Checked on scratch copy p23g: current unit file + Task 4 tests 91 passed; product-run file 25 passed; `[["men slippers","men flip flop navy","navy flip flops"]]*3` -> ['men flip flops', 'men flip flop navy', 'navy flip flops', 'men slippers']; `[["men slippers","men flip flop navy","cushioned slippers"]]*3` -> ['men flip flop', ...]; probe 4's S4 unchanged ('men flip flops' first); Task 4's 3 new tests fail on the branch (3 failed) and pass on p23g; Task 4's code blocks have no line over 80 and its test block is ruff-format clean.
  - Note (not ledger text; from the spec's R3): found by the review of the R2 spec change (b0c0cb0) and its re-review. Cost if wrong: LC-05 can still search "navy flip flops" or "men flip flop" on a run where the model offers no colour-free title-fitting keyword and no plural one, or offers the audience-plus-type keyword itself in the singular. Done in 0d99220 (Task 4).

From the spec review (the last spec re-review approved the spec and left two minor notes; plan, "From the spec review"):
- `title_first`'s audience exclusion applies to the other keywords, not to the first. If the model's first keyword is itself an audience-word phrase ("casual men"), `title_first` returns the keywords as given and `fit_rank` searches it as today. The spec's last ceiling covers this loosely; "including the first keyword" would make it exact.
- `types` removes audience stems but not colour stems, so in `choose_keywords`' unfiltered fallback a phrase such as "flip flop navy" counts as title-fitting. The colour stays out of the built keyword (`ok - NOISE_STEMS`): "men slippers", "flip flop navy" and "cushioned flip flops" give "men flip flop".
  - R2 makes this unfiltered path reachable whenever the guard leaves the wrong type, not only when the filtered samples leave nothing (R3 accepts the results as ceilings). With R3's plural rule the example now builds "men flip flops" ("cushioned flip flops" supplies the plural).

Untested:
- The tests use fixed model output, so they do not show which keyword real samples give. The dev re-check (§3) is where that is observed.

Known ceilings, spec §1 (the guard, in the `# ponytail:` comment above `drop_noise_terms`):
- A real colour or size phrase that shoppers type ("white sneakers", "little kids sandals", "big kids shoes") is searched only when no keyword without one names the title's type and none can be built.
- Outside footwear some of these are product words ("gold", "cream", "plus size").
- English only.

Known ceilings, spec §2 (the built fallback, in the `# ponytail:` comment above `title_first`, in shorter wording):
- The audience is whatever is left of the first keyword after its colour and size words (R2), in the model's spelling: "men house slippers" gives "men house flip flops", "mens slippers" gives "mens flip flops", and "babies booties" with "baby shoes" for a "Baby Shoe" gives "babies shoes".
- When the title-fitting keywords name two different types that are both in the title, they share no word and nothing is built.
- Audience-then-type order suits English.
- With one title-fitting keyword, a style word in it that the title has too is kept: "men floaters" and "casual sandals" give "men casual sandals".
- `AUDIENCE_WORDS` is closed and English only ("ladies", "gents", "teens" are not in it).
- Observed on footwear only.
- It depends on the model's first keyword being the audience plus the category's type (10 of 12 LC-05 samples).
- A title word that is not a product type can count as one: the rule only checks that a keyword's type word is in the title and is not an audience word.
- A type word is singular when no title-fitting keyword spells it in the plural: samples `[["men slippers", "men flip flop navy", "cushioned slippers"]] * 3` for LC-05 build "men flip flop" (main: "men flip flop navy"). On the probes' guarded samples the first title-fitting keyword was plural, so the fallback was not used; on probe 4's unfiltered samples the first title fit is the singular "men flip flop navy", and "navy flip flops" supplies the plural.
- `choose_keywords`' wrong-type fallback (R2) uses `fit_rank`'s rule, in which an audience word in the title counts as a type word; so "slippers boys" for a "Boys Sandal" keeps the guarded result, as before R2 and on main.

Out of scope (spec):
- `vote`'s first-seen ordering and its `MAX_KEYWORDS` cap.
- Storing the raw keyword samples or the raw rewrite.
- Any prompt change.
- The deferred minors in docs/findings-slice21.md §3 and docs/findings-slice22.md §3.
