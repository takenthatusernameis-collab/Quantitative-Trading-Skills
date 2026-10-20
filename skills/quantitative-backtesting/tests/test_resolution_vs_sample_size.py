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
    verdict.

The data is the synthetic positive-control fixture (a formula, not a
market): the numbers are properties of that formula and of the decision
machinery, never evidence about a security.

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

from falsifiable_hypothesis_example import run_hypothesis_test  # noqa: E402
from generate_positive_control_data import write_control_fixture  # noqa: E402
from measure_resolution_vs_sample_size import (  # noqa: E402
    measure_synthetic,
    summarize,
)
from walk_forward import (  # noqa: E402
    PLAUSIBLE_MAX_ANNUALIZED_ALPHA,
    PLAUSIBLE_MAX_ANNUALIZED_SHARPE,
)

# The rungs the tests measure at. They bracket the crossing of the
# plausibility bound: at 2,500 bars criterion 2 is still out of reach on
# every draw measured, at 10,000 bars it is inside the bound on every draw
# measured.
SMALL_SAMPLE_BARS = 2500
LARGE_SAMPLE_BARS = 10000
SEEDS = (7, 1, 2024)

# Each measurement runs a full walk-forward validation, so the results are
# computed once and shared by the tests that read them.
_MEASUREMENTS = {}


def _measured(bars, seed, inject_effect):
    key = (bars, seed, bool(inject_effect))
    if key not in _MEASUREMENTS:
        _MEASUREMENTS[key] = measure_synthetic(bars, seed, inject_effect)
    return _MEASUREMENTS[key]


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
]


if __name__ == "__main__":
    sys.exit(main())
