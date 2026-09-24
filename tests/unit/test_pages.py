"""URL optimizer (PRD F11): the page parser, the score, the suggestions."""

import pytest
from bsi_core import pages
from bsi_core.pages import SECTION_CAP, SECTION_CHARS, normalize_url, parse

ARTICLE = """<html><head><title>Best school shoes for kids | Acme</title>
<meta name="description" content="Acme picks the best school shoes">
<meta name="author" content="Jane Doe">
<script type="application/ld+json">{"@type":"Article","author":
{"@type":"Person","name":"Jane"}}</script>
<script>var x = 1;</script></head><body>
<nav><a href="/home">Home</a> nav words here</nav>
<h1>Best school shoes for kids</h1>
<p>Acme has sold school shoes for years.</p>
<h2>Which school shoes last longest?</h2>
<p>Leather uppers last longest. They cost more but outlast canvas.</p>
<table><tr><th>Shoe</th><th>Price</th></tr><tr><td>A</td><td>1</td></tr>
</table>
<h2>Our picks</h2>
<ol><li>One</li><li>Two</li><li>Three</li></ol>
<h3>Budget</h3><p>Under 1000.</p>
<div class="byline">By Jane</div>
<a href="https://forbes.com/x" rel="nofollow">Forbes</a>
<a href="https://acme.com/about">About</a>
<h2>FAQ</h2>
<footer>footer words</footer>
</body></html>"""


def test_parse_collects_head_fields_and_skips_boilerplate():
    p = parse(ARTICLE)
    assert p.title == "Best school shoes for kids | Acme"
    assert p.description == "Acme picks the best school shoes"
    assert p.author == "Jane Doe"
    assert len(p.ld) == 1 and '"Article"' in p.ld[0]
    assert p.h1_count == 1
    assert p.headings == [
        (1, "Best school shoes for kids"),
        (2, "Which school shoes last longest?"),
        (2, "Our picks"),
        (3, "Budget"),
        (2, "FAQ"),
    ]
    assert p.tables == 1 and p.lists == 1 and p.ordered_lists == 1
    assert p.links == [
        ("https://forbes.com/x", "nofollow"),
        ("https://acme.com/about", ""),
    ]
    assert p.byline is True
    # nav, footer and script text never reach the word count.
    assert "nav" not in " ".join(s.text for s in p.sections)
    assert p.words == len(
        "Acme has sold school shoes for years. Leather uppers last longest. "
        "They cost more but outlast canvas. Shoe Price A 1 One Two Three "
        "Under 1000. By Jane Forbes About".split()
    )


def test_sections_follow_headings_and_keep_their_text():
    p = parse(ARTICLE)
    assert [s.heading for s in p.sections] == [h for _, h in p.headings]
    first = p.sections[1]
    assert first.level == 2
    assert first.text.startswith("Leather uppers last longest.")
    assert "Shoe Price" in first.text  # table text belongs to its section
    assert first.embed_text() == f"{first.heading}\n{first.text}"


def test_tables_and_lists_need_two_rows_and_three_items():
    p = parse(
        "<h1>x</h1><table><tr><td>1</td></tr></table><ul><li>a</li>"
        "<li>b</li></ul><ol><li>a</li><li>b</li><li>c</li></ol>"
    )
    assert (p.tables, p.lists, p.ordered_lists) == (0, 1, 1)


def test_sections_are_capped():
    html = "<h1>t</h1>" + "".join(
        f"<h2>h{i}</h2><p>{'w ' * 3000}</p>" for i in range(SECTION_CAP + 5)
    )
    p = parse(html)
    assert len(p.sections) == SECTION_CAP
    assert all(len(s.text) <= SECTION_CHARS for s in p.sections)
    assert len(p.headings) == SECTION_CAP + 6  # every heading still counted


def test_author_from_rel_or_class_or_id():
    assert parse('<a rel="author" href="/j">J</a>').byline is True
    assert parse('<span id="post-author">J</span>').byline is True
    assert parse("<p>By nobody</p>").byline is False


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("HTTPS://Acme.com/Shoes?x=1#top", "https://acme.com/Shoes?x=1"),
        ("http://acme.com", "http://acme.com/"),
    ],
)
def test_normalize_url(raw, clean):
    assert normalize_url(raw) == clean


@pytest.mark.parametrize(
    "bad",
    ["ftp://acme.com/x", "acme.com/x", "http://user:pw@acme.com/", "http:///x"],
)
def test_normalize_url_refuses(bad):
    with pytest.raises(ValueError):
        normalize_url(bad)


def test_module_states_the_score_is_a_diagnostic():
    assert "not a promised outcome" in pages.NOTE


def test_header_inside_article_is_content():
    p = parse(
        '<article><header><h1>Title</h1><span class="byline">By J</span>'
        "</header><p>body text</p></article>"
    )
    assert p.headings == [(1, "Title")]
    assert p.byline is True
    assert "body text" in p.sections[0].text


def test_top_level_header_is_still_skipped():
    p = parse("<header><h1>Site</h1></header><main><h1>Page</h1></main>")
    assert p.headings == [(1, "Page")]


def test_footer_kept_inside_article_dropped_at_top_level():
    p = parse(
        "<article><h1>t</h1><footer>kept words</footer></article>"
        "<footer>dropped words</footer>"
    )
    assert "kept words" in p.sections[0].text
    assert "dropped" not in p.sections[0].text
    assert p.words == 2
