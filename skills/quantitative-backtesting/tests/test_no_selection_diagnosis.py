#!/usr/bin/env python3
"""Regression tests for the "no parameter could be selected" diagnosis.

A run that selects nothing used to be reported as a wall of `null`s:
`best_params_per_fold: [None, ...]`, `total_oos_return: null`,
`avg_param_stability: 0.0` and an "overfitting risk" verdict -- with no
explanation of *why* nothing was selected. On the shipped sample the default
CPCV configuration puts a **5-bar** test window in every fold (the effective
out-of-sample fraction is `test_size / n_splits`, not the fraction the flag
name suggests), which is shorter than the indicator warm-up, so no
combination can take a position and no parameter can be selected.

The out-of-sample path already named its cause. These tests pin that the
standalone CPCV and walk-forward paths now do the same, with the same
vocabulary, in the artifact and in the console:

  * `summary["no_selection_diagnosis"]` records `{cause, message, details}`;
  * the cause is `no_position_in_validation_window` when the windows were
    built but every combination stayed flat, and `no_validation_windows`
    when there was no window at all;
  * the message names the window length and a remedy that uses the flags
    the path's own subcommand actually accepts;
  * a run that *does* select a parameter carries no diagnosis;
  * the overfitting-risk verdict is "not applicable" when nothing could be
    selected (it is not "low" or "high"), and unchanged when it could;
  * the diagnosis is a measurement: it changes no number.

Run with: python3 skills/quantitative-backtesting/tests/test_no_selection_diagnosis.py
No third-party test framework is required; uses only the standard library.
"""

import json
import re
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import (  # noqa: E402
    _make_strategy_factory,
    cpcv_analysis,
    out_of_sample_validation,
    overfitting_check,
    walk_forward_analysis,
)

SAMPLE_DATA = SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv"
WALK_FORWARD_CLI = SKILLS_DIR / "scripts" / "walk_forward.py"

# A grid the strategy actually reads (`sma_crossover` uses `fast_period` and
# `slow_period`).
MEANINGFUL_GRID = {"fast_period": [5, 10], "slow_period": [20, 30]}
# A grid whose slowest lookback is longer than any out-of-sample window of
# the shipped sample, so no combination can take a position in any window.
TOO_SLOW_GRID = {"fast_period": [5], "slow_period": [200]}


def _load_sample() -> pd.DataFrame:
    return pd.read_csv(SAMPLE_DATA, parse_dates=["date"]).set_index("date")


def _run_cli(args):
    return subprocess.run(
        [sys.executable, str(WALK_FORWARD_CLI)] + args,
        capture_output=True,
        text=True,
        timeout=1800,
    )


