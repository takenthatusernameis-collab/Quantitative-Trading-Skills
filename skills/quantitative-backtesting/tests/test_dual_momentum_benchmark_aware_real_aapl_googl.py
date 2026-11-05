#!/usr/bin/env python3
"""Benchmark-aware falsification test for dual momentum (absolute + relative
momentum, long-only) on the committed AAPL/GOOGL pair.

Runs the pre-registered BENCHMARK_CRITERIA set (OOS Sharpe > 0, OOS total
return > benchmark total return, Deflated Sharpe p-value < 0.10 across the
pre-registered parameter grid, and raw benchmark alpha p-value < 0.05 vs the
committed MSFT buy-and-hold benchmark) on the AAPL/GOOGL pair. Verdicts are
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
    BENCHMARK_CRITERIA,
    BENCHMARK_FILE,
    N_TRIALS,
    run_benchmark_aware_hypothesis_test,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def _build_pair_csv(dest: Path) -> Path:
    frames = []
    for name in ("AAPL.csv", "GOOGL.csv"):
        frame = pd.read_csv(SRC / name)
        frame["symbol"] = Path(name).stem
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    out = dest / "aapl_googl_pair.csv"
    combined.to_csv(out, index=False)
    return out


def test_benchmark_aware_hypothesis_runs_on_aapl_googl_real_window_dual_momentum():
    for name in ("AAPL.csv", "GOOGL.csv", "MSFT.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_pair_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_benchmark_aware_hypothesis_test(
                data_path, benchmark_path="MSFT.csv", n_trials=N_TRIALS
            )

    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["all_pass"] in (True, False)
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")
    assert len(result["criteria"]) == 4
    assert {c["name"] for c in result["criteria"]} == {
        name for name, _, _ in BENCHMARK_CRITERIA
    }
    out = buffer.getvalue()
    assert "VERDICT:" in out


def test_benchmark_metrics_pinned_on_aapl_googl_real_window_dual_momentum():
    """Regression guard: the benchmark-aware advertised run on the committed
    AAPL/GOOGL pair must reproduce the pinned strategy + benchmark metrics
    (net of costs) so a silent change to the backtest numbers is caught.
    Relative tolerance only, never exact equality. The verdict is
    NOT SUPPORTED: the strategy loses money on the held-out split
    (negative Sharpe and return) and fares far worse than buy-and-hold MSFT
    (+90.2%); benchmark alpha is not statistically significant and the
    Deflated Sharpe p-value is not significant across the pre-registered grid.
    This is the honest pre-registered outcome; the test does not tune to force
    SUPPORT.
    """
    for name in ("AAPL.csv", "GOOGL.csv", "MSFT.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_pair_csv(d)
        result = run_benchmark_aware_hypothesis_test(
            data_path, benchmark_path="MSFT.csv", n_trials=N_TRIALS
        )

    # Enforce the no-tuning rule: benchmark-aware verdict stays NOT SUPPORTED.
    assert result["verdict"] == "NOT SUPPORTED"
    assert result["all_pass"] is False

    expected_criteria = {
        "oos_sharpe_gt_zero": False,
        "oos_total_return_gt_benchmark": False,
        "deflated_sharpe_pvalue_lt_0.10": False,
        "benchmark_alpha_pvalue_lt_0.05": False,
    }
    for c in result["criteria"]:
        name = c["name"]
        assert name in expected_criteria, f"unexpected criterion {name}"
        assert c["passed"] == expected_criteria[name], (
            f"criterion {name} flipped: got {c['passed']}, expected "
            f"{expected_criteria[name]}"
        )

    observed = result.get("observed") or {}
    assert observed.get("benchmark_path") is not None
    assert str(observed["benchmark_path"]).endswith("MSFT.csv")
    assert observed.get("n_trials") == N_TRIALS

    EXPECTED = {
        "sharpe_ratio": -0.30135865959630453,
        "total_return": -0.06361793931133031,
        "benchmark_total_return": 0.9015402575236577,
        "benchmark_alpha": -0.07861132100133345,
        "benchmark_alpha_pvalue": 0.41999142422576474,
        "correlation_with_benchmark": 0.27173298962874365,
        "deflated_sharpe_pvalue": 0.9904800860018925,
    }
    REL_TOL = 1e-3
    for key, exp in EXPECTED.items():
        assert key in observed, f"missing observed metric {key}"
        got = observed[key]
        assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"{key} regression: got {got}, expected {exp}"
        )


if __name__ == "__main__":
    test_benchmark_aware_hypothesis_runs_on_aapl_googl_real_window_dual_momentum()
    test_benchmark_metrics_pinned_on_aapl_googl_real_window_dual_momentum()
    print("OK")
