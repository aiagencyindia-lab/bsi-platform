"""The Brand SERP audit: the table, and what the worker stores."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import bsi_workers.worker as worker
import pytest
from bsi_core import models as m
from bsi_core.config import Settings
from bsi_core.crawl import Response
from bsi_core.db import system_session
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError

from tests.integration.test_worker import FakeAdapter, _job, _load_job, _spender
from tests.unit.test_dataforseo import ITEMS, Fetch, body

BATA = {
    "type": "organic",
    "rank_absolute": 5,
    "domain": "www.bata.com",
    "url": "https://www.bata.com/in/",
    "title": "Bata",
}


def _settings(login="me", password="pw"):
    return lambda: Settings(
        dataforseo_login=login, dataforseo_password=password
    )


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(worker, "get_settings", _settings())


def _run(fetch):
    _, generator, embedder = _spender()
    return worker.process_job(
        FakeAdapter(), generator, embedder, serp_fetch=fetch
    )


def _rows(owner, bid):
    with owner() as s:
        return list(
            s.scalars(
                select(m.SerpAudit)
                .where(m.SerpAudit.brand_id == bid)
                .order_by(
                    m.SerpAudit.country, m.SerpAudit.language, m.SerpAudit.kind
                )
            )
        )


def test_the_kind_is_checked(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    with pytest.raises(IntegrityError), owner() as s, s.begin():
        s.add(
            m.SerpAudit(
                org_id=org.id,
                brand_id=bid,
                kind="other",
                query="q",
                country="IN",
                language="en",
                fetched_at=datetime.now(UTC),
            )
        )


def test_audit_serp_is_known_and_estimated():
    assert worker.JOB_ESTIMATES["audit_serp"] == worker.SERP_JOB_MICROS
    assert worker.SERP_JOB_MICROS == 40_000


def test_the_job_stores_one_classified_row_per_query(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host="walkaroo.in"))
        # A suggested competitor's domain is not used: amazon.in is "other".
        s.add(
            m.Competitor(
                org_id=org.id,
                brand_id=bid,
                name="Amazon",
                domains=["amazon.in"],
                status="suggested",
            )
        )
        s.add(
            m.Competitor(
                org_id=org.id, brand_id=bid, name="Bata", domains=["bata.com"]
            )
        )
    job_id = _job(owner, org, bid, "audit_serp", "queued")
    fetch = Fetch(Response(200, body([*ITEMS, BATA])))
    assert _run(fetch) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.error, job.cost_micros) == ("done", None, 8_000)
    rows = _rows(owner, bid)
    assert [
        (r.kind, r.query, r.country, r.language, r.device) for r in rows
    ] == [
        ("brand", "Walkaroo", "IN", "en", "desktop"),
        ("reviews", "Walkaroo reviews", "IN", "en", "desktop"),
    ]
    # People Also Ask (position 4) is not stored.
    assert [
        (x["position"], x["item_type"], x["result_type"], x["sitelinks"])
        for x in rows[0].results
    ] == [
        (1, "knowledge_graph", "knowledge_panel", False),
        (2, "organic", "official", True),
        (3, "organic", "other", False),
        (5, "organic", "competitor", False),
    ]
    assert rows[0].results[1] == {
        "position": 2,
        "item_type": "organic",
        "result_type": "official",
        "url": "https://walkaroo.in/",
        "domain": "walkaroo.in",
        "title": "Walkaroo footwear",
        "sitelinks": True,
    }
    for r in rows:
        assert (r.job_id, r.cost_micros, r.error) == (job_id, 4_000, None)
        assert r.fetched_at is not None
    assert [
        json.loads(kw["body"])[0]["keyword"] for _, _, kw in fetch.calls
    ] == [
        "Walkaroo",
        "Walkaroo reviews",
    ]


def test_a_partial_failure_keeps_both_rows_and_is_done(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    job_id = _job(owner, org, bid, "audit_serp", "queued")
    assert _run(Fetch(Response(200, body()), Response(500, "oops"))) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.error, job.cost_micros) == ("done", None, 4_000)
    brand, reviews = _rows(owner, bid)
    assert (brand.error, len(brand.results)) == (None, 3)
    assert (reviews.error, reviews.results, reviews.cost_micros) == (
        "http",
        [],
        0,
    )


def test_an_all_failed_run_keeps_its_rows_and_fails_with_the_code_and_cost(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    job_id = _job(owner, org, bid, "audit_serp", "queued")
    assert _run(Fetch(Response(200, body(task_status=40202)))) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.error, job.cost_micros) == ("failed", "rate", 8_000)
    assert [(r.error, r.cost_micros) for r in _rows(owner, bid)] == [
        ("rate", 4_000),
        ("rate", 4_000),
    ]


def test_a_failed_write_still_records_the_spend(
    monkeypatch, configured, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    job_id = _job(owner, org, bid, "audit_serp", "queued")
    # A value JSONB cannot store makes the write itself fail.
    monkeypatch.setattr(
        worker, "_serp_results", lambda *args: [{"bad": object()}]
    )
    assert _run(Fetch(Response(200, body()))) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.error, job.cost_micros) == (
        "failed",
        "error",
        8_000,
    )
    assert _rows(owner, bid) == []


def test_missing_credentials_fail_with_no_call_and_no_rows(
    monkeypatch, owner, make_org, make_brand
):
    monkeypatch.setattr(worker, "get_settings", _settings(password=""))
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    job_id = _job(owner, org, bid, "audit_serp", "queued")
    fetch = Fetch(Response(200, body()))
    assert _run(fetch) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.error, job.cost_micros) == (
        "failed",
        "serp_not_configured",
        0,
    )
    assert fetch.calls == [] and _rows(owner, bid) == []


def test_only_the_first_locale_is_audited(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")  # comes with IN/en
    with owner() as s, s.begin():
        for language in ("hi", "ta", "te", "bn", "mr", "gu"):
            s.add(
                m.Locale(
                    org_id=org.id, brand_id=bid, country="IN", language=language
                )
            )
    job_id = _job(owner, org, bid, "audit_serp", "queued")
    fetch = Fetch(Response(200, body()))
    assert _run(fetch) is True
    assert len(fetch.calls) == 2 and len(_rows(owner, bid)) == 2
    job = _load_job(owner, job_id)
    assert (job.status, job.cost_micros) == ("done", 8_000)


def test_a_brand_with_no_locale_uses_in_en(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    with owner() as s, s.begin():
        s.execute(delete(m.Locale).where(m.Locale.brand_id == bid))
    _job(owner, org, bid, "audit_serp", "queued")
    assert _run(Fetch(Response(200, body()))) is True
    assert [(r.country, r.language) for r in _rows(owner, bid)] == [
        ("IN", "en"),
        ("IN", "en"),
    ]


def test_no_transaction_is_open_during_the_calls(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    _job(owner, org, bid, "audit_serp", "queued")
    seen = []

    def fetch(url, user_agent, **kw):
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
        return Response(200, body())

    assert _run(fetch) is True
    assert seen == [0, 0]


def test_an_over_budget_serp_job_fails_without_a_call(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    job_id = _job(owner, org, bid, "audit_serp", "queued")
    with owner() as s, s.begin():
        # $0.03 is under the job's $0.04 estimate.
        s.execute(
            update(m.Organization)
            .where(m.Organization.id == org.id)
            .values(daily_budget_usd=Decimal("0.03"))
        )
    fetch = Fetch(Response(200, body()))
    assert _run(fetch) is True
    job = _load_job(owner, job_id)
    assert (job.status, job.error, job.cost_micros) == ("failed", "budget", 0)
    assert fetch.calls == []


def _page(owner, org, bid, kind, days_ago=0, error=None, results=()):
    with owner() as s, s.begin():
        s.add(
            m.SerpAudit(
                org_id=org.id,
                brand_id=bid,
                kind=kind,
                query="q",
                country="IN",
                language="en",
                results=list(results),
                fetched_at=datetime.now(UTC) - timedelta(days=days_ago),
                error=error,
            )
        )


def _old_job(owner, org, bid, status, hours, kind="audit_serp"):
    """A job created `hours` ago, in its own slot."""
    return _job(
        owner,
        org,
        bid,
        kind,
        status,
        minutes=-60 * hours,
        created_at=datetime.now(UTC) - timedelta(hours=hours),
    )


def _declared(owner, org, bid):
    """Give the brand a domain: only a brand with one is ever due."""
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host="walkaroo.in"))
    return bid


def due():
    with system_session() as s:
        return [
            r[0]
            for r in s.execute(text("SELECT brand_id FROM due_serp_audits()"))
        ]


def _serp_jobs(owner):
    with owner() as s:
        return list(
            s.scalars(
                select(m.Job)
                .where(m.Job.kind == "audit_serp")
                .order_by(m.Job.created_at, m.Job.id)
            )
        )


def test_a_brand_with_no_pages_and_no_jobs_is_due(owner, make_org, make_brand):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    assert due() == [bid]


def test_a_brand_with_no_domain_is_not_due_until_one_is_declared(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    assert due() == []
    _declared(owner, org, bid)
    assert due() == [bid]


def test_good_pages_for_both_queries_this_week_are_not_due(
    owner, make_org, make_brand
):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    _page(owner, org, bid, "brand", 6, results=[{"position": 1}])
    _page(owner, org, bid, "reviews", 6, results=[{"position": 1}])
    assert due() == []


def test_due_again_once_the_pages_are_over_seven_days_old(
    owner, make_org, make_brand
):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    _page(owner, org, bid, "brand", 8)
    _page(owner, org, bid, "reviews", 6)
    assert due() == [bid]  # one page is too old
    _page(owner, org, bid, "brand", 6)
    assert due() == []
    with owner() as s, s.begin():
        s.execute(
            update(m.SerpAudit).values(
                fetched_at=datetime.now(UTC) - timedelta(days=8)
            )
        )
    assert due() == [bid]


def test_one_good_page_and_one_failed_page_is_due(owner, make_org, make_brand):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    _page(owner, org, bid, "brand")
    _page(owner, org, bid, "brand")  # two pages of one kind are one kind
    assert due() == [bid]
    _page(owner, org, bid, "reviews", error="timeout")
    assert due() == [bid]  # an error page is not a page
    _page(owner, org, bid, "reviews")
    assert due() == []


def test_a_good_page_with_no_results_counts(owner, make_org, make_brand):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    _page(owner, org, bid, "brand", results=[])
    _page(owner, org, bid, "reviews", results=[])
    assert due() == []


@pytest.mark.parametrize("status", ["failed", "done"])
def test_a_job_in_the_last_day_blocks_whatever_its_status(
    owner, make_org, make_brand, status
):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    job_id = _old_job(owner, org, bid, status, 23)
    assert due() == []
    with owner() as s, s.begin():
        s.execute(
            update(m.Job)
            .where(m.Job.id == job_id)
            .values(created_at=datetime.now(UTC) - timedelta(hours=25))
        )
    assert due() == [bid]


@pytest.mark.parametrize("status", ["queued", "running"])
def test_a_waiting_job_blocks_however_old(owner, make_org, make_brand, status):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    job_id = _old_job(owner, org, bid, status, 72)
    assert due() == []
    with owner() as s, s.begin():
        s.execute(
            update(m.Job).where(m.Job.id == job_id).values(status="failed")
        )
    assert due() == [bid]


def test_three_failed_jobs_in_a_week_stop_the_retries(
    owner, make_org, make_brand
):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    first = _old_job(owner, org, bid, "failed", 30)
    _old_job(owner, org, bid, "failed", 60)
    _old_job(owner, org, bid, "done", 90)  # only failures count
    _old_job(owner, org, bid, "failed", 100, kind="audit_crawl")
    assert due() == [bid]
    _old_job(owner, org, bid, "failed", 120)
    assert due() == []
    with owner() as s, s.begin():
        s.execute(
            update(m.Job)
            .where(m.Job.id == first)
            .values(created_at=datetime.now(UTC) - timedelta(days=8))
        )
    assert due() == [bid]  # two failures left in the window


def test_a_job_of_another_kind_does_not_block(owner, make_org, make_brand):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    _old_job(owner, org, bid, "done", 1, kind="audit_crawl")
    _old_job(owner, org, bid, "queued", 2, kind="crawl_rivals")
    assert due() == [bid]


def test_archived_brands_are_never_due_for_a_serp_audit(
    owner, make_org, make_brand
):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand).where(m.Brand.id == bid).values(status="archived")
        )
    assert due() == []


def test_due_serves_every_tenant_in_brand_id_order(owner, make_org, make_brand):
    a = make_org("A")
    b = make_org("B")
    brands = [
        _declared(owner, org, make_brand(org, f"B{i}"))
        for i in range(3)
        for org in (a, b)
    ]
    assert due() == sorted(brands)


def test_the_sweep_queues_one_job_per_due_brand_once(
    configured, owner, make_org, make_brand
):
    a = make_org("A")
    b = make_org("B")
    brands = {
        _declared(owner, a, make_brand(a)),
        _declared(owner, b, make_brand(b)),
    }
    assert worker.queue_due_serp_audits() == 2
    assert worker.queue_due_serp_audits() == 0  # a job is waiting
    jobs = _serp_jobs(owner)
    assert {j.brand_id for j in jobs} == brands and len(jobs) == 2
    assert all((j.status, j.params) == ("queued", {}) for j in jobs)


def test_the_sweep_retries_a_failed_audit_after_a_day_not_before(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    assert worker.queue_due_serp_audits() == 1
    (job,) = _serp_jobs(owner)
    with owner() as s, s.begin():
        s.execute(
            update(m.Job)
            .where(m.Job.id == job.id)
            .values(status="failed", error="timeout")
        )
    assert worker.queue_due_serp_audits() == 0
    assert [(j.id, j.status) for j in _serp_jobs(owner)] == [(job.id, "failed")]
    with owner() as s, s.begin():
        s.execute(
            update(m.Job)
            .where(m.Job.id == job.id)
            .values(
                created_at=datetime.now(UTC) - timedelta(hours=25),
                scheduled_slot=datetime.now(UTC) - timedelta(hours=25),
            )
        )
    assert worker.queue_due_serp_audits() == 1
    assert [(j.brand_id, j.status) for j in _serp_jobs(owner)] == [
        (bid, "failed"),
        (bid, "queued"),
    ]


def test_the_sweep_skips_a_brand_while_the_budget_has_no_room(
    configured, owner, make_org, make_brand
):
    org = make_org()
    _declared(owner, org, make_brand(org))

    def budget(usd):
        with owner() as s, s.begin():
            s.execute(
                update(m.Organization)
                .where(m.Organization.id == org.id)
                .values(daily_budget_usd=Decimal(usd))
            )

    budget("0.03")  # under the job's $0.04 estimate
    assert worker.queue_due_serp_audits() == 0
    assert _serp_jobs(owner) == []  # no job, so the brand stays due
    budget("0.04")
    assert worker.queue_due_serp_audits() == 1
    assert [j.status for j in _serp_jobs(owner)] == ["queued"]


@pytest.mark.parametrize(
    "missing", [{"login": ""}, {"password": ""}], ids=["login", "password"]
)
def test_the_sweep_queues_nothing_without_credentials(
    monkeypatch, owner, make_org, make_brand, missing
):
    monkeypatch.setattr(worker, "get_settings", _settings(**missing))
    org = make_org()
    bid = _declared(owner, org, make_brand(org))
    assert due() == [bid]
    assert worker.queue_due_serp_audits() == 0
    assert _serp_jobs(owner) == []


def test_a_swept_job_stores_the_pages_and_the_brand_is_no_longer_due(
    configured, owner, make_org, make_brand
):
    org = make_org()
    bid = _declared(owner, org, make_brand(org, "Walkaroo"))
    assert worker.queue_due_serp_audits() == 1
    assert _run(Fetch(Response(200, body()))) is True
    (job,) = _serp_jobs(owner)
    assert (job.status, job.error) == ("done", None)
    assert [(r.kind, r.error) for r in _rows(owner, bid)] == [
        ("brand", None),
        ("reviews", None),
    ]
    # Not due for a week, even once the job is over a day old.
    with owner() as s, s.begin():
        s.execute(
            update(m.Job)
            .where(m.Job.id == job.id)
            .values(created_at=datetime.now(UTC) - timedelta(hours=25))
        )
    assert due() == []


def test_serp_audit_is_indexed_by_brand_and_fetch_time(owner):
    with owner() as s:
        found = s.scalars(
            text(
                "SELECT indexdef FROM pg_indexes WHERE tablename = "
                "'serp_audit' AND indexname = 'ix_serp_audit_brand_fetched'"
            )
        ).all()
    assert found == [
        "CREATE INDEX ix_serp_audit_brand_fetched ON public.serp_audit "
        "USING btree (brand_id, fetched_at)"
    ]
    (index,) = [
        i
        for i in m.SerpAudit.__table__.indexes
        if i.name == "ix_serp_audit_brand_fetched"
    ]
    assert [c.name for c in index.columns] == ["brand_id", "fetched_at"]
