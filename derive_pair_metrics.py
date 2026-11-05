#!/usr/bin/env python3
"""Derive pinned metrics for the new pair-panel regression-guard tests.

Runs each new test's underlying sweep live against committed fixtures and
prints the observed metrics as JSON, so the test files can pin them with
relative tolerance rather than copying stale numbers.
"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent / "skills" / "quantitative-backtesting"
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from cross_sectional_momentum_hypothesis import (  # noqa: E402
    N_TRIALS,
    run_benchmark_aware_hypothesis_test,
    run_elevated_cost_sweep,
    run_param_sensitivity_sweep,
)
from dual_momentum_hypothesis import (  # noqa: E402
    N_TRIALS as DM_N_TRIALS,
    run_benchmark_aware_hypothesis_test as dm_ba,
    run_elevated_cost_sweep as dm_elevated,
    run_param_sensitivity_sweep as dm_param,
)
from rsi_mean_reversion_hypothesis import (  # noqa: E402
    N_TRIALS as RSI_N_TRIALS,
    run_benchmark_aware_hypothesis_test as rsi_ba,
    run_elevated_cost_sweep as rsi_elevated,
    run_param_sensitivity_sweep as rsi_param,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

PAIRS = ("AAPL.csv", "GOOGL.csv")


def _panel_csv(names, dest, fname):
    frames = []
    for name in names:
        frame = pd.read_csv(SRC / name)
        frame["symbol"] = Path(name).stem
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    out = dest / fname
    combined.to_csv(out, index=False)
    return out


def _dump(label, obj):
    print(f"\n===== {label} =====")
    print(json.dumps(obj, indent=2, default=str))


def _key(k):
    return ",".join(str(x) for x in k) if isinstance(k, tuple) else str(k)


def _ba_metrics(r):
    return {
        "sharpe_ratio": r["observed"].get("sharpe_ratio"),
        "total_return": r["observed"].get("total_return"),
        "benchmark_total_return": r["observed"].get("benchmark_total_return"),
        "benchmark_alpha": r["observed"].get("benchmark_alpha"),
        "benchmark_alpha_pvalue": r["observed"].get("benchmark_alpha_pvalue"),
        "correlation_with_benchmark": r["observed"].get("correlation_with_benchmark"),
        "deflated_sharpe_pvalue": r["observed"].get("deflated_sharpe_pvalue"),
        "n_trials": r["observed"].get("n_trials"),
        "benchmark_path": r["observed"].get("benchmark_path"),
    }


def _row_metrics(r, keys):
    return {k: r.get(k) for k in keys}


def main():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        pair = _panel_csv(PAIRS, d, "pair.csv")

        # ---- cross_sectional_momentum pair ----
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ba = run_benchmark_aware_hypothesis_test(pair, benchmark_path="MSFT.csv", n_trials=N_TRIALS)
        _dump("CSM pair benchmark-aware", {"observed": _ba_metrics(ba), "verdict": ba["verdict"]})

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rows = run_elevated_cost_sweep(pair)
        _dump("CSM pair elevated-cost", {
            _key((r["commission_bps"], r["slippage_bps"])): _row_metrics(r, [
                "sharpe_ratio", "total_return",
            ])
            for r in rows
        })

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rows = run_param_sensitivity_sweep(pair)
        _dump("CSM pair param-sensitivity", {
            _key((r["lookback"], r["top_quantile"], r["bottom_quantile"])): _row_metrics(r, [
                "sharpe_ratio", "total_return",
            ])
            for r in rows
        })

        # ---- dual_momentum pair ----
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ba = dm_ba(pair, benchmark_path="MSFT.csv", n_trials=DM_N_TRIALS)
        _dump("DM pair benchmark-aware", {"observed": _ba_metrics(ba), "verdict": ba["verdict"]})

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rows = dm_elevated(pair, benchmark_path="MSFT.csv", n_trials=DM_N_TRIALS)
        _dump("DM pair elevated-cost", {
            (r["commission_bps"], r["slippage_bps"]): _row_metrics(r, [
                "sharpe_ratio", "total_return", "benchmark_total_return",
                "benchmark_alpha", "benchmark_alpha_pvalue",
                "correlation_with_benchmark", "deflated_sharpe_pvalue",
            ])
            for r in rows
        })

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rows = dm_param(pair, benchmark_path="MSFT.csv", n_trials=DM_N_TRIALS)
        _dump("DM pair param-sensitivity", {
            (r["lookback"], r["top_quantile"], r["risk_free_rate"]): _row_metrics(r, [
                "sharpe_ratio", "total_return", "benchmark_total_return",
                "benchmark_alpha", "benchmark_alpha_pvalue",
                "correlation_with_benchmark", "deflated_sharpe_pvalue",
            ])
            for r in rows
        })

        # ---- rsi_mean_reversion pair ----
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ba = rsi_ba(pair, benchmark_path="MSFT.csv", n_trials=RSI_N_TRIALS)
        _dump("RSI pair benchmark-aware", {"observed": _ba_metrics(ba), "verdict": ba["verdict"]})

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rows = rsi_elevated(pair, benchmark_path="MSFT.csv")
        _dump("RSI pair elevated-cost", {
            (r["commission_bps"], r["slippage_bps"]): _row_metrics(r, [
                "sharpe_ratio", "total_return",
            ])
            for r in rows
        })

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rows = rsi_param(pair, benchmark_path="MSFT.csv")
        _dump("RSI pair param-sensitivity", {
            (r["period"], r["oversold"], r["overbought"]): _row_metrics(r, [
                "sharpe_ratio", "total_return",
            ])
            for r in rows
        })


if __name__ == "__main__":
    main()