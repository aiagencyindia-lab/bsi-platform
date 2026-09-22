import hashlib
from datetime import UTC, datetime

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
    "schedule",
    "rec_label",
    "recommendation",
    "task",
    "site_audit",
]


@pytest.fixture
def org_b(owner, make_org, make_brand, make_observation):
    """Org B with at least one row in every tenant table."""
    b = make_org("B")
    bid = make_brand(b)
    oid = make_observation(b, bid, status="done")
    with owner() as s, s.begin():
        comp = m.Competitor(org_id=b.id, brand_id=bid, name="Rival")
        s.add_all([comp, m.Domain(org_id=b.id, brand_id=bid, host="b.com")])
        s.flush()
        s.add_all(
            [
                m.Extraction(
                    org_id=b.id,
                    observation_id=oid,
                    pipeline_version="1",
                    model_used="none",
                    brand_mentioned=True,
                ),
                m.Mention(
                    org_id=b.id,
                    observation_id=oid,
                    entity_type="competitor",
                    entity_id=comp.id,
                    position=1,
                    rec_status="mentioned",
                    sentiment="neutral",
                ),
                m.Citation(
                    org_id=b.id,
                    observation_id=oid,
                    url="u",
                    domain="b.com",
                    position=1,
                ),
                m.Schedule(
                    org_id=b.id,
                    brand_id=bid,
                    cadence="daily",
                    hour_utc=3,
                    next_run_at=datetime.now(UTC),
                ),
                m.RecLabel(
                    org_id=b.id,
                    observation_id=oid,
                    entity_type="brand",
                    entity_id=bid,
                    label="listed",
                ),
            ]
        )
    with owner() as s, s.begin():
        rec = m.Recommendation(
            org_id=b.id,
            brand_id=bid,
            type="sample_more",
            subject_key="k",
            title="t",
            body="b",
            reach=0.1,
            pressure=0.1,
            feasibility=1.0,
            priority=0.01,
        )
        s.add(rec)
        s.flush()
        s.add(
            m.Task(
                org_id=b.id, brand_id=bid, recommendation_id=rec.id, title="t"
            )
        )
        s.add(
            m.SiteAudit(
                org_id=b.id,
                brand_id=bid,
                domain="b.com",
                checks=[{"code": "llms_missing", "ok": False}],
            )
        )
    return b


def _count(s, table, org_id):
    column = "id" if table == "organization" else "org_id"
    q = text(f"SELECT count(*) FROM {table} WHERE {column} = :o")
    return s.execute(q, {"o": org_id}).scalar()


def test_fixture_populates_every_tenant_table(owner, org_b):
    # Otherwise the isolation checks below pass vacuously on empty tables.
    with owner() as s:
        empty = [t for t in TENANT_TABLES if not _count(s, t, org_b.id)]
    assert empty == []


def test_no_tenant_means_no_rows(org_b):
    with system_session() as s:
        for t in TENANT_TABLES:
            assert s.execute(text(f"SELECT count(*) FROM {t}")).scalar() == 0, t


def test_other_tenant_sees_none_of_its_rows(make_org, org_b):
    a = make_org("A")
    with tenant_session(a.id) as s:
        for t in TENANT_TABLES:
            assert _count(s, t, org_b.id) == 0, t


def test_tenant_table_list_matches_the_schema(owner, db):
    q = text(
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND column_name = 'org_id'"
    )
    with owner() as s:
        tables = {r for (r,) in s.execute(q)} | {"organization"}
    assert tables == set(TENANT_TABLES)


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
