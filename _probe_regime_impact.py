#!/usr/bin/env python3
"""Probe regime-aware sqrt impact closed forms for both panel and book paths."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path("skills/quantitative-backtesting")
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from utils import market_impact_cost, book_market_impact_cost

periods = 6
dates = pd.date_range("2020-01-01", periods=periods, freq="B")
symbols = ["AAA", "BBB", "CCC"]
close = pd.DataFrame(
    {sym: np.full(periods, px) for sym, px in zip(symbols, [100.0, 200.0, 50.0])},
    index=dates,
)
volume = pd.DataFrame(
    {sym: np.full(periods, vol) for sym, vol in zip(symbols, [1_000_000.0, 2_000_000.0, 500_000.0])},
    index=dates,
)
raw_returns = pd.Series(np.zeros(periods), index=dates)
position_changes = pd.Series([0.0, 1.0, 0.0, 0.5, 0.0, 1.0], index=dates)
coefficient = 0.5
initial_capital = 100_000.0
adv_window = 20

# Regime labels: alternate between two known regimes so the per-period
# coefficient differs from the flat coefficient.
regimes = pd.Series(["high_vol", "low_vol", "high_vol", "high_vol", "low_vol", "low_vol"], index=dates)
regime_coeffs = {"high_vol": 1.0, "low_vol": 0.1}

print("=== PANEL sqrt, default aggregation, regime-aware ===")
res = market_impact_cost(
    position_changes, raw_returns, close, volume,
    is_panel=True, impact_coefficient=coefficient,
    adv_window=adv_window, initial_capital=initial_capital,
    impact_model="sqrt", regimes=regimes,
    regime_impact_coefficients=regime_coeffs,
)
print("result:", res.values)

# Closed form: mean_i( period_coeff * sqrt(per_asset_notional_i / ADV_i) )
n_assets = len(symbols)
equity = initial_capital * (1 + raw_returns).cumprod()
per_asset_notional = (position_changes * equity) / n_assets
adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
participation = per_asset_notional.values[:, None] / adv_notional.values
period_coeff = regimes.map(regime_coeffs).fillna(coefficient).values
expected = (period_coeff[:, None] * np.sqrt(participation)).mean(axis=1)
print("expected:", expected)
print("match:", np.allclose(res.values, expected, atol=1e-12))

print("\n=== PANEL sqrt, notional-weighted, regime-aware ===")
res_nw = market_impact_cost(
    position_changes, raw_returns, close, volume,
    is_panel=True, impact_coefficient=coefficient,
    adv_window=adv_window, initial_capital=initial_capital,
    impact_model="sqrt", impact_aggregation="notional-weighted",
    regimes=regimes, regime_impact_coefficients=regime_coeffs,
)
print("result:", res_nw.values)
expected_nw = (period_coeff[:, None] * np.sqrt(participation) * per_asset_notional.values[:, None] / equity.values[:, None]).sum(axis=1)
print("expected:", expected_nw)
print("match:", np.allclose(res_nw.values, expected_nw, atol=1e-12))

print("\n=== BOOK sqrt, default aggregation, regime-aware ===")
held_book = pd.DataFrame(
    {
        "AAA": [0.5, 0.5, 0.5, -0.5, -0.5, 0.5],
        "BBB": [-0.5, -0.5, -0.5, 0.5, 0.5, -0.5],
        "CCC": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    },
    index=dates,
)
res_b = book_market_impact_cost(
    held_book=held_book, raw_returns=raw_returns, close=close,
    volume=volume, impact_coefficient=coefficient,
    adv_window=adv_window, initial_capital=initial_capital,
    impact_model="sqrt", regimes=regimes,
    regime_impact_coefficients=regime_coeffs,
)
print("result:", res_b.values)
traded_weight = held_book.diff().abs()
traded_notional = traded_weight.mul(equity, axis=0)
participation_b = traded_notional.values / adv_notional.values
expected_b = (period_coeff[:, None] * np.sqrt(participation_b)).mean(axis=1)
print("expected:", expected_b)
print("match:", np.allclose(res_b.values, expected_b, atol=1e-12))

print("\n=== BOOK sqrt, notional-weighted, regime-aware ===")
res_b_nw = book_market_impact_cost(
    held_book=held_book, raw_returns=raw_returns, close=close,
    volume=volume, impact_coefficient=coefficient,
    adv_window=adv_window, initial_capital=initial_capital,
    impact_model="sqrt", impact_aggregation="notional-weighted",
    regimes=regimes, regime_impact_coefficients=regime_coeffs,
)
print("result:", res_b_nw.values)
expected_b_nw = (period_coeff[:, None] * np.sqrt(participation_b) * traded_weight.fillna(0.0).values).sum(axis=1)
print("expected:", expected_b_nw)
print("match:", np.allclose(res_b_nw.values, expected_b_nw, atol=1e-12))

print("\n=== SINGLE-ASSET sqrt, default aggregation, regime-aware ===")
res_s = market_impact_cost(
    position_changes, raw_returns, close["AAA"], volume["AAA"],
    is_panel=False, impact_coefficient=coefficient,
    adv_window=adv_window, initial_capital=initial_capital,
    impact_model="sqrt", regimes=regimes,
    regime_impact_coefficients=regime_coeffs,
)
print("result:", res_s.values)
adv_notional_s = volume["AAA"].rolling(window=adv_window, min_periods=1).mean() * close["AAA"]
participation_s = (position_changes * equity) / adv_notional_s
expected_s = period_coeff * np.sqrt(participation_s)
print("expected:", expected_s.values)
print("match:", np.allclose(res_s.values, expected_s.values, atol=1e-12))

print("\n=== SINGLE-ASSET sqrt, notional-weighted, regime-aware ===")
res_s_nw = market_impact_cost(
    position_changes, raw_returns, close["AAA"], volume["AAA"],
    is_panel=False, impact_coefficient=coefficient,
    adv_window=adv_window, initial_capital=initial_capital,
    impact_model="sqrt", impact_aggregation="notional-weighted",
    regimes=regimes, regime_impact_coefficients=regime_coeffs,
)
print("result:", res_s_nw.values)
expected_s_nw = period_coeff * np.sqrt(participation_s) * position_changes
print("expected:", expected_s_nw.values)
print("match:", np.allclose(res_s_nw.values, expected_s_nw.values, atol=1e-12))