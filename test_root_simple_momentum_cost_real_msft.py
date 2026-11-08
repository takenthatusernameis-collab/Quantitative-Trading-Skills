#!/usr/bin/env python3
"""
Real-data regression guard for the root-level simple_momentum_hypothesis.py cost
path on the committed MSFT fixture (2010-2019).

Complements test_root_scripts_pit_bias_controls.py, which guards the same
cost path on the bundled SYNTHETIC control (sample_ohlcv.csv /
sample_benchmark.csv), and test_root_simple_momentum_real_msft.py, which guards
the headline run_hypothesis_test on MSFT. This file exercises the root script's
advertised-cost application on the committed real-market MSFT fixture, so a
silent change to the root backtest wiring or cost model is caught on real data
rather than only on a synthetic series.

Mirrors test_root_scripts_pit_bias_controls.py::test_advertised_costs_are_actually_applied:
imports the root module (`import simple_momentum_hypothesis as smh`), runs
smh._run_backtest_metrics at the advertised cost setting and at the frictionless
(0 bps) upper bound, and asserts the costed run is strictly below the
frictionless run on net Sharpe and total return -- the regression guard that
catches a cost model that silently no-ops. Metrics are pinned with relative
tolerance 1e-3 (never exact equality).

Offline, committed fixtures only; no live network.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import simple_momentum_hypothesis as smh  # noqa: E402

DATA = (
    ROOT
    / "skills"
    / "quantitative-backtesting"
    / "assets"
    / "example_data"
    / "real_market_data"
    / "MSFT.csv"
)
BENCH = (
    ROOT
    / "skills"
    / "quantitative-backtesting"
    / "assets"
    / "example_data"
    / "real_market_data"
    / "sample_benchmark.csv"
)

IMPACT = smh.CAPACITY_SWEEP_SETTINGS[-1][1]  # advertised impact_coefficient
REL_TOL = 1e-3


def test_root_cost_path_applies_advertised_costs_on_real_msft():
    """At the advertised cost setting the net out-of-sample Sharpe and total
    return must be strictly below the frictionless (0 bps) upper bound on the
    committed MSFT fixture. If the cost model silently no-ops, the two runs are
    identical and this assertion fails.
    """
    assert DATA.exists(), f"missing committed fixture {DATA}"
    assert BENCH.exists(), f"missing committed benchmark {BENCH}"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        frictionless = smh._run_backtest_metrics(
            DATA, BENCH, 0.0, 0.0, tmpdir_path, impact_coefficient=IMPACT
        )
        costed = smh._run_backtest_metrics(
            DATA, BENCH, smh.COMMISSION, smh.SLIPPAGE,
            tmpdir_path, impact_coefficient=IMPACT,
        )

    fs = frictionless.get("sharpe_ratio")
    cs = costed.get("sharpe_ratio")
    assert fs is not None and cs is not None
    assert cs < fs, (
        f"costed Sharpe {cs} must be below frictionless {fs}: costs not applied"
    )

    fr = frictionless.get("total_return")
    cr = costed.get("total_return")
    assert fr is not None and cr is not None
    assert cr < fr, (
        f"costed return {cr} must be below frictionless {fr}: costs not applied"
    )

    # Capacity is impact-driven, not cost-driven, so it must be identical at
    # both cost settings -- a silent cost model would not touch it either.
    fcap = frictionless.get("capacity")
    ccap = costed.get("capacity")
    assert fcap is not None and ccap is not None
    assert abs(float(ccap) - float(fcap)) <= REL_TOL * max(abs(float(fcap)), 1e-9)


def test_root_cost_path_metrics_pinned_on_real_msft_window():
    """Regression guard: the root script's cost-path runs on committed MSFT
    must reproduce the pinned frictionless vs advertised metrics. Relative
    tolerance only, never exact equality.
    """
    assert DATA.exists(), f"missing committed fixture {DATA}"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        frictionless = smh._run_backtest_metrics(
            DATA, BENCH, 0.0, 0.0, tmpdir_path, impact_coefficient=IMPACT
        )
        costed = smh._run_backtest_metrics(
            DATA, BENCH, smh.COMMISSION, smh.SLIPPAGE,
            tmpdir_path, impact_coefficient=IMPACT,
        )

    EXPECTED_FRICTIONLESS = {
        "sharpe_ratio": 0.7018377614484158,
        "total_return": 0.2873355632467691,
        "capacity": 16454953.518723998,
    }
    EXPECTED_COSTED = {
        "sharpe_ratio": 0.6853465301869522,
        "total_return": 0.28002040656752203,
        "capacity": 16454953.518723998,
    }
    for key, exp in EXPECTED_FRICTIONLESS.items():
        got = frictionless.get(key)
        assert got is not None, f"frictionless metric {key} is None"
        assert abs(float(got) - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"frictionless {key} regression: got {got}, expected {exp}"
        )
    for key, exp in EXPECTED_COSTED.items():
        got = costed.get(key)
        assert got is not None, f"costed metric {key} is None"
        assert abs(float(got) - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"costed {key} regression: got {got}, expected {exp}"
        )


TEST_REGISTRY = [
    ("test_root_cost_path_applies_advertised_costs_on_real_msft",
     test_root_cost_path_applies_advertised_costs_on_real_msft),
    ("test_root_cost_path_metrics_pinned_on_real_msft_window",
     test_root_cost_path_metrics_pinned_on_real_msft_window),
]


def main() -> int:
    failures = 0
    for name, fn in TEST_REGISTRY:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            import traceback
            traceback.print_exc()
    print(f"\n{len(TEST_REGISTRY) - failures}/{len(TEST_REGISTRY)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())