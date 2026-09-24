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


def _crawl(owner, org, bid, cid, domain, days_ago, baseline=False, types=None):
    with owner() as s, s.begin():
        c = m.RivalCrawl(
            org_id=org.id,
            brand_id=bid,
            competitor_id=cid,
            domain=domain,
            baseline=baseline,
            complete=True,
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


def test_out_of_time_domain_is_not_stored(
    owner, make_org, make_brand, monkeypatch
):
    org = make_org()
    bid = make_brand(org)
    _rival(owner, org, bid, domains=("r.com",))
    monkeypatch.setattr(worker, "RIVAL_JOB_SECONDS", -1)  # already late
    job = _run(owner, org, bid, _fake({}))
    assert job.status == "done"
    with owner() as s:
        assert s.scalar(select(func.count()).select_from(m.RivalCrawl)) == 0


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
