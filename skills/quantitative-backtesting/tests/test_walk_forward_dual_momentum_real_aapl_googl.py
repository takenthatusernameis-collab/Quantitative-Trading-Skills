#!/usr/bin/env python3
"""Walk-forward out-of-sample falsification test for dual momentum (absolute +
relative momentum, long-only) on the committed pair panel (AAPL / GOOGL).

Evaluates dual momentum across chronological walk-forward windows (train 12 /
test 12 months, stepping 12 months) on committed fixtures only, with a
pre-registered parameter grid and the Deflated Sharpe Ratio multiple-testing
correction applied to the pooled out-of-sample record.

Verdicts are falsification outcomes, never profitability claims.

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

from walk_forward import walk_forward_analysis
from strategy_builder import build_strategy

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade

PARAM_GRID = {
    "lookback": [189, 252],
    "top_quantile": [0.5],
    "risk_free_rate": [0.0],
}

TRAIN_MONTHS = 12
TEST_MONTHS = 12
STEP_MONTHS = 12


def _build_panel():
    panel = {}
    for name in ("AAPL.csv", "GOOGL.csv"):
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        panel[Path(name).stem] = df
    return panel


def _factory(params):
    return build_strategy("dual_momentum", json.dumps(params))


def _run_walk_forward():
    return walk_forward_analysis(
        data=_build_panel(),
        strategy_factory=_factory,
        param_grid=PARAM_GRID,
        train_months=TRAIN_MONTHS,
        test_months=TEST_MONTHS,
        step_months=STEP_MONTHS,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        panel_pricing="book",
        apply_deflation=True,
        validate_pit=True,
    )


def test_walk_forward_dual_momentum_pairs_real_aapl_googl_structure():
    for name in ("AAPL.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_walk_forward()

    assert isinstance(result, dict)
    assert "periods" in result and "summary" in result
    summary = result["summary"]
    assert summary["n_periods"] >= 1
    assert summary["bias_controls_engaged"] is True
    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out


if __name__ == "__main__":
    test_walk_forward_dual_momentum_pairs_real_aapl_googl_structure()
    print("OK")
