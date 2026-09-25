# Slice 14 design: read big competitor sitemaps in full

## Context

The competitor site crawl (slice 12) reads sitemaps through `crawl.http_fetch`, which stops reading at 512 KiB and returns a 2xx body with no marker. `rivals.parse_sitemap` then sees a root that never closes and reports "cut off or not XML", and the products listed past the cut are never seen. The slice 12 live check showed this on skechers.in and crocs.in; the first worker pass (findings-slice12 §5) showed it on skechers.com too. Every other fetch path relies on the same cap to bound memory: the page score, the crawlability and entity audits, the Wikidata calls and the webhook POST. The change must therefore be scoped to sitemap fetches.

Decisions. The ceiling, the file cap and the approach were chosen by the user in brainstorming. The four design sections below were first asked about without their text being shown; after the build, on 2026-09-25, each section was shown in full and approved as built, including the URL ceiling cutting in sitemap order, which was the controller's choice:

- **Ceiling:** bounded but large. Each sitemap file is read up to the sitemap protocol's 50 MB. A domain yields at most 50,000 URLs per crawl and at most 50 sitemap files (was 11). Either cap ends the read and marks the snapshot incomplete.
- **Approach:** a `cap` argument and a `truncated` flag on the fetcher; the crawl fetches sitemap files with a 50 MiB cap and parses each file whole. A streaming parser and spooling to disk were considered and rejected: more code, and no gain at 50 MB.
- **Gzip:** a `.xml.gz` served without a Content-Encoding header is recognised by its magic bytes and unzipped, under the same 50 MiB bound.
- **Time budget:** per domain. The job's 420 seconds are divided by the number of due domains, with a floor of 60 seconds. Every domain that runs out of time is stored as an incomplete crawl, not only the job's first.
- **Kept as they are:** the 30-second deadline per fetch, the robots.txt rules, the owned-host check on sitemap URLs, the newest-first sample of 10 pages, the pause between fetches, the URL length and NUL filters, and the storage layout. No migration, API or web change.

Planning ran on Fable 5.1 with the user's approval. Implementers and reviewers run on Opus 5.5 only.

## Design

### 1. Fetcher (`bsi_core/crawl.py`)

- `http_fetch` gains two keyword arguments: `cap: int = BODY_CAP_BYTES` and `raw: bool = False`.
- The read loop uses `cap` where it uses the constant today. The gzip-bomb bound (`decompress(chunk, room)`) therefore holds at any cap.
- `Response` gains `truncated: bool = False`, set when the loop stops at the cap and something was dropped: the rest of the chunk that crossed it, input the inflater had not consumed, or a later chunk. A body that fits the cap exactly is not truncated. Every existing caller keeps its behaviour: the default cap is unchanged and nothing reads the flag yet.
- With `raw=True` the body bytes are decoded as Latin-1, which is lossless, instead of the response charset. A caller recovers the exact bytes with `body.encode("latin-1")`. Only sitemap fetches use it.
- A new constant `SITEMAP_CAP_BYTES = 50 * 1024 * 1024`. The fetcher does not apply it; the crawl passes it.
- The `Fetch` alias `(url, user_agent) -> Response` is unchanged. Callers bind `cap` and `raw` with `functools.partial`, so test fakes keep two arguments.

### 2. Sitemap reading (`bsi_core/rivals.py`)

- `MAX_SITEMAP_FETCHES` becomes 50. A new `MAX_URLS = 50_000`.
- `parse_sitemap` takes bytes instead of text and returns four values: the root tag, the `(loc, lastmod)` entries, whether the root closed, and whether a gzip body was cut. If the bytes start with the gzip magic `\x1f\x8b`, they are unzipped with `zlib.decompressobj(47)` under a `SITEMAP_CAP_BYTES` bound; input left unconsumed at the bound means cut. Parsing is otherwise unchanged: `XMLPullParser`, depth tracking, `clear()` per entry.
- `snapshot_domain(host, fetch, known, *, pause=0.0, sitemap_fetch=None)` uses `sitemap_fetch or fetch` for robots-declared and default sitemap files and `fetch` for pages. `rivals.SITEMAP_FETCH = partial(http_fetch, cap=SITEMAP_CAP_BYTES, raw=True)` is defined once, and the worker and the script both use it (moved there by the final review so the live check runs exactly what the worker runs); tests inject fakes for both.
- Incomplete detection becomes exact. A truncated response, or a gzip body cut at the unzip bound, adds "sitemap {url}: cut off at the size cap". Otherwise a root that does not close adds "sitemap {url}: not well-formed XML". Both mark the snapshot incomplete. Children of a cut-off index are still queued, as today.
- URL ceiling: before adding a urlset's entries, if the total would pass `MAX_URLS`, the crawl adds entries up to the ceiling, appends "sitemap {url}: URL ceiling of 50000 reached", marks the snapshot incomplete and empties the sitemap queue. The file cap keeps its existing error line.

