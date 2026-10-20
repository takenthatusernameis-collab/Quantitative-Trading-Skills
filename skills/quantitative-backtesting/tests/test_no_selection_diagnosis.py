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

The same question has a second, sharper form: what about a run in which
*some* windows selected a parameter and others did not? "2 of 5 folds
selected" is compatible with "the three flat folds were too short to
trade" (a design problem) and with "the strategy never triggers on 60%
of the sample" (a finding about the strategy), and the two need opposite
remedies. The tests below pin that the artifact now says which windows
were flat, why (measured in the search itself, not inferred), and how
many windows the overfitting-risk verdict rests on.

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

import numpy as np
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
# The partial selection: some windows selected a parameter, some did not
# ---------------------------------------------------------------------------

# A configuration in which some folds select a parameter and others do
# not: 5 CPCV folds over the shipped sample with a 20-bar test window.
# Two folds select, three do not. The count alone is compatible with
# "the three flat folds were too short to trade" (a design problem) and
# with "the strategy never triggers on 60% of the sample" (a finding
# about the strategy), and the two need opposite remedies.
PARTIAL_CPCV_KWARGS = {"n_splits": 5, "test_size": 0.2}


def _cpcv_partial_run():
    data = _load_sample()
    return cpcv_analysis(
        data=data,
        strategy_factory=_make_strategy_factory("sma_crossover"),
        param_grid=MEANINGFUL_GRID,
        **PARTIAL_CPCV_KWARGS,
    )


def _flat_then_rising(months=40, flat_months=15, start="2018-01-01"):
    """A price series that is flat, then rises.

    The flat stretch gives the strategy no crossover, so the windows that
    fall inside it cannot select a parameter; the rising stretch gives it
    one. A run over this series therefore selects a parameter in *some*
    windows and not in others -- the partial state the diagnosis is
    about. The fixture is deterministic (no randomness), so the run it
    produces is the same on every machine.
    """
    index = pd.bdate_range(start=start, periods=int(months * 21.2))
    n = len(index)
    rising = index >= pd.Timestamp(start) + pd.DateOffset(months=flat_months)
    close = np.where(rising, 100.0 + np.arange(n) / n * 100.0, 100.0)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": 1_000_000.0,
        },
        index=index,
    )


def test_the_partial_run_is_reproducible():
    """The facts the partial diagnosis reports are pinned.

    The diagnosis is only worth reading if the facts it rests on are
    stable, so they are asserted here: the run selects a parameter in
    two of the five folds, the three flat folds carry the same 20 bars
    each, and they produced no out-of-sample return at all.
    """
    cpcv = _cpcv_partial_run()
    assert cpcv["best_params_per_fold"] == [
        {"fast_period": 10, "slow_period": 20},
        None,
        None,
        {"fast_period": 10, "slow_period": 20},
        None,
    ]
    assert cpcv["summary"]["n_folds"] == 5
    assert cpcv["summary"]["folds_with_position"] == 2

    flat = [f for f in cpcv["folds"] if f.get("best_params") is None]
    assert len(flat) == 3
    for fold in flat:
        assert len(fold["test_data"]) == 20
        assert len(fold["test_returns"]) == 0
        assert fold.get("test_sharpe") is None
        # No combination took a position in the window: the search's own
        # tally says so.
        assert fold["selection_outcomes"]["flat"] == 4
        assert fold["selection_outcomes"]["eligible"] == 0
        assert fold["max_position_bars"] == 0


def test_the_pre_fix_artifact_named_no_cause_for_the_flat_folds():
    """The demonstration behind the fix, pinned so it cannot rot.

    The artifact the previous session produced carried the *count* of the
    folds that selected a parameter and nothing else: no key named a
    cause, a reason or a per-window breakdown for the folds that selected
    nothing. The fix only *adds* that information, so the demonstration
    stays true after the fix -- and this test fails loudly if the
    pre-fix information is ever removed, because then the demonstration
    would be describing a hypothetical.
    """
    cpcv = _cpcv_partial_run()
    summary = {
        key: value
        for key, value in cpcv["summary"].items()
        if key not in ("partial_selection_diagnosis", "overfitting_risk_reason")
    }
    cause_keys = [
        key
        for key in summary
        if "cause" in key.lower()
        or "reason" in key.lower()
        or "diagnosis" in key.lower()
    ]
    assert cause_keys == [], (
        "the pre-fix artifact already names a cause for the folds that "
        f"selected nothing ({cause_keys}), so the demonstration behind the "
        f"fix has to be re-written"
    )
    # The count was there; the reason was not.
    assert summary["folds_with_position"] == 2
    assert summary["n_folds"] == 5


