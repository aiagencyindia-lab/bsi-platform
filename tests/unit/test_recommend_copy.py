import pytest
from bsi_core import entity
from bsi_core.alerts import drop_copy, shift_copy, source_copy
from bsi_core.crawl import SEVERITY
from bsi_core.recommend import (
    citation_copy,
    cluster_copy,
    competitor_copy,
    content_copy,
    crawl_copy,
    entity_copy,
    names,
    page_copy,
    rival_content_copy,
    sample_copy,
)

# A template may describe evidence and name the metric to watch; it may
# never promise what will happen.
FORBIDDEN = (
    "guarantee",
    "will rank",
    "will appear",
    "will be recommended",
    "ensure",
    "boost",
    "#1",
    "top spot",
    "dominat",
    "certain",
)

CASES = [
    citation_copy("Nike", "forbes.com", 4, ["Adidas", "Puma", "Bata", "Crocs"]),
    citation_copy("Nike", "forbes.com", 3, []),
    content_copy(
        "Nike", "best shoes", 4, 4, "competitor_dominance", ["Adidas"]
    ),
    content_copy("Nike", "best shoes", 3, 5, "competitor_dominance", []),
    content_copy("Nike", "best shoes", 3, 4, "not_retrieved", []),
    competitor_copy("Puma", 2),
    sample_copy("Nike", "best shoes", 3, 4, "Adidas"),
    sample_copy("Nike", "best shoes", 3, 7, "Adidas"),
]

CASES += [
    cluster_copy(
        "Nike",
        "comparison",
        "running shoes",
        "comparison page",
        ["nike vs adidas", "best running shoe brand"],
        6,
        8,
        ["Adidas", "Puma"],
    ),
    cluster_copy(
        "Nike",
        "informational",
        "sizing",
        "guide",
        ["shoe size chart"],
        2,
        3,
        [],
    ),
]

ALTERNATIVES = cluster_copy(
    "Nike",
    "alternative",
    "running shoes",
    "alternatives page",
    ["adidas alternatives"],
    3,
    4,
    ["Adidas"],
)
CASES.append(ALTERNATIVES)

# Every crawl family, so the scans below cover each template.
CRAWL_CODES = [f"{c}:GPTBot" if c.startswith("bot_") else c for c in SEVERITY]
CASES += [
    crawl_copy(
        "Nike",
        "nike.com",
        {
            "code": code,
            "observed": "HTTP 404",
            "expected": "x",
            "url": "https://nike.com/",
            "severity": SEVERITY[code.split(":", 1)[0]],
        },
    )
    for code in CRAWL_CODES
]

CASES += [
    entity_copy(
        "Nike",
        "nike.com",
        {
            "code": code,
            "observed": "Q42: Nikey",
            "expected": "x",
            "url": "https://nike.com/",
            "severity": sev,
        },
    )
    for code, sev in entity.SEVERITY.items()
]


def test_entity_copy_names_the_brand_domain_and_evidence():
    title, body = entity_copy(
        "Nike",
        "nike.com",
        {
            "code": "org_name_mismatch",
            "observed": "Nikey Inc",
            "expected": "x",
            "url": "https://nike.com/",
            "severity": "high",
        },
    )
    assert "nike.com" in title
    assert "Nikey Inc" in body and "https://nike.com/" in body
    assert entity.EXPECTED["org_name_mismatch"] in body
    assert "mention rate" in body


PAGE_SUGGESTIONS = {
    "add": [
        {
            "text": "Add a section that answers “best school shoes” directly.",
            "urls": [],
            "prompt_ids": ["p"],
            "observation_ids": [],
        }
    ],
    "remove": [],
    "rewrite": [
        {
            "text": "Name Nike in the title or H1.",
            "urls": [],
            "prompt_ids": [],
            "observation_ids": ["o"],
        }
    ],
    "evidence_to_add": [
        {
            "text": "Cite https://forbes.com/x: 3 answers in this cluster "
            "draw on it.",
            "urls": ["https://forbes.com/x"],
            "prompt_ids": [],
            "observation_ids": ["o"],
        }
    ],
}
CASES += [
    page_copy(
        "Nike",
        "https://nike.com/kids/school",
        "school shoes",
        4,
        62,
        PAGE_SUGGESTIONS,
    ),
    page_copy(
        "Nike",
        "https://nike.com/",
        "school shoes",
        1,
        0,
        {"add": [], "remove": [], "rewrite": [], "evidence_to_add": []},
    ),
]


