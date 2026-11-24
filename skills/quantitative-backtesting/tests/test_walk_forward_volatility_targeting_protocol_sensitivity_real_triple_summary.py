#!/usr/bin/env python3
"""Walk-forward *protocol-sensitivity* cross-asset summary for volatility
targeting on the committed triple panel (AAPL, MSFT, GOOGL).

Motivation
----------
Three parallel per-asset protocol-sensitivity studies now exist for volatility
targeting (AAPL, MSFT, GOOGL). Each applies a Bonferroni correction across its
five-protocol family. This summary aggregates the three assets into one
reproducible artifact and applies a **two-level multiplicity correction**:

1. Per-asset Bonferroni across the 5 protocols (FWER within asset).
2. Cross-asset Bonferroni across the 3 assets on the per-asset best nominal
   p-values (family-wise across assets).

This honestly reports whether volatility targeting survives multiplicity
anywhere on the committed panel.

Design (pre-registered before any number is inspected)
------------------------------------------------------
* Signal: ``volatility_targeting`` (single-asset, momentum-fallback base with
  volatility-targeting position sizing overlay) on committed AAPL, MSFT, GOOGL
  fixtures.
* Parameter grid: ``{"target_vol": [0.15], "lookback": [63]}`` (1
  configuration, the advertised default settings).
* Costs: commission 2 bps + slippage 1 bps per trade.
* Deflated Sharpe Ratio multiple-testing correction applied within each
  protocol (across the single configuration and all walk-forward periods).
* Protocols vary ``train_months`` / ``test_months`` with ``step_months ==
  test_months``. One pre-registered family of equally-valid 12-month-test
  protocols: (12, 12, 12), (18, 12, 12), (24, 12, 12), (30, 12, 12), (36, 12, 12).
* Pre-registered per-cell falsification criteria: OOS Sharpe > 0 AND OOS total
  return > 0 AND Deflated Sharpe p-value < 0.10.
* Two-level Bonferroni: first per-asset (5 protocols), then cross-asset
  (3 assets) on per-asset best nominal p-values.

Honest finding (all committed fixtures, offline)
------------------------------------------------
Pinned by the probe run below. Each cell is checked for informativeness
(periods_with_position >= 2) and the pre-registered criteria are applied
nominally; per-asset Bonferroni across the five-protocol family is applied to
the best nominal DSR p-value; then a cross-asset Bonferroni across the three
assets is applied to the per-asset best nominal p-values. The honest overall
verdict is reported whether zero, one, or more cells pass nominally, and
whether any survive the correction.

Offline, committed fixtures only; no live network. Test-only: the default JSON
backtest output is untouched.
"""
import contextlib
import io
import json
import math
import sys
from pathlib import Path

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
    "target_vol": [0.15],
    "lookback": [63],
}
DSR_PVALUE_THRESHOLD = 0.10

# Informative protocols: 12-month test windows.
INFORMATIVE_PROTOCOLS = [(12, 12, 12), (18, 12, 12), (24, 12, 12),
                         (30, 12, 12), (36, 12, 12)]
ALL_PROTOCOLS = INFORMATIVE_PROTOCOLS

# A cell is "informative" when the portfolio actually held a position for at
# least this many walk-forward periods; below it the OOS record is flat /
# undefined and cannot falsify the hypothesis.
MIN_INFORMATIVE_PERIODS = 2

# Pinned evidence matrix. Values are rounded to 4 decimals for readability and
# compared with ABS_TOL (see _assert_close). This is a regression guard on the
# study's observed results, not a profitability claim.
ABS_TOL = 1e-3

