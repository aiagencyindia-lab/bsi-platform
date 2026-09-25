"""Competitor site crawl (PRD F07): what is due, what the job stores,
and what counts as a change."""

from datetime import timedelta

import bsi_workers.worker as worker
import pytest
from bsi_core import models as m
from bsi_core.crawl import Response
from bsi_core.db import system_session, tenant_session
from bsi_core.rivals import NEW_PAGES_CAP, feed_evidence, site_changes
from sqlalchemy import func, select, text, update

from tests.integration.test_worker import FakeAdapter, _job, _load_job, _spender
from tests.unit.test_rivals import HOME, urlset


def _rival(
    owner, org, bid, name="Adidas", domains=("adidas.co.in",), status="active"
):
    with owner() as s, s.begin():
        c = m.Competitor(
            org_id=org.id,
            brand_id=bid,
            name=name,
            domains=list(domains),
            status=status,
        )
        s.add(c)
        s.flush()
        return c.id


def _crawl(
    owner,
    org,
    bid,
    cid,
    domain,
    days_ago,
    baseline=False,
    types=None,
    complete=True,
):
    with owner() as s, s.begin():
        c = m.RivalCrawl(
            org_id=org.id,
            brand_id=bid,
            competitor_id=cid,
            domain=domain,
            baseline=baseline,
            complete=complete,
            types=types or {},
        )
        s.add(c)
        s.flush()
        s.execute(
            update(m.RivalCrawl)
            .where(m.RivalCrawl.id == c.id)
            .values(
                created_at=func.now() - func.make_interval(0, 0, 0, days_ago)
            )
        )
        return c.id


def due():
    with system_session() as s:
        return [
            r[0]
            for r in s.execute(text("SELECT brand_id FROM due_rival_crawls()"))
        ]


def test_a_brand_with_an_active_rival_domain_is_due(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Nike")
    bare = make_brand(org, "NoRivals")
    _rival(owner, org, bare, domains=())  # no domains: never due
    _rival(owner, org, bare, "Sugg", status="suggested")  # suggested: never
    _rival(owner, org, bid)
    assert due() == [bid]


def test_due_again_after_seven_days(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid)
    _crawl(owner, org, bid, cid, "adidas.co.in", days_ago=6)
    assert due() == []
    _crawl(owner, org, bid, cid, "adidas.co.in", days_ago=8)
    assert due() == []  # the 6-day-old crawl is the latest
    with owner() as s, s.begin():
        s.execute(
            text(
                "DELETE FROM rival_crawl WHERE created_at > "
                "now() - interval '7 days'"
            )
        )
    assert due() == [bid]


def test_each_declared_domain_counts(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid, domains=("a.com", "b.com"))
    _crawl(owner, org, bid, cid, "a.com", days_ago=1)
    assert due() == [bid]  # b.com never crawled


def test_archived_brands_are_never_due(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _rival(owner, org, bid)
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand).where(m.Brand.id == bid).values(status="archived")
        )
    assert due() == []


def test_never_crawled_first_then_oldest(owner, make_org, make_brand):
    org = make_org()
    # Roles go against id order (the tiebreak), so an id-only ORDER BY
    # fails every run, not by chance.
    eight, ten, never = sorted(make_brand(org, n) for n in ("A", "B", "C"))
    for bid, days in ((eight, 8), (ten, 10)):
        cid = _rival(owner, org, bid)
        _crawl(owner, org, bid, cid, "adidas.co.in", days_ago=days)
    _rival(owner, org, never)
    assert due() == [never, ten, eight]


def test_deleting_a_competitor_deletes_its_rows(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid)
    _crawl(owner, org, bid, cid, "adidas.co.in", days_ago=1)
    with owner() as s, s.begin():
        s.add(
            m.RivalPage(
                org_id=org.id,
                brand_id=bid,
                competitor_id=cid,
                domain="adidas.co.in",
                url="https://adidas.co.in/x",
                baseline=True,
            )
        )
    with owner() as s, s.begin():
        s.execute(text("DELETE FROM competitor WHERE id = :c"), {"c": cid})
    with owner() as s:
        assert s.scalar(text("SELECT count(*) FROM rival_crawl")) == 0
        assert s.scalar(text("SELECT count(*) FROM rival_page")) == 0


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch):
    monkeypatch.setattr(worker, "PAUSE_SECONDS", 0)


