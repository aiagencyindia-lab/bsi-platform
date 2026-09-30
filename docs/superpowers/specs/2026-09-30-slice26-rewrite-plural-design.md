# Slice 26 design: the rewrite keeps one form of each word

## Context

Slice 25's live check (docs/findings-slice25.md §2, job `08939d2b`) stored the rewrite call's raw titles for the first time. All 10 of them end with the original title's type word or its plural (LC-09 ends with "Shoes"; its original has "Shoe"), after a plural or singular form of it earlier in the title. One example is LC-01: "BSOAgentTestBrand Blue Kid Sandals Boys Sandal" for the original "BSOAgentTestBrand Boys Sandal Blue". `rule_check`'s repeat-stem drop removed the repeat each time, so every suggested title was clean, but every status was `adjusted`.

*Inferred* cause: `rewrite_prompt` (`packages/core/bsi_core/products.py`) says "Keep every word of the original title (you may reorder them); add the keyword and the missing terms naturally; never change the product type; repeat no word; no keyword stuffing." *Inferred*: with the keyword "kids sandals" and the original word "Sandal", the model keeps "Sandal" and adds "Sandals".

Classification, said in chat as the first line of the first brainstorming reply: **architectural** — "The fix changes the rewrite prompt or the rule check, and every product run passes through both. The process also calls for a spec even for small changes."

Decisions approved in chat (brainstorming on Opus 5.5, 2026-09-30). Each question below had its options described in the question, and each design section's text was in chat before its approval question:

- **Goal:** a clean raw rewrite. The prompt stops the model from writing both forms of a word, so statuses reflect real edits. Rejected: "honest status only" (make the rule check not count the removed repeat), and doing both.
- **Success test:** probe 3 + 3 rewrite calls on dev's 10 products before building (current prompt, then the new prompt). Rejected: judging on the post-merge live check only; 5 + 5 calls.
- **Probe criteria (from the spec review, put to the user as a question and approved in chat):** only singular/plural repeats count against the pass rule (other repeats are recorded); a baseline with no singular/plural repeat makes the probe inconclusive.
- **Approach A:** reword the prompt's keep rule. Approaches B (the code gives each product a per-product "use X in place of Y" hint) and C (A and B together) were described in chat with trade-offs; A was recommended and chosen, with B to be put to the user if A fails the probe.
- **After probe 1 failed (§2), approach C:** the user chose "Probe C: sentence + hint" over B alone, accepting A as is, or stopping. The revised §1 design text (the sentence plus per-product swaps, probe 2, the tests) was put in chat and approved.
- **Swap rule (from the spec review, put to the user as a question and approved in chat):** a hint only when the title word and the keyword word have the same folded stems and different tokens, so a hyphenated word such as "Flip-Flop" gets no hint that would lose a word.

Codebase facts (main `aa62285`, checked 2026-09-30):

- `rewrite_prompt(brand, products)` returns one string, and `run_products` sends it with `RewriteSet` at temperature 0.0, once per batch.
- `rule_check("BSOAgentTestBrand Boys Sandal Blue", "BSOAgentTestBrand Blue Kid Sandals Boys", ["BSOAgentTestBrand"], allowed=["kids sandals", "kid"])` returns `("BSOAgentTestBrand Blue Kid Sandals Boys", "pass", [])`. The same call with a trailing " Sandal" on the suggestion returns the same title with `"adjusted"`. `rule_check("BSOAgentTestBrand Boys School Shoe Black", "BSOAgentTestBrand Black Kids School Shoes Boys", ...)` returns `"pass"` (with `["BSOAgentTestBrand"], allowed=["kids sandals", "kid"]`, the same arguments as the first call). So swapping a word for its plural is neither a lost word nor an adjustment (checked 2026-09-30).
- `tests/unit/test_products.py` has `test_prompts_ask_for_plural_kids_keywords_and_kept_words`, which asserts `"Keep every word" in rewrite_prompt("Walkaroo", [])`, and a prompt test that asserts `"summer"` and `"150"` in a rewrite prompt. `tests/unit/test_recommend_copy.py` scans `rewrite_prompt("Acme", [])` against the banned-word list.

## Design

### 1. The prompt change (approach C: sentence plus per-product swaps)

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

Nothing else changes: `rule_check`, `run_products`, the stored columns, the other prompts, the API, and the web app. If probe 2 leads to a different wording, the new wording is put to the user before it is built.

### 2. Probe 1 (run 2026-09-30) and probe 2

