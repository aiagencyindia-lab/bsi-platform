# Slice 7 findings: citation intelligence and the crawlability audit

Date: 2026-09-23. Branch `slice7-audits`. Sources: a direct, read-only call
of `bsi_core.citations.sources()` and `bsi_core.recommend.generate()` in a
tenant session against the dev database (`bsi`) for "Run 1" (brand
`BSOAgentTestBrand`, id `34db213a-f484-4991-a969-c52cfa5e1c10`), a direct
call of `bsi_core.crawl.audit_domain()` against two real public domains
(plain HTTP, no model, no spend), and one owner-session transaction that
inserted a domain and a `site_audit` row for Run 1 from a live audit, ran
`generate()` and `top_by_type()`, and was rolled back. No API server was
used and nothing was written to the dev database.

## 1. What was measured, and how

**Citations (read-only, tenant session):**
```python
from bsi_core.citations import sources
from bsi_core.db import tenant_session
from bsi_core.metrics import Filters
from bsi_core.recommend import generate

with tenant_session(ORG) as s:            # ORG = de2e7f7b-... (Run 1's org)
    rows = sources(s, BRAND, Filters())    # BRAND = 34db213a-...
    cands = generate(s, BRAND)             # read-only; does not write
```

**Crawl audit (plain HTTP, no session):**
```python
from bsi_core.crawl import audit_domain, http_fetch
audit_domain("nytimes.com", http_fetch, pause=0.5)
audit_domain("example.com", http_fetch, pause=0.5)
```

**`fix_crawlability` inside `top_by_type` (owner session, rolled back):**
inserted an `m.Domain(host="nytimes.com")` and an `m.SiteAudit(...)` for
Run 1 built from the live nytimes.com audit's checks, called `generate()`
and `top_by_type()`, printed the result, then `s.rollback()`. A second,
fresh session afterward confirmed `site_audit`, `recommendation`, `task`
and `domain` row counts for the brand are all back to 0.

Run 1 currently has 100 done observations on active prompts (up from 80 at
slice 6 — more runs have been recorded since), no declared domain, and 5
active competitors (Adidas, Bata, Campus, Crocs, Skechers), each with a
declared domain.

## 2. Citations on Run 1

`sources(s, BRAND, Filters())` returned **247 cited domains**.

| | |
|---|---|
| Domain count | 247 |
| Gap domains (`gap: true`) | **136** |
| Source-type split | other 236, review 4, vendor 4, community 2, video 1 |

Top 10 by answers:

| # | Domain | Owner | Type | Answers | Prompts | Brand named |
|---|---|---|---|---|---|---|
| 1 | youtube.com | third_party | video | 41 | 15 | 4 |
| 2 | forbes.com | third_party | other | 29 | 11 | 1 |
| 3 | wearetto.com | third_party | other | 23 | 8 | 0 |
| 4 | starkidz.co.in | third_party | other | 22 | 6 | 0 |
| 5 | facebook.com | third_party | other | 18 | 8 | 0 |
| 6 | reddit.com | third_party | community | 18 | 8 | 1 |
| 7 | adidas.com | third_party | other | 17 | 7 | 0 |
| 8 | myntra.com | third_party | other | 17 | 6 | 0 |
| 9 | zappos.com | third_party | other | 17 | 7 | 0 |
| 10 | campusshoes.com | rival | vendor | 16 | 4 | 0 |

Of the top 10, the brand is named in only **3** (youtube.com, forbes.com,
reddit.com); the other 7, including 6 of the top 9 third-party domains,
cite the brand's rivals without ever naming the brand itself.

**The gap count is 136 of 247 domains, about 55%, and it is large because
Run 1 has 5 active competitors, not because it has none.** The brief's
working assumption — that Run 1 might have few or no active competitors —
does not hold on the live data: all 5 competitors are `active` and each
carries a declared domain (§1). PRD F06's `gap` definition only needs 2+
*active* rivals named in a domain's citing answers and the brand never
named; with 5 active rivals and 100 answers spread across a long tail of
publishers, blogs and retailers, most brand-free answers name two or more
of them, so the raw gap flag marks a majority of domains rather than a
short list. `campusshoes.com` is the one top-10 exception: it is a rival's
own declared domain (`owner: rival`), so it is excluded from `gap` by
construction — a rival's site is not an outreach opportunity (see the
docstring in `citations.py`).

