#!/usr/bin/env python3
"""End-to-end survivorship-bias positive control: a symbol dropped at load time
due to data-validation failure must be reported, not silently hidden.

Regression for a universe-construction/survivorship blind spot: load_multi_symbol
drops symbols that fail validate_data (e.g. duplicate timestamps, invalid OHLC)
without surfacing them. If survivorship screening only sees the loaded survivors,
a corrupted/excluded symbol disappears and bias_score can be 0.0 on the reduced
universe — indistinguishable from a clean panel.

This test deterministically corrupts the committed 2010-2019 AAPL/MSFT/GOOGL
fixtures by injecting a duplicate timestamp row into MSFT. The CLI run
(--multi-symbol, non-strict PIT; focus is survivorship/universe integrity) must:
  - drop MSFT during load (data validation fails on duplicate dates),
  - report MSFT in survivorship_bias.invalid_data_dropped,
  - return bias_score > 0 (1/3 of the intended universe affected),
  - keep AAPL/GOOGL as survivors with checksums and bias_controls_engaged=True.

Audit of bias controls, not a profitability claim. Offline, committed fixtures
only.
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

DROPPED_SYMBOL = "MSFT"
SURVIVING_SYMBOLS = ["AAPL", "GOOGL"]


def _build_panel_csv(path: Path) -> Path:
    """Build a panel where MSFT contains a duplicate timestamp (validation fail)."""
    frames = []
    for sym in SYMBOLS:
        df = pd.read_csv(REAL_DATA / f"{sym}.csv")
        if sym == DROPPED_SYMBOL:
            # Insert a duplicate of row 50 -> duplicate date in index.
            df = pd.concat([df.iloc[:50], df.iloc[[50]], df.iloc[50:]], ignore_index=True)
        df["symbol"] = sym
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    out = path / "panel_dropped_invalid.csv"
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


def test_survivorship_bias_reports_symbol_dropped_for_validation_failure():
    """A symbol excluded at load due to validation failure (duplicate
    timestamp) must appear in invalid_data_dropped with bias_score > 0, not be
    silently omitted from the survivorship report.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        panel = _build_panel_csv(tmp)
        out_dir = tmp / "out"
        result = _run_panel_backtest(panel, out_dir)
        assert result.returncode == 0, (
            f"multi-symbol run aborted (exit {result.returncode})\n"
            f"stdout:\n{result.stdout[-2500:]}\nstderr:\n{result.stderr[-2500:]}"
        )

        combined = (result.stdout or "") + "\n" + (result.stderr or "")
        assert DROPPED_SYMBOL in combined and "dropped" in combined.lower(), (
            f"CLI output did not surface dropped symbol {DROPPED_SYMBOL}:\n{combined[-2500:]}"
        )

        surv_path = out_dir / "survivorship_bias.json"
        assert surv_path.is_file(), "survivorship_bias.json not written"
        surv = json.loads(surv_path.read_text())

        assert DROPPED_SYMBOL in surv.get("invalid_data_dropped", []), (
            f"expected {DROPPED_SYMBOL} in invalid_data_dropped, got "
            f"{surv.get('invalid_data_dropped')}"
        )
        assert sorted(surv["surviving_symbols"]) == sorted(SURVIVING_SYMBOLS)
        assert surv["insufficient_data"] == []
        assert surv["large_gaps"] == []
        # 1 of 3 intended symbols affected (dropped) => 1/3.
        assert abs(surv["bias_score"] - (1.0 / 3.0)) < 1e-9, (
            f"expected bias_score 1/3 for one dropped symbol in 3-symbol universe, "
            f"got {surv['bias_score']}"
        )

        prov = json.loads((out_dir / "data_provenance.json").read_text())
        assert sorted(prov.keys()) == sorted(SURVIVING_SYMBOLS)
        for sym in SURVIVING_SYMBOLS:
            assert prov[sym].get("checksum"), f"missing checksum for {sym}"

        summary = json.loads((out_dir / "tear_sheet_summary.json").read_text())
        assert summary.get("bias_controls_engaged") is True
        assert summary["survivorship_bias"].get("invalid_data_dropped") == [DROPPED_SYMBOL]


if __name__ == "__main__":
    test_survivorship_bias_reports_symbol_dropped_for_validation_failure()
    print("PASS  test_survivorship_bias_reports_symbol_dropped_for_validation_failure")
    print("OK")
