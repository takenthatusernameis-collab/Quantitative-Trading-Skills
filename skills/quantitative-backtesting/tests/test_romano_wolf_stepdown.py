#!/usr/bin/env python3
"""Focused unit tests for the Romano-Wolf (2005) stepdown procedure.

Complements ``test_reality_check.py``: the Reality Check tests whether the
*best* strategy in a family beats a benchmark by more than luck; the stepdown
additionally identifies *which* strategies drive that rejection while
controlling the family-wise error rate.

Offline, committed fixtures only; no live network.
"""

import sys
from pathlib import Path

import numpy as np

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from utils import reality_check_test, romano_wolf_stepdown  # noqa: E402


def _family(T=504, K=6, seed=2024):
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 0.01, size=(T, K))


def test_romano_wolf_single_strategy_matches_reality_check():
    """With K=1 the stepdown p-value and statistic equal the Reality Check."""
    F = _family(T=504, K=1, seed=8).ravel()
    rc = reality_check_test(F, n_bootstrap=500, seed=4)
    rw = romano_wolf_stepdown(F, n_bootstrap=500, seed=4)
    assert rw["n_strategies"] == 1
    assert rw["statistics"][0] == rc["test_statistic"]
    assert rw["p_values"][0] == rc["p_value"]
    assert rw["adjusted_p_values"] == [rc["p_value"]]
    assert rw["rejected"] == [rc["significant"]]


def test_romano_wolf_identifies_dominant_strategy():
    """One strategy with a real edge is ordered first and rejected."""
    T = 504
    F = _family(T=T, K=6, seed=21)
    F[:, 3] = 0.01 + np.random.default_rng(99).normal(0.0, 0.001, T)
    res = romano_wolf_stepdown(F, n_bootstrap=2000, seed=7)

    assert res["ordered_indices"][0] == 3
    assert res["rejected"][0] is True
    assert res["n_rejected"] >= 1
    assert res["n_rejected"] <= res["n_strategies"]


def test_romano_wolf_no_skill_rejects_nothing():
    """A family of zero-mean strategies should not reject any strategy."""
    F = _family(T=504, K=6, seed=11)
    res = romano_wolf_stepdown(F, n_bootstrap=2000, seed=5)
    assert res["n_rejected"] == 0
    assert not any(res["rejected"])


def test_romano_wolf_adjusted_p_values_monotone_and_rejections_prefix():
    """Adjusted p-values are non-decreasing and rejections form a prefix."""
    F = _family(T=504, K=5, seed=31)
    res = romano_wolf_stepdown(F, n_bootstrap=1000, seed=13)

    adjusted = res["adjusted_p_values"]
    assert len(adjusted) == res["n_strategies"]
    assert all(adjusted[i] <= adjusted[i + 1] for i in range(len(adjusted) - 1))

    seen_false = False
    for r in res["rejected"]:
        if not r:
            seen_false = True
        else:
            assert not seen_false, "rejections must be a prefix of the ordering"


def test_romano_wolf_benchmark_subtraction():
    """A strategy equal to the benchmark is not identified as a winner."""
    T = 504
    rng = np.random.default_rng(33)
    benchmark = rng.normal(0.0, 0.01, T)
    at_benchmark = benchmark.copy()
    beats = benchmark + 0.02
    F = np.column_stack([at_benchmark, beats])
    res = romano_wolf_stepdown(F, benchmark=benchmark, n_bootstrap=2000, seed=3)

    assert res["ordered_indices"][0] == 1
    assert res["rejected"][0] is True
    assert abs(res["means"][0] - 0.02) < 1e-9


def test_romano_wolf_unstudentized_and_reproducible():
    """The unstudentized path runs and the same seed is reproducible."""
    F = _family(T=252, K=4, seed=17)
    a = romano_wolf_stepdown(F, n_bootstrap=300, seed=42)
    b = romano_wolf_stepdown(F, n_bootstrap=300, seed=42)
    assert a["studentized"] is True
    assert a["p_values"] == b["p_values"]
    assert a["statistics"] == b["statistics"]
    assert a["ordered_indices"] == b["ordered_indices"]

    raw = romano_wolf_stepdown(F, n_bootstrap=300, seed=42, studentize=False)
    assert raw["studentized"] is False
    assert raw["ordered_indices"] == a["ordered_indices"]


def test_romano_wolf_drops_non_finite_rows():
    """Rows with a NaN in any column are dropped listwise."""
    F = _family(T=200, K=3, seed=6)
    F[10, 1] = np.nan
    F[50, :] = np.nan
    res = romano_wolf_stepdown(F, n_bootstrap=100, seed=1)
    assert res["n_observations"] == 198


def test_romano_wolf_input_validation():
    """Malformed inputs raise ValueError rather than returning a bogus result."""
    F = _family(T=50, K=2, seed=1)
    for kwargs in (
        {"benchmark": np.zeros(10)},
        {"n_bootstrap": 0},
    ):
        try:
            romano_wolf_stepdown(F, **kwargs)
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError(f"expected ValueError for {kwargs}")

    short = np.zeros((1, 2))
    try:
        romano_wolf_stepdown(short)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for < 2 observations")

    try:
        romano_wolf_stepdown(np.zeros((5, 2, 2)))
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for 3-D input")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))