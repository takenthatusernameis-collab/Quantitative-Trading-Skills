#!/usr/bin/env python3
"""Cross-family protocol-sensitivity meta-analysis (5 families) using Reality
Check / Romano-Wolf stepdown on aligned per-bar OOS returns under
purged/embargoed Combinatorial Purged Cross-Validation (CPCV).

Motivation
----------
The committed 5-family cross-family meta-analysis
(test_walk_forward_cross_family_reality_check_5family_real_triple.py) uses
walk-forward splits only and concludes NOT SUPPORTED
(Reality Check p = 0.1630 > 0.10; Romano-Wolf n_rejected = 0 at alpha = 0.10).
This study tests whether that verdict is stable to the CV scheme: it re-runs
each family's pinned best-nominal cell under purged/embargoed CPCV splits
(the repo's stated defense against leakage/look-ahead bias) and re-applies the
same family-wise Reality Check / Romano-Wolf procedures on the aligned
per-bar OOS returns.

Design (pre-registered before any number is inspected)
------------------------------------------------------
* Five families on the committed triple panel (AAPL, MSFT, GOOGL), each
  represented by its pinned best-nominal per-asset cell (same cells as the
  committed walk-forward 5-family study):
    - time_series_momentum   : MSFT @ (30, 12, 12), lookback [126, 189, 252]
    - volatility_targeting   : GOOGL @ (36, 12, 12), target_vol [0.15], lookback [63]
    - rsi_mean_reversion     : GOOGL @ (36, 12, 12), period/oversold/overbought/neutral
    - sma_crossover          : AAPL @ (36, 12, 12), fast_period [20], slow_period [50]
    - zscore_mean_reversion  : MSFT @ (24, 12, 12), period [20], entry_z [2.0], exit_z [0.5]
* Costs: commission 2 bps + slippage 1 bps per trade (shipped default).
* CPCV: n_splits=5, test_size=0.2, purge_size=0.10, embargo_size=0.10
  (purged/embargoed training around each test window).
* apply_deflation=True, validate_pit=True for each cell.
* Date alignment: each family's pooled CPCV OOS returns are reindexed to a
  common daily calendar (intersection of all five date ranges) with listwise
  deletion.
* Benchmark: daily risk-free rate = 0.02 / 252.
* Pre-registered falsification criterion (same as the walk-forward study):
  reality_check_test p-value < 0.10 (family-wise), and
  romano_wolf_stepdown n_rejected > 0 at alpha = 0.10.
* n_bootstrap = 1000, seed = 42 for reproducibility.

Honest finding (committed fixtures, offline; pinned by the run below)
--------------------------------------------------------------------
Captured from the first green run; regression pins are recorded after that run
so the test guards against silent changes to the backtest numbers.

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

from walk_forward import cpcv_analysis  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402
from utils import reality_check_test, romano_wolf_stepdown  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade
ALPHA = 0.10
N_BOOTSTRAP = 1000
SEED = 42
RF_DAILY = 0.02 / 252  # 2% annual risk-free rate

# CPCV scheme under test (purged/embargoed): the repo's leakage defense.
N_SPLITS = 5
TEST_SIZE = 0.2
PURGE_SIZE = 0.10
EMBARGO_SIZE = 0.10

ABS_TOL = 1e-3

# Best-nominal per-asset cell for each family (from cross-asset summaries;
# identical to the committed walk-forward 5-family study).
BEST_CELLS = {
    "time_series_momentum": dict(
        symbol="MSFT",
        protocol=(30, 12, 12),
        param_grid={"lookback": [126, 189, 252]},
        signal="time_series_momentum",
    ),
    "volatility_targeting": dict(
        symbol="GOOGL",
        protocol=(36, 12, 12),
        param_grid={"target_vol": [0.15], "lookback": [63]},
        signal="volatility_targeting",
    ),
    "rsi_mean_reversion": dict(
        symbol="GOOGL",
        protocol=(36, 12, 12),
        param_grid={"period": [14], "oversold": [30], "overbought": [70], "neutral": [50]},
        signal="rsi_mean_reversion",
    ),
    "sma_crossover": dict(
        symbol="AAPL",
        protocol=(36, 12, 12),
        param_grid={"fast_period": [20], "slow_period": [50]},
        signal="sma_crossover",
    ),
    "zscore_mean_reversion": dict(
        symbol="MSFT",
        protocol=(24, 12, 12),
        param_grid={"period": [20], "entry_z": [2.0], "exit_z": [0.5]},
        signal="zscore_mean_reversion",
    ),
}

FAMILY_ORDER = ["time_series_momentum", "volatility_targeting",
                "rsi_mean_reversion", "sma_crossover", "zscore_mean_reversion"]

# Regression pins (captured from the committed green run, purge=0.10/embargo=0.10,
# n_splits=5, test_size=0.2, seed=42). Hard-coded so the test guards against
# silent changes to the backtest numbers rather than capturing itself.
PINNED_RC = dict(
    test_statistic=1.5960274921963793,
    p_value=0.261,
    best_index=2,  # rsi_mean_reversion
    best_mean=0.0011142449580313328,
    means=[0.00017399132267447988, 0.00010503370252333698,
           0.0011142449580313328, 2.9248989208393186e-05, 5.7615274876778894e-05],
    significant=False,
)

PINNED_RW = dict(
    ordered_indices=[2, 0, 1, 4, 3],
    p_values=[0.261, 0.869, 0.833, 0.733, 0.457],
    adjusted_p_values=[0.261, 0.869, 0.869, 0.869, 0.869],
    rejected=[False, False, False, False, False],
    n_rejected=0,
    statistics=[1.5960274921963793, 0.22987989773539663, 0.15784946478646691,
                0.11260771954555876, 0.05535556561861802],
    means=[0.0011142449580313328, 0.00017399132267447988, 0.00010503370252333698,
           5.7615274876778894e-05, 2.9248989208393186e-05],
    simultaneous_ci_lower=[-0.0005465217215373933, -0.0016265160648414561,
                           -0.0014778677389224559, -0.0011595170255725479,
                           -0.0012277006649801655],
    simultaneous_ci_upper=[0.0027750116376000587, 0.001974498710190416,
                           0.00168793514396913, 0.0012747475753261057,
                           0.0012861986433969517],
    simultaneous_ci_small_sample_warning=(
        "max-t simultaneous bands are asymptotic and may undercover on short samples "
        "(n_observations=232 < 504); interpret coverage as approximate"
    ),
)

# Pinned aligned sample size (T=232 daily observations, K=5 strategies).
PINNED_N_OBS = 232


def _build_data(symbol):
    df = pd.read_csv(SRC / f"{symbol}.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _factory(signal, params):
    return build_strategy(signal, json.dumps(params))


def _run_cpcv_cell(family_name):
    """Run the pinned best-nominal cell for one family under CPCV, return OOS returns."""
    cfg = BEST_CELLS[family_name]
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = cpcv_analysis(
            data=_build_data(cfg["symbol"]),
            strategy_factory=lambda params: _factory(cfg["signal"], params),
            param_grid=cfg["param_grid"],
            n_splits=N_SPLITS,
            test_size=TEST_SIZE,
            purge_size=PURGE_SIZE,
            embargo_size=EMBARGO_SIZE,
            commission=COMMISSION,
            slippage=SLIPPAGE,
            apply_deflation=True,
            validate_pit=True,
        )
    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out, (
        f"{family_name}: point-in-time validation not engaged"
    )
    summary = result["summary"]
    dsr = summary.get("deflated_sharpe") or {}
    dsr_p = dsr.get("p_value")
    assert dsr_p is not None, f"{family_name}: missing DSR p-value"
    oos = result["oos_returns"]
    assert isinstance(oos, pd.Series) and len(oos) > 0, (
        f"{family_name}: empty CPCV OOS returns"
    )
    return {
        "family": family_name,
        "symbol": cfg["symbol"],
        "oos_returns": oos,
        "dsr_p": dsr_p,
        "n_folds": summary.get("n_folds"),
        "folds_with_position": summary.get("folds_with_position"),
    }


def _collect_aligned_returns():
    """Run all 5 best cells under CPCV, align to common calendar, return (T, K)."""
    cells = [_run_cpcv_cell(family) for family in FAMILY_ORDER]
    all_indices = [c["oos_returns"].index for c in cells]
    common_start = max(idx[0] for idx in all_indices)
    common_end = min(idx[-1] for idx in all_indices)

    common_dates = pd.DatetimeIndex([])
    for c in cells:
        common_dates = common_dates.union(
            c["oos_returns"].loc[common_start:common_end].index
        )
    common_dates = common_dates.sort_values()

    aligned = {}
    for c in cells:
        aligned[c["family"]] = c["oos_returns"].loc[common_start:common_end].reindex(common_dates)

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


def test_per_family_cpcv_cell_runs():
    """Each family's best-nominal cell runs under CPCV and yields usable OOS returns."""
    aligned = _collect_aligned_returns()
    for c in aligned["cells"]:
        fam = c["family"]
        assert c["n_folds"] == N_SPLITS, f"{fam}: expected {N_SPLITS} CPCV folds"
        assert c["folds_with_position"] >= 1, (
            f"{fam}: no fold took a position under CPCV (purge={PURGE_SIZE}, embargo={EMBARGO_SIZE})"
        )
        p = c["dsr_p"]
        assert 0.0 <= float(p) <= 1.0, f"{fam}: DSR p-value out of range: {p!r}"
    print(f"CPCV cross-family (5): all {len(aligned['cells'])} family cells ran under "
          f"purge={PURGE_SIZE}, embargo={EMBARGO_SIZE}, n_splits={N_SPLITS}, test_size={TEST_SIZE}")


