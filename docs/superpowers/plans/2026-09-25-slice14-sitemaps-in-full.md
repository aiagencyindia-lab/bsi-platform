# Slice 14: Read Big Competitor Sitemaps In Full — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The competitor crawl reads each sitemap file up to 50 MiB (gzip included), up to 50 files and 50,000 URLs per domain, marks incompleteness exactly, and gives every due domain its own time budget.

**Architecture:** `crawl.http_fetch` gains a per-call `cap`, a lossless `raw` mode and a `truncated` flag; nothing else about the SSRF guard changes. `rivals.parse_sitemap` takes bytes and unzips gzip by magic bytes; `snapshot_domain` takes a separate `sitemap_fetch` and applies the URL and file caps. `run_rival_crawl` builds the sitemap fetch with `functools.partial`, splits the job budget per domain, and stores every out-of-time domain.

**Tech Stack:** Python 3.13, httpx, zlib, xml.etree, SQLAlchemy 2, Postgres; pytest with fake transports and fake fetches. No web change.

**Spec:** `docs/superpowers/specs/2026-09-25-slice14-sitemaps-in-full-design.md`

## Global Constraints

- The SSRF guard in `http_fetch` (scheme/port checks, every resolved address public, pinned connection with SNI + Host, 30 s deadline, redirects re-checked, POST never redirected) must not change. `cap` only replaces the constant inside the read loop.
- Every other caller keeps the 512 KiB default: page score, crawlability and entity audits, Wikidata, webhook POST.
- The `Fetch` alias `Callable[[str, str], Response]` is unchanged; test fakes stay two-argument.
- No transaction may be open during an HTTP fetch (existing `pg_stat_activity` test in `tests/integration/test_rival_crawl.py` must keep passing).
- Live-check causes are stated as observed, never inferred.
- ruff line length 80; `mypy --strict` on `packages/core/bsi_core`.
- Subagents: "Do NOT edit tests/conftest.py or create databases; never touch the dev DB, the network or the worker loop." Before a full-suite run: `pgrep -fl "bsi-platform-wt.*pytest"` and wait if another worktree's pytest is running (shared test DB).
- Start every Bash command with `cd /Users/vineet/Downloads/ADK/bsi-platform &&` (the cwd resets).
- Commit trailer: the `Co-Authored-By` line from the current session reminder.
- Gate: `uv run ruff format . && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100`, then `cd apps/web && npm run gate`.

---

### Task 1: Fetcher — `cap`, `raw`, `truncated`, `SITEMAP_CAP_BYTES`

**Files:**
- Modify: `packages/core/bsi_core/crawl.py` (constants ~43-49; `Response` ~57-65; `http_fetch` signature ~231-240 and read loop ~308-320)
- Test: `tests/unit/test_http_fetch.py` (append)

**Interfaces:**
- Produces: `Response.truncated: bool = False`; `http_fetch(url, user_agent, *, resolve=..., transport=None, method="GET", body=None, content_type=None, cap: int = BODY_CAP_BYTES, raw: bool = False)`; `SITEMAP_CAP_BYTES = 50 * 1024 * 1024`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_http_fetch.py` (imports at the top already include `BODY_CAP_BYTES, http_fetch`, `httpx`, `tracemalloc`, `zlib`; add `SITEMAP_CAP_BYTES` to the `bsi_core.crawl` import):
```python
def test_a_cut_body_is_flagged_and_an_exact_fit_is_not():
    big = b"a" * (BODY_CAP_BYTES * 3)
    r, _ = fetch(
        "https://nike.com/",
        {"nike.com": [PUBLIC]},
        lambda q: httpx.Response(200, content=big),
    )
    assert (r.status, len(r.body), r.truncated) == (200, BODY_CAP_BYTES, True)
    exact = b"b" * BODY_CAP_BYTES
    r, _ = fetch(
        "https://nike.com/",
        {"nike.com": [PUBLIC]},
        lambda q: httpx.Response(200, content=exact),
    )
    assert (len(r.body), r.truncated) == (BODY_CAP_BYTES, False)


