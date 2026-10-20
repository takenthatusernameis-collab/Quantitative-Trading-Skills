#!/usr/bin/env python3
"""Tests for the test-resolution (minimum detectable effect) reporting.

A significance test on a small sample can only fail: with T observations the
threshold "deflated p < 0.10" requires the effect to exceed a certain size.
A reader of a summary that carries a p-value and a risk verdict therefore
has no way to tell an informative result from an unfalsifiable one.

The framework now reports that resolution next to the significance
statistics it already carries, as `summary["test_resolution"]` and on the
console. These tests pin:

  * all three analysis paths (walk-forward, CPCV, out-of-sample) report the
    block, and the CLI prints it next to the Deflated Sharpe line;
  * the primary backtest entry point (`run_backtest.py`) reports the block
    too, built on the very return series its Deflated Sharpe Ratio was
    computed on, and carries it in `metrics.json`;
  * the aggregate Deflated Alpha Ratio -- the statistic the alpha resolution
    belongs to -- is printed next to that resolution;
  * the block agrees with the `minimum_detectable_sharpe` /
    `minimum_detectable_alpha` helpers it is built from;
  * a statistic whose return series does not match is reported as "not
    resolvable" with a reason, never as a number;
  * a threshold beyond the stated plausibility bound is flagged, so a failed
    test can be read as a statement about the sample rather than about the
    strategy;
  * the block is reporting-only: it mutates nothing and changes no number;
  * a run without a significance test says so instead of staying silent;
  * the cost sweeps (`run_backtest.py --commissions` and its siblings) report
    the resolution of every sweep point beside its Sharpe, flag the points
    the sample cannot distinguish from zero, and move no swept number.

Run with: python3 skills/quantitative-backtesting/tests/test_test_resolution.py
No third-party test framework is required; uses only the standard library.
"""

import copy
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
    PLAUSIBLE_MAX_ANNUALIZED_ALPHA,
    PLAUSIBLE_MAX_ANNUALIZED_SHARPE,
    _build_test_resolution,
    _make_strategy_factory,
    _print_deflated_alpha,
    _print_test_resolution,
    cpcv_analysis,
    minimum_detectable_alpha,
    minimum_detectable_sharpe,
    out_of_sample_validation,
    walk_forward_analysis,
)
from run_backtest import (  # noqa: E402
    _sweep_resolution_fields,
    _sweep_sharpe_below_resolution,
)

SAMPLE_DATA = SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv"
SAMPLE_BENCHMARK = SKILLS_DIR / "assets" / "example_data" / "sample_benchmark.csv"
WALK_FORWARD_CLI = SKILLS_DIR / "scripts" / "walk_forward.py"
RUN_BACKTEST_CLI = SKILLS_DIR / "scripts" / "run_backtest.py"

MEANINGFUL_GRID = {"fast_period": [5, 10], "slow_period": [20, 30]}


def _make_ohlcv_data(periods: int = 600, seed: int = 42) -> pd.DataFrame:
    """OHLCV data with a mild trend, so the strategy takes positions."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    trend = np.linspace(0, 0.5, periods)
    returns = trend / periods + rng.normal(0, 0.01, periods)
    prices = 100 * np.exp(np.cumsum(returns))
    return pd.DataFrame({
        "open": prices * rng.uniform(0.995, 1.005, periods),
        "high": prices * rng.uniform(1.005, 1.02, periods),
        "low": prices * rng.uniform(0.98, 0.995, periods),
        "close": prices,
        "volume": rng.integers(1_000_000, 10_000_000, periods),
    }, index=dates)


def _make_benchmark_data(periods: int = 600, seed: int = 99) -> pd.DataFrame:
    """A second OHLCV series, used as a benchmark universe."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    trend = np.linspace(0, 0.3, periods)
    returns = trend / periods + rng.normal(0, 0.008, periods)
    prices = 100 * np.exp(np.cumsum(returns))
    return pd.DataFrame({
        "open": prices * rng.uniform(0.995, 1.005, periods),
        "high": prices * rng.uniform(1.005, 1.02, periods),
        "low": prices * rng.uniform(0.98, 0.995, periods),
        "close": prices,
        "volume": rng.integers(1_000_000, 10_000_000, periods),
    }, index=dates)


def _walk_forward_summary(apply_deflation=True, benchmark=None):
    data = _make_ohlcv_data()
    results = walk_forward_analysis(
        data=data,
        strategy_factory=_make_strategy_factory("sma_crossover"),
        param_grid=MEANINGFUL_GRID,
        train_months=12,
        test_months=3,
        step_months=3,
        apply_deflation=apply_deflation,
        benchmark=benchmark,
    )
    return results["summary"], results["oos_returns"]


