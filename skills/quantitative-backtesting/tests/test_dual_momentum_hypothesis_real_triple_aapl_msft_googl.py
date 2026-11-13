#!/usr/bin/env python3
"""Real-market falsification test for dual momentum (absolute + relative
momentum, long-only) on the committed three-asset panel (AAPL / MSFT / GOOGL).

Mirrors test_cross_sectional_momentum_hypothesis_real_triple_aapl_msft_googl.py
but for the dual momentum family, to determine whether this family passes the
pre-registered falsification criteria (OOS Sharpe > 0 and OOS total return > 0,
net of costs) on the same triple where cross-sectional momentum and multi-pair
z-score mean reversion were falsified or shown cost-fragile. Verdicts are
falsification outcomes, never profitability claims.
Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from dual_momentum_hypothesis import (  # noqa: E402
    run_hypothesis_test,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def _build_triple_csv(dest: Path) -> Path:
    frames = []
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        frame = pd.read_csv(SRC / name)
        frame["symbol"] = Path(name).stem
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    out = dest / "aapl_msft_googl_triple.csv"
    combined.to_csv(out, index=False)
    return out


def test_hypothesis_runs_on_triple_real_window_dual_momentum():
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_triple_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_hypothesis_test(
                data_path, "aapl_msft_googl triple dual momentum real window"
            )

    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["all_pass"] in (True, False)
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")
    assert len(result["criteria"]) == 2
    assert {c["name"] for c in result["criteria"]} == {
        "oos_sharpe_gt_zero",
        "oos_total_return_positive",
    }
    out = buffer.getvalue()
    assert "Chronological: True, Disjoint: True" in out
    assert "Point-in-time validation: True" in out
    assert "VERDICT:" in out


def test_baseline_metrics_pinned_on_triple_real_window_dual_momentum():
    """Regression guard: the baseline (no-benchmark) advertised run on the
    committed triple must reproduce the pinned out-of-sample metrics so a
    silent change to the backtest numbers is caught. Relative tolerance only,
    never exact equality (last decimals depend on the numpy/pandas build).
    """
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_triple_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_hypothesis_test(
                data_path, "aapl_msft_googl triple dual momentum real window"
            )

    observed = result.get("observed") or {}
    assert observed.get("sharpe_ratio") is not None
    assert observed.get("total_return") is not None

    EXPECTED = {
        "sharpe_ratio": 0.5714563609925428,
        "total_return": 0.07873174188606424,
    }
    REL_TOL = 1e-3
    for key, exp in EXPECTED.items():
        got = observed[key]
        assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"{key} regression: got {got}, expected {exp}"
        )
    assert observed.get("benchmark_path") is None


if __name__ == "__main__":
    test_hypothesis_runs_on_triple_real_window_dual_momentum()
    test_baseline_metrics_pinned_on_triple_real_window_dual_momentum()
    print("OK")