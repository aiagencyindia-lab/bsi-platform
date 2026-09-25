"""Pure functions of the product-title wedge (slice 18)."""

import gzip
import hashlib
from types import SimpleNamespace

from bsi_core.products import (
    EXPORT_COLUMNS,
    export_rows,
    parse_attributes,
    parse_csv,
    parse_feed,
)

CSV = (
    "Title,Id,Description,Attributes,LINK,Price,Category,material\n"
    "Walkaroo Boys Sandal,W-1,Light sandal,Size: 10; Color: Blue,"
    "https://walkaroo.in/p/1,499 INR,Sandals,EVA\n"
    "No id row,,,,,,,\n"
    ",W-3,Missing title,,,,,\n"
    "Url only,,,,https://walkaroo.in/p/4,,,\n"
)


def test_parse_csv_maps_headers_case_insensitively():
    rows, skipped = parse_csv(CSV)
    assert skipped == 1
    first = rows[0]
    assert first["external_id"] == "W-1"
    assert first["title"] == "Walkaroo Boys Sandal"
    assert first["description"] == "Light sandal"
    assert first["url"] == "https://walkaroo.in/p/1"
    assert first["price"] == "499 INR"
    assert first["category"] == "Sandals"
    assert first["attributes"] == {
        "size": "10",
        "color": "blue",
        "material": "EVA",
    }


def test_parse_csv_external_id_falls_back_to_url_then_title_hash():
    rows, _ = parse_csv(CSV)
    by_title = {r["title"]: r for r in rows}
    assert by_title["Url only"]["external_id"] == "https://walkaroo.in/p/4"
    expected = hashlib.sha1(b"No id row").hexdigest()
    assert by_title["No id row"]["external_id"] == expected
    assert by_title["No id row"]["description"] is None


def test_parse_attributes_splits_on_semicolon_and_colon():
    assert parse_attributes("Size: 10; Color: Blue; junk") == {
        "size": "10",
        "color": "blue",
    }
    assert parse_attributes("") == {}


RSS = b"""<?xml version="1.0"?>
<rss xmlns:g="http://base.google.com/ns/1.0" version="2.0"><channel>
<title>Feed</title>
<item><g:id>F-1</g:id><title>Kids Sandal Red</title>
<description>Soft sandal</description><link>https://x.in/1</link>
<g:price>799.00 INR</g:price>
<g:product_type>Footwear &gt; Sandals</g:product_type>
<g:color>Red</g:color><g:brand>Walkaroo</g:brand></item>
<item><g:id>F-2</g:id><title>Kids Sandal Blue</title>
<link>https://x.in/2</link><g:google_product_category>187</g:google_product_category>
</item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:g="http://base.google.com/ns/1.0">
<entry><g:id>A-1</g:id><title>Atom sandal</title>
<link href="https://x.in/a1"/><g:price>10 USD</g:price></entry>
</feed>"""


def test_parse_feed_reads_rss_items():
    rows, note = parse_feed(RSS)
    assert note is None
    assert [r["external_id"] for r in rows] == ["F-1", "F-2"]
    first = rows[0]
    assert first["title"] == "Kids Sandal Red"
    assert first["description"] == "Soft sandal"
    assert first["url"] == "https://x.in/1"
    assert first["price"] == "799.00 INR"
    assert first["category"] == "Footwear > Sandals"
    assert first["attributes"] == {"color": "Red", "brand": "Walkaroo"}
    assert rows[1]["category"] == "187"
    assert rows[1]["attributes"] == {}


def test_parse_feed_reads_atom_entries_and_link_href():
    rows, note = parse_feed(ATOM)
    assert note is None
    assert len(rows) == 1
    assert rows[0]["external_id"] == "A-1"
    assert rows[0]["url"] == "https://x.in/a1"
    assert rows[0]["price"] == "10 USD"


def test_parse_feed_inflates_gzip():
    rows, note = parse_feed(gzip.compress(RSS))
    assert note is None and len(rows) == 2


def test_parse_feed_cut_mid_item_keeps_complete_items():
    cut = RSS[: RSS.index(b"<item><g:id>F-2") + 30]
    rows, note = parse_feed(cut)
    assert [r["external_id"] for r in rows] == ["F-1"]
    assert note == "malformed"


def test_export_rows_joins_lists_and_blanks_none():
    p = SimpleNamespace(
        external_id="W-1",
        url=None,
        title="Walkaroo Boys Sandal",
        keyword="kids sandals",
        missing_keywords=["summer", "kids"],
        suggested_title="Walkaroo Kids Summer Sandal for Boys",
        suggested_bullets=["Light EVA sole", "Washable"],
        rule_check="pass",
    )
    q = SimpleNamespace(
        external_id="W-2",
        url="https://walkaroo.in/p/2",
        title="Other",
        keyword=None,
        missing_keywords=None,
        suggested_title=None,
        suggested_bullets=None,
        rule_check=None,
    )
    assert EXPORT_COLUMNS == [
        "external_id",
        "url",
        "title",
        "keyword",
        "missing_keywords",
        "suggested_title",
        "suggested_bullets",
        "rule_check",
    ]
    assert export_rows([p, q]) == [
        [
            "W-1",
            "",
            "Walkaroo Boys Sandal",
            "kids sandals",
            "summer|kids",
            "Walkaroo Kids Summer Sandal for Boys",
            "Light EVA sole|Washable",
            "pass",
        ],
        ["W-2", "https://walkaroo.in/p/2", "Other", "", "", "", "", ""],
    ]
