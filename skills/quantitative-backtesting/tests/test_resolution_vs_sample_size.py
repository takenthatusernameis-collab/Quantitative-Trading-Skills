#!/usr/bin/env python3
"""Tests for the resolution-vs-sample-size measurement.

A significance test on a small sample can only fail. The framework reports
the smallest effect each significance criterion could have confirmed at the
sample size actually available (the *test resolution*), and flags the
criteria whose required effect exceeds a stated plausibility bound -- so a
failed criterion that the sample cannot resolve is not mistaken for evidence
against the hypothesis.

On the shipped samples every significance threshold sits beyond the
plausibility bound, which raises the question these tests answer:

    Is that a property of the criteria, or of the sample size?

The measurement (`scripts/measure_resolution_vs_sample_size.py`) sweeps the
sample size at the shipped configuration and reports the framework's own
minimum detectable effect at each rung. The answer, measured: the resolution
IMPROVES with the sample size and crosses below the plausibility bound at a
few thousand daily bars, so criterion 2 *can* confirm a plausible effect --
the shipped sample's verdict is a statement about its 500 bars, not about the
criteria.

These tests pin:

  * the resolution falls as the sample grows, and crosses below the
    framework's plausibility bound (the answer to the open question);
  * the crossing is not an artefact of one random draw;
  * the measurement agrees with the worked example's own shipped path, so it
    measures the shipped configuration and not a private copy of it;
  * the measurement moves no threshold, no bound, no criterion and no
    verdict;
  * every analysis path is measured, and each one reports the framework's
    own resolution block for the sample it prices;
  * the paths cross the plausibility bound at *different* sample sizes,
    because they do not see the same sample.

THE DATA IS THE SYNTHETIC POSITIVE-CONTROL FIXTURE
    The numbers are properties of a formula and of the decision machinery,
    never evidence about a security.

Run with: python3 skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py
No third-party test framework is required; uses only the standard library.
"""

import contextlib
import io
import sys
import tempfile
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from data_loader import load_data  # noqa: E402
from falsifiable_hypothesis_example import run_hypothesis_test  # noqa: E402
from generate_positive_control_data import (  # noqa: E402
    CONTROL_BENCHMARK_SEED,
    CONTROL_STRATEGY_SEED,
    write_control_fixture,
)
from measure_resolution_vs_sample_size import (  # noqa: E402
    COMMISSION,
    CPCV_N_SPLITS,
    CPCV_TEST_SIZE,
    INITIAL_CAPITAL,
    PARAM_GRID,
    SELECTION_CRITERION,
    SLIPPAGE,
    TEST_FRAC,
    TRAIN_FRAC,
    VAL_FRAC,
    WF_STEP_MONTHS,
    WF_TEST_MONTHS,
    WF_TRAIN_MONTHS,
    measure_synthetic,
    summarize,
)
from walk_forward import (  # noqa: E402
    PLAUSIBLE_MAX_ANNUALIZED_ALPHA,
    PLAUSIBLE_MAX_ANNUALIZED_SHARPE,
    _make_strategy_factory,
    cpcv_analysis,
    out_of_sample_validation,
    walk_forward_analysis,
)

# The rungs the tests measure at. They bracket the crossing of the
# plausibility bound: at 2,500 bars criterion 2 is still out of reach on
# every draw measured, at 10,000 bars it is inside the bound on every draw
# measured.
SMALL_SAMPLE_BARS = 2500
MIDDLE_SAMPLE_BARS = 5000
LARGE_SAMPLE_BARS = 10000
SEEDS = (7, 1, 2024)

# The analysis paths the measurement covers.
OUT_OF_SAMPLE = "out_of_sample"
WALK_FORWARD = "walk_forward"
CPCV = "cpcv"

# Each measurement runs a full walk-forward validation, so the results are
# computed once and shared by the tests that read them.
_MEASUREMENTS = {}


