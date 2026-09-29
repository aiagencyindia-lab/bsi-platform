# Findings: slice 21 — product-suggestion quality

## 1. What was built

This slice targets the three problems that slice 20's second live check recorded (findings-slice20 §2 and §3):
- Model names that carried the product type excluded generic words such as "sneaker".
- Size and colour words ("Little", "White") were suggested.
- The rewrite added "Boys" to LC-06, a men's sandal.

All code changes are in `packages/core/bsi_core/products.py`. No schema, API or web change.

**Constants.**
- `TITLES_PARSE = 2`, next to `TOP_TITLES`. Its comment carries the ceiling: a bump searches every cached keyword again (about $0.04 each).
- `NOISE_WORDS`: white, black, blue, red, green, pink, grey, gray, brown, navy, beige, tan, silver, gold, purple, orange, yellow, cream, multi, multicolor, color, colour, size, little, big. `NOISE_STEMS` holds their stems. The comment above `NOISE_WORDS` (`# missing() never suggests these…`, with a `ponytail:` part) carries spec §2's ceiling in shortened wording.
- `FUNCTION_WORDS`: and, for, with, of, the, a, an, in, on, to, by, or.

**The model prompt.** `titles_prompt`'s brand-and-model sentence now asks for "its model or product-line name without the product type (for example "Taye 2.0", not "Taye 2.0 Sneaker")".

**`missing(..., keyword="")`.** The `have` set is now `fold_set(product_title) | _brand_stems(brand_names) | (_brand_stems(exclude) - _brand_stems([keyword]))`. So a rival brand, model or competitor name never removes a stem of the product's own keyword, and the brand's own names are still excluded in full. `run_products` passes `keyword=p["keyword"]`. The `# ponytail:` comment at that call now says a competitor's generic word is excluded "for every keyword that does not contain it".

**The noise filter.** `missing` skips a ranking-title token whose stem is in `NOISE_STEMS`, as it skips stopwords. Nothing else uses it: `dropped()` still reports a lost original colour.

**The parse version.** `keep_present` now returns `list[dict[str, Any]]` and adds `"parse": TITLES_PARSE` to every stored title. A cached row is a hit only when two things hold:
- Its query matches `search_query(row.keyword)`, as before.
- Every stored title has `parse == TITLES_PARSE`. This replaces slice 20's rule that every title has a `brand` key.

A row with no titles is still a hit. Rows written before this slice lack the key, so they are searched again.

**`rule_check(..., allowed=())`.** A new step runs right after the brand is prepended and before the repeat check. It drops a suggestion word when all three hold:
- The word has at least one stem.
- None of its stems is in `_allowed_stems(original, allowed, brand_names)`.
- Not every token of it is a function word or a number.

`_allowed_stems` is a helper the spec does not name. It returns the stems of the original title, the allowed texts and the brand's names. It also adds, for each allowed token that is longer than 3 characters and ends in "es", the stem without the "es" ("watches" allows "watch").

`run_products` passes `allowed=[keyword, *missing, description or "", category or "", *attribute values as str]`. A title changed by this step is `adjusted`; `review` still means original words were lost.

**Tests.**
- `tests/unit/test_products.py`:
  - The prompt contains "without the product type".
  - The Chase/Paley `missing` call gives `["kids"]` with `keyword` and `[]` without it.
  - The Taye/Artie call gives `["sneaker"]`.
  - `dropped("Black Shoe", "Shoe", [])` gives `["black"]`. It is a pin and passed before Task 1.
  - In the LC-06 case, "Boys" is dropped and the status is `adjusted`.
  - The Blue Boys "Kids" case and "for Kids 3" are `pass`.
  - "Sale" is dropped (`adjusted`).
  - "Watch" with "men watches", and "Leather" with `allowed` "Leather", are `pass`.
  - The eight named `rule_check` tests pass `allowed=` and keep their expected values.
  - The `keep_present` expectation gains `"parse": 2`.
- `tests/integration/test_products_run.py`:
  - Every exact stored-title assertion and the two seeds gain `"parse": 2`.
  - `test_a_row_parsed_without_brand_is_redone` is renamed `test_a_row_parsed_before_parse_2_is_redone`. It checks that a row whose titles have brand and model keys but no `parse` key is searched again.
  - `_generator` gains `rewrite=`.
  - The failed-search test expects "Walkaroo Kids Sandals".
  - New `test_the_rewrite_cannot_add_an_invented_word`: "Walkaroo Boys Toddler Sandal Kids" is stored as "Walkaroo Boys Sandal Kids", with status `adjusted`.
