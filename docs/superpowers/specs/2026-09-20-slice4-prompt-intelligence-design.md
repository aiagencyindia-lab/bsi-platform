# Slice 4: Prompt intelligence and the brand wizard — design

- **Date:** 2026-09-20
- **Status:** Draft for review
- **Builds on:** slices 1–3 (`2026-09-19-slice1-…`, `2026-09-19-slice2-…`, `2026-09-20-slice3-…`), `docs/findings-slice1.md`, `findings-slice2.md`, `findings-slice3.md`
- **PRD modules touched:** F01 (onboarding and brand setup), F02 (prompt intelligence), §10.1 (model routing), §10.5 and §19 (cost)

## 1. Why this slice exists

A brand is only as good as its prompts, and today every prompt is typed
by hand. `scripts/live_run.py` is the entire setup flow. The PRD's first
promise (F01) is a brand that goes from a name to a running measurement
in minutes: competitors suggested and confirmed, about 50 prompts
generated and reviewed, then a first run.

Two things make this more than "call a model and insert rows".

1. **The starter set does not fit the budget we just shipped.** Slice 3
   estimates $0.05 per observation, so 50 prompts × 2 samples reads as
   $5 against the $2 daily cap. A wizard-built brand would be skipped by
   its own schedule on day one.
2. **Suggestion itself costs money**, through the worker, outside every
   guard we have. It has to be budgeted, recorded and visible.

### 1.1 Decisions made (user, 2026-09-20)

| # | Question | Decision |
|---|---|---|
| D1 | How are near-duplicate prompts found? | Vertex text embeddings stored in a `vector(768)` column; cosine ≥ 0.92 within a brand and locale is a duplicate. The `pgvector` package is accepted. |
| D2 | How are prompts grouped? | Labels assigned once at generation: one of the PRD's 10 intents plus a short topic. A group is (intent, topic). No clustering algorithm. |
| D3 | How is the budget conflict resolved? | A per-organization daily budget override (default stays $2), plus a cost preview whenever prompts are activated or a schedule is set. Nothing is refused because of the preview. |
| D4 | Are competitors suggested too? | Yes. One grounded query asked three times, ranked by how many answers name each competitor, confirmed by the user. |

### 1.2 Out of scope

- Any UI. The wizard is the API flow plus a driver script.
- Hindi and Hinglish variants (PRD Phase 2).
- Other prompt sources: SERP autocomplete, People Also Ask, Search
  Console, CSV import.
- Volume estimates, the `product` table, and brand detection from a
  domain (F01 has the user type the name, aliases and category).
- An API to set the organization budget; a script sets it, because
  `bsi_app` has no UPDATE on `organization`.
- An HNSW index on embeddings, and any relabelling of existing groups.
- Budgets on on-demand runs. This slice makes it easier to create many
  prompts, so §7 states the exposure plainly.

## 2. Data model (migration 0007)

| Table | Change | Rule |
|---|---|---|
| `prompt` | `intent` | nullable; CHECK in the 10 PRD classes |
| | `topic` | nullable text, lowercase, 1–3 words |
| | `embedding` | `vector(768)`, nullable |
| | `status` | CHECK `suggested`, `active`, `paused`, `archived` |
| | `source` | CHECK `manual`, `generated` |
| `competitor` | `status` | default `active`; CHECK `suggested`, `active` |
| | `evidence` | nullable int: how many of three answers named it |
| `organization` | `daily_budget_usd` | `numeric(10,2)` nullable, CHECK ≥ 0 |
| `job` | `status` | NULL for `kind='run'`; else `queued`, `running`, `done`, `failed` |
| | `params`, `error`, `cost_micros`, `started_at` | job bookkeeping |

No new table, so the tenancy suites need no new entry; the isolation
suite gains rows for the new endpoints (§6).

Existing rows carry only the server defaults, so the new CHECK
constraints are safe to add.

### 2.1 Claiming a job

`claim_job()` mirrors `claim_observation()`: plpgsql, SECURITY DEFINER,
`SET search_path = public`, revoked from PUBLIC and granted to
`bsi_app`. It first fails any `running` job older than 10 minutes with
`error='stale'`, then claims one `queued` job of a kind other than
`run`, using `FOR UPDATE SKIP LOCKED`.

A stale job is **failed, not retried**: it may already have spent money.
Re-posting the suggest endpoint requeues it (§5).

### 2.2 Suggestions must not affect measurement

A suggested competitor is a guess. Until the user confirms it, it must
not appear in the matcher's entity list or in share of voice. Three
readers gain `status = 'active'`: `extraction.load_entities`,
`metrics.brand_sov`, and `scripts/export_benchmark.py`. Each gets a test
where a suggested competitor with a mention row is absent from the
result, because a missed filter here silently changes a customer's
numbers.

## 3. Generating prompts

### 3.1 The call

Generation uses the judge model (`gemini-3.5-flash-lite`, already
priced), through the existing typed-output helper, which becomes public
as `judge.generate(prompt, schema, temperature)`. Two differences from
the judge's use:

- **Temperature ≈ 1.0.** The judge runs at 0 for repeatability. At 0 a
  second suggestion for the same brand returns the same prompts and
  dedupe deletes all of them.
- **The model is told what already exists**: a capped, escaped list of
  current prompt texts and topics, so it adds rather than repeats.

It asks for about 25% more than requested, to absorb dedupe losses.

### 3.2 Labels (D2)

Each generated prompt carries one of the PRD's ten intents
(informational, commercial, transactional, comparison, alternative,
recommendation, problem-based, industry-specific, persona-specific,
geographic) and a topic of one to three lowercase words. The prompt
instructs the model to use at most eight topics and to reuse the ones
already present, which is what stops "running shoes" and "shoes for
running" becoming separate groups. Topics are stripped and case-folded
before storage.

