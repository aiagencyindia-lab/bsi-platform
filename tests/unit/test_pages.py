"""URL optimizer (PRD F11): the page parser, the score, the suggestions."""

import hashlib
import math
import re

import pytest
from bsi_core import pages
from bsi_core.pages import (
    COS_COVERED,
    COS_FLOOR,
    COS_SPAN,
    SECTION_CAP,
    SECTION_CHARS,
    WEIGHTS,
    WEIGHTS_VERSION,
    Target,
    cosine,
    normalize_url,
    parse,
    score,
)

from tests.unit.test_recommend_copy import FORBIDDEN

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


def bow(text):
    """Deterministic 768-dim bag-of-words vector; cosine is meaningful."""
    v = [0.0] * 768
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        v[int(hashlib.sha1(w.encode()).hexdigest(), 16) % 768] += 1.0
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else [0.0] * 767 + [1.0]


def vectors(page, queries):
    return [bow(q) for _, q in queries], [
        bow(s.embed_text()) for s in page.sections
    ]


def target(**kw):
    base = dict(
        intent="recommendation",
        topic="school shoes",
        queries=[
            ("p1", "best school shoes for kids"),
            ("p2", "durable school shoes"),
        ],
        rivals=["Bata", "Campus"],
        brand="Acme",
        aliases=[],
        brand_hosts=["acme.com"],
        rival_hosts=["bata.in"],
        cited=[
            {
                "url": "https://forbes.com/x",
                "domain": "forbes.com",
                "answers": 3,
                "observation_ids": ["o1", "o2", "o3"],
            },
            {
                "url": "https://bata.in/school",
                "domain": "bata.in",
                "answers": 2,
                "observation_ids": ["o1", "o4"],
            },
        ],
        observation_ids=["o1", "o2", "o3", "o4"],
    )
    return Target(**{**base, **kw})


def by_code(result):
    return {c["code"]: c for c in result["components"]}


def test_weights_sum_to_100_and_are_in_weight_order():
    assert sum(WEIGHTS.values()) == 100
    assert list(WEIGHTS.values()) == sorted(WEIGHTS.values(), reverse=True)


def test_cosine():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_score_is_the_weighted_sum_and_components_are_in_weight_order():
    p = parse(ARTICLE)
    t = target()
    r = score(p, t, *vectors(p, t.queries))
    assert r["weights_version"] == WEIGHTS_VERSION
    assert [c["code"] for c in r["components"]] == list(WEIGHTS)
    for c in r["components"]:
        assert c["weight"] == WEIGHTS[c["code"]]
        assert c["points"] == round(c["weight"] * c["value"], 2)
        assert 0.0 <= c["value"] <= 1.0
    assert r["score"] == round(sum(c["points"] for c in r["components"]))


def test_topic_coverage_is_mean_best_cosine_mapped_and_names_uncovered():
    p = parse(ARTICLE)
    t = target()
    qv, sv = vectors(p, t.queries)
    r = score(p, t, qv, sv)
    best = [max(cosine(q, s) for s in sv) for q in qv]
    expect = sum(min(1.0, max(0.0, (b - COS_FLOOR) / COS_SPAN)) for b in best)
    c = by_code(r)["topic_coverage"]
    assert c["value"] == pytest.approx(round(expect / len(best), 4))
    uncovered = [t.queries[i] for i, b in enumerate(best) if b < COS_COVERED]
    adds = [
        s
        for s in r["suggestions"]["add"]
        if s["text"].startswith("Add a section that answers")
    ]
    assert [s["prompt_ids"] for s in adds] == [[pid] for pid, _ in uncovered]
    for s in adds:
        assert s["observation_ids"] == t.observation_ids


def test_topic_coverage_without_prompt_vectors_is_zero():
    p = parse(ARTICLE)
    t = target()
    r = score(p, t, [None, None], vectors(p, t.queries)[1])
    c = by_code(r)["topic_coverage"]
    assert c["value"] == 0.0 and "no prompt embeddings" in c["observed"]


def test_intent_fit_by_page_type():
    p = parse(ARTICLE)  # a table, a list, 3 H2, > 30 words, no Product schema
    comparison = target(intent="comparison")
    r = score(p, comparison, *vectors(p, comparison.queries))
    # comparison page: table (yes) + two rivals named (no) -> 0.5
    assert by_code(r)["intent_fit"]["value"] == 0.5
    product = target(intent="transactional")
    r = score(p, product, *vectors(p, product.queries))
    assert by_code(r)["intent_fit"]["value"] == 0.0
    assert any("Product" in s["text"] for s in r["suggestions"]["add"])


def test_entity_coverage():
    p = parse(ARTICLE)
    t = target()  # Acme in title and body and description -> 1.0
    r = score(p, t, *vectors(p, t.queries))
    assert by_code(r)["entity_coverage"]["value"] == 1.0
    t2 = target(brand="Zed")
    c = by_code(score(p, t2, *vectors(p, t2.queries)))["entity_coverage"]
    assert c["value"] == 0.0
    t3 = target(intent="comparison", rivals=["Bata", "Campus"], brand="Zed")
    body = ARTICLE.replace("<p>Acme has", "<p>Bata and Acme has")
    p3 = parse(body)
    c = by_code(score(p3, t3, *vectors(p3, t3.queries)))["entity_coverage"]
    assert c["value"] == pytest.approx(0.25 * 0.5)  # one of two rivals


