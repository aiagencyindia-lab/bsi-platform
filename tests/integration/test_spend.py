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
    spend.record("x", 40_000, ledger)
    assert spend.check(10_000, ledger) == 10_000
    with pytest.raises(spend.SpendCapReached, match="cap"):
        spend.check(10_001, ledger)
