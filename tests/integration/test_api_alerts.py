from datetime import UTC, datetime

import pytest
from bsi_core import models as m
from sqlalchemy import select

from tests.integration.test_alerts import _alert, _source_scene


def test_list_is_newest_first_and_limited(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    ids = [_alert(owner, org, bid, subject_key=f"d{i}.com") for i in range(3)]
    r = client.get(f"/v1/brands/{bid}/alerts", headers=org.headers)
    assert r.status_code == 200
    assert [a["id"] for a in r.json()] == [str(i) for i in reversed(ids)]
    assert r.json()[0]["delivery_attempts"] == 0
    two = client.get(f"/v1/brands/{bid}/alerts?limit=2", headers=org.headers)
    assert len(two.json()) == 2
    assert (
        client.get(
            f"/v1/brands/{bid}/alerts?limit=0", headers=org.headers
        ).status_code
        == 422
    )


def test_scan_creates_alerts_and_reports_the_count(
    client, owner, make_org, make_brand
):
    org, bid, _ = _source_scene(owner, make_org, make_brand)
    r = client.post(f"/v1/brands/{bid}/alerts/scan", headers=org.headers)
    assert r.status_code == 200 and r.json() == {"created": 1}
    again = client.post(f"/v1/brands/{bid}/alerts/scan", headers=org.headers)
    assert again.json() == {"created": 0}
    with owner() as s:
        brand = s.get(m.Brand, bid)
        alerts = s.scalars(select(m.Alert)).all()
    assert brand.alerts_scanned_at is None  # the daily pass still runs
    assert len(alerts) == 1 and alerts[0].next_attempt_at is None


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("https://hooks.slack.com/services/T0/B0/x", 200),
        ("https://hooks.example.com:443/in", 200),
        ("http://hooks.example.com/in", 422),
        ("https://localhost/x", 422),
        ("https://10.0.0.1/", 422),
        ("https://user:pw@hooks.example.com/in", 422),
        ("https://hooks.example.com:8443/in", 422),
        ("ftp://hooks.example.com/in", 422),
    ],
)
def test_webhook_url_validation(client, make_org, make_brand, url, code):
    org = make_org()
    bid = make_brand(org)
    r = client.patch(
        f"/v1/brands/{bid}", headers=org.headers, json={"webhook_url": url}
    )
    assert r.status_code == code, r.text
    if code == 200:
        assert r.json()["webhook_url"] == url


def test_null_clears_the_webhook(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    client.patch(
        f"/v1/brands/{bid}",
        headers=org.headers,
        json={"webhook_url": "https://hooks.example.com/in"},
    )
    r = client.patch(
        f"/v1/brands/{bid}", headers=org.headers, json={"webhook_url": None}
    )
    assert r.status_code == 200 and r.json()["webhook_url"] is None
    with owner() as s:
        assert s.get(m.Brand, bid).webhook_url is None


def test_clearing_the_webhook_stops_pending_deliveries(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid, other = make_brand(org), make_brand(org, "Other")
    now = datetime.now(UTC)
    pending = _alert(owner, org, bid, next_attempt_at=now)
    kept = _alert(owner, org, other, next_attempt_at=now)
    r = client.patch(
        f"/v1/brands/{bid}", headers=org.headers, json={"webhook_url": None}
    )
    assert r.status_code == 200
    with owner() as s:
        a, b = s.get(m.Alert, pending), s.get(m.Alert, kept)
    assert a.next_attempt_at is None and a.delivered_at is None
    assert b.next_attempt_at is not None


SECRET = "s" * 32


def test_secret_is_write_only_and_shown_as_a_flag(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    r = client.patch(
        f"/v1/brands/{bid}",
        headers=org.headers,
        json={"webhook_secret": SECRET},
    )
    assert r.status_code == 200, r.text
    assert "webhook_secret" not in r.json()
    assert r.json()["has_webhook_secret"] is True
    with owner() as s:
        assert s.get(m.Brand, bid).webhook_secret == SECRET


@pytest.mark.parametrize("secret", ["s" * 31, " " + SECRET])
def test_a_short_or_padded_secret_is_rejected(
    client, make_org, make_brand, secret
):
    org = make_org()
    bid = make_brand(org)
    r = client.patch(
        f"/v1/brands/{bid}",
        headers=org.headers,
        json={"webhook_secret": secret},
    )
    assert r.status_code == 422, r.text


def test_clearing_the_url_also_clears_the_secret(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    client.patch(
        f"/v1/brands/{bid}",
        headers=org.headers,
        json={
            "webhook_url": "https://hooks.example.com/in",
            "webhook_secret": SECRET,
        },
    )
    r = client.patch(
        f"/v1/brands/{bid}", headers=org.headers, json={"webhook_url": None}
    )
    assert r.status_code == 200 and r.json()["has_webhook_secret"] is False
    with owner() as s:
        assert s.get(m.Brand, bid).webhook_secret is None


def test_null_clears_only_the_secret(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    client.patch(
        f"/v1/brands/{bid}",
        headers=org.headers,
        json={
            "webhook_url": "https://hooks.example.com/in",
            "webhook_secret": SECRET,
        },
    )
    r = client.patch(
        f"/v1/brands/{bid}", headers=org.headers, json={"webhook_secret": None}
    )
    assert r.status_code == 200
    assert r.json()["has_webhook_secret"] is False
    assert r.json()["webhook_url"] == "https://hooks.example.com/in"
    with owner() as s:
        assert s.get(m.Brand, bid).webhook_secret is None
