"""Compare candidate engine models before gemini-2.5-flash retires
(slice-56 spec, Section 1).

One grounded call per prompt per model on the prompts of eval/run1.json,
interleaved per prompt in MODELS order. Run it with the main checkout's
.env sourced and RAW_STORE_DIR set to its data/ directory, so the spend
ledger is the canonical one:

usage: python scripts/engine_probe.py
Raw answers go to $RAW_STORE_DIR/experiments/engine/ (git-ignored);
results to eval/results/engine_probe_v0.json. Every try is spend-guarded.

A re-run refuses to start while those outputs exist: move them first.
probe_spend_micros in the results is the total of every engine_probe
ledger entry (earlier runs and failed tries included, the number the stop
uses); run_spend_micros is what this run recorded. An unexpected error
writes the partial results (stopped: "error") and re-raises. A null
spend number in any results means the ledger had a line that is not
valid JSON or lacks micros; the ledger stays the record. A write that
itself fails replaces the original error, which stays as its __context__.
Ctrl-C writes nothing.
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


def existing_outputs(out: Path, raw_dir: Path, models) -> list[Path]:
    """The results file and the models' raw directories an earlier run
    left; a re-run would overwrite them."""
    return [p for p in (out, *(raw_dir / m for m in models)) if p.exists()]


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


def report(calls, ledger, stopped, before):
    results = {m: summarize(c) for m, c in calls.items()}
    try:
        total = sum(probe_costs(ledger))
    except (ValueError, KeyError):  # a malformed ledger line
        total = None
    return {
        "models": list(calls),
        "results": results,
        "calls": calls,
        "probe_spend_micros": total,
        "run_spend_micros": None if total is None else total - before,
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
    written on the probe stop, the spend cap and an unexpected error."""
    calls: dict[str, list[dict]] = {m: [] for m in adapters}
    before = sum(probe_costs(ledger))
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
        write(report(calls, ledger, "spend cap", before))
        raise
    except Exception:
        write(report(calls, ledger, "error", before))
        raise
    out = report(calls, ledger, stopped, before)
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
    raw_dir = Path(settings.raw_store_dir) / "experiments" / "engine"
    left = existing_outputs(OUT, raw_dir, MODELS)
    if left:
        raise SystemExit(
            "earlier probe outputs exist: "
            + ", ".join(str(p) for p in left)
            + "; move them first so a re-run does not overwrite them"
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

    def write(out: dict) -> None:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(out, indent=1))
        print("wrote", OUT, "| stopped:", out["stopped"], flush=True)
        print("pick:", out["pick"], flush=True)

    run(adapters, run1["prompts"], entities, ledger, raw_dir, write=write)


if __name__ == "__main__":
    main()
