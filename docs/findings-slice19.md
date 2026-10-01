# Findings: slice 19 — product-title quality fixes

## 1. What was built

The four quality problems found by slice 18's live check (findings-slice18 §2 and §3): plural echo, an ill-fitting keyword pulling the title, unprompted dropped words, and keywords too specific to share a search. All changes are in `bsi_core/products.py` unless named otherwise.

**Word folding.** `fold(text)` is `tokens(text)` without 1-letter tokens, each mapped through `rivals._stem` (imported, not copied), which drops one trailing `s` from words longer than three characters: `fold("Men's Sandals") == ["men", "sandal"]`, `fold("Flip-Flops") == ["flip", "flop"]`. `fold_set(text)` is its set form, and `_brand_stems` folds the brand name and aliases.

**`missing`** compares by stem. A ranking-title token counts if it is at least 3 characters, not a number, not a stopword, and its stem is not in the product title's or the brand's stems. Each title counts a stem once, a stem needs `MIN_TITLES` titles, and the first surface form seen is reported (by title count, then stem, at most `MAX_MISSING`). "sandals" is no longer missing from a title that has "Sandal".

**`dropped(original, suggestion, brand_names)`** lists the original title's words whose stem is not in the suggestion. Stopwords, brand stems, pure numbers and 1-letter tokens are ignored; the words are lowercased, in original order, without repeats. `STOPWORDS` gained `a an in of on to by at or` (ruling R4), so "Kurta Set of 3 Blue" rewritten as "Blue Kurta Set 3 Piece" is a `pass` with nothing dropped, where "of" was flagged before. `missing` already skipped words under 3 letters, so R4 does not change it.

**`rule_check(original, suggestion, brand_names)`** now returns `(title, status, dropped_words)`. It prepends a lost brand, drops a word whose stems overlap an earlier kept word's stems (R7, now by stem, so "Sandal And Sandals" loses "Sandals"), strips trailing `CONNECTORS` (`and`, `with`, `for`, `&`, `-`, `|`), trims to 150 characters at a word boundary, and strips trailing connectors again after the trim (ruling R2, helper `_strip_connectors`). `dropped` runs on the final title. Status is `review` when any original word was lost, else `adjusted` when the title differs from the suggestion, else `pass`.

**The keyword step.**
- `keyword_key(k)` is `" ".join(_stem(t) for t in tokens(_display(k)))`. `_display` lowercases, collapses whitespace and removes the possessive `'s` (straight or curly apostrophe, `_POSSESSIVE`). 1-letter tokens are kept (ruling R1).
- `vote(samples)` compares keys: rank 1 is the key most often at rank 1 (ties by sample order), then the other keys in first-seen order, each shown in its first surface form. `vote([["men's sandals"], ["mens sandal"], ["men flip flops"]]) == ["men sandals", "men flip flops"]`.
- `fit_rank(keywords, title, category, description)` runs after `drop_brand_terms`. A keyword is cut at its first `CATEGORY_CUTS` token (`for` or `with`; rulings R3 and R6). Its category word is the last folded word before the cut, or the last folded word of the whole keyword when nothing folds before the cut (R3): "slippers for men" is read by `slipper`, not `men`, and "men slip on shoes" by `shoe`. Keywords whose category stem is in the title come first, then those whose stem is only in the category or description; the rest are dropped. With none left the keyword is NULL and R13 applies.
- **Run-wide key map.** `run_products` keeps `key_map: dict[str, str]` for the whole run. The first product with a key sets the keyword string, and later products with the same key reuse it, so `mens sandal` and `men sandals` share one search and one `keyword_search` row.

