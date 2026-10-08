from datetime import UTC, datetime, timedelta

from bsi_api.routers import audits
from bsi_core import models as m
from bsi_core.config import Settings
from sqlalchemy import update

from tests.integration.test_worker import _job

OFFICIAL = {
    "position": 1,
    "item_type": "organic",
    "result_type": "official",
    "url": "https://nike.com/",
    "domain": "nike.com",
    "title": "Nike",
    "sitelinks": True,
}
OTHER = {**OFFICIAL, "position": 2, "result_type": "other", "sitelinks": False}
PANEL = {
    "position": 3,
    "item_type": "knowledge_graph",
    "result_type": "knowledge_panel",
    "url": "",
    "domain": "",
    "title": "Nike",
    "sitelinks": False,
}


def _audit(owner, org, bid, kind, minutes_ago, results=(), error=None):
    with owner() as s, s.begin():
        s.add(
            m.SerpAudit(
                org_id=org.id,
                brand_id=bid,
                kind=kind,
                query="nike" if kind == "brand" else "nike reviews",
                country="IN",
                language="en",
                results=list(results),
                fetched_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
                cost_micros=4_000,
                error=error,
            )
        )


def _configured(monkeypatch, login="me", password="pw"):
    """The API's DataForSEO settings, patched where audits.py reads them
    (the lambda bypasses get_settings' lru_cache; explicit kwargs win
    over .env)."""
    monkeypatch.setattr(
        audits,
        "get_settings",
        lambda: Settings(dataforseo_login=login, dataforseo_password=password),
    )


def _aged(owner, job_id, ago):
    """Set a job's created_at (_job sets scheduled_slot only; created_at
    is the server default) to now() - ago."""
    with owner() as s, s.begin():
        s.execute(
            update(m.Job)
            .where(m.Job.id == job_id)
            .values(created_at=datetime.now(UTC) - ago)
        )


def test_post_queues_a_serp_audit_job(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    r = client.post(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert r.status_code == 202, r.text
    queued = r.json()
    assert queued["status"] == "queued"
    with owner() as s:
        job = s.get(m.Job, queued["job_id"])
    assert (job.kind, job.brand_id) == ("audit_serp", bid)
    # Same hour, same job.
    again = client.post(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert again.json()["job_id"] == queued["job_id"]


def test_post_on_an_archived_brand_is_409(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand).where(m.Brand.id == bid).values(status="archived")
        )
    r = client.post(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert r.status_code == 409


def test_get_is_empty_before_any_audit(
    client, make_org, make_brand, monkeypatch
):
    _configured(monkeypatch)
    org = make_org()
    bid = make_brand(org)
    r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "job": None,
        "audits": [],
        "serp_configured": True,
        "failed_7d": 0,
    }


def test_get_returns_the_latest_row_per_query_with_ownership(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _audit(owner, org, bid, "brand", 60, [OTHER])
    _audit(owner, org, bid, "brand", 5, [OFFICIAL, OTHER, PANEL])
    _audit(owner, org, bid, "reviews", 60, [OFFICIAL])
    # The latest reviews row is an error: it is shown, not the older one.
    _audit(owner, org, bid, "reviews", 5, error="rate")
    r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert r.status_code == 200, r.text
    brand, reviews = r.json()["audits"]
    assert (brand["kind"], brand["query"]) == ("brand", "nike")
    assert (brand["country"], brand["language"], brand["device"]) == (
        "IN",
        "en",
        "desktop",
    )
    assert (brand["owned"], brand["organic"]) == (1, 2)
    assert brand["cost_micros"] == 4_000 and brand["error"] is None
    assert brand["results"] == [OFFICIAL, OTHER, PANEL]
    assert (reviews["kind"], reviews["error"]) == ("reviews", "rate")
    assert (reviews["owned"], reviews["organic"]) == (0, 0)
    assert reviews["results"] == []


def test_get_reports_the_latest_audit_serp_job(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _job(owner, org, bid, "audit_serp", "done", minutes=-60)
    newest = _job(
        owner, org, bid, "audit_serp", "failed", error="serp_not_configured"
    )
    with owner() as s, s.begin():
        # created_at orders the jobs; make the failed one the newest
        # audit_serp job.
        s.execute(
            update(m.Job)
            .where(m.Job.id != newest, m.Job.brand_id == bid)
            .values(created_at=datetime.now(UTC) - timedelta(hours=1))
        )
    # Added last, so the brand's newest job of all: the kind filter
    # must skip it.
    _job(owner, org, bid, "audit_crawl", "done", minutes=-120)
    r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert r.status_code == 200, r.text
    assert r.json()["job"] == {
        "status": "failed",
        "error": "serp_not_configured",
    }


def test_get_reports_serp_configured(client, make_org, make_brand, monkeypatch):
    org = make_org()
    bid = make_brand(org)
    for login, password, expected in (
        ("me", "pw", True),
        ("me", "", False),
        ("", "pw", False),
    ):
        _configured(monkeypatch, login, password)
        r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
        assert r.status_code == 200, r.text
        assert r.json()["serp_configured"] is expected, (login, password)


def test_get_counts_failed_audit_serp_jobs_in_7_days(
    client, owner, make_org, make_brand, monkeypatch
):
    _configured(monkeypatch)
    org = make_org()
    bid = make_brand(org)
    # Counted: three failed audit_serp jobs inside the window. Each
    # audit_serp job on a brand needs its own scheduled_slot (minutes).
    for i, days in enumerate((1, 3, 6)):
        job = _job(owner, org, bid, "audit_serp", "failed", minutes=-i)
        _aged(owner, job, timedelta(days=days))
    # Not counted: outside the window; not failed; another kind.
    _aged(
        owner,
        _job(owner, org, bid, "audit_serp", "failed", minutes=-10),
        timedelta(days=8),
    )
    _aged(
        owner,
        _job(owner, org, bid, "audit_serp", "done", minutes=-20),
        timedelta(days=2),
    )
    _aged(
        owner,
        _job(owner, org, bid, "audit_crawl", "failed", minutes=-30),
        timedelta(days=2),
    )
    # Not counted: another brand of the same org (RLS would hide another
    # org's rows whether or not the query filters on brand).
    other = make_brand(org, name="Other")
    for i, days in enumerate((2, 4)):
        job = _job(owner, org, other, "audit_serp", "failed", minutes=-i)
        _aged(owner, job, timedelta(days=days))
    r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert r.status_code == 200, r.text
    assert r.json()["failed_7d"] == 3


def test_failed_7d_window_boundary(
    client, owner, make_org, make_brand, monkeypatch
):
    """A one-minute margin against DB now(): proves the window is 7
    days, not whether its edge is > or >=."""
    _configured(monkeypatch)
    org = make_org()
    bid = make_brand(org)
    inside = _job(owner, org, bid, "audit_serp", "failed", minutes=-1)
    outside = _job(owner, org, bid, "audit_serp", "failed", minutes=-2)
    _aged(owner, inside, timedelta(days=7) - timedelta(minutes=1))
    _aged(owner, outside, timedelta(days=7) + timedelta(minutes=1))
    r = client.get(f"/v1/brands/{bid}/audits/serp", headers=org.headers)
    assert r.status_code == 200, r.text
    assert r.json()["failed_7d"] == 1
