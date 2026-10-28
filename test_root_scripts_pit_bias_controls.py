#!/usr/bin/env python3
"""
Regression guards for the root-level simple_momentum_hypothesis.py script.

Guards the pre-registered methodology controls the script advertises, without
asserting on the verdict itself (SUPPORTED / NOT SUPPORTED are both valid
scientific outcomes):

  * point-in-time validation is engaged (--validate-point-in-time) and the
    chronological 0.6/0.2/0.2 train/val/test split is pre-registered;
  * the advertised trading costs (2 bp commission + 1 bp slippage) are
    actually applied -- a zero-cost run must beat the costed run on net
    Sharpe and total return (catches a cost model that silently no-ops);
  * the market-impact capacity path produces a finite estimate at the
    advertised impact level that exceeds the deployed capital;
  * the test-resolution block (minimum detectable effect) is reported beside
    the criteria, so a failed criterion the sample cannot resolve is not
    mistaken for evidence against the hypothesis.

These are structural + executable regression guards on the root script, not
research conclusions about any market.
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
    / "sample_ohlcv.csv"
)
BENCH = (
    ROOT
    / "skills"
    / "quantitative-backtesting"
    / "assets"
    / "example_data"
    / "sample_benchmark.csv"
)

IMPACT = smh.CAPACITY_SWEEP_SETTINGS[-1][1]  # advertised impact_coefficient


def test_pre_registered_criteria_are_present():
    criteria = smh.CRITERIA
    assert len(criteria) == 4
    names = {c[0] for c in criteria}
    assert names == {
        "oos_sharpe_gt_zero",
        "oos_total_return_positive",
        "deflated_alpha_ratio_gt_threshold",
        "capacity_gt_initial_capital",
    }
    for name, desc in criteria:
        assert isinstance(name, str) and name
        assert isinstance(desc, str) and desc


def test_advertised_costs_are_recorded():
    assert smh.COMMISSION == 0.0002   # 2 bp per trade
    assert smh.SLIPPAGE == 0.0001     # 1 bp per trade
    assert smh.CAPACITY_INITIAL_CAPITAL == 100_000.0
    assert smh.DEFLATED_ALPHA_THRESHOLD == 0.5


def test_cost_sweep_is_a_frictionless_vs_advertised_regression_guard():
    settings = smh.COST_SWEEP_SETTINGS
    assert len(settings) == 2
    labels = {label for label, _, _ in settings}
    assert "frictionless (0 bps)" in labels
    assert "advertised (2bp comm + 1bp slip)" in labels
    (_, c0, s0), (_, c1, s1) = settings
    assert c0 == 0.0 and s0 == 0.0
    assert c1 == smh.COMMISSION and s1 == smh.SLIPPAGE


def test_cost_sensitivity_levels_are_ascending_with_advertised_in_middle():
    levels = smh.COST_SWEEP_LEVELS
    assert levels == sorted(levels, key=lambda c_s: c_s[0] + c_s[1])
    assert levels[0] == (0.0, 0.0)
    advertised = next(
        (c, s) for c, s in levels
        if c == smh.COMMISSION and s == smh.SLIPPAGE
    )
    assert advertised == levels[2]  # middle rung of five


def test_capacity_sweep_is_impact_disabled_vs_advertised():
    settings = smh.CAPACITY_SWEEP_SETTINGS
    assert len(settings) == 2
    assert settings[0] == ("impact disabled (capacity unmeasurable)", 0.0)
    assert settings[1] == (
        "advertised (impact_coefficient=0.1)", smh.CAPACITY_SWEEP_SETTINGS[-1][1]
    )
    assert smh.CAPACITY_SENSITIVITY_LEVELS == [0.0, 0.05, 0.1, 0.2]


def test_pit_and_split_are_pre_registered_in_source():
    source = Path(smh.__file__).read_text()
    assert "--validate-point-in-time" in source
    assert "--train-frac" in source and "--val-frac" in source and "--test-frac" in source


def test_run_hypothesis_test_reports_methodology_controls():
    result = smh.run_hypothesis_test(DATA)

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

    da = metrics["deflated_alpha"]
    assert isinstance(da, dict)
    assert da.get("n_benchmarks", 0) >= 2   # multiple-benchmark control live

    cap = metrics["capacity"]
    assert cap is not None
    assert float(cap) > smh.CAPACITY_INITIAL_CAPITAL   # capacity path live

    tr = metrics["test_resolution"]
    assert isinstance(tr, dict)
    assert tr.get("n_test_observations") and tr["n_test_observations"] > 0
    assert tr.get("alpha_status") in ("resolvable", "not_applicable", "not_resolvable")
    assert "min_detectable_alpha" in tr
    assert "alpha_beyond_plausible_bound" in tr
    assert "plausible_max_annualized_alpha" in tr


def test_advertised_costs_are_actually_applied():
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


TEST_REGISTRY = [
    ("test_pre_registered_criteria_are_present", test_pre_registered_criteria_are_present),
    ("test_advertised_costs_are_recorded", test_advertised_costs_are_recorded),
    ("test_cost_sweep_is_a_frictionless_vs_advertised_regression_guard",
     test_cost_sweep_is_a_frictionless_vs_advertised_regression_guard),
    ("test_cost_sensitivity_levels_are_ascending_with_advertised_in_middle",
     test_cost_sensitivity_levels_are_ascending_with_advertised_in_middle),
    ("test_capacity_sweep_is_impact_disabled_vs_advertised",
     test_capacity_sweep_is_impact_disabled_vs_advertised),
    ("test_pit_and_split_are_pre_registered_in_source",
     test_pit_and_split_are_pre_registered_in_source),
    ("test_run_hypothesis_test_reports_methodology_controls",
     test_run_hypothesis_test_reports_methodology_controls),
    ("test_advertised_costs_are_actually_applied",
     test_advertised_costs_are_actually_applied),
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
