#!/usr/bin/env python3
"""
Falsifiable financial hypothesis test using run_backtest.py CLI.

HYPOTHESIS: A Bollinger Bands mean-reversion strategy (long when price is
below the lower band, short when above the upper band) on the committed
single-asset panel (AAPL) produces positive out-of-sample risk-adjusted
returns (Sharpe > 0) and positive out-of-sample total return, net of 3 bps
round-trip trading costs, on the held-out test split.

BENCHMARK-AWARE FALSIFICATION CRITERIA (hypothesis NOT SUPPORTED if ANY fails):
1. Out-of-sample Sharpe ratio (net of costs) > 0
2. Out-of-sample total return (net of costs) > benchmark total return
3. Deflated Sharpe p-value < 0.10 (multiple-testing corrected across the
   pre-registered parameter grid)
4. Benchmark alpha p-value < 0.05 (raw, vs buy-and-hold benchmark)

The benchmark is AAPL itself (buy-and-hold self-benchmark). All figures net of costs.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "example_data"

COMMISSION = 0.0002
SLIPPAGE = 0.0001
PARAMS = '{"period": 20, "std_dev": 2.0}'

BENCHMARK_FILE = "AAPL.csv"

ELEVATED_COST_SWEEP_LEVELS = [
    (COMMISSION, SLIPPAGE),
    (0.0005, 0.00025),
    (0.0010, 0.0005),
    (0.0020, 0.0010),
]

HYPOTHESIS = (
    "A Bollinger Bands mean-reversion strategy on the committed single-asset panel "
    "(AAPL) produces positive out-of-sample risk-adjusted returns (Sharpe > 0) "
    "and positive out-of-sample total return, net of 3 bps round-trip trading "
    "costs, on the held-out test split."
)

CRITERIA = [
    ("oos_sharpe_gt_zero", "oos_sharpe > 0 (net of costs)"),
    ("oos_total_return_positive", "oos_total_return > 0 (net of costs)"),
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


def _run_backtest_metrics(data_path, commission, slippage, tmpdir_path, params=PARAMS,
                          benchmark=None, n_trials=None):
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "run_backtest.py"),
        "--data", str(data_path),
        "--strategy", "bollinger_bands",
        "--symbol", "AAPL",
        "--params", params,
        "--commission", str(commission),
        "--slippage", str(slippage),
        "--train-frac", "0.6",
        "--val-frac", "0.2",
        "--test-frac", "0.2",
        "--run-split", "test",
        "--output", str(tmpdir_path / "results"),
        "--validate-point-in-time",
    ]
    if benchmark is not None:
        cmd += ["--benchmark", str(benchmark)]
    if n_trials is not None:
        cmd += ["--n-trials", str(int(n_trials))]
    result = subprocess.run(cmd, cwd=str(SCRIPTS_DIR), capture_output=True, text=True)
    if result.returncode != 0:
        print("STDOUT:", result.stdout[-800:])
        print("STDERR:", result.stderr[-800:])
        raise RuntimeError(f"run_backtest failed with code {result.returncode}")

    metrics = {}
    metrics_path = tmpdir_path / "results" / "metrics.json"
    if metrics_path.exists() and metrics_path.is_file():
        with open(metrics_path) as f:
            metrics = json.load(f)
    summary_path = tmpdir_path / "results" / "tear_sheet_summary.json"
    if summary_path.exists() and summary_path.is_file():
        with open(summary_path) as f:
            summary = json.load(f)
        for key in ("train_val_test_split", "point_in_time_validation"):
            if key in summary and key not in metrics:
                metrics[key] = summary[key]
    return metrics


def _resolve_benchmark(benchmark_path):
    p = Path(benchmark_path)
    if p.is_absolute():
        return p
    return ASSETS_DIR / "real_market_data" / p


def _gt_zero(v):
    return v is not None and float(v) > 0.0


def _lt_0_10(v):
    return v is not None and float(v) < 0.10


def _lt_0_05(v):
    return v is not None and float(v) < 0.05


def _oos_total_return_gt_benchmark(strategy_total_return, benchmark_total_return):
    return (strategy_total_return is not None
            and benchmark_total_return is not None
            and float(strategy_total_return) > float(benchmark_total_return))


BENCHMARK_CRITERIA = [
    ("oos_sharpe_gt_zero", "oos_sharpe > 0 (net of costs)", _gt_zero),
    ("oos_total_return_gt_benchmark",
     "oos_total_return > benchmark_total_return (net of costs)",
     _oos_total_return_gt_benchmark),
    ("deflated_sharpe_pvalue_lt_0.10",
     "deflated_sharpe_pvalue < 0.10 (multiple-testing corrected)",
     _lt_0_10),
    ("benchmark_alpha_pvalue_lt_0.05",
     "benchmark_alpha_pvalue < 0.05 (raw, vs buy-and-hold)",
     _lt_0_05),
]


def run_hypothesis_test(data_path, label, benchmark_path=None, n_trials=None):
    data_path = Path(data_path)
    if benchmark_path is None:
        cand = data_path.parent / "sample_benchmark.csv"
        if cand.exists():
            benchmark_path = cand
    benchmark = _resolve_benchmark(benchmark_path) if benchmark_path is not None else None
    raw_criteria = BENCHMARK_CRITERIA if benchmark is not None else CRITERIA
    criteria = []
    for entry in raw_criteria:
        if len(entry) == 3:
            criteria.append(tuple(entry))
        else:
            name, desc = entry
            criteria.append((name, desc, lambda v: v is not None and float(v) > 0.0))

    print("=" * 80)
    print(f"FALSIFIABLE HYPOTHESIS TEST (using run_backtest.py) -- {label}")
    print("=" * 80)
    print(f"Hypothesis: {HYPOTHESIS}")
    print(f"Trading costs: {COMMISSION*10000:.0f} bps commission + {SLIPPAGE*10000:.0f} bps slippage")
    print(f"Data: {data_path}")
    print(f"Strategy: bollinger_bands {PARAMS}")
    print("Split: train/val/test = 0.6/0.2/0.2 (test split only)")
    if benchmark is not None:
        print(f"Benchmark (buy-and-hold): {benchmark}")
        print(f"Parameter trials (Deflated Sharpe): {n_trials}")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        metrics = _run_backtest_metrics(
            data_path, COMMISSION, SLIPPAGE, tmpdir_path,
            benchmark=benchmark, n_trials=n_trials,
        )
        summary_path = tmpdir_path / "results" / "tear_sheet_summary.json"
        summary = {}
        if summary_path.exists() and summary_path.is_file():
            with open(summary_path) as f:
                summary = json.load(f)

        print("\n1. METHODOLOGY CONTROLS")
        split_info = summary.get("train_val_test_split", {})
        if split_info:
            sep = split_info.get("separation_check", {})
            print(f"  Split sizes (train/val/test): {sep.get('train_size')}/{sep.get('val_size')}/{sep.get('test_size')}")
            print(f"  Chronological: {sep.get('chronological')}, Disjoint: {sep.get('disjoint')}")
        pit = summary.get("point_in_time_validation", {})
        print(f"  Point-in-time validation: {pit.get('passed') if pit else None}")
        print(f"  Run split: test only (held-out)")
        print(f"  Commission: {COMMISSION}, Slippage: {SLIPPAGE}")

        print("\n2. OUT-OF-SAMPLE PERFORMANCE (net of costs)")
        print(f"  Total Return: {_fmt_pct(metrics.get('total_return'))}")
        print(f"  Annualized Return: {_fmt_pct(metrics.get('annualized_return'))}")
        print(f"  Sharpe Ratio: {_fmt_num(metrics.get('sharpe_ratio'))}")
        print(f"  Max Drawdown: {_fmt_pct(metrics.get('max_drawdown'))}")
        if benchmark is not None:
            print(f"  Benchmark Total Return: {_fmt_pct(metrics.get('benchmark_total_return'))}")
            print(f"  Benchmark Alpha: {_fmt_pct(metrics.get('alpha'))}")
            print(f"  Benchmark Alpha p-value (raw): {_fmt_num(metrics.get('alpha_pvalue'))}")
            print(f"  Correlation with benchmark: {_fmt_num(metrics.get('correlation_with_benchmark'))}")
            dsr = metrics.get("deflated_sharpe") or {}
            if isinstance(dsr, dict):
                print(f"  Deflated Sharpe Ratio: {_fmt_num(dsr.get('deflated_sharpe_ratio'))} "
                      f"(p-value {_fmt_num(dsr.get('p_value'))}, {dsr.get('n_trials')} trials)")

        print("\n3. FALSIFICATION CRITERIA")
        criterion_results = []
        passes = []
        sharpe = metrics.get('sharpe_ratio')
        ret = metrics.get('total_return')
        bench_ret = metrics.get('benchmark_total_return')
        dsr_pvalue = None
        if isinstance(metrics.get("deflated_sharpe"), dict):
            dsr_pvalue = metrics["deflated_sharpe"].get("p_value")
        alpha_pvalue = metrics.get('alpha_pvalue')

        for name, desc, fn in criteria:
            if name == "oos_sharpe_gt_zero":
                ok = fn(sharpe)
            elif name == "oos_total_return_positive":
                ok = fn(ret)
            elif name == "oos_total_return_gt_benchmark":
                ok = bool(ret is not None and bench_ret is not None
                          and float(ret) > float(bench_ret))
            elif name == "deflated_sharpe_pvalue_lt_0.10":
                ok = fn(dsr_pvalue)
            elif name == "benchmark_alpha_pvalue_lt_0.05":
                ok = fn(alpha_pvalue)
            else:
                ok = False
            passes.append(ok)
            criterion_results.append({"name": name, "description": desc, "passed": bool(ok)})
            print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {desc}")

        all_pass = all(passes)
        verdict = "SUPPORTED" if all_pass else "NOT SUPPORTED"

        print("\n" + "=" * 80)
        print(f"VERDICT: {verdict}  ({label})")
        print("  SUPPORTED   = all falsification criteria passed")
        print("  NOT SUPPORTED = at least one criterion failed (hypothesis falsified)")
        print("=" * 80)

        cost_rows = run_elevated_cost_sweep(data_path)

        observed = {
            "sharpe_ratio": sharpe,
            "total_return": ret,
            "benchmark_total_return": bench_ret,
            "benchmark_alpha": metrics.get('alpha'),
            "benchmark_alpha_pvalue": alpha_pvalue,
            "correlation_with_benchmark": metrics.get('correlation_with_benchmark'),
            "deflated_sharpe_pvalue": dsr_pvalue,
            "n_trials": n_trials,
            "benchmark_path": str(benchmark) if benchmark is not None else None,
        }

        return {
            "label": label,
            "hypothesis": HYPOTHESIS,
            "verdict": verdict,
            "all_pass": all_pass,
            "criteria": criterion_results,
            "cost_sweep": cost_rows,
            "observed": observed,
        }


def run_elevated_cost_sweep(data_path, grid=ELEVATED_COST_SWEEP_LEVELS):
    data_path = Path(data_path)
    print("\n" + "=" * 80)
    print("ELEVATED COST SENSITIVITY SWEEP")
    print("=" * 80)
    rows = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        for commission, slippage in grid:
            metrics = _run_backtest_metrics(data_path, commission, slippage, tmpdir_path)
            sharpe = metrics.get("sharpe_ratio")
            ret = metrics.get("total_return")
            ok1 = sharpe is not None and float(sharpe) > 0
            ok2 = ret is not None and float(ret) > 0
            passes = {"oos_sharpe_gt_zero": bool(ok1), "oos_total_return_positive": bool(ok2)}
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
    assert len(rows) == len(grid)
    return rows


PARAM_SENSITIVITY_GRID = (
    (20, 2.0),
    (10, 1.5),
    (40, 2.0),
    (20, 2.5),
    (20, 1.0),
    (14, 2.0),
)

N_TRIALS = len(PARAM_SENSITIVITY_GRID)


def run_param_sensitivity_sweep(data_path, grid=PARAM_SENSITIVITY_GRID):
    data_path = Path(data_path)
    rows = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        for period, std_dev in grid:
            params = json.dumps({"period": int(period), "std_dev": float(std_dev)})
            metrics = _run_backtest_metrics(data_path, COMMISSION, SLIPPAGE, tmpdir_path, params=params)
            sharpe = metrics.get("sharpe_ratio")
            ret = metrics.get("total_return")
            ok1 = sharpe is not None and float(sharpe) > 0
            ok2 = ret is not None and float(ret) > 0
            passes = {"oos_sharpe_gt_zero": bool(ok1), "oos_total_return_positive": bool(ok2)}
            verdict = "SUPPORTED" if all(passes.values()) else "NOT SUPPORTED"
            rows.append({
                "period": int(period),
                "std_dev": float(std_dev),
                "sharpe_ratio": sharpe,
                "total_return": ret,
                "verdict": verdict,
                "all_pass": all(passes.values()),
            })
    assert isinstance(rows, list) and len(rows) == len(grid)
    return rows


def run_benchmark_aware_hypothesis_test(data_path, benchmark_path=BENCHMARK_FILE,
                                         n_trials=N_TRIALS):
    return run_hypothesis_test(
        data_path,
        "aapl mean-reversion benchmark-aware real window",
        benchmark_path=benchmark_path,
        n_trials=n_trials,
    )


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Mean reversion falsifiable hypothesis test")
    parser.add_argument("--data", type=str, default=None, help="Path to the single-symbol CSV")
    parser.add_argument("--benchmark", type=str, default=BENCHMARK_FILE)
    parser.add_argument("--no-benchmark", action="store_true")
    parser.add_argument("--n-trials", type=int, default=N_TRIALS)
    parser.add_argument("--output-json", type=str, default=None)
    args = parser.parse_args()

    data_path = Path(args.data) if args.data else (ASSETS_DIR / "real_market_data" / "AAPL.csv")
    if args.no_benchmark:
        result = run_hypothesis_test(args.data, "mean reversion baseline (no benchmark)")
    else:
        result = run_benchmark_aware_hypothesis_test(
            data_path, benchmark_path=args.benchmark, n_trials=args.n_trials
        )

    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\nResult written to {args.output_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
