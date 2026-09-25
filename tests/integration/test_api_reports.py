import pytest
from bsi_core import models as m
from bsi_core.db import system_session
from sqlalchemy import select, text

from tests.integration.test_reports import NOW, _definition, _scene


def test_list_synthesises_off_for_missing_definitions(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    _definition(owner, org, bid, "seo", "monthly", NOW)
    r = client.get(f"/v1/brands/{bid}/reports", headers=org.headers)
    assert r.status_code == 200
    rows = r.json()
    assert [x["type"] for x in rows] == [
        "cmo",
        "seo",
        "content",
        "pr",
        "agency",
    ]
    assert [x["cadence"] for x in rows] == [
        "off",
        "monthly",
        "off",
        "off",
        "off",
    ]
    assert rows[0]["generated_at"] is None and rows[1]["generated_at"]


def test_put_cadence_upserts_and_resets_the_stamp(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    url = f"/v1/brands/{bid}/reports/cmo"
    r = client.put(url, headers=org.headers, json={"cadence": "weekly"})
    assert r.status_code == 200 and r.json()["cadence"] == "weekly"
    with owner() as s, s.begin():
        rep = s.scalars(select(m.Report)).one()
        rep.generated_at = NOW
    # weekly -> monthly keeps the stamp; off -> anything clears it.
    client.put(url, headers=org.headers, json={"cadence": "monthly"})
    with owner() as s:
        assert s.scalars(select(m.Report)).one().generated_at is not None
    client.put(url, headers=org.headers, json={"cadence": "off"})
    with owner() as s, s.begin():
        s.scalars(select(m.Report)).one().generated_at = NOW
    client.put(url, headers=org.headers, json={"cadence": "weekly"})
    with owner() as s:
        assert s.scalars(select(m.Report)).one().generated_at is None
    assert (
        client.put(
            url, headers=org.headers, json={"cadence": "daily"}
        ).status_code
        == 422
    )
    assert (
        client.put(
            f"/v1/brands/{bid}/reports/weekly_digest",
            headers=org.headers,
            json={"cadence": "weekly"},
        ).status_code
        == 422
    )


def test_manual_run_returns_document_and_leaves_the_stamp(
    client, owner, make_org, make_brand
):
    org, bid = _scene(owner, make_org, make_brand)
    r = client.post(f"/v1/brands/{bid}/reports/pr/runs", headers=org.headers)
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["type"] == "pr" and run["source"] == "manual"
    assert run["document"]["title"] == "Nike: PR report"
    assert run["share_token"] and run["methodology_version"] == "1"
    with owner() as s:
        assert s.scalars(select(m.Report)).one().generated_at is None
    assert (
        client.post(
            f"/v1/brands/{bid}/reports/x/runs", headers=org.headers
        ).status_code
        == 422
    )


def test_archive_is_newest_first_without_documents(
    client, owner, make_org, make_brand
):
    org, bid = _scene(owner, make_org, make_brand)
    for t in ("cmo", "seo", "content"):
        client.post(f"/v1/brands/{bid}/reports/{t}/runs", headers=org.headers)
    r = client.get(f"/v1/brands/{bid}/reports/runs", headers=org.headers)
    assert [x["type"] for x in r.json()] == ["content", "seo", "cmo"]
    assert "document" not in r.json()[0]
    two = client.get(
        f"/v1/brands/{bid}/reports/runs?limit=2", headers=org.headers
    )
    assert len(two.json()) == 2
    one = client.get(
        f"/v1/brands/{bid}/reports/runs/{r.json()[2]['id']}",
        headers=org.headers,
    )
    assert one.status_code == 200 and one.json()["document"]["type"] == "cmo"


def test_share_and_revoke(client, owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    run = client.post(
        f"/v1/brands/{bid}/reports/cmo/runs", headers=org.headers
    ).json()
    first = run["share_token"]
    url = f"/v1/brands/{bid}/reports/runs/{run['id']}/share"
    assert client.delete(url, headers=org.headers).status_code == 204
    listed = client.get(
        f"/v1/brands/{bid}/reports/runs", headers=org.headers
    ).json()
    assert listed[0]["share_token"] is None
    again = client.post(url, headers=org.headers)
    assert again.status_code == 200
    assert again.json()["share_token"] not in (None, first)


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"report_logo_url": "https://nike.com/logo.png"}, 200),
        ({"report_logo_url": "http://nike.com/logo.png"}, 422),
        ({"report_accent": "#1A2b3C"}, 200),
        ({"report_accent": "red"}, 422),
        ({"report_prepared_by": "x" * 80}, 200),
        ({"report_prepared_by": "x" * 81}, 422),
        (
            {
                "report_logo_url": None,
                "report_accent": None,
                "report_prepared_by": None,
            },
            200,
        ),
    ],
)
def test_branding_validation(client, make_org, make_brand, body, code):
    org = make_org()
    bid = make_brand(org)
    r = client.patch(f"/v1/brands/{bid}", headers=org.headers, json=body)
    assert r.status_code == code, r.text
    if code == 200:
        for k, v in body.items():
            assert r.json()[k] == v


def _idle_in_transaction() -> int:
    with system_session() as s:
        return s.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = "
                "current_database() AND state LIKE 'idle in transaction%' "
                "AND pid <> pg_backend_pid()"
            )
        ).scalar_one()


def _generic_404(r) -> None:
    """A dead or unknown token gets the bare problem: nothing about the run,
    its brand or its org."""
    assert r.status_code == 404
    body = r.json()
    assert body["title"] == "Not found" and body["detail"] == ""
    assert body["errors"] == []
    assert "nike" not in r.text.lower()


def test_public_page_and_pdf_follow_the_token(
    client, owner, make_org, make_brand
):
    org, bid = _scene(owner, make_org, make_brand)
    run = client.post(
        f"/v1/brands/{bid}/reports/agency/runs", headers=org.headers
    ).json()
    tok = run["share_token"]
    r = client.get(f"/v1/r/{tok}")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json()["document"]["title"] == "Nike visibility report"
    pdf = client.get(f"/v1/r/{tok}.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"].startswith(
        'attachment; filename="nike-agency-'
    )
    assert pdf.content.startswith(b"%PDF-")
    assert _idle_in_transaction() == 0
    client.delete(
        f"/v1/brands/{bid}/reports/runs/{run['id']}/share", headers=org.headers
    )
    _generic_404(client.get(f"/v1/r/{tok}"))
    _generic_404(client.get(f"/v1/r/{tok}.pdf"))
    new = client.post(
        f"/v1/brands/{bid}/reports/runs/{run['id']}/share", headers=org.headers
    ).json()["share_token"]
    assert client.get(f"/v1/r/{new}").status_code == 200
    assert client.get(f"/v1/r/{tok}").status_code == 404
    _generic_404(client.get("/v1/r/unknown-token-unknown-token-x"))
    assert client.get("/v1/r/short").status_code == 422
