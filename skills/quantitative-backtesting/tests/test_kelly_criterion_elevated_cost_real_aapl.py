#!/usr/bin/env python3
"""Elevated-cost confirmation sweep for Kelly criterion (lookback=63, half-Kelly)
on the committed single-asset panel (AAPL).

Runs pre-registered ELEVATED_COST_SWEEP_LEVELS and pins observed out-of-sample
metrics (net of costs) with relative tolerance.

METHODOLOGICAL NOTE (committed fixtures only): under the weak two-criterion
sweep (oos_sharpe > 0, oos_total_return > 0) the verdict is SUPPORTED across
all tested cost levels (beats a zero baseline). The stronger benchmark-aware
guard (test_kelly_criterion_benchmark_aware_real_aapl.py) records NOT
SUPPORTED: it does not beat buy-and-hold AAPL (77.43%), alpha not significant
(p 0.2175), Deflated Sharpe not significant (p 0.7884, N=6). Consistent;
records the weak-criterion outcome honestly, no profitability claim.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from kelly_criterion_hypothesis import (  # noqa: E402
    COMMISSION,
    ELEVATED_COST_SWEEP_LEVELS,
    SLIPPAGE,
    run_elevated_cost_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"
REL_TOL = 1e-3


def test_elevated_cost_sweep_runs_on_aapl_real_window_kelly_criterion():
    assert (SRC / "AAPL.csv").exists()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_elevated_cost_sweep(SRC / "AAPL.csv")

    assert isinstance(rows, list) and len(rows) == len(ELEVATED_COST_SWEEP_LEVELS)
    assert rows[0]["commission_bps"] == COMMISSION * 10_000
    assert rows[0]["slippage_bps"] == SLIPPAGE * 10_000
    for prev, curr in zip(rows, rows[1:]):
        assert curr["commission_bps"] >= prev["commission_bps"]
        assert curr["slippage_bps"] >= prev["slippage_bps"]
    for r in rows:
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])
        assert len(r["criteria"]) == 2
        assert {c["name"] for c in r["criteria"]} == {
            "oos_sharpe_gt_zero",
            "oos_total_return_positive",
        }

    EXPECTED_METRICS = {
        (2.0, 1.0):   {"sharpe_ratio": 0.7710596325955302, "total_return": 0.4736842323382433},
        (5.0, 2.5):   {"sharpe_ratio": 0.7387352117865373, "total_return": 0.4479381654731962},
        (10.0, 5.0):  {"sharpe_ratio": 0.6847886991308316, "total_return": 0.4059745119564797},
        (20.0, 10.0): {"sharpe_ratio": 0.5767858761387973, "total_return": 0.3254858903148774},
    }
    for r in rows:
        key = (r["commission_bps"], r["slippage_bps"])
        assert key in EXPECTED_METRICS, f"unexpected cost level {key}"
        exp = EXPECTED_METRICS[key]
        for k, expv in exp.items():
            gotv = r[k]
            assert abs(gotv - expv) <= REL_TOL * max(abs(expv), 1e-9), (
                f"{k} regression at {key}: got {gotv}, expected {expv}"
            )
        # weak-criterion: SUPPORTED across all tested levels on this window
        assert r["verdict"] == "SUPPORTED"

    out = buffer.getvalue()
    assert "ELEVATED COST SENSITIVITY SWEEP" in out


if __name__ == "__main__":
    test_elevated_cost_sweep_runs_on_aapl_real_window_kelly_criterion()
    print("OK")
