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
`pursue_citation_source` rule (§ below) is the ranked, actionable list, but
it is a different selection, not a cut of `gap`: it needs 5+ brand-free
citing answers on active prompts and excludes rival-declared domains, with
no two-rival requirement, so its 56 recommendations are not a subset of
the 136 gap rows.

**Comparison with `generate()`'s `pursue_citation_source` count.**
`generate(s, BRAND)` (called read-only, not `refresh`) produced:

| Type | Count |
|---|---|
| `pursue_citation_source` | 56 |
| `create_content` | 18 |
| `sample_more` | 6 |
| `add_competitor` | 0 (no suggested competitors on this org) |

56 is well below 136. The two numbers measure different things and are not
expected to match: `sources()`'s `gap` requires 2+ active rivals named and
the brand never named in any citing answer, with no floor on how many
answers cite the domain; `generate()`'s citation rule instead requires
`MIN_CITING_ANSWERS = 5` brand-free citing answers on active prompts
(findings-slice6 §3), has no rival-count requirement, and excludes any
domain a rival has declared (`_rival_domains`, findings-slice6 §2). A
domain can be recommended without being a gap (the brand is named in some
of its other answers, or fewer than two rivals are), so the 56 are not a
subset of the 136. Most of the gap between
the two counts (136 vs. 56) is the citing-answer floor: the bulk of the 136
gap domains beyond the top few dozen are cited in only 1-4 answers, which
the recommendation rule intentionally excludes as too thin to act on (same
reasoning as findings-slice6 §3).

## 3. Crawl audit: two real domains

These runs predate the crawl-hardening fixes (§5.8, §5.9) and were not
re-run after them. Each nytimes.com `bot_blocked` failure below came from a
group naming that bot exactly, which RFC 9309 reads the same way.

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
| Failing | 8 |

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
sitemap (`sitemaps/new/news.xml.gz`) answered `200` and is valid. The
first two runs reported it as `sitemap_invalid` ("no element found: line
9002"). That was a defect in the audit, fixed before merge (§5.3). The
table above was not produced by a fresh run: it is the pre-fix run's output
with the false `sitemap_invalid` removed, and Elapsed is from that run.

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

(This used the first run's nytimes.com audit, whose 9 failing checks
included the false `sitemap_invalid` fixed in §5.3. With the fix it is 8
failures and 88 candidates; the top-three below does not change, since the
false check was medium severity.)

`generate()` returned **89 candidates**: 9 `fix_crawlability` (one per
failing check), plus the same 56 `pursue_citation_source`, 18
`create_content` and 6 `sample_more` from §2.

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
3. **Fixed before merge: large sitemaps were reported invalid.**
   `http_fetch` keeps the first 512 KiB (`BODY_CAP_BYTES`) of a body, and the
   sitemap check parsed the whole of what it kept, so any sitemap larger
   than the cap arrived cut off mid-element and failed to parse. nytimes.com
   showed it: its sitemap is served as `text/xml` with
   `Content-Encoding: gzip`, httpx decompresses it to 601,518 characters,
   and the cap cut it at 524,288 — hence "no element found: line 9002". An
   earlier draft of these findings blamed gzip; that was wrong, since httpx
   decodes `Content-Encoding` itself. The check now feeds the capped body
   to a pull parser and the root element decides (`crawl._root_tag`); the
   parser is never closed, so a truncated tail no longer matters; `test_a_sitemap_cut_off_at_the_body_cap_is_still_valid`
   pins it. Still unhandled: a `.gz` file served as raw `application/gzip`
   with no `Content-Encoding` header arrives compressed and is reported
   invalid.
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
   11; the actual budget, confirmed by example.com's live run (12 fetches;
   nytimes.com's made 4 because its homepage failed, so the bot-UA and
   on-page checks were skipped), is home (1) + robots.txt (1) + 8 bot-UA
   homepage fetches (8) + sitemap (1) + llms.txt (1) = 12. The spec's 11
   was a miscount, not a deliberate reduction; this findings doc is the
   correction of record.