def _cpcv_summary(apply_deflation=True, benchmark=None):
    data = _make_ohlcv_data()
    results = cpcv_analysis(
        data=data,
        strategy_factory=_make_strategy_factory("sma_crossover"),
        param_grid=MEANINGFUL_GRID,
        n_splits=5,
        test_size=0.5,
        apply_deflation=apply_deflation,
        benchmark=benchmark,
    )
    return results["summary"], results["oos_returns"]


def _out_of_sample_summary(apply_deflation=True, benchmark=None):
    data = _make_ohlcv_data()
    results = out_of_sample_validation(
        data=data,
        strategy_factory=_make_strategy_factory("sma_crossover"),
        param_grid=MEANINGFUL_GRID,
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        validation_method="walk_forward",
        walk_forward_train_months=12,
        walk_forward_test_months=3,
        walk_forward_step_months=3,
        apply_deflation=apply_deflation,
        benchmark=benchmark,
    )
    return results["summary"], results["test_performance"]["test_returns"]


# ---------------------------------------------------------------------------
# The block is reported by all three analysis paths
# ---------------------------------------------------------------------------

def test_walk_forward_summary_reports_the_test_resolution():
    """The walk-forward path reports what its significance test could detect."""
    summary, oos_returns = _walk_forward_summary(benchmark=_make_benchmark_data())

    resolution = summary.get("test_resolution")
    assert isinstance(resolution, dict), "walk-forward summary has no test_resolution"
    assert resolution["sharpe_status"] == "resolvable"
    assert resolution["min_detectable_sharpe"] is not None
    assert resolution["n_test_observations"] == len(oos_returns)
    assert resolution["n_parameter_trials"] == summary["deflated_sharpe"]["n_trials"]
    # A single benchmark produces no Deflated Alpha statistic to invert, so
    # the alpha resolution is reported as not applicable, not as a number.
    assert resolution["alpha_status"] == "not_applicable"
    assert resolution["min_detectable_alpha"] is None


def test_cpcv_summary_reports_the_test_resolution():
    """The CPCV path reports what its significance test could detect."""
    summary, oos_returns = _cpcv_summary(benchmark=_make_benchmark_data())

    resolution = summary.get("test_resolution")
    assert isinstance(resolution, dict), "CPCV summary has no test_resolution"
    assert resolution["sharpe_status"] == "resolvable"
    assert resolution["min_detectable_sharpe"] is not None
    assert resolution["n_test_observations"] == len(oos_returns)


def test_out_of_sample_summary_reports_the_test_resolution():
    """The out-of-sample path reports what its held-out test could detect."""
    summary, test_returns = _out_of_sample_summary(
        benchmark=[_make_benchmark_data(), _make_benchmark_data(seed=123)]
    )

    resolution = summary.get("test_resolution")
    assert isinstance(resolution, dict), "out-of-sample summary has no test_resolution"
    assert resolution["sharpe_status"] == "resolvable"
    assert resolution["alpha_status"] == "resolvable"
    assert resolution["min_detectable_sharpe"] is not None
    assert resolution["min_detectable_alpha"] is not None
    assert resolution["n_test_observations"] == len(test_returns)
    assert resolution["n_benchmarks"] == 2


# ---------------------------------------------------------------------------
# The block agrees with the helpers it is built from
# ---------------------------------------------------------------------------

def test_the_reported_resolution_matches_the_minimum_detectable_helpers():
    """The consolidated block carries the helpers' own numbers."""
    summary, oos_returns = _walk_forward_summary(benchmark=_make_benchmark_data())

    resolution = summary["test_resolution"]
    expected = minimum_detectable_sharpe(summary["deflated_sharpe"], oos_returns)
    assert resolution["min_detectable_sharpe"] == expected["minimum_detectable_sharpe"]
    assert resolution["observed_annualized_sharpe"] == summary["deflated_sharpe"]["sharpe_ratio"]
    # The pre-existing per-statistic key and the new consolidated block must
    # never disagree.
    assert (
        resolution["min_detectable_sharpe"]
        == summary["minimum_detectable_sharpe"]["minimum_detectable_sharpe"]
    )


def test_the_alpha_resolution_matches_the_minimum_detectable_helper():
    """The Deflated Alpha resolution comes from the same helper."""
    summary, test_returns = _out_of_sample_summary(
        benchmark=[_make_benchmark_data(), _make_benchmark_data(seed=123)]
    )

    resolution = summary["test_resolution"]
    expected = minimum_detectable_alpha(summary["deflated_alpha"], test_returns)
    assert resolution["min_detectable_alpha"] == expected["minimum_detectable_alpha"]
    assert (
        resolution["min_detectable_alpha"]
        == summary["minimum_detectable_alpha"]["minimum_detectable_alpha"]
    )


