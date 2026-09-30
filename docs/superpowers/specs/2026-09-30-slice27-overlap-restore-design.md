# Slice 27 design: no keyword words in the rewrite's missing list, and lost original words restored

## Context

After slice 26 merged, two model behaviours from slice 26's probes were listed as open (docs/findings-slice26.md §2): the rewrite writing both "kids" and "kid" when a product's keyword and a missing word share a stem, and the rewrite dropping an original word such as "Casual". The user asked to fix both.

A check of the probe outputs before the design (probe 1 and probe 2 results, 2026-09-30) showed:
- "kids kid" also occurs with main's rewrite prompt (probe 1, current-prompt call 3: LC-01 and LC-02), but since slice 26 `rule_check` removes the repeat and the status is `pass`; it shows only in `raw_title`.
- No original word was dropped with main's prompt: 0 of 30 current-prompt probe rewrites and 0 of 20 live-check rewrites (slices 25 and 26). The drops ("Casual") happened only under the two probed prompts, which were not built.

Classification, said in chat as the first line of the first brainstorming reply: **architectural** — "Either open issue changes what every product run produces: the missing-word list, or the rewrite and its status. The process also calls for a spec even for small changes."

Decisions approved in chat (brainstorming on Opus 5.5, 2026-09-30). Each question had its options described in the question; each design section's text was in chat before its approval question:

- **Scope:** both issues ("Both"). After the check above was put to the user as a new question (the facts behind the first choice were partly wrong), the user chose "Both, as chosen" again over fixing the overlap only or stopping.
- **Dropped words, approaches:** three approaches were described in chat with trade-offs and a recommendation: A, restore lost words in `rule_check` with status `adjusted`; B, restore but keep `review`; C, a prompt change with probes. The user chose A.
- **Overlap:** the first proposal (`missing()` never lists a keyword word) was withdrawn after the tests showed that the missing list deliberately includes keyword words (`test_missing_never_excludes_a_keyword_word`, from 24c5726 "keyword guard"; `test_missing_backing_folds_es_plurals`, where "watch" is missing from "Titan Analog Dial"). This was put to the user as a new question; the user chose "Prompt input only" over tidying the missing list or dropping the overlap part.
- **Section 2's ceiling:** the user approved the restore "as described", accepting that a replaced product type ends up as both types with status `adjusted`, over keeping `review` for that case.

Codebase facts (main `532b577`, checked 2026-09-30):

- `missing()` (products.py) builds `have` from the title's stems, the brand's stems and the exclude stems not in the keyword; a keyword word the title lacks can be listed (the keyword guard).
- `rewrite_prompt(brand, products)` sends each product's `keyword`, `missing`, `description` and `attributes` through `_product_lines`, which leaves out an empty value.
- `run_products` passes `allowed=[*p["backing"], *p["missing"]]` to `rule_check`; the stored `missing_keywords` is `p["missing"]`.
- `rule_check` prepends a lost brand, drops unbacked words, falls back to the original if only connectors remain, drops repeats (`_drop_repeats`), strips connectors, trims to `MAX_TITLE_CHARS` (150), then returns `review` with `dropped()`'s lost words if any original word is missing, else `pass` or `adjusted` (slice 26).
- `dropped(original, suggestion, brand_names)` returns the original title's lowercased tokens (not stopwords, brand stems, numbers or 1-letter tokens) whose stem is not in the suggestion.

## Design

### 1. The prompt filter (the overlap)

New helper in `products.py`, and `rewrite_prompt` passes each product's `missing` through it:

```python
def _not_in_keyword(p: dict[str, Any]) -> list[str]:
    """The product's missing words without those whose stems are in its
    keyword: the rewrite adds the keyword anyway, so asking for both
    ("kids" and "kid") invites a repeat."""
    kw = fold_set(p.get("keyword") or "")
    return [m for m in p.get("missing") or [] if not fold_set(m) & kw]
```

```python
        + _product_lines(
            [{**p, "missing": _not_in_keyword(p)} for p in products],
            "keyword",
            "missing",
            "description",
            "attributes",
        )
```

On dev this leaves "kid" out of LC-01's and LC-02's prompt lines and "kids" out of LC-09's; LC-10 keeps "footbed". `missing()`, the stored `missing_keywords`, the Missing keywords column, the CSV, and `rule_check`'s `allowed` are unchanged.

### 2. Restoring lost words (the dropped words)

New helper in `products.py`:

```python
def _restore(
    original: str, words: Sequence[str], brand_names: Sequence[str]
) -> list[str]:
    """The words with each original-title word the suggestion lost put
    back, right after the nearest earlier original word that is still
    there (at the start if none)."""
    lost = set(dropped(original, " ".join(words), brand_names))
    out = list(words)
    if not lost:
        return out
    orig = original.split()
    for i, word in enumerate(orig):
        if not set(tokens(word)) & lost:
            continue
        pos = 0
        for prev in reversed(orig[:i]):
            stems = fold_set(prev)
            at = [n for n, w in enumerate(out) if stems and fold_set(w) & stems]
            if at:
                pos = at[0] + 1
                break
        out.insert(pos, word)
    return out
```

