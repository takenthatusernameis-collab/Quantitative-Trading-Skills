#!/usr/bin/env python3
"""
Example demonstrating deflated alpha ratio computation.

Shows how to use deflated_alpha_ratio directly to correct for
multiple testing when evaluating a strategy against multiple
benchmarks.
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from walk_forward import deflated_alpha_ratio, _annualization_factor


def run_deflated_alpha_example():
    print("=" * 80)
    print("DEFLATED ALPHA RATIO: WORKED EXAMPLE")
    print("=" * 80)
    print()

    np.random.seed(42)
    dates = pd.date_range('2018-01-01', periods=252 * 2, freq='B')  # 2 years of business days

    # Strategy returns (slightly positive alpha vs benchmark)
    bench_rets = pd.Series(np.random.normal(0.0005, 0.015, len(dates)), index=dates)
    strat_rets = bench_rets * 1.0 + np.random.normal(0.0002, 0.005, len(dates))  # ~5% annual alpha
    strat_rets = pd.Series(strat_rets, index=dates)

    ann_factor = _annualization_factor(dates)
    alpha_annual = float((1 + strat_rets - bench_rets).mean()) * ann_factor if False else None  # simple approx
    # Better: compute OLS alpha approximation
    # For demo, assume alpha ~ 0.05 annual
    alpha_annual = 0.05

    print("1. SINGLE BENCHMARK (N=1) - No multiple-testing correction")
    print("-" * 50)
    da_single = deflated_alpha_ratio(
        alpha=alpha_annual,
        returns=strat_rets,
        benchmark_returns=bench_rets,
        n_benchmarks=1,
        trial_alphas=[alpha_annual],
    )
    print(f"DAR: {da_single['deflated_alpha_ratio']:.4f}, p-value: {da_single['p_value']:.4f}")
    print("(With N=1, correction is minimal)")
    print()

    print("2. MULTIPLE BENCHMARKS (N=5) - With trial alphas")
    print("-" * 50)
    trial_alphas = [0.05, 0.03, 0.08, -0.01, 0.02]  # Alphas found across 5 benchmarks
    da_multi = deflated_alpha_ratio(
        alpha=alpha_annual,
        returns=strat_rets,
        benchmark_returns=bench_rets,
        n_benchmarks=5,
        trial_alphas=trial_alphas,
    )
    print(f"Strategy alpha:        {alpha_annual:.2%}")
    print(f"Trial alphas tested:   {trial_alphas}")
    print(f"Expected max alpha:    {da_multi['expected_max_alpha']:.4%}")
    print(f"DAR:                   {da_multi['deflated_alpha_ratio']:.4f}")
    print(f"P-value:               {da_multi['p_value']:.4f}")
    print("(Higher N makes it harder to reject null; correction is stronger)")
    print()

    print("3. MULTIPLE BENCHMARKS (N=10) - Without trial alphas (fallback)")
    print("-" * 50)
    da_fallback = deflated_alpha_ratio(
        alpha=alpha_annual,
        returns=strat_rets,
        benchmark_returns=bench_rets,
        n_benchmarks=10,
    )
    print(f"DAR: {da_fallback['deflated_alpha_ratio']:.4f}, p-value: {da_fallback['p_value']:.4f}")
    print("(Fallback uses i.i.d. normal approximation when trial_alphas not provided)")
    print()

    print("=" * 80)
    print("EXAMPLE COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    run_deflated_alpha_example()
