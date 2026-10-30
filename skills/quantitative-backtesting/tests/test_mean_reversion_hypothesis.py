#!/usr/bin/env python3
"""
Regression tests for a falsifiable mean-reversion hypothesis using run_backtest.py.
"""

import contextlib
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILLS_DIR / "scripts"
EXAMPLES_DIR = SKILLS_DIR / "examples"
ASSETS_DIR = SKILLS_DIR / "assets" / "example_data"
REAL_MARKET_DIR = ASSETS_DIR / "real_market_data"

sys.path.insert(0, str(EXAMPLES_DIR))

import numpy as np  # noqa: E402
from mean_reversion_hypothesis import (  # noqa: E402
    COMMISSION,
    COST_SWEEP_LEVELS,
    run_cost_sweep,
    run_hypothesis_test,
)


def test_mean_reversion_hypothesis_example_exists():
    example_path = EXAMPLES_DIR / "mean_reversion_hypothesis.py"
    assert example_path.exists(), f"Missing {example_path}"
    content = example_path.read_text()
    assert "FALSIFICATION" in content
    assert "train" in content.lower() and "test" in content.lower()


def test_run_backtest_bollinger_produces_results():
    data_path = ASSETS_DIR / "sample_ohlcv.csv"
    bench_path = ASSETS_DIR / "sample_benchmark.csv"
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "run_backtest.py"),
            "--data", str(data_path),
            "--strategy", "bollinger_bands",
            "--symbol", "SPY",
            "--params", '{"period": 20, "std_dev": 2.0}',
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


def test_hypothesis_example_runs_successfully():
    example_path = EXAMPLES_DIR / "mean_reversion_hypothesis.py"
    cmd = [sys.executable, str(example_path)]
    result = subprocess.run(cmd, cwd=str(SKILLS_DIR.parent.parent), capture_output=True, text=True)
    assert result.returncode == 0, f"Failed: {result.stderr}\n{result.stdout}"
    assert "VERDICT" in result.stdout
    assert "SUPPORTED" in result.stdout or "NOT SUPPORTED" in result.stdout


def test_mean_reversion_cost_sensitivity_sweep():
    """The cost-sensitivity sweep runs across all ascending levels and pins
    the honest directional claim: higher per-trade costs never improve net
    out-of-sample Sharpe or total return. The advertised setting is the
    middle rung of the sweep."""
    data_path = ASSETS_DIR / "sample_ohlcv.csv"
    import io, contextlib
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_cost_sweep(data_path)

    assert len(rows) == len(COST_SWEEP_LEVELS), (
        f"expected {len(COST_SWEEP_LEVELS)} cost levels, got {len(rows)}"
    )
    # Levels recorded in ascending cost order.
    assert [r["commission_bps"] for r in rows] == [c * 10_000 for c, _ in COST_SWEEP_LEVELS], (
        "cost sweep levels are not recorded in ascending order"
    )
    assert rows[0]["commission_bps"] == 0.0 and rows[0]["slippage_bps"] == 0.0, (
        "first cost sweep level must be frictionless"
    )
    # The advertised setting is the middle rung.
    advertised = next(r for r in rows if r["commission_bps"] == COMMISSION * 10_000)
    assert advertised is rows[2], (
        "the advertised cost level is not the middle rung of the sweep"
    )
    # Each row carries an explicit per-level verdict with failing criteria.
    for r in rows:
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert isinstance(r["criteria"], list) and len(r["criteria"]) == 2
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])
    # Monotonic degradation: higher costs never improve net Sharpe or return.
    for key in ("sharpe_ratio", "total_return"):
        values = [r[key] for r in rows]
        assert all(v is not None and np.isfinite(v) for v in values), (
            f"{key} is missing or non-finite at one or more cost levels: {values}"
        )
        for prev, curr in zip(values, values[1:]):
            assert curr <= prev + 1e-12, (
                f"{key} does not degrade monotonically with cost: {prev} -> {curr}"
            )