def _measured(bars, seed, inject_effect):
    key = (bars, seed, bool(inject_effect))
    if key not in _MEASUREMENTS:
        _MEASUREMENTS[key] = measure_synthetic(bars, seed, inject_effect)
    return _MEASUREMENTS[key]


def _ladder_rows():
    """The ladder the per-path summaries are read from.

    Every draw (three seeds, both series) at the three rungs.
    """
    rows = []
    for bars in (SMALL_SAMPLE_BARS, MIDDLE_SAMPLE_BARS, LARGE_SAMPLE_BARS):
        for seed in SEEDS:
            for inject_effect in (False, True):
                rows.append(_measured(bars, seed, inject_effect))
    return rows


def _control_fixture(bars, seed, inject_effect):
    """The control fixture the measurement builds, rebuilt independently."""
    tmpdir = tempfile.TemporaryDirectory(prefix="resolution_path_parity_")
    paths = write_control_fixture(
        tmpdir.name,
        inject_effect=inject_effect,
        periods=bars,
        strategy_seed=seed,
        benchmark_seed=seed + (CONTROL_BENCHMARK_SEED - CONTROL_STRATEGY_SEED),
    )
    data = load_data(str(paths["strategy"]))
    benchmarks = [
        load_data(str(paths["strategy"])),
        load_data(str(paths["benchmark"])),
    ]
    return tmpdir, data, benchmarks


def _framework_oos_block(bars, seed, inject_effect, train_frac, val_frac, test_frac):
    """Run the framework's own out_of_sample_validation on the same fixture.

    Returns the summary and the test returns, so callers can read the
    framework's own ``summary["test_resolution"]]`` block and compare it with
    what the measurement reports for the identical split.
    """
    tmpdir, data, benchmarks = _control_fixture(bars, seed, inject_effect)
    try:
        strategy_factory = _make_strategy_factory("sma_crossover")
        results = out_of_sample_validation(
            data=data,
            strategy_factory=strategy_factory,
            param_grid=PARAM_GRID,
            train_frac=train_frac,
            val_frac=val_frac,
            test_frac=test_frac,
            validation_method="walk_forward",
            walk_forward_train_months=WF_TRAIN_MONTHS,
            walk_forward_test_months=WF_TEST_MONTHS,
            walk_forward_step_months=WF_STEP_MONTHS,
            initial_capital=INITIAL_CAPITAL,
            commission=COMMISSION,
            slippage=SLIPPAGE,
            benchmark=benchmarks,
            total_return_benchmark=False,
            benchmark_commission=COMMISSION,
            benchmark_slippage=SLIPPAGE,
            benchmark_expense_ratio=0.0,
            benchmark_cost_is_periodic=False,
            apply_deflation=True,
            selection_criterion=SELECTION_CRITERION,
            validate_pit=True,
        )
    finally:
        tmpdir.cleanup()
    return results.get("summary", {}), results.get("test_performance") or {}


