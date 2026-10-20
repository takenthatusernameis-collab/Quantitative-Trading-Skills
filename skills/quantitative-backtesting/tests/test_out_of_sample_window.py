#!/usr/bin/env python3
"""Regression tests for the out-of-sample validation window and its diagnosis.

The `out-of-sample` CLI used to abort on the shipped sample data with
"No valid parameters selected from validation phase." The real cause was that
the walk-forward validation phase runs *inside* the training split, and the
default window (12 months of training + 3 months of out-of-sample testing)
does not fit the one-year training split the CLI carves out of the sample:
the phase produced **zero** periods, so no parameter could be selected.

These tests guard the repaired behaviour:

  * the walk-forward window is shortened to the largest value that still
    yields a period, and the adaptation is reported and recorded;
  * a window that already fits is left untouched (no silent change to the
    methodology of the runs that already worked);
  * a validation phase that really cannot select a parameter says *why*,
    in a machine-readable diagnosis and in the CLI output, instead of
    collapsing every failure into one sentence;
  * a parameter grid that does not change the strategy's behaviour is
    reported as the null experiment it is.

Run with: python3 skills/quantitative-backtesting/tests/test_out_of_sample_window.py
No third-party test framework is required; uses only the standard library.
"""

import json
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
    _inert_param_grid_keys,
    _make_strategy_factory,
    _resolve_walk_forward_window,
    _walk_forward_window_periods,
    out_of_sample_validation,
)

SAMPLE_DATA = SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv"
WALK_FORWARD_CLI = SKILLS_DIR / "scripts" / "walk_forward.py"

# A grid the strategy actually reads. `sma_crossover` uses `fast_period` and
# `slow_period`; a grid over any other name is inert (see the inertness
# tests below).
MEANINGFUL_GRID = {"fast_period": [5, 10], "slow_period": [20, 30]}


def _load_sample() -> pd.DataFrame:
    df = pd.read_csv(SAMPLE_DATA, parse_dates=["date"]).set_index("date")
    return df


