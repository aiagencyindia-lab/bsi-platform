# Slice 26 design: a removed repeat no longer counts as an adjustment

## Context

Slice 25's live check (docs/findings-slice25.md §2, job `08939d2b`) stored the rewrite call's raw titles for the first time. All 10 of them end with the original title's type word or its plural (LC-09 ends with "Shoes"; its original has "Shoe"), after a plural or singular form of it earlier in the title. One example is LC-01: "BSOAgentTestBrand Blue Kid Sandals Boys Sandal" for the original "BSOAgentTestBrand Boys Sandal Blue". `rule_check`'s repeat-stem drop removed the repeat each time, so every suggested title was clean, but every status was `adjusted`.

*Inferred* cause: `rewrite_prompt` (`packages/core/bsi_core/products.py`) says "Keep every word of the original title (you may reorder them); add the keyword and the missing terms naturally; never change the product type; repeat no word; no keyword stuffing." *Inferred*: with the keyword "kids sandals" and the original word "Sandal", the model keeps "Sandal" and adds "Sandals".

Classification, said in chat as the first line of the first brainstorming reply: **architectural** — "The fix changes the rewrite prompt or the rule check, and every product run passes through both. The process also calls for a spec even for small changes."

Decisions approved in chat (brainstorming on Opus 5.5, 2026-09-30). Each question below had its options described in the question, and each design section's text was in chat before its approval question:

