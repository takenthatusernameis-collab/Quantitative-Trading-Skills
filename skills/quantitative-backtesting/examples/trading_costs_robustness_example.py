#!/usr/bin/env python3
"""
Trading Costs & Robustness Sensitivity Analysis Example

Demonstrates how transaction costs and cost-modeling assumptions affect both
strategy profitability and statistical inference:

  1. Strategy cost sensitivity — sweeps commission and slippage on the strategy
     side, measuring how Sharpe, Calmar, and max drawdown degrade.
  2. Benchmark cost-model sensitivity — sweeps benchmark commission, expense
     ratio, and periodic-vs-round-trip costing, showing the impact on estimated
     alpha and the Deflated Alpha Ratio (DAR).
  3. CPCV robustness under cost stress — compares out-of-sample Sharpe, return,
     and DAR between low-cost and high-cost regimes.

All data is synthetic (generated via generate_sample_data.py); no external
network access is required.
"""

import json
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

# Suppress numpy RuntimeWarnings from correlation computation when a series
# has zero variance (e.g., a flat benchmark after heavy cost deductions).
warnings.filterwarnings("ignore", category=RuntimeWarning, module="numpy")

# Add scripts to path
scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from generate_sample_data import generate_multi_asset_data  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402
from walk_forward import (  # noqa: E402
    cpcv_analysis,
    _calculate_strategy_returns,
    _benchmark_list_alpha_correction,
)
from performance import calculate_metrics  # noqa: E402


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

INITIAL_CAPITAL = 100_000.0
N_PERIODS = 756          # ~3 years of business days
N_ASSETS = 8
STRATEGY_PARAMS = {"fast_period": 10, "slow_period": 30}
CPCV_PARAM_GRID = {"fast_period": [5, 10, 15], "slow_period": [20, 30, 40]}
CPCV_N_SPLITS = 5

# Strategy cost sweep grids (expressed as decimals, 1 bps = 0.0001)
COMMISSION_GRID = [0.0, 0.0001, 0.0005, 0.0010]    # 0, 1, 5, 10 bps
SLIPPAGE_GRID = [0.0, 0.0001, 0.0005]               # 0, 1, 5 bps

# Extended cost sweep grids for borrow and funding costs (annualized)
BORROW_COST_GRID = [0.0, 0.03]                      # 0%, 3% annual
FUNDING_COST_GRID = [0.0, 0.02]                     # 0%, 2% annual

# Benchmark cost-model sweep grids
BENCH_COST_MODES = [False, True]                    # round-trip vs periodic
BENCH_EXPENSE_GRID = [0.0, 0.005, 0.01]             # 0 %, 0.5 %, 1 % annual
BENCH_TRADING_COST_GRID = [0.0, 0.0005, 0.0010]     # 0, 5, 10 bps total commission+slippage


def _safe_float(v):
    """Convert a value to a finite float, or None if not finite / not a number."""
    if v is None:
        return None
    try:
        f = float(v)
        return f if np.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _make_universe():
    """Generate a synthetic universe and return (strategy_df, benchmark_dfs, symbols)."""
    raw = generate_multi_asset_data(n_assets=N_ASSETS, periods=N_PERIODS, seed=42)
    # generate_multi_asset_data stores dates in a ``date`` column; set DatetimeIndex
    assets = {sym: df.set_index("date") for sym, df in raw.items()}
    symbols = sorted(assets.keys())
    strategy_df = assets[symbols[0]]
    benchmark_dfs = [assets[symbols[1]], assets[symbols[2]]]
    return strategy_df, benchmark_dfs, symbols


def _make_flat_benchmark(strategy_df):
    """Create a flat benchmark (near-zero drift) from the strategy's date index.

    A flat benchmark has near-constant close prices with small noise,
    yielding ~0% returns with minimal variance. This produces a positive
    alpha for any strategy with positive returns, resulting in a high DAR
    that costs erode.
    """
    dates = strategy_df.index
    n = len(dates)
    rng = np.random.default_rng(12345)
    # Near-zero drift with small noise (0.1% annual vol)
    daily_vol = 0.001 / np.sqrt(252)
    daily_drift = 0.001 / 252  # 0.1% annual drift
    returns = rng.normal(loc=daily_drift, scale=daily_vol, size=n)
    close = 100.0 * np.exp(np.cumsum(returns))
    volume = rng.integers(500_000, 2_000_000, n)
    flat_df = pd.DataFrame({
        "close": close,
        "volume": volume,
    }, index=dates)
    return flat_df


