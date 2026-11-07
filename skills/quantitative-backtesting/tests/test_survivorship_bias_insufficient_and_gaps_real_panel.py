#!/usr/bin/env python3
"""End-to-end survivorship-bias positive controls for the insufficient_data and
large_gaps branches of detect_survivorship_bias, exercised via
run_backtest.py --multi-symbol on a real-data-derived panel.

Complements:
- test_multi_symbol_pit_survivorship_real_panel.py (negative control: aligned
  complete AAPL/MSFT/GOOGL panel => bias_score 0.0, all surviving).
- test_survivorship_bias_positive_control_real_panel.py (positive control:
  late entry + delisting => entered/exited reported, bias_score > 0).

This test deterministically corrupts the committed 2010-2019 AAPL/MSFT/GOOGL
fixtures to trigger the remaining detector branches:

  - MSFT is truncated to INSUFFICIENT_ROWS contiguous rows starting at the
    global sample open (fewer than the default min_observations=252). It
    therefore also ends well before the global sample close and is reported as
    exited; the key assertion is that it appears in insufficient_data.
  - GOOGL has GAP_ROWS consecutive trading rows removed from its middle,
    creating a calendar gap well above the default max_gap_days=30 while
    keeping its start/end at the global boundaries and its observation count
    above min_observations. It is reported in large_gaps.
  - AAPL is kept intact as the reference symbol spanning the full range.

Run via the CLI (non-strict PIT; the focus is survivorship detection). This is
an audit of the survivorship control, not a profitability claim.
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

# Fewer than default min_observations=252; contiguous from global start so the
# gap detector does not fire on this symbol.
INSUFFICIENT_ROWS = 120
INSUFFICIENT_SYMBOL = "MSFT"

# Remove this many consecutive rows from the middle of GOOGL. 45 trading days
# spans >60 calendar days, exceeding default max_gap_days=30. GOOGL retains
# 2515-45=2470 rows (>252) and its original start/end dates.
GAP_ROWS = 45
GAP_SYMBOL = "GOOGL"
GAP_START_INDEX = 1000  # deterministic midpoint splice into the fixture

REFERENCE_SYMBOL = "AAPL"


def _build_panel_csv(path: Path) -> Path:
    """Build a panel with an insufficient-history symbol and a gapped symbol."""
    frames = []
    for sym in SYMBOLS:
        df = pd.read_csv(REAL_DATA / f"{sym}.csv")
        df["symbol"] = sym
        if sym == INSUFFICIENT_SYMBOL:
            df = df.iloc[:INSUFFICIENT_ROWS].copy()
        elif sym == GAP_SYMBOL:
            df = pd.concat(
                [df.iloc[:GAP_START_INDEX], df.iloc[GAP_START_INDEX + GAP_ROWS :]],
                ignore_index=True,
            )
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    out = path / "insufficient_and_gaps_panel.csv"
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


def test_survivorship_bias_insufficient_data_and_large_gaps_on_real_data_derived_panel():
    """A panel where one symbol has fewer than min_observations and another has
    an interior gap exceeding max_gap_days must be flagged by
    detect_survivorship_bias: insufficient_data and large_gaps are populated,
    bias_score > 0, and the audit artifacts are persisted with
    bias_controls_engaged == True.
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

        surv_path = out_dir / "survivorship_bias.json"
        assert surv_path.is_file(), "survivorship_bias.json not written"
        surv = json.loads(surv_path.read_text())

        # insufficient_data branch: MSFT truncated below min_observations=252.
        assert INSUFFICIENT_SYMBOL in surv["insufficient_data"], (
            f"expected {INSUFFICIENT_SYMBOL} in insufficient_data, got "
            f"{surv['insufficient_data']}"
        )

        # large_gaps branch: GOOGL has an interior gap > max_gap_days=30.
        gap_symbols = {e["symbol"] for e in surv["large_gaps"]}
        assert GAP_SYMBOL in gap_symbols, (
            f"expected {GAP_SYMBOL} in large_gaps, got {surv['large_gaps']}"
        )
        googl_gap = next(e for e in surv["large_gaps"] if e["symbol"] == GAP_SYMBOL)
        assert googl_gap["max_gap_days"] > 30, (
            f"expected GOOGL max_gap_days > 30, got {googl_gap['max_gap_days']}"
        )
        assert googl_gap.get("gap_date"), "large_gaps entry missing gap_date"

        # The detector reports issues; bias_score must be positive.
        assert surv["bias_score"] > 0.0, (
            f"expected positive bias_score on a corrupted panel, got {surv['bias_score']}"
        )

        # MSFT's truncation also makes it end before global close, so the
        # detector reports it as exited as well. Assert this to document the
        # full, deterministic detector output (not just the targeted branch).
        exited_symbols = {e["symbol"] for e in surv["exited_symbols"]}
        assert INSUFFICIENT_SYMBOL in exited_symbols, (
            f"truncated {INSUFFICIENT_SYMBOL} should also be reported as exited, "
            f"got {exited_symbols}"
        )

        # Reference symbol remains a full-history survivor relative to the
        # global range defined by AAPL/GOOGL.
        assert REFERENCE_SYMBOL in surv["surviving_symbols"], (
            f"expected {REFERENCE_SYMBOL} surviving, got {surv['surviving_symbols']}"
        )

        # Bias controls engaged and artifacts persisted.
        prov = json.loads((out_dir / "data_provenance.json").read_text())
        assert sorted(prov.keys()) == sorted(SYMBOLS)
        for sym in SYMBOLS:
            assert prov[sym].get("checksum"), f"missing checksum for {sym}"

        summary = json.loads((out_dir / "tear_sheet_summary.json").read_text())
        assert summary.get("bias_controls_engaged") is True
        assert "survivorship_bias" in summary
        assert summary["survivorship_bias"]["bias_score"] == surv["bias_score"]


if __name__ == "__main__":
    test_survivorship_bias_insufficient_data_and_large_gaps_on_real_data_derived_panel()
    print("PASS  test_survivorship_bias_insufficient_data_and_large_gaps_on_real_data_derived_panel")
    print("OK")