def test_the_resolution_improves_with_the_sample_size():
    """The minimum confirmable annualized Sharpe falls as the sample grows.

    Measured on the no-effect control (the null calibration: the trial
    Sharpes there are pure estimation noise, which is what the deflation
    benchmark is meant to measure). At 2,500 bars the Deflated Sharpe test
    cannot confirm anything under the framework's own plausibility bound; at
    10,000 bars it can.

    This is the answer to the question the shipped samples left open: the
    criteria are not unsatisfiable at plausible effect sizes -- the shipped
    sample is simply too small to resolve them.
    """
    small = _measured(SMALL_SAMPLE_BARS, 7, False)
    large = _measured(LARGE_SAMPLE_BARS, 7, False)

    assert small["min_detectable_sharpe"] is not None
    assert large["min_detectable_sharpe"] is not None

    # The resolution improves.
    assert large["min_detectable_sharpe"] < small["min_detectable_sharpe"], (
        "the minimum confirmable Sharpe must fall as the sample grows "
        f"({large['min_detectable_sharpe']} at {LARGE_SAMPLE_BARS} bars vs "
        f"{small['min_detectable_sharpe']} at {SMALL_SAMPLE_BARS} bars)"
    )

    # The small sample cannot resolve criterion 2 at a plausible effect size.
    assert small["min_detectable_sharpe"] > PLAUSIBLE_MAX_ANNUALIZED_SHARPE
    assert small["sharpe_beyond_plausible_bound"] is True

    # The larger sample can: criterion 2 is inside the sample's resolution.
    assert large["min_detectable_sharpe"] <= PLAUSIBLE_MAX_ANNUALIZED_SHARPE
    assert large["sharpe_beyond_plausible_bound"] is False

    # The mechanism: the floor the resolution converges to is the framework's
    # own deflation benchmark (SR*), and it is below the plausibility bound
    # on this construction, so no sample size can leave criterion 2
    # permanently out of reach.
    assert large["expected_max_sharpe"] is not None
    assert large["expected_max_sharpe"] <= PLAUSIBLE_MAX_ANNUALIZED_SHARPE


def test_the_crossing_is_not_a_property_of_one_random_draw():
    """The resolution falls below the plausibility bound on every draw measured.

    A single seed would report a number that reads as a property of the
    framework rather than of one sample. The crossing is checked on the
    no-effect control and on the effect series, on three seeds.
    """
    for inject_effect in (False, True):
        for seed in SEEDS:
            measured = _measured(LARGE_SAMPLE_BARS, seed, inject_effect)
            assert measured["min_detectable_sharpe"] is not None
            assert measured["min_detectable_sharpe"] <= PLAUSIBLE_MAX_ANNUALIZED_SHARPE, (
                "criterion 2 must be within the sample's resolution on a "
                f"{LARGE_SAMPLE_BARS}-bar sample (effect={inject_effect}, "
                f"seed={seed}): the minimum confirmable annualized Sharpe is "
                f"{measured['min_detectable_sharpe']}"
            )
            assert measured["sharpe_beyond_plausible_bound"] is False

    # And at the small rung every measured draw is still out of reach.
    for inject_effect in (False, True):
        for seed in SEEDS:
            measured = _measured(SMALL_SAMPLE_BARS, seed, inject_effect)
            assert measured["min_detectable_sharpe"] > PLAUSIBLE_MAX_ANNUALIZED_SHARPE, (
                "criterion 2 must be beyond the sample's resolution on a "
                f"{SMALL_SAMPLE_BARS}-bar sample (effect={inject_effect}, "
                f"seed={seed}): the minimum confirmable annualized Sharpe is "
                f"{measured['min_detectable_sharpe']}"
            )


def test_the_measurement_agrees_with_the_shipped_example_path():
    """The measurement runs the shipped configuration, not a copy of it.

    The worked example's own `run_hypothesis_test` reports the resolution of
    the statistics it produced. The measurement must report the same numbers
    for the same data, or it is measuring something else.
    """
    bars = SMALL_SAMPLE_BARS
    with tempfile.TemporaryDirectory(prefix="resolution_parity_") as tmpdir:
        paths = write_control_fixture(
            tmpdir, inject_effect=False, periods=bars,
            strategy_seed=7, benchmark_seed=1007,
        )
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_hypothesis_test(paths["strategy"])

    measured = _measured(bars, 7, False)

    assert abs(
        result["resolution"]["min_detectable_sharpe"]
        - measured["min_detectable_sharpe"]
    ) < 1e-12, (
        "the measured resolution must equal the resolution the example's "
        "own path reports"
    )
    assert result["resolution"]["n_test_observations"] == measured["n_test_observations"]
    assert result["resolution"]["n_parameter_trials"] == measured["n_parameter_trials"]
    assert result["resolution"]["n_benchmarks"] == measured["n_benchmarks"]
    if result["resolution"]["min_detectable_alpha"] is not None:
        assert abs(
            result["resolution"]["min_detectable_alpha"]
            - measured["min_detectable_alpha"]
        ) < 1e-12


