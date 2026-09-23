"""http_fetch fetches only public addresses. DNS and HTTP are faked."""

import gzip
import ipaddress
import itertools
import threading
import time
import tracemalloc
import zlib
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from bsi_core.crawl import BODY_CAP_BYTES, http_fetch

PUBLIC = "93.184.216.34"


def dns(table):
    """A resolver over host -> [ip]; unknown hosts do not resolve."""

    def resolve(host, port):
        if host not in table:
            raise OSError(f"no such host {host}")
        return table[host]

    return resolve


def server(handler):
    """A MockTransport that records every request it sees."""
    seen = []

    def handle(request):
        seen.append(request)
        r = handler(request)
        if r.is_stream_consumed:
            # httpx pre-reads a bytes body; a socket never does, and
            # http_fetch reads the raw stream.
            r = httpx.Response(
                r.status_code,
                headers=r.headers,
                stream=httpx.ByteStream(r.content),
            )
        return r

    transport = httpx.MockTransport(handle)
    transport.seen = seen
    return transport


def ok(request):
    return httpx.Response(200, text="hello")


def fetch(url, table=None, handler=ok):
    t = server(handler)
    r = http_fetch(url, "UA", resolve=dns(table or {}), transport=t)
    return r, t.seen


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        "224.0.0.1",  # multicast: is_global says True
        "ff02::1",
        "64:ff9b::a9fe:a9fe",  # NAT64 of 169.254.169.254
        "::7f00:1",  # IPv4-compatible 127.0.0.1
        "2002:7f00:1::",  # 6to4 of 127.0.0.1
        "2001:0:4136:e378:8000:63bf:80ff:fffe",  # Teredo
    ],
)
def test_internal_addresses_are_refused(ip):
    # As an IP literal in the URL, and as what a public name resolves to.
    literal = f"[{ip}]" if ":" in ip else ip
    for url, table in (
        (f"https://{literal}/", {}),
        ("https://nike.com/", {"nike.com": [ip]}),
    ):
        r, seen = fetch(url, table)
        assert (r.status, r.body) == (0, "")
        # Python 3.13 changed how IPv4-mapped addresses print, so expect
        # whatever this interpreter prints rather than the literal.
        shown = ipaddress.ip_address(ip)
        assert r.error == f"refused: {shown} is not a public address", url
        assert seen == []


def test_a_nat64_address_of_a_public_ipv4_is_allowed():
    r, seen = fetch("https://nike.com/", {"nike.com": ["64:ff9b::808:808"]})
    assert r.status == 200
    assert str(seen[0].url) == "https://[64:ff9b::808:808]/"


def test_one_private_address_among_public_ones_is_refused():
    r, seen = fetch("https://nike.com/", {"nike.com": [PUBLIC, "10.0.0.1"]})
    assert r.error == "refused: 10.0.0.1 is not a public address"
    assert seen == []


def test_a_name_that_does_not_resolve_is_refused():
    r, seen = fetch("https://nowhere.example/", {})
    assert r.status == 0 and r.error.startswith("refused: ")
    r, seen = fetch("https://nike.com/", {"nike.com": []})
    assert r.error == "refused: nike.com does not resolve"
    assert seen == []


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("ftp://nike.com/", "refused: scheme ftp"),
        ("file:///etc/passwd", "refused: scheme file"),
        ("https://nike.com:22/", "refused: port 22"),
        ("http://nike.com:443/", "refused: port 443"),
    ],
)
def test_other_schemes_and_ports_are_refused(url, reason):
    r, seen = fetch(url, {"nike.com": [PUBLIC]})
    assert r.error == reason
    assert seen == []


def test_the_default_port_may_be_explicit():
    for url in ("https://nike.com:443/", "http://nike.com:80/"):
        r, _ = fetch(url, {"nike.com": [PUBLIC]})
        assert (r.status, r.body) == (200, "hello"), url


def test_the_connection_is_pinned_to_the_checked_address():
    r, seen = fetch("https://nike.com/a?b=1", {"nike.com": [PUBLIC, "8.8.8.8"]})
    assert r.status == 200
    (req,) = seen
    assert str(req.url) == f"https://{PUBLIC}/a?b=1"
    assert req.headers["host"] == "nike.com"
    assert req.headers["user-agent"] == "UA"
    assert req.extensions["sni_hostname"] == "nike.com"


def test_an_ipv6_address_is_bracketed_and_plain_http_sends_no_sni():
    r, seen = fetch("http://nike.com/", {"nike.com": ["2606:4700::1"]})
    assert r.status == 200
    (req,) = seen
    assert str(req.url) == "http://[2606:4700::1]/"
    assert req.headers["host"] == "nike.com"
    assert "sni_hostname" not in req.extensions


