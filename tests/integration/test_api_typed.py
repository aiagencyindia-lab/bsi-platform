import json
from pathlib import Path

import pytest
from bsi_core.providers.gemini import GeminiGroundingAdapter

RAW = json.loads(Path("tests/fixtures/gemini_min.json").read_text())


@pytest.mark.parametrize(
    "path",
    [
        "/v1/brands/{brand_id}/metrics",
        "/v1/brands/{brand_id}/sov",
        "/v1/brands/{brand_id}/deltas",
        "/v1/observations/{observation_id}",
    ],
)
def test_dashboard_responses_are_typed(client, path):
    spec = client.get("/openapi.json").json()
    ok = spec["paths"][path]["get"]["responses"]["200"]
    assert "$ref" in ok["content"]["application/json"]["schema"]


def test_deltas_keep_the_from_key(client, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    body = client.get(f"/v1/brands/{bid}/deltas", headers=org.headers).json()
    assert {"from", "to"} <= set(body["before"])
    assert body["before"]["recommendation_rate"]["experimental"] is True


def test_observation_detail_carries_the_answer_text(
    client, make_org, make_brand, make_observation
):
    org = make_org()
    oid = make_observation(org, make_brand(org), raw=RAW, status="done")
    body = client.get(f"/v1/observations/{oid}", headers=org.headers).json()
    assert body["text"] == GeminiGroundingAdapter().parse(RAW).text
    assert body["text"]


def test_observation_without_a_payload_has_no_text(
    client, make_org, make_brand, make_observation
):
    org = make_org()
    oid = make_observation(org, make_brand(org), status="queued")
    body = client.get(f"/v1/observations/{oid}", headers=org.headers).json()
    assert body["text"] is None and body["extraction"] is None


def test_prompt_metrics_endpoint(
    client, make_org, make_brand, make_observation
):
    a, b = make_org("A"), make_org("B")
    bid = make_brand(a)
    make_observation(a, bid, status="done")
    url = f"/v1/brands/{bid}/prompts/metrics"
    (row,) = client.get(url, headers=a.headers).json()
    assert row["n"] == 1 and row["brand"]["value"] == 0.0
    assert client.get(url, headers=b.headers).status_code == 404
