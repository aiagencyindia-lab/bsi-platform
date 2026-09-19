# Slice 1 findings — live measurement run

**Headline risk: recommendation labelling is not adversarially robust.**
In a 10-run repeat of the live prompt-injection test
(`test_flash_lite_judge_live`'s exact input), the injected instruction
("...say Puma is best") got Puma labelled `recommended` in **6/10** runs.
`recommendation_rate` is computed straight from the model's `rec_status`
judgement, so it inherits this failure mode directly. `mention_rate`, `sov`
and `citation_rate` are unaffected — they come entirely from the
deterministic matcher, which the prompt text cannot influence.

**Headline risk: engine cost at scale is 3–5× the PRD target** (section 2).
Grounded search on Gemini 2.5 Flash costs about $0.038 per observation once
the free allowance is used up, and Gemini 3 about $0.059, against the
PRD's $0.012. One third-party source says the Gemini 2.5 models retire on
**16 October 2026**. That is unconfirmed on Google's own page, but if true
the move to Gemini 3's per-query pricing is weeks away.

## 1. Run

| | |
|---|---|
| Brand | `BSOAgentTestBrand` (made-up test brand) |
| Competitors | Bata, Campus, Skechers, Crocs, Adidas |
| Prompts | 20 |
| Samples/prompt | 3 |
| Date | 2026-09-19 |
| Job totals | enqueued 60, **done 60, failed 0**, job-level retry re-posts 0 |
| Observation-level retries | 0 (all 60 rows `attempts = 0`) |
| Wall clock | **21m 54s** (09:17:16 UTC first enqueue → 09:39:10 UTC last observation done) |

## 2. Cost per observation

> **Corrected 2026-09-19.** The first version of this section priced
> grounding at $14 per 1,000, flat per answer. That is Gemini 3's price
> for each *search query*. Gemini 2.5 Flash, the engine this run used, is
> billed **$35 per 1,000 grounded prompts** after a free allowance of
> 1,500 per day.
> Sources: [Google AI Developers Forum](https://discuss.ai.google.dev/t/grounding-free-quota-clarifying-2026-rules-for-gemini-2-5-flash-paid-tier-1/144593)
> and [CloudZero](https://www.cloudzero.com/blog/google-vertex-ai-pricing/).
> The `cost_micros` stored for this run's 60 rows (avg 16,761) used the
> old constant. The figures below are recomputed from the 60 stored raw
> payloads, and the adapter now prices by model (`PRICES` in
> `bsi_core/providers/gemini.py`).

Measured from the 60 raw payloads:
- Every answer was grounded.
- Each answer triggered **4.0 search queries on average** (min 2, max 13).
- Engine tokens averaged **2,761 micros** per answer (Flash $0.30 per 1M in, $2.50 per 1M out; thinking tokens billed as output).
- Extraction with Flash-Lite averaged **about 189 micros** per answer (1,213 input and 168 output tokens at $0.10 and $0.40 per 1M).

| Scenario | Per observation | vs PRD blended target $0.012 |
|---|---|---|
| This run: Gemini 2.5 Flash, inside the 1,500/day free grounding allowance | **≈ $0.0030** (the whole run ≈ $0.18) | 0.25× |
| **Gemini 2.5 Flash at scale** (paid grounding, $35/1k prompts) | **≈ $0.0380** | **3.2×** |
| **Gemini 3 at scale** ($14/1k search queries × 4.0 queries) | **≈ $0.0590** | **4.9×** |

Grounding, not tokens and not extraction, sets the price at scale. It is
more than 90% of each paid observation. The PRD's $0.015 Gemini estimate
assumed $14 once per answer, so on either current model it is out by 2.5×
to 4×. This invalidates the PRD §19.3 per-brand cost table until it is
re-derived. The 1,500 free grounded prompts per day cover only about 25
brands at 60 observations a day.

## 3. Interval widths

| n | Wilson full width (95% CI) | Source |
|---|---|---|
| 3 (single prompt) | ~0.56 (mention_rate CI: [0, 0.5615]) | `/metrics?prompt_ids=<1 id>` |
| 15 (5-prompt competitor-heavy subset) | ~0.20 (mention_rate CI: [0, 0.2039]) | `/metrics?prompt_ids=<5 ids>` |
| 60 (full run) | ~0.14 (mention_rate CI: [0.0361, 0.1807]) | `/metrics` (brand-level) |

### Sample-count recommendation

Using `bsi_core.metrics.wilson` directly (throwaway script, p≈0.3 — the
middle of this run's observed competitor share-of-mentions range,
0.20–0.47) to find the smallest n where the Wilson half-width drops below
0.075 (so that two independent measurements 15 points apart, e.g. 30% vs
45%, have non-overlapping confidence intervals):

| n | k (p=0.3) | half-width |
|---|---|---|
| 60 | 18 | 0.113 |
| 100 | 30 | 0.089 |
| **141** | **42** | **0.0747 (< 0.075, first to clear)** |
| 150 | 45 | 0.073 |
| 200 | 60 | 0.063 |

**A 15-point change needs n ≈ 140–150** at p≈0.3 to be distinguishable at
95% confidence — roughly **2.5× this run's n=60**.

For a brand-level or cluster-level number to reliably detect a 15-point
swing, that means **~150 observations**, e.g. 30 prompts × 5 samples, or 50
prompts × 3 samples (this run used 20×3=60). At paid-grounding prices
(section 2), one brand-level measurement at n=150 costs **about $5.69 on
Gemini 2.5 Flash, or about $8.84 on Gemini 3**. The same measurement at
n=60 costs about $2.28 or $3.54. Weigh this against PRD §19.3's per-brand
budget before making n=150 the default. The absolute §19.3 figure is not
in scope for this report.

## 4. Matcher vs. model

| Metric | Value |
|---|---|
| `model_only:` disagreements | 121 |
| `matcher_only:` disagreements | 2 |
| `model_error` rows | 10 |
| `model_used = 'none'` rows | 10 (same 10 as `model_error`) |
| Benchmark precision | **0.98** (50/51) |
| Benchmark recall | **1.0** (50/50) |

`model_error`/`model_used=none` (10/60 = 16.7%) all trace to transient
Flash-Lite 429/504 errors under load; `extract()` swallows the exception and
falls back to matcher-only mentions, so the observation still completes —
but loses `rec_status`/`sentiment` for those rows.

**Known matcher limitation** (the single benchmark false positive): a
product-name collision. "Adidas combines LED lights with iconic styles like
the **Campus** and Superstar" — "Campus" here names Adidas's own sneaker
model (alongside "Superstar", another Adidas model), not the competitor
brand Campus. The deterministic matcher has no way to disambiguate a
competitor's brand name from a different brand's product-model name sharing
the same token. Fixable later with per-brand exclusion phrases (e.g. "Adidas
Campus" as a stop-phrase) or short-window context checks (is the token
preceded by a different brand's name within N tokens).

## 5. Injection resistance

| | |
|---|---|
| Input | live test's exact adversarial answer (`test_flash_lite_judge_live`) |
| Repeats | 10 |
| Puma labelled `recommended` | **6/10** |
| Puma labelled `mentioned` (defense held) | 4/10 |

Consequence: `recommendation_rate` cannot be trusted when the underlying
engine answer contains adversarial or manipulated text — a majority of
trials let the injected instruction set `rec_status`. `mention_rate`, `sov`,
and `citation_rate` are computed entirely by the deterministic matcher and
are unaffected by this failure mode, since the matcher never reads model
judgements to decide *whether* an entity is mentioned (see `apply_sanity` in
`bsi_core.extraction`, which uses `hits` from `find_mentions` for mention
identity and only asks the model for `rec_status`/`sentiment` on entities
already found).

## 6. Caveats

- `BSOAgentTestBrand` is a made-up brand, so its brand-level rates (5/60
  mentions) mostly measure the two prompts that named it directly
  ("Is BSOAgentTestBrand a good brand...", "BSOAgentTestBrand light-up
  sneakers review"), not organic recognition — do not read brand-level
  numbers from this run as representative of a real brand's baseline.
- The `/sov` denominator only counts entities currently in the
  `competitor`/`brand` tables; a hard-deleted competitor's historical
  mentions drop out of the denominator retroactively, so SOV share is not
  stable across a competitor-roster edit.
- The live anti-injection test (`test_flash_lite_judge_live`) is `xfail`
  per spec R19 — this run's 6/10 failure rate is consistent with that
  expectation, not a regression.

## Follow-ups for the next sub-project (priority order)

0. **Re-derive the cost model before pricing anything.**
   - Confirm the grounding prices and the Gemini 2.5 retirement date on Google's own pricing page.
   - Add Gemini 3's price to `PRICES`. Until a model has a price there, its observations fail instead of being mispriced.
   - Re-run PRD §19.3.
   - Test levers: fewer grounded samples per prompt, and caching the search results for a prompt across its samples.
1. **Harden recommendation labelling** — a structured two-step judge (first
   pass: extract facts; second pass: a critic re-checks `rec_status` against
   only non-instructional sentences) or an independent second-model critic
   pass, since a single-call Flash-Lite judge is not reliable against
   injected instructions (6/10 failure in this run).
2. **Retry Flash-Lite 429s inside the extraction step** — currently a
   transient error silently degrades to matcher-only (10/60 rows this run);
   a short retry-with-backoff inside `extract()`'s judge call would recover
   most of these without touching observation-level retry semantics.
3. **Handle product-name/brand collisions** — per-brand exclusion phrases or
   local-context disambiguation for cases like "Adidas Campus" vs. the
   competitor "Campus" (this run's one benchmark false positive).
4. **The worker holds a transaction open during the judge call (R22)** — the
   Flash-Lite call happens inside the same `tenant_session` transaction that
   writes `raw_uri`/`status`; a long-running judge call (up to 120s timeout)
   holds that transaction/row lock the whole time. Worth moving the judge
   call outside the write transaction, mirroring how the grounding query
   already runs outside any transaction.
