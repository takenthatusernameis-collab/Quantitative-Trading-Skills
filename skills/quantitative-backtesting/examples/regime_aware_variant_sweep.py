#!/usr/bin/env python3
"""
Regime-Aware Variant Sweep: focused runner.

Runs the regime-aware position-sizing overlay (and cost-multiplier control)
on the six single-asset adversarial scenarios, comparing OOS Sharpe vs the
committed baseline walk-forward results. Applies a pre-registered
falsification criterion and reports whether the null result (session 144/145)
generalizes beyond volatility_clustering and regime_shift.

Reuses components from adversarial_stress_test.py and the backtesting scripts.
No profitability claim is made; this is a test verdict against a
pre-registered criterion.
"""

import json
import sys
from pathlib import Path

import pandas as pd

EXAMPLES_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = EXAMPLES_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(EXAMPLES_DIR))

from adversarial_stress_test import (  # noqa: E402
    RegimeAwareStrategy,
    SCENARIOS,
    STRATEGIES,
    detect_combined_regime,
    run_walk_forward_stress,
)
from generate_adversarial_scenarios import ScenarioConfig  # noqa: E402
from regime_detection import RegimeConfig  # noqa: E402

TARGET_VOL = 0.10
COST_MULTIPLIER = 1.5
SEED = 42
PERIODS = 5000

FALSIFICATION_CRITERION = (
    "Regime-aware vol targeting to 10% annualized vol per regime must "
    "improve OOS Sharpe vs baseline on at least one scenario-strategy "
    "combination across the adversarial suite; otherwise the null result "
    "is confirmed as generalizable."
)

VARIANT_SCENARIOS = [
    "volatility_clustering",
    "regime_shift",
    "fat_tail_crash",
    "liquidity_crisis",
    "structural_break",
    "trend_persistence",
]


def fmt(val, fmt_str="{:.4f}"):
    if val is None:
        return "N/A"
    try:
        return fmt_str.format(val)
    except (ValueError, TypeError):
        return str(val)


def load_baseline_index():
    """Load committed baseline walk-forward results per (scenario, strategy)."""
    candidates = [
        EXAMPLES_DIR / "adversarial_stress_test_results.json",
        Path("adversarial_stress_test_results.json"),
    ]
    for path in candidates:
        if path.exists():
            with open(path) as f:
                records = json.load(f)
            return {
                (r["scenario"], r["strategy"]): r.get("walk_forward", {})
                for r in records
                if r.get("walk_forward", {}).get("success")
            }
    raise FileNotFoundError("No committed adversarial_stress_test_results.json baseline found")


