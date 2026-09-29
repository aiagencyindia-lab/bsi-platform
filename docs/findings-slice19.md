# Findings: slice 19 — product-title quality fixes

## 1. What was built

The four quality problems found by slice 18's live check (findings-slice18 §2 and §3): plural echo, an ill-fitting keyword pulling the title, unprompted dropped words, and keywords too specific to share a search. All changes are in `bsi_core/products.py` unless named otherwise.

**Word folding.** `fold(text)` is `tokens(text)` without 1-letter tokens, each mapped through `rivals._stem` (imported, not copied), which drops one trailing `s` from words longer than three characters: `fold("Men's Sandals") == ["men", "sandal"]`, `fold("Flip-Flops") == ["flip", "flop"]`. `fold_set(text)` is its set form, and `_brand_stems` folds the brand name and aliases.

**`missing`** compares by stem. A ranking-title token counts if it is at least 3 characters, not a number, not a stopword, and its stem is not in the product title's or the brand's stems. Each title counts a stem once, a stem needs `MIN_TITLES` titles, and the first surface form seen is reported (by title count, then stem, at most `MAX_MISSING`). "sandals" is no longer missing from a title that has "Sandal".

**`dropped(original, suggestion, brand_names)`** lists the original title's words whose stem is not in the suggestion. Stopwords, brand stems, pure numbers and 1-letter tokens are ignored; the words are lowercased, in original order, without repeats.

**`rule_check(original, suggestion, brand_names)`** now returns `(title, status, dropped_words)`. It prepends a lost brand, drops a word whose stems overlap an earlier kept word's stems (R7, now by stem, so "Sandal And Sandals" loses "Sandals"), strips trailing `CONNECTORS` (`and`, `with`, `for`, `&`, `-`, `|`), trims to 150 characters at a word boundary, and strips trailing connectors again after the trim (ruling R2, helper `_strip_connectors`). `dropped` runs on the final title. Status is `review` when any original word was lost, else `adjusted` when the title differs from the suggestion, else `pass`.

**The keyword step.**
- `keyword_key(k)` is `" ".join(_stem(t) for t in tokens(_display(k)))`. `_display` lowercases, collapses whitespace and removes the possessive `'s` (straight or curly apostrophe, `_POSSESSIVE`). 1-letter tokens are kept (ruling R1).
- `vote(samples)` compares keys: rank 1 is the key most often at rank 1 (ties by sample order), then the other keys in first-seen order, each shown in its first surface form. `vote([["men's sandals"], ["mens sandal"], ["men flip flops"]]) == ["men sandals", "men flip flops"]`.
- `fit_rank(keywords, title, category, description)` runs after `drop_brand_terms`. A keyword's category word is its last word. Keywords whose category stem is in the title come first, then those whose stem is only in the category or description; the rest are dropped. With none left the keyword is NULL and R13 applies.
- **Run-wide key map.** `run_products` keeps `key_map: dict[str, str]` for the whole run. The first product with a key sets the keyword string, and later products with the same key reuse it, so `mens sandal` and `men sandals` share one search and one `keyword_search` row.

**Prompts.** `keyword_prompt` asks for rank 1 as a broad plural shopper phrase (audience plus the product's own category, e.g. "kids sandals", "men flip flops"), "kids" rather than "boys" or "girls", and never a different product type. `rewrite_prompt` says to keep every word of the original title (reordering allowed), add the keyword and missing terms naturally, never change the product type, repeat no word and avoid keyword stuffing.

**Migration `0020_product_review.py`, `models.py`.** `ck_product_rule_check` is dropped and recreated as `rule_check IS NULL OR rule_check IN ('pass', 'adjusted', 'review')`, and a nullable `product.dropped_words text[]` is added. The downgrade sets `review` rows to `adjusted`, drops the column and restores the two-value CHECK. `models.RULE_CHECKS` gains `review`; `Product.dropped_words` is `Mapped[list[str] | None]`.

**The run writes.** `run_products` stores `dropped_words` with the other result columns on each rewrite, and R13's clearing sets it to NULL.

**API and export.** `ProductOut` gains `dropped_words: list[str] | None`; `openapi.json` and `schema.d.ts` are regenerated. `EXPORT_COLUMNS` gains a last column `dropped_words`, `|`-joined and blank for NULL through the existing `export_rows`.

**Products tab.** `format.ts` gains `droppedNote(words)`, which returns `dropped: a, b` or `null` for an empty or missing list. The Check cell shows the `rule_check` tag (now including `review`) and under it a muted line with the dropped words. `PRODUCT_CASES` in `test_recommend_copy.py` gains `review` and `dropped: `.

**Commits** (`git log --oneline main..HEAD`, oldest first; this docs commit follows them):

| Commit | Subject |
|---|---|
| 339642a | docs: slice 19 spec, product-title quality fixes |
| ea53627 | docs: slice 19 implementation plan, product-title quality fixes |
| ff3f7f5 | feat(products): review status and dropped_words (migration 0020) |
| 054d5a1 | feat(products): fold plurals; flag dropped words for review |
| 95f62ca | fix(products): strip a trailing connector the 150-char trim leaves |
| 6fd76ac | feat(products): key-based keyword vote, shared searches and a fit check |
| 386a59b | feat(web): show the review status and dropped words |

## 2. Live check on dev

Not yet run. The controller runs it after the user approves migrating dev to 0020; results are recorded here then.

## 3. Deferred and untested

Decisions with a cost (rulings, spec `## Rulings`):
- `keyword_key` keeps 1-letter tokens and strips the possessive first, where the spec's first text used `fold` (R1). Cost: none seen.
- Trailing connectors are stripped a second time, after the 150-character trim (R2). Cost: none.

Migration and export:
- No test checks that `dropped_words` export cells are formula-neutralised (R6 applies to every cell through `export_rows`, but no test uses a `dropped_words` value that starts with a formula character such as `=` or `-`).
- The downgrade of migration 0020 was never exercised, by a test or against a database.

Folding, `dropped` and the rule check:
- `dropped()` de-duplicates by surface form, not by stem, so an original with both "sandal" and "sandals" that loses them lists both.
- A connector with punctuation attached ("And," or "for:") is not in `CONNECTORS` and is not stripped from the end of a title.
- A rewritten product stores `dropped_words = []` when nothing was lost, while a product that was never rewritten has NULL. Both show no dropped line on the tab.
- No tests for mixed surface forms in `missing` (e.g. "Sandals" in one title and "sandal" in another) or for several connectors in a row at the end of a title.

The keyword step:
- `fit_rank` drops most lower-rank keywords, because they often end in an attribute rather than the category word (*inferred* from the reviews, not observed on a live run), so the stored `keywords` list often shrinks to the generic phrase. This is what the spec asks for; watch it in the dev re-check.
- The key map lives for one run only. A variant of a keyword that an earlier run cached (for example `men sandals` when `mens sandal` is cached) is a new string, misses the cache and pays for a new search.
- `fit_rank` ignores a trailing 1-letter word: it uses `fold`, which drops 1-letter tokens, so a keyword ending in one (for example "size a") is judged by the word before it, while `keyword_key` keeps that letter (R1).

Web:
- `droppedNote` is called twice per row in the Check cell (the plan's snippet); the call is cheap.
- Only the `droppedNote` helper is tested, not the rendered Check cell. The dev live check (§2) is meant to cover the rendered cell; it has not run yet.

Out of scope (spec):
- Irregular plurals (feet, children) and non-English titles: `_stem` does not fold them.
- Mapping audience words deterministically (boys/girls → kids): left to the prompt.
- Auto-restoring dropped words.
- A real SERP provider; Shopify.
