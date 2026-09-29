# Slice 19 design: product-title quality fixes

## Context

Slice 18's live check (docs/findings-slice18.md §2) ran ten sample products through the product-title wedge. It found four quality problems, recorded in findings-slice18 §3:

1. **Plural echo.** "Sandal And Sandals". `missing` and `rule_check` compare tokens exactly, so `sandal` and `sandals` are different words.
2. **An ill-fitting keyword pulls the title.** A flip flop got the keyword `men slipper`, the rewrite prompt says to work the keyword in, and the title became "…Slipper".
3. **Unprompted dropped words.** "Casual" and "School" disappeared. The rewrite prompt never says to keep the original's words, and `rule_check` does not look for dropped words.
4. **Keywords too specific to share a search.** Ten products gave ten different keywords (`boys sandal`, `girls sandal`, `mens sandal`…), so ten paid grounded searches.

Classification, said in chat as the first line of the first brainstorming reply: **bounded**. It changes an existing flow (the product run in `bsi_core/products.py`); by the user's standing rule it still gets a spec, a plan and the full review cycle.

Decisions approved in chat (brainstorming on Opus 5.5, 2026-09-29). Each design section's text was shown in chat before its approval:

- **Scope:** all four problems.
- **Dropped words:** flag them with a new `review` status and store the dropped words; never auto-restore or silently fall back.
- **Keyword step:** a prompt change, deterministic normalisation before the vote, and a fit check after it.
- **Approach A:** one shared word-folding function built on the existing `rivals._stem`, used by every check. Rejected: a lemmatiser library (new dependency and model data for a footwear/apparel catalogue) and asking the model (spend per product, not deterministic, not unit-testable).

Codebase facts the design rests on:

- `rivals._stem(word)` drops one trailing `s` from words longer than three characters: mens→men, womens→women, boys→boy, kids→kid, flops→flop, shoes→shoe, sandals→sandal, slippers→slipper, cases→case; bus stays bus; dress→dres and glass→glas (consistently on both sides, so matching still works). Checked on 2026-09-29.
- `products.tokens(text)` is `[a-z0-9]+` over the casefolded text, so "men's" gives `men`, `s` and "Flip-Flops" gives `flip`, `flops`.
- `rule_check(original, suggestion, brand_names) -> (title, status)` prepends a lost brand, drops words that repeat an earlier token (R7), then trims to `MAX_TITLE_CHARS = 150`. Its callers are `run_products` and the unit tests.
- `product.rule_check` has `ck_product_rule_check` = `rule_check IS NULL OR rule_check IN ('pass','adjusted')` (migration 0019); `models.RULE_CHECKS = ("pass", "adjusted")`.
- `run_products` votes per product with `vote(samples)`, then `drop_brand_terms`; distinct rank-1 keywords per batch are searched once and cached in `keyword_search` by exact keyword string for 7 days (R9).
- R13 clears the result columns when a product's keyword drops to NULL.

## Design

### 1. Word folding, `missing` and the repeat check

- New `fold(text) -> list[str]` in `products.py`: `tokens(text)`, drop 1-letter tokens, map each through `rivals._stem` (imported, not copied). `fold_set(text) -> frozenset[str]` is the set form.
- `missing(product_title, titles, brand_names)` compares by stem. A ranking-title token is a candidate if its surface form is at least 3 characters, not a number and not a stopword, and its stem is not among the product title's stems or the brand's stems. Each title counts a stem at most once. A stem must appear in at least `MIN_TITLES` titles. The output is the first surface form seen for each stem, ordered by title count, then by stem; at most `MAX_MISSING`.
- `rule_check`'s repeat check (R7) works on stems: a word whose `fold_set` overlaps the stems of earlier kept words is dropped whole; words with no stems (punctuation) are kept.
- New tidy step after the repeat check: trailing connector words are removed from the end, repeatedly: `and`, `with`, `for`, `&`, `-`, `|` (compared casefolded). "Sandal And" becomes "Sandal".
- Brand handling (prepend if lost) and the 150-character trim are unchanged.

### 2. The dropped-word check, the `review` status and migration 0020

- New `dropped(original, suggestion, brand_names) -> list[str]`: the original title's words whose stem is missing from `fold_set(suggestion)`. Ignored: stopwords, brand stems, pure numbers and 1-letter tokens. Lowercased surface forms, in original order, without repeats.
- `rule_check(original, suggestion, brand_names) -> tuple[str, str, list[str]]` returns `(title, status, dropped_words)`, where `dropped_words = dropped(original, title, brand_names)` is computed on the final title (after the brand, repeat, tidy and trim steps). Status: `review` if `dropped_words` is non-empty; else `adjusted` if the title differs from the suggestion; else `pass`.
- Migration `0020_product_review.py`:
  - drops `ck_product_rule_check` and recreates it as `rule_check IS NULL OR rule_check IN ('pass','adjusted','review')`;
  - adds nullable `product.dropped_words text[]`;
  - downgrade: `UPDATE product SET rule_check = 'adjusted' WHERE rule_check = 'review'`, drop the column, restore the two-value CHECK.
- `models.RULE_CHECKS = ("pass", "adjusted", "review")`; `Product.dropped_words: Mapped[list[str] | None]`.
- `run_products` writes `dropped_words` with the other result columns; R13's clearing sets it to NULL too.
- API: `ProductOut` gains `dropped_words: list[str] | None`. The CSV export gains a last column `dropped_words` (`|`-joined, formula-neutralised like every cell, R6). Regenerate `openapi.json` and `schema.d.ts`.
- Web: the Check column shows the `review` badge, and under it a muted line `dropped: casual` (comma-separated) when `dropped_words` is non-empty. `PRODUCT_CASES` gains `review` and `dropped:`.

