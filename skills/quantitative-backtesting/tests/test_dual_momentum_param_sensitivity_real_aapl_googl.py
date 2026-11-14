#!/usr/bin/env python3
"""Parameter sensitivity for dual momentum (absolute + relative momentum,
long-only) on the committed AAPL/GOOGL pair.

Sweeps a narrow pre-registered grid on the pair and reports an explicit
falsification verdict at each setting. Extended to run benchmark-aware (MSFT
buy-and-hold) with the Deflated Sharpe Ratio across the pre-registered
parameter grid (N_TRIALS=6), pinning strategy + benchmark metrics (net of
costs) with relative tolerance and asserting the four BENCHMARK_CRITERIA.
Verdicts are falsification outcomes, never profitability claims. Verdict
remains NOT SUPPORTED on committed fixtures; we do not tune to force SUPPORT.

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
    PARAM_SENSITIVITY_GRID,
    N_TRIALS,
    run_param_sensitivity_sweep,
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


def test_param_sensitivity_runs_on_aapl_googl_real_window_dual_momentum():
    for name in ("AAPL.csv", "GOOGL.csv", "MSFT.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_pair_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = run_param_sensitivity_sweep(
                data_path,
                benchmark_path="MSFT.csv",
                n_trials=N_TRIALS,
            )

    assert isinstance(rows, list) and len(rows) == len(PARAM_SENSITIVITY_GRID)
    for r, (lookback, top_q, risk_free_rate) in zip(rows, PARAM_SENSITIVITY_GRID):
        assert r["lookback"] == int(lookback)
        assert r["top_quantile"] == float(top_q)
        assert r["risk_free_rate"] == float(risk_free_rate)
        assert r["commission"] == COMMISSION
        assert r["slippage"] == SLIPPAGE
        assert r["commission_bps"] == COMMISSION * 10_000
        assert r["slippage_bps"] == SLIPPAGE * 10_000
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
        (252, 0.5, 0.0): {
            "sharpe_ratio": 1.213481728917752,
            "total_return": 0.22297242890032654,
            "benchmark_total_return": 0.1711375869976839,
            "benchmark_alpha": 0.17813258239401938,
            "benchmark_alpha_pvalue": 0.1338616416250097,
            "correlation_with_benchmark": -0.015544590903470388,
            "deflated_sharpe_pvalue": 0.730819050210997,
        },
        (189, 0.5, 0.0): {
            "sharpe_ratio": 2.257145286892217,
            "total_return": 0.6397789678480681,
            "benchmark_total_return": 0.1711375869976839,
            "benchmark_alpha": 0.4256778599125213,
            "benchmark_alpha_pvalue": 0.011166652095988492,
            "correlation_with_benchmark": 0.039755600674195715,
            "deflated_sharpe_pvalue": 0.24851367912549538,
        },
        (280, 0.5, 0.0): {
            "sharpe_ratio": -0.6047475327448264,
            "total_return": -0.020069096986148116,
            "benchmark_total_return": 0.1711375869976839,
            "benchmark_alpha": -0.014313219111306591,
            "benchmark_alpha_pvalue": 0.7891519092660466,
            "correlation_with_benchmark": -0.024295791789858835,
            "deflated_sharpe_pvalue": 0.9964626523585458,
        },
        (252, 0.4, 0.0): {
            "sharpe_ratio": 1.213481728917752,
            "total_return": 0.22297242890032654,
            "benchmark_total_return": 0.1711375869976839,
            "benchmark_alpha": 0.17813258239401938,
            "benchmark_alpha_pvalue": 0.1338616416250097,
            "correlation_with_benchmark": -0.015544590903470388,
            "deflated_sharpe_pvalue": 0.730819050210997,
        },
        (252, 0.6, 0.0): {
            "sharpe_ratio": 1.0742201012824766,
            "total_return": 0.13071624570235207,
            "benchmark_total_return": 0.1711375869976839,
            "benchmark_alpha": 0.10621602345551048,
            "benchmark_alpha_pvalue": 0.1493234056988707,
            "correlation_with_benchmark": -0.0033048190412337465,
            "deflated_sharpe_pvalue": 0.7848852706357607,
        },
        (252, 0.5, 0.02): {
            "sharpe_ratio": 1.213481728917752,
            "total_return": 0.22297242890032654,
            "benchmark_total_return": 0.1711375869976839,
            "benchmark_alpha": 0.17813258239401938,
            "benchmark_alpha_pvalue": 0.1338616416250097,
            "correlation_with_benchmark": -0.015544590903470388,
            "deflated_sharpe_pvalue": 0.730819050210997,
        },
    }
    REL_TOL = 1e-3
    for r in rows:
        key = (r["lookback"], r["top_quantile"], r["risk_free_rate"])
        assert key in EXPECTED_METRICS, f"unexpected parameter setting {key}"
        exp = EXPECTED_METRICS[key]
        for k, expv in exp.items():
            assert k in r, f"missing {k} at {key}"
            gotv = r[k]
            assert abs(gotv - expv) <= REL_TOL * max(abs(expv), 1e-9), (
                f"{k} regression at {key}: got {gotv}, expected {expv}"
            )
        if key == (252, 0.5, 0.0):
            assert r["verdict"] == "NOT SUPPORTED"
            assert r["all_pass"] is False

    out = buffer.getvalue()
    assert "PARAMETER SENSITIVITY SWEEP" in out
    assert "VERDICT" in out


if __name__ == "__main__":
    test_param_sensitivity_runs_on_aapl_googl_real_window_dual_momentum()
    print("OK")
