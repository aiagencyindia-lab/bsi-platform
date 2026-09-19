import pytest
from bsi_core import models as m
from sqlalchemy import select


@pytest.fixture
def other(owner, make_org, make_brand, make_observation):
    """Org B with one of everything; returns ids."""
    b = make_org("B")
    bid = make_brand(b, "Secret")
    with owner() as s, s.begin():
        comp = m.Competitor(org_id=b.id, brand_id=bid, name="Rival")
        dom = m.Domain(org_id=b.id, brand_id=bid, host="secret.com")
        s.add_all([comp, dom])
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


def test_org_b_data_is_untouched(client, owner, make_org, other):
    a = make_org("A")
    for method, path, body in CASES:
        client.request(
            method, path.format(**other), headers=a.headers, json=body
        )
    with owner() as s:
        assert s.get(m.Brand, other["b"]).status == "active"
        assert s.get(m.Competitor, other["c"]).name == "Rival"
        n = len(s.scalars(select(m.Observation)).all())
    assert n == 1
