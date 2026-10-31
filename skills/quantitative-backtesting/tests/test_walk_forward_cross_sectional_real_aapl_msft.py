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
    msft = pd.read_csv(SRC / "MSFT.csv")
    aapl["date"] = pd.to_datetime(aapl["date"])
    msft["date"] = pd.to_datetime(msft["date"])
    aapl = aapl.set_index("date")
    msft = msft.set_index("date")
    return {"AAPL": aapl, "MSFT": msft}


def _factory(params):
    return build_strategy("cross_sectional_momentum", json.dumps(params))


def test_walk_forward_cross_sectional_pairs_real_msft_aapl_structure():
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "MSFT.csv").exists()

    data = _build_pair_data()
    param_grid = {"lookback": [60], "top_quantile": [0.5], "bottom_quantile": [0.5]}  # symmetric to test structure only

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


if __name__ == "__main__":
    test_walk_forward_cross_sectional_pairs_real_msft_aapl_structure()
    print("OK")
