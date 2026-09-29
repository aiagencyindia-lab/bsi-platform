# Slice 23 findings: the searched keyword when title and category disagree

## 1. What was built

This slice targets LC-05 ("BSOAgentTestBrand Men Flip Flop Navy", category "Slippers"), which got the searched keyword "navy flip flops" in 3 of the 4 live checks on record (spec, Context). The target is the audience plus the type named in the title ("men flip flops"), the same shape as the other 9 dev products.

All code changes are in `packages/core/bsi_core/products.py`. No prompt, schema, API or web change.

**`_type_word`, and `fit_rank` using it.** `fit_rank`'s lines that find a keyword's category word moved into `_type_word(keyword) -> str | None`, placed between `CATEGORY_CUTS` and `fit_rank`. It returns the last folded word before the keyword's first `CATEGORY_CUTS` token, or the keyword's last folded word if nothing folds before the cut, and `None` if nothing folds. `fit_rank`'s loop calls it; its signature, docstring and behaviour are unchanged, and its 3 tests pass.

**`AUDIENCE_WORDS` and `title_first`.** `AUDIENCE_WORDS` is men, women, kids, boys, girls, unisex, baby; `AUDIENCE_STEMS` holds their stems. `title_first(keywords, title)`, placed after `fit_rank`, acts only when the first keyword's type word is not in the title and another keyword is title-fitting (its type word is in the title and is not an audience stem). It then puts first the first keyword's audience plus the title's type ("men slippers" and "cushioned flip flops" for "Men Flip Flop Navy" give "men flip flops"). The type words are the tokens of the first title-fitting keyword whose stems are in the title, in every title-fitting keyword, and not an audience stem of the first keyword, not in `AUDIENCE_STEMS` and not in `NOISE_STEMS`. An offered keyword with the same key is used in its own spelling. Otherwise the keywords are returned as given. The result is at most `MAX_KEYWORDS`. A `# ponytail:` comment above it carries the known ceilings, in the plan's shorter wording (§4).

**`drop_noise_terms`.** Placed after `drop_brand_terms`. It keeps a keyword only if none of its stems is in `NOISE_STEMS`. A `# ponytail:` comment above it carries the §1 ceilings.

**`choose_keywords`.** Placed after `title_first`, before `missing`. It is the whole keyword choice for one product: an inner `pick` runs `vote`, `drop_brand_terms`, `title_first` and `fit_rank`, first over the samples with `drop_noise_terms` applied to each, and only if that leaves nothing, over the samples as given (the per-product fallback, products.py:584).

**`run_products`.** The `ranked = vote(...)` and `fitted = fit_rank(...)` lines are replaced by one `fitted = choose_keywords([sm.get(i, []) for sm in samples], names, p["title"], p["category"], p["description"])` call. The `p["keywords"]` and `p["keyword"]` lines are unchanged, as are `vote`, `drop_brand_terms`, `keyword_key`, the run-wide `key_map` and every prompt.

**The `NOISE_WORDS` comment.** Its first sentence now reads "missing() never suggests these (slice 21 spec §2), and the keyword choice drops keywords that contain them (slice 23 spec §1)." The rest of the comment is unchanged (re-wrapped). The `NOISE_WORDS` values are unchanged.

**Tests.**
- `tests/unit/test_products.py`, Task 1: module constants `T`, `W` and `CASUAL`, and 10 new tests: `test_type_word_is_the_category_word_fit_rank_reads` and 9 `title_first` tests (the two builds, the offered spelling, the cases where nothing is built, the cap, audience words kept out of the type, shared words, a keyword that fits only by an audience word, two title types, no colour built in).
- `tests/unit/test_products.py`, Task 2: the constant `S4` (probe 4's samples for LC-05) and 5 new tests: `test_drop_noise_terms_removes_colour_and_size_keywords` and 4 `choose_keywords` tests (probe 4's samples, one all-colour sample, the fallback when the product has no other keyword, an audience-word keyword).
- The existing `fit_rank`, `vote` and `drop_brand_terms` tests are unchanged and pass.
- `tests/integration/test_products_run.py`: 1 new test, `test_the_searched_keyword_has_the_title_type_and_no_colour`. One seeded product ("Walkaroo Boys Sandal 0", no description or category), fake keywords `["kids slippers", "blue sandals", "strap sandals"]`; it asserts `keyword == "kids sandals"`, `keywords == ["kids sandals", "strap sandals"]` and one search for "kids sandals". No existing integration test changed.
- TDD evidence, as the tasks recorded it:
  - Task 1 RED: `ImportError: cannot import name '_type_word' from 'bsi_core.products'`, 1 error during collection. GREEN: 17 passed, 66 deselected.
  - Task 2 RED: `ImportError: cannot import name 'choose_keywords' from 'bsi_core.products'` (unit); `AssertionError: assert 'blue sandals' == 'kids sandals'`, 1 failed, 24 deselected (integration). GREEN: 113 passed.
  - Task 2 Step 9: with `return pick(samples)` in `choose_keywords`, the new integration test failed with `At index 1 diff: 'blue sandals' != 'strap sandals'`. It passed after `products.py` was restored from the scratchpad backup, and `git diff --stat` showed only the 3 expected files.
