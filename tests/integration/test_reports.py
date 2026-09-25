"""Reports: due function, builders, generate, worker sweep."""

from datetime import UTC, datetime, timedelta

from bsi_core import models as m
from bsi_core.db import system_session
from sqlalchemy import text, update


def due_runs():
    with system_session() as s:
        return [
            (r.report_id, r.report_type)
            for r in s.execute(
                text(
                    "SELECT report_id, report_type, cadence "
                    "FROM due_report_runs()"
                )
            )
        ]


def _definition(owner, org, bid, type_="cmo", cadence="weekly", stamp=None):
    with owner() as s, s.begin():
        r = m.Report(
            org_id=org.id,
            brand_id=bid,
            type=type_,
            cadence=cadence,
            generated_at=stamp,
        )
        s.add(r)
        s.flush()
        return r.id


def test_due_needs_cadence_on_active_brand_and_old_stamp(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    now = datetime.now(UTC)
    never = _definition(owner, org, bid, "cmo", "weekly", None)
    _definition(owner, org, bid, "seo", "off", None)
    fresh_w = _definition(owner, org, bid, "content", "weekly", now)
    old_w = _definition(
        owner, org, bid, "pr", "weekly", now - timedelta(days=8)
    )
    # 8 days is old for weekly but fresh for monthly.
    _definition(owner, org, bid, "agency", "monthly", now - timedelta(days=8))
    assert due_runs() == [(never, "cmo"), (old_w, "pr")]
    with owner() as s, s.begin():
        s.execute(
            update(m.Report)
            .where(m.Report.id == fresh_w)
            .values(generated_at=now - timedelta(days=31))
        )
        s.execute(
            update(m.Brand).where(m.Brand.id == bid).values(status="archived")
        )
    assert due_runs() == []


def test_token_lookup_crosses_tenants_only_by_exact_token(
    owner, make_org, make_brand
):
    org = make_org()
    bid = make_brand(org)
    rid = _definition(owner, org, bid)
    with owner() as s, s.begin():
        run = m.ReportRun(
            org_id=org.id,
            brand_id=bid,
            report_id=rid,
            type="cmo",
            source="manual",
            period_from=datetime.now(UTC),
            period_to=datetime.now(UTC),
            compare_from=datetime.now(UTC),
            document={},
            methodology_version="1",
            share_token="tok-abcdefghijklmnopqrstuvwxyz",
        )
        s.add(run)
        s.flush()
        run_id = run.id
    q = text("SELECT run_id, org_id FROM report_run_by_token(:t)")
    with system_session() as s:
        hit = s.execute(q, {"t": "tok-abcdefghijklmnopqrstuvwxyz"}).first()
        miss = s.execute(q, {"t": "tok-abcdefghijklmnopqrstuvwxy"}).first()
        none = s.execute(q, {"t": ""}).first()
    assert hit is not None and (hit.run_id, hit.org_id) == (run_id, org.id)
    assert miss is None and none is None
