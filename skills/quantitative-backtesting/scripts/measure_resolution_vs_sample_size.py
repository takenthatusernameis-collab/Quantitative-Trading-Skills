#!/usr/bin/env python3
"""Measure the Deflated-Sharpe resolution as a function of sample size.

Reads the framework's own helpers (minimum_detectable_sharpe) and reports the
smallest confirmable annualized Sharpe at a ladder of sample sizes, on data
drawn from generate_positive_control_data with a representative regime length.
No threshold, bound, criterion or verdict is changed; this is a measurement
beside the verdict.
"""
import sys, tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))
from generate_positive_control_data import write_control_fixture
import falsifiable_hypothesis_example as ex

SIZES = [500, 1000, 2500, 5000]


def measure_one(periods):
    with tempfile.TemporaryDirectory() as d:
        write_control_fixture(Path(d), inject_effect=True, periods=periods)
        data = Path(d) / "sample_ohlcv.csv"
        res = ex.run_hypothesis_test(data)
        tr = res.get("resolution") or {}
        mds = tr.get("min_detectable_sharpe")
        obs = res.get("observed", {})
        return {
            "periods": periods,
            "test_observations": obs.get("test_n_observations"),
            "min_detectable_sharpe": mds,
            "plausible_bound": ex.PLAUSIBLE_MAX_ANNUALIZED_SHARPE,
        }


def main():
    for p in SIZES:
        r = measure_one(p)
        print(r)


if __name__ == "__main__":
    main()
