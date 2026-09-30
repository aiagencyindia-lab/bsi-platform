# Slice 27 design: no keyword words in the rewrite's missing list, and lost original words restored

## Context

After slice 26 merged, two model behaviours from slice 26's probes were listed as open (docs/findings-slice26.md §4, Out of scope; seen in the §2 probes): the rewrite writing both "kids" and "kid" when a product's keyword and a missing word share a stem, and the rewrite dropping an original word such as "Casual". The user asked to fix both.

A check of the probe outputs before the design (probe 1 and probe 2 results, 2026-09-30) showed:
- "kids kid" also occurs with main's rewrite prompt (probe 1, current-prompt call 3: LC-01 and LC-02), but since slice 26 `rule_check` removes the repeat and the status is `pass`; it shows only in `raw_title`.
- No original word was dropped with main's prompt: 0 of 30 current-prompt probe rewrites and 0 of 20 live-check rewrites (slices 25 and 26). The drops ("Casual") happened only under the two probed prompts, which were not built.

Classification, said in chat as the first line of the first brainstorming reply: **architectural** — "Either open issue changes what every product run produces: the missing-word list, or the rewrite and its status. The process also calls for a spec even for small changes."

Decisions approved in chat (brainstorming on Opus 5.5, 2026-09-30). Each question had its options described in the question; each design section's text was in chat before its approval question:

- **Scope:** both issues ("Both"). After the check above was put to the user as a new question (the facts behind the first choice were partly wrong), the user chose "Both, as chosen" again over fixing the overlap only or stopping.
- **Dropped words, approaches:** three approaches were described in chat with trade-offs and a recommendation: A, restore lost words in `rule_check` with status `adjusted`; B, restore but keep `review`; C, a prompt change with probes. The user chose A.
- **Overlap:** the first proposal (`missing()` never lists a keyword word) was withdrawn after the tests showed that the missing list deliberately includes keyword words (`test_missing_never_excludes_a_keyword_word`, from 24c5726 "keyword guard"; `test_missing_backing_folds_es_plurals`, where "watch" is missing from "Titan Analog Dial"). This was put to the user as a new question; the user chose "Prompt input only" over tidying the missing list or dropping the overlap part.
- **Section 2's ceiling:** the user approved the restore "as described", accepting that a replaced product type ends up as both types with status `adjusted`, over keeping `review` for that case.
- **From the spec review, each put to the user as a question and approved in chat:** the restore runs before the repeat step, so a restored word cannot bring back a repeat ("Yes, restore before repeats"); the prompt filter folds "-es" plurals with `_allowed_stems` ("Yes, reuse _allowed_stems"); and four consequences of the restore are accepted as ceilings (§2) over keeping the dropped-word signal in `dropped_words` ("Accept all, record as ceilings").
- **From the plan review, put to the user as a question and approved in chat:** the statement that only the trim can lose a word was wrong (the repeat step can drop a restored hyphenated word); the user chose "Correct the wording, accept it" over making the restore win over the repeat step. §2 and the ceilings now say so, and a test pins the case.

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
    kw = _allowed_stems("", [p.get("keyword") or ""], [])
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

`_allowed_stems` adds the singular of an "-es" keyword word (as `missing()` and `rule_check` already fold it), so for the keyword "men watches" the missing word "watch" is left out too. On dev this leaves "kid" out of LC-01's and LC-02's prompt lines and "kids" out of LC-09's; LC-10 keeps "footbed". `missing()`, the stored `missing_keywords`, the Missing keywords column, the CSV, and `rule_check`'s `allowed` are unchanged.

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

In `rule_check`, right after the R1/R2 fallback and before the repeat step (so a restored word cannot bring back a repeat):

```python
    title = " ".join(_restore(original, title.split(), brand_names))
    title = " ".join(_strip_connectors(_drop_repeats(title.split())))
```

(the second line is the existing repeat step, unchanged; the restore line is the only addition)

The status rules are unchanged in code: after the trim, `review` if an original word is still lost (when the 150-character trim cuts an original word, whether the suggestion kept it or the restore put it back, or when the repeat step drops a restored hyphenated word whose other half is already earlier in the title), else `pass` or `adjusted`. A restored title differs from the suggestion, so it is `adjusted` with empty dropped words. The docstring gains the restore step and says `review` now means an original word was lost by the trim or the repeat step.