def _subcommand_flags(subcommand: str) -> set:
    """The long flags a subcommand actually accepts."""
    proc = subprocess.run(
        [sys.executable, str(WALK_FORWARD_CLI), subcommand, "--help"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return set(re.findall(r"--[a-z0-9][a-z0-9-]*", proc.stdout))


def _flags_in(message: str) -> set:
    return set(re.findall(r"--[a-z0-9][a-z0-9-]*", message))


# ---------------------------------------------------------------------------
# The diagnosis on the standalone paths
# ---------------------------------------------------------------------------

def test_cpcv_analysis_records_the_no_selection_diagnosis():
    """The default CPCV run says why no fold could select a parameter."""
    data = _load_sample()

    results = cpcv_analysis(
        data=data,
        strategy_factory=_make_strategy_factory("sma_crossover"),
        param_grid=MEANINGFUL_GRID,
    )

    # Nothing was selected: the artifact must explain itself.
    assert results["best_params_per_fold"] == [None] * 10
    diagnosis = results["summary"]["no_selection_diagnosis"]
    assert diagnosis["cause"] == "no_position_in_validation_window"
    assert diagnosis["details"]["n_validation_windows"] == 10
    assert diagnosis["details"]["n_windows_with_selected_params"] == 0
    assert diagnosis["details"]["validation_method"] == "cpcv"
    assert diagnosis["details"]["analysis_path"] == "cpcv"
    # The window length is the fact that explains the failure.
    assert diagnosis["details"]["validation_window_bars"] == [5] * 10
    assert "5 bars" in diagnosis["message"]


def test_cpcv_diagnosis_names_the_effective_out_of_sample_fraction():
    """The remedy states the effective fraction, which is the root cause."""
    data = _load_sample()

    results = cpcv_analysis(
        data=data,
        strategy_factory=_make_strategy_factory("sma_crossover"),
        param_grid=MEANINGFUL_GRID,
    )
    message = results["summary"]["no_selection_diagnosis"]["message"]

    # The test size is the fraction of each group, so the effective
    # out-of-sample fraction is test_size / n_splits = 0.1 / 10 = 1%.
    assert "--test-size" in message
    assert "--n-splits" in message
    assert "0.1/10" in message
    assert "fraction of each group" in message


def test_walk_forward_analysis_records_the_no_selection_diagnosis():
    """The walk-forward path says why no period could select a parameter."""
    data = _load_sample()

    results = walk_forward_analysis(
        data=data,
        strategy_factory=_make_strategy_factory("sma_crossover"),
        param_grid=TOO_SLOW_GRID,
    )

    assert results["best_params_per_period"] == [None] * 3
    diagnosis = results["summary"]["no_selection_diagnosis"]
    assert diagnosis["cause"] == "no_position_in_validation_window"
    assert diagnosis["details"]["n_validation_windows"] == 3
    assert diagnosis["details"]["n_windows_with_selected_params"] == 0
    assert diagnosis["details"]["analysis_path"] == "walk_forward"
    # The remedy for the walk-forward path names its own flag.
    assert "--test-months" in diagnosis["message"]


def test_the_remedy_names_flags_the_path_actually_accepts():
    """A remedy that names an unusable flag is not a remedy."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    cpcv_message = cpcv_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
    )["summary"]["no_selection_diagnosis"]["message"]
    cpcv_flags = _subcommand_flags("cpcv")
    for flag in _flags_in(cpcv_message):
        assert flag in cpcv_flags, (
            f"{flag} is named in the CPCV remedy but the `cpcv` subcommand "
            f"does not accept it"
        )

    wf_message = walk_forward_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=TOO_SLOW_GRID,
    )["summary"]["no_selection_diagnosis"]["message"]
    wf_flags = _subcommand_flags("walk-forward")
    for flag in _flags_in(wf_message):
        assert flag in wf_flags, (
            f"{flag} is named in the walk-forward remedy but the "
            f"`walk-forward` subcommand does not accept it"
        )

    oos_message = out_of_sample_validation(
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
        train_frac=0.5,
        val_frac=0.25,
        test_frac=0.25,
        validation_method="cpcv",
    )["summary"]["no_selection_diagnosis"]["message"]
    oos_flags = _subcommand_flags("out-of-sample")
    for flag in _flags_in(oos_message):
        assert flag in oos_flags, (
            f"{flag} is named in the out-of-sample remedy but the "
            f"`out-of-sample` subcommand does not accept it"
        )


def test_a_run_that_selects_a_parameter_carries_no_diagnosis():
    """A run that selected something says nothing about failing to select."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    wf = walk_forward_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
    )
    assert all(p is not None for p in wf["best_params_per_period"])
    assert "no_selection_diagnosis" not in wf["summary"]

    cpcv = cpcv_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
        n_splits=4,
        test_size=0.4,
    )
    assert all(p is not None for p in cpcv["best_params_per_fold"])
    assert "no_selection_diagnosis" not in cpcv["summary"]


# ---------------------------------------------------------------------------
# The overfitting-risk verdict
# ---------------------------------------------------------------------------

