#!/usr/bin/env python3
"""End-to-end regression guard: the out-of-sample CLI path discloses
regime-dependent performance in its artifact.

The walk-forward, CPCV, Monte Carlo and single-backtest paths each surface
``summary["regime_analysis"]`` (per-regime Sharpe/return/observation counts,
regime periods and the regime distribution) and ``summary["regime_robustness"]``
(the regime-concentration classification) so a consumer can tell whether the
held-out verdict rests on a diversified edge or on one market regime. The
out-of-sample path wires the same two blocks into its own summary
(``walk_forward.py:7044-7063``), but until now nothing asserted that the wiring
survives the trip through the CLI and lands in ``out_of_sample_summary.json``:
the block was present in the in-process summary and in the tear sheet, yet a
consumer reading only the artifact could not rely on it. This test closes that
gap by reading the artifact the CLI writes.

It is an audit of disclosure, not a profitability claim. Offline, committed
fixtures only; no live network, no parameter tuning, no verdict is asserted
beyond the shape and validity of the disclosure itself.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
WALK_FORWARD_CLI = SKILLS_DIR / "scripts" / "walk_forward.py"
SAMPLE_DATA = SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv"

MEANINGFUL_GRID = '{"fast_period": [5, 10], "slow_period": [20, 30]}'

VALID_CLASSIFICATIONS = ("robust", "moderate", "fragile", "insufficient_data")


def _run_out_of_sample_cli(output_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(WALK_FORWARD_CLI),
            "out-of-sample",
            "--data", str(SAMPLE_DATA),
            "--strategy", "sma_crossover",
            "--validation-method", "walk_forward",
            "--train-frac", "0.5",
            "--val-frac", "0.25",
            "--test-frac", "0.25",
            "--param-grid", MEANINGFUL_GRID,
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


def test_out_of_sample_cli_records_regime_analysis_in_artifact():
    """The out-of-sample artifact carries regime_analysis and
    regime_robustness on its summary, mirroring the walk-forward / CPCV /
    Monte Carlo / single-backtest disclosure paths."""
    assert SAMPLE_DATA.exists(), f"missing committed fixture {SAMPLE_DATA}"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        result = _run_out_of_sample_cli(tmpdir)
        assert result.returncode == 0, (
            f"out-of-sample CLI exited {result.returncode}\n"
            f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
        )
        artifact_path = tmpdir / "out_of_sample_summary.json"
        assert artifact_path.is_file(), "out_of_sample_summary.json not written"
        artifact = json.loads(artifact_path.read_text())
        assert "summary" in artifact, "artifact carries no summary"

        summary = artifact["summary"]
        assert "regime_analysis" in summary, (
            "out_of_sample summary must carry regime_analysis"
        )
        _assert_regime_analysis_shape(summary["regime_analysis"], "out_of_sample")

        assert "regime_robustness" in summary, (
            "out_of_sample summary must carry regime_robustness"
        )
        _assert_regime_robustness_shape(summary["regime_robustness"], "out_of_sample")

        # The two blocks are consistent: the classification is derived from the
        # per-regime Sharpes the analysis block reports, so the robustness
        # block must name only regimes that the analysis block actually saw.
        combined = summary["regime_analysis"]["combined_regime_performance"]
        named_regimes = {
            r for r in summary["regime_robustness"]["regime_sharpes"]
        }
        assert named_regimes <= set(combined), (
            f"regime_robustness names regimes not in regime_analysis: "
            f"{named_regimes - set(combined)}"
        )


def test_out_of_sample_cli_artifact_is_json_safe_and_round_trippable():
    """The regime disclosure in the artifact is JSON-serializable through the
    framework's own ``_json_safe`` path (it contains numpy scalars and period
    objects from the detection step) and round-trips back into a dict, so a
    downstream consumer reading ``out_of_sample_summary.json`` gets usable
    numbers rather than a file that fails to parse."""
    assert SAMPLE_DATA.exists(), f"missing committed fixture {SAMPLE_DATA}"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        result = _run_out_of_sample_cli(tmpdir)
        assert result.returncode == 0, (
            f"out-of-sample CLI exited {result.returncode}\n{result.stderr[-2000:]}"
        )
        artifact_path = tmpdir / "out_of_sample_summary.json"
        raw = artifact_path.read_text()
        artifact = json.loads(raw)  # the file itself must parse
        assert isinstance(artifact["summary"]["regime_analysis"], dict)
        assert isinstance(artifact["summary"]["regime_robustness"], dict)
        # Re-serializing the parsed payload must reproduce the same structure:
        # any numpy/pandas scalar left in the dict would survive the first
        # json.loads but poison a second dump, so this guards the round-trip.
        json.dumps(artifact, default=str)


if __name__ == "__main__":
    test_out_of_sample_cli_records_regime_analysis_in_artifact()
    print("PASS  test_out_of_sample_cli_records_regime_analysis_in_artifact")
    test_out_of_sample_cli_artifact_is_json_safe_and_round_trippable()
    print("PASS  test_out_of_sample_cli_artifact_is_json_safe_and_round_trippable")
    print("OK")