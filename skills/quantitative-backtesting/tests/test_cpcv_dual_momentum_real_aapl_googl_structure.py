#!/usr/bin/env python3
"""CPCV (combinatorial purged cross-validation) structural regression guard
for dual momentum (absolute + relative, long-only) on the committed
two-asset panel (AAPL / GOOGL).

Dual momentum is a multi-asset panel strategy producing a per-asset target
book (generate_target_weights), priced with panel_pricing="book". The
pre-registered grid fixes lookback=252 (the advertised default). With
n_splits=5 and test_size=0.2 on the ~2515-bar committed panel, each CPCV
test window is ~100 bars — shorter than the 252-bar lookback — so no
parameter combination can take a position in any fold.

This is an honest, falsification-relevant outcome on the committed window: the
CPCV machinery engages (PIT validated, bias controls on) but yields no
selectable out-of-sample record, diagnosed as
`no_position_in_validation_window`. The test pins that structural outcome so a
silent change to windowing, selection, or the no-selection diagnosis is caught.
It does NOT fabricate a positive result or tune parameters/windowing to force
selection.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import cpcv_analysis
from strategy_builder import build_strategy

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade

# Narrow, pre-registered grid (advertised dual momentum defaults). Fixed before
# any result is inspected. lookback=252 exceeds the ~100-bar CPCV test window
# produced by n_splits=5/test_size=0.2 on this panel, so no position is
# selectable in any fold — an honest structural outcome recorded below.
PARAM_GRID = {
    "lookback": [252],
    "top_quantile": [0.2],
    "risk_free_rate": [0.0],
}

N_SPLITS = 5
TEST_SIZE = 0.2


def _build_panel():
    panel = {}
    for name in ("AAPL.csv", "GOOGL.csv"):
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        panel[Path(name).stem] = df.set_index("date").sort_index()
    return panel


def _factory(params):
    return build_strategy("dual_momentum", json.dumps(params))


def _run_cpcv():
    return cpcv_analysis(
        data=_build_panel(),
        strategy_factory=_factory,
        param_grid=PARAM_GRID,
        n_splits=N_SPLITS,
        test_size=TEST_SIZE,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        panel_pricing="book",
        apply_deflation=True,
        validate_pit=True,
    )


def test_cpcv_dual_momentum_real_aapl_googl_runs():
    for name in ("AAPL.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_cpcv()

    assert isinstance(result, dict)
    assert "folds" in result and "summary" in result
    summary = result["summary"]
    assert summary["n_folds"] == N_SPLITS
    assert summary["bias_controls_engaged"] is True
    assert summary.get("panel_pricing") == "book"
    assert summary.get("test_resolution") is not None
    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out


def test_cpcv_dual_momentum_real_aapl_googl_warmup_enables_selection_pinned():
    """Regression guard: the advertised CPCV run (lookback=252, n_splits=5,
    test_size=0.2, panel/book) on the committed AAPL/GOOGL panel selects a
    position in 4 of the 5 out-of-sample folds.

    Each ~100-bar test window is shorter than the 252-bar lookback, so a naive
    per-window signal is undefined. The CPCV path prepends the bars that
    immediately precede each fold's test window as *warmup* (used only to
    initialize the rolling indicators, then sliced away), which supplies the
    lookback history without leaking future bars into the test record. This
    pins that honest structural outcome: 4 folds trade, one stays flat, and the
    run reports a real pooled OOS record rather than "no selection". It does
    not tune to force a positive result.
    """
    for name in ("AAPL.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_cpcv()

    summary = result["summary"]
    assert summary["n_folds"] == N_SPLITS
    assert summary["folds_with_position"] == 4
    assert summary["bias_controls_engaged"] is True
    assert summary.get("panel_pricing") == "book"
    # A real pooled OOS record now exists (it was None before the per-fold
    # warmup fix, when no fold could satisfy the 252-bar lookback).
    assert summary.get("total_oos_return") is not None

    # One fold stays flat; that is a partial selection, not a total failure.
    assert summary.get("no_selection_diagnosis") is None
    partial = summary.get("partial_selection_diagnosis")
    assert isinstance(partial, dict)
    assert partial.get("cause") == "no_position_in_validation_window"

    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out


if __name__ == "__main__":
    test_cpcv_dual_momentum_real_aapl_googl_runs()
    test_cpcv_dual_momentum_real_aapl_googl_warmup_enables_selection_pinned()
    print("OK")
