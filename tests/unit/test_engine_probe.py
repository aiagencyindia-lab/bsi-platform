"""The engine probe's pure parts: the pick rule and the spend stop."""

import importlib.util
import json
from pathlib import Path

from bsi_core.metrics import rate
from bsi_core.providers.base import EngineResult

_spec = importlib.util.spec_from_file_location(
    "engine_probe", Path("scripts/engine_probe.py")
)
assert _spec and _spec.loader
engine_probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine_probe)

LITE, LITE31, FLASH = engine_probe.MODELS


def summary(searched, cost, calls=20, completed=None):
    done = calls if completed is None else completed
    return {
        "calls": calls,
        "completed": done,
        "failed": calls - done,
        "share": rate(searched, calls),
        "mean_queries": 3.0,
        "mean_cost": cost,
        "mean_brands": 1.0,
    }


def test_a_model_below_the_bar_loses_to_one_above_it():
    results = {LITE: summary(20, 60_000), FLASH: summary(5, 20_000)}
    assert engine_probe.pick(results) == LITE


def test_an_overlapping_cheaper_candidate_wins():
    results = {LITE: summary(20, 60_000), LITE31: summary(18, 40_000)}
    assert engine_probe.pick(results) == LITE31


def test_a_cheaper_overlapping_model_below_the_bar_does_not_win():
    # 15 of 20 overlaps 20 of 20's interval but is under 0.80.
    results = {LITE: summary(20, 60_000), LITE31: summary(15, 10_000)}
    assert engine_probe.pick(results) == LITE


def test_a_share_tie_goes_to_the_lower_cost():
    results = {LITE: summary(19, 60_000), LITE31: summary(19, 50_000)}
    assert engine_probe.pick(results) == LITE31


def test_an_exact_cost_tie_goes_to_the_later_retirement_date():
    results = {LITE31: summary(20, 50_000), LITE: summary(20, 50_000)}
    assert engine_probe.pick(results) == LITE  # July 2027 beats May 2027


def test_no_pick_when_every_share_is_below_the_bar():
    results = {LITE: summary(15, 60_000), FLASH: summary(5, 20_000)}
    assert engine_probe.pick(results) is None


def test_failures_count_as_not_searched():
    # 16 searched of 16 completed, 4 failed: 16 of 20 is exactly 0.80.
    ok = summary(16, 60_000, completed=16)
    assert ok["share"]["value"] == 0.80
    assert engine_probe.pick({LITE: ok}) == LITE
    worse = summary(15, 60_000, completed=15)
    assert engine_probe.pick({LITE: worse}) is None


def test_summarize_counts_failed_calls_as_not_searched():
    ok = {"ok": True, "searched": True, "queries": 2, "cost": 50_000}
    calls = [{**ok, "brands": 1}] * 16 + [{"ok": False, "error": "x"}] * 4
    got = engine_probe.summarize(calls)
    assert (got["calls"], got["completed"], got["failed"]) == (20, 16, 4)
    assert (got["share"]["value"], got["share"]["n"]) == (0.80, 20)
    assert (got["mean_cost"], got["mean_queries"]) == (50_000, 2)


def test_a_model_cut_short_is_not_picked():
    results = {LITE: summary(19, 60_000, calls=19), FLASH: summary(5, 1)}
    assert engine_probe.pick(results) is None


def test_the_reservation_is_the_largest_probe_entry_or_the_floor():
    assert engine_probe.reservation([]) == 100_000
    assert engine_probe.reservation([40_000, 150_000]) == 150_000


def test_the_stop_counts_the_largest_entry_not_a_fixed_floor():
    costs = [150_000, *[100_000] * 32]  # 3,350,000 spent
    assert engine_probe.must_stop(costs[:-1]) is False  # 3.25M + 150k
    # 3.38M + 150k crosses 3.5M; a fixed 100k reservation would not.
    assert engine_probe.must_stop([*costs, 30_000]) is True


class FakeAdapter:
    def __init__(self, cost):
        self.cost = cost

    def query(self, prompt, country, language, grounded=True):
        raw = {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Bata and Campus"}]},
                    "grounding_metadata": {"web_search_queries": ["q"]},
                }
            ],
            "usage_metadata": {
                "prompt_token_count": 10,
                "candidates_token_count": 20,
            },
        }
        return EngineResult("ok", raw=raw, cost_micros=self.cost)

    def parse(self, raw):
        from bsi_core.providers.gemini import GeminiGroundingAdapter

        return GeminiGroundingAdapter(client=object()).parse(raw)


def test_the_probe_stops_before_the_crossing_try(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_probe.spend, "check", lambda r: 0)
    ledger = tmp_path / "ledger.jsonl"
    # An earlier run already spent 3,000,000 in 30 engine_probe entries;
    # another kind of entry does not count.
    ledger.write_text(
        json.dumps({"kind": "sampling:A", "micros": 9_000_000})
        + "\n  \n"
        + (json.dumps({"kind": "engine_probe:x", "micros": 100_000}) + "\n")
        * 30
    )
    monkeypatch.setattr(
        engine_probe.spend,
        "record",
        lambda kind, micros, release=0: ledger.open("a").write(
            json.dumps({"kind": kind, "micros": micros}) + "\n"
        ),
    )
    adapters = {m: FakeAdapter(120_000) for m in engine_probe.MODELS}
    written = []
    out = engine_probe.run(
        adapters,
        ["p0", "p1"],
        [],
        ledger,
        tmp_path / "raw",
        sleep=lambda s: None,
        write=written.append,
    )
    assert [w["stopped"] for w in written] == ["probe stop"]
    # 3,000,000 + 4 x 120,000 = 3,480,000; the next reservation is the
    # largest entry, 120,000, and 3.6M would cross 3.5M: stop.
    assert out["stopped"] == "probe stop"
    assert [out["results"][m]["calls"] for m in engine_probe.MODELS] == [
        2,
        1,
        1,
    ]
    assert out["probe_spend_micros"] == 3_480_000
    assert (tmp_path / "raw" / LITE / "p1.json").exists()
    assert engine_probe.pick(out["results"]) is None


def test_the_probe_writes_partial_results_when_the_cap_is_reached(
    tmp_path, monkeypatch
):
    def cap(r):
        raise engine_probe.spend.SpendCapReached("cap")

    monkeypatch.setattr(engine_probe.spend, "check", cap)
    written = []
    adapters = {m: FakeAdapter(1) for m in engine_probe.MODELS}
    try:
        engine_probe.run(
            adapters,
            ["p0"],
            [],
            tmp_path / "ledger.jsonl",
            tmp_path / "raw",
            write=written.append,
        )
    except engine_probe.spend.SpendCapReached:
        pass
    else:
        raise AssertionError("SpendCapReached was swallowed")
    assert [w["stopped"] for w in written] == ["spend cap"]
