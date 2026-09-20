"""The eval's pure statistics, so the reported numbers mean something."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "prompt_eval", Path("scripts/prompt_eval.py")
)
assert _spec and _spec.loader
prompt_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prompt_eval)


def test_pairwise_covers_every_unordered_pair():
    vectors = [[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]
    pairs = prompt_eval.pairwise(vectors)
    assert [(i, j) for _, i, j in pairs] == [(0, 1), (0, 2), (1, 2)]
    sims = [round(s, 4) for s, _, _ in pairs]
    assert sims == [0.0, 0.7071, 0.7071]


def test_summarize_reports_spread_and_threshold_counts():
    sims = [i / 100 for i in range(1, 101)]  # 0.01 .. 1.00
    got = prompt_eval.summarize(sims)
    assert got["n_pairs"] == 100
    assert (got["min"], got["max"]) == (0.01, 1.0)
    assert got["median"] == 0.505
    assert got["p90"] == 0.909  # statistics.quantiles, as the probe used
    # Inclusive: 0.92 .. 1.00 is nine of the hundred.
    assert got["at_or_above"]["0.92"] == 9
    assert got["at_or_above"]["0.95"] == 6


def test_summarize_of_nothing_is_empty_not_a_crash():
    assert prompt_eval.summarize([]) == {"n_pairs": 0}
