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
    msft = pd.read_csv(SRC / "MSFT.csv")
    googl = pd.read_csv(SRC / "GOOGL.csv")
    msft["date"] = pd.to_datetime(msft["date"])
    googl["date"] = pd.to_datetime(googl["date"])
    msft = msft.set_index("date")
    googl = googl.set_index("date")
    return {"MSFT": msft, "GOOGL": googl}


def _factory(params):
    return build_strategy("zscore_mean_reversion", json.dumps(params))


def test_cpcv_zscore_pairs_real_msft_googl_structure():
    assert (SRC / "MSFT.csv").exists()
    assert (SRC / "GOOGL.csv").exists()

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
    assert "folds" in result or "paths" in result or "summary" in result


if __name__ == "__main__":
    test_cpcv_zscore_pairs_real_msft_googl_structure()
    print("OK")
