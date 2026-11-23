#!/usr/bin/env python3
"""Cross-family protocol-sensitivity meta-analysis (5 families) using Reality
Check / Romano-Wolf stepdown on aligned per-period OOS returns.

Motivation
----------
The 4-family cross-family meta-analysis
(``test_walk_forward_cross_family_reality_check_real_triple.py``) covers
time-series momentum, volatility targeting, RSI mean reversion, and SMA
crossover. A fifth family, ``zscore_mean_reversion``, has since received its
own cross-asset protocol-sensitivity summary
(``test_walk_forward_zscore_mean_reversion_protocol_sensitivity_real_triple_summary.py``,
which concludes NOT SUPPORTED with best nominal DSR p = 0.2738 at MSFT @
(24, 12, 12)). It is a methodological gap that the cross-family family-wise
test still omits it.

This study closes that gap by re-running the family-wise procedures on
*aligned per-period OOS returns* across **all five** families, each represented
by its pinned best-nominal per-asset cell:
- utils.reality_check_test (White 2000 / Hansen 2005; stationary block bootstrap)
- utils.romano_wolf_stepdown (Romano-Wolf 2005 stepdown; FWER-controlled)

Design (pre-registered before any number is inspected)
------------------------------------------------------
* Five families on the committed triple panel (AAPL, MSFT, GOOGL), each
  represented by its pinned best-nominal per-asset cell (the asset-protocol
  combination with the minimum within-protocol DSR p-value in that family):
    - time_series_momentum   : MSFT @ (30, 12, 12), param_grid lookback [126, 189, 252]
    - volatility_targeting   : GOOGL @ (36, 12, 12), param_grid target_vol [0.15], lookback [63]
    - rsi_mean_reversion     : GOOGL @ (36, 12, 12), param_grid period/oversold/overbought/neutral
    - sma_crossover          : AAPL @ (36, 12, 12), param_grid fast_period [20], slow_period [50]
    - zscore_mean_reversion  : MSFT @ (24, 12, 12), param_grid period [20], entry_z [2.0], exit_z [0.5]
* Costs: commission 2 bps + slippage 1 bps per trade (shipped default).
* apply_deflation=True, validate_pit=True for each cell.
* Date alignment: each family's best cell produces OOS returns on its own
  protocol dates. We construct a common daily calendar (union of all dates in
  the intersection of the five date ranges), reindex each series to that
  calendar, and apply listwise deletion (drop rows where any strategy has NaN).
* Benchmark: daily risk-free rate = 0.02 / 252 (2% annual, matching the
  framework's Sharpe annualization convention).
* Pre-registered falsification criterion: reality_check_test p-value < 0.10
  (family-wise), and romano_wolf_stepdown n_rejected > 0 at alpha = 0.10.
* n_bootstrap = 1000, seed = 42 for reproducibility.

Honest finding (all committed fixtures, offline; pinned by the run below)
-------------------------------------------------------------------------
Aligned OOS returns after listwise deletion: T = 368 daily observations,
K = 5 strategies (one per family, best-nominal per-asset cells).
Common calendar: 2023-04-06 .. 2024-12-31.

Reality Check Test (studentized, block bootstrap, n_bootstrap=1000, seed=42):
    Test statistic = 1.7695
    P-value = 0.1630
    Best strategy = sma_crossover (mean excess = 0.000882/day)
    Significant at alpha=0.10: FALSE

Romano-Wolf Stepdown (studentized, same bootstrap, alpha=0.10):
    Ordered by studentized statistic: time_series_momentum (1.7695),
    sma_crossover (1.5803), rsi_mean_reversion (1.4718),
    volatility_targeting (0.5804), zscore_mean_reversion (0.3730)
    Raw p-values: [0.1630, 0.2130, 0.1980, 0.4770, 0.3600]
    Adjusted p-values (running max): [0.1630, 0.2130, 0.2130, 0.4770, 0.4770]
    Rejected: [False, False, False, False, False]
    n_rejected = 0
    Simultaneous 90% max-t CI for mean excess (all contain zero):
        time_series_momentum:  [-0.000182, 0.001558]
        sma_crossover:         [-0.000367, 0.002132]
        rsi_mean_reversion:    [-0.000440, 0.002133]
        volatility_targeting:  [-0.000837, 0.001422]
        zscore_mean_reversion: [-0.000893, 0.001251]

Overall verdict: NOT SUPPORTED. No signal family survives family-wise control
when tested on aligned per-period returns. Adding the fifth family (zscore)
lowers the best mean excess (zscore = 0.000179/day, lowest of the five) and
enlarges the max-statistic null, so the Reality Check p-value rises from
0.1310 (4-family) to 0.1630 (5-family) — still above the pre-registered 0.10
threshold, and the Romano-Wolf stepdown still rejects zero strategies.

Limitation: the aligned sample (T=368) is below the 504-observation threshold
where the Romano-Wolf simultaneous max-t bands are empirically well-covered;
the result carries a small-sample warning. The Reality Check p-value itself
is valid at this sample size. The conclusion is robust either way.

Offline, committed fixtures only; no live network. Test-only.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import walk_forward_analysis  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402
from utils import reality_check_test, romano_wolf_stepdown  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade
ALPHA = 0.10
N_BOOTSTRAP = 1000
SEED = 42
RF_DAILY = 0.02 / 252  # 2% annual risk-free rate

ABS_TOL = 1e-3

# Best-nominal per-asset cell for each family (from cross-asset summaries)
# Each entry: symbol, protocol (train, test, step), param_grid, signal_name
BEST_CELLS = {
    "time_series_momentum": dict(
        symbol="MSFT",
        protocol=(30, 12, 12),
        param_grid={"lookback": [126, 189, 252]},
        signal="time_series_momentum",
        expected_dsr_p=0.0696,
    ),
    "volatility_targeting": dict(
        symbol="GOOGL",
        protocol=(36, 12, 12),
        param_grid={"target_vol": [0.15], "lookback": [63]},
        signal="volatility_targeting",
        expected_dsr_p=0.2782,
    ),
    "rsi_mean_reversion": dict(
        symbol="GOOGL",
        protocol=(36, 12, 12),
        param_grid={"period": [14], "oversold": [30], "overbought": [70], "neutral": [50]},
        signal="rsi_mean_reversion",
        expected_dsr_p=0.1726,
    ),
    "sma_crossover": dict(
        symbol="AAPL",
        protocol=(36, 12, 12),
        param_grid={"fast_period": [20], "slow_period": [50]},
        signal="sma_crossover",
        expected_dsr_p=0.0415,
    ),
    "zscore_mean_reversion": dict(
        symbol="MSFT",
        protocol=(24, 12, 12),
        param_grid={"period": [20], "entry_z": [2.0], "exit_z": [0.5]},
        signal="zscore_mean_reversion",
        expected_dsr_p=0.2738,
    ),
}

FAMILY_ORDER = ["time_series_momentum", "volatility_targeting",
                "rsi_mean_reversion", "sma_crossover", "zscore_mean_reversion"]

# Pinned results from the pre-registered run (regression guards)
PINNED_RC = dict(
    test_statistic=1.7695,
    p_value=0.1630,
    best_index=3,  # sma_crossover
    best_mean=0.000882,
    means=[0.000688, 0.000293, 0.000846, 0.000882, 0.000179],
    significant=False,
)

PINNED_RW = dict(
    ordered_indices=[0, 3, 2, 1, 4],
    p_values=[0.1630, 0.2130, 0.1980, 0.4770, 0.3600],
    adjusted_p_values=[0.1630, 0.2130, 0.2130, 0.4770, 0.4770],
    rejected=[False, False, False, False, False],
    n_rejected=0,
    statistics=[1.7695, 1.5803, 1.4718, 0.5804, 0.3730],
    means=[0.000688, 0.000882, 0.000846, 0.000293, 0.000179],
    simultaneous_ci_lower=[-0.000182, -0.000367, -0.000440, -0.000837, -0.000893],
    simultaneous_ci_upper=[0.001558, 0.002132, 0.002133, 0.001422, 0.001251],
    simultaneous_ci_small_sample_warning=(
        "max-t simultaneous bands are asymptotic and may undercover on short samples "
        "(n_observations=368 < 504); interpret coverage as approximate"
    ),
)

# Pinned aligned sample size
PINNED_N_OBS = 368


def _build_data(symbol):
    df = pd.read_csv(SRC / f"{symbol}.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _factory(signal, params):
    return build_strategy(signal, json.dumps(params))


def _run_best_cell(family_name):
    """Run the pinned best-nominal cell for one family, return OOS returns Series."""
    cfg = BEST_CELLS[family_name]
    protocol = cfg["protocol"]
    train_months, test_months, step_months = protocol
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = walk_forward_analysis(
            data=_build_data(cfg["symbol"]),
            strategy_factory=lambda params: _factory(cfg["signal"], params),
            param_grid=cfg["param_grid"],
            train_months=train_months,
            test_months=test_months,
            step_months=step_months,
            commission=COMMISSION,
            slippage=SLIPPAGE,
            apply_deflation=True,
            validate_pit=True,
        )
    summary = result["summary"]
    assert summary.get("bias_controls_engaged") is True, (
        f"{family_name}: point-in-time validation not engaged"
    )
    dsr = summary.get("deflated_sharpe") or {}
    dsr_p = dsr.get("p_value")
    assert dsr_p is not None, f"{family_name}: missing DSR p-value"
    return {
        "family": family_name,
        "symbol": cfg["symbol"],
        "protocol": protocol,
        "oos_returns": result["oos_returns"],
        "dsr_p": dsr_p,
    }


def _collect_aligned_returns():
    """Run all 5 best cells, align to common calendar, return (T, K) array and metadata."""
    cells = []
    for family in FAMILY_ORDER:
        cells.append(_run_best_cell(family))

    # Build common calendar: union of dates in the intersection of all ranges
    all_indices = [c["oos_returns"].index for c in cells]
    common_start = max(idx[0] for idx in all_indices)
    common_end = min(idx[-1] for idx in all_indices)

    common_dates = pd.DatetimeIndex([])
    for c in cells:
        common_dates = common_dates.union(
            c["oos_returns"].loc[common_start:common_end].index
        )
    common_dates = common_dates.sort_values()

    # Reindex each series to common calendar
    aligned = {}
    for c in cells:
        fam = c["family"]
        aligned[fam] = c["oos_returns"].loc[common_start:common_end].reindex(common_dates)

    # Listwise deletion (same as utils functions do internally)
    df = pd.DataFrame(aligned, columns=FAMILY_ORDER).dropna()
    performance = df.values  # shape (T, K)
    benchmark = np.full(performance.shape[0], RF_DAILY)

    return {
        "performance": performance,
        "benchmark": benchmark,
        "n_obs": performance.shape[0],
        "n_strategies": performance.shape[1],
        "families": FAMILY_ORDER,
        "cells": cells,
    }


def _assert_close(got, exp, label):
    assert got is not None, f"{label}: missing value (expected ~{exp})"
    assert abs(float(got) - float(exp)) <= ABS_TOL, (
        f"{label}: got {got!r}, expected ~{exp} (abs tol {ABS_TOL})"
    )


def _assert_list_close(got, exp, label):
    assert len(got) == len(exp), f"{label}: length mismatch {len(got)} vs {len(exp)}"
    for i, (g, e) in enumerate(zip(got, exp)):
        assert abs(float(g) - float(e)) <= ABS_TOL, (
            f"{label}[{i}]: got {g!r}, expected ~{e} (abs tol {ABS_TOL})"
        )


def test_per_family_best_cell_dsr_regress():
    """Regression guard: each family's best-nominal DSR p-value matches the
    pinned value from the cross-asset protocol-sensitivity summary."""
    cells = []
    for family in FAMILY_ORDER:
        cells.append(_run_best_cell(family))
    for c in cells:
        fam = c["family"]
        exp_p = BEST_CELLS[fam]["expected_dsr_p"]
        _assert_close(c["dsr_p"], exp_p, f"{fam} {c['symbol']} {c['protocol']} DSR p")
        p = c["dsr_p"]
        assert 0.0 <= float(p) <= 1.0, f"{fam}: DSR p-value out of range: {p!r}"
    print(f"Cross-family RC (5): re-verified {len(cells)} per-family best-nominal DSR p-values")


def test_aligned_sample_size():
    """Verify the aligned sample size matches the pinned value."""
    aligned = _collect_aligned_returns()
    n_obs = aligned["n_obs"]
    _assert_close(n_obs, PINNED_N_OBS, "aligned n_obs")
    print(f"Cross-family RC (5): aligned sample size n_obs = {n_obs}")


def test_reality_check_test():
    """Reality Check Test on the aligned 5-family performance matrix.
    Pre-registered criterion: p-value < 0.10 (family-wise).
    Pinned result: p = 0.1630 > 0.10, NOT SUPPORTED."""
    aligned = _collect_aligned_returns()
    res = reality_check_test(
        performance=aligned["performance"],
        benchmark=aligned["benchmark"],
        n_bootstrap=N_BOOTSTRAP,
        seed=SEED,
        studentize=True,
        alpha=ALPHA,
    )

    # Regression guards against pinned results
    _assert_close(res["test_statistic"], PINNED_RC["test_statistic"], "RC test_statistic")
    _assert_close(res["p_value"], PINNED_RC["p_value"], "RC p_value")
    assert res["best_index"] == PINNED_RC["best_index"], (
        f"RC best_index: got {res['best_index']}, expected {PINNED_RC['best_index']}"
    )
    _assert_close(res["best_mean"], PINNED_RC["best_mean"], "RC best_mean")
    _assert_list_close(res["means"], PINNED_RC["means"], "RC means")
    assert res["significant"] == PINNED_RC["significant"], (
        f"RC significant: got {res['significant']}, expected {PINNED_RC['significant']}"
    )

    # Honest report
    best_fam = aligned["families"][res["best_index"]]
    print(f"Reality Check (5 families): best strategy = {best_fam} (studentized stat = "
          f"{res['test_statistic']:.4f}, p = {res['p_value']:.4f})")
    print(f"  Family-wise verdict at alpha={ALPHA}: {'SUPPORTED' if res['significant'] else 'NOT SUPPORTED'}")
    print(f"  Mean excess per strategy (daily): "
          f"{', '.join(f'{f}={m:.6f}' for f, m in zip(aligned['families'], res['means']))}")

    # Pre-registered falsification criterion
    assert not res["significant"], (
        f"Reality Check: p-value {res['p_value']:.4f} should exceed {ALPHA} "
        f"(NOT SUPPORTED at family-wise level)"
    )


def test_romano_wolf_stepdown():
    """Romano-Wolf stepdown on the aligned 5-family performance matrix.
    Pre-registered criterion: n_rejected > 0 at alpha = 0.10 (FWER-controlled).
    Pinned result: n_rejected = 0, NOT SUPPORTED."""
    aligned = _collect_aligned_returns()
    res = romano_wolf_stepdown(
        performance=aligned["performance"],
        benchmark=aligned["benchmark"],
        n_bootstrap=N_BOOTSTRAP,
        seed=SEED,
        studentize=True,
        alpha=ALPHA,
    )

    # Regression guards against pinned results
    assert res["ordered_indices"] == PINNED_RW["ordered_indices"], (
        f"RW ordered_indices: got {res['ordered_indices']}, "
        f"expected {PINNED_RW['ordered_indices']}"
    )
    _assert_list_close(res["p_values"], PINNED_RW["p_values"], "RW p_values")
    _assert_list_close(res["adjusted_p_values"], PINNED_RW["adjusted_p_values"], "RW adjusted_p_values")
    assert res["rejected"] == PINNED_RW["rejected"], (
        f"RW rejected: got {res['rejected']}, expected {PINNED_RW['rejected']}"
    )
    assert res["n_rejected"] == PINNED_RW["n_rejected"], (
        f"RW n_rejected: got {res['n_rejected']}, expected {PINNED_RW['n_rejected']}"
    )
    _assert_list_close(res["statistics"], PINNED_RW["statistics"], "RW statistics")
    _assert_list_close(res["means"], PINNED_RW["means"], "RW means")
    _assert_list_close(res["simultaneous_ci_lower"], PINNED_RW["simultaneous_ci_lower"], "RW sim CI lower")
    _assert_list_close(res["simultaneous_ci_upper"], PINNED_RW["simultaneous_ci_upper"], "RW sim CI upper")
    assert res["simultaneous_ci_small_sample_warning"] == PINNED_RW["simultaneous_ci_small_sample_warning"], (
        "RW small sample warning mismatch"
    )

    # Honest report
    ordered_fams = [aligned["families"][i] for i in res["ordered_indices"]]
    print(f"Romano-Wolf Stepdown (5 families, alpha={ALPHA}):")
    print(f"  Ordered by studentized stat: "
          f"{', '.join(f'{f}={s:.4f}' for f, s in zip(ordered_fams, res['statistics']))}")
    print(f"  Raw p-values: "
          f"{', '.join(f'{f}={p:.4f}' for f, p in zip(ordered_fams, res['p_values']))}")
    print(f"  Adjusted p-values: "
          f"{', '.join(f'{f}={p:.4f}' for f, p in zip(ordered_fams, res['adjusted_p_values']))}")
    print(f"  Rejected: "
          f"{', '.join(f'{f}={r}' for f, r in zip(ordered_fams, res['rejected']))}")
    print(f"  n_rejected = {res['n_rejected']}")
    print(f"  Simultaneous 90% max-t CIs (all contain zero):")
    for f, lo, hi in zip(ordered_fams, res["simultaneous_ci_lower"], res["simultaneous_ci_upper"]):
        print(f"    {f}: [{lo:.6f}, {hi:.6f}]")
    if res["simultaneous_ci_small_sample_warning"]:
        print(f"  Warning: {res['simultaneous_ci_small_sample_warning']}")

    # Pre-registered falsification criterion
    assert res["n_rejected"] == 0, (
        f"Romano-Wolf: expected n_rejected = 0 at alpha={ALPHA}, got {res['n_rejected']}"
    )


def test_overall_verdict_not_supported():
    """Aggregate verdict: both family-wise tests conclude NOT SUPPORTED with
    all five families included."""
    aligned = _collect_aligned_returns()
    rc = reality_check_test(
        performance=aligned["performance"],
        benchmark=aligned["benchmark"],
        n_bootstrap=N_BOOTSTRAP,
        seed=SEED,
        studentize=True,
        alpha=ALPHA,
    )
    rw = romano_wolf_stepdown(
        performance=aligned["performance"],
        benchmark=aligned["benchmark"],
        n_bootstrap=N_BOOTSTRAP,
        seed=SEED,
        studentize=True,
        alpha=ALPHA,
    )

    # Both tests must agree on NOT SUPPORTED
    assert not rc["significant"], "Reality Check should not reject at alpha=0.10"
    assert rw["n_rejected"] == 0, "Romano-Wolf should reject 0 strategies at alpha=0.10"

    print(f"Overall 5-family cross-family verdict (Reality Check + Romano-Wolf): NOT SUPPORTED")
    print(f"  Reality Check p-value: {rc['p_value']:.4f} (threshold {ALPHA})")
    print(f"  Romano-Wolf n_rejected: {rw['n_rejected']} (threshold > 0)")
    print(f"  Adding zscore (lowest mean excess) raises RC p 0.1310 -> 0.1630; still NOT SUPPORTED")


def test_main_registers_every_module_level_test():
    """main() must register every module-level ``test_*`` function."""
    import inspect

    module_tests = {
        obj
        for name, obj in list(globals().items())
        if name.startswith("test_")
        and inspect.isfunction(obj)
        and obj.__module__ == __name__
    }
    registered = {fn for _, fn in TEST_REGISTRY}

    missing = module_tests - registered
    assert not missing, (
        f"test functions defined but not registered in TEST_REGISTRY: "
        f"{sorted(f.__name__ for f in missing)}"
    )
    phantom = registered - module_tests
    assert not phantom, (
        f"entries in TEST_REGISTRY that are not module-level test_* "
        f"functions: {sorted(f.__name__ for f in phantom)}"
    )
    labels = [name for name, _ in TEST_REGISTRY]
    assert len(labels) == len(set(labels)), (
        f"TEST_REGISTRY has duplicate labels: "
        f"{[l for l in labels if labels.count(l) > 1]}"
    )


TEST_REGISTRY = [
    ("per_family_best_cell_dsr_regress", test_per_family_best_cell_dsr_regress),
    ("aligned_sample_size", test_aligned_sample_size),
    ("reality_check_test", test_reality_check_test),
    ("romano_wolf_stepdown", test_romano_wolf_stepdown),
    ("overall_verdict_not_supported", test_overall_verdict_not_supported),
    ("main_registers_every_module_level_test", test_main_registers_every_module_level_test),
]


def main() -> int:
    import traceback

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