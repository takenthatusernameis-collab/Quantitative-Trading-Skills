#!/usr/bin/env python3
"""
Regression tests for the falsifiable financial hypothesis worked example
(skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py).

Locks the pre-registered hypothesis-testing methodology as a regression guard:
the example must run end-to-end on the shipped sample data, return a well-formed
verdict dict, and report explicit pass/fail for each falsification criterion
against a chronological out-of-sample split. No claim is made about the verdict
itself (SUPPORTED / NOT SUPPORTED are both valid scientific outcomes); the test
guards the structure and executability of the methodology, not its result.

Run with: python3 skills/quantitative-backtesting/tests/test_falsifiable_hypothesis_example.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from falsifiable_hypothesis_example import run_hypothesis_test  # noqa: E402


def _sample_paths():
    data = SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv"
    bench = SKILLS_DIR / "assets" / "example_data" / "sample_benchmark.csv"
    return data, bench


def test_falsifiable_hypothesis_example_runs_end_to_end():
    """The pre-registered hypothesis test executes on the shipped sample data."""
    data_path, bench_path = _sample_paths()
    assert data_path.exists() and bench_path.exists(), "sample data fixtures missing"
    result = run_hypothesis_test(data_path)

    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert isinstance(result["all_pass"], bool)
    assert result["all_pass"] == (result["verdict"] == "SUPPORTED")
    assert result["hypothesis"]  # non-empty pre-registered hypothesis
    assert result["pit_passed"] is True
    assert result["bias_controls_engaged"] is True

    obs = result["observed"]
    for key in ("oos_sharpe", "oos_total_return", "deflated_sharpe_pvalue",
                "benchmark_alpha", "benchmark_alpha_pvalue",
                "benchmark_total_return", "deflated_alpha_ratio",
                "deflated_alpha_pvalue", "n_benchmarks",
                "selected_params", "test_n_periods"):
        assert key in obs, f"observed metrics missing {key}"
    assert obs["test_n_periods"] and obs["test_n_periods"] > 0
    # The strategy is tested against a set of benchmarks (N >= 2), so the
    # Deflated Alpha Ratio data-mining control is engaged.
    assert obs["n_benchmarks"] and obs["n_benchmarks"] >= 2
    assert obs["deflated_alpha_ratio"] is not None
    assert obs["deflated_alpha_pvalue"] is not None

    criteria = result["criteria"]
    assert len(criteria) == 5
    names = {c["name"] for c in criteria}
    assert names == {
        "oos_sharpe_gt_zero",
        "deflated_sharpe_pvalue_lt_0.10",
        "benchmark_alpha_pvalue_lt_0.05",
        "oos_total_return_gt_benchmark",
        "deflated_alpha_ratio_gt_0.90",
    }
    for c in criteria:
        assert isinstance(c["passed"], bool)
        assert c["description"]

    sep = result["separation_check"]
    assert sep.get("disjoint") is True
    assert sep.get("chronological") is True
    for overlap in ("train_val_overlap", "val_test_overlap", "train_test_overlap"):
        assert sep.get(overlap) == 0
    assert sep.get("train_size") and sep.get("val_size") and sep.get("test_size")


def test_falsifiable_hypothesis_criteria_are_explicit_and_evaluated():
    """Every falsification criterion carries a pre-registered description and
    a boolean pass/fail, so the verdict is attributable to explicit criteria
    rather than an opaque outcome."""
    data_path, bench_path = _sample_paths()
    result = run_hypothesis_test(data_path)

    for c in result["criteria"]:
        assert c["passed"] in (True, False)
        assert "<" in c["description"] or ">" in c["description"]
    # The verdict is the conjunction of the criteria.
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])


def test_falsifiable_hypothesis_out_of_sample_split_is_chronological():
    """The held-out test set is disjoint from train/val and never used in
    selection (chronological 0.6/0.2/0.2 split)."""
    data_path, bench_path = _sample_paths()
    result = run_hypothesis_test(data_path)
    sep = result["separation_check"]
    assert sep.get("disjoint") is True
    assert sep.get("chronological") is True
    assert sep.get("train_test_overlap") == 0


def main() -> int:
    tests = TEST_REGISTRY
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return 1 if failures else 0


TEST_REGISTRY = [
    ("test_falsifiable_hypothesis_example_runs_end_to_end", test_falsifiable_hypothesis_example_runs_end_to_end),
    ("test_falsifiable_hypothesis_criteria_are_explicit_and_evaluated", test_falsifiable_hypothesis_criteria_are_explicit_and_evaluated),
    ("test_falsifiable_hypothesis_out_of_sample_split_is_chronological", test_falsifiable_hypothesis_out_of_sample_split_is_chronological),
]

if __name__ == "__main__":
    import sys
    sys.exit(main())
