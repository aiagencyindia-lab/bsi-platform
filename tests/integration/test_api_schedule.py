from datetime import datetime

from bsi_core import models as m
from sqlalchemy import func, select, update


def _url(bid):
    return f"/v1/brands/{bid}/schedule"


def _db_now(owner):
    with owner() as s:
        return s.scalars(select(func.now())).one()


def test_put_creates_then_replaces(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    r = client.put(
        _url(bid), headers=org.headers, json={"cadence": "daily", "hour_utc": 5}
    )
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["brand_id"] == str(bid)
    assert got["cadence"] == "daily" and got["hour_utc"] == 5
    assert got["samples"] == 2 and got["status"] == "active"
    assert got["last_run_at"] is None and got["last_result"] is None

    ran = datetime.fromisoformat("2026-01-01T05:00:00+00:00")
    with owner() as s, s.begin():
        s.execute(
            update(m.Schedule)
            .where(m.Schedule.brand_id == bid)
            .values(last_run_at=ran, last_result="enqueued:4")
        )

    body = {
        "cadence": "weekly",
        "hour_utc": 17,
        "samples": 3,
        "status": "paused",
    }
    r = client.put(_url(bid), headers=org.headers, json=body)
    assert r.status_code == 200, r.text
    got = r.json()
    assert {k: got[k] for k in body} == body
    nxt = datetime.fromisoformat(got["next_run_at"])
    assert nxt.hour == 17
    # A replace keeps the record of the last run.
    assert datetime.fromisoformat(got["last_run_at"]) == ran
    assert got["last_result"] == "enqueued:4"

    with owner() as s:
        rows = s.scalars(
            select(m.Schedule).where(m.Schedule.brand_id == bid)
        ).all()
    assert len(rows) == 1 and rows[0].cadence == "weekly"
    assert rows[0].next_run_at == nxt


def test_next_run_at_is_the_next_hour_utc(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    before = _db_now(owner)
    r = client.put(
        _url(bid), headers=org.headers, json={"cadence": "daily", "hour_utc": 3}
    )
    nxt = datetime.fromisoformat(r.json()["next_run_at"])
    assert nxt > before
    assert (nxt.hour, nxt.minute, nxt.second) == (3, 0, 0)
    assert nxt.utcoffset().total_seconds() == 0


def test_get_and_delete(client, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    assert client.get(_url(bid), headers=org.headers).status_code == 404
    client.put(
        _url(bid), headers=org.headers, json={"cadence": "daily", "hour_utc": 1}
    )
    r = client.get(_url(bid), headers=org.headers)
    assert r.status_code == 200 and r.json()["cadence"] == "daily"
    assert client.delete(_url(bid), headers=org.headers).status_code == 204
    assert client.get(_url(bid), headers=org.headers).status_code == 404
    assert client.delete(_url(bid), headers=org.headers).status_code == 404


def test_archived_brand_is_409(client, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    client.delete(f"/v1/brands/{bid}", headers=org.headers)
    r = client.put(
        _url(bid), headers=org.headers, json={"cadence": "daily", "hour_utc": 1}
    )
    assert r.status_code == 409
    assert r.headers["content-type"] == "application/problem+json"


def test_invalid_bodies_are_422(client, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    ok = {"cadence": "daily", "hour_utc": 1}
    cases = [
        ({**ok, "extra": 1}, "extra"),
        ({**ok, "hour_utc": 24}, "hour_utc"),
        ({**ok, "cadence": "hourly"}, "cadence"),
    ]
    for body, field in cases:
        r = client.put(_url(bid), headers=org.headers, json=body)
        assert r.status_code == 422, (body, r.text)
        assert r.json()["errors"][0]["loc"][-1] == field
    assert client.get(_url(bid), headers=org.headers).status_code == 404
