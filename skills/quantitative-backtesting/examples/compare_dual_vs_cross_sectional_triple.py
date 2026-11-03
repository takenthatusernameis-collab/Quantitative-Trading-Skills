#!/usr/bin/env python3
"""Side-by-side comparison of dual momentum vs cross-sectional momentum on the
committed real-market triple panel (AAPL/MSFT/GOOGL)."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "example_data"
SRC = ASSETS_DIR / "real_market_data"
BENCHMARK = SRC / "MSFT.csv"

COMMISSION = 0.0002
SLIPPAGE = 0.0001
PARAMS_DUAL = '{"lookback": 252, "top_quantile": 0.5, "risk_free_rate": 0.0}'
PARAMS_CS = '{"lookback": 252, "skip_period": 1, "top_quantile": 0.5}'


def build_triple(dest: Path) -> Path:
    frames = []
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        frame = pd.read_csv(SRC / name)
        frame["symbol"] = Path(name).stem
        frames.append(frame)
    out = dest / "aapl_msft_googl_triple.csv"
    pd.concat(frames, ignore_index=True).to_csv(out, index=False)
    return out


def _run(data_path, strategy, params):
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "res"
        cmd = [
            sys.executable, str(SCRIPTS_DIR / "run_backtest.py"),
            "--data", str(data_path),
            "--strategy", strategy,
            "--multi-symbol",
            "--params", params,
            "--commission", str(COMMISSION),
            "--slippage", str(SLIPPAGE),
            "--train-frac", "0.6", "--val-frac", "0.2", "--test-frac", "0.2",
            "--run-split", "test",
            "--panel-pricing", "book",
            "--output", str(out),
            "--validate-point-in-time",
            "--benchmark", str(BENCHMARK),
            "--n-trials", "6",
        ]
        res = subprocess.run(cmd, cwd=str(SCRIPTS_DIR), capture_output=True, text=True)
        if res.returncode != 0:
            print(res.stdout[-600:])
            print(res.stderr[-600:])
            raise RuntimeError(f"failed {strategy}")
        with open(out / "metrics.json") as f:
            return json.load(f)


def main():
    with tempfile.TemporaryDirectory() as td:
        triple = build_triple(Path(td))
        m_dual = _run(triple, "dual_momentum", PARAMS_DUAL)
        m_cs = _run(triple, "cross_sectional_momentum", PARAMS_CS)
        print("\n=== Comparison (OOS test, net of 3bps, benchmark MSFT) ===")
        for name, m in [("dual_momentum", m_dual), ("cross_sectional_momentum", m_cs)]:
            print(f"\n{name}:")
            print(f"  Sharpe: {m.get('sharpe_ratio')}")
            print(f"  Total Return: {m.get('total_return')}")
            print(f"  MaxDD: {m.get('max_drawdown')}")
            print(f"  Benchmark TR: {m.get('benchmark_total_return')}")
            print(f"  Alpha p: {m.get('benchmark_alpha_pvalue')}")
            print(f"  Deflated Sharpe p: {m.get('deflated_sharpe_pvalue')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
