import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from bsi_core import models as m
from bsi_core import scheduling
from bsi_core.db import system_session, tenant_session
from sqlalchemy import func, text, update

from tests.integration.test_api_recommendations import _wait_until_blocked


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


def fits(org, n: int, extra_micros: int = 0) -> bool:
    with tenant_session(org.id) as s:
        return scheduling.budget_fits(s, org.id, n, extra_micros)


def set_cost(owner, obs_id, micros, **values):
    with owner() as s, s.begin():
        s.execute(
            update(m.Observation)
            .where(m.Observation.id == obs_id)
            .values(cost_micros=micros, **values)
        )


def add_job(owner, org, brand_id, micros, kind="suggest_prompts"):
    """A suggestion job carrying cost; run jobs never carry any."""
    with owner() as s, s.begin():
        s.add(
            m.Job(
                org_id=org.id,
                brand_id=brand_id,
                kind=kind,
                scheduled_slot=datetime.now(UTC),
                status="done",
                cost_micros=micros,
            )
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


def test_spent_and_pending_refuses_outside_the_orgs_tenant_session(make_org):
    # spent_and_pending's counts rely on row-level security too, so it
    # must fail closed exactly like budget_fits and check_active_limit,
    # not trust whatever session it is handed.
    a, b = make_org("A"), make_org("B")
    with system_session() as s, pytest.raises(RuntimeError, match="tenant"):
        scheduling.spent_and_pending(s, a.id)
    with tenant_session(a.id) as s, pytest.raises(RuntimeError, match="tenant"):
        scheduling.spent_and_pending(s, b.id)


def set_budget(owner, org, usd):
    with owner() as s, s.begin():
        s.execute(
            update(m.Organization)
            .where(m.Organization.id == org.id)
            .values(daily_budget_usd=usd)
        )


def test_org_override_replaces_the_settings_default(owner, make_org):
    org = make_org()
    set_budget(owner, org, Decimal("0.50"))
    assert fits(org, 10)  # its own cap, not the $0.20 default
    assert not fits(org, 11)
    set_budget(owner, org, None)
    assert fits(org, 4)
    assert not fits(org, 5)


def test_todays_job_cost_counts(owner, make_org, make_brand, make_observation):
    org = make_org()
    add_job(owner, org, make_brand(org), 50_000)
    assert fits(org, 3)
    assert not fits(org, 4)


def test_a_run_jobs_cost_is_not_counted(owner, make_org, make_brand):
    # Only suggestion jobs carry cost; an observation's cost is counted
    # through the observation, so a costed run job would double count.
    org = make_org()
    add_job(owner, org, make_brand(org), 50_000, kind="run")
    assert fits(org, 4)


def test_job_cost_is_not_fanned_out_by_the_extraction_join(
    owner, make_org, make_brand, make_observation
):
    org = make_org()
    bid = make_brand(org)
    pid = None
    for i in range(3):
        oid = make_observation(
            org, bid, status="done", prompt_id=pid, sample_index=i
        )
        with owner() as s, s.begin():
            obs = s.get_one(m.Observation, oid)
            pid = obs.prompt_id
            s.add(
                m.Extraction(
                    org_id=org.id,
                    observation_id=oid,
                    pipeline_version="2",
                    model_used="x",
                    brand_mentioned=False,
                )
            )
    add_job(owner, org, bid, 50_000)
    assert fits(org, 3)  # 50,000 once, not 150,000
    assert not fits(org, 4)


def test_extra_micros_shifts_the_boundary(make_org):
    org = make_org()
    assert fits(org, 3, extra_micros=50_000)
    assert not fits(org, 3, extra_micros=50_001)


def test_lock_false_gives_the_same_verdict_and_still_fails_closed(make_org):
    a, b = make_org("A"), make_org("B")
    for n, expected in ((4, True), (5, False)):
        with tenant_session(a.id) as s:
            assert scheduling.budget_fits(s, a.id, n, lock=False) is expected
        assert fits(a, n) is expected
    with system_session() as s, pytest.raises(RuntimeError, match="tenant"):
        scheduling.budget_fits(s, a.id, 1, lock=False)
    with tenant_session(a.id) as s, pytest.raises(RuntimeError, match="tenant"):
        scheduling.budget_fits(s, b.id, 1, lock=False)


def test_the_default_check_waits_for_the_orgs_lock(owner, make_org):
    """Writers keep serializing: budget_fits takes the org's advisory lock
    unless told not to, so it waits while another transaction holds it."""
    org = make_org()
    holder = owner()
    holder.begin()
    holder.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:org))"),
        {"org": str(org.id)},
    )
    done = threading.Event()

    def check() -> None:
        fits(org, 1)
        done.set()

    t = threading.Thread(target=check)
    t.start()
    try:
        assert _wait_until_blocked(holder), "budget_fits did not wait"
        assert not done.is_set()
    finally:
        holder.rollback()
        holder.close()
    t.join(timeout=5)
    assert done.is_set()
