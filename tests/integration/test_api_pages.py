from bsi_core import models as m
from sqlalchemy import update

from tests.integration.test_gaps import scene  # noqa: F401
from tests.integration.test_recommend import _page_audit

KEY = "cluster:comparison:running shoes"


def test_optimize_queues_one_job_per_request(client, owner, scene):  # noqa: F811
    body = {"url": "HTTPS://Nike.com/run#top", "cluster_key": KEY}
    url = f"/v1/brands/{scene.brand}/pages/optimize"
    r1 = client.post(url, json=body, headers=scene.org.headers)
    r2 = client.post(url, json=body, headers=scene.org.headers)
    assert r1.status_code == 202 and r2.status_code == 202, r1.text
    assert r1.json()["job_id"] != r2.json()["job_id"]
    with owner() as s:
        job = s.get(m.Job, r1.json()["job_id"])
    assert (job.kind, job.status) == ("optimize_url", "queued")
    assert job.params == {"url": "https://nike.com/run", "cluster_key": KEY}


def test_optimize_rejects_bad_urls_and_unknown_clusters(client, scene):  # noqa: F811
    base = f"/v1/brands/{scene.brand}/pages/optimize"
    for url in ["ftp://nike.com/x", "nike.com/x", "http://u:p@nike.com/"]:
        body = {"url": url, "cluster_key": KEY}
        r = client.post(base, json=body, headers=scene.org.headers)
        assert r.status_code == 422, url
        assert r.json()["errors"][0]["loc"] == ["body", "url"], r.text
    body = {"url": "https://nike.com/", "cluster_key": "cluster:x:y"}
    r = client.post(base, json=body, headers=scene.org.headers)
    assert r.status_code == 422 and "cluster" in r.json()["detail"].lower()


def test_optimize_on_an_archived_brand_is_409(client, owner, scene):  # noqa: F811
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand)
            .where(m.Brand.id == scene.brand)
            .values(status="archived")
        )
    r = client.post(
        f"/v1/brands/{scene.brand}/pages/optimize",
        json={"url": "https://nike.com/", "cluster_key": KEY},
        headers=scene.org.headers,
    )
    assert r.status_code == 409


def test_list_is_latest_per_url_newest_first(client, owner, scene):  # noqa: F811
    _page_audit(owner, scene.org, scene.brand, "https://nike.com/a", 40)
    newer = _page_audit(owner, scene.org, scene.brand, "https://nike.com/a", 80)
    other = _page_audit(
        owner,
        scene.org,
        scene.brand,
        "https://nike.com/b",
        None,
        key="cluster:informational:sizing",
    )
    r = client.get(f"/v1/brands/{scene.brand}/pages", headers=scene.org.headers)
    assert r.status_code == 200, r.text
    assert [a["id"] for a in r.json()] == [str(other), str(newer)]
    assert r.json()[0]["score"] is None
    assert r.json()[0]["error"] == "ConnectError"
    filtered = client.get(
        f"/v1/brands/{scene.brand}/pages",
        params={"cluster_key": KEY},
        headers=scene.org.headers,
    )
    assert [a["id"] for a in filtered.json()] == [str(newer)]


def test_get_one(client, owner, scene):  # noqa: F811
    aid = _page_audit(owner, scene.org, scene.brand, "https://nike.com/a", 40)
    r = client.get(
        f"/v1/brands/{scene.brand}/pages/{aid}", headers=scene.org.headers
    )
    assert r.status_code == 200 and r.json()["url"] == "https://nike.com/a"
    assert r.json()["evidence"]["prompt_ids"] == ["p0", "p1"]