8. **Fixed (crawl-hardening): SSRF.** `audit_domain()`/`http_fetch()` used
   to fetch whatever host it was given, with no check that the resolved
   address was public, and followed redirects automatically. The vectors
   were a declared domain via `POST /v1/brands/{id}/domains`
   (`normalize_domain` accepted `127.0.0.1`, `169.254.169.254` and
   `localhost`), a public host that 302-redirects inward, and a
   robots.txt `Sitemap:` URL on a tenant-controlled subdomain whose DNS
   points inside. What now happens, on every hop:
   - only `http`/`https` on the default port (80/443) is fetched;
   - the host is resolved once, and the fetch is refused unless every
     returned address is globally routable and not multicast (`ipaddress`
     `is_global`, plus an explicit multicast check, since `is_global` calls
     `224.0.0.1` and `ff02::1` global): loopback, private, link-local
     (including `169.254.169.254`), CGNAT, unspecified, multicast, reserved
     and ULA ranges are all refused, and an IP literal in the URL goes
     through the same check;
   - an IPv6 address that carries an IPv4 one is judged by that IPv4
     address: IPv4-mapped (`::ffff:0:0/96`), 6to4 (`2002::/16`) and the
     well-known NAT64 prefix (`64:ff9b::/96`, so `64:ff9b::a9fe:a9fe`,
     i.e. 169.254.169.254, is refused and `64:ff9b::808:808` allowed);
     Teredo (`2001::/32`) and IPv4-compatible (`::/96`) addresses are
     refused outright. The rule is spelled out rather than left to
     `is_global`, whose IPv6 tables differ before Python 3.13
     (requires-python is >=3.12). A network-specific NAT64 prefix cannot
     be recognised and is judged as plain IPv6;
   - the connection is pinned to the checked address: the request URL
     carries the IP, `Host` carries the name, and for https the name is
     passed as `sni_hostname`, which httpcore uses as the TLS
     `server_hostname`, so SNI and certificate verification still use the
     real name (verification stays on); environment proxies are ignored;
   - redirects are followed by hand, at most 5, each Location resolved
     against the current URL and re-checked from the top;
   - the body is read raw and decoded by the audit itself: only
     `Accept-Encoding: gzip, deflate` is sent, a single gzip/x-gzip/deflate
     layer is inflated with zlib's `max_length` so the output never passes
     `BODY_CAP_BYTES` (512 KiB), and stacked (`gzip, gzip`, which let a
     1.8 KB response reach 2.1 GiB of heap under httpx's own decoder) or
     unknown encodings are refused; a 1 GiB gzip bomb now peaks at about
     3 MiB of Python heap;
   - the whole fetch, all hops included, stops at 30 s: each request's
     timeout is the time left (at most 15 s per phase). DNS resolution is
     not time-bounded: `getaddrinfo` takes no timeout, so a slow resolver
     can hold a fetch past the deadline.

   A refused URL is a `Response(0, "", "refused: <reason>")`, e.g.
   `refused: 169.254.169.254 is not a public address`. As defence in depth
   the API now rejects, with 422, a brand domain or competitor domain whose
   normalized host is an IP literal, has no dot, or has a last label that
   does not start with a letter (`127.1`, `0x7f.0x1`)
   (`matching.is_public_hostname`). Model-suggested competitor domains skip
   this check; they are never crawled. `tests/unit/test_http_fetch.py` covers
   every refused range, DNS that answers with an internal or mixed set of
   addresses, embedded IPv4, pinning, redirects, the byte cap, a gzip bomb
   (with a memory bound), stacked encodings and the deadline, with DNS and
   HTTP faked.
9. **Fixed (crawl-hardening): robots.txt is read per RFC 9309.**
   `urllib.robotparser` applied the first rule whose path prefixed the URL,
   where RFC 9309 says the longest match wins, so `User-agent: *` /
   `Disallow: /` / `Allow: /$` ("only the homepage is allowed") read as the
   homepage blocked and yielded 8 false high-severity `bot_blocked`
   failures. `crawl.py` no longer uses robotparser. Groups end only when a
   user-agent line follows a rule (blank lines, comments, `Sitemap:`,
   `Host:` and unknown keys do not split them); a bot uses every group
   whose product token equals its name, case-insensitively, else every
   `*` group; `*` and a trailing `$` work in patterns; the longest matching
   pattern wins and Allow wins a tie. Lines follow the RFC grammar: only
   CR, LF and CRLF end a line, only space and tab are whitespace (so NEL,
   U+2028 and NBSP are ordinary characters), and a leading BOM is dropped
   rather than hiding the first line. Percent-encoding is not normalized,
   which cannot matter for "/". `observed` is the verdict's lines,
   normalized (`Disallow: /`, no padding), and always re-evaluates to the
   same verdict; seeded fuzzes pin that and compare every verdict with an
   independent RFC reading. Three verdicts change on purpose:
   - a loose name no longer covers a bot: `User-agent: Claude` does not
     apply to ClaudeBot (its product token is `ClaudeBot`), which now falls
     to the `*` group; `User-agent: claudebot/1.0` does apply;
   - an unreachable robots.txt (5xx, or a fetch that failed or was
     refused by the SSRF guard) now means disallow-all (RFC 9309 §2.3.1.4)
     and fails every `bot_blocked` check with the reason in `observed`;
     robotparser's reading was allow-all. A 4xx is still "no robots.txt",
     allow-all, and so is a robots.txt behind more than 5 redirects, which
     §2.3.1.2 calls unavailable;
   - a robots.txt starting with a BOM is now read from its first line.

## 6. Spend

Unchanged: **$9.2762**. Both live steps in this task are plain HTTP
(`httpx` fetches for the crawl audit) or direct SQL reads (citations,
`generate()`); neither calls a model or the Vertex API, so
`db_micros(since) + ledger_micros()` is exactly what it was before this
task, confirmed by re-running the same spend calculation
(`bsi_core.spend.db_micros` + `bsi_core.spend.ledger_micros`) after all
live checks completed.
