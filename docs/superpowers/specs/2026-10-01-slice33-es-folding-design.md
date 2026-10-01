# Slice 33 design: folding "-es" plurals in `rivals._stem`

## Context

Codebase facts: main `44930e6`, checked 2026-10-01.

The last of the four smaller items the user ordered on 2026-10-01 (labels, rate limits, webhook signing, "-es" folding). docs/findings-slice19.md §3 records the gap: "`-es` plurals (dresses, watches, boxes) do not fold with `_stem`, which drops only one `s`, so a "Dress Dresses" echo survives the repeat check and "dress" can be flagged as dropped when the suggestion has only "dresses"." docs/findings-slice21.md §3 records the partial fix: "The `-es` fix is one-sided: it applies to allowed texts only, so an original "Watches" or "Boxes" is not folded. `-es` folding is out of scope."

Facts read before the approaches (direct reads on Fable 5.1, plus one read-only query of dev):
- `rivals._stem(word)` (packages/core/bsi_core/rivals.py:50-55) drops one trailing `s` on words longer than three characters. It is used by `rivals._words` (slug and topic words: `slug_words`, `topic_words`, consumed by recommend.py for competitor-content matching) and, imported as `_stem`, by 21 sites in packages/core/bsi_core/products.py: `fold`/`fold_set` (`products.py:351-360`), `NOISE_STEMS`, `AUDIENCE_STEMS`, `_brand_stems`, `_allowed_stems`, `keyword_key` (`products.py:416-419`; keywords with the same key share one cached grounded search), `title_first`, `missing`, `rule_check` and its helpers.
- `_allowed_stems` (`products.py:376-394`) adds, for an allowed token ending in "es", `_stem(t[:-2])` — the one-sided patch. `fold`'s docstring calls itself "The one place to swap in a real lemmatiser."
- Tests: tests/unit/test_rivals.py `test_stem_drops_one_trailing_s_on_longer_words` pins `sneakers → sneaker, shoes → shoe, kids → kid, bus → bus, glass → glas`; `test_slug_words_reads_the_path_only` and `test_topic_words_match_slugs_by_subset` pin `kid`, `shoe`, `sneaker`. tests/unit/test_products.py: `test_rule_check_allows_the_singular_of_an_es_plural` (allowed "men watches" backs "Watch"), `test_rule_check_allows_glass_for_glasses` (allowed "reading glasses" backs "Glass"), `test_missing_backing_folds_es_plurals` (backing "men watches" backs "watch"). No test calls `keyword_key` directly. No other test pins `glas`.
- Dev (read-only, 2026-10-01): the 10 products' titles, categories, keywords and missing words and the 9 `keyword_search` keywords contain no word ending in ches/shes/xes/sses/zzes (sandals, shoes, slippers, flip flops, sports, boys, kids, …). `rival_page` URL slugs contain 6 distinct such words: `passes, boxes, shes, watches, kisses, sunglasses`.

Classification, said in chat as the first line of the first brainstorming reply: **architectural** — "`_stem` is one shared helper with 24 call sites across `rivals.py` (slug/topic word matching for competitor content) and `products.py` (`keyword_key`, `fold`, noise and audience stems, rule_check, missing words), and `keyword_key` decides which keywords share a cached search, so a stemming change alters cache grouping, matching and spend across several components."

Decisions approved in chat (brainstorming on Fable 5.1, 2026-10-01, after the session switched from Opus 5.5; implementer and reviewer subagents on Opus 5.5). Each decision had two or three approaches with trade-offs and a recommendation in a chat message before its question:
- D1, the rule: suffix rules in `_stem` (over suffix rules plus `-ies → -y`, which breaks hoodies/hoodie and ties; and a Snowball stemmer, a new dependency that over-stems and re-keys every cached keyword). The user chose suffix rules.
- D2, the old patch: remove `_allowed_stems`' one-sided `-es` set (over keeping two rules for one concept). The user chose to remove it.
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
- Known limits (docstring and findings): `-ches` also strips words whose singular ends in `-che` (`caches → cach`, `niches → nich`; such pairs no longer meet); `-zes` after a single `z` is left to the one-`s` rule (`sizes → size`); `-oes` and `-ies` are untouched (`potatoes → potatoe`, `accessories → accessorie`, as today).
- Every caller picks the rule up. `keyword_key` for a keyword containing an affected word changes (`"men watches"`: `men watche → men watch`), so such a cached `keyword_search` row misses once (one grounded search, about 38,000 micros). Dev has no such keyword.

