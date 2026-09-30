# Design: delete the 11 unused `keyword_search` rows on dev

Written after the fact (2026-10-01), at the process audit's request: the change went ahead on the bounded path with no spec (R5).

## Context

The handoff listed "delete the stale duplicate `keyword_search` rows (11 of 20)" as a small next step with no spend. The rows are the open item "Stale duplicate `keyword_search` rows" carried forward in docs/findings-slice24.md §3 through docs/findings-slice27.md §3.

Classification, said in chat as the first line of the first brainstorming reply: **bounded** — "This is a one-off delete in the dev database, with no code or migration change."

Facts read before the approaches (read-only queries on dev and the code):
- The brand had 20 rows. None was past `SEARCH_TTL_DAYS`: 10 were searched 2026-09-25 18:36 UTC (stale at 2026-10-02 18:36 UTC, 2026-10-03 00:06 IST), "men flip flops" 2026-09-29 11:23 UTC, 8 at 2026-09-29 13:10:34 UTC and "mens flip flops" 2026-09-30 09:27 UTC.
- By `keyword_key`, 7 of the 11 older rows share a key with a newer row ("kids shoe", "kids slipper", "men flip flops", "men shoe", "mens sandal", "women slipper", "womens sandal"); 4 have no newer row ("boys sandal", "boys shoe", "girls sandal", "men slipper").
- Only `run_products` reads the table; `DELETE /v1/brands/{id}/products` (`clear`) deletes a brand's rows with its products.

## Approaches (in chat, with a recommendation)

1. Delete all 11 now (recommended): one `DELETE` as `bsi_owner` in a block that checks exactly 11 rows go; print the table before and after; a dated note in docs/findings-slice27.md.
2. Delete only the 7 duplicates, keeping the 4 old spellings.
3. Do nothing; the rows go stale on 2026-10-02 and are never read again.

The user chose option 1.

Correction to the approaches message (2026-10-01): it said option 2's 4 kept rows "could still be reused until tomorrow", and a later message said a new run "could still reuse" the 11. Both were wrong: none of the 11 could be seeded or reused, because each failed `_current` (the 10 from 2026-09-25 had the old query wording; "men flip flops" had no `parse` key) and "men shoe" also held an error. docs/superpowers/specs/2026-09-30-slice24-keyword-cache-key-design.md §3 Dev re-check had recorded this. After the process audit the choice was asked again with the corrected fact, and the user confirmed option 1.

Correction to the approaches message and the re-ask (2026-10-01): both gave one stale time for all 11 rows ("searched on 2026-09-25 at 18:36 UTC", "would have gone stale on 2026-10-02"). That holds for 10 of them; "men flip flops", searched 2026-09-29 11:23 UTC, would have gone stale at 2026-10-06 11:23 UTC.

## Design

- A `DO` block run as `bsi_owner` (which bypasses RLS) deletes the brand's rows whose keyword is one of the 11, raises unless `ROW_COUNT` is 11, and so rolls back on any other count.
- No code, migration or test change.
- A dated update under the open item in docs/findings-slice27.md §3; the open item stays open because the code still leaves old spellings behind.

## Result

Observed: `NOTICE: deleted 11 rows`; 9 rows remain (the 8 current first keywords and "navy flip flops", which no product uses). *Inferred* from the code: no run's result or cost changed, since none of the 11 could be read by a run.

## Rulings

- **R1: the first review's minor points 1 to 4 were applied.** Decided: reword the findings note (the reason for the age, "men shoe" held an error, the exact 13:10:34 cutoff, both time zones). Found by the docs review of 6a6b808. Why: each made the note more exact at no cost. Cost if wrong: none beyond one more re-review. Named in chat when made.
- **R2: the first review's minor point 5 was left unapplied.** Decided: leave the pre-existing "nothing deletes them" wording in docs/findings-slice24.md alone, as outside this change. Found by the docs review of 6a6b808. Why: it predates this change. Cost if wrong: an inaccurate sentence stays. Named in chat when made; the user then overrode it ("include the slice 24 correction too").
- **R3: the correction note went into docs/findings-slice24.md and docs/findings-slice27.md only.** Decided: the copies of the open item in docs/findings-slice25.md and docs/findings-slice26.md are past snapshots and stay unchanged. Found by the controller when applying the user's request. Why: slice 27's copy is where the open item lives now. Cost if wrong: two older files keep the imprecise wording. Named in chat when made.
- **R4: the third review's two minor points were applied.** Decided: past tense for the deleted rows, and the spec section name "§3 Dev re-check". Found by the re-review of 192a1d8 and afc15b1. Why: wording only. Cost if wrong: none. Named in chat when made.
- **R5: no spec was written before the change.** Decided: take the bounded path (design in chat, no spec file) for a data-only change. Found by the controller at classification. Why: no code changed. Cost if wrong: the user's rule is a spec even for small changes; this file was written after the fact. Not named as a ruling when made; named at the process audit.
- **R6: the findings note describes the deleted rows by a timestamp cutoff.** Decided: "the 11 rows searched before 2026-09-29 13:10:34 UTC", replacing the first draft's "rows no current product used", which was wrong ("navy flip flops" is also unused and was kept). Found by the controller checking `product.keyword` before commit. Why: the cutoff separates the 11 from the 9 exactly. Cost if wrong: a reader misidentifies the deleted rows. Not named when made; named at the process audit.
- **R7: the note says "navy flip flops" is kept though no product uses it.** Decided: add that line. Found by the controller checking `product.keyword`. Why: it corrects the chat claim that the 9 kept rows were the ones current products use. Cost if wrong: none. Not named when made; named at the process audit.
- **R8: the re-review's Important finding was fixed.** Decided: afc15b1 replaced "the run-start seed could still load the valid ones" with "none could be seeded or reused", citing the slice 24 spec. Found by the re-review of 41f2235. Why: the text was wrong, and R1's wording had introduced it. Cost if wrong: none. Not named when made; named at the process audit.
- **R9: the user's "option 1, delete all 11" was taken as the go-ahead for the dev write.** Decided: run the delete on that reply. Found by the controller. Why: the approaches message said the answer would also be the go-ahead. Cost if wrong: an unapproved dev write. Said in chat, but not named as a ruling until the process audit.
- **R10: this spec, the findings link and the README row go on the same branch, `keyword-search-cleanup`.** Decided: add them to the open branch rather than a new one. Found by the controller at the process audit. Why: the fixes belong to the same change. Cost if wrong: none. Named in chat when made.
- **R11: the spec review's two minor points were applied.** Decided: correct the one stale time given for all 11 rows, and give R10 the "Decided / Found by" form. Found by the review of b53150c. Why: one was a factual error, the other a format gap. Cost if wrong: none. Named in chat when made.
- **R12: the spec re-review's minor point was applied.** Decided: remove the blank line between R10 and R11. Found by the re-review of 28bef34. Why: it split the Rulings list. Cost if wrong: none. Named in chat when made.
- **R13: the quoted rulings in docs/findings-slice27.md got a lead-in.** Decided: say they are numbered separately from slice 27's own R1 and R2, and that "this file" and "this spec" in them mean this spec; the copy is kept word for word. Found by the review of e25bdb9. Why: two R1s and two R2s in one findings file were ambiguous, and "this file" read as the findings file. Cost if wrong: none. Named in chat when made.

## Out of scope

- Any code change so runs delete or skip old spellings on their own.
- The copies of the open item in docs/findings-slice25.md and docs/findings-slice26.md (R3).
