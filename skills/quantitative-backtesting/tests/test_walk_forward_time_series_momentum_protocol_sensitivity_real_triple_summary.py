#!/usr/bin/env python3
"""Walk-forward *protocol-sensitivity* cross-asset summary for standalone
time-series momentum (TSMOM) on the committed triple panel (AAPL, MSFT, GOOGL).

Motivation
----------
Session 155 produced a per-asset protocol-sensitivity study for standalone TSMOM
(``test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py``)
that found exactly one nominal pass across the twelve informative
(symbol x protocol) cells -- MSFT at (30, 12, 12), DSR p = 0.0696 -- and showed
it dies under a *within-MSFT* Bonferroni across the four 12-month protocols
(0.0696 * 4 = 0.278 > 0.10).

That study stops at the single-asset boundary: it asks "is MSFT's lone nominal
pass robust to the protocols tried *on MSFT*?" It does not ask the broader
family-wise question the volatility-targeting cross-asset summary introduced:
"does the best nominal evidence for TSMOM survive correction for the *number of
assets* tried as well?" Because AAPL, MSFT and GOOGL are three separate ways to
look for a TSMOM edge, testing all three is itself a multiple-testing decision.

This summary extends the **two-level multiplicity framework** established for
volatility targeting
(``test_walk_forward_volatility_targeting_protocol_sensitivity_real_triple_summary.py``)
to TSMOM, the foundational momentum family:

1. Per-asset Bonferroni across the four 12-month-test protocols (FWER within
   each asset), then
2. Cross-asset Bonferroni across the three assets applied to the per-asset best
   nominal DSR p-values (family-wise across assets).

The two levels are nested: an asset must clear the within-asset protocol
correction before its best nominal p-value is even eligible to be tested at the
cross-asset level; the cross-asset correction is what a reader must apply when
interpreting "the best of three assets" as evidence.

Design (pre-registered before any number is inspected)
------------------------------------------------------
* Signal: ``time_series_momentum`` (long when the trailing return over
  ``lookback`` days is positive, flat otherwise), single asset.
* Lookback grid: ``{"lookback": [126, 189, 252]}`` (3 configurations, identical
  to the per-asset TSMOM study).
* Costs: commission 2 bps + slippage 1 bps per trade (the shipped default).
* Deflated Sharpe Ratio correction applied *within* each protocol (across the 3
  lookback values and all walk-forward periods).
* Protocols vary ``train_months`` / ``test_months`` with ``step_months ==
  test_months``. The informative 12-month-test family (test window >= the
  252-day lookback, so the signal is defined throughout):
  (24, 12, 12), (36, 12, 12), (18, 12, 12), (30, 12, 12).
  The 6-month short-window protocols from the per-asset study are excluded here:
  they leave the strategy essentially flat (periods_with_position <= 1) and carry
  no OOS evidence (documented in the per-asset study).
* Pre-registered per-cell falsification criteria: OOS Sharpe > 0 AND OOS total
  return > 0 AND Deflated Sharpe p-value < 0.10.
* Two-level Bonferroni: per-asset (4 protocols) then cross-asset (3 assets).

Honest finding (all committed fixtures, offline)
------------------------------------------------
Pinned by the run below.

* Nominal: exactly one of the twelve informative cells passes all three
  criteria -- MSFT at (30, 12, 12) (DSR p = 0.0696). The (24, 12, 12) baseline
  fails for every asset, matching the single-protocol NOT SUPPORTED verdicts.
* Per-asset Bonferroni (4 protocols):
    - AAPL: best nominal p = 0.1021 @ (36, 12, 12) -> adjusted = 0.4084, n_rejected = 0
    - MSFT: best nominal p = 0.0696 @ (30, 12, 12) -> adjusted = 0.2782, n_rejected = 0
    - GOOGL: best nominal p = 0.5814 @ (30, 12, 12) -> adjusted = 1.0, n_rejected = 0
* Cross-asset Bonferroni (3 assets) on per-asset best nominal p-values:
    - best nominal p = 0.0696 (MSFT) -> adjusted = 0.2087, n_rejected = 0
* Total n_rejected across both levels = 0.
* Overall verdict: NOT SUPPORTED. TSMOM does not survive multiplicity correction
  anywhere on the committed triple panel, and no protocol-selection or
  asset-selection bias can rescue it.

Conclusion: the lone nominal MSFT pass (p = 0.0696) is consistent with
protocol/asset selection noise, not a demonstrated TSMOM edge. Any future
SUPPORT/NOT-SUPPORT claim must be pre-registered on held-out data not used to
select the protocol or the asset. This study exists to make that limitation
explicit and regression-guarded, and to close the cross-asset loop for TSMOM the
same way the volatility-targeting summary closes it for volatility targeting.

Offline, committed fixtures only; no live network. Test-only: the default JSON
backtest output is untouched.
"""
import contextlib
import io
import json
import math
import sys
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import walk_forward_analysis  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402
from utils import bonferroni_correction  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

