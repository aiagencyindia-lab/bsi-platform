"""The Brand SERP audit: the table, and what the worker stores."""

from datetime import UTC, datetime

import pytest
from bsi_core import models as m
from sqlalchemy.exc import IntegrityError


def test_the_kind_is_checked(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    with pytest.raises(IntegrityError), owner() as s, s.begin():
        s.add(
            m.SerpAudit(
                org_id=org.id,
                brand_id=bid,
                kind="other",
                query="q",
                country="IN",
                language="en",
                fetched_at=datetime.now(UTC),
            )
        )
