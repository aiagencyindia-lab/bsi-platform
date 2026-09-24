# Findings: slice 11 — URL optimizer and AI Citability Score

## 1. What was built
(one paragraph: pages.py, optimize_url job, page_audit, optimize_page rule, routes, tabs)

## 2. Live check
(to be filled after the live check: brand, cluster, URL, score, components table, top suggestions, spend; run read-only via scripts/score_page.py)

## 3. Calibration notes
(to be filled after the live check: COS_FLOOR / COS_SPAN / COS_COVERED against the real cosines seen)

## 4. Deferred
- Competitor pages are cited, not fetched.
- brand_urls are not scored automatically.
- No judge call; entity coverage is name matching.
- No per-engine score; no scheduled re-scoring.
- URLs are not restricted to declared domains (SSRF guard is the boundary).
- Threshold 70 and weights v1 are first guesses.
