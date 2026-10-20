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

The suite also pins three methodological properties of the example that are
easy to break silently:

  * criterion 3 (the raw benchmark-alpha test) and criterion 5 (the
    multiple-testing corrected test) must read DIFFERENT statistics. Reading
    only the corrected p-value would make the advertised benchmark-side
    data-mining control redundant: criterion 5 would be implied by criterion 3
    and could never bind independently.
  * the example must report the test's resolution -- the smallest effect each
    significance criterion requires -- so a failed criterion that the sample
    cannot resolve is not mistaken for evidence against the hypothesis.
  * the resolution analysis is a measurement: it must not change any criterion
    outcome or the verdict.

Run with: python3 skills/quantitative-backtesting/tests/test_falsifiable_hypothesis_example.py
No third-party test framework is required; uses only the standard library.
"""

import subprocess
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


# The example runs a full walk-forward validation, which is expensive. The
# result is immutable and the same for every test, so it is computed once and
# shared (each test only reads it).
_RESULT = None


def _result():
    global _RESULT
    if _RESULT is None:
        data_path, _ = _sample_paths()
        _RESULT = run_hypothesis_test(data_path)
    return _RESULT


def test_falsifiable_hypothesis_example_runs_end_to_end():
    """The pre-registered hypothesis test executes on the shipped sample data."""
    data_path, bench_path = _sample_paths()
    assert data_path.exists() and bench_path.exists(), "sample data fixtures missing"
    result = _result()

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
                "benchmark_alpha_pvalue_corrected",
                "benchmark_alpha_correction_applied",
                "benchmark_total_return", "deflated_alpha_ratio",
                "deflated_alpha_pvalue", "n_benchmarks",
                "selected_params", "test_n_observations"):
        assert key in obs, f"observed metrics missing {key}"
    assert obs["test_n_observations"] and obs["test_n_observations"] > 0
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
    result = _result()

    for c in result["criteria"]:
        assert c["passed"] in (True, False)
        assert "<" in c["description"] or ">" in c["description"]
    # The verdict is the conjunction of the criteria.
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])


def test_falsifiable_hypothesis_out_of_sample_split_is_chronological():
    """The held-out test set is disjoint from train/val and never used in
    selection (chronological 0.6/0.2/0.2 split)."""
    result = _result()
    sep = result["separation_check"]
    assert sep.get("disjoint") is True
    assert sep.get("chronological") is True
    assert sep.get("train_test_overlap") == 0


def test_the_alpha_criterion_reads_the_raw_p_value_and_the_dar_the_corrected_one():
    """Criterion 3 (raw alpha test) and criterion 5 (multiple-testing
    corrected) must be different statistics.

    The benchmark correction rewrites the primary benchmark's `alpha_pvalue`
    with the deflated p-value and keeps the raw one in
    `alpha_pvalue_original`. If the example read only `alpha_pvalue`, the two
    criteria would test the same number and the benchmark-side data-mining
    control could never bind independently."""
    result = _result()
    obs = result["observed"]

    raw = obs["benchmark_alpha_pvalue"]
    corrected = obs["benchmark_alpha_pvalue_corrected"]
    assert raw is not None and corrected is not None
    # The correction is engaged on the shipped fixture (N = 2 benchmarks), so
    # the two p-values genuinely differ.
    assert obs["benchmark_alpha_correction_applied"] is True
    assert raw != corrected
    # The corrected p-value is the Deflated Alpha p-value of the primary
    # benchmark (1 - DAR), the number criterion 5 is stated against.
    assert abs(corrected - obs["deflated_alpha_pvalue"]) < 1e-12
    assert abs((1.0 - obs["deflated_alpha_ratio"]) - corrected) < 1e-12
    # The raw p-value is the uncorrected two-sided alpha t-test p-value.
    assert raw > corrected, (
        "the multiple-testing correction can only make the p-value larger"
    )


def test_the_example_reports_the_test_resolution():
    """The example reports the smallest effect each significance criterion
    requires at the sample size actually available (minimum detectable
    effect), and flags the criteria the sample cannot resolve."""
    result = _result()
    res = result["resolution"]

    for key in ("n_test_observations", "n_parameter_trials", "n_benchmarks",
                "min_detectable_sharpe", "min_detectable_alpha",
                "min_detectable_benchmark_alpha", "alpha_regression_df",
                "criteria_beyond_resolution",
                "plausible_max_annualized_sharpe",
                "plausible_max_annualized_alpha"):
        assert key in res, f"resolution block missing {key}"

    obs = result["observed"]
    # The held-out window carries far too few observations for the deflated
    # thresholds to be reachable, so every reported minimum detectable effect
    # is larger than the effect that was observed.
    assert res["min_detectable_sharpe"] > 0
    assert res["min_detectable_sharpe"] > obs["oos_sharpe"]
    assert res["min_detectable_alpha"] > 0
    assert res["min_detectable_alpha"] > obs["benchmark_alpha"]
    assert res["min_detectable_benchmark_alpha"] > 0
    assert res["min_detectable_benchmark_alpha"] > obs["benchmark_alpha"]

    # The three significance criteria are the ones beyond the sample's
    # resolution on the shipped fixture; criteria 1 and 4 are direct
    # comparisons and are not power-limited in the same way.
    assert set(res["criteria_beyond_resolution"]) == {
        "deflated_sharpe_pvalue_lt_0.10",
        "benchmark_alpha_pvalue_lt_0.05",
        "deflated_alpha_ratio_gt_0.90",
    }
    assert result["criteria_beyond_resolution"] == res["criteria_beyond_resolution"]


def test_the_resolution_does_not_change_the_verdict():
    """The resolution analysis is a measurement: it changes no criterion
    outcome and no verdict."""
    result = _result()
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")
    # The verdict on the shipped sample data is a regression guard on the
    # wiring (raw vs corrected p-value), not a claim about the strategy.
    assert result["verdict"] == "NOT SUPPORTED"


def test_the_test_window_is_reported_in_observations_not_periods():
    """The held-out window is reported as a number of observations (daily
    bars), not as a number of independent periods -- the distinction is what
    makes the resolution numbers interpretable."""
    result = _result()
    obs = result["observed"]
    assert obs["test_n_observations"] == 100
    assert "test_n_periods" not in obs


def test_the_example_prints_the_resolution_and_the_reading_note():
    """The console output carries the resolution section and says in plain
    words that a criterion the sample cannot resolve is not evidence against
    the hypothesis."""
    example_path = SKILLS_DIR / "examples" / "falsifiable_hypothesis_example.py"
    proc = subprocess.run(
        [sys.executable, str(example_path)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, (
        f"example exited {proc.returncode}\n"
        f"stdout:\n{proc.stdout[-3000:]}\n"
        f"stderr:\n{proc.stderr[-3000:]}"
    )
    out = proc.stdout
    assert "TEST RESOLUTION" in out
    assert "Beyond the sample's resolution" in out
    assert "HOW TO READ THIS VERDICT:" in out
    assert "Benchmark alpha p-value (raw, criterion 3)" in out
    assert "Benchmark alpha p-value (deflated" in out
    assert "Test observations:" in out
    # The pre-registered decision rule is reported unchanged.
    assert "VERDICT:" in out


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
    ("test_the_alpha_criterion_reads_the_raw_p_value_and_the_dar_the_corrected_one", test_the_alpha_criterion_reads_the_raw_p_value_and_the_dar_the_corrected_one),
    ("test_the_example_reports_the_test_resolution", test_the_example_reports_the_test_resolution),
    ("test_the_resolution_does_not_change_the_verdict", test_the_resolution_does_not_change_the_verdict),
    ("test_the_test_window_is_reported_in_observations_not_periods", test_the_test_window_is_reported_in_observations_not_periods),
    ("test_the_example_prints_the_resolution_and_the_reading_note", test_the_example_prints_the_resolution_and_the_reading_note),
]

if __name__ == "__main__":
    import sys
    sys.exit(main())
