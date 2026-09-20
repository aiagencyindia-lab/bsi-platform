"""Fill observation.search_queries from the stored raw payloads.

Owner-side and idempotent. usage: python scripts/backfill_search_queries.py
"""

from bsi_core import models as m
from bsi_core.db import owner_engine
from bsi_core.providers.gemini import GeminiGroundingAdapter
from bsi_core.storage import LocalRawStore
from sqlalchemy import select
from sqlalchemy.orm import Session

store, done = LocalRawStore(), 0
with Session(owner_engine()) as s, s.begin():
    rows = s.scalars(
        select(m.Observation).where(
            m.Observation.raw_uri.is_not(None),
            m.Observation.search_queries.is_(None),
        )
    )
    for obs in rows:
        raw = store.get(obs.raw_uri, obs.org_id)
        obs.search_queries = GeminiGroundingAdapter.search_queries(raw)
        done += 1
print(f"backfilled {done} observations")
