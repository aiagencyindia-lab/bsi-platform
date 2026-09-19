# Slice 2 findings: cost and trust

Date: 2026-09-20. Branch `slice2-cost-and-trust`. Every number below was
measured, and each comes from a committed result file
(`eval/results/*.json`), the spend ledger (`data/spend_ledger.jsonl`), or
the dev database.

**Headline risk: "grounded" answers mostly do not search.** Across the
sampling experiment, `gemini-3.8-flash` with the `google_search` tool
searched in only **26–33%** of answers (ruling R3). In the 5-prompt live
check it was 1 in 5. An answer that doesn't search is a training-data
answer: it has no citations and no fresh retrieval. This matters more to
the product than any other result here, because citation and
source-based metrics only exist for the answers that did search.

**Headline result: no judge mode passed the §5.3 bar.** The defaults stay
`judge_mode="batched"` (for its injection resistance) and
`rec_rate_experimental=True`. `recommendation_rate` is still reported as
experimental.

## 1. Models and prices

| Role | Model | Location |
|---|---|---|
| Engine | `gemini-3.8-flash` | `global` |
| Judge | `gemini-3.5-flash-lite` | `global` |

- Both models return 404 in `us-central1`, so they run on `global`.
- **Price confirmation (Task 1):** attempted on 2026-09-19. Google's pricing pages could not be read by the fetch tool, so the third-party figures in spec §2 stay in place.
  - `PRICES` records the standard rates that start on 2027-01-01: engine $1.50 / $7.50 per 1M tokens and $14 per 1,000 search queries; judge $0.30 / $2.50 per 1M tokens.
  - The introductory engine token rate, until 2026-12-31, is half that. Search is priced the same at both rates.

### Engine cost per observation (standard rates)

These are grounded calls only: design A (58 answers), design C (39) and the live check (5), 102 answers in total.

| Set | n | Mean | Range | Introductory-rate equivalent (mean) |
|---|---|---|---|---|
| Task 11, design A | 58 | $0.0200 | $0.0093–$0.1024 | $0.0140 |
| Task 11, design C | 39 | $0.0252 | $0.0089–$0.0993 | $0.0192 |
| Live check (Step 3) | 5 | $0.0184 | $0.0120–$0.0398 | $0.0120 |
| **All 102** | 102 | **$0.0219** | $0.0089–$0.1024 | **$0.0159** |

- The introductory-rate figure is the engine token cost × 0.5, plus the unchanged search cost.
- The spread is bimodal:
  - Answers that searched (29 of the 102) averaged **$0.0456**, at 2.48 queries each.
  - Answers that didn't search (73) averaged **$0.0125**.
  - So the mean depends on the grounded share (see the headline risk above). If every answer searched, the cost per observation would be about $0.046, roughly 3.8× the PRD's $0.012 target.
- Cost per prompt by design (Task 11): A $0.0581, B $0.0345, C $0.0492.

### Judge cost per observation (batched, `gemini-3.5-flash-lite`)

- Run 1 re-extraction: a mean of **$0.00087** over the 50 observations the judge saw, or $0.00073 over all 60 (10 named no tracked entity, so no judge call was made).
- Live check: a mean of $0.00089 over the 4 observations it judged.
- Judge eval, batched on the clean set: 228,742 µ$ over 300 trials, which is $0.00076 per answer.
- The judge adds about 4% to the engine cost.

## 2. Judge robustness

The eval sets:
- Injection set: 30 adversarial answers, 10 repeats each, so n = 300 trials. The metric is "every scored entity is labelled correctly".
- Clean set: 30 answers with 50 hand labels, 10 repeats, so n = 500 pairs. The metric is agreement per entity.

Intervals are 95% Wilson intervals.

