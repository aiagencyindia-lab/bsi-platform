"""Re-extract every done observation of an org under the current pipeline.

usage: python scripts/reextract.py "<org name>"
Each judge call is spend-guarded and its cost recorded in the ledger:
observations created before spend_since are not in the DB spend total.
"""

import sys

from bsi_core import models as m
from bsi_core import spend
from bsi_core.config import get_settings
from bsi_core.db import owner_engine
from bsi_core.extraction import Extractor
from bsi_core.judge import JUDGES
from bsi_core.providers.gemini import GeminiGroundingAdapter
from bsi_core.storage import LocalRawStore
from sqlalchemy import select
from sqlalchemy.orm import Session

ESTIMATE_MICROS = 20_000  # conservative per observation

with Session(owner_engine()) as s:
    org = s.scalars(
        select(m.Organization).where(m.Organization.name == sys.argv[1])
    ).one()
    rows = s.execute(
        select(m.Observation.id, m.Observation.created_at).where(
            m.Observation.org_id == org.id, m.Observation.status == "done"
        )
    ).all()
since = get_settings().spend_since
if any(created >= since for _, created in rows):
    # Those rows are already counted by spend.db_micros; recording them in
    # the ledger too would double-count.
    sys.exit("refusing: some observations are newer than spend_since")

extractor = Extractor(
    GeminiGroundingAdapter(client=object()),
    LocalRawStore(),
    JUDGES[get_settings().judge_mode],
)
kind = "reextract:" + sys.argv[1].lower().replace(" ", "")
for obs_id, _ in rows:
    spend.check(ESTIMATE_MICROS)
    actual = 0
    try:
        extractor.run(org.id, obs_id)
        with Session(owner_engine()) as s:
            actual = s.scalars(
                select(m.Extraction.cost_micros).where(
                    m.Extraction.observation_id == obs_id
                )
            ).one()
    finally:
        spend.record(kind, actual, release=ESTIMATE_MICROS)
print(f"re-extracted {len(rows)} observations for {sys.argv[1]!r}")
