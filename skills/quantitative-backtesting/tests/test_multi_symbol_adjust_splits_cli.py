"""Regression: --multi-symbol must honor --adjust-splits (corporate actions/data-integrity).

Guards two bugs found in session 68:
- run_backtest.py CLI ignored --adjust-splits in the --multi-symbol load path.
- data_loader.load_multi_symbol raised ValueError when recording split
  provenance (splits_adjusted is a per-row Series, not a scalar).
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = SKILLS_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS))
from data_loader import load_multi_symbol  # noqa: E402


def _make_panel(path):
    rows = []
    dates = pd.date_range("2020-01-01", periods=60, freq="B")
    rng = np.random.default_rng(42)
    for sym, base in [("AAA", 100.0), ("BBB", 50.0)]:
        close = base + rng.standard_normal(len(dates)).cumsum() * 0.2
        for i, d in enumerate(dates):
            split = 2.0 if (sym == "AAA" and i == 30) else 1.0
            c = float(close[i])
            rows.append(
                {
                    "date": d.strftime("%Y-%m-%d"),
                    "symbol": sym,
                    "open": c,
                    "high": c * 1.01,
                    "low": c * 0.99,
                    "close": c,
                    "volume": 1_000_000,
                    "splits": split,
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False)


def test_load_multi_symbol_adjust_splits_changes_prices_and_provenance():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "panel.csv"
        _make_panel(p)
        raw, _ = load_multi_symbol(p, return_provenance=True, adjust_splits=False)
        adj, prov = load_multi_symbol(p, return_provenance=True, adjust_splits=True)
        # AAA has a 2:1 split at bar 30: pre-split prices halved (Yahoo convention).
        assert abs(adj["AAA"]["close"].iloc[0] - raw["AAA"]["close"].iloc[0] / 2.0) < 1e-9
        # BBB has no split: unchanged.
        assert abs(adj["BBB"]["close"].iloc[0] - raw["BBB"]["close"].iloc[0]) < 1e-12
        assert "split_adjustment_applied" in prov["AAA"].transformations_applied


def test_run_backtest_multi_symbol_cli_honors_adjust_splits():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        panel = td / "panel.csv"
        _make_panel(panel)
        base = [
            sys.executable,
            str(SCRIPTS / "run_backtest.py"),
            "--data",
            str(panel),
            "--multi-symbol",
            "--strategy",
            "cross_sectional_momentum",
            "--params",
            '{"lookback": 10, "top_quantile": 0.6, "bottom_quantile": 0.4}',
            "--commission",
            "0",
            "--slippage",
            "0",
        ]
        r_no = subprocess.run(
            base + ["--output", str(td / "no")],
            capture_output=True,
            text=True,
            cwd=str(SCRIPTS),
        )
        r_yes = subprocess.run(
            base + ["--adjust-splits", "--output", str(td / "yes")],
            capture_output=True,
            text=True,
            cwd=str(SCRIPTS),
        )
        assert r_no.returncode == 0, r_no.stdout[-1200:] + r_no.stderr[-1200:]
        assert r_yes.returncode == 0, r_yes.stdout[-1200:] + r_yes.stderr[-1200:]
        m_no = json.load(open(td / "no" / "metrics.json"))
        m_yes = json.load(open(td / "yes" / "metrics.json"))
        # Split adjustment on one panel leg must change the resulting metrics.
        assert (
            m_no["total_return"] != m_yes["total_return"]
            or m_no["sharpe_ratio"] != m_yes["sharpe_ratio"]
        ), "adjust-splits had no effect on multi-symbol panel metrics"
