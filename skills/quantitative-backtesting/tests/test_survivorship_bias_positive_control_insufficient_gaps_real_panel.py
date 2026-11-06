#!/usr/bin/env python3
"""End-to-end survivorship-bias POSITIVE control for insufficient_data and large_gaps.

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

INSUFFICIENT_SYMBOL = "AAPL"
GAP_SYMBOL = "MSFT"
OK_SYMBOL = "GOOGL"


def _build_panel_csv(path: Path) -> Path:
    frames = []
    for sym in SYMBOLS:
        df = pd.read_csv(REAL_DATA / f"{sym}.csv")
        df["symbol"] = sym
        if sym == INSUFFICIENT_SYMBOL:
            df = df.iloc[:100].copy()
        elif sym == GAP_SYMBOL:
            df = df.copy().reset_index(drop=True)
            if len(df) > 150:
                mid_idx = len(df) // 2
                dates = pd.to_datetime(df["date"])
                gap_shift = pd.Timedelta(days=65)
                dates[mid_idx:] = dates[mid_idx:] + gap_shift
                df["date"] = dates.dt.strftime("%Y-%m-%d")
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    out = path / "corrupted_panel_insufficient_gaps.csv"
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


def test_survivorship_bias_positive_control_insufficient_and_gaps():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        panel = _build_panel_csv(tmp)
        out_dir = tmp / "out"
        result = _run_panel_backtest(panel, out_dir)
        assert result.returncode == 0, (
            f"multi-symbol run aborted (exit {result.returncode})\n"
            f"stdout:\n{result.stdout[-2500:]}\nstderr:\n{result.stderr[-2500:]}"
        )

        surv_path = out_dir / "survivorship_bias.json"
        assert surv_path.is_file(), "survivorship_bias.json not written"
        surv = json.loads(surv_path.read_text())

        assert INSUFFICIENT_SYMBOL in surv["insufficient_data"], (
            f"{INSUFFICIENT_SYMBOL} not in insufficient_data: {surv['insufficient_data']}"
        )
        gap_symbols = {e["symbol"] for e in surv["large_gaps"]}
        assert GAP_SYMBOL in gap_symbols, (
            f"{GAP_SYMBOL} not in large_gaps: {surv['large_gaps']}"
        )
        assert surv["bias_score"] > 0.0

        prov = json.loads((out_dir / "data_provenance.json").read_text())
        assert sorted(prov.keys()) == sorted(SYMBOLS)
        summary = json.loads((out_dir / "tear_sheet_summary.json").read_text())
        assert summary.get("bias_controls_engaged") is True
        assert "survivorship_bias" in summary


if __name__ == "__main__":
    test_survivorship_bias_positive_control_insufficient_and_gaps()
    print("PASS")
    print("OK")
