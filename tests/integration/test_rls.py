import hashlib

import pytest
from bsi_core import models as m
from bsi_core.db import system_session, tenant_session
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

TENANT_TABLES = [
    "organization",
    "workspace",
    "api_key",
    "brand",
    "domain",
    "competitor",
    "locale",
    "prompt",
    "job",
    "observation",
    "extraction",
    "mention",
    "citation",
]


def test_no_tenant_means_no_rows(make_org, make_brand):
    make_brand(make_org())
    with system_session() as s:
        for t in TENANT_TABLES:
            assert s.execute(text(f"SELECT count(*) FROM {t}")).scalar() == 0


def test_tenant_sees_only_own_rows(make_org, make_brand):
    a, b = make_org("A"), make_org("B")
    make_brand(a, "BrandA")
    make_brand(b, "BrandB")
    with tenant_session(a.id) as s:
        assert [x.name for x in s.scalars(select(m.Brand))] == ["BrandA"]


def test_setting_does_not_leak_or_break_next_transaction(make_org, make_brand):
    a = make_org()
    make_brand(a)
    with tenant_session(a.id):
        pass
    with system_session() as s:  # same pool; setting is now ''
        assert s.execute(text("SELECT count(*) FROM brand")).scalar() == 0


def test_cannot_write_into_another_org(make_org):
    a, b = make_org("A"), make_org("B")
    with pytest.raises(DBAPIError), tenant_session(a.id) as s:
        s.add(m.Brand(org_id=b.id, workspace_id=b.workspace_id, name="x"))
        s.flush()


def test_resolve_api_key(make_org):
    a = make_org()
    h = hashlib.sha256(a.token.encode()).hexdigest()
    with system_session() as s:
        q = text("SELECT resolve_api_key(:h)")
        assert s.execute(q, {"h": h}).scalar() == a.id
        assert s.execute(q, {"h": "nope"}).scalar() is None
