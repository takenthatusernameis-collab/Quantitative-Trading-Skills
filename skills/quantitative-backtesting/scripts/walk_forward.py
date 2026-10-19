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
    aggregate_book_diagnostics,
    book_is_active,
    book_return_series,
    build_market_model,
    compute_book_diagnostic,
    market_impact_cost,
    resolve_panel_pricing,
    strategy_target_weights,
)
from reporting import generate_tear_sheet
from monte_carlo import monte_carlo_simulation


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
        print(" | ".join(latency_header))
        print("-" * len(" | ".join(latency_header)))
        for row in sweep_rows:
            print(" | ".join(row_cells(row, "latency")))
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
        print(" | ".join(fill_rate_header))
        print("-" * len(" | ".join(fill_rate_header)))
        for row in sweep_rows:
            print(" | ".join(row_cells(row, "fill_rate")))
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
        fill_rate: Fraction of each targeted position change that is filled,
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

        for combo in product(*param_values):
            params = dict(zip(param_names, combo))

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
                if not _window_takes_position(
                    strategy,
                    test_signals,
                    test_data,
                    panel_pricing=panel_pricing,
                    latency=latency,
                    fill_rate=fill_rate,
                    book_weights=test_book_weights,
                ):
                    continue

                # Calculate returns for this parameter set
                test_returns = _calculate_strategy_returns(
                    test_data, test_signals, commission, slippage,
                    impact_coefficient, adv_window, borrow_cost, funding_cost,
                    latency, fill_rate,
                    initial_capital=initial_capital,
                    panel_pricing=panel_pricing,
                    book_weights=test_book_weights,
                )

                # Evaluate on training set
                train_returns = _calculate_strategy_returns(
                    train_data, train_signals, commission, slippage,
                    impact_coefficient, adv_window, borrow_cost, funding_cost,
                    latency, fill_rate,
                    initial_capital=initial_capital,
                    panel_pricing=panel_pricing,
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
                else:
                    sharpe = -np.inf

                if apply_deflation and np.isfinite(sharpe):
                    period_trial_sharpes.append(float(sharpe))

                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_params = params
                    best_test_returns = test_returns
                    if apply_deflation:
                        best_train_returns = train_returns

            except Exception:
                continue

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
        fill_rate: Fraction of each targeted position change that is filled,
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
    diagnostics["overfitting_risk"] = "low"
    if len(valid_params) > 0:
        # High parameter variation across periods suggests overfitting
        avg_stability = np.mean([
            v["stability_ratio"] for v in diagnostics.get("param_stability", {}).values()
        ]) if diagnostics.get("param_stability") else 1.0
        if avg_stability < 0.3:
            diagnostics["overfitting_risk"] = "high"
        elif avg_stability < 0.5:
            diagnostics["overfitting_risk"] = "medium"

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
    """
    if panel_pricing == "book":
        if book_weights is None:
            book_weights = strategy_target_weights(strategy, data)
        if book_weights is not None:
            market = build_market_model(data)
            if market["is_panel"]:
                return book_is_active(
                    book_weights,
                    market,
                    lag=1 + latency,
                    fill_rate=fill_rate,
                )
    return signals_active(signals)


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
        fill_rate: Fraction of each targeted position change that is filled,
            in (0, 1]. Scales achieved positions and all position-change-based
            costs (commission, slippage, impact) and borrow/funding exposure.
            Default 1.0 (full fill) is bitwise identical to no fill modeling.
        initial_capital: Starting portfolio value used to scale the position
            notional for market-impact calculation. The notional at risk is
            |position_change| * equity, where equity is approximated by
            initial_capital * cumprod(1 + raw_returns). Default 100000.
        panel_pricing: "net-exposure" (the default) prices the portfolio as
            `net_exposure x mean(asset returns)`; "book" prices the true
            per-asset book return `sum_i w_i r_i`. The cost model is
            identical in both modes (it still sees |d net exposure|).
        book_weights: the per-asset target book of the strategy on `data`
            (rows = dates, columns = symbols). Required for the "book"
            pricing mode; ignored otherwise.
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

    positions = signals.shift(1 + latency) * fill_rate  # Trade at next period's open, delayed by execution latency; partial fills scale achieved exposure

    # Transaction costs: apply on position changes
    position_changes = positions.diff().abs()
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
    )
    if market_impact is not None:
        costs = costs + market_impact

    # Borrow and funding costs are annualized rates applied per period.
    # The per-period rate divides by the number of periods per year inferred
    # from the data's index (e.g. 252 for business-daily, 365 for
    # calendar-daily, 52 for weekly, 12 for monthly), matching the
    # annualization used for the strategy's own return metrics. Falls back
    # to 252 when the frequency cannot be inferred.
    ann_factor = _annualization_factor(raw_returns.index)

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
    # The cost series is identical in both modes (commission, slippage,
    # impact, borrow and funding all come from the net-exposure position
    # series), so the two modes differ exactly by the exposure-convention
    # gap and nothing else. When the "book" mode is requested but no book is
    # available, the net-exposure pricing is used.
    book_returns = None
    if panel_pricing == "book" and book_weights is not None:
        book_returns = book_return_series(
            book_weights,
            market,
            lag=1 + latency,
            fill_rate=fill_rate,
        )
    if book_returns is not None:
        strategy_returns = book_returns - costs
    else:
        strategy_returns = positions * raw_returns - costs
    return strategy_returns.dropna()


def _capacity_trend_from_series(
    capacity_series: pd.Series,
    point_in_time_capacity: float,
) -> Dict[str, Any]:
    """Summarise the distribution of per-period capacity readings.

    The point-in-time ``estimated_capacity`` is a *single* reading: the ADV
    of the last bar of the window. A drying-up liquidity regime *inside* the
    window is invisible to it. This helper turns the per-period capacity
    series into the distribution that the single reading hides:

        min_capacity      worst liquidity point inside the window
        median_capacity   typical liquidity point inside the window
        max_capacity      best liquidity point inside the window
        last_capacity     the point-in-time reading (= estimated_capacity)

    The two ratios express how the extremes relate to the typical reading:

        min_to_median_ratio  worst / typical  (<= 1; a mid-window squeeze)
        last_to_median_ratio end-of-window / typical (<= 1 when liquidity
                              dried up towards the end of the window)

    Both ratios are relative to the median, so they are comparable across
    windows with different absolute capacity levels.
    """
    series = pd.Series(capacity_series, dtype=float)
    valid = series.replace([np.inf, -np.inf], np.nan).dropna()
    valid = valid[np.isfinite(valid)]

    last_capacity = float(point_in_time_capacity)

    if len(valid) == 0:
        return {
            "n_periods": 0,
            "min_capacity": None,
            "median_capacity": None,
            "max_capacity": None,
            "last_capacity": last_capacity,
            "min_to_median_ratio": None,
            "last_to_median_ratio": None,
        }

    min_capacity = float(valid.min())
    median_capacity = float(valid.median())
    max_capacity = float(valid.max())

    return {
        "n_periods": int(len(valid)),
        "min_capacity": min_capacity,
        "median_capacity": median_capacity,
        "max_capacity": max_capacity,
        "last_capacity": last_capacity,
        "min_to_median_ratio": (
            float(min_capacity / median_capacity) if median_capacity > 0 else None
        ),
        "last_to_median_ratio": (
            float(last_capacity / median_capacity) if median_capacity > 0 else None
        ),
    }


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


def _window_book_diagnostic(
    strategy_factory: Callable,
    best_params: Optional[Dict[str, Any]],
    window_data,
    framework_returns,
    latency: int = 0,
    fill_rate: float = 1.0,
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
        fill_rate: Fraction of each targeted position change that is filled,
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

        for combo in product(*param_values):
            params = dict(zip(param_names, combo))

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
                if not _window_takes_position(
                    strategy,
                    test_signals,
                    test_data,
                    panel_pricing=panel_pricing,
                    latency=latency,
                    fill_rate=fill_rate,
                    book_weights=test_book_weights,
                ):
                    continue

                # Calculate returns for this parameter set
                test_returns = _calculate_strategy_returns(
                    test_data, test_signals, commission, slippage,
                    impact_coefficient, adv_window, borrow_cost, funding_cost,
                    latency, fill_rate,
                    initial_capital=initial_capital,
                    panel_pricing=panel_pricing,
                    book_weights=test_book_weights,
                )

                # Evaluate on training set
                train_returns = _calculate_strategy_returns(
                    train_data, train_signals, commission, slippage,
                    impact_coefficient, adv_window, borrow_cost, funding_cost,
                    latency, fill_rate,
                    initial_capital=initial_capital,
                    panel_pricing=panel_pricing,
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
                else:
                    sharpe = -np.inf

                if apply_deflation and np.isfinite(sharpe):
                    fold_trial_sharpes.append(float(sharpe))

                if sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_params = params
                    best_test_returns = test_returns
                    if apply_deflation:
                        best_train_returns = train_returns

            except Exception:
                continue

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
    # Panel book diagnostic aggregated over the out-of-sample folds (see
    # the walk-forward summary for the same key). None when no fold
    # produced a diagnostic.
    summary["book_diagnostic"] = aggregate_book_diagnostics(
        [f.get("book_diagnostic") for f in folds]
    )
    # The pricing convention that produced the reported out-of-sample P&L.
    summary["panel_pricing"] = panel_pricing

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
        summary["overfitting_risk"] = "high"

    return summary


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
        fill_rate: Fraction of each targeted position change that is filled,
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
    if validation_method == "walk_forward":
        validation_results = walk_forward_analysis(
            data=train_data,
            strategy_factory=strategy_factory,
            param_grid=param_grid,
            train_months=walk_forward_train_months,
            test_months=walk_forward_test_months,
            step_months=walk_forward_step_months,
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
    # Phase 2: SELECTION - Select best parameters based on criterion
    selected_params = _select_parameters(
        validation_results=validation_results,
        validation_method=validation_method,
        criterion=selection_criterion,
    )
    if selected_params is None:
        return {
            "train_val_test_split": split_info,
            "validation_results": validation_results,
            "selected_params": None,
            "validation_performance": None,
            "test_performance": None,
            "test_benchmark": None,
            "summary": {
                "error": "No valid parameters found in validation phase",
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

    validation_performance = {
        "selected_params": selected_params,
        "val_total_return": val_total_return,
        "val_sharpe": val_sharpe,
        "val_volatility": float(val_returns.std() * np.sqrt(ann_factor)) if len(val_returns) > 1 else 0.0,
        "val_n_periods": len(val_returns),
        "capacity": val_capacity_point,
        "capacity_trend": val_capacity_trend,
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

    test_performance = {
     "test_total_return": test_total_return,
         "test_sharpe": test_sharpe,
         "test_volatility": float(test_returns.std() * np.sqrt(ann_factor_test)) if len(test_returns) > 1 else 0.0,
         "test_n_periods": len(test_returns),
         "test_returns": test_returns,
         "capacity": test_capacity_point,
         "capacity_trend": test_capacity_trend,
         # Panel book diagnostic for the held-out test window. Measurement
         # only -- the reported test performance is unchanged.
         "book_diagnostic": _window_book_diagnostic(
             strategy_factory,
             selected_params,
             test_data,
             test_returns,
             latency=latency,
             fill_rate=fill_rate,
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
        # Capacity trends for the same two windows: the distribution of the
        # per-period capacity readings inside each window, so a liquidity
        # squeeze *within* a window is visible too (the point-in-time
        # `*_capacity` keys only read the last bar of the window).
        "validation_capacity_trend": val_capacity_trend,
        "test_capacity_trend": test_capacity_trend,
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
    elif apply_deflation and len(test_returns) > 1:
        summary["deflated_sharpe"] = deflated_sharpe_ratio(
            sharpe_ratio=test_sharpe,
            returns=test_returns,
            n_trials=1,
            trial_sharpes=None,
        )

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
        print("Impact coefficient | Total OOS Return | OOS Sharpe | Avg Param Stability | Overfitting Risk | Deflated Sharpe | N Folds")
        print("-" * 112)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['impact_coefficient']:>17} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {row['avg_param_stability']:>17.4f} | "
                f"{str(row['overfitting_risk']):>17} | {dsr_txt:>14} | {row['n_folds']:>7}"
            )
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
        print("Borrow Cost | Total OOS Return | OOS Sharpe | Avg Param Stability | Overfitting Risk | Deflated Sharpe | N Folds")
        print("-" * 112)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['borrow_cost']:>13.4f} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {row['avg_param_stability']:>17.4f} | "
                f"{str(row['overfitting_risk']):>17} | {dsr_txt:>14} | {row['n_folds']:>7}"
            )
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
        print("Funding Cost | Total OOS Return | OOS Sharpe | Avg Param Stability | Overfitting Risk | Deflated Sharpe | N Folds")
        print("-" * 112)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['funding_cost']:>13.4f} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {row['avg_param_stability']:>17.4f} | "
                f"{str(row['overfitting_risk']):>17} | {dsr_txt:>14} | {row['n_folds']:>7}"
            )
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
            str(row["overfitting_risk"]),
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
        print("Commission | Total OOS Return | OOS Sharpe | Avg Param Stability | Overfitting Risk | Deflated Sharpe | N Folds")
        print("-" * 112)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['commission']:>13.6f} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {row['avg_param_stability']:>17.4f} | "
                f"{str(row['overfitting_risk']):>17} | {dsr_txt:>14} | {row['n_folds']:>7}"
            )
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
        print("Slippage | Total OOS Return | OOS Sharpe | Avg Param Stability | Overfitting Risk | Deflated Sharpe | N Folds")
        print("-" * 112)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['slippage']:>13.6f} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {row['avg_param_stability']:>17.4f} | "
                f"{str(row['overfitting_risk']):>17} | {dsr_txt:>14} | {row['n_folds']:>7}"
            )
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
    _total_oos_return = results["summary"]["total_oos_return"]
    print(
        f"Total OOS Return: {'N/A' if _total_oos_return is None else f'{_total_oos_return:.2%}'}"
    )
    print(f"OOS Sharpe Ratio: {results['summary'].get('oos_sharpe', 'N/A')}")
    print(f"Avg Parameter Stability: {results['summary'].get('avg_param_stability', 'N/A'):.2f}")
    print(f"Overfitting Risk: {results['summary'].get('overfitting_risk', 'N/A')}")
    _print_panel_pricing(results["summary"].get("panel_pricing"))
    _print_book_diagnostic(
        results["summary"].get("book_diagnostic"),
        panel_pricing=results["summary"].get("panel_pricing"),
    )

    dsr = results["summary"].get("deflated_sharpe")
    if dsr is not None:
        print(
            f"Deflated Sharpe Ratio: {dsr['deflated_sharpe_ratio']:.4f} "
            f"(p-value {dsr['p_value']:.4f}, expected max Sharpe "
            f"{dsr['expected_max_sharpe']:.4f}, {dsr['n_trials']} trials)"
        )

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

    return 0


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
            f"true per-asset book return sum_i w_i r_i)."
        )
    else:
        print(
            f"{indent}Panel pricing mode: net-exposure (the portfolio return "
            f"is net_exposure x mean(asset returns))."
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
    print(f"{indent}  Turnover charged by the model: {diag.get('framework_turnover', 0.0):.4f}")
    print(
        f"{indent}  Periods with a book:           "
        f"{diag.get('n_periods_with_book', 0)}/{diag.get('n_periods', 0)}"
    )
    gap_bps = diag.get("return_gap_bps")
    gap_total = diag.get("return_gap_total")
    if gap_bps is not None and gap_total is not None:
        print(
            f"{indent}  Return gap (framework - book): {gap_bps:.2f} bps/period "
            f"({gap_total:.2%} cumulative)"
        )
        print(
            f"{indent}  Book total return:            "
            f"{diag.get('book_total_return', 0.0):.2%} vs framework "
            f"{diag.get('framework_total_return_after_costs', 0.0):.2%}"
        )
    if panel_pricing == "book":
        print(
            f"{indent}  NOTE: the cost and impact model still sees |d net "
            f"exposure|, so the book's own rotation is under-charged "
            f"(compare gross turnover with the charged turnover above). "
            f"Book-mode results are an upper bound on what a fully costed "
            f"book would earn."
        )


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
        print("Impact coefficient | Total OOS Return | OOS Sharpe | Deflated Sharpe | N Periods")
        print("-" * 90)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['impact_coefficient']:>17} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {dsr_txt:>15} | {row['n_periods']:>9}"
            )
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
        print("Borrow Cost | Total OOS Return | OOS Sharpe | Deflated Sharpe | N Periods")
        print("-" * 90)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['borrow_cost']:>13.4f} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {dsr_txt:>15} | {row['n_periods']:>9}"
            )
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
        print("Funding Cost | Total OOS Return | OOS Sharpe | Deflated Sharpe | N Periods")
        print("-" * 90)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['funding_cost']:>13.4f} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {dsr_txt:>15} | {row['n_periods']:>9}"
            )
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
        print("Commission | Total OOS Return | OOS Sharpe | Deflated Sharpe | N Periods")
        print("-" * 90)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['commission']:>13.6f} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {dsr_txt:>15} | {row['n_periods']:>9}"
            )
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
        print("Slippage | Total OOS Return | OOS Sharpe | Deflated Sharpe | N Periods")
        print("-" * 90)
        for row in sweep_rows:
            oos_sharpe_txt = "N/A" if row["oos_sharpe"] is None else f"{row['oos_sharpe']:.4f}"
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['slippage']:>13.6f} | {'N/A' if row["total_oos_return"] is None else f"{row['total_oos_return']:>16.4f}"} | "
                f"{oos_sharpe_txt:>10} | {dsr_txt:>15} | {row['n_periods']:>9}"
            )
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
    _total_oos_return = results["summary"]["total_oos_return"]
    print(
        f"Total OOS Return: {'N/A' if _total_oos_return is None else f'{_total_oos_return:.2%}'}"
    )
    print(f"OOS Sharpe Ratio: {results['summary'].get('oos_sharpe', 'N/A')}")
    _print_panel_pricing(results["summary"].get("panel_pricing"))
    _print_book_diagnostic(
        results["summary"].get("book_diagnostic"),
        panel_pricing=results["summary"].get("panel_pricing"),
    )

    dsr = results["summary"].get("deflated_sharpe")
    if dsr is not None:
        print(
            f"Deflated Sharpe Ratio: {dsr['deflated_sharpe_ratio']:.4f} "
            f"(p-value {dsr['p_value']:.4f}, expected max Sharpe "
            f"{dsr['expected_max_sharpe']:.4f}, {dsr['n_trials']} trials)"
        )

    # Check for overfitting
    diagnostics = overfitting_check(results)
    print(f"Overfitting Risk: {diagnostics['overfitting_risk']}")

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

    return 0


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
        print("Impact coefficient | Top Sharpe | Top Total Return | N Combos")
        print("-" * 70)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["top_sharpe"] is None else f"{row['top_sharpe']:.4f}"
            print(
                f"{row['impact_coefficient']:>17} | {sharpe_txt:>10} | "
                f"{row['top_total_return']:>16.4f} | {row['n_combos']:>7}"
            )
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
        print("Borrow Cost | Top Sharpe | Top Total Return | N Combos")
        print("-" * 70)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["top_sharpe"] is None else f"{row['top_sharpe']:.4f}"
            print(
                f"{row['borrow_cost']:>13.4f} | {sharpe_txt:>10} | "
                f"{row['top_total_return']:>16.4f} | {row['n_combos']:>7}"
            )
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
        print("Funding Cost | Top Sharpe | Top Total Return | N Combos")
        print("-" * 70)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["top_sharpe"] is None else f"{row['top_sharpe']:.4f}"
            print(
                f"{row['funding_cost']:>13.4f} | {sharpe_txt:>10} | "
                f"{row['top_total_return']:>16.4f} | {row['n_combos']:>7}"
            )
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
        print("Commission | Top Sharpe | Top Total Return | N Combos")
        print("-" * 70)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["top_sharpe"] is None else f"{row['top_sharpe']:.4f}"
            print(
                f"{row['commission']:>13.6f} | {sharpe_txt:>10} | "
                f"{row['top_total_return']:>16.4f} | {row['n_combos']:>7}"
            )
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
        print("Slippage | Top Sharpe | Top Total Return | N Combos")
        print("-" * 70)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["top_sharpe"] is None else f"{row['top_sharpe']:.4f}"
            print(
                f"{row['slippage']:>13.6f} | {sharpe_txt:>10} | "
                f"{row['top_total_return']:>16.4f} | {row['n_combos']:>7}"
            )
        return 0

    param_grid = _parse_param_grid(args.param_grid)
    strategy_factory = _make_strategy_factory(args.strategy)

    print(f"Running parameter optimization with {args.strategy}...")
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
    return {
        "impact_coefficient": float(impact_coefficient),
        "borrow_cost": float(borrow_cost),
        "funding_cost": float(funding_cost),
        "commission": float(commission),
        "slippage": float(slippage),
        "latency": int(latency),
        "fill_rate": float(fill_rate),
        "total_return": float(sm.get("total_return", {}).get("mean", 0.0)),
        "sharpe_ratio": float(sm.get("sharpe_ratio", {}).get("mean", 0.0)),
        "max_drawdown": float(sm.get("max_drawdown", {}).get("mean", 0.0)),
        "probability_of_ruin": float(mc_results["probability_of_ruin"]),
        "deflated_sharpe": (float(dsr["deflated_sharpe_ratio"]) if dsr is not None else None),
        "deflated_sharpe_n_trials": (
            int(dsr["n_trials"]) if dsr is not None and dsr.get("n_trials") is not None else None
        ),
        "n_simulations": int(mc_results["n_simulations"]),
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
        print("Impact coefficient | Total Return | Sharpe Ratio | Max Drawdown | Prob. of Ruin | Deflated Sharpe")
        print("-" * 96)
        for row in sweep_rows:
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['impact_coefficient']:>17} | {row['total_return']:>12.4f} | {row['sharpe_ratio']:>12.4f} | "
                f"{row['max_drawdown']:>12.4f} | {row['probability_of_ruin']:>13.2%} | {dsr_txt:>15}"
            )
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
        print("Borrow Cost | Total Return | Sharpe Ratio | Max Drawdown | Prob. of Ruin | Deflated Sharpe")
        print("-" * 96)
        for row in sweep_rows:
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['borrow_cost']:>13.4f} | {row['total_return']:>12.4f} | {row['sharpe_ratio']:>12.4f} | "
                f"{row['max_drawdown']:>12.4f} | {row['probability_of_ruin']:>13.2%} | {dsr_txt:>15}"
            )
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
        print("Funding Cost | Total Return | Sharpe Ratio | Max Drawdown | Prob. of Ruin | Deflated Sharpe")
        print("-" * 96)
        for row in sweep_rows:
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['funding_cost']:>13.4f} | {row['total_return']:>12.4f} | {row['sharpe_ratio']:>12.4f} | "
                f"{row['max_drawdown']:>12.4f} | {row['probability_of_ruin']:>13.2%} | {dsr_txt:>15}"
            )
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
        print("Commission | Total Return | Sharpe Ratio | Max Drawdown | Prob. of Ruin | Deflated Sharpe")
        print("-" * 96)
        for row in sweep_rows:
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['commission']:>13.6f} | {row['total_return']:>12.4f} | {row['sharpe_ratio']:>12.4f} | "
                f"{row['max_drawdown']:>12.4f} | {row['probability_of_ruin']:>13.2%} | {dsr_txt:>15}"
            )
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
        print("Slippage | Total Return | Sharpe Ratio | Max Drawdown | Prob. of Ruin | Deflated Sharpe")
        print("-" * 96)
        for row in sweep_rows:
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['slippage']:>13.6f} | {row['total_return']:>12.4f} | {row['sharpe_ratio']:>12.4f} | "
                f"{row['max_drawdown']:>12.4f} | {row['probability_of_ruin']:>13.2%} | {dsr_txt:>15}"
            )
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
        print("Impact coefficient | Test Total Return | Test Sharpe | Deflated Sharpe")
        print("-" * 74)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["test_sharpe"] is None else f"{row['test_sharpe']:.4f}"
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['impact_coefficient']:>17} | {row['test_total_return']:>16.4f} | "
                f"{sharpe_txt:>11} | {dsr_txt:>15}"
            )
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
        print("Borrow Cost | Test Total Return | Test Sharpe | Deflated Sharpe")
        print("-" * 74)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["test_sharpe"] is None else f"{row['test_sharpe']:.4f}"
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['borrow_cost']:>13.4f} | {row['test_total_return']:>16.4f} | "
                f"{sharpe_txt:>11} | {dsr_txt:>15}"
            )
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
        print("Funding Cost | Test Total Return | Test Sharpe | Deflated Sharpe")
        print("-" * 74)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["test_sharpe"] is None else f"{row['test_sharpe']:.4f}"
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['funding_cost']:>13.4f} | {row['test_total_return']:>16.4f} | "
                f"{sharpe_txt:>11} | {dsr_txt:>15}"
            )
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
        print("Commission | Test Total Return | Test Sharpe | Deflated Sharpe")
        print("-" * 74)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["test_sharpe"] is None else f"{row['test_sharpe']:.4f}"
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['commission']:>13.6f} | {row['test_total_return']:>16.4f} | "
                f"{sharpe_txt:>11} | {dsr_txt:>15}"
            )
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
        print("Slippage | Test Total Return | Test Sharpe | Deflated Sharpe")
        print("-" * 74)
        for row in sweep_rows:
            sharpe_txt = "N/A" if row["test_sharpe"] is None else f"{row['test_sharpe']:.4f}"
            dsr_txt = "N/A" if row["deflated_sharpe"] is None else f"{row['deflated_sharpe']:.4f}"
            print(
                f"{row['slippage']:>13.6f} | {row['test_total_return']:>16.4f} | "
                f"{sharpe_txt:>11} | {dsr_txt:>15}"
            )
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
        print("No valid parameters selected from validation phase.")
        return 1

    print(f"\nSelected Parameters: {selected}")

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
    _print_book_diagnostic(
        test_perf.get("book_diagnostic"),
        indent="  ",
        panel_pricing=results["summary"].get("panel_pricing"),
    )

    summary = results["summary"]
    dsr = summary.get("deflated_sharpe")
    if dsr is not None:
        print(
            f"\nDeflated Sharpe Ratio (test): {dsr['deflated_sharpe_ratio']:.4f} "
            f"(p-value {dsr['p_value']:.4f}, expected max Sharpe "
            f"{dsr['expected_max_sharpe']:.4f}, {dsr['n_trials']} trials)"
        )

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
            "test_n_periods": results["test_performance"]["test_n_periods"],
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

    return 0


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
    common_parser.add_argument("--fill-rate", type=float, default=1.0, help="Execution fill rate (0 < r <= 1); only this fraction of each targeted position change is filled, scaling the achieved position and all transaction costs proportionally. Default 1.0 (full fill, backward compatible).")
    common_parser.add_argument("--fill-rates", type=float, nargs="+", default=None, help="List of fill rates to sweep (overrides --fill-rate).")
    common_parser.add_argument("--latencies", type=int, nargs="+", default=None, help="List of execution latencies (in periods) to sweep (overrides --latency). Delays position execution by each latency after signal generation.")
    common_parser.add_argument(
        "--panel-pricing",
        type=str,
        default="net-exposure",
        choices=["net-exposure", "book"],
        help=(
            "How a multi-asset panel is priced. 'net-exposure' (default) prices "
            "the portfolio as net_exposure x mean(asset returns) -- the "
            "convention every published number was produced under. 'book' "
            "prices the true per-asset book return sum_i w_i r_i, which makes "
            "a market-neutral book backtestable. The cost and impact model is "
            "unchanged in both modes (it still sees |d net exposure|)."
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
