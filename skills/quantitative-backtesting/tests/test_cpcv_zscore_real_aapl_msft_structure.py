#!/usr/bin/env python3
import contextlib
import io
import json
import sys
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import cpcv_analysis
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
    return build_strategy("zscore_mean_reversion", json.dumps(params))


def test_cpcv_zscore_pairs_real_msft_aapl_structure():
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "MSFT.csv").exists()

    data = _build_pair_data()
    param_grid = {"period": [20], "entry_z": [2.0], "exit_z": [0.5]}

    with contextlib.redirect_stdout(io.StringIO()):
        result = cpcv_analysis(
            data=data,
            strategy_factory=_factory,
            param_grid=param_grid,
            n_splits=5,
            test_size=0.2,
            n_jobs=1,
        )

    assert isinstance(result, dict)
    # CPCV returns folds/paths structure
    assert "folds" in result or "paths" in result or "summary" in result


if __name__ == "__main__":
    test_cpcv_zscore_pairs_real_msft_aapl_structure()
    print("OK")
