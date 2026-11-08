#!/usr/bin/env python3
"""End-to-end survivorship-bias POSITIVE control for insufficient_data and
large_gaps branches on a real-data-derived panel.

Complements:
- test_multi_symbol_pit_survivorship_real_panel.py (negative control: complete
  aligned panel, bias_score 0.0)
- test_survivorship_bias_positive_control_real_panel.py (entered/exited)

This panel is deterministically corrupted from committed AAPL/MSFT/GOOGL
(2010-2019) fixtures:

  - AAPL is truncated to INSUFFICIENT_ROWS bars (< default min_observations=252),
    simulating a symbol with insufficient history for reliable inference.
  - MSFT has GAP_ROWS consecutive trading-day rows removed from the middle,
    creating a calendar gap well above max_gap_days=30 while preserving its
    start/end coverage (so it remains a "survivor" in span but is flagged for
    the gap).
  - GOOGL remains intact (full span, no gap, sufficient observations).

The detector must report AAPL in insufficient_data, MSFT in large_gaps,
GOOGL as surviving, bias_score > 0, and artifacts must be persisted with
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

INSUFFICIENT_ROWS = 100  # < default min_observations (252)
GAP_START_IDX = 1000     # deterministic splice point in MSFT
GAP_ROWS = 46            # ~65 calendar days removed => gap > 30 days
INSUFFICIENT_SYMBOL = "AAPL"
GAPPED_SYMBOL = "MSFT"
INTACT_SYMBOL = "GOOGL"


def _build_panel_csv(path: Path) -> Path:
    """Build a corrupted panel: AAPL insufficient history, MSFT has a large gap."""
    frames = []
    for sym in SYMBOLS:
        df = pd.read_csv(REAL_DATA / f"{sym}.csv")
        df["symbol"] = sym
        if sym == INSUFFICIENT_SYMBOL:
            # Keep only the tail INSUFFICIENT_ROWS bars: preserves recency but
            # leaves n_obs below min_observations and ends before global_end,
            # so the symbol is also an "exited" entry (both are expected).
            df = df.iloc[-INSUFFICIENT_ROWS:]
        elif sym == GAPPED_SYMBOL:
            # Remove a contiguous block from the middle to create a large gap
            # while keeping start/end unchanged.
            before = df.iloc[:GAP_START_IDX]
            after = df.iloc[GAP_START_IDX + GAP_ROWS:]
            df = pd.concat([before, after], ignore_index=True)
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    out = path / "corrupted_insufficient_gaps_panel.csv"
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
    """A real-data-derived panel with insufficient history (AAPL) and a large
    gap (MSFT) must be flagged: AAPL appears in insufficient_data, MSFT in
    large_gaps, GOOGL remains surviving, bias_score > 0, and artifacts are
    persisted with bias_controls_engaged == True.
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

        # GOOGL must still be a full-span survivor.
        assert INTACT_SYMBOL in surv["surviving_symbols"], (
            f"expected {INTACT_SYMBOL} surviving, got {surv['surviving_symbols']}"
        )

        # Insufficient-data branch.
        assert INSUFFICIENT_SYMBOL in surv["insufficient_data"], (
            f"expected {INSUFFICIENT_SYMBOL} in insufficient_data, got {surv['insufficient_data']}"
        )

        # Large-gaps branch.
        gap_symbols = {g["symbol"] for g in surv["large_gaps"]}
        assert GAPPED_SYMBOL in gap_symbols, (
            f"expected {GAPPED_SYMBOL} in large_gaps, got {surv['large_gaps']}"
        )
        msft_gap = next(g for g in surv["large_gaps"] if g["symbol"] == GAPPED_SYMBOL)
        assert msft_gap["max_gap_days"] > 30, (
            f"expected max_gap_days > 30 for injected gap, got {msft_gap['max_gap_days']}"
        )
        assert msft_gap.get("gap_date"), "large_gaps entry missing gap_date"

        assert surv["bias_score"] > 0.0, (
            f"expected positive bias_score on a corrupted panel, got {surv['bias_score']}"
        )

        # Bias controls must remain engaged and the artifacts persisted.
        prov = json.loads((out_dir / "data_provenance.json").read_text())
        assert sorted(prov.keys()) == sorted(SYMBOLS)
        for sym in SYMBOLS:
            assert prov[sym].get("checksum"), f"missing checksum for {sym}"

        summary = json.loads((out_dir / "tear_sheet_summary.json").read_text())
        assert summary.get("bias_controls_engaged") is True
        assert "survivorship_bias" in summary
        assert summary["survivorship_bias"]["bias_score"] == surv["bias_score"]
        assert INSUFFICIENT_SYMBOL in summary["survivorship_bias"]["insufficient_data"]
        assert GAPPED_SYMBOL in {g["symbol"] for g in summary["survivorship_bias"]["large_gaps"]}


if __name__ == "__main__":
    test_survivorship_bias_insufficient_data_and_large_gaps_on_real_data_derived_panel()
    print("PASS  test_survivorship_bias_insufficient_data_and_large_gaps_on_real_data_derived_panel")
    print("OK")
