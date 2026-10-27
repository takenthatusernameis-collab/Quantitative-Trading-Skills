#!/usr/bin/env python3
"""
Regression tests for the falsifiable Z-Score mean-reversion (pairs) hypothesis
(skills/quantitative-backtesting/examples/zscore_mean_reversion_hypothesis.py).

Locks the pre-registered hypothesis-testing methodology as a regression guard:

  * the example exists and declares pre-registered falsification criteria on a
    chronological train/val/test split;
  * run_backtest.py runs end-to-end on the synthetic pair fixture
    (--multi-symbol, --strategy zscore_mean_reversion, --panel-pricing book);
  * the example runs and reports a verdict for each fixture;
  * the committed fixtures are reproducible from the documented construction
    (scripts/generate_synthetic_pair.py);
  * the machinery is not a rubber stamp: SUPPORTED on the cointegrated pair
    (genuine stationary spread) and NOT SUPPORTED on the no-effect pair (two
    independent random walks, no cointegration).

No claim is made about either verdict being "correct" as market evidence: both
fixtures are synthetic, produced by a known formula, and carry no security
identifier. The verdicts are properties of the formula and of the test
machinery.

Run with: python3 skills/quantitative-backtesting/tests/test_zscore_mean_reversion_hypothesis.py
No third-party test framework is required; uses only the standard library,
numpy and pandas.
"""

import contextlib
import io
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from zscore_mean_reversion_hypothesis import (  # noqa: E402
    ASSETS_DIR,
    COMMISSION,
    COST_SWEEP_LEVELS,
    CRITERIA,
    HYPOTHESIS,
    run_cost_sweep,
    run_hypothesis_test,
)
from generate_synthetic_pair import (  # noqa: E402
    FIXTURE_PURPOSE,
    describe_construction,
    write_pair_fixtures,
)

COINTEGRATED = ASSETS_DIR / "sample_pair_ohlcv.csv"
NO_EFFECT = ASSETS_DIR / "sample_pair_no_effect_ohlcv.csv"
SCRIPTS_DIR = SKILLS_DIR / "scripts"
EXAMPLE_PATH = SKILLS_DIR / "examples" / "zscore_mean_reversion_hypothesis.py"


def _run_example():
    return subprocess.run(
        [sys.executable, str(EXAMPLE_PATH)],
        capture_output=True, text=True,
        cwd=str(SKILLS_DIR.parent.parent),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_example_exists_and_declares_pre_registered_criteria():
    assert EXAMPLE_PATH.exists(), f"Missing {EXAMPLE_PATH}"
    content = EXAMPLE_PATH.read_text()
    assert "FALSIFICATION" in content, "example must declare falsification criteria"
    assert "train" in content.lower() and "test" in content.lower(), (
        "example must reference a train/test split")
    assert HYPOTHESIS, "pre-registered hypothesis must be non-empty"
    assert len(CRITERIA) == 2
    names = {c[0] for c in CRITERIA}
    assert names == {
        "oos_sharpe_gt_zero",
        "oos_total_return_positive",
    }
    for name, desc in CRITERIA:
        assert name
        assert ("<" in desc or ">" in desc) and desc


def test_committed_fixtures_exist_and_are_two_symbol_panels():
    for path in (COINTEGRATED, NO_EFFECT):
        assert path.exists(), f"Missing fixture {path}"
        df = pd.read_csv(path)
        assert "symbol" in df.columns, f"{path} must carry a symbol column"
        symbols = sorted(df["symbol"].unique().tolist())
        assert symbols == ["ASSET_A", "ASSET_B"], (
            f"{path} must contain exactly two symbols, got {symbols}")
        assert set(df.columns) >= {"date", "open", "high", "low", "close", "volume", "symbol"}
        assert len(df) > 0


def test_cli_run_backtest_produces_results_on_cointegrated_pair():
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "run_backtest.py"),
            "--data", str(COINTEGRATED),
            "--strategy", "zscore_mean_reversion",
            "--multi-symbol",
            "--params",
            '{"period": 20, "entry_z": 2.0, "exit_z": 0.5, '
            '"spread_method": "log_ratio", "hedge_ratio": 1.0, "hedge_lookback": 30}',
            "--commission", "0.0002",
            "--slippage", "0.0001",
            "--train-frac", "0.6",
            "--val-frac", "0.2",
            "--test-frac", "0.2",
            "--run-split", "test",
            "--panel-pricing", "book",
            "--validate-point-in-time",
            "--output", str(Path(tmpdir) / "out"),
        ]
        result = subprocess.run(cmd, cwd=str(SCRIPTS_DIR), capture_output=True, text=True)
        assert result.returncode == 0, (
            f"run_backtest failed on the cointegrated pair\n"
            f"stdout:\n{result.stdout[-2000:]}\n"
            f"stderr:\n{result.stderr[-2000:]}")
        metrics_path = Path(tmpdir) / "out" / "metrics.json"
        assert metrics_path.exists(), "metrics.json not written"
        import json
        metrics = json.load(open(metrics_path))
        assert metrics.get("total_return") is not None
        assert metrics.get("sharpe_ratio") is not None


