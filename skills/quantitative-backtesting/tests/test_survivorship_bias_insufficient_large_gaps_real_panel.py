#!/usr/bin/env python3
"""End-to-end survivorship-bias POSITIVE control for the insufficient-data and
large-gaps branches on a real-data-derived panel.

Complements test_survivorship_bias_positive_control_real_panel.py (late-entry /
delisting). Here the panel is deterministically corrupted to exercise the
remaining detector branches:

  - GOOGL is truncated to fewer than min_observations (insufficient data).
  - MSFT has a synthetic 60-trading-day gap spliced into its history
    (large gap / delisting-relisting artifact).

The detector must report GOOGL in insufficient_data and MSFT in large_gaps,
with bias_score > 0, and the artifacts must still be persisted with
bias_controls_engaged == True.

This is an audit of the survivorship control, not a profitability claim.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILLS_DIR / "scripts"
REAL_DATA = SKILLS_DIR / "assets" / "example_data" / "real_market_data"
SYMBOLS = ["AAPL", "MSFT", "GOOGL"]

MIN_OBSERVATIONS = 252
INSUFFICIENT_TARGET = 100  # below min_observations
GAP_DAYS = 60


def _build_panel_csv(path: Path) -> Path:
    frames = []
    for sym in SYMBOLS:
        df = pd.read_csv(REAL_DATA / f"{sym}.csv")
        df["symbol"] = sym
        if sym == "GOOGL":
            df = df.iloc[:INSUFFICIENT_TARGET]  # insufficient observations
        elif sym == "MSFT":
            # Splice a 60-trading-day gap by dropping the middle block.
            mid = len(df) // 2
            df = pd.concat([df.iloc[:mid], df.iloc[mid + GAP_DAYS:]], ignore_index=True)
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    out = path / "gaps_insufficient_panel.csv"
    panel.to_csv(out, index=False)
    return out


def _run_panel_backtest(panel_csv: Path, out_dir: Path):
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "run_backtest.py"),
        "--data", str(panel_csv),
        "--multi-symbol",
        "--strategy", "cross_sectional_momentum",
        "--params", '{"lookback": 60, "top_quantile": 0.67, "bottom_quantile": 0.34}',
        "--commission", "0.0002",
        "--slippage", "0.0001",
        "--validate-point-in-time",
        "--output", str(out_dir),
    ]
    return subprocess.run(cmd, cwd=str(SCRIPTS_DIR), capture_output=True, text=True)


def test_survivorship_bias_insufficient_and_large_gaps_positive_control():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        panel = _build_panel_csv(tmp)
        out_dir = tmp / "out"
        result = _run_panel_backtest(panel, out_dir)
        assert result.returncode == 0, (
            f"multi-symbol run aborted (exit {result.returncode})\n"
            f"stdout:\n{result.stdout[-2500:]}\nstderr:\n{result.stderr[-2500:]}"
        )

        surv = json.loads((out_dir / "survivorship_bias.json").read_text())
        assert "GOOGL" in surv["insufficient_data"], (
            f"GOOGL not flagged insufficient: {surv['insufficient_data']}"
        )
        gap_syms = {g["symbol"] for g in surv["large_gaps"]}
        assert "MSFT" in gap_syms, f"MSFT not flagged as large gap: {gap_syms}"
        assert surv["bias_score"] > 0.0

        prov = json.loads((out_dir / "data_provenance.json").read_text())
        assert sorted(prov.keys()) == sorted(SYMBOLS)
        for sym in SYMBOLS:
            assert prov[sym].get("checksum"), f"missing checksum for {sym}"

        summary = json.loads((out_dir / "tear_sheet_summary.json").read_text())
        assert summary.get("bias_controls_engaged") is True
        assert summary["survivorship_bias"]["bias_score"] == surv["bias_score"]


if __name__ == "__main__":
    test_survivorship_bias_insufficient_and_large_gaps_positive_control()
    print("PASS  test_survivorship_bias_insufficient_and_large_gaps_positive_control")
    print("OK")