def test_the_cpcv_partial_diagnosis_names_every_flat_fold():
    """Every flat fold is reported with its cause and its evidence."""
    cpcv = _cpcv_partial_run()
    diagnosis = cpcv["summary"]["partial_selection_diagnosis"]

    # The same shape as the "no parameter could be selected" diagnosis.
    assert set(diagnosis) == {"cause", "message", "details"}
    assert diagnosis["cause"] == "no_position_in_validation_window"

    details = diagnosis["details"]
    assert details["n_validation_windows"] == 5
    assert details["n_windows_with_selected_params"] == 2
    assert details["n_flat_windows"] == 3
    assert details["analysis_path"] == "cpcv"
    assert details["window_noun"] == "fold"

    flat_windows = details["flat_windows"]
    assert len(flat_windows) == 3
    for window in flat_windows:
        # The cause comes from the vocabulary the "no selection at all"
        # diagnosis already uses.
        assert window["cause"] == "no_position_in_validation_window"
        # The evidence for it.
        assert window["bars"] == 20
        assert window["test_returns_bars"] == 0
        assert window["test_sharpe"] is None
        assert window["max_position_bars"] == 0
        assert window["outcome_tally"]["no_position_in_validation_window"] == 4
        assert window["text"]


def test_the_flat_folds_are_not_short_window_folds():
    """The measurement that separates the two readings of the count.

    Every fold carries the same 20 test bars, so the flat folds are not
    short windows: the signal simply never triggered in them. The
    diagnosis has to say that, and it has to say it from a measurement
    rather than an assumption.
    """
    cpcv = _cpcv_partial_run()
    details = cpcv["summary"]["partial_selection_diagnosis"]["details"]

    # The windows in which the strategy traded are the same length as the
    # flat ones.
    assert details["min_traded_window_bars"] == 20
    assert all(
        window["bars"] >= details["min_traded_window_bars"]
        for window in details["flat_windows"]
    )
    for window in details["flat_windows"]:
        assert window["reason"] == "signal_never_triggered"
        assert "never triggered" in window["text"]


def test_the_overfitting_risk_verdict_is_qualified_but_unchanged():
    """A verdict that rests on two of five windows has to say so."""
    cpcv = _cpcv_partial_run()
    summary = cpcv["summary"]

    # The categorical verdict is unchanged: the measurement supports it.
    assert summary["overfitting_risk"] in ("low", "medium", "high")
    reason = summary["overfitting_risk_reason"]
    assert "2" in reason and "5" in reason
    assert "partial_selection_diagnosis" in reason

    # The walk-forward path qualifies its verdict the same way.
    results = walk_forward_analysis(
        data=_flat_then_rising(),
        strategy_factory=_make_strategy_factory("sma_crossover"),
        param_grid=MEANINGFUL_GRID,
    )
    diagnostics = overfitting_check(results)
    assert diagnostics["overfitting_risk"] in ("low", "medium", "high")
    assert "partial_selection_diagnosis" in diagnostics["overfitting_risk_reason"]


