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

## Slice 5: operator dashboard

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-20-slice5-operator-dashboard-design.md](superpowers/specs/2026-09-20-slice5-operator-dashboard-design.md) | Design spec: a Next.js operator dashboard (overview, prompt table and evidence, ops and spend, judge labelling) and the API changes it needs. |
| [superpowers/plans/2026-09-20-slice5-operator-dashboard.md](superpowers/plans/2026-09-20-slice5-operator-dashboard.md) | Implementation plan, Tasks 1–9. |
| [findings-slice5.md](findings-slice5.md) | Results: the searched rate by model/org, which prompts separate the brand from its top rival on "Run 1" and at what n, label count and judge agreement with its interval, and the known gaps. Ends with the 2026-09-22 follow-up run at n=5, which tested the projection on the nine prompts the first run could not. |

## Slice 6: recommendations and tasks

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-21-slice6-recommendations-and-tasks-design.md](superpowers/specs/2026-09-21-slice6-recommendations-and-tasks-design.md) | Design spec: four rule-generated recommendation types with linked evidence, accept/dismiss, tasks, and a measured-impact window that reuses the deltas code. |
| [superpowers/plans/2026-09-21-slice6-recommendations-and-tasks.md](superpowers/plans/2026-09-21-slice6-recommendations-and-tasks.md) | Implementation plan, Tasks 1–6. |
| [findings-slice6.md](findings-slice6.md) | Results: what `generate` produced on "Run 1" and "Slice4 check", the citation rule's rival-domain fix and its residue, threshold sensitivity, the loop walked end to end to an honest "insufficient data", the weights as set, and the known gaps. |

## Slice 7: citation intelligence and the crawlability audit

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-23-slice7-citations-and-crawlability-design.md](superpowers/specs/2026-09-23-slice7-citations-and-crawlability-design.md) | Design spec: per-domain citation sources with a gap flag, a crawlability audit of the brand's own domain (robots.txt, bot user agents, sitemap, llms.txt, on-page checks), a weekly audit job, and a `fix_crawlability` recommendation type. |
| [superpowers/plans/2026-09-23-slice7-citations-and-crawlability.md](superpowers/plans/2026-09-23-slice7-citations-and-crawlability.md) | Implementation plan, Tasks 1–10. |
| [findings-slice7.md](findings-slice7.md) | Results: `sources()` and `generate()` on "Run 1" (247 cited domains, 136 gaps, and why the gap count is large), a live `audit_domain()` run against nytimes.com and example.com with every failing check, where `fix_crawlability` lands in `top_by_type` (first, tied at priority 0.8), the corrected 12-fetch budget, the SSRF guard and RFC 9309 robots.txt reading added by crawl-hardening (§5.8, §5.9), and spend (unchanged). |

## Slice 8: entity consistency audit

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-23-slice8-entity-consistency-design.md](superpowers/specs/2026-09-23-slice8-entity-consistency-design.md) | Design spec: schema.org Organization, homepage title and About-link checks, a domain-verified Wikidata match with a social-profile comparison, run inside the crawl audit, and a `fix_entity` recommendation type. |
| [superpowers/plans/2026-09-23-slice8-entity-consistency.md](superpowers/plans/2026-09-23-slice8-entity-consistency.md) | Implementation plan, Tasks 1–5. |
| [findings-slice8.md](findings-slice8.md) | Results: a live `audit_entity()` run against real domains with every check, which Wikidata candidates matched and why, where `fix_entity` ranks against `fix_crawlability`, and what is deferred. |

## Slice 9: competitor intelligence

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-23-slice9-competitor-intelligence-design.md](superpowers/specs/2026-09-23-slice9-competitor-intelligence-design.md) | Design spec: per-competitor metrics with Wilson intervals, a leaderboard, week-over-week deltas, and a visibility change feed gated by the PRD's count rule plus a pooled Newcombe test; computed on read. |
| [superpowers/plans/2026-09-23-slice9-competitor-intelligence.md](superpowers/plans/2026-09-23-slice9-competitor-intelligence.md) | Implementation plan, Tasks 1–5. |
| [findings-slice9.md](findings-slice9.md) | Results: the Run 1 leaderboard, why the feed is empty on a single-burst run, what the synthetic fixture proves, and what is deferred. |

## Slice 10: content gaps

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-23-slice10-content-gaps-design.md](superpowers/specs/2026-09-23-slice10-content-gaps-design.md) | Design spec: `(intent, topic)` clusters of active prompts, the slice 6 absence rule at cluster level, one `create_content` per gap cluster with a model-free brief, and a budget-gated `label_prompts` job. |
| [superpowers/plans/2026-09-23-slice10-content-gaps.md](superpowers/plans/2026-09-23-slice10-content-gaps.md) | Implementation plan, Tasks 1–5. |
| [findings-slice10.md](findings-slice10.md) | Results: Run 1 labelled live ($0.0022), its 15 clusters and 13 gaps with their briefs, where the cluster recommendations rank, what the cluster rule replaced, and label quality. |

