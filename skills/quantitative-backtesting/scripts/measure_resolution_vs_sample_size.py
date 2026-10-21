#!/usr/bin/env python3
"""Measure the test resolution (minimum detectable effect) as a function of sample size.

WHAT THIS IS
    A measurement *beside* the verdict, never part of it. It answers one
    question:

        At the shipped configuration, how large must the sample be before
        the pre-registered significance criteria can confirm an effect of a
        plausible size -- and is there such a sample size at all?

    The framework's own helpers are the single source of truth. The script
    calls ``walk_forward.out_of_sample_validation`` (the shipped
    configuration), ``walk_forward.walk_forward_analysis`` and
    ``walk_forward.cpcv_analysis`` (the shipped configuration of the other
    two analysis paths) and reads the ``summary["test_resolution"]`` block
    each of them attaches to its own summary. It re-derives nothing,
    re-tunes nothing, and changes no threshold, no plausibility bound, no
    criterion and no verdict.

THE THREE PATHS ARE MEASURED SEPARATELY
    The paths do not see the same sample, so they do not have the same
    resolution:

    * ``out_of_sample`` -- the pre-registered criteria live here: the
      Deflated Sharpe test is evaluated on the *held-out test window*, so
      its resolution is governed by the length of that window (a fraction
      of the sample);
    * ``walk_forward`` -- the Deflated Sharpe test is evaluated on the
      pooled out-of-sample returns of every walk-forward window, so its
      resolution is governed by the whole sample;
    * ``cpcv`` -- the same, over the pooled out-of-sample returns of every
      CPCV fold.

    Each path therefore gets its own curve, its own crossing point and its
    own floor. Reading only one of them answers the question for that path
    only.

WHAT THE NUMBERS MEAN
    ``min_detectable_sharpe`` is the smallest *annualized* Sharpe the
    Deflated Sharpe test could have confirmed at the sample size actually
    available -- the resolution of criterion 2. ``expected_max_sharpe`` (the
    deflation benchmark SR*, read straight out of the framework's own
    Deflated Sharpe block) is the floor that resolution converges to: no
    sample size can make the test confirm an effect *below* it, because SR*
    is the Sharpe the parameter grid would produce from luck alone. The
    sample size only removes the ``1 / sqrt(T)`` term on top of that floor.

    So the question "can criterion 2 ever confirm a plausible effect?" has
    two parts, and the script reports both: the floor (a property of the
    data's trial-Sharpe dispersion) and the sample size at which the
    ``1 / sqrt(T)`` term has shrunk enough for the total to fall under the
    plausibility bound. When the floor itself exceeds the plausibility
    bound at every rung measured, the answer is "no *measured* sample
    size", and the summary says so -- naming the largest rung it measured,
    because the floor is estimated from trial Sharpes (criterion 2) or
    benchmark alphas (criterion 5) that are themselves estimated on more
    data as the sample grows, and a ladder that stops short of the
    crossing supports a statement about the ladder, not about every sample
    size. Measured on the control fixture, the walk-forward path's alpha
    floor was above the 10% bound at every rung up to 10,000 bars and
    under it at 25,000: the absolute reading was falsified by the next
    rung.

    CRITERION 5 IS MEASURED THE SAME WAY, IN PARALLEL
    ``min_detectable_alpha`` is the smallest *annualized* alpha the
    Deflated Alpha test could have confirmed at the sample size actually
    available -- the resolution of criterion 5. ``expected_max_alpha`` (the
    deflation benchmark alpha*, read straight out of the framework's own
    Deflated Alpha block) is the floor that resolution converges to. The
    per-path summary reports the alpha crossing alongside the Sharpe one
    (``per_size_alpha``, ``first_size_all_within_alpha_bound``,
    ``first_size_any_within_alpha_bound``, ``max_expected_max_alpha``,
    ``alpha_floor_at_largest_size`` and the ``alpha_floor_*`` flags).

    The two criteria are reported separately because they cross at
    *different* sample sizes: the alpha bound is the stricter of the two
    (a 10% annualized alpha is a much smaller effect than a 2.0 annualized
    Sharpe), so criterion 5's resolution stays above it longer. Measured
    on the control fixture, the CPCV path's minimum confirmable alpha is
    still 10-13% at 10,000 bars -- above the bound -- and is under it on
    every draw at 25,000; the walk-forward path needs 50,000. The report
    says so explicitly rather than leaving it implicit.

WHAT SETS THE ALPHA FLOOR
    The alpha floor is reported with the driver that sets it, because the
    number is not what a reader would guess. The framework estimates
    alpha* as the cross-sectional dispersion of the *benchmark* alphas
    scaled by the expected maximum of N draws::

        alpha* = std(benchmark alphas, ddof=1) * sqrt(2 * ln(N))

    so the floor tracks the strategy's own edge over its benchmark set --
    not the size of the parameter search -- and it does not fall to zero as
    the sample grows: only the estimation noise in the alphas shrinks, the
    gap between them survives. The report prints the driver and checks the
    identity against the framework's own ``expected_max_alpha``, so the
    floor can be reproduced from the numbers the summary carries. A higher
    alpha floor is a bigger gap, not a worse test.

A FLOOR THAT WAS NEVER MEASURED IS NOT A FLOOR OF ZERO
    The floor above is a measurement: the framework priced the Deflated
    Alpha criterion on that draw. When it could not price it, the alpha
    numbers the block carries are the degenerate output of the failed
    pricing -- on a zero-volatility draw the strategy's alpha, every
    benchmark alpha and the dispersion between them are all exactly zero --
    so the block's floor is a placeholder, not a measured floor of zero.

    Read as a measurement, that placeholder produces two false statements:
    that the floor is zero (it was never estimated), and that the floor
    "does not block criterion 5" (criterion 5 was never evaluated on that
    draw). The framework's own ``alpha_status`` / ``alpha_reason`` say
    which is which, and the report follows them: the floor is reported as
    not measured, with the framework's own reason, and the summary's floor
    flags are ``None`` (unknown) rather than ``False`` (measured, and not
    above the bound).

THE DATA IS SYNTHETIC
    By default the measurement runs on the synthetic control fixture
    (``scripts/generate_positive_control_data.py``): a series produced by a
    written-out formula, with a known injected effect and a matched
    no-effect control built from the identical draws. Both are used, because
    the resolution is a property of the *sample*: the no-effect series is
    the null calibration (the trial Sharpes there are pure estimation
    noise, which is what SR* is meant to measure) and the effect series is
    the control's own configuration. The numbers are properties of a formula
    and of the decision machinery -- never evidence about a security.

    ``--data FILE`` measures the same curve on a real history instead: each
    rung is the *first* N bars of that history, so the curve is the
    resolution the framework would have reported on a sample of that size.

THE HELD-OUT-FRACTION SWEEP NAMES ITS SERIES
    ``--test-fracs`` sweeps the held-out fraction at a fixed sample size
    (``val_frac`` stays 0.2, ``train_frac = 0.8 - test_frac``). The sweep
    measures the synthetic control fixture, and it says which series it
    measured: the no-effect series is the null calibration and the effect
    series is the positive control's own configuration, and their numbers
    answer different questions. ``--series both`` (the default) measures
    both and prints both, so a reader is never left guessing whether a
    table is the null or the control.

Usage
    python3 skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py
    python3 skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py \
        --sizes 1000,2500,5000,10000 --json
    python3 skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py \
        --paths walk_forward,cpcv
    python3 skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py \
        --data path/to/history.csv --sizes 2500,5000,10000,25000
    python3 skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py \
        --sizes 10000 --test-fracs 0.1,0.2,0.3 --series effect
"""

import argparse
import contextlib
import io
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from data_loader import load_data  # noqa: E402
from generate_positive_control_data import (  # noqa: E402
    CONTROL_BENCHMARK_SEED,
    CONTROL_STRATEGY_SEED,
    write_control_fixture,
)
from walk_forward import (  # noqa: E402
    PLAUSIBLE_MAX_ANNUALIZED_ALPHA,
    PLAUSIBLE_MAX_ANNUALIZED_SHARPE,
    _build_test_resolution,
    _make_strategy_factory,
    cpcv_analysis,
    out_of_sample_validation,
    walk_forward_analysis,
)

# ---------------------------------------------------------------------------
# The shipped configuration.
#
# These are the parameters the worked example
# (`examples/falsifiable_hypothesis_example.py`) passes to
# `out_of_sample_validation`. They are read from the example module itself
# where it exposes them, so the grid, the costs and the benchmark set cannot
# drift apart from the example; the window and the split are literals here
# because the example passes them inline.
#
# `tests/test_resolution_vs_sample_size.py` pins the equivalence the other
# way round: the resolution this script measures at a given sample size must
# equal the resolution the example's own shipped path reports on the same
# data. If the example's configuration changes, that test fails.
# ---------------------------------------------------------------------------
import falsifiable_hypothesis_example as example  # noqa: E402

PARAM_GRID = example.PARAM_GRID
COMMISSION = example.COMMISSION
SLIPPAGE = example.SLIPPAGE
BENCHMARK_FILES = example.BENCHMARK_FILES
TRAIN_FRAC, VAL_FRAC, TEST_FRAC = 0.6, 0.2, 0.2
WF_TRAIN_MONTHS, WF_TEST_MONTHS, WF_STEP_MONTHS = 6, 2, 2
# The CPCV configuration the ladder measures. It is the configuration the
# framework's own CPCV tests and examples use (5 splits, a test window of
# 20% of each group), so the curve reported here is the curve that
# configuration produces.
CPCV_N_SPLITS, CPCV_TEST_SIZE = 5, 0.2
INITIAL_CAPITAL = 100000
SELECTION_CRITERION = "best_avg_sharpe"

# The analysis paths the ladder measures. Each path runs its own
# significance test on its own out-of-sample return series, so each has its
# own resolution and its own floor.
PATH_OUT_OF_SAMPLE = "out_of_sample"
PATH_WALK_FORWARD = "walk_forward"
PATH_CPCV = "cpcv"
PATHS: Sequence[str] = (PATH_OUT_OF_SAMPLE, PATH_WALK_FORWARD, PATH_CPCV)

