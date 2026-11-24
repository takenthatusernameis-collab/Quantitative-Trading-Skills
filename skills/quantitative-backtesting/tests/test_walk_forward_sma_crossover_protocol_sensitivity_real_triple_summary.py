#!/usr/bin/env python3
"""Walk-forward *protocol-sensitivity* cross-asset summary for standalone
SMA crossover on the committed triple panel (AAPL, MSFT, GOOGL).

Motivation
----------
The existing per-asset-then-equal-weight protocol-sensitivity study for SMA
crossover
(``test_walk_forward_sma_crossover_protocol_sensitivity_real_triple_aapl_msft_googl.py``)
runs each asset independently and then *pools* the per-asset out-of-sample
returns into a single equal-weight portfolio, computing one DSR per protocol
with ``n_trials = 3 assets x n_periods``. Pooling folds the asset-selection
decision *into* the DSR's trial count, so the asset dimension is corrected only
implicitly and cannot be audited separately from the protocol dimension.

This summary closes the cross-asset loop the same way the volatility-targeting,
time-series-momentum, and RSI mean-reversion cross-asset summaries do:
it treats each asset as a *separate hypothesis* with its own per-asset DSR and
applies an explicit **two-level Bonferroni**:

1. Per-asset Bonferroni across the four 12-month-test protocols (FWER within
   each asset), then
2. Cross-asset Bonferroni across the three assets applied to the per-asset best
   nominal DSR p-values (family-wise across assets).

The two levels are nested: an asset must clear the within-asset protocol
correction before its best nominal p-value is even eligible to be tested at the
cross-asset level; the cross-asset correction is what a reader must apply when
interpreting "the best of three assets" as evidence. This is the layer the
pooled triple test cannot isolate, because pooling bakes the three assets into a
single portfolio return series and a single DSR.

Design (pre-registered before any number is inspected)
-----------------------------------------------------
* Signal: ``sma_crossover`` (long when fast SMA > slow SMA, flat otherwise),
  per-asset long-only trend. SMA crossover operates on a single-asset frame,
  so each cell runs ``walk_forward_analysis`` on one asset at a time.
* Parameter grid: ``{"fast_period": [20], "slow_period": [50]}`` (1
  configuration, the same grid the existing single-protocol test uses).
* Costs: commission 2 bps + slippage 1 bps per trade (the shipped default).
* Deflated Sharpe Ratio correction applied *within* each per-asset protocol
  (across the single configuration and that asset's walk-forward periods).
* Protocols vary ``train_months`` / ``test_months`` with ``step_months ==
  test_months``. The informative 12-month-test family:
  (24, 12, 12), (36, 12, 12), (18, 12, 12), (30, 12, 12).
* Pre-registered per-cell falsification criteria: OOS Sharpe > 0 AND OOS total
  return > 0 AND Deflated Sharpe p-value < 0.10.
* Two-level Bonferroni: per-asset (4 protocols) then cross-asset (3 assets).

Honest finding (all committed fixtures, offline)
------------------------------------------------
Pinned by the run below.

* Nominal: two of the twelve informative cells pass all three criteria.
  AAPL @ (36, 12, 12) (DSR p = 0.0415) and MSFT @ (30, 12, 12) (DSR p = 0.0574)
  both pass nominally. The raw OOS Sharpe and total return are positive there
  and survive deflation at the nominal 0.10 level.
* Per-asset Bonferroni (4 protocols):
    - AAPL: best nominal p = 0.0415 @ (36, 12, 12) -> adjusted = 0.1660, n_rejected = 0
    - MSFT: best nominal p = 0.0574 @ (30, 12, 12) -> adjusted = 0.2296, n_rejected = 0
    - GOOGL: best nominal p = 0.1299 @ (36, 12, 12) -> adjusted = 0.5196, n_rejected = 0
* Cross-asset Bonferroni (3 assets) on per-asset best nominal p-values:
    - best nominal p = 0.0415 (AAPL) -> adjusted = 0.1245, n_rejected = 0
* Total n_rejected across both levels = 0.
* Overall verdict: NOT SUPPORTED. SMA crossover does not survive multiplicity
  correction anywhere on the committed triple panel. The nominal passes are
  consistent with protocol/asset selection noise, not a demonstrated edge.

Conclusion: the positive raw out-of-sample Sharpe for SMA crossover is
consistent with protocol/asset selection noise. Any future SUPPORT/NOT-SUPPORT
claim must be pre-registered on held-out data not used to select the protocol
or the asset. This study exists to make that limitation explicit and
regression-guarded, and to close the cross-asset loop for SMA crossover the
same way the volatility-targeting, TSMOM, and RSI mean-reversion summaries
close it for those families.

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
PARAM_GRID = {
    "fast_period": [20],
    "slow_period": [50],
}
DSR_PVALUE_THRESHOLD = 0.10

# Informative protocols: 12-month test windows.
INFORMATIVE_PROTOCOLS = [(24, 12, 12), (36, 12, 12), (18, 12, 12), (30, 12, 12)]

# A cell is "informative" when the strategy actually held a position for at
# least this many walk-forward periods; below it the OOS record is flat /
# undefined and cannot falsify the hypothesis.
MIN_INFORMATIVE_PERIODS = 2

# Pinned evidence matrix. Values are rounded to 4 decimals for readability and
# compared with ABS_TOL (see _assert_close). This is a regression guard on the
# study's observed results, not a profitability claim. Sourced from a per-asset
# walk-forward run (each asset evaluated independently with apply_deflation=True)
# and re-verified by the run below.
ABS_TOL = 1e-3

# Per-asset expected matrices.
# key: (train_months, test_months, step_months)
# value: dict(n_periods, n_pos, sharpe, tot, dsr_p, n_trials)
# n_trials is the number of lookback configurations the within-protocol DSR
# corrected for (1 configuration x n_periods, i.e. one per asset per period).
EXPECTED = {
    "AAPL": {
        (24, 12, 12): dict(n_periods=3, n_pos=3, sharpe=0.3006, tot=0.1787, dsr_p=0.7076, n_trials=3),
        (36, 12, 12): dict(n_periods=2, n_pos=2, sharpe=1.2798, tot=0.5029, dsr_p=0.0415, n_trials=2),
        (18, 12, 12): dict(n_periods=4, n_pos=4, sharpe=0.0565, tot=0.0695, dsr_p=0.7016, n_trials=4),
        (30, 12, 12): dict(n_periods=3, n_pos=3, sharpe=0.0802, tot=0.0649, dsr_p=0.5499, n_trials=3),
    },
    "MSFT": {
        (24, 12, 12): dict(n_periods=3, n_pos=3, sharpe=-0.4144, tot=-0.1632, dsr_p=0.9759, n_trials=3),
        (36, 12, 12): dict(n_periods=2, n_pos=2, sharpe=0.4344, tot=0.1672, dsr_p=0.3918, n_trials=2),
        (18, 12, 12): dict(n_periods=4, n_pos=4, sharpe=0.4087, tot=0.3210, dsr_p=0.5593, n_trials=4),
        (30, 12, 12): dict(n_periods=3, n_pos=3, sharpe=1.0088, tot=0.6092, dsr_p=0.0574, n_trials=3),
    },
    "GOOGL": {
        (24, 12, 12): dict(n_periods=3, n_pos=3, sharpe=0.1642, tot=0.1016, dsr_p=0.8493, n_trials=3),
        (36, 12, 12): dict(n_periods=2, n_pos=2, sharpe=0.8012, tot=0.4116, dsr_p=0.1299, n_trials=2),
        (18, 12, 12): dict(n_periods=4, n_pos=4, sharpe=0.1017, tot=0.0828, dsr_p=0.8771, n_trials=4),
        (30, 12, 12): dict(n_periods=3, n_pos=3, sharpe=0.4821, tot=0.3487, dsr_p=0.3283, n_trials=3),
    },
}

# Best nominal protocol by raw DSR p-value (pre-registered index for the
# Bonferroni checks) per asset.
BEST_NOMINAL_PROTOCOL = {
    "AAPL": (36, 12, 12),
    "MSFT": (30, 12, 12),
    "GOOGL": (36, 12, 12),
}

# Two informative cells pass all three pre-registered criteria nominally:
# AAPL @ (36, 12, 12) (DSR p = 0.0415) and MSFT @ (30, 12, 12) (DSR p = 0.0574).
# Reported honestly, then confirmed by the multiplicity tests below.
EXPECTED_NOMINAL_PASS = (
    ("AAPL", (36, 12, 12)),
    ("MSFT", (30, 12, 12)),
)


def _build_data(symbol):
    df = pd.read_csv(SRC / f"{symbol}.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _factory(params):
    return build_strategy("sma_crossover", json.dumps(params))


def _run_cell(symbol, protocol):
    """Run one (symbol, protocol) walk-forward cell and return its summary."""
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
    no forcing toward a predetermined outcome. For SMA crossover, two cells
    pass all three criteria nominally (AAPL @ (36, 12, 12) with DSR p = 0.0415
    and MSFT @ (30, 12, 12) with DSR p = 0.0574); the corrected verdict is
    governed by the multiplicity tests below.
    """
    nominal_passes = []
    best_cell = None
    best_p = None
    for symbol in SYMBOLS:
        for protocol in INFORMATIVE_PROTOCOLS:
            summary = _run_cell(symbol, protocol)
            assert summary["periods_with_position"] >= MIN_INFORMATIVE_PERIODS
            crit = _criteria(summary)
            p = _dsr_p(summary)
            if p is not None and (best_p is None or float(p) < best_p):
                best_p = float(p)
                best_cell = (symbol, protocol)
            if all(crit.values()):
                nominal_passes.append((symbol, protocol))

    print(f"SMA nominal passing cells: {nominal_passes}")
    print(f"Best nominal cell by DSR p: {best_cell} (p={best_p:.4f})")

    # The pinned 24/12/12 baseline must fail the DSR criterion for every asset.
    for symbol in SYMBOLS:
        baseline_crit = _criteria(_run_cell(symbol, (24, 12, 12)))
        assert baseline_crit["deflated_sharpe_pvalue_lt_0.10"] is False, (
            f"{symbol} baseline (24, 12, 12) unexpectedly passes DSR criterion"
        )

    # Honest report of the nominal state: two cells pass all three criteria.
    assert nominal_passes == list(EXPECTED_NOMINAL_PASS), (
        f"expected nominal passes {list(EXPECTED_NOMINAL_PASS)}, got {nominal_passes}"
    )

    # The single best nominal cell passes the DSR criterion nominally
    # (p < 0.10), but multiplicity correction will determine the final verdict.
    assert best_p is not None and best_p < DSR_PVALUE_THRESHOLD, (
        f"best nominal DSR p={best_p} should be < {DSR_PVALUE_THRESHOLD} "
        f"(nominal pass exists)"
    )


def test_no_cell_survives_protocol_multiplicity():
    """Per-asset Bonferroni: the nominal pass (if any) does not survive
    correction for the number of protocols within each asset.

    The DSR inside each cell corrects for the 1 configuration only; it does
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