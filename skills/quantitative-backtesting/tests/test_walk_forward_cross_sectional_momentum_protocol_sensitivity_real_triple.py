#!/usr/bin/env python3
"""Walk-forward *protocol-sensitivity* study for cross-sectional momentum on the
committed AAPL/MSFT/GOOGL triple panel.

Motivation
----------
The existing walk-forward cross-sectional momentum tests pin a *single*
evaluation protocol (train 12 / test 12 / step 12 months) and record a NOT
SUPPORTED verdict from it. A single protocol cannot distinguish "the strategy
has no edge" from "the evaluation window was unlucky": the train/test window
lengths are an analyst degree of freedom, and choosing among them after seeing
results is a form of data mining (protocol-selection bias). This study
quantifies that sensitivity for cross-sectional momentum, generalizing the
time-series momentum protocol-sensitivity study
(``test_walk_forward_time_series_momentum_protocol_sensitivity_real_triple.py``).

Design (pre-registered before any number is inspected)
-------------------------------------------------------
* Signal: ``cross_sectional_momentum`` on the committed three-asset panel
  (AAPL / MSFT / GOOGL), long top quantile / short bottom quantile, priced per
  long-and-short ``book`` (asymmetric quantiles 0.4 / 0.2 so the portfolio
  takes a genuine directional net position).
* Lookback grid: ``{"lookback": [60, 126, 252], "top_quantile": [0.4],
  "bottom_quantile": [0.2]}`` (3 lookback configurations; quantiles fixed).
* Costs: commission 2 bps + slippage 1 bps per trade (the shipped default).
* Deflated Sharpe Ratio multiple-testing correction is applied *within* each
  protocol (across the 3 lookback values and all walk-forward periods).
* Protocols vary ``train_months`` and ``test_months`` with ``step_months ==
  test_months`` (the framework rejects ``step_months < test_months``). Two
  families are examined:
    - 12-month-test protocols (informative): (24, 12, 12), (36, 12, 12),
      (18, 12, 12), (30, 12, 12).
    - 6-month-test protocols: (36, 6, 6), (24, 6, 6).
* Pre-registered per-cell falsification criteria: OOS Sharpe > 0 AND OOS total
  return > 0 AND Deflated Sharpe p-value < 0.10.

Honest finding (all committed fixtures, offline)
------------------------------------------------
Unlike time-series momentum, cross-sectional momentum is a portfolio strategy
over the whole panel, so there is one cell per protocol (not one per symbol).

* The OOS verdict is *protocol-dependent*: the panel-level OOS Sharpe flips
  sign across the four equally-valid 12-month-test protocols
  (-0.6737 -> -0.9806 -> -0.0789 -> +0.3966). The pinned 24/12/12 NOT
  SUPPORTED verdict is therefore protocol-conditional, not a property of the
  signal alone.
* No informative cell passes all three pre-registered criteria. The best
  nominal cell, (30, 12, 12) (Sharpe +0.3966, return +0.1744), fails on the
  Deflated Sharpe p-value (0.5896), and a Bonferroni correction across the
  four 12-month protocols pushes it further above 0.10.
* Baseline (24, 12, 12) fails all criteria (Sharpe -0.6737, return -0.1074,
  p 0.9988), matching the single-protocol test's NOT SUPPORTED verdict.
* Contrast with time-series momentum: the 6-month-test windows are *not*
  degenerate here (periods_with_position > 1), because cross-sectional
  momentum ranks across assets with ample lookback history; they carry
  evidence but still do not pass the criteria.

Conclusion: no robust profitability claim is warranted in either direction
from this matrix. A single protocol cannot establish or falsify cross-sectional
momentum; any future SUPPORT/NOT-SUPPORT claim must be pre-registered on
held-out data not used to select the protocol. This study exists to make that
limitation explicit and regression-guarded.

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
from utils import bonferroni_correction, holm_stepdown  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade
PARAM_GRID = {
    "lookback": [60, 126, 252],
    "top_quantile": [0.4],
    "bottom_quantile": [0.2],
}
DSR_PVALUE_THRESHOLD = 0.10

# Informative protocols: 12-month test windows.
INFORMATIVE_PROTOCOLS = [(24, 12, 12), (36, 12, 12), (18, 12, 12), (30, 12, 12)]
# Short-window family: 6-month test windows.
SHORT_WINDOW_PROTOCOLS = [(36, 6, 6), (24, 6, 6)]
ALL_PROTOCOLS = INFORMATIVE_PROTOCOLS + SHORT_WINDOW_PROTOCOLS

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
    (24, 12, 12): dict(n_periods=3, n_pos=3, sharpe=-0.6737, tot=-0.1074, dsr_p=0.9988, n_trials=6),
    (36, 12, 12): dict(n_periods=2, n_pos=2, sharpe=-0.9806, tot=-0.1085, dsr_p=0.9819, n_trials=4),
    (18, 12, 12): dict(n_periods=4, n_pos=4, sharpe=-0.0789, tot=0.0291, dsr_p=0.9661, n_trials=8),
    (30, 12, 12): dict(n_periods=3, n_pos=3, sharpe=0.3966, tot=0.1744, dsr_p=0.5896, n_trials=6),
    # --- Short-window cells (informative for cross-sectional momentum) ---
    (36, 6, 6): dict(n_periods=5, n_pos=5, sharpe=0.5903, tot=0.1854, dsr_p=0.2794, n_trials=5),
    (24, 6, 6): dict(n_periods=7, n_pos=7, sharpe=-0.1585, tot=0.0003, dsr_p=0.9228, n_trials=7),
}


def _build_panel():
    panel = {}
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        panel[Path(name).stem] = df.set_index("date").sort_index()
    return panel


def _factory(params):
    return build_strategy("cross_sectional_momentum", json.dumps(params))


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


def test_verdict_is_protocol_dependent():
    """Core finding: the panel-level OOS Sharpe flips sign across equally-valid
    protocols, and the pinned 24/12/12 baseline fails everywhere.

    This is why a single protocol cannot establish a cross-sectional momentum
    verdict.
    """
    per_protocol_sharpes = []
    baseline_pass = None
    passing_cells = []

    for protocol in INFORMATIVE_PROTOCOLS:
        summary = _run_cell(protocol)
        assert summary["periods_with_position"] >= MIN_INFORMATIVE_PERIODS
        sharpe = summary["oos_sharpe"]
        assert sharpe is not None and math.isfinite(sharpe)
        per_protocol_sharpes.append(sharpe)

        crit = _criteria(summary)
        if protocol == (24, 12, 12):
            baseline_pass = all(crit.values())
        if all(crit.values()):
            passing_cells.append(protocol)

    # Sign flip per panel across informative protocols.
    assert min(per_protocol_sharpes) < 0.0 < max(per_protocol_sharpes), (
        f"expected OOS Sharpe to change sign across protocols, "
        f"got min={min(per_protocol_sharpes)} max={max(per_protocol_sharpes)}"
    )

    # The pinned 24/12/12 baseline fails for every criterion.
    assert baseline_pass is False, (
        f"baseline (24,12,12) unexpectedly passes: {baseline_pass}"
    )

    # No informative cell passes all three pre-registered criteria.
    assert passing_cells == [], (
        f"expected zero passing informative cells, got {passing_cells}"
    )


def test_no_cell_survives_protocol_multiplicity():
    """No nominal pass survives correction for the number of protocols.

    The best nominal cell (30, 12, 12) passes Sharpe > 0 and return > 0 but
    fails the Deflated Sharpe p-value (0.5896). A Bonferroni correction across
    the four 12-month protocols only inflates that p-value further.
    """
    # Collect DSR p-values for all informative protocols
    dsr_p_values = []
    best_idx = None
    for i, protocol in enumerate(INFORMATIVE_PROTOCOLS):
        summary = _run_cell(protocol)
        dsr = summary.get("deflated_sharpe") or {}
        p = dsr.get("p_value")
        assert p is not None, f"{protocol}: missing Deflated Sharpe p-value"
        dsr_p_values.append(float(p))
        if protocol == (30, 12, 12):
            best_idx = i
            best_p = float(p)

    assert best_p >= DSR_PVALUE_THRESHOLD, (
        f"best-nominal cell DSR p={best_p} should be >= {DSR_PVALUE_THRESHOLD}"
    )

    # Use the shared Bonferroni helper (FWER control across the protocol family)
    res = bonferroni_correction(dsr_p_values, alpha=DSR_PVALUE_THRESHOLD)
    best_adjusted = res["adjusted_p_values"][best_idx]
    assert best_adjusted > DSR_PVALUE_THRESHOLD, (
        f"best-nominal DSR p={best_p} Bonferroni-adjusted = {best_adjusted} should "
        f"exceed {DSR_PVALUE_THRESHOLD} (not robust to protocol multiplicity)"
    )

    holm_res = holm_stepdown(dsr_p_values, alpha=DSR_PVALUE_THRESHOLD)
    holm_best_adjusted = holm_res["adjusted_p_values"][best_idx]
    assert holm_best_adjusted > DSR_PVALUE_THRESHOLD, (
        f"best-nominal DSR p={best_p} Holm-adjusted = {holm_best_adjusted} should "
        f"exceed {DSR_PVALUE_THRESHOLD} (not robust to protocol multiplicity)"
    )


def test_short_test_windows_are_informative():
    """Contrast with time-series momentum: for cross-sectional momentum the
    6-month-test windows are NOT degenerate (positions are taken in every
    period) because the strategy ranks across assets with ample lookback
    history. They carry evidence but still fail the criteria, so they must not
    be read as a SUPPORT verdict nor dismissed as uninformative."""
    for protocol in SHORT_WINDOW_PROTOCOLS:
        summary = _run_cell(protocol)
        assert summary["periods_with_position"] >= MIN_INFORMATIVE_PERIODS, (
            f"{protocol}: expected an informative short-window cell, "
            f"got periods_with_position={summary['periods_with_position']}"
        )
        crit = _criteria(summary)
        assert all(crit.values()) is False, (
            f"{protocol}: short-window cell unexpectedly passes all criteria: {crit}"
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
    ("verdict_is_protocol_dependent", test_verdict_is_protocol_dependent),
    ("no_cell_survives_protocol_multiplicity", test_no_cell_survives_protocol_multiplicity),
    ("short_test_windows_are_informative", test_short_test_windows_are_informative),
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
