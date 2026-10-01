"""Pure functions of the product-title wedge (slice 18)."""

import gzip
import hashlib
from types import SimpleNamespace

import pytest
from bsi_core.products import (
    CONNECTORS,
    EXPORT_COLUMNS,
    KeywordSet,
    RewriteSet,
    TitleSet,
    _type_word,
    choose_keywords,
    drop_brand_terms,
    drop_noise_terms,
    drop_stores,
    dropped,
    export_rows,
    fit_rank,
    fold,
    keep_present,
    keyword_key,
    keyword_prompt,
    missing,
    parse_attributes,
    parse_csv,
    parse_feed,
    rewrite_prompt,
    rule_check,
    search_query,
    title_first,
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
        dropped_words=["casual"],
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
        dropped_words=None,
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
        "dropped_words",
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
            "casual",
        ],
        ["W-2", "https://walkaroo.in/p/2", "Other", "", "", "", "", "", ""],
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
        dropped_words=None,
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
        "pass",
        [],
    )


def test_rule_check_restores_the_brand_the_original_had():
    assert rule_check(
        "Walkaroo Boys Sandal",
        "Boys Summer Sandal",
        BRAND,
        allowed=["Summer"],
    ) == (
        "Walkaroo Boys Summer Sandal",
        "adjusted",
        [],
    )
    # The original had no brand: none is added.
    assert rule_check(
        "Boys Sandal", "Boys Summer Sandal", BRAND, allowed=["Summer"]
    ) == (
        "Boys Summer Sandal",
        "pass",
        [],
    )


def test_rule_check_trims_to_150_at_a_word_boundary():
    words = [f"w{i}" for i in range(60)]  # "w0 w1 ... w59" = 229 chars
    fixed, status, lost = rule_check(
        "Plain", " ".join(words), BRAND, allowed=[" ".join(words)]
    )
    # The lost "Plain" is restored at the start, then the trim applies.
    assert status == "adjusted" and lost == []
    assert len(fixed) <= 150
    assert fixed.removeprefix("Plain ") == " ".join(words)[: len(fixed) - 6]
    assert not fixed.endswith(" ") and fixed.split()[-1] in words


def test_rule_check_trim_can_still_lose_a_restored_word():
    words = [f"w{i}" for i in range(60)]
    fixed, status, lost = rule_check(
        "w59 Plain", " ".join(words), BRAND, allowed=[" ".join(words)]
    )
    assert (status, lost, len(fixed)) == ("review", ["w59", "plain"], 149)


def test_rule_check_passes_an_unchanged_suggestion():
    assert rule_check(
        "Walkaroo Boys Sandal",
        "Walkaroo Boys Summer Sandal",
        BRAND,
        allowed=["Summer"],
    ) == (
        "Walkaroo Boys Summer Sandal",
        "pass",
        [],
    )


def test_keep_present_drops_titles_absent_from_the_text():
    text = "Top picks:\n1. **Kids  Sandals for Boys** on amazon.in\n2. other"
    titles = [
        {"title": "Kids Sandals for Boys", "domain": "Amazon.in"},
        {"title": "Invented Sandal", "domain": "x.in"},
    ]
    assert keep_present(titles, text) == [
        {
            "title": "Kids Sandals for Boys",
            "domain": "amazon.in",
            "brand": "",
            "model": "",
            "parse": 2,
        }
    ]


TEVA_KIDS = "Teva Hurricane XLT 2 Sandals - Kids'"


def test_keep_present_keeps_a_brand_and_model_named_in_the_title():
    got = keep_present(
        [
            {
                "title": TEVA_KIDS,
                "domain": "",
                "brand": "Teva",
                "model": "Hurricane XLT 2",
            }
        ],
        f"Try the {TEVA_KIDS} today.",
    )
    assert (got[0]["brand"], got[0]["model"]) == ("Teva", "Hurricane XLT 2")


def test_keep_present_blanks_a_brand_not_in_the_title():
    title = "Teva Original Universal Sandals"
    got = keep_present(
        [
            {
                "title": title,
                "domain": "",
                "brand": "Nike",
                "model": "Original Universal",
            }
        ],
        f"See {title}.",
    )
    assert (got[0]["brand"], got[0]["model"]) == ("", "Original Universal")


