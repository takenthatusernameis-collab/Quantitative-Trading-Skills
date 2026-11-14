#!/usr/bin/env python3
"""Parameter sensitivity on the committed real-market three-asset panel
(AAPL / MSFT / GOOGL).

Sweeps dual momentum (absolute + relative momentum, long-only) parameters
across a narrow pre-registered grid on the three-asset panel and reports an
explicit falsification verdict at each setting. Extended to run benchmark-aware
(MSFT buy-and-hold) with the Deflated Sharpe Ratio across the pre-registered
parameter grid (N_TRIALS=6), pinning strategy + benchmark metrics (net of
costs) with relative tolerance and asserting the four BENCHMARK_CRITERIA.
Verdict remains NOT SUPPORTED on committed fixtures; we do not tune to force
SUPPORT.

Offline, committed fixtures only (assets/example_data/real_market_data/
{AAPL,MSFT,GOOGL}.csv). No live network.
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


def test_param_sensitivity_runs_on_triple_real_window_dual_momentum():
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_triple_csv(d)
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

    # Regression guard: pin the observed out-of-sample metrics per parameter
    # setting so the robustness evidence is reproducible and any silent change
    # to the backtest numbers is caught. Compared with a relative tolerance.
    EXPECTED_METRICS = {
        (252, 0.5, 0.0): {
            "sharpe_ratio": 0.5714563609925428,
            "total_return": 0.07873174188606424,
            "benchmark_total_return": 0.1711375869976839,
            "benchmark_alpha": 0.06289473591490319,
            "benchmark_alpha_pvalue": 0.401656514907732,
            "correlation_with_benchmark": 0.07046507740107277,
            "deflated_sharpe_pvalue": 0.9065939349881487,
        },
        (189, 0.5, 0.0): {
            "sharpe_ratio": 1.3184117994454974,
            "total_return": 0.2657185552290937,
            "benchmark_total_return": 0.1711375869976839,
            "benchmark_alpha": 0.185213195942318,
            "benchmark_alpha_pvalue": 0.14489992241130978,
            "correlation_with_benchmark": 0.2300798625293813,
            "deflated_sharpe_pvalue": 0.7048711813028067,
        },
        (280, 0.5, 0.0): {
            "sharpe_ratio": -1.0350336734494465,
            "total_return": -0.01995957485010047,
            "benchmark_total_return": 0.1711375869976839,
            "benchmark_alpha": -0.015744218934175564,
            "benchmark_alpha_pvalue": 0.6245082403966703,
            "correlation_with_benchmark": -0.022083712089721083,
            "deflated_sharpe_pvalue": 0.999592902706947,
        },
        (252, 0.4, 0.0): {
            "sharpe_ratio": 0.5714563609925428,
            "total_return": 0.07873174188606424,
            "benchmark_total_return": 0.1711375869976839,
            "benchmark_alpha": 0.06289473591490319,
            "benchmark_alpha_pvalue": 0.401656514907732,
            "correlation_with_benchmark": 0.07046507740107277,
            "deflated_sharpe_pvalue": 0.9065939349881487,
        },
        (252, 0.6, 0.0): {
            "sharpe_ratio": 0.5714563609925428,
            "total_return": 0.07873174188606424,
            "benchmark_total_return": 0.1711375869976839,
            "benchmark_alpha": 0.06289473591490319,
            "benchmark_alpha_pvalue": 0.401656514907732,
            "correlation_with_benchmark": 0.07046507740107277,
            "deflated_sharpe_pvalue": 0.9065939349881487,
        },
        (252, 0.5, 0.02): {
            "sharpe_ratio": 0.5714563609925428,
            "total_return": 0.07873174188606424,
            "benchmark_total_return": 0.1711375869976839,
            "benchmark_alpha": 0.06289473591490319,
            "benchmark_alpha_pvalue": 0.401656514907732,
            "correlation_with_benchmark": 0.07046507740107277,
            "deflated_sharpe_pvalue": 0.9065939349881487,
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
    test_param_sensitivity_runs_on_triple_real_window_dual_momentum()
    print("OK")
