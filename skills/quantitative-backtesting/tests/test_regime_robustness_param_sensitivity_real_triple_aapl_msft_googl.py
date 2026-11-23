#!/usr/bin/env python3
"""Parameter-sensitivity (data-mining control) for the regime-robustness SMA
crossover on the committed triple panel (AAPL+MSFT+GOOGL).

Runs `run_regime_robustness_triple_panel` across a small grid of nearby SMA
fast/slow periods at advertised costs (2 bp commission / 1 bp slippage):

    (10, 40), (10, 50), (10, 60), (20, 50) [pre-registered], (20, 60), (30, 60)

METHODOLOGICAL PURPOSE (committed fixtures only, not evidence about any market):
The advertised-level result (fast=20/slow=50) is already pinned NOT SUPPORTED
by test_regime_robustness_sma_crossover_real_triple_aapl_msft_googl.py: each
asset wins only 1 of 3 regimes (sideways) and loses in bull and bear. This
test strengthens that falsification as a data-mining control: if NOT
SUPPORTED held only at exactly fast=20/slow=50, the result would be an
artifact of parameter choice; if it holds across a small grid, the
falsification is stronger.

MEASURED FINDING (pinned below, real measured values -- not invented):

    * Panel verdict is NOT SUPPORTED at all six combos (panel requires all
      three assets to be SUPPORTED). The panel-level falsification is robust
      across the grid.
    * At the asset level the verdict is NOT parameter-invariant: GOOGL flips
      to SUPPORTED at fast=30/slow=60, winning 2 of 3 regimes (bear and
      sideways). This is genuine parameter-specific support, reported here
      rather than suppressed or tuned away. It does not make the panel
      SUPPORTED because AAPL and MSFT remain NOT SUPPORTED at every combo.

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

# Grid of (fast_period, slow_period), fast < slow, advertised costs
# (2 bp commission + 1 bp slippage). (20, 50) is the pre-registered combo.
GRID = [
    (10, 40),
    (10, 50),
    (10, 60),
    (20, 50),
    (20, 60),
    (30, 60),
]

# Per-combo measured results: total won, per-asset verdict and won count.
# fast=30/slow=60 is the one exception: GOOGL is SUPPORTED (won 2 of 3),
# all other asset/combo verdicts are NOT SUPPORTED.
EXPECTED_SUMMARY = {
    (10, 40): {"panel": "NOT SUPPORTED", "total_won": 1,
               "AAPL": ("NOT SUPPORTED", 1), "MSFT": ("NOT SUPPORTED", 0), "GOOGL": ("NOT SUPPORTED", 0)},
    (10, 50): {"panel": "NOT SUPPORTED", "total_won": 1,
               "AAPL": ("NOT SUPPORTED", 1), "MSFT": ("NOT SUPPORTED", 0), "GOOGL": ("NOT SUPPORTED", 0)},
    (10, 60): {"panel": "NOT SUPPORTED", "total_won": 2,
               "AAPL": ("NOT SUPPORTED", 1), "MSFT": ("NOT SUPPORTED", 0), "GOOGL": ("NOT SUPPORTED", 1)},
    (20, 50): {"panel": "NOT SUPPORTED", "total_won": 3,
               "AAPL": ("NOT SUPPORTED", 1), "MSFT": ("NOT SUPPORTED", 1), "GOOGL": ("NOT SUPPORTED", 1)},
    (20, 60): {"panel": "NOT SUPPORTED", "total_won": 1,
               "AAPL": ("NOT SUPPORTED", 1), "MSFT": ("NOT SUPPORTED", 0), "GOOGL": ("NOT SUPPORTED", 0)},
    (30, 60): {"panel": "NOT SUPPORTED", "total_won": 3,
               "AAPL": ("NOT SUPPORTED", 1), "MSFT": ("NOT SUPPORTED", 0), "GOOGL": ("SUPPORTED", 2)},
}

# Per-combo per-asset per-regime measured strategy + benchmark Sharpe ratios
# at advertised costs. Benchmark Sharpe is parameter-invariant (buy-and-hold
# raw returns); strategy Sharpe varies with the grid. Regression guard only.
EXPECTED = {
    (10, 40): {
        "AAPL": {
            "bear": {"strategy_sharpe": 0.5754049939353956, "benchmark_sharpe": 1.451629801394141},
            "bull": {"strategy_sharpe": -0.21660175771294957, "benchmark_sharpe": 0.4534496163975293},
            "sideways": {"strategy_sharpe": 4.20779980564028, "benchmark_sharpe": 0.10278059166467346},
        },
        "MSFT": {
            "bear": {"strategy_sharpe": -0.38527177049315264, "benchmark_sharpe": -0.0048539210571094706},
            "bull": {"strategy_sharpe": 0.4698019896197359, "benchmark_sharpe": 1.0539297073529},
            "sideways": {"strategy_sharpe": -1.137463975588473, "benchmark_sharpe": 0.5927710661803279},
        },
        "GOOGL": {
            "bear": {"strategy_sharpe": -0.6314304040796399, "benchmark_sharpe": -0.13438963976919285},
            "bull": {"strategy_sharpe": 1.3099080278236614, "benchmark_sharpe": 1.5549832709110525},
            "sideways": {"strategy_sharpe": 1.6171279520298147, "benchmark_sharpe": 1.801497876702869},
        },
    },
    (10, 50): {
        "AAPL": {
            "bear": {"strategy_sharpe": 0.8548575797451686, "benchmark_sharpe": 1.451629801394141},
            "bull": {"strategy_sharpe": -0.011814892075320544, "benchmark_sharpe": 0.4534496163975293},
            "sideways": {"strategy_sharpe": 4.524099854800899, "benchmark_sharpe": 0.10278059166467346},
        },
        "MSFT": {
            "bear": {"strategy_sharpe": -0.44273787262632075, "benchmark_sharpe": -0.0048539210571094706},
            "bull": {"strategy_sharpe": 0.6106931490449337, "benchmark_sharpe": 1.0539297073529},
            "sideways": {"strategy_sharpe": -0.5245951994323601, "benchmark_sharpe": 0.5927710661803279},
        },
        "GOOGL": {
            "bear": {"strategy_sharpe": -0.5182810860392284, "benchmark_sharpe": -0.13438963976919285},
            "bull": {"strategy_sharpe": 1.4337529330662744, "benchmark_sharpe": 1.5549832709110525},
            "sideways": {"strategy_sharpe": 1.6171279520298147, "benchmark_sharpe": 1.801497876702869},
        },
    },
    (10, 60): {
        "AAPL": {
            "bear": {"strategy_sharpe": 0.846379077978754, "benchmark_sharpe": 1.451629801394141},
            "bull": {"strategy_sharpe": -0.054802618467108266, "benchmark_sharpe": 0.4534496163975293},
            "sideways": {"strategy_sharpe": 3.1936964471547933, "benchmark_sharpe": 0.10278059166467346},
        },
        "MSFT": {
            "bear": {"strategy_sharpe": -0.56773465060694, "benchmark_sharpe": -0.0048539210571094706},
            "bull": {"strategy_sharpe": 1.0431610201607353, "benchmark_sharpe": 1.0539297073529},
            "sideways": {"strategy_sharpe": -0.7838422758005588, "benchmark_sharpe": 0.5927710661803279},
        },
        "GOOGL": {
            "bear": {"strategy_sharpe": -0.4769397631890313, "benchmark_sharpe": -0.13438963976919285},
            "bull": {"strategy_sharpe": 1.7548792129769395, "benchmark_sharpe": 1.5549832709110525},
            "sideways": {"strategy_sharpe": 1.794039876181889, "benchmark_sharpe": 1.801497876702869},
        },
    },
    (20, 50): {
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
    (20, 60): {
        "AAPL": {
            "bear": {"strategy_sharpe": 0.3811450002021943, "benchmark_sharpe": 1.451629801394141},
            "bull": {"strategy_sharpe": 0.3874803824615983, "benchmark_sharpe": 0.4534496163975293},
            "sideways": {"strategy_sharpe": 2.922775828058839, "benchmark_sharpe": 0.10278059166467346},
        },
        "MSFT": {
            "bear": {"strategy_sharpe": -0.9616055379214878, "benchmark_sharpe": -0.0048539210571094706},
            "bull": {"strategy_sharpe": 0.8017563518125146, "benchmark_sharpe": 1.0539297073529},
            "sideways": {"strategy_sharpe": -0.5120144454551805, "benchmark_sharpe": 0.5927710661803279},
        },
        "GOOGL": {
            "bear": {"strategy_sharpe": -0.6890971467320687, "benchmark_sharpe": -0.13438963976919285},
            "bull": {"strategy_sharpe": 1.4252564005624997, "benchmark_sharpe": 1.5549832709110525},
            "sideways": {"strategy_sharpe": 1.4414904484775506, "benchmark_sharpe": 1.801497876702869},
        },
    },
    (30, 60): {
        "AAPL": {
            "bear": {"strategy_sharpe": 0.45308618644059456, "benchmark_sharpe": 1.451629801394141},
            "bull": {"strategy_sharpe": 0.18410881203368848, "benchmark_sharpe": 0.4534496163975293},
            "sideways": {"strategy_sharpe": 1.8460292565787015, "benchmark_sharpe": 0.10278059166467346},
        },
        "MSFT": {
            "bear": {"strategy_sharpe": -0.6915510566652895, "benchmark_sharpe": -0.0048539210571094706},
            "bull": {"strategy_sharpe": 1.006701429872023, "benchmark_sharpe": 1.0539297073529},
            "sideways": {"strategy_sharpe": 0.5208078143907762, "benchmark_sharpe": 0.5927710661803279},
        },
        "GOOGL": {
            "bear": {"strategy_sharpe": -0.031051969156127228, "benchmark_sharpe": -0.13438963976919285},
            "bull": {"strategy_sharpe": 1.3250790981146738, "benchmark_sharpe": 1.5549832709110525},
            "sideways": {"strategy_sharpe": 2.404607711569266, "benchmark_sharpe": 1.801497876702869},
        },
    },
}


def _run(fast_period: int, slow_period: int):
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "MSFT.csv").exists()
    assert (SRC / "GOOGL.csv").exists()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_regime_robustness_triple_panel(
            data_dir=SRC,
            fast_period=fast_period,
            slow_period=slow_period,
        )
    return result, buffer.getvalue()


def test_param_sensitivity_runs_on_grid():
    """The runner executes at every grid combo and returns a stable structure
    with the advertised-costs config recorded."""
    for fast_period, slow_period in GRID:
        result, _ = _run(fast_period, slow_period)
        assert isinstance(result, dict)
        assert result["signal"] == "sma_crossover"
        assert result["panel_verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert result["total_regimes_evaluated"] == 9  # 3 assets * 3 regimes
        assert result["min_regimes_won_per_asset"] == 2
        assert set(result["assets"]) == {"AAPL", "MSFT", "GOOGL"}
        assert result["config"]["fast_period"] == fast_period
        assert result["config"]["slow_period"] == slow_period
        assert result["config"]["commission"] == 0.0002
        assert result["config"]["slippage"] == 0.0001
        for label in ("AAPL", "MSFT", "GOOGL"):
            asset = result["assets"][label]
            assert asset["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
            assert asset["n_regimes_evaluated"] == 3
            assert set(asset["regimes"]) == {"bear", "bull", "sideways"}


def test_param_sensitivity_panel_verdict_robustly_not_supported():
    """Panel-level falsification holds across the whole grid: NOT SUPPORTED
    at all six nearby fast/slow combos, not just at the pre-registered
    (20, 50). The panel is SUPPORTED only when all three assets are
    SUPPORTED, which never occurs on this grid."""
    for fast_period, slow_period in GRID:
        result, _ = _run(fast_period, slow_period)
        assert result["panel_verdict"] == "NOT SUPPORTED", (
            f"fast={fast_period} slow={slow_period}: panel unexpectedly SUPPORTED"
        )
        expected = EXPECTED_SUMMARY[(fast_period, slow_period)]
        assert result["total_regimes_won"] == expected["total_won"], (
            f"fast={fast_period} slow={slow_period}: expected {expected['total_won']} won, "
            f"got {result['total_regimes_won']}"
        )


def test_param_sensitivity_per_asset_verdict_pinned():
    """Per-asset verdicts pinned to measured values. Notably GOOGL flips to
    SUPPORTED at fast=30/slow=60 (wins bear + sideways): genuine
    parameter-specific support, reported honestly rather than suppressed.
    The panel remains NOT SUPPORTED because AAPL and MSFT stay NOT
    SUPPORTED at every combo."""
    for fast_period, slow_period in GRID:
        result, _ = _run(fast_period, slow_period)
        expected = EXPECTED_SUMMARY[(fast_period, slow_period)]
        for label in ("AAPL", "MSFT", "GOOGL"):
            asset = result["assets"][label]
            exp_verdict, exp_won = expected[label]
            assert asset["verdict"] == exp_verdict, (
                f"{label} at fast={fast_period} slow={slow_period}: expected "
                f"{exp_verdict}, got {asset['verdict']}"
            )
            assert asset["n_regimes_won"] == exp_won, (
                f"{label} at fast={fast_period} slow={slow_period}: expected "
                f"{exp_won} won, got {asset['n_regimes_won']}"
            )


def test_param_sensitivity_metrics_pinned():
    """Regression guard: per-regime strategy and benchmark Sharpe ratios
    (net of advertised costs) remain stable on the committed fixtures at
    every grid combo. Relative tolerance only, never exact equality. Measured
    values, not profitability claims."""
    for fast_period, slow_period in GRID:
        result, _ = _run(fast_period, slow_period)
        level = EXPECTED[(fast_period, slow_period)]
        for label in ("AAPL", "MSFT", "GOOGL"):
            asset = result["assets"][label]
            for regime, exp in level[label].items():
                detail = asset["regimes"][regime]
                got_s = detail["strategy"]["sharpe_ratio"]
                got_b = detail["benchmark"]["sharpe_ratio"]
                assert abs(got_s - exp["strategy_sharpe"]) <= REL_TOL * max(
                    abs(exp["strategy_sharpe"]), 1e-9
                ), (
                    f"{label} {regime} fast={fast_period} slow={slow_period} "
                    f"strategy Sharpe regression: got {got_s}, expected "
                    f"{exp['strategy_sharpe']}"
                )
                assert abs(got_b - exp["benchmark_sharpe"]) <= REL_TOL * max(
                    abs(exp["benchmark_sharpe"]), 1e-9
                ), (
                    f"{label} {regime} fast={fast_period} slow={slow_period} "
                    f"benchmark Sharpe regression: got {got_b}, expected "
                    f"{exp['benchmark_sharpe']}"
                )


def test_param_sensitivity_benchmark_parameter_invariant():
    """Benchmark Sharpe (buy-and-hold raw returns) must not vary with the SMA
    grid since the benchmark carries no trading signal or cost. Any drift
    here would indicate a bug in regime alignment rather than a signal
    effect."""
    benchmarks = {}
    for fast_period, slow_period in GRID:
        result, _ = _run(fast_period, slow_period)
        for label in ("AAPL", "MSFT", "GOOGL"):
            for regime in ("bear", "bull", "sideways"):
                key = (label, regime)
                got = result["assets"][label]["regimes"][regime]["benchmark"]["sharpe_ratio"]
                if key in benchmarks:
                    assert abs(got - benchmarks[key]) <= REL_TOL * max(
                        abs(benchmarks[key]), 1e-9
                    ), (
                        f"{key} benchmark Sharpe drifted across the grid: "
                        f"{benchmarks[key]} vs {got} at fast={fast_period} "
                        f"slow={slow_period}"
                    )
                else:
                    benchmarks[key] = got


if __name__ == "__main__":
    test_param_sensitivity_runs_on_grid()
    test_param_sensitivity_panel_verdict_robustly_not_supported()
    test_param_sensitivity_per_asset_verdict_pinned()
    test_param_sensitivity_metrics_pinned()
    test_param_sensitivity_benchmark_parameter_invariant()
    print("OK")
