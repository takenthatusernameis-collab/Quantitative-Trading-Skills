#!/usr/bin/env python3
"""
Falsifiable financial hypothesis test using run_backtest.py CLI.

HYPOTHESIS: An RSI mean-reversion strategy produces positive
out-of-sample risk-adjusted returns (Sharpe > 0) net of 3 bps
round-trip trading costs on the held-out test set.

FALSIFICATION CRITERIA:
1. Out-of-sample Sharpe ratio (net of costs) > 0
2. Out-of-sample total return > 0 (net of costs)
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path


HYPOTHESIS = (
    "An RSI mean-reversion strategy produces positive "
    "out-of-sample risk-adjusted returns (Sharpe > 0) net of 3 bps "
    "round-trip trading costs on the held-out test set."
)

CRITERIA = [
    ("oos_sharpe_gt_zero", "oos_sharpe > 0 (net of costs)"),
    ("oos_total_return_positive", "oos_total_return > 0 (net of costs)"),
]

COMMISSION = 0.0002
SLIPPAGE = 0.0001

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


def _resolve_benchmarks(data_path, benchmark_path=None):
    """Return the ordered, de-duplicated list of benchmark CSV paths.

    The Deflated Alpha Ratio only exists when the strategy is tested against
    MULTIPLE benchmarks (n_benchmarks >= 2): testing against a single
    benchmark is not a multiple-testing problem, so the framework suppresses
    the correction rather than inventing one. Both the strategy universe and
    the alternative benchmark are passed so the correction is engaged.
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


def _extract_benchmark_metrics(metrics):
    """Pull the primary-benchmark alpha / total return out of a metrics dict.

    With multiple benchmarks the framework keys metrics per benchmark
    (benchmark_0_alpha, benchmark_1_...) and leaves the aggregate
    benchmark_total_return / alpha fields as None. Prefer benchmark_0 (the
    strategy's own universe, listed first) and fall back to the aggregate
    fields for single-benchmark runs.
    """
    alpha = metrics.get("benchmark_0_alpha")
    if alpha is None:
        alpha = metrics.get("alpha")
    bench_return = metrics.get("benchmark_0_benchmark_total_return")
    if bench_return is None:
        bench_return = metrics.get("benchmark_total_return")
    return alpha, bench_return


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


def run_hypothesis_test(data_path, benchmark_path=None):
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    data_path = Path(data_path)
    if benchmark_path is None:
        benchmark_path = data_path.parent / "sample_benchmark.csv"
    benchmark_path = Path(benchmark_path)

    print("=" * 80)
    print("FALSIFIABLE HYPOTHESIS TEST (using run_backtest.py)")
    print("=" * 80)
    print(f"Hypothesis: {HYPOTHESIS}")
    print(f"Trading costs: {COMMISSION*10000:.0f} bps commission + {SLIPPAGE*10000:.0f} bps slippage")
    print(f"Data: {data_path}")
    print(f"Benchmark: {benchmark_path if benchmark_path.exists() else 'None'}")
    print("Split: train/val/test = 0.6/0.2/0.2 (test split only)")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        out_path = tmpdir_path / "metrics.json"
        cmd = [
            sys.executable,
            str(scripts_dir / "run_backtest.py"),
            "--data", str(data_path),
            "--strategy", "rsi_mean_reversion",
            "--symbol", "SPY",
            "--params", '{"period": 14, "oversold": 30, "overbought": 70, "neutral": 50}',
            "--commission", str(COMMISSION),
            "--slippage", str(SLIPPAGE),
            "--train-frac", "0.6",
            "--val-frac", "0.2",
            "--test-frac", "0.2",
            "--run-split", "test",
            "--output", str(tmpdir_path / "results"),
            "--validate-point-in-time",
        ]
        if benchmark_path.exists():
            cmd.extend(["--benchmark", str(benchmark_path)])

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
    if metrics.get('benchmark_total_return') is not None:
        print(f"  Benchmark Total Return: {_fmt_pct(metrics.get('benchmark_total_return'))}")
        print(f"  Alpha: {_fmt_pct(metrics.get('alpha'))}")

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

    all_pass = all(passes)
    verdict = "SUPPORTED" if all_pass else "NOT SUPPORTED"

    print("\n" + "=" * 80)
    print(f"VERDICT: {verdict}")
    print("  SUPPORTED = all falsification criteria passed")
    print("  NOT SUPPORTED = at least one criterion failed (hypothesis falsified)")
    print("=" * 80)

    # Cost sweep (regression guard, not a research conclusion): report the
    # verdict at each ascending cost level and assert the honest directional
    # claim -- higher per-trade costs never improve net performance.
    cost_rows = run_cost_sweep(data_path, benchmark_path)

    return {
        "hypothesis": HYPOTHESIS,
        "verdict": verdict,
        "all_pass": all_pass,
        "criteria": criterion_results,
        "cost_sweep": cost_rows,
        "metrics": {
            "sharpe_ratio": sharpe,
            "total_return": ret,
            "benchmark_total_return": metrics.get('benchmark_total_return'),
            "alpha": metrics.get('alpha'),
        },
    }