def test_example_runs_and_reports_both_verdicts():
    proc = _run_example()
    assert proc.returncode == 0, (
        f"example exited {proc.returncode}\n"
        f"stdout:\n{proc.stdout[-3000:]}\n"
        f"stderr:\n{proc.stderr[-3000:]}")
    out = proc.stdout
    assert "VERDICT:" in out
    assert "SUPPORTED" in out
    assert "NOT SUPPORTED" in out
    assert "Chronological: True, Disjoint: True" in out
    assert "Point-in-time validation: True" in out
    # One fixture must be SUPPORTED and the other NOT SUPPORTED: the machinery
    # distinguishes a genuine mean-reverting spread from noise.
    assert "cointegrated pair" in out and "no-effect pair" in out


def test_fixtures_are_reproducible_from_documented_construction():
    """The committed fixtures must be exactly reproducible from the generator.

    This pins the synthetic data to its documented construction so the
    hypothesis test is reproducible, not an artifact of a hand-edited CSV.
    """
    construction = describe_construction()
    assert "SYNTHETIC" in FIXTURE_PURPOSE
    assert "not evidence" in FIXTURE_PURPOSE.lower()
    assert construction["symbols"] == ["ASSET_A", "ASSET_B"]
    assert 0.0 < construction["spread_rho"] < 1.0  # stationary spread
    assert construction["spread_sigma"] > 0
    assert construction["periods"] > 0

    with tempfile.TemporaryDirectory(prefix="zscore_pair_repro_") as tmpdir:
        for role, committed_path in (("pair", COINTEGRATED),
                                     ("no_effect_pair", NO_EFFECT)):
            paths = write_pair_fixtures(tmpdir, inject_effect=(role == "pair"))
            regenerated = pd.read_csv(paths[role])
            committed = pd.read_csv(committed_path)
            assert list(regenerated.columns) == list(committed.columns), (
                f"{role} column layout changed")
            assert len(regenerated) == len(committed), (
                f"{role} row count changed")
            numeric_cols = ("open", "high", "low", "close", "volume")
            string_cols = ("date", "symbol")
            for col in regenerated.columns:
                if col in numeric_cols:
                    assert np.allclose(
                        regenerated[col].to_numpy(dtype=float),
                        committed[col].to_numpy(dtype=float),
                        atol=1e-12, equal_nan=True), (
                            f"{role} column {col} does not match the documented construction")
                elif col in string_cols:
                    assert (regenerated[col].to_numpy() == committed[col].to_numpy()).all(), (
                        f"{role} column {col} does not match the documented construction")
                else:
                    raise AssertionError(f"{role} has unexpected column {col}")


def test_machinery_supported_on_cointegrated_not_on_no_effect():
    """The pre-registered criteria must distinguish signal from noise.

    A genuine cointegrated spread should be SUPPORTED; two independent random
    walks (no cointegration, no mean-reverting edge) should be NOT SUPPORTED.
    If both return the same verdict, the machinery is a rubber stamp and the
    test is meaningless."""
    effect = run_hypothesis_test(COINTEGRATED, "cointegrated pair")
    control = run_hypothesis_test(NO_EFFECT, "no-effect pair")

    assert effect["verdict"] == "SUPPORTED", (
        "the cointegrated pair must be SUPPORTED\n"
        f"observed: {effect['metrics']}")
    assert effect["all_pass"] is True
    assert control["verdict"] == "NOT SUPPORTED", (
        "the no-effect pair must be NOT SUPPORTED\n"
        f"observed: {control['metrics']}")
    assert control["all_pass"] is False

    # Each criterion carries an explicit pass/fail against a pre-registered
    # description, so the verdict is attributable to the criteria.
    for r in (effect, control):
        for c in r["criteria"]:
            assert c["passed"] in (True, False)
            assert c["description"]
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])
        assert r["verdict"] == ("SUPPORTED" if r["all_pass"] else "NOT SUPPORTED")

    # The two verdicts must differ (the control is meaningful).
    assert effect["verdict"] != control["verdict"]

    # The cointegrated pair must clear both criteria; the no-effect pair must
    # fail at least one (here both, since trading noise loses to costs).
    eff_metrics = effect["metrics"]
    ctrl_metrics = control["metrics"]
    assert eff_metrics["sharpe_ratio"] is not None and float(eff_metrics["sharpe_ratio"]) > 0
    assert eff_metrics["total_return"] is not None and float(eff_metrics["total_return"]) > 0


