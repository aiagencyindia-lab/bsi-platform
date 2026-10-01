# Slice 33 design: folding "-es" plurals in `rivals._stem`

## Context

Codebase facts: main `44930e6`, checked 2026-10-01.

The last of the four smaller items the user ordered on 2026-10-01 (labels, rate limits, webhook signing, "-es" folding). docs/findings-slice19.md §3 records the gap: "`-es` plurals (dresses, watches, boxes) do not fold with `_stem`, which drops only one `s`, so a "Dress Dresses" echo survives the repeat check and "dress" can be flagged as dropped when the suggestion has only "dresses"." docs/findings-slice21.md §3 records the partial fix: "The `-es` fix is one-sided: it applies to allowed texts only, so an original "Watches" or "Boxes" is not folded. `-es` folding is out of scope."

Facts read before the approaches (direct reads on Fable 5.1, plus one read-only query of dev):
- `rivals._stem(word)` (packages/core/bsi_core/rivals.py:50-55) drops one trailing `s` on words longer than three characters. It is called once in rivals.py, by `rivals._words` (slug and topic words: `slug_words`, `topic_words`, consumed by recommend.py:623 and :629 for competitor-content matching), and 15 times in packages/core/bsi_core/products.py (lines 340, 356, 364, 387, 419, 516, 555, 557, 559, 565 ×2, 566 ×2, 644, 680): `fold`/`fold_set` (`products.py:351-360`), `NOISE_STEMS`, `AUDIENCE_STEMS`, `_brand_stems`, `_allowed_stems`, `keyword_key` (`products.py:416-419`; keywords with the same key share one cached grounded search), `title_first`, `missing`, `rule_check` and its helpers. 16 direct calls in all (R3).
- `_allowed_stems` (`products.py:376-394`) adds, for every allowed token longer than three characters ending in "es", `_stem(t[:-2])` — the one-sided patch. It folds any `-es` ending, so today an allowed "contact lenses" backs a suggested "Lens", "baby clothes" backs "Cloth" and "potatoes" backs "Potato" (checked in memory by the spec review). Its callers are `rule_check` (as `allowed`), `missing` (as `backing`) and `_not_in_keyword` (`products.py:947`). `fold`'s docstring calls itself "The one place to swap in a real lemmatiser."; the ponytail comment in `missing` (`products.py:630`) says stems match exactly apart from the `-es` singular.
- Tests: tests/unit/test_rivals.py `test_stem_drops_one_trailing_s_on_longer_words` pins `sneakers → sneaker, shoes → shoe, kids → kid, bus → bus, glass → glas`; `test_slug_words_reads_the_path_only` and `test_topic_words_match_slugs_by_subset` pin `kid`, `shoe`, `sneaker`. tests/unit/test_products.py: `test_rule_check_allows_the_singular_of_an_es_plural` (allowed "men watches" backs "Watch"), `test_rule_check_allows_glass_for_glasses` (allowed "reading glasses" backs "Glass"), `test_missing_backing_folds_es_plurals` (backing "men watches" backs "watch"), `test_rewrite_prompt_leaves_keyword_words_out_of_missing` (test_products.py:594; keyword "men watches" removes "watch" through `_not_in_keyword`). `test_vote_groups_plural_and_possessive_variants` (test_products.py:573) asserts `keyword_key("men's sandals") == keyword_key("mens sandal")`; no test pins an `-es` key. No other test pins `glas`.
- Dev (read-only, 2026-10-01): the 10 products' titles, categories, keywords and missing words and the 9 `keyword_search` keywords contain no word ending in ches/shes/xes/sses/zzes (sandals, shoes, slippers, flip flops, sports, boys, kids, …). `rival_page` URL slugs contain 6 distinct such words: `passes, boxes, shes, watches, kisses, sunglasses`; "shes" has four characters, so the `len(word) > 4` guard leaves it at `she` under both rules, and the live check should show 5 changed words.

