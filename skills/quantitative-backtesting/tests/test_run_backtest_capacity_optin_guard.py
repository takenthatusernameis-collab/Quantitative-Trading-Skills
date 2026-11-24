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


def _run(out: Path, max_impact=None, impact_coefficient=1.0):
    cmd = [
        sys.executable, str(SCRIPT),
        "--data", str(DATA),
        "--strategy", "sma_crossover",
        "--symbol", "AAPL",
        "--impact-coefficient", str(impact_coefficient),
        "--commission", "0.0002",
        "--slippage", "0.0001",
        "--output", str(out),
    ]
    if max_impact is not None:
        cmd += ["--max-impact", str(max_impact)]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_capacity_optin_guard():
    assert DATA.exists()
    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2, tempfile.TemporaryDirectory() as d3:
        r_loose = _run(Path(d1), max_impact=1.0)
        r_unset = _run(Path(d2))
        assert r_loose.returncode == 0, r_loose.stderr
        assert r_unset.returncode == 0, r_unset.stderr
        s_loose = json.loads((Path(d1) / "tear_sheet_summary.json").read_text())
        s_unset = json.loads((Path(d2) / "tear_sheet_summary.json").read_text())
        assert s_loose["metrics"]["total_return"] == s_unset["metrics"]["total_return"]
        assert s_loose["metrics"]["sharpe_ratio"] == s_unset["metrics"]["sharpe_ratio"]

        r_cap = _run(Path(d3), max_impact=1e-4, impact_coefficient=1.0)
        assert r_cap.returncode == 0, r_cap.stderr
        s_cap = json.loads((Path(d3) / "tear_sheet_summary.json").read_text())
        assert s_cap["metrics"]["capacity"] < s_unset["metrics"]["capacity"]