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
    because they do not see the same sample;
  * the held-out-fraction sweep on the POSITIVE CONTROL (the effect series),
    measured against the framework's own blocks on a directly re-run
    analysis;
  * the control DISCRIMINATES: on the same fixture, at the same split, on
    the same seed, the effect series' observed statistic clears the
    framework's plausibility bounds and the null series' does not, while
    the two series' minimum confirmable effects are nearly the same -- the
    resolution is a property of the sample, the observed statistic is what
    carries the edge;
  * the sweep says which series it measured, and refuses to report a real
    history it did not measure;
  * the Deflated Alpha floor is the dispersion of the BENCHMARK alphas
    scaled by the expected maximum of N draws -- so the floor tracks the
    strategy's own edge over its benchmark set, not the size of the
    parameter search -- and the report says so, with the numbers that
    reproduce the floor.

THE DATA IS THE SYNTHETIC POSITIVE-CONTROL FIXTURE
    The numbers are properties of a formula and of the decision machinery,
    never evidence about a security.

Run with: python3 skills/quantitative-backtesting/tests/test_resolution_vs_sample_size.py
No third-party test framework is required; uses only the standard library.
"""

import contextlib
import io
import json
import math
import statistics
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
    DEFAULT_SIZES,
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
    main as measurement_main,
    measure_synthetic,
    measure_test_frac_sweep,
    print_path_summary,
    summarize,
    _summarize_test_frac_sweep,
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
        assert block["min_detectable_alpha"] == framework["min_detectable_alpha"], (
            f"test_frac={test_frac}: the measured minimum confirmable alpha "
            "must equal the framework's own block"
        )
        assert block["expected_max_alpha"] == (
            framework_summary["deflated_alpha"]["expected_max_alpha"]
        ), (
            f"test_frac={test_frac}: the measured deflation floor (alpha*) must "
            "equal the framework's own Deflated Alpha block"
        )


def test_test_frac_sweep_at_larger_sizes_matches_the_framework_own_block():
    """Each swept split at 5,000 and 10,000 bars matches the framework's own block.

    The held-out-fraction sweep was measured at 2,500 bars where no fraction
    crosses either plausibility bound. At 5,000 and 10,000 bars the trade-off
    between test observations and the deflation floor moves, so the sweep's
    alpha numbers are pinned here against the framework's own
    ``test_resolution`` / ``deflated_alpha`` blocks on a directly re-run
    analysis. No threshold, bound, criterion or verdict moves.
    """
    for bars in (MIDDLE_SAMPLE_BARS, LARGE_SAMPLE_BARS):
        for test_frac in (0.1, 0.2, 0.3):
            train_frac = 0.8 - test_frac
            measured = measure_synthetic(
                bars, 7, False,
                train_frac=train_frac, val_frac=0.2, test_frac=test_frac,
                paths=(OUT_OF_SAMPLE,),
            )
            block = measured["paths"][OUT_OF_SAMPLE]
            framework_summary, _ = _framework_oos_block(
                bars, 7, False, train_frac, 0.2, test_frac
            )
            framework = framework_summary.get("test_resolution")
            assert isinstance(framework, dict), (
                f"{bars} bars test_frac={test_frac}: the framework did not "
                "attach a test_resolution block to its summary"
            )
            assert block["min_detectable_alpha"] == framework["min_detectable_alpha"], (
                f"{bars} bars test_frac={test_frac}: the measured minimum "
                "confirmable alpha must equal the framework's own block"
            )
            assert block["expected_max_alpha"] == (
                framework_summary["deflated_alpha"]["expected_max_alpha"]
            ), (
                f"{bars} bars test_frac={test_frac}: the measured deflation "
                "floor (alpha*) must equal the framework's own Deflated Alpha "
                "block"
            )
            # The plausibility bounds the sweep compares against stay where
            # they are: the measurement reads them, it never re-tunes them.
            assert block["plausible_max_annualized_alpha"] == PLAUSIBLE_MAX_ANNUALIZED_ALPHA


def test_test_frac_sweep_alpha_crossings_match_the_per_fraction_flags():
    """The sweep's reported alpha crossings agree with the per-fraction flags.

    Verifies that no verdict moves: the crossing fraction the summary reports
    is exactly the smallest measured fraction whose per-fraction flag is set,
    or None when no fraction is inside the bound.
    """
    for bars in (MIDDLE_SAMPLE_BARS, LARGE_SAMPLE_BARS):
        rows = measure_test_frac_sweep(
            bars, seeds=(7,), test_fracs=(0.1, 0.2, 0.3), inject_effect=False,
        )
        stats, first_all, first_any, first_all_alpha, first_any_alpha = (
            _summarize_test_frac_sweep(rows)
        )
        flag_all = [e["test_frac"] for e in stats if e["all_within_alpha_bound"]]
        flag_any = [e["test_frac"] for e in stats if e["any_within_alpha_bound"]]
        assert (first_all_alpha is None) == (not flag_all)
        assert (first_any_alpha is None) == (not flag_any)
        if first_all_alpha is not None:
            assert first_all_alpha == min(flag_all)
        if first_any_alpha is not None:
            assert first_any_alpha == min(flag_any)



def test_deflated_alpha_floor_identity_matches_benchmark_dispersion():
    """The Deflated Alpha floor is std(benchmark alphas, ddof=1) * sqrt(2 ln N).

    The floor is the number the report quotes, so its driver has to be the
    framework's own: the cross-sectional dispersion of the *benchmark*
    alphas, scaled by the expected maximum of N draws (N the number of
    benchmarks). The identity is checked here against a live measurement of
    the framework, and the formula is re-derived with the standard library
    (not the implementation's own estimator), so the documented formula and
    the code cannot drift apart.
    """
    bars = SMALL_SAMPLE_BARS
    seed = 7
    measured = _measured(bars, seed, False)
    framework = _framework_wf_block(bars, seed, False)
    block = measured["paths"][WALK_FORWARD]
    deflated_alpha = framework["deflated_alpha"]
    benchmark_alphas = [
        float(b["alpha"]) for b in (framework.get("benchmark_metrics") or [])
        if isinstance(b, dict) and b.get("alpha") is not None
    ]
    n = int(deflated_alpha.get("n_benchmarks", len(benchmark_alphas)))
    predicted = statistics.stdev(benchmark_alphas) * math.sqrt(2.0 * math.log(n))
    assert abs(block["expected_max_alpha"] - predicted) < 1e-9, (
        "the measured deflation floor (alpha*) must equal "
        "std(benchmark alphas, ddof=1) * sqrt(2 ln N)"
    )
    assert abs(block["expected_max_alpha"] - deflated_alpha["expected_max_alpha"]) < 1e-12

    # The report's driver is the framework's own numbers, not a private copy
    # of them: the block carries the benchmark alphas the framework used, and
    # the strategy's own alpha is the primary benchmark's alpha.
    assert block["benchmark_alphas"] == benchmark_alphas
    assert abs(block["benchmark_alpha_std"] - statistics.stdev(benchmark_alphas)) < 1e-12
    assert abs(block["strategy_alpha"] - benchmark_alphas[0]) < 1e-12
    assert block["n_benchmarks"] == n


def _framework_wf_block(bars, seed, inject_effect):
    """Run the framework's own walk_forward_analysis on the same fixture.

    Returns its summary, so callers can read the framework's own
    ``summary["test_resolution"]`` and ``summary["deflated_alpha"]`` blocks
    and compare them with what the measurement reports for the identical
    configuration.
    """
    tmpdir, data, benchmarks = _control_fixture(bars, seed, inject_effect)
    try:
        strategy_factory = _make_strategy_factory("sma_crossover")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            results = walk_forward_analysis(
                data=data,
                strategy_factory=strategy_factory,
                param_grid=PARAM_GRID,
                train_months=WF_TRAIN_MONTHS,
                test_months=WF_TEST_MONTHS,
                step_months=WF_STEP_MONTHS,
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
    finally:
        tmpdir.cleanup()
    return results.get("summary", {})


def _framework_cpcv_block(bars, seed, inject_effect):
    """Run the framework's own cpcv_analysis on the same fixture.

    Returns its summary, so callers can read the framework's own
    ``summary["test_resolution"]`` and ``summary["deflated_alpha"]`` blocks
    and compare them with what the measurement reports for the identical
    configuration.
    """
    tmpdir, data, benchmarks = _control_fixture(bars, seed, inject_effect)
    try:
        strategy_factory = _make_strategy_factory("sma_crossover")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            results = cpcv_analysis(
                data=data,
                strategy_factory=strategy_factory,
                param_grid=PARAM_GRID,
                n_splits=CPCV_N_SPLITS,
                test_size=CPCV_TEST_SIZE,
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
    finally:
        tmpdir.cleanup()
    return results.get("summary", {})


def test_each_path_reports_the_framework_s_own_alpha_block():
    """The measurement reads the framework's alpha block, not a private copy.

    The walk-forward and CPCV paths are measured by calling the framework's
    own ``walk_forward_analysis`` and ``cpcv_analysis`` and reading the
    ``summary["test_resolution"]`` block those functions attach. This test
    runs them again, directly, on the same fixture, and requires the
    measurement to report exactly what they report for the minimum
    confirmable annualized alpha and the deflation benchmark alpha* -- so
    it measures the shipped configuration of each path's criterion 5, not
    a copy of it.
    """
    bars = SMALL_SAMPLE_BARS
    seed = 7
    measured = _measured(bars, seed, False)
    for path, framework in (
        (WALK_FORWARD, _framework_wf_block(bars, seed, False)),
        (CPCV, _framework_cpcv_block(bars, seed, False)),
    ):
        resolution = framework.get("test_resolution")
        assert isinstance(resolution, dict), (
            f"the framework did not attach a test_resolution block to its {path} summary"
        )
        block = measured["paths"][path]
        assert block["min_detectable_alpha"] == resolution["min_detectable_alpha"], (
            f"the {path} measurement must report the framework's own minimum "
            "confirmable annualized alpha"
        )
        assert block["expected_max_alpha"] == (
            framework["deflated_alpha"]["expected_max_alpha"]
        ), (
            f"the {path} measurement must report the framework's own deflation "
            "benchmark alpha*"
        )


def test_the_alpha_bound_is_crossed_later_than_the_sharpe_bound():
    """Criterion 5 needs a larger sample than criterion 2 on some paths.

    The alpha plausibility bound (10% annualized alpha) is much stricter
    than the Sharpe one (2.0 annualized Sharpe), so the minimum confirmable
    alpha stays above it longer. Measured on the control fixture, over
    three seeds and both series:

    * out-of-sample: criterion 5 crosses the bound at the same sample sizes
      as criterion 2 (5,000 bars on some draws, 10,000 bars on every draw);
    * walk-forward: criterion 5 is crossed on some draws already at 2,500
      bars, but never on every draw measured, and its alpha floor (alpha*)
      is above the bound at every rung of THIS ladder -- so no sample size
      measured here would let this path confirm a plausible alpha on every
      draw;
    * CPCV: criterion 5 is crossed on some draws at 5,000 bars, later than
      criterion 2 (which is crossed on every draw already at 2,500 bars),
      and never on every draw measured.

    "Every rung of THIS ladder" is load-bearing: the ladder above stops at
    10,000 bars, and the walk-forward path's alpha floor comes under the
    10% bound at 25,000 bars. The flag is a statement about the rungs
    measured, not about every sample size, and the section below measures
    the longer ladder that settles it.
    """
    summary = summarize(_ladder_rows())
    by_path = summary["by_path"]

    # The out-of-sample path crosses the alpha bound at the same sample
    # sizes as the Sharpe bound: 5,000 bars on some draws, 10,000 bars on
    # every draw.
    assert by_path[OUT_OF_SAMPLE]["first_size_all_within_alpha_bound"] == LARGE_SAMPLE_BARS
    assert by_path[OUT_OF_SAMPLE]["first_size_any_within_alpha_bound"] == MIDDLE_SAMPLE_BARS

    # The walk-forward path crosses the alpha bound on some draws already
    # at 2,500 bars, but never on every draw measured, and its alpha floor
    # (alpha*) is above the bound at every measured rung -- so no measured
    # sample size would let this path confirm a plausible alpha on every
    # draw.
    assert by_path[WALK_FORWARD]["first_size_any_within_alpha_bound"] == SMALL_SAMPLE_BARS
    assert by_path[WALK_FORWARD]["first_size_all_within_alpha_bound"] is None
    assert by_path[WALK_FORWARD]["alpha_floor_beyond_plausible_bound"] is True
    assert by_path[WALK_FORWARD]["alpha_floor_beyond_plausible_bound_at_largest_size"] is True

    # The CPCV path crosses the alpha bound on some draws at 5,000 bars --
    # later than the Sharpe bound, which it crosses on every draw already at
    # 2,500 bars -- and never on every draw measured.
    assert by_path[CPCV]["first_size_any_within_alpha_bound"] == MIDDLE_SAMPLE_BARS
    assert by_path[CPCV]["first_size_all_within_alpha_bound"] is None
    assert by_path[CPCV]["first_size_any_within_alpha_bound"] > (
        by_path[CPCV]["first_size_any_within_bound"]
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


# ---------------------------------------------------------------------------
# The held-out-fraction sweep on the POSITIVE CONTROL, and what the control
# and the null calibration together show.
#
# The sweep on the null series is measured above. This section measures the
# same sweep on the effect series -- the series the machinery has to be able
# to confirm -- and pins the two together:
#
#   * the resolution (the smallest effect the significance tests could have
#     confirmed) is nearly the SAME on both series, so it is a property of
#     the sample -- its size, its trial count, its realized volatility --
#     and not of whether the strategy has an edge;
#   * the OBSERVED statistic is what separates them, so the machinery
#     discriminates: the control's observed Sharpe is above the framework's
#     plausibility bound and the null's is not, on the same fixture at the
#     same split on the same seed;
#   * every number is the framework's own block, re-run directly, and no
#     threshold, bound, criterion or verdict moves.
#
# The fixture is a formula, not a market: these are properties of a
# construction and of the decision machinery, never evidence about a
# security.
# ---------------------------------------------------------------------------

# Measurements at a given split, computed once and shared by the tests that
# read them (each point is a full walk-forward validation).
_SPLIT_MEASUREMENTS = {}


def _measured_split(bars, seed, inject_effect, train_frac, val_frac, test_frac):
    """One measurement at one split, on the out-of-sample path only.

    The sweep measures the out-of-sample path -- the path the pre-registered
    criteria are evaluated on -- so this measures that path only; the other
    two paths are measured by the ladder tests above.
    """
    key = (bars, seed, bool(inject_effect), train_frac, val_frac, test_frac)
    if key not in _SPLIT_MEASUREMENTS:
        _SPLIT_MEASUREMENTS[key] = measure_synthetic(
            bars,
            seed,
            bool(inject_effect),
            train_frac=train_frac,
            val_frac=val_frac,
            test_frac=test_frac,
            paths=(OUT_OF_SAMPLE,),
        )
    return _SPLIT_MEASUREMENTS[key]


def _sweep_rows(bars, seeds, test_fracs, inject_effect):
    """The rows a held-out-fraction sweep is made of, read from the cache."""
    rows = []
    for test_frac in test_fracs:
        for seed in seeds:
            rows.append(
                _measured_split(
                    bars, seed, inject_effect, 0.8 - test_frac, VAL_FRAC, test_frac
                )
            )
    return rows


def test_the_effect_series_sweep_matches_the_framework_own_block():
    """The control's swept numbers are the framework's own blocks.

    The effect series is the one the machinery has to be able to confirm, so
    the sweep measured on it must be the framework's own `test_resolution`,
    `deflated_sharpe` and `deflated_alpha` blocks -- not a private copy of
    them. This test re-runs the framework's out-of-sample path directly, on
    the same fixture at the same split, and requires the measurement to
    report exactly what the framework reports: the minimum confirmable
    effect, the deflation floors, the observation count, the observed
    statistic and the bound flags. No threshold, bound, criterion or verdict
    moves.
    """
    for bars in (MIDDLE_SAMPLE_BARS, LARGE_SAMPLE_BARS):
        for test_frac in (0.1, 0.2, 0.3):
            train_frac = 0.8 - test_frac
            measured = _measured_split(
                bars, 7, True, train_frac, VAL_FRAC, test_frac
            )
            block = measured["paths"][OUT_OF_SAMPLE]
            framework_summary, _ = _framework_oos_block(
                bars, 7, True, train_frac, VAL_FRAC, test_frac
            )
            framework = framework_summary.get("test_resolution")
            assert isinstance(framework, dict), (
                f"{bars} bars test_frac={test_frac}: the framework did not "
                "attach a test_resolution block to its summary"
            )
            assert block["min_detectable_sharpe"] == framework["min_detectable_sharpe"], (
                f"{bars} bars test_frac={test_frac}: the measured minimum "
                "confirmable Sharpe must equal the framework's own block"
            )
            assert block["min_detectable_alpha"] == framework["min_detectable_alpha"], (
                f"{bars} bars test_frac={test_frac}: the measured minimum "
                "confirmable alpha must equal the framework's own block"
            )
            assert block["n_test_observations"] == framework["n_test_observations"]
            assert block["expected_max_sharpe"] == (
                framework_summary["deflated_sharpe"]["expected_max_sharpe"]
            ), (
                f"{bars} bars test_frac={test_frac}: the measured deflation "
                "floor (SR*) must equal the framework's own Deflated Sharpe block"
            )
            assert block["expected_max_alpha"] == (
                framework_summary["deflated_alpha"]["expected_max_alpha"]
            ), (
                f"{bars} bars test_frac={test_frac}: the measured deflation "
                "floor (alpha*) must equal the framework's own Deflated Alpha block"
            )
            assert block["observed_annualized_sharpe"] == (
                framework["observed_annualized_sharpe"]
            )
            assert block["observed_annualized_alpha"] == (
                framework["observed_annualized_alpha"]
            )
            # The bound flag is the framework's own comparison, not a
            # recomputed one: the measurement cannot move it.
            assert block["sharpe_beyond_plausible_bound"] == (
                framework["min_detectable_sharpe"] > PLAUSIBLE_MAX_ANNUALIZED_SHARPE
            )
            assert block["alpha_beyond_plausible_bound"] == (
                framework["min_detectable_alpha"] > PLAUSIBLE_MAX_ANNUALIZED_ALPHA
            )
            # And the bounds the sweep compares against stay where they are.
            assert block["plausible_max_annualized_sharpe"] == PLAUSIBLE_MAX_ANNUALIZED_SHARPE
            assert block["plausible_max_annualized_alpha"] == PLAUSIBLE_MAX_ANNUALIZED_ALPHA


def test_the_control_discriminates_the_effect_series_from_the_null():
    """Same fixture, same split, same seed: the observed statistic separates.

    The control's job is to show the machinery can say yes, and the null
    calibration's job is to show it does not say yes for free. Measured
    here on the resolution machinery, at every swept held-out fraction and
    on every seed:

    * the effect series' observed annualized Sharpe is ABOVE the framework's
      plausibility bound (2.0) and its observed annualized alpha is above
      the alpha bound (10%);
    * the null series' observed statistics are not: the null's Sharpe never
      reaches the bound (its best draw is 0.34) and its alpha never reaches
      5.1% (the bound is 10%);
    * while the two series' MINIMUM CONFIRMABLE effects are nearly the same
      -- within 0.5 annualized Sharpe and within 0.08 annualized alpha at
      every swept point (the measured worst cases are 0.398 and 0.050).

    That is the finding: the resolution is a property of the sample, and
    the observed statistic is what carries the edge. A machinery that could
    not tell the two apart would report the same resolution for both --
    which is exactly what it does -- but it must NOT report the same
    observed statistic, and it does not.

    No verdict moves: the measurement reports a resolution and an observed
    statistic, never a verdict, and the bounds it compares them against are
    the framework's own.
    """
    for bars in (MIDDLE_SAMPLE_BARS, LARGE_SAMPLE_BARS):
        for test_frac in (0.1, 0.2, 0.3):
            for seed in SEEDS:
                effect = _measured_split(
                    bars, seed, True, 0.8 - test_frac, VAL_FRAC, test_frac
                )["paths"][OUT_OF_SAMPLE]
                null = _measured_split(
                    bars, seed, False, 0.8 - test_frac, VAL_FRAC, test_frac
                )["paths"][OUT_OF_SAMPLE]
                where = f"{bars} bars test_frac={test_frac} seed={seed}"

                # The control's observed effect clears the framework's own
                # plausibility bounds...
                assert effect["observed_annualized_sharpe"] > (
                    PLAUSIBLE_MAX_ANNUALIZED_SHARPE
                ), (
                    f"{where}: the control's observed annualized Sharpe must "
                    f"exceed the plausibility bound, got "
                    f"{effect['observed_annualized_sharpe']}"
                )
                assert effect["observed_annualized_alpha"] > (
                    PLAUSIBLE_MAX_ANNUALIZED_ALPHA
                ), (
                    f"{where}: the control's observed annualized alpha must "
                    f"exceed the alpha bound, got "
                    f"{effect['observed_annualized_alpha']}"
                )

                # ...and the null's does not.
                assert null["observed_annualized_sharpe"] <= (
                    PLAUSIBLE_MAX_ANNUALIZED_SHARPE
                ), (
                    f"{where}: the null series' observed annualized Sharpe "
                    "must not reach the plausibility bound, got "
                    f"{null['observed_annualized_sharpe']}"
                )
                assert null["observed_annualized_alpha"] <= (
                    PLAUSIBLE_MAX_ANNUALIZED_ALPHA
                ), (
                    f"{where}: the null series' observed annualized alpha "
                    "must not reach the alpha bound, got "
                    f"{null['observed_annualized_alpha']}"
                )

                # The two observed statistics are far apart.
                assert (
                    effect["observed_annualized_sharpe"]
                    - null["observed_annualized_sharpe"]
                ) > 1.0, (
                    f"{where}: the control's and the null's observed "
                    "annualized Sharpe must differ by more than 1.0, got "
                    f"{effect['observed_annualized_sharpe']} and "
                    f"{null['observed_annualized_sharpe']}"
                )

                # The resolution barely moves between the two samples: it is
                # a property of the sample, not of the edge.
                assert abs(
                    effect["min_detectable_sharpe"] - null["min_detectable_sharpe"]
                ) < 0.5, (
                    f"{where}: the minimum confirmable Sharpe must be nearly "
                    "the same on the control and on the null, got "
                    f"{effect['min_detectable_sharpe']} and "
                    f"{null['min_detectable_sharpe']}"
                )
                assert abs(
                    effect["min_detectable_alpha"] - null["min_detectable_alpha"]
                ) < 0.08, (
                    f"{where}: the minimum confirmable alpha must be nearly "
                    "the same on the control and on the null, got "
                    f"{effect['min_detectable_alpha']} and "
                    f"{null['min_detectable_alpha']}"
                )

                # No verdict moves: the measurement reports numbers, and the
                # bounds it compares them against are the framework's own.
                assert PLAUSIBLE_MAX_ANNUALIZED_SHARPE == 2.0
                assert PLAUSIBLE_MAX_ANNUALIZED_ALPHA == 0.10
                assert effect["plausible_max_annualized_sharpe"] == (
                    PLAUSIBLE_MAX_ANNUALIZED_SHARPE
                )
                assert effect["plausible_max_annualized_alpha"] == (
                    PLAUSIBLE_MAX_ANNUALIZED_ALPHA
                )


def test_the_effect_series_sweep_crossings_are_pinned():
    """The control's crossings, measured on the effect series.

    The null series' crossings are pinned above; this is the same sweep on
    the positive control, so the two can be compared:

    * at 5,000 bars no swept held-out fraction brings EVERY draw inside the
      Sharpe bound -- the control's own sample cannot resolve a plausible
      effect at that size either -- while fraction 0.2 already brings SOME
      draw inside it, and at fraction 0.1 every draw is still beyond both
      bounds;
    * at 10,000 bars every draw is inside the Sharpe bound at every swept
      fraction, and the alpha bound is inside for every draw from fraction
      0.2 on (at 0.1 one draw is still beyond it).

    The alpha crossing at 5,000 bars is a hair's breadth: seed 1's minimum
    confirmable alpha is 0.1041 against the 0.10 bound at fraction 0.2 and
    0.0999 at fraction 0.3. It is reported rather than pinned, because a
    pin that thin would fail on a rounding difference rather than on a
    change of substance.
    """
    for bars in (MIDDLE_SAMPLE_BARS, LARGE_SAMPLE_BARS):
        rows = _sweep_rows(bars, SEEDS, (0.1, 0.2, 0.3), True)
        stats, first_all, first_any, first_all_alpha, first_any_alpha = (
            _summarize_test_frac_sweep(rows)
        )
        by_frac = {entry["test_frac"]: entry for entry in stats}

        if bars == MIDDLE_SAMPLE_BARS:
            assert first_any == 0.2, (
                "at 5,000 bars some draw must be inside the Sharpe bound from "
                f"the 0.2 held-out fraction on, got {first_any}"
            )
            assert first_all is None, (
                "at 5,000 bars no held-out fraction may bring every draw "
                f"inside the Sharpe bound, got {first_all}"
            )
            assert by_frac[0.1]["all_within_alpha_bound"] is False, (
                "at 5,000 bars every draw must still be beyond the alpha bound "
                "at the 0.1 held-out fraction"
            )
        else:
            assert first_all == 0.1, (
                "at 10,000 bars every draw must be inside the Sharpe bound at "
                f"every swept held-out fraction, got {first_all}"
            )
            assert first_any == 0.1
            assert first_all_alpha == 0.2, (
                "at 10,000 bars the alpha bound must be inside for every draw "
                f"from the 0.2 held-out fraction on, got {first_all_alpha}"
            )
            assert first_any_alpha == 0.1, (
                "at 10,000 bars some draw must be inside the alpha bound at "
                f"the 0.1 held-out fraction, got {first_any_alpha}"
            )

        # The reported crossings agree with the per-fraction flags: no
        # verdict moves between the flags and the summary.
        flag_all = [e["test_frac"] for e in stats if e["all_within_alpha_bound"]]
        flag_any = [e["test_frac"] for e in stats if e["any_within_alpha_bound"]]
        assert (first_all_alpha is None) == (not flag_all)
        assert (first_any_alpha is None) == (not flag_any)
        if first_all_alpha is not None:
            assert first_all_alpha == min(flag_all)
        if first_any_alpha is not None:
            assert first_any_alpha == min(flag_any)


def test_the_sweep_names_the_series_it_measured():
    """A sweep table says which series it is.

    The null calibration and the positive control answer different
    questions, and a table that does not name its series can be read as
    the wrong one. The default (``--series both``) therefore measures both
    and prints both, each labeled, and the labels are the ones the rows
    themselves carry.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exit_code = measurement_main(
            ["--sizes", "2500", "--seeds", "7", "--test-fracs", "0.2"]
        )
    output = buffer.getvalue()

    assert exit_code == 0
    assert "series: no_effect" in output, (
        "the sweep must label the no-effect (null calibration) table"
    )
    assert "series: effect" in output, (
        "the sweep must label the effect (positive control) table"
    )
    assert output.count("held-out fraction sweep") == 2, (
        "the default sweep must measure both series and print both tables"
    )

    # A single-series sweep says so too, and says which one.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exit_code = measurement_main(
            ["--sizes", "2500", "--seeds", "7", "--test-fracs", "0.2", "--series", "effect"]
        )
    output = buffer.getvalue()
    assert exit_code == 0
    assert "series: effect" in output
    assert "series: no_effect" not in output