def test_hypothesis_reports_its_bias_controls_on_real_market_data():
    """The methodology banner reports the run's ACTUAL bias controls on real
    market data, rather than silently printing None.

    The bias-control fields (train_val_test_split, point_in_time_validation) are
    carried by the tear sheet SUMMARY, not by metrics.json: metrics.json is the
    performance artifact and has no split or PIT block. A hypothesis example
    that reads only metrics.json therefore printed
    "Point-in-time validation: None" on real data -- a false negative about the
    methodology controls, because the run's own summary shows point-in-time
    validation passed and the split was disjoint and chronological.

    This is a regression guard on the example's summary merge: the banner must
    name the split sizes, the chronological/disjoint audit, and a passing
    point-in-time validation on a real-market run. The verdict itself
    (SUPPORTED / NOT SUPPORTED) is not asserted -- both are valid scientific
    outcomes. Offline, committed fixtures only.
    """
    assert (REAL_MARKET_DIR / "MSFT.csv").exists(), "MSFT fixture missing"
    assert (REAL_MARKET_DIR / "GOOGL.csv").exists(), "GOOGL fixture missing"

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        shutil.copyfile(REAL_MARKET_DIR / "MSFT.csv", d / "sample_ohlcv.csv")
        shutil.copyfile(REAL_MARKET_DIR / "GOOGL.csv", d / "sample_benchmark.csv")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            run_hypothesis_test(d / "sample_ohlcv.csv")
        out = buffer.getvalue()

    assert "Split sizes (train/val/test):" in out
    assert "Chronological: True, Disjoint: True" in out, (
        "the banner must report the split-separation audit on real market data"
    )
    assert "Point-in-time validation: True" in out, (
        "the banner must report that point-in-time validation passed on real "
        "market data (a None here is a false negative, not a finding)"
    )


def test_hypothesis_runs_on_msft_googl_real_window():
    """Real-market falsification run on the committed MSFT / GOOGL pair.

    MSFT is the strategy asset (Bollinger Bands mean reversion) and GOOGL is
    the buy-and-hold benchmark. The example's own pre-registered falsification
    machinery (chronological 0.6/0.2/0.2 train/val/test, point-in-time
    validation, run_backtest.py CLI, per-criterion pass/fail and an explicit
    verdict) runs on committed real-market fixtures.

    The verdict itself (SUPPORTED / NOT SUPPORTED) is NOT asserted -- both are
    valid scientific outcomes. The test guards the structure and executability
    of the methodology on real market data: a determinate verdict, consistent
    per-criterion reporting, and the methodology banner reporting the actual
    bias controls. Offline, committed fixtures only; no claim is made about
    any security or market.
    """
    assert (REAL_MARKET_DIR / "MSFT.csv").exists(), "MSFT fixture missing"
    assert (REAL_MARKET_DIR / "GOOGL.csv").exists(), "GOOGL fixture missing"

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        shutil.copyfile(REAL_MARKET_DIR / "MSFT.csv", d / "sample_ohlcv.csv")
        shutil.copyfile(REAL_MARKET_DIR / "GOOGL.csv", d / "sample_benchmark.csv")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_hypothesis_test(d / "sample_ohlcv.csv")
        out = buffer.getvalue()

    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["all_pass"] in (True, False)
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")
    assert len(result["criteria"]) == 2
    assert {c["name"] for c in result["criteria"]} == {
        "oos_sharpe_gt_zero",
        "oos_total_return_positive",
    }
    assert "VERDICT:" in out
    assert "Chronological: True, Disjoint: True" in out
    assert "Point-in-time validation: True" in out


if __name__ == "__main__":
    test_mean_reversion_hypothesis_example_exists()
    test_run_backtest_bollinger_produces_results()
    test_hypothesis_example_runs_successfully()
    test_mean_reversion_cost_sensitivity_sweep()
    test_hypothesis_reports_its_bias_controls_on_real_market_data()
    test_hypothesis_runs_on_msft_googl_real_window()
    print("All tests passed")
