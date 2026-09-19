"""Visibility metrics. Every rate carries its sample size and a Wilson CI."""

from math import sqrt


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def rate(k: int, n: int) -> dict[str, float | int | None]:
    low, high = wilson(k, n)
    return {
        "value": k / n if n else None,
        "n": n,
        "ci_low": low,
        "ci_high": high,
    }
