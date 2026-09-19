"""Judge robustness: injection resistance and clean-label agreement.

usage: python scripts/judge_eval.py --mode legacy|batched|isolated \
           [--repeats 10] [--workers 4]
Writes eval/results/judge_eval_<mode>.json. Every call is spend-guarded.
"""

import argparse
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bsi_core import spend
from bsi_core.extraction import apply_sanity
from bsi_core.judge import JUDGES, legacy_judge
from bsi_core.labels import combine, select_sentences
from bsi_core.matching import Entity, find_mentions
from bsi_core.metrics import rate

INJECTION_ENTITIES = [
    Entity("nike", "brand", ("Nike",)),
    Entity("adidas", "competitor", ("Adidas",)),
    Entity("puma", "competitor", ("Puma",)),
    Entity("skechers", "competitor", ("Skechers",)),
]
CALL_ESTIMATE_MICROS = 2_000  # conservative per judge call


def load(name):
    return [
        json.loads(line)
        for line in Path(f"eval/{name}").read_text().splitlines()
        if line.strip()
    ]


def entities_of(row):
    if "entities" not in row:
        return INJECTION_ENTITIES
    return [
        Entity(e["id"], e["type"], tuple(e["aliases"])) for e in row["entities"]
    ]


def label(mode, text, entities):
    """Return ({entity_id: rec_status}, cost_micros)."""
    names = [e.aliases[0] for e in entities]
    hits = find_mentions(text, entities)
    if mode == "legacy":
        out, cost = legacy_judge(text, names)
        rows, _ = apply_sanity(hits, entities, out)
    else:
        selected = select_sentences(text, entities)
        reply = JUDGES[mode](selected, names) if selected else None
        cost = reply.cost_micros if reply else 0
        rows, _, _ = combine(
            hits, entities, selected, reply.out if reply else None
        )
    return {r.entity.id: r.rec_status for r in rows}, cost


def estimate(mode, row):
    if mode == "isolated":
        n = len(select_sentences(row["text"], entities_of(row)))
        return CALL_ESTIMATE_MICROS * max(1, n)
    return CALL_ESTIMATE_MICROS


def trial(mode, row):
    est = estimate(mode, row)
    spend.check(est)  # SpendCapReached propagates and stops the run
    got, cost, err = None, 0, None
    try:
        got, cost = label(mode, row["text"], entities_of(row))
    except Exception as e:  # counted as a miss, reported separately
        err = repr(e)[:200]
        cost = getattr(e, "cost_micros", 0)
    finally:
        spend.record(f"judge_eval:{mode}", cost, release=est)
    return got, cost, err


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--mode", required=True, choices=["legacy", "batched", "isolated"]
    )
    p.add_argument("--repeats", type=int, default=10)
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args()

    results = {}
    for set_name in ("injection_v0.jsonl", "rec_labels_v0.jsonl"):
        rows = load(set_name)
        jobs = [(r, i) for r in rows for i in range(a.repeats)]
        with ThreadPoolExecutor(a.workers) as pool:
            outcomes = list(pool.map(lambda j: trial(a.mode, j[0]), jobs))
        passed = agree = pairs = errors = cost = 0
        misses = []
        by_id = {str(r.get("id", r.get("observation_id"))): r for r in rows}
        confusion = Counter()  # want->got over every pair
        row_agree = Counter()
        for (row, _), (got, c, err) in zip(jobs, outcomes, strict=True):
            cost += c
            if err:
                errors += 1
            ok_all = True
            for entity_id, want in row["expected"].items():
                pairs += 1
                have = got.get(entity_id) if got is not None else None
                ok = have == want
                agree += ok
                confusion[f"{want}->{have}"] += 1
                row_agree[str(row.get("id", row.get("observation_id")))] += ok
                ok_all &= ok
            passed += ok_all
            if not ok_all and len(misses) < 20:
                misses.append(
                    {
                        "row": row.get("id", row.get("observation_id")),
                        "got": got,
                        "want": row["expected"],
                        "error": err,
                    }
                )
        results[set_name] = {
            "trials": len(jobs),
            "all_entities_correct": rate(passed, len(jobs)),
            "entity_agreement": rate(agree, pairs),
            "errors": errors,
            "cost_micros": cost,
            "confusion": dict(confusion.most_common()),
            "row_agreement": {
                r: n / (a.repeats * len(by_id[r]["expected"]))
                for r, n in row_agree.most_common()
            },
            "misses": misses,
        }
        print(
            set_name,
            json.dumps(
                {
                    k: v
                    for k, v in results[set_name].items()
                    if k not in ("misses", "row_agreement")
                }
            ),
        )
    out = Path(f"eval/results/judge_eval_{a.mode}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=1, default=str))
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
