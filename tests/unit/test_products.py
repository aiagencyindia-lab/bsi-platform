"""Pure functions of the product-title wedge (slice 18)."""

import gzip
import hashlib
from types import SimpleNamespace

from bsi_core.products import (
    EXPORT_COLUMNS,
    KeywordSet,
    RewriteSet,
    TitleSet,
    drop_brand_terms,
    export_rows,
    keep_present,
    keyword_prompt,
    missing,
    parse_attributes,
    parse_csv,
    parse_feed,
    rewrite_prompt,
    rule_check,
    titles_prompt,
    vote,
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


def test_export_rows_neutralises_formula_cells():
    p = SimpleNamespace(
        external_id="W-1",
        url=None,
        title="=HYPERLINK(1)",
        keyword=None,
        missing_keywords=["-x", "ok"],
        suggested_title="+cmd",
        suggested_bullets=None,
        rule_check=None,
    )
    row = export_rows([p])[0]
    assert row[2] == "'=HYPERLINK(1)"
    assert row[5] == "'+cmd"
    assert row[4] == "'-x|ok"


BRAND = ("Walkaroo", "WKR")


def test_vote_picks_the_most_frequent_rank_one():
    samples = [
        ["kids shoes", "running shoes"],
        ["kids shoes"],
        ["running shoes", "kids shoes"],
    ]
    assert vote(samples) == ["kids shoes", "running shoes"]


def test_vote_ties_go_to_the_first_sample_and_cap_at_five():
    samples = [["a", "b", "c"], ["d", "e", "f"], ["g", "h"]]
    assert vote(samples) == ["a", "b", "c", "d", "e"]
    assert vote([[], [], []]) == []


def test_drop_brand_terms_matches_tokens():
    assert drop_brand_terms(
        ["walkaroo sandals", "kids sandals", "wkr shoes"], BRAND
    ) == ["kids sandals"]
    assert drop_brand_terms(["walkaroo sandals"], BRAND) == []
    # A keyword with no tokens is dropped too: it would be stored as "".
    assert drop_brand_terms(["", "!!!", "kids shoes"], BRAND) == ["kids shoes"]


TITLES = [
    "Kids Sandals for Boys Summer Sandal",
    "Boys Summer Sandals Lightweight",
    "Summer Sandals Kids",
]


def test_missing_keywords_need_two_titles_and_skip_present_tokens():
    assert missing("Walkaroo Boys Sandal Blue", TITLES, BRAND) == [
        "sandals",
        "summer",
        "kids",
    ]


def test_missing_skips_brand_stopwords_numbers_and_caps_at_eight():
    titles = [
        "walkaroo for online 2024 alpha beta gamma delta eps zeta eta "
        "theta iota",
        "walkaroo for online 2024 alpha beta gamma delta eps zeta eta "
        "theta iota",
    ]
    out = missing("Plain", titles, BRAND)
    assert len(out) == 8
    for bad in ("walkaroo", "for", "online", "2024"):
        assert bad not in out


def test_rule_check_removes_repeated_tokens():
    assert rule_check(
        "Walkaroo Kids Shoes", "Walkaroo Kids Shoes Shoes", BRAND
    ) == (
        "Walkaroo Kids Shoes",
        "adjusted",
    )


def test_rule_check_restores_the_brand_the_original_had():
    assert rule_check("Walkaroo Boys Sandal", "Boys Summer Sandal", BRAND) == (
        "Walkaroo Boys Summer Sandal",
        "adjusted",
    )
    # The original had no brand: none is added.
    assert rule_check("Boys Sandal", "Boys Summer Sandal", BRAND) == (
        "Boys Summer Sandal",
        "pass",
    )


def test_rule_check_trims_to_150_at_a_word_boundary():
    words = [f"w{i}" for i in range(60)]  # "w0 w1 ... w59" = 229 chars
    fixed, status = rule_check("Plain", " ".join(words), BRAND)
    assert status == "adjusted"
    assert len(fixed) <= 150
    assert fixed == " ".join(words)[: len(fixed)]
    assert not fixed.endswith(" ") and fixed.split()[-1] in words


def test_rule_check_passes_an_unchanged_suggestion():
    assert rule_check(
        "Walkaroo Boys Sandal", "Walkaroo Boys Summer Sandal", BRAND
    ) == (
        "Walkaroo Boys Summer Sandal",
        "pass",
    )


def test_keep_present_drops_titles_absent_from_the_text():
    text = "Top picks:\n1. **Kids  Sandals for Boys** on amazon.in\n2. other"
    titles = [
        {"title": "Kids Sandals for Boys", "domain": "Amazon.in"},
        {"title": "Invented Sandal", "domain": "x.in"},
    ]
    assert keep_present(titles, text) == [
        {"title": "Kids Sandals for Boys", "domain": "amazon.in"}
    ]


def test_prompts_carry_the_inputs_and_parse_with_their_schemas():
    products = [
        {
            "index": 0,
            "title": "Walkaroo Boys Sandal",
            "description": "Light sandal",
            "attributes": {"color": "blue"},
            "category": "Sandals",
            "keyword": "kids sandals",
            "missing": ["summer"],
        }
    ]
    kp = keyword_prompt("Walkaroo", products)
    assert "Walkaroo Boys Sandal" in kp and "Light sandal" in kp
    KeywordSet.model_validate_json(
        '{"products": [{"index": 0, "keywords": ["kids sandals"]}]}'
    )
    tp = titles_prompt("kids sandals", "answer text", ["amazon.in"])
    assert "kids sandals" in tp and "answer text" in tp and "amazon.in" in tp
    TitleSet.model_validate_json(
        '{"titles": [{"title": "Kids Sandals", "domain": "amazon.in"}]}'
    )
    rp = rewrite_prompt("Walkaroo", products)
    assert "summer" in rp and "150" in rp
    RewriteSet.model_validate_json(
        '{"products": [{"index": 0, "title": "t", "bullets": ["b"]}]}'
    )


def test_rule_check_drops_a_word_that_repeats_an_earlier_token():
    assert rule_check(
        "Walkaroo Kids-Sandal", "Walkaroo Kids-Sandal Sandal", BRAND
    ) == ("Walkaroo Kids-Sandal", "adjusted")
    # The brand is prepended first, then the repeated token is dropped.
    assert rule_check("Red Tape Boots", "Tape Shoes", ("Red Tape",)) == (
        "Red Tape Shoes",
        "adjusted",
    )


def test_rule_check_keeps_punctuation_only_words():
    assert rule_check("Walkaroo Sandal", "Walkaroo - Sandal | Kids", BRAND) == (
        "Walkaroo - Sandal | Kids",
        "pass",
    )
