#!/usr/bin/env python3
"""Walk-forward out-of-sample comparison of dual momentum vs cross-sectional
momentum vs the z-score mean-reversion family on the committed real-market
triple panel (AAPL / MSFT / GOOGL).

Each strategy is evaluated across chronological walk-forward windows
(train 12 / test 12 months, stepping 12 months) on committed fixtures only,
with a pre-registered parameter grid and the Deflated Sharpe Ratio
multiple-testing correction applied to the pooled out-of-sample record.
All figures are net of 3 bps round-trip trading costs (2 bps commission +
1 bps slippage) and priced with the per-asset book convention.

The honest comparative result is reported side by side. No claim of
profitability is made: every verdict is a falsification outcome against
pre-registered criteria, and the MSFT buy-and-hold benchmark is the least
generous plausible baseline on this panel.

Offline, committed fixtures only; no live network.
"""
import contextlib
import io
import json
import sys
import tempfile
import warnings
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import walk_forward_analysis
from strategy_builder import build_strategy

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade

# Pre-registered narrow parameter grids, drawn from the corresponding
# hypothesis-example PARAM_SENSITIVITY_GRID settings. Fixed before any result
# is inspected; small enough to stay fast in CI.
PARAM_GRID_DUAL = {
    "lookback": [189, 252],
    "top_quantile": [0.5],
    "risk_free_rate": [0.0],
}
PARAM_GRID_CS = {
    "lookback": [20, 252],
    "skip_period": [1],
    "top_quantile": [0.5],
    "bottom_quantile": [0.5],
}
# The single-pair ``zscore_mean_reversion`` strategy requires exactly two
# assets, so the three-asset panel is run with ``multi_pair_zscore_mean_reversion``,
# which trades every pair in the panel and aggregates into a book. This mirrors
# the benchmark-aware hypothesis test in zscore_mean_reversion_hypothesis.py.
PARAM_GRID_ZSCORE = {
    "period": [20],
    "entry_z": [2.0],
    "exit_z": [0.5],
}

TRAIN_MONTHS = 12
TEST_MONTHS = 12
STEP_MONTHS = 12


def _build_panel():
    panel = {}
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        panel[Path(name).stem] = df
    return panel


def _factory(strategy_name, params):
    return build_strategy(strategy_name, json.dumps(params))


def _run_walk_forward(strategy_name, param_grid):
    factory = lambda params: _factory(strategy_name, params)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = walk_forward_analysis(
            data=_build_panel(),
            strategy_factory=factory,
            param_grid=param_grid,
            train_months=TRAIN_MONTHS,
            test_months=TEST_MONTHS,
            step_months=STEP_MONTHS,
            commission=COMMISSION,
            slippage=SLIPPAGE,
            panel_pricing="book",
            apply_deflation=True,
            validate_pit=True,
        )
    return result, buffer.getvalue()


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


def main():
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        if not (SRC / name).exists():
            print(f"Missing fixture: {SRC / name}")
            return 1

    configs = [
        ("dual_momentum", PARAM_GRID_DUAL),
        ("cross_sectional_momentum", PARAM_GRID_CS),
        ("multi_pair_zscore_mean_reversion", PARAM_GRID_ZSCORE),
    ]

    results = {}
    for strategy_name, param_grid in configs:
        result, _out = _run_walk_forward(strategy_name, param_grid)
        results[strategy_name] = result

    print("\n" + "=" * 80)
    print("WALK-FORWARD COMPARISON (OOS pooled, net of 3bps, book pricing)")
    print("=" * 80)
    print(f"  {'strategy':<26} {'Sharpe':>9} {'Return':>9} {'DSR p':>9} {'periods':>8}")
    print("  " + "-" * 70)
    for strategy_name, result in results.items():
        summary = result.get("summary") or {}
        sharpe = summary.get("oos_sharpe")
        ret = summary.get("total_oos_return")
        dsr = summary.get("deflated_sharpe") or {}
        dsr_p = dsr.get("p_value")
        n_periods = summary.get("n_periods")
        print(
            f"  {strategy_name:<26} {_fmt_num(sharpe):>9} {_fmt_pct(ret):>9} "
            f"{_fmt_num(dsr_p):>9} {n_periods:>8}"
        )

    print("\n  Honest verdicts (Deflated Sharpe p-value < 0.10 required):")
    for strategy_name, result in results.items():
        summary = result.get("summary") or {}
        dsr = summary.get("deflated_sharpe") or {}
        dsr_p = dsr.get("p_value")
        verdict = "SUPPORTED" if (dsr_p is not None and float(dsr_p) < 0.10) else "NOT SUPPORTED"
        print(f"    {strategy_name}: {verdict} (DSR p={_fmt_num(dsr_p)})")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(main())