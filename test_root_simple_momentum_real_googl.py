#!/usr/bin/env python3
"""
Real-data regression guard for the root-level simple_momentum_hypothesis.py on
the committed GOOGL fixture (2020-2025).

Complements test_root_scripts_pit_bias_controls.py, which guards the same
script on the bundled SYNTHETIC control (sample_ohlcv.csv / sample_benchmark.csv),
and test_root_simple_momentum_real_aapl.py / test_root_simple_momentum_real_msft.py.
This file exercises the root script's advertised methodology controls on the
committed real-market GOOGL fixture so a silent change to the root script's
backtest wiring, cost model, capacity path or test-resolution block is caught on
real data rather than only on a synthetic series.

Mirrors test_root_simple_momentum_real_aapl.py: imports the root module
(`import simple_momentum_hypothesis as smh`), runs smh.run_hypothesis_test on
the committed GOOGL.csv fixture, pins metrics with relative tolerance 1e-3
(never exact equality), and does NOT assert the verdict (SUPPORTED and NOT
SUPPORTED are both valid scientific outcomes -- GOOGL returns SUPPORTED here,
which is a falsification outcome on this fixture, not a profitability claim
about any market).

Offline, committed fixtures only; no live network.
"""
import sys
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
    / "GOOGL.csv"
)

REL_TOL = 1e-3


def test_root_simple_momentum_runs_on_real_googl_window():
    """The root script's run_hypothesis_test must run end-to-end on the
    committed GOOGL fixture and return the pre-registered methodology controls."""
    assert DATA.exists(), f"missing committed fixture {DATA}"

    result = smh.run_hypothesis_test(DATA)

    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert isinstance(result["all_pass"], bool)
    assert result["all_pass"] == (result["verdict"] == "SUPPORTED")

    criteria = result["criteria"]
    assert len(criteria) == len(smh.CRITERIA)
    for c in criteria:
        assert isinstance(c["passed"], bool)
        assert c["description"]

    metrics = result["metrics"]
    assert metrics["sharpe_ratio"] is not None
    assert metrics["total_return"] is not None

    # Multiple-benchmark control must be live (self-benchmark + fallback).
    da = metrics["deflated_alpha"]
    assert isinstance(da, dict)
    assert da.get("n_benchmarks", 0) >= 2

    # Capacity path must produce a finite estimate at the advertised level
    # that exceeds the deployed capital.
    cap = metrics["capacity"]
    assert cap is not None
    assert float(cap) > smh.CAPACITY_INITIAL_CAPITAL

    # Test-resolution block must be reported beside the criteria.
    tr = metrics["test_resolution"]
    assert isinstance(tr, dict)
    assert tr.get("n_test_observations") and tr["n_test_observations"] > 0
    assert tr.get("alpha_status") in ("resolvable", "not_applicable", "not_resolvable")
    assert "min_detectable_alpha" in tr
    assert "alpha_beyond_plausible_bound" in tr
    assert "plausible_max_annualized_alpha" in tr


def test_root_simple_momentum_metrics_pinned_on_real_googl_window():
    """Regression guard: the root script's run on committed GOOGL must reproduce
    the pinned out-of-sample vs-benchmark metrics (net of costs) so a silent
    change to the root backtest wiring is caught. Relative tolerance only,
    never exact equality.

    The verdict is deliberately NOT asserted here: SUPPORTED and NOT SUPPORTED
    are both valid falsification outcomes.
    """
    assert DATA.exists(), f"missing committed fixture {DATA}"

    result = smh.run_hypothesis_test(DATA)
    metrics = result["metrics"]

    EXPECTED = {
        "sharpe_ratio": 0.5143360018077565,
        "total_return": 0.2072115709436657,
        "benchmark_total_return": 0.2714240402506196,
        "alpha": 0.040455858408182485,
        "capacity": 457242.34985400003,
    }
    for key, exp in EXPECTED.items():
        assert key in metrics, f"missing metric {key}"
        got = metrics[key]
        assert got is not None, f"metric {key} is None"
        assert abs(float(got) - exp) <= REL_TOL * max(abs(exp), 1e-9), (
            f"{key} regression: got {got}, expected {exp}"
        )

    # Deflated Alpha Ratio (multiple-benchmark correction) pinned too.
    da = metrics["deflated_alpha"]
    assert da.get("n_benchmarks") == 2
    assert abs(float(da["deflated_alpha_ratio"]) - 0.5462152222600346) <= REL_TOL
    assert abs(float(da["p_value"]) - 0.4537847777399654) <= REL_TOL

    # Test resolution pinned.
    tr = metrics["test_resolution"]
    assert tr.get("alpha_status") == "resolvable"
    assert abs(float(tr["min_detectable_alpha"]) - 0.18302207776218415) <= REL_TOL
    assert tr.get("alpha_beyond_plausible_bound") is True
    assert tr.get("plausible_max_annualized_alpha") == 0.1
    assert tr.get("n_test_observations") == 502
    assert tr.get("n_benchmarks") == 2


TEST_REGISTRY = [
    ("test_root_simple_momentum_runs_on_real_googl_window",
     test_root_simple_momentum_runs_on_real_googl_window),
    ("test_root_simple_momentum_metrics_pinned_on_real_googl_window",
     test_root_simple_momentum_metrics_pinned_on_real_googl_window),
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
