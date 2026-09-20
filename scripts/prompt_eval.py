"""Prompt generation eval: three brands, one 50-prompt set each.

usage: set -a && source .env && set +a && uv run python scripts/prompt_eval.py
Writes eval/results/prompt_gen_v0.json. Every paid call is spend-guarded.

This runs the production path - `build_prompt_request`, `clean_prompts`,
`embed`, `dedupe` from `bsi_core.suggest` - without a database, so what
it measures is what a suggestion job would produce.
"""

import argparse
import json
import statistics
import time
from collections import Counter
from math import ceil
from pathlib import Path
from typing import Any

from bsi_core import spend
from bsi_core.judge import generate
from bsi_core.labels import key
from bsi_core.suggest import (
    DUPLICATE_THRESHOLD,
    OVERSHOOT,
    PromptContext,
    PromptSet,
    build_prompt_request,
    clean_prompts,
    cosine,
    dedupe,
    embed,
)

# Three categories, deliberately unlike each other: the probe's kids
# footwear (so the numbers are comparable with findings §1), a B2B SaaS
# where the buyer is not a shopper, and an Indian D2C brand.
BRANDS = [
    PromptContext(
        brand="BSOAgentTestBrand",
        aliases=("BSO Agent Test Brand",),
        category="kids footwear",
        locale="en-IN",
    ),
    PromptContext(
        brand="Northwind CRM",
        aliases=("Northwind",),
        category="B2B SaaS CRM software",
        locale="en-US",
    ),
    PromptContext(
        brand="Vanaspati Glow",
        aliases=("Vanaspati",),
        category="D2C ayurvedic skincare",
        locale="en-IN",
    ),
]
# Reservations, not prices: released and replaced by the real cost.
GEN_ESTIMATE_MICROS = 80_000
EMBED_ESTIMATE_MICROS = 10_000
# 0.88 and 0.90 bracket the threshold; 0.92 is the one in use.
THRESHOLDS = (0.85, 0.88, 0.90, DUPLICATE_THRESHOLD, 0.95)


def guarded(kind: str, estimate: int, fn: Any) -> Any:
    """Run a paid call under the spend guard; fn returns (value, cost)."""
    spend.check(estimate)
    cost = 0
    try:
        value, cost = fn()
        return value
    finally:
        spend.record(f"prompt_eval:{kind}", cost, release=estimate)


def pairwise(vectors: list[list[float]]) -> list[tuple[float, int, int]]:
    """(similarity, i, j) for every unordered pair, in index order."""
    return [
        (cosine(vectors[i], vectors[j]), i, j)
        for i in range(len(vectors))
        for j in range(i + 1, len(vectors))
    ]


def summarize(sims: list[float]) -> dict[str, Any]:
    """Spread and threshold counts. Same statistics as the step-0 probe."""
    if len(sims) < 2:
        return {"n_pairs": len(sims)}
    ordered = sorted(sims)
    q = statistics.quantiles(ordered, n=100)
    return {
        "n_pairs": len(ordered),
        "min": round(ordered[0], 4),
        "median": round(statistics.median(ordered), 4),
        "p90": round(q[89], 4),
        "p99": round(q[98], 4),
        "max": round(ordered[-1], 4),
        "at_or_above": {
            f"{t:g}": sum(s >= t for s in ordered) for t in THRESHOLDS
        },
    }


def run_one(ctx: PromptContext, count: int) -> dict[str, Any]:
    asked = ceil(count * OVERSHOOT)
    request = build_prompt_request(ctx, asked)
    started = time.monotonic()
    raw, gen_cost, model = guarded(
        "generate",
        GEN_ESTIMATE_MICROS,
        lambda: ((r := generate(request, PromptSet, 1.0)), r[1]),
    )
    seconds = round(time.monotonic() - started, 2)
    parsed = PromptSet.model_validate_json(raw)
    brand_keys = {key(n) for n in (ctx.brand, *ctx.aliases)} - {""}
    cleaned = clean_prompts(parsed, (), brand_keys)

    embed_started = time.monotonic()
    texts = [p.text for p in cleaned]
    vectors, embed_cost = guarded(
        "embed",
        EMBED_ESTIMATE_MICROS,
        lambda: ((v := embed(texts)), v[1]),
    )
    embed_seconds = round(time.monotonic() - embed_started, 2)

    pairs = pairwise(vectors)
    kept = dedupe(vectors, DUPLICATE_THRESHOLD)
    dropped = len(cleaned) - len(kept)
    return {
        "brand": ctx.brand,
        "category": ctx.category,
        "locale": ctx.locale,
        "model": model,
        "asked": asked,
        "wanted": count,
        "returned": len(parsed.prompts),
        "seconds_generate": seconds,
        "seconds_embed": embed_seconds,
        "seconds_total": round(seconds + embed_seconds, 2),
        "cost_micros": {
            "generate": gen_cost,
            "embed": embed_cost,
            "total": gen_cost + embed_cost,
        },
        # clean_prompts drops blanks, over-long text, a bad intent, an
        # exact repeat, and anything naming the brand.
        "rejected_by_clean": len(parsed.prompts) - len(cleaned),
        "candidates": len(cleaned),
        "near_duplicates": dropped,
        "near_duplicate_rate": round(dropped / len(cleaned), 4)
        if cleaned
        else 0.0,
        "post_dedupe": len(kept),
        # A job writes at most `count`, however many survive.
        "would_write": min(len(kept), count),
        "intents": dict(Counter(p.intent for p in cleaned).most_common()),
        "topics": dict(Counter(p.topic for p in cleaned).most_common()),
        "similarity": summarize([s for s, _, _ in pairs]),
        "closest_pairs": [
            {
                "sim": round(s, 4),
                "a": cleaned[i].text,
                "b": cleaned[j].text,
                "dropped": j not in kept,
            }
            for s, i, j in sorted(pairs, reverse=True)[:10]
        ],
        "prompts": [p.model_dump() for p in cleaned],
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--count", type=int, default=50)
    p.add_argument(
        "--out", default="eval/results/prompt_gen_v0.json", type=Path
    )
    a = p.parse_args()

    results = []
    for ctx in BRANDS:
        print(f"== {ctx.brand} ({ctx.category})")
        row = run_one(ctx, a.count)
        results.append(row)
        print(
            f"  {row['returned']} returned, {row['candidates']} clean, "
            f"{row['post_dedupe']} after dedupe in {row['seconds_total']}s "
            f"for {row['cost_micros']['total']} micros"
        )
        print(f"  near-duplicate rate {row['near_duplicate_rate']:.1%}")
        print(f"  intents {row['intents']}")
        print(f"  topics {sorted(row['topics'])}")
        print(f"  similarity {json.dumps(row['similarity'])}")

    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(
        json.dumps(
            {"threshold": DUPLICATE_THRESHOLD, "brands": results},
            indent=1,
            default=str,
        )
    )
    total = spend.ledger_micros() + spend.db_micros(
        spend.get_settings().spend_since
    )
    print(f"wrote {a.out} | slice spend so far: ${total / 1e6:.2f}")


if __name__ == "__main__":
    main()
