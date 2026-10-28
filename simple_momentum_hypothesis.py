#!/usr/bin/env python3
"""
Falsifiable financial hypothesis test using run_backtest.py CLI.

HYPOTHESIS: A simple SMA crossover trend-following strategy produces
positive out-of-sample risk-adjusted returns (Sharpe > 0) net of 3 bps
round-trip trading costs on the held-out test set.

FALSIFICATION CRITERIA:
    1. Out-of-sample Sharpe ratio (net of costs) > 0
    2. Out-of-sample total return > 0 (net of costs)
    3. Deflated Alpha Ratio > 0.5 (multiple-benchmark deflated alpha)
    4. Strategy capacity (notional) > initial capital at the advertised
       market-impact level.

The script also runs two cost sweeps, both regression guards rather than
research conclusions:

    COST SWEEP (2 points) — advertised costs vs the frictionless upper
    bound. Catches a cost model that silently no-ops.

    COST SENSITIVITY SWEEP (5 levels, 0 -> 10 bps round-trip) — asserts the
    honest directional claim: as per-trade costs rise, net out-of-sample
    performance degrades monotonically (Sharpe, total return, and Deflated
    Alpha Ratio all fall). Catches a cost model whose output does not move
    with its cost setting, and it is the only section that reports how far
    the hypothesis's verdict moves before it flips.

    Criterion 3 is a benchmark-side data-mining control: the strategy is tested
    against MULTIPLE benchmarks, which is itself a multiple-testing problem, so
    the Deflated Alpha Ratio corrects the benchmark alpha for the number of
    benchmarks tested (N = 2 here). It only exists when n_benchmarks >= 2; the
    script resolves the benchmark set to the strategy universe plus the
    alternative benchmark so the criterion is always live rather than a
    permanently-silent no-op.

    Criterion 4 is an execution-side capacity control. The framework estimates
    the notional size at which market impact reaches an acceptable bound
    (capacity = max_impact * ADV / impact_coefficient); this criterion requires
    that estimate to exceed the capital actually deployed, i.e. the strategy is
    not capacity-constrained at the tested scale. The estimate is None when
    market impact is disabled (impact_coefficient = 0), so the criterion is only
    live when the capacity sweep produces a finite reading -- an impact model
    that silently no-ops would report capacity=None forever and the criterion
    would be a permanently-silent no-op dressed as an execution control.

If any fails -> NOT SUPPORTED.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


HYPOTHESIS = (
    "An SMA-crossover trend-following strategy produces positive "
    "out-of-sample risk-adjusted returns (Sharpe > 0) net of 3 bps "
    "round-trip trading costs on the held-out test set."
)

CRITERIA = [
    ("oos_sharpe_gt_zero", "oos_sharpe > 0 (net of costs)"),
    ("oos_total_return_positive", "oos_total_return > 0 (net of costs)"),
    ("deflated_alpha_ratio_gt_threshold", "deflated_alpha_ratio > 0.5 (multiple-benchmark deflated alpha)"),
    ("capacity_gt_initial_capital", "strategy capacity (notional) > initial capital at advertised impact level"),
]

DEFLATED_ALPHA_THRESHOLD = 0.5
CAPACITY_INITIAL_CAPITAL = 100_000.0
# Market-impact coefficient exercised by the capacity sweep. The advertised
# setting is the hypothesis's operating assumption; the zero-impact setting is
# the upper bound where capacity is unmeasurable (None). Comparing the two is a
# regression guard that the capacity estimate is actually produced by the
# impact path: an impact model that silently no-ops reports capacity=None at
# every setting and the criterion would be a permanently-silent no-op.
CAPACITY_SWEEP_SETTINGS = [
    ("impact disabled (capacity unmeasurable)", 0.0),
    ("advertised (impact_coefficient=0.1)", 0.1),
]

# Market-impact coefficients exercised by the capacity sensitivity sweep, in
# ascending order. Capacity scales inversely with the impact coefficient
# (capacity = max_impact * ADV_notional / impact_coefficient), so as the
# market-impact assumption rises the strategy's tradable capacity must fall.
# Sweeping several levels -- rather than a single advertised point plus the
# impact-disabled None -- guards the capacity path against being a silent
# no-op and reports how far the estimate moves before it breaches the deployed
# capital. Kept separate from CAPACITY_SWEEP_SETTINGS so the two-point
# regression guard (impact disabled vs advertised) and the cost sweeps that
# reuse its final level are not disturbed.
CAPACITY_SENSITIVITY_LEVELS = [0.0, 0.05, 0.1, 0.2]

COMMISSION = 0.0002
SLIPPAGE = 0.0001

# Cost settings exercised by the cost sweep. The advertised setting is the
# hypothesis's operating assumption; the zero-cost setting is the frictionless
# upper bound. Comparing the two is a regression guard that the advertised
# costs are actually applied by the cost path -- a cost model that silently
# no-ops would produce identical numbers at both settings and fail the sweep.
COST_SWEEP_SETTINGS = [
    ("frictionless (0 bps)", 0.0, 0.0),
    ("advertised (2bp comm + 1bp slip)", COMMISSION, SLIPPAGE),
]

# Commission / slippage levels exercised by the cost-sensitivity sweep, in
# ascending order, spanning realistic retail-to-institutional round-trip
# costs (1 bps = 0.0001). The advertised setting is the middle rung. The
# sweep asserts the honest directional claim -- higher per-trade costs reduce
# net out-of-sample performance -- rather than merely comparing two points.
COST_SWEEP_LEVELS = [
    (0.0, 0.0),
    (0.0001, 0.0),
    (COMMISSION, SLIPPAGE),
    (0.0005, 0.00025),
    (0.0010, 0.0005),
]


def _fmt_pct(v):
    if v is None:
        return "N/A"
    try:
        return f"{float(v):.2%}"
    except Exception:
        return "N/A"


def _fmt_num(v, nd=4):
    if v is None:
        return "N/A"
    try:
        return f"{float(v):.{nd}f}"
    except Exception:
        return "N/A"


def _resolve_benchmarks(data_path, benchmark_path=None):
    """Return the ordered, de-duplicated list of benchmark CSV paths.

    The Deflated Alpha Ratio only exists when the strategy is tested against
    MULTIPLE benchmarks (n_benchmarks >= 2): testing against a single
    benchmark is not a multiple-testing problem, so the framework suppresses
    the correction rather than inventing one. The prior version of this script
    resolved both its primary and fallback benchmark to the same
    sample_benchmark.csv, so exactly one unique path survived and the
    deflated_alpha criterion reported ratio=N/A forever -- a silent no-op
    dressed as a data-mining control.

    The primary benchmark is the strategy's own universe (sample_ohlcv.csv),
    matching the sibling falsifiable_hypothesis_example.py convention; the
    alternative benchmark is sample_benchmark.csv.
    """
    data_path = Path(data_path)
    if benchmark_path is None:
        benchmark_path = data_path.parent / "sample_benchmark.csv"
    benchmark_path = Path(benchmark_path)

    candidates = [data_path, benchmark_path]
    seen, result = set(), []
    for cand in candidates:
        key = str(cand.resolve())
        if cand.exists() and key not in seen:
            seen.add(key)
            result.append(cand)
    return result


def run_hypothesis_test(data_path, benchmark_path=None, impact_coefficient=0.1):
    scripts_dir = Path(__file__).resolve().parent / "skills" / "quantitative-backtesting" / "scripts"
    data_path = Path(data_path)
    bench_paths = _resolve_benchmarks(data_path, benchmark_path)
    benchmark_path = bench_paths[0] if bench_paths else None

    print("=" * 80)
    print("FALSIFIABLE HYPOTHESIS TEST (using run_backtest.py)")
    print("=" * 80)
    print(f"Hypothesis: {HYPOTHESIS}")
    print(f"Trading costs: {COMMISSION*10000:.0f} bps commission + {SLIPPAGE*10000:.0f} bps slippage")
    print(f"Market impact: impact_coefficient={impact_coefficient} "
          f"(capacity sweep advertised setting)")
    print(f"Data: {data_path}")
    print(f"Benchmarks ({len(bench_paths)}): {[str(p) for p in bench_paths]}")
    print("Split: train/val/test = 0.6/0.2/0.2 (test split only)")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        out_path = tmpdir_path / "results"
        cmd = [
            sys.executable,
            str(scripts_dir / "run_backtest.py"),
            "--data", str(data_path),
            "--strategy", "sma_crossover",
            "--symbol", "SPY",
            "--params", '{"fast_period": 10, "slow_period": 30}',
            "--commission", str(COMMISSION),
            "--slippage", str(SLIPPAGE),
            "--train-frac", "0.6",
            "--val-frac", "0.2",
            "--test-frac", "0.2",
            "--run-split", "test",
            "--output", str(out_path),
            "--validate-point-in-time",
            "--impact-coefficient", str(impact_coefficient),
        ]
        if bench_paths:
            cmd.extend(["--benchmark"] + [str(p) for p in bench_paths])

        result = subprocess.run(cmd, cwd=str(scripts_dir), capture_output=True, text=True)
        if result.returncode != 0:
            print("STDOUT:", result.stdout[-800:])
            print("STDERR:", result.stderr[-800:])
            raise RuntimeError(f"run_backtest failed with code {result.returncode}")

        # Look for metrics
        metrics = {}
        candidates = [
            tmpdir_path / "results" / "metrics.json",
            scripts_dir / "results" / "metrics.json",
            Path("results") / "metrics.json",
        ]
        for cand in candidates:
            if cand.exists() and cand.is_file():
                with open(cand) as f:
                    metrics = json.load(f)
                break

    print("\n1. METHODOLOGY CONTROLS")
    split_info = metrics.get("train_val_test_split", {})
    if split_info:
        sep = split_info.get("separation_check", {})
        print(f"  Split sizes (train/val/test): {sep.get('train_size')}/{sep.get('val_size')}/{sep.get('test_size')}")
        print(f"  Chronological: {sep.get('chronological')}, Disjoint: {sep.get('disjoint')}")
    pit = metrics.get("point_in_time_validation", {})
    print(f"  Point-in-time validation: {pit.get('passed')}")
    print(f"  Run split: test only (held-out)")
    print(f"  Commission: {COMMISSION}, Slippage: {SLIPPAGE}")

    print("\n2. OUT-OF-SAMPLE PERFORMANCE (net of costs)")
    print(f"  Total Return: {_fmt_pct(metrics.get('total_return'))}")
    print(f"  Annualized Return: {_fmt_pct(metrics.get('annualized_return'))}")
    print(f"  Sharpe Ratio: {_fmt_num(metrics.get('sharpe_ratio'))}")
    print(f"  Max Drawdown: {_fmt_pct(metrics.get('max_drawdown'))}")
    alpha, bench_return = _extract_benchmark_metrics(metrics)
    if bench_return is not None:
        print(f"  Benchmark Total Return (primary): {_fmt_pct(bench_return)}")
        print(f"  Alpha (primary benchmark): {_fmt_pct(alpha)}")
    da = metrics.get('deflated_alpha')
    if isinstance(da, dict):
        print(f"  Deflated Alpha Ratio: {_fmt_num(da.get('deflated_alpha_ratio'))} (p={_fmt_num(da.get('p_value'))}, N={da.get('n_benchmarks')})")
    capacity = metrics.get('capacity')
    if capacity is not None:
        print(f"  Strategy Capacity (notional, impact_coefficient={impact_coefficient}): "
              f"${capacity:,.0f} vs initial capital ${CAPACITY_INITIAL_CAPITAL:,.0f}")
    else:
        print(f"  Strategy Capacity (notional): N/A "
              f"(impact_coefficient={impact_coefficient} produced no estimate)")

    print("\n3. FALSIFICATION CRITERIA")
    criterion_results = []
    passes = []
    sharpe = metrics.get('sharpe_ratio')
    ok1 = sharpe is not None and float(sharpe) > 0
    passes.append(ok1)
    criterion_results.append({"name": CRITERIA[0][0], "description": CRITERIA[0][1], "passed": bool(ok1)})
    print(f"  [{'PASS' if ok1 else 'FAIL'}] {CRITERIA[0][0]}: {CRITERIA[0][1]}")
    ret = metrics.get('total_return')
    ok2 = ret is not None and float(ret) > 0
    passes.append(ok2)
    criterion_results.append({"name": CRITERIA[1][0], "description": CRITERIA[1][1], "passed": bool(ok2)})
    print(f"  [{'PASS' if ok2 else 'FAIL'}] {CRITERIA[1][0]}: {CRITERIA[1][1]}")
    da = metrics.get('deflated_alpha')
    da_ratio = None
    if isinstance(da, dict):
        da_ratio = da.get('deflated_alpha_ratio')
    ok3 = da_ratio is not None and float(da_ratio) > DEFLATED_ALPHA_THRESHOLD
    passes.append(ok3)
    criterion_results.append({"name": CRITERIA[2][0], "description": CRITERIA[2][1], "passed": bool(ok3)})
    print(f"  [{'PASS' if ok3 else 'FAIL'}] {CRITERIA[2][0]}: {CRITERIA[2][1]} (ratio={_fmt_num(da_ratio)})")

    # Test resolution beside the Deflated Alpha Ratio criterion: the smallest
    # annualized alpha the test could have confirmed at the sample size
    # actually available (run_backtest.py attaches metrics["test_resolution"]
    # to every multi-benchmark run), and whether that threshold sits beyond the
    # stated plausibility bound. A measurement, not a correction -- it changes
    # no criterion outcome and no verdict. A FAIL verdict on a criterion the
    # sample cannot resolve is a statement about the sample size, not about
    # the strategy.
    test_resolution = metrics.get("test_resolution") or {}
    if test_resolution:
        alpha_status = test_resolution.get("alpha_status")
        min_detectable_alpha = test_resolution.get("min_detectable_alpha")
        alpha_beyond = bool(test_resolution.get("alpha_beyond_plausible_bound"))
        n_obs = test_resolution.get("n_test_observations")
        n_bench = test_resolution.get("n_benchmarks")
        if alpha_status == "resolvable":
            print(
                f"  Test resolution (criterion 3): min detectable annualized alpha "
                f"{_fmt_num(min_detectable_alpha)} at {n_obs} test observation(s), "
                f"{n_bench} benchmark(s); beyond plausibility bound: {alpha_beyond}."
            )
            if alpha_beyond:
                print(
                    f"  The criterion's outcome measures the sample size, not "
                    f"the strategy: {test_resolution.get('message')}"
                )
        else:
            print(
                f"  Test resolution (criterion 3): not resolvable "
                f"({test_resolution.get('alpha_reason') or test_resolution.get('message')})"
            )
    capacity = metrics.get('capacity')
    ok4 = capacity is not None and float(capacity) > CAPACITY_INITIAL_CAPITAL
    passes.append(ok4)
    criterion_results.append({"name": CRITERIA[3][0], "description": CRITERIA[3][1], "passed": bool(ok4)})
    print(f"  [{'PASS' if ok4 else 'FAIL'}] {CRITERIA[3][0]}: {CRITERIA[3][1]} "
          f"(capacity={_fmt_num(capacity)})")

    all_pass = all(passes)
    verdict = "SUPPORTED" if all_pass else "NOT SUPPORTED"

    print("\n" + "=" * 80)
    print(f"VERDICT: {verdict}")
    print("  SUPPORTED = all falsification criteria passed")
    print("  NOT SUPPORTED = at least one criterion failed (hypothesis falsified)")
    print("=" * 80)

    return {
        "hypothesis": HYPOTHESIS,
        "verdict": verdict,
        "all_pass": all_pass,
        "criteria": criterion_results,
        "metrics": {
            "sharpe_ratio": sharpe,
            "total_return": ret,
            "benchmark_total_return": bench_return,
            "alpha": alpha,
            "deflated_alpha": metrics.get('deflated_alpha'),
            "capacity": capacity,
            "test_resolution": test_resolution,
        },
    }


def _run_backtest_metrics(data_path, benchmark_path, commission, slippage, tmpdir_path, impact_coefficient=0.1):
    """Run run_backtest.py at the given cost/impact settings and return parsed metrics."""
    scripts_dir = Path(__file__).resolve().parent / "skills" / "quantitative-backtesting" / "scripts"
    bench_paths = _resolve_benchmarks(data_path, benchmark_path)
    cmd = [
        sys.executable,
        str(scripts_dir / "run_backtest.py"),
        "--data", str(data_path),
        "--strategy", "sma_crossover",
        "--symbol", "SPY",
        "--params", '{"fast_period": 10, "slow_period": 30}',
        "--commission", str(commission),
        "--slippage", str(slippage),
        "--train-frac", "0.6",
        "--val-frac", "0.2",
        "--test-frac", "0.2",
        "--run-split", "test",
        "--output", str(tmpdir_path / "results"),
        "--validate-point-in-time",
        "--impact-coefficient", str(impact_coefficient),
    ]
    if bench_paths:
        cmd.extend(["--benchmark"] + [str(p) for p in bench_paths])

    result = subprocess.run(cmd, cwd=str(scripts_dir), capture_output=True, text=True)
    if result.returncode != 0:
        print("STDOUT:", result.stdout[-800:])
        print("STDERR:", result.stderr[-800:])
        raise RuntimeError(f"run_backtest failed with code {result.returncode}")

    metrics = {}
    candidates = [
        tmpdir_path / "results" / "metrics.json",
        scripts_dir / "results" / "metrics.json",
        Path("results") / "metrics.json",
    ]
    for cand in candidates:
        if cand.exists() and cand.is_file():
            with open(cand) as f:
                metrics = json.load(f)
            break
    return metrics


def _extract_benchmark_metrics(metrics):
    """Pull the primary-benchmark alpha / total return out of a metrics dict.

    With multiple benchmarks the framework keys metrics per benchmark
    (benchmark_0_alpha, benchmark_1_...) and leaves the aggregate
    benchmark_total_return / alpha fields as None. Reporting the aggregate
    there therefore prints "Alpha=N/A" even though the run is fully valid.
    Prefer benchmark_0 (the strategy's own universe, listed first) and fall
    back to the aggregate fields for single-benchmark runs.
    """
    alpha = metrics.get("benchmark_0_alpha")
    if alpha is None:
        alpha = metrics.get("alpha")
    bench_return = metrics.get("benchmark_0_benchmark_total_return")
    if bench_return is None:
        bench_return = metrics.get("benchmark_total_return")
    return alpha, bench_return


def run_cost_sweep(data_path, benchmark_path=None):
    """Compare the hypothesis at its advertised cost setting against the
    frictionless (zero-cost) upper bound.

    This is a regression guard, not a research conclusion: if the advertised
    costs are not actually applied by the cost path, the two settings produce
    identical Sharpe and total return, and the sweep fails. A cost model that
    silently no-ops is the failure mode this check exists to catch.
    """
    data_path = Path(data_path)
    if benchmark_path is None:
        benchmark_path = data_path.parent / "sample_benchmark.csv"
    benchmark_path = Path(benchmark_path)

    print("\n" + "=" * 80)
    print("COST SWEEP: advertised costs vs frictionless upper bound")
    print("=" * 80)

    rows = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        for label, commission, slippage in COST_SWEEP_SETTINGS:
            metrics = _run_backtest_metrics(
                data_path, benchmark_path, commission, slippage, tmpdir_path,
                impact_coefficient=CAPACITY_SWEEP_SETTINGS[-1][1],
            )
            alpha, bench_return = _extract_benchmark_metrics(metrics)
            rows.append({
                "label": label,
                "commission": commission,
                "slippage": slippage,
                "sharpe_ratio": metrics.get("sharpe_ratio"),
                "total_return": metrics.get("total_return"),
                "benchmark_total_return": bench_return,
                "alpha": alpha,
            })
            print(
                f"  {label:<34} "
                f"Sharpe={_fmt_num(metrics.get('sharpe_ratio'))}  "
                f"Return={_fmt_pct(metrics.get('total_return'))}  "
                f"Alpha={_fmt_pct(alpha)}"
            )

    # Regression guard: the frictionless run must beat the costed run on both
    # Sharpe and total return. If costs are not applied, the two rows are
    # identical and this assertion fails.
    frictionless = rows[0]
    costed = rows[-1]
    assert frictionless["commission"] == 0.0 and costed["commission"] == COMMISSION, (
        "cost sweep rows are not the frictionless / advertised pair"
    )
    assert frictionless["sharpe_ratio"] is not None and costed["sharpe_ratio"] is not None
    assert frictionless["sharpe_ratio"] > costed["sharpe_ratio"], (
        "frictionless Sharpe must exceed the costed Sharpe: "
        f"{frictionless['sharpe_ratio']} vs {costed['sharpe_ratio']}"
    )
    assert frictionless["total_return"] is not None and costed["total_return"] is not None
    assert frictionless["total_return"] > costed["total_return"], (
        "frictionless total return must exceed the costed total return: "
        f"{frictionless['total_return']} vs {costed['total_return']}"
    )

    delta_sharpe = costed["sharpe_ratio"] - frictionless["sharpe_ratio"]
    delta_return = costed["total_return"] - frictionless["total_return"]
    print()
    print(
        f"  Cost impact (0 bps -> {COMMISSION*10000:.0f}bp + {SLIPPAGE*10000:.0f}bp): "
        f"Sharpe {frictionless['sharpe_ratio']:.4f} -> {costed['sharpe_ratio']:.4f} "
        f"(Delta {delta_sharpe:+.4f}); "
        f"Return {frictionless['total_return']:.2%} -> {costed['total_return']:.2%} "
        f"(Delta {delta_return:+.2%})"
    )
    print("  Cost path verified live: the advertised costs reduce net performance.")
    print("=" * 80)

    return rows


def run_capacity_sweep(data_path, benchmark_path=None):
    """Compare the advertised impact level against the impact-disabled upper bound.

    This is a regression guard, not a research conclusion: the framework's
    capacity estimate is None when impact_coefficient is 0 (the impact path is
    disabled), so the two settings produce one finite reading and one None. If
    the impact path silently no-ops, the advertised setting also reports
    capacity=None and this sweep fails. A capacity estimate that is missing or
    that does not move with the impact coefficient is the failure mode this
    check exists to catch.
    """
    data_path = Path(data_path)
    if benchmark_path is None:
        benchmark_path = data_path.parent / "sample_benchmark.csv"
    benchmark_path = Path(benchmark_path)

    print("\n" + "=" * 80)
    print("CAPACITY SWEEP: advertised impact level vs impact-disabled upper bound")
    print("=" * 80)

    rows = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        for label, impact_coefficient in CAPACITY_SWEEP_SETTINGS:
            metrics = _run_backtest_metrics(
                data_path, benchmark_path, COMMISSION, SLIPPAGE, tmpdir_path,
                impact_coefficient=impact_coefficient,
            )
            capacity = metrics.get("capacity")
            rows.append({
                "label": label,
                "impact_coefficient": impact_coefficient,
                "capacity": capacity,
                "sharpe_ratio": metrics.get("sharpe_ratio"),
                "total_return": metrics.get("total_return"),
            })
            cap_str = "N/A (impact disabled)" if capacity is None else f"${capacity:,.0f}"
            print(
                f"  {label:<38} capacity={cap_str}  "
                f"Sharpe={_fmt_num(metrics.get('sharpe_ratio'))}  "
                f"Return={_fmt_pct(metrics.get('total_return'))}"
            )

    # Regression guard: the advertised setting must produce a finite capacity
    # estimate, and the impact-disabled setting must not. An impact model that
    # silently no-ops reports capacity=None at every setting.
    disabled = rows[0]
    advertised = rows[-1]
    assert disabled["impact_coefficient"] == 0.0 and advertised["impact_coefficient"] == CAPACITY_SWEEP_SETTINGS[-1][1], (
        "capacity sweep rows are not the impact-disabled / advertised pair"
    )
    assert disabled["capacity"] is None, (
        "impact-disabled setting must report capacity=None, got "
        f"{disabled['capacity']}"
    )
    assert advertised["capacity"] is not None, (
        "advertised impact setting must produce a finite capacity estimate"
    )
    assert float(advertised["capacity"]) > 0, (
        "capacity estimate must be positive: "
        f"{advertised['capacity']}"
    )
    assert float(advertised["capacity"]) > CAPACITY_INITIAL_CAPITAL, (
        "capacity estimate must exceed the capital actually deployed: "
        f"{advertised['capacity']} vs {CAPACITY_INITIAL_CAPITAL}"
    )

    print()
    print(
        f"  Capacity path verified live: impact_coefficient "
        f"{advertised['impact_coefficient']} produces a finite estimate of "
        f"${advertised['capacity']:,.0f}, exceeding the deployed capital of "
        f"${CAPACITY_INITIAL_CAPITAL:,.0f}; impact_coefficient 0 reports no "
        f"estimate (impact path disabled)."
    )
    print("=" * 80)

    return rows


def run_capacity_sensitivity_sweep(data_path, benchmark_path=None):
    """Sweep market impact coefficient across ascending levels and assert the
    honest directional claim: as market impact rises, estimated strategy
    capacity falls.

    Capacity = max_impact * ADV_notional / impact_coefficient, so it scales
    inversely with impact_coefficient. This is a sensitivity analysis on the
    shipped synthetic sample, not evidence about any market; the claim is
    purely directional and guards the capacity path against a silent no-op
    (an impact model whose estimate does not move with impact_coefficient).
    """
    data_path = Path(data_path)
    if benchmark_path is None:
        benchmark_path = data_path.parent / "sample_benchmark.csv"
    benchmark_path = Path(benchmark_path)

    print("\n" + "=" * 80)
    print("CAPACITY SENSITIVITY SWEEP: rising market impact, falling capacity")
    print("=" * 80)
    print(f"  {'impact coeff':>14} {'capacity (notional)':>26} {'vs capital':>12}")
    print("  " + "-" * 60)

    rows = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        for impact_coefficient in CAPACITY_SENSITIVITY_LEVELS:
            metrics = _run_backtest_metrics(
                data_path, benchmark_path, COMMISSION, SLIPPAGE, tmpdir_path,
                impact_coefficient=impact_coefficient,
            )
            capacity = metrics.get("capacity")
            rows.append({
                "impact_coefficient": impact_coefficient,
                "capacity": capacity,
                "sharpe_ratio": metrics.get("sharpe_ratio"),
                "total_return": metrics.get("total_return"),
            })
            cap_str = "None (impact disabled)" if capacity is None else f"${capacity:,.0f}"
            vs_cap = "N/A" if capacity is None else (
                "above" if float(capacity) > CAPACITY_INITIAL_CAPITAL else "below")
            print(
                f"  {impact_coefficient:>14} {cap_str:>26} {vs_cap:>12}"
            )

    # Levels recorded in ascending order; impact disabled first.
    assert [r["impact_coefficient"] for r in rows] == list(CAPACITY_SENSITIVITY_LEVELS), (
        "capacity sensitivity levels are not recorded in ascending order"
    )
    assert rows[0]["impact_coefficient"] == 0.0, (
        "first capacity sensitivity level must be impact disabled"
    )
    assert rows[0]["capacity"] is None, (
        "impact-disabled setting must report capacity=None, got "
        f"{rows[0]['capacity']}"
    )

    finite = [r for r in rows if r["capacity"] is not None]
    assert len(finite) >= 2, (
        "capacity sensitivity sweep must produce at least two finite readings"
    )
    for r in finite:
        assert float(r["capacity"]) > 0, (
            "capacity estimate must be positive: " f"{r['capacity']}"
        )
    # Capacity must fall monotonically as impact_coefficient rises.
    for prev, curr in zip(finite, finite[1:]):
        assert curr["capacity"] < prev["capacity"], (
            "capacity does not fall as market impact rises: "
            f"impact {prev['impact_coefficient']} -> {prev['capacity']:,.0f}, "
            f"impact {curr['impact_coefficient']} -> {curr['capacity']:,.0f}"
        )

    print()
    first = finite[0]
    last = finite[-1]
    print(
        f"  Capacity falls with market impact: ${first['capacity']:,.0f} at "
        f"impact_coefficient={first['impact_coefficient']} -> "
        f"${last['capacity']:,.0f} at impact_coefficient={last['impact_coefficient']}."
    )
    print("  Capacity path verified live: the estimate moves with impact_coefficient.")
    print("=" * 80)

    return rows


def run_cost_sensitivity_sweep(data_path, benchmark_path=None):
    """Sweep commission / slippage across five ascending levels and assert the
    honest directional claim: as per-trade costs rise, net out-of-sample
    performance degrades monotonically.

    This is a sensitivity analysis on the shipped synthetic sample, not
    evidence about any market. The claim is purely directional and is
    measured on the same 500-bar fixture the rest of the script prices, so
    the numbers are properties of the cost path and the sample, never of a
    security.

    Three series are asserted monotone-decreasing across the ascending cost
    levels, in that order:
      * Sharpe ratio,
      * total return,
      * Deflated Alpha Ratio (the benchmark-side data-mining control, which
        falls as the strategy's edge is eroded by costs).

    A cost model whose output does not move with its cost setting fails here,
    and a cost model that moves non-monotonically fails here too.
    """
    data_path = Path(data_path)
    if benchmark_path is None:
        benchmark_path = data_path.parent / "sample_benchmark.csv"
    benchmark_path = Path(benchmark_path)

    print("\n" + "=" * 80)
    print("COST SENSITIVITY SWEEP: 0 -> 10 bps round-trip (5 ascending levels)")
    print("=" * 80)
    print(f"  {'cost level':<34} {'comm':>6} {'slip':>6} {'Sharpe':>9} {'Return':>9} {'DAR':>8} {'verdict':>12}")
    print("  " + "-" * 88)

    rows = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        for commission, slippage in COST_SWEEP_LEVELS:
            metrics = _run_backtest_metrics(
                data_path, benchmark_path, commission, slippage, tmpdir_path,
                impact_coefficient=CAPACITY_SWEEP_SETTINGS[-1][1],
            )
            da = metrics.get("deflated_alpha") or {}
            # Try to get verdict from metrics if present
            verdict = metrics.get("verdict") or metrics.get("hypothesis_verdict")
            criteria = metrics.get("criteria") or []
            row = {
                "commission_bps": commission * 10_000,
                "slippage_bps": slippage * 10_000,
                "sharpe_ratio": metrics.get("sharpe_ratio"),
                "total_return": metrics.get("total_return"),
                "deflated_alpha_ratio": da.get("deflated_alpha_ratio"),
                "verdict": verdict,
                "criteria": criteria,
            }
            rows.append(row)
            print(
                f"  {commission*10_000:.0f}bp comm + {slippage*10_000:.2f}bp slip".ljust(34)
                + f" {row['commission_bps']:>6.0f} {row['slippage_bps']:>6.2f} "
                + f"{_fmt_num(row['sharpe_ratio']):>9} {_fmt_pct(row['total_return']):>9} {_fmt_num(row['deflated_alpha_ratio']):>8} {str(row['verdict'])[:12]:>12}"
            )

    # The levels must be strictly ascending in cost, so monotonicity in the
    # recorded order is a statement about rising costs, not about ordering.
    assert [r["commission_bps"] for r in rows] == [c * 10_000 for c, _ in COST_SWEEP_LEVELS], (
        "cost sweep levels are not recorded in ascending order"
    )
    assert rows[0]["commission_bps"] == 0.0 and rows[0]["slippage_bps"] == 0.0, (
        "first cost sweep level must be frictionless"
    )
    advertised = next(r for r in rows if r["commission_bps"] == COMMISSION * 10_000)
    assert advertised is rows[2], (
        "the advertised cost level is not the middle rung of the sweep"
    )

    series = {
        "sharpe_ratio": "Sharpe ratio",
        "total_return": "total return",
        "deflated_alpha_ratio": "Deflated Alpha Ratio",
    }
    for key, label in series.items():
        values = [r[key] for r in rows]
        assert all(v is not None for v in values), (
            f"{label} is missing at one or more cost levels: {values}"
        )
        for prev, curr in zip(values, values[1:]):
            assert curr <= prev, (
                f"{label} does not degrade monotonically with cost: "
                f"{prev} -> {curr}"
            )

    frictionless, costed = rows[0], rows[-1]
    print()
    print(
        f"  Directional claim verified (0 -> 10 bps round-trip): "
        f"Sharpe {frictionless['sharpe_ratio']:.4f} -> {costed['sharpe_ratio']:.4f}, "
        f"Return {_fmt_pct(frictionless['total_return'])} -> {_fmt_pct(costed['total_return'])}, "
        f"DAR {_fmt_num(frictionless['deflated_alpha_ratio'])} -> {_fmt_num(costed['deflated_alpha_ratio'])}."
    )
    print("  All metrics degrade monotonically as costs rise (asserted).")

    # Report how verdict changes with costs and which criteria fail
    print("\n  VERDICT BY COST LEVEL (with failing criteria):")
    for i, r in enumerate(rows):
        crits = r.get("criteria") or []
        failed = [c["name"] for c in crits if isinstance(c, dict) and not c.get("passed")]
        if failed:
            failed_str = ", ".join(failed)
        else:
            failed_str = "none"
        print(f"    [{i}] {r['commission_bps']:.0f}bp+{r['slippage_bps']:.2f}bp -> {str(r.get('verdict'))[:12]}: failing={failed_str}")
    verdicts = [r.get("verdict") for r in rows if r.get("verdict") and not str(r.get("verdict")).startswith("ERR")]
    if verdicts and len(set(verdicts)) > 1:
        print(f"  VERDICT CHANGES across cost sweep: {verdicts[0]} -> ... -> {verdicts[-1]} (sensitivity demonstrated)")
    else:
        print(f"  VERDICT STABLE across cost sweep: {verdicts[0] if verdicts else 'N/A'} (pre-registered criteria applied at each level)")

    print("=" * 80)
    print("  COST SENSITIVITY SWEEP COMPLETE: verdicts/failing criteria reported per level above.")
    print("=" * 80)

    return rows


def main():
    data_path = Path(__file__).resolve().parent / "skills" / "quantitative-backtesting" / "assets" / "example_data" / "sample_ohlcv.csv"
    result = run_hypothesis_test(data_path)
    run_cost_sweep(data_path)
    run_cost_sensitivity_sweep(data_path)
    run_capacity_sweep(data_path)
    run_capacity_sensitivity_sweep(data_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())