# The path the pre-registered criteria are evaluated on: the Deflated
# Sharpe test of the worked example runs on the held-out test window, so
# the out-of-sample path is the primary one. It is always measured, and the
# ladder row's top-level fields are its fields.
PRIMARY_PATH = PATH_OUT_OF_SAMPLE

PATH_LABELS = {
    PATH_OUT_OF_SAMPLE: "out-of-sample (held-out test window)",
    PATH_WALK_FORWARD: "walk-forward (pooled out-of-sample windows)",
    PATH_CPCV: "CPCV (pooled out-of-sample folds)",
}

# The ladder of sample sizes (business-day bars) the resolution is measured
# at. The default ladder brackets the crossing of the plausibility bound
# measured on the control's construction: criterion 2 is still out of reach
# at 2,500 bars and inside it by 10,000. It goes on to 25,000 and 50,000
# because criterion 5 crosses later than criterion 2 -- the walk-forward
# path's alpha floor comes under the 10% bound at 25,000 bars and every
# draw is inside the bound at 50,000 -- and a ladder that stopped at 10,000
# would report "no measured sample size" for a path that has one. The
# rungs cost minutes each (the two largest are minutes per draw), so the
# default run takes a while; pass --sizes to measure a narrower ladder.
DEFAULT_SIZES: Sequence[int] = (500, 1000, 2500, 5000, 10000, 25000, 50000)

# The seeds the measurement is repeated over. The crossing point moves a
# little with the draw, so a single seed would report a number that reads
# as a property of the framework rather than of one sample.
DEFAULT_SEEDS: Sequence[int] = (7, 1, 2024)

MEASUREMENT_NOTE = (
    "MEASUREMENT, NOT A VERDICT: no threshold, plausibility bound, "
    "criterion or verdict is changed by this script."
)


# The strategy factory the worked example builds: the framework's own
# `sma_crossover` factory, so the strategy under test is the same object
# the example trades.
_STRATEGY_FACTORY = _make_strategy_factory("sma_crossover")


