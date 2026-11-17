#!/usr/bin/env python3
"""End-to-end regression guard: the run_backtest CLI discloses
regime-dependent performance in its artifact.

``run_backtest.py`` computes regime analysis/robustness in-process and
``reporting.generate_tear_sheet`` writes them into ``tear_sheet_summary.json``;
in-process coverage exists in ``tests/test_run_backtest.py`` and the reporting
unit tests cover the summary shape, but nothing asserted that the CLI wiring
survives end-to-end into the artifact a consumer reads. This mirrors the
walk-forward/CPCV/Monte Carlo/out-of-sample CLI artifact round-trip tests and
closes that gap for the single-backtest path.

Audit of disclosure only, not a profitability claim. Offline, committed
fixtures only; no live network, no parameter tuning, no verdict asserted beyond
the shape and validity of the disclosure itself.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
RUN_BACKTEST_CLI = SKILLS_DIR / "scripts" / "run_backtest.py"
SAMPLE_DATA = SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv"

VALID_CLASSIFICATIONS = ("robust", "moderate", "fragile", "insufficient_data")


def _run_backtest_cli(output_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(RUN_BACKTEST_CLI),
            "--data", str(SAMPLE_DATA),
            "--strategy", "sma_crossover",
            "--params", '{"fast_period": 10, "slow_period": 30}',
            "--output", str(output_dir),
        ],
        capture_output=True,
        text=True,
        timeout=900,
    )


def _assert_regime_analysis_shape(ra, label):
    assert isinstance(ra, dict), f"{label}: regime_analysis must be a dict, got {type(ra)}"
    for key in (
        "trend_regime_performance",
        "volatility_regime_performance",
        "combined_regime_performance",
        "regime_periods",
        "regime_distribution",
    ):
        assert key in ra, f"{label}: regime_analysis missing {key!r}"


def _assert_regime_robustness_shape(rr, label):
    assert isinstance(rr, dict), f"{label}: regime_robustness must be a dict, got {type(rr)}"
    assert rr.get("regime_robustness") in VALID_CLASSIFICATIONS, (
        f"{label}: unexpected classification {rr.get('regime_robustness')!r}"
    )


def test_run_backtest_cli_records_regime_analysis_in_artifact():
    """tear_sheet_summary.json carries regime_analysis and regime_robustness,
    mirroring the walk-forward/CPCV/Monte Carlo/out-of-sample disclosure paths."""
    assert SAMPLE_DATA.exists(), f"missing committed fixture {SAMPLE_DATA}"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        result = _run_backtest_cli(tmpdir)
        assert result.returncode == 0, (
            f"run_backtest CLI exited {result.returncode}\n"
            f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
        )
        artifact_path = tmpdir / "tear_sheet_summary.json"
        assert artifact_path.is_file(), "tear_sheet_summary.json not written"
        artifact = json.loads(artifact_path.read_text())

        assert "regime_analysis" in artifact, (
            "run_backtest summary must carry regime_analysis"
        )
        _assert_regime_analysis_shape(artifact["regime_analysis"], "run_backtest")

        assert "regime_robustness" in artifact, (
            "run_backtest summary must carry regime_robustness"
        )
        _assert_regime_robustness_shape(artifact["regime_robustness"], "run_backtest")

        combined = artifact["regime_analysis"]["combined_regime_performance"]
        named_regimes = set(artifact["regime_robustness"]["regime_sharpes"])
        assert named_regimes <= set(combined), (
            f"regime_robustness names regimes not in regime_analysis: "
            f"{named_regimes - set(combined)}"
        )


def test_run_backtest_cli_artifact_is_json_safe_and_round_trippable():
    """Regime disclosure in tear_sheet_summary.json is JSON-serializable via the
    framework's _json_safe path and round-trips, so downstream consumers get
    usable parsed numbers (no unhandled numpy/pandas scalars)."""
    assert SAMPLE_DATA.exists(), f"missing committed fixture {SAMPLE_DATA}"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        result = _run_backtest_cli(tmpdir)
        assert result.returncode == 0, (
            f"run_backtest CLI exited {result.returncode}\n{result.stderr[-2000:]}"
        )
        artifact_path = tmpdir / "tear_sheet_summary.json"
        raw = artifact_path.read_text()
        artifact = json.loads(raw)
        assert isinstance(artifact["regime_analysis"], dict)
        assert isinstance(artifact["regime_robustness"], dict)
        json.dumps(artifact, default=str)


if __name__ == "__main__":
    test_run_backtest_cli_records_regime_analysis_in_artifact()
    print("PASS  test_run_backtest_cli_records_regime_analysis_in_artifact")
    test_run_backtest_cli_artifact_is_json_safe_and_round_trippable()
    print("PASS  test_run_backtest_cli_artifact_is_json_safe_and_round_trippable")
    print("OK")
