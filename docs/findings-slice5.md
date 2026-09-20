# Slice 5 findings: operator dashboard

Date: 2026-09-20. Branch `slice5-operator-dashboard`. Sources: Task 6's
backfill (`scripts/backfill_search_queries.py`) against the dev database
(`bsi`), a live query of `GET /brands/{id}/prompts/metrics` and
`GET /brands/{id}/labels/next` for org "Run 1", and a direct read of the
dev database's `rec_label` table. No existing rows were truncated or
modified; a fresh API key was minted owner-side for "Run 1" the same way
`tests/conftest.py`'s `make_org` does, to call the endpoints as that org.

## 1. The searched rate — one number, two very different populations

Task 6's backfill found **63 of 75** dev-database observations with a
known `search_queries` count actually ran at least one search query
(84%). `docs/findings-slice2.md` separately reports **26–33%**, from a
dedicated sampling experiment on `gemini-3.8-flash` designed to measure
exactly this. Those two numbers are not in tension and neither is "the"
platform rate — they describe different runs on different models:

| Org | Model | Rows with a known count | Rows that searched | Rate |
|---|---|---|---|---|
| Run 1 | `gemini-2.5-flash` | 60 | 60 | **100%** |
| Slice3 check | `gemini-3.8-flash` | 10 | 2 | 20% |
| Slice2 check | `gemini-3.8-flash` | 5 | 1 | 20% |

The 63/75 blend is dominated by "Run 1" — 60 of the 75 rows, all on
`gemini-2.5-flash`, all grounded. That matches `findings-slice1.md`'s
own measurement of that exact run ("every answer was grounded"): it is
the same 60 rows, re-measured. The remaining 15 rows, on
`gemini-3.8-flash`, searched only 3 times (20%) — in the same range as
slice 2's dedicated 26–33% figure.

**Correction to this task's brief:** the brief attributes the 26–33%
figure to `findings-slice1.md`. It does not appear there — slice 1's
live run had 100% grounding (a different model, `gemini-2.5-flash`,
which apparently searches far more readily than `gemini-3.8-flash`). The
26–33% figure is from `findings-slice2.md`'s sampling experiment on
`gemini-3.8-flash`, which is also where the closely related 1-in-5
figure for a small live check comes from.

**What this does and does not say.** The dev database has no runs that
mix models within one measurement, so it cannot say whether the gap is
model-driven, prompt-driven, or an artifact of how few rows exist per
model (10, 5, and 60 is not a controlled comparison). What it does say:
whichever model an org runs on changes the searched rate enormously —
20% vs. 100% is not noise — so **any platform-wide "searched rate" quoted
without naming the model is not a fact about the platform, it is a fact
about whichever run happened to be sampled.** Treat both 84% and 26–33%
as measurements of specific small runs, not platform constants.

## 2. Which prompts discriminate — measured, then tested

"Run 1" (brand `BSOAgentTestBrand`, 20 prompts, the run behind
`findings-slice1.md`) began this slice at n=3 samples per prompt with
**0 of 20** prompts separating the brand from its top rival at 95%
confidence. Read alone, that number invites the conclusion that
per-prompt discrimination needs sampling far beyond 3. **That
conclusion is wrong, and we tested it rather than reasoning about it.**

`samples_to_separate` projects, from each prompt's observed rates, the
sample size at which the two Wilson intervals would stop overlapping.
Before running anything it said:

| Samples needed | Prompts |
|---|---|
| 4 — one more than we had | **11** |
| 7 | 5 |
| 20 | 3 |
| never (rates identical) | 1 |

So more than half the table was a single observation short of a
conclusive answer, which "0 of 20" conceals entirely.

### The experiment

One extra sample per prompt, run live on 2026-09-21: 20 observations,
0 failures, **$0.7686** (engine $0.7513, judge $0.0173).

Run deliberately with `ENGINE_MODEL=gemini-2.5-flash` rather than the
configured `gemini-3.8-flash`. `prompt_metrics` pools every done
observation and `Filters` has no model filter, so adding samples from a
model that searches ~20% of the time (§1) to a population that searches
100% of the time would have conflated "one more sample" with "changed
model" and made the test meaningless.

