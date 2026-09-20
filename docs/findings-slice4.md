# Slice 4 findings: prompt intelligence and the brand wizard

Date: 2026-09-20. Branch `slice4-prompt-intelligence`. Sources: the
step-0 probe (`scripts/probe_embed.py`, raw output committed at
`eval/results/probe_slice4.json`), the spend ledger, and the dev
database.

## 1. Step-0 probe (2026-09-20, $0.19)

### Embedding model

`gemini-embedding-001` works in `GOOGLE_CLOUD_LOCATION=global` on the
first try, so no separate client or location is needed.

| Property | Result |
|---|---|
| Dimensions | 768, as requested via `output_dimensionality` |
| Task type | `SEMANTIC_SIMILARITY` accepted |
| **Batching** | **Accepted 3 texts in one call** and returned 3 vectors |
| Latency | 3.6 s for a 3-text call |
| Billing fields | per-embedding `statistics.token_count`, plus `metadata.billable_character_count` (79 for 19 words) |
| Cost | 711 tokens for 60 prompts, so a 50-prompt job is a fraction of a cent |

Sanity check on the threshold: "best running shoes for kids in India"
against "top shoes for children who run" scores **0.9324**; against "how
do I clean white sneakers" it scores 0.7265. A reworded duplicate does
land above 0.92, and an unrelated prompt is far below.

### Generation

One call, temperature 1.0, asking for 60 prompts for the slice-1 test
brand in kids footwear:

| Measure | Result |
|---|---|
| Returned | 60 of 60 |
| Time | **9.35 s** (the PRD allows 90 s for 50) |
| Cost | 6,437 micros ($0.0064) |
| Exact duplicates | 0 |
| Intents used | 9 of 10 (transactional 6, informational 12, recommendation 11, comparison 7, problem_based 7, geographic 6, alternative 4, persona_specific 4, industry_specific 3) |
| Topics used | **7**, within the instructed maximum of 8: best brands, comfort issues, comparison, school shoes, sizing guide, sports shoes, toddler shoes |

The instruction to reuse a small topic vocabulary held, which is what
keeps (intent, topic) groups from fragmenting.

### Similarity distribution (1,770 pairs from the 60 generated prompts)

| Statistic | Value |
|---|---|
| min | 0.7078 |
| median | 0.8147 |
| p90 | 0.8614 |
| p99 | 0.9001 |
| max | 0.9518 |

| Threshold | Pairs flagged | Share |
|---|---|---|
| ≥ 0.88 | 86 | 4.9% |
| ≥ 0.90 | 17 | 1.0% |
| **≥ 0.92** | **5** | **0.3%** |
| ≥ 0.95 | 1 | 0.1% |

**This model's similarity floor is high**: two unrelated prompts in the
same category sit around 0.81. The PRD's 0.92 is therefore roughly the
99.7th percentile here, not a middling cut.

The five pairs at or above 0.92:

| Similarity | Pair | Really a duplicate? |
|---|---|---|
| 0.9518 | "best kids footwear brands in India" / "best arch support in India" | No |
| 0.9473 | "best kids footwear brands" / "good home-grown Indian brands" | No |
| 0.9398 | "best kids footwear brands" / "best orthotic kids footwear brands" | No |
| 0.9398 | "Adidas vs Skechers durability" / "Skechers vs Adidas cushioning" | Borderline |
| 0.9265 | "best arch support" / "best orthotic brands" | Yes |

So 0.92 costs a few false positives inside one batch. It is still the
right cut, because the case it must catch — the **same prompt
regenerated on a later run** — scores far higher (the reworded sanity
pair is 0.9324, and identical text is 1.0). Raising the cut to 0.95
would miss that reworded pair, which is the whole point of the check.

**Decision (user, 2026-09-20): keep 0.92.** It is the PRD's number, it
catches the reworded repeat, and erring toward fewer prompts also errs
toward lower spend. It is a constant in `suggest.py`, not a setting; if
the embedding model ever changes, re-run this probe before trusting it.

### Competitor suggestion

Three grounded answers, parsed and merged. One clear winner and a long
tail:

| Evidence | Suggestion |
|---|---|
| 3/3 | Aretto (wearetto.com) |
| 2/3 | Campus Activewear, Skechers Kids, Puma Kids |
| 1/3 | 18 more |

**Defect found:** the tail is mostly the same companies under different
names. "Bata India (Bubblegummers)", "Bata India" and "Bubblegummers"
each scored 1/3, and all three resolve to `bata.com`; the same happened
for Liberty, Relaxo, Crocs, Skechers, Puma, Campus and FirstCry. The
probe merged on the normalized **name** only. Merging on the domain
first would have turned those into 2/3 and 3/3 signals.

**Carried into the build:** `merge_competitors` keys on the normalized
domain when one is present, and only falls back to the name. Without
that, evidence counts are meaningless and the ranking is noise.

### Corrections to the plan from the probe

1. **Embeddings are batched**, not one call per text. The plan assumed
   the SDK would refuse a list; it did not.
2. **Competitor merge keys on domain first**, as above.
3. `EMBED_PRICES` is keyed on `gemini-embedding-001`; the token counts
   the response carries make the cost exact rather than estimated.

## 2. Spend

The probe cost $0.19 of its $0.25 allowance. The slice-wide ledger plus
database total stands at $7.13 against the $15 cap.
