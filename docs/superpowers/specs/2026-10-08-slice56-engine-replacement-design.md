# Slice 56 design: replace the gemini-2.5-flash engine before it retires

Classification: architectural, said first in chat on 2026-10-08 before the first question. Session model Opus 5.5 throughout.

## Context

The grounded-search engine is `gemini-2.5-flash` (packages/core/bsi_core/config.py `engine_model`, `.env`, `.env.example`). Google's Vertex AI "Model versions and lifecycle" page, updated 2026-10-07 and read on 2026-10-08, lists its retirement date as October 20, 2026. After that date every observation call would fail. Google lists `gemini-3.8-flash`, `gemini-3.5-flash-lite` and `gemini-3.1-flash-lite` as replacements. The extraction model (`extract_model`, `gemini-3.5-flash-lite`) lasts to July 21, 2027 or later, and the embeddings model `gemini-embedding-001` to no sooner than May 20, 2028, so only the engine is affected.

The choice is not a config edit. On 2026-09-22 the engine moved off `gemini-3.8-flash` because it searched in about 1 answer in 4 (findings-slice2: 26–33%), while `gemini-2.5-flash` searched in 80 of 80 (findings-slice5). On every Gemini 3 model grounding is billed per search query ($14 per 1,000; 5,000 a month free across Gemini 3, which the platform does not model), not per grounded prompt as on 2.5 ($35 per 1,000). So the cost of an observation depends on how often, and how much, each model searches.

Spend: $11.23 of the $15.00 project cap is used (ledger 6,858,204 micros + DB 4,374,377 micros, computed as `spend.check` does), so $3.77 is left.

Approaches offered in chat: (A) probe three listed replacements on the 20 Run 1 prompts, then switch; (B) switch to `gemini-3.8-flash` now and measure only it; (C) A plus a "search before answering" instruction arm. The user chose A on 2026-10-08.

## Section 1 — The probe

A new script, `scripts/engine_probe.py`, follows `scripts/sampling_experiment.py`. It reads the 20 prompts from `eval/run1.json`, makes one shared `genai` client, and builds `GeminiGroundingAdapter(client=shared, model=m)` per candidate.

