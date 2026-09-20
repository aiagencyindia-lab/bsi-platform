"""Build eval/rec_labels_v0.jsonl from benchmark_v0: one row per benchmark
row, with each matcher-confirmed entity awaiting a hand rec_status label.

usage: python scripts/export_rec_labels.py > eval/rec_labels_v0.jsonl
       python scripts/export_rec_labels.py --from-db "Org name"
"""

import json
import sys
import uuid
from pathlib import Path


def from_benchmark() -> None:
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


def from_db(org_name: str) -> None:
    from bsi_core import models as m
    from bsi_core.db import owner_engine
    from bsi_core.providers.gemini import GeminiGroundingAdapter
    from bsi_core.storage import LocalRawStore
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    with Session(owner_engine()) as s:
        org = s.scalars(
            select(m.Organization).where(m.Organization.name == org_name)
        ).one()
        labels = s.scalars(
            select(m.RecLabel)
            .where(m.RecLabel.org_id == org.id)
            .order_by(m.RecLabel.observation_id, m.RecLabel.created_at)
        ).all()
        by_obs: dict[uuid.UUID, list[m.RecLabel]] = {}
        for lb in labels:
            by_obs.setdefault(lb.observation_id, []).append(lb)
        for obs_id, rows in by_obs.items():
            obs = s.get_one(m.Observation, obs_id)
            raw = LocalRawStore().get(obs.raw_uri, org.id)
            entities, expected = [], {}
            for lb in rows:
                model = m.Brand if lb.entity_type == "brand" else m.Competitor
                e = s.get(model, lb.entity_id)
                if e is None:
                    # The entity (almost always a competitor) was deleted
                    # after being labelled. Skip it rather than aborting
                    # the whole export over one stale row.
                    continue
                entities.append(
                    {
                        "id": e.name,
                        "type": lb.entity_type,
                        "aliases": [e.name, *e.aliases],
                    }
                )
                expected[e.name] = lb.label
            print(
                json.dumps(
                    {
                        "observation_id": str(obs_id),
                        "text": GeminiGroundingAdapter().parse(raw).text,
                        "entities": entities,
                        "expected": expected,
                        "reviewed": True,
                    },
                    ensure_ascii=False,
                )
            )


def main() -> None:
    if sys.argv[1:2] == ["--from-db"]:
        if len(sys.argv) < 3:
            sys.exit("usage: export_rec_labels.py --from-db ORG_NAME")
        from_db(sys.argv[2])
    else:
        from_benchmark()


if __name__ == "__main__":
    main()