def _make_ohlcv_data(periods: int = 900, seed: int = 42) -> pd.DataFrame:
    """Long trending sample, used where a 12 + 3 month window does fit."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    trend = np.linspace(0, 0.5, periods)
    noise = rng.normal(0, 0.01, periods)
    prices = 100 * np.exp(np.cumsum(trend / periods + noise))
    return pd.DataFrame(
        {
            "open": prices * rng.uniform(0.995, 1.005, periods),
            "high": prices * rng.uniform(1.005, 1.02, periods),
            "low": prices * rng.uniform(0.98, 0.995, periods),
            "close": prices,
            "volume": rng.integers(1_000_000, 10_000_000, periods),
        },
        index=dates,
    )


def _run_cli(args, output_dir):
    result = subprocess.run(
        [sys.executable, str(WALK_FORWARD_CLI)] + args,
        capture_output=True,
        text=True,
        timeout=900,
    )
    return result


# ---------------------------------------------------------------------------
# The window resolver
# ---------------------------------------------------------------------------

def test_walk_forward_window_periods_counts_the_periods_the_generator_builds():
    """The period count mirrors the generator in walk_forward_analysis."""
    data = _make_ohlcv_data(periods=900, seed=3)
    assert _walk_forward_window_periods(data, 12, 3, 3) > 0
    # A window that cannot fit the sample produces no period.
    assert _walk_forward_window_periods(data, 240, 3, 3) == 0


def test_resolve_walk_forward_window_keeps_a_window_that_fits():
    """A requested window that fits is used unchanged (no silent change)."""
    data = _make_ohlcv_data(periods=900, seed=3)
    resolution = _resolve_walk_forward_window(data, 12, 3, 3)
    assert resolution["adapted"] is False
    assert resolution["effective"] == {
        "train_months": 12,
        "test_months": 3,
        "step_months": 3,
    }
    assert resolution["requested_periods"] == resolution["effective_periods"]
    assert resolution["effective_periods"] > 0
    assert resolution["reason"] is None


def test_resolve_walk_forward_window_shortens_to_the_largest_fitting_window():
    """A window that does not fit is shortened on the training side only."""
    data = _load_sample()
    # The training split of the shipped sample spans ~11.5 months, so the
    # default 12 + 3 month window cannot produce a single period.
    train_split = data.iloc[: len(data) // 2]
    resolution = _resolve_walk_forward_window(train_split, 12, 3, 3)
    assert resolution["adapted"] is True
    assert resolution["requested"] == {
        "train_months": 12,
        "test_months": 3,
        "step_months": 3,
    }
    # Only the training window is shortened: the out-of-sample test window
    # of the validation phase is untouched.
    assert resolution["effective"]["test_months"] == 3
    assert resolution["effective"]["step_months"] == 3
    assert resolution["effective"]["train_months"] < 12
    assert resolution["effective_periods"] >= 1
    # The shortened window is the largest one that still yields a period.
    assert _walk_forward_window_periods(
        train_split,
        resolution["effective"]["train_months"] + 1,
        3,
        3,
    ) == 0
    assert "training split spans" in resolution["reason"]


def test_resolve_walk_forward_window_reports_an_infeasible_split():
    """A training split too short for any window is reported, not guessed."""
    data = _load_sample().iloc[:20]  # ~4 weeks
    resolution = _resolve_walk_forward_window(data, 12, 3, 3)
    assert resolution["adapted"] is False
    assert resolution["effective_periods"] == 0
    assert resolution["reason"] is not None
    assert "no walk-forward period can be built" in resolution["reason"]


# ---------------------------------------------------------------------------
# The out-of-sample path
# ---------------------------------------------------------------------------

def test_out_of_sample_validation_adapts_the_window_to_the_training_split():
    """The shipped sample now completes, and records the adapted window."""
    data = _load_sample()
    results = out_of_sample_validation(
        data=data,
        strategy_factory=_make_strategy_factory("sma_crossover"),
        param_grid=MEANINGFUL_GRID,
        train_frac=0.5,
        val_frac=0.25,
        test_frac=0.25,
        validation_method="walk_forward",
    )
    assert results["selected_params"] is not None, results["summary"].get("error")
    window = results["summary"]["walk_forward_window"]
    assert window["adapted"] is True
    assert window["requested"]["train_months"] == 12
    assert window["effective"]["train_months"] < 12
    assert window["effective_periods"] >= 1
    # The validation phase really ran on the adapted window.
    periods = results["validation_results"]["periods"]
    assert len(periods) == window["effective_periods"]
    # The out-of-sample report is complete: a selection, a validation window
    # and a held-out test window.
    assert results["test_performance"]["test_n_periods"] > 0
    assert results["validation_performance"]["val_n_periods"] > 0


def test_out_of_sample_validation_keeps_the_window_when_it_fits():
    """A long sample keeps the requested window, so the method is unchanged."""
    data = _make_ohlcv_data(periods=1200, seed=11)
    results = out_of_sample_validation(
        data=data,
        strategy_factory=_make_strategy_factory("sma_crossover"),
        param_grid=MEANINGFUL_GRID,
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        validation_method="walk_forward",
    )
    assert results["selected_params"] is not None, results["summary"].get("error")
    window = results["summary"]["walk_forward_window"]
    assert window["adapted"] is False
    assert window["effective"] == {
        "train_months": 12,
        "test_months": 3,
        "step_months": 3,
    }


def test_out_of_sample_validation_flags_an_inert_parameter_grid():
    """A grid the strategy ignores is reported as the null experiment it is."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    inert = _inert_param_grid_keys(factory, {"lookback": [5, 20]}, data)
    assert inert == ["lookback"]

    live = _inert_param_grid_keys(factory, MEANINGFUL_GRID, data)
    assert live == []

    results = out_of_sample_validation(
        data=data,
        strategy_factory=factory,
        param_grid={"lookback": [5, 20]},
        train_frac=0.5,
        val_frac=0.25,
        test_frac=0.25,
        validation_method="walk_forward",
    )
    assert results["summary"]["inert_grid_params"] == ["lookback"]


