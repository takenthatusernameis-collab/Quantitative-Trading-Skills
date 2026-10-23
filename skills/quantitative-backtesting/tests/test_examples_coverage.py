#!/usr/bin/env python3
"""Regression tests for the three worked examples that lacked executable coverage.

The existing suite already guards `real_data_pipeline_example.py`,
`trading_costs_robustness_example.py`, and `falsifiable_hypothesis_example.py`
(imports + end-to-end run).  This file adds the same treatment to the remaining
three examples in `examples/`:
  - `deflated_alpha_example.py`           (direct Deflated Alpha Ratio demo)
  - `multiple_benchmarks_example.py`       (multi-benchmark DAR via calculate_metrics)
  - `full_pipeline_example.py`             (end-to-end data->report pipeline)

Each test asserts the example imports cleanly, exposes its documented entry
point, runs end-to-end on the shipped sample fixtures (no network), exits 0,
and prints its completion banner.  No claim is made about the verdicts or
metric values themselves; these tests guard executability and API stability.
"""

import re
import subprocess
import sys
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent

_DEFLATED_PATH = SKILLS_DIR / "examples" / "deflated_alpha_example.py"
_MULTIPLE_PATH = SKILLS_DIR / "examples" / "multiple_benchmarks_example.py"
_FULL_PIPELINE_PATH = SKILLS_DIR / "examples" / "full_pipeline_example.py"
_PAIRS_PATH = SKILLS_DIR / "examples" / "pairs_trading_example.py"
_COSTS_PATH = SKILLS_DIR / "examples" / "trading_costs_robustness_example.py"
_SIMPLE_MOMENTUM_PATH = SKILLS_DIR / "examples" / "simple_momentum_hypothesis.py"
_MEAN_REVERSION_PATH = SKILLS_DIR / "examples" / "mean_reversion_hypothesis.py"
_RSI_MR_PATH = SKILLS_DIR / "examples" / "rsi_mean_reversion_hypothesis.py"
_ZSCORE_MR_PATH = SKILLS_DIR / "examples" / "zscore_mean_reversion_hypothesis.py"
_REAL_DATA_PIPELINE_PATH = SKILLS_DIR / "examples" / "real_data_pipeline_example.py"


