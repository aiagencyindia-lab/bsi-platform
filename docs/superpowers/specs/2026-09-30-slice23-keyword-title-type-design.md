# Slice 23 design: the searched keyword when title and category disagree

## Context

LC-05 ("BSOAgentTestBrand Men Flip Flop Navy", category "Slippers") got the searched keyword "navy flip flops" in 3 of the 4 live checks on record (slice 20's first check, slice 21's and slice 22's; slice 20's second check gave "men flip flops"). The other 9 dev products get the audience plus the product type ("kids sandals", "men shoes"). Slices 20, 21 and 22 each listed "the keyword vote choosing a colour phrase" as out of scope.

Classification, said in chat as the first line of the first brainstorming reply: **bounded** — "it changes one existing step, the keyword choice in `products.py`, with no schema, API or web change; by your standing rule it still gets a spec, a plan and the full review cycle."

Decisions approved in chat (brainstorming on Fable 5.1, 2026-09-29 and 2026-09-30). Sections 1, 2 and 3 each had their design text in chat before their approval:

- **Target:** the audience plus the type ("men flip flops"), the same shape as the other 9 products. Rejected: any keyword without a colour ("mens casual flip flops"), and the keyword minus its colour ("flip flops").
- **Probes:** four, each approved by the user before it ran (below).
- **Approach, first choice:** A, a new prompt sentence plus a colour guard. Rejected then: B (the guard only), C (build the keyword in code) and the prompt sentence only.
- **A first Section 1 (the prompt sentence) was approved and then withdrawn**, with the user's OK, after probes 2 to 4: the prompt is not changed.
- **Final design:** the guard plus a built fallback. Rejected: the guard only (LC-05 gets a narrower keyword when the model does not offer "men flip flops"), and stopping with a findings doc only.
- **After the spec review, finding 4:** the guard falls back per product, not per sample. Rejected: no fallback (a product whose every keyword has a colour word gets no keyword), and keeping the per-sample fallback (a colour keyword could still be searched).
- **After the spec review, finding 7:** the built keyword's type words follow both rules, shared words and an audience list. Rejected: either rule alone, and dropping the fallback.
- **After the spec re-review, finding 1:** a keyword counts as title-fitting for `title_first` only when its type word is in the title and is not an audience word. Rejected: dropping the fallback, and listing the case as a ceiling.
- **After the final whole-branch review (Ruling R2):** the user asked for the review's wrong-type regression to be fixed without fix (a)'s singular "men flip flop" on probe 4's samples ("fix it"). The controller chose option (b): a second fallback in `choose_keywords`, and no colour or size word in `title_first`'s audience.

### The probes

Each probe: the 10 dev products read from dev read-only, `keyword_prompt` called `SAMPLES` (3) times through `judge.generate` at `KEYWORD_TEMPERATURE`, then the current `vote`, `drop_brand_terms` and `fit_rank` applied in a scratch script. No database writes, no job, no worker, no repo edits. Probes 2 to 4 added one sentence to the prompt text inside the scratch script, after the rank-1 sentence.

