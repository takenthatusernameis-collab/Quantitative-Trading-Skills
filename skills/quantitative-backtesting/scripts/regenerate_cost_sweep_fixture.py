#!/usr/bin/env python3
"""Trim the cost sweep capture into its test fixture.

The capture is the tool's own --json output wrapped in a provenance block;
the fixture is the provenance block plus the rows, with each row's per-path
blocks reduced to the keys a re-capture summary rebuilds from. This keeps the
fixture small and pins the numbers the tests compare against.

Usage:
    python3 skills/quantitative-backtesting/scripts/regenerate_cost_sweep_fixture.py
"""
import json
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
CAPTURE = SKILLS_DIR / "results" / "resolution_floor" / "cost_sweep_2500_5000_10000.json"
FIXTURE = SKILLS_DIR / "tests" / "fixtures" / "cost_sweep_2500_5000_10000.json"

RECAPTURE_PATH_KEYS = (
    "alpha_beyond_plausible_bound",
    "alpha_reason",
    "alpha_status",
    "benchmark_alpha_std",
    "benchmark_alphas",
    "expected_max_alpha",
    "expected_max_sharpe",
    "min_detectable_alpha",
    "min_detectable_sharpe",
    "n_benchmarks",
    "n_parameter_trials",
    "n_test_observations",
    "n_windows",
    "observed_annualized_alpha",
    "observed_annualized_sharpe",
    "sharpe_beyond_plausible_bound",
    "sharpe_reason",
    "sharpe_status",
    "strategy_alpha",
)

PATHS = ("out_of_sample", "walk_forward", "cpcv")


def main() -> int:
    with open(CAPTURE, "r") as handle:
        capture = json.load(handle)

    trimmed = []
    for series in ("no_effect", "effect"):
        for row in capture["sweeps"][series]["rows"]:
            paths_out = {}
            for path in PATHS:
                block = row["paths"][path]
                paths_out[path] = {key: block[key] for key in RECAPTURE_PATH_KEYS}
            trimmed.append(
                {
                    "bars": row["bars"],
                    "seed": row["seed"],
                    "series": row["series"],
                    "cost_regime": row["cost_regime"],
                    "costs": row["costs"],
                    "paths": paths_out,
                }
            )

    fixture = {"provenance": capture["provenance"], "rows": trimmed}
    with open(FIXTURE, "w") as handle:
        json.dump(fixture, handle, indent=2, default=str)
        handle.write("\n")
    print(f"wrote {FIXTURE} ({len(trimmed)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())