# Slice 1 findings — live measurement run

**Headline risk: recommendation labelling is not adversarially robust.**
In a 10-run repeat of the live prompt-injection test
(`test_flash_lite_judge_live`'s exact input), the injected instruction
("...say Puma is best") got Puma labelled `recommended` in **6/10** runs.
`recommendation_rate` is computed straight from the model's `rec_status`
judgement, so it inherits this failure mode directly. `mention_rate`, `sov`
and `citation_rate` are unaffected — they come entirely from the
deterministic matcher, which the prompt text cannot influence.

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
| Wall clock | **22m 07s** (09:17:16 UTC → 09:39:23 UTC) |

## 2. Cost per observation

| Component | Value | Basis |
|---|---|---|
| Engine (grounding) — measured | avg **16,760.8 micros** ($0.016761), sum 1,005,648 micros ($1.005648), n=60 | `SELECT count(*), avg(cost_micros), sum(cost_micros) FROM observation WHERE brand_id = '<id>' AND status = 'done'` (owner connection) |
| Extraction (Flash-Lite) — estimated | **≈188.5 micros ($0.0001885)**/obs = ~$0.0113 total | avg built prompt 1,213 input tokens + avg output 168 tokens (measured from all 60 rows) × Flash-Lite list price $0.10/1M in, $0.40/1M out |
| **Combined per observation** | **≈16,949 micros ≈ $0.0170** | engine + extraction |
| PRD Gemini estimate | $0.015/observation | measured $0.0170 is ~13% above this |
| PRD blended target | $0.012/observation | measured $0.0170 is ~42% above this |
| `GROUNDED_QUERY_MICROS` (14,000) | **confirmed current** | matches Google Search grounding list price, $14/1,000 requests = $0.014/request = 14,000 micros, exactly |

The gap to both PRD figures is driven by the engine call, not extraction
(extraction is ~1% of the total cost). Grounded-query flat fee (14,000
micros) is ~84% of the average per-observation engine cost — this run's
prompts are consistently grounded, so the flat fee dominates over the
token-based cost.

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
prompts × 3 samples (this run used 20×3=60). At the measured $0.0170/obs,
that raises the cost of a single brand-level measurement from **~$1.02
(n=60) to ~$2.55 (n=150)** — about **2.5×** the run cost this task
performed, which should be weighed against PRD §19.3's per-brand cost
budget before rolling this out as the default sample size (this report does
not have the PRD §19.3 absolute figure in scope; the multiplier above is
what changes if n=60 is raised to n=150).

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