| Probe | Sentence added | Cost (micros) |
|---|---|---|
| 1 | none (today's prompt) | 4,415 |
| 2 | "When the title names a different product type from the category, rank 1 uses the type named in the title (a "Men Flip Flop Navy" in the category "Slippers" is "men flip flops")." | 4,367 |
| 3 | the same sentence with the example (a "Women Clog Black" in the category "Sandals" is "women clogs") | 5,099 |
| 4 | "Always include the audience plus the product type named in the title as one keyword, even when the category names a different type (a "Women Clog Black" in the category "Sandals" includes "women clogs")." | 4,845 |

Total 18,726 micros; spend about $10.90 of the $15 cap.

Observed for LC-05:

| Probe | Rank 1 in samples 1, 2, 3 | Samples offering "men flip flops" | After `vote` and `fit_rank`, first keyword |
|---|---|---|---|
| 1 | men slippers, men slippers, men slippers | 2 of 3 | men flip flops |
| 2 | men slippers, men flip flops, men flip flops | 3 of 3 | men flip flops |
| 3 | men slippers, men slippers, men slippers | 3 of 3 (one as "mens flip flops") | men flip flops |
| 4 | men slippers, men slippers, men slippers | 2 of 3 | men flip flop navy |

Observed for the other 9 products: the same rank 1 in all 3 samples of every probe, and the same first keyword after `fit_rank` in all four probes (kids sandals ×2, kids shoes ×2, kids slippers, men sandals, men shoes, women slippers, women sandals).

What the probes show:

- The model's first keyword for LC-05 is the audience plus the *category's* type: "men slippers" in 10 of 12 samples. (An earlier count in chat and in the approved plan said 11 of 12; the table above gives 10.) The prompt asks for "the audience plus the product's own category".
- The colour keyword is not the model's first choice. `fit_rank` puts keywords whose type is in the title ahead of "men slippers", so the searched keyword is the first title-fitting keyword that `vote` kept.
- In probe 4, "men flip flops" was offered in 2 of 3 samples and still cut: `vote` keeps `MAX_KEYWORDS` (5) keys, the top key and then the others in first-seen order, so sample 1's list took the places.
- Probe 2's gain came from the example being LC-05 itself; with a neutral example (probe 3) rank 1 did not change.
- Probe 4's sentence made the model echo titles: "men flip flop navy" (LC-05, sample 1) and "kids slipper grey" (LC-04, all 3 samples).
- *Inferred*: in the real runs that gave "navy flip flops", the model did not offer "men flip flops", or `vote` cut it. The raw samples of those runs were not stored. LC-05's stored list after slice 22's check is "navy flip flops", "mens casual flip flops", "daily wear flip flops", "men slippers", "cushioned slippers".

Codebase facts (main `0029d03`, checked 2026-09-30 by running the current code):

- `run_products` builds each product's keywords as `fit_rank(drop_brand_terms(vote(samples), names), title, category, description)`, maps each through the run-wide `key_map` by `keyword_key`, and searches the first.
- `fit_rank` finds a keyword's category word as the last folded word before the keyword's first `CATEGORY_CUTS` token ("for", "with"), or the keyword's last folded word if nothing folds before the cut. It keeps keywords whose category word is in the title first, then those whose word is only in the category or description, and drops the rest.
- `NOISE_WORDS` (slice 21): white, black, blue, red, green, pink, grey, gray, brown, navy, beige, tan, silver, gold, purple, orange, yellow, cream, multi, multicolor, color, colour, size, little, big. `NOISE_STEMS` holds their stems.
- `STOPWORDS` contains "for" and "with".
- `vote` returns each key in its `_display` form, so a possessive 's is already removed.
- In `tests/integration/test_products_run.py`, the fake generator's keywords are the default `["kids sandals", "walkaroo kids"]`, `keywords=["walkaroo sandals"]` and, in `test_plural_variants_share_one_search`, `by_index={0: ["mens sandal"], 1: ["men sandals"]}`. The first two run against the seeded title "Walkaroo Boys Sandal 0"; the third seeds its own products, "Walkaroo Men Sandal A" and "Walkaroo Men Sandal B". With this design each gives the same list as today before the run-wide `key_map`: `["kids sandals"]`, `[]`, `["mens sandal"]` and `["men sandals"]` (the `key_map` then stores both of the third test's products as `["mens sandal"]`, as today).
- `rewrite_prompt` passes each product's `keyword` to the model, so a built keyword reaches the rewrite like any other.
- The 9 dev products other than LC-05 share 7 distinct keywords: kids sandals, kids shoes, kids slippers, men sandals, men shoes, women slippers, women sandals. Their `keyword_search` rows were searched on 2026-09-29.
- Measured costs: slice 21's re-check (8 grounded searches with their parse calls, 3 keyword calls, 1 rewrite) cost 310,292 micros; slice 22's (no search, 3 keyword calls, 1 rewrite) cost 5,819. So one grounded search with its parse call is about 38,000 micros. `budget_fits` reserves `SEARCH_MICROS` (45,000) per new search; that is the budget check, not the cost.

## Design

All code changes are in `packages/core/bsi_core/products.py`. No prompt, schema, API or web change.

### 1. The colour and size guard

New function, next to `drop_brand_terms`:

```python
def drop_noise_terms(keywords: Sequence[str]) -> list[str]:
    """Keep a keyword only if none of its stems is a colour or size
    word (NOISE_STEMS)."""
    return [k for k in keywords if not fold_set(k) & NOISE_STEMS]
```

New function, the whole keyword choice for one product:

