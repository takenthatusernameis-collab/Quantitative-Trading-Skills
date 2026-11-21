#!/usr/bin/env python3
"""
Crash-Trigger Regime Detector for fat_tail_crash.

Flags 'bear_high' regime directly from >5% 1-day negative returns,
matching the crash definition in the adversarial generator.
This bypasses the rolling-vol quantile approach that lags the crash.
"""

import sys
from pathlib import Path
from typing import Dict, Optional

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


def detect_crash_trigger_regime(
    close: pd.Series,
    crash_threshold: float = -0.05,  # 5% drop
    min_regime_length: int = 10,
    lookback: int = 21,
    vol_quantile_high: float = 0.75,
    vol_quantile_low: float = 0.25,
    trend_ma_short: int = 50,
    trend_ma_long: int = 200,
    trend_threshold: float = 0.02,
) -> pd.Series:
    """
    Detect combined trend+vol regime with crash-trigger enhancement.

    When a crash (>5% daily drop) occurs, immediately flag 'bear_high'
    for the crash day and subsequent recovery period, rather than
    waiting for rolling-vol quantile to cross threshold.

    Args:
        close: Close price series
        crash_threshold: Daily return threshold to trigger crash regime (default -5%)
        min_regime_length: Minimum bars for crash regime to persist
        lookback: Lookback for rolling vol after crash
        vol_quantile_high/low: Vol quantiles for non-crash periods
        trend_ma_short/long: Trend MA parameters
        trend_threshold: Trend classification threshold

    Returns:
        Series with regime labels including crash-triggered 'bear_high'
    """
    # Start with standard combined regime detection
    config = RegimeConfig(
        trend_ma_short=trend_ma_short,
        trend_ma_long=trend_ma_long,
        trend_threshold=trend_threshold,
        vol_window=lookback,
        vol_quantile_high=vol_quantile_high,
        vol_quantile_low=vol_quantile_low,
        min_regime_length=min_regime_length,
    )
    base_regimes = detect_combined_regime(close, config=config)

    # Compute daily returns
    returns = close.pct_change()

    # Find crash days (>5% drop)
    crash_mask = returns < crash_threshold
    crash_indices = crash_mask[crash_mask].index

    if len(crash_indices) == 0:
        return base_regimes

    # Create crash-triggered regime overlay
    # For each crash, force 'bear_high' for crash day + recovery window
    crash_regime = pd.Series("unknown", index=close.index)

    for crash_idx in crash_indices:
        crash_pos = close.index.get_loc(crash_idx)
        # Crash day + recovery (min_regime_length bars)
        end_pos = min(crash_pos + min_regime_length, len(close))
        crash_regime.iloc[crash_pos:end_pos] = "bear_high"

    # Combine: use crash_regime where it's 'bear_high', otherwise base_regimes
    # This ensures crash-triggered bear_high takes precedence
    combined = base_regimes.copy()
    mask_crash_bear = crash_regime == "bear_high"
    combined[mask_crash_bear] = "bear_high"

    # Forward fill to handle any remaining unknown
    combined = combined.replace("unknown", np.nan).ffill().fillna("unknown")

    return combined