def redirects(chain):
    """Each host in `chain` redirects to the next URL; the last answers."""

    def handle(request):
        hop = int(request.url.path.strip("/") or 0)
        if hop < len(chain):
            return httpx.Response(302, headers={"Location": chain[hop]})
        return httpx.Response(200, text=f"final {hop}")

    return handle


def test_a_redirect_inward_is_refused():
    table = {"nike.com": [PUBLIC], "admin.nike.com": ["10.0.0.5"]}
    r, seen = fetch(
        "https://nike.com/", table, redirects(["https://admin.nike.com/1"])
    )
    assert r.error == "refused: 10.0.0.5 is not a public address"
    assert len(seen) == 1


def test_a_redirect_to_another_port_is_refused():
    r, seen = fetch(
        "https://nike.com/",
        {"nike.com": [PUBLIC]},
        redirects(["http://nike.com:22/1"]),
    )
    assert r.error == "refused: port 22"
    assert len(seen) == 1


def test_a_public_redirect_chain_is_followed_and_pinned_each_hop():
    table = {"nike.com": [PUBLIC], "www.nike.com": ["8.8.4.4"]}
    # The second Location is relative: it resolves against www.nike.com.
    r, seen = fetch(
        "https://nike.com/", table, redirects(["https://www.nike.com/1", "/2"])
    )
    assert (r.status, r.body) == (200, "final 2")
    assert [str(q.url) for q in seen] == [
        f"https://{PUBLIC}/",
        "https://8.8.4.4/1",
        "https://8.8.4.4/2",
    ]
    assert [q.headers["host"] for q in seen] == ["nike.com"] + [
        "www.nike.com"
    ] * 2


def test_five_redirects_are_followed_and_a_sixth_is_refused():
    table = {"nike.com": [PUBLIC]}
    five = [f"/{i}" for i in range(1, 6)]
    r, seen = fetch("https://nike.com/", table, redirects(five))
    assert (r.status, r.body, len(seen)) == (200, "final 5", 6)
    r, seen = fetch("https://nike.com/", table, redirects([*five, "/6"]))
    assert (r.status, r.error, len(seen)) == (
        0,
        "refused: too many redirects",
        6,
    )


def test_the_body_is_cut_at_the_byte_cap():
    big = b"a" * (BODY_CAP_BYTES * 3)
    r, _ = fetch(
        "https://nike.com/",
        {"nike.com": [PUBLIC]},
        lambda q: httpx.Response(200, content=big),
    )
    assert (r.status, len(r.body)) == (200, BODY_CAP_BYTES)


def gz_zeros(size):
    """gzip of `size` zero bytes, built without holding them all."""
    z = zlib.compressobj(9, zlib.DEFLATED, 31)
    block = b"\0" * (1 << 20)
    out = [z.compress(block) for _ in range(size >> 20)]
    return b"".join([*out, z.flush()])


def encoded(body, encoding):
    return lambda q: httpx.Response(
        200,
        headers={"Content-Encoding": encoding},
        stream=httpx.ByteStream(body),
    )


def test_a_gzip_bomb_is_decoded_only_up_to_the_cap_in_bounded_memory():
    bomb = gz_zeros(256 << 20)
    assert len(bomb) < 300 * 1024  # small on the wire, 256 MiB inflated
    tracemalloc.start()
    try:
        r, seen = fetch(
            "https://nike.com/", {"nike.com": [PUBLIC]}, encoded(bomb, "gzip")
        )
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert (r.status, len(r.body)) == (200, BODY_CAP_BYTES)
    assert peak < 5 * 1024 * 1024, peak
    assert seen[0].headers["accept-encoding"] == "gzip, deflate"


def test_stacked_encodings_are_refused():
    two = gzip.compress(gz_zeros(8 << 20))
    for enc in ("gzip, gzip", "gzip,deflate"):
        r, _ = fetch(
            "https://nike.com/", {"nike.com": [PUBLIC]}, encoded(two, enc)
        )
        assert (r.status, r.body) == (0, ""), enc
        assert r.error == "refused: stacked content-encoding"


def test_an_unknown_encoding_is_refused():
    r, _ = fetch(
        "https://nike.com/", {"nike.com": [PUBLIC]}, encoded(b"x", "br")
    )
    assert r.error == "refused: content-encoding br"


@pytest.mark.parametrize(
    ("encoding", "compress"),
    [
        ("gzip", gzip.compress),
        ("x-gzip", gzip.compress),
        ("deflate", zlib.compress),
        ("identity", lambda b: b),
    ],
)
def test_each_supported_encoding_decodes(encoding, compress):
    body = compress(b"<html>hello</html>")
    r, _ = fetch(
        "https://nike.com/", {"nike.com": [PUBLIC]}, encoded(body, encoding)
    )
    assert (r.status, r.body) == (200, "<html>hello</html>")