**Result: the projection was exact.** 11 predicted, 11 separated, no
prompt separated that was not predicted to, and none predicted failed
to. Every prompt is now at n=4 and 11 of 20 are conclusive.

### How strong that validation actually is

Weaker than the clean hit rate suggests, and the same run shows why.
All 11 were extreme cases — brand 0/3, rival 3/3 — which stayed extreme
at 0/4 and 4/4. The projection assumes today's rates hold; for these it
held perfectly. The arithmetic is confirmed; the assumption got the
easiest test available.

The other nine measure the assumption properly, and it is shaky:

| Before (n=3) | After (n=4) | Projection |
|---|---|---|
| spread ±0.67, needs 7 | ±0.75, needs 7 | stable |
| spread −0.33, needs 20 | −0.50, needs **11** | nearly halved |
| spread −0.33, needs 20 | −0.25, needs **27** | rose by a third |

Only 12 of 20 prompts had an unchanged spread: **one observation moved
eight of them**, and where the gap is middling the projection swung by
up to nine samples on that single result.

**Answer to the open question.** At n=3 no prompt discriminates, but the
deficit is one sample for over half of them, not the large increase the
bare count implies. The projection is dependable where the gap is
extreme and noisy where it is not — which is exactly where an operator
most wants it, so it is labelled a projection in the UI and should not
be quoted as a plan without re-reading it after the next run.

## 3. Labels and judge agreement

Read directly from the dev database and via `GET /brands/{id}/labels/next`:

| | |
|---|---|
| `rec_label` rows in the dev database | **1** |
| Agreement (that org's queue) | **1/1 = 100%**, 95% CI **[0.21, 1.0]** |

This is a single hand label, made while building and testing the tool
in this slice — not a judge-accuracy result. State it plainly: **one
data point proves nothing about judge accuracy**, and the CI width
above (0.21 to 1.0 — essentially "somewhere between rarely right and
always right") is the honest way to say that. The labelling tool works
end to end (queue → label → agreement recompute, confirmed in
`tests/integration/test_api_labels.py`); measuring the judge is a
separate, not-yet-done exercise that needs dozens of labels at minimum,
and the 95% CI width above is exactly the tool telling you how many.

## 4. Known gaps

Carried from the plan and what the per-task reviews deferred:

1. **No locale picker.** `next_label`/prompt views still take a
   `locale_id` in the URL if you set it by hand, but there is no UI
   control to switch it (plan: "ponytail: no locale picker; a locale_id
   in the URL is still honoured").
2. **No sparklines.** The overview and prompt pages show point-in-time
   rates and deltas, not trend lines.
3. **`next_label` loads every mention of the brand to pick the next
   one and count `remaining`/`labelled`.** Fine at the volumes this
   slice runs (hundreds of mentions); past roughly 10,000 mentions this
   should move into SQL rather than pulling every row into Python
   (`apps/api/bsi_api/routers/labels.py`, marked with a `ponytail:`
   comment at the call site).
4. **Production error pages show a digest only.** `error.tsx` prints the
   actual message in dev; in a production build it shows just the
   digest Next.js assigns, with the real problem and request id in the
   server log — by design (Next strips server error messages from
   production builds), but it means an operator seeing an error page
   cannot self-diagnose without server log access.
5. **On-demand runs still have no budget check.** Slice 4 flagged this
   as its top known gap and it is still true here: nothing added in
   this slice puts a ceiling on `POST /brands/{id}/runs`.
6. **No trend history.** Every number here is a point-in-time read of
   the dev database. Nothing in this slice stores a daily series, so
   "how did the searched rate move last week" cannot be answered
   without re-querying raw observations by hand.

Two gaps listed when this document was first written have since been
closed, and are recorded here so the list is not read as still-open:
the ops spend bar dividing by a possibly-zero budget (now an explicit
zero-budget branch rendering a full meter), and `api()` leaving a
rejected `bsi_key` cookie in place on a 401 (now cleared by
`apps/web/src/middleware.ts` on `/login`).
