import pytest
from bsi_core.crawl import SEVERITY
from bsi_core.recommend import (
    citation_copy,
    competitor_copy,
    content_copy,
    crawl_copy,
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