def test_out_of_sample_validation_diagnoses_a_selection_failure():
    """A validation phase that cannot select says which cause it is."""
    data = _load_sample()
    # The default CPCV configuration puts a 2-bar test window in every fold:
    # no strategy can take a position in it, so nothing can be selected.
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
    assert diagnosis["details"]["n_validation_windows"] > 0
    assert diagnosis["details"]["n_windows_with_selected_params"] == 0
    # The message names the window length and the remedy.
    assert "2 bars" in diagnosis["message"]
    assert "--cpcv-test-size" in diagnosis["message"]
    assert results["summary"]["error"] == diagnosis["message"]


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------

def test_out_of_sample_cli_completes_on_the_shipped_sample():
    """The regression: the CLI used to exit 1 with no artifact at all."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_cli(
            [
                "out-of-sample",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--validation-method", "walk_forward",
                "--train-frac", "0.5",
                "--val-frac", "0.25",
                "--test-frac", "0.25",
                "--param-grid", json.dumps(MEANINGFUL_GRID),
                "--output", tmpdir,
            ],
            tmpdir,
        )
        assert result.returncode == 0, (
            f"out-of-sample CLI exited {result.returncode}\n"
            f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
        )
        summary_path = Path(tmpdir) / "out_of_sample_summary.json"
        assert summary_path.exists(), "the out-of-sample artifact was not written"
        artifact = json.loads(summary_path.read_text())
        assert artifact["selected_params"] is not None
        assert artifact["summary"]["walk_forward_window"]["adapted"] is True
        # The adaptation is stated in the console output too.
        assert "Walk-forward window adapted" in result.stdout


def test_out_of_sample_cli_reports_the_cause_and_writes_the_diagnosis():
    """A failing run states the cause and leaves a machine-readable record."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_cli(
            [
                "out-of-sample",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--validation-method", "cpcv",
                "--train-frac", "0.5",
                "--val-frac", "0.25",
                "--test-frac", "0.25",
                "--param-grid", json.dumps(MEANINGFUL_GRID),
                "--output", tmpdir,
            ],
            tmpdir,
        )
        assert result.returncode == 1
        assert "No valid parameters selected from validation phase" in result.stdout
        assert "no parameter combination took a position" in result.stdout
        summary_path = Path(tmpdir) / "out_of_sample_summary.json"
        assert summary_path.exists(), "the failure diagnosis was not written"
        artifact = json.loads(summary_path.read_text())
        diagnosis = artifact["summary"]["no_selection_diagnosis"]
        assert diagnosis["cause"] == "no_position_in_validation_window"
        assert artifact["selected_params"] is None


# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------

TEST_REGISTRY = [
    ("test_walk_forward_window_periods_counts_the_periods_the_generator_builds",
     test_walk_forward_window_periods_counts_the_periods_the_generator_builds),
    ("test_resolve_walk_forward_window_keeps_a_window_that_fits",
     test_resolve_walk_forward_window_keeps_a_window_that_fits),
    ("test_resolve_walk_forward_window_shortens_to_the_largest_fitting_window",
     test_resolve_walk_forward_window_shortens_to_the_largest_fitting_window),
    ("test_resolve_walk_forward_window_reports_an_infeasible_split",
     test_resolve_walk_forward_window_reports_an_infeasible_split),
    ("test_out_of_sample_validation_adapts_the_window_to_the_training_split",
     test_out_of_sample_validation_adapts_the_window_to_the_training_split),
    ("test_out_of_sample_validation_keeps_the_window_when_it_fits",
     test_out_of_sample_validation_keeps_the_window_when_it_fits),
    ("test_out_of_sample_validation_flags_an_inert_parameter_grid",
     test_out_of_sample_validation_flags_an_inert_parameter_grid),
    ("test_out_of_sample_validation_diagnoses_a_selection_failure",
     test_out_of_sample_validation_diagnoses_a_selection_failure),
    ("test_out_of_sample_cli_completes_on_the_shipped_sample",
     test_out_of_sample_cli_completes_on_the_shipped_sample),
    ("test_out_of_sample_cli_reports_the_cause_and_writes_the_diagnosis",
     test_out_of_sample_cli_reports_the_cause_and_writes_the_diagnosis),
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