def _make_negative_drift_benchmark(strategy_df):
    """Create a negatively-drifting benchmark from the strategy's date index.

    A negative drift benchmark has declining close prices with noise,
    yielding negative returns. This amplifies the strategy's positive alpha,
    producing a high DAR.
    """
    dates = strategy_df.index
    n = len(dates)
    rng = np.random.default_rng(54321)
    # Strong negative drift: -15% annualized with realistic vol (15% annual)
    # This ensures the strategy (which has ~-3% annualized return) has
    # positive alpha vs this benchmark.
    daily_drift = -0.15 / 252
    daily_vol = 0.15 / np.sqrt(252)
    returns = rng.normal(loc=daily_drift, scale=daily_vol, size=n)
    close = 100.0 * np.exp(np.cumsum(returns))
    volume = rng.integers(500_000, 2_000_000, n)
    neg_df = pd.DataFrame({
        "close": close,
        "volume": volume,
    }, index=dates)
    return neg_df


def _make_degraded_strategy_benchmark(strategy_df, drag_annual=-0.10):
    """Create a benchmark derived from the strategy asset but with a performance drag.

    This benchmark is perfectly correlated with the strategy asset but has
    a drag applied (default -10% annual). This guarantees positive alpha for the
    strategy (since it outperforms this degraded version of itself), producing
    a meaningful DAR that varies with cost assumptions.
    """
    dates = strategy_df.index
    # Apply an annual drag to the strategy's close prices
    n = len(dates)
    daily_drag = drag_annual / 252
    drag_factor = np.exp(np.cumsum(np.full(n, daily_drag)))
    degraded_close = strategy_df["close"].values * drag_factor
    # Volume with some noise
    rng = np.random.default_rng(98765)
    volume = rng.integers(500_000, 2_000_000, n)
    deg_df = pd.DataFrame({
        "close": degraded_close,
        "volume": volume,
    }, index=dates)
    return deg_df


def _strategy_signals(data_df):
    """Build an SMA-crossover strategy and generate position signals."""
    strategy = build_strategy("sma_crossover", json.dumps(STRATEGY_PARAMS))
    return strategy.generate_signals(data_df)


def _metrics_from_returns(returns):
    """Compute a compact performance-metrics dict from a return Series."""
    equity = (1 + returns).cumprod() * INITIAL_CAPITAL
    m = calculate_metrics({"returns": returns, "equity_curve": equity})
    return {
        "total_return": _safe_float(m.get("total_return")),
        "annualized_return": _safe_float(m.get("annualized_return")),
        "annualized_volatility": _safe_float(m.get("annualized_volatility")),
        "sharpe_ratio": _safe_float(m.get("sharpe_ratio")),
        "max_drawdown": _safe_float(m.get("max_drawdown")),
        "calmar_ratio": _safe_float(m.get("calmar_ratio")),
    }


# ---------------------------------------------------------------------------
# Section 1: Strategy cost sensitivity
# ---------------------------------------------------------------------------

