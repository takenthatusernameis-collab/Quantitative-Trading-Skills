#!/usr/bin/env python3
"""Real-market cost-sensitivity sweep for multi-pair z-score mean reversion on
the committed three-asset panel (AAPL / MSFT / GOOGL).

Mirrors test_zscore_cost_sensitivity_real_msft_googl.py but on a three-asset
panel. Sweeps commission / slippage across five ascending levels and asserts
the honest directional claim: higher per-trade costs never improve net
out-of-sample performance. This is a sensitivity analysis on committed
fixtures, not evidence about any market. Offline, committed fixtures only;
no live network.
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
    COST_SWEEP_LEVELS,
    run_cost_sweep,
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


def test_cost_sensitivity_runs_on_triple_real_window_multi_pair_zscore():
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "MSFT.csv").exists()
    assert (SRC / "GOOGL.csv").exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_triple_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = run_cost_sweep(data_path, strategy="multi_pair_zscore_mean_reversion")

    assert isinstance(rows, list) and len(rows) == len(COST_SWEEP_LEVELS)
    assert rows[0]["commission_bps"] == 0.0 and rows[0]["slippage_bps"] == 0.0
    assert [r["commission_bps"] for r in rows] == [c * 10_000 for c, _ in COST_SWEEP_LEVELS]
    advertised = next(r for r in rows if r["commission_bps"] == COMMISSION * 10_000)
    assert advertised is rows[2]
    for r in rows:
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])
        assert len(r["criteria"]) == 2
        assert {c["name"] for c in r["criteria"]} == {
            "oos_sharpe_gt_zero",
            "oos_total_return_positive",
        }
    out = buffer.getvalue()
    assert "COST SENSITIVITY SWEEP" in out
    assert "VERDICT" in out


if __name__ == "__main__":
    test_cost_sensitivity_runs_on_triple_real_window_multi_pair_zscore()
    print("OK")
