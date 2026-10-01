# Slice 34 design: a unit test for the `-es` rule's length guard

## Context

Codebase facts: main `02f3592`, checked 2026-10-01.

docs/findings-slice33.md §3 quotes the deferred minor: "Task 1: minor (deferred): tests/unit/test_rivals.py:528-531 — the stem list does not pin the `len > 4` guard on the -es rule (`axes` → `axe`, `shes` → `she`); a mutation to `> 3` would turn `axes` into `ax` and pass every listed case; the spec names no boundary case." and its "Untested" line names "the `len > 4` guard on the `-es` rule (`axes` → `axe`; Task 1's deferred minor above)". The user asked for "a unit test for the axes length guard".

Facts read before the approaches (direct reads on Opus 5.5):
- `rivals._stem` (packages/core/bsi_core/rivals.py:55-67): `if len(word) > 4 and word.endswith(_ES): return word[:-2]`, with `_ES = ("ches", "shes", "xes", "sses", "zzes")`; then the `ss` keep; then the one-`s` rule on words longer than three characters.
- `test_stem_folds_plurals` (tests/unit/test_rivals.py:525-546) pins `boxes → box` (five characters, the shortest `_ES` case it lists) and no four-character `-es` word.
- In memory, the real rule gives `axes → axe`, `shes → she`, `taxes → tax`, `boxes → box`; a mutant with `len(word) > 3` gives `axes → ax`, `shes → sh`, and the same for the five-character words.

Classification, said in chat as the first line of the first brainstorming reply: **bounded** — "one test added to an existing file, no production code change; the flow (`_stem`'s `len(word) > 4` guard) already exists to read." The user's process rule asks for a spec even for small changes, so this file exists.

Decision approved in chat (brainstorming on Opus 5.5, 2026-10-01), after three approaches with trade-offs and a recommendation in a chat message: a separate named test (over adding `axes` and `shes` to the existing list, the smallest diff but with an unnamed failure; and a parametrized boundary that would duplicate `boxes`). The user chose the separate named test. The design text was in chat before its approval question; the user approved it.

## Design

- tests/unit/test_rivals.py, directly after `test_stem_folds_plurals`:

```python
def test_stem_es_rule_skips_four_letter_words():
    # The -es rule needs more than four characters: axes and shes fall
    # through to the one-s rule (axe, she), not ax and sh.
    assert [_stem(w) for w in ("axes", "shes")] == ["axe", "she"]
```

- No production change: `_stem` already behaves this way.
- Proof, checked on 2026-10-01 on scratch copies outside the repo (a copy of `bsi_core` with line 63 changed to `len(word) > 3`; the test in a separate folder): on main's code the new test gives `1 passed in 0.06s`; on the mutant `1 failed in 0.05s` with `At index 0 diff: 'ax' != 'axe'`; the existing tests/unit/test_rivals.py and tests/unit/test_products.py give `132 passed` on the mutant and `132 passed` on main, so before this test nothing pinned the guard. ruff check and ruff format --check are clean on the test.
- Counts: tests/unit/test_rivals.py 32 → 33; backend 1570 → 1571.
- Copy: the new comment and test name are checked against `FORBIDDEN` in tests/unit/test_recommend_copy.py by a grep of the diff.

## Process and docs

- Branch `slice34-axes-guard-test`; spec reviewer; plan by writing-plans (one task); one implementer and its task review; final whole-branch review; PR; merge on the user's go-ahead.
- Post-merge docs: dated notes (originals kept) under the Task 1 deferred minor and the "Untested" line in docs/findings-slice33.md §3, pointing here; the note under the "Untested" line covers only the `len > 4` guard, and that line's other item (the rule on real catalogue data beyond dev's 10 products) stays untested. Two README rows, a spec row then a plan row, directly after the `findings-slice33.md` row; no findings file of its own, since this spec and the PR description carry the results.
- No live check: a test-only change touches no running system.

## Rulings

- **R1: the spec review's three minors were applied.** Decided: "the shortest `_ES` case it lists" (shoes and sizes are also five characters); the note under findings-slice33's "Untested" line covers only the guard, and the catalogue-data item stays untested; the README rows (spec, then plan) go after the `findings-slice33.md` row. Found by the spec review of 953097e and 3940e03. Why: accuracy for the plan writer. Cost if wrong: none. Named in chat when made.

## Out of scope

- Other boundary cases of `_stem` (the `ss` keep below four characters, `ass`); any change to `_stem`.