### 2. `products.py` and the tests

- `_allowed_stems` loses the `es` set: the body becomes `text = " ".join(allowed)` then `return fold_set(original) | fold_set(text) | _brand_stems(brand_names)`; the docstring keeps its first sentence only ("Stems a suggestion word may come from: the original title, the allowed texts (keyword, missing words, the product's description, category and attribute values), the brand's names."). `fold`'s docstring changes "each with one trailing s dropped (rivals._stem): sandals and sandal, mens and men meet." to "each plural-folded by rivals._stem: sandals and sandal, mens and men, watches and watch meet."; the rest of it, including "The one place to swap in a real lemmatiser.", stays. No other `products.py` line changes.
- tests/unit/test_rivals.py: `test_stem_drops_one_trailing_s_on_longer_words` is renamed `test_stem_folds_plurals` and asserts, as one list, `sneakers → sneaker, shoes → shoe, kids → kid, bus → bus, glass → glass, watches → watch, dishes → dish, boxes → box, dresses → dress, glasses → glass, quizzes → quizz, sizes → size, caches → cach` (the named limit, pinned so it is deliberate).
- tests/unit/test_products.py, three two-sided cases the old patch could not pass:
  - `test_keyword_key_folds_es_plurals`: `keyword_key("men watches") == keyword_key("men watch") == "men watch"` and `keyword_key("kids shoes") == "kid shoe"`.
  - `test_rule_check_removes_an_es_plural_repeat`: `rule_check("Zara Summer Dress", "Zara Summer Dress Dresses", ["Zara"]) == ("Zara Summer Dress", "pass", [])` (the repeat is dropped; a removed repeat is not an adjustment, slice 26).
  - `test_missing_folds_an_es_plural_in_the_title`: `missing("Titan Analog Dial Watches", ["Titan Men Watch", "Fossil Men Watch"], ["Titan"], keyword="men watches", backing=["men watches"]) == ["men"]`.
- The three existing `-es` tests stay as they are and pass through `_stem`.
- Red and green, checked on 2026-10-01 on scratch copies outside the repo (a patched copy of `bsi_core`; the four new tests in a separate folder, named as above): on main's code `4 failed in 0.25s` (`'watche'` in the stem list; `'men watche' == 'men watch'`; the echo case returns `adjusted`; `['men', 'watch'] == ['men']`); with the patched copy `4 passed in 0.18s`. The existing tests/unit/test_products.py and tests/unit/test_rivals.py against the patched copy: `1 failed, 127 passed in 0.36s`, the one failure the old `glas` pin (`test_stem_drops_one_trailing_s_on_longer_words`); on main `128 passed in 0.31s`. `mypy --strict` with the repo config, ruff check and ruff format --check are clean on the two patched modules.
- Expected counts: test_rivals.py unchanged in number (one test rewritten); test_products.py +3; backend 1566 → 1569.
- Copy: new strings, test names, fixtures and comments are checked against `FORBIDDEN` in tests/unit/test_recommend_copy.py by a grep of the diff.

### 3. Docs, live check, process

- Spec on branch `slice33-es-folding`; reviewer subagent (Opus 5.5); user review; then writing-plans. One plan, two tasks (rivals, then products).
- Post-merge docs: docs/findings-slice33.md; README rows; dated notes keeping the originals under findings-slice19 §3's `-es` line, findings-slice21 §3's "The `-es` fix is one-sided" line, and the "later slices" lines in findings-slice30 §3 and findings-slice31 §3.
- Live check (approved: read-only): after merge, `docker compose exec -T db psql -U bsi_owner -d bsi` dumps dev's `rival_page` URLs to the scratchpad; a scratch script runs `slug_words` with the merged `_stem` and with the old rule over them and prints the words whose stem changed, with page counts per word and domain. Reads only, no API key, no worker, no model, so nothing is written. Spend: none. Recorded in findings §2. The cached `keyword_search` rows are untouched (no dev keyword contains an affected word).
- Commits carry the trailer the latest attribution reminder names; subagents run on Opus 5.5 (`model: "opus"`).

## Rulings

None yet.

## Out of scope

- `-ies`, `-oes` and irregular plurals; a real stemmer; re-keying existing `keyword_search` rows.
- `-ches` words whose singular ends in `-che` (`caches`, `niches`): accepted limit.