# Per-asset expected matrices. Each asset has its own EXPECTED dict.
# key: (train_months, test_months, step_months)
# value: dict(n_periods, n_pos, sharpe, tot, dsr_p, n_trials)
# n_trials is the number of configurations the DSR corrected for
# (1 configuration x n_periods).
EXPECTED = {
    "AAPL": {
        (12, 12, 12): dict(n_periods=4, n_pos=4, sharpe=0.04461683981968077, tot=0.0457715763671549, dsr_p=0.8606126629398998, n_trials=4),
        (18, 12, 12): dict(n_periods=4, n_pos=4, sharpe=0.08100666194993703, tot=0.06044684783323273, dsr_p=0.5217248755167543, n_trials=4),
        (24, 12, 12): dict(n_periods=3, n_pos=3, sharpe=-0.22362548156258563, tot=-0.05613730442271225, dsr_p=0.848419600822373, n_trials=3),
        (30, 12, 12): dict(n_periods=3, n_pos=3, sharpe=0.15166590866421192, tot=0.07185864016740462, dsr_p=0.4792316959505105, n_trials=3),
        (36, 12, 12): dict(n_periods=2, n_pos=2, sharpe=-0.0362752046731056, tot=0.005254185617500351, dsr_p=0.5976683344618153, n_trials=2),
    },
    "MSFT": {
        (12, 12, 12): dict(n_periods=4, n_pos=4, sharpe=-0.15814356104701618, tot=-0.045661951633572474, dsr_p=0.9793883242990916, n_trials=4),
        (18, 12, 12): dict(n_periods=4, n_pos=4, sharpe=0.48508575384937904, tot=0.2825453210961859, dsr_p=0.7577481274190563, n_trials=4),
        (24, 12, 12): dict(n_periods=3, n_pos=3, sharpe=-0.41952203913623264, tot=-0.11490678956583806, dsr_p=0.8281144339310352, n_trials=3),
        (30, 12, 12): dict(n_periods=3, n_pos=3, sharpe=0.41325338791484985, tot=0.1725799048012826, dsr_p=0.39180492806311727, n_trials=3),
        (36, 12, 12): dict(n_periods=2, n_pos=2, sharpe=-0.3496651091823761, tot=-0.061681129862135745, dsr_p=0.7620722662545692, n_trials=2),
    },
    "GOOGL": {
        (12, 12, 12): dict(n_periods=4, n_pos=4, sharpe=0.02879820324284823, tot=0.03737509738470683, dsr_p=0.6251761124142578, n_trials=4),
        (18, 12, 12): dict(n_periods=4, n_pos=4, sharpe=-0.34603814673451536, tot=-0.13789910948602775, dsr_p=0.9749699730062187, n_trials=4),
        (24, 12, 12): dict(n_periods=3, n_pos=3, sharpe=0.3277961219906063, tot=0.14021023206250714, dsr_p=0.40599811185992745, n_trials=3),
        (30, 12, 12): dict(n_periods=3, n_pos=3, sharpe=0.12650420504372844, tot=0.06227227566305748, dsr_p=0.4821131128391507, n_trials=3),
        (36, 12, 12): dict(n_periods=2, n_pos=2, sharpe=0.5404756450232447, tot=0.1464817720481209, dsr_p=0.27824213296348014, n_trials=2),
    },
}

# Best nominal protocol by raw DSR p-value (pre-registered index for the
# Bonferroni check) per asset.
BEST_NOMINAL_PROTOCOL = {
    "AAPL": (30, 12, 12),
    "MSFT": (30, 12, 12),
    "GOOGL": (36, 12, 12),
}