def test_the_measurement_moves_no_threshold_and_no_verdict():
    """The measurement is beside the verdict: it changes nothing.

    The plausibility bounds are the framework's own and stay where they are;
    the measurement reads them, it does not re-derive or re-tune them. The
    worked example's own verdict on the shipped sample is unchanged.
    """
    assert PLAUSIBLE_MAX_ANNUALIZED_SHARPE == 2.0
    assert PLAUSIBLE_MAX_ANNUALIZED_ALPHA == 0.10

    measured = _measured(LARGE_SAMPLE_BARS, 7, False)
    # The bounds the measurement compares against are the framework's.
    assert measured["plausible_max_annualized_sharpe"] == PLAUSIBLE_MAX_ANNUALIZED_SHARPE
    assert measured["plausible_max_annualized_alpha"] == PLAUSIBLE_MAX_ANNUALIZED_ALPHA

    # The summary reports the crossing as a measurement beside the verdict:
    # it names a size, it never states a verdict.
    rows = [
        _measured(bars, 7, False) for bars in (SMALL_SAMPLE_BARS, LARGE_SAMPLE_BARS)
    ]
    summary = summarize(rows)
    assert summary["first_size_all_within_bound"] == LARGE_SAMPLE_BARS
    assert summary["first_size_any_within_bound"] == LARGE_SAMPLE_BARS
    assert "verdict" not in summary
    for key in summary:
        assert "verdict" not in key


# ---------------------------------------------------------------------------
# Every analysis path is measured, and each one reports the framework's own
# resolution block.
# ---------------------------------------------------------------------------

def test_every_analysis_path_is_measured_and_reports_its_own_resolution():
    """The ladder covers all three analysis paths, not just one.

    The three paths price their significance test on different
    out-of-sample series: the out-of-sample path on the held-out test
    window, the walk-forward path on its pooled out-of-sample windows, the
    CPCV path on its pooled out-of-sample folds. Each one therefore has its
    own resolution, and the measurement reports each of them.
    """
    measured = _measured(SMALL_SAMPLE_BARS, 7, False)
    blocks = measured.get("paths")
    assert isinstance(blocks, dict), "the measurement carries no per-path blocks"

    for path in (OUT_OF_SAMPLE, WALK_FORWARD, CPCV):
        block = blocks.get(path)
        assert isinstance(block, dict), f"the {path} path was not measured"
        assert block["path"] == path
        assert block["min_detectable_sharpe"] is not None, (
            f"the {path} path reported no minimum confirmable Sharpe"
        )
        assert block["expected_max_sharpe"] is not None, (
            f"the {path} path reported no deflation benchmark (SR*)"
        )
        assert block["n_test_observations"] > 0
        # The bounds are the framework's own.
        assert block["plausible_max_annualized_sharpe"] == PLAUSIBLE_MAX_ANNUALIZED_SHARPE
        assert block["plausible_max_annualized_alpha"] == PLAUSIBLE_MAX_ANNUALIZED_ALPHA

    # The paths do not see the same sample, so they do not report the same
    # resolution: a measurement that copied one path's number into the
    # others would pass every other check in this file.
    sharpes = [blocks[p]["min_detectable_sharpe"] for p in blocks]
    assert len(set(sharpes)) == len(sharpes), (
        "the three paths reported the same minimum confirmable Sharpe; they "
        "price their tests on different out-of-sample series and cannot "
        "coincide by construction"
    )


