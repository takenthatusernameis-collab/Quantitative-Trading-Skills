#!/usr/bin/env python3
"""
Verification for the Fama-MacBeth factor-attribution worked example.

Runs factor_attribution_example.py end-to-end on committed real data
(AAPL / MSFT / GOOGL) and asserts the produced artifact is sane:

  * the example runs to completion (exit 0),
  * a factor_attribution.json artifact is written,
  * lambda_hat and t-statistics are finite,
  * at least one valid cross-sectional period was priced,
  * explained variance ratio lies in [0, 1].

Offline, deterministic, committed fixtures only; no network.
"""

import json
import sys
import tempfile
from pathlib import Path

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
sys.path.insert(0, str(EXAMPLES_DIR))

import factor_attribution_example  # noqa: E402


def test_example_runs_and_writes_artifact():
    with tempfile.TemporaryDirectory() as tmp:
        summary = factor_attribution_example.run_factor_attribution(output=tmp)
        artifact = Path(summary["artifact"])
        assert artifact.exists(), f"artifact not written: {artifact}"
        data = json.loads(artifact.read_text())

        assert data["symbols"] == ["AAPL", "MSFT", "GOOGL"]
        assert data["n_assets"] == 3
        assert data["n_factors"] == 2
        assert data["n_periods"] > 0, "no valid cross-sectional periods"

        lam = data["lambda_hat"][1]
        t = data["t_stats"][1]
        se = data["se"][1]
        assert np_is_finite(lam), f"lambda_hat not finite: {lam}"
        assert t is not None and np_is_finite(t), f"t-stat not finite: {t}"
        assert se is not None and np_is_finite(se) and se > 0, f"SE not finite/positive: {se}"

        evr = data["explained_variance_ratio"]
        assert 0.0 <= evr <= 1.0, f"explained variance ratio out of [0,1]: {evr}"

        assert data["data_range"][0] < data["data_range"][1]
    print("test_example_runs_and_writes_artifact PASSED")


def test_example_main_returns_zero():
    with tempfile.TemporaryDirectory() as tmp:
        rc = factor_attribution_example.main(["--output", tmp])
        assert rc == 0, f"main() returned {rc}"
        artifact = Path(tmp) / "factor_attribution.json"
        assert artifact.exists(), f"artifact not written: {artifact}"
    print("test_example_main_returns_zero PASSED")


def np_is_finite(x):
    return x is not None and float(x) == float(x) and abs(float(x)) != float("inf")


if __name__ == "__main__":
    test_example_runs_and_writes_artifact()
    test_example_main_returns_zero()
    print("\nALL TESTS PASSED")
