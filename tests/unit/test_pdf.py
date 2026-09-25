import re
import time
from datetime import UTC, datetime

from bsi_core.pdf import render_pdf
from bsi_core.reports import (
    Branding,
    Document,
    Paragraph,
    Period,
    Section,
    Table,
)
from reportlab import rl_config

AT = datetime(2026, 9, 25, tzinfo=UTC)
PAGE = re.compile(rb"/Type\s*/Page(?!s)")


def _doc(rows: int, sections: int = 1, branding=None) -> Document:
    table = Table(
        columns=["Domain", "Owner", "Answers"],
        rows=[
            [f"site-{i}.example.com/a/long/path", "third_party", str(i)]
            for i in range(rows)
        ],
    )
    return Document(
        title="Nike: CMO summary",
        brand="Nike",
        type="cmo",
        period=Period(from_=AT, to=AT, compare_from=AT),
        branding=branding,
        sections=[
            Section(
                heading=f"Section {j}",
                blocks=[Paragraph(text="p & <q>"), table],
            )
            for j in range(sections)
        ],
        footer="Methodology v1 · pipeline v2",
    )


def test_small_document_is_one_page_pdf():
    pdf = render_pdf(_doc(3))
    assert pdf.startswith(b"%PDF-") and len(PAGE.findall(pdf)) == 1


def test_long_table_spans_pages():
    assert len(PAGE.findall(render_pdf(_doc(300)))) > 1


def test_branding_accent_and_escaping_do_not_break_rendering(monkeypatch):
    # Uncompressed page streams so the prepared-by text is findable.
    monkeypatch.setattr(rl_config, "pageCompression", 0)
    pdf = render_pdf(
        _doc(2, branding=Branding(accent="#112233", prepared_by="Acme"))
    )
    assert pdf.startswith(b"%PDF-") and b"Prepared by Acme" in pdf


def test_invalid_accent_falls_back_instead_of_crashing():
    pdf = render_pdf(_doc(2, branding=Branding(accent="not-a-colour")))
    assert pdf.startswith(b"%PDF-")


def test_twenty_pages_render_within_the_prd_budget():
    start = time.monotonic()
    pdf = render_pdf(_doc(60, sections=16))
    assert time.monotonic() - start < 30
    assert len(PAGE.findall(pdf)) >= 20
