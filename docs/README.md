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

Run data lives next to the code, because the scripts and tests read it
there:
- [../eval/run1.json](../eval/run1.json): the brand, competitors and prompts of the live run.
- [../eval/benchmark_v0.jsonl](../eval/benchmark_v0.jsonl): 30 hand-labelled observations.

The raw engine answers from the live run are in `data/`. They are
git-ignored and stay local.
