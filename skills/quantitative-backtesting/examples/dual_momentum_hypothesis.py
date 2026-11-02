#!/usr/bin/env python3
"""
Falsifiable financial hypothesis test using run_backtest.py CLI.

HYPOTHESIS: A dual momentum strategy (absolute + relative momentum, long-only)
on a committed real-market three-asset panel (AAPL / MSFT / GOOGL) produces
positive out-of-sample risk-adjusted returns (Sharpe > 0) and positive
out-of-sample total return, net of 3 bps round-trip trading costs, on the
held-out test split.

BENCHMARK-AWARE FALSIFICATION CRITERIA (hypothesis NOT SUPPORTED if ANY fails):
1. Out-of-sample Sharpe ratio (net of costs) > 0
2. Out-of-sample total return (net of costs) > benchmark total return
3. Deflated Sharpe p-value < 0.10 (multiple-testing corrected across the
   pre-registered parameter grid, N = len(PARAM_SENSITIVITY_GRID) = 6)
4. Benchmark alpha p-value < 0.05 (raw, uncorrected, vs the buy-and-hold
   benchmark)

The benchmark is MSFT, the strongest buy-and-hold name on the panel over the
held-out window (~90% total return), so testing alpha against it is the least
generous plausible baseline: if dual momentum does not beat the best single
name on the panel, it does not beat a market index either. With a single
benchmark (N=1) the Deflated Alpha Ratio benchmark-selection correction is not
applicable (the framework reports deflated_alpha=None for N<2), so it is
deliberately NOT a criterion here -- stating it would be a vacuous control.

Methodology controls:
- Chronological train/validation/test split (0.6 / 0.2 / 0.2)
- Point-in-time validation (look-ahead/stale-data/temporal-ordering screening)
- All figures net of trading costs
- Offline only: committed fixtures under assets/example_data/real_market_data/
- Panel pricing book for multi-asset panel

Nothing here is evidence about any security or market: the three series are
committed historical fixtures, and the verdict is a falsification outcome,
not a profitability claim.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "example_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade
PARAMS = '{"lookback": 252, "top_quantile": 0.5, "risk_free_rate": 0.0}'

# Primary buy-and-hold benchmark for the dual momentum hypothesis on the
# committed three-asset panel. MSFT is the strongest buy-and-hold on the panel
# over the held-out test window (total return ~90%), so testing alpha against
# it is the least generous plausible baseline: if dual momentum does not beat
# the best single name on the panel, it does not beat a market index either.
# Path is resolved relative to the committed real-market fixtures directory.
BENCHMARK_FILE = "MSFT.csv"

ELEVATED_COST_SWEEP_LEVELS = [
    (COMMISSION, SLIPPAGE),          # advertised 3bps reference
    (0.0005, 0.00025),               # 5bp comm + 2.5bp slip (10bps round-trip)
    (0.0010, 0.0005),                # 10bp comm + 5bp slip (30bps round-trip)
    (0.0020, 0.0010),                # 20bp comm + 10bp slip (60bps round-trip)
]

HYPOTHESIS = (
    "A dual momentum strategy on a committed real-market three-asset panel "
    "(AAPL / MSFT / GOOGL) produces positive out-of-sample risk-adjusted returns "
    "(Sharpe > 0) and positive out-of-sample total return, net of 3 bps "
    "round-trip trading costs, on the held-out test split."
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
    """Run run_backtest.py once at the given cost setting and return metrics.

    ``benchmark`` is a path to a committed buy-and-hold OHLCV file (resolved
    relative to the committed real-market fixtures directory when relative).
    ``n_trials`` reports the number of parameter configurations to the
    Deflated Sharpe Ratio machinery; None disables the correction.
    """
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "run_backtest.py"),
        "--data", str(data_path),
        "--strategy", "dual_momentum",
        "--multi-symbol",
        "--params", params,
        "--commission", str(commission),
        "--slippage", str(slippage),
        "--train-frac", "0.6",
        "--val-frac", "0.2",
        "--test-frac", "0.2",
        "--run-split", "test",
        "--panel-pricing", "book",
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
    """Resolve a benchmark path relative to the committed fixtures directory
    when it is relative, so callers can pass a bare filename like "MSFT.csv".
    """
    p = Path(benchmark_path)
    if p.is_absolute():
        return p
    return ASSETS_DIR / "real_market_data" / p


# Predicate helpers shared by both the baseline and benchmark-aware criterion
# lists. Defined as named functions (not lambdas) so the criterion tuples are
# plain data and the evaluation loop below can compare them by identity.
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


# Baseline falsification criteria (no benchmark). Stored as 2-tuples
# (name, description); the predicate is the shared _gt_zero for both.
CRITERIA = [
    ("oos_sharpe_gt_zero", "oos_sharpe > 0 (net of costs)"),
    ("oos_total_return_positive", "oos_total_return > 0 (net of costs)"),
]

# Benchmark-aware falsification criteria. Stored as 3-tuples
# (name, description, predicate). Criterion 3 (Deflated Sharpe p-value) is the
# multiple-testing correction across the pre-registered parameter grid;
# criterion 4 (raw benchmark alpha p-value) is the uncorrected buy-and-hold
# comparison. With a single benchmark (N=1) the Deflated Alpha Ratio
# benchmark-selection correction is not applicable (the framework reports
# deflated_alpha=None for N<2), so it is deliberately NOT a criterion here --
# stating it would be a vacuous control.
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
    """Run the pre-registered falsifiable hypothesis test on one real-market panel.

    ``benchmark_path`` is an optional committed buy-and-hold OHLCV file (a bare
    filename like "MSFT.csv" is resolved relative to the committed real-market
    fixtures directory). When provided, the benchmark-aware criteria in
    BENCHMARK_CRITERIA are evaluated in place of the two baseline criteria;
    when omitted, the baseline CRITERIA are used.

    ``n_trials`` reports the number of parameter configurations to the Deflated
    Sharpe Ratio machinery; None disables the correction.
    """
    data_path = Path(data_path)
    benchmark = _resolve_benchmark(benchmark_path) if benchmark_path is not None else None
    # Normalize the criterion list to (name, description, predicate) triples so
    # the baseline two-criterion list and the benchmark-aware four-criterion
    # list are interchangeable in the evaluation loop below. The baseline
    # list is stored as 2-tuples; the benchmark-aware list as 3-tuples.
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
    print(f"Strategy: dual_momentum {PARAMS}")
    print("Split: train/val/test = 0.6/0.2/0.2 (test split only)")
    print("Panel pricing: book (true per-asset book return, costs charged on the book)")
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
    bd = metrics.get("book_diagnostic") or {}
    print(f"  Panel pricing: book; periods with a book: {bd.get('n_periods_with_book')}/{bd.get('n_periods')}")

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
    print("ELEVATED COST SENSITIVITY SWEEP: ascending costs above advertised (falsifiable criteria)")
    print("=" * 80)
    print(f"  {'cost level':<36} {'comm':>6} {'slip':>6} {'Sharpe':>9} {'Return':>9} {'verdict':>12}")
    print("  " + "-" * 90)

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
            print(
                f"  {commission*10_000:.0f}bp comm + {slippage*10_000:.2f}bp slip".ljust(36)
                + f" {commission*10_000:>6.0f} {slippage*10_000:>6.2f} "
                + f"{_fmt_num(sharpe):>9} {_fmt_pct(ret):>9} {verdict[:12]:>12}"
            )

    assert len(rows) == len(grid)
    assert rows[0]["commission_bps"] == COMMISSION * 10_000
    assert rows[0]["slippage_bps"] == SLIPPAGE * 10_000
    for r in rows:
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])

    verdicts = [r["verdict"] for r in rows]
    if len(set(verdicts)) > 1:
        print(f"\n  VERDICT CHANGES across elevated cost sweep: {verdicts[0]} -> ... -> {verdicts[-1]} (sensitivity demonstrated)")
    else:
        print(f"\n  VERDICT STABLE across elevated cost sweep: {verdicts[0]}")
    print("=" * 80)

    return rows


# Narrow, pre-registered dual momentum parameter grid used by the parameter
# sensitivity sweep. Every setting is a small perturbation of the advertised
# parameters (lookback=252, top_quantile=0.5, risk_free_rate=0.0); the
# advertised setting is the first rung. The grid is fixed before looking at
# results, so verdict flips across it are robustness/sensitivity signal, not
# parameter hunting.
PARAM_SENSITIVITY_GRID = (
    (252, 0.5, 0.0),   # advertised baseline
    (189, 0.5, 0.0),   # shorter lookback (~39 weeks)
    (315, 0.5, 0.0),   # longer lookback (~63 weeks)
    (252, 0.4, 0.0),   # lower top quantile (more assets in the long book)
    (252, 0.6, 0.0),   # higher top quantile (fewer assets in the long book)
    (252, 0.5, 0.02),  # positive risk-free rate for the absolute-momentum floor
)

# Number of parameter configurations in PARAM_SENSITIVITY_GRID, reported to
# run_backtest via --n-trials so the Deflated Sharpe Ratio (multiple-testing
# correction across the parameter grid) is computed. Pre-registered: it is the
# length of the grid, fixed before any result is looked at.
N_TRIALS = len(PARAM_SENSITIVITY_GRID)


def run_param_sensitivity_sweep(data_path, grid=PARAM_SENSITIVITY_GRID):
    """Sweep dual momentum parameters across a narrow pre-registered grid and
    report an explicit falsification verdict at each setting.

    Reports how the per-criterion pass/fail and overall verdict change as
    parameters are perturbed around the advertised setting
    (lookback=252, top_quantile=0.5, risk_free_rate=0.0), holding
    commission/slippage fixed at the advertised level. This is a
    robustness/sensitivity analysis on the committed sample, not evidence about
    any market. No claim is made about which setting is "best"; verdict flips
    across the grid are the signal that the result is not robust to small
    parameter changes.
    """
    data_path = Path(data_path)

    print("\n" + "=" * 80)
    print("PARAMETER SENSITIVITY SWEEP: dual momentum params around the advertised setting")
    print("=" * 80)
    print(f"  Fixed costs: {COMMISSION*10_000:.0f}bp comm + {SLIPPAGE*10_000:.0f}bp slip")
    print(
        f"  {'lookback':>8} {'top_q':>7} {'rf':>7} {'Sharpe':>9} {'Return':>9} "
        f"{'criteria':>10} {'verdict':>12}"
    )
    print("  " + "-" * 90)

    rows = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        for lookback, top_q, risk_free_rate in grid:
            params = json.dumps({
                "lookback": int(lookback),
                "top_quantile": float(top_q),
                "risk_free_rate": float(risk_free_rate),
            })
            metrics = _run_backtest_metrics(data_path, COMMISSION, SLIPPAGE, tmpdir_path, params=params)
            sharpe = metrics.get("sharpe_ratio")
            ret = metrics.get("total_return")
            ok1 = sharpe is not None and float(sharpe) > 0
            ok2 = ret is not None and float(ret) > 0
            passes = {"oos_sharpe_gt_zero": bool(ok1), "oos_total_return_positive": bool(ok2)}
            failed = [name for name, ok in passes.items() if not ok]
            verdict = "SUPPORTED" if all(passes.values()) else "NOT SUPPORTED"
            rows.append({
                "lookback": int(lookback),
                "top_quantile": float(top_q),
                "risk_free_rate": float(risk_free_rate),
                "commission": COMMISSION,
                "slippage": SLIPPAGE,
                "commission_bps": COMMISSION * 10_000,
                "slippage_bps": SLIPPAGE * 10_000,
                "sharpe_ratio": sharpe,
                "total_return": ret,
                "criteria": [{"name": name, "passed": ok} for name, ok in passes.items()],
                "verdict": verdict,
                "all_pass": all(passes.values()),
                "failed_criteria": failed,
            })
            print(
                f"  {int(lookback):>8} {float(top_q):>7.1f} {float(risk_free_rate):>7.2f} "
                + f"{_fmt_num(sharpe):>9} {_fmt_pct(ret):>9} {','.join(failed) if failed else 'ok':>10} {verdict[:12]:>12}"
            )

    assert isinstance(rows, list) and len(rows) == len(grid)
    for r, (lookback, top_q, risk_free_rate) in zip(rows, grid):
        assert r["lookback"] == int(lookback)
        assert r["top_quantile"] == float(top_q)
        assert r["risk_free_rate"] == float(risk_free_rate)
        assert r["commission"] == COMMISSION
        assert r["slippage"] == SLIPPAGE
        assert r["commission_bps"] == COMMISSION * 10_000
        assert r["slippage_bps"] == SLIPPAGE * 10_000
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])
        assert r["verdict"] == ("SUPPORTED" if r["all_pass"] else "NOT SUPPORTED")
        assert len(r["criteria"]) == 2
        assert {c["name"] for c in r["criteria"]} == {
            "oos_sharpe_gt_zero",
            "oos_total_return_positive",
        }

    verdicts = [r["verdict"] for r in rows]
    if len(set(verdicts)) > 1:
        print(f"\n  VERDICT CHANGES across parameter grid: {verdicts[0]} -> ... -> {verdicts[-1]} (sensitivity demonstrated)")
    else:
        print(f"\n  VERDICT STABLE across parameter grid: {verdicts[0]} (pre-registered criteria applied at each setting)")
    print("=" * 80)

    return rows


def run_benchmark_aware_hypothesis_test(data_path, benchmark_path=BENCHMARK_FILE,
                                        n_trials=N_TRIALS):
    """Run the benchmark-aware falsification test on one real-market panel.

    Wraps ``run_hypothesis_test`` with the committed buy-and-hold benchmark and
    the pre-registered parameter-trial count, so callers (and the regression
    test) have a single documented entry point that exercises the Deflated
    Sharpe Ratio and the benchmark alpha comparison together.
    """
    return run_hypothesis_test(
        data_path,
        "aapl_msft_googl triple dual momentum benchmark-aware real window",
        benchmark_path=benchmark_path,
        n_trials=n_trials,
    )


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Dual momentum falsifiable hypothesis test")
    parser.add_argument("--data", type=str, required=True, help="Path to the multi-symbol panel CSV")
    parser.add_argument("--benchmark", type=str, default=BENCHMARK_FILE,
                        help="Buy-and-hold benchmark OHLCV path (default: committed MSFT.csv)")
    parser.add_argument("--no-benchmark", action="store_true",
                        help="Run the baseline two-criterion test without a benchmark")
    parser.add_argument("--n-trials", type=int, default=N_TRIALS,
                        help="Parameter trials for the Deflated Sharpe Ratio")
    parser.add_argument("--output-json", type=str, default=None, help="Write result JSON to this path")
    args = parser.parse_args()

    if args.no_benchmark:
        result = run_hypothesis_test(args.data, "dual momentum baseline (no benchmark)")
    else:
        result = run_benchmark_aware_hypothesis_test(
            args.data, benchmark_path=args.benchmark, n_trials=args.n_trials
        )

    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\nResult written to {args.output_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
