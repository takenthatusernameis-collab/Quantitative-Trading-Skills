#!/usr/bin/env python3
"""
Falsifiable financial hypothesis test using run_backtest.py CLI.

HYPOTHESIS: A cross-sectional momentum strategy on a committed real-market
two-asset panel (MSFT / GOOGL) produces positive out-of-sample risk-adjusted
returns (Sharpe > 0) and positive out-of-sample total return, net of 3 bps
round-trip trading costs, on the held-out test split.

The panel is priced with --panel-pricing book: the true per-asset book return
sum_i w_i r_i, with commission and slippage charged on the book's gross
turnover, borrow on its short legs, and funding on its gross exposure.

FALSIFICATION CRITERIA (hypothesis NOT SUPPORTED if ANY fails):
1. Out-of-sample Sharpe ratio (net of costs) > 0
2. Out-of-sample total return (net of costs) > 0

Methodology controls:
- Chronological train/validation/test split (0.6 / 0.2 / 0.2). The held-out
  test set is never used in any parameter selection step; the split is
  verified disjoint and chronological.
- Point-in-time validation (look-ahead / stale-data / temporal-ordering
  screening) runs by default.
- All figures are net of trading costs.
- Offline only: committed fixtures under assets/example_data/real_market_data/
  {MSFT,GOOGL}.csv. No live network.

Nothing here is evidence about any security or market: both series are
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
PARAMS = '{"lookback": 20, "top_quantile": 0.5, "bottom_quantile": 0.5}'

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

# Elevated cost levels exercised by the elevated-cost confirmation sweep on
# the real-market MSFT/GOOGL pair. These are higher than the advertised 3bps
# (2bp comm + 1bp slip) round-trip. The advertised level is re-run inside the
# sweep as the reference baseline, so verdict changes are reported relative to it.
ELEVATED_COST_SWEEP_LEVELS = [
    (COMMISSION, SLIPPAGE),          # advertised 3bps reference
    (0.0005, 0.00025),               # 5bp comm + 2.5bp slip (10bps round-trip)
    (0.0010, 0.0005),                # 10bp comm + 5bp slip (30bps round-trip)
    (0.0020, 0.0010),                # 20bp comm + 10bp slip (60bps round-trip)
]

HYPOTHESIS = (
    "A cross-sectional momentum strategy on a committed real-market "
    "two-asset panel (MSFT / GOOGL) produces positive out-of-sample "
    "risk-adjusted returns (Sharpe > 0) and positive out-of-sample total "
    "return, net of 3 bps round-trip trading costs, on the held-out test "
    "split."
)

CRITERIA = [
    ("oos_sharpe_gt_zero", "oos_sharpe > 0 (net of costs)"),
    ("oos_total_return_positive", "oos_total_return > 0 (net of costs)"),
]

# Each fixture: (label, symbols to combine from the committed real-market CSVs).
FIXTURES = [
    ("MSFT / GOOGL real window (cross-sectional momentum)", ("MSFT.csv", "GOOGL.csv")),
    ("AAPL / GOOGL real window (cross-sectional momentum)", ("AAPL.csv", "GOOGL.csv")),
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
    """Run the pre-registered falsification test on one real-market panel.

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
    print(f"Strategy: cross_sectional_momentum {PARAMS}")
    print("Split: train/val/test = 0.6/0.2/0.2 (test split only)")
    print("Panel pricing: book (true per-asset book return, costs charged on the book)")
    print("=" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "run_backtest.py"),
            "--data", str(data_path),
            "--strategy", "cross_sectional_momentum",
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

    cost_rows = run_cost_sweep(data_path)

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
    """Run run_backtest.py once at the given cost setting and return metrics."""
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "run_backtest.py"),
        "--data", str(data_path),
        "--strategy", "cross_sectional_momentum",
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
    committed sample, not evidence about any market. The claim is purely
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


def run_elevated_cost_sweep(data_path, grid=ELEVATED_COST_SWEEP_LEVELS):
    """Elevated-cost confirmation sweep on a real-market pair.

    Runs the same pre-registered falsification criteria at a set of ascending
    cost levels that are higher than the advertised 3bps round-trip, with the
    advertised level re-run first as the reference baseline. Reports per-
    criterion pass/fail and the verdict at each level, and flags whether the
    verdict flips as costs rise.
    """
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

    assert isinstance(rows, list) and len(rows) == len(grid)
    assert rows[0]["commission_bps"] == COMMISSION * 10_000
    assert rows[0]["slippage_bps"] == SLIPPAGE * 10_000
    for prev, curr in zip(rows, rows[1:]):
        assert curr["commission_bps"] >= prev["commission_bps"]
        assert curr["slippage_bps"] >= prev["slippage_bps"]
    for r in rows:
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
        print(f"\n  VERDICT CHANGES across elevated cost sweep: {verdicts[0]} -> ... -> {verdicts[-1]} (sensitivity demonstrated)")
    else:
        print(f"\n  VERDICT STABLE across elevated cost sweep: {verdicts[0]} (pre-registered criteria applied at each level)")
    print("=" * 80)

    return rows


def main():
    results = []
    for label, filenames in FIXTURES:
        SRC = ASSETS_DIR / "real_market_data"
        frames = []
        for name in filenames:
            frame = pd.read_csv(SRC / name)
            frame["symbol"] = Path(name).stem
            frames.append(frame)
        combined = pd.concat(frames, ignore_index=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            safe_name = label.lower().replace(" ", "_").replace("/", "_").replace("(", "").replace(")", "")
            data_path = Path(tmpdir) / f"{safe_name}.csv"
            combined.to_csv(data_path, index=False)
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
