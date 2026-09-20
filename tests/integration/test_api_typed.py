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


def test_prompt_metrics_projects_what_it_would_take_to_separate(
    client, owner, make_org, make_brand, make_observation
):
    from bsi_core import models as m

    org = make_org()
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        comp = m.Competitor(org_id=org.id, brand_id=bid, name="Adidas")
        s.add(comp)
        s.flush()
        cid = comp.id
    first = make_observation(org, bid, status="done", text="p")
    with owner() as s:
        pid = s.get(m.Observation, first).prompt_id
    ids = [first] + [
        make_observation(org, bid, status="done", prompt_id=pid, sample_index=i)
        for i in (1, 2)
    ]
    # Brand in 2 of 3 answers, rival in 1 — a gap too small to call at n=3.
    with owner() as s, s.begin():
        for oid, eid, etype in (
            (ids[0], bid, "brand"),
            (ids[1], bid, "brand"),
            (ids[0], cid, "competitor"),
        ):
            s.add(
                m.Mention(
                    org_id=org.id,
                    observation_id=oid,
                    entity_type=etype,
                    entity_id=eid,
                    position=1,
                    rec_status="mentioned",
                    sentiment="neutral",
                )
            )
    url = f"/v1/brands/{bid}/prompts/metrics"
    (row,) = client.get(url, headers=org.headers).json()
    assert (row["n"], row["separated"]) == (3, False)
    assert row["needs_samples"] == 31
    assert row["needs_days"] is None  # no schedule yet

    client.put(
        f"/v1/brands/{bid}/schedule",
        json={"cadence": "daily", "hour_utc": 3, "samples": 3},
        headers=org.headers,
    )
    (row,) = client.get(url, headers=org.headers).json()
    assert row["needs_days"] == 10  # 28 more samples at 3/day
