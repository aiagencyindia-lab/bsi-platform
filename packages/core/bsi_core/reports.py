"""Reports: a frozen document per run, built from the same metric
functions the dashboard uses, so report and API agree for one window.

Every cell is a pre-formatted string, so the HTML page and the PDF only
render. No links or ids: readers are outside the app. Fixed copy only.
"""

from __future__ import annotations

import secrets
import uuid
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from . import models as m
from .citations import sources
from .competitors import entity_metrics
from .gaps import clusters
from .metrics import (
    DELTA_METRICS,
    Filters,
    _where,
    brand_deltas,
    brand_sov,
    prompt_metrics,
    rate,
)
from .recommend import top_by_type

# Bump whenever a builder changes what it computes or how a cell is
# formatted: a reader comparing two runs must know they are comparable.
METHODOLOGY_VERSION = "1"

METRIC_LABEL = {
    "mention_rate": "Mention rate",
    "recommendation_rate": "Recommendation rate",
    "citation_rate": "Citation rate",
    "prompt_coverage": "Prompt coverage",
    "sov": "Share of voice",
}
REC_LABEL = {
    "pursue_citation_source": "Citation source",
    "create_content": "Content",
    "add_competitor": "Competitor",
    "sample_more": "Measurement",
    "fix_crawlability": "Site fix",
    "fix_entity": "Entity fix",
    "optimize_page": "Page fix",
    "respond_to_rival_content": "Rival content",
}
ALERT_LABEL = {
    "mention_drop": "Mention drop",
    "competitor_shift": "Competitor shift",
    "new_source": "New source",
}


