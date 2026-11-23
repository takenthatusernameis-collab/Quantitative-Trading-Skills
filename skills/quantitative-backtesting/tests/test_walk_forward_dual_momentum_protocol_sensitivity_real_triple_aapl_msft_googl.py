#!/usr/bin/env python3
"""Walk-forward *protocol-sensitivity* study for dual momentum on the committed
AAPL/MSFT/GOOGL triple panel.

Motivation
----------
The existing walk-forward dual momentum test pins a *single* evaluation
protocol (train 12 / test 12 / step 12 months) and records a NOT SUPPORTED
verdict from it. A single protocol cannot distinguish "the strategy has no
edge" from "the evaluation window was unlucky": the train/test window lengths
are an analyst degree of freedom, and choosing among them after seeing results
is a form of data mining (protocol-selection bias). This study quantifies that
sensitivity for dual momentum, generalizing the time-series momentum and
cross-sectional momentum protocol-sensitivity studies.

Design (pre-registered before any number is inspected)
------------------------------------------------------
* Signal: ``dual_momentum`` (absolute-momentum filter + relative-momentum
  top-quantile selection, equal-weight long-only book) on the committed
  three-asset panel (AAPL / MSFT / GOOGL), priced per long-and-short ``book``.
* Lookback grid: ``{"lookback": [189, 252], "top_quantile": [0.5],
  "risk_free_rate": [0.0]}`` (2 configurations, the same grid the existing
  single-protocol test uses).
* Costs: commission 2 bps + slippage 1 bps per trade (the shipped default).
* Deflated Sharpe Ratio multiple-testing correction is applied *within* each
  protocol (across the 2 lookback values and all walk-forward periods).
* Protocols vary ``train_months`` and ``test_months`` with ``step_months ==
  test_months`` (the framework rejects ``step_months < test_months``). One
  pre-registered family of equally-valid 12-month-test protocols (test window
  >= the 252-day lookback, so the signal is defined throughout):
  (12, 12, 12), (24, 12, 12), (36, 12, 12), (30, 12, 12).
* Pre-registered per-cell falsification criteria: OOS Sharpe > 0 AND OOS total
  return > 0 AND Deflated Sharpe p-value < 0.10.

Honest finding (all committed fixtures, offline)
------------------------------------------------
Unlike time-series momentum, dual momentum does *not* flip the OOS Sharpe sign
across these four equally-valid protocols: the raw out-of-sample Sharpe is
positive in every cell (0.9481 -> 0.9844 -> 0.9844 -> 0.9890) and the total
return is positive in every cell. However, the Deflated Sharpe p-value exceeds
0.10 in every cell (0.1002 -> 0.1130 -> 0.1130 -> 0.1186), so *no cell passes
all three pre-registered criteria* and the verdict is consistently NOT
SUPPORTED. The best nominal cell, (12, 12, 12) (DSR p = 0.1002), does not
survive a Bonferroni correction across the four protocols (adjusted p ~ 0.40 > 0.10).

Conclusion: the positive raw out-of-sample Sharpe is not robust to
multiple-testing correction under any of the four equally-valid protocols, and
no protocol-selection bias can rescue it. A single protocol cannot establish a
dual momentum verdict; any future SUPPORT/NOT-SUPPORT claim must be
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

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import walk_forward_analysis  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402
from utils import bonferroni_correction  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade
PARAM_GRID = {
    "lookback": [189, 252],
    "top_quantile": [0.5],
    "risk_free_rate": [0.0],
}
DSR_PVALUE_THRESHOLD = 0.10

# Informative protocols: 12-month test windows (>= the 252-day lookback).
INFORMATIVE_PROTOCOLS = [(12, 12, 12), (24, 12, 12), (36, 12, 12), (30, 12, 12)]
ALL_PROTOCOLS = INFORMATIVE_PROTOCOLS

# A cell is "informative" when the strategy actually held a position for at
# least this many walk-forward periods; below it the OOS record is flat /
# undefined and cannot falsify the hypothesis.
MIN_INFORMATIVE_PERIODS = 2

# Pinned evidence matrix. Values are rounded to 4 decimals for readability and
# compared with ABS_TOL (see _assert_close). This is a regression guard on the
# study's observed results, not a profitability claim.
ABS_TOL = 1e-3

# key: (train_months, test_months, step_months)
# value: dict(n_periods, n_pos, sharpe, tot, dsr_p, n_trials)
EXPECTED = {
    # --- Informative 12-month-test cells ---
    (12, 12, 12): dict(n_periods=4, n_pos=3, sharpe=0.9481, tot=0.3914, dsr_p=0.1002, n_trials=3),
    (24, 12, 12): dict(n_periods=3, n_pos=2, sharpe=0.9844, tot=0.2425, dsr_p=0.1130, n_trials=2),
    (36, 12, 12): dict(n_periods=2, n_pos=2, sharpe=0.9844, tot=0.2425, dsr_p=0.1130, n_trials=2),
    (30, 12, 12): dict(n_periods=3, n_pos=3, sharpe=0.9890, tot=0.4222, dsr_p=0.1186, n_trials=3),
}


def _build_panel():
    panel = {}
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        panel[Path(name).stem] = df.set_index("date").sort_index()
    return panel


def _factory(params):
    return build_strategy("dual_momentum", json.dumps(params))


def _run_cell(protocol):
    """Run one protocol walk-forward cell on the triple panel and return its
    summary. Point-in-time validation is asserted engaged."""
    train_months, test_months, step_months = protocol
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = walk_forward_analysis(
            data=_build_panel(),
            strategy_factory=_factory,
            param_grid=PARAM_GRID,
            train_months=train_months,
            test_months=test_months,
            step_months=step_months,
            commission=COMMISSION,
            slippage=SLIPPAGE,
            panel_pricing="book",
            apply_deflation=True,
            validate_pit=True,
        )
    summary = result["summary"]
    assert summary.get("bias_controls_engaged") is True, (
        f"{protocol}: point-in-time validation not engaged"
    )
    return summary


def _criteria(summary):
    """Pre-registered per-cell criteria -> dict of booleans (NaN-safe)."""
    sharpe = summary.get("oos_sharpe")
    tot = summary.get("total_oos_return")
    dsr = summary.get("deflated_sharpe") or {}
    p = dsr.get("p_value")
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
    engaged inside _run_cell.
    """
    for protocol in ALL_PROTOCOLS:
        summary = _run_cell(protocol)
        exp = EXPECTED[protocol]

        assert summary["n_periods"] == exp["n_periods"], (
            f"{protocol}: n_periods {summary['n_periods']} != {exp['n_periods']}"
        )
        assert summary["periods_with_position"] == exp["n_pos"], (
            f"{protocol}: periods_with_position "
            f"{summary['periods_with_position']} != {exp['n_pos']}"
        )

        _assert_close(summary.get("oos_sharpe"), exp["sharpe"], f"{protocol} oos_sharpe")
        _assert_close(summary.get("total_oos_return"), exp["tot"], f"{protocol} total_oos_return")
        dsr = summary.get("deflated_sharpe") or {}
        _assert_close(dsr.get("p_value"), exp["dsr_p"], f"{protocol} deflated_sharpe.p_value")
        assert dsr.get("n_trials") == exp["n_trials"], (
            f"{protocol}: DSR n_trials {dsr.get('n_trials')} != {exp['n_trials']}"
        )
        p = dsr.get("p_value")
        assert p is not None and 0.0 <= float(p) <= 1.0, (
            f"{protocol}: DSR p-value out of range: {p!r}"
        )


