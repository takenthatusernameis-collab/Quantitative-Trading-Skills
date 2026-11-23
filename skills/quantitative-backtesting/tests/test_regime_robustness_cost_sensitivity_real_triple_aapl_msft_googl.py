#!/usr/bin/env python3
"""Cost sensitivity for the regime-robustness SMA crossover on the committed
triple panel (AAPL+MSFT+GOOGL).

Runs `run_regime_robustness_triple_panel` at four ascending commission /
slippage levels: frictionless (0 bp / 0 bp), advertised (2 bp / 1 bp,
pre-registered), elevated (5 bp / 5 bp), and high (10 bp / 10 bp).

METHODOLOGICAL NOTE (committed fixtures only, not evidence about any market):
The advertised-level result is already pinned NOT SUPPORTED by
test_regime_robustness_sma_crossover_real_triple_aapl_msft_googl.py: each
asset wins only 1 of 3 regimes (sideways) and loses in bull and bear. This
test strengthens that falsification in two directions:

  * Even at frictionless (zero trading cost) the verdict is still NOT
    SUPPORTED, so transaction costs are not the reason the signal fails --
    the signal underperforms buy-and-hold on risk-adjusted returns in bull
    and bear regimes even with no costs at all. Costs are not an excuse.
  * As costs rise, total_regimes_won degrades (3 -> 3 -> 2 -> 2): MSFT's
    sideways regime stops beating the benchmark once costs exceed the
    advertised level. No profitability claim is made; the honest verdict
    remains NOT SUPPORTED at every tested cost level.

Offline, committed fixtures only; no live network. Regression pins use
relative tolerance only, never exact equality. These are measured values,
not profitability claims.
"""
import contextlib
import io
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
if str(SKILLS_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from regime_robustness import run_regime_robustness_triple_panel

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

REL_TOL = 1e-3

# Ascending cost levels (commission, slippage) as decimal fractions.
COST_LEVELS = [
    (0.0, 0.0),      # frictionless
    (0.0002, 0.0001),  # advertised: 2 bp commission + 1 bp slippage
    (0.0005, 0.0005),  # elevated: 5 bp / 5 bp
    (0.0010, 0.0010),  # high: 10 bp / 10 bp
]

# Per-asset expected won count and verdict at each cost level.
# Frictionless/advertised: 3 regimes won total (1 per asset). Elevated/high:
# 2 won total (MSFT sideways flips to a loss; AAPL and GOOGL keep sideways).
EXPECTED_WON = {
    (0.0, 0.0): {"panel": 3, "AAPL": 1, "MSFT": 1, "GOOGL": 1},
    (0.0002, 0.0001): {"panel": 3, "AAPL": 1, "MSFT": 1, "GOOGL": 1},
    (0.0005, 0.0005): {"panel": 2, "AAPL": 1, "MSFT": 0, "GOOGL": 1},
    (0.0010, 0.0010): {"panel": 2, "AAPL": 1, "MSFT": 0, "GOOGL": 1},
}
EXPECTED_VERDICT = "NOT SUPPORTED"

# Benchmark Sharpe ratios are cost-invariant (buy-and-hold raw returns carry
# no trading cost); strategy Sharpe ratios degrade as costs rise. Measured on
# the committed fixtures. Regression guard only -- relative tolerance, never
# exact equality; these are measured values, not profitability claims.
EXPECTED = {
    (0.0, 0.0): {
        "AAPL": {
            "bear": {"strategy_sharpe": -0.22120129401026895, "benchmark_sharpe": 1.451629801394141},
            "bull": {"strategy_sharpe": 0.12932345724605787, "benchmark_sharpe": 0.4534496163975293},
            "sideways": {"strategy_sharpe": 3.3346002741569705, "benchmark_sharpe": 0.10278059166467346},
        },
        "MSFT": {
            "bear": {"strategy_sharpe": -1.4726733630551423, "benchmark_sharpe": -0.0048539210571094706},
            "bull": {"strategy_sharpe": 0.6567608527241225, "benchmark_sharpe": 1.0539297073529},
            "sideways": {"strategy_sharpe": 0.6210516165321742, "benchmark_sharpe": 0.5927710661803279},
        },
        "GOOGL": {
            "bear": {"strategy_sharpe": -0.3883665748970252, "benchmark_sharpe": -0.13438963976919285},
            "bull": {"strategy_sharpe": 1.3541125751330434, "benchmark_sharpe": 1.5549832709110525},
            "sideways": {"strategy_sharpe": 2.0794934207231126, "benchmark_sharpe": 1.801497876702869},
        },
    },
    (0.0002, 0.0001): {
        "AAPL": {
            "bear": {"strategy_sharpe": -0.23627517020820568, "benchmark_sharpe": 1.451629801394141},
            "bull": {"strategy_sharpe": 0.12058921157124423, "benchmark_sharpe": 0.4534496163975293},
            "sideways": {"strategy_sharpe": 3.3251793689417615, "benchmark_sharpe": 0.10278059166467346},
        },
        "MSFT": {
            "bear": {"strategy_sharpe": -1.483717083197383, "benchmark_sharpe": -0.0048539210571094706},
            "bull": {"strategy_sharpe": 0.6470929496470363, "benchmark_sharpe": 1.0539297073529},
            "sideways": {"strategy_sharpe": 0.603684412831922, "benchmark_sharpe": 0.5927710661803279},
        },
        "GOOGL": {
            "bear": {"strategy_sharpe": -0.4006175291370394, "benchmark_sharpe": -0.13438963976919285},
            "bull": {"strategy_sharpe": 1.346657372150235, "benchmark_sharpe": 1.5549832709110525},
            "sideways": {"strategy_sharpe": 2.0742415489313983, "benchmark_sharpe": 1.801497876702869},
        },
    },
    (0.0005, 0.0005): {
        "AAPL": {
            "bear": {"strategy_sharpe": -0.2712347759655968, "benchmark_sharpe": 1.451629801394141},
            "bull": {"strategy_sharpe": 0.10025162757350904, "benchmark_sharpe": 0.4534496163975293},
            "sideways": {"strategy_sharpe": 3.3031267587402864, "benchmark_sharpe": 0.10278059166467346},
        },
        "MSFT": {
            "bear": {"strategy_sharpe": -1.5092467515611818, "benchmark_sharpe": -0.0048539210571094706},
            "bull": {"strategy_sharpe": 0.6245572763602154, "benchmark_sharpe": 1.0539297073529},
            "sideways": {"strategy_sharpe": 0.5632059958579037, "benchmark_sharpe": 0.5927710661803279},
        },
        "GOOGL": {
            "bear": {"strategy_sharpe": -0.42910315428648904, "benchmark_sharpe": -0.13438963976919285},
            "bull": {"strategy_sharpe": 1.3292584595467778, "benchmark_sharpe": 1.5549832709110525},
            "sideways": {"strategy_sharpe": 2.06195461821891, "benchmark_sharpe": 1.801497876702869},
        },
    },
    (0.0010, 0.0010): {
        "AAPL": {
            "bear": {"strategy_sharpe": -0.3206373860209602, "benchmark_sharpe": 1.451629801394141},
            "bull": {"strategy_sharpe": 0.071307567863824, "benchmark_sharpe": 0.4534496163975293},
            "sideways": {"strategy_sharpe": 3.2714566042056235, "benchmark_sharpe": 0.10278059166467346},
        },
        "MSFT": {
            "bear": {"strategy_sharpe": -1.5451206852243415, "benchmark_sharpe": -0.0048539210571094706},
            "bull": {"strategy_sharpe": 0.592426745331473, "benchmark_sharpe": 1.0539297073529},
            "sideways": {"strategy_sharpe": 0.5055238838486275, "benchmark_sharpe": 0.5927710661803279},
        },
        "GOOGL": {
            "bear": {"strategy_sharpe": -0.469540842574153, "benchmark_sharpe": -0.13438963976919285},
            "bull": {"strategy_sharpe": 1.3043975859007322, "benchmark_sharpe": 1.5549832709110525},
            "sideways": {"strategy_sharpe": 2.044324537569114, "benchmark_sharpe": 1.801497876702869},
        },
    },
}


def _run(commission: float, slippage: float):
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "MSFT.csv").exists()
    assert (SRC / "GOOGL.csv").exists()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_regime_robustness_triple_panel(
            data_dir=SRC,
            commission=commission,
            slippage=slippage,
        )
    return result, buffer.getvalue()


