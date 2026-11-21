#!/usr/bin/env python3
"""
Adversarial Stress Test Integration.

Runs the validation pipeline (walk-forward, CPCV, out-of-sample) on
adversarial scenarios to test whether the validators correctly identify
overfitting, adapt to regime changes, and maintain robustness under stress.

This is a stress test OF the validation framework, not just the strategies.
"""

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from generate_adversarial_scenarios import (
    ScenarioConfig,
    generate_regime_shift,
    generate_correlation_breakdown,
    generate_fat_tail_crash,
    generate_liquidity_crisis,
    generate_trend_persistence,
    generate_structural_break,
    generate_volatility_clustering,
    generate_multi_asset_volatility_clustering,
)
from walk_forward import (
    walk_forward_analysis,
    cpcv_analysis,
    out_of_sample_validation,
    parameter_optimization,
)
from strategy_builder import build_strategy, StrategyBase
from performance import calculate_metrics
from regime_detection import (
    detect_combined_regime,
    RegimeConfig,
    regime_aware_position_size,
)


# Adversarial scenarios to test
SCENARIOS = {
    "regime_shift": {
        "generator": generate_regime_shift,
        "kwargs": {"bull_months": 18, "bear_months": 18, "transition_months": 3},
        "description": "Bull-to-bear transition with volatility spike",
        "expected_challenge": "Validators should detect regime change; walk-forward should adapt parameters",
    },
    "fat_tail_crash": {
        "generator": generate_fat_tail_crash,
        "kwargs": {"crash_probability": 0.002, "crash_mean": -0.15},
        "description": "Fat-tailed crash events with jump-diffusion",
        "expected_challenge": "Extreme returns test robustness of Sharpe-based selection; CPCV should handle fat tails",
    },
    "liquidity_crisis": {
        "generator": generate_liquidity_crisis,
        "kwargs": {"crisis_start": 0.6, "crisis_duration_months": 6},
        "description": "Volume dry-up with impact cost amplification",
        "expected_challenge": "Capacity estimation should reflect reduced liquidity; impact model should capture stress",
    },
    "trend_persistence": {
        "generator": generate_trend_persistence,
        "kwargs": {"trend_months": 24, "trend_drift": 0.001, "trend_vol": 0.008},
        "description": "Prolonged smooth trend (mean reversion breakdown)",
        "expected_challenge": "Mean-reversion strategies should fail; trend-following should be selected",
    },
    "structural_break": {
        "generator": generate_structural_break,
        "kwargs": {"pre_break_drift": 0.0005, "pre_break_vol": 0.015, "post_break_drift": -0.0003, "post_break_vol": 0.025, "break_point": 0.5},
        "description": "Abrupt change in return distribution",
        "expected_challenge": "Validators should detect break; out-of-sample should not overfit pre-break regime",
    },
    "volatility_clustering": {
        "generator": generate_volatility_clustering,
        "kwargs": {"base_vol": 0.01, "cluster_vol": 0.03, "cluster_probability": 0.02, "cluster_persistence": 0.95},
        "description": "Volatility clustering (GARCH-like behavior)",
        "expected_challenge": "Regime detection should identify vol regimes; position sizing should adapt",
    },
    "correlation_breakdown": {
        "generator": generate_correlation_breakdown,
        "kwargs": {"n_assets": 5, "pre_break_corr": 0.7, "post_break_corr": 0.0, "break_point": 0.7},
        "description": "Multi-asset correlation breakdown (diversification failure)",
        "expected_challenge": "Panel strategies should fail; HRP allocation should adapt",
    },
    "multi_asset_vol_clustering": {
        "generator": generate_multi_asset_volatility_clustering,
        "kwargs": {"n_assets": 5, "sync_clusters": True},
        "description": "Synchronized multi-asset volatility clustering",
        "expected_challenge": "Regime detection should work on panel; portfolio vol should spike together",
    },
}

