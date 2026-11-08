#!/usr/bin/env python3
"""Core falsifiable hypothesis test for Bollinger Bands on the committed
single-asset panel (AAPL).

Uses the bollinger_bands_hypothesis example (run_backtest.py CLI path): weak
two-criterion falsification (oos_sharpe > 0, oos_total_return > 0) net of 3bp
round-trip costs on the held-out test split. Pins observed metrics (regression
guard, relative tolerance, never exact equality).

Honest outcome on this committed window: Bollinger Bands mean-reversion does
NOT produce positive out-of-sample risk-adjusted returns (Sharpe -1.3014,
total return -42.55%) so the weak-criterion verdict is NOT SUPPORTED. The
stronger benchmark-aware guard (test_bollinger_bands_benchmark_aware_real_aapl.py)
records NOT SUPPORTED too. This test records the weak-criterion outcome
honestly and does not claim profitability.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from bollinger_bands_hypothesis import run_hypothesis_test  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

REL_TOL = 1e-3

# Pinned to the committed AAPL fixture via run_backtest.py (test split,
# 3bp round-trip). Regression guard only -- never exact equality.
EXPECTED = {
    "sharpe_ratio": -1.3013699003638697,
    "total_return": -0.42546223321687104,
}


def test_hypothesis_bollinger_runs_on_aapl_real_window():
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
    assert len(result["criteria"]) == 2
    assert {c["name"] for c in result["criteria"]} == {
        "oos_sharpe_gt_zero",
        "oos_total_return_positive",
    }
    out = buffer.getvalue()
    assert "VERDICT:" in out


def test_hypothesis_bollinger_metrics_pinned_on_aapl_real_window():
    """Regression guard: the weak-criterion run on committed AAPL must
    reproduce the pinned out-of-sample metrics (net of costs). Relative
    tolerance only, never exact equality.

    The verdict is pinned as NOT SUPPORTED to enforce "do not tune to force
    SUPPORT": any future change that silently flips this to SUPPORTED fails
    this test.
    """
    assert (SRC / "AAPL.csv").exists()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_hypothesis_test(
            data_path=SRC / "AAPL.csv",
            label="AAPL",
            benchmark_path=None,
        )
    # Enforce the no-tuning rule: weak-criterion verdict stays NOT SUPPORTED.
    assert result["verdict"] == "NOT SUPPORTED"
    assert result["all_pass"] is False
    obs = result["observed"]
    for k, expv in EXPECTED.items():
        gotv = obs[k]
        assert abs(gotv - expv) <= REL_TOL * max(abs(expv), 1e-9), (
            f"{k} regression: got {gotv}, expected {expv}"
        )


if __name__ == "__main__":
    test_hypothesis_bollinger_runs_on_aapl_real_window()
    test_hypothesis_bollinger_metrics_pinned_on_aapl_real_window()
    print("OK")
