#!/usr/bin/env python3
"""Regime-robustness regression guard for SMA crossover on the committed
triple panel (AAPL+MSFT+GOOGL).

Runs the single-asset regime-robustness analysis on all three assets and
aggregates the results. The pre-registered falsification criterion requires
the signal to beat the benchmark (higher Sharpe ratio) in at least 2 of the 3
regimes net of costs *per asset*; otherwise the verdict is NOT SUPPORTED.

Honest outcome on this committed window: for each asset the signal wins 1 of 3
regimes (sideways only) and loses in bull and bear, so the verdict is NOT
SUPPORTED for all three assets and the panel verdict is NOT SUPPORTED.
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
from regime_robustness import run_regime_robustness_triple_panel

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

REL_TOL = 1e-3

# Pre-registered falsification threshold (>= 2 of 3 regimes per asset).
MIN_REGIMES_WON = 2

# Measured on the committed fixtures (net of costs). Regression guard
# only -- relative tolerance, never exact equality. The verdict is pinned as
# NOT SUPPORTED to enforce "do not tune to force SUPPORT": any future change
# that silently flips this to SUPPORTED fails this test.

# Per-asset expected values
EXPECTED_AAPL = {
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

EXPECTED_MSFT = {
    "bear": {
        "strategy_sharpe": -1.483717083197383,
        "benchmark_sharpe": -0.0048539210571094706,
    },
    "bull": {
        "strategy_sharpe": 0.6470929496470363,
        "benchmark_sharpe": 1.0539297073529,
    },
    "sideways": {
        "strategy_sharpe": 0.603684412831922,
        "benchmark_sharpe": 0.5927710661803279,
    },
}

EXPECTED_GOOGL = {
    "bear": {
        "strategy_sharpe": -0.4006175291370394,
        "benchmark_sharpe": -0.13438963976919285,
    },
    "bull": {
        "strategy_sharpe": 1.346657372150235,
        "benchmark_sharpe": 1.5549832709110525,
    },
    "sideways": {
        "strategy_sharpe": 2.0742415489313983,
        "benchmark_sharpe": 1.801497876702869,
    },
}

EXPECTED_ALL = {
    "AAPL": EXPECTED_AAPL,
    "MSFT": EXPECTED_MSFT,
    "GOOGL": EXPECTED_GOOGL,
}

EXPECTED_VERDICT = "NOT SUPPORTED"
EXPECTED_N_WON_PER_ASSET = 1
EXPECTED_N_EVALUATED_PER_ASSET = 3


def _run_triple():
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "MSFT.csv").exists()
    assert (SRC / "GOOGL.csv").exists()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_regime_robustness_triple_panel(data_dir=SRC)
    return result, buffer.getvalue()


def _run_single(label: str):
    data_path = SRC / f"{label}.csv"
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_regime_robustness_analysis(data_path=data_path, label=label)
    return result, buffer.getvalue()


def test_regime_robustness_sma_crossover_real_triple_runs():
    result, _ = _run_triple()
    assert isinstance(result, dict)
    assert result["signal"] == "sma_crossover"
    assert result["panel_verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["total_regimes_evaluated"] == 9  # 3 assets * 3 regimes
    assert result["total_regimes_won"] == 3  # 1 per asset
    assert result["min_regimes_won_per_asset"] == MIN_REGIMES_WON
    assert set(result["assets"]) == {"AAPL", "MSFT", "GOOGL"}

    for label in ("AAPL", "MSFT", "GOOGL"):
        asset = result["assets"][label]
        assert asset["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert asset["signal"] == "sma_crossover"
        assert asset["label"] == label
        assert asset["n_regimes_total"] == 3
        assert asset["n_regimes_evaluated"] == EXPECTED_N_EVALUATED_PER_ASSET
        assert asset["n_regimes_won"] == EXPECTED_N_WON_PER_ASSET
        assert asset["min_regimes_won"] == MIN_REGIMES_WON
        assert set(asset["regimes"]) == {"bear", "bull", "sideways"}
        for regime, detail in asset["regimes"].items():
            assert set(detail) == {"strategy", "benchmark", "strategy_beats_benchmark_sharpe"}
            for side in ("strategy", "benchmark"):
                m = detail[side]
                for key in ("sharpe_ratio", "max_drawdown", "win_rate", "total_return", "n_observations"):
                    assert key in m, f"missing {label}/{regime}/{side}/{key}"
            assert isinstance(detail["strategy_beats_benchmark_sharpe"], bool)


def test_regime_robustness_sma_crossover_real_triple_verdict_not_supported():
    """No-tuning rule: on the committed window each asset wins only 1 of 3
    regimes (sideways) and loses in bull and bear, so the honest verdict is
    NOT SUPPORTED for all three assets and the panel verdict is NOT SUPPORTED.
    Any future change that flips this to SUPPORTED fails."""
    result, _ = _run_triple()
    assert result["panel_verdict"] == EXPECTED_VERDICT
    for label in ("AAPL", "MSFT", "GOOGL"):
        asset = result["assets"][label]
        assert asset["verdict"] == EXPECTED_VERDICT
        assert asset["n_regimes_won"] == EXPECTED_N_WON_PER_ASSET
        assert asset["n_regimes_won"] < MIN_REGIMES_WON


def test_regime_robustness_sma_crossover_real_triple_metrics_pinned():
    """Regression guard: per-regime Sharpe ratios (net of costs) must remain
    stable on the committed fixtures. Relative tolerance only, never exact
    equality. These are measured values, not profitability claims."""
    result, _ = _run_triple()
    for label in ("AAPL", "MSFT", "GOOGL"):
        asset = result["assets"][label]
        for regime, exp in EXPECTED_ALL[label].items():
            detail = asset["regimes"][regime]
            got_s = detail["strategy"]["sharpe_ratio"]
            got_b = detail["benchmark"]["sharpe_ratio"]
            assert abs(got_s - exp["strategy_sharpe"]) <= REL_TOL * max(abs(exp["strategy_sharpe"]), 1e-9), (
                f"{label} {regime} strategy Sharpe regression: got {got_s}, expected {exp['strategy_sharpe']}"
            )
            assert abs(got_b - exp["benchmark_sharpe"]) <= REL_TOL * max(abs(exp["benchmark_sharpe"]), 1e-9), (
                f"{label} {regime} benchmark Sharpe regression: got {got_b}, expected {exp['benchmark_sharpe']}"
            )


def test_regime_robustness_sma_crossover_real_triple_regime_labels_are_point_in_time():
    """Point-in-time correctness: the regime label at bar t must be
    reproducible from data up to and including bar t alone (causal), with no
    dependence on future bars. Checked for all three assets."""
    import pandas as pd

    for label in ("AAPL", "MSFT", "GOOGL"):
        df = pd.read_csv(SRC / f"{label}.csv")
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
                f"{label} regime label at bar {cut} is not point-in-time: "
                f"prefix={prefix.iloc[-1]}, full={full.iloc[cut]}"
            )


if __name__ == "__main__":
    test_regime_robustness_sma_crossover_real_triple_runs()
    test_regime_robustness_sma_crossover_real_triple_verdict_not_supported()
    test_regime_robustness_sma_crossover_real_triple_metrics_pinned()
    test_regime_robustness_sma_crossover_real_triple_regime_labels_are_point_in_time()
    print("OK")