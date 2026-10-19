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