## Slice 11: URL optimizer

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-24-slice11-url-optimizer-design.md](superpowers/specs/2026-09-24-slice11-url-optimizer-design.md) | Design spec: an AI Citability Score for one page against one gap cluster, a budget-gated `optimize_url` job, stored page audits with suggestions, and an `optimize_page` recommendation type. |
| [superpowers/plans/2026-09-24-slice11-url-optimizer.md](superpowers/plans/2026-09-24-slice11-url-optimizer.md) | Implementation plan, Tasks 1–8. |
| [findings-slice11.md](findings-slice11.md) | Results: what was built, the read-only live check with `scripts/score_page.py`, calibration notes, and what is deferred. |

## Slice 12: competitor site crawl

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-24-slice12-competitor-site-crawl-design.md](superpowers/specs/2026-09-24-slice12-competitor-site-crawl-design.md) | Design spec: a weekly, spend-free crawl of each competitor's declared domain (robots.txt, sitemaps, homepage and new pages' JSON-LD types), new pages and new structured data per competitor, and that evidence in the visibility change feed. |
| [superpowers/plans/2026-09-24-slice12-competitor-site-crawl.md](superpowers/plans/2026-09-24-slice12-competitor-site-crawl.md) | Implementation plan, Tasks 1–7. |
| [findings-slice12.md](findings-slice12.md) | Results: what was built, the read-only live check with `scripts/snapshot_rival.py`, and what is deferred. |

## Brand domains re-flag citations (after slice 12)

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-24-domains-reflag-citations-design.md](superpowers/specs/2026-09-24-domains-reflag-citations-design.md) | Design, written after the build: adding or removing a brand domain recomputes the stored brand-owned flag on that brand's citations, and Run 1's domains to declare. |
| [superpowers/plans/2026-09-24-domains-reflag-citations.md](superpowers/plans/2026-09-24-domains-reflag-citations.md) | Plan, Tasks 1–2 and the post-merge data step. |
| [findings-slice12.md](findings-slice12.md) §4 | The change's limits and deferred items. |

## Slice 13: alerts

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-25-slice13-alerts-design.md](superpowers/specs/2026-09-25-slice13-alerts-design.md) | Design spec: three rolling-window alert types, an Alerts tab, and one webhook per brand with bounded retries. |
| [superpowers/plans/2026-09-25-slice13-alerts.md](superpowers/plans/2026-09-25-slice13-alerts.md) | Implementation plan, Tasks 1–7. |
| [findings-slice13.md](findings-slice13.md) | Results: what was built, the read-only scan on Run 1, and what is deferred. |

## Slice 14: sitemaps in full

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-25-slice14-sitemaps-in-full-design.md](superpowers/specs/2026-09-25-slice14-sitemaps-in-full-design.md) | Design spec: sitemap files read up to 50 MiB with gzip, 50 files and 50,000 URLs per domain, exact cut-off errors, a time budget per domain. |
| [superpowers/plans/2026-09-25-slice14-sitemaps-in-full.md](superpowers/plans/2026-09-25-slice14-sitemaps-in-full.md) | Implementation plan, Tasks 1–4. |
| [findings-slice14.md](findings-slice14.md) | Results: the read-only re-check of skechers.in, skechers.com and crocs.in against the slice 12 numbers, and what is deferred. |

## Slice 15: reports

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-25-slice15-reports-design.md](superpowers/specs/2026-09-25-slice15-reports-design.md) | Design spec: five report types (CMO, SEO, content, PR, agency client) on a weekly or monthly cadence or on demand, stored as frozen documents, a revocable public share link and a reportlab PDF; with the rulings made during the build. |
| [superpowers/plans/2026-09-25-slice15-reports.md](superpowers/plans/2026-09-25-slice15-reports.md) | Implementation plan, Tasks 1–11, with the changes made during execution. |
| [findings-slice15.md](findings-slice15.md) | Results: what was built, a section for the live check on dev (pages, bytes and seconds per type), and what is deferred or untested. |

## Slice 16: recommendations from competitor site changes

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-25-slice16-rival-content-recs-design.md](superpowers/specs/2026-09-25-slice16-rival-content-recs-design.md) | Design spec: a `respond_to_rival_content` recommendation when a competitor's new pages match, by URL words, a cluster where the brand is behind; with the rulings made during the build. |
| [superpowers/plans/2026-09-25-slice16-rival-content-recs.md](superpowers/plans/2026-09-25-slice16-rival-content-recs.md) | Implementation plan, Tasks 1–6, with the changes made during execution. |
| [findings-slice16.md](findings-slice16.md) | Results: what was built, a section for the live check on dev, and what is deferred or untested. |