def test_aligned_sample_size():
    """Verify the aligned CPCV sample has K=5 strategies and a usable T."""
    aligned = _collect_aligned_returns()
    n_obs = aligned["n_obs"]
    assert n_obs >= 50, f"aligned CPCV sample too small: T={n_obs}"
    assert aligned["n_strategies"] == 5
    _assert_close(n_obs, PINNED_N_OBS, "aligned CPCV n_obs")
    print(f"CPCV cross-family (5): aligned sample size n_obs = {n_obs}")


def test_reality_check_test():
    """Reality Check Test on the aligned 5-family CPCV performance matrix.
    Pre-registered criterion: p-value < 0.10 (family-wise). Expect NOT SUPPORTED."""
    aligned = _collect_aligned_returns()
    res = reality_check_test(
        performance=aligned["performance"],
        benchmark=aligned["benchmark"],
        n_bootstrap=N_BOOTSTRAP,
        seed=SEED,
        studentize=True,
        alpha=ALPHA,
    )

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

    best_fam = aligned["families"][res["best_index"]]
    print(f"Reality Check (5 families, CPCV purge={PURGE_SIZE}/embargo={EMBARGO_SIZE}): "
          f"best = {best_fam} (stat = {res['test_statistic']:.4f}, p = {res['p_value']:.4f})")
    print(f"  Family-wise verdict at alpha={ALPHA}: "
          f"{'SUPPORTED' if res['significant'] else 'NOT SUPPORTED'}")
    print(f"  Mean excess per strategy (daily): "
          f"{', '.join(f'{f}={m:.6f}' for f, m in zip(aligned['families'], res['means']))}")

    # Pre-registered falsification criterion: NOT SUPPORTED at family-wise level.
    assert not res["significant"], (
        f"Reality Check (CPCV): p-value {res['p_value']:.4f} should exceed {ALPHA} "
        f"(NOT SUPPORTED at family-wise level)"
    )


