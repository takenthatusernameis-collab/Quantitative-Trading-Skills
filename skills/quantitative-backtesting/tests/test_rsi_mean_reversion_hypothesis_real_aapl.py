#!/usr/bin/env python3
"""Core falsifiable hypothesis test for RSI mean reversion on the committed
single-asset panel (AAPL).

Uses the rsi_mean_reversion_hypothesis example (run_backtest.py CLI path):
weak two-criterion falsification (oos_sharpe > 0, oos_total_return > 0) net of
3bp round-trip costs on the held-out test split. Pins observed metrics
(regression guard, relative tolerance, never exact equality).

Honest outcome on this committed window: RSI mean reversion beats a zero
baseline (Sharpe 0.9264, total return 30.11% net of 3bp costs, vs buy-and-hold
AAPL self-benchmark +17.78%) so the weak-criterion verdict is SUPPORTED. The
stronger benchmark-aware guard
(test_rsi_mean_reversion_benchmark_aware_real_aapl.py) also records
SUPPORTED on this window. This test records the weak-criterion outcome
honestly and does not claim profitability.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import shutil
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from rsi_mean_reversion_hypothesis import run_hypothesis_test  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

REL_TOL = 1e-3

# Pinned to the committed AAPL fixture via run_backtest.py (test split,
# 3bp round-trip, AAPL self-benchmark in the example's temp layout).
# Regression guard only -- never exact equality.
EXPECTED = {
    "sharpe_ratio": 0.9264422710590631,
    "total_return": 0.3010781700588485,
}


def _run():
    assert (SRC / "AAPL.csv").exists()
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        shutil.copyfile(SRC / "AAPL.csv", d / "sample_ohlcv.csv")
        shutil.copyfile(SRC / "AAPL.csv", d / "sample_benchmark.csv")
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_hypothesis_test(
                data_path=d / "sample_ohlcv.csv",
                benchmark_path=d / "sample_benchmark.csv",
            )
    return result, buffer.getvalue()


def test_hypothesis_rsi_mean_reversion_runs_on_aapl_real_window():
    result, out = _run()
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
    assert "VERDICT:" in out


def test_hypothesis_rsi_mean_reversion_metrics_pinned_on_aapl_real_window():
    """Regression guard: the weak-criterion run on committed AAPL must
    reproduce the pinned out-of-sample metrics (net of costs). Relative
    tolerance only, never exact equality.

    The verdict is pinned as SUPPORTED to enforce "do not tune to force NOT
    SUPPORTED": any future change that silently flips this verdict fails this
    test.
    """
    result, _ = _run()
    # Enforce the no-tuning rule: weak-criterion verdict stays SUPPORTED.
    assert result["verdict"] == "SUPPORTED"
    assert result["all_pass"] is True
    obs = result.get("metrics") or {}
    for k, expv in EXPECTED.items():
        assert k in obs, f"missing metric {k}"
        gotv = obs[k]
        assert abs(gotv - expv) <= REL_TOL * max(abs(expv), 1e-9), (
            f"{k} regression: got {gotv}, expected {expv}"
        )


if __name__ == "__main__":
    test_hypothesis_rsi_mean_reversion_runs_on_aapl_real_window()
    test_hypothesis_rsi_mean_reversion_metrics_pinned_on_aapl_real_window()
    print("OK")