Examples (checked on a scratch copy, 2026-09-30):
- "BSOAgentTestBrand Beige Women Slippers" for "BSOAgentTestBrand Women Casual Slipper Beige" (allowed ["women slippers"]) gives "BSOAgentTestBrand Beige Women Casual Slippers", `adjusted`.
- "BSOAgentTestBrand Brown Men Sandals" for "BSOAgentTestBrand Men Casual Sandal Brown" gives "BSOAgentTestBrand Brown Men Casual Sandals", `adjusted`.
- The integration fixture "Walkaroo Kids Summer Sandals Sandals" for "Walkaroo Boys Sandal 0" gives "Walkaroo Boys Kids Summer Sandals", `adjusted` (today `review` with ["boys"]).
- "Walkaroo Anti Sandal" for "Walkaroo Anti-Skid Sandal" gives "Walkaroo Anti-Skid Sandal", and "Walkaroo Sandal Wear" for "Walkaroo Casual Sandal Casual Wear" gives "Walkaroo Casual Sandal Wear", both `adjusted` (the repeat step runs after the restore).
- Known ceiling (approved): a replaced product type ends up as both types, `adjusted`: "Tape Shoes" for "Red Tape Boots" gives "Red Tape Boots Shoes"; "Navy Men Slipper" for "Men Flip Flop Navy" gives "Navy Men Flip Flop Slipper".
- Ceilings accepted from the spec review:
  - The page, the API and the CSV no longer show which word the model dropped: a restored word shows as `adjusted` with an empty dropped list; only `raw_title` (read with psql, not exposed) shows it. Consumers are unchanged in code (API `ProductOut.rule_check`/`dropped_words`, the products page tag and `droppedNote`, the CSV `rule_check`/`dropped_words` columns); `review` and a non-empty "dropped: …" note appear only when the trim cuts an original word or the repeat step drops a restored hyphenated word.
  - Numbers and stopwords are never restored, because `dropped()` skips them: "Walkaroo Sandal" for "Walkaroo Sandal 2 Pack" gives "Walkaroo Sandal Pack"; a lost "for" stays lost.
  - The anchor is the first title word sharing a stem with the nearest earlier original word, which can be a function word: "Look with Sandal" for "Sandal with Casual Look" gives "Look with Casual Sandal".
  - The repeat step runs after the restore, so a restored hyphenated word whose other half is already earlier in the title is dropped again: "Walkaroo Anti Boys Sandal" for "Walkaroo Boys Anti-Skid Sandal" gives `review` with lost ["skid"] (the same result as on main).
  - A restored word adds length, so the trim can cut words the model added at the end (such as the keyword) with status `adjusted` and no flag; dev's original titles are 34 to 44 characters and slice 25's raw titles 44 to 53 (docs/findings-slice25.md §2).

### 3. Testing

`tests/unit/test_products.py` (values computed on the scratch copy):
- `test_rule_check_trims_to_150_at_a_word_boundary`: with original "Plain", the result is `adjusted`, lost `[]`, 147 characters, starting "Plain w0 w1" and ending "w37"; the test asserts `status == "adjusted" and lost == []`, `len(fixed) <= 150`, and `fixed.removeprefix("Plain ") == " ".join(words)[: len(fixed) - 6]`.
- New `test_rule_check_trim_can_still_lose_a_restored_word`: original "w59 Plain" with the same 229-character suggestion gives `review` with lost `["w59", "plain"]`, 149 characters.
- `test_rule_check_strips_a_connector_the_trim_leaves_at_the_end`: the original becomes "w0" (a word the suggestion keeps), so nothing is restored and the cut still lands after "for"; the result is "w0 … w38" (145 characters), `adjusted`. (With "Plain" the restore would move the cut to "w37", and the test would pass without exercising the strip.)
- New `test_rule_check_repeat_step_can_drop_a_restored_hyphenated_word`: `rule_check("Walkaroo Boys Anti-Skid Sandal", "Walkaroo Anti Boys Sandal", ["Walkaroo"]) == ("Walkaroo Anti Boys Sandal", "review", ["skid"])` (passes on main too; it pins the ceiling).
- New `test_rule_check_restore_does_not_bring_back_a_repeat`: `rule_check("Walkaroo Anti-Skid Sandal", "Walkaroo Anti Sandal", ["Walkaroo"]) == ("Walkaroo Anti-Skid Sandal", "adjusted", [])` and `rule_check("Walkaroo Casual Sandal Casual Wear", "Walkaroo Sandal Wear", ["Walkaroo"]) == ("Walkaroo Casual Sandal Wear", "adjusted", [])`.
- `test_rule_check_drops_a_word_that_repeats_an_earlier_token`, the Red Tape case: `("Red Tape Boots Shoes", "adjusted", [])`.
- `test_rule_check_does_not_count_a_removed_repeat`, the repeat-plus-lost-word case: `("Walkaroo Boys Kids Sandal", "adjusted", [])`, and its comment ("A repeat plus a lost word is still flagged for review.") becomes "A repeat plus a lost word: the word is restored.".
- `test_rule_check_flags_dropped_words_for_review` is renamed `test_rule_check_restores_dropped_words` and expects `("Brown Mens Casual Sandal Shoes", "adjusted", [])` and `("Navy Men Flip Flop Slipper", "adjusted", [])`.
- New `test_rewrite_prompt_leaves_keyword_words_out_of_missing`: a product with keyword "kids sandals" and missing ["kid", "summer"] gives `"missing": ["summer"]` in the prompt; a product with keyword "men watches" and missing ["men", "watch", "analog"] gives `"missing": ["analog"]`; a product whose missing words are all in its keyword gets no `"missing"` key.

