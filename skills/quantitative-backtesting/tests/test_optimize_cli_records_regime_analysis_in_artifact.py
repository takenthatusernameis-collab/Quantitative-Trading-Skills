#!/usr/bin/env python3
"""End-to-end regression guard: the ``optimize`` CLI discloses the
regime profile of its top-ranked parameter combination.

``parameter_optimization`` ranks parameter combinations by in-sample Sharpe
over the full sample. Every other analysis path (walk-forward, CPCV, Monte
Carlo, out-of-sample, single backtest) already discloses regime analysis /
robustness in its artifact, but the optimization ranking did not. A reader of
``parameter_optimization.json`` could not see whether the top-ranked
combination's in-sample edge is concentrated in a single market regime.

This test asserts the disclosure exists, is internally consistent, is
explicitly labelled as an in-sample *selection* (not out-of-sample evidence),
and is written to a separate artifact so the ranked list itself stays a plain
list. It also asserts the disclosure is a measurement: requesting it changes
no ranking number.

Audit of disclosure only, not a profitability claim. Offline, committed
fixtures only; no live network, no parameter tuning, no verdict asserted
beyond the shape and validity of the disclosure itself.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILLS_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from walk_forward import _make_strategy_factory, parameter_optimization  # noqa: E402

WALK_FORWARD_CLI = SCRIPTS_DIR / "walk_forward.py"
SAMPLE_DATA = SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv"
SAMPLE_PANEL = SKILLS_DIR / "assets" / "example_data" / "sample_panel_ohlcv.csv"

MEANINGFUL_GRID = {"fast_period": [5, 10], "slow_period": [20, 30]}

VALID_CLASSIFICATIONS = ("robust", "moderate", "fragile", "insufficient_data")


def _run_optimize_cli(output_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(WALK_FORWARD_CLI),
            "optimize",
            "--data", str(SAMPLE_DATA),
            "--strategy", "sma_crossover",
            "--param-grid", json.dumps(MEANINGFUL_GRID),
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


def test_optimize_cli_records_regime_analysis_in_artifact():
    """parameter_optimization_regime.json carries the top combo's regime
    profile, labelled as an in-sample selection."""
    assert SAMPLE_DATA.exists(), f"missing committed fixture {SAMPLE_DATA}"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        result = _run_optimize_cli(tmpdir)
        assert result.returncode == 0, (
            f"optimize CLI exited {result.returncode}\n"
            f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
        )

        regime_path = tmpdir / "parameter_optimization_regime.json"
        assert regime_path.is_file(), "parameter_optimization_regime.json not written"
        report = json.loads(regime_path.read_text())

        # Explicit scope label: this is an in-sample selection, not OOS.
        assert report.get("scope") == "in_sample_parameter_selection", (
            f"unexpected scope {report.get('scope')!r}"
        )
        assert "not out-of-sample evidence" in report.get("message", ""), (
            "regime record must state it is not out-of-sample evidence"
        )

        _assert_regime_analysis_shape(report["regime_analysis"], "optimize")

        rr = report["regime_robustness"]
        assert isinstance(rr, dict), "regime_robustness must be a dict"
        assert rr.get("regime_robustness") in VALID_CLASSIFICATIONS, (
            f"unexpected classification {rr.get('regime_robustness')!r}"
        )

        combined = report["regime_analysis"]["combined_regime_performance"]
        named_regimes = set(rr.get("regime_sharpes") or {})
        assert named_regimes <= set(combined), (
            f"regime_robustness names regimes not in regime_analysis: "
            f"{named_regimes - set(combined)}"
        )

        # The disclosure describes the same combination the ranking puts first.
        ranking = json.loads((tmpdir / "parameter_optimization.json").read_text())
        assert isinstance(ranking, list) and ranking, "ranking artifact missing"
        assert report["top_params"] == ranking[0]["params"], (
            "regime record's top_params does not match the ranked first row"
        )
        assert report["top_sharpe_ratio"] == ranking[0]["sharpe_ratio"], (
            "regime record's top_sharpe_ratio does not match the ranked first row"
        )


def test_optimize_ranking_artifact_stays_a_plain_ranked_list():
    """The regime disclosure is a separate record; the ranked list gains no
    regime keys, so existing consumers of parameter_optimization.json are
    unaffected."""
    assert SAMPLE_DATA.exists(), f"missing committed fixture {SAMPLE_DATA}"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        result = _run_optimize_cli(tmpdir)
        assert result.returncode == 0, result.stderr[-2000:]
        ranking = json.loads((tmpdir / "parameter_optimization.json").read_text())
        assert isinstance(ranking, list)
        for row in ranking:
            assert "regime_analysis" not in row
            assert "regime_robustness" not in row


def test_optimize_cli_records_regime_for_a_panel():
    """A multi-symbol panel uses the first asset's close for the regime
    profile instead of failing on the (field, symbol) columns."""
    assert SAMPLE_PANEL.exists(), f"missing committed fixture {SAMPLE_PANEL}"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        result = subprocess.run(
            [
                sys.executable,
                str(WALK_FORWARD_CLI),
                "optimize",
                "--data", str(SAMPLE_PANEL),
                "--multi-symbol",
                "--strategy", "cross_sectional_momentum",
                "--param-grid",
                json.dumps({"top_quantile": [0.4], "bottom_quantile": [0.2]}),
                "--output", str(tmpdir),
            ],
            capture_output=True,
            text=True,
            timeout=900,
        )
        assert result.returncode == 0, (
            f"panel optimize CLI exited {result.returncode}\n"
            f"stderr:\n{result.stderr[-3000:]}"
        )
        report = json.loads(
            (tmpdir / "parameter_optimization_regime.json").read_text()
        )
        assert report["scope"] == "in_sample_parameter_selection"
        assert report["regime_error"] is None, (
            f"panel regime disclosure errored: {report['regime_error']}"
        )
        _assert_regime_analysis_shape(report["regime_analysis"], "optimize-panel")
        assert report["regime_robustness"]["regime_robustness"] in VALID_CLASSIFICATIONS


def test_optimize_cli_artifact_is_json_safe_and_round_trippable():
    """The regime record round-trips, so downstream consumers get usable
    parsed numbers (no unhandled numpy/pandas scalars)."""
    assert SAMPLE_DATA.exists(), f"missing committed fixture {SAMPLE_DATA}"
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        result = _run_optimize_cli(tmpdir)
        assert result.returncode == 0, result.stderr[-2000:]
        report = json.loads(
            (tmpdir / "parameter_optimization_regime.json").read_text()
        )
        json.dumps(report, default=str)


def test_requesting_the_regime_report_changes_no_ranking_number():
    """Library-level guard: the disclosure is a measurement. Requesting it
    returns the identical ranking."""
    import pandas as pd

    data = pd.read_csv(SAMPLE_DATA, parse_dates=["date"]).set_index("date")
    factory = _make_strategy_factory("sma_crossover")

    without = parameter_optimization(
        data=data, strategy_factory=factory, param_grid=MEANINGFUL_GRID
    )
    report = {}
    with_report = parameter_optimization(
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
        regime_report=report,
    )
    assert without == with_report, "requesting the regime report moved a number"
    assert report.get("scope") == "in_sample_parameter_selection"
    assert report.get("regime_analysis") is not None


if __name__ == "__main__":
    test_optimize_cli_records_regime_analysis_in_artifact()
    print("PASS  test_optimize_cli_records_regime_analysis_in_artifact")
    test_optimize_ranking_artifact_stays_a_plain_ranked_list()
    print("PASS  test_optimize_ranking_artifact_stays_a_plain_ranked_list")
    test_optimize_cli_records_regime_for_a_panel()
    print("PASS  test_optimize_cli_records_regime_for_a_panel")
    test_optimize_cli_artifact_is_json_safe_and_round_trippable()
    print("PASS  test_optimize_cli_artifact_is_json_safe_and_round_trippable")
    test_requesting_the_regime_report_changes_no_ranking_number()
    print("PASS  test_requesting_the_regime_report_changes_no_ranking_number")
    print("OK")