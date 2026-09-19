import pytest
from bsi_core import models as m
from sqlalchemy import select


@pytest.fixture
def brand(client, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    client.post(
        f"/v1/brands/{bid}/prompts",
        headers=org.headers,
        json=[{"text": "best shoes"}, {"text": "kids shoes"}],
    )
    return org, bid


def test_run_enqueues_prompts_times_samples(client, brand):
    org, bid = brand
    r = client.post(f"/v1/brands/{bid}/runs", headers=org.headers)
    assert r.status_code == 202
    body = r.json()
    assert body["enqueued"] == 6
    job = client.get(body["status_url"], headers=org.headers).json()
    assert (job["total"], job["queued"], job["status"]) == (6, 6, "running")


def test_second_post_in_same_slot_adds_nothing(client, brand):
    org, bid = brand
    first = client.post(f"/v1/brands/{bid}/runs", headers=org.headers).json()
    again = client.post(f"/v1/brands/{bid}/runs", headers=org.headers).json()
    assert again["job_id"] == first["job_id"]
    assert again["enqueued"] == 0


def test_new_prompt_joins_the_same_slot(client, brand):
    org, bid = brand
    client.post(f"/v1/brands/{bid}/runs", headers=org.headers)
    client.post(
        f"/v1/brands/{bid}/prompts", headers=org.headers, json={"text": "new"}
    )
    r = client.post(f"/v1/brands/{bid}/runs", headers=org.headers).json()
    assert r["enqueued"] == 3
    job = client.get(r["status_url"], headers=org.headers).json()
    assert job["total"] == 9


def test_samples_and_paused_prompts(client, brand):
    org, bid = brand
    prompts = client.get(f"/v1/brands/{bid}/prompts", headers=org.headers)
    pid = prompts.json()[0]["id"]
    client.patch(
        f"/v1/brands/{bid}/prompts/{pid}",
        headers=org.headers,
        json={"status": "paused"},
    )
    r = client.post(
        f"/v1/brands/{bid}/runs", headers=org.headers, json={"samples": 5}
    )
    assert r.json()["enqueued"] == 5
    bad = client.post(
        f"/v1/brands/{bid}/runs", headers=org.headers, json={"samples": 11}
    )
    assert bad.status_code == 422


def test_no_active_prompts_is_422(client, make_org, make_brand):
    org = make_org()
    r = client.post(f"/v1/brands/{make_brand(org)}/runs", headers=org.headers)
    assert r.status_code == 422


def test_retry_failed_requeues_failed_observations(client, brand, owner):
    org, bid = brand
    body = client.post(f"/v1/brands/{bid}/runs", headers=org.headers).json()
    job_id = body["job_id"]

    with owner() as s, s.begin():
        obs = s.scalars(
            select(m.Observation).where(m.Observation.job_id == job_id)
        ).first()
        obs.status = "failed"
        obs.attempts = 3
        obs_id = obs.id

    r = client.post(
        f"/v1/brands/{bid}/runs",
        headers=org.headers,
        json={"retry_failed": True},
    )
    assert r.status_code == 202
    result = r.json()
    assert result["requeued"] == 1
    assert result["enqueued"] == 0

    with owner() as s:
        refreshed = s.get(m.Observation, obs_id)
        assert refreshed.status == "queued"
        assert refreshed.attempts == 0

    again = client.post(f"/v1/brands/{bid}/runs", headers=org.headers).json()
    assert again["requeued"] == 0


def test_list_runs(client, brand):
    org, bid = brand
    jid = client.post(f"/v1/brands/{bid}/runs", headers=org.headers).json()[
        "job_id"
    ]
    runs = client.get(f"/v1/brands/{bid}/runs", headers=org.headers).json()
    assert [r["id"] for r in runs] == [jid]
