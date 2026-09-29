# Slice 22 design: missing words backed by product data

## Context

Slice 21's dev re-check (docs/findings-slice21.md §2, job `f9de4eb9`) left three problems in the product wedge's suggestions, observed:

1. **Category drift.** "Boots" is suggested for the LC-03 and LC-09 shoes, and "Slide" for the LC-06 sandal.
2. **Retailer phrasing.** LC-10 got the missing words footbed, available, slide, strap, wide, width, and the suggestion "…Tan Sandal Women Footbed Available Slide Strap Wide Width".
3. **Size markers.** "Toddler" is suggested for LC-01 and LC-02.

Classification, said in chat as the first line of the first brainstorming reply: **architectural** — "it changes how missing words and rewrites are chosen across three separate behaviours in `products.py`, the design choices are open (cap vs. generic-word test), and your rule is a spec even for small changes." (The design that followed changes one function and its call site; slice 21, of similar size, was classed bounded. The process is the same either way: spec, plan and the full review cycle.)

Decisions approved in chat (brainstorming on Fable 5.1, 2026-09-29). Sections 1 and 2 each had their design text in chat before their approval, and so did the revised Section 1:

- **Scope:** the three problems. The colour keyword vote ("navy flip flops") is out.
- **Subtype words** ("Slide", "Footbed"): suggested only if the product's own data backs them. Rejected: suggest when most titles use the word, and suggest but flag for review (needs a way to show which words are unconfirmed).
- **Approach, first choice:** A, a backing filter on every missing word. Rejected B (A plus a judge call so near-matches count: more cost per run and more model output to validate).
- **Approach, after the spec review:** the controller had told the user that "slide" is in 3 of the 5 women-sandals titles, and rejected approach C (a title threshold plus a size-word list) because LC-10 would still get "Slide". The count is 2 of 5, so that reason was wrong. Asked again with the corrected count, the user chose **both rules**: a word must be backed by product data and be in more than half of the ranking titles. No size-word list.
- **Rule 2's form:** more than half of the stored titles, never fewer than 2. Rejected: a fixed 3 titles (a keyword with fewer than 3 stored titles could suggest nothing, and the 7 existing `missing` unit tests would change).
- **The rival-exclusion integration test** (review finding 2): its fixtures are reworked so that only the exclusions remove the rival words. Rejected: covering exclusions by unit tests only, and removing the exclusions.
- **"-es" plurals** (review finding 6): the backing set is built with `_allowed_stems`, so `missing` and `rule_check` fold the same way. Rejected: leaving it as a known ceiling.

Codebase facts (main `2c5e7b0`, checked 2026-09-29 by running the current code):

- `missing(product_title, titles, brand_names, exclude=(), keyword="")` has one non-test caller, `run_products`.
- In `run_products`, `missing` runs in one loop over the batch's products, before the rewrite call. `rule_check` runs in a second loop after it.
- `run_products` builds, for `rule_check`, `allowed=[p["keyword"], *p["missing"], p["description"] or "", p["category"] or "", *(str(v) for v in (p["attributes"] or {}).values())]`.
- `_allowed_stems("", ["watches"], [])` returns the stems `watch` and `watche`; `fold_set("watches")` returns `watche` only.
- With the women-sandals titles below, product title "BSOAgentTestBrand Women Sandal Tan", brand `["BSOAgentTestBrand"]` and `keyword="women sandals"`, `missing` returns `["footbed", "available", "slide", "strap", "wide", "width"]`.
- With the kids-sandals titles, product title "BSOAgentTestBrand Boys Sandal Blue" and `keyword="kids sandals"` (no `exclude`), `missing` returns `["kid", "toddler", "josmo"]`.
- With the kids-shoes titles, product title "BSOAgentTestBrand Kids Sports Shoe Black" and `keyword="kids shoes"` (no `exclude`), `missing` returns `["nike", "boots"]`.
- Title counts in the stored dev titles, out of 5 each: "boots" 2 (kids shoes); "slide" 2 (men sandals); "footbed" 4, and "slide", "strap", "wide", "width", "available" 2 each (women sandals); "toddler" 4 and "kid" 5 (kids sandals).
- All 10 dev products have a description, a category and the attributes `size` and `color`.
- The 7 existing `missing` unit tests use 2 or 3 ranking titles.
- In `tests/integration/test_products_run.py`, `_seed(owner, org, bid, n)` creates products with a title only. Exactly two tests assert a non-empty `missing_keywords`, both `["summer"]`: `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` (2 stored titles) and `test_rival_brands_models_and_competitors_are_not_missing_words` (4 titles in `RIVAL_TITLES`, each rival word in 2 of them). Every other `missing_keywords` assertion there is `[]` or `None`.