A group is simply (intent, topic). Labels are written once and never
recomputed, so the PRD's stability requirement holds by construction.

### 3.3 Deduplication (D1)

- **Within the batch:** embed the candidates, then a greedy keep-first
  pass using cosine similarity in Python.
- **Against existing prompts:** one `EXISTS` query per survivor against
  the same brand and locale, using pgvector's distance operator. No
  index yet; a brand has a few thousand prompts at most, and the query
  is bounded by that. Doing this in SQL rather than Python avoids
  loading every stored vector into the worker.

Manual prompts are not de-duplicated when created. They gain labels and
an embedding on the next suggestion job, which backfills anything
missing first. A job with `count = 0` therefore means "classify what I
already have".

### 3.4 Embeddings

`embed()` calls `client.models.embed_content` with
`task_type="SEMANTIC_SIMILARITY"` and `output_dimensionality=768`, one
text per call under the existing retry helper, because the SDK rejects
batched input for most Gemini embedding models. Cost comes from the
response's token counts against a new `EMBED_PRICES` table that raises
for an unpriced model, exactly like `JUDGE_PRICES`, and the worker
fails at startup on an unpriced embedding model.

Step 0 of the build probes which model id works in `global`, its
latency and its price, and confirms that 0.92 is the right threshold for
that model by printing the similarity distribution of a real generated
set. The threshold is a product judgement, so the user confirms it.

## 4. Suggesting competitors (D4)

The product's own rule is that one answer is not evidence, so the
suggestion asks the engine three times, through the existing grounded
adapter. Each answer is parsed into typed output by the model, then
merged by normalized name and domain. Each survivor stores `evidence`:
how many of the three answers named it. The brand itself, its aliases
and already-known competitors are dropped.

The adapter never raises: a failed answer is skipped, and the job fails
only if all three fail.

## 5. API

| Method | Path | Behaviour |
|---|---|---|
| POST | `/v1/brands/{id}/prompts/suggest` | `{count: 0..100 = 50}` → 202 `{job_id, status_url}`. 409 for an archived brand. |
| POST | `/v1/brands/{id}/competitors/suggest` | 202, same shape. |
| GET | `/v1/brands/{id}/prompts` | Gains `status` and `intent` filters; the view gains `intent` and `topic`. |
| PATCH | `/v1/brands/{id}/prompts/{pid}` | Accepts all four statuses. |
| PATCH | `/v1/brands/{id}/prompts` | Bulk `{ids, status}`. Every id must belong to this brand, else 404. |
| GET | `/v1/brands/{id}/clusters` | `[{intent, topic, active, suggested, paused}]`. |
| PATCH | `/v1/brands/{id}/competitors/{cid}` | Accepts `status: "active"` to confirm a suggestion. |

One job per brand, kind and UTC hour, reusing the existing unique key. A
repeat in the same hour returns the same job, **except** that a failed
job is requeued, so a user is not locked out for the rest of the hour by
one failure.

**Plan limits.** Active prompts per organization are capped by plan
(Starter 100, Pro 500, Agency 2,000; an unknown plan is treated as
Starter). Checked on create, on single activation and on bulk
activation, under the same per-organization lock the budget uses, and
refused with 409 naming the limit and the current count.

**Length caps.** Category, aliases and competitor names are capped at
200 characters, because they flow into paid model input.

## 6. Cost preview (D3)

`daily_cost_preview` reports what a brand's prompts will cost per day
and what the whole organization's active schedules will cost, against
the effective budget:

- per brand: active prompts × samples ÷ cadence days × the same
  per-observation estimate the budget check uses;
- per organization: the same, summed over every active schedule, because
  the budget is per organization and two brands can each look
  affordable while together exceeding it.

It appears in the schedule view and in the bulk-activation response,
with `fits: false` as the warning. Nothing is refused on its basis; the
budget check still decides at enqueue time.

The organization's budget override is read by the budget check, falling
back to the setting. Suggestion spend is added to both guards: the daily
budget and the script-level spend ledger, so a wizard run cannot be
invisible to either.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Generated prompts are bland or wrong for the brand | A user review stop on a real generated set before the slice closes |
| The 0.92 threshold is wrong for this embedding model | The probe prints the similarity distribution; the user confirms |
| A suggested competitor silently changes metrics | `status='active'` filters, each with its own test (§2.2) |
| Activating many prompts spends heavily on an on-demand run | Stated plainly: on-demand runs have no budget check, so the plan limit is the only ceiling. 100 prompts × 10 samples × $0.05 is $50 for one call |
| Suggestion jobs overshoot the daily budget | Each job reserves an estimate before spending; queued jobs are not reserved, so overshoot is bounded by workers × estimate. Recorded as a known gap |
| Tenant text reaches model input | Everything escaped and wrapped in a delimited data block, as the judge does; outputs validated and capped in Python |
| A crashed job spends twice | A stale job is failed, never retried; the final write discards its work unless the job is still `running` |

## 8. Definition of done

1. `POST …/prompts/suggest` produces about 50 suggested prompts with
   intents, topics and embeddings, in 90 seconds or less, with
   near-duplicates under 5% on the eval set.
2. A second suggestion for the same brand adds new prompts rather than
   none.
3. `POST …/competitors/suggest` produces suggestions with evidence
   counts, and suggested competitors affect no metric until confirmed.
4. Prompt states, plan limits, filters, bulk activation and the clusters
   view all work, and suggestions cost money that both spend guards see.
5. Activating a 50-prompt set shows a cost preview that does not fit the
   $2 default, and does fit after the organization's budget is raised.
6. Gate green, `bsi_core.metrics` still at 100%, and
   `docs/findings-slice4.md` records the probe, the eval and the spend.
