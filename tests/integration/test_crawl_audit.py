"""The crawl audit: what is due, and what the worker stores."""

import bsi_workers.worker as worker
import pytest
from bsi_core import models as m
from bsi_core.crawl import Response
from bsi_core.db import system_session, tenant_session
from bsi_core.scheduling import enqueue_job
from sqlalchemy import func, select, text, update

from tests.integration.test_worker import FakeAdapter, _job, _load_job, _spender


@pytest.fixture(autouse=True)
def _no_pause(monkeypatch):
    # Production pauses PAUSE_SECONDS between fetches; that would make
    # every test in this file sleep for real. Proven separately below.
    monkeypatch.setattr(worker, "PAUSE_SECONDS", 0)


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


def _fake_fetch(pages=None):
    calls = []

    def fetch(url, ua):
        calls.append(url)
        return (pages or {}).get(url, Response(200, "<title>x</title>"))

    fetch.calls = calls
    return fetch


def test_audit_job_stores_one_row_per_domain(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _domain(owner, org, bid, "nike.com")
    _domain(owner, org, bid, "nike.in")
    job_id = _job(owner, org, bid, "audit_crawl", "queued")
    _, generator, embedder = _spender()
    fetch = _fake_fetch()
    assert worker.process_job(FakeAdapter(), generator, embedder, fetch=fetch)
    job = _load_job(owner, job_id)
    assert (job.status, job.error, job.cost_micros) == ("done", None, 0)
    with owner() as s:
        rows = s.scalars(select(m.SiteAudit).order_by(m.SiteAudit.domain)).all()
    assert [(r.domain, r.job_id) for r in rows] == [
        ("nike.com", job_id),
        ("nike.in", job_id),
    ]
    assert rows[0].fetches == 12 and len(rows[0].checks) >= 20
    assert {c["code"] for c in rows[0].checks} >= {"home_unreachable"}
    # Everything the page needs is in the JSON, no dataclass leaked.
    assert set(rows[0].checks[0]) == {
        "code",
        "ok",
        "severity",
        "observed",
        "expected",
        "url",
    }
    assert fetch.calls[0] == "https://nike.com/"
    assert due() == []  # audited: not due again for a week


def test_a_brand_without_domains_finishes_with_no_rows(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    job_id = _job(owner, org, bid, "audit_crawl", "queued")
    _, generator, embedder = _spender()
    fetch = _fake_fetch()
    assert worker.process_job(FakeAdapter(), generator, embedder, fetch=fetch)
    assert _load_job(owner, job_id).status == "done"
    assert fetch.calls == []
    with owner() as s:
        assert s.scalars(select(m.SiteAudit)).all() == []


def test_a_raising_fetch_fails_the_check_not_the_job(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _domain(owner, org, bid)
    job_id = _job(owner, org, bid, "audit_crawl", "queued")
    _, generator, embedder = _spender()

    def fetch(url, ua):
        return Response(0, "", "ConnectError('down')")

    assert worker.process_job(FakeAdapter(), generator, embedder, fetch=fetch)
    assert _load_job(owner, job_id).status == "done"
    with owner() as s:
        row = s.scalars(select(m.SiteAudit)).one()
    home = next(c for c in row.checks if c["code"] == "home_unreachable")
    assert home["ok"] is False and "ConnectError" in home["observed"]


def test_no_transaction_is_open_while_fetching(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _domain(owner, org, bid)
    _job(owner, org, bid, "audit_crawl", "queued")
    _, generator, embedder = _spender()
    seen = []

    def fetch(url, ua):
        with owner() as s:
            seen.append(
                s.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE state = 'idle in transaction' "
                        "AND pid <> pg_backend_pid()"
                    )
                )
            )
        return Response(200, "")

    worker.process_job(FakeAdapter(), generator, embedder, fetch=fetch)
    assert seen and set(seen) == {0}


def test_queue_due_crawl_audits_is_idempotent_within_the_hour(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _domain(owner, org, bid)
    assert worker.queue_due_crawl_audits() == 1
    assert worker.queue_due_crawl_audits() == 1  # counted, but no new row
    with owner() as s:
        jobs = s.scalars(select(m.Job).where(m.Job.kind == "audit_crawl")).all()
    assert len(jobs) == 1 and jobs[0].status == "queued"


def test_enqueue_job_requeues_only_a_failed_job(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    with tenant_session(org.id) as s:
        first = enqueue_job(s, org.id, bid, "audit_crawl", {})
        first_id, slot = first.id, first.scheduled_slot
    with owner() as s, s.begin():
        s.execute(
            update(m.Job).where(m.Job.id == first_id).values(status="done")
        )
    with tenant_session(org.id) as s:
        again = enqueue_job(s, org.id, bid, "audit_crawl", {}, slot=slot)
        assert (again.id, again.status) == (first_id, "done")
    with owner() as s, s.begin():
        s.execute(
            update(m.Job)
            .where(m.Job.id == first_id)
            .values(status="failed", error="x")
        )
    with tenant_session(org.id) as s:
        again = enqueue_job(s, org.id, bid, "audit_crawl", {"k": 1}, slot=slot)
        assert (again.status, again.error, again.params) == (
            "queued",
            None,
            {"k": 1},
        )


def test_production_pauses_between_fetches(
    monkeypatch, owner, make_org, make_brand
):
    """PAUSE_SECONDS is read at call time, so production really pauses;
    every other test in this file sets it to 0 via the autouse fixture."""
    monkeypatch.setattr(worker, "PAUSE_SECONDS", 0.25)
    sleeps = []
    monkeypatch.setattr(
        "bsi_core.crawl.time.sleep", lambda secs: sleeps.append(secs)
    )
    org = make_org()
    bid = make_brand(org)
    _domain(owner, org, bid)
    _job(owner, org, bid, "audit_crawl", "queued")
    _, generator, embedder = _spender()
    fetch = _fake_fetch()
    worker.process_job(FakeAdapter(), generator, embedder, fetch=fetch)
    assert sleeps == [0.25] * 11
