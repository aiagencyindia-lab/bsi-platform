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

## 2. Prompt generation eval (`scripts/prompt_eval.py`, $0.017)

Three unlike categories, 50 prompts asked for each, through the
production path (`build_prompt_request` → `judge.generate` at
temperature 1.0 → `clean_prompts` → `embed` → `dedupe`) with no database.
Raw output: `eval/results/prompt_gen_v0.json`.

| | kids footwear (IN) | B2B SaaS CRM (US) | D2C ayurvedic skincare (IN) |
|---|---|---|---|
| Asked (50 × 1.25 overshoot) | 63 | 63 | 63 |
| Returned | 63 | 63 | 63 |
| Rejected by `clean_prompts` | 0 | 0 | 0 |
| Generation | 8.56 s | 10.20 s | **78.16 s** |
| Embedding (63 texts, 1 call) | 24.52 s | 11.80 s | 17.69 s |
| Total | 33.08 s | 22.00 s | 95.85 s |
| Cost (generate + embed) | 4,968 | 7,160 | 4,749 micros |
| Near-duplicates dropped | 5 | 0 | 2 |
| **Near-duplicate rate** | **7.9%** | **0.0%** | **3.2%** |
| Post-dedupe | 58 | 63 | 61 |
| Would be written (capped at 50) | 50 | 50 | 50 |
| Intents used | 9 of 10 | **10 of 10** | 9 of 10 |
| Topics used | 8 | **10** | 6 |

Intent spread, from the same run:

- kids footwear: informational 8, commercial 8, transactional 8,
  comparison 8, alternative 8, recommendation 8, problem-based 8,
  industry-specific 4, persona-specific 3 (no geographic).
- CRM: informational 8, commercial 7, then 6 each of the other eight.
- skincare: 7 each of nine intents (no geographic).

Three observations that are facts rather than judgements:

1. **The "at most eight topics" instruction is soft.** The CRM set used
   ten, and one of them is the literal word `industry-specific`, which
   is an intent, not a topic. Groups still form; they just fragment a
   little more than the prompt asks for.
2. **Generation time is not stable.** The same call took 8.6 s and
   78.2 s on different categories. The 90-second bar in spec §8 has less
   headroom than the probe's 9.35 s suggested. A generation plus an
   embedding call reached 95.85 s end to end for the skincare brand.
3. **The `geographic` intent is rare** — it appeared in the live set
   (once) and in neither eval set that lacked a tenth intent.

### Pairwise similarity (1,953 pairs each)

| Statistic | kids footwear | CRM | skincare |
|---|---|---|---|
| min | 0.7222 | 0.6843 | 0.6908 |
| median | 0.8200 | 0.7987 | 0.8001 |
| p90 | 0.8673 | 0.8384 | 0.8454 |
| p99 | 0.9035 | 0.8788 | 0.8859 |
| max | 0.9570 | 0.9013 | 0.9323 |
| ≥ 0.85 | 373 (19.1%) | 117 (6.0%) | 158 (8.1%) |
| ≥ 0.88 | 105 (5.4%) | 17 (0.9%) | 32 (1.6%) |
| ≥ 0.90 | 27 (1.4%) | 1 (0.1%) | 8 (0.4%) |
| **≥ 0.92** | **5 (0.26%)** | **0** | **2 (0.10%)** |
| ≥ 0.95 | 1 (0.05%) | 0 | 0 |

This repeats the probe's shape (§1) on two further categories: the floor
sits near 0.80 and 0.92 is around the 99.7th percentile, not a middling
cut. The CRM set never reached it at all.

**Two different "duplicate rates" are reported above, and they are not
the same number.** The pair rate (0.26%) is how many of the 1,953 pairs
are flagged. The near-duplicate rate (7.9%) is how many *prompts* the
greedy keep-first pass dropped, which is higher because one crowded
cluster drops several prompts against a single kept one. Spec §8 asks
for "near-duplicates under 5% on the eval set"; on the prompt-level
reading, kids footwear is 7.9% and the other two are under.

Every pair that the threshold dropped, so the judgement can be made on
the text rather than the number:

| Sim | Kept | Dropped |
|---|---|---|
| 0.9570 | Waterproof footwear options for children during the monsoon | Top recommended waterproof footwear for kids during heavy rain |
| 0.9425 | Waterproof footwear options … (same kept prompt) | Waterproof synthetic boots versus rubber gumboots for kids |
| 0.9340 | Waterproof footwear options … (same kept prompt) | Order waterproof outdoor boots for children for the rainy season |
| 0.9295 | Affordable everyday footwear options for fast-growing children | Affordable alternatives to expensive imported orthotic shoes |
| 0.9247 | Compare Velcro strap sneakers versus lace-up shoes for kindergarten | Slip-on shoes versus lace shoes which is better for independent dressing |
| 0.9323 | Ayurvedic face oil versus modern hyaluronic acid serum | Ayurvedic anti-aging treatments vs retinol serums |
| 0.9213 | Regulations on labeling herbal skincare in the Indian market | Export standards for Indian herbal beauty formulations |