### 3. Worker (`bsi_workers/worker.py`, `run_rival_crawl`)

- Each due domain gets its own budget: `max(RIVAL_DOMAIN_FLOOR_SECONDS, RIVAL_JOB_SECONDS // len(due))`, with `RIVAL_DOMAIN_FLOOR_SECONDS = 60`. Its page fetch and sitemap fetch are both wrapped with `with_deadline` on that budget.
- A domain that runs out of time is stored as `Snapshot(complete=False)` with the error "out of time", whatever its position in the job, and the loop moves to the next domain. What it had read before running out is not kept. Between domains the job checks its own 420-second clock; domains it never reaches stay unstored and due, as today. The worst case is about 570 seconds of fetching with four due domains (the budget, the last domain's 105-second share, and one fetch that can run about 45 seconds because each read may wait 15), then parsing and the write, under the 10-minute stale cutoff.
- Writes are unchanged: one savepoint per domain, upserts in chunks of 2,000 rows. At 50,000 URLs that is 25 statements. Snapshots are held until the write phase, so peak memory is the sum of the due domains' URL sets, well under 100 MB for Run 1's seven domains. `urls_seen` keeps its meaning and becomes exact when `complete` is true.
- `scripts/snapshot_rival.py` passes the sitemap fetch too. It stays read-only: real HTTP, no database.

### 4. Testing

- Fetcher: a body over the cap returns `truncated=True` and exactly `cap` bytes; a custom cap is honoured; a gzip bomb stays bounded at a custom cap, checked with tracemalloc; `raw=True` round-trips bytes; the existing GET, POST and guard tests are untouched.
- Sitemaps: a gzip body without Content-Encoding parses; a gzip body cut at the unzip bound reports "cut off at the size cap"; a truncated response reports the same and an unclosed root reports "not well-formed XML"; the URL ceiling (with a small monkeypatched `MAX_URLS`) stops with the error line, `complete=False` and an emptied queue; with a small monkeypatched file cap that is not reached, the URL ceiling stops the read first; `sitemap_fetch` serves sitemap files and `fetch` serves pages. Fakes stay two-argument functions returning a `Response`.
- Worker: with two due domains, the second running out of time, both are stored and the second is incomplete with "out of time"; a single domain out of time reports the full 420 s; with ten due domains the reported budget is the 60-second floor; a domain the job never reaches stays due; the existing "no transaction open during fetch" test still passes.
- `tests/unit/test_crawl.py::test_a_sitemap_cut_off_at_the_body_cap_is_still_valid` stays: the crawlability audit tolerates truncation by design.

### 5. Live check

Read-only: `uv run python scripts/snapshot_rival.py skechers.in skechers.com crocs.in` on the branch, with real HTTP, no database writes and no spend. The script also prints each host's wall time. The findings report each domain's URL count, completeness, fetch count, seconds and error lines as observed, next to the slice 12 numbers (2,765 / 3,015 / 654 URLs, all incomplete), and compare the seconds with the 60-second budget a domain gets when Run 1's seven domains are due.

## Rulings

Each is listed to the user with its cost if wrong. The first three were approved by the user through the design sections, as built, on 2026-09-25; the fourth follows from the approach the user chose. Rulings made during the build are in `docs/findings-slice14.md` §3.

- **The 30-second deadline per fetch stays for sitemap files.** Cost: a file that cannot download in 30 seconds stays incomplete; the fix is a `deadline` keyword shaped like `cap`.
- **The URL ceiling cuts in sitemap order, not newest first.** Cost: on a site over 50,000 URLs the newest products may be the ones dropped; a later slice can sort by lastmod before cutting.
- **Equal split of the job budget with a 60-second floor.** Cost: one slow site gets less time when many domains are due. Run 1 has seven due domains, so each gets 60 seconds, and a domain that runs out of time is stored with none of the URLs it had read.
- **Parse each file whole rather than stream.** Cost: peak memory of one 50 MB file plus its parsed entries, a few hundred MB, on one worker.

## Out of scope

Streaming or spooled fetches, a longer per-fetch deadline, sitemap freshness ordering before the cut, recommendations from site changes, and any change to the page, audit or webhook fetch paths.