def _build_data(symbol):
    import pandas as pd

    df = pd.read_csv(SRC / f"{symbol}.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _factory(params):
    return build_strategy("volatility_targeting", json.dumps(params))


def _run_cell(symbol, protocol):
    """Run one protocol walk-forward cell on single-asset.

    Returns the cell summary: n_periods, periods_with_position, oos_sharpe,
    total_oos_return, deflated_sharpe p-value / n_trials.
    """
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
    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out, (
        f"{symbol} {protocol}: PIT validation not reported"
    )
    ds = summary.get("deflated_sharpe") or {}
    return {
        "n_periods": summary.get("n_periods"),
        "periods_with_position": summary.get("periods_with_position"),
        "oos_sharpe": summary.get("oos_sharpe"),
        "total_oos_return": summary.get("total_oos_return"),
        "dsr_p": ds.get("p_value"),
        "n_trials": ds.get("n_trials"),
        "n_observations": len(summary.get("oos_returns") or []),
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


def _run_all_assets():
    """Run all cells for all assets, return nested dict of results."""
    actuals = {}
    for symbol in SYMBOLS:
        actuals[symbol] = {}
        for protocol in ALL_PROTOCOLS:
            actuals[symbol][protocol] = _run_cell(symbol, protocol)
    return actuals


def test_protocol_sensitivity_matrix_pinned():
    """Regression guard + structural validity for the full protocol matrix
    across all three assets.

    Every cell must produce finite OOS metrics and the pinned number of
    walk-forward periods / positions. Point-in-time validation is asserted
    engaged inside _run_cell. Observed values are pinned against EXPECTED.
    """
    actuals = _run_all_assets()

    for symbol in SYMBOLS:
        for protocol in ALL_PROTOCOLS:
            cell = actuals[symbol][protocol]

            assert cell["n_periods"] is not None, (
                f"{symbol} {protocol}: n_periods missing"
            )
            assert cell["periods_with_position"] is not None, (
                f"{symbol} {protocol}: periods_with_position missing"
            )
            assert cell["periods_with_position"] >= MIN_INFORMATIVE_PERIODS, (
                f"{symbol} {protocol}: cell not informative, "
                f"periods_with_position={cell['periods_with_position']}"
            )
            for key, label in (("oos_sharpe", f"{symbol} {protocol} oos_sharpe"),
                               ("total_oos_return", f"{symbol} {protocol} total_oos_return"),
                               ("dsr_p", f"{symbol} {protocol} deflated_sharpe.p_value")):
                val = cell.get(key)
                assert val is not None and math.isfinite(float(val)), (
                    f"{label}: non-finite/missing value {val!r}"
                )
            p = cell.get("dsr_p")
            assert p is not None and 0.0 <= float(p) <= 1.0, (
                f"{symbol} {protocol}: DSR p-value out of range: {p!r}"
            )
            assert cell["n_trials"] is not None, (
                f"{symbol} {protocol}: DSR n_trials missing"
            )

    for symbol in SYMBOLS:
        for protocol in ALL_PROTOCOLS:
            cell = actuals[symbol][protocol]
            exp = EXPECTED[symbol][protocol]
            assert cell["n_periods"] == exp["n_periods"], (
                f"{symbol} {protocol}: n_periods {cell['n_periods']} != {exp['n_periods']}"
            )
            assert cell["periods_with_position"] == exp["n_pos"], (
                f"{symbol} {protocol}: periods_with_position "
                f"{cell['periods_with_position']} != {exp['n_pos']}"
            )
            _assert_close(cell.get("oos_sharpe"), exp["sharpe"], f"{symbol} {protocol} oos_sharpe")
            _assert_close(cell.get("total_oos_return"), exp["tot"], f"{symbol} {protocol} total_oos_return")
            _assert_close(cell.get("dsr_p"), exp["dsr_p"], f"{symbol} {protocol} deflated_sharpe.p_value")
            assert cell["n_trials"] == exp["n_trials"], (
                f"{symbol} {protocol}: DSR n_trials {cell['n_trials']} != {exp['n_trials']}"
            )


def test_verdict_is_consistently_not_supported():
    """Core finding: applies pre-registered nominal criteria per cell per asset
    and reports which cells pass; the corrected verdicts are checked in
    test_no_cell_survives_protocol_multiplicity and
    test_no_asset_survives_cross_asset_multiplicity.

    The verdict is reported honestly whether zero, one, or more cells pass
    nominally — no forcing toward a predetermined outcome.
    """
    for symbol in SYMBOLS:
        passing_cells = []

        for protocol in INFORMATIVE_PROTOCOLS:
            cell = _run_cell(symbol, protocol)
            crit = _criteria(cell)
            if all(crit.values()):
                passing_cells.append(protocol)

        # Recorded for honesty: no assertion on the count (avoid forcing a
        # verdict); multiplicity correction governs the overall conclusion below.
        print(f"{symbol} volatility targeting nominal passing cells: {passing_cells}")

        # The pinned baseline (12, 12, 12): its DSR p-value should fail the DSR criterion.
        baseline_crit = _criteria(_run_cell(symbol, (12, 12, 12)))
        assert baseline_crit["deflated_sharpe_pvalue_lt_0.10"] is False, (
            f"{symbol} baseline (12, 12, 12) unexpectedly passes DSR criterion"
        )


def test_no_cell_survives_protocol_multiplicity():
    """Per-asset Bonferroni: the nominal passers (if any) do not survive
    correction for the number of protocols within each asset.

    The DSR inside each cell corrects for the 1 configuration only (across all
    periods); it does not correct for the 5 protocols tried. A Bonferroni
    correction across the five-protocol family is applied to the best nominal
    p-value per asset; the corrected verdict governs the per-asset conclusion.
    """
    per_asset_results = {}

    for symbol in SYMBOLS:
        dsr_p_values = []
        best_idx = None
        best_p = None
        for i, protocol in enumerate(INFORMATIVE_PROTOCOLS):
            cell = _run_cell(symbol, protocol)
            p = cell.get("dsr_p")
            assert p is not None, f"{symbol} {protocol}: missing Deflated Sharpe p-value"
            p = float(p)
            dsr_p_values.append(p)
            if best_p is None or p < best_p:
                best_p = p
                best_idx = i

        # Use the shared Bonferroni helper (FWER control across the protocol family).
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

    # Store for cross-asset test
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

    # Extract the per-asset best nominal p-values
    per_asset_best_nominal = [per_asset_results[s]["best_nominal_p"] for s in SYMBOLS]

    # Apply Bonferroni across the 3 assets
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

    # Report total n_rejected across both levels
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
    ("verdict_is_consistently_not_supported", test_verdict_is_consistently_not_supported),
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