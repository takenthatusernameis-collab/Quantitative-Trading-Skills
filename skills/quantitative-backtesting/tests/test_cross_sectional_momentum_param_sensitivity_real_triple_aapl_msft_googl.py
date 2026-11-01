#!/usr/bin/env python3
"""Parameter sensitivity on the committed real-market three-asset panel
(AAPL / MSFT / GOOGL).

Sweeps cross-sectional momentum parameters across a narrow pre-registered
grid on the three-asset panel and reports an explicit falsification verdict
at each setting. Reports how the per-criterion pass/fail and overall verdict
change as parameters are perturbed around the advertised setting
(lookback=20, top_quantile=0.5, bottom_quantile=0.5), holding
commission/slippage fixed at the advertised level. This is a
robustness/sensitivity analysis on committed fixtures, not evidence about
any market. No claim is made about which setting is "best"; verdict flips
across the grid are the signal that the result is not robust to small
parameter changes.

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

from cross_sectional_momentum_hypothesis import (  # noqa: E402
    COMMISSION,
    SLIPPAGE,
    PARAM_SENSITIVITY_GRID,
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


def test_param_sensitivity_runs_on_triple_real_window_cross_sectional_momentum():
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_triple_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = run_param_sensitivity_sweep(data_path)

    assert isinstance(rows, list) and len(rows) == len(PARAM_SENSITIVITY_GRID)
    for r, (lookback, top_q, bottom_q) in zip(rows, PARAM_SENSITIVITY_GRID):
        assert r["lookback"] == int(lookback)
        assert r["top_quantile"] == float(top_q)
        assert r["bottom_quantile"] == float(bottom_q)
        assert r["commission"] == COMMISSION
        assert r["slippage"] == SLIPPAGE
        assert r["commission_bps"] == COMMISSION * 10_000
        assert r["slippage_bps"] == SLIPPAGE * 10_000
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])
        assert r["verdict"] == ("SUPPORTED" if r["all_pass"] else "NOT SUPPORTED")
        assert len(r["criteria"]) == 2
        assert {c["name"] for c in r["criteria"]} == {
            "oos_sharpe_gt_zero",
            "oos_total_return_positive",
        }
    out = buffer.getvalue()
    assert "PARAMETER SENSITIVITY SWEEP" in out
    assert "VERDICT" in out


if __name__ == "__main__":
    test_param_sensitivity_runs_on_triple_real_window_cross_sectional_momentum()
    print("OK")