#!/usr/bin/env python3
"""
Probability of Backtest Overfitting (PBO / CSCV) worked example.

This example demonstrates the Bailey–Borwein–López de Prado–Zhu (2017)
Combinatorially Symmetric Cross-Validation on a pre-registered SMA Crossover
parameter grid using the committed AAPL.csv fixture.

The PBO measures how often the configuration that wins in-sample ranks at or
below the out-of-sample median across all symmetric C(S, S/2) partitions.
It is a DIAGNOSTIC on the *selection procedure*, not a profitability claim:
a low PBO means the procedure generalizes; a high PBO means the winner is
likely a product of the search. PBO says nothing about the sign or magnitude
of the out-of-sample edge.

Methodology:
- Uses the committed AAPL.csv price panel (offline, no live data).
- Pre-registered parameter grid (fixed before looking at results).
- Generates one return series per grid configuration over the full price panel,
  net of per-side costs of 3 bps (2 bps commission + 1 bps slippage), i.e. a
  6 bps flat-to-flat round trip, respecting
  the point-in-time convention (trade at next period's open, 1-bar latency).
- Assembles a (T, N) return matrix and computes PBO with n_splits=8 and n_splits=16.
- Reports PBO, mean_oos_rank, mean_logit, and n_partitions for both settings.

Nothing here is evidence about any security or market: the series is a
committed historical fixture, and the PBO reading is a diagnostic on the
selection procedure, not a profitability or strategy claim.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILLS_DIR / "scripts"
ASSETS_DIR = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

sys.path.insert(0, str(SCRIPTS_DIR))

from strategy_builder import SMACrossoverStrategy, StrategyConfig
from walk_forward import pbo_cscv, _calculate_strategy_returns
from utils import build_market_model

# Pre-registered SMA Crossover parameter grid (fixed before looking at results).
# Each tuple: (fast_period, slow_period)
PARAM_GRID = [
    (5, 20),
    (8, 21),
    (10, 30),
    (12, 26),
    (12, 50),
    (15, 30),
    (16, 34),
    (20, 50),
    (20, 60),
    (25, 50),
]

# Trading costs: 3 bps round-trip (2 bps commission + 1 bps slippage)
COMMISSION = 0.0002
SLIPPAGE = 0.0001

DATA_FILE = ASSETS_DIR / "AAPL.csv"


def generate_return_series_for_grid(data: pd.DataFrame, param_grid: list) -> pd.DataFrame:
    """
    Generate one return series per parameter configuration in the grid.

    Returns a (T, N) DataFrame where columns are parameter configs and
    rows are daily returns (net of costs, with 1-bar latency).
    """
    # Build market model once for cost calculations
    market = build_market_model(data)
    raw_returns = market["raw_returns"]
    close = market["close"]
    volume = market["volume"]
    is_panel = market["is_panel"]

    return_series_list = []
    column_names = []

    for fast, slow in param_grid:
        # Build strategy
        config = StrategyConfig(
            name="sma_crossover",
            parameters={"fast_period": fast, "slow_period": slow}
        )
        strategy = SMACrossoverStrategy(config)

        # Generate signals on full data
        signals = strategy.generate_signals(data)

        # Compute returns net of costs (using the shared _calculate_strategy_returns)
        test_returns = _calculate_strategy_returns(
            data=data,
            signals=signals,
            commission=COMMISSION,
            slippage=SLIPPAGE,
            impact_coefficient=0.0,  # no market impact
            adv_window=20,
            borrow_cost=0.0,
            funding_cost=0.0,
            latency=0,  # default 1-bar latency applied inside (shift(1))
            fill_rate=1.0,
            initial_capital=100000.0,
            panel_pricing="net-exposure",
            book_weights=None,
            impact_aggregation="panel",
            impact_model="linear",
            regime_impact_coefficients=None,
            regime_cost_multipliers=None,
            max_impact=None,
        )

        # The function returns a Series indexed by date; align all to common index
        return_series_list.append(test_returns)
        column_names.append(f"fast={fast},slow={slow}")

    # Concatenate all series into a (T, N) DataFrame, aligning on common index
    panel = pd.concat(return_series_list, axis=1)
    panel.columns = column_names

    # Drop rows where any column is NaN (PBO function will also drop NaN rows)
    panel = panel.dropna(axis=0, how="any")

    return panel


def main():
    print("=" * 80)
    print("PROBABILITY OF BACKTEST OVERFITTING (CSCV / PBO) — WORKED EXAMPLE")
    print("=" * 80)
    print("Reference: Bailey, Borwein, López de Prado & Zhu (2017)")
    print("Method: Combinatorially Symmetric Cross-Validation")
    print()
    print("IMPORTANT: PBO is a DIAGNOSTIC on the parameter selection procedure,")
    print("           NOT a profitability or strategy claim.")
    print("           A low PBO means the procedure generalizes; a high PBO means")
    print("           the winning configuration is likely a product of the search.")
    print("           PBO says nothing about the sign or magnitude of OOS edge.")
    print("=" * 80)

    # Load committed AAPL data
    print(f"\nLoading data from: {DATA_FILE}")
    data = pd.read_csv(DATA_FILE, parse_dates=["date"], index_col="date")
    print(f"Data shape: {data.shape}")
    print(f"Date range: {data.index[0]} to {data.index[-1]}")

    # Define pre-registered parameter grid
    print(f"\nPre-registered parameter grid ({len(PARAM_GRID)} configurations):")
    for fast, slow in PARAM_GRID:
        print(f"  fast={fast:2d}, slow={slow:2d}")

    # Generate return series for each configuration
    print("\nGenerating return series for each configuration (net of 3 bps costs)...")
    return_panel = generate_return_series_for_grid(data, PARAM_GRID)
    print(f"Return panel shape (T, N): {return_panel.shape}")
    print(f"Date range after alignment: {return_panel.index[0]} to {return_panel.index[-1]}")

    # Compute PBO for n_splits=8 and n_splits=16
    print("\n" + "=" * 80)
    print("PBO / CSCV RESULTS")
    print("=" * 80)

    for n_splits in [8, 16]:
        print(f"\n--- n_splits = {n_splits} ---")
        result = pbo_cscv(return_panel, n_splits=n_splits, metric="sharpe")

        print(f"  n_trials (configurations):     {result['n_trials']}")
        print(f"  n_observations (rows used):    {result['n_observations']}")
        print(f"  n_splits (S):                  {result['n_splits']}")
        print(f"  n_partitions (C(S, S/2)):      {result['n_partitions']}")
        print(f"  n_partitions_evaluated:        {result['n_partitions_evaluated']}")
        print(f"  PBO (probability of overfit):  {result['pbo']:.4f}")
        print(f"  is_overfit (PBO > 0.5):        {result['is_overfit']}")
        print(f"  mean_logit:                    {result['mean_logit']:.4f}")
        print(f"  mean_oos_rank (1=worst):       {result['mean_oos_rank']:.4f}")

        if result['logits']:
            logits_str = ", ".join(f"{lam:.3f}" for lam in result['logits'][:10])
            if len(result['logits']) > 10:
                logits_str += f", ... ({len(result['logits'])} total)"
            print(f"  logits (first 10):             [{logits_str}]")

    print("\n" + "=" * 80)
    print("INTERPRETATION")
    print("=" * 80)
    print("""
PBO (Probability of Backtest Overfitting) interpretation:
- PBO ≈ 0.0: The in-sample winner consistently ranks well out-of-sample.
             The selection procedure generalizes (low overfitting risk).
- PBO ≈ 0.5: The in-sample winner ranks randomly out-of-sample.
             No evidence the procedure generalizes.
- PBO ≈ 1.0: The in-sample winner consistently ranks poorly out-of-sample.
             Strong evidence the selection procedure overfits.

mean_oos_rank: Mean relative rank of the in-sample winner out-of-sample.
- 1.0 = best out-of-sample, 0.0 = worst out-of-sample.
- Complements the share-based PBO with a level diagnostic.

mean_logit: Mean of log(omega / (1 - omega)) where omega is the relative rank.
- Positive mean_logit → in-sample winners tend to rank well OOS.
- Negative mean_logit → in-sample winners tend to rank poorly OOS.

NOTE: These are diagnostic readings on a committed fixture with a small,
      pre-registered grid. They do not constitute evidence about AAPL,
      the SMA Crossover strategy, or any market. The grid size (N=10) and
      data length limit the statistical power of CSCV.
""")
    print("=" * 80)
    print("DIAGNOSTIC ONLY — NOT A PROFITABILITY CLAIM")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())