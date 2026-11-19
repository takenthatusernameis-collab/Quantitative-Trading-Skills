#!/usr/bin/env python3
"""
Worked example: Probability of Backtest Overfitting (PBO via CSCV) on a
pre-registered SMA crossover parameter search over committed market data.

PBO (Bailey, Borwein, Lopez de Prado & Zhu, 2017) estimates how often the
configuration that wins in-sample ranks at or below the out-of-sample median.
It complements the Deflated Sharpe Ratio: DSR corrects *one selected*
statistic; PBO measures the *selection procedure's* generalization.

This example:
  * fixes a small parameter grid BEFORE looking at results,
  * builds one per-period return series per grid configuration over the
    committed AAPL panel (signals from `strategy_builder.SMACrossoverStrategy`,
    positions lagged by one period exactly as `run_backtest.py` does, so there
    is no look-ahead into the return being earned),
  * assembles a (T, N) return matrix and calls
    `walk_forward.pbo_cscv(panel, n_splits=8)` and `pbo_cscv(panel, n_splits=16)`,
  * prints both readings with an explicit "diagnostic, not profitability"
    note.

Nothing here is evidence about AAPL or any market: the series is a committed
historical fixture and PBO is a diagnostic of the search, not a claim of
profitability or robustness. Do not assert a "good" PBO value.
"""
import argparse
import itertools
import json
import math
import sys
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from data_loader import load_data  # noqa: E402
from strategy_builder import SMACrossoverStrategy  # noqa: E402
from walk_forward import pbo_cscv  # noqa: E402

DEFAULT_DATA = (
    SKILLS_DIR
    / "assets"
    / "example_data"
    / "real_market_data"
    / "AAPL.csv"
)

COMMISSION = 0.0002  # 2 bps per unit notional traded
SLIPPAGE = 0.0001    # 1 bps per unit notional traded

# Pre-registered, fixed before results are inspected. Small by design.
PARAM_GRID = (
    (10, 20),
    (12, 26),
    (20, 50),   # reference / advertised setting
    (20, 40),
    (8, 21),
)


def _config_name(fast, slow):
    return f"sma_f{fast}_s{slow}"


def _config_returns(data, fast, slow, commission, slippage):
    """Per-period net return series for one SMA crossover configuration.

    Signal is long (1) when fast SMA > slow SMA, flat (0) otherwise, computed
    on data available at the close of each bar. Positions are lagged by one
    period (trade next period's open) so the position earning return_t was
    decided before return_t is known -- the same point-in-time convention as
    `run_backtest.py` (`positions = signals.shift(1).fillna(0)`).

    A simple proportional cost of (commission + slippage) is charged on each
    period's notional turnover.
    """
    strategy = SMACrossoverStrategy(
        type("StrategyConfig", (), {"name": "sma_crossover", "parameters": {
            "fast_period": int(fast), "slow_period": int(slow),
        }})()
    )
    signals = strategy.generate_signals(data)
    positions = signals.shift(1).fillna(0.0)

    close = data["close"].astype(float)
    period_return = close.pct_change()

    gross = positions * period_return
    turnover = positions.diff().abs().fillna(positions.abs())
    cost = (commission + slippage) * turnover
    net = gross - cost

    return net.rename(_config_name(fast, slow))


def build_panel(data_path, grid=PARAM_GRID, commission=COMMISSION, slippage=SLIPPAGE):
    """Assemble a (T, N) return matrix, one column per grid configuration."""
    data = load_data(str(data_path))
    series = [
        _config_returns(data, fast, slow, commission, slippage)
        for fast, slow in grid
    ]
    panel = pd.concat(series, axis=1)
    # Every column is drawn from the same price panel so the index already
    # aligns; drop rows any configuration cannot price (warm-up / NaN).
    panel = panel.dropna(axis=0, how="any")
    return panel


def _fmt(v, nd=4):
    if v is None:
        return "N/A"
    try:
        return f"{float(v):.{nd}f}"
    except Exception:
        return "N/A"