The ranking titles used above and in the tests, as stored in dev's `keyword_search`:

- **women sandals (`WS`):** "Women's Double Strap Footbed Sandals"; "Women's Footbed Slide Sandals, Wide Width Available"; "Men's and Women's Unisex Baya II Slide Sandals"; "Women's Faux Suede Thong Footbed Sandals"; "Women's Asymmetric Strap Footbed Sandals, Wide Width Available".
- **kids sandals (`KS`):** "MIA - Lolli (Toddler/Little Kid)"; "Josmo - Cars Lighted Sandal (Toddler/Little Kid)"; "Naturino - Flower Mountain Nazca 2 Junior (Little Kid)"; "Teva - Toachi Hydratrek (Toddler/Little Kid/Big Kid)"; "Josmo - Spiderman Sandals (Toddler/Little Kid)".
- **kids shoes (`KSH`):** "Nike A'Two A'ja Wilson Big Kids' Basketball Shoes"; "Nike Free Ride Little Kids' Running Shoes"; "Nike Woodside 2 High Big Kids' Boots"; "Nike Manoa 17 Big Kids' Boots"; "Nike Air Max 270 Big Kids' Shoes".

## Design

All code changes are in `packages/core/bsi_core/products.py`.

### 1. Two rules in `missing`

`missing(product_title, titles, brand_names, exclude=(), keyword="", backing=None)` gains `backing: Sequence[str] | None = None`.

**Rule 1, backing.**

- When `backing` is not `None`, a ranking-title token is skipped unless its stem is in `_allowed_stems("", backing, [])`. That is `fold_set(" ".join(backing))` plus the singular of every backing token that ends in "es" and is longer than 3 characters.
- The check sits beside the existing `have` and `NOISE_STEMS` checks in the loop.
- When `backing` is `None` (the default), rule 1 is off.

**Rule 2, more than half the titles.**

- A word must be in at least `max(MIN_TITLES, len(titles) // 2 + 1)` titles: 2 of 2, 2 of 3, 3 of 4, 3 of 5.
- It replaces `n >= MIN_TITLES` in the ranking step and applies always, with or without `backing`. `MIN_TITLES` stays 2.

**Unchanged checks.** At least 3 characters, not a number, not in `STOPWORDS`, not in `NOISE_STEMS`, not in `have` (the product title, the brand's names, `exclude` minus the keyword's stems), at most `MAX_MISSING` words, ranked by title count then stem.

**`run_products`.** The first loop stores the list on the product's dict and passes it to `missing`; the second loop reuses it for `rule_check`:

```python
p["backing"] = [
    p["keyword"],
    p["description"] or "",
    p["category"] or "",
    *(str(v) for v in (p["attributes"] or {}).values()),
]
p["missing"] = missing(..., keyword=p["keyword"], backing=p["backing"])
...
rule_check(..., allowed=[*p["backing"], *p["missing"]])
```

- `rule_check`'s `allowed` holds the same texts as today, in a different order. `_allowed_stems` builds a set, so the order does not matter.
- Behaviour that follows, not a separate change: a ranking word that is not backed is neither a missing word nor in `allowed`, so if the rewrite adds it on its own, `rule_check` drops it (status `adjusted`).

**Comments and docstrings.**

- The docstring of `missing` names both rules.
- The `NOISE_WORDS` comment's last clause ("toddler/youth/infant are not listed, and "kid" from "Little Kid" is still suggested") is replaced: such a word is now suggested only when the product data backs it.
- Known ceilings, in a `# ponytail:` comment:
  - Stems must match exactly, apart from the "-es" singular: "cushioned" does not back "cushion".
  - A product with no description, category or attributes gets only words of its keyword.
  - A colour or size word in the attributes ("blue") is still not suggested, because `NOISE_STEMS` is checked too.
  - A word the product data backs but only 2 of 5 titles use is not suggested.

**Unchanged:** `search_query`, `titles_prompt`, `keep_present`, `drop_stores`, `TITLES_PARSE`, the cache-hit rule, `rule_check`, `_allowed_stems`, `rewrite_prompt`, the schema, the API and the web app. Cached `keyword_search` rows stay valid.

### 2. Testing

Unit, `tests/unit/test_products.py`. `B` is `["BSOAgentTestBrand"]`, and `WSB` is `["women sandals", "Flat sandal with a cushioned footbed", "Sandals", "7", "tan"]`:

