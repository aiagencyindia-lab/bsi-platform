import pytest
from bsi_core import entity
from bsi_core.crawl import SEVERITY
from bsi_core.recommend import (
    citation_copy,
    cluster_copy,
    competitor_copy,
    content_copy,
    crawl_copy,
    entity_copy,
    names,
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
