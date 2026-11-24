#!/usr/bin/env python3
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(EXAMPLES_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import factor_attribution_example  # noqa: E402
from data_loader import load_data  # noqa: E402
from factor_models import _newey_west_var  # noqa: E402

SYMBOLS = ["AAPL", "MSFT", "GOOGL"]
DATA_DIR = Path(__file__).resolve().parent.parent / "assets" / "example_data" / "real_market_data"


def independent_recompute():
    close = factor_attribution_example.load_panel(SYMBOLS, DATA_DIR)
    returns = close.pct_change()
    asset_returns, exposures = factor_attribution_example.build_exposures(returns)
    # factor 1 = lagged return
    T = asset_returns.shape[0]
    lambdas = []
    for t in range(T):
        r = asset_returns[t]
        X = exposures[t][:, 1]
        valid = np.isfinite(r) & np.isfinite(X)
        if valid.sum() < 2:
            continue
        y = r[valid]; x = X[valid]
        # OLS slope (no intercept, single factor)
        beta = float(np.dot(x, y) / np.dot(x, x)) if np.dot(x, x) != 0 else float("nan")
        lambdas.append(beta)
    lambdas = np.array(lambdas)
    lam_hat = float(np.nanmean(lambdas))
    # NW t-stat
    series = lambdas - lambdas.mean()
    Tn = len(series)
    lrv = _newey_west_var(series)
    se = float(np.sqrt(lrv / Tn))
    t = float(np.sqrt(Tn) * lam_hat / se) if se > 0 else None
    return lam_hat, t, se, len(lambdas)


def test_reproducibility():
    with tempfile.TemporaryDirectory() as tmp:
        summary = factor_attribution_example.run_factor_attribution(output=tmp)
        artifact = Path(summary["artifact"])
        data = json.loads(artifact.read_text())
        lam_hat, t, se, n = independent_recompute()
        assert abs(data["lambda_hat"][1] - lam_hat) < 1e-9, (data["lambda_hat"][1], lam_hat)
        assert abs(data["t_stats"][1] - t) < 1e-6, (data["t_stats"][1], t)
        assert abs(data["se"][1] - se) < 1e-9, (data["se"][1], se)
        assert data["n_periods"] == n
    print("test_reproducibility PASSED")


if __name__ == "__main__":
    test_reproducibility()
    print("\nALL TESTS PASSED")
