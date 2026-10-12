#!/usr/bin/env python3
"""Generate a small sample OHLCV dataset for testing the backtesting skill."""
import numpy as np
import pandas as pd
from pathlib import Path

np.random.seed(42)

dates = pd.date_range("2018-01-01", periods=504, freq="B")  # ~2 years of trading days
returns = np.random.normal(0.0005, 0.015, len(dates))
prices = 100 * np.exp(np.cumsum(returns))

df = pd.DataFrame({
    "date": dates,
    "open": prices * np.random.uniform(0.995, 1.005, len(dates)),
    "high": prices * np.random.uniform(1.005, 1.02, len(dates)),
    "low": prices * np.random.uniform(0.98, 0.995, len(dates)),
    "close": prices,
    "volume": np.random.randint(1_000_000, 10_000_000, len(dates)),
})

out = Path(__file__).parent.parent / "assets" / "example_data" / "sample_ohlcv.csv"
df.to_csv(out, index=False)
print(f"Wrote {out} ({len(df)} rows)")