SYMBOLS = ["AAPL", "MSFT", "GOOGL"]

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade
LOOKBACK_GRID = {"lookback": [126, 189, 252]}
DSR_PVALUE_THRESHOLD = 0.10

# Informative protocols: 12-month test windows (>= the 252-day lookback), so
# the signal is defined throughout the test window.
INFORMATIVE_PROTOCOLS = [(24, 12, 12), (36, 12, 12), (18, 12, 12), (30, 12, 12)]

# A cell is "informative" when the strategy actually held a position for at
# least this many walk-forward periods; below it the OOS record is flat /
# undefined and cannot falsify the hypothesis.
MIN_INFORMATIVE_PERIODS = 2

# Pinned evidence matrix. Values are rounded to 4 decimals for readability and
# compared with ABS_TOL (see _assert_close). This is a regression guard on the
# study's observed results, not a profitability claim. Sourced from the pinned
# per-asset TSMOM protocol-sensitivity study
# (test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py)
# and re-verified by the run below.
ABS_TOL = 1e-3

# Per-asset expected matrices.
# key: (train_months, test_months, step_months)
# value: dict(n_periods, n_pos, sharpe, tot, dsr_p, n_trials)
# n_trials is the number of lookback configurations the within-protocol DSR
# corrected for (3 configurations x n_periods).
EXPECTED = {
    "AAPL": {
        (24, 12, 12): dict(n_periods=3, n_pos=3, sharpe=-0.3885, tot=-0.0598, dsr_p=0.9746, n_trials=5),
        (36, 12, 12): dict(n_periods=2, n_pos=2, sharpe=1.0575, tot=0.2235, dsr_p=0.1021, n_trials=4),
        (18, 12, 12): dict(n_periods=4, n_pos=4, sharpe=-0.0288, tot=0.0247, dsr_p=0.8231, n_trials=7),
        (30, 12, 12): dict(n_periods=3, n_pos=3, sharpe=0.5345, tot=0.2428, dsr_p=0.3170, n_trials=5),
    },
    "MSFT": {
        (24, 12, 12): dict(n_periods=3, n_pos=3, sharpe=-0.4138, tot=-0.1018, dsr_p=0.9569, n_trials=5),
        (36, 12, 12): dict(n_periods=2, n_pos=2, sharpe=-0.3358, tot=-0.0726, dsr_p=0.8325, n_trials=4),
        (18, 12, 12): dict(n_periods=4, n_pos=4, sharpe=0.4950, tot=0.3306, dsr_p=0.4330, n_trials=8),
        (30, 12, 12): dict(n_periods=3, n_pos=3, sharpe=1.2195, tot=0.6403, dsr_p=0.0696, n_trials=6),
    },
    "GOOGL": {
        (24, 12, 12): dict(n_periods=3, n_pos=2, sharpe=-0.1162, tot=-0.0245, dsr_p=0.6223, n_trials=4),
        (36, 12, 12): dict(n_periods=2, n_pos=2, sharpe=-0.1162, tot=-0.0245, dsr_p=0.6223, n_trials=4),
        (18, 12, 12): dict(n_periods=4, n_pos=4, sharpe=-0.2120, tot=-0.0707, dsr_p=0.9658, n_trials=8),
        (30, 12, 12): dict(n_periods=3, n_pos=3, sharpe=0.0979, tot=0.0711, dsr_p=0.5814, n_trials=6),
    },
}

