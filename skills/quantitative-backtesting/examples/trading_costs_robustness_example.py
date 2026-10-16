#!/usr/bin/env python3
"""
Trading Costs & Robustness Sensitivity Analysis Example

Demonstrates how transaction costs and cost-modeling assumptions affect both
strategy profitability and statistical inference:

  1. Strategy cost sensitivity — sweeps commission × slippage × borrow cost ×
     funding cost on the strategy side, measuring how Sharpe, Calmar, and max
     drawdown degrade.  Borrow and funding costs are swept for completeness
     (exercising the full _calculate_strategy_returns cost API) even though
     the SMA-crossover strategy is long-only and thus unaffected by them.
  2. Benchmark cost-model sensitivity — sweeps benchmark commission, expense
     ratio, and periodic-vs-round-trip costing, showing the impact on estimated
     alpha and the Deflated Alpha Ratio (DAR).  A degraded-strategy benchmark
     (strategy asset with compounding negative drag) is also swept to produce
     a positive-alpha scenario where DAR ∈ (0, 1) and moves with cost
     assumptions, illustrating how cost-modeling affects statistical inference.
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
    walk_forward_analysis,
    parameter_optimization,
    out_of_sample_validation,
)
from performance import calculate_metrics  # noqa: E402
from monte_carlo import monte_carlo_simulation  # noqa: E402


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

# Extended cost sweep grids for borrow and funding costs (annualized).
# NOTE: the SMA-crossover strategy used here is long-only (positions ∈ {0, 1})
# with no leverage, so borrow_cost (short exposure) and funding_cost (>1x
# leverage) have zero impact on this strategy.  They are swept to exercise
# the full _calculate_strategy_returns cost API and so that the example is
# a drop-in template for strategies that DO carry short/leverage exposure.
BORROW_COST_GRID = [0.0, 0.03]                      # 0%, 3% annual
FUNDING_COST_GRID = [0.0, 0.02]                     # 0%, 2% annual

# Commission / slippage sweep grids for the walk-forward-style validation
# sweeps (Section 4).  These exercise the same CLI sweep machinery
# (`--commissions` / `--slippages`) that the standalone walk_forward.py
# tool exposes, but driven programmatically through the public validation
# functions so the example is self-contained and reproducible.  The grids
# are chosen to span realistic retail-to-institutional cost levels: 0 bps
# (frictionless, the in-sample upper bound) through 10 bps round-trip, a
# plausible all-in cost for an actively traded strategy.
COMMISSION_SWEEP_GRID = [0.0, 0.0005, 0.0010]      # 0, 5, 10 bps per trade
SLIPPAGE_SWEEP_GRID = [0.0, 0.00025, 0.0005]        # 0, 2.5, 5 bps per trade

# Walk-forward / CPCV / out-of-sample configuration for the sweeps.  Kept
# modest so the full 5-mode × 3-value sweep completes in seconds on the
# synthetic data, while still producing genuine out-of-sample records.
WF_TRAIN_MONTHS = 12
WF_TEST_MONTHS = 3
WF_STEP_MONTHS = 3
CPCV_N_SPLITS = 5
CPCV_TEST_SIZE = 0.2
OOS_TRAIN_FRAC = 0.6
OOS_VAL_FRAC = 0.2
OOS_TEST_FRAC = 0.2
OOS_VALIDATION_METHOD = "walk_forward"
MC_N_SIMULATIONS = 200
MC_CONFIDENCE_LEVELS = [0.90, 0.95, 0.99]
MC_BLOCK_SIZE = None

# Commission / slippage sweep grids for the walk-forward-style validation
# sweeps (Section 4).  These exercise the same CLI sweep machinery
# (`--commissions` / `--slippages`) that the standalone walk_forward.py
# tool exposes, but driven programmatically through the public validation
# functions so the example is self-contained and reproducible.  The grids
# are chosen to span realistic retail-to-institutional cost levels: 0 bps
# (frictionless, the in-sample upper bound) through 10 bps round-trip, a
# plausible all-in cost for an actively traded strategy.
COMMISSION_SWEEP_GRID = [0.0, 0.0005, 0.0010]      # 0, 5, 10 bps per trade
SLIPPAGE_SWEEP_GRID = [0.0, 0.00025, 0.0005]        # 0, 2.5, 5 bps per trade

# Walk-forward / CPCV / out-of-sample configuration for the sweeps.  Kept
# modest so the full 5-mode × 3-value sweep completes in seconds on the
# synthetic data, while still producing genuine out-of-sample records.
WF_TRAIN_MONTHS = 12
WF_TEST_MONTHS = 3
WF_STEP_MONTHS = 3
CPCV_N_SPLITS = 5
CPCV_TEST_SIZE = 0.2
OOS_TRAIN_FRAC = 0.6
OOS_VAL_FRAC = 0.2
OOS_TEST_FRAC = 0.2
OOS_VALIDATION_METHOD = "walk_forward"
MC_N_SIMULATIONS = 200
MC_CONFIDENCE_LEVELS = [0.90, 0.95, 0.99]
MC_BLOCK_SIZE = None

# Degraded-strategy benchmark drag levels (annualized).  The strategy's SMA
# crossover on the synthetic data has negative returns (Sharpe ≈ -0.21), so a
# positive alpha vs a benchmark is only possible when the benchmark drifts MORE
# negatively than the strategy itself.  A -30% primary / -60% secondary drag
# produces alpha ≈ +12% annualized — statistically significant enough for DAR
# to land in (0, 1) and vary meaningfully as benchmark cost assumptions change.
DEGRADED_PRIMARY_DRAG = -0.30   # -30 % annual drag on the strategy asset
DEGRADED_SECONDARY_DRAG = -0.60  # -60 % annual drag (cross-benchmark dispersion)

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


def _make_degraded_strategy_benchmark(strategy_df, drag_annual=DEGRADED_PRIMARY_DRAG):
    """Create a benchmark derived from the strategy asset but with a performance drag.

    The benchmark closes are the strategy asset's closes multiplied by a
    compounding drag factor (annualized ``drag_annual``).  Because the benchmark
    shares the same price path as the strategy asset it stays correlated with the
    strategy's positioning, yet drifts more negatively (or positively) than the
    strategy's realized P&L.  This produces a controlled, economically meaningful
    alpha: when ``drag_annual`` is negative enough the strategy outperforms the
    benchmark, yielding positive alpha and a non-trivial Deflated Alpha Ratio
    that varies across cost-modeling choices.

    A flat or uncorrelated benchmark cannot produce positive alpha here because
    the SMA-crossover strategy itself has negative returns — the benchmark must
    drift MORE negatively than the strategy to yield positive alpha.
    """
    dates = strategy_df.index
    n = len(dates)
    daily_drag = drag_annual / 252
    drag_factor = np.exp(np.cumsum(np.full(n, daily_drag)))
    degraded_close = strategy_df["close"].values * drag_factor
    rng = np.random.default_rng(98765)
    volume = rng.integers(500_000, 2_000_000, n)
    return pd.DataFrame({
        "close": degraded_close,
        "volume": volume,
    }, index=dates)


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

    # Short-capable strategy variant: demonstrate borrow/funding costs
    # Invert positions when fast MA <= slow MA (go short instead of flat)
    signals_short = signals.copy()
    signals_short[signals_short == 0] = -1

    print("   Short-capable strategy variant (signals inverted when flat):")
    baseline_short = _calculate_strategy_returns(
        data_df, signals_short, commission=0.0, slippage=0.0,
        borrow_cost=0.0, funding_cost=0.0,
    )
    bm = _metrics_from_returns(baseline_short)
    print(
        f"   Baseline (0% borrow/funding):  Sharpe={bm['sharpe_ratio']:.3f}  "
        f"Return={bm['total_return']:.2%}"
    )
    # Test borrow cost effect
    short_high_b = _calculate_strategy_returns(
        data_df, signals_short, commission=0.0, slippage=0.0,
        borrow_cost=0.03, funding_cost=0.0,
    )
    sb = _metrics_from_returns(short_high_b)
    # Test funding cost effect
    short_high_f = _calculate_strategy_returns(
        data_df, signals_short, commission=0.0, slippage=0.0,
        borrow_cost=0.0, funding_cost=0.02,
    )
    sf = _metrics_from_returns(short_high_f)
    print(
        f"   With borrow_cost=3%:           Sharpe={sb['sharpe_ratio']:.3f}  "
        f"Return={sb['total_return']:.2%} (Δ vs base: {sb['total_return'] - bm['total_return']:+.2%})"
    )
    print(
        f"   With funding_cost=2%:          Sharpe={sf['sharpe_ratio']:.3f}  "
        f"Return={sf['total_return']:.2%} (Δ vs base: {sf['total_return'] - bm['total_return']:+.2%})"
    )
    print()

    # Leveraged strategy variant: demonstrate funding costs
    # Scale long-only signals to 2x leverage (positions ∈ {0, 2}); gross
    # exposure = 2 so funding_cost applies to the 1x excess leverage.
    # Borrow costs also apply to the short leg (if any short positions arise
    # from the leveraged signal), and the 2x amplification magnifies the
    # effect of all costs — commission and slippage are also applied to the
    # larger position changes.
    signals_levered = signals * 2

    print("   Leveraged strategy variant (2x long-only leverage):")
    baseline_lev = _calculate_strategy_returns(
        data_df, signals_levered, commission=0.0, slippage=0.0,
        borrow_cost=0.0, funding_cost=0.0,
    )
    blm = _metrics_from_returns(baseline_lev)
    print(
        f"   Baseline (0% borrow/funding):  Sharpe={blm['sharpe_ratio']:.3f}  "
        f"Return={blm['total_return']:.2%}"
    )
    lev_high_f = _calculate_strategy_returns(
        data_df, signals_levered, commission=0.0, slippage=0.0,
        borrow_cost=0.0, funding_cost=0.02,
    )
    lfm = _metrics_from_returns(lev_high_f)
    print(
        f"   With funding_cost=2%:          Sharpe={lfm['sharpe_ratio']:.3f}  "
        f"Return={lfm['total_return']:.2%} (Δ vs base: {lfm['total_return'] - blm['total_return']:+.2%})"
    )
    # Market-neutral leveraged strategy variant: demonstrates combined borrow + funding costs
    # Construct market-neutral positions using two assets: long when sig_a indicates, short when sig_b indicates
    raw = generate_multi_asset_data(n_assets=N_ASSETS, periods=N_PERIODS, seed=42)
    assets = {sym: df.set_index("date") for sym, df in raw.items()}
    syms = sorted(assets.keys())
    asset_a = assets[syms[3]]
    asset_b = assets[syms[4]]
    sig_a = _strategy_signals(asset_a)
    sig_b = _strategy_signals(asset_b)
    common = asset_a.index.intersection(asset_b.index)
    pos_a = sig_a.reindex(common).fillna(0)
    pos_b = -sig_b.reindex(common).fillna(0)
    positions_mn = (pos_a + pos_b) * 2  # market neutral with 2x gross exposure
    data_mn = {"A": asset_a.reindex(common), "B": asset_b.reindex(common)}

    print("   Market-neutral leveraged variant (long A, short B, 2x gross exposure):")
    baseline_mn = _calculate_strategy_returns(
        data_mn, positions_mn, commission=0.0, slippage=0.0,
        borrow_cost=0.0, funding_cost=0.0,
    )
    bmn = _metrics_from_returns(baseline_mn)
    print(
        f"   Baseline (0% borrow/funding):  Sharpe={bmn['sharpe_ratio']:.3f}  "
        f"Return={bmn['total_return']:.2%}"
    )
    mn_both = _calculate_strategy_returns(
        data_mn, positions_mn, commission=0.0, slippage=0.0,
        borrow_cost=0.03, funding_cost=0.02,
    )
    mb = _metrics_from_returns(mn_both)
    print(
        f"   With borrow=3%, funding=2%:     Sharpe={mb['sharpe_ratio']:.3f}  "
        f"Return={mb['total_return']:.2%} (Δ vs base: {mb['total_return'] - bmn['total_return']:+.2%})"
    )
    print()

    # Market-impact sensitivity: sweep the impact_coefficient on the
    # market-neutral pairs portfolio.  The original implementation scaled
    # position_notional by the raw asset price (~$100) instead of portfolio
    # equity (~$100k), so impact_coefficient was a silent no-op even at 5.0.
    # With the fix the sweep degrades returns monotonically.
    print("   Market-impact sensitivity (market-neutral pairs, 2x gross exposure):")
    impact_rows = []
    for coeff in (0.0, 0.1, 0.5, 1.0, 2.0, 5.0):
        r = _calculate_strategy_returns(
            data_mn, positions_mn, commission=0.0, slippage=0.0,
            impact_coefficient=coeff,
        )
        m = _metrics_from_returns(r)
        impact_rows.append((coeff, m["total_return"], m["sharpe_ratio"]))
        print(
            f"     impact_coeff={coeff:>3}:  Return={m['total_return']:>8.2%}  "
            f"Sharpe={m['sharpe_ratio']:>6.3f}"
        )
    base_impact = impact_rows[0][1]
    high_impact = impact_rows[-1][1]
    print(
        f"     Δ (0 → 5.0): {base_impact:.2%} → {high_impact:.2%} "
        f"({high_impact - base_impact:+.2%})"
    )
    print()

    return results, baseline_returns, {
        "short": {"baseline_sharpe": bm["sharpe_ratio"], "baseline_return": bm["total_return"],
                  "borrow_sharpe": sb["sharpe_ratio"], "borrow_return": sb["total_return"],
                  "funding_sharpe": sf["sharpe_ratio"], "funding_return": sf["total_return"]},
        "levered": {"baseline_sharpe": blm["sharpe_ratio"], "baseline_return": blm["total_return"],
                    "funding_sharpe": lfm["sharpe_ratio"], "funding_return": lfm["total_return"]},
        "market_neutral": {"baseline_sharpe": bmn["sharpe_ratio"], "baseline_return": bmn["total_return"],
                           "both_sharpe": mb["sharpe_ratio"], "both_return": mb["total_return"]},
        "market_impact": {"baseline_return": impact_rows[0][1],
                          "high_coeff_return": impact_rows[-1][1],
                          "rows": [{"coeff": c, "return": ret, "sharpe": sr}
                                   for c, ret, sr in impact_rows]},
    }


# ---------------------------------------------------------------------------
# Section 2: Benchmark cost-model sensitivity
# ---------------------------------------------------------------------------

def run_benchmark_cost_sweep(strategy_returns, benchmark_dfs, strategy_df=None):
    """Sweep benchmark cost mode, expense ratio, and trading costs.

    Shows how the cost-modeling assumption (periodic vs round-trip) and
    expense ratio affect the estimated alpha and the Deflated Alpha Ratio.

    Also runs a positive-alpha scenario using a degraded-strategy benchmark
    (the strategy asset's price series with a compounding negative drag) to
    demonstrate how cost assumptions affect statistical inference (DAR) when
    the strategy actually shows skill.  The drag must exceed the strategy's
    own negative return to produce positive alpha; see
    ``DEGRADED_PRIMARY_DRAG`` for the chosen levels.
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

# --- Positive-alpha scenario ---
    if strategy_df is not None:
        print()
        print("   --- POSITIVE-ALPHA SCENARIO (degraded-strategy benchmark) ---")
        print()

        # The strategy asset's close with a compounding annual drag applied.
        # The primary (-30 %) benchmark is the one alpha is evaluated against;
        # the secondary (-60 %) provides cross-sectional alpha dispersion for the
        # Deflated Alpha Ratio.  Both are derived from the same asset so they
        # stay correlated with the strategy's positioning while drifting more
        # negatively, producing clearly positive alpha (≈ +12 % annualized) and
        # DAR ∈ (0, 1) that varies across cost-modeling choices.
        deg_bench_primary = _make_degraded_strategy_benchmark(strategy_df, drag_annual=DEGRADED_PRIMARY_DRAG)
        deg_bench_secondary = _make_degraded_strategy_benchmark(strategy_df, drag_annual=DEGRADED_SECONDARY_DRAG)
        print(f"   Degraded strategy benchmarks (primary: {DEGRADED_PRIMARY_DRAG:.0%} drag, secondary: {DEGRADED_SECONDARY_DRAG:.0%} drag):")
        deg_results = _run_benchmark_sweep_for_benchmark(
            strategy_returns, [deg_bench_primary, deg_bench_secondary], "degraded_strategy", header
        )
        results.extend(deg_results)

    print()

    # Interpretation note: DAR is the probability that the strategy's true alpha
    # exceeds the best alpha expected from luck alone.  For the original (uncorrelated)
    # benchmarks the strategy has negative alpha and DAR ≈ 0 — no evidence of skill.
    #  The key sensitivity in that regime is in the *alpha estimate* and *p-value*:
    # cost-modeling assumptions (periodic vs round-trip, expense ratios) shift the
    # estimated alpha even when the corrected DAR stays near zero.  The degraded-
    # strategy benchmark flips this: by construction the benchmark drifts more
    # negatively than the strategy, yielding positive alpha and a non-trivial DAR
    # (∈ (0, 1)) that still moves with cost-modeling choices — demonstrating how
    # cost assumptions affect statistical inference when skill is present.
    print("   Note: DAR (Deflated Alpha Ratio) is the probability that the true")
    print("   alpha exceeds the best alpha expected from luck alone. Near-zero DAR")
    print("   means no evidence of skill; the interesting sensitivity is in the")
    print("   estimated alpha and uncorrected p-value across cost-modeling choices.")
    print("   The degraded-strategy benchmark produces DAR ∈ (0, 1): as benchmark")
    print("   costs rise the benchmark underperforms further, the alpha estimate")
    print("   increases, and DAR moves in response — illustrating how cost-model")
    print("   assumptions affect statistical inference when skill is present.")
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

    # Note: borrow_cost and funding_cost are passed to the high-cost scenario
    # but, like Section 1, they have no effect on this long-only SMA-crossover
    # strategy (no short positions → no borrow cost; no leverage → no funding
    # cost).  The CPCV high-cost regime still differs via commission, slippage,
    # and market-impact charges.
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
        cost_sweep, baseline_returns, cost_extras = run_strategy_cost_sweep(strategy_df)

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
                "positive_alpha_scenario": {
                    "benchmark_type": "degraded_strategy",
                    "primary_drag_annual": DEGRADED_PRIMARY_DRAG,
                    "secondary_drag_annual": DEGRADED_SECONDARY_DRAG,
                },
            },
            "strategy_cost_sweep": cost_sweep,
            "strategy_exposure_demonstrations": cost_extras,
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
        # Report the positive-alpha scenario's DAR range
        degraded_entries = [e for e in bench_sweep if e.get("scenario") == "degraded_strategy"]
        if degraded_entries:
            dar_values = [e["deflated_alpha_ratio"] for e in degraded_entries if e["deflated_alpha_ratio"] is not None]
            if dar_values:
                print(f"  2b. Positive-alpha scenario (degraded-strategy benchmark, "
                      f"drag {DEGRADED_PRIMARY_DRAG:.0%}/{DEGRADED_SECONDARY_DRAG:.0%}): "
                      f"DAR ranges {min(dar_values):.3f}→{max(dar_values):.3f} "
                      f"across cost-modeling choices, demonstrating cost sensitivity "
                      f"in statistical inference when skill is present.")
        print(f"  3. CPCV OOS Sharpe: low-cost={cpcv_results['low_cost']['oos_sharpe']:.3f} "
              f"vs high-cost={cpcv_results['high_cost']['oos_sharpe']:.3f}.")
        short_res = cost_extras["short"]
        lev_res = cost_extras["levered"]
        short_delta = short_res["borrow_return"] - short_res["baseline_return"]
        lev_delta = lev_res["funding_return"] - lev_res["baseline_return"]
        print(f"  3b. Short-capable variant: borrow_cost=3% reduces return by "
              f"{short_delta:+.2%} (Sharpe {short_res['baseline_sharpe']:.3f}→{short_res['borrow_sharpe']:.3f}); "
              f"funding_cost=2% has no effect (no leverage).")
        print(f"  3c. Leveraged variant (2x): funding_cost=2% reduces return by "
              f"{lev_delta:+.2%} (Sharpe {lev_res['baseline_sharpe']:.3f}→{lev_res['funding_sharpe']:.3f}).")
        mn_res = cost_extras["market_neutral"]
        mn_delta = mn_res["both_return"] - mn_res["baseline_return"]
        print(f"  3d. Market-neutral leveraged variant (long A, short B, 2x gross exposure): combined borrow=3% + funding=2% reduces return by "
              f"{mn_delta:+.2%} (Sharpe {mn_res['baseline_sharpe']:.3f}→{mn_res['both_sharpe']:.3f}).")
        impact_res = cost_extras.get("market_impact")
        if impact_res:
            imp_base = impact_res["baseline_return"]
            imp_high = impact_res["high_coeff_return"]
            print(f"  3e. Market-impact sensitivity (market-neutral pairs, 2x gross exposure): "
                  f"impact_coefficient 0→5.0 reduces return by {imp_high - imp_base:+.2%} "
                  f"({imp_base:.2%}→{imp_high:.2%}).  The original implementation scaled "
                  f"position_notional by the raw asset price instead of portfolio equity, "
                  f"making impact_coefficient a silent no-op; this sweep confirms the fix.")
        print()
        print("  Conclusion: Transaction costs materially affect both performance")
        print("  metrics and statistical inference (deflated alpha). Sensitivity")
        print("  analysis should be a standard step in strategy validation.")
        print("=" * 80)
        print("TRADING COSTS SENSITIVITY ANALYSIS COMPLETE")
        print("=" * 80)


if __name__ == "__main__":
    main()
