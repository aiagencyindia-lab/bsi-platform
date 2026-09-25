import uuid
from datetime import UTC, datetime

import pytest
from bsi_core import models as m
from sqlalchemy import func, select


@pytest.fixture
def other(owner, make_org, make_brand, make_observation):
    """Org B with one of everything; returns ids."""
    b = make_org("B")
    bid = make_brand(b, "Secret")
    with owner() as s, s.begin():
        # Suggested, so the confirm case below can be caught leaking:
        # an already-active competitor could not show the difference.
        comp = m.Competitor(
            org_id=b.id, brand_id=bid, name="Rival", status="suggested"
        )
        dom = m.Domain(org_id=b.id, brand_id=bid, host="secret.com")
        sch = m.Schedule(
            org_id=b.id,
            brand_id=bid,
            cadence="daily",
            hour_utc=6,
            next_run_at=func.now(),
        )
        job = m.Job(
            org_id=b.id,
            brand_id=bid,
            kind="suggest_prompts",
            # An old slot, so a leaked suggest would have to create a
            # new row rather than collide with this one and vanish.
            scheduled_slot=datetime(2024, 1, 1, tzinfo=UTC),
            status="done",
        )
        s.add_all([comp, dom, sch, job])
        s.flush()
        cid, did, j2 = comp.id, dom.id, job.id
    oid = make_observation(b, bid, raw={"secret": True}, status="done")
    with owner() as s, s.begin():
        # A real mention, so PUT .../labels/{e} has something for org B
        # itself to find; only then does a 404 for org A prove RLS is
        # doing the blocking, rather than the row simply not existing.
        s.add(
            m.Mention(
                org_id=b.id,
                observation_id=oid,
                entity_type="brand",
                entity_id=bid,
                position=1,
                rec_status="listed",
                sentiment="neutral",
                evidence_sentence="Secret is fine.",
            )
        )
    with owner() as s:
        obs = s.get(m.Observation, oid)
        pid, jid = obs.prompt_id, obs.job_id
    with owner() as s, s.begin():
        rec = m.Recommendation(
            org_id=b.id,
            brand_id=bid,
            type="sample_more",
            subject_key="k",
            title="Secret",
            body="Secret",
            reach=0.1,
            pressure=0.1,
            feasibility=1.0,
            priority=0.01,
        )
        s.add(rec)
        s.flush()
        task = m.Task(
            org_id=b.id, brand_id=bid, recommendation_id=rec.id, title="Secret"
        )
        s.add(task)
        audit = m.PageAudit(
            org_id=b.id,
            brand_id=bid,
            url="https://secret.com/p",
            cluster_key="cluster:guide:Secret",
            status=200,
            weights_version="v1",
            score=1,
            error="Secret",
        )
        s.add(audit)
        alert = m.Alert(
            org_id=b.id,
            brand_id=bid,
            type="new_source",
            subject_key="secret.com",
            title="Secret",
            window_from=datetime.now(UTC),
            window_to=datetime.now(UTC),
        )
        s.add(alert)
        rep = m.Report(org_id=b.id, brand_id=bid, type="cmo")
        s.add(rep)
        s.flush()
        run = m.ReportRun(
            org_id=b.id,
            brand_id=bid,
            report_id=rep.id,
            type="cmo",
            source="manual",
            period_from=datetime.now(UTC),
            period_to=datetime.now(UTC),
            compare_from=datetime.now(UTC),
            document={"title": "Secret"},
            methodology_version="1",
            share_token="Secret-token-Secret-token-Secret",
        )
        s.add(run)
        s.flush()
        rid, tid, aid, rrid = rec.id, task.id, audit.id, run.id
    return {
        "b": bid,
        "c": cid,
        "d": did,
        "o": oid,
        "p": pid,
        "j": jid,
        "j2": j2,
        "e": bid,
        "r": rid,
        "t": tid,
        "a": aid,
        "rr": rrid,
    }