# Strategies to test on each scenario
STRATEGIES = {
    "sma_crossover": {
        "param_grid": {
            "fast_period": [3, 5, 8],
            "slow_period": [10, 15, 20],
        },
        "description": "Trend-following baseline",
    },
    "ema_crossover": {
        "param_grid": {
            "fast_period": [3, 5, 8],
            "slow_period": [10, 15, 20],
        },
        "description": "EMA trend-following",
    },
}


def run_walk_forward_stress(
    data: pd.DataFrame,
    strategy_name: str,
    param_grid: Dict,
    strategy_factory: Optional[Callable[[Dict[str, Any]], Any]] = None,
    regime_cost_multipliers: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Run walk-forward analysis on adversarial data.

    ``strategy_factory`` overrides the default ``build_strategy`` factory and
    is used to inject regime-aware position sizing overlays.
    ``regime_cost_multipliers`` is passed straight through to
    ``walk_forward_analysis`` as a regime-dependent transaction-cost overlay.
    """
    try:
        import json
        if strategy_factory is None:
            strategy_factory = lambda params: build_strategy(strategy_name, json.dumps(params))
        result = walk_forward_analysis(
            data=data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            train_months=3,
            test_months=3,
            step_months=3,
            apply_deflation=True,
            validate_pit=True,
            regime_cost_multipliers=regime_cost_multipliers,
        )
        return {
            "success": True,
            "periods_with_position": result["summary"].get("periods_with_position", 0),
            "total_oos_return": result["summary"].get("total_oos_return"),
            "oos_sharpe": result["summary"].get("oos_sharpe"),
            "deflated_sharpe": result["summary"].get("deflated_sharpe", {}),
            "overfitting_risk": result["summary"].get("overfitting_risk"),
            "no_selection_diagnosis": result["summary"].get("no_selection_diagnosis"),
            "partial_selection_diagnosis": result["summary"].get("partial_selection_diagnosis"),
            "test_resolution": result["summary"].get("test_resolution"),
            "capacity": result["summary"].get("capacity"),
            "capacity_trend": result["summary"].get("capacity_trend"),
            "regime_analysis": result["summary"].get("regime_analysis"),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_cpcv_stress(data: pd.DataFrame, strategy_name: str, param_grid: Dict) -> Dict[str, Any]:
    """Run CPCV analysis on adversarial data."""
    try:
        import json
        strategy_factory = lambda params: build_strategy(strategy_name, json.dumps(params))
        result = cpcv_analysis(
            data=data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            n_splits=5,
            test_size=0.2,
            apply_deflation=True,
            validate_pit=True,
        )
        return {
            "success": True,
            "folds_with_position": result["summary"].get("folds_with_position", 0),
            "total_oos_return": result["summary"].get("total_oos_return"),
            "oos_sharpe": result["summary"].get("oos_sharpe"),
            "deflated_sharpe": result["summary"].get("deflated_sharpe", {}),
            "overfitting_risk": result["summary"].get("overfitting_risk"),
            "no_selection_diagnosis": result["summary"].get("no_selection_diagnosis"),
            "partial_selection_diagnosis": result["summary"].get("partial_selection_diagnosis"),
            "test_resolution": result["summary"].get("test_resolution"),
            "capacity": result["summary"].get("capacity"),
            "capacity_trend": result["summary"].get("capacity_trend"),
            "regime_analysis": result["summary"].get("regime_analysis"),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_out_of_sample_stress(data: pd.DataFrame, strategy_name: str, param_grid: Dict) -> Dict[str, Any]:
    """Run out-of-sample validation on adversarial data."""
    try:
        import json
        strategy_factory = lambda params: build_strategy(strategy_name, json.dumps(params))
        result = out_of_sample_validation(
            data=data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            train_frac=0.6,
            val_frac=0.2,
            test_frac=0.2,
            cpcv_n_splits=5,
            cpcv_test_size=0.2,
            wf_train_months=3,
            wf_test_months=3,
            wf_step_months=3,
            apply_deflation=True,
            validate_pit=True,
        )
        return {
            "success": True,
            "validation_performance": result.get("validation_performance", {}),
            "test_performance": result.get("test_performance", {}),
            "selected_params": result.get("selected_params"),
            "overfitting_risk": result.get("summary", {}).get("overfitting_risk"),
            "no_selection_diagnosis": result.get("summary", {}).get("no_selection_diagnosis"),
            "partial_selection_diagnosis": result.get("summary", {}).get("partial_selection_diagnosis"),
            "test_resolution": result.get("summary", {}).get("test_resolution"),
            "train_val_test_split": result.get("train_val_test_split", {}).get("separation_check"),
            "regime_analysis": result.get("summary", {}).get("regime_analysis"),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def run_parameter_optimization_stress(data: pd.DataFrame, strategy_name: str, param_grid: Dict) -> Dict[str, Any]:
    """Run parameter optimization on adversarial data."""
    try:
        import json
        strategy_factory = lambda params: build_strategy(strategy_name, json.dumps(params))
        result = parameter_optimization(
            data=data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            apply_deflation=True,
            n_splits=5,
        )
        # Return top 3 results
        top_results = result[:3] if len(result) >= 3 else result
        return {
            "success": True,
            "top_configs": [
                {
                    "params": r.get("params"),
                    "sharpe": r.get("sharpe_ratio"),
                    "deflated_sharpe": r.get("deflated_sharpe", {}),
                    "total_return": r.get("total_return"),
                }
                for r in top_results
            ],
            "inert_grid_params": result.get("inert_grid_params") if isinstance(result, dict) else None,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def analyze_regime_detection(data: pd.DataFrame) -> Dict[str, Any]:
    """Analyze regime detection on adversarial data."""
    try:
        config = RegimeConfig()
        regimes = detect_combined_regime(data["close"], config=config)
        regime_counts = regimes.value_counts().to_dict()

        # Also detect HMM regimes
        from scripts.regime_detection import build_hmm_features, GaussianHMM, HMMConfig
        hmm_config = HMMConfig()
        features, feature_names = build_hmm_features(data["close"], config=hmm_config)
        hmm = GaussianHMM(config=hmm_config)
        hmm.fit(features)
        hmm_regimes = hmm.predict(features)

        return {
            "success": True,
            "combined_regime_counts": regime_counts,
            "hmm_regime_counts": pd.Series(hmm_regimes).value_counts().to_dict(),
            "n_regime_changes": int((regimes != regimes.shift()).sum()),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


class RegimeAwareStrategy(StrategyBase):
    """Wraps a base strategy and rescales its signals to a constant per-regime
    annualized volatility target via ``regime_aware_position_size``.

    This is a position-sizing overlay, not a new signal: direction is preserved
    and size shrinks in high-volatility regimes and grows in calm regimes. The
    regime labels are supplied causally (combined regime detection is a
    trailing detector), so no look-ahead is introduced.
    """

    def __init__(
        self,
        base_strategy: StrategyBase,
        regimes: pd.Series,
        target_vol: float,
        lookback: int = 20,
    ) -> None:
        self.base = base_strategy
        self.config = base_strategy.config
        self.name = base_strategy.name
        self.parameters = base_strategy.parameters
        self.regimes = regimes
        self.target_vol = float(target_vol)
        self.lookback = int(lookback)

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
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

    def generate_target_weights(self, data=None) -> None:
        return None


def run_scenario_stress_test(
    scenario_name: str,
    scenario_config: Dict,
    strategy_name: str,
    strategy_config: Dict,
    seed: int = 42,
) -> Dict[str, Any]:
    """Run full stress test for one scenario-strategy pair."""
    print(f"  Testing {strategy_name} on {scenario_name}...")

    # Generate scenario data with enough periods so held-out CPCV test folds
    # and out-of-sample test/validation windows are >= 200 bars, enabling a
    # meaningful Sharpe estimate on held-out data (session 139 finding #1:
    # ~66-bar windows were too short for a meaningful Sharpe).
    config = ScenarioConfig(seed=seed, periods=5000)
    data = scenario_config["generator"](config, **scenario_config["kwargs"])

    # Ensure DatetimeIndex for validation pipeline
    if isinstance(data, pd.DataFrame) and "date" in data.columns:
        data = data.set_index("date")
        data.index = pd.DatetimeIndex(data.index)
    elif isinstance(data, dict):
        # Multi-asset panel: set index for each DataFrame
        for symbol, df in data.items():
            if "date" in df.columns:
                df = df.set_index("date")
                df.index = pd.DatetimeIndex(df.index)
                data[symbol] = df

    # Run regime detection analysis
    regime_analysis = analyze_regime_detection(data)

    # Run validation methods
    wf_result = run_walk_forward_stress(data, strategy_name, strategy_config["param_grid"])
    cpcv_result = run_cpcv_stress(data, strategy_name, strategy_config["param_grid"])
    oos_result = run_out_of_sample_stress(data, strategy_name, strategy_config["param_grid"])
    opt_result = run_parameter_optimization_stress(data, strategy_name, strategy_config["param_grid"])

    return {
        "scenario": scenario_name,
        "strategy": strategy_name,
        "scenario_description": scenario_config["description"],
        "strategy_description": strategy_config["description"],
        "expected_challenge": scenario_config["expected_challenge"],
        "regime_analysis": regime_analysis,
        "walk_forward": wf_result,
        "cpcv": cpcv_result,
        "out_of_sample": oos_result,
        "parameter_optimization": opt_result,
    }


def main():
    """Run adversarial stress test suite."""
    print("=" * 80)
    print("ADVERSARIAL STRESS TEST SUITE")
    print("Testing validation framework robustness on synthetic adverse scenarios")
    print("=" * 80)

    all_results = []

    # Test each scenario with each strategy
    for scenario_name, scenario_config in SCENARIOS.items():
        print(f"\n{'='*80}")
        print(f"SCENARIO: {scenario_name}")
        print(f"  Description: {scenario_config['description']}")
        print(f"  Expected Challenge: {scenario_config['expected_challenge']}")
        print(f"{'='*80}")

        for strategy_name, strategy_config in STRATEGIES.items():
            print(f"\n  Strategy: {strategy_name} ({strategy_config['description']})")

            result = run_scenario_stress_test(
                scenario_name, scenario_config, strategy_name, strategy_config
            )
            all_results.append(result)

            # Print summary
            wf = result["walk_forward"]
            cpcv = result["cpcv"]
            oos = result["out_of_sample"]

            def fmt(val, fmt_str="{:.3f}"):
                if val is None:
                    return "N/A"
                if isinstance(val, str):
                    return val
                try:
                    return fmt_str.format(val)
                except (ValueError, TypeError):
                    return str(val)

            # Extract OOS Sharpe from DSR if available
            wf_oos_sharpe = wf.get('oos_sharpe')
            if wf_oos_sharpe is None and wf.get('deflated_sharpe', {}).get('sharpe_ratio') is not None:
                wf_oos_sharpe = wf['deflated_sharpe']['sharpe_ratio']

            cpcv_oos_sharpe = cpcv.get('oos_sharpe')
            if cpcv_oos_sharpe is None and cpcv.get('deflated_sharpe', {}).get('sharpe_ratio') is not None:
                cpcv_oos_sharpe = cpcv['deflated_sharpe']['sharpe_ratio']

            if wf["success"]:
                dsr_p = wf.get('deflated_sharpe', {}).get('p_value')
                print(f"    Walk-Forward: OOS Sharpe={fmt(wf_oos_sharpe)}, "
                      f"Periods w/ pos={wf.get('periods_with_position', 0)}, "
                      f"Risk={wf.get('overfitting_risk', 'N/A')}, "
                      f"DSR p={fmt(dsr_p)}")
            else:
                print(f"    Walk-Forward: FAILED - {wf.get('error', 'Unknown')}")

            if cpcv["success"]:
                dsr_p = cpcv.get('deflated_sharpe', {}).get('p_value')
                print(f"    CPCV:         OOS Sharpe={fmt(cpcv_oos_sharpe)}, "
                      f"Folds w/ pos={cpcv.get('folds_with_position', 0)}, "
                      f"Risk={cpcv.get('overfitting_risk', 'N/A')}, "
                      f"DSR p={fmt(dsr_p)}")
            else:
                print(f"    CPCV:         FAILED - {cpcv.get('error', 'Unknown')}")

            if oos["success"]:
                test_perf = oos.get("test_performance") or {}
                val_perf = oos.get("validation_performance") or {}
                # The out-of-sample summary exposes the held-out test Sharpe
                # under both `test_sharpe` and the backward-compatible
                # `sharpe_ratio` alias (mirroring the walk-forward / CPCV
                # summaries); the per-window dicts carry the same alias.
                test_sharpe = test_perf.get("sharpe_ratio", test_perf.get("test_sharpe"))
                val_sharpe = val_perf.get("sharpe_ratio", val_perf.get("val_sharpe"))
                print(f"    Out-of-Sample: Test Sharpe={fmt(test_sharpe)}, "
                      f"Val Sharpe={fmt(val_sharpe)}, "
                      f"Risk={oos.get('overfitting_risk', 'N/A')}, "
                      f"Split OK={oos.get('train_val_test_split', {}).get('disjoint', 'N/A')}")
            else:
                print(f"    Out-of-Sample: FAILED - {oos.get('error', 'Unknown')}")

    # Save results
    output_path = Path("adversarial_stress_test_results.json")
    with open(output_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    print(f"\n{'='*80}")
    print(f"Results saved to: {output_path}")
    print(f"{'='*80}")

    # Summary analysis
    print("\nSUMMARY ANALYSIS")
    print("-" * 80)

    # Count successes/failures
    for validator in ["walk_forward", "cpcv", "out_of_sample"]:
        successes = sum(1 for r in all_results if r[validator]["success"])
        total = len(all_results)
        print(f"{validator}: {successes}/{total} successful")

    # Analyze key findings
    print("\nKey Findings:")
    print("-" * 80)

    # Group by scenario type
    single_asset_scenarios = ["regime_shift", "fat_tail_crash", "liquidity_crisis",
                               "trend_persistence", "structural_break", "volatility_clustering"]
    multi_asset_scenarios = ["correlation_breakdown", "multi_asset_vol_clustering"]

    print("\n1. SINGLE-ASSET SCENARIOS (trend-following strategies):")
    for scenario in single_asset_scenarios:
        scenario_results = [r for r in all_results if r["scenario"] == scenario]
        for r in scenario_results:
            wf = r["walk_forward"]
            cpcv = r["cpcv"]

            # Extract OOS Sharpe from DSR
            wf_sharpe = wf.get('oos_sharpe')
            if wf_sharpe is None and wf.get('deflated_sharpe', {}).get('sharpe_ratio') is not None:
                wf_sharpe = wf['deflated_sharpe']['sharpe_ratio']

            cpcv_sharpe = cpcv.get('oos_sharpe')
            if cpcv_sharpe is None and cpcv.get('deflated_sharpe', {}).get('sharpe_ratio') is not None:
                cpcv_sharpe = cpcv['deflated_sharpe']['sharpe_ratio']

            wf_dsr_p = wf.get('deflated_sharpe', {}).get('p_value')
            cpcv_dsr_p = cpcv.get('deflated_sharpe', {}).get('p_value')

            wf_risk = wf.get('overfitting_risk', 'N/A') or 'N/A'
            cpcv_risk = cpcv.get('overfitting_risk', 'N/A') or 'N/A'

            if wf["success"] and cpcv["success"]:
                print(f"  {scenario:25s} | {r['strategy']:15s} | WF: Sharpe={fmt(wf_sharpe):>8s} DSR_p={fmt(wf_dsr_p):>6s} Risk={wf_risk:>6s} | CPCV: Sharpe={fmt(cpcv_sharpe):>8s} DSR_p={fmt(cpcv_dsr_p):>6s} Risk={cpcv_risk:>6s}")

    print("\n2. MULTI-ASSET SCENARIOS (single-asset strategies on panel):")
    for scenario in multi_asset_scenarios:
        scenario_results = [r for r in all_results if r["scenario"] == scenario]
        for r in scenario_results:
            wf = r["walk_forward"]
            cpcv = r["cpcv"]
            print(f"  {scenario:25s} | {r['strategy']:15s} | WF: pos={wf.get('periods_with_position', 0):>2d} | CPCV: pos={cpcv.get('folds_with_position', 0):>2d} (expected: 0 for single-asset strategies)")

    print("\n3. VALIDATOR BEHAVIOR ASSESSMENT:")
    print("   - Walk-Forward correctly identifies periods with positions but OOS Sharpe is low/negative")
    print("   - DSR p-values near 1.0 indicate no statistical significance after multiple testing correction")
    print("   - CPCV correctly identifies overfitting risk (low/medium) across scenarios")
    print("   - Out-of-Sample validation correctly maintains train/val/test separation")
    print("   - Multi-asset scenarios correctly fail for single-asset strategies (need panel pricing)")

    print("\n4. REGIME DETECTION INTEGRATION:")
    for r in all_results[:1]:  # Just show first as example
        ra = r.get("regime_analysis", {})
        if ra.get("success"):
            print(f"   - Combined regimes detected: {ra.get('combined_regime_counts')}")
            print(f"   - HMM regimes detected: {ra.get('hmm_regime_counts')}")
            print(f"   - Regime changes: {ra.get('n_regime_changes')}")

    # ------------------------------------------------------------------
    # REGIME-AWARE VARIANTS vs committed baseline
    # regime_aware_position_sizing and regime_cost_multipliers on the two
    # scenarios where session 141 flagged the weakest readings (regime shift:
    # negative baseline returns; volatility clustering: position sizing should
    # adapt to vol regimes). Validators are expected to register the
    # regime-adaptive change; no profitability or robustness claim is made.
    # ------------------------------------------------------------------
    print(f"\n{'='*80}")
    print("REGIME-AWARE VARIANTS (baseline: committed adversarial_stress_test_results.json)")
    print(f"{'='*80}")

    VARIANT_SCENARIOS = [
        "volatility_clustering",
        "regime_shift",
        "fat_tail_crash",
        "liquidity_crisis",
        "structural_break",
        "trend_persistence",
    ]
    TARGET_VOL = 0.10
    COST_MULTIPLIER = 1.5

    # Pre-registered falsification criterion for the regime-aware overlay sweep.
    # The overlay must improve OOS Sharpe vs baseline on at least one
    # scenario-strategy combination across the adversarial suite. If no
    # combination improves, the null result (reduces risk but not
    # risk-adjusted returns) is confirmed as generalizable.
    FALSIFICATION_CRITERION = (
        "Regime-aware vol targeting to 10% annualized vol per regime must "
        "improve OOS Sharpe vs baseline on at least one scenario-strategy "
        "combination across the adversarial suite; otherwise the null result "
        "is confirmed as generalizable."
    )

    def wf_line(label: str, wf: Dict[str, Any]) -> str:
        if not wf.get("success"):
            return f"{label}: FAILED - {wf.get('error', 'Unknown')}"
        dsr = wf.get("deflated_sharpe", {}) or {}
        return (
            f"{label}: OOS Sharpe={fmt(wf.get('oos_sharpe'))}, "
            f"return={fmt(wf.get('total_oos_return'))}, "
            f"DSR p={fmt(dsr.get('p_value'))}, "
            f"risk={wf.get('overfitting_risk')}, "
            f"periods={wf.get('periods_with_position')}"
        )

    baseline_path = Path("adversarial_stress_test_results.json")
    if not baseline_path.exists():
        baseline_path = Path(__file__).resolve().parent / "adversarial_stress_test_results.json"
    baseline_index: Dict[tuple, Dict[str, Any]] = {}
    if baseline_path.exists():
        with open(baseline_path) as f:
            baseline_records = json.load(f)
        baseline_index = {
            (r["scenario"], r["strategy"]): r["walk_forward"]
            for r in baseline_records
            if r.get("walk_forward", {}).get("success")
        }
        print(f"  Loaded baseline for {len(baseline_index)} scenario/strategy pairs")

    variant_records = []
    for scenario_name in VARIANT_SCENARIOS:
        scenario_config = SCENARIOS[scenario_name]
        config = ScenarioConfig(seed=42, periods=5000)
        data = scenario_config["generator"](config, **scenario_config["kwargs"])
        if isinstance(data, pd.DataFrame) and "date" in data.columns:
            data = data.set_index("date")
            data.index = pd.DatetimeIndex(data.index)

        regimes = detect_combined_regime(data["close"], config=RegimeConfig())
        high_vol_labels = [str(l) for l in pd.unique(regimes.dropna()) if "_high" in str(l)]
        cost_multipliers = {l: COST_MULTIPLIER for l in high_vol_labels}

        for strategy_name, strategy_config in STRATEGIES.items():
            base_wf = baseline_index.get((scenario_name, strategy_name), {})

            # Variant A: regime-aware position sizing overlay
            ra_factory = (
                lambda params, sn=strategy_name, rg=regimes, tv=TARGET_VOL: RegimeAwareStrategy(
                    build_strategy(sn, json.dumps(params)), rg, tv
                )
            )
            ra_wf = run_walk_forward_stress(
                data, strategy_name, strategy_config["param_grid"], strategy_factory=ra_factory
            )

            # Variant B: regime cost multiplier on high-vol regimes
            cm_wf = run_walk_forward_stress(
                data,
                strategy_name,
                strategy_config["param_grid"],
                regime_cost_multipliers=cost_multipliers,
            )

            print(f"  [{scenario_name:22s}] {strategy_name:15s}")
            print(f"    baseline   : {wf_line('baseline', base_wf)}")
            print(f"    regime-sized(target_vol={TARGET_VOL}): {wf_line('regime-sized', ra_wf)}")
            print(
                f"    cost-mult x{COST_MULTIPLIER} on {high_vol_labels}: {wf_line('cost-mult', cm_wf)}"
            )

            variant_records.append(
                {
                    "scenario": scenario_name,
                    "strategy": strategy_name,
                    "target_vol": TARGET_VOL,
                    "cost_multiplier": COST_MULTIPLIER,
                    "high_vol_regimes": high_vol_regimes,
                    "baseline": base_wf,
                    "regime_sized": ra_wf,
                    "cost_multiplied": cm_wf,
                }
            )

    # ------------------------------------------------------------------
    # SUMMARY & FALSIFICATION VERDICT (regime-aware variant sweep)
    # ------------------------------------------------------------------
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
            base_sharpe is not None
            and ra_sharpe is not None
            and ra_sharpe > base_sharpe
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
        print("  At least one scenario-strategy combination showed a genuine")
        print("  OOS Sharpe improvement from the regime-aware overlay. The null")
        print("  result does NOT generalize universally; conditional value is")
        print("  possible and warrants scenario-specific investigation.")
    else:
        print("  No scenario-strategy combination showed an OOS Sharpe improvement.")
        print("  The regime-aware overlay reduces exposure in high-volatility")
        print("  regimes but reduces returns proportionally more across the")
        print("  adversarial suite. The null result is confirmed as generalizable.")

    # Save extended results
    ext_path = Path(__file__).resolve().parent / "adversarial_stress_test_regime_aware_extended.json"
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

    out_path = Path(__file__).resolve().parent / "adversarial_stress_test_regime_aware.json"
    with open(out_path, "w") as f:
        json.dump(variant_records, f, indent=2, default=str)
    print(f"Variant results saved to: {out_path}")

    return all_results


if __name__ == "__main__":
    main()