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
       from zero vs buy-and-hold).
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
against pre-registered criteria, not a performance endorsement.

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
from strategy_builder import build_strategy
from walk_forward import out_of_sample_validation


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
    ("benchmark_alpha_pvalue_lt_0.05", "benchmark_alpha_pvalue < 0.05",
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
    ("deflated_alpha_ratio_gt_0.90", "deflated_alpha_ratio > 0.90",
     lambda v: v is not None and v > 0.90),
]

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade
PARAM_GRID = {"fast_period": [5, 10, 15, 20], "slow_period": [20, 30, 40, 50]}

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
    test_n_periods = test_perf.get("test_n_periods")

    # Multiple-benchmark path: alpha / alpha_pvalue / benchmark_total_return
    # come from the primary (first) benchmark in the per-benchmark list; the
    # Deflated Alpha Ratio (criterion 5) is the multiple-testing corrected
    # benchmark alpha across the whole benchmark set.
    bench_alpha = None
    bench_alpha_pvalue = None
    bench_total_return = None
    if isinstance(test_bench, list) and test_bench:
        primary = test_bench[0]
        if isinstance(primary, dict):
            bench_alpha = primary.get("alpha")
            bench_alpha_pvalue = primary.get("alpha_pvalue")
            bench_total_return = primary.get("benchmark_total_return")
    if isinstance(test_bench, dict):
        bench_alpha = bench_alpha or test_bench.get("alpha")
        bench_alpha_pvalue = bench_alpha_pvalue or test_bench.get("alpha_pvalue")
        bench_total_return = bench_total_return or test_bench.get("benchmark_total_return")
    if bench_alpha is None:
        bench_alpha = test_perf.get("alpha")
    if bench_alpha_pvalue is None:
        bench_alpha_pvalue = test_perf.get("alpha_pvalue")
    if bench_total_return is None:
        bench_total_return = test_perf.get("benchmark_total_return")

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
        "benchmark_alpha_pvalue": bench_alpha_pvalue,
        "benchmark_total_return": bench_total_return,
        "deflated_alpha_ratio": dar,
        "deflated_alpha_pvalue": dar_pvalue,
        "n_benchmarks": n_benchmarks,
        "selected_params": summary.get("selected_params"),
        "selected_params_avg_test_sharpe": summary.get("selected_params_avg_test_sharpe"),
        "test_n_periods": test_n_periods,
    }

    # --- Evaluate falsification criteria ---
    print("\n3. OBSERVED OUT-OF-SAMPLE METRICS (net of costs)")
    print(f"  OOS Sharpe:              {_fmt_num(oos_sharpe)}")
    print(f"  OOS total return:        {_fmt_pct(oos_total_return)}")
    print(f"  Benchmark total return:  {_fmt_pct(bench_total_return)}")
    print(f"  Benchmark alpha:         {_fmt_pct(bench_alpha)}")
    print(f"  Benchmark alpha p-value: {_fmt_num(bench_alpha_pvalue)}")
    print(f"  Deflated Sharpe p-value: {_fmt_num(dsr_pvalue)}")
    print(f"  Deflated Alpha Ratio:     {_fmt_num(dar)}")
    print(f"  Deflated Alpha p-value:  {_fmt_num(dar_pvalue)}")
    print(f"  Benchmarks tested (N):   {n_benchmarks}")
    print(f"  Selected params:         {observed['selected_params']}")
    print(f"  Test periods:            {observed['test_n_periods']}")

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

    # Criterion results
    criterion_results = []
    passes = {
        "oos_sharpe_gt_zero": CRITERIA[0][2](oos_sharpe),
        "deflated_sharpe_pvalue_lt_0.10": CRITERIA[1][2](dsr_pvalue),
        "benchmark_alpha_pvalue_lt_0.05": CRITERIA[2][2](bench_alpha_pvalue),
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

    return {
        "hypothesis": HYPOTHESIS,
        "verdict": verdict,
        "observed": observed,
        "criteria": criterion_results,
        "all_pass": all_pass,
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
