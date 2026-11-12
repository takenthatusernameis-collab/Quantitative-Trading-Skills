#!/usr/bin/env python3
"""Unit tests for Benjamini-Hochberg FDR control and its benchmark integration."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from utils import benjamini_hochberg  # noqa: E402
from walk_forward import _benchmark_list_alpha_correction  # noqa: E402


def _make_benchmark_data(periods: int = 252, seed: int = 99) -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    rng = np.random.default_rng(seed)
    close = 100.0 * np.cumprod(1.0 + rng.normal(0.0003, 0.01, periods))
    return pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": rng.integers(900000, 1100000, periods),
        },
        index=dates,
    )


def test_benjamini_hochberg_known_values():
    # Classic BH example
    res = benjamini_hochberg([0.01, 0.04, 0.03, 0.005, 0.8])
    q = res["q_values"]
    assert res["n_tests"] == 5
    # Expected BH q-values (step-up monotone): m* p_i/rank_i cummin from right
    # sorted asc by p: (0.005,r1)->0.025,(0.01,r2)->0.025,(0.03,r3)->0.05,(0.04,r4)->0.05,(0.8,r5)->0.8
    expected = [0.025, 0.05, 0.05, 0.025, 0.8]
    for got, exp in zip(q, expected):
        assert abs(got - exp) < 1e-12, (q, expected)
    assert res["rejected"] == [True, True, True, True, False]
    assert res["n_rejected"] == 4


def test_benjamini_hochberg_single_and_empty():
    single = benjamini_hochberg([0.03])
    assert single["q_values"] == [0.03]
    assert single["rejected"] == [True]
    assert single["n_tests"] == 1

    empty = benjamini_hochberg([])
    assert empty["q_values"] == []
    assert empty["n_tests"] == 0
    assert empty["n_rejected"] == 0


def test_benjamini_hochberg_handles_nan_and_bounds():
    res = benjamini_hochberg([0.01, np.nan, 1.5, -0.2])
    # NaN -> q=1.0 invalid; 1.5 clamped to 1.0 valid; -0.2 clamped to 0.0 valid
    assert res["n_tests"] == 3
    q = res["q_values"]
    assert q[1] == 1.0
    assert 0.0 <= q[0] <= 1.0
    assert 0.0 <= q[2] <= 1.0
    assert 0.0 <= q[3] <= 1.0
    # p clamped to 0.0 should yield q 0.0
    assert abs(q[3] - 0.0) < 1e-12


def test_benchmark_list_alpha_correction_reports_fdr_bh_qvalues():
    periods = 252
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    bench1 = _make_benchmark_data(periods=periods, seed=99)
    bench2 = _make_benchmark_data(periods=periods, seed=7)
    strategy_returns = pd.Series(
        np.random.default_rng(123).normal(0.0005, 0.012, periods), index=dates
    )

    result = _benchmark_list_alpha_correction(
        strategy_returns,
        [bench1, bench2],
        benchmark_commission=0.001,
        benchmark_slippage=0.001,
        benchmark_cost_is_periodic=True,
    )
    assert result["n_benchmarks"] == 2
    for stats in result["per_benchmark"]:
        assert stats is not None
        assert "alpha_qvalue_fdr_bh" in stats
        assert "alpha_fdr_bh_rejected" in stats
        assert 0.0 <= float(stats["alpha_qvalue_fdr_bh"]) <= 1.0
        assert isinstance(stats["alpha_fdr_bh_rejected"], bool)

    family_p = [s["alpha_pvalue"] for s in result["per_benchmark"]]
    bh = benjamini_hochberg(family_p)
    for i, stats in enumerate(result["per_benchmark"]):
        assert abs(stats["alpha_qvalue_fdr_bh"] - bh["q_values"][i]) < 1e-12


TESTS = [
    test_benjamini_hochberg_known_values,
    test_benjamini_hochberg_single_and_empty,
    test_benjamini_hochberg_handles_nan_and_bounds,
    test_benchmark_list_alpha_correction_reports_fdr_bh_qvalues,
]


def main() -> int:
    failed = 0
    for test in TESTS:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {test.__name__}")
            import traceback

            traceback.print_exc()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