def test_keep_present_model_named_in_title_edge_cases():
    title = "Teva Hurricane XLT 2 Sandals"

    def model(value: str) -> str:
        got = keep_present(
            [{"title": title, "domain": "", "brand": "", "model": value}],
            f"See {title}.",
        )
        return got[0]["model"]

    assert model("-") == ""  # no letters or digits
    assert model("XLT-2") == "XLT-2"  # tokens match across punctuation
    assert model(title) == ""  # the whole title (Ruling R4)


def test_keep_present_without_brand_or_model_keys_stores_empty():
    got = keep_present([{"title": "Kids Sandal", "domain": ""}], "Kids Sandal")
    assert (got[0]["brand"], got[0]["model"]) == ("", "")


TEVA_TITLES = [
    TEVA_KIDS,
    "Teva Hurricane XLT 2 Sandals - Toddlers'",
    "Teva Original Universal Sandals - Kids'",
]


def test_missing_leaves_out_excluded_brand_and_model_words():
    exclude = ["Teva", "Hurricane XLT 2", "Original Universal"]
    got = missing(
        "Blue Boys Sandal", TEVA_TITLES, ["BSOAgentTestBrand"], exclude=exclude
    )
    assert got == ["kids"]
    assert "teva" in missing(
        "Blue Boys Sandal", TEVA_TITLES, ["BSOAgentTestBrand"]
    )


def test_titles_prompt_asks_for_brand_and_model():
    tp = titles_prompt("kids sandals", "answer text", ["amazon.in"])
    assert (
        "For each title also give its brand and its model or product-line name"
        in tp
    )


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
    ) == ("Walkaroo Kids-Sandal", "pass", [])
    # The brand is prepended first, then the repeated token is dropped.
    assert rule_check(
        "Red Tape Boots", "Tape Shoes", ("Red Tape",), allowed=["Shoes"]
    ) == (
        "Red Tape Boots Shoes",
        "adjusted",
        [],
    )


def test_rule_check_repeat_step_can_drop_a_restored_hyphenated_word():
    # "Anti" is kept first, so the restored "Anti-Skid" repeats it and is
    # dropped again: a spec ceiling, the same result as before the restore.
    assert rule_check(
        "Walkaroo Boys Anti-Skid Sandal",
        "Walkaroo Anti Boys Sandal",
        ["Walkaroo"],
    ) == ("Walkaroo Anti Boys Sandal", "review", ["skid"])


def test_rule_check_restore_does_not_bring_back_a_repeat():
    assert rule_check(
        "Walkaroo Anti-Skid Sandal", "Walkaroo Anti Sandal", ["Walkaroo"]
    ) == ("Walkaroo Anti-Skid Sandal", "adjusted", [])
    assert rule_check(
        "Walkaroo Casual Sandal Casual Wear",
        "Walkaroo Sandal Wear",
        ["Walkaroo"],
    ) == ("Walkaroo Casual Sandal Wear", "adjusted", [])


def test_rule_check_does_not_count_a_removed_repeat():
    lc = ["BSOAgentTestBrand"]
    assert rule_check(
        "BSOAgentTestBrand Boys Sandal Blue",
        "BSOAgentTestBrand Blue Kid Sandals Boys Sandal",
        lc,
        allowed=["kids sandals", "kid"],
    ) == ("BSOAgentTestBrand Blue Kid Sandals Boys", "pass", [])
    assert rule_check(
        "BSOAgentTestBrand Men Flip Flop Navy",
        "BSOAgentTestBrand Navy Mens Flip Flops Flip Flop",
        lc,
        allowed=["mens flip flops"],
    ) == ("BSOAgentTestBrand Navy Mens Flip Flops", "pass", [])
    # A repeat plus an unbacked word is still an adjustment.
    assert rule_check(
        "Walkaroo Kids Shoes", "Walkaroo Kids Shoes Shoes Sale", ["Walkaroo"]
    ) == ("Walkaroo Kids Shoes", "adjusted", [])
    # A repeat plus a lost word: the word is restored.
    assert rule_check(
        "Walkaroo Boys Sandal",
        "Walkaroo Kids Sandal Sandal",
        ["Walkaroo"],
        allowed=["kids sandals"],
    ) == ("Walkaroo Boys Kids Sandal", "adjusted", [])