## Slice 17: report polish

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-25-slice17-report-polish-design.md](superpowers/specs/2026-09-25-slice17-report-polish-design.md) | Design spec: the report PDF served from the web app's own domain through one Route Handler, readable labels for coded cells in new report runs, an Intent column in the SEO content-gap table, and methodology v2; with the rulings made during the build. |
| [superpowers/plans/2026-09-25-slice17-report-polish.md](superpowers/plans/2026-09-25-slice17-report-polish.md) | Implementation plan, Tasks 1–3, with the changes made during execution. |
| [findings-slice17.md](findings-slice17.md) | Results: what was built, a section for the live check on dev, and what is deferred or untested. |

## Slice 18: product-title wedge

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-25-slice18-product-title-wedge-design.md](superpowers/specs/2026-09-25-slice18-product-title-wedge-design.md) | Design spec: a brand-scoped Products tab (PRD F16) that imports a catalogue by CSV or Google Merchant feed, infers each product's generic keyword, compares its title with titles found by one grounded search per keyword, and suggests a rule-checked title and bullets, exported as CSV through the web app's second Route Handler; with the rulings made during the build. |
| [superpowers/plans/2026-09-25-slice18-product-title-wedge.md](superpowers/plans/2026-09-25-slice18-product-title-wedge.md) | Implementation plan, Tasks 1–8, with the changes made during execution. |
| [findings-slice18.md](findings-slice18.md) | Results: what was built, a section for the live check on dev, and what is deferred or untested. |
| [superpowers/specs/2026-09-29-slice19-product-quality-design.md](superpowers/specs/2026-09-29-slice19-product-quality-design.md) | Design spec: product-title quality fixes for the slice 18 wedge, from its live check: singular and plural folded in `missing` and the rule check, trailing connectors removed, dropped original words flagged with a new `review` status and stored (migration 0020), and a key-based keyword vote with a run-wide key map and a fit check so products share searches; with the rulings made during the build. |
| [superpowers/plans/2026-09-29-slice19-product-quality.md](superpowers/plans/2026-09-29-slice19-product-quality.md) | Implementation plan, Tasks 1–5, with the changes made during execution. |
| [findings-slice19.md](findings-slice19.md) | Results: what was built, the live check on dev (run on 2026-09-29: migration 0020 and the ten-product re-check), and what is deferred or untested. |
| [superpowers/specs/2026-09-29-slice20-product-titles-not-stores-design.md](superpowers/specs/2026-09-29-slice20-product-titles-not-stores-design.md) | Design spec: product titles, not store names, for the product-title wedge (slice 19's deferred R5): a grounded search query that asks for products with full titles, cached rows from the old query searched again, a `titles_prompt` rule against store names, a `drop_stores` filter that removes a title equal to a known store's name or containing its domain, and `com` as a stopword; extended after the first live check so the parse returns each title's brand and model and `missing` leaves out rival brand and model names and competitor names; with the rulings made during the build. |
| [superpowers/plans/2026-09-29-slice20-product-titles-not-stores.md](superpowers/plans/2026-09-29-slice20-product-titles-not-stores.md) | Implementation plan, Tasks 1–5 (Tasks 4–5: the rival brand and model exclusion), with the changes made during execution. |
| [findings-slice20.md](findings-slice20.md) | Results: what was built (including the rival brand and model exclusion), both live checks on dev (both run on 2026-09-29), and what is deferred or untested. |
| [superpowers/specs/2026-09-29-slice21-suggestion-quality-design.md](superpowers/specs/2026-09-29-slice21-suggestion-quality-design.md) | Design spec: product-suggestion quality after slice 20's second live check — the parse asks for models without the product type, a keyword guard on exclusions, colour and size words never suggested, a parse version on cached titles, and the rule check dropping words the rewrite invents; with the rulings made during the build. |
| [superpowers/plans/2026-09-29-slice21-suggestion-quality.md](superpowers/plans/2026-09-29-slice21-suggestion-quality.md) | Implementation plan, Tasks 1–3, with the changes made during execution. |
| [findings-slice21.md](findings-slice21.md) | Results: what was built, the live check on dev (run on 2026-09-29), and what is deferred or untested. |
| [superpowers/specs/2026-09-29-slice22-backed-missing-words-design.md](superpowers/specs/2026-09-29-slice22-backed-missing-words-design.md) | Design spec: missing words backed by product data after slice 21's live check — a missing word must be backed by the product's keyword, description, category or attribute values and appear in more than half of the ranking titles; with the rulings made during the build. |
| [superpowers/plans/2026-09-29-slice22-backed-missing-words.md](superpowers/plans/2026-09-29-slice22-backed-missing-words.md) | Implementation plan, Tasks 1–3, with the changes made during execution. |
| [findings-slice22.md](findings-slice22.md) | Results: what was built, the live check on dev (run on 2026-09-29), and what is deferred or untested. |
| [superpowers/specs/2026-09-30-slice23-keyword-title-type-design.md](superpowers/specs/2026-09-30-slice23-keyword-title-type-design.md) | Design spec: the searched keyword when a product's title and category name different types — colour and size keywords are dropped before the vote, and the first keyword's audience joins the title's type ("men flip flops"); with the four probes of the keyword prompt. |
| [superpowers/plans/2026-09-30-slice23-keyword-title-type.md](superpowers/plans/2026-09-30-slice23-keyword-title-type.md) | Implementation plan, Tasks 1–4, with the changes made during execution. |
| [findings-slice23.md](findings-slice23.md) | Results: what was built, the four probes, the live check on dev (run on 2026-09-30), and what is deferred or untested. |
| [superpowers/specs/2026-09-30-slice24-keyword-cache-key-design.md](superpowers/specs/2026-09-30-slice24-keyword-cache-key-design.md) | Design spec: one cached search per keyword phrase across runs — the run's spelling merge is seeded from the brand's fresh cache rows, so a product adopts the cached spelling and its search is reused; no migration. |
| [superpowers/plans/2026-09-30-slice24-keyword-cache-key.md](superpowers/plans/2026-09-30-slice24-keyword-cache-key.md) | Implementation plan, Tasks 1–2, with the changes made during execution. |
| [findings-slice24.md](findings-slice24.md) | Results: what was built, the live check on dev (run on 2026-09-30), and what is deferred or untested. |
| [superpowers/specs/2026-09-30-slice25-raw-samples-design.md](superpowers/specs/2026-09-30-slice25-raw-samples-design.md) | Design spec: store the raw keyword samples and the raw rewrite — `product.keyword_samples` (JSONB) and `product.raw_title` (migration 0021), written by each product run and read with psql, so live checks stop inferring them; with the ruling made during the build. |
| [superpowers/plans/2026-09-30-slice25-raw-samples.md](superpowers/plans/2026-09-30-slice25-raw-samples.md) | Implementation plan, Tasks 1–3, with the changes made during execution. |
| [findings-slice25.md](findings-slice25.md) | Results: what was built, the live check on dev (run on 2026-09-30), and what is deferred or untested. |
| [superpowers/specs/2026-09-30-slice26-rewrite-plural-design.md](superpowers/specs/2026-09-30-slice26-rewrite-plural-design.md) | Design spec: a removed repeat no longer counts as an adjustment — `rule_check` gives `pass` when the only change to the suggestion is removing words that repeat an earlier word's stem; the rewrite prompt is unchanged, with the two failed prompt probes in the appendix. |
| [superpowers/plans/2026-09-30-slice26-rewrite-plural.md](superpowers/plans/2026-09-30-slice26-rewrite-plural.md) | Implementation plan, Tasks 1–2, with the changes made during execution. |
| [findings-slice26.md](findings-slice26.md) | Results: what was built, the two prompt probes, the live check on dev (run on 2026-09-30), and what is deferred or untested. |
| [superpowers/specs/2026-09-30-slice27-overlap-restore-design.md](superpowers/specs/2026-09-30-slice27-overlap-restore-design.md) | Design spec: the rewrite prompt's `missing` field leaves out words already in the product's keyword, and `rule_check` puts back original-title words the rewrite dropped (status `adjusted`), with the approved ceilings. |
| [superpowers/plans/2026-09-30-slice27-overlap-restore.md](superpowers/plans/2026-09-30-slice27-overlap-restore.md) | Implementation plan, Tasks 1–2, with the changes made during execution. |
| [findings-slice27.md](findings-slice27.md) | Results: what was built, the live check on dev (run on 2026-10-01), and what is deferred or untested. |
| [superpowers/specs/2026-10-01-keyword-search-cleanup-design.md](superpowers/specs/2026-10-01-keyword-search-cleanup-design.md) | Design spec, written after the fact: the one-off delete of the 11 `keyword_search` rows on dev that no run could use, with rulings R1–R13. |
| [superpowers/specs/2026-10-01-slice28-seed-tests-design.md](superpowers/specs/2026-10-01-slice28-seed-tests-design.md) | Design spec: three integration tests pin the slice 24 seed's error filter, its newest-first order and its use for every keyword; tests only, with rulings R1–R12. |
| [superpowers/plans/2026-10-01-slice28-seed-tests.md](superpowers/plans/2026-10-01-slice28-seed-tests.md) | Implementation plan, Tasks 1–2, with the changes made during execution. |
| [findings-slice28.md](findings-slice28.md) | Results: what was built, the red and green runs, no live check (tests only), and what is deferred or untested. |

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