def test_each_path_reports_the_framework_s_own_resolution_block():
    """The measurement reads the framework's block, not a private copy.

    The walk-forward and CPCV paths are measured by calling the framework's
    own `walk_forward_analysis` and `cpcv_analysis` and reading the
    `summary["test_resolution"]` block those functions attach. This test
    runs them again, directly, on the same fixture, and requires the
    measurement to report exactly what they report -- so it measures the
    shipped configuration of each path, not a copy of it.
    """
    bars = SMALL_SAMPLE_BARS
    seed = 7
    tmpdir, data, benchmarks = _control_fixture(bars, seed, False)
    try:
        strategy_factory = _make_strategy_factory("sma_crossover")
        common = dict(
            data=data,
            strategy_factory=strategy_factory,
            param_grid=PARAM_GRID,
            initial_capital=INITIAL_CAPITAL,
            commission=COMMISSION,
            slippage=SLIPPAGE,
            benchmark=benchmarks,
            total_return_benchmark=False,
            benchmark_commission=COMMISSION,
            benchmark_slippage=SLIPPAGE,
            benchmark_expense_ratio=0.0,
            benchmark_cost_is_periodic=False,
            apply_deflation=True,
            validate_pit=True,
        )
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            walk_forward_results = walk_forward_analysis(
                train_months=WF_TRAIN_MONTHS,
                test_months=WF_TEST_MONTHS,
                step_months=WF_STEP_MONTHS,
                **common,
            )
            cpcv_results = cpcv_analysis(
                n_splits=CPCV_N_SPLITS,
                test_size=CPCV_TEST_SIZE,
                **common,
            )
    finally:
        tmpdir.cleanup()

    measured = _measured(bars, seed, False)
    for path, results in (
        (WALK_FORWARD, walk_forward_results),
        (CPCV, cpcv_results),
    ):
        framework = results["summary"]["test_resolution"]
        block = measured["paths"][path]
        assert block["min_detectable_sharpe"] == framework["min_detectable_sharpe"], (
            f"the {path} measurement must report the framework's own minimum "
            "confirmable Sharpe"
        )
        assert block["n_test_observations"] == framework["n_test_observations"]
        assert block["n_parameter_trials"] == framework["n_parameter_trials"]
        assert block["expected_max_sharpe"] == (
            results["summary"]["deflated_sharpe"]["expected_max_sharpe"]
        )


def test_the_paths_cross_the_plausibility_bound_at_different_sample_sizes():
    """Each path answers the question for itself, and they differ.

    The out-of-sample path prices criterion 2 on the held-out test window
    -- a fifth of the sample -- so it needs the largest sample before it can
    confirm a plausible effect. The walk-forward and CPCV paths price it on
    their pooled out-of-sample returns, which span the whole sample, so
    they resolve a plausible effect with fewer bars.

    Measured on the control fixture, over three seeds and both series:

    * out-of-sample: some draws inside the bound at 5,000 bars, every draw
      inside it at 10,000 bars;
    * walk-forward: some draws inside the bound already at 2,500 bars, and
      every draw inside it at 5,000 bars (its floor is higher than the
      CPCV path's: it searched more configurations);
    * CPCV: every draw inside the bound already at 2,500 bars.
    """
    summary = summarize(_ladder_rows())
    by_path = summary["by_path"]

    assert by_path[OUT_OF_SAMPLE]["first_size_any_within_bound"] == MIDDLE_SAMPLE_BARS
    assert by_path[OUT_OF_SAMPLE]["first_size_all_within_bound"] == LARGE_SAMPLE_BARS

    assert by_path[WALK_FORWARD]["first_size_any_within_bound"] == SMALL_SAMPLE_BARS
    assert by_path[WALK_FORWARD]["first_size_all_within_bound"] == MIDDLE_SAMPLE_BARS

    assert by_path[CPCV]["first_size_any_within_bound"] == SMALL_SAMPLE_BARS
    assert by_path[CPCV]["first_size_all_within_bound"] == SMALL_SAMPLE_BARS

    # The primary path's summary is the out-of-sample path's, so a reader
    # of the top-level numbers and a reader of the per-path numbers agree.
    assert summary["first_size_all_within_bound"] == (
        by_path[OUT_OF_SAMPLE]["first_size_all_within_bound"]
    )


