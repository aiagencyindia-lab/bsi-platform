from bsi_core import models as m
from sqlalchemy import update

from tests.integration.test_crawl_audit import _audit, _domain


def test_post_queues_an_audit_job(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    r = client.post(f"/v1/brands/{bid}/audits/crawl", headers=org.headers)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["status_url"] == f"/v1/jobs/{body['job_id']}"
    with owner() as s:
        job = s.get(m.Job, body["job_id"])
    assert (job.kind, job.brand_id) == ("audit_crawl", bid)
    # Same hour, same job.
    again = client.post(f"/v1/brands/{bid}/audits/crawl", headers=org.headers)
    assert again.json()["job_id"] == body["job_id"]


def test_post_on_an_archived_brand_is_409(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand).where(m.Brand.id == bid).values(status="archived")
        )
    r = client.post(f"/v1/brands/{bid}/audits/crawl", headers=org.headers)
    assert r.status_code == 409


def test_get_returns_the_latest_audit_per_domain(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _domain(owner, org, bid, "nike.com")
    _domain(owner, org, bid, "nike.in")
    _audit(owner, org, bid, 10, "nike.com")
    with owner() as s, s.begin():
        s.add(
            m.SiteAudit(
                org_id=org.id,
                brand_id=bid,
                domain="nike.com",
                fetches=12,
                checks=[
                    {
                        "code": "llms_missing",
                        "ok": False,
                        "severity": "low",
                        "observed": "HTTP 404",
                        "expected": "x",
                        "url": "https://nike.com/llms.txt",
                    }
                ],
            )
        )
        s.add(m.SiteAudit(org_id=org.id, brand_id=bid, domain="nike.in"))
    r = client.get(f"/v1/brands/{bid}/audits/crawl", headers=org.headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [x["domain"] for x in rows] == ["nike.com", "nike.in"]
    assert rows[0]["fetches"] == 12
    assert rows[0]["checks"][0]["code"] == "llms_missing"
    assert rows[1]["checks"] == []


def test_get_is_empty_before_any_audit(client, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    r = client.get(f"/v1/brands/{bid}/audits/crawl", headers=org.headers)
    assert r.json() == []


def test_get_excludes_audits_of_undeclared_domains(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    # No Domain row for this host: an audit exists but the domain was
    # since removed (or never declared), so it must not appear.
    _audit(owner, org, bid, 1, "ghost.com")
    r = client.get(f"/v1/brands/{bid}/audits/crawl", headers=org.headers)
    assert r.status_code == 200, r.text
    assert r.json() == []
