"""Build eval/rec_labels_v0.jsonl from benchmark_v0: one row per benchmark
row, with each matcher-confirmed entity awaiting a hand rec_status label.

usage: python scripts/export_rec_labels.py > eval/rec_labels_v0.jsonl
"""

import json
from pathlib import Path

for line in Path("eval/benchmark_v0.jsonl").read_text().splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    print(
        json.dumps(
            {
                "observation_id": row["observation_id"],
                "text": row["text"],
                "entities": row["entities"],
                "expected": {e: "TO_LABEL" for e in row["expected"]},
                "reviewed": False,
            },
            ensure_ascii=False,
        )
    )
