#!/usr/bin/env python3
import contextlib
import io
import json
import sys
import warnings
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import cpcv_analysis
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
    return build_strategy("cross_sectional_momentum", json.dumps(params))


def test_cpcv_cross_sectional_pairs_real_aapl_googl_structure():
    assert (SRC / "AAPL.csv").exists()
    assert (SRC / "GOOGL.csv").exists()

    data = _build_pair_data()
    # Asymmetric quantiles (0.4/0.2) so the long and short books differ in size
    # and the strategy takes a genuine directional position. Symmetric
    # quantiles (e.g. 0.5/0.5) emit a "flat (zero) portfolio signal" warning
    # under net-exposure pricing and make the test structurally trivial.
    param_grid = {"lookback": [60], "top_quantile": [0.4], "bottom_quantile": [0.2]}

    buffer = io.StringIO()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with contextlib.redirect_stdout(buffer):
            result = cpcv_analysis(
                data=data,
                strategy_factory=_factory,
                param_grid=param_grid,
                n_splits=5,
                test_size=0.2,
                n_jobs=1,
                panel_pricing="book",
            )

    assert isinstance(result, dict)
    assert "folds" in result or "paths" in result or "summary" in result
    flat_warnings = [
        str(w.message) for w in caught
        if "flat (zero) portfolio signal" in str(w.message)
    ]
    assert flat_warnings == [], f"unexpected flat-signal warning: {flat_warnings}"


if __name__ == "__main__":
    test_cpcv_cross_sectional_pairs_real_aapl_googl_structure()
    print("OK")