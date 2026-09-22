from tests.integration.test_citations import cited  # noqa: F401
from tests.integration.test_recommend import world  # noqa: F401


def test_citations_endpoint_lists_domains(client, cited):  # noqa: F811
    r = client.get(
        f"/v1/brands/{cited.brand}/citations", headers=cited.org.headers
    )
    assert r.status_code == 200, r.text
    rows = {x["domain"]: x for x in r.json()}
    forbes = rows["forbes.com"]
    assert forbes["gap"] is True
    assert forbes["owner"] == "third_party"
    assert forbes["rivals"][0] == {"name": "Adidas", "answers": 5}
    assert len(forbes["observation_ids"]) == 5
    assert forbes["first_seen"] and forbes["last_seen"]


def test_citations_endpoint_honours_filters(client, cited):  # noqa: F811
    r = client.get(
        f"/v1/brands/{cited.brand}/citations?prompt_ids={cited.present}",
        headers=cited.org.headers,
    )
    assert {x["domain"] for x in r.json()} == {
        "blog.com",
        "forbes.com",
        "adidas.co.in",
    }


def test_unknown_brand_is_404(client, make_org):
    org = make_org()
    r = client.get(
        "/v1/brands/00000000-0000-0000-0000-000000000000/citations",
        headers=org.headers,
    )
    assert r.status_code == 404