`tests/integration/test_products_run.py`:
- `test_one_search_per_distinct_keyword_and_the_rewrite_is_checked`: suggested title "Walkaroo Boys Kids Summer Sandals", `(rule_check, dropped_words) == ("adjusted", [])`; `raw_title` unchanged; its comment ("…loses "boys", so the suggestion is flagged for review.") becomes one that says "boys" is restored.
- `test_a_failed_search_is_stored_and_the_run_goes_on`: suggested title "Walkaroo Boys Kids Sandals".

The other 116 of the 122 collected items in those two files pass unchanged on the scratch copy (with the restore before the repeat step and the `_allowed_stems` filter). No model call and no probe: both changes are deterministic.

### 4. Live check and docs

- **Live check, after merge, with the user's OK at that point:** one `product_run` on dev by the live-check pattern (API queues, `process_job` once, the worker loop never started). Dev is at 0021; no migration. The 8 stored keywords' `keyword_search` rows are fresh until 2026-10-06 13:10 UTC ("mens flip flops" until 2026-10-07 09:27; docs/findings-slice23.md §3; `SEARCH_TTL_DAYS` = 7). Expected cost about 6,600 micros (slice 26's check: 6,545), plus about 38,000 per keyword with no fresh valid row. Writes: the job, the 10 product rows, `api_key.last_used_at`, any new `keyword_search` row.
- **Read-back:** per product, the raw title, the suggested title, the status and the dropped words, stated as observed. *Inferred* expectation: LC-01's and LC-02's raw titles no longer pair "kid" with "Kids"; any dropped original word is restored and the product shows `adjusted` (the read-back also lists, for any `adjusted` product, which original words the suggested title has that the raw title lacks, since `dropped_words` stays empty); with main's prompt a drop is rare, so the run may show none.
- **Docs:** this spec, the plan, `docs/findings-slice27.md` (the live check, every `minor (deferred)` and `parked` ledger line), docs/README.md rows, the `(this commit)` hash convention, and every ruling named in chat when made.

## Rulings

None.

Correction (2026-10-01, after merge): the ledger records two rulings, made after the docs task, so they are recorded here in the post-merge docs commit:

- **R1: a pre-existing doubled period in the plan is left unfixed.** Decided: the plan's Task 2 changes bullet ends `stays "None.".` (doubled punctuation, there before the fix wave); it is left as is. Found by the final fix wave's re-review (a trivial nit). Why: the skill allows one fix wave and no controller fixes after it, and deferring it into findings would need another findings commit. Cost if wrong: one stray period in the plan. Named in chat and ledgered when made; recorded here in the post-merge docs commit.
- **R2: the plan re-review's two optional wording points were left unapplied.** Decided: at the end of planning, the plan re-review's optional points (the self-review line could also name the hyphen test; departure (5) overlaps departure (2)) were not applied. Found by the plan re-review. Why: applying them would need another review round for no change in substance. Cost if wrong: two small wording imprecisions in the plan. Disclosed in chat when made but not named as a ruling until the process audit; ledgered after the audit.

## Out of scope

- Any change to `missing()`, the stored missing list, the UI or the CSV.
- Keeping `review` when the model replaced the product type (the approved ceiling).
- Any rewrite prompt wording change other than the `missing` field's content.
- The deferred items in docs/findings-slice26.md §4.
