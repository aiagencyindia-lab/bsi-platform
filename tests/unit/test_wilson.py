import pytest
from bsi_core.metrics import rate, samples_to_separate, wilson


@pytest.mark.parametrize(
    ("k", "n", "low", "high"),
    [
        (1, 3, 0.0615, 0.7923),
        (30, 60, 0.3773, 0.6227),
        (0, 10, 0.0, 0.2775),
        (10, 10, 0.7225, 1.0),
    ],
)
def test_wilson_known_values(k, n, low, high):
    lo, hi = wilson(k, n)
    assert lo == pytest.approx(low, abs=1e-3)
    assert hi == pytest.approx(high, abs=1e-3)


@pytest.mark.parametrize("n", range(1, 201))
def test_interval_contains_the_estimate_exactly_at_the_edges(n):
    # Float rounding used to give ci_low=2.8e-17 at k=0 and
    # ci_high=0.9999999999999999 at k=n for some n.
    assert wilson(0, n)[0] == 0.0
    assert wilson(n, n)[1] == 1.0
    for k in range(n + 1):
        low, high = wilson(k, n)
        assert low <= k / n <= high


def test_wilson_no_samples():
    assert wilson(0, 0) == (0.0, 1.0)


def test_more_samples_narrow_the_interval_not_the_estimate():
    a, b = rate(1, 3), rate(10, 30)
    assert a["value"] == pytest.approx(b["value"])
    assert b["ci_high"] - b["ci_low"] < a["ci_high"] - a["ci_low"]


def test_rate_with_no_samples():
    assert rate(0, 0) == {
        "value": None,
        "n": 0,
        "ci_low": 0.0,
        "ci_high": 1.0,
    }


def test_samples_to_separate_projects_from_the_observed_rates():
    # Holding the observed rates, the smallest sample size at which the two
    # Wilson intervals stop overlapping. Verified by exhaustive search.
    assert samples_to_separate(3, 0, 3) == 4  # 100% vs 0%
    assert samples_to_separate(2, 1, 3) == 31  # 67% vs 33%
    # already separated at its own n, so the projection is that n
    assert samples_to_separate(9, 1, 10) == 10


def test_samples_to_separate_counts_a_rival_being_ahead():
    # `separated` flags either direction, so the projection must too.
    assert samples_to_separate(1, 2, 3) == 31


def test_samples_to_separate_is_none_when_nothing_could_separate():
    assert samples_to_separate(1, 1, 2) is None  # equal rates, any n
    assert samples_to_separate(0, 0, 0) is None  # no observations yet


def test_samples_to_separate_gives_up_at_the_cap():
    # Rates this close need far more samples than the cap allows.
    assert samples_to_separate(51, 49, 100, cap=200) is None
    assert samples_to_separate(51, 49, 100, cap=100_000) is not None
