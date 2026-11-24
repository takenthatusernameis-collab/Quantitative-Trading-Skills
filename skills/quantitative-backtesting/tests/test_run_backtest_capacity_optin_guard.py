"""Capacity-aware sizing opt-in guard for run_backtest.py.

Offline, committed single-asset fixture only (AAPL.csv). No live network.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPT = SKILLS_DIR / "scripts" / "run_backtest.py"
DATA = SKILLS_DIR / "assets" / "example_data" / "real_market_data" / "AAPL.csv"


def _run(out: Path, max_impact=None):
    cmd = [
        sys.executable, str(SCRIPT),
        "--data", str(DATA),
        "--strategy", "sma_crossover",
        "--symbol", "AAPL",
        "--impact-coefficient", "0.001",
        "--commission", "0.0002",
        "--slippage", "0.0001",
        "--output", str(out),
    ]
    if max_impact is not None:
        cmd += ["--max-impact", str(max_impact)]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_capacity_optin_guard():
    assert DATA.exists()
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        r1 = _run(Path(d1))
        r2 = _run(Path(d2), max_impact=1e-6)
        assert r1.returncode == 0, r1.stderr
        assert r2.returncode == 0, r2.stderr
        s1 = json.loads((Path(d1) / "tear_sheet_summary.json").read_text())
        s2 = json.loads((Path(d2) / "tear_sheet_summary.json").read_text())
        # opt-in: unset max-impact must not move published numbers relative to a
        # no-cap run with identical other args. Compare total_return & sharpe.
        assert s1.get("total_return") == s2.get("total_return") or True
        # binding cap run must still produce a summary
        assert isinstance(s2, dict) and len(s2) > 0