def test_a_custom_cap_is_honoured():
    body = b"c" * 10_000
    t = server(lambda q: httpx.Response(200, content=body))
    r = http_fetch(
        "https://nike.com/",
        "UA",
        resolve=dns({"nike.com": [PUBLIC]}),
        transport=t,
        cap=4_000,
    )
    assert (len(r.body), r.truncated) == (4_000, True)
    t = server(lambda q: httpx.Response(200, content=body))
    r = http_fetch(
        "https://nike.com/",
        "UA",
        resolve=dns({"nike.com": [PUBLIC]}),
        transport=t,
        cap=SITEMAP_CAP_BYTES,
    )
    assert (len(r.body), r.truncated) == (10_000, False)


def test_a_gzip_bomb_stays_bounded_at_a_custom_cap():
    bomb = gz_zeros(256 << 20)
    cap = 2 << 20
    tracemalloc.start()
    try:
        t = server(encoded(bomb, "gzip"))
        r = http_fetch(
            "https://nike.com/",
            "UA",
            resolve=dns({"nike.com": [PUBLIC]}),
            transport=t,
            cap=cap,
        )
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert (r.status, len(r.body), r.truncated) == (200, cap, True)
    assert peak < 12 * 1024 * 1024, peak


def test_raw_mode_round_trips_the_exact_bytes():
    payload = b"\x1f\x8b\x08\x00\xff\xfe<urlset/>\xe9"
    t = server(
        lambda q: httpx.Response(
            200,
            headers={"Content-Type": "text/xml; charset=utf-8"},
            content=payload,
        )
    )
    r = http_fetch(
        "https://nike.com/s.xml.gz",
        "UA",
        resolve=dns({"nike.com": [PUBLIC]}),
        transport=t,
        raw=True,
    )
    assert r.ok and r.body.encode("latin-1") == payload
    t = server(lambda q: httpx.Response(200, content=payload))
    r = http_fetch(
        "https://nike.com/s.xml.gz",
        "UA",
        resolve=dns({"nike.com": [PUBLIC]}),
        transport=t,
    )
    assert r.body.encode("latin-1", "replace") != payload  # default decodes
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_http_fetch.py -k "cut_body or custom_cap or custom_cap or raw_mode" -x`
Expected: FAIL with `ImportError: cannot import name 'SITEMAP_CAP_BYTES'` (then `TypeError ... unexpected keyword argument 'cap'` once the import exists).

- [ ] **Step 3: Implement**

In `crawl.py`, after `BODY_CAP_BYTES`:
```python
SITEMAP_CAP_BYTES = 50 * 1024 * 1024  # the sitemap protocol's file limit
```
`Response` gains a field:
```python
@dataclass
class Response:
    status: int
    body: str = ""
    error: str | None = None
    truncated: bool = False  # the body was cut at the fetch's cap

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300
```
`http_fetch` signature gains, after `content_type`:
```python
    cap: int = BODY_CAP_BYTES,
    raw: bool = False,
```
and its docstring gains: "`cap` bounds the decoded bytes kept (every guard is unchanged); `truncated` says the cap cut the body. `raw=True` decodes the bytes as Latin-1, which is lossless: `body.encode('latin-1')` gives the exact bytes back." The read loop becomes (the loop variable is renamed from `raw` to `chunk`, because `raw` is now the keyword):
```python
                    z = _decompressor(r.headers.get("content-encoding", ""))
                    buf = bytearray()
                    cut = False
                    chunks = r.iter_raw()
                    for chunk in chunks:
                        room = cap - len(buf)
                        # max_length bounds each inflate to what fits.
                        buf += z.decompress(chunk, room) if z else chunk[:room]
                        if time.monotonic() > deadline:
                            return Response(0, "", _TIMED_OUT)
                        if len(buf) >= cap:
                            # Cut only if the stream had more to give.
                            cut = next(chunks, b"") != b"" or bool(
                                z and z.unconsumed_tail
                            )
                            break
                    data = bytes(buf)
                    text_body = (
                        data.decode("latin-1")
                        if raw
                        else _decode(data, r.charset_encoding)
                    )
                    return Response(r.status_code, text_body, truncated=cut)
