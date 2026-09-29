# Slice 22 design: missing words backed by product data

## Context

Slice 21's dev re-check (docs/findings-slice21.md §2, job `f9de4eb9`) left three problems in the product wedge's suggestions, observed:

1. **Category drift.** "Boots" is suggested for the LC-03 and LC-09 shoes, and "Slide" for the LC-06 sandal.
2. **Retailer phrasing.** LC-10 got the missing words footbed, available, slide, strap, wide, width, and the suggestion "…Tan Sandal Women Footbed Available Slide Strap Wide Width".
3. **Size markers.** "Toddler" is suggested for LC-01 and LC-02.

Classification, said in chat as the first line of the first brainstorming reply: **architectural** — "it changes how missing words and rewrites are chosen across three separate behaviours in `products.py`, the design choices are open (cap vs. generic-word test), and your rule is a spec even for small changes." (The design that followed is one new argument to one function; slice 21, of similar size, was classed bounded. The process is the same either way: spec, plan and the full review cycle.)

Decisions approved in chat (brainstorming on Fable 5.1 in plan mode, 2026-09-29). Sections 1 and 2 each had their design text in chat before their approval:

- **Scope:** the three problems. The colour keyword vote ("navy flip flops") is out.
- **Subtype words** ("Slide", "Footbed"): suggested only if the product's own data backs them. Rejected: suggest when most titles use the word (LC-10 keeps "Slide"), and suggest but flag for review (needs a way to show which words are unconfirmed).
- **Approach A:** a backing filter on every missing word. Rejected B (A plus a judge call so near-matches count: more cost per run and more model output to validate) and C (a 3-of-5 title threshold plus a size-word list: LC-10 would still get "Slide").

Codebase facts (main `2c5e7b0`, checked 2026-09-29 by running the current code):

- `missing(product_title, titles, brand_names, exclude=(), keyword="")` has one non-test caller, `run_products`.
- `run_products` already builds, for `rule_check`, `allowed=[p["keyword"], *p["missing"], p["description"] or "", p["category"] or "", *(str(v) for v in (p["attributes"] or {}).values())]`.
- With the women-sandals titles below, product title "BSOAgentTestBrand Women Sandal Tan", brand `["BSOAgentTestBrand"]` and `keyword="women sandals"`, `missing` returns `["footbed", "available", "slide", "strap", "wide", "width"]`. Of those, only "footbed" has its stem in `fold_set("women sandals Flat sandal with a cushioned footbed Sandals 7 tan")`.
- With the kids-sandals titles, product title "BSOAgentTestBrand Boys Sandal Blue" and `keyword="kids sandals"` (no `exclude`), `missing` returns `["kid", "toddler", "josmo"]`. Only "kid" has its stem in the backing "kids sandals", "Lightweight EVA sandal with a hook-and-loop strap", "Sandals", "3", "blue".
- With the kids-shoes titles, product title "BSOAgentTestBrand Kids Sports Shoe Black" and `keyword="kids shoes"` (no `exclude`), `missing` returns `["nike", "boots"]`. Neither has its stem in the backing "kids shoes", "Breathable mesh running shoe for school and play", "Shoes", "4", "black".
- The word counts in the stored dev titles: "boots" 2 of 5 (kids shoes), "slide" 2 of 5 (men sandals), "wide", "width", "available", "strap" 2 of 5 each and "slide" 3 of 5, "footbed" 4 of 5 (women sandals), "toddler" 4 of 5 (kids sandals).
- All 10 dev products have a description, a category and the attributes `size` and `color`.
- `tests/integration/test_products_run.py`'s `_seed` creates products with a title only. Two of its tests assert `missing_keywords == ["summer"]` (lines 214 and 505), and the first also asserts the suggestion "Walkaroo Kids Summer Sandals".

The ranking titles used above and in the tests, as stored in dev's `keyword_search`:

- **women sandals:** "Women's Double Strap Footbed Sandals"; "Women's Footbed Slide Sandals, Wide Width Available"; "Men's and Women's Unisex Baya II Slide Sandals"; "Women's Faux Suede Thong Footbed Sandals"; "Women's Asymmetric Strap Footbed Sandals, Wide Width Available".
- **kids sandals:** "MIA - Lolli (Toddler/Little Kid)"; "Josmo - Cars Lighted Sandal (Toddler/Little Kid)"; "Naturino - Flower Mountain Nazca 2 Junior (Little Kid)"; "Teva - Toachi Hydratrek (Toddler/Little Kid/Big Kid)"; "Josmo - Spiderman Sandals (Toddler/Little Kid)".
- **kids shoes:** "Nike A'Two A'ja Wilson Big Kids' Basketball Shoes"; "Nike Free Ride Little Kids' Running Shoes"; "Nike Woodside 2 High Big Kids' Boots"; "Nike Manoa 17 Big Kids' Boots"; "Nike Air Max 270 Big Kids' Shoes".