Classification, said in chat as the first line of the first brainstorming reply: **architectural** — "`_stem` is one shared helper with 24 call sites across `rivals.py` (slug/topic word matching for competitor content) and `products.py` (`keyword_key`, `fold`, noise and audience stems, rule_check, missing words), and `keyword_key` decides which keywords share a cached search, so a stemming change alters cache grouping, matching and spend across several components." (Correction, 2026-10-01, R3: "24 call sites" was said without counting; there are 16 direct calls, 15 in products.py and 1 in rivals.py. The classification stands.)

Decisions approved in chat (brainstorming on Fable 5.1, 2026-10-01, after the session switched from Opus 5.5; implementer and reviewer subagents on Opus 5.5). Each decision had two or three approaches with trade-offs and a recommendation in a chat message before its question:
- D1, the rule: suffix rules in `_stem` (over suffix rules plus `-ies → -y`, which breaks hoodies/hoodie and ties; and a Snowball stemmer, a new dependency that over-stems and re-keys every cached keyword). The user chose suffix rules.
- D2, the old patch: first decided as "remove `_allowed_stems`' one-sided `-es` set" (over keeping two rules for one concept). Re-asked after the spec review of 7131835 showed the set also backs `-oes`, `-ses` and `-thes` plurals (lenses/lens, clothes/cloth, potatoes/potato, canvases/canvas) that the new `_stem` does not fold: the user then chose to keep the set, with its docstring updated (R1).
- D4, the rule's limits: accept and name the `-sse`, `-xe` and `-che` singulars (`mousses → mouss`, `pickaxes → pickax`, `caches → cach`) and `quiz` (`quizzes → quizz`) as limits, pinned in the test (over dropping `sses` and `xes` from the rule, which leaves dresses, glasses and boxes unfolded; or dropping only `zzes`, which loses buzz/fizz). The user chose to accept them (R2).
- D3, the live check: read-only over dev's `rival_page` URLs (over a product run that could show no change on dev data, or importing a "watches" product that would cost a grounded search and leave rows to clean up). The user chose read-only.
Each design section's text was in chat before its approval question; the user approved Sections 1–3.

## Design

### 1. The stem rule (`rivals.py`)

```python
# -es after these endings is a plural marker: watches, dishes, boxes,
# dresses, quizzes. Not after a plain z (sizes -> size).
_ES = ("ches", "shes", "xes", "sses", "zzes")


def _stem(word: str) -> str:
    """Fold plurals: drop "es" after ch, sh, x, ss or zz on words longer
    than four characters (watches -> watch, glasses -> glass), keep a
    word ending in ss (glass stays glass), else drop one trailing s on
    words longer than three characters (shoes -> shoe, kids -> kid).
    ponytail: suffix rules, not a stemmer; -ies stays as is (hoodies ->
    hoodie, accessories -> accessorie); a real stemmer is the upgrade
    path if topic words start missing slugs."""
    if len(word) > 4 and word.endswith(_ES):
        return word[:-2]
    if word.endswith("ss"):
        return word
    return word[:-1] if len(word) > 3 and word.endswith("s") else word
```

- Order: the `-es` rule first (`glasses → glass`), then the `ss` keep (`glass → glass`; today `glas`), then the one-`s` rule unchanged for everything else (`shoes → shoe`, `sandals → sandal`, `mens → men`, `bus → bus`).
- Known limits (docstring, test and findings; R2): the `-es` rule also strips words whose singular ends in `-che`, `-sse` or `-xe`, so those pairs no longer meet (`caches → cach` vs `cache`; `mousses → mouss` vs `mousse`; `lacrosses → lacross`, `posses → poss`, `pickaxes → pickax`), whereas today the one-`s` rule folds them (`mousses → mousse`); `zzes` is right for `buzz/buzzes` and `fizz/fizzes` and wrong for `quiz` (`quizzes → quizz`, `quiz → quiz`); `-zes` after a single `z` is left to the one-`s` rule (`sizes → size`); `-oes` and `-ies` are untouched (`potatoes → potatoe`, `accessories → accessorie`, as today).
- Every caller picks the rule up. `keyword_key` for a keyword containing an affected word changes (`"men watches"`: `men watche → men watch`), so such a cached `keyword_search` row misses once (one grounded search, about 38,000 micros). Dev has no such keyword.

