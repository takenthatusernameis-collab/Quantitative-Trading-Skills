#!/usr/bin/env python3
"""Benchmark-aware falsification test for RSI mean reversion on the committed
two-asset panel (AAPL / GOOGL).

Runs the pre-registered BENCHMARK_CRITERIA set (OOS Sharpe > 0, OOS total
return > benchmark total return, Deflated Sharpe p-value < 0.10 across the
pre-registered parameter grid, and raw benchmark alpha p-value < 0.05 vs the
committed MSFT buy-and-hold benchmark) on the AAPL/GOOGL pair. Verdicts are
falsification outcomes, never profitability claims.

RSI mean reversion supports panel data via a per-asset target book priced with
panel_pricing="book" (true per-asset book return). The hypothesis runner
detects multi-symbol panel CSVs and passes --multi-symbol so the full panel is
loaded.

The benchmark-aware verdict is NOT SUPPORTED on this committed window: the
strategy loses money net of costs (Sharpe -0.2333, return -18.71%) while
buy-and-hold MSFT returns +90.15%, benchmark alpha is not statistically
significant (p=0.4165), and the Deflated Sharpe p-value is 0.9828 (N_TRIALS=5).
The test does not tune to force SUPPORT.

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

from rsi_mean_reversion_hypothesis import (  # noqa: E402
    BENCHMARK_CRITERIA,
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


def test_benchmark_aware_hypothesis_runs_on_aapl_googl_real_window_rsi_mean_reversion():
    for name in ("AAPL.csv", "GOOGL.csv", "MSFT.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_pair_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_benchmark_aware_hypothesis_test(data_path)

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
    assert "Chronological: True, Disjoint: True" in out
    assert "Point-in-time validation: True" in out
    assert "VERDICT:" in out


def test_benchmark_metrics_pinned_on_aapl_googl_real_window_rsi_mean_reversion():
    """Regression guard: the benchmark-aware advertised run on the committed
    AAPL/GOOGL pair must reproduce the pinned strategy + benchmark metrics
    (net of costs) so a silent change to the backtest numbers is caught.
    Relative tolerance only, never exact equality. Enforces the no-tuning rule:
    benchmark-aware verdict stays NOT SUPPORTED.
    """
    for name in ("AAPL.csv", "GOOGL.csv", "MSFT.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_pair_csv(d)
        result = run_benchmark_aware_hypothesis_test(data_path)

    observed = result.get("observed") or {}
    assert observed.get("benchmark_path") is not None
    assert str(observed["benchmark_path"]).endswith("MSFT.csv")
    assert observed.get("n_trials") == N_TRIALS

    EXPECTED = {
        "sharpe_ratio": -0.17963418984292787,
        "total_return": -0.15198041180791866,
        "benchmark_total_return": 0.1711375869976839,
        "benchmark_alpha": -0.15137494848768812,
        "benchmark_alpha_pvalue": 0.6721767235298922,
        "correlation_with_benchmark": 0.3469280373841266,
        "deflated_sharpe_pvalue": 0.9750473077098107,
    }
    REL_TOL = 1e-3
    for key, exp in EXPECTED.items():
        assert key in observed, f"missing {key}"
        got = observed[key]
        assert abs(got - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"{key} regression: got {got}, expected {exp}"
        )

    assert result["verdict"] == "NOT SUPPORTED"
    assert result["all_pass"] is False
    failed = [c["name"] for c in result["criteria"] if not c["passed"]]
    assert "oos_sharpe_gt_zero" in failed
    assert "oos_total_return_gt_benchmark" in failed
    assert "deflated_sharpe_pvalue_lt_0.10" in failed
    assert "benchmark_alpha_pvalue_lt_0.05" in failed


if __name__ == "__main__":
    test_benchmark_aware_hypothesis_runs_on_aapl_googl_real_window_rsi_mean_reversion()
    test_benchmark_metrics_pinned_on_aapl_googl_real_window_rsi_mean_reversion()
    print("OK")