def test_the_floor_is_reported_for_every_path_and_every_rung():
    """SR* is a first-class reported number, per path and per rung.

    The floor is the level below which no sample size can let a path
    confirm an effect, so it is reported next to the resolution: as the
    highest floor seen on the ladder, as the floor at each rung, and as the
    floor at the largest rung measured (the one closest to the asymptote).
    """
    summary = summarize(_ladder_rows())
    for path, stats in summary["by_path"].items():
        assert stats["max_expected_max_sharpe"] is not None, (
            f"the {path} path reported no deflation benchmark on the ladder"
        )
        assert stats["floor_at_largest_size"] is not None
        for entry in stats["per_size"]:
            assert entry["max_expected_max_sharpe"] is not None
            assert entry["min_expected_max_sharpe"] is not None
        largest = stats["per_size"][-1]
        assert largest["bars"] == LARGE_SAMPLE_BARS
        assert stats["floor_at_largest_size"] == largest["max_expected_max_sharpe"]
        # The floor is a level below which nothing can be confirmed, so it
        # cannot sit above the resolution that converges onto it.
        assert stats["floor_at_largest_size"] <= stats["max_expected_max_sharpe"]


def test_the_measurement_moves_no_threshold_and_no_verdict_on_any_path():
    """The measurement is beside the verdict on every path.

    Each path's block carries the framework's own bounds, and the flag that
    says the sample cannot resolve criterion 2 is the framework's own: it
    is set exactly when the minimum confirmable Sharpe exceeds the bound.
    The per-path summaries name a size; they never state a verdict.
    """
    measured = _measured(LARGE_SAMPLE_BARS, 7, False)
    for path, block in measured["paths"].items():
        assert block["plausible_max_annualized_sharpe"] == PLAUSIBLE_MAX_ANNUALIZED_SHARPE
        assert block["plausible_max_annualized_alpha"] == PLAUSIBLE_MAX_ANNUALIZED_ALPHA
        value = block["min_detectable_sharpe"]
        expected = value is not None and value > PLAUSIBLE_MAX_ANNUALIZED_SHARPE
        assert block["sharpe_beyond_plausible_bound"] is expected, (
            f"the {path} path's bound flag does not match its own resolution"
        )

    summary = summarize(_ladder_rows())
    for path, stats in summary["by_path"].items():
        assert "verdict" not in stats
        for key in stats:
            assert "verdict" not in key


# ---------------------------------------------------------------------------
# Held-out fraction sweep: the out-of-sample path's resolution as a function
# of test_frac (train_frac = 0.8 - test_frac, val_frac = 0.2).
# ---------------------------------------------------------------------------


def test_test_frac_sweep_keeps_val_frac_and_sums_to_one():
    """The sweep holds val_frac at 0.2 and train_frac = 0.8 - test_frac."""
    for test_frac in (0.1, 0.2, 0.3):
        measured = measure_synthetic(
            SMALL_SAMPLE_BARS, 7, False,
            train_frac=0.8 - test_frac, val_frac=0.2, test_frac=test_frac,
            paths=(OUT_OF_SAMPLE,),
        )
        assert measured["val_frac"] == 0.2
        assert measured["test_frac"] == test_frac
        assert measured["train_frac"] == 0.8 - test_frac
        assert abs(
            measured["train_frac"]
            + measured["val_frac"]
            + measured["test_frac"]
            - 1.0
        ) < 1e-9


