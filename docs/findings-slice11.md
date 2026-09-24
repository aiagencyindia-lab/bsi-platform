# Findings: slice 11 — URL optimizer and AI Citability Score

## 1. What was built
`packages/core/bsi_core/pages.py` parses a fetched page (title, meta, JSON-LD, headings, sections, links, tables, lists) and scores it against one gap cluster with score v1: nine weighted components and suggestions (add, remove, rewrite, evidence to add), each citing prompt ids, observation ids or URLs. Migration 0014 adds the tenant table `page_audit` and the recommendation type `optimize_page`. The worker job `optimize_url` makes one fetch and one embed call per run and is budget-gated at `PAGE_JOB_MICROS`. The `_pages` recommendation rule fires when the latest score is under 70 (feasibility 0.6, impact measured on the cluster's prompts). The API exposes `/v1/brands/{id}/pages` routes to queue a score, list the latest audit per URL and read one audit. The web app adds a score-a-URL form on the Clusters tab and a Pages tab. `scripts/score_page.py` scores a page read-only.

## 2. Live check
(to be filled after the live check: brand, cluster, URL, score, components table, top suggestions, spend; run read-only via scripts/score_page.py)

## 3. Calibration notes
(to be filled after the live check: COS_FLOOR / COS_SPAN / COS_COVERED against the real cosines seen)

## 4. Deferred / decisions
- Competitor pages are cited, not fetched.
- brand_urls are not scored automatically.
- No judge call; entity coverage is name matching.
- No per-engine score; no scheduled re-scoring.
- URLs are not restricted to declared domains (SSRF guard is the boundary).
- Threshold 70 and weights v1 are first guesses.
- No `final_url` column: `crawl.http_fetch` does not return the post-redirect URL, so a redirected page is stored under the requested URL.
- `<header>`/`<footer>` are skipped only outside `<article>`, `<main>` and `<section>`.
- Evidence counts distinct cited domains; `www.` is collapsed for other third-party links.
- When a cluster has no absent answers, suggestions cite its prompt ids instead of observations.
- Rival pages appear in evidence-to-add as pages to study, not to link; rival links never count as evidence.
- The audited page's own host counts as a brand host, so scoring a rival's URL scores it as if it were the brand's.
- A newer failed fetch does not replace an older score; the open rec stays on the last scored audit.
- Reach is frozen at scoring time (observation ids captured then).
- `clusters()` runs on every POST, in the worker, and again in `refresh()`.
- `subject_key` embeds the URL; a pathologically long URL could exceed the index limit.
- An open `create_content` rec and an `optimize_page` rec can both be open for the same gap; whether one should yield is a product decision for a later slice.
- Parser limits: unclosed tags hide or merge text; h4–h6 are not headings; byline match is a substring; protocol-relative and upper-case-scheme links are not counted.
