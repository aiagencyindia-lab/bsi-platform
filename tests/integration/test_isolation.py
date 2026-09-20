import uuid

import pytest
from bsi_core import models as m
from sqlalchemy import func, select


@pytest.fixture
def other(owner, make_org, make_brand, make_observation):
    """Org B with one of everything; returns ids."""
    b = make_org("B")
    bid = make_brand(b, "Secret")
    with owner() as s, s.begin():
        comp = m.Competitor(org_id=b.id, brand_id=bid, name="Rival")
        dom = m.Domain(org_id=b.id, brand_id=bid, host="secret.com")
        sch = m.Schedule(
            org_id=b.id,
            brand_id=bid,
            cadence="daily",
            hour_utc=6,
            next_run_at=func.now(),
        )
        s.add_all([comp, dom, sch])
        s.flush()
        cid, did = comp.id, dom.id
    oid = make_observation(b, bid, raw={"secret": True}, status="done")
    with owner() as s:
        obs = s.get(m.Observation, oid)
        pid, jid = obs.prompt_id, obs.job_id
    return {"b": bid, "c": cid, "d": did, "o": oid, "p": pid, "j": jid}


CASES = [
    ("GET", "/v1/brands/{b}", None),
    ("PATCH", "/v1/brands/{b}", {"name": "x"}),
    ("DELETE", "/v1/brands/{b}", None),
    ("GET", "/v1/brands/{b}/competitors", None),
    ("POST", "/v1/brands/{b}/competitors", {"name": "x"}),
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
]


@pytest.mark.parametrize(("method", "path", "body"), CASES)
def test_org_a_cannot_reach_org_b(client, make_org, other, method, path, body):
    a = make_org("A")
    r = client.request(
        method, path.format(**other), headers=a.headers, json=body
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
            method, path.format(**other), headers=a.headers, json=body
        )
    with owner() as s:
        assert s.get(m.Brand, other["b"]).status == "active"
        assert s.get(m.Competitor, other["c"]).name == "Rival"

        # Check Domain was not deleted
        domain = s.get(m.Domain, other["d"])
        assert domain is not None
        assert domain.host == "secret.com"

        # Check Prompt was not modified
        prompt = s.get(m.Prompt, other["p"])
        assert prompt.status == "active"

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

    assert n_obs == 1
    assert n_comp == 1
    assert n_dom == 1
    assert n_prompt == 1
