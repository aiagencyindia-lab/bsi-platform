# Slice 56 design: replace the gemini-2.5-flash engine before it retires

Classification: architectural, said first in chat on 2026-10-08 before the first question. Session model Opus 5.5 throughout.

## Context

The grounded-search engine is `gemini-2.5-flash` (packages/core/bsi_core/config.py `engine_model`, `.env`, `.env.example`). Google's Vertex AI "Model versions and lifecycle" page, updated 2026-10-07 and read on 2026-10-08, lists its retirement date as October 20, 2026. After that date every observation call would fail. Google lists `gemini-3.8-flash`, `gemini-3.5-flash-lite` and `gemini-3.1-flash-lite` as replacements. The judge `gemini-3.5-flash-lite` lasts to July 21, 2027 or later, and the embeddings model `gemini-embedding-001` to no sooner than May 20, 2028, so only the engine is affected.

The choice is not a config edit. On 2026-09-22 the engine moved off `gemini-3.8-flash` because it searched in about 1 answer in 4 (findings-slice2: 26–33%), while `gemini-2.5-flash` searched in 80 of 80 (findings-slice5). On every Gemini 3 model grounding is billed per search query ($14 per 1,000; 5,000 a month free across Gemini 3, which the platform does not model), not per grounded prompt as on 2.5 ($35 per 1,000). So the cost of an observation depends on how often, and how much, each model searches.

Spend: $11.23 of the $15.00 project cap is used (ledger 6,858,204 micros + DB 4,374,377 micros, computed as `spend.check` does), so $3.77 is left.

Approaches offered in chat: (A) probe three listed replacements on the 20 Run 1 prompts, then switch; (B) switch to `gemini-3.8-flash` now and measure only it; (C) A plus a "search before answering" instruction arm. The user chose A on 2026-10-08.

## Section 1 — The probe

A new script, `scripts/engine_probe.py`, follows `scripts/sampling_experiment.py`. It reads the 20 prompts from `eval/run1.json`, makes one shared `genai` client, and builds `GeminiGroundingAdapter(client=shared, model=m)` per candidate.

