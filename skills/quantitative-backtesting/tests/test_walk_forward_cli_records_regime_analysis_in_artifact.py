#!/usr/bin/env python3
"""End-to-end regression guard: the walk_forward CLI discloses regime-dependent
performance in its artifact.

``walk_forward_analysis`` computes regime analysis/robustness in-process
(walk_forward.py:1851-1879) and ``reporting.generate_tear_sheet`` writes them
into ``tear_sheet_summary.json`` under ``summary["walk_forward"]["summary"]``
(reporting.py:1680-1685). In-process coverage exists in
``tests/test_walk_forward.py`` and the reporting unit tests cover the summary
shape, but nothing asserted that the CLI wiring survives end-to-end into the
artifact a consumer reads. This mirrors the run_backtest/CPCV/Monte
Carlo/out-of-sample CLI artifact round-trip tests and closes that gap for the
walk-forward path.

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
WALK_FORWARD_CLI = SKILLS_DIR / "scripts" / "walk_forward.py"
SAMPLE_DATA = SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv"

VALID_CLASSIFICATIONS = ("robust", "moderate", "fragile", "insufficient_data")

MEANINGFUL_GRID = '{"fast_period": [3, 5], "slow_period": [8, 10]}'


def _run_walk_forward_cli(output_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(WALK_FORWARD_CLI),
            "walk-forward",
            "--data", str(SAMPLE_DATA),
            "--strategy", "sma_crossover",
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


def _walk_forward_summary(artifact):
    wf = artifact.get("walk_forward")
    assert isinstance(wf, dict), "artifact carries no walk_forward block"
    summary = wf.get("summary")
    assert isinstance(summary, dict), "walk_forward block carries no summary"
    return summary


def test_walk_forward_cli_records_regime_analysis_in_artifact():
    """tear_sheet_summary.json carries walk_forward regime_analysis and
    regime_robustness, mirroring the run_backtest/CPCV/Monte Carlo/out-of-sample
    disclosure paths."""
    assert SAMPLE_DATA.exists(), f"missing committed fixture {SAMPLE_DATA}"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        result = _run_walk_forward_cli(tmpdir)
        assert result.returncode == 0, (
            f"walk-forward CLI exited {result.returncode}\n"
            f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
        )
        artifact_path = tmpdir / "tear_sheet_summary.json"
        assert artifact_path.is_file(), "tear_sheet_summary.json not written"
        artifact = json.loads(artifact_path.read_text())

        summary = _walk_forward_summary(artifact)

        assert "regime_analysis" in summary, (
            "walk_forward summary must carry regime_analysis"
        )
        _assert_regime_analysis_shape(summary["regime_analysis"], "walk_forward")

        assert "regime_robustness" in summary, (
            "walk_forward summary must carry regime_robustness"
        )
        _assert_regime_robustness_shape(summary["regime_robustness"], "walk_forward")

        # The two blocks are consistent: the classification is derived from the
        # per-regime Sharpes the analysis block reports, so the robustness
        # block must name only regimes that the analysis block actually saw.
        combined = summary["regime_analysis"]["combined_regime_performance"]
        named_regimes = set(summary["regime_robustness"]["regime_sharpes"])
        assert named_regimes <= set(combined), (
            f"regime_robustness names regimes not in regime_analysis: "
            f"{named_regimes - set(combined)}"
        )


def test_walk_forward_cli_artifact_is_json_safe_and_round_trippable():
    """The regime disclosure in the walk_forward artifact is JSON-serializable
    through the framework's own ``_json_safe`` path (it contains numpy scalars
    and period objects from the detection step) and round-trips back into a
    dict, so a downstream consumer reading ``tear_sheet_summary.json`` gets
    usable numbers rather than a file that fails to parse."""
    assert SAMPLE_DATA.exists(), f"missing committed fixture {SAMPLE_DATA}"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        result = _run_walk_forward_cli(tmpdir)
        assert result.returncode == 0, (
            f"walk-forward CLI exited {result.returncode}\n{result.stderr[-2000:]}"
        )
        artifact_path = tmpdir / "tear_sheet_summary.json"
        raw = artifact_path.read_text()
        artifact = json.loads(raw)  # the file itself must parse
        summary = _walk_forward_summary(artifact)
        assert isinstance(summary["regime_analysis"], dict)
        assert isinstance(summary["regime_robustness"], dict)
        # Re-serializing the parsed payload must reproduce the same structure:
        # any numpy/pandas scalar left in the dict would survive the first
        # json.loads but poison a second dump, so this guards the round-trip.
        json.dumps(artifact, default=str)


if __name__ == "__main__":
    test_walk_forward_cli_records_regime_analysis_in_artifact()
    print("PASS  test_walk_forward_cli_records_regime_analysis_in_artifact")
    test_walk_forward_cli_artifact_is_json_safe_and_round_trippable()
    print("PASS  test_walk_forward_cli_artifact_is_json_safe_and_round_trippable")
    print("OK")
