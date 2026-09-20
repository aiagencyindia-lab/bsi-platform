"""Set or clear an organization's daily budget override.

usage: python scripts/set_budget.py "<org name>" <usd|none>
bsi_app has no UPDATE on organization, so this runs as the owner.
"""

import sys
from decimal import Decimal, InvalidOperation

from bsi_core import models as m
from bsi_core.db import owner_engine
from sqlalchemy import select
from sqlalchemy.orm import Session

if len(sys.argv) != 3:
    sys.exit(__doc__)
name, value = sys.argv[1], sys.argv[2]
try:
    new = None if value.lower() == "none" else Decimal(value)
except InvalidOperation:
    sys.exit(f"not a number: {value!r}")
with Session(owner_engine()) as s, s.begin():
    orgs = s.scalars(
        select(m.Organization).where(m.Organization.name == name)
    ).all()
    if len(orgs) != 1:  # name is not unique
        sys.exit(f"{len(orgs)} organizations named {name!r}")
    org = orgs[0]
    old = org.daily_budget_usd
    org.daily_budget_usd = new
    s.flush()
    s.refresh(org)
    stored = org.daily_budget_usd  # what the numeric(10,2) column kept
print(f"{name!r} daily budget: {old} -> {stored}")
