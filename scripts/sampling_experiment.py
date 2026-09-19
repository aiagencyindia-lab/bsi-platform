"""Compare sampling designs on cost vs interval (slice-2 spec §6).

A: 3 grounded samples per prompt. B: 1 grounded + 2 ungrounded resamples
seeded with the grounded answer's source domains. C: 2 grounded samples.
Designs run independently on the prompts of eval/run1.json.

usage: python scripts/sampling_experiment.py [--designs A,B,C] [--workers 4]
Raw answers go to data/experiments/ (git-ignored). Every call is
spend-guarded.
"""

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bsi_core import spend
from bsi_core.matching import Entity, find_mentions, normalize_domain
from bsi_core.metrics import rate
from bsi_core.providers.gemini import GeminiGroundingAdapter
from google import genai
from google.genai import types

DESIGNS = {"A": (3, 0), "B": (1, 2), "C": (2, 0)}  # (grounded, resampled)
ESTIMATE = {True: 60_000, False: 25_000}  # conservative micros per call
_DOMAIN = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,24}\b", re.I)


def ask(adapter, prompt, grounded, context, design, tag):
    for attempt in range(3):
        est = ESTIMATE[grounded]
        spend.check(est)  # SpendCapReached propagates and stops the run
        r, cost = None, 0
        try:
            r = adapter.query(
                prompt, "IN", "en", grounded=grounded, context=context
            )
            cost = r.cost_micros
        finally:
            spend.record(f"sampling:{design}", cost, release=est)
        if r.kind == "ok":
            path = Path("data/experiments") / design / f"{tag}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(r.raw))
            return r
        print(design, tag, r.kind, r.error, flush=True)
        if r.kind == "fatal":
            break
        time.sleep(15 * (attempt + 1))
    return None


def searched(raw):
    """True when the answer ran at least one Google Search query (R3)."""
    meta = GeminiGroundingAdapter._candidate(raw).get("grounding_metadata")
    return bool((meta or {}).get("web_search_queries"))


def run_prompt(adapter, design, pi, prompt):
    grounded_n, resampled_n = DESIGNS[design]
    out = {
        "answers": [],
        "cost": 0,
        "missing": 0,
        "grounded": 0,
        "searched": 0,
        "resampled": 0,
        "outside": 0,
        "no_seeds": False,
    }
    seeds: list[str] = []
    for i in range(grounded_n):
        r = ask(adapter, prompt, True, None, design, f"p{pi}-g{i}")
        if r is None:
            out["missing"] += 1
            continue
        out["cost"] += r.cost_micros
        parsed = adapter.parse(r.raw)
        out["answers"].append(parsed.text)
        out["grounded"] += 1
        out["searched"] += searched(r.raw)
        seeds = seeds or list(dict.fromkeys(d for _, d in parsed.citations))
    if resampled_n:
        # ponytail: resamples still run when the seed answer cited nothing;
        # they are counted in b_prompts_without_seeds.
        out["no_seeds"] = not seeds
    for i in range(resampled_n):
        context = (
            "Answer using what these search results say. Sources: "
            + ", ".join(seeds)
        )
        r = ask(adapter, prompt, False, context, design, f"p{pi}-r{i}")
        if r is None:
            out["missing"] += 1
            continue
        out["cost"] += r.cost_micros
        text = adapter.parse(r.raw).text
        out["answers"].append(text)
        out["resampled"] += 1
        cited = {normalize_domain(d) for d in _DOMAIN.findall(text)}
        out["outside"] += bool(cited - set(seeds))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--designs", default="A,B,C")
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args()
    run = json.loads(Path("eval/run1.json").read_text())
    prompts = run["prompts"]
    competitors = [
        Entity(c["name"], "competitor", (c["name"], *c["aliases"]))
        for c in run["competitors"]
    ]
    # Build the client up front: the adapter's lazy init races across
    # threads, and a replaced client is closed while still in use.
    client = genai.Client(http_options=types.HttpOptions(timeout=120_000))
    adapter = GeminiGroundingAdapter(client)

    report = {}
    for design in a.designs.split(","):
        with ThreadPoolExecutor(a.workers) as pool:
            per = list(
                pool.map(
                    lambda j, d=design: run_prompt(adapter, d, *j),
                    enumerate(prompts),
                )
            )
        answers = [t for o in per for t in o["answers"]]
        total = {
            k: sum(o[k] for o in per)
            for k in (
                "cost",
                "missing",
                "grounded",
                "searched",
                "resampled",
                "outside",
                "no_seeds",
            )
        }
        n = len(answers)
        report[design] = {
            "answers": n,
            "missing": total["missing"],
            "cost_micros": total["cost"],
            "cost_per_prompt_usd": total["cost"] / 1e6 / len(prompts),
            "grounded_share": rate(total["searched"], total["grounded"]),
            "rates": {
                c.id: rate(
                    sum(
                        any(
                            h.entity_id == c.id
                            for h in find_mentions(t, competitors)
                        )
                        for t in answers
                    ),
                    n,
                )
                for c in competitors
            },
            "resampled_citing_outside_seeds": rate(
                total["outside"], total["resampled"]
            )
            if total["resampled"]
            else None,
            "b_prompts_without_seeds": total["no_seeds"]
            if DESIGNS[design][1]
            else None,
        }
        print(
            design,
            json.dumps(
                {k: v for k, v in report[design].items() if k != "rates"}
            ),
            flush=True,
        )

    if "A" in report:
        base = report["A"]["rates"]
        for r in report.values():
            r["inside_A_interval"] = {
                c: base[c]["ci_low"] <= v["value"] <= base[c]["ci_high"]
                for c, v in r["rates"].items()
                if v["value"] is not None and base[c]["value"] is not None
            }
        qualified = [
            d for d, r in report.items() if all(r["inside_A_interval"].values())
        ]
        report["recommended"] = min(
            qualified, key=lambda d: report[d]["cost_per_prompt_usd"]
        )
    out = Path("eval/results/sampling_v0.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1))
    print(
        "wrote",
        out,
        "| slice spend so far: $%.2f"
        % (
            (
                spend.ledger_micros()
                + spend.db_micros(spend.get_settings().spend_since)
            )
            / 1e6
        ),
    )


if __name__ == "__main__":
    main()