- Backend gate:
  - Task 1 (23eb548): ruff and mypy clean; 1530 passed, 2 deselected, 2 warnings; metrics coverage 100%.
  - Task 2 (d072568): ruff and mypy clean; 1536 passed, 2 deselected, 2 warnings; metrics coverage 100%.
  - The 2 warnings in both runs: `StarletteDeprecationWarning` (fastapi/testclient.py:1) and the anyio `BlockingPortal` alias `DeprecationWarning` (starlette/testclient.py:53).
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
| (this commit) | docs: slice 23 findings, index and rulings |

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
- Task 1: the gate output carries 2 third-party warnings (StarletteDeprecationWarning from fastapi's test client; DeprecationWarning, the anyio BlockingPortal alias, from starlette's test client); pre-existing on main; not caused by this diff.
- Task 2: in the unfiltered fallback `pick(samples)` (products.py:584), `title_first` can build a colour into a keyword no sample offered: `choose_keywords([['men navy slippers', 'navy flip flops']], ['Brand'], 'Brand Men Flip Flop', None, None)` returns `['men navy flip flops', 'navy flip flops']`. The reviewer labelled it plan-mandated. Only when every keyword has a noise word; the result is a colour keyword either way. Possible fixes (both spec changes, the user's call): audience only from `AUDIENCE_STEMS`, or skip `title_first` in the fallback.
- Task 2: no unit test covers `title_first` on the fallback path (test_products.py:1036-1047 has only fallback inputs where nothing is built).

Parked: none. The ledger has no parked lines and no rulings.

From the spec review (the last spec re-review approved the spec and left two minor notes; plan, "From the spec review"):
- `title_first`'s audience exclusion applies to the other keywords, not to the first. If the model's first keyword is itself an audience-word phrase ("casual men"), `title_first` returns the keywords as given and `fit_rank` searches it as today. The spec's last ceiling covers this loosely; "including the first keyword" would make it exact.
- `types` removes audience stems but not colour stems, so in `choose_keywords`' unfiltered fallback a phrase such as "flip flop navy" counts as title-fitting. The colour stays out of the built keyword (`ok - NOISE_STEMS`): "men slippers", "flip flop navy" and "cushioned flip flops" give "men flip flop".

Untested:
- The tests use fixed model output, so they do not show which keyword real samples give. The dev re-check (§3) is where that is observed.

Known ceilings, spec §1 (the guard, in the `# ponytail:` comment above `drop_noise_terms`):
- A real colour or size phrase that shoppers type ("white sneakers", "little kids sandals", "big kids shoes") is searched only when the product has no other fitting keyword.
- Outside footwear some of these are product words ("gold", "cream", "plus size").
- English only.

Known ceilings, spec §2 (the built fallback, in the `# ponytail:` comment above `title_first`, in shorter wording):
- The audience is whatever is left of the first keyword, in the model's spelling: "men house slippers" gives "men house flip flops", "mens slippers" gives "mens flip flops", and "babies booties" with "baby shoes" for a "Baby Shoe" gives "babies shoes".
- When the title-fitting keywords name two different types that are both in the title, they share no word and nothing is built.
- Audience-then-type order suits English.
- With one title-fitting keyword, a style word in it that the title has too is kept: "men floaters" and "casual sandals" give "men casual sandals".
- `AUDIENCE_WORDS` is closed and English only ("ladies", "gents", "teens" are not in it).
- Observed on footwear only.
- It depends on the model's first keyword being the audience plus the category's type (10 of 12 LC-05 samples).
- A title word that is not a product type can count as one: the rule only checks that a keyword's type word is in the title and is not an audience word.

Out of scope (spec):
- `vote`'s first-seen ordering and its `MAX_KEYWORDS` cap.
- Storing the raw keyword samples or the raw rewrite.
- Any prompt change.
- The deferred minors in docs/findings-slice21.md §3 and docs/findings-slice22.md §3.