CASES = [
    ("GET", "/v1/brands/{b}", None),
    ("PATCH", "/v1/brands/{b}", {"name": "x"}),
    ("DELETE", "/v1/brands/{b}", None),
    ("GET", "/v1/brands/{b}/competitors", None),
    ("POST", "/v1/brands/{b}/competitors", {"name": "x"}),
    ("GET", "/v1/brands/{b}/competitors/metrics", None),
    ("GET", "/v1/brands/{b}/competitors/deltas", None),
    ("GET", "/v1/brands/{b}/competitors/changes", None),
    ("POST", "/v1/brands/{b}/competitors/crawl", None),
    ("GET", "/v1/brands/{b}/competitors/site-changes", None),
    ("PATCH", "/v1/brands/{b}/competitors/{c}", {"name": "x"}),
    ("DELETE", "/v1/brands/{b}/competitors/{c}", None),
    ("GET", "/v1/brands/{b}/domains", None),
    ("POST", "/v1/brands/{b}/domains", {"host": "x.com"}),
    ("DELETE", "/v1/brands/{b}/domains/{d}", None),
    ("GET", "/v1/brands/{b}/prompts", None),
    ("POST", "/v1/brands/{b}/prompts", {"text": "x"}),
    ("PATCH", "/v1/brands/{b}/prompts/{p}", {"status": "paused"}),
    ("GET", "/v1/brands/{b}/runs", None),
    ("POST", "/v1/brands/{b}/runs", None),
    ("GET", "/v1/jobs/{j}", None),
    ("GET", "/v1/observations/{o}", None),
    ("GET", "/v1/observations/{o}/raw", None),
    ("GET", "/v1/brands/{b}/metrics", None),
    ("GET", "/v1/brands/{b}/sov", None),
    ("GET", "/v1/brands/{b}/deltas", None),
    ("GET", "/v1/brands/{b}/schedule", None),
    ("PUT", "/v1/brands/{b}/schedule", {"cadence": "weekly", "hour_utc": 1}),
    ("DELETE", "/v1/brands/{b}/schedule", None),
    ("POST", "/v1/brands/{b}/prompts/suggest", {}),
    ("POST", "/v1/brands/{b}/competitors/suggest", None),
    # BulkPatch.ids has min_length=1, so an empty list would be a 422
    # and never reach the tenancy check; _fill puts org B's prompt in.
    ("PATCH", "/v1/brands/{b}/prompts", {"ids": [], "status": "paused"}),
    ("GET", "/v1/brands/{b}/clusters", None),
    ("GET", "/v1/jobs/{j2}", None),
    ("PATCH", "/v1/brands/{b}/competitors/{c}", {"status": "active"}),
    ("GET", "/v1/brands/{b}/prompts/metrics", None),
    ("GET", "/v1/brands/{b}/labels/next", None),
    ("PUT", "/v1/observations/{o}/labels/{e}", {"label": "listed"}),
    ("POST", "/v1/brands/{b}/recommendations/generate", None),
    ("GET", "/v1/brands/{b}/recommendations", None),
    ("GET", "/v1/brands/{b}/recommendations/top", None),
    ("POST", "/v1/brands/{b}/recommendations/{r}/accept", None),
    ("POST", "/v1/brands/{b}/recommendations/{r}/dismiss", {"reason": "x"}),
    ("GET", "/v1/brands/{b}/tasks", None),
    ("PATCH", "/v1/brands/{b}/tasks/{t}", {"notes": "x"}),
    ("GET", "/v1/brands/{b}/citations", None),
    ("POST", "/v1/brands/{b}/audits/crawl", None),
    ("GET", "/v1/brands/{b}/audits/crawl", None),
    ("GET", "/v1/brands/{b}/clusters/gaps", None),
    ("POST", "/v1/brands/{b}/prompts/label", None),
    (
        "POST",
        "/v1/brands/{b}/pages/optimize",
        {"url": "https://x.com/", "cluster_key": "cluster:guide:Secret"},
    ),
    ("GET", "/v1/brands/{b}/pages", None),
    ("GET", "/v1/brands/{b}/pages/{a}", None),
    ("GET", "/v1/brands/{b}/alerts", None),
    ("POST", "/v1/brands/{b}/alerts/scan", None),
    ("GET", "/v1/brands/{b}/reports", None),
    ("PUT", "/v1/brands/{b}/reports/cmo", {"cadence": "weekly"}),
    ("POST", "/v1/brands/{b}/reports/cmo/runs", None),
    ("GET", "/v1/brands/{b}/reports/runs", None),
    ("GET", "/v1/brands/{b}/reports/runs/{rr}", None),
    ("POST", "/v1/brands/{b}/reports/runs/{rr}/share", None),
    ("DELETE", "/v1/brands/{b}/reports/runs/{rr}/share", None),
]


def _fill(body, ids):
    """Only the fixture knows a real id to put in a bulk PATCH."""
    if body and "ids" in body:
        return {**body, "ids": [str(ids["p"])]}
    return body