def test_rule_check_keeps_punctuation_only_words():
    assert rule_check(
        "Walkaroo Sandal", "Walkaroo - Sandal | Kids", BRAND, allowed=["Kids"]
    ) == (
        "Walkaroo - Sandal | Kids",
        "pass",
        [],
    )


def test_fold_drops_one_letter_tokens_and_trailing_s():
    assert fold("Men's Sandals") == ["men", "sandal"]
    assert fold("Flip-Flops") == ["flip", "flop"]


def test_rule_check_folds_plurals_and_strips_a_trailing_connector():
    assert rule_check(
        "Walkaroo Boys Sandal Blue",
        "Walkaroo Blue Boys Sandal And Sandals",
        BRAND,
    ) == ("Walkaroo Blue Boys Sandal", "adjusted", [])


def test_rule_check_restores_dropped_words():
    assert rule_check(
        "Men Casual Sandal Brown",
        "Brown Mens Sandal Shoes",
        BRAND,
        allowed=["Shoes"],
    ) == ("Brown Mens Casual Sandal Shoes", "adjusted", [])
    # A replaced product type ends up as both types (spec ceiling).
    assert rule_check(
        "Men Flip Flop Navy", "Navy Men Slipper", BRAND, allowed=["Slipper"]
    ) == (
        "Navy Men Flip Flop Slipper",
        "adjusted",
        [],
    )


def test_dropped_ignores_stopwords_brand_numbers_and_short_tokens():
    assert dropped(
        "Walkaroo Boys Sandal 3 for x", "Walkaroo Sandal", BRAND
    ) == ["boys"]


def test_rule_check_strips_a_connector_the_trim_leaves_at_the_end():
    # "w0 ... w38 for" is 149 characters; " tail" would pass 150, so the
    # cut lands just after "for".
    words = [f"w{i}" for i in range(39)] + ["for", "tail", "end"]
    # The original "w0" is kept, so nothing is restored ahead of the cut.
    fixed, _status, _lost = rule_check(
        "w0", " ".join(words), BRAND, allowed=[" ".join(words)]
    )
    assert len(fixed) <= 150
    assert fixed.split()[-1].casefold() not in CONNECTORS


def test_vote_groups_plural_and_possessive_variants():
    samples = [["men's sandals"], ["mens sandal"], ["men flip flops"]]
    assert vote(samples) == ["men sandals", "men flip flops"]
    assert keyword_key("men's sandals") == keyword_key("mens sandal")


def test_fit_rank_prefers_the_title_then_category_and_drops_misfits():
    title, category = "Men Flip Flop Navy", "Slippers"
    assert fit_rank(
        ["men slippers", "men flip flops"], title, category, None
    ) == [
        "men flip flops",
        "men slippers",
    ]
    assert fit_rank(["men slippers"], title, category, None) == ["men slippers"]
    assert fit_rank(["kids shoes"], title, category, None) == []


def test_prompts_ask_for_plural_kids_keywords_and_kept_words():
    kp = keyword_prompt("Walkaroo", [])
    assert "kids" in kp and "plural" in kp
    assert "Keep every word" in rewrite_prompt("Walkaroo", [])


def test_rewrite_prompt_leaves_keyword_words_out_of_missing():
    rp = rewrite_prompt(
        "Walkaroo",
        [
            {
                "index": 0,
                "title": "Walkaroo Boys Sandal",
                "keyword": "kids sandals",
                "missing": ["kid", "summer"],
            },
            {
                "index": 1,
                "title": "Titan Analog Dial",
                "keyword": "men watches",
                "missing": ["men", "watch", "analog"],
            },
        ],
    )
    assert '"missing": ["summer"]' in rp
    assert '"missing": ["analog"]' in rp
    rp = rewrite_prompt(
        "Walkaroo",
        [
            {
                "index": 0,
                "title": "Walkaroo Boys Sandal",
                "keyword": "kids sandals",
                "missing": ["kid"],
            }
        ],
    )
    assert '"missing"' not in rp


