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
            "sharpe_ratio": -0.30135865959630453,
            "total_return": -0.06361793931133031,
            "benchmark_total_return": 0.9015402575236577,
            "benchmark_alpha": -0.07861132100133345,
            "benchmark_alpha_pvalue": 0.41999142422576474,
            "correlation_with_benchmark": 0.27173298962874365,
            "deflated_sharpe_pvalue": 0.9904800860018925,
        },
        (189, 0.5, 0.0): {
            "sharpe_ratio": 0.4919140847967558,
            "total_return": 0.21039617661627763,
            "benchmark_total_return": 0.9015402575236577,
            "benchmark_alpha": 0.00754644475515633,
            "benchmark_alpha_pvalue": 0.9521472874031677,
            "correlation_with_benchmark": 0.38560221686105167,
            "deflated_sharpe_pvalue": 0.8851996901574766,
        },
        (315, 0.5, 0.0): {
            "sharpe_ratio": 1.0667936764341146,
            "total_return": 0.40744569229057737,
            "benchmark_total_return": 0.9015402575236577,
            "benchmark_alpha": 0.12370670170801487,
            "benchmark_alpha_pvalue": 0.2394467186359821,
            "correlation_with_benchmark": 0.2697793231468673,
            "deflated_sharpe_pvalue": 0.6456778937626653,
        },
        (252, 0.4, 0.0): {
            "sharpe_ratio": -0.30135865959630453,
            "total_return": -0.06361793931133031,
            "benchmark_total_return": 0.9015402575236577,
            "benchmark_alpha": -0.07861132100133345,
            "benchmark_alpha_pvalue": 0.41999142422576474,
            "correlation_with_benchmark": 0.27173298962874365,
            "deflated_sharpe_pvalue": 0.9904800860018925,
        },
        (252, 0.6, 0.0): {
            "sharpe_ratio": -0.06565153757395178,
            "total_return": 0.004518953315828744,
            "benchmark_total_return": 0.9015402575236577,
            "benchmark_alpha": -0.04538734839147846,
            "benchmark_alpha_pvalue": 0.6173095365518957,
            "correlation_with_benchmark": 0.29396693836602955,
            "deflated_sharpe_pvalue": 0.9768180707048604,
        },
        (252, 0.5, 0.02): {
            "sharpe_ratio": -0.357447431705218,
            "total_return": -0.0665547502983087,
            "benchmark_total_return": 0.9015402575236577,
            "benchmark_alpha": -0.06724932566913482,
            "benchmark_alpha_pvalue": 0.45388025598062276,
            "correlation_with_benchmark": 0.22020775655338476,
            "deflated_sharpe_pvalue": 0.9926233826203716,
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
