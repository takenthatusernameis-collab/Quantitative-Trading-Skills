#!/usr/bin/env python3
"""
Returns-based regime detector for fat_tail_crash at uniform tv=0.20.

Detects bear_high from cumulative negative returns instead of volatility
quantiles. Reuses detect_combined_regime machinery for trend/vol labels,
overwriting bear_high based on cumulative-return threshold, then runs
walk_forward_analysis at uniform target_vol=0.20.

No profitability or statistical-significance claims; synthetic adversarial data.
"""
import json
import sys
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_adversarial_scenarios import ScenarioConfig, generate_fat_tail_crash  # noqa: E402
from regime_detection import RegimeConfig, detect_combined_regime, detect_trend_regime  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402
from walk_forward import walk_forward_analysis  # noqa: E402
from regime_detection import regime_aware_position_size  # noqa: E402

BASELINE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "adversarial_stress_test_results.json"
TARGET_VOL = 0.20
STRATEGIES = ["sma_crossover", "ema_crossover"]


def detect_returns_based_regime(
    close: pd.Series,
    cum_return_window: int = 63,
    cum_return_threshold: float = -0.10,
    recovery_days: int = 20,
    trend_ma_short: int = 50,
    trend_ma_long: int = 200,
    trend_threshold: float = 0.02,
    vol_quantile_high: float = 0.75,
    vol_quantile_low: float = 0.25,
    vol_window: int = 63,
) -> pd.Series:
    """
    Returns-based detector: standard combined regime, but bear_high is set
    whenever cumulative return over cum_return_window falls below
    cum_return_threshold. Other regimes from detect_combined_regime retained.
    """
    from regime_detection import TrendRegime, VolatilityRegime, detect_volatility_regime

    trend = detect_trend_regime(close, trend_ma_short, trend_ma_long, trend_threshold)
    vol = detect_volatility_regime(close, vol_window, vol_quantile_high, vol_quantile_low)

    combined = pd.Series("unknown", index=close.index)
    mask_known = (trend != TrendRegime.UNKNOWN.value) & (vol != VolatilityRegime.UNKNOWN.value)
    combined[mask_known] = trend[mask_known] + "_" + vol[mask_known]

    # Remove standard bear_high; re-derive from cumulative returns
    combined = combined.where(~(combined.str.startswith("bear")), "unknown")

    cum_ret = close.pct_change().rolling(cum_return_window).apply(lambda r: (1 + r).prod() - 1, raw=False)
    crash_mask = cum_ret < cum_return_threshold
    crash_indices = crash_mask[crash_mask.fillna(False)].index

    for crash_idx in crash_indices:
        crash_pos = close.index.get_loc(crash_idx)
        end_pos = min(crash_pos + recovery_days, len(close))
        combined.iloc[crash_pos:end_pos] = "bear_high"

    combined = combined.replace("unknown", np.nan).ffill().fillna("unknown")
    return combined


def run() -> Dict:
    print("=" * 80)
    print("RETURNS-BASED REGIME DETECTION ON fat_tail_crash (uniform tv=0.20)")
    print("=" * 80)

    baseline_index = {}
    if BASELINE_PATH.exists():
        with open(BASELINE_PATH) as f:
            records = json.load(f)
        baseline_index = {
            (r["scenario"], r["strategy"]): r["walk_forward"]
            for r in records
            if r.get("walk_forward", {}).get("success")
        }
        print(f"Loaded baseline for {len(baseline_index)} pairs")

    config = ScenarioConfig(seed=42, periods=5000)
    data = generate_fat_tail_crash(config)
    if isinstance(data, pd.DataFrame) and "date" in data.columns:
        data = data.set_index("date")
        data.index = pd.DatetimeIndex(data.index)

    STRATEGIES_LOCAL = {
        "sma_crossover": {"param_grid": {"fast_period": [3, 5, 8], "slow_period": [10, 15, 20]}},
        "ema_crossover": {"param_grid": {"fast_period": [3, 5, 8], "slow_period": [10, 15, 20]}},
    }

    results = []
    for strategy_name in STRATEGIES:
        base_wf = baseline_index.get(("fat_tail_crash", strategy_name), {})
        base_sharpe = base_wf.get("oos_sharpe") if isinstance(base_wf, dict) else None
        print(f"\n  Strategy: {strategy_name}, Baseline Sharpe: {base_sharpe}")

        regimes = detect_returns_based_regime(data["close"])
        bear_mask = regimes == "bear_high"
        first_bear = int(bear_mask.argmax()) if bear_mask.any() else None
        print(f"    First bear_high idx: {first_bear}, count: {int(bear_mask.sum())}")

        unique_regimes = [str(l) for l in pd.unique(regimes.dropna())]
        target_by_regime = {label: TARGET_VOL for label in unique_regimes}

        class RegimeAware:
            def __init__(self, base_strategy, regimes, target_by_regime):
                self.base = base_strategy
                self.config = base_strategy.config
                self.name = base_strategy.name
                self.parameters = base_strategy.parameters
                self.regimes = regimes
                self.target_by_regime = target_by_regime

            def generate_signals(self, data):
                base_sig = self.base.generate_signals(data)
                regimes_sub = self.regimes.reindex(data.index)
                return regime_aware_position_size(
                    base_sig, data["close"], regimes_sub, self.target_by_regime,
                    lookback=20, default_target_vol=TARGET_VOL, min_leverage=0.0, max_leverage=2.0,
                )

            def generate_target_weights(self, data=None):
                return None

        ra_factory = lambda params, sn=strategy_name, rg=regimes, tb=target_by_regime: RegimeAware(
            build_strategy(sn, json.dumps(params)), rg, tb
        )

        ra_wf = walk_forward_analysis(
            data=data,
            strategy_factory=ra_factory,
            param_grid=STRATEGIES_LOCAL[strategy_name]["param_grid"],
            train_months=3, test_months=3, step_months=3,
            apply_deflation=True, validate_pit=True,
        )

        ra_sharpe = ra_wf["summary"].get("oos_sharpe")
        delta = (ra_sharpe - base_sharpe) if (base_sharpe is not None and ra_sharpe is not None) else None
        results.append({
            "strategy": strategy_name,
            "detector": "returns_based",
            "target_vol": TARGET_VOL,
            "first_bear_high_idx": first_bear,
            "bear_high_count": int(bear_mask.sum()),
            "baseline_sharpe": base_sharpe,
            "returns_based_sharpe": ra_sharpe,
            "delta": delta,
        })
        print(f"    OOS Sharpe: {ra_sharpe}, Delta: {delta}")

    out_path = Path(__file__).resolve().parent.parent / "examples" / "returns_based_regime_results.json"
    with open(out_path, "w") as f:
        json.dump({"fat_tail_crash_returns_based": results}, f, indent=2, default=str)
    print(f"\nResults saved to: {out_path}")
    return {"fat_tail_crash_returns_based": results}


if __name__ == "__main__":
    run()
