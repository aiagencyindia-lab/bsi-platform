"""Newcombe (1998) method 10, checked against his Table II."""

import pytest
from bsi_core.metrics import delta, rate

# before (k, n), after (k, n), expected [low, high] from Newcombe Table II
TABLE_II = [
    ((48, 80), (56, 70), (0.0524, 0.3339)),
    ((3, 10), (9, 10), (0.1705, 0.8090)),
    ((0, 29), (5, 56), (-0.0381, 0.1926)),
    ((0, 10), (10, 10), (0.6075, 1.0)),
]


@pytest.mark.parametrize(("before", "after", "want"), TABLE_II)
def test_matches_newcombe_table_ii(before, after, want):
    got = delta(rate(*before), rate(*after))
    assert got["value"] == pytest.approx(
        after[0] / after[1] - before[0] / before[1]
    )
    assert got["ci_low"] == pytest.approx(want[0], abs=1e-3)
    assert got["ci_high"] == pytest.approx(want[1], abs=1e-3)


def test_labels():
    assert delta(rate(48, 80), rate(56, 70))["label"] == "increase"
    assert delta(rate(56, 70), rate(48, 80))["label"] == "decrease"
    assert delta(rate(0, 29), rate(5, 56))["label"] == "no significant change"


@pytest.mark.parametrize(
    ("before", "after"),
    [((0, 0), (5, 10)), ((5, 10), (0, 0))],
)
def test_empty_window_is_insufficient_data(before, after):
    assert delta(rate(*before), rate(*after)) == {
        "value": None,
        "ci_low": None,
        "ci_high": None,
        "label": "insufficient data",
    }
