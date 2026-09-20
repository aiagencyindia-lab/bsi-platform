import json
from pathlib import Path

import pytest
from bsi_core import models as m

RAW = json.loads(Path("tests/fixtures/gemini_min.json").read_text())


@pytest.fixture
def labelled_scene(owner, make_org, make_brand, make_observation):
    org = make_org()
    bid = make_brand(org, "Nike")
    oid = make_observation(org, bid, raw=RAW, status="done")
    with owner() as s, s.begin():
        s.add(
            m.Mention(
                org_id=org.id,
                observation_id=oid,
                entity_type="brand",
                entity_id=bid,
                position=1,
                rec_status="recommended",
                sentiment="positive",
                evidence_sentence="Nike is best.",
            )
        )
    return org, bid, oid


def test_queue_hides_the_verdict_then_put_reveals_it(client, labelled_scene):
    org, bid, oid = labelled_scene
    queue = client.get(
        f"/v1/brands/{bid}/labels/next", headers=org.headers
    ).json()
    item = queue["item"]
    assert (item["observation_id"], item["entity_name"]) == (str(oid), "Nike")
    assert item["evidence_sentence"] == "Nike is best." and item["text"]
    assert "rec_status" not in item and "judge" not in item
    assert (queue["labelled"], queue["remaining"]) == (0, 1)

    url = f"/v1/observations/{oid}/labels/{bid}"
    put = client.put(url, json={"label": "listed"}, headers=org.headers)
    assert put.json() == {
        "label": "listed",
        "judge": "recommended",
        "agrees": False,
    }
    again = client.put(url, json={"label": "recommended"}, headers=org.headers)
    assert again.json()["agrees"] is True  # relabelling overwrites

    queue = client.get(
        f"/v1/brands/{bid}/labels/next", headers=org.headers
    ).json()
    assert queue["item"] is None
    assert (queue["labelled"], queue["remaining"]) == (1, 0)
    assert (queue["agreement"]["value"], queue["agreement"]["n"]) == (1.0, 1)


def test_labels_reject_bad_input_and_other_tenants(
    client, make_org, labelled_scene
):
    org, bid, oid = labelled_scene
    url = f"/v1/observations/{oid}/labels/{bid}"
    bad = client.put(url, json={"label": "brilliant"}, headers=org.headers)
    assert bad.status_code == 422
    missing = client.put(
        f"/v1/observations/{oid}/labels/{oid}",
        json={"label": "listed"},
        headers=org.headers,
    )
    assert missing.status_code == 404  # no such mention
    other = make_org("B")
    assert (
        client.put(url, json={"label": "listed"}, headers=other.headers)
    ).status_code == 404
    assert (
        client.get(f"/v1/brands/{bid}/labels/next", headers=other.headers)
    ).status_code == 404


def test_label_vocabulary_matches_the_model():
    from typing import get_args

    from bsi_api.routers.labels import RecStatus

    assert get_args(RecStatus) == m.REC_STATUSES
