# Slice 56: replace the gemini-2.5-flash engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** add price rows for the candidate engines, a spend-guarded probe that measures them on the Run 1 prompts, and a comparability guard so no delta, alert or impact label compares answers from two engine models; then (Task 2, after the probe) switch the default engine to the model the probe picks.

**Architecture:** `PRICES` gains two rows. `scripts/engine_probe.py` runs the probe; its rule (`pick`) and spend stop (`reservation`, `must_stop`) are pure functions with unit tests. `metrics.window_models` returns a window's distinct engine models, and one helper, `metrics.comparability(versions, models)`, decides comparability for both `metrics.brand_deltas` and `competitors._comparable`.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Postgres (RLS), google-genai on Vertex AI, pytest, ruff, mypy.

**Spec:** docs/superpowers/specs/2026-10-08-slice56-engine-replacement-design.md

Every block below was applied by script to a fresh copy of `87fc0c4` and verified on a second fresh copy: the result is byte-identical to the proof for all 9 files; each replace block occurs exactly once, ends on a whole line, and matches with or without its trailing newline. Apply the blocks as written; do not retype them. New files are given in full.

## Global Constraints

- Every shell command starts with `cd /Users/vineet/Downloads/ADK/bsi-wt/slice56 && …` (the cwd resets after each command).
- Added text must not contain any word in `FORBIDDEN` of tests/unit/test_recommend_copy.py. Banned-word grep (must block the commit): `! { git diff --cached -U0 | grep '^+' | grep -v -F 'Banned-word grep (must block the commit)' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1([^0-9]|$)|top spot|dominat|certain'; }` — it gates every commit and must print nothing.
- **Never run `scripts/engine_probe.py` or call any Google API.** The probe spends real money and is run by the controller only, on the user's go.
- No migration; no new route; no API schema change (`brand_metrics` output is unchanged); the dev DB is not touched.
- ruff line length 80; `mypy --strict` covers packages/core/bsi_core.
- Commit trailer, after a blank line: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Shared test DB `bsi_test` on :5433: run `pgrep -fl "bsi.*pytest"` before any pytest run and wait if one is running.
- Mutation steps: stage the implemented files **before** applying any mutant, then restore each mutant with `git checkout -- <file>` (which restores from the index) and confirm `git diff -- <file>` is empty.
- Never run Prettier; never `rm`; no heredoc file writes except commit messages; never stage `.DS_Store`.
- Report every command's one-line summary, pasted, not paraphrased; count before stating a number.

---

### Task 1: prices, the probe script, the comparability guard

**Files:**
- Modify: `packages/core/bsi_core/providers/gemini.py` (`PRICES`)
- Modify: `packages/core/bsi_core/metrics.py` (new `window_models`, `comparability`; `brand_deltas`)
- Modify: `packages/core/bsi_core/competitors.py` (imports; `_comparable`)
- Create: `scripts/engine_probe.py`
- Test: `tests/unit/test_engine_probe.py` (new), `tests/unit/test_gemini_adapter.py`, `tests/integration/test_metrics.py`, `tests/integration/test_competitors.py`, `tests/integration/test_impact.py`

**Interfaces:**
- Produces: `PRICES["gemini-3.5-flash-lite"]`, `PRICES["gemini-3.1-flash-lite"]`; `metrics.window_models(s, brand_id, f) -> list[str]`; `metrics.comparability(versions: set[str], models: set[str]) -> tuple[bool, str | None]`; `scripts/engine_probe.py` with `MODELS`, `pick(results) -> str | None`, `reservation(costs) -> int`, `must_stop(costs) -> bool`, `summarize(calls) -> dict`, `run(...)`, `main()`.

