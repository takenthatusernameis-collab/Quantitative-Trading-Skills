#!/usr/bin/env python3
"""Elevated-cost confirmation on the committed real-market AAPL/GOOGL pair.

Extends the cost-sensitivity evidence with a sweep at cost levels higher than
the advertised 3bps (2bp comm + 1bp slip) round-trip, re-running the
advertised level first as the reference baseline. Reports per-criterion
pass/fail and the verdict at each level, and flags whether the verdict flips
as costs rise. Verdict flips are the signal that the result is not robust to
elevated costs -- this test never asserts SUPPORTED as a profitability claim.

METHODOLOGICAL NOTE (committed fixtures only, not evidence about any market):
Under the weak two-criterion sweep (oos_sharpe > 0, oos_total_return > 0) the
z-score mean-reversion verdict is NOT SUPPORTED at every tested elevated cost
level on this AAPL/GOOGL window: Sharpe degrades from -0.426 to -1.063 and
total return from -3.1% to -12.3% as costs rise to 20bp/10bp. The stronger
benchmark-aware guard (buy-and-hold MSFT + Deflated Sharpe) is recorded in
test_zscore_mean_reversion_benchmark_aware_real_triple_aapl_msft_googl.py;
this test records the weak-criterion falsification outcome honestly and does
not claim profitability.

Offline, committed fixtures only (assets/example_data/real_market_data/
{AAPL,GOOGL}.csv). No live network.
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from zscore_mean_reversion_hypothesis import (  # noqa: E402
    COMMISSION,
    SLIPPAGE,
    ELEVATED_COST_SWEEP_LEVELS,
    run_elevated_cost_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def _build_pair_csv(dest: Path) -> Path:
    aapl = pd.read_csv(SRC / "AAPL.csv")
    googl = pd.read_csv(SRC / "GOOGL.csv")
    aapl["symbol"] = "AAPL"
    googl["symbol"] = "GOOGL"
    combined = pd.concat([aapl, googl], ignore_index=True)
    out = dest / "aapl_googl_pair.csv"
    combined.to_csv(out, index=False)
    return out


def test_elevated_cost_sweep_runs_on_aapl_googl_real_window():
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "GOOGL.csv").exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_pair_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = run_elevated_cost_sweep(data_path)

    assert isinstance(rows, list) and len(rows) == len(ELEVATED_COST_SWEEP_LEVELS)
    # First level is the advertised reference, re-run for baseline comparison.
    assert rows[0]["commission_bps"] == COMMISSION * 10_000
    assert rows[0]["slippage_bps"] == SLIPPAGE * 10_000
    # Ascending costs above the advertised reference.
    for prev, curr in zip(rows, rows[1:]):
        assert curr["commission_bps"] >= prev["commission_bps"]
        assert curr["slippage_bps"] >= prev["slippage_bps"]
    # Determinate verdicts; never a profitability claim.
    for r in rows:
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])
        assert r["verdict"] == ("SUPPORTED" if r["all_pass"] else "NOT SUPPORTED")
        assert len(r["criteria"]) == 2
        assert {c["name"] for c in r["criteria"]} == {
            "oos_sharpe_gt_zero",
            "oos_total_return_positive",
        }
    out = buffer.getvalue()
    assert "ELEVATED COST SENSITIVITY SWEEP" in out
    assert "VERDICT" in out

    # Regression guard: pin strategy metrics (net of costs) per elevated cost
    # level so the sensitivity evidence is reproducible and any silent change
    # to the backtest numbers is caught. Compared with a relative tolerance.
    EXPECTED_METRICS = {
        (2.0, 1.0): {
            "sharpe_ratio": 0.7110990902058707,
            "total_return": 0.09772954160702252,
        },
        (5.0, 2.5): {
            "sharpe_ratio": 0.6327005515617641,
            "total_return": 0.08887004708265778,
        },
        (10.0, 5.0): {
            "sharpe_ratio": 0.5018284455022648,
            "total_return": 0.07425411749643795,
        },
        (20.0, 10.0): {
            "sharpe_ratio": 0.24079508041722858,
            "total_return": 0.04557632776886966,
        },
    }
    REL_TOL = 1e-3
    for r in rows:
        key = (r["commission_bps"], r["slippage_bps"])
        assert key in EXPECTED_METRICS, f"unexpected elevated cost level {key}"
        exp = EXPECTED_METRICS[key]
        for k, expv in exp.items():
            assert k in r, f"missing {k} at {key}"
            gotv = r[k]
            assert abs(gotv - expv) <= REL_TOL * max(abs(expv), 1e-9), (
                f"{k} regression at {key}: got {gotv}, expected {expv}"
            )


if __name__ == "__main__":
    test_elevated_cost_sweep_runs_on_aapl_googl_real_window()
    print("OK")