# ---------------------------------------------------------------------------
# "Not resolvable" is reported instead of a number
# ---------------------------------------------------------------------------

def test_an_unmatched_return_series_is_reported_as_not_resolvable():
    """A statistic computed on another series yields a reason, not a number."""
    summary, oos_returns = _walk_forward_summary(benchmark=_make_benchmark_data())

    # A return series that is not the one the statistic was computed on.
    wrong = oos_returns.iloc[:10]
    resolution = _build_test_resolution(summary, wrong)

    assert resolution["sharpe_status"] == "not_resolvable"
    assert resolution["sharpe_reason"] == "returns_do_not_match_statistic"
    assert resolution["min_detectable_sharpe"] is None
    assert "not computable" in resolution["message"]


def test_a_missing_return_series_is_reported_as_not_resolvable():
    """No return series at all yields a reason, not a number."""
    summary, _ = _walk_forward_summary(benchmark=_make_benchmark_data())

    resolution = _build_test_resolution(summary, None)
    assert resolution["sharpe_status"] == "not_resolvable"
    assert resolution["sharpe_reason"] == "no_returns"
    assert resolution["min_detectable_sharpe"] is None


# ---------------------------------------------------------------------------
# The plausibility bound
# ---------------------------------------------------------------------------

def test_thresholds_beyond_the_plausibility_bound_are_flagged():
    """A threshold the sample cannot resolve is flagged, not silently passed."""
    summary, oos_returns = _walk_forward_summary(benchmark=_make_benchmark_data())
    resolution = summary["test_resolution"]

    assert resolution["plausible_max_annualized_sharpe"] == PLAUSIBLE_MAX_ANNUALIZED_SHARPE
    assert resolution["plausible_max_annualized_alpha"] == PLAUSIBLE_MAX_ANNUALIZED_ALPHA
    assert resolution["sharpe_beyond_plausible_bound"] == (
        resolution["min_detectable_sharpe"] > PLAUSIBLE_MAX_ANNUALIZED_SHARPE
    )
    assert resolution["alpha_beyond_plausible_bound"] == (
        resolution["min_detectable_alpha"] is not None
        and resolution["min_detectable_alpha"] > PLAUSIBLE_MAX_ANNUALIZED_ALPHA
    )
    if resolution["sharpe_beyond_plausible_bound"]:
        assert "plausibility bound" in resolution["message"]


# ---------------------------------------------------------------------------
# The block is reporting-only
# ---------------------------------------------------------------------------

def test_the_resolution_block_mutates_nothing():
    """Building the block leaves the summary it was built from untouched."""
    summary, oos_returns = _walk_forward_summary(benchmark=_make_benchmark_data())
    before = copy.deepcopy(summary)

    _build_test_resolution(summary, oos_returns)

    assert summary == before, "the test-resolution block changed the summary"


def test_the_resolution_block_carries_no_verdict():
    """The block reports; it never decides."""
    summary, oos_returns = _walk_forward_summary(benchmark=_make_benchmark_data())
    resolution = summary["test_resolution"]

    for forbidden in ("verdict", "supported", "pass", "failed", "rejected"):
        assert forbidden not in resolution, (
            f"the test-resolution block must not carry a verdict key: {forbidden}"
        )
    # The p-value the verdict rests on is untouched by the block.
    assert resolution["target_p_value"] == 0.10
    assert summary["deflated_sharpe"]["p_value"] == 1.0 - summary["deflated_sharpe"]["deflated_sharpe_ratio"]


# ---------------------------------------------------------------------------
# A run without a significance test
# ---------------------------------------------------------------------------

def test_a_run_without_deflation_says_there_is_no_test_resolution():
    """No significance test means no resolution, and the artifact says so."""
    summary, _ = _walk_forward_summary(apply_deflation=False, benchmark=_make_benchmark_data())

    resolution = summary.get("test_resolution")
    assert isinstance(resolution, dict)
    assert resolution["sharpe_status"] == "not_applicable"
    assert resolution["alpha_status"] == "not_applicable"
    assert resolution["min_detectable_sharpe"] is None
    assert resolution["min_detectable_alpha"] is None
    assert "No significance test" in resolution["message"]


# ---------------------------------------------------------------------------
# The primary backtest entry point (run_backtest.py)
# ---------------------------------------------------------------------------