def test_the_walk_forward_path_records_the_partial_diagnosis():
    """The walk-forward path says which periods were flat and why."""
    results = walk_forward_analysis(
        data=_flat_then_rising(),
        strategy_factory=_make_strategy_factory("sma_crossover"),
        param_grid=MEANINGFUL_GRID,
    )
    diagnosis = results["summary"]["partial_selection_diagnosis"]
    details = diagnosis["details"]

    assert details["analysis_path"] == "walk_forward"
    assert details["window_noun"] == "period"
    assert details["n_flat_windows"] == 2
    assert details["n_windows_with_selected_params"] == (
        details["n_validation_windows"] - 2
    )

    # The two flat periods do not have the same cause, and the diagnosis
    # says which is which. The first one is flat (the strategy never
    # takes a position in it); the second one is NOT flat -- every
    # combination takes a position in it, but its training split produced
    # a constant return series, so the Sharpe the selection ranks on is
    # not estimable. A diagnosis that reported "no position" for both
    # would be wrong.
    causes = {window["cause"] for window in details["flat_windows"]}
    assert causes == {
        "no_position_in_validation_window",
        "no_estimable_training_sharpe",
    }
    degenerate = [
        window
        for window in details["flat_windows"]
        if window["cause"] == "no_estimable_training_sharpe"
    ][0]
    assert degenerate["max_position_bars"] > 0
    assert degenerate["outcome_tally"]["no_estimable_training_sharpe"] == 4
    assert "constant return series" in degenerate["text"]


def test_the_out_of_sample_path_records_the_partial_diagnosis():
    """The out-of-sample path says which validation windows were flat."""
    results = out_of_sample_validation(
        data=_flat_then_rising(),
        strategy_factory=_make_strategy_factory("sma_crossover"),
        param_grid=MEANINGFUL_GRID,
    )
    assert results["selected_params"] is not None
    diagnosis = results["summary"]["partial_selection_diagnosis"]
    details = diagnosis["details"]

    assert details["analysis_path"] == "out_of_sample"
    assert details["n_flat_windows"] >= 1
    assert details["n_windows_with_selected_params"] >= 1
    # The selected parameter was chosen from the windows that could
    # select one; the artifact says so.
    assert "selected parameter" in diagnosis["message"]
    # The out-of-sample subcommand spells its own flags.
    assert "--wf-test-months" in diagnosis["message"]


def test_the_partial_remedy_names_flags_the_path_actually_accepts():
    """A remedy that names an unusable flag is not a remedy."""
    cpcv_message = _cpcv_partial_run()["summary"]["partial_selection_diagnosis"]["message"]
    cpcv_flags = _subcommand_flags("cpcv")
    for flag in _flags_in(cpcv_message):
        assert flag in cpcv_flags, (
            f"{flag} is named in the CPCV partial remedy but the `cpcv` "
            f"subcommand does not accept it"
        )

    wf_message = walk_forward_analysis(
        data=_flat_then_rising(),
        strategy_factory=_make_strategy_factory("sma_crossover"),
        param_grid=MEANINGFUL_GRID,
    )["summary"]["partial_selection_diagnosis"]["message"]
    wf_flags = _subcommand_flags("walk-forward")
    for flag in _flags_in(wf_message):
        assert flag in wf_flags, (
            f"{flag} is named in the walk-forward partial remedy but the "
            f"`walk-forward` subcommand does not accept it"
        )

    oos_message = out_of_sample_validation(
        data=_flat_then_rising(),
        strategy_factory=_make_strategy_factory("sma_crossover"),
        param_grid=MEANINGFUL_GRID,
    )["summary"]["partial_selection_diagnosis"]["message"]
    oos_flags = _subcommand_flags("out-of-sample")
    for flag in _flags_in(oos_message):
        assert flag in oos_flags, (
            f"{flag} is named in the out-of-sample partial remedy but the "
            f"`out-of-sample` subcommand does not accept it"
        )


def test_a_run_that_selects_in_every_window_carries_no_partial_diagnosis():
    """Nothing to explain when every window selected a parameter."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    wf = walk_forward_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
    )
    assert all(p is not None for p in wf["best_params_per_period"])
    assert "partial_selection_diagnosis" not in wf["summary"]
    assert "overfitting_risk_reason" not in overfitting_check(wf)

    cpcv = cpcv_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
        n_splits=4,
        test_size=0.4,
    )
    assert all(p is not None for p in cpcv["best_params_per_fold"])
    assert "partial_selection_diagnosis" not in cpcv["summary"]


def test_the_all_flat_case_still_uses_the_no_selection_diagnosis():
    """The partial key is only for the partial state."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    cpcv = cpcv_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
    )
    assert "no_selection_diagnosis" in cpcv["summary"]
    assert "partial_selection_diagnosis" not in cpcv["summary"]

    wf = walk_forward_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=TOO_SLOW_GRID,
    )
    assert "no_selection_diagnosis" in wf["summary"]
    assert "partial_selection_diagnosis" not in wf["summary"]


