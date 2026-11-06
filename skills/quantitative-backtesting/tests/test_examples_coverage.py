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
import tempfile
import traceback
from pathlib import Path

import pandas as pd

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
_DUAL_MOMENTUM_PATH = SKILLS_DIR / "examples" / "dual_momentum_hypothesis.py"

_BOLLINGER_PATH = SKILLS_DIR / "examples" / "bollinger_bands_hypothesis.py"
_DONCHIAN_PATH = SKILLS_DIR / "examples" / "donchian_breakout_hypothesis.py"
_EMA_CROSS_PATH = SKILLS_DIR / "examples" / "ema_cross_hypothesis.py"
_MACD_PATH = SKILLS_DIR / "examples" / "macd_hypothesis.py"
_WF_COMPARE_TRIPLE_PATH = SKILLS_DIR / "examples" / "walk_forward_compare_triple.py"
_COMPARE_DUAL_CS_PATH = SKILLS_DIR / "examples" / "compare_dual_vs_cross_sectional_triple.py"

_REAL_MARKET_DATA = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def _build_triple_csv(dest: Path) -> Path:
    """Combine the committed AAPL/MSFT/GOOGL fixtures into one panel CSV."""
    frames = []
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        frame = pd.read_csv(_REAL_MARKET_DATA / name)
        frame["symbol"] = Path(name).stem
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    out = dest / "aapl_msft_googl_triple.csv"
    combined.to_csv(out, index=False)
    return out
_DUAL_MOMENTUM_PATH = SKILLS_DIR / "examples" / "dual_momentum_hypothesis.py"


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