def _fake(sites):
    """sites: host -> {url: body}; robots allow-all everywhere."""
    calls = []

    def fetch(url, ua):
        calls.append(url)
        host = url.split("/")[2]
        if url.endswith("/robots.txt"):
            return Response(200, "User-agent: *\nAllow: /\n")
        body = sites.get(host, {}).get(url)
        return Response(200, body) if body is not None else Response(404, "")

    fetch.calls = calls
    return fetch


def _run(owner, org, bid, fetch):
    jid = _job(owner, org, bid, "crawl_rivals", "queued")
    _, gen, emb = _spender()
    worker.process_job(FakeAdapter(), gen, emb, fetch=fetch)
    return _load_job(owner, jid)


def _pages(owner, cid):
    with owner() as s:
        return {
            p.url: p
            for p in s.scalars(
                select(m.RivalPage).where(m.RivalPage.competitor_id == cid)
            )
        }


def test_first_crawl_is_a_baseline(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid, domains=("r.com",))
    fetch = _fake(
        {
            "r.com": {
                "https://r.com/sitemap.xml": urlset(
                    ("https://r.com/a", "2026-09-01")
                ),
                "https://r.com/": HOME,
            }
        }
    )
    job = _run(owner, org, bid, fetch)
    assert (job.status, job.error, job.cost_micros) == ("done", None, 0)
    with owner() as s:
        [c] = s.scalars(select(m.RivalCrawl)).all()
    assert (c.domain, c.baseline, c.complete, c.urls_seen, c.new_urls) == (
        "r.com",
        True,
        True,
        1,
        1,
    )
    assert c.types == {"Organization": "https://r.com/"}
    assert c.fetches == len(fetch.calls)
    pages = _pages(owner, cid)
    assert (
        set(pages) == {"https://r.com/a"} and pages["https://r.com/a"].baseline
    )


def test_second_crawl_records_new_pages_not_baseline(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid, domains=("r.com",))
    one = {
        "https://r.com/sitemap.xml": urlset(("https://r.com/a", None)),
        "https://r.com/": HOME,
    }
    _run(owner, org, bid, _fake({"r.com": one}))
    with owner() as s, s.begin():  # make it due again
        s.execute(
            update(m.RivalCrawl).values(
                created_at=func.now() - func.make_interval(0, 0, 0, 8)
            )
        )
    two = {
        **one,
        "https://r.com/sitemap.xml": urlset(
            ("https://r.com/a", None), ("https://r.com/b", "2026-09-20")
        ),
    }
    two["https://r.com/b"] = (
        '<script type="application/ld+json">{"@type":"FAQPage"}</script>'
    )
    fetch = _fake({"r.com": two})
    _run(owner, org, bid, fetch)
    assert "https://r.com/a" not in fetch.calls  # known: not re-sampled
    pages = _pages(owner, cid)
    assert pages["https://r.com/b"].baseline is False
    assert pages["https://r.com/b"].types == ["FAQPage"]
    assert (
        pages["https://r.com/a"].last_seen_at
        > pages["https://r.com/a"].first_seen_at
    )
    with owner() as s:
        latest = s.scalars(
            select(m.RivalCrawl).order_by(m.RivalCrawl.created_at.desc())
        ).first()
    assert (latest.baseline, latest.new_urls) == (False, 1)


