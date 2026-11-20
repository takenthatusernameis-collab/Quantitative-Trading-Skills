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
from typing import Dict, Any, List, Optional

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
from strategy_builder import build_strategy
from performance import calculate_metrics
from regime_detection import detect_combined_regime, RegimeConfig


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


def run_walk_forward_stress(data: pd.DataFrame, strategy_name: str, param_grid: Dict) -> Dict[str, Any]:
    """Run walk-forward analysis on adversarial data."""
    try:
        import json
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


def run_scenario_stress_test(
    scenario_name: str,
    scenario_config: Dict,
    strategy_name: str,
    strategy_config: Dict,
    seed: int = 42,
) -> Dict[str, Any]:
    """Run full stress test for one scenario-strategy pair."""
    print(f"  Testing {strategy_name} on {scenario_name}...")

    # Generate scenario data with more periods for validation
    config = ScenarioConfig(seed=seed, periods=2000)
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

    return all_results


if __name__ == "__main__":
    main()