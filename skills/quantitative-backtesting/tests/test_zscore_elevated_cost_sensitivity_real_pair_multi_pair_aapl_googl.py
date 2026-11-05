#!/usr/bin/env python3
"""Elevated-cost confirmation sweep for multi-pair z-score mean reversion on
the committed two-asset pair (AAPL / GOOGL).

Mirrors test_zscore_elevated_cost_sensitivity_real_aapl_googl.py but runs the
panel ``multi_pair_zscore_mean_reversion`` strategy over the pair (which trades
the single AAPL/GOOGL pair and aggregates into a book). Re-runs the pre-
registered falsification criteria at ascending cost levels above the advertised
3bps round-trip, with the advertised level re-run first as the reference
baseline. Reports per-criterion pass/fail and the verdict at each level, and
flags whether the verdict flips as costs rise. Verdict flips are the signal
that the result is not robust to elevated costs -- this test never asserts
SUPPORTED as a profitability claim.

Offline, committed fixtures only; no live network.
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


def test_elevated_cost_sweep_runs_on_aapl_googl_real_window_multi_pair_zscore():
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "GOOGL.csv").exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_pair_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = run_elevated_cost_sweep(
                data_path, strategy="multi_pair_zscore_mean_reversion"
            )

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

    # Regression guard: pin the observed out-of-sample metrics per elevated cost
    # level so the sensitivity evidence is reproducible and any silent change to
    # the backtest numbers is caught. On a two-asset panel the multi-pair
    # strategy trades exactly the AAPL/GOOGL pair, so its metrics match the
    # single-pair guard in test_zscore_elevated_cost_sensitivity_real_aapl_googl.py.
    EXPECTED_METRICS = {
        (2.0, 1.0): {
            "sharpe_ratio": -0.4256114742108271,
            "total_return": -0.030959664968179257,
        },
        (5.0, 2.5): {
            "sharpe_ratio": -0.5336697318874039,
            "total_return": -0.046969474552062684,
        },
        (10.0, 5.0): {
            "sharpe_ratio": -0.7125384303768411,
            "total_return": -0.07308232848114982,
        },
        (20.0, 10.0): {
            "sharpe_ratio": -1.0626776169126118,
            "total_return": -0.12323612173328402,
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

    out = buffer.getvalue()
    assert "ELEVATED COST SENSITIVITY SWEEP" in out
    assert "VERDICT" in out


if __name__ == "__main__":
    test_elevated_cost_sweep_runs_on_aapl_googl_real_window_multi_pair_zscore()
    print("OK")