def test_fit_rank_reads_the_category_word_before_a_stopword():
    # R3: "slippers for men" is a slippers phrase, not a men phrase.
    assert fit_rank(
        ["men slippers", "slippers for men", "men flip flops"],
        "Men Flip Flop Navy",
        "Slippers",
        None,
    ) == ["men flip flops", "men slippers", "slippers for men"]
    assert fit_rank(["sandals for kids"], "Boys Sandal Blue", None, None) == [
        "sandals for kids"
    ]


def test_fit_rank_cuts_only_at_for_and_with():
    # R6: "on" and "a" are stopwords (R4) but not category cuts.
    assert fit_rank(
        ["men slip on shoes", "men shoes"], "Men Casual Shoe Black", None, None
    ) == ["men slip on shoes", "men shoes"]
    assert fit_rank(
        ["women pull on boots"], "Women Ankle Boot", None, None
    ) == ["women pull on boots"]
    assert fit_rank(
        ["a line dress for women"], "Blue A Line Dress", None, None
    ) == ["a line dress for women"]


def test_short_stopwords_are_not_flagged_as_dropped():
    # R4: "of" and "in" are not product words.
    assert rule_check(
        "Kurta Set of 3 Blue", "Blue Kurta Set 3 Piece", (), allowed=["Piece"]
    ) == (
        "Blue Kurta Set 3 Piece",
        "pass",
        [],
    )
    assert dropped("Made in India Sandal", "Sandal Made India", ()) == []


def test_search_query_asks_for_products_with_full_titles():
    assert search_query("kids sandals") == (
        "kids sandals: popular products to buy online, "
        "with each product's full title"
    )


def test_titles_prompt_names_the_new_query_and_forbids_stores():
    tp = titles_prompt("kids sandals", "answer text", ["amazon.in"])
    assert search_query("kids sandals") in tp
    assert "buy online." not in tp
    assert (
        "never list a store, retailer, marketplace or brand name on its own"
        in tp
    )


@pytest.mark.parametrize(
    ("title", "domains"),
    [
        ({"title": "Famous Footwear", "domain": "famousfootwear.com"}, []),
        ({"title": "Zappos.com", "domain": "zappos.com"}, []),
        ({"title": "REEF", "domain": "reef.com"}, []),
        ({"title": "Kids Foot Locker", "domain": "www.kidsfootlocker.com"}, []),
        ({"title": "Zappos.com", "domain": ""}, ["zappos.com"]),
        ({"title": "Buy at ShopWSS.com", "domain": "shopwss.com"}, []),
        ({"title": "Zappos", "domain": "https://www.zappos.com/kids"}, []),
    ],
)
def test_drop_stores_drops_a_store_name(title, domains):
    assert drop_stores([title], domains) == []


def test_drop_stores_keeps_product_titles_in_order():
    titles = [
        {"title": "Crocs Classic Clog", "domain": "crocs.com"},
        {"title": "Zappos Kids Sandal", "domain": ""},
        {"title": "Amazon Essentials Sandal", "domain": "amazon"},
        {"title": "Kids Lanner Ridge II Slipper", "domain": ""},
        # The documented ceiling: a store named unlike its domain is left
        # to the prompt. A later fix that catches it flips this case.
        {"title": "Journeys Kidz", "domain": "journeys.com"},
    ]
    assert drop_stores(titles, ["zappos.com"]) == titles


def test_drop_stores_keeps_order_around_a_dropped_title():
    crocs = {"title": "Crocs Classic Clog", "domain": "crocs.com"}
    reef = {"title": "REEF", "domain": "reef.com"}
    lanner = {"title": "Kids Lanner Ridge II Slipper", "domain": ""}
    assert drop_stores([crocs, reef, lanner], []) == [crocs, lanner]


def test_missing_never_suggests_com():
    got = missing(
        "Blue Sandal", ["Zappos com sandal", "ShopWSS com sandal"], []
    )
    assert "com" not in got