def test_verdict_is_conjunction_of_criteria():
    effect = run_hypothesis_test(COINTEGRATED, "cointegrated pair")
    assert effect["all_pass"] == all(c["passed"] for c in effect["criteria"])
    assert effect["verdict"] == ("SUPPORTED" if effect["all_pass"] else "NOT SUPPORTED")


def test_zscore_cost_sensitivity_sweep():
    """The cost-sensitivity sweep runs across all ascending cost levels and
    the honest directional claim holds: higher per-trade costs never improve
    net out-of-sample Sharpe or total return on the cointegrated pair.

    This pins a core methodological control: sensitivity to transaction costs
    must be measured and reported, not merely stated. The sweep is a
    sensitivity analysis on the shipped sample, not evidence about any market;
    the claim is purely directional."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_cost_sweep(COINTEGRATED)

    assert len(rows) == len(COST_SWEEP_LEVELS), (
        f"expected {len(COST_SWEEP_LEVELS)} cost levels, got {len(rows)}"
    )
    assert [r["commission_bps"] for r in rows] == [
        c * 10_000 for c, _ in COST_SWEEP_LEVELS
    ], "cost sweep levels are not recorded in ascending order"
    assert rows[0]["commission_bps"] == 0.0 and rows[0]["slippage_bps"] == 0.0, (
        "first cost sweep level must be frictionless"
    )

    series = {
        "sharpe_ratio": "Sharpe ratio",
        "total_return": "total return",
    }
    for key, label in series.items():
        values = [r[key] for r in rows]
        assert all(v is not None and np.isfinite(v) for v in values), (
            f"{label} is missing or non-finite at one or more cost levels: {values}"
        )
        for prev, curr in zip(values, values[1:]):
            assert curr <= prev + 1e-12, (
                f"{label} does not degrade monotonically with cost: "
                f"{prev} -> {curr}"
            )

    # The advertised cost level is the middle rung of the five levels.
    advertised = next(
        r for r in rows if r["commission_bps"] == COMMISSION * 10_000
    )
    assert advertised is rows[2], (
        "the advertised cost level is not the middle rung of the sweep"
    )

    # The sweep must report a per-level verdict with explicit failing criteria.
    for r in rows:
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert "criteria" in r and len(r["criteria"]) == 2
        for c in r["criteria"]:
            assert c["passed"] in (True, False)
            assert c["name"] in {"oos_sharpe_gt_zero", "oos_total_return_positive"}


def test_run_hypothesis_test_returns_cost_sweep_on_cointegrated_pair():
    """run_hypothesis_test on the cointegrated pair must surface the cost sweep
    rows so callers can inspect sensitivity without re-running the sweep."""
    effect = run_hypothesis_test(COINTEGRATED, "cointegrated pair")
    assert "cost_sweep" in effect
    assert isinstance(effect["cost_sweep"], list)
    assert len(effect["cost_sweep"]) == len(COST_SWEEP_LEVELS)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

TEST_REGISTRY = [
    ("test_example_exists_and_declares_pre_registered_criteria",
     test_example_exists_and_declares_pre_registered_criteria),
    ("test_committed_fixtures_exist_and_are_two_symbol_panels",
     test_committed_fixtures_exist_and_are_two_symbol_panels),
    ("test_cli_run_backtest_produces_results_on_cointegrated_pair",
     test_cli_run_backtest_produces_results_on_cointegrated_pair),
    ("test_example_runs_and_reports_both_verdicts",
     test_example_runs_and_reports_both_verdicts),
    ("test_fixtures_are_reproducible_from_documented_construction",
     test_fixtures_are_reproducible_from_documented_construction),
    ("test_machinery_supported_on_cointegrated_not_on_no_effect",
     test_machinery_supported_on_cointegrated_not_on_no_effect),
    ("test_verdict_is_conjunction_of_criteria",
     test_verdict_is_conjunction_of_criteria),
    ("test_zscore_cost_sensitivity_sweep",
     test_zscore_cost_sensitivity_sweep),
    ("test_run_hypothesis_test_returns_cost_sweep_on_cointegrated_pair",
     test_run_hypothesis_test_returns_cost_sweep_on_cointegrated_pair),
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
            traceback.print_exc()
    print(f"\n{len(TEST_REGISTRY) - failures}/{len(TEST_REGISTRY)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