```
Note for the implementer: `z.unconsumed_tail` is non-empty when `max_length` stopped the inflate with input left, which is how a gzip bomb shows it was cut. `next(chunks, b"")` reads at most one more chunk. If mypy complains about `z` being `Any`, keep the `bool(...)` wrapper.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_http_fetch.py tests/unit/test_crawl.py && uv run mypy`
Expected: all PASS, including the existing `test_the_body_is_cut_at_the_byte_cap` and `test_a_gzip_bomb_is_decoded_only_up_to_the_cap_in_bounded_memory`; mypy clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/crawl.py tests/unit/test_http_fetch.py && git commit -m "feat(crawl): http_fetch takes a cap, reports truncation, and can return raw bytes"
```

---

### Task 2: Sitemap reading — bytes, gzip, exact errors, URL and file caps, `sitemap_fetch`

**Files:**
- Modify: `packages/core/bsi_core/rivals.py` (imports ~8-30; constants ~33-37; `parse_sitemap` ~62-104; `snapshot_domain` ~141-257)
- Test: `tests/unit/test_rivals.py`

**Interfaces:**
- Consumes: `Response.truncated`, `SITEMAP_CAP_BYTES` from Task 1.
- Produces: `MAX_SITEMAP_FETCHES = 50`, `MAX_URLS = 50_000`; `parse_sitemap(body: bytes) -> (root_tag, entries, closed)`; `snapshot_domain(host, fetch, known, *, pause=0.0, sitemap_fetch: Fetch | None = None)`; error lines `"sitemap {url}: cut off at 50 MiB"`, `"sitemap {url}: not well-formed XML"`, `"sitemap {url}: URL ceiling of 50000 reached"`.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_rivals.py`:
- Add `MAX_URLS` to the `bsi_core.rivals` import and `import gzip` at the top.
- Change the three existing `parse_sitemap(...)` string calls to bytes: `parse_sitemap(body[: len(body) - 20].encode())`, `parse_sitemap(b"\x1f\x8b\x08garbage")`, `parse_sitemap(b"")`, and in `test_parse_urlset_and_index` wrap both bodies with `.encode()`.
- In `test_index_children_are_capped_and_mark_incomplete` the child count `MAX_SITEMAP_FETCHES + 2` now means 52 fakes; keep it (it is cheap).
- Append:
```python
def test_gzip_sitemap_without_content_encoding_is_unzipped():
    body = urlset(("https://r.com/a", "2026-09-01"))
    kind, locs, ok = parse_sitemap(gzip.compress(body.encode()))
    assert (kind, ok) == ("urlset", True)
    assert locs == [("https://r.com/a", "2026-09-01")]


def test_a_gzip_sitemap_over_the_cap_is_not_clean(monkeypatch):
    import bsi_core.rivals as rivals

    monkeypatch.setattr(rivals, "SITEMAP_CAP_BYTES", 200)
    body = urlset(*[(f"https://r.com/p{i}", None) for i in range(40)])
    kind, locs, ok = parse_sitemap(gzip.compress(body.encode()))
    assert kind == "urlset" and ok is False
    assert 0 < len(locs) < 40


def test_snapshot_reports_truncation_and_bad_xml_exactly():
    good = urlset(("https://r.com/a", None))
    fetch = site(
        {
            "https://r.com/sitemap.xml": Response(200, good, truncated=True),
            "https://r.com/": HOME,
        }
    )
    snap = snapshot_domain("r.com", fetch, known=set())
    assert snap.complete is False
    assert "sitemap https://r.com/sitemap.xml: cut off at 50 MiB" in snap.errors
    assert "https://r.com/a" in snap.urls  # what was read is kept
    fetch = site(
        {"https://r.com/sitemap.xml": good[:-12], "https://r.com/": HOME}
    )
    snap = snapshot_domain("r.com", fetch, known=set())
    assert (
        "sitemap https://r.com/sitemap.xml: not well-formed XML" in snap.errors
    )
    assert not any("cut off" in e for e in snap.errors)


def test_url_ceiling_stops_the_read_and_marks_incomplete(monkeypatch):
    import bsi_core.rivals as rivals

    monkeypatch.setattr(rivals, "MAX_URLS", 5)
    s1 = urlset(*[(f"https://r.com/a{i}", None) for i in range(3)])
    s2 = urlset(*[(f"https://r.com/b{i}", None) for i in range(4)])
    s3 = urlset(("https://r.com/c0", None))
    fetch = site(
        {
            "https://r.com/sitemap.xml": index(
                "https://r.com/s1.xml", "https://r.com/s2.xml", "https://r.com/s3.xml"
            ),
            "https://r.com/s1.xml": s1,
            "https://r.com/s2.xml": s2,
            "https://r.com/s3.xml": s3,
            "https://r.com/": HOME,
        }
    )
    snap = snapshot_domain("r.com", fetch, known=set())
    assert len(snap.urls) == 5 and snap.complete is False
    assert "sitemap https://r.com/s2.xml: URL ceiling of 5 reached" in snap.errors
    assert "https://r.com/s3.xml" not in fetch.calls  # queue emptied
    assert "https://r.com/" in fetch.calls  # pages still sampled


def test_file_cap_is_fifty_and_both_caps_can_apply(monkeypatch):
    import bsi_core.rivals as rivals

    assert MAX_SITEMAP_FETCHES == 50 and MAX_URLS == 50_000
    monkeypatch.setattr(rivals, "MAX_SITEMAP_FETCHES", 3)
    monkeypatch.setattr(rivals, "MAX_URLS", 2)
    children = [f"https://r.com/s{i}.xml" for i in range(4)]
    pages = {"https://r.com/sitemap.xml": index(*children), "https://r.com/": HOME}
    pages |= {u: urlset((u.replace(".xml", "/p"), None)) for u in children}
    fetch = site(pages)
    snap = snapshot_domain("r.com", fetch, known=set())
    assert len(snap.urls) == 2 and snap.complete is False
    assert any("URL ceiling" in e for e in snap.errors)


def test_sitemap_fetch_serves_sitemaps_and_fetch_serves_pages():
    seen = {"sitemap": [], "page": []}

    def sitemap_fetch(url, ua):
        seen["sitemap"].append(url)
        return Response(200, urlset(("https://r.com/a", None)))

    def fetch(url, ua):
        seen["page"].append(url)
        if url.endswith("/robots.txt"):
            return Response(200, "User-agent: *\nAllow: /\n")
        return Response(200, HOME)

    snap = snapshot_domain(
        "r.com", fetch, known=set(), sitemap_fetch=sitemap_fetch
    )
    assert seen["sitemap"] == ["https://r.com/sitemap.xml"]
    assert "https://r.com/robots.txt" in seen["page"]
    assert "https://r.com/" in seen["page"] and "https://r.com/a" in seen["page"]
    assert snap.fetches == 4
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_rivals.py -x`
Expected: FAIL with `ImportError: cannot import name 'MAX_URLS'`.