def run(data_path, grid=PARAM_GRID, commission=COMMISSION, slippage=SLIPPAGE,
        n_splits_values=(8, 16)):
    panel = build_panel(data_path, grid, commission, slippage)
    n_trials = panel.shape[1]

    print("=" * 78)
    print("PROBABILITY OF BACKTEST OVERFITTING (CSCV / PBO) -- worked example")
    print("=" * 78)
    print(f"Data: {data_path}")
    print(f"Strategy: SMA crossover (long when fast SMA > slow SMA, else flat)")
    print(f"Costs: {commission*10_000:.0f}bp commission + {slippage*10_000:.0f}bp "
          f"slippage on notional turnover (simple proportional model)")
    print("Point-in-time: positions lagged one period (next bar's open); no "
          "look-ahead into the return being earned.")
    print(f"Parameter grid (pre-registered, fixed before results):")
    for fast, slow in grid:
        print(f"  {_config_name(fast, slow):<14} fast={fast} slow={slow}")
    print(f"Configurations (N): {n_trials}")
    print(f"Observations used per configuration (T): {len(panel)}")
    print("-" * 78)

    readings = []
    for n_splits in n_splits_values:
        result = pbo_cscv(panel, n_splits=n_splits, metric="sharpe")
        readings.append((n_splits, result))
        expected_partitions = math.comb(n_splits, n_splits // 2)
        print(f"\nCSCV / PBO reading  n_splits={n_splits}")
        print(f"  n_partitions        = {result['n_partitions']} "
              f"(expected C({n_splits},{n_splits//2}) = {expected_partitions})")
        print(f"  n_partitions_evaluated = {result['n_partitions_evaluated']}")
        print(f"  n_trials            = {result['n_trials']}")
        print(f"  n_observations      = {result['n_observations']}")
        print(f"  PBO                 = {_fmt(result['pbo'])}  "
              f"(fraction of partitions where the in-sample winner ranks at or "
              f"below the out-of-sample median)")
        print(f"  is_overfit          = {result['is_overfit']}  (pbo > 0.5)")
        print(f"  mean_logit          = {_fmt(result['mean_logit'])}")
        print(f"  mean_oos_rank       = {_fmt(result['mean_oos_rank'])}  "
              f"(1 = worst, n_ranked = best; level diagnostic)")

    print("\n" + "=" * 78)
    print("READING (diagnostic, NOT a profitability or robustness claim):")
    print("  PBO is a share in [0, 1]. A low PBO is evidence that the selection")
    print("  procedure generalizes; a high PBO is evidence the winning configuration")
    print("  is a product of the search. PBO says nothing about the sign or size of")
    print("  the out-of-sample edge. No claim is made about AAPL or any market.")
    print("=" * 78)

    return {
        "data": str(data_path),
        "grid": [{"fast": int(f), "slow": int(s), "name": _config_name(f, s)}
                 for f, s in grid],
        "commission": commission,
        "slippage": slippage,
        "n_trials": n_trials,
        "n_observations": int(len(panel)),
        "readings": [
            {
                "n_splits": n_splits,
                "pbo": result["pbo"],
                "is_overfit": result["is_overfit"],
                "n_partitions": result["n_partitions"],
                "n_partitions_evaluated": result["n_partitions_evaluated"],
                "n_trials": result["n_trials"],
                "n_observations": result["n_observations"],
                "mean_logit": result["mean_logit"],
                "mean_oos_rank": result["mean_oos_rank"],
            }
            for n_splits, result in readings
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PBO/CSCV worked example on a pre-registered SMA grid.")
    parser.add_argument("--data", type=str, default=str(DEFAULT_DATA),
                        help="Path to the single-symbol CSV (default: committed AAPL).")
    parser.add_argument("--output-json", type=str, default=None,
                        help="Write the readings to a JSON file.")
    parser.add_argument("--n-splits", type=int, nargs="+", default=[8, 16],
                        help="CSCV split counts (even integers >= 4).")
    args = parser.parse_args()

    result = run(
        args.data,
        n_splits_values=tuple(args.n_splits),
    )
    if args.output_json:
        out_path = Path(args.output_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2, default=str))
        print(f"\nReadings written to {out_path}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
