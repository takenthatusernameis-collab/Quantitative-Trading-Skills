#!/usr/bin/env python3
"""End-to-end regression guard for --point-in-time-strict CLI mode.

Verifies that run_backtest.py with --validate-point-in-time --point-in-time-strict
completes successfully on clean single-asset data (no false PIT violations for
legitimate close[t]-based strategies), and that the PIT result is surfaced in the
metrics output.

This is the CLI-level negative control complementing the unit-level positive
controls in test_data_loader.py (which confirm that next-period / look-ahead
signals are detected and rejected by validate_point_in_time).

Offline, committed fixtures only; no live network.
"""
import json
import subprocess
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILLS_DIR / "scripts"

DATA = SKILLS_DIR / "assets" / "example_data" / "real_market_data" / "AAPL.csv"


def _run_backtest(extra_args):
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "run_backtest.py"),
        "--data", str(DATA),
        "--strategy", "sma_crossover",
        "--commission", "0.0002",
        "--slippage", "0.0001",
        "--train-frac", "0.6",
        "--val-frac", "0.2",
        "--test-frac", "0.2",
        "--run-split", "test",
        "--validate-point-in-time",
    ] + extra_args
    return subprocess.run(cmd, cwd=str(SCRIPTS_DIR), capture_output=True, text=True)


def test_point_in_time_strict_passes_on_clean_data():
    """Legitimate close[t]-based sma_crossover must pass PIT strict mode."""
    result = _run_backtest(["--point-in-time-strict"])
    assert result.returncode == 0, (
        f"PIT strict mode aborted on clean data (exit {result.returncode})\n"
        f"stdout:\n{result.stdout[-2000:]}\nstderr:\n{result.stderr[-2000:]}"
    )
    assert "Point-in-time validation passed" in result.stdout, (
        f"PIT validation result not surfaced in CLI output:\n{result.stdout[-2000:]}"
    )


def test_point_in_time_validation_result_in_summary():
    """The PIT result must be recorded in tear_sheet_summary.json when --validate-point-in-time is used."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        result = _run_backtest(["--output", str(tmpdir_path / "results")])
        assert result.returncode == 0, (
            f"backtest failed (exit {result.returncode})\n"
            f"stderr:\n{result.stderr[-2000:]}"
        )
        summary_path = tmpdir_path / "results" / "tear_sheet_summary.json"
        assert summary_path.is_file(), "tear_sheet_summary.json not written"
        summary = json.loads(summary_path.read_text())
        pit = summary.get("point_in_time_validation")
        assert pit is not None, "point_in_time_validation missing from tear sheet summary"
        assert pit.get("passed") is True, f"PIT did not pass: {pit}"
        assert pit.get("violations") == [], f"unexpected PIT violations: {pit.get('violations')}"


if __name__ == "__main__":
    test_point_in_time_strict_passes_on_clean_data()
    print("PASS  test_point_in_time_strict_passes_on_clean_data")
    test_point_in_time_validation_result_in_summary()
    print("PASS  test_point_in_time_validation_result_in_summary")
    print("OK")
