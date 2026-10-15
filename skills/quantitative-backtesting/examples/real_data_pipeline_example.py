#!/usr/bin/env python3
"""
Real-data integration pipeline example.

Demonstrates the complete quantitative research workflow end-to-end:
- Synthetic multi-asset data generation (no network access)
- Point-in-time validation and survivorship bias detection
- Walk-forward/CPCV validation with multiple benchmarks
- Deflated alpha multiple-testing correction
- Tear sheet generation with cross-benchmark analysis

All data comes from the built-in sample data generator - no external
network access required. The pipeline mirrors production patterns
for real market data workflows.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

# Add scripts to path
scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from data_loader import (
    load_data,
    validate_data,
    validate_point_in_time,
    detect_survivorship_bias,
    load_multi_symbol,
)
from generate_sample_data import generate_multi_asset_data
from performance import calculate_metrics
from walk_forward import (
    cpcv_analysis,
    _benchmark_list_alpha_correction,
    deflated_alpha_ratio,
    _annualization_factor,
)


def generate_synthetic_universe(output_dir: Path, n_assets: int = 10, periods: int = 756) -> dict:
    """
    Generate a synthetic multi-asset universe with realistic characteristics.

    Returns a dict with:
    - 'data_paths': dict mapping symbols to CSV paths
    - 'benchmark_paths': list of benchmark CSV paths
    - 'provenance': list of provenance records
    """
    print("1. GENERATING SYNTHETIC MULTI-ASSET UNIVERSE")
    print("-" * 60)

    # Use the existing generator to create multi-asset data
    data_dict = generate_multi_asset_data(
        n_assets=n_assets,
        periods=periods,
        seed=42,
    )

    data_paths = {}
    provenance_records = []

    for symbol, df in data_dict.items():
        csv_path = output_dir / f"{symbol}.csv"
        df.to_csv(csv_path, index=False)
        data_paths[symbol] = str(csv_path)

        # Load with provenance tracking
        loaded_df, prov = load_data(str(csv_path), symbol=symbol, return_provenance=True)
        provenance_records.append(prov.to_dict())
        print(f"  ✓ {symbol}: {len(loaded_df)} periods, checksum={prov.checksum[:12]}...")

    print(f"  Total assets: {len(data_paths)}")
    print()

    # Select two assets as benchmarks (first two symbols)
    symbols = list(data_paths.keys())
    benchmark_paths = [data_paths[symbols[0]], data_paths[symbols[1]]]

    return {
        "data_paths": data_paths,
        "benchmark_paths": benchmark_paths,
        "provenance": provenance_records,
        "all_symbols": symbols,
    }


def run_pit_validation(data_paths: dict) -> dict:
    """Run point-in-time validation on all assets."""
    print("2. POINT-IN-TIME VALIDATION")
    print("-" * 60)

    pit_results = {}
    for symbol, path in data_paths.items():
        df = load_data(path, symbol=symbol)
        # Test with SMA lookback windows (20, 50)
        result = validate_point_in_time(df, lookback_windows=[20, 50])
        pit_results[symbol] = result
        status = "PASSED" if result["passed"] else "FAILED"
        print(f"  {symbol}: {status} (violations: {len(result['violations'])}, warnings: {len(result['warnings'])})")

    print()
    return pit_results


def run_survivorship_detection(data_paths: dict) -> dict:
    """Run survivorship bias detection on the universe."""
    print("3. SURVIVORSHIP BIAS DETECTION")
    print("-" * 60)

    # Load all data into a dict for detection
    data_dict = {}
    for symbol, path in data_paths.items():
        df = load_data(path, symbol=symbol)
        data_dict[symbol] = df

    result = detect_survivorship_bias(data_dict)
    print(f"  Bias score: {result['bias_score']:.3f}")
    print(f"  Surviving symbols: {result['surviving_symbols']}")
    print(f"  Entered: {len(result['entered_symbols'])}")
    print(f"  Exited: {len(result['exited_symbols'])}")
    print()

    return result


def run_cpcv_validation(data_path: str, benchmark_paths: list, output_dir: Path) -> dict:
    """
    Run CPCV validation with multiple benchmarks via the Python API.

    This mirrors the CLI pipeline but uses the direct function call
    for programmatic access and result inspection.
    """
    print("4. CPCV VALIDATION WITH MULTIPLE BENCHMARKS")
    print("-" * 60)

    # Load strategy data
    data_df = load_data(data_path, symbol="ASSET_0")

    # Load benchmarks
    benchmark_dfs = [load_data(p, symbol=f"BENCH_{i}") for i, p in enumerate(benchmark_paths)]

    # Run CPCV analysis
    results = cpcv_analysis(
        data=data_df,
        strategy_factory=lambda params: __import__("strategy_builder", fromlist=["build_strategy"]).build_strategy(
            "sma_crossover", json.dumps(params)
        ),
        param_grid={"fast_period": [5, 10, 15], "slow_period": [20, 30, 40]},
        n_splits=5,
        test_size=0.2,
        benchmark=benchmark_dfs,  # List of benchmarks triggers deflated alpha
        total_return_benchmark=False,
        benchmark_commission=0.001,
        benchmark_slippage=0.001,
        benchmark_cost_is_periodic=True,
    )

    # Print key results
    summary = results["summary"]
    print(f"  Best params: {results.get('best_params')}")
    print(f"  Selected params: {results.get('selected_params')}")

    if "deflated_alpha" in summary:
        da = summary["deflated_alpha"]
        print(f"  Deflated Alpha Ratio: {da['deflated_alpha_ratio']:.4f}")
        print(f"  DAR p-value: {da['p_value']:.4f}")
        print(f"  Expected max alpha (luck): {da['expected_max_alpha']:.4%}")
        print(f"  N benchmarks: {da['n_benchmarks']}")

    if "benchmark_metrics" in summary:
        print(f"  Per-benchmark metrics: {len(summary['benchmark_metrics'])} benchmarks")
        for i, bm in enumerate(summary["benchmark_metrics"]):
            print(f"    Benchmark {i}: alpha={bm.get('alpha', 'N/A'):.4%}, "
                  f"p={bm.get('alpha_pvalue', 'N/A'):.4f}, "
                  f"DAR={bm.get('deflated_alpha', 'N/A'):.4f}")

    # Save results
    results_path = output_dir / "cpcv_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Results saved to: {results_path}")

    print()
    return results


def run_cli_cpcv_validation(data_path: str, benchmark_paths: list, output_dir: Path) -> dict:
    """
    Run CPCV validation via CLI (mirrors production usage).
    """
    print("5. CLI CPCV VALIDATION (PRODUCTION PATTERN)")
    print("-" * 60)

    cmd = [
        sys.executable,
        str(scripts_dir / "walk_forward.py"),
        "cpcv",
        "--data", data_path,
        "--benchmark", *benchmark_paths,
        "--strategy", "sma_crossover",
        "--param-grid", '{"fast_period": [5, 10, 15], "slow_period": [20, 30, 40]}',
        "--output", str(output_dir),
        "--benchmark-commission", "0.001",
        "--benchmark-slippage", "0.001",
        "--benchmark-cost-is-periodic",
        "--n-splits", "5",
        "--test-size", "0.2",
    ]

    print(f"  Running: {' '.join(cmd[:5])} ...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        print(f"  ⚠ CLI exited with code {result.returncode}")
        print(f"  stderr: {result.stderr[-500:]}")
        return {}

    # Load and display results
    summary_path = output_dir / "cpcv_summary.json"
    if summary_path.exists():
        with open(summary_path) as f:
            payload = json.load(f)
        summary = payload.get("summary", {})
        print(f"  ✓ CLI CPCV completed successfully")
        if "deflated_alpha" in summary:
            da = summary["deflated_alpha"]
            print(f"  Deflated Alpha Ratio: {da['deflated_alpha_ratio']:.4f}")
            print(f"  DAR p-value: {da['p_value']:.4f}")
            print(f"  N benchmarks: {da['n_benchmarks']}")
        if "benchmark_metrics" in summary:
            print(f"  Per-benchmark metrics: {len(summary['benchmark_metrics'])}")
    else:
        print(f"  ⚠ No summary file found at {summary_path}")

    print()
    return payload if summary_path.exists() else {}


def run_cli_monte_carlo(data_path: str, benchmark_paths: list, output_dir: Path) -> dict:
    """
    Run Monte Carlo validation via CLI with multiple benchmarks.
    """
    print("6. CLI MONTE CARLO VALIDATION (PRODUCTION PATTERN)")
    print("-" * 60)

    cmd = [
        sys.executable,
        str(scripts_dir / "walk_forward.py"),
        "monte-carlo",
        "--data", data_path,
        "--benchmark", *benchmark_paths,
        "--strategy", "sma_crossover",
        "--param-grid", '{"fast_period": [5, 10], "slow_period": [20, 30]}',
        "--output", str(output_dir),
        "--benchmark-commission", "0.001",
        "--benchmark-slippage", "0.001",
        "--benchmark-cost-is-periodic",
        "--n-simulations", "100",
    ]

    print(f"  Running: {' '.join(cmd[:5])} ...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

    if result.returncode != 0:
        print(f"  ⚠ CLI exited with code {result.returncode}")
        print(f"  stderr: {result.stderr[-500:]}")
        return {}

    # Load and display results
    results_path = output_dir / "monte_carlo_results.json"
    if results_path.exists():
        with open(results_path) as f:
            payload = json.load(f)
        summary = payload.get("summary", {})
        print(f"  ✓ CLI Monte Carlo completed successfully")
        if "deflated_alpha" in summary:
            da = summary["deflated_alpha"]
            print(f"  Deflated Alpha Ratio: {da['deflated_alpha_ratio']:.4f}")
            print(f"  DAR p-value: {da['p_value']:.4f}")
            print(f"  N benchmarks: {da['n_benchmarks']}")
        if "benchmark_metrics" in summary:
            print(f"  Per-benchmark metrics: {len(summary['benchmark_metrics'])}")

        # Check tear sheet
        ts_path = output_dir / "tear_sheet.html"
        if ts_path.exists():
            with open(ts_path) as f:
                html = f.read()
            if "Multiple-Testing Correction (Deflated Alpha)" in html:
                print(f"  ✓ Tear sheet renders Deflated Alpha section")
            if "Per-Benchmark Comparison" in html:
                print(f"  ✓ Tear sheet renders Per-Benchmark Comparison")
    else:
        print(f"  ⚠ No results file found at {results_path}")

    print()
    return payload if results_path.exists() else {}


def demonstrate_deflated_alpha_directly(strategy_returns: pd.Series, benchmark_returns_list: list) -> dict:
    """
    Demonstrate direct usage of the deflated alpha machinery.
    """
    print("7. DIRECT DEFLATED ALPHA COMPUTATION")
    print("-" * 60)

    # Compute trial alphas from each benchmark
    trial_alphas = []
    ann_factor = _annualization_factor(strategy_returns.index)

    for i, bench_rets in enumerate(benchmark_returns_list):
        from walk_forward import _benchmark_stats
        # Align returns
        aligned = pd.concat([strategy_returns, bench_rets], axis=1, join="inner").dropna()
        if len(aligned) < 30:
            continue
        strat_aligned = aligned.iloc[:, 0]
        bench_aligned = aligned.iloc[:, 1]
        stats = _benchmark_stats(strat_aligned, bench_aligned, ann_factor)
        if "alpha" in stats and np.isfinite(stats["alpha"]):
            trial_alphas.append(stats["alpha"])
            print(f"  Benchmark {i} alpha: {stats['alpha']:.4%}")

    # Compute deflated alpha with trial alphas
    da_result = deflated_alpha_ratio(
        alpha=trial_alphas[0] if trial_alphas else 0.0,
        returns=strategy_returns,
        benchmark_returns=benchmark_returns_list[0],
        n_benchmarks=len(trial_alphas),
        trial_alphas=trial_alphas,
    )

    print(f"  Trial alphas: {[f'{a:.4%}' for a in trial_alphas]}")
    print(f"  Deflated Alpha Ratio: {da_result['deflated_alpha_ratio']:.4f}")
    print(f"  DAR p-value: {da_result['p_value']:.4f}")
    print(f"  Expected max alpha: {da_result['expected_max_alpha']:.4%}")
    print(f"  Z-score: {da_result['z_score']:.3f}")
    print(f"  N benchmarks: {da_result['n_benchmarks']}")
    print(f"  Observations: {da_result['n_observations']}")
    print(f"  Skewness/Kurtosis: {da_result['skewness']:.3f}/{da_result['kurtosis']:.3f}")
    print()

    return da_result


def main():
    print("=" * 80)
    print("QUANTITATIVE RESEARCH: REAL-DATA INTEGRATION PIPELINE")
    print("=" * 80)
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Step 1: Generate synthetic universe
        universe = generate_synthetic_universe(tmpdir, n_assets=8, periods=756)
        data_paths = universe["data_paths"]
        benchmark_paths = universe["benchmark_paths"]
        symbols = universe["all_symbols"]

        # Step 2: PIT validation
        pit_results = run_pit_validation(data_paths)

        # Step 3: Survivorship detection
        surv_result = run_survivorship_detection(data_paths)

        # Step 4: CPCV via Python API (programmatic access)
        strategy_data_path = data_paths[symbols[0]]  # Use first asset as strategy
        cpcv_results = run_cpcv_validation(strategy_data_path, benchmark_paths, tmpdir)

        # Step 5: CPCV via CLI (production pattern)
        cli_cpcv_results = run_cli_cpcv_validation(strategy_data_path, benchmark_paths, tmpdir)

        # Step 6: Monte Carlo via CLI (production pattern)
        cli_mc_results = run_cli_monte_carlo(strategy_data_path, benchmark_paths, tmpdir)

        # Step 7: Direct deflated alpha demonstration
        # Load strategy returns for direct computation
        data_df = load_data(strategy_data_path, symbol=symbols[0])
        strat = __import__("strategy_builder", fromlist=["build_strategy"]).build_strategy(
            "sma_crossover", json.dumps({"fast_period": 10, "slow_period": 30})
        )
        signals = strat.generate_signals(data_df)
        positions = signals.shift(1).fillna(0)
        returns = data_df["close"].pct_change().fillna(0)
        strategy_returns = (positions * returns).dropna()

        bench_returns_list = []
        for bp in benchmark_paths:
            bench_df = load_data(bp, symbol=f"BENCH")
            bench_rets = bench_df["close"].pct_change().dropna()
            bench_returns_list.append(bench_rets)

        da_direct = demonstrate_deflated_alpha_directly(strategy_returns, bench_returns_list)

        # Final summary
        print("=" * 80)
        print("PIPELINE COMPLETE - SUMMARY")
        print("=" * 80)
        print(f"Assets generated: {len(data_paths)}")
        print(f"Benchmarks used: {len(benchmark_paths)}")
        print(f"PIT validation: {'All passed' if all(r['passed'] for r in pit_results.values()) else 'Some failed'}")
        print(f"Survivorship bias score: {surv_result['bias_score']:.3f}")
        if "deflated_alpha" in cpcv_results.get("summary", {}):
            da = cpcv_results["summary"]["deflated_alpha"]
            print(f"CPCV Deflated Alpha Ratio: {da['deflated_alpha_ratio']:.4f} (p={da['p_value']:.4f})")
        if "deflated_alpha" in cli_cpcv_results.get("summary", {}):
            da = cli_cpcv_results["summary"]["deflated_alpha"]
            print(f"CLI CPCV Deflated Alpha Ratio: {da['deflated_alpha_ratio']:.4f} (p={da['p_value']:.4f})")
        if "deflated_alpha" in cli_mc_results.get("summary", {}):
            da = cli_mc_results["summary"]["deflated_alpha"]
            print(f"CLI Monte Carlo Deflated Alpha Ratio: {da['deflated_alpha_ratio']:.4f} (p={da['p_value']:.4f})")
        print(f"Direct DAR: {da_direct['deflated_alpha_ratio']:.4f} (p={da_direct['p_value']:.4f})")
        print()
        print("All outputs written to temporary directory (auto-cleaned on exit).")
        print("For persistent outputs, copy files before script exit.")
        print("=" * 80)


if __name__ == "__main__":
    main()