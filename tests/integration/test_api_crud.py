import threading

import pytest
from bsi_core import models as m
from sqlalchemy import func, select, update

from tests.integration.test_api_recommendations import _wait_until_blocked


def test_health_needs_no_key(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_missing_and_unknown_key_are_401(client, make_org):
    make_org()
    for headers in ({}, {"Authorization": "Bearer nope"}):
        r = client.get("/v1/brands", headers=headers)
        assert r.status_code == 401
        assert r.headers["content-type"] == "application/problem+json"
        assert r.json()["request_id"] == r.headers["x-request-id"]


def test_request_id_is_echoed(client, make_org):
    h = {**make_org().headers, "X-Request-Id": "abc-123"}
    assert client.get("/v1/brands", headers=h).headers["x-request-id"] == (
        "abc-123"
    )


def test_brand_lifecycle(client, make_org):
    h = make_org().headers
    r = client.post(
        "/v1/brands", headers=h, json={"name": "Acme", "aliases": ["ACME Co"]}
    )
    assert r.status_code == 201
    bid = r.json()["id"]
    assert [b["id"] for b in client.get("/v1/brands", headers=h).json()] == [
        bid
    ]
    r = client.patch(f"/v1/brands/{bid}", headers=h, json={"category": "shoes"})
    assert r.json()["category"] == "shoes"
    assert r.json()["aliases"] == ["ACME Co"]
    assert client.delete(f"/v1/brands/{bid}", headers=h).status_code == 204
    assert client.get(f"/v1/brands/{bid}", headers=h).json()["status"] == (
        "archived"
    )


def test_validation_error_is_problem_json(client, make_org):
    r = client.post("/v1/brands", headers=make_org().headers, json={})
    assert r.status_code == 422
    body = r.json()
    assert body["status"] == 422 and body["errors"][0]["loc"][-1] == "name"


def test_other_orgs_brand_is_404(client, make_org, make_brand):
    a, b = make_org("A"), make_org("B")
    bid = make_brand(b)
    assert client.get(f"/v1/brands/{bid}", headers=a.headers).status_code == 404


def test_competitors_and_domains(client, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    base = f"/v1/brands/{bid}"
    r = client.post(
        f"{base}/competitors",
        headers=org.headers,
        json={"name": "Rival", "aliases": ["Rival Inc"], "domains": []},
    )
    cid = r.json()["id"]
    client.patch(
        f"{base}/competitors/{cid}", headers=org.headers, json={"name": "R2"}
    )
    got = client.get(f"{base}/competitors", headers=org.headers).json()
    assert [c["name"] for c in got] == ["R2"]
    assert (
        client.delete(
            f"{base}/competitors/{cid}", headers=org.headers
        ).status_code
        == 204
    )

    r = client.post(
        f"{base}/domains",
        headers=org.headers,
        json={"host": "https://www.Acme.com/shop", "is_primary": True},
    )
    assert r.json()["host"] == "acme.com"
    r = client.post(
        f"{base}/domains", headers=org.headers, json={"host": "acme.com"}
    )
    assert r.status_code == 409


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "127.0.0.1",
        "http://169.254.169.254/latest",
        "[::1]",
        "10.1",
    ],
)
def test_a_host_that_is_not_a_public_name_is_422(
    client, make_org, make_brand, host
):
    org = make_org()
    base = f"/v1/brands/{make_brand(org)}"
    h = org.headers
    r = client.post(f"{base}/domains", headers=h, json={"host": host})
    assert r.status_code == 422, r.text
    assert r.json()["errors"][0]["loc"][-1] == "host"
    r = client.post(
        f"{base}/competitors", headers=h, json={"name": "R", "domains": [host]}
    )
    assert r.status_code == 422, r.text
    cid = client.post(
        f"{base}/competitors",
        headers=h,
        json={"name": "R", "domains": ["r.com"]},
    ).json()["id"]
    r = client.patch(
        f"{base}/competitors/{cid}",
        headers=h,
        json={"domains": ["ok.com", host]},
    )
    assert r.status_code == 422, r.text
    got = client.get(f"{base}/competitors", headers=h).json()
    assert got[0]["domains"] == ["r.com"]  # the bad PATCH wrote nothing


