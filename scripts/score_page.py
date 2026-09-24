"""Score one URL against one gap cluster, read-only: nothing is stored.

usage: set -a && source .env && set +a
       uv run python scripts/score_page.py <brand_id> <cluster_key> <url>
Spend: one embedding call (about $0.002)."""

import json
import sys
import uuid

from bsi_core import models as m
from bsi_core.crawl import http_fetch
from bsi_core.db import owner_engine
from bsi_core.suggest import embed
from bsi_workers.worker import audit_page
from sqlalchemy import select
from sqlalchemy.orm import Session

if len(sys.argv) != 4:
    sys.exit(__doc__)
try:
    brand_id = uuid.UUID(sys.argv[1])
except ValueError:
    sys.exit(f"not a brand id: {sys.argv[1]!r}")
with Session(owner_engine()) as s:
    org_id = s.scalar(select(m.Brand.org_id).where(m.Brand.id == brand_id))
if org_id is None:
    sys.exit(f"no brand {brand_id}")
spent = []


def metered(texts: list[str]) -> tuple[list[list[float]], int]:
    vectors, micros = embed(texts)
    spent.append(micros)
    return vectors, micros


row = audit_page(
    org_id,
    brand_id,
    {"url": sys.argv[3], "cluster_key": sys.argv[2]},
    metered,
    http_fetch,
)
print(json.dumps(row, indent=2, default=str))
print(f"spend: {sum(spent)} micros", file=sys.stderr)
