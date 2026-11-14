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
            "sharpe_ratio": 1.213481728917752,
            "total_return": 0.22297242890032654,
            "benchmark_total_return": 0.1711375869976839,
            "benchmark_alpha": 0.17813258239401938,
            "benchmark_alpha_pvalue": 0.1338616416250097,
            "correlation_with_benchmark": -0.015544590903470388,
            "deflated_sharpe_pvalue": 0.730819050210997,
        },
        (5.0, 2.5): {
            "sharpe_ratio": 1.2098820619383024,
            "total_return": 0.22240853646656245,
            "benchmark_total_return": 0.17061041693251533,
            "benchmark_alpha": 0.1777569445335177,
            "benchmark_alpha_pvalue": 0.13490001314247602,
            "correlation_with_benchmark": -0.015548556430388522,
            "deflated_sharpe_pvalue": 0.7321067041091627,
        },
        (10.0, 5.0): {
            "sharpe_ratio": 1.2038654084204221,
            "total_return": 0.22146871574362126,
            "benchmark_total_return": 0.16973180015723455,
            "benchmark_alpha": 0.17713088143268158,
            "benchmark_alpha_pvalue": 0.13665040336723489,
            "correlation_with_benchmark": -0.015554816707883959,
            "deflated_sharpe_pvalue": 0.7342450406486899,
        },
        (20.0, 10.0): {
            "sharpe_ratio": 1.1917699027481223,
            "total_return": 0.21958907429773888,
            "benchmark_total_return": 0.16797456660667276,
            "benchmark_alpha": 0.17587875523100932,
            "benchmark_alpha_pvalue": 0.14022575223519795,
            "correlation_with_benchmark": -0.015566035967803132,
            "deflated_sharpe_pvalue": 0.7384911493490879,
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