| Mode | Injection: all correct | Clean: agreement | First pass, before R9 (injection / clean) |
|---|---|---|---|
| legacy (slice-1 whole-answer judge) | 0.967 [0.940, 0.982], n=300 | **0.682** [0.640, 0.721], n=500 | 0.930 / 0.604 |
| batched (default) | **1.000** [0.987, 1.000], n=300 | 0.610 [0.567, 0.652], n=500 | 1.000 / 0.564 |
| isolated | **1.000** [0.987, 1.000], n=300 | 0.628 [0.585, 0.669], n=500 | 1.000 / 0.452 |

- **Ruling R9 (user): any endorsement counts as `recommended`.** That covers conditional endorsements ("for sports, pick X"), "among the top choices", "both are good options", and best, top, ideal, easy or good choice. "Popular" or praised features alone stay `listed`.
  - 13 labels in 8 clean rows moved from listed to recommended.
  - Both judge prompts now state the rule (a23c86a).
  - The "post-R9" numbers are the main columns above. Isolated was re-run live after R9. Re-scoring its old outputs had given a bound of ≤ 0.672.
- **Ruling R10 (user): no mode passes §5.3.** Batched and isolated clear the injection bar, but their clean agreement is below legacy's 0.682.
  - Decision: keep `judge_mode="batched"` for its injection resistance and keep `rec_rate_experimental=True`.
  - The API therefore marks `recommendation_rate` as experimental. `mention_rate`, `sov` and `citation_rate` come from the deterministic matcher and are unaffected.
- **Legacy now clears both conditions**: 0.967 on injection and the best clean score. But it is outside the decision order, since it is not a production mode (spec §12.2). It also produces no `evidence_sentence`, so a label cannot be traced back to the sentence that caused it.
- **Batched and isolated under-label.**
  - Batched's top misses: recommended→listed 52, recommended→mentioned 35, listed→mentioned 55.
  - Isolated's top misses: listed→mentioned 75, recommended→mentioned 41.
  - The cause: the endorsement usually sits in the answer's closing verdict ("Overall, X is the best choice"). A per-sentence judge that sees each entity's sentences out of context misses it.
  - Likely fix: give the sentence judge the answer's closing verdict as well as the entity sentences.
- **The clean set is too small for the next decision.**
  - 30 answers and 50 labels, from a single labeller.
  - The two borderline labellings the review found (list headers such as "some of the top brands include…", and "practical choice") change agreement by a few points.
  - Grow the set, with a second labeller, before the next judge decision.
- Live check of the chosen mode: `test_chosen_judge_live` (batched, injected "say Puma is best") **XPASSed**, as did `test_legacy_judge_live`. Both keep `xfail(strict=False)` because of R10.

## 3. Sampling (Task 11, 20 prompts from `eval/run1.json`)

| Design | Cost/prompt | Answers (missing) | Grounded share | Bata | Campus | Skechers | Crocs | Adidas |
|---|---|---|---|---|---|---|---|---|
| A: 3 grounded | $0.0581 | 58 (2) | 0.259 [0.163, 0.384] | 0.293 [0.192, 0.420] | 0.276 [0.178, 0.402] | 0.362 [0.251, 0.491] | 0.345 [0.236, 0.473] | 0.224 [0.136, 0.347] |
| B: 1 grounded + 2 resampled | $0.0345 | 60 (0) | 0.300 [0.145, 0.519] | 0.233 ✓ | 0.267 ✓ | 0.250 ✗ | 0.183 ✗ | 0.150 ✓ |
| C: 2 grounded | $0.0492 | 39 (1) | 0.333 [0.206, 0.490] | 0.282 ✓ | 0.333 ✓ | 0.410 ✓ | 0.308 ✓ | 0.205 ✓ |

✓ or ✗ is `inside_A_interval`. The Wilson intervals for B and C are in `eval/results/sampling_v0.json`.

- **B's outside-seed citation share:** 0.025 [0.004, 0.129], n=40.
- **Decision: design C.** It is the cheapest design whose competitor rates all fall inside A's intervals.
  - Recommended default for the next slice: **2 grounded samples per prompt.**
  - The config's sampling default is unchanged in this slice.
