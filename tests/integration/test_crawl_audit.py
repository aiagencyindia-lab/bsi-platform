"""The crawl audit: what is due, and what the worker stores."""

from bsi_core import models as m
from bsi_core.db import system_session
from sqlalchemy import func, text, update


def _domain(owner, org, bid, host="nike.com"):
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host=host))


def _audit(owner, org, bid, days_ago, host="nike.com"):
    with owner() as s, s.begin():
        a = m.SiteAudit(org_id=org.id, brand_id=bid, domain=host, checks=[])
        s.add(a)
        s.flush()
        s.execute(
            update(m.SiteAudit)
            .where(m.SiteAudit.id == a.id)
            .values(
                created_at=func.now() - func.make_interval(0, 0, 0, days_ago)
            )
        )


def due():
    with system_session() as s:
        return [
            r[0]
            for r in s.execute(text("SELECT brand_id FROM due_crawl_audits()"))
        ]


def test_a_brand_with_domains_and_no_audit_is_due(owner, make_org, make_brand):
    org = make_org()
    bare = make_brand(org, "NoDomains")
    bid = make_brand(org, "Nike")
    _domain(owner, org, bid)
    assert due() == [bid]
    assert bare not in due()


def test_due_again_after_seven_days(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _domain(owner, org, bid)
    _audit(owner, org, bid, 6)
    assert due() == []
    _audit(owner, org, bid, 8)  # an older row does not make it due...
    assert due() == []  # ...the latest row is what counts
    with owner() as s, s.begin():
        s.execute(
            update(m.SiteAudit).values(
                created_at=func.now() - func.make_interval(0, 0, 0, 8)
            )
        )
    assert due() == [bid]


def test_archived_brands_are_never_due(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _domain(owner, org, bid)
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand).where(m.Brand.id == bid).values(status="archived")
        )
    assert due() == []


def test_due_serves_every_tenant_oldest_first(owner, make_org, make_brand):
    a = make_org("A")
    b = make_org("B")
    ba = make_brand(a)
    bb = make_brand(b)
    _domain(owner, a, ba)
    _domain(owner, b, bb)
    _audit(owner, a, ba, 30)
    assert due() == [bb, ba]  # never-audited first, then the oldest
