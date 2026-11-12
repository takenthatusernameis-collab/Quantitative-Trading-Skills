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
    assert len(raw["simultaneous_ci_lower"]) == raw["n_strategies"]
    for lo, hi, mean in zip(
        raw["simultaneous_ci_lower"], raw["simultaneous_ci_upper"], raw["means"]
    ):
        assert lo <= mean <= hi


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

    for bad_alpha in (0.0, 1.0, -0.1, 1.5):
        try:
            romano_wolf_stepdown(F, n_bootstrap=50, seed=1, alpha=bad_alpha)
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError(f"expected ValueError for alpha={bad_alpha}")

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


def test_romano_wolf_confidence_interval_contract():
    """Per-strategy percentile bootstrap CIs are aligned and ordered."""
    F = _family(T=504, K=4, seed=23)
    res = romano_wolf_stepdown(F, n_bootstrap=1000, seed=9)

    assert res["ci_level"] == 0.95
    assert len(res["ci_lower"]) == res["n_strategies"]
    assert len(res["ci_upper"]) == res["n_strategies"]
    for lo, hi, mean in zip(res["ci_lower"], res["ci_upper"], res["means"]):
        assert lo <= hi
        # A percentile bootstrap interval for the mean should bracket the
        # sample mean for these well-behaved Gaussian families.
        assert lo <= mean <= hi


def test_romano_wolf_confidence_interval_reproducible_and_seed_sensitive():
    """Same seed reproduces the CIs; a different seed moves them."""
    F = _family(T=504, K=3, seed=29)
    a = romano_wolf_stepdown(F, n_bootstrap=500, seed=17)
    b = romano_wolf_stepdown(F, n_bootstrap=500, seed=17)
    c = romano_wolf_stepdown(F, n_bootstrap=500, seed=18)

    assert a["ci_lower"] == b["ci_lower"]
    assert a["ci_upper"] == b["ci_upper"]
    assert a["ci_lower"] != c["ci_lower"] or a["ci_upper"] != c["ci_upper"]


def test_romano_wolf_confidence_interval_widens_with_level():
    """A higher confidence level yields weakly wider intervals."""
    F = _family(T=504, K=3, seed=41)
    lo95 = romano_wolf_stepdown(F, n_bootstrap=1000, seed=5, ci_level=0.95)
    lo99 = romano_wolf_stepdown(F, n_bootstrap=1000, seed=5, ci_level=0.99)

    for i in range(lo95["n_strategies"]):
        width95 = lo95["ci_upper"][i] - lo95["ci_lower"][i]
        width99 = lo99["ci_upper"][i] - lo99["ci_lower"][i]
        assert width99 >= width95


def test_romano_wolf_confidence_interval_benchmark_subtraction():
    """A strategy at the benchmark has a CI covering zero; a real edge does not."""
    T = 504
    rng = np.random.default_rng(53)
    benchmark = rng.normal(0.0, 0.01, T)
    at_benchmark = benchmark.copy()
    beats = benchmark + 0.02
    F = np.column_stack([at_benchmark, beats])
    res = romano_wolf_stepdown(F, benchmark=benchmark, n_bootstrap=2000, seed=3)

    # ordered_indices[0] is the genuine-edge strategy (column 1).
    assert res["ordered_indices"][0] == 1
    assert res["ci_lower"][0] > 0.0
    # The at-benchmark strategy is ordered last; its CI covers zero.
    at_bench_rank = res["ordered_indices"].index(0)
    assert res["ci_lower"][at_bench_rank] <= 0.0 <= res["ci_upper"][at_bench_rank]


def test_romano_wolf_confidence_interval_validation():
    """An out-of-range ci_level raises ValueError."""
    F = _family(T=100, K=2, seed=2)
    for bad in (0.0, 1.0, -0.1, 1.5):
        try:
            romano_wolf_stepdown(F, n_bootstrap=50, seed=1, ci_level=bad)
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError(f"expected ValueError for ci_level={bad}")


def test_romano_wolf_simultaneous_ci_contract():
    """FWER-adjusted max-t bands are aligned, bracket the mean, and are valid."""
    F = _family(T=504, K=4, seed=23)
    res = romano_wolf_stepdown(F, n_bootstrap=1000, seed=9, alpha=0.05)

    assert res["simultaneous_ci_level"] == 0.95
    assert res["simultaneous_ci_method"] == "max-t"
    assert res["simultaneous_ci_critical_value"] > 0.0
    assert res["simultaneous_ci_small_sample_warning"] is None
    assert len(res["simultaneous_ci_lower"]) == res["n_strategies"]
    assert len(res["simultaneous_ci_upper"]) == res["n_strategies"]
    for lo, hi, mean in zip(
        res["simultaneous_ci_lower"], res["simultaneous_ci_upper"], res["means"]
    ):
        assert lo <= hi
        assert lo <= mean <= hi


