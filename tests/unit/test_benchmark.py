import json
from pathlib import Path

from bsi_core.matching import Entity, find_mentions

ROWS = [
    json.loads(line)
    for line in Path("eval/benchmark_v0.jsonl").read_text().splitlines()
    if line.strip()
]


def test_benchmark_is_reviewed_and_big_enough():
    assert len(ROWS) >= 30
    assert all(r["reviewed"] for r in ROWS)


def test_matcher_precision_and_recall():
    tp = fp = fn = 0
    for row in ROWS:
        entities = [
            Entity(e["id"], e["type"], tuple(e["aliases"]))
            for e in row["entities"]
        ]
        predicted = {h.entity_id for h in find_mentions(row["text"], entities)}
        expected = set(row["expected"])
        tp += len(predicted & expected)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
    assert tp / (tp + fp) >= 0.95, f"precision {tp}/{tp + fp}"
    assert tp / (tp + fn) >= 0.95, f"recall {tp}/{tp + fn}"
