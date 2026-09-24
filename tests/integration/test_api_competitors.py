from datetime import timedelta

from bsi_core import models as m
from sqlalchemy import update

from tests.integration.test_competitors import (  # noqa: F401
    NOW,
    feed,
    scene,
)


def test_metrics_lists_brand_and_active_rivals(client, scene):  # noqa: F811
    org, bid, _ = scene
    r = client.get(f"/v1/brands/{bid}/competitors/metrics", headers=org.headers)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [x["name"] for x in rows] == ["Nike", "Adidas", "Puma"]
    adidas = rows[1]
    assert adidas["mention_rate"]["value"] == 0.4
    assert adidas["recommendation_rate"]["experimental"] is True
    assert adidas["sentiment"]["index"] == 0.0
    assert adidas["citing_domains"][0]["owner"] == "third_party"


def test_metrics_honours_filters(client, scene):  # noqa: F811
    org, bid, ids = scene
    r = client.get(
        f"/v1/brands/{bid}/competitors/metrics?prompt_ids={ids['p1']}",
        headers=org.headers,
    )
    assert r.json()[1]["mention_rate"]["n"] == 2


def test_deltas_and_changes(client, feed):  # noqa: F811
    org, bid, ids = feed
    # params=, not an f-string: "+00:00" in a raw query string reads as
    # a space.
    q = {"days": 14, "date_to": NOW.isoformat()}
    r = client.get(
        f"/v1/brands/{bid}/competitors/deltas", params=q, headers=org.headers
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["comparable"] is True
    assert d["deltas"][str(ids["a"])]["mention_rate"]["label"] == "increase"
    assert (
        d["after"]["entities"][0]["recommendation_rate"]["experimental"] is True
    )
    r = client.get(
        f"/v1/brands/{bid}/competitors/changes", params=q, headers=org.headers
    )
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["prompts"] == 12
    assert set(c["window"]) == {"before_from", "split", "to"}
    assert c["window"]["to"].startswith(NOW.isoformat()[:19])
    assert [x["name"] for x in c["changes"]] == ["A"]
    assert c["changes"][0]["direction"] == "up"
    assert c["changes"][0]["new_citing_domains"] == ["new.com"]
    assert len(c["changes"][0]["observation_ids"]) == 20


def test_date_from_is_rejected_on_window_routes(client, scene):  # noqa: F811
    org, bid, _ = scene
    frm = (NOW - timedelta(days=3)).isoformat()
    for route in ("deltas", "changes"):
        r = client.get(
            f"/v1/brands/{bid}/competitors/{route}",
            params={"date_from": frm},
            headers=org.headers,
        )
        assert r.status_code == 422, route
        # The route's own refusal, not a parse error on the timestamp.
        assert "date_from is not allowed" in r.text, route


def test_unknown_brand_is_404(client, make_org):
    org = make_org()
    for route in ("metrics", "deltas", "changes"):
        r = client.get(
            f"/v1/brands/00000000-0000-0000-0000-000000000000/competitors/{route}",
            headers=org.headers,
        )
        assert r.status_code == 404, route


def test_patch_and_delete_on_metrics_are_a_uuid_parse_error(client, scene):  # noqa: F811
    """/competitors/metrics shares its path with /competitors/{id}: the
    write routes must read "metrics" as a bad id, not act on anything."""
    org, bid, _ = scene
    url = f"/v1/brands/{bid}/competitors/metrics"
    for r in (
        client.patch(url, json={"status": "active"}, headers=org.headers),
        client.delete(url, headers=org.headers),
    ):
        assert r.status_code == 422, r.text
        assert "uuid" in r.text.lower(), r.text


def test_crawl_route_queues_one_job_per_hour(client, owner, scene):  # noqa: F811
    org, bid, _ = scene
    r = client.post(f"/v1/brands/{bid}/competitors/crawl", headers=org.headers)
    assert r.status_code == 202, r.text
    again = client.post(
        f"/v1/brands/{bid}/competitors/crawl", headers=org.headers
    )
    assert again.json()["job_id"] == r.json()["job_id"]
    with owner() as s:
        job = s.get(m.Job, r.json()["job_id"])
    assert (job.kind, job.status) == ("crawl_rivals", "queued")


def test_crawl_route_on_an_archived_brand_is_409(client, owner, scene):  # noqa: F811
    org, bid, _ = scene
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand).where(m.Brand.id == bid).values(status="archived")
        )
    r = client.post(f"/v1/brands/{bid}/competitors/crawl", headers=org.headers)
    assert r.status_code == 409


def test_site_changes_route(client, owner, scene):  # noqa: F811
    org, bid, ids = scene
    with owner() as s, s.begin():
        s.add(
            m.RivalPage(
                org_id=org.id,
                brand_id=bid,
                competitor_id=ids["adidas"],
                domain="adidas.co.in",
                url="https://adidas.co.in/n",
            )
        )
    url = f"/v1/brands/{bid}/competitors/site-changes"
    r = client.get(url, headers=org.headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["competitors"][0]["name"] == "Adidas"
    assert body["competitors"][0]["new_pages"][0]["url"] == (
        "https://adidas.co.in/n"
    )
    bad = client.get(url, params={"days": 0}, headers=org.headers)
    assert bad.status_code == 422
    refused = client.get(
        url,
        params={"date_from": "2026-01-01T00:00:00+00:00"},
        headers=org.headers,
    )
    assert refused.status_code == 422