**What this means for using the flag.** `gap` alone is too broad to act on:
at 55% of domains it is a filter for browsing the citation table, not a
prioritized list — it answers "is this domain even a candidate" without
saying which of 136 candidates to work first. `generate()`'s
`pursue_citation_source` rule (§ below) is the ranked, actionable cut: it
adds a floor of 5+ citing answers and excludes rival-declared domains,
producing 56 recommendations ordered by priority instead of 136 unranked
rows.

**Comparison with `generate()`'s `pursue_citation_source` count.**
`generate(s, BRAND)` (called read-only, not `refresh`) produced:

| Type | Count |
|---|---|
| `pursue_citation_source` | 56 |
| `create_content` | 18 |
| `sample_more` | 6 |
| `add_competitor` | 0 (no suggested competitors on this org) |

56 is well below 136. The two numbers measure different things and are not
expected to match: `sources()`'s `gap` only requires 2+ active rivals named
and the brand absent, with no floor on how many answers cite the domain;
`generate()`'s citation rule additionally requires `MIN_CITING_ANSWERS = 5`
citing answers (findings-slice6 §3) **and** excludes any domain a rival has
declared (`_rival_domains`, findings-slice6 §2). Most of the gap between
the two counts (136 vs. 56) is the citing-answer floor: the bulk of the 136
gap domains beyond the top few dozen are cited in only 1-4 answers, which
the recommendation rule intentionally excludes as too thin to act on (same
reasoning as findings-slice6 §3).

## 3. Crawl audit: two real domains

Both runs used the real fetch (`http_fetch`), `pause=0.5` between calls, 8
bot user agents, and the standard 12-fetch budget (home, robots.txt, 8 bot
homepage fetches, sitemap, llms.txt — see §5.7). The bot fetches only run
when the homepage answered the browser user agent; otherwise the budget is
4 (home, robots.txt, sitemap, llms.txt).

### nytimes.com

Re-run in the final fix round with the audit's new browser user agent (a
real desktop Chrome string). The first run used a bot-like one
(`Mozilla/5.0 (compatible; BSI-Audit/1.0)`), got `403` on the homepage and
was blind: bot-managed sites turn such a user agent away, so the audit had
no baseline. That is why the user agent changed.

| | |
|---|---|
| Fetches | 4 |
| Elapsed | 4.36s |
| Checks run | 12 (on-page and bot-UA checks skipped: home unreachable) |
| Failing | 9 |

Failing checks:

| Code | Severity | URL | Observed |
|---|---|---|---|
| `home_unreachable` | high | `https://nytimes.com/` | `HTTP 403` |
| `bot_blocked:GPTBot` | high | `https://nytimes.com/robots.txt` | `User-agent: GPTBot\nDisallow: /` |
| `bot_blocked:OAI-SearchBot` | high | same | `User-agent: OAI-SearchBot\nDisallow: /` |
| `bot_blocked:ClaudeBot` | high | same | `User-agent: ClaudeBot\nDisallow: /` |
| `bot_blocked:Claude-SearchBot` | high | same | `User-agent: Claude-SearchBot\nDisallow: /` |
| `bot_blocked:PerplexityBot` | high | same | `User-agent: PerplexityBot\nDisallow: /` |
| `bot_blocked:Google-Extended` | high | same | `User-agent: Google-Extended\nDisallow: /` |
| `sitemap_invalid` | medium | `https://www.nytimes.com/sitemaps/new/news.xml.gz` | `root <unparseable: no element found: line 9002, column 15>` |
| `llms_missing` | low | `https://nytimes.com/llms.txt` | `HTTP 404` |

This confirms the premise: nytimes.com's robots.txt disallows GPTBot (and
five other AI bots) outright; Googlebot and Bingbot are allowed. The real
Chrome user agent did **not** get through either: the homepage still
answered `403`. The block is not keyed on the user agent string alone —
a plain `httpx` request lacks the rest of a browser's headers and TLS
fingerprint, which bot management also checks. The audit's answer for
nytimes.com is therefore still "home unreachable, high severity", now
without the misleading part: because the homepage gave no baseline, the 5
on-page checks and the 8 `bot_ua_blocked:*` checks were skipped and never
fetched, where the first run fetched all 8 bot user agents and reported
each as "not blocked" regardless of what it got. The robots-declared
sitemap (`sitemaps/new/news.xml.gz`) answered `200` but did not parse
(§5.3).