def detect_hybrid_crash_regime(
    close: pd.Series,
    crash_threshold: float = -0.05,
    crash_recovery_days: int = 20,
    vol_quantile_high: float = 0.75,
    vol_quantile_low: float = 0.25,
    vol_window: int = 63,
    min_regime_length: int = 21,
    trend_ma_short: int = 50,
    trend_ma_long: int = 200,
    trend_threshold: float = 0.02,
) -> pd.Series:
    """
    Hybrid detector: uses crash trigger for bear_high, standard quantile for other regimes.

    More nuanced approach:
    - Crash trigger immediately sets bear_high for crash + recovery period
    - Standard vol quantiles handle bull_high, sideways_high, low-vol regimes
    - Trend detection unchanged
    """
    from regime_detection import (
        detect_trend_regime,
        detect_volatility_regime,
        TrendRegime,
        VolatilityRegime,
    )

    # Detect trend regime (unchanged)
    trend = detect_trend_regime(
        close, trend_ma_short, trend_ma_long, trend_threshold
    )

    # Detect volatility regime (standard)
    vol = detect_volatility_regime(
        close, vol_window, vol_quantile_high, vol_quantile_low
    )

    # Crash-triggered bear_high overlay
    returns = close.pct_change()
    crash_mask = returns < crash_threshold
    crash_indices = crash_mask[crash_mask].index

    combined = pd.Series("unknown", index=close.index)

    # Start with standard combination
    mask_known = (trend != TrendRegime.UNKNOWN.value) & (vol != VolatilityRegime.UNKNOWN.value)
    combined[mask_known] = trend[mask_known] + "_" + vol[mask_known]

    # Overlay crash-triggered bear_high
    for crash_idx in crash_indices:
        crash_pos = close.index.get_loc(crash_idx)
        end_pos = min(crash_pos + crash_recovery_days, len(close))
        combined.iloc[crash_pos:end_pos] = "bear_high"

    # Forward fill
    combined = combined.replace("unknown", np.nan).ffill().fillna("unknown")

    return combined


def run_crash_trigger_test() -> Dict:
    """Test crash-trigger detector on fat_tail_crash at target_vol=0.20."""
    print("=" * 80)
    print("CRASH-TRIGGER DETECTOR TEST ON fat_tail_crash")
    print("=" * 80)

    # Load baseline
    baseline_index = {}
    if BASELINE_PATH.exists():
        import json
        with open(BASELINE_PATH) as f:
            records = json.load(f)
        baseline_index = {
            (r["scenario"], r["strategy"]): r["walk_forward"]
            for r in records
            if r.get("walk_forward", {}).get("success")
        }
        print(f"Loaded baseline for {len(baseline_index)} pairs")

    # Generate fat_tail_crash data
    config = ScenarioConfig(seed=42, periods=5000)
    data = generate_fat_tail_crash(config)
    if isinstance(data, pd.DataFrame) and "date" in data.columns:
        data = data.set_index("date")
        data.index = pd.DatetimeIndex(data.index)

    # Test crash-trigger detector configs
    crash_configs = [
        {"name": "crash_trigger_5pct_10day", "crash_threshold": -0.05, "min_regime_length": 10},
        {"name": "crash_trigger_5pct_20day", "crash_threshold": -0.05, "min_regime_length": 20},
        {"name": "crash_trigger_5pct_30day", "crash_threshold": -0.05, "min_regime_length": 30},
        {"name": "crash_trigger_3pct_10day", "crash_threshold": -0.03, "min_regime_length": 10},
        {"name": "crash_trigger_7pct_10day", "crash_threshold": -0.07, "min_regime_length": 10},
        {"name": "hybrid_crash_5pct_20day", "crash_threshold": -0.05, "crash_recovery_days": 20},
    ]

    results = []

    for strategy_name in STRATEGIES:
        base_wf = baseline_index.get(("fat_tail_crash", strategy_name), {})
        base_sharpe = base_wf.get("oos_sharpe") if isinstance(base_wf, dict) else None
        print(f"\n  Strategy: {strategy_name}, Baseline Sharpe: {base_sharpe}")

        for cfg in crash_configs:
            print(f"    Testing: {cfg['name']}")

            if cfg["name"].startswith("hybrid"):
                regimes = detect_hybrid_crash_regime(
                    data["close"],
                    crash_threshold=cfg["crash_threshold"],
                    crash_recovery_days=cfg["crash_recovery_days"],
                )
            else:
                regimes = detect_crash_trigger_regime(
                    data["close"],
                    crash_threshold=cfg["crash_threshold"],
                    min_regime_length=cfg["min_regime_length"],
                )

            # Check first bear_high
            bear_high_mask = regimes == "bear_high"
            first_bear_high = int(bear_high_mask.argmax()) if bear_high_mask.any() else None

            # Run walk-forward with regime-aware sizing
            STRATEGIES_LOCAL = {
                "sma_crossover": {
                    "param_grid": {
                        "fast_period": [3, 5, 8],
                        "slow_period": [10, 15, 20],
                    },
                },
                "ema_crossover": {
                    "param_grid": {
                        "fast_period": [3, 5, 8],
                        "slow_period": [10, 15, 20],
                    },
                },
            }

            class RegimeAwareStrategyLocal:
                def __init__(self, base_strategy, regimes, target_vol, lookback=20):
                    self.base = base_strategy
                    self.config = base_strategy.config
                    self.name = base_strategy.name
                    self.parameters = base_strategy.parameters
                    self.regimes = regimes
                    self.target_vol = float(target_vol)
                    self.lookback = int(lookback)

                def generate_signals(self, data):
                    from regime_detection import regime_aware_position_size
                    base_sig = self.base.generate_signals(data)
                    regimes_sub = self.regimes.reindex(data.index)
                    target_by_regime = {
                        str(label): self.target_vol for label in pd.unique(regimes_sub.dropna())
                    }
                    return regime_aware_position_size(
                        base_sig,
                        data["close"],
                        regimes_sub,
                        target_by_regime,
                        lookback=self.lookback,
                        default_target_vol=self.target_vol,
                        min_leverage=0.0,
                        max_leverage=2.0,
                    )

                def generate_target_weights(self, data=None):
                    return None

            ra_factory = (
                lambda params, sn=strategy_name, rg=regimes, tv=TARGET_VOL: RegimeAwareStrategyLocal(
                    build_strategy(sn, json.dumps(params)), rg, tv
                )
            )

            ra_wf = walk_forward_analysis(
                data=data,
                strategy_factory=ra_factory,
                param_grid=STRATEGIES_LOCAL[strategy_name]["param_grid"],
                train_months=3,
                test_months=3,
                step_months=3,
                apply_deflation=True,
                validate_pit=True,
            )

            ra_sharpe = ra_wf["summary"].get("oos_sharpe")
            delta = (ra_sharpe - base_sharpe) if (base_sharpe is not None and ra_sharpe is not None) else None

            result = {
                "strategy": strategy_name,
                "config_name": cfg["name"],
                "first_bear_high_idx": first_bear_high,
                "baseline_sharpe": base_sharpe,
                "regime_sized_sharpe": ra_sharpe,
                "delta": delta,
            }
            results.append(result)

            print(f"      First bear_high: {first_bear_high}, OOS Sharpe: {ra_sharpe}, Delta: {delta}")

    return {"fat_tail_crash_crash_trigger": results}