def test_competitor_domains_are_normalized(client, make_org, make_brand):
    org = make_org()
    base = f"/v1/brands/{make_brand(org)}"
    h = org.headers
    r = client.post(
        f"{base}/competitors",
        headers=h,
        json={"name": "R", "domains": ["https://WWW.Rival.com/x"]},
    )
    assert r.json()["domains"] == ["rival.com"]
    r = client.patch(
        f"{base}/competitors/{r.json()['id']}",
        headers=h,
        json={"domains": ["Shop.Rival.com:443"]},
    )
    assert r.json()["domains"] == ["shop.rival.com"]


def test_prompts_single_bulk_and_pause(client, make_org, make_brand):
    org = make_org()
    base = f"/v1/brands/{make_brand(org)}/prompts"
    one = client.post(base, headers=org.headers, json={"text": "best shoes"})
    assert one.status_code == 201 and len(one.json()) == 1
    many = client.post(
        base, headers=org.headers, json=[{"text": "a"}, {"text": "b"}]
    )
    assert len(many.json()) == 2
    pid = one.json()[0]["id"]
    r = client.patch(
        f"{base}/{pid}", headers=org.headers, json={"status": "paused"}
    )
    assert r.json()["status"] == "paused"
    assert len(client.get(base, headers=org.headers).json()) == 3


def test_null_for_a_required_field_is_422(client, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    cid = client.post(
        f"/v1/brands/{bid}/competitors", headers=org.headers, json={"name": "R"}
    ).json()["id"]
    cases = [
        (f"/v1/brands/{bid}", {"name": None}),
        (f"/v1/brands/{bid}", {"aliases": None}),
        (f"/v1/brands/{bid}/competitors/{cid}", {"name": None}),
        (f"/v1/brands/{bid}/competitors/{cid}", {"aliases": None}),
        (f"/v1/brands/{bid}/competitors/{cid}", {"domains": None}),
    ]
    for path, body in cases:
        r = client.patch(path, headers=org.headers, json=body)
        assert r.status_code == 422, (path, body, r.text)
        assert r.json()["errors"][0]["loc"][-1] == next(iter(body))


def test_category_can_be_cleared(client, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    client.patch(
        f"/v1/brands/{bid}", headers=org.headers, json={"category": "shoes"}
    )
    r = client.patch(
        f"/v1/brands/{bid}", headers=org.headers, json={"category": None}
    )
    assert r.status_code == 200
    assert r.json()["category"] is None


def test_an_archived_brand_accepts_no_new_domain(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand).where(m.Brand.id == bid).values(status="archived")
        )
    base = f"/v1/brands/{bid}/domains"
    r = client.post(base, headers=org.headers, json={"host": "acme.com"})
    assert r.status_code == 409, r.text
    assert r.json()["title"] == "Brand is archived"
    assert client.get(base, headers=org.headers).json() == []


def test_a_host_is_capped_at_200_characters(client, make_org, make_brand):
    org = make_org()
    base = f"/v1/brands/{make_brand(org)}/domains"
    at_cap = "a" * 196 + ".com"
    r = client.post(base, headers=org.headers, json={"host": at_cap})
    assert r.status_code == 201, r.text
    r = client.post(base, headers=org.headers, json={"host": "a" + at_cap})
    assert r.status_code == 422, r.text
    assert r.json()["errors"][0]["loc"][-1] == "host"


def test_a_simultaneous_duplicate_domain_is_409_not_500(
    client, owner, make_org, make_brand
):
    """A first submit that has inserted the host and not yet committed: the
    second must wait on the unique index, then see the row and get 409,
    never a raw unique violation as a 500 (and never two rows)."""
    org = make_org()
    bid = make_brand(org)
    holder = owner()
    holder.begin()
    holder.add(m.Domain(org_id=org.id, brand_id=bid, host="acme.com"))
    holder.flush()
    result: dict[str, object] = {}

    def post() -> None:
        result["response"] = client.post(
            f"/v1/brands/{bid}/domains",
            headers=org.headers,
            json={"host": "acme.com"},
        )

    t = threading.Thread(target=post)
    t.start()
    try:
        assert _wait_until_blocked(holder), (
            "the POST never waited on the uncommitted row; the test would "
            "pass whether or not the insert handles the conflict"
        )
        holder.commit()
        t.join(timeout=5)
        assert not t.is_alive()
    finally:
        holder.close()
    response = result["response"]
    assert response.status_code == 409, response.text
    assert response.json()["title"] == "Domain already exists"
    with owner() as s:
        rows = s.scalar(
            select(func.count())
            .select_from(m.Domain)
            .where(m.Domain.brand_id == bid)
        )
    assert rows == 1