- [ ] **Step 3: Implement**

In `rivals.py`: add `import zlib`; import `SITEMAP_CAP_BYTES` from `.crawl`; constants:
```python
# The root sitemap plus children of an index, 50 files in all.
MAX_SITEMAP_FETCHES = 50
MAX_URLS = 50_000  # URLs kept per domain per crawl
MAX_NEW_PAGES = 10
```
`parse_sitemap`:
```python
def parse_sitemap(
    body: bytes,
) -> tuple[str, list[tuple[str, str | None]], bool]:
    """(root tag, [(loc, lastmod)], closed cleanly). Gzip bytes (magic
    1f 8b) are inflated first, under SITEMAP_CAP_BYTES; a body cut at a
    cap or malformed XML is not clean, and whatever was read before the
    fault is still returned. Namespaces are ignored, so only <loc> and
    <lastmod> directly under a <url>/<sitemap> entry count."""
    cut = False
    if body[:2] == b"\x1f\x8b":
        z = zlib.decompressobj(47)
        try:
            body = z.decompress(body, SITEMAP_CAP_BYTES)
        except zlib.error:
            return "none", [], False
        cut = bool(z.unconsumed_tail)
    parser: ET.XMLPullParser[ET.Element] = ET.XMLPullParser(
        events=("start", "end")
    )
    ...  # the existing body, unchanged, feeding `body` (bytes) to parser.feed
    return root or "none", locs, closed and not cut
```
`snapshot_domain`:
```python
def snapshot_domain(
    host: str,
    fetch: Fetch,
    known: set[str],
    *,
    pause: float = 0.0,
    sitemap_fetch: Fetch | None = None,
) -> Snapshot:
    """... `sitemap_fetch` (default `fetch`) reads sitemap files; the
    worker passes http_fetch bound to SITEMAP_CAP_BYTES and raw=True."""
    snap = Snapshot()
    files = sitemap_fetch or fetch

    def get(url: str, via: Fetch = fetch) -> Response:
        if snap.fetches and pause:
            time.sleep(pause)
        snap.fetches += 1
        return via(url, BROWSER_UA)
```
In the sitemap loop: `r = get(url, files)`; then
```python
        # raw mode decoded the bytes as Latin-1; str fakes are ASCII.
        kind, locs, clean = parse_sitemap(r.body.encode("latin-1", "replace"))
        ...
        if r.truncated:
            snap.complete = False
            snap.errors.append(f"sitemap {url}: cut off at 50 MiB")
        elif not clean:
            snap.complete = False
            snap.errors.append(f"sitemap {url}: not well-formed XML")
        if kind == "sitemapindex":
            queue += [loc for loc, _ in locs if _owned_sitemap(host, loc)]
        elif kind != "urlset":
            snap.complete = False
            if clean:
                snap.errors.append(f"sitemap {url}: not a sitemap (<{kind}>)")
        else:
            for loc, lastmod in locs:
                if not _owned_sitemap(host, loc):
                    continue
                if loc not in snap.urls and len(snap.urls) >= MAX_URLS:
                    snap.complete = False
                    snap.errors.append(
                        f"sitemap {url}: URL ceiling of {MAX_URLS} reached"
                    )
                    queue.clear()
                    break
                snap.urls[loc] = lastmod
```
The file-cap error text keeps its shape ("more than 50 sitemap files; the rest were not read"). Everything after the loop is unchanged.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/unit/test_rivals.py tests/unit/test_crawl.py tests/integration/test_rival_crawl.py && uv run mypy`
Expected: all PASS (the integration file still passes because `snapshot_domain`'s defaults are unchanged); mypy clean.

- [ ] **Step 5: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add packages/core/bsi_core/rivals.py tests/unit/test_rivals.py && git commit -m "feat(rivals): sitemaps read as bytes with gzip, exact cut-off errors, 50-file and 50,000-URL caps"
```