```python
def choose_keywords(
    samples: Sequence[Sequence[str]],
    brand_names: Sequence[str],
    title: str,
    category: str | None,
    description: str | None,
) -> list[str]:
    """One product's keywords, the searched one first: the vote over
    the samples without colour and size keywords, without brand terms,
    the title's type first (title_first), then fit_rank. The same over
    the samples as given is used instead when the first leaves nothing,
    or when its first keyword names a type the title does not and the
    second's first keyword names one the title does."""

    def pick(lists: Sequence[Sequence[str]]) -> list[str]:
        ranked = drop_brand_terms(vote(lists), brand_names)
        return fit_rank(
            title_first(ranked, title), title, category, description
        )

    in_title = fold_set(title)

    def fits(keywords: Sequence[str]) -> bool:
        return bool(keywords) and _type_word(keywords[0]) in in_title

    guarded = pick([drop_noise_terms(s) for s in samples])
    if fits(guarded):
        return guarded
    raw = pick(samples)
    return raw if fits(raw) or not guarded else guarded
```

`run_products` replaces its `vote` and `fit_rank` lines with:

```python
fitted = choose_keywords(
    [sm.get(i, []) for sm in samples],
    names,
    p["title"],
    p["category"],
    p["description"],
)
```

- Colour and size keywords are removed from every sample before the vote, so they cannot take one of `vote`'s `MAX_KEYWORDS` places.
- **The fallback is per product** (spec review, finding 4). The unfiltered samples are used when the filtered samples leave the product with no keyword at all, after the brand filter and `fit_rank` too. A product with no keyword gets no suggestion (R13), so a colour keyword is better than none.
- **The wrong-type fallback** (final review, Important 1; Ruling R2). The unfiltered samples are also used when the filtered result's first keyword names a type the title does not, and the unfiltered result's first keyword names one the title does. Without it, when every title-fitting keyword has a colour word, the guard removes them all and `fit_rank` searches the category's type: for LC-05's title and category, samples `[["men slippers", "navy flip flops", "cushioned slippers"]] * 3` gave "men slippers" (main: "navy flip flops"). With it they give "men flip flops", built by `title_first` from "navy flip flops" with the colour kept out.
- So a colour or size keyword is searched only when no keyword without one names the title's type and none can be built: for example samples `[["navy flip flops", "men slippers"]] * 3` for LC-05 search "navy flip flops", as on main, rather than the category's "men slippers" (the title's type ranks above the category's, as in `fit_rank`). A colour or size keyword is stored in `keywords` whenever an unfiltered path is used, after the searched keyword or as it ("navy flip flops" in both examples).
- `vote`, `drop_brand_terms` and the run-wide `key_map` are unchanged.
- The existing comment above `NOISE_WORDS` says `missing()` never suggests these words. It gains one clause: the keyword choice drops keywords that contain them too.
- Known ceilings, in a `# ponytail:` comment:
  - A real colour or size phrase that shoppers type ("white sneakers", "little kids sandals", "big kids shoes") is searched only when no keyword without one names the title's type and none can be built.
  - Outside footwear some of these are product words ("gold", "cream", "plus size").
  - English only.

### 2. The built fallback

`fit_rank`'s lines that find a keyword's category word move into a helper. `fit_rank` calls it and behaves as before:

```python
def _type_word(keyword: str) -> str | None:
    """The keyword's category word: the last folded word before its
    first CATEGORY_CUTS token, or its last folded word if nothing folds
    before the cut; None if nothing folds."""
    words = fold(keyword)
    if not words:
        return None
    toks = tokens(keyword)
    cut = next((i for i, t in enumerate(toks) if t in CATEGORY_CUTS), len(toks))
    head = fold(" ".join(toks[:cut]))
    return (head or words)[-1]
```

New constant and function:

```python
# Never part of a built keyword's type words (slice 23 spec §2).
AUDIENCE_WORDS = frozenset("men women kids boys girls unisex baby".split())
AUDIENCE_STEMS = frozenset(_stem(w) for w in AUDIENCE_WORDS)


def title_first(keywords: Sequence[str], title: str) -> list[str]:
    """When the first keyword names a type the title does not, and
    other keywords name one it does, put the first keyword's audience
    plus the title's type first ("men slippers" and "cushioned flip
    flops" for "Men Flip Flop Navy" -> "men flip flops"); an offered
    keyword with the same key is used in its own spelling. Otherwise
    the keywords as given. At most MAX_KEYWORDS."""
    if not keywords:
        return []
    in_title = fold_set(title)
    word = _type_word(keywords[0])
    if word is None or word in in_title:
        return list(keywords)
    types = in_title - AUDIENCE_STEMS
    fits = [k for k in keywords if _type_word(k) in types]
    if not fits:
        return list(keywords)
    audience = [
        t
        for t in tokens(keywords[0])
        if len(t) > 1
        and _stem(t) != word
        and t not in STOPWORDS
        and _stem(t) not in NOISE_STEMS
    ]
    ok = in_title - {_stem(t) for t in audience}
    ok = ok - AUDIENCE_STEMS - NOISE_STEMS
    for k in fits:
        ok &= fold_set(k)
    kind = [t for t in tokens(fits[0]) if _stem(t) in ok]
    if not audience or not kind:
        return list(keywords)
    built = " ".join([*audience, *kind])
    key = keyword_key(built)
    first = next((k for k in keywords if keyword_key(k) == key), built)
    rest = [k for k in keywords if keyword_key(k) != key]
    return [first, *rest][:MAX_KEYWORDS]
```