def test_titles_prompt_asks_for_the_model_without_the_product_type():
    tp = titles_prompt("kids sandals", "answer text", ["amazon.in"])
    assert "without the product type" in tp


def test_missing_never_excludes_a_keyword_word():
    titles = ["Kids Chase Sandal", "Kids Paley Sandal"]
    exclude = ["Kids Chase", "Kids Paley"]
    assert missing(
        "Boys Sandal", titles, ["X"], exclude=exclude, keyword="kids sandals"
    ) == ["kids"]
    assert missing("Boys Sandal", titles, ["X"], exclude=exclude) == []


def test_missing_skips_colour_and_size_words():
    titles = [
        "Taye Sneaker - Little Kid White",
        "Artie Sneaker - Little Kid White",
    ]
    got = missing("Black Kids Sports Shoe", titles, ["BSOAgentTestBrand"])
    assert got == ["sneaker"]


def test_dropped_still_flags_a_lost_colour():
    assert dropped("Black Shoe", "Shoe", []) == ["black"]


def test_rule_check_drops_an_invented_word():
    assert rule_check(
        "BSOAgentTestBrand Brown Men Casual Sandal",
        "BSOAgentTestBrand Brown Boys Casual Sandal Men",
        ["BSOAgentTestBrand"],
        allowed=["men sandals"],
    ) == ("BSOAgentTestBrand Brown Casual Sandal Men", "adjusted", [])


def test_rule_check_keeps_a_keyword_word():
    assert rule_check(
        "BSOAgentTestBrand Blue Boys Sandal",
        "BSOAgentTestBrand Blue Boys Sandal Kids",
        ["BSOAgentTestBrand"],
        allowed=["kids sandals"],
    ) == ("BSOAgentTestBrand Blue Boys Sandal Kids", "pass", [])


def test_rule_check_keeps_function_words_and_numbers():
    assert rule_check(
        "Walkaroo Sandal 3",
        "Walkaroo Sandal for Kids 3",
        ["Walkaroo"],
        allowed=["kids sandals"],
    ) == ("Walkaroo Sandal for Kids 3", "pass", [])


def test_rule_check_drops_an_invented_promotional_word():
    assert rule_check(
        "Walkaroo Sandal",
        "Walkaroo Sandal Sale",
        ["Walkaroo"],
        allowed=["kids sandals"],
    ) == ("Walkaroo Sandal", "adjusted", [])


def test_rule_check_allows_the_singular_of_an_es_plural():
    assert rule_check(
        "Titan Analog Dial",
        "Titan Analog Dial Watch",
        ["Titan"],
        allowed=["men watches"],
    ) == ("Titan Analog Dial Watch", "pass", [])


def test_rule_check_allows_attribute_words():
    assert rule_check(
        "Walkaroo Sandal",
        "Walkaroo Leather Sandal",
        ["Walkaroo"],
        allowed=["kids sandals", "Leather"],
    ) == ("Walkaroo Leather Sandal", "pass", [])


def test_rule_check_falls_back_to_the_original_when_every_word_is_invented():
    assert rule_check(
        "Boys Sandal", "Comfy Footwear", [], allowed=["kids sandals"]
    ) == ("Boys Sandal", "adjusted", [])


def test_rule_check_falls_back_when_only_a_trailing_connector_is_left():
    assert rule_check(
        "Boys Sandal", "Comfy Footwear for", [], allowed=["kids sandals"]
    ) == ("Boys Sandal", "adjusted", [])


def test_rule_check_falls_back_when_only_an_inner_connector_is_left():
    assert rule_check(
        "Boys Sandal", "Comfy and Footwear", [], allowed=["kids sandals"]
    ) == ("Boys Sandal", "adjusted", [])


def test_missing_skips_a_noise_word_even_in_the_keyword():
    assert missing(
        "Kids Shoe",
        ["Taye White Sneaker", "Artie White Sneaker"],
        ["X"],
        keyword="white sneakers",
    ) == ["sneaker"]


