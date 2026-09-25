# Findings: slice 14 — sitemaps in full

## 1. What was built

**Fetcher.** `crawl.http_fetch` takes `cap` (default `BODY_CAP_BYTES`, 512 KiB) and `raw` (default false). The read loop keeps at most `cap` decoded bytes, so the gzip-bomb bound holds at any cap of 1 byte or more. `Response` gains `truncated`, set when the loop stops at the cap and something was dropped: the rest of the chunk that crossed it, input the inflater had not consumed, or a later non-empty chunk. A body that fits the cap exactly is not truncated. With `raw=True` the bytes are decoded as Latin-1, so `body.encode("latin-1")` gives them back exactly. A new constant `SITEMAP_CAP_BYTES` is 50 MiB; the fetcher does not apply it. Every other caller keeps the 512 KiB cap and ignores the flag.

**Sitemap reading.** In `rivals.py`, `MAX_SITEMAP_FETCHES` is 50 (was 11) and `MAX_URLS` is 50,000. `parse_sitemap` takes bytes and returns four values: root tag, entries, closed cleanly, and cut. Bytes starting with the gzip magic `1f 8b` are inflated with `zlib.decompressobj(47)` under `SITEMAP_CAP_BYTES`; input left over at the bound means cut. `snapshot_domain` takes `sitemap_fetch` (default `fetch`) for sitemap files and uses `fetch` for robots.txt and pages. A truncated response or a cut gzip body adds "sitemap {url}: cut off at the size cap"; otherwise an unclosed root adds "sitemap {url}: not well-formed XML". Reaching 50,000 URLs adds "sitemap {url}: URL ceiling of 50000 reached", keeps the URLs up to the ceiling and empties the sitemap queue. All of these mark the snapshot incomplete.

**Worker.** `run_rival_crawl` uses `SITEMAP_FETCH = partial(http_fetch, cap=SITEMAP_CAP_BYTES, raw=True)` for sitemap files when `fetch` is `http_fetch`. Each due domain gets `max(60, 420 // len(due))` seconds, and both its page fetch and its sitemap fetch are wrapped with `with_deadline` on that budget. A domain that runs out of time is stored as an incomplete crawl with "out of time: the crawl did not finish within {per} s", whatever its position, and the loop goes on. What it had read is not kept. Before each domain the job checks its own 420 s clock; domains it never reaches stay unstored and due. Writes are unchanged. No migration, API or web change.

**Script.** `scripts/snapshot_rival.py` passes the same sitemap fetch and prints each host's wall time as `seconds`. It stays read-only: real HTTP, no database.

## 2. Live check

Run by the controller at 2026-09-25 08:15:32 UTC on the branch: `scripts/snapshot_rival.py skechers.in skechers.com crocs.in`, real HTTP, no database, no model spend.

| Domain | Slice 12 URLs | Slice 12 complete | Slice 12 fetches | Slice 14 URLs | Slice 14 complete | Slice 14 fetches | Slice 14 seconds |
|---|---|---|---|---|---|---|---|
| skechers.in | 2,765 | no | 15 | 3,017 | yes | 15 | 17.0 |
| skechers.com | 3,015 | no | not recorded | 5,478 | yes | 21 | 24.9 |
| crocs.in | 654 | no | 15 | 2,101 | yes | 15 | 13.2 |

Slice 12's skechers.in and crocs.in numbers are from its §2 script run; skechers.com's is from the first worker pass (findings-slice12 §5), which recorded no fetch count. Slice 12 recorded no seconds per host (69 s for its five domains in all).

Error lines:
- Slice 12, in its findings' summary wording (findings-slice12 does not quote the stored strings): skechers.in "`sitemap_1-custom.xml` cut off or not XML" and crocs.in "`sitemap_product_product.xml` cut off or not XML" (§2 table); skechers.com "the product and image sitemaps cut off or not XML" (§5 table).
- Slice 14: none, on all three hosts. skechers.in skipped 1 URL for robots.txt, as in slice 12.

**What this shows:**
- **All three domains are now complete**, with more URLs than slice 12: +252 on skechers.in, +2,463 on skechers.com, +1,447 on crocs.in.
- **Every host finished inside 60 s.** Run 1 has seven due domains, so each gets `max(60, 420 // 7)` = 60 s. The slowest, skechers.com, took 24.9 s. A host over its budget would be stored as "out of time" with none of its URLs kept.
- The file cap (50) and the URL ceiling (50,000) were not reached. Fetches include robots.txt and the 11 sampled pages, so skechers.com's 21 fetches read 9 sitemap files (21 − robots.txt − 11 pages), well under 50; the most URLs was 5,478.
- These are one run's timings from one machine; the worker's timings on dev were not measured.

## 3. Deferred / decisions

