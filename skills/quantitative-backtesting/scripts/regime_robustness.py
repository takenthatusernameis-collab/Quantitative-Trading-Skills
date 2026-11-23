#!/usr/bin/env python3
"""
Regime-robustness analysis for a single-asset signal on committed fixtures.

Stratifies walk-forward-style out-of-sample (per-bar) strategy returns by
market regime and compares the signal to a buy-and-hold benchmark *within
each regime*, net of realistic transaction costs.

Design points (see AGENTS.md quantitative-research mission):
  * Regime labels are computed point-in-time (causal): the 200-day
    moving-average trend regime at bar t uses only closes up to and
    including bar t (`regime_detection.detect_trend_regime`). No look-ahead.
  * Strategy returns are computed per bar net of commission + slippage via
    `walk_forward._calculate_strategy_returns`, with positions delayed by
    one bar (trade at next period's open, the look-ahead-safe convention).
  * Benchmark = buy-and-hold raw returns of the asset, stratified by the
    same regimes.
  * Falsification criterion (pre-registered): the signal must beat the
    benchmark (higher Sharpe ratio) in at least 2 of the 3 bull/bear/
    sideways regimes net of costs. Otherwise the verdict is NOT SUPPORTED.
    No profitability or capacity claim is made.

Offline, committed fixtures only; no live network.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
if str(SKILLS_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from regime_detection import compute_regime_performance, detect_trend_regime
from strategy_builder import build_strategy
from utils import build_market_model
from walk_forward import _calculate_strategy_returns

# Pre-registered, advertised SMA crossover defaults (matches the walk-forward
# and CPCV SMA crossover guards). Fixed before any result is inspected.
DEFAULT_FAST_PERIOD = 20
DEFAULT_SLOW_PERIOD = 50

# Realistic round-trip transaction costs (2 bps commission + 1 bps slippage
# per trade), consistent with the committed fixtures and cost_models.md.
DEFAULT_COMMISSION = 0.0002
DEFAULT_SLIPPAGE = 0.0001

# 200-day moving-average trend regime (bull / bear / sideways).
DEFAULT_MA_SHORT = 50
DEFAULT_MA_LONG = 200
DEFAULT_MA_THRESHOLD = 0.02

# Minimum observations required for a regime to be evaluable.
DEFAULT_MIN_REGIME_PERIODS = 21

# Falsification threshold: signal must beat the benchmark in >= this many
# regimes (out of the 3 bull/bear/sideways regimes) to be SUPPORTED.
DEFAULT_MIN_REGIMES_WON = 2


def _load_panel(data_path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(data_path)
    if "date" not in df.columns:
        raise ValueError(f"{data_path} must contain a 'date' column")
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            raise ValueError(f"{data_path} must contain a '{col}' column")
    return df


def _regime_labels(close: pd.Series, ma_short: int, ma_long: int, threshold: float) -> pd.Series:
    """Point-in-time bull/bear/sideways labels from the 200-day MA regime.

    Causal by construction: rolling means use only bars up to and including
    the current bar, so the label known at trade time is the label applied.
    """
    return detect_trend_regime(close, ma_short=ma_short, ma_long=ma_long, threshold=threshold)


def run_regime_robustness_analysis(
    data_path: str | Path,
    label: str = "AAPL",
    benchmark_path: str | Path | None = None,
    fast_period: int = DEFAULT_FAST_PERIOD,
    slow_period: int = DEFAULT_SLOW_PERIOD,
    commission: float = DEFAULT_COMMISSION,
    slippage: float = DEFAULT_SLIPPAGE,
    ma_short: int = DEFAULT_MA_SHORT,
    ma_long: int = DEFAULT_MA_LONG,
    threshold: float = DEFAULT_MA_THRESHOLD,
    min_regime_periods: int = DEFAULT_MIN_REGIME_PERIODS,
    min_regimes_won: int = DEFAULT_MIN_REGIMES_WON,
) -> dict:
    """
    Run a regime-stratified robustness analysis of the SMA crossover signal.

    Returns a dict with per-regime strategy vs benchmark metrics (Sharpe,
    max drawdown, win rate, total return, n observations), an overall
    summary, the number of regimes won, and a falsification verdict
    (SUPPORTED / NOT SUPPORTED).
    """
    data_path = Path(data_path)
    assert data_path.exists(), f"fixture not found: {data_path}"

    df = _load_panel(data_path)
    close = df["close"]

    # --- Point-in-time signals (long/flat SMA crossover) -------------------
    strategy = build_strategy(
        "sma_crossover",
        json.dumps({"fast_period": fast_period, "slow_period": slow_period}),
    )
    signals = strategy.generate_signals(df)

    # --- Per-bar strategy returns net of commission + slippage -------------
    # Positions are delayed by one bar (trade at next period's open), the
    # look-ahead-safe convention used throughout the framework.
    strategy_returns = _calculate_strategy_returns(
        data=df,
        signals=signals,
        commission=commission,
        slippage=slippage,
        impact_coefficient=0.0,
        borrow_cost=0.0,
        funding_cost=0.0,
        latency=0,
        fill_rate=1.0,
    )

    # --- Regime labels (causal; same labels for signal and benchmark) ------
    regimes = _regime_labels(close, ma_short=ma_short, ma_long=ma_long, threshold=threshold)

    # --- Benchmark = buy-and-hold raw returns ------------------------------
    market = build_market_model(df)
    raw_returns = market["raw_returns"]

    # --- Align all series on a common index --------------------------------
    common_idx = strategy_returns.index.intersection(regimes.index).intersection(raw_returns.index)
    sr = strategy_returns.reindex(common_idx).dropna()
    rg = regimes.reindex(sr.index)
    br = raw_returns.reindex(sr.index)

    # --- Per-regime performance for signal and benchmark -------------------
    strategy_by_regime = compute_regime_performance(
        sr, rg, min_period_length=min_regime_periods
    )
    benchmark_by_regime = compute_regime_performance(
        br, rg, min_period_length=min_regime_periods
    )

    # --- Falsification: beat benchmark in >= min_regimes_won regimes -------
    regime_detail = {}
    n_won = 0
    n_evaluated = 0
    for regime in sorted(set(strategy_by_regime) & set(benchmark_by_regime)):
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

    verdict = "SUPPORTED" if n_won >= min_regimes_won else "NOT SUPPORTED"

    # --- Overall (un-stratified) metrics for context -----------------------
    overall_strategy = compute_regime_performance(
        sr, pd.Series(["all"] * len(sr), index=sr.index), min_period_length=1
    ).get("all", {})
    overall_benchmark = compute_regime_performance(
        br, pd.Series(["all"] * len(br), index=br.index), min_period_length=1
    ).get("all", {})

    return {
        "label": label,
        "signal": "sma_crossover",
        "regime_labels": "200-day moving-average trend (bull/bear/sideways)",
        "verdict": verdict,
        "n_regimes_won": int(n_won),
        "n_regimes_evaluated": int(n_evaluated),
        "min_regimes_won": int(min_regimes_won),
        "n_regimes_total": 3,
        "criterion": (
            "signal Sharpe ratio > benchmark Sharpe ratio in "
            f">={min_regimes_won} of 3 regimes, net of costs"
        ),
        "regimes": regime_detail,
        "overall": {
            "strategy": overall_strategy,
            "benchmark": overall_benchmark,
        },
        "config": {
            "fast_period": fast_period,
            "slow_period": slow_period,
            "commission": commission,
            "slippage": slippage,
            "ma_short": ma_short,
            "ma_long": ma_long,
            "threshold": threshold,
            "min_regime_periods": min_regime_periods,
        },
    }


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Regime-robustness analysis for the SMA crossover signal."
    )
    parser.add_argument("data_path", help="Path to a committed OHLCV CSV fixture")
    parser.add_argument("--label", default="AAPL")
    args = parser.parse_args(argv)

    result = run_regime_robustness_analysis(args.data_path, label=args.label)
    print(f"Regime-robustness ({result['signal']}, {result['label']}):")
    print(f"  verdict: {result['verdict']}")
    print(f"  regimes won: {result['n_regimes_won']} / {result['n_regimes_evaluated']} "
          f"(need >= {result['min_regimes_won']} of 3)")
    for regime, detail in result["regimes"].items():
        s = detail["strategy"]
        b = detail["benchmark"]
        print(
            f"  {regime}: strategy Sharpe {s['sharpe_ratio']:+.3f} "
            f"(DD {s['max_drawdown']:.3f}, win {s['win_rate']:.2%}, n={s['n_observations']}) | "
            f"benchmark Sharpe {b['sharpe_ratio']:+.3f} "
            f"(DD {b['max_drawdown']:.3f}, win {b['win_rate']:.2%}, n={b['n_observations']}) | "
            f"beats benchmark: {detail['strategy_beats_benchmark_sharpe']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
