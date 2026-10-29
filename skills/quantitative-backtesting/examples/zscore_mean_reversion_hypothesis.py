#!/usr/bin/env python3
"""
Falsifiable financial hypothesis test using run_backtest.py CLI.

HYPOTHESIS: A Z-Score mean-reversion (pairs) strategy on a cointegrated
two-asset pair produces positive out-of-sample risk-adjusted returns
(Sharpe > 0) and positive out-of-sample total return, net of 3 bps
round-trip trading costs, on the held-out test split.

The pair is synthetic: two assets that are each a random walk (individually
non-stationary) but whose log-price spread is stationary and mean-reverting
-- they cointegrate, so a genuine mean-reversion edge exists. A matched
no-effect pair (two independent random walks, no cointegration) is also
tested; the same pre-registered criteria must fail there, showing the
verdict is not a rubber stamp. Nothing here is evidence about any security
or market: both pairs are produced by a known formula.

FALSIFICATION CRITERIA (hypothesis NOT SUPPORTED if ANY fails):
1. Out-of-sample Sharpe ratio (net of costs) > 0
2. Out-of-sample total return (net of costs) > 0

Methodology controls:
- Chronological train/validation/test split (0.6 / 0.2 / 0.2). The held-out
  test set is never used in any parameter selection step; the split is
  verified disjoint and chronological.
- Point-in-time validation (look-ahead / stale-data / temporal-ordering
  screening) runs by default.
- Panel priced with --panel-pricing book: the true per-asset book return
  sum_i w_i r_i (long one leg / short the other), with commission and
  slippage charged on the book's gross turnover, borrow on its short legs,
  and funding on its gross exposure. This makes the market-neutral pairs
  book backtestable; net-exposure pricing would report a flat position.
- All figures are net of trading costs.
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
PARAMS = (
    '{"period": 20, "entry_z": 2.0, "exit_z": 0.5, '
    '"spread_method": "log_ratio", "hedge_ratio": 1.0, "hedge_lookback": 30}'
)

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

# Narrow, pre-registered z-score parameter grid used by the parameter
# sensitivity sweep. Every setting is a small perturbation of the advertised
# parameters (period=20, entry_z=2.0, exit_z=0.5); the advertised setting is
# the first rung. The grid is fixed before looking at results, so verdict
# flips across it are robustness/sensitivity signal, not parameter hunting.
PARAM_SENSITIVITY_GRID = (
    (20, 2.0, 0.5),   # advertised baseline
    (20, 1.5, 0.5),   # looser entry
    (20, 2.5, 0.5),   # tighter entry
    (20, 2.0, 0.3),   # earlier exit
    (20, 2.0, 0.7),   # later exit
    (15, 2.0, 0.5),   # shorter lookback
)

HYPOTHESIS = (
    "A Z-Score mean-reversion (pairs) strategy on a cointegrated two-asset "
    "pair produces positive out-of-sample risk-adjusted returns (Sharpe > 0) "
    "and positive out-of-sample total return, net of 3 bps round-trip "
    "trading costs, on the held-out test split."
)

CRITERIA = [
    ("oos_sharpe_gt_zero", "oos_sharpe > 0 (net of costs)"),
    ("oos_total_return_positive", "oos_total_return > 0 (net of costs)"),
]

# Each fixture: (label, file name relative to ASSETS_DIR). The cointegrated
# pair carries a genuine stationary spread; the no-effect pair is two
# independent random walks (no cointegration, no mean-reverting edge).
FIXTURES = [
    ("cointegrated pair (genuine mean-reverting spread)",
     "sample_pair_ohlcv.csv"),
    ("no-effect pair (two independent random walks)",
     "sample_pair_no_effect_ohlcv.csv"),
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


def run_hypothesis_test(data_path, label):
    """Run the pre-registered falsification test on one pair fixture.

    Returns a dict with the observed metrics, per-criterion pass/fail, and
    the overall verdict ("SUPPORTED" / "NOT SUPPORTED").
    """
    data_path = Path(data_path)
    print("=" * 80)
    print(f"FALSIFIABLE HYPOTHESIS TEST (using run_backtest.py) -- {label}")
    print("=" * 80)
    print(f"Hypothesis: {HYPOTHESIS}")
    print(f"Trading costs: {COMMISSION*10000:.0f} bps commission + {SLIPPAGE*10000:.0f} bps slippage")
    print(f"Data: {data_path}")
    print(f"Strategy: zscore_mean_reversion {PARAMS}")
    print("Split: train/val/test = 0.6/0.2/0.2 (test split only)")
    print("Panel pricing: book (true per-asset book return, costs charged on the book)")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        out_path = tmpdir_path / "metrics.json"
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "run_backtest.py"),
            "--data", str(data_path),
            "--strategy", "zscore_mean_reversion",
            "--multi-symbol",
            "--params", PARAMS,
            "--commission", str(COMMISSION),
            "--slippage", str(SLIPPAGE),
            "--train-frac", "0.6",
            "--val-frac", "0.2",
            "--test-frac", "0.2",
            "--run-split", "test",
            "--panel-pricing", "book",
            "--output", str(tmpdir_path / "results"),
            "--validate-point-in-time",
        ]
        result = subprocess.run(cmd, cwd=str(SCRIPTS_DIR), capture_output=True, text=True)
        if result.returncode != 0:
            print("STDOUT:", result.stdout[-800:])
            print("STDERR:", result.stderr[-800:])
            raise RuntimeError(f"run_backtest failed with code {result.returncode} for {label}")

        metrics = {}
        summary = {}
        metrics_path = tmpdir_path / "results" / "metrics.json"
        summary_path = tmpdir_path / "results" / "tear_sheet_summary.json"
        if metrics_path.exists() and metrics_path.is_file():
            with open(metrics_path) as f:
                metrics = json.load(f)
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

    print("\n3. FALSIFICATION CRITERIA")
    criterion_results = []
    passes = []
    sharpe = metrics.get('sharpe_ratio')
    ok1 = sharpe is not None and float(sharpe) > 0
    passes.append(ok1)
    criterion_results.append({"name": CRITERIA[0][0], "description": CRITERIA[0][1], "passed": bool(ok1)})
    print(f"  [{'PASS' if ok1 else 'FAIL'}] {CRITERIA[0][0]}: {CRITERIA[0][1]} -> {_fmt_num(sharpe)}")
    ret = metrics.get('total_return')
    ok2 = ret is not None and float(ret) > 0
    passes.append(ok2)
    criterion_results.append({"name": CRITERIA[1][0], "description": CRITERIA[1][1], "passed": bool(ok2)})
    print(f"  [{'PASS' if ok2 else 'FAIL'}] {CRITERIA[1][0]}: {CRITERIA[1][1]} -> {_fmt_pct(ret)}")

    all_pass = all(passes)
    verdict = "SUPPORTED" if all_pass else "NOT SUPPORTED"

    print("\n" + "=" * 80)
    print(f"VERDICT: {verdict}  ({label})")
    print("  SUPPORTED   = all falsification criteria passed")
    print("  NOT SUPPORTED = at least one criterion failed (hypothesis falsified)")
    print("=" * 80)

    # Cost sweep (regression guard, not a research conclusion): report the
    # verdict at each ascending cost level and assert the honest directional
    # claim -- higher per-trade costs never improve net performance. Run only
    # on the cointegrated pair fixture so the sweep is pinned to a single
    # data series (the no-effect pair is a control, not a sweep target).
    cost_rows = run_cost_sweep(data_path) if label.startswith("cointegrated") else []

    return {
        "label": label,
        "hypothesis": HYPOTHESIS,
        "verdict": verdict,
        "all_pass": all_pass,
        "criteria": criterion_results,
        "cost_sweep": cost_rows,
        "metrics": {
            "sharpe_ratio": sharpe,
            "total_return": ret,
        },
    }


def _run_backtest_metrics(data_path, commission, slippage, tmpdir_path, params=PARAMS):
    """Run run_backtest.py once at the given cost setting and return metrics.

    Uses the same CLI invocation as run_hypothesis_test (multi-symbol panel,
    book pricing, chronological train/val/test split, point-in-time
    validation) but with the caller-specified commission / slippage and the
    caller-specified strategy params JSON. Returns the parsed metrics.json,
    or {} if no metrics file was written.
    """
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "run_backtest.py"),
        "--data", str(data_path),
        "--strategy", "zscore_mean_reversion",
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


def run_cost_sweep(data_path):
    """Sweep commission / slippage across ascending levels and report an
    explicit falsification verdict at each level.

    Reports how the verdict changes as transaction costs rise, with the
    failing criteria shown per level. This is a sensitivity analysis on the
    shipped sample, not evidence about any market. The claim is purely
    directional: higher per-trade costs must never improve net performance.
    """
    data_path = Path(data_path)

    print("\n" + "=" * 80)
    print("COST SENSITIVITY SWEEP: ascending costs (falsifiable criteria)")
    print("=" * 80)
    print(f"  {'cost level':<36} {'comm':>6} {'slip':>6} {'Sharpe':>9} {'Return':>9} {'verdict':>12}")
    print("  " + "-" * 90)

    rows = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        for commission, slippage in COST_SWEEP_LEVELS:
            metrics = _run_backtest_metrics(data_path, commission, slippage, tmpdir_path)
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


def run_param_sensitivity_sweep(data_path, grid=PARAM_SENSITIVITY_GRID):
    """Sweep z-score parameters across a narrow pre-registered grid and report
    an explicit falsification verdict at each setting.

    Reports how the per-criterion pass/fail and overall verdict change as the
    z-score mean-reversion parameters are perturbed around the advertised
    setting, holding commission/slippage fixed at the advertised level. This
    is a robustness/sensitivity analysis on the shipped fixture, not evidence
    about any market. No claim is made about which setting is "best"; verdict
    flips across the grid are the signal that the result is not robust to
    small parameter changes.

    Returns a list of rows, one per grid setting, each with the params used,
    per-criterion pass/fail, and the overall verdict ("SUPPORTED" / "NOT
    SUPPORTED"). No assertion is made about the verdict itself.
    """
    data_path = Path(data_path)
    fixed_params_base = {
        "spread_method": "log_ratio",
        "hedge_ratio": 1.0,
        "hedge_lookback": 30,
    }

    print("\n" + "=" * 80)
    print("PARAMETER SENSITIVITY SWEEP: z-score params around the advertised setting")
    print("=" * 80)
    print(f"  Fixed costs: {COMMISSION*10_000:.0f}bp comm + {SLIPPAGE*10_000:.0f}bp slip")
    print(f"  Fixed: spread_method=log_ratio, hedge_ratio=1.0, hedge_lookback=30")
    print(
        f"  {'period':>6} {'entry_z':>7} {'exit_z':>7} {'Sharpe':>9} {'Return':>9} "
        f"{'criteria':>10} {'verdict':>12}"
    )
    print("  " + "-" * 90)

    rows = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        for period, entry_z, exit_z in grid:
            params = json.dumps({**fixed_params_base, "period": period, "entry_z": entry_z, "exit_z": exit_z})
            metrics = _run_backtest_metrics(data_path, COMMISSION, SLIPPAGE, tmpdir_path, params=params)
            sharpe = metrics.get("sharpe_ratio")
            ret = metrics.get("total_return")
            ok1 = sharpe is not None and float(sharpe) > 0
            ok2 = ret is not None and float(ret) > 0
            passes = {"oos_sharpe_gt_zero": bool(ok1), "oos_total_return_positive": bool(ok2)}
            failed = [name for name, ok in passes.items() if not ok]
            verdict = "SUPPORTED" if all(passes.values()) else "NOT SUPPORTED"
            rows.append({
                "period": period,
                "entry_z": entry_z,
                "exit_z": exit_z,
                "commission": COMMISSION,
                "slippage": SLIPPAGE,
                "commission_bps": COMMISSION * 10_000,
                "slippage_bps": SLIPPAGE * 10_000,
                "sharpe_ratio": sharpe,
                "total_return": ret,
                "criteria": [{"name": name, "passed": ok} for name, ok in passes.items()],
                "verdict": verdict,
                "all_pass": all(passes.values()),
            })
            crit_str = ",".join(
                "1" if c["passed"] else "0" for c in rows[-1]["criteria"]
            )
            print(
                f"  {period:>6} {entry_z:>7} {exit_z:>7} "
                f"{_fmt_num(sharpe):>9} {_fmt_pct(ret):>9} "
                f"{crit_str:>10} {verdict[:12]:>12}"
            )

    # Structural sanity: every grid setting produced a determinate row with
    # consistent per-criterion reporting. No claim is made about the verdict.
    assert len(rows) == len(grid), "param sensitivity sweep did not cover every grid setting"
    for r in rows:
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])
        assert r["verdict"] == ("SUPPORTED" if r["all_pass"] else "NOT SUPPORTED")
        assert len(r["criteria"]) == 2
        assert r["commission_bps"] == COMMISSION * 10_000
        assert r["slippage_bps"] == SLIPPAGE * 10_000

    verdicts = [r["verdict"] for r in rows]
    if len(set(verdicts)) > 1:
        print(f"\n  VERDICT CHANGES across param grid: {verdicts[0]} -> ... -> {verdicts[-1]} "
              f"(sensitivity to small param changes demonstrated)")
    else:
        print(f"\n  VERDICT STABLE across param grid: {verdicts[0]} (pre-registered criteria applied at each setting)")
    print("=" * 80)

    return rows


def main():
    results = []
    for label, filename in FIXTURES:
        data_path = ASSETS_DIR / filename
        if not data_path.exists():
            print(f"Missing fixture: {data_path}")
            return 1
        results.append(run_hypothesis_test(data_path, label))

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    for r in results:
        print(f"  {r['label']}: {r['verdict']} "
              f"(Sharpe {_fmt_num(r['metrics']['sharpe_ratio'])}, "
              f"total return {_fmt_pct(r['metrics']['total_return'])})")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