def _run_backtest_metrics(data_path, benchmark_path, commission, slippage, tmpdir_path):
    """Run run_backtest.py once at the given cost setting and return metrics."""
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    bench_paths = _resolve_benchmarks(data_path, benchmark_path)
    cmd = [
        sys.executable,
        str(scripts_dir / "run_backtest.py"),
        "--data", str(data_path),
        "--strategy", "rsi_mean_reversion",
        "--symbol", "SPY",
        "--params", '{"period": 14, "oversold": 30, "overbought": 70, "neutral": 50}',
        "--commission", str(commission),
        "--slippage", str(slippage),
        "--train-frac", "0.6",
        "--val-frac", "0.2",
        "--test-frac", "0.2",
        "--run-split", "test",
        "--output", str(tmpdir_path / "results"),
        "--validate-point-in-time",
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


def run_cost_sweep(data_path, benchmark_path=None):
    """Sweep commission / slippage across ascending levels and report an
    explicit falsification verdict at each level.

    Reports how the verdict changes as transaction costs rise, with the
    failing criteria shown per level. This is a sensitivity analysis on the
    shipped sample, not evidence about any market. The claim is purely
    directional: higher per-trade costs must never improve net performance.
    """
    data_path = Path(data_path)
    if benchmark_path is None:
        benchmark_path = data_path.parent / "sample_benchmark.csv"
    benchmark_path = Path(benchmark_path)

    print("\n" + "=" * 80)
    print("COST SENSITIVITY SWEEP: ascending costs (falsifiable criteria)")
    print("=" * 80)
    print(f"  {'cost level':<36} {'comm':>6} {'slip':>6} {'Sharpe':>9} {'Return':>9} {'verdict':>12}")
    print("  " + "-" * 90)

    rows = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        for commission, slippage in COST_SWEEP_LEVELS:
            metrics = _run_backtest_metrics(data_path, benchmark_path, commission, slippage, tmpdir_path)
            sharpe = metrics.get("sharpe_ratio")
            ret = metrics.get("total_return")
            ok1 = sharpe is not None and float(sharpe) > 0
            ok2 = ret is not None and float(ret) > 0
            passes = {"oos_sharpe_gt_zero": bool(ok1), "oos_total_return_positive": bool(ok2)}
            failed = [name for name, ok in passes.items() if not ok]
            verdict = "SUPPORTED" if all(passes.values()) else "NOT SUPPORTED"
            rows.append({
                "commission": commission,
                "slippage": slippage,
                "commission_bps": commission * 10_000,
                "slippage_bps": slippage * 10_000,
                "sharpe_ratio": sharpe,
                "total_return": ret,
                "criteria": [{"name": name, "passed": ok} for name, ok in passes.items()],
                "verdict": verdict,
                "all_pass": all(passes.values()),
            })
            print(
                f"  {commission*10_000:.0f}bp comm + {slippage*10_000:.2f}bp slip".ljust(36)
                + f" {commission*10_000:>6.0f} {slippage*10_000:>6.2f} "
                + f"{_fmt_num(sharpe):>9} {_fmt_pct(ret):>9} {verdict[:12]:>12}"
            )

    assert [r["commission_bps"] for r in rows] == [c * 10_000 for c, _ in COST_SWEEP_LEVELS], (
        "cost sweep levels not recorded in ascending order"
    )
    assert rows[0]["commission_bps"] == 0.0 and rows[0]["slippage_bps"] == 0.0, (
        "first cost sweep level must be frictionless"
    )
    advertised = next(r for r in rows if r["commission_bps"] == COMMISSION * 10_000)
    assert advertised is rows[2], (
        "the advertised cost level is not the middle rung of the sweep"
    )

    # Monotonic degradation where values are finite: higher costs never improve
    # net Sharpe or net total return.
    for key, label in (("sharpe_ratio", "Sharpe ratio"), ("total_return", "total return")):
        values = [r[key] for r in rows]
        for prev, curr in zip(values, values[1:]):
            if prev is not None and curr is not None:
                assert curr <= prev + 1e-12, (
                    f"{label} does not degrade monotonically with cost: "
                    f"{prev} -> {curr}"
                )

    frictionless = rows[0]
    costed = rows[-1]
    print()
    if frictionless["sharpe_ratio"] is not None and costed["sharpe_ratio"] is not None:
        print(
            f"  Directional claim: Sharpe {frictionless['sharpe_ratio']:.4f} -> {costed['sharpe_ratio']:.4f}, "
            f"Return {_fmt_pct(frictionless['total_return'])} -> {_fmt_pct(costed['total_return'])}."
        )

    # Report how verdict changes with costs and which criteria fail at each level.
    print("\n  VERDICT BY COST LEVEL (with failing criteria):")
    for i, r in enumerate(rows):
        failed = [c["name"] for c in r["criteria"] if not c["passed"]]
        failed_str = ", ".join(failed) if failed else "none"
        print(f"    [{i}] {r['commission_bps']:.0f}bp+{r['slippage_bps']:.2f}bp -> {r['verdict']}: failing={failed_str}")
    verdicts = [r["verdict"] for r in rows]
    if len(set(verdicts)) > 1:
        print(f"  VERDICT CHANGES across cost sweep: {verdicts[0]} -> ... -> {verdicts[-1]} (sensitivity demonstrated)")
    else:
        print(f"  VERDICT STABLE across cost sweep: {verdicts[0]} (pre-registered criteria applied at each level)")

    print("  Costs sweep completed with directional sensitivity observed.")
    print("=" * 80)

    return rows


def main():
    data_path = Path(__file__).resolve().parent.parent / "assets" / "example_data" / "sample_ohlcv.csv"
    result = run_hypothesis_test(data_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
