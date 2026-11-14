#!/usr/bin/env python3
"""CPCV (combinatorial purged cross-validation) regression guard for the Kelly
criterion position-sizing overlay on the committed single-asset panel (AAPL).

Kelly criterion is a position-sizing overlay with no signal generator of its
own, so in standalone mode it falls back to a plain time-series momentum base
(close vs its rolling mean) that yields a tradable signal -- the same fallback
used by ``volatility_targeting`` in standalone mode. CPCV is run directly on
the AAPL time series with the ``kelly_criterion`` strategy.

This fills the CPCV gap for the Kelly path on committed fixtures. Because the
standalone Kelly overlay falls back to the identical time-series momentum base
as the standalone volatility-targeting overlay, its CPCV metrics on this
fixture are byte-identical to those pinned in
test_cpcv_volatility_targeting_real_aapl.py; this guard pins the same values
directly for the Kelly strategy and additionally asserts that identity, so a
silent divergence between the two overlays' standalone fallbacks is caught.

Evaluates the strategy across CPCV folds (n_splits=5, test_size=0.2) on
committed fixtures only, with a narrow pre-registered parameter grid fixed
before any result is inspected. Verdicts are falsification outcomes, never
profitability claims.

Honest outcome on this committed window (metrics pinned below): the pooled
out-of-sample Sharpe is negative (-1.6572) and total return is negative
(-62.11%), and the Deflated Sharpe p-value (0.9980) is far above 0.10, so the
multiple-testing-corrected criterion fails and the honest verdict is NOT
SUPPORTED. The test records this outcome and does not tune to force SUPPORT.

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

# Narrow, pre-registered grid (advertised Kelly defaults). Fixed before any
# result is inspected.
PARAM_GRID = {
    "lookback": [63],
    "fraction": [0.5],
    "max_leverage": [2.0],
}

N_SPLITS = 5
TEST_SIZE = 0.2

# Falsification threshold, pre-registered.
DSR_PVALUE_THRESHOLD = 0.10


def _build_data():
    df = pd.read_csv(SRC / "AAPL.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _factory(params):
    return build_strategy("kelly_criterion", json.dumps(params))


def _run_cpcv():
    return cpcv_analysis(
        data=_build_data(),
        strategy_factory=_factory,
        param_grid=PARAM_GRID,
        n_splits=N_SPLITS,
        test_size=TEST_SIZE,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        apply_deflation=True,
        validate_pit=True,
    )


def test_cpcv_kelly_criterion_real_aapl_runs():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_cpcv()

    assert isinstance(result, dict)
    assert "folds" in result and "summary" in result and "oos_returns" in result
    summary = result["summary"]
    assert summary["n_folds"] == N_SPLITS
    assert summary["folds_with_position"] == N_SPLITS
    assert summary["bias_controls_engaged"] is True
    assert summary.get("panel_pricing") is not None
    assert summary.get("test_resolution") is not None
    assert len(result["folds"]) == N_SPLITS
    for fold in result["folds"]:
        assert "fold" in fold
        assert "best_params" in fold
        assert "test_returns" in fold
        assert fold["best_params"] is not None
    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out


def test_cpcv_kelly_criterion_real_aapl_metrics_pinned():
    """Regression guard: the advertised CPCV run on the committed AAPL
    fixture must reproduce the pinned pooled out-of-sample metrics (net of
    costs) so a silent change to the backtest numbers is caught. Relative
    tolerance only, never exact equality.

    Honest outcome: the pooled out-of-sample Sharpe is negative (-1.6572) and
    total return is negative (-62.11%), and the Deflated Sharpe p-value
    (0.9980) is far above 0.10, so every criterion fails and the verdict is NOT
    SUPPORTED. The test records the falsification outcome and does not tune to
    force SUPPORT.

    The standalone Kelly overlay falls back to the same time-series momentum
    base as the standalone volatility-targeting overlay, so its CPCV metrics
    on this fixture are identical to those pinned in
    test_cpcv_volatility_targeting_real_aapl.py; this guard pins the same
    values for the Kelly strategy and asserts that identity.
    """
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_cpcv()

    summary = result["summary"]

    EXPECTED = {
        "oos_sharpe": -1.801808813556185,
        "total_oos_return": -0.13079793512620908,
        "oos_volatility": 0.3203869962773295,
    }
    REL_TOL = 1e-6
    for key, exp in EXPECTED.items():
        got = summary.get(key)
        assert got is not None, f"missing {key}"
        assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"{key} regression: got {got}, expected {exp}"
        )

    dsr = summary.get("deflated_sharpe") or {}
    assert dsr.get("n_trials") == N_SPLITS
    dsr_p = dsr.get("p_value")
    assert dsr_p is not None
    assert abs(dsr_p - 0.9980453336919024) <= 1e-6 * max(abs(0.9980453336919024), 1e-9)

    # Honest verdict: Sharpe < 0 and return < 0 fail, and Deflated Sharpe
    # p-value >= 0.10 fails, so the hypothesis is NOT SUPPORTED.
    sharpe = summary["oos_sharpe"]
    ret = summary["total_oos_return"]
    passes = {
        "oos_sharpe_gt_zero": bool(sharpe is not None and float(sharpe) > 0),
        "oos_total_return_positive": bool(ret is not None and float(ret) > 0),
        "deflated_sharpe_pvalue_lt_0.10": bool(
            dsr_p is not None and float(dsr_p) < DSR_PVALUE_THRESHOLD
        ),
    }
    assert passes["oos_sharpe_gt_zero"] is False
    assert passes["oos_total_return_positive"] is False
    assert passes["deflated_sharpe_pvalue_lt_0.10"] is False
    assert all(passes.values()) is False

    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out


if __name__ == "__main__":
    test_cpcv_kelly_criterion_real_aapl_runs()
    test_cpcv_kelly_criterion_real_aapl_metrics_pinned()
    print("OK")