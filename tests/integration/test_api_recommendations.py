import pytest
from bsi_core import models as m


@pytest.fixture
def scene(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        s.add(
            m.Competitor(
                org_id=org.id,
                brand_id=bid,
                name="Puma",
                status="suggested",
                evidence=3,
            )
        )
    return org, bid


def generate(client, org, bid):
    return client.post(
        f"/v1/brands/{bid}/recommendations/generate", headers=org.headers
    )


def test_generate_stores_and_lists_open_recommendations(client, scene):
    org, bid = scene
    r = generate(client, org, bid)
    assert r.status_code == 200
    (rec,) = r.json()
    assert (rec["type"], rec["status"]) == ("add_competitor", "open")
    assert rec["priority"] == pytest.approx(
        rec["reach"] * rec["pressure"] * rec["feasibility"], abs=1e-4
    )
    listed = client.get(
        f"/v1/brands/{bid}/recommendations", headers=org.headers
    )
    assert listed.json() == r.json()


def test_accept_creates_exactly_one_task(client, scene):
    org, bid = scene
    rec = generate(client, org, bid).json()[0]
    url = f"/v1/brands/{bid}/recommendations/{rec['id']}/accept"
    t = client.post(url, headers=org.headers)
    assert t.status_code == 201
    body = t.json()
    assert (body["title"], body["status"], body["recommendation_id"]) == (
        rec["title"],
        "open",
        rec["id"],
    )
    assert client.post(url, headers=org.headers).status_code == 409
    accepted = client.get(
        f"/v1/brands/{bid}/recommendations?status=accepted",
        headers=org.headers,
    ).json()
    assert [r["id"] for r in accepted] == [rec["id"]]


def test_accept_carries_the_evidence_prompts(
    client, owner, make_observation, scene
):
    org, bid = scene
    oid = make_observation(org, bid)
    with owner() as s, s.begin():
        pid = s.get(m.Observation, oid).prompt_id
        rec = m.Recommendation(
            org_id=org.id,
            brand_id=bid,
            type="sample_more",
            subject_key=str(pid),
            title="t",
            body="b",
            evidence={"prompt_ids": [str(pid)]},
            reach=0.1,
            pressure=0.1,
            feasibility=1.0,
            priority=0.01,
        )
        s.add(rec)
        s.flush()
        rid = rec.id
    t = client.post(
        f"/v1/brands/{bid}/recommendations/{rid}/accept", headers=org.headers
    ).json()
    assert t["prompt_ids"] == [str(pid)]


def test_dismissing_needs_a_reason_and_sticks(client, scene):
    org, bid = scene
    rec = generate(client, org, bid).json()[0]
    url = f"/v1/brands/{bid}/recommendations/{rec['id']}/dismiss"
    assert client.post(url, json={}, headers=org.headers).status_code == 422
    blank = client.post(url, json={"reason": "   "}, headers=org.headers)
    assert blank.status_code == 422
    ok = client.post(
        url, json={"reason": "tracked elsewhere"}, headers=org.headers
    ).json()
    assert (ok["status"], ok["dismiss_reason"]) == (
        "dismissed",
        "tracked elsewhere",
    )
    assert generate(client, org, bid).json() == []  # not resurrected


def test_task_status_rules(client, scene):
    org, bid = scene
    rec = generate(client, org, bid).json()[0]
    task = client.post(
        f"/v1/brands/{bid}/recommendations/{rec['id']}/accept",
        headers=org.headers,
    ).json()
    url = f"/v1/brands/{bid}/tasks/{task['id']}"

    def patch(body):
        return client.patch(url, json=body, headers=org.headers)

    assert patch({"status": "in_progress"}).json()["status"] == "in_progress"
    assert patch({"status": "in_progress"}).status_code == 200  # no-op
    done = patch({"status": "done"}).json()
    assert done["done_at"] and done["window_days"] == 14
    assert patch({"status": "open"}).status_code == 422
    assert patch({"status": "impact_measured"}).status_code == 422
    assert patch({"notes": "shipped the page"}).json()["notes"] == (
        "shipped the page"
    )
    assert patch({"title": None}).status_code == 422
    assert patch({"owner": "Asha"}).json()["owner"] == "Asha"
    assert patch({"owner": None}).json()["owner"] is None
    listed = client.get(f"/v1/brands/{bid}/tasks", headers=org.headers)
    assert [t["id"] for t in listed.json()] == [task["id"]]