def test_pairs_trading_example_emits_walk_forward_out_of_sample():
    """pairs_trading_example reports walk-forward/out-of-sample validation and cost sensitivity."""
    result = subprocess.run(
        [sys.executable, str(_PAIRS_PATH)],
        capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, (
        f"pairs_trading_example exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    out = result.stdout
    assert "Walk-forward" in out and "out-of-sample" in out
    assert "Train/Val/Test" in out
    assert "chronological" in out
    assert "Cost sensitivity" in out


def test_pairs_trading_example_writes_report_to_directory():
    """generate_report writes report.txt into the output directory."""
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
    # Numerical cost-sensitivity guard: higher per-trade costs must reduce net
    # Sharpe and total return in the strategy cost-sweep impact block.  The
    # data is synthetic (seed=42), so this relationship is deterministic and the
    # test is a regression guard against a silent break in the cost model.
    m = re.search(r"Sharpe:\s*([-0-9.]+)\s*→\s*([-0-9.]+)", result.stdout)
    assert m, "strategy cost-impact Sharpe line missing"
    sharpe_start, sharpe_end = float(m.group(1)), float(m.group(2))
    assert sharpe_end < sharpe_start, (
        f"higher cost did not reduce Sharpe: {sharpe_start} → {sharpe_end}"
    )
    m = re.search(r"Return:\s*([-0-9.]+)%\s*→\s*([-0-9.]+)%", result.stdout)
    assert m, "strategy cost-impact Return line missing"
    ret_start, ret_end = float(m.group(1)), float(m.group(2))
    assert ret_end < ret_start, (
        f"higher cost did not reduce return: {ret_start}% → {ret_end}%"
    )


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


def test_simple_momentum_hypothesis_emits_falsification_verdict():
    """simple_momentum_hypothesis emits falsification criteria and verdict outputs."""
    result = subprocess.run(
        [sys.executable, str(_SIMPLE_MOMENTUM_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"simple_momentum_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "FALSIFICATION CRITERIA" in result.stdout
    assert re.search(r"\[(PASS|FAIL)\].*oos_sharpe_gt_zero", result.stdout)
    assert re.search(r"\[(PASS|FAIL)\].*oos_total_return_gt_benchmark", result.stdout)
    assert re.search(r"VERDICT:\s*(SUPPORTED|NOT SUPPORTED)", result.stdout)
    # Criteria must include numeric values (Sharpe/returns) in numerically sane form
    assert "Sharpe" in result.stdout
    assert "Total Return" in result.stdout


# ---------------------------------------------------------------------------
# dual_momentum_hypothesis.py
# ---------------------------------------------------------------------------


def test_dual_momentum_hypothesis_imports():
    """dual_momentum_hypothesis must import cleanly and expose its entry points."""
    module = _import_module("dual_momentum_hypothesis", _DUAL_MOMENTUM_PATH)
    assert hasattr(module, "run_hypothesis_test")
    assert callable(module.run_hypothesis_test)
    assert hasattr(module, "run_benchmark_aware_hypothesis_test")
    assert callable(module.run_benchmark_aware_hypothesis_test)
    assert hasattr(module, "main")
    assert callable(module.main)
    assert hasattr(module, "BENCHMARK_CRITERIA")
    assert hasattr(module, "N_TRIALS")
    assert module.N_TRIALS == len(module.PARAM_SENSITIVITY_GRID)


def test_dual_momentum_hypothesis_runs():
    """dual_momentum_hypothesis must run end-to-end and exit 0."""
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (_REAL_MARKET_DATA / name).exists()
    with tempfile.TemporaryDirectory() as td:
        data_path = _build_triple_csv(Path(td))
        result = subprocess.run(
            [sys.executable, str(_DUAL_MOMENTUM_PATH), "--data", str(data_path), "--no-benchmark"],
            capture_output=True, text=True, timeout=600,
        )
    assert result.returncode == 0, (
        f"dual_momentum_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "FALSIFIABLE HYPOTHESIS TEST" in result.stdout
    assert "VERDICT:" in result.stdout


def test_dual_momentum_hypothesis_emits_baseline_verdict():
    """dual_momentum_hypothesis baseline path reports the two baseline criteria."""
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (_REAL_MARKET_DATA / name).exists()
    with tempfile.TemporaryDirectory() as td:
        data_path = _build_triple_csv(Path(td))
        result = subprocess.run(
            [sys.executable, str(_DUAL_MOMENTUM_PATH), "--data", str(data_path), "--no-benchmark"],
            capture_output=True, text=True, timeout=600,
        )
    assert result.returncode == 0, (
        f"dual_momentum_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "FALSIFICATION CRITERIA" in result.stdout
    assert re.search(r"\[(PASS|FAIL)\].*oos_sharpe_gt_zero", result.stdout)
    assert re.search(r"\[(PASS|FAIL)\].*oos_total_return_positive", result.stdout)
    assert re.search(r"VERDICT:\s*(SUPPORTED|NOT SUPPORTED)", result.stdout)


def test_dual_momentum_hypothesis_emits_benchmark_verdict():
    """dual_momentum_hypothesis benchmark-aware path reports the four criteria."""
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (_REAL_MARKET_DATA / name).exists()
    with tempfile.TemporaryDirectory() as td:
        data_path = _build_triple_csv(Path(td))
        result = subprocess.run(
            [sys.executable, str(_DUAL_MOMENTUM_PATH), "--data", str(data_path)],
            capture_output=True, text=True, timeout=600,
        )
    assert result.returncode == 0, (
        f"dual_momentum_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "FALSIFICATION CRITERIA" in result.stdout
    assert re.search(r"\[(PASS|FAIL)\].*oos_sharpe_gt_zero", result.stdout)
    assert re.search(r"\[(PASS|FAIL)\].*oos_total_return_gt_benchmark", result.stdout)
    assert re.search(r"\[(PASS|FAIL)\].*deflated_sharpe_pvalue_lt_0.10", result.stdout)
    assert re.search(r"\[(PASS|FAIL)\].*benchmark_alpha_pvalue_lt_0.05", result.stdout)
    assert re.search(r"VERDICT:\s*(SUPPORTED|NOT SUPPORTED)", result.stdout)
    assert "Deflated Sharpe" in result.stdout or "Deflated" in result.stdout


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


def test_mean_reversion_hypothesis_emits_falsification_verdict():
    """mean_reversion_hypothesis emits falsification criteria and verdict outputs."""
    result = subprocess.run(
        [sys.executable, str(_MEAN_REVERSION_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"mean_reversion_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "FALSIFICATION CRITERIA" in result.stdout
    assert re.search(r"\[(PASS|FAIL)\].*oos_sharpe_gt_zero", result.stdout)
    assert re.search(r"\[(PASS|FAIL)\].*oos_total_return", result.stdout)
    assert re.search(r"VERDICT:\s*(SUPPORTED|NOT SUPPORTED)", result.stdout)
    assert "Sharpe" in result.stdout
    assert "Total Return" in result.stdout


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


def test_rsi_mean_reversion_hypothesis_emits_falsification_verdict():
    """rsi_mean_reversion_hypothesis emits falsification criteria and verdict outputs."""
    result = subprocess.run(
        [sys.executable, str(_RSI_MR_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"rsi_mean_reversion_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "FALSIFICATION CRITERIA" in result.stdout
    assert re.search(r"\[(PASS|FAIL)\].*oos_sharpe_gt_zero", result.stdout)
    assert re.search(r"\[(PASS|FAIL)\].*oos_total_return_positive", result.stdout)
    assert re.search(r"VERDICT:\s*(SUPPORTED|NOT SUPPORTED)", result.stdout)
    assert "Sharpe" in result.stdout
    assert "Total Return" in result.stdout


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


def test_zscore_mean_reversion_hypothesis_emits_falsification_verdict():
    """zscore_mean_reversion_hypothesis emits falsification criteria and verdict outputs."""
    result = subprocess.run(
        [sys.executable, str(_ZSCORE_MR_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"zscore_mean_reversion_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "FALSIFICATION CRITERIA" in result.stdout
    assert re.search(r"\[(PASS|FAIL)\].*oos_sharpe_gt_zero", result.stdout)
    assert re.search(r"\[(PASS|FAIL)\].*oos_total_return_positive", result.stdout)
    assert re.search(r"VERDICT:\s*(SUPPORTED|NOT SUPPORTED)", result.stdout)
    assert "Sharpe" in result.stdout
    assert "Total Return" in result.stdout
    # Must surface book panel pricing as documented
    assert "book" in result.stdout.lower()
    assert "Panel pricing" in result.stdout


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


def test_real_data_pipeline_example_emits_deflated_alpha_outputs():
    """real_data_pipeline_example must surface its deflated alpha / MCC outputs.

    Regression guard for the example's multiple-testing correction surface:
    stages 4-7 each print a Deflated Alpha Ratio, DAR p-value, expected max
    alpha and benchmark count, and the summary repeats them. Assert every
    DAR and p-value stays within [0, 1] so a silent machinery failure (e.g.
    a dropped correction or a NaN) cannot masquerade as a complete run.
    """
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
    # Stages 4 (API CPCV), 5 (CLI CPCV), 6 (CLI Monte Carlo) and 7 (direct)
    # each print a Deflated Alpha Ratio line.
    dar_lines = re.findall(r"Deflated Alpha Ratio:\s*([0-9.]+)", result.stdout)
    assert len(dar_lines) >= 4, (
        f"expected at least 4 Deflated Alpha Ratio lines, got {len(dar_lines)}"
    )
    for value in dar_lines:
        assert 0.0 <= float(value) <= 1.0, f"DAR out of range: {value}"
    pvalue_lines = re.findall(r"DAR p-value:\s*([0-9.]+)", result.stdout)
    assert len(pvalue_lines) >= 4, (
        f"expected at least 4 DAR p-value lines, got {len(pvalue_lines)}"
    )
    for value in pvalue_lines:
        assert 0.0 <= float(value) <= 1.0, f"p-value out of range: {value}"
    assert result.stdout.count("N benchmarks: 2") >= 4
    assert "Expected max alpha" in result.stdout
    # The summary block repeats the headline figures.
    assert "CPCV Deflated Alpha Ratio:" in result.stdout
    assert "Direct DAR:" in result.stdout


# ---------------------------------------------------------------------------
# bollinger_bands_hypothesis.py
# ---------------------------------------------------------------------------


def test_bollinger_bands_hypothesis_imports():
    """bollinger_bands_hypothesis must import cleanly and expose its entry points."""
    module = _import_module("bollinger_bands_hypothesis", _BOLLINGER_PATH)
    assert hasattr(module, "run_hypothesis_test")
    assert callable(module.run_hypothesis_test)
    assert hasattr(module, "main")
    assert callable(module.main)
    assert hasattr(module, "HYPOTHESIS")
    assert hasattr(module, "CRITERIA")


def test_bollinger_bands_hypothesis_runs():
    """bollinger_bands_hypothesis must run end-to-end and exit 0."""
    data_path = _REAL_MARKET_DATA / "AAPL.csv"
    assert data_path.exists()
    result = subprocess.run(
        [sys.executable, str(_BOLLINGER_PATH), "--data", str(data_path)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"bollinger_bands_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "FALSIFIABLE HYPOTHESIS TEST" in result.stdout
    assert "VERDICT:" in result.stdout


# ---------------------------------------------------------------------------
# donchian_breakout_hypothesis.py
# ---------------------------------------------------------------------------


def test_donchian_breakout_hypothesis_imports():
    """donchian_breakout_hypothesis must import cleanly and expose its entry points."""
    module = _import_module("donchian_breakout_hypothesis", _DONCHIAN_PATH)
    assert hasattr(module, "run_hypothesis_test")
    assert callable(module.run_hypothesis_test)
    assert hasattr(module, "main")
    assert callable(module.main)
    assert hasattr(module, "HYPOTHESIS")
    assert hasattr(module, "CRITERIA")


def test_donchian_breakout_hypothesis_runs():
    """donchian_breakout_hypothesis must run end-to-end and exit 0."""
    data_path = _REAL_MARKET_DATA / "AAPL.csv"
    assert data_path.exists()
    result = subprocess.run(
        [sys.executable, str(_DONCHIAN_PATH), "--data", str(data_path)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"donchian_breakout_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "FALSIFIABLE HYPOTHESIS TEST" in result.stdout
    assert "VERDICT:" in result.stdout


# ---------------------------------------------------------------------------
# ema_cross_hypothesis.py
# ---------------------------------------------------------------------------


def test_ema_cross_hypothesis_imports():
    """ema_cross_hypothesis must import cleanly and expose its entry points."""
    module = _import_module("ema_cross_hypothesis", _EMA_CROSS_PATH)
    assert hasattr(module, "run_hypothesis_test")
    assert callable(module.run_hypothesis_test)
    assert hasattr(module, "main")
    assert callable(module.main)
    assert hasattr(module, "HYPOTHESIS")
    assert hasattr(module, "CRITERIA")


def test_ema_cross_hypothesis_runs():
    """ema_cross_hypothesis must run end-to-end and exit 0."""
    data_path = _REAL_MARKET_DATA / "AAPL.csv"
    assert data_path.exists()
    result = subprocess.run(
        [sys.executable, str(_EMA_CROSS_PATH), "--data", str(data_path)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"ema_cross_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "FALSIFIABLE HYPOTHESIS TEST" in result.stdout
    assert "VERDICT:" in result.stdout


# ---------------------------------------------------------------------------
# macd_hypothesis.py
# ---------------------------------------------------------------------------


def test_macd_hypothesis_imports():
    """macd_hypothesis must import cleanly and expose its entry points."""
    module = _import_module("macd_hypothesis", _MACD_PATH)
    assert hasattr(module, "run_hypothesis_test")
    assert callable(module.run_hypothesis_test)
    assert hasattr(module, "main")
    assert callable(module.main)
    assert hasattr(module, "HYPOTHESIS")
    assert hasattr(module, "CRITERIA")


def test_macd_hypothesis_runs():
    """macd_hypothesis must run end-to-end and exit 0."""
    data_path = _REAL_MARKET_DATA / "AAPL.csv"
    assert data_path.exists()
    result = subprocess.run(
        [sys.executable, str(_MACD_PATH), "--data", str(data_path)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"macd_hypothesis exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "FALSIFIABLE HYPOTHESIS TEST" in result.stdout
    assert "VERDICT:" in result.stdout


# ---------------------------------------------------------------------------
# walk_forward_compare_triple.py
# ---------------------------------------------------------------------------


def test_walk_forward_compare_triple_imports():
    """walk_forward_compare_triple must import cleanly and expose main."""
    module = _import_module("walk_forward_compare_triple", _WF_COMPARE_TRIPLE_PATH)
    assert hasattr(module, "main")
    assert callable(module.main)


def test_walk_forward_compare_triple_runs():
    """walk_forward_compare_triple must run end-to-end and exit 0."""
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (_REAL_MARKET_DATA / name).exists()
    result = subprocess.run(
        [sys.executable, str(_WF_COMPARE_TRIPLE_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"walk_forward_compare_triple exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "WALK-FORWARD COMPARISON" in result.stdout
    assert "Honest verdicts" in result.stdout
    for strategy in ("dual_momentum", "cross_sectional_momentum", "multi_pair_zscore_mean_reversion"):
        assert strategy in result.stdout, f"strategy {strategy} missing from comparison output"


# ---------------------------------------------------------------------------
# compare_dual_vs_cross_sectional_triple.py
# ---------------------------------------------------------------------------


def test_compare_dual_vs_cross_sectional_triple_imports():
    """compare_dual_vs_cross_sectional_triple must import cleanly and expose main."""
    module = _import_module("compare_dual_vs_cross_sectional_triple", _COMPARE_DUAL_CS_PATH)
    assert hasattr(module, "main")
    assert callable(module.main)
    assert hasattr(module, "build_triple")
    assert callable(module.build_triple)


def test_compare_dual_vs_cross_sectional_triple_runs():
    """compare_dual_vs_cross_sectional_triple must run end-to-end and exit 0."""
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (_REAL_MARKET_DATA / name).exists()
    result = subprocess.run(
        [sys.executable, str(_COMPARE_DUAL_CS_PATH)],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, (
        f"compare_dual_vs_cross_sectional_triple exited {result.returncode}\n"
        f"stdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
    )
    assert "Comparison (OOS test" in result.stdout
    for strategy in ("dual_momentum", "cross_sectional_momentum"):
        assert strategy in result.stdout, f"strategy {strategy} missing from comparison output"


# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------

def test_scripts_results_untouched_after_examples():
    import subprocess
    repo_root = SKILLS_DIR.parent.parent
    result = subprocess.run(
        ["git", "status", "--porcelain", "skills/quantitative-backtesting/scripts/results/"],
        cwd=str(repo_root), capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "", (
        "tracked scripts/results/ artifacts were mutated by the test suite:\n"
        + result.stdout
    )


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
    ("test_pairs_trading_example_emits_walk_forward_out_of_sample", test_pairs_trading_example_emits_walk_forward_out_of_sample),
    ("test_pairs_trading_example_writes_report_to_directory", test_pairs_trading_example_writes_report_to_directory),
    ("test_trading_costs_robustness_example_imports", test_trading_costs_robustness_example_imports),
    ("test_trading_costs_robustness_example_runs", test_trading_costs_robustness_example_runs),
    ("test_trading_costs_robustness_example_shows_cost_sensitivity", test_trading_costs_robustness_example_shows_cost_sensitivity),
    ("test_simple_momentum_hypothesis_imports", test_simple_momentum_hypothesis_imports),
    ("test_simple_momentum_hypothesis_runs", test_simple_momentum_hypothesis_runs),
    ("test_simple_momentum_hypothesis_emits_hypothesis_and_costs", test_simple_momentum_hypothesis_emits_hypothesis_and_costs),
    ("test_simple_momentum_hypothesis_uses_point_in_time_split", test_simple_momentum_hypothesis_uses_point_in_time_split),
    ("test_simple_momentum_hypothesis_emits_falsification_verdict", test_simple_momentum_hypothesis_emits_falsification_verdict),
    ("test_mean_reversion_hypothesis_imports", test_mean_reversion_hypothesis_imports),
    ("test_mean_reversion_hypothesis_runs", test_mean_reversion_hypothesis_runs),
    ("test_mean_reversion_hypothesis_emits_hypothesis_and_costs", test_mean_reversion_hypothesis_emits_hypothesis_and_costs),
    ("test_mean_reversion_hypothesis_uses_point_in_time_split", test_mean_reversion_hypothesis_uses_point_in_time_split),
    ("test_mean_reversion_hypothesis_emits_falsification_verdict", test_mean_reversion_hypothesis_emits_falsification_verdict),
    ("test_rsi_mean_reversion_hypothesis_imports", test_rsi_mean_reversion_hypothesis_imports),
    ("test_rsi_mean_reversion_hypothesis_runs", test_rsi_mean_reversion_hypothesis_runs),
    ("test_rsi_mean_reversion_hypothesis_emits_hypothesis_and_costs", test_rsi_mean_reversion_hypothesis_emits_hypothesis_and_costs),
    ("test_rsi_mean_reversion_hypothesis_uses_point_in_time_split", test_rsi_mean_reversion_hypothesis_uses_point_in_time_split),
    ("test_rsi_mean_reversion_hypothesis_emits_falsification_verdict", test_rsi_mean_reversion_hypothesis_emits_falsification_verdict),
    ("test_zscore_mean_reversion_hypothesis_imports", test_zscore_mean_reversion_hypothesis_imports),
    ("test_zscore_mean_reversion_hypothesis_runs", test_zscore_mean_reversion_hypothesis_runs),
    ("test_zscore_mean_reversion_hypothesis_emits_hypothesis_and_costs", test_zscore_mean_reversion_hypothesis_emits_hypothesis_and_costs),
    ("test_zscore_mean_reversion_hypothesis_uses_point_in_time_split", test_zscore_mean_reversion_hypothesis_uses_point_in_time_split),
    ("test_zscore_mean_reversion_hypothesis_emits_falsification_verdict", test_zscore_mean_reversion_hypothesis_emits_falsification_verdict),
    ("test_dual_momentum_hypothesis_imports", test_dual_momentum_hypothesis_imports),
    ("test_dual_momentum_hypothesis_runs", test_dual_momentum_hypothesis_runs),
    ("test_dual_momentum_hypothesis_emits_baseline_verdict", test_dual_momentum_hypothesis_emits_baseline_verdict),
    ("test_dual_momentum_hypothesis_emits_benchmark_verdict", test_dual_momentum_hypothesis_emits_benchmark_verdict),
    ("test_real_data_pipeline_example_imports", test_real_data_pipeline_example_imports),
    ("test_real_data_pipeline_example_runs", test_real_data_pipeline_example_runs),
    ("test_real_data_pipeline_example_emits_deflated_alpha_outputs", test_real_data_pipeline_example_emits_deflated_alpha_outputs),
    ("test_bollinger_bands_hypothesis_imports", test_bollinger_bands_hypothesis_imports),
    ("test_bollinger_bands_hypothesis_runs", test_bollinger_bands_hypothesis_runs),
    ("test_donchian_breakout_hypothesis_imports", test_donchian_breakout_hypothesis_imports),
    ("test_donchian_breakout_hypothesis_runs", test_donchian_breakout_hypothesis_runs),
    ("test_ema_cross_hypothesis_imports", test_ema_cross_hypothesis_imports),
    ("test_ema_cross_hypothesis_runs", test_ema_cross_hypothesis_runs),
    ("test_macd_hypothesis_imports", test_macd_hypothesis_imports),
    ("test_macd_hypothesis_runs", test_macd_hypothesis_runs),
    ("test_walk_forward_compare_triple_imports", test_walk_forward_compare_triple_imports),
    ("test_walk_forward_compare_triple_runs", test_walk_forward_compare_triple_runs),
    ("test_compare_dual_vs_cross_sectional_triple_imports", test_compare_dual_vs_cross_sectional_triple_imports),
    ("test_compare_dual_vs_cross_sectional_triple_runs", test_compare_dual_vs_cross_sectional_triple_runs),
    ("test_scripts_results_untouched_after_examples", test_scripts_results_untouched_after_examples),
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



def test_scripts_results_untouched_after_examples():
    import subprocess
    repo_root = SKILLS_DIR.parent.parent
    result = subprocess.run(
        ["git", "status", "--porcelain", "skills/quantitative-backtesting/scripts/results/"],
        cwd=str(repo_root), capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "", (
        "tracked scripts/results/ artifacts were mutated by the test suite:\n"
        + result.stdout
    )

if __name__ == "__main__":
    sys.exit(main())
