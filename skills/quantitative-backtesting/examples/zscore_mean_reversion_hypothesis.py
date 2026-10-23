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
            "--validate-point-in-time",
            "--output", str(tmpdir_path),
        ]
        result = subprocess.run(cmd, cwd=str(SCRIPTS_DIR), capture_output=True, text=True)
        if result.returncode != 0:
            print("STDOUT:", result.stdout[-800:])
            print("STDERR:", result.stderr[-800:])
            raise RuntimeError(f"run_backtest failed with code {result.returncode} for {label}")

        metrics = {}
        summary = {}
        metrics_path = tmpdir_path / "metrics.json"
        summary_path = tmpdir_path / "tear_sheet_summary.json"
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

    return {
        "label": label,
        "hypothesis": HYPOTHESIS,
        "verdict": verdict,
        "all_pass": all_pass,
        "criteria": criterion_results,
        "metrics": {
            "sharpe_ratio": sharpe,
            "total_return": ret,
        },
    }


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