The nearest pair that was **kept**, in each set: 0.9199 (kids
footwear, two running-shoe prompts), 0.9013 (CRM, two
alternatives-to-Salesforce prompts), 0.9166 (skincare).

## 3. Live wizard check (2026-09-20, $0.201)

Org "Slice4 check" (`737ac6bc`), brand `6eb29bf2` ("BSOAgentTestBrand",
category "kids footwear", the `eval/run1.json` brand so the numbers line
up with §1). API and worker local; both stopped afterwards and confirmed
gone with `ps`.

| Spec §8 item | Result |
|---|---|
| Both jobs finish `done` with `cost_micros > 0` | competitors `e39c3f2d` done, 192,981 micros; prompts `82d342cb` done, 6,724 micros |
| ~50 prompts with intents, topics and embeddings | exactly 50 written, 50 intents, 50 topics, 50 embeddings of 768 dims, all `source='generated'`, `status='suggested'` |
| … in ≤ 90 s | **15.0 s** for the prompt job (claimed 11:52:23.7, finished 11:52:38.7) |
| Competitors carry evidence | 10 suggested, all with an evidence count: 7 at 3/3, 2 at 2/3, 1 at 1/3 |
| A second suggest in a later hour adds new prompts | 11:00 slot job vs a new 12:00 slot job `f7c754ef`; asked for 20, **wrote 16 new** (1,696 micros); brand now 66 prompts |
| Activating 50 shows `fits: false` at $2 | `{"brand": {"active_prompts": 50, "samples": 2, "runs_per_day": 1.0, "est_daily_usd": 5.0}, "org": {"est_daily_usd": 5.0}, "budget_usd": 2.0, "fits": false}` |
| … and `true` after `scripts/set_budget.py` | `set_budget.py "Slice4 check" 6.00` → `None -> 6.00`; same preview then `"budget_usd": 6.0, "fits": true` |
| A scheduled run then enqueues | daily schedule at 12:00 UTC; at 12:00:05 `run_due_schedules()` logged `schedule d9a0388d: enqueued:100` (50 prompts × 2 samples) |

**Stopped at enqueue, as instructed.** The 100 observations were never
executed: no worker loop was running when the schedule fired, the rows
were then deleted and the schedule removed, so nothing can drain them
into a ~$5 measurement run later.

### What the wall clock looked like, and why it is not the job time

The wizard posts both suggest calls at once, and one worker runs jobs
one at a time. The prompt job therefore sat queued for 124 s behind the
competitor job and only *appeared* to take 140 s end to end:

| Job | Queued | Claimed | Finished | Own duration |
|---|---|---|---|---|
| `suggest_competitors` | 11:50:19.0 | 11:50:20.0 | 11:52:23.7 | **123.7 s** |
| `suggest_prompts` | 11:50:19.0 | 11:52:23.7 | 11:52:38.7 | **15.0 s** |

Spec §8's 90 seconds is met by the job, not by the wizard's wall clock.
Competitor suggestion is the slow and expensive half — three grounded
answers plus three parses, 123.7 s and $0.193 against the prompt job's
15.0 s and $0.0067. A user watching a single-worker wizard waits for
both.

### The repeat-in-the-same-hour path

Re-running the wizard against the same brand inside the same UTC hour
returned the two finished jobs in 0.04 s with their costs unchanged and
did no work, as the Task-7 ruling says it should. **Any UI must word
this as "already suggested this hour", not as "queued".**

### The competitor list (evidence counts)

| Evidence | Suggestion |
|---|---|
| 3/3 | Bata India Limited (bata.com), Brainbees Solutions Limited (firstcry.com), Campus Activewear Limited (campusshoes.com), Crocs India (crocs.in), Liberty Shoes Limited (libertyshoesonline.com), Puma Sports India (in.puma.com), Relaxo Footwears Limited (relaxofootwear.com) |
| 2/3 | Khadim India Limited (khadims.com), Skechers Kids (skechers.in) |
| 1/3 | Metro Brands (metroshoes.com) |

