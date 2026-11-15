#!/usr/bin/env python3
"""
Falsifiable financial hypothesis test for a standalone time-series momentum
(TSMOM) strategy on the committed single-asset panel (AAPL).

HYPOTHESIS: A 12-month (252-trading-day) time-series momentum signal (long
when the trailing return is positive, flat otherwise) produces positive
out-of-sample risk-adjusted returns (Sharpe > 0) and positive out-of-sample
total return, net of 3 bps round-trip trading costs, on held-out walk-forward
windows of the committed AAPL fixture.

This is a standalone, falsifiable TSMOM hypothesis. The same absolute-momentum
idea already appears as a base signal inside the volatility-targeting and
Kelly-criterion overlays; here it is evaluated as its own registered strategy
(`time_series_momentum`) with pre-pinned criteria and a pre-registered
parameter grid.

PRE-REGISTERED FALSIFICATION CRITERIA (pinned before results were inspected;
hypothesis NOT SUPPORTED if ANY fails):
1. Out-of-sample Sharpe ratio (net of costs) > 0
2. Out-of-sample total return (net of costs) > 0
3. Deflated Sharpe p-value < 0.10 (multiple-testing corrected across the
   pre-registered parameter grid)

Methodology controls:
- Chronological walk-forward evaluation (train 24 / test 12 / step 12 months)
  so the 252-day lookback fits within each test window's warmup path and the
  strategy can take positions (shorter test windows leave the signal undefined
  for the whole window).
- Pre-registered parameter grid fixed before inspection (N = 3 trials).
- Point-in-time validation engaged; trading costs applied (2 bps commission +
  1 bps slippage per trade, 3 bps round-trip).
- Offline only: committed fixture under assets/example_data/real_market_data/.

Verdicts are falsification outcomes, never profitability claims.
"""

import io
import json
import sys
from pathlib import Path
from contextlib import redirect_stdout

import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "example_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade

# Pre-registered grid (fixed before any result is inspected).
PARAM_GRID = {"lookback": [126, 189, 252]}
N_TRIALS = len(PARAM_GRID["lookback"])

TRAIN_MONTHS = 24
TEST_MONTHS = 12
STEP_MONTHS = 12

DSR_PVALUE_THRESHOLD = 0.10

HYPOTHESIS = (
    "A 12-month (252-trading-day) time-series momentum signal (long when the "
    "trailing return is positive, flat otherwise) on the committed AAPL "
    "fixture produces positive out-of-sample risk-adjusted returns (Sharpe > 0) "
    "and positive out-of-sample total return, net of 3 bps round-trip trading "
    "costs, on held-out walk-forward windows."
)

CRITERIA = [
    ("oos_sharpe_gt_zero", "oos_sharpe > 0 (net of costs)"),
    ("oos_total_return_positive", "oos_total_return > 0 (net of costs)"),
    ("deflated_sharpe_pvalue_lt_0.10",
     "deflated_sharpe_pvalue < 0.10 (multiple-testing corrected)"),
]


