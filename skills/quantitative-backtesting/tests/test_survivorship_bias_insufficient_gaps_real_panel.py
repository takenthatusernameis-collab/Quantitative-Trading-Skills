#!/usr/bin/env python3
"""Positive control: insufficient-data and large-gap branches of
detect_survivorship_bias on a real-data-derived panel.
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
GAP_SYMBOL = "GOOGL"
SURVIVOR_SYMBOL = "MSFT"


def _build_panel_csv(path: Path) -> Path:
    frames = []
    for sym in SYMBOLS:
        df = pd.read_csv(REAL_DATA / f"{sym}.csv")
        df["symbol"] = sym
        if sym == INSUFFICIENT_SYMBOL:
            df = df.iloc[:100]  # too few obs (< 252)
        elif sym == GAP_SYMBOL:
            # splice a ~60 calendar-day gap in the middle
            mid = len(df) // 2
            df = pd.concat([df.iloc[:mid], df.iloc[mid + 40:]], ignore_index=True)
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    out = path / "corrupted_panel.csv"
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


def test_survivorship_bias_insufficient_and_gaps_on_real_data_derived_panel():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        panel = _build_panel_csv(tmp)
        out_dir = tmp / "out"
        result = _run_panel_backtest(panel, out_dir)
        assert result.returncode == 0, (
            f"exit {result.returncode}\nstdout:\n{result.stdout[-2000:]}\nstderr:\n{result.stderr[-2000:]}"
        )

        surv_path = out_dir / "survivorship_bias.json"
        assert surv_path.is_file()
        surv = json.loads(surv_path.read_text())

        assert INSUFFICIENT_SYMBOL in surv["insufficient_data"], f"insufficient: {surv['insufficient_data']}"
        assert any(g["symbol"] == GAP_SYMBOL for g in surv["large_gaps"]), f"gaps: {surv['large_gaps']}"
        assert surv["bias_score"] > 0, f"bias_score: {surv['bias_score']}"

        prov = json.loads((out_dir / "data_provenance.json").read_text())
        assert sorted(prov.keys()) == sorted(SYMBOLS)
        for sym in SYMBOLS:
            assert prov[sym].get("checksum")

        summary = json.loads((out_dir / "tear_sheet_summary.json").read_text())
        assert summary.get("bias_controls_engaged") is True
        assert "survivorship_bias" in summary
        assert summary["survivorship_bias"].get("bias_score") == surv["bias_score"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
