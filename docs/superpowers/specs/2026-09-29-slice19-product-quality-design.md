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
- Brand handling (prepend if lost) and the 150-character trim are unchanged. After the trim, trailing connectors are stripped again, because a cut at a word boundary can end the title on one ("…Sandal For"); ruling R2.

### 2. The dropped-word check, the `review` status and migration 0020

- New `dropped(original, suggestion, brand_names) -> list[str]`: the original title's words whose stem is missing from `fold_set(suggestion)`. Ignored: stopwords, brand stems, pure numbers and 1-letter tokens. Lowercased surface forms, in original order, without repeats.
- `rule_check(original, suggestion, brand_names) -> tuple[str, str, list[str]]` returns `(title, status, dropped_words)`, where `dropped_words = dropped(original, title, brand_names)` is computed on the final title (after the brand, repeat, tidy, trim and second tidy steps; R2). Status: `review` if `dropped_words` is non-empty; else `adjusted` if the title differs from the suggestion; else `pass`.
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
- **Normalisation before the vote.** `keyword_key(k) = " ".join(_stem(t) for t in tokens(_display(k)))`: the possessive `'s` is stripped first (`_display`), then every token is stemmed, and 1-letter tokens are kept (ruling R1; `fold` would drop them). `vote` compares keys: rank 1 is the key most often at rank 1 across the samples (ties by sample order); the rest are the other keys in first-seen order. Each key's display form is the first surface form seen, cleaned by `_clean` and with possessive `'s` removed (`"men's sandals"` → `"men sandals"`). At most `MAX_KEYWORDS`.
- **Run-wide key map.** `run_products` keeps a map key → keyword for the whole run. The first product with a key sets its keyword string; later products with the same key get the same string, so they share one search and one `keyword_search` row.
- **Fit check after the vote and `drop_brand_terms`.** New `fit_rank(keywords, title, category, description) -> list[str]`. A keyword's category word is the last folded word before its first `STOPWORDS` token, or its last folded word if nothing comes before that token (R3): "slippers for men" is read by `slipper`, "men flip flops" by `flop`; its stem is compared with the product's stems. Keywords whose category stem is in `fold_set(title)` come first; then those whose category stem is only in `fold_set(category)` or `fold_set(description)`; keywords that fit neither are dropped. Order within a tier is kept. Rank 1 is the first keyword left; none left → keyword NULL (R13 applies).
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
- `rule_check`, added during execution (R2): a suggestion of 39 `w` words, then `for tail end` (`"w0 … w38 for tail end"`), (original `"Plain"`) is cut just after `for`; the fixed title is at most 150 characters and its last word is not in `CONNECTORS` (`test_rule_check_strips_a_connector_the_trim_leaves_at_the_end`).
- `dropped("Walkaroo Boys Sandal 3 for x", "Walkaroo Sandal", ("Walkaroo", "WKR")) == ["boys"]` (`test_dropped_ignores_stopwords_brand_numbers_and_short_tokens`).
- Added by the final review (R4): `rule_check("Kurta Set of 3 Blue", "Blue Kurta Set 3 Piece", ())` → `("Blue Kurta Set 3 Piece", "pass", [])`; `dropped("Made in India Sandal", "Sandal Made India", ()) == []` (`test_short_stopwords_are_not_flagged_as_dropped`).
- `rule_check`, existing cases whose expected value changes because every call now reports dropped words:
  - the 229-character trim case (original `"Plain"`) → status `review`, dropped `["plain"]` (the title assertions stay);
  - `("Red Tape Boots", "Tape Shoes", ("Red Tape",))` → `("Red Tape Shoes", "review", ["boots"])`.
- The other existing `rule_check` cases keep their titles and statuses and gain `[]`.
- `vote([["men's sandals"], ["mens sandal"], ["men flip flops"]]) == ["men sandals", "men flip flops"]`.
- `fit_rank`, for title `"Men Flip Flop Navy"`, category `"Slippers"`, description `None`:
  - `["men slippers", "men flip flops"]` → `["men flip flops", "men slippers"]`;
  - `["men slippers"]` → `["men slippers"]`;
  - `["kids shoes"]` → `[]`.
- `fit_rank`, added by the final review (R3; `test_fit_rank_reads_the_category_word_before_a_stopword`):
  - `["men slippers", "slippers for men", "men flip flops"]` with the same title and category → `["men flip flops", "men slippers", "slippers for men"]` (the title tier, then the category tier in input order);
  - `fit_rank(["sandals for kids"], "Boys Sandal Blue", None, None) == ["sandals for kids"]`.
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

- **R1: `keyword_key` keeps 1-letter tokens.** Decided: `keyword_key(k)` is `" ".join(_stem(t) for t in tokens(_display(k)))`, as the plan wrote it, not the spec's first text `" ".join(fold(k))`. The possessive `'s` is stripped first and 1-letter tokens are kept. Why: `fold` drops 1-letter tokens only to remove the `s` of "men's", and stripping the possessive already does that; keeping them preserves words such as the "a" of "a line dress" and keeps the existing `["a", "b", "c"]` vote tie test valid. Cost if wrong: none seen. `fit_rank` still uses `fold`, so it ignores a trailing 1-letter word that `keyword_key` keeps (recorded in findings-slice19 §3). §3 above is updated.
- **R2: strip trailing connectors again after the trim.** Decided: `rule_check` removes trailing `CONNECTORS` a second time after the 150-character trim (helper `_strip_connectors`, commit 95f62ca). Why: in the spec's first order (tidy, then trim) a cut at a word boundary could leave "…Sandal For", the kind of junk §1 set out to remove. Found by the Task 2 implementer and reviewer. Cost if wrong: none. §1, §2 and §4 above are updated.
- **R3: `fit_rank`'s category word comes before the first stopword.** Decided: the keyword is tokenised with `tokens()` and cut at its first `STOPWORDS` token; the rest is folded (1-letter tokens dropped, each `_stem`med) and the category word is its last element. If nothing comes before the stopword, the last folded word of the whole keyword is used. Why: with the last word, "slippers for men" was ranked first for "Men Flip Flop Navy", ahead of "men flip flops", and "sandals for kids" was dropped for "Boys Sandal Blue". Found by the final whole-branch review. Cost if wrong: a phrase whose category genuinely follows a stopword is read by the earlier word. §3 and §4 above are updated.
- **R4: `a an in of on to by at or` join `STOPWORDS`.** Decided: the nine words are added to `STOPWORDS`. Why: `dropped()` flagged "of" and "in" on legitimate rewrites ("Kurta Set of 3 Blue" → "Blue Kurta Set 3 Piece" went to `review`). `missing` already skips words under 3 letters, so it is unaffected. Found by the final whole-branch review. Cost if wrong: none. §4 above is updated.
- **R5: store names parsed as product titles are deferred to the next slice.** Decided: the dev re-check (findings-slice19 §2) found the titles-parse step returning retailer names ("Zappos.com", "ShopWSS.com") for `kids sandals`, so `missing` suggested "com" and two suggestions gained "Com"; it is recorded in findings §3 with likely fixes, not fixed in this slice. Why: the problem sits upstream of this slice's four fixes (in `titles_prompt` and `keep_present`), and fixing it needs its own tests and another paid re-check. Cost if wrong: until the next slice, runs can add a domain fragment such as "Com" to suggestions; on dev, LC-01 and LC-02 carry it. This ruling was made in chat during the re-check without being named; it was recorded here after the slice 19 audit (2026-09-29).

## Out of scope

- Irregular plurals (feet, children) and non-English titles: `_stem` does not fold them.
- Mapping audience words deterministically (boys/girls → kids): left to the prompt.
- Auto-restoring dropped words.
- A real SERP provider; Shopify.
