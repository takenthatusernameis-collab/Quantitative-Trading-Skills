#!/usr/bin/env python3
"""
Falsifiable financial hypothesis test using run_backtest.py CLI.

HYPOTHESIS: A simple SMA crossover trend-following strategy produces
positive out-of-sample risk-adjusted returns (Sharpe > 0) net of 3 bps
round-trip trading costs on the held-out test set.

FALSIFICATION CRITERIA:
1. Out-of-sample Sharpe ratio (net of costs) > 0
2. Out-of-sample total return > 0 (net of costs)
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


HYPOTHESIS = (
    "An SMA-crossover trend-following strategy produces positive "
    "out-of-sample risk-adjusted returns (Sharpe > 0) net of 3 bps "
    "round-trip trading costs on the held-out test set."
)

CRITERIA = [
    ("oos_sharpe_gt_zero", "oos_sharpe > 0 (net of costs)"),
    ("oos_total_return_positive", "oos_total_return > 0 (net of costs)"),
]

COMMISSION = 0.0002
SLIPPAGE = 0.0001

# Cost settings exercised by the cost sweep. The advertised setting is the
# hypothesis's operating assumption; the zero-cost setting is the frictionless
# upper bound. Comparing the two is a regression guard that the advertised
# costs are actually applied by the cost path -- a cost model that silently
# no-ops would produce identical numbers at both settings and fail the sweep.
COST_SWEEP_SETTINGS = [
    ("frictionless (0 bps)", 0.0, 0.0),
    ("advertised (2bp comm + 1bp slip)", COMMISSION, SLIPPAGE),
]


def _fmt_pct(v):
    if v is None:
        return "N/A"
    try:
        return f"{float(v):.2%}"
    except Exception:
        return "N/A"


def _fmt_num(v, nd=4):
    if v is None:
        return "N/A"
    try:
        return f"{float(v):.{nd}f}"
    except Exception:
        return "N/A"


def run_hypothesis_test(data_path, benchmark_path=None):
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    data_path = Path(data_path)
    if benchmark_path is None:
        benchmark_path = data_path.parent / "sample_benchmark.csv"
    benchmark_path = Path(benchmark_path)

    print("=" * 80)
    print("FALSIFIABLE HYPOTHESIS TEST (using run_backtest.py)")
    print("=" * 80)
    print(f"Hypothesis: {HYPOTHESIS}")
    print(f"Trading costs: {COMMISSION*10000:.0f} bps commission + {SLIPPAGE*10000:.0f} bps slippage")
    print(f"Data: {data_path}")
    print(f"Benchmark: {benchmark_path if benchmark_path.exists() else 'None'}")
    print("Split: train/val/test = 0.6/0.2/0.2 (test split only)")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        out_path = tmpdir_path / "metrics.json"
        cmd = [
            sys.executable,
            str(scripts_dir / "run_backtest.py"),
            "--data", str(data_path),
            "--strategy", "sma_crossover",
            "--symbol", "SPY",
            "--params", '{"fast_period": 10, "slow_period": 30}',
            "--commission", str(COMMISSION),
            "--slippage", str(SLIPPAGE),
            "--train-frac", "0.6",
            "--val-frac", "0.2",
            "--test-frac", "0.2",
            "--run-split", "test",
            "--output", str(tmpdir_path / "results"),
            "--validate-point-in-time",
        ]
        if benchmark_path.exists():
            cmd.extend(["--benchmark", str(benchmark_path)])
        
        result = subprocess.run(cmd, cwd=str(scripts_dir), capture_output=True, text=True)
        if result.returncode != 0:
            print("STDOUT:", result.stdout[-800:])
            print("STDERR:", result.stderr[-800:])
            raise RuntimeError(f"run_backtest failed with code {result.returncode}")

        # Look for metrics
        metrics = {}
        candidates = [
            tmpdir_path / "results" / "metrics.json",
            scripts_dir / "results" / "metrics.json",
            Path("results") / "metrics.json",
        ]
        for cand in candidates:
            if cand.exists() and cand.is_file():
                with open(cand) as f:
                    metrics = json.load(f)
                break

    print("\n1. METHODOLOGY CONTROLS")
    split_info = metrics.get("train_val_test_split", {})
    if split_info:
        sep = split_info.get("separation_check", {})
        print(f"  Split sizes (train/val/test): {sep.get('train_size')}/{sep.get('val_size')}/{sep.get('test_size')}")
        print(f"  Chronological: {sep.get('chronological')}, Disjoint: {sep.get('disjoint')}")
    pit = metrics.get("point_in_time_validation", {})
    print(f"  Point-in-time validation: {pit.get('passed')}")
    print(f"  Run split: test only (held-out)")
    print(f"  Commission: {COMMISSION}, Slippage: {SLIPPAGE}")

    print("\n2. OUT-OF-SAMPLE PERFORMANCE (net of costs)")
    print(f"  Total Return: {_fmt_pct(metrics.get('total_return'))}")
    print(f"  Annualized Return: {_fmt_pct(metrics.get('annualized_return'))}")
    print(f"  Sharpe Ratio: {_fmt_num(metrics.get('sharpe_ratio'))}")
    print(f"  Max Drawdown: {_fmt_pct(metrics.get('max_drawdown'))}")
    if metrics.get('benchmark_total_return') is not None:
        print(f"  Benchmark Total Return: {_fmt_pct(metrics.get('benchmark_total_return'))}")
        print(f"  Alpha: {_fmt_pct(metrics.get('alpha'))}")

    print("\n3. FALSIFICATION CRITERIA")
    criterion_results = []
    passes = []
    sharpe = metrics.get('sharpe_ratio')
    ok1 = sharpe is not None and float(sharpe) > 0
    passes.append(ok1)
    criterion_results.append({"name": CRITERIA[0][0], "description": CRITERIA[0][1], "passed": bool(ok1)})
    print(f"  [{'PASS' if ok1 else 'FAIL'}] {CRITERIA[0][0]}: {CRITERIA[0][1]}")
    ret = metrics.get('total_return')
    ok2 = ret is not None and float(ret) > 0
    passes.append(ok2)
    criterion_results.append({"name": CRITERIA[1][0], "description": CRITERIA[1][1], "passed": bool(ok2)})
    print(f"  [{'PASS' if ok2 else 'FAIL'}] {CRITERIA[1][0]}: {CRITERIA[1][1]}")

    all_pass = all(passes)
    verdict = "SUPPORTED" if all_pass else "NOT SUPPORTED"

    print("\n" + "=" * 80)
    print(f"VERDICT: {verdict}")
    print("  SUPPORTED = all falsification criteria passed")
    print("  NOT SUPPORTED = at least one criterion failed (hypothesis falsified)")
    print("=" * 80)

    return {
        "hypothesis": HYPOTHESIS,
        "verdict": verdict,
        "all_pass": all_pass,
        "criteria": criterion_results,
        "metrics": {
            "sharpe_ratio": sharpe,
            "total_return": ret,
            "benchmark_total_return": metrics.get('benchmark_total_return'),
            "alpha": metrics.get('alpha'),
        },
    }


def _run_backtest_metrics(data_path, benchmark_path, commission, slippage, tmpdir_path):
    """Run run_backtest.py at the given cost settings and return parsed metrics."""
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    cmd = [
        sys.executable,
        str(scripts_dir / "run_backtest.py"),
        "--data", str(data_path),
        "--strategy", "sma_crossover",
        "--symbol", "SPY",
        "--params", '{"fast_period": 10, "slow_period": 30}',
        "--commission", str(commission),
        "--slippage", str(slippage),
        "--train-frac", "0.6",
        "--val-frac", "0.2",
        "--test-frac", "0.2",
        "--run-split", "test",
        "--output", str(tmpdir_path / "results"),
        "--validate-point-in-time",
    ]
    if benchmark_path.exists():
        cmd.extend(["--benchmark", str(benchmark_path)])

    result = subprocess.run(cmd, cwd=str(scripts_dir), capture_output=True, text=True)
    if result.returncode != 0:
        print("STDOUT:", result.stdout[-800:])
        print("STDERR:", result.stderr[-800:])
        raise RuntimeError(f"run_backtest failed with code {result.returncode}")

    metrics = {}
    candidates = [
        tmpdir_path / "results" / "metrics.json",
        scripts_dir / "results" / "metrics.json",
        Path("results") / "metrics.json",
    ]
    for cand in candidates:
        if cand.exists() and cand.is_file():
            with open(cand) as f:
                metrics = json.load(f)
            break
    return metrics


def run_cost_sweep(data_path, benchmark_path=None):
    """Compare the hypothesis at its advertised cost setting against the
    frictionless (zero-cost) upper bound.

    This is a regression guard, not a research conclusion: if the advertised
    costs are not actually applied by the cost path, the two settings produce
    identical Sharpe and total return, and the sweep fails. A cost model that
    silently no-ops is the failure mode this check exists to catch.
    """
    data_path = Path(data_path)
    if benchmark_path is None:
        benchmark_path = data_path.parent / "sample_benchmark.csv"
    benchmark_path = Path(benchmark_path)

    print("\n" + "=" * 80)
    print("COST SWEEP: advertised costs vs frictionless upper bound")
    print("=" * 80)

    rows = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        for label, commission, slippage in COST_SWEEP_SETTINGS:
            metrics = _run_backtest_metrics(
                data_path, benchmark_path, commission, slippage, tmpdir_path
            )
            rows.append({
                "label": label,
                "commission": commission,
                "slippage": slippage,
                "sharpe_ratio": metrics.get("sharpe_ratio"),
                "total_return": metrics.get("total_return"),
                "benchmark_total_return": metrics.get("benchmark_total_return"),
                "alpha": metrics.get("alpha"),
            })
            print(
                f"  {label:<34} "
                f"Sharpe={_fmt_num(metrics.get('sharpe_ratio'))}  "
                f"Return={_fmt_pct(metrics.get('total_return'))}  "
                f"Alpha={_fmt_pct(metrics.get('alpha'))}"
            )

    # Regression guard: the frictionless run must beat the costed run on both
    # Sharpe and total return. If costs are not applied, the two rows are
    # identical and this assertion fails.
    frictionless = rows[0]
    costed = rows[-1]
    assert frictionless["commission"] == 0.0 and costed["commission"] == COMMISSION, (
        "cost sweep rows are not the frictionless / advertised pair"
    )
    assert frictionless["sharpe_ratio"] is not None and costed["sharpe_ratio"] is not None
    assert frictionless["sharpe_ratio"] > costed["sharpe_ratio"], (
        "frictionless Sharpe must exceed the costed Sharpe: "
        f"{frictionless['sharpe_ratio']} vs {costed['sharpe_ratio']}"
    )
    assert frictionless["total_return"] is not None and costed["total_return"] is not None
    assert frictionless["total_return"] > costed["total_return"], (
        "frictionless total return must exceed the costed total return: "
        f"{frictionless['total_return']} vs {costed['total_return']}"
    )

    delta_sharpe = costed["sharpe_ratio"] - frictionless["sharpe_ratio"]
    delta_return = costed["total_return"] - frictionless["total_return"]
    print()
    print(
        f"  Cost impact (0 bps -> {COMMISSION*10000:.0f}bp + {SLIPPAGE*10000:.0f}bp): "
        f"Sharpe {frictionless['sharpe_ratio']:.4f} -> {costed['sharpe_ratio']:.4f} "
        f"(Delta {delta_sharpe:+.4f}); "
        f"Return {frictionless['total_return']:.2%} -> {costed['total_return']:.2%} "
        f"(Delta {delta_return:+.2%})"
    )
    print("  Cost path verified live: the advertised costs reduce net performance.")
    print("=" * 80)

    return rows


def main():
    data_path = Path(__file__).resolve().parent.parent / "assets" / "example_data" / "sample_ohlcv.csv"
    run_hypothesis_test(data_path)
    run_cost_sweep(data_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
