import threading

from bsi_api import ratelimit
from bsi_api.ratelimit import TokenLimiter


class Clock:
    def __init__(self, at: float = 1_000.0) -> None:
        self.at = at

    def __call__(self) -> float:
        return self.at


def test_a_key_gets_its_budget_then_waits_until_the_window_ends():
    clock = Clock(1_000.0)
    limiter = TokenLimiter(2, 60, clock)
    assert limiter.check("a") is None
    assert limiter.check("a") is None
    # The window [960, 1020) has 20 s left.
    assert limiter.check("a") == 20
    assert limiter.check("b") is None
    clock.at = 1_020.0
    assert limiter.check("a") is None


def test_the_wait_rounds_up_to_a_whole_second():
    limiter = TokenLimiter(1, 60, Clock(1_019.5))
    assert limiter.check("a") is None
    assert limiter.check("a") == 1


def test_expired_keys_are_dropped_past_the_cap(monkeypatch):
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 1)
    clock = Clock(1_000.0)
    limiter = TokenLimiter(1, 60, clock)
    assert limiter.check("a") is None
    assert limiter.check("b") is None
    clock.at = 1_060.0
    assert limiter.check("c") is None
    assert list(limiter._seen) == ["c"]


def test_the_sweep_runs_once_per_window(monkeypatch):
    monkeypatch.setattr(ratelimit, "MAX_KEYS", 1)
    clock = Clock(1_000.0)
    limiter = TokenLimiter(1, 60, clock)
    assert limiter.check("a") is None
    assert limiter.check("b") is None
    # Two keys are past the cap, so the next check sweeps: a new dict.
    before = limiter._seen
    assert limiter.check("c") is None
    assert limiter._seen is not before
    # Later in the same window a check must not rebuild the dict again.
    seen = limiter._seen
    clock.at = 1_010.0
    assert limiter.check("d") is None
    assert limiter._seen is seen
    # The next window sweeps once more and keeps only its own keys.
    clock.at = 1_060.0
    assert limiter.check("e") is None
    assert limiter._seen is not seen
    assert list(limiter._seen) == ["e"]


class Parked(dict):
    """A _seen whose writes park, so a test can hold a check between its
    read and its write."""

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0
        self.writing = threading.Event()
        self.release = threading.Event()

    def get(self, key, default=None):
        self.reads += 1
        return super().get(key, default)

    def __setitem__(self, key, value) -> None:
        self.writing.set()
        self.release.wait(5)
        super().__setitem__(key, value)


def test_checks_on_one_key_do_not_interleave():
    limiter = TokenLimiter(1, 60, Clock(1_000.0))
    seen = limiter._seen = Parked()
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(limiter.check("a")))
        for _ in range(2)
    ]
    try:
        threads[0].start()
        assert seen.writing.wait(5)
        threads[1].start()
        threads[1].join(0.2)
        # The first check holds the lock from its read to its write, so
        # the second has not read yet.
        assert threads[1].is_alive() and seen.reads == 1
    finally:
        seen.release.set()
        for t in threads:
            if t.ident is not None:
                t.join(5)
    assert sorted(results, key=str) == [20, None]