def test_the_charset_decides_the_decoding():
    r, _ = fetch(
        "https://nike.com/",
        {"nike.com": [PUBLIC]},
        lambda q: httpx.Response(
            200,
            content="café".encode("latin-1"),
            headers={"Content-Type": "text/html; charset=latin-1"},
        ),
    )
    assert r.body == "café"
    r, _ = fetch(
        "https://nike.com/",
        {"nike.com": [PUBLIC]},
        lambda q: httpx.Response(200, content=b"caf\xe9"),
    )
    assert r.body == "caf\ufffd"  # utf-8 by default, bad bytes replaced


def test_the_whole_fetch_has_a_deadline(monkeypatch):
    # Each clock read is 1 s later: a slow stream that never ends.
    clock = itertools.count(0.0, 1.0)
    monkeypatch.setattr("bsi_core.crawl.time.monotonic", lambda: next(clock))

    def drip():
        while True:
            yield b"x"

    r, _ = fetch(
        "https://nike.com/",
        {"nike.com": [PUBLIC]},
        lambda q: httpx.Response(200, content=drip()),
    )
    assert (r.status, r.body) == (0, "")
    assert r.error == "timeout: over the 30 s deadline"


def test_a_transport_error_is_a_response_not_an_exception():
    def boom(request):
        raise httpx.ConnectError("boom")

    r, _ = fetch("https://nike.com/", {"nike.com": [PUBLIC]}, boom)
    assert r.status == 0 and "ConnectError" in r.error


def test_each_request_timeout_is_capped_by_the_time_left(monkeypatch):
    # 25 s of the 30 s deadline are gone when the request is sent (the
    # second reading is the one taken before the DNS lookup).
    clock = iter([0.0, 24.0, 25.0] + [26.0] * 10)
    monkeypatch.setattr("bsi_core.crawl.time.monotonic", lambda: next(clock))
    r, seen = fetch("https://nike.com/", {"nike.com": [PUBLIC]})
    assert r.status == 200
    assert set(seen[0].extensions["timeout"].values()) == {5.0}


@pytest.fixture
def hang():
    """A resolver that blocks until the test ends, then answers."""
    release = threading.Event()
    calls = []

    def resolve(host, port):
        calls.append(host)
        release.wait(5)
        return [PUBLIC]

    resolve.release = release
    yield resolve
    release.set()  # let the pool's threads finish before pytest exits


def test_a_slow_lookup_is_refused_at_the_dns_timeout(monkeypatch, hang):
    # getaddrinfo takes no timeout, so the lookup runs on a worker thread
    # and the fetch gives up on it; nothing is ever requested.
    monkeypatch.setattr("bsi_core.crawl.DNS_TIMEOUT_SECONDS", 0.2)
    t = server(ok)
    start = time.monotonic()
    r = http_fetch("https://nike.com/", "UA", resolve=hang, transport=t)
    assert time.monotonic() - start < 1
    assert (r.status, r.error) == (
        0,
        "refused: nike.com did not resolve in time",
    )
    assert t.seen == []


def test_the_lookup_wait_is_capped_by_the_time_left(monkeypatch, hang):
    # A generous DNS timeout still cannot carry a fetch past its deadline.
    monkeypatch.setattr("bsi_core.crawl.DNS_TIMEOUT_SECONDS", 10)
    monkeypatch.setattr("bsi_core.crawl.DEADLINE_SECONDS", 0.2)
    t = server(ok)
    start = time.monotonic()
    r = http_fetch("https://nike.com/", "UA", resolve=hang, transport=t)
    assert time.monotonic() - start < 1
    assert r.error == "refused: nike.com did not resolve in time"
    assert t.seen == []


def test_an_abandoned_lookup_still_queued_never_runs(monkeypatch, hang):
    # Fill every worker with a hung lookup, then time one out in the
    # queue: it is cancelled, so it never runs once workers free up.
    monkeypatch.setattr("bsi_core.crawl.DNS_TIMEOUT_SECONDS", 0.05)
    pool = ThreadPoolExecutor(max_workers=4)
    monkeypatch.setattr("bsi_core.crawl._LOOKUPS", pool)
    for i in range(4):
        http_fetch(f"https://h{i}.com/", "UA", resolve=hang)
    ran = []

    def late(host, port):
        ran.append(host)
        return [PUBLIC]

    r = http_fetch("https://late.com/", "UA", resolve=late)
    assert r.error == "refused: late.com did not resolve in time"
    hang.release.set()
    pool.shutdown(wait=True)  # every lookup that will ever run has run
    assert ran == []