def test_romano_wolf_stepdown():
    """Romano-Wolf stepdown on the aligned 5-family CPCV performance matrix.
    Pre-registered criterion: n_rejected > 0 at alpha = 0.10. Expect n_rejected = 0."""
    aligned = _collect_aligned_returns()
    res = romano_wolf_stepdown(
        performance=aligned["performance"],
        benchmark=aligned["benchmark"],
        n_bootstrap=N_BOOTSTRAP,
        seed=SEED,
        studentize=True,
        alpha=ALPHA,
    )

    assert res["ordered_indices"] == PINNED_RW["ordered_indices"], (
        f"RW ordered_indices: got {res['ordered_indices']}, expected {PINNED_RW['ordered_indices']}"
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

    ordered_fams = [aligned["families"][i] for i in res["ordered_indices"]]
    print(f"Romano-Wolf Stepdown (5 families, CPCV, alpha={ALPHA}):")
    print(f"  Ordered by studentized stat: "
          f"{', '.join(f'{f}={s:.4f}' for f, s in zip(ordered_fams, res['statistics']))}")
    print(f"  n_rejected = {res['n_rejected']}")
    print(f"  Simultaneous 90% max-t CIs (all contain zero):")
    for f, lo, hi in zip(ordered_fams, res["simultaneous_ci_lower"], res["simultaneous_ci_upper"]):
        print(f"    {f}: [{lo:.6f}, {hi:.6f}]")
    if res["simultaneous_ci_small_sample_warning"]:
        print(f"  Warning: {res['simultaneous_ci_small_sample_warning']}")

    # Pre-registered falsification criterion: n_rejected == 0 at alpha=0.10.
    assert res["n_rejected"] == 0, (
        f"Romano-Wolf (CPCV): expected n_rejected = 0 at alpha={ALPHA}, got {res['n_rejected']}"
    )


def test_overall_verdict_not_supported():
    """Aggregate verdict: both family-wise tests conclude NOT SUPPORTED under CPCV,
    matching the walk-forward 5-family verdict (RC p = 0.1630, RW n_rejected = 0)."""
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
    assert not rc["significant"], "Reality Check (CPCV) should not reject at alpha=0.10"
    assert rw["n_rejected"] == 0, "Romano-Wolf (CPCV) should reject 0 strategies at alpha=0.10"
    print(f"Overall 5-family CPCV verdict (Reality Check + Romano-Wolf): NOT SUPPORTED")
    print(f"  Reality Check p-value: {rc['p_value']:.4f} (threshold {ALPHA})")
    print(f"  Romano-Wolf n_rejected: {rw['n_rejected']} (threshold > 0)")
    print(f"  Verdict stable vs walk-forward (RC p = 0.1630, RW n_rejected = 0): "
          f"{'YES' if (not rc['significant'] and rw['n_rejected'] == 0) else 'NO'}")


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
    ("per_family_cpcv_cell_runs", test_per_family_cpcv_cell_runs),
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
