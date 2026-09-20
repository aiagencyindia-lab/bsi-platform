from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from bsi_core import models as m
from bsi_core import spend
from sqlalchemy import update


def test_ledger_round_trip(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    assert spend.ledger_micros(ledger) == 0
    spend.record("judge_eval:batched", 1_500, ledger)
    spend.record("sampling:A", 40_000, ledger)
    assert spend.ledger_micros(ledger) == 41_500


def test_db_micros_counts_engine_and_judge_cost_since_cutoff(
    owner, make_org, make_brand, make_observation
):
    org = make_org()
    bid = make_brand(org)
    old = make_observation(org, bid, status="done", text="old")
    new = make_observation(org, bid, status="done", text="new")
    cutoff = datetime.now(UTC) - timedelta(minutes=1)
    with owner() as s, s.begin():
        s.execute(
            update(m.Observation)
            .where(m.Observation.id == old)
            .values(created_at=cutoff - timedelta(days=1), cost_micros=999)
        )
        s.execute(
            update(m.Observation)
            .where(m.Observation.id == new)
            .values(cost_micros=40_000)
        )
        s.add(
            m.Extraction(
                org_id=org.id,
                observation_id=new,
                pipeline_version="2",
                model_used="x",
                brand_mentioned=False,
                cost_micros=600,
            )
        )
    assert spend.db_micros(cutoff) == 40_600


def test_check_raises_before_crossing_the_cap(tmp_path, monkeypatch, db):
    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(
        spend,
        "get_settings",
        lambda: SimpleNamespace(
            spend_cap_usd=0.05,
            spend_since=datetime.now(UTC),
            raw_store_dir=str(tmp_path),
        ),
    )
    monkeypatch.setattr(spend, "_reserved", 0)
    spend.record("x", 40_000, ledger)
    assert spend.check(10_000, ledger) == 0
    with pytest.raises(spend.SpendCapReached, match="cap"):
        spend.check(10_001, ledger)


def test_concurrent_checks_cannot_overshoot_the_cap(tmp_path, monkeypatch, db):
    import threading

    ledger = tmp_path / "ledger.jsonl"
    monkeypatch.setattr(
        spend,
        "get_settings",
        lambda: SimpleNamespace(
            spend_cap_usd=0.01,  # 10,000 micros
            spend_since=datetime.now(UTC),
            raw_store_dir=str(tmp_path),
        ),
    )
    monkeypatch.setattr(spend, "_reserved", 0)
    passed = []
    barrier = threading.Barrier(6)

    def worker():
        barrier.wait()
        try:
            spend.check(3_000, ledger)
        except spend.SpendCapReached:
            return
        passed.append(1)
        spend.record("x", 3_000, ledger, release=3_000)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(passed) == 3
    assert spend.ledger_micros(ledger) == 9_000


def test_naive_spend_since_is_rejected(monkeypatch):
    import pydantic
    from bsi_core.config import Settings

    monkeypatch.setenv("SPEND_SINCE", "2026-09-19 10:00:00")
    with pytest.raises(pydantic.ValidationError):
        Settings()


def test_db_micros_counts_job_cost(
    owner, make_org, make_brand, make_observation
):
    org = make_org()
    make_observation(org, make_brand(org), status="done")
    cutoff = datetime.now(UTC) - timedelta(minutes=1)
    with owner() as s, s.begin():
        s.execute(update(m.Job).values(cost_micros=7_500))
    assert spend.db_micros(cutoff) == 7_500
