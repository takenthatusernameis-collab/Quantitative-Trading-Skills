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
    configuration) and ``walk_forward._build_test_resolution`` (the shipped
    resolution block) and reports what they return. It re-derives nothing,
    re-tunes nothing, and changes no threshold, no plausibility bound, no
    criterion and no verdict.

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
    plausibility bound.

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

Usage
    python3 skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py
    python3 skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py \
        --sizes 1000,2500,5000,10000 --json
    python3 skills/quantitative-backtesting/scripts/measure_resolution_vs_sample_size.py \
        --data path/to/history.csv --sizes 2500,5000,10000,25000
"""

import argparse
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

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
    out_of_sample_validation,
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
INITIAL_CAPITAL = 100000
SELECTION_CRITERION = "best_avg_sharpe"

# The ladder of sample sizes (business-day bars) the resolution is measured
# at. The default ladder brackets the crossing of the plausibility bound
# measured on the control's construction: criterion 2 is still out of reach
# at 2,500 bars and inside it by 10,000.
DEFAULT_SIZES: Sequence[int] = (500, 1000, 2500, 5000, 10000)

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


def _run_validation(data, benchmarks) -> Dict[str, Any]:
    """Run the shipped out-of-sample validation on one prepared sample.

    The framework's own path, with the worked example's configuration. The
    routine console output is captured so the measurement can print its own
    table; anything that is not a routine point-in-time confirmation is
    passed through, so a warning is never swallowed.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        results = out_of_sample_validation(
            data=data,
            strategy_factory=_STRATEGY_FACTORY,
            param_grid=PARAM_GRID,
            train_frac=TRAIN_FRAC,
            val_frac=VAL_FRAC,
            test_frac=TEST_FRAC,
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
    for line in buffer.getvalue().splitlines():
        if not line.startswith("Point-in-time validation passed"):
            print(f"  [framework] {line}")
    return results


def _measure_sample(data, benchmarks) -> Dict[str, Any]:
    """Measure the resolution on one prepared sample.

    Returns the framework's own resolution block plus the Deflated Sharpe
    block it was built from (for the deflation benchmark SR*) and the
    observed out-of-sample Sharpe, for comparison.
    """
    results = _run_validation(data, benchmarks)
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
    return {
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


def measure_synthetic(bars: int, seed: int, inject_effect: bool) -> Dict[str, Any]:
    """Measure the resolution on a synthetic control fixture of `bars` bars.

    The fixture is the worked example's positive control
    (`generate_positive_control_data.py`): the same construction, regenerated
    at the requested length, with the same seeds.
    """
    with tempfile.TemporaryDirectory(prefix="resolution_vs_sample_size_") as tmpdir:
        paths = write_control_fixture(
            tmpdir,
            strategy_seed=seed,
            benchmark_seed=seed + (CONTROL_BENCHMARK_SEED - CONTROL_STRATEGY_SEED),
            inject_effect=inject_effect,
            periods=bars,
        )
        data = load_data(str(paths["strategy"]))
        # The worked example's benchmark set, in the same order as its
        # `BENCHMARK_FILES`: the strategy's own series is the primary
        # benchmark, the alternative benchmark is the second.
        benchmarks = [
            load_data(str(paths["strategy"])),
            load_data(str(paths["benchmark"])),
        ]
        measured = _measure_sample(data, benchmarks)
    measured.update(
        {
            "bars": bars,
            "seed": seed,
            "series": "effect" if inject_effect else "no_effect",
            "source": "synthetic control fixture",
        }
    )
    return measured


def measure_real(data_path: str, bars: int) -> Dict[str, Any]:
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
    measured = _measure_sample(data, benchmarks)
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
            rows.append(measure_real(data_path, bars))
        return rows

    variants = [True, False] if inject_effect is None else [bool(inject_effect)]
    for bars in sizes:
        for seed in seeds:
            for effect in variants:
                rows.append(measure_synthetic(bars, seed, effect))
    return rows


def summarize(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarise a ladder: the crossing of the plausibility bound and the floor.

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

    ``max_expected_max_sharpe`` is the highest deflation benchmark (SR*) seen
    on the ladder: the floor the resolution converges to, and therefore the
    level below which no sample size can ever let criterion 2 confirm an
    effect.
    """
    sharpes = [r.get("min_detectable_sharpe") for r in rows]
    floors = [r.get("expected_max_sharpe") for r in rows]
    finite_sharpes = [s for s in sharpes if s is not None]
    finite_floors = [f for f in floors if f is not None]

    per_size: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        bars = row["bars"]
        value = row.get("min_detectable_sharpe")
        bucket = per_size.setdefault(
            bars, {"values": [], "within": 0, "measured": 0}
        )
        bucket["measured"] += 1
        if value is None:
            continue
        bucket["values"].append(value)
        if value <= PLAUSIBLE_MAX_ANNUALIZED_SHARPE:
            bucket["within"] += 1

    size_summary = []
    for bars in sorted(per_size):
        bucket = per_size[bars]
        values = bucket["values"]
        size_summary.append(
            {
                "bars": bars,
                "min_min_detectable_sharpe": min(values) if values else None,
                "max_min_detectable_sharpe": max(values) if values else None,
                "draws_measured": bucket["measured"],
                "draws_within_bound": bucket["within"],
                "all_within_bound": bool(values)
                and all(v <= PLAUSIBLE_MAX_ANNUALIZED_SHARPE for v in values),
                "any_within_bound": any(
                    v <= PLAUSIBLE_MAX_ANNUALIZED_SHARPE for v in values
                ),
            }
        )

    def _first(predicate):
        for entry in size_summary:
            if predicate(entry):
                return entry["bars"]
        return None

    return {
        "plausible_max_annualized_sharpe": PLAUSIBLE_MAX_ANNUALIZED_SHARPE,
        "plausible_max_annualized_alpha": PLAUSIBLE_MAX_ANNUALIZED_ALPHA,
        "per_size": size_summary,
        "first_size_all_within_bound": _first(lambda e: e["all_within_bound"]),
        "first_size_any_within_bound": _first(lambda e: e["any_within_bound"]),
        "min_min_detectable_sharpe": min(finite_sharpes) if finite_sharpes else None,
        "max_min_detectable_sharpe": max(finite_sharpes) if finite_sharpes else None,
        "max_expected_max_sharpe": max(finite_floors) if finite_floors else None,
        "all_rungs_within_bound": bool(finite_sharpes)
        and all(s <= PLAUSIBLE_MAX_ANNUALIZED_SHARPE for s in finite_sharpes),
        "any_rung_within_bound": bool(finite_sharpes)
        and any(s <= PLAUSIBLE_MAX_ANNUALIZED_SHARPE for s in finite_sharpes),
    }


def _fmt(value, spec="%.4f", missing="n/a"):
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return missing
    return spec % value


def print_table(rows: Sequence[Dict[str, Any]]) -> None:
    """Print the ladder as a table."""
    header = (
        f"{'bars':>7} {'series':>10} {'seed':>5} {'T':>6} {'N':>6} "
        f"{'min SR':>8} {'SR*':>8} {'obs SR':>8} {'min alpha':>10} "
        f"{'criterion 2':>12}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        within = row.get("sharpe_beyond_plausible_bound")
        verdict = "beyond bound" if within else "within bound"
        if within is None:
            verdict = "n/a"
        print(
            f"{row.get('bars', 0):>7} {str(row.get('series')):>10} "
            f"{str(row.get('seed') if row.get('seed') is not None else '-'):>5} "
            f"{str(row.get('n_test_observations') or '-'):>6} "
            f"{str(row.get('n_parameter_trials') or '-'):>6} "
            f"{_fmt(row.get('min_detectable_sharpe')):>8} "
            f"{_fmt(row.get('expected_max_sharpe')):>8} "
            f"{_fmt(row.get('observed_annualized_sharpe')):>8} "
            f"{_fmt(row.get('min_detectable_alpha'), '%.4f'):>10} "
            f"{verdict:>12}"
        )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure the Deflated-Sharpe resolution (the smallest annualized "
            "Sharpe the pre-registered criteria could confirm) as a function "
            "of sample size. " + MEASUREMENT_NOTE
        )
    )
    parser.add_argument(
        "--sizes",
        default=",".join(str(s) for s in DEFAULT_SIZES),
        help="Comma-separated sample sizes (business-day bars) to measure at.",
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

    inject = {"both": None, "effect": True, "no_effect": False}[args.series]

    print(MEASUREMENT_NOTE)
    if args.data:
        print(f"Source: {args.data} (each rung is the first N bars)")
    else:
        print(
            "Source: synthetic control fixture (a formula, not a market). "
            "The no-effect series is the null calibration; the effect "
            "series is the control's own configuration."
        )
    print()

    rows = measure_ladder(sizes, seeds=seeds, inject_effect=inject, data_path=args.data)
    summary = summarize(rows)

    if args.json:
        print(json.dumps({"rows": rows, "summary": summary}, indent=2, default=str))
        return 0

    print_table(rows)
    print()
    print("SUMMARY")
    print(
        f"  smallest measured annualized Sharpe criterion 2 could confirm: "
        f"{_fmt(summary['min_min_detectable_sharpe'])}"
    )
    print(
        f"  highest deflation benchmark (SR*, the floor the resolution "
        f"converges to): {_fmt(summary['max_expected_max_sharpe'])}"
    )
    print(
        f"  plausibility bound for an annualized Sharpe: "
        f"{_fmt(summary['plausible_max_annualized_sharpe'], '%.2f')}"
    )
    if summary["first_size_all_within_bound"] is not None:
        print(
            f"  first measured sample size at which EVERY draw measured had "
            f"criterion 2 within the plausibility bound: "
            f"{summary['first_size_all_within_bound']} bars"
        )
    else:
        print(
            "  no measured sample size brought criterion 2 within the "
            "plausibility bound on every draw measured at that size"
        )
    if summary["first_size_any_within_bound"] is not None:
        print(
            f"  first measured sample size at which SOME draw had criterion 2 "
            f"within the plausibility bound: "
            f"{summary['first_size_any_within_bound']} bars"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
