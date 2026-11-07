#!/usr/bin/env python3
"""Parameter sensitivity sweep for volatility targeting (target_vol / lookback)
on the committed single-asset panel (AAPL).

Sweeps the pre-registered PARAM_SENSITIVITY_GRID (narrow grid around the
advertised target_vol=0.15 / lookback=63 setting) and pins the observed
out-of-sample metrics (net of costs) with relative tolerance so any silent
change to the backtest numbers is caught.

METHODOLOGICAL NOTE (committed fixtures only, not evidence about any market):
Under the weak two-criterion sweep (oos_sharpe > 0, oos_total_return > 0) the
volatility-targeting verdict is SUPPORTED across all six pre-registered
parameter settings on this window, because the strategy beats a zero baseline.
The stronger benchmark-aware guard
(test_volatility_targeting_benchmark_aware_real_aapl.py) records NOT SUPPORTED:
the strategy does not beat buy-and-hold AAPL (return 47.4% vs 77.4%), the
benchmark alpha is not significant (raw p = 0.22), and the Deflated Sharpe
p-value is not significant (p = 0.79 across 6 trials). This test records the
weak-criterion falsification outcome honestly and does not claim profitability.

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
    EXPECTED_METRICS = {
        (0.15, 63): {
            "sharpe_ratio": 0.7710596325955302,
            "total_return": 0.4736842323382433,
        },
        (0.10, 63): {
            "sharpe_ratio": 0.7710596325955302,
            "total_return": 0.4736842323382433,
        },
        (0.20, 63): {
            "sharpe_ratio": 0.7710596325955302,
            "total_return": 0.4736842323382433,
        },
        (0.15, 50): {
            "sharpe_ratio": 0.1720868275560054,
            "total_return": 0.06029405217210648,
        },
        (0.15, 100): {
            "sharpe_ratio": 0.8219319509661736,
            "total_return": 0.5151164660790588,
        },
        (0.10, 50): {
            "sharpe_ratio": 0.1720868275560054,
            "total_return": 0.06029405217210648,
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