def test_the_sweep_refuses_to_report_a_real_history_it_did_not_measure():
    """The sweep measures the control fixture, and says so.

    The held-out-fraction sweep is defined on the synthetic control
    fixture. Combining it with ``--data`` would print the fixture's
    numbers under the real history's name, so the combination is refused
    instead.
    """
    stdout = io.StringIO()
    stderr = io.StringIO()
    raised = False
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            measurement_main(
                ["--sizes", "2500", "--test-fracs", "0.2", "--data", "history.csv"]
            )
    except SystemExit as exc:
        raised = True
        assert exc.code == 2, (
            f"the refusal must be an argparse error (exit 2), got {exc.code}"
        )
    assert raised, (
        "the sweep must refuse --data instead of reporting the control "
        "fixture's numbers under the real history's name"
    )


# ---------------------------------------------------------------------------
# THE FLOOR'S VERDICT IS SCOPED TO THE MEASURED RANGE.
#
# The tool answers "is there a sample size at which this path could confirm
# a plausible effect?" from the ladder it measured. The floor (SR*, alpha*)
# is the level below which no sample size can confirm an effect, so a floor
# above the plausibility bound used to be printed as an absolute conclusion:
# "no sample size would let this path confirm a plausible alpha".
#
# Measured on the control fixture, that conclusion is FALSIFIED by the next
# rung: the walk-forward path's alpha floor is above the 10% bound at every
# rung up to 10,000 bars and under it at 25,000. So the conclusion is scoped
# to the measured range and the largest rung measured is named, and the case
# where the floor has come under the bound -- the one case in which the
# floor stops being the reason a criterion cannot be satisfied -- is
# reported instead of being silently dropped.
#
# The measured ladder this rests on is captured in
# ``tests/fixtures/resolution_ladder_2500_to_50000.json`` with its
# provenance (command, commit, environment, fixture construction), and one
# rung of it is re-measured live below.
# ---------------------------------------------------------------------------

