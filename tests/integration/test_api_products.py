"""The products API (slice 18): import, run, export, delete."""

from bsi_core import models as m
from bsi_core.db import system_session
from sqlalchemy import select, text

CSV = (
    "title,id,url,attributes\n"
    "Walkaroo Boys Sandal,W-1,https://walkaroo.in/p/1,Size: 10\n"
    "Walkaroo Kids Shoe,W-2,,\n"
    ",W-3,,\n"
)
CSV_HEADERS = {"Content-Type": "text/csv"}


def _import(client, org, bid, body=CSV):
    return client.post(
        f"/v1/brands/{bid}/products/import/csv",
        content=body,
        headers={**org.headers, **CSV_HEADERS},
    )


def _products(owner, bid):
    with owner() as s:
        return list(
            s.scalars(
                select(m.Product)
                .where(m.Product.brand_id == bid)
                .order_by(m.Product.external_id)
            )
        )


def test_csv_import_round_trip_keeps_result_columns(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org, "Walkaroo")
    r = _import(client, org, bid)
    assert r.status_code == 201, r.text
    assert r.json() == {"created": 2, "updated": 0, "skipped": 1, "total": 2}
    rows = _products(owner, bid)
    assert [p.external_id for p in rows] == ["W-1", "W-2"]
    assert rows[0].attributes == {"size": "10"} and rows[0].source == "csv"
    with owner() as s, s.begin():
        p = s.get(m.Product, rows[0].id)
        p.keyword, p.suggested_title, p.rule_check = "kids sandals", "X", "pass"
    r = _import(client, org, bid, CSV.replace("Boys Sandal", "Boys Sandal 2"))
    assert r.json() == {"created": 0, "updated": 2, "skipped": 1, "total": 2}
    rows = _products(owner, bid)
    assert rows[0].title == "Walkaroo Boys Sandal 2"
    assert (rows[0].keyword, rows[0].suggested_title) == ("kids sandals", "X")


def test_csv_import_refuses_the_catalogue_cap_and_writes_nothing(
    client, owner, make_org, make_brand, monkeypatch
):
    from bsi_core import products

    monkeypatch.setattr(products, "MAX_PRODUCTS", 1)
    org = make_org()
    bid = make_brand(org)
    r = _import(client, org, bid)
    assert r.status_code == 422
    assert r.json()["title"] == "Catalogue cap is 1,000 products"
    assert _products(owner, bid) == []


def test_csv_import_refuses_a_large_body(client, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    big = "title\n" + ("x" * 1024 + "\n") * (5 * 1024)
    r = _import(client, org, bid, big)
    assert r.status_code == 413


def test_feed_import_queues_a_job_and_rejects_non_http(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    r = client.post(
        f"/v1/brands/{bid}/products/import/feed",
        json={"url": "ftp://x.in/feed.xml"},
        headers=org.headers,
    )
    assert r.status_code == 422
    r = client.post(
        f"/v1/brands/{bid}/products/import/feed",
        json={"url": "https://x.in/feed.xml"},
        headers=org.headers,
    )
    assert r.status_code == 202 and r.json()["status"] == "queued"
    with owner() as s:
        job = s.scalars(select(m.Job).where(m.Job.kind == "import_feed")).one()
    assert job.params == {"url": "https://x.in/feed.xml"}


def test_run_needs_products_then_queues_with_the_locale(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    r = client.post(f"/v1/brands/{bid}/products/run", headers=org.headers)
    assert r.status_code == 422 and r.json()["title"] == "No products to run"
    _import(client, org, bid)
    r = client.post(f"/v1/brands/{bid}/products/run", headers=org.headers)
    assert r.status_code == 202
    with owner() as s:
        job = s.scalars(select(m.Job).where(m.Job.kind == "product_run")).one()
    assert job.params == {
        "locale": {"country": "IN", "language": "en"},
        "product_count": 2,
    }
    r = client.get(f"/v1/brands/{bid}/products/runs", headers=org.headers)
    body = r.json()
    assert [j["kind"] for j in body["jobs"]] == ["product_run"]
    assert (body["done"], body["total"]) == (0, 2)


def test_list_and_export(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _import(client, org, bid)
    with owner() as s, s.begin():
        p = s.scalars(
            select(m.Product).where(m.Product.external_id == "W-1")
        ).one()
        p.keyword = "kids sandals"
        p.missing_keywords = ["summer", "kids"]
        p.suggested_title = "Walkaroo Kids Summer Sandal for Boys"
        p.suggested_bullets = ["Light", "Washable"]
        p.rule_check = "adjusted"
    r = client.get(f"/v1/brands/{bid}/products", headers=org.headers)
    assert [p["external_id"] for p in r.json()] == ["W-1", "W-2"]
    assert r.json()[0]["missing_keywords"] == ["summer", "kids"]
    r = client.get(f"/v1/brands/{bid}/products/export.csv", headers=org.headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == (
        f'attachment; filename="products-{bid}.csv"'
    )
    lines = r.text.splitlines()
    assert lines[0] == (
        "external_id,url,title,keyword,missing_keywords,"
        "suggested_title,suggested_bullets,rule_check"
    )
    assert lines[1] == (
        "W-1,https://walkaroo.in/p/1,Walkaroo Boys Sandal,kids sandals,"
        "summer|kids,Walkaroo Kids Summer Sandal for Boys,Light|Washable,"
        "adjusted"
    )
    assert lines[2] == "W-2,,Walkaroo Kids Shoe,,,,,"


def test_delete_clears_products_and_searches(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _import(client, org, bid)
    with owner() as s, s.begin():
        s.add(
            m.KeywordSearch(
                org_id=org.id, brand_id=bid, keyword="kids sandals", query="q"
            )
        )
    r = client.delete(f"/v1/brands/{bid}/products", headers=org.headers)
    assert r.status_code == 204
    with owner() as s:
        assert s.scalar(select(m.Product).limit(1)) is None
        assert s.scalar(select(m.KeywordSearch).limit(1)) is None


def test_csv_import_into_another_orgs_brand_is_404(
    client, make_org, make_brand
):
    org_a, org_b = make_org("A"), make_org("B")
    bid_b = make_brand(org_b, "Secret")
    r = _import(client, org_a, bid_b)
    assert r.status_code == 404 and "Secret" not in r.text


def test_no_request_leaves_an_idle_transaction(client, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    _import(client, org, bid)
    client.get(f"/v1/brands/{bid}/products/export.csv", headers=org.headers)
    with system_session() as s:
        idle = s.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = "
                "current_database() AND state LIKE 'idle in transaction%' "
                "AND pid <> pg_backend_pid()"
            )
        ).scalar_one()
    assert idle == 0


def test_duplicate_ids_in_one_import_keep_the_last_row(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    body = "title,id\nFirst Title,W-1\nSecond Title,W-1\n"
    r = _import(client, org, bid, body)
    assert r.status_code == 201, r.text
    assert r.json() == {"created": 1, "updated": 0, "skipped": 0, "total": 1}
    assert [p.title for p in _products(owner, bid)] == ["Second Title"]


def test_csv_import_ignores_a_leading_bom(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    r = _import(client, org, bid, b"\xef\xbb\xbf" + CSV.encode())
    assert r.status_code == 201, r.text
    assert r.json() == {"created": 2, "updated": 0, "skipped": 1, "total": 2}