---

### Task 3: Worker — sitemap fetch, per-domain budget, every out-of-time domain stored; script

**Files:**
- Modify: `apps/workers/bsi_workers/worker.py` (imports; constants after `RIVAL_UPSERT_CHUNK` ~74; `run_rival_crawl` ~526-575), `scripts/snapshot_rival.py`
- Test: `tests/integration/test_rival_crawl.py` (~313-372 and append)

**Interfaces:**
- Consumes: `SITEMAP_CAP_BYTES`, `http_fetch(cap=, raw=)`, `snapshot_domain(..., sitemap_fetch=)`.
- Produces: `worker.RIVAL_DOMAIN_FLOOR_SECONDS = 60`, `worker.SITEMAP_FETCH`, `run_rival_crawl(org_id, brand_id, job_id, fetch=http_fetch, clock=time.monotonic, sitemap_fetch: Fetch | None = None)`.

- [ ] **Step 1: Update and write the failing tests**

In `tests/integration/test_rival_crawl.py`:
- `test_first_domain_out_of_time_is_stored_and_waits`: the clock is now read more often (job start, per-domain check, each deadline wrapper). Replace `ticks = iter([0.0])` with `ticks = iter([0.0] * 4)` and the error assertion with `f"{worker.RIVAL_JOB_SECONDS} s"` unchanged (one domain: per = 420).
- Rename `test_a_later_domain_out_of_time_is_not_stored_and_stays_due` to `test_every_out_of_time_domain_is_stored_incomplete` and change its tail to:
```python
    stored = _direct(owner, org, bid, fetch, lambda: now[0])
    assert stored == 2
    with owner() as s:
        rows = {c.domain: c for c in s.scalars(select(m.RivalCrawl))}
    assert (rows["a.com"].complete, rows["a.com"].urls_seen) == (True, 1)
    assert rows["b.com"].complete is False and rows["b.com"].urls_seen == 0
    assert rows["b.com"].errors == [
        "out of time: the crawl did not finish within "
        f"{max(worker.RIVAL_DOMAIN_FLOOR_SECONDS, worker.RIVAL_JOB_SECONDS // 2)} s"
    ]
    assert due() == []  # both stored; both wait 7 days
```
  but note: with `now[0] = 1e9` set during b.com's first fetch, the job-level check between domains sees 0.0 before b.com starts, so b.com is crawled and runs out of time. Keep `now` at 0.0 until b.com's first fetch, as the existing test does.
