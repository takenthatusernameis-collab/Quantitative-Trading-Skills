#!/usr/bin/env python3
"""Regime-robustness regression guard for SMA crossover on the committed
single-asset panel (AAPL).

Stratifies per-bar out-of-sample strategy returns (net of 2 bps commission +
1 bps slippage per trade) by market regime and compares the signal to a
buy-and-hold benchmark *within each regime*.

Regime labels: 200-day moving-average trend regime (bull / bear / sideways),
computed point-in-time (causal) via regime_detection.detect_trend_regime --
the label at bar t uses only closes up to and including bar t, so there is no
look-ahead into regime assignment.

Falsification criterion (pre-registered): the signal must beat the benchmark
(higher Sharpe ratio) in at least 2 of the 3 regimes net of costs; otherwise
the verdict is NOT SUPPORTED.

Honest outcome on this committed window: the signal wins 1 of 3 regimes
(sideways only) and loses in bull and bear, so the verdict is NOT SUPPORTED.
This test records the falsification outcome honestly and does not tune to
force SUPPORT.

Offline, committed fixtures only; no live network.
"""

import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from regime_detection import detect_trend_regime
from regime_robustness import run_regime_robustness_analysis

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

REL_TOL = 1e-3

# Pre-registered falsification threshold (>= 2 of 3 regimes).
MIN_REGIMES_WON = 2

# Measured on the committed AAPL fixture (net of costs). Regression guard
# only -- relative tolerance, never exact equality. The verdict is pinned as
# NOT SUPPORTED to enforce "do not tune to force SUPPORT": any future change
# that silently flips this to SUPPORTED fails this test.
EXPECTED_VERDICT = "NOT SUPPORTED"
EXPECTED_N_WON = 1
EXPECTED_N_EVALUATED = 3

EXPECTED = {
    "bear": {
        "strategy_sharpe": -0.23627517020820568,
        "benchmark_sharpe": 1.451629801394141,
    },
    "bull": {
        "strategy_sharpe": 0.12058921157124423,
        "benchmark_sharpe": 0.4534496163975293,
    },
    "sideways": {
        "strategy_sharpe": 3.3251793689417615,
        "benchmark_sharpe": 0.10278059166467346,
    },
}


def _run():
    assert (SRC / "AAPL.csv").exists()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_regime_robustness_analysis(
            data_path=SRC / "AAPL.csv",
            label="AAPL",
        )
    return result, buffer.getvalue()


def test_regime_robustness_sma_crossover_real_aapl_runs():
    result, _ = _run()
    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["signal"] == "sma_crossover"
    assert result["label"] == "AAPL"
    assert result["n_regimes_total"] == 3
    assert result["n_regimes_evaluated"] == EXPECTED_N_EVALUATED
    assert result["n_regimes_won"] == EXPECTED_N_WON
    assert result["min_regimes_won"] == MIN_REGIMES_WON
    assert set(result["regimes"]) == {"bear", "bull", "sideways"}
    for regime, detail in result["regimes"].items():
        assert set(detail) == {"strategy", "benchmark", "strategy_beats_benchmark_sharpe"}
        for side in ("strategy", "benchmark"):
            m = detail[side]
            for key in ("sharpe_ratio", "max_drawdown", "win_rate", "total_return", "n_observations"):
                assert key in m, f"missing {regime}/{side}/{key}"
        assert isinstance(detail["strategy_beats_benchmark_sharpe"], bool)
    assert result["verdict"] == ("SUPPORTED" if result["n_regimes_won"] >= MIN_REGIMES_WON else "NOT SUPPORTED")


def test_regime_robustness_sma_crossover_real_aapl_verdict_not_supported():
    """No-tuning rule: on the committed window the signal wins only 1 of 3
    regimes (sideways) and loses in bull and bear, so the honest verdict is
    NOT SUPPORTED. Any future change that flips this to SUPPORTED fails."""
    result, _ = _run()
    assert result["verdict"] == EXPECTED_VERDICT
    assert result["n_regimes_won"] == EXPECTED_N_WON
    assert result["n_regimes_won"] < MIN_REGIMES_WON


def test_regime_robustness_sma_crossover_real_aapl_metrics_pinned():
    """Regression guard: per-regime Sharpe ratios (net of costs) must remain
    stable on the committed fixture. Relative tolerance only, never exact
    equality. These are measured values, not profitability claims."""
    result, _ = _run()
    for regime, exp in EXPECTED.items():
        detail = result["regimes"][regime]
        got_s = detail["strategy"]["sharpe_ratio"]
        got_b = detail["benchmark"]["sharpe_ratio"]
        assert abs(got_s - exp["strategy_sharpe"]) <= REL_TOL * max(abs(exp["strategy_sharpe"]), 1e-9), (
            f"{regime} strategy Sharpe regression: got {got_s}, expected {exp['strategy_sharpe']}"
        )
        assert abs(got_b - exp["benchmark_sharpe"]) <= REL_TOL * max(abs(exp["benchmark_sharpe"]), 1e-9), (
            f"{regime} benchmark Sharpe regression: got {got_b}, expected {exp['benchmark_sharpe']}"
        )


def test_regime_robustness_sma_crossover_real_aapl_regime_labels_are_point_in_time():
    """Point-in-time correctness: the regime label at bar t must be
    reproducible from data up to and including bar t alone (causal), with no
    dependence on future bars."""
    import pandas as pd

    df = pd.read_csv(SRC / "AAPL.csv")
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    close = df["close"]

    full = detect_trend_regime(close, ma_short=50, ma_long=200, threshold=0.02)

    # Spot-check several cut points: the label at the last bar of each
    # prefix must equal the full-series label at that same bar.
    cut_points = [200, 400, 800, 1200, len(close) - 1]
    for cut in cut_points:
        if cut < 200:
            continue
        prefix = detect_trend_regime(close.iloc[: cut + 1], ma_short=50, ma_long=200, threshold=0.02)
        assert prefix.iloc[-1] == full.iloc[cut], (
            f"regime label at bar {cut} is not point-in-time: "
            f"prefix={prefix.iloc[-1]}, full={full.iloc[cut]}"
        )


if __name__ == "__main__":
    test_regime_robustness_sma_crossover_real_aapl_runs()
    test_regime_robustness_sma_crossover_real_aapl_verdict_not_supported()
    test_regime_robustness_sma_crossover_real_aapl_metrics_pinned()
    test_regime_robustness_sma_crossover_real_aapl_regime_labels_are_point_in_time()
    print("OK")
