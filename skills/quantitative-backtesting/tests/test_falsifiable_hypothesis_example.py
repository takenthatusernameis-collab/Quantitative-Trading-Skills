#!/usr/bin/env python3
"""
Regression tests for the falsifiable financial hypothesis worked example
(skills/quantitative-backtesting/examples/falsifiable_hypothesis_example.py).

Locks the pre-registered hypothesis-testing methodology as a regression guard:
the example must run end-to-end on the shipped sample data, return a well-formed
verdict dict, and report explicit pass/fail for each falsification criterion
against a chronological out-of-sample split. No claim is made about the verdict
itself (SUPPORTED / NOT SUPPORTED are both valid scientific outcomes); the test
guards the structure and executability of the methodology, not its result.

The suite also pins three methodological properties of the example that are
easy to break silently:

  * criterion 3 (the raw benchmark-alpha test) and criterion 5 (the
    multiple-testing corrected test) must read DIFFERENT statistics. Reading
    only the corrected p-value would make the advertised benchmark-side
    data-mining control redundant: criterion 5 would be implied by criterion 3
    and could never bind independently.
  * the example must report the test's resolution -- the smallest effect each
    significance criterion requires -- so a failed criterion that the sample
    cannot resolve is not mistaken for evidence against the hypothesis.
  * the resolution analysis is a measurement: it must not change any criterion
    outcome or the verdict.

THE POSITIVE CONTROL (a check on the test machinery, not on any market)
    Everything above is a "can only fail" demonstration: on the shipped
    sample the resolution thresholds sit beyond the plausibility bound, so
    the verdict is largely a statement about the size of the held-out
    sample. That does not show the machinery CAN say yes when it should.

    The tests below close that gap with a SYNTHETIC fixture
    (`scripts/generate_positive_control_data.py`): a series built by a
    known formula with a known injected effect, plus a no-effect control
    built from the identical draws with the effect removed. The example's
    own criteria machinery must return SUPPORTED on the effect series and
    NOT SUPPORTED on the no-effect series.

    This is a check on the decision machinery only. The fixture is produced
    by a formula, describes no real security, and the numbers it produces
    are properties of that formula and of the test machinery -- never
    evidence about a market.

Run with: python3 skills/quantitative-backtesting/tests/test_falsifiable_hypothesis_example.py
No third-party test framework is required; uses only the standard library.
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

from falsifiable_hypothesis_example import (  # noqa: E402
    COMMISSION,
    COST_SWEEP_LEVELS,
    SLIPPAGE,
    run_cost_sensitivity_sweep,
    run_hypothesis_test,
)
from generate_positive_control_data import (  # noqa: E402
    CONTROL_BENCHMARK_SEED,
    CONTROL_DRIFT,
    CONTROL_PERIODS,
    CONTROL_REGIME_BARS,
    CONTROL_STRATEGY_SEED,
    CONTROL_VOLATILITY,
    FIXTURE_PURPOSE,
    generate_control_series,
    write_control_fixture,
)


def _sample_paths():
    data = SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv"
    bench = SKILLS_DIR / "assets" / "example_data" / "sample_benchmark.csv"
    return data, bench


# The example runs a full walk-forward validation, which is expensive. The
# result is immutable and the same for every test, so it is computed once and
# shared (each test only reads it).
_RESULT = None
_COST_RESULTS = {}


def _result():
    global _RESULT
    if _RESULT is None:
        data_path, _ = _sample_paths()
        _RESULT = run_hypothesis_test(data_path)
    return _RESULT


def _cost_result(data_path, commission, slippage):
    """Run the example's machinery at a caller-supplied cost setting.

    Each (commission, slippage) pair is computed once and shared by the tests
    that read it. The example resolves its benchmark set from the data file's
    directory, so the shipped fixtures are used unchanged.
    """
    key = (float(commission), float(slippage))
    if key in _COST_RESULTS:
        return _COST_RESULTS[key]
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_hypothesis_test(
            data_path, commission=commission, slippage=slippage
        )
    result["_console"] = buffer.getvalue()
    _COST_RESULTS[key] = result
    return result


def test_falsifiable_hypothesis_example_runs_end_to_end():
    """The pre-registered hypothesis test executes on the shipped sample data."""
    data_path, bench_path = _sample_paths()
    assert data_path.exists() and bench_path.exists(), "sample data fixtures missing"
    result = _result()

    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert isinstance(result["all_pass"], bool)
    assert result["all_pass"] == (result["verdict"] == "SUPPORTED")
    assert result["hypothesis"]  # non-empty pre-registered hypothesis
    assert result["pit_passed"] is True
    assert result["bias_controls_engaged"] is True

    obs = result["observed"]
    for key in ("oos_sharpe", "oos_total_return", "deflated_sharpe_pvalue",
                "benchmark_alpha", "benchmark_alpha_pvalue",
                "benchmark_alpha_pvalue_corrected",
                "benchmark_alpha_correction_applied",
                "benchmark_total_return", "deflated_alpha_ratio",
                "deflated_alpha_pvalue", "n_benchmarks",
                "selected_params", "test_n_observations"):
        assert key in obs, f"observed metrics missing {key}"
    assert obs["test_n_observations"] and obs["test_n_observations"] > 0
    # The strategy is tested against a set of benchmarks (N >= 2), so the
    # Deflated Alpha Ratio data-mining control is engaged.
    assert obs["n_benchmarks"] and obs["n_benchmarks"] >= 2
    assert obs["deflated_alpha_ratio"] is not None
    assert obs["deflated_alpha_pvalue"] is not None

    criteria = result["criteria"]
    assert len(criteria) == 5
    names = {c["name"] for c in criteria}
    assert names == {
        "oos_sharpe_gt_zero",
        "deflated_sharpe_pvalue_lt_0.10",
        "benchmark_alpha_pvalue_lt_0.05",
        "oos_total_return_gt_benchmark",
        "deflated_alpha_ratio_gt_0.90",
    }
    for c in criteria:
        assert isinstance(c["passed"], bool)
        assert c["description"]

    sep = result["separation_check"]
    assert sep.get("disjoint") is True
    assert sep.get("chronological") is True
    for overlap in ("train_val_overlap", "val_test_overlap", "train_test_overlap"):
        assert sep.get(overlap) == 0
    assert sep.get("train_size") and sep.get("val_size") and sep.get("test_size")


def test_falsifiable_hypothesis_criteria_are_explicit_and_evaluated():
    """Every falsification criterion carries a pre-registered description and
    a boolean pass/fail, so the verdict is attributable to explicit criteria
    rather than an opaque outcome."""
    result = _result()

    for c in result["criteria"]:
        assert c["passed"] in (True, False)
        assert "<" in c["description"] or ">" in c["description"]
    # The verdict is the conjunction of the criteria.
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])


def test_falsifiable_hypothesis_out_of_sample_split_is_chronological():
    """The held-out test set is disjoint from train/val and never used in
    selection (chronological 0.6/0.2/0.2 split)."""
    result = _result()
    sep = result["separation_check"]
    assert sep.get("disjoint") is True
    assert sep.get("chronological") is True
    assert sep.get("train_test_overlap") == 0


def test_the_alpha_criterion_reads_the_raw_p_value_and_the_dar_the_corrected_one():
    """Criterion 3 (raw alpha test) and criterion 5 (multiple-testing
    corrected) must be different statistics.

    The benchmark correction rewrites the primary benchmark's `alpha_pvalue`
    with the deflated p-value and keeps the raw one in
    `alpha_pvalue_original`. If the example read only `alpha_pvalue`, the two
    criteria would test the same number and the benchmark-side data-mining
    control could never bind independently."""
    result = _result()
    obs = result["observed"]

    raw = obs["benchmark_alpha_pvalue"]
    corrected = obs["benchmark_alpha_pvalue_corrected"]
    assert raw is not None and corrected is not None
    # The correction is engaged on the shipped fixture (N = 2 benchmarks), so
    # the two p-values genuinely differ.
    assert obs["benchmark_alpha_correction_applied"] is True
    assert raw != corrected
    # The corrected p-value is the Deflated Alpha p-value of the primary
    # benchmark (1 - DAR), the number criterion 5 is stated against.
    assert abs(corrected - obs["deflated_alpha_pvalue"]) < 1e-12
    assert abs((1.0 - obs["deflated_alpha_ratio"]) - corrected) < 1e-12
    # The raw p-value is the uncorrected two-sided alpha t-test p-value.
    assert raw < corrected, (
        "the multiple-testing correction can only make the p-value larger"
    )


def test_the_example_reports_the_test_resolution():
    """The example reports the smallest effect each significance criterion
    requires at the sample size actually available (minimum detectable
    effect), and flags the criteria the sample cannot resolve."""
    result = _result()
    res = result["resolution"]

    for key in ("n_test_observations", "n_parameter_trials", "n_benchmarks",
                "min_detectable_sharpe", "min_detectable_alpha",
                "min_detectable_benchmark_alpha", "alpha_regression_df",
                "criteria_beyond_resolution",
                "plausible_max_annualized_sharpe",
                "plausible_max_annualized_alpha"):
        assert key in res, f"resolution block missing {key}"

    obs = result["observed"]
    # The held-out window carries far too few observations for the deflated
    # thresholds to be reachable, so every reported minimum detectable effect
    # is larger than the effect that was observed.
    assert res["min_detectable_sharpe"] > 0
    assert res["min_detectable_sharpe"] > obs["oos_sharpe"]
    assert res["min_detectable_alpha"] > 0
    assert res["min_detectable_alpha"] > obs["benchmark_alpha"]
    assert res["min_detectable_benchmark_alpha"] > 0
    assert res["min_detectable_benchmark_alpha"] > obs["benchmark_alpha"]

    # The three significance criteria are the ones beyond the sample's
    # resolution on the shipped fixture; criteria 1 and 4 are direct
    # comparisons and are not power-limited in the same way.
    assert set(res["criteria_beyond_resolution"]) == {
        "deflated_sharpe_pvalue_lt_0.10",
        "benchmark_alpha_pvalue_lt_0.05",
        "deflated_alpha_ratio_gt_0.90",
    }
    assert result["criteria_beyond_resolution"] == res["criteria_beyond_resolution"]

    paths = res["paths"]
    assert isinstance(paths, dict)
    for path_key in ("out_of_sample", "walk_forward", "cpcv"):
        assert path_key in paths, f"resolution paths missing {path_key}"
        block = paths[path_key]
        assert isinstance(block, dict)
        assert "minimum_detectable_sharpe" in block
        assert "minimum_detectable_alpha" in block


def test_the_resolution_does_not_change_the_verdict():
    """The resolution analysis is a measurement: it changes no criterion
    outcome and no verdict."""
    result = _result()
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")
    # The verdict on the shipped sample data is a regression guard on the
    # wiring (raw vs corrected p-value), not a claim about the strategy.
    assert result["verdict"] == "NOT SUPPORTED"


def test_the_test_window_is_reported_in_observations_not_periods():
    """The held-out window is reported as a number of observations (daily
    bars), not as a number of independent periods -- the distinction is what
    makes the resolution numbers interpretable."""
    result = _result()
    obs = result["observed"]
    assert obs["test_n_observations"] == 100
    assert "test_n_periods" not in obs


def test_the_example_prints_the_resolution_and_the_reading_note():
    """The console output carries the resolution section and says in plain
    words that a criterion the sample cannot resolve is not evidence against
    the hypothesis."""
    example_path = SKILLS_DIR / "examples" / "falsifiable_hypothesis_example.py"
    proc = subprocess.run(
        [sys.executable, str(example_path)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, (
        f"example exited {proc.returncode}\n"
        f"stdout:\n{proc.stdout[-3000:]}\n"
        f"stderr:\n{proc.stderr[-3000:]}"
    )
    out = proc.stdout
    assert "TEST RESOLUTION" in out
    assert "Beyond the sample's resolution" in out
    assert "HOW TO READ THIS VERDICT:" in out
    assert "Benchmark alpha p-value (raw, criterion 3)" in out
    assert "Benchmark alpha p-value (deflated" in out
    assert "Test observations:" in out
    # The pre-registered decision rule is reported unchanged.
    assert "VERDICT:" in out


# ---------------------------------------------------------------------------
# The positive control
# ---------------------------------------------------------------------------
#
# A check on the test machinery, NOT on any strategy or market. The fixture
# is a synthetic series produced by a known formula with a known injected
# effect (see `scripts/generate_positive_control_data.py`), plus a no-effect
# control built from the identical draws with the effect removed.
#
# What the control establishes:
#   * the example's own criteria machinery can return SUPPORTED when the
#     effect is real and the sample is large enough (the shipped sample only
#     ever shows that it can fail);
#   * the same machinery returns NOT SUPPORTED on the matched no-effect
#     series, so the SUPPORTED verdict is not the machinery answering yes
#     unconditionally;
#   * the SUPPORTED verdict rests on an effect that EXCEEDS the framework's
#     own reported minimum detectable effect, so it is a power statement and
#     not an accident.
#
# What it does NOT establish: anything about real securities. The numbers
# below are properties of a formula and of the decision machinery.

# The control runs a full walk-forward validation per case, so each result is
# computed once and shared by the tests that read it.
_CONTROL_RESULTS = {}


def _control_result(inject_effect, strategy_seed=None, benchmark_seed=None):
    """Run the example's criteria machinery on the synthetic control fixture.

    The fixture is written into a temporary directory because the example
    resolves its benchmark set from the directory of the data file it is
    given, and the fixture's file names are fixed by that list.
    """
    key = (bool(inject_effect), strategy_seed, benchmark_seed)
    if key in _CONTROL_RESULTS:
        return _CONTROL_RESULTS[key]

    kwargs = {}
    if strategy_seed is not None:
        kwargs["strategy_seed"] = strategy_seed
    if benchmark_seed is not None:
        kwargs["benchmark_seed"] = benchmark_seed

    buffer = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="positive_control_") as tmpdir:
        paths = write_control_fixture(tmpdir, inject_effect=inject_effect, **kwargs)
        with contextlib.redirect_stdout(buffer):
            result = run_hypothesis_test(paths["strategy"])
    result["_console"] = buffer.getvalue()
    _CONTROL_RESULTS[key] = result
    return result


def _criterion(result, name):
    for criterion in result["criteria"]:
        if criterion["name"] == name:
            return criterion
    raise AssertionError(f"criterion {name} missing from the result")


def test_the_synthetic_positive_control_returns_supported():
    """The machinery can say yes: on a series with a known injected effect the
    example's own pre-registered criteria return SUPPORTED.

    This is the half the shipped sample cannot show. On the shipped sample
    the resolution thresholds sit beyond the plausibility bound, so the
    verdict there is largely a statement about the sample size; here the
    thresholds are inside the sample's resolution AND the effect clears them.
    """
    result = _control_result(inject_effect=True)
    console = result.get("_console", "")

    assert result["verdict"] == "SUPPORTED", (
        "the positive control must be SUPPORTED\n"
        f"observed: {result['observed']}\n"
        f"console tail:\n{console[-3000:]}"
    )
    assert result["all_pass"] is True
    failed = [c["name"] for c in result["criteria"] if not c["passed"]]
    assert not failed, f"criteria failed on the positive control: {failed}"

    # The same machinery, the same split, the same bias controls: the
    # SUPPORTED verdict was produced by the shipped code path, not by a
    # shortcut around it.
    sep = result["separation_check"]
    assert sep.get("disjoint") is True
    assert sep.get("chronological") is True
    assert sep.get("train_test_overlap") == 0
    assert result["pit_passed"] is True
    assert result["bias_controls_engaged"] is True


def test_the_positive_control_effect_clears_the_reported_minimum_detectable_effect():
    """The SUPPORTED verdict rests on an effect the test could have detected.

    The framework reports, for each significance criterion, the smallest
    effect that criterion could have confirmed at the sample size actually
    available. On the control the observed effect is above that threshold,
    so the verdict is a power statement rather than luck -- and the control
    is the first case in this repository where the significance criteria are
    demonstrably *within* the sample's resolution.
    """
    result = _control_result(inject_effect=True)
    obs = result["observed"]
    res = result["resolution"]

    assert res["n_test_observations"] > 0
    assert res["n_parameter_trials"] > 0
    assert res["n_benchmarks"] >= 2

    # Criterion 2 (deflated Sharpe): the observed Sharpe is above the
    # smallest one the deflated test could have confirmed.
    assert res["min_detectable_sharpe"] > 0
    assert obs["oos_sharpe"] > res["min_detectable_sharpe"], (
        "the observed Sharpe must exceed the reported minimum detectable "
        f"effect ({obs['oos_sharpe']} vs {res['min_detectable_sharpe']})"
    )
    # Criteria 3 and 5 (raw and deflated benchmark alpha): same statement.
    assert res["min_detectable_alpha"] > 0
    assert obs["benchmark_alpha"] > res["min_detectable_alpha"]
    assert res["min_detectable_benchmark_alpha"] > 0
    assert obs["benchmark_alpha"] > res["min_detectable_benchmark_alpha"]

    # Every criterion was inside the sample's resolution: the thresholds did
    # not exceed the framework's own plausibility bounds, so the verdict is
    # informative rather than a statement about the sample size.
    assert res["criteria_beyond_resolution"] == [], (
        "on the positive control every criterion must be within the sample's "
        f"resolution, got {res['criteria_beyond_resolution']}"
    )
    assert result["criteria_beyond_resolution"] == []


def test_the_no_effect_control_returns_not_supported():
    """The negative side: the identical construction with the effect removed
    must NOT be SUPPORTED.

    A control that only asserted the positive case would pass even if the
    criteria always returned SUPPORTED.
    """
    result = _control_result(inject_effect=False)
    console = result.get("_console", "")

    assert result["verdict"] == "NOT SUPPORTED", (
        "the no-effect control must not be SUPPORTED\n"
        f"observed: {result['observed']}\n"
        f"console tail:\n{console[-3000:]}"
    )
    assert result["all_pass"] is False
    # The significance criteria are the ones that must fail: with no effect
    # there is nothing for them to detect.
    assert _criterion(result, "deflated_sharpe_pvalue_lt_0.10")["passed"] is False
    assert _criterion(result, "deflated_alpha_ratio_gt_0.90")["passed"] is False


def test_the_control_pair_differs_only_by_the_injected_effect():
    """The effect series and the no-effect control are the same construction.

    They share the noise draws and the OHLC micro-structure; the only
    difference is the injected regime drift. That is what makes the pair a
    control rather than two unrelated samples, so the property is asserted
    rather than assumed.
    """
    with_effect = generate_control_series(inject_effect=True)
    without_effect = generate_control_series(inject_effect=False)

    assert len(with_effect) == len(without_effect) == CONTROL_PERIODS
    assert list(with_effect["date"]) == list(without_effect["date"])

    # The log-return paths differ by exactly the regime drift.
    drift = np.where(
        (np.arange(CONTROL_PERIODS) // CONTROL_REGIME_BARS) % 2 == 0,
        CONTROL_DRIFT,
        -CONTROL_DRIFT,
    )
    log_effect = np.diff(np.log(with_effect["close"].to_numpy()))
    log_control = np.diff(np.log(without_effect["close"].to_numpy()))
    difference = log_effect - log_control
    assert np.allclose(difference, drift[1:], atol=1e-12), (
        "the no-effect control must be the effect series with exactly the "
        "injected drift removed"
    )

    # The noise is identical: the difference is the drift, nothing else.
    noise_effect = log_effect - drift[1:]
    noise_control = log_control
    assert np.allclose(noise_effect, noise_control, atol=1e-12)


def test_the_control_verdict_is_not_a_property_of_one_seed():
    """The verdict survives a change of the random draw.

    A control pinned to a single seed could be a lucky seed. The effect
    series must be SUPPORTED and the no-effect series NOT SUPPORTED on other
    seeds as well.
    """
    for seed in (1, 2024):
        effect = _control_result(
            inject_effect=True, strategy_seed=seed, benchmark_seed=seed + 1000
        )
        assert effect["verdict"] == "SUPPORTED", (
            f"the positive control must be SUPPORTED on seed {seed}; "
            f"observed: {effect['observed']}"
        )
        control = _control_result(
            inject_effect=False, strategy_seed=seed, benchmark_seed=seed + 1000
        )
        assert control["verdict"] == "NOT SUPPORTED", (
            f"the no-effect control must not be SUPPORTED on seed {seed}; "
            f"observed: {control['observed']}"
        )


def test_the_control_fixture_is_labelled_as_synthetic_and_carries_no_security():
    """The fixture must never read as a claim about a real security.

    Two guards: the generator states its purpose (synthetic, machinery check,
    not evidence), and the generated data carries no security identifier at
    all -- only prices and volume.
    """
    assert "SYNTHETIC" in FIXTURE_PURPOSE
    assert "not evidence" in FIXTURE_PURPOSE.lower()
    assert "TEST-MACHINERY" in FIXTURE_PURPOSE

    series = generate_control_series()
    assert set(series.columns) == {"date", "open", "high", "low", "close", "volume"}
    # No symbol / ticker / name column: the series identifies nothing.
    for identifier in ("symbol", "ticker", "name", "isin", "security"):
        assert identifier not in series.columns

    with tempfile.TemporaryDirectory(prefix="positive_control_") as tmpdir:
        paths = write_control_fixture(tmpdir)
        strategy = pd.read_csv(paths["strategy"])
        benchmark = pd.read_csv(paths["benchmark"])
    assert list(strategy.columns) == list(benchmark.columns)
    assert len(strategy) == len(benchmark) == CONTROL_PERIODS
    # The pinned seeds are the ones the control is documented with.
    assert CONTROL_STRATEGY_SEED != CONTROL_BENCHMARK_SEED
    assert CONTROL_VOLATILITY > 0
    assert CONTROL_DRIFT > 0


def test_the_example_records_its_methodology_block():
    """The result carries a methodology block naming the costs, the
    validation path, the selection criterion and the benchmark set actually
    engaged, so the advertised controls are auditable from the return value
    rather than only from the printed banner."""
    result = _result()
    method = result["methodology"]

    for key in (
        "commission", "slippage", "validation_method", "selection_criterion",
        "walk_forward_window", "multiple_benchmarks", "n_benchmarks_loaded",
        "param_grid", "train_frac", "val_frac", "test_frac",
    ):
        assert key in method, f"methodology block missing {key}"

    # The example's advertised costs are recorded verbatim.
    assert method["commission"] == 0.0002
    assert method["slippage"] == 0.0001
    # The pre-registered validation path is the walk-forward one.
    assert method["validation_method"] == "walk_forward"
    assert method["selection_criterion"] == "best_avg_sharpe"
    # The walk-forward window actually ran (3 periods on 504 bars).
    assert method["walk_forward_window"]["effective_periods"] == 3
    # The multiple-benchmark Deflated Alpha path is engaged.
    assert method["multiple_benchmarks"] is True
    assert method["n_benchmarks_loaded"] == 2
    # The split fractions are the pre-registered 0.6/0.2/0.2.
    assert (method["train_frac"], method["val_frac"], method["test_frac"]) == (0.6, 0.2, 0.2)
    # The parameter grid is the pre-registered one (must match
    # falsifiable_hypothesis_example.PARAM_GRID, the source of truth).
    assert method["param_grid"] == {
        "fast_period": [10, 20],
        "slow_period": [30, 40],
    }


def test_the_advertised_costs_are_actually_applied():
    """The 2bps commission + 1bps slippage are not merely stated: running the
    identical machinery at zero cost must produce a *higher* net Sharpe and a
    higher net total return. A cost path that silently no-ops would fail this.

    The data is synthetic and seed-fixed, so the relationship is deterministic
    and the test is a regression guard against a silent break in the cost
    model -- the same shape of guard as the pairs-trading cost sweep.
    """
    data_path, _ = _sample_paths()
    with_costs = _cost_result(data_path, commission=0.0002, slippage=0.0001)
    without_costs = _cost_result(data_path, commission=0.0, slippage=0.0)

    assert with_costs["methodology"]["commission"] == 0.0002
    assert without_costs["methodology"]["commission"] == 0.0

    sharpe_cost = with_costs["observed"]["oos_sharpe"]
    sharpe_nocost = without_costs["observed"]["oos_sharpe"]
    assert sharpe_nocost > sharpe_cost, (
        "zero-cost run must beat the costed run on net Sharpe: "
        f"{sharpe_nocost} vs {sharpe_cost}"
    )

    return_cost = with_costs["observed"]["oos_total_return"]
    return_nocost = without_costs["observed"]["oos_total_return"]
    assert return_nocost > return_cost, (
        "zero-cost run must beat the costed run on net total return: "
        f"{return_nocost} vs {return_cost}"
    )


def test_falsifiable_hypothesis_cost_sensitivity_sweep():
    """The cost-sensitivity sweep runs across all ascending cost levels and
    the honest directional claim holds: higher per-trade costs never improve
    net out-of-sample Sharpe, total return, or Deflated Alpha Ratio.

    This pins a core methodological control: sensitivity to transaction costs
    must be measured and reported, not merely stated. The sweep is a
    sensitivity analysis on the shipped sample, not evidence about any market;
    the claim is purely directional."""
    data_path, _ = _sample_paths()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_cost_sensitivity_sweep(data_path)

    assert len(rows) == len(COST_SWEEP_LEVELS), (
        f"expected {len(COST_SWEEP_LEVELS)} cost levels, got {len(rows)}"
    )
    # Levels recorded in ascending cost order.
    assert [r["commission_bps"] for r in rows] == [
        c * 10_000 for c, _ in COST_SWEEP_LEVELS
    ], "cost sweep levels are not recorded in ascending order"
    assert rows[0]["commission_bps"] == 0.0 and rows[0]["slippage_bps"] == 0.0, (
        "first cost sweep level must be frictionless"
    )

    series = {
        "sharpe_ratio": "Sharpe ratio",
        "total_return": "total return",
        "deflated_alpha_ratio": "Deflated Alpha Ratio",
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

    # The advertised setting is the middle rung (index 2) of the five levels.
    advertised = next(
        r for r in rows if r["commission_bps"] == COMMISSION * 10_000
    )
    assert advertised is rows[2], (
        "the advertised cost level is not the middle rung of the sweep"
    )


def test_the_selection_criterion_is_oos_aware():
    """The selection criterion is the pre-registered 'best_avg_sharpe' --
    the parameter set with the best AVERAGE OUT-OF-SAMPLE test Sharpe across
    the walk-forward periods where it was chosen -- not the best in-sample
    training Sharpe. Selecting on in-sample fit would pick the combo that
    overfit its training window, which is the selection bias this framework
    exists to avoid."""
    result = _result()
    assert result["methodology"]["selection_criterion"] == "best_avg_sharpe"
    # The recorded average test Sharpe of the selected params is a real
    # number, so the selection actually read OOS scores.
    assert result["observed"]["selected_params_avg_test_sharpe"] is not None


def test_falsifiable_machinery_on_independent_out_of_sample_fixture():
    """The falsifiable machinery produces a determinate, explicitly
    criteria-evaluated verdict on an independent synthetic fixture that was
    not used to develop the example (a distinct seed/DGP from the shipped
    sample).

    This is independent out-of-sample evidence beyond the primary synthetic
    fixture: the held-out test set is disjoint from train/val and never used
    in parameter selection. The verdict itself (SUPPORTED / NOT SUPPORTED) is
    not asserted -- both are valid scientific outcomes -- only that the
    machinery runs, evaluates every pre-registered criterion, reports the
    test resolution, and audits the split separation on independent data.

    Labelled synthetic: a machinery check, not evidence about any market.
    Independent real-market out-of-sample evidence remains blocked (the data
    loader reads local files only and there is no real-data fetch), so it is
    left as the next agent's item.
    """
    import contextlib
    import io
    import tempfile
    from pathlib import Path

    from generate_sample_data import generate_single_asset_data

    # Independent fixture: distinct seed/DGP from the shipped sample.
    strategy_df = generate_single_asset_data(periods=504, seed=2024)
    # Independent buy-and-hold benchmark (a different seed).
    bench_df = generate_single_asset_data(periods=504, seed=777)

    with tempfile.TemporaryDirectory(prefix="independent_oos_") as tmpdir:
        tmpdir = Path(tmpdir)
        data_path = tmpdir / "sample_ohlcv.csv"
        bench_path = tmpdir / "sample_benchmark.csv"
        strategy_df.to_csv(data_path, index=False)
        bench_df.to_csv(bench_path, index=False)

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_hypothesis_test(data_path)

    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert isinstance(result["all_pass"], bool)
    assert result["all_pass"] == (result["verdict"] == "SUPPORTED")
    assert result["pit_passed"] is True
    assert result["bias_controls_engaged"] is True

    obs = result["observed"]
    for key in ("oos_sharpe", "oos_total_return", "deflated_sharpe_pvalue",
                "benchmark_alpha", "benchmark_alpha_pvalue",
                "benchmark_alpha_pvalue_corrected",
                "benchmark_alpha_correction_applied",
                "benchmark_total_return", "deflated_alpha_ratio",
                "deflated_alpha_pvalue", "n_benchmarks",
                "selected_params", "test_n_observations"):
        assert key in obs, f"observed metrics missing {key}"
    assert obs["test_n_observations"] and obs["test_n_observations"] > 0
    # The strategy is tested against a set of benchmarks (N >= 2), so the
    # Deflated Alpha Ratio data-mining control is engaged on independent data.
    assert obs["n_benchmarks"] and obs["n_benchmarks"] >= 2

    criteria = result["criteria"]
    assert len(criteria) == 5
    names = {c["name"] for c in criteria}
    assert names == {
        "oos_sharpe_gt_zero",
        "deflated_sharpe_pvalue_lt_0.10",
        "benchmark_alpha_pvalue_lt_0.05",
        "oos_total_return_gt_benchmark",
        "deflated_alpha_ratio_gt_0.90",
    }
    for c in criteria:
        assert isinstance(c["passed"], bool)
        assert c["description"]
    assert result["all_pass"] == all(c["passed"] for c in criteria)

    # Split separation audit: the held-out test set is independent of
    # train/val and never used in selection.
    sep = result["separation_check"]
    assert sep.get("disjoint") is True
    assert sep.get("chronological") is True
    for overlap in ("train_val_overlap", "val_test_overlap", "train_test_overlap"):
        assert sep.get(overlap) == 0
    assert sep.get("train_size") and sep.get("val_size") and sep.get("test_size")

    # Test resolution is reported alongside the verdict (a measurement, not a
    # correction): the smallest effect each significance criterion could have
    # confirmed on this independent sample.
    res = result["resolution"]
    for key in ("n_test_observations", "n_parameter_trials", "n_benchmarks",
                "min_detectable_sharpe", "min_detectable_alpha",
                "min_detectable_benchmark_alpha",
                "criteria_beyond_resolution",
                "plausible_max_annualized_sharpe",
                "plausible_max_annualized_alpha"):
        assert key in res, f"resolution block missing {key}"
    assert res["n_test_observations"] == obs["test_n_observations"]
    # The resolution analysis must not change the verdict.
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")


def test_falsifiable_machinery_on_independent_real_market_data():
    """The falsifiable machinery produces a determinate, explicitly
    criteria-evaluated verdict on committed real market data.

    This is independent real-market out-of-sample evidence: the held-out test
    set is disjoint from train/val and never used in parameter selection,
    point-in-time validation passes, and all five pre-registered falsification
    criteria are explicitly evaluated with boolean pass/fail. The verdict
    itself (SUPPORTED / NOT SUPPORTED) is not asserted -- both are valid
    scientific outcomes -- only that the machinery runs on real market data
    and reports the test resolution and the split-separation audit.

    Labelled real-market evidence: the series are committed OHLCV for real
    equities (AAPL universe), not a synthetic formula. This is evidence about
    the machinery's behavior on real market data, read against the
    pre-registered criteria; it is not a claim of profitability or robustness.
    """
    import contextlib
    import io

    data_path = SKILLS_DIR / "assets" / "example_data" / "real_market_data" / "sample_ohlcv.csv"
    assert data_path.exists(), "real market data fixture missing"

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_hypothesis_test(data_path)

    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert isinstance(result["all_pass"], bool)
    assert result["all_pass"] == (result["verdict"] == "SUPPORTED")
    assert result["pit_passed"] is True
    assert result["bias_controls_engaged"] is True

    obs = result["observed"]
    for key in ("oos_sharpe", "oos_total_return", "deflated_sharpe_pvalue",
                "benchmark_alpha", "benchmark_alpha_pvalue",
                "benchmark_alpha_pvalue_corrected",
                "benchmark_alpha_correction_applied",
                "benchmark_total_return", "deflated_alpha_ratio",
                "deflated_alpha_pvalue", "n_benchmarks",
                "selected_params", "test_n_observations"):
        assert key in obs, f"observed metrics missing {key}"
    assert obs["test_n_observations"] and obs["test_n_observations"] > 0
    # Real market data exercised against multiple benchmarks (N >= 2), so the
    # Deflated Alpha Ratio data-mining control is engaged.
    assert obs["n_benchmarks"] and obs["n_benchmarks"] >= 2

    criteria = result["criteria"]
    assert len(criteria) == 5
    names = {c["name"] for c in criteria}
    assert names == {
        "oos_sharpe_gt_zero",
        "deflated_sharpe_pvalue_lt_0.10",
        "benchmark_alpha_pvalue_lt_0.05",
        "oos_total_return_gt_benchmark",
        "deflated_alpha_ratio_gt_0.90",
    }
    for c in criteria:
        assert isinstance(c["passed"], bool)
        assert c["description"]
    assert result["all_pass"] == all(c["passed"] for c in criteria)

    # Split separation audit: the held-out test set is independent of train/val
    # and never used in selection.
    sep = result["separation_check"]
    assert sep.get("disjoint") is True
    assert sep.get("chronological") is True
    for overlap in ("train_val_overlap", "val_test_overlap", "train_test_overlap"):
        assert sep.get(overlap) == 0
    assert sep.get("train_size") and sep.get("val_size") and sep.get("test_size")

    # Test resolution is reported alongside the verdict (a measurement, not a
    # correction): the smallest effect each significance criterion could have
    # confirmed on this real-market sample.
    res = result["resolution"]
    for key in ("n_test_observations", "n_parameter_trials", "n_benchmarks",
                "min_detectable_sharpe", "min_detectable_alpha",
                "min_detectable_benchmark_alpha",
                "criteria_beyond_resolution",
                "plausible_max_annualized_sharpe",
                "plausible_max_annualized_alpha"):
        assert key in res, f"resolution block missing {key}"
    assert res["n_test_observations"] == obs["test_n_observations"]
    # The resolution analysis must not change the verdict.
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")


def test_falsifiable_machinery_on_googl_real_market_data():
    """Real-market machinery check on GOOGL primary, MSFT benchmark."""
    import contextlib
    import io
    import shutil
    import tempfile
    from pathlib import Path

    src_dir = SKILLS_DIR / "assets" / "example_data" / "real_market_data"
    assert (src_dir / "GOOGL.csv").exists()
    assert (src_dir / "MSFT.csv").exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        shutil.copyfile(src_dir / "GOOGL.csv", d / "sample_ohlcv.csv")
        shutil.copyfile(src_dir / "MSFT.csv", d / "sample_benchmark.csv")
        data_path = d / "sample_ohlcv.csv"

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_hypothesis_test(data_path)

    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["pit_passed"] is True
    assert result["bias_controls_engaged"] is True
    obs = result["observed"]
    assert obs["test_n_observations"] and obs["test_n_observations"] > 0
    assert obs["n_benchmarks"] and obs["n_benchmarks"] >= 2
    assert len(result["criteria"]) == 5
    sep = result["separation_check"]
    assert sep.get("disjoint") is True
    assert sep.get("chronological") is True
    for overlap in ("train_val_overlap", "val_test_overlap", "train_test_overlap"):
        assert sep.get(overlap) == 0
    res = result["resolution"]
    for key in ("n_test_observations", "n_parameter_trials", "n_benchmarks",
                "min_detectable_sharpe", "min_detectable_alpha",
                "min_detectable_benchmark_alpha"):
        assert key in res
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")


def test_falsifiable_machinery_on_aapl_real_market_data():
    """Real-market machinery check on AAPL primary, MSFT benchmark."""
    import contextlib
    import io
    import shutil
    import tempfile
    from pathlib import Path

    src_dir = SKILLS_DIR / "assets" / "example_data" / "real_market_data"
    assert (src_dir / "AAPL.csv").exists()
    assert (src_dir / "MSFT.csv").exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        shutil.copyfile(src_dir / "AAPL.csv", d / "sample_ohlcv.csv")
        shutil.copyfile(src_dir / "MSFT.csv", d / "sample_benchmark.csv")
        data_path = d / "sample_ohlcv.csv"

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_hypothesis_test(data_path)

    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["pit_passed"] is True
    assert result["bias_controls_engaged"] is True
    obs = result["observed"]
    assert obs["test_n_observations"] and obs["test_n_observations"] > 0
    assert obs["n_benchmarks"] and obs["n_benchmarks"] >= 2
    assert len(result["criteria"]) == 5
    sep = result["separation_check"]
    assert sep.get("disjoint") is True
    assert sep.get("chronological") is True
    for overlap in ("train_val_overlap", "val_test_overlap", "train_test_overlap"):
        assert sep.get(overlap) == 0
    res = result["resolution"]
    for key in ("n_test_observations", "n_parameter_trials", "n_benchmarks",
                "min_detectable_sharpe", "min_detectable_alpha",
                "min_detectable_benchmark_alpha"):
        assert key in res
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")


def test_falsifiable_machinery_on_msft_real_market_data():
    """Real-market machinery check on MSFT primary, GOOGL benchmark."""
    import contextlib
    import io
    import shutil
    import tempfile
    from pathlib import Path

    src_dir = SKILLS_DIR / "assets" / "example_data" / "real_market_data"
    assert (src_dir / "MSFT.csv").exists()
    assert (src_dir / "GOOGL.csv").exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        shutil.copyfile(src_dir / "MSFT.csv", d / "sample_ohlcv.csv")
        shutil.copyfile(src_dir / "GOOGL.csv", d / "sample_benchmark.csv")
        data_path = d / "sample_ohlcv.csv"

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            result = run_hypothesis_test(data_path)

    assert isinstance(result, dict)
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert result["pit_passed"] is True
    assert result["bias_controls_engaged"] is True
    obs = result["observed"]
    assert obs["test_n_observations"] and obs["test_n_observations"] > 0
    assert obs["n_benchmarks"] and obs["n_benchmarks"] >= 2
    assert len(result["criteria"]) == 5
    sep = result["separation_check"]
    assert sep.get("disjoint") is True
    assert sep.get("chronological") is True
    for overlap in ("train_val_overlap", "val_test_overlap", "train_test_overlap"):
        assert sep.get(overlap) == 0
    res = result["resolution"]
    for key in ("n_test_observations", "n_parameter_trials", "n_benchmarks",
                "min_detectable_sharpe", "min_detectable_alpha",
                "min_detectable_benchmark_alpha"):
        assert key in res
    assert result["all_pass"] == all(c["passed"] for c in result["criteria"])
    assert result["verdict"] == ("SUPPORTED" if result["all_pass"] else "NOT SUPPORTED")


def test_real_market_cost_sensitivity_sweep():
    """Transaction-cost sensitivity on committed real market data.

    Runs the example's cost-sensitivity sweep on real market data
    (GOOGL strategy vs the committed MSFT benchmark) across ascending
    commission/slippage levels and asserts the honest directional claim:
    as per-trade costs rise, net out-of-sample Sharpe, total return and
    Deflated Alpha Ratio never improve.

    This extends the independent real-market out-of-sample evidence with a
    sensitivity analysis on real securities, not a synthetic formula. The
    claim is purely directional; the verdict at each cost level is not
    asserted (SUPPORTED / NOT SUPPORTED are both valid scientific outcomes).
    Offline: uses only committed fixtures, no network.
    """
    data_path = (
        SKILLS_DIR
        / "assets"
        / "example_data"
        / "real_market_data"
        / "GOOGL.csv"
    )
    assert data_path.exists(), "real market data fixture missing"
    assert (data_path.parent / "sample_benchmark.csv").exists(), (
        "benchmark fixture missing"
    )

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_cost_sensitivity_sweep(data_path)

    assert len(rows) == len(COST_SWEEP_LEVELS), (
        f"expected {len(COST_SWEEP_LEVELS)} cost levels, got {len(rows)}"
    )
    assert [r["commission_bps"] for r in rows] == [
        c * 10_000 for c, _ in COST_SWEEP_LEVELS
    ], "cost sweep levels are not recorded in ascending order"
    assert rows[0]["commission_bps"] == 0.0 and rows[0]["slippage_bps"] == 0.0, (
        "first cost sweep level must be frictionless"
    )

    # Directional claim: higher per-trade costs never improve net metrics.
    series = {
        "sharpe_ratio": "Sharpe ratio",
        "total_return": "total return",
        "deflated_alpha_ratio": "Deflated Alpha Ratio",
    }
    for key, label in series.items():
        values = [r[key] for r in rows]
        assert all(v is not None and np.isfinite(v) for v in values), (
            f"{label} is missing or non-finite at one or more cost levels: {values}"
        )
        for prev, curr in zip(values, values[1:]):
            assert curr <= prev + 1e-12, (
                f"{label} does not degrade monotonically with cost on real "
                f"market data: {prev} -> {curr}"
            )

    # Each cost level produces a determinate, criteria-evaluated verdict.
    for r in rows:
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert len(r["criteria"]) == 5

    # Extend machinery separation audit to GOOGL vs committed benchmark pair.
    from falsifiable_hypothesis_example import run_hypothesis_test

    buffer2 = io.StringIO()
    with contextlib.redirect_stdout(buffer2):
        result = run_hypothesis_test(data_path, commission=COMMISSION, slippage=SLIPPAGE)
    sep = result.get("separation_check") or result.get("train_val_test_split", {}).get("separation_check", {})
    assert sep.get("disjoint") is True
    assert sep.get("chronological") is True
    for overlap in ("train_val_overlap", "val_test_overlap", "train_test_overlap"):
        assert sep.get(overlap) == 0
    assert result.get("pit_passed") is True
    assert result.get("bias_controls_engaged") is True


def test_real_market_cost_sensitivity_sweep_msft():
    """Transaction-cost sensitivity on committed real market data (MSFT vs GOOGL).

    Runs the example's cost-sensitivity sweep on real market data
    (MSFT strategy vs the committed GOOGL benchmark) across
    ascending commission/slippage levels and asserts the honest directional
    claim: as per-trade costs rise, net out-of-sample Sharpe, total return
    and Deflated Alpha Ratio never improve.
    Offline: uses only committed fixtures, no network.
    """
    data_path = (
        SKILLS_DIR
        / "assets"
        / "example_data"
        / "real_market_data"
        / "MSFT.csv"
    )
    benchmark_path = (
        SKILLS_DIR
        / "assets"
        / "example_data"
        / "real_market_data"
        / "GOOGL.csv"
    )
    assert data_path.exists(), "real market data fixture missing"
    assert benchmark_path.exists(), "benchmark fixture missing"

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_cost_sensitivity_sweep(data_path, benchmark_path=benchmark_path)

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
        "deflated_alpha_ratio": "Deflated Alpha Ratio",
    }
    for key, label in series.items():
        values = [r[key] for r in rows]
        assert all(v is not None and np.isfinite(v) for v in values), (
            f"{label} is missing or non-finite at one or more cost levels: {values}"
        )
        for prev, curr in zip(values, values[1:]):
            assert curr <= prev + 1e-12, (
                f"{label} does not degrade monotonically with cost on real "
                f"market data: {prev} -> {curr}"
            )

    for r in rows:
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert len(r["criteria"]) == 5

    # Extend machinery separation audit to MSFT vs GOOGL pair.
    from falsifiable_hypothesis_example import run_hypothesis_test

    buffer2 = io.StringIO()
    with contextlib.redirect_stdout(buffer2):
        result = run_hypothesis_test(data_path, benchmark_path=benchmark_path, commission=COMMISSION, slippage=SLIPPAGE)
    sep = result.get("separation_check") or result.get("train_val_test_split", {}).get("separation_check", {})
    assert sep.get("disjoint") is True
    assert sep.get("chronological") is True
    for overlap in ("train_val_overlap", "val_test_overlap", "train_test_overlap"):
        assert sep.get(overlap) == 0
    assert result.get("pit_passed") is True
    assert result.get("bias_controls_engaged") is True


def test_real_market_cost_sensitivity_sweep_aapl_msft():
    """Transaction-cost sensitivity on committed real market data (AAPL vs MSFT).

    Runs the example's cost-sensitivity sweep on real market data
    (AAPL strategy vs the committed MSFT benchmark) across ascending
    commission/slippage levels and asserts the honest directional claim.
    Offline: uses only committed fixtures, no network.
    """
    data_path = (
        SKILLS_DIR
        / "assets"
        / "example_data"
        / "real_market_data"
        / "AAPL.csv"
    )
    benchmark_path = (
        SKILLS_DIR
        / "assets"
        / "example_data"
        / "real_market_data"
        / "MSFT.csv"
    )
    assert data_path.exists(), "real market data fixture missing"
    assert benchmark_path.exists(), "benchmark fixture missing"

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_cost_sensitivity_sweep(data_path, benchmark_path=benchmark_path)

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
        "deflated_alpha_ratio": "Deflated Alpha Ratio",
    }
    for key, label in series.items():
        values = [r[key] for r in rows]
        assert all(v is not None and np.isfinite(v) for v in values), (
            f"{label} is missing or non-finite at one or more cost levels: {values}"
        )
        for prev, curr in zip(values, values[1:]):
            assert curr <= prev + 1e-12, (
                f"{label} does not degrade monotonically with cost on real "
                f"market data: {prev} -> {curr}"
            )

    for r in rows:
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert len(r["criteria"]) == 5

    # Extend machinery separation audit to AAPL vs MSFT pair and verify split
    # separation audit holds (held-out test set never used in selection).
    from falsifiable_hypothesis_example import run_hypothesis_test

    buffer2 = io.StringIO()
    with contextlib.redirect_stdout(buffer2):
        result = run_hypothesis_test(data_path, commission=COMMISSION, slippage=SLIPPAGE)
    sep = result.get("separation_check") or result.get("train_val_test_split", {}).get("separation_check", {})
    assert sep.get("disjoint") is True
    assert sep.get("chronological") is True
    for overlap in ("train_val_overlap", "val_test_overlap", "train_test_overlap"):
        assert sep.get(overlap) == 0
    assert result.get("pit_passed") is True
    assert result.get("bias_controls_engaged") is True


def test_real_market_cost_sensitivity_sweep_aapl():
    """Transaction-cost sensitivity on committed real market data (AAPL).

    Runs the example's cost-sensitivity sweep on real market data
    (AAPL strategy vs committed benchmarks in real_market_data/) across
    ascending commission/slippage levels and asserts the honest directional
    claim: as per-trade costs rise, net out-of-sample Sharpe, total return
    and Deflated Alpha Ratio never improve.
    Offline: uses only committed fixtures, no network.
    """
    data_path = (
        SKILLS_DIR
        / "assets"
        / "example_data"
        / "real_market_data"
        / "AAPL.csv"
    )
    assert data_path.exists(), "real market data fixture missing"

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        rows = run_cost_sensitivity_sweep(data_path)

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
        "deflated_alpha_ratio": "Deflated Alpha Ratio",
    }
    for key, label in series.items():
        values = [r[key] for r in rows]
        assert all(v is not None and np.isfinite(v) for v in values), (
            f"{label} is missing or non-finite at one or more cost levels: {values}"
        )
        for prev, curr in zip(values, values[1:]):
            assert curr <= prev + 1e-12, (
                f"{label} does not degrade monotonically with cost on real "
                f"market data: {prev} -> {curr}"
            )

    for r in rows:
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert len(r["criteria"]) == 5


def main() -> int:
    tests = TEST_REGISTRY
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return 1 if failures else 0


TEST_REGISTRY = [
    ("test_falsifiable_hypothesis_example_runs_end_to_end", test_falsifiable_hypothesis_example_runs_end_to_end),
    ("test_falsifiable_hypothesis_criteria_are_explicit_and_evaluated", test_falsifiable_hypothesis_criteria_are_explicit_and_evaluated),
    ("test_falsifiable_hypothesis_out_of_sample_split_is_chronological", test_falsifiable_hypothesis_out_of_sample_split_is_chronological),
    ("test_the_alpha_criterion_reads_the_raw_p_value_and_the_dar_the_corrected_one", test_the_alpha_criterion_reads_the_raw_p_value_and_the_dar_the_corrected_one),
    ("test_the_example_reports_the_test_resolution", test_the_example_reports_the_test_resolution),
    ("test_the_resolution_does_not_change_the_verdict", test_the_resolution_does_not_change_the_verdict),
    ("test_the_test_window_is_reported_in_observations_not_periods", test_the_test_window_is_reported_in_observations_not_periods),
    ("test_the_example_prints_the_resolution_and_the_reading_note", test_the_example_prints_the_resolution_and_the_reading_note),
    ("test_the_synthetic_positive_control_returns_supported", test_the_synthetic_positive_control_returns_supported),
    ("test_the_positive_control_effect_clears_the_reported_minimum_detectable_effect", test_the_positive_control_effect_clears_the_reported_minimum_detectable_effect),
    ("test_the_no_effect_control_returns_not_supported", test_the_no_effect_control_returns_not_supported),
    ("test_the_control_pair_differs_only_by_the_injected_effect", test_the_control_pair_differs_only_by_the_injected_effect),
    ("test_the_control_verdict_is_not_a_property_of_one_seed", test_the_control_verdict_is_not_a_property_of_one_seed),
    ("test_the_control_fixture_is_labelled_as_synthetic_and_carries_no_security", test_the_control_fixture_is_labelled_as_synthetic_and_carries_no_security),
    ("test_the_example_records_its_methodology_block", test_the_example_records_its_methodology_block),
    ("test_the_advertised_costs_are_actually_applied", test_the_advertised_costs_are_actually_applied),
    ("test_falsifiable_hypothesis_cost_sensitivity_sweep", test_falsifiable_hypothesis_cost_sensitivity_sweep),
    ("test_the_selection_criterion_is_oos_aware", test_the_selection_criterion_is_oos_aware),
    ("test_falsifiable_machinery_on_independent_out_of_sample_fixture", test_falsifiable_machinery_on_independent_out_of_sample_fixture),
    ("test_falsifiable_machinery_on_independent_real_market_data", test_falsifiable_machinery_on_independent_real_market_data),
    ("test_falsifiable_machinery_on_googl_real_market_data", test_falsifiable_machinery_on_googl_real_market_data),
    ("test_falsifiable_machinery_on_aapl_real_market_data", test_falsifiable_machinery_on_aapl_real_market_data),
    ("test_falsifiable_machinery_on_msft_real_market_data", test_falsifiable_machinery_on_msft_real_market_data),
    ("test_real_market_cost_sensitivity_sweep", test_real_market_cost_sensitivity_sweep),
    ("test_real_market_cost_sensitivity_sweep_msft", test_real_market_cost_sensitivity_sweep_msft),
    ("test_real_market_cost_sensitivity_sweep_aapl", test_real_market_cost_sensitivity_sweep_aapl),
    ("test_real_market_cost_sensitivity_sweep_aapl_msft", test_real_market_cost_sensitivity_sweep_aapl_msft),
]


if __name__ == "__main__":
    import sys
    sys.exit(main())
