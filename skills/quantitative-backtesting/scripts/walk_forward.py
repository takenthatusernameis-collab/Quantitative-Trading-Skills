#!/usr/bin/env python3
"""
Walk-forward analysis and parameter optimization.

Splits historical data into rolling training and testing windows to validate
strategy robustness across market regimes. Monte Carlo simulation lives in
the standalone `monte_carlo.py` module and is re-exported here for backward
compatibility.
"""

import argparse
import json
import math
import sys
import numpy as np
import pandas as pd
from pathlib import Path
from statistics import NormalDist
from typing import Dict, Any, List, Callable, Optional, Union
from itertools import product

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy_builder import build_strategy
from data_loader import (
    load_data,
    validate_data,
    validate_point_in_time,
    load_multi_symbol,
    detect_survivorship_bias,
    _compute_benchmark_total_return,
    adjust_for_splits,
)
from performance import calculate_metrics, generate_report, _benchmark_stats
from utils import (
    _annualization_factor,
    _capacity_trend_from_series,
    aggregate_book_diagnostics,
    book_capacity_estimate,
    book_cost_components,
    book_market_impact_cost,
    book_return_from_held,
    build_market_model,
    compute_book_diagnostic,
    execution_warmup_metadata,
    format_impact_dilution_lines,
    held_book_weights,
    market_impact_cost,
    resolve_impact_aggregation,
    resolve_panel_pricing,
    strategy_target_weights,
    DEFAULT_IMPACT_AGGREGATION,
    EXECUTION_WARMUP_BARS,
    WARMUP_CONVENTION_WALK_FORWARD,
    _print_sweep_resolution_note,
    _sweep_resolution_fields,
    _sweep_sharpe_below_resolution,
)
from reporting import generate_tear_sheet
from monte_carlo import monte_carlo_simulation


# The outcome of ONE parameter combination inside ONE validation window.
#
# The grid search does not simply rank the combinations: it skips a
# combination that takes no position in the window, and it cannot rank one
# whose training return series is constant (the in-sample Sharpe it ranks
# on is undefined). A window in which nothing could be selected therefore
# has a *reason*, and the reason is not always the same one: a window can
# be flat (no combination trades in it) while another window trades in
# every combination and is still unusable because the training split
# produced a constant return series.
#
# The tally of these outcomes is measured inside the search itself (see
# `selection_outcomes` on the period / fold record) and is what the
# partial-selection diagnosis reports, so the diagnosis states a measured
# cause instead of an inferred one.
_COMBO_ELIGIBLE = "eligible"
_COMBO_FLAT = "flat"
_COMBO_DEGENERATE_TRAINING = "degenerate_training"
_COMBO_FAILED = "failed"

# The cause each outcome maps to in the selection diagnosis. The first two
# are the vocabulary the "no parameter could be selected" diagnosis already
# uses; the last two are the causes that diagnosis could not tell apart.
_COMBO_OUTCOME_CAUSES = {
    _COMBO_FLAT: "no_position_in_validation_window",
    _COMBO_DEGENERATE_TRAINING: "no_estimable_training_sharpe",
    _COMBO_FAILED: "all_combinations_failed",
}

# What each cause means, in the words the diagnosis uses.
_PARTIAL_CAUSE_TEXT = {
    "no_position_in_validation_window": (
        "no parameter combination took a position in the window"
    ),
    "no_estimable_training_sharpe": (
        "every combination took a position, but the training split produced "
        "a constant return series, so the in-sample Sharpe the selection "
        "ranks on is not estimable"
    ),
    "all_combinations_failed": (
        "every parameter combination failed to build or to be evaluated"
    ),
}


def _resolve_latency_fill_rate(args) -> tuple[int, float]:
    """Resolve `--latency` / `--fill-rate` from CLI args with fail-fast validation.

    Mirrors the validation performed inside `_calculate_strategy_returns` /
    `walk_forward_analysis` / `cpcv_analysis` / `out_of_sample_validation` so
    an invalid CLI value is rejected at the boundary instead of being swallowed
    by the per-combo try/except inside the sweep helpers.

    Returns:
        Tuple of (latency, fill_rate). `latency` is clamped to >= 0; `fill_rate`
        is normalised to 1.0 when None and validated to be in (0, 1].
    """
    latency = getattr(args, "latency", 0)
    if latency is None:
        latency = 0
    if latency < 0:
        latency = 0
    fill_rate = getattr(args, "fill_rate", 1.0)
    if fill_rate is None:
        fill_rate = 1.0
    if fill_rate <= 0 or fill_rate > 1:
        raise ValueError(
            f"--fill-rate must be in (0, 1], got {fill_rate}"
        )
    return int(latency), float(fill_rate)


def _resolve_min_position_fraction(args) -> Optional[float]:
    """Resolve `--min-position-fraction` from CLI args with fail-fast validation.

    The flag is opt-in: when None the run is unchanged. When set it must be a
    fraction in (0, 1]; a run whose verdict rests on windows the strategy
    traded for a smaller fraction of their executable bars is rejected.

    Returns:
        The validated fraction, or None when the flag was not set.
    """
    value = getattr(args, "min_position_fraction", None)
    if value is None:
        return None
    value = float(value)
    if value <= 0 or value > 1:
        raise ValueError(
            f"--min-position-fraction must be in (0, 1], got {value}"
        )
    return value


def _resolution_cells(row: Dict[str, Any]) -> List[str]:
    """The minSR and note console cells for one sweep row.

    Reuses the shared resolution semantics (`_sweep_resolution_fields`) so the
    latency / fill-rate sweep tables print the same threshold beside the swept
    Sharpe as the cost sweep tables.
    """
    minSR_txt, note = _sweep_resolution_fields(row)
    return [minSR_txt, note]


def _run_latency_fill_rate_sweep(
    args,
    runner,
    latency_values,
    fill_rate_values,
    latency_artifact,
    fill_rate_artifact,
    latency_header,
    fill_rate_header,
    row_cells,
):
    """Run latency and/or fill-rate sweeps for one analysis path.

    Mirrors the existing per-path cost-sweep blocks (impact / borrow / funding /
    commission / slippage) but factors the latency / fill-rate sweep out so the
    five CLI paths (walk-forward, optimize, monte-carlo, cpcv, out-of-sample)
    share one implementation instead of each carrying a ~35-line copy.

    Args:
        args: CLI args namespace (uses ``args.output``).
        runner: callable(value, key) -> per-value metrics dict, where ``key`` is
            ``"latency"`` or ``"fill_rate"``. Must thread the value down to the
            underlying analysis function and record it under the same key.
        latency_values: latencies to sweep. A single-element list (the default)
            is skipped, preserving the original single-run path.
        fill_rate_values: fill rates to sweep. Single-element -> skipped.
        latency_artifact / fill_rate_artifact: JSON filenames written into
            ``args.output``.
        latency_header / fill_rate_header: column headers printed above each
            sweep table.
        row_cells: callable(metrics_dict, value_key) -> list of formatted cell
            strings matching the corresponding header order.

    Returns:
        True if a sweep was run (the caller should ``return 0``), else False.
    """
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    if len(latency_values) > 1:
        sweep_rows = [runner(v, "latency") for v in latency_values]
        sweep_path = output_dir / latency_artifact
        with open(sweep_path, "w") as f:
            json.dump(
                {"latencies": latency_values, "results": sweep_rows},
                f, indent=2, default=str,
            )
        print(f"\nLatency sweep ({len(latency_values)} latencies) saved to: {sweep_path}")
        latency_header_with_resolution = list(latency_header) + ["minSR", "note"]
        print(" | ".join(latency_header_with_resolution))
        print("-" * len(" | ".join(latency_header_with_resolution)))
        for row in sweep_rows:
            print(" | ".join(row_cells(row, "latency") + _resolution_cells(row)))
        _print_sweep_resolution_note(sweep_rows)
        return True

    if len(fill_rate_values) > 1:
        sweep_rows = [runner(v, "fill_rate") for v in fill_rate_values]
        sweep_path = output_dir / fill_rate_artifact
        with open(sweep_path, "w") as f:
            json.dump(
                {"fill_rates": fill_rate_values, "results": sweep_rows},
                f, indent=2, default=str,
            )
        print(f"\nFill-rate sweep ({len(fill_rate_values)} fill rates) saved to: {sweep_path}")
        fill_rate_header_with_resolution = list(fill_rate_header) + ["minSR", "note"]
        print(" | ".join(fill_rate_header_with_resolution))
        print("-" * len(" | ".join(fill_rate_header_with_resolution)))
        for row in sweep_rows:
            print(" | ".join(row_cells(row, "fill_rate") + _resolution_cells(row)))
        _print_sweep_resolution_note(sweep_rows)
        return True

    return False


def _split_train_val_test(
    data: Union[pd.DataFrame, dict],
    train_frac: float = 0.6,
    val_frac: float = 0.2,
    test_frac: float = 0.2,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split data chronologically into train/validation/test sets.

    Args:
        data: DataFrame with OHLCV data indexed by date (or dict panel)
        train_frac: Fraction of data for training (default 0.6)
        val_frac: Fraction of data for validation (default 0.2)
        test_frac: Fraction of data for testing (default 0.2)

    Returns:
        Tuple of (train_data, val_data, test_data) DataFrames

    Raises:
        ValueError: If fractions don't sum to ~1.0 or data is empty
    """
    if isinstance(data, dict):
        data = _dict_to_multiindex(data)

    if not isinstance(data.index, pd.DatetimeIndex):
        try:
            data.index = pd.DatetimeIndex(data.index)
        except Exception:
            pass
    data = data.sort_index()

    n = len(data)
    if n == 0:
        raise ValueError("Data is empty")

    total_frac = train_frac + val_frac + test_frac
    if abs(total_frac - 1.0) > 1e-9:
        raise ValueError(f"Fractions must sum to 1.0, got {total_frac}")

    train_end = int(n * train_frac)
    val_end = train_end + int(n * val_frac)

    # Ensure each split has at least some data
    if train_end == 0 or val_end == train_end or val_end >= n:
        raise ValueError("Data too small for requested split fractions")

    train_data = data.iloc[:train_end]
    val_data = data.iloc[train_end:val_end]
    test_data = data.iloc[val_end:]

    # Enforce strict chronological separation between the three splits.
    # A leak (a validation or test bar appearing in the training set, or
    # a test bar appearing in the validation set) would silently invalidate
    # the "held-out test set has never been used in any selection step"
    # guarantee, so the check is an executable invariant rather than a
    # documentation note. The check is also exposed as a standalone
    # helper (`_verify_split_separation`) so it can be reused and tested
    # independently of the full out-of-sample pipeline.
    _verify_split_separation(train_data, val_data, test_data)

    return train_data, val_data, test_data


def _verify_split_separation(
    train_data: pd.DataFrame,
    val_data: pd.DataFrame,
    test_data: pd.DataFrame,
    strict: bool = True,
) -> Dict[str, Any]:
    """Verify that train/validation/test splits are pairwise disjoint and
    chronologically ordered.

    This encodes the critical invariant that the held-out test set has
    never been used in any parameter selection or confirmation step.
    Without this check, a slicing bug (e.g. an inclusive ``<=`` boundary
    or an overlapping window) would silently leak future information
    into the training/selection phase, producing an in-sample-optimistic
    result that is indistinguishable from a genuine out-of-sample one.

    Args:
        train_data: Training split (earliest).
        val_data: Validation split (middle).
        test_data: Test split (latest, held out).
        strict: If True, raise ValueError on any violation. If False,
            return the check result without raising (useful for diagnostics).

    Returns:
        Dict with keys:
            - 'disjoint': bool, True when all three index sets are pairwise disjoint
            - 'chronological': bool, True when train_end < val_start and val_end < test_start
            - 'train_val_overlap': int, number of timestamps shared by train and val
            - 'val_test_overlap': int, number of timestamps shared by val and test
            - 'train_test_overlap': int, number of timestamps shared by train and test
            - 'train_end': last train timestamp (or None)
            - 'val_start': first validation timestamp (or None)
            - 'val_end': last validation timestamp (or None)
            - 'test_start': first test timestamp (or None)
            - 'train_size'/'val_size'/'test_size': bar counts

    Raises:
        ValueError: When strict=True and any overlap or chronological
            violation is detected.
    """
    result: Dict[str, Any] = {
        "disjoint": True,
        "chronological": True,
        "train_val_overlap": 0,
        "val_test_overlap": 0,
        "train_test_overlap": 0,
        "train_end": None,
        "val_start": None,
        "val_end": None,
        "test_start": None,
        "train_size": int(len(train_data)),
        "val_size": int(len(val_data)),
        "test_size": int(len(test_data)),
    }

    # Empty splits are not a separation *violation* per se (they are a
    # data-availability problem caught by the caller), but they make the
    # overlap arithmetic trivial and must not be treated as "disjoint".
    if len(train_data) == 0 or len(val_data) == 0 or len(test_data) == 0:
        result["disjoint"] = False
        result["chronological"] = False
        if strict:
            raise ValueError(
                "Split contains an empty segment: "
                f"train={len(train_data)}, val={len(val_data)}, test={len(test_data)}"
            )
        return result

    train_idx = set(train_data.index)
    val_idx = set(val_data.index)
    test_idx = set(test_data.index)

    tv_overlap = len(train_idx & val_idx)
    vt_overlap = len(val_idx & test_idx)
    tt_overlap = len(train_idx & test_idx)

    result["train_val_overlap"] = tv_overlap
    result["val_test_overlap"] = vt_overlap
    result["train_test_overlap"] = tt_overlap
    result["disjoint"] = (tv_overlap == 0 and vt_overlap == 0 and tt_overlap == 0)

    train_end_ts = train_data.index[-1]
    val_start_ts = val_data.index[0]
    val_end_ts = val_data.index[-1]
    test_start_ts = test_data.index[0]

    result["train_end"] = str(train_end_ts)
    result["val_start"] = str(val_start_ts)
    result["val_end"] = str(val_end_ts)
    result["test_start"] = str(test_start_ts)

    # Chronological ordering: the last training bar must precede the first
    # validation bar, and the last validation bar must precede the first
    # test bar. Using ``<=`` (rather than ``<``) would allow adjacent
    # splits to share a boundary timestamp, which is a leak.
    chronological = (train_end_ts < val_start_ts) and (val_end_ts < test_start_ts)
    result["chronological"] = bool(chronological)

    if strict and (not result["disjoint"] or not result["chronological"]):
        reasons = []
        if tv_overlap:
            reasons.append(f"train/validation share {tv_overlap} timestamp(s)")
        if vt_overlap:
            reasons.append(f"validation/test share {vt_overlap} timestamp(s)")
        if tt_overlap:
            reasons.append(f"train/test share {tt_overlap} timestamp(s)")
        if not chronological:
            reasons.append(
                f"chronological order violated: train_end={train_end_ts}, "
                f"val_start={val_start_ts}, val_end={val_end_ts}, "
                f"test_start={test_start_ts}"
            )
        raise ValueError(
            "Train/validation/test split is not strictly separated: "
            + "; ".join(reasons)
        )

    return result


def _dict_to_multiindex(data_dict: dict) -> pd.DataFrame:
    """Convert dict panel data (symbol -> OHLCV DataFrame) to a
    MultiIndex (field, symbol) DataFrame aligned on the common date index.

    Strategies and return calculators produce identical results for the
    dict and MultiIndex formats, so walk-forward/CPCV code paths can
    operate on a single DataFrame representation.
    """
    common_index = None
    columns = None
    for df in data_dict.values():
        if common_index is None:
            common_index = df.index
            columns = set(df.columns)
        else:
            common_index = common_index.intersection(df.index)
            columns &= set(df.columns)
    if common_index is None or len(common_index) == 0:
        raise ValueError("No common index found")

    common_index = common_index.sort_values()
    fields = sorted(columns)
    symbols = list(data_dict.keys())
    panel = pd.DataFrame(
        index=common_index,
        columns=pd.MultiIndex.from_product([fields, symbols]),
        dtype=float,
    )
    for symbol, df in data_dict.items():
        aligned = df.reindex(common_index)
        for field in fields:
            panel[(field, symbol)] = aligned[field].to_numpy()
    return panel


def walk_forward_analysis(
    data: Union[pd.DataFrame, dict],
    strategy_factory: Callable,
    param_grid: Dict[str, List[Any]],
    train_months: int = 12,
    test_months: int = 3,
    step_months: int = 3,
    initial_capital: float = 100000,
    commission: float = 0.0002,
    slippage: float = 0.0001,
    impact_coefficient: float = 0.0,
    adv_window: int = 20,
    borrow_cost: float = 0.0,
    funding_cost: float = 0.0,
    latency: int = 0,
    fill_rate: float = 1.0,
    apply_deflation: bool = False,
    benchmark: Optional[pd.DataFrame] = None,
    total_return_benchmark: bool = False,
    benchmark_commission: float = 0.0,
    benchmark_slippage: float = 0.0,
    benchmark_expense_ratio: float = 0.0,
    benchmark_cost_is_periodic: bool = False,
    validate_pit: bool = True,
    panel_pricing: str = "net-exposure",
    impact_aggregation=DEFAULT_IMPACT_AGGREGATION,
    **kwargs,
) -> Dict[str, Any]:
    """
    Perform walk-forward analysis with expanding training windows.
    Args:
        data: DataFrame with OHLCV data indexed by date
        strategy_factory: Function that creates a strategy from params dict
        param_grid: Dictionary of parameter name -> list of values to search
        train_months: Training window size in months
        test_months: Testing window size in months
        step_months: Step size between walk-forward iterations
        initial_capital: Starting portfolio value
        commission: Commission rate per trade
        slippage: Slippage rate per trade
        impact_coefficient: Market impact coefficient. Market impact is modeled as
            (position_notional / ADV) * impact_coefficient, where ADV is the
            average daily volume over `adv_window` periods. Set to 0 to disable.
        adv_window: Rolling window for Average Daily Volume calculation. Default 20.
        borrow_cost: Annual borrow cost rate for short positions (as decimal,
            e.g., 0.03 = 3% per year). Applied daily on short exposure.
        funding_cost: Annual funding cost rate for leveraged positions (as decimal,
            e.g., 0.02 = 2% per year). Applied daily on gross exposure exceeding 1x.
        latency: Execution latency in periods passed to _calculate_strategy_returns.
            Positions are delayed by `1 + latency` periods after signal generation.
            Default 0 (no added delay beyond the standard next-period fill).
        fill_rate: Position-scale limit (participation rate) in (0, 1]. The
            achieved position is ``fill_rate * target_position`` on every bar,
            so every position-change-based cost (commission, slippage, market
            impact) and every exposure-based cost (borrow, funding) scales
            with it. Default 1.0 (full fill, backward compatible).

            This is a *position-size (leverage) lever*, not a partial-fill
            execution model: the held position is reset to ``fill_rate *
            target`` each bar instead of converging toward the target
            (``position_t = position_{t-1} + fill_rate * (target_t -
            position_{t-1})``), and the unfilled part of the order is not
            charged anything. Sweeping ``fill_rate`` therefore measures
            leverage sensitivity, not execution realism -- the Sharpe ratio is
            not scale-invariant because the risk-free rate is subtracted from
            the scaled return and is not scaled with it. See
            `references/validation_methods.md`, "Fill rate: decided convention".
            passed to _calculate_strategy_returns. Default 1.0 (full fill).
        apply_deflation: When True, compute the Deflated Sharpe Ratio
            (multiple-testing correction) for each period's in-sample
            parameter selection, plus an aggregate correction on the
            combined out-of-sample returns with n_trials equal to the
            total number of configurations evaluated across all periods.
        benchmark: Optional benchmark OHLCV DataFrame for buy-and-hold comparison
        total_return_benchmark: If True, compute benchmark returns using total return
            (dividends + price) when dividend/adj_close data is available
        benchmark_commission: Commission per trade for benchmark (as decimal)
        benchmark_slippage: Slippage per trade for benchmark (as decimal)
        benchmark_expense_ratio: Annual expense ratio for benchmark (as decimal, e.g., 0.005 for 0.5%)
        validate_pit: When True, run point-in-time validation (look-ahead /
            stale-data / temporal-ordering screening) on the input data and
            record the result in `results["point_in_time_validation"]` and
            `summary["bias_controls_engaged"]`. Default True on the programmatic
            API; default True (CLI parity, non-strict: warns, never aborts).

    Returns:
        Dictionary with walk-forward results including:
            - 'periods': list of period results
            - 'best_params_per_period': list of optimal params per period
            - 'oos_returns': out-of-sample returns across all periods
            - 'summary': aggregate metrics
    """
    # Fail fast on invalid execution-realism parameters rather than silently
    # skipping every grid combination inside the per-combo try/except below.
    if fill_rate is None:
        fill_rate = 1.0
    if fill_rate <= 0 or fill_rate > 1:
        raise ValueError(f"fill_rate must be in (0, 1], got {fill_rate}")
    if latency is None:
        latency = 0
    if latency < 0:
        latency = 0
    panel_pricing = resolve_panel_pricing(panel_pricing)

    if isinstance(data, dict):
        # Normalize dict panel data (symbol -> OHLCV DataFrame) to a
        # MultiIndex (field, symbol) panel. Strategies and return
        # calculators produce identical results for both multi-asset
        # formats, so the DataFrame code paths below handle either.
        data = _dict_to_multiindex(data)

    if isinstance(data.columns, pd.MultiIndex):
        if not isinstance(data.index, pd.DatetimeIndex):
            try:
                data.index = pd.DatetimeIndex(data.index)
            except Exception:
                pass
        data = data.sort_index()
    else:
        if not isinstance(data.index, pd.DatetimeIndex):
            raise ValueError("Data must be indexed by DatetimeIndex")
        data = data.sort_index()

    # Point-in-time validation (look-ahead / stale-data / temporal-ordering
    # screening). Opt-in on the programmatic API; the CLI engages it via
    # _load_and_validate_data (validate_pit=True by default).
    pit_results = None
    if validate_pit:
        pit_results = validate_point_in_time(data)
        if pit_results["violations"]:
            print("Point-in-time validation violations:")
            for violation in pit_results["violations"]:
                print(f"  - {violation}")
        if pit_results["warnings"]:
            print("Point-in-time validation warnings:")
            for warning in pit_results["warnings"]:
                print(f"  - {warning}")
        if not pit_results["violations"] and not pit_results["warnings"]:
            print("Point-in-time validation passed (no violations or warnings).")
        elif not pit_results["violations"]:
            print("Point-in-time validation passed (no violations).")

    start_date = data.index.min()
    end_date = data.index.max()

    # Enforce non-overlapping out-of-sample test windows. When
    # step_months < test_months, consecutive test windows overlap and the
    # concatenated OOS record (built by pd.concat below) double-counts bars,
    # which silently biases the aggregate Sharpe / Deflated Sharpe Ratio
    # (duplicate entries distort the mean, variance, and the independence
    # assumption behind the SR* estimator). Reject the configuration up front
    # rather than emitting a misleading aggregate metric.
    if step_months < test_months:
        raise ValueError(
            f"step_months ({step_months}) must be >= test_months "
            f"({test_months}) so consecutive out-of-sample test windows do "
            f"not overlap. Overlapping windows double-count bars in the "
            f"concatenated oos_returns record and bias aggregate metrics. "
            f"Use step_months >= test_months, or evaluate each period's OOS "
            f"return independently instead of concatenating them."
        )

    # Generate walk-forward periods
    periods = []
    train_end = start_date + pd.DateOffset(months=train_months)
    test_start = train_end

    while test_start + pd.DateOffset(months=test_months) <= end_date:
        test_end = test_start + pd.DateOffset(months=test_months)

        train_data = data[data.index < train_end]
        test_data = data[(data.index >= test_start) & (data.index < test_end)]

        if len(train_data) > 0 and len(test_data) > 0:
            periods.append({
                "train_start": train_data.index[0],
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
                "train_data": train_data,
                "test_data": test_data,
            })

        train_end = train_end + pd.DateOffset(months=step_months)
        test_start = train_end

    # Grid search for best params on each training period
    best_params_per_period = []
    oos_returns_list = []
    total_evaluated_trials = 0
    all_trial_sharpes: List[float] = []
    period_benchmark_stats = []
    # Per-period book capacity series, merged into the summary trend.
    period_book_capacity_series: List[Any] = []
    period_book_capacity_nw_series: List[Any] = []

    for period in periods:
        train_data = period["train_data"]
        test_data = period["test_data"]

        best_sharpe = -np.inf
        best_params = None
        best_test_returns = None
        period_trial_sharpes: List[float] = []
        best_train_returns = None

        # Generate all parameter combinations
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())

        # Why each combination did or did not produce a candidate. The
        # tally is measured here, in the search itself, so the
        # partial-selection diagnosis can report a measured cause instead
        # of inferring one from an empty result.
        selection_outcomes = {
            _COMBO_ELIGIBLE: 0,
            _COMBO_FLAT: 0,
            _COMBO_DEGENERATE_TRAINING: 0,
            _COMBO_FAILED: 0,
        }
        # The bars the strategy actually held a position: for the selected
        # combination, and the most any combination could have held. The
        # diagnosis reports them next to the window's length, because a
        # window in which the strategy held a position for one bar out of
        # twenty carries far less evidence than one in which it held it
        # throughout.
        best_position_bars = 0
        max_position_bars = 0

        for combo in product(*param_values):
            params = dict(zip(param_names, combo))
            outcome = _COMBO_FAILED

            try:
                strategy = strategy_factory(params)
                train_signals = strategy.generate_signals(train_data)
                test_signals = strategy.generate_signals(test_data)

                # Skip parameter sets that take no position in the test window
                # (e.g. a lookback longer than the window itself leaves every
                # rolling indicator NaN, so the strategy stays flat). Without
                # this guard the grid search silently selects such a combo as
                # "optimal" and reports a flat (zero) out-of-sample return.
                # The test is book-aware in the "book" pricing mode: a
                # market-neutral book is a position, not a flat one.
                test_book_weights = (
                    strategy_target_weights(strategy, test_data)
                    if panel_pricing == "book"
                    else None
                )
                position_bars = _window_position_bars(
                    strategy,
                    test_signals,
                    test_data,
                    panel_pricing=panel_pricing,
                    latency=latency,
                    fill_rate=fill_rate,
                    book_weights=test_book_weights,
                )
                if position_bars > max_position_bars:
                    max_position_bars = position_bars
                if position_bars == 0:
                    outcome = _COMBO_FLAT
                else:
                    # Calculate returns for this parameter set
                    test_returns = _calculate_strategy_returns(
                        test_data, test_signals, commission, slippage,
                        impact_coefficient, adv_window, borrow_cost, funding_cost,
                        latency, fill_rate,
                        initial_capital=initial_capital,
                        panel_pricing=panel_pricing,
                        impact_aggregation=impact_aggregation,
                        book_weights=test_book_weights,
                    )

                    # Evaluate on training set
                    train_returns = _calculate_strategy_returns(
                        train_data, train_signals, commission, slippage,
                        impact_coefficient, adv_window, borrow_cost, funding_cost,
                        latency, fill_rate,
                        initial_capital=initial_capital,
                        panel_pricing=panel_pricing,
                        impact_aggregation=impact_aggregation,
                        book_weights=(
                            strategy_target_weights(strategy, train_data)
                            if panel_pricing == "book"
                            else None
                        ),
                    )

                    if len(train_returns) > 1 and not _is_constant_returns(train_returns):
                        ann_factor = _annualization_factor(train_returns.index)
                        excess = train_returns - 0.02 / ann_factor
                        sharpe = excess.mean() / excess.std() * np.sqrt(ann_factor)
                        outcome = _COMBO_ELIGIBLE
                    else:
                        # A constant (or too short) training return series has
                        # no Sharpe, so the combination cannot be ranked. It is
                        # counted separately: a window in which every
                        # combination lands here is unusable for a reason
                        # that has nothing to do with the window.
                        sharpe = -np.inf
                        outcome = _COMBO_DEGENERATE_TRAINING

                    if apply_deflation and np.isfinite(sharpe):
                        period_trial_sharpes.append(float(sharpe))

                    if sharpe > best_sharpe:
                        best_sharpe = sharpe
                        best_params = params
                        best_test_returns = test_returns
                        best_position_bars = position_bars
                        if apply_deflation:
                            best_train_returns = train_returns

            except Exception:
                outcome = _COMBO_FAILED

            selection_outcomes[outcome] += 1

        period["selection_outcomes"] = selection_outcomes
        period["max_position_bars"] = int(max_position_bars)
        period["position_bars"] = int(best_position_bars) if best_params is not None else None

        best_params_per_period.append(best_params)
        all_trial_sharpes.extend(period_trial_sharpes)
        total_evaluated_trials += len(period_trial_sharpes)
        if best_test_returns is not None and len(best_test_returns) > 0:
            oos_returns_list.append(best_test_returns)
            period["best_params"] = best_params
            period["best_sharpe"] = best_sharpe
            period["test_returns"] = best_test_returns
            period["trial_sharpes"] = list(period_trial_sharpes)
            # Per-period OUT-OF-SAMPLE test Sharpe of the selected combo.
            # Distinct from `best_sharpe`, which is the IN-SAMPLE training
            # Sharpe used by the grid search. Selection criteria that claim
            # to pick on out-of-sample quality must read this key, not
            # `best_sharpe` (which would select on in-sample fit).
            period["test_sharpe"] = _period_sharpe(best_test_returns)
            # Compute benchmark stats for this period
            if benchmark is not None:
                if isinstance(benchmark, list) and len(benchmark) > 1:
                    # Multiple benchmarks: surface a per-period Deflated Alpha
                    # correction (multiple-testing control across the benchmark
                    # set).  Uses the shared helper so the correction is applied
                    # identically to the aggregate path.
                    correction = _benchmark_list_alpha_correction(
                        best_test_returns, benchmark,
                        total_return_benchmark=total_return_benchmark,
                        benchmark_commission=benchmark_commission,
                        benchmark_slippage=benchmark_slippage,
                        benchmark_expense_ratio=benchmark_expense_ratio,
                        benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                    )
                    period["benchmark_stats"] = correction["per_benchmark"]
                    period["deflated_alpha"] = correction["deflated_alpha"]
                    period_benchmark_stats.append(correction["per_benchmark"])
                else:
                    # Single benchmark (DataFrame or single-element list):
                    # backward-compatible path (no cross-benchmark deflation).
                    bench = benchmark[0] if isinstance(benchmark, list) else benchmark
                    benchmark_returns = _compute_benchmark_returns(bench, best_test_returns, total_return_benchmark)
                    if benchmark_returns is not None:
                        period_ann_factor = _annualization_factor(best_test_returns.index)
                        bench_stats = _benchmark_stats(
                            best_test_returns, benchmark_returns, period_ann_factor,
                            total_return_benchmark=total_return_benchmark,
                            benchmark_commission=benchmark_commission,
                            benchmark_slippage=benchmark_slippage,
                            benchmark_expense_ratio=benchmark_expense_ratio,
                            benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                        )
                        period_benchmark_stats.append(bench_stats)
                    else:
                        period_benchmark_stats.append(None)
            else:
                period_benchmark_stats.append(None)
            if apply_deflation and best_train_returns is not None and period_trial_sharpes:
                # Deflate the in-sample selection Sharpe by the number of
                # configurations compared in this period's grid search.
                period["deflated_sharpe"] = deflated_sharpe_ratio(
                    sharpe_ratio=best_sharpe,
                    returns=best_train_returns,
                    n_trials=len(period_trial_sharpes),
                    trial_sharpes=period_trial_sharpes,
                )
        else:
            period["best_params"] = None
            period["best_sharpe"] = None
            period["test_returns"] = pd.Series(dtype=float)

        # Surface a per-period market-impact capacity estimate so capacity
        # degradation across regimes is observable. Capacity is a property of
        # the period's market data, so it is computed for every period (not
        # only periods whose grid search produced returns) and is None when
        # impact is disabled or ADV is not estimable.
        _period_capacity = estimate_capacity(
            period["test_data"], impact_coefficient, adv_window=adv_window
        )
        period["capacity"] = _period_capacity.get("estimated_capacity")
        # Capacity trend for the period's test window: the distribution of the
        # per-period capacity readings (min / median / max). The point-in-time
        # `capacity` above only reads the last bar of the window, so a
        # liquidity squeeze inside the window is invisible to it. None when
        # impact is disabled or ADV is not estimable.
        period["capacity_trend"] = _period_capacity.get("capacity_trend")
        # Book-based capacity for the period's test window: the capacity
        # implied by the trade sizes the selected strategy actually executes,
        # next to the basket-based number above (which assumes an
        # equal-weight basket rebalancing 1/n per constituent). Reported in
        # the "book" pricing mode only, so the default net-exposure path
        # keeps a single capacity number. None when impact is disabled, when
        # the panel carries no volume, or when the strategy exposes no book.
        period["capacity_book"] = None
        period["capacity_book_trend"] = None
        _period_book_capacity = None
        if panel_pricing == "book":
            _period_book_capacity = _window_book_capacity(
                strategy_factory,
                period.get("best_params"),
                period["test_data"],
                impact_coefficient=impact_coefficient,
                adv_window=adv_window,
                latency=latency,
                fill_rate=fill_rate,
                impact_aggregation=impact_aggregation,
            )
            if _period_book_capacity is not None:
                period["capacity_book"] = _period_book_capacity.get(
                    "estimated_capacity"
                )
                period["capacity_book_trend"] = _period_book_capacity.get(
                    "capacity_trend"
                )
                period["capacity_notional_weighted"] = _period_book_capacity.get(
                    "estimated_capacity_notional_weighted"
                )
                period["capacity_notional_weighted_trend"] = (
                    _period_book_capacity.get("capacity_notional_weighted_trend")
                )
        period_book_capacity_series.append(
            _period_book_capacity.get("capacity_series")
            if _period_book_capacity is not None
            else None
        )
        period_book_capacity_nw_series.append(
            _period_book_capacity.get("capacity_notional_weighted_series")
            if _period_book_capacity is not None
            else None
        )
        # Panel book diagnostic for the period's test window: the per-asset
        # book the selected strategy holds, measured against the
        # framework's net-exposure pricing of the same window. None when
        # the strategy exposes no book (or the path is not a panel).
        # Measurement only -- no return, cost or impact number changes.
        period["book_diagnostic"] = _window_book_diagnostic(
            strategy_factory,
            period.get("best_params"),
            period["test_data"],
            period.get("test_returns"),
            latency=latency,
            fill_rate=fill_rate,
            panel_pricing=panel_pricing,
            impact_coefficient=impact_coefficient,
            adv_window=adv_window,
            initial_capital=initial_capital,
            impact_aggregation=impact_aggregation,
        )

    # Combine all out-of-sample returns
    if oos_returns_list:
        oos_returns = pd.concat(oos_returns_list)
    else:
        oos_returns = pd.Series(dtype=float)

    # Summary metrics
    summary = _calculate_walk_forward_summary(
        oos_returns, periods, periods_with_position=len(oos_returns_list)
    )

    # Benchmark comparison on combined OOS returns
    if benchmark is not None and len(oos_returns) > 0:
        if isinstance(benchmark, list) and len(benchmark) > 1:
            # Multiple benchmarks: surface a cross-benchmark Deflated Alpha
            # correction on the aggregate out-of-sample record, mirroring the
            # calculate_metrics / benchmark_list path.
            correction = _benchmark_list_alpha_correction(
                oos_returns, benchmark,
                total_return_benchmark=total_return_benchmark,
                benchmark_commission=benchmark_commission,
                benchmark_slippage=benchmark_slippage,
                benchmark_expense_ratio=benchmark_expense_ratio,
                benchmark_cost_is_periodic=benchmark_cost_is_periodic,
            )
            summary["benchmark_metrics"] = correction["per_benchmark"]
            if correction["deflated_alpha"] is not None:
                summary["deflated_alpha"] = correction["deflated_alpha"]
                try:
                    summary["minimum_detectable_alpha"] = minimum_detectable_alpha(
                        summary["deflated_alpha"], oos_returns
                    )
                except Exception:
                    pass
        else:
            # Single benchmark (DataFrame or single-element list): backward compat
            bench = benchmark[0] if isinstance(benchmark, list) else benchmark
            benchmark_returns = _compute_benchmark_returns(bench, oos_returns, total_return_benchmark)
            if benchmark_returns is not None:
                summary = _add_benchmark_to_summary(
                    summary, oos_returns, benchmark_returns,
                    commission=benchmark_commission, slippage=benchmark_slippage,
                    benchmark_expense_ratio=benchmark_expense_ratio, total_return_benchmark=total_return_benchmark,
                    benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                    benchmark_data=bench,
                )

    # Add per-period benchmark metrics to summary
    if period_benchmark_stats:
        summary['benchmark_metrics_per_period'] = period_benchmark_stats

    # Aggregate multiple-testing correction on the combined out-of-sample
    # returns. The conservative interpretation: the OOS record was produced
    # by a search that evaluated total_evaluated_trials configurations, so
    # the OOS Sharpe is deflated by all of them. Use the pooled cross-period
    # trial Sharpes for the cross-sectional SR* estimator (conservative:
    # between-period variation inflates the null Sharpe).
    #
    # Do not skip for constant (zero-variance) return series: `deflated_sharpe_ratio`
    # handles degenerate cases by returning DSR=0, p_value=1, z_score=None.
    if apply_deflation and len(oos_returns) > 1 and max(total_evaluated_trials, 1) >= 1:
        summary["deflated_sharpe"] = deflated_sharpe_ratio(
            sharpe_ratio=summary.get("oos_sharpe", 0.0),
            returns=oos_returns,
            n_trials=max(total_evaluated_trials, 1),
            trial_sharpes=all_trial_sharpes if all_trial_sharpes else None,
        )
        # Report minimum detectable effect alongside the deflated statistic
        if summary.get("deflated_sharpe") is not None:
            try:
                summary["minimum_detectable_sharpe"] = minimum_detectable_sharpe(
                    summary["deflated_sharpe"], oos_returns
                )
            except Exception:
                pass

    # The resolution of the significance statistics carried by this summary:
    # the smallest annualized Sharpe / alpha the aggregate Deflated Sharpe
    # and Deflated Alpha tests could have confirmed at the sample size
    # actually available. A significance test on a small sample can only
    # fail, so a reader needs this to tell an informative result from an
    # unfalsifiable one. A measurement, not a correction: it changes no
    # verdict and no reported number.
    summary["test_resolution"] = _build_test_resolution(summary, oos_returns)

    summary["bias_controls_engaged"] = bool(pit_results is not None)

    # Surface market-impact capacity estimate in the summary when impact is
    # enabled and estimable; keep None (backward compatible) otherwise.
    _capacity = estimate_capacity(data, impact_coefficient, adv_window=adv_window)
    summary["capacity"] = _capacity.get("estimated_capacity")
    # Capacity trend over the whole sample: the distribution of the
    # per-period capacity readings, so a liquidity squeeze anywhere in the
    # sample is visible instead of being hidden behind the last bar's
    # point-in-time reading. None when impact is disabled or ADV is not
    # estimable.
    summary["capacity_trend"] = _capacity.get("capacity_trend")
    # Worst capacity seen in any out-of-sample window (the liquidity level
    # that actually bound the strategy in the regimes it was traded in).
    summary["oos_min_capacity"] = _aggregate_oos_capacity(
        [p.get("capacity_trend") for p in periods]
    )
    # Book-based capacity: the same estimate computed from the trade sizes
    # the strategy actually executed in the out-of-sample windows, next to
    # the basket-based number above. The per-period series of every window
    # are merged (each computed inside its own window, so no artificial
    # trade is created at a window boundary) and the trend is the
    # distribution of those per-period readings.
    _book_capacity_series = _merge_capacity_series(period_book_capacity_series)
    summary["capacity_book"] = None
    summary["capacity_book_trend"] = None
    if _book_capacity_series is not None:
        _book_readings = _book_capacity_series.replace(
            [np.inf, -np.inf], np.nan
        ).dropna()
        if len(_book_readings):
            _book_point = float(_book_readings.iloc[-1])
            summary["capacity_book"] = _book_point
            summary["capacity_book_trend"] = _capacity_trend_from_series(
                _book_capacity_series, _book_point
            )
    # Worst book-based capacity seen in any out-of-sample window: the
    # liquidity level that actually bound the strategy's own trade sizes.
    summary["oos_min_capacity_book"] = _aggregate_oos_capacity(
        [p.get("capacity_book_trend") for p in periods]
    )
    # Notional-weighted book capacity: the capacity consistent with the
    # dollar-consistent ("dw^2") impact charge, reported side by side with
    # the "|dw|" book capacity. Merged across the out-of-sample windows.
    _book_capacity_nw_series = _merge_capacity_series(period_book_capacity_nw_series)
    summary["capacity_notional_weighted"] = None
    summary["capacity_notional_weighted_trend"] = None
    if _book_capacity_nw_series is not None:
        _nw_readings = _book_capacity_nw_series.replace(
            [np.inf, -np.inf], np.nan
        ).dropna()
        if len(_nw_readings):
            _nw_point = float(_nw_readings.iloc[-1])
            summary["capacity_notional_weighted"] = _nw_point
            summary["capacity_notional_weighted_trend"] = _capacity_trend_from_series(
                _book_capacity_nw_series, _nw_point
            )
    summary["oos_min_capacity_notional_weighted"] = _aggregate_oos_capacity(
        [p.get("capacity_notional_weighted_trend") for p in periods]
    )
    # Panel book diagnostic aggregated over the out-of-sample windows: the
    # book the strategy actually held against the framework's net-exposure
    # pricing. None when no window produced a diagnostic (single asset, or
    # a strategy that does not expose a book).
    summary["book_diagnostic"] = aggregate_book_diagnostics(
        [p.get("book_diagnostic") for p in periods]
    )
    # The pricing convention that produced the reported out-of-sample P&L.
    # Recorded so a result can never be read without knowing how the panel
    # was priced.
    summary["panel_pricing"] = panel_pricing
    summary["impact_aggregation"] = impact_aggregation
    # A grid key whose values do not change the strategy's behaviour is a
    # null experiment: the per-period selection over it cannot change any
    # result, yet the artifact would still report it as a selected
    # parameter. The finding is measured and recorded here; the CLI prints
    # it next to the per-period selection.
    inert_report = _inert_grid_report(strategy_factory, param_grid, data)
    summary["inert_grid_params"] = inert_report["inert_grid_params"]
    summary["inert_grid_message"] = inert_report["message"]
    # A run in which no period could select a parameter has to say why. The
    # diagnosis uses the same vocabulary as the out-of-sample path (so one
    # reader handles both) and is recorded in the summary, so the artifact
    # explains itself instead of leaving `null` selections to be
    # interpreted. It is a measurement: it changes no number.
    if not any(p is not None for p in best_params_per_period):
        summary["no_selection_diagnosis"] = _diagnose_no_selection(
            validation_results={"periods": periods},
            validation_method="walk_forward",
            param_grid=param_grid,
            train_data=data,
            context={
                "analysis_path": "walk_forward",
                "train_months": train_months,
                "test_months": test_months,
                "step_months": step_months,
                "cli_flags": {
                    "train_months": "--train-months",
                    "test_months": "--test-months",
                    "step_months": "--step-months",
                },
            },
        )
    else:
        # A run in which *some* periods could select a parameter and others
        # could not has to say which periods were flat and why: the count
        # alone is compatible with "the flat periods were too short to
        # trade" (a design problem) and with "the strategy never triggers
        # on that part of the sample" (a finding about the strategy), and
        # the two need opposite remedies. The measurement changes no
        # number.
        partial_diagnosis = _diagnose_partial_selection(
            validation_results={"periods": periods},
            validation_method="walk_forward",
            param_grid=param_grid,
            train_data=data,
            context={
                "analysis_path": "walk_forward",
                "window_noun": "period",
                "selection_basis": "overfitting_risk_verdict",
                "train_months": train_months,
                "test_months": test_months,
                "step_months": step_months,
                "cli_flags": {
                    "train_months": "--train-months",
                    "test_months": "--test-months",
                    "step_months": "--step-months",
                },
            },
        )
        if partial_diagnosis is not None:
            summary["partial_selection_diagnosis"] = partial_diagnosis
            # A verdict that rests on some windows has to be read against
            # how much of those windows the strategy actually traded in. The
            # aggregate Sharpe and stability ratio hide that: a "low"
            # overfitting-risk rating earned on two windows that each traded
            # for one bar says little about the strategy. This is a
            # measurement -- it changes no number.
            _warmup_bars = execution_warmup_metadata(
                WARMUP_CONVENTION_WALK_FORWARD, latency
            )["execution_warmup_bars"]
            _thin = _thin_evidence_warning(
                partial_diagnosis["details"].get("traded_windows", []),
                _warmup_bars,
                window_noun="period",
            )
            if _thin is not None:
                summary["thin_evidence_warning"] = _thin
    # The execution warmup this path applied, so a consumer of the summary
    # knows how many leading bars of every window are not tradable without
    # having to re-derive the convention from the return series.
    summary.update(
        execution_warmup_metadata(WARMUP_CONVENTION_WALK_FORWARD, latency)
    )

    return {
        "periods": periods,
        "best_params_per_period": best_params_per_period,
        "oos_returns": oos_returns,
        "point_in_time_validation": pit_results,
        "summary": summary,
    }


def parameter_optimization(
    data: Union[pd.DataFrame, dict],
    strategy_factory: Callable,
    param_grid: Dict[str, List[Any]],
    initial_capital: float = 100000,
    commission: float = 0.0002,
    slippage: float = 0.0001,
    impact_coefficient: float = 0.0,
    adv_window: int = 20,
    borrow_cost: float = 0.0,
    funding_cost: float = 0.0,
    latency: int = 0,
    fill_rate: float = 1.0,
    n_splits: int = 5,
    apply_deflation: bool = False,
    benchmark: Optional[pd.DataFrame] = None,
    total_return_benchmark: bool = False,
    benchmark_commission: float = 0.0,
    benchmark_slippage: float = 0.0,
    benchmark_expense_ratio: float = 0.0,
    benchmark_cost_is_periodic: bool = False,
    panel_pricing: str = "net-exposure",
    impact_aggregation=DEFAULT_IMPACT_AGGREGATION,
    inert_grid_report: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> List[Dict[str, Any]]:
    """
    Perform parameter optimization using walk-forward-like splits.

    Args:
        data: OHLCV DataFrame
        strategy_factory: Strategy factory callable
        param_grid: Parameter grid to search
        initial_capital: Starting capital
        commission: Commission rate
        slippage: Slippage rate
        impact_coefficient: Market impact coefficient. Market impact is modeled as
            (position_notional / ADV) * impact_coefficient, where ADV is the
            average daily volume over `adv_window` periods. Set to 0 to disable.
        adv_window: Rolling window for Average Daily Volume calculation. Default 20.
        borrow_cost: Annual borrow cost rate for short positions (as decimal,
            e.g., 0.03 = 3% per year). Applied daily on short exposure.
        funding_cost: Annual funding cost rate for leveraged positions (as decimal,
            e.g., 0.02 = 2% per year). Applied daily on gross exposure exceeding 1x.
        latency: Execution latency in periods passed to _calculate_strategy_returns.
            Positions are delayed by `1 + latency` periods after signal generation.
            Default 0 (no added delay beyond the standard next-period fill).
        fill_rate: Position-scale limit (participation rate) in (0, 1]. The
            achieved position is ``fill_rate * target_position`` on every bar,
            so every position-change-based cost (commission, slippage, market
            impact) and every exposure-based cost (borrow, funding) scales
            with it. Default 1.0 (full fill, backward compatible).

            This is a *position-size (leverage) lever*, not a partial-fill
            execution model: the held position is reset to ``fill_rate *
            target`` each bar instead of converging toward the target
            (``position_t = position_{t-1} + fill_rate * (target_t -
            position_{t-1})``), and the unfilled part of the order is not
            charged anything. Sweeping ``fill_rate`` therefore measures
            leverage sensitivity, not execution realism -- the Sharpe ratio is
            not scale-invariant because the risk-free rate is subtracted from
            the scaled return and is not scaled with it. See
            `references/validation_methods.md`, "Fill rate: decided convention".
            passed to _calculate_strategy_returns. Default 1.0 (full fill).
        n_splits: Number of train/test splits
        apply_deflation: When True, compute the Deflated Sharpe Ratio
            (Bailey & Lopez de Prado, 2014) for every combination,
            correcting each Sharpe ratio for the number of trials in
            the grid. Adds a 'deflated_sharpe' dict to each result
            with keys 'deflated_sharpe_ratio', 'p_value',
            'expected_max_sharpe', 'n_trials', etc.
        benchmark: Optional benchmark OHLCV DataFrame for buy-and-hold comparison
        total_return_benchmark: If True, compute benchmark returns using total return
            (dividends + price) when dividend/adj_close data is available
        benchmark_commission: Commission per trade for benchmark (as decimal)
        benchmark_slippage: Slippage per trade for benchmark (as decimal)
        benchmark_expense_ratio: Annual expense ratio for benchmark (as decimal, e.g., 0.005 for 0.5%)
        inert_grid_report: Optional dict that receives the inert-grid
            measurement (``inert_grid_params``, ``strategy_parameters`` and
            ``message``) for the grid that was priced. A grid key whose
            values do not change the strategy's behaviour is a null
            experiment, so the caller can record the finding in its artifact
            and print it next to the ranking. This function never prints, so
            a cost sweep does not repeat the warning once per coefficient.

    Returns:
        List of result dictionaries sorted by Sharpe ratio (descending)
    """
    # Fail fast on invalid execution-realism parameters rather than silently
    # skipping every grid combination inside the per-combo try/except below.
    if fill_rate is None:
        fill_rate = 1.0
    if fill_rate <= 0 or fill_rate > 1:
        raise ValueError(f"fill_rate must be in (0, 1], got {fill_rate}")
    if latency is None:
        latency = 0
    if latency < 0:
        latency = 0
    panel_pricing = resolve_panel_pricing(panel_pricing)

    if isinstance(data, dict):
        # Normalize dict panel data (symbol -> OHLCV DataFrame) to a
        # MultiIndex (field, symbol) panel. Strategies and return
        # calculators produce identical results for both multi-asset
        # formats, so the DataFrame code paths below handle either.
        data = _dict_to_multiindex(data)

    if isinstance(data.columns, pd.MultiIndex):
        if not isinstance(data.index, pd.DatetimeIndex):
            try:
                data.index = pd.DatetimeIndex(data.index)
            except Exception:
                pass
        data = data.sort_index()
    else:
        if not isinstance(data.index, pd.DatetimeIndex):
            raise ValueError("Data must be indexed by DatetimeIndex")
        data = data.sort_index()

    # Pre-compute benchmark returns if benchmark provided
    benchmark_returns = None
    if benchmark is not None and not (isinstance(benchmark, list) and len(benchmark) > 1):
        bench = benchmark[0] if isinstance(benchmark, list) else benchmark
        if total_return_benchmark:
            benchmark_returns = _compute_benchmark_total_return(bench)
        else:
            benchmark_returns = bench["close"].pct_change()

    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())

    results = []

    for combo in product(*param_values):
        params = dict(zip(param_names, combo))

        try:
            strategy = strategy_factory(params)
            signals = strategy.generate_signals(data)

            # Skip parameter sets that take no position across the entire
            # dataset (e.g. a lookback longer than the data itself leaves
            # every rolling indicator NaN, so the strategy stays flat).
            # Without this guard such a combo reports a flat (zero) return
            # and can be ranked as "optimal" by the grid search.
            # The test is book-aware in the "book" pricing mode: a
            # market-neutral book is a position, not a flat one.
            book_weights = (
                strategy_target_weights(strategy, data)
                if panel_pricing == "book"
                else None
            )
            if not _window_takes_position(
                strategy,
                signals,
                data,
                panel_pricing=panel_pricing,
                latency=latency,
                fill_rate=fill_rate,
                book_weights=book_weights,
            ):
                continue

            returns = _calculate_strategy_returns(
                data, signals, commission, slippage,
                impact_coefficient, adv_window, borrow_cost, funding_cost,
                latency, fill_rate,
                    initial_capital=initial_capital,
                    panel_pricing=panel_pricing,
                    impact_aggregation=impact_aggregation,
                    book_weights=book_weights,
                )

            if len(returns) > 1:
                ann_factor = _annualization_factor(returns.index)
                excess = returns - 0.02 / ann_factor
                sharpe = excess.mean() / excess.std() * np.sqrt(ann_factor) if not _is_constant_returns(returns) else 0
                total_return = (1 + returns).prod() - 1

                result = {
                    "params": params,
                    "sharpe_ratio": float(sharpe),
                    "total_return": float(total_return),
                    "n_periods": len(returns),
                }

                # Add benchmark comparison metrics if benchmark provided
                if benchmark is not None:
                    if isinstance(benchmark, list) and len(benchmark) > 1:
                        correction = _benchmark_list_alpha_correction(
                            returns, benchmark,
                            total_return_benchmark=total_return_benchmark,
                            benchmark_commission=benchmark_commission,
                            benchmark_slippage=benchmark_slippage,
                            benchmark_expense_ratio=benchmark_expense_ratio,
                            benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                        )
                        primary_stats = correction["per_benchmark"][0] if correction["per_benchmark"] else None
                        if primary_stats is not None:
                            result.update(primary_stats)
                        result["benchmark_metrics"] = correction["per_benchmark"]
                        if correction["deflated_alpha"] is not None:
                            result["deflated_alpha"] = correction["deflated_alpha"]
                    elif benchmark_returns is not None and len(benchmark_returns) > 0:
                        bench_stats = _benchmark_stats(
                            returns, benchmark_returns, ann_factor,
                            total_return_benchmark=total_return_benchmark,
                            benchmark_commission=benchmark_commission,
                            benchmark_slippage=benchmark_slippage,
                            benchmark_expense_ratio=benchmark_expense_ratio,
                            benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                        )
                        result.update(bench_stats)

                results.append(result)
                if apply_deflation:
                    # Transient key: the return series is consumed by
                    # the deflation step below and never returned.
                    results[-1]["_returns"] = returns
        except Exception:
            continue

    # A grid key whose values do not change the strategy's behaviour is a null
    # experiment: the ranking over it cannot change any result, yet the
    # artifact would still report it as a selected parameter. The finding is
    # measured here and handed to the caller (which records it in the artifact
    # and prints it next to the ranking); this function never prints, so a
    # cost sweep does not repeat the warning once per coefficient.
    inert_report = _inert_grid_report(strategy_factory, param_grid, data)
    if inert_grid_report is not None:
        inert_grid_report.update(inert_report)

    results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)

    # Multiple-testing correction: deflate every combination's Sharpe
    # by the number of ranked trials, using the cross-sectional
    # dispersion of the trial Sharpes to estimate the Sharpe
    # attainable from luck.
    if apply_deflation and results:
        n_trials = len(results)
        trial_sharpes = [r["sharpe_ratio"] for r in results]
        for result in results:
            result["deflated_sharpe"] = deflated_sharpe_ratio(
                sharpe_ratio=result["sharpe_ratio"],
                returns=result.pop("_returns"),
                n_trials=n_trials,
                trial_sharpes=trial_sharpes,
            )

    return results


def overfitting_check(
    wf_results: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Check for overfitting in walk-forward results.

    Args:
        wf_results: Results from walk_forward_analysis

    Returns:
        Dictionary with overfitting diagnostics
    """
    periods = wf_results.get("periods", [])
    oos_returns = wf_results.get("oos_returns", pd.Series(dtype=float))

    diagnostics = {
        "n_periods": len(periods),
        "n_valid_periods": len([p for p in periods if p.get("test_returns") is not None and len(p["test_returns"]) > 0]),
    }

    # Check if optimal params are consistent across periods
    valid_params = [p["best_params"] for p in periods if p.get("best_params") is not None]
    if valid_params:
        # Count how often each parameter value appears
        param_stability = {}
        param_names = set()
        for params in valid_params:
            param_names.update(params.keys())

        for name in param_names:
            values = [p.get(name) for p in valid_params if name in p]
            if values:
                unique_count = len(set(values))
                param_stability[name] = {
                    "unique_values": unique_count,
                    "most_common": max(set(values), key=values.count) if values else None,
                    "stability_ratio": 1.0 - unique_count / len(values),
                }
        diagnostics["param_stability"] = param_stability

    # OOS performance
    if len(oos_returns) > 0 and not _is_constant_returns(oos_returns):
        ann_factor = _annualization_factor(oos_returns.index)
        excess = oos_returns - 0.02 / ann_factor
        diagnostics["oos_sharpe"] = float(excess.mean() / excess.std() * np.sqrt(ann_factor))
        diagnostics["oos_total_return"] = float((1 + oos_returns).prod() - 1)
        diagnostics["oos_volatility"] = float(oos_returns.std() * np.sqrt(ann_factor))
    else:
        diagnostics["oos_sharpe"] = 0.0
        diagnostics["oos_total_return"] = 0.0
        diagnostics["oos_volatility"] = 0.0

    # Surface the aggregate Deflated Sharpe Ratio when the
    # walk-forward run computed one (apply_deflation=True).
    wf_summary = wf_results.get("summary", {})
    if isinstance(wf_summary, dict) and "deflated_sharpe" in wf_summary:
        diagnostics["deflated_sharpe"] = wf_summary["deflated_sharpe"]

    # Overfitting flags
    if len(valid_params) > 0:
        # High parameter variation across periods suggests overfitting
        avg_stability = np.mean([
            v["stability_ratio"] for v in diagnostics.get("param_stability", {}).values()
        ]) if diagnostics.get("param_stability") else 1.0
        if avg_stability < 0.3:
            diagnostics["overfitting_risk"] = "high"
        elif avg_stability < 0.5:
            diagnostics["overfitting_risk"] = "medium"
        else:
            diagnostics["overfitting_risk"] = "low"
        # A run in which only some periods could select a parameter has a
        # verdict that rests on fewer periods than the run has. The
        # categorical verdict is unchanged (the measurement supports it),
        # but its basis is stated: a reader must not read "low risk" as
        # "measured on every period".
        partial = wf_summary.get("partial_selection_diagnosis")
        if isinstance(partial, dict):
            details = partial.get("details") or {}
            diagnostics["overfitting_risk_reason"] = (
                f"the '{diagnostics['overfitting_risk']}' verdict rests on "
                f"the parameter stability of the "
                f"{details.get('n_windows_with_selected_params')} of the "
                f"{details.get('n_validation_windows')} out-of-sample "
                f"{details.get('window_noun', 'period')}s that selected a "
                f"parameter; the other {details.get('n_flat_windows')} "
                f"produced no selection and contributed nothing to it (see "
                f"summary['partial_selection_diagnosis'])"
            )
    else:
        # No period selected a parameter, so there is no parameter
        # instability to measure: the risk verdict is *not applicable*, not
        # "low". A categorical verdict on a run in which nothing could trade
        # is a category error, and it reads as a finding about the strategy
        # when it is a fact about the window. The CPCV path reports the same
        # state the same way.
        diagnostics["overfitting_risk"] = None
        diagnostics["overfitting_risk_reason"] = (
            "not applicable: no parameter was selected in any period, so "
            "there is no parameter stability to classify (see "
            "summary['no_selection_diagnosis'])"
        )

    return diagnostics


def signals_active(signals: pd.Series) -> bool:
    """Return True if the signal series ever takes a non-zero position.

    A strategy that never takes a position (e.g. a lookback longer than the
    data window leaves every rolling indicator NaN, so the signal stays flat
    at 0) produces no trades and meaningless zero returns. Callers should
    skip such parameter sets rather than ranking them as "optimal".
    """
    # NaN != 0 evaluates to True in pandas, so we must explicitly exclude NaN
    return bool((signals.notna() & (signals != 0)).any())


def _window_position_bars(
    strategy,
    signals: pd.Series,
    data,
    panel_pricing: str = "net-exposure",
    latency: int = 0,
    fill_rate: float = 1.0,
    book_weights: Optional[pd.DataFrame] = None,
) -> int:
    """How many bars of the window does the strategy hold a position?

    The count is the *amount of evidence* a window contributes: a window in
    which the strategy holds a position for one bar out of twenty says far
    less about the strategy than one in which it holds it throughout, and a
    window in which it never holds a position says nothing at all. The
    selection diagnosis reports the count next to the window's length so
    the two can be read together.

    Under the ``net-exposure`` pricing convention the count is the number
    of bars with a non-flat signal. Under the ``book`` pricing convention
    it is the number of bars with a non-empty held book (a market-neutral
    book is a position: its *net* exposure is flat but its gross book is
    not). A strategy that exposes no book falls back to the scalar count.
    """
    if panel_pricing == "book":
        if book_weights is None:
            book_weights = strategy_target_weights(strategy, data)
        if book_weights is not None:
            market = build_market_model(data)
            if market["is_panel"]:
                held = held_book_weights(
                    book_weights,
                    market,
                    lag=1 + latency,
                    fill_rate=fill_rate,
                )
                if held is None:
                    # No usable book: the strategy holds no position. The
                    # scalar signal test is *not* a fallback here -- a
                    # panel book that cannot be held is not a position.
                    return 0
                return int((held.abs().sum(axis=1) > 0).sum())
    # NaN != 0 evaluates to True in pandas, so NaN bars are excluded.
    return int((signals.notna() & (signals != 0)).sum())


def _window_takes_position(
    strategy,
    signals: pd.Series,
    data,
    panel_pricing: str = "net-exposure",
    latency: int = 0,
    fill_rate: float = 1.0,
    book_weights: Optional[pd.DataFrame] = None,
) -> bool:
    """Does the strategy hold a position in this window?

    Under the ``net-exposure`` pricing convention the test is the scalar
    signal test (:func:`signals_active`): a flat signal means no position.

    Under the ``book`` pricing convention the test is book-aware: a
    market-neutral book has a flat *net* exposure but a non-zero *gross*
    book, so it does hold a position and must not be skipped by the grid
    search. A strategy that exposes no book falls back to the scalar test.

    The test is the "more than zero bars" reading of
    :func:`_window_position_bars`, which measures the same thing and also
    reports how many bars the position was held.
    """
    return _window_position_bars(
        strategy,
        signals,
        data,
        panel_pricing=panel_pricing,
        latency=latency,
        fill_rate=fill_rate,
        book_weights=book_weights,
    ) > 0


def _is_constant_returns(returns: pd.Series) -> bool:
    """Return True when every observation in `returns` is identical.

    A constant (zero-variance) return series carries no statistical
    information about skill: the Sharpe is undefined and the DSR is
    defined conservatively as 0 (see ``deflated_sharpe_ratio``).

    Detection is exact (``nunique() == 1``), not a tolerance test on
    ``std()``. ``pd.Series.std()`` on a constant series is not exactly
    zero — it is a float-noise residue (~1e-19) — so comparing
    ``returns.std() > 0`` would wrongly treat a constant series as
    non-degenerate and route it through the finite-z branch, emitting
    a non-degenerate DSR (a finite z_score, DSR != 0) for data the
    contract classifies as degenerate. Exact equality also keeps a
    genuine near-constant-but-noisy series (real std ~1e-3) on the
    non-degenerate path, where it belongs.
    """
    return bool(returns.nunique(dropna=False) == 1)


def _period_sharpe(returns: pd.Series) -> Optional[float]:
    """Annualized Sharpe of a single period's OUT-OF-SAMPLE test returns.

    Mirrors the in-sample Sharpe computed inline in the walk-forward grid
    search (``excess = returns - 0.02/ann_factor``; Sharpe = mean/std *
    sqrt(ann_factor)) but evaluated on the *test* window of the selected
    combo. Returns ``None`` when the series is too short or degenerate,
    so callers can distinguish "no OOS Sharpe available" from "Sharpe 0".
    """
    if returns is None or len(returns) <= 1:
        return None
    if _is_constant_returns(returns):
        return 0.0
    ann_factor = _annualization_factor(returns.index)
    excess = returns - 0.02 / ann_factor
    std = excess.std()
    if std == 0 or not np.isfinite(std):
        return 0.0
    return float(excess.mean() / std * np.sqrt(ann_factor))


def _selected_params_avg_test_sharpe(
    validation_results: Dict[str, Any],
    validation_method: str,
    selected_params: Optional[Dict[str, Any]],
) -> Optional[float]:
    """Mean OUT-OF-SAMPLE test Sharpe of `selected_params` across the
    validation periods/folds where the grid search chose it.

    Computed from each period/fold's ``test_sharpe`` (OOS), never from
    ``best_sharpe`` (in-sample training fit). Returns ``None`` when the
    selected combo was never chosen, or when no period that chose it
    carries a finite ``test_sharpe`` (e.g. all such test windows were
    degenerate/empty). Excludes periods with ``test_sharpe is None``
    rather than treating them as 0, so a degenerate test window cannot
    drag the average to zero.
    """
    if selected_params is None:
        return None
    key = tuple(sorted(selected_params.items()))
    items_key = "periods" if validation_method == "walk_forward" else "folds"
    items = validation_results.get(items_key, [])
    sharpes = [
        p.get("test_sharpe")
        for p in items
        if p.get("best_params") is not None
        and tuple(sorted(p["best_params"].items())) == key
        and p.get("test_sharpe") is not None
    ]
    if not sharpes:
        return None
    return float(np.mean(sharpes))


def deflated_sharpe_ratio(
    sharpe_ratio: float,
    returns: pd.Series,
    n_trials: int,
    trial_sharpes: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """
    Compute the Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014).

    Searching over a grid of parameter combinations is a multiple-testing
    problem: with enough configurations, luck alone produces an attractive
    in-sample Sharpe ratio. The Deflated Sharpe Ratio (DSR) corrects the
    estimated Sharpe for this selection bias and for the non-normality
    (skewness, kurtosis) of the return distribution.

    Formula (all Sharpe quantities in per-period, non-annualized units):

        DSR = Phi( (SR_hat - SR*) * sqrt(T - 1)
                    / sqrt(1 - gamma3 * SR_hat + ((gamma4 - 1) / 4) * SR_hat^2) )

    where SR_hat is the per-period estimated Sharpe, T the number of return
    observations, gamma3 the return skewness, gamma4 the return kurtosis
    (not excess), Phi the standard normal CDF, and SR* the expected maximum
    Sharpe ratio under the null hypothesis of no skill.

    SR* is estimated from the cross-sectional dispersion of the trial Sharpe
    ratios when `trial_sharpes` is provided (SR* = std(SR_trials) *
    sqrt(2 * ln(N))), and otherwise from the i.i.d.-normal null approximation
    (SR* = sqrt(2 * ln(N) / T)). Both estimators are conservative: they
    slightly overstate the Sharpe attainable from luck.

    Args:
        sharpe_ratio: Annualized Sharpe ratio of the strategy being evaluated.
        returns: Per-period return series behind `sharpe_ratio`.
        n_trials: Number of configurations tested (N).
        trial_sharpes: Optional list of the annualized Sharpe ratios of all
            trials. When provided (recommended), the cross-sectional
            dispersion of the trials estimates SR*; otherwise the i.i.d.-
            normal null approximation is used.

    Returns:
        Dictionary with:
            - 'deflated_sharpe_ratio': DSR in [0, 1]; the probability that
              the strategy's true Sharpe exceeds the best Sharpe expected
              from luck alone across the N trials
            - 'p_value': 1 - DSR
            - 'sharpe_ratio': input annualized Sharpe ratio
            - 'expected_max_sharpe': SR* in annualized units (the deflation
              benchmark)
            - 'z_score': standardized distance passed to Phi
            - 'n_trials': number of trials N
            - 'n_observations': T
            - 'skewness', 'kurtosis': return moments used in the correction
    """
    if n_trials < 1:
        raise ValueError("n_trials must be at least 1")

    returns = returns.dropna()
    if len(returns) < 2:
        raise ValueError("Need at least 2 return observations for Deflated Sharpe Ratio")

    ann_factor = _annualization_factor(returns.index)
    t_obs = len(returns)
    sr = float(sharpe_ratio) / np.sqrt(ann_factor)

    ln_trials = np.log(max(int(n_trials), 1))

    # Expected maximum Sharpe under the null (per-period units)
    sr_star = None
    if trial_sharpes is not None and len(trial_sharpes) >= 2:
        trial_sr = np.asarray([float(s) for s in trial_sharpes], dtype=float)
        trial_sr = trial_sr / np.sqrt(ann_factor)
        trial_std = float(np.std(trial_sr, ddof=1))
        if trial_std > 0 and np.isfinite(trial_std):
            sr_star = trial_std * np.sqrt(2.0 * ln_trials)
    if sr_star is None:
        sr_star = float(np.sqrt(2.0 * ln_trials / t_obs))

    # Variance of the Sharpe estimator under non-normality (skew/kurt are
    # invariant to constant shifts, so raw-return moments are valid for a
    # Sharpe computed on excess returns)
    skew = float(returns.skew())
    kurt = float(returns.kurtosis()) + 3.0  # pandas reports excess kurtosis
    if not np.isfinite(skew):
        skew = 0.0
    if not np.isfinite(kurt):
        kurt = 3.0

    variance_term = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if not np.isfinite(variance_term) or variance_term <= 0.0:
        variance_term = np.finfo(float).tiny
    denom = np.sqrt(variance_term)

    vol = float(returns.std())
    if _is_constant_returns(returns):
        # Degenerate (constant) returns carry no information about skill
        z = -np.inf
    elif vol > 0:
        z = (sr - sr_star) * np.sqrt(t_obs - 1) / denom
    else:
        # Zero observations after dropna (impossible here: the guard
        # above requires len >= 2) — fall back to the degenerate branch.
        z = -np.inf

    dsr = 0.5 * (1.0 + math.erf(z / np.sqrt(2.0)))
    dsr = float(min(max(dsr, 0.0), 1.0))

    return {
        "deflated_sharpe_ratio": dsr,
        "p_value": 1.0 - dsr,
        "sharpe_ratio": float(sharpe_ratio),
        "expected_max_sharpe": float(sr_star * np.sqrt(ann_factor)),
        "z_score": float(z) if np.isfinite(z) else None,
        "n_trials": int(n_trials),
        "n_observations": int(t_obs),
        "skewness": float(skew),
        "kurtosis": float(kurt),
    }


def deflated_alpha_ratio(
    alpha: float,
    returns: pd.Series,
    benchmark_returns: pd.Series,
    n_benchmarks: int,
    trial_alphas: Optional[List[float]] = None,
) -> Dict[str, Any]:
    """
    Compute the Deflated Alpha Ratio (analogue to Deflated Sharpe Ratio).

    Testing multiple benchmarks is a multiple-testing problem: with enough
    benchmarks, luck alone produces an attractive alpha. The Deflated Alpha
    Ratio (DAR) corrects the estimated alpha for this selection bias and for
    the non-normality (skewness, kurtosis) of the return distribution.

    Formula (Bailey & Lopez de Prado, 2014, Deflated Sharpe Ratio analogue).
    The statistic is formulated in dimensionless Sharpe-ratio units so that
    it is invariant to the data frequency: the estimated alpha is divided by
    the strategy's annualized volatility to form a Sharpe-like ratio ``sr``,
    and the expected maximum under the null is expressed in the same units.

        DAR = Phi( (sr - sr*) * sqrt(T - 1)
                    / sqrt(1 - gamma3 * sr + ((gamma4 - 1) / 4) * sr^2) )

    where sr is the estimated Sharpe-like ratio, T the number of return
    observations, gamma3 the return skewness, gamma4 the return kurtosis
    (not excess), Phi the standard normal CDF, and sr* the expected maximum
    Sharpe-like ratio under the null hypothesis of no skill.

    sr* is estimated from the cross-sectional dispersion of the trial alphas
    (converted to Sharpe units) when `trial_alphas` is provided
    (sr* = std(trial_sr) * sqrt(2 * ln(N))), and otherwise from the
    i.i.d.-normal null approximation (sr* = sqrt(2 * ln(N) / T)). Both
    estimators are conservative: they slightly overstate the Sharpe attainable
    from luck alone.

    The expected-maximum alpha is reported back in annualized alpha units
    (sr* * strategy_vol_ann) for backward compatibility with consumers that
    read `expected_max_alpha` as an annualized alpha.

    Args:
        alpha: Annualized alpha of the strategy being evaluated.
        returns: Per-period return series of the strategy.
        benchmark_returns: Per-period return series of the benchmark.
        n_benchmarks: Number of benchmarks tested (N).
        trial_alphas: Optional list of the annualized alphas of all
            benchmarks tested. When provided (recommended), the cross-sectional
            dispersion of the alphas estimates sr*; otherwise the i.i.d.-
            normal null approximation is used.

    Returns:
        Dictionary with:
            - 'deflated_alpha_ratio': DAR in [0, 1]; the probability that
              the strategy's true alpha exceeds the best alpha expected
              from luck alone across the N benchmarks
            - 'p_value': 1 - DAR
            - 'alpha': input annualized alpha
            - 'expected_max_alpha': alpha* in annualized units (the deflation
              benchmark)
            - 'z_score': standardized distance passed to Phi
            - 'n_benchmarks': number of benchmarks N
            - 'n_observations': T
            - 'skewness', 'kurtosis': return moments used in the correction
    """
    if n_benchmarks < 1:
        raise ValueError("n_benchmarks must be at least 1")

    returns = returns.dropna()
    if len(returns) < 2:
        raise ValueError("Need at least 2 return observations for Deflated Alpha Ratio")

    ann_factor = _annualization_factor(returns.index)
    t_obs = len(returns)

    # Annualized strategy volatility. The Deflated Sharpe Ratio's variance
    # adjustment term (1 - gamma3*x + ((gamma4-1)/4)*x^2) is dimensionless and
    # only valid when x is a Sharpe-like ratio; plugging in a raw per-period
    # return makes the statistic frequency-dependent and understates skill on
    # lower-frequency data. Normalizing alpha by strategy vol cancels the
    # annualization factor, so DAR is invariant to the sampling frequency when
    # calendar time is held fixed.
    strat_vol_ann = float(returns.std() * np.sqrt(ann_factor))
    if _is_constant_returns(returns):
        # Degenerate (constant) returns carry no information about skill.
        sr = 0.0
    elif strat_vol_ann > 0:
        # alpha and strat_vol_ann are both annualized, so their ratio is an
        # annualized Sharpe-like ratio.  The z-formula below is derived for
        # PER-PERIOD Sharpe quantities (its sqrt(T - 1) term is the standard
        # error of a per-period Sharpe estimate), so rescale to per-period
        # before comparing against sr* (which is period-scale in both the
        # cross-sectional and i.i.d.-null estimators).
        sr = float(alpha) / strat_vol_ann / np.sqrt(ann_factor)
    else:
        # Zero observations after dropna (impossible here: the guard
        # above requires len >= 2) — fall back to the degenerate branch.
        sr = 0.0

    ln_benchmarks = np.log(max(int(n_benchmarks), 1))

    # Expected maximum Sharpe-like ratio under the null (dimensionless).
    sr_star = None
    if trial_alphas is not None and len(trial_alphas) >= 2:
        trial_alpha = np.asarray([float(a) for a in trial_alphas], dtype=float)
        # Convert annualized trial alphas to per-period Sharpe-like ratios for
        # consistency with `sr` (the z-formula is derived in per-period units).
        trial_sr = trial_alpha / strat_vol_ann / np.sqrt(ann_factor) if strat_vol_ann > 0 else trial_alpha
        trial_std = float(np.std(trial_sr, ddof=1))
        if trial_std > 0 and np.isfinite(trial_std):
            sr_star = trial_std * np.sqrt(2.0 * ln_benchmarks)
    if sr_star is None:
        # Fallback to i.i.d.-normal null approximation: the Sharpe estimate under
        # the null has std ~ 1/sqrt(T), so the expected max of N draws is
        # sqrt(2 * ln(N) / T).
        sr_star = float(np.sqrt(2.0 * ln_benchmarks / t_obs)) if t_obs > 0 else 0.0

    # Variance of the Sharpe estimator under non-normality (skew/kurt are
    # invariant to constant shifts, so raw-return moments are valid).
    skew = float(returns.skew())
    kurt = float(returns.kurtosis()) + 3.0  # pandas reports excess kurtosis
    if not np.isfinite(skew):
        skew = 0.0
    if not np.isfinite(kurt):
        kurt = 3.0

    variance_term = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * sr * sr
    if not np.isfinite(variance_term) or variance_term <= 0.0:
        variance_term = np.finfo(float).tiny
    denom = np.sqrt(variance_term)

    if _is_constant_returns(returns):
        # Degenerate (constant) returns carry no information about skill
        z = -np.inf
    elif strat_vol_ann > 0:
        z = (sr - sr_star) * np.sqrt(t_obs - 1) / denom
    else:
        # Zero observations after dropna (impossible here: the guard
        # above requires len >= 2) — fall back to the degenerate branch.
        z = -np.inf

    dar = 0.5 * (1.0 + math.erf(z / np.sqrt(2.0)))
    dar = float(min(max(dar, 0.0), 1.0))

    # Report expected_max_alpha in annualized alpha units (backward-compat shape).
    # sr_star is now per-period; annualize via strat_vol_ann * sqrt(ann_factor)
    # (= vol_per_period * ann_factor) so expected_max_alpha stays in annualized
    # alpha units and matches the cross-sectional estimator's pre-fix value.
    expected_max_alpha = sr_star * strat_vol_ann * np.sqrt(ann_factor) if strat_vol_ann > 0 else 0.0

    return {
        "deflated_alpha_ratio": dar,
        "p_value": 1.0 - dar,
        "alpha": float(alpha),
        "expected_max_alpha": float(expected_max_alpha),
        "z_score": float(z) if np.isfinite(z) else None,
        "n_benchmarks": int(n_benchmarks),
        "n_observations": int(t_obs),
        "skewness": float(skew),
        "kurtosis": float(kurt),
    }


# ---------------------------------------------------------------------------
# Minimum detectable effect (test resolution)
# ---------------------------------------------------------------------------
#
# A significance test on a small sample can fail for reasons that have
# nothing to do with the hypothesis. With T observations, a threshold of
# "deflated p < 0.10" requires the effect to exceed a certain size; when that
# size is implausible, the criterion is not discriminating between
# hypotheses -- it is measuring the sample size. Reporting the minimum
# detectable effect (MDE) alongside the verdict makes that explicit: it
# states the smallest effect the test could have confirmed, so a reader can
# judge whether a failed criterion is evidence against the hypothesis or just
# a statement about the resolution of the test.
#
# The helpers below invert the Deflated Sharpe / Deflated Alpha statistics
# using the forward statistic's own components (SR*, T, skewness, kurtosis),
# so the reported resolution is exactly the resolution of the statistic that
# produced the verdict.


def _normal_quantile(p: float) -> float:
    """Inverse standard-normal CDF (stdlib only, no SciPy dependency)."""
    if not np.isfinite(p) or p <= 0.0 or p >= 1.0:
        raise ValueError(f"probability must be in (0, 1), got {p}")
    return float(NormalDist().inv_cdf(p))


def _deflation_z_score(
    effect: float,
    effect_star: float,
    t_obs: int,
    skew: float,
    kurt: float,
) -> float:
    """z-statistic of the Deflated Sharpe / Deflated Alpha test.

    Mirrors the z-formula of :func:`deflated_sharpe_ratio` and
    :func:`deflated_alpha_ratio`, which both use it to turn an estimated
    effect into a probability. The minimum-detectable-effect helpers invert
    it, so the forward and inverse forms must stay in lockstep (pinned by
    ``test_the_minimum_detectable_effect_helpers_mirror_the_forward_statistics``).
    """
    if t_obs <= 1:
        return float("-inf")
    variance_term = 1.0 - skew * effect + ((kurt - 1.0) / 4.0) * effect * effect
    if not np.isfinite(variance_term) or variance_term <= 0.0:
        variance_term = np.finfo(float).tiny
    return (effect - effect_star) * math.sqrt(t_obs - 1) / math.sqrt(variance_term)


def _solve_minimum_effect(
    target_z: float,
    effect_star: float,
    t_obs: int,
    skew: float,
    kurt: float,
) -> Optional[float]:
    """Smallest effect whose deflation z-score reaches ``target_z``.

    ``effect`` and ``effect_star`` share the same (per-period, dimensionless)
    units. Returns None when no such effect exists -- the z-score saturates
    below the target for every effect when the variance term grows faster
    than the numerator.
    """
    if not np.isfinite(target_z) or t_obs <= 1:
        return None
    if _deflation_z_score(effect_star, effect_star, t_obs, skew, kurt) >= target_z:
        return float(effect_star)

    # The z-score is increasing in the effect for well-behaved parameters, so
    # expand upward until the target is crossed and then bisect.
    step = max(abs(effect_star) * 0.25, 0.05)
    lo = float(effect_star)
    hi = float(effect_star) + step
    z_hi = _deflation_z_score(hi, effect_star, t_obs, skew, kurt)
    for _ in range(200):
        if np.isfinite(z_hi) and z_hi >= target_z:
            break
        lo = hi
        step *= 2.0
        hi = float(effect_star) + step
        z_hi = _deflation_z_score(hi, effect_star, t_obs, skew, kurt)
    else:
        return None

    for _ in range(200):
        mid = 0.5 * (lo + hi)
        z_mid = _deflation_z_score(mid, effect_star, t_obs, skew, kurt)
        if np.isfinite(z_mid) and z_mid >= target_z:
            hi = mid
        else:
            lo = mid
    return float(0.5 * (lo + hi))


def minimum_detectable_sharpe(
    deflated_sharpe: Dict[str, Any],
    returns: pd.Series,
    target_p_value: float = 0.10,
) -> Dict[str, Any]:
    """Smallest annualized Sharpe the Deflated Sharpe Ratio can confirm.

    Inverts the Deflated Sharpe Ratio: given the forward statistic (its
    ``expected_max_sharpe``, ``n_observations``, ``skewness`` and
    ``kurtosis``) and the return series it was computed on, returns the
    smallest annualized Sharpe whose deflated p-value reaches
    ``target_p_value``.

    Args:
        deflated_sharpe: Forward result from :func:`deflated_sharpe_ratio`
            (e.g. ``summary["deflated_sharpe"]``).
        returns: The per-period return series the statistic was computed on.
        target_p_value: The p-value threshold the criterion uses.

    Returns:
        Dict with ``minimum_detectable_sharpe`` (annualized), the per-period
        value, the observed Sharpe, the expected-max Sharpe under the null,
        T and N, plus ``attainable`` / ``reason`` describing whether the
        threshold can be reached at all.
    """
    out: Dict[str, Any] = {
        "minimum_detectable_sharpe": None,
        "minimum_detectable_sharpe_per_period": None,
        "target_p_value": float(target_p_value),
        "observed_sharpe": None,
        "expected_max_sharpe": None,
        "n_observations": None,
        "n_trials": None,
        "attainable": False,
        "reason": None,
    }
    if not isinstance(deflated_sharpe, dict):
        out["reason"] = "no_deflated_sharpe"
        return out

    t_obs = deflated_sharpe.get("n_observations")
    sr_star_ann = deflated_sharpe.get("expected_max_sharpe")
    out["observed_sharpe"] = deflated_sharpe.get("sharpe_ratio")
    out["expected_max_sharpe"] = sr_star_ann
    out["n_observations"] = t_obs
    out["n_trials"] = deflated_sharpe.get("n_trials")

    if returns is None:
        out["reason"] = "no_returns"
        return out
    series = returns.dropna() if hasattr(returns, "dropna") else returns
    if len(series) < 2:
        out["reason"] = "insufficient_returns"
        return out
    if t_obs is None or int(t_obs) != len(series):
        out["reason"] = "returns_do_not_match_statistic"
        return out
    if sr_star_ann is None or not np.isfinite(float(sr_star_ann)):
        out["reason"] = "no_expected_max_sharpe"
        return out

    ann_factor = _annualization_factor(series.index)
    skew = float(deflated_sharpe.get("skewness", 0.0))
    kurt = float(deflated_sharpe.get("kurtosis", 3.0))
    target_z = _normal_quantile(1.0 - float(target_p_value))

    sr_star = float(sr_star_ann) / math.sqrt(ann_factor)
    sr_required = _solve_minimum_effect(target_z, sr_star, int(t_obs), skew, kurt)
    if sr_required is None:
        out["reason"] = "target_unattainable"
        return out

    out["minimum_detectable_sharpe_per_period"] = float(sr_required)
    out["minimum_detectable_sharpe"] = float(sr_required * math.sqrt(ann_factor))
    out["attainable"] = True
    return out


def minimum_detectable_alpha(
    deflated_alpha: Dict[str, Any],
    returns: pd.Series,
    target_p_value: float = 0.10,
) -> Dict[str, Any]:
    """Smallest annualized alpha the Deflated Alpha Ratio can confirm.

    The Deflated Alpha Ratio analogue of :func:`minimum_detectable_sharpe`:
    inverts the DAR statistic to report the smallest annualized alpha whose
    deflated p-value reaches ``target_p_value`` at the realized sample size.

    Args:
        deflated_alpha: Forward result from :func:`deflated_alpha_ratio`
            (e.g. ``summary["deflated_alpha"]``).
        returns: The strategy's per-period return series (the series the
            statistic was computed on).
        target_p_value: The p-value threshold the criterion uses.

    Returns:
        Dict with ``minimum_detectable_alpha`` (annualized), the per-period
        value, the observed alpha, the expected-max alpha under the null, T
        and N, plus ``attainable`` / ``reason``.
    """
    out: Dict[str, Any] = {
        "minimum_detectable_alpha": None,
        "minimum_detectable_alpha_per_period": None,
        "target_p_value": float(target_p_value),
        "observed_alpha": None,
        "expected_max_alpha": None,
        "n_observations": None,
        "n_benchmarks": None,
        "attainable": False,
        "reason": None,
    }
    if not isinstance(deflated_alpha, dict):
        out["reason"] = "no_deflated_alpha"
        return out

    t_obs = deflated_alpha.get("n_observations")
    max_alpha_ann = deflated_alpha.get("expected_max_alpha")
    out["observed_alpha"] = deflated_alpha.get("alpha")
    out["expected_max_alpha"] = max_alpha_ann
    out["n_observations"] = t_obs
    out["n_benchmarks"] = deflated_alpha.get("n_benchmarks")

    if returns is None:
        out["reason"] = "no_returns"
        return out
    series = returns.dropna() if hasattr(returns, "dropna") else returns
    if len(series) < 2:
        out["reason"] = "insufficient_returns"
        return out
    if t_obs is None or int(t_obs) != len(series):
        out["reason"] = "returns_do_not_match_statistic"
        return out
    if max_alpha_ann is None or not np.isfinite(float(max_alpha_ann)):
        out["reason"] = "no_expected_max_alpha"
        return out

    ann_factor = _annualization_factor(series.index)
    strat_vol_ann = float(series.std() * math.sqrt(ann_factor))
    if strat_vol_ann <= 0:
        out["reason"] = "zero_volatility"
        return out
    skew = float(deflated_alpha.get("skewness", 0.0))
    kurt = float(deflated_alpha.get("kurtosis", 3.0))
    target_z = _normal_quantile(1.0 - float(target_p_value))

    # The forward statistic works in per-period Sharpe-like units:
    # sr = alpha / (vol_ann * sqrt(ann_factor)), so invert through the same
    # scale factor and report the required alpha back in annualized units.
    scale = strat_vol_ann * math.sqrt(ann_factor)
    sr_star = float(max_alpha_ann) / scale
    sr_required = _solve_minimum_effect(target_z, sr_star, int(t_obs), skew, kurt)
    if sr_required is None:
        out["reason"] = "target_unattainable"
        return out

    out["minimum_detectable_alpha_per_period"] = float(sr_required)
    out["minimum_detectable_alpha"] = float(sr_required * scale)
    out["attainable"] = True
    return out


def _format_optional_float(value: Any, fmt: str = "{:.4f}") -> str:
    """Format a possibly-missing number for the console."""
    if value is None:
        return "N/A"
    try:
        fvalue = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if not np.isfinite(fvalue):
        return "N/A"
    return fmt.format(fvalue)


# The significance level the reported resolution is stated at: the threshold a
# "deflated p < 0.10" style criterion uses.
TEST_RESOLUTION_TARGET_P_VALUE = 0.10

# Plausibility bounds used to flag a significance criterion as beyond the
# sample's resolution. These are ASSUMPTIONS, not results: they are declared
# here, reported in every `test_resolution` block and printed with the
# verdict, so a reader can dispute them. An annualized Sharpe above 2.0 or an
# annualized alpha above 10% would itself be extraordinary for a liquid
# equity strategy (in practice a sign of a bug or a data problem rather than
# of skill), so a criterion that requires more than this cannot discriminate
# between hypotheses at the sample size actually available: its outcome is a
# statement about the sample, not about the strategy.
#
# They never change a verdict and they never change a reported number.
PLAUSIBLE_MAX_ANNUALIZED_SHARPE = 2.0
PLAUSIBLE_MAX_ANNUALIZED_ALPHA = 0.10


def _build_test_resolution(
    summary: Dict[str, Any],
    returns: Optional[pd.Series],
    target_p_value: float = TEST_RESOLUTION_TARGET_P_VALUE,
) -> Dict[str, Any]:
    """Minimum detectable effect of a summary's significance statistics.

    A significance test on a small sample can only fail: with T observations
    the threshold "deflated p < 0.10" requires the effect to exceed a certain
    size. This helper reports that size for the aggregate Deflated Sharpe and
    Deflated Alpha statistics carried by an analysis summary, so a reader of
    ``out_of_sample_summary.json`` (or of the console) can tell an
    informative result from an unfalsifiable one.

    The numbers are measurements, not corrections: no verdict, no p-value and
    no other reported number is changed here.

    Args:
        summary: An analysis summary carrying ``deflated_sharpe`` and/or
            ``deflated_alpha`` (as produced by the walk-forward, CPCV and
            out-of-sample paths).
        returns: The per-period return series the statistic was computed on.
            When it does not match the statistic's observation count the
            resolution is reported as "not resolvable", never as a number.
        target_p_value: The p-value threshold the criterion uses.

    Returns:
        The ``test_resolution`` block: the sample size the statistics were
        computed on, the number of parameter trials and benchmarks behind
        them, the smallest annualized Sharpe / alpha each statistic could
        confirm, the plausibility bounds used to judge those, and the reason
        a statistic could not be resolved when that is the case.
    """
    resolution: Dict[str, Any] = {
        "n_test_observations": None,
        "n_parameter_trials": None,
        "n_benchmarks": None,
        "target_p_value": float(target_p_value),
        "min_detectable_sharpe": None,
        "min_detectable_alpha": None,
        "observed_annualized_sharpe": None,
        "observed_annualized_alpha": None,
        # "resolvable": the minimum detectable effect was computed.
        # "not_resolvable": the statistic exists but the effect could not be
        #   computed (see the matching `*_reason`).
        # "not_applicable": the statistic itself does not exist for this run
        #   (no deflation requested, or no benchmark set to correct).
        "sharpe_status": "not_applicable",
        "alpha_status": "not_applicable",
        "sharpe_reason": None,
        "alpha_reason": None,
        "sharpe_beyond_plausible_bound": False,
        "alpha_beyond_plausible_bound": False,
        "plausible_max_annualized_sharpe": PLAUSIBLE_MAX_ANNUALIZED_SHARPE,
        "plausible_max_annualized_alpha": PLAUSIBLE_MAX_ANNUALIZED_ALPHA,
        "message": "",
    }

    deflated_sharpe = summary.get("deflated_sharpe")
    deflated_alpha = summary.get("deflated_alpha")

    if isinstance(deflated_sharpe, dict):
        resolution["n_test_observations"] = deflated_sharpe.get("n_observations")
        resolution["n_parameter_trials"] = deflated_sharpe.get("n_trials")
        resolution["observed_annualized_sharpe"] = deflated_sharpe.get("sharpe_ratio")
        try:
            mde = minimum_detectable_sharpe(deflated_sharpe, returns, target_p_value)
        except Exception as exc:  # pragma: no cover - defensive
            mde = {"attainable": False, "reason": f"error:{type(exc).__name__}"}
        if mde.get("attainable"):
            resolution["sharpe_status"] = "resolvable"
            value = mde.get("minimum_detectable_sharpe")
            resolution["min_detectable_sharpe"] = (
                float(value) if value is not None and np.isfinite(float(value)) else None
            )
            if resolution["min_detectable_sharpe"] is not None:
                resolution["sharpe_beyond_plausible_bound"] = bool(
                    resolution["min_detectable_sharpe"] > PLAUSIBLE_MAX_ANNUALIZED_SHARPE
                )
        else:
            resolution["sharpe_status"] = "not_resolvable"
            resolution["sharpe_reason"] = mde.get("reason")
    elif deflated_sharpe is not None:
        resolution["sharpe_status"] = "not_resolvable"
        resolution["sharpe_reason"] = "no_deflated_sharpe"

    if isinstance(deflated_alpha, dict):
        if resolution["n_test_observations"] is None:
            resolution["n_test_observations"] = deflated_alpha.get("n_observations")
        resolution["n_benchmarks"] = deflated_alpha.get("n_benchmarks")
        resolution["observed_annualized_alpha"] = deflated_alpha.get("alpha")
        try:
            mde = minimum_detectable_alpha(deflated_alpha, returns, target_p_value)
        except Exception as exc:  # pragma: no cover - defensive
            mde = {"attainable": False, "reason": f"error:{type(exc).__name__}"}
        if mde.get("attainable"):
            resolution["alpha_status"] = "resolvable"
            value = mde.get("minimum_detectable_alpha")
            resolution["min_detectable_alpha"] = (
                float(value) if value is not None and np.isfinite(float(value)) else None
            )
            if resolution["min_detectable_alpha"] is not None:
                resolution["alpha_beyond_plausible_bound"] = bool(
                    resolution["min_detectable_alpha"] > PLAUSIBLE_MAX_ANNUALIZED_ALPHA
                )
        else:
            resolution["alpha_status"] = "not_resolvable"
            resolution["alpha_reason"] = mde.get("reason")
    elif deflated_alpha is not None:
        resolution["alpha_status"] = "not_resolvable"
        resolution["alpha_reason"] = "no_deflated_alpha"

    resolution["message"] = _test_resolution_message(resolution)
    return resolution


def _test_resolution_message(resolution: Dict[str, Any]) -> str:
    """One plain-English sentence describing a test-resolution block.

    The artifact carries the same message the console prints, so the two
    never disagree.
    """
    n_obs = resolution.get("n_test_observations")
    trials = resolution.get("n_parameter_trials")
    if n_obs is None and trials is None:
        return (
            "No significance test was run on this record, so there is no "
            "test resolution to report."
        )

    parts = []
    if n_obs is not None:
        parts.append(f"{n_obs} test observation(s)")
    if trials is not None:
        parts.append(f"{trials} parameter trial(s)")
    scope = ", ".join(parts) if parts else "this record"

    sentences = []
    if resolution.get("sharpe_status") == "resolvable":
        sentences.append(
            "the Deflated Sharpe test can only confirm an annualized Sharpe "
            f"of at least {_format_optional_float(resolution.get('min_detectable_sharpe'))} "
            f"(observed "
            f"{_format_optional_float(resolution.get('observed_annualized_sharpe'))})"
        )
    elif resolution.get("sharpe_status") == "not_resolvable":
        sentences.append(
            "the Deflated Sharpe test resolution is not computable "
            f"({resolution.get('sharpe_reason')})"
        )
    if resolution.get("alpha_status") == "resolvable":
        sentences.append(
            "the Deflated Alpha test can only confirm an annualized alpha of "
            f"at least {_format_optional_float(resolution.get('min_detectable_alpha'), '{:.2%}')} "
            f"(observed "
            f"{_format_optional_float(resolution.get('observed_annualized_alpha'), '{:.2%}')})"
        )
    elif resolution.get("alpha_status") == "not_resolvable":
        sentences.append(
            "the Deflated Alpha test resolution is not computable "
            f"({resolution.get('alpha_reason')})"
        )

    beyond = []
    if resolution.get("sharpe_beyond_plausible_bound"):
        beyond.append("Deflated Sharpe")
    if resolution.get("alpha_beyond_plausible_bound"):
        beyond.append("Deflated Alpha")

    message = f"With {scope}: " + "; ".join(sentences) + "."
    if beyond:
        message += (
            " The "
            + " and ".join(beyond)
            + " threshold(s) exceed the stated plausibility bound, so at this "
            "sample size their outcome measures the sample, not the strategy."
        )
    return message


def _calculate_strategy_returns(
    data: Union[pd.DataFrame, dict],
    signals: pd.Series,
    commission: float,
    slippage: float,
    impact_coefficient: float = 0.0,
    adv_window: int = 20,
    borrow_cost: float = 0.0,
    funding_cost: float = 0.0,
    latency: int = 0,
    fill_rate: float = 1.0,
    initial_capital: float = 100000.0,
    panel_pricing: str = "net-exposure",
    book_weights: Optional[pd.DataFrame] = None,
    impact_aggregation=DEFAULT_IMPACT_AGGREGATION,
) -> pd.Series:
    """Calculate strategy returns from signals and market data.

    Args:
        data: OHLCV data (DataFrame, MultiIndex panel, or dict of DataFrames)
        signals: Position signals (1=long, -1=short, 0=flat)
        commission: Commission rate per trade (as decimal, e.g., 0.0002 = 2 bps)
        slippage: Slippage rate per trade (as decimal)
        impact_coefficient: Market impact coefficient. Market impact is modeled as
            (position_notional / ADV) * impact_coefficient, where ADV is the
            average daily volume over `adv_window` periods. Set to 0 to disable.
            Typical values: 0.1-1.0 for linear impact models.
        adv_window: Rolling window for Average Daily Volume calculation. Default 20.
        borrow_cost: Annual borrow cost rate for short positions (as decimal,
            e.g., 0.03 = 3% per year). Applied per period on short exposure;
            the per-period rate is borrow_cost divided by the periods per
            year inferred from the data's index (252 for business-daily,
            52 for weekly, etc.).
        funding_cost: Annual funding cost rate for leveraged positions (as
            decimal, e.g., 0.02 = 2% per year). Applied per period on gross
            exposure exceeding 1x; the per-period rate is funding_cost
            divided by the periods per year inferred from the data's index.
        latency: Execution latency in periods. Positions are delayed by
            `1 + latency` periods after signal generation (1 = trade at next
            period's open, the default look-ahead-safe convention).
            Negative values are clamped to 0 to prevent accidental look-ahead.
        fill_rate: Position-scale limit (participation rate) in (0, 1]. The
            achieved position is ``fill_rate * target_position`` on every bar,
            so every position-change-based cost (commission, slippage, market
            impact) and every exposure-based cost (borrow, funding) scales
            with it. Default 1.0 (full fill, backward compatible).

            This is a *position-size (leverage) lever*, not a partial-fill
            execution model: the held position is reset to ``fill_rate *
            target`` each bar instead of converging toward the target
            (``position_t = position_{t-1} + fill_rate * (target_t -
            position_{t-1})``), and the unfilled part of the order is not
            charged anything. Sweeping ``fill_rate`` therefore measures
            leverage sensitivity, not execution realism -- the Sharpe ratio is
            not scale-invariant because the risk-free rate is subtracted from
            the scaled return and is not scaled with it. See
            `references/validation_methods.md`, "Fill rate: decided convention".
            in (0, 1]. Scales achieved positions and all position-change-based
            costs (commission, slippage, impact) and borrow/funding exposure.
            Default 1.0 (full fill) is bitwise identical to no fill modeling.
        initial_capital: Starting portfolio value used to scale the position
            notional for market-impact calculation. The notional at risk is
            |position_change| * equity, where equity is approximated by
            initial_capital * cumprod(1 + raw_returns). Default 100000.
        panel_pricing: "net-exposure" (the default) prices the portfolio as
            `net_exposure x mean(asset returns)` and charges the costs on the
            net exposure; "book" prices the true per-asset book return
            `sum_i w_i r_i` and charges the costs on the book itself (gross
            turnover, short legs, gross exposure, per-asset market impact).
        book_weights: the per-asset target book of the strategy on `data`
            (rows = dates, columns = symbols). Required for the "book"
            pricing mode; ignored otherwise.
        impact_aggregation: ``"panel"`` (the default) charges the equal-weighted
            mean of the per-asset impact rates; ``"notional-weighted"``
            charges the dollar-consistent aggregation. Default ``"panel"``
            keeps every published number unchanged.
    """
    if fill_rate is None:
        fill_rate = 1.0
    if fill_rate <= 0 or fill_rate > 1:
        raise ValueError(f"fill_rate must be in (0, 1], got {fill_rate}")
    if latency is None:
        latency = 0
    if latency < 0:
        latency = 0
    panel_pricing = resolve_panel_pricing(panel_pricing)
    # Shared market model: the single definition of how a single asset, a
    # MultiIndex panel and a dict panel are priced. It is shared with
    # run_backtest.py so the two entry points return comparable results for
    # the same panel (see references/cost_models.md, "Cross-path parity").
    market = build_market_model(data)
    raw_returns = market["raw_returns"]
    close = market["close"]
    volume = market["volume"]
    is_panel = market["is_panel"]

    # Execution warmup: intentional two-bar warmup (see validation_methods.md,
    # "The Warmup Bars of a Window"). shift(1 + latency) leaves the first
    # `1 + latency` position undefined and positions.diff() is undefined on
    # the following bar, so both bars are non-tradable and dropped. The
    # constant is shared with run_backtest.py through utils.py so the
    # convention has a single definition.
    positions = signals.shift(1 + latency) * fill_rate  # Trade at next period's open, delayed by execution latency; the achieved position is fill_rate * target (a position-scale limit, not a partial-fill model)

    # Borrow and funding costs are annualized rates applied per period.
    # The per-period rate divides by the number of periods per year inferred
    # from the data's index (e.g. 252 for business-daily, 365 for
    # calendar-daily, 52 for weekly, 12 for monthly), matching the
    # annualization used for the strategy's own return metrics. Falls back
    # to 252 when the frequency cannot be inferred.
    ann_factor = _annualization_factor(raw_returns.index)

    # The book actually held, when the run prices the panel as a book. It is
    # the single source of truth for the book-mode return AND the book-mode
    # cost basis.
    held_book = None
    if panel_pricing == "book" and book_weights is not None:
        held_book = held_book_weights(
            book_weights,
            market,
            lag=1 + latency,
            fill_rate=fill_rate,
            # The net-exposure path of this module uses a NaN warmup
            # (`positions = signals.shift(...)` without a fill), so the
            # first defined position is entered for free and its bar is
            # dropped from the return series. A NaN-warmup book reproduces
            # exactly that treatment, so the two pricing modes report the
            # same bars.
            warmup="nan",
        )

    if held_book is not None:
        # Book cost basis: the costs are charged on the book the strategy
        # actually holds, not on the scalar net exposure.
        #
        #   commission + slippage  on the gross turnover sum_i |dw_i|
        #   borrow                 on the short legs sum_i max(-w_i, 0)
        #   funding                on the gross exposure sum_i |w_i| > 1x
        #   market impact          per asset, against that asset's own ADV
        _book_costs = book_cost_components(
            held_book,
            commission=commission,
            slippage=slippage,
            borrow_cost=borrow_cost,
            funding_cost=funding_cost,
            ann_factor=ann_factor,
        )
        costs = _book_costs["total"]
        market_impact = book_market_impact_cost(
            held_book=held_book,
            raw_returns=raw_returns,
            close=close,
            volume=volume,
            impact_coefficient=impact_coefficient,
            adv_window=adv_window,
            initial_capital=initial_capital,
            impact_aggregation=impact_aggregation,
        )
        if market_impact is not None:
            costs = costs + market_impact
    else:
        # Transaction costs: apply on position changes. The first
        # EXECUTION_WARMUP_BARS bars are explicitly non-tradable (see above),
        # so their cost is NaN rather than an emergent property of NaN
        # propagation through the cost term.
        position_changes = positions.diff().abs()
        position_changes.iloc[:EXECUTION_WARMUP_BARS] = float("nan")
        costs = position_changes * (commission + slippage)

        # Market impact model: impact = (position_notional / ADV) * impact_coefficient
        # Position notional = |position| * equity, where equity is the current
        # portfolio value.  Since this function only sees returns (not equity),
        # equity is approximated by initial_capital * cumprod(1 + raw_returns),
        # i.e. the value of a fully-invested buy-and-hold position in the asset
        # at the current price.  This is the correct scaling: the original
        # implementation multiplied by the raw asset price (~$100), understating
        # the notional by ~1000x and making impact_coefficient a silent no-op.
        # ADV = rolling average of daily volume (in shares) * price
        #
        # The model itself lives in utils.market_impact_cost so that this path
        # and run_backtest.py charge the same impact for the same panel.
        market_impact = market_impact_cost(
            position_changes=position_changes,
            raw_returns=raw_returns,
            close=close,
            volume=volume,
            is_panel=is_panel,
            impact_coefficient=impact_coefficient,
            adv_window=adv_window,
            initial_capital=initial_capital,
            impact_aggregation=impact_aggregation,
        )
        if market_impact is not None:
            costs = costs + market_impact

        # Borrow cost for short positions
        # Applied per period on the absolute value of short positions
        if borrow_cost > 0:
            # Convert annual rate to per-period rate
            period_borrow_rate = borrow_cost / ann_factor
            # Short positions are negative; borrow cost applies to absolute short exposure
            short_positions = positions.clip(upper=0).abs()
            borrow_costs = short_positions * period_borrow_rate
            costs = costs + borrow_costs

        # Funding cost for leveraged positions (gross exposure > 1)
        # Applied per period on the amount of leverage used beyond 100% equity
        if funding_cost > 0:
            # Convert annual rate to per-period rate
            period_funding_rate = funding_cost / ann_factor
            # Gross leverage = absolute position size
            gross_exposure = positions.abs()
            # Funding cost applies to leverage beyond 1x (i.e., gross_exposure - 1 when > 1)
            leverage_excess = (gross_exposure - 1).clip(lower=0)
            funding_costs = leverage_excess * period_funding_rate
            costs = costs + funding_costs

    # Portfolio return. Two pricing conventions:
    #
    #   net-exposure (default): `positions x mean(asset returns)`.
    #   book: `sum_i w_i r_i` -- the true P&L of the per-asset book.
    #
    # The two modes also differ in their *cost* basis: the net-exposure
    # mode charges the scalar net exposure, the book mode charges the book
    # (gross turnover, short legs, gross exposure). When the "book" mode is
    # requested but no book is available, the net-exposure pricing is used.
    book_returns = None
    if held_book is not None:
        book_returns = book_return_from_held(held_book, close)
    if book_returns is not None:
        strategy_returns = book_returns - costs
        # Report the same bars as the net-exposure convention: the bars
        # where the position series is undefined (the execution warmup)
        # are not tradable and are dropped by both conventions.
        strategy_returns = strategy_returns.reindex(positions.dropna().index)
    else:
        strategy_returns = positions * raw_returns - costs
    return strategy_returns.dropna()


def estimate_capacity(
    data: pd.DataFrame,
    impact_coefficient: float,
    max_impact: float = 0.0005,
    adv_window: int = 20,
) -> Dict[str, Any]:
    """
    Estimate strategy capacity from the market-impact cost model.

    Market impact of trading notional ``N`` is:
        impact = (N / ADV_notional) * impact_coefficient
    Solving for the maximum tradable notional at a target impact gives the
    per-trade capacity:
        capacity_notional = max_impact * ADV_notional / impact_coefficient

    A strategy that rebalances its full position each period can therefore
    hold roughly ``capacity_notional`` of notional exposure without exceeding
    ``max_impact`` per trade. Capacity scales inversely with the impact
    coefficient and directly with the target impact and average daily volume.

    Multi-asset panels (MultiIndex columns) are treated as an equal-weighted
    basket: each of the ``n_assets`` constituents carries ``1 / n_assets`` of
    the portfolio notional, so the *least liquid* constituent sets the
    portfolio capacity:

        capacity = n_assets * max_impact * min_i(ADV_notional_i) / impact_coefficient

    This is the binding constraint: a basket can only grow until its least
    liquid member exceeds the impact threshold. For a panel the reported
    ``price`` / ``adv_shares`` / ``adv_notional`` describe that binding
    (least liquid) member, and ``binding_asset`` / ``n_assets`` identify it.

    The point-in-time estimate above reads the ADV of the *last* bar of the
    window, so a liquidity squeeze that happened earlier in the window is
    hidden. The ``capacity_trend`` key therefore reports the distribution of
    the per-period capacity readings across the whole window (min / median /
    max plus the ratios of the extremes to the median). It is ``None`` when
    impact is disabled or ADV is not estimable, exactly like
    ``estimated_capacity``.

    Args:
        data: OHLCV DataFrame (must contain ``close`` and ``volume``). For a
            multi-asset panel the columns are a MultiIndex whose levels carry
            the field names and the symbols (either order is accepted).
        impact_coefficient: Linear market-impact coefficient. A value of 0
            means impact is disabled and capacity is unconstrained.
        max_impact: Maximum acceptable market impact per trade, as a fraction
            of notional traded (default 0.0005 = 5 bps).
        adv_window: Rolling window (in periods) for the ADV calculation.

    Returns:
        Dictionary with keys: impact_coefficient, max_impact, adv_window,
        price, adv_shares, adv_notional, periods_per_year,
        max_notional_per_trade, estimated_capacity, unconstrained, estimable,
        n_assets, binding_asset, capacity_trend.
        ``unconstrained`` is True when impact is disabled. ``estimable`` is
        False when ADV cannot be computed (missing columns or empty data).
        ``capacity_trend`` describes the per-period capacity distribution
        inside the window (see ``_capacity_trend_from_series``); it is None
        when impact is disabled or ADV is not estimable.
    """
    result = {
        "impact_coefficient": float(impact_coefficient),
        "max_impact": float(max_impact),
        "adv_window": int(adv_window),
        "price": None,
        "adv_shares": None,
        "adv_notional": None,
        "periods_per_year": None,
        "max_notional_per_trade": None,
        "estimated_capacity": None,
        "unconstrained": False,
        "estimable": False,
        "n_assets": None,
        "binding_asset": None,
        "capacity_trend": None,
    }

    if impact_coefficient <= 0:
        result["unconstrained"] = True
        return result

    is_panel = isinstance(data.columns, pd.MultiIndex)
    if is_panel:
        # Panel columns are a MultiIndex; the field names ("close",
        # "volume") live on one of the two levels. Accept either ordering.
        level0 = set(data.columns.get_level_values(0))
        level1 = set(data.columns.get_level_values(1))
        if {"close", "volume"} <= level0:
            close = data["close"]
            volume = data["volume"]
        elif {"close", "volume"} <= level1:
            close = data.xs("close", axis=1, level=1)
            volume = data.xs("volume", axis=1, level=1)
        else:
            return result
    else:
        if "close" not in data.columns or "volume" not in data.columns:
            return result
        close = data["close"]
        volume = data["volume"]

    if len(close) == 0 or len(volume) == 0:
        return result

    ann_factor = _annualization_factor(data.index)
    adv_shares = volume.rolling(window=adv_window, min_periods=1).mean()
    adv_notional = adv_shares * close

    if is_panel:
        # Equal-weighted basket: every asset carries 1/n_assets of the
        # portfolio notional, so the least liquid asset binds the portfolio
        # capacity (per-asset capacity x n_assets).
        adv_notional_last = adv_notional.iloc[-1]
        if not isinstance(adv_notional_last, pd.Series):
            adv_notional_last = pd.Series([adv_notional_last])
        valid = adv_notional_last[
            np.isfinite(adv_notional_last) & (adv_notional_last > 0)
        ]
        if len(valid) == 0:
            return result

        n_assets = int(len(close.columns))
        binding_asset = valid.idxmin()
        binding_adv_notional = float(valid.min())
        binding_adv_shares = float(adv_shares.iloc[-1][binding_asset])
        binding_price = float(close.iloc[-1][binding_asset])
        per_asset_capacity = (
            max_impact * binding_adv_notional / float(impact_coefficient)
        )
        portfolio_capacity = n_assets * per_asset_capacity

        # Capacity trend: the per-period portfolio capacity series, so a
        # liquidity squeeze *inside* the window is visible instead of being
        # hidden behind the last bar's reading. Each period's portfolio
        # capacity binds on that period's least liquid constituent.
        _valid_adv_notional = adv_notional.where(
            np.isfinite(adv_notional) & (adv_notional > 0)
        )
        _row_min_adv = _valid_adv_notional.min(axis=1, skipna=True)
        _capacity_series = (
            n_assets * max_impact * _row_min_adv / float(impact_coefficient)
        )

        result.update(
            price=binding_price,
            adv_shares=binding_adv_shares,
            adv_notional=binding_adv_notional,
            periods_per_year=float(ann_factor),
            max_notional_per_trade=float(portfolio_capacity),
            estimated_capacity=float(portfolio_capacity),
            estimable=True,
            n_assets=n_assets,
            binding_asset=str(binding_asset),
            capacity_trend=_capacity_trend_from_series(
                _capacity_series, float(portfolio_capacity)
            ),
        )
        return result

    price = float(close.iloc[-1])
    last_adv_notional = float(adv_notional.iloc[-1])

    if not np.isfinite(last_adv_notional) or last_adv_notional <= 0:
        return result

    max_notional_per_trade = max_impact * last_adv_notional / float(impact_coefficient)

    # Capacity trend: the per-period capacity series across the window.
    _valid_adv = adv_notional.where(
        np.isfinite(adv_notional) & (adv_notional > 0)
    )
    _capacity_series = max_impact * _valid_adv / float(impact_coefficient)

    result.update(
        price=price,
        adv_shares=float(adv_shares.iloc[-1]),
        adv_notional=last_adv_notional,
        periods_per_year=float(ann_factor),
        max_notional_per_trade=float(max_notional_per_trade),
        estimated_capacity=float(max_notional_per_trade),
        estimable=True,
        n_assets=1,
        capacity_trend=_capacity_trend_from_series(
            _capacity_series, float(max_notional_per_trade)
        ),
    )
    return result


def _window_held_book(
    strategy_factory: Callable,
    best_params: Optional[Dict[str, Any]],
    window_data,
    latency: int = 0,
    fill_rate: float = 1.0,
):
    """The book the selected strategy holds in one window, and its market.

    The held book is the target book lagged by the execution convention
    (``lag = 1 + latency``) and scaled by the fill rate -- the same
    convention the framework's position series uses, and the same one the
    book diagnostic and the book cost model measure.

    Returns ``(held_book, market)``, or ``(None, None)`` when the window
    has no usable book (no selected parameters, a strategy that exposes no
    weights, a non-panel market, or a book over a different universe).
    """
    if best_params is None or window_data is None:
        return None, None

    strategy = strategy_factory(best_params)
    weights = strategy_target_weights(strategy, window_data)
    if weights is None:
        return None, None

    market = build_market_model(window_data)
    held = held_book_weights(
        weights, market, lag=1 + latency, fill_rate=fill_rate
    )
    if held is None:
        return None, None
    return held, market


def _window_book_capacity(
    strategy_factory: Callable,
    best_params: Optional[Dict[str, Any]],
    window_data,
    impact_coefficient: float,
    adv_window: int = 20,
    latency: int = 0,
    fill_rate: float = 1.0,
    max_impact: float = 0.0005,
    impact_aggregation=DEFAULT_IMPACT_AGGREGATION,
) -> Optional[Dict[str, Any]]:
    """The capacity implied by the book's own rebalance pattern in a window.

    The basket rule assumes an equal-weight basket that rebalances
    ``1 / n_assets`` per constituent; the book-based estimate uses the trade
    sizes the strategy actually executes, so a concentrated book reports a
    lower capacity than the basket rule. See
    :func:`utils.book_capacity_estimate`.

    Two book-based capacities are returned: the "|dw|" rule (the capacity
    consistent with the panel impact charge) and the "notional-weighted"
    ("dw^2") rule (the capacity consistent with the dollar-consistent
    impact charge).

    Returns ``None`` when the window has no book, when the panel carries no
    volume, or when impact is disabled.
    """
    held, market = _window_held_book(
        strategy_factory,
        best_params,
        window_data,
        latency=latency,
        fill_rate=fill_rate,
    )
    if held is None:
        return None
    volume = market.get("volume")
    if volume is None:
        return None
    return book_capacity_estimate(
        held,
        market["close"],
        volume,
        impact_coefficient=impact_coefficient,
        max_impact=max_impact,
        adv_window=adv_window,
        impact_aggregation=impact_aggregation,
    )


def _merge_capacity_series(series_list: List[Any]) -> Optional[pd.Series]:
    """Merge per-window capacity series into one chronological series.

    Each window's series is computed inside its own window, so merging them
    creates no artificial trade at a window boundary (a boundary trade would
    otherwise show up as a capacity reading the strategy never faced).
    Windows that overlap are de-duplicated by timestamp, keeping the last
    reading of each timestamp.

    Args:
        series_list: per-window capacity series (``None`` entries ignored).

    Returns:
        The merged series, or ``None`` when no window produced a series.
    """
    parts = [
        s for s in (series_list or [])
        if s is not None and len(s) > 0
    ]
    if not parts:
        return None
    merged = pd.concat(parts)
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    return merged


def _window_book_diagnostic(
    strategy_factory: Callable,
    best_params: Optional[Dict[str, Any]],
    window_data,
    framework_returns,
    latency: int = 0,
    fill_rate: float = 1.0,
    panel_pricing: str = "net-exposure",
    impact_coefficient: float = 0.0,
    adv_window: int = 20,
    initial_capital: float = 100000.0,
    impact_aggregation=DEFAULT_IMPACT_AGGREGATION,
) -> Optional[Dict[str, Any]]:
    """Panel book diagnostic for one validation window.

    The panel path prices a portfolio as ``net_exposure x mean(asset
    returns)`` -- one scalar per period -- so a strategy that holds a
    long/short book cannot be represented by that scalar. This measures the
    book the selected strategy actually holds in the window against the
    framework's pricing of the same window.

    Measurement only: no return, cost, impact or capacity number is
    changed. Returns ``None`` when the strategy exposes no book, when the
    window produced no returns, or when the panel has no per-asset data.
    """
    if best_params is None or window_data is None:
        return None
    if framework_returns is None or len(framework_returns) == 0:
        return None

    strategy = strategy_factory(best_params)
    weights = strategy_target_weights(strategy, window_data)
    if weights is None:
        return None

    signals = strategy.generate_signals(window_data)
    market = build_market_model(window_data)
    # Same position convention as `_calculate_strategy_returns`: the signal
    # is executed with a one-period delay (plus the execution latency) and
    # scaled by the fill rate.
    positions = signals.shift(1 + latency) * fill_rate
    return compute_book_diagnostic(
        weights,
        market,
        positions=positions,
        framework_returns=framework_returns,
        lag=1 + latency,
        fill_rate=fill_rate,
        pricing_mode=panel_pricing,
        impact_coefficient=impact_coefficient,
        adv_window=adv_window,
        initial_capital=initial_capital,
        impact_aggregation=impact_aggregation,
    )


def _aggregate_oos_capacity(
    trends: List[Any],
) -> Optional[float]:
    """Minimum per-window capacity across the out-of-sample windows.

    ``trends`` is a list of per-regime ``capacity_trend`` dicts (one per
    walk-forward period / CPCV fold). The result is the worst capacity the
    strategy faced inside any of the out-of-sample windows it was actually
    traded in, i.e. the liquidity level that really bound the strategy
    rather than the level of the last bar of the sample.

    None when no window produced a capacity trend (impact disabled or ADV
    not estimable).
    """
    values: List[float] = []
    for trend in trends or []:
        if not isinstance(trend, dict):
            continue
        value = trend.get("min_capacity")
        if value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(value):
            values.append(value)
    if not values:
        return None
    return float(min(values))


def _calculate_walk_forward_summary(
    oos_returns: pd.Series,
    periods: List[Dict[str, Any]],
    periods_with_position: int = 0,
) -> Dict[str, Any]:
    """Calculate summary metrics for walk-forward results."""
    summary = {
        "n_periods": len(periods),
        "periods_with_position": int(periods_with_position),
        "total_oos_return": None if len(oos_returns) == 0 else float((1 + oos_returns).prod() - 1),
    }

    if len(oos_returns) > 1:
        ann_factor = _annualization_factor(oos_returns.index)
        excess = oos_returns - 0.02 / ann_factor
        if not _is_constant_returns(oos_returns):
            summary["oos_sharpe"] = float(excess.mean() / oos_returns.std() * np.sqrt(ann_factor))
            summary["oos_volatility"] = float(oos_returns.std() * np.sqrt(ann_factor))
        else:
            summary["oos_sharpe"] = 0.0
            summary["oos_volatility"] = 0.0

        summary["avg_period_return"] = float(oos_returns.mean())
        summary["n_positive_periods"] = int((oos_returns > 0).sum())
        summary["win_rate_periods"] = float((oos_returns > 0).sum() / len(oos_returns)) if len(oos_returns) > 0 else 0.0

    return summary


def cpcv_analysis(
    data: Union[pd.DataFrame, dict],
    strategy_factory: Callable,
    param_grid: Dict[str, List[Any]],
    n_splits: int = 10,
    test_size: float = 0.1,
    purge_size: float = 0.0,
    embargo_size: float = 0.0,
    initial_capital: float = 100000,
    commission: float = 0.0002,
    slippage: float = 0.0001,
    impact_coefficient: float = 0.0,
    adv_window: int = 20,
    borrow_cost: float = 0.0,
    funding_cost: float = 0.0,
    latency: int = 0,
    fill_rate: float = 1.0,
    apply_deflation: bool = False,
    benchmark: Optional[pd.DataFrame] = None,
    total_return_benchmark: bool = False,
    benchmark_commission: float = 0.0,
    benchmark_slippage: float = 0.0,
    benchmark_expense_ratio: float = 0.0,
    benchmark_cost_is_periodic: bool = False,
    validate_pit: bool = True,
    panel_pricing: str = "net-exposure",
    impact_aggregation=DEFAULT_IMPACT_AGGREGATION,
    **kwargs,
) -> Dict[str, Any]:
    """
    Perform Combinatorially Purged Cross-Validation (CPCV).

    CPCV addresses look-ahead bias and multiple-testing issues by:
    1. Splitting data into n_splits sequential groups
    2. For each fold, using n_splits-1 groups for training, 1 group for testing
    3. Purging (removing) observations around test set from training to prevent
       look-ahead bias (e.g., due to overlapping rolling windows)
    4. Adding embargo period after test set to prevent contamination

    Args:
        data: DataFrame with OHLCV data indexed by date
        strategy_factory: Function that creates a strategy from params dict
        param_grid: Dictionary of parameter name -> list of values to search
        n_splits: Number of sequential groups to split data into
        test_size: Fraction of each group to use as test set (within the group)
        purge_size: Fraction of observations to purge from training around test
        embargo_size: Fraction of observations to embargo after test set
        initial_capital: Starting portfolio value
        commission: Commission rate per trade
        slippage: Slippage rate per trade
        impact_coefficient: Market impact coefficient. Market impact is modeled as
            (position_notional / ADV) * impact_coefficient, where ADV is the
            average daily volume over `adv_window` periods. Set to 0 to disable.
        adv_window: Rolling window for Average Daily Volume calculation. Default 20.
        borrow_cost: Annual borrow cost rate for short positions (as decimal,
            e.g., 0.03 = 3% per year). Applied daily on short exposure.
        funding_cost: Annual funding cost rate for leveraged positions (as decimal,
            e.g., 0.02 = 2% per year). Applied daily on gross exposure exceeding 1x.
        latency: Execution latency in periods passed to _calculate_strategy_returns.
            Positions are delayed by `1 + latency` periods after signal generation.
            Default 0 (no added delay beyond the standard next-period fill).
        fill_rate: Position-scale limit (participation rate) in (0, 1]. The
            achieved position is ``fill_rate * target_position`` on every bar,
            so every position-change-based cost (commission, slippage, market
            impact) and every exposure-based cost (borrow, funding) scales
            with it. Default 1.0 (full fill, backward compatible).

            This is a *position-size (leverage) lever*, not a partial-fill
            execution model: the held position is reset to ``fill_rate *
            target`` each bar instead of converging toward the target
            (``position_t = position_{t-1} + fill_rate * (target_t -
            position_{t-1})``), and the unfilled part of the order is not
            charged anything. Sweeping ``fill_rate`` therefore measures
            leverage sensitivity, not execution realism -- the Sharpe ratio is
            not scale-invariant because the risk-free rate is subtracted from
            the scaled return and is not scaled with it. See
            `references/validation_methods.md`, "Fill rate: decided convention".
            passed to _calculate_strategy_returns. Default 1.0 (full fill).
        apply_deflation: When True, compute the Deflated Sharpe Ratio
            (multiple-testing correction) for each fold's in-sample
            parameter selection, plus an aggregate correction on the
            combined out-of-sample returns with n_trials equal to the
             total number of configurations evaluated across all folds.
        benchmark: Optional benchmark OHLCV DataFrame for buy-and-hold comparison
        total_return_benchmark: If True, compute benchmark returns using total return
            (dividends + price) when dividend/adj_close data is available
        benchmark_commission: Commission per trade for benchmark (as decimal)
        benchmark_slippage: Slippage per trade for benchmark (as decimal)
        benchmark_expense_ratio: Annual expense ratio for benchmark (as decimal, e.g., 0.005 for 0.5%)
        validate_pit: When True, run point-in-time validation (look-ahead /
            stale-data / temporal-ordering screening) on the input data and
            record the result in `results["point_in_time_validation"]` and
            `summary["bias_controls_engaged"]`. Default True on the programmatic
            API; default True (CLI parity, non-strict: warns, never aborts).

    Returns:
        Dictionary with CPCV results including:
            - 'folds': list of fold results
            - 'best_params_per_fold': list of optimal params per fold
            - 'oos_returns': out-of-sample returns across all folds
            - 'summary': aggregate metrics
            - 'param_stability': parameter stability across folds
    """
    # Fail fast on invalid execution-realism parameters rather than silently
    # skipping every grid combination inside the per-combo try/except below.
    if fill_rate is None:
        fill_rate = 1.0
    if fill_rate <= 0 or fill_rate > 1:
        raise ValueError(f"fill_rate must be in (0, 1], got {fill_rate}")
    if latency is None:
        latency = 0
    if latency < 0:
        latency = 0
    panel_pricing = resolve_panel_pricing(panel_pricing)

    if isinstance(data, dict):
        # Normalize dict panel data (symbol -> OHLCV DataFrame) to a
        # MultiIndex (field, symbol) panel. Strategies and return
        # calculators produce identical results for both multi-asset
        # formats, so the DataFrame code paths below handle either.
        data = _dict_to_multiindex(data)

    if isinstance(data.columns, pd.MultiIndex):
        if not isinstance(data.index, pd.DatetimeIndex):
            try:
                data.index = pd.DatetimeIndex(data.index)
            except Exception:
                pass
        data = data.sort_index()
    else:
        if not isinstance(data.index, pd.DatetimeIndex):
            raise ValueError("Data must be indexed by DatetimeIndex")
        data = data.sort_index()

    # Point-in-time validation (look-ahead / stale-data / temporal-ordering
    # screening). Opt-in on the programmatic API; the CLI engages it via
    # _load_and_validate_data (validate_pit=True by default).
    pit_results = None
    if validate_pit:
        pit_results = validate_point_in_time(data)
        if pit_results["violations"]:
            print("Point-in-time validation violations:")
            for violation in pit_results["violations"]:
                print(f"  - {violation}")
        if pit_results["warnings"]:
            print("Point-in-time validation warnings:")
            for warning in pit_results["warnings"]:
                print(f"  - {warning}")
        if not pit_results["violations"] and not pit_results["warnings"]:
            print("Point-in-time validation passed (no violations or warnings).")
        elif not pit_results["violations"]:
            print("Point-in-time validation passed (no violations).")

    n_obs = len(data)

    if n_splits < 2:
        raise ValueError("n_splits must be at least 2")

    # Split indices into n_splits sequential groups
    group_size = n_obs // n_splits
    group_indices = []
    for i in range(n_splits):
        start = i * group_size
        end = (i + 1) * group_size if i < n_splits - 1 else n_obs
        group_indices.append((start, end))

    # For each group, create a test set (fraction test_size of the group)
    # and training set (all other groups, purged)
    folds = []
    purge_n = int(purge_size * group_size)
    embargo_n = int(embargo_size * group_size)

    for test_group_idx in range(n_splits):
        test_start, test_end = group_indices[test_group_idx]
        # Use a fraction of the group as test set
        test_n = int((test_end - test_start) * test_size)
        test_start_idx = test_start
        test_end_idx = test_start + test_n

        if test_end_idx <= test_start_idx:
            continue

        test_indices = list(range(test_start_idx, test_end_idx))

        # Training indices: all other groups, with purge/embargo
        train_indices = []
        for train_group_idx in range(n_splits):
            if train_group_idx == test_group_idx:
                continue
            tr_start, tr_end = group_indices[train_group_idx]

            # Apply purge: remove observations near test set
            # For groups before test group, purge the end
            # For groups after test group, purge the start
            if train_group_idx < test_group_idx:
                purged_end = min(tr_end, test_start_idx - purge_n)
                if purged_end > tr_start:
                    train_indices.extend(range(tr_start, purged_end))
            else:  # train_group_idx > test_group_idx
                purged_start = max(tr_start, test_end_idx + embargo_n)
                if purged_start < tr_end:
                    train_indices.extend(range(purged_start, tr_end))

        if len(train_indices) == 0 or len(test_indices) == 0:
            continue

        train_data = data.iloc[train_indices]
        test_data = data.iloc[test_indices]

        folds.append({
            "fold": len(folds),
            "test_group": test_group_idx,
            "train_start": train_data.index[0],
            "train_end": train_data.index[-1],
            "test_start": test_data.index[0],
            "test_end": test_data.index[-1],
            "train_data": train_data,
            "test_data": test_data,
            "train_indices": train_indices,
            "test_indices": test_indices,
        })

    # Grid search for best params on each training fold
    best_params_per_fold = []
    oos_returns_list = []
    total_evaluated_trials = 0
    all_trial_sharpes: List[float] = []
    fold_benchmark_stats = []
    # Per-fold book capacity series, merged into the summary trend.
    fold_book_capacity_series: List[Any] = []
    fold_book_capacity_nw_series: List[Any] = []

    for fold in folds:
        train_data = fold["train_data"]
        test_data = fold["test_data"]

        best_sharpe = -np.inf
        best_params = None
        best_test_returns = None
        fold_trial_sharpes: List[float] = []
        best_train_returns = None

        # Generate all parameter combinations
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())

        # Why each combination did or did not produce a candidate (see the
        # walk-forward path for the same tally).
        selection_outcomes = {
            _COMBO_ELIGIBLE: 0,
            _COMBO_FLAT: 0,
            _COMBO_DEGENERATE_TRAINING: 0,
            _COMBO_FAILED: 0,
        }
        # The bars the strategy actually held a position (see the
        # walk-forward path for the same measurement).
        best_position_bars = 0
        max_position_bars = 0

        for combo in product(*param_values):
            params = dict(zip(param_names, combo))
            outcome = _COMBO_FAILED

            try:
                strategy = strategy_factory(params)
                train_signals = strategy.generate_signals(train_data)
                test_signals = strategy.generate_signals(test_data)

                # Skip parameter sets that take no position in the test window.
                # The test is book-aware in the "book" pricing mode: a
                # market-neutral book is a position, not a flat one.
                test_book_weights = (
                    strategy_target_weights(strategy, test_data)
                    if panel_pricing == "book"
                    else None
                )
                position_bars = _window_position_bars(
                    strategy,
                    test_signals,
                    test_data,
                    panel_pricing=panel_pricing,
                    latency=latency,
                    fill_rate=fill_rate,
                    book_weights=test_book_weights,
                )
                if position_bars > max_position_bars:
                    max_position_bars = position_bars
                if position_bars == 0:
                    outcome = _COMBO_FLAT
                else:
                    # Calculate returns for this parameter set
                    test_returns = _calculate_strategy_returns(
                        test_data, test_signals, commission, slippage,
                        impact_coefficient, adv_window, borrow_cost, funding_cost,
                        latency, fill_rate,
                        initial_capital=initial_capital,
                        panel_pricing=panel_pricing,
                        impact_aggregation=impact_aggregation,
                        book_weights=test_book_weights,
                    )

                    # Evaluate on training set
                    train_returns = _calculate_strategy_returns(
                        train_data, train_signals, commission, slippage,
                        impact_coefficient, adv_window, borrow_cost, funding_cost,
                        latency, fill_rate,
                        initial_capital=initial_capital,
                        panel_pricing=panel_pricing,
                        impact_aggregation=impact_aggregation,
                        book_weights=(
                            strategy_target_weights(strategy, train_data)
                            if panel_pricing == "book"
                            else None
                        ),
                    )

                    if len(train_returns) > 1 and not _is_constant_returns(train_returns):
                        ann_factor = _annualization_factor(train_returns.index)
                        excess = train_returns - 0.02 / ann_factor
                        sharpe = excess.mean() / excess.std() * np.sqrt(ann_factor)
                        outcome = _COMBO_ELIGIBLE
                    else:
                        # A constant (or too short) training return series has
                        # no Sharpe, so the combination cannot be ranked.
                        sharpe = -np.inf
                        outcome = _COMBO_DEGENERATE_TRAINING

                    if apply_deflation and np.isfinite(sharpe):
                        fold_trial_sharpes.append(float(sharpe))

                    if sharpe > best_sharpe:
                        best_sharpe = sharpe
                        best_params = params
                        best_test_returns = test_returns
                        best_position_bars = position_bars
                        if apply_deflation:
                            best_train_returns = train_returns

            except Exception:
                outcome = _COMBO_FAILED

            selection_outcomes[outcome] += 1

        fold["selection_outcomes"] = selection_outcomes
        fold["max_position_bars"] = int(max_position_bars)
        fold["position_bars"] = int(best_position_bars) if best_params is not None else None

        best_params_per_fold.append(best_params)
        all_trial_sharpes.extend(fold_trial_sharpes)
        total_evaluated_trials += len(fold_trial_sharpes)
        if best_test_returns is not None and len(best_test_returns) > 0:
            oos_returns_list.append(best_test_returns)
            fold["best_params"] = best_params
            fold["best_sharpe"] = best_sharpe
            fold["test_returns"] = best_test_returns
            fold["trial_sharpes"] = list(fold_trial_sharpes)
            # Per-fold OUT-OF-SAMPLE test Sharpe of the selected combo.
            # Distinct from `best_sharpe`, which is the IN-SAMPLE training
            # Sharpe used by the grid search. Selection criteria that claim
            # to pick on out-of-sample quality must read this key, not
            # `best_sharpe` (which would select on in-sample fit).
            fold["test_sharpe"] = _period_sharpe(best_test_returns)
            # Compute benchmark stats for this fold
            if benchmark is not None:
                if isinstance(benchmark, list) and len(benchmark) > 1:
                    # Multiple benchmarks: surface a per-fold Deflated Alpha
                    # correction (multiple-testing control across the benchmark
                    # set).  Uses the shared helper so the correction is applied
                    # identically to the aggregate path.
                    correction = _benchmark_list_alpha_correction(
                        best_test_returns, benchmark,
                        total_return_benchmark=total_return_benchmark,
                        benchmark_commission=benchmark_commission,
                        benchmark_slippage=benchmark_slippage,
                        benchmark_expense_ratio=benchmark_expense_ratio,
                        benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                    )
                    fold["benchmark_stats"] = correction["per_benchmark"]
                    fold["deflated_alpha"] = correction["deflated_alpha"]
                    fold_benchmark_stats.append(correction["per_benchmark"])
                else:
                    # Single benchmark (DataFrame or single-element list):
                    # backward-compatible path (no cross-benchmark deflation).
                    bench = benchmark[0] if isinstance(benchmark, list) else benchmark
                    benchmark_returns = _compute_benchmark_returns(bench, best_test_returns, total_return_benchmark)
                    if benchmark_returns is not None:
                        fold_ann_factor = _annualization_factor(best_test_returns.index)
                        bench_stats = _benchmark_stats(
                            best_test_returns, benchmark_returns, fold_ann_factor,
                            total_return_benchmark=total_return_benchmark,
                            benchmark_commission=benchmark_commission,
                            benchmark_slippage=benchmark_slippage,
                            benchmark_expense_ratio=benchmark_expense_ratio,
                            benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                        )
                        fold_benchmark_stats.append(bench_stats)
                    else:
                        fold_benchmark_stats.append(None)
            else:
                fold_benchmark_stats.append(None)
            if apply_deflation and best_train_returns is not None and fold_trial_sharpes:
                # Deflate the in-sample selection Sharpe by the number
                # of configurations compared in this fold's grid search.
                fold["deflated_sharpe"] = deflated_sharpe_ratio(
                    sharpe_ratio=best_sharpe,
                    returns=best_train_returns,
                    n_trials=len(fold_trial_sharpes),
                    trial_sharpes=fold_trial_sharpes,
                )
        else:
            fold["best_params"] = None
            fold["best_sharpe"] = None
            fold["test_returns"] = pd.Series(dtype=float)
            fold_benchmark_stats.append(None)

        # Surface a per-fold market-impact capacity estimate so capacity
        # degradation across folds/regimes is observable, mirroring the
        # per-period capacity that `walk_forward_analysis` records. Capacity
        # is a property of the fold's market data, so it is computed for
        # every fold (not only folds whose grid search produced returns) and
        # is None when impact is disabled or ADV is not estimable.
        _fold_capacity = estimate_capacity(
            fold["test_data"], impact_coefficient, adv_window=adv_window
        )
        fold["capacity"] = _fold_capacity.get("estimated_capacity")
        # Capacity trend for the fold's test window (mirrors the per-period
        # trend that `walk_forward_analysis` records). None when impact is
        # disabled or ADV is not estimable.
        fold["capacity_trend"] = _fold_capacity.get("capacity_trend")
        # Book-based capacity for the fold's test window (mirrors the
        # per-period book capacity that `walk_forward_analysis` records).
        # Reported in the "book" pricing mode only. None when impact is
        # disabled, when the panel carries no volume, or when the strategy
        # exposes no book.
        fold["capacity_book"] = None
        fold["capacity_book_trend"] = None
        _fold_book_capacity = None
        if panel_pricing == "book":
            _fold_book_capacity = _window_book_capacity(
                strategy_factory,
                fold.get("best_params"),
                fold["test_data"],
                impact_coefficient=impact_coefficient,
                adv_window=adv_window,
                latency=latency,
                fill_rate=fill_rate,
                impact_aggregation=impact_aggregation,
            )
            if _fold_book_capacity is not None:
                fold["capacity_book"] = _fold_book_capacity.get("estimated_capacity")
                fold["capacity_book_trend"] = _fold_book_capacity.get("capacity_trend")
                fold["capacity_notional_weighted"] = _fold_book_capacity.get(
                    "estimated_capacity_notional_weighted"
                )
                fold["capacity_notional_weighted_trend"] = _fold_book_capacity.get(
                    "capacity_notional_weighted_trend"
                )
        fold_book_capacity_series.append(
            _fold_book_capacity.get("capacity_series")
            if _fold_book_capacity is not None
            else None
        )
        fold_book_capacity_nw_series.append(
            _fold_book_capacity.get("capacity_notional_weighted_series")
            if _fold_book_capacity is not None
            else None
        )
        # Panel book diagnostic for the fold's test window (mirrors the
        # per-period diagnostic that `walk_forward_analysis` records).
        # Measurement only -- no return, cost or impact number changes.
        fold["book_diagnostic"] = _window_book_diagnostic(
            strategy_factory,
            fold.get("best_params"),
            fold["test_data"],
            fold.get("test_returns"),
            latency=latency,
            fill_rate=fill_rate,
            panel_pricing=panel_pricing,
            impact_coefficient=impact_coefficient,
            adv_window=adv_window,
            initial_capital=initial_capital,
            impact_aggregation=impact_aggregation,
        )

    # Combine all out-of-sample returns
    if oos_returns_list:
        oos_returns = pd.concat(oos_returns_list)
    else:
        oos_returns = pd.Series(dtype=float)

    # Parameter stability analysis
    valid_params = [p for p in best_params_per_fold if p is not None]
    param_stability = {}
    if valid_params:
        param_names = set()
        for params in valid_params:
            param_names.update(params.keys())

        for name in param_names:
            values = [p.get(name) for p in valid_params if name in p]
            if values:
                unique_count = len(set(values))
                param_stability[name] = {
                    "unique_values": unique_count,
                    "most_common": max(set(values), key=values.count) if values else None,
                    "stability_ratio": 1.0 - unique_count / len(values),
                }

    # Summary metrics
    summary = _calculate_cpcv_summary(
        oos_returns, folds, param_stability, folds_with_position=len(oos_returns_list)
    )

    # Aggregate multiple-testing correction on the combined out-of-sample
    # returns. The conservative interpretation: the OOS record was produced
    # by a search that evaluated total_evaluated_trials configurations, so
    # the OOS Sharpe is deflated by all of them. Use the pooled cross-fold
    # trial Sharpes for the cross-sectional SR* estimator (conservative:
    # between-fold variation inflates the null Sharpe).
    #
    # Do not skip for constant (zero-variance) return series: `deflated_sharpe_ratio`
    # handles degenerate cases by returning DSR=0, p_value=1, z_score=None.
    if apply_deflation and len(oos_returns) > 1 and max(total_evaluated_trials, 1) >= 1:
        summary["deflated_sharpe"] = deflated_sharpe_ratio(
            sharpe_ratio=summary.get("oos_sharpe", 0.0),
            returns=oos_returns,
            n_trials=max(total_evaluated_trials, 1),
            trial_sharpes=all_trial_sharpes if all_trial_sharpes else None,
        )
        if summary.get("deflated_sharpe") is not None:
            try:
                summary["minimum_detectable_sharpe"] = minimum_detectable_sharpe(
                    summary["deflated_sharpe"], oos_returns
                )
            except Exception:
                pass

    # Benchmark comparison on combined OOS returns
    if benchmark is not None and len(oos_returns) > 0:
        if isinstance(benchmark, list) and len(benchmark) > 1:
            # Multiple benchmarks: surface a cross-benchmark Deflated Alpha
            # correction on the aggregate out-of-sample record, mirroring the
            # calculate_metrics / benchmark_list path.
            correction = _benchmark_list_alpha_correction(
                oos_returns, benchmark,
                total_return_benchmark=total_return_benchmark,
                benchmark_commission=benchmark_commission,
                benchmark_slippage=benchmark_slippage,
                benchmark_expense_ratio=benchmark_expense_ratio,
                benchmark_cost_is_periodic=benchmark_cost_is_periodic,
            )
            summary["benchmark_metrics"] = correction["per_benchmark"]
            if correction["deflated_alpha"] is not None:
                summary["deflated_alpha"] = correction["deflated_alpha"]
                try:
                    summary["minimum_detectable_alpha"] = minimum_detectable_alpha(
                        summary["deflated_alpha"], oos_returns
                    )
                except Exception:
                    pass
        else:
            # Single benchmark (DataFrame or single-element list): backward compat
            bench = benchmark[0] if isinstance(benchmark, list) else benchmark
            benchmark_returns = _compute_benchmark_returns(bench, oos_returns, total_return_benchmark)
            if benchmark_returns is not None:
                summary = _add_benchmark_to_summary(
                    summary, oos_returns, benchmark_returns,
                    commission=benchmark_commission, slippage=benchmark_slippage,
                    benchmark_expense_ratio=benchmark_expense_ratio, total_return_benchmark=total_return_benchmark,
                    benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                    benchmark_data=bench,
                )

    # The resolution of the significance statistics carried by this summary:
    # the smallest annualized Sharpe / alpha the aggregate Deflated Sharpe
    # and Deflated Alpha tests could have confirmed at the sample size
    # actually available (the number of fold observations that carried a
    # position). A significance test on a small sample can only fail, so a
    # reader needs this to tell an informative result from an unfalsifiable
    # one. A measurement, not a correction: it changes no verdict and no
    # reported number.
    summary["test_resolution"] = _build_test_resolution(summary, oos_returns)

    # Add per-fold benchmark metrics to summary
    if fold_benchmark_stats:
        summary['benchmark_metrics_per_fold'] = fold_benchmark_stats

    summary["bias_controls_engaged"] = bool(pit_results is not None)

    # Surface market-impact capacity estimate in the summary when impact is
    # enabled and estimable; keep None (backward compatible) otherwise.
    _capacity = estimate_capacity(data, impact_coefficient, adv_window=adv_window)
    summary["capacity"] = _capacity.get("estimated_capacity")
    # Capacity trend over the whole sample (see the walk-forward summary for
    # the same key) plus the worst capacity seen in any out-of-sample fold.
    summary["capacity_trend"] = _capacity.get("capacity_trend")
    summary["oos_min_capacity"] = _aggregate_oos_capacity(
        [f.get("capacity_trend") for f in folds]
    )
    # Book-based capacity: the same estimate computed from the trade sizes
    # the strategy actually executed in the out-of-sample folds, next to the
    # basket-based number above (see the walk-forward summary for the same
    # keys).
    _book_capacity_series = _merge_capacity_series(fold_book_capacity_series)
    summary["capacity_book"] = None
    summary["capacity_book_trend"] = None
    if _book_capacity_series is not None:
        _book_readings = _book_capacity_series.replace(
            [np.inf, -np.inf], np.nan
        ).dropna()
        if len(_book_readings):
            _book_point = float(_book_readings.iloc[-1])
            summary["capacity_book"] = _book_point
            summary["capacity_book_trend"] = _capacity_trend_from_series(
                _book_capacity_series, _book_point
            )
    summary["oos_min_capacity_book"] = _aggregate_oos_capacity(
        [f.get("capacity_book_trend") for f in folds]
    )
    # Notional-weighted book capacity (mirrors the walk-forward summary).
    _book_capacity_nw_series = _merge_capacity_series(fold_book_capacity_nw_series)
    summary["capacity_notional_weighted"] = None
    summary["capacity_notional_weighted_trend"] = None
    if _book_capacity_nw_series is not None:
        _nw_readings = _book_capacity_nw_series.replace(
            [np.inf, -np.inf], np.nan
        ).dropna()
        if len(_nw_readings):
            _nw_point = float(_nw_readings.iloc[-1])
            summary["capacity_notional_weighted"] = _nw_point
            summary["capacity_notional_weighted_trend"] = _capacity_trend_from_series(
                _book_capacity_nw_series, _nw_point
            )
    summary["oos_min_capacity_notional_weighted"] = _aggregate_oos_capacity(
        [f.get("capacity_notional_weighted_trend") for f in folds]
    )
    # Panel book diagnostic aggregated over the out-of-sample folds (see
    # the walk-forward summary for the same key). None when no fold
    # produced a diagnostic.
    summary["book_diagnostic"] = aggregate_book_diagnostics(
        [f.get("book_diagnostic") for f in folds]
    )
    # The pricing convention that produced the reported out-of-sample P&L.
    summary["panel_pricing"] = panel_pricing
    summary["impact_aggregation"] = impact_aggregation
    # A grid key whose values do not change the strategy's behaviour is a
    # null experiment: the per-fold selection over it cannot change any
    # result, yet the artifact would still report it as a selected
    # parameter. The finding is measured and recorded here; the CLI prints
    # it next to the per-fold selection.
    inert_report = _inert_grid_report(strategy_factory, param_grid, data)
    summary["inert_grid_params"] = inert_report["inert_grid_params"]
    summary["inert_grid_message"] = inert_report["message"]
    # A run in which no fold could select a parameter has to say why. The
    # diagnosis uses the same vocabulary as the out-of-sample path (so one
    # reader handles both) and is recorded in the summary, so the artifact
    # explains itself instead of leaving ten `null` selections to be
    # interpreted. It is a measurement: it changes no number.
    if not any(p is not None for p in best_params_per_fold):
        summary["no_selection_diagnosis"] = _diagnose_no_selection(
            validation_results={"folds": folds},
            validation_method="cpcv",
            param_grid=param_grid,
            train_data=data,
            context={
                "analysis_path": "cpcv",
                "cpcv_n_splits": n_splits,
                "cpcv_test_size": test_size,
                "cpcv_purge_size": purge_size,
                "cpcv_embargo_size": embargo_size,
                "cli_flags": {
                    "n_splits": "--n-splits",
                    "test_size": "--test-size",
                },
            },
        )
    else:
        # A run in which *some* folds could select a parameter and others
        # could not has to say which folds were flat and why: the count
        # alone is compatible with "the flat folds were too short to
        # trade" (a design problem) and with "the strategy never triggers
        # on that part of the sample" (a finding about the strategy), and
        # the two need opposite remedies. The measurement changes no
        # number.
        partial_diagnosis = _diagnose_partial_selection(
            validation_results={"folds": folds},
            validation_method="cpcv",
            param_grid=param_grid,
            train_data=data,
            context={
                "analysis_path": "cpcv",
                "window_noun": "fold",
                "selection_basis": "overfitting_risk_verdict",
                "cpcv_n_splits": n_splits,
                "cpcv_test_size": test_size,
                "cpcv_purge_size": purge_size,
                "cpcv_embargo_size": embargo_size,
                "cli_flags": {
                    "n_splits": "--n-splits",
                    "test_size": "--test-size",
                },
            },
        )
        if partial_diagnosis is not None:
            summary["partial_selection_diagnosis"] = partial_diagnosis
            # The overfitting-risk verdict is a statement about the
            # parameter stability across the folds that selected a
            # parameter. When only some folds selected one, the verdict
            # rests on fewer windows than the run has, and the artifact
            # has to say so: the categorical verdict itself is unchanged
            # (the measurement supports it), but its basis is stated.
            if summary.get("overfitting_risk") is not None and (
                "overfitting_risk_reason" not in summary
            ):
                details = partial_diagnosis["details"]
                summary["overfitting_risk_reason"] = (
                    f"the '{summary['overfitting_risk']}' verdict rests on "
                    f"the parameter stability of the "
                    f"{details['n_windows_with_selected_params']} of the "
                    f"{details['n_validation_windows']} out-of-sample "
                    f"{details.get('window_noun', 'fold')}s that selected a "
                    f"parameter; the other "
                    f"{details['n_flat_windows']} produced no selection and "
                    f"contributed nothing to it (see "
                    f"summary['partial_selection_diagnosis'])"
                )
            # The verdict also rests on how much of those windows the
            # strategy actually traded in. The aggregate Sharpe and
            # stability ratio hide that: a "low" rating earned on two folds
            # that each traded for one bar says little about the strategy.
            # Measurement only -- it changes no number.
            _warmup_bars = execution_warmup_metadata(
                WARMUP_CONVENTION_WALK_FORWARD, latency
            )["execution_warmup_bars"]
            _thin = _thin_evidence_warning(
                partial_diagnosis["details"].get("traded_windows", []),
                _warmup_bars,
                window_noun="fold",
            )
            if _thin is not None:
                summary["thin_evidence_warning"] = _thin
    # The execution warmup this path applied (see the walk-forward summary
    # for the same key).
    summary.update(
        execution_warmup_metadata(WARMUP_CONVENTION_WALK_FORWARD, latency)
    )

    return {
        "folds": folds,
        "best_params_per_fold": best_params_per_fold,
        "oos_returns": oos_returns,
        "point_in_time_validation": pit_results,
        "summary": summary,
        "param_stability": param_stability,
    }


def _calculate_cpcv_summary(
    oos_returns: pd.Series,
    folds: List[Dict[str, Any]],
    param_stability: Dict[str, Any],
    folds_with_position: int = 0,
) -> Dict[str, Any]:
    """Calculate summary metrics for CPCV results."""
    summary = {
        "n_folds": len(folds),
        "folds_with_position": int(folds_with_position),
        "total_oos_return": None if len(oos_returns) == 0 else float((1 + oos_returns).prod() - 1),
    }

    if len(oos_returns) > 1:
        ann_factor = _annualization_factor(oos_returns.index)
        excess = oos_returns - 0.02 / ann_factor
        if not _is_constant_returns(oos_returns):
            summary["oos_sharpe"] = float(excess.mean() / oos_returns.std() * np.sqrt(ann_factor))
            summary["oos_volatility"] = float(oos_returns.std() * np.sqrt(ann_factor))
        else:
            summary["oos_sharpe"] = 0.0
            summary["oos_volatility"] = 0.0

        summary["avg_fold_return"] = float(oos_returns.mean())
        summary["n_positive_folds"] = int((oos_returns > 0).sum())
        summary["win_rate_folds"] = float((oos_returns > 0).sum() / len(oos_returns)) if len(oos_returns) > 0 else 0.0

    # Average parameter stability
    if param_stability:
        stability_ratios = [v["stability_ratio"] for v in param_stability.values()]
        summary["avg_param_stability"] = float(np.mean(stability_ratios))
        if summary["avg_param_stability"] >= 0.5:
            summary["overfitting_risk"] = "low"
        elif summary["avg_param_stability"] >= 0.3:
            summary["overfitting_risk"] = "medium"
        else:
            summary["overfitting_risk"] = "high"
    else:
        summary["avg_param_stability"] = 0.0
        # No fold selected a parameter, so there is no parameter instability
        # to measure: the risk verdict is *not applicable*, not "high". A
        # categorical verdict on a run in which nothing could trade is a
        # category error, and it reads as a finding about the strategy when
        # it is a fact about the window.
        summary["overfitting_risk"] = None
        n_selected_folds = len(
            [f for f in folds if f.get("best_params") is not None]
        )
        if n_selected_folds == 0:
            summary["overfitting_risk_reason"] = (
                "not applicable: no parameter was selected in any fold, so "
                "there is no parameter stability to classify (see "
                "summary['no_selection_diagnosis'])"
            )
        else:
            summary["overfitting_risk_reason"] = (
                "not available: the selected parameters produced no "
                "stability record to classify"
            )

    return summary


def _walk_forward_window_periods(
    data: pd.DataFrame,
    train_months: int,
    test_months: int,
    step_months: int,
) -> int:
    """Number of walk-forward periods a window yields on `data`.

    Mirrors the period generator inside `walk_forward_analysis` exactly (same
    calendar arithmetic, same "non-empty train and test slice" condition), so
    a caller can ask "does this window fit this sample?" without paying for
    the grid search.
    """
    if data is None or len(data) == 0:
        return 0
    start_date = data.index.min()
    end_date = data.index.max()
    count = 0
    train_end = start_date + pd.DateOffset(months=train_months)
    test_start = train_end
    while test_start + pd.DateOffset(months=test_months) <= end_date:
        test_end = test_start + pd.DateOffset(months=test_months)
        train_slice = data[data.index < train_end]
        test_slice = data[(data.index >= test_start) & (data.index < test_end)]
        if len(train_slice) > 0 and len(test_slice) > 0:
            count += 1
        train_end = train_end + pd.DateOffset(months=step_months)
        test_start = train_end
    return count


def _resolve_walk_forward_window(
    data: pd.DataFrame,
    train_months: int,
    test_months: int,
    step_months: int,
) -> Dict[str, Any]:
    """Resolve the walk-forward window that is actually used on a training split.

    The walk-forward validation phase runs *inside* the training split, so the
    window has to fit the training split: a single period needs
    ``train_months + test_months`` of calendar span. When the requested window
    does not fit -- e.g. the default 12 + 3 months on a one-year training
    split -- the validation phase silently produces **zero** periods, no
    parameter can be selected, and the run aborts with a "no valid parameters"
    message that hides the real cause.

    The resolver keeps the requested window whenever it fits, and otherwise
    shrinks **only the training window** (never the out-of-sample test window
    of the walk-forward phase, and never the validation / test splits of the
    out-of-sample framework) to the largest value that still yields at least
    one period. The effective window is returned so the caller can print it
    and record it in the result artifact: an adapted window is a methodology
    choice, not a detail, so it must be visible in the output.
    """
    requested = {
        "train_months": int(train_months),
        "test_months": int(test_months),
        "step_months": int(step_months),
    }
    span_days = 0
    if data is not None and len(data) > 0:
        span_days = int((data.index.max() - data.index.min()).days)
    span_months = span_days / 30.4375

    requested_periods = _walk_forward_window_periods(
        data, train_months, test_months, step_months
    )
    resolution: Dict[str, Any] = {
        "requested": requested,
        "effective": dict(requested),
        "adapted": False,
        "train_span_months": round(float(span_months), 4),
        "requested_periods": int(requested_periods),
        "effective_periods": int(requested_periods),
        "reason": None,
    }
    if requested_periods > 0:
        return resolution

    # The requested window does not fit: shrink the training window to the
    # largest value that still produces at least one period.
    for candidate in range(int(train_months) - 1, 0, -1):
        if _walk_forward_window_periods(data, candidate, test_months, step_months) > 0:
            resolution["effective"] = {
                "train_months": candidate,
                "test_months": int(test_months),
                "step_months": int(step_months),
            }
            resolution["adapted"] = True
            resolution["effective_periods"] = _walk_forward_window_periods(
                data, candidate, test_months, step_months
            )
            resolution["reason"] = (
                f"the training split spans {span_months:.1f} months, which cannot "
                f"hold the requested walk-forward window "
                f"(train {int(train_months)} + test {int(test_months)} = "
                f"{int(train_months) + int(test_months)} months); the training "
                f"window was shortened to {candidate} month(s) so the validation "
                f"phase can run"
            )
            return resolution

    resolution["reason"] = (
        f"the training split spans only {span_months:.1f} months, which cannot "
        f"hold even a 1-month training window plus a {int(test_months)}-month "
        f"out-of-sample window; no walk-forward period can be built"
    )
    return resolution


def _strategy_behaviour_fingerprint(
    strategy: Any,
    data: pd.DataFrame,
) -> Optional[tuple]:
    """Behavioural fingerprint of a strategy on `data`.

    The fingerprint is the signal series plus the strategy's optional book
    (per-asset target weights). Two parameter settings with the same
    fingerprint are behaviourally identical on this data, so a grid search
    between them is a null experiment.
    """
    try:
        signals = strategy.generate_signals(data)
        signal_values = np.asarray(pd.Series(signals).to_numpy(), dtype=float)
    except Exception:
        return None
    try:
        weights = strategy_target_weights(strategy, data)
    except Exception:
        weights = None
    if weights is None:
        weight_values = None
    else:
        try:
            weight_values = np.asarray(weights, dtype=float)
        except Exception:
            weight_values = None
    return (signal_values, weight_values)


def _same_behaviour(left: Optional[tuple], right: Optional[tuple]) -> bool:
    """Whether two behavioural fingerprints describe the same strategy."""
    if left is None or right is None:
        return left is None and right is None
    left_signals, left_weights = left
    right_signals, right_weights = right
    if left_weights is None or right_weights is None:
        if left_weights is not right_weights:
            return False
    elif left_weights.shape != right_weights.shape:
        return False
    elif not np.array_equal(left_weights, right_weights, equal_nan=True):
        return False
    if left_signals.shape != right_signals.shape:
        return False
    return bool(np.array_equal(left_signals, right_signals, equal_nan=True))


# The maximum number of combinations of the *other* grid values that are
# evaluated for a single key before the check gives up and falls back to
# comparing the key's values with the other grid keys held at their first
# value. The exhaustive comparison costs `len(values) x product(len(other
# values))` behavioural fingerprints per key, which is unbounded in the size
# of the grid; the bound keeps the measurement affordable on a large grid.
#
# The bound only ever weakens the *inert* verdict: a key that shows a
# behavioural difference in the evaluated combinations is live whatever the
# bound, because one difference is proof of liveness. A key that shows no
# difference may therefore be accused on incomplete evidence, and the
# finding says so when that happens.
_INERT_GRID_MAX_COMBINATIONS = 16


def _other_grid_keys(
    param_grid: Dict[str, List[Any]],
    key: str,
) -> List[str]:
    """The grid keys other than `key` whose values can be held fixed.

    A key whose values are not a non-empty list cannot be set at all, so it
    takes no part in the combinations (the strategy is built without it).
    """
    return [
        other
        for other, other_values in (param_grid or {}).items()
        if other != key
        and isinstance(other_values, (list, tuple))
        and len(other_values) > 0
    ]


def _grid_combination_count(
    param_grid: Dict[str, List[Any]],
    other_keys: List[str],
) -> int:
    """Number of combinations the values of `other_keys` span."""
    count = 1
    for other in other_keys:
        count *= len(param_grid[other])
    return count


def _key_behaviour_within_combination(
    strategy_factory: Callable,
    key: str,
    values: List[Any],
    base_params: Dict[str, Any],
    data: pd.DataFrame,
) -> str:
    """Whether `key` changes the behaviour within one combination.

    The key's values are compared against each other while every other grid
    key is held at the values in `base_params`.

    Returns:
        ``"live"`` when the values produce different behaviour (so the key
        changes something in this combination), ``"inert"`` when they all
        produce the same behaviour, and ``"unknown"`` when the comparison
        cannot be made (the strategy could not be built, or the behaviour
        could not be fingerprinted).
    """
    fingerprints = []
    for value in values:
        params: Dict[str, Any] = dict(base_params)
        params[key] = value
        try:
            strategy = strategy_factory(params)
        except Exception:
            fingerprints.append(None)
            continue
        fingerprints.append(_strategy_behaviour_fingerprint(strategy, data))
    if not fingerprints:
        return "unknown"
    reference = fingerprints[0]
    if reference is None:
        return "unknown"
    if all(_same_behaviour(reference, other) for other in fingerprints[1:]):
        return "inert"
    return "live"


def _inert_param_grid_keys_measured(
    strategy_factory: Callable,
    param_grid: Dict[str, List[Any]],
    data: pd.DataFrame,
    max_combinations: Optional[int] = None,
) -> Dict[str, Any]:
    """Measure the inert grid keys, with the bound that shaped the answer.

    A grid key is inert when its values produce the *same* behaviour in
    **every** combination of the other grid keys' values. Varying one key
    while holding the others at their first value is not enough: a key whose
    effect appears only in combination with a non-first value of another key
    (a parameter the strategy reads only inside a branch, say) would be
    accused of being inert while it is live. A false accusation is worse
    than no accusation, because it teaches the reader to ignore the warning.

    The comparison is exhaustive over the combinations of the other keys'
    values, with an early exit: the first combination that shows a
    behavioural difference proves the key is live, so the remaining
    combinations are skipped and a live key costs the same as a single
    comparison. The cost of an inert key is `len(values) x product(len(other
    values))` fingerprints, which is unbounded in the size of the grid, so
    the number of combinations per key is bounded by `max_combinations`.
    Beyond the bound the check falls back to the first combination (the
    other grid keys held at their first value) and the key is reported as
    ``bounded``, so the finding never reports a partial answer silently.

    Returns:
        A dict with the inert keys, the keys whose check was bounded (a
        subset of the inert keys: a bounded check that found a difference
        proves liveness, so it never accuses), the bound that was applied
        and the number of combinations that were evaluated per key.
    """
    cap = (
        _INERT_GRID_MAX_COMBINATIONS
        if max_combinations is None
        else int(max_combinations)
    )
    inert: List[str] = []
    bounded: List[str] = []
    combinations_evaluated: Dict[str, int] = {}
    for key, values in (param_grid or {}).items():
        if not isinstance(values, (list, tuple)) or len(values) < 2:
            continue
        other_keys = _other_grid_keys(param_grid, key)
        n_combinations = _grid_combination_count(param_grid, other_keys)
        was_bounded = n_combinations > cap
        value_lists = [list(param_grid[other]) for other in other_keys]
        if was_bounded:
            # The combination space does not fit in the bound, so the check
            # falls back to the first combination (the other grid keys held
            # at their first value) and the finding says that it did. The
            # product is consumed lazily: materialising it would cost
            # `n_combinations` tuples on a large grid.
            combos = [next(product(*value_lists), ())]
        else:
            combos = list(product(*value_lists))
        combinations_evaluated[key] = len(combos)
        verdict = "inert"
        for combo in combos:
            base_params = dict(zip(other_keys, combo))
            outcome = _key_behaviour_within_combination(
                strategy_factory, key, list(values), base_params, data
            )
            if outcome != "inert":
                # A difference proves the key is live; an inconclusive
                # comparison proves nothing, so the key is not accused.
                verdict = outcome
                break
        if verdict == "inert":
            inert.append(key)
            if was_bounded:
                bounded.append(key)
    return {
        "inert": inert,
        "bounded": bounded,
        "max_combinations": cap,
        "combinations_evaluated": combinations_evaluated,
    }


def _inert_param_grid_keys(
    strategy_factory: Callable,
    param_grid: Dict[str, List[Any]],
    data: pd.DataFrame,
    max_combinations: Optional[int] = None,
) -> List[str]:
    """Grid keys that do not change the strategy's behaviour on `data`.

    A grid key whose values all produce the *same* signals (and the same
    book) is inert: the "search" over it cannot change any result, yet the
    artifact would still report it as a "selected parameter". This is a
    null experiment, so it is reported rather than silently ranked.

    The key is inert only when it changes nothing in *every* combination of
    the other grid keys' values, so a parameter that matters only in
    combination with another parameter is never accused. See
    :func:`_inert_param_grid_keys_measured` for the bound that keeps the
    exhaustive comparison affordable.
    """
    measured = _inert_param_grid_keys_measured(
        strategy_factory, param_grid, data, max_combinations
    )
    return measured["inert"]


def _strategy_parameter_names(strategy: Any) -> List[str]:
    """Parameter names a strategy actually reads (diagnostic hint only).

    The names are read from the strategy's own source, so they reflect the
    implementation rather than a hand-maintained registry that could drift.
    A strategy that reads its parameters from somewhere else simply yields an
    empty list, which only weakens the hint, never the checks.
    """
    try:
        import inspect
        import re as _re

        source = inspect.getsource(type(strategy).generate_signals)
        names = _re.findall(
            r"parameters\.get\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']",
            source,
        )
        return sorted(set(names))
    except Exception:
        return []


def _first_grid_params(param_grid: Dict[str, List[Any]]) -> Dict[str, Any]:
    """One concrete parameter set from a grid (the first value of every key)."""
    params: Dict[str, Any] = {}
    for key, values in (param_grid or {}).items():
        if isinstance(values, (list, tuple)) and len(values) > 0:
            params[key] = values[0]
    return params


def _inert_grid_report(
    strategy_factory: Callable,
    param_grid: Dict[str, List[Any]],
    data: pd.DataFrame,
    scope: str = "over the full sample",
    max_combinations: Optional[int] = None,
) -> Dict[str, Any]:
    """Measure the grid keys that are inert, and describe the finding.

    A grid key whose values do not change the strategy's behaviour is a null
    experiment: the search over it cannot change any result, yet the artifact
    would still report it as a selected parameter.

    The helper only *measures*. It never changes a return, cost, impact,
    capacity or selection number, and it never prints, so every caller
    decides where the finding belongs (summary, artifact, console) and the
    console never repeats itself.

    Returns a dict with:
      * ``inert_grid_params``: the inert grid keys (empty when there are none);
      * ``strategy_parameters``: the parameter names the strategy actually
        reads (a diagnostic hint, possibly empty);
      * ``message``: a human-readable description, or None when nothing is
        inert. The same string is written to the artifact and printed by the
        CLI, so the two never disagree. When the check of an accused key was
        bounded, the message says so, so a partial answer is never reported
        as a complete one.
    """
    measured = _inert_param_grid_keys_measured(
        strategy_factory, param_grid, data, max_combinations
    )
    inert = measured["inert"]
    try:
        accepted = _strategy_parameter_names(
            strategy_factory(_first_grid_params(param_grid))
        )
    except Exception:
        accepted = []
    message = None
    if inert:
        hint = f" The strategy reads: {', '.join(accepted)}." if accepted else ""
        # A bounded check accuses on incomplete evidence, so the accusation
        # says so. A bounded check that found a difference proves liveness
        # and never accuses, so it needs no caveat.
        caveat = ""
        if measured["bounded"]:
            caveat = (
                f" The check for {', '.join(measured['bounded'])} was bounded: "
                f"the combinations of the other grid values exceed the bound "
                f"of {measured['max_combinations']}, so only the first was "
                f"evaluated (the other grid keys held at their first value) "
                f"and it may have missed an interaction between parameters."
            )
        message = (
            f"the parameter grid did not change the strategy's behaviour "
            f"{scope} for: {', '.join(inert)}. The search over those parameters "
            f"is a null experiment, not evidence.{caveat}{hint}"
        )
    return {
        "inert_grid_params": inert,
        "strategy_parameters": accepted,
        "message": message,
    }


def _print_inert_grid_warning(
    message: Optional[str],
    indent: str = "  ",
) -> None:
    """Print an inert-grid warning next to the ranking / selection it qualifies.

    The warning is printed by the CLI (not by the analysis functions), so it
    appears exactly once, next to the numbers it qualifies, and the console
    and the artifact say the same thing.
    """
    if not message:
        return
    print(f"{indent}WARNING: {message}")


def _print_no_selection_diagnosis(
    diagnosis: Optional[Dict[str, Any]],
    indent: str = "  ",
) -> None:
    """Print why no parameter could be selected, next to the fold / period count.

    A run that selected nothing has to say why: the artifact carries the
    diagnosis under ``summary["no_selection_diagnosis"]`` and the console
    prints the same message, so the two never disagree. Nothing is printed
    when a parameter *was* selected.
    """
    if not isinstance(diagnosis, dict):
        return
    message = diagnosis.get("message")
    if not message:
        return
    print(f"{indent}No parameter could be selected: {message}")


def _print_partial_selection_diagnosis(
    diagnosis: Optional[Dict[str, Any]],
    indent: str = "  ",
) -> None:
    """Print the flat windows of a partially flat run, one line per window.

    A run in which some windows could select a parameter and others could
    not has to say which windows were flat and why: the count alone is
    compatible with "the flat windows were too short to trade" (a design
    problem) and with "the strategy never triggers on that part of the
    sample" (a finding about the strategy). The artifact carries the same
    strings under ``summary["partial_selection_diagnosis"]``, so the
    console and the artifact never disagree. Nothing is printed when
    every window selected a parameter, or when none did (that is the
    "no parameter could be selected" diagnosis).
    """
    if not isinstance(diagnosis, dict):
        return
    message = diagnosis.get("message")
    if not message:
        return
    print(f"{indent}Partial selection: {message}")
    details = diagnosis.get("details") or {}
    for window in details.get("flat_windows") or []:
        text = window.get("text")
        if text:
            print(f"{indent}  {text}")


def _print_thin_evidence_warning(
    warning: Optional[Dict[str, Any]],
    indent: str = "  ",
) -> None:
    """Print how much evidence the verdict rests on, when that is little.

    A verdict measured on windows the strategy barely traded in is weak
    evidence: the aggregate Sharpe and stability ratio hide how much of
    those windows the strategy actually held a position, so a "low"
    overfitting-risk rating earned on two windows that each traded for one
    bar reads as a finding about the strategy when it is mostly a finding
    about the windows. The artifact carries the same message under
    ``summary["thin_evidence_warning"]``, so the console and the artifact
    never disagree. Nothing is printed when every window the verdict rests
    on traded in at least the threshold fraction of its executable bars.
    """
    if not isinstance(warning, dict):
        return
    message = warning.get("message")
    if not message:
        return
    print(f"{indent}WARNING: {message}")
    details = warning.get("details") or {}
    for window in details.get("thin_windows") or []:
        text = (
            f"window {window.get('window')}: held a position for "
            f"{window.get('position_bars')} of "
            f"{window.get('executable_bars')} executable bars "
            f"({window.get('position_fraction_of_executable'):.0%}), "
            f"{window.get('test_start')} to {window.get('test_end')}"
        )
        print(f"{indent}  {text}")


def _print_test_resolution(
    resolution: Optional[Dict[str, Any]],
    indent: str = "  ",
) -> None:
    """Print what the significance tests could have detected, next to the verdict.

    A significance test on a small sample can only fail: the p-value a
    Deflated Sharpe / Deflated Alpha test reports says nothing about whether
    the effect could have been detected at all. Reporting the smallest
    confirmable effect next to the p-value is what separates an informative
    result from an unfalsifiable one.

    The artifact carries the same numbers under
    ``summary["test_resolution"]``, so the console and the artifact never
    disagree. These are measurements, not corrections: nothing printed here
    changes a verdict or a reported number.
    """
    if not isinstance(resolution, dict):
        return

    n_obs = resolution.get("n_test_observations")
    trials = resolution.get("n_parameter_trials")
    benches = resolution.get("n_benchmarks")
    if n_obs is None and trials is None and benches is None:
        # No significance test was run on this record, so there is no
        # resolution to report. Say so rather than staying silent: silence
        # would be indistinguishable from a run that forgot to report it.
        print(f"{indent}Test resolution: {resolution.get('message')}")
        return

    print(f"{indent}Test resolution (measurement, not a correction):")
    scope = []
    if n_obs is not None:
        scope.append(f"{n_obs} test observation(s)")
    if trials is not None:
        scope.append(f"{trials} parameter trial(s)")
    if benches is not None:
        scope.append(f"{benches} benchmark(s)")
    if scope:
        print(f"{indent}  {', '.join(scope)}.")

    sharpe_status = resolution.get("sharpe_status")
    if sharpe_status == "resolvable":
        print(
            f"{indent}  Deflated Sharpe: smallest confirmable annualized Sharpe "
            f"{_format_optional_float(resolution.get('min_detectable_sharpe'))} "
            f"(observed "
            f"{_format_optional_float(resolution.get('observed_annualized_sharpe'))})"
        )
    elif sharpe_status == "not_resolvable":
        print(
            f"{indent}  Deflated Sharpe: resolution not computable "
            f"({resolution.get('sharpe_reason')})"
        )

    alpha_status = resolution.get("alpha_status")
    if alpha_status == "resolvable":
        print(
            f"{indent}  Deflated Alpha: smallest confirmable annualized alpha "
            f"{_format_optional_float(resolution.get('min_detectable_alpha'), '{:.2%}')} "
            f"(observed "
            f"{_format_optional_float(resolution.get('observed_annualized_alpha'), '{:.2%}')})"
        )
    elif alpha_status == "not_resolvable":
        print(
            f"{indent}  Deflated Alpha: resolution not computable "
            f"({resolution.get('alpha_reason')})"
        )

    beyond = []
    if resolution.get("sharpe_beyond_plausible_bound"):
        beyond.append("Deflated Sharpe")
    if resolution.get("alpha_beyond_plausible_bound"):
        beyond.append("Deflated Alpha")
    if beyond:
        print(
            f"{indent}  Beyond the plausibility bound (annualized Sharpe <= "
            f"{_format_optional_float(resolution.get('plausible_max_annualized_sharpe'), '{:.2f}')}, "
            f"annualized alpha <= "
            f"{_format_optional_float(resolution.get('plausible_max_annualized_alpha'), '{:.2%}')}):"
        )
        for name in beyond:
            print(f"{indent}    - {name}")
        print(
            f"{indent}  A threshold the sample cannot resolve measures the sample, "
            f"not the strategy."
        )


def _print_deflated_alpha(
    deflated_alpha: Optional[Dict[str, Any]],
    indent: str = "",
    label: str = "Deflated Alpha Ratio",
) -> None:
    """Print the aggregate Deflated Alpha Ratio a summary carries.

    The alpha *resolution* printed next to the verdict belongs to the
    aggregate Deflated Alpha Ratio (the DAR over the benchmark set), so that
    statistic has to be visible next to it: a resolution whose statistic the
    reader cannot see cannot be checked.

    The per-benchmark corrected alpha p-value the CLIs also print is that
    benchmark's own DAR p-value -- for the primary benchmark it coincides with
    the aggregate's. What the aggregate line adds is the ratio itself, the
    expected maximum alpha and the benchmark count, none of which the
    per-benchmark print carries.

    The numbers printed here are the ones the artifact already carries under
    ``summary["deflated_alpha"]``; nothing is recomputed and no reported
    number is changed.
    """
    if not isinstance(deflated_alpha, dict):
        return
    print(
        f"{indent}{label}: "
        f"{_format_optional_float(deflated_alpha.get('deflated_alpha_ratio'))} "
        f"(p-value {_format_optional_float(deflated_alpha.get('p_value'))}, "
        f"expected max alpha "
        f"{_format_optional_float(deflated_alpha.get('expected_max_alpha'), '{:.2%}')}, "
        f"{deflated_alpha.get('n_benchmarks')} benchmarks)"
    )


def _format_overfitting_risk(value: Any, unknown: str = "unknown") -> str:
    """Format the overfitting-risk verdict, including the 'not applicable' case.

    ``None`` means the verdict is not applicable (no parameter was selected,
    so there was no parameter stability to classify). It is rendered as
    "unknown" rather than as a categorical risk level, and never as a
    fabricated "low" or "high".
    """
    if value is None:
        return unknown
    return str(value)


def _print_overfitting_risk(
    summary: Optional[Dict[str, Any]],
    indent: str = "  ",
) -> None:
    """Print the overfitting-risk verdict and, when it is not applicable, why.

    The verdict is printed by the CLI (not by the analysis functions), so it
    appears exactly once and next to the numbers it qualifies.
    """
    if not isinstance(summary, dict):
        return
    value = summary.get("overfitting_risk")
    print(f"Overfitting Risk: {_format_overfitting_risk(value)}")
    reason = summary.get("overfitting_risk_reason")
    if reason:
        print(f"{indent}Reason: {reason}")


def _selection_window_remedy(
    validation_method: str,
    context: Optional[Dict[str, Any]],
) -> str:
    """The remedy for "the windows did not give the strategy room to trade".

    The remedy has to name the flags of the path that produced the
    windows: the standalone `cpcv` and `walk-forward` subcommands and the
    `out-of-sample` subcommand spell the same settings differently, and a
    remedy that names a flag the user cannot pass is not a remedy.

    Shared by the "no parameter could be selected" diagnosis and the
    partial-selection diagnosis, so both name the same knobs.
    """
    flags = (context or {}).get("cli_flags") or {}
    if validation_method == "cpcv":
        test_size_flag = flags.get("test_size", "--test-size")
        n_splits_flag = flags.get("n_splits", "--n-splits")
        return (
            f"raise {test_size_flag} (it is the fraction of each group "
            f"used as the test set) or lower {n_splits_flag} so a fold's "
            f"test window holds enough bars for the strategy to take a "
            f"position"
        )
    test_months_flag = flags.get("test_months", "--test-months")
    return (
        "shorten the indicator lookbacks in the parameter grid, use a "
        f"longer {test_months_flag} window, or give the training "
        "split more history"
    )


def _selection_training_remedy(
    validation_method: str,
    context: Optional[Dict[str, Any]],
) -> str:
    """The remedy for "the training split produced no estimable Sharpe".

    The training split is what the selection ranks on, so a training split
    with a constant return series cannot be repaired by changing the
    out-of-sample window: the training split needs more history (or a
    strategy that is not flat over it). The flags are the ones the path's
    own subcommand accepts.
    """
    flags = (context or {}).get("cli_flags") or {}
    if validation_method == "cpcv":
        n_splits_flag = flags.get("n_splits", "--n-splits")
        return (
            f"raise {n_splits_flag} so every fold trains on more of the "
            f"sample, or use a strategy that does not stay flat over the "
            f"training split"
        )
    train_months_flag = flags.get("train_months", "--train-months")
    return (
        f"raise {train_months_flag} so the training split covers more "
        f"history, or use a strategy that does not stay flat over it"
    )


def _effective_oos_fraction_sentence(
    validation_method: str,
    context: Optional[Dict[str, Any]],
) -> str:
    """The sentence that states CPCV's effective out-of-sample fraction.

    CPCV splits the data into groups and takes a *fraction of each
    group* as the test set, so the effective out-of-sample fraction is
    test_size / n_splits -- not the fraction the flag name suggests. It is
    the usual reason a CPCV window is too short to trade, so the sentence
    is stated whenever the CPCV configuration is known.
    """
    if validation_method != "cpcv":
        return ""
    flags = (context or {}).get("cli_flags") or {}
    test_size_flag = flags.get("test_size", "--test-size")
    n_splits_flag = flags.get("n_splits", "--n-splits")
    n_splits = (context or {}).get("cpcv_n_splits")
    test_size = (context or {}).get("cpcv_test_size")
    if not n_splits or test_size is None:
        return ""
    return (
        f" With {test_size_flag} {test_size} and {n_splits_flag} "
        f"{n_splits}, the effective out-of-sample fraction is "
        f"{test_size}/{n_splits} = {test_size / n_splits:.4g} of the "
        f"data, because the test size is the fraction of each group."
    )


def _diagnose_no_selection(
    validation_results: Dict[str, Any],
    validation_method: str,
    param_grid: Dict[str, List[Any]],
    train_data: pd.DataFrame,
    wf_window: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Explain why the validation phase selected no parameters.

    "No valid parameters selected from validation phase" is a symptom, not a
    diagnosis: the two usual causes (the walk-forward window does not fit the
    training split, and every grid combination stays flat over the
    out-of-sample window) call for completely different remedies, so the
    cause is reported explicitly instead of being collapsed into one message.

    The same vocabulary is used by every path that can end up selecting
    nothing: the out-of-sample framework (whose validation phase runs inside
    the training split) and the standalone walk-forward and CPCV analyses.
    ``context`` carries the configuration of the path that asks (the analysis
    path, and the split/window settings that produced the windows); it is
    recorded in ``details`` and, for CPCV, it also produces the sentence that
    states the effective out-of-sample fraction, because that fraction is the
    usual reason a CPCV window is too short to trade.

    ``train_data`` is the data the selection ran on: the training split for
    the out-of-sample path, the whole sample for the standalone paths. Its
    length is reported as ``details["train_split_bars"]``.
    """
    windows = (
        (validation_results.get("periods") or [])
        if validation_method == "walk_forward"
        else (validation_results.get("folds") or [])
    )
    n_windows = len(windows)
    n_with_params = len([w for w in windows if w.get("best_params") is not None])

    window_bars: List[int] = []
    for window in windows:
        test_data = window.get("test_data")
        if test_data is not None:
            window_bars.append(int(len(test_data)))

    details: Dict[str, Any] = {
        "validation_method": validation_method,
        "n_validation_windows": n_windows,
        "n_windows_with_selected_params": n_with_params,
        "train_split_bars": int(len(train_data)) if train_data is not None else 0,
        "param_grid": param_grid,
    }
    if window_bars:
        details["validation_window_bars"] = window_bars
    if wf_window is not None:
        details["walk_forward_window"] = wf_window
    if context:
        details.update(context)

    if n_windows == 0:
        cause = "no_validation_windows"
        if wf_window is not None and wf_window.get("reason"):
            message = (
                "The walk-forward validation phase produced no out-of-sample "
                f"period: {wf_window['reason']}."
            )
        else:
            message = (
                f"The {validation_method} analysis produced no out-of-sample "
                "window, so no parameter could be selected."
            )
    else:
        cause = "no_position_in_validation_window"
        longest = max(window_bars) if window_bars else 0
        # The remedy names the flags of the path that produced the
        # windows: the standalone `cpcv` and `walk-forward` subcommands and
        # the `out-of-sample` subcommand spell the same settings
        # differently, and a remedy that names a flag the user cannot pass
        # is not a remedy.
        remedy = _selection_window_remedy(validation_method, context)
        message = (
            f"The {validation_method} analysis produced {n_windows} "
            f"out-of-sample window(s) but no parameter combination took a "
            f"position in any of them (the longest window holds {longest} "
            f"bars). A combination is skipped when the strategy stays flat "
            f"over the whole window, which usually means the indicator "
            f"warm-up is longer than the window: {remedy}."
        )
        # CPCV splits the data into groups and takes a *fraction of each
        # group* as the test set, so the effective out-of-sample fraction is
        # test_size / n_splits -- not the fraction the flag name suggests.
        # State it, because it is the usual reason the window is too short.
        message += _effective_oos_fraction_sentence(validation_method, context)
    return {"cause": cause, "message": message, "details": details}


def _window_date_text(value: Any) -> str:
    """The date of a window boundary, as text.

    The window records carry ``pandas`` timestamps; the artifact has to be
    JSON-serialisable and readable, so the date part is what is reported.
    """
    if value is None:
        return "unknown"
    try:
        return str(pd.Timestamp(value).date())
    except Exception:
        return str(value)


def _diagnose_partial_selection(
    validation_results: Dict[str, Any],
    validation_method: str,
    param_grid: Dict[str, List[Any]],
    train_data: pd.DataFrame,
    wf_window: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Explain the windows in which no parameter could be selected.

    "2 of 5 folds selected" is not a finding on its own. It is compatible
    with "the other three folds were too short to trade" (a design
    problem) and with "the strategy never triggers on 60% of the sample"
    (a finding about the strategy), and the two call for completely
    different remedies. The count alone therefore does not say what
    happened, so every flat window is reported with the cause the grid
    search itself measured and the evidence for it.

    The cause vocabulary is the one the "no parameter could be selected"
    diagnosis already uses, extended with the two causes that diagnosis
    cannot tell apart:

    * ``no_position_in_validation_window`` -- no combination took a
      position in the window. The window is either shorter than every
      window in which the strategy did trade (``window_too_short``, a
      window fact) or at least as long as the shortest one
      (``signal_never_triggered``, a strategy fact);
    * ``no_estimable_training_sharpe`` -- every combination took a
      position, but the training split produced a constant return series,
      so the in-sample Sharpe the selection ranks on is undefined;
    * ``all_combinations_failed`` -- every combination failed to build or
      to be evaluated.

    The per-window cause is the one the search's own tally attributes to
    the window (recorded on the period / fold record as
    ``selection_outcomes``), so the diagnosis states a *measured* cause
    instead of inferring one from an empty result: a window with no
    selection and no position and a window with no selection but a
    constant training series look identical from the outside and need
    opposite remedies.

    Returns ``None`` when the run is not in the partial state: a run in
    which every window selected a parameter has nothing to explain, and a
    run in which no window selected one is the ``no_selection_diagnosis``
    case, not this one.
    """
    windows = (
        (validation_results.get("periods") or [])
        if validation_method == "walk_forward"
        else (validation_results.get("folds") or [])
    )
    n_windows = len(windows)
    selected = [w for w in windows if w.get("best_params") is not None]
    n_with_params = len(selected)
    if n_windows == 0 or n_with_params == 0 or n_with_params == n_windows:
        return None

    flat = [
        (index, window)
        for index, window in enumerate(windows)
        if window.get("best_params") is None
    ]

    # The bars of the windows in which the strategy did trade. The
    # comparison against the flat windows separates "the window was too
    # short to trade" (a window fact) from "the signal never triggered on
    # the window" (a strategy fact).
    traded_bars = [
        int(len(w["test_data"]))
        for w in selected
        if w.get("test_data") is not None
    ]
    min_traded_bars = min(traded_bars) if traded_bars else None
    traded_position_bars = [
        int(w["position_bars"])
        for w in selected
        if w.get("position_bars") is not None
    ]
    min_traded_position_bars = min(traded_position_bars) if traded_position_bars else None

    noun = (context or {}).get("window_noun") or (
        "fold" if validation_method == "cpcv" else "period"
    )

    flat_records: List[Dict[str, Any]] = []
    for index, window in flat:
        outcomes = window.get("selection_outcomes") or {}
        tally = {
            cause: int(outcomes.get(outcome, 0))
            for outcome, cause in _COMBO_OUTCOME_CAUSES.items()
        }
        # The cause the search's own tally attributes to this window. A tie
        # is broken by the order the causes are listed in, so the verdict
        # is deterministic.
        if any(tally.values()):
            cause = max(tally, key=lambda key: tally[key])
        else:
            # No tally (a window record without one): fall back to the
            # vocabulary's default cause.
            cause = "no_position_in_validation_window"

        test_data = window.get("test_data")
        train_window = window.get("train_data")
        bars = int(len(test_data)) if test_data is not None else 0
        train_bars = int(len(train_window)) if train_window is not None else 0
        test_returns = window.get("test_returns")
        returns_bars = 0 if test_returns is None else int(len(test_returns))
        max_position_bars = window.get("max_position_bars")

        if cause == "no_position_in_validation_window":
            if min_traded_bars is not None and bars < min_traded_bars:
                reason = "window_too_short"
            else:
                reason = "signal_never_triggered"
        elif cause == "no_estimable_training_sharpe":
            reason = "training_sharpe_not_estimable"
        else:
            reason = "all_combinations_failed"

        if reason == "window_too_short":
            length_clause = (
                f"the window is shorter than every window in which the "
                f"strategy traded ({bars} bars against {min_traded_bars} "
                f"bars), so the window length cannot be ruled out as the "
                f"cause"
            )
        elif reason == "signal_never_triggered":
            length_clause = (
                f"the window holds at least as many bars as the shortest "
                f"window in which the strategy traded ({min_traded_bars} "
                f"bars), so its length does not by itself explain the "
                f"failure: the signal never triggered on it"
            )
        elif reason == "training_sharpe_not_estimable":
            length_clause = (
                f"the training split of this window holds {train_bars} bars "
                f"and produced a constant return series, so the in-sample "
                f"Sharpe the selection ranks on is undefined"
            )
        else:
            length_clause = (
                "every parameter combination raised an error while it was "
                "evaluated"
            )

        text = (
            f"{noun.capitalize()} {index} ({bars} bars, "
            f"{_window_date_text(window.get('test_start'))} to "
            f"{_window_date_text(window.get('test_end'))}): "
            f"{_PARTIAL_CAUSE_TEXT[cause]} ({returns_bars} out-of-sample "
            f"return bars"
        )
        if max_position_bars is not None:
            text += f", {max_position_bars} bars with a position"
        text += f"); {length_clause}."

        flat_records.append({
            "window": index,
            "fold": window.get("fold"),
            "cause": cause,
            "reason": reason,
            "bars": bars,
            "train_bars": train_bars,
            "test_returns_bars": returns_bars,
            "test_sharpe": window.get("test_sharpe"),
            "max_position_bars": max_position_bars,
            "test_start": _window_date_text(window.get("test_start")),
            "test_end": _window_date_text(window.get("test_end")),
            "outcome_tally": tally,
            "text": text,
        })

    n_flat = len(flat_records)
    cause_counts: Dict[str, int] = {}
    for record in flat_records:
        cause_counts[record["cause"]] = cause_counts.get(record["cause"], 0) + 1
    dominant = max(cause_counts, key=lambda key: cause_counts[key])

    if len(cause_counts) == 1:
        cause_clause = (
            f"Every flat {noun} has the same cause ({dominant}): "
            f"{_PARTIAL_CAUSE_TEXT[dominant]}."
        )
    else:
        parts = ", ".join(
            f"{count} with cause {cause}" for cause, count in sorted(cause_counts.items())
        )
        cause_clause = (
            f"The flat {noun}s do not share one cause ({parts})."
        )

    basis = (context or {}).get("selection_basis") or "the result"
    if basis == "overfitting_risk_verdict":
        basis_clause = (
            f"the overfitting-risk verdict rests on {n_with_params} of the "
            f"{n_windows} out-of-sample {noun}s"
        )
    elif basis == "selected_parameter":
        basis_clause = (
            f"the selected parameter was chosen from the {n_with_params} of "
            f"the {n_windows} validation {noun}s that could select one"
        )
    else:
        basis_clause = (
            f"the result rests on {n_with_params} of the {n_windows} "
            f"out-of-sample {noun}s"
        )
    if min_traded_position_bars is not None:
        basis_clause += (
            f", and the thinnest of them held a position for only "
            f"{min_traded_position_bars} "
            f"{'bar' if min_traded_position_bars == 1 else 'bars'}"
        )
    basis_clause += "."

    remedy_parts: List[str] = []
    flat_causes = {record["cause"] for record in flat_records}
    if "no_position_in_validation_window" in flat_causes:
        if all(
            record["reason"] == "signal_never_triggered"
            for record in flat_records
            if record["cause"] == "no_position_in_validation_window"
        ):
            remedy_parts.append(
                "To give the strategy room to trade, "
                f"{_selection_window_remedy(validation_method, context)} -- but "
                f"the flat {noun}s are already as long as the {noun}s in which "
                f"the strategy traded, so if the signal never triggers on that "
                f"stretch of the sample, no window length will change the "
                f"outcome."
            )
        else:
            remedy_parts.append(
                "To give the strategy room to trade, "
                f"{_selection_window_remedy(validation_method, context)}."
            )
    if "no_estimable_training_sharpe" in flat_causes:
        remedy_parts.append(
            f"The training split is what is broken in at least one flat "
            f"{noun}: "
            f"{_selection_training_remedy(validation_method, context)}."
        )
    if "all_combinations_failed" in flat_causes:
        remedy_parts.append(
            f"The parameter grid itself is the problem in at least one flat "
            f"{noun}: every combination failed, so the values in the grid "
            f"have to be checked before any result of this run can be read."
        )
    remedy_clause = " ".join(remedy_parts)

    message = (
        f"The {validation_method} analysis selected a parameter in "
        f"{n_with_params} of its {n_windows} out-of-sample {noun}s; the "
        f"other {n_flat} produced no selection. {cause_clause} So "
        f"{basis_clause} {remedy_clause}"
    )

    # The windows the verdict rests on: how many bars they held and how
    # many of them carried a position. A verdict measured on two windows
    # that traded for a single bar each is a different statement from a
    # verdict measured on two windows the strategy traded throughout.
    traded_records = [
        {
            "window": index,
            "bars": int(len(w["test_data"])) if w.get("test_data") is not None else 0,
            "position_bars": w.get("position_bars"),
            "test_sharpe": w.get("test_sharpe"),
            "test_start": _window_date_text(w.get("test_start")),
            "test_end": _window_date_text(w.get("test_end")),
        }
        for index, w in enumerate(windows)
        if w.get("best_params") is not None
    ]

    details: Dict[str, Any] = {
        "validation_method": validation_method,
        "n_validation_windows": n_windows,
        "n_windows_with_selected_params": n_with_params,
        "n_flat_windows": n_flat,
        "flat_windows": flat_records,
        "traded_windows": traded_records,
        "flat_window_causes": cause_counts,
        "dominant_cause": dominant,
        "min_traded_window_bars": min_traded_bars,
        "min_traded_position_bars": min_traded_position_bars,
        "traded_window_bars": traded_bars,
        "train_split_bars": int(len(train_data)) if train_data is not None else 0,
        "param_grid": param_grid,
    }
    if wf_window is not None:
        details["walk_forward_window"] = wf_window
    if context:
        details.update(context)

    return {
        "cause": dominant,
        "message": message,
        "details": details,
    }


def _thin_evidence_warning(
    windows: List[Dict[str, Any]],
    warmup_bars: int,
    *,
    window_noun: str = "window",
    threshold: float = 0.2,
) -> Optional[Dict[str, Any]]:
    """Does the run's verdict rest on windows the strategy barely traded in?

    A verdict measured on windows in which the strategy held a position for
    only a handful of bars is a much weaker statement than the same verdict
    measured on windows it traded throughout -- and the difference is not
    visible in any number the artifact already reports. ``position_bars`` is
    a per-window measurement and the aggregate Sharpe / stability ratio
    hides it, so a "low" overfitting-risk rating earned on two windows that
    each traded for one bar reads as a finding about the strategy when it is
    mostly a finding about the windows. This surfaces that, as a
    measurement: it changes no number.

    The threshold is expressed in *executable* bars, not raw window bars, so
    it is stable across the two warmup conventions. The walk-forward path
    drops ``latency + 2`` leading bars from every window before the strategy
    can act on them; run_backtest drops one. A 20-bar window that the
    walk-forward path reports as holding a position for 1 bar therefore has
    18 executable bars left, and the question is whether the position count
    is a small fraction of *that*.

    Args:
        windows: The windows that selected a parameter, each carrying at
            least ``position_bars`` and ``bars`` (the shape the
            partial-selection diagnosis already builds in
            ``traded_windows``).
        warmup_bars: The number of leading bars the run's warmup convention
            makes non-tradable (``execution_warmup_bars``).
        window_noun: "period" / "fold" / "window", for the message.
        threshold: The maximum position count, as a fraction of the
            executable window, that counts as "thin". Default 0.2.

    Returns:
        ``None`` when every window the verdict rests on traded in at least
        ``threshold`` of its executable bars, otherwise a dict with
        ``message`` and ``details`` recording the thin windows and the
        fraction of executable bars each held a position.
    """
    if not windows:
        return None

    warmup_bars = int(warmup_bars or 0)
    thin: List[Dict[str, Any]] = []
    for window in windows:
        position_bars = window.get("position_bars")
        bars = window.get("bars")
        if position_bars is None or bars is None:
            continue
        executable = max(int(bars) - warmup_bars, 0)
        if executable <= 0:
            # Nothing tradable in the window at all: the position count is
            # not a fraction of an executable window, so there is nothing
            # thin to report here (the window is flat, which the
            # partial-selection diagnosis already names).
            continue
        fraction = float(position_bars) / float(executable)
        if fraction <= threshold:
            thin.append(
                {
                    "window": window.get("window"),
                    "bars": int(bars),
                    "executable_bars": executable,
                    "position_bars": int(position_bars),
                    "position_fraction_of_executable": round(fraction, 4),
                    "test_sharpe": window.get("test_sharpe"),
                    "test_start": window.get("test_start"),
                    "test_end": window.get("test_end"),
                }
            )

    if not thin:
        return None

    n_thin = len(thin)
    n_total = len(windows)
    min_fraction = min(t["position_fraction_of_executable"] for t in thin)
    max_fraction = max(t["position_fraction_of_executable"] for t in thin)

    if n_thin == n_total:
        scope = (
            f"every one of the {n_total} {window_noun}s the verdict rests on"
        )
    else:
        scope = (
            f"{n_thin} of the {n_total} {window_noun}s the verdict rests on"
        )

    message = (
        f"The verdict rests on {scope} in which the strategy held a "
        f"position for {min_fraction:.0%} to {max_fraction:.0%} of the "
        f"executable bars (at most {threshold:.0%} of each window, after "
        f"the {warmup_bars} warmup bar(s) this run drops are removed). A "
        f"verdict measured on windows the strategy barely traded in is weak "
        f"evidence: it says little about the strategy and more about the "
        f"windows it was measured on. The reported numbers are unchanged -- "
        f"this is a measurement of how much evidence the verdict has, not a "
        f"correction to it."
    )

    return {
        "message": message,
        "details": {
            "n_windows_with_selected_params": n_total,
            "n_thin_windows": n_thin,
            "thin_windows": thin,
            "max_position_fraction_of_executable": round(max_fraction, 4),
            "min_position_fraction_of_executable": round(min_fraction, 4),
            "warmup_bars": warmup_bars,
            "threshold": float(threshold),
            "window_noun": window_noun,
        },
    }


def _thin_evidence_failure(
    summary: Dict[str, Any],
    min_position_fraction: Optional[float],
) -> Optional[Dict[str, Any]]:
    """Reject a run whose verdict rests on thin evidence.

    When ``--min-position-fraction`` is set and the thin-evidence warning the
    run would emit has a `details.min_position_fraction_of_executable` below
    the threshold, record a `thin_evidence_failure` on the summary so the
    artifact and the console say why the run was rejected. The failure
    reuses `_selection_window_remedy` for the flag names, so the remedy names
    the flags of the path that produced the windows.

    Returns the failure record, or None when the run passes (flag unset, no
    warning, or the warning's thinnest window clears the threshold).
    """
    if min_position_fraction is None:
        return None
    warning = summary.get("thin_evidence_warning")
    if not isinstance(warning, dict):
        return None
    details = warning.get("details") or {}
    actual = details.get("min_position_fraction_of_executable")
    if actual is None:
        return None
    if float(actual) >= float(min_position_fraction):
        return None

    diagnosis = summary.get("partial_selection_diagnosis") or {}
    diagnosis_details = diagnosis.get("details") or {}
    context = {"cli_flags": diagnosis_details.get("cli_flags") or {}}
    validation_method = diagnosis_details.get("validation_method") or ""
    remedy = _selection_window_remedy(validation_method, context)

    message = (
        f"The verdict rests on windows the strategy held a position for "
        f"{float(actual):.0%} of their executable bars at most, below the "
        f"--min-position-fraction {min_position_fraction:.0%} floor. A "
        f"verdict measured on windows the strategy barely traded in is weak "
        f"evidence: it says little about the strategy and more about the "
        f"windows it was measured on, so the run is rejected. {remedy}."
    )

    failure = {
        "cause": "thin_evidence",
        "message": message,
        "details": {
            "min_position_fraction_of_executable": round(float(actual), 4),
            "min_position_fraction_requested": round(float(min_position_fraction), 4),
            "n_thin_windows": details.get("n_thin_windows"),
            "n_windows_with_selected_params": details.get(
                "n_windows_with_selected_params"
            ),
            "thin_windows": details.get("thin_windows"),
            "warning": warning,
        },
    }
    summary["thin_evidence_failure"] = failure
    return failure


def out_of_sample_validation(
    data: Union[pd.DataFrame, dict],
    strategy_factory: Callable,
    param_grid: Dict[str, List[Any]],
    train_frac: float = 0.6,
    val_frac: float = 0.2,
    test_frac: float = 0.2,
    validation_method: str = "walk_forward",
    walk_forward_train_months: int = 12,
    walk_forward_test_months: int = 3,
    walk_forward_step_months: int = 3,
    cpcv_n_splits: int = 10,
    cpcv_test_size: float = 0.1,
    cpcv_purge_size: float = 0.0,
    cpcv_embargo_size: float = 0.0,
    selection_criterion: str = "best_oos_sharpe",
    initial_capital: float = 100000,
    commission: float = 0.0002,
    slippage: float = 0.0001,
    impact_coefficient: float = 0.0,
    adv_window: int = 20,
    borrow_cost: float = 0.0,
    funding_cost: float = 0.0,
    latency: int = 0,
    fill_rate: float = 1.0,
    apply_deflation: bool = False,
    benchmark: Optional[List[pd.DataFrame]] = None,
    total_return_benchmark: bool = False,
    benchmark_commission: float = 0.0,
    benchmark_slippage: float = 0.0,
    benchmark_expense_ratio: float = 0.0,
    benchmark_cost_is_periodic: bool = False,
    validate_pit: bool = True,
    panel_pricing: str = "net-exposure",
    impact_aggregation=DEFAULT_IMPACT_AGGREGATION,
    **kwargs,
) -> Dict[str, Any]:
    """
    Perform rigorous out-of-sample validation with chronological train/validation/test split.

    This function implements a three-phase validation framework to prevent data leakage:
    1. TRAIN: Walk-forward analysis or CPCV on the training portion to select optimal parameters
    2. VALIDATE: Evaluate selected parameters on the validation portion (confirmation)
    3. TEST: Final evaluation on the held-out test set (never used in any selection step)

    Args:
        data: OHLCV DataFrame indexed by date (or dict panel)
        strategy_factory: Function that creates a strategy from params dict
        param_grid: Dictionary of parameter name -> list of values to search
        train_frac: Fraction of data for training (default 0.6)
        val_frac: Fraction of data for validation (default 0.2)
        test_frac: Fraction of data for testing (default 0.2)
        validation_method: "walk_forward" or "cpcv" for parameter selection on training data
        walk_forward_train_months: Training window size in months for walk-forward
        walk_forward_test_months: Testing window size in months for walk-forward
        walk_forward_step_months: Step size between walk-forward iterations
        cpcv_n_splits: Number of sequential groups for CPCV
        cpcv_test_size: Fraction of each group to use as test set in CPCV
        cpcv_purge_size: Fraction of observations to purge from training around test
        cpcv_embargo_size: Fraction of observations to embargo after test set
        selection_criterion: How to select final params from validation results:
            - "best_oos_sharpe": Best out-of-sample Sharpe from walk-forward/CPCV
            - "most_stable": Most frequently selected params across periods/folds
            - "best_avg_sharpe": Best average Sharpe across periods/folds
        initial_capital: Starting portfolio value
        commission: Commission rate per trade
        slippage: Slippage rate per trade
        impact_coefficient: Market impact coefficient
        adv_window: Rolling window for Average Daily Volume calculation
        borrow_cost: Annual borrow cost rate for short positions
        funding_cost: Annual funding cost rate for leveraged positions
        latency: Execution latency in periods passed to _calculate_strategy_returns.
            Positions are delayed by `1 + latency` periods after signal generation.
            Default 0 (no added delay beyond the standard next-period fill).
        fill_rate: Position-scale limit (participation rate) in (0, 1]. The
            achieved position is ``fill_rate * target_position`` on every bar,
            so every position-change-based cost (commission, slippage, market
            impact) and every exposure-based cost (borrow, funding) scales
            with it. Default 1.0 (full fill, backward compatible).

            This is a *position-size (leverage) lever*, not a partial-fill
            execution model: the held position is reset to ``fill_rate *
            target`` each bar instead of converging toward the target
            (``position_t = position_{t-1} + fill_rate * (target_t -
            position_{t-1})``), and the unfilled part of the order is not
            charged anything. Sweeping ``fill_rate`` therefore measures
            leverage sensitivity, not execution realism -- the Sharpe ratio is
            not scale-invariant because the risk-free rate is subtracted from
            the scaled return and is not scaled with it. See
            `references/validation_methods.md`, "Fill rate: decided convention".
            passed to _calculate_strategy_returns. Default 1.0 (full fill).
        apply_deflation: Compute Deflated Sharpe Ratio for multiple-testing correction
        benchmark: Optional list of benchmark OHLCV DataFrames for buy-and-hold comparison. When multiple benchmarks are provided, alpha p-values are corrected for multiple comparisons using a Deflated Alpha analogue.
        total_return_benchmark: Compute benchmark returns using total return (dividends + price)
        benchmark_commission: Commission per trade for benchmark (applies to all benchmarks if multiple provided)
        benchmark_slippage: Slippage per trade for benchmark (applies to all benchmarks if multiple provided)
        benchmark_expense_ratio: Annual expense ratio for benchmark (as decimal, e.g., 0.005 for 0.5%) (applies to all benchmarks if multiple provided)
        validate_pit: When True, run point-in-time validation (look-ahead /
            stale-data / temporal-ordering screening) on the input data and
            record the result in `results["point_in_time_validation"]` and
            `summary["bias_controls_engaged"]`. Default True on the programmatic
            API; default True (CLI parity, non-strict: warns, never aborts).

    Returns:
        Dictionary with:
            - 'train_val_test_split': Dict with split boundaries and sizes
            - 'validation_results': Full results from walk_forward_analysis or cpcv_analysis on training data
            - 'selected_params': Parameters selected by the selection criterion
            - 'validation_performance': Performance of selected params on validation data
            - 'test_performance': Final performance on held-out test data
            - 'test_benchmark': Benchmark comparison on test data (if benchmark provided). When multiple benchmarks are provided, this is a list of benchmark comparisons, and the summary includes multiple-testing correction for benchmark alpha.
            - 'summary': Aggregate summary with key metrics, deflated Sharpe, and deflated alpha p-values when multiple benchmarks are provided
    """
    # Fail fast on invalid execution-realism parameters rather than silently
    # skipping every grid combination inside the per-combo try/except below.
    if fill_rate is None:
        fill_rate = 1.0
    if fill_rate <= 0 or fill_rate > 1:
        raise ValueError(f"fill_rate must be in (0, 1], got {fill_rate}")
    if latency is None:
        latency = 0
    if latency < 0:
        latency = 0
    panel_pricing = resolve_panel_pricing(panel_pricing)

    # Normalize data format
    if isinstance(data, dict):
        data = _dict_to_multiindex(data)

    if isinstance(data.columns, pd.MultiIndex):
        if not isinstance(data.index, pd.DatetimeIndex):
            try:
                data.index = pd.DatetimeIndex(data.index)
            except Exception:
                pass
        data = data.sort_index()
    else:
        if not isinstance(data.index, pd.DatetimeIndex):
            raise ValueError("Data must be indexed by DatetimeIndex")
        data = data.sort_index()

    # Point-in-time validation (look-ahead / stale-data / temporal-ordering
    # screening). Opt-in on the programmatic API; the CLI engages it via
    # _load_and_validate_data (validate_pit=True by default).
    pit_results = None
    if validate_pit:
        pit_results = validate_point_in_time(data)
        if pit_results["violations"]:
            print("Point-in-time validation violations:")
            for violation in pit_results["violations"]:
                print(f"  - {violation}")
        if pit_results["warnings"]:
            print("Point-in-time validation warnings:")
            for warning in pit_results["warnings"]:
                print(f"  - {warning}")
        if not pit_results["violations"] and not pit_results["warnings"]:
            print("Point-in-time validation passed (no violations or warnings).")
        elif not pit_results["violations"]:
            print("Point-in-time validation passed (no violations).")

    # Split data chronologically
    train_data, val_data, test_data = _split_train_val_test(
        data, train_frac, val_frac, test_frac
    )

    # Record split boundaries
    split_info = {
        "train_start": train_data.index[0],
        "train_end": train_data.index[-1],
        "val_start": val_data.index[0],
        "val_end": val_data.index[-1],
        "test_start": test_data.index[0],
        "test_end": test_data.index[-1],
        "train_size": len(train_data),
        "val_size": len(val_data),
        "test_size": len(test_data),
        "train_frac": train_frac,
        "val_frac": val_frac,
        "test_frac": test_frac,
    }

    # Executable invariant: assert the three splits are pairwise disjoint
    # and chronologically ordered. A leak here would silently invalidate
    # the "held-out test set has never been used in any selection step"
    # guarantee, so the check result is recorded in the summary for audit.
    separation_check = _verify_split_separation(train_data, val_data, test_data)
    split_info["separation_check"] = separation_check

    # Phase 1: VALIDATION - Run walk-forward or CPCV on training data
    wf_window = None
    if validation_method == "walk_forward":
        # The walk-forward window has to fit the *training split* (the
        # validation phase runs inside it). When the requested window is
        # longer than the training split it produces zero periods, so no
        # parameter can be selected and the run aborts with a message that
        # hides the cause. The window is therefore resolved against the
        # training split first: unchanged when it fits, otherwise shortened
        # on the training side only, and the resolution is reported and
        # recorded (an adapted window is a methodology choice).
        wf_window = _resolve_walk_forward_window(
            train_data,
            walk_forward_train_months,
            walk_forward_test_months,
            walk_forward_step_months,
        )
        if wf_window["adapted"]:
            print(
                f"Walk-forward window adapted to the training split: "
                f"train {wf_window['requested']['train_months']} -> "
                f"{wf_window['effective']['train_months']} month(s) "
                f"(test {wf_window['effective']['test_months']}, "
                f"step {wf_window['effective']['step_months']}), "
                f"{wf_window['effective_periods']} period(s). "
                f"Reason: {wf_window['reason']}"
            )
        validation_results = walk_forward_analysis(
            data=train_data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            train_months=wf_window["effective"]["train_months"],
            test_months=wf_window["effective"]["test_months"],
            step_months=wf_window["effective"]["step_months"],
            initial_capital=initial_capital,
            commission=commission,
            slippage=slippage,
            impact_coefficient=impact_coefficient,
            adv_window=adv_window,
            borrow_cost=borrow_cost,
            funding_cost=funding_cost,
            latency=latency,
            fill_rate=fill_rate,
            apply_deflation=apply_deflation,
            benchmark=benchmark,
            total_return_benchmark=total_return_benchmark,
            benchmark_commission=benchmark_commission,
            benchmark_slippage=benchmark_slippage,
            benchmark_expense_ratio=benchmark_expense_ratio,
            panel_pricing=panel_pricing,
        )
    elif validation_method == "cpcv":
        validation_results = cpcv_analysis(
            data=train_data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            n_splits=cpcv_n_splits,
            test_size=cpcv_test_size,
            purge_size=cpcv_purge_size,
            embargo_size=cpcv_embargo_size,
            initial_capital=initial_capital,
            commission=commission,
            slippage=slippage,
            impact_coefficient=impact_coefficient,
            adv_window=adv_window,
            borrow_cost=borrow_cost,
            funding_cost=funding_cost,
            latency=latency,
            fill_rate=fill_rate,
            apply_deflation=apply_deflation,
            panel_pricing=panel_pricing,
        )
    else:
        raise ValueError(f"Unknown validation_method: {validation_method}. Use 'walk_forward' or 'cpcv'.")

    # A grid key whose values do not change the strategy's behaviour is a
    # null experiment: the "search" over it cannot change any result, yet the
    # artifact would still report it as a selected parameter. The finding is
    # recorded and reported so the selection is never mistaken for evidence.
    # The measurement is taken on the training split, which is where the
    # selection happens.
    inert_report = _inert_grid_report(
        strategy_factory, param_grid, train_data, scope="on the training split"
    )
    inert_grid_params = inert_report["inert_grid_params"]

    # The validation phase runs inside the training split, so the CPCV
    # configuration that produced its windows is the one the diagnosis
    # has to state: the effective out-of-sample fraction is
    # test_size / n_splits, not the fraction the flag name suggests.
    _diagnosis_context = {"analysis_path": "out_of_sample"}
    if validation_method == "cpcv":
        _diagnosis_context.update({
            "cpcv_n_splits": cpcv_n_splits,
            "cpcv_test_size": cpcv_test_size,
            "cpcv_purge_size": cpcv_purge_size,
            "cpcv_embargo_size": cpcv_embargo_size,
            "cli_flags": {
                "n_splits": "--cpcv-n-splits",
                "test_size": "--cpcv-test-size",
            },
        })
    else:
        _diagnosis_context.update({
            "walk_forward_train_months": walk_forward_train_months,
            "walk_forward_test_months": walk_forward_test_months,
            "walk_forward_step_months": walk_forward_step_months,
            "cli_flags": {
                "train_months": "--wf-train-months",
                "test_months": "--wf-test-months",
                "step_months": "--wf-step-months",
            },
        })

    # Phase 2: SELECTION - Select best parameters based on criterion
    selected_params = _select_parameters(
        validation_results=validation_results,
        validation_method=validation_method,
        criterion=selection_criterion,
    )
    if selected_params is None:
        # The validation phase runs inside the training split, so the CPCV
        # configuration that produced its windows is the one the diagnosis
        # has to state: the effective out-of-sample fraction is
        # test_size / n_splits, not the fraction the flag name suggests.
        diagnosis = _diagnose_no_selection(
            validation_results=validation_results,
            validation_method=validation_method,
            param_grid=param_grid,
            train_data=train_data,
            wf_window=wf_window,
            context=_diagnosis_context,
        )
        print(f"No valid parameters selected from validation phase: {diagnosis['message']}")
        return {
            "train_val_test_split": split_info,
            "validation_results": validation_results,
            "selected_params": None,
            "validation_performance": None,
            "test_performance": None,
            "test_benchmark": None,
            "summary": {
                "error": diagnosis["message"],
                "no_selection_diagnosis": diagnosis,
                "inert_grid_params": inert_grid_params,
                "inert_grid_message": inert_report["message"],
                "walk_forward_window": wf_window,
                "train_val_test_split": split_info,
            },
        }

    # Phase 3: CONFIRMATION - Evaluate selected params on validation data
    strategy = strategy_factory(selected_params)
    val_signals = strategy.generate_signals(val_data)
    val_book_weights = (
        strategy_target_weights(strategy, val_data)
        if panel_pricing == "book"
        else None
    )
    val_returns = _calculate_strategy_returns(
        val_data, val_signals, commission, slippage,
        impact_coefficient, adv_window, borrow_cost, funding_cost,
        latency, fill_rate,
                initial_capital=initial_capital,
                panel_pricing=panel_pricing,
                impact_aggregation=impact_aggregation,
                book_weights=val_book_weights,
            )

    ann_factor = _annualization_factor(val_returns.index)
    excess = val_returns - 0.02 / ann_factor
    val_sharpe = float(excess.mean() / excess.std() * np.sqrt(ann_factor)) if len(val_returns) > 1 and not _is_constant_returns(val_returns) else 0.0
    val_total_return = float((1 + val_returns).prod() - 1) if len(val_returns) > 0 else 0.0

    # Per-split market-impact capacity estimates. The validation and test
    # windows are separate market regimes, so the capacity that the strategy
    # could have supported in each window is reported separately (mirroring
    # the per-period capacity that `walk_forward_analysis` records). None
    # when impact is disabled or ADV is not estimable.
    val_capacity = estimate_capacity(
        val_data, impact_coefficient, adv_window=adv_window
    )
    val_capacity_point = val_capacity.get("estimated_capacity")
    val_capacity_trend = val_capacity.get("capacity_trend")
    # Book-based capacity for the validation window: the capacity implied by
    # the trade sizes the selected strategy actually executes, next to the
    # basket-based number above. Reported in the "book" pricing mode only.
    val_capacity_book = None
    val_capacity_book_trend = None
    val_capacity_book_nw = None
    val_capacity_book_nw_trend = None
    if panel_pricing == "book":
        _val_book_capacity = _window_book_capacity(
            strategy_factory,
            selected_params,
            val_data,
            impact_coefficient=impact_coefficient,
            adv_window=adv_window,
            latency=latency,
            fill_rate=fill_rate,
            impact_aggregation=impact_aggregation,
        )
        if _val_book_capacity is not None:
            val_capacity_book = _val_book_capacity.get("estimated_capacity")
            val_capacity_book_trend = _val_book_capacity.get("capacity_trend")
            val_capacity_book_nw = _val_book_capacity.get(
                "estimated_capacity_notional_weighted"
            )
            val_capacity_book_nw_trend = _val_book_capacity.get(
                "capacity_notional_weighted_trend"
            )

    validation_performance = {
        "selected_params": selected_params,
        "val_total_return": val_total_return,
        "val_sharpe": val_sharpe,
        "val_volatility": float(val_returns.std() * np.sqrt(ann_factor)) if len(val_returns) > 1 else 0.0,
        "val_n_periods": len(val_returns),
        "capacity": val_capacity_point,
        "capacity_trend": val_capacity_trend,
        # Book-based capacity for the validation window (see above).
        "capacity_book": val_capacity_book,
        "capacity_book_trend": val_capacity_book_trend,
        # Notional-weighted book capacity for the validation window (the
        # capacity consistent with the dollar-consistent impact charge).
        "capacity_book_notional_weighted": val_capacity_book_nw,
        "capacity_book_notional_weighted_trend": val_capacity_book_nw_trend,
        # Panel book diagnostic for the validation window: the per-asset
        # book the selected strategy holds, measured against the
        # framework's net-exposure pricing of the same window. None when
        # the strategy exposes no book. Measurement only.
        "book_diagnostic": _window_book_diagnostic(
            strategy_factory,
            selected_params,
            val_data,
            val_returns,
            latency=latency,
            fill_rate=fill_rate,
            panel_pricing=panel_pricing,
            impact_coefficient=impact_coefficient,
            adv_window=adv_window,
            initial_capital=initial_capital,
            impact_aggregation=impact_aggregation,
        ),
    }

    # Phase 4: FINAL TEST - Evaluate on held-out test data
    test_signals = strategy.generate_signals(test_data)
    test_book_weights = (
        strategy_target_weights(strategy, test_data)
        if panel_pricing == "book"
        else None
    )
    test_returns = _calculate_strategy_returns(
                    test_data, test_signals, commission, slippage,
                    impact_coefficient, adv_window, borrow_cost, funding_cost,
                    latency, fill_rate,
                    initial_capital=initial_capital,
                    panel_pricing=panel_pricing,
                    impact_aggregation=impact_aggregation,
                    book_weights=test_book_weights,
                )

    ann_factor_test = _annualization_factor(test_returns.index)
    excess_test = test_returns - 0.02 / ann_factor_test

    test_sharpe = float(excess_test.mean() / excess_test.std() * np.sqrt(ann_factor_test)) if len(test_returns) > 1 and not _is_constant_returns(test_returns) else 0.0
    test_total_return = float((1 + test_returns).prod() - 1) if len(test_returns) > 0 else 0.0

    test_capacity = estimate_capacity(
        test_data, impact_coefficient, adv_window=adv_window
    )
    test_capacity_point = test_capacity.get("estimated_capacity")
    test_capacity_trend = test_capacity.get("capacity_trend")
    # Book-based capacity for the held-out test window: the capacity implied
    # by the trade sizes the selected strategy actually executes. Reported in
    # the "book" pricing mode only.
    test_capacity_book = None
    test_capacity_book_trend = None
    test_capacity_book_nw = None
    test_capacity_book_nw_trend = None
    if panel_pricing == "book":
        _test_book_capacity = _window_book_capacity(
            strategy_factory,
            selected_params,
            test_data,
            impact_coefficient=impact_coefficient,
            adv_window=adv_window,
            latency=latency,
            fill_rate=fill_rate,
            impact_aggregation=impact_aggregation,
        )
        if _test_book_capacity is not None:
            test_capacity_book = _test_book_capacity.get("estimated_capacity")
            test_capacity_book_trend = _test_book_capacity.get("capacity_trend")
            test_capacity_book_nw = _test_book_capacity.get(
                "estimated_capacity_notional_weighted"
            )
            test_capacity_book_nw_trend = _test_book_capacity.get(
                "capacity_notional_weighted_trend"
            )

    test_performance = {
     "test_total_return": test_total_return,
         "test_sharpe": test_sharpe,
         "test_volatility": float(test_returns.std() * np.sqrt(ann_factor_test)) if len(test_returns) > 1 else 0.0,
         # The held-out window is counted in OBSERVATIONS (one per return
         # observation, e.g. one daily bar), not in independent periods. The
         # two are not interchangeable: 100 daily bars are not 100
         # independent periods, and the resolution arithmetic (min
         # detectable Sharpe / alpha) needs the observation count. The
         # walk-forward PERIOD count lives in `summary["n_periods"]`.
         "test_n_observations": len(test_returns),
         "test_returns": test_returns,
         "capacity": test_capacity_point,
         "capacity_trend": test_capacity_trend,
         # Book-based capacity for the held-out test window (see above).
         "capacity_book": test_capacity_book,
         "capacity_book_trend": test_capacity_book_trend,
         # Notional-weighted book capacity for the held-out test window.
         "capacity_book_notional_weighted": test_capacity_book_nw,
         "capacity_book_notional_weighted_trend": test_capacity_book_nw_trend,
         # Panel book diagnostic for the held-out test window. Measurement
         # only -- the reported test performance is unchanged.
         "book_diagnostic": _window_book_diagnostic(
             strategy_factory,
             selected_params,
             test_data,
             test_returns,
             latency=latency,
             fill_rate=fill_rate,
             panel_pricing=panel_pricing,
             impact_coefficient=impact_coefficient,
             adv_window=adv_window,
             initial_capital=initial_capital,
             impact_aggregation=impact_aggregation,
         ),
     }

    # Benchmark comparison on test set
    test_benchmark = None
    correction_result = None
    if benchmark is not None and len(test_returns) > 0:
        if isinstance(benchmark, list):
            # Use the shared helper for multiple-testing correction
            correction_result = _benchmark_list_alpha_correction(
                test_returns, benchmark,
                total_return_benchmark=total_return_benchmark,
                benchmark_commission=benchmark_commission,
                benchmark_slippage=benchmark_slippage,
                benchmark_expense_ratio=benchmark_expense_ratio,
                benchmark_cost_is_periodic=benchmark_cost_is_periodic,
            )
            test_benchmark = correction_result["per_benchmark"]
            # Preserve backward compatibility: keep the list of deflated alphas
            # and also provide the canonical single deflated_alpha for the primary benchmark
        else:
            # Single benchmark (backward compatibility)
            benchmark_returns = _compute_benchmark_returns(benchmark, test_returns, total_return_benchmark)
            if benchmark_returns is not None:
                if "splits" in benchmark.columns:
                    test_benchmark = _benchmark_stats_with_splits(
                        test_returns, benchmark_returns, ann_factor_test,
                        total_return_benchmark=total_return_benchmark,
                        benchmark_commission=benchmark_commission,
                        benchmark_slippage=benchmark_slippage,
                        benchmark_expense_ratio=benchmark_expense_ratio,
                        benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                        benchmark_data=benchmark,
                    )
                else:
                    test_benchmark = _benchmark_stats(
                        test_returns, benchmark_returns, ann_factor_test,
                        total_return_benchmark=total_return_benchmark,
                        benchmark_commission=benchmark_commission,
                        benchmark_slippage=benchmark_slippage,
                        benchmark_expense_ratio=benchmark_expense_ratio,
                        benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                    )
                test_performance.update(test_benchmark)
    summary = {
        "train_val_test_split": split_info,
        "validation_method": validation_method,
        "selection_criterion": selection_criterion,
        "selected_params": selected_params,
        "validation_total_return": val_total_return,
        "validation_sharpe": val_sharpe,
        # Per-window market-impact capacity estimates. The aggregate
        # `capacity` key below is computed on the full sample; these two are
        # computed on the validation and held-out test windows only, so a
        # capacity collapse in the unseen test window stays visible.
        "validation_capacity": val_capacity_point,
        "test_capacity": test_capacity_point,
        # Notional-weighted book capacity for the validation and test windows
        # (the capacity consistent with the dollar-consistent impact charge).
        "validation_capacity_notional_weighted": val_capacity_book_nw,
        "test_capacity_notional_weighted": test_capacity_book_nw,
        # Capacity trends for the same two windows: the distribution of the
        # per-period capacity readings inside each window, so a liquidity
        # squeeze *within* a window is visible too (the point-in-time
        # `*_capacity` keys only read the last bar of the window).
        "validation_capacity_trend": val_capacity_trend,
        "test_capacity_trend": test_capacity_trend,
        "validation_capacity_notional_weighted_trend": val_capacity_book_nw_trend,
        "test_capacity_notional_weighted_trend": test_capacity_book_nw_trend,
        # Panel book diagnostics for the two windows: the per-asset book
        # the selected strategy holds against the framework's net-exposure
        # pricing. The aggregate below covers both windows; the test window
        # is the out-of-sample one. Measurement only.
        "validation_book_diagnostic": validation_performance.get("book_diagnostic"),
        "test_book_diagnostic": test_performance.get("book_diagnostic"),
        "test_total_return": test_total_return,
        "test_sharpe": test_sharpe,
        "test_volatility": test_performance["test_volatility"],
        # Average OUT-OF-SAMPLE test Sharpe of the selected parameter set
        # across the validation periods/folds where it was chosen. This is
        # the out-of-sample analogue of the old in-sample "best_avg_sharpe"
        # selection criterion and is computed from `test_sharpe` (OOS), never
        # from `best_sharpe` (in-sample training fit). None when the selected
        # combo was never chosen in any period/fold, or when every such
        # period's test_sharpe is None (degenerate test windows).
        "selected_params_avg_test_sharpe": _selected_params_avg_test_sharpe(
            validation_results, validation_method, selected_params
        ),
    }

    # A validation phase in which *some* windows could select a parameter and
    # others could not has to say which windows were flat and why: the
    # selected parameter was then chosen from fewer windows than the
    # validation phase had, and the count alone does not say what happened
    # in the flat ones. The measurement changes no number.
    _partial_diagnosis = _diagnose_partial_selection(
        validation_results=validation_results,
        validation_method=validation_method,
        param_grid=param_grid,
        train_data=train_data,
        wf_window=wf_window,
        context=dict(
            _diagnosis_context,
            window_noun="fold" if validation_method == "cpcv" else "period",
            selection_basis="selected_parameter",
        ),
    )
    if _partial_diagnosis is not None:
        summary["partial_selection_diagnosis"] = _partial_diagnosis
        # The selected parameter was chosen from the windows that could
        # select one, and the verdict on it rests on how much of those
        # windows the strategy actually traded in. The aggregate Sharpe
        # and stability ratio hide that: a "low" rating earned on two
        # windows that each traded for one bar says little about the
        # strategy. Measurement only -- it changes no number.
        _warmup_bars = execution_warmup_metadata(
            WARMUP_CONVENTION_WALK_FORWARD, latency
        )["execution_warmup_bars"]
        _thin = _thin_evidence_warning(
            _partial_diagnosis["details"].get("traded_windows", []),
            _warmup_bars,
            window_noun=_partial_diagnosis["details"].get(
                "window_noun", "window"
            ),
        )
        if _thin is not None:
            summary["thin_evidence_warning"] = _thin

    # Add multiple benchmark information to summary if applicable
    if isinstance(test_benchmark, list):
        summary["multiple_benchmarks"] = True
        summary["benchmark_count"] = len(test_benchmark)
        # Reuse correction_result directly rather than re-iterating test_benchmark
        # to rebuild the same fields: correction_result already holds the
        # per-benchmark stats and the aggregate Deflated Alpha (it is the same
        # object as test_benchmark in this branch), so the backward-compatible
        # summary keys are derived from it in one place. This mirrors the
        # cpcv_analysis / walk_forward_analysis aggregate path, which never
        # re-looped.
        per_benchmark = (
            correction_result["per_benchmark"]
            if correction_result is not None
            else test_benchmark
        )
        summary["benchmark_metrics"] = per_benchmark
        if correction_result is not None:
            alpha_pvalues = [
                b["alpha_pvalue"]
                for b in per_benchmark
                if b is not None and "alpha_pvalue" in b
            ]
            alpha_pvalues_original = [
                b["alpha_pvalue_original"]
                for b in per_benchmark
                if b is not None and "alpha_pvalue_original" in b
            ]
            # deflated_alphas preserves the backward-compatible list of full
            # per-benchmark dicts (each carried through the correction).
            deflated_alphas = [
                b
                for b in per_benchmark
                if b is not None and "alpha_pvalue_original" in b
            ]
            expected_max_alphas = [
                b["expected_max_alpha"]
                for b in per_benchmark
                if b is not None and "expected_max_alpha" in b
            ]
            if alpha_pvalues:
                summary["alpha_pvalues"] = alpha_pvalues
                if alpha_pvalues_original:
                    summary["alpha_pvalues_original"] = alpha_pvalues_original
            if deflated_alphas:
                summary["deflated_alphas"] = deflated_alphas
            if expected_max_alphas:
                summary["expected_max_alphas"] = expected_max_alphas

            # Canonical aggregate Deflated Alpha (n_benchmarks, DAR, p_value,
            # ...), consistent with the CPCV / walk-forward pipelines, sourced
            # directly from correction_result instead of a manual re-derivation.
            aggregate_da = correction_result["deflated_alpha"]
            if aggregate_da is not None:
                summary["deflated_alpha"] = aggregate_da
                try:
                    summary["minimum_detectable_alpha"] = minimum_detectable_alpha(
                        summary["deflated_alpha"], test_returns
                    )
                except Exception:
                    pass
                primary_bench = (
                    per_benchmark[0]
                    if per_benchmark and per_benchmark[0] is not None
                    else None
                )
                if primary_bench is not None:
                    for key in ("alpha_pvalue", "alpha_pvalue_original",
                                "expected_max_alpha"):
                        if key in primary_bench:
                            summary[key] = primary_bench[key]

    # Add Deflated Sharpe Ratio on test returns if requested
    # n_trials = total configurations evaluated in validation phase.
    #
    # The trial Sharpes from the validation-phase grid searches are pooled
    # across periods/folds and forwarded to `deflated_sharpe_ratio` so the
    # cross-sectional dispersion of the actually-evaluated Sharpes estimates
    # the expected max Sharpe under the null (SR*). This makes the OOS
    # aggregate correction use the same SR* estimator as
    # `walk_forward_analysis` / `cpcv_analysis` (which pool their own
    # period/fold trial Sharpes), so the reported DSR / p-value is
    # comparable across all four analysis paths on the same grid and data.
    # When a period/fold has no recorded trial Sharpes (e.g. `apply_deflation`
    # was off in the validation phase, or every combo was skipped), fall back
    # to the full grid size for that period/fold and use the i.i.d.-normal
    # null approximation (trial_sharpes=None).
    total_trials = 0
    pooled_trial_sharpes: List[float] = []
    if validation_method == "walk_forward":
        for period in validation_results.get("periods", []):
            if period.get("best_params") is not None:
                sharps = period.get("trial_sharpes")
                if sharps:
                    total_trials += len(sharps)
                    pooled_trial_sharpes.extend(float(s) for s in sharps)
                else:
                    total_trials += len(list(product(*param_grid.values())))
    elif validation_method == "cpcv":
        for fold in validation_results.get("folds", []):
            if fold.get("best_params") is not None:
                sharps = fold.get("trial_sharpes")
                if sharps:
                    total_trials += len(sharps)
                    pooled_trial_sharpes.extend(float(s) for s in sharps)
                else:
                    total_trials += len(list(product(*param_grid.values())))

    if apply_deflation and len(test_returns) > 1 and total_trials > 0:
        summary["deflated_sharpe"] = deflated_sharpe_ratio(
            sharpe_ratio=test_sharpe,
            returns=test_returns,
            n_trials=total_trials,
            trial_sharpes=pooled_trial_sharpes if pooled_trial_sharpes else None,
        )
        if summary.get("deflated_sharpe") is not None:
            try:
                summary["minimum_detectable_sharpe"] = minimum_detectable_sharpe(
                    summary["deflated_sharpe"], test_returns
                )
            except Exception:
                pass
    elif apply_deflation and len(test_returns) > 1:
        summary["deflated_sharpe"] = deflated_sharpe_ratio(
            sharpe_ratio=test_sharpe,
            returns=test_returns,
            n_trials=1,
            trial_sharpes=None,
        )
        if summary.get("deflated_sharpe") is not None:
            try:
                summary["minimum_detectable_sharpe"] = minimum_detectable_sharpe(
                    summary["deflated_sharpe"], test_returns
                )
            except Exception:
                pass

    # The resolution of the significance statistics carried by this summary:
    # the smallest annualized Sharpe / alpha the held-out Deflated Sharpe and
    # Deflated Alpha tests could have confirmed at the sample size actually
    # available. A significance test on a small held-out window can only
    # fail, so a reader needs this to tell an informative result from an
    # unfalsifiable one. A measurement, not a correction: it changes no
    # verdict and no reported number.
    summary["test_resolution"] = _build_test_resolution(summary, test_returns)

    # Add benchmark information to summary (only for single benchmark for backward compatibility)
    if test_benchmark and not isinstance(test_benchmark, list):
        summary.update(test_benchmark)

    summary["bias_controls_engaged"] = bool(pit_results is not None)

    # Surface market-impact capacity estimate in the summary when impact is
    # enabled and estimable; keep None (backward compatible) otherwise.
    _capacity = estimate_capacity(data, impact_coefficient, adv_window=adv_window)
    summary["capacity"] = _capacity.get("estimated_capacity")
    # Capacity trend over the whole sample (the per-period / per-fold
    # records carry the same key for their own window).
    summary["capacity_trend"] = _capacity.get("capacity_trend")
    # Book-based capacity: the capacity implied by the trade sizes the
    # selected strategy actually executes in the held-out test window, next
    # to the basket-based number above. The validation window's own book
    # capacity is reported in `validation_performance`.
    summary["capacity_book"] = test_capacity_book
    summary["capacity_book_trend"] = test_capacity_book_trend
    # Panel book diagnostic aggregated over the validation and test
    # windows. None when neither window produced one (single asset, or a
    # strategy that does not expose a book).
    summary["book_diagnostic"] = aggregate_book_diagnostics(
        [
            validation_performance.get("book_diagnostic"),
            test_performance.get("book_diagnostic"),
        ]
    )
    # The pricing convention that produced the reported validation and test
    # P&L.
    summary["panel_pricing"] = panel_pricing
    summary["impact_aggregation"] = impact_aggregation
    # The walk-forward window the validation phase actually ran with, and
    # whether it had to be shortened to fit the training split. Recorded so a
    # result is never read without knowing the window that produced it.
    summary["walk_forward_window"] = wf_window
    # Grid keys that did not change the strategy's behaviour on the training
    # split: a selection over them is a null experiment.
    summary["inert_grid_params"] = inert_grid_params
    summary["inert_grid_message"] = inert_report["message"]
    # The execution warmup this path applied (see the walk-forward summary
    # for the same key).
    summary.update(
        execution_warmup_metadata(WARMUP_CONVENTION_WALK_FORWARD, latency)
    )

    return {
        "train_val_test_split": split_info,
        "validation_results": validation_results,
        "selected_params": selected_params,
        "validation_performance": validation_performance,
        "test_performance": test_performance,
        "test_benchmark": test_benchmark,
        "point_in_time_validation": pit_results,
        "summary": summary,
    }


def _select_parameters(
    validation_results: Dict[str, Any],
    validation_method: str,
    criterion: str = "best_oos_sharpe",
) -> Optional[Dict[str, Any]]:
    """Select optimal parameters from validation results based on criterion.

    Selection criteria that claim to optimize *out-of-sample* quality
    ("best_oos_sharpe", "best_avg_sharpe") must read each period/fold's
    OUT-OF-SAMPLE test Sharpe (``test_sharpe``), never the IN-SAMPLE
    training Sharpe stored under ``best_sharpe``. The grid search ranks
    combos by in-sample fit, so ranking *periods* by ``best_sharpe``
    would select the combo that overfit its training window — the exact
    selection bias the out-of-sample framework exists to avoid.

    "most_stable" is unaffected: it counts how often each combo was
    selected by the in-sample grid search, which is a property of the
    optimizer, not of the test data.
    """
    if validation_method == "walk_forward":
        periods = validation_results.get("periods", [])
        valid_periods = [p for p in periods if p.get("best_params") is not None]

        if not valid_periods:
            return None

        if criterion == "best_oos_sharpe":
            # Select params from period with best OUT-OF-SAMPLE test Sharpe.
            def _oos_key(p):
                s = p.get("test_sharpe")
                return s if s is not None else -np.inf
            best_period = max(valid_periods, key=_oos_key)
            return best_period["best_params"]

        elif criterion == "most_stable":
            # Most frequently selected params across periods
            from collections import Counter
            param_tuples = [tuple(sorted(p["best_params"].items())) for p in valid_periods]
            if param_tuples:
                most_common = Counter(param_tuples).most_common(1)[0][0]
                return dict(most_common)
            return None

        elif criterion == "best_avg_sharpe":
            # Params with best AVERAGE OUT-OF-SAMPLE test Sharpe across the
            # periods where they were selected. Averages only periods that
            # carry a finite test_sharpe; periods where it is None (e.g. a
            # degenerate test window) are excluded rather than treated as 0.
            from collections import defaultdict
            param_sharpes = defaultdict(list)
            for p in valid_periods:
                key = tuple(sorted(p["best_params"].items()))
                s = p.get("test_sharpe")
                if s is not None:
                    param_sharpes[key].append(s)

            if not param_sharpes:
                return None
            best_key = max(param_sharpes.keys(), key=lambda k: np.mean(param_sharpes[k]))
            return dict(best_key)

    elif validation_method == "cpcv":
        folds = validation_results.get("folds", [])
        valid_folds = [f for f in folds if f.get("best_params") is not None]

        if not valid_folds:
            return None

        if criterion == "best_oos_sharpe":
            def _oos_key(f):
                s = f.get("test_sharpe")
                return s if s is not None else -np.inf
            best_fold = max(valid_folds, key=_oos_key)
            return best_fold["best_params"]

        elif criterion == "most_stable":
            from collections import Counter
            param_tuples = [tuple(sorted(f["best_params"].items())) for f in valid_folds]
            if param_tuples:
                most_common = Counter(param_tuples).most_common(1)[0][0]
                return dict(most_common)
            return None

        elif criterion == "best_avg_sharpe":
            from collections import defaultdict
            param_sharpes = defaultdict(list)
            for f in valid_folds:
                key = tuple(sorted(f["best_params"].items()))
                s = f.get("test_sharpe")
                if s is not None:
                    param_sharpes[key].append(s)

            if not param_sharpes:
                return None
            best_key = max(param_sharpes.keys(), key=lambda k: np.mean(param_sharpes[k]))
            return dict(best_key)

    # Default fallback
    if validation_method == "walk_forward" and validation_results.get("periods"):
        for p in validation_results["periods"]:
            if p.get("best_params") is not None:
                return p["best_params"]
    elif validation_method == "cpcv" and validation_results.get("folds"):
        for f in validation_results["folds"]:
            if f.get("best_params") is not None:
                return f["best_params"]

    return None


def _walk_forward_sweep_coefficient(args, data, benchmark, total_return_benchmark,
                                    bench_commission, bench_slippage, bench_expense_ratio,
                                    impact_coefficient, borrow_cost=None, funding_cost=None,
                                    commission=None, slippage=None, latency=None, fill_rate=None,
                                    survivorship=None):
    """Run walk-forward for a single cost coefficient (sweep helper).

    No file I/O or stdout; returns the per-coefficient metrics used by the
    sweep table and JSON artifact. Mirrors the single-run body of run_walk_forward
    for one coefficient value.

    `borrow_cost` / `funding_cost` / `commission` / `slippage` default to the
    CLI args when None, so the same helper serves the market-impact sweep (which
    varies only `impact_coefficient`) and the borrow/funding sweeps.

    `latency` / `fill_rate` default to the CLI args when None, so the same
    helper serves the latency / fill-rate sweeps (which vary only one of those
    while leaving the other at its single-run value).

    `survivorship` carries the survivorship-bias detection report from the
    caller so the sweep artifact records the same bias-controls signal as the
    single-run walk-forward summary.
    """
    if borrow_cost is None:
        borrow_cost = args.borrow_cost
    if funding_cost is None:
        funding_cost = args.funding_cost
    if commission is None:
        commission = args.commission
    if slippage is None:
        slippage = args.slippage
    if latency is None:
        latency = getattr(args, "latency", 0)
    if latency is None:
        latency = 0
    if latency < 0:
        latency = 0
    if fill_rate is None:
        fill_rate = getattr(args, "fill_rate", 1.0)
    if fill_rate is None:
        fill_rate = 1.0
    if fill_rate <= 0 or fill_rate > 1:
        raise ValueError(f"fill_rate must be in (0, 1], got {fill_rate}")
    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    results = walk_forward_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        train_months=args.train_months,
        test_months=args.test_months,
        step_months=args.step_months,
        initial_capital=args.initial_capital,
        commission=commission,
        slippage=slippage,
        impact_coefficient=impact_coefficient,
        adv_window=args.adv_window,
        borrow_cost=borrow_cost,
        funding_cost=funding_cost,
        latency=latency,
        fill_rate=fill_rate,
        apply_deflation=args.deflate,
        benchmark=benchmark,
        total_return_benchmark=total_return_benchmark,
        benchmark_commission=bench_commission,
        benchmark_slippage=bench_slippage,
        benchmark_expense_ratio=bench_expense_ratio,
        benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
        panel_pricing=getattr(args, "panel_pricing", "net-exposure"),
        impact_aggregation=getattr(args, "impact_aggregation", "panel"),
    )
    summary = results["summary"]
    dsr = summary.get("deflated_sharpe")
    return {
        "impact_coefficient": float(impact_coefficient),
        "borrow_cost": float(borrow_cost),
        "funding_cost": float(funding_cost),
        "commission": float(commission),
        "slippage": float(slippage),
        "latency": int(latency),
        "fill_rate": float(fill_rate),
        # Grid keys that did not change the strategy's behaviour: the
        # per-period selection over them is a null experiment, so the sweep
        # artifact says so too.
        "inert_grid_params": list(summary.get("inert_grid_params") or []),
        "total_oos_return": (
            None
            if summary.get("total_oos_return") is None
            else float(summary.get("total_oos_return", 0.0))
        ),
        "oos_sharpe": (
            float(summary["oos_sharpe"]) if summary.get("oos_sharpe") is not None else None
        ),
        "deflated_sharpe": (
            float(dsr["deflated_sharpe_ratio"]) if dsr is not None else None
        ),
        "deflated_sharpe_n_trials": (
            int(dsr["n_trials"]) if dsr is not None and dsr.get("n_trials") is not None else None
        ),
        "n_periods": int(summary.get("n_periods", 0)),
        # Bias-controls engagement flag (point-in-time validation + multiple-
        # testing deflation). Propagated from the walk-forward summary so the
        # sweep artifact is traceable to the same signal as the single-run
        # summary JSON.
        "bias_controls_engaged": bool(summary.get("bias_controls_engaged", False)),
        # Survivorship-bias detection report (multi-symbol panels). Threaded
        # through so a panel walk-forward sweep is traceable to the universe
        # selection risk flagged at load time.
        "survivorship_bias": survivorship,
        # Test resolution of this sweep point's own statistics: the walk-forward
        # analysis builds summary["test_resolution"] on its out-of-sample
        # returns, the same series its Deflated Sharpe was computed on. The flag
        # compares this point's OOS Sharpe against that resolution on magnitudes;
        # it is a statement about the sample, not a verdict on the point, and is
        # None ("unknown") when the run carried no significance test.
        "test_resolution": summary.get("test_resolution"),
        "sharpe_below_resolution": _sweep_sharpe_below_resolution(
            None if summary.get("oos_sharpe") is None else float(summary["oos_sharpe"]),
            summary.get("test_resolution"),
        ),
    }


def _optimize_sweep_coefficient(args, data, benchmark, total_return_benchmark,
                                bench_commission, bench_slippage, bench_expense_ratio,
                                impact_coefficient, borrow_cost=None, funding_cost=None,
                                commission=None, slippage=None, latency=None, fill_rate=None,
                                pit_results=None, survivorship=None):
    """Run parameter optimization for a single cost coefficient (sweep helper).

    No file I/O or stdout; returns the per-coefficient metrics used by the
    sweep table and JSON artifact. Mirrors the single-run body of
    run_parameter_optimization for one coefficient value.

    `borrow_cost` / `funding_cost` / `commission` / `slippage` default to the
    CLI args when None, so the same helper serves the market-impact sweep
    (which varies only `impact_coefficient`), the borrow/funding sweeps
    (which vary one of those while leaving the others at their single-run
    values), and the commission/slippage sweeps (which vary one of those
    while leaving impact/borrow/funding at their single-run values).

    `latency` / `fill_rate` default to the CLI args when None, so the same
    helper serves the latency / fill-rate sweeps (which vary only one of
    those while leaving the other at its single-run value).

    `pit_results` carries the point-in-time validation outcome from the
    caller so the sweep artifact records the same bias-controls engagement
    flag as the single-run parameter-optimization JSON.
    `survivorship` carries the survivorship-bias detection report from the
    caller so the sweep artifact records the same bias-controls signal as the
    single-run JSON.
    """
    if borrow_cost is None:
        borrow_cost = args.borrow_cost
    if funding_cost is None:
        funding_cost = args.funding_cost
    if commission is None:
        commission = args.commission
    if slippage is None:
        slippage = args.slippage
    if latency is None:
        latency = getattr(args, "latency", 0)
    if latency is None:
        latency = 0
    if latency < 0:
        latency = 0
    if fill_rate is None:
        fill_rate = getattr(args, "fill_rate", 1.0)
    if fill_rate is None:
        fill_rate = 1.0
    if fill_rate <= 0 or fill_rate > 1:
        raise ValueError(f"fill_rate must be in (0, 1], got {fill_rate}")
    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    # The inert-grid measurement is requested so the sweep artifact records
    # it next to the ranking it qualifies. The helper performs no I/O and no
    # printing, so the sweep stays silent and the artifact stays explicit.
    inert_report: Dict[str, Any] = {}
    results = parameter_optimization(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        commission=commission,
        slippage=slippage,
        impact_coefficient=impact_coefficient,
        adv_window=args.adv_window,
        borrow_cost=borrow_cost,
        funding_cost=funding_cost,
        latency=latency,
        fill_rate=fill_rate,
        apply_deflation=args.deflate,
        benchmark=benchmark,
        total_return_benchmark=total_return_benchmark,
        benchmark_commission=bench_commission,
        benchmark_slippage=bench_slippage,
        benchmark_expense_ratio=bench_expense_ratio,
        benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
        panel_pricing=getattr(args, "panel_pricing", "net-exposure"),
        impact_aggregation=getattr(args, "impact_aggregation", "panel"),
        inert_grid_report=inert_report,
    )
    top = results[0] if results else None
    dsr = top.get("deflated_sharpe") if isinstance(top, dict) else None
    return {
        "impact_coefficient": float(impact_coefficient),
        "borrow_cost": float(borrow_cost),
        "funding_cost": float(funding_cost),
        "commission": float(commission),
        "slippage": float(slippage),
        "latency": int(latency),
        "fill_rate": float(fill_rate),
        "top_sharpe": (float(top["sharpe_ratio"]) if top is not None else None),
        "top_total_return": (float(top["total_return"]) if top is not None else None),
        "n_combos": int(len(results)),
        # Grid keys that did not change the strategy's behaviour: the ranking
        # over them is a null experiment, so the sweep artifact says so too.
        "inert_grid_params": list(inert_report.get("inert_grid_params") or []),
        # Deflated Sharpe Ratio (multiple-testing correction) of the best
        # combination, corrected for all evaluated combos (n_trials = len(
        # results)). Mirrors the deflated_sharpe key each optimization result
        # carries when apply_deflation is set.
        "deflated_sharpe": (
            float(dsr["deflated_sharpe_ratio"]) if isinstance(dsr, dict) else None
        ),
        "deflated_sharpe_n_trials": (
            int(dsr["n_trials"])
            if isinstance(dsr, dict) and dsr.get("n_trials") is not None
            else None
        ),
        # Bias-controls engagement flag (point-in-time validation + multiple-
        # testing deflation). Propagated from the caller so the sweep artifact
        # is traceable to the same signal as the single-run JSON.
        "bias_controls_engaged": bool(pit_results is not None or survivorship is not None),
        # Survivorship-bias detection report (multi-symbol panels). Threaded
        # through so a panel optimization sweep is traceable to the universe
        # selection risk flagged at load time.
        "survivorship_bias": survivorship,
        # Parameter optimization's top_sharpe is an in-sample selection
        # statistic over the grid: the resolution that belongs to it is the
        # resolution of the selection itself (the trials searched), not of a
        # held-out series, and this helper holds no held-out returns to build
        # one on. The sweep therefore reports the number as explicitly
        # unresolved: no resolution block, and the flag is None ("unknown"),
        # never "not below".
        "test_resolution": None,
        "sharpe_below_resolution": None,
    }


def _oos_sweep_coefficient(args, data, benchmark, total_return_benchmark,
                           bench_commission, bench_slippage, bench_expense_ratio,
                           impact_coefficient, borrow_cost=None, funding_cost=None,
                           commission=None, slippage=None, latency=None, fill_rate=None,
                           pit_results=None, survivorship=None):
    """Run out-of-sample validation for a single cost coefficient (sweep helper).

    No file I/O or stdout; returns the per-coefficient metrics used by the
    sweep table and JSON artifact. Mirrors the single-run body of
    run_out_of_sample_validation for one coefficient value.

    `borrow_cost` / `funding_cost` / `commission` / `slippage` default to the
    CLI args when None, so the same helper serves the market-impact sweep
    (which varies only `impact_coefficient`), the borrow/funding sweeps
    (which vary one of those while leaving the others at their single-run
    values), and the commission/slippage sweeps (which vary one of those
    while leaving impact/borrow/funding at their single-run values).

    `latency` / `fill_rate` default to the CLI args when None, so the same
    helper serves the latency / fill-rate sweeps (which vary only one of
    those while leaving the other at its single-run value).

    `pit_results` carries the point-in-time validation outcome from the
    caller so the sweep artifact records the same bias-controls engagement
    flag as the single-run out-of-sample JSON.
    `survivorship` carries the survivorship-bias detection report from the
    caller so the sweep artifact records the same bias-controls signal as the
    single-run out-of-sample JSON.
    """
    if borrow_cost is None:
        borrow_cost = args.borrow_cost
    if funding_cost is None:
        funding_cost = args.funding_cost
    if commission is None:
        commission = args.commission
    if slippage is None:
        slippage = args.slippage
    if latency is None:
        latency = getattr(args, "latency", 0)
    if latency is None:
        latency = 0
    if latency < 0:
        latency = 0
    if fill_rate is None:
        fill_rate = getattr(args, "fill_rate", 1.0)
    if fill_rate is None:
        fill_rate = 1.0
    if fill_rate <= 0 or fill_rate > 1:
        raise ValueError(f"fill_rate must be in (0, 1], got {fill_rate}")
    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    results = out_of_sample_validation(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        train_frac=args.train_frac,
        val_frac=args.val_frac,
        test_frac=args.test_frac,
        validation_method=args.validation_method,
        walk_forward_train_months=args.wf_train_months,
        walk_forward_test_months=args.wf_test_months,
        walk_forward_step_months=args.wf_step_months,
        cpcv_n_splits=args.cpcv_n_splits,
        cpcv_test_size=args.cpcv_test_size,
        cpcv_purge_size=args.cpcv_purge_size,
        cpcv_embargo_size=args.cpcv_embargo_size,
        selection_criterion=args.selection_criterion,
        initial_capital=args.initial_capital,
        commission=commission,
        slippage=slippage,
        impact_coefficient=impact_coefficient,
        adv_window=args.adv_window,
        borrow_cost=borrow_cost,
        funding_cost=funding_cost,
        latency=latency,
        fill_rate=fill_rate,
        apply_deflation=args.deflate,
        benchmark=benchmark,
        total_return_benchmark=total_return_benchmark,
        benchmark_commission=bench_commission,
        benchmark_slippage=bench_slippage,
        benchmark_expense_ratio=bench_expense_ratio,
        benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
        panel_pricing=getattr(args, "panel_pricing", "net-exposure"),
        impact_aggregation=getattr(args, "impact_aggregation", "panel"),
    )
    test_perf = results.get("test_performance") or {}
    summary = results.get("summary") or {}
    dsr = summary.get("deflated_sharpe")
    return {
        "impact_coefficient": float(impact_coefficient),
        "borrow_cost": float(borrow_cost),
        "funding_cost": float(funding_cost),
        "commission": float(commission),
        "slippage": float(slippage),
        "latency": int(latency),
        "fill_rate": float(fill_rate),
        "test_total_return": float(test_perf.get("test_total_return", 0.0)),
        "test_sharpe": (
            float(test_perf["test_sharpe"]) if test_perf.get("test_sharpe") is not None else None
        ),
        # Grid keys that did not change the strategy's behaviour: the
        # selection over them is a null experiment, so the sweep artifact says
        # so too.
        "inert_grid_params": list(summary.get("inert_grid_params") or []),
        "deflated_sharpe": (
            float(dsr["deflated_sharpe_ratio"]) if dsr is not None else None
        ),
        "deflated_sharpe_n_trials": (
            int(dsr["n_trials"]) if dsr is not None and dsr.get("n_trials") is not None else None
        ),
        # Bias-controls engagement flag (point-in-time validation + multiple-
        # testing deflation). Propagated from the out-of-sample summary so the
        # sweep artifact is traceable to the same signal as the single-run
        # summary JSON.
        "bias_controls_engaged": bool(summary.get("bias_controls_engaged", False) or survivorship is not None),
        # Survivorship-bias detection report (multi-symbol panels). Threaded
        # through so a panel out-of-sample sweep is traceable to the universe
        # selection risk flagged at load time.
        "survivorship_bias": survivorship,
        # Test resolution of this sweep point's own statistics: the out-of-sample
        # validation builds summary["test_resolution"] on its held-out test
        # returns, the same series its Deflated Sharpe was computed on. The flag
        # compares this point's test Sharpe against that resolution on magnitudes;
        # it is a statement about the sample, not a verdict on the point, and is
        # None ("unknown") when the run carried no significance test.
        "test_resolution": summary.get("test_resolution"),
        "sharpe_below_resolution": _sweep_sharpe_below_resolution(
            None if test_perf.get("test_sharpe") is None else float(test_perf["test_sharpe"]),
            summary.get("test_resolution"),
        ),
    }


def _cpcv_sweep_coefficient(args, data, benchmark, total_return_benchmark,
                            bench_commission, bench_slippage, bench_expense_ratio,
                            impact_coefficient, borrow_cost=None, funding_cost=None,
                            commission=None, slippage=None, latency=None, fill_rate=None,
                            survivorship=None):
    """Run CPCV for a single cost coefficient (sweep helper).

    No file I/O or stdout; returns the per-coefficient metrics used by the
    sweep table and JSON artifact. Mirrors the single-run body of run_cpcv
    for one coefficient value.

    `borrow_cost` / `funding_cost` / `commission` / `slippage` default to the
    CLI args when None, so the same helper serves the market-impact sweep
    (which varies only `impact_coefficient`), the borrow/funding sweeps
    (which vary one of those while leaving impact at its single-run value),
    and the commission/slippage sweeps (which vary one of those while leaving
    impact/borrow/funding at their single-run values).

    `latency` / `fill_rate` default to the CLI args when None, so the same
    helper serves the latency / fill-rate sweeps (which vary only one of
    those while leaving the other at its single-run value).

    `survivorship` carries the survivorship-bias detection report from the
    caller so the sweep artifact records the same bias-controls signal as the
    single-run CPCV summary.
    """
    if borrow_cost is None:
        borrow_cost = args.borrow_cost
    if funding_cost is None:
        funding_cost = args.funding_cost
    if commission is None:
        commission = args.commission
    if slippage is None:
        slippage = args.slippage
    if latency is None:
        latency = getattr(args, "latency", 0)
    if latency is None:
        latency = 0
    if latency < 0:
        latency = 0
    if fill_rate is None:
        fill_rate = getattr(args, "fill_rate", 1.0)
    if fill_rate is None:
        fill_rate = 1.0
    if fill_rate <= 0 or fill_rate > 1:
        raise ValueError(f"fill_rate must be in (0, 1], got {fill_rate}")
    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    results = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=args.n_splits,
        test_size=args.test_size,
        purge_size=args.purge_size,
        embargo_size=args.embargo_size,
        commission=commission,
        slippage=slippage,
        impact_coefficient=impact_coefficient,
        adv_window=args.adv_window,
        borrow_cost=borrow_cost,
        funding_cost=funding_cost,
        latency=latency,
        fill_rate=fill_rate,
        apply_deflation=args.deflate,
        benchmark=benchmark,
        total_return_benchmark=total_return_benchmark,
        benchmark_commission=bench_commission,
        benchmark_slippage=bench_slippage,
        benchmark_expense_ratio=bench_expense_ratio,
        benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
        panel_pricing=getattr(args, "panel_pricing", "net-exposure"),
        impact_aggregation=getattr(args, "impact_aggregation", "panel"),
    )
    summary = results["summary"]
    dsr = summary.get("deflated_sharpe")
    return {
        "impact_coefficient": float(impact_coefficient),
        "borrow_cost": float(borrow_cost),
        "funding_cost": float(funding_cost),
        "commission": float(commission),
        "slippage": float(slippage),
        "latency": int(latency),
        "fill_rate": float(fill_rate),
        "total_oos_return": (
            None
            if summary.get("total_oos_return") is None
            else float(summary.get("total_oos_return", 0.0))
        ),
        "oos_sharpe": (
            float(summary["oos_sharpe"]) if summary.get("oos_sharpe") is not None else None
        ),
        "avg_param_stability": float(summary.get("avg_param_stability", 0.0)),
        "overfitting_risk": summary.get("overfitting_risk"),
        # Grid keys that did not change the strategy's behaviour: the
        # per-fold selection over them is a null experiment, so the sweep
        # artifact says so too.
        "inert_grid_params": list(summary.get("inert_grid_params") or []),
        "deflated_sharpe": (
            float(dsr["deflated_sharpe_ratio"]) if dsr is not None else None
        ),
        "deflated_sharpe_n_trials": (
            int(dsr["n_trials"]) if dsr is not None and dsr.get("n_trials") is not None else None
        ),
        "n_folds": int(summary.get("n_folds", 0)),
        # Bias-controls engagement flag (point-in-time validation + multiple-
        # testing deflation). Propagated from the CPCV summary so the sweep
        # artifact is traceable to the same signal as the single-run summary
        # JSON.
        "bias_controls_engaged": bool(summary.get("bias_controls_engaged", False)),
        # Survivorship-bias detection report (multi-symbol panels). Threaded
        # through so a panel CPCV sweep is traceable to the universe selection
        # risk flagged at load time.
        "survivorship_bias": survivorship,
        # Test resolution of this sweep point's own statistics: the CPCV
        # analysis builds summary["test_resolution"] on its pooled out-of-sample
        # returns, the same series its Deflated Sharpe was computed on. The flag
        # compares this point's OOS Sharpe against that resolution on magnitudes;
        # it is a statement about the sample, not a verdict on the point, and is
        # None ("unknown") when the run carried no significance test.
        "test_resolution": summary.get("test_resolution"),
        "sharpe_below_resolution": _sweep_sharpe_below_resolution(
            None if summary.get("oos_sharpe") is None else float(summary["oos_sharpe"]),
            summary.get("test_resolution"),
        ),
    }


def run_cpcv(args) -> int:
    """Run CPCV analysis from CLI args."""
    print(f"Loading data from {args.data}...")
    data, pit_results, survivorship = _load_and_validate_data(
        args.data, args.symbol, args.start, args.end,
        validate_pit=getattr(args, "validate_point_in_time", True),
        pit_strict=getattr(args, "point_in_time_strict", False),
        multi_symbol=getattr(args, "multi_symbol", False),
    )

    # Load benchmark if provided
    benchmark = None
    benchmark_provenance = None
    total_return_benchmark = getattr(args, "total_return_benchmark", False)
    bench_commission = getattr(args, "benchmark_commission", None) if getattr(args, "benchmark_commission", None) is not None else args.commission
    bench_slippage = getattr(args, "benchmark_slippage", None) if getattr(args, "benchmark_slippage", None) is not None else args.slippage
    bench_expense_ratio = getattr(args, "benchmark_expense_ratio", None) if getattr(args, "benchmark_expense_ratio", None) is not None else 0.0
    if getattr(args, "benchmark", None):
        benchmark_paths = args.benchmark if isinstance(args.benchmark, list) else [args.benchmark]
        print(f"Loading benchmark data from {', '.join(benchmark_paths)}...")
        if len(benchmark_paths) == 1:
            benchmark, benchmark_provenance = _load_benchmark(benchmark_paths[0], total_return_benchmark)
        else:
            benchmark = []
            benchmark_provenance = []
            for bench_file in benchmark_paths:
                b, prov = _load_benchmark(bench_file, total_return_benchmark)
                benchmark.append(b)
                benchmark_provenance.append(prov)

    latency, fill_rate = _resolve_latency_fill_rate(args)
    min_position_fraction = _resolve_min_position_fraction(args)

    impact_coefficients = [float(c) for c in (args.impact_coefficients or [args.impact_coefficient])]

    # Capacity / market-impact sensitivity sweep for CPCV: re-run the CPCV
    # pipeline for each coefficient and record degradation in a single
    # artifact so capacity/impact sensitivity is part of the robustness flow.
    if len(impact_coefficients) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for coeff in impact_coefficients:
            row = _cpcv_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio, coeff,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "cpcv_impact_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"impact_coefficients": impact_coefficients, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nMarket impact sweep ({len(impact_coefficients)} coefficients) saved to: {sweep_path}")
        print("Impact coefficient | Total OOS Return | OOS Sharpe | minSR | note | Avg Param Stability | Overfitting Risk | Deflated Sharpe | N Folds")
        print("-" * 112)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['impact_coefficient']:>17} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {minSR_txt:>9} | {note:>16} | {row['avg_param_stability']:>17.4f} | "
                f"{_format_overfitting_risk(row['overfitting_risk']):>17} | {dsr_txt:>14} | {row['n_folds']:>7}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    borrow_costs = [float(c) for c in (args.borrow_costs or [args.borrow_cost])]
    funding_costs = [float(c) for c in (args.funding_costs or [args.funding_cost])]

    # Borrow-cost sensitivity sweep for CPCV: re-run the CPCV pipeline for
    # each borrow cost and record degradation in a single artifact. Mirrors
    # the market-impact sweep but varies short-position borrow cost.
    if len(borrow_costs) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in borrow_costs:
            row = _cpcv_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=cost, funding_cost=args.funding_cost,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "cpcv_borrow_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"borrow_costs": borrow_costs, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nBorrow-cost sweep ({len(borrow_costs)} costs) saved to: {sweep_path}")
        print("Borrow Cost | Total OOS Return | OOS Sharpe | minSR | note | Avg Param Stability | Overfitting Risk | Deflated Sharpe | N Folds")
        print("-" * 112)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['borrow_cost']:>13.4f} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {minSR_txt:>9} | {note:>16} | {row['avg_param_stability']:>17.4f} | "
                f"{_format_overfitting_risk(row['overfitting_risk']):>17} | {dsr_txt:>14} | {row['n_folds']:>7}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    # Funding-cost sensitivity sweep for CPCV: re-run the CPCV pipeline for
    # each funding cost and record degradation in a single artifact. Varies
    # leveraged-position funding cost while leaving borrow cost at its value.
    if len(funding_costs) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in funding_costs:
            row = _cpcv_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=args.borrow_cost, funding_cost=cost,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "cpcv_funding_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"funding_costs": funding_costs, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nFunding-cost sweep ({len(funding_costs)} costs) saved to: {sweep_path}")
        print("Funding Cost | Total OOS Return | OOS Sharpe | minSR | note | Avg Param Stability | Overfitting Risk | Deflated Sharpe | N Folds")
        print("-" * 112)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['funding_cost']:>13.4f} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {minSR_txt:>9} | {note:>16} | {row['avg_param_stability']:>17.4f} | "
                f"{_format_overfitting_risk(row['overfitting_risk']):>17} | {dsr_txt:>14} | {row['n_folds']:>7}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    borrow_costs = [float(c) for c in (args.borrow_costs or [args.borrow_cost])]
    funding_costs = [float(c) for c in (args.funding_costs or [args.funding_cost])]

    # Execution-latency / partial-fill sweeps for CPCV: re-run the CPCV
    # pipeline for each latency / fill-rate and record degradation in a single
    # artifact. Single value keeps the original path.
    latencies = [int(l) for l in (args.latencies or [args.latency])]
    fill_rates = [float(f) for f in (args.fill_rates or [args.fill_rate])]
    if _run_latency_fill_rate_sweep(
        args,
        runner=lambda v, key: _cpcv_sweep_coefficient(
            args, data, benchmark, total_return_benchmark,
            bench_commission, bench_slippage, bench_expense_ratio,
            args.impact_coefficient, borrow_cost=args.borrow_cost,
            funding_cost=args.funding_cost, **{key: v},
            survivorship=survivorship,
        ),
        latency_values=latencies,
        fill_rate_values=fill_rates,
        latency_artifact="cpcv_latency_sweep.json",
        fill_rate_artifact="cpcv_fill_rate_sweep.json",
        latency_header=["Latency", "Total OOS Return", "OOS Sharpe", "Avg Param Stability", "Overfitting Risk", "Deflated Sharpe", "N Folds"],
        fill_rate_header=["Fill Rate", "Total OOS Return", "OOS Sharpe", "Avg Param Stability", "Overfitting Risk", "Deflated Sharpe", "N Folds"],
        row_cells=lambda row, key: [
            str(row[key]),
            'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:.4f}",
            "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}",
            f"{row['avg_param_stability']:.4f}",
            _format_overfitting_risk(row["overfitting_risk"]),
            "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}",
            str(row["n_folds"]),
        ],
    ):
        return 0

    commissions = [float(c) for c in (args.commissions or [args.commission])]
    slippages = [float(s) for s in (args.slippages or [args.slippage])]

    # Commission sensitivity sweep for CPCV: re-run the CPCV pipeline for each
    # commission rate and record degradation in a single artifact. Varies
    # commission while leaving impact/borrow/funding/slippage at their
    # single-run values.
    if len(commissions) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in commissions:
            row = _cpcv_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=args.borrow_cost,
                funding_cost=args.funding_cost, commission=cost,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "cpcv_commission_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"commissions": commissions, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nCommission sweep ({len(commissions)} rates) saved to: {sweep_path}")
        print("Commission | Total OOS Return | OOS Sharpe | minSR | note | Avg Param Stability | Overfitting Risk | Deflated Sharpe | N Folds")
        print("-" * 112)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['commission']:>13.6f} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {minSR_txt:>9} | {note:>16} | {row['avg_param_stability']:>17.4f} | "
                f"{_format_overfitting_risk(row['overfitting_risk']):>17} | {dsr_txt:>14} | {row['n_folds']:>7}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    # Slippage sensitivity sweep for CPCV: re-run the CPCV pipeline for each
    # slippage rate and record degradation in a single artifact. Varies
    # slippage while leaving impact/borrow/funding/commission at their
    # single-run values.
    if len(slippages) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in slippages:
            row = _cpcv_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=args.borrow_cost,
                funding_cost=args.funding_cost, slippage=cost,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "cpcv_slippage_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"slippages": slippages, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nSlippage sweep ({len(slippages)} rates) saved to: {sweep_path}")
        print("Slippage | Total OOS Return | OOS Sharpe | minSR | note | Avg Param Stability | Overfitting Risk | Deflated Sharpe | N Folds")
        print("-" * 112)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['slippage']:>13.6f} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {minSR_txt:>9} | {note:>16} | {row['avg_param_stability']:>17.4f} | "
                f"{_format_overfitting_risk(row['overfitting_risk']):>17} | {dsr_txt:>14} | {row['n_folds']:>7}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    print(f"Running CPCV analysis with {args.strategy} (n_splits={args.n_splits})...")
    results = cpcv_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        n_splits=args.n_splits,
        test_size=args.test_size,
        purge_size=args.purge_size,
        embargo_size=args.embargo_size,
        commission=args.commission,
        slippage=args.slippage,
        impact_coefficient=args.impact_coefficient,
        adv_window=args.adv_window,
        borrow_cost=args.borrow_cost,
        funding_cost=args.funding_cost,
        latency=latency,
        fill_rate=fill_rate,
        apply_deflation=args.deflate,
        benchmark=benchmark,
        total_return_benchmark=total_return_benchmark,
        benchmark_commission=bench_commission,
        benchmark_slippage=bench_slippage,
        benchmark_expense_ratio=bench_expense_ratio,
        benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
        panel_pricing=getattr(args, "panel_pricing", "net-exposure"),
        impact_aggregation=getattr(args, "impact_aggregation", "panel"),
    )
    if pit_results is not None:
        results["point_in_time_validation"] = pit_results

    # Compute benchmark comparison metrics if benchmark provided
    benchmark_returns = None
    benchmark_returns_list = None
    if benchmark is not None and len(results["oos_returns"]) > 0:
        if isinstance(benchmark, list):
            # Multiple benchmarks: the aggregate Deflated Alpha comparison is
            # already computed inside cpcv_analysis; expose the aligned
            # benchmark returns to calculate_metrics (which surfaces the
            # canonical deflated_alpha via its benchmark_list path).
            benchmark_returns_list = []
            for b in benchmark:
                br = _compute_benchmark_returns(b, results["oos_returns"], total_return_benchmark)
                if br is not None:
                    benchmark_returns_list.append(br)
            if benchmark_returns_list and results["summary"].get("deflated_alpha") is None:
                # Defensive: ensure a deflated_alpha surfaces even if cpcv_analysis
                # did not compute one (e.g. degenerate returns).
                correction = _benchmark_list_alpha_correction(
                    results["oos_returns"], benchmark,
                    total_return_benchmark=total_return_benchmark,
                    benchmark_commission=bench_commission,
                    benchmark_slippage=bench_slippage,
                    benchmark_expense_ratio=bench_expense_ratio,
                    benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
                )
                if correction["deflated_alpha"] is not None:
                    results["summary"]["deflated_alpha"] = correction["deflated_alpha"]
                results["summary"]["benchmark_metrics"] = correction["per_benchmark"]
        else:
            benchmark_returns = _compute_benchmark_returns(benchmark, results["oos_returns"], total_return_benchmark)
            if benchmark_returns is not None:
                # Single benchmark: backward-compatible summary update
                results["summary"] = _add_benchmark_to_summary(
                    results["summary"], results["oos_returns"], benchmark_returns,
                    commission=bench_commission, slippage=bench_slippage,
                    benchmark_expense_ratio=bench_expense_ratio, total_return_benchmark=total_return_benchmark,
                    benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
                    benchmark_data=benchmark,
                )
                print(
                    f"Benchmark Correlation: {results['summary'].get('correlation_with_benchmark', 'N/A'):.4f}"
                )
                print(
                    f"Alpha (annualized): {results['summary'].get('alpha', 'N/A'):.2%}"
                )
                print(
                    f"Beta: {results['summary'].get('beta', 'N/A'):.4f}"
                )
                pval = results["summary"].get("alpha_pvalue")
                print(
                    f"Alpha p-value: {pval if pval is None else f'{pval:.4f}'}"
                )
                rs = results["summary"].get("r_squared")
                print(
                    f"R-squared: {rs if rs is None else f'{rs:.4f}'}"
                )

    print(f"Number of CPCV folds: {results['summary']['n_folds']}")
    # A grid key that did not change the strategy's behaviour makes the
    # per-fold selection over it a null experiment: say so next to the folds,
    # not only in the summary JSON.
    _print_inert_grid_warning(results["summary"].get("inert_grid_message"))
    # A run that selected nothing says why, next to the fold count, so the
    # console and the artifact carry the same diagnosis.
    _print_no_selection_diagnosis(
        results["summary"].get("no_selection_diagnosis")
    )
    # A run in which only some folds could select a parameter says which
    # folds were flat and why, next to the fold count.
    _print_partial_selection_diagnosis(
        results["summary"].get("partial_selection_diagnosis")
    )
    # A verdict that rests on some folds also rests on how much of those
    # folds the strategy actually traded in: a "low" rating earned on two
    # folds that each traded for one bar says little about the strategy.
    _print_thin_evidence_warning(
        results["summary"].get("thin_evidence_warning")
    )
    # --min-position-fraction rejects a run whose verdict rests on windows
    # the strategy barely traded in, printing a remedy that names the flags
    # of the path that produced the windows. The failure is written to the
    # artifact too (summary.thin_evidence_failure) so a machine reader sees
    # why the run was rejected.
    thin_evidence_failed = _thin_evidence_failure(
        results["summary"], min_position_fraction
    )
    if thin_evidence_failed is not None:
        print(f"REJECTED: {thin_evidence_failed['message']}")
    _total_oos_return = results["summary"]["total_oos_return"]
    print(
        f"Total OOS Return: {'N/A' if _total_oos_return is None else f'{_total_oos_return:.2%}'}"
    )
    print(f"OOS Sharpe Ratio: {results['summary'].get('oos_sharpe', 'N/A')}")
    print(f"Avg Parameter Stability: {results['summary'].get('avg_param_stability', 'N/A'):.2f}")
    _print_overfitting_risk(results["summary"])
    _print_panel_pricing(results["summary"].get("panel_pricing"))
    _print_execution_warmup(results["summary"])
    _print_book_diagnostic(
        results["summary"].get("book_diagnostic"),
        panel_pricing=results["summary"].get("panel_pricing"),
    )
    _print_capacity(results["summary"])

    dsr = results["summary"].get("deflated_sharpe")
    if dsr is not None:
        print(
            f"Deflated Sharpe Ratio: {dsr['deflated_sharpe_ratio']:.4f} "
            f"(p-value {dsr['p_value']:.4f}, expected max Sharpe "
            f"{dsr['expected_max_sharpe']:.4f}, {dsr['n_trials']} trials)"
        )
    # The aggregate Deflated Alpha Ratio: the statistic the alpha resolution
    # below belongs to.
    _print_deflated_alpha(results["summary"].get("deflated_alpha"))
    # What the significance tests could have detected at the sample size
    # actually available: the smallest confirmable effect. A measurement, not
    # a correction -- it changes no verdict and no reported number.
    _print_test_resolution(results["summary"].get("test_resolution"))

    # Save results
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save summary as JSON
    summary_path = output_dir / "cpcv_summary.json"
    summary_data = {
        "summary": results["summary"],
        "param_stability": results["param_stability"],
        "best_params_per_fold": results["best_params_per_fold"],
        # Per-fold market-impact capacity so capacity degradation across
        # folds/regimes is observable from the saved artifact alone. The
        # trend carries the per-window distribution (min / median) so a
        # liquidity squeeze inside a fold is visible too.
        "capacity_per_fold": [
            {
                "fold": f.get("fold"),
                "test_start": f.get("test_start"),
                "test_end": f.get("test_end"),
                "capacity": f.get("capacity"),
                "capacity_trend": f.get("capacity_trend"),
                # Book-based capacity for the fold (book pricing mode only):
                # the capacity implied by the strategy's own trade sizes.
                "capacity_book": f.get("capacity_book"),
                "capacity_book_trend": f.get("capacity_book_trend"),
                # Panel book diagnostic for the fold's test window: the
                # per-asset book against the framework's net-exposure
                # pricing (measurement only).
                "book_diagnostic": f.get("book_diagnostic"),
            }
            for f in results.get("folds", [])
        ],
        "config": {
            "strategy": args.strategy,
            "symbol": args.symbol,
            "n_splits": args.n_splits,
            "test_size": args.test_size,
            "purge_size": args.purge_size,
            "embargo_size": args.embargo_size,
            "commission": args.commission,
            "slippage": args.slippage,
            "impact_coefficient": args.impact_coefficient,
            "adv_window": args.adv_window,
            "borrow_cost": args.borrow_cost,
            "funding_cost": args.funding_cost,
            "latency": latency,
            "fill_rate": fill_rate,
            "deflate": bool(getattr(args, "deflate", False)),
            "param_grid": param_grid,
            "point_in_time_validation": pit_results,
            "bias_controls_engaged": pit_results is not None,
            "benchmark": getattr(args, "benchmark", None),
            "total_return_benchmark": total_return_benchmark,
            "benchmark_commission": bench_commission,
            "benchmark_slippage": bench_slippage,
            "benchmark_expense_ratio": bench_expense_ratio,
            "benchmark_cost_is_periodic": getattr(args, "benchmark_cost_is_periodic", False),
            "multi_symbol": getattr(args, "multi_symbol", False),
            # The execution warmup this run applied, so the saved artifact
            # records how many leading bars of every fold are not tradable.
            **execution_warmup_metadata(WARMUP_CONVENTION_WALK_FORWARD, latency),
        },
    }
    if pit_results is not None:
        results["point_in_time_validation"] = pit_results
        summary_data["point_in_time_validation"] = pit_results
    results["bias_controls_engaged"] = bool(pit_results is not None or survivorship is not None)
    summary_data["bias_controls_engaged"] = bool(pit_results is not None or survivorship is not None)
    if survivorship is not None:
        results["survivorship_bias"] = survivorship
        summary_data["survivorship_bias"] = survivorship
        # Persist the survivorship-bias report as a standalone artifact so
        # panel CPCV runs are auditable on the same file name used by the
        # run_backtest CLI path.
        surv_path = output_dir / "survivorship_bias.json"
        with open(surv_path, "w") as f:
            json.dump(survivorship, f, indent=2, default=str)
        print(f"Survivorship bias report saved to: {surv_path}")
    if benchmark_provenance is not None:
        if isinstance(benchmark_provenance, list):
            summary_data["benchmark_provenance"] = [prov.to_dict() for prov in benchmark_provenance]
        else:
            summary_data["benchmark_provenance"] = benchmark_provenance.to_dict()
    with open(summary_path, "w") as f:
        json.dump(summary_data, f, indent=2, default=str)
    print(f"CPCV summary saved to: {summary_path}")

    # Generate full report if OOS returns available
    if len(results["oos_returns"]) > 0:
        equity = (1 + results["oos_returns"]).cumprod() * args.initial_capital
        report_results = {
            "equity_curve": equity,
            "returns": results["oos_returns"],
            "config": {
                "initial_capital": args.initial_capital,
                "commission": args.commission,
                "slippage": args.slippage,
                "strategy": args.strategy,
                "symbol": args.symbol,
                "total_return_benchmark": total_return_benchmark,
                "benchmark_commission": bench_commission,
                "benchmark_slippage": bench_slippage,
            },
        }
        if benchmark_returns is not None:
            report_results["benchmark"] = benchmark_returns
        elif benchmark_returns_list:
            report_results["benchmark_list"] = benchmark_returns_list
        # Thread benchmark provenance through the report results so the
        # tear-sheet summary can associate each benchmark_metrics row with
        # the exact benchmark file/checksum (mirrors the run_backtest CLI
        # path, which already serializes it into results["benchmark_provenance"]).
        if benchmark_provenance is not None:
            report_results["benchmark_provenance"] = benchmark_provenance
        if pit_results is not None:
            report_results["point_in_time_validation"] = pit_results
        if survivorship is not None:
            report_results["survivorship_bias"] = survivorship
        report_results["bias_controls_engaged"] = bool(pit_results is not None or survivorship is not None)
        metrics = calculate_metrics(report_results)
        generate_report(metrics, args.output, symbol=args.symbol, strategy_name=f"{args.strategy}_cpcv")
        generate_tear_sheet(
            report_results, metrics, args.output,
            symbol=args.symbol,
            strategy_name=f"{args.strategy}_cpcv",
            analysis_results={"cpcv": results},
        )
        print(f"Detailed report saved to: {args.output}/")

    return 1 if thin_evidence_failed else 0


def _make_strategy_factory(strategy_type: str):
    """Create a strategy factory function for the given strategy type."""
    def factory(params: Dict[str, Any]):
        return build_strategy(strategy_type, json.dumps(params))
    return factory


def _print_panel_pricing(mode, indent: str = "  ") -> None:
    """Print the panel pricing convention that produced the reported P&L.

    Every panel number must be read together with the convention it was
    produced under: the two conventions can differ by more than the
    transaction costs (the sign of the gap is not even stable across
    windows), so a return without its pricing mode is not interpretable.
    """
    if mode == "book":
        print(
            f"{indent}Panel pricing mode: book (the portfolio return is the "
            f"true per-asset book return sum_i w_i r_i, and the costs are "
            f"charged on the book: gross turnover, short legs and gross "
            f"exposure)."
        )
    else:
        print(
            f"{indent}Panel pricing mode: net-exposure (the portfolio return "
            f"is net_exposure x mean(asset returns), and the costs are "
            f"charged on the net exposure)."
        )


def _print_execution_warmup(summary, indent: str = "  ") -> None:
    """Print the execution warmup convention a run applied.

    Every window this path evaluates starts with bars that are not tradable:
    the lagged position is undefined on the first ``1 + latency`` bars and
    the turnover on the bar after that is undefined too. Those bars are
    dropped from the reported return series, so the number of them is part
    of the methodology and is printed next to the pricing mode.

    Nothing is printed when the summary carries no warmup metadata (for
    example a summary produced by an older caller), so the output of such a
    run is unchanged.
    """
    if not isinstance(summary, dict):
        return
    convention = summary.get("warmup_convention")
    warmup_bars = summary.get("execution_warmup_bars")
    if convention is None or warmup_bars is None:
        return
    print(
        f"{indent}Execution warmup: {convention} ({warmup_bars} bar(s) "
        "dropped from the front of every window; the position is opened on "
        "the first bar after the warmup)."
    )


def _print_capacity(summary, indent: str = "  ") -> None:
    """Print the market-impact capacity estimates of a summary.

    The basket-based estimate assumes an equal-weight basket that rebalances
    ``1 / n`` per constituent. Under the ``book`` pricing mode the summary
    also carries the book-based estimate -- the equity level at which the
    strategy's *own* rebalances reach the impact threshold -- and both are
    printed so the reader can see which convention produced which number.

    Nothing is printed when there is no book-based estimate, so the
    ``net-exposure`` output is unchanged.
    """
    if not isinstance(summary, dict):
        return
    _basket = summary.get("capacity")
    _book = summary.get("capacity_book")
    if _book is None:
        return
    print(f"{indent}Capacity (market impact):")
    if _basket is not None:
        print(
            f"{indent}  Basket-based (equal 1/n per constituent): {_basket:,.2f}"
        )
    print(
        f"{indent}  Book-based (the strategy's own trade sizes): {_book:,.2f}"
    )
    _book_trend = summary.get("capacity_book_trend") or {}
    _book_min = _book_trend.get("min_capacity")
    if _book_min is not None:
        print(
            f"{indent}  Book-based, worst reading in the sample:    {_book_min:,.2f}"
        )
    _oos_min_book = summary.get("oos_min_capacity_book")
    if _oos_min_book is not None:
        print(
            f"{indent}  Book-based, worst out-of-sample window:      {_oos_min_book:,.2f}"
        )


def _print_book_diagnostic(diag, indent: str = "  ", panel_pricing=None) -> None:
    """Print the panel book diagnostic (measurement only).

    The panel path prices a portfolio as ``net_exposure x mean(asset
    returns)``. This prints how much of the strategy's actual book that
    convention misses: the gross book and the turnover the model charges
    nothing for, and the gap between the framework's P&L and the book P&L.
    Under the ``book`` pricing mode the reported P&L *is* the book's, and
    the net-exposure numbers are shown for comparison.
    """
    if not isinstance(diag, dict):
        return
    if panel_pricing == "book":
        print(
            f"{indent}Panel Book Diagnostic (the reported P&L uses the book "
            f"convention; the net-exposure pricing is shown for comparison):"
        )
    else:
        print(f"{indent}Panel Book Diagnostic (measurement only -- reported P&L unchanged):")
    print(f"{indent}  Gross book (mean sum|w|):     {diag.get('gross_book', 0.0):.4f}")
    print(f"{indent}  Net exposure (book):          {diag.get('net_exposure', 0.0):.4f}")
    print(f"{indent}  Net exposure (framework):      {diag.get('framework_net_exposure', 0.0):.4f}")
    print(f"{indent}  Gross turnover (book):         {diag.get('gross_turnover', 0.0):.4f}")
    _charged = diag.get("charged_turnover")
    if _charged is None:
        _charged = diag.get("framework_turnover", 0.0)
    print(
        f"{indent}  Turnover charged by the model: {_charged:.4f}"
        f"  (cost basis: {diag.get('cost_basis', 'net-exposure')})"
    )
    print(
        f"{indent}  Periods with a book:           "
        f"{diag.get('n_periods_with_book', 0)}/{diag.get('n_periods', 0)}"
    )
    gap_bps = diag.get("return_gap_bps")
    gap_total = diag.get("return_gap_total")
    if gap_bps is not None and gap_total is not None:
        print(
            f"{indent}  Return gap (framework - book): {gap_bps:.2f} bps/period "
            f"({gap_total:.2%} cumulative, pre-cost)"
        )
        _reported = diag.get("reported_total_return")
        if _reported is None:
            _reported = diag.get("framework_total_return_after_costs", 0.0)
        print(
            f"{indent}  Book return (pre-cost):        "
            f"{diag.get('book_total_return', 0.0):.2%}; reported (net of costs): "
            f"{_reported:.2%}"
        )
    if panel_pricing == "book":
        print(
            f"{indent}  Cost basis: book. Commission and slippage are "
            f"charged on the book's gross turnover, borrow on its short legs "
            f"and funding on its gross exposure."
        )
        print(
            f"{indent}  Residual approximation: the market-impact model "
            f"charges the equal-weighted mean of the per-asset impacts over "
            f"the whole panel, so a period in which only some names trade is "
            f"charged less than the participation actually consumed (see the "
            f"impact participation block below)."
        )
    for _line in format_impact_dilution_lines(diag, indent=indent + "  "):
        print(_line)


def _load_and_validate_data(
    data_path: str,
    symbol: str,
    start: str,
    end: str,
    validate_pit: bool = True,
    pit_strict: bool = False,
    multi_symbol: bool = False,
) -> tuple[Any, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Load and validate data from file.

    Point-in-time validation (look-ahead / stale-data / temporal-ordering
    screening) runs by default so a naive CLI run does not silently proceed
    without bias controls. With pit_strict, violations raise so the analysis
    aborts instead of continuing on suspect data.

    When ``multi_symbol`` is True, the file is loaded as a symbol panel via
    ``load_multi_symbol`` (requiring a 'symbol' or 'ticker' column) and
    survivorship-bias detection runs on the panel. The loaded data is a
    ``dict`` of {symbol: DataFrame}, which the analysis pipelines convert to a
    MultiIndex panel internally.

    Returns:
        tuple of (data_frame_or_dict, pit_results_dict_or_None, survivorship_dict_or_None)
    """
    survivorship = None
    if multi_symbol:
        print("Multi-symbol mode: loading the full symbol universe...")
        data = load_multi_symbol(data_path, return_provenance=False)
        if not data:
            raise ValueError(
                "No symbols could be loaded from the multi-symbol file!"
            )
        survivorship = detect_survivorship_bias(data)
        _print_survivorship_report(survivorship)
    else:
        data = load_data(data_path, symbol=symbol, start=start, end=end)
        if not validate_data(data):
            raise ValueError("Data validation failed!")
    pit = None
    if validate_pit:
        if isinstance(data, dict):
            # Multi-symbol panels have no single signal column, so each
            # symbol frame is validated for structural violations instead.
            combined = {"passed": True, "violations": [], "warnings": []}
            for df in data.values():
                frame_result = validate_point_in_time(df)
                combined["passed"] = combined["passed"] and frame_result["passed"]
                combined["violations"].extend(frame_result["violations"])
                combined["warnings"].extend(frame_result["warnings"])
            pit = combined
        else:
            pit = validate_point_in_time(data)
        if pit["violations"]:
            print("Point-in-time validation violations:")
            for violation in pit["violations"]:
                print(f"  - {violation}")
        if pit["warnings"]:
            print("Point-in-time validation warnings:")
            for warning in pit["warnings"]:
                print(f"  - {warning}")
        if not pit["violations"] and not pit["warnings"]:
            print("Point-in-time validation passed (no violations or warnings).")
        elif not pit["violations"]:
            print("Point-in-time validation passed (no violations).")
        if pit_strict and not pit["passed"]:
            raise ValueError(
                "Point-in-time validation failed in strict mode: "
                + "; ".join(pit["violations"])
            )
    return data, pit, survivorship


def _print_survivorship_report(survivorship: Dict[str, Any]) -> None:
    """Print a survivorship-bias detection report to the log."""
    print("Survivorship bias detection:")
    print(f"  bias_score: {survivorship['bias_score']:.3f}")
    print(f"  surviving symbols: {len(survivorship['surviving_symbols'])}")
    for entry in survivorship["entered_symbols"]:
        print(
            f"  entered after sample start: {entry['symbol']} "
            f"({entry['days_after_global_start']} days late)"
        )
    for entry in survivorship["exited_symbols"]:
        print(
            f"  exited before sample end: {entry['symbol']} "
            f"({entry['days_before_global_end']} days early)"
        )
    for symbol in survivorship["insufficient_data"]:
        print(f"  insufficient observations: {symbol}")
    for entry in survivorship["large_gaps"]:
        print(
            f"  large data gap: {entry['symbol']} "
            f"(max {entry['max_gap_days']} days)"
        )


def _load_benchmark(benchmark_path: str, total_return_benchmark: bool = False) -> tuple[pd.DataFrame, Optional[Any]]:
    """Load benchmark data and return (benchmark_df, benchmark_provenance)."""
    benchmark, provenance = load_data(benchmark_path, return_provenance=True)
    if not validate_data(benchmark):
        raise ValueError("Benchmark data validation failed!")
    print(
        f"Loaded benchmark: {provenance.final_shape[0]} rows "
        f"(checksum {provenance.checksum}, "
        f"total_return_type: {provenance.total_return_type})"
    )
    if total_return_benchmark:
        if provenance.total_return_type == "total":
            print("Using total-return benchmark (dividends/adj_close included)")
        else:
            print("Warning: --total-return-benchmark requested but benchmark data has no dividends/adj_close column; falling back to price-only returns")
    return benchmark, provenance


def _compute_benchmark_returns(
    benchmark: pd.DataFrame,
    strategy_returns: pd.Series,
    total_return_benchmark: bool = False,
) -> Optional[pd.Series]:
    """Compute buy-and-hold benchmark returns aligned to strategy returns.

    The benchmark return for period t is the close-to-close return
    from t-1 to t (no shift). Aligned to the strategy returns index
    via inner join on common trading dates.

    If total_return_benchmark is True, uses _compute_benchmark_total_return
    which includes dividends/adj_close when available.
    """
    if total_return_benchmark:
        benchmark_returns = _compute_benchmark_total_return(benchmark)
    else:
        benchmark_returns = benchmark["close"].pct_change()
    _, aligned_benchmark = strategy_returns.align(benchmark_returns, join="inner")
    if len(aligned_benchmark) > 0:
        return aligned_benchmark
    return None


def _add_benchmark_to_summary(
    summary: Dict[str, Any],
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    commission: float = 0.0,
    slippage: float = 0.0,
    benchmark_expense_ratio: float = 0.0,
    total_return_benchmark: bool = False,
    benchmark_cost_is_periodic: bool = False,
    benchmark_data: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Add benchmark comparison metrics to a summary dict.

    Computes benchmark total/annualized return, correlation, alpha, beta,
    the alpha t-statistic, its two-sided p-value, and the regression R^2
    from the aligned return series (delegates to ``_benchmark_stats``).

    Args:
        summary: Dictionary to update with benchmark metrics.
        strategy_returns: Strategy returns series.
        benchmark_returns: Benchmark returns series.
        commission: Commission rate per trade.
        slippage: Slippage rate per trade.
        benchmark_expense_ratio: Annual expense ratio for benchmark (as decimal, e.g., 0.005 for 0.5%).
        total_return_benchmark: If True, compute benchmark returns using total return (dividends + price).
        benchmark_data: Original benchmark OHLCV data with splits column (optional).
    """
    if len(benchmark_returns) == 0:
        return summary

    ann_factor = _annualization_factor(strategy_returns.index)

    # If we have benchmark data with a splits column, use split-aware cost
    # calculation.  Split adjustment is orthogonal to the cost model: a
    # corporate action injects an artificial price drop into benchmark
    # returns regardless of whether benchmark costs are modeled as round-trip
    # or periodic, so gating it on benchmark_cost_is_periodic silently
    # misprices every split-bearing benchmark under the default cost model.
    if benchmark_data is not None and "splits" in benchmark_data.columns:
        # Align benchmark data with returns
        _, aligned_benchmark_data = strategy_returns.align(benchmark_data, join="inner")
        if len(aligned_benchmark_data) > 0:
            stats = _benchmark_stats_with_splits(
                strategy_returns, benchmark_returns, ann_factor,
                total_return_benchmark=total_return_benchmark,
                benchmark_commission=commission,
                benchmark_slippage=slippage,
                benchmark_expense_ratio=benchmark_expense_ratio,
                benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                benchmark_data=aligned_benchmark_data,
            )
        else:
            stats = _benchmark_stats(
                strategy_returns, benchmark_returns, ann_factor,
                total_return_benchmark=total_return_benchmark,
                benchmark_commission=commission,
                benchmark_slippage=slippage,
                benchmark_expense_ratio=benchmark_expense_ratio,
                benchmark_cost_is_periodic=benchmark_cost_is_periodic,
            )
    else:
        stats = _benchmark_stats(
            strategy_returns, benchmark_returns, ann_factor,
            total_return_benchmark=total_return_benchmark,
            benchmark_commission=commission,
            benchmark_slippage=slippage,
            benchmark_expense_ratio=benchmark_expense_ratio,
            benchmark_cost_is_periodic=benchmark_cost_is_periodic,
        )
    summary.update(stats)
    return summary


def _benchmark_stats_with_splits(
    strategy_returns: pd.Series,
    benchmark_returns: pd.Series,
    ann_factor: float,
    total_return_benchmark: bool = False,
    benchmark_commission: float = 0.0,
    benchmark_slippage: float = 0.0,
    benchmark_expense_ratio: float = 0.0,
    benchmark_cost_is_periodic: bool = False,
    benchmark_data: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    """Compute benchmark stats with split-adjusted returns.

    When benchmark OHLCV data includes a ``splits`` column, prices are
    adjusted for splits before computing returns.  This prevents the
    artificial return drop that a stock split would otherwise introduce on
    the split date (e.g. a 2-for-1 split halves the close price), which
    would distort benchmark comparison metrics and cost calculations.

    After recomputing returns from split-adjusted prices, the function
    delegates to ``_benchmark_stats`` and forwards ``benchmark_cost_is_periodic``
    unchanged so that periodic or round-trip cost handling is preserved.
    """
    if benchmark_data is not None and "splits" in benchmark_data.columns:
        benchmark_data = adjust_for_splits(benchmark_data)

    if benchmark_data is not None and "close" in benchmark_data.columns:
        if total_return_benchmark:
            adjusted_benchmark_returns = _compute_benchmark_total_return(benchmark_data)
        else:
            adjusted_benchmark_returns = benchmark_data["close"].pct_change()
        _, aligned_bench = strategy_returns.align(
            adjusted_benchmark_returns, join="inner"
        )
        if len(aligned_bench) > 0:
            # pct_change() leaves a leading NaN on the first observation; the
            # OLS alpha/beta/correlation/p-value in _benchmark_stats all
            # propagate that NaN to NaN (a silent no-inference result), so
            # drop it here.  This matches the non-splits path, where
            # _compute_benchmark_returns already aligns and the caller is
            # expected to dropna before passing to _benchmark_stats.
            benchmark_returns = aligned_bench.dropna()

    return _benchmark_stats(
        strategy_returns,
        benchmark_returns,
        ann_factor,
        total_return_benchmark=total_return_benchmark,
        benchmark_commission=benchmark_commission,
        benchmark_slippage=benchmark_slippage,
        benchmark_expense_ratio=benchmark_expense_ratio,
        benchmark_cost_is_periodic=benchmark_cost_is_periodic,
    )


def _benchmark_list_alpha_correction(
    strategy_returns: pd.Series,
    benchmark_list: List[pd.DataFrame],
    total_return_benchmark: bool = False,
    benchmark_commission: float = 0.0,
    benchmark_slippage: float = 0.0,
    benchmark_expense_ratio: float = 0.0,
    benchmark_cost_is_periodic: bool = False,
) -> Dict[str, Any]:
    """Compute per-benchmark comparison stats and a cross-benchmark Deflated Alpha correction.

    Testing a strategy against multiple benchmarks is a multiple-testing problem:
    with enough benchmarks, luck alone yields an attractive alpha.  This helper
    computes the OLS alpha/beta/correlation/p-value for each benchmark
    (split-aware whenever the benchmark data carries a ``splits`` column,
    regardless of the cost model) and then applies the Deflated Alpha Ratio
    across the benchmark set, mirroring the correction already performed by
    ``out_of_sample_validation`` so the validation, CPCV, and walk-forward
    pipelines apply it uniformly at the per-fold/per-period and aggregate
    levels.

    Returns a dict with:
        - 'per_benchmark': list of per-benchmark stats dicts (None where a
          benchmark had no aligned returns).  When >= 2 benchmarks produced
          finite alphas each dict also carries the corrected ``alpha_pvalue``,
          ``alpha_pvalue_original``, ``deflated_alpha`` and
          ``expected_max_alpha``.
        - 'deflated_alpha': aggregate Deflated Alpha Ratio dict for the primary
          (first) benchmark when >= 2 benchmarks produced finite alphas, else
          None (same shape as ``deflated_alpha_ratio`` output).
        - 'n_benchmarks': number of benchmarks tested
    """
    per_benchmark: List[Optional[Dict[str, Any]]] = []
    p_values: List[float] = []
    benchmark_returns_list: List[Optional[pd.Series]] = []

    # Drop NaN from the strategy returns once; downstream OLS and the Deflated
    # Alpha Ratio assume a common-date aligned, NaN-free series.  This is
    # idempotent on returns already produced by _calculate_strategy_returns
    # (which dropna's), but makes the helper robust to leading-NaN pct_change
    # artifacts when callers pass arbitrary return series.
    strategy_returns = strategy_returns.dropna()

    for bench in benchmark_list:
        benchmark_returns = _compute_benchmark_returns(
            bench, strategy_returns, total_return_benchmark
        )
        if benchmark_returns is not None:
            benchmark_returns = benchmark_returns.dropna()
        benchmark_returns_list.append(benchmark_returns)
        if benchmark_returns is not None and len(benchmark_returns) > 0:
            if isinstance(bench, pd.DataFrame) and "splits" in bench.columns:
                bench_stats = _benchmark_stats_with_splits(
                    strategy_returns, benchmark_returns, _annualization_factor(strategy_returns.index),
                    total_return_benchmark=total_return_benchmark,
                    benchmark_commission=benchmark_commission,
                    benchmark_slippage=benchmark_slippage,
                    benchmark_expense_ratio=benchmark_expense_ratio,
                    benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                    benchmark_data=bench,
                )
            else:
                bench_stats = _benchmark_stats(
                    strategy_returns, benchmark_returns, _annualization_factor(strategy_returns.index),
                    total_return_benchmark=total_return_benchmark,
                    benchmark_commission=benchmark_commission,
                    benchmark_slippage=benchmark_slippage,
                    benchmark_expense_ratio=benchmark_expense_ratio,
                    benchmark_cost_is_periodic=benchmark_cost_is_periodic,
                )
            per_benchmark.append(bench_stats)
            p_values.append(bench_stats.get("alpha_pvalue", 1.0) if bench_stats.get("alpha_pvalue") is not None else 1.0)
        else:
            per_benchmark.append(None)
            p_values.append(1.0)

    deflated_alpha: Optional[Dict[str, Any]] = None
    n_benchmarks = len(p_values)

    if p_values and n_benchmarks > 1:
        # Collect trial alphas from benchmarks with finite alpha (cross-sectional
        # dispersion estimator for alpha*, when enough are available).
        trial_alphas = [
            r["alpha"] for r in per_benchmark
            if r is not None and "alpha" in r and np.isfinite(r["alpha"])
        ]

        for i, bench_result in enumerate(per_benchmark):
            if bench_result is None or "alpha" not in bench_result:
                continue
            if np.isfinite(bench_result["alpha"]) and len(trial_alphas) >= 2:
                bench_returns = benchmark_returns_list[i]
                if bench_returns is not None:
                    try:
                        dar = deflated_alpha_ratio(
                            alpha=bench_result["alpha"],
                            returns=strategy_returns,
                            benchmark_returns=bench_returns,
                            n_benchmarks=n_benchmarks,
                            trial_alphas=trial_alphas,
                        )
                        bench_result["alpha_pvalue_original"] = p_values[i]
                        bench_result["alpha_pvalue"] = dar["p_value"]
                        bench_result["deflated_alpha"] = dar["deflated_alpha_ratio"]
                        bench_result["expected_max_alpha"] = dar["expected_max_alpha"]
                    except Exception:
                        # DAR computation failed (e.g. too few aligned
                        # observations): fall back to a Bonferroni correction
                        # rather than silently dropping the correction.
                        corrected_p = min(p_values[i] * n_benchmarks, 1.0)
                        bench_result["alpha_pvalue_original"] = p_values[i]
                        bench_result["alpha_pvalue"] = corrected_p
                        bench_result.setdefault("deflated_alpha", None)
                        bench_result.setdefault("expected_max_alpha", None)
            elif bench_result is not None:
                # Fallback (Bonferroni) when too few trial alphas for the
                # cross-sectional estimator.
                corrected_p = min(p_values[i] * n_benchmarks, 1.0)
                bench_result["alpha_pvalue_original"] = p_values[i]
                bench_result["alpha_pvalue"] = corrected_p
                bench_result.setdefault("deflated_alpha", None)
                bench_result.setdefault("expected_max_alpha", None)

        # Aggregate Deflated Alpha for the primary (first) benchmark.
        primary = per_benchmark[0] if per_benchmark and per_benchmark[0] is not None else None
        if primary is not None and "alpha" in primary and np.isfinite(primary["alpha"]):
            first_returns = benchmark_returns_list[0]
            if first_returns is not None:
                try:
                    deflated_alpha = deflated_alpha_ratio(
                        alpha=primary["alpha"],
                        returns=strategy_returns,
                        benchmark_returns=first_returns,
                        n_benchmarks=n_benchmarks,
                        trial_alphas=trial_alphas if len(trial_alphas) >= 2 else None,
                    )
                except Exception:
                    deflated_alpha = None

    return {
        "per_benchmark": per_benchmark,
        "deflated_alpha": deflated_alpha,
        "n_benchmarks": n_benchmarks,
    }


def _parse_param_grid(param_grid_str: str) -> Dict[str, List[Any]]:
    """Parse parameter grid from JSON string."""
    try:
        param_grid = json.loads(param_grid_str)
        # Ensure all values are lists
        for k, v in param_grid.items():
            if not isinstance(v, list):
                param_grid[k] = [v]
        return param_grid
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON for param_grid: {e}")


def run_walk_forward(args) -> int:
    """Run walk-forward analysis from CLI args."""
    print(f"Loading data from {args.data}...")
    data, pit_results, survivorship = _load_and_validate_data(
        args.data, args.symbol, args.start, args.end,
        validate_pit=getattr(args, "validate_point_in_time", True),
        pit_strict=getattr(args, "point_in_time_strict", False),
        multi_symbol=getattr(args, "multi_symbol", False),
    )

    # Load benchmark if provided
    benchmark = None
    benchmark_provenance = None
    total_return_benchmark = getattr(args, "total_return_benchmark", False)
    bench_commission = getattr(args, "benchmark_commission", None) if getattr(args, "benchmark_commission", None) is not None else args.commission
    bench_slippage = getattr(args, "benchmark_slippage", None) if getattr(args, "benchmark_slippage", None) is not None else args.slippage
    bench_expense_ratio = getattr(args, "benchmark_expense_ratio", None) if getattr(args, "benchmark_expense_ratio", None) is not None else 0.0
    if getattr(args, "benchmark", None):
        benchmark_paths = args.benchmark if isinstance(args.benchmark, list) else [args.benchmark]
        print(f"Loading benchmark data from {', '.join(benchmark_paths)}...")
        if len(benchmark_paths) == 1:
            benchmark, benchmark_provenance = _load_benchmark(benchmark_paths[0], total_return_benchmark)
        else:
            benchmark = []
            benchmark_provenance = []
            for bench_file in benchmark_paths:
                b, prov = _load_benchmark(bench_file, total_return_benchmark)
                benchmark.append(b)
                benchmark_provenance.append(prov)

    latency, fill_rate = _resolve_latency_fill_rate(args)
    min_position_fraction = _resolve_min_position_fraction(args)

    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    print(f"Running walk-forward analysis with {args.strategy}...")
    impact_coefficients = [float(c) for c in (args.impact_coefficients or [args.impact_coefficient])]
    borrow_costs = [float(c) for c in (args.borrow_costs or [args.borrow_cost])]
    funding_costs = [float(c) for c in (args.funding_costs or [args.funding_cost])]

    # Execution-latency / partial-fill sweeps for walk-forward: re-run the
    # walk-forward pipeline for each latency / fill-rate and record
    # degradation in a single artifact. Single value keeps the original path.
    latencies = [int(l) for l in (args.latencies or [args.latency])]
    fill_rates = [float(f) for f in (args.fill_rates or [args.fill_rate])]
    if _run_latency_fill_rate_sweep(
        args,
        runner=lambda v, key: _walk_forward_sweep_coefficient(
            args, data, benchmark, total_return_benchmark,
            bench_commission, bench_slippage, bench_expense_ratio,
            args.impact_coefficient, borrow_cost=args.borrow_cost,
            funding_cost=args.funding_cost, **{key: v},
            survivorship=survivorship,
        ),
        latency_values=latencies,
        fill_rate_values=fill_rates,
        latency_artifact="walk_forward_latency_sweep.json",
        fill_rate_artifact="walk_forward_fill_rate_sweep.json",
        latency_header=["Latency", "Total OOS Return", "OOS Sharpe", "Deflated Sharpe", "N Periods"],
        fill_rate_header=["Fill Rate", "Total OOS Return", "OOS Sharpe", "Deflated Sharpe", "N Periods"],
        row_cells=lambda row, key: [
            str(row[key]),
            'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:.4f}",
            "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}",
            "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}",
            str(row["n_periods"]),
        ],
    ):
        return 0

    # Capacity / cost sensitivity sweeps for walk-forward: re-run the
    # walk-forward pipeline for each coefficient/cost and record degradation
    # in a single artifact. Single value (default) keeps the original path.
    if len(impact_coefficients) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for coeff in impact_coefficients:
            row = _walk_forward_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio, coeff,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "walk_forward_impact_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"impact_coefficients": impact_coefficients, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nMarket impact sweep ({len(impact_coefficients)} coefficients) saved to: {sweep_path}")
        print("Impact coefficient | Total OOS Return | OOS Sharpe | minSR | note | Deflated Sharpe | N Periods")
        print("-" * 90)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['impact_coefficient']:>17} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {minSR_txt:>9} | {note:>16} | {dsr_txt:>15} | {row['n_periods']:>9}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    if len(borrow_costs) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in borrow_costs:
            row = _walk_forward_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=cost, funding_cost=args.funding_cost,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "walk_forward_borrow_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"borrow_costs": borrow_costs, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nBorrow-cost sweep ({len(borrow_costs)} costs) saved to: {sweep_path}")
        print("Borrow Cost | Total OOS Return | OOS Sharpe | minSR | note | Deflated Sharpe | N Periods")
        print("-" * 90)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['borrow_cost']:>13.4f} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {minSR_txt:>9} | {note:>16} | {dsr_txt:>15} | {row['n_periods']:>9}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    if len(funding_costs) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in funding_costs:
            row = _walk_forward_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=args.borrow_cost, funding_cost=cost,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "walk_forward_funding_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"funding_costs": funding_costs, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nFunding-cost sweep ({len(funding_costs)} costs) saved to: {sweep_path}")
        print("Funding Cost | Total OOS Return | OOS Sharpe | minSR | note | Deflated Sharpe | N Periods")
        print("-" * 90)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['funding_cost']:>13.4f} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {minSR_txt:>9} | {note:>16} | {dsr_txt:>15} | {row['n_periods']:>9}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    commissions = [float(c) for c in (args.commissions or [args.commission])]
    slippages = [float(s) for s in (args.slippages or [args.slippage])]

    # Commission sensitivity sweep for walk-forward: re-run the walk-forward
    # pipeline for each commission rate and record degradation in a single
    # artifact. Varies commission while leaving impact/borrow/funding/slippage
    # at their single-run values.
    if len(commissions) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in commissions:
            row = _walk_forward_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=args.borrow_cost,
                funding_cost=args.funding_cost, commission=cost,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "walk_forward_commission_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"commissions": commissions, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nCommission sweep ({len(commissions)} rates) saved to: {sweep_path}")
        print("Commission | Total OOS Return | OOS Sharpe | minSR | note | Deflated Sharpe | N Periods")
        print("-" * 90)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['commission']:>13.6f} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {minSR_txt:>9} | {note:>16} | {dsr_txt:>15} | {row['n_periods']:>9}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    # Slippage sensitivity sweep for walk-forward: re-run the walk-forward
    # pipeline for each slippage rate and record degradation in a single
    # artifact. Varies slippage while leaving impact/borrow/funding/commission
    # at their single-run values.
    if len(slippages) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in slippages:
            row = _walk_forward_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=args.borrow_cost,
                funding_cost=args.funding_cost, slippage=cost,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "walk_forward_slippage_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"slippages": slippages, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nSlippage sweep ({len(slippages)} rates) saved to: {sweep_path}")
        print("Slippage | Total OOS Return | OOS Sharpe | minSR | note | Deflated Sharpe | N Periods")
        print("-" * 90)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['slippage']:>13.6f} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {minSR_txt:>9} | {note:>16} | {dsr_txt:>15} | {row['n_periods']:>9}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    results = walk_forward_analysis(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        train_months=args.train_months,
        test_months=args.test_months,
        step_months=args.step_months,
        commission=args.commission,
        slippage=args.slippage,
        impact_coefficient=args.impact_coefficient,
        adv_window=args.adv_window,
        borrow_cost=args.borrow_cost,
        funding_cost=args.funding_cost,
        latency=latency,
        fill_rate=fill_rate,
        apply_deflation=args.deflate,
        benchmark=benchmark,
        total_return_benchmark=total_return_benchmark,
        benchmark_commission=bench_commission,
        benchmark_slippage=bench_slippage,
        benchmark_expense_ratio=bench_expense_ratio,
        benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
        panel_pricing=getattr(args, "panel_pricing", "net-exposure"),
        impact_aggregation=getattr(args, "impact_aggregation", "panel"),
    )
    if pit_results is not None:
        results["point_in_time_validation"] = pit_results

    # Compute benchmark comparison metrics if benchmark provided
    benchmark_returns = None
    benchmark_returns_list = None
    if benchmark is not None and len(results["oos_returns"]) > 0:
        if isinstance(benchmark, list):
            # Multiple benchmarks: the aggregate Deflated Alpha comparison is
            # already computed inside walk_forward_analysis; expose the aligned
            # benchmark returns to calculate_metrics (which surfaces the
            # canonical deflated_alpha via its benchmark_list path).
            benchmark_returns_list = []
            for b in benchmark:
                br = _compute_benchmark_returns(b, results["oos_returns"], total_return_benchmark)
                if br is not None:
                    benchmark_returns_list.append(br)
            if benchmark_returns_list and results["summary"].get("deflated_alpha") is None:
                # Defensive: ensure a deflated_alpha surfaces even if
                # walk_forward_analysis did not compute one (e.g. degenerate
                # returns).
                correction = _benchmark_list_alpha_correction(
                    results["oos_returns"], benchmark,
                    total_return_benchmark=total_return_benchmark,
                    benchmark_commission=bench_commission,
                    benchmark_slippage=bench_slippage,
                    benchmark_expense_ratio=bench_expense_ratio,
                    benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
                )
                if correction["deflated_alpha"] is not None:
                    results["summary"]["deflated_alpha"] = correction["deflated_alpha"]
                results["summary"]["benchmark_metrics"] = correction["per_benchmark"]
        else:
            benchmark_returns = _compute_benchmark_returns(benchmark, results["oos_returns"], total_return_benchmark)
            if benchmark_returns is not None:
                # Add benchmark metrics to summary
                results["summary"] = _add_benchmark_to_summary(
                    results["summary"], results["oos_returns"], benchmark_returns,
                    commission=bench_commission, slippage=bench_slippage,
                    benchmark_expense_ratio=bench_expense_ratio, total_return_benchmark=total_return_benchmark,
                    benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
                    benchmark_data=benchmark,
                )
                print(
                    f"Benchmark Correlation: {results['summary'].get('correlation_with_benchmark', 'N/A'):.4f}"
                )
                print(
                    f"Alpha (annualized): {results['summary'].get('alpha', 'N/A'):.2%}"
                )
                print(
                    f"Beta: {results['summary'].get('beta', 'N/A'):.4f}"
                )
                pval = results["summary"].get("alpha_pvalue")
                print(
                    f"Alpha p-value: {pval if pval is None else f'{pval:.4f}'}"
                )
                rs = results["summary"].get("r_squared")
                print(
                    f"R-squared: {rs if rs is None else f'{rs:.4f}'}"
                )

    print(f"Number of walk-forward periods: {results['summary']['n_periods']}")
    # A grid key that did not change the strategy's behaviour makes the
    # per-period selection over it a null experiment: say so next to the
    # periods, not only in the summary JSON.
    _print_inert_grid_warning(results["summary"].get("inert_grid_message"))
    # A run that selected nothing says why, next to the period count, so the
    # console and the artifact carry the same diagnosis.
    _print_no_selection_diagnosis(
        results["summary"].get("no_selection_diagnosis")
    )
    # A run in which only some periods could select a parameter says which
    # periods were flat and why, next to the period count.
    _print_partial_selection_diagnosis(
        results["summary"].get("partial_selection_diagnosis")
    )
    # A verdict that rests on some periods also rests on how much of those
    # periods the strategy actually traded in: a "low" rating earned on two
    # periods that each traded for one bar says little about the strategy.
    _print_thin_evidence_warning(
        results["summary"].get("thin_evidence_warning")
    )
    thin_evidence_failed = _thin_evidence_failure(
        results["summary"], min_position_fraction
    )
    if thin_evidence_failed is not None:
        print(f"REJECTED: {thin_evidence_failed['message']}")
    _total_oos_return = results["summary"]["total_oos_return"]
    print(
        f"Total OOS Return: {'N/A' if _total_oos_return is None else f'{_total_oos_return:.2%}'}"
    )
    print(f"OOS Sharpe Ratio: {results['summary'].get('oos_sharpe', 'N/A')}")
    _print_panel_pricing(results["summary"].get("panel_pricing"))
    _print_execution_warmup(results["summary"])
    _print_book_diagnostic(
        results["summary"].get("book_diagnostic"),
        panel_pricing=results["summary"].get("panel_pricing"),
    )
    _print_capacity(results["summary"])

    dsr = results["summary"].get("deflated_sharpe")
    if dsr is not None:
        print(
            f"Deflated Sharpe Ratio: {dsr['deflated_sharpe_ratio']:.4f} "
            f"(p-value {dsr['p_value']:.4f}, expected max Sharpe "
            f"{dsr['expected_max_sharpe']:.4f}, {dsr['n_trials']} trials)"
        )
    # The aggregate Deflated Alpha Ratio: the statistic the alpha resolution
    # below belongs to.
    _print_deflated_alpha(results["summary"].get("deflated_alpha"))
    # What the significance tests could have detected at the sample size
    # actually available: the smallest confirmable effect. A measurement, not
    # a correction -- it changes no verdict and no reported number.
    _print_test_resolution(results["summary"].get("test_resolution"))

    # Check for overfitting
    diagnostics = overfitting_check(results)
    _print_overfitting_risk(diagnostics)

    # Save results
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save summary as JSON
    summary_path = output_dir / "walk_forward_summary.json"
    summary_data = {
        "summary": results["summary"],
        "diagnostics": diagnostics,
        "best_params_per_period": results["best_params_per_period"],
        # Per-period market-impact capacity so capacity degradation across
        # periods/regimes is observable from the saved artifact alone. The
        # trend carries the per-window distribution (min / median) so a
        # liquidity squeeze inside a period is visible too.
        "capacity_per_period": [
            {
                "period": i,
                "test_start": p.get("test_start"),
                "test_end": p.get("test_end"),
                "capacity": p.get("capacity"),
                "capacity_trend": p.get("capacity_trend"),
                # Book-based capacity for the period (book pricing mode only):
                # the capacity implied by the strategy's own trade sizes.
                "capacity_book": p.get("capacity_book"),
                "capacity_book_trend": p.get("capacity_book_trend"),
                # Panel book diagnostic for the period's test window: the
                # per-asset book against the framework's net-exposure
                # pricing (measurement only).
                "book_diagnostic": p.get("book_diagnostic"),
            }
            for i, p in enumerate(results.get("periods", []))
        ],
        "config": {
            "strategy": args.strategy,
            "symbol": args.symbol,
            "train_months": args.train_months,
            "test_months": args.test_months,
            "step_months": args.step_months,
            "commission": args.commission,
            "slippage": args.slippage,
            "impact_coefficient": args.impact_coefficient,
            "adv_window": args.adv_window,
            "borrow_cost": args.borrow_cost,
            "funding_cost": args.funding_cost,
            "latency": latency,
            "fill_rate": fill_rate,
            "deflate": bool(getattr(args, "deflate", False)),
            "param_grid": param_grid,
            "point_in_time_validation": pit_results,
            "bias_controls_engaged": pit_results is not None,
            "benchmark": getattr(args, "benchmark", None),
            "total_return_benchmark": total_return_benchmark,
            "benchmark_commission": bench_commission,
            "benchmark_slippage": bench_slippage,
            "benchmark_expense_ratio": bench_expense_ratio,
            "benchmark_cost_is_periodic": getattr(args, "benchmark_cost_is_periodic", False),
            "multi_symbol": getattr(args, "multi_symbol", False),
            # The execution warmup this run applied, so the saved artifact
            # records how many leading bars of every window are not tradable.
            **execution_warmup_metadata(WARMUP_CONVENTION_WALK_FORWARD, latency),
        },
    }
    if pit_results is not None:
        results["point_in_time_validation"] = pit_results
        summary_data["point_in_time_validation"] = pit_results
    results["bias_controls_engaged"] = bool(pit_results is not None or survivorship is not None)
    summary_data["bias_controls_engaged"] = bool(pit_results is not None or survivorship is not None)
    if survivorship is not None:
        results["survivorship_bias"] = survivorship
        summary_data["survivorship_bias"] = survivorship
        # Persist the survivorship-bias report as a standalone artifact so
        # panel walk-forward runs are auditable on the same file name used by
        # the run_backtest CLI path.
        surv_path = output_dir / "survivorship_bias.json"
        with open(surv_path, "w") as f:
            json.dump(survivorship, f, indent=2, default=str)
        print(f"Survivorship bias report saved to: {surv_path}")
    if benchmark_provenance is not None:
        if isinstance(benchmark_provenance, list):
            summary_data["benchmark_provenance"] = [bp.to_dict() for bp in benchmark_provenance if bp is not None]
        else:
            summary_data["benchmark_provenance"] = benchmark_provenance.to_dict()
    with open(summary_path, "w") as f:
        json.dump(summary_data, f, indent=2, default=str)
    print(f"Walk-forward summary saved to: {summary_path}")

    # Generate full report if OOS returns available
    if len(results["oos_returns"]) > 0:
        equity = (1 + results["oos_returns"]).cumprod() * args.initial_capital
        report_results = {
            "equity_curve": equity,
            "returns": results["oos_returns"],
            "config": {
                "initial_capital": args.initial_capital,
                "commission": args.commission,
                "slippage": args.slippage,
                "strategy": args.strategy,
                "symbol": args.symbol,
                "total_return_benchmark": total_return_benchmark,
                "benchmark_commission": bench_commission,
                "benchmark_slippage": bench_slippage,
                "benchmark_cost_is_periodic": getattr(args, "benchmark_cost_is_periodic", False),
            },
        }
        if benchmark_returns is not None:
            report_results["benchmark"] = benchmark_returns
        elif benchmark_returns_list:
            report_results["benchmark_list"] = benchmark_returns_list
        # Thread benchmark provenance through the report results so the
        # tear-sheet summary is traceable to the exact benchmark file(s).
        # Single-benchmark path: benchmark_provenance is a DataProvenance;
        # multi-benchmark path: it is a list of them (matching the shape of
        # results["benchmark_list"] / results["benchmark_provenance"] used by
        # the run_backtest CLI path).
        if benchmark_provenance is not None:
            report_results["benchmark_provenance"] = benchmark_provenance
        if pit_results is not None:
            report_results["point_in_time_validation"] = pit_results
        if survivorship is not None:
            report_results["survivorship_bias"] = survivorship
        report_results["bias_controls_engaged"] = bool(pit_results is not None or survivorship is not None)
        metrics = calculate_metrics(report_results)
        generate_report(metrics, args.output, symbol=args.symbol, strategy_name=f"{args.strategy}_walk_forward")
        generate_tear_sheet(
            report_results, metrics, args.output,
            symbol=args.symbol,
            strategy_name=f"{args.strategy}_walk_forward",
            analysis_results={"walk_forward": results},
        )
        print(f"Detailed report saved to: {args.output}/")

    return 1 if thin_evidence_failed else 0


def run_parameter_optimization(args) -> int:
    """Run parameter optimization from CLI args."""
    print(f"Loading data from {args.data}...")
    data, pit_results, survivorship = _load_and_validate_data(
        args.data, args.symbol, args.start, args.end,
        validate_pit=getattr(args, "validate_point_in_time", True),
        pit_strict=getattr(args, "point_in_time_strict", False),
        multi_symbol=getattr(args, "multi_symbol", False),
    )

    # Load benchmark if provided
    benchmark = None
    benchmark_provenance = None
    total_return_benchmark = getattr(args, "total_return_benchmark", False)
    bench_commission = getattr(args, "benchmark_commission", None) if getattr(args, "benchmark_commission", None) is not None else args.commission
    bench_slippage = getattr(args, "benchmark_slippage", None) if getattr(args, "benchmark_slippage", None) is not None else args.slippage
    bench_expense_ratio = getattr(args, "benchmark_expense_ratio", None) if getattr(args, "benchmark_expense_ratio", None) is not None else 0.0
    if getattr(args, "benchmark", None):
        benchmark_paths = args.benchmark if isinstance(args.benchmark, list) else [args.benchmark]
        print(f"Loading benchmark data from {', '.join(benchmark_paths)}...")
        if len(benchmark_paths) == 1:
            benchmark, benchmark_provenance = _load_benchmark(benchmark_paths[0], total_return_benchmark)
        else:
            benchmark = []
            benchmark_provenance = []
            for bench_file in benchmark_paths:
                b, prov = _load_benchmark(bench_file, total_return_benchmark)
                benchmark.append(b)
                benchmark_provenance.append(prov)

    latency, fill_rate = _resolve_latency_fill_rate(args)

    impact_coefficients = [float(c) for c in (args.impact_coefficients or [args.impact_coefficient])]
    borrow_costs = [float(c) for c in (args.borrow_costs or [args.borrow_cost])]
    funding_costs = [float(c) for c in (args.funding_costs or [args.funding_cost])]

    # Capacity / cost sensitivity sweeps for parameter optimization: re-run
    # the optimization pipeline for each coefficient/cost and record
    # degradation in a single artifact. Single value keeps the original path.
    if len(impact_coefficients) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for coeff in impact_coefficients:
            row = _optimize_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio, coeff,
                survivorship=survivorship,
                pit_results=pit_results,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "parameter_optimization_impact_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"impact_coefficients": impact_coefficients, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nMarket impact sweep ({len(impact_coefficients)} coefficients) saved to: {sweep_path}")
        print("Impact coefficient | Top Sharpe | minSR | note | Top Total Return | N Combos")
        print("-" * 70)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["top_sharpe"] is None else f"{row['top_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            print(
                f"{row['impact_coefficient']:>17} | {sharpe_txt:>10} | {minSR_txt:>9} | {note:>16} | "
                f"{row['top_total_return']:>16.4f} | {row['n_combos']:>7}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    if len(borrow_costs) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in borrow_costs:
            row = _optimize_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=cost, funding_cost=args.funding_cost,
                pit_results=pit_results,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "parameter_optimization_borrow_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"borrow_costs": borrow_costs, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nBorrow-cost sweep ({len(borrow_costs)} costs) saved to: {sweep_path}")
        print("Borrow Cost | Top Sharpe | minSR | note | Top Total Return | N Combos")
        print("-" * 70)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["top_sharpe"] is None else f"{row['top_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            print(
                f"{row['borrow_cost']:>13.4f} | {sharpe_txt:>10} | {minSR_txt:>9} | {note:>16} | "
                f"{row['top_total_return']:>16.4f} | {row['n_combos']:>7}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    if len(funding_costs) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in funding_costs:
            row = _optimize_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=args.borrow_cost, funding_cost=cost,
                pit_results=pit_results,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "parameter_optimization_funding_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"funding_costs": funding_costs, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nFunding-cost sweep ({len(funding_costs)} costs) saved to: {sweep_path}")
        print("Funding Cost | Top Sharpe | minSR | note | Top Total Return | N Combos")
        print("-" * 70)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["top_sharpe"] is None else f"{row['top_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            print(
                f"{row['funding_cost']:>13.4f} | {sharpe_txt:>10} | {minSR_txt:>9} | {note:>16} | "
                f"{row['top_total_return']:>16.4f} | {row['n_combos']:>7}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    # Execution-latency / partial-fill sweeps for parameter optimization:
    # re-run the optimization pipeline for each latency / fill-rate and
    # record degradation in a single artifact. Single value keeps the
    # original path.
    latencies = [int(l) for l in (args.latencies or [args.latency])]
    fill_rates = [float(f) for f in (args.fill_rates or [args.fill_rate])]
    if _run_latency_fill_rate_sweep(
        args,
        runner=lambda v, key: _optimize_sweep_coefficient(
            args, data, benchmark, total_return_benchmark,
            bench_commission, bench_slippage, bench_expense_ratio,
            args.impact_coefficient, borrow_cost=args.borrow_cost,
            funding_cost=args.funding_cost, **{key: v},
            pit_results=pit_results, survivorship=survivorship,
        ),
        latency_values=latencies,
        fill_rate_values=fill_rates,
        latency_artifact="parameter_optimization_latency_sweep.json",
        fill_rate_artifact="parameter_optimization_fill_rate_sweep.json",
        latency_header=["Latency", "Top Sharpe", "Top Total Return", "N Combos"],
        fill_rate_header=["Fill Rate", "Top Sharpe", "Top Total Return", "N Combos"],
        row_cells=lambda row, key: [
            str(row[key]),
            "N/A" if row["top_sharpe"] is None else f"{row['top_sharpe']:.4f}",
            "N/A" if row["top_total_return"] is None else f"{row['top_total_return']:.4f}",
            str(row["n_combos"]),
        ],
    ):
        return 0

    commissions = [float(c) for c in (args.commissions or [args.commission])]
    slippages = [float(s) for s in (args.slippages or [args.slippage])]

    # Commission sensitivity sweep for parameter optimization: re-run the
    # optimization pipeline for each commission rate and record degradation
    # in a single artifact. Varies commission while leaving impact/borrow/
    # funding/slippage at their single-run values.
    if len(commissions) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in commissions:
            row = _optimize_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=args.borrow_cost,
                funding_cost=args.funding_cost, commission=cost,
                pit_results=pit_results,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "parameter_optimization_commission_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"commissions": commissions, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nCommission sweep ({len(commissions)} rates) saved to: {sweep_path}")
        print("Commission | Top Sharpe | minSR | note | Top Total Return | N Combos")
        print("-" * 70)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["top_sharpe"] is None else f"{row['top_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            print(
                f"{row['commission']:>13.6f} | {sharpe_txt:>10} | {minSR_txt:>9} | {note:>16} | "
                f"{row['top_total_return']:>16.4f} | {row['n_combos']:>7}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    # Slippage sensitivity sweep for parameter optimization: re-run the
    # optimization pipeline for each slippage rate and record degradation in
    # a single artifact. Varies slippage while leaving impact/borrow/funding/
    # commission at their single-run values.
    if len(slippages) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in slippages:
            row = _optimize_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=args.borrow_cost,
                funding_cost=args.funding_cost, slippage=cost,
                pit_results=pit_results,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "parameter_optimization_slippage_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"slippages": slippages, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nSlippage sweep ({len(slippages)} rates) saved to: {sweep_path}")
        print("Slippage | Top Sharpe | minSR | note | Top Total Return | N Combos")
        print("-" * 70)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["top_sharpe"] is None else f"{row['top_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            print(
                f"{row['slippage']:>13.6f} | {sharpe_txt:>10} | {minSR_txt:>9} | {note:>16} | "
                f"{row['top_total_return']:>16.4f} | {row['n_combos']:>7}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    print(f"Running parameter optimization with {args.strategy}...")
    # The inert-grid measurement is requested from the analysis function so
    # the ranking artifact can record it. The function itself never prints.
    inert_report: Dict[str, Any] = {}
    results = parameter_optimization(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        commission=args.commission,
        slippage=args.slippage,
        impact_coefficient=args.impact_coefficient,
        adv_window=args.adv_window,
        borrow_cost=args.borrow_cost,
        funding_cost=args.funding_cost,
        latency=latency,
        fill_rate=fill_rate,
        apply_deflation=args.deflate,
        benchmark=benchmark,
        total_return_benchmark=total_return_benchmark,
        benchmark_commission=bench_commission,
        benchmark_slippage=bench_slippage,
        benchmark_expense_ratio=bench_expense_ratio,
        benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
        panel_pricing=getattr(args, "panel_pricing", "net-exposure"),
        impact_aggregation=getattr(args, "impact_aggregation", "panel"),
        inert_grid_report=inert_report,
    )

    if not results:
        print("No valid parameter combinations found!")
        return 1

    print(f"\nTop {min(args.top_n, len(results))} parameter combinations:")
    print("-" * 80)
    print(f"{'Rank':<5} {'Sharpe':<10} {'Total Return':<15} {'Alpha':<12} {'Beta':<8} {'Corr':<8} {'Params'}")
    print("-" * 80)
    for i, r in enumerate(results[:args.top_n]):
        alpha_str = f"{r.get('alpha', 0):.2%}" if 'alpha' in r else "N/A"
        beta_str = f"{r.get('beta', 0):.4f}" if 'beta' in r else "N/A"
        corr_str = f"{r.get('correlation_with_benchmark', 0):.4f}" if 'correlation_with_benchmark' in r else "N/A"
        print(f"{i+1:<5} {r['sharpe_ratio']:<10.4f} {r['total_return']:<15.2%} {alpha_str:<12} {beta_str:<8} {corr_str:<8} {r['params']}")
        if "deflated_sharpe" in r:
            dsr = r["deflated_sharpe"]
            print(
                f"      Deflated Sharpe Ratio: {dsr['deflated_sharpe_ratio']:.4f} "
                f"(p-value {dsr['p_value']:.4f}, expected max Sharpe "
                f"{dsr['expected_max_sharpe']:.4f}, {dsr['n_trials']} trials)"
            )
    # A grid key that did not change the strategy's behaviour makes the
    # ranking over it a null experiment: say so next to the ranking, not
    # only in the artifact.
    _print_inert_grid_warning(inert_report.get("message"))

    # Print benchmark comparison summary if benchmark provided
    if benchmark is not None and results and 'alpha' in results[0]:
        best = results[0]
        bench_str = f"{len(benchmark)} benchmarks" if isinstance(benchmark, list) and len(benchmark) > 1 else "benchmark"
        print(
            f"\nBenchmark Comparison (best params, {bench_str}):"
        )
        if isinstance(best.get("benchmark_metrics"), list):
            # Multiple benchmarks
            for i, bench_result in enumerate(best["benchmark_metrics"]):
                if bench_result is not None:
                    print(
                        f"  Benchmark {i+1}:"
                    )
                    print(
                        f"    Correlation: {bench_result.get('correlation_with_benchmark', 'N/A'):.4f}"
                    )
                    print(
                        f"    Alpha (annualized): {bench_result.get('alpha', 'N/A'):.2%}"
                    )
                    print(
                        f"    Beta: {bench_result.get('beta', 'N/A'):.4f}"
                    )
                    if 'alpha_pvalue_original' in bench_result:
                        print(
                            f"    Alpha p-value (original): {bench_result['alpha_pvalue_original'] if bench_result['alpha_pvalue_original'] is None else f'{bench_result['alpha_pvalue_original']:.4f}'}"
                        )
                        print(
                            f"    Alpha p-value (corrected): {bench_result['alpha_pvalue'] if bench_result['alpha_pvalue'] is None else f'{bench_result['alpha_pvalue']:.4f}'} "
                        )
                    else:
                        pval = bench_result.get("alpha_pvalue")
                        print(
                            f"    Alpha p-value: {pval if pval is None else f'{pval:.4f}'}"
                        )
                    rs = bench_result.get("r_squared")
                    print(
                        f"    R-squared: {rs if rs is None else f'{rs:.4f}'}"
                    )
        else:
            # Single benchmark (backward compatibility)
            print(
                f"  Correlation: {best.get('correlation_with_benchmark', 'N/A'):.4f}"
            )
            print(
                f"  Alpha (annualized): {best.get('alpha', 'N/A'):.2%}"
            )
            print(
                f"  Beta: {best.get('beta', 'N/A'):.4f}"
            )
            pval = best.get("alpha_pvalue")
            print(
                f"  Alpha p-value: {pval if pval is None else f'{pval:.4f}'}"
            )
            rs = best.get("r_squared")
            print(
                f"  R-squared: {rs if rs is None else f'{rs:.4f}'}"
            )
            ir = best.get("information_ratio")
            if ir is not None and np.isfinite(ir):
                print(f"  Information Ratio: {ir:.4f}")
        if "deflated_alpha" in best and best["deflated_alpha"] is not None:
            da = best["deflated_alpha"]
            print(
                f"  Deflated Alpha Ratio: {da.get('deflated_alpha_ratio', 'N/A'):.4f} "
                f"(p-value {da.get('p_value', 'N/A'):.4f}, expected max alpha "
                f"{da.get('expected_max_alpha', 'N/A'):.6f}, {da.get('n_benchmarks', 0)} benchmarks)"
            )

    # Save results
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    results_path = output_dir / "parameter_optimization.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull results saved to: {results_path}")

    # The ranking artifact is a plain ranked list, so the inert-grid finding
    # is written next to it as a separate record: a reader of the ranking can
    # see that the grid never changed the strategy's behaviour, and that the
    # ranking is therefore a null experiment rather than evidence.
    inert_path = output_dir / "parameter_optimization_inert_grid.json"
    with open(inert_path, "w") as f:
        json.dump(
            {
                "inert_grid_params": inert_report.get("inert_grid_params") or [],
                "inert_grid_message": inert_report.get("message"),
                "strategy_parameters": inert_report.get("strategy_parameters") or [],
                "param_grid": param_grid,
                "strategy": args.strategy,
                "n_ranked_combinations": len(results),
            },
            f,
            indent=2,
            default=str,
        )
    print(f"Inert-grid record saved to: {inert_path}")

    # Persist PIT validation results alongside the optimization artifact
    # so the data-integrity baseline is reproducible with the search.
    if pit_results is not None:
        pit_path = output_dir / "point_in_time_validation.json"
        with open(pit_path, "w") as f:
            json.dump(pit_results, f, indent=2, default=str)

    # Persist benchmark provenance if available
    if benchmark_provenance is not None:
        bench_prov_path = output_dir / "benchmark_provenance.json"
        with open(bench_prov_path, "w") as f:
            if isinstance(benchmark_provenance, list):
                json.dump([bp.to_dict() for bp in benchmark_provenance if bp is not None], f, indent=2, default=str)
            else:
                json.dump(benchmark_provenance.to_dict(), f, indent=2, default=str)
        print(f"Benchmark provenance saved to: {bench_prov_path}")

    # Persist the survivorship-bias report as a standalone artifact so panel
    # parameter-optimization runs are auditable on the same file name used by
    # the run_backtest CLI path.
    if survivorship is not None:
        surv_path = output_dir / "survivorship_bias.json"
        with open(surv_path, "w") as f:
            json.dump(survivorship, f, indent=2, default=str)
        print(f"Survivorship bias report saved to: {surv_path}")

    return 0


def _monte_carlo_sweep_coefficient(args, data, benchmark, total_return_benchmark,
                                    bench_commission, bench_slippage, bench_expense_ratio,
                                    impact_coefficient, borrow_cost=None, funding_cost=None,
                                    commission=None, slippage=None, latency=None, fill_rate=None,
                                    pit_results=None, survivorship=None):
    """Run the Monte Carlo pipeline for a single cost coefficient (sweep helper).

    No file I/O or stdout; returns the per-coefficient metrics used by the
    sweep table and JSON artifact. Mirrors the single-run body of
    run_monte_carlo (parameter selection, cost backtest, Deflated
    Sharpe correction, Monte Carlo simulation) for one coefficient value.

    `borrow_cost` / `funding_cost` / `commission` / `slippage` default to the
    CLI args when None, so the same helper serves the market-impact sweep
    (which varies only `impact_coefficient`), the borrow/funding sweeps
    (which vary one of those while leaving the others at their single-run
    values), and the commission/slippage sweeps (which vary one of those
    while leaving impact/borrow/funding at their single-run values).

    `latency` / `fill_rate` default to the CLI args when None, so the same
    helper serves the latency / fill-rate sweeps (which vary only one of
    those while leaving the other at its single-run value).

    `pit_results` carries the point-in-time validation outcome from the
    caller so the sweep artifact records the same bias-controls engagement
    flag as the single-run Monte Carlo JSON.
    `survivorship` carries the survivorship-bias detection report from the
    caller so the sweep artifact records the same bias-controls signal as the
    single-run Monte Carlo JSON.
    """
    if borrow_cost is None:
        borrow_cost = args.borrow_cost
    if funding_cost is None:
        funding_cost = args.funding_cost
    if commission is None:
        commission = args.commission
    if slippage is None:
        slippage = args.slippage
    if latency is None:
        latency = getattr(args, "latency", 0)
    if latency is None:
        latency = 0
    if latency < 0:
        latency = 0
    if fill_rate is None:
        fill_rate = getattr(args, "fill_rate", 1.0)
    if fill_rate is None:
        fill_rate = 1.0
    if fill_rate <= 0 or fill_rate > 1:
        raise ValueError(f"fill_rate must be in (0, 1], got {fill_rate}")
    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    opt_results = None
    if param_grid:
        opt_results = parameter_optimization(
            data=data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            commission=commission,
            slippage=slippage,
            impact_coefficient=impact_coefficient,
            adv_window=args.adv_window,
            borrow_cost=borrow_cost,
            funding_cost=funding_cost,
            latency=latency,
            fill_rate=fill_rate,
            benchmark=benchmark,
            total_return_benchmark=total_return_benchmark,
            benchmark_commission=bench_commission,
            benchmark_slippage=bench_slippage,
            benchmark_expense_ratio=bench_expense_ratio,
            benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
            panel_pricing=getattr(args, "panel_pricing", "net-exposure"),
        )
        if opt_results:
            best_params = opt_results[0]["params"]
        else:
            param_names = list(param_grid.keys())
            param_values = list(param_grid.values())
            first_combo = next(product(*param_values))
            best_params = dict(zip(param_names, first_combo))
    else:
        best_params = {}

    strategy = strategy_factory(best_params)
    signals = strategy.generate_signals(data)
    panel_pricing = resolve_panel_pricing(getattr(args, "panel_pricing", None))
    book_weights = (
        strategy_target_weights(strategy, data)
        if panel_pricing == "book"
        else None
    )
    returns = _calculate_strategy_returns(data, signals, commission, slippage,
                                          impact_coefficient, args.adv_window,
                                          borrow_cost, funding_cost,
                                          latency=latency, fill_rate=fill_rate,
                                          initial_capital=args.initial_capital,
                                          panel_pricing=panel_pricing,
                                          book_weights=book_weights)

    dsr = None
    n_trials = getattr(args, "n_trials", None)
    if n_trials is not None and int(n_trials) >= 1 and len(returns.dropna()) >= 2:
        # Reconcile with walk_forward_analysis/cpcv/out_of_sample_validation:
        # use the actually-evaluated combo count when a grid was searched, so
        # Deflated Sharpe p-values are comparable across paths.
        if opt_results:
            effective_n_trials = len(opt_results)
        else:
            effective_n_trials = int(n_trials)
        base_results = {
            "equity_curve": (1 + returns).cumprod() * args.initial_capital,
            "returns": returns,
            "config": {
                "initial_capital": args.initial_capital,
                "commission": commission,
                "slippage": slippage,
                "strategy": args.strategy,
                "symbol": args.symbol,
                "n_trials": effective_n_trials,
            },
        }
        if opt_results:
            base_results["config"]["trial_sharpes"] = [
                r["sharpe_ratio"] for r in opt_results
            ]
        dsr = calculate_metrics(base_results).get("deflated_sharpe")

    mc_results = monte_carlo_simulation(
        base_returns=returns,
        n_simulations=args.n_simulations,
        confidence_levels=args.confidence_levels,
        block_size=args.block_size,
        seed=args.seed if args.seed is not None else 0,
    )

    sm = mc_results["summary"]
    mc_sharpe = float(sm.get("sharpe_ratio", {}).get("mean", 0.0))
    # The Monte Carlo point's Deflated Sharpe was computed on `returns`
    # (via calculate_metrics over base_results), so the resolution of that
    # statistic is built on the same series it was computed on and shares its
    # observation count -- never re-derived elsewhere.
    resolution = (
        _build_test_resolution({"deflated_sharpe": dsr}, returns) if dsr is not None else None
    )
    return {
        "impact_coefficient": float(impact_coefficient),
        "borrow_cost": float(borrow_cost),
        "funding_cost": float(funding_cost),
        "commission": float(commission),
        "slippage": float(slippage),
        "latency": int(latency),
        "fill_rate": float(fill_rate),
        "total_return": float(sm.get("total_return", {}).get("mean", 0.0)),
        "sharpe_ratio": mc_sharpe,
        "max_drawdown": float(sm.get("max_drawdown", {}).get("mean", 0.0)),
        "probability_of_ruin": float(mc_results["probability_of_ruin"]),
        "deflated_sharpe": (float(dsr["deflated_sharpe_ratio"]) if dsr is not None else None),
        "deflated_sharpe_n_trials": (
            int(dsr["n_trials"]) if dsr is not None and dsr.get("n_trials") is not None else None
        ),
        "n_simulations": int(mc_results["n_simulations"]),
        "test_resolution": resolution,
        "sharpe_below_resolution": _sweep_sharpe_below_resolution(mc_sharpe, resolution),
        # Bias-controls engagement flag (point-in-time validation + multiple-
        # testing deflation). Propagated from the CLI args so the sweep artifact
        # is traceable to the same signal as the single-run Monte Carlo JSON.
        "bias_controls_engaged": bool(pit_results is not None or survivorship is not None),
        # Survivorship-bias detection report (multi-symbol panels). Threaded
        # through so a panel Monte Carlo sweep is traceable to the universe
        # selection risk flagged at load time.
        "survivorship_bias": survivorship,
    }


def run_monte_carlo(args) -> int:
    """Run Monte Carlo simulation from CLI args."""
    print(f"Loading data from {args.data}...")
    data, pit_results, survivorship = _load_and_validate_data(
        args.data, args.symbol, args.start, args.end,
        validate_pit=getattr(args, "validate_point_in_time", True),
        pit_strict=getattr(args, "point_in_time_strict", False),
        multi_symbol=getattr(args, "multi_symbol", False),
    )

    # Load benchmark if provided
    benchmark = None
    benchmark_provenance = None
    total_return_benchmark = getattr(args, "total_return_benchmark", False)
    bench_commission = getattr(args, "benchmark_commission", None) if getattr(args, "benchmark_commission", None) is not None else args.commission
    bench_slippage = getattr(args, "benchmark_slippage", None) if getattr(args, "benchmark_slippage", None) is not None else args.slippage
    bench_expense_ratio = getattr(args, "benchmark_expense_ratio", None) if getattr(args, "benchmark_expense_ratio", None) is not None else 0.0
    if getattr(args, "benchmark", None):
        benchmark_paths = args.benchmark if isinstance(args.benchmark, list) else [args.benchmark]
        print(f"Loading benchmark data from {', '.join(benchmark_paths)}...")
        if len(benchmark_paths) == 1:
            benchmark, benchmark_provenance = _load_benchmark(benchmark_paths[0], total_return_benchmark)
        else:
            benchmark = []
            benchmark_provenance = []
            for bench_file in benchmark_paths:
                b, prov = _load_benchmark(bench_file, total_return_benchmark)
                benchmark.append(b)
                benchmark_provenance.append(prov)

    latency, fill_rate = _resolve_latency_fill_rate(args)

    impact_coefficients = [float(c) for c in (args.impact_coefficients or [args.impact_coefficient])]

    # Capacity / market-impact sensitivity sweep: re-run the pipeline for
    # each coefficient and record degradation in a single artifact so the
    # sweep is part of the standard robustness workflow.
    if len(impact_coefficients) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for coeff in impact_coefficients:
            row = _monte_carlo_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio, coeff,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "monte_carlo_impact_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"impact_coefficients": impact_coefficients, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nMarket impact sweep ({len(impact_coefficients)} coefficients) saved to: {sweep_path}")
        print("Impact coefficient | Total Return | Sharpe Ratio | minSR | note | Max Drawdown | Prob. of Ruin | Deflated Sharpe")
        print("-" * 96)
        for row in sweep_rows:
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['impact_coefficient']:>17} | {row['total_return']:>12.4f} | {row['sharpe_ratio']:>12.4f} | {minSR_txt:>9} | {note:>16} | "
                f"{row['max_drawdown']:>12.4f} | {row['probability_of_ruin']:>13.2%} | {dsr_txt:>15}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    borrow_costs = [float(c) for c in (args.borrow_costs or [args.borrow_cost])]
    funding_costs = [float(c) for c in (args.funding_costs or [args.funding_cost])]

    # Borrow-cost sensitivity sweep: re-run the pipeline for each borrow cost
    # and record degradation in a single artifact. Varies short-position
    # borrow cost while leaving impact and funding at their single-run values.
    if len(borrow_costs) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in borrow_costs:
            row = _monte_carlo_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=cost, funding_cost=args.funding_cost,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "monte_carlo_borrow_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"borrow_costs": borrow_costs, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nBorrow-cost sweep ({len(borrow_costs)} costs) saved to: {sweep_path}")
        print("Borrow Cost | Total Return | Sharpe Ratio | minSR | note | Max Drawdown | Prob. of Ruin | Deflated Sharpe")
        print("-" * 96)
        for row in sweep_rows:
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['borrow_cost']:>13.4f} | {row['total_return']:>12.4f} | {row['sharpe_ratio']:>12.4f} | {minSR_txt:>9} | {note:>16} | "
                f"{row['max_drawdown']:>12.4f} | {row['probability_of_ruin']:>13.2%} | {dsr_txt:>15}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    # Funding-cost sensitivity sweep: re-run the pipeline for each funding cost
    # and record degradation in a single artifact. Varies leveraged-position
    # funding cost while leaving impact and borrow at their single-run values.
    if len(funding_costs) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in funding_costs:
            row = _monte_carlo_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=args.borrow_cost, funding_cost=cost,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "monte_carlo_funding_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"funding_costs": funding_costs, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nFunding-cost sweep ({len(funding_costs)} costs) saved to: {sweep_path}")
        print("Funding Cost | Total Return | Sharpe Ratio | minSR | note | Max Drawdown | Prob. of Ruin | Deflated Sharpe")
        print("-" * 96)
        for row in sweep_rows:
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['funding_cost']:>13.4f} | {row['total_return']:>12.4f} | {row['sharpe_ratio']:>12.4f} | {minSR_txt:>9} | {note:>16} | "
                f"{row['max_drawdown']:>12.4f} | {row['probability_of_ruin']:>13.2%} | {dsr_txt:>15}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    # Execution-latency / partial-fill sweeps for Monte Carlo: re-run the
    # Monte Carlo pipeline for each latency / fill-rate and record
    # degradation in a single artifact. Single value keeps the original path.
    latencies = [int(l) for l in (args.latencies or [args.latency])]
    fill_rates = [float(f) for f in (args.fill_rates or [args.fill_rate])]
    if _run_latency_fill_rate_sweep(
        args,
        runner=lambda v, key: _monte_carlo_sweep_coefficient(
            args, data, benchmark, total_return_benchmark,
            bench_commission, bench_slippage, bench_expense_ratio,
            args.impact_coefficient, borrow_cost=args.borrow_cost,
            funding_cost=args.funding_cost, **{key: v},
            survivorship=survivorship,
        ),
        latency_values=latencies,
        fill_rate_values=fill_rates,
        latency_artifact="monte_carlo_latency_sweep.json",
        fill_rate_artifact="monte_carlo_fill_rate_sweep.json",
        latency_header=["Latency", "Total Return", "Sharpe Ratio", "Max Drawdown", "Prob. of Ruin", "Deflated Sharpe"],
        fill_rate_header=["Fill Rate", "Total Return", "Sharpe Ratio", "Max Drawdown", "Prob. of Ruin", "Deflated Sharpe"],
        row_cells=lambda row, key: [
            str(row[key]),
            f"{row['total_return']:.4f}",
            f"{row['sharpe_ratio']:.4f}",
            f"{row['max_drawdown']:.4f}",
            f"{row['probability_of_ruin']:.2%}",
            "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}",
        ],
    ):
        return 0

    commissions = [float(c) for c in (args.commissions or [args.commission])]
    slippages = [float(s) for s in (args.slippages or [args.slippage])]

    # Commission sensitivity sweep: re-run the pipeline for each commission
    # rate and record degradation in a single artifact. Varies commission
    # while leaving impact/borrow/funding/slippage at their single-run values.
    if len(commissions) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in commissions:
            row = _monte_carlo_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=args.borrow_cost,
                funding_cost=args.funding_cost, commission=cost,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "monte_carlo_commission_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"commissions": commissions, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nCommission sweep ({len(commissions)} rates) saved to: {sweep_path}")
        print("Commission | Total Return | Sharpe Ratio | minSR | note | Max Drawdown | Prob. of Ruin | Deflated Sharpe")
        print("-" * 96)
        for row in sweep_rows:
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['commission']:>13.6f} | {row['total_return']:>12.4f} | {row['sharpe_ratio']:>12.4f} | {minSR_txt:>9} | {note:>16} | "
                f"{row['max_drawdown']:>12.4f} | {row['probability_of_ruin']:>13.2%} | {dsr_txt:>15}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    # Slippage sensitivity sweep: re-run the pipeline for each slippage rate
    # and record degradation in a single artifact. Varies slippage while
    # leaving impact/borrow/funding/commission at their single-run values.
    if len(slippages) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in slippages:
            row = _monte_carlo_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=args.borrow_cost,
                funding_cost=args.funding_cost, slippage=cost,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "monte_carlo_slippage_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"slippages": slippages, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nSlippage sweep ({len(slippages)} rates) saved to: {sweep_path}")
        print("Slippage | Total Return | Sharpe Ratio | minSR | note | Max Drawdown | Prob. of Ruin | Deflated Sharpe")
        print("-" * 96)
        for row in sweep_rows:
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['slippage']:>13.6f} | {row['total_return']:>12.4f} | {row['sharpe_ratio']:>12.4f} | {minSR_txt:>9} | {note:>16} | "
                f"{row['max_drawdown']:>12.4f} | {row['probability_of_ruin']:>13.2%} | {dsr_txt:>15}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    # First run a backtest to get base returns
    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    # Use best params from optimization or first combo
    opt_results = None
    if param_grid:
        # Try to get best params from optimization
        opt_results = parameter_optimization(
            data=data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            commission=args.commission,
            slippage=args.slippage,
            impact_coefficient=args.impact_coefficient,
            adv_window=args.adv_window,
            borrow_cost=args.borrow_cost,
            funding_cost=args.funding_cost,
            latency=latency,
            fill_rate=fill_rate,
            benchmark=benchmark,
            total_return_benchmark=total_return_benchmark,
            benchmark_commission=bench_commission,
            benchmark_slippage=bench_slippage,
            benchmark_expense_ratio=bench_expense_ratio,
            benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
            panel_pricing=getattr(args, "panel_pricing", "net-exposure"),
        )
        if opt_results:
            best_params = opt_results[0]["params"]
            print(f"Using best params from optimization: {best_params}")
        else:
            # Use first combo
            param_names = list(param_grid.keys())
            param_values = list(param_grid.values())
            from itertools import product
            first_combo = next(product(*param_values))
            best_params = dict(zip(param_names, first_combo))
            print(f"Using first param combo: {best_params}")
    else:
        best_params = {}

    strategy = strategy_factory(best_params)
    signals = strategy.generate_signals(data)
    panel_pricing = resolve_panel_pricing(getattr(args, "panel_pricing", None))
    book_weights = (
        strategy_target_weights(strategy, data)
        if panel_pricing == "book"
        else None
    )
    returns = _calculate_strategy_returns(data, signals, args.commission, args.slippage,
                                          args.impact_coefficient, args.adv_window,
                                          args.borrow_cost, args.funding_cost,
                                          latency=latency, fill_rate=fill_rate,
                                          initial_capital=args.initial_capital,
                                          panel_pricing=panel_pricing,
                                          book_weights=book_weights)
    # The warmup convention of the series the Monte Carlo resamples.
    _print_execution_warmup(
        execution_warmup_metadata(WARMUP_CONVENTION_WALK_FORWARD, latency)
    )

    # Multiple-testing correction: the base backtest's Sharpe was
    # produced by the parameter search above (or by development
    # trials the caller reports via --n-trials). When the number of
    # development trials is reported, deflate the base Sharpe for
    # selection bias and for the non-normality of returns, mirroring
    # the run_backtest --n-trials path. When the optimization
    # record is available, its trial Sharpes give the cross-sectional
    # SR* estimator (recommended over the i.i.d. null approximation).
    #
    # Trial count: when a parameter grid was searched, the internal
    # optimization evaluated len(opt_results) ranked configurations.
    # The effective trial count is the number of grid combinations
    # actually evaluated, mirroring walk_forward_analysis /
    # cpcv_analysis / out_of_sample_validation so Deflated Sharpe
    # p-values stay comparable across paths. Without a grid (or an
    # empty optimization record) the user-supplied --n-trials is the
    # sole source.
    dsr = None
    n_trials = getattr(args, "n_trials", None)
    effective_n_trials = None
    if n_trials is not None and int(n_trials) >= 1 and len(returns.dropna()) >= 2:
        if opt_results:
            effective_n_trials = len(opt_results)
        else:
            effective_n_trials = int(n_trials)
        base_results = {
            "equity_curve": (1 + returns).cumprod() * args.initial_capital,
            "returns": returns,
            "config": {
                "initial_capital": args.initial_capital,
                "commission": args.commission,
                "slippage": args.slippage,
                "strategy": args.strategy,
                "symbol": args.symbol,
                "n_trials": effective_n_trials,
            },
        }
        if opt_results:
            base_results["config"]["trial_sharpes"] = [
                r["sharpe_ratio"] for r in opt_results
            ]
        dsr = calculate_metrics(base_results).get("deflated_sharpe")

    if dsr is not None:
        print(
            f"Deflated Sharpe Ratio: {dsr['deflated_sharpe_ratio']:.4f} "
            f"(p-value {dsr['p_value']:.4f}, expected max Sharpe "
            f"{dsr['expected_max_sharpe']:.4f}, {dsr['n_trials']} trials)"
        )

    # Compute benchmark comparison metrics if benchmark provided
    benchmark_returns = None
    benchmark_returns_list = None
    if benchmark is not None and len(returns) > 0:
        if isinstance(benchmark, list):
            benchmark_returns_list = []
            for b in benchmark:
                br = _compute_benchmark_returns(b, returns, total_return_benchmark)
                if br is not None:
                    benchmark_returns_list.append(br)
            if benchmark_returns_list:
                bm_stats = _benchmark_list_alpha_correction(
                    returns, benchmark,
                    total_return_benchmark=total_return_benchmark,
                    benchmark_commission=bench_commission,
                    benchmark_slippage=bench_slippage,
                    benchmark_expense_ratio=bench_expense_ratio,
                    benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
                )
                correction = bm_stats
                if correction["deflated_alpha"] is not None:
                    da = correction["deflated_alpha"]
                    print(
                        f"  Deflated Alpha Ratio: {da['deflated_alpha_ratio']:.4f} "
                        f"(p-value {da['p_value']:.4f}, "
                        f"{da['n_benchmarks']} benchmarks)"
                    )
                for i, bench_metric in enumerate(correction["per_benchmark"]):
                    if bench_metric is not None:
                        print(f"  Benchmark {i+1}:")
                        print(
                            f"    Correlation: {bench_metric.get('correlation_with_benchmark', 'N/A'):.4f}"
                        )
                        pval = bench_metric.get("alpha_pvalue")
                        print(
                            f"    Alpha p-value: {pval if pval is None else f'{pval:.4f}'}"
                        )
                        rs = bench_metric.get("r_squared")
                        print(
                            f"    R-squared: {rs if rs is None else f'{rs:.4f}'}"
                        )
        else:
            benchmark_returns = _compute_benchmark_returns(benchmark, returns, total_return_benchmark)
            if benchmark_returns is not None:
                bstats = _benchmark_stats(
                    returns, benchmark_returns, _annualization_factor(returns.index),
                    total_return_benchmark=total_return_benchmark,
                    benchmark_commission=bench_commission,
                    benchmark_slippage=bench_slippage,
                    benchmark_expense_ratio=bench_expense_ratio,
                )
                print(
                    f"Benchmark Correlation: {bstats.get('correlation_with_benchmark', 0):.4f}"
                )
                pval = bstats.get("alpha_pvalue")
                print(
                    f"Alpha p-value: {pval if pval is None else f'{pval:.4f}'}"
                )
                rs = bstats.get("r_squared")
                print(
                    f"R-squared: {rs if rs is None else f'{rs:.4f}'}"
                )

    print(f"Running Monte Carlo simulation with {args.n_simulations} simulations...")
    mc_results = monte_carlo_simulation(
        base_returns=returns,
        n_simulations=args.n_simulations,
        confidence_levels=args.confidence_levels,
        block_size=args.block_size,
        seed=args.seed if args.seed is not None else 0,
    )

    print(f"Probability of Ruin (>50% drawdown): {mc_results['probability_of_ruin']:.2%}")

    # Print confidence intervals for key metrics
    print("\nKey Metric Confidence Intervals (95%):")
    print("-" * 60)
    for metric in ["sharpe_ratio", "total_return", "max_drawdown", "annualized_return"]:
        if metric in mc_results["confidence_intervals"]:
            ci = mc_results["confidence_intervals"][metric].get(0.95)
            if ci:
                mean_val = mc_results["summary"][metric]["mean"]
                print(f"  {metric}: {mean_val:.4f} [{ci[0]:.4f}, {ci[1]:.4f}]")

    # Save results
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    mc_path = output_dir / "monte_carlo_results.json"
    # Convert numpy arrays to lists for JSON serialization
    mc_save = {
        "metric_distributions": {k: v.tolist() for k, v in mc_results["metric_distributions"].items()},
        "confidence_intervals": mc_results["confidence_intervals"],
        "probability_of_ruin": mc_results["probability_of_ruin"],
        "ruin_threshold": mc_results["ruin_threshold"],
        "summary": mc_results["summary"],
        "n_simulations": mc_results["n_simulations"],
        "base_observations": mc_results["base_observations"],
        "block_size_used": mc_results.get("block_size_used"),
        "config": {
            "strategy": args.strategy,
            "symbol": args.symbol,
            "params": best_params,
            "commission": args.commission,
            "slippage": args.slippage,
            "impact_coefficient": args.impact_coefficient,
            "adv_window": args.adv_window,
            "borrow_cost": args.borrow_cost,
            "funding_cost": args.funding_cost,
            "latency": latency,
            "fill_rate": fill_rate,
            "n_simulations": args.n_simulations,
            "block_size": args.block_size,
            "point_in_time_validation": pit_results,
            "bias_controls_engaged": bool(pit_results is not None or survivorship is not None),
            "benchmark": getattr(args, "benchmark", None),
            "total_return_benchmark": total_return_benchmark,
            "benchmark_commission": bench_commission,
            "benchmark_slippage": bench_slippage,
            "benchmark_expense_ratio": bench_expense_ratio,
            "benchmark_cost_is_periodic": getattr(args, "benchmark_cost_is_periodic", False),
            "multi_symbol": getattr(args, "multi_symbol", False),
            # The execution warmup of the return series the Monte Carlo
            # resampled, so the artifact records the convention the
            # resampled series was produced under.
            **execution_warmup_metadata(WARMUP_CONVENTION_WALK_FORWARD, latency),
        },
    }
    if pit_results is not None:
        mc_save["point_in_time_validation"] = pit_results
    mc_save["bias_controls_engaged"] = bool(pit_results is not None or survivorship is not None)
    if survivorship is not None:
        mc_save["survivorship_bias"] = survivorship
    if dsr is not None:
        mc_save["deflated_sharpe"] = dsr
        mc_save["config"]["n_trials"] = effective_n_trials
    if benchmark_provenance is not None:
        if isinstance(benchmark_provenance, list):
            mc_save["benchmark_provenance"] = [bp.to_dict() for bp in benchmark_provenance if bp is not None]
        else:
            mc_save["benchmark_provenance"] = benchmark_provenance.to_dict()
    if benchmark_returns is not None:
        mc_save["summary"] = _add_benchmark_to_summary(
            mc_save["summary"], returns, benchmark_returns,
            commission=bench_commission, slippage=bench_slippage,
            benchmark_expense_ratio=bench_expense_ratio, total_return_benchmark=total_return_benchmark,
            benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
            benchmark_data=benchmark,
        )
    elif benchmark_returns_list:
        correction = _benchmark_list_alpha_correction(
            returns, benchmark,
            total_return_benchmark=total_return_benchmark,
            benchmark_commission=bench_commission,
            benchmark_slippage=bench_slippage,
            benchmark_expense_ratio=bench_expense_ratio,
            benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
        )
        mc_save["summary"]["benchmark_metrics"] = correction["per_benchmark"]
        if correction["deflated_alpha"] is not None:
            mc_save["summary"]["deflated_alpha"] = correction["deflated_alpha"]
    with open(mc_path, "w") as f:
        json.dump(mc_save, f, indent=2, default=str)
    print(f"\nMonte Carlo results saved to: {mc_path}")

    # Generate tear sheet with Monte Carlo analysis rendered as a section
    mc_equity = (1 + returns).cumprod() * args.initial_capital
    mc_base_results = {
        "equity_curve": mc_equity,
        "returns": returns,
"config": {
                "initial_capital": args.initial_capital,
                "commission": args.commission,
                "slippage": args.slippage,
                "strategy": args.strategy,
                "symbol": args.symbol,
                "total_return_benchmark": total_return_benchmark,
                "benchmark_commission": getattr(args, "benchmark_commission", None) if getattr(args, "benchmark_commission", None) is not None else args.commission,
                "benchmark_slippage": getattr(args, "benchmark_slippage", None) if getattr(args, "benchmark_slippage", None) is not None else args.slippage,
                "benchmark_expense_ratio": bench_expense_ratio,
            },
        }
    if benchmark_returns is not None:
        mc_base_results["benchmark"] = benchmark_returns
    elif benchmark_returns_list:
        mc_base_results["benchmark_list"] = benchmark_returns_list
    # Thread benchmark provenance through the tear-sheet results so the
    # Monte Carlo tear sheet can associate each benchmark_metrics row with
    # the exact benchmark file/checksum (mirrors the run_backtest CLI path).
    if benchmark_provenance is not None:
        mc_base_results["benchmark_provenance"] = benchmark_provenance
    mc_base_metrics = calculate_metrics(mc_base_results)
    if dsr is not None:
        mc_base_metrics["deflated_sharpe"] = dsr
    if pit_results is not None:
        mc_base_results["point_in_time_validation"] = pit_results
    if survivorship is not None:
        mc_base_results["survivorship_bias"] = survivorship
    mc_base_results["bias_controls_engaged"] = bool(pit_results is not None or survivorship is not None)
    generate_tear_sheet(
        mc_base_results, mc_base_metrics, args.output,
        symbol=args.symbol,
        strategy_name=f"{args.strategy}_monte_carlo",
        analysis_results={"monte_carlo": mc_results},
    )
    print(f"Tear sheet saved to: {args.output}/tear_sheet.html")

    return 0


def run_out_of_sample_validation(args) -> int:
    """Run out-of-sample validation from CLI args."""
    print(f"Loading data from {args.data}...")
    data, pit_results, survivorship = _load_and_validate_data(
        args.data, args.symbol, args.start, args.end,
        validate_pit=getattr(args, "validate_point_in_time", True),
        pit_strict=getattr(args, "point_in_time_strict", False),
        multi_symbol=getattr(args, "multi_symbol", False),
    )

    # Load benchmark if provided
    benchmark = None
    benchmark_provenance = None
    total_return_benchmark = getattr(args, "total_return_benchmark", False)
    bench_commission = getattr(args, "benchmark_commission", None) if getattr(args, "benchmark_commission", None) is not None else args.commission
    bench_slippage = getattr(args, "benchmark_slippage", None) if getattr(args, "benchmark_slippage", None) is not None else args.slippage
    bench_expense_ratio = getattr(args, "benchmark_expense_ratio", None) if getattr(args, "benchmark_expense_ratio", None) is not None else 0.0
    if getattr(args, "benchmark", None):
        print(f"Loading benchmark data from {', '.join(args.benchmark)}...")
        benchmark = []
        benchmark_provenance = []
        for bench_file in args.benchmark:
            b, prov = _load_benchmark(bench_file, total_return_benchmark)
            benchmark.append(b)
            benchmark_provenance.append(prov)

    latency, fill_rate = _resolve_latency_fill_rate(args)
    min_position_fraction = _resolve_min_position_fraction(args)

    impact_coefficients = [float(c) for c in (args.impact_coefficients or [args.impact_coefficient])]
    borrow_costs = [float(c) for c in (args.borrow_costs or [args.borrow_cost])]
    funding_costs = [float(c) for c in (args.funding_costs or [args.funding_cost])]

    # Capacity / cost sensitivity sweeps for out-of-sample validation: re-run
    # the validation pipeline for each coefficient/cost and record
    # degradation in a single artifact. Single value keeps the original path.
    if len(impact_coefficients) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for coeff in impact_coefficients:
            row = _oos_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio, coeff,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "out_of_sample_impact_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"impact_coefficients": impact_coefficients, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nMarket impact sweep ({len(impact_coefficients)} coefficients) saved to: {sweep_path}")
        print("Impact coefficient | Test Total Return | Test Sharpe | minSR | note | Deflated Sharpe")
        print("-" * 74)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["test_sharpe"] is None else f"{row['test_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['impact_coefficient']:>17} | {row['test_total_return']:>16.4f} | "
                f"{sharpe_txt:>11} | {minSR_txt:>9} | {note:>16} | {dsr_txt:>15}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    if len(borrow_costs) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in borrow_costs:
            row = _oos_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=cost, funding_cost=args.funding_cost,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "out_of_sample_borrow_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"borrow_costs": borrow_costs, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nBorrow-cost sweep ({len(borrow_costs)} costs) saved to: {sweep_path}")
        print("Borrow Cost | Test Total Return | Test Sharpe | minSR | note | Deflated Sharpe")
        print("-" * 74)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["test_sharpe"] is None else f"{row['test_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['borrow_cost']:>13.4f} | {row['test_total_return']:>16.4f} | "
                f"{sharpe_txt:>11} | {minSR_txt:>9} | {note:>16} | {dsr_txt:>15}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    if len(funding_costs) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in funding_costs:
            row = _oos_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=args.borrow_cost, funding_cost=cost,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "out_of_sample_funding_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"funding_costs": funding_costs, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nFunding-cost sweep ({len(funding_costs)} costs) saved to: {sweep_path}")
        print("Funding Cost | Test Total Return | Test Sharpe | minSR | note | Deflated Sharpe")
        print("-" * 74)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["test_sharpe"] is None else f"{row['test_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['funding_cost']:>13.4f} | {row['test_total_return']:>16.4f} | "
                f"{sharpe_txt:>11} | {minSR_txt:>9} | {note:>16} | {dsr_txt:>15}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    # Execution-latency / partial-fill sweeps for out-of-sample validation:
    # re-run the validation pipeline for each latency / fill-rate and record
    # degradation in a single artifact. Single value keeps the original path.
    latencies = [int(l) for l in (args.latencies or [args.latency])]
    fill_rates = [float(f) for f in (args.fill_rates or [args.fill_rate])]
    if _run_latency_fill_rate_sweep(
        args,
        runner=lambda v, key: _oos_sweep_coefficient(
            args, data, benchmark, total_return_benchmark,
            bench_commission, bench_slippage, bench_expense_ratio,
            args.impact_coefficient, borrow_cost=args.borrow_cost,
            funding_cost=args.funding_cost, **{key: v},
            survivorship=survivorship,
        ),
        latency_values=latencies,
        fill_rate_values=fill_rates,
        latency_artifact="out_of_sample_latency_sweep.json",
        fill_rate_artifact="out_of_sample_fill_rate_sweep.json",
        latency_header=["Latency", "Test Total Return", "Test Sharpe", "Deflated Sharpe"],
        fill_rate_header=["Fill Rate", "Test Total Return", "Test Sharpe", "Deflated Sharpe"],
        row_cells=lambda row, key: [
            str(row[key]),
            f"{row['test_total_return']:.4f}",
            "N/A" if row["test_sharpe"] is None else f"{row['test_sharpe']:.4f}",
            "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}",
        ],
    ):
        return 0

    commissions = [float(c) for c in (args.commissions or [args.commission])]
    slippages = [float(s) for s in (args.slippages or [args.slippage])]

    # Commission sensitivity sweep for out-of-sample validation: re-run the
    # validation pipeline for each commission rate and record degradation in
    # a single artifact. Varies commission while leaving impact/borrow/
    # funding/slippage at their single-run values.
    if len(commissions) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in commissions:
            row = _oos_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=args.borrow_cost,
                funding_cost=args.funding_cost, commission=cost,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "out_of_sample_commission_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"commissions": commissions, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nCommission sweep ({len(commissions)} rates) saved to: {sweep_path}")
        print("Commission | Test Total Return | Test Sharpe | minSR | note | Deflated Sharpe")
        print("-" * 74)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["test_sharpe"] is None else f"{row['test_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['commission']:>13.6f} | {row['test_total_return']:>16.4f} | "
                f"{sharpe_txt:>11} | {minSR_txt:>9} | {note:>16} | {dsr_txt:>15}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    # Slippage sensitivity sweep for out-of-sample validation: re-run the
    # validation pipeline for each slippage rate and record degradation in a
    # single artifact. Varies slippage while leaving impact/borrow/funding/
    # commission at their single-run values.
    if len(slippages) > 1:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        sweep_rows = []
        for cost in slippages:
            row = _oos_sweep_coefficient(
                args, data, benchmark, total_return_benchmark,
                bench_commission, bench_slippage, bench_expense_ratio,
                args.impact_coefficient, borrow_cost=args.borrow_cost,
                funding_cost=args.funding_cost, slippage=cost,
                survivorship=survivorship,
            )
            sweep_rows.append(row)
        sweep_path = output_dir / "out_of_sample_slippage_sweep.json"
        with open(sweep_path, "w") as f:
            json.dump(
                {"slippages": slippages, "results": sweep_rows},
                f,
                indent=2,
                default=str,
            )
        print(f"\nSlippage sweep ({len(slippages)} rates) saved to: {sweep_path}")
        print("Slippage | Test Total Return | Test Sharpe | minSR | note | Deflated Sharpe")
        print("-" * 74)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["test_sharpe"] is None else f"{row['test_sharpe']:.4f}"
            minSR_txt, note = _sweep_resolution_fields(row)
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['slippage']:>13.6f} | {row['test_total_return']:>16.4f} | "
                f"{sharpe_txt:>11} | {minSR_txt:>9} | {note:>16} | {dsr_txt:>15}"
            )
        _print_sweep_resolution_note(sweep_rows)
        return 0

    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    print(f"Running out-of-sample validation with {args.strategy}...")
    print(f"  Train/Val/Test split: {args.train_frac:.1%}/{args.val_frac:.1%}/{args.test_frac:.1%}")
    print(f"  Validation method: {args.validation_method}")
    print(f"  Selection criterion: {args.selection_criterion}")

    results = out_of_sample_validation(
        data=data,
        strategy_factory=strategy_factory,
        param_grid=param_grid,
        train_frac=args.train_frac,
        val_frac=args.val_frac,
        test_frac=args.test_frac,
        validation_method=args.validation_method,
        walk_forward_train_months=args.wf_train_months,
        walk_forward_test_months=args.wf_test_months,
        walk_forward_step_months=args.wf_step_months,
        cpcv_n_splits=args.cpcv_n_splits,
        cpcv_test_size=args.cpcv_test_size,
        cpcv_purge_size=args.cpcv_purge_size,
        cpcv_embargo_size=args.cpcv_embargo_size,
        selection_criterion=args.selection_criterion,
        initial_capital=args.initial_capital,
        commission=args.commission,
        slippage=args.slippage,
        impact_coefficient=args.impact_coefficient,
        adv_window=args.adv_window,
        borrow_cost=args.borrow_cost,
        funding_cost=args.funding_cost,
        latency=latency,
        fill_rate=fill_rate,
        apply_deflation=args.deflate,
        benchmark=benchmark,
        total_return_benchmark=total_return_benchmark,
        benchmark_commission=bench_commission,
        benchmark_slippage=bench_slippage,
        benchmark_expense_ratio=bench_expense_ratio,
        benchmark_cost_is_periodic=getattr(args, "benchmark_cost_is_periodic", False),
        panel_pricing=getattr(args, "panel_pricing", "net-exposure"),
        impact_aggregation=getattr(args, "impact_aggregation", "panel"),
    )

    if pit_results is not None:
        results["point_in_time_validation"] = pit_results

    # Print results
    split_info = results["train_val_test_split"]
    print(f"\nTrain/Validation/Test Split:")
    print(f"  Train: {split_info['train_start'].date()} to {split_info['train_end'].date()} ({split_info['train_size']} bars)")
    print(f"  Val:   {split_info['val_start'].date()} to {split_info['val_end'].date()} ({split_info['val_size']} bars)")
    print(f"  Test:  {split_info['test_start'].date()} to {split_info['test_end'].date()} ({split_info['test_size']} bars)")

    selected = results["selected_params"]
    if selected is None:
        error = results["summary"].get("error") or (
            "No valid parameters selected from validation phase."
        )
        print(f"No valid parameters selected from validation phase.\n{error}")
        # A grid key that did not change the strategy's behaviour makes the
        # selection over it a null experiment: say so next to the failure,
        # which is exactly where a null experiment is most likely to be
        # mistaken for "no good parameters were found".
        _print_inert_grid_warning(results["summary"].get("inert_grid_message"))
        # The failure is written out as an artifact too: a run that cannot
        # select parameters still has to leave a machine-readable record of
        # why, next to the split it used.
        failure_dir = Path(args.output)
        failure_dir.mkdir(parents=True, exist_ok=True)
        failure_path = failure_dir / "out_of_sample_summary.json"
        with open(failure_path, "w") as f:
            json.dump(
                {
                    "summary": results["summary"],
                    "train_val_test_split": results["train_val_test_split"],
                    "selected_params": None,
                    "validation_performance": None,
                    "test_performance": None,
                    "test_benchmark": None,
                    "config": {
                        "strategy": args.strategy,
                        "symbol": args.symbol,
                        "train_frac": args.train_frac,
                        "val_frac": args.val_frac,
                        "test_frac": args.test_frac,
                        "validation_method": args.validation_method,
                        "selection_criterion": args.selection_criterion,
                        "param_grid": param_grid,
                        "wf_train_months": args.wf_train_months,
                        "wf_test_months": args.wf_test_months,
                        "wf_step_months": args.wf_step_months,
                        "cpcv_n_splits": args.cpcv_n_splits,
                        "cpcv_test_size": args.cpcv_test_size,
                    },
                },
                f,
                indent=2,
                default=str,
            )
        print(f"Failure diagnosis saved to: {failure_path}")
        return 1

    print(f"\nSelected Parameters: {selected}")
    # A grid key that did not change the strategy's behaviour makes the
    # selection over it a null experiment: say so next to the selection, not
    # only in the summary JSON.
    _print_inert_grid_warning(results["summary"].get("inert_grid_message"))
    # A validation phase in which only some windows could select a parameter
    # says which windows were flat and why: the selected parameter was then
    # chosen from fewer windows than the validation phase had.
    _print_partial_selection_diagnosis(
        results["summary"].get("partial_selection_diagnosis")
    )
    # The selected parameter was chosen from the windows that could select
    # one, and if those windows barely traded, the selection rests on thin
    # evidence: the aggregate Sharpe hides how much of them the strategy
    # actually held a position.
    _print_thin_evidence_warning(
        results["summary"].get("thin_evidence_warning")
    )
    thin_evidence_failed = _thin_evidence_failure(
        results["summary"], min_position_fraction
    )
    if thin_evidence_failed is not None:
        print(f"REJECTED: {thin_evidence_failed['message']}")

    # The walk-forward window the validation phase actually ran with (it is
    # shortened when the requested window does not fit the training split).
    wf_window = results["summary"].get("walk_forward_window")
    if wf_window:
        effective = wf_window["effective"]
        requested = wf_window["requested"]
        adapted = " (adapted to the training split)" if wf_window.get("adapted") else ""
        print(
            f"  Validation-phase walk-forward window{adapted}: "
            f"train {effective['train_months']} / test {effective['test_months']} / "
            f"step {effective['step_months']} month(s) "
            f"(requested {requested['train_months']} / {requested['test_months']} / "
            f"{requested['step_months']}), "
            f"{wf_window.get('effective_periods')} period(s)"
        )

    val_perf = results["validation_performance"]
    print(f"\nValidation Performance:")
    print(f"  Total Return: {val_perf['val_total_return']:.2%}")
    print(f"  Sharpe Ratio: {val_perf['val_sharpe']:.4f}")

    test_perf = results["test_performance"]
    print(f"\nTest Performance (HELD-OUT, never used in selection):")
    print(f"  Total Return: {test_perf['test_total_return']:.2%}")
    print(f"  Sharpe Ratio: {test_perf['test_sharpe']:.4f}")
    # The held-out window's own diagnostic is printed next to the held-out
    # performance; the validation window's diagnostic and the aggregate over
    # both windows are in the summary JSON.
    _print_panel_pricing(results["summary"].get("panel_pricing"), indent="  ")
    _print_execution_warmup(results["summary"], indent="  ")
    _print_book_diagnostic(
        test_perf.get("book_diagnostic"),
        indent="  ",
        panel_pricing=results["summary"].get("panel_pricing"),
    )
    _print_capacity(
        {
            "capacity": test_perf.get("capacity"),
            "capacity_book": test_perf.get("capacity_book"),
            "capacity_book_trend": test_perf.get("capacity_book_trend"),
        },
        indent="  ",
    )

    summary = results["summary"]
    dsr = summary.get("deflated_sharpe")
    if dsr is not None:
        print(
            f"\nDeflated Sharpe Ratio (test): {dsr['deflated_sharpe_ratio']:.4f} "
            f"(p-value {dsr['p_value']:.4f}, expected max Sharpe "
            f"{dsr['expected_max_sharpe']:.4f}, {dsr['n_trials']} trials)"
        )
    # The aggregate Deflated Alpha Ratio: the statistic the alpha resolution
    # below belongs to.
    _print_deflated_alpha(
        summary.get("deflated_alpha"),
        label="Deflated Alpha Ratio (test)",
    )
    # What the held-out significance tests could have detected at the sample
    # size actually available: the smallest confirmable effect. A
    # measurement, not a correction -- it changes no verdict and no reported
    # number.
    _print_test_resolution(summary.get("test_resolution"))

    if results["test_benchmark"]:
        print(
            f"\nTest Benchmark Comparison:"
        )
        if isinstance(results["test_benchmark"], list):
            # Multiple benchmarks
            for i, bench_result in enumerate(results["test_benchmark"]):
                if bench_result is not None:
                    print(
                        f"  Benchmark {i+1}:"
                    )
                    print(
                        f"    Correlation: {bench_result.get('correlation_with_benchmark', 'N/A'):.4f}"
                    )
                    print(
                        f"    Alpha (annualized): {bench_result.get('alpha', 'N/A'):.2%}"
                    )
                    print(
                        f"    Beta: {bench_result.get('beta', 'N/A'):.4f}"
                    )
                    # Show both original and corrected p-values if available
                    if 'alpha_pvalue_original' in bench_result:
                        print(
                            f"    Alpha p-value (original): {bench_result['alpha_pvalue_original'] if bench_result['alpha_pvalue_original'] is None else f'{bench_result['alpha_pvalue_original']:.4f}'}"
                        )
                        print(
                            f"    Alpha p-value (corrected): {bench_result['alpha_pvalue'] if bench_result['alpha_pvalue'] is None else f'{bench_result['alpha_pvalue']:.4f}'}"
                        )
                    else:
                        pval = bench_result.get("alpha_pvalue")
                        print(
                            f"    Alpha p-value: {pval if pval is None else f'{pval:.4f}'}"
                        )
                    rs = bench_result.get("r_squared")
                    print(
                        f"    R-squared: {rs if rs is None else f'{rs:.4f}'}"
                    )
                else:
                    print(f"  Benchmark {i+1}: Failed to compute")
        else:
            # Single benchmark (backward compatibility)
            print(
                f"  Correlation: {results['test_benchmark'].get('correlation_with_benchmark', 'N/A'):.4f}"
            )
            print(
                f"  Alpha (annualized): {results['test_benchmark'].get('alpha', 'N/A'):.2%}"
            )
            print(
                f"  Beta: {results['test_benchmark'].get('beta', 'N/A'):.4f}"
            )
            pval = results["test_benchmark"].get("alpha_pvalue")
            print(
                f"  Alpha p-value: {pval if pval is None else f'{pval:.4f}'}"
            )
            rs = results["test_benchmark"].get("r_squared")
            print(
                f"  R-squared: {rs if rs is None else f'{rs:.4f}'}"
            )

    # Save results
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save summary as JSON
    summary_path = output_dir / "out_of_sample_summary.json"
    summary_data = {
        "summary": results["summary"],
        "train_val_test_split": results["train_val_test_split"],
        "selected_params": results["selected_params"],
        "validation_performance": results["validation_performance"],
        "test_performance": {
            "test_total_return": results["test_performance"]["test_total_return"],
            "test_sharpe": results["test_performance"]["test_sharpe"],
            "test_volatility": results["test_performance"]["test_volatility"],
            "test_n_observations": results["test_performance"]["test_n_observations"],
            "capacity": results["test_performance"].get("capacity"),
            # Panel book diagnostic for the held-out test window: the
            # per-asset book against the framework's net-exposure pricing
            # (measurement only).
            "book_diagnostic": results["test_performance"].get("book_diagnostic"),
        },
        "test_benchmark": results["test_benchmark"],
        "config": {
            "strategy": args.strategy,
            "symbol": args.symbol,
            "train_frac": args.train_frac,
            "val_frac": args.val_frac,
            "test_frac": args.test_frac,
            "validation_method": args.validation_method,
            "selection_criterion": args.selection_criterion,
            "commission": args.commission,
            "slippage": args.slippage,
            "impact_coefficient": args.impact_coefficient,
            "adv_window": args.adv_window,
            "borrow_cost": args.borrow_cost,
            "funding_cost": args.funding_cost,
            "latency": latency,
            "fill_rate": fill_rate,
            "deflate": bool(getattr(args, "deflate", False)),
            "param_grid": param_grid,
            "point_in_time_validation": pit_results,
            "bias_controls_engaged": pit_results is not None,
            "benchmark": getattr(args, "benchmark", None),
            "total_return_benchmark": total_return_benchmark,
            "benchmark_commission": bench_commission,
            "benchmark_slippage": bench_slippage,
            "benchmark_expense_ratio": bench_expense_ratio,
            "benchmark_cost_is_periodic": getattr(args, "benchmark_cost_is_periodic", False),
            # Validation method specific config
            "wf_train_months": args.wf_train_months,
            "wf_test_months": args.wf_test_months,
            "wf_step_months": args.wf_step_months,
            "cpcv_n_splits": args.cpcv_n_splits,
            "cpcv_test_size": args.cpcv_test_size,
            "cpcv_purge_size": args.cpcv_purge_size,
            "cpcv_embargo_size": args.cpcv_embargo_size,
            "multi_symbol": getattr(args, "multi_symbol", False),
            # The execution warmup this run applied, so the saved artifact
            # records how many leading bars of every window are not tradable.
            **execution_warmup_metadata(WARMUP_CONVENTION_WALK_FORWARD, latency),
        },
    }
    if pit_results is not None:
        summary_data["point_in_time_validation"] = pit_results
    summary_data["bias_controls_engaged"] = bool(pit_results is not None or survivorship is not None)
    if survivorship is not None:
        summary_data["survivorship_bias"] = survivorship
    if benchmark_provenance is not None:
        # benchmark_provenance is a single DataProvenance when one benchmark
        # was supplied, or a list of them when multiple benchmarks were
        # supplied (multi-benchmark alpha multiple-testing correction).
        if isinstance(benchmark_provenance, list):
            summary_data["benchmark_provenance"] = [
                prov.to_dict() for prov in benchmark_provenance
            ]
        else:
            summary_data["benchmark_provenance"] = benchmark_provenance.to_dict()
    with open(summary_path, "w") as f:
        json.dump(summary_data, f, indent=2, default=str)
    print(f"\nOut-of-sample summary saved to: {summary_path}")

    # Optional survivorship-bias artifact (multi-symbol panels). Mirrors the
    # run_backtest CLI so panel runs are auditable on the same file name.
    if survivorship is not None:
        surv_path = Path(args.output) / "survivorship_bias.json"
        with open(surv_path, "w") as f:
            json.dump(survivorship, f, indent=2, default=str)
        print(f"Survivorship bias report saved to: {surv_path}")

    # Generate full report if test returns available
    if len(results["test_performance"]["test_returns"]) > 0:
        equity = (1 + results["test_performance"]["test_returns"]).cumprod() * args.initial_capital
        report_results = {
            "equity_curve": equity,
            "returns": results["test_performance"]["test_returns"],
            "config": {
                "initial_capital": args.initial_capital,
                "commission": args.commission,
                "slippage": args.slippage,
                "strategy": args.strategy,
                "symbol": args.symbol,
                "total_return_benchmark": total_return_benchmark,
                "benchmark_commission": bench_commission,
                "benchmark_slippage": bench_slippage,
                "benchmark_expense_ratio": bench_expense_ratio,
                "benchmark_cost_is_periodic": getattr(args, "benchmark_cost_is_periodic", False),
            },
        }
        if results["test_benchmark"] is not None:
            # The report/tear sheet path is single-benchmark by design, so
            # use the first benchmark when multiple were supplied. The
            # multi-benchmark comparison (with Deflated Alpha correction)
            # is already surfaced in the printed summary and the JSON.
            bench_for_report = benchmark
            if isinstance(benchmark, list) and len(benchmark) > 0:
                bench_for_report = benchmark[0]
            bench_returns = _compute_benchmark_returns(
                bench_for_report,
                results["test_performance"]["test_returns"],
                total_return_benchmark,
            )
            if bench_returns is not None:
                report_results["benchmark"] = bench_returns
            # Thread benchmark provenance through the report results so the
            # tear-sheet summary is traceable to the exact benchmark file.
            # The report path renders a single benchmark (the first when
            # multiple were supplied), so thread the provenance of that same
            # first benchmark when a list was captured.
            if benchmark_provenance is not None:
                if isinstance(benchmark_provenance, list) and benchmark_provenance:
                    report_results["benchmark_provenance"] = benchmark_provenance[0]
                else:
                    report_results["benchmark_provenance"] = benchmark_provenance
        if pit_results is not None:
            report_results["point_in_time_validation"] = pit_results
        if survivorship is not None:
            report_results["survivorship_bias"] = survivorship
        report_results["bias_controls_engaged"] = bool(pit_results is not None or survivorship is not None)
        metrics = calculate_metrics(report_results)
        if dsr is not None:
            metrics["deflated_sharpe"] = dsr
        generate_report(metrics, args.output, symbol=args.symbol, strategy_name=f"{args.strategy}_out_of_sample")
        generate_tear_sheet(
            report_results, metrics, args.output,
            symbol=args.symbol,
            strategy_name=f"{args.strategy}_out_of_sample",
            analysis_results={"out_of_sample": results},
        )
        print(f"Detailed report saved to: {args.output}/")

    return 1 if thin_evidence_failed else 0


def main():
    parser = argparse.ArgumentParser(description="Walk-forward analysis and validation tools")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Common arguments
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--data", type=str, required=True, help="Path to data file (CSV/Parquet)")
    common_parser.add_argument("--strategy", type=str, default="sma_crossover", help="Strategy type")
    common_parser.add_argument("--symbol", type=str, default="SPY", help="Symbol to analyze")
    common_parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    common_parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    common_parser.add_argument("--commission", type=float, default=0.0002, help="Commission per trade (as decimal)")
    common_parser.add_argument("--commissions", type=float, nargs="+", default=None, help="List of commissions to sweep (overrides --commission)")
    common_parser.add_argument("--slippage", type=float, default=0.0001, help="Slippage per trade (as decimal)")
    common_parser.add_argument("--slippages", type=float, nargs="+", default=None, help="List of slippages to sweep (overrides --slippage)")
    common_parser.add_argument("--impact-coefficient", type=float, default=0.0, help="Market impact coefficient (position_notional/ADV * coefficient). 0 to disable.")
    common_parser.add_argument("--impact-aggregation", type=str, default="panel", choices=["panel", "notional-weighted"], help="Market-impact aggregation convention. 'panel' (default) charges the equal-weighted mean of the per-asset impact rates; 'notional-weighted' charges the dollar-consistent aggregation. Default unchanged so no published number moves.")
    common_parser.add_argument("--adv-window", type=int, default=20, help="Rolling window for Average Daily Volume calculation")
    common_parser.add_argument("--borrow-cost", type=float, default=0.0, help="Annual borrow cost rate for short positions (as decimal, e.g., 0.03 = 3%% per year)")
    common_parser.add_argument("--funding-cost", type=float, default=0.0, help="Annual funding cost rate for leveraged positions (as decimal, e.g., 0.02 = 2%% per year)")
    common_parser.add_argument("--output", type=str, default="results", help="Output directory")
    common_parser.add_argument("--param-grid", type=str, required=True, help="Parameter grid as JSON string")
    common_parser.add_argument("--validate-point-in-time", action="store_true", default=True, help="Run point-in-time validation on the loaded data (temporal ordering, duplicate timestamps, stale-data warnings); enabled by default, use --no-validate-point-in-time to disable")
    common_parser.add_argument("--no-validate-point-in-time", action="store_false", dest="validate_point_in_time", help="Disable point-in-time validation (enabled by default)")
    common_parser.add_argument("--point-in-time-strict", action="store_true", help="Abort when point-in-time validation finds violations (default: warn only)")
    common_parser.add_argument("--benchmark", type=str, nargs="+", default=None, help="Path to benchmark OHLCV file(s) (e.g. SPY QQQ) for buy-and-hold baseline comparison (alpha/beta, correlation)")
    common_parser.add_argument("--total-return-benchmark", action="store_true", help="Compute benchmark returns using total return (dividends + price) when dividend/adj_close data is available, instead of price-only returns (applies to all benchmarks)")
    common_parser.add_argument("--benchmark-commission", type=float, default=None, help="Commission per trade for benchmark (as decimal). Defaults to strategy commission if not specified (applies to all benchmarks).")
    common_parser.add_argument("--benchmark-slippage", type=float, default=None, help="Slippage per trade for benchmark (as decimal). Defaults to strategy slippage if not specified (applies to all benchmarks).")
    common_parser.add_argument("--benchmark-expense-ratio", type=float, default=None, help="Annual expense ratio for benchmark (as decimal, e.g., 0.005 for 0.5 percent). Defaults to 0 (applies to all benchmarks).")
    common_parser.add_argument("--benchmark-cost-is-periodic", action="store_true", help="If set, apply benchmark trading costs (commission+slippage) as periodic deductions each period instead of as a round-trip cost on total return (applies to all benchmarks).")
    common_parser.add_argument("--adjust-splits", action="store_true", help="Adjust prices for stock splits using the splits column if present.")
    common_parser.add_argument("--multi-symbol", action="store_true", help="Load every symbol in a multi-symbol file (with a 'symbol' or 'ticker' column) as a panel, run survivorship-bias detection, and backtest a panel. Requires a panel strategy such as cross_sectional_momentum or dual_momentum.")
    common_parser.add_argument("--seed", type=int, default=None, help="Seed for the Monte Carlo random number generator. A fixed default seed is used when unset, so repeated runs (and cost sweeps) are reproducible; set any value to override.")
    common_parser.add_argument("--latency", type=int, default=0, help="Execution latency in periods (0 = no delay, 1 = one period delay). Delays position execution by latency periods after signal generation.")
    common_parser.add_argument("--fill-rate", type=float, default=1.0, help="Position-scale limit (0 < r <= 1): the achieved position is fill_rate times the target position on every bar, so all position-change-based costs scale proportionally. It is a position-size (leverage) lever, not a partial-fill execution model. Default 1.0 (full fill, backward compatible).")
    common_parser.add_argument("--fill-rates", type=float, nargs="+", default=None, help="List of fill rates to sweep (overrides --fill-rate).")
    common_parser.add_argument("--latencies", type=int, nargs="+", default=None, help="List of execution latencies (in periods) to sweep (overrides --latency). Delays position execution by each latency after signal generation.")
    common_parser.add_argument("--min-position-fraction", type=float, default=None, help="Reject a run whose verdict rests on windows the strategy held a position for less than this fraction of each window's executable bars (after warmup). Opt-in: unset means the run is never rejected on this basis.")
    common_parser.add_argument(
        "--panel-pricing",
        type=str,
        default="net-exposure",
        choices=["net-exposure", "book"],
        help=(
            "How a multi-asset panel is priced and costed. 'net-exposure' "
            "(default) prices the portfolio as net_exposure x mean(asset "
            "returns) -- the convention every published number was produced "
            "under -- and charges the costs on the net exposure. 'book' "
            "prices the true per-asset book return sum_i w_i r_i, which makes "
            "a market-neutral book backtestable, and charges the costs on the "
            "book itself: commission and slippage on its gross turnover, "
            "borrow on its short legs, funding on its gross exposure, and "
            "market impact per asset against that asset's own ADV."
        ),
    )

    # Walk-forward analysis
    wf_parser = subparsers.add_parser("walk-forward", parents=[common_parser], help="Run walk-forward analysis")
    wf_parser.add_argument("--train-months", type=int, default=12, help="Training window size in months")
    wf_parser.add_argument("--test-months", type=int, default=3, help="Testing window size in months")
    wf_parser.add_argument("--step-months", type=int, default=3, help="Step size between iterations in months")
    wf_parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    wf_parser.add_argument("--deflate", action="store_true", help="Compute Deflated Sharpe Ratio (multiple-testing correction) on the parameter search and OOS results")
    wf_parser.add_argument("--impact-coefficients", type=float, nargs="+", default=None, help="Sweep over multiple market impact coefficients for capacity/impact sensitivity; overrides --impact-coefficient when given (e.g. --impact-coefficients 0 1 2 5).")
    wf_parser.add_argument("--borrow-costs", type=float, nargs="+", default=None, help="Sweep over multiple annual borrow costs for short positions; overrides --borrow-cost when given (e.g. --borrow-costs 0 0.01 0.03).")
    wf_parser.add_argument("--funding-costs", type=float, nargs="+", default=None, help="Sweep over multiple annual funding costs for leveraged positions; overrides --funding-cost when given (e.g. --funding-costs 0 0.01 0.02).")
    wf_parser.set_defaults(func=run_walk_forward)

    # Parameter optimization
    opt_parser = subparsers.add_parser("optimize", parents=[common_parser], help="Run parameter optimization")
    opt_parser.add_argument("--top-n", type=int, default=10, help="Number of top results to display")
    opt_parser.add_argument("--deflate", action="store_true", help="Compute Deflated Sharpe Ratio (multiple-testing correction) for every parameter combination")
    opt_parser.add_argument("--impact-coefficients", type=float, nargs="+", default=None, help="Sweep over multiple market impact coefficients for capacity/impact sensitivity; overrides --impact-coefficient when given (e.g. --impact-coefficients 0 1 2 5).")
    opt_parser.add_argument("--borrow-costs", type=float, nargs="+", default=None, help="Sweep over multiple annual borrow costs for short positions; overrides --borrow-cost when given (e.g. --borrow-costs 0 0.01 0.03).")
    opt_parser.add_argument("--funding-costs", type=float, nargs="+", default=None, help="Sweep over multiple annual funding costs for leveraged positions; overrides --funding-cost when given (e.g. --funding-costs 0 0.01 0.02).")
    opt_parser.set_defaults(func=run_parameter_optimization)

    # Monte Carlo simulation
    mc_parser = subparsers.add_parser("monte-carlo", parents=[common_parser], help="Run Monte Carlo simulation")
    mc_parser.add_argument("--n-simulations", type=int, default=2000, help="Number of simulations")
    mc_parser.add_argument("--confidence-levels", type=float, nargs="+", default=[0.90, 0.95, 0.99], help="Confidence levels")
    mc_parser.add_argument("--block-size", type=lambda x: x if x == "auto" else int(x), help="Block size for block bootstrap (int or 'auto' for automatic selection)")
    mc_parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    mc_parser.add_argument("--n-trials", type=int, default=None, help="Number of development trials (parameter configurations) tested; when set, report the Deflated Sharpe Ratio (multiple-testing correction) for the base backtest Sharpe. When a --param-grid is searched, the effective count is the number of grid combinations actually evaluated; otherwise --n-trials is used.")
    mc_parser.add_argument("--impact-coefficients", type=float, nargs="+", default=None, help="Sweep over multiple market impact coefficients for capacity/impact sensitivity; overrides --impact-coefficient when given (e.g. --impact-coefficients 0 1 2 5).")
    mc_parser.add_argument("--borrow-costs", type=float, nargs="+", default=None, help="Sweep over multiple annual borrow costs for short positions; overrides --borrow-cost when given (e.g. --borrow-costs 0 0.01 0.03).")
    mc_parser.add_argument("--funding-costs", type=float, nargs="+", default=None, help="Sweep over multiple annual funding costs for leveraged positions; overrides --funding-cost when given (e.g. --funding-costs 0 0.01 0.02).")
    mc_parser.set_defaults(func=run_monte_carlo)

    # CPCV analysis
    cpcv_parser = subparsers.add_parser("cpcv", parents=[common_parser], help="Run Combinatorially Purged Cross-Validation")
    cpcv_parser.add_argument("--n-splits", type=int, default=10, help="Number of sequential groups (folds)")
    cpcv_parser.add_argument("--test-size", type=float, default=0.1, help="Fraction of each group to use as test set")
    cpcv_parser.add_argument("--purge-size", type=float, default=0.0, help="Fraction of observations to purge from training around test set")
    cpcv_parser.add_argument("--embargo-size", type=float, default=0.0, help="Fraction of observations to embargo after test set")
    cpcv_parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    cpcv_parser.add_argument("--deflate", action="store_true", help="Compute Deflated Sharpe Ratio (multiple-testing correction) on the fold searches and OOS results")
    cpcv_parser.add_argument("--impact-coefficients", type=float, nargs="+", default=None, help="Sweep over multiple market impact coefficients for capacity/impact sensitivity; overrides --impact-coefficient when given (e.g. --impact-coefficients 0 1 2 5).")
    cpcv_parser.add_argument("--borrow-costs", type=float, nargs="+", default=None, help="Sweep over multiple annual borrow costs for short positions; overrides --borrow-cost when given (e.g. --borrow-costs 0 0.01 0.03).")
    cpcv_parser.add_argument("--funding-costs", type=float, nargs="+", default=None, help="Sweep over multiple annual funding costs for leveraged positions; overrides --funding-cost when given (e.g. --funding-costs 0 0.01 0.02).")
    cpcv_parser.set_defaults(func=run_cpcv)

    # Out-of-sample validation
    oos_parser = subparsers.add_parser("out-of-sample", parents=[common_parser], help="Run rigorous out-of-sample validation with train/validation/test split")
    oos_parser.add_argument("--train-frac", type=float, default=0.6, help="Fraction of data for training (default 0.6)")
    oos_parser.add_argument("--val-frac", type=float, default=0.2, help="Fraction of data for validation (default 0.2)")
    oos_parser.add_argument("--test-frac", type=float, default=0.2, help="Fraction of data for testing (default 0.2)")
    oos_parser.add_argument("--validation-method", type=str, choices=["walk_forward", "cpcv"], default="walk_forward", help="Method for parameter selection on training data")
    oos_parser.add_argument("--selection-criterion", type=str, choices=["best_oos_sharpe", "most_stable", "best_avg_sharpe"], default="best_oos_sharpe", help="Criterion for selecting final parameters from validation results")
    oos_parser.add_argument("--initial-capital", type=float, default=100000, help="Initial capital")
    oos_parser.add_argument("--deflate", action="store_true", help="Compute Deflated Sharpe Ratio (multiple-testing correction) on the test results")
    oos_parser.add_argument("--impact-coefficients", type=float, nargs="+", default=None, help="Sweep over multiple market impact coefficients for capacity/impact sensitivity; overrides --impact-coefficient when given (e.g. --impact-coefficients 0 1 2 5).")
    oos_parser.add_argument("--borrow-costs", type=float, nargs="+", default=None, help="Sweep over multiple annual borrow costs for short positions; overrides --borrow-cost when given (e.g. --borrow-costs 0 0.01 0.03).")
    oos_parser.add_argument("--funding-costs", type=float, nargs="+", default=None, help="Sweep over multiple annual funding costs for leveraged positions; overrides --funding-cost when given (e.g. --funding-costs 0 0.01 0.02).")
    # Walk-forward specific args for validation phase
    oos_parser.add_argument("--wf-train-months", type=int, default=12, help="Training window size in months for walk-forward validation")
    oos_parser.add_argument("--wf-test-months", type=int, default=3, help="Testing window size in months for walk-forward validation")
    oos_parser.add_argument("--wf-step-months", type=int, default=3, help="Step size between walk-forward iterations")
    # CPCV specific args for validation phase
    oos_parser.add_argument("--cpcv-n-splits", type=int, default=10, help="Number of sequential groups for CPCV validation")
    oos_parser.add_argument("--cpcv-test-size", type=float, default=0.1, help="Fraction of each group to use as test set in CPCV")
    oos_parser.add_argument("--cpcv-purge-size", type=float, default=0.0, help="Fraction of observations to purge from training around test")
    oos_parser.add_argument("--cpcv-embargo-size", type=float, default=0.0, help="Fraction of observations to embargo after test set")
    oos_parser.set_defaults(func=run_out_of_sample_validation)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
