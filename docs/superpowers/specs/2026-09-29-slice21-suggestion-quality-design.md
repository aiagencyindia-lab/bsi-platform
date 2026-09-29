# Slice 21 design: product-suggestion quality

## Context

Slice 20's second dev live check (docs/findings-slice20.md §2, job `89facf99`) removed store names and rival brand and model names from the product wedge's suggestions, but showed three new problems, observed:

1. **Over-exclusion.** The parse step put product-type nouns inside model names ("Chase Sandal", "Moc Slipper", "Artie Shoe", "Adalyn Sneaker", "Taye 2.0 Sneaker"), and `missing` excludes every stem of every model for the keyword. "sneaker", in 3 of the 5 kids-shoes titles ("Taye 2.0 Sneaker…", "Adalyn Sneaker…", "Lighted Glimmer 2.0 Sneaker…", observed in the controller's read-only query after the job), could not be suggested. The competitor alias "Campus Shoes" excludes "shoe" for every keyword (slice 20 ruling R6). *Inferred* from those observed titles: several of the 7 empty missing lists are correct anyway, since the kids-sandals titles were brand plus model only, with no generic word in 2 or more titles.
2. **Size and colour noise.** Zappos-style titles ("Taye 2.0 Sneaker - Little Kid White") gave LC-03 and LC-09 the missing words `little` and `white`; LC-03's suggestion "…Little White Black Kids Sports Shoe" adds "White" to a black shoe.
3. **Invented words.** The rewrite turned LC-06 "BSOAgentTestBrand Brown Men Casual Sandal" (a men's sandal, no missing words) into "…Brown Boys Casual Sandal Men". `rule_check` checks only for dropped words, so it passed.

Classification, said in chat as the first line of the first brainstorming reply: **bounded**. Slice 21 changes existing steps in `bsi_core/products.py`: which words the model-name exclusion removes, filtering size and colour noise out of the missing words, and a rule-check flag for words the rewrite adds. It needs no schema, API or UI change beyond perhaps one existing status. (The design that followed needs no new status either.) By the user's standing rule it gets a spec, a plan and the full review cycle.

Decisions approved in chat (brainstorming on Opus 5.5, 2026-09-29). Sections 1–4 each had their design text in chat before their approval:

- **Scope:** all three problems.
- **Invented words:** removed automatically by `rule_check` (status `adjusted`). Rejected: keep and flag with a stored list (needs a migration, API field and UI), and flag without storing (the operator cannot see why).
- **Allowed sources (after the spec review):** words the rewrite takes from the product's own description, attribute values or category survive the invented-word check. Rejected: adding "Add no other words." to the rewrite prompt.
- **Approaches:** (1) A — the parse asks for the model without the product type, plus a keyword guard on exclusions; rejected B (a model word shared by 2 or more brands is generic; fails when brands are blank) and C (keyword guard only; "sneaker" stays excluded). (2) A — a fixed `NOISE_WORDS` list; rejected B (the parse returns colour and size per title: more model output to validate for the same result). (3) the `rule_check` drop.

Codebase facts (main `c81f47d`, checked 2026-09-29 with the current code):

- `missing("Black Kids Sports Shoe", ["Taye Sneaker - Little Kid White", "Artie Sneaker - Little Kid White"], ["BSOAgentTestBrand"])` returns `["little", "sneaker", "white"]`.
- `missing("Boys Sandal", ["Kids Chase Sandal", "Kids Paley Sandal"], ["X"], exclude=["Kids Chase", "Kids Paley"])` returns `[]`; without `exclude` it returns `["kids"]`.
- `rule_check("BSOAgentTestBrand Brown Men Casual Sandal", "BSOAgentTestBrand Brown Boys Casual Sandal Men", ["BSOAgentTestBrand"])` returns the suggestion unchanged with `"pass"` and `[]`.
- `dropped("Black Shoe", "Shoe", [])` returns `["black"]`.
- `missing` builds `have = fold_set(product_title) | _brand_stems([*brand_names, *exclude])`; `run_products` passes `exclude` = the ranking titles' non-empty brands and models plus every competitor's name and aliases.
- A cached `keyword_search` row is a hit only when `row.query == search_query(row.keyword)` and every stored title has a `brand` key (slice 20 §5 B); a row with no titles is a hit.
- `rewrite_prompt` asks the model to "add the keyword and the missing terms naturally" (no "only") and passes each product's `description` (first 300 characters) and `attributes`; `category` goes only to `keyword_prompt`. Category words are allowed in the invented-word check anyway, by the user's choice.
- `rivals._stem` drops one trailing `s` only: "watches" → "watche", "glasses" → "glasse".
- `rule_check(original, suggestion, brand_names)` prepends a lost brand, drops a word repeating an earlier stem, strips trailing connectors, trims to 150 characters, strips connectors again, then computes `dropped`; status `review` if anything was dropped, else `adjusted` if the title changed, else `pass`. `run_products` is its only non-test caller.

## Design

All code changes are in `packages/core/bsi_core/products.py`.

### 1. Model words, the keyword guard, and the cache

- `titles_prompt`'s brand-and-model sentence becomes exactly: "For each title also give its brand and its model or product-line name without the product type (for example "Taye 2.0", not "Taye 2.0 Sneaker"), each as written in the title, else an empty string."
- `missing(product_title, titles, brand_names, exclude=(), keyword="")` gains `keyword: str`. Its `have` set becomes `fold_set(product_title) | _brand_stems(brand_names) | (_brand_stems(exclude) - _brand_stems([keyword]))`: a model, brand or competitor name never removes a stem of the product's own keyword; the brand's own names are excluded in full, as before.
- `run_products` passes `keyword=p["keyword"]` to `missing`.
- This fixes slice 20's R6 ("Campus Shoes" excluding "shoe") only for keywords containing "shoe"; for sandal, slipper and sneaker keywords "shoe" stays excluded (known ceiling).
- New constant `TITLES_PARSE = 2`. `keep_present` (its return annotation becomes `list[dict[str, Any]]`) adds `"parse": TITLES_PARSE` to every stored title. A cached row is a hit only when its query matches (unchanged) and every stored title has `t.get("parse") == TITLES_PARSE`; this replaces slice 20's "every title has a `brand` key". A row with no titles is still a hit. Rows written before this slice lack the key and are searched again.
- Known ceiling, in a code comment: bumping `TITLES_PARSE` makes every cached keyword be searched again (about $0.04 each).
- Unchanged: `_named_in` and R4, `drop_stores`, `search_query`.

### 2. Size and colour noise

- New constant `NOISE_WORDS`: white, black, blue, red, green, pink, grey, gray, brown, navy, beige, tan, silver, gold, purple, orange, yellow, cream, multi, multicolor, color, colour, size, little, big. `NOISE_STEMS = frozenset(_stem(w) for w in NOISE_WORDS)`.
- `missing` skips a ranking-title token whose stem is in `NOISE_STEMS`, as it skips stopwords. Nothing else uses it: `dropped()` still reports a lost original colour, so a rewrite that loses "Black" is still `review`.
- Known ceiling, in a code comment: English only and closed; a real colour phrase ("white sneakers") is never suggested; a noise word is skipped even when it is in the keyword; outside footwear some are product words ("cream", "gold", "silver", "orange", "plus size", hair "color"); other size markers ("toddler", "youth", "infant") are not in the list, and "kid" from "Little Kid" is still suggested.

### 3. `rule_check` drops invented words

- `rule_check(original, suggestion, brand_names, allowed=())` gains `allowed: Sequence[str]`. `run_products` passes `allowed=[p["keyword"], *p["missing"], p["description"] or "", p["category"] or "", *(str(v) for v in (p["attributes"] or {}).values())]`.
- Allowed stems: `fold_set(original) | fold_set(" ".join(allowed)) | _brand_stems(brand_names)`, plus, for every token of `allowed` that ends in "es" and is longer than 3 characters, `_stem(token[:-2])` ("watches" allows "watch", "glasses" allows "glass").
- New step, right after the brand is prepended and before the repeat check: a word of the suggestion is dropped when it has at least one stem (`fold_set(word)` non-empty), none of its stems is allowed, and not every token of it is a function word or a number. Function words: `FUNCTION_WORDS = frozenset({"and", "for", "with", "of", "the", "a", "an", "in", "on", "to", "by", "or"})`; a number is a token for which `tok.isdigit()` is true. Promotional stopwords such as "new", "sale", "free", "offer" are not function words, so an added "Sale" is dropped unless the product's own description, attributes or category contain it (a description such as "new arrival on sale" allows "New" and "Sale"; known ceiling). Punctuation-only words have no stems and are kept.
- A hyphenated word ("Flip-Flop", "2-Pack") is kept whole when any of its stems is allowed and dropped whole otherwise. Dropping a word can leave a neighbour on its own ("Sandal Size 10" → "Sandal 10"); this is accepted.
- A title changed by this step is `adjusted` (the existing rule: it differs from the suggestion). `review` still means original words were lost; `dropped()` is unchanged.
- Known ceiling: a real synonym the rewrite adds from nowhere ("Footwear") is removed too.
- If the step leaves no word, or nothing but CONNECTORS, the original title is used instead (Rulings R1 and R2), so this step never makes a suggestion empty. A title can still end up empty when the original title is itself empty or only connectors, or when the 150-character trim leaves only connectors before a word longer than 150 characters.

### 4. Testing

Unit, `tests/unit/test_products.py`:

- `titles_prompt(...)` contains "without the product type".
- `missing("Boys Sandal", ["Kids Chase Sandal", "Kids Paley Sandal"], ["X"], exclude=["Kids Chase", "Kids Paley"], keyword="kids sandals") == ["kids"]`; the same call without `keyword` returns `[]`.
- `missing("Black Kids Sports Shoe", ["Taye Sneaker - Little Kid White", "Artie Sneaker - Little Kid White"], ["BSOAgentTestBrand"]) == ["sneaker"]` (today `["little", "sneaker", "white"]`).
- `dropped("Black Shoe", "Shoe", []) == ["black"]`.
- `rule_check("BSOAgentTestBrand Brown Men Casual Sandal", "BSOAgentTestBrand Brown Boys Casual Sandal Men", ["BSOAgentTestBrand"], allowed=["men sandals"]) == ("BSOAgentTestBrand Brown Casual Sandal Men", "adjusted", [])`.
- `rule_check("BSOAgentTestBrand Blue Boys Sandal", "BSOAgentTestBrand Blue Boys Sandal Kids", ["BSOAgentTestBrand"], allowed=["kids sandals"]) == ("BSOAgentTestBrand Blue Boys Sandal Kids", "pass", [])`.
- `rule_check("Walkaroo Sandal 3", "Walkaroo Sandal for Kids 3", ["Walkaroo"], allowed=["kids sandals"]) == ("Walkaroo Sandal for Kids 3", "pass", [])`.
- `rule_check("Walkaroo Sandal", "Walkaroo Sandal Sale", ["Walkaroo"], allowed=["kids sandals"]) == ("Walkaroo Sandal", "adjusted", [])`.
- `rule_check("Titan Analog Dial", "Titan Analog Dial Watch", ["Titan"], allowed=["men watches"]) == ("Titan Analog Dial Watch", "pass", [])`.
- `rule_check("Walkaroo Sandal", "Walkaroo Leather Sandal", ["Walkaroo"], allowed=["kids sandals", "Leather"]) == ("Walkaroo Leather Sandal", "pass", [])`.
- `rule_check("Boys Sandal", "Comfy Footwear", [], allowed=["kids sandals"]) == ("Boys Sandal", "adjusted", [])` (Ruling R1).
- `rule_check("Boys Sandal", "Comfy Footwear for", [], allowed=["kids sandals"]) == ("Boys Sandal", "adjusted", [])` and `rule_check("Boys Sandal", "Comfy and Footwear", [], allowed=["kids sandals"]) == ("Boys Sandal", "adjusted", [])` (Ruling R2).
- `missing("Kids Shoe", ["Taye White Sneaker", "Artie White Sneaker"], ["X"], keyword="white sneakers") == ["sneaker"]` (a noise word is skipped even when it is in the keyword).
- `rule_check("Ray Reading Frame", "Ray Reading Frame Glass", ["Ray"], allowed=["reading glasses"]) == ("Ray Reading Frame Glass", "pass", [])`.
- Existing `rule_check` tests whose suggestions add words pass `allowed` holding those words (the default `()` allows nothing extra), keeping their current expected values: `test_rule_check_restores_the_brand_the_original_had`, `test_rule_check_passes_an_unchanged_suggestion`, `test_rule_check_drops_a_word_that_repeats_an_earlier_token`, `test_rule_check_keeps_punctuation_only_words`, `test_rule_check_flags_dropped_words_for_review`, `test_short_stopwords_are_not_flagged_as_dropped`, and the two trim tests (`test_rule_check_trims_to_150_at_a_word_boundary`, `test_rule_check_strips_a_connector_the_trim_leaves_at_the_end`), which pass `allowed=[" ".join(words)]` so they still exercise the trim.
- The exact `keep_present` comparison in `test_keep_present_drops_titles_absent_from_the_text` expects `"parse": 2`.

Integration, `tests/integration/test_products_run.py`:

- Every exact stored-title assertion gains `"parse": 2`: in `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked`, `test_an_error_search_is_not_reused`, `test_a_search_under_the_old_query_is_redone`, `test_store_names_are_not_stored_as_titles` and the no-parse-key test below.
- `test_a_failed_search_is_stored_and_the_run_goes_on` expects the suggestion "Walkaroo Kids Sandals" (its missing list is empty, so the fake rewrite's "Summer" is dropped).
- The reuse test (`test_a_fresh_search_is_reused_and_a_stale_one_redone`) and the R2 old-query test (`test_a_search_under_the_old_query_is_redone`) seed titles with `"parse": 2`, so each still depends only on its own condition.
- Slice 20's `test_a_row_parsed_without_brand_is_redone` becomes a test that a fresh row with the new query whose titles have brand and model keys but no `parse` key is searched again, and that the rewritten row's first title carries `"parse": 2`.
- New: `_generator` gains a `rewrite=` parameter; a run whose rewrite returns "Walkaroo Boys Toddler Sandal Kids" for the seeded "Walkaroo Boys Sandal 0" (keyword "kids sandals") stores the suggestion "Walkaroo Boys Sandal Kids" with `rule_check` `adjusted`.
- The idle-in-transaction probe is unaffected (no new session or model call).

Gates: the backend gate and `npm run gate`, run by the controller.

### 5. Dev re-check

Asked for at that point. No migration (dev stays at 0020); the worker stays stopped; one `product_run` for LC-01..LC-10 through one `process_job`. The 8 keywords are searched again (parse bump). Cost, derived: 8 × 37,500 + 6,000 = 306,000 micros (about $0.31; slice 20's two 8-search runs measured 313,103 and 313,238); 10 × 37,500 + 6,000 = 381,000 (about $0.38) with 10 keywords. Spend would go from about $10.56 to about $10.87–$10.94 of the $15 cap. Writes: the job row, 10 `product` rows, up to 10 `keyword_search` rows, `api_key.last_used_at`. On dev, LC-06's description is "Floater sandal with adjustable straps" and its attributes are size 8 and colour brown (read-only query, 2026-09-29), so an invented "Boys" is not an allowed word there. Reported as observed, per product: missing words, suggestion, status, and whether any colour or size word, rival name or invented word remains.

## Rulings

- **R1: an empty title falls back to the original.** Decided: in `rule_check`, right after the invented-word step, `title = title or original`; when every suggestion word is dropped the original title is used (status then `adjusted` by the existing rule, with no dropped words). Found by the final whole-branch review (controller ruling, 2026-09-29). Why: a rewrite made only of invented words left `suggested_title` empty with status `review`. Cost if wrong: a fully invented rewrite shows the original title instead of a blank. §3 and §4 above are updated. R2 widens the check.

- **R2: the fallback also covers connector-only rewrites.** Decided: R1's line becomes `title = title if _strip_connectors(title.split()) else original`; when the invented-word step leaves nothing but CONNECTORS ("Comfy Footwear for", "Comfy and Footwear"), the original title is used (status `adjusted`, no dropped words). Found by the re-review of the final fix wave, approved by the user (2026-09-29). Why: with R1 alone a kept connector made the title non-empty, so the later connector strip still left `suggested_title` empty with status `review`. Not covered: an original title that is itself empty or only connectors, and a 150-character trim that leaves only connectors before a word longer than 150 characters, can still give an empty title. Cost if wrong: a rewrite whose only kept words are connectors shows the original title instead of a blank. §3 and §4 above are updated.

## Out of scope

- The keyword vote choosing a colour phrase ("navy flip flops", slice 20's first live check).
- Answer commentary kept inside a verbatim title.
- Locale in the query; storing the answer text; `-es` plural folding.
