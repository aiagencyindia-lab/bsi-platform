# Findings: slice 12 — competitor site crawl

## 1. What was built
`packages/core/bsi_core/rivals.py` snapshots one competitor domain: it reads robots.txt (5xx or unreachable stops the crawl; 4xx means no restrictions), follows the declared sitemaps or `/sitemap.xml` through a sitemap index to 11 sitemap files in all, then fetches the homepage and up to 10 URLs not seen before, newest `<lastmod>` first, and records the JSON-LD `@type`s on each. Every fetch after robots.txt obeys its `*` group, and any sitemap cap, cut-off sitemap, sitemap fetch error, non-sitemap root, sitemap disallowed by robots.txt or `Disallow: /` marks the snapshot incomplete; page fetch errors show only as each page's status. A domain that runs out of the job's time as its first domain is stored as an incomplete crawl with an "out of time" error. Migration 0015 adds the tenant tables `rival_crawl` (with a `baseline` flag) and `rival_page`, and the SECURITY DEFINER function `due_rival_crawls()`, which lists brands whose competitors' declared domains have no crawl in 7 days. The worker job `crawl_rivals` is queued weekly from it, runs within a 420 s fetch budget and costs nothing (`JOB_ESTIMATES["crawl_rivals"] = 0`). `site_changes` lists, per active competitor, the pages and structured-data types first seen in the last 14 days and each declared domain's latest crawl, and `feed_evidence` adds `new_pages` and `new_types` to the visibility change feed. The API exposes `POST /v1/brands/{id}/competitors/crawl` to queue a crawl and `GET /v1/brands/{id}/competitors/site-changes` to read the changes. The web app adds a site-changes section to the Competitors tab. `scripts/snapshot_rival.py` snapshots domains read-only.

## 2. Live check
I ran `scripts/snapshot_rival.py` read-only against Run 1's five competitor domains on 2026-09-24. It took 69 s in all and had no model spend. Afterwards, dev's `rival_crawl`, `rival_page` and `crawl_rivals` jobs were all still at 0 rows.

| Domain | URLs | Complete | Fetches | What happened | Types on sampled pages |
|---|---|---|---|---|---|
| campusshoes.com | 3,915 | yes | 21 | Every sitemap read; homepage + 10 new pages fetched | Product, Offer, AggregateRating, Rating, Review, Brand, Organization, WebSite, SearchAction, ContactPoint, Person (product pages carry 11 each; the homepage none) |
| skechers.in | 2,765 | no | 15 | `sitemap_1-custom.xml` cut off or not XML; 1 page skipped by robots.txt | Organization, WebSite, SearchAction, BreadcrumbList, ItemList, ListItem, ContactPoint, EntryPoint, PostalAddress |
| crocs.in | 654 | no | 15 | `sitemap_product_product.xml` cut off or not XML | Organization only |
| adidas.co.in | 0 | no | 3 | Sitemap answered 403 (bot protection); the homepage answered 403 too | — |
| bata.com | 0 | no | 1 | robots.txt timed out, so nothing was crawled | — |

**What this shows:**
- **Only 1 of 5 domains was complete.** The two cut-off sitemaps are product sitemaps, most likely at the 512 KiB fetch cap. URLs before the cut are kept. Products listed after the cut are never seen, so new pages that a site appends to the end of a large sitemap will not be detected. This is the main ceiling of the slice. The fix would be a larger body cap for sitemap fetches, or streaming the sitemap parse. Neither is built.
- **Bot protection blocks one domain completely (Adidas), and a slow robots.txt blocks another this week (Bata).** Both are stored as incomplete crawls with the error. With the final-review fix, they stay baselines until a crawl actually reads URLs, so a later success is never reported as a flood of "new" pages.
- **Structured data is rich where it exists.** Campus product pages carry full Product/Offer/Review markup. Crocs shows only Organization. That difference is exactly what "new structured data" is meant to track.

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
- A domain stays a baseline until a crawl reads URLs; failed crawls before that never make later URLs "new".
- URLs over 2,048 characters or containing NUL are dropped; so are types over 200 characters or containing NUL.
- Each domain is written in its own savepoint.
- A domain that runs out of time as a job's first domain is stored as an incomplete "out of time" crawl and waits 7 days; later domains cut by the deadline stay due.
- Subdomain URLs are judged by the declared domain's robots.txt, not the subdomain's own.
- `Crawl-delay` is ignored; the pause between fetches is fixed at 0.5 s.
- A crawl job holds the single worker for up to about 7.5 minutes.
- The manual trigger crawls only domains not crawled in the last 7 days.
- A domain listed under two competitors is fetched once per competitor.
- A URL listed under two domains of one competitor can be counted twice in `new_urls` within one job.
- The site-changes route accepts the shared filter parameters (engine, locale, prompt_ids) and ignores them; only `date_to` applies.
- A sitemap whose root is not `urlset` or `sitemapindex` (a soft-404 page, an RSS feed) marks the snapshot incomplete, and its URLs are not read.
- A sitemap disallowed by robots.txt adds an error line and marks the snapshot incomplete.
- The site-changes window is returned as `start`/`to` (not `from`), so the schema needs no alias.
- The feed card lists up to 20 new pages ("up to 20 shown") and shows no count; the site-changes section shows the full count.
- The site-changes section uses the feed's window, including the user's `date_to`.
- Not covered by tests: none of the Server Component rendering (the page has no component tests); the exact 7-day boundary (tests use 6 and 8 days).
- Deferred from the task reviews: `skipped` URLs are not capped (not stored); `rival_crawl` subqueries in `due_rival_crawls()` don't lead with `brand_id`, so they can't use the index prefix; the empty-state message shows even when a brand has no active competitors; the section heading omits "(last 14 days)" (the dates are in the paragraph below it).

## 4. Follow-up: brand domains re-flag citations

Adding or deleting a brand domain now recomputes `citation.is_brand_owned` for that brand's answers (`citations.reflag_citations`), so the Overview citation rate and the competitor `k_cit` use the same hosts from then on.
- Citations flagged before this change are corrected the next time any domain of that brand is added or removed; no bulk backfill was run.
- An extraction running at the moment a domain changes can still write a flag from the old host list.
- Competitor domains need no re-flag: rival ownership is read live, not stored per citation.
- Suggested competitors' domains skip `is_public_hostname` (`suggest.py`) and become crawl targets when confirmed; the confirm PATCH does not re-check them.
- Deferred test nits: the two-domain delete test repeats host names instead of using its `hosts` list, and its POSTs do not assert 201.
