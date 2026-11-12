#!/usr/bin/env python3
"""Focused unit tests for the family-wise Reality Check (White 2000 / Hansen 2005).

The Reality Check is the family-level multiple-testing control that complements
the per-strategy Deflated Sharpe Ratio and the Benjamini-Hochberg FDR control:
it tests whether the *best* strategy in a family beats a benchmark by more than
luck, using a stationary block bootstrap that preserves cross-sectional
dependence. Its arithmetic and edge cases are pinned directly here.

Offline, committed fixtures only; no live network.
"""

import sys
from pathlib import Path

import numpy as np

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from utils import reality_check_test  # noqa: E402


def _family(T=252, K=6, seed=2024):
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 0.01, size=(T, K))


def test_reality_check_no_skill_high_pvalue():
    """A family of zero-mean strategies should not reject H0."""
    F = _family(T=504, K=6, seed=11)
    res = reality_check_test(F, n_bootstrap=2000, seed=5)
    for key in (
        "test_statistic",
        "p_value",
        "studentized",
        "n_strategies",
        "n_observations",
        "block_size",
        "n_bootstrap",
        "best_index",
        "best_mean",
        "means",
        "alpha",
        "significant",
    ):
        assert key in res
    assert res["n_strategies"] == 6
    assert res["n_observations"] == 504
    assert res["studentized"] is True
    assert 0.0 <= res["p_value"] <= 1.0
    assert res["p_value"] > 0.10, res
    assert res["significant"] is False


def test_reality_check_dominant_strategy_rejects():
    """One strategy with a real positive edge should reject H0."""
    T = 504
    F = _family(T=T, K=6, seed=21)
    F[:, 3] = 0.01 + np.random.default_rng(99).normal(0.0, 0.001, T)
    res = reality_check_test(F, n_bootstrap=2000, seed=7)
    assert res["best_index"] == 3
    assert res["p_value"] < 0.01, res
    assert res["significant"] is True
    assert abs(res["best_mean"] - 0.01) < 0.001


def test_reality_check_benchmark_subtraction():
    """A strategy equal to the benchmark has no edge; one that beats it does."""
    T = 504
    rng = np.random.default_rng(33)
    benchmark = rng.normal(0.0, 0.01, T)
    at_benchmark = benchmark.copy()
    beats = benchmark + 0.02
    F = np.column_stack([at_benchmark, beats])
    res = reality_check_test(F, benchmark=benchmark, n_bootstrap=2000, seed=3)
    assert res["n_strategies"] == 2
    assert res["best_index"] == 1
    assert abs(res["means"][0]) < 1e-12
    assert res["p_value"] < 0.01, res


def test_reality_check_unstudentized_and_1d_equivalence():
    """The raw (unstudentized) path runs, and a 1-D input matches a 1-column 2-D input."""
    F1 = _family(T=252, K=1, seed=8).ravel()
    res_1d = reality_check_test(F1, n_bootstrap=500, seed=4, studentize=False)
    res_2d = reality_check_test(
        F1.reshape(-1, 1), n_bootstrap=500, seed=4, studentize=False
    )
    assert res_1d["n_strategies"] == 1
    assert res_1d["studentized"] is False
    assert res_1d["p_value"] == res_2d["p_value"]
    assert res_1d["test_statistic"] == res_2d["test_statistic"]


def test_reality_check_seeded_reproducible():
    """The same seed gives an identical p-value; the statistic is deterministic."""
    F = _family(T=252, K=4, seed=17)
    a = reality_check_test(F, n_bootstrap=300, seed=42)
    b = reality_check_test(F, n_bootstrap=300, seed=42)
    assert a["p_value"] == b["p_value"]
    assert a["test_statistic"] == b["test_statistic"]
    assert a["best_index"] == b["best_index"]


def test_reality_check_drops_non_finite_rows():
    """Rows with a NaN in any column are dropped listwise, keeping columns aligned."""
    F = _family(T=200, K=3, seed=6)
    F[10, 1] = np.nan
    F[50, :] = np.nan
    res = reality_check_test(F, n_bootstrap=100, seed=1)
    assert res["n_observations"] == 198


def test_reality_check_input_validation():
    """Malformed inputs raise ValueError rather than returning a bogus result."""
    F = _family(T=50, K=2, seed=1)
    for kwargs in (
        {"benchmark": np.zeros(10)},
        {"n_bootstrap": 0},
    ):
        try:
            reality_check_test(F, **kwargs)
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError(f"expected ValueError for {kwargs}")

    short = np.zeros((1, 2))
    try:
        reality_check_test(short)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for < 2 observations")

    try:
        reality_check_test(np.zeros((5, 2, 2)))
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for 3-D input")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))