def run_strategy_cost_sweep(data_df):
    """Sweep strategy commission × slippage and report net performance metrics."""
    print("1. STRATEGY COST SENSITIVITY SWEEP")
    print("-" * 75)

    signals = _strategy_signals(data_df)
    baseline_returns = _calculate_strategy_returns(
        data_df, signals, commission=0.0, slippage=0.0,
        borrow_cost=0.0, funding_cost=0.0,
    )
    baseline = _metrics_from_returns(baseline_returns)
    print(
        f"   Baseline (0 bps costs):  Sharpe={baseline['sharpe_ratio']:.3f}  "
        f"Return={baseline['total_return']:.2%}  "
        f"MaxDD={baseline['max_drawdown']:.2%}"
    )
    print()

    header = (
        f"   {'Comm':>6} | {'Slip':>6} | {'Borrow':>6} | {'Fund':>6} | {'Total':>6} | "
        f"{'Return':>8} | {'Sharpe':>7} | {'Calmar':>7} | {'MaxDD':>8}"
    )
    print(header)
    print("   " + "-" * (len(header) - 3))

    results = []
    for commission in COMMISSION_GRID:
        for slippage in SLIPPAGE_GRID:
            for borrow_cost in BORROW_COST_GRID:
                for funding_cost in FUNDING_COST_GRID:
                    returns = _calculate_strategy_returns(
                        data_df, signals,
                        commission=commission, slippage=slippage,
                        borrow_cost=borrow_cost, funding_cost=funding_cost,
                    )
                    m = _metrics_from_returns(returns)
                    entry = {
                        "commission_bps": commission * 10_000,
                        "slippage_bps": slippage * 10_000,
                        "borrow_cost_annual_pct": borrow_cost * 100,
                        "funding_cost_annual_pct": funding_cost * 100,
                        "total_cost_bps": (commission + slippage) * 10_000,
                        **m,
                    }
                    results.append(entry)
                    calmar = "N/A" if m["calmar_ratio"] is None else f"{m['calmar_ratio']:.3f}"
                    print(
                        f"   {entry['commission_bps']:>4.0f} bp | "
                        f"{entry['slippage_bps']:>4.0f} bp | "
                        f"{entry['borrow_cost_annual_pct']:>4.0f}% | "
                        f"{entry['funding_cost_annual_pct']:>4.0f}% | "
                        f"{entry['total_cost_bps']:>4.0f} bp | "
                        f"{m['total_return']:>7.2%} | "
                        f"{m['sharpe_ratio']:>6.3f} | "
                        f"{calmar:>7} | "
                        f"{m['max_drawdown']:>7.2%}"
                    )

    first = results[0]
    last = results[-1]
    print()
    print(f"   Cost impact (0 bps / 0% borrow/funding → {int(last['total_cost_bps'])} bps / {last['borrow_cost_annual_pct']:.0f}% borrow / {last['funding_cost_annual_pct']:.0f}% funding):")
    print(f"     Sharpe:  {first['sharpe_ratio']:.3f} → {last['sharpe_ratio']:.3f} "
          f"(Δ {last['sharpe_ratio'] - first['sharpe_ratio']:+.3f})")
    print(f"     Return:  {first['total_return']:.2%} → {last['total_return']:.2%} "
          f"(Δ {last['total_return'] - first['total_return']:+.2%})")
    print()
    return results, baseline_returns


# ---------------------------------------------------------------------------
# Section 2: Benchmark cost-model sensitivity
# ---------------------------------------------------------------------------

def run_benchmark_cost_sweep(strategy_returns, benchmark_dfs, strategy_df=None):
    """Sweep benchmark cost mode, expense ratio, and trading costs.

    Shows how the cost-modeling assumption (periodic vs round-trip) and
    expense ratio affect the estimated alpha and the Deflated Alpha Ratio.

    Also runs a positive-alpha scenario using a flat benchmark and a
    negative-drift benchmark to demonstrate how cost assumptions affect
    statistical inference when the strategy actually shows skill.
    """
    print("2. BENCHMARK COST-MODEL SENSITIVITY (DEFLATED ALPHA)")
    print("-" * 75)

    header = (
        f"   {'Mode':>11} | {'Expense':>8} | {'Bench':>7} | "
        f"{'Alpha':>8} | {'p(uncorr)':>9} | {'p(corr)':>8} | {'DAR':>6}"
    )
    print(header)
    print("   " + "-" * (len(header) - 3))

    results = []
    for cost_is_periodic in BENCH_COST_MODES:
        mode_label = "periodic" if cost_is_periodic else "round-trip"
        for expense in BENCH_EXPENSE_GRID:
            for bench_cost in BENCH_TRADING_COST_GRID:
                correction = _benchmark_list_alpha_correction(
                    strategy_returns, benchmark_dfs,
                    benchmark_commission=bench_cost / 2,
                    benchmark_slippage=bench_cost / 2,
                    benchmark_expense_ratio=expense,
                    benchmark_cost_is_periodic=cost_is_periodic,
                )
                da = correction.get("deflated_alpha") or {}
                per_bench = correction.get("per_benchmark") or []
                primary = per_bench[0] if per_bench else {}
                dar = _safe_float(da.get("deflated_alpha_ratio"))
                entry = {
                    "cost_mode": mode_label,
                    "benchmark_cost_is_periodic": cost_is_periodic,
                    "expense_ratio": expense,
                    "bench_cost_bps": bench_cost * 10_000,
                    "alpha": _safe_float(primary.get("alpha")),
                    "alpha_pvalue_original": _safe_float(primary.get("alpha_pvalue_original")),
                    "alpha_pvalue": _safe_float(primary.get("alpha_pvalue")),
                    "deflated_alpha_ratio": dar,
                    "dar_pvalue": _safe_float(da.get("p_value")),
                    "n_benchmarks": int(da.get("n_benchmarks", len(benchmark_dfs))),
                    "scenario": "original",
                }
                results.append(entry)
                dar_str = "N/A" if dar is None else f"{dar:.3f}"
                print(
                    f"   {mode_label:>11} | "
                    f"{expense:>7.1%} | "
                    f"{bench_cost*10_000:>5.0f} bp | "
                    f"{entry['alpha'] or 0:>7.2%} | "
                    f"{entry['alpha_pvalue_original'] or 1:>8.4f} | "
                    f"{entry['alpha_pvalue'] or 1:>7.4f} | "
                    f"{dar_str:>6}"
                )

