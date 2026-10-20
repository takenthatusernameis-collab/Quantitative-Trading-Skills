#!/usr/bin/env python3
"""Pairs Trading (Z-Score Mean Reversion) Example.

Demonstrates statistical arbitrage pairs trading using the
MeanReversionZScore strategy from the quantitative-backtesting skill.
Shows spread construction, z-score signals, realistic costs, and
performance evaluation on correlated assets.

Key concepts:
- Spread construction (log ratio vs price ratio)
- Rolling z-score for entry/exit signals
- Pairs trading mechanics (long spread / short spread)
- Transaction costs and slippage
- Performance attribution for market-neutral strategies
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Add scripts directory to path
scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from data_loader import load_data, validate_data
from strategy_builder import build_strategy
from run_backtest import run_backtest
from performance import calculate_metrics, generate_report
from reporting import generate_tear_sheet


def generate_correlated_pair(
    n_days=756,
    seed=42,
    correlation=0.85,
    cointegrated=True
):
    """Generate two correlated price series suitable for pairs trading.

    If cointegrated=True, creates prices that share a common trend
    (good for pairs trading). Otherwise generates independent random walks.
    """
    np.random.seed(seed)

    dates = pd.date_range(start="2020-01-01", periods=n_days, freq="B")

    if cointegrated:
        # Common stochastic trend
        common_trend = np.cumsum(np.random.randn(n_days) * 0.001 + 0.0002)
        # Asset 1
        noise1 = np.random.randn(n_days) * 0.008
        log_p1 = 100 + common_trend * 1.0 + noise1
        # Asset 2 with different beta to common trend
        beta = 1.2
        noise2 = np.random.randn(n_days) * 0.006
        log_p2 = 95 + common_trend * beta + noise2 * (1 - correlation)

        p1 = np.exp(log_p1)
        p2 = np.exp(log_p2)
    else:
        # Independent random walks
        returns1 = np.random.randn(n_days) * 0.01
        returns2 = np.random.randn(n_days) * 0.01
        p1 = 100 * np.exp(np.cumsum(returns1))
        p2 = 100 * np.exp(np.cumsum(returns2))

    # Generate OHLCV
    def make_ohlcv(prices):
        df = pd.DataFrame(index=dates)
        df['close'] = prices
        df['open'] = prices * (1 + np.random.randn(n_days) * 0.002)
        df['high'] = df[['open', 'close']].max(axis=1) * (1 + np.abs(np.random.randn(n_days)) * 0.003)
        df['low'] = df[['open', 'close']].min(axis=1) * (1 - np.abs(np.random.randn(n_days)) * 0.003)
        df['volume'] = np.random.randint(100000, 1000000, n_days)
        return df

    df1 = make_ohlcv(p1)
    df2 = make_ohlcv(p2)

    return df1, df2


def main():
    print("=" * 80)
    print("PAIRS TRADING EXAMPLE - Z-SCORE MEAN REVERSION")
    print("=" * 80)
    print()

    # Generate correlated pair (simulating two stocks like KO/PEP)
    print("1. Generating correlated pair data...")
    df1, df2 = generate_correlated_pair(n_days=756, seed=123, correlation=0.9)
    print(f"   Asset A: {len(df1)} days, price range ${df1['close'].min():.2f} - ${df1['close'].max():.2f}")
    print(f"   Asset B: {len(df2)} days, price range ${df2['close'].min():.2f} - ${df2['close'].max():.2f}")

    # Check correlation
    corr = df1['close'].corr(df2['close'])
    print(f"   Correlation: {corr:.3f}")
    print()

    # Prepare panel data for pairs trading (dict format)
    pair_data = {
        "ASSET_A": df1,
        "ASSET_B": df2
    }

    # Validate data
    print("2. Validating data quality...")
    val1 = validate_data(df1)
    val2 = validate_data(df2)
    print(f"   Asset A valid: {val1}")
    print(f"   Asset B valid: {val2}")
    print()

    # Create pairs trading strategy
    print("3. Building pairs trading strategy (Z-Score Mean Reversion)...")
    strategy = build_strategy(
        "zscore_mean_reversion",
        json.dumps({
            "period": 20,           # Lookback for z-score calculation
            "entry_z": 2.0,         # Entry threshold
            "exit_z": 0.5,          # Exit threshold
            "spread_method": "log_ratio",  # Use log prices (more stable)
            "hedge_ratio": 1.0,     # Equal dollar neutral
        })
    )
    print(f"   Strategy: {strategy.name}")
    print(f"   Parameters: {strategy.parameters}")
    print()

    # Run backtest with realistic costs
    print("4. Running backtest with transaction costs...")
    print("   Commission: 2 bps, Slippage: 1 bp")
    results = run_backtest(
        data=pair_data,
        strategy=strategy,
        args=type('Args', (), {
            'strategy': strategy.name,
            'symbol': 'ASSET_A',
            'commission': 0.0002,
            'slippage': 0.0001,
            'impact_coefficient': 0.0,
            'borrow_cost': 0.0,
            'funding_cost': 0.0,
            'fill_rate': 1.0,
            'latency': 0,
            'initial_capital': 100000,
            'risk_free_rate': None,
            'n_trials': None,
            'multi_symbol': False,
            'validate_point_in_time': False,
            'point_in_time_strict': False,
            'panel_pricing': 'net-exposure',
            'impact_aggregation': 'panel',
            'adv_window': 20,
        })(),
    )
    print()

    # Display results
    print("5. Performance Results:")
    print("-" * 80)
    metrics = calculate_metrics(results)
    print(f"   Total Return: {metrics.get('total_return', 0):.2%}")
    print(f"   Annualized Return: {metrics.get('annualized_return', 0):.2%}")
    print(f"   Sharpe Ratio: {metrics.get('sharpe_ratio', 0):.3f}")
    print(f"   Sortino Ratio: {metrics.get('sortino_ratio', 0):.3f}")
    print(f"   Max Drawdown: {metrics.get('max_drawdown', 0):.2%}")
    print(f"   Calmar Ratio: {metrics.get('calmar_ratio', 0):.3f}")
    print(f"   Volatility (ann.): {metrics.get('volatility', 0):.2%}")
    print(f"   Win Rate: {metrics.get('win_rate', 0):.2%}")
    print(f"   Profit Factor: {metrics.get('profit_factor', 0):.3f}")
    print(f"   Total Trades: {metrics.get('total_trades', 0)}")
    print()

    # Save outputs
    output_dir = Path(__file__).parent / "example_output" / "pairs_trading"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save metrics
    with open(output_dir / "metrics.json", 'w') as f:
        json.dump(metrics, f, indent=2)

    # Generate report
    report_path = output_dir / "report.txt"
    generate_report({**results, "metrics": metrics}, str(report_path))
    print(f"6. Report saved to: {report_path}")

    # Generate tear sheet if possible
    try:
        generate_tear_sheet(
            {**results, "metrics": metrics},
            metrics,
            output_dir,
            symbol="PAIR",
            strategy_name="zscore_mean_reversion",
        )
        print(f"   Tear sheet saved to: {output_dir}")
    except Exception as e:
        print(f"   Tear sheet skipped: {e}")

    print()
    print("=" * 80)
    print("Pairs trading example complete!")
    print("=" * 80)

    return results


if __name__ == "__main__":
    main()
