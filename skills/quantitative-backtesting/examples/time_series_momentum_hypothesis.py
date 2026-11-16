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
import tempfile
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
# the committed three-asset TSMOM panel. These are higher than the advertised
# 3bps (2bp comm + 1bp slip) round-trip. The advertised level is re-run inside
# the sweep as the reference baseline, so verdict changes are reported relative
# to it.
ELEVATED_COST_SWEEP_LEVELS = [
    (COMMISSION, SLIPPAGE),          # advertised 3bps reference
    (0.0005, 0.00025),               # 5bp comm + 2.5bp slip (10bps round-trip)
    (0.0010, 0.0005),                # 10bp comm + 5bp slip (30bps round-trip)
    (0.0020, 0.0010),                # 20bp comm + 10bp slip (60bps round-trip)
]

# Market-impact coefficients exercised by the capacity sensitivity sweep on the
# committed three-asset TSMOM panel, in ascending order. Capacity scales
# inversely with impact_coefficient (capacity = max_impact * ADV_notional /
# impact_coefficient for the linear model), so as the market-impact assumption
# rises the strategy's tradable capacity must fall. The first level disables
# impact (capacity unmeasurable / None); later levels must each produce a finite
# positive estimate that is strictly lower than the previous one. Sweeping
# several levels -- rather than one advertised point plus impact-disabled --
# guards the capacity path against a silent no-op and reports how far the
# estimate falls as impact rises. Honest NOT-SUPPORTED outcomes are allowed;
# defaults are unchanged.
CAPACITY_SENSITIVITY_LEVELS = [0.0, 0.05, 0.1, 0.2]

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


def _build_triple_panel():
    """Build the committed three-asset panel (AAPL / MSFT / GOOGL) as a dict."""
    panel = {}
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        df = pd.read_csv(ASSETS_DIR / "real_market_data" / name)
        df["date"] = pd.to_datetime(df["date"])
        panel[Path(name).stem] = df.set_index("date").sort_index()
    return panel


