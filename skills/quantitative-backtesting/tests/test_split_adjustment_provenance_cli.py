"""End-to-end regression: split-adjustment provenance and adjustment_integrity_guard.

Verifies that per-symbol split-adjustment provenance and guard results survive
CLI execution into tear_sheet_summary.json, and that a deterministic adj_close
corruption is recorded visibly (advisory, not silently dropped).
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPT = SKILLS_DIR / "scripts" / "run_backtest.py"


def _make_panel(path: Path, corrupt_adj_close: bool = False) -> None:
    rows = []
    dates = pd.date_range("2020-01-01", periods=60, freq="B")
    rng = np.random.default_rng(42)
    for sym, base in [("AAA", 100.0), ("BBB", 50.0)]:
        close = base + rng.standard_normal(len(dates)).cumsum() * 0.2
        for i, d in enumerate(dates):
            split = 2.0 if (sym == "AAA" and i == 30) else 1.0
            c = float(close[i])
            # Fixture consistent with --adjust-splits: load_multi_symbol applies
            # _adjust_for_splits (dividing pre-split OHLC by split ratio) but
            # leaves adj_close unchanged, then adjustment_integrity_guard runs
            # on the ORIGINAL data BEFORE adjustment and checks adj_close
            # against the raw close and recorded split factors. Under the
            # guard's convention (a split with ratio r at date k means close on
            # and after k is already at the post-split level), expected
            # adj_close[t] == close[t] / cum_split_after[t], so for AAA's 2:1
            # split at i==30 the pre-split adj_close is raw c/2 and on/after it
            # is c. (c/4 would be off by a factor of 2 and fail the guard.)
            if sym == "AAA" and i < 30:
                adj_close = c / 2.0
            else:
                adj_close = c
            if corrupt_adj_close and sym == "AAA":
                adj_close = c * 1.234567  # deterministic corruption
            rows.append(
                {
                    "date": d.strftime("%Y-%m-%d"),
                    "symbol": sym,
                    "open": c,
                    "high": c * 1.01,
                    "low": c * 0.99,
                    "close": c,
                    "adj_close": adj_close,
                    "volume": 1_000_000,
                    "splits": split,
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False)


def _run_cli(panel: Path, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
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
            "--adjust-splits",
            "--output",
            str(out),
        ],
        capture_output=True,
        text=True,
    )


def _load_summary(out: Path) -> dict:
    with open(out / "tear_sheet_summary.json") as f:
        return json.load(f)


def test_adjust_splits_records_split_provenance_and_guard_pass_in_summary():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        panel = td / "panel.csv"
        out = td / "out"
        _make_panel(panel, corrupt_adj_close=False)
        r = _run_cli(panel, out)
        assert r.returncode == 0, r.stdout[-1200:] + r.stderr[-1200:]
        summary = _load_summary(out)
        prov = summary.get("data_provenance")
        assert isinstance(prov, dict), prov
        assert set(prov.keys()) == {"AAA", "BBB"}

        aaa = prov["AAA"]
        assert "split_adjustment_applied" in aaa.get("transformations_applied", []), aaa
        guard = aaa.get("adjustment_integrity")
        assert isinstance(guard, dict), aaa
        assert guard.get("passed") is True, guard
        assert guard.get("violations") == [], guard

        bbb = prov["BBB"]
        assert "split_adjustment_applied" in bbb.get("transformations_applied", []), bbb
        assert bbb.get("adjustment_integrity", {}).get("passed") is True, bbb


def test_corrupted_adj_close_is_recorded_visibly_not_silently_dropped():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        panel = td / "panel.csv"
        out = td / "out"
        _make_panel(panel, corrupt_adj_close=True)
        r = _run_cli(panel, out)
        assert r.returncode == 0, r.stdout[-1200:] + r.stderr[-1200:]
        summary = _load_summary(out)
        prov = summary.get("data_provenance")
        assert isinstance(prov, dict), prov

        aaa_guard = prov["AAA"].get("adjustment_integrity")
        assert isinstance(aaa_guard, dict), prov["AAA"]
        assert aaa_guard.get("passed") is False, aaa_guard
        violations = aaa_guard.get("violations") or []
        assert any("not reproducible" in v for v in violations), violations

        bbb_guard = prov["BBB"].get("adjustment_integrity")
        assert bbb_guard.get("passed") is True, bbb_guard
