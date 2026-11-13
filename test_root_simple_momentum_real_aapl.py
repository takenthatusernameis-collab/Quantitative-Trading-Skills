#!/usr/bin/env python3
"""
Real-data regression guard for the root-level simple_momentum_hypothesis.py.

Complements test_root_scripts_pit_bias_controls.py, which guards the same
script on the bundled SYNTHETIC control (sample_ohlcv.csv / sample_benchmark.csv).
This file exercises the root script's advertised methodology controls on the
committed REAL-market fixture (AAPL, 2020-2025) so a silent change to the root
script's backtest wiring, cost model, capacity path or test-resolution block is
caught on real data rather than only on a synthetic series.

Mirrors the skill-level test_simple_momentum_benchmark_aware_real_aapl.py
convention: the strategy asset is AAPL.csv and the buy-and-hold benchmark is
AAPL.csv itself (self-benchmark), single-asset-vs-benchmark, run via the root
module's run_hypothesis_test. Metrics are pinned with relative tolerance
1e-3, never exact equality; the verdict is NOT asserted (SUPPORTED and NOT
SUPPORTED are both valid scientific outcomes -- the root script reports
SUPPORTED here, which is a falsification outcome on this fixture, not a
profitability claim about any market).

Offline, committed fixtures only; no live network.
"""
import json
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
    / "AAPL.csv"
)


def test_root_simple_momentum_runs_on_real_aapl_window():
    """The root script's run_hypothesis_test must run end-to-end on the
    committed AAPL fixture and return the pre-registered methodology controls."""
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

    # Capacity path must produce a finite estimate at the advertised level.
    cap = metrics["capacity"]
    assert cap is not None
    assert float(cap) > smh.CAPACITY_INITIAL_CAPITAL

    # Test-resolution block must be reported beside the deflated-alpha criterion.
    tr = metrics["test_resolution"]
    assert isinstance(tr, dict)
    assert tr.get("n_test_observations") and tr["n_test_observations"] > 0
    assert tr.get("alpha_status") in ("resolvable", "not_applicable", "not_resolvable")
    assert "min_detectable_alpha" in tr
    assert "alpha_beyond_plausible_bound" in tr
    assert "plausible_max_annualized_alpha" in tr


def test_root_simple_momentum_metrics_pinned_on_real_aapl_window():
    """Regression guard: the root script's run on committed AAPL must reproduce
    the pinned out-of-sample vs-benchmark metrics (net of costs) so a silent
    change to the root backtest wiring is caught. Relative tolerance only,
    never exact equality.

    The verdict is pinned as SUPPORTED to enforce "do not tune to force NOT
    SUPPORTED": any future change that silently flips this verdict fails this
    test.
    """
    assert DATA.exists(), f"missing committed fixture {DATA}"

    result = smh.run_hypothesis_test(DATA)

    # Enforce the no-tuning rule: root verdict stays SUPPORTED on this fixture.
    assert result["verdict"] == "SUPPORTED"
    assert result["all_pass"] is True

    expected_criteria = {
        "oos_sharpe_gt_zero": True,
        "oos_total_return_positive": True,
        "deflated_alpha_ratio_gt_threshold": True,
        "capacity_gt_initial_capital": True,
    }
    for c in result["criteria"]:
        name = c["name"]
        assert name in expected_criteria, f"unexpected criterion {name}"
        assert c["passed"] == expected_criteria[name], (
            f"criterion {name} flipped: got {c['passed']}, expected "
            f"{expected_criteria[name]}"
        )

    metrics = result["metrics"]
    EXPECTED = {
        "sharpe_ratio": 1.501892938128653,
        "total_return": 0.7616516108796803,
        "benchmark_total_return": 0.7742601739304709,
        "alpha": 0.15053019320246347,
        "capacity": 10155434.69296,
    }
    REL_TOL = 1e-3
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
    assert abs(float(da["deflated_alpha_ratio"]) - 0.802148439589307) <= REL_TOL
    assert abs(float(da["p_value"]) - 0.19785156041069296) <= REL_TOL

    # Test resolution pinned: the deflated-alpha criterion is resolvable here
    # (alpha_status == "resolvable") and its threshold sits beyond the
    # plausibility bound -- a statement about the sample size, not the strategy.
    tr = metrics["test_resolution"]
    assert tr.get("alpha_status") == "resolvable"
    assert abs(float(tr["min_detectable_alpha"]) - 0.2079417568779945) <= REL_TOL
    assert tr.get("alpha_beyond_plausible_bound") is True
    assert tr.get("plausible_max_annualized_alpha") == 0.1
    assert tr.get("n_test_observations") == 502


TEST_REGISTRY = [
    ("test_root_simple_momentum_runs_on_real_aapl_window",
     test_root_simple_momentum_runs_on_real_aapl_window),
    ("test_root_simple_momentum_metrics_pinned_on_real_aapl_window",
     test_root_simple_momentum_metrics_pinned_on_real_aapl_window),
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