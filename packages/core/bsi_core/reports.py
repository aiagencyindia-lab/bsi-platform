"""Reports: a frozen document per run, built from the same metric
functions the dashboard uses, so report and API agree for one window.

Every cell is a pre-formatted string, so the HTML page and the PDF only
render. No links or ids: readers are outside the app. Fixed copy only.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models as m
from .citations import sources
from .competitors import entity_metrics
from .metrics import DELTA_METRICS, Filters, brand_deltas, brand_sov
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
            fmt_pct(e["sov"]["value"]),
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
            heading="Alerts",
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
