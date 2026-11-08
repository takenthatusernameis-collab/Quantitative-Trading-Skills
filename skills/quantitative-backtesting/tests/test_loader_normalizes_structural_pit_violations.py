"""Invariant audit: loader normalizes temporal ordering and drops symbols with
duplicate timestamps, so structural PIT violations cannot reach the multi-symbol
strict-abort gate via the normal CSV load path.

Documents the invariant that pre-empts CLI end-to-end structural-abort for
multi-symbol input. Offline, committed fixtures only.
"""
import sys
import tempfile
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
from data_loader import load_data, load_multi_symbol  # noqa: E402

REAL_DATA = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def test_load_data_sorts_unsorted_input():
    df = pd.read_csv(REAL_DATA / "AAPL.csv")
    # reverse rows to create unsorted CSV order
    unsorted = df.iloc[::-1].reset_index(drop=True)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "AAPL_unsorted.csv"
        unsorted.to_csv(p, index=False)
        loaded = load_data(p)
    assert loaded.index.is_monotonic_increasing
    assert len(loaded) == len(df)


def test_load_multi_symbol_drops_symbol_with_duplicate_timestamps():
    aapl = pd.read_csv(REAL_DATA / "AAPL.csv")
    aapl["symbol"] = "AAPL"
    # duplicate the first row to introduce duplicate timestamps
    dup = pd.concat([aapl, aapl.iloc[[0]]], ignore_index=True)
    msft = pd.read_csv(REAL_DATA / "MSFT.csv")
    msft["symbol"] = "MSFT"
    panel = pd.concat([dup, msft], ignore_index=True)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "panel.csv"
        panel.to_csv(p, index=False)
        result, dropped = load_multi_symbol(p, return_dropped=True)
    assert "MSFT" in result
    assert "AAPL" not in result
    assert "AAPL" in dropped
