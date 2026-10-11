# Slice 61 design: the slice 56 engine probe's deferred minors

Classification: architectural, said first in chat on 2026-10-11, before the first question: the probe script already exists, which the skill would call bounded, but this project gives every slice a spec and a plan and the ten minors had not been read yet, so the heavier path was taken. Session model Sonnet 5.5 for the brainstorm, the approaches, the proof and this spec; implementation and reviews on Opus 5.5 (every dispatch passes `model: opus`).

## Context

"Fix every item" (user, 2026-10-09) was split into four slices: 59 behaviour (merged), 60 test hardening (merged, PRs #120 and #121, main e2b2b8b), 61 the slice 56 probe script's minors (this one), 62 the docs sweep. The ten deferred minors are docs/findings-slice56.md lines 141 to 150 (as at main e2b2b8b), grouped by what they ask for:

- Tests (3): 142 (the `.get("kind", "")` half of departure 10 is untested), 143 (the per-call fields `call()` builds are never asserted; a mutant `"searched": True` survives), 146 (the stop test's patched `record` opens the ledger without closing it).
- Script behaviour (2): 144 (an exception other than `Stop` or `SpendCapReached` ends the run without partial results), 145 (`probe_spend_micros` totals every earlier run while the results cover this run, and a re-run overwrites the raw files and the results file).
- Comment (1): 150 (the `obs_cost_estimate_micros` comment does not repeat the measured mean, 30,039.5).
- Docs (4): 141 (M14's proof cell), 147 and 148 (plan departures 7, 11 and 12), 149 (the `config.py` comment cites findings-slice56, added by the docs PR after the code PR; that file exists now, so the line is already true). These are slice 62's.

The script ran once on 2026-10-08 and picked `gemini-3.5-flash-lite`; its record is `eval/results/engine_probe_v0.json`. Nothing outside its own tests imports it, and it carries that day's constants (the ledger floor 6,858,204, the $3.50 stop, the retirement dates). The slice spends nothing: no Gemini, no DataForSEO, no worker, and `engine_probe.py` itself is not run.

Assumption, stated in chat before the first question and not changed by the user's next answer: the six script-side items (142, 143, 144, 145, 146, 150) are this slice's scope and 141, 147, 148, 149 stay in slice 62.

User decisions (2026-10-11), with the approaches text shown in chat before each:
1. Item 145, a re-run: refuse by default (the probe exits before spending when the results file or a model's raw directory exists; the report gains `run_spend_micros` beside the cumulative `probe_spend_micros`), over a per-run output and over documenting the overwrite only.
2. Item 144, an unexpected exception: write the partial results with `stopped: "error"` and re-raise, over continuing as a failed call and over documenting only.
3. Sections 1 to 4 each approved ("Yes, go on" for 1 to 3, "Yes, write the spec" for 4) after their text was shown in chat.

## Section 1 — The script (144 and 145)

All of it in scripts/engine_probe.py.

- A new `existing_outputs(out, raw_dir, models)` returns the paths among the results file and `raw_dir/<model>` for each model that already exist. `main()` calls it right after the ledger-floor check, before it reads `eval/run1.json`, builds the client or makes any call, and exits with `SystemExit` naming the paths and saying to move them first.
- `run()` reads `sum(probe_costs(ledger))` once at the start and passes it to `report()`. The report keeps `probe_spend_micros` (the cumulative total, the number the stop uses) and gains `run_spend_micros`, the cumulative total minus the start value.
- `run()` gains `except Exception:` after the `Stop` and `SpendCapReached` branches (`SpendCapReached` is a `RuntimeError`, so the order matters): it writes `report(..., "error", before)` and re-raises. A Ctrl-C is not an `Exception`, so it writes nothing; the docstring says so.
- The pick rule, the stop, the pricing, the models and the constants do not change. The module docstring gains a paragraph on the re-run refusal, the two spend numbers and the exception behaviour.

## Section 2 — The tests (142, 143, 146, and the proofs for 144 and 145)

All of them in tests/unit/test_engine_probe.py.

- `test_probe_costs_reads_only_engine_probe_entries` (142): a ledger with an `engine_probe:x` row, a row with no `kind`, a blank line and a `sampling:A` row yields `[100_000]`; the mutant `r["kind"]` raises a `KeyError`.
- `FakeAdapter` takes `search_queries` (default `None`, so the existing tests are unchanged), returns `thoughts_token_count` 5 in its usage, and a reply that names Bata twice and Campus once.
- `test_a_call_records_what_was_searched_and_counted` and `test_a_call_with_no_search_queries_is_not_searched` (143) call `call()` directly with the spend functions patched as the stop test does: with `search_queries=2` the dict is `ok`, `searched` true, `queries` 2, `cost` 7,000, `tokens_in` 10, `tokens_out` 25, `brands` 2 and a non-negative float `latency`; with `None`, `searched` false and `queries` 0. An exact latency is not asserted, since patching `time.monotonic` would patch it for pytest too.
- A shared `_recorder(ledger)` writes the ledger inside a `with` block; the stop test uses it (146) and asserts `run_spend_micros == 480_000` beside `probe_spend_micros == 3_480_000`.
- `test_the_probe_writes_partial_results_on_an_unexpected_error` (144): `spend.check` raises `OSError` on its second call; `run()` re-raises `OSError`, `write` is called once with `stopped == "error"`, and the first model's one completed call is in the results.
- `test_existing_outputs_names_what_a_rerun_would_overwrite` and `test_a_rerun_refuses_to_start_while_outputs_exist` (145): the first on an empty and then a populated directory; the second runs `main()` with `get_settings`, `spend.ledger_micros` (6,858,204) and `spend.db_micros` patched, in a temporary directory that already holds the results file, and expects `SystemExit` naming the file; `genai.Client` fails the test if it is built, so nothing can be spent.

## Section 3 — The comment (150) and what stays out

- In packages/core/bsi_core/config.py the `obs_cost_estimate_micros` comment names the measured mean: "measured mean (30,039.5 micros, gemini-3.5-flash-lite in the probe) plus 2,000 for extraction". 30,039.5 + 2,000 = 32,039.5, and the next multiple of 10,000 above it is 40,000, so the value and the arithmetic are unchanged. The `engine_model` comment already gives the $0.0300 figure and stays.
- Out of scope: 141, 147, 148 and 149 (slice 62), the probe's constants, and every production behaviour other than the script's own re-run refusal.

## Section 4 — Testing

- Red: four tests fail against main's script: `test_the_probe_stops_before_the_crossing_try` (no `run_spend_micros`), the unexpected-error test, the `existing_outputs` test and the refusal test (15 pass: the items asking for stronger tests of code that is already right are covered by the mutation table).
- Green: tests/unit/test_engine_probe.py 13 → 19 passed; the whole backend 1809 passed, 2 deselected, 2 warnings, metrics coverage 100.00%, ruff and mypy clean. No web change (91 vitest unchanged), no generated file.
- No live check: the script is not run and nothing is called.

## The change

Generated from the proof (a scratchpad copy of main e2b2b8b with the change applied), as a unified diff over the three files:

```diff
--- a/scripts/engine_probe.py
+++ b/scripts/engine_probe.py
@@ -9,6 +9,13 @@
 usage: python scripts/engine_probe.py
 Raw answers go to $RAW_STORE_DIR/experiments/engine/ (git-ignored);
 results to eval/results/engine_probe_v0.json. Every try is spend-guarded.
+
+A re-run refuses to start while those outputs exist: move them first.
+probe_spend_micros in the results is the total of every engine_probe
+ledger entry (earlier runs and failed tries included, the number the stop
+uses); run_spend_micros is what this run recorded. An unexpected error
+writes the partial results (stopped: "error") and re-raises; Ctrl-C does
+not write them.
 """
 
 import json
@@ -55,6 +62,12 @@
     ]
 
 
+def existing_outputs(out: Path, raw_dir: Path, models) -> list[Path]:
+    """The results file and the models' raw directories an earlier run
+    left; a re-run would overwrite them."""
+    return [p for p in (out, *(raw_dir / m for m in models)) if p.exists()]
+
+
 def reservation(costs: list[int]) -> int:
     return max([FLOOR_MICROS, *costs])
 
@@ -153,13 +166,15 @@
     return {"ok": False, "error": result.error if result else None}
 
 
-def report(calls, ledger, stopped):
+def report(calls, ledger, stopped, before):
     results = {m: summarize(c) for m, c in calls.items()}
+    total = sum(probe_costs(ledger))
     return {
         "models": list(calls),
         "results": results,
         "calls": calls,
-        "probe_spend_micros": sum(probe_costs(ledger)),
+        "probe_spend_micros": total,
+        "run_spend_micros": total - before,
         "stopped": stopped,
         "pick": pick(results),
     }
@@ -177,6 +192,7 @@
     """Every model on prompt 0, then prompt 1, ...; partial results are
     written on either stop."""
     calls: dict[str, list[dict]] = {m: [] for m in adapters}
+    before = sum(probe_costs(ledger))
     stopped = None
     try:
         for i, prompt in enumerate(prompts):
@@ -196,9 +212,12 @@
     except Stop:
         stopped = "probe stop"
     except spend.SpendCapReached:
-        write(report(calls, ledger, "spend cap"))
+        write(report(calls, ledger, "spend cap", before))
         raise
-    out = report(calls, ledger, stopped)
+    except Exception:
+        write(report(calls, ledger, "error", before))
+        raise
+    out = report(calls, ledger, stopped, before)
     write(out)
     return out
 
@@ -214,6 +233,14 @@
             f"ledger {ledger} reads {ledger_total} micros, below "
             f"{LEDGER_FLOOR}: not the canonical ledger"
         )
+    raw_dir = Path(settings.raw_store_dir) / "experiments" / "engine"
+    left = existing_outputs(OUT, raw_dir, MODELS)
+    if left:
+        raise SystemExit(
+            "earlier probe outputs exist: "
+            + ", ".join(str(p) for p in left)
+            + "; move them first so a re-run does not overwrite them"
+        )
     run1 = json.loads(Path("eval/run1.json").read_text())
     entities = [
         Entity(run1["brand"], "brand", (run1["brand"], *run1["aliases"]))
@@ -223,7 +250,6 @@
     ]
     client = genai.Client(http_options=types.HttpOptions(timeout=120_000))
     adapters = {m: GeminiGroundingAdapter(client, model=m) for m in MODELS}
-    raw_dir = Path(settings.raw_store_dir) / "experiments" / "engine"
 
     def write(out: dict) -> None:
         OUT.parent.mkdir(parents=True, exist_ok=True)
--- a/tests/unit/test_engine_probe.py
+++ b/tests/unit/test_engine_probe.py
@@ -3,7 +3,10 @@
 import importlib.util
 import json
 from pathlib import Path
+from types import SimpleNamespace
 
+import pytest
+from bsi_core.matching import Entity
 from bsi_core.metrics import rate
 from bsi_core.providers.base import EngineResult
 
@@ -97,23 +100,30 @@
 
 
 class FakeAdapter:
-    def __init__(self, cost):
+    def __init__(self, cost, search_queries=None):
         self.cost = cost
+        self.search_queries = search_queries
 
     def query(self, prompt, country, language, grounded=True):
         raw = {
             "candidates": [
                 {
-                    "content": {"parts": [{"text": "Bata and Campus"}]},
+                    "content": {"parts": [{"text": "Bata, Bata and Campus"}]},
                     "grounding_metadata": {"web_search_queries": ["q"]},
                 }
             ],
             "usage_metadata": {
                 "prompt_token_count": 10,
                 "candidates_token_count": 20,
+                "thoughts_token_count": 5,
             },
         }
-        return EngineResult("ok", raw=raw, cost_micros=self.cost)
+        return EngineResult(
+            "ok",
+            raw=raw,
+            cost_micros=self.cost,
+            search_queries=self.search_queries,
+        )
 
     def parse(self, raw):
         from bsi_core.providers.gemini import GeminiGroundingAdapter
@@ -121,6 +131,72 @@
         return GeminiGroundingAdapter(client=object()).parse(raw)
 
 
+def _recorder(ledger):
+    """A spend.record stand-in that appends to the ledger and closes it."""
+
+    def record(kind, micros, release=0):
+        with ledger.open("a") as f:
+            f.write(json.dumps({"kind": kind, "micros": micros}) + "\n")
+
+    return record
+
+
+ENTITIES = [
+    Entity("Bata", "brand", ("Bata",)),
+    Entity("Campus", "competitor", ("Campus",)),
+]
+
+
+def _call(tmp_path, monkeypatch, search_queries):
+    monkeypatch.setattr(engine_probe.spend, "check", lambda r: 0)
+    ledger = tmp_path / "ledger.jsonl"
+    monkeypatch.setattr(engine_probe.spend, "record", _recorder(ledger))
+    return engine_probe.call(
+        FakeAdapter(7_000, search_queries),
+        LITE,
+        3,
+        "p",
+        ENTITIES,
+        ledger,
+        tmp_path / "raw",
+        lambda s: None,
+    )
+
+
+def test_probe_costs_reads_only_engine_probe_entries(tmp_path):
+    ledger = tmp_path / "ledger.jsonl"
+    ledger.write_text(
+        json.dumps({"kind": "engine_probe:x", "micros": 100_000})
+        + "\n  \n"
+        + json.dumps({"micros": 5})  # no kind
+        + "\n"
+        + json.dumps({"kind": "sampling:A", "micros": 9_000_000})
+        + "\n"
+    )
+    assert engine_probe.probe_costs(ledger) == [100_000]
+
+
+def test_a_call_records_what_was_searched_and_counted(tmp_path, monkeypatch):
+    got = _call(tmp_path, monkeypatch, 2)
+    latency = got.pop("latency")
+    assert isinstance(latency, float) and latency >= 0
+    assert got == {
+        "ok": True,
+        "searched": True,
+        "queries": 2,
+        "cost": 7_000,
+        "tokens_in": 10,
+        "tokens_out": 25,  # candidates 20 + thoughts 5
+        "brands": 2,  # Bata twice and Campus once: two distinct entities
+    }
+    assert (tmp_path / "raw" / LITE / "p3.json").exists()
+
+
+def test_a_call_with_no_search_queries_is_not_searched(tmp_path, monkeypatch):
+    got = _call(tmp_path, monkeypatch, None)
+    assert (got["searched"], got["queries"]) == (False, 0)
+
+
 def test_the_probe_stops_before_the_crossing_try(tmp_path, monkeypatch):
     monkeypatch.setattr(engine_probe.spend, "check", lambda r: 0)
     ledger = tmp_path / "ledger.jsonl"
@@ -132,13 +208,7 @@
         + (json.dumps({"kind": "engine_probe:x", "micros": 100_000}) + "\n")
         * 30
     )
-    monkeypatch.setattr(
-        engine_probe.spend,
-        "record",
-        lambda kind, micros, release=0: ledger.open("a").write(
-            json.dumps({"kind": kind, "micros": micros}) + "\n"
-        ),
-    )
+    monkeypatch.setattr(engine_probe.spend, "record", _recorder(ledger))
     adapters = {m: FakeAdapter(120_000) for m in engine_probe.MODELS}
     written = []
     out = engine_probe.run(
@@ -160,6 +230,7 @@
         1,
     ]
     assert out["probe_spend_micros"] == 3_480_000
+    assert out["run_spend_micros"] == 480_000  # this run's four tries
     assert (tmp_path / "raw" / LITE / "p1.json").exists()
     assert engine_probe.pick(out["results"]) is None
 
@@ -187,3 +258,77 @@
     else:
         raise AssertionError("SpendCapReached was swallowed")
     assert [w["stopped"] for w in written] == ["spend cap"]
+
+
+def test_the_probe_writes_partial_results_on_an_unexpected_error(
+    tmp_path, monkeypatch
+):
+    seen = []
+
+    def check(r):
+        seen.append(r)
+        if len(seen) == 2:
+            raise OSError("disk")
+        return 0
+
+    monkeypatch.setattr(engine_probe.spend, "check", check)
+    ledger = tmp_path / "ledger.jsonl"
+    monkeypatch.setattr(engine_probe.spend, "record", _recorder(ledger))
+    written = []
+    adapters = {m: FakeAdapter(1, 1) for m in engine_probe.MODELS}
+    with pytest.raises(OSError, match="disk"):
+        engine_probe.run(
+            adapters,
+            ["p0"],
+            [],
+            ledger,
+            tmp_path / "raw",
+            sleep=lambda s: None,
+            write=written.append,
+        )
+    assert [w["stopped"] for w in written] == ["error"]
+    # The first model's call finished before the second try failed.
+    assert [written[0]["results"][m]["calls"] for m in engine_probe.MODELS] == [
+        1,
+        0,
+        0,
+    ]
+
+
+def test_existing_outputs_names_what_a_rerun_would_overwrite(tmp_path):
+    out = tmp_path / "results.json"
+    raw = tmp_path / "raw"
+    assert engine_probe.existing_outputs(out, raw, engine_probe.MODELS) == []
+    out.write_text("{}")
+    (raw / LITE).mkdir(parents=True)
+    assert engine_probe.existing_outputs(out, raw, engine_probe.MODELS) == [
+        out,
+        raw / LITE,
+    ]
+
+
+def test_a_rerun_refuses_to_start_while_outputs_exist(tmp_path, monkeypatch):
+    monkeypatch.chdir(tmp_path)
+    results = tmp_path / "eval" / "results"
+    results.mkdir(parents=True)
+    (results / "engine_probe_v0.json").write_text("{}")
+    monkeypatch.setattr(
+        engine_probe,
+        "get_settings",
+        lambda: SimpleNamespace(
+            raw_store_dir=str(tmp_path / "data"), spend_since=None
+        ),
+    )
+    monkeypatch.setattr(
+        engine_probe.spend, "ledger_micros", lambda ledger: 6_858_204
+    )
+    monkeypatch.setattr(engine_probe.spend, "db_micros", lambda since: 0)
+
+    def no_client(*args, **kwargs):
+        raise AssertionError("a client was built before the refusal")
+
+    monkeypatch.setattr(engine_probe.genai, "Client", no_client)
+    with pytest.raises(SystemExit) as refused:
+        engine_probe.main()
+    assert "engine_probe_v0.json" in str(refused.value)
+    assert "move them first" in str(refused.value)
--- a/packages/core/bsi_core/config.py
+++ b/packages/core/bsi_core/config.py
@@ -33,7 +33,8 @@
     # Slice 3: per-organization daily cap on scheduled runs (spec §3).
     daily_budget_usd: float = 2.0
     # Slice 56: max(50,000, the next multiple of 10,000 above the engine's
-    # measured mean plus 2,000 for extraction) = max(50,000, 40,000).
+    # measured mean (30,039.5 micros, gemini-3.5-flash-lite in the probe)
+    # plus 2,000 for extraction) = max(50,000, 40,000).
     obs_cost_estimate_micros: int = 50_000
     # Slice 6: days either side of a task's done_at that impact compares.
     # Copied onto the task when it is marked done, so changing it never
```

## Evidence

Proof directory: a fresh scratchpad copy of main e2b2b8b (`proof61-1791742833`), written only by the controller through an edit script with assert-counted replacements.

- Green, patched: tests/unit/test_engine_probe.py 19 passed; `ruff format` reformatted one file (the proof's own edit) and `ruff check` and `mypy` are clean; the whole backend 1809 passed, 2 deselected, 2 warnings with metrics coverage 100.00%.
- Red on main's script: 4 failed, 15 passed, as Section 4 says.

Mutations, each applied alone to the patched scripts/engine_probe.py and reverted, the whole test file run:

| # | Mutation | Result |
|---|---|---|
| M1 | `probe_costs` reads `r["kind"]` in place of `r.get("kind", "")` | killed: test_probe_costs_reads_only_engine_probe_entries (1 failed, 18 passed) |
| M2 | `call()` records `"searched": True` | killed: test_a_call_with_no_search_queries_is_not_searched (1 failed, 18 passed) |
| M3 | `tokens_out` drops the thoughts tokens | killed: test_a_call_records_what_was_searched_and_counted (1 failed, 18 passed) |
| M4 | `brands` counts every mention, not distinct entities | killed: test_a_call_records_what_was_searched_and_counted (1 failed, 18 passed) |
| M5 | the `except Exception` branch is removed | killed: test_the_probe_writes_partial_results_on_an_unexpected_error (1 failed, 18 passed) |
| M6 | `existing_outputs` always returns `[]` | killed: the `existing_outputs` test and the refusal test (2 failed, 17 passed) |
| M7 | `run_spend_micros` is the cumulative total | killed: test_the_probe_stops_before_the_crossing_try (1 failed, 18 passed) |
| M8 | `main()` skips the refusal (`if False:`) | killed: test_a_rerun_refuses_to_start_while_outputs_exist (1 failed, 18 passed) |

## Rulings

None yet.

## Out of scope

- 141, 147, 148 and 149 of findings-slice56 (slice 62).
- The probe's constants and models, and re-running the probe.

## Docs follow-ups

- Dated notes under findings-slice56.md lines 142, 143, 144, 145, 146 and 150 in the docs PR after the merge, and README rows for the spec, plan and findings.