def _run_framework(call, **kwargs) -> Dict[str, Any]:
    """Run one framework analysis, keeping its routine console output quiet.

    The routine point-in-time confirmation is filtered out; anything that is
    not a routine point-in-time confirmation is passed through, so a warning
    is never swallowed.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        results = call(**kwargs)
    for line in buffer.getvalue().splitlines():
        if not line.startswith("Point-in-time validation passed"):
            print(f"  [framework] {line}")
    return results


def _run_validation(
    data, benchmarks, train_frac=TRAIN_FRAC, val_frac=VAL_FRAC, test_frac=TEST_FRAC
) -> Dict[str, Any]:
    """Run the out-of-sample validation on one prepared sample.

    Defaults to the shipped 0.6/0.2/0.2 split; passing other fractions sweeps
    the held-out fraction (train_frac = 0.8 - test_frac, val_frac = 0.2).
    """
    return _run_framework(
        out_of_sample_validation,
        data=data,
        strategy_factory=_STRATEGY_FACTORY,
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


def _run_walk_forward(data, benchmarks) -> Dict[str, Any]:
    """Run the shipped walk-forward analysis on one prepared sample.

    The whole sample is this path's sample: it prices its own out-of-sample
    windows across it, and the resolution measured here is the resolution of
    the significance test that path actually runs on those windows.
    """
    return _run_framework(
        walk_forward_analysis,
        data=data,
        strategy_factory=_STRATEGY_FACTORY,
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


def _run_cpcv(data, benchmarks) -> Dict[str, Any]:
    """Run the shipped CPCV analysis on one prepared sample.

    As for the walk-forward path: the whole sample is this path's sample,
    and the resolution measured here is the resolution of the test that
    path runs on its pooled out-of-sample fold returns.
    """
    return _run_framework(
        cpcv_analysis,
        data=data,
        strategy_factory=_STRATEGY_FACTORY,
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


def _measure_path(
    path: str,
    summary: Dict[str, Any],
    returns,
    n_windows: int,
) -> Dict[str, Any]:
    """One analysis path's resolution block, read from its own summary.

    The block is the one the path attached to its summary
    (``summary["test_resolution"]``); it is not rebuilt here. The Deflated
    Sharpe block it was built from is read too, for the deflation benchmark
    SR*.
    """
    resolution = summary.get("test_resolution")
    if not isinstance(resolution, dict):
        resolution = _build_test_resolution(summary, returns)

    deflated_sharpe = summary.get("deflated_sharpe") or {}
    deflated_alpha = summary.get("deflated_alpha") or {}
    benchmark_metrics = summary.get("benchmark_metrics") or []
    # The same set the framework itself used as the trial alphas: the
    # benchmark rows with a finite alpha. Those are the alphas the Deflated
    # Alpha floor is estimated from, so the report can reconstruct the floor
    # from them.
    benchmark_alphas = [
        float(b["alpha"]) for b in benchmark_metrics
        if isinstance(b, dict) and "alpha" in b and b.get("alpha") is not None
        and np.isfinite(b["alpha"])
    ]
    benchmark_alpha_std = float(np.std(benchmark_alphas, ddof=1)) if len(benchmark_alphas) >= 2 else None
    return {
        "path": path,
        "min_detectable_sharpe": resolution.get("min_detectable_sharpe"),
        "min_detectable_alpha": resolution.get("min_detectable_alpha"),
        "observed_annualized_sharpe": resolution.get("observed_annualized_sharpe"),
        "observed_annualized_alpha": resolution.get("observed_annualized_alpha"),
        # The deflation benchmark: the floor the resolution converges to.
        "expected_max_sharpe": deflated_sharpe.get("expected_max_sharpe"),
        "expected_max_alpha": deflated_alpha.get("expected_max_alpha"),
        # Driver of the Deflated Alpha floor: alpha* = std(benchmark alphas,
        # ddof=1) * sqrt(2 ln N) (in Sharpe units, then annualized). The
        # strategy's own alpha and the dispersion/count of the benchmark
        # alphas make the floor reproducible from the report.
        "strategy_alpha": deflated_alpha.get("alpha"),
        "benchmark_alpha_std": benchmark_alpha_std,
        "benchmark_alphas": benchmark_alphas,
        "n_test_observations": resolution.get("n_test_observations"),
        "n_parameter_trials": resolution.get("n_parameter_trials"),
        "n_benchmarks": deflated_alpha.get("n_benchmarks", resolution.get("n_benchmarks")),
        "sharpe_beyond_plausible_bound": resolution.get(
            "sharpe_beyond_plausible_bound"
        ),
        "alpha_beyond_plausible_bound": resolution.get(
            "alpha_beyond_plausible_bound"
        ),
        "sharpe_status": resolution.get("sharpe_status"),
        "alpha_status": resolution.get("alpha_status"),
        "sharpe_reason": resolution.get("sharpe_reason"),
        "alpha_reason": resolution.get("alpha_reason"),
        # The windows the path's test observations came from.
        "n_windows": n_windows,
        "plausible_max_annualized_sharpe": PLAUSIBLE_MAX_ANNUALIZED_SHARPE,
        "plausible_max_annualized_alpha": PLAUSIBLE_MAX_ANNUALIZED_ALPHA,
    }


def _alpha_floor_measured(block: Dict[str, Any]) -> bool:
    """Whether a block's alpha floor is a measurement or a placeholder.

    The framework's own ``alpha_status`` is the record of whether the
    Deflated Alpha criterion (criterion 5) could be *priced* on that draw.
    When it could not, the alpha numbers the block carries are the
    degenerate output of the failed pricing: on a zero-volatility draw the
    strategy's alpha, every benchmark alpha and the dispersion between them
    are all exactly zero, so the floor the block reports is a placeholder,
    not a measured floor of zero.

    That distinction is the difference between "the floor is zero" and
    "the floor was never measured", and the report has to keep it: a floor
    that was never measured cannot be said not to block criterion 5, because
    criterion 5 was never evaluated on that draw.

    A block that carries no status at all (an older capture, written before
    the status was recorded) is treated as measured: every block in the
    committed captures is a resolvable one, and the alternative would
    silently drop a real floor from a summary that used to report it.
    """
    status = block.get("alpha_status")
    if status is None:
        return True
    return status == "resolvable"


def _sharpe_floor_measured(block: Dict[str, Any]) -> bool:
    """Whether a block's Sharpe floor is a measurement or a placeholder.

    Mirror of ``_alpha_floor_measured`` for criterion 2. The framework's
    own ``sharpe_status`` records whether the Deflated Sharpe criterion
    could be priced on that draw. When it could not, the floor the block
    carries is a placeholder rather than a measurement.
    """
    status = block.get("sharpe_status")
    if status is None:
        return True
    return status == "resolvable"


def _alpha_floor_driver(block: Dict[str, Any]) -> Dict[str, Any]:
    """One path block's Deflated Alpha floor, and what sets it.

    The framework estimates the Deflated Alpha floor (alpha*) from the
    cross-sectional dispersion of the *benchmark* alphas, scaled by the
    expected maximum of N draws::

        alpha* = std(benchmark alphas, ddof=1) * sqrt(2 * ln(N))

    with N the number of benchmarks. So the floor tracks the strategy's own
    edge over its benchmark set -- not the size of the parameter search --
    and it does not fall to zero as the sample grows: only the estimation
    noise in the two alphas shrinks, the gap between them survives.

    The block carries the framework's own benchmark alphas, so the floor can
    be reconstructed from the report and checked against the framework's own
    ``expected_max_alpha``. When the reconstruction does not match, the
    framework used its i.i.d.-normal null fallback instead of the
    cross-sectional estimator (the benchmark alphas were not available in
    sufficient number), and the driver says so rather than reporting a
    floor it cannot back.

    A floor the framework could not price at all is reported as unpriceable,
    not as a floor of zero: the driver carries the framework's own status
    and reason, and neither the reconstruction nor the identity check is
    claimed for a draw whose alphas are placeholders (see
    ``_alpha_floor_measured``).
    """
    floor = block.get("expected_max_alpha")
    alphas = [
        float(a)
        for a in (block.get("benchmark_alphas") or [])
        if a is not None and np.isfinite(a)
    ]
    try:
        n = int(block.get("n_benchmarks"))
    except (TypeError, ValueError):
        n = len(alphas)
    std = float(np.std(alphas, ddof=1)) if len(alphas) >= 2 else None
    # The floor is a measurement only where the framework priced the alpha
    # criterion on this draw AND reported a floor. Otherwise the block's
    # alphas are the degenerate output of a failed pricing, and neither the
    # reconstruction nor the identity is claimed for them.
    measured = _alpha_floor_measured(block) and floor is not None
    predicted = None
    if measured and std is not None and n >= 2:
        predicted = std * math.sqrt(2.0 * math.log(n))
    identity_holds = None
    if predicted is not None and floor is not None:
        identity_holds = bool(
            abs(predicted - float(floor)) <= 1e-9 * max(1.0, abs(float(floor)))
        )
    return {
        "strategy_alpha": block.get("strategy_alpha"),
        "benchmark_alphas": alphas,
        "n_benchmarks": n,
        "benchmark_alpha_std": std,
        "alpha_star_from_dispersion": predicted,
        "expected_max_alpha": floor,
        "identity_holds": identity_holds,
        # The framework's own record of whether criterion 5 could be priced
        # on this draw, and why not when it could not.
        "alpha_status": block.get("alpha_status"),
        "alpha_reason": block.get("alpha_reason"),
        "floor_measured": measured,
    }


def _measure_sample(
    data,
    benchmarks,
    paths: Sequence[str] = PATHS,
    train_frac: float = TRAIN_FRAC,
    val_frac: float = VAL_FRAC,
    test_frac: float = TEST_FRAC,
) -> Dict[str, Any]:
    """Measure the resolution on one prepared sample, for every path.

    Returns the framework's own resolution block plus the Deflated Sharpe
    block it was built from (for the deflation benchmark SR*) and the
    observed out-of-sample Sharpe, for comparison.

    The top-level fields are the primary (out-of-sample) path's fields;
    ``paths`` carries every measured path's own block.
    """
    results = _run_validation(data, benchmarks, train_frac=train_frac, val_frac=val_frac, test_frac=test_frac)
    summary = results.get("summary", {})
    test_performance = results.get("test_performance") or {}
    test_returns = test_performance.get("test_returns")

    # The framework's own block: the same builder the walk-forward, CPCV and
    # out-of-sample paths attach to their summaries.
    resolution = _build_test_resolution(summary, test_returns)

    deflated_sharpe = summary.get("deflated_sharpe") or {}
    deflated_alpha = summary.get("deflated_alpha") or {}
    periods = (results.get("validation_results") or {}).get("periods", [])

    train_lengths = [
        len(p.get("train_data", [])) for p in periods if p.get("train_data") is not None
    ]
    trial_sharpes: List[float] = []
    for period in periods:
        trial_sharpes.extend(period.get("trial_sharpes") or [])

    min_detectable_sharpe = resolution.get("min_detectable_sharpe")
    min_detectable_alpha = resolution.get("min_detectable_alpha")
    measured = {
        "walk_forward_periods": len(periods),
        "train_window_bars_first": train_lengths[0] if train_lengths else None,
        "train_window_bars_last": train_lengths[-1] if train_lengths else None,
        "n_test_observations": resolution.get("n_test_observations"),
        "n_parameter_trials": resolution.get("n_parameter_trials"),
        "n_benchmarks": resolution.get("n_benchmarks"),
        "min_detectable_sharpe": min_detectable_sharpe,
        "min_detectable_alpha": min_detectable_alpha,
        "observed_annualized_sharpe": resolution.get("observed_annualized_sharpe"),
        "observed_annualized_alpha": resolution.get("observed_annualized_alpha"),
        # The deflation benchmark: the floor the resolution converges to.
        "expected_max_sharpe": deflated_sharpe.get("expected_max_sharpe"),
        "expected_max_alpha": deflated_alpha.get("expected_max_alpha"),
        "sharpe_beyond_plausible_bound": resolution.get(
            "sharpe_beyond_plausible_bound"
        ),
        "alpha_beyond_plausible_bound": resolution.get(
            "alpha_beyond_plausible_bound"
        ),
        "plausible_max_annualized_sharpe": PLAUSIBLE_MAX_ANNUALIZED_SHARPE,
        "plausible_max_annualized_alpha": PLAUSIBLE_MAX_ANNUALIZED_ALPHA,
        "trial_sharpe_count": len(trial_sharpes),
    }

    # The other analysis paths. Each one is measured on the same sample
    # with its own shipped configuration, and each one reports its own
    # resolution: they do not share the held-out test window the
    # out-of-sample path is governed by.
    requested = set(paths)
    blocks: Dict[str, Dict[str, Any]] = {
        PATH_OUT_OF_SAMPLE: _measure_path(
            PATH_OUT_OF_SAMPLE, summary, test_returns, n_windows=1
        )
    }
    if PATH_WALK_FORWARD in requested:
        wf_results = _run_walk_forward(data, benchmarks)
        wf_summary = wf_results.get("summary", {})
        blocks[PATH_WALK_FORWARD] = _measure_path(
            PATH_WALK_FORWARD,
            wf_summary,
            wf_results.get("oos_returns"),
            n_windows=len(wf_results.get("periods") or []),
        )
    if PATH_CPCV in requested:
        cpcv_results = _run_cpcv(data, benchmarks)
        cpcv_summary = cpcv_results.get("summary", {})
        blocks[PATH_CPCV] = _measure_path(
            PATH_CPCV,
            cpcv_summary,
            cpcv_results.get("oos_returns"),
            n_windows=len(cpcv_results.get("folds") or []),
        )
    measured["paths"] = blocks
    return measured


def measure_synthetic(
    bars: int,
    seed: int,
    inject_effect: bool,
    paths: Sequence[str] = PATHS,
    train_frac: float = TRAIN_FRAC,
    val_frac: float = VAL_FRAC,
    test_frac: float = TEST_FRAC,
) -> Dict[str, Any]:
    """Measure the resolution on a synthetic control fixture of `bars` bars.

    The fixture is the worked example's positive control
    (`generate_positive_control_data.py`): the same construction, regenerated
    at the requested length, with the same seeds.
    """
    with tempfile.TemporaryDirectory(prefix="resolution_vs_sample_size_") as tmpdir:
        fixture_paths = write_control_fixture(
            tmpdir,
            strategy_seed=seed,
            benchmark_seed=seed + (CONTROL_BENCHMARK_SEED - CONTROL_STRATEGY_SEED),
            inject_effect=inject_effect,
            periods=bars,
        )
        data = load_data(str(fixture_paths["strategy"]))
        # The worked example's benchmark set, in the same order as its
        # `BENCHMARK_FILES`: the strategy's own series is the primary
        # benchmark, the alternative benchmark is the second.
        benchmarks = [
            load_data(str(fixture_paths["strategy"])),
            load_data(str(fixture_paths["benchmark"])),
        ]
        measured = _measure_sample(data, benchmarks, paths=paths, train_frac=train_frac, val_frac=val_frac, test_frac=test_frac)
    measured.update(
        {
            "bars": bars,
            "seed": seed,
            "series": "effect" if inject_effect else "no_effect",
            "source": "synthetic control fixture",
            "train_frac": train_frac,
            "val_frac": val_frac,
            "test_frac": test_frac,
        }
    )
    return measured


def measure_real(
    data_path: str,
    bars: int,
    paths: Sequence[str] = PATHS,
) -> Dict[str, Any]:
    """Measure the resolution on the first `bars` bars of a real history.

    The benchmark set is resolved the way the worked example resolves it --
    from the directory of the data file -- so the same multiple-benchmark
    Deflated Alpha path is exercised.
    """
    base = Path(data_path).resolve().parent
    full = load_data(str(data_path))
    if len(full) < bars:
        raise ValueError(
            f"{data_path} has {len(full)} rows, fewer than the {bars} requested"
        )
    data = full.iloc[:bars]
    benchmarks = []
    for name in BENCHMARK_FILES:
        candidate = base / name
        frame = load_data(str(candidate)).iloc[:bars]
        benchmarks.append(frame)
    measured = _measure_sample(data, benchmarks, paths=paths)
    measured.update(
        {
            "bars": bars,
            "seed": None,
            "series": "real_history_prefix",
            "source": str(data_path),
        }
    )
    return measured


def measure_ladder(
    sizes: Sequence[int],
    seeds: Sequence[int] = DEFAULT_SEEDS,
    inject_effect: Optional[bool] = None,
    data_path: Optional[str] = None,
    paths: Sequence[str] = PATHS,
) -> List[Dict[str, Any]]:
    """Measure the resolution at every rung of the ladder.

    With `data_path` the ladder is measured on prefixes of that history;
    otherwise it is measured on the synthetic control fixture, for the
    effect series and the no-effect series (`inject_effect=None` means
    both).
    """
    rows: List[Dict[str, Any]] = []
    if data_path:
        for bars in sizes:
            rows.append(measure_real(data_path, bars, paths=paths))
        return rows

    variants = [True, False] if inject_effect is None else [bool(inject_effect)]
    for bars in sizes:
        for seed in seeds:
            for effect in variants:
                rows.append(measure_synthetic(bars, seed, effect, paths=paths))
    return rows


def measure_test_frac_sweep(
    bars: int,
    seeds: Sequence[int],
    test_fracs: Sequence[float],
    val_frac: float = VAL_FRAC,
    inject_effect: bool = True,
    paths: Sequence[str] = (PATH_OUT_OF_SAMPLE,),
) -> List[Dict[str, Any]]:
    """Measure the out-of-sample path's resolution across held-out fractions.

    At a fixed sample size, sweeps ``test_frac`` with
    ``train_frac = 0.8 - test_frac`` and ``val_frac = 0.2``, so the three
    fractions always sum to 1.0 (the shipped default is 0.6 / 0.2 / 0.2 at
    ``test_frac = 0.2``). Each row is one ``measure_synthetic`` run annotated
    with the split actually used.

    The trade-off measured: a larger held-out window gives the test more
    observations (better resolution) but shortens the training window, which
    raises the deflation floor SR* because the trial Sharpes it is estimated
    from are then estimated on less data. Where the two effects cross is the
    answer to "how much of the data should be held out?".

    One series at a time: the no-effect series is the null calibration and
    the effect series is the positive control, and their numbers answer
    different questions, so the series is named rather than defaulted.
    ``inject_effect=None`` is refused instead of silently measuring the
    no-effect series.
    """
    if inject_effect is None:
        raise ValueError(
            "the sweep measures one series at a time: pass inject_effect=True "
            "(the effect series) or inject_effect=False (the no-effect "
            "series). None would silently measure the no-effect series."
        )
    rows: List[Dict[str, Any]] = []
    for test_frac in test_fracs:
        train_frac = 0.8 - test_frac
        if train_frac <= 0:
            raise ValueError(
                f"test_frac {test_frac} leaves no training data "
                f"(train_frac = {train_frac}); keep test_frac below 0.8"
            )
        for seed in seeds:
            rows.append(
                measure_synthetic(
                    bars,
                    seed,
                    inject_effect,
                    paths=paths,
                    train_frac=train_frac,
                    val_frac=val_frac,
                    test_frac=test_frac,
                )
            )
    return rows


def _path_block(row: Dict[str, Any], path: str) -> Dict[str, Any]:
    """One path's measurement block in one ladder row.

    A row written before the per-path blocks existed carries the primary
    path's fields at the top level; it is read as the primary path.
    """
    blocks = row.get("paths")
    if isinstance(blocks, dict):
        block = blocks.get(path)
        if isinstance(block, dict):
            return block
    if path == PRIMARY_PATH:
        return row
    return {}


def _measured_paths(rows: Sequence[Dict[str, Any]]) -> List[str]:
    """The paths the ladder actually measured, in the canonical order."""
    found = set()
    for row in rows:
        blocks = row.get("paths")
        if isinstance(blocks, dict):
            found.update(k for k, v in blocks.items() if isinstance(v, dict))
    if not found:
        found = {PRIMARY_PATH}
    return [p for p in PATHS if p in found]


def _summarize_path(rows: Sequence[Dict[str, Any]], path: str) -> Dict[str, Any]:
    """Summarise one path's ladder: the crossing of the bound and the floor.

    The crossing is reported per sample size, over the draws measured at that
    size, because the resolution moves with the draw: a size at which *some*
    draws are inside the bound and others are not is a size at which the
    answer depends on the sample, and saying so is more useful than
    reporting the first row that happens to be inside.

    ``first_size_all_within_bound`` is the smallest measured sample size at
    which *every* draw measured at that size had a minimum confirmable
    annualized Sharpe at or below the framework's plausibility bound -- i.e.
    the first size at which criterion 2 could have confirmed a plausible
    effect regardless of the draw. ``first_size_any_within_bound`` is the
    smallest size at which at least one draw was inside the bound.
    ``None`` means no measured rung reached it.

    A draw whose resolution could not be computed at all (too few
    observations for the path to price a significance test) is neither
    inside nor outside the bound, so it does not count towards
    ``first_size_all_within_bound``.

    ``max_expected_max_sharpe`` is the highest deflation benchmark (SR*)
    seen anywhere on the ladder. The floor itself is a per-rung number
    (``per_size[*]["max_expected_max_sharpe"]``): it falls as the sample
    grows, because the trial Sharpes the floor is estimated from are
    estimated on more data, so the rung closest to the asymptote is the
    largest one measured. ``floor_at_largest_size`` is that number, and
    ``floor_beyond_plausible_bound`` says whether the floor was above the
    plausibility bound at *every* measured rung -- which is the "no
    *measured* sample size" answer. The flag is a statement about the
    measured range, not about every sample size: the floor falls as the
    sample grows, so a ladder that stops short of the crossing cannot
    settle the question, and the summary says "no measured sample size"
    and names the largest rung measured rather than claiming more.

    THE ALPHA SIDE IS MIRRORED OFF THE SHARPE SIDE
    The same machinery is applied to criterion 5 (the minimum confirmable
    annualized alpha against the framework's own 10% annualized-alpha
    plausibility bound), and the result is reported in parallel:
    ``per_size_alpha``, ``first_size_all_within_alpha_bound``,
    ``first_size_any_within_alpha_bound``, ``max_expected_max_alpha``,
    ``alpha_floor_at_largest_size`` and the ``alpha_floor_*`` flags. The
    two criteria are reported separately because they cross at different
    sample sizes: the alpha bound is the stricter of the two (a 10%
    annualized alpha is a much smaller effect than a 2.0 annualized
    Sharpe), so criterion 5's resolution stays above it longer. Measured
    on the control fixture, the CPCV path's minimum confirmable alpha is
    still 10-13% at 10,000 bars -- above the bound -- and under it on
    every draw at 25,000, while its minimum confirmable Sharpe is already
    well under 2.0 at 10,000.
    """
    sharpes = []
    floors = []
    per_size: Dict[int, Dict[str, Any]] = {}
    # Draws whose Sharpe floor could NOT be measured: the framework could
    # not price the Deflated Sharpe criterion on them, so the floor they
    # carry is a placeholder, not a measurement.
    sharpe_unmeasured: Dict[int, List[Dict[str, Any]]] = {}
    for row in rows:
        block = _path_block(row, path)
        bars = row.get("bars")
        value = block.get("min_detectable_sharpe")
        bucket = per_size.setdefault(
            bars, {"values": [], "within": 0, "measured": 0, "floors": [], "unmeasured": []}
        )
        bucket["measured"] += 1
        if _sharpe_floor_measured(block):
            floor = block.get("expected_max_sharpe")
            if floor is not None:
                bucket["floors"].append(floor)
                floors.append(floor)
        else:
            sharpe_unmeasured.setdefault(bars, []).append(block)
            bucket["unmeasured"].append(block)
        if value is None:
            continue
        bucket["values"].append(value)
        if value <= PLAUSIBLE_MAX_ANNUALIZED_SHARPE:
            bucket["within"] += 1
        sharpes.append(value)

    finite_sharpes = [s for s in sharpes if s is not None]
    finite_floors = [f for f in floors if f is not None]

    # The alpha side is measured the same way, against the framework's own
    # 10% annualized-alpha plausibility bound. The two criteria are reported
    # separately because they cross at different sample sizes: the alpha
    # bound is the stricter of the two (a 10% annualized alpha is a much
    # smaller effect than a 2.0 annualized Sharpe), so the minimum
    # confirmable alpha stays above it longer. Measured on the control
    # fixture, the CPCV path's minimum confirmable alpha is still 10-13% at
    # 10,000 bars -- above the bound -- and under it on every draw at
    # 25,000, while its minimum confirmable Sharpe is already well under
    # 2.0 at 10,000.
    alphas: List[float] = []
    alpha_floors: List[float] = []
    per_size_alpha: Dict[int, Dict[str, Any]] = {}
    # The driver of the alpha floor: what sets it, per draw. The framework
    # estimates alpha* from the cross-sectional dispersion of the benchmark
    # alphas (see `_alpha_floor_driver`), so each draw's floor is explained
    # by its own dispersion -- and the report can say so.
    alpha_drivers: Dict[int, List[Dict[str, Any]]] = {}
    # The draws whose alpha floor could NOT be measured: the framework could
    # not price the Deflated Alpha criterion on them, so the floor they
    # carry is a placeholder, not a measurement. They are kept apart from
    # the measured floors so that a placeholder zero is never read as a
    # measured floor of zero.
    alpha_unmeasured: Dict[int, List[Dict[str, Any]]] = {}
    for row in rows:
        block = _path_block(row, path)
        bars = row.get("bars")
        value = block.get("min_detectable_alpha")
        bucket = per_size_alpha.setdefault(
            bars,
            {"values": [], "within": 0, "measured": 0, "floors": [], "unmeasured": []},
        )
        bucket["measured"] += 1
        driver = _alpha_floor_driver(block)
        if driver["floor_measured"]:
            floor = block.get("expected_max_alpha")
            bucket["floors"].append(floor)
            alpha_floors.append(floor)
            alpha_drivers.setdefault(bars, []).append(driver)
        else:
            bucket["unmeasured"].append(driver)
            alpha_unmeasured.setdefault(bars, []).append(driver)
        if value is None:
            continue
        bucket["values"].append(value)
        if value <= PLAUSIBLE_MAX_ANNUALIZED_ALPHA:
            bucket["within"] += 1
        alphas.append(value)

    finite_alphas = [a for a in alphas if a is not None]
    finite_alpha_floors = [f for f in alpha_floors if f is not None]

    size_summary = []
    for bars in sorted(per_size):
        bucket = per_size[bars]
        values = bucket["values"]
        rung_floors = bucket["floors"]
        size_summary.append(
            {
                "bars": bars,
                "min_min_detectable_sharpe": min(values) if values else None,
                "max_min_detectable_sharpe": max(values) if values else None,
                # The floor at this rung: the level below which this path's
                # test cannot confirm an effect, whatever the sample size.
                "max_expected_max_sharpe": max(rung_floors) if rung_floors else None,
                "min_expected_max_sharpe": min(rung_floors) if rung_floors else None,
                "draws_measured": bucket["measured"],
                "draws_resolved": len(values),
                "draws_within_bound": bucket["within"],
                "draws_floor_unmeasured": len(bucket.get("unmeasured", [])),
                "floor_unmeasured_reason": next(
                    (
                        b.get("sharpe_reason")
                        for b in bucket.get("unmeasured", [])
                        if b.get("sharpe_reason")
                    ),
                    None,
                ),
                "all_within_bound": bool(values)
                and len(values) == bucket["measured"]
                and all(v <= PLAUSIBLE_MAX_ANNUALIZED_SHARPE for v in values),
                "any_within_bound": any(
                    v <= PLAUSIBLE_MAX_ANNUALIZED_SHARPE for v in values
                ),
            }
        )

    alpha_size_summary = []
    for bars in sorted(per_size_alpha):
        bucket = per_size_alpha[bars]
        values = bucket["values"]
        rung_floors = bucket["floors"]
        rung_drivers = alpha_drivers.get(bars, [])
        rung_unmeasured = alpha_unmeasured.get(bars, [])
        rung_stds = [
            d["benchmark_alpha_std"] for d in rung_drivers
            if d.get("benchmark_alpha_std") is not None
        ]
        alpha_size_summary.append(
            {
                "bars": bars,
                "min_min_detectable_alpha": min(values) if values else None,
                "max_min_detectable_alpha": max(values) if values else None,
                # The deflation floor for alpha (alpha*): the level below
                # which no sample size can let this path confirm a
                # plausible alpha. The framework estimates it as the
                # dispersion of the benchmark alphas scaled by the expected
                # maximum of N draws (N the number of benchmarks), so it
                # tracks the strategy's own alpha gap to its benchmark set
                # rather than the size of the parameter grid.
                #
                # A draw whose floor could not be measured is NOT in this
                # number: the framework could not price the Deflated Alpha
                # criterion there, so the block's floor is a placeholder
                # (on a zero-volatility draw, a zero) rather than a
                # measurement. The count of those draws is reported
                # alongside, so a rung with no floor says why.
                "max_expected_max_alpha": max(rung_floors) if rung_floors else None,
                "min_expected_max_alpha": min(rung_floors) if rung_floors else None,
                # What sets the floor at this rung: the dispersion of the
                # benchmark alphas it is estimated from.
                "min_benchmark_alpha_std": min(rung_stds) if rung_stds else None,
                "max_benchmark_alpha_std": max(rung_stds) if rung_stds else None,
                "draws_measured": bucket["measured"],
                "draws_resolved": len(values),
                # The draws at this rung whose alpha floor could not be
                # measured, and the framework's own reason why.
                "draws_floor_unmeasured": len(rung_unmeasured),
                "floor_unmeasured_reason": next(
                    (
                        d.get("alpha_reason")
                        for d in rung_unmeasured
                        if d.get("alpha_reason")
                    ),
                    None,
                ),
                "draws_within_bound": bucket["within"],
                "all_within_bound": bool(values)
                and len(values) == bucket["measured"]
                and all(v <= PLAUSIBLE_MAX_ANNUALIZED_ALPHA for v in values),
                "any_within_bound": any(
                    v <= PLAUSIBLE_MAX_ANNUALIZED_ALPHA for v in values
                ),
            }
        )

    def _first(predicate):
        for entry in size_summary:
            if predicate(entry):
                return entry["bars"]
        return None

    def _first_alpha(predicate):
        for entry in alpha_size_summary:
            if predicate(entry):
                return entry["bars"]
        return None

    # The floor at the largest rung measured: the closest to the asymptote
    # the resolution converges onto.
    floor_at_largest = (
        size_summary[-1].get("max_expected_max_sharpe") if size_summary else None
    )
    # The floor is above the bound at every rung measured: the floor never
    # comes under the bound on this ladder, so no *measured* sample size
    # would let this path confirm a plausible effect. The flag is about the
    # measured range: the floor falls as the sample grows, so a longer
    # ladder can overturn it (and does, on the control fixture).
    rung_floor_maxima = [
        entry["max_expected_max_sharpe"]
        for entry in size_summary
        if entry.get("max_expected_max_sharpe") is not None
    ]
    floor_beyond_bound = (
        all(f > PLAUSIBLE_MAX_ANNUALIZED_SHARPE for f in rung_floor_maxima)
        if rung_floor_maxima
        else None
    )

    # The alpha crossing, mirrored off the Sharpe crossing. The alpha floor
    # (alpha*) is the deflation benchmark for criterion 5, and the bound is
    # the framework's own 10% annualized alpha.
    #
    # The floor the summary quotes is the floor at the largest rung where
    # the floor could be MEASURED. A rung where the framework could not
    # price the Deflated Alpha criterion carries a placeholder, not a
    # measurement, so it cannot set the floor the summary quotes -- and the
    # flag below is about the rungs whose floor was measured.
    alpha_floor_at_largest = None
    alpha_floor_at_largest_bars = None
    for entry in reversed(alpha_size_summary):
        if entry.get("max_expected_max_alpha") is not None:
            alpha_floor_at_largest = entry["max_expected_max_alpha"]
            alpha_floor_at_largest_bars = entry["bars"]
            break
    alpha_rung_floor_maxima = [
        entry["max_expected_max_alpha"]
        for entry in alpha_size_summary
        if entry.get("max_expected_max_alpha") is not None
    ]
    # The floor was above the bound at every rung whose floor was measured.
    # When no rung's floor could be measured the flag is None, not False:
    # "the floor does not block criterion 5" is not established on a path
    # where criterion 5 was never evaluated.
    alpha_floor_beyond_bound = (
        all(f > PLAUSIBLE_MAX_ANNUALIZED_ALPHA for f in alpha_rung_floor_maxima)
        if alpha_rung_floor_maxima
        else None
    )

    # WHAT SETS THE ALPHA FLOOR
    # The floor is a number without an explanation, and the explanation is
    # not the one a reader would guess: it is the strategy's own edge over
    # its benchmark set, not the size of the parameter search. The driver is
    # reported here so the summary can say why the floor is where it is.
    #
    # It is reported at the largest measured rung, on the worst draw there
    # -- the draw that sets the floor the summary quotes -- and the identity
    # is checked on every measured draw, so a floor the framework did not
    # estimate from the benchmark dispersion (its i.i.d.-normal null
    # fallback) is reported as such instead of being explained away.
    all_alpha_drivers = [d for drivers in alpha_drivers.values() for d in drivers]
    all_alpha_unmeasured = [d for drivers in alpha_unmeasured.values() for d in drivers]
    # Only the draws whose benchmark alphas were reported can be checked; a
    # draw that cannot be checked is not counted as a failure, and the
    # counts are reported so a reader can see how many were checked.
    identity_flags = [
        d["identity_holds"] for d in all_alpha_drivers if d["identity_holds"] is not None
    ]
    worst_driver: Optional[Dict[str, Any]] = None
    if alpha_drivers:
        largest_bars = max(alpha_drivers)
        candidates = alpha_drivers.get(largest_bars, [])
        if candidates:
            worst_driver = max(candidates, key=lambda d: d["expected_max_alpha"])
    driver_stds = [
        d["benchmark_alpha_std"] for d in all_alpha_drivers
        if d.get("benchmark_alpha_std") is not None
    ]
    driver_strategy_alphas = [
        d["strategy_alpha"] for d in all_alpha_drivers
        if d.get("strategy_alpha") is not None
    ]
    alpha_floor_driver = {
        "identity": "alpha* = std(benchmark alphas, ddof=1) * sqrt(2 ln N)",
        "n_benchmarks": (worst_driver or {}).get("n_benchmarks"),
        "identity_holds_on_every_measured_draw": (
            all(identity_flags) if identity_flags else None
        ),
        "draws_measured": len(all_alpha_drivers),
        "draws_checked": len(identity_flags),
        # The draws whose floor could not be measured, and the framework's
        # own reason: the floor they carry is a placeholder, so the driver
        # is not claimed for them.
        "floor_measured": bool(all_alpha_drivers),
        "draws_unmeasured": len(all_alpha_unmeasured),
        "unmeasured_rungs": sorted(alpha_unmeasured),
        "unmeasured_reason": next(
            (
                d.get("alpha_reason")
                for d in all_alpha_unmeasured
                if d.get("alpha_reason")
            ),
            None,
        ),
        "at_largest_measured_size": worst_driver,
        "benchmark_alpha_std_range": {
            "min": min(driver_stds) if driver_stds else None,
            "max": max(driver_stds) if driver_stds else None,
        },
        "strategy_alpha_range": {
            "min": min(driver_strategy_alphas) if driver_strategy_alphas else None,
            "max": max(driver_strategy_alphas) if driver_strategy_alphas else None,
        },
    }

    return {
        "path": path,
        "plausible_max_annualized_sharpe": PLAUSIBLE_MAX_ANNUALIZED_SHARPE,
        "plausible_max_annualized_alpha": PLAUSIBLE_MAX_ANNUALIZED_ALPHA,
        # The largest rung this path was measured at. Every conclusion drawn
        # from the ladder is a statement about the measured range, so the
        # range is reported with it.
        "largest_measured_size": size_summary[-1]["bars"] if size_summary else None,
        "per_size": size_summary,
        "per_size_alpha": alpha_size_summary,
        "first_size_all_within_bound": _first(lambda e: e["all_within_bound"]),
        "first_size_any_within_bound": _first(lambda e: e["any_within_bound"]),
        "first_size_all_within_alpha_bound": _first_alpha(
            lambda e: e["all_within_bound"]
        ),
        "first_size_any_within_alpha_bound": _first_alpha(
            lambda e: e["any_within_bound"]
        ),
        "min_min_detectable_sharpe": min(finite_sharpes) if finite_sharpes else None,
        "max_min_detectable_sharpe": max(finite_sharpes) if finite_sharpes else None,
        "min_min_detectable_alpha": min(finite_alphas) if finite_alphas else None,
        "max_min_detectable_alpha": max(finite_alphas) if finite_alphas else None,
        "max_expected_max_sharpe": max(finite_floors) if finite_floors else None,
        "max_expected_max_alpha": (
            max(finite_alpha_floors) if finite_alpha_floors else None
        ),
        "floor_at_largest_size": floor_at_largest,
        "sharpe_floor_measured": bool(floors),
        "sharpe_floor_unmeasured_rungs": sorted(sharpe_unmeasured),
        "sharpe_floor_unmeasured_reason": next(
            (
                b.get("sharpe_reason")
                for bs in sharpe_unmeasured.values()
                for b in bs
                if b.get("sharpe_reason")
            ),
            None,
        ),
        "alpha_floor_at_largest_size": alpha_floor_at_largest,
        # The rung the alpha floor above was measured at, and whether the
        # floor could be measured at all: where the framework could not
        # price the Deflated Alpha criterion, the floor it carries is a
        # placeholder, not a measurement, and the summary says so instead
        # of quoting a zero.
        "alpha_floor_at_largest_measured_size": alpha_floor_at_largest_bars,
        "alpha_floor_measured": bool(all_alpha_drivers),
        "alpha_floor_unmeasured_rungs": sorted(alpha_unmeasured),
        "alpha_floor_unmeasured_reason": alpha_floor_driver["unmeasured_reason"],
        # What sets the alpha floor (alpha*), and the check that the floor
        # the framework reported is the one the driver reproduces.
        "alpha_floor_driver": alpha_floor_driver,
        # The floor was above the plausibility bound at every measured rung:
        # no sample size would ever let this path confirm a plausible effect.
        "floor_beyond_plausible_bound": floor_beyond_bound,
        "alpha_floor_beyond_plausible_bound": alpha_floor_beyond_bound,
        # The floor is still above the bound at the largest rung measured:
        # more data may bring it under. None (not False) when the floor was
        # never measured: the question was not settled.
        "floor_beyond_plausible_bound_at_largest_size": (
            floor_at_largest > PLAUSIBLE_MAX_ANNUALIZED_SHARPE
            if floor_at_largest is not None
            else None
        ),
        "alpha_floor_beyond_plausible_bound_at_largest_size": (
            alpha_floor_at_largest > PLAUSIBLE_MAX_ANNUALIZED_ALPHA
            if alpha_floor_at_largest is not None
            else None
        ),
        "all_rungs_within_bound": bool(finite_sharpes)
        and all(s <= PLAUSIBLE_MAX_ANNUALIZED_SHARPE for s in finite_sharpes),
        "all_rungs_within_alpha_bound": bool(finite_alphas)
        and all(a <= PLAUSIBLE_MAX_ANNUALIZED_ALPHA for a in finite_alphas),
        "any_rung_within_bound": bool(finite_sharpes)
        and any(s <= PLAUSIBLE_MAX_ANNUALIZED_SHARPE for s in finite_sharpes),
        "any_rung_within_alpha_bound": bool(finite_alphas)
        and any(a <= PLAUSIBLE_MAX_ANNUALIZED_ALPHA for a in finite_alphas),
    }


def _summarize_test_frac_sweep(
    rows: Sequence[Dict[str, Any]],
) -> Tuple[
    List[Dict[str, Any]], Optional[float], Optional[float], Optional[float], Optional[float]
]:
    """Summarise a test-fraction sweep, bucketed by held-out fraction.

    Returns ``(per_fraction_stats, first_all_within_bound, first_any_within_bound,
    first_all_within_alpha_bound, first_any_within_alpha_bound)``.
    Each stat block reports the framework's own resolution numbers for that
    split: the minimum confirmable Sharpe, the deflation floor SR*, the minimum
    confirmable alpha, the deflation floor alpha*, the test observations
    available, and whether the plausibility bounds are crossed.
    """
    buckets: Dict[float, Dict[str, Any]] = {}
    for row in rows:
        test_frac = row.get("test_frac")
        block = _path_block(row, PATH_OUT_OF_SAMPLE)
        bucket = buckets.setdefault(
            test_frac,
            {
                "sharpe_values": [],
                "sharpe_floors": [],
                "alpha_values": [],
                "alpha_floors": [],
                "measured": 0,
                "sharpe_within": 0,
                "alpha_within": 0,
                "n_test_observations": None,
            },
        )
        bucket["measured"] += 1
        sharpe_floor = block.get("expected_max_sharpe")
        if sharpe_floor is not None:
            bucket["sharpe_floors"].append(sharpe_floor)
        sharpe_value = block.get("min_detectable_sharpe")
        if sharpe_value is not None:
            if bucket["n_test_observations"] is None:
                bucket["n_test_observations"] = block.get("n_test_observations")
            bucket["sharpe_values"].append(sharpe_value)
            if sharpe_value <= PLAUSIBLE_MAX_ANNUALIZED_SHARPE:
                bucket["sharpe_within"] += 1
        alpha_floor = block.get("expected_max_alpha")
        if alpha_floor is not None:
            bucket["alpha_floors"].append(alpha_floor)
        alpha_value = block.get("min_detectable_alpha")
        if alpha_value is not None:
            bucket["alpha_values"].append(alpha_value)
            if alpha_value <= PLAUSIBLE_MAX_ANNUALIZED_ALPHA:
                bucket["alpha_within"] += 1

    stats: List[Dict[str, Any]] = []
    for test_frac in sorted(buckets):
        bucket = buckets[test_frac]
        sharpe_values = bucket["sharpe_values"]
        alpha_values = bucket["alpha_values"]
        stats.append(
            {
                "test_frac": test_frac,
                "train_frac": 0.8 - test_frac,
                "val_frac": VAL_FRAC,
                "n_test_observations": bucket["n_test_observations"],
                "min_min_detectable_sharpe": min(sharpe_values) if sharpe_values else None,
                "max_min_detectable_sharpe": max(sharpe_values) if sharpe_values else None,
                "max_expected_max_sharpe": (
                    max(bucket["sharpe_floors"]) if bucket["sharpe_floors"] else None
                ),
                "min_min_detectable_alpha": min(alpha_values) if alpha_values else None,
                "max_min_detectable_alpha": max(alpha_values) if alpha_values else None,
                "max_expected_max_alpha": (
                    max(bucket["alpha_floors"]) if bucket["alpha_floors"] else None
                ),
                "draws_measured": bucket["measured"],
                "draws_resolved": len(sharpe_values),
                "draws_within_bound": bucket["sharpe_within"],
                "draws_within_alpha_bound": bucket["alpha_within"],
                "all_within_bound": bool(sharpe_values)
                and len(sharpe_values) == bucket["measured"]
                and all(v <= PLAUSIBLE_MAX_ANNUALIZED_SHARPE for v in sharpe_values),
                "any_within_bound": any(
                    v <= PLAUSIBLE_MAX_ANNUALIZED_SHARPE for v in sharpe_values
                ),
                "all_within_alpha_bound": bool(alpha_values)
                and len(alpha_values) == bucket["measured"]
                and all(v <= PLAUSIBLE_MAX_ANNUALIZED_ALPHA for v in alpha_values),
                "any_within_alpha_bound": any(
                    v <= PLAUSIBLE_MAX_ANNUALIZED_ALPHA for v in alpha_values
                ),
            }
        )

    first_all = next(
        (entry["test_frac"] for entry in stats if entry["all_within_bound"]),
        None,
    )
    first_any = next(
        (entry["test_frac"] for entry in stats if entry["any_within_bound"]),
        None,
    )
    first_all_alpha = next(
        (entry["test_frac"] for entry in stats if entry["all_within_alpha_bound"]),
        None,
    )
    first_any_alpha = next(
        (entry["test_frac"] for entry in stats if entry["any_within_alpha_bound"]),
        None,
    )
    return stats, first_all, first_any, first_all_alpha, first_any_alpha


def summarize(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarise a ladder: the crossing of the plausibility bound and the floor.

    The top-level keys are the primary (out-of-sample) path's summary, and
    ``by_path`` carries every measured path's summary -- the paths do not
    share a sample, so they do not share a crossing point or a floor.
    """
    summary = _summarize_path(rows, PRIMARY_PATH)
    summary["by_path"] = {
        path: _summarize_path(rows, path) for path in _measured_paths(rows)
    }
    return summary


