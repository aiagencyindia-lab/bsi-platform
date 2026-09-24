"""Competitor site crawl: sitemap parsing and the per-domain snapshot."""

import pytest
from bsi_core.crawl import BROWSER_UA, Response
from bsi_core.rivals import (
    MAX_NEW_PAGES,
    MAX_SITEMAP_FETCHES,
    MAX_TYPE_CHARS,
    MAX_URL_CHARS,
    OutOfTime,
    parse_sitemap,
    snapshot_domain,
    with_deadline,
)

NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def urlset(*locs):
    rows = "".join(
        f"<url><loc>{u}</loc>{f'<lastmod>{d}</lastmod>' if d else ''}</url>"
        for u, d in locs
    )
    return f'<?xml version="1.0"?><urlset {NS}>{rows}</urlset>'


def index(*locs):
    rows = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in locs)
    return f"<sitemapindex {NS}>{rows}</sitemapindex>"


def site(pages, robots="User-agent: *\nAllow: /\n"):
    """A fake fetch over a dict url -> body (str) or Response."""
    calls = []

    def fetch(url, ua):
        calls.append(url)
        assert ua == BROWSER_UA
        if url == "https://r.com/robots.txt" and robots is not None:
            return Response(200, robots)
        v = pages.get(url)
        if v is None:
            return Response(404, "")
        return v if isinstance(v, Response) else Response(200, v)

    fetch.calls = calls
    return fetch


HOME = (
    '<html><script type="application/ld+json">'
    '{"@type":"Organization"}</script></html>'
)


def test_parse_urlset_and_index():
    kind, locs, ok = parse_sitemap(
        urlset(("https://r.com/a", "2026-09-01"), ("https://r.com/b", None))
    )
    assert (kind, ok) == ("urlset", True)
    assert locs == [
        ("https://r.com/a", "2026-09-01"),
        ("https://r.com/b", None),
    ]
    kind, locs, ok = parse_sitemap(index("https://r.com/s1.xml"))
    assert (kind, locs, ok) == (
        "sitemapindex",
        [("https://r.com/s1.xml", None)],
        True,
    )


def test_truncated_or_garbage_sitemap_is_not_clean():
    body = urlset(("https://r.com/a", None), ("https://r.com/b", None))
    kind, locs, ok = parse_sitemap(body[: len(body) - 20])
    assert kind == "urlset" and ok is False
    assert ("https://r.com/a", None) in locs  # what was read is kept
    assert parse_sitemap("\x1f\x8b\x08garbage")[2] is False
    assert parse_sitemap("")[2] is False


def test_snapshot_reads_the_sitemap_home_and_new_pages():
    pages = {
        "https://r.com/sitemap.xml": urlset(
            ("https://r.com/old", "2026-01-01"),
            ("https://r.com/new1", "2026-09-02"),
            ("https://r.com/new2", "2026-09-03"),
            ("https://other.com/x", None),  # off-host: dropped
        ),
        "https://r.com/": HOME,
        "https://r.com/new2": '<script type="application/ld+json">'
        '{"@graph":[{"@type":"Product"}]}</script>',
        "https://r.com/new1": "<p>no schema</p>",
    }
    fetch = site(pages)
    snap = snapshot_domain("r.com", fetch, known={"https://r.com/old"})
    assert set(snap.urls) == {
        "https://r.com/old",
        "https://r.com/new1",
        "https://r.com/new2",
    }
    assert snap.complete is True and snap.errors == []
    # newest lastmod first; the known URL is never fetched
    assert fetch.calls == [
        "https://r.com/robots.txt",
        "https://r.com/sitemap.xml",
        "https://r.com/",
        "https://r.com/new2",
        "https://r.com/new1",
    ]
    assert snap.fetches == len(fetch.calls)
    assert snap.domain_types == {
        "Organization": "https://r.com/",
        "Product": "https://r.com/new2",
    }
    by_url = {p["url"]: p for p in snap.pages}
    assert by_url["https://r.com/new2"]["types"] == ["Product"]
    assert by_url["https://r.com/new1"]["types"] == []


def test_robots_sitemap_lines_on_host_only():
    robots = (
        "User-agent: *\nAllow: /\nSitemap: https://evil.com/s.xml\n"
        "Sitemap: https://www.r.com/s.xml\n"
    )
    fetch = site(
        {
            "https://www.r.com/s.xml": urlset(("https://r.com/a", None)),
            "https://r.com/": HOME,
        },
        robots=robots,
    )
    snap = snapshot_domain("r.com", fetch, known=set())
    assert "https://evil.com/s.xml" not in fetch.calls
    assert "https://r.com/sitemap.xml" not in fetch.calls  # robots named one
    assert set(snap.urls) == {"https://r.com/a"}