@pytest.mark.parametrize(("method", "path", "body"), CASES)
def test_org_a_cannot_reach_org_b(client, make_org, other, method, path, body):
    a = make_org("A")
    r = client.request(
        method,
        path.format(**other),
        headers=a.headers,
        json=_fill(body, other),
    )
    assert r.status_code == 404, (method, path, r.text)
    assert "Secret" not in r.text and "secret" not in r.text


def test_lists_are_empty_for_org_a(client, make_org, other):
    a = make_org("A")
    assert client.get("/v1/brands", headers=a.headers).json() == []
    assert client.get("/v1/observations", headers=a.headers).json() == []
    filtered = client.get(
        f"/v1/observations?brand_id={other['b']}", headers=a.headers
    )
    assert filtered.json() == []


def test_foreign_filter_is_indistinguishable_from_unknown_id(
    client, make_org, other
):
    """Foreign filter and unknown id return identical responses."""
    a = make_org("A")

    # Test brand_id filter with foreign id vs unknown id
    foreign_brand_resp = client.get(
        f"/v1/observations?brand_id={other['b']}", headers=a.headers
    )
    unknown_brand = uuid.uuid4()
    unknown_brand_resp = client.get(
        f"/v1/observations?brand_id={unknown_brand}", headers=a.headers
    )
    assert foreign_brand_resp.status_code == 200
    assert unknown_brand_resp.status_code == 200
    assert foreign_brand_resp.json() == unknown_brand_resp.json() == []

    # Test prompt_id filter with foreign id vs unknown id
    foreign_prompt_resp = client.get(
        f"/v1/observations?prompt_id={other['p']}", headers=a.headers
    )
    unknown_prompt = uuid.uuid4()
    unknown_prompt_resp = client.get(
        f"/v1/observations?prompt_id={unknown_prompt}", headers=a.headers
    )
    assert foreign_prompt_resp.status_code == 200
    assert unknown_prompt_resp.status_code == 200
    assert foreign_prompt_resp.json() == unknown_prompt_resp.json() == []


def test_org_b_data_is_untouched(client, owner, make_org, other):
    a = make_org("A")
    for method, path, body in CASES:
        client.request(
            method,
            path.format(**other),
            headers=a.headers,
            json=_fill(body, other),
        )
    with owner() as s:
        assert s.get(m.Brand, other["b"]).status == "active"
        comp = s.get(m.Competitor, other["c"])
        assert comp.name == "Rival"
        assert comp.status == "suggested"  # the confirm case did not land

        # Check Domain was not deleted
        domain = s.get(m.Domain, other["d"])
        assert domain is not None
        assert domain.host == "secret.com"

        # Check Prompt was not modified
        prompt = s.get(m.Prompt, other["p"])
        assert prompt.status == "active"
        # A leaked suggest_prompts would have labelled and embedded it.
        assert prompt.intent is None
        assert prompt.topic is None
        assert prompt.embedding is None

        # Check the schedule was neither replaced nor deleted
        sch = s.scalars(
            select(m.Schedule).where(m.Schedule.brand_id == other["b"])
        ).one()
        assert (sch.cadence, sch.hour_utc) == ("daily", 6)

        # Count org B's resources
        n_obs = len(s.scalars(select(m.Observation)).all())
        n_comp = len(
            s.scalars(
                select(m.Competitor).where(m.Competitor.brand_id == other["b"])
            ).all()
        )
        n_dom = len(
            s.scalars(
                select(m.Domain).where(m.Domain.brand_id == other["b"])
            ).all()
        )
        n_prompt = len(
            s.scalars(
                select(m.Prompt).where(m.Prompt.brand_id == other["b"])
            ).all()
        )
        n_job = len(
            s.scalars(select(m.Job).where(m.Job.brand_id == other["b"])).all()
        )

    assert n_obs == 1
    assert n_comp == 1
    assert n_dom == 1
    assert n_prompt == 1
    # The run job and the suggest job the fixture made, and nothing the
    # suggest cases queued.
    assert n_job == 2


def test_bulk_patch_cannot_reach_across_brands(
    client, make_org, make_brand, owner, other
):
    """Row-level security alone does not cover this: the path brand is
    legitimately org A's, only the ids in the body are foreign."""
    a = make_org("A")
    mine = make_brand(a, "Acme")
    r = client.patch(
        f"/v1/brands/{mine}/prompts",
        headers=a.headers,
        json={"ids": [str(other["p"])], "status": "paused"},
    )
    assert r.status_code == 404, r.text
    with owner() as s:
        assert s.get(m.Prompt, other["p"]).status == "active"