- It applies only when both conditions hold: the first keyword's type word is not in the title, and another keyword is title-fitting.
- **Title-fitting**, for `title_first` (spec re-review, finding 1): the keyword's type word is in the title and is not in `AUDIENCE_STEMS`. So "slippers boys" and "casual men" are not title-fitting for a "Boys Sandal" or a "Men Flip Flop". `fit_rank`'s own rule is unchanged.
- **Audience:** the first keyword's tokens, without 1-letter tokens, without its type word, without `STOPWORDS` (which hold "for" and "with") and without `NOISE_STEMS` words (Ruling R2; before it, "men navy slippers" built "men navy flip flops" on the unfiltered path).
- **Type** (spec review, finding 7): the tokens of the first title-fitting keyword whose stems pass all of these:
  - in the title;
  - in every title-fitting keyword (shared words);
  - not an audience stem of the first keyword, not in `AUDIENCE_STEMS`, not in `NOISE_STEMS`.
- When it builds a keyword that was not offered and the list is already `MAX_KEYWORDS` long, the last keyword is cut.
- `fit_rank` runs after it, as today, so a built keyword is kept only because its type word is in the title.
- Known ceilings, in a `# ponytail:` comment:
  - The audience is whatever is left of the first keyword after its colour and size words (R2), in the model's spelling: "men house slippers" gives "men house flip flops", "mens slippers" gives "mens flip flops", and "babies booties" with "baby shoes" for a "Baby Shoe" gives "babies shoes".
  - When the title-fitting keywords name two different types that are both in the title, they share no word and nothing is built.
  - Audience-then-type order suits English.
  - With one title-fitting keyword, a style word in it that the title has too is kept: "men floaters" and "casual sandals" give "men casual sandals".
  - `AUDIENCE_WORDS` is closed and English only ("ladies", "gents", "teens" are not in it).
  - Observed on footwear only.
  - It depends on the model's first keyword being the audience plus the category's type (10 of 12 LC-05 samples).
  - A title word that is not a product type can count as one: the rule only checks that a keyword's type word is in the title and is not an audience word.
  - The type words take the first title-fitting keyword's spelling, so they can be singular: samples `[["men slippers", "men flip flop navy", "cushioned slippers"]] * 3` for LC-05 build "men flip flop" (main: "men flip flop navy"). The probes never produced this: each had a plural title-fitting keyword first.
  - `choose_keywords`' wrong-type fallback (R2) uses `fit_rank`'s rule, in which an audience word in the title counts as a type word; so "slippers boys" for a "Boys Sandal" keeps the guarded result, as before R2 and on main.

### 3. Testing

Unit, `tests/unit/test_products.py`. `T` is "BSOAgentTestBrand Men Flip Flop Navy", `W` is "Walkaroo Boys Sandal 0", `B` is `["BSOAgentTestBrand"]`:

`drop_noise_terms`:
- `drop_noise_terms(["men slippers", "navy flip flops", "men flip flop navy"]) == ["men slippers"]`.
- `drop_noise_terms(["navy flip flops", "blue flip flops"]) == []`.
- Size words: `drop_noise_terms(["free size slippers", "little kids sandals", "kids sandals"]) == ["kids sandals"]`.

`_type_word`:
- `[_type_word(k) for k in ("men slippers", "slippers for men", "men slip on shoes", "for", "")] == ["slipper", "slipper", "shoe", "for", None]`.

