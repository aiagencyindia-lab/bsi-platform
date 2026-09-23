from datetime import timedelta

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