def _import_module(name, path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# deflated_alpha_example.py
# ---------------------------------------------------------------------------

def test_deflated_alpha_example_imports():
    module = _import_module("deflated_alpha_example", _DEFLATED_PATH)
    assert hasattr(module, "run_deflated_alpha_example")
    assert callable(module.run_deflated_alpha_example)


def test_deflated_alpha_example_runs():
    result = subprocess.run(
        [sys.executable, str(_DEFLATED_PATH)],
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"deflated_alpha_example exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
    )
    assert "EXAMPLE COMPLETE" in result.stdout
    # The three scenarios (N=1, N=5, N=10) must each print a DAR and p-value.
    assert result.stdout.count("DAR:") >= 3, (
        "expected at least 3 DAR lines (N=1, N=5, N=10)"
    )
    # p-value is printed in both lowercase ("p-value:") and title-case
    # ("P-value:") forms across the three scenarios.
    assert result.stdout.lower().count("p-value:") >= 3
    # DAR must stay within [0, 1] for every scenario.
    for m in re.finditer(r"DAR:\s*([0-9.]+)", result.stdout):
        assert 0.0 <= float(m.group(1)) <= 1.0, (
            f"DAR out of range: {m.group(1)}"
        )


# ---------------------------------------------------------------------------
# multiple_benchmarks_example.py
# ---------------------------------------------------------------------------

def test_multiple_benchmarks_example_imports():
    module = _import_module("multiple_benchmarks_example", _MULTIPLE_PATH)
    assert hasattr(module, "run_multiple_benchmarks_example")
    assert callable(module.run_multiple_benchmarks_example)


def test_multiple_benchmarks_example_runs():
    result = subprocess.run(
        [sys.executable, str(_MULTIPLE_PATH)],
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"multiple_benchmarks_example exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
    )
    assert "MULTIPLE BENCHMARKS EXAMPLE COMPLETE" in result.stdout
    assert "Deflated Alpha Ratio (DAR):" in result.stdout
    assert "P-value (DAR):" in result.stdout
    assert "Number of Benchmarks (N):" in result.stdout
    assert "Trial alphas collected:" in result.stdout
    # DAR and p-value must be within [0, 1].
    m = re.search(r"Deflated Alpha Ratio \(DAR\):\s*([0-9.]+)", result.stdout)
    assert m, "DAR line missing"
    assert 0.0 <= float(m.group(1)) <= 1.0
    m = re.search(r"P-value \(DAR\):\s*([0-9.]+)", result.stdout)
    assert m, "p-value line missing"
    assert 0.0 <= float(m.group(1)) <= 1.0


# ---------------------------------------------------------------------------
# full_pipeline_example.py
# ---------------------------------------------------------------------------

def test_full_pipeline_example_imports():
    module = _import_module("full_pipeline_example", _FULL_PIPELINE_PATH)
    assert hasattr(module, "run_full_pipeline")
    assert callable(module.run_full_pipeline)


def test_full_pipeline_example_runs():
    result = subprocess.run(
        [sys.executable, str(_FULL_PIPELINE_PATH)],
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"full_pipeline_example exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
    )
    assert "FULL PIPELINE EXAMPLE COMPLETE" in result.stdout
    # The pipeline must surface the key stages.
    for stage in (
        "LOADING DATA WITH PROVENANCE TRACKING",
        "DATA QUALITY VALIDATION",
        "POINT-IN-TIME VALIDATION",
        "SURVIVORSHIP BIAS DETECTION",
        "RUNNING BACKTEST WITH TRANSACTION COSTS",
        "BENCHMARK COMPARISON",
        "COMPUTING PERFORMANCE METRICS",
        "GENERATING REPORTS AND TEAR SHEETS",
    ):
        assert stage in result.stdout, f"pipeline stage missing: {stage}"


def test_full_pipeline_example_surfaces_single_benchmark_significance():
    """Stage 7 prints the alpha t-stat / p-value from the canonical keys.

    Regression guard for a defect where the example read ``alpha_t_stat``
    (with an underscore) while ``performance._benchmark_stats`` emits
    ``alpha_tstat`` -- the same key the tear sheet and text report render
    under -- so the significance block silently never fired and the
    pipeline claimed a stage it did not actually print.
    """
    result = subprocess.run(
        [sys.executable, str(_FULL_PIPELINE_PATH)],
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"full_pipeline_example exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
    )
    assert "Alpha t-stat:" in result.stdout, (
        "stage 7 must print the alpha t-statistic for the single-benchmark case"
    )
    assert "Alpha p-value:" in result.stdout, (
        "stage 7 must print the alpha p-value for the single-benchmark case"
    )


# ---------------------------------------------------------------------------
# pairs_trading_example.py
# ---------------------------------------------------------------------------

def test_pairs_trading_example_imports():
    module = _import_module("pairs_trading_example", _PAIRS_PATH)
    assert hasattr(module, "main")
    assert callable(module.main)


def test_pairs_trading_example_runs():
    result = subprocess.run(
        [sys.executable, str(_PAIRS_PATH)],
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"pairs_trading_example exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
    )
    assert "Pairs trading example complete!" in result.stdout


def test_pairs_trading_example_emits_realistic_prices():
    """The synthetic pair must be priced in real dollar ranges, not ~1e43.

    Regression guard for a defect where the log-price was anchored at 100
    (a raw log level) and then exponentiated, producing prices of ~1e43
    dollars -- a correlated pair that was technically valid but priced in a
    universe the no bankroll could trade. The log-price must be anchored at
    log(100) so exp() yields a realistic price near $100.
    """
    result = subprocess.run(
        [sys.executable, str(_PAIRS_PATH)],
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"pairs_trading_example exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
    )
    # The banner prints each asset's price range as "$min - $max".
    import re
    ranges = re.findall(r"price range \$(.*) - \$(.*)", result.stdout)
    assert len(ranges) >= 2, "asset price ranges not printed"
    for low, high in ranges:
        lo = float(low.replace(",", ""))
        hi = float(high.replace(",", ""))
        assert 1.0 <= lo <= 1e6, f"implausible low price: {lo}"
        assert 1.0 <= hi <= 1e6, f"implausible high price: {hi}"


def test_pairs_trading_example_writes_report_to_directory():
    """generate_report writes report.txt into the output directory.

    Regression guard for passing a file path (and the wrong dict shape) to
    generate_report, which expects a directory and a metrics dict and therefore
    created a nested report.txt/report.txt.
    """
    result = subprocess.run(
        [sys.executable, str(_PAIRS_PATH)],
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"pairs_trading_example exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
    )
    report = _PAIRS_PATH.parent / "example_output" / "pairs_trading" / "report.txt"
    assert report.is_file(), f"report.txt not written to {report}"
    # The nested path defect would have left a report.txt *directory* instead.
    assert not report.is_dir(), "report.txt is a directory (nested path defect)"


# ---------------------------------------------------------------------------
# trading_costs_robustness_example.py
# ---------------------------------------------------------------------------


def test_trading_costs_robustness_example_imports():
    module = _import_module("trading_costs_robustness_example", _COSTS_PATH)
    assert hasattr(module, "main")
    assert callable(module.main)


def test_trading_costs_robustness_example_runs():
    result = subprocess.run(
        [sys.executable, str(_COSTS_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"trading_costs_robustness_example exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "TRADING COSTS SENSITIVITY ANALYSIS COMPLETE" in result.stdout


def test_trading_costs_robustness_example_shows_cost_sensitivity():
    """Higher costs reduce net performance in the strategy cost sweep."""
    result = subprocess.run(
        [sys.executable, str(_COSTS_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"trading_costs_robustness_example exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    # Cost sweep must be printed and show degradation
    assert "STRATEGY COST SENSITIVITY SWEEP" in result.stdout
    assert "Sharpe" in result.stdout
    assert "0 bps" in result.stdout
    # The key findings must state cost degradation
    assert "Strategy transaction costs" in result.stdout


# ---------------------------------------------------------------------------
# simple_momentum_hypothesis.py
# ---------------------------------------------------------------------------


def test_simple_momentum_hypothesis_imports():
    """simple_momentum_hypothesis must be importable as a module."""
    module = _import_module("simple_momentum_hypothesis", _SIMPLE_MOMENTUM_PATH)
    assert hasattr(module, "run_hypothesis_test")


def test_simple_momentum_hypothesis_runs():
    """simple_momentum_hypothesis must run end-to-end and exit 0."""
    result = subprocess.run(
        [sys.executable, str(_SIMPLE_MOMENTUM_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"simple_momentum_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "FALSIFIABLE HYPOTHESIS TEST" in result.stdout


def test_simple_momentum_hypothesis_emits_hypothesis_and_costs():
    """simple_momentum_hypothesis reports hypothesis, costs, and falsification criteria."""
    result = subprocess.run(
        [sys.executable, str(_SIMPLE_MOMENTUM_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"simple_momentum_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    # Must state the hypothesis and trading costs
    assert "SMA-crossover trend-following" in result.stdout
    assert "bps" in result.stdout
    assert "FALSIFICATION CRITERIA" in result.stdout
    # Must report out-of-sample performance
    assert "OUT-OF-SAMPLE PERFORMANCE" in result.stdout
    assert "Sharpe Ratio" in result.stdout


def test_simple_momentum_hypothesis_uses_point_in_time_split():
    """simple_momentum_hypothesis uses chronological train/val/test and point-in-time validation."""
    result = subprocess.run(
        [sys.executable, str(_SIMPLE_MOMENTUM_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"simple_momentum_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    # Must show methodology controls
    assert "METHODOLOGY CONTROLS" in result.stdout
    assert "train/val/test" in result.stdout
    assert "Point-in-time validation" in result.stdout


# ---------------------------------------------------------------------------
# mean_reversion_hypothesis.py
# ---------------------------------------------------------------------------


def test_mean_reversion_hypothesis_imports():
    """mean_reversion_hypothesis must be importable as a module."""
    module = _import_module("mean_reversion_hypothesis", _MEAN_REVERSION_PATH)
    assert hasattr(module, "run_hypothesis_test")


def test_mean_reversion_hypothesis_runs():
    """mean_reversion_hypothesis must run end-to-end and exit 0."""
    result = subprocess.run(
        [sys.executable, str(_MEAN_REVERSION_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"mean_reversion_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "FALSIFIABLE HYPOTHESIS TEST" in result.stdout


def test_mean_reversion_hypothesis_emits_hypothesis_and_costs():
    """mean_reversion_hypothesis reports hypothesis, costs, and falsification criteria."""
    result = subprocess.run(
        [sys.executable, str(_MEAN_REVERSION_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"mean_reversion_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    # Must state the hypothesis and trading costs
    assert "Bollinger Bands mean-reversion" in result.stdout
    assert "bps" in result.stdout
    assert "FALSIFICATION CRITERIA" in result.stdout
    # Must report out-of-sample performance
    assert "OUT-OF-SAMPLE PERFORMANCE" in result.stdout
    assert "Sharpe Ratio" in result.stdout


def test_mean_reversion_hypothesis_uses_point_in_time_split():
    """mean_reversion_hypothesis uses chronological train/val/test and point-in-time validation."""
    result = subprocess.run(
        [sys.executable, str(_MEAN_REVERSION_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"mean_reversion_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    # Must show methodology controls
    assert "METHODOLOGY CONTROLS" in result.stdout
    assert "train/val/test" in result.stdout
    assert "Point-in-time validation" in result.stdout


# ---------------------------------------------------------------------------
# rsi_mean_reversion_hypothesis.py
# ---------------------------------------------------------------------------


_RSI_MR_PATH = SKILLS_DIR / "examples" / "rsi_mean_reversion_hypothesis.py"
_ZSCORE_MR_PATH = SKILLS_DIR / "examples" / "zscore_mean_reversion_hypothesis.py"


def test_rsi_mean_reversion_hypothesis_imports():
    """rsi_mean_reversion_hypothesis must be importable as a module."""
    module = _import_module("rsi_mean_reversion_hypothesis", _RSI_MR_PATH)
    assert hasattr(module, "run_hypothesis_test")


def test_rsi_mean_reversion_hypothesis_runs():
    """rsi_mean_reversion_hypothesis must run end-to-end and exit 0."""
    result = subprocess.run(
        [sys.executable, str(_RSI_MR_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"rsi_mean_reversion_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "FALSIFIABLE HYPOTHESIS TEST" in result.stdout


def test_rsi_mean_reversion_hypothesis_emits_hypothesis_and_costs():
    """rsi_mean_reversion_hypothesis reports hypothesis, costs, and falsification criteria."""
    result = subprocess.run(
        [sys.executable, str(_RSI_MR_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"rsi_mean_reversion_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    # Must state the hypothesis and trading costs
    assert "RSI mean-reversion" in result.stdout
    assert "bps" in result.stdout
    assert "FALSIFICATION CRITERIA" in result.stdout
    # Must report out-of-sample performance
    assert "OUT-OF-SAMPLE PERFORMANCE" in result.stdout
    assert "Sharpe Ratio" in result.stdout


def test_rsi_mean_reversion_hypothesis_uses_point_in_time_split():
    """rsi_mean_reversion_hypothesis uses chronological train/val/test and point-in-time validation."""
    result = subprocess.run(
        [sys.executable, str(_RSI_MR_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"rsi_mean_reversion_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    # Must show methodology controls
    assert "METHODOLOGY CONTROLS" in result.stdout
    assert "train/val/test" in result.stdout
    assert "Point-in-time validation" in result.stdout


# ---------------------------------------------------------------------------
# zscore_mean_reversion_hypothesis.py
# ---------------------------------------------------------------------------


def test_zscore_mean_reversion_hypothesis_imports():
    """zscore_mean_reversion_hypothesis must be importable as a module."""
    module = _import_module("zscore_mean_reversion_hypothesis", _ZSCORE_MR_PATH)
    assert hasattr(module, "run_hypothesis_test")


def test_zscore_mean_reversion_hypothesis_runs():
    """zscore_mean_reversion_hypothesis must run end-to-end and exit 0."""
    result = subprocess.run(
        [sys.executable, str(_ZSCORE_MR_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"zscore_mean_reversion_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "FALSIFIABLE HYPOTHESIS TEST" in result.stdout


def test_zscore_mean_reversion_hypothesis_emits_hypothesis_and_costs():
    """zscore_mean_reversion_hypothesis reports hypothesis, costs, and falsification criteria."""
    result = subprocess.run(
        [sys.executable, str(_ZSCORE_MR_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"zscore_mean_reversion_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    # Must state the hypothesis and trading costs
    assert "Z-Score" in result.stdout
    assert "bps" in result.stdout
    assert "FALSIFICATION CRITERIA" in result.stdout
    # Must report out-of-sample performance
    assert "OUT-OF-SAMPLE PERFORMANCE" in result.stdout
    assert "Sharpe Ratio" in result.stdout


def test_zscore_mean_reversion_hypothesis_uses_point_in_time_split():
    """zscore_mean_reversion_hypothesis uses chronological train/val/test and point-in-time validation."""
    result = subprocess.run(
        [sys.executable, str(_ZSCORE_MR_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"zscore_mean_reversion_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    # Must show methodology controls
    assert "METHODOLOGY CONTROLS" in result.stdout
    assert "train/val/test" in result.stdout
    assert "Point-in-time validation" in result.stdout


# ---------------------------------------------------------------------------
# real_data_pipeline_example.py
# ---------------------------------------------------------------------------


def test_real_data_pipeline_example_imports():
    """real_data_pipeline_example must import cleanly and expose key callables."""
    module = _import_module("real_data_pipeline_example", _REAL_DATA_PIPELINE_PATH)
    for name in (
        "main",
        "generate_synthetic_universe",
        "run_pit_validation",
        "run_survivorship_detection",
        "run_cpcv_validation",
        "run_cli_cpcv_validation",
        "run_cli_monte_carlo",
        "demonstrate_deflated_alpha_directly",
    ):
        assert hasattr(module, name), f"example module missing callable: {name}"
        assert callable(getattr(module, name)), f"{name} should be callable"


def test_real_data_pipeline_example_runs():
    """real_data_pipeline_example must run end-to-end and exit 0."""
    result = subprocess.run(
        [sys.executable, str(_REAL_DATA_PIPELINE_PATH)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"real_data_pipeline_example exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "PIPELINE COMPLETE - SUMMARY" in result.stdout



# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------

TEST_REGISTRY = [
    ("test_deflated_alpha_example_imports", test_deflated_alpha_example_imports),
    ("test_deflated_alpha_example_runs", test_deflated_alpha_example_runs),
    ("test_multiple_benchmarks_example_imports", test_multiple_benchmarks_example_imports),
    ("test_multiple_benchmarks_example_runs", test_multiple_benchmarks_example_runs),
    ("test_full_pipeline_example_imports", test_full_pipeline_example_imports),
    ("test_full_pipeline_example_runs", test_full_pipeline_example_runs),
    ("test_full_pipeline_example_surfaces_single_benchmark_significance", test_full_pipeline_example_surfaces_single_benchmark_significance),
    ("test_pairs_trading_example_imports", test_pairs_trading_example_imports),
    ("test_pairs_trading_example_runs", test_pairs_trading_example_runs),
    ("test_pairs_trading_example_emits_realistic_prices", test_pairs_trading_example_emits_realistic_prices),
    ("test_pairs_trading_example_writes_report_to_directory", test_pairs_trading_example_writes_report_to_directory),
    ("test_trading_costs_robustness_example_imports", test_trading_costs_robustness_example_imports),
    ("test_trading_costs_robustness_example_runs", test_trading_costs_robustness_example_runs),
    ("test_trading_costs_robustness_example_shows_cost_sensitivity", test_trading_costs_robustness_example_shows_cost_sensitivity),
    ("test_simple_momentum_hypothesis_imports", test_simple_momentum_hypothesis_imports),
    ("test_simple_momentum_hypothesis_runs", test_simple_momentum_hypothesis_runs),
    ("test_simple_momentum_hypothesis_emits_hypothesis_and_costs", test_simple_momentum_hypothesis_emits_hypothesis_and_costs),
    ("test_simple_momentum_hypothesis_uses_point_in_time_split", test_simple_momentum_hypothesis_uses_point_in_time_split),
    ("test_mean_reversion_hypothesis_imports", test_mean_reversion_hypothesis_imports),
    ("test_mean_reversion_hypothesis_runs", test_mean_reversion_hypothesis_runs),
    ("test_mean_reversion_hypothesis_emits_hypothesis_and_costs", test_mean_reversion_hypothesis_emits_hypothesis_and_costs),
    ("test_mean_reversion_hypothesis_uses_point_in_time_split", test_mean_reversion_hypothesis_uses_point_in_time_split),
    ("test_rsi_mean_reversion_hypothesis_imports", test_rsi_mean_reversion_hypothesis_imports),
    ("test_rsi_mean_reversion_hypothesis_runs", test_rsi_mean_reversion_hypothesis_runs),
    ("test_rsi_mean_reversion_hypothesis_emits_hypothesis_and_costs", test_rsi_mean_reversion_hypothesis_emits_hypothesis_and_costs),
    ("test_rsi_mean_reversion_hypothesis_uses_point_in_time_split", test_rsi_mean_reversion_hypothesis_uses_point_in_time_split),
    ("test_zscore_mean_reversion_hypothesis_imports", test_zscore_mean_reversion_hypothesis_imports),
    ("test_zscore_mean_reversion_hypothesis_runs", test_zscore_mean_reversion_hypothesis_runs),
    ("test_zscore_mean_reversion_hypothesis_emits_hypothesis_and_costs", test_zscore_mean_reversion_hypothesis_emits_hypothesis_and_costs),
    ("test_zscore_mean_reversion_hypothesis_uses_point_in_time_split", test_zscore_mean_reversion_hypothesis_uses_point_in_time_split),
    ("test_real_data_pipeline_example_imports", test_real_data_pipeline_example_imports),
    ("test_real_data_pipeline_example_runs", test_real_data_pipeline_example_runs),
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
