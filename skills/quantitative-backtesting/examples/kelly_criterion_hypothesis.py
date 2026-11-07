#!/usr/bin/env python3
"""
Falsifiable financial hypothesis test using run_backtest.py CLI.

HYPOTHESIS: A Kelly criterion position-sizing overlay (fractional half-Kelly,
lookback 63 bars, annualized mu/sigma^2 sizing) on the committed single-asset
panel (AAPL) produces positive out-of-sample risk-adjusted returns (Sharpe > 0)
and positive out-of-sample total return, net of 3 bps round-trip trading costs,
on the held-out test split.

Kelly criterion is a position-sizing overlay, not a signal generator. In
standalone mode (no base strategy registered via the CLI) it falls back to a
plain time-series momentum base (close vs its rolling mean) that yields a
tradable signal, so the backtest is well-defined and reproducible.

BENCHMARK-AWARE FALSIFICATION CRITERIA (hypothesis NOT SUPPORTED if ANY fails):
1. Out-of-sample Sharpe ratio (net of costs) > 0
2. Out-of-sample total return (net of costs) > benchmark total return
3. Deflated Sharpe p-value < 0.10 (multiple-testing corrected across the
   pre-registered parameter grid)
4. Benchmark alpha p-value < 0.05 (raw, vs buy-and-hold benchmark)

The benchmark is AAPL itself (buy-and-hold self-benchmark). All figures net of
costs.

Methodology controls:
- Chronological train/validation/test split (0.6 / 0.2 / 0.2)
- Point-in-time validation (look-ahead/stale-data/temporal-ordering screening)
- All figures net of trading costs
- Offline only: committed fixtures under assets/example_data/real_market_data/

Nothing here is evidence about any security or market: the series is a
committed historical fixture, and the verdict is a falsification outcome,
not a profitability claim.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "example_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade
PARAMS = '{"lookback": 63, "fraction": 0.5, "max_leverage": 2.0}'

BENCHMARK_FILE = "AAPL.csv"

ELEVATED_COST_SWEEP_LEVELS = [
    (COMMISSION, SLIPPAGE),
    (0.0005, 0.00025),
    (0.0010, 0.0005),
    (0.0020, 0.0010),
]

HYPOTHESIS = (
    "A Kelly criterion position-sizing overlay (fractional half-Kelly, "
    "lookback 63 bars) on the committed single-asset panel (AAPL) produces "
    "positive out-of-sample risk-adjusted returns (Sharpe > 0) and positive "
    "out-of-sample total return, net of 3 bps round-trip trading costs, on "
    "the held-out test split."
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
        "--strategy", "kelly_criterion",
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


BENCHMARK_CRITERIA = [
    ("oos_sharpe_gt_zero", "oos_sharpe > 0 (net of costs)", _gt_zero),
    ("oos_total_return_gt_benchmark",
     "oos_total_return > benchmark_total_return (net of costs)",
     lambda s, b: s is not None and b is not None and float(s) > float(b)),
    ("deflated_sharpe_pvalue_lt_0.10",
     "deflated_sharpe_pvalue < 0.10 (multiple-testing corrected)",
     _lt_0_10),
    ("benchmark_alpha_pvalue_lt_0.05",
     "benchmark_alpha_pvalue < 0.05 (raw, vs buy-and-hold)",
     _lt_0_05),
]


def run_hypothesis_test(data_path, label, benchmark_path=None, n_trials=None):
    data_path = Path(data_path)
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
    print(f"Strategy: kelly_criterion {PARAMS}")
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

        print("\n2. OUT-OF-SAMPLE PERFORMANCE (net of costs)")
        print(f"  Sharpe Ratio: {_fmt_num(metrics.get('sharpe_ratio'))}")
        print(f"  Total Return: {_fmt_pct(metrics.get('total_return'))}")
        if benchmark is not None:
            print(f"  Benchmark Total Return: {_fmt_pct(metrics.get('benchmark_total_return'))}")
            print(f"  Benchmark Alpha p-value (raw): {_fmt_num(metrics.get('alpha_pvalue'))}")
            dsr = metrics.get("deflated_sharpe") or {}
            if isinstance(dsr, dict):
                print(f"  Deflated Sharpe p-value: {_fmt_num(dsr.get('p_value'))} ({dsr.get('n_trials')} trials)")

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
                ok = bool(ret is not None and bench_ret is not None and float(ret) > float(bench_ret))
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
        print(f"\nVERDICT: {verdict}  ({label})")

        run_elevated_cost_sweep(data_path)
        observed = {
            "sharpe_ratio": sharpe, "total_return": ret,
            "benchmark_total_return": bench_ret,
            "benchmark_alpha_pvalue": alpha_pvalue,
            "deflated_sharpe_pvalue": dsr_pvalue,
            "n_trials": n_trials,
            "benchmark_path": str(benchmark) if benchmark is not None else None,
        }
        return {"label": label, "hypothesis": HYPOTHESIS, "verdict": verdict,
                "all_pass": all_pass, "criteria": criterion_results, "observed": observed}


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
                "commission": commission, "slippage": slippage,
                "commission_bps": commission * 10_000, "slippage_bps": slippage * 10_000,
                "sharpe_ratio": sharpe, "total_return": ret,
                "criteria": [{"name": n, "passed": v} for n, v in passes.items()],
                "verdict": verdict, "all_pass": all(passes.values()),
            })
            print(f"  {commission*10000:.0f}/{slippage*10000:.1f}bp  sharpe={_fmt_num(sharpe)} ret={_fmt_pct(ret)}  {verdict}")
    return rows


# Pre-registered Kelly parameter grid (lookback x fraction). Fixed before
# looking at results. Note: on this fixture the CLI sizing path makes fraction
# insensitive across 0.25/0.5/1.0 for these lookbacks (observed), so lookback
# drives the variation; the grid is still pre-registered and honest.
PARAM_SENSITIVITY_GRID = (
    (63, 0.5),    # advertised baseline
    (50, 0.5),    # shorter lookback
    (100, 0.5),   # longer lookback
    (63, 0.25),   # lower fraction
    (63, 1.0),    # full Kelly
    (50, 0.25),   # different setting
)

N_TRIALS = len(PARAM_SENSITIVITY_GRID)


def run_param_sensitivity_sweep(data_path, grid=PARAM_SENSITIVITY_GRID):
    data_path = Path(data_path)
    print("\n" + "=" * 80)
    print("PARAMETER SENSITIVITY SWEEP: Kelly params (lookback, fraction)")
    print("=" * 80)
    rows = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        for lookback, fraction in grid:
            params = json.dumps({"lookback": int(lookback), "fraction": float(fraction), "max_leverage": 2.0})
            metrics = _run_backtest_metrics(data_path, COMMISSION, SLIPPAGE, tmpdir_path, params=params)
            sharpe = metrics.get("sharpe_ratio")
            ret = metrics.get("total_return")
            ok1 = sharpe is not None and float(sharpe) > 0
            ok2 = ret is not None and float(ret) > 0
            passes = {"oos_sharpe_gt_zero": bool(ok1), "oos_total_return_positive": bool(ok2)}
            verdict = "SUPPORTED" if all(passes.values()) else "NOT SUPPORTED"
            rows.append({
                "lookback": int(lookback), "fraction": float(fraction),
                "commission": COMMISSION, "slippage": SLIPPAGE,
                "sharpe_ratio": sharpe, "total_return": ret,
                "criteria": [{"name": n, "passed": v} for n, v in passes.items()],
                "verdict": verdict, "all_pass": all(passes.values()),
            })
            print(f"  lb={lookback} fr={fraction}  sharpe={_fmt_num(sharpe)} ret={_fmt_pct(ret)}  {verdict}")
    return rows


def run_benchmark_aware_hypothesis_test(data_path, benchmark_path=None, n_trials=None):
    if benchmark_path is None:
        benchmark_path = BENCHMARK_FILE
    if n_trials is None:
        n_trials = N_TRIALS
    return run_hypothesis_test(
        data_path=data_path, label="AAPL",
        benchmark_path=benchmark_path, n_trials=n_trials,
    )


if __name__ == "__main__":
    data = ASSETS_DIR / "real_market_data" / "AAPL.csv"
    res = run_benchmark_aware_hypothesis_test(data)
    print(json.dumps(res.get("observed"), indent=2, default=str))