`title_first`:
- `title_first(["men slippers", "cushioned flip flops"], T) == ["men flip flops", "men slippers", "cushioned flip flops"]`.
- `title_first(["slippers for men", "daily wear flip flops"], T) == ["men flip flops", "slippers for men", "daily wear flip flops"]`.
- An offered keyword with the same key keeps its spelling: `title_first(["men slippers", "cushioned flip flops", "mens flip flops"], T) == ["mens flip flops", "men slippers", "cushioned flip flops"]`.
- The first keyword fits the title: `title_first(["kids slippers", "kids flip flops"], "BSOAgentTestBrand Kids Slipper Grey") == ["kids slippers", "kids flip flops"]`.
- No keyword fits the title: `title_first(["men slippers", "cushioned slippers"], "BSOAgentTestBrand Men Thong Navy") == ["men slippers", "cushioned slippers"]`.
- No audience word: `title_first(["slippers", "flip flops"], T) == ["slippers", "flip flops"]`.
- Empty: `title_first([], T) == []`.
- The cap: `title_first(["men slippers", "a", "b", "c", "cushioned flip flops"], T) == ["men flip flops", "men slippers", "a", "b", "c"]`.
- An audience word in the title is not a type word: `title_first(["kids slippers", "boys sandals"], W) == ["kids sandals", "kids slippers", "boys sandals"]` and `title_first(["kids slippers", "sandals for boys"], W) == ["kids sandals", "kids slippers", "sandals for boys"]`.
- Shared words: `title_first(["men floaters", "casual sandals", "floater sandals"], "BSOAgentTestBrand Men Casual Sandal Brown") == ["men sandals", "men floaters", "casual sandals", "floater sandals"]`.
- The one-fit ceiling: `title_first(["men floaters", "casual sandals"], "BSOAgentTestBrand Men Casual Sandal Brown") == ["men casual sandals", "men floaters", "casual sandals"]`.
- Only an audience word fits: `title_first(["kids slippers", "slippers boys"], W) == ["kids slippers", "slippers boys"]`.
- A good fit and an audience-word fit together: `title_first(["men slippers", "cushioned flip flops", "casual men"], T) == ["men flip flops", "men slippers", "cushioned flip flops", "casual men"]`.
- Two title types: `title_first(["men slippers", "flip flops", "men thongs"], "X Men Flip Flop Thong") == ["men slippers", "flip flops", "men thongs"]`.
- A colour word is never built in: `title_first(["men slippers", "navy flip flops"], T) == ["men flip flops", "men slippers", "navy flip flops"]`.
- Nor from the first keyword (R2): `title_first(["men navy slippers", "navy flip flops"], T) == ["men flip flops", "men navy slippers", "navy flip flops"]`.

`choose_keywords`:
- Probe 4's samples for LC-05, `choose_keywords(S4, B, T, "Slippers", "Cushioned flip flop for daily use") == ["men flip flops", "cushioned flip flops", "daily use flip flop", "men slippers", "cushioned slippers"]`, where `S4` is `[["men slippers", "men flip flop navy", "navy flip flops", "cushioned flip flops", "daily use flip flop"], ["men slippers", "men flip flops", "navy flip flops", "cushioned slippers"], ["men slippers", "men flip flops", "navy flip flops", "cushioned flip flops"]]`.
- One all-colour sample does not bring colour back: `choose_keywords([["navy flip flops"], ["navy flip flops", "men slippers"], ["men slippers", "men flip flops"]], B, T, "Slippers", None) == ["men flip flops", "men slippers"]`.
- Every keyword has a colour: `choose_keywords([["navy flip flops", "blue flip flops"]], B, T, "Slippers", None) == ["navy flip flops", "blue flip flops"]`.
- Only a brand phrase is left after the guard: `choose_keywords([["walkaroo sandals", "navy sandals"]], ["Walkaroo"], W, None, None) == ["navy sandals"]`.
- An audience-word keyword does not stop the build: `choose_keywords([["kids slippers", "boys sandals", "slippers boys"]] * 3, ["Walkaroo"], W, None, None) == ["kids sandals", "boys sandals", "slippers boys"]`.
- No samples: `choose_keywords([], B, T, None, None) == []`.
- The wrong-type fallback (R2): `choose_keywords([["men slippers", "navy flip flops", "cushioned slippers"]] * 3, B, T, "Slippers", None) == ["men flip flops", "navy flip flops", "men slippers", "cushioned slippers"]`.
- A category fit alone keeps the guarded result: `choose_keywords([["men slippers", "navy slippers"]], B, "X Men Thong Navy", "Slippers", None) == ["men slippers"]`.
- No colour in a built keyword on the unfiltered path (R2): `choose_keywords([["men navy slippers", "navy flip flops", "cushioned slippers"]], B, T, None, None) == ["men flip flops", "navy flip flops"]`.

The three existing `fit_rank` tests, the three `vote` tests and the `drop_brand_terms` test keep their values.