### 2. `products.py` and the tests

- `_allowed_stems` keeps its `es` set and body (R1); only the last two sentences of its docstring change, from "ponytail: rivals._stem drops only one "s"; this patches -es for allowed words only." to "ponytail: rivals._stem folds -es only after ch, sh, x, ss and zz; this also folds -oes, -ses and -thes (lenses, clothes, potatoes) for allowed words only." The ponytail comment in `missing` (`products.py:630`, "apart from the -es singular") stays accurate, since the special case stays. `fold`'s docstring changes "each with one trailing s dropped (rivals._stem): sandals and sandal, mens and men meet." to "each plural-folded by rivals._stem: sandals and sandal, mens and men, watches and watch meet."; the rest of it, including "The one place to swap in a real lemmatiser.", stays. No other `products.py` line changes.
- tests/unit/test_rivals.py: `test_stem_drops_one_trailing_s_on_longer_words` is renamed `test_stem_folds_plurals` and asserts, as one list, `sneakers → sneaker, shoes → shoe, kids → kid, bus → bus, glass → glass, watches → watch, dishes → dish, boxes → box, dresses → dress, glasses → glass, quizzes → quizz, sizes → size, caches → cach, mousses → mouss` (`caches`, `mousses` and `quizzes` are the named limits, pinned so they are deliberate).
- tests/unit/test_products.py, three two-sided cases the old patch could not pass, and one that pins what the kept set still does:
  - `test_keyword_key_folds_es_plurals`: `keyword_key("men watches") == keyword_key("men watch") == "men watch"` and `keyword_key("kids shoes") == "kid shoe"`.
  - `test_rule_check_removes_an_es_plural_repeat`: `rule_check("Zara Summer Dress", "Zara Summer Dress Dresses", ["Zara"]) == ("Zara Summer Dress", "pass", [])` (the repeat is dropped; a removed repeat is not an adjustment, slice 26).
  - `test_missing_folds_an_es_plural_in_the_title`: `missing("Titan Analog Dial Watches", ["Titan Men Watch", "Fossil Men Watch"], ["Titan"], keyword="men watches", backing=["men watches"]) == ["men"]`.
  - `test_lenses_still_back_lens_for_allowed_text`: `rule_check("Acme Daily", "Acme Daily Lens", ["Acme"], allowed=["contact lenses"]) == ("Acme Daily Lens", "pass", [])` (passes today too; it pins R1).
- The four existing `-es` tests (the three in Context plus `test_rewrite_prompt_leaves_keyword_words_out_of_missing`) stay as they are and pass.
- Red and green, checked on 2026-10-01 on scratch copies outside the repo (a copy of `bsi_core` with the new `_stem` and the two docstring edits, the `es` set kept; the five new tests in a separate folder, named as above): on main's code `4 failed, 1 passed in 0.19s` (`'watche'` in the stem list; `'men watche' == 'men watch'`; the echo case returns `adjusted`; `['men', 'watch'] == ['men']`; the lenses case passes today); with the patched copy `5 passed in 0.22s`. The existing tests/unit/test_products.py and tests/unit/test_rivals.py against the patched copy: `1 failed, 127 passed in 0.31s`, the one failure the old `glas` pin (`test_stem_drops_one_trailing_s_on_longer_words`); on main `128 passed in 0.31s`. `mypy --strict` with the repo config, ruff check and ruff format --check are clean on the two patched modules. (An earlier scratch run with the set removed, before R1, gave `4 passed` on the four two-sided tests; it is superseded.)
- Expected counts: test_rivals.py unchanged in number (one test rewritten); test_products.py +4; backend 1566 → 1570.
- Copy: new strings, test names, fixtures and comments are checked against `FORBIDDEN` in tests/unit/test_recommend_copy.py by a grep of the diff.

