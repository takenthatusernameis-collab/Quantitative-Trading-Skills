#!/usr/bin/env python3
"""Walk-forward *protocol-sensitivity* study for SMA crossover on the committed
AAPL/MSFT/GOOGL triple panel.

Motivation
----------
The existing walk-forward SMA crossover test pins a *single* evaluation
protocol (train 24 / validation 6 / test 12 months, stepping 12 months) with a
pre-registered single configuration (fast=20, slow=50) and records a NOT
SUPPORTED verdict from it. A single protocol cannot distinguish "the strategy
has no edge" from "the evaluation window was unlucky": the train/test window
lengths are an analyst degree of freedom, and choosing among them after seeing
results is a form of data mining (protocol-selection bias). This study
quantifies that sensitivity for SMA crossover.

Because SMA crossover is a per-asset long-only trend strategy whose
``generate_signals`` operates on a single-asset frame (not a panel), each cell
runs ``walk_forward_analysis`` per asset on committed fixtures and pools the
per-asset out-of-sample returns into an equal-weight portfolio -- the same
per-asset-then-equal-weight construction the existing single-protocol SMA
walk-forward test uses.

Design (pre-registered before any number is inspected)
------------------------------------------------------
* Signal: ``sma_crossover`` (long when fast SMA > slow SMA, flat otherwise),
  per-asset long-only trend on the committed three-asset panel
  (AAPL / MSFT / GOOGL).
* Parameter grid: ``{"fast_period": [20], "slow_period": [50]}`` (1
  configuration, the same grid the existing single-protocol test uses).
* Costs: commission 2 bps + slippage 1 bps per trade (the shipped default).
* Deflated Sharpe Ratio multiple-testing correction is applied *within* each
  protocol (across the single configuration and all walk-forward periods,
  pooled across the 3 assets).
* Protocols vary ``train_months`` and ``test_months`` with ``step_months ==
  test_months`` (the framework rejects ``step_months < test_months``). One
  pre-registered family of equally-valid 12-month-test protocols:
  (24, 12, 12), (36, 12, 12), (18, 12, 12), (30, 12, 12).
* Pre-registered per-cell falsification criteria: OOS Sharpe > 0 AND OOS total
  return > 0 AND Deflated Sharpe p-value < 0.10.

Honest finding (all committed fixtures, offline)
------------------------------------------------
The OOS verdict is consistent across the four equally-valid protocols: the raw
OOS Sharpe is positive in every cell (0.0363 / 1.0848 / 0.2336 / 0.7025) and
the total OOS return is positive in every cell, yet the Deflated Sharpe
p-value exceeds 0.10 in every cell (0.9365 / 0.1582 / 0.825 / 0.302), so
*no cell passes all three pre-registered criteria* and the verdict is
consistently NOT SUPPORTED. The best nominal cell, (36, 12, 12) (DSR p =
0.1582), does not survive a Bonferroni correction across the four protocols
(adjusted p ~ 0.63 > 0.10).

Conclusion: the positive raw out-of-sample Sharpe is not robust to
multiple-testing correction under any of the four equally-valid protocols, and
no protocol-selection bias can rescue it. A single protocol cannot establish a
SMA crossover verdict; any future SUPPORT/NOT-SUPPORT claim must be
pre-registered on held-out data not used to select the protocol. This study
exists to make that limitation explicit and regression-guarded.

Offline, committed fixtures only; no live network. Test-only: the default JSON
backtest output is untouched.
"""
import contextlib
import io
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import walk_forward_analysis, deflated_sharpe_ratio  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402
from utils import _annualization_factor, bonferroni_correction  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

SYMBOLS = ("AAPL", "MSFT", "GOOGL")

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade
PARAM_GRID = {
    "fast_period": [20],
    "slow_period": [50],
}
DSR_PVALUE_THRESHOLD = 0.10

# Informative protocols: 12-month test windows.
INFORMATIVE_PROTOCOLS = [(24, 12, 12), (36, 12, 12), (18, 12, 12), (30, 12, 12)]
ALL_PROTOCOLS = INFORMATIVE_PROTOCOLS

# A cell is "informative" when the portfolio actually held a position for at
# least this many walk-forward periods; below it the OOS record is flat /
# undefined and cannot falsify the hypothesis.
MIN_INFORMATIVE_PERIODS = 2

# Pinned evidence matrix. Values are rounded to 4 decimals for readability and
# compared with ABS_TOL (see _assert_close). This is a regression guard on the
# study's observed results, not a profitability claim.
ABS_TOL = 1e-3

# key: (train_months, test_months, step_months)
# value: dict(n_periods, n_pos, sharpe, tot, dsr_p, n_trials)
# n_trials is the number of configurations the pool-level DSR corrected for
# (3 assets x n_periods configurations, one per asset per period).
EXPECTED = {
    # --- Informative 12-month-test cells ---
    (24, 12, 12): dict(n_periods=3, n_pos=3, sharpe=0.0363, tot=0.0463, dsr_p=0.9365, n_trials=9),
    (36, 12, 12): dict(n_periods=2, n_pos=2, sharpe=1.0848, tot=0.3726, dsr_p=0.1582, n_trials=6),
    (18, 12, 12): dict(n_periods=4, n_pos=4, sharpe=0.2336, tot=0.1800, dsr_p=0.8250, n_trials=12),
    (30, 12, 12): dict(n_periods=3, n_pos=3, sharpe=0.7025, tot=0.3496, dsr_p=0.3020, n_trials=9),
}