- Rule 1 and rule 2 together: `missing("BSOAgentTestBrand Women Sandal Tan", WS, B, keyword="women sandals", backing=WSB) == ["footbed"]`.
- A size marker: `missing("BSOAgentTestBrand Boys Sandal Blue", KS, B, keyword="kids sandals", backing=["kids sandals", "Lightweight EVA sandal with a hook-and-loop strap", "Sandals", "3", "blue"]) == ["kid"]`.
- A different product type: `missing("BSOAgentTestBrand Kids Sports Shoe Black", KSH, B, keyword="kids shoes", backing=["kids shoes", "Breathable mesh running shoe for school and play", "Shoes", "4", "black"]) == []`.
- Empty backing: `missing("BSOAgentTestBrand Women Sandal Tan", WS, B, keyword="women sandals", backing=[]) == []`.
- Rule 2 alone: `missing("BSOAgentTestBrand Women Sandal Tan", WS, B, keyword="women sandals") == ["footbed"]` (today `["footbed", "available", "slide", "strap", "wide", "width"]`).
- Rule 2 over a backed word: `missing("BSOAgentTestBrand Women Sandal Tan", WS, B, keyword="women sandals", backing=[*WSB, "adjustable strap, wide width"]) == ["footbed"]`.
- The "-es" singular: `missing("Titan Analog Dial", ["Titan Men Watch", "Fossil Men Watch"], ["Titan"], keyword="men watches", backing=["men watches"]) == ["men", "watch"]`.
- The 7 existing `missing` unit tests pass no `backing`, use 2 or 3 titles, and keep their expected values.

Integration, `tests/integration/test_products_run.py`:

- `_seed` gains `description=None`, passed to every product it creates. Callers that do not pass it are unchanged.
- `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` seeds with `description="Summer sandal"`. Its expected values stay (`["summer"]`, "Walkaroo Kids Summer Sandals", `review`, `["boys"]`).
- `test_rival_brands_models_and_competitors_are_not_missing_words` is reworked so that only the exclusions remove the rival words:
  - It seeds with `description="Summer sandal, an alternative to Crocs and Teva Hurricane"`.
  - `RIVAL_TITLES` becomes 3 titles, so a word needs 2: `("Teva Hurricane Summer Sandals", "Teva", "Hurricane")`, `("Crocs Teva Hurricane Summer Slides", "Teva", "Hurricane")`, `("Crocs Summer Sandals", "", "")`.
  - Its expected value stays `["summer"]`, and its comment stays "Without the exclusions: ["summer", "crocs", "hurricane", "teva"]".
  - The plan re-proves slice 20's R5 check by the same change: with `for n in (c.name, *c.aliases)` changed to `for n in (c.name,)` in `run_products`, this test fails with "crocs" in the missing words. The file is then restored from a backup.
- Two new tests, backed and unbacked words end to end, one per rewrite below. Each seeds and runs on its own. One product, seeded with `description="Summer sandal for daily wear"`; the answer text and the parsed titles hold "Kids Summer Sandals Lightweight" and "Boys Summer Sandals Lightweight"; the keyword is the fake generator's default, "kids sandals".
  - With `rewrite="Walkaroo Boys Summer Sandal 0"`: `missing_keywords == ["summer"]`, `suggested_title == "Walkaroo Boys Summer Sandal 0"`, `rule_check == "pass"`.
  - With `rewrite="Walkaroo Boys Lightweight Summer Sandal 0"`: `missing_keywords == ["summer"]`, `suggested_title == "Walkaroo Boys Summer Sandal 0"`, `rule_check == "adjusted"`.
- A description also goes to `fit_rank` and `rewrite_prompt`. With the keyword "kids sandals" and the fake generator's fixed output, no other expected value changes.

Copy: the new fixtures and comments are checked against `FORBIDDEN` in `tests/unit/test_recommend_copy.py`. No prompt changes, so `PRODUCT_CASES` is unchanged.

### 3. Dev re-check

Run by the controller only with the user's OK at that point, by the live-check pattern (the worker loop is never started).

- Expected cost: about 6,000 micros ($0.01). That is 4 flash-lite calls (3 keyword samples and 1 rewrite, for one batch of 10) at about 1,500 micros each, and no grounded searches, because the 8 current-keyword rows were searched on 2026-09-29 and stay fresh for 7 days.
- Each keyword the vote picks that is not one of those 8 adds one grounded search, about 37,500 micros.
- Writes: the job, 10 product rows, `api_key.last_used_at`, and a `keyword_search` row for any new keyword.
- Expected missing words, *inferred* from the stored titles and product data, to be compared with what is observed: LC-01 and LC-02 "kid"; LC-09 "kids"; LC-10 "footbed"; none for LC-03, LC-04, LC-05, LC-06, LC-07 and LC-08.

## Out of scope

- The keyword vote choosing a colour phrase ("navy flip flops").
- Near-matches and synonyms between a ranking-title word and the product data.
- The deferred minors in docs/findings-slice21.md §3.
