"""Product-title wedge (PRD F16): import a catalogue, infer each
product's generic shopper keyword, compare its title with the titles that
rank for that keyword, and rewrite it.

Parsing, voting, the missing-keyword rule and the rule check are pure.
`run_products` orchestrates the job in short tenant sessions, with no
transaction open during a model call, the `suggest_competitors` shape.
"""

import csv
import hashlib
import io
import xml.etree.ElementTree as ET
import zlib
from collections.abc import Iterable
from functools import partial
from typing import Any

from .crawl import Fetch, http_fetch

MAX_PRODUCTS = 1_000  # per brand, the PRD's run ceiling
CSV_MAX_BYTES = 4 * 1024 * 1024
FEED_CAP_BYTES = 8 * 1024 * 1024
FEED_FETCH: Fetch = partial(http_fetch, cap=FEED_CAP_BYTES, raw=True)

# CSV header (lowercased) -> row key. Any other header is an attribute.
CSV_FIELDS = {
    "id": "external_id",
    "title": "title",
    "description": "description",
    "url": "url",
    "link": "url",
    "price": "price",
    "category": "category",
}
# Merchant feed tags (namespace stripped) kept as attributes.
FEED_ATTRS = (
    "brand",
    "color",
    "size",
    "material",
    "gender",
    "age_group",
    "condition",
)
EXPORT_COLUMNS = [
    "external_id",
    "url",
    "title",
    "keyword",
    "missing_keywords",
    "suggested_title",
    "suggested_bullets",
    "rule_check",
]


class CatalogueCap(ValueError):
    """An import would take the brand past MAX_PRODUCTS."""


def _external_id(row: dict[str, Any]) -> str:
    return str(
        row.get("external_id")
        or row.get("url")
        or hashlib.sha1(str(row["title"]).encode()).hexdigest()
    )


def parse_attributes(cell: str) -> dict[str, str]:
    """`Size: 10; Color: Blue` -> {"size": "10", "color": "blue"}. A
    fragment without a colon is dropped."""
    out: dict[str, str] = {}
    for frag in cell.split(";"):
        key, sep, value = frag.partition(":")
        if sep and key.strip():
            out[key.strip().lower()] = value.strip().lower()
    return out


def _blank_row() -> dict[str, Any]:
    return {
        "external_id": None,
        "title": None,
        "description": None,
        "attributes": {},
        "url": None,
        "price": None,
        "category": None,
    }


def parse_csv(text: str) -> tuple[list[dict[str, Any]], int]:
    """(rows, rows skipped for an empty title). Headers are matched
    case-insensitively after stripping; unknown headers become
    attributes keyed by the lowercased header."""
    rows: list[dict[str, Any]] = []
    skipped = 0
    for raw in csv.DictReader(io.StringIO(text)):
        row = _blank_row()
        for header, cell in raw.items():
            if header is None:  # a row with more cells than headers
                continue
            key = header.strip().lower()
            value = (cell or "").strip()
            if key == "attributes":
                row["attributes"].update(parse_attributes(value))
            elif key in CSV_FIELDS:
                row[CSV_FIELDS[key]] = value or None
            elif key and value:
                row["attributes"][key] = value
        if not row["title"]:
            skipped += 1
            continue
        row["external_id"] = _external_id(row)
        rows.append(row)
    return rows, skipped


def _feed_row(fields: dict[str, str]) -> dict[str, Any] | None:
    title = fields.get("title")
    if not title:
        return None
    row = _blank_row()
    row.update(
        external_id=fields.get("id") or None,
        title=title,
        description=fields.get("description") or None,
        url=fields.get("link") or None,
        price=fields.get("price") or None,
        category=fields.get("product_type")
        or fields.get("google_product_category")
        or None,
        attributes={k: fields[k] for k in FEED_ATTRS if fields.get(k)},
    )
    row["external_id"] = _external_id(row)
    return row


def parse_feed(body: bytes) -> tuple[list[dict[str, Any]], str | None]:
    """(rows, note). Reads RSS <item> and Atom <entry> elements with the
    XMLPullParser pattern of rivals.parse_sitemap: namespaces are
    stripped, so g:id and id both read as "id"; an Atom <link href> is
    read from the attribute. Gzip is inflated under FEED_CAP_BYTES.
    Malformed or cut XML returns what was read, with note "malformed"."""
    note: str | None = None
    if body[:2] == b"\x1f\x8b":
        z = zlib.decompressobj(47)
        try:
            body = z.decompress(body, FEED_CAP_BYTES)
        except zlib.error:
            return [], "gzip error"
        if z.unconsumed_tail:
            note = "truncated"
    parser: ET.XMLPullParser[ET.Element] = ET.XMLPullParser(
        events=("start", "end")
    )
    rows: list[dict[str, Any]] = []
    depth = 0
    entry_depth = 0
    closed = False  # the root's end event arrived
    fields: dict[str, str] = {}
    try:
        parser.feed(body)
        for ev in parser.read_events():
            event, el = ev[0], ev[-1]
            if not isinstance(el, ET.Element):
                continue
            tag = str(el.tag).rsplit("}", 1)[-1]
            if event == "start":
                depth += 1
                if tag in ("item", "entry") and not entry_depth:
                    entry_depth, fields = depth, {}
                continue
            if entry_depth and depth == entry_depth:
                row = _feed_row(fields)
                if row:
                    rows.append(row)
                entry_depth = 0
                el.clear()
            elif entry_depth and depth == entry_depth + 1:
                value = (el.text or "").strip()
                if tag == "link" and not value:
                    value = (el.get("href") or "").strip()
                fields.setdefault(tag, value)
            elif depth == 1:
                closed = True
            depth -= 1
    except ET.ParseError:
        note = note or "malformed"
    if not closed:  # feed() does not raise on a cut body; close() would
        note = note or "malformed"
    return rows, note


def export_rows(products: Iterable[Any]) -> list[list[str]]:
    """One CSV row per product in EXPORT_COLUMNS order; lists are
    '|'-joined and None is blank."""

    def cell(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return "|".join(str(v) for v in value)
        return str(value)

    return [[cell(getattr(p, c)) for c in EXPORT_COLUMNS] for p in products]
