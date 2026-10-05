"""The Brand SERP audit: the table, and what the worker stores."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import bsi_workers.worker as worker
import pytest
from bsi_core import models as m
from bsi_core.config import Settings
from bsi_core.crawl import Response
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
