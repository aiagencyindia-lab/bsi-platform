# Findings: slice 11 — URL optimizer and AI Citability Score

## 1. What was built
`packages/core/bsi_core/pages.py` parses a fetched page (title, meta, JSON-LD, headings, sections, links, tables, lists) and scores it against one gap cluster with score v1: nine weighted components and suggestions (add, remove, rewrite, evidence to add), each citing prompt ids, observation ids or URLs. Migration 0014 adds the tenant table `page_audit` and the recommendation type `optimize_page`. The worker job `optimize_url` makes one fetch and one embed call per run and is budget-gated at `PAGE_JOB_MICROS`. The `_pages` recommendation rule fires when the latest score is under 70 (feasibility 0.6, impact measured on the cluster's prompts). The API exposes `/v1/brands/{id}/pages` routes to queue a score, list the latest audit per URL and read one audit. The web app adds a score-a-URL form on the Clusters tab and a Pages tab. `scripts/score_page.py` scores a page read-only.

## 2. Live check
Run 1 (`BSOAgentTestBrand`), cluster `recommendation: school shoes` (2 prompts, 10 absent answers), read-only via `scripts/score_page.py`; dev's `page_audit`, `recommendation`, `task` and job queue stayed at 0 rows. Spend: 277 + 1,361 = 1,638 micros ($0.0016).

**Page A**: the indiatimes.com article that Run 1's answers cite for this cluster (fetched through its grounding redirect). HTTP 200, score **65 / 100**.

| Component | Points | Observed |
|---|---|---|
| topic_coverage | 24.82 / 25 | 2 of 2 prompts covered |
| evidence | 9.0 / 15 | 1 cited domain linked, 13 other third-party domains |
| intent_fit | 10 / 10 | best-of round-up: list yes, ≥ 3 H2 yes |
| entity_coverage | 0 / 10 | brand not named (it is not the brand's page) |
| structure | 10 / 10 | 1 H1, 10 H2, 1,639 words |
| faqs | 0 / 10 | no FAQ |
| direct_answers | 6 / 10 | 6 of 10 H2 sections |
| author_attribution | 5 / 5 | author found |
| tables | 0 / 5 | no table |

Suggestions: add an FAQ with FAQPage schema; add a table; name the brand in the title or H1; 9 evidence-to-add entries.

**Page B (control)**: `https://en.wikipedia.org/wiki/Photosynthesis`, an unrelated page. Score **49 / 100**, with topic_coverage **0.51** and "1 of 2 prompts covered".

Two problems the live check found:
1. **Topic coverage is miscalibrated.** An unrelated page covers half the cluster, so `COS_FLOOR = 0.55` and `COS_COVERED = 0.70` sit below the similarity `gemini-embedding-001` gives unrelated text. See §3.
2. **Evidence-to-add shows opaque URLs.** Every stored `citation.url` is a `vertexaisearch.cloud.google.com/grounding-api-redirect/…` link. The domain is real (`citation.domain`), but the URL in the suggestion text tells the operator nothing.

Smaller: the site's own chrome headings ("TOI", "Photostories", "Featured In lifestyle") count as H2 sections, so `direct_answers` asks for direct answers under them.

## 3. Calibration notes
The two pages bracket the problem. The matching article scored a mean mapped value of 0.99 (both best cosines ≈ 0.85 or above). The unrelated page still scored 0.51, with one prompt above the 0.70 "covered" line. The constants were set from the slice-4 probe's rough bands (unrelated ≈ 0.5, paraphrase ≈ 0.8), which were measured on short prompt-to-prompt pairs. Prompt-to-section pairs with `SEMANTIC_SIMILARITY` embeddings sit higher. The per-query cosines were not printed, so the exact floor needs one more probe that prints them for a matching page and a few unrelated ones (≈ $0.003). Until then, topic coverage should be read as an upper bound.

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