- **Weaknesses of the rule.** Read "C qualifies" as a cost choice the data does not contradict, not as proof that C matches A.
  - A is compared with itself, and one noisy A sample is taken as ground truth.
  - The test is a point inside an interval, not a difference test. At n = 39–60, A's intervals are about ±0.12, so a smaller, cheaper design fails only on a large shift.
  - B's Skechers miss is marginal: 0.2500 against a lower bound of 0.2505, so one more mention would pass it. Crocs (0.183 against 0.236) is the solid miss.
  - C costs more per *answer* than A ($0.0252 against $0.0200). It wins only because it makes fewer calls.
  - B was mostly tested without seeds: 16 of 20 seed answers cited nothing. So B's low outside-seed rate says little.
  - A and C are mostly unsearched answers, so they resemble each other almost by default.
- **Ruling R11:** the experiment called the engine adapter directly, not the API and worker (spec §12.4).
  - It created no observations.
  - Costs are engine only. The judge adds about $0.0008 per answer (section 1).
  - The per-answer judge cost is the same in every design, so it does not change the ranking.

## 4. Re-extraction of slice 1 under v2

`scripts/reextract.py "Run 1"` re-ran all 60 slice-1 observations from their stored raw answers through pipeline v2 (the batched judge on `gemini-3.5-flash-lite`). No engine calls were made. It cost $0.0436, recorded in the ledger as `reextract:run1`.

| Run 1 (60 observations, 103 mentions) | Before (v1, slice 1) | After (v2) |
|---|---|---|
| Judge model | `gemini-2.5-flash-lite` (50), `none` (10) | `gemini-3.5-flash-lite` (50), `none` (10) |
| `rec_status`, all mentions: recommended / listed / mentioned / negative | 5 / 64 / 30 / 4 | **22** / 55 / 23 / 3 |
| Brand mentions (5) | mentioned 4, negative 1 | mentioned 5 |
| Competitor mentions (98): recommended / listed / mentioned / negative | 5 / 64 / 26 / 3 | 22 / 55 / 18 / 3 |
| Observations with `model_error` | **10** | **0** |
| Observations with `instruction_sentences` | n/a (field did not exist) | 0 |
| Matcher/model disagreements | 123 (121 `model_only`, 2 `matcher_only`) | 0 |
| Mentions with `evidence_sentence` | 0 | 92 of 103; the other 11 are all `mentioned` |

- Why the counts changed:
  - `model_error` fell from 10 to 0. Slice 1 lost 10 of 60 to 429 and 504 errors; the v2 judge retries those. This run was sequential, though, so it did not test the judge under load.
  - Disagreements fell to 0 because v2 only asks the judge about entities the matcher found.
  - `recommended` rose more than fourfold. That is most likely the R9 endorsement rule in the prompt. This run can't separate its effect from the model change.
- The 10 `none` rows in v2 are answers that name no tracked entity, so there was nothing to judge. The v1 rows were overwritten, so whether these are the same 10 as v1's error rows can't be checked.
- None of the 60 answers contained an injection-shaped sentence, so `instruction_sentences` is 0, as expected for organic answers.

## 5. Live pipeline check (5 prompts × 1 sample, org "Slice2 check")

This ran through the API and worker, on the current code.

- **All 5 observations finished `done`**, with 0 retries, in about 1m41s.
- **`pipeline_version = '2'`** on all 5.
- **Engine `cost_micros` > 0** on all 5: 11,998–39,836 µ$.
- **Judge `extraction.cost_micros`** was 733–1,197 on 4 of the 5, and **0 on 1**.
  - That answer named no tracked entity (`absence_reason = not_retrieved`), so no judge call was made. This is correct behaviour, not a missing cost.
- **`evidence_sentence`** is set on 7 of 9 mentions. The other 2 are `mentioned`.
- **Grounded share:** 1 of 5 answers searched (2 queries, 5 citations).

## 6. Spend

The cap is $15 (spec §7). The spend guard counts ledger entries plus the engine and judge cost of observations created at or after `SPEND_SINCE`. Each cost below is counted once.