def test_test_frac_sweep_each_split_matches_the_framework_own_block():
    """Each swept split's numbers equal the framework's own test_resolution block."""
    for test_frac in (0.1, 0.2, 0.3):
        train_frac = 0.8 - test_frac
        measured = measure_synthetic(
            SMALL_SAMPLE_BARS, 7, False,
            train_frac=train_frac, val_frac=0.2, test_frac=test_frac,
            paths=(OUT_OF_SAMPLE,),
        )
        block = measured["paths"][OUT_OF_SAMPLE]
        framework_summary, _ = _framework_oos_block(
            SMALL_SAMPLE_BARS, 7, False, train_frac, 0.2, test_frac
        )
        framework = framework_summary.get("test_resolution")
        assert isinstance(framework, dict), (
            "the framework did not attach a test_resolution block to its summary"
        )
        assert block["min_detectable_sharpe"] == framework["min_detectable_sharpe"], (
            f"test_frac={test_frac}: the measured minimum confirmable Sharpe "
            "must equal the framework's own block"
        )
        assert block["n_test_observations"] == framework["n_test_observations"]
        assert block["expected_max_sharpe"] == (
            framework_summary["deflated_sharpe"]["expected_max_sharpe"]
        ), (
            f"test_frac={test_frac}: the measured deflation floor (SR*) must "
            "equal the framework's own Deflated Sharpe block"
        )


def test_shipped_default_split_is_unchanged():
    """The shipped 0.6 / 0.2 / 0.2 split remains the default and its numbers match."""
    assert TRAIN_FRAC == 0.6
    assert VAL_FRAC == 0.2
    assert TEST_FRAC == 0.2

    measured = measure_synthetic(SMALL_SAMPLE_BARS, 7, False, paths=(OUT_OF_SAMPLE,))
    assert measured["train_frac"] == 0.6
    assert measured["val_frac"] == 0.2
    assert measured["test_frac"] == 0.2

    block = measured["paths"][OUT_OF_SAMPLE]
    framework_summary, _ = _framework_oos_block(
        SMALL_SAMPLE_BARS, 7, False, 0.6, 0.2, 0.2
    )
    framework = framework_summary["test_resolution"]
    assert block["min_detectable_sharpe"] == framework["min_detectable_sharpe"]
    assert block["n_test_observations"] == framework["n_test_observations"]
    assert block["expected_max_sharpe"] == (
        framework_summary["deflated_sharpe"]["expected_max_sharpe"]
    )


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
    ("test_the_resolution_improves_with_the_sample_size", test_the_resolution_improves_with_the_sample_size),
    ("test_the_crossing_is_not_a_property_of_one_random_draw", test_the_crossing_is_not_a_property_of_one_random_draw),
    ("test_the_measurement_agrees_with_the_shipped_example_path", test_the_measurement_agrees_with_the_shipped_example_path),
    ("test_the_measurement_moves_no_threshold_and_no_verdict", test_the_measurement_moves_no_threshold_and_no_verdict),
    ("test_every_analysis_path_is_measured_and_reports_its_own_resolution", test_every_analysis_path_is_measured_and_reports_its_own_resolution),
    ("test_each_path_reports_the_framework_s_own_resolution_block", test_each_path_reports_the_framework_s_own_resolution_block),
    ("test_the_paths_cross_the_plausibility_bound_at_different_sample_sizes", test_the_paths_cross_the_plausibility_bound_at_different_sample_sizes),
    ("test_the_floor_is_reported_for_every_path_and_every_rung", test_the_floor_is_reported_for_every_path_and_every_rung),
    ("test_the_measurement_moves_no_threshold_and_no_verdict_on_any_path", test_the_measurement_moves_no_threshold_and_no_verdict_on_any_path),
    ("test_test_frac_sweep_keeps_val_frac_and_sums_to_one", test_test_frac_sweep_keeps_val_frac_and_sums_to_one),
    ("test_test_frac_sweep_each_split_matches_the_framework_own_block", test_test_frac_sweep_each_split_matches_the_framework_own_block),
    ("test_shipped_default_split_is_unchanged", test_shipped_default_split_is_unchanged),
]


if __name__ == "__main__":
    sys.exit(main())