class Period(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: datetime = Field(alias="from")
    to: datetime
    compare_from: datetime


class Branding(BaseModel):
    logo_url: str | None = None
    accent: str | None = None
    prepared_by: str | None = None


class Paragraph(BaseModel):
    kind: Literal["p"] = "p"
    text: str


class Table(BaseModel):
    kind: Literal["table"] = "table"
    columns: list[str]
    rows: list[list[str]]


Block = Annotated[Paragraph | Table, Field(discriminator="kind")]


class Section(BaseModel):
    heading: str
    blocks: list[Block]


class Document(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    title: str
    brand: str
    type: str
    period: Period
    branding: Branding | None = None
    sections: list[Section]
    footer: str


def fmt_rate(r: Mapping[str, Any]) -> str:
    if r["n"] == 0 or r["value"] is None:
        return "— (n=0)"
    return (
        f"{r['value']:.2f} [{r['ci_low']:.2f}, {r['ci_high']:.2f}] n={r['n']}"
    )


def fmt_delta(d: Mapping[str, Any] | None) -> str:
    if d is None:
        return "—"
    if d["value"] is None:
        return str(d["label"])
    return (
        f"{d['value']:+.2f} [{d['ci_low']:+.2f}, {d['ci_high']:+.2f}] "
        f"{d['label']}"
    )


def fmt_pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def fmt_signed(v: float | None) -> str:
    return "—" if v is None else f"{v:+.2f}"


def fmt_day(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def footer(versions: Sequence[str], at: datetime) -> str:
    seen = ", ".join(sorted(set(versions))) or "—"
    return (
        f"Methodology v{METHODOLOGY_VERSION} · pipeline v{seen} · "
        "rates: 95% Wilson interval · deltas: 95% Newcombe interval · "
        f"generated {at.strftime('%Y-%m-%d %H:%M')} UTC"
    )


def empty(what: str) -> Paragraph:
    return Paragraph(text=f"No {what} in this period.")


def table_or_empty(
    columns: list[str], rows: list[list[str]], what: str
) -> Paragraph | Table:
    return Table(columns=columns, rows=rows) if rows else empty(what)


Builder = Callable[[Session, m.Brand, int, datetime], Document]

SOV_ROWS = 10
COMPETITOR_ROWS = 10
SOURCE_ROWS = 10
REC_ROWS = 10


def _opening(
    s: Session, brand: m.Brand, days: int, to: datetime
) -> tuple[Period, list[Section], list[str]]:
    """The Period paragraph, the Visibility table, and the pipeline
    versions seen in either window. Reads brand_deltas so report and
    dashboard agree."""
    out = brand_deltas(s, brand.id, Filters(), days, to)
    period = Period(
        from_=out["after"]["from"],
        to=to,
        compare_from=out["before"]["from"],
    )
    rows = []
    for k in DELTA_METRICS:
        change = (
            fmt_delta(out["deltas"][k])
            if out["comparable"]
            else f"not comparable: {out['reason']}"
        )
        rows.append(
            [
                METRIC_LABEL[k],
                fmt_rate(out["after"][k]),
                fmt_rate(out["before"][k]),
                change,
            ]
        )
    versions = [
        *out["after"]["pipeline_versions"],
        *out["before"]["pipeline_versions"],
    ]
    sections = [
        Section(
            heading="Period",
            blocks=[
                Paragraph(
                    text=(
                        f"{fmt_day(period.from_)} to {fmt_day(to)}, "
                        f"compared with {fmt_day(period.compare_from)} "
                        f"to {fmt_day(period.from_)}. Each rate is "
                        "value [95% interval] n=answers."
                    )
                )
            ],
        ),
        Section(
            heading="Visibility",
            blocks=[
                Table(
                    columns=["Metric", "This period", "Prior period", "Change"],
                    rows=rows,
                )
            ],
        ),
    ]
    return period, sections, versions


def _window(period: Period) -> Filters:
    return Filters(date_from=period.from_, date_to=period.to)


def _open_recommendations(
    s: Session, brand_id: uuid.UUID, types: tuple[str, ...] | None = None
) -> list[m.Recommendation]:
    q = (
        select(m.Recommendation)
        .where(
            m.Recommendation.brand_id == brand_id,
            m.Recommendation.status == "open",
        )
        .order_by(m.Recommendation.priority.desc(), m.Recommendation.id)
    )
    if types is not None:
        q = q.where(m.Recommendation.type.in_(types))
    return list(s.scalars(q))


def _rec_rows(recs: Sequence[m.Recommendation]) -> list[list[str]]:
    return [
        [REC_LABEL.get(r.type, r.type), r.title, f"{r.priority:.2f}"]
        for r in recs[:REC_ROWS]
    ]


def _rec_section(heading: str, recs: Sequence[m.Recommendation]) -> Section:
    return Section(
        heading=heading,
        blocks=[
            table_or_empty(
                ["Type", "Recommendation", "Priority"],
                _rec_rows(recs),
                "open recommendations",
            )
        ],
    )


def _alerts_in(
    s: Session, brand_id: uuid.UUID, period: Period, type_: str | None = None
) -> list[m.Alert]:
    q = (
        select(m.Alert)
        .where(
            m.Alert.brand_id == brand_id,
            m.Alert.created_at >= period.from_,
            m.Alert.created_at < period.to,
        )
        .order_by(m.Alert.created_at.desc(), m.Alert.id)
    )
    if type_ is not None:
        q = q.where(m.Alert.type == type_)
    return list(s.scalars(q))


def _alert_rows(alerts: Sequence[m.Alert]) -> list[list[str]]:
    return [
        [
            ALERT_LABEL.get(a.type, a.type),
            a.title,
            f"{fmt_day(a.window_from)} to {fmt_day(a.window_to)}",
        ]
        for a in alerts
    ]


def _task_rows(
    s: Session, brand_id: uuid.UUID, period: Period, *, client_facing: bool
) -> list[list[str]]:
    q = (
        select(m.Task)
        .where(
            m.Task.brand_id == brand_id,
            (m.Task.done_at.is_(None)) | (m.Task.done_at >= period.from_),
        )
        .order_by(m.Task.created_at.desc(), m.Task.id)
    )
    rows = []
    for t in s.scalars(q):
        impact = t.impact or {}
        row = [
            t.title,
            t.owner or "—",
            t.status,
            t.impact_label or "—",
            fmt_delta(impact.get("delta")),
        ]
        if client_facing:
            del row[1]
        rows.append(row)
    return rows


def build_cmo(
    s: Session,
    brand: m.Brand,
    days: int,
    to: datetime,
    *,
    client_facing: bool = False,
) -> Document:
    period, sections, versions = _opening(s, brand, days, to)
    f = _window(period)
    sov_rows = [
        [
            r["name"],
            f"{fmt_pct(r['share'])} [{fmt_pct(r['ci_low'])}, "
            f"{fmt_pct(r['ci_high'])}]",
            str(r["mentions"]),
        ]
        for r in brand_sov(s, brand.id, f)[:SOV_ROWS]
    ]
    comp_rows = [
        [
            e["name"],
            fmt_rate(e["mention_rate"]),
            fmt_rate(e["sov"]),
            fmt_signed(e["sentiment"]["index"]),
        ]
        for e in entity_metrics(s, brand.id, f)[:COMPETITOR_ROWS]
        # With no answers every row is "— (n=0)": nothing to show.
        if e["mention_rate"]["n"]
    ]
    src_rows = [
        [x["domain"], x["owner"], str(x["answers"]), str(x["prompts"])]
        for x in sources(s, brand.id, f)[:SOURCE_ROWS]
    ]
    task_columns = ["Task", "Owner", "Status", "Impact", "Change"]
    if client_facing:
        task_columns.remove("Owner")
    sections += [
        Section(
            heading="Share of voice",
            blocks=[
                table_or_empty(
                    ["Entity", "Share [95% interval]", "Mentions"],
                    sov_rows,
                    "mentions",
                )
            ],
        ),
        Section(
            heading="Competitors",
            blocks=[
                table_or_empty(
                    ["Entity", "Mention rate", "Share of voice", "Sentiment"],
                    comp_rows,
                    "mentions",
                )
            ],
        ),
        Section(
            heading="Top cited sources",
            blocks=[
                table_or_empty(
                    ["Domain", "Owner", "Answers", "Prompts"],
                    src_rows,
                    "cited sources",
                )
            ],
        ),
        _rec_section(
            "Recommendations", top_by_type(_open_recommendations(s, brand.id))
        ),
        Section(
            heading="Tasks",
            blocks=[
                table_or_empty(
                    task_columns,
                    _task_rows(
                        s, brand.id, period, client_facing=client_facing
                    ),
                    "tasks",
                )
            ],
        ),
        Section(
            heading="Alerts in period",
            blocks=[
                table_or_empty(
                    ["Type", "Alert", "Window"],
                    _alert_rows(_alerts_in(s, brand.id, period)),
                    "alerts",
                )
            ],
        ),
    ]
    if client_facing:
        title = f"{brand.name} visibility report"
        branding = Branding(
            logo_url=brand.report_logo_url,
            accent=brand.report_accent,
            prepared_by=brand.report_prepared_by,
        )
        if brand.report_prepared_by:
            sections[0].blocks.append(
                Paragraph(text=f"Prepared by {brand.report_prepared_by}.")
            )
    else:
        title = f"{brand.name}: CMO summary"
        branding = None
    return Document(
        title=title,
        brand=brand.name,
        type="agency" if client_facing else "cmo",
        period=period,
        branding=branding,
        sections=sections,
        footer=footer(versions, to),
    )


def build_agency(
    s: Session, brand: m.Brand, days: int, to: datetime
) -> Document:
    return build_cmo(s, brand, days, to, client_facing=True)


SEO_SOURCE_ROWS = 20
GAP_ROWS = 10
NEGATIVE_ROWS = 20
SEO_REC_TYPES = (
    "pursue_citation_source",
    "fix_crawlability",
    "fix_entity",
    "optimize_page",
    "respond_to_rival_content",
)
CONTENT_REC_TYPES = (
    "create_content",
    "optimize_page",
    "respond_to_rival_content",
)


def _latest_site_audits(s: Session, brand_id: uuid.UUID) -> list[m.SiteAudit]:
    """The latest audit per currently declared domain (the Site tab's
    query)."""
    q = (
        select(m.SiteAudit)
        .join(
            m.Domain,
            (m.Domain.brand_id == m.SiteAudit.brand_id)
            & (m.Domain.host == m.SiteAudit.domain),
        )
        .where(m.SiteAudit.brand_id == brand_id)
        .order_by(
            m.SiteAudit.domain,
            m.SiteAudit.created_at.desc(),
            m.SiteAudit.id.desc(),
        )
        .distinct(m.SiteAudit.domain)
    )
    return list(s.scalars(q))


def _latest_page_audits(s: Session, brand_id: uuid.UUID) -> list[m.PageAudit]:
    """The latest scored audit per (cluster, url), best score first."""
    q = (
        select(m.PageAudit)
        .where(m.PageAudit.brand_id == brand_id)
        .order_by(
            m.PageAudit.cluster_key,
            m.PageAudit.url,
            m.PageAudit.created_at.desc(),
            m.PageAudit.id.desc(),
        )
        .distinct(m.PageAudit.cluster_key, m.PageAudit.url)
    )
    rows = [a for a in s.scalars(q) if a.score is not None]
    rows.sort(key=lambda a: (-(a.score or 0), a.url))
    return rows


def _gap_rows(
    s: Session, brand_id: uuid.UUID, f: Filters
) -> list[dict[str, Any]]:
    return [c for c in clusters(s, brand_id, f) if c["gap"]][:GAP_ROWS]


def build_seo(s: Session, brand: m.Brand, days: int, to: datetime) -> Document:
    period, sections, versions = _opening(s, brand, days, to)
    f = _window(period)
    src_rows = [
        [
            x["domain"],
            x["owner"],
            str(x["answers"]),
            str(x["prompts"]),
            "yes" if x["gap"] else "no",
        ]
        for x in sources(s, brand.id, f)[:SEO_SOURCE_ROWS]
    ]
    audit_rows = [
        [
            a.domain,
            str(c.get("code", "")),
            str(c.get("severity", "")),
            f"{c.get('observed', '')} (expected {c.get('expected', '')})",
        ]
        for a in _latest_site_audits(s, brand.id)
        for c in a.checks
        if not c.get("ok", True)
    ]
    page_rows = [
        [a.url, a.cluster_key, str(a.score)]
        for a in _latest_page_audits(s, brand.id)
    ]
    gap_rows = [
        [
            c["topic"],
            str(len(c["prompts"])),
            fmt_rate(c["brand"]),
            (
                f"{c['top_rival']['name']} {fmt_rate(c['top_rival'])}"
                if c["top_rival"]
                else "—"
            ),
        ]
        for c in _gap_rows(s, brand.id, f)
    ]
    sections += [
        Section(
            heading="Cited sources",
            blocks=[
                table_or_empty(
                    ["Domain", "Owner", "Answers", "Prompts", "Gap"],
                    src_rows,
                    "cited sources",
                )
            ],
        ),
        Section(
            heading="Site audit",
            blocks=[
                table_or_empty(
                    ["Domain", "Check", "Severity", "Detail"],
                    audit_rows,
                    "failing site checks",
                )
            ],
        ),
        Section(
            heading="Page citability",
            blocks=[
                table_or_empty(
                    ["URL", "Cluster", "Score"], page_rows, "scored pages"
                )
            ],
        ),
        Section(
            heading="Content gaps",
            blocks=[
                table_or_empty(
                    ["Topic", "Prompts", "Brand mention rate", "Top rival"],
                    gap_rows,
                    "content gaps",
                )
            ],
        ),
        _rec_section(
            "Recommendations",
            _open_recommendations(s, brand.id, SEO_REC_TYPES),
        ),
    ]
    return Document(
        title=f"{brand.name}: SEO report",
        brand=brand.name,
        type="seo",
        period=period,
        sections=sections,
        footer=footer(versions, to),
    )


def _topic_rows(s: Session, brand_id: uuid.UUID, f: Filters) -> list[list[str]]:
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for p in prompt_metrics(s, brand_id, f):
        by_topic.setdefault(p["topic"] or "untopiced", []).append(p)
    rows = []
    for topic, ps in sorted(by_topic.items()):
        n = sum(p["brand"]["n"] for p in ps)
        # rate() stores k/n; k is recovered exactly by rounding.
        k = sum(
            round(p["brand"]["value"] * p["brand"]["n"])
            for p in ps
            if p["brand"]["value"] is not None
        )
        tops = Counter(
            p["top_competitor"]["name"] for p in ps if p["top_competitor"]
        )
        top = tops.most_common(1)[0][0] if tops else "—"
        rows.append([topic, str(len(ps)), fmt_rate(rate(k, n)), top])
    return rows


def build_content(
    s: Session, brand: m.Brand, days: int, to: datetime
) -> Document:
    period, sections, versions = _opening(s, brand, days, to)
    f = _window(period)
    gap_rows = []
    for c in _gap_rows(s, brand.id, f):
        b = c["brief"] or {}
        gap_rows.append(
            [
                c["topic"],
                str(b.get("page_type", "—")),
                "; ".join(b.get("structure", [])[:3]) or "—",
                str(b.get("prompts_total", len(c["prompts"]))),
            ]
        )
    page_rows = []
    for a in _latest_page_audits(s, brand.id):
        sug = a.suggestions or {}
        first = next(
            (
                str(x.get("text", ""))
                for key in ("add", "rewrite", "remove", "evidence_to_add")
                for x in sug.get(key, [])
                if x.get("text")
            ),
            "—",
        )
        page_rows.append([a.url, str(a.score), first])
    sections += [
        Section(
            heading="Prompt performance by topic",
            blocks=[
                table_or_empty(
                    ["Topic", "Prompts", "Mention rate", "Top rival"],
                    _topic_rows(s, brand.id, f),
                    "answered prompts",
                )
            ],
        ),
        Section(
            heading="Content gaps with briefs",
            blocks=[
                table_or_empty(
                    ["Topic", "Page type", "Structure", "Prompts"],
                    gap_rows,
                    "content gaps",
                )
            ],
        ),
        Section(
            heading="Page citability with next step",
            blocks=[
                table_or_empty(
                    ["URL", "Score", "Next step"], page_rows, "scored pages"
                )
            ],
        ),
        _rec_section(
            "Recommendations",
            _open_recommendations(s, brand.id, CONTENT_REC_TYPES),
        ),
    ]
    return Document(
        title=f"{brand.name}: content report",
        brand=brand.name,
        type="content",
        period=period,
        sections=sections,
        footer=footer(versions, to),
    )


_MENTIONS = (
    "FROM mention mn JOIN observation o ON o.id = mn.observation_id "
    "WHERE o.status = 'done' AND mn.entity_type = 'brand' AND "
)


def build_pr(s: Session, brand: m.Brand, days: int, to: datetime) -> Document:
    period, sections, versions = _opening(s, brand, days, to)
    f = _window(period)
    where, params = _where(brand.id, f)
    mix = s.execute(
        text(
            "SELECT mn.sentiment, count(*) AS k "
            + _MENTIONS
            + where
            + " GROUP BY mn.sentiment ORDER BY k DESC, mn.sentiment"
        ),
        params,
    ).all()
    total = sum(r.k for r in mix)
    mix_rows = [
        [r.sentiment, str(r.k), fmt_rate(rate(r.k, total))] for r in mix
    ]
    negatives = s.execute(
        text(
            "SELECT o.requested_at, p.text, mn.evidence_sentence "
            "FROM mention mn JOIN observation o ON o.id = mn.observation_id "
            "JOIN prompt p ON p.id = o.prompt_id "
            "WHERE o.status = 'done' AND mn.entity_type = 'brand' "
            "AND mn.sentiment = 'negative' AND "
            + where
            + " ORDER BY o.requested_at DESC, mn.id LIMIT :cap"
        ),
        {**params, "cap": NEGATIVE_ROWS},
    ).all()
    neg_rows = [
        [fmt_day(r.requested_at), r.text, r.evidence_sentence or "—"]
        for r in negatives
    ]
    comp_rows = [
        [
            e["name"],
            fmt_rate(e["sentiment"]["positive"]),
            fmt_rate(e["sentiment"]["negative"]),
            fmt_signed(e["sentiment"]["index"]),
        ]
        for e in entity_metrics(s, brand.id, f)[:COMPETITOR_ROWS]
        # With no answers every row is "— (n=0)": nothing to show.
        if e["mention_rate"]["n"]
    ]
    third_rows = [
        [x["domain"], str(x["answers"]), str(x["prompts"])]
        for x in sources(s, brand.id, f)
        if x["brand_named"] and x["owner"] == "third_party"
    ][:SEO_SOURCE_ROWS]
    new_rows = [
        [
            str(a.detail.get("domain", a.subject_key)),
            a.title,
            f"{fmt_day(a.window_from)} to {fmt_day(a.window_to)}",
        ]
        for a in _alerts_in(s, brand.id, period, "new_source")
    ]
    sections += [
        Section(
            heading="Sentiment mix",
            blocks=[
                table_or_empty(
                    ["Sentiment", "Mentions", "Share"], mix_rows, "mentions"
                )
            ],
        ),
        Section(
            heading="Negative mentions",
            blocks=[
                table_or_empty(
                    ["Date", "Prompt", "Evidence"],
                    neg_rows,
                    "negative mentions",
                )
            ],
        ),
        Section(
            heading="Competitor sentiment",
            blocks=[
                table_or_empty(
                    ["Entity", "Positive", "Negative", "Index"],
                    comp_rows,
                    "mentions",
                )
            ],
        ),
        Section(
            heading="Third-party sources naming the brand",
            blocks=[
                table_or_empty(
                    ["Domain", "Answers", "Prompts"],
                    third_rows,
                    "third-party sources naming the brand",
                )
            ],
        ),
        Section(
            heading="New sources in period",
            blocks=[
                table_or_empty(
                    ["Domain", "Alert", "Window"], new_rows, "new sources"
                )
            ],
        ),
    ]
    return Document(
        title=f"{brand.name}: PR report",
        brand=brand.name,
        type="pr",
        period=period,
        sections=sections,
        footer=footer(versions, to),
    )


BUILDERS: dict[str, Builder] = {
    "cmo": build_cmo,
    "seo": build_seo,
    "content": build_content,
    "pr": build_pr,
    "agency": build_agency,
}

WEEKLY_DAYS = 7
MONTHLY_DAYS = 30


def days_for(cadence: str) -> int:
    return MONTHLY_DAYS if cadence == "monthly" else WEEKLY_DAYS


def new_token() -> str:
    return secrets.token_urlsafe(32)


def definition(
    s: Session, org_id: uuid.UUID, brand_id: uuid.UUID, type_: str
) -> m.Report:
    """The (brand, type) definition row, created with cadence off if
    absent. ON CONFLICT DO NOTHING so two first runs cannot collide."""
    s.execute(
        pg_insert(m.Report)
        .values(org_id=org_id, brand_id=brand_id, type=type_)
        .on_conflict_do_nothing(constraint="uq_report_brand_type")
    )
    return s.scalars(
        select(m.Report).where(
            m.Report.brand_id == brand_id, m.Report.type == type_
        )
    ).one()


def generate(
    s: Session,
    org_id: uuid.UUID,
    brand_id: uuid.UUID,
    type_: str,
    *,
    days: int,
    to: datetime,
    source: str,
) -> m.ReportRun:
    """Build and store one run. SQL only: no HTTP, no model call, no
    spend. Runs inside the caller's tenant session; never stamps
    report.generated_at (the worker does that for scheduled runs)."""
    brand = s.get_one(m.Brand, brand_id)
    rep = definition(s, org_id, brand_id, type_)
    doc = BUILDERS[type_](s, brand, days, to)
    run = m.ReportRun(
        org_id=org_id,
        brand_id=brand_id,
        report_id=rep.id,
        type=type_,
        source=source,
        period_from=to - timedelta(days=days),
        period_to=to,
        compare_from=to - timedelta(days=2 * days),
        document=doc.model_dump(mode="json", by_alias=True),
        methodology_version=METHODOLOGY_VERSION,
        share_token=new_token(),
    )
    s.add(run)
    s.flush()
    return run
