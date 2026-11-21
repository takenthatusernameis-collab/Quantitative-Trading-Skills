#!/usr/bin/env python3
"""
Target_vol x vol_window sweep for the regime-aware volatility-targeting overlay.

Extends the session 145/146 regime-aware variant sweep
(skills/quantitative-backtesting/examples/adversarial_stress_test.py,
REGIME-AWARE VARIANTS section) with a parameter grid instead of a single
(target_vol=0.10, vol_window=63) cell:

    target_vol   in {0.05, 0.10, 0.15, 0.20}
    vol_window   in {21, 63, 126}     (vol_quantiles 0.25/0.75,
                                        min_regime_length 21 held fixed)

Runs all 6 adversarial scenarios x SMA/EMA (144 regime-sized walk-forwards),
compares OOS Sharpe delta vs the committed baseline
(adversarial_stress_test_results.json), and evaluates the session-146 success
criterion:

    volatility_clustering / fat_tail_crash deltas less negative than at the
    (0.10, 63) reference cell, AND
    regime_shift / liquidity_crisis / structural_break / trend_persistence
    deltas non-negative.

No statistical-significance or profitability claims: synthetic adversarial
data, DSR p ~ 1.0, test resolution ~ 2.0 Sharpe (session 145/146 finding).

Outputs (nothing else is modified):
    skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware_sweep.json
"""

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from generate_adversarial_scenarios import (  # noqa: E402
    generate_fat_tail_crash,
    generate_liquidity_crisis,
    generate_regime_shift,
    generate_structural_break,
    generate_trend_persistence,
    generate_volatility_clustering,
    ScenarioConfig,
)
from strategy_builder import build_strategy  # noqa: E402
from walk_forward import walk_forward_analysis  # noqa: E402
from regime_detection import (  # noqa: E402
    RegimeConfig,
    detect_combined_regime,
    regime_aware_position_size,
)

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
BASELINE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "adversarial_stress_test_results.json"
OUT_PATH = EXAMPLES_DIR / "adversarial_stress_test_regime_aware_sweep.json"

sys.path.insert(0, str(EXAMPLES_DIR))
from adversarial_stress_test import RegimeAwareStrategy, run_walk_forward_stress, STRATEGIES  # noqa: E402

TARGET_VOLS = [0.05, 0.10, 0.15, 0.20]
VOL_WINDOWS = [21, 63, 126]
VOL_QUANTILE_HIGH = 0.75
VOL_QUANTILE_LOW = 0.25
MIN_REGIME_LENGTH = 21

VARIANT_SCENARIOS = [
    "volatility_clustering",
    "regime_shift",
    "fat_tail_crash",
    "liquidity_crisis",
    "structural_break",
    "trend_persistence",
]
IMPROVING = ["regime_shift", "liquidity_crisis", "structural_break", "trend_persistence"]
DEGRADING = ["volatility_clustering", "fat_tail_crash"]
REF_CELL = (0.10, 63)

VARIANT_GENS = {
    "regime_shift": lambda cfg: generate_regime_shift(cfg, bull_months=18, bear_months=18, transition_months=3),
    "structural_break": lambda cfg: generate_structural_break(cfg),
    "liquidity_crisis": lambda cfg: generate_liquidity_crisis(cfg),
    "trend_persistence": lambda cfg: generate_trend_persistence(cfg),
    "fat_tail_crash": lambda cfg: generate_fat_tail_crash(cfg),
    "volatility_clustering": lambda cfg: generate_volatility_clustering(cfg),
}


def fmt(x):
    return "n/a" if x is None else f"{x:+.4f}"


def load_baseline() -> Dict[tuple, Dict[str, Any]]:
    if not BASELINE_PATH.exists():
        print(f"WARNING: baseline {BASELINE_PATH} not found; deltas will be unavailable")
        return {}
    with open(BASELINE_PATH) as f:
        records = json.load(f)
    return {
        (r["scenario"], r["strategy"]): r["walk_forward"]
        for r in records
        if r.get("walk_forward", {}).get("success")
    }


