#!/usr/bin/env python3
"""End-to-end audit: multi-symbol panel on committed real-market fixtures with
strict point-in-time validation and survivorship-bias screening.

Falsifiable controls (offline, committed fixtures only; no live network):
- A panel built from AAPL/MSFT/GOOGL (2010-2019, aligned full histories) must
  pass --point-in-time-strict: the cross-sectional signal uses only
  information available at decision time (no look-ahead).
- Survivorship detection must report all three symbols as surviving with
  bias_score 0.0 and no entered/exited symbols, because the fixtures share an
  identical, complete date range (a negative control: the detector must NOT
  manufacture survivorship bias on a complete panel).
- Per-symbol data provenance (checksums) and a survivorship_bias.json artifact
  must be written; bias_controls_engaged must be true in the tear-sheet summary.

This is an audit of the methodology controls, not a profitability claim.
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


def _build_panel_csv(path: Path) -> Path:
    frames = []
    for sym in SYMBOLS:
        df = pd.read_csv(REAL_DATA / f"{sym}.csv")
        df["symbol"] = sym
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    out = path / "real_panel.csv"
    panel.to_csv(out, index=False)
    return out


def _run_panel_backtest(panel_csv: Path, out_dir: Path, extra_args=None):
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "run_backtest.py"),
        "--data", str(panel_csv),
        "--multi-symbol",
        "--strategy", "cross_sectional_momentum",
        # Asymmetric quantiles on 3 assets produce a non-flat net-exposure
        # signal (2 long, 1 short => net +1/3) so the engine takes a position.
        "--params", '{"lookback": 60, "top_quantile": 0.67, "bottom_quantile": 0.34}',
        "--commission", "0.0002",
        "--slippage", "0.0001",
        "--train-frac", "0.6",
        "--val-frac", "0.2",
        "--test-frac", "0.2",
        "--run-split", "test",
        "--validate-point-in-time",
        "--point-in-time-strict",
        "--output", str(out_dir),
    ] + (extra_args or [])
    return subprocess.run(cmd, cwd=str(SCRIPTS_DIR), capture_output=True, text=True)


def test_multi_symbol_pit_strict_passes_on_complete_real_panel():
    """Strict PIT validation must accept a legitimate cross-sectional signal on
    a complete, aligned real panel (no look-ahead)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        panel = _build_panel_csv(tmp)
        out_dir = tmp / "out"
        result = _run_panel_backtest(panel, out_dir)
        assert result.returncode == 0, (
            f"multi-symbol PIT strict run aborted (exit {result.returncode})\n"
            f"stdout:\n{result.stdout[-2500:]}\nstderr:\n{result.stderr[-2500:]}"
        )
        assert "Point-in-time validation passed" in result.stdout, (
            f"PIT pass not surfaced in CLI output:\n{result.stdout[-2000:]}"
        )


def test_survivorship_bias_negative_control_on_aligned_real_histories():
    """Aligned AAPL/MSFT/GOOGL histories (identical date range) must produce
    bias_score 0.0 with all symbols surviving and no entry/exit events."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        panel = _build_panel_csv(tmp)
        out_dir = tmp / "out"
        result = _run_panel_backtest(panel, out_dir)
        assert result.returncode == 0, result.stderr[-2000:]

        surv_path = out_dir / "survivorship_bias.json"
        assert surv_path.is_file(), "survivorship_bias.json not written"
        surv = json.loads(surv_path.read_text())

        assert sorted(surv["surviving_symbols"]) == sorted(SYMBOLS)
        assert surv["entered_symbols"] == [], f"unexpected entries: {surv['entered_symbols']}"
        assert surv["exited_symbols"] == [], f"unexpected exits: {surv['exited_symbols']}"
        assert surv["insufficient_data"] == [], f"unexpected insufficient: {surv['insufficient_data']}"
        assert surv["large_gaps"] == [], f"unexpected gaps: {surv['large_gaps']}"
        assert surv["bias_score"] == 0.0, f"expected zero bias on complete panel, got {surv['bias_score']}"


def test_multi_symbol_provenance_and_bias_controls_recorded():
    """Per-symbol provenance checksums and bias_controls_engaged must be
    recorded in the audit artifacts."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        panel = _build_panel_csv(tmp)
        out_dir = tmp / "out"
        result = _run_panel_backtest(panel, out_dir)
        assert result.returncode == 0, result.stderr[-2000:]

        prov = json.loads((out_dir / "data_provenance.json").read_text())
        assert sorted(prov.keys()) == sorted(SYMBOLS)
        for sym in SYMBOLS:
            assert prov[sym].get("checksum"), f"missing checksum for {sym}"

        summary = json.loads((out_dir / "tear_sheet_summary.json").read_text())
        pit = summary.get("point_in_time_validation")
        assert pit is not None, "point_in_time_validation missing from summary"
        assert pit.get("passed") is True, f"PIT did not pass: {pit}"
        assert pit.get("violations") == [], f"unexpected PIT violations: {pit.get('violations')}"
        assert summary.get("bias_controls_engaged") is True
        assert "survivorship_bias" in summary


if __name__ == "__main__":
    test_multi_symbol_pit_strict_passes_on_complete_real_panel()
    print("PASS  test_multi_symbol_pit_strict_passes_on_complete_real_panel")
    test_survivorship_bias_negative_control_on_aligned_real_histories()
    print("PASS  test_survivorship_bias_negative_control_on_aligned_real_histories")
    test_multi_symbol_provenance_and_bias_controls_recorded()
    print("PASS  test_multi_symbol_provenance_and_bias_controls_recorded")
    print("OK")