### 3. Docs, live check, process

- Spec on branch `slice33-es-folding`; reviewer subagent (Opus 5.5); user review; then writing-plans. One plan, two tasks (rivals, then products).
- Post-merge docs: docs/findings-slice33.md; README rows; dated notes keeping the originals under findings-slice19 §3's `-es` line, findings-slice21 §3's "The `-es` fix is one-sided" line, and the "later slices" lines in findings-slice30 §3 and findings-slice31 §3.
- Live check (approved: read-only): after merge, `docker compose exec -T db psql -U bsi_owner -d bsi` dumps dev's `rival_page` URLs to the scratchpad; a scratch script runs `slug_words` with the merged `_stem` and with the old rule over them and prints the words whose stem changed, with page counts per word and domain. Reads only, no API key, no worker, no model, so nothing is written. Spend: none. Recorded in findings §2. The cached `keyword_search` rows are untouched (no dev keyword contains an affected word).
- Commits carry the trailer the latest attribution reminder names; subagents run on Opus 5.5 (`model: "opus"`).

## Rulings

- **R1: `_allowed_stems` keeps its `es` set.** Decided: the set and body stay; only the docstring's last two sentences change; the user chose this over removing the set as first decided (D2). Found by the spec review of 7131835 (the set folds every `-es` token, so removing it regresses allowed-text backing for lenses/lens, clothes/cloth, potatoes/potato, canvases/canvas, and `missing` would report "lens" for keyword "contact lenses"). Why: a fact behind D2 was wrong (the cost named in chat was only clothes/cloth), so the choice was re-asked. Cost if wrong: two folding rules for one concept, stated in the docstring. Asked in chat.
- **R2: the `-sse`, `-xe`, `-che` singulars and `quiz` are accepted, named limits.** Decided: `_ES` keeps its five endings; the test pins `caches → cach`, `mousses → mouss` and `quizzes → quizz`; the user chose this over dropping `sses` and `xes` (dresses, glasses, boxes stay unfolded) or only `zzes` (buzz/fizz stop folding). Found by the spec review of 7131835 (mousse/mousses, lacrosse, posse, pickaxe meet today and would not; quizzes → quizz never meets quiz). Why: the common cases that motivated the slice outweigh rare `-sse`/`-xe` words; the limits are pinned so they are deliberate. Cost if wrong: those pairs stop matching in slugs, titles and keys, and an allowed plural of that shape no longer backs its singular (an allowed "hair mousses" with a suggested "Mousse": `pass` today, `adjusted` after; the kept set does not help, since `_stem("mouss")` is `mouss`). Asked in chat.
- **R4: the re-review's three minors were applied.** Decided: the test bullet names `caches`, `mousses` and `quizzes` as the pinned limits (it had said "the last three", which counted `sizes`); R2's cost line names the lost allowed-text backing; the `missing` comment is cited as `products.py:630`. Found by the re-review of 1b2babb. Why: accuracy. Cost if wrong: none. Named in chat when made.
- **R3: the review's factual points were applied.** Decided: 16 direct `_stem` calls (15 in products.py, 1 in rivals.py) in Context and a dated correction after the classification quote; `test_vote_groups_plural_and_possessive_variants` and the fourth `-es` test named; `_not_in_keyword` named as an `_allowed_stems` caller; the `missing` comment stays accurate under R1; "shes" is unchanged by the length guard, so the live check shows 5 words. Found by the spec review of 7131835. Why: the counts were said without counting (process rule "count before stating"); the rest is accuracy for the plan writer. Cost if wrong: none. Named in chat when made.

## Out of scope

- `-ies`, `-oes` and irregular plurals; a real stemmer; re-keying existing `keyword_search` rows.
- Words whose singular ends in `-che`, `-sse` or `-xe` (`caches`, `niches`, `mousses`, `lacrosses`, `posses`, `pickaxes`) and `quiz`/`quizzes`: accepted limits (R2).
