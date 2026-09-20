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

## 2. Which prompts discriminate — "Run 1", `GET /brands/{id}/prompts/metrics`

Queried live against the dev database for "Run 1" (brand
`BSOAgentTestBrand`, the slice-1 test brand, 20 prompts at n=3 samples
each — the same run behind `findings-slice1.md`):

| | |
|---|---|
| Prompts | 20 |
| Samples per prompt (`n`) | 3, for every prompt |
| Prompts with `separated: true` (brand's CI does not overlap its top rival's) | **0 of 20** |

Not one of the 20 prompts separates the brand from its top competitor at
95% confidence, at n=3. This is not a surprising result given
`findings-slice1.md` §3's own interval-width analysis of this exact run:
a single prompt's Wilson CI at n=3 spans about 0.56 wide (e.g.
`[0, 0.56]`), and `BSOAgentTestBrand`'s per-prompt mention rate is
usually 0 (it is a made-up brand most prompts do not name), so its CI is
`[0, 0.56]` against a rival's CI that is often `[0.44, 1.0]` at n=3 —
overlapping by construction unless the rival is mentioned in literally
every sample and the brand in none, which still leaves the two ranges
touching at their edges. Reaching separation at the per-prompt level
needs far more than n=3; `findings-slice1.md` put the brand-level
threshold at **n≈140–150** for a 15-point swing to be non-overlapping at
95% confidence, and per-prompt separation from a rival that is mentioned
far more often is an even harder bar. **Answer to the open question:**
at today's default sampling (3 per prompt), no prompt is a reliable
discriminator on its own; discrimination only shows up once results are
pooled across many prompts or samples are increased well past 3.

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
6. **The ops spend bar divides by the daily budget, which may be
   zero.** `apps/web/src/app/ops/page.tsx` computes
   `committed / o.budget_micros` and `o.spent_micros / o.budget_micros`
   directly; an org with no budget configured divides by zero rather
   than showing an explicit "no budget set" state.
7. **`api()` does not clear a stale cookie on 401.** `src/lib/api.ts`
   redirects to `/login` on a 401 but leaves the rejected `bsi_key`
   cookie in place, so the next request repeats the same failed
   round-trip before landing on the login page again.