### example.com

| | |
|---|---|
| Fetches | 12 |
| Elapsed | 6.25s |
| Checks run | 24 (all but `sitemap_invalid`: no sitemap to validate) |
| Failing | 5 |

Failing checks:

| Code | Severity | URL | Observed |
|---|---|---|---|
| `description_missing` | low | `https://example.com/` | `absent` |
| `canonical_missing` | low | `https://example.com/` | `absent` |
| `org_schema_missing` | medium | `https://example.com/` | `0 ld+json block(s)` |
| `sitemap_missing` | medium | `https://example.com/sitemap.xml` | `HTTP 404` |
| `llms_missing` | low | `https://example.com/llms.txt` | `HTTP 404` |

example.com's homepage, robots.txt (absent, so every bot is allowed) and
title/h1 all pass; it has no sitemap, no meta description, no canonical
link, no JSON-LD, and no `llms.txt`, which is exactly what its famously
minimal placeholder page looks like.

## 4. `fix_crawlability` in `top_by_type`

Inside one owner-session transaction (rolled back, never committed): a
`domain` row for `nytimes.com` and a `site_audit` row built from §3's live
nytimes.com audit were inserted for Run 1, then `generate()` and
`top_by_type()` were called.

(This used the first run's nytimes.com audit; the re-run in §3 has the
same 9 failing checks, so the counts below are unchanged.)

