from bsi_core import models as m
from bsi_core.recommend import top_by_type


def recs(*rows):
    """(type, priority) pairs, already in priority order as the API lists
    them. Transient rows: no session needed."""
    return [
        m.Recommendation(type=t, subject_key=f"{t}-{i}", priority=p)
        for i, (t, p) in enumerate(rows)
    ]


def keys(chosen):
    return [r.subject_key for r in chosen]


def test_the_best_of_each_type_beats_a_types_runners_up():
    # Citations hold the three highest priorities, but the shortlist takes
    # only the best of them, then the best content and sampling rows.
    ranked = recs(
        ("pursue_citation_source", 0.9),
        ("pursue_citation_source", 0.8),
        ("pursue_citation_source", 0.7),
        ("create_content", 0.1),
        ("sample_more", 0.05),
    )
    assert keys(top_by_type(ranked)) == [
        "pursue_citation_source-0",
        "create_content-3",
        "sample_more-4",
    ]


def test_types_keep_their_priority_order():
    ranked = recs(
        ("sample_more", 0.5),
        ("pursue_citation_source", 0.4),
        ("create_content", 0.3),
        ("add_competitor", 0.2),
    )
    assert keys(top_by_type(ranked)) == [
        "sample_more-0",
        "pursue_citation_source-1",
        "create_content-2",
    ]


def test_fewer_types_than_slots_fills_with_the_next_best():
    ranked = recs(
        ("pursue_citation_source", 0.9),
        ("pursue_citation_source", 0.8),
        ("create_content", 0.1),
    )
    assert keys(top_by_type(ranked)) == [
        "pursue_citation_source-0",
        "create_content-2",
        "pursue_citation_source-1",
    ]


def test_limits_and_empty():
    ranked = recs(("create_content", 0.2), ("create_content", 0.1))
    assert keys(top_by_type(ranked, k=1)) == ["create_content-0"]
    assert top_by_type([]) == []
