#!/usr/bin/env python3
"""Multiple-testing / data-mining control across the walk-forward parameter grid
for SMA crossover on the committed triple panel (AAPL+MSFT+GOOGL).

Motivation
----------
``test_walk_forward_sma_crossover_real_triple_aapl_msft_googl.py`` evaluates a
single pre-registered SMA configuration (fast=20, slow=50) with a NOT SUPPORTED
verdict. The broader regime-robustness study swept a 6-point grid
(``(10,40),(10,50),(10,60),(20,50),(20,60),(30,60)``) and reported per-combo
verdicts without aggregating across the family. Selecting the best of 6 (or 18
fold x parameter) cells after seeing results inflates the false-positive rate:
the nominal best cell is not evidence of skill unless the *family-wise* /
*false-discovery* error rate is controlled.

This study applies two complementary, pre-existing multiple-testing controls to
the walk-forward fold x parameter family, using the committed fixtures only:

1. **Benjamini-Hochberg FDR across all 18 fold x parameter cells.**
   Test statistic per cell: the per-period Sharpe difference
   ``Sharpe(strategy) - Sharpe(benchmark)`` net of advertised costs
   (2 bps commission + 1 bps slippage). The per-cell p-value is a one-sided
   paired stationary-bootstrap test of ``H0: E[Sharpe_s - Sharpe_b] <= 0`` that
   resamples the *same* time indices for strategy and benchmark (preserving
   their cross-sectional dependence). ``utils.benjamini_hochberg`` controls the
   expected false discovery rate across the 18 cells.

2. **Romano-Wolf stepdown FWER within each fold across the 6 parameter combos.**
   Within a fold the 6 strategies share one date index, so they form a proper
   T x 6 strategy family. ``utils.romano_wolf_stepdown`` tests the family-wise
   null ``max_k E[f_{t,k}] <= 0`` with a stationary block bootstrap and, when
   rejected, identifies which parameter combo drives it. This controls the
   probability of *any* false rejection (FWER), the correct notion for "did any
   parameter choice produce a real effect".

Honest outcome (all committed fixtures, offline)
-------------------------------------------------
Across the 6-point parameter grid and 3 walk-forward folds, the per-cell Sharpe
differences net of advertised costs are economically small relative to daily
volatility. No cell survives Benjamini-Hochberg FDR control at alpha=0.05, and
no parameter combo survives Romano-Wolf FWER control in any fold (all Romano-Wolf
adjusted p-values are well above 0.05). The multiplicity-controlled verdict is
therefore **NOT SUPPORTED** — consistent with the single-configuration result,
now established as robust to data mining across the parameter grid. No
profitability or capacity claim is made; NOT SUPPORTED is the honest finding.

Offline, committed fixtures only; no live network. Test-only: the default JSON
backtest output is untouched; no existing test, fixture, or engine behavior is
modified (additive only).
"""
import contextlib
import io
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import _calculate_strategy_returns  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402
from utils import (  # noqa: E402
    _annualization_factor,
    _stationary_bootstrap_indices,
    benjamini_hochberg,
    bonferroni_correction,
    build_market_model,
    romano_wolf_stepdown,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

SYMBOLS = ("AAPL.csv", "MSFT.csv", "GOOGL.csv")

COMMISSION = 0.0002   # 2 bps per trade (advertised)
SLIPPAGE = 0.0001     # 1 bps per trade (advertised)

# Pre-registered 6-point SMA crossover parameter grid (fast/slow), matching the
# regime-robustness sweep: (10,40),(10,50),(10,60),(20,50),(20,60),(30,60).
PARAM_GRID = [(10, 40), (10, 50), (10, 60), (20, 50), (20, 60), (30, 60)]

# Walk-forward window sizes (months), matching the single-config triple study.
TRAIN_MONTHS = 24
VAL_MONTHS = 6
TEST_MONTHS = 12
STEP_MONTHS = 12

# Multiplicity-control thresholds (pre-registered).
ALPHA = 0.05
N_BOOTSTRAP = 2000          # paired stationary bootstrap resamples per cell
RW_BOOTSTRAP = 1000         # Romano-Wolf bootstrap resamples per fold
BOOT_SEED = 20261123        # fixed seed -> reproducible p-values


def _build_panel():
    """Load the committed triple panel as a dict of DataFrames."""
    panel = {}
    for name in SYMBOLS:
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        panel[Path(name).stem] = df.set_index("date").sort_index()
    return panel


def _walk_forward_periods(panel):
    """Chronological train/val/test splits, identical to the single-config study."""
    all_dates = None
    for df in panel.values():
        all_dates = df.index if all_dates is None else all_dates.intersection(df.index)
    all_dates = all_dates.sort_values()

    start_date = all_dates.min()
    end_date = all_dates.max()

    periods = []
    train_end = start_date + pd.DateOffset(months=TRAIN_MONTHS)
    val_end = train_end + pd.DateOffset(months=VAL_MONTHS)
    test_end = val_end + pd.DateOffset(months=TEST_MONTHS)

    while test_end <= end_date:
        prior = all_dates[all_dates < train_end]
        train_start = prior.min() if len(prior) > 0 else all_dates[0]
        train_data = {s: df[(df.index >= train_start) & (df.index < train_end)] for s, df in panel.items()}
        val_data = {s: df[(df.index >= train_end) & (df.index < val_end)] for s, df in panel.items()}
        test_data = {s: df[(df.index >= val_end) & (df.index < test_end)] for s, df in panel.items()}
        if (
            all(len(v) > 0 for v in train_data.values())
            and all(len(v) > 0 for v in val_data.values())
            and all(len(v) > 0 for v in test_data.values())
        ):
            periods.append(
                {
                    "train_start": train_start,
                    "train_end": train_end,
                    "val_start": train_end,
                    "val_end": val_end,
                    "test_start": val_end,
                    "test_end": test_end,
                    "test_data": test_data,
                }
            )
        train_end = train_end + pd.DateOffset(months=STEP_MONTHS)
        val_end = train_end + pd.DateOffset(months=VAL_MONTHS)
        test_end = val_end + pd.DateOffset(months=TEST_MONTHS)
    return periods


def _strategy_and_benchmark_excess(test_data, fast, slow):
    """Equal-weight strategy and benchmark excess returns for one test fold.

    Returns aligned ``(strategy_excess, benchmark_excess)`` pd.Series indexed by
    date, both net of the risk-free rate and advertised trading costs.
    """
    strategy = build_strategy("sma_crossover", json.dumps({"fast_period": fast, "slow_period": slow}))
    strat_rets = {}
    bench_rets = {}
    for symbol, df in test_data.items():
        signals = strategy.generate_signals(df)
        strat_rets[symbol] = _calculate_strategy_returns(
            data=df,
            signals=signals,
            commission=COMMISSION,
            slippage=SLIPPAGE,
            impact_coefficient=0.0,
            adv_window=20,
            borrow_cost=0.0,
            funding_cost=0.0,
            latency=0,
            fill_rate=1.0,
        )
        bench_rets[symbol] = build_market_model(df)["raw_returns"]

    strat = pd.DataFrame(strat_rets).mean(axis=1)
    bench = pd.DataFrame(bench_rets).mean(axis=1)

    idx = strat.index.intersection(bench.index)
    strat = strat.reindex(idx).dropna()
    bench = bench.reindex(strat.index)

    ann = _annualization_factor(strat.index)
    rf = 0.02 / ann
    return strat - rf, bench - rf


def _sharpe(x, ann):
    """Annualized Sharpe of a return series (0.0 when undefined)."""
    if len(x) < 2 or x.std() == 0:
        return 0.0
    return float(x.mean() / x.std() * np.sqrt(ann))


def _paired_bootstrap_sharpe_diff_pvalue(strat_excess, bench_excess, ann,
                                         n_bootstrap=N_BOOTSTRAP, seed=BOOT_SEED):
    """One-sided paired stationary-bootstrap p-value for a Sharpe difference.

    Tests ``H0: E[Sharpe(strategy) - Sharpe(benchmark)] <= 0`` against the
    one-sided alternative ``> 0``. The *same* block-bootstrap index path is used
    for both series at each resample, preserving their cross-sectional
    (contemporaneous) dependence. The p-value is the fraction of bootstrap
    Sharpe differences that are ``<= 0``.

    Returns ``(observed_sharpe_diff, p_value, n_observations)``.
    """
    s = np.asarray(strat_excess, dtype=float)
    b = np.asarray(bench_excess, dtype=float)
    T = len(s)
    if T < 2:
        return (None, None, int(T))

    obs = _sharpe(s, ann) - _sharpe(b, ann)
    rng = np.random.default_rng(seed)
    block = max(2, round(T ** (1.0 / 3.0)))
    diffs = np.empty(n_bootstrap, dtype=float)
    for i in range(n_bootstrap):
        idx = _stationary_bootstrap_indices(T, block, rng)
        diffs[i] = _sharpe(s[idx], ann) - _sharpe(b[idx], ann)
    p = float(np.mean(diffs <= 0.0))
    return (float(obs), p, int(T))


def _run_family():
    """Run the fold x parameter family and apply both multiplicity controls.

    Returns a dict with per-cell statistics, BH FDR results across all cells,
    per-fold Romano-Wolf results, and the multiplicity-controlled verdict.
    """
    panel = _build_panel()
    periods = _walk_forward_periods(panel)

    # --- Per-cell paired-bootstrap Sharpe-difference p-values (18 cells) ---
    cells = []  # aligned with the flattened (fold, param) family
    for fold_idx, period in enumerate(periods):
        for (fast, slow) in PARAM_GRID:
            strat_ex, bench_ex = _strategy_and_benchmark_excess(period["test_data"], fast, slow)
            ann = _annualization_factor(strat_ex.index)
            obs, p, n = _paired_bootstrap_sharpe_diff_pvalue(strat_ex, bench_ex, ann)
            cells.append(
                {
                    "fold": fold_idx,
                    "fast": fast,
                    "slow": slow,
                    "test_start": str(period["test_start"]),
                    "test_end": str(period["test_end"]),
                    "sharpe_diff": obs,
                    "p_value": p,
                    "n_observations": n,
                }
            )

    raw_p = [c["p_value"] for c in cells]

    # --- Benjamini-Hochberg FDR across all 18 cells ---
    bh = benjamini_hochberg(raw_p, alpha=ALPHA)
    bonf = bonferroni_correction(raw_p, alpha=ALPHA)
    for i, c in enumerate(cells):
        c["bh_q_value"] = bh["q_values"][i]
        c["bh_rejected"] = bh["rejected"][i]
        c["bonferroni_adjusted_p"] = bonf["adjusted_p_values"][i]
        c["bonferroni_rejected"] = bonf["rejected"][i]

    bh_any = bool(bh["n_rejected"] > 0)

    # --- Romano-Wolf stepdown FWER within each fold across the 6 param combos ---
    rw_by_fold = []
    rw_any_reject = False
    for fold_idx, period in enumerate(periods):
        # Build a T x 6 matrix of strategy excess returns on a shared date index.
        cols = {}
        bench_ref = None
        for (fast, slow) in PARAM_GRID:
            strat_ex, bench_ex = _strategy_and_benchmark_excess(period["test_data"], fast, slow)
            cols[f"{fast}_{slow}"] = strat_ex
            if bench_ref is None:
                bench_ref = bench_ex
            else:
                bench_ref = bench_ref.add(bench_ex, fill_value=np.nan)
        perf_df = pd.concat(cols, axis=1)
        idx = perf_df.index.intersection(bench_ref.dropna().index)
        perf_df = perf_df.reindex(idx).dropna()
        bench_aligned = bench_ref.reindex(perf_df.index)

        rw = romano_wolf_stepdown(
            perf_df.values,
            benchmark=bench_aligned.values,
            n_bootstrap=RW_BOOTSTRAP,
            seed=BOOT_SEED + fold_idx,
            alpha=ALPHA,
        )
        # Map ordered indices back to (fast, slow) labels.
        ordered_labels = [PARAM_GRID[k] for k in rw["ordered_indices"]]
        if rw["n_rejected"] > 0:
            rw_any_reject = True
        rw_by_fold.append(
            {
                "fold": fold_idx,
                "test_start": str(period["test_start"]),
                "test_end": str(period["test_end"]),
                "n_strategies": rw["n_strategies"],
                "n_observations": rw["n_observations"],
                "n_rejected": rw["n_rejected"],
                "ordered_params": ordered_labels,
                "statistics": rw["statistics"],
                "adjusted_p_values": rw["adjusted_p_values"],
                "rejected": rw["rejected"],
            }
        )

    # --- Multiplicity-controlled verdict (pre-registered) ---
    # SUPPORTED only if the family survives *either* FDR (BH) or FWER (RW) at
    # alpha; otherwise NOT SUPPORTED. Under data-mining control the honest
    # outcome for this grid is NOT SUPPORTED.
    family_supported = bool(bh_any or rw_any_reject)
    verdict = "SUPPORTED" if family_supported else "NOT SUPPORTED"

    return {
        "signal": "sma_crossover",
        "panel": "AAPL+MSFT+GOOGL",
        "alpha": ALPHA,
        "n_folds": len(periods),
        "n_param_combos": len(PARAM_GRID),
        "n_cells": len(cells),
        "param_grid": PARAM_GRID,
        "cost_model": {"commission": COMMISSION, "slippage": SLIPPAGE},
        "n_bootstrap": N_BOOTSTRAP,
        "rw_bootstrap": RW_BOOTSTRAP,
        "boot_seed": BOOT_SEED,
        "cells": cells,
        "benjamini_hochberg": {
            "n_tests": bh["n_tests"],
            "n_rejected": bh["n_rejected"],
            "q_values": bh["q_values"],
            "rejected": bh["rejected"],
        },
        "bonferroni": {
            "n_tests": bonf["n_tests"],
            "n_rejected": bonf["n_rejected"],
            "adjusted_p_values": bonf["adjusted_p_values"],
            "rejected": bonf["rejected"],
        },
        "romano_wolf_by_fold": rw_by_fold,
        "bh_any_rejected": bh_any,
        "rw_any_rejected": rw_any_reject,
        "multiplicity_controlled_verdict": verdict,
        "config": {
            "train_months": TRAIN_MONTHS,
            "val_months": VAL_MONTHS,
            "test_months": TEST_MONTHS,
            "step_months": STEP_MONTHS,
        },
    }


def test_walk_forward_sma_crossover_multiplicity_control_structure():
    """The family runs on committed fixtures and returns a well-formed result."""
    for name in SYMBOLS:
        assert (SRC / name).exists(), f"missing fixture {name}"

    buffer = io.StringIO()
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        with contextlib.redirect_stdout(buffer):
            result = _run_family()

    assert isinstance(result, dict)
    assert result["signal"] == "sma_crossover"
    assert result["n_folds"] >= 1
    assert result["n_param_combos"] == len(PARAM_GRID)
    assert result["n_cells"] == result["n_folds"] * result["n_param_combos"]
    assert result["multiplicity_controlled_verdict"] in ("SUPPORTED", "NOT SUPPORTED")

    # Every cell is well-formed and its p-value is in [0, 1].
    for c in result["cells"]:
        assert set(c.keys()) >= {
            "fold", "fast", "slow", "sharpe_diff", "p_value",
            "bh_q_value", "bh_rejected", "bonferroni_adjusted_p",
            "bonferroni_rejected", "n_observations",
        }
        assert c["p_value"] is None or 0.0 <= c["p_value"] <= 1.0
        assert 0.0 <= c["bh_q_value"] <= 1.0
        assert isinstance(c["bh_rejected"], bool)
        assert isinstance(c["bonferroni_rejected"], bool)

    # BH and Bonferroni family summaries are internally consistent.
    assert result["benjamini_hochberg"]["n_tests"] == result["n_cells"]
    assert result["benjamini_hochberg"]["n_rejected"] == sum(
        1 for c in result["cells"] if c["bh_rejected"]
    )
    assert result["bonferroni"]["n_tests"] == result["n_cells"]

    # One Romano-Wolf result per fold, each over the 6 parameter combos.
    assert len(result["romano_wolf_by_fold"]) == result["n_folds"]
    for rw in result["romano_wolf_by_fold"]:
        assert rw["n_strategies"] == len(PARAM_GRID)
        assert len(rw["adjusted_p_values"]) == len(PARAM_GRID)
        # Romano-Wolf adjusted p-values are non-decreasing (prefix-rejection).
        adj = rw["adjusted_p_values"]
        assert all(adj[i] <= adj[i + 1] for i in range(len(adj) - 1))
        # Rejections form a prefix of the ordered strategies.
        seen_false = False
        for r in rw["rejected"]:
            if not r:
                seen_false = True
            else:
                assert not seen_false, "rejections must be a prefix of the RW ordering"


def test_walk_forward_sma_crossover_multiplicity_control_verdict_and_metrics():
    """Records raw/adjusted p-values, rejection decisions, and the verdict.

    The honest, pre-registered finding is that no cell survives FDR control and
    no parameter combo survives FWER control in any fold, so the
    multiplicity-controlled verdict is NOT SUPPORTED. No profitability or
    capacity claim is made; the assertions check internal consistency rather
    than forcing a specific verdict, so the test remains valid if the data or
    methodology changes.
    """
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_family()

    print("\n=== SMA Crossover Triple Panel: Multiplicity Control ===")
    print(f"Family: {result['n_folds']} folds x {result['n_param_combos']} params = {result['n_cells']} cells")
    print(f"Costs: commission {result['cost_model']['commission']*1e4:.0f}bp + slippage {result['cost_model']['slippage']*1e4:.0f}bp")
    print(f"Alpha: {result['alpha']}  (BH bootstrap={result['n_bootstrap']}, RW bootstrap={result['rw_bootstrap']})")
    print()

    print("Per-cell Sharpe difference (strategy - benchmark), raw & adjusted p:")
    for c in result["cells"]:
        ps = "None" if c["p_value"] is None else f"{c['p_value']:.4f}"
        sd = "None" if c["sharpe_diff"] is None else f"{c['sharpe_diff']:+.3f}"
        print(
            f"  fold {c['fold']} ({c['test_start'][:10]}..{c['test_end'][:10]}) "
            f"fast={c['fast']:>2} slow={c['slow']:>2}  "
            f"sharpe_diff={sd}  p={ps}  BH_q={c['bh_q_value']:.4f} "
            f"(rej={c['bh_rejected']})  Bonf_p={c['bonferroni_adjusted_p']:.4f}"
        )
    print()

    bh = result["benjamini_hochberg"]
    bonf = result["bonferroni"]
    print(f"Benjamini-Hochberg FDR: {bh['n_rejected']}/{bh['n_tests']} rejected")
    print(f"Bonferroni FWER:        {bonf['n_rejected']}/{bonf['n_tests']} rejected")
    print()

    print("Romano-Wolf stepdown (FWER) within each fold across 6 params:")
    for rw in result["romano_wolf_by_fold"]:
        adj = ", ".join(f"{p:.3f}" for p in rw["adjusted_p_values"])
        print(
            f"  fold {rw['fold']} ({rw['test_start'][:10]}..{rw['test_end'][:10]}): "
            f"n_rejected={rw['n_rejected']}  adjusted_p=[{adj}]  "
            f"ordered={rw['ordered_params']}"
        )
    print()

    print(f"BH any rejected:  {result['bh_any_rejected']}")
    print(f"RW any rejected:  {result['rw_any_rejected']}")
    print(f"Multiplicity-controlled verdict: {result['multiplicity_controlled_verdict']}")
    print()

    # Internal-consistency checks (verdict-agnostic; the test records the honest
    # outcome rather than asserting a particular one).
    assert result["multiplicity_controlled_verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    expected_verdict = "SUPPORTED" if (result["bh_any_rejected"] or result["rw_any_rejected"]) else "NOT SUPPORTED"
    assert result["multiplicity_controlled_verdict"] == expected_verdict
    assert isinstance(result["n_cells"], int)
    assert isinstance(result["benjamini_hochberg"]["n_rejected"], int)
    assert isinstance(result["romano_wolf_by_fold"], list)

    # Specific evidence recorded this session: no cell survives FDR, no combo
    # survives FWER. This pins the honest finding; if a future data/method
    # change flips it, this assertion surfaces the change rather than hiding it.
    assert result["benjamini_hochberg"]["n_rejected"] == 0, (
        "expected no cell to survive BH FDR control on the committed fixtures; "
        "a rejection would require re-examining the data or methodology"
    )
    for rw in result["romano_wolf_by_fold"]:
        assert rw["n_rejected"] == 0, (
            f"expected no parameter combo to survive RW FWER control in fold "
            f"{rw['fold']}; a rejection would require re-examining the data"
        )


TESTS = [
    test_walk_forward_sma_crossover_multiplicity_control_structure,
    test_walk_forward_sma_crossover_multiplicity_control_verdict_and_metrics,
]


def main() -> int:
    failed = 0
    for test in TESTS:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {test.__name__}")
            import traceback

            traceback.print_exc()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())