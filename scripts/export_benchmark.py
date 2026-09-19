"""Dump done observations as benchmark rows with the matcher's guess.

usage: python scripts/export_benchmark.py <brand_id> [limit] \
    > eval/benchmark_v0.jsonl
A person then corrects each row's "expected" list by reading "text".
"""

import json
import sys
import uuid

from bsi_core import models as m
from bsi_core.db import owner_engine
from bsi_core.matching import Entity, find_mentions
from bsi_core.providers.gemini import GeminiGroundingAdapter
from bsi_core.storage import LocalRawStore
from sqlalchemy import select
from sqlalchemy.orm import Session

brand_id = uuid.UUID(sys.argv[1])
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 30
adapter, store = GeminiGroundingAdapter(client=object()), LocalRawStore()

with Session(owner_engine()) as s:
    brand = s.get_one(m.Brand, brand_id)
    comps = s.scalars(
        select(m.Competitor).where(m.Competitor.brand_id == brand_id)
    ).all()
    entities = [
        {
            "id": brand.name,
            "type": "brand",
            "aliases": [brand.name, *brand.aliases],
        }
    ] + [
        {"id": c.name, "type": "competitor", "aliases": [c.name, *c.aliases]}
        for c in comps
    ]
    typed = [Entity(e["id"], e["type"], tuple(e["aliases"])) for e in entities]
    # One sample per prompt first, so the set covers every prompt.
    rows = s.scalars(
        select(m.Observation)
        .where(
            m.Observation.brand_id == brand_id, m.Observation.status == "done"
        )
        .order_by(m.Observation.sample_index, m.Observation.prompt_id)
        .limit(limit)
    ).all()
    for obs in rows:
        text = adapter.parse(store.get(obs.raw_uri, obs.org_id)).text
        guess = sorted({h.entity_id for h in find_mentions(text, typed)})
        print(
            json.dumps(
                {
                    "observation_id": str(obs.id),
                    "text": text,
                    "entities": entities,
                    "expected": guess,
                    "reviewed": False,
                },
                ensure_ascii=False,
            )
        )