# --- Positive-alpha scenarios ---
    if strategy_df is not None:
        print()
        print("   --- POSITIVE-ALPHA SCENARIOS ---")
        print()

        # Degraded strategy benchmarks: primary (-10% drag) + secondary (-20% drag)
        # The primary benchmark is the one we evaluate alpha against; the secondary
        # provides cross-sectional dispersion for the Deflated Alpha Ratio.
        # Using a more extreme secondary benchmark creates meaningful alpha dispersion.
        deg_bench_primary = _make_degraded_strategy_benchmark(strategy_df, drag_annual=-0.10)
        deg_bench_secondary = _make_degraded_strategy_benchmark(strategy_df, drag_annual=-0.20)
        print("   Degraded strategy benchmarks (primary: -10% drag, secondary: -20% drag):")
        deg_results = _run_benchmark_sweep_for_benchmark(
            strategy_returns, [deg_bench_primary, deg_bench_secondary], "degraded_strategy", header
        )
        results.extend(deg_results)

        # Negative drift benchmark (-15% annual)
        neg_bench = _make_negative_drift_benchmark(strategy_df)
        print("   Negative-drift benchmark (-15% annual):")
        neg_results = _run_benchmark_sweep_for_benchmark(
            strategy_returns, neg_bench, "negative_drift", header
        )
        results.extend(neg_results)

    print()

    # Interpretation note: DAR is the probability that the strategy's true alpha
    # exceeds the best alpha expected from luck alone. A near-zero DAR indicates
    # no statistical evidence of skill — the strategy's alpha is not significantly
    # positive.  The key sensitivity here is in the *alpha estimate* and
    # *p-value*: cost-modeling assumptions (periodic vs round-trip, expense
    # ratios) shift the estimated alpha and its original (uncorrected) p-value,
    # even when the corrected DAR remains near zero for a weak strategy.
    print("   Note: DAR (Deflated Alpha Ratio) is the probability that the true")
    print("   alpha exceeds the best alpha expected from luck alone. Near-zero DAR")
    print("   means no evidence of skill; the interesting sensitivity is in the")
    print("   estimated alpha and uncorrected p-value across cost-modeling choices.")
    print("   Positive-alpha scenarios (flat/negative-drift benchmarks) show how")
    print("   cost assumptions affect statistical inference when skill is present.")
    print()
    return results