- A scratch script outside the repo reads the brand's name and aliases and dev's 10 products (title, keyword, missing words, description, category, attributes) with read-only queries, in `run_products`' order (`result_at NULLS FIRST, title, id`), sets `index` to 0-9 in that order, and builds the product dicts that `run_products` passes to `rewrite_prompt` (`index`, `title`, `keyword`, `missing`, `description`, `attributes`).
- It calls `judge.generate(prompt, RewriteSet, 0.0)` 3 times with the current `rewrite_prompt` and 3 times with the first-proposed prompt, built as `rewrite_prompt(name, products).replace(<old sentence>, <new sentence>)` so the rest of the prompt is identical. The first-proposed sentence was: "Keep every word of the original title (you may reorder them); a word may switch between singular and plural (for example Sandal to Sandals), which counts as the same word, so write only one of the two forms; add the keyword and the missing terms naturally; never change the product type; repeat no word in any form; no keyword stuffing." There are no database writes and no job.
- For each call and product it records the raw title, whether any word's stems repeat an earlier word's stems (`fold_set`, as `rule_check` does), and `rule_check(title, raw, [brand name, *aliases], allowed=[keyword, description, category, attribute values, missing words])`'s status and dropped words, as `run_products` passes them. The report shows the non-sandal products (LC-03, 04, 05, 07, 08, 09) separately, since the prompt's example names sandals.
- **Pass:** in all 3 calls with the prompt under test, no raw title has a word whose `fold_set` shares a stem with an earlier word's `fold_set` because of a singular/plural pair (the two words share a stem but their casefolded tokens differ, for example "Sandal"/"Sandals"; a same-form repeat such as "Flip"/"Flip", or a repeat of any other kind, is recorded, not counted), and no product's status is `review`.
- **Baseline:** the current prompt's 3 calls. If they show no singular/plural repeat, the probe is inconclusive: stop and report to the user before building.
- **Cost:** 6 calls at about 1,650 micros each (slice 25's 6,587-micro job made 4 calls), about 10,000 micros ($0.01).
- **If probe 1 fails:** stop, report the raw titles, and ask the user about approach B before building (done: see the probe 1 result and the decisions list).

**Probe 1 result (run 2026-09-30 with the user's OK; 6 calls, 11,211 micros, estimate about 10,000; the model reported `gemini-3.5-flash-lite`):** failed. Baseline (current prompt): singular/plural repeats in 10, 9 and 10 of 10 titles, so the probe was conclusive. The first-proposed sentence alone: 10 of 10 titles repeated in call 4 (the model wrote the original type word first and appended the keyword, for example "BSOAgentTestBrand Blue Kid Sandal Boys Kids Sandals"); 0 of 10 in calls 5 and 6, but call 6 gave LC-07 `review` (the raw title "BSOAgentTestBrand Beige Women Slippers" dropped "Casual"). Non-sandal products behaved like the sandal products. Temperature 0.0 did not make the calls repeatable.

**Probe 2 (approach C; the user approves the spend first):** the same script and read-only queries, 3 calls with the §1 prompt built from a scratch copy of the planned `form_swaps` and `rewrite_prompt` (the baseline is probe 1's). The same pass rule. About 5,000 to 6,000 micros (probe 1's new-prompt calls cost 1,392 to 2,002 each). If it fails: stop and report to the user before building.

### 3. Testing

- `tests/unit/test_products.py`, new test `test_rewrite_prompt_keeps_one_form_of_each_word`: asserts `"singular and plural" in rp`, `"write only one of the two forms" in rp`, `"lists swaps" in rp` and `"repeat no word in any form" in rp`, where `rp = rewrite_prompt("Walkaroo", [])`.
- New test `test_form_swaps`: `form_swaps("BSOAgentTestBrand Boys Sandal Blue", "kids sandals") == ["Sandals for Sandal"]`; `form_swaps("BSOAgentTestBrand Men Flip Flop Navy", "mens flip flops") == ["Mens for Men", "Flops for Flop"]`; `form_swaps("BSOAgentTestBrand Boys School Shoe Black", "kids shoes") == ["Shoes for Shoe"]`; `form_swaps("BSOAgentTestBrand Women Casual Slipper Beige", "women slippers") == ["Slippers for Slipper"]`; `form_swaps("Walkaroo Kids Sandals", "kids sandals") == []` (same forms); `form_swaps("Walkaroo Boys Sandal", "") == []`; `form_swaps("Walkaroo Flip-Flop Navy", "flip flops") == []` (a hyphenated word with two stems).
- New test `test_rewrite_prompt_lists_swaps`: `rewrite_prompt("Walkaroo", [{"index": 0, "title": "Walkaroo Boys Sandal", "keyword": "kids sandals"}])` contains `'"swaps": ["Sandals for Sandal"]'`, and `rewrite_prompt("Walkaroo", [{"index": 0, "title": "Walkaroo Kids Sandals", "keyword": "kids sandals"}])` does not contain `'"swaps"'` (the JSON key with its quotes; the prompt sentence has the bare word).
- The existing "Keep every word" and "summer"/"150" assertions stay and still pass.
- `tests/unit/test_recommend_copy.py` already scans `rewrite_prompt`; no change.
- No integration test: the fake generator returns a fixed title, so it cannot show the model's behaviour. The probe and the live check are the evidence.

### 4. Live check and docs

- **Live check, after merge, with the user's OK at that point:** one `product_run` on dev by the live-check pattern (API queues, `process_job` once, the worker loop never started). Dev is at 0021; no migration. The 8 stored keywords' `keyword_search` rows are fresh: 7 searched 2026-09-29 13:10:34 UTC, fresh until 2026-10-06 13:10 (docs/findings-slice23.md §3), and "mens flip flops" searched 2026-09-30 09:27:13 (docs/findings-slice23.md §3), fresh until 2026-10-07 09:27 (`SEARCH_TTL_DAYS` = 7). So with the same keywords there is no grounded search. Expected cost about 6,600 micros (slice 25's check: 6,587), plus about 38,000 per keyword with no fresh valid row. Writes: the job, the 10 product rows, `api_key.last_used_at`, any new `keyword_search` row.
- **Read-back:** per product, whether the raw title has a singular/plural repeat (as in §2) and any other repeat, recorded separately, and `rule_check`'s status and dropped words, stated as observed.
- **Docs:** this spec, the plan, `docs/findings-slice26.md` (the probe results, the live check, every `minor (deferred)` and `parked` ledger line), docs/README.md rows, and the `(this commit)` hash convention. The slice 25 live-check reviewer's optional wording nit (docs/findings-slice25.md §2 calls $10.9464 "slice 24's unrounded" figure, though slice 24 wrote "about $10.94 + $0.0064") gets a dated correction note in docs/findings-slice25.md, with the original sentence kept.

## Rulings

None.

## Out of scope

- Any change to `rule_check`, the status rules, or the stored columns.
- Swaps from missing words, or from any words other than the keyword's.
- Other repeats the model may make that are not singular/plural forms.
- The deferred items in docs/findings-slice25.md §3.