Integration, `tests/integration/test_products_run.py`:

- One new test. One seeded product ("Walkaroo Boys Sandal 0", no description or category); the fake generator's keywords are `["kids slippers", "blue sandals", "strap sandals"]`; the default engine answer and titles. After `run_products`: `keyword == "kids sandals"`, `keywords == ["kids sandals", "strap sandals"]`, and the engine's prompts are `[(products.search_query("kids sandals"), "IN", "en")]`.
- No existing integration test changes (codebase facts).

Copy: no prompt changes, so `PRODUCT_CASES` is unchanged. The new fixtures and comments are checked against `FORBIDDEN` in `tests/unit/test_recommend_copy.py`.

### 4. Dev re-check

Run by the controller only with the user's OK at that point, by the live-check pattern (the worker loop is never started).

- Expected cost: about 44,000 micros ($0.044). That is about 6,000 for the 4 flash-lite calls (3 keyword samples and 1 rewrite, for one batch of 10; slice 22's re-check measured 5,819) and about 38,000 for 1 new grounded search for "men flip flops" with its parse call.
- The 7 keywords of the other 9 products were searched on 2026-09-29 and stay fresh for 7 days. The "men flip flops" row from slice 20 has no `parse` key and counts as a miss.
- Each further keyword that is not one of those 7 adds one grounded search with its parse call, about 38,000 micros.
- Writes: the job, 10 product rows, 1 `keyword_search` row, `api_key.last_used_at`.
- Expected, *inferred* from the probes, to be compared with what is observed: LC-05's keyword is "men flip flops"; the other 9 keywords are unchanged; no stored `keywords` list contains a colour or size word, if every product's guarded result names its title's type (otherwise R2's fallback stores the unfiltered list).

## Rulings

- **R1: the README's slice 23 spec row drops the rulings clause.** Decided: the README's slice 23 spec row ends at "…with the four probes of the keyword prompt." (the rulings clause is dropped), departing from the plan's Step 2 wording. Found by the Task 3 review. Why: the row must not claim rulings the spec does not hold; dropping the clause stays true whatever the spec's Rulings holds, while "(none)" would become false once this ruling itself is recorded. Cost if wrong: the row no longer points readers to the spec's Rulings section.
- **R2: the wrong-type fallback in `choose_keywords`, and no colour in the audience.** Decided: fix the final review's Important 1 with option (b), not fix (a): `choose_keywords` keeps the guarded path, and uses the unguarded path instead when the guarded result's first keyword names a type the title does not and the unguarded result's first keyword names one the title does; `title_first`'s audience also leaves out `NOISE_STEMS` words (§1, §2). Found by the final whole-branch review (Important 1) and the Task 2 review (the fallback-colour minor). Why: the user asked for the regression to be fixed without fix (a)'s singular "men flip flop" on probe 4's samples; option (b) keeps probe 4's "men flip flops" and every other value in §3, and gives "men flip flops" for the regression case (main: "navy flip flops"; before R2: "men slippers"). Cost if wrong: the stored `keywords` list keeps colour keywords whenever the fallback is used; a colour keyword that names the title's type is searched ahead of a category-only keyword when nothing can be built (`[["navy flip flops", "men slippers"]] * 3` searches "navy flip flops", as main does; before R2 "men slippers"); and a close variant of probe 4 still builds the singular "men flip flop" (`[["men slippers", "men flip flop navy", "cushioned slippers"]] * 3`; main: "men flip flop navy"; before R2: "men slippers"), because the fallback reaches the unfiltered path more often. The spec re-review found these; the controller kept R2 as is, since each is the title's type and none is worse than main (Ruling R3).
- **R3: R2's side effects are accepted as ceilings.** Decided: no further code for the three cases in R2's cost (colour keyword stored; colour keyword searched when nothing can be built; singular type word when the only title fit is singular); they are listed as ceilings in §1 and §2. Found by the review of the R2 spec change. Why: in each case the searched keyword names the title's type, which is the slice's target, and each gives the same type as main; a plural-spelling rule was simulated and helps only when some title-fitting keyword is plural, so it was not added. Cost if wrong: LC-05 can search "navy flip flops" or "men flip flop" on a run where the model offers no colour-free plural flip-flop keyword.

## Out of scope

- `vote`'s first-seen ordering and its `MAX_KEYWORDS` cap.
- Storing the raw keyword samples or the raw rewrite.
- Any prompt change.
- The deferred minors in docs/findings-slice21.md §3 and docs/findings-slice22.md §3.
