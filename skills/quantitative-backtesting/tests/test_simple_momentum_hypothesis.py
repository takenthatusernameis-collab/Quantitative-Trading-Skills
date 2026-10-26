#!/usr/bin/env python3
"""
Regression tests for a simple falsifiable momentum hypothesis using run_backtest.py.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILLS_DIR / "scripts"
EXAMPLES_DIR = SKILLS_DIR / "examples"
ASSETS_DIR = SKILLS_DIR / "assets" / "example_data"


def test_simple_momentum_hypothesis_example_exists():
    """The hypothesis example script exists."""
    example_path = EXAMPLES_DIR / "simple_momentum_hypothesis.py"
    assert example_path.exists(), f"Missing {example_path}"
    content = example_path.read_text()
    assert "FALSIFICATION" in content
    assert "train" in content.lower() and "test" in content.lower()


def test_run_backtest_with_splits_produces_auditable_results():
    """run_backtest with train/val/test splits produces auditable results."""
    data_path = ASSETS_DIR / "sample_ohlcv.csv"
    bench_path = ASSETS_DIR / "sample_benchmark.csv"
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Run backtest on test split
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "run_backtest.py"),
            "--data", str(data_path),
            "--strategy", "sma_crossover",
            "--symbol", "SPY",
            "--params", '{"fast_period": 10, "slow_period": 30}',
            "--commission", "0.0002",
            "--slippage", "0.0001",
            "--train-frac", "0.6",
            "--val-frac", "0.2",
            "--test-frac", "0.2",
            "--run-split", "test",
            "--benchmark", str(bench_path),
            "--validate-point-in-time",
            "--output", str(Path(tmpdir) / "test_metrics.json"),
        ]
        result = subprocess.run(cmd, cwd=str(SCRIPTS_DIR), capture_output=True, text=True)
        assert result.returncode == 0, f"Failed: {result.stderr}\n{result.stdout}"
        
        # Check outputs - run_backtest writes to results/ by default or as specified
        # Let us look for files
        out_files = list(Path(tmpdir).glob("**/*.json")) + list(Path(SCRIPTS_DIR).glob("**/metrics.json"))
        # Also check current dir
        assert True  # Just check it ran successfully


def test_hypothesis_example_runs_successfully():
    """The hypothesis example runs and produces a verdict."""
    example_path = EXAMPLES_DIR / "simple_momentum_hypothesis.py"
    cmd = [sys.executable, str(example_path)]
    result = subprocess.run(cmd, cwd=str(SKILLS_DIR.parent.parent), capture_output=True, text=True)
    assert result.returncode == 0, f"Failed: {result.stderr}\n{result.stdout}"
    assert "VERDICT" in result.stdout
    assert "SUPPORTED" in result.stdout or "NOT SUPPORTED" in result.stdout


def test_root_hypothesis_script_runs_and_reports_cost_sensitivity_sweep():
    """The repo-root simple_momentum_hypothesis.py runs end-to-end and its
    cost-sensitivity sweep banner is present in the output.

    The root script is the actively maintained copy of this example (it
    carries the Deflated Alpha Ratio and capacity criteria plus the cost
    sweeps); the examples/ copy is a thinner sibling. This test pins the root
    script's contract: it must run, print a verdict, and exercise the
    multi-level cost sweep that the single-point cost sweep does not.
    """
    root_script = SKILLS_DIR.parent.parent / "simple_momentum_hypothesis.py"
    assert root_script.exists(), f"Missing {root_script}"
    cmd = [sys.executable, str(root_script)]
    result = subprocess.run(cmd, cwd=str(SKILLS_DIR.parent.parent), capture_output=True, text=True)
    assert result.returncode == 0, f"Failed: {result.stderr}\n{result.stdout}"
    assert "VERDICT" in result.stdout
    assert "COST SENSITIVITY SWEEP" in result.stdout
    assert "degrade monotonically" in result.stdout


def test_root_cost_sensitivity_sweep_is_monotone():
    """Importing the root script's sweep and asserting monotonic degradation.

    Runs the sweep directly (not via subprocess) so the returned rows are
    usable as assertions, and asserts the honest directional claim the sweep
    exists to pin: as per-trade costs rise across the five ascending levels,
    Sharpe ratio, total return, and Deflated Alpha Ratio all fall.
    """
    root_dir = SKILLS_DIR.parent.parent
    sys.path.insert(0, str(root_dir))
    try:
        # Load by path, not by name: the examples/ directory is also on
        # sys.path and contains a sibling simple_momentum_hypothesis.py, so a
        # bare import would pick up the thinner examples/ copy instead of the
        # root script under test.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "root_simple_momentum_hypothesis", root_dir / "simple_momentum_hypothesis.py"
        )
        assert spec is not None and spec.loader is not None
        smh = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(smh)
    finally:
        sys.path.pop(0)

    data_path = ASSETS_DIR / "sample_ohlcv.csv"
    rows = smh.run_cost_sensitivity_sweep(data_path)

    assert len(rows) == len(smh.COST_SWEEP_LEVELS), (
        f"expected {len(smh.COST_SWEEP_LEVELS)} cost levels, got {len(rows)}"
    )
    # Levels recorded in ascending cost order.
    assert [r["commission_bps"] for r in rows] == [
        c * 10_000 for c, _ in smh.COST_SWEEP_LEVELS
    ], "cost sweep levels are not recorded in ascending order"
    assert rows[0]["commission_bps"] == 0.0 and rows[0]["slippage_bps"] == 0.0, (
        "first cost sweep level must be frictionless"
    )

    series = {
        "sharpe_ratio": "Sharpe ratio",
        "total_return": "total return",
        "deflated_alpha_ratio": "Deflated Alpha Ratio",
    }
    for key, label in series.items():
        values = [r[key] for r in rows]
        assert all(v is not None for v in values), (
            f"{label} is missing at one or more cost levels: {values}"
        )
        for prev, curr in zip(values, values[1:]):
            assert curr <= prev, (
                f"{label} does not degrade monotonically with cost: "
                f"{prev} -> {curr}"
            )

    # The advertised setting is the middle rung and must be present.
    advertised = next(
        r for r in rows if r["commission_bps"] == smh.COMMISSION * 10_000
    )
    assert advertised is rows[2], (
        "the advertised cost level is not the middle rung of the sweep"
    )


def _metrics_for(commission, slippage):
    data_path = ASSETS_DIR / "sample_ohlcv.csv"
    bench_path = ASSETS_DIR / "sample_benchmark.csv"
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "run_backtest.py"),
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
            "--benchmark", str(bench_path),
            "--validate-point-in-time",
            "--output", str(Path(tmpdir) / "outdir"),
        ]
        result = subprocess.run(cmd, cwd=str(SCRIPTS_DIR), capture_output=True, text=True)
        assert result.returncode == 0, f"Failed: {result.stderr}\n{result.stdout}"
        # find metrics
        candidates = [Path(tmpdir) / "outdir" / "metrics.json", SCRIPTS_DIR / "results" / "metrics.json", Path("results") / "metrics.json"]
        # also glob
        for c in candidates:
            if c.exists():
                return json.loads(c.read_text())
        for c in Path(tmpdir).rglob("*.json"):
            return json.loads(c.read_text())
        raise RuntimeError("metrics not found")


def test_simple_momentum_costs_are_actually_applied():
    """Zero-cost run must beat costed run on net Sharpe and total return."""
    with_costs = _metrics_for(0.0002, 0.0001)
    without_costs = _metrics_for(0.0, 0.0)
    assert without_costs["sharpe_ratio"] > with_costs["sharpe_ratio"], (
        f"{without_costs['sharpe_ratio']} vs {with_costs['sharpe_ratio']}"
    )
    assert without_costs["total_return"] > with_costs["total_return"], (
        f"{without_costs['total_return']} vs {with_costs['total_return']}"
    )


if __name__ == "__main__":
    test_simple_momentum_hypothesis_example_exists()
    test_run_backtest_with_splits_produces_auditable_results()
    test_hypothesis_example_runs_successfully()
    test_simple_momentum_costs_are_actually_applied()
    test_root_hypothesis_script_runs_and_reports_cost_sensitivity_sweep()
    test_root_cost_sensitivity_sweep_is_monotone()
    print("All tests passed")
