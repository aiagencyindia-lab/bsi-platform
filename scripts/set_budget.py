"""Set or clear an organization's daily budget override.

usage: python scripts/set_budget.py "<org name>" <usd|none>
bsi_app has no UPDATE on organization, so this runs as the owner.
"""

import sys
from decimal import Decimal

from bsi_core import models as m
from bsi_core.db import owner_engine
from sqlalchemy import select
from sqlalchemy.orm import Session

name, value = sys.argv[1], sys.argv[2]
new = None if value.lower() == "none" else Decimal(value)
with Session(owner_engine()) as s, s.begin():
    org = s.scalars(
        select(m.Organization).where(m.Organization.name == name)
    ).one()
    old = org.daily_budget_usd
    org.daily_budget_usd = new
print(f"{name!r} daily budget: {old} -> {new}")
