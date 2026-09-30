# Slice 26 design: the rewrite keeps one form of each word

## Context

Slice 25's live check (docs/findings-slice25.md §2, job `08939d2b`) stored the rewrite call's raw titles for the first time. All 10 of them end with the original title's type word after a plural or singular form of it earlier in the title. One example is LC-01: "BSOAgentTestBrand Blue Kid Sandals Boys Sandal" for the original "BSOAgentTestBrand Boys Sandal Blue". `rule_check`'s repeat-stem drop removed the repeat each time, so every suggested title was clean, but every status was `adjusted`.

The cause is in `rewrite_prompt` (`packages/core/bsi_core/products.py`). It says "Keep every word of the original title (you may reorder them); add the keyword and the missing terms naturally; never change the product type; repeat no word; no keyword stuffing." With the keyword "kids sandals" and the original word "Sandal", the model keeps "Sandal" and adds "Sandals".

Classification, said in chat as the first line of the first brainstorming reply: **architectural** — "The fix changes the rewrite prompt or the rule check, and every product run passes through both. The process also calls for a spec even for small changes."

Decisions approved in chat (brainstorming on Opus 5.5, 2026-09-30). Each question below had its options described in the question, and each design section's text was in chat before its approval question:

- **Goal:** a clean raw rewrite. The prompt stops the model from writing both forms of a word, so statuses reflect real edits. Rejected: "honest status only" (make the rule check not count the removed repeat), and doing both.
- **Success test:** probe 3 + 3 rewrite calls on dev's 10 products before building (current prompt, then the new prompt). Rejected: judging on the post-merge live check only; 5 + 5 calls.
- **Approach A:** reword the prompt's keep rule. Approaches B (the code gives each product a per-product "use X in place of Y" hint) and C (A and B together) were described in chat with trade-offs; A was recommended and chosen, with B to be put to the user if A fails the probe.

Codebase facts (main `aa62285`, checked 2026-09-30):

- `rewrite_prompt(brand, products)` returns one string, and `run_products` sends it with `RewriteSet` at temperature 0.0, once per batch.
- `rule_check("BSOAgentTestBrand Boys Sandal Blue", "BSOAgentTestBrand Blue Kid Sandals Boys", ["BSOAgentTestBrand"], allowed=["kids sandals", "kid"])` returns `("BSOAgentTestBrand Blue Kid Sandals Boys", "pass", [])`. The same call with a trailing " Sandal" on the suggestion returns the same title with `"adjusted"`. `rule_check("BSOAgentTestBrand Boys School Shoe Black", "BSOAgentTestBrand Black Kids School Shoes Boys", ...)` returns `"pass"`. So swapping a word for its plural is neither a lost word nor an adjustment (checked 2026-09-30).
- `tests/unit/test_products.py` has `test_prompts_ask_for_plural_kids_keywords_and_kept_words`, which asserts `"Keep every word" in rewrite_prompt("Walkaroo", [])`, and a prompt test that asserts `"summer"` and `"150"` in a rewrite prompt. `tests/unit/test_recommend_copy.py` scans `rewrite_prompt("Acme", [])` against the banned-word list.

## Design

### 1. The prompt change

In `rewrite_prompt`, the sentence

> Keep every word of the original title (you may reorder them); add the keyword and the missing terms naturally; never change the product type; repeat no word; no keyword stuffing.

becomes

> Keep every word of the original title (you may reorder them); a word may switch between singular and plural (for example Sandal to Sandals), which counts as the same word, so write only one of the two forms; add the keyword and the missing terms naturally; never change the product type; repeat no word in any form; no keyword stuffing.

Nothing else changes: `rule_check`, `run_products`, the stored columns, the other prompts, the API, and the web app. If the probe (§2) leads to a different wording, the new wording is put to the user before it is built.

### 2. The probe (before building; the user approves the spend first)

- A scratch script outside the repo reads dev's 10 products with one read-only query (title, keyword, missing words, description, attributes), and builds the product dicts that `run_products` passes to `rewrite_prompt` (`index`, `title`, `keyword`, `missing`, `description`, `attributes`).
- It calls `judge.generate(prompt, RewriteSet, 0.0)` 3 times with the current `rewrite_prompt` and 3 times with the §1 prompt (from a patched copy of `products.py` in the scratch directory). There are no database writes and no job.
- For each call and product it records the raw title, whether any word's stems repeat an earlier word's stems (`fold_set`, as `rule_check` does), and `rule_check`'s status and dropped words (with `allowed = [keyword, description, category, attribute values, missing words]`, as `run_products` passes).
- **Pass:** in all 3 calls with the §1 prompt, no raw title repeats a stem and no product's status is `review`. The current prompt's 3 calls are the baseline.
- **Cost:** 6 calls at about 1,500 micros each, about 9,000 micros ($0.009).
- **If it fails:** stop, report the raw titles, and ask the user about approach B before building.

### 3. Testing

- `tests/unit/test_products.py`, new test `test_rewrite_prompt_keeps_one_form_of_each_word`: asserts `"singular and plural" in rp`, `"write only one of the two forms" in rp` and `"repeat no word in any form" in rp`, where `rp = rewrite_prompt("Walkaroo", [])`.
- The existing "Keep every word" and "summer"/"150" assertions stay and still pass.
- `tests/unit/test_recommend_copy.py` already scans `rewrite_prompt`; no change.
- No integration test: the fake generator returns a fixed title, so it cannot show the model's behaviour. The probe and the live check are the evidence.

### 4. Live check and docs

- **Live check, after merge, with the user's OK at that point:** one `product_run` on dev by the live-check pattern (API queues, `process_job` once, the worker loop never started). Dev is at 0021; no migration. The 9 fresh valid `keyword_search` rows last until 2026-10-06 13:10 UTC ("mens flip flops" until 2026-10-07 09:27), so with the same keywords there is no grounded search. Expected cost about 6,600 micros (slice 25's check: 6,587), plus about 38,000 per keyword with no fresh valid row. Writes: the job, the 10 product rows, `api_key.last_used_at`, any new `keyword_search` row.
- **Read-back:** per product, whether the raw title repeats a stem, and `rule_check`'s status and dropped words, stated as observed.
- **Docs:** this spec, the plan, `docs/findings-slice26.md` (the probe results, the live check, every `minor (deferred)` and `parked` ledger line), README rows, and the `(this commit)` hash convention. The slice 25 live-check reviewer's optional wording nit (docs/findings-slice25.md §2 calls $10.9464 "slice 24's unrounded" figure, though slice 24 wrote "about $10.94 + $0.0064") gets a dated correction note in docs/findings-slice25.md, with the original sentence kept.

## Rulings

None.

## Out of scope

- Any change to `rule_check`, the status rules, or the stored columns.
- Per-product swap hints (approach B), unless the probe fails and the user chooses it.
- Other repeats the model may make that are not singular/plural forms.
- The deferred items in docs/findings-slice25.md §3.
