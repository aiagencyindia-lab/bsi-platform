from datetime import timedelta
from types import SimpleNamespace

import pytest
from bsi_core import models as m
from bsi_core import scheduling
from bsi_core.db import system_session, tenant_session
from sqlalchemy import func, update


@pytest.fixture(autouse=True)
def budget(monkeypatch):
    # $0.20 cap, 50,000 micros per observation: 4 observations fit.
    monkeypatch.setattr(
        scheduling,
        "get_settings",
        lambda: SimpleNamespace(
            daily_budget_usd=0.2, obs_cost_estimate_micros=50_000
        ),
    )


def fits(org, n: int) -> bool:
    with tenant_session(org.id) as s:
        return scheduling.budget_fits(s, org.id, n)


def set_cost(owner, obs_id, micros, **values):
    with owner() as s, s.begin():
        s.execute(
            update(m.Observation)
            .where(m.Observation.id == obs_id)
            .values(cost_micros=micros, **values)
        )


def test_empty_org_fits_up_to_the_cap(make_org):
    org = make_org()
    assert fits(org, 4)
    assert not fits(org, 5)


def test_todays_observation_and_extraction_cost_count(
    owner, make_org, make_brand, make_observation
):
    org = make_org()
    oid = make_observation(org, make_brand(org), status="done")
    set_cost(owner, oid, 40_000)
    with owner() as s, s.begin():
        s.add(
            m.Extraction(
                org_id=org.id,
                observation_id=oid,
                pipeline_version="2",
                model_used="x",
                brand_mentioned=False,
                cost_micros=10_000,
            )
        )
    assert fits(org, 3)  # 50,000 spent + 3 x 50,000 = cap
    assert not fits(org, 4)


def test_yesterdays_spend_does_not_count(
    owner, make_org, make_brand, make_observation
):
    org = make_org()
    oid = make_observation(org, make_brand(org), status="done")
    set_cost(owner, oid, 150_000, requested_at=func.now() - timedelta(days=1))
    assert fits(org, 4)


def test_queued_running_and_retry_count_as_pending(
    make_org, make_brand, make_observation
):
    org = make_org()
    bid = make_brand(org)
    for status in ("queued", "running", "retry", "failed", "done"):
        make_observation(org, bid, status=status, text=status)
    assert fits(org, 1)  # 3 pending + 1 = 4
    assert not fits(org, 2)


def test_another_orgs_spend_does_not_count(
    owner, make_org, make_brand, make_observation
):
    org, other = make_org("A"), make_org("B")
    ob = make_brand(other)
    oid = make_observation(other, ob, status="done")
    set_cost(owner, oid, 200_000)
    make_observation(other, ob, status="queued", text="pending")
    assert fits(org, 4)
    assert not fits(other, 1)


def test_refuses_to_run_outside_the_orgs_tenant_session(make_org):
    # Outside a tenant session row-level security hides every row, so the
    # check would see zero spend and pass anything up to the cap.
    a, b = make_org("A"), make_org("B")
    with system_session() as s, pytest.raises(RuntimeError, match="tenant"):
        scheduling.budget_fits(s, a.id, 1)
    with tenant_session(a.id) as s, pytest.raises(RuntimeError, match="tenant"):
        scheduling.budget_fits(s, b.id, 1)