def _run_benchmark_sweep_for_benchmark(strategy_returns, benchmark_df_or_list, scenario_label, header):
    """Run the benchmark cost sweep for a single benchmark or list of benchmarks and return results."""
    # Normalize to list
    if isinstance(benchmark_df_or_list, pd.DataFrame):
        benchmark_list = [benchmark_df_or_list]
    else:
        benchmark_list = benchmark_df_or_list

    print(f"   {'Mode':>11} | {'Expense':>8} | {'Bench':>7} | "
          f"{'Alpha':>8} | {'p(uncorr)':>9} | {'p(corr)':>8} | {'DAR':>6}")
    print("   " + "-" * (len(header) - 3))

    results = []
    for cost_is_periodic in BENCH_COST_MODES:
        mode_label = "periodic" if cost_is_periodic else "round-trip"
        for expense in BENCH_EXPENSE_GRID:
            for bench_cost in BENCH_TRADING_COST_GRID:
                correction = _benchmark_list_alpha_correction(
                    strategy_returns, benchmark_list,
                    benchmark_commission=bench_cost / 2,
                    benchmark_slippage=bench_cost / 2,
                    benchmark_expense_ratio=expense,
                    benchmark_cost_is_periodic=cost_is_periodic,
                )
                da = correction.get("deflated_alpha") or {}
                per_bench = correction.get("per_benchmark") or []
                primary = per_bench[0] if per_bench else {}
                dar = _safe_float(da.get("deflated_alpha_ratio"))
                entry = {
                    "cost_mode": mode_label,
                    "benchmark_cost_is_periodic": cost_is_periodic,
                    "expense_ratio": expense,
                    "bench_cost_bps": bench_cost * 10_000,
                    "alpha": _safe_float(primary.get("alpha")),
                    "alpha_pvalue_original": _safe_float(primary.get("alpha_pvalue_original")),
                    "alpha_pvalue": _safe_float(primary.get("alpha_pvalue")),
                    "deflated_alpha_ratio": dar,
                    "dar_pvalue": _safe_float(da.get("p_value")),
                    "n_benchmarks": int(da.get("n_benchmarks", len(benchmark_list))),
                    "scenario": scenario_label,
                }
                results.append(entry)
                dar_str = "N/A" if dar is None else f"{dar:.3f}"
                print(
                    f"   {mode_label:>11} | "
                    f"{expense:>7.1%} | "
                    f"{bench_cost*10_000:>5.0f} bp | "
                    f"{entry['alpha'] or 0:>7.2%} | "
                    f"{entry['alpha_pvalue_original'] or 1:>8.4f} | "
                    f"{entry['alpha_pvalue'] or 1:>7.4f} | "
                    f"{dar_str:>6}"
                )
    return results


# ---------------------------------------------------------------------------
# Section 3: CPCV robustness under cost stress
# ---------------------------------------------------------------------------

