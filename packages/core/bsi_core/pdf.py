"""PDF rendering of a report Document with reportlab. Pure function of
the stored document: nothing is fetched and nothing is written to disk.
No logo in the PDF (an image fetch inside a request is out); the accent
colour and the prepared-by line carry the branding."""

import io
import re
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .reports import Document, fmt_day

MARGIN = 15 * mm
WIDTH = A4[0] - 2 * MARGIN
HEX = re.compile(r"#[0-9a-fA-F]{6}")


def render_pdf(doc: Document) -> bytes:
    styles = getSampleStyleSheet()
    # The API validates #rrggbb, but a brand row may hold anything.
    raw = doc.branding.accent if doc.branding else None
    accent = (
        colors.HexColor(raw) if raw and HEX.fullmatch(raw) else colors.black
    )
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=accent)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=accent)
    body = styles["BodyText"]
    cell = ParagraphStyle("cell", parent=body, fontSize=8, leading=10)
    footer = doc.footer

    def on_page(canvas: Any, d: Any) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(MARGIN, 10 * mm, footer[:180])
        canvas.drawRightString(A4[0] - MARGIN, 10 * mm, f"page {d.page}")
        canvas.restoreState()

    story: list[Any] = [
        Paragraph(escape(doc.title), h1),
        Paragraph(
            escape(f"{fmt_day(doc.period.from_)} to {fmt_day(doc.period.to)}"),
            body,
        ),
        Spacer(1, 4 * mm),
    ]
    if doc.branding and doc.branding.prepared_by:
        story.insert(
            2,
            Paragraph(escape(f"Prepared by {doc.branding.prepared_by}"), body),
        )
    for sec in doc.sections:
        blocks = [_block(b, body, cell) for b in sec.blocks]
        story.append(
            KeepTogether([Paragraph(escape(sec.heading), h2), *blocks[:1]])
        )
        story += blocks[1:]
        story.append(Spacer(1, 3 * mm))
    buf = io.BytesIO()
    pdf = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=18 * mm,
        title=doc.title,
    )
    pdf.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()


def _block(b: Any, body: ParagraphStyle, cell: ParagraphStyle) -> Any:
    if b.kind == "p":
        return Paragraph(escape(b.text), body)
    data = [[Paragraph(escape(c), cell) for c in b.columns]]
    data += [[Paragraph(escape(c), cell) for c in row] for row in b.rows]
    widths = [WIDTH / len(b.columns)] * len(b.columns)
    t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return t