- Delete-and-fail checks, each restored from a backup afterwards:
  - Without the parse clause, `test_a_row_parsed_before_parse_2_is_redone` failed (`assert (0 == 1)`).
  - With `allowed=[p["keyword"]]` at the call, `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked` failed, because "Summer", a missing word, was dropped.
- Backend gate: 1499 passed after Task 1 and 1506 after Task 2, and metrics coverage was 100%. Each run reported 2 warnings.
  - Task 1's report names both: Starlette's `StarletteDeprecationWarning` for its test client and anyio's `BlockingPortal` alias `DeprecationWarning`.
  - Task 2's report names only the anyio one.
  - The controller's own gate run at 1e10fa4 (1506 passed) named both, the same two deprecations as on `main`. Run with `-W default`, it also showed a psycopg `ResourceWarning` for a connection deleted while still open (§3).

**Commits** (`git log --oneline main..HEAD`, oldest first):

| Commit | Subject |
|---|---|
| 33ebd8c | docs: slice 21 spec (product-suggestion quality) |
| 27cfc97 | docs: slice 21 spec review fixes (allowed sources, function words, -es plurals, named tests) |
| cc087b7 | docs: slice 21 spec: category fact, description ceiling, LC-06 dev data |
| ba9ead5 | docs: slice 21 implementation plan |
| d8df741 | docs: slice 21 plan review fixes |
| e16a389 | docs: slice 21 plan: wrapped ponytail comment, ruff note out of the code block |
| 24c5726 | fix(products): keyword guard, colour/size noise and parse version for missing words |
| 4e3f668 | fix(products): the rule check drops words the rewrite invents |
| 1e10fa4 | docs: slice 21 findings, index and rulings |
| (this commit) | docs: slice 21 findings: gate warnings as observed; wording |

## 2. Live check on dev

Not yet run. The controller runs it after the user approves; results are recorded here then.

## 3. Deferred and untested

From the task reviews:
- `keyword=p["keyword"]` in `run_products`'s `missing` call has no integration test (plan departure 7). The unit test pins the guard inside `missing`, and the spec asks for none.
- A drop can leave a function word that is not a connector at the end ("Walkaroo Sandal in"), because only CONNECTORS are stripped from the end.
- Kept numbers can leave promotional scraps ("Walkaroo Sandal 50%"). The plan keeps numbers by design.
- `rule_check` can return an empty title when the rewrite shares no word with anything allowed ("Comfy Footwear" gives `""` with `review`). `run_products` then stores `suggested_title = ""`. A one-line guard could fall back to the original title.
- The `-es` fix is one-sided: it applies to allowed texts only, so an original "Watches" or "Boxes" is not folded. `-es` folding is out of scope.
- The description, category and attribute sources of `allowed` are untested end to end, because the seeded products have none.
- Gate warnings:
  - Task 1's gate output carries 2 third-party deprecation warnings, the same as on `main`.
  - Task 2's report names only one of its 2 warnings (the anyio `BlockingPortal` alias). The controller's own gate run at 1e10fa4 has since named both (§1).
- With `-W default`, the backend suite also shows a psycopg `ResourceWarning` ("Connection ... deleted while still open"). It has not been checked against `main`.
- Task 1's implementer ran the full suite twice, one after the other. The second run was only to read the warning names.

Known ceilings (spec §1–§3, in `# ponytail:` comments where the spec asks):
- The keyword guard fixes slice 20's R6 ("Campus Shoes" excluding "shoe") only for keywords containing "shoe". For sandal, slipper and sneaker keywords, "shoe" stays excluded.
- Bumping `TITLES_PARSE` makes every cached keyword be searched again (about $0.04 each).
- `NOISE_WORDS` is English only and closed:
  - A real colour phrase ("white sneakers") is never suggested.
  - A noise word is skipped even when it is in the keyword.
  - Outside footwear, some are product words ("cream", "gold", "silver", "orange", "plus size", hair "color").
  - "toddler", "youth" and "infant" are not in the list, and "kid" from "Little Kid" is still suggested.
- Promotional words in the product's own description, attributes or category are allowed ("new arrival on sale" allows "New" and "Sale").
- Dropping a word can leave a neighbour on its own ("Sandal Size 10" gives "Sandal 10").
- A real synonym the rewrite adds from nowhere ("Footwear") is removed too.

Untested against real answers:
- It is not yet observed whether the parse now returns models without the product type, because the tests use fixed judge output. *Inferred*: the dev re-check (§2) is where this shows.

Out of scope (spec):
- The keyword vote choosing a colour phrase ("navy flip flops", slice 20's first live check).
- Answer commentary kept inside a verbatim title.
- Locale in the query; storing the answer text; `-es` plural folding.
