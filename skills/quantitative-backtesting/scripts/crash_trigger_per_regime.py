#!/usr/bin/env python3
"""
Crash-Trigger Regime Detector with Per-Regime Target Vol for fat_tail_crash.

Tests whether a crash-trigger detector combined with per-regime target_vol
(bear_high gets lower target_vol) can recover the fat_tail_crash degradation.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from generate_adversarial_scenarios import ScenarioConfig, generate_fat_tail_crash  # noqa: E402
from regime_detection import RegimeConfig, detect_combined_regime, regime_aware_position_size  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402
from walk_forward import walk_forward_analysis  # noqa: E402


BASELINE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "adversarial_stress_test_results.json"
TARGET_VOL_BASE = 0.20  # Base target vol from sweep (best uniform)
TARGET_VOL_BEAR_HIGH = 0.10  # Lower target vol for bear_high (crash protection)
STRATEGIES = ["sma_crossover", "ema_crossover"]


def detect_crash_trigger_regime(
    close: pd.Series,
    crash_threshold: float = -0.05,
    recovery_days: int = 20,
    vol_quantile_high: float = 0.75,
    vol_quantile_low: float = 0.25,
    vol_window: int = 63,
    min_regime_length: int = 21,
    trend_ma_short: int = 50,
    trend_ma_long: int = 200,
    trend_threshold: float = 0.02,
) -> pd.Series:
    """
    Hybrid detector: crash-triggered bear_high + standard quantile for other regimes.
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
        end_pos = min(crash_pos + recovery_days, len(close))
        combined.iloc[crash_pos:end_pos] = "bear_high"

    # Forward fill
    combined = combined.replace("unknown", np.nan).ffill().fillna("unknown")

    return combined


