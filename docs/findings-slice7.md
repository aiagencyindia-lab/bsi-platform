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

**The gap count is 136, not 0, and it is large because Run 1 has 5 active
competitors, not because it has none.** The brief's working assumption —
that Run 1 might have few or no active competitors — does not hold on the
live data: all 5 competitors are `active` and each carries a declared
domain (§1). PRD F06's `gap` definition only needs 2+ *active* rivals named
in a domain's citing answers and the brand never named; with 5 active
rivals and 100 answers spread across a long tail of publishers, blogs and
retailers, most third-party domains clear that bar easily. `campusshoes.com`
is the one top-10 exception: it is a rival's own declared domain
(`owner: rival`), so it is excluded from `gap` by construction — a rival's
site is not an outreach opportunity (see the docstring in `citations.py`).

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
homepage fetches, sitemap, llms.txt — see §5.6).

### nytimes.com

| | |
|---|---|
| Fetches | 12 |
| Elapsed | 10.34s |
| Checks run | 20 (on-page checks skipped: home unreachable) |
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
| `sitemap_invalid` | medium | `https://www.nytimes.com/sitemaps/new/news.xml.gz` | `root <unparseable: no element found: line 8997, column 156>` |
| `llms_missing` | low | `https://nytimes.com/llms.txt` | `HTTP 404` |

This confirms the premise: nytimes.com's robots.txt disallows GPTBot (and
five other AI bots) outright, exactly as claimed. It also surfaced two
things nobody asked for: the homepage itself answered `403` to the
audit's own browser user agent (`BSI-Audit/1.0`, not a real browser UA —
Fastly/nytimes bot-detection turned it away before robots.txt was even
relevant), and the robots-declared sitemap (`sitemaps/new/news.xml.gz`,
gzip-compressed) came back as unparsed XML because the audit reads the raw
(still-compressed) bytes as text rather than decompressing them —
`sitemap_invalid` is correctly `false`, but for a reason the check's copy
("root <urlset> or <sitemapindex>") doesn't name. Because `home_unreachable`
failed, `bot_ua_blocked:*` and the 5 on-page checks (title, description,
h1, canonical, org schema) were skipped by design ("on-page checks need a
reachable homepage" — `crawl.py`), and `bot_ua_blocked:*` for the 8 bots
came back `ok` — not because nytimes.com answers those bots, but because
the check's own logic (`blocked = home.ok and (...)`) can't tell "the
browser UA itself was blocked" from "no bot-specific block exists" when
the baseline homepage fetch already failed. That is a real edge case in
the check, not a defect in the finding: nytimes.com's status is accurately
"home unreachable, high severity," which already dominates.

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
3. **No page crawl.** The audit reads the homepage and the declared site
   files only — robots.txt, one sitemap, llms.txt. It never follows a link
   or fetches a second page, so it cannot see whether *other* pages on the
   site are crawlable, have their own metadata, or are blocked differently
   than the homepage.
4. **`bot_ua_blocked` cannot tell a CDN challenge from a hard block.** The
   check treats any `401`/`403`/`429`/`5xx` response to a bot's user agent
   as "blocked," which is also what a generic anti-bot challenge (rate
   limiting, a CAPTCHA wall, a WAF rule keyed on request shape rather than
   UA) looks like from the outside. Section 3's nytimes.com run shows the
   contrapositive of this gap directly: the *browser* UA itself got a 403,
   which the check correctly treats as `home_unreachable` rather than
   `bot_ua_blocked`, but it means every `bot_ua_blocked:*` check was
   silently skipped-as-passing rather than evaluated, because the
   check's logic only flags a bot as blocked relative to a homepage that
   itself answered successfully.
5. **A failing weekly audit retries at most hourly.** `audit_crawl` is
   queued weekly by `due_crawl_audits()`; if a run fails (network error,
   timeout), the next attempt is gated by the job system's normal retry
   backoff, not before an hour has passed — so a domain that starts
   failing outside the weekly window can go most of a week before the next
   audit even attempts to reach it again, longer if the retry itself keeps
   failing.
6. **The fetch budget is 12 per domain, not 11.** The design spec counted
   11; the actual budget, confirmed by both live runs above (`fetches: 12`
   in each), is home (1) + robots.txt (1) + 8 bot-UA homepage fetches (8)
   + sitemap (1) + llms.txt (1) = 12. The spec's 11 was a miscount, not a
   deliberate reduction; this findings doc is the correction of record.
7. **Security gap to close before any hosted deployment: SSRF.**
   `audit_domain()`/`http_fetch()` fetches whatever host is passed to it,
   following redirects, with no check that the resolved address is
   public. The host comes from an operator-declared domain (the `domain`
   table, or a value typed into the Site tab's audit trigger) — nothing
   currently stops that host from being `127.0.0.1`, `169.254.169.254`
   (a cloud metadata endpoint), a private RFC1918 address, or a public
   hostname that 302-redirects to one of those, and `httpx`'s
   `follow_redirects=True` will follow it there. In a single-tenant local
   setup with trusted operators this is inert; the moment the platform is
   hosted for multiple tenants, any tenant who can set their own domain
   (or point a domain they control at a redirect) can make the crawl-audit
   worker issue arbitrary internal HTTP requests on the server's own
   network (SSRF) — reading cloud metadata, hitting internal admin
   endpoints, or port-scanning the private network, entirely through a
   feature designed to fetch public web pages. This must be fixed (resolve
   the host first, reject private/loopback/link-local/metadata ranges,
   re-check after every redirect hop) before the crawl audit is exposed to
   more than one trusted tenant.

## 6. Spend

Unchanged: **$9.2762**. Both live steps in this task are plain HTTP
(`httpx` fetches for the crawl audit) or direct SQL reads (citations,
`generate()`); neither calls a model or the Vertex API, so
`db_micros(since) + ledger_micros()` is exactly what it was before this
task, confirmed by re-running the same spend calculation
(`bsi_core.spend.db_micros` + `bsi_core.spend.ledger_micros`) after all
live checks completed.