From the spec (the first three approved by the user through the design sections, as built, on 2026-09-25; the fourth follows from the approach the user chose):
- The 30 s deadline per fetch stays for sitemap files. Cost: a file that cannot download in 30 s stays incomplete; the fix is a `deadline` keyword shaped like `cap`.
- The URL ceiling cuts in sitemap order, not newest first. Cost: on a site over 50,000 URLs the newest products may be dropped.
- The job budget is split equally with a 60 s floor. Cost: one slow site gets less time when many domains are due, and an out-of-time domain keeps none of the URLs it read.
- Each file is parsed whole, not streamed. Cost: peak memory of one 50 MB file plus its entries, a few hundred MB, on one worker.

Rulings during the build:
- Ruling 1: the both-caps test became `test_file_cap_is_fifty_and_the_url_ceiling_can_stop_first` (4 files, ceiling 2). The planned test could not pass: with its caps the file cap tripped first, so its ceiling assertion would fail. Cost if wrong: none.
- Ruling 2: the floor test was rewritten to show the 60 s floor in the stored error ("within 60 s", with 10 domains) instead of asserting arithmetic. Cost if wrong: none (stronger test).
- Ruling 3: `parse_sitemap` is fed `r.body.encode("latin-1", "replace")`, lossless only for raw fetches, which production always uses. Cost if wrong: a caller with a non-raw fetch gets mangled Unicode URLs.
- Ruling 4: the read loop checks what the crossing chunk dropped, and the error reads "cut off at the size cap", true for any cap. Cost if wrong: a less specific error line.
- Ruling 5: `parse_sitemap` returns a fourth value, `cut`, so a gzip body cut at the unzip bound is reported as cut. Cost if wrong: four existing test edits.
- Ruling 6: the approved per-domain split stays; an out-of-time domain keeps none of what it read, and the script prints seconds so they can be compared with the 60 s budget. Cost if wrong: large sites lose partial reads until a later slice stores them.

Minor items deferred from the task reviews ("final triage" marks those the ledger flags for final triage):
- Final triage: after an exact-fit body, the extra read can time out and turn a good capped body into a status-0 error (`crawl.py`). Cost: a rare lost sitemap at exactly the cap.
- `cap` is not validated; `cap=0` makes zlib's `max_length` unlimited. Cost: an unbounded inflate for a caller passing 0 (none does).
- Final triage: the fetcher's gzip cut check can report a cut wrongly (trailer in a later chunk) or miss one (stream cut mid-match). `not z.eof` would fix the missed cut but not the false one: an exact-fit gzip body whose trailer arrives in a later chunk can be reported as cut either way. The item stays deferred. Cost: a wrong "cut off" line, or a missed one.
- No multi-chunk test (exact fit then a later non-empty chunk; exact-fit gzip). Cost: those paths are checked by reading only.
- The raw-mode test's second assertion should assert "�" in the body. Cost: a weaker assertion.
- Final triage: the Latin-1 re-encode corrupts non-raw bodies ("é" becomes "not well-formed XML"; characters above U+00FF become "?"). Ruling 3's cost made concrete. Cost: only a non-raw caller is affected.
- Final triage: `parser.feed` gets the whole body at once, so the full tree is built before any `clear()`; peak memory is not bounded by clearing. Cost: higher peak memory on a 50 MB file than clearing suggests.
- A duplicate `import gzip as gz` inside a test (plan-mandated). Cost: cosmetic.
- A multi-member gzip body reads only the first member and reports "not well-formed XML". Cost: such a sitemap stays incomplete.
- Final triage (fixed in the final review): the worst case is about 570 s of fetching with four due domains (the 420 s budget, the last domain's 105 s share, and one fetch of up to ~45 s, since each read may wait 15 s and the 30 s deadline is checked after a chunk), then parsing and the write, against claim_job's 600 s stale cutoff. Cost: going past 600 s lets another worker's claim_job mark the job failed while its crawls are still written.
- The 50 MiB cap in production depends on `fetch is http_fetch`; untested, and a wrapped `http_fetch` would fall back to 512 KiB silently. Cost: big sitemaps cut again after such a refactor.
- `test_domains_the_job_never_reaches_stay_due` does not assert how the first domain ended. Cost: a weaker test.
- `iter([0.0] * 4)` ties a test to the exact number of clock reads. Cost: a brittle test.

Nits from the final re-review, deferred:
- An uneven line break in the `RIVAL_JOB_SECONDS` comment in `worker.py`. Cost: cosmetic.
- The worst-case item above is marked fixed but sits in this deferred list. Cost: a misleading placement.

## 4. Not covered by tests
- Real gzip sitemaps served without Content-Encoding. The tests fake them. The live check's output does not list the sitemap URLs it read, and ".gz" appears nowhere in it, so it neither shows nor rules out that a `.gz` file was read.
- Memory at a real 50 MB file. Only the fetcher's two gzip-bomb tests measure memory, with tracemalloc (`test_a_gzip_bomb_is_decoded_only_up_to_the_cap_in_bounded_memory`, `test_a_gzip_bomb_stays_bounded_at_a_custom_cap`); `parse_sitemap`'s 50 MiB unzip step is not memory-measured.
- The exact 50,000-URL boundary against a real site; the tests use a small monkeypatched ceiling, and no live host came near it.
- The worker's per-domain budget on dev; the live check ran the script, not the worker.