def test_the_overfitting_risk_verdict_is_not_applicable_when_nothing_was_selected():
    """No selection means no parameter stability to classify."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    cpcv = cpcv_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
    )
    assert cpcv["summary"]["overfitting_risk"] is None
    assert "not applicable" in cpcv["summary"]["overfitting_risk_reason"]

    wf = walk_forward_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=TOO_SLOW_GRID,
    )
    diagnostics = overfitting_check(wf)
    assert diagnostics["overfitting_risk"] is None
    assert "not applicable" in diagnostics["overfitting_risk_reason"]


def test_the_overfitting_risk_verdict_is_unchanged_when_a_parameter_was_selected():
    """A run that selected something keeps its categorical verdict."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    cpcv = cpcv_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
        n_splits=4,
        test_size=0.4,
    )
    assert cpcv["summary"]["overfitting_risk"] in ("low", "medium", "high")
    assert "overfitting_risk_reason" not in cpcv["summary"]

    wf = walk_forward_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
    )
    diagnostics = overfitting_check(wf)
    assert diagnostics["overfitting_risk"] in ("low", "medium", "high")
    assert "overfitting_risk_reason" not in diagnostics


# ---------------------------------------------------------------------------
# The diagnosis is a measurement: it changes no number
# ---------------------------------------------------------------------------

def test_the_diagnosis_changes_no_number():
    """The recorded numbers are the ones the run produced, diagnosis or not."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    cpcv = cpcv_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
    )
    summary = cpcv["summary"]
    assert summary["n_folds"] == 10
    assert summary["folds_with_position"] == 0
    assert summary["total_oos_return"] is None
    assert summary["avg_param_stability"] == 0.0
    assert cpcv["best_params_per_fold"] == [None] * 10

    wf = walk_forward_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=TOO_SLOW_GRID,
    )
    assert wf["summary"]["n_periods"] == 3
    assert wf["summary"]["periods_with_position"] == 0
    assert wf["summary"]["total_oos_return"] is None
    assert wf["best_params_per_period"] == [None] * 3

    # A run that does select keeps its numbers (pinned against the
    # pre-diagnosis implementation).
    selected = walk_forward_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
    )
    assert selected["summary"]["n_periods"] == 3
    assert selected["summary"]["periods_with_position"] == 3
    assert selected["best_params_per_period"] == [
        {"fast_period": 10, "slow_period": 20}
    ] * 3
    assert abs(selected["summary"]["total_oos_return"] - 0.14963115673955674) < 1e-12
    assert abs(selected["summary"]["oos_sharpe"] - 1.1612607898199636) < 1e-12


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------

def test_cpcv_cli_prints_the_diagnosis_next_to_the_fold_count():
    """The console and the artifact carry the same diagnosis."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_cli(
            [
                "cpcv",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(MEANINGFUL_GRID),
                "--output", tmpdir,
            ]
        )
        assert result.returncode == 0, result.stderr[-3000:]
        artifact = json.loads(
            (Path(tmpdir) / "cpcv_summary.json").read_text()
        )
        diagnosis = artifact["summary"]["no_selection_diagnosis"]
        assert diagnosis["cause"] == "no_position_in_validation_window"
        # The console prints the very same message, next to the fold count.
        assert diagnosis["message"] in result.stdout
        fold_line = result.stdout.index("Number of CPCV folds")
        diagnosis_line = result.stdout.index("No parameter could be selected")
        assert fold_line < diagnosis_line
        # The verdict that used to read "high" on a run that could not trade
        # now reads as not applicable.
        assert "Overfitting Risk: unknown" in result.stdout
        assert "Overfitting Risk: high" not in result.stdout


