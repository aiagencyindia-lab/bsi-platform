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
| [superpowers/specs/2026-10-01-slice28-seed-tests-design.md](superpowers/specs/2026-10-01-slice28-seed-tests-design.md) | Design spec: three integration tests pin the slice 24 seed's error filter, its newest-first order and its use for every keyword; tests only, with rulings R1–R14. |
| [superpowers/plans/2026-10-01-slice28-seed-tests.md](superpowers/plans/2026-10-01-slice28-seed-tests.md) | Implementation plan, Tasks 1–2, with the changes made during execution. |
| [findings-slice28.md](findings-slice28.md) | Results: what was built, the red and green runs, no live check (tests only), and what is deferred or untested. |
| [superpowers/specs/2026-10-01-slice29-stale-rows-design.md](superpowers/specs/2026-10-01-slice29-stale-rows-design.md) | Design spec: a product run deletes the brand's stale `keyword_search` rows at its start (`searched_at <= fresh_after`), so no old spelling stays once stale; no migration, with rulings R1–R10. |
| [superpowers/plans/2026-10-01-slice29-stale-rows.md](superpowers/plans/2026-10-01-slice29-stale-rows.md) | Implementation plan, Tasks 1–2, with the changes made during execution. |
| [findings-slice29.md](findings-slice29.md) | Results: what was built, the red and green runs, no live check in this slice (one was run on 2026-10-06, after slice 43: it deleted the stale "navy flip flops" row and re-searched 7 keywords for $0.28), and what is deferred or untested. |
| [superpowers/specs/2026-10-01-slice30-audit-labels-design.md](superpowers/specs/2026-10-01-slice30-audit-labels-design.md) | Design spec: the SEO report's site audit codes read from a hand-written `AUDIT_LABEL` table (keeping any ":" suffix), methodology v3, with rulings R1–R12. |
| [superpowers/plans/2026-10-01-slice30-audit-labels.md](superpowers/plans/2026-10-01-slice30-audit-labels.md) | Implementation plan, Tasks 1–2, with the changes made during execution. |
| [findings-slice30.md](findings-slice30.md) | Results: what was built, the red and green runs, no live check (tests pin the cells), and what is deferred or untested. |
| [superpowers/specs/2026-10-01-slice31-public-rate-limit-design.md](superpowers/specs/2026-10-01-slice31-public-rate-limit-design.md) | Design spec: the public share-link routes allow 60 requests per 60-second window per share token (page and PDF together), then `429` with `Retry-After`, counted in the API process; the PDF proxy passes the 429 through, with rulings R1–R14. |
| [superpowers/plans/2026-10-01-slice31-public-rate-limit.md](superpowers/plans/2026-10-01-slice31-public-rate-limit.md) | Implementation plan, Tasks 1–3, with the changes made during execution. |
| [findings-slice31.md](findings-slice31.md) | Results: what was built, the red and green runs, the live check on dev (to run after merge), and what is deferred or untested. |
| [superpowers/specs/2026-10-01-slice32-webhook-signing-design.md](superpowers/specs/2026-10-01-slice32-webhook-signing-design.md) | Design spec: a per-brand, write-only webhook signing secret (migration 0022); each alert POST carries `X-BSI-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 over "{t}." + body>`; `http_fetch` takes caller headers that cannot override its pinned ones, with rulings R1–R11. |
| [superpowers/plans/2026-10-01-slice32-webhook-signing.md](superpowers/plans/2026-10-01-slice32-webhook-signing.md) | Implementation plan, Tasks 1–4, with the changes made during execution. |
| [findings-slice32.md](findings-slice32.md) | Results: what was built, the receiver contract, the red and green runs, the dev migration to 0022 and the API live check, and what is deferred or untested. |
| [superpowers/specs/2026-10-01-slice33-es-folding-design.md](superpowers/specs/2026-10-01-slice33-es-folding-design.md) | Design spec: `rivals._stem` folds -es plurals after ch, sh, x, ss and zz and keeps ss-final words whole; `_allowed_stems` keeps its one-sided set; named limits (caches, mousses, quizzes), with rulings R1–R10. |
| [superpowers/plans/2026-10-01-slice33-es-folding.md](superpowers/plans/2026-10-01-slice33-es-folding.md) | Implementation plan, Tasks 1–2, with the changes made during execution. |
| [findings-slice33.md](findings-slice33.md) | Results: what was built, the effects on folding and cached searches, the red and green runs, the read-only live check on dev's rival pages, and what is deferred or untested. |
| [superpowers/specs/2026-10-01-slice34-axes-guard-test-design.md](superpowers/specs/2026-10-01-slice34-axes-guard-test-design.md) | Design spec: a unit test pins `rivals._stem`'s `len(word) > 4` guard on the -es rule (axes → axe, shes → she); a mutation run is the red evidence; the results are in this spec and in PR #65, with rulings R1–R5. |
| [superpowers/plans/2026-10-01-slice34-axes-guard-test.md](superpowers/plans/2026-10-01-slice34-axes-guard-test.md) | Implementation plan, Task 1 (one test), with the changes made during execution. |
| [superpowers/specs/2026-10-01-slice35-sweep-test-design.md](superpowers/specs/2026-10-01-slice35-sweep-test-design.md) | Design spec: a unit test pins the rate limiter's once-per-window sweep (slice 31 R10) by the identity of its key map; a mutation run is the red evidence; the results are in this spec, the plan's execution note and PR #67, with rulings R1–R9. |
| [superpowers/plans/2026-10-01-slice35-sweep-test.md](superpowers/plans/2026-10-01-slice35-sweep-test.md) | Implementation plan, Task 1 (one test), with the changes made during execution. |
| [superpowers/specs/2026-10-02-slice36-limiter-tests-design.md](superpowers/specs/2026-10-02-slice36-limiter-tests-design.md) | Design spec: a unit test pins the rate limiter's lock (two checks on one key do not interleave between the read and the write) and an integration test pins an unknown share token's own budget; a mutation run is the red evidence; the results are in this spec, the plan's execution section and PR #69, with rulings R1–R17. |
| [superpowers/plans/2026-10-02-slice36-limiter-tests.md](superpowers/plans/2026-10-02-slice36-limiter-tests.md) | Implementation plan, Task 1 (two tests), with the changes made during execution. |
| [superpowers/specs/2026-10-02-slice37-serp-audit-design.md](superpowers/specs/2026-10-02-slice37-serp-audit-design.md) | Design spec: DataForSEO live first pages for `{brand}` and `{brand} reviews`, rule-based result types, the ownership share, the `serp_audit` table, the `audit_serp` job, two routes and the Brand SERP page; the results are in docs/findings-slice37.md, with rulings R1–R30 and a dated process note. |
| [superpowers/plans/2026-10-02-slice37-serp-audit.md](superpowers/plans/2026-10-02-slice37-serp-audit.md) | Implementation plan, Tasks 1–6 (classifier, adapter, table, job, routes, page), with the changes made during execution. |
| [findings-slice37.md](findings-slice37.md) | Results: what was built, the gates and reviews, the live check (first written as not run; three attempts on 2026-10-03, none returned a page: credentials, then account verification, then a provider pause; on 2026-10-05 a fourth timed out at 15 s and a fifth, on slice 41's 120 s timeout, returned pages), the deferred, parked and untested items, rulings R12–R21, and the 2026-10-03 process audit. |
| [superpowers/specs/2026-10-03-slice38-serp-error-codes-design.md](superpowers/specs/2026-10-03-slice38-serp-error-codes-design.md) | Design spec: the DataForSEO adapter reads the provider's error code from a non-2xx answer, maps 40104 and 40201, and accepts a status only as a plain integer from 0 to 99999; a mutation run is the red evidence; the results are in this spec, the plan's execution section and PR #74, with rulings R1–R12. |
| [superpowers/plans/2026-10-03-slice38-serp-error-codes.md](superpowers/plans/2026-10-03-slice38-serp-error-codes.md) | Implementation plan, Tasks 1–2 (adapter and tests; page labels), with the changes made during execution. |
| [superpowers/specs/2026-10-03-slice39-serp-cost-cap-design.md](superpowers/specs/2026-10-03-slice39-serp-cost-cap-design.md) | Design spec: the DataForSEO adapter accepts a call's cost only as a plain number from 0 to $1, so no provider cost can overflow the Integer cost columns; the tick comment describes the stale paths; a mutation run is the red evidence; the results are in this spec, the plan's execution section and PR #76, with rulings R1–R15 and the deferred minors. |
| [superpowers/plans/2026-10-03-slice39-serp-cost-cap.md](superpowers/plans/2026-10-03-slice39-serp-cost-cap.md) | Implementation plan, Task 1 (adapter, tests and the tick comment, in two commits), with the changes made during execution. |
| [superpowers/specs/2026-10-03-slice40-serp-code-on-bad-cost-design.md](superpowers/specs/2026-10-03-slice40-serp-code-on-bad-cost-design.md) | Design spec: a DataForSEO answer with a provider error code keeps the code and records cost 0 when its cost is bad; a success with a bad cost is still json; a mutation run is the red evidence; the results are in this spec, the plan's execution section and PR #80, with rulings R1–R14 and the deferred minors. |
| [superpowers/plans/2026-10-03-slice40-serp-code-on-bad-cost.md](superpowers/plans/2026-10-03-slice40-serp-code-on-bad-cost.md) | Implementation plan, Task 1 (adapter and tests), with the changes made during execution. |
| [superpowers/specs/2026-10-05-slice41-serp-timeout-design.md](superpowers/specs/2026-10-05-slice41-serp-timeout-design.md) | Design spec: the DataForSEO live call waits up to 120 s (http_fetch gains deadline_seconds and phase_seconds), a read timeout is recorded as timeout at the expected price, and an audit covers one locale; the 2026-10-05 live check that found the 15 s timeout; a mutation run is the red evidence, with rulings R1–R19 and the deferred minors; the results are in this spec, the plan's execution section, findings-slice37 §2 and PR #82. |
| [superpowers/plans/2026-10-05-slice41-serp-timeout.md](superpowers/plans/2026-10-05-slice41-serp-timeout.md) | Implementation plan, Tasks 1–3 (http_fetch; adapter and worker; page label), with the changes made during execution. |
| [superpowers/specs/2026-10-05-slice42-deferred-minors-design.md](superpowers/specs/2026-10-05-slice42-deferred-minors-design.md) | Design spec: slice 41's three deferred minors: http_fetch's timeout message reports the deadline in force, a test drives a real ReadTimeout through http_fetch into serp(), and the SERP_JOB_MICROS comment states the observed price; a mutation run is the red evidence, with rulings R1–R9 and the deferred minors; the results are in this spec, the plan's execution section and PR #84. |
| [superpowers/plans/2026-10-05-slice42-deferred-minors.md](superpowers/plans/2026-10-05-slice42-deferred-minors.md) | Implementation plan, Tasks 1–2 (the timeout message; the end-to-end test and the worker comment), with the changes made during execution. |
| [superpowers/specs/2026-10-06-slice43-weekly-serp-schedule-design.md](superpowers/specs/2026-10-06-slice43-weekly-serp-schedule-design.md) | Design spec: the worker queues a Brand SERP audit weekly for every active brand with a declared domain (migration 0024's due_serp_audits() and the queue_due_serp_audits() sweep), retrying a failed audit once a day at most, stopping after three failed jobs in a week (a partial success is retried daily), and queueing nothing while the budget has no room; a red/green run and a mutation table are the evidence, with rulings R1–R10 and the deferred minors. |
| [superpowers/plans/2026-10-06-slice43-weekly-serp-schedule.md](superpowers/plans/2026-10-06-slice43-weekly-serp-schedule.md) | Implementation plan, Tasks 1–3 (migration 0024 and the due-rule tests; the worker sweep; the page sentence), with the changes made during execution. |
| [findings-slice43.md](findings-slice43.md) | Results: the weekly Brand SERP schedule (migration 0024's due_serp_audits() and the worker's queue_due_serp_audits()), the gates and reviews, the live check (run 2026-10-06: dev migrated to 0024, one brand due, one job queued and done for $0.006, then none due), and every ruling (R1–R15) and deferred minor, quoted from the ledger. |
| [superpowers/specs/2026-10-06-slice44-serp-drop-alert-design.md](superpowers/specs/2026-10-06-slice44-serp-drop-alert-design.md) | Design spec: the Brand SERP drop alert (`serp_drop`, migration 0025): a fourth detector in the daily alert scan fires when the brand's own-site organic results on two later pages are both below a baseline page, each page at least a day apart and with the same query and locale; a red/green run and a mutation table are the evidence, with rulings R1–R7 and the deferred minors. |
| [superpowers/plans/2026-10-06-slice44-serp-drop-alert.md](superpowers/plans/2026-10-06-slice44-serp-drop-alert.md) | Implementation plan, Tasks 1–3 (the serp_drop type: migration 0025, ALERT_TYPES, the report label; detect_serp_drop and its tests; the web label and link), with the changes made during execution. |
| [findings-slice44.md](findings-slice44.md) | Results: the Brand SERP drop alert (`serp_drop`, migration 0025, `detect_serp_drop` in the daily scan), the gates and reviews, no live check in this slice, and every ruling (R1–R8) and deferred minor, quoted from the ledger. |
| [superpowers/specs/2026-10-07-slice45-serp-audit-index-design.md](superpowers/specs/2026-10-07-slice45-serp-audit-index-design.md) | Design spec: migration 0026 adds `ix_serp_audit_brand_fetched` on `serp_audit (brand_id, fetched_at)`, the index the slice 44 final review deferred; a red/green run and a mutation table are the evidence, with rulings R1–R6 and the deferred minors. |
| [superpowers/plans/2026-10-07-slice45-serp-audit-index.md](superpowers/plans/2026-10-07-slice45-serp-audit-index.md) | Implementation plan, Task 1 (migration 0026, the model Index, the alerts.py comment and the index test), with the changes made during execution. |
| [findings-slice45.md](findings-slice45.md) | Results: the serp_audit (brand_id, fetched_at) index (migration 0026), the gates and reviews, no live check, and every ruling (R1–R7) and deferred minor, quoted from the ledger. |
| [superpowers/specs/2026-10-07-slice46-serp-sweep-budget-design.md](superpowers/specs/2026-10-07-slice46-serp-sweep-budget-design.md) | Design spec: the weekly SERP sweep counts the org's queued and running audit_serp jobs against the budget at their full estimate, so one sweep does not queue past the budget (the slice 43 deferred minor; R1 names the race with a manual press); a red/green run and a mutation table are the evidence, with rulings R1–R5 and the deferred minors. |
| [superpowers/plans/2026-10-07-slice46-serp-sweep-budget.md](superpowers/plans/2026-10-07-slice46-serp-sweep-budget.md) | Implementation plan, Task 1 (the waiting-job count in queue_due_serp_audits and its three tests), with the changes made during execution. |
| [findings-slice46.md](findings-slice46.md) | Results: the SERP sweep counts waiting audit_serp jobs against the budget (the slice 43 minor, found overstated), the gates and reviews, no live check, and every ruling (R1–R6) and deferred minor, quoted from the ledger. |
| [superpowers/specs/2026-10-07-slice47-serp-schedule-line-design.md](superpowers/specs/2026-10-07-slice47-serp-schedule-line-design.md) | Design spec: the Brand SERP page shows "Audited automatically once a week." only for an active brand with a declared domain, and otherwise says why (archived, or no declared domain), from a web helper (the slice 43 deferred minor); a red/green run and a mutation table are the evidence, with rulings R1–R9 and the deferred minors. |
| [superpowers/plans/2026-10-07-slice47-serp-schedule-line.md](superpowers/plans/2026-10-07-slice47-serp-schedule-line.md) | Implementation plan, Task 1 (serpSchedule, the Domain type, the page's fetches and the vitest), with the changes made during execution. |
| [findings-slice47.md](findings-slice47.md) | Results: the Brand SERP page's schedule line (the slice 43 minor), the gates and reviews, no live check, and every ruling (R1–R9) and deferred minor, quoted from the ledger. |
| [superpowers/specs/2026-10-07-slice48-add-domain-form-design.md](superpowers/specs/2026-10-07-slice48-add-domain-form-design.md) | Design spec: an add-domain form (visible label, a browser pattern, a spend warning) on the Brand SERP page for an active brand with no declared domain, posting to the existing domains API from a server action (the slice 47 deferred minor); a red/green run and a mutation table are the evidence, with rulings R1–R8 and the deferred minors. |
| [superpowers/plans/2026-10-07-slice48-add-domain-form.md](superpowers/plans/2026-10-07-slice48-add-domain-form.md) | Implementation plan, Task 1 (addDomain, the page's form and the two action tests), with the changes made during execution. |
| [findings-slice48.md](findings-slice48.md) | Results: the add-domain form (the slice 47 minor), the gates and reviews, no live check, and every ruling (R1–R8) and deferred minor, quoted from the ledger. |
| [superpowers/specs/2026-10-07-slice49-api-path-guard-design.md](superpowers/specs/2026-10-07-slice49-api-path-guard-design.md) | Design spec: seg() (one path segment of letters, digits, '-' and '_') on every value interpolated into an API path in the web app, plus an api()/publicApi() guard that refuses a path fetch would not send as written, and a source-scan test (the slice 48 deferred minor); a red/green run and a mutation table are the evidence, with rulings R1–R13, two corrections and the deferred minors. |
| [superpowers/plans/2026-10-07-slice49-api-path-guard.md](superpowers/plans/2026-10-07-slice49-api-path-guard.md) | Implementation plan, Tasks 1 (the guard and seg() with their tests) and 2 (the scan test and seg() in 28 call-site files), with the changes made during execution. |
| [findings-slice49.md](findings-slice49.md) | Results: seg() on every API path value and the api() guard (the slice 48 minor), the gates and reviews, no live check, and every ruling (R1–R13), correction and deferred minor, quoted from the ledger. |
| [superpowers/specs/2026-10-07-slice50-refusal-log-cap-design.md](superpowers/specs/2026-10-07-slice50-refusal-log-cap-design.md) | Design spec: the two refusal log lines in the web app's api.ts print the value JSON-quoted (C0 control characters escaped) and capped at 200 code units, plus its full length (the slice 49 deferred minor); a red/green run and a mutation table are the evidence, with rulings R1–R6, one correction and the deferred minors. |
| [superpowers/plans/2026-10-07-slice50-refusal-log-cap.md](superpowers/plans/2026-10-07-slice50-refusal-log-cap.md) | Implementation plan, Task 1 (shown(), the two log lines and their tests), with the changes made during execution. |
| [findings-slice50.md](findings-slice50.md) | Results: quoted, capped refusal logs with the length (the slice 49 minor), the gates and reviews, no live check, and every ruling (R1–R6), correction and deferred minor, quoted from the ledger. |
| [superpowers/specs/2026-10-07-slice51-guard-log-content-test-design.md](superpowers/specs/2026-10-07-slice51-guard-log-content-test-design.md) | Design spec: the guard's long-path log test uses a path with a double quote and asserts the exact 200-character logged text (the slice 50 deferred minor); a mutation table with the old and new test is the evidence, with rulings R1–R9, one correction and the deferred minors. |
| [superpowers/plans/2026-10-07-slice51-guard-log-content-test.md](superpowers/plans/2026-10-07-slice51-guard-log-content-test.md) | Implementation plan, Task 1 (the one test), with the changes made during execution. |
| [findings-slice51.md](findings-slice51.md) | Results: the guard's long-path log test checks the logged text (the slice 50 minor), the gates and reviews, no live check, and every ruling (R1–R9), correction and deferred minor, quoted from the ledger. |
| [findings-slice52.md](findings-slice52.md) | Results: the guard's long-path log test pins one console.error call (the slice 51 minor), bounded path with no spec or plan file, the gates and reviews, no live check, and every ruling (R1–R4) and deferred minor, quoted from the ledger. |
| [findings-slice53.md](findings-slice53.md) | Results: the slice 49 and slice 50 spec mutation tables escape the `\|` inside their cells so they render, docs only, bounded path, and every ruling (R1–R4), quoted from the ledger. |
| [findings-slice54.md](findings-slice54.md) | Results: a refused (422) or duplicate (409) domain from the Brand SERP add-domain form shows a note instead of the error page (the slice 48 minor, reversing the slice 48 decision with the user's approval), bounded path, the gates and reviews, no live check, and every ruling (R2–R4) and deferred minor, quoted from the ledger. |
| [superpowers/specs/2026-10-08-slice55-serp-schedule-reasons-design.md](superpowers/specs/2026-10-08-slice55-serp-schedule-reasons-design.md) | Design spec: the Brand SERP audits response gains serp_configured and failed_7d, and the page's schedule line says when the weekly sweep skips the brand for missing DataForSEO credentials or three failed audits in 7 days (two of the slice 47 out-of-scope cases); a mutation table is the evidence, with rulings R1–R7 and the deferred minors. |
| [superpowers/plans/2026-10-08-slice55-serp-schedule-reasons.md](superpowers/plans/2026-10-08-slice55-serp-schedule-reasons.md) | Implementation plan, Tasks 1 (the API fields and their tests) and 2 (the schedule line), generated from a scratchpad proof, with the changes made during execution. |
| [findings-slice55.md](findings-slice55.md) | Results: the schedule line names two of the sweep's three skip reasons (budget room still not shown), the gates, CI and reviews, no live check, and every ruling (R1–R7) and deferred minor, quoted from the ledger. |
| [superpowers/specs/2026-10-08-slice56-engine-replacement-design.md](superpowers/specs/2026-10-08-slice56-engine-replacement-design.md) | Design spec: a spend-guarded probe of the replacements Google lists for the retiring gemini-2.5-flash engine, a pick rule fixed in advance, price rows, the switch, and a guard so deltas, alerts and task impact never compare two engine models; with rulings R1–R9, four corrections and the deferred minors. |
| [superpowers/plans/2026-10-08-slice56-engine-replacement.md](superpowers/plans/2026-10-08-slice56-engine-replacement.md) | Implementation plan: Task 1 (prices, the probe script, the guard) from a scratchpad proof, the probe run, and the Task 2 addendum (the switch) written after the probe, with the changes made during execution. |
| [findings-slice56.md](findings-slice56.md) | Results: the probe (3.5-flash-lite searched 20 of 20 at $0.0300 per observation), the switch to gemini-3.5-flash-lite, the gates and reviews, the probe as the live check, and every ruling (R1–R9), correction and deferred minor, quoted from the ledger. |

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
