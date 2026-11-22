#!/usr/bin/env python3
"""Walk-forward *protocol-sensitivity* study for standalone time-series
momentum (TSMOM) on the committed single-asset panels (AAPL, MSFT, GOOGL).

Motivation
----------
The existing walk-forward TSMOM tests pin a *single* evaluation protocol
(train 24 / test 12 / step 12 months) and record a NOT SUPPORTED verdict from
it. A single protocol cannot distinguish "the strategy has no edge" from
"the evaluation window was unlucky": the train/test window lengths are an
analyst degree of freedom, and choosing among them after seeing results is a
form of data mining (protocol-selection bias). This study quantifies that
sensitivity.

Design (pre-registered before any number is inspected)
-------------------------------------------------------
* Signal: ``time_series_momentum`` (long when the trailing return over
  ``lookback`` days is positive, flat otherwise), single asset.
* Lookback grid: ``{126, 189, 252}`` trading days (3 configurations, the same
  grid the single-protocol tests use).
* Costs: commission 2 bps + slippage 1 bps per trade (the shipped default).
* Deflated Sharpe Ratio multiple-testing correction is applied *within* each
  protocol (across the 3 lookback values).
* Protocols vary ``train_months`` and ``test_months`` with ``step_months ==
  test_months`` (the framework rejects ``step_months < test_months`` to avoid
  overlapping OOS windows). Two families are examined:
    - 12-month-test protocols (informative: the test window is longer than the
      longest 252-day lookback, so the signal is defined throughout):
      (24, 12, 12), (36, 12, 12), (18, 12, 12), (30, 12, 12).
    - 6-month-test protocols (short-window family: the test window is shorter
      than the 189/252-day lookbacks, which is itself a pitfall documented
      below): (36, 6, 6), (24, 6, 6).
* Pre-registered per-cell falsification criteria (identical to the
  single-protocol tests): OOS Sharpe > 0 AND OOS total return > 0 AND
  Deflated Sharpe p-value < 0.10.

Honest finding (all committed fixtures, offline)
-----------------------------------------------
The OOS verdict is strongly *protocol-dependent*:

* Every symbol's OOS Sharpe flips sign across the four equally-valid
  12-month-test protocols (AAPL -0.39 -> +1.06, MSFT -0.41 -> +1.22,
  GOOGL -0.21 -> +0.10). The pinned 24/12/12 NOT SUPPORTED verdict is therefore
  protocol-conditional, not a property of the strategy alone.
* Exactly 1 of the 12 informative (symbol x protocol) cells passes all three
  criteria: MSFT at (30, 12, 12). The other 11 fail.
* That lone pass is (a) isolated -- the other MSFT protocols fail, and (b) does
  not survive a Bonferroni correction for the four 12-month protocols tried on
  MSFT (p = 0.0696 * 4 = 0.278 > 0.10). It is consistent with protocol-
  selection noise, not a demonstrated edge.
* The 6-month-test protocols are *uninformative*: the test window is shorter
  than the 126/189/252-day lookbacks, so the strategy is flat for almost the
  entire window (periods_with_position <= 1) and must not be read as evidence
  against the hypothesis.

Conclusion: no robust profitability claim is warranted in either direction from
this matrix. A single protocol cannot establish or falsify TSMOM; any future
SUPPORT/NOT-SUPPORT claim must be pre-registered on held-out data not used to
select the protocol. This study exists to make that limitation explicit and
regression-guarded.

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

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade
LOOKBACK_GRID = {"lookback": [126, 189, 252]}
DSR_PVALUE_THRESHOLD = 0.10

# Informative protocols: 12-month test windows (>= the 252-day lookback).
INFORMATIVE_PROTOCOLS = [(24, 12, 12), (36, 12, 12), (18, 12, 12), (30, 12, 12)]
# Short-window family: 6-month test windows (< the 189/252-day lookbacks).
SHORT_WINDOW_PROTOCOLS = [(36, 6, 6), (24, 6, 6)]
ALL_PROTOCOLS = INFORMATIVE_PROTOCOLS + SHORT_WINDOW_PROTOCOLS
SYMBOLS = ["AAPL", "MSFT", "GOOGL"]

# A cell is "informative" when the strategy actually held a position for at
# least this many walk-forward periods; below it the OOS record is flat /
# undefined and cannot falsify the hypothesis.
MIN_INFORMATIVE_PERIODS = 2

# Pinned evidence matrix. Values are rounded to 4 decimals for readability and
# compared with ABS_TOL (see _assert_close). This is a regression guard on the
# study's observed results, not a profitability claim.
ABS_TOL = 1e-3

# key: (symbol, (train_months, test_months, step_months))
# value: dict(n_periods, n_pos, sharpe, tot, dsr_p, n_trials)
# n_trials is the number of configurations the within-protocol DSR corrected for.
EXPECTED = {
    # --- Informative 12-month-test cells ---
    ("AAPL", (24, 12, 12)): dict(n_periods=3, n_pos=3, sharpe=-0.3885, tot=-0.0598, dsr_p=0.9746, n_trials=5),
    ("AAPL", (36, 12, 12)): dict(n_periods=2, n_pos=2, sharpe=1.0575, tot=0.2235, dsr_p=0.1021, n_trials=4),
    ("AAPL", (18, 12, 12)): dict(n_periods=4, n_pos=4, sharpe=-0.0288, tot=0.0247, dsr_p=0.8231, n_trials=7),
    ("AAPL", (30, 12, 12)): dict(n_periods=3, n_pos=3, sharpe=0.5345, tot=0.2428, dsr_p=0.3170, n_trials=5),
    ("MSFT", (24, 12, 12)): dict(n_periods=3, n_pos=3, sharpe=-0.4138, tot=-0.1018, dsr_p=0.9569, n_trials=5),
    ("MSFT", (36, 12, 12)): dict(n_periods=2, n_pos=2, sharpe=-0.3358, tot=-0.0726, dsr_p=0.8325, n_trials=4),
    ("MSFT", (18, 12, 12)): dict(n_periods=4, n_pos=4, sharpe=0.4950, tot=0.3306, dsr_p=0.4330, n_trials=8),
    ("MSFT", (30, 12, 12)): dict(n_periods=3, n_pos=3, sharpe=1.2195, tot=0.6403, dsr_p=0.0696, n_trials=6),
    ("GOOGL", (24, 12, 12)): dict(n_periods=3, n_pos=2, sharpe=-0.1162, tot=-0.0245, dsr_p=0.6223, n_trials=4),
    ("GOOGL", (36, 12, 12)): dict(n_periods=2, n_pos=2, sharpe=-0.1162, tot=-0.0245, dsr_p=0.6223, n_trials=4),
    ("GOOGL", (18, 12, 12)): dict(n_periods=4, n_pos=4, sharpe=-0.2120, tot=-0.0707, dsr_p=0.9658, n_trials=8),
    ("GOOGL", (30, 12, 12)): dict(n_periods=3, n_pos=3, sharpe=0.0979, tot=0.0711, dsr_p=0.5814, n_trials=6),
    # --- Short-window (degenerate) cells: no meaningful OOS position record ---
    ("AAPL", (36, 6, 6)): dict(n_periods=5, n_pos=1),
    ("AAPL", (24, 6, 6)): dict(n_periods=7, n_pos=1),
    ("MSFT", (36, 6, 6)): dict(n_periods=5, n_pos=0),
    ("MSFT", (24, 6, 6)): dict(n_periods=7, n_pos=0),
    ("GOOGL", (36, 6, 6)): dict(n_periods=5, n_pos=1),
    ("GOOGL", (24, 6, 6)): dict(n_periods=7, n_pos=1),
}

# The single informative cell that passes all three pre-registered criteria.
EXPECTED_SOLE_PASS = ("MSFT", (30, 12, 12))


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
    # Point-in-time validation is engaged on every cell.
    assert summary.get("bias_controls_engaged") is True, (
        f"{symbol} {protocol}: point-in-time validation not engaged"
    )
    return summary


def _criteria(summary):
    """Pre-registered per-cell criteria -> dict of booleans (NaN-safe)."""
    sharpe = summary.get("oos_sharpe")
    tot = summary.get("total_oos_return")
    dsr = summary.get("deflated_sharpe") or {}
    p = dsr.get("p_value")
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


def test_protocol_sensitivity_matrix_pinned():
    """Regression guard + structural validity for the full protocol x symbol
    matrix (12 informative + 6 short-window cells).

    Informative cells must produce finite OOS metrics; short-window cells must
    stay degenerate (periods_with_position <= 1). Point-in-time validation is
    asserted engaged inside _run_cell.
    """
    for symbol in SYMBOLS:
        for protocol in ALL_PROTOCOLS:
            summary = _run_cell(symbol, protocol)
            exp = EXPECTED[(symbol, protocol)]

            assert summary["n_periods"] == exp["n_periods"], (
                f"{symbol} {protocol}: n_periods {summary['n_periods']} != {exp['n_periods']}"
            )
            assert summary["periods_with_position"] == exp["n_pos"], (
                f"{symbol} {protocol}: periods_with_position "
                f"{summary['periods_with_position']} != {exp['n_pos']}"
            )

            if "sharpe" in exp:
                # Informative cell: metrics must be present and finite.
                _assert_close(summary.get("oos_sharpe"), exp["sharpe"], f"{symbol} {protocol} oos_sharpe")
                _assert_close(summary.get("total_oos_return"), exp["tot"], f"{symbol} {protocol} total_oos_return")
                dsr = summary.get("deflated_sharpe") or {}
                _assert_close(dsr.get("p_value"), exp["dsr_p"], f"{symbol} {protocol} deflated_sharpe.p_value")
                assert dsr.get("n_trials") == exp["n_trials"], (
                    f"{symbol} {protocol}: DSR n_trials {dsr.get('n_trials')} != {exp['n_trials']}"
                )
                p = dsr.get("p_value")
                assert p is not None and 0.0 <= float(p) <= 1.0, (
                    f"{symbol} {protocol}: DSR p-value out of range: {p!r}"
                )
            else:
                # Short-window cell: must remain uninformative.
                assert summary["periods_with_position"] <= 1, (
                    f"{symbol} {protocol}: expected degenerate short-window cell, "
                    f"got periods_with_position={summary['periods_with_position']}"
                )


def test_verdict_is_protocol_dependent():
    """Core finding: the OOS Sharpe sign flips across equally-valid protocols
    for every symbol, and the pinned 24/12/12 baseline fails everywhere.

    This is why a single protocol cannot establish a TSMOM verdict.
    """
    per_symbol_sharpes = {sym: [] for sym in SYMBOLS}
    baseline_pass = {}
    passing_cells = []

    for symbol in SYMBOLS:
        for protocol in INFORMATIVE_PROTOCOLS:
            summary = _run_cell(symbol, protocol)
            assert summary["periods_with_position"] >= MIN_INFORMATIVE_PERIODS
            sharpe = summary["oos_sharpe"]
            assert sharpe is not None and math.isfinite(sharpe)
            per_symbol_sharpes[symbol].append(sharpe)

            crit = _criteria(summary)
            if protocol == (24, 12, 12):
                baseline_pass[symbol] = all(crit.values())
            if all(crit.values()):
                passing_cells.append((symbol, protocol))

    # (1) Sign flip per symbol across informative protocols.
    for symbol in SYMBOLS:
        sharpes = per_symbol_sharpes[symbol]
        assert min(sharpes) < 0.0 < max(sharpes), (
            f"{symbol}: expected OOS Sharpe to change sign across protocols, "
            f"got min={min(sharpes)} max={max(sharpes)}"
        )

    # (2) The pinned 24/12/12 baseline fails for every symbol (matches the
    #     single-protocol tests' NOT SUPPORTED verdicts).
    assert baseline_pass == {sym: False for sym in SYMBOLS}, (
        f"baseline (24,12,12) unexpectedly passes somewhere: {baseline_pass}"
    )

    # (3) Exactly one informative cell passes all three criteria.
    assert len(passing_cells) == 1, (
        f"expected exactly one passing informative cell, got {passing_cells}"
    )
    assert passing_cells[0] == EXPECTED_SOLE_PASS, (
        f"expected the sole pass at {EXPECTED_SOLE_PASS}, got {passing_cells[0]}"
    )


def test_sole_pass_does_not_survive_protocol_multiplicity():
    """The one nominal pass is isolated and dies under a correction for the
    number of protocols examined.

    DSR inside the passing cell corrects for the 3 lookback values only; it
    does not correct for the 4 protocols tried on MSFT. A Bonferroni
    correction across those 4 protocols pushes the p-value above 0.10.
    """
    summary = _run_cell(*EXPECTED_SOLE_PASS)
    dsr = summary.get("deflated_sharpe") or {}
    p = dsr.get("p_value")
    assert p is not None, "sole-pass cell has no Deflated Sharpe p-value"

    n_protocols = len(INFORMATIVE_PROTOCOLS)
    corrected = float(p) * n_protocols
    assert corrected > DSR_PVALUE_THRESHOLD, (
        f"sole-pass DSR p={p} x {n_protocols} protocols = {corrected} should "
        f"exceed {DSR_PVALUE_THRESHOLD} (not robust to protocol multiplicity)"
    )

    # Isolation: the other MSFT informative protocols must not all pass.
    symbol = EXPECTED_SOLE_PASS[0]
    other_pass = []
    for protocol in INFORMATIVE_PROTOCOLS:
        if protocol == EXPECTED_SOLE_PASS[1]:
            continue
        crit = _criteria(_run_cell(symbol, protocol))
        if all(crit.values()):
            other_pass.append(protocol)
    assert other_pass == [], (
        f"{symbol}: the sole pass is not isolated, other protocols also pass: {other_pass}"
    )


def test_short_test_windows_are_uninformative():
    """6-month test windows are shorter than the 189/252-day lookbacks, so the
    strategy is flat for almost the whole window. Such cells carry no OOS
    evidence and must never be counted as a NOT SUPPORTED verdict.
    """
    for symbol in SYMBOLS:
        for protocol in SHORT_WINDOW_PROTOCOLS:
            summary = _run_cell(symbol, protocol)
            npos = summary["periods_with_position"]
            assert npos <= 1, (
                f"{symbol} {protocol}: short test window should leave the "
                f"strategy essentially flat, got periods_with_position={npos}"
            )
            sharpe = summary.get("oos_sharpe")
            # Flat / undefined OOS record only.
            assert sharpe is None or float(sharpe) == 0.0, (
                f"{symbol} {protocol}: expected flat OOS Sharpe (0 or None), got {sharpe!r}"
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
    ("sole_pass_does_not_survive_protocol_multiplicity", test_sole_pass_does_not_survive_protocol_multiplicity),
    ("short_test_windows_are_uninformative", test_short_test_windows_are_uninformative),
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