- Candidates: `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, `gemini-3.8-flash`. One grounded call per prompt per model: 60 attempts. Calls are interleaved per prompt (prompt 1 on all three models, then prompt 2, and so on).
- Environment: the probe runs from the slice worktree's code with the main checkout's `.env` sourced (for the Vertex settings) and `RAW_STORE_DIR=/Users/vineet/Downloads/ADK/bsi-platform/data`, so `spend` reads and writes the canonical ledger. Before the first call it prints `spend.ledger_micros()` and the DB spend and refuses to start if the ledger reads less than 6,858,204 micros, the canonical ledger's total on 2026-10-08 (a lower value means it is reading another ledger).
- Spend guard. The probe's own spend is the sum of the ledger entries whose kind starts with `engine_probe:` (read at start) plus what this run records, so a re-run shares one budget. Before each call the probe reserves `r = max(100_000, the largest single call cost recorded so far by the probe)` and stops, writing partial results, if probe spend + r would exceed 3,000,000 micros. The call itself goes through `spend.check(r)` and then `spend.record("engine_probe:<model>", cost, release=r)`, with retries as in `sampling_experiment.ask` (3 attempts, each attempt's cost recorded). On `SpendCapReached` the probe writes partial results and re-raises.
- The bound, stated honestly: total probe spend is at most $3.00 plus one call's excess over its reservation, plus any billed call that recorded no cost (a timeout or an unparseable payload records 0, because the platform never sees its usage). Expected total from list prices: about $0.6 if both flash-lite models search as rarely as 3.8 did, about $2.8 if they search like 2.5 did (4 queries per answer).
- Per attempt it records: the raw response, to `data/experiments/engine/<model>/p<i>.json` (git-ignored); success or failure; searched (`web_search_queries` non-empty); the number of queries; `cost_micros` from the adapter's own `cost()`; input and output tokens; latency; and brands found by the deterministic matcher (`bsi_core.matching.find_mentions` over entities built from `eval/run1.json`: the brand with its aliases and the competitors). No judge call.
- Results go to `eval/results/engine_probe_v0.json`. Per model: attempts, completed, failures, searched share as `metrics.rate(searched, attempts)` (95% Wilson; a failed attempt counts as not searched), mean queries per completed answer, mean `cost_micros` per completed observation, and mean brands found. Overall: total probe spend and the pick.
- Decision rule, fixed before the run as the pure function `pick(results)`:
  1. a model is eligible only with 20 attempts (a model cut short by the stop is not picked);
  2. the candidate set is the eligible models whose searched share is at least 0.80; if it is empty, `pick` returns `None`;
  3. the leader is the candidate with the highest searched share, ties broken by lower mean cost;
  4. any other candidate whose Wilson interval overlaps the leader's (inclusive: touching intervals overlap) competes on mean cost, and the lowest mean cost wins;
  5. an exact tie on mean cost goes to the later retirement date (`gemini-3.5-flash-lite` July 21, 2027; `gemini-3.1-flash-lite` May 7, 2027; `gemini-3.8-flash` none announced, treated as earliest), then to the alphabetically first model id.
  If `pick` returns `None`, the numbers go to the user and Task 2 waits for a decision.
- The script spends money. It runs only after the user says so, and its numbers go to the ledger.

## Section 2 — The switch

- `packages/core/bsi_core/providers/gemini.py` `PRICES` gains, from the pricing page read 2026-10-08 (global, standard rates):
  - `"gemini-3.5-flash-lite": Price(0.30, 2.50, 0, 14_000)`
  - `"gemini-3.1-flash-lite": Price(0.25, 1.50, 0, 14_000)`
  The `gemini-3.8-flash` row stays at its standard rate. The `gemini-2.5-flash` row stays, so stored observations remain priced. These rows land before the probe runs, because the adapter fails any model with no price row.
- After the probe: `config.py` `engine_model` becomes the picked model, with its comment updated to the probe's measured searched share and cost; `.env.example` follows. The dev `.env` is changed only after asking the user.
- `config.py` `obs_cost_estimate_micros` becomes max(50,000, the smallest multiple of 10,000 strictly above (the picked model's mean engine cost per completed observation + 2,000 micros for extraction)). It can only stay or rise.
- Comparability guard (option (i′), chosen and then re-confirmed after two fact corrections in chat). A new helper `window_models(s, brand_id, f) -> list[str]` in `packages/core/bsi_core/metrics.py`, beside `window_versions`, returns the distinct non-NULL `observation.model` values of the done observations in a window (same `_where` filter). Both comparability rules call it directly; `brand_metrics`' output does not change, so no API schema changes.
  - `metrics.brand_deltas`: windows are comparable only when the union of both windows' pipeline versions has at most one value and the union of both windows' models has at most one value. Consumers: the deltas API, reports, the `mention_drop` alert, and task impact (`impact.measure`), which returns `not_comparable` with the reason.
  - `competitors._comparable`: the same model check. Consumers: `entity_deltas`, `visibility_changes`, and through it the `competitor_shift` alert.
  - When models differ, the reason is `windows use different engine models [<sorted models>]`. When both the pipeline versions and the models differ, the pipeline-version reason is kept (it names a fix: re-extract).
- Effects after the switch at time S (each delta compares [to − 2·days, to − days) with [to − days, to)):
  - brand deltas (API default 7 days), the `mention_drop` alert (7-day windows) and competitor deltas (API default 7 days): no comparison for about 14 days;
  - `/competitors/changes` and the `competitor_shift` alert (14-day windows): about 28 days;
  - task impact (14-day windows by default): tasks done between S − 14 days and S + 14 days get `not_comparable`. `close_window` stores the label once, so it is permanent, and the model reason names no fix.
  - Not changed by the guard: the `new_source` alert flags domains first cited in the last 7 days; a new engine will likely cite new domains, so spurious `new_source` alerts are likely for about a week.
  Rows with a NULL model are ignored by the check; dev has none (110 done rows on `gemini-2.5-flash`, 15 on `gemini-3.8-flash`, read 2026-10-08).

## Section 3 — Sequencing and tests

One branch and one PR, merged before 2026-10-20:

1. Task 1 (independent of the pick): the two `PRICES` rows; `scripts/engine_probe.py` with `pick()` and the stop check importable as pure functions; `window_models` and the guard in both rules; tests.
2. The probe run, on the user's go; the results file is committed and every number is ledgered.
3. Task 2 (the switch): the `engine_model` default and comment, `.env.example`, `obs_cost_estimate_micros`, the rewritten default-engine test, and `tests/integration/test_full_flow.py`'s `CannedGemini` pinned to `model="gemini-2.5-flash"` (it asserts the 2.5 price, 35,303 micros, on the default model today). If `pick` returned `None`, Task 2 waits.

Tests:
- `pick()`: the highest share wins; a share tie goes to the lower mean cost (step 3); an overlapping cheaper candidate wins (step 4); a cheaper overlapping model below 0.80 does not win; an exact cost tie goes to the later retirement date; no pick when every share is below 0.80; failures count as not searched; a model with fewer than 20 attempts is not picked.
- Stop check: the reservation is max(100,000, largest cost so far); with fake costs that would cross 3,000,000 micros the probe stops before the crossing call and writes partial results; earlier `engine_probe:` ledger entries count toward the 3,000,000.
- Prices: one cost test per new row; a fixture with 3 queries costs its token cost plus 42,000 micros.
- Guard: one window of `gemini-2.5-flash` rows and one of another model's give `brand_deltas` `comparable: false` with the model reason, `entity_deltas` the same, and `impact.measure` `not_comparable`; when both pipeline versions and models differ the pipeline reason is returned; NULL-model rows do not make windows incomparable. Existing same-model tests stay green.
- The default-engine test (`test_default_engine_is_gemini_2_5_flash_priced_per_grounded_prompt`, tests/unit/test_gemini_adapter.py) becomes: `Settings.model_fields["engine_model"].default` is the picked model and has a `PRICES` row (it does not read `get_settings()`, which follows `.env`).

Proof: red on main, green when patched, and a mutation table, each mutant caught by a named test: either rule without the model check; the pipeline reason not kept first; NULL models counted; `pick` without step 3's cost tie-break; `pick` without step 4; `pick` without the 0.80 bar; `pick` judging failures as missing instead of not searched; the reservation fixed at 100,000; a new price row without the per-query fee.

## Section 4 — Process, live check, docs

Spec → Opus review → scoped re-review → user review → "Approve, write plan" → writing-plans from a scratchpad proof → plan review → execution choice → Opus 5.5 implementers per task with task reviews → the probe run on the user's go → Task 2 → final review → controller gates → finishing menu → PR → docs (controller-written under the user's standing rule).

Live check: the probe itself, with the bound and expected cost in Section 1, counted against the $15 cap. The dev DB is untouched by the probe (it calls the adapter directly, not the API). The dev `.env` changes only after asking.

Out of scope: a "search before answering" instruction (approach C); modelling the free grounding allowances; re-running stored observations on the new model; a model filter on `/metrics`; the `engine` table's seeded `default_model` (`'gemini-2.5-flash'`, migration 0002), which is not read by the code and stays stale.

## Rulings

Every `Ruling:` line in the ledger, verbatim (later ones are appended by the docs commits):

> Ruling: R1. Decided: the spec review's other findings are fixed in the spec: the probe runs with the main checkout's .env sourced and RAW_STORE_DIR pointing at /Users/vineet/Downloads/ADK/bsi-platform/data, and refuses to start unless spend.ledger_micros() reads the canonical ledger (6,858,204 micros at 2026-10-08 plus any later entries the user knows of) (I1); the probe's own spend is the sum of ledger entries whose kind starts with 'engine_probe:' read at start plus this run's, so a re-run shares the $3.00 (I4 gap); Task 2 pins tests/integration/test_full_flow.py's CannedGemini to model 'gemini-2.5-flash' and the default-engine test reads Settings.model_fields['engine_model'].default, not get_settings() (I5); 'brands found' counts the brand and its aliases plus the competitors from eval/run1.json (M2); on SpendCapReached the probe writes partial results and then re-raises (M3); tests are added for the pipeline-reason precedence and for NULL models being ignored (M4) and for pick() refusing a cheaper overlapping model below 0.80 and breaking a share tie by cost (M5); the mutation table names step 2 and step 3 tie-breaks separately (M5); engine.default_model in the engine table stays stale and is out of scope (M7); window_models is called in brand_deltas and _comparable, not added to brand_metrics output, so no API schema change (M8); 3.5-flash-lite is named as extract_model (M9). Found by: the spec reviewer (Opus 5.5), 2026-10-08. Why: an unsafe run procedure, tests that would break or depend on .env, and loose statements of mine. Cost if wrong: none to behaviour; a wrong ledger path would make the probe's spend invisible to the cap, which the pre-run check stops. How named: quoted in chat. (2026-10-08 09:01 UTC)

## Deferred

- The 5,000 free Gemini 3 search queries a month are not modelled, so recorded costs are list prices.
- `n = 20` per model separates about 100% from 30% searched share, not finer differences.
