from datetime import UTC, datetime

from bsi_core.reports import (
    METHODOLOGY_VERSION,
    Document,
    Paragraph,
    Period,
    Section,
    Table,
    fmt_delta,
    fmt_pct,
    fmt_rate,
    fmt_signed,
    footer,
    table_or_empty,
)

AT = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)


def test_fmt_rate_prints_value_interval_and_n():
    r = {"value": 0.4166, "n": 12, "ci_low": 0.194, "ci_high": 0.6749}
    assert fmt_rate(r) == "0.42 [0.19, 0.67] n=12"
    assert fmt_rate({"value": None, "n": 0, "ci_low": 0, "ci_high": 1}) == (
        "— (n=0)"
    )


def test_fmt_delta_prints_signed_interval_and_label():
    d = {"value": -0.09, "ci_low": -0.18, "ci_high": 0.005, "label": "x"}
    assert fmt_delta(d) == "-0.09 [-0.18, +0.01] x"
    assert fmt_delta({"value": None, "label": "insufficient data"}) == (
        "insufficient data"
    )
    assert fmt_delta(None) == "—"


def test_fmt_pct_and_signed():
    assert fmt_pct(0.1234) == "12.3%" and fmt_pct(None) == "—"
    assert fmt_signed(0.25) == "+0.25" and fmt_signed(None) == "—"


def test_footer_names_methodology_and_pipeline_versions():
    f = footer(["2"], AT)
    assert f.startswith(f"Methodology v{METHODOLOGY_VERSION} · pipeline v2")
    assert "95% Wilson" in f and "95% Newcombe" in f
    assert f.endswith("generated 2026-09-25 09:00 UTC")
    assert "pipeline v1, 2" in footer(["2", "1"], AT)
    assert "pipeline v—" in footer([], AT)


def test_table_or_empty():
    assert table_or_empty(["a"], [], "cited sources") == Paragraph(
        text="No cited sources in this period."
    )
    t = table_or_empty(["a"], [["1"]], "x")
    assert isinstance(t, Table) and t.rows == [["1"]]


def test_document_round_trips_through_json_with_from_alias():
    doc = Document(
        title="t",
        brand="Nike",
        type="cmo",
        period=Period(from_=AT, to=AT, compare_from=AT),
        sections=[Section(heading="h", blocks=[Paragraph(text="p")])],
        footer="f",
    )
    data = doc.model_dump(mode="json", by_alias=True)
    assert data["period"]["from"] == "2026-09-25T09:00:00Z"
    assert data["sections"][0]["blocks"][0] == {"kind": "p", "text": "p"}
    assert Document.model_validate(data) == doc