LADDER_FIXTURE = (
    SKILLS_DIR / "tests" / "fixtures" / "resolution_ladder_2500_to_50000.json"
)


def _load_ladder_fixture():
    """The measured ladder, with its provenance."""
    with open(LADDER_FIXTURE, "r") as handle:
        return json.load(handle)


def _floor_rows(path, rungs):
    """Rows carrying only a floor and a resolution, one row per rung.

    ``rungs`` is a sequence of ``(bars, floor, min_detectable_sharpe,
    min_detectable_alpha)``. The floor is used for both criteria, so the
    Sharpe and the alpha side can be driven independently.
    """
    rows = []
    for bars, floor, mde_sharpe, mde_alpha in rungs:
        rows.append(
            {
                "bars": bars,
                "seed": 7,
                "series": "effect",
                "paths": {
                    path: {
                        "min_detectable_sharpe": mde_sharpe,
                        "min_detectable_alpha": mde_alpha,
                        "expected_max_sharpe": floor,
                        "expected_max_alpha": floor,
                    }
                },
            }
        )
    return rows


def _printed_summary(rows, path):
    """The summary the tool prints for one path, as text."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        print_path_summary(summarize(rows), path)
    return buffer.getvalue()


def test_the_summary_reports_what_sets_the_alpha_floor():
    """The alpha floor is reported with the driver that sets it.

    A floor quoted as a bare number is not readable: the number is not what
    a reader would guess, and a *high* floor is easily misread as a bigger
    search or a worse test. It is in fact the strategy's own edge over its
    benchmark set (the dispersion of the benchmark alphas, scaled by the
    expected maximum of N draws), so the summary has to say so and to carry
    the numbers that reproduce the floor.
    """
    rows = [_measured(SMALL_SAMPLE_BARS, 7, False)]
    stats = summarize(rows)["by_path"][WALK_FORWARD]

    driver = stats["alpha_floor_driver"]
    assert driver["identity"] == (
        "alpha* = std(benchmark alphas, ddof=1) * sqrt(2 ln N)"
    )
    assert driver["identity_holds_on_every_measured_draw"] is True, (
        "the floor the framework reported must be reproducible from the "
        "benchmark alphas the framework reported"
    )

    at_largest = driver["at_largest_measured_size"]
    assert at_largest is not None
    assert at_largest["n_benchmarks"] == 2
    assert abs(
        at_largest["alpha_star_from_dispersion"] - at_largest["expected_max_alpha"]
    ) < 1e-12, (
        "the driver must reproduce the floor the framework reported"
    )
    assert abs(
        at_largest["expected_max_alpha"] - stats["alpha_floor_at_largest_size"]
    ) < 1e-12, (
        "the driver reported must be the driver of the floor the summary "
        "quotes"
    )
    # The strategy's own alpha is the primary benchmark's alpha, so the
    # driver is the strategy's edge over its benchmark set.
    assert any(
        abs(a - at_largest["strategy_alpha"]) < 1e-12
        for a in at_largest["benchmark_alphas"]
    )

    output = _printed_summary(rows, WALK_FORWARD)
    assert "what sets the alpha floor" in output, (
        "the report must say what sets the floor, not only what it is"
    )
    assert "std(benchmark alphas, ddof=1) * sqrt(2 ln N)" in output
    assert "reproduced from the benchmark alphas" in output, (
        "the report must state that the floor is reproduced from the "
        "benchmark alphas"
    )
    assert "not a bigger search" in output, (
        "the report must say what a higher floor does and does not mean"
    )


def test_the_floor_conclusion_is_scoped_to_the_measured_range():
    """A floor above the bound is a statement about the ladder, not about
    every sample size.

    The floor falls as the sample grows -- it is estimated from trial
    Sharpes (criterion 2) or benchmark alphas (criterion 5) that are
    themselves estimated on more data -- so a ladder that stops short of the
    crossing cannot settle "is there such a sample size at all?". The
    printed conclusion is therefore scoped to the rungs measured, and names
    the largest one.
    """
    rows = _floor_rows(
        WALK_FORWARD,
        [
            (2500, 2.5, 3.1, 0.20),
            (10000, 2.5, 2.6, 0.15),
        ],
    )
    output = _printed_summary(rows, WALK_FORWARD)

    assert "no measured sample size would let this path confirm a plausible alpha" in output, (
        "the conclusion must be scoped to the sample sizes actually measured"
    )
    assert "no sample size would let this path confirm a plausible alpha" not in output, (
        "an unscoped conclusion claims more than the ladder supports: the "
        "measured walk-forward alpha floor is under the 10% bound at 25,000 "
        "bars, so 'no sample size' is false"
    )
    assert "no measured sample size would let this path confirm a plausible effect" in output, (
        "the Sharpe floor's conclusion must be scoped the same way"
    )
    assert "no sample size would let this path confirm a plausible effect" not in output
    assert "(up to 10000 bars)" in output, (
        "the conclusion must name the largest rung it measured"
    )


def test_the_summary_reports_the_floor_when_it_stops_blocking_the_path():
    """A floor that has come under the bound is reported, not dropped.

    Both branches the summary used to print required the floor to be *above*
    the plausibility bound, so a floor that had come under it -- the one
    case in which the floor is no longer the reason a criterion cannot be
    satisfied -- was silently absent from the summary. The path's criterion
    5 can confirm a plausible alpha at 50,000 bars, and the summary has to
    say so.
    """
    rows = _floor_rows(
        WALK_FORWARD,
        [
            (25000, 0.087, 0.10, 0.1002),
            (50000, 0.084, 0.09, 0.0936),
        ],
    )
    output = _printed_summary(rows, WALK_FORWARD)

    assert "does not block criterion 5" in output, (
        "the summary must report that the alpha floor no longer blocks "
        "criterion 5 at the largest measured sample size"
    )
    assert "50000 bars" in output
    assert "does not block criterion 2" in output, (
        "the same must hold for the Sharpe floor"
    )
    assert "no sample size would let this path confirm a plausible alpha" not in output
    assert "no sample size would let this path confirm a plausible effect" not in output

    # And the flags the message is read from say the same thing.
    stats = summarize(rows)["by_path"][WALK_FORWARD]
    assert stats["alpha_floor_beyond_plausible_bound"] is False
    assert stats["alpha_floor_beyond_plausible_bound_at_largest_size"] is False
    assert stats["alpha_floor_at_largest_size"] < PLAUSIBLE_MAX_ANNUALIZED_ALPHA
    assert stats["largest_measured_size"] == 50000


def test_the_measured_ladder_finds_the_alpha_crossing_the_shorter_ladder_missed():
    """The longer ladder settles what the shorter one could not.

    On the ladder that stops at 10,000 bars, the walk-forward path's alpha
    floor is above the 10% plausibility bound at every rung measured. On
    the ladder that goes on to 25,000 and 50,000 bars it is not: the floor
    comes under the bound at 25,000 bars, and at 50,000 bars every draw
    measured is inside the bound. The shorter ladder's answer was a
    statement about the rungs it measured, not about the path.

    The numbers are the measured ones, captured with their provenance in
    ``tests/fixtures/resolution_ladder_2500_to_50000.json``.
    """
    fixture = _load_ladder_fixture()
    rows = fixture["rows"]

    # The fixture says what it is and where it came from.
    provenance = fixture["provenance"]
    assert provenance["measured"]["sizes"] == [2500, 5000, 10000, 25000, 50000]
    assert provenance["measured"]["seeds"] == [7, 1, 2024]
    assert provenance["measured"]["draws_per_rung"] == 6
    assert "measure_resolution_vs_sample_size.py" in provenance["command"]
    assert provenance["script_commit"]
    assert len(rows) == 5 * 6

    short = [row for row in rows if row["bars"] <= LARGE_SAMPLE_BARS]
    full = rows

    short_summary = summarize(short)["by_path"]
    full_summary = summarize(full)["by_path"]

    # The shorter ladder: the walk-forward alpha floor is above the bound at
    # every rung measured. This is the same verdict the live ladder reaches
    # (the test below measures the same rungs), so the fixture is a faithful
    # record of the measurement and not a different one.
    assert short_summary[WALK_FORWARD]["alpha_floor_beyond_plausible_bound"] is True
    assert short_summary[WALK_FORWARD]["alpha_floor_beyond_plausible_bound_at_largest_size"] is True
    assert short_summary[WALK_FORWARD]["first_size_all_within_alpha_bound"] is None

    # The longer ladder: the floor comes under the bound and the path
    # confirms a plausible alpha on every draw at 50,000 bars.
    walk = full_summary[WALK_FORWARD]
    assert walk["alpha_floor_beyond_plausible_bound"] is False, (
        "the walk-forward alpha floor is under the 10% bound at the larger "
        "rungs, so the 'above the bound at every rung' verdict does not hold "
        "on the longer ladder"
    )
    assert walk["alpha_floor_at_largest_size"] < PLAUSIBLE_MAX_ANNUALIZED_ALPHA
    assert walk["first_size_all_within_alpha_bound"] == 50000, (
        "criterion 5 on the walk-forward path is inside the alpha bound on "
        "every draw measured at 50,000 bars"
    )
    assert walk["largest_measured_size"] == 50000

    # The CPCV path crosses the alpha bound earlier than the walk-forward
    # path, and the out-of-sample path earlier than both.
    assert full_summary[CPCV]["first_size_all_within_alpha_bound"] == 25000
    assert full_summary[OUT_OF_SAMPLE]["first_size_all_within_alpha_bound"] == 10000
    assert full_summary[OUT_OF_SAMPLE]["first_size_all_within_bound"] == 10000

    # Criterion 2 is crossed by every path well before criterion 5.
    assert full_summary[WALK_FORWARD]["first_size_all_within_bound"] == 5000
    assert full_summary[CPCV]["first_size_all_within_bound"] == 2500


def test_the_measured_ladder_is_the_frameworks_own_numbers():
    """The captured ladder is the framework's own blocks, at its own bounds.

    Every number in the fixture is the block the framework attaches to its
    own summary, so the fixture is checked against the framework's own
    bound flags and against the bounds the framework uses now: if a
    plausibility bound ever moves, this test fails and the fixture is
    visibly stale rather than quietly wrong.
    """
    fixture = _load_ladder_fixture()
    provenance = fixture["provenance"]

    assert provenance["plausibility_bounds"]["plausible_max_annualized_sharpe"] == (
        PLAUSIBLE_MAX_ANNUALIZED_SHARPE
    )
    assert provenance["plausibility_bounds"]["plausible_max_annualized_alpha"] == (
        PLAUSIBLE_MAX_ANNUALIZED_ALPHA
    )

    for row in fixture["rows"]:
        for path, block in row["paths"].items():
            sharpe = block["min_detectable_sharpe"]
            alpha = block["min_detectable_alpha"]
            assert block["sharpe_beyond_plausible_bound"] == (
                sharpe is not None and sharpe > PLAUSIBLE_MAX_ANNUALIZED_SHARPE
            ), f"{path} at {row['bars']} bars: the framework's own bound flag does not match its own resolution"
            assert block["alpha_beyond_plausible_bound"] == (
                alpha is not None and alpha > PLAUSIBLE_MAX_ANNUALIZED_ALPHA
            ), f"{path} at {row['bars']} bars: the framework's own bound flag does not match its own resolution"
            # The floor cannot sit above the resolution that converges onto it.
            assert block["expected_max_sharpe"] <= block["min_detectable_sharpe"]
            assert block["expected_max_alpha"] <= block["min_detectable_alpha"]


def test_the_walk_forward_alpha_floor_is_under_the_bound_at_25000_bars():
    """Live re-measurement of the rung the shorter ladder could not see.

    One rung of the captured ladder is measured again from scratch, so the
    fixture is checked against a fresh run of the framework rather than
    against itself. The walk-forward path's alpha floor is under the 10%
    plausibility bound at 25,000 bars -- which is the measurement that
    falsifies the absolute "no sample size" conclusion.
    """
    measured = measure_synthetic(25000, 7, True, paths=(WALK_FORWARD,))
    block = measured["paths"][WALK_FORWARD]

    assert block["expected_max_alpha"] < PLAUSIBLE_MAX_ANNUALIZED_ALPHA, (
        "the walk-forward alpha floor is under the 10% bound at 25,000 bars"
    )
    assert block["min_detectable_alpha"] < PLAUSIBLE_MAX_ANNUALIZED_ALPHA, (
        "the walk-forward path can confirm a plausible alpha at 25,000 bars"
    )
    assert block["n_test_observations"] > 10000, (
        "the walk-forward path prices its test on the pooled out-of-sample "
        "windows, so it has more test observations than the sample"
    )

    # The floor is still under the bound on the null calibration, so this is
    # a property of the path and the sample, not of the injected effect.
    null = measure_synthetic(25000, 7, False, paths=(WALK_FORWARD,))
    assert null["paths"][WALK_FORWARD]["expected_max_alpha"] < (
        PLAUSIBLE_MAX_ANNUALIZED_ALPHA
    )


def test_the_default_ladder_brackets_the_measured_alpha_crossing():
    """The default ladder reaches the rungs where the crossings happen.

    The default ladder used to stop at 10,000 bars, which is before the
    criterion 5 crossings: the walk-forward path confirms a plausible alpha
    at 50,000 bars and the CPCV path at 25,000. A default ladder that
    cannot see the crossing reports "no measured sample size" for a path
    that has one, so the default ladder carries the rungs where the
    crossings were measured.
    """
    assert 10000 in DEFAULT_SIZES, "criterion 2 crosses at 10,000 bars"
    assert 25000 in DEFAULT_SIZES, "the CPCV alpha crossing is at 25,000 bars"
    assert 50000 in DEFAULT_SIZES, "the walk-forward alpha crossing is at 50,000 bars"
    assert max(DEFAULT_SIZES) >= 50000


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
    ("test_each_path_reports_the_framework_s_own_alpha_block", test_each_path_reports_the_framework_s_own_alpha_block),
    ("test_the_alpha_bound_is_crossed_later_than_the_sharpe_bound", test_the_alpha_bound_is_crossed_later_than_the_sharpe_bound),
    ("test_the_paths_cross_the_plausibility_bound_at_different_sample_sizes", test_the_paths_cross_the_plausibility_bound_at_different_sample_sizes),
    ("test_the_floor_is_reported_for_every_path_and_every_rung", test_the_floor_is_reported_for_every_path_and_every_rung),
    ("test_the_measurement_moves_no_threshold_and_no_verdict_on_any_path", test_the_measurement_moves_no_threshold_and_no_verdict_on_any_path),
    ("test_test_frac_sweep_keeps_val_frac_and_sums_to_one", test_test_frac_sweep_keeps_val_frac_and_sums_to_one),
    ("test_test_frac_sweep_each_split_matches_the_framework_own_block", test_test_frac_sweep_each_split_matches_the_framework_own_block),
    ("test_test_frac_sweep_at_larger_sizes_matches_the_framework_own_block", test_test_frac_sweep_at_larger_sizes_matches_the_framework_own_block),
    ("test_test_frac_sweep_alpha_crossings_match_the_per_fraction_flags", test_test_frac_sweep_alpha_crossings_match_the_per_fraction_flags),
    ("test_the_effect_series_sweep_matches_the_framework_own_block", test_the_effect_series_sweep_matches_the_framework_own_block),
    ("test_the_control_discriminates_the_effect_series_from_the_null", test_the_control_discriminates_the_effect_series_from_the_null),
    ("test_the_effect_series_sweep_crossings_are_pinned", test_the_effect_series_sweep_crossings_are_pinned),
    ("test_the_sweep_names_the_series_it_measured", test_the_sweep_names_the_series_it_measured),
    ("test_the_sweep_refuses_to_report_a_real_history_it_did_not_measure", test_the_sweep_refuses_to_report_a_real_history_it_did_not_measure),
    ("test_shipped_default_split_is_unchanged", test_shipped_default_split_is_unchanged),
    ("test_the_floor_conclusion_is_scoped_to_the_measured_range", test_the_floor_conclusion_is_scoped_to_the_measured_range),
    ("test_the_summary_reports_the_floor_when_it_stops_blocking_the_path", test_the_summary_reports_the_floor_when_it_stops_blocking_the_path),
    ("test_the_measured_ladder_finds_the_alpha_crossing_the_shorter_ladder_missed", test_the_measured_ladder_finds_the_alpha_crossing_the_shorter_ladder_missed),
    ("test_the_measured_ladder_is_the_frameworks_own_numbers", test_the_measured_ladder_is_the_frameworks_own_numbers),
    ("test_the_walk_forward_alpha_floor_is_under_the_bound_at_25000_bars", test_the_walk_forward_alpha_floor_is_under_the_bound_at_25000_bars),
    ("test_the_default_ladder_brackets_the_measured_alpha_crossing", test_the_default_ladder_brackets_the_measured_alpha_crossing),
]


if __name__ == "__main__":
    sys.exit(main())