### 3. The keyword step and the rewrite prompt

- **Keyword prompt.** Rank 1 is a broad shopper phrase: the audience plus the product's own category, plural ("kids sandals", "men flip flops", "women slippers"). Children's products use "kids", not "boys" or "girls". Never replace the product's type with a different one. Otherwise unchanged (up to 5 keywords, generic first, no brand).
- **Normalisation before the vote.** `keyword_key(k) = " ".join(fold(k))`. `vote` compares keys: rank 1 is the key most often at rank 1 across the samples (ties by sample order); the rest are the other keys in first-seen order. Each key's display form is the first surface form seen, cleaned by `_clean` and with possessive `'s` removed (`"men's sandals"` → `"men sandals"`). At most `MAX_KEYWORDS`.
- **Run-wide key map.** `run_products` keeps a map key → keyword for the whole run. The first product with a key sets its keyword string; later products with the same key get the same string, so they share one search and one `keyword_search` row.
- **Fit check after the vote and `drop_brand_terms`.** New `fit_rank(keywords, title, category, description) -> list[str]`. A keyword's category word is its last word; its stem is compared with the product's stems. Keywords whose category stem is in `fold_set(title)` come first; then those whose category stem is only in `fold_set(category)` or `fold_set(description)`; keywords that fit neither are dropped. Order within a tier is kept. Rank 1 is the first keyword left; none left → keyword NULL (R13 applies).
- **Rewrite prompt.** Keep every word of the original title (you may reorder); add the keyword and the missing terms naturally; never change the product type; repeat no word; no keyword stuffing.
- Unchanged: the search query `"{keyword} buy online"`, the 7-day cache, R9, R10, R12 and spend accounting.

### 4. Testing

Unit (`tests/unit/test_products.py`):

- `fold("Men's Sandals") == ["men", "sandal"]`; `fold("Flip-Flops") == ["flip", "flop"]`.
- `missing("Walkaroo Boys Sandal Blue", ["Kids Sandals for Boys Summer Sandal", "Boys Summer Sandals Lightweight", "Summer Sandals Kids"], ("Walkaroo", "WKR")) == ["summer", "kids"]`. This existing test's expected value changes from `["sandals", "summer", "kids"]`: "sandals" now folds to the product's "sandal".
- `rule_check`, new cases (brand names `("Walkaroo", "WKR")` unless given):
  - `("Walkaroo Boys Sandal Blue", "Walkaroo Blue Boys Sandal And Sandals")` → `("Walkaroo Blue Boys Sandal", "adjusted", [])`.
  - `("Men Casual Sandal Brown", "Brown Mens Sandal Shoes")` → `("Brown Mens Sandal Shoes", "review", ["casual"])`.
  - `("Men Flip Flop Navy", "Navy Men Slipper")` → `("Navy Men Slipper", "review", ["flip", "flop"])`.
- `rule_check`, existing cases whose expected value changes because every call now reports dropped words:
  - the 229-character trim case (original `"Plain"`) → status `review`, dropped `["plain"]` (the title assertions stay);
  - `("Red Tape Boots", "Tape Shoes", ("Red Tape",))` → `("Red Tape Shoes", "review", ["boots"])`.
- The other existing `rule_check` cases keep their titles and statuses and gain `[]`.
- `vote([["men's sandals"], ["mens sandal"], ["men flip flops"]]) == ["men sandals", "men flip flops"]`.
- `fit_rank`, for title `"Men Flip Flop Navy"`, category `"Slippers"`, description `None`:
  - `["men slippers", "men flip flops"]` → `["men flip flops", "men slippers"]`;
  - `["men slippers"]` → `["men slippers"]`;
  - `["kids shoes"]` → `[]`.
- `keyword_prompt` contains "kids" and "plural"; `rewrite_prompt` contains "Keep every word".
- `PRODUCT_CASES` (banned-word test) gains the new prompt text, `review` and `dropped:`.

Integration (`tests/integration/test_products_run.py`, `test_api_products.py`; `test_constraints.py` does not cover the product CHECK today, so the new CHECK test goes in `test_products_run.py`):

- Two products whose samples vote `mens sandal` and `men sandals` cause exactly one engine query and one `keyword_search` row.
- A rewrite that drops an original word stores `rule_check = "review"` and `dropped_words`.
- R13 clearing sets `dropped_words` to NULL.
- `GET /products` and the CSV export include `dropped_words`.
- The database accepts `rule_check = 'review'` and still rejects an unknown value.

Web: `format.test.ts` or a page-level check that the `review` badge and `dropped:` line render; the gate as usual.

### 5. Dev re-check

After the gates, and after the user approves migrating dev to 0020: re-run the same ten products LC-01..LC-10 for the Run 1 brand through one `process_job`, then view the tab on a production build.

Spend, derived: the cache matches only identical keyword strings, so every new key costs one grounded search (measured ~37,500 micros in slice 18) and the four flash-lite calls (three keyword samples and one rewrite, one batch) cost about 1,500 micros each. If the keys group into about seven, the run costs about 7 × 37,500 + 6,000 ≈ 268,500 micros ($0.27); with no sharing, 10 × 37,500 + 6,000 ≈ 381,000 micros ($0.38).

Checked and recorded in `docs/findings-slice19.md`: no plural echo; flip flops keep their category; every dropped word is flagged `review`; fewer searches than products. Every API-key request writes `api_key.last_used_at`; the run writes `product`, `keyword_search` and `job`.

## Rulings

Rulings made during execution are appended here.

## Out of scope

- Irregular plurals (feet, children) and non-English titles: `_stem` does not fold them.
- Mapping audience words deterministically (boys/girls → kids): left to the prompt.
- Auto-restoring dropped words.
- A real SERP provider; Shopify.