# Best nominal cell by raw DSR p-value (pre-registered index for the
# Bonferroni check).
BEST_NOMINAL_PROTOCOL = (36, 12, 12)


def _build_data(symbol):
    df = pd.read_csv(SRC / f"{symbol}.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _factory(params):
    return build_strategy("sma_crossover", json.dumps(params))


def _run_asset_cell(symbol, protocol):
    """Run one asset's walk-forward cell for one protocol; assert PIT engaged."""
    train_months, test_months, step_months = protocol
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = walk_forward_analysis(
            data=_build_data(symbol),
            strategy_factory=_factory,
            param_grid=PARAM_GRID,
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
        f"{symbol} {protocol}: point-in-time validation not engaged"
    )
    return result


def _run_cell(protocol):
    """Run one protocol walk-forward cell on the triple panel.

    Each asset is evaluated independently (SMA crossover is per-asset), and the
    per-period out-of-sample returns are pooled into an equal-weight portfolio.
    Returns the cell summary: n_periods, periods_with_position, oos_sharpe,
    total_oos_return, deflated_sharpe p-value / n_trials.
    """
    train_months, test_months, step_months = protocol
    asset_results = {sym: _run_asset_cell(sym, protocol) for sym in SYMBOLS}

    # All assets share identical period dates under one protocol, so periods
    # line up by position across assets.
    periods = [
        p for p in asset_results[SYMBOLS[0]]["periods"]
        if p.get("test_returns") is not None and len(p["test_returns"]) > 0
    ]
    n_periods = len(periods)

    portfolio_rets = []
    trial_sharpes = []
    periods_with_position = 0
    for i, period in enumerate(periods):
        rets = []
        for sym in SYMBOLS:
            p = asset_results[sym]["periods"][i]
            tr = p.get("test_returns")
            if tr is not None and len(tr) > 0:
                rets.append(tr)
            trial_sharpes.extend(p.get("trial_sharpes") or [])
        if len(rets) == len(SYMBOLS):
            portfolio_rets.append(pd.concat(rets, axis=1).mean(axis=1))
            periods_with_position += 1

    oos_returns = pd.concat(portfolio_rets) if portfolio_rets else pd.Series(dtype=float)
    ann = _annualization_factor(oos_returns.index) if len(oos_returns) > 0 else 252.0
    excess = oos_returns - 0.02 / ann
    if len(oos_returns) > 1 and excess.std() > 0:
        oos_sharpe = float(excess.mean() / excess.std() * np.sqrt(ann))
    else:
        oos_sharpe = None
    total_oos_return = float((1 + oos_returns).prod() - 1) if len(oos_returns) > 0 else None

    n_trials = len(trial_sharpes)
    if len(oos_returns) >= 2 and n_trials >= 1:
        dsr = deflated_sharpe_ratio(
            sharpe_ratio=oos_sharpe if oos_sharpe is not None else 0.0,
            returns=oos_returns,
            n_trials=n_trials,
            trial_sharpes=trial_sharpes,
        )
        dsr_p = dsr.get("p_value")
    else:
        dsr_p = None

    return {
        "n_periods": n_periods,
        "periods_with_position": periods_with_position,
        "oos_sharpe": oos_sharpe,
        "total_oos_return": total_oos_return,
        "dsr_p": dsr_p,
        "n_trials": n_trials,
        "n_observations": int(len(oos_returns)),
    }


def _criteria(cell):
    """Pre-registered per-cell criteria -> dict of booleans (NaN-safe)."""
    sharpe = cell.get("oos_sharpe")
    tot = cell.get("total_oos_return")
    p = cell.get("dsr_p")
    return {
        "oos_sharpe_gt_zero": bool(
            sharpe is not None and math.isfinite(sharpe) and sharpe > 0
        ),
        "oos_total_return_positive": bool(
            tot is not None and math.isfinite(tot) and tot > 0
        ),
        "deflated_sharpe_pvalue_lt_0.10": bool(
            p is not None and math.isfinite(p) and float(p) < DSR_PVALUE_THRESHOLD
        ),
    }


def _assert_close(got, exp, label):
    assert got is not None, f"{label}: missing value (expected ~{exp})"
    assert abs(float(got) - float(exp)) <= ABS_TOL, (
        f"{label}: got {got!r}, expected ~{exp} (abs tol {ABS_TOL})"
    )


def test_protocol_sensitivity_matrix_pinned():
    """Regression guard + structural validity for the full protocol matrix.

    Every cell must produce finite OOS metrics and the pinned number of
    walk-forward periods / positions. Point-in-time validation is asserted
    engaged inside _run_asset_cell.
    """
    for protocol in ALL_PROTOCOLS:
        cell = _run_cell(protocol)
        exp = EXPECTED[protocol]

        assert cell["n_periods"] == exp["n_periods"], (
            f"{protocol}: n_periods {cell['n_periods']} != {exp['n_periods']}"
        )
        assert cell["periods_with_position"] == exp["n_pos"], (
            f"{protocol}: periods_with_position "
            f"{cell['periods_with_position']} != {exp['n_pos']}"
        )
        assert cell["periods_with_position"] >= MIN_INFORMATIVE_PERIODS, (
            f"{protocol}: cell not informative, periods_with_position="
            f"{cell['periods_with_position']}"
        )

        _assert_close(cell.get("oos_sharpe"), exp["sharpe"], f"{protocol} oos_sharpe")
        _assert_close(cell.get("total_oos_return"), exp["tot"], f"{protocol} total_oos_return")
        _assert_close(cell.get("dsr_p"), exp["dsr_p"], f"{protocol} deflated_sharpe.p_value")
        assert cell["n_trials"] == exp["n_trials"], (
            f"{protocol}: DSR n_trials {cell['n_trials']} != {exp['n_trials']}"
        )
        p = cell.get("dsr_p")
        assert p is not None and 0.0 <= float(p) <= 1.0, (
            f"{protocol}: DSR p-value out of range: {p!r}"
        )


def test_verdict_is_consistently_not_supported():
    """Core finding: the raw OOS Sharpe and total return are positive under
    every equally-valid protocol, yet the Deflated Sharpe p-value exceeds 0.10
    in every cell, so no cell passes all three pre-registered criteria and the
    verdict is consistently NOT SUPPORTED. The pinned 24/12/12 baseline
    therefore fails, matching the single-protocol test's NOT SUPPORTED verdict.

    This shows SMA crossover cannot be rescued by protocol selection here: the
    positive raw Sharpe never survives multiple-testing correction.
    """
    baseline_pass = None
    passing_cells = []

    for protocol in INFORMATIVE_PROTOCOLS:
        cell = _run_cell(protocol)
        crit = _criteria(cell)
        if protocol == (24, 12, 12):
            baseline_pass = all(crit.values())
        if all(crit.values()):
            passing_cells.append(protocol)

    # Every cell passes Sharpe > 0 and return > 0 but fails DSR p < 0.10.
    for protocol in INFORMATIVE_PROTOCOLS:
        crit = _criteria(_run_cell(protocol))
        assert crit["oos_sharpe_gt_zero"] is True, f"{protocol}: OOS Sharpe not > 0"
        assert crit["oos_total_return_positive"] is True, f"{protocol}: OOS return not > 0"
        assert crit["deflated_sharpe_pvalue_lt_0.10"] is False, (
            f"{protocol}: DSR p-value unexpectedly < 0.10"
        )

    # The pinned 24/12/12 baseline fails all criteria.
    assert baseline_pass is False, (
        f"baseline (24,12,12) unexpectedly passes: {baseline_pass}"
    )

    # No informative cell passes all three pre-registered criteria.
    assert passing_cells == [], (
        f"expected zero passing informative cells, got {passing_cells}"
    )


def test_no_cell_survives_protocol_multiplicity():
    """No nominal pass survives correction for the number of protocols.

    The DSR inside each cell corrects for the 1 configuration only (pooled
    across 3 assets and all periods); it does not correct for the 4 protocols
    tried. A Bonferroni correction across the protocol family pushes the best
    nominal cell's p-value well above 0.10.
    """
    dsr_p_values = []
    best_idx = None
    best_p = None
    for i, protocol in enumerate(INFORMATIVE_PROTOCOLS):
        cell = _run_cell(protocol)
        p = cell.get("dsr_p")
        assert p is not None, f"{protocol}: missing Deflated Sharpe p-value"
        p = float(p)
        dsr_p_values.append(p)
        if best_p is None or p < best_p:
            best_p = p
            best_idx = i

    assert best_p >= DSR_PVALUE_THRESHOLD, (
        f"best-nominal cell DSR p={best_p} should be >= {DSR_PVALUE_THRESHOLD}"
    )

    # Use the shared Bonferroni helper (FWER control across the protocol family).
    res = bonferroni_correction(dsr_p_values, alpha=DSR_PVALUE_THRESHOLD)
    best_adjusted = res["adjusted_p_values"][best_idx]
    assert best_adjusted > DSR_PVALUE_THRESHOLD, (
        f"best-nominal DSR p={best_p} Bonferroni-adjusted = {best_adjusted} should "
        f"exceed {DSR_PVALUE_THRESHOLD} (not robust to protocol multiplicity)"
    )

    # No protocol should be rejected at the FWER threshold.
    assert res["n_rejected"] == 0, (
        f"expected 0 rejections at alpha={DSR_PVALUE_THRESHOLD}, got {res['n_rejected']}"
    )


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
    ("protocol_sensitivity_matrix_pinned", test_protocol_sensitivity_matrix_pinned),
    ("verdict_is_consistently_not_supported", test_verdict_is_consistently_not_supported),
    ("no_cell_survives_protocol_multiplicity", test_no_cell_survives_protocol_multiplicity),
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
