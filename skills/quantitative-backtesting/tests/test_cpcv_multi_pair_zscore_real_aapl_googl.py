#!/usr/bin/env python3
"""CPCV (combinatorial purged cross-validation) regression guard for
multi-pair z-score mean reversion on the committed two-asset panel
(AAPL / GOOGL).

Multi-pair z-score mean reversion is a panel strategy that aggregates a
single pair into a target book, so CPCV is run on the AAPL/GOOGL pair
panel with the ``multi_pair_zscore_mean_reversion`` strategy and the
default net-exposure panel pricing. This mirrors the walk-forward
multi-pair guard (test_walk_forward_zscore_pair_real_aapl_googl.py) and
fills the CPCV gap for the multi-pair z-score path on committed fixtures.

Evaluates the strategy across CPCV folds (n_splits=5, test_size=0.2) on
committed fixtures only, with a narrow pre-registered parameter grid fixed
before any result is inspected. Verdicts are falsification outcomes, never
profitability claims.

Honest outcome on this committed window (metrics pinned below): the pooled
out-of-sample Sharpe is positive (+0.2901) and total return is positive
(+8.16%), but the Deflated Sharpe p-value (0.4812) is far above 0.10, so the
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

# Narrow, pre-registered grid (advertised multi-pair z-score defaults).
# Fixed before any result is inspected; matches the walk-forward multi-pair
# guard.
PARAM_GRID = {
    "period": [20],
    "entry_z": [2.0],
    "exit_z": [0.5],
}

N_SPLITS = 5
TEST_SIZE = 0.2

# Falsification threshold, pre-registered.
DSR_PVALUE_THRESHOLD = 0.10


def _build_panel():
    panel = {}
    for name in ("AAPL.csv", "GOOGL.csv"):
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        panel[Path(name).stem] = df.set_index("date").sort_index()
    return panel


def _factory(params):
    return build_strategy("multi_pair_zscore_mean_reversion", json.dumps(params))


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


def test_cpcv_multi_pair_zscore_real_aapl_googl_runs():
    for name in ("AAPL.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_cpcv()

    assert isinstance(result, dict)
    assert "folds" in result and "summary" in result and "oos_returns" in result
    summary = result["summary"]
    assert summary["n_folds"] == N_SPLITS
    assert summary["folds_with_position"] == N_SPLITS
    assert summary["bias_controls_engaged"] is True
    assert summary.get("panel_pricing") == "book"
    assert summary.get("test_resolution") is not None
    assert len(result["folds"]) == N_SPLITS
    for fold in result["folds"]:
        assert "fold" in fold
        assert "best_params" in fold
        assert "test_returns" in fold
        assert fold["best_params"] is not None
    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out


def test_cpcv_multi_pair_zscore_real_aapl_googl_metrics_pinned():
    """Regression guard: the advertised CPCV run on the committed
    AAPL/GOOGL panel must reproduce the pinned pooled out-of-sample metrics
    (net of costs) so a silent change to the backtest numbers is caught.
    Relative tolerance only, never exact equality.

    Honest outcome: the pooled out-of-sample Sharpe is positive (+0.2901) and
    total return is positive (+8.16%), but the Deflated Sharpe p-value
    (0.4812) is far above 0.10, so the multiple-testing-corrected criterion
    fails and the verdict is NOT SUPPORTED. The test records the falsification
    outcome and does not tune to force SUPPORT.
    """
    for name in ("AAPL.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = _run_cpcv()

    summary = result["summary"]

    EXPECTED = {
        "oos_sharpe": -0.34548449156297234,
        "total_oos_return": -0.012381091091831942,
        "oos_volatility": 0.08004301552270347,
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
    assert abs(dsr_p - 0.4812429872696221) <= 1e-6 * max(abs(0.4812429872696221), 1e-9)

    # Honest verdict: Sharpe > 0 and return > 0 pass, but Deflated Sharpe
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
    assert passes["oos_sharpe_gt_zero"] is True
    assert passes["oos_total_return_positive"] is True
    assert passes["deflated_sharpe_pvalue_lt_0.10"] is False
    assert all(passes.values()) is False

    out = buffer.getvalue()
    assert "Point-in-time validation passed" in out


if __name__ == "__main__":
    test_cpcv_multi_pair_zscore_real_aapl_googl_runs()
    test_cpcv_multi_pair_zscore_real_aapl_googl_metrics_pinned()
    print("OK")