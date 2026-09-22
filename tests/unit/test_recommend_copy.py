import pytest
from bsi_core.recommend import (
    citation_copy,
    competitor_copy,
    content_copy,
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


@pytest.mark.parametrize("copy", CASES)
def test_copy_never_promises_an_outcome(copy):
    text = " ".join(copy).lower()
    for word in FORBIDDEN:
        assert word not in text, word


@pytest.mark.parametrize("copy", CASES)
def test_copy_names_the_metric_to_watch(copy):
    assert "Metric to watch:" in copy[1]


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