def test_index_children_are_capped_and_mark_incomplete():
    children = [
        f"https://r.com/s{i}.xml" for i in range(MAX_SITEMAP_FETCHES + 2)
    ]
    pages = {
        "https://r.com/sitemap.xml": index(*children),
        "https://r.com/": HOME,
    }
    pages |= {u: urlset((u.replace(".xml", "/p"), None)) for u in children}
    fetch = site(pages)
    snap = snapshot_domain("r.com", fetch, known=set())
    sitemap_calls = [u for u in fetch.calls if u.endswith(".xml")]
    assert len(sitemap_calls) == MAX_SITEMAP_FETCHES
    assert snap.complete is False
    assert any("sitemap" in e for e in snap.errors)


def test_failed_child_or_truncated_sitemap_is_incomplete():
    body = urlset(*[(f"https://r.com/p{i}", None) for i in range(5)])
    fetch = site(
        {"https://r.com/sitemap.xml": body[:-30], "https://r.com/": HOME}
    )
    assert snapshot_domain("r.com", fetch, known=set()).complete is False
    fetch = site(
        {
            "https://r.com/sitemap.xml": index("https://r.com/s1.xml"),
            "https://r.com/": HOME,
        }
    )  # child 404
    assert snapshot_domain("r.com", fetch, known=set()).complete is False
    fetch = site({"https://r.com/": HOME})  # no sitemap at all
    snap = snapshot_domain("r.com", fetch, known=set())
    assert snap.complete is False and snap.urls == {}


def test_new_page_sample_is_capped_and_newest_first():
    locs = [
        (f"https://r.com/p{i:02d}", f"2026-09-{i + 1:02d}") for i in range(15)
    ]
    pages = {"https://r.com/sitemap.xml": urlset(*locs), "https://r.com/": HOME}
    fetch = site(pages)
    snap = snapshot_domain("r.com", fetch, known=set())
    sampled = [u for u in fetch.calls if "/p" in u]
    assert sampled == [
        f"https://r.com/p{i:02d}" for i in range(14, 14 - MAX_NEW_PAGES, -1)
    ]
    assert len(snap.urls) == 15  # every URL is still listed


def test_robots_disallowed_pages_are_skipped_not_fetched():
    robots = "User-agent: *\nDisallow: /private\n"
    pages = {
        "https://r.com/sitemap.xml": urlset(
            ("https://r.com/private/a", "2026-09-09"),
            ("https://r.com/ok", "2026-09-01"),
        ),
        "https://r.com/": HOME,
    }
    fetch = site(pages, robots=robots)
    snap = snapshot_domain("r.com", fetch, known=set())
    assert "https://r.com/private/a" not in fetch.calls
    assert snap.skipped == ["https://r.com/private/a"]
    assert "https://r.com/ok" in fetch.calls


def test_robots_disallow_all_fetches_nothing_more():
    fetch = site(
        {"https://r.com/sitemap.xml": urlset(("https://r.com/a", None))},
        robots="User-agent: *\nDisallow: /\n",
    )
    snap = snapshot_domain("r.com", fetch, known=set())
    assert fetch.calls == ["https://r.com/robots.txt"]
    assert snap.complete is False and snap.errors


@pytest.mark.parametrize("status", [0, 503])
def test_robots_unreachable_or_5xx_stops(status):
    def fetch(url, ua):
        return Response(status, "", "ConnectError" if status == 0 else None)

    snap = snapshot_domain("r.com", fetch, known=set())
    assert snap.fetches == 1 and snap.complete is False and snap.errors


def test_robots_4xx_means_no_restrictions():
    fetch = site(
        {
            "https://r.com/sitemap.xml": urlset(("https://r.com/a", None)),
            "https://r.com/": HOME,
        },
        robots=None,
    )
    snap = snapshot_domain("r.com", fetch, known=set())
    assert set(snap.urls) == {"https://r.com/a"} and snap.complete is True


def test_deadline_wrapper_refuses_late_fetches():
    now = [0.0]
    inner = site({})
    fetch = with_deadline(inner, 10, clock=lambda: now[0])
    fetch("https://r.com/robots.txt", BROWSER_UA)
    now[0] = 11
    with pytest.raises(OutOfTime):
        fetch("https://r.com/", BROWSER_UA)
    assert inner.calls == ["https://r.com/robots.txt"]