`generate()` returned **89 candidates**: 9 `fix_crawlability` (one per
failing check, §3's 9 failures), plus the same 56 `pursue_citation_source`,
18 `create_content` and 6 `sample_more` from §2.

All 7 `high`-severity `fix_crawlability` checks tie at **priority 0.8**
(reach 1.0 x pressure 1.0 x feasibility 0.8) — higher than every other
candidate on Run 1, including the top citation source (youtube.com, 0.108).
`top_by_type()`'s result (best of each type, up to 3):

| # | Type | Subject | Priority |
|---|---|---|---|
| 1 | `fix_crawlability` | `nytimes.com:bot_blocked:Claude-SearchBot` | 0.8 |
| 2 | `pursue_citation_source` | youtube.com | 0.108 |
| 3 | `sample_more` | (prompt `28e90862-...`) | 0.04 |

`fix_crawlability` lands first. Which of the 7 tied 0.8 candidates wins the
slot is decided by `generate()`'s tie-break, `(type, subject_key)`:
`Claude-SearchBot` sorts before `ClaudeBot` before `GPTBot` before
`Google-Extended` before `OAI-SearchBot` before `PerplexityBot` before
`home_unreachable` — an artifact of ASCII ordering on the bot name inside
the subject key, not a judgment that Claude-SearchBot's block matters more
than GPTBot's.

Recommendations now refresh at the end of every audit: the worker's
`run_crawl_audit` calls `recommend.refresh()` in the same transaction that
writes the `site_audit` rows, so a new failure (or a fix) reaches the
recommendation list at once instead of at the next weekly pass. It does not
stamp `brand.recs_refreshed_at`, so the weekly refresh is not deferred.

Afterward, a fresh session confirmed the dev database for Run 1 is
unchanged:

| Table | Count |
|---|---|
| `site_audit` | 0 |
| `recommendation` | 0 |
| `task` | 0 |
| `domain` | 0 |

## 5. Known gaps

1. **Source-type heuristic.** `citations.source_type()` classifies a
   third-party domain by a fixed keyword table (`youtube`/`vimeo` ->
   video, `reddit`/`quora`/`stackexchange` -> community,
   `review`/`g2.com`/`capterra`/`trustpilot`/`mouthshut` -> review, else
   `other`) — labelled as a heuristic in the code and in the API, not a
   licensed source classifier. On live data 236 of 247 domains (96%) fall
   into `other`, which is honest but not very informative; a real
   classifier would replace the table, not the callers.
2. **First owned sitemap only.** `audit_domain()` reads only the first
   `robots.txt`-declared sitemap that resolves to the audited host (or a
   subdomain), falling back to `/sitemap.xml`; any further sitemap entries,
   and any off-host or non-http(s) entries, go unread. A sitemap index that
   fans out to many per-section sitemaps is not walked.
3. **A gzip-encoded sitemap fails `sitemap_invalid` for the wrong reason.**
   nytimes.com's live sitemap (`sitemaps/new/news.xml.gz`, §3) is served
   gzip-compressed; `audit_domain()` reads the response body as text
   without decompressing it, so `ET.fromstring` sees compressed bytes and
   raises a parse error. `sitemap_invalid` happens to come back `false`,
   the same as any other unparseable sitemap, but the observed text ("root
   <unparseable: ...>") does not say the file is gzipped, and a
   *correctly* gzip-encoded sitemap — a normal, valid practice for large
   sitemaps — would be wrongly flagged as invalid.
4. **No page crawl.** The audit reads the homepage and the declared site
   files only — robots.txt, one sitemap, llms.txt. It never follows a link
   or fetches a second page, so it cannot see whether *other* pages on the
   site are crawlable, have their own metadata, or are blocked differently
   than the homepage.
5. **`bot_ua_blocked` cannot tell a CDN challenge from a hard block.** The
   check treats any `401`/`403`/`429`/`5xx` response to a bot's user agent
   as "blocked," which is also what a generic anti-bot challenge (rate
   limiting, a CAPTCHA wall, a WAF rule keyed on request shape rather than
   UA) looks like from the outside. The check needs a reachable homepage
   to mean anything, so when the browser user agent is refused (nytimes.com,
   §3) the 8 bot fetches are now skipped and no `bot_ua_blocked:*` check is
   emitted, rather than being reported as "not blocked".
6. **A failed audit retries hourly; a failing check waits a week.** A
   failed `audit_crawl` job writes no `site_audit` row, so the brand stays
   due and `queue_due_crawl_audits()` queues it again in the next hour's
   slot (it never re-runs a failed job within the same hour). So a failed
   audit retries hourly until one succeeds; a successful audit with failing
   checks waits a week. One host raising inside a job no longer loses the
   other hosts' rows: the worker skips that host and writes the rest, and
   the skipped host stays due.
7. **The fetch budget is 12 per domain, not 11.** The design spec counted
   11; the actual budget, confirmed by both live runs above (`fetches: 12`
   in each), is home (1) + robots.txt (1) + 8 bot-UA homepage fetches (8)
   + sitemap (1) + llms.txt (1) = 12. The spec's 11 was a miscount, not a
   deliberate reduction; this findings doc is the correction of record.
8. **Security gap to close before any hosted deployment: SSRF.**
   `audit_domain()`/`http_fetch()` fetches whatever host it is given, with
   no check that the resolved address is public. Nothing is typed into the
   Site tab (its POST has no body); the real vectors are:
   - a declared domain via `POST /v1/brands/{id}/domains` —
     `normalize_domain` accepts `127.0.0.1`, `169.254.169.254` (a cloud
     metadata endpoint) and `localhost`;
   - redirects: `httpx` runs with `follow_redirects=True`, so a public host
     that 302-redirects inward is followed there;
   - the robots.txt `Sitemap:` URL: it must be on the audited host or a
     subdomain, but a tenant-controlled subdomain whose DNS points at an
     internal address passes that check.

   In a single-tenant local setup with trusted operators this is inert;
   hosted for multiple tenants, any tenant could make the worker issue
   internal HTTP requests (cloud metadata, internal admin endpoints, port
   scans). The fix: resolve the host and pin the IP for the request; reject
   private, loopback, link-local and metadata ranges; disable automatic
   redirects and re-check every hop; stream the body with a byte cap and a
   total deadline. `http_fetch` carries a `SECURITY:` comment pointing here.
9. **robots.txt matching is first-match, not RFC 9309 longest-match.**
   `urllib.robotparser` applies the first rule whose path prefixes the URL;
   RFC 9309 says the longest match wins. So `User-agent: *` /
   `Disallow: /` / `Allow: /$` — "only the homepage is allowed" — reads as
   the homepage blocked, and yields 8 false high-severity `bot_blocked`
   failures. Deferred to the crawl-hardening task, with SSRF.

## 6. Spend

Unchanged: **$9.2762**. Both live steps in this task are plain HTTP
(`httpx` fetches for the crawl audit) or direct SQL reads (citations,
`generate()`); neither calls a model or the Vertex API, so
`db_micros(since) + ledger_micros()` is exactly what it was before this
task, confirmed by re-running the same spend calculation
(`bsi_core.spend.db_micros` + `bsi_core.spend.ledger_micros`) after all
live checks completed.