def test_evidence_links_to_cited_domains_and_other_third_parties():
    p = parse(ARTICLE)  # forbes.com (cited) linked; acme.com is owned
    t = target()
    r = score(p, t, *vectors(p, t.queries))
    c = by_code(r)["evidence"]
    assert c["value"] == pytest.approx(0.6 * (1 / 3) + 0.4 * 0)
    ev = r["suggestions"]["evidence_to_add"]
    # forbes is already linked; the Bata page is a cited competitor page.
    assert [s["urls"] for s in ev] == [["https://bata.in/school"]]
    assert ev[0]["observation_ids"] == ["o1", "o4"]


@pytest.mark.parametrize(
    ("href", "cited_domain"),
    [
        ("https://bata.in/x", "bata.in"),  # rival host, still linked
        ("https://forbes.com/y", "blog.forbes.com"),  # cited under linked
        ("https://www.forbes.com/y", "forbes.com"),  # linked under cited
    ],
)
def test_evidence_to_add_skips_a_domain_already_linked(href, cited_domain):
    p = parse(f'<h1>t</h1><a href="{href}">x</a>')
    t = target(
        cited=[
            {
                "url": f"https://{cited_domain}/z",
                "domain": cited_domain,
                "answers": 1,
                "observation_ids": ["o1"],
            }
        ]
    )
    r = score(p, t, *vectors(p, t.queries))
    assert r["suggestions"]["evidence_to_add"] == []


def test_author_structure_faqs_tables_direct_answers():
    p = parse(ARTICLE)
    t = target()
    c = by_code(score(p, t, *vectors(p, t.queries)))
    assert c["author_attribution"]["value"] == 1.0
    # one H1 (0.3) + 3 H2 (0.3) + no level skipped (0.2) + < 300 words (0)
    assert c["structure"]["value"] == pytest.approx(0.8)
    # no FAQPage schema; one heading ends in "?" and one contains "FAQ"
    assert c["faqs"]["value"] == 0.6
    assert c["tables"]["value"] == 1.0
    # H2 sections: "Which school shoes..." (direct), "Our picks" (direct),
    # "FAQ" (empty text -> not direct)
    assert c["direct_answers"]["value"] == round(2 / 3, 4)


def test_direct_answer_boundaries():
    long = "word " * 41
    html = (
        f"<h1>t</h1><h2>a</h2><p>{long}.</p><h2>b</h2>"
        "<p>In this article we cover x.</p><h2>c</h2><p>Yes.</p>"
    )
    p = parse(html)
    t = target()
    r = score(p, t, *vectors(p, t.queries))
    assert by_code(r)["direct_answers"]["value"] == round(1 / 3, 4)
    texts = [s["text"] for s in r["suggestions"]["rewrite"]]
    assert any("“a”" in x for x in texts) and any("“b”" in x for x in texts)
    assert any("“b”" in s["text"] for s in r["suggestions"]["remove"])


def test_faqpage_schema_and_extra_h1_and_no_h2():
    html = (
        '<script type="application/ld+json">{"@type":"FAQPage"}</script>'
        "<h1>a</h1><h1>b</h1><p>x</p>"
    )
    p = parse(html)
    t = target()
    r = score(p, t, *vectors(p, t.queries))
    c = by_code(r)
    assert c["faqs"]["value"] == 1.0
    assert c["structure"]["value"] == pytest.approx(0.2)  # levels fine only
    assert c["direct_answers"]["value"] == 0.0
    assert any("extra H1" in s["text"] for s in r["suggestions"]["remove"])


def test_every_suggestion_cites_an_id_or_a_url():
    p = parse("<h1>Nothing here</h1><p>x</p>")
    t = target()
    r = score(p, t, *vectors(p, t.queries))
    items = [s for lst in r["suggestions"].values() for s in lst]
    assert items
    for s in items:
        assert s["urls"] or s["prompt_ids"] or s["observation_ids"], s


def test_suggestion_copy_has_no_banned_words():
    t = target(intent="comparison", brand="Zed")
    texts = []
    for html in ("<h1>Nothing here</h1><p>x</p>", ARTICLE):
        p = parse(html)
        r = score(p, t, *vectors(p, t.queries))
        texts += [s["text"] for lst in r["suggestions"].values() for s in lst]
    assert len(texts) >= 10
    for text in texts:
        for word in FORBIDDEN:
            assert word not in text.lower(), (word, text)


def test_evidence_counts_cited_domains_not_hosts():
    p = parse(
        '<h1>t</h1><a href="https://forbes.com/a">a</a>'
        '<a href="https://www.forbes.com/b">b</a>'
        '<a href="https://m.forbes.com/c">c</a>'
        '<a href="https://nyt.com/a">d</a>'
        '<a href="https://www.nyt.com/b">e</a>'
    )
    t = target(cited=[target().cited[0]])  # forbes.com only
    c = by_code(score(p, t, *vectors(p, t.queries)))["evidence"]
    assert c["value"] == round(0.6 * (1 / 3) + 0.4 * (1 / 5), 4)
    assert c["observed"].startswith("1 cited domains linked, 1 other")
    assert c["evidence"] == ["forbes.com"]


def test_suggestions_cite_prompts_when_the_cluster_has_no_absent_answers():
    p = parse("<h1>Nothing here</h1><h1>again</h1><h3>skip</h3><p>x</p>")
    t = target(observation_ids=[], cited=[])
    r = score(p, t, *vectors(p, t.queries))
    items = [s for lst in r["suggestions"].values() for s in lst]
    assert len(items) >= 5
    for s in items:
        assert s["urls"] or s["prompt_ids"] or s["observation_ids"], s
    # every suggestion owns its lists
    ids = [id(s[k]) for s in items for k in ("prompt_ids", "observation_ids")]
    assert len(ids) == len(set(ids))