def run_sweep(baseline_index: Dict[tuple, Dict[str, Any]]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for scenario_name in VARIANT_SCENARIOS:
        gen = VARIANT_GENS[scenario_name]
        for vol_window in VOL_WINDOWS:
            config = ScenarioConfig(seed=42, periods=5000)
            data = gen(config)
            if isinstance(data, pd.DataFrame) and "date" in data.columns:
                data = data.set_index("date")
                data.index = pd.DatetimeIndex(data.index)

            regimes = detect_combined_regime(
                data["close"],
                config=RegimeConfig(
                    vol_window=vol_window,
                    vol_quantile_high=VOL_QUANTILE_HIGH,
                    vol_quantile_low=VOL_QUANTILE_LOW,
                    min_regime_length=MIN_REGIME_LENGTH,
                ),
            )

            for strategy_name, strategy_config in STRATEGIES.items():
                base_wf = baseline_index.get((scenario_name, strategy_name), {})
                base_sharpe = base_wf.get("oos_sharpe") if isinstance(base_wf, dict) else None

                for target_vol in TARGET_VOLS:
                    ra_factory = (
                        lambda params, sn=strategy_name, rg=regimes, tv=target_vol: RegimeAwareStrategy(
                            build_strategy(sn, json.dumps(params)), rg, tv
                        )
                    )
                    ra_wf = run_walk_forward_stress(
                        data, strategy_name, strategy_config["param_grid"], strategy_factory=ra_factory
                    )
                    ra_sharpe = ra_wf.get("oos_sharpe") if isinstance(ra_wf, dict) else None
                    delta = (ra_sharpe - base_sharpe) if (base_sharpe is not None and ra_sharpe is not None) else None

                    print(
                        f"  [{scenario_name:22s} | {strategy_name:14s} | "
                        f"tv={target_vol} | vw={vol_window:3d}] "
                        f"baseline {fmt(base_sharpe)}  regime-sized {fmt(ra_sharpe)}  delta {fmt(delta)}"
                    )

                    records.append(
                        {
                            "scenario": scenario_name,
                            "strategy": strategy_name,
                            "target_vol": target_vol,
                            "vol_window": vol_window,
                            "baseline": base_wf,
                            "regime_sized": ra_wf,
                            "baseline_sharpe": base_sharpe,
                            "regime_sized_sharpe": ra_sharpe,
                            "delta": delta,
                        }
                    )
    return records
def evaluate(records: List[Dict[str, Any]]) -> None:
    # Reference deltas at the (0.10, 63) cell
    ref = {
        (r["scenario"], r["strategy"]): r["delta"]
        for r in records
        if (r["target_vol"], r["vol_window"]) == REF_CELL
    }

    print("\n" + "=" * 100)
    print("SWEEP SUMMARY — delta vs baseline (regime-sized minus baseline OOS Sharpe)")
    print("=" * 100)
    print(
        f"  {'scenario':<22} {'strategy':<14} {'tv':>5} {'vw':>4} "
        f"{'base':>10} {'ra':>10} {'delta':>9} {'vs ref':>9}"
    )
    for r in records:
        vs_ref = (
            f"{(r['delta'] - ref[(r['scenario'], r['strategy'])]):+.4f}"
            if r["delta"] is not None and ref.get((r["scenario"], r["strategy"])) is not None
            else "n/a"
        )
        print(
            f"  {r['scenario']:<22} {r['strategy']:<14} {r['target_vol']!s:>5} "
            f"{r['vol_window']!s:>4} {fmt(r['baseline_sharpe']):>10} "
            f"{fmt(r['regime_sized_sharpe']):>10} {fmt(r['delta']):>9} {vs_ref:>9}"
        )

    print("\n" + "=" * 100)
    print("SUCCESS CRITERION (session 146):")
    print("  - degrading (volatility_clustering, fat_tail_crash): delta less negative than at (0.10, 63)")
    print("  - improving (regime_shift, liquidity_crisis, structural_break, trend_persistence): delta >= 0")
    print("=" * 100)

    best_cell = None
    best_score = None
    for cell in [(tv, vw) for tv in TARGET_VOLS for vw in VOL_WINDOWS]:
        cell_records = [r for r in records if (r["target_vol"], r["vol_window"]) == cell]
        degrading_ok = all(
            r["delta"] is not None
            and ref.get((r["scenario"], r["strategy"])) is not None
            and r["delta"] > ref[(r["scenario"], r["strategy"])]
            for r in cell_records
            if r["scenario"] in DEGRADING
        )
        improving_ok = all(
            r["delta"] is not None and r["delta"] >= 0.0
            for r in cell_records
            if r["scenario"] in IMPROVING
        )
        ok = degrading_ok and improving_ok
        # Score: sum of improving deltas minus sum of degrading abs deltas relative to ref
        score = sum(
            r["delta"] for r in cell_records if r["scenario"] in IMPROVING and r["delta"] is not None
        ) - sum(
            abs(r["delta"]) for r in cell_records if r["scenario"] in DEGRADING and r["delta"] is not None
        )
        print(
            f"  cell tv={cell[0]} vw={cell[1]}: degrading_ok={degrading_ok} "
            f"improving_ok={improving_ok} -> {'PASS' if ok else 'pass'} score={fmt(score)}"
        )
        if ok and (best_score is None or score > best_score):
            best_cell = cell
            best_score = score

    if best_cell is not None:
        print(f"\nBEST PASSING CELL: target_vol={best_cell[0]}, vol_window={best_cell[1]} (score={fmt(best_score)})")
    else:
        print("\nNo cell satisfied the full success criterion; inspect the table above for the best compromise.")


def main():
    print(f"Baseline: {BASELINE_PATH} (exists={BASELINE_PATH.exists()})")
    baseline_index = load_baseline()
    print(f"Loaded baseline for {len(baseline_index)} scenario/strategy pairs")
    print(f"Grid: target_vol={TARGET_VOLS} x vol_window={VOL_WINDOWS} "
          f"x {len(VARIANT_SCENARIOS)} scenarios x 2 strategies = "
          f"{len(TARGET_VOLS)*len(VOL_WINDOWS)*len(VARIANT_SCENARIOS)*2} walk-forwards")

    records = run_sweep(baseline_index)

    sweep = {
        "target_vols": TARGET_VOLS,
        "vol_windows": VOL_WINDOWS,
        "vol_quantiles": [VOL_QUANTILE_LOW, VOL_QUANTILE_HIGH],
        "min_regime_length": MIN_REGIME_LENGTH,
        "reference_cell": REF_CELL,
        "n_records": len(records),
        "records": records,
    }
    with open(OUT_PATH, "w") as f:
        json.dump(sweep, f, indent=2, default=str)
    print(f"\nSweep results saved to: {OUT_PATH}")

    evaluate(records)


if __name__ == "__main__":
    main()