def test_the_partial_diagnosis_changes_no_number():
    """The diagnosis is a measurement: it changes no number."""
    cpcv = _cpcv_partial_run()
    summary = cpcv["summary"]
    assert summary["n_folds"] == 5
    assert summary["folds_with_position"] == 2
    # The two folds that did select held the position for a single bar
    # each, so the run's out-of-sample record is a flat one: the numbers
    # are the ones the run produced, diagnosis or not.
    assert summary["n_positive_folds"] == 0
    assert summary["win_rate_folds"] == 0.0
    assert summary["total_oos_return"] == 0.0
    assert summary["oos_sharpe"] == 0.0
    assert cpcv["best_params_per_fold"] == [
        {"fast_period": 10, "slow_period": 20},
        None,
        None,
        {"fast_period": 10, "slow_period": 20},
        None,
    ]
    assert len(cpcv["oos_returns"]) > 0


def test_the_cli_prints_the_partial_diagnosis_next_to_the_fold_count():
    """The console and the artifact carry the same per-window breakdown."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_cli(
            [
                "cpcv",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(MEANINGFUL_GRID),
                "--n-splits", "5",
                "--test-size", "0.2",
                "--output", tmpdir,
            ]
        )
        assert result.returncode == 0, result.stderr[-3000:]
        artifact = json.loads(
            (Path(tmpdir) / "cpcv_summary.json").read_text()
        )
        diagnosis = artifact["summary"]["partial_selection_diagnosis"]
        assert diagnosis["message"] in result.stdout
        fold_line = result.stdout.index("Number of CPCV folds")
        diagnosis_line = result.stdout.index("Partial selection")
        assert fold_line < diagnosis_line
        # Every flat fold is named on the console, with the same text the
        # artifact carries.
        for window in diagnosis["details"]["flat_windows"]:
            assert window["text"] in result.stdout
        # The run that selected something prints no "no parameter could be
        # selected" diagnosis.
        assert "No parameter could be selected" not in result.stdout


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
    ("test_the_partial_run_is_reproducible",
     test_the_partial_run_is_reproducible),
    ("test_the_pre_fix_artifact_named_no_cause_for_the_flat_folds",
     test_the_pre_fix_artifact_named_no_cause_for_the_flat_folds),
    ("test_the_cpcv_partial_diagnosis_names_every_flat_fold",
     test_the_cpcv_partial_diagnosis_names_every_flat_fold),
    ("test_the_flat_folds_are_not_short_window_folds",
     test_the_flat_folds_are_not_short_window_folds),
    ("test_the_overfitting_risk_verdict_is_qualified_but_unchanged",
     test_the_overfitting_risk_verdict_is_qualified_but_unchanged),
    ("test_the_walk_forward_path_records_the_partial_diagnosis",
     test_the_walk_forward_path_records_the_partial_diagnosis),
    ("test_the_out_of_sample_path_records_the_partial_diagnosis",
     test_the_out_of_sample_path_records_the_partial_diagnosis),
    ("test_the_partial_remedy_names_flags_the_path_actually_accepts",
     test_the_partial_remedy_names_flags_the_path_actually_accepts),
    ("test_a_run_that_selects_in_every_window_carries_no_partial_diagnosis",
     test_a_run_that_selects_in_every_window_carries_no_partial_diagnosis),
    ("test_the_all_flat_case_still_uses_the_no_selection_diagnosis",
     test_the_all_flat_case_still_uses_the_no_selection_diagnosis),
    ("test_the_partial_diagnosis_changes_no_number",
     test_the_partial_diagnosis_changes_no_number),
    ("test_the_cli_prints_the_partial_diagnosis_next_to_the_fold_count",
     test_the_cli_prints_the_partial_diagnosis_next_to_the_fold_count),
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
