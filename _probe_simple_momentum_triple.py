#!/usr/bin/env python3
import sys, tempfile, traceback
from pathlib import Path
import pandas as pd

SKILLS_DIR = Path("skills/quantitative-backtesting")
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from simple_momentum_hypothesis import N_TRIALS, run_benchmark_aware_hypothesis_test

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    frames = []
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        frame = pd.read_csv(SRC / name)
        frame["symbol"] = Path(name).stem
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    data_path = d / "aapl_msft_googl_triple.csv"
    combined.to_csv(data_path, index=False)

    try:
        result = run_benchmark_aware_hypothesis_test(data_path, benchmark_path="MSFT.csv", n_trials=N_TRIALS)
        import json
        print("N_TRIALS:", N_TRIALS)
        print("verdict:", result.get("verdict"))
        print("observed:", json.dumps(result.get("observed"), indent=2, default=str))
    except Exception as e:
        print("EXCEPTION:", type(e).__name__, e)
        traceback.print_exc()