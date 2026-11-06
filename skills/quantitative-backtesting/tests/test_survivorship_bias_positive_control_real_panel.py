#!/usr/bin/env python3
"""End-to-end survivorship-bias POSITIVE control on a real-data-derived panel.

Complements test_multi_symbol_pit_survivorship_real_panel.py (the negative
control: a complete, aligned AAPL/MSFT/GOOGL panel reports bias_score 0.0).
Here the panel is deterministically corrupted to simulate real-world universe
construction artifacts:

  - AAPL is truncated at the START (simulating a late entry / IPO that is
    present in the sample but was not tradable at sample open).
  - MSFT is truncated at the END (simulating a delisting / exit that is
    present in the sample but no longer tradable at sample close).

The detector must report AAPL as entered, MSFT as exited, GOOGL as the sole
survivor, bias_score > 0, and the artifacts (survivorship_bias.json,
data_provenance.json, tear_sheet_summary.json) must still be written with
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

# Truncate the first/last TRUNCATE_ROWS trading days (~3 calendar months of
# daily bars). Deterministic and pinned to the committed fixtures.
TRUNCATE_ROWS = 63
ENTERED_SYMBOL = "AAPL"
EXITED_SYMBOL = "MSFT"
SURVIVOR_SYMBOL = "GOOGL"


def _build_panel_csv(path: Path) -> Path:
    """Build a corrupted panel: AAPL missing its first TRUNCATE_ROWS bars
    (late entry) and MSFT missing its last TRUNCATE_ROWS bars (delisting)."""
    frames = []
    for sym in SYMBOLS:
        df = pd.read_csv(REAL_DATA / f"{sym}.csv")
        df["symbol"] = sym
        if sym == ENTERED_SYMBOL:
            df = df.iloc[TRUNCATE_ROWS:]  # late entry
        elif sym == EXITED_SYMBOL:
            df = df.iloc[:-TRUNCATE_ROWS]  # delisting
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


def test_survivorship_bias_positive_control_on_real_data_derived_panel():
    """A real-data-derived panel with a late entry (AAPL) and a delisting
    (MSFT) must be flagged by detect_survivorship_bias: the entered and
    exited symbols are reported, the sole survivor is GOOGL, bias_score > 0,
    and the audit artifacts are persisted with bias_controls_engaged == True.
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

        # Positive control: the detector must surface the injected biases.
        assert sorted(surv["surviving_symbols"]) == [SURVIVOR_SYMBOL], (
            f"expected sole survivor {SURVIVOR_SYMBOL}, got {surv['surviving_symbols']}"
        )
        entered = {e["symbol"] for e in surv["entered_symbols"]}
        assert ENTERED_SYMBOL in entered, (
            f"late-entry symbol {ENTERED_SYMBOL} not reported as entered: {entered}"
        )
        exited = {e["symbol"] for e in surv["exited_symbols"]}
        assert EXITED_SYMBOL in exited, (
            f"delisted symbol {EXITED_SYMBOL} not reported as exited: {exited}"
        )
        assert surv["insufficient_data"] == [], f"unexpected insufficient: {surv['insufficient_data']}"
        assert surv["large_gaps"] == [], f"unexpected gaps: {surv['large_gaps']}"
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


if __name__ == "__main__":
    test_survivorship_bias_positive_control_on_real_data_derived_panel()
    print("PASS  test_survivorship_bias_positive_control_on_real_data_derived_panel")
    print("OK")