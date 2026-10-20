#!/usr/bin/env python3
"""Regression tests for inert parameter grids on every analysis path.

A grid key whose values do not change the strategy's behaviour is a null
experiment: the "search" over it cannot change any result, yet the artifact
would still report it as a selected parameter. The shipped example makes the
trap easy to hit -- `sma_crossover` reads `fast_period` and `slow_period`, so
a grid over `lookback` prices the same strategy in every combination and the
ranking that comes out is an artefact of the tie-break, not evidence.

These tests guard the behaviour of all four analysis paths:

  * `walk_forward_analysis` records the finding in its summary;
  * `cpcv_analysis` records the finding in its summary;
  * `parameter_optimization` measures it and hands it to the caller;
  * `out_of_sample_validation` records the finding in its summary;
  * every CLI prints the warning exactly once, next to the ranking /
    selection it qualifies, and writes the finding into the artifact;
  * the measurement is a measurement: no return, cost, impact, capacity or
    selection number changes because of it.

Run with: python3 skills/quantitative-backtesting/tests/test_inert_param_grid.py
No third-party test framework is required; uses only the standard library.
"""

import contextlib
import io
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
    _inert_grid_report,
    _inert_param_grid_keys,
    _make_strategy_factory,
    cpcv_analysis,
    out_of_sample_validation,
    parameter_optimization,
    walk_forward_analysis,
)

SAMPLE_DATA = SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv"
WALK_FORWARD_CLI = SKILLS_DIR / "scripts" / "walk_forward.py"

# A grid the strategy actually reads. `sma_crossover` uses `fast_period` and
# `slow_period`; a grid over any other name is inert.
MEANINGFUL_GRID = {"fast_period": [5, 10], "slow_period": [20, 30]}
INERT_GRID = {"lookback": [5, 20]}
# One live key and one inert key: only the inert one may be reported.
MIXED_GRID = {"fast_period": [5, 10], "lookback": [5, 20]}


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


def _run_cli(args):
    return subprocess.run(
        [sys.executable, str(WALK_FORWARD_CLI)] + args,
        capture_output=True,
        text=True,
        timeout=1800,
    )


def _capture_stdout(fn, *args, **kwargs):
    """Run `fn` and return (result, stdout)."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = fn(*args, **kwargs)
    return result, buffer.getvalue()


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------

def test_inert_grid_report_flags_a_key_the_strategy_ignores():
    """The report names the inert keys and says why the search is empty."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    report = _inert_grid_report(factory, INERT_GRID, data)
    assert report["inert_grid_params"] == ["lookback"]
    assert "lookback" in report["message"]
    assert "null experiment" in report["message"]
    # The hint names the parameters the strategy actually reads.
    assert report["strategy_parameters"] == ["fast_period", "slow_period"]
    assert "fast_period" in report["message"]


def test_inert_grid_report_does_not_flag_a_live_key():
    """A grid the strategy reads is never reported as inert."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    report = _inert_grid_report(factory, MEANINGFUL_GRID, data)
    assert report["inert_grid_params"] == []
    assert report["message"] is None


def test_inert_grid_report_flags_only_the_inert_key_of_a_mixed_grid():
    """A grid with one live and one inert key reports only the inert one."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    report = _inert_grid_report(factory, MIXED_GRID, data)
    assert report["inert_grid_params"] == ["lookback"]


def test_inert_grid_report_agrees_with_the_key_detector():
    """The report is a thin layer over the key detector, not a second rule."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")
    for grid in (INERT_GRID, MEANINGFUL_GRID, MIXED_GRID):
        report = _inert_grid_report(factory, grid, data)
        assert report["inert_grid_params"] == _inert_param_grid_keys(factory, grid, data)


# ---------------------------------------------------------------------------
# The library paths
# ---------------------------------------------------------------------------

def test_walk_forward_analysis_records_the_inert_grid():
    """The walk-forward summary says which grid keys were never searched."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    results, stdout = _capture_stdout(
        walk_forward_analysis,
        data=data,
        strategy_factory=factory,
        param_grid=INERT_GRID,
    )
    summary = results["summary"]
    assert summary["inert_grid_params"] == ["lookback"]
    assert "lookback" in summary["inert_grid_message"]
    # The analysis function never prints: the CLI decides where the warning
    # goes, so it appears exactly once and next to the numbers it qualifies.
    assert "WARNING" not in stdout