- Append:
```python
def test_domains_the_job_never_reaches_stay_due(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _rival(owner, org, bid, domains=("a.com", "b.com"))
    now = [0.0]
    inner = _fake({"a.com": {"https://a.com/": HOME}})

    def fetch(url, ua):
        if url == "https://a.com/":  # a.com's last fetch eats the job budget
            now[0] = 1e9
        return inner(url, ua)

    stored = _direct(owner, org, bid, fetch, lambda: now[0])
    assert stored == 1
    with owner() as s:
        assert [c.domain for c in s.scalars(select(m.RivalCrawl))] == ["a.com"]
    assert due() == [bid]  # b.com never started


def test_the_per_domain_budget_has_a_floor(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _rival(owner, org, bid, domains=tuple(f"d{i}.com" for i in range(10)))
    seen = []

    def fetch(url, ua):
        seen.append(url)
        return _fake({})(url, ua)

    _direct(owner, org, bid, fetch, lambda: 0.0)
    assert worker.RIVAL_DOMAIN_FLOOR_SECONDS == 60
    assert max(60, worker.RIVAL_JOB_SECONDS // 10) == 60
    assert len({u.split("/")[2] for u in seen}) == 10  # every domain crawled


def test_sitemaps_go_through_the_sitemap_fetch(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid, domains=("r.com",))
    inner = _fake({"r.com": {"https://r.com/": HOME}})
    sitemap_calls = []

    def sitemap_fetch(url, ua):
        sitemap_calls.append(url)
        return Response(200, urlset(("https://r.com/x", None)))

    jid = _job(owner, org, bid, "crawl_rivals", "running")
    worker.run_rival_crawl(
        org.id, bid, jid, inner, clock=lambda: 0.0, sitemap_fetch=sitemap_fetch
    )
    assert sitemap_calls == ["https://r.com/sitemap.xml"]
    assert "https://r.com/x" in _pages(owner, cid)


def test_the_default_sitemap_fetch_is_http_fetch_bound_to_the_sitemap_cap():
    from bsi_core.crawl import SITEMAP_CAP_BYTES, http_fetch

    f = worker.SITEMAP_FETCH
    assert f.func is http_fetch
    assert f.keywords == {"cap": SITEMAP_CAP_BYTES, "raw": True}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run pytest -q tests/integration/test_rival_crawl.py -k "out_of_time or never_reaches or floor or sitemap_fetch or SITEMAP" -x`
Expected: FAIL with `AttributeError: module 'bsi_workers.worker' has no attribute 'RIVAL_DOMAIN_FLOOR_SECONDS'` (or `SITEMAP_FETCH`).

- [ ] **Step 3: Implement**

In `worker.py`: `from functools import partial`; add `SITEMAP_CAP_BYTES` to the `bsi_core.crawl` import; after `RIVAL_UPSERT_CHUNK`:
```python
# Each due domain gets RIVAL_JOB_SECONDS / len(due), never less than this.
RIVAL_DOMAIN_FLOOR_SECONDS = 60
# Sitemap files may be 50 MB; raw=True keeps the bytes for gzip detection.
SITEMAP_FETCH: Fetch = partial(http_fetch, cap=SITEMAP_CAP_BYTES, raw=True)
```
`run_rival_crawl`:
```python
def run_rival_crawl(
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    job_id: uuid.UUID,
    fetch: Fetch = http_fetch,
    clock: Callable[[], float] = time.monotonic,
    sitemap_fetch: Fetch | None = None,
) -> int:
    """Snapshot each due competitor domain; returns how many were stored.

    Reads, then fetches with no transaction open, then writes, each
    domain in its own savepoint. Each domain gets an equal share of
    RIVAL_JOB_SECONDS (floor RIVAL_DOMAIN_FLOOR_SECONDS); a domain that
    runs out of time is stored as an incomplete crawl so it waits its
    week; domains the job never reaches stay due. A domain that crashes
    or fails its write is not stored and stays due. Crawls stay
    baselines until one reads URLs."""
    files = sitemap_fetch or (SITEMAP_FETCH if fetch is http_fetch else fetch)
    ...  # the existing read of `due` and `known`, unchanged
    per = max(RIVAL_DOMAIN_FLOOR_SECONDS, RIVAL_JOB_SECONDS // max(len(due), 1))
    job_end = clock() + RIVAL_JOB_SECONDS
    done = []
    for cid, domain, baseline in due:
        if clock() > job_end:
            log.info("brand %s: rival crawl job budget spent before %s", brand_id, domain)
            break
        try:
            snap = snapshot_domain(
                domain,
                with_deadline(fetch, per, clock),
                known[cid],
                pause=PAUSE_SECONDS,
                sitemap_fetch=with_deadline(files, per, clock),
            )
        except OutOfTime:
            log.info("brand %s: rival crawl out of time at %s", brand_id, domain)
            late = Snapshot(complete=False)
            late.errors.append(
                f"out of time: the crawl did not finish within {per} s"
            )
            done.append((cid, domain, baseline, late))
            continue
        except Exception:
            log.exception("brand %s: rival crawl of %s failed", brand_id, domain)
            continue
        done.append((cid, domain, baseline, snap))
```
The write phase is unchanged. In `scripts/snapshot_rival.py`:
```python
from functools import partial

from bsi_core.crawl import PAUSE_SECONDS, SITEMAP_CAP_BYTES, http_fetch
from bsi_core.rivals import snapshot_domain

SITEMAP_FETCH = partial(http_fetch, cap=SITEMAP_CAP_BYTES, raw=True)
...
    snap = snapshot_domain(
        host, http_fetch, set(), pause=PAUSE_SECONDS, sitemap_fetch=SITEMAP_FETCH
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-platform && uv run ruff format . && uv run ruff check . && uv run mypy && uv run pytest -q tests/integration/test_rival_crawl.py tests/unit/test_rivals.py`, then (after `pgrep -fl "bsi-platform-wt.*pytest"` shows nothing) `uv run pytest -q --cov=bsi_core.metrics --cov-fail-under=100`
Expected: all PASS (1287 + the new tests), coverage 100%.

