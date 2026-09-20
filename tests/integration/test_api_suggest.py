"""Task 7: suggestion endpoints, prompt states, plan limits, clusters."""

import uuid
from datetime import UTC, datetime

import pytest
from bsi_core import models as m
from bsi_core.scheduling import hour_slot
from sqlalchemy import select


@pytest.fixture
def brand(client, make_org, make_brand):
    org = make_org()
    return org, make_brand(org)


def _seed_prompts(owner, org, brand_id, rows):
    """rows: list of dicts of Prompt overrides."""
    with owner() as s, s.begin():
        locale = s.scalars(
            select(m.Locale).where(m.Locale.brand_id == brand_id)
        ).one()
        s.add_all(
            [
                m.Prompt(
                    org_id=org.id,
                    brand_id=brand_id,
                    locale_id=locale.id,
                    **row,
                )
                for row in rows
            ]
        )


def _job(owner, brand_id):
    with owner() as s:
        return s.scalars(select(m.Job).where(m.Job.brand_id == brand_id)).one()


def test_suggest_prompts_queues_one_job_per_hour(client, brand, owner):
    org, bid = brand
    r = client.post(
        f"/v1/brands/{bid}/prompts/suggest",
        headers=org.headers,
        json={"count": 20},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status_url"] == f"/v1/jobs/{body['job_id']}"
    job = _job(owner, bid)
    assert (job.kind, job.status, job.params) == (
        "suggest_prompts",
        "queued",
        {"count": 20},
    )
    assert job.scheduled_slot == hour_slot(datetime.now(UTC))

    again = client.post(
        f"/v1/brands/{bid}/prompts/suggest", headers=org.headers, json={}
    )
    assert again.json()["job_id"] == body["job_id"]


def test_suggest_competitors_queues_its_own_job(client, brand, owner):
    org, bid = brand
    r = client.post(
        f"/v1/brands/{bid}/competitors/suggest", headers=org.headers
    )
    assert r.status_code == 202, r.text
    job = _job(owner, bid)
    assert (job.kind, job.status) == ("suggest_competitors", "queued")
    assert r.json()["job_id"] == str(job.id)


@pytest.mark.parametrize("body", [{"count": -1}, {"count": 101}, {"n": 1}])
def test_suggest_prompts_rejects_a_bad_count(client, brand, body):
    org, bid = brand
    r = client.post(
        f"/v1/brands/{bid}/prompts/suggest", headers=org.headers, json=body
    )
    assert r.status_code == 422, r.text


def test_a_failed_job_is_requeued_keeping_its_spend(client, brand, owner):
    org, bid = brand
    first = client.post(
        f"/v1/brands/{bid}/prompts/suggest", headers=org.headers, json={}
    ).json()
    with owner() as s, s.begin():
        job = s.get(m.Job, uuid.UUID(first["job_id"]))
        job.status, job.error, job.cost_micros = "failed", "boom", 7_000

    again = client.post(
        f"/v1/brands/{bid}/prompts/suggest", headers=org.headers, json={}
    )
    assert again.status_code == 202
    assert again.json()["job_id"] == first["job_id"]
    job = _job(owner, bid)
    assert (job.status, job.error, job.cost_micros) == ("queued", None, 7_000)


def test_a_requeue_honours_the_new_count(client, brand, owner):
    # Retrying with a different count must not silently run the old one.
    org, bid = brand
    url = f"/v1/brands/{bid}/prompts/suggest"
    client.post(url, headers=org.headers, json={"count": 50})
    with owner() as s, s.begin():
        s.get(m.Job, _job(owner, bid).id).status = "failed"

    client.post(url, headers=org.headers, json={"count": 20})

    assert _job(owner, bid).params["count"] == 20


def test_a_running_job_is_not_disturbed(client, brand, owner):
    org, bid = brand
    first = client.post(
        f"/v1/brands/{bid}/prompts/suggest", headers=org.headers, json={}
    ).json()
    with owner() as s, s.begin():
        s.get(m.Job, uuid.UUID(first["job_id"])).status = "running"
    again = client.post(
        f"/v1/brands/{bid}/prompts/suggest", headers=org.headers, json={}
    )
    assert again.json()["job_id"] == first["job_id"]
    assert _job(owner, bid).status == "running"


def test_archived_brand_cannot_be_suggested_for(client, brand):
    org, bid = brand
    client.delete(f"/v1/brands/{bid}", headers=org.headers)
    for path in ("prompts/suggest", "competitors/suggest"):
        r = client.post(f"/v1/brands/{bid}/{path}", headers=org.headers)
        assert r.status_code == 409, (path, r.text)


def test_job_view_branches_on_kind(client, brand):
    org, bid = brand
    client.post(
        f"/v1/brands/{bid}/prompts", headers=org.headers, json={"text": "a"}
    )
    run = client.post(f"/v1/brands/{bid}/runs", headers=org.headers).json()
    sug = client.post(
        f"/v1/brands/{bid}/prompts/suggest", headers=org.headers, json={}
    ).json()

    view = client.get(sug["status_url"], headers=org.headers).json()
    assert view == {
        "id": sug["job_id"],
        "brand_id": str(bid),
        "kind": "suggest_prompts",
        "status": "queued",
        "error": None,
        "cost_micros": 0,
    }
    # The run list is runs only.
    runs = client.get(f"/v1/brands/{bid}/runs", headers=org.headers).json()
    assert [r["id"] for r in runs] == [run["job_id"]]


def test_prompt_view_and_filters(client, brand, owner):
    org, bid = brand
    _seed_prompts(
        owner,
        org,
        bid,
        [
            {"text": "a", "intent": "comparison", "topic": "running"},
            {"text": "b", "intent": "geographic", "status": "suggested"},
        ],
    )
    base = f"/v1/brands/{bid}/prompts"
    rows = client.get(base, headers=org.headers).json()
    assert {(r["intent"], r["topic"]) for r in rows} == {
        ("comparison", "running"),
        ("geographic", None),
    }
    got = client.get(f"{base}?status=suggested", headers=org.headers).json()
    assert [r["text"] for r in got] == ["b"]
    got = client.get(f"{base}?intent=comparison", headers=org.headers).json()
    assert [r["text"] for r in got] == ["a"]


def test_patch_accepts_all_four_statuses(client, brand, owner):
    org, bid = brand
    _seed_prompts(owner, org, bid, [{"text": "a", "status": "suggested"}])
    base = f"/v1/brands/{bid}/prompts"
    pid = client.get(base, headers=org.headers).json()[0]["id"]
    for status in ("active", "paused", "archived", "suggested"):
        r = client.patch(
            f"{base}/{pid}", headers=org.headers, json={"status": status}
        )
        assert r.status_code == 200 and r.json()["status"] == status


def test_bulk_patch_activates(client, brand, owner):
    org, bid = brand
    _seed_prompts(
        owner,
        org,
        bid,
        [{"text": t, "status": "suggested"} for t in ("a", "b", "c")],
    )
    base = f"/v1/brands/{bid}/prompts"
    ids = [p["id"] for p in client.get(base, headers=org.headers).json()]
    r = client.patch(
        base, headers=org.headers, json={"ids": ids[:2], "status": "active"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 2
    got = client.get(f"{base}?status=active", headers=org.headers).json()
    assert {p["id"] for p in got} == set(ids[:2])


def test_bulk_patch_rejects_a_foreign_id(client, make_org, make_brand, owner):
    org = make_org()
    mine, other = make_brand(org, "Mine"), make_brand(org, "Other")
    _seed_prompts(owner, org, mine, [{"text": "a"}])
    _seed_prompts(owner, org, other, [{"text": "b"}])
    ids = {
        b: [
            p["id"]
            for p in client.get(
                f"/v1/brands/{b}/prompts", headers=org.headers
            ).json()
        ]
        for b in (mine, other)
    }
    r = client.patch(
        f"/v1/brands/{mine}/prompts",
        headers=org.headers,
        json={"ids": ids[mine] + ids[other], "status": "paused"},
    )
    assert r.status_code == 404, r.text
    # The matching row must not have moved.
    got = client.get(f"/v1/brands/{mine}/prompts", headers=org.headers).json()
    assert got[0]["status"] == "active"


def test_plan_limit_refuses_at_the_boundary(client, brand, owner):
    org, bid = brand
    base = f"/v1/brands/{bid}/prompts"
    r = client.post(
        base,
        headers=org.headers,
        json=[{"text": f"p {i}"} for i in range(100)],
    )
    assert r.status_code == 201, r.text
    r = client.post(base, headers=org.headers, json={"text": "one too many"})
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "100 + 1 > 100"


def test_plan_limit_counts_the_whole_org(client, make_org, make_brand, owner):
    org = make_org()
    a, b = make_brand(org, "A"), make_brand(org, "B")
    _seed_prompts(owner, org, a, [{"text": f"p {i}"} for i in range(100)])
    r = client.post(
        f"/v1/brands/{b}/prompts", headers=org.headers, json={"text": "x"}
    )
    assert r.status_code == 409, r.text


def test_plan_limit_applies_to_activation(client, brand, owner):
    org, bid = brand
    _seed_prompts(owner, org, bid, [{"text": f"p {i}"} for i in range(100)])
    _seed_prompts(owner, org, bid, [{"text": "s", "status": "suggested"}])
    base = f"/v1/brands/{bid}/prompts"
    sid = client.get(f"{base}?status=suggested", headers=org.headers).json()[0][
        "id"
    ]
    single = client.patch(
        f"{base}/{sid}", headers=org.headers, json={"status": "active"}
    )
    assert single.status_code == 409, single.text
    bulk = client.patch(
        base, headers=org.headers, json={"ids": [sid], "status": "active"}
    )
    assert bulk.status_code == 409, bulk.text
    # Pausing is never refused.
    assert (
        client.patch(
            base, headers=org.headers, json={"ids": [sid], "status": "paused"}
        ).status_code
        == 200
    )


def test_plan_limit_follows_the_plan(client, make_org, make_brand, owner):
    org = make_org()
    bid = make_brand(org)
    with owner() as s, s.begin():
        s.get(m.Organization, org.id).plan = "pro"
    _seed_prompts(owner, org, bid, [{"text": f"p {i}"} for i in range(100)])
    r = client.post(
        f"/v1/brands/{bid}/prompts", headers=org.headers, json={"text": "x"}
    )
    assert r.status_code == 201, r.text


def test_clusters_group_and_order(client, brand, owner):
    org, bid = brand
    _seed_prompts(
        owner,
        org,
        bid,
        [
            {"text": "a", "intent": "comparison", "topic": "running"},
            {"text": "b", "intent": "comparison", "topic": "running"},
            {
                "text": "c",
                "intent": "comparison",
                "topic": "running",
                "status": "paused",
            },
            {
                "text": "d",
                "intent": "geographic",
                "topic": "delhi",
                "status": "suggested",
            },
            {"text": "e"},  # never labelled: intent and topic are NULL
        ],
    )
    got = client.get(f"/v1/brands/{bid}/clusters", headers=org.headers).json()
    assert got == [
        {
            "intent": "comparison",
            "topic": "running",
            "active": 2,
            "suggested": 0,
            "paused": 1,
        },
        {
            "intent": None,
            "topic": None,
            "active": 1,
            "suggested": 0,
            "paused": 0,
        },
        {
            "intent": "geographic",
            "topic": "delhi",
            "active": 0,
            "suggested": 1,
            "paused": 0,
        },
    ]


def test_competitor_status_evidence_and_confirm(client, brand, owner):
    org, bid = brand
    with owner() as s, s.begin():
        s.add(
            m.Competitor(
                org_id=org.id,
                brand_id=bid,
                name="Rival",
                status="suggested",
                evidence=2,
            )
        )
    base = f"/v1/brands/{bid}/competitors"
    client.post(base, headers=org.headers, json={"name": "Known"})
    rows = client.get(base, headers=org.headers).json()
    assert {(c["name"], c["status"], c["evidence"]) for c in rows} == {
        ("Rival", "suggested", 2),
        ("Known", "active", None),
    }
    suggested = client.get(
        f"{base}?status=suggested", headers=org.headers
    ).json()
    assert [c["name"] for c in suggested] == ["Rival"]
    r = client.patch(
        f"{base}/{suggested[0]['id']}",
        headers=org.headers,
        json={"status": "active"},
    )
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert (
        client.get(f"{base}?status=suggested", headers=org.headers).json() == []
    )


def test_competitor_cannot_be_patched_back_to_suggested(client, brand):
    org, bid = brand
    cid = client.post(
        f"/v1/brands/{bid}/competitors", headers=org.headers, json={"name": "R"}
    ).json()["id"]
    r = client.patch(
        f"/v1/brands/{bid}/competitors/{cid}",
        headers=org.headers,
        json={"status": "suggested"},
    )
    assert r.status_code == 422, r.text


def test_length_caps(client, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    long = "x" * 201
    cases = [
        ("POST", "/v1/brands", {"name": "A", "category": long}),
        ("POST", "/v1/brands", {"name": "A", "aliases": [long]}),
        (
            "POST",
            f"/v1/brands/{bid}/competitors",
            {"name": "R", "aliases": [long]},
        ),
        (
            "POST",
            f"/v1/brands/{bid}/competitors",
            {"name": "R", "domains": [long]},
        ),
    ]
    for method, path, body in cases:
        r = client.request(method, path, headers=org.headers, json=body)
        assert r.status_code == 422, (path, body, r.text)


def test_clusters_ignore_archived_prompts(client, brand, owner):
    # An all-archived group would otherwise render as a phantom 0/0/0 row
    # and the counts would not sum to the prompts on show.
    org, bid = brand
    _seed_prompts(
        owner,
        org,
        bid,
        [
            {
                "text": "gone",
                "intent": "commercial",
                "topic": "old",
                "status": "archived",
            },
            {
                "text": "here",
                "intent": "commercial",
                "topic": "kept",
                "status": "active",
            },
        ],
    )

    rows = client.get(f"/v1/brands/{bid}/clusters", headers=org.headers).json()

    assert [(r["topic"], r["active"]) for r in rows] == [("kept", 1)]


def test_activating_nothing_is_allowed_over_the_limit(client, brand, owner):
    # A downgraded org is over its limit; re-activating rows that are
    # already active adds nothing, so it must not be refused.
    org, bid = brand
    _seed_prompts(
        owner,
        org,
        bid,
        [{"text": f"p{i}", "status": "active"} for i in range(101)],
    )
    with owner() as s:
        ids = [
            str(pid)
            for pid in s.scalars(
                select(m.Prompt.id).where(m.Prompt.brand_id == bid).limit(2)
            )
        ]

    r = client.patch(
        f"/v1/brands/{bid}/prompts",
        headers=org.headers,
        json={"ids": ids, "status": "active"},
    )

    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 2