def test_rule_check_allows_glass_for_glasses():
    assert rule_check(
        "Ray Reading Frame",
        "Ray Reading Frame Glass",
        ["Ray"],
        allowed=["reading glasses"],
    ) == ("Ray Reading Frame Glass", "pass", [])


# Ranking titles stored in dev's keyword_search (slice 22 spec).
WS = [
    "Women's Double Strap Footbed Sandals",
    "Women's Footbed Slide Sandals, Wide Width Available",
    "Men's and Women's Unisex Baya II Slide Sandals",
    "Women's Faux Suede Thong Footbed Sandals",
    "Women's Asymmetric Strap Footbed Sandals, Wide Width Available",
]
KS = [
    "MIA - Lolli (Toddler/Little Kid)",
    "Josmo - Cars Lighted Sandal (Toddler/Little Kid)",
    "Naturino - Flower Mountain Nazca 2 Junior (Little Kid)",
    "Teva - Toachi Hydratrek (Toddler/Little Kid/Big Kid)",
    "Josmo - Spiderman Sandals (Toddler/Little Kid)",
]
KSH = [
    "Nike A'Two A'ja Wilson Big Kids' Basketball Shoes",
    "Nike Free Ride Little Kids' Running Shoes",
    "Nike Woodside 2 High Big Kids' Boots",
    "Nike Manoa 17 Big Kids' Boots",
    "Nike Air Max 270 Big Kids' Shoes",
]
B = ["BSOAgentTestBrand"]
WSB = [
    "women sandals",
    "Flat sandal with a cushioned footbed",
    "Sandals",
    "7",
    "tan",
]


def test_missing_needs_backing_and_more_than_half_the_titles():
    assert missing(
        "BSOAgentTestBrand Women Sandal Tan",
        WS,
        B,
        keyword="women sandals",
        backing=WSB,
    ) == ["footbed"]


def test_missing_drops_an_unbacked_size_marker():
    assert missing(
        "BSOAgentTestBrand Boys Sandal Blue",
        KS,
        B,
        keyword="kids sandals",
        backing=[
            "kids sandals",
            "Lightweight EVA sandal with a hook-and-loop strap",
            "Sandals",
            "3",
            "blue",
        ],
    ) == ["kid"]


def test_missing_drops_a_different_product_type():
    assert (
        missing(
            "BSOAgentTestBrand Kids Sports Shoe Black",
            KSH,
            B,
            keyword="kids shoes",
            backing=[
                "kids shoes",
                "Breathable mesh running shoe for school and play",
                "Shoes",
                "4",
                "black",
            ],
        )
        == []
    )


def test_missing_with_empty_backing_suggests_nothing():
    assert (
        missing(
            "BSOAgentTestBrand Women Sandal Tan",
            WS,
            B,
            keyword="women sandals",
            backing=[],
        )
        == []
    )


def test_missing_needs_more_than_half_the_titles_without_backing():
    # Before slice 22: footbed, available, slide, strap, wide, width.
    assert missing(
        "BSOAgentTestBrand Women Sandal Tan", WS, B, keyword="women sandals"
    ) == ["footbed"]


def test_missing_needs_more_than_half_the_titles_even_when_backed():
    # strap, wide and width are backed but in only 2 of the 5 titles.
    assert missing(
        "BSOAgentTestBrand Women Sandal Tan",
        WS,
        B,
        keyword="women sandals",
        backing=[*WSB, "adjustable strap, wide width"],
    ) == ["footbed"]


def test_missing_backing_folds_es_plurals():
    assert missing(
        "Titan Analog Dial",
        ["Titan Men Watch", "Fossil Men Watch"],
        ["Titan"],
        keyword="men watches",
        backing=["men watches"],
    ) == ["men", "watch"]


T = "BSOAgentTestBrand Men Flip Flop Navy"
W = "Walkaroo Boys Sandal 0"
CASUAL = "BSOAgentTestBrand Men Casual Sandal Brown"


def test_type_word_is_the_category_word_fit_rank_reads():
    keywords = (
        "men slippers",
        "slippers for men",
        "men slip on shoes",
        "for",
        "",
    )
    assert [_type_word(k) for k in keywords] == [
        "slipper",
        "slipper",
        "shoe",
        "for",
        None,
    ]