def _build_data(data_path):
    df = pd.read_csv(data_path)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _run_walk_forward(data_path):
    sys.path.insert(0, str(SCRIPTS_DIR))
    from walk_forward import walk_forward_analysis
    from strategy_builder import build_strategy

    def factory(params):
        return build_strategy("time_series_momentum", json.dumps(params))

    data = _build_data(data_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = walk_forward_analysis(
            data=data,
            strategy_factory=factory,
            param_grid=PARAM_GRID,
            train_months=TRAIN_MONTHS,
            test_months=TEST_MONTHS,
            step_months=STEP_MONTHS,
            commission=COMMISSION,
            slippage=SLIPPAGE,
            apply_deflation=True,
            validate_pit=True,
        )
    return result, buf.getvalue()


def run_hypothesis_test(data_path, label):
    data_path = Path(data_path)
    print("=" * 80)
    print(f"FALSIFIABLE HYPOTHESIS TEST (TSMOM walk-forward) -- {label}")
    print("=" * 80)
    print(f"Hypothesis: {HYPOTHESIS}")
    print(f"Trading costs: {COMMISSION*10000:.0f} bps commission + {SLIPPAGE*10000:.0f} bps slippage")
    print(f"Data: {data_path}")
    print(f"Strategy: time_series_momentum, grid={PARAM_GRID} (N={N_TRIALS} trials)")
    print(f"Walk-forward: train={TRAIN_MONTHS}m / test={TEST_MONTHS}m / step={STEP_MONTHS}m")
    print("=" * 80)

    result, out = _run_walk_forward(data_path)
    summary = result.get("summary", {})
    dsr = summary.get("deflated_sharpe") or {}
    dsr_p = dsr.get("p_value")
    sharpe = summary.get("oos_sharpe")
    total_ret = summary.get("total_oos_return")

    print("\n1. METHODOLOGY CONTROLS")
    print(f"  Point-in-time validation passed: {'Point-in-time validation passed' in out}")
    print(f"  n_periods: {summary.get('n_periods')}, periods_with_position: {summary.get('periods_with_position')}")
    print(f"  bias_controls_engaged: {summary.get('bias_controls_engaged')}")

    print("\n2. OUT-OF-SAMPLE PERFORMANCE (net of costs, pooled walk-forward)")
    print(f"  OOS Sharpe: {sharpe}")
    print(f"  Total OOS Return: {total_ret}")
    print(f"  Deflated Sharpe Ratio: {dsr.get('deflated_sharpe_ratio')} (p-value {dsr_p}, {dsr.get('n_trials')} trials)")

    print("\n3. FALSIFICATION CRITERIA (pinned before inspection)")
    criterion_results = []
    for name, desc in CRITERIA:
        if name == "oos_sharpe_gt_zero":
            ok = sharpe is not None and float(sharpe) > 0.0
        elif name == "oos_total_return_positive":
            ok = total_ret is not None and float(total_ret) > 0.0
        elif name == "deflated_sharpe_pvalue_lt_0.10":
            ok = dsr_p is not None and float(dsr_p) < DSR_PVALUE_THRESHOLD
        else:
            ok = False
        criterion_results.append({"name": name, "description": desc, "passed": bool(ok)})
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")

    all_pass = all(c["passed"] for c in criterion_results)
    verdict = "SUPPORTED" if all_pass else "NOT SUPPORTED"

    print("\n4. VERDICT")
    print(f"  HYPOTHESIS {verdict}.")
    print(f"  VERDICT: {verdict}")
    if not all_pass:
        failed = [c["name"] for c in criterion_results if not c["passed"]]
        print(f"  Failed criteria: {', '.join(failed)}")
    print("\n  Falsification outcome on committed fixtures only; not evidence about")
    print("  any security or market, and not a profitability claim.")

    return {
        "hypothesis": HYPOTHESIS,
        "criteria": criterion_results,
        "all_pass": all_pass,
        "verdict": verdict,
        "observed": {
            "oos_sharpe": sharpe,
            "oos_volatility": summary.get("oos_volatility"),
            "total_oos_return": total_ret,
            "n_periods": summary.get("n_periods"),
            "periods_with_position": summary.get("periods_with_position"),
            "deflated_sharpe_ratio": dsr.get("deflated_sharpe_ratio"),
            "deflated_sharpe_pvalue": dsr_p,
            "n_trials": dsr.get("n_trials"),
        },
        "summary": summary,
    }


def main():
    for symbol in ("AAPL", "MSFT", "GOOGL"):
        data_path = ASSETS_DIR / "real_market_data" / f"{symbol}.csv"
        run_hypothesis_test(
            data_path,
            f"TSMOM (12m lookback grid) on {symbol}, walk-forward",
        )
        print()


if __name__ == "__main__":
    main()