def _run_walk_forward_panel(commission=COMMISSION, slippage=SLIPPAGE, impact_coefficient=0.0):
    """Run walk-forward analysis on the triple panel with given costs."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    from walk_forward import walk_forward_analysis
    from strategy_builder import build_strategy

    def factory(params):
        return build_strategy("time_series_momentum", json.dumps(params))

    buf = io.StringIO()
    with redirect_stdout(buf):
        result = walk_forward_analysis(
            data=_build_triple_panel(),
            strategy_factory=factory,
            param_grid=PARAM_GRID,
            train_months=TRAIN_MONTHS,
            test_months=TEST_MONTHS,
            step_months=STEP_MONTHS,
            commission=commission,
            slippage=slippage,
            impact_coefficient=impact_coefficient,
            panel_pricing="book",
            apply_deflation=True,
            validate_pit=True,
        )
    return result, buf.getvalue()


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


def run_cost_sweep():
    """Sweep commission / slippage across ascending levels on the triple panel
    (AAPL / MSFT / GOOGL) and report an explicit falsification verdict at each
    level.

    Reports how the verdict changes as transaction costs rise, with the failing
    criteria shown per level. This is a sensitivity analysis on the committed
    sample, not evidence about any market. The claim is purely directional:
    higher per-trade costs must never improve net performance.
    """
    print("\n" + "=" * 80)
    print("COST SENSITIVITY SWEEP: ascending costs on triple panel (falsifiable criteria)")
    print("=" * 80)
    print(f"  {'cost level':<36} {'comm':>6} {'slip':>6} {'Sharpe':>9} {'Return':>9} {'verdict':>12}")
    print("  " + "-" * 90)

    rows = []
    for commission, slippage in COST_SWEEP_LEVELS:
        result, _ = _run_walk_forward_panel(commission=commission, slippage=slippage)
        summary = result.get("summary", {})
        dsr = summary.get("deflated_sharpe") or {}
        dsr_p = dsr.get("p_value")
        sharpe = summary.get("oos_sharpe")
        total_ret = summary.get("total_oos_return")

        ok1 = sharpe is not None and float(sharpe) > 0
        ok2 = total_ret is not None and float(total_ret) > 0
        ok3 = dsr_p is not None and float(dsr_p) < DSR_PVALUE_THRESHOLD
        passes = {
            "oos_sharpe_gt_zero": bool(ok1),
            "oos_total_return_positive": bool(ok2),
            "deflated_sharpe_pvalue_lt_0.10": bool(ok3),
        }
        failed = [name for name, ok in passes.items() if not ok]
        verdict = "SUPPORTED" if all(passes.values()) else "NOT SUPPORTED"
        rows.append({
            "commission": commission,
            "slippage": slippage,
            "commission_bps": commission * 10_000,
            "slippage_bps": slippage * 10_000,
            "sharpe_ratio": sharpe,
            "total_return": total_ret,
            "deflated_sharpe_pvalue": dsr_p,
            "criteria": [{"name": name, "passed": ok} for name, ok in passes.items()],
            "verdict": verdict,
            "all_pass": all(passes.values()),
        })
        print(
            f"  {commission*10_000:.0f}bp comm + {slippage*10_000:.2f}bp slip".ljust(36)
            + f" {commission*10_000:>6.0f} {slippage*10_000:>6.2f} "
            + f"{(sharpe if sharpe is not None else float('nan')):>9.4f} {total_ret if total_ret is not None else float('nan'):>9.4f} {verdict[:12]:>12}"
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
            f"Return {frictionless['total_return']:.4f} -> {costed['total_return']:.4f}."
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


def run_elevated_cost_sweep(grid=ELEVATED_COST_SWEEP_LEVELS):
    """Elevated-cost confirmation sweep on the committed three-asset TSMOM
    panel (AAPL / MSFT / GOOGL).

    Runs the same pre-registered falsification criteria at a set of ascending
    cost levels that are higher than the advertised 3bps (2bp comm + 1bp slip)
    round-trip, with the advertised level re-run first as the reference baseline.
    Reports per-criterion pass/fail and the verdict at each level, and flags
    whether the verdict flips as costs rise.

    This is a sensitivity analysis on the committed sample, not evidence about
    any market. The claim is purely directional: higher per-trade costs must
    never improve net performance.
    """
    print("\n" + "=" * 80)
    print("ELEVATED COST SENSITIVITY SWEEP: ascending costs above advertised (falsifiable criteria)")
    print("=" * 80)
    print(f"  {'cost level':<36} {'comm':>6} {'slip':>6} {'Sharpe':>9} {'Return':>9} {'verdict':>12}")
    print("  " + "-" * 90)

    rows = []
    for commission, slippage in grid:
        result, _ = _run_walk_forward_panel(commission=commission, slippage=slippage)
        summary = result.get("summary", {})
        dsr = summary.get("deflated_sharpe") or {}
        dsr_p = dsr.get("p_value")
        sharpe = summary.get("oos_sharpe")
        total_ret = summary.get("total_oos_return")

        ok1 = sharpe is not None and float(sharpe) > 0
        ok2 = total_ret is not None and float(total_ret) > 0
        ok3 = dsr_p is not None and float(dsr_p) < DSR_PVALUE_THRESHOLD
        passes = {
            "oos_sharpe_gt_zero": bool(ok1),
            "oos_total_return_positive": bool(ok2),
            "deflated_sharpe_pvalue_lt_0.10": bool(ok3),
        }
        verdict = "SUPPORTED" if all(passes.values()) else "NOT SUPPORTED"
        rows.append({
            "commission": commission,
            "slippage": slippage,
            "commission_bps": commission * 10_000,
            "slippage_bps": slippage * 10_000,
            "sharpe_ratio": sharpe,
            "total_return": total_ret,
            "deflated_sharpe_pvalue": dsr_p,
            "criteria": [{"name": name, "passed": ok} for name, ok in passes.items()],
            "verdict": verdict,
            "all_pass": all(passes.values()),
        })
        print(
            f"  {commission*10_000:.0f}bp comm + {slippage*10_000:.2f}bp slip".ljust(36)
            + f" {commission*10_000:>6.0f} {slippage*10_000:>6.2f} "
            + f"{(sharpe if sharpe is not None else float('nan')):>9.4f} {total_ret if total_ret is not None else float('nan'):>9.4f} {verdict[:12]:>12}"
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
        assert len(r["criteria"]) == 3
        assert {c["name"] for c in r["criteria"]} == {
            "oos_sharpe_gt_zero",
            "oos_total_return_positive",
            "deflated_sharpe_pvalue_lt_0.10",
        }

    verdicts = [r["verdict"] for r in rows]
    if len(set(verdicts)) > 1:
        print(f"\n  VERDICT CHANGES across elevated cost sweep: {verdicts[0]} -> ... -> {verdicts[-1]} (sensitivity demonstrated)")
    else:
        print(f"\n  VERDICT STABLE across elevated cost sweep: {verdicts[0]} (pre-registered criteria applied at each level)")
    print("=" * 80)

    return rows


def run_capacity_sensitivity_sweep(grid=CAPACITY_SENSITIVITY_LEVELS):
    """Market-impact capacity sensitivity sweep on the committed three-asset
    TSMOM walk-forward panel (AAPL / MSFT / GOOGL).

    Sweeps the market-impact coefficient across ascending levels at the
    advertised 3bps (2bp comm + 1bp slip) round-trip costs and reports how the
    framework's estimated strategy capacity (notional) behaves. Capacity scales
    inversely with impact_coefficient (capacity = max_impact * ADV_notional /
    impact_coefficient for the linear model), so as the market-impact
    assumption rises the strategy's tradable capacity must fall.

    This is a sensitivity analysis on the committed sample, not evidence about
    any market, and not a profitability or capacity claim. The claim is purely
    directional: higher market impact must never increase estimated capacity,
    the impact-disabled level must report capacity=None (impact path off), and
    every impact-enabled level must produce a finite positive estimate that is
    strictly lower than the previous one. Honest outcomes are allowed;
    defaults are unchanged.
    """
    print("\n" + "=" * 80)
    print("CAPACITY SENSITIVITY SWEEP: rising market impact, falling capacity")
    print("=" * 80)
    print(f"  {'impact coeff':>14} {'capacity (notional)':>26} {'book':>20} {'verdict':>14}")
    print("  " + "-" * 82)

    rows = []
    for impact_coefficient in grid:
        result, _ = _run_walk_forward_panel(
            commission=COMMISSION,
            slippage=SLIPPAGE,
            impact_coefficient=impact_coefficient,
        )
        summary = result.get("summary", {})
        capacity = summary.get("capacity")
        capacity_book = summary.get("capacity_book")
        capacity_nw = summary.get("capacity_notional_weighted")
        oos_min_capacity = summary.get("oos_min_capacity")
        oos_min_capacity_book = summary.get("oos_min_capacity_book")

        finite = capacity is not None
        verdict = "MEASURABLE" if finite else "UNMEASURABLE (impact off)"
        rows.append({
            "impact_coefficient": impact_coefficient,
            "capacity": capacity,
            "capacity_book": capacity_book,
            "capacity_notional_weighted": capacity_nw,
            "oos_min_capacity": oos_min_capacity,
            "oos_min_capacity_book": oos_min_capacity_book,
            "verdict": verdict,
        })
        cap_str = "None (impact disabled)" if capacity is None else f"${capacity:,.0f}"
        book_str = "N/A" if capacity_book is None else f"${capacity_book:,.0f}"
        print(
            f"  {impact_coefficient:>14.4f} {cap_str:>26} {book_str:>20} {verdict[:14]:>14}"
        )

    assert isinstance(rows, list) and len(rows) == len(grid)
    assert [r["impact_coefficient"] for r in rows] == list(grid), (
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

    first = finite[0]
    last = finite[-1]
    print()
    print(
        f"  Capacity falls with market impact: ${first['capacity']:,.0f} at "
        f"impact_coefficient={first['impact_coefficient']} -> "
        f"${last['capacity']:,.0f} at impact_coefficient={last['impact_coefficient']}."
    )
    print("  Capacity path verified live: the estimate moves with impact_coefficient.")
    print("=" * 80)

    return rows


DEPLOYED_CAPITAL_REFERENCE = 100000.0


def run_oos_min_capacity_vs_deployed_capital_report(grid=CAPACITY_SENSITIVITY_LEVELS,
                                                   deployed_capital=DEPLOYED_CAPITAL_REFERENCE):
    """Bounded, falsifiable report: per impact level, does worst-OOS-window
    capacity exceed a pinned deployed-capital reference? Flags
    NOT CAPACITY-CONSTRAINED vs CAPACITY-CONSTRAINED honestly per level.
    Additive; no default/verdict changes.
    """
    rows = run_capacity_sensitivity_sweep(grid)
    report = []
    for r in rows:
        oos_min = r["oos_min_capacity"]
        oos_min_book = r.get("oos_min_capacity_book")
        if oos_min is None or r["capacity"] is None:
            constrained = None
            flag = "UNMEASURABLE (impact off)"
            constrained_book = None
            flag_book = "UNMEASURABLE (impact off)"
        else:
            constrained = float(oos_min) < float(deployed_capital)
            flag = "CAPACITY-CONSTRAINED" if constrained else "NOT CAPACITY-CONSTRAINED"
            if oos_min_book is None:
                constrained_book = None
                flag_book = "UNMEASURABLE (impact off)"
            else:
                constrained_book = float(oos_min_book) < float(deployed_capital)
                flag_book = "CAPACITY-CONSTRAINED" if constrained_book else "NOT CAPACITY-CONSTRAINED"
        report.append({
            "impact_coefficient": r["impact_coefficient"],
            "oos_min_capacity": oos_min,
            "oos_min_capacity_book": oos_min_book,
            "deployed_capital": float(deployed_capital),
            "capacity_constrained": constrained,
            "capacity_constrained_book": constrained_book,
            "flag": flag,
            "flag_book": flag_book,
        })
        print(f"  impact={r['impact_coefficient']:.4f} oos_min_capacity={oos_min} "
              f"oos_min_capacity_book={oos_min_book} deployed={deployed_capital:,.0f} "
              f"-> {flag} / book {flag_book}")
    assert len(report) == len(grid)
    assert report[0]["impact_coefficient"] == 0.0
    return report


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