def test_title_first_builds_the_audience_plus_the_title_type():
    assert title_first(["men slippers", "cushioned flip flops"], T) == [
        "men flip flops",
        "men slippers",
        "cushioned flip flops",
    ]
    assert title_first(["slippers for men", "daily wear flip flops"], T) == [
        "men flip flops",
        "slippers for men",
        "daily wear flip flops",
    ]


def test_title_first_uses_an_offered_keyword_in_its_own_spelling():
    assert title_first(
        ["men slippers", "cushioned flip flops", "mens flip flops"], T
    ) == ["mens flip flops", "men slippers", "cushioned flip flops"]


def test_title_first_leaves_the_keywords_when_it_cannot_build():
    # The first keyword fits the title.
    assert title_first(
        ["kids slippers", "kids flip flops"],
        "BSOAgentTestBrand Kids Slipper Grey",
    ) == ["kids slippers", "kids flip flops"]
    # No keyword fits the title.
    assert title_first(
        ["men slippers", "cushioned slippers"],
        "BSOAgentTestBrand Men Thong Navy",
    ) == ["men slippers", "cushioned slippers"]
    # No audience word.
    assert title_first(["slippers", "flip flops"], T) == [
        "slippers",
        "flip flops",
    ]
    assert title_first([], T) == []


def test_title_first_caps_at_max_keywords():
    assert title_first(
        ["men slippers", "a", "b", "c", "cushioned flip flops"], T
    ) == ["men flip flops", "men slippers", "a", "b", "c"]


def test_title_first_keeps_audience_words_out_of_the_type():
    assert title_first(["kids slippers", "boys sandals"], W) == [
        "kids sandals",
        "kids slippers",
        "boys sandals",
    ]
    assert title_first(["kids slippers", "sandals for boys"], W) == [
        "kids sandals",
        "kids slippers",
        "sandals for boys",
    ]


def test_title_first_keeps_only_words_every_fitting_keyword_shares():
    assert title_first(
        ["men floaters", "casual sandals", "floater sandals"], CASUAL
    ) == ["men sandals", "men floaters", "casual sandals", "floater sandals"]
    # ponytail ceiling: with one fitting keyword its style word stays.
    assert title_first(["men floaters", "casual sandals"], CASUAL) == [
        "men casual sandals",
        "men floaters",
        "casual sandals",
    ]


def test_title_first_ignores_a_keyword_that_fits_only_by_an_audience_word():
    assert title_first(["kids slippers", "slippers boys"], W) == [
        "kids slippers",
        "slippers boys",
    ]
    assert title_first(
        ["men slippers", "cushioned flip flops", "casual men"], T
    ) == [
        "men flip flops",
        "men slippers",
        "cushioned flip flops",
        "casual men",
    ]


def test_title_first_builds_nothing_for_two_title_types():
    assert title_first(
        ["men slippers", "flip flops", "men thongs"], "X Men Flip Flop Thong"
    ) == ["men slippers", "flip flops", "men thongs"]


def test_title_first_never_builds_in_a_colour_word():
    assert title_first(["men slippers", "navy flip flops"], T) == [
        "men flip flops",
        "men slippers",
        "navy flip flops",
    ]


def test_drop_noise_terms_removes_colour_and_size_keywords():
    assert drop_noise_terms(
        ["men slippers", "navy flip flops", "men flip flop navy"]
    ) == ["men slippers"]
    assert drop_noise_terms(["navy flip flops", "blue flip flops"]) == []
    assert drop_noise_terms(
        ["free size slippers", "little kids sandals", "kids sandals"]
    ) == ["kids sandals"]


# Probe 4's samples for LC-05 (slice 23 spec).
S4 = [
    [
        "men slippers",
        "men flip flop navy",
        "navy flip flops",
        "cushioned flip flops",
        "daily use flip flop",
    ],
    ["men slippers", "men flip flops", "navy flip flops", "cushioned slippers"],
    [
        "men slippers",
        "men flip flops",
        "navy flip flops",
        "cushioned flip flops",
    ],
]


