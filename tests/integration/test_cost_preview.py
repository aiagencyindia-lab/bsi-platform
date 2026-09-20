"""Task 8: the advisory daily cost preview."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from bsi_core import models as m
from bsi_core import scheduling
from bsi_core.db import tenant_session
from sqlalchemy import select, update


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


def add_prompts(owner, org, brand_id, n, status="active"):
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
                    text=f"p {i}",
                    status=status,
                )
                for i in range(n)
            ]
        )


def add_schedule(owner, org, brand_id, cadence="daily", samples=2, **kw):
    with owner() as s, s.begin():
        s.add(
            m.Schedule(
                org_id=org.id,
                brand_id=brand_id,
                cadence=cadence,
                hour_utc=5,
                samples=samples,
                next_run_at=datetime.now(UTC),
                **kw,
            )
        )


def set_budget(owner, org, usd):
    with owner() as s, s.begin():
        s.execute(
            update(m.Organization)
            .where(m.Organization.id == org.id)
            .values(daily_budget_usd=Decimal(str(usd)))
        )


def preview(org, brand_id):
    with tenant_session(org.id) as s:
        return scheduling.daily_cost_preview(s, org.id, brand_id)


def test_no_schedule_assumes_one_run_a_day(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    add_prompts(owner, org, bid, 3)
    got = preview(org, bid)
    assert got["brand"] == {
        "active_prompts": 3,
        "samples": 2,
        "runs_per_day": 1.0,
        "est_daily_usd": 0.3,  # 3 x 2 x 50,000 micros
    }
    assert got["org"]["est_daily_usd"] == 0.3
    assert got["budget_usd"] == 0.2
    assert got["fits"] is False


@pytest.mark.parametrize(
    ("cadence", "runs", "usd"),
    [
        ("daily", 1.0, 0.1),
        ("every_3_days", 0.3333, 0.0333),
        ("weekly", 0.1429, 0.0143),
    ],
)
def test_cadence_divides(owner, make_org, make_brand, cadence, runs, usd):
    org = make_org()
    bid = make_brand(org)
    add_prompts(owner, org, bid, 1)
    add_schedule(owner, org, bid, cadence=cadence)
    got = preview(org, bid)
    assert got["brand"]["runs_per_day"] == runs
    assert got["brand"]["est_daily_usd"] == usd
    assert got["org"]["est_daily_usd"] == usd


def test_only_active_prompts_count(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    add_prompts(owner, org, bid, 1)
    add_prompts(owner, org, bid, 5, status="suggested")
    assert preview(org, bid)["brand"]["active_prompts"] == 1


def test_two_brands_sum_into_the_org_figure(owner, make_org, make_brand):
    org = make_org()
    a, b = make_brand(org, "A"), make_brand(org, "B")
    for bid in (a, b):
        add_prompts(owner, org, bid, 1)
        add_schedule(owner, org, bid)
    got = preview(org, a)
    # Each brand alone is affordable; together they are the whole budget.
    assert got["brand"]["est_daily_usd"] == 0.1
    assert got["org"]["est_daily_usd"] == 0.2
    assert got["fits"] is True

    c = make_brand(org, "C")
    add_prompts(owner, org, c, 1)
    add_schedule(owner, org, c)
    got = preview(org, a)
    assert got["brand"]["est_daily_usd"] == 0.1
    assert got["org"]["est_daily_usd"] == 0.3
    assert got["fits"] is False


def test_another_orgs_schedules_do_not_count(owner, make_org, make_brand):
    org, other = make_org("A"), make_org("B")
    mine, theirs = make_brand(org), make_brand(other)
    for o, bid in ((org, mine), (other, theirs)):
        add_prompts(owner, o, bid, 1)
        add_schedule(owner, o, bid)
    assert preview(org, mine)["org"]["est_daily_usd"] == 0.1


def test_a_paused_schedule_elsewhere_does_not_count(
    owner, make_org, make_brand
):
    org = make_org()
    a, b = make_brand(org, "A"), make_brand(org, "B")
    add_prompts(owner, org, a, 1)
    add_schedule(owner, org, a)
    add_prompts(owner, org, b, 1)
    add_schedule(owner, org, b, status="paused")
    assert preview(org, a)["org"]["est_daily_usd"] == 0.1


def test_fits_flips_at_the_boundary_and_agrees_with_budget_fits(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    add_prompts(owner, org, bid, 2)  # 2 x 2 x 50,000 = the $0.20 cap
    add_schedule(owner, org, bid)
    got = preview(org, bid)
    assert got["org"]["est_daily_usd"] == 0.2
    assert got["fits"] is True
    with tenant_session(org.id) as s:
        assert scheduling.budget_fits(s, org.id, 4) is True

    add_prompts(owner, org, bid, 1)  # one prompt over
    got = preview(org, bid)
    assert got["org"]["est_daily_usd"] == 0.3
    assert got["fits"] is False
    with tenant_session(org.id) as s:
        assert scheduling.budget_fits(s, org.id, 6) is False


def test_the_org_override_moves_the_boundary(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    add_prompts(owner, org, bid, 3)
    add_schedule(owner, org, bid)
    assert preview(org, bid)["fits"] is False
    set_budget(owner, org, "0.30")
    got = preview(org, bid)
    assert got["budget_usd"] == 0.3
    assert got["fits"] is True
    set_budget(owner, org, "0.29")
    assert preview(org, bid)["fits"] is False


def test_schedule_put_and_get_carry_the_preview(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    add_prompts(owner, org, bid, 1)
    url = f"/v1/brands/{bid}/schedule"
    body = {"cadence": "weekly", "hour_utc": 5, "samples": 4}
    r = client.put(url, headers=org.headers, json=body)
    assert r.status_code == 200, r.text
    want = {
        "active_prompts": 1,
        "samples": 4,
        "runs_per_day": 0.1429,
        "est_daily_usd": 0.0286,
    }
    assert r.json()["cost_preview"]["brand"] == want
    got = client.get(url, headers=org.headers).json()["cost_preview"]
    assert got["brand"] == want
    assert got["fits"] is True


def test_bulk_activation_returns_the_preview(
    client, owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    add_prompts(owner, org, bid, 3, status="suggested")
    base = f"/v1/brands/{bid}/prompts"
    ids = [p["id"] for p in client.get(base, headers=org.headers).json()]
    r = client.patch(
        base, headers=org.headers, json={"ids": ids, "status": "active"}
    )
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["updated"] == 3
    # The rows just activated are counted.
    assert got["cost_preview"]["brand"]["active_prompts"] == 3
    assert got["cost_preview"]["org"]["est_daily_usd"] == 0.3
    assert got["cost_preview"]["fits"] is False