The probe's defect is fixed in practice: the companies that the probe
saw split into three 1/3 rows each (Bata, Liberty, Relaxo, Crocs,
Skechers, Puma, Campus, FirstCry) now merge on the domain and come back
as single 3/3 or 2/3 rows. Seven clear signals and one straggler,
against the probe's one winner and an 18-row tail.

### The full generated set, for review

All 50, as `intent/topic` and text, in the order the wizard printed
them:

- `informational/sizing` — How do I measure my child's feet accurately at home?
- `informational/sizing` — What size shoe should I buy for a toddler growing fast?
- `informational/sizing` — How often should children's shoes be replaced?
- `informational/sizing` — Are there printable charts to check kids shoe sizes?
- `informational/sizing` — Why do kids need different shoe sizes for different brands?
- `informational/foot health` — What causes foot pain in growing children?
- `informational/foot health` — Do toddlers need arch support in their footwear?
- `informational/foot health` — Is it safe for kids to wear hand-me-down shoes?
- `informational/foot health` — How do flat feet affect children's walking and running?
- `informational/foot health` — What are signs that my child's shoes are too small?
- `commercial/school shoes` — Best breathable sneakers for active school kids
- `commercial/school shoes` — Durable black leather shoes for daily school uniform
- `commercial/school shoes` — Lightweight sports shoes for physical education class
- `commercial/school shoes` — Easy slip-on school shoes for young kindergarteners
- `commercial/school shoes` — Stain resistant white canvas shoes for school events
- `transactional/outdoor play` — Where can I buy waterproof rain boots for toddlers online?
- `transactional/outdoor play` — Order durable hiking sandals for kids with good grip
- `transactional/outdoor play` — Shop comfortable running shoes for kids with fast delivery
- `transactional/outdoor play` — Buy machine washable playground sneakers for boys
- `transactional/outdoor play` — Purchase light-up shoes for toddlers with free shipping
- `comparison/school shoes` — Compare Velcro straps versus traditional laces for kids shoes
- `comparison/school shoes` — Canvas shoes versus mesh sneakers for hot weather kids
- `comparison/school shoes` — Leather versus synthetic materials for durability in children's footwear
- `comparison/outdoor play` — Rubber soles versus foam soles for playground safety
- `comparison/outdoor play` — High-top versus low-top sneakers for ankle stability in kids
- `alternative/school shoes` — What are good alternatives to traditional laced sports shoes for toddlers?
- `alternative/school shoes` — Alternative options to heavy leather shoes for daily school wear
- `alternative/outdoor play` — Eco-friendly alternatives to plastic-based children's sneakers
- `alternative/outdoor play` — Open-toe sandal alternatives that still protect children's toes
- `alternative/outdoor play` — Lightweight alternatives to traditional winter boots for kids
- `recommendation/foot health` — Can you recommend comfortable shoes for children with wide feet?
- `recommendation/foot health` — Suggest top-rated orthopedic shoes for toddlers who overpronate
- `recommendation/outdoor play` — What are the most durable sneaker brands for rough playground use?
- `recommendation/school shoes` — Recommend easy-to-clean white sneakers for school uniforms
- `recommendation/foot health` — Which sandals offer the best support for children with flat feet?
- `problem-based/foot health` — My toddler keeps tripping over shoelaces what should I do?
- `problem-based/foot health` — How to stop children's canvas shoes from smelling bad quickly
- `problem-based/foot health` — What to do when kids shoes cause blisters on their heels
- `problem-based/school shoes` — How to clean muddy white school sneakers without ruining them
- `industry-specific/school shoes` — What safety standards apply to children's school footwear manufacturing?
- `industry-specific/foot health` — Are there non-toxic chemical regulations for kids shoe dyes in India?
- `industry-specific/foot health` — What ergonomic certifications matter most in children's footwear design?
- `industry-specific/school shoes` — How do shoe manufacturers test slip resistance for school floors?
- `industry-specific/outdoor play` — Sustainable material sourcing trends in the kids footwear market
- `persona-specific/sizing` — Best shoes for busy moms looking for quick slip-ons for toddlers
- `persona-specific/school shoes` — Durable school shoes recommended by teachers for active students
- `persona-specific/outdoor play` — Lightweight athletic footwear for young athletes in junior sports leagues
- `persona-specific/foot health` — Easy closure shoes for children with sensory sensitivities to tight fits
- `persona-specific/sizing` — Affordable sturdy footwear options for large families buying multiple pairs
- `geographic/outdoor play` — Where to buy breathable kids footwear in Mumbai during monsoon season

The clusters view over that set, which is what a reviewer would group
by: 21 (intent, topic) groups over 9 intents and 4 topics — sizing,
foot health, school shoes and outdoor play — the largest being
`informational/sizing`, `informational/foot health`,
`commercial/school shoes` and `transactional/outdoor play` at 5 each.

