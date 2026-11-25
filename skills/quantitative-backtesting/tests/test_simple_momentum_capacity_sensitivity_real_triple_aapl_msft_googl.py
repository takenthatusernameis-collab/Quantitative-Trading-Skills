#!/usr/bin/env python3
"""Market-impact capacity sensitivity for simple momentum on the committed
three-asset panel (AAPL / MSFT / GOOGL).

Simple momentum (SMA crossover fast=10 / slow=30) is a single-asset strategy:
it trades AAPL only on the committed triple panel and is compared against
buy-and-hold MSFT, mirroring the pinned benchmark-aware test
(``test_simple_momentum_benchmark_aware_real_triple_aapl_msft_googl.py``).
The triple CSV (AAPL/MSFT/GOOGL with a ``symbol`` column) is the data source;
``--symbol AAPL`` selects the traded asset, matching that pinned test.

Sweeps the market-impact coefficient across ascending levels at the advertised
3bps (2bp comm + 1bp slip) round-trip costs, with impact disabled first
(capacity unmeasurable / None), and reports how estimated strategy capacity
(notional) behaves. Capacity scales inversely with impact_coefficient, so as
market impact rises estimated capacity must fall -- never increase. The
impact-disabled level must report capacity=None. No profitability or capacity
claim is made; capacity is an execution-side control.

Offline, committed fixtures only
(assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv). No live network.
"""
import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"
SCRIPTS_DIR = SKILLS_DIR / "scripts"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade

# Market-impact coefficients exercised by the capacity sensitivity sweep,
# ascending; the first level disables impact (capacity unmeasurable / None).
CAPACITY_SENSITIVITY_LEVELS = [0.0, 0.05, 0.1, 0.2]

TRAIN_FRAC = 0.6
VAL_FRAC = 0.2
TEST_FRAC = 0.2


def _build_triple_csv(dest: Path) -> Path:
    frames = []
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        frame = pd.read_csv(SRC / name)
        frame["symbol"] = Path(name).stem
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    out = dest / "aapl_msft_googl_triple.csv"
    combined.to_csv(out, index=False)
    return out


def _run_backtest(impact_coefficient, data_path, tmpdir_path):
    out_path = tmpdir_path / "results"
    # clean prior results
    import shutil as _sh
    if out_path.exists():
        _sh.rmtree(out_path)
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "run_backtest.py"),
        "--data", str(data_path),
        "--strategy", "sma_crossover",
        "--symbol", "AAPL",
        "--params", '{"fast_period": 10, "slow_period": 30}',
        "--commission", str(COMMISSION),
        "--slippage", str(SLIPPAGE),
        "--train-frac", str(TRAIN_FRAC),
        "--val-frac", str(VAL_FRAC),
        "--test-frac", str(TEST_FRAC),
        "--run-split", "test",
        "--output", str(out_path),
        "--validate-point-in-time",
        "--impact-coefficient", str(impact_coefficient),
        "--benchmark", str(SRC / "MSFT.csv"),
    ]
    result = subprocess.run(cmd, cwd=str(SCRIPTS_DIR), capture_output=True, text=True)
    if result.returncode != 0:
        print("STDOUT:", result.stdout[-800:])
        print("STDERR:", result.stderr[-800:])
        raise RuntimeError(f"run_backtest failed with code {result.returncode}")
    metrics = {}
    candidates = [
        out_path / "metrics.json",
        SCRIPTS_DIR / "results" / "metrics.json",
        Path("results") / "metrics.json",
    ]
    for cand in candidates:
        if cand.exists() and cand.is_file():
            with open(cand) as f:
                metrics = json.load(f)
            break
    return metrics


def _summarize(impact_coefficient, metrics):
    summary = metrics if isinstance(metrics, dict) else {}
    capacity = summary.get("capacity")
    if isinstance(capacity, dict):
        capacity = capacity.get("cost_adjusted_capacity")
    capacity_book = summary.get("capacity_book")
    print(
        "CAPACITY SENSITIVITY SWEEP: "
        f"impact_coefficient={impact_coefficient:.4f} "
        f"capacity={('None (impact disabled)' if capacity is None else f'${capacity:,.0f}')} "
        f"capacity_book={('N/A' if capacity_book is None else f'${capacity_book:,.0f}')}"
    )
    return {
        "impact_coefficient": impact_coefficient,
        "capacity": capacity,
        "capacity_book": capacity_book,
    }


def test_simple_momentum_capacity_sensitivity_sweep_real_triple_panel():
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists(), f"missing fixture {name}"

    buffer = io.StringIO()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with contextlib.redirect_stdout(buffer):
            with tempfile.TemporaryDirectory() as td:
                d = Path(td)
                data_path = _build_triple_csv(d)
                rows = [
                    _summarize(level, _run_backtest(level, data_path, d))
                    for level in CAPACITY_SENSITIVITY_LEVELS
                ]
                finite = [r for r in rows if r["capacity"] is not None]
                first = finite[0]
                last = finite[-1]
                print(
                    "  Capacity falls with market impact: "
                    f"${first['capacity']:,.0f} at impact_coefficient={first['impact_coefficient']} -> "
                    f"${last['capacity']:,.0f} at impact_coefficient={last['impact_coefficient']}."
                )

    assert [r["impact_coefficient"] for r in rows] == list(
        CAPACITY_SENSITIVITY_LEVELS
    ), "capacity sensitivity levels are not recorded in ascending order"
    assert rows[0]["impact_coefficient"] == 0.0, (
        "first capacity sensitivity level must be impact disabled"
    )
    assert rows[0]["capacity"] is None, (
        "impact-disabled setting must report capacity=None, got "
        f"{rows[0]['capacity']}"
    )
    assert rows[0]["capacity_book"] is None, (
        "impact-disabled setting must report capacity_book=None, got "
        f"{rows[0]['capacity_book']}"
    )

    finite = [r for r in rows if r["capacity"] is not None]
    assert len(finite) >= 2, (
        "capacity sensitivity sweep must produce at least two finite readings"
    )
    for r in finite:
        assert float(r["capacity"]) > 0, (
            "capacity estimate must be positive: " f"{r['capacity']}"
        )
    # Capacity must fall monotonically as market impact rises.
    for prev, curr in zip(finite, finite[1:]):
        assert curr["capacity"] < prev["capacity"], (
            "capacity does not fall as market impact rises: "
            f"impact {prev['impact_coefficient']} -> {prev['capacity']:,.0f}, "
            f"impact {curr['impact_coefficient']} -> {curr['capacity']:,.0f}"
        )

    out = buffer.getvalue()
    assert "CAPACITY SENSITIVITY SWEEP" in out
    assert "Capacity falls with market impact" in out
    flat_warnings = [
        str(w.message) for w in caught
        if "flat (zero) portfolio signal" in str(w.message)
    ]
    assert flat_warnings == [], f"unexpected flat-signal warning: {flat_warnings}"


if __name__ == "__main__":
    test_simple_momentum_capacity_sensitivity_sweep_real_triple_panel()
    print("OK")