def test_verdict_is_consistently_not_supported():
    """Core finding: the raw OOS Sharpe is positive under every equally-valid
    protocol, yet the Deflated Sharpe p-value exceeds 0.10 in every cell, so
    no cell passes all three pre-registered criteria and the verdict is
    consistently NOT SUPPORTED. The pinned 12/12/12 baseline therefore fails,
    matching the single-protocol test's NOT SUPPORTED verdict.

    This shows dual momentum cannot be rescued by protocol selection here: the
    positive raw Sharpe never survives multiple-testing correction.
    """
    baseline_pass = None
    passing_cells = []

    for protocol in INFORMATIVE_PROTOCOLS:
        summary = _run_cell(protocol)
        assert summary["periods_with_position"] >= MIN_INFORMATIVE_PERIODS
        sharpe = summary["oos_sharpe"]
        assert sharpe is not None and math.isfinite(sharpe)

        crit = _criteria(summary)
        if protocol == (12, 12, 12):
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

    # The pinned 12/12/12 baseline fails all criteria.
    assert baseline_pass is False, (
        f"baseline (12,12,12) unexpectedly passes: {baseline_pass}"
    )

    # No informative cell passes all three pre-registered criteria.
    assert passing_cells == [], (
        f"expected zero passing informative cells, got {passing_cells}"
    )


def test_no_cell_survives_protocol_multiplicity():
    """No nominal pass survives correction for the number of protocols.

    The DSR inside each cell corrects for the 2 lookback values only; it does
    not correct for the 4 protocols tried. A Bonferroni correction across the
    protocol family pushes the best nominal cell's p-value well above 0.10.
    """
    dsr_p_values = []
    best_idx = None
    best_p = None
    for i, protocol in enumerate(INFORMATIVE_PROTOCOLS):
        summary = _run_cell(protocol)
        dsr = summary.get("deflated_sharpe") or {}
        p = dsr.get("p_value")
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