def _level_key(commission: float, slippage: float) -> tuple:
    """Return the (commission, slippage) tuple used to key EXPECTED /
    EXPECTED_WON. COST_LEVELS and EXPECTED share the same float literals, so
    direct equality works for dict lookup."""
    return (commission, slippage)


def test_cost_sensitivity_runs_at_all_levels():
    """The runner executes at every cost level and returns a stable structure
    with costs recorded in ascending order."""
    prev_bps = -1.0
    for commission, slippage in COST_LEVELS:
        result, _ = _run(commission, slippage)
        assert isinstance(result, dict)
        assert result["signal"] == "sma_crossover"
        assert result["panel_verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert result["total_regimes_evaluated"] == 9  # 3 assets * 3 regimes
        assert result["min_regimes_won_per_asset"] == 2
        assert set(result["assets"]) == {"AAPL", "MSFT", "GOOGL"}
        cbps, sbps = _level_key(commission, slippage)
        assert cbps >= prev_bps, "cost levels are not ascending"
        prev_bps = cbps
        for label in ("AAPL", "MSFT", "GOOGL"):
            asset = result["assets"][label]
            assert asset["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
            assert asset["n_regimes_evaluated"] == 3
            assert set(asset["regimes"]) == {"bear", "bull", "sideways"}


def test_cost_sensitivity_verdict_robustly_not_supported():
    """Honest verdict: NOT SUPPORTED at every cost level, including
    frictionless. Transaction costs are not the reason the signal fails --
    even with zero trading cost each asset wins only 1 of 3 regimes
    (sideways) and loses in bull and bear. As costs rise the count of won
    regimes degrades (3 -> 3 -> 2 -> 2); this is documented degradation, not
    a profitability claim."""
    for commission, slippage in COST_LEVELS:
        result, _ = _run(commission, slippage)
        cbps, sbps = _level_key(commission, slippage)
        comm_bps, slip_bps = commission * 1e4, slippage * 1e4
        expected = EXPECTED_WON[(cbps, sbps)]
        assert result["panel_verdict"] == EXPECTED_VERDICT
        assert result["total_regimes_won"] == expected["panel"], (
            f"{comm_bps}bp/{slip_bps}bp: expected {expected['panel']} won, got "
            f"{result['total_regimes_won']}"
        )
        for label in ("AAPL", "MSFT", "GOOGL"):
            asset = result["assets"][label]
            assert asset["verdict"] == EXPECTED_VERDICT, (
                f"{label} at {comm_bps}bp/{slip_bps}bp unexpectedly SUPPORTED"
            )
            assert asset["n_regimes_won"] == expected[label], (
                f"{label} at {comm_bps}bp/{slip_bps}bp: expected {expected[label]} won, "
                f"got {asset['n_regimes_won']}"
            )
            assert asset["n_regimes_won"] < result["min_regimes_won_per_asset"]


def test_cost_sensitivity_metrics_pinned():
    """Regression guard: per-regime strategy and benchmark Sharpe ratios (net
    of costs) remain stable on the committed fixtures at every cost level.
    Relative tolerance only, never exact equality. Measured values, not
    profitability claims."""
    for commission, slippage in COST_LEVELS:
        result, _ = _run(commission, slippage)
        cbps, sbps = _level_key(commission, slippage)
        comm_bps, slip_bps = commission * 1e4, slippage * 1e4
        level = EXPECTED[(cbps, sbps)]
        for label in ("AAPL", "MSFT", "GOOGL"):
            asset = result["assets"][label]
            for regime, exp in level[label].items():
                detail = asset["regimes"][regime]
                got_s = detail["strategy"]["sharpe_ratio"]
                got_b = detail["benchmark"]["sharpe_ratio"]
                assert abs(got_s - exp["strategy_sharpe"]) <= REL_TOL * max(
                    abs(exp["strategy_sharpe"]), 1e-9
                ), (
                    f"{label} {regime} at {comm_bps}bp/{slip_bps}bp strategy "
                    f"Sharpe regression: got {got_s}, expected "
                    f"{exp['strategy_sharpe']}"
                )
                assert abs(got_b - exp["benchmark_sharpe"]) <= REL_TOL * max(
                    abs(exp["benchmark_sharpe"]), 1e-9
                ), (
                    f"{label} {regime} at {comm_bps}bp/{slip_bps}bp benchmark "
                    f"Sharpe regression: got {got_b}, expected "
                    f"{exp['benchmark_sharpe']}"
                )


def test_cost_sensitivity_frictionless_rules_out_cost_excuse():
    """At zero trading cost the verdict is still NOT SUPPORTED with 3 regimes
    won total (1 per asset). If costs were the cause, the frictionless run
    would flip to SUPPORTED; it does not. The signal genuinely underperforms
    buy-and-hold on risk-adjusted returns in bull and bear regimes even with
    no transaction costs, so costs cannot explain the failure."""
    result, _ = _run(0.0, 0.0)
    assert result["panel_verdict"] == EXPECTED_VERDICT
    assert result["total_regimes_won"] == EXPECTED_WON[(0.0, 0.0)]["panel"]
    for label in ("AAPL", "MSFT", "GOOGL"):
        asset = result["assets"][label]
        assert asset["verdict"] == EXPECTED_VERDICT
        assert asset["n_regimes_won"] == EXPECTED_WON[(0.0, 0.0)][label]


if __name__ == "__main__":
    test_cost_sensitivity_runs_at_all_levels()
    test_cost_sensitivity_verdict_robustly_not_supported()
    test_cost_sensitivity_metrics_pinned()
    test_cost_sensitivity_frictionless_rules_out_cost_excuse()
    print("OK")
