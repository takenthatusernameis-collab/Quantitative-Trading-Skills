#!/usr/bin/env python3
"""Regression guard: Monte Carlo discloses regime robustness.

The Monte Carlo aggregate path (`walk_forward monte-carlo`) now surfaces
`summary["regime_robustness"]` (the regime-concentration diagnostic) alongside
`summary["regime_analysis"]`, so a consumer can see whether the edge is
diversified across regimes or concentrated in a single one. Mirrors
`test_walk_forward_records_regime_robustness` (walk-forward / CPCV) and
`test_run_backtest_records_regime_robustness` (single backtest).

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import main as walk_forward_main  # noqa: E402

SAMPLE_DATA = SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv"

VALID_CLASSIFICATIONS = ("robust", "moderate", "fragile", "insufficient_data")


def _assert_regime_robustness(rr, label):
    assert isinstance(rr, dict), f"{label}: regime_robustness must be a dict, got {type(rr)}"
    assert "regime_robustness" in rr, f"{label}: regime_robustness dict missing classification key"
    assert rr["regime_robustness"] in VALID_CLASSIFICATIONS, (
        f"{label}: unexpected classification {rr['regime_robustness']!r}"
    )


def test_monte_carlo_records_regime_robustness():
    """Monte Carlo summary carries regime_robustness next to regime_analysis.

    Invokes the CLI ``walk_forward monte-carlo`` path offline with the
    committed ``sample_ohlcv.csv`` fixture (no live network, no temp CSV
    generated) and asserts the saved ``monte_carlo_results.json`` artifact's
    summary carries a valid ``regime_robustness`` classification, mirroring
    the walk-forward / CPCV / single-backtest disclosure paths.
    """
    assert SAMPLE_DATA.exists(), f"missing committed fixture {SAMPLE_DATA}"
    with tempfile.TemporaryDirectory() as tmpdir:
        argv = [
            "walk_forward", "monte-carlo",
            "--data", str(SAMPLE_DATA),
            "--symbol", "SPY",
            "--strategy", "sma_crossover",
            "--param-grid", '{"fast_period": [5, 10], "slow_period": [20, 30]}',
            "--n-simulations", "50",
            "--output", tmpdir,
            "--impact-coefficient", "0",
        ]
        with patch.object(sys, "argv", argv), \
                contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            rc = walk_forward_main()

        assert rc == 0, f"CLI monte-carlo should exit 0, got {rc}"
        mc_path = os.path.join(tmpdir, "monte_carlo_results.json")
        assert os.path.exists(mc_path), "monte_carlo_results.json not written"
        with open(mc_path) as f:
            payload = json.load(f)

        summary = payload["summary"]
        assert "regime_analysis" in summary, (
            "monte_carlo summary must carry regime_analysis alongside regime_robustness"
        )
        assert "regime_robustness" in summary, (
            "monte_carlo summary must carry regime_robustness"
        )
        _assert_regime_robustness(summary["regime_robustness"], "monte_carlo")


if __name__ == "__main__":
    for name in sorted(globals()):
        if name.startswith("test_") and callable(globals()[name]):
            try:
                globals()[name]()
                print(f"PASS {name}")
            except Exception:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                print(f"FAIL {name}")
    print("OK")