In `rule_check`, right after the repeat step and before the trim:

```python
    title = " ".join(_restore(original, title.split(), brand_names))
```

The status rules are unchanged in code: after the trim, `review` if an original word is still lost (only when the trim cuts a restored word), else `pass` or `adjusted`. A restored title differs from the suggestion, so it is `adjusted` with empty dropped words. The docstring gains the restore step and says `review` now means an original word was lost by the trim.

Examples (checked on a scratch copy, 2026-09-30):
- "BSOAgentTestBrand Beige Women Slippers" for "BSOAgentTestBrand Women Casual Slipper Beige" (allowed ["women slippers"]) gives "BSOAgentTestBrand Beige Women Casual Slippers", `adjusted`.
- "BSOAgentTestBrand Brown Men Sandals" for "BSOAgentTestBrand Men Casual Sandal Brown" gives "BSOAgentTestBrand Brown Men Casual Sandals", `adjusted`.
- The integration fixture "Walkaroo Kids Summer Sandals Sandals" for "Walkaroo Boys Sandal 0" gives "Walkaroo Boys Kids Summer Sandals", `adjusted` (today `review` with ["boys"]).
- Known ceiling (approved): a replaced product type ends up as both types, `adjusted`: "Tape Shoes" for "Red Tape Boots" gives "Red Tape Boots Shoes"; "Navy Men Slipper" for "Men Flip Flop Navy" gives "Navy Men Flip Flop Slipper".

### 3. Testing

`tests/unit/test_products.py` (values computed on the scratch copy):
- `test_rule_check_trims_to_150_at_a_word_boundary`: with original "Plain", the result is `adjusted`, lost `[]`, 147 characters, starting "Plain w0 w1"; the test keeps its trim checks on the words after "Plain".
- New case (in the same test or a new `test_rule_check_trim_can_still_lose_a_restored_word`): original "w59 Plain" with the same 229-character suggestion gives `review` with lost `["w59", "plain"]`, 149 characters.
- `test_rule_check_drops_a_word_that_repeats_an_earlier_token`, the Red Tape case: `("Red Tape Boots Shoes", "adjusted", [])`.
- `test_rule_check_does_not_count_a_removed_repeat`, the repeat-plus-lost-word case: `("Walkaroo Boys Kids Sandal", "adjusted", [])`.
- `test_rule_check_flags_dropped_words_for_review` is renamed `test_rule_check_restores_dropped_words` and expects `("Brown Mens Casual Sandal Shoes", "adjusted", [])` and `("Navy Men Flip Flop Slipper", "adjusted", [])`.
- New `test_rewrite_prompt_leaves_keyword_words_out_of_missing`: a product with keyword "kids sandals" and missing ["kid", "summer"] gives `"missing": ["summer"]` in the prompt; a product whose missing words are all in its keyword gets no `"missing"` key.

`tests/integration/test_products_run.py`:
- `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked`: suggested title "Walkaroo Boys Kids Summer Sandals", `(rule_check, dropped_words) == ("adjusted", [])`; `raw_title` unchanged.
- `test_a_failed_search_is_stored_and_the_run_goes_on`: suggested title "Walkaroo Boys Kids Sandals".

The other 116 product tests pass unchanged on the scratch copy. No model call and no probe: both changes are deterministic.

### 4. Live check and docs

- **Live check, after merge, with the user's OK at that point:** one `product_run` on dev by the live-check pattern (API queues, `process_job` once, the worker loop never started). Dev is at 0021; no migration. The 8 stored keywords' `keyword_search` rows are fresh until 2026-10-06 13:10 UTC ("mens flip flops" until 2026-10-07 09:27; docs/findings-slice23.md §3; `SEARCH_TTL_DAYS` = 7). Expected cost about 6,600 micros (slice 26's check: 6,545), plus about 38,000 per keyword with no fresh valid row. Writes: the job, the 10 product rows, `api_key.last_used_at`, any new `keyword_search` row.
- **Read-back:** per product, the raw title, the suggested title, the status and the dropped words, stated as observed. *Inferred* expectation: LC-01's and LC-02's raw titles no longer pair "kid" with "Kids"; any dropped original word is restored and the product shows `adjusted`; with main's prompt a drop is rare, so the run may show none.
- **Docs:** this spec, the plan, `docs/findings-slice27.md` (the live check, every `minor (deferred)` and `parked` ledger line), docs/README.md rows, the `(this commit)` hash convention, and every ruling named in chat when made.

## Rulings

None.

## Out of scope

- Any change to `missing()`, the stored missing list, the UI or the CSV.
- Keeping `review` when the model replaced the product type (the approved ceiling).
- Any rewrite prompt wording change other than the `missing` field's content.
- The deferred items in docs/findings-slice26.md §4.