# Best nominal protocol by raw DSR p-value (pre-registered index for the
# Bonferroni checks) per asset.
BEST_NOMINAL_PROTOCOL = {
    "AAPL": (36, 12, 12),
    "MSFT": (30, 12, 12),
    "GOOGL": (30, 12, 12),
}

# The single informative cell that passes all three pre-registered criteria
# nominally (from the per-asset TSMOM study). It is reported honestly and then
# corrected in test_no_cell_survives_protocol_multiplicity.
EXPECTED_NOMINAL_PASS = ("MSFT", (30, 12, 12))


def _build_data(symbol):
    df = pd.read_csv(SRC / f"{symbol}.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _factory(params):
    return build_strategy("time_series_momentum", json.dumps(params))


def _run_cell(symbol, protocol):
    """Run one (symbol, protocol) walk-forward cell and return its summary."""
    train_months, test_months, step_months = protocol
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = walk_forward_analysis(
            data=_build_data(symbol),
            strategy_factory=_factory,
            param_grid=LOOKBACK_GRID,
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
    return summary


def _dsr_p(summary):
    dsr = summary.get("deflated_sharpe") or {}
    return dsr.get("p_value")


def _criteria(summary):
    """Pre-registered per-cell criteria -> dict of booleans (NaN-safe)."""
    sharpe = summary.get("oos_sharpe")
    tot = summary.get("total_oos_return")
    p = _dsr_p(summary)
    return {
        "oos_sharpe_gt_zero": bool(sharpe is not None and math.isfinite(sharpe) and sharpe > 0),
        "oos_total_return_positive": bool(tot is not None and math.isfinite(tot) and tot > 0),
        "deflated_sharpe_pvalue_lt_0.10": bool(p is not None and math.isfinite(p) and float(p) < DSR_PVALUE_THRESHOLD),
    }


def _assert_close(got, exp, label):
    assert got is not None, f"{label}: missing value (expected ~{exp})"
    assert abs(float(got) - float(exp)) <= ABS_TOL, (
        f"{label}: got {got!r}, expected ~{exp} (abs tol {ABS_TOL})"
    )


def _run_all_assets():
    """Run all informative cells for all assets, return nested dict."""
    actuals = {}
    for symbol in SYMBOLS:
        actuals[symbol] = {}
        for protocol in INFORMATIVE_PROTOCOLS:
            actuals[symbol][protocol] = _run_cell(symbol, protocol)
    return actuals


def test_protocol_sensitivity_matrix_pinned():
    """Regression guard + structural validity for the full (symbol x protocol)
    matrix across all three assets.

    Every cell must produce finite OOS metrics and the pinned number of
    walk-forward periods / positions. Point-in-time validation is asserted
    engaged inside _run_cell.
    """
    actuals = _run_all_assets()

    for symbol in SYMBOLS:
        for protocol in INFORMATIVE_PROTOCOLS:
            summary = actuals[symbol][protocol]
            exp = EXPECTED[symbol][protocol]

            assert summary["n_periods"] == exp["n_periods"], (
                f"{symbol} {protocol}: n_periods {summary['n_periods']} != {exp['n_periods']}"
            )
            assert summary["periods_with_position"] == exp["n_pos"], (
                f"{symbol} {protocol}: periods_with_position "
                f"{summary['periods_with_position']} != {exp['n_pos']}"
            )
            assert summary["periods_with_position"] >= MIN_INFORMATIVE_PERIODS, (
                f"{symbol} {protocol}: cell not informative, "
                f"periods_with_position={summary['periods_with_position']}"
            )

            _assert_close(summary.get("oos_sharpe"), exp["sharpe"], f"{symbol} {protocol} oos_sharpe")
            _assert_close(summary.get("total_oos_return"), exp["tot"], f"{symbol} {protocol} total_oos_return")
            _assert_close(_dsr_p(summary), exp["dsr_p"], f"{symbol} {protocol} deflated_sharpe.p_value")
            dsr = summary.get("deflated_sharpe") or {}
            assert dsr.get("n_trials") == exp["n_trials"], (
                f"{symbol} {protocol}: DSR n_trials {dsr.get('n_trials')} != {exp['n_trials']}"
            )
            p = _dsr_p(summary)
            assert p is not None and 0.0 <= float(p) <= 1.0, (
                f"{symbol} {protocol}: DSR p-value out of range: {p!r}"
            )


def test_nominal_criteria_report_honestly():
    """Core nominal finding: applies the pre-registered per-cell criteria per
    asset and reports which cells pass nominally.

    The verdict is reported honestly whether zero, one, or more cells pass --
    no forcing toward a predetermined outcome. The nominal pass is expected to
    be exactly MSFT at (30, 12, 12); the *corrected* verdict is governed by the
    multiplicity tests below.
    """
    nominal_passes = []
    for symbol in SYMBOLS:
        for protocol in INFORMATIVE_PROTOCOLS:
            summary = _run_cell(symbol, protocol)
            assert summary["periods_with_position"] >= MIN_INFORMATIVE_PERIODS
            crit = _criteria(summary)
            if all(crit.values()):
                nominal_passes.append((symbol, protocol))

    print(f"TSMOM nominal passing cells: {nominal_passes}")

    # The pinned 24/12/12 baseline must fail the DSR criterion for every asset,
    # matching the single-protocol NOT SUPPORTED verdicts.
    for symbol in SYMBOLS:
        baseline_crit = _criteria(_run_cell(symbol, (24, 12, 12)))
        assert baseline_crit["deflated_sharpe_pvalue_lt_0.10"] is False, (
            f"{symbol} baseline (24, 12, 12) unexpectedly passes DSR criterion"
        )

    # Honest report of the nominal state: exactly the one known nominal pass.
    assert nominal_passes == [EXPECTED_NOMINAL_PASS], (
        f"expected exactly the nominal pass {EXPECTED_NOMINAL_PASS}, got {nominal_passes}"
    )


def test_no_cell_survives_protocol_multiplicity():
    """Per-asset Bonferroni: the nominal pass (if any) does not survive
    correction for the number of protocols within each asset.

    The DSR inside each cell corrects for the 3 lookback values only; it does
    not correct for the 4 protocols tried. A Bonferroni correction across the
    four-protocol family is applied to the best nominal p-value per asset; the
    corrected verdict governs the per-asset conclusion.
    """
    per_asset_results = {}

    for symbol in SYMBOLS:
        dsr_p_values = []
        best_idx = None
        best_p = None
        for i, protocol in enumerate(INFORMATIVE_PROTOCOLS):
            p = _dsr_p(_run_cell(symbol, protocol))
            assert p is not None, f"{symbol} {protocol}: missing Deflated Sharpe p-value"
            p = float(p)
            dsr_p_values.append(p)
            if best_p is None or p < best_p:
                best_p = p
                best_idx = i

        # Confirm the best-nominal protocol matches the pinned index.
        assert INFORMATIVE_PROTOCOLS[best_idx] == BEST_NOMINAL_PROTOCOL[symbol], (
            f"{symbol}: best-nominal protocol {INFORMATIVE_PROTOCOLS[best_idx]} "
            f"!= pinned {BEST_NOMINAL_PROTOCOL[symbol]}"
        )

        res = bonferroni_correction(dsr_p_values, alpha=DSR_PVALUE_THRESHOLD)
        best_adjusted = res["adjusted_p_values"][best_idx]
        per_asset_results[symbol] = {
            "best_nominal_p": best_p,
            "best_protocol": INFORMATIVE_PROTOCOLS[best_idx],
            "best_adjusted_p": best_adjusted,
            "n_rejected": res["n_rejected"],
        }
        print(f"{symbol}: best-nominal DSR p={best_p:.4f} at {INFORMATIVE_PROTOCOLS[best_idx]}, "
              f"Bonferroni-adjusted={best_adjusted:.4f}, n_rejected={res['n_rejected']}")

        # No protocol should be rejected at the FWER threshold for this asset.
        assert best_adjusted > DSR_PVALUE_THRESHOLD, (
            f"{symbol}: best-nominal DSR p={best_p} Bonferroni-adjusted = {best_adjusted} should "
            f"exceed {DSR_PVALUE_THRESHOLD} (not robust to protocol multiplicity)"
        )
        assert res["n_rejected"] == 0, (
            f"{symbol}: expected 0 rejections at alpha={DSR_PVALUE_THRESHOLD}, got {res['n_rejected']}"
        )

    # Store for the cross-asset test.
    test_no_cell_survives_protocol_multiplicity.per_asset_results = per_asset_results


def test_no_asset_survives_cross_asset_multiplicity():
    """Cross-asset Bonferroni: the per-asset best nominal p-values do not
    survive correction for the number of assets tested (3).

    This is the second level of multiplicity correction, applied to the
    per-asset best nominal DSR p-values (after the per-asset protocol
    Bonferroni has already been applied and failed).
    """
    # Recompute the per-asset results in-process instead of reading a function
    # attribute left by the per-asset test: pytest-xdist distributes tests
    # across workers and a standalone run skips it entirely, so the attribute
    # handoff is order/worker dependent (it failed under the -n 4 gate).
    test_no_cell_survives_protocol_multiplicity()
    per_asset_results = test_no_cell_survives_protocol_multiplicity.per_asset_results
    assert per_asset_results is not None, "per-asset results not available"

    per_asset_best_nominal = [per_asset_results[s]["best_nominal_p"] for s in SYMBOLS]

    res = bonferroni_correction(per_asset_best_nominal, alpha=DSR_PVALUE_THRESHOLD)
    best_idx = per_asset_best_nominal.index(min(per_asset_best_nominal))
    best_symbol = SYMBOLS[best_idx]
    best_nominal = per_asset_best_nominal[best_idx]
    best_adjusted = res["adjusted_p_values"][best_idx]

    print(f"Cross-asset: best-nominal DSR p={best_nominal:.4f} ({best_symbol}), "
          f"Bonferroni-adjusted={best_adjusted:.4f}, n_rejected={res['n_rejected']}")

    # No asset should be rejected at the FWER threshold across assets.
    assert best_adjusted > DSR_PVALUE_THRESHOLD, (
        f"cross-asset: best-nominal DSR p={best_nominal} ({best_symbol}) "
        f"Bonferroni-adjusted = {best_adjusted} should exceed {DSR_PVALUE_THRESHOLD} "
        f"(not robust to cross-asset multiplicity)"
    )
    assert res["n_rejected"] == 0, (
        f"cross-asset: expected 0 rejections at alpha={DSR_PVALUE_THRESHOLD}, got {res['n_rejected']}"
    )

    total_rejected = sum(per_asset_results[s]["n_rejected"] for s in SYMBOLS) + res["n_rejected"]
    print(f"Total n_rejected across per-asset protocol multiplicity + cross-asset: {total_rejected}")


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
    ("nominal_criteria_report_honestly", test_nominal_criteria_report_honestly),
    ("no_cell_survives_protocol_multiplicity", test_no_cell_survives_protocol_multiplicity),
    ("no_asset_survives_cross_asset_multiplicity", test_no_asset_survives_cross_asset_multiplicity),
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