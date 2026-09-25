"""Reports: a frozen document per run, built from the same metric
functions the dashboard uses, so report and API agree for one window.

Every cell is a pre-formatted string, so the HTML page and the PDF only
render. No links or ids: readers are outside the app. Fixed copy only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
