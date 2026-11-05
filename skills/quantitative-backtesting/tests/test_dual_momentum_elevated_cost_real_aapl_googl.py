#!/usr/bin/env python3
"""Elevated-cost confirmation sweep for dual momentum (absolute + relative
momentum, long-only) on the committed AAPL/GOOGL pair.

Extended to run benchmark-aware (MSFT buy-and-hold) with the Deflated Sharpe
Ratio across the pre-registered parameter grid (N_TRIALS=6), pinning strategy +
benchmark metrics (net of costs) with relative tolerance and asserting the
four BENCHMARK_CRITERIA. The verdict remains NOT SUPPORTED on committed
fixtures; we do not tune to force SUPPORT.

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

from dual_momentum_hypothesis import (  # noqa: E402
    COMMISSION,
    SLIPPAGE,
    ELEVATED_COST_SWEEP_LEVELS,
    N_TRIALS,
    run_elevated_cost_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def _build_pair_csv(dest: Path) -> Path:
    frames = []
    for name in ("AAPL.csv", "GOOGL.csv"):
        frame = pd.read_csv(SRC / name)
        frame["symbol"] = Path(name).stem
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    out = dest / "aapl_googl_pair.csv"
    combined.to_csv(out, index=False)
    return out


def test_elevated_cost_sweep_runs_on_aapl_googl_real_window_dual_momentum():
    for name in ("AAPL.csv", "GOOGL.csv", "MSFT.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_pair_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = run_elevated_cost_sweep(
                data_path,
                benchmark_path="MSFT.csv",
                n_trials=N_TRIALS,
            )

    assert isinstance(rows, list) and len(rows) == len(ELEVATED_COST_SWEEP_LEVELS)
    assert rows[0]["commission_bps"] == COMMISSION * 10_000
    assert rows[0]["slippage_bps"] == SLIPPAGE * 10_000
    for prev, curr in zip(rows, rows[1:]):
        assert curr["commission_bps"] >= prev["commission_bps"]
        assert curr["slippage_bps"] >= prev["slippage_bps"]
    for r in rows:
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])
        assert r["verdict"] == ("SUPPORTED" if r["all_pass"] else "NOT SUPPORTED")
        assert len(r["criteria"]) == 4
        assert {c["name"] for c in r["criteria"]} == {
            "oos_sharpe_gt_zero",
            "oos_total_return_gt_benchmark",
            "deflated_sharpe_pvalue_lt_0.10",
            "benchmark_alpha_pvalue_lt_0.05",
        }
        assert r.get("benchmark_path") is not None
        assert str(r["benchmark_path"]).endswith("MSFT.csv")
        assert r.get("n_trials") == N_TRIALS

    EXPECTED_METRICS = {
        (2.0, 1.0): {
            "sharpe_ratio": -0.30135865959630453,
            "total_return": -0.06361793931133031,
            "benchmark_total_return": 0.9015402575236577,
            "benchmark_alpha": -0.07861132100133345,
            "benchmark_alpha_pvalue": 0.41999142422576474,
            "correlation_with_benchmark": 0.27173298962874365,
            "deflated_sharpe_pvalue": 0.9904800860018925,
        },
        (5.0, 2.5): {
            "sharpe_ratio": -0.40360675434020027,
            "total_return": -0.090716599219274,
            "benchmark_total_return": 0.9006843076228017,
            "benchmark_alpha": -0.0932830590976983,
            "benchmark_alpha_pvalue": 0.34004827354699696,
            "correlation_with_benchmark": 0.2709569796868625,
            "deflated_sharpe_pvalue": 0.993810027564056,
        },
        (10.0, 5.0): {
            "sharpe_ratio": -0.5721694199822972,
            "total_return": -0.13419398840864594,
            "benchmark_total_return": 0.8992577244547089,
            "benchmark_alpha": -0.11773595592497306,
            "benchmark_alpha_pvalue": 0.2314470137200192,
            "correlation_with_benchmark": 0.2693657707816513,
            "deflated_sharpe_pvalue": 0.9971236244852216,
        },
        (20.0, 10.0): {
            "sharpe_ratio": -0.9000445132774076,
            "total_return": -0.2151631735895001,
            "benchmark_total_return": 0.8964045581185223,
            "benchmark_alpha": -0.16664174957952255,
            "benchmark_alpha_pvalue": 0.09588474542808112,
            "correlation_with_benchmark": 0.26514013358106975,
            "deflated_sharpe_pvalue": 0.9994759629824468,
        },
    }
    REL_TOL = 1e-3
    for r in rows:
        key = (r["commission_bps"], r["slippage_bps"])
        assert key in EXPECTED_METRICS, f"unexpected cost level {key}"
        exp = EXPECTED_METRICS[key]
        for k, expv in exp.items():
            assert k in r, f"missing {k} at {key}"
            gotv = r[k]
            assert abs(gotv - expv) <= REL_TOL * max(abs(expv), 1e-9), (
                f"{k} regression at {key}: got {gotv}, expected {expv}"
            )
        if key == (2.0, 1.0):
            assert r["verdict"] == "NOT SUPPORTED"
            assert r["all_pass"] is False

    out = buffer.getvalue()
    assert "ELEVATED COST SENSITIVITY SWEEP" in out
    assert "VERDICT" in out


if __name__ == "__main__":
    test_elevated_cost_sweep_runs_on_aapl_googl_real_window_dual_momentum()
    print("OK")