**Prompts.** `keyword_prompt` asks for rank 1 as a broad plural shopper phrase (audience plus the product's own category, e.g. "kids sandals", "men flip flops"), "kids" rather than "boys" or "girls", and never a different product type. `rewrite_prompt` says to keep every word of the original title (reordering allowed), add the keyword and missing terms naturally, never change the product type, repeat no word and avoid keyword stuffing.

**Migration `0020_product_review.py`, `models.py`.** `ck_product_rule_check` is dropped and recreated as `rule_check IS NULL OR rule_check IN ('pass', 'adjusted', 'review')`, and a nullable `product.dropped_words text[]` is added. The downgrade sets `review` rows to `adjusted`, drops the column and restores the two-value CHECK. `models.RULE_CHECKS` gains `review`; `Product.dropped_words` is `Mapped[list[str] | None]`.

**The run writes.** `run_products` stores `dropped_words` with the other result columns on each rewrite, and R13's clearing sets it to NULL.

**API and export.** `ProductOut` gains `dropped_words: list[str] | None`; `openapi.json` and `schema.d.ts` are regenerated. `EXPORT_COLUMNS` gains a last column `dropped_words`, `|`-joined and blank for NULL through the existing `export_rows`.

**Products tab.** `format.ts` gains `droppedNote(words)`, which returns `dropped: a, b` or `null` for an empty or missing list. The Check cell shows the `rule_check` tag (now including `review`) and under it a muted line with the dropped words. `PRODUCT_CASES` in `test_recommend_copy.py` gains `review` and `dropped: `.

**Commits** (`git log --oneline main..HEAD`, oldest first):

| Commit | Subject |
|---|---|
| 339642a | docs: slice 19 spec, product-title quality fixes |
| ea53627 | docs: slice 19 implementation plan, product-title quality fixes |
| ff3f7f5 | feat(products): review status and dropped_words (migration 0020) |
| 054d5a1 | feat(products): fold plurals; flag dropped words for review |
| 95f62ca | fix(products): strip a trailing connector the 150-char trim leaves |
| 6fd76ac | feat(products): key-based keyword vote, shared searches and a fit check |
| 386a59b | feat(web): show the review status and dropped words |
| e0d349c | docs: slice 19 findings, index and rulings |
| e1c1260 | docs: show the RUF001 fix as the escape text in the plan |
| 8cfa6fa | fix(products): read the category word before a stopword; add short stopwords |
| 0c98e29 | docs: slice 19 rulings R3 and R4 and final-review deferrals |
| fb41c4a | docs: record the R3 fallback limit in slice 19 findings |
| 5763bfe | docs: slice 19 dev re-check results |
| 02e0f0a | docs: align slice 19 findings with the re-check |
| e7cf869 | docs: mark the LC-09 cause as inferred; correct the kept-keywords reason |
| 3983fb4 | docs: record ruling R5 (store names as titles deferred) in the slice 19 spec |
| d1bc876 | fix(products): cut a keyword only at for/with in fit_rank (R6) |
| (this commit) | docs: slice 19 audit fixes: ruling R6, R4's cost, R5's cause, test lists |

## 2. Live check on dev

Run on 2026-09-29 against the dev database, with the user's approval for both the migration and the re-check. The code was the branch at fb41c4a, which includes R1–R4 but not R6 (d1bc876, made later in the audit). R6 changes only where `fit_rank` cuts a keyword containing "for" or "with" versus other stopwords; none of the ten products' stored keywords contains `on`, `in`, `a` or another stopword that R6 no longer cuts at (checked on dev). *Inferred:* the rank-1 keywords would not change under R6; keywords the model offered but R3/R4 dropped (such as a "slip on" phrase) are not stored, so that part could not be checked without a re-run. Everything below was observed unless it is marked *inferred*.

**Migration.** `alembic current` read `0019` before and `0020 (head)` after `alembic upgrade head`. `pg_get_constraintdef` shows `ck_product_rule_check` allowing `pass`, `adjusted` and `review`, and `product.dropped_words` exists. No existing rows were changed.

**Run.** With the API running locally, `POST /products/run` returned `202` and queued job `d2aee331…`, the only queued job in dev. It was run once through `process_job(GeminiGroundingAdapter(), generate, embed)`; the worker loop was not started. It took 1 min 37 s (slice 18's run took 2 min 16 s) and finished `done` with `cost_micros = 308,958` ($0.3090), inside the spec §5 estimate of $0.27–$0.38. The summary was `products:10 keywords:8 searched:8`.

**The four slice 18 problems on the same ten products:**
- **Plural echo:** gone. No suggestion contains a repeated stem; LC-01 is "BSOAgentTestBrand Blue Boys Sandal Com Kids" (see the new problem below), not "…Sandal And Sandals".
- **Ill-fitting keyword:** LC-05 "Men Flip Flop Navy" got `men flip flops` and became "BSOAgentTestBrand Navy Men Flip Flop"; slice 18 gave `men slipper` and "…Navy Men Slipper".
- **Dropped words:** none. "Casual" (LC-06, LC-07) and "School" (LC-09) are kept. Every product's `dropped_words` is `[]`, so no product was flagged `review`.
- **Shared searches:** 10 products used 8 keywords (`kids sandals` for LC-01 and LC-02, `kids shoes` for LC-03 and LC-09), so 8 grounded searches instead of 10.
- All ten suggestions are `adjusted`. Six only move the colour forward; besides the two "Com Kids" additions, LC-04 gained "Classic" (from `missing_keywords`) and LC-09 gained "Kids" (*inferred:* from its keyword `kids shoes`, which the rewrite prompt says to work in; its `missing_keywords` is empty).

**New problem found by this re-check.** Two suggestions gained the junk word "Com": LC-01 "…Blue Boys Sandal Com Kids" and LC-02 "…Pink Girls Sandal Com Kids". The titles-parse step for `kids sandals` returned store names, not product titles: "Famous Footwear", "Zappos.com", "Next USA", "Journeys Kidz", "ShopWSS.com". They pass `keep_present` because they appear in the answer text, and "com" is in two of them, so `missing` reported it and the rewrite worked it in. Two searches (`women sandals`, `women slippers`) stored 0 titles. The search results are US stores although the locale is IN/en (*inferred* from the domains; the locale is recorded, not enforced). Recorded in §3.

**Web, production build.** Requests were made with `curl` against `next start -p 3001` with `API_URL=http://localhost:8000` and the Run 1 key in the `bsi_key` cookie. `GET /b/{id}/products` returned 200 with 11 table rows and "Last run: done"; "Navy Men Flip Flop" is present and "And Sandals" is not. `GET /b/{id}/products/export.csv` returned 200 with the header ending `rule_check,dropped_words` and 10 data rows. No product was `review`, so the `review` badge and the `dropped:` line were not rendered in this check.

**Writes to dev.** 10 `product` rows updated, 8 new `keyword_search` rows (the 10 slice 18 rows remain), 1 `job` row (`product_run`, $0.3090). Every API-key request updated `api_key.last_used_at`, latest 2026-09-29 08:07 UTC. Both servers were stopped afterwards. Model spend on dev is now $9.9377 of the $15 cap.

## 3. Deferred and untested

- **Store names parsed as product titles (found by the re-check, §2).** For `kids sandals` the titles-parse step returned retailer names ("Zappos.com", "ShopWSS.com"), and `missing` then suggested "com", which the rewrite put into two titles. Likely fixes: tell `titles_prompt` to return product titles only, drop titles that equal or contain their own domain, and add "com" to `STOPWORDS` (`in` is already one under R4, and `missing` skips tokens under 3 letters, so `co` never reaches it).
- **Grounded search results ignore the locale (found by the re-check, §2).** US stores came back for an IN/en brand; the locale is recorded, not enforced (slice 1 design).

Decisions with a cost (rulings, spec `## Rulings`):
- `keyword_key` keeps 1-letter tokens and strips the possessive first, where the spec's first text used `fold` (R1). Cost: none seen.
- Trailing connectors are stripped a second time, after the 150-character trim (R2). Cost: none.
- `fit_rank` reads the category word before the keyword's first cut word, `for` or `with` since R6 (R3). Cost: a phrase whose category genuinely follows `for` or `with` is read by the earlier word.
- `a an in of on to by at or` are stopwords (R4). Cost: not none, as first recorded. From commit 8cfa6fa until R6, R3 cut at these words too, so "men slip on shoes" (read by `slip`) and "women pull on boots" (read by `pull`) were dropped. R6 fixed that.
- Store names parsed as product titles are deferred to the next slice (R5). The root cause is upstream, in `titles_prompt` and `keep_present`; the stop-gap of adding "com" to `STOPWORDS` was deferred too. Cost: until then a run can add a domain fragment such as "Com" to suggestions; on dev, LC-01 and LC-02 carry it.
- `fit_rank` cuts a keyword only at `CATEGORY_CUTS` (`for`, `with`), not at every stopword (R6). Cost: a category after another joining word ("sandals in black") is read by the last word (`black`), as it was before R3.

Migration and export:
- `dropped_words` export cells cannot start with a formula character: the values come from `tokens()`, which yields only `[a-z0-9]+`, so the risk cannot occur. The generic `cell()` in `export_rows` (slice 18 R6) still covers the column.
- The CSV export gained a 9th column, `dropped_words`, so a consumer that checks the column count strictly will see a change.
- The downgrade of migration 0020 was never exercised, by a test or against a database.

Folding, `dropped` and the rule check:
- `dropped()` de-duplicates by surface form, not by stem, so an original with both "sandal" and "sandals" that loses them lists both.
- A connector with punctuation attached ("And," or "for:") is not in `CONNECTORS` and is not stripped from the end of a title.
- A rewritten product stores `dropped_words = []` when nothing was lost, while a product that was never rewritten has NULL. Both show no dropped line on the tab.
- `-es` plurals (dresses, watches, boxes) do not fold with `_stem`, which drops only one `s`, so a "Dress Dresses" echo survives the repeat check and "dress" can be flagged as dropped when the suggestion has only "dresses".
  - Note (2026-10-01): folded in slice 33: `_stem` drops -es after ch, sh, x, ss and zz; the echo is removed (docs/findings-slice33.md).
- Removing a repeated word mid-title can leave two connectors side by side ("Sandal And For Kids"), because connectors are stripped only at the end.
- `drop_brand_terms` compares exact tokens while the other checks compare stems, so "croc clogs" survives for the brand "Crocs".
- No tests for mixed surface forms in `missing` (e.g. "Sandals" in one title and "sandal" in another) or for several connectors in a row at the end of a title.

The keyword step:
- The worry that `fit_rank` would drop most lower-rank keywords did not happen in the re-check (§2): every product kept 4–5 keywords, e.g. LC-01 `kids sandals, boys sandals, eva sandals, blue sandals, kids strap sandals`. Some of them fit only through the category or description tier: LC-05 "Men Flip Flop Navy" (category "Slippers") kept `men slippers` and `daily wear slippers` below its rank-1 `men flip flops`, and LC-04 "Kids Slipper Grey" kept `kids flip flops` from its description.
- The key map lives for one run only. A variant of a keyword that an earlier run cached (for example `men sandals` when `mens sandal` is cached) is a new string, misses the cache and pays for a new search.
- `fit_rank` ignores a trailing 1-letter word: it uses `fold`, which drops 1-letter tokens, so a keyword ending in one (for example "size a") is judged by the word before it, while `keyword_key` keeps that letter (R1).
- The R3 fallback uses the last folded word of the whole keyword when nothing folds before the cut: a keyword that starts with a cut word ("for men") or whose head has only 1-letter tokens ("x for men") is read by "men", because `fold` drops 1-letter tokens. No test covers the fallback. Since R6, "a" is not a cut word, so "a line dress for women" is read by `dres` (dress), not by the fallback (`test_fit_rank_cuts_only_at_for_and_with`).

Web:
- `droppedNote` is called twice per row in the Check cell (the plan's snippet); the call is cheap.
- Only the `droppedNote` helper is tested, not the rendered Check cell. The dev re-check (§2) ran, but no product was `review`, so the `review` badge and the `dropped:` line are still unverified in a browser or production build.

Out of scope (spec):
- Irregular plurals (feet, children) and non-English titles: `_stem` does not fold them.
- Mapping audience words deterministically (boys/girls → kids): left to the prompt.
- Auto-restoring dropped words.
- A real SERP provider; Shopify.