def test_romano_wolf_simultaneous_ci_wider_than_marginal():
    """The simultaneous band is at least as wide as the marginal interval."""
    F = _family(T=504, K=4, seed=41)
    res = romano_wolf_stepdown(
        F, n_bootstrap=1000, seed=5, ci_level=0.95, alpha=0.05
    )
    for i in range(res["n_strategies"]):
        marginal_width = res["ci_upper"][i] - res["ci_lower"][i]
        simultaneous_width = (
            res["simultaneous_ci_upper"][i] - res["simultaneous_ci_lower"][i]
        )
        assert simultaneous_width >= marginal_width - 1e-12


def test_romano_wolf_simultaneous_ci_reproducible_and_seed_sensitive():
    """Same seed reproduces the simultaneous bands; a different seed moves them."""
    F = _family(T=504, K=3, seed=29)
    a = romano_wolf_stepdown(F, n_bootstrap=500, seed=17)
    b = romano_wolf_stepdown(F, n_bootstrap=500, seed=17)
    c = romano_wolf_stepdown(F, n_bootstrap=500, seed=18)

    assert a["simultaneous_ci_lower"] == b["simultaneous_ci_lower"]
    assert a["simultaneous_ci_upper"] == b["simultaneous_ci_upper"]
    assert (
        a["simultaneous_ci_lower"] != c["simultaneous_ci_lower"]
        or a["simultaneous_ci_upper"] != c["simultaneous_ci_upper"]
    )


def test_romano_wolf_simultaneous_ci_benchmark_subtraction():
    """A benchmark strategy's simultaneous band covers zero; a real edge does not."""
    T = 504
    rng = np.random.default_rng(53)
    benchmark = rng.normal(0.0, 0.01, T)
    at_benchmark = benchmark.copy()
    beats = benchmark + 0.02
    F = np.column_stack([at_benchmark, beats])
    res = romano_wolf_stepdown(F, benchmark=benchmark, n_bootstrap=2000, seed=3)

    assert res["ordered_indices"][0] == 1
    assert res["simultaneous_ci_lower"][0] > 0.0
    at_bench_rank = res["ordered_indices"].index(0)
    assert (
        res["simultaneous_ci_lower"][at_bench_rank]
        <= 0.0
        <= res["simultaneous_ci_upper"][at_bench_rank]
    )


def test_romano_wolf_simultaneous_ci_fwer_coverage():
    """Across zero-mean families the simultaneous bands cover all means ~95% of the time.

    This is a Monte Carlo check of the max-t construction: marginal 95%
    intervals would cover all K means far less often (roughly 0.95**K under
    independence). The fixed seed makes the check deterministic.
    """
    rng = np.random.default_rng(2026)
    T, K, n_sim, n_boot = 504, 4, 60, 300
    covered = 0
    for s in range(n_sim):
        F = rng.normal(0.0, 0.01, size=(T, K))
        res = romano_wolf_stepdown(
            F, n_bootstrap=n_boot, seed=5000 + s, alpha=0.05
        )
        if all(
            lo <= 0.0 <= hi
            for lo, hi in zip(
                res["simultaneous_ci_lower"], res["simultaneous_ci_upper"]
            )
        ):
            covered += 1
    assert covered / n_sim >= 0.90, (
        "simultaneous bands undercovered the joint null: "
        f"{covered}/{n_sim} families covered"
    )


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))


def test_romano_wolf_simultaneous_ci_small_sample_warning():
    """Short samples emit a small-sample warning; T>=504 does not."""
    short = romano_wolf_stepdown(_family(T=252, K=3, seed=71), n_bootstrap=100, seed=5)
    assert isinstance(short["simultaneous_ci_small_sample_warning"], str)
    assert "undercover" in short["simultaneous_ci_small_sample_warning"]
    assert "252" in short["simultaneous_ci_small_sample_warning"]

    long = romano_wolf_stepdown(_family(T=504, K=3, seed=71), n_bootstrap=100, seed=5)
    assert long["simultaneous_ci_small_sample_warning"] is None
