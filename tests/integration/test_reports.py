"""Reports: due function, builders, generate, worker sweep."""

from datetime import UTC, datetime, timedelta

from bsi_core import models as m
from bsi_core.citations import sources
from bsi_core.competitors import entity_metrics
from bsi_core.db import system_session, tenant_session
from bsi_core.metrics import DELTA_METRICS, Filters, brand_deltas, rate
from bsi_core.reports import (
    BUILDERS,
    METRIC_LABEL,
    Document,
    build_agency,
    build_cmo,
    build_content,
    build_pr,
    build_seo,
    days_for,
    definition,
    fmt_day,
    fmt_delta,
    fmt_rate,
    generate,
    label,
)
from bsi_workers.worker import generate_due_reports
from sqlalchemy import select, text, update

from tests.integration.test_competitors import (
    NOW,
    _answers,
    _cite,
    _mention,
    _prompt,
)
from tests.unit.test_recommend_copy import FORBIDDEN


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


def _scene(owner, make_org, make_brand):
    """Nike (nike.com) v Adidas (adidas.com). One prompt; 6 answers in the
    last 7 days, 6 in the 7 before. This period: Nike named 4/6 (one
    negative), Adidas 3/6; forbes.com cited on every answer, nike.com on
    2. Prior period: Nike 1/6. One open recommendation, one done task
    with a measured impact, one alert inside the period."""
    org = make_org()
    bid = make_brand(org, "Nike")
    with owner() as s, s.begin():
        s.add(m.Domain(org_id=org.id, brand_id=bid, host="nike.com"))
        comp = m.Competitor(
            org_id=org.id, brand_id=bid, name="Adidas", domains=["adidas.com"]
        )
        s.add(comp)
        s.flush()
        cid = comp.id
    p = _prompt(owner, org, bid, "best shoes")
    before = _answers(owner, org, bid, p, NOW - timedelta(days=10), 6)
    after = _answers(owner, org, bid, p, NOW - timedelta(days=2), 6)
    rows = [_mention(org, before[0], "brand", bid)]
    rows += [_mention(org, o, "brand", bid) for o in after[:3]]
    rows.append(
        _mention(org, after[3], "brand", bid, rec="negative", sent="negative")
    )
    rows += [_mention(org, o, "competitor", cid) for o in after[:3]]
    rows += [_cite(org, o, "forbes.com") for o in after]
    rows += [_cite(org, o, "nike.com", owned=True) for o in after[:2]]
    with owner() as s, s.begin():
        s.add_all(rows)
        rec = m.Recommendation(
            org_id=org.id,
            brand_id=bid,
            type="pursue_citation_source",
            subject_key="forbes.com",
            title="Pitch forbes.com",
            body="b",
            reach=0.5,
            pressure=0.5,
            feasibility=0.5,
            priority=0.125,
        )
        s.add(rec)
        s.flush()
        s.add(
            m.Task(
                org_id=org.id,
                brand_id=bid,
                recommendation_id=rec.id,
                title="Pitch forbes.com",
                owner="Priya",
                status="impact_measured",
                done_at=NOW - timedelta(days=3),
                window_days=14,
                impact_label="improved",
                impact={
                    "delta": {
                        "value": 0.2,
                        "ci_low": 0.1,
                        "ci_high": 0.3,
                        "label": "increase",
                    }
                },
            )
        )
        s.add(
            m.Alert(
                org_id=org.id,
                brand_id=bid,
                type="new_source",
                subject_key="forbes.com",
                title="forbes.com is a new source",
                detail={"domain": "forbes.com", "answers": 6},
                window_from=NOW - timedelta(days=7),
                window_to=NOW,
                created_at=NOW - timedelta(days=1),
            )
        )
    return org, bid


def _section(doc: Document, heading: str):
    return next(sec for sec in doc.sections if sec.heading == heading)


def _table(doc: Document, heading: str):
    block = _section(doc, heading).blocks[0]
    assert block.kind == "table", (heading, block)
    return block