# Quoted URL slugs are data, exempt from FORBIDDEN; fixtures avoid banned words.
RIVAL_ONE = rival_content_copy(
    "Nike",
    "running shoes",
    "comparison",
    "comparison page",
    [("Adidas", ["https://adidas.co.in/running-shoes/adizero-sl-2"])],
    8,
    0.25,
    ("Adidas", 0.625),
    False,
)
RIVAL_FOUR = rival_content_copy(
    "Nike",
    "running shoes",
    "comparison",
    "comparison page",
    [
        (
            "Adidas",
            [
                "https://adidas.co.in/running-shoes/a",
                "https://adidas.co.in/running-shoes/b",
                "https://adidas.co.in/running-shoes/c",
                "https://adidas.co.in/running-shoes/d",
            ],
        )
    ],
    8,
    0.25,
    ("Adidas", 0.625),
    False,
)
RIVAL_MANY = rival_content_copy(
    "Nike",
    "kids shoes",
    "commercial",
    "category page",
    [
        ("Adidas", ["https://adidas.co.in/kids-shoes"]),
        ("Puma", ["https://puma.com/kids/shoes"]),
        ("Bata", ["https://bata.com/kids-shoes/"]),
        ("Crocs", ["https://crocs.in/kids-shoes"]),
    ],
    10,
    0.3,
    ("Adidas", 0.7),
    False,
)
RIVAL_GAP = rival_content_copy(
    "Nike",
    "running shoes",
    "comparison",
    "comparison page",
    [("Adidas", ["https://adidas.co.in/running-shoes/"])],
    8,
    0.25,
    ("Adidas", 0.625),
    True,
)
CASES += [RIVAL_ONE, RIVAL_FOUR, RIVAL_MANY, RIVAL_GAP]


# Alert titles are single strings with no metric line.
ALERT_CASES = [
    drop_copy(0.18, 0.52, 0.34),
    shift_copy("Adidas", "up", 11),
    shift_copy("Adidas", "down", 10),
    source_copy("forbes.com", 6),
]


@pytest.mark.parametrize("copy", ALERT_CASES)
def test_alert_copy_never_promises_an_outcome(copy):
    text = copy.lower()
    for word in FORBIDDEN:
        assert word not in text, word


@pytest.mark.parametrize("copy", CASES)
def test_copy_never_promises_an_outcome(copy):
    text = " ".join(copy).lower()
    for word in FORBIDDEN:
        assert word not in text, word


@pytest.mark.parametrize("copy", CASES)
def test_copy_names_the_metric_to_watch(copy):
    assert "Metric to watch:" in copy[1]


def test_every_crawl_family_is_covered():
    assert len(CRAWL_CODES) == 11
    assert "bot_ua_blocked:GPTBot" in CRAWL_CODES


def test_rival_lists_read_naturally():
    assert names([]) == ""
    assert names(["A"]) == "A"
    assert names(["A", "B"]) == "A and B"
    assert names(["A", "B", "C", "D"]) == "A, B and C"


def test_sample_copy_counts_the_shortfall():
    assert sample_copy("N", "p", 3, 4, "R")[0].startswith(
        "Take 1 more sample of"
    )
    assert sample_copy("N", "p", 3, 7, "R")[0].startswith(
        "Take 4 more samples of"
    )


def test_crawl_copy_names_the_bot_and_the_file():
    title, body = crawl_copy(
        "Nike",
        "nike.com",
        {
            "code": "bot_ua_blocked:ClaudeBot",
            "observed": "HTTP 403",
            "expected": "x",
            "url": "https://nike.com/",
            "severity": "high",
        },
    )
    assert "ClaudeBot" in title and "nike.com" in title
    assert "HTTP 403" in body and "https://nike.com/" in body


def test_cluster_copy_uses_an_before_a_vowel():
    title, body = ALTERNATIVES
    assert title.startswith("Publish an alternatives page for ")
    assert "An alternatives page that answers" in body
    assert cluster_copy("N", "i", "t", "guide", ["q"], 1, 2, [])[0].startswith(
        "Publish a guide"
    )


def test_cluster_copy_names_rivals_in_this_cluster():
    assert "Rivals named in this cluster: Adidas." in ALTERNATIVES[1]


def test_page_copy_names_the_page_score_and_first_steps():
    title, body = page_copy(
        "Nike",
        "https://nike.com/kids/school",
        "school shoes",
        4,
        62,
        PAGE_SUGGESTIONS,
    )
    assert title == "Improve nike.com/kids/school for school shoes"
    assert "62/100" in body and "v1" in body
    assert "best school shoes" in body and "forbes.com" in body
    assert "4 prompts" in body and "Metric to watch:" in body


def test_page_copy_drops_a_bare_root_path():
    title, _ = page_copy("Nike", "https://nike.com/", "school shoes", 1, 0, {})
    assert title == "Improve nike.com for school shoes"


def test_rival_content_copy_names_pages_standing_and_response():
    title, body = RIVAL_ONE
    assert title == "Adidas published 1 new running shoes page"
    assert "Adidas published 1 new page: adizero-sl-2." in body
    assert "Nike is named in 25% of 8 answers; Adidas in 62%." in body
    assert "Publish a comparison page on running shoes" in body
    assert body.endswith(
        "Metric to watch: Nike's mention rate on the running shoes cluster."
    )
    title, body = RIVAL_FOUR
    assert title == "Adidas published 4 new running shoes pages"
    assert "4 new pages: a, b, c." in body  # three named, count kept
    title, body = RIVAL_MANY
    assert title == "4 new kids shoes pages from Adidas, Puma and Bata"
    assert "Crocs published 1 new page: kids-shoes." in body
    assert "Publish a category page on kids shoes" in body
    _, body = RIVAL_GAP
    assert "This cluster is a content gap for Nike." in body
    assert "named in" not in body