def run_per_regime_target_vol_test() -> Dict:
    """Test crash-trigger detector with per-regime target_vol on fat_tail_crash."""
    print("=" * 80)
    print("CRASH-TRIGGER DETECTOR WITH PER-REGIME TARGET_VOL ON fat_tail_crash")
    print("=" * 80)

    # Load baseline (uniform tv=0.20 from sweep)
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

    # Generate fat_tail_crash data
    config = ScenarioConfig(seed=42, periods=5000)
    data = generate_fat_tail_crash(config)
    if isinstance(data, pd.DataFrame) and "date" in data.columns:
        data = data.set_index("date")
        data.index = pd.DatetimeIndex(data.index)

    # Test configs: detector type x target_vol scheme
    test_configs = [
        {
            "name": "default_detector_uniform_0.20",
            "detector": "default",
            "target_vol_scheme": "uniform",
            "target_vol_base": TARGET_VOL_BASE,
        },
        {
            "name": "crash_trigger_uniform_0.20",
            "detector": "crash_trigger",
            "target_vol_scheme": "uniform",
            "target_vol_base": TARGET_VOL_BASE,
        },
        {
            "name": "default_detector_per_regime",
            "detector": "default",
            "target_vol_scheme": "per_regime",
            "target_vol_base": TARGET_VOL_BASE,
            "target_vol_bear_high": TARGET_VOL_BEAR_HIGH,
        },
        {
            "name": "crash_trigger_per_regime",
            "detector": "crash_trigger",
            "target_vol_scheme": "per_regime",
            "target_vol_base": TARGET_VOL_BASE,
            "target_vol_bear_high": TARGET_VOL_BEAR_HIGH,
        },
    ]

    results = []

    for strategy_name in STRATEGIES:
        base_wf = baseline_index.get(("fat_tail_crash", strategy_name), {})
        base_sharpe = base_wf.get("oos_sharpe") if isinstance(base_wf, dict) else None
        print(f"\n  Strategy: {strategy_name}, Baseline Sharpe: {base_sharpe}")

        for cfg in test_configs:
            print(f"    Testing: {cfg['name']}")

            # Generate regimes
            if cfg["detector"] == "default":
                regimes = detect_combined_regime(
                    data["close"],
                    config=RegimeConfig(),
                )
            else:  # crash_trigger
                regimes = detect_crash_trigger_regime(
                    data["close"],
                    crash_threshold=-0.05,
                    recovery_days=20,
                )

            # Check first bear_high
            bear_high_mask = regimes == "bear_high"
            first_bear_high = int(bear_high_mask.argmax()) if bear_high_mask.any() else None

            # Build target_by_regime dict
            unique_regimes = [str(l) for l in pd.unique(regimes.dropna())]
            if cfg["target_vol_scheme"] == "uniform":
                target_by_regime = {label: cfg["target_vol_base"] for label in unique_regimes}
            else:  # per_regime
                target_by_regime = {}
                for label in unique_regimes:
                    if label == "bear_high":
                        target_by_regime[label] = cfg["target_vol_bear_high"]
                    else:
                        target_by_regime[label] = cfg["target_vol_base"]

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

            class RegimeAwareStrategyPerRegime:
                def __init__(self, base_strategy, regimes, target_by_regime, lookback=20):
                    self.base = base_strategy
                    self.config = base_strategy.config
                    self.name = base_strategy.name
                    self.parameters = base_strategy.parameters
                    self.regimes = regimes
                    self.target_by_regime = target_by_regime
                    self.lookback = int(lookback)

                def generate_signals(self, data):
                    base_sig = self.base.generate_signals(data)
                    regimes_sub = self.regimes.reindex(data.index)
                    return regime_aware_position_size(
                        base_sig,
                        data["close"],
                        regimes_sub,
                        self.target_by_regime,
                        lookback=self.lookback,
                        default_target_vol=cfg["target_vol_base"],
                        min_leverage=0.0,
                        max_leverage=2.0,
                    )

                def generate_target_weights(self, data=None):
                    return None

            ra_factory = (
                lambda params, sn=strategy_name, rg=regimes, tb=target_by_regime: RegimeAwareStrategyPerRegime(
                    build_strategy(sn, json.dumps(params)), rg, tb
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
                "detector": cfg["detector"],
                "target_vol_scheme": cfg["target_vol_scheme"],
                "first_bear_high_idx": first_bear_high,
                "baseline_sharpe": base_sharpe,
                "regime_sized_sharpe": ra_sharpe,
                "delta": delta,
            }
            results.append(result)

            print(f"      First bear_high: {first_bear_high}, OOS Sharpe: {ra_sharpe}, Delta: {delta}")

    return {"fat_tail_crash_per_regime_test": results}


def generate_results_table(results: Dict) -> str:
    """Generate markdown table for results."""
    lines = []
    lines.append("| Strategy | Config | Detector | Target Scheme | First bear_high | Baseline Sharpe | Regime-Sized Sharpe | Delta |")
    lines.append("|----------|--------|----------|---------------|-----------------|-----------------|---------------------|-------|")

    for res in results["fat_tail_crash_per_regime_test"]:
        lines.append(
            f"| {res['strategy']} | {res['config_name']} | "
            f"{res['detector']} | {res['target_vol_scheme']} | "
            f"{res['first_bear_high_idx']} | "
            f"{res['baseline_sharpe']:+.4f} | "
            f"{res['regime_sized_sharpe']:+.4f} | "
            f"{res['delta']:+.4f} |"
        )

    return "\n".join(lines)


def main():
    results = run_per_regime_target_vol_test()

    # Print table
    print("\n" + "=" * 80)
    print("RESULTS SUMMARY")
    print("=" * 80)
    print(generate_results_table(results))

    # Find best config
    best = max(
        results["fat_tail_crash_per_regime_test"],
        key=lambda r: r["delta"] if r["delta"] is not None else -999
    )
    print(f"\n**Best config**: {best['config_name']} "
          f"(delta = {best['delta']:+.4f} vs baseline)")

    if best["delta"] is not None and best["delta"] > 0:
        print("The crash-trigger detector with per-regime target_vol **improves OOS Sharpe vs baseline**.")
    else:
        print("The crash-trigger detector with per-regime target_vol did **not** recover the degradation vs baseline.")

    # Compare crash-trigger vs default within same target_vol scheme
    print("\n--- Comparison: Crash-trigger vs Default (same target_vol scheme) ---")
    for scheme in ["uniform", "per_regime"]:
        scheme_results = [r for r in results["fat_tail_crash_per_regime_test"] if r["target_vol_scheme"] == scheme]
        default = next(r for r in scheme_results if r["detector"] == "default")
        crash = next(r for r in scheme_results if r["detector"] == "crash_trigger")
        diff = (crash["delta"] - default["delta"]) if (crash["delta"] is not None and default["delta"] is not None) else None
        print(f"  {scheme}: crash_trigger delta {crash['delta']:+.4f} vs default delta {default['delta']:+.4f} (diff = {diff:+.4f})")

    # Save results
    out_path = Path(__file__).resolve().parent.parent / "examples" / "crash_trigger_per_regime_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {out_path}")


if __name__ == "__main__":
    main()