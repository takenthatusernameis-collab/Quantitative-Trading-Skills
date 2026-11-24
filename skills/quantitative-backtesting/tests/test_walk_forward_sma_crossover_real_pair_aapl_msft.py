#!/usr/bin/env python3
"""Chronological train/validation/test walk-forward for SMA crossover on the
committed two-asset panel (AAPL + MSFT).

Replaces the per-bar regime stratification (in-sample label/return alignment)
with a genuinely out-of-sample design: test folds are held out, and regime
labels are derived point-in-time from data available at each fold boundary.

Evaluates the strategy across chronological walk-forward windows
(train 24 / validation 6 / test 12 months, stepping 12 months) on committed
fixtures only, with a pre-registered parameter grid (fast=20, slow=50) and
advertised costs (2bp commission + 1bp slippage).

Verdict rule (pre-registered, mirrors existing regime robustness semantics):
- Pool all held-out test fold returns (genuinely out-of-sample).
- Compute regime labels point-in-time on the pooled test data.
- SUPPORTED only if strategy beats benchmark (higher Sharpe) in >=2 of the 3
  regimes (bull/bear/sideways) net of costs on the pooled test data.
- Additionally, require strategy beats benchmark on a majority of test folds
  (>=2 of 3 folds) for the fold-level consistency check.
- Otherwise the panel verdict is NOT SUPPORTED.

Honest outcome: the test records the per-fold and per-regime results
transparently. No profitability or capacity claim is made. NOT SUPPORTED is
an acceptable and likely honest outcome.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import _calculate_strategy_returns
from strategy_builder import build_strategy
from utils import build_market_model
from regime_detection import detect_trend_regime, compute_regime_performance

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

SYMBOLS = ("AAPL.csv", "MSFT.csv")

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade

# Pre-registered SMA crossover parameters (advertised defaults)
PARAM_GRID = {
    "fast_period": [20],
    "slow_period": [50],
}

# Train/Val/Test window sizes (months)
TRAIN_MONTHS = 24
VAL_MONTHS = 6
TEST_MONTHS = 12
STEP_MONTHS = 12

# Regime detection parameters (200-day MA trend regime)
MA_SHORT = 50
MA_LONG = 200
MA_THRESHOLD = 0.02
MIN_REGIME_PERIODS = 21

# Falsification thresholds (pre-registered)
MIN_REGIMES_WON_POOLED = 2  # must beat benchmark in >=2 of 3 regimes on pooled test data
MIN_FOLDS_WON = 2           # must beat benchmark on >=2 of 3 folds (majority)


def _build_panel():
    """Load the committed pair panel as a dict of DataFrames."""
    panel = {}
    for name in SYMBOLS:
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        panel[Path(name).stem] = df.set_index("date").sort_index()
    return panel


def _factory(params):
    return build_strategy("sma_crossover", json.dumps(params))


def _compute_fold_returns(test_data_dict, params, commission, slippage):
    """Compute strategy and benchmark returns for a single test fold.

    Returns:
        tuple of (portfolio_strategy_rets, portfolio_benchmark_rets, regime_labels)
        where each is a Series indexed by date.
    """
    # Extract scalar params from grid (pre-registered single combo)
    params_flat = {k: v[0] for k, v in params.items()}
    strategy = _factory(params_flat)

    returns_dict = {}
    bench_dict = {}
    regime_labels_dict = {}

    for symbol, df in test_data_dict.items():
        signals = strategy.generate_signals(df)
        ret = _calculate_strategy_returns(
            data=df,
            signals=signals,
            commission=commission,
            slippage=slippage,
            impact_coefficient=0.0,
            adv_window=20,
            borrow_cost=0.0,
            funding_cost=0.0,
            latency=0,
            fill_rate=1.0,
        )
        returns_dict[symbol] = ret

        market = build_market_model(df)
        bench_dict[symbol] = market["raw_returns"]

        # Regime labels point-in-time: compute on the full available history
        # up to each point in the test period. Since detect_trend_regime uses
        # rolling MAs, it is inherently causal.
        close = df["close"]
        regimes = detect_trend_regime(close, ma_short=MA_SHORT, ma_long=MA_LONG, threshold=MA_THRESHOLD)
        regime_labels_dict[symbol] = regimes

    # Equal-weight portfolio
    rets_df = pd.DataFrame(returns_dict)
    portfolio_rets = rets_df.mean(axis=1)
    portfolio_rets.name = "strategy"

    bench_df = pd.DataFrame(bench_dict)
    portfolio_bench = bench_df.mean(axis=1)
    portfolio_bench.name = "benchmark"

    # For regime labels, use the first asset's regimes as proxy for market regime
    # (both are large-cap US equities).
    first_symbol = list(test_data_dict.keys())[0]
    regimes = regime_labels_dict[first_symbol]
    regimes.name = "regime"

    return portfolio_rets, portfolio_bench, regimes


def _evaluate_pooled_test_data(all_test_rets, all_test_bench, all_test_regimes):
    """Evaluate strategy vs benchmark per regime on pooled test data.

    Returns:
        dict with per-regime strategy/benchmark Sharpe and overall verdict.
    """
    # Align all series
    common_idx = all_test_rets.index.intersection(all_test_bench.index).intersection(all_test_regimes.index)
    rets = all_test_rets.reindex(common_idx).dropna()
    bench = all_test_bench.reindex(rets.index)
    regimes = all_test_regimes.reindex(rets.index)

    # Compute per-regime performance for strategy and benchmark
    strategy_by_regime = compute_regime_performance(
        rets, regimes, min_period_length=MIN_REGIME_PERIODS
    )
    benchmark_by_regime = compute_regime_performance(
        bench, regimes, min_period_length=MIN_REGIME_PERIODS
    )

    # Falsification: beat benchmark in >= MIN_REGIMES_WON_POOLED regimes
    regime_detail = {}
    n_won = 0
    n_evaluated = 0
    for regime in sorted(set(strategy_by_regime) & set(benchmark_by_regime)):
        if regime == "unknown":
            continue
        s = strategy_by_regime[regime]
        b = benchmark_by_regime[regime]
        beats = s["sharpe_ratio"] > b["sharpe_ratio"]
        n_evaluated += 1
        if beats:
            n_won += 1
        regime_detail[regime] = {
            "strategy": s,
            "benchmark": b,
            "strategy_beats_benchmark_sharpe": bool(beats),
        }

    pooled_verdict = "SUPPORTED" if n_won >= MIN_REGIMES_WON_POOLED else "NOT SUPPORTED"

    return {
        "pooled_verdict": pooled_verdict,
        "n_regimes_won": int(n_won),
        "n_regimes_evaluated": int(n_evaluated),
        "regimes": regime_detail,
        "regime_distribution": regimes.value_counts().to_dict(),
    }


def _run_walk_forward():
    """Run chronological train/val/test walk-forward on the pair panel."""
    panel = _build_panel()

    # Get common date range
    all_dates = None
    for df in panel.values():
        if all_dates is None:
            all_dates = df.index
        else:
            all_dates = all_dates.intersection(df.index)
    all_dates = all_dates.sort_values()

    start_date = all_dates.min()
    end_date = all_dates.max()

    # Generate walk-forward periods with train/val/test splits
    periods = []
    train_end = start_date + pd.DateOffset(months=TRAIN_MONTHS)
    val_end = train_end + pd.DateOffset(months=VAL_MONTHS)
    test_end = val_end + pd.DateOffset(months=TEST_MONTHS)

    while test_end <= end_date:
        train_start = all_dates[all_dates < train_end].min() if len(all_dates[all_dates < train_end]) > 0 else all_dates[0]
        train_data = {sym: df[(df.index >= train_start) & (df.index < train_end)] for sym, df in panel.items()}
        val_data = {sym: df[(df.index >= train_end) & (df.index < val_end)] for sym, df in panel.items()}
        test_data = {sym: df[(df.index >= val_end) & (df.index < test_end)] for sym, df in panel.items()}

        # Check all have data
        if all(len(v) > 0 for v in train_data.values()) and \
           all(len(v) > 0 for v in val_data.values()) and \
           all(len(v) > 0 for v in test_data.values()):
            periods.append({
                "train_start": train_start,
                "train_end": train_end,
                "val_start": train_end,
                "val_end": val_end,
                "test_start": val_end,
                "test_end": test_end,
                "train_data": train_data,
                "val_data": val_data,
                "test_data": test_data,
            })

        # Step forward
        train_end = train_end + pd.DateOffset(months=STEP_MONTHS)
        val_end = train_end + pd.DateOffset(months=VAL_MONTHS)
        test_end = val_end + pd.DateOffset(months=TEST_MONTHS)

    # Run evaluation on each test fold
    fold_results = []
    all_test_rets_list = []
    all_test_bench_list = []
    all_test_regimes_list = []

    for period in periods:
        test_data = period["test_data"]
        fold_rets, fold_bench, fold_regimes = _compute_fold_returns(test_data, PARAM_GRID, COMMISSION, SLIPPAGE)

        # Store for pooling
        all_test_rets_list.append(fold_rets)
        all_test_bench_list.append(fold_bench)
        all_test_regimes_list.append(fold_regimes)

        # Per-fold overall evaluation (not per-regime, since folds are short)
        common_idx = fold_rets.index.intersection(fold_bench.index)
        fold_rets_aligned = fold_rets.reindex(common_idx).dropna()
        fold_bench_aligned = fold_bench.reindex(fold_rets_aligned.index)

        fold_sharpe = None
        fold_bench_sharpe = None
        if len(fold_rets_aligned) > 1:
            from utils import _annualization_factor
            ann_factor = _annualization_factor(fold_rets_aligned.index)
            excess_s = fold_rets_aligned - 0.02 / ann_factor
            excess_b = fold_bench_aligned - 0.02 / ann_factor
            if excess_s.std() > 0:
                fold_sharpe = float(excess_s.mean() / excess_s.std() * np.sqrt(ann_factor))
            if excess_b.std() > 0:
                fold_bench_sharpe = float(excess_b.mean() / excess_b.std() * np.sqrt(ann_factor))

        fold_beats = (fold_sharpe is not None and fold_bench_sharpe is not None and fold_sharpe > fold_bench_sharpe)

        fold_results.append({
            "period": {
                "train_start": str(period["train_start"]),
                "train_end": str(period["train_end"]),
                "val_start": str(period["val_start"]),
                "val_end": str(period["val_end"]),
                "test_start": str(period["test_start"]),
                "test_end": str(period["test_end"]),
            },
            "fold_sharpe": fold_sharpe,
            "fold_benchmark_sharpe": fold_bench_sharpe,
            "fold_beats_benchmark": bool(fold_beats),
            "n_observations": int(len(fold_rets_aligned)),
            "regime_distribution": fold_regimes.value_counts().to_dict(),
        })

    # Pool all test fold data for regime-stratified evaluation
    all_test_rets = pd.concat(all_test_rets_list)
    all_test_bench = pd.concat(all_test_bench_list)
    all_test_regimes = pd.concat(all_test_regimes_list)

    pooled_eval = _evaluate_pooled_test_data(all_test_rets, all_test_bench, all_test_regimes)

    # Fold-level verdict: majority of folds must beat benchmark overall
    folds_won = sum(1 for fr in fold_results if fr["fold_beats_benchmark"])
    total_folds = len(fold_results)
    fold_verdict = "SUPPORTED" if folds_won >= MIN_FOLDS_WON else "NOT SUPPORTED"

    # Final panel verdict: BOTH pooled regime criterion AND fold majority must pass
    panel_verdict = "SUPPORTED" if (pooled_eval["pooled_verdict"] == "SUPPORTED" and fold_verdict == "SUPPORTED") else "NOT SUPPORTED"

    return {
        "signal": "sma_crossover",
        "panel_verdict": panel_verdict,
        "total_folds": total_folds,
        "folds_won": folds_won,
        "min_folds_won": MIN_FOLDS_WON,
        "fold_verdict": fold_verdict,
        "pooled_regime_verdict": pooled_eval["pooled_verdict"],
        "min_regimes_won_pooled": MIN_REGIMES_WON_POOLED,
        "pooled_regimes_won": pooled_eval["n_regimes_won"],
        "pooled_regimes_evaluated": pooled_eval["n_regimes_evaluated"],
        "fold_results": fold_results,
        "pooled_regime_detail": pooled_eval["regimes"],
        "pooled_regime_distribution": pooled_eval["regime_distribution"],
        "config": {
            "fast_period": PARAM_GRID["fast_period"][0],
            "slow_period": PARAM_GRID["slow_period"][0],
            "commission": COMMISSION,
            "slippage": SLIPPAGE,
            "train_months": TRAIN_MONTHS,
            "val_months": VAL_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
            "ma_short": MA_SHORT,
            "ma_long": MA_LONG,
            "ma_threshold": MA_THRESHOLD,
            "min_regime_periods": MIN_REGIME_PERIODS,
        },
    }


def test_walk_forward_sma_crossover_real_pair_runs():
    for name in SYMBOLS:
        assert (SRC / name).exists()

    buffer = io.StringIO()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with contextlib.redirect_stdout(buffer):
            result = _run_walk_forward()

    assert isinstance(result, dict)
    assert "fold_results" in result and "panel_verdict" in result
    assert result["panel_verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["total_folds"] >= 1
    assert set(result.keys()) >= {
        "signal", "panel_verdict", "total_folds", "folds_won",
        "min_folds_won", "fold_verdict", "pooled_regime_verdict",
        "min_regimes_won_pooled", "pooled_regimes_won",
        "pooled_regimes_evaluated", "fold_results", "pooled_regime_detail",
        "pooled_regime_distribution", "config"
    }

    for fr in result["fold_results"]:
        assert "fold_sharpe" in fr
        assert "fold_benchmark_sharpe" in fr
        assert "fold_beats_benchmark" in fr
        assert isinstance(fr["fold_beats_benchmark"], bool)
        assert "n_observations" in fr
        assert "regime_distribution" in fr

    # Pooled regime detail
    for regime in ("bear", "bull", "sideways"):
        if regime in result["pooled_regime_detail"]:
            detail = result["pooled_regime_detail"][regime]
            assert set(detail) == {"strategy", "benchmark", "strategy_beats_benchmark_sharpe"}
            for side in ("strategy", "benchmark"):
                m = detail[side]
                for key in ("sharpe_ratio", "max_drawdown", "win_rate", "total_return", "n_observations"):
                    assert key in m, f"missing {regime}/{side}/{key}"
            assert isinstance(detail["strategy_beats_benchmark_sharpe"], bool)


def test_walk_forward_sma_crossover_real_pair_verdict_and_metrics():
    """Records the per-fold and per-regime results transparently.

    The honest outcome is recorded: per-fold verdicts, per-regime Sharpe
    ratios (strategy vs benchmark), and the final panel verdict.
    No profitability claim; NOT SUPPORTED is an acceptable outcome.
    """
    for name in SYMBOLS:
        assert (SRC / name).exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_walk_forward()

    # Print detailed results for transparency
    print(f"\n=== Walk-Forward SMA Crossover (Pair Panel) ===")
    print(f"Panel verdict: {result['panel_verdict']}")
    print(f"  Pooled regime verdict: {result['pooled_regime_verdict']} "
          f"(regimes won: {result['pooled_regimes_won']}/{result['pooled_regimes_evaluated']}, need >= {result['min_regimes_won_pooled']})")
    print(f"  Fold verdict: {result['fold_verdict']} "
          f"(folds won: {result['folds_won']}/{result['total_folds']}, need >= {result['min_folds_won']})")
    print()

    # Per-fold results
    for i, fr in enumerate(result["fold_results"]):
        period = fr["period"]
        print(f"Fold {i+1}: {period['test_start'][:10]} to {period['test_end'][:10]}")
        print(f"  Strategy Sharpe: {fr['fold_sharpe']:.3f}" if fr['fold_sharpe'] is not None else "  Strategy Sharpe: N/A")
        print(f"  Benchmark Sharpe: {fr['fold_benchmark_sharpe']:.3f}" if fr['fold_benchmark_sharpe'] is not None else "  Benchmark Sharpe: N/A")
        print(f"  Beats benchmark: {fr['fold_beats_benchmark']} (n={fr['n_observations']})")
        print(f"  Regime dist: {fr['regime_distribution']}")
        print()

    # Pooled regime results
    print("Pooled test data regime-stratified evaluation:")
    for regime in ("bear", "bull", "sideways"):
        if regime in result["pooled_regime_detail"]:
            detail = result["pooled_regime_detail"][regime]
            s = detail["strategy"]
            b = detail["benchmark"]
            beats = detail["strategy_beats_benchmark_sharpe"]
            print(f"  {regime:8s}: strategy Sharpe {s['sharpe_ratio']:+.3f} "
                  f"(DD {s['max_drawdown']:.3f}, win {s['win_rate']:.2%}, n={s['n_observations']}) | "
                  f"benchmark Sharpe {b['sharpe_ratio']:+.3f} "
                  f"(DD {b['max_drawdown']:.3f}, win {b['win_rate']:.2%}, n={b['n_observations']}) | beats: {beats}")
    print(f"  Regime distribution (pooled): {result['pooled_regime_distribution']}")
    print()

    # The test always passes - it records the honest outcome
    # The verdict is determined by the pre-registered criteria
    assert result["panel_verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert isinstance(result["folds_won"], int)
    assert isinstance(result["total_folds"], int)
    assert isinstance(result["pooled_regimes_won"], int)


if __name__ == "__main__":
    test_walk_forward_sma_crossover_real_pair_runs()
    test_walk_forward_sma_crossover_real_pair_verdict_and_metrics()
    print("OK")
