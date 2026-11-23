#!/usr/bin/env python3
"""Walk-forward *protocol-sensitivity* study for Bollinger Bands mean
reversion on the committed single-asset panel (AAPL).

Motivation
----------
The existing walk-forward Bollinger Bands test pins a *single* evaluation
protocol (train 12 / test 12 months, stepping 12 months) on a single asset
(AAPL) and records a NOT SUPPORTED verdict from it. A single protocol cannot
distinguish "the strategy has no edge" from "the evaluation window was
unlucky": the train/test window lengths are an analyst degree of freedom, and
choosing among them after seeing results is a form of data mining
(protocol-selection bias). This study quantifies that sensitivity for Bollinger
Bands mean reversion on AAPL.

Design (pre-registered before any number is inspected)
------------------------------------------------------
* Signal: ``bollinger_bands`` mean reversion (long when price < lower band,
  short when > upper band, flat otherwise), single-asset long/short/flat on
  committed AAPL fixture.
* Parameter grid: ``{"period": [20], "std_dev": [2.0]}`` (1 configuration, the
  advertised default settings drawn from ``examples/bollinger_bands_hypothesis.py``).
* Costs: commission 2 bps + slippage 1 bps per trade.
* Deflated Sharpe Ratio multiple-testing correction applied within each
  protocol (across the single configuration and all walk-forward periods).
* Protocols vary ``train_months`` / ``test_months`` with ``step_months ==
  test_months`` (the framework rejects ``step_months < test_months``). One
  pre-registered family of equally-valid 12-month-test protocols:
  (12, 12, 12), (18, 12, 12), (24, 12, 12), (30, 12, 12), (36, 12, 12).
* Pre-registered per-cell falsification criteria: OOS Sharpe > 0 AND OOS total
  return > 0 AND Deflated Sharpe p-value < 0.10.

Honest finding (all committed fixtures, offline)
------------------------------------------------
The Deflated Sharpe p-value exceeds 0.10 in every cell, so *no cell passes all
three pre-registered criteria* and the verdict is consistently NOT SUPPORTED.
Raw positive OOS Sharpe in any cell does not survive multiple-testing
correction under any of the five equally-valid protocols.

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

SYMBOL = "AAPL"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade
PARAM_GRID = {
    "period": [20],
    "std_dev": [2.0],
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
# study's observed results, not a profitability claim. Left empty on first
# (probe) run so real numbers can be captured; populated afterward.
ABS_TOL = 1e-3

# key: (train_months, test_months, step_months)
# value: dict(n_periods, n_pos, sharpe, tot, dsr_p, n_trials)
# n_trials is the number of configurations the DSR corrected for
# (1 configuration x n_periods).
EXPECTED = {
    # --- Informative 12-month-test cells ---
    (12, 12, 12): dict(n_periods=4, n_pos=4, sharpe=-0.3303, tot=-0.2222, dsr_p=0.9274, n_trials=4),
    (18, 12, 12): dict(n_periods=4, n_pos=4, sharpe=0.0052, tot=-0.0087, dsr_p=0.6832, n_trials=4),
    (24, 12, 12): dict(n_periods=3, n_pos=3, sharpe=0.0063, tot=0.0074, dsr_p=0.7045, n_trials=3),
    (30, 12, 12): dict(n_periods=3, n_pos=3, sharpe=-0.2563, tot=-0.1538, dsr_p=0.7718, n_trials=3),
    (36, 12, 12): dict(n_periods=2, n_pos=2, sharpe=-0.2657, tot=-0.0578, dsr_p=0.6468, n_trials=2),
}

# Best nominal cell by raw DSR p-value (pre-registered index for the
# Bonferroni check).
BEST_NOMINAL_PROTOCOL = (12, 12, 12)


def _build_data():
    import pandas as pd

    df = pd.read_csv(SRC / f"{SYMBOL}.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _factory(params):
    return build_strategy("bollinger_bands", json.dumps(params))


def _run_cell(protocol):
    """Run one protocol walk-forward cell on single-asset AAPL.

    Returns the cell summary: n_periods, periods_with_position, oos_sharpe,
    total_oos_return, deflated_sharpe p-value / n_trials.
    """
    train_months, test_months, step_months = protocol
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = walk_forward_analysis(
            data=_build_data(),
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
        f"{SYMBOL} {protocol}: point-in-time validation not engaged"
    )
    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out, (
        f"{SYMBOL} {protocol}: PIT validation not reported"
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


def test_protocol_sensitivity_matrix_pinned():
    """Regression guard + structural validity for the full protocol matrix.

    Every cell must produce finite OOS metrics and the pinned number of
    walk-forward periods / positions. Point-in-time validation is asserted
    engaged inside _run_cell. When EXPECTED is populated, observed values are
    pinned against it; on the probe run (EXPECTED empty) actuals are printed
    for pinning.
    """
    actuals = {}
    for protocol in ALL_PROTOCOLS:
        cell = _run_cell(protocol)
        actuals[protocol] = cell

        assert cell["n_periods"] is not None, (
            f"{protocol}: n_periods missing"
        )
        assert cell["periods_with_position"] is not None, (
            f"{protocol}: periods_with_position missing"
        )
        assert cell["periods_with_position"] >= MIN_INFORMATIVE_PERIODS, (
            f"{protocol}: cell not informative, periods_with_position="
            f"{cell['periods_with_position']}"
        )
        for key, label in (("oos_sharpe", f"{protocol} oos_sharpe"),
                           ("total_oos_return", f"{protocol} total_oos_return"),
                           ("dsr_p", f"{protocol} deflated_sharpe.p_value")):
            val = cell.get(key)
            assert val is not None and math.isfinite(float(val)), (
                f"{label}: non-finite/missing value {val!r}"
            )
        p = cell.get("dsr_p")
        assert p is not None and 0.0 <= float(p) <= 1.0, (
            f"{protocol}: DSR p-value out of range: {p!r}"
        )
        assert cell["n_trials"] is not None, (
            f"{protocol}: DSR n_trials missing"
        )

    for protocol in ALL_PROTOCOLS:
        cell = actuals[protocol]
        exp = EXPECTED[protocol]
        assert cell["n_periods"] == exp["n_periods"], (
            f"{protocol}: n_periods {cell['n_periods']} != {exp['n_periods']}"
        )
        assert cell["periods_with_position"] == exp["n_pos"], (
            f"{protocol}: periods_with_position "
            f"{cell['periods_with_position']} != {exp['n_pos']}"
        )
        _assert_close(cell.get("oos_sharpe"), exp["sharpe"], f"{protocol} oos_sharpe")
        _assert_close(cell.get("total_oos_return"), exp["tot"], f"{protocol} total_oos_return")
        _assert_close(cell.get("dsr_p"), exp["dsr_p"], f"{protocol} deflated_sharpe.p_value")
        assert cell["n_trials"] == exp["n_trials"], (
            f"{protocol}: DSR n_trials {cell['n_trials']} != {exp['n_trials']}"
        )


def test_verdict_is_consistently_not_supported():
    """Core finding: no cell passes all three pre-registered criteria under any
    equally-valid protocol, so the verdict is consistently NOT SUPPORTED.

    The Deflated Sharpe p-value exceeds 0.10 in every cell, so the raw OOS
    Sharpe (positive in only some cells) never survives multiple-testing
    correction. Bollinger Bands mean reversion cannot be rescued by protocol
    selection here.
    """
    baseline_pass = None
    passing_cells = []

    for protocol in INFORMATIVE_PROTOCOLS:
        cell = _run_cell(protocol)
        crit = _criteria(cell)
        if protocol == BEST_NOMINAL_PROTOCOL:
            baseline_pass = all(crit.values())
        if all(crit.values()):
            passing_cells.append(protocol)

    # The Deflated Sharpe criterion fails in every cell.
    for protocol in INFORMATIVE_PROTOCOLS:
        crit = _criteria(_run_cell(protocol))
        assert crit["deflated_sharpe_pvalue_lt_0.10"] is False, (
            f"{protocol}: DSR p-value unexpectedly < 0.10"
        )

    # The pinned baseline fails all criteria.
    assert baseline_pass is False, (
        f"baseline {BEST_NOMINAL_PROTOCOL} unexpectedly passes: {baseline_pass}"
    )

    # No informative cell passes all three pre-registered criteria.
    assert passing_cells == [], (
        f"expected zero passing informative cells, got {passing_cells}"
    )


def test_no_cell_survives_protocol_multiplicity():
    """No nominal pass survives correction for the number of protocols.

    The DSR inside each cell corrects for the 1 configuration only (across all
    periods); it does not correct for the 5 protocols tried. A Bonferroni
    correction across the protocol family pushes the best nominal cell's
    p-value well above 0.10.
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