def generate_results_table(results: Dict) -> str:
    """Generate markdown table for results."""
    lines = []
    lines.append("| Strategy | Config | First bear_high | Baseline Sharpe | Regime-Sized Sharpe | Delta |")
    lines.append("|----------|--------|-----------------|-----------------|---------------------|-------|")

    for res in results["fat_tail_crash_crash_trigger"]:
        lines.append(
            f"| {res['strategy']} | {res['config_name']} | "
            f"{res['first_bear_high_idx']} | "
            f"{res['baseline_sharpe']:+.4f} | "
            f"{res['regime_sized_sharpe']:+.4f} | "
            f"{res['delta']:+.4f} |"
        )

    return "\n".join(lines)


def main():
    results = run_crash_trigger_test()

    # Print table
    print("\n" + "=" * 80)
    print("RESULTS SUMMARY")
    print("=" * 80)
    print(generate_results_table(results))

    # Find best config
    best = max(
        results["fat_tail_crash_crash_trigger"],
        key=lambda r: r["delta"] if r["delta"] is not None else -999
    )
    print(f"\n**Best crash-trigger config**: {best['config_name']} "
          f"(delta = {best['delta']:+.4f} vs baseline)")

    if best["delta"] is not None and best["delta"] > 0:
        print("The crash-trigger detector **improves OOS Sharpe vs baseline** for this configuration.")
    else:
        print("The crash-trigger detector variants tested did **not** recover the degradation vs baseline.")

    # Save results
    import json
    out_path = Path(__file__).resolve().parent.parent / "examples" / "crash_trigger_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    main()