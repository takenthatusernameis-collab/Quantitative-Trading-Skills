#!/usr/bin/env python3
"""Elevated-cost confirmation sweep for dual momentum (absolute + relative
momentum, long-only) on the committed three-asset panel (AAPL / MSFT / GOOGL).

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


def _build_triple_csv(dest: Path) -> Path:
    frames = []
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        frame = pd.read_csv(SRC / name)
        frame["symbol"] = Path(name).stem
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    out = dest / "aapl_msft_googl_triple.csv"
    combined.to_csv(out, index=False)
    return out


def test_elevated_cost_sweep_runs_on_triple_real_window_dual_momentum():
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_triple_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = run_elevated_cost_sweep(
                data_path,
                benchmark_path="MSFT.csv",
                n_trials=N_TRIALS,
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

    # Regression guard: pin strategy + benchmark metrics (net of costs)
    EXPECTED_METRICS = {
        (2, 1.0): {
            "sharpe_ratio": 0.5714563609925428,
            "total_return": 0.07873174188606424,
            "benchmark_total_return": 0.1711375869976839,
            "benchmark_alpha": 0.06289473591490319,
            "benchmark_alpha_pvalue": 0.401656514907732,
            "correlation_with_benchmark": 0.07046507740107277,
            "deflated_sharpe_pvalue": 0.9065939349881487,
        },
        (5, 2.5): {
            "sharpe_ratio": 0.5386631955963834,
            "total_return": 0.07533022569452408,
            "benchmark_total_return": 0.17061041693251533,
            "benchmark_alpha": 0.06021974258001611,
            "benchmark_alpha_pvalue": 0.4224225202347348,
            "correlation_with_benchmark": 0.0710776585196312,
            "deflated_sharpe_pvalue": 0.9119894145092636,
        },
        (10, 5.0): {
            "sharpe_ratio": 0.48397680735404736,
            "total_return": 0.06968146053303137,
            "benchmark_total_return": 0.16973180015723455,
            "benchmark_alpha": 0.05576142035520433,
            "benchmark_alpha_pvalue": 0.4584757189245652,
            "correlation_with_benchmark": 0.07206829025272145,
            "deflated_sharpe_pvalue": 0.9204275108430078,
        },
        (20, 10.0): {
            "sharpe_ratio": 0.37477249421102654,
            "total_return": 0.05846019207384345,
            "benchmark_total_return": 0.16797456660667276,
            "benchmark_alpha": 0.04684477590558077,
            "benchmark_alpha_pvalue": 0.5356131756404983,
            "correlation_with_benchmark": 0.07393259380039821,
            "deflated_sharpe_pvalue": 0.9353354675715837,
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
        # Enforce no-tuning rule at advertised level
        if key == (2, 1.0):
            assert r["verdict"] == "NOT SUPPORTED"
            assert r["all_pass"] is False

    out = buffer.getvalue()
    assert "ELEVATED COST SENSITIVITY SWEEP" in out
    assert "VERDICT" in out


if __name__ == "__main__":
    test_elevated_cost_sweep_runs_on_triple_real_window_dual_momentum()
    print("OK")
