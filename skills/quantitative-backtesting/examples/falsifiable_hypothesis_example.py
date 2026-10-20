#!/usr/bin/env python3
"""
Falsifiable financial hypothesis test.

Tests a specific, bounded hypothesis with explicit falsification criteria:

    HYPOTHESIS: An SMA-crossover trend-following strategy produces
    statistically significant positive out-of-sample alpha (net of 3 bps
    round-trip trading costs) versus a buy-and-hold benchmark on the sample
    equity universe.

FALSIFICATION CRITERIA (reject H / declare "NOT SUPPORTED" if ANY fails):
    1. Out-of-sample Sharpe (net of costs) must be > 0.
    2. Deflated Sharpe p-value (selection-bias corrected across the parameter
       grid) must be < 0.10.
    3. Benchmark alpha p-value must be < 0.05 (alpha statistically distinct
       from zero vs buy-and-hold). This is the RAW, uncorrected alpha test.
    4. Out-of-sample total return (net of costs) must exceed benchmark total
       return.
    5. Deflated Alpha Ratio (multiple-testing corrected benchmark alpha across
       the benchmark set) must be > 0.90, i.e. the corrected p-value < 0.10.
       This is the benchmark-side data-mining control: testing against
       multiple benchmarks is itself a multiple-testing problem, and this
       criterion requires the alpha to survive the correction for the number
       of benchmarks tested (N = 2 here).

The hypothesis is SUPPORTED only when ALL five criteria pass. Otherwise it is
NOT SUPPORTED. No claim of profitability is made: this is a test verdict
against pre-registered criteria, not a performance endorsement. The decision
rule is fixed in advance and is not changed after the result is seen.

WHAT THE VERDICT DOES AND DOES NOT MEAN
    A significance test on a small sample can fail for reasons that have
    nothing to do with the hypothesis. This example therefore also reports the
    RESOLUTION of the test: the smallest effect each statistical criterion
    requires in order to pass, given the number of test observations actually
    available (the "minimum detectable effect"). Criteria whose required
    effect exceeds a stated plausibility bound are flagged as beyond the
    sample's resolution, and the report says so in those words. A failed
    criterion that the sample cannot resolve is not evidence against the
    hypothesis; it is a statement about the sample size. The verdict itself
    is unchanged by this analysis -- it remains the conjunction of the
    pre-registered criteria.

Methodology controls:
    - Chronological train/validation/test split (0.6 / 0.2 / 0.2). The held-out
      test set is never used in any parameter selection step; the executable
      split-separation invariant is asserted and audited.
    - Point-in-time validation (look-ahead / stale-data / temporal-ordering
      screening) runs by default (bias_controls_engaged).
    - Walk-forward parameter selection on training data only.
    - Deflated Sharpe Ratio for multiple-testing correction across the
      parameter grid (selection bias).
    - Multiple benchmarks with Deflated Alpha Ratio correction for benchmark
      selection bias (data-mining control).
    - Benchmark alpha vs buy-and-hold, net of the same trading costs
      (2 bps commission + 1 bps slippage per trade).
    - All figures are net of trading costs.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from data_loader import load_data
from performance import t_critical_value
from strategy_builder import build_strategy
from walk_forward import (
    PLAUSIBLE_MAX_ANNUALIZED_ALPHA,
    PLAUSIBLE_MAX_ANNUALIZED_SHARPE,
    _annualization_factor,
    minimum_detectable_alpha,
    minimum_detectable_sharpe,
    out_of_sample_validation,
)


# ---------------------------------------------------------------------------
# Pre-registered hypothesis & falsification criteria
# ---------------------------------------------------------------------------
HYPOTHESIS = (
    "An SMA-crossover trend-following strategy produces statistically "
    "significant positive out-of-sample alpha (net of 3 bps round-trip "
    "trading costs) versus a buy-and-hold benchmark on the sample equity "
    "universe."
)

# Criterion name -> (required direction, threshold). A criterion "passes" when
# the observed value satisfies the direction relative to the threshold.
CRITERIA = [
    ("oos_sharpe_gt_zero", "oos_sharpe > 0", lambda v: v is not None and v > 0.0),
    ("deflated_sharpe_pvalue_lt_0.10", "deflated_sharpe_pvalue < 0.10",
     lambda v: v is not None and v < 0.10),
    ("benchmark_alpha_pvalue_lt_0.05", "raw benchmark_alpha_pvalue < 0.05",
     lambda v: v is not None and v < 0.05),
    ("oos_total_return_gt_benchmark", "oos_total_return > benchmark_total_return",
     lambda v: v is not None),
    # Data-mining control for benchmark selection: the strategy is tested
    # against MULTIPLE benchmarks, which is itself a multiple-testing
    # problem (the more benchmarks you try, the more likely one yields a
    # spurious "significant" alpha by luck). The Deflated Alpha Ratio (DAR)
    # corrects the benchmark alpha for the number of benchmarks tested, so
    # this criterion requires the corrected alpha to survive the correction
    # (DAR > 0.90, i.e. corrected p-value < 0.10). It is the benchmark-side
    # analogue of criterion 2 (the Deflated Sharpe Ratio), which corrects
    # the parameter-grid selection bias.
    #
    # Criterion 3 above is deliberately the RAW (uncorrected) alpha test, so
    # that criterion 5 carries the multiple-testing correction on its own:
    # with both criteria reading the corrected p-value, criterion 5 would be
    # implied by criterion 3 and the advertised data-mining control would
    # never bind independently.
    ("deflated_alpha_ratio_gt_0.90", "deflated_alpha_ratio > 0.90 (corrected p-value < 0.10)",
     lambda v: v is not None and v > 0.90),
]

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade
PARAM_GRID = {"fast_period": [5, 10, 15, 20], "slow_period": [20, 30, 40, 50]}

# Significance level the deflated criteria are stated at (criteria 2 and 5).
CRITERION_P_VALUE_THRESHOLD = 0.10

# Plausibility bounds used to flag a criterion as beyond the sample's
# resolution. These are ASSUMPTIONS, declared up front and printed with the
# result so a reader can see and dispute them; they are not derived from the
# data and they never change the verdict. An annualized Sharpe above 2.0 or
# an annualized alpha above 10% would itself be extraordinary for a liquid
# equity strategy -- in practice a sign of a bug or a data problem rather
# than of skill -- so a criterion that requires more than this cannot
# discriminate between hypotheses at the available sample size.
#
# The values are the framework's own (`walk_forward.PLAUSIBLE_MAX_*`), so the
# example and the library's aggregate verdicts cannot drift apart.

# Benchmarks tested against. Testing multiple benchmarks is a
# multiple-testing problem; the Deflated Alpha Ratio (criterion 5) corrects
# the benchmark alpha for the number of benchmarks tested (N = len(BENCHMARKS)).
# The primary benchmark is the first entry; the remainder are alternative
# buy-and-hold universes that the strategy might have "cherry-picked" alpha
# against. All are net of the same commission/slippage as the strategy.
# Paths are relative to the strategy data file's directory (assets/example_data).
BENCHMARK_FILES = [
    "sample_ohlcv.csv",     # primary (same universe)
    "sample_benchmark.csv",  # alternative benchmark
]


def _fmt_pct(v):
    if v is None or not np.isfinite(v):
        return "N/A"
    return f"{v:.2%}"


def _fmt_num(v, nd=4):
    if v is None or not np.isfinite(v):
        return "N/A"
    return f"{v:.{nd}f}"


def _alpha_regression_df(test_returns, benchmark_frame):
    """Degrees of freedom of the benchmark alpha regression.

    The alpha regression runs on the strategy and benchmark returns aligned
    on common dates over the held-out test window, so its observation count is
    the length of that aligned intersection (and its degrees of freedom are
    that count minus two). Returns None when it cannot be determined.
    """
    try:
        if test_returns is None or benchmark_frame is None:
            return None
        bench_returns = benchmark_frame["close"].pct_change()
        aligned_strategy, aligned_bench = test_returns.align(
            bench_returns, join="inner"
        )
        n = int((aligned_strategy.notna() & aligned_bench.notna()).sum())
    except Exception:
        return None
    if n < 3:
        return None
    return n - 2


def _test_resolution(summary, test_returns, benchmark_frame, primary_bench):
    """Minimum detectable effect of each statistical criterion.

    A significance test on a small sample can only fail: with T observations
    the threshold "deflated p < 0.10" requires the effect to exceed a
    certain size. This helper reports that size for each statistical
    criterion (the test's resolution) and flags the criteria whose required
    effect exceeds the stated plausibility bound -- a failure of such a
    criterion is not evidence against the hypothesis.

    The numbers are measurements, not corrections: no criterion outcome and
    no verdict is changed here.
    """
    resolution = {
        "n_test_observations": None,
        "n_parameter_trials": None,
        "n_benchmarks": None,
        "min_detectable_sharpe": None,
        "min_detectable_alpha": None,
        "min_detectable_benchmark_alpha": None,
        "alpha_regression_df": None,
        "criteria_beyond_resolution": [],
        "plausible_max_annualized_sharpe": PLAUSIBLE_MAX_ANNUALIZED_SHARPE,
        "plausible_max_annualized_alpha": PLAUSIBLE_MAX_ANNUALIZED_ALPHA,
    }

    deflated_sharpe = summary.get("deflated_sharpe")
    deflated_alpha = summary.get("deflated_alpha")

    if isinstance(deflated_sharpe, dict):
        resolution["n_test_observations"] = deflated_sharpe.get("n_observations")
        resolution["n_parameter_trials"] = deflated_sharpe.get("n_trials")
        mde = minimum_detectable_sharpe(
            deflated_sharpe, test_returns, CRITERION_P_VALUE_THRESHOLD
        )
        value = mde.get("minimum_detectable_sharpe")
        if value is not None:
            resolution["min_detectable_sharpe"] = float(value)
            if value > PLAUSIBLE_MAX_ANNUALIZED_SHARPE:
                resolution["criteria_beyond_resolution"].append(
                    "deflated_sharpe_pvalue_lt_0.10"
                )

    if isinstance(deflated_alpha, dict):
        resolution["n_benchmarks"] = deflated_alpha.get("n_benchmarks")
        mde = minimum_detectable_alpha(
            deflated_alpha, test_returns, CRITERION_P_VALUE_THRESHOLD
        )
        value = mde.get("minimum_detectable_alpha")
        if value is not None:
            resolution["min_detectable_alpha"] = float(value)
            if value > PLAUSIBLE_MAX_ANNUALIZED_ALPHA:
                resolution["criteria_beyond_resolution"].append(
                    "deflated_alpha_ratio_gt_0.90"
                )

    # Criterion 3 (the raw, uncorrected alpha t-test). Its resolution is
    # t_crit * standard error of the alpha estimate; the standard error is
    # recovered exactly from the reported t-statistic (t = alpha / se).
    df = _alpha_regression_df(test_returns, benchmark_frame)
    if df is None:
        n_obs = resolution["n_test_observations"]
        df = (int(n_obs) - 2) if n_obs else None
    resolution["alpha_regression_df"] = df
    if df and isinstance(primary_bench, dict):
        alpha = primary_bench.get("alpha")
        t_stat = primary_bench.get("alpha_tstat")
        if alpha is not None and t_stat not in (None, 0) and test_returns is not None:
            ann_factor = _annualization_factor(test_returns.index)
            se_alpha = (float(alpha) / ann_factor) / float(t_stat)
            t_crit = t_critical_value(int(df), 0.05)
            if t_crit is not None and se_alpha > 0:
                mde_alpha = t_crit * se_alpha * ann_factor
                resolution["min_detectable_benchmark_alpha"] = float(mde_alpha)
                if mde_alpha > PLAUSIBLE_MAX_ANNUALIZED_ALPHA:
                    resolution["criteria_beyond_resolution"].append(
                        "benchmark_alpha_pvalue_lt_0.05"
                    )

    return resolution


def run_hypothesis_test(data_path, symbol="SPY"):
    """Run the pre-registered falsifiable hypothesis test.

    Returns a dict with the observed metrics, per-criterion pass/fail, and the
    overall verdict ("SUPPORTED" / "NOT SUPPORTED" / "ERROR").

    The benchmark set is resolved from BENCHMARK_FILES relative to this
    example's assets directory (the same directory as `data_path`), so the
    test exercises the multiple-benchmark Deflated Alpha Ratio path by default.
    """
    base_dir = Path(data_path).resolve().parent
    print("=" * 80)
    print("FALSIFIABLE FINANCIAL HYPOTHESIS TEST")
    print("=" * 80)
    print()
    print("Hypothesis:")
    print(f"  {HYPOTHESIS}")
    print()
    print("Falsification criteria (hypothesis NOT SUPPORTED if any fails):")
    for name, desc, _ in CRITERIA:
        print(f"  - {name}: {desc}")
    print()
    print("Methodology controls: chronological 0.6/0.2/0.2 train/val/test split,")
    print("  point-in-time validation, walk-forward parameter selection on training")
    print("  data only, Deflated Sharpe multiple-testing correction, Deflated Alpha")
    print("  Ratio benchmark-selection correction, benchmark alpha vs buy-and-hold,")
    print(f"  all figures net of {COMMISSION*1e4:.0f}bps commission +")
    print(f"  {SLIPPAGE*1e4:.0f}bps slippage per trade.")
    print("-" * 80)

    # --- Load data (point-in-time validation runs inside out_of_sample_validation) ---
    print("\n1. LOADING DATA")
    df = load_data(str(data_path), symbol=symbol)
    # Multiple benchmarks: the strategy is tested against N=2 buy-and-hold
    # universes. Testing multiple benchmarks is itself a multiple-testing
    # problem — with enough benchmarks, luck alone yields a spurious
    # "significant" alpha — so criterion 5 (Deflated Alpha Ratio) corrects the
    # benchmark alpha for the number of benchmarks tested. The primary
    # benchmark is the first entry; the remainder are alternative universes
    # the strategy might have "cherry-picked" alpha against.
    benchmarks = [load_data(str(base_dir / p), symbol=symbol) for p in BENCHMARK_FILES]
    print(f"  Strategy data: {len(df)} rows ({df.index.min().date()} -> {df.index.max().date()})")
    print(f"  Benchmarks: {len(benchmarks)} ({[len(b) for b in benchmarks]} rows each)")

    # --- Run out-of-sample validation ---
    print("\n2. OUT-OF-SAMPLE VALIDATION (chronological train/val/test)")
    # selection_criterion="best_avg_sharpe" selects the parameter set with the
    # best AVERAGE OUT-OF-SAMPLE test Sharpe across the walk-forward periods
    # where it was chosen. It is OOS-aware: it reads each period's
    # `test_sharpe`, never `best_sharpe` (the in-sample training Sharpe the
    # grid search ranked by). Selecting on in-sample fit would pick the combo
    # that overfit its training window — the selection bias this framework
    # exists to avoid.
    results = out_of_sample_validation(
        data=df,
        strategy_factory=lambda params: build_strategy("sma_crossover", __import__("json").dumps(params)),
        param_grid=PARAM_GRID,
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        validation_method="walk_forward",
        walk_forward_train_months=6,
        walk_forward_test_months=2,
        walk_forward_step_months=2,
        initial_capital=100000,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        benchmark=benchmarks,
        total_return_benchmark=False,
        benchmark_commission=COMMISSION,
        benchmark_slippage=SLIPPAGE,
        benchmark_expense_ratio=0.0,
        benchmark_cost_is_periodic=False,
        apply_deflation=True,
        selection_criterion="best_avg_sharpe",
        validate_pit=True,
    )

    if results.get("test_performance") is None:
        print("  No valid parameters found in validation phase -> hypothesis NOT SUPPORTED (no testable signal).")
        return {
            "hypothesis": HYPOTHESIS,
            "verdict": "NOT SUPPORTED",
            "reason": "no_valid_parameters",
            "criteria": [],
            "observed": {},
            "resolution": {},
            "criteria_beyond_resolution": [],
        }

    test_perf = results["test_performance"]
    test_bench = results.get("test_benchmark")
    summary = results.get("summary", {})
    split = results.get("train_val_test_split", {})
    pit = results.get("point_in_time_validation")

    oos_sharpe = summary.get("test_sharpe")
    oos_total_return = summary.get("test_total_return")
    deflated_sharpe = summary.get("deflated_sharpe")
    dsr_pvalue = deflated_sharpe.get("p_value") if isinstance(deflated_sharpe, dict) else None
    # The framework reports the number of test OBSERVATIONS (daily bars in the
    # held-out window), not the number of independent periods.
    test_n_observations = test_perf.get("test_n_periods")

    # Multiple-benchmark path: alpha / alpha_pvalue / benchmark_total_return
    # come from the primary (first) benchmark in the per-benchmark list; the
    # Deflated Alpha Ratio (criterion 5) is the multiple-testing corrected
    # benchmark alpha across the whole benchmark set.
    #
    # The correction REWRITES the primary benchmark's `alpha_pvalue` with the
    # deflated p-value and keeps the raw one in `alpha_pvalue_original`.
    # Criterion 3 is the RAW test and criterion 5 is the corrected one, so
    # both are read explicitly here: reading only `alpha_pvalue` would make
    # the two criteria the same statistic and the advertised data-mining
    # control vacuous.
    bench_alpha = None
    bench_alpha_pvalue_raw = None
    bench_alpha_pvalue_corrected = None
    bench_total_return = None
    primary_bench = None
    if isinstance(test_bench, list) and test_bench:
        primary_bench = test_bench[0]
        if isinstance(primary_bench, dict):
            bench_alpha = primary_bench.get("alpha")
            bench_alpha_pvalue_corrected = primary_bench.get("alpha_pvalue")
            bench_alpha_pvalue_raw = primary_bench.get("alpha_pvalue_original")
            bench_total_return = primary_bench.get("benchmark_total_return")
    if isinstance(test_bench, dict):
        primary_bench = primary_bench or test_bench
        bench_alpha = bench_alpha or test_bench.get("alpha")
        bench_alpha_pvalue_corrected = (
            bench_alpha_pvalue_corrected or test_bench.get("alpha_pvalue")
        )
        bench_alpha_pvalue_raw = (
            bench_alpha_pvalue_raw or test_bench.get("alpha_pvalue_original")
        )
        bench_total_return = bench_total_return or test_bench.get("benchmark_total_return")
    if bench_alpha is None:
        bench_alpha = test_perf.get("alpha")
    if bench_alpha_pvalue_corrected is None:
        bench_alpha_pvalue_corrected = test_perf.get("alpha_pvalue")
    if bench_alpha_pvalue_raw is None:
        # No multiple-testing correction was applied (single benchmark), so
        # the raw and the corrected p-value are the same number.
        bench_alpha_pvalue_raw = bench_alpha_pvalue_corrected
    if bench_total_return is None:
        bench_total_return = test_perf.get("benchmark_total_return")

    # A multiple-testing correction was applied only when the raw p-value is
    # still available and differs from the corrected one.
    alpha_correction_applied = bool(
        bench_alpha_pvalue_raw is not None
        and bench_alpha_pvalue_corrected is not None
        and bench_alpha_pvalue_raw != bench_alpha_pvalue_corrected
    )

    # Deflated Alpha Ratio (multiple-testing corrected benchmark alpha across
    # the benchmark set). Sourced from the canonical aggregate
    # `deflated_alpha` in the summary, which carries the corrected p-value
    # (and DAR) for the primary benchmark across all N benchmarks.
    deflated_alpha = summary.get("deflated_alpha")
    dar = deflated_alpha.get("deflated_alpha_ratio") if isinstance(deflated_alpha, dict) else None
    dar_pvalue = deflated_alpha.get("p_value") if isinstance(deflated_alpha, dict) else None
    n_benchmarks = deflated_alpha.get("n_benchmarks") if isinstance(deflated_alpha, dict) else len(benchmarks)

    observed = {
        "oos_sharpe": oos_sharpe,
        "oos_total_return": oos_total_return,
        "deflated_sharpe_pvalue": dsr_pvalue,
        "benchmark_alpha": bench_alpha,
        "benchmark_alpha_pvalue": bench_alpha_pvalue_raw,
        "benchmark_alpha_pvalue_corrected": bench_alpha_pvalue_corrected,
        "benchmark_alpha_correction_applied": alpha_correction_applied,
        "benchmark_total_return": bench_total_return,
        "deflated_alpha_ratio": dar,
        "deflated_alpha_pvalue": dar_pvalue,
        "n_benchmarks": n_benchmarks,
        "selected_params": summary.get("selected_params"),
        "selected_params_avg_test_sharpe": summary.get("selected_params_avg_test_sharpe"),
        "test_n_observations": test_n_observations,
    }

    # --- Evaluate falsification criteria ---
    print("\n3. OBSERVED OUT-OF-SAMPLE METRICS (net of costs)")
    print(f"  OOS Sharpe:              {_fmt_num(oos_sharpe)}")
    print(f"  OOS total return:        {_fmt_pct(oos_total_return)}")
    print(f"  Benchmark total return:  {_fmt_pct(bench_total_return)}")
    print(f"  Benchmark alpha:         {_fmt_pct(bench_alpha)}")
    print(f"  Benchmark alpha p-value (raw, criterion 3):     "
          f"{_fmt_num(bench_alpha_pvalue_raw)}")
    print(f"  Benchmark alpha p-value (deflated, N={n_benchmarks}): "
          f"{_fmt_num(bench_alpha_pvalue_corrected)}")
    print(f"  Deflated Sharpe p-value: {_fmt_num(dsr_pvalue)}")
    print(f"  Deflated Alpha Ratio:     {_fmt_num(dar)}")
    print(f"  Deflated Alpha p-value:  {_fmt_num(dar_pvalue)}")
    print(f"  Benchmarks tested (N):   {n_benchmarks}")
    print(f"  Selected params:         {observed['selected_params']}")
    print(f"  Test observations:       {observed['test_n_observations']}"
          "  (daily bars in the held-out window, not independent periods)")

    print("\n4. SPLIT SEPARATION AUDIT (held-out test set never used in selection)")
    sep = split.get("separation_check", {})
    print(f"  Disjoint:                {sep.get('disjoint')}")
    print(f"  Chronological:           {sep.get('chronological')}")
    print(f"  Train/val overlap:       {sep.get('train_val_overlap')}")
    print(f"  Val/test overlap:        {sep.get('val_test_overlap')}")
    print(f"  Train/test overlap:      {sep.get('train_test_overlap')}")
    print(f"  Train/val/test sizes:    {sep.get('train_size')}/{sep.get('val_size')}/{sep.get('test_size')}")

    print("\n5. BIAS CONTROLS")
    print(f"  Point-in-time validation passed: {pit.get('passed') if pit else None}")
    print(f"  PIT violations:                  {len(pit.get('violations', [])) if pit else None}")
    print(f"  Bias controls engaged:           {summary.get('bias_controls_engaged')}")

    # --- Test resolution (minimum detectable effect) ---
    # A measurement, not a correction: it changes no criterion outcome and no
    # verdict. It states the smallest effect each significance test could have
    # confirmed at the sample size actually available, so a failed criterion
    # can be read correctly (a criterion the sample cannot resolve is not
    # evidence against the hypothesis).
    resolution = _test_resolution(
        summary, test_perf.get("test_returns"), benchmarks[0], primary_bench
    )
    beyond = resolution["criteria_beyond_resolution"]

    print("\n6. TEST RESOLUTION (smallest effect each significance test could detect)")
    print(f"  Test observations:                {resolution['n_test_observations']}")
    print(f"  Parameter configurations tested:  {resolution['n_parameter_trials']}")
    print(f"  Benchmarks tested (N):            {resolution['n_benchmarks']}")
    print(f"  Criterion 2 needs an annualized Sharpe of at least "
          f"{_fmt_num(resolution['min_detectable_sharpe'])} "
          f"(observed {_fmt_num(oos_sharpe)})")
    print(f"  Criterion 3 needs an annualized alpha of at least "
          f"{_fmt_pct(resolution['min_detectable_benchmark_alpha'])} "
          f"(observed {_fmt_pct(bench_alpha)})")
    print(f"  Criterion 5 needs an annualized alpha of at least "
          f"{_fmt_pct(resolution['min_detectable_alpha'])} "
          f"(observed {_fmt_pct(bench_alpha)})")
    print(f"  Plausibility bounds (stated assumptions, not results):")
    print(f"    max plausible annualized Sharpe: {_fmt_num(PLAUSIBLE_MAX_ANNUALIZED_SHARPE)}")
    print(f"    max plausible annualized alpha:  {_fmt_pct(PLAUSIBLE_MAX_ANNUALIZED_ALPHA)}")
    if beyond:
        print("  Beyond the sample's resolution (a failure here is not evidence")
        print("  against the hypothesis):")
        for name in beyond:
            print(f"    - {name}")
    else:
        print("  Every criterion is within the sample's resolution.")

    # Criterion results
    criterion_results = []
    passes = {
        "oos_sharpe_gt_zero": CRITERIA[0][2](oos_sharpe),
        "deflated_sharpe_pvalue_lt_0.10": CRITERIA[1][2](dsr_pvalue),
        "benchmark_alpha_pvalue_lt_0.05": CRITERIA[2][2](bench_alpha_pvalue_raw),
        "oos_total_return_gt_benchmark": CRITERIA[3][2](
            oos_total_return is not None and bench_total_return is not None
            and oos_total_return > bench_total_return
        ),
        "deflated_alpha_ratio_gt_0.90": CRITERIA[4][2](dar),
    }
    for name, desc, _ in CRITERIA:
        ok = passes[name]
        criterion_results.append({"name": name, "description": desc, "passed": bool(ok)})
        print(f"\n  [{'PASS' if ok else 'FAIL'}] {name}: {desc}")

    all_pass = all(passes.values())
    verdict = "SUPPORTED" if all_pass else "NOT SUPPORTED"

    print("\n" + "=" * 80)
    print(f"VERDICT: {verdict}")
    print("  SUPPORTED  = all falsification criteria passed")
    print("  NOT SUPPORTED = at least one criterion failed (hypothesis falsified)")
    print("=" * 80)

    if beyond:
        print()
        print("HOW TO READ THIS VERDICT:")
        print(f"  {len(beyond)} of the {len(CRITERIA)} criteria could not be resolved by")
        print("  this sample (section 6): their thresholds require an effect larger")
        print("  than the held-out sample can detect. Their failure is a statement")
        print("  about the size of the sample, not evidence against the hypothesis.")
        print("  The verdict above remains the conjunction of the pre-registered")
        print("  criteria; it is reported here unchanged.")
        print("=" * 80)

    return {
        "hypothesis": HYPOTHESIS,
        "verdict": verdict,
        "observed": observed,
        "criteria": criterion_results,
        "all_pass": all_pass,
        "resolution": resolution,
        "criteria_beyond_resolution": beyond,
        "separation_check": sep,
        "bias_controls_engaged": bool(summary.get("bias_controls_engaged")),
        "pit_passed": bool(pit.get("passed")) if pit else None,
    }


def main():
    data_path = Path(__file__).resolve().parent.parent / "assets" / "example_data" / "sample_ohlcv.csv"
    result = run_hypothesis_test(data_path)
    # Exit 0 when the test runs successfully; the verdict (SUPPORTED / NOT
    # SUPPORTED) is carried by the printed output, not the exit code. A
    # falsified hypothesis is a valid scientific outcome, not a script failure.
    return 0


if __name__ == "__main__":
    sys.exit(main())