- [ ] **Step 0: Install the worktree's dependencies**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice56 && uv sync`
Expected: finishes without error; `git status` shows no tracked file changed.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_engine_probe.py` with exactly this content:

````python
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
````

In `tests/unit/test_gemini_adapter.py` (insert two price tests and a helper before the per-query test), replace this block (it occurs exactly once and ends on a whole line):

````python
def test_per_query_cost_scales_with_query_count():
````

with:

````python
def test_gemini_3_5_flash_lite_is_priced_per_search_query():
    adapter = GeminiGroundingAdapter(
        client=object(), model="gemini-3.5-flash-lite"
    )
    # min fixture: 10 * 0.30 + 120 * 2.50 = 303 for tokens, 1 query.
    assert adapter.cost(RAW) == 14_303
    raw = {**RAW, "candidates": [_three_queries()]}
    assert adapter.cost(raw) == 303 + 42_000


def test_gemini_3_1_flash_lite_is_priced_per_search_query():
    adapter = GeminiGroundingAdapter(
        client=object(), model="gemini-3.1-flash-lite"
    )
    # 10 * 0.25 + 120 * 1.50 = 182.5, rounded to 182, plus 14_000.
    assert adapter.cost(RAW) == 14_182
    raw = {**RAW, "candidates": [_three_queries()]}
    assert adapter.cost(raw) == 182 + 42_000


def _three_queries():
    return {"grounding_metadata": {"web_search_queries": ["a", "b", "c"]}}


def test_per_query_cost_scales_with_query_count():
````

In `tests/integration/test_metrics.py` (insert the model tests before `test_suggested_competitor_is_not_measured`), replace this block (it occurs exactly once and ends on a whole line):

````python
def test_suggested_competitor_is_not_measured(owner, scene):
````

with:

````python
def set_models(owner, bid, before, after):
    """The windows fixture's older observations get model `before`, the
    newer ones `after` (None leaves the column NULL)."""
    cut = func.now() - timedelta(hours=12)
    with owner() as s, s.begin():
        for model, older in ((before, True), (after, False)):
            s.execute(
                update(m.Observation)
                .where(
                    m.Observation.brand_id == bid,
                    m.Observation.requested_at < cut
                    if older
                    else m.Observation.requested_at >= cut,
                )
                .values(model=model)
            )


def test_brand_deltas_refuses_mixed_engine_models(owner, windows):
    org, bid = windows("2")
    set_models(owner, bid, "gemini-2.5-flash", "gemini-3.5-flash-lite")
    got = deltas(org, bid)
    assert got["comparable"] is False
    assert got["deltas"] is None
    assert got["reason"] == (
        "windows use different engine models "
        "['gemini-2.5-flash', 'gemini-3.5-flash-lite']"
    )


def test_brand_deltas_names_the_pipeline_first(owner, windows):
    org, bid = windows("1")
    set_models(owner, bid, "gemini-2.5-flash", "gemini-3.5-flash-lite")
    got = deltas(org, bid)
    assert got["comparable"] is False
    assert got["reason"].startswith("windows use different pipeline versions")


def test_brand_deltas_ignores_null_models(owner, windows):
    org, bid = windows("2")
    set_models(owner, bid, None, "gemini-3.5-flash-lite")
    assert deltas(org, bid)["comparable"] is True


def test_suggested_competitor_is_not_measured(owner, scene):
````

In `tests/integration/test_competitors.py` (insert the model test before the pipeline-version test), replace this block (it occurs exactly once and ends on a whole line):

````python
def test_mixed_pipeline_versions_are_not_comparable(owner, feed):
````

with:

````python
def test_mixed_engine_models_are_not_comparable(owner, feed):
    org, bid, ids = feed
    with owner() as s, s.begin():
        for side, model in (
            ("before", "gemini-2.5-flash"),
            ("after", "gemini-3.5-flash-lite"),
        ):
            s.execute(
                update(m.Observation)
                .where(
                    m.Observation.id.in_(
                        [o for p in ids["prompts"] for o in ids[side][p]]
                    )
                )
                .values(model=model)
            )
    reason = (
        "windows use different engine models "
        "['gemini-2.5-flash', 'gemini-3.5-flash-lite']"
    )
    got = changes(org, bid)
    assert (got["comparable"], got["reason"], got["changes"]) == (
        False,
        reason,
        [],
    )
    with tenant_session(org.id) as s:
        d = entity_deltas(s, bid, Filters(), 14, NOW)
    assert (d["comparable"], d["reason"], d["deltas"]) == (
        False,
        reason,
        None,
    )


def test_mixed_pipeline_versions_are_not_comparable(owner, feed):
````

In `tests/integration/test_impact.py` (the import), replace this block (it occurs exactly once and ends on a whole line):

````python
from bsi_core.impact import close_window, measure
````

with:

````python
from bsi_core.impact import close_window, measure
from sqlalchemy import update
````

In `tests/integration/test_impact.py` (insert the model test before `test_measure_counts_only_the_tasks_prompts`), replace this block (it occurs exactly once and ends on a whole line):

````python
def test_measure_counts_only_the_tasks_prompts(owner, base, make_observation):
````

with:

````python
def test_measure_refuses_mixed_engine_models(owner, base):
    org, bid, pid, first = base
    seed(owner, org, first, BEFORE, 10, 20, start=100)
    seed(owner, org, first, AFTER, 10, 20, start=200)
    with owner() as s, s.begin():
        for when, model in (
            (BEFORE, "gemini-2.5-flash"),
            (AFTER, "gemini-3.5-flash-lite"),
        ):
            s.execute(
                update(m.Observation)
                .where(
                    m.Observation.brand_id == bid,
                    m.Observation.requested_at == when,
                )
                .values(model=model)
            )
    got, payload = measured(org, make_task(owner, org, bid, [pid]))
    assert got == "not_comparable"
    assert payload["delta"] is None
    assert "engine models" in payload["reason"]


def test_measure_counts_only_the_tasks_prompts(owner, base, make_observation):
````

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice56 && uv run pytest -q -p no:cacheprovider tests/unit/test_engine_probe.py`
Expected (proof): `1 error` at collection (`scripts/engine_probe.py` does not exist yet).

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice56 && uv run pytest -q -p no:cacheprovider tests/unit/test_gemini_adapter.py tests/integration/test_metrics.py tests/integration/test_competitors.py tests/integration/test_impact.py`
Expected (proof): `5 failed, 58 passed` — the two flash-lite price tests, `test_brand_deltas_refuses_mixed_engine_models`, `test_mixed_engine_models_are_not_comparable`, `test_measure_refuses_mixed_engine_models`. (`test_brand_deltas_names_the_pipeline_first` and `test_brand_deltas_ignores_null_models` pass on main: they pin behaviour the change must keep.)

- [ ] **Step 3: Implement**

In `packages/core/bsi_core/providers/gemini.py` (the price table), replace this block (it occurs exactly once and ends on a whole line):

````python
# List prices read 2026-09-19. Sources: docs/findings-slice1.md (2.5) and
# the slice-2 spec §2 (3.8). 3.8 is recorded at its standard rate from
# 2027-01-01; it is cheaper until then, but planning should not rely on it.
# ponytail: marginal price at scale; the free grounding allowance (1,500
# prompts/day on 2.5, 5,000 queries/month on 3) is not modelled.
# A model missing here fails its observations rather than being mispriced.
PRICES = {
    "gemini-2.5-flash": Price(0.30, 2.50, 35_000, 0),
    "gemini-3.8-flash": Price(1.50, 7.50, 0, 14_000),
}
````

with:

````python
# List prices read 2026-09-19. Sources: docs/findings-slice1.md (2.5) and
# the slice-2 spec §2 (3.8). 3.8 is recorded at its standard rate from
# 2027-01-01; it is cheaper until then, but planning should not rely on it.
# The two flash-lite rows were read from the pricing page on 2026-10-08
# (slice-56 spec); 2.5 stays priced for the observations it produced.
# ponytail: marginal price at scale; the free grounding allowance (1,500
# prompts/day on 2.5, 5,000 queries/month on 3) is not modelled.
# A model missing here fails its observations rather than being mispriced.
PRICES = {
    "gemini-2.5-flash": Price(0.30, 2.50, 35_000, 0),
    "gemini-3.8-flash": Price(1.50, 7.50, 0, 14_000),
    "gemini-3.5-flash-lite": Price(0.30, 2.50, 0, 14_000),
    "gemini-3.1-flash-lite": Price(0.25, 1.50, 0, 14_000),
}
````

In `packages/core/bsi_core/metrics.py` (insert `window_models` and `comparability` before `delta`), replace this block (it occurs exactly once and ends on a whole line):

````python
def delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
````

with:

````python
def window_models(s: Session, brand_id: uuid.UUID, f: Filters) -> list[str]:
    """Distinct engine models of the done observations in a window; a
    NULL model is unknown and does not count."""
    where, params = _where(brand_id, f)
    return list(
        s.scalars(
            text(
                "SELECT DISTINCT o.model FROM observation o "
                f"WHERE {where} AND o.status = 'done' "
                "AND o.model IS NOT NULL ORDER BY 1"
            ),
            params,
        ).all()
    )


def comparability(
    versions: set[str], models: set[str]
) -> tuple[bool, str | None]:
    """Two windows compare only on one pipeline version and one engine
    model; the pipeline reason comes first because it names a fix."""
    if len(versions) > 1:
        return False, (
            "windows use different pipeline versions "
            f"{sorted(versions)}; re-extract the older window"
        )
    if len(models) > 1:
        return False, f"windows use different engine models {sorted(models)}"
    return True, None


def delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
````

In `packages/core/bsi_core/metrics.py` (the body of `brand_deltas`), replace this block (it occurs exactly once and ends on a whole line):

````python
    mid, start = to - timedelta(days=days), to - timedelta(days=2 * days)
    before = brand_metrics(
        s, brand_id, replace(f, date_from=start, date_to=mid)
    )
    after = brand_metrics(s, brand_id, replace(f, date_from=mid, date_to=to))
    versions = set(before["pipeline_versions"]) | set(
        after["pipeline_versions"]
    )
    comparable = len(versions) <= 1
    return {
        "before": {"from": start, "to": mid, **before},
        "after": {"from": mid, "to": to, **after},
        "comparable": comparable,
        "reason": None
        if comparable
        else (
            "windows use different pipeline versions "
            f"{sorted(versions)}; re-extract the older window"
        ),
        "deltas": {k: delta(before[k], after[k]) for k in DELTA_METRICS}
````

with:

````python
    mid, start = to - timedelta(days=days), to - timedelta(days=2 * days)
    fb = replace(f, date_from=start, date_to=mid)
    fa = replace(f, date_from=mid, date_to=to)
    before = brand_metrics(s, brand_id, fb)
    after = brand_metrics(s, brand_id, fa)
    versions = set(before["pipeline_versions"]) | set(
        after["pipeline_versions"]
    )
    models = set(window_models(s, brand_id, fb)) | set(
        window_models(s, brand_id, fa)
    )
    comparable, reason = comparability(versions, models)
    return {
        "before": {"from": start, "to": mid, **before},
        "after": {"from": mid, "to": to, **after},
        "comparable": comparable,
        "reason": reason,
        "deltas": {k: delta(before[k], after[k]) for k in DELTA_METRICS}
````

In `packages/core/bsi_core/competitors.py` (the `from .metrics import (...)` list), replace this block (it occurs exactly once and ends on a whole line):

````python
    _entities,
    _where,
    delta,
    rate,
    window_versions,
)
````

with:

````python
    _entities,
    _where,
    comparability,
    delta,
    rate,
    window_models,
    window_versions,
)
````

In `packages/core/bsi_core/competitors.py` (the body of `_comparable`), replace this block (it occurs exactly once and ends on a whole line):

````python
    versions = set(window_versions(s, brand_id, before)) | set(
        window_versions(s, brand_id, after)
    )
    if len(versions) <= 1:
        return True, None
    return False, (
        "windows use different pipeline versions "
        f"{sorted(versions)}; re-extract the older window"
    )
````

with:

````python
    versions = set(window_versions(s, brand_id, before)) | set(
        window_versions(s, brand_id, after)
    )
    models = set(window_models(s, brand_id, before)) | set(
        window_models(s, brand_id, after)
    )
    return comparability(versions, models)
````

Create `scripts/engine_probe.py` with exactly this content:

````python
"""Compare candidate engine models before gemini-2.5-flash retires
(slice-56 spec, Section 1).

One grounded call per prompt per model on the prompts of eval/run1.json,
interleaved per prompt in MODELS order. Run it with the main checkout's
.env sourced and RAW_STORE_DIR set to its data/ directory, so the spend
ledger is the canonical one:

usage: python scripts/engine_probe.py
Raw answers go to $RAW_STORE_DIR/experiments/engine/ (git-ignored);
results to eval/results/engine_probe_v0.json. Every try is spend-guarded.
"""

import json
import time
from datetime import date
from pathlib import Path

from bsi_core import spend
from bsi_core.config import get_settings
from bsi_core.matching import Entity, find_mentions
from bsi_core.metrics import rate
from bsi_core.providers.gemini import GeminiGroundingAdapter
from google import genai
from google.genai import types

MODELS = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.8-flash")
# Retirement dates from Google's lifecycle page, read 2026-10-08; none
# announced counts as the earliest.
RETIRES = {
    "gemini-3.5-flash-lite": date(2027, 7, 21),
    "gemini-3.1-flash-lite": date(2027, 5, 7),
}
CALLS = 20  # a model needs all of them to be picked
BAR = 0.80  # minimum searched share
FLOOR_MICROS = 100_000
STOP_MICROS = 3_500_000
LEDGER_FLOOR = 6_858_204  # the canonical ledger on 2026-10-08
KIND = "engine_probe:"
OUT = Path("eval/results/engine_probe_v0.json")


class Stop(Exception):
    pass


def probe_costs(ledger: Path) -> list[int]:
    """Every engine_probe ledger entry, earlier runs included."""
    if not ledger.exists():
        return []
    lines = ledger.read_text().splitlines()
    rows = [json.loads(x) for x in lines if x.strip()]
    return [
        int(r["micros"]) for r in rows if r.get("kind", "").startswith(KIND)
    ]


def reservation(costs: list[int]) -> int:
    return max([FLOOR_MICROS, *costs])


def must_stop(costs: list[int]) -> bool:
    return sum(costs) + reservation(costs) > STOP_MICROS


def summarize(calls: list[dict]) -> dict:
    done = [c for c in calls if c["ok"]]
    searched = sum(c["searched"] for c in done)

    def mean(key: str) -> float | None:
        return sum(c[key] for c in done) / len(done) if done else None

    return {
        "calls": len(calls),
        "completed": len(done),
        "failed": len(calls) - len(done),
        # a failed call counts as not searched
        "share": rate(searched, len(calls)),
        "mean_queries": mean("queries"),
        "mean_cost": mean("cost"),
        "mean_brands": mean("brands"),
    }


def _later_first(model: str) -> int:
    return -RETIRES.get(model, date.min).toordinal()


def pick(results: dict[str, dict]) -> str | None:
    """The spec's rule: eligible with CALLS calls and a share of at least
    BAR; the leader has the highest share; the leader and every candidate
    whose Wilson interval touches it compete on mean cost, then on the
    later retirement date, then on model id."""
    cands = {
        m: r
        for m, r in results.items()
        if r["calls"] >= CALLS and (r["share"]["value"] or 0) >= BAR
    }
    if not cands:
        return None
    leader = max(
        cands,
        key=lambda m: (cands[m]["share"]["value"], -cands[m]["mean_cost"]),
    )
    low, high = (
        cands[leader]["share"]["ci_low"],
        cands[leader]["share"]["ci_high"],
    )
    pool = [
        m
        for m, r in cands.items()
        if r["share"]["ci_low"] <= high and r["share"]["ci_high"] >= low
    ]
    return min(pool, key=lambda m: (cands[m]["mean_cost"], _later_first(m), m))


def call(adapter, model, i, prompt, entities, ledger, raw_dir, sleep):
    for attempt in range(3):
        costs = probe_costs(ledger)
        if must_stop(costs):
            raise Stop
        r = reservation(costs)
        spend.check(r)  # SpendCapReached propagates
        started, result, cost = time.monotonic(), None, 0
        try:
            result = adapter.query(prompt, "IN", "en", grounded=True)
            cost = result.cost_micros
        finally:
            spend.record(KIND + model, cost, release=r)
        if result.kind == "ok":
            path = raw_dir / model / f"p{i}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(result.raw))
            usage = result.raw.get("usage_metadata") or {}
            text = adapter.parse(result.raw).text
            return {
                "ok": True,
                "searched": bool(result.search_queries),
                "queries": result.search_queries or 0,
                "cost": cost,
                "tokens_in": usage.get("prompt_token_count") or 0,
                "tokens_out": (usage.get("candidates_token_count") or 0)
                + (usage.get("thoughts_token_count") or 0),
                "latency": round(time.monotonic() - started, 2),
                "brands": len(
                    {h.entity_id for h in find_mentions(text, entities)}
                ),
            }
        print(model, i, result.kind, result.error, flush=True)
        if result.kind == "fatal":
            break
        sleep(15 * (attempt + 1))
    return {"ok": False, "error": result.error if result else None}


def report(calls, ledger, stopped):
    results = {m: summarize(c) for m, c in calls.items()}
    return {
        "models": list(calls),
        "results": results,
        "calls": calls,
        "probe_spend_micros": sum(probe_costs(ledger)),
        "stopped": stopped,
        "pick": pick(results),
    }


def run(
    adapters,
    prompts,
    entities,
    ledger,
    raw_dir,
    sleep=time.sleep,
    write=lambda out: None,
):
    """Every model on prompt 0, then prompt 1, ...; partial results are
    written on either stop."""
    calls: dict[str, list[dict]] = {m: [] for m in adapters}
    stopped = None
    try:
        for i, prompt in enumerate(prompts):
            for model, adapter in adapters.items():
                calls[model].append(
                    call(
                        adapter,
                        model,
                        i,
                        prompt,
                        entities,
                        ledger,
                        raw_dir,
                        sleep,
                    )
                )
    except Stop:
        stopped = "probe stop"
    except spend.SpendCapReached:
        write(report(calls, ledger, "spend cap"))
        raise
    out = report(calls, ledger, stopped)
    write(out)
    return out


def main() -> None:
    settings = get_settings()
    ledger = Path(settings.raw_store_dir) / "spend_ledger.jsonl"
    ledger_total = spend.ledger_micros(ledger)
    db_total = spend.db_micros(settings.spend_since)
    print(f"ledger {ledger_total} micros, db {db_total} micros", flush=True)
    if ledger_total < LEDGER_FLOOR:
        raise SystemExit(
            f"ledger {ledger} reads {ledger_total} micros, below "
            f"{LEDGER_FLOOR}: not the canonical ledger"
        )
    run1 = json.loads(Path("eval/run1.json").read_text())
    entities = [
        Entity(run1["brand"], "brand", (run1["brand"], *run1["aliases"]))
    ] + [
        Entity(c["name"], "competitor", (c["name"], *c["aliases"]))
        for c in run1["competitors"]
    ]
    client = genai.Client(http_options=types.HttpOptions(timeout=120_000))
    adapters = {m: GeminiGroundingAdapter(client, model=m) for m in MODELS}
    raw_dir = Path(settings.raw_store_dir) / "experiments" / "engine"

    def write(out: dict) -> None:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(out, indent=1))
        print("wrote", OUT, "| stopped:", out["stopped"], flush=True)
        print("pick:", out["pick"], flush=True)

    run(adapters, run1["prompts"], entities, ledger, raw_dir, write=write)


if __name__ == "__main__":
    main()
````

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice56 && uv run pytest -q -p no:cacheprovider tests/unit/test_engine_probe.py tests/unit/test_gemini_adapter.py tests/integration/test_metrics.py tests/integration/test_competitors.py tests/integration/test_impact.py`
Expected (proof): all pass (13 probe tests; unit files 34 passed, integration files 42 passed).

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice56 && uv run ruff format --check . && uv run ruff check . && uv run mypy`
Expected (proof): all files already formatted; `All checks passed!`; `Success: no issues found in 31 source files`.

- [ ] **Step 5: Mutation table**

Stage first: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice56 && git add -A packages scripts tests`. Then apply each mutant, run the named test files, paste the summary line, restore with `git checkout -- <file>`, and confirm `git diff -- <file>` is empty. Integration files: test_metrics, test_competitors, test_impact. Unit files: test_engine_probe, test_gemini_adapter. Proof results in the last column.

