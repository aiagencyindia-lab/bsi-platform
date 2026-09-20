from bsi_core import models as m
from sqlalchemy import update


def test_ops_reports_spend_queue_failures_and_search_rate(
    client, owner, make_org, make_brand, make_observation
):
    a, b = make_org("A"), make_org("B")
    bid = make_brand(a)
    searched = make_observation(a, bid, status="done")
    plain = make_observation(a, bid, status="done", text="p2")
    failed = make_observation(a, bid, status="failed", text="p3")
    make_observation(a, bid, status="queued", text="p4")
    make_observation(b, make_brand(b), status="queued")
    with owner() as s, s.begin():
        for oid, values in (
            (searched, {"cost_micros": 46_000, "search_queries": 2}),
            (plain, {"cost_micros": 13_000, "search_queries": 0}),
            (failed, {"error": "400 bad"}),
        ):
            s.execute(
                update(m.Observation)
                .where(m.Observation.id == oid)
                .values(**values)
            )
        s.add(
            m.Job(
                org_id=a.id,
                brand_id=bid,
                kind="prompts",
                cost_micros=1_000,
                scheduled_slot=s.get(m.Observation, searched).scheduled_slot,
            )
        )
    body = client.get("/v1/ops", headers=a.headers).json()
    assert body["spent_micros"] == 60_000  # 46k + 13k + the non-run job
    assert body["pending"] == 1
    assert body["budget_micros"] == 2_000_000
    assert body["queue"] == {"done": 2, "failed": 1, "queued": 1}
    assert (body["searched"]["value"], body["searched"]["n"]) == (0.5, 2)
    assert [f["error"] for f in body["failures"]] == ["400 bad"]
    assert body["schedules"] == []


def test_ops_is_scoped_to_the_caller(client, make_org):
    body = client.get("/v1/ops", headers=make_org().headers).json()
    assert body["spent_micros"] == 0 and body["queue"] == {}
    assert client.get("/v1/ops").status_code == 401