def test_only_due_domains_of_active_rivals_are_crawled(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    fresh = _rival(owner, org, bid, "Fresh", domains=("f.com",))
    _crawl(owner, org, bid, fresh, "f.com", days_ago=1)
    _rival(owner, org, bid, "Sugg", domains=("s.com",), status="suggested")
    _rival(owner, org, bid, "Due", domains=("d.com",))
    fetch = _fake({})
    _run(owner, org, bid, fetch)
    hosts = {u.split("/")[2] for u in fetch.calls}
    assert hosts == {"d.com"}


def test_a_crashing_domain_stores_nothing_and_stays_due(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _rival(owner, org, bid, domains=("bad.com", "good.com"))

    def fetch(url, ua):
        if "bad.com" in url:
            raise RuntimeError("boom")
        return _fake({"good.com": {"https://good.com/": HOME}})(url, ua)

    job = _run(owner, org, bid, fetch)
    assert job.status == "done"
    with owner() as s:
        assert [c.domain for c in s.scalars(select(m.RivalCrawl))] == [
            "good.com"
        ]
    assert due() == [bid]


def _direct(owner, org, bid, fetch, clock):
    jid = _job(owner, org, bid, "crawl_rivals", "running")
    return worker.run_rival_crawl(org.id, bid, jid, fetch, clock=clock)


def test_first_domain_out_of_time_is_stored_and_waits(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid, domains=("r.com",))
    ticks = iter([0.0] * 4)  # job start, domain check, two deadlines
    stored = _direct(owner, org, bid, _fake({}), lambda: next(ticks, 1e9))
    assert stored == 1
    with owner() as s:
        [c] = s.scalars(select(m.RivalCrawl)).all()
    assert (c.domain, c.complete, c.urls_seen, c.baseline) == (
        "r.com",
        False,
        0,
        True,
    )
    assert c.errors == [
        "out of time: the crawl did not finish within "
        f"{worker.RIVAL_JOB_SECONDS} s"
    ]
    assert _pages(owner, cid) == {}
    assert due() == []  # waits 7 days like any other crawl


def test_every_out_of_time_domain_is_stored_incomplete(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _rival(owner, org, bid, domains=("a.com", "b.com"))
    now = [0.0]
    inner = _fake(
        {
            "a.com": {
                "https://a.com/sitemap.xml": urlset(("https://a.com/x", None)),
                "https://a.com/": HOME,
            }
        }
    )

    def fetch(url, ua):
        if "b.com" in url:
            now[0] = 1e9  # b.com's first fetch uses up the budget
        return inner(url, ua)

    stored = _direct(owner, org, bid, fetch, lambda: now[0])
    assert stored == 2
    with owner() as s:
        rows = {c.domain: c for c in s.scalars(select(m.RivalCrawl))}
    assert (rows["a.com"].complete, rows["a.com"].urls_seen) == (True, 1)
    assert rows["b.com"].complete is False and rows["b.com"].urls_seen == 0
    per = max(worker.RIVAL_DOMAIN_FLOOR_SECONDS, worker.RIVAL_JOB_SECONDS // 2)
    assert rows["b.com"].errors == [
        f"out of time: the crawl did not finish within {per} s"
    ]
    assert due() == []  # both stored; both wait 7 days


def test_one_domain_failing_its_write_does_not_lose_the_others(
    owner, make_org, make_brand, monkeypatch
):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid, domains=("bad.com", "good.com"))
    real = worker.snapshot_domain

    def snap(host, fetch, known, **kw):
        out = real(host, fetch, known, **kw)
        if host == "bad.com":  # NUL cannot be stored in text: insert fails
            out.urls["https://bad.com/a\x00b"] = None
        return out

    monkeypatch.setattr(worker, "snapshot_domain", snap)
    fetch = _fake(
        {
            "good.com": {
                "https://good.com/sitemap.xml": urlset(
                    ("https://good.com/a", None)
                ),
                "https://good.com/": HOME,
            }
        }
    )
    job = _run(owner, org, bid, fetch)
    assert job.status == "done"
    with owner() as s:
        assert [c.domain for c in s.scalars(select(m.RivalCrawl))] == [
            "good.com"
        ]
    assert set(_pages(owner, cid)) == {"https://good.com/a"}
    assert due() == [bid]  # bad.com stays due


def test_a_failed_first_crawl_does_not_end_the_baseline(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid, domains=("r.com",))
    blocked = {"https://r.com/sitemap.xml": Response(403, "")}

    def forbidden(url, ua):
        if url in blocked:
            return blocked[url]
        return _fake({"r.com": {"https://r.com/": HOME}})(url, ua)

    _run(owner, org, bid, forbidden)
    with owner() as s:
        [c] = s.scalars(select(m.RivalCrawl)).all()
    assert (c.urls_seen, c.baseline) == (0, True)
    with owner() as s, s.begin():  # make it due again
        s.execute(
            update(m.RivalCrawl).values(
                created_at=func.now() - func.make_interval(0, 0, 0, 8)
            )
        )
    listed = {
        "https://r.com/sitemap.xml": urlset(
            ("https://r.com/a", None), ("https://r.com/b", None)
        ),
        "https://r.com/": HOME,
        "https://r.com/a": (
            '<script type="application/ld+json">{"@type":"FAQPage"}</script>'
        ),
    }
    _run(owner, org, bid, _fake({"r.com": listed}))
    pages = _pages(owner, cid)
    assert set(pages) == {"https://r.com/a", "https://r.com/b"}
    assert all(p.baseline for p in pages.values())
    with owner() as s:
        latest = s.scalars(
            select(m.RivalCrawl).order_by(m.RivalCrawl.created_at.desc())
        ).first()
    assert (latest.baseline, latest.urls_seen) == (True, 2)
    [ad] = _changes(org, bid)["competitors"]
    assert (ad["new_pages_total"], ad["new_pages"], ad["new_types"]) == (
        0,
        [],
        [],
    )


def test_writes_are_chunked(owner, make_org, make_brand, monkeypatch):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid, domains=("r.com",))
    monkeypatch.setattr(worker, "RIVAL_UPSERT_CHUNK", 3)
    locs = [(f"https://r.com/p{i}", None) for i in range(10)]
    _run(
        owner,
        org,
        bid,
        _fake(
            {
                "r.com": {
                    "https://r.com/sitemap.xml": urlset(*locs),
                    "https://r.com/": HOME,
                }
            }
        ),
    )
    assert len(_pages(owner, cid)) == 10


def test_no_transaction_is_open_while_fetching(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _rival(owner, org, bid, domains=("r.com",))
    seen = []

    def fetch(url, ua):
        with owner() as s:
            seen.append(
                s.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE state = "
                        "'idle in transaction' AND pid <> pg_backend_pid()"
                    )
                )
            )
        return Response(200, "")

    _run(owner, org, bid, fetch)
    assert seen and set(seen) == {0}


def test_queue_due_rival_crawls_is_idempotent_within_the_hour(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _rival(owner, org, bid)
    assert worker.queue_due_rival_crawls() == 1
    assert worker.queue_due_rival_crawls() == 1
    with owner() as s:
        jobs = s.scalars(
            select(m.Job).where(m.Job.kind == "crawl_rivals")
        ).all()
    assert len(jobs) == 1 and jobs[0].status == "queued"


def _page(
    owner,
    org,
    bid,
    cid,
    url,
    days_ago,
    baseline=False,
    types=None,
    domain="r.com",
):
    with owner() as s, s.begin():
        p = m.RivalPage(
            org_id=org.id,
            brand_id=bid,
            competitor_id=cid,
            domain=domain,
            url=url,
            baseline=baseline,
            types=types,
        )
        s.add(p)
        s.flush()
        s.execute(
            update(m.RivalPage)
            .where(m.RivalPage.id == p.id)
            .values(
                first_seen_at=func.now() - func.make_interval(0, 0, 0, days_ago)
            )
        )


def _changes(org, bid, **kw):
    with tenant_session(org.id) as s:
        return site_changes(s, bid, **kw)


def test_site_changes_lists_new_pages_types_and_crawl_status(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    a = _rival(owner, org, bid, "Adidas", domains=("r.com",))
    b = _rival(owner, org, bid, "Bata", domains=("b.com",))
    _crawl(
        owner,
        org,
        bid,
        a,
        "r.com",
        days_ago=20,
        baseline=True,
        types={"Organization": "https://r.com/"},
    )
    _crawl(
        owner,
        org,
        bid,
        a,
        "r.com",
        days_ago=2,
        types={
            "Organization": "https://r.com/",
            "FAQPage": "https://r.com/new",
        },
    )
    _page(owner, org, bid, a, "https://r.com/base", 20, baseline=True)
    _page(owner, org, bid, a, "https://r.com/old", 30)  # before the window
    _page(owner, org, bid, a, "https://r.com/new", 2, types=["FAQPage"])
    _page(owner, org, bid, a, "https://r.com/new0", 1)
    out = _changes(org, bid)
    assert [c["name"] for c in out["competitors"]] == ["Adidas", "Bata"]
    ad = out["competitors"][0]
    assert ad["new_pages_total"] == 2
    assert [p["url"] for p in ad["new_pages"]] == [
        "https://r.com/new0",
        "https://r.com/new",
    ]
    assert ad["new_pages"][1]["types"] == ["FAQPage"]
    assert ad["new_types"] == [{"type": "FAQPage", "url": "https://r.com/new"}]
    assert [(c["domain"], c["complete"]) for c in ad["crawls"]] == [
        ("r.com", True)
    ]
    bata = out["competitors"][1]
    assert (bata["new_pages_total"], bata["crawls"]) == (0, [])
    assert b == bata["competitor_id"]


def test_new_pages_are_capped_and_types_first_seen_on_baseline_are_not_new(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    a = _rival(owner, org, bid, domains=("r.com", "s.com"))
    for i in range(NEW_PAGES_CAP + 3):
        _page(owner, org, bid, a, f"https://r.com/p{i:02d}", 3)
    # s.com's baseline crawl lands in the window with a type r.com never
    # had: still not new (baseline).
    _crawl(
        owner,
        org,
        bid,
        a,
        "s.com",
        days_ago=1,
        baseline=True,
        types={"Product": "https://s.com/"},
    )
    ad = _changes(org, bid)["competitors"][0]
    assert ad["new_pages_total"] == NEW_PAGES_CAP + 3
    assert len(ad["new_pages"]) == NEW_PAGES_CAP
    assert ad["new_types"] == []


def test_feed_evidence_is_windowed_per_competitor_in_two_statements(
    owner, make_org, make_brand
):
    from sqlalchemy import event

    org = make_org()
    bid = make_brand(org)
    a = _rival(owner, org, bid, "A", domains=("r.com",))
    b = _rival(owner, org, bid, "B", domains=("b.com",))
    _page(owner, org, bid, a, "https://r.com/in", 2)
    _page(owner, org, bid, a, "https://r.com/out", 20)
    _page(owner, org, bid, b, "https://b.com/in", 2, domain="b.com")
    _crawl(owner, org, bid, a, "r.com", days_ago=20, baseline=True)
    _crawl(
        owner,
        org,
        bid,
        a,
        "r.com",
        days_ago=2,
        types={"HowTo": "https://r.com/in"},
    )
    seen = []
    with tenant_session(org.id) as s:
        end = s.scalar(text("SELECT now()"))
        bind = s.get_bind()
        listener = lambda *args: seen.append(args[2])  # noqa: E731
        event.listen(bind, "before_cursor_execute", listener)
        try:
            ev = feed_evidence(s, bid, [a], end - timedelta(days=14), end)
        finally:
            event.remove(bind, "before_cursor_execute", listener)
    assert len(seen) == 2
    assert ev == {
        a: {"new_pages": ["https://r.com/in"], "new_types": ["HowTo"]}
    }


def _age_crawls(owner, days=8):
    with owner() as s, s.begin():
        s.execute(
            update(m.RivalCrawl).values(
                created_at=func.now() - func.make_interval(0, 0, 0, days)
            )
        )


def test_known_urls_keep_their_types_when_not_resampled(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid, domains=("r.com",))
    product = '<script type="application/ld+json">{"@type":"Product"}</script>'
    one = {
        "https://r.com/sitemap.xml": urlset(("https://r.com/a", None)),
        "https://r.com/": HOME,
        "https://r.com/a": product,
    }
    _run(owner, org, bid, _fake({"r.com": one}))
    first = _pages(owner, cid)["https://r.com/a"]
    assert first.types == ["Product"]
    _age_crawls(owner)
    two = {
        **one,
        "https://r.com/sitemap.xml": urlset(
            ("https://r.com/a", None), ("https://r.com/b", None)
        ),
    }
    fetch = _fake({"r.com": two})
    _run(owner, org, bid, fetch)
    assert "https://r.com/a" not in fetch.calls  # known: not re-sampled
    again = _pages(owner, cid)["https://r.com/a"]
    assert again.types == ["Product"]
    assert again.last_seen_at > first.last_seen_at


def test_run_rival_crawl_passes_the_pause(
    owner, make_org, make_brand, monkeypatch
):
    org = make_org()
    bid = make_brand(org)
    _rival(owner, org, bid, domains=("r.com",))
    monkeypatch.setattr(worker, "PAUSE_SECONDS", 0.25)
    pauses = []

    def snap(host, fetch, known, **kw):
        pauses.append(kw.get("pause"))
        return worker.Snapshot()

    monkeypatch.setattr(worker, "snapshot_domain", snap)
    _direct(owner, org, bid, _fake({}), lambda: 0.0)
    assert pauses == [0.25]


def test_site_changes_orders_by_new_pages_then_name(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    zeta = _rival(owner, org, bid, "Zeta", domains=("z.com",))
    alpha = _rival(owner, org, bid, "Alpha", domains=("a.com",))
    _rival(owner, org, bid, "Mid", domains=("m.com",))
    _rival(owner, org, bid, "Beta", domains=("b.com",))
    for i in range(2):
        _page(owner, org, bid, zeta, f"https://z.com/{i}", 1, domain="z.com")
    _page(owner, org, bid, alpha, "https://a.com/0", 1, domain="a.com")
    names = [c["name"] for c in _changes(org, bid)["competitors"]]
    assert names == ["Zeta", "Alpha", "Beta", "Mid"]


def test_site_changes_reports_the_latest_crawl_of_declared_domains(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    cid = _rival(owner, org, bid, domains=("r.com",))
    _crawl(owner, org, bid, cid, "r.com", days_ago=5)
    newer = _crawl(owner, org, bid, cid, "r.com", days_ago=1, complete=False)
    _crawl(owner, org, bid, cid, "gone.com", days_ago=1)  # not declared
    with owner() as s:
        at = s.get(m.RivalCrawl, newer).created_at
    [ad] = _changes(org, bid)["competitors"]
    assert [
        (c["domain"], c["complete"], c["crawled_at"]) for c in ad["crawls"]
    ] == [("r.com", False, at)]


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
    # 420 // 10 = 42 s, so the floor of 60 s applies.
    org = make_org()
    bid = make_brand(org)
    _rival(owner, org, bid, domains=tuple(f"d{i}.com" for i in range(10)))
    now = [0.0]
    inner = _fake({})

    def fetch(url, ua):
        now[0] = 1e9  # the first fetch uses up every budget
        return inner(url, ua)

    stored = _direct(owner, org, bid, fetch, lambda: now[0])
    assert worker.RIVAL_DOMAIN_FLOOR_SECONDS == 60
    assert stored == 1
    with owner() as s:
        [c] = s.scalars(select(m.RivalCrawl)).all()
    assert c.complete is False
    assert c.errors == ["out of time: the crawl did not finish within 60 s"]
    assert due() == [bid]  # the other nine never started


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