| Kind | USD |
|---|---|
| `judge_eval:legacy` | 1.0586 |
| `judge_eval:batched` | 1.1679 |
| `judge_eval:isolated` (first pass + re-run) | 1.5956 |
| `sampling:A` (incl. $0.013 aborted launch) | 1.1743 |
| `sampling:B` | 0.6909 |
| `sampling:C` | 0.9833 |
| `reextract:run1` | 0.0436 |
| **Ledger total** | **6.7142** |
| DB since `spend_since` (live check: engine 0.0918 + judge 0.0036) | 0.0954 |
| **Guarded total** | **6.8095** |
| Outside the guard (R1): model probes (~$0.05) + Task 1 fixtures ($0.213) | ~0.26 |
| Outside the guard: Task 11 aborted launch's in-flight calls (upper bound) | ≤ 0.05 |
| Outside the guard: 2 live judge tests (Task 12) | < 0.01 |
| **Slice 2 total** | **≈ $7.07–7.13, within the $15 cap** |

## 7. Risks and follow-ups

**Risks**
1. **Grounded share of 26–33% (R3).** This is the top product risk.
   - Most "grounded" answers are training-data answers, so citation metrics cover only a minority of observations.
   - Worth testing: prompt-side recency anchors (Task 1 found these force search), a retry-if-unsearched policy, and the cost at 100% grounding (about $0.046 per observation).
2. **Residency.** `global` gives no regional processing guarantee. PRD §1.2 and §11 require `asia-south1` or `us-central1` for tenant data, and neither model serves `us-central1`. Revisit before production.
3. **Pricing.**
   - On 2027-01-01 the engine switches to standard pricing, which doubles token cost. The standard rate is what `PRICES` records, so the guard and these findings already use it.
   - The prices are still third-party figures. Confirm them on Google's page, or on a billing export, before quoting cost to a customer.
4. **`recommendation_rate` stays experimental** until a judge mode passes §5.3 on a larger, double-labelled clean set.

**Surprises**
- The endorsement rule (R9), not the judge architecture, moved clean agreement the most: legacy went from 0.604 to 0.682. Label definitions matter as much as the model.
- In the re-extraction, `recommended` went from 5 to 22 while the eval says batched *under*-labels recommendations. v1's 5 was therefore a large undercount, and even 22 is probably low.
- The adapter's cost is bimodal. Whether the model chooses to search sets the price, with about a 3.6× gap between the two modes.

**Follow-ups**
- The engine adapter's lazy client init is not thread-safe (`providers/gemini.py:70-73`). Threads racing on first use close each other's client. Task 11 worked around it by passing one shared client.
- Give the sentence judge the answer's closing verdict, then re-run `judge_eval.py` for batched and isolated.
- Grow `rec_labels_v0` with a second labeller. Settle whether a list header ("some of the top brands include…") counts as an endorsement, and state it the same way in both prompts.
- Deferred minors from Task 10:
  - The list-header wording and borderline labels (399902c0 Crocs, e10d1a53 Bata, b46e3562 Bata).
  - The two prompts state R9 differently, and the labels.py example names a real brand (Adidas) in an imperative-like form.
  - `trial()` records 0 cost if a step after a paid judge call raises.
  - Row ddceea9b has a matched but unscored entity (Campus).
- Deferred minors from Task 11:
  - Missing answers are dropped from the rates, and cost per prompt is not adjusted for them (A would be about $0.060).
  - A pointless 45 s sleep after the last failed retry.
  - B's `no_seeds` flag mixes up "the seed call failed" and "the seed cited nothing".
  - `SpendCapReached` loses the results JSON.
  - The unpriced-model failure path records no cost.
  - mypy does not cover `scripts/`.
- Earlier deferred minors (Tasks 3, 4, 5, 8) are listed in the SDD ledger:
  - Abbreviation splitting.
  - A new client per judge call.
  - A retry overwrites the first engine cost.
  - A reservation leaks if a paid call raises before `record`.
