#!/usr/bin/env python3
"""Core falsifiable hypothesis test for Mean Reversion on the committed
single-asset panel (AAPL).

Uses the mean_reversion_hypothesis example (run_backtest.py CLI path):
benchmark-aware falsification (oos_sharpe > 0, oos_total_return > benchmark,
deflated Sharpe p < 0.10, benchmark alpha p < 0.05) net of 3bp round-trip
costs on the held-out test split. Pins observed metrics (regression guard,
relative tolerance, never exact equality).

Honest outcome on this committed window: Mean Reversion does NOT beat
buy-and-hold AAPL (Sharpe -0.1439, return -5.05% vs benchmark +17.78%), so
the verdict is NOT SUPPORTED. This test records the outcome honestly and does
not claim profitability; the verdict itself is not asserted (SUPPORTED and NOT
SUPPORTED are both valid scientific outcomes).

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from mean_reversion_hypothesis import run_hypothesis_test  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

REL_TOL = 1e-3

# Pinned to the committed AAPL fixture via run_backtest.py (test split,
# 3bp round-trip). Regression guard only -- never exact equality.
EXPECTED = {
    "sharpe_ratio": -0.1439393233148262,
    "total_return": -0.05051279837754248,
}


def test_hypothesis_mean_reversion_runs_on_aapl_real_window():
    assert (SRC / "AAPL.csv").exists()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_hypothesis_test(
            data_path=SRC / "AAPL.csv",
            label="AAPL",
            benchmark_path=None,
        )
    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["all_pass"] in (True, False)
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")
    assert len(result["criteria"]) == 4
    assert {c["name"] for c in result["criteria"]} == {
        "oos_sharpe_gt_zero",
        "oos_total_return_gt_benchmark",
        "deflated_sharpe_pvalue_lt_0.10",
        "benchmark_alpha_pvalue_lt_0.05",
    }
    out = buffer.getvalue()
    assert "VERDICT:" in out


def test_hypothesis_mean_reversion_metrics_pinned_on_aapl_real_window():
    assert (SRC / "AAPL.csv").exists()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_hypothesis_test(
            data_path=SRC / "AAPL.csv",
            label="AAPL",
            benchmark_path=None,
        )
    obs = result["observed"]
    for k, expv in EXPECTED.items():
        gotv = obs[k]
        assert abs(gotv - expv) <= REL_TOL * max(abs(expv), 1e-9), (
            f"{k} regression: got {gotv}, expected {expv}"
        )


if __name__ == "__main__":
    test_hypothesis_mean_reversion_runs_on_aapl_real_window()
    test_hypothesis_mean_reversion_metrics_pinned_on_aapl_real_window()
    print("OK")