- **Goal (first choice, superseded after probe 2; see below):** a clean raw rewrite. The prompt stops the model from writing both forms of a word, so statuses reflect real edits. Rejected: "honest status only" (make the rule check not count the removed repeat), and doing both.
- **Success test (for the prompt route, Appendix A2):** probe 3 + 3 rewrite calls on dev's 10 products before building (current prompt, then the new prompt). Rejected: judging on the post-merge live check only; 5 + 5 calls.
- **Probe criteria (from the spec review, put to the user as a question and approved in chat):** only singular/plural repeats count against the pass rule (other repeats are recorded); a baseline with no singular/plural repeat makes the probe inconclusive.
- **Approach A:** reword the prompt's keep rule. Approaches B (the code gives each product a per-product "use X in place of Y" hint) and C (A and B together) were described in chat with trade-offs; A was recommended and chosen, with B to be put to the user if A fails the probe.
- **After probe 1 failed (Appendix A2), approach C:** the user chose "Probe C: sentence + hint" over B alone, accepting A as is, or stopping. The revised design text (the sentence plus per-product swaps, now Appendix A1; probe 2; the tests) was put in chat and approved.
- **Swap rule (from the spec review, put to the user as a question and approved in chat):** a hint only when the title word and the keyword word have the same folded stems and different tokens, so a hyphenated word such as "Flip-Flop" gets no hint that would lose a word.
- **After probe 2 failed (Appendix A2), the goal was asked again**, because the fact behind "clean raw rewrite" (that a prompt change could reach it reliably) had turned out wrong. The user chose "Honest status, code only" over one more prompt fix with probe 3, and over stopping the slice. The status design (§1), the testing (§2), and the live check and docs (§3) were each put in chat in their own message and approved.
- **Repeat scope (§1's approval question):** any word removed only because it repeats an earlier word's stem stops counting as an adjustment. Rejected: singular/plural repeats only, under which LC-05's "Flip Flops Flip Flop" stays `adjusted`.
- **Spacing (asked after the process audit, 2026-09-30):** a suggestion that differs from the final title only in spacing gives `pass` (`plain` is re-joined with single spaces). The spec review had found this consequence and it was written into §1 without asking; the user was then asked and chose the recommended option, "Yes, pass (Recommended)".

Codebase facts (main `aa62285`, checked 2026-09-30):

- `rule_check` (products.py) drops a word whose `fold_set` stems overlap an earlier kept word's stems, in a loop inline in the function, and returns status `"pass"` only when the final title equals the suggestion (`"review"` when an original word is lost). Today `rule_check("BSOAgentTestBrand Boys Sandal Blue", "BSOAgentTestBrand Blue Kid Sandals Boys Sandal", ["BSOAgentTestBrand"], allowed=["kids sandals", "kid"])` and `rule_check("BSOAgentTestBrand Men Flip Flop Navy", "BSOAgentTestBrand Navy Mens Flip Flops Flip Flop", ["BSOAgentTestBrand"], allowed=["mens flip flops"])` both return status `"adjusted"`.
- `apps/web` and `apps/api` show the status value and have no copy that explains `adjusted`.
- For the prompt route (Appendix): `rewrite_prompt(brand, products)` returns one string, and `run_products` sends it with `RewriteSet` at temperature 0.0, once per batch.
- `rule_check("BSOAgentTestBrand Boys Sandal Blue", "BSOAgentTestBrand Blue Kid Sandals Boys", ["BSOAgentTestBrand"], allowed=["kids sandals", "kid"])` returns `("BSOAgentTestBrand Blue Kid Sandals Boys", "pass", [])`. The same call with a trailing " Sandal" on the suggestion returns the same title with `"adjusted"`. `rule_check("BSOAgentTestBrand Boys School Shoe Black", "BSOAgentTestBrand Black Kids School Shoes Boys", ...)` returns `"pass"` (with `["BSOAgentTestBrand"], allowed=["kids sandals", "kid"]`, the same arguments as the first call). So swapping a word for its plural is neither a lost word nor an adjustment (checked 2026-09-30).
- `tests/unit/test_products.py` has `test_prompts_ask_for_plural_kids_keywords_and_kept_words`, which asserts `"Keep every word" in rewrite_prompt("Walkaroo", [])`, and a prompt test that asserts `"summer"` and `"150"` in a rewrite prompt. `tests/unit/test_recommend_copy.py` scans `rewrite_prompt("Acme", [])` against the banned-word list.

## Design

The rewrite prompt stays as it is on main. Only `rule_check`'s status changes.

### 1. The status rule

- The repeat loop inside `rule_check` moves into a helper that `rule_check` uses for the title:

```python
def _drop_repeats(words: Sequence[str]) -> list[str]:
    """The words without any whose folded stems repeat an earlier kept
    word's stems (punctuation-only words are kept)."""
    seen: set[str] = set()
    kept: list[str] = []
    for word in words:
        stems = fold_set(word)
        if stems & seen:
            continue
        seen |= stems
        kept.append(word)
    return kept
```

- In `rule_check`, `title = " ".join(_strip_connectors(_drop_repeats(title.split())))` replaces the inline loop, and the last line becomes:

```python
    plain = " ".join(_drop_repeats(suggestion.split()))
    return title, ("pass" if title in (suggestion, plain) else "adjusted"), []
```

- So the status is `pass` when the final title equals the suggestion, or the suggestion with only its repeats removed. Prepending the brand, dropping an unbacked word, the connector strip (including a connector left at the end by a removed repeat, as in `test_rule_check_folds_plurals_and_strips_a_trailing_connector`), the trim, or the fallback to the original still give `adjusted`; a lost original word still gives `review`. The docstring's Status sentence says so. A suggestion that differs only in spacing also gives `pass` (`plain` is re-joined with single spaces).
- Checked on a scratch copy of `products.py` (2026-09-30): LC-01's pattern gives `("BSOAgentTestBrand Blue Kid Sandals Boys", "pass", [])`; LC-05's gives `("BSOAgentTestBrand Navy Mens Flip Flops", "pass", [])`; `rule_check("Walkaroo Kids Shoes", "Walkaroo Kids Shoes Shoes Sale", ["Walkaroo"])` gives `("Walkaroo Kids Shoes", "adjusted", [])`; `rule_check("Walkaroo Boys Sandal", "Walkaroo Kids Sandal Sandal", ["Walkaroo"], allowed=["kids sandals"])` gives `("Walkaroo Kids Sandal", "review", ["boys"])`. Ruff check and format pass on the patched file; `tests/unit/test_products.py` against it fails exactly the two tests §2 changes (89 passed); `tests/integration/test_products_run.py` against it passes (30).
- Unchanged: `rewrite_prompt`, the final titles, `dropped_words`, the stored columns, the API and the web app.

### 2. Testing

`tests/unit/test_products.py`:

- `test_rule_check_removes_repeated_tokens`: the expected status for `rule_check("Walkaroo Kids Shoes", "Walkaroo Kids Shoes Shoes", BRAND)` changes from `"adjusted"` to `"pass"`.
- `test_rule_check_drops_a_word_that_repeats_an_earlier_token`: the first case's expected status (`"Walkaroo Kids-Sandal Sandal"`) changes from `"adjusted"` to `"pass"`; the second case (the brand is prepended first) is unchanged.
- New test `test_rule_check_does_not_count_a_removed_repeat`, with the four cases in §1's check: the LC-01 and LC-05 patterns give `pass`; a repeat plus an unbacked word gives `adjusted`; a repeat plus a lost word gives `review`.
- Unchanged: the connector-strip, invented-word, fallback and brand tests, and the integration tests (the main run test's "Walkaroo Kids Summer Sandals Sandals" stays `review`; the Toddler and unbacked-word tests stay `adjusted`).
- No model call and no probe: the rule is deterministic.

### 3. Live check and docs

- **Live check, after merge, with the user's OK at that point:** one `product_run` on dev by the live-check pattern (API queues, `process_job` once, the worker loop never started). Dev is at 0021; no migration. The 8 stored keywords' `keyword_search` rows are fresh: 7 searched 2026-09-29 13:10:34 UTC, fresh until 2026-10-06 13:10 (docs/findings-slice23.md §3), and "mens flip flops" searched 2026-09-30 09:27:13 (docs/findings-slice23.md §3), fresh until 2026-10-07 09:27 (`SEARCH_TTL_DAYS` = 7). So with the same keywords there is no grounded search. Expected cost about 6,600 micros (slice 25's check: 6,587), plus about 38,000 per keyword with no fresh valid row. Writes: the job, the 10 product rows, `api_key.last_used_at`, any new `keyword_search` row.
- **Read-back:** per product, the raw title, the suggested title, the status and the dropped words, stated as observed. *Inferred* expectation: a product whose raw title differs from its final title only by repeats shows `pass`; a product that loses a word shows `review`.
- **Docs:** this spec; the plan; `docs/findings-slice26.md` (probes 1 and 2 from Appendix A2, the live check, every `minor (deferred)` and `parked` ledger line); docs/README.md rows; the `(this commit)` hash convention; a dated correction note in docs/findings-slice25.md §2 for the slice 25 live-check reviewer's optional nit ($10.9464 is called "slice 24's unrounded" figure, though slice 24 wrote "about $10.94 + $0.0064"), with the original sentence kept.
- **Spend so far:** probes 1 and 2 cost 11,211 + 6,757 = 17,968 micros; spend is about $10.97 of the $15 cap.

## Rulings

None.

Correction (2026-09-30, after the process audit): the ledger now records one ruling, added after the audit:

- **R1: the findings §4 lead-in was fixed by the controller, not deferred.** Decided: after the final fix wave's re-review, the controller changed docs/findings-slice26.md §4's lead-in to "From the task reviews and the final review" (7a55220) instead of deferring the re-reviewer's out-of-scope observation. Found by the final fix wave's implementer (a concern) and its re-review (an out-of-scope observation). Why: the lead-in under-described the 8 lines under it, and fixing it avoided a ninth deferred line. Cost if wrong: a process deviation (the skill allows one fix wave and no controller fixes); the change is docs wording only and was re-reviewed. The fix was noted in the ledger when made (as a note, not a ruling); it was named as a ruling in chat and in the ledger only after the process audit.

## Out of scope

- Any change to `rewrite_prompt` (Appendix A1 was designed and probed, not built).
- Overlap between the keyword and the missing words (probe 2's "kids kid"), and the model's word dropping and lower-case appends seen in the probes.
- The deferred items in docs/findings-slice25.md §3.

## Appendix: the prompt route (designed and probed, not built)

### A1. The approach C prompt (designed, not built)

In `rewrite_prompt`, the sentence

> Keep every word of the original title (you may reorder them); add the keyword and the missing terms naturally; never change the product type; repeat no word; no keyword stuffing.

becomes

> Keep every word of the original title (you may reorder them); a word may switch between singular and plural (for example Sandal to Sandals), which counts as the same word, so write only one of the two forms; where a product lists swaps, write the first form of each swap in place of the second ("Sandals for Sandal" means write Sandals, not Sandal); add the keyword and the missing terms naturally; never change the product type; repeat no word in any form; no keyword stuffing.

New function in `products.py`:

```python
def form_swaps(title: str, keyword: str) -> list[str]:
    """Hints for the rewrite: "Sandals for Sandal" when a title word and a
    keyword word have the same folded stems but different tokens, so the
    model writes one form. The first such keyword word per title word; no
    duplicates; none without a keyword."""
    out: list[str] = []
    words = keyword.split()
    for w in title.split():
        stems = fold_set(w)
        for k in words:
            if stems and fold_set(k) == stems and tokens(k) != tokens(w):
                hint = f"{k[:1].upper()}{k[1:]} for {w}"
                if hint not in out:
                    out.append(hint)
                break
    return out
```

`rewrite_prompt` passes each product with a `swaps` field, `[{**p, "swaps": form_swaps(p["title"], p.get("keyword") or "")} for p in products]`, and `_product_lines(..., "keyword", "missing", "swaps", "description", "attributes")`; `_product_lines` already leaves out an empty list. On dev's products (checked 2026-09-30), every product gets a swap: "Sandals for Sandal" (LC-01, 02, 06, 10), "Shoes for Shoe" (LC-03, 08, 09), "Slippers for Slipper" (LC-04, 07), and "Mens for Men" plus "Flops for Flop" (LC-05). LC-05's hint asks for "Mens" in place of the original "Men" because the stored keyword is spelled "mens" (the cache spelling); the clean rewrites in probe 1 already wrote "Mens".

As designed, approach C changed nothing else (not `rule_check`, `run_products`, the stored columns, the other prompts, the API or the web app). It was not built: probe 2 failed (A2).

### A2. Probes 1 and 2

- A scratch script outside the repo reads the brand's name and aliases and dev's 10 products (title, keyword, missing words, description, category, attributes) with read-only queries, in `run_products`' order (`result_at NULLS FIRST, title, id`), sets `index` to 0-9 in that order, and builds the product dicts that `run_products` passes to `rewrite_prompt` (`index`, `title`, `keyword`, `missing`, `description`, `attributes`).
- It calls `judge.generate(prompt, RewriteSet, 0.0)` 3 times with the current `rewrite_prompt` and 3 times with the first-proposed prompt, built as `rewrite_prompt(name, products).replace(<old sentence>, <new sentence>)` so the rest of the prompt is identical. The first-proposed sentence was: "Keep every word of the original title (you may reorder them); a word may switch between singular and plural (for example Sandal to Sandals), which counts as the same word, so write only one of the two forms; add the keyword and the missing terms naturally; never change the product type; repeat no word in any form; no keyword stuffing." There are no database writes and no job.
- For each call and product it records the raw title, whether any word's stems repeat an earlier word's stems (`fold_set`, as `rule_check` does), and `rule_check(title, raw, [brand name, *aliases], allowed=[keyword, description, category, attribute values, missing words])`'s status and dropped words, as `run_products` passes them. The report shows the non-sandal products (LC-03, 04, 05, 07, 08, 09) separately, since the probed sentences' example names sandals.
- **Pass (probe criteria, from the decisions list; the slice's own repeat scope is "any repeat"):** in all 3 calls with the prompt under test, no raw title has a word whose `fold_set` shares a stem with an earlier word's `fold_set` because of a singular/plural pair (the two words share a stem but their casefolded tokens differ, for example "Sandal"/"Sandals"; a same-form repeat such as "Flip"/"Flip", or a repeat of any other kind, is recorded, not counted), and no product's status is `review`.
- **Baseline:** the current prompt's 3 calls. If they show no singular/plural repeat, the probe is inconclusive: stop and report to the user before building.
- **Cost:** 6 calls at about 1,650 micros each (slice 25's 6,587-micro job made 4 calls), about 10,000 micros ($0.01).
- **If probe 1 fails:** stop, report the raw titles, and ask the user about approach B before building (done: see the probe 1 result and the decisions list).

**Probe 1 result (run 2026-09-30 with the user's OK; 6 calls, 11,211 micros, estimate about 10,000; the model reported `gemini-3.5-flash-lite`):** failed. Baseline (current prompt): singular/plural repeats in 10, 9 and 10 of 10 titles, so the probe was conclusive. The first-proposed sentence alone: 10 of 10 titles repeated in call 4 (the model wrote the original type word first and appended the keyword, for example "BSOAgentTestBrand Blue Kid Sandal Boys Kids Sandals"); 0 of 10 in calls 5 and 6, but call 6 gave LC-07 `review` (the raw title "BSOAgentTestBrand Beige Women Slippers" dropped "Casual"). Non-sandal products behaved like the sandal products. Temperature 0.0 did not make the calls repeatable.

**Probe 2 result (approach C, run 2026-09-30 with the user's OK; 3 calls, 6,757 micros, estimate about 5,000 to 6,000; the model reported `gemini-3.5-flash-lite`; the prompt is A1's sentence plus a `swaps` list per product, built from a scratch copy of A1's `form_swaps`; the baseline is probe 1's):** failed. Call 1: no repeats, but LC-06 ("BSOAgentTestBrand Brown Men Sandals") and LC-07 ("BSOAgentTestBrand Beige Slippers for Women") were `review`, both dropping "Casual". Calls 2 and 3: LC-01 and LC-02 repeated "kids kid" (the keyword and the missing word, for example "BSOAgentTestBrand Blue Boys Sandals kids kid") and were `adjusted`; the other 8 were `pass`. The model also appended lower-case words ("kids", "men", "footbed").
