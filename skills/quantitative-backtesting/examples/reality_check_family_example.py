#!/usr/bin/env python3
"""Family-wise Reality Check (White 2000 / Hansen 2005) on a strategy family.

Builds a K-column out-of-sample return matrix by running multiple strategies
on the committed real-market triple panel (AAPL/MSFT/GOOGL) with the same
chronological train/val/test split and costs, aligns the per-period returns on
common dates, then calls ``utils.reality_check_test`` to test whether the best
strategy in the family beats a benchmark by more than luck (preserving
cross-sectional dependence via the stationary block bootstrap).

Offline, committed fixtures only; no live network. No claim of profitability
is made -- this is a multiple-testing control example, not a performance
endorsement.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from data_loader import load_data, load_multi_symbol  # noqa: E402
from run_backtest import run_backtest  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402
from utils import reality_check_test, romano_wolf_stepdown  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"
BENCHMARK_PATH = SRC / "MSFT.csv"

COMMISSION = 0.0002
SLIPPAGE = 0.0001

# Pre-registered, bounded family evaluated on the same OOS test split.
STRATEGIES = [
    (
        "dual_momentum",
        {"lookback": 252, "top_quantile": 0.5, "risk_free_rate": 0.0},
    ),
    (
        "cross_sectional_momentum",
        {"lookback": 252, "skip_period": 1, "top_quantile": 0.5},
    ),
]


def build_triple_panel() -> tuple[dict, dict]:
    """Load the committed AAPL/MSFT/GOOGL panel as a multi-symbol dict."""
    with tempfile.TemporaryDirectory() as td:
        triple_path = Path(td) / "aapl_msft_googl_triple.csv"
        frames = []
        for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
            frame = pd.read_csv(SRC / name)
            frame["symbol"] = Path(name).stem
            frames.append(frame)
        pd.concat(frames, ignore_index=True).to_csv(triple_path, index=False)
        panel, provenance = load_multi_symbol(triple_path, return_provenance=True)
    return panel, provenance


def _make_args(strategy_name: str, params: dict, output_dir: Path) -> SimpleNamespace:
    return SimpleNamespace(
        data="",
        strategy=strategy_name,
        symbol="MULTI",
        start=None,
        end=None,
        commission=COMMISSION,
        commissions=None,
        slippage=SLIPPAGE,
        slippages=None,
        impact_coefficient=0.0,
        impact_coefficients=None,
        impact_model="linear",
        impact_aggregation="panel",
        regime_impact_coefficients=None,
        adv_window=20,
        max_impact=None,
        max_impacts=None,
        borrow_cost=0.0,
        borrow_costs=None,
        funding_cost=0.0,
        funding_costs=None,
        initial_capital=100000.0,
        output=str(output_dir),
        params=json.dumps(params),
        n_trials=6,
        risk_free_rate=None,
        validate_point_in_time=True,
        point_in_time_strict=False,
        multi_symbol=True,
        benchmark=None,
        benchmark_name=None,
        benchmark_names=None,
        total_return_benchmark=False,
        benchmark_commission=None,
        benchmark_slippage=None,
        benchmark_expense_ratio=None,
        benchmark_cost_is_periodic=False,
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        run_split="test",
        fill_rates=None,
        fill_rate=1.0,
        latencies=None,
        latency=0,
        adjust_splits=False,
        panel_pricing="book",
    )


def run_reality_check_family_example(
    seed: int = 12345, n_bootstrap: int = 1000
) -> tuple[dict, pd.DataFrame]:
    """Run the family Reality Check on raw OOS returns (H0: mean <= 0)."""
    panel, provenance = build_triple_panel()
    bench_df, _ = load_data(BENCHMARK_PATH, return_provenance=True)

    returns_by_strategy = {}
    for strategy_name, params in STRATEGIES:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out"
            args = _make_args(strategy_name, params, out)
            strategy = build_strategy(strategy_name, args.params)
            result = run_backtest(
                panel,
                strategy,
                args,
                data_provenance=provenance,
                benchmark=bench_df,
            )
            if result == 1 or not isinstance(result, dict):
                raise RuntimeError(f"run_backtest failed for {strategy_name}")
            series = pd.Series(result["returns"]).sort_index()
            series.name = strategy_name
            returns_by_strategy[strategy_name] = series

    # Align on common OOS dates so the bootstrap preserves cross-sectional dependence.
    family_returns = pd.concat(returns_by_strategy.values(), axis=1, join="inner").dropna(
        how="any"
    )
    if family_returns.empty or family_returns.shape[1] < 1:
        raise RuntimeError("No overlapping finite out-of-sample returns across the family")

    rc = reality_check_test(
        family_returns.to_numpy(),
        benchmark=None,
        n_bootstrap=n_bootstrap,
        seed=seed,
    )
    rc["strategy_names"] = list(family_returns.columns)
    return rc, family_returns


def run_reality_check_family_example_benchmark_subtracted(
    seed: int = 12345,
    n_bootstrap: int = 1000,
    family_returns: pd.DataFrame | None = None,
) -> tuple[dict, pd.DataFrame, pd.Series]:
    """Run the family Reality Check on benchmark-subtracted OOS returns.

    Subtracts aligned buy-and-hold MSFT per-period returns from each strategy in
    the family so the test targets H0: max_k E[r_{t,k} - b_t] <= 0 (no strategy
    beats the benchmark by more than luck) rather than raw mean <= 0.
    When ``family_returns`` is provided, it is reused instead of recomputing the
    family (avoids redundant backtests).
    """
    if family_returns is None:
        _, family_returns = run_reality_check_family_example(
            seed=seed, n_bootstrap=n_bootstrap
        )
    bench_df, _ = load_data(BENCHMARK_PATH, return_provenance=True)
    bench = bench_df.copy()
    if not isinstance(bench.index, pd.DatetimeIndex):
        bench.index = pd.to_datetime(bench.index)
    bench_ret = bench["close"].pct_change().sort_index()
    bench_aligned = bench_ret.reindex(family_returns.index)
    valid = bench_aligned.notna().to_numpy()
    if not valid.any():
        raise RuntimeError("No overlapping benchmark returns on family OOS dates")
    family_aligned = family_returns.loc[valid]
    bench_aligned = bench_aligned.loc[valid]

    rc = reality_check_test(
        family_aligned.to_numpy(),
        benchmark=bench_aligned.to_numpy(),
        n_bootstrap=n_bootstrap,
        seed=seed,
    )
    rc["strategy_names"] = list(family_aligned.columns)
    rc["benchmark"] = BENCHMARK_PATH.stem
    return rc, family_aligned, bench_aligned


def run_romano_wolf_family_stepdown(
    seed: int = 12345,
    n_bootstrap: int = 1000,
    family_returns: pd.DataFrame | None = None,
    benchmark: pd.Series | None = None,
) -> dict:
    """Identify which strategies drive the family rejection (FWER-controlled).

    Runs the Romano-Wolf (2005) stepdown on the same K-column OOS return
    matrix used by the Reality Check, reusing ``family_returns`` when supplied
    to avoid redundant backtests.

    If ``benchmark`` is provided, the stepdown tests whether any strategy
    beats the benchmark (H0: max_k E[r_{t,k} - b_t] <= 0) rather than testing
    raw mean <= 0. The benchmark Series must be aligned to the same dates as
    ``family_returns``.
    """
    if family_returns is None:
        _, family_returns = run_reality_check_family_example(
            seed=seed, n_bootstrap=n_bootstrap
        )
    res = romano_wolf_stepdown(
        family_returns.to_numpy(),
        benchmark=benchmark.to_numpy() if benchmark is not None else None,
        n_bootstrap=n_bootstrap,
        seed=seed,
    )
    res["strategy_names"] = list(family_returns.columns)
    return res


def run_romano_wolf_family_stepdown_benchmark_subtracted(
    seed: int = 12345,
    n_bootstrap: int = 1000,
    family_returns: pd.DataFrame | None = None,
) -> tuple[dict, pd.DataFrame, pd.Series]:
    """Romano-Wolf stepdown on benchmark-subtracted OOS returns.

    Subtracts aligned buy-and-hold MSFT per-period returns from each strategy in
    the family so the test targets H0: max_k E[r_{t,k} - b_t] <= 0 (no strategy
    beats the benchmark by more than luck) rather than raw mean <= 0.
    When ``family_returns`` is provided, it is reused instead of recomputing the
    family (avoids redundant backtests).
    """
    if family_returns is None:
        _, family_returns = run_reality_check_family_example(
            seed=seed, n_bootstrap=n_bootstrap
        )
    bench_df, _ = load_data(BENCHMARK_PATH, return_provenance=True)
    bench = bench_df.copy()
    if not isinstance(bench.index, pd.DatetimeIndex):
        bench.index = pd.to_datetime(bench.index)
    bench_ret = bench["close"].pct_change().sort_index()
    bench_aligned = bench_ret.reindex(family_returns.index)
    valid = bench_aligned.notna().to_numpy()
    if not valid.any():
        raise RuntimeError("No overlapping benchmark returns on family OOS dates")
    family_aligned = family_returns.loc[valid]
    bench_aligned = bench_aligned.loc[valid]

    rw = romano_wolf_stepdown(
        family_aligned.to_numpy(),
        benchmark=bench_aligned.to_numpy(),
        n_bootstrap=n_bootstrap,
        seed=seed,
    )
    rw["strategy_names"] = list(family_aligned.columns)
    rw["benchmark"] = BENCHMARK_PATH.stem
    return rw, family_aligned, bench_aligned


def main() -> int:
    rc, family_returns = run_reality_check_family_example()
    print("=== Reality Check Family Example (OOS test, net of 3bps, MSFT panel book) ===")
    print(f"Strategies: {rc['strategy_names']}")
    print(f"Family size: {rc['n_strategies']} | Observations: {rc['n_observations']}")
    print(f"Best index: {rc['best_index']} ({rc['strategy_names'][rc['best_index']]})")
    print(f"Best mean excess (per period, raw): {rc['best_mean']:.8f}")
    print(f"Studentized: {rc['studentized']} | Block size: {rc['block_size']}")
    print(f"Bootstrap resamples: {rc['n_bootstrap']} | alpha: {rc['alpha']}")
    print(f"Test statistic: {rc['test_statistic']:.6f}")
    print(f"p-value: {rc['p_value']:.6f} | significant: {rc['significant']}")

    rc_bench, _, bench_aligned = run_reality_check_family_example_benchmark_subtracted(
        n_bootstrap=500, family_returns=family_returns
    )
    print("--- Benchmark-subtracted (H0: no strategy beats buy-and-hold MSFT) ---")
    print(f"Benchmark: {rc_bench.get('benchmark')} | Observations: {rc_bench['n_observations']}")
    print(f"Best index: {rc_bench['best_index']} ({rc_bench['strategy_names'][rc_bench['best_index']]})")
    print(f"Best mean excess (per period vs benchmark): {rc_bench['best_mean']:.8f}")
    print(f"Test statistic: {rc_bench['test_statistic']:.6f}")
    print(f"p-value: {rc_bench['p_value']:.6f} | significant: {rc_bench['significant']}")

    rw = run_romano_wolf_family_stepdown(n_bootstrap=500, family_returns=family_returns)
    print("--- Romano-Wolf stepdown (identify winners, FWER-controlled) ---")
    print(f"Rejected: {rw['n_rejected']} of {rw['n_strategies']}")
    for rank, idx in enumerate(rw["ordered_indices"]):
        name = rw["strategy_names"][idx]
        print(
            f"  rank {rank}: {name} | p={rw['p_values'][rank]:.6f} "
            f"adj_p={rw['adjusted_p_values'][rank]:.6f} "
            f"mean={rw['means'][rank]:.8f} "
            f"95%CI=[{rw['ci_lower'][rank]:.8f}, {rw['ci_upper'][rank]:.8f}] "
            f"rejected={rw['rejected'][rank]}"
        )

    rw_bench, _, _ = run_romano_wolf_family_stepdown_benchmark_subtracted(
        n_bootstrap=500, family_returns=family_returns
    )
    print("--- Romano-Wolf stepdown benchmark-subtracted (H0: no strategy beats buy-and-hold MSFT) ---")
    print(f"Benchmark: {rw_bench.get('benchmark')} | Observations: {rw_bench['n_observations']}")
    print(f"Rejected: {rw_bench['n_rejected']} of {rw_bench['n_strategies']}")
    for rank, idx in enumerate(rw_bench["ordered_indices"]):
        name = rw_bench["strategy_names"][idx]
        print(
            f"  rank {rank}: {name} | p={rw_bench['p_values'][rank]:.6f} "
            f"adj_p={rw_bench['adjusted_p_values'][rank]:.6f} "
            f"mean={rw_bench['means'][rank]:.8f} "
            f"95%CI=[{rw_bench['ci_lower'][rank]:.8f}, {rw_bench['ci_upper'][rank]:.8f}] "
            f"rejected={rw_bench['rejected'][rank]}"
        )
    print("EXAMPLE COMPLETE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
