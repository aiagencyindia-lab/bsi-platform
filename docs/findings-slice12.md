# Findings: slice 12 — competitor site crawl

## 1. What was built
`packages/core/bsi_core/rivals.py` snapshots one competitor domain: it reads robots.txt (5xx or unreachable stops the crawl; 4xx means no restrictions), follows the declared sitemaps or `/sitemap.xml` through a sitemap index to 11 sitemap files in all, then fetches the homepage and up to 10 URLs not seen before, newest `<lastmod>` first, and records the JSON-LD `@type`s on each. Every fetch after robots.txt obeys its `*` group, and any cap, cut-off body, fetch error or non-sitemap root marks the snapshot incomplete. Migration 0015 adds the tenant tables `rival_crawl` (with a `baseline` flag) and `rival_page`, and the SECURITY DEFINER function `due_rival_crawls()`, which lists brands whose competitors' declared domains have no crawl in 7 days. The worker job `crawl_rivals` is queued weekly from it, runs within a 420 s fetch budget and costs nothing (`JOB_ESTIMATES["crawl_rivals"] = 0`). `site_changes` lists, per active competitor, the pages and structured-data types first seen in the last 14 days and each declared domain's latest crawl, and `feed_evidence` adds `new_pages` and `new_types` to the visibility change feed. The API exposes `POST /v1/brands/{id}/competitors/crawl` to queue a crawl and `GET /v1/brands/{id}/competitors/site-changes` to read the changes. The web app adds a site-changes section to the Competitors tab. `scripts/snapshot_rival.py` snapshots domains read-only.

## 2. Live check
(to be filled after the live check: per domain — URLs, complete, errors, fetches, sampled types)

## 3. Deferred / decisions
- Removed URLs and lastmod changes are not reported; a domain's first crawl is a baseline.
- gzip sitemaps served without Content-Encoding are marked incomplete, not unzipped.
- A sitemap index is read to 11 files in all; counts are lower bounds when `complete` is false.
- robots.txt 5xx or unreachable: nothing crawled; 4xx: no restrictions (RFC 9309 §2.3.1).
- Pages are fetched with a browser user agent while obeying the `*` robots group.
- No recommendations from site changes; no topic matching of rival pages to clusters.
- Feed entries are still computed on read, not stored; no alerts (F15).
- Feed evidence uses two statements (pages, types) per feed.
- `rival_crawl.baseline` added (not in the spec) so types first seen on a baseline crawl never count as new.
