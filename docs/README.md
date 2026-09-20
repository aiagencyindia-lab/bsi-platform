# Documents

Everything behind this repo: the documents it was built from, and the ones
produced while building it.

## Inputs (given)

| Document | What it is |
|---|---|
| [inputs/prd-brand-search-intelligence-platform.md](inputs/prd-brand-search-intelligence-platform.md) | The product requirements document (PRD) for the whole platform, v1.0, 2026-09-18. This repo is sub-project 1 of it. This Markdown file is the version the build worked from. |
| [inputs/prd-brand-search-intelligence-platform.docx](inputs/prd-brand-search-intelligence-platform.docx) | The same PRD as a Word document. |
| [inputs/prd-brand-search-intelligence-platform.pdf](inputs/prd-brand-search-intelligence-platform.pdf) | The same PRD as a 51-page PDF, exported a few hours before the `.md` and `.docx`. Its sections and content match. |
| [inputs/handoff-2026-09-19-adk-brand-search-optimization.md](inputs/handoff-2026-09-19-adk-brand-search-optimization.md) | Handoff describing the ADK demo app this platform grew out of. |

## Reference

| Document | What it is |
|---|---|
| [reference/adk-brand-search-optimization-test-guide.md](reference/adk-brand-search-optimization-test-guide.md) | The ADK demo's application, features and manual test guide. The PRD lists it as a related document. |

## Produced for slice 1: measurement core

In the order they were written:

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-19-slice1-measurement-core-design.md](superpowers/specs/2026-09-19-slice1-measurement-core-design.md) | Design spec. It is binding for slice 1 and was amended during the build. |
| [superpowers/plans/2026-09-19-slice1-measurement-core.md](superpowers/plans/2026-09-19-slice1-measurement-core.md) | Implementation plan, Tasks 0–11, with code and tests. |
| [findings-slice1.md](findings-slice1.md) | Results of the live run: cost, interval widths, matcher accuracy, injection resistance, follow-ups. |
| [audit-slice1.md](audit-slice1.md) | Task-by-task audit after the build, with the defects it found and the commits that fixed them. |

## Slice 2: cost and trust

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-19-slice2-cost-and-trust-design.md](superpowers/specs/2026-09-19-slice2-cost-and-trust-design.md) | Design spec: migrate to Gemini 3, make recommendation labels trustworthy, add extraction retries, run the sampling-cost experiment. |
| [superpowers/plans/2026-09-19-slice2-cost-and-trust.md](superpowers/plans/2026-09-19-slice2-cost-and-trust.md) | Implementation plan, Tasks 0–12. |
| [findings-slice2.md](findings-slice2.md) | Results: model cost per observation, judge robustness, sampling designs, slice 1 re-extracted under v2, spend, risks. |

## Slice 3: scheduler and deltas

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-20-slice3-scheduler-and-deltas-design.md](superpowers/specs/2026-09-20-slice3-scheduler-and-deltas-design.md) | Design spec: schedules per brand, a per-tenant daily budget, week-over-week deltas with Newcombe intervals, and pipeline-version comparability. |
| [superpowers/plans/2026-09-20-slice3-scheduler-and-deltas.md](superpowers/plans/2026-09-20-slice3-scheduler-and-deltas.md) | Implementation plan, Tasks 1–9. |
| [findings-slice3.md](findings-slice3.md) | Results: the live scheduler check, budget behaviour, delta semantics and their false-significant rate, the cost of a daily schedule against the budget, follow-ups. |

## Slice 4: prompt intelligence and the brand wizard

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-20-slice4-prompt-intelligence-design.md](superpowers/specs/2026-09-20-slice4-prompt-intelligence-design.md) | Design spec: generated prompts with intents and topics, embedding de-duplication, suggested competitors, prompt states and plan limits, a per-org budget override and a cost preview. |
| [superpowers/plans/2026-09-20-slice4-prompt-intelligence.md](superpowers/plans/2026-09-20-slice4-prompt-intelligence.md) | Implementation plan, Tasks 0–10. |
| [findings-slice4.md](findings-slice4.md) | Results: the embedding probe and duplicate threshold, prompt generation across three brands, the live wizard check, spend, and the known gaps. |
| [superpowers/specs/2026-09-20-slice5-operator-dashboard-design.md](superpowers/specs/2026-09-20-slice5-operator-dashboard-design.md) | Design spec: a Next.js operator dashboard (overview, prompt table and evidence, ops and spend, judge labelling) and the API changes it needs. |
| [superpowers/plans/2026-09-20-slice5-operator-dashboard.md](superpowers/plans/2026-09-20-slice5-operator-dashboard.md) | Implementation plan, Tasks 1–9. |
| [findings-slice5.md](findings-slice5.md) | Results: the searched rate by model/org, which prompts separate the brand from its top rival on "Run 1" and at what n, label count and judge agreement with its interval, and the known gaps. |

Run data and evaluation sets live next to the code, because the scripts
and tests read them there.

**Run specs** (a brand, its competitors and its prompts):
- [../eval/run1.json](../eval/run1.json): slice 1's live run — 20 prompts, 5 competitors, 3 samples.
- [../eval/run2_check.json](../eval/run2_check.json): the same brand cut to 5 prompts at 1 sample, for a cheap smoke check.

**Labelled sets** (hand-checked, the bar the models are measured against):
- [../eval/benchmark_v0.jsonl](../eval/benchmark_v0.jsonl): 30 hand-labelled observations for the matcher.
- [../eval/injection_v0.jsonl](../eval/injection_v0.jsonl): 30 adversarial answers that try to talk the judge into a verdict.
- [../eval/rec_labels_v0.jsonl](../eval/rec_labels_v0.jsonl): 50 recommendation labels over 30 real answers, reviewed by the user.

**Results** (the evidence behind the findings):
- [../eval/results/judge_eval_legacy.json](../eval/results/judge_eval_legacy.json), [batched](../eval/results/judge_eval_batched.json), [isolated](../eval/results/judge_eval_isolated.json): judge robustness per mode ([findings-slice2.md](findings-slice2.md) §2).
- [../eval/results/sampling_v0.json](../eval/results/sampling_v0.json): the sampling designs A, B and C ([findings-slice2.md](findings-slice2.md) §3).
- [../eval/results/probe_slice4.json](../eval/results/probe_slice4.json): the embedding probe and the similarity distribution behind the 0.92 duplicate threshold ([findings-slice4.md](findings-slice4.md) §1).
- [../eval/results/prompt_gen_v0.json](../eval/results/prompt_gen_v0.json): prompt generation across three brands ([findings-slice4.md](findings-slice4.md) §2).

The raw engine answers from the live run are in `data/`. They are
git-ignored and stay local.