def test_image_sitemap_locs_do_not_replace_the_page_loc():
    body = (
        f'<urlset {NS} xmlns:image="http://www.google.com/schemas/'
        'sitemap-image/1.1"><url><loc>https://r.com/a</loc>'
        "<image:image><image:loc>https://cdn.r.com/a.jpg</image:loc>"
        "</image:image><lastmod>2026-09-01</lastmod></url></urlset>"
    )
    assert parse_sitemap(body) == (
        "urlset",
        [("https://r.com/a", "2026-09-01")],
        True,
    )


def test_undated_new_pages_come_after_dated_in_url_order():
    pages = {
        "https://r.com/sitemap.xml": urlset(
            ("https://r.com/z", None),
            ("https://r.com/a", None),
            ("https://r.com/b", "2026-09-01"),
            ("https://r.com/c", "2026-09-01"),
        ),
        "https://r.com/": HOME,
    }
    fetch = site(pages)
    snapshot_domain("r.com", fetch, known=set())
    assert fetch.calls[3:] == [
        "https://r.com/c",
        "https://r.com/b",
        "https://r.com/a",
        "https://r.com/z",
    ]


@pytest.mark.parametrize(
    "body", ["<html><body>Not found</body></html>", "<rss><channel/></rss>"]
)
def test_soft_404_or_non_sitemap_root_is_incomplete(body):
    fetch = site({"https://r.com/sitemap.xml": body, "https://r.com/": HOME})
    snap = snapshot_domain("r.com", fetch, known=set())
    assert snap.complete is False and snap.urls == {}
    assert any("not a sitemap" in e for e in snap.errors)


def test_overlong_locs_are_dropped_with_one_error_line():
    long = "https://r.com/" + "x" * (3_000 - len("https://r.com/"))
    edge = "https://r.com/" + "y" * (MAX_URL_CHARS - len("https://r.com/"))
    fetch = site(
        {
            "https://r.com/sitemap.xml": urlset(
                (long, None), (long + "2", None), (edge, None)
            ),
            "https://r.com/": HOME,
        }
    )
    snap = snapshot_domain("r.com", fetch, known=set())
    assert set(snap.urls) == {edge}
    assert snap.errors == [
        "sitemap https://r.com/sitemap.xml: 2 URLs dropped "
        "(too long or invalid)"
    ]
    assert snap.complete is True


def test_nul_locs_are_dropped(monkeypatch):
    # XML itself cannot carry NUL (expat rejects it), so stub the parser
    # to prove the guard.
    import bsi_core.rivals as rivals

    locs = [("https://r.com/a\x00b", None), ("https://r.com/ok", None)]
    monkeypatch.setattr(
        rivals, "parse_sitemap", lambda body: ("urlset", locs, True)
    )
    fetch = site({"https://r.com/sitemap.xml": "x", "https://r.com/": HOME})
    snap = snapshot_domain("r.com", fetch, known=set())
    assert set(snap.urls) == {"https://r.com/ok"}
    assert snap.errors == [
        "sitemap https://r.com/sitemap.xml: 1 URLs dropped "
        "(too long or invalid)"
    ]


def test_nul_or_overlong_types_are_dropped():
    bad = [
        '{"@type":"Bad\\u0000Type"}',
        '{"@type":"' + "T" * (MAX_TYPE_CHARS + 1) + '"}',
        '{"@type":"' + "T" * MAX_TYPE_CHARS + '"}',
        '{"@type":"Product"}',
    ]
    body = "".join(
        f'<script type="application/ld+json">{b}</script>' for b in bad
    )
    fetch = site({"https://r.com/": body})
    snap = snapshot_domain("r.com", fetch, known=set())
    assert snap.pages[0]["types"] == sorted(["T" * MAX_TYPE_CHARS, "Product"])
    assert set(snap.domain_types) == {"T" * MAX_TYPE_CHARS, "Product"}


def test_robots_disallowed_sitemap_gets_an_error_line():
    fetch = site(
        {"https://r.com/sitemap.xml": urlset(("https://r.com/a", None))},
        robots="User-agent: *\nDisallow: /sitemap\n",
    )
    snap = snapshot_domain("r.com", fetch, known=set())
    assert "https://r.com/sitemap.xml" not in fetch.calls
    assert snap.complete is False
    assert snap.errors == [
        "sitemap https://r.com/sitemap.xml: disallowed by robots.txt"
    ]