def run_cpcv_robustness(data_df, benchmark_dfs, factory):
    """Run CPCV under low-cost and high-cost regimes and compare OOS results."""
    print("3. CPCV ROBUSTNESS UNDER COST STRESS")
    print("-" * 75)

    scenarios = {
        "low_cost": {
            "commission": 0.0, "slippage": 0.0,
            "impact_coefficient": 0.0, "borrow_cost": 0.0, "funding_cost": 0.0,
        },
        "high_cost": {
            "commission": 0.0010, "slippage": 0.0005,
            "impact_coefficient": 0.1, "borrow_cost": 0.03, "funding_cost": 0.02,
        },
    }

    results = {}
    for name, costs in scenarios.items():
        print(f"   Running CPCV ({name}) ...")
        r = cpcv_analysis(
            data=data_df,
            strategy_factory=factory,
            param_grid=CPCV_PARAM_GRID,
            n_splits=CPCV_N_SPLITS,
            test_size=0.2,
            benchmark=benchmark_dfs,
            benchmark_commission=0.0005,
            benchmark_slippage=0.0005,
            benchmark_expense_ratio=0.005,
            benchmark_cost_is_periodic=True,
            commission=costs["commission"],
            slippage=costs["slippage"],
            impact_coefficient=costs["impact_coefficient"],
            borrow_cost=costs["borrow_cost"],
            funding_cost=costs["funding_cost"],
        )
        s = r["summary"]
        da = s.get("deflated_alpha") or {}
        results[name] = {
            "total_oos_return": _safe_float(s.get("total_oos_return")),
            "oos_sharpe": _safe_float(s.get("oos_sharpe")),
            "n_folds": s.get("n_folds"),
            "overfitting_risk": s.get("overfitting_risk"),
            "deflated_alpha_ratio": _safe_float(da.get("deflated_alpha_ratio")),
            "dar_pvalue": _safe_float(da.get("p_value")),
            "n_benchmarks": int(da.get("n_benchmarks", len(benchmark_dfs))),
            "strategy_costs": {
                "commission_bps": costs["commission"] * 10_000,
                "slippage_bps": costs["slippage"] * 10_000,
                "impact_coefficient": costs["impact_coefficient"],
                "borrow_cost_annual": costs["borrow_cost"],
                "funding_cost_annual": costs["funding_cost"],
            },
        }
        ret = results[name]["total_oos_return"]
        sharpe = results[name]["oos_sharpe"]
        dar = results[name]["deflated_alpha_ratio"]
        print(f"     OOS Return:  {ret if ret is not None else 'N/A':>8.2%}")
        print(f"     OOS Sharpe:  {sharpe if sharpe is not None else 'N/A':>8.3f}")
        print(f"     DAR:         {dar if dar is not None else 'N/A':>8.3f}")
        print(f"     Overfitting: {results[name]['overfitting_risk']}")
        print()

    low, high = results["low_cost"], results["high_cost"]
    print("   Cost impact on OOS performance:")
    print(f"     Sharpe:  {low['oos_sharpe']:.3f} → {high['oos_sharpe']:.3f} "
          f"(Δ {high['oos_sharpe'] - low['oos_sharpe']:+.3f})")
    print(f"     Return:  {low['total_oos_return']:.2%} → {high['total_oos_return']:.2%} "
          f"(Δ {high['total_oos_return'] - low['total_oos_return']:+.2%})")
    print()
    return results


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    print("=" * 80)
    print("QUANTITATIVE BACKTESTING: TRADING COSTS & ROBUSTNESS SENSITIVITY ANALYSIS")
    print("=" * 80)
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # --- Generate synthetic universe ---
        strategy_df, benchmark_dfs, symbols = _make_universe()
        print(f"Generated {N_ASSETS} synthetic assets ({N_PERIODS} business days each).")
        print(f"Strategy data: {symbols[0]}")
        print(f"Benchmarks:    {symbols[1]}, {symbols[2]}")
        print()

        factory = lambda params: build_strategy("sma_crossover", json.dumps(params))

        # --- Section 1: Strategy cost sensitivity ---
        cost_sweep, baseline_returns = run_strategy_cost_sweep(strategy_df)

        # --- Section 2: Benchmark cost-model sensitivity ---
        bench_sweep = run_benchmark_cost_sweep(baseline_returns, benchmark_dfs, strategy_df)

        # --- Section 3: CPCV robustness under cost stress ---
        cpcv_results = run_cpcv_robustness(strategy_df, benchmark_dfs, factory)

        # --- Write structured JSON summary ---
        summary = {
            "metadata": {
                "description": "Trading costs & robustness sensitivity analysis",
                "data_source": "synthetic (generate_multi_asset_data)",
                "n_assets": N_ASSETS,
                "n_periods": N_PERIODS,
                "strategy": "sma_crossover",
                "strategy_params": STRATEGY_PARAMS,
                "initial_capital": INITIAL_CAPITAL,
            },
            "strategy_cost_sweep": cost_sweep,
            "benchmark_cost_sweep": bench_sweep,
            "cpcv_robustness": cpcv_results,
        }
        out_path = tmpdir / "trading_costs_sensitivity.json"
        with open(out_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        print(f"Structured results saved to: {out_path}")
        print()

        # --- Key findings ---
        print("=" * 80)
        print("KEY FINDINGS")
        print("=" * 80)
        print(f"  1. Strategy transaction costs (0→{int(cost_sweep[-1]['total_cost_bps'])} bps) "
              f"degrade Sharpe from {cost_sweep[0]['sharpe_ratio']:.3f} to "
              f"{cost_sweep[-1]['sharpe_ratio']:.3f} "
              f"(Δ {cost_sweep[-1]['sharpe_ratio'] - cost_sweep[0]['sharpe_ratio']:+.3f}).")
        print(f"  2. Benchmark cost-model choice (periodic vs round-trip, "
              f"expense ratio 0%→1%) shifts the estimated alpha and the DAR.")
        print(f"  3. CPCV OOS Sharpe: low-cost={cpcv_results['low_cost']['oos_sharpe']:.3f} "
              f"vs high-cost={cpcv_results['high_cost']['oos_sharpe']:.3f}.")
        print()
        print("  Conclusion: Transaction costs materially affect both performance")
        print("  metrics and statistical inference (deflated alpha). Sensitivity")
        print("  analysis should be a standard step in strategy validation.")
        print("=" * 80)
        print("TRADING COSTS SENSITIVITY ANALYSIS COMPLETE")
        print("=" * 80)


if __name__ == "__main__":
    main()