def _fmt(value, spec="%.4f", missing="n/a"):
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return missing
    return spec % value


def print_table(rows: Sequence[Dict[str, Any]], path: str = PRIMARY_PATH) -> None:
    """Print one path's ladder as a table."""
    header = (
        f"{'bars':>7} {'series':>10} {'seed':>5} {'T':>6} {'N':>6} "
        f"{'min SR':>8} {'SR*':>8} {'obs SR':>8} {'min alpha':>10} "
        f"{'criterion 2':>12}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        block = _path_block(row, path)
        within = block.get("sharpe_beyond_plausible_bound")
        # A path whose resolution could not be computed is neither inside
        # nor outside the bound: it says nothing about criterion 2.
        if block.get("min_detectable_sharpe") is None:
            verdict = "n/a"
        elif within:
            verdict = "beyond bound"
        else:
            verdict = "within bound"
        print(
            f"{row.get('bars', 0):>7} {str(row.get('series')):>10} "
            f"{str(row.get('seed') if row.get('seed') is not None else '-'):>5} "
            f"{str(block.get('n_test_observations') or '-'):>6} "
            f"{str(block.get('n_parameter_trials') or '-'):>6} "
            f"{_fmt(block.get('min_detectable_sharpe')):>8} "
            f"{_fmt(block.get('expected_max_sharpe')):>8} "
            f"{_fmt(block.get('observed_annualized_sharpe')):>8} "
            f"{_fmt(block.get('min_detectable_alpha'), '%.4f'):>10} "
            f"{verdict:>12}"
        )


def _print_floor_status(
    stats: Dict[str, Any],
    label: str,
    criterion: int,
    floor_key: str,
    beyond_key: str,
    beyond_at_largest_key: str,
    measured_key: Optional[str] = None,
    unmeasured_reason_key: Optional[str] = None,
) -> None:
    """Print where one criterion's deflation floor stands.

    The floor is the level below which no sample size can let the path
    confirm an effect, so where the floor sits relative to the plausibility
    bound is the answer to "is there such a sample size at all?". Three
    cases, and all three are reported:

    * the floor was above the bound at every measured rung -- no
      **measured** sample size would let this path confirm a plausible
      effect. The conclusion is scoped to the measured range and the
      largest rung measured is named: the floor falls as the sample grows
      (it is estimated from trial Sharpes or benchmark alphas that are
      themselves estimated on more data), so a ladder that stops short of
      the crossing supports a statement about the ladder, not about every
      sample size. Measured on the control fixture, the walk-forward path's
      alpha floor was above the 10% bound at every rung up to 10,000 bars
      and under it at 25,000 -- the absolute wording was falsified by the
      next rung;
    * the floor is still above the bound at the largest measured rung -- a
      longer sample may bring it under;
    * the floor is at or under the bound at the largest measured rung -- the
      floor no longer blocks this criterion there.

    The third case used to print nothing at all: the two branches that
    existed both required the floor to be *above* the bound, so a floor
    that had come under it was silently dropped from the summary -- the
    one case in which the floor stops being the reason a criterion cannot
    be satisfied.

    A fourth case is reported when the floor was never measured at all:
    the framework could not price the criterion, so the block carries a
    placeholder rather than a floor. That is not "a floor of zero" and it
    is not "a floor that does not block the criterion" -- the criterion was
    never evaluated on that path, so nothing about it is settled here.
    """
    largest = stats.get("largest_measured_size")
    floor = stats.get(floor_key)
    if measured_key is not None and not stats.get(measured_key, True):
        reason = stats.get(unmeasured_reason_key) if unmeasured_reason_key else None
        if reason:
            print(
                f"  the {label} floor was not measured on this path: the "
                f"framework could not price the "
                f"{'alpha' if criterion == 5 else 'Sharpe'} criterion "
                f"({reason}), so the floor it carries is a placeholder rather "
                f"than a measurement, and nothing here settles criterion "
                f"{criterion}"
            )
        else:
            print(
                f"  the {label} floor could not be measured on this path: the "
                f"deflation benchmark is missing from the summary, so nothing "
                f"here settles criterion {criterion}"
            )
        return
    if floor is None:
        print(
            f"  the {label} floor could not be measured on this path: the "
            f"deflation benchmark is missing from the summary"
        )
        return
    if stats.get(beyond_key):
        print(
            f"  the {label} floor was above the plausibility bound at every "
            f"measured sample size (up to {largest} bars): no measured "
            f"sample size would let this path confirm a plausible "
            f"{'effect' if criterion == 2 else 'alpha'}"
        )
    elif stats.get(beyond_at_largest_key):
        print(
            f"  the {label} floor is still above the plausibility bound at "
            f"the largest measured sample size ({largest} bars): a longer "
            f"sample may bring it under"
        )
    else:
        print(
            f"  the {label} floor is at or under the plausibility bound at "
            f"the largest measured sample size ({largest} bars): the floor "
            f"does not block criterion {criterion} at that size"
        )


def _print_alpha_floor_driver(stats: Dict[str, Any]) -> None:
    """Print what sets the Deflated Alpha floor (alpha*).

    The floor is reported as a bare number by the framework, and the number
    is not what a reader would guess: it is the strategy's own edge over its
    benchmark set, not the size of the parameter search. The report says so
    explicitly, with the numbers that reproduce the floor::

        alpha* = std(benchmark alphas, ddof=1) * sqrt(2 ln N)

    so a reader can check the floor against their own run -- the benchmark
    alphas and the benchmark count are in the block the summary carries --
    and knows that a higher floor is a bigger gap, not a worse test.

    The driver is reported for the worst draw at the largest measured rung
    (the draw that sets the floor the summary quotes). If the framework did
    not estimate the floor from the benchmark dispersion (its i.i.d.-normal
    null fallback), the report says that instead of explaining the floor
    with numbers that do not produce it.

    A floor the framework could not price at all is reported as unpriceable:
    the report does not quote the block's placeholder alphas as a dispersion
    and does not claim the identity is reproduced on them.
    """
    driver = stats.get("alpha_floor_driver") or {}
    if not driver.get("floor_measured", True):
        reason = driver.get("unmeasured_reason")
        if reason:
            print(
                "  what sets the alpha floor (alpha*): not measurable on this "
                "ladder -- the framework could not price the alpha criterion "
                f"({reason}), so the alphas the block carries are placeholders "
                "and the floor they imply is not a measurement"
            )
        else:
            print(
                "  what sets the alpha floor (alpha*): not measurable on this "
                "ladder -- the framework did not report a floor, so there is "
                "nothing to explain"
            )
        return
    at_largest = driver.get("at_largest_measured_size") or {}
    if not at_largest or at_largest.get("benchmark_alpha_std") is None:
        print(
            "  what sets the alpha floor (alpha*): not measurable on this "
            "ladder -- the benchmark alphas the floor is estimated from "
            "were not reported by the framework"
        )
        return

    n = at_largest.get("n_benchmarks")
    std = at_largest.get("benchmark_alpha_std")
    predicted = at_largest.get("alpha_star_from_dispersion")
    reported = at_largest.get("expected_max_alpha")
    benchmark_alphas = at_largest.get("benchmark_alphas") or []
    print(
        f"  what sets the alpha floor (alpha*): "
        f"std(benchmark alphas, ddof=1) * sqrt(2 ln N) with N = "
        f"{_fmt(n, '%.0f')}"
    )
    print(
        f"    strategy alpha: {_fmt(at_largest.get('strategy_alpha'), '%.4f')}; "
        f"benchmark alphas: "
        + (
            ", ".join(_fmt(a, '%.4f') for a in benchmark_alphas)
            if benchmark_alphas
            else "n/a"
        )
    )
    print(
        f"    benchmark alpha dispersion (ddof=1): {_fmt(std, '%.4f')}; "
        f"alpha* from that dispersion: {_fmt(predicted, '%.4f')}; "
        f"the framework's own alpha*: {_fmt(reported, '%.4f')}"
    )
    if at_largest.get("identity_holds"):
        print(
            "    the framework's floor is reproduced from the benchmark "
            "alphas, so a higher alpha floor means a bigger gap between the "
            "strategy and its benchmark set -- not a bigger search, and not "
            "a worse test"
        )
    elif at_largest.get("identity_holds") is None:
        print(
            "    the identity could not be checked on this draw: the "
            "framework did not report the benchmark alphas the floor is "
            "estimated from"
        )
    else:
        print(
            "    the framework's floor was NOT reproduced from the benchmark "
            "alphas (it used its i.i.d.-normal null fallback, so the floor "
            "is set by the sample size, not by the benchmark dispersion)"
        )
    # The draws whose floor could not be measured at all: their alphas are
    # placeholders, so the driver is not claimed for them and their floor
    # is not compared against the bound.
    unmeasured = driver.get("draws_unmeasured") or 0
    if unmeasured:
        rungs = driver.get("unmeasured_rungs") or []
        reason = driver.get("unmeasured_reason")
        rungs_text = ", ".join(str(r) for r in rungs) if rungs else "?"
        print(
            f"    {unmeasured} draw(s) measured at {rungs_text} bars could "
            f"not price the alpha criterion"
            + (f" ({reason})" if reason else "")
            + ", so their floor is a placeholder and is not compared against "
            "the bound"
        )


def print_path_summary(summary: Dict[str, Any], path: str) -> None:
    """Print one path's summary: its crossing point and its floor."""
    by_path = summary.get("by_path") or {}
    stats = by_path.get(path, summary)
    print(f"SUMMARY -- {path}: {PATH_LABELS.get(path, path)}")
    print(
        f"  smallest measured annualized Sharpe criterion 2 could confirm: "
        f"{_fmt(stats['min_min_detectable_sharpe'])}"
    )
    print(
        f"  highest deflation benchmark (SR*) seen on the ladder: "
        f"{_fmt(stats['max_expected_max_sharpe'])}"
    )
    print(
        f"  deflation benchmark (SR*) at the largest measured sample size -- "
        f"the floor the resolution converges onto: "
        f"{_fmt(stats.get('floor_at_largest_size'))}"
    )
    print(
        f"  plausibility bound for an annualized Sharpe: "
        f"{_fmt(stats['plausible_max_annualized_sharpe'], '%.2f')}"
    )
    if stats["first_size_all_within_bound"] is not None:
        print(
            f"  first measured sample size at which EVERY draw measured had "
            f"criterion 2 within the plausibility bound: "
            f"{stats['first_size_all_within_bound']} bars"
        )
    else:
        print(
            "  no measured sample size brought criterion 2 within the "
            "plausibility bound on every draw measured at that size"
        )
    if stats["first_size_any_within_bound"] is not None:
        print(
            f"  first measured sample size at which SOME draw had criterion 2 "
            f"within the plausibility bound: "
            f"{stats['first_size_any_within_bound']} bars"
        )
    _print_floor_status(
        stats,
        label="Sharpe (SR*)",
        criterion=2,
        floor_key="floor_at_largest_size",
        beyond_key="floor_beyond_plausible_bound",
        beyond_at_largest_key="floor_beyond_plausible_bound_at_largest_size",
        measured_key="sharpe_floor_measured",
        unmeasured_reason_key="sharpe_floor_unmeasured_reason",
    )
    print(
        f"  smallest measured annualized alpha criterion 5 could confirm: "
        f"{_fmt(stats.get('min_min_detectable_alpha'), '%.4f')}"
    )
    print(
        f"  highest deflation benchmark (alpha*) seen on the ladder: "
        f"{_fmt(stats.get('max_expected_max_alpha'), '%.4f')}"
    )
    # The floor the summary quotes is the floor at the largest rung where it
    # could be MEASURED. When that rung is not the largest rung measured (a
    # larger rung's floor could not be measured), the rung is named.
    alpha_floor_bars = stats.get("alpha_floor_at_largest_measured_size")
    largest = stats.get("largest_measured_size")
    if stats.get("alpha_floor_at_largest_size") is None:
        print(
            f"  deflation benchmark (alpha*) at the largest measured sample size: "
            f"not measured"
        )
    elif alpha_floor_bars is not None and alpha_floor_bars != largest:
        print(
            f"  deflation benchmark (alpha*) at the largest sample size whose "
            f"floor could be measured ({alpha_floor_bars} bars): "
            f"{_fmt(stats.get('alpha_floor_at_largest_size'), '%.4f')}"
        )
    else:
        print(
            f"  deflation benchmark (alpha*) at the largest measured sample size: "
            f"{_fmt(stats.get('alpha_floor_at_largest_size'), '%.4f')}"
        )
    print(
        f"  plausibility bound for an annualized alpha: "
        f"{_fmt(stats['plausible_max_annualized_alpha'], '%.2f')}"
    )
    if stats.get("first_size_all_within_alpha_bound") is not None:
        print(
            f"  first measured sample size at which EVERY draw measured had "
            f"criterion 5 within the alpha plausibility bound: "
            f"{stats['first_size_all_within_alpha_bound']} bars"
        )
    else:
        print(
            "  no measured sample size brought criterion 5 within the "
            "alpha plausibility bound on every draw measured at that size"
        )
    if stats.get("first_size_any_within_alpha_bound") is not None:
        print(
            f"  first measured sample size at which SOME draw had criterion 5 "
            f"within the alpha plausibility bound: "
            f"{stats['first_size_any_within_alpha_bound']} bars"
        )
    _print_floor_status(
        stats,
        label="alpha (alpha*)",
        criterion=5,
        floor_key="alpha_floor_at_largest_size",
        beyond_key="alpha_floor_beyond_plausible_bound",
        beyond_at_largest_key="alpha_floor_beyond_plausible_bound_at_largest_size",
        measured_key="alpha_floor_measured",
        unmeasured_reason_key="alpha_floor_unmeasured_reason",
    )
    _print_alpha_floor_driver(stats)
    # The two criteria cross at different sample sizes. The alpha bound is
    # the stricter of the two -- a 10% annualized alpha is a much smaller
    # effect than a 2.0 annualized Sharpe -- so criterion 5's resolution
    # stays above it longer. State it when the measurement shows it: the
    # first size at which every draw is inside the alpha bound is later than
    # (or equal to) the Sharpe one, or the first size at which some draw is
    # inside the alpha bound is later than the Sharpe one.
    alpha_all = stats.get("first_size_all_within_alpha_bound")
    alpha_any = stats.get("first_size_any_within_alpha_bound")
    sharpe_all = stats.get("first_size_all_within_bound")
    sharpe_any = stats.get("first_size_any_within_bound")
    later = (
        (alpha_all is not None and sharpe_all is not None and alpha_all > sharpe_all)
        or (alpha_any is not None and sharpe_any is not None and alpha_any > sharpe_any)
    )
    if later:
        print(
            "  the alpha bound is crossed later than the Sharpe bound on this "
            "path: criterion 5 needs a larger sample than criterion 2 does, "
            "because a 10% annualized alpha is a much smaller effect than a "
            "2.0 annualized Sharpe"
        )

def print_test_frac_sweep(
    stats: Sequence[Dict[str, Any]],
    first_all: Optional[float],
    first_any: Optional[float],
    first_all_alpha: Optional[float],
    first_any_alpha: Optional[float],
) -> None:
    """Print the held-out-fraction sweep as a table.

    One row per held-out fraction: the framework's own minimum confirmable
    Sharpe and deflation floor SR* for that split, plus the plausibility-bound
    crossing -- and, in parallel, the minimum confirmable alpha and deflation
    floor alpha* for criterion 5.
    """
    header = (
        f"{'test_frac':>9} {'train_frac':>10} {'val_frac':>8} "
        f"{'T':>6} {'min SR':>8} {'SR*':>8} {'min alpha':>10} {'alpha*':>10} "
        f"{'all SR':>9} {'any SR':>9} {'all alpha':>10} {'any alpha':>10}"
    )
    print(header)
    print("-" * len(header))
    for entry in stats:
        print(
            f"{entry['test_frac']:>9.1%} "
            f"{entry['train_frac']:>10.1%} "
            f"{entry['val_frac']:>8.1%} "
            f"{str(entry['n_test_observations'] or '-'):>6} "
            f"{_fmt(entry['min_min_detectable_sharpe']):>8} "
            f"{_fmt(entry['max_expected_max_sharpe']):>8} "
            f"{_fmt(entry['min_min_detectable_alpha'], '%.4f'):>10} "
            f"{_fmt(entry['max_expected_max_alpha'], '%.4f'):>10} "
            f"{str(entry['all_within_bound']):>9} "
            f"{str(entry['any_within_bound']):>9} "
            f"{str(entry['all_within_alpha_bound']):>10} "
            f"{str(entry['any_within_alpha_bound']):>10}"
        )
    print()
    if first_all is not None:
        print(
            "  first held-out fraction at which EVERY draw is within the "
            f"plausibility bound: {first_all:.1%}"
        )
    else:
        print(
            "  no measured held-out fraction brought every draw within the "
            "plausibility bound"
        )
    if first_any is not None:
        print(
            "  first held-out fraction at which SOME draw is within the bound: "
            f"{first_any:.1%}"
        )
    if first_all_alpha is not None:
        print(
            "  first held-out fraction at which EVERY draw is within the "
            f"alpha plausibility bound: {first_all_alpha:.1%}"
        )
    else:
        print(
            "  no measured held-out fraction brought every draw within the "
            "alpha plausibility bound"
        )
    if first_any_alpha is not None:
        print(
            "  first held-out fraction at which SOME draw is within the alpha "
            f"bound: {first_any_alpha:.1%}"
        )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure the Deflated-Sharpe resolution (the smallest annualized "
            "Sharpe the pre-registered criteria could confirm) as a function "
            "of sample size, for each analysis path. " + MEASUREMENT_NOTE
        )
    )
    parser.add_argument(
        "--sizes",
        default=",".join(str(s) for s in DEFAULT_SIZES),
        help=(
            "Comma-separated sample sizes (business-day bars) to measure at. "
            "The default ladder brackets the measured crossing of the "
            "plausibility bounds (criterion 2 by 10,000 bars, criterion 5 "
            "by 50,000) and takes a while -- the largest rungs are minutes "
            "per draw -- so pass a narrower ladder to measure less."
        ),
    )
    parser.add_argument(
        "--seeds",
        default=",".join(str(s) for s in DEFAULT_SEEDS),
        help="Comma-separated seeds for the synthetic fixture.",
    )
    parser.add_argument(
        "--series",
        choices=("both", "effect", "no_effect"),
        default="both",
        help="Which synthetic series to measure (ignored with --data).",
    )
    parser.add_argument(
        "--paths",
        default=",".join(PATHS),
        help=(
            "Comma-separated analysis paths to measure and report: "
            + ", ".join(PATHS)
            + ". The out-of-sample path is always measured (it is where the "
            "pre-registered criteria are evaluated), but only the paths "
            "listed here are reported."
        ),
    )
    parser.add_argument(
        "--test-fracs",
        default=None,
        help=(
            "Comma-separated held-out fractions to sweep at a fixed sample "
            "size (val_frac stays 0.2, train_frac = 0.8 - test_frac, so the "
            "three always sum to 1). When set, the ladder is replaced by this "
            "sweep at the single --size given; the shipped 0.6/0.2/0.2 split "
            "remains the default and is unchanged. The sweep measures the "
            "synthetic control fixture -- it cannot be combined with --data "
            "-- and it names the series it measured (--series both, the "
            "default, measures the null calibration and the positive "
            "control and prints both)."
        ),
    )
    parser.add_argument(
        "--data",
        default=None,
        help=(
            "Measure on a real history instead of the synthetic fixture: "
            "each rung is the first N bars of this file. The benchmark set "
            "is resolved from the file's directory."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the measurement as JSON instead of a table.",
    )
    args = parser.parse_args(argv)

    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    if not sizes:
        parser.error("--sizes must list at least one sample size")

    requested = [p.strip() for p in args.paths.split(",") if p.strip()]
    unknown = [p for p in requested if p not in PATHS]
    if unknown:
        parser.error(
            f"unknown path(s): {', '.join(unknown)}; choose from {', '.join(PATHS)}"
        )
    paths = tuple(dict.fromkeys(requested)) or tuple(PATHS)

    inject = {"both": None, "effect": True, "no_effect": False}[args.series]

    # The banner. With --json it goes to stderr, so the JSON a caller parses
    # is the JSON the tool produced and nothing else.
    banner = io.StringIO()
    banner.write(MEASUREMENT_NOTE + "\n")
    if args.data:
        banner.write(f"Source: {args.data} (each rung is the first N bars)\n")
    else:
        banner.write(
            "Source: synthetic control fixture (a formula, not a market). "
            "The no-effect series is the null calibration; the effect "
            "series is the control's own configuration.\n"
        )
    banner.write("\n")
    if args.json:
        sys.stderr.write(banner.getvalue())
    else:
        sys.stdout.write(banner.getvalue())

    if args.test_fracs:
        test_fracs = [float(t) for t in args.test_fracs.split(",") if t.strip()]
        bad = [t for t in test_fracs if t <= 0.0 or t >= 0.8]
        if bad:
            parser.error(
                "test_frac must be in (0, 0.8) so train_frac = 0.8 - test_frac "
                f"stays positive: {bad}"
            )
        if len(sizes) != 1:
            parser.error("--test-fracs requires exactly one --size (fixed sample size)")
        if args.data:
            parser.error(
                "--test-fracs sweeps the synthetic control fixture and cannot "
                "be combined with --data: the sweep would report the "
                "fixture's numbers under the real history's name. Measure a "
                "real history with --sizes (the ladder) instead."
            )
        size = sizes[0]

        # The sweep measures the series the flag asks for, and names it.
        # "both" measures the null calibration and the positive control and
        # prints both: their numbers answer different questions, and a
        # table that does not say which one it is cannot be read.
        series_to_measure = (
            [("no_effect", False), ("effect", True)]
            if inject is None
            else [("effect" if inject else "no_effect", inject)]
        )
        sweeps: Dict[str, Dict[str, Any]] = {}
        for label, inject_effect in series_to_measure:
            rows = measure_test_frac_sweep(
                size,
                seeds=seeds,
                test_fracs=test_fracs,
                inject_effect=inject_effect,
            )
            stats, first_all, first_any, first_all_alpha, first_any_alpha = (
                _summarize_test_frac_sweep(rows)
            )
            sweeps[label] = {
                "rows": rows,
                "sweep": {
                    "series": label,
                    "stats": stats,
                    "first_all_within_bound": first_all,
                    "first_any_within_bound": first_any,
                    "first_all_within_alpha_bound": first_all_alpha,
                    "first_any_within_alpha_bound": first_any_alpha,
                },
            }
            if args.json:
                continue
            print(
                f"PATH: {PATH_OUT_OF_SAMPLE} -- held-out fraction sweep at "
                f"{size} bars (val_frac = {VAL_FRAC:.1%}, train_frac = 0.8 - "
                f"test_frac) -- series: {label}"
            )
            print_test_frac_sweep(
                stats, first_all, first_any, first_all_alpha, first_any_alpha
            )
            print()

        if args.json:
            if len(sweeps) == 1:
                label, payload = next(iter(sweeps.items()))
                print(json.dumps({"series": label, **payload}, indent=2, default=str))
            else:
                print(json.dumps({"sweeps": sweeps}, indent=2, default=str))
        return 0

    rows = measure_ladder(
        sizes, seeds=seeds, inject_effect=inject, data_path=args.data, paths=paths
    )
    summary = summarize(rows)

    if args.json:
        print(json.dumps({"rows": rows, "summary": summary}, indent=2, default=str))
        return 0

    # The out-of-sample path is always measured (the pre-registered criteria
    # are evaluated on its held-out test window); the paths that are
    # reported are the ones that were asked for.
    reported = [p for p in PATHS if p in paths]
    for path in reported:
        print(f"PATH: {path} -- {PATH_LABELS.get(path, path)}")
        print_table(rows, path)
        print()

    print("SUMMARY")
    for path in reported:
        print_path_summary(summary, path)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