## Design

All code changes are in `packages/core/bsi_core/products.py`.

### 1. The backing rule in `missing`

- `missing(product_title, titles, brand_names, exclude=(), keyword="", backing=None)` gains `backing: Sequence[str] | None = None`.
- When `backing` is not `None`, a ranking-title token is skipped unless its stem is in `fold_set(" ".join(backing))`. The check sits beside the existing `have` and `NOISE_STEMS` checks in the loop.
- When `backing` is `None` (the default), `missing` behaves as it does today.
- Every other check is unchanged and still applies: at least 3 characters, not a number, not in `STOPWORDS`, not in `NOISE_STEMS`, not in `have` (the product title, the brand's names, `exclude` minus the keyword's stems), in at least `MIN_TITLES` titles, at most `MAX_MISSING` words, ranked by title count then stem.
- `run_products` builds the list once per product and uses it for both calls:

```python
backing = [
    p["keyword"],
    p["description"] or "",
    p["category"] or "",
    *(str(v) for v in (p["attributes"] or {}).values()),
]
p["missing"] = missing(..., keyword=p["keyword"], backing=backing)
...
rule_check(..., allowed=[*backing, *p["missing"]])
```

- `rule_check`'s `allowed` holds the same texts as today, in a different order. `_allowed_stems` builds a set, so the order does not matter.
- The docstring of `missing` names the new rule.
- Known ceilings, in a `# ponytail:` comment:
  - Stems must match exactly: "cushioned" does not back "cushion".
  - A product with no description, category or attributes gets only words of its keyword.
  - A colour or size word in the attributes ("blue") is still not suggested, because `NOISE_STEMS` is checked too.
- Unchanged: `search_query`, `titles_prompt`, `keep_present`, `drop_stores`, `TITLES_PARSE`, the cache-hit rule, `rule_check`, `rewrite_prompt`, the schema, the API and the web app. Cached `keyword_search` rows stay valid.

### 2. Testing

Unit, `tests/unit/test_products.py`. `WS`, `KS` and `KSH` are the women-sandals, kids-sandals and kids-shoes title lists above:

- `missing("BSOAgentTestBrand Women Sandal Tan", WS, ["BSOAgentTestBrand"], keyword="women sandals", backing=["women sandals", "Flat sandal with a cushioned footbed", "Sandals", "7", "tan"]) == ["footbed"]`.
- `missing("BSOAgentTestBrand Boys Sandal Blue", KS, ["BSOAgentTestBrand"], keyword="kids sandals", backing=["kids sandals", "Lightweight EVA sandal with a hook-and-loop strap", "Sandals", "3", "blue"]) == ["kid"]`.
- `missing("BSOAgentTestBrand Kids Sports Shoe Black", KSH, ["BSOAgentTestBrand"], keyword="kids shoes", backing=["kids shoes", "Breathable mesh running shoe for school and play", "Shoes", "4", "black"]) == []`.
- `missing("BSOAgentTestBrand Women Sandal Tan", WS, ["BSOAgentTestBrand"], keyword="women sandals", backing=[]) == []`.
- The 7 existing `missing` unit tests pass no `backing` and keep their expected values.

Integration, `tests/integration/test_products_run.py`:

- New test: one seeded product with a description; the ranking titles hold one word the description backs and one it does not, each in 2 titles. After `run_products`, `missing_keywords` holds only the backed word, and a rewrite that uses the backed word keeps it (status `pass`).
- The existing tests that expect a missing word outside the keyword (the two asserting `["summer"]`, and any others the plan finds) are fixed by giving their seeded product a description that contains the word. Their expected values stay. The plan counts them and lists each change.

Copy: the new fixtures and comments are checked against `FORBIDDEN` in `tests/unit/test_recommend_copy.py`. No prompt changes, so `PRODUCT_CASES` is unchanged.

### 3. Dev re-check

Run by the controller only with the user's OK at that point, by the live-check pattern (the worker loop is never started).

- Expected cost: about 6,000 micros ($0.01). That is 4 flash-lite calls (3 keyword samples and 1 rewrite, for one batch of 10) at about 1,500 micros each, and no grounded searches, because the 8 current-keyword rows were searched on 2026-09-29 and stay fresh for 7 days.
- Each keyword the vote picks that is not one of those 8 adds one grounded search, about 37,500 micros.
- Writes: the job, 10 product rows, `api_key.last_used_at`, and a `keyword_search` row for any new keyword.
- Expected missing words, *inferred* from the stored titles and product data, to be compared with what is observed: LC-01 and LC-02 "kid"; LC-03 none; LC-06 none; LC-09 "kids"; LC-10 "footbed".

## Out of scope

- The keyword vote choosing a colour phrase ("navy flip flops").
- Near-matches and synonyms between a ranking-title word and the product data.
- The deferred minors in docs/findings-slice21.md §3.