| Mutant | Change | Tests | Proof |
|---|---|---|---|
| M1 | `brand_deltas`: `comparability(versions, set())` | integration | 2 failed |
| M2 | `_comparable`: `comparability(versions, set())` | integration | 1 failed |
| M3 | `comparability`: the models check before the versions check | integration | 1 failed (`test_brand_deltas_names_the_pipeline_first`) |
| M4 | `window_models` without `AND o.model IS NOT NULL` | integration | 1 failed (`test_brand_deltas_ignores_null_models`, by a TypeError from `sorted()` over `None`) |
| M5 | `pick` returns `leader` (no step 4) | unit | 2 failed |
| M6 | `pick` bar `>= 0` instead of `>= BAR` | unit | 4 failed |
| M7 | `summarize`: `rate(searched, len(done))` | unit | 1 failed (`test_summarize_counts_failed_calls_as_not_searched`) |
| M8 | `reservation` returns `FLOOR_MICROS` | unit | 2 failed |
| M9 | 3.5-flash-lite row `Price(0.30, 2.50, 0, 0)` | unit | 1 failed |
| M10 | 3.1-flash-lite row `Price(0.25, 1.50, 0, 0)` | unit | 1 failed |
| M11 | `pick`'s final key `(mean_cost, m)` (no retirement date) | unit | 1 failed |
| M12 | `pick` eligibility `calls >= 0` | unit | 1 failed |
| M13 | `run` without `write(out)` after the loop | unit | 1 failed (`test_the_probe_stops_before_the_crossing_try`) |
| M14 | `probe_costs` reading lines without `if x.strip()` | unit | 1 failed (`test_the_probe_stops_before_the_crossing_try`) |

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice56 && git add packages/core/bsi_core/providers/gemini.py packages/core/bsi_core/metrics.py packages/core/bsi_core/competitors.py scripts/engine_probe.py tests/unit/test_engine_probe.py tests/unit/test_gemini_adapter.py tests/integration/test_metrics.py tests/integration/test_competitors.py tests/integration/test_impact.py && ! { git diff --cached -U0 | grep '^+' | grep -v -F 'Banned-word grep (must block the commit)' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1([^0-9]|$)|top spot|dominat|certain'; } && git commit -F - <<'EOF' # Banned-word grep (must block the commit)
feat: engine probe, flash-lite prices, and an engine-model comparability guard

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### The probe run (controller only, after Task 1 is reviewed; not a task)

On the user's go, the controller runs, from the worktree:

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice56 && set -a && source /Users/vineet/Downloads/ADK/bsi-platform/.env && set +a && RAW_STORE_DIR=/Users/vineet/Downloads/ADK/bsi-platform/data uv run python scripts/engine_probe.py
```

It prints the ledger and DB spend first and stops if the ledger reads below 6,858,204 micros. The results file `eval/results/engine_probe_v0.json` is committed; every number and the pick go to the ledger.

---

### Task 2: the switch (addendum, 2026-10-08, after the probe)

The probe ran on 2026-10-08 from `6b3caf8` and is committed at `85fce17` (`eval/results/engine_probe_v0.json`). It completed all 60 calls (one 429 retried) for $2.063363 of recorded spend. `pick` returned `gemini-3.5-flash-lite`: it searched 20 of 20 answers, as did `gemini-3.1-flash-lite`, so their intervals were identical and the cheaper won, at a mean 30,039.5 micros per observation ($0.0300) against 53,652.5. `gemini-3.8-flash` searched 6 of 20. An independent recount from the raw files gave the same searched and query counts. The estimate formula gives max(50,000, the smallest multiple of 10,000 strictly above 30,039.5 + 2,000) = max(50,000, 40,000) = 50,000, so `obs_cost_estimate_micros` keeps its value and gains a comment.

Every block below was applied by script to a fresh copy of `85fce17` and verified on a second fresh copy (byte-identical; each block once, with and without its trailing newline, ending on a whole line).

**Files:**
- Modify: `packages/core/bsi_core/config.py` (`engine_model` and its comment; a comment on `obs_cost_estimate_micros`)
- Modify: `.env.example` (`ENGINE_MODEL`)
- Test: `tests/unit/test_gemini_adapter.py` (imports; the default-engine test renamed and rewritten), `tests/integration/test_full_flow.py` (`CannedGemini` pinned)

**Interfaces:**
- Consumes: `PRICES["gemini-3.5-flash-lite"]` from Task 1.
- Produces: `Settings.model_fields["engine_model"].default == "gemini-3.5-flash-lite"`.

- [ ] **Step 0: Dependencies.** Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice56 && uv sync`. Expected: no tracked file changes.

- [ ] **Step 1: Write the failing tests**

In `tests/unit/test_gemini_adapter.py` (the imports), replace this block (it occurs exactly once and ends on a whole line):

````python
import pytest
from bsi_core.providers.gemini import GeminiGroundingAdapter
````

with:

````python
import pytest
from bsi_core.config import Settings
from bsi_core.providers.gemini import PRICES, GeminiGroundingAdapter
````

In `tests/unit/test_gemini_adapter.py` (the default-engine test), replace this block (it occurs exactly once and ends on a whole line):

````python
def test_default_engine_is_gemini_2_5_flash_priced_per_grounded_prompt():
    # 2.5 searched in every answer; 3.8 in about 1 in 4 (findings-slice5).
    assert GeminiGroundingAdapter(client=object()).cost(RAW) == 35_303
````

with:

````python
def test_default_engine_is_the_slice_56_pick_and_has_a_price():
    # The declared default, not get_settings(), which follows .env.
    default = Settings.model_fields["engine_model"].default
    assert default == "gemini-3.5-flash-lite"
    assert default in PRICES
````

In `tests/integration/test_full_flow.py` (`CannedGemini.__init__`), replace this block (it occurs exactly once and ends on a whole line):

````python
    def __init__(self):
        super().__init__(client=object())
````

with:

````python
    def __init__(self):
        # Pinned: the cost asserted below is gemini-2.5-flash's price.
        super().__init__(client=object(), model="gemini-2.5-flash")
````

- [ ] **Step 2: Run them to verify the new test fails**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice56 && uv run pytest -q -p no:cacheprovider tests/unit/test_gemini_adapter.py tests/integration/test_full_flow.py`
Expected (proof): `1 failed, 21 passed` — `test_default_engine_is_the_slice_56_pick_and_has_a_price`.

- [ ] **Step 3: Implement**

In `packages/core/bsi_core/config.py` (the engine model), replace this block (it occurs exactly once and ends on a whole line):

````python
    # 2.5 searched in 80 of 80 answers; 3.8 in about 1 in 4, so most of its
    # answers had no citations (findings-slice2 §7, findings-slice5 §1).
    engine_model: str = "gemini-2.5-flash"
````

with:

````python
    # gemini-2.5-flash retires 2026-10-20. Slice 56's probe on the 20 Run 1
    # prompts (2026-10-08): 3.5-flash-lite searched 20 of 20 at a mean
    # $0.0300 per observation; 3.1-flash-lite 20 of 20 at $0.0537;
    # 3.8-flash 6 of 20 (findings-slice56).
    engine_model: str = "gemini-3.5-flash-lite"
````

In `packages/core/bsi_core/config.py` (the estimate's comment), replace this block (it occurs exactly once and ends on a whole line):

````python
    daily_budget_usd: float = 2.0
    obs_cost_estimate_micros: int = 50_000
````

with:

````python
    daily_budget_usd: float = 2.0
    # Slice 56: max(50,000, the next multiple of 10,000 above the engine's
    # measured mean plus 2,000 for extraction) = max(50,000, 40,000).
    obs_cost_estimate_micros: int = 50_000
````

In `.env.example`, replace this block (it occurs exactly once and ends on a whole line):

````
ENGINE_MODEL=gemini-2.5-flash
````

with:

````
ENGINE_MODEL=gemini-3.5-flash-lite
````

The dev `.env` is not touched: the controller asks the user before changing its `ENGINE_MODEL`.

- [ ] **Step 4: Run the full backend suite**

Run: `cd /Users/vineet/Downloads/ADK/bsi-wt/slice56 && uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest -q -p no:cacheprovider --cov=bsi_core.metrics --cov-fail-under=100`
Expected (proof, a copy with no `.env`, so the new default applies): `184 files already formatted`, `All checks passed!`, `Success: no issues found in 31 source files`, `1776 passed, 2 deselected`, coverage 100%.

- [ ] **Step 5: Mutation table** (stage first: `git add -A packages tests .env.example`; restore each with `git checkout -- <file>`, confirm an empty `git diff -- <file>`)

| Mutant | Change | Tests | Proof |
|---|---|---|---|
| M15 | `engine_model` default left at `"gemini-2.5-flash"` | test_gemini_adapter | 1 failed (`test_default_engine_is_the_slice_56_pick_and_has_a_price`) |
| M16 | the `gemini-3.5-flash-lite` `PRICES` row deleted | test_gemini_adapter | 2 failed (the default-engine test and the 3.5-flash-lite price test) |
| M17 | `CannedGemini` unpinned (`super().__init__(client=object())`) | test_full_flow | 1 failed (`test_prompt_to_metric`) in a tree with no `.env` |

- [ ] **Step 6: Commit**

```bash
cd /Users/vineet/Downloads/ADK/bsi-wt/slice56 && git add packages/core/bsi_core/config.py .env.example tests/unit/test_gemini_adapter.py tests/integration/test_full_flow.py && ! { git diff --cached -U0 | grep '^+' | grep -v -F 'Banned-word grep (must block the commit)' | grep -i -E 'guarantee|will rank|will appear|will be recommended|ensure|boost|#1([^0-9]|$)|top spot|dominat|certain'; } && git commit -F - <<'EOF' # Banned-word grep (must block the commit)
feat: the default engine becomes gemini-3.5-flash-lite (slice 56 probe)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

Addendum departures from the spec:
- 11. `obs_cost_estimate_micros` keeps 50,000 (the formula's result) and gains a comment showing the computation; the spec says it "becomes" the formula's value, which here is the current value.
- 12. M17 is caught only where `ENGINE_MODEL` is not set to `gemini-2.5-flash` (a worktree or CI with no `.env`); in the main checkout, whose dev `.env` still names 2.5-flash, the unpinned class would still pass.

---

## Departures from the spec

1. Spec Section 2 has both rules call `window_models`; the plan also adds one shared helper, `metrics.comparability(versions, models)`, used by both rules, so the reason text and the pipeline-first order live in one place.
2. Spec Section 1 describes the probe; the plan's script structures it as `probe_costs`, `reservation`, `must_stop`, `summarize`, `pick`, `call`, `report`, `run(..., write=...)` and `main`, with `run` taking an injected `sleep` and `write` for tests.
3. The stop is checked before every try, and a stop that lands between the tries of one call leaves that call unrecorded (it is neither completed nor failed); the call count for that model is then short, so the model is not picked, as the spec's step 1 requires for any model cut short.
4. The stop test builds its ledger with 30 earlier entries of 100,000 micros and one non-probe entry, to show both that earlier `engine_probe:` entries count and that other kinds do not.
5. Spec Section 3's test list has one `summarize` test the spec does not name (`test_summarize_counts_failed_calls_as_not_searched`); the proof showed mutant M7 survived without it.
6. The impact test sets models by `requested_at` equality on the two seeded windows rather than adding a parameter to `seed()`.
7. Task 2 is an addendum after the probe (R4), not written now.
8. Spec Section 1 says each call records the final try's raw response; the script writes the raw response only for a completed call (a failed call may have no payload).
9. A failed call's record holds only `ok` and `error`; its tries' costs appear in the ledger-based total probe spend, not in the call record.
10. `probe_costs` skips blank ledger lines and reads `kind` with `.get`, beyond what the spec states, so a stray blank line cannot crash the stop check (mutant M14).

## Changes made during execution

(filled by the post-merge docs commit)