def test_choose_keywords_searches_the_audience_plus_the_title_type():
    assert choose_keywords(
        S4, B, T, "Slippers", "Cushioned flip flop for daily use"
    ) == [
        "men flip flops",
        "cushioned flip flops",
        "daily use flip flop",
        "men slippers",
        "cushioned slippers",
    ]


def test_choose_keywords_one_all_colour_sample_brings_no_colour_back():
    samples = [
        ["navy flip flops"],
        ["navy flip flops", "men slippers"],
        ["men slippers", "men flip flops"],
    ]
    assert choose_keywords(samples, B, T, "Slippers", None) == [
        "men flip flops",
        "men slippers",
    ]


def test_choose_keywords_falls_back_when_the_product_has_no_other_keyword():
    # Every keyword has a colour.
    assert choose_keywords(
        [["navy flip flops", "blue flip flops"]], B, T, "Slippers", None
    ) == ["navy flip flops", "blue flip flops"]
    # Only a brand phrase is left after the guard.
    assert choose_keywords(
        [["walkaroo sandals", "navy sandals"]], ["Walkaroo"], W, None, None
    ) == ["navy sandals"]
    assert choose_keywords([], B, T, None, None) == []


def test_choose_keywords_an_audience_word_keyword_does_not_stop_the_build():
    assert choose_keywords(
        [["kids slippers", "boys sandals", "slippers boys"]] * 3,
        ["Walkaroo"],
        W,
        None,
        None,
    ) == ["kids sandals", "boys sandals", "slippers boys"]


def test_title_first_never_takes_a_colour_from_the_first_keyword():
    assert title_first(["men navy slippers", "navy flip flops"], T) == [
        "men flip flops",
        "men navy slippers",
        "navy flip flops",
    ]


def test_title_first_prefers_a_plural_spelling_of_the_type():
    assert title_first(
        ["men slippers", "men flip flop navy", "navy flip flops"], T
    ) == [
        "men flip flops",
        "men slippers",
        "men flip flop navy",
        "navy flip flops",
    ]
    # ponytail ceiling: with no plural title fit the type stays singular.
    assert title_first(["men slippers", "men flip flop navy"], T)[0] == (
        "men flip flop"
    )


def test_choose_keywords_falls_back_when_the_guard_leaves_the_wrong_type():
    # Every title-fitting keyword has a colour: the guarded vote would
    # search the category's type ("men slippers").
    assert choose_keywords(
        [["men slippers", "navy flip flops", "cushioned slippers"]] * 3,
        B,
        T,
        "Slippers",
        None,
    ) == [
        "men flip flops",
        "navy flip flops",
        "men slippers",
        "cushioned slippers",
    ]
    # A category fit alone keeps the guarded result.
    assert choose_keywords(
        [["men slippers", "navy slippers"]],
        B,
        "X Men Thong Navy",
        "Slippers",
        None,
    ) == ["men slippers"]
    # No colour in a keyword built on the unfiltered path.
    assert choose_keywords(
        [["men navy slippers", "navy flip flops", "cushioned slippers"]],
        B,
        T,
        None,
        None,
    ) == ["men flip flops", "navy flip flops"]


def test_keyword_key_folds_es_plurals():
    assert keyword_key("men watches") == keyword_key("men watch") == "men watch"
    assert keyword_key("kids shoes") == "kid shoe"


def test_rule_check_removes_an_es_plural_repeat():
    assert rule_check(
        "Zara Summer Dress", "Zara Summer Dress Dresses", ["Zara"]
    ) == ("Zara Summer Dress", "pass", [])


def test_missing_folds_an_es_plural_in_the_title():
    assert missing(
        "Titan Analog Dial Watches",
        ["Titan Men Watch", "Fossil Men Watch"],
        ["Titan"],
        keyword="men watches",
        backing=["men watches"],
    ) == ["men"]


def test_lenses_still_back_lens_for_allowed_text():
    # The one-sided set in _allowed_stems stays (spec R1).
    assert rule_check(
        "Acme Daily", "Acme Daily Lens", ["Acme"], allowed=["contact lenses"]
    ) == ("Acme Daily Lens", "pass", [])