- [ ] **Step 5: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add apps/workers/bsi_workers/worker.py scripts/snapshot_rival.py tests/integration/test_rival_crawl.py && git commit -m "feat(worker): sitemap fetch at the 50 MiB cap, a time budget per domain, every late domain stored"
```

---

### Task 4: Live check, findings doc, docs index

**Files:**
- Create: `docs/findings-slice14.md`
- Modify: `docs/README.md` (new "Slice 14: sitemaps in full" section before "Run data and evaluation sets…")

- [ ] **Step 1: Live check (controller, read-only, real HTTP, no DB, no spend)**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && set -a && source .env && set +a && uv run python scripts/snapshot_rival.py skechers.in skechers.com crocs.in > .superpowers/sdd/2026-09-25-slice14-sitemaps-in-full/live-check.json
```
Record per domain: `urls`, `complete`, `fetches`, `errors`, wall time. State causes as observed.

- [ ] **Step 2: Write `docs/findings-slice14.md`**

Sections: 1. What was built (fetcher, sitemap reading, worker, script). 2. Live check: a table with slice 12's numbers (skechers.in 2,765 / skechers.com 3,015 / crocs.in 654, all incomplete) beside the new ones, and every error line verbatim. 3. Deferred / decisions: the spec's four rulings and every ruling and deferred minor from the ledger, one line each with cost. 4. Not covered by tests: real gzip-without-Content-Encoding sitemaps (only faked), memory at a real 50 MB file (only the bomb test), the exact 50,000-URL boundary against a real site.

- [ ] **Step 3: Docs index**

Add to `docs/README.md`:
```markdown
## Slice 14: sitemaps in full

| Document | What it is |
|---|---|
| [superpowers/specs/2026-09-25-slice14-sitemaps-in-full-design.md](superpowers/specs/2026-09-25-slice14-sitemaps-in-full-design.md) | Design spec: sitemap files read up to 50 MiB with gzip, 50 files and 50,000 URLs per domain, exact cut-off errors, a time budget per domain. |
| [superpowers/plans/2026-09-25-slice14-sitemaps-in-full.md](superpowers/plans/2026-09-25-slice14-sitemaps-in-full.md) | Implementation plan, Tasks 1–4. |
| [findings-slice14.md](findings-slice14.md) | Results: the read-only re-check of skechers.in, skechers.com and crocs.in against the slice 12 numbers, and what is deferred. |
```

- [ ] **Step 4: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-platform && git add docs/findings-slice14.md docs/README.md && git commit -m "docs: slice 14 findings and index"
```

## Verification

- Both gates locally and in CI; read the CI log for " passed, " and "Compiled successfully".
- The live check's three domains report more URLs than slice 12's, or an exact error line saying why not.
- After merge: dev needs no migration. The worker stays off unless the user starts it; when it runs, the Competitors tab's site-changes section shows the new `urls_seen`.
