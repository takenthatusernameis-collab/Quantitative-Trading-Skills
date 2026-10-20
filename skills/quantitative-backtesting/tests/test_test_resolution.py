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
  * the block agrees with the `minimum_detectable_sharpe` /
    `minimum_detectable_alpha` helpers it is built from;
  * a statistic whose return series does not match is reported as "not
    resolvable" with a reason, never as a number;
  * a threshold beyond the stated plausibility bound is flagged, so a failed
    test can be read as a statement about the sample rather than about the
    strategy;
  * the block is reporting-only: it mutates nothing and changes no number;
  * a run without a significance test says so instead of staying silent.

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
    _print_test_resolution,
    cpcv_analysis,
    minimum_detectable_alpha,
    minimum_detectable_sharpe,
    out_of_sample_validation,
    walk_forward_analysis,
)

SAMPLE_DATA = SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv"
SAMPLE_BENCHMARK = SKILLS_DIR / "assets" / "example_data" / "sample_benchmark.csv"
WALK_FORWARD_CLI = SKILLS_DIR / "scripts" / "walk_forward.py"

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
    ("test_the_console_prints_the_resolution_and_its_wording",
     test_the_console_prints_the_resolution_and_its_wording),
    ("test_the_walk_forward_cli_prints_the_test_resolution",
     test_the_walk_forward_cli_prints_the_test_resolution),
    ("test_the_out_of_sample_cli_prints_the_test_resolution",
     test_the_out_of_sample_cli_prints_the_test_resolution),
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
