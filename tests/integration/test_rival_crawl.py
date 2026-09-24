"""Competitor site crawl (PRD F07): what is due, what the job stores,
and what counts as a change."""

from bsi_core import models as m
from bsi_core.db import system_session
from sqlalchemy import func, text, update


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


def test_never_crawled_brands_come_first(owner, make_org, make_brand):
    org = make_org()
    old = make_brand(org, "Old")
    new = make_brand(org, "New")
    c_old = _rival(owner, org, old)
    _rival(owner, org, new)
    _crawl(owner, org, old, c_old, "adidas.co.in", days_ago=9)
    assert due() == [new, old]


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
