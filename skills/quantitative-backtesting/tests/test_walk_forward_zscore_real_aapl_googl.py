#!/usr/bin/env python3
import contextlib
import io
import json
import sys
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import walk_forward_analysis
from strategy_builder import build_strategy

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def _build_pair_data():
    aapl = pd.read_csv(SRC / "AAPL.csv")
    googl = pd.read_csv(SRC / "GOOGL.csv")
    aapl["date"] = pd.to_datetime(aapl["date"])
    googl["date"] = pd.to_datetime(googl["date"])
    aapl = aapl.set_index("date")
    googl = googl.set_index("date")
    return {"AAPL": aapl, "GOOGL": googl}


def _factory(params):
    return build_strategy("zscore_mean_reversion", json.dumps(params))


def test_walk_forward_zscore_pairs_real_googl_aapl_structure():
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "GOOGL.csv").exists()

    data = _build_pair_data()
    param_grid = {"period": [20], "entry_z": [2.0], "exit_z": [0.5]}

    with contextlib.redirect_stdout(io.StringIO()):
        result = walk_forward_analysis(
            data=data,
            strategy_factory=_factory,
            param_grid=param_grid,
            train_months=12,
            test_months=3,
            step_months=3,
        )

    assert isinstance(result, dict)
    assert "periods" in result
    assert len(result["periods"]) > 0
    for period in result["periods"]:
        assert "test_returns" in period


if __name__ == "__main__":
    test_walk_forward_zscore_pairs_real_googl_aapl_structure()
    print("OK")
