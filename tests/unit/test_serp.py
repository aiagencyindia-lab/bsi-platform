import pytest
from bsi_core.serp import classify, ownership

OWN = ["walkaroo.in"]
RIVALS = ["bata.com", "www.campusshoes.com"]
CASES = [
    ("knowledge_graph", "", "knowledge_panel"),
    ("ai_overview", "", "ai_overview"),
    ("top_stories", "", "news"),
    ("video", "", "video"),
    ("images", "", "image"),
    ("organic", "https://www.youtube.com/watch?v=1", "video"),
    ("organic", "https://walkaroo.in/", "official"),
    ("organic", "https://shop.walkaroo.in/kids", "official"),
    ("organic", "https://www.bata.com/in/", "competitor"),
    ("organic", "https://campusshoes.com/x", "competitor"),
    ("organic", "https://x.com/walkaroo", "social"),
    ("organic", "https://in.linkedin.com/company/w", "social"),
    ("organic", "https://www.mouthshut.com/w-reviews", "review"),
    ("organic", "https://www.glassdoor.co.in/Reviews/w", "review"),
    ("organic", "https://www.amazon.in/walkaroo", "other"),
    ("organic", "https://notwalkaroo.in/", "other"),
    ("featured_snippet", "walkaroo.in", "official"),
    ("featured_snippet", "www.amazon.in", "other"),
    ("organic", "walkaroo.in", "official"),
    ("organic", "", "other"),
    ("people_also_ask", "", None),
    ("paid", "https://walkaroo.in/", None),
]


@pytest.mark.parametrize(("item_type", "host", "expected"), CASES)
def test_classify(item_type, host, expected):
    assert classify(item_type, host, OWN, RIVALS) == expected


def test_the_rule_order_is_video_then_own_then_rival():
    # A rival's YouTube channel is a video result.
    assert classify("organic", "https://youtube.com/@bata", OWN, RIVALS) == (
        "video"
    )
    # A host listed as both the brand's own and a rival's is the brand's.
    assert classify("organic", "walkaroo.in", OWN, ["walkaroo.in"]) == (
        "official"
    )
    # A social host in the rival list takes every result on that host.
    assert classify("organic", "x.com", OWN, ["x.com"]) == "competitor"


def test_ownership_counts_official_organic_results():
    rows = [
        {"item_type": "organic", "result_type": "official"},
        {"item_type": "organic", "result_type": "other"},
        {"item_type": "knowledge_graph", "result_type": "knowledge_panel"},
        {"item_type": "featured_snippet", "result_type": "official"},
    ]
    assert ownership(rows) == (1, 2)
    assert ownership([]) == (0, 0)