- Candidates: `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.8-flash`. One grounded call per prompt per model: 60 calls. Calls are interleaved per prompt (prompt 1 on all three models, then prompt 2, and so on).
- Spend guard. Every call goes through `spend.check(100_000)` and then `spend.record("engine_probe:<model>", cost, release=100_000)`, with retries as in `sampling_experiment.ask` (3 attempts, each attempt's cost recorded). On top of the project cap, the probe has a hard stop at $3.00 of its own recorded spend: before each call it checks that the probe's spend so far plus 100,000 micros stays at or under 3,000,000 micros. If not, it stops before the call and writes partial results.
- Per call it records: the raw response, to `data/experiments/engine/<model>/p<i>.json` (git-ignored); searched (`web_search_queries` non-empty); the number of queries; `cost_micros` from the adapter's own `cost()`; input and output tokens; latency; and the brands found by the deterministic matcher (`bsi_core.matching.find_mentions` over the entities built from `eval/run1.json`, as sampling_experiment does). No judge call.
- Results go to `eval/results/engine_probe_v0.json`. Per model: completed calls, failures, searched share as `metrics.rate(k, n)` (95% Wilson), mean queries per answer, mean `cost_micros` per observation, and mean brands found. Overall: total spent and the pick.
- Decision rule, fixed before the run as the pure function `pick(results)`. Among models with at least one completed call, judged on completed calls only:
  1. the candidate set is the models whose searched-share point estimate is at least 0.80; if it is empty, `pick` returns `None`;
  2. the leader is the model with the highest searched share, ties broken by lower mean cost;
  3. any other candidate whose Wilson interval overlaps the leader's competes on mean cost, and the lowest mean cost wins.
  If `pick` returns `None`, the numbers go to the user and Task 2 waits for a decision.
- The script spends money. It runs only after the user says so, from the slice worktree, and its numbers go to the ledger.

## Section 2 — The switch

- `packages/core/bsi_core/providers/gemini.py` `PRICES` gains, from the pricing page read 2026-10-08 (global, standard rates):
  - `"gemini-3.5-flash-lite": Price(0.30, 2.50, 0, 14_000)`
  - `"gemini-3.1-flash-lite": Price(0.25, 1.50, 0, 14_000)`
  The `gemini-3.8-flash` row stays at its standard rate. The `gemini-2.5-flash` row stays, so stored observations remain priced. These rows land before the probe runs, because the adapter fails any model with no price row.
- After the probe: `config.py` `engine_model` becomes the picked model, with its comment updated to the probe's measured searched share and cost; `.env.example` follows. The dev `.env` is changed only after asking the user.
- `config.py` `obs_cost_estimate_micros` (50,000 today) becomes the picked model's measured mean cost per observation, rounded up to the next 10,000 micros.
- Comparability guard (option (i′), chosen after a fact correction in chat). A new helper `window_models(s, brand_id, f) -> list[str]` in `packages/core/bsi_core/metrics.py`, beside `window_versions`, returns the distinct non-NULL `observation.model` values of the done observations in a window (same `_where` filter). Both comparability rules use it:
  - `metrics.brand_deltas`: windows are comparable only when the union of both windows' pipeline versions has at most one value and the union of both windows' models has at most one value. Consumers: the deltas API, reports, the `mention_drop` alert, and task impact (`impact.measure`), which returns `not_comparable` with the reason.
  - `competitors._comparable`: the same model check. Consumers: `entity_deltas` and `visibility_changes`, and through it the `competitor_shift` alert.
  - When models differ, the reason is `windows use different engine models [<sorted models>]`. When both the pipeline versions and the models differ, the pipeline-version reason is kept (it names a fix: re-extract).
  Effect after the switch: no brand delta or `mention_drop` alert for about 7 days per brand, no competitor delta or `competitor_shift` alert for up to 28 days, and done tasks whose windows straddle the switch get `not_comparable`. Rows with a NULL model are ignored by the check; dev has none (110 done rows on `gemini-2.5-flash`, 15 on `gemini-3.8-flash`, read 2026-10-08).

## Section 3 — Sequencing and tests

One branch and one PR, merged before 2026-10-20:

1. Task 1 (independent of the pick): the two `PRICES` rows; `scripts/engine_probe.py` with `pick()` and the hard-stop check importable as pure functions; `window_models` and the guard in both rules; tests.
2. The probe run, on the user's go, ≤ $3.00; the results file is committed and every number is ledgered.
3. Task 2 (the switch): the `engine_model` default and comment, `.env.example`, `obs_cost_estimate_micros`, and the rewritten default-engine test. If `pick` returned `None`, Task 2 waits.

Tests:
- `pick()`: the highest share wins; overlapping intervals go to the lower mean cost; no pick when every share is below 0.80; failures excluded (a model is judged on completed calls).
- Hard stop: with a fake adapter whose costs would cross 3,000,000 micros, the probe stops before the crossing call and writes partial results.
- Prices: one cost test per new row; a fixture with 3 queries costs its token cost plus 42,000 micros.
- Guard: one window of `gemini-2.5-flash` rows and one of another model's rows give `brand_deltas` `comparable: false` with the model reason, `entity_deltas` `comparable: false` with the same reason, and `impact.measure` `not_comparable`. Existing same-model tests stay green.
- The default-engine test (`test_default_engine_is_gemini_2_5_flash_priced_per_grounded_prompt`, tests/unit/test_gemini_adapter.py) becomes: the default engine has a `PRICES` row and is the picked model.

Proof: red on main, green when patched, and a mutation table, each mutant caught by a named test: either rule without the model check; `pick` without the tie-break; `pick` without the 0.80 bar; a new price row without the per-query fee.

## Section 4 — Process, live check, docs

Spec → Opus review → scoped re-review → user review → "Approve, write plan" → writing-plans from a scratchpad proof → plan review → execution choice → Opus 5.5 implementers per task with task reviews → the probe run on the user's go → Task 2 → final review → controller gates → finishing menu → PR → docs (controller-written under the user's standing rule).

Live check: the probe itself, ≤ $3.00 of real spend, counted against the $15 cap. Dev DB untouched by the probe (it calls the adapter directly, not the API). The dev `.env` changes only after asking.

Out of scope: a "search before answering" instruction (approach C); modelling the free grounding allowances; re-running stored observations on the new model; a model filter on `/metrics`.

## Rulings

None at spec time.

## Deferred

- The 5,000 free Gemini 3 search queries a month are not modelled, so recorded costs are list prices.
- `n = 20` per model separates about 100% from 30% searched share, not finer differences.