def test_cmo_opening_agrees_with_brand_deltas(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    with tenant_session(org.id) as s:
        brand = s.get_one(m.Brand, bid)
        doc = build_cmo(s, brand, 7, NOW)
        out = brand_deltas(s, bid, Filters(), 7, NOW)
    assert doc.type == "cmo" and doc.brand == "Nike"
    assert doc.period.from_ == out["after"]["from"]
    assert doc.period.compare_from == out["before"]["from"]
    assert doc.sections[0].heading == "Period"
    vis = _table(doc, "Visibility")
    assert vis.columns == ["Metric", "This period", "Prior period", "Change"]
    assert vis.rows == [
        [
            METRIC_LABEL[k],
            fmt_rate(out["after"][k]),
            fmt_rate(out["before"][k]),
            fmt_delta(out["deltas"][k]),
        ]
        for k in DELTA_METRICS
    ]
    assert vis.rows[0][1] == "0.67 [0.30, 0.90] n=6"
    assert doc.footer.startswith("Methodology v2 · pipeline v")


def test_cmo_sections_agree_with_the_dashboard_functions(
    owner, make_org, make_brand
):
    org, bid = _scene(owner, make_org, make_brand)
    f = Filters(date_from=NOW - timedelta(days=7), date_to=NOW)
    with tenant_session(org.id) as s:
        brand = s.get_one(m.Brand, bid)
        doc = build_cmo(s, brand, 7, NOW)
        ents = entity_metrics(s, bid, f)
        srcs = sources(s, bid, f)
    assert [sec.heading for sec in doc.sections] == [
        "Period",
        "Visibility",
        "Share of voice",
        "Competitors",
        "Top cited sources",
        "Recommendations",
        "Tasks",
        "Alerts in period",
    ]
    comp = _table(doc, "Competitors")
    assert [r[0] for r in comp.rows] == [e["name"] for e in ents]
    assert comp.rows[0][1] == fmt_rate(ents[0]["mention_rate"])
    assert comp.rows[0][2] == fmt_rate(ents[0]["sov"])
    src = _table(doc, "Top cited sources")
    assert src.rows == [
        [x["domain"], label(x["owner"]), str(x["answers"]), str(x["prompts"])]
        for x in srcs[:10]
    ]
    assert src.rows[0][1] == "Third party"
    assert _table(doc, "Recommendations").rows == [
        ["Citation source", "Pitch forbes.com", "0.12"]
    ]
    assert _table(doc, "Tasks").columns == [
        "Task",
        "Owner",
        "Status",
        "Impact",
        "Change",
    ]
    assert _table(doc, "Tasks").rows == [
        [
            "Pitch forbes.com",
            "Priya",
            "Impact measured",
            "Improved",
            "+0.20 [+0.10, +0.30] increase",
        ]
    ]
    alerts = _table(doc, "Alerts in period")
    assert alerts.rows[0][:2] == ["New source", "forbes.com is a new source"]


def test_empty_brand_gets_a_complete_report(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Fresh")
    with tenant_session(org.id) as s:
        doc = build_cmo(s, s.get_one(m.Brand, bid), 7, NOW)
    assert len(doc.sections) == 8
    vis = _table(doc, "Visibility")
    assert vis.rows[0][1] == "— (n=0)"
    assert vis.rows[0][3] == "insufficient data"
    assert _section(doc, "Competitors").blocks[0].kind == "p"
    assert _section(doc, "Tasks").blocks[0].text == "No tasks in this period."


def test_agency_is_client_facing_cmo(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    with owner() as s, s.begin():
        s.execute(
            update(m.Brand)
            .where(m.Brand.id == bid)
            .values(
                report_logo_url="https://nike.com/logo.png",
                report_accent="#112233",
                report_prepared_by="Acme Agency",
            )
        )
    with tenant_session(org.id) as s:
        doc = build_agency(s, s.get_one(m.Brand, bid), 7, NOW)
    assert doc.type == "agency" and doc.title == "Nike visibility report"
    assert doc.branding is not None
    assert doc.branding.model_dump() == {
        "logo_url": "https://nike.com/logo.png",
        "accent": "#112233",
        "prepared_by": "Acme Agency",
    }
    assert doc.sections[0].blocks[-1].text == "Prepared by Acme Agency."
    tasks = _table(doc, "Tasks")
    assert tasks.columns == ["Task", "Status", "Impact", "Change"]
    assert "Priya" not in str(doc.model_dump())


def _audits(owner, org, bid):
    with owner() as s, s.begin():
        s.add(
            m.SiteAudit(
                org_id=org.id,
                brand_id=bid,
                domain="nike.com",
                checks=[
                    {
                        "code": "robots_ok",
                        "ok": True,
                        "severity": "high",
                        "observed": "200",
                        "expected": "200",
                        "url": "https://nike.com/robots.txt",
                    },
                    {
                        "code": "llms_txt",
                        "ok": False,
                        "severity": "low",
                        "observed": "404",
                        "expected": "200",
                        "url": "https://nike.com/llms.txt",
                    },
                ],
            )
        )
        s.add(
            m.PageAudit(
                org_id=org.id,
                brand_id=bid,
                url="https://nike.com/best-shoes",
                cluster_key="cluster:commercial:shoes",
                status=200,
                weights_version="v1",
                score=61,
                suggestions={
                    "add": [{"text": "Add an FAQ block"}],
                    "remove": [],
                    "rewrite": [],
                    "evidence_to_add": [],
                },
            )
        )


def test_seo_sections(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    _audits(owner, org, bid)
    with tenant_session(org.id) as s:
        doc = build_seo(s, s.get_one(m.Brand, bid), 7, NOW)
    assert [sec.heading for sec in doc.sections][2:] == [
        "Cited sources",
        "Site audit",
        "Page citability",
        "Content gaps",
        "Recommendations",
    ]
    src = _table(doc, "Cited sources")
    assert src.columns == ["Domain", "Owner", "Answers", "Prompts", "Gap"]
    audit = _table(doc, "Site audit")
    assert audit.columns == ["Domain", "Check", "Severity", "Detail"]
    assert audit.rows == [["nike.com", "Llms txt", "Low", "404 (expected 200)"]]
    assert _table(doc, "Page citability").rows == [
        ["https://nike.com/best-shoes", "cluster:commercial:shoes", "61"]
    ]
    assert _table(doc, "Recommendations").rows[0][1] == "Pitch forbes.com"


def test_seo_gap_table_has_an_intent_column(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    # Two labelled prompts with the same topic and different intents, the
    # brand absent on every answer, so both clusters are gaps.
    with owner() as s, s.begin():
        cid = s.scalars(
            select(m.Competitor.id).where(m.Competitor.brand_id == bid)
        ).first()
    for intent in ("commercial", "problem-based"):
        p = _prompt(owner, org, bid, f"{intent} kids shoes")
        with owner() as s, s.begin():
            s.execute(
                update(m.Prompt)
                .where(m.Prompt.id == p)
                .values(intent=intent, topic="kids shoes")
            )
        obs = _answers(owner, org, bid, p, NOW - timedelta(days=1), 4)
        with owner() as s, s.begin():
            for o in obs:
                s.add(
                    m.Extraction(
                        org_id=org.id,
                        observation_id=o,
                        pipeline_version="2",
                        model_used="t",
                        brand_mentioned=False,
                        absence_reason="competitor_dominance",
                    )
                )
                s.add(_mention(org, o, "competitor", cid))
    with tenant_session(org.id) as s:
        doc = build_seo(s, s.get_one(m.Brand, bid), 7, NOW)
    gaps = _table(doc, "Content gaps")
    assert gaps.columns == [
        "Intent",
        "Topic",
        "Prompts",
        "Brand mention rate",
        "Top rival",
    ]
    assert sorted((r[0], r[1]) for r in gaps.rows) == [
        ("Commercial", "kids shoes"),
        ("Problem-based", "kids shoes"),
    ]


def test_content_sections(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    _audits(owner, org, bid)
    with tenant_session(org.id) as s:
        doc = build_content(s, s.get_one(m.Brand, bid), 7, NOW)
    assert [sec.heading for sec in doc.sections][2:] == [
        "Prompt performance by topic",
        "Content gaps with briefs",
        "Page citability with next step",
        "Recommendations",
    ]
    topics = _table(doc, "Prompt performance by topic")
    assert topics.columns == ["Topic", "Prompts", "Mention rate", "Top rival"]
    assert topics.rows == [
        ["untopiced", "1", "0.67 [0.30, 0.90] n=6", "Adidas"]
    ]
    assert _table(doc, "Page citability with next step").rows == [
        ["https://nike.com/best-shoes", "61", "Add an FAQ block"]
    ]
    assert _section(doc, "Recommendations").blocks[0].kind == "p"


def test_pr_sections(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    with tenant_session(org.id) as s:
        doc = build_pr(s, s.get_one(m.Brand, bid), 7, NOW)
    assert [sec.heading for sec in doc.sections][2:] == [
        "Sentiment mix",
        "Negative mentions",
        "Competitor sentiment",
        "Third-party sources naming the brand",
        "New sources in period",
    ]
    mix = _table(doc, "Sentiment mix")
    assert mix.rows == [
        ["Neutral", "3", fmt_rate(rate(3, 4))],
        ["Negative", "1", fmt_rate(rate(1, 4))],
    ]
    neg = _table(doc, "Negative mentions")
    assert len(neg.rows) == 1 and neg.rows[0][1] == "best shoes"
    third = _table(doc, "Third-party sources naming the brand")
    assert third.rows == [["forbes.com", "6", "1"]]
    assert _table(doc, "New sources in period").rows == [
        [
            "forbes.com",
            "forbes.com is a new source",
            f"{fmt_day(NOW - timedelta(days=7))} to {fmt_day(NOW)}",
        ]
    ]


def test_pr_empty_brand_has_no_dash_rows(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org, "Fresh")
    with tenant_session(org.id) as s:
        doc = build_pr(s, s.get_one(m.Brand, bid), 7, NOW)
    for heading in [sec.heading for sec in doc.sections][2:]:
        assert _section(doc, heading).blocks[0].kind == "p", heading


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def test_copy_never_promises(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    _audits(owner, org, bid)
    with tenant_session(org.id) as s:
        brand = s.get_one(m.Brand, bid)
        docs = [b(s, brand, 7, NOW) for b in BUILDERS.values()]
    assert set(BUILDERS) == set(m.REPORT_TYPES)
    for doc in docs:
        for text_ in _strings(doc.model_dump(mode="json", by_alias=True)):
            low = text_.lower()
            assert not any(w in low for w in FORBIDDEN), (doc.type, text_)
            assert "bsi" not in low and "lumenca" not in low, text_


def test_definition_is_created_once(owner, make_org, make_brand):
    org = make_org()
    bid = make_brand(org)
    with tenant_session(org.id) as s:
        a = definition(s, org.id, bid, "cmo")
        b = definition(s, org.id, bid, "cmo")
        assert a.id == b.id and a.cadence == "off"


def test_generate_freezes_the_document(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    with tenant_session(org.id) as s:
        run = generate(s, org.id, bid, "cmo", days=7, to=NOW, source="manual")
        run_id, token, doc = run.id, run.share_token, run.document
    assert token is not None and len(token) >= 40
    assert doc["type"] == "cmo" and doc["title"] == "Nike: CMO summary"
    before = Document.model_validate(doc)
    # New answers after generation must not change the stored run.
    p = _prompt(owner, org, bid, "more shoes")
    _answers(owner, org, bid, p, NOW - timedelta(days=1), 6)
    with tenant_session(org.id) as s:
        run = s.get_one(m.ReportRun, run_id)
        assert Document.model_validate(run.document) == before
        assert run.methodology_version == "2"
        assert run.period_to == NOW
        assert run.period_from == NOW - timedelta(days=7)
        assert run.compare_from == NOW - timedelta(days=14)
        assert run.report_id == definition(s, org.id, bid, "cmo").id
        assert s.get_one(m.Report, run.report_id).generated_at is None


def test_days_for():
    assert (days_for("weekly"), days_for("monthly")) == (7, 30)


def test_worker_generates_due_runs_and_stamps(owner, make_org, make_brand):
    org, bid = _scene(owner, make_org, make_brand)
    other = make_brand(make_org("B"))
    _definition(owner, org, bid, "cmo", "weekly")
    with owner() as s, s.begin():
        s.add(
            m.Report(
                org_id=s.get_one(m.Brand, other).org_id,
                brand_id=other,
                type="pr",
                cadence="monthly",
            )
        )
    assert generate_due_reports() == 2
    with owner() as s:
        runs = s.scalars(select(m.ReportRun)).all()
        stamps = s.scalars(select(m.Report.generated_at)).all()
    assert sorted((r.type, r.source) for r in runs) == [
        ("cmo", "scheduled"),
        ("pr", "scheduled"),
    ]
    pr = next(r for r in runs if r.type == "pr")
    assert pr.period_to - pr.period_from == timedelta(days=30)
    assert all(t is not None for t in stamps)
    assert generate_due_reports() == 0


def test_worker_survives_one_failing_brand(
    owner, make_org, make_brand, monkeypatch
):
    org = make_org()
    a, b = make_brand(org, "A"), make_brand(org, "B")
    _definition(owner, org, a, "cmo", "weekly")
    _definition(owner, org, b, "cmo", "weekly")
    from bsi_core import reports

    real = reports.BUILDERS["cmo"]

    def boom(s, brand, days, to):
        if brand.name == "A":
            raise RuntimeError("boom")
        return real(s, brand, days, to)

    monkeypatch.setitem(reports.BUILDERS, "cmo", boom)
    assert generate_due_reports() == 1
    with owner() as s:
        stamped = s.scalars(
            select(m.Report.brand_id).where(m.Report.generated_at.isnot(None))
        ).all()
    assert stamped == [b]
