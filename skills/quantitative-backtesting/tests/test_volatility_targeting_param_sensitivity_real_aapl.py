#!/usr/bin/env python3
"""Parameter sensitivity sweep for volatility targeting (target_vol / lookback)
on the committed single-asset panel (AAPL).

Sweeps the pre-registered PARAM_SENSITIVITY_GRID (narrow grid around the
advertised target_vol=0.15 / lookback=63 setting) and pins the observed
out-of-sample metrics (net of costs) with relative tolerance so any silent
change to the backtest numbers is caught.

METHODOLOGICAL NOTE (committed fixtures only, not evidence about any market):
Under the weak two-criterion sweep (oos_sharpe > 0, oos_total_return > 0) the
volatility-targeting verdict is SUPPORTED at four of the six pre-registered
parameter settings on this window (target_vol 0.10/0.15/0.20 at lookback 63,
and lookback 100) but NOT SUPPORTED at the lookback=50 rung (both criteria
fail), so the verdict flips across the grid. The stronger benchmark-aware
guard (test_volatility_targeting_benchmark_aware_real_aapl.py) records NOT
SUPPORTED: the strategy does not beat buy-and-hold AAPL (return 16.10% vs
17.78%), the benchmark alpha is not significant, and the Deflated Sharpe
p-value is not significant across 6 trials. This test records the
weak-criterion falsification outcome honestly and does not claim
profitability; a verdict that flips across the grid is a sensitivity finding.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from volatility_targeting_hypothesis import (  # noqa: E402
    COMMISSION,
    PARAM_SENSITIVITY_GRID,
    SLIPPAGE,
    run_param_sensitivity_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_param_sensitivity_runs_on_aapl_real_window_volatility_targeting():
    assert (SRC / "AAPL.csv").exists()

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_param_sensitivity_sweep(SRC / "AAPL.csv")

    assert isinstance(rows, list) and len(rows) == len(PARAM_SENSITIVITY_GRID)
    for r, (target_vol, lookback) in zip(rows, PARAM_SENSITIVITY_GRID):
        assert r["target_vol"] == float(target_vol)
        assert r["lookback"] == int(lookback)
        assert r["commission"] == COMMISSION
        assert r["slippage"] == SLIPPAGE
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])
        assert r["verdict"] == ("SUPPORTED" if r["all_pass"] else "NOT SUPPORTED")
        assert len(r["criteria"]) == 2
        assert {c["name"] for c in r["criteria"]} == {
            "oos_sharpe_gt_zero",
            "oos_total_return_positive",
        }

    # Regression guard: pin the observed out-of-sample metrics per parameter
    # setting so the robustness evidence is reproducible and any silent change
    # to the backtest numbers is caught. Compared with a relative tolerance.
    #
    # These numbers are NOT identical across target_vol at a fixed lookback:
    # the VolatilityTargeting overlay was previously broken in standalone
    # mode (the target_vol multiplier was computed and then discarded, so
    # every target_vol produced the same unsized signal). The fix makes the
    # sizing math actually apply, so the pinned metrics now differ by
    # target_vol and lookback as the documented formula predicts.
    EXPECTED_METRICS = {
        (0.15, 63): {
            "sharpe_ratio": 0.5154860951632668,
            "total_return": 0.10666302954386775,
        },
        (0.10, 63): {
            "sharpe_ratio": 0.44729933506308894,
            "total_return": 0.07296094653230978,
        },
        (0.20, 63): {
            "sharpe_ratio": 0.5495794752133558,
            "total_return": 0.13815856732330256,
        },
        (0.15, 50): {
            "sharpe_ratio": -0.10398593989275874,
            "total_return": -0.009743911765914715,
        },
        (0.15, 100): {
            "sharpe_ratio": 0.3290414214742712,
            "total_return": 0.06747912716144122,
        },
        (0.10, 50): {
            "sharpe_ratio": -0.1683619399500347,
            "total_return": -0.0033209027944205406,
        },
    }
    REL_TOL = 1e-3
    for r in rows:
        key = (r["target_vol"], r["lookback"])
        assert key in EXPECTED_METRICS, f"unexpected parameter setting {key}"
        exp = EXPECTED_METRICS[key]
        for k, expv in exp.items():
            assert k in r, f"missing {k} at {key}"
            gotv = r[k]
            assert abs(gotv - expv) <= REL_TOL * max(abs(expv), 1e-9), (
                f"{k} regression at {key}: got {gotv}, expected {expv}"
            )

    out = buffer.getvalue()
    assert "PARAMETER SENSITIVITY SWEEP" in out
    assert "VERDICT" in out


if __name__ == "__main__":
    test_param_sensitivity_runs_on_aapl_real_window_volatility_targeting()
    print("OK")