def _run_backtest_cli(extra_args, tmp):
    """Run the primary backtest CLI and return (result, metrics artifact)."""
    result = subprocess.run(
        [
            sys.executable, str(RUN_BACKTEST_CLI),
            "--data", str(SAMPLE_DATA),
            "--strategy", "sma_crossover",
            "--params", json.dumps({"fast_period": 10, "slow_period": 30}),
            "--output", tmp,
        ] + list(extra_args),
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert result.returncode == 0, (
        f"run_backtest CLI exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
    )
    metrics = json.loads((Path(tmp) / "metrics.json").read_text())
    return result, metrics


def test_the_run_backtest_cli_reports_the_test_resolution():
    """The primary backtest entry point reports what its test could detect."""
    with tempfile.TemporaryDirectory() as tmp:
        result, metrics = _run_backtest_cli(
            [
                "--n-trials", "12",
                "--benchmark", str(SAMPLE_BENCHMARK), str(SAMPLE_DATA),
            ],
            tmp,
        )

        assert "Test resolution (measurement, not a correction)" in result.stdout
        assert "Deflated Sharpe: smallest confirmable annualized Sharpe" in result.stdout
        assert "Deflated Alpha: smallest confirmable annualized alpha" in result.stdout

        resolution = metrics.get("test_resolution")
        assert isinstance(resolution, dict), "metrics.json has no test_resolution"
        assert resolution["sharpe_status"] == "resolvable"
        assert resolution["alpha_status"] == "resolvable"
        assert resolution["min_detectable_sharpe"] is not None
        assert resolution["min_detectable_alpha"] is not None

        # The resolution must be the resolution of *that* statistic: the
        # observation count and the observed effect are the Deflated Sharpe
        # Ratio's own, not a re-derivation over some other series.
        dsr = metrics["deflated_sharpe"]
        assert resolution["n_test_observations"] == dsr["n_observations"]
        assert resolution["n_parameter_trials"] == dsr["n_trials"]
        assert resolution["observed_annualized_sharpe"] == dsr["sharpe_ratio"]

        dar = metrics["deflated_alpha"]
        assert resolution["n_benchmarks"] == dar["n_benchmarks"]
        assert resolution["observed_annualized_alpha"] == dar["alpha"]

        # The console and the artifact carry the same numbers.
        assert f"{resolution['min_detectable_sharpe']:.4f}" in result.stdout
        assert f"{resolution['min_detectable_alpha']:.2%}" in result.stdout


def test_the_run_backtest_resolution_is_built_on_the_statistics_own_series():
    """The block and the helper agree when built the way run_backtest builds it.

    `run_backtest.py` reads the Deflated Sharpe Ratio out of the metrics
    `calculate_metrics` produced and inverts it on `results["returns"]` -- the
    same series `calculate_metrics` handed to `deflated_sharpe_ratio`. This
    pins that the two are the same numbers, and that the block is not built
    on a re-derived series.
    """
    from performance import calculate_metrics

    rng = np.random.default_rng(7)
    dates = pd.date_range("2021-01-01", periods=400, freq="B")
    returns = pd.Series(rng.normal(0.0004, 0.011, 400), index=dates)
    results = {
        "equity_curve": (1 + returns).cumprod() * 100000,
        "returns": returns,
        "config": {"n_trials": 9, "initial_capital": 100000},
    }
    metrics = calculate_metrics(results)

    resolution = _build_test_resolution(metrics, results["returns"])
    expected = minimum_detectable_sharpe(
        metrics["deflated_sharpe"], results["returns"]
    )
    assert resolution["sharpe_status"] == "resolvable"
    assert resolution["min_detectable_sharpe"] == expected["minimum_detectable_sharpe"]
    assert resolution["n_test_observations"] == metrics["deflated_sharpe"]["n_observations"]
    # A different series must not silently resolve the same statistic.
    other = _build_test_resolution(metrics, results["returns"].iloc[:10])
    assert other["sharpe_status"] == "not_resolvable"
    assert other["sharpe_reason"] == "returns_do_not_match_statistic"


def test_the_run_backtest_cli_says_so_when_no_significance_test_was_run():
    """A run without --n-trials reports that there is no resolution."""
    with tempfile.TemporaryDirectory() as tmp:
        result, metrics = _run_backtest_cli([], tmp)

        assert "No significance test was run" in result.stdout
        resolution = metrics["test_resolution"]
        assert resolution["sharpe_status"] == "not_applicable"
        assert resolution["alpha_status"] == "not_applicable"
        assert resolution["min_detectable_sharpe"] is None
        assert resolution["min_detectable_alpha"] is None


# ---------------------------------------------------------------------------
# The aggregate Deflated Alpha Ratio the alpha resolution belongs to
# ---------------------------------------------------------------------------

def test_the_aggregate_deflated_alpha_is_printed_next_to_the_resolution():
    """The statistic the alpha resolution belongs to is visible on the console."""
    import io
    from contextlib import redirect_stdout

    summary, _ = _out_of_sample_summary(
        benchmark=[_make_benchmark_data(), _make_benchmark_data(seed=123)]
    )
    dar = summary["deflated_alpha"]
    assert isinstance(dar, dict)

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        _print_deflated_alpha(dar)
    printed = buffer.getvalue()

    assert "Deflated Alpha Ratio" in printed
    assert f"{dar['deflated_alpha_ratio']:.4f}" in printed
    assert f"{dar['p_value']:.4f}" in printed
    assert f"{dar['n_benchmarks']} benchmarks" in printed


def test_the_walk_forward_cli_prints_the_aggregate_deflated_alpha():
    """The walk-forward CLI shows the aggregate DAR, not only its resolution."""
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [
                sys.executable, str(WALK_FORWARD_CLI), "walk-forward",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(MEANINGFUL_GRID),
                "--train-months", "12",
                "--test-months", "3",
                "--step-months", "3",
                "--deflate",
                "--benchmark", str(SAMPLE_BENCHMARK), str(SAMPLE_DATA),
                "--output", tmp,
            ],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        assert result.returncode == 0, (
            f"walk-forward CLI exited {result.returncode}\n"
            f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
        )

        artifact = json.loads(
            (Path(tmp) / "walk_forward_summary.json").read_text()
        )
        dar = artifact["summary"]["deflated_alpha"]
        assert "Deflated Alpha Ratio: " in result.stdout
        assert f"{dar['deflated_alpha_ratio']:.4f}" in result.stdout
        assert f"{dar['p_value']:.4f}" in result.stdout
        # The aggregate DAR is printed before the alpha resolution it belongs to.
        assert result.stdout.index("Deflated Alpha Ratio: ") < result.stdout.index(
            "Deflated Alpha: smallest confirmable annualized alpha"
        )


def test_the_cpcv_cli_prints_the_aggregate_deflated_alpha():
    """The CPCV CLI shows the aggregate DAR, not only its resolution."""
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [
                sys.executable, str(WALK_FORWARD_CLI), "cpcv",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(MEANINGFUL_GRID),
                "--n-splits", "5",
                "--test-size", "0.5",
                "--deflate",
                "--benchmark", str(SAMPLE_BENCHMARK), str(SAMPLE_DATA),
                "--output", tmp,
            ],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        assert result.returncode == 0, (
            f"cpcv CLI exited {result.returncode}\n"
            f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
        )

        artifact = json.loads((Path(tmp) / "cpcv_summary.json").read_text())
        dar = artifact["summary"]["deflated_alpha"]
        assert "Deflated Alpha Ratio: " in result.stdout
        assert f"{dar['deflated_alpha_ratio']:.4f}" in result.stdout
        assert f"{dar['p_value']:.4f}" in result.stdout


def test_the_out_of_sample_cli_prints_the_aggregate_deflated_alpha():
    """The out-of-sample CLI shows the aggregate DAR it deflates against."""
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [
                sys.executable, str(WALK_FORWARD_CLI), "out-of-sample",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(MEANINGFUL_GRID),
                "--deflate",
                "--benchmark", str(SAMPLE_BENCHMARK), str(SAMPLE_DATA),
                "--output", tmp,
            ],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        assert result.returncode == 0, (
            f"out-of-sample CLI exited {result.returncode}\n"
            f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
        )

        artifact = json.loads(
            (Path(tmp) / "out_of_sample_summary.json").read_text()
        )
        dar = artifact["summary"]["deflated_alpha"]
        assert "Deflated Alpha Ratio (test): " in result.stdout
        assert f"{dar['deflated_alpha_ratio']:.4f}" in result.stdout
        assert f"{dar['p_value']:.4f}" in result.stdout


# ---------------------------------------------------------------------------
# The console
# ---------------------------------------------------------------------------

def test_the_console_prints_the_resolution_and_its_wording():
    """The console states that the block is a measurement, not a correction."""
    summary, oos_returns = _walk_forward_summary(benchmark=_make_benchmark_data())
    resolution = summary["test_resolution"]

    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        _print_test_resolution(resolution)
    printed = buffer.getvalue()

    assert "Test resolution" in printed
    assert "measurement, not a correction" in printed
    assert f"{resolution['min_detectable_sharpe']:.4f}" in printed


def test_the_walk_forward_cli_prints_the_test_resolution():
    """The CLI prints the resolution next to the Deflated Sharpe line."""
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [
                sys.executable, str(WALK_FORWARD_CLI), "walk-forward",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(MEANINGFUL_GRID),
                "--train-months", "12",
                "--test-months", "3",
                "--step-months", "3",
                "--deflate",
                "--benchmark", str(SAMPLE_BENCHMARK),
                "--output", tmp,
            ],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        assert result.returncode == 0, (
            f"walk-forward CLI exited {result.returncode}\n"
            f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
        )
        assert "Test resolution (measurement, not a correction)" in result.stdout
        assert "Deflated Sharpe: smallest confirmable annualized Sharpe" in result.stdout

        artifact = json.loads(
            (Path(tmp) / "walk_forward_summary.json").read_text()
        )
        resolution = artifact["summary"]["test_resolution"]
        assert resolution["sharpe_status"] == "resolvable"
        assert resolution["min_detectable_sharpe"] is not None
        # The console and the artifact carry the same number.
        assert f"{resolution['min_detectable_sharpe']:.4f}" in result.stdout


def test_the_out_of_sample_cli_prints_the_test_resolution():
    """The out-of-sample CLI prints the resolution of the held-out test."""
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [
                sys.executable, str(WALK_FORWARD_CLI), "out-of-sample",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(MEANINGFUL_GRID),
                "--deflate",
                "--benchmark", str(SAMPLE_BENCHMARK), str(SAMPLE_DATA),
                "--output", tmp,
            ],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        assert result.returncode == 0, (
            f"out-of-sample CLI exited {result.returncode}\n"
            f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
        )
        assert "Test resolution (measurement, not a correction)" in result.stdout
        assert "Deflated Alpha: smallest confirmable annualized alpha" in result.stdout

        artifact = json.loads(
            (Path(tmp) / "out_of_sample_summary.json").read_text()
        )
        resolution = artifact["summary"]["test_resolution"]
        assert resolution["sharpe_status"] == "resolvable"
        assert resolution["alpha_status"] == "resolvable"
        assert f"{resolution['min_detectable_alpha']:.2%}" in result.stdout


# ---------------------------------------------------------------------------
# The cost sweeps (run_backtest.py --commissions and its siblings)
# ---------------------------------------------------------------------------

def _run_sweep_cli(extra_args, tmp):
    """Run a cost sweep through the primary backtest CLI."""
    result = subprocess.run(
        [
            sys.executable, str(RUN_BACKTEST_CLI),
            "--data", str(SAMPLE_DATA),
            "--strategy", "sma_crossover",
            "--params", json.dumps({"fast_period": 10, "slow_period": 30}),
            "--output", tmp,
        ] + list(extra_args),
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert result.returncode == 0, (
        f"run_backtest CLI exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
    )
    return result


def _commission_sweep_payload(tmp):
    return json.loads(
        (Path(tmp) / "run_backtest_commission_sweep.json").read_text()
    )


def test_every_sweep_point_carries_its_own_test_resolution():
    """Each sweep point reports the resolution of its own statistics.

    A sweep reports one Sharpe per cost level. Without the resolution of the
    statistics that produced it, "Sharpe 1.42 at 2 bps" and "Sharpe 0.31 at
    8 bps" read as a difference the sample may not be able to see.
    """
    with tempfile.TemporaryDirectory() as tmp:
        _run_sweep_cli(
            ["--n-trials", "12", "--commissions", "0.0002", "0.002", "0.004"], tmp
        )
        payload = _commission_sweep_payload(tmp)

    points = payload["results"]
    assert len(points) == 3
    for point in points:
        resolution = point.get("test_resolution")
        assert isinstance(resolution, dict), "sweep point has no test_resolution"
        assert resolution["sharpe_status"] == "resolvable"
        assert resolution["min_detectable_sharpe"] is not None
        assert resolution["min_detectable_sharpe"] > 0
        assert resolution["n_parameter_trials"] == 12
        # The block describes *this* point's statistics: the observed effect is
        # the point's own reported Sharpe, not another coefficient's.
        assert resolution["observed_annualized_sharpe"] == point["sharpe_ratio"]
        assert resolution["n_test_observations"] is not None


def test_the_sweep_point_reports_exactly_what_the_single_run_reports():
    """The sweep point and the single run are the same run.

    The resolution is a measurement attached to a run, so it must not change
    the run: the sweep point for a coefficient and the single run at that
    coefficient report the same numbers and the same resolution.
    """
    with tempfile.TemporaryDirectory() as tmp:
        sweep_dir = Path(tmp) / "sweep"
        single_dir = Path(tmp) / "single"
        _run_sweep_cli(
            ["--n-trials", "12", "--commissions", "0.0002", "0.002"], str(sweep_dir)
        )
        _run_sweep_cli(
            ["--n-trials", "12", "--commission", "0.002"], str(single_dir)
        )
        payload = _commission_sweep_payload(sweep_dir)
        metrics = json.loads((single_dir / "metrics.json").read_text())

    point = [p for p in payload["results"] if p["commission"] == 0.002][0]
    for key in ("total_return", "annualized_return", "sharpe_ratio", "max_drawdown"):
        assert point[key] == metrics[key], (
            f"{key} moved between the sweep point and the single run"
        )
    assert point["test_resolution"] == metrics["test_resolution"]


def test_the_sweep_table_prints_the_threshold_next_to_the_sharpe():
    """The swept Sharpe is read next to what the sample could resolve."""
    with tempfile.TemporaryDirectory() as tmp:
        result = _run_sweep_cli(
            ["--n-trials", "12", "--commissions", "0.0002", "0.002"], tmp
        )
        payload = _commission_sweep_payload(tmp)

    stdout = result.stdout
    assert "minSR" in stdout, "the sweep table has no resolution column"
    assert "Test resolution (measurement, not a correction)" in stdout
    for point in payload["results"]:
        threshold = point["test_resolution"]["min_detectable_sharpe"]
        # The console and the artifact carry the same numbers.
        assert f"{threshold:.4f}" in stdout
        assert f"{point['sharpe_ratio']:.4f}" in stdout


def test_the_below_resolution_flag_compares_magnitudes():
    """A Sharpe the sample cannot resolve is flagged, not called a failure.

    The minimum detectable effect is the smallest *magnitude* the test could
    confirm, so a large negative Sharpe is resolvable and a small positive
    one is not. A signed comparison would get both backwards.
    """
    resolution = {
        "sharpe_status": "resolvable",
        "min_detectable_sharpe": 2.0,
        "observed_annualized_sharpe": 0.31,
    }
    assert _sweep_sharpe_below_resolution(0.31, resolution) is True
    assert _sweep_sharpe_below_resolution(2.5, resolution) is False
    assert _sweep_sharpe_below_resolution(-3.0, resolution) is False
    # No resolution means "unknown", never "not below".
    assert _sweep_sharpe_below_resolution(0.31, None) is None
    assert _sweep_sharpe_below_resolution(
        0.31, {"sharpe_status": "not_applicable"}
    ) is None

    fields = _sweep_resolution_fields({
        "sharpe_ratio": 0.31,
        "test_resolution": resolution,
    })
    assert fields == ("2.0000", "below resolution")
    above = _sweep_resolution_fields({
        "sharpe_ratio": 2.5,
        "test_resolution": resolution,
    })
    assert above == ("2.0000", "resolvable")


def test_the_sweep_flags_the_points_the_sample_cannot_distinguish_from_zero():
    """Every swept point carries the flag, and the console shows it."""
    with tempfile.TemporaryDirectory() as tmp:
        result = _run_sweep_cli(
            ["--n-trials", "12", "--commissions", "0.0002", "0.002"], tmp
        )
        payload = _commission_sweep_payload(tmp)

    for point in payload["results"]:
        threshold = point["test_resolution"]["min_detectable_sharpe"]
        expected = abs(point["sharpe_ratio"]) < threshold
        assert point["sharpe_below_resolution"] is expected
    assert "below resolution" in result.stdout
    assert "cannot distinguish from zero" in result.stdout
    assert "measures the sample, not the strategy" in result.stdout


def test_a_sweep_without_a_significance_test_says_so():
    """No significance test means no resolution, and the sweep says so."""
    with tempfile.TemporaryDirectory() as tmp:
        result = _run_sweep_cli(["--commissions", "0.0002", "0.002"], tmp)
        payload = _commission_sweep_payload(tmp)

    assert "no significance test was run" in result.stdout
    assert "n/a" in result.stdout
    for point in payload["results"]:
        resolution = point["test_resolution"]
        assert resolution["sharpe_status"] == "not_applicable"
        assert resolution["min_detectable_sharpe"] is None
        # Unknown, not "not below".
        assert point["sharpe_below_resolution"] is None


def test_the_sweep_point_resolution_carries_no_verdict():
    """The sweep's block reports; it never decides."""
    with tempfile.TemporaryDirectory() as tmp:
        _run_sweep_cli(
            ["--n-trials", "12", "--commissions", "0.0002", "0.002"], tmp
        )
        payload = _commission_sweep_payload(tmp)

    for point in payload["results"]:
        resolution = point["test_resolution"]
        for forbidden in ("verdict", "supported", "pass", "failed", "rejected"):
            assert forbidden not in resolution, (
                f"the sweep's test-resolution block must not carry a verdict "
                f"key: {forbidden}"
            )
        assert resolution["target_p_value"] == 0.10
        # The plausibility bounds are the framework's, and unmoved.
        assert resolution["plausible_max_annualized_sharpe"] == (
            PLAUSIBLE_MAX_ANNUALIZED_SHARPE
        )
        assert resolution["plausible_max_annualized_alpha"] == (
            PLAUSIBLE_MAX_ANNUALIZED_ALPHA
        )


# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------

TEST_REGISTRY = [
    ("test_walk_forward_summary_reports_the_test_resolution",
     test_walk_forward_summary_reports_the_test_resolution),
    ("test_cpcv_summary_reports_the_test_resolution",
     test_cpcv_summary_reports_the_test_resolution),
    ("test_out_of_sample_summary_reports_the_test_resolution",
     test_out_of_sample_summary_reports_the_test_resolution),
    ("test_the_reported_resolution_matches_the_minimum_detectable_helpers",
     test_the_reported_resolution_matches_the_minimum_detectable_helpers),
    ("test_the_alpha_resolution_matches_the_minimum_detectable_helper",
     test_the_alpha_resolution_matches_the_minimum_detectable_helper),
    ("test_an_unmatched_return_series_is_reported_as_not_resolvable",
     test_an_unmatched_return_series_is_reported_as_not_resolvable),
    ("test_a_missing_return_series_is_reported_as_not_resolvable",
     test_a_missing_return_series_is_reported_as_not_resolvable),
    ("test_thresholds_beyond_the_plausibility_bound_are_flagged",
     test_thresholds_beyond_the_plausibility_bound_are_flagged),
    ("test_the_resolution_block_mutates_nothing",
     test_the_resolution_block_mutates_nothing),
    ("test_the_resolution_block_carries_no_verdict",
     test_the_resolution_block_carries_no_verdict),
    ("test_a_run_without_deflation_says_there_is_no_test_resolution",
     test_a_run_without_deflation_says_there_is_no_test_resolution),
    ("test_the_run_backtest_cli_reports_the_test_resolution",
     test_the_run_backtest_cli_reports_the_test_resolution),
    ("test_the_run_backtest_resolution_is_built_on_the_statistics_own_series",
     test_the_run_backtest_resolution_is_built_on_the_statistics_own_series),
    ("test_the_run_backtest_cli_says_so_when_no_significance_test_was_run",
     test_the_run_backtest_cli_says_so_when_no_significance_test_was_run),
    ("test_the_aggregate_deflated_alpha_is_printed_next_to_the_resolution",
     test_the_aggregate_deflated_alpha_is_printed_next_to_the_resolution),
    ("test_the_walk_forward_cli_prints_the_aggregate_deflated_alpha",
     test_the_walk_forward_cli_prints_the_aggregate_deflated_alpha),
    ("test_the_cpcv_cli_prints_the_aggregate_deflated_alpha",
     test_the_cpcv_cli_prints_the_aggregate_deflated_alpha),
    ("test_the_out_of_sample_cli_prints_the_aggregate_deflated_alpha",
     test_the_out_of_sample_cli_prints_the_aggregate_deflated_alpha),
    ("test_the_console_prints_the_resolution_and_its_wording",
     test_the_console_prints_the_resolution_and_its_wording),
    ("test_the_walk_forward_cli_prints_the_test_resolution",
     test_the_walk_forward_cli_prints_the_test_resolution),
    ("test_the_out_of_sample_cli_prints_the_test_resolution",
     test_the_out_of_sample_cli_prints_the_test_resolution),
    ("test_every_sweep_point_carries_its_own_test_resolution",
     test_every_sweep_point_carries_its_own_test_resolution),
    ("test_the_sweep_point_reports_exactly_what_the_single_run_reports",
     test_the_sweep_point_reports_exactly_what_the_single_run_reports),
    ("test_the_sweep_table_prints_the_threshold_next_to_the_sharpe",
     test_the_sweep_table_prints_the_threshold_next_to_the_sharpe),
    ("test_the_below_resolution_flag_compares_magnitudes",
     test_the_below_resolution_flag_compares_magnitudes),
    ("test_the_sweep_flags_the_points_the_sample_cannot_distinguish_from_zero",
     test_the_sweep_flags_the_points_the_sample_cannot_distinguish_from_zero),
    ("test_a_sweep_without_a_significance_test_says_so",
     test_a_sweep_without_a_significance_test_says_so),
    ("test_the_sweep_point_resolution_carries_no_verdict",
     test_the_sweep_point_resolution_carries_no_verdict),
]


def main() -> int:
    failures = 0
    for name, fn in TEST_REGISTRY:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(TEST_REGISTRY) - failures}/{len(TEST_REGISTRY)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