def test_walk_forward_cli_prints_the_diagnosis_next_to_the_period_count():
    """The console and the artifact carry the same diagnosis."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_cli(
            [
                "walk-forward",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(TOO_SLOW_GRID),
                "--output", tmpdir,
            ]
        )
        assert result.returncode == 0, result.stderr[-3000:]
        artifact = json.loads(
            (Path(tmpdir) / "walk_forward_summary.json").read_text()
        )
        diagnosis = artifact["summary"]["no_selection_diagnosis"]
        assert diagnosis["cause"] == "no_position_in_validation_window"
        assert diagnosis["message"] in result.stdout
        period_line = result.stdout.index("Number of walk-forward periods")
        diagnosis_line = result.stdout.index("No parameter could be selected")
        assert period_line < diagnosis_line
        assert "Overfitting Risk: unknown" in result.stdout
        assert "Overfitting Risk: low" not in result.stdout


def test_a_cli_run_that_selects_a_parameter_prints_no_diagnosis():
    """A successful run stays quiet about the diagnosis."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_cli(
            [
                "cpcv",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(MEANINGFUL_GRID),
                "--n-splits", "4",
                "--test-size", "0.4",
                "--output", tmpdir,
            ]
        )
        assert result.returncode == 0, result.stderr[-3000:]
        assert "No parameter could be selected" not in result.stdout
        artifact = json.loads(
            (Path(tmpdir) / "cpcv_summary.json").read_text()
        )
        assert "no_selection_diagnosis" not in artifact["summary"]
        assert artifact["summary"]["overfitting_risk"] in ("low", "medium", "high")


def test_the_out_of_sample_path_still_reports_its_own_diagnosis():
    """The shared helper did not break the path that already had one."""
    data = _load_sample()
    results = out_of_sample_validation(
        data=data,
        strategy_factory=_make_strategy_factory("sma_crossover"),
        param_grid=MEANINGFUL_GRID,
        train_frac=0.5,
        val_frac=0.25,
        test_frac=0.25,
        validation_method="cpcv",
    )
    assert results["selected_params"] is None
    diagnosis = results["summary"]["no_selection_diagnosis"]
    assert diagnosis["cause"] == "no_position_in_validation_window"
    assert results["summary"]["error"] == diagnosis["message"]
    # The out-of-sample subcommand spells its own flags.
    assert "--cpcv-test-size" in diagnosis["message"]
    assert "--cpcv-n-splits" in diagnosis["message"]
    # The training split is 2-bar windows at the default configuration.
    assert "2 bars" in diagnosis["message"]


# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------

TEST_REGISTRY = [
    ("test_cpcv_analysis_records_the_no_selection_diagnosis",
     test_cpcv_analysis_records_the_no_selection_diagnosis),
    ("test_cpcv_diagnosis_names_the_effective_out_of_sample_fraction",
     test_cpcv_diagnosis_names_the_effective_out_of_sample_fraction),
    ("test_walk_forward_analysis_records_the_no_selection_diagnosis",
     test_walk_forward_analysis_records_the_no_selection_diagnosis),
    ("test_the_remedy_names_flags_the_path_actually_accepts",
     test_the_remedy_names_flags_the_path_actually_accepts),
    ("test_a_run_that_selects_a_parameter_carries_no_diagnosis",
     test_a_run_that_selects_a_parameter_carries_no_diagnosis),
    ("test_the_overfitting_risk_verdict_is_not_applicable_when_nothing_was_selected",
     test_the_overfitting_risk_verdict_is_not_applicable_when_nothing_was_selected),
    ("test_the_overfitting_risk_verdict_is_unchanged_when_a_parameter_was_selected",
     test_the_overfitting_risk_verdict_is_unchanged_when_a_parameter_was_selected),
    ("test_the_diagnosis_changes_no_number",
     test_the_diagnosis_changes_no_number),
    ("test_cpcv_cli_prints_the_diagnosis_next_to_the_fold_count",
     test_cpcv_cli_prints_the_diagnosis_next_to_the_fold_count),
    ("test_walk_forward_cli_prints_the_diagnosis_next_to_the_period_count",
     test_walk_forward_cli_prints_the_diagnosis_next_to_the_period_count),
    ("test_a_cli_run_that_selects_a_parameter_prints_no_diagnosis",
     test_a_cli_run_that_selects_a_parameter_prints_no_diagnosis),
    ("test_the_out_of_sample_path_still_reports_its_own_diagnosis",
     test_the_out_of_sample_path_still_reports_its_own_diagnosis),
]


def main() -> int:
    failures = 0
    for name, fn in TEST_REGISTRY:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {name}: {e}")
            traceback.print_exc()

    print(f"\n{len(TEST_REGISTRY) - failures}/{len(TEST_REGISTRY)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
