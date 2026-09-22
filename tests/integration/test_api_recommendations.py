import threading
import time
import uuid

import pytest
from bsi_core import models as m
from sqlalchemy import select, text


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
    # add_competitor cannot move mention rate: no impact window.
    assert (rec["type"], body["measures_impact"]) == ("add_competitor", False)
    assert client.post(url, headers=org.headers).status_code == 409
    accepted = client.get(
        f"/v1/brands/{bid}/recommendations?status=accepted",
        headers=org.headers,
    ).json()
    assert [r["id"] for r in accepted] == [rec["id"]]


def test_a_crawl_task_measures_no_impact(client, owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host="nike.com"))
        s.add(
            m.SiteAudit(
                org_id=org.id,
                brand_id=bid,
                domain="nike.com",
                checks=[
                    {
                        "code": "llms_missing",
                        "ok": False,
                        "severity": "low",
                        "observed": "HTTP 404",
                        "expected": "e",
                        "url": "https://nike.com/llms.txt",
                    }
                ],
            )
        )
    recs = client.post(
        f"/v1/brands/{bid}/recommendations/generate", headers=org.headers
    ).json()
    rec = next(r for r in recs if r["type"] == "fix_crawlability")
    task = client.post(
        f"/v1/brands/{bid}/recommendations/{rec['id']}/accept",
        headers=org.headers,
    ).json()
    assert task["measures_impact"] is False


@pytest.mark.parametrize(
    ("rtype", "measures"),
    [("sample_more", False), ("create_content", True)],
)
def test_accept_carries_the_evidence_prompts(
    client, owner, make_observation, scene, rtype, measures
):
    org, bid = scene
    oid = make_observation(org, bid)
    with owner() as s, s.begin():
        pid = s.get(m.Observation, oid).prompt_id
        rec = m.Recommendation(
            org_id=org.id,
            brand_id=bid,
            type=rtype,
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
    assert (t["prompt_ids"], t["measures_impact"]) == ([str(pid)], measures)


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


def _wait_until_blocked(holder, deadline=5.0):
    """Poll pg_stat_activity for some *other* backend waiting on a lock,
    so the test cannot pass just because the request happened to arrive
    late. Postgres reports a row-lock wait via wait_event_type='Lock'
    (wait_event='transactionid'); the query text it shows alongside a
    blocked backend is not reliable (it can lag behind the statement
    actually stuck), so filter on the wait state, not the query text.
    """
    my_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar()
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        waiting = holder.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE wait_event_type = 'Lock' AND pid != :pid"
            ),
            {"pid": my_pid},
        ).scalar()
        if waiting:
            return True
        time.sleep(0.05)
    return False


def test_concurrent_accept_returns_409_not_500(client, owner, scene):
    """Two overlapping accepts on the same recommendation: the second
    must see 'accepted' and 409, never race a raw IntegrityError into a
    500 (and never both succeed)."""
    org, bid = scene
    rec = generate(client, org, bid).json()[0]
    rec_id = uuid.UUID(rec["id"])
    url = f"/v1/brands/{bid}/recommendations/{rec['id']}/accept"

    # Hold a row lock on the recommendation from a separate transaction,
    # standing in for a first request that has read the row and not yet
    # committed.
    holder = owner()
    holder.begin()
    locked = holder.execute(
        select(m.Recommendation)
        .where(m.Recommendation.id == rec_id)
        .with_for_update()
    ).scalar_one()

    result: dict[str, object] = {}

    def call_accept() -> None:
        result["response"] = client.post(url, headers=org.headers)

    t = threading.Thread(target=call_accept)
    t.start()
    try:
        assert _wait_until_blocked(holder), (
            "accept request never blocked on the row lock; the test "
            "would pass regardless of whether _open locks the row"
        )
        assert t.is_alive()  # still waiting, not raced ahead

        # Simulate the first accept finishing: flip status, commit, which
        # releases the lock the second request is waiting on.
        locked.status = "accepted"
        holder.commit()

        t.join(timeout=5)
        assert not t.is_alive()
    finally:
        holder.close()

    response = result["response"]
    assert response.status_code == 409, response.text


def test_tied_recommendations_list_in_generate_order(client, owner, scene):
    org, bid = scene
    with owner() as s, s.begin():
        # Ids opposite to subject_key order, so id order cannot pass this.
        for key, n in (("b.com", 1), ("a.com", 2)):
            s.add(
                m.Recommendation(
                    id=uuid.UUID(int=n),
                    org_id=org.id,
                    brand_id=bid,
                    type="pursue_citation_source",
                    subject_key=key,
                    title=key,
                    body="b",
                    reach=0.5,
                    pressure=0.5,
                    feasibility=0.4,
                    priority=0.1,
                )
            )
    got = client.get(f"/v1/brands/{bid}/recommendations", headers=org.headers)
    assert [r["subject_key"] for r in got.json()] == ["a.com", "b.com"]


def test_top_takes_the_best_of_each_type(client, owner, scene):
    org, bid = scene
    rows = [
        ("pursue_citation_source", "a.com", 0.9),
        ("pursue_citation_source", "b.com", 0.8),
        ("pursue_citation_source", "c.com", 0.7),
        ("create_content", "p1", 0.1),
        ("sample_more", "p2", 0.05),
    ]
    with owner() as s, s.begin():
        s.add_all(
            m.Recommendation(
                org_id=org.id,
                brand_id=bid,
                type=t,
                subject_key=key,
                title=key,
                body="b",
                reach=p,
                pressure=1.0,
                feasibility=1.0,
                priority=p,
            )
            for t, key, p in rows
        )
    top = client.get(
        f"/v1/brands/{bid}/recommendations/top", headers=org.headers
    )
    assert top.status_code == 200
    assert [r["subject_key"] for r in top.json()] == ["a.com", "p1", "p2"]