def test_walk_forward_analysis_records_no_inert_grid_for_a_live_grid():
    """A meaningful grid is not reported as inert (no false positives)."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    results, _ = _capture_stdout(
        walk_forward_analysis,
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
    )
    assert results["summary"]["inert_grid_params"] == []
    assert results["summary"]["inert_grid_message"] is None


def test_cpcv_analysis_records_the_inert_grid():
    """The CPCV summary says which grid keys were never searched."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    results, stdout = _capture_stdout(
        cpcv_analysis,
        data=data,
        strategy_factory=factory,
        param_grid=INERT_GRID,
    )
    summary = results["summary"]
    assert summary["inert_grid_params"] == ["lookback"]
    assert "lookback" in summary["inert_grid_message"]
    assert "WARNING" not in stdout


def test_parameter_optimization_hands_the_inert_grid_to_the_caller():
    """The optimization measures the inert grid without printing it."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    report = {}
    results, stdout = _capture_stdout(
        parameter_optimization,
        data=data,
        strategy_factory=factory,
        param_grid=INERT_GRID,
        inert_grid_report=report,
    )
    assert report["inert_grid_params"] == ["lookback"]
    assert "lookback" in report["message"]
    # The function is silent: a cost sweep calls it once per coefficient and
    # must not repeat the warning.
    assert "WARNING" not in stdout
    # The measurement changes no number: the ranking is the one the search
    # produced, with the same sharpe and return.
    assert len(results) == 2
    assert results[0]["sharpe_ratio"] == results[1]["sharpe_ratio"]
    assert results[0]["total_return"] == results[1]["total_return"]


def test_parameter_optimization_is_unchanged_by_the_measurement():
    """Requesting the report does not change a single returned number."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    without, _ = _capture_stdout(
        parameter_optimization,
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
    )
    with_report, _ = _capture_stdout(
        parameter_optimization,
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
        inert_grid_report={},
    )
    assert without == with_report


def test_out_of_sample_validation_records_the_inert_grid():
    """The out-of-sample summary keeps the finding (training split scope)."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    results, stdout = _capture_stdout(
        out_of_sample_validation,
        data=data,
        strategy_factory=factory,
        param_grid=INERT_GRID,
        train_frac=0.5,
        val_frac=0.25,
        test_frac=0.25,
        validation_method="walk_forward",
    )
    summary = results["summary"]
    assert summary["inert_grid_params"] == ["lookback"]
    assert "training split" in summary["inert_grid_message"]
    assert "WARNING" not in stdout


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------

def test_optimize_cli_warns_next_to_the_ranking_and_records_it():
    """The ranking says, next to itself, that it ranked nothing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_cli(
            [
                "optimize",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(INERT_GRID),
                "--output", tmpdir,
            ]
        )
        assert result.returncode == 0, result.stderr[-3000:]
        # The warning is printed once, next to the ranking.
        assert result.stdout.count("WARNING: the parameter grid") == 1
        lines = result.stdout.splitlines()
        warning_idx = [
            i for i, line in enumerate(lines)
            if "WARNING: the parameter grid" in line
        ]
        ranking_idx = [i for i, line in enumerate(lines) if line.startswith("Rank")]
        assert warning_idx and ranking_idx, "the warning or the ranking is missing"
        # The warning follows the ranking table, so a reader meets it while
        # looking at the ranking it qualifies.
        assert warning_idx[0] > ranking_idx[0]
        # The finding is recorded next to the ranking artifact.
        record_path = Path(tmpdir) / "parameter_optimization_inert_grid.json"
        assert record_path.exists(), "the inert-grid record was not written"
        record = json.loads(record_path.read_text())
        assert record["inert_grid_params"] == ["lookback"]
        assert record["param_grid"] == INERT_GRID
        assert record["strategy"] == "sma_crossover"
        assert record["n_ranked_combinations"] == 2
        # The ranking artifact itself is unchanged (a plain ranked list).
        ranking = json.loads(
            (Path(tmpdir) / "parameter_optimization.json").read_text()
        )
        assert isinstance(ranking, list)
        assert ranking[0]["params"] == {"lookback": 5}
        assert ranking[0]["sharpe_ratio"] == ranking[1]["sharpe_ratio"]


def test_optimize_cli_does_not_warn_for_a_live_grid():
    """No false positive: a grid the strategy reads is never called inert."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_cli(
            [
                "optimize",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(MEANINGFUL_GRID),
                "--output", tmpdir,
            ]
        )
        assert result.returncode == 0, result.stderr[-3000:]
        assert "WARNING: the parameter grid" not in result.stdout
        record = json.loads(
            (Path(tmpdir) / "parameter_optimization_inert_grid.json").read_text()
        )
        assert record["inert_grid_params"] == []
        assert record["inert_grid_message"] is None


def test_walk_forward_cli_warns_and_records_the_inert_grid():
    """The walk-forward console and artifact agree."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_cli(
            [
                "walk-forward",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(INERT_GRID),
                "--output", tmpdir,
            ]
        )
        assert result.returncode == 0, result.stderr[-3000:]
        assert result.stdout.count("WARNING: the parameter grid") == 1
        artifact = json.loads(
            (Path(tmpdir) / "walk_forward_summary.json").read_text()
        )
        assert artifact["summary"]["inert_grid_params"] == ["lookback"]
        assert "lookback" in artifact["summary"]["inert_grid_message"]


