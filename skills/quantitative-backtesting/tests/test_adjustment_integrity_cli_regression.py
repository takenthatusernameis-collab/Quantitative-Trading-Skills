"""End-to-end regression for split-adjustment provenance and adjustment_integrity_guard.

Verifies that run_backtest.py --multi-symbol --adjust-splits correctly:
1. Records split_adjustment_applied in transformations_applied
2. Runs adjustment_integrity_guard on the original data (pre-adjustment) and
   serializes the result to tear_sheet_summary.json data_provenance.
3. Positive control: clean data -> adjustment_integrity.passed == True
4. Negative control: corrupted adj_close -> adjustment_integrity.passed == False
   with reproducible/look-ahead-related violations visibly recorded.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _make_panel(path: Path, corrupt_adj_close: bool = False):
    """Build a two-symbol panel with a recorded 2-for-1 split on AAA at bar 30.

    close follows the Yahoo convention: pre-split prices are at pre-split level
    (2x post-split), post-split prices are at post-split level. adj_close is the
    continuous post-split series. When corrupt_adj_close=True, adj_close for AAA
    is multiplied by 1.5 to produce a deterministic guard failure.
    """
    rows = []
    dates = pd.date_range("2020-01-01", periods=60, freq="B")
    rng = np.random.default_rng(42)
    for sym, base in [("AAA", 100.0), ("BBB", 50.0)]:
        post_split_close = base + rng.standard_normal(len(dates)).cumsum() * 0.2
        split_ratios = np.ones(len(dates))
        if sym == "AAA":
            split_ratios[30] = 2.0
            close = post_split_close.copy()
            close[:30] = close[:30] * 2.0  # pre-split level
        else:
            close = post_split_close
        adj_close = post_split_close
        if corrupt_adj_close and sym == "AAA":
            adj_close = adj_close * 1.5  # deterministic corruption
        for i, d in enumerate(dates):
            c = float(close[i])
            ac = float(adj_close[i])
            rows.append(
                {
                    "date": d.strftime("%Y-%m-%d"),
                    "symbol": sym,
                    "open": c,
                    "high": c * 1.01,
                    "low": c * 0.99,
                    "close": c,
                    "adj_close": ac,
                    "volume": 1_000_000,
                    "splits": float(split_ratios[i]),
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False)


def _run_cli(panel: Path, output_dir: Path) -> subprocess.CompletedProcess:
    """Run run_backtest.py with the standard cross_sectional_momentum config."""
    cmd = [
        sys.executable,
        str(SCRIPTS / "run_backtest.py"),
        "--data",
        str(panel),
        "--multi-symbol",
        "--adjust-splits",
        "--strategy",
        "cross_sectional_momentum",
        "--params",
        '{"lookback": 10, "top_quantile": 0.6, "bottom_quantile": 0.4}',
        "--commission",
        "0",
        "--slippage",
        "0",
        "--output",
        str(output_dir),
    ]
    return subprocess.run(cmd, capture_output=True, text=True, cwd=".")


def _read_provenance(summary_path: Path) -> dict:
    with open(summary_path) as f:
        summary = json.load(f)
    return summary.get("data_provenance", {})


def test_positive_control_clean_data_passes_guard():
    """Clean panel with recorded split -> guard passes for both symbols."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        panel = td / "panel.csv"
        _make_panel(panel, corrupt_adj_close=False)
        output_dir = td / "output"

        result = _run_cli(panel, output_dir)
        assert result.returncode == 0, f"CLI failed: {result.stdout[-500:]} {result.stderr[-500:]}"

        prov = _read_provenance(output_dir / "tear_sheet_summary.json")
        assert "AAA" in prov and "BBB" in prov

        for sym in ("AAA", "BBB"):
            adj = prov[sym].get("adjustment_integrity", {})
            assert adj.get("passed") is True, f"{sym}: expected passed, got {adj.get('violations')}"
            assert "split_adjustment_applied" in prov[sym].get("transformations_applied", [])


def test_negative_control_corrupted_adj_close_fails_guard():
    """Corrupted adj_close on AAA -> guard fails visibly for AAA, passes for BBB."""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        panel = td / "panel.csv"
        _make_panel(panel, corrupt_adj_close=True)
        output_dir = td / "output"

        result = _run_cli(panel, output_dir)
        assert result.returncode == 0, f"CLI failed: {result.stdout[-500:]} {result.stderr[-500:]}"

        prov = _read_provenance(output_dir / "tear_sheet_summary.json")
        assert "AAA" in prov and "BBB" in prov

        # AAA: corrupted -> guard fails with reproducibility/look-ahead violations
        aaa_adj = prov["AAA"].get("adjustment_integrity", {})
        assert aaa_adj.get("passed") is False, "AAA should fail with corrupted adj_close"
        violations = aaa_adj.get("violations", [])
        assert any("not reproducible" in v for v in violations), f"missing reproducibility violation: {violations}"
        assert any("non-split date" in v or "illegal_change" in v.lower() or "ratio changes at non-split" in v for v in violations), f"missing look-ahead violation: {violations}"

        # BBB: clean -> guard passes
        bbb_adj = prov["BBB"].get("adjustment_integrity", {})
        assert bbb_adj.get("passed") is True, f"BBB should pass: {bbb_adj.get('violations')}"
        assert "split_adjustment_applied" in prov["BBB"].get("transformations_applied", [])


if __name__ == "__main__":
    # Allow running as a script for quick manual verification
    import sys

    tests = [test_positive_control_clean_data_passes_guard, test_negative_control_corrupted_adj_close_fails_guard]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
            passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} tests passed")
    sys.exit(0 if passed == len(tests) else 1)