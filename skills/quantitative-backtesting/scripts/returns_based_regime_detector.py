#!/usr/bin/env python3
"""
Returns-Based Regime Detector for fat_tail_crash.

Detects 'bear_high' from cumulative negative returns (drawdown) instead of
volatility quantiles, reusing detect_combined_regime for other regimes.
"""

import json
import sys
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from generate_adversarial_scenarios import ScenarioConfig, generate_fat_tail_crash  # noqa: E402
from regime_detection import RegimeConfig, detect_combined_regime  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402
from walk_forward import walk_forward_analysis  # noqa: E402


BASELINE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "adversarial_stress_test_results.json"
TARGET_VOL = 0.20
STRATEGIES = ["sma_crossover", "ema_crossover"]


def detect_returns_based_regime(
    close: pd.Series,
    cum_return_threshold: float = -0.10,
    window: int = 21,
    recovery_days: int = 20,
    trend_ma_short: int = 50,
    trend_ma_long: int = 200,
    trend_threshold: float = 0.02,
    vol_quantile_high: float = 0.75,
    vol_quantile_low: float = 0.25,
    vol_window: int = 63,
    min_regime_length: int = 21,
) -> pd.Series:
    config = RegimeConfig(
        trend_ma_short=trend_ma_short,
        trend_ma_long=trend_ma_long,
        trend_threshold=trend_threshold,
        vol_window=vol_window,
        vol_quantile_high=vol_quantile_high,
        vol_quantile_low=vol_quantile_low,
        min_regime_length=min_regime_length,
    )
    base = detect_combined_regime(close, config=config)

    cumret = close.pct_change().rolling(window).sum()
    trigger = cumret < cum_return_threshold
    bear = pd.Series("unknown", index=close.index)
    idxs = trigger[trigger].index
    for i in idxs:
        pos = close.index.get_loc(i)
        end = min(pos + recovery_days, len(close))
        bear.iloc[pos:end] = "bear_high"

    combined = base.copy()
    combined[bear == "bear_high"] = "bear_high"
    combined = combined.replace("unknown", np.nan).ffill().fillna("unknown")
    return combined


def run_experiment():
    cfg = ScenarioConfig(periods=1000, seed=42)
    data = generate_fat_tail_crash(cfg)
    data.index = pd.to_datetime(data["date"])
    close = data["close"]
    regimes = detect_returns_based_regime(close)
    from collections import Counter
    counts = dict(Counter(regimes))
    out = Path(__file__).resolve().parent.parent / "examples" / "returns_based_regime_results.json"
    with open(out, "w") as f:
        json.dump({"target_vol": TARGET_VOL, "regime_counts": counts}, f, indent=2, default=str)
    print("wrote", out, counts)


if __name__ == "__main__":
    run_experiment()