def main():
    baseline_index = load_baseline_index()
    print(f"Loaded baseline for {len(baseline_index)} scenario/strategy pairs")

    variant_records = []
    for scenario_name in VARIANT_SCENARIOS:
        scenario_config = SCENARIOS[scenario_name]
        config = ScenarioConfig(seed=SEED, periods=PERIODS)
        data = scenario_config["generator"](config, **scenario_config["kwargs"])
        if isinstance(data, pd.DataFrame) and "date" in data.columns:
            data = data.set_index("date")
            data.index = pd.DatetimeIndex(data.index)

        regimes = detect_combined_regime(data["close"], config=RegimeConfig())
        high_vol_labels = [str(l) for l in pd.unique(regimes.dropna()) if "_high" in str(l)]
        cost_multipliers = {l: COST_MULTIPLIER for l in high_vol_labels}

        for strategy_name, strategy_config in STRATEGIES.items():
            base_wf = baseline_index.get((scenario_name, strategy_name), {})

            ra_factory = (
                lambda params, sn=strategy_name, rg=regimes, tv=TARGET_VOL: RegimeAwareStrategy(
                    __import__("strategy_builder", fromlist=["build_strategy"]).build_strategy(sn, __import__("json").dumps(params)),
                    rg,
                    tv,
                )
            )
            ra_wf = run_walk_forward_stress(
                data, strategy_name, strategy_config["param_grid"], strategy_factory=ra_factory
            )

            cm_wf = run_walk_forward_stress(
                data,
                strategy_name,
                strategy_config["param_grid"],
                regime_cost_multipliers=cost_multipliers,
            )

            print(
                f"  [{scenario_name:22s}] {strategy_name:15s}"
                f"  baseline={fmt(base_wf.get('oos_sharpe'))}"
                f"  regime-sized={fmt(ra_wf.get('oos_sharpe'))}"
                f"  cost-mult={fmt(cm_wf.get('oos_sharpe'))}"
            )

            variant_records.append(
                {
                    "scenario": scenario_name,
                    "strategy": strategy_name,
                    "target_vol": TARGET_VOL,
                    "cost_multiplier": COST_MULTIPLIER,
                    "high_vol_regimes": high_vol_labels,
                    "baseline": base_wf,
                    "regime_sized": ra_wf,
                    "cost_multiplied": cm_wf,
                }
            )

    # Summary & falsification verdict
    print(f"\n{'='*80}")
    print("REGIME-AWARE VARIANT SWEEP: SUMMARY & FALSIFICATION VERDICT")
    print(f"{'='*80}")
    print(f"  Criterion: {FALSIFICATION_CRITERION}")
    print()
    print(
        f"  {'Scenario':<22} {'Strategy':<16} {'Baseline Sharpe':>16} "
        f"{'Regime-Sized Sharpe':>20} {'Delta':>10} {'Improved':>9}"
    )
    print(f"  {'-'*80}")

    n_improved = 0
    n_evaluable = 0
    for rec in variant_records:
        sc = rec["scenario"]
        st = rec["strategy"]
        base = rec["baseline"] or {}
        ra = rec["regime_sized"] or {}
        base_sharpe = base.get("oos_sharpe") if isinstance(base, dict) else None
        ra_sharpe = ra.get("oos_sharpe") if isinstance(ra, dict) else None
        improved = bool(
            base_sharpe is not None and ra_sharpe is not None and ra_sharpe > base_sharpe
        )
        if base_sharpe is not None and ra_sharpe is not None:
            n_evaluable += 1
            if improved:
                n_improved += 1
        delta = ra_sharpe - base_sharpe if (base_sharpe is not None and ra_sharpe is not None) else None
        print(
            f"  {sc:<22} {st:<16} {fmt(base_sharpe):>16} "
            f"{fmt(ra_sharpe):>20} {fmt(delta):>10} {str(improved):>9}"
        )

    criterion_passed = n_improved >= 1
    verdict = (
        "NOT FALSIFIED (criterion passed)"
        if criterion_passed
        else "FALSIFIED (null confirmed as generalizable)"
    )
    print()
    print(f"  Evaluable combinations: {n_evaluable}")
    print(f"  Combinations where regime-sizing improved OOS Sharpe: {n_improved}")
    print(f"  Criterion PASSED: {criterion_passed}")
    print(f"  VERDICT: {verdict}")
    print()
    if criterion_passed:
        print("  At least one combination showed a genuine OOS Sharpe improvement.")
        print("  The null result does NOT generalize universally.")
    else:
        print("  No combination showed an OOS Sharpe improvement.")
        print("  The null result is confirmed as generalizable across the suite.")

    ext_path = EXAMPLES_DIR / "adversarial_stress_test_regime_aware_extended.json"
    extended = {
        "falsification_criterion": FALSIFICATION_CRITERION,
        "target_vol": TARGET_VOL,
        "cost_multiplier": COST_MULTIPLIER,
        "criterion_passed": criterion_passed,
        "n_improved": n_improved,
        "n_evaluable": n_evaluable,
        "verdict": verdict,
        "variants": variant_records,
    }
    with open(ext_path, "w") as f:
        json.dump(extended, f, indent=2, default=str)
    print(f"\nExtended variant results saved to: {ext_path}")
    return extended


if __name__ == "__main__":
    main()