## 4. Spend

| | Micros | USD |
|---|---|---|
| Slice total before this task | 7,134,933 | $7.135 |
| Competitor suggestion job | 192,981 | $0.193 |
| First prompt suggestion job (50) | 6,724 | $0.0067 |
| Second prompt suggestion job (20 → 16) | 1,696 | $0.0017 |
| Eval, three brands (generate + embed) | 16,877 | $0.0169 |
| **This task** | **218,278** | **$0.218** |
| Slice total after | 7,353,211 | $7.353 |

Against the task's ~$0.30 allowance and the slice's $15 cap. The split
is worth keeping in view: **88% of this task's spend was competitor
suggestion**, one brand, one time. Prompt generation is nearly free
($0.0067 for 50); measuring those prompts is not (see §6).

Both guards saw it. The three job costs are on the `job` rows and reach
`spend.db_micros` and `budget_fits`; the eval's calls are in the ledger
under `prompt_eval:generate` and `prompt_eval:embed`.

One dating quirk carried from slice 3: job spend is dated by
`created_at` while observation spend is dated by `requested_at`, so a
job created at 23:59 and charged at 00:05 counts against the earlier
day.

## 5. The 0.92 threshold and the quality of the prompts

**Awaiting the user's review. Nothing is concluded here.**

The evidence for the two questions the spec's §7 risks name is above:
the full 50-prompt live set at the end of §3, the similarity
distributions in §2, and every pair the threshold dropped. Two things
to decide:

- **(a) Are the generated prompts worth running?** They cost $0.0067 to
  produce and about $5 a day to measure at 50 × 2 samples.
- **(b) Is 0.92 the right cut for `gemini-embedding-001`?** §1 kept it
  on the probe's evidence; §2 adds two more categories, where the
  prompt-level near-duplicate rate ran 0.0%, 3.2% and 7.9% against the
  spec's "under 5%" wording, and where the pairs it dropped are listed
  in full.

Until (b) is answered, `DUPLICATE_THRESHOLD = 0.92` in `suggest.py`
stands as the probe's decision.

## 6. Known gaps and follow-ups

Carried from the build, in the order they would bite:

1. **On-demand runs have no budget check** (spec §7). The plan limit is
   the only ceiling, so a Starter org can spend 100 prompts × 10 samples
   × $0.05 = **$50 on one POST**. This slice made creating many prompts
   easy, which is exactly what makes this worth stating.
2. **A suggestion job reserves an estimate before spending, but queued
   jobs are not reserved**, so a daily-budget overshoot is bounded by
   workers × estimate, not by zero.
3. **One worker runs jobs serially.** The competitor job took 123.7 s
   and blocked the prompt job behind it; a wizard on one worker is as
   slow as its slowest half.
4. **A generated prompt can still name an active competitor.** The
   active competitors are read but are not passed to `clean_prompts`,
   so only the brand's own names are filtered out.
5. **Embedding spend is lost if a later chunk fails**, and `count` is
   unvalidated inside core (the API enforces 0..100; the worker only
   casts).
6. **Reads span every locale while writes and the duplicate check span
   one**, so a second locale sees the first's prompts as context but
   dedupes only within itself.
7. **`evidence=1` competitor rows are written.** Ten suggestions came
   back here and one of them had a single answer behind it; the product
   rule is that one answer is not evidence, so the UI should either hide
   or mark them.
8. **A discarded job attempt leaves its tenant rows written.** A requeue
   re-runs and dedupes against them, so it is self-healing for both
   prompts and competitors, but the first attempt's money is spent
   twice.
9. **The "at most eight topics" instruction is advisory**, and the model
   sometimes answers with an intent name as a topic (§2).

Deliberately out of scope, for a later slice:

- **Other prompt sources**: SERP autocomplete, People Also Ask, Search
  Console, CSV import. Everything here comes from one model call.
- **Volume estimates**: no prompt carries a demand figure, so a
  reviewer cannot yet rank 50 suggestions by how much traffic they
  represent.
- **An HNSW index on `prompt.embedding`**: the duplicate check is a
  sequential scan per survivor, which is fine at a few thousand prompts
  per brand and is not fine at a hundred thousand.
- **Relabelling**: labels are written once and never recomputed, which
  is what makes groups stable; there is no way to re-topic an existing
  set after the vocabulary drifts.
- **Exposing on-demand runs safely**: item 1 above needs either a budget
  check or an explicit confirmation step before the flow is put in front
  of a user.