def test_cpcv_cli_warns_and_records_the_inert_grid():
    """The CPCV console and artifact agree."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_cli(
            [
                "cpcv",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(INERT_GRID),
                "--output", tmpdir,
            ]
        )
        assert result.returncode == 0, result.stderr[-3000:]
        assert result.stdout.count("WARNING: the parameter grid") == 1
        artifact = json.loads((Path(tmpdir) / "cpcv_summary.json").read_text())
        assert artifact["summary"]["inert_grid_params"] == ["lookback"]
        assert "lookback" in artifact["summary"]["inert_grid_message"]


def test_out_of_sample_cli_prints_the_warning_once():
    """The warning is printed by the CLI only, so it never repeats."""
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
                "--param-grid", json.dumps(INERT_GRID),
                "--output", tmpdir,
            ]
        )
        assert result.returncode == 0, result.stderr[-3000:]
        assert result.stdout.count("WARNING: the parameter grid") == 1
        artifact = json.loads(
            (Path(tmpdir) / "out_of_sample_summary.json").read_text()
        )
        assert artifact["summary"]["inert_grid_params"] == ["lookback"]


def test_the_sweep_artifacts_record_the_inert_grid():
    """A cost sweep records the finding too, not only the single run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_cli(
            [
                "optimize",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(INERT_GRID),
                "--impact-coefficients", "0.0", "0.0001",
                "--output", tmpdir,
            ]
        )
        assert result.returncode == 0, result.stderr[-3000:]
        sweep = json.loads(
            (Path(tmpdir) / "parameter_optimization_impact_sweep.json").read_text()
        )
        assert sweep["results"], "the sweep artifact has no rows"
        for row in sweep["results"]:
            assert row["inert_grid_params"] == ["lookback"]


# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------

TEST_REGISTRY = [
    ("test_inert_grid_report_flags_a_key_the_strategy_ignores",
     test_inert_grid_report_flags_a_key_the_strategy_ignores),
    ("test_inert_grid_report_does_not_flag_a_live_key",
     test_inert_grid_report_does_not_flag_a_live_key),
    ("test_inert_grid_report_flags_only_the_inert_key_of_a_mixed_grid",
     test_inert_grid_report_flags_only_the_inert_key_of_a_mixed_grid),
    ("test_inert_grid_report_agrees_with_the_key_detector",
     test_inert_grid_report_agrees_with_the_key_detector),
    ("test_walk_forward_analysis_records_the_inert_grid",
     test_walk_forward_analysis_records_the_inert_grid),
    ("test_walk_forward_analysis_records_no_inert_grid_for_a_live_grid",
     test_walk_forward_analysis_records_no_inert_grid_for_a_live_grid),
    ("test_cpcv_analysis_records_the_inert_grid",
     test_cpcv_analysis_records_the_inert_grid),
    ("test_parameter_optimization_hands_the_inert_grid_to_the_caller",
     test_parameter_optimization_hands_the_inert_grid_to_the_caller),
    ("test_parameter_optimization_is_unchanged_by_the_measurement",
     test_parameter_optimization_is_unchanged_by_the_measurement),
    ("test_out_of_sample_validation_records_the_inert_grid",
     test_out_of_sample_validation_records_the_inert_grid),
    ("test_optimize_cli_warns_next_to_the_ranking_and_records_it",
     test_optimize_cli_warns_next_to_the_ranking_and_records_it),
    ("test_optimize_cli_does_not_warn_for_a_live_grid",
     test_optimize_cli_does_not_warn_for_a_live_grid),
    ("test_walk_forward_cli_warns_and_records_the_inert_grid",
     test_walk_forward_cli_warns_and_records_the_inert_grid),
    ("test_cpcv_cli_warns_and_records_the_inert_grid",
     test_cpcv_cli_warns_and_records_the_inert_grid),
    ("test_out_of_sample_cli_prints_the_warning_once",
     test_out_of_sample_cli_prints_the_warning_once),
    ("test_the_sweep_artifacts_record_the_inert_grid",
     test_the_sweep_artifacts_record_the_inert_grid),
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
