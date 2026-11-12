#!/usr/bin/env python3
"""End-to-end test for the Reality Check family example.

Runs the committed-fixture example that builds a K-column OOS return matrix
from multiple strategies and applies ``utils.reality_check_test``. Offline,
committed fixtures only; no live network.
"""

import importlib.util
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
EXAMPLE_PATH = SKILLS_DIR / "examples" / "reality_check_family_example.py"


def _import_module(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_reality_check_family_example_imports():
    module = _import_module("reality_check_family_example", EXAMPLE_PATH)
    assert hasattr(module, "run_reality_check_family_example")
    assert hasattr(module, "run_reality_check_family_example_benchmark_subtracted")
    assert hasattr(module, "run_romano_wolf_family_stepdown")
    assert hasattr(module, "run_romano_wolf_family_stepdown_benchmark_subtracted")
    assert hasattr(module, "main")
    assert callable(module.run_reality_check_family_example)
    assert callable(module.run_reality_check_family_example_benchmark_subtracted)
    assert callable(module.run_romano_wolf_family_stepdown)
    assert callable(module.run_romano_wolf_family_stepdown_benchmark_subtracted)
    assert callable(module.main)


def test_reality_check_family_example_runs_and_returns_valid_result():
    module = _import_module("reality_check_family_example_run", EXAMPLE_PATH)
    rc, family_returns = module.run_reality_check_family_example(seed=12345, n_bootstrap=200)

    # Family / alignment checks
    assert family_returns.shape[1] == len(module.STRATEGIES) >= 2
    assert rc["n_strategies"] == family_returns.shape[1]
    assert rc["n_observations"] == len(family_returns)
    assert rc["n_observations"] >= 50
    assert list(family_returns.columns) == rc["strategy_names"]

    # Result contract
    for key in (
        "test_statistic",
        "p_value",
        "studentized",
        "n_strategies",
        "n_observations",
        "block_size",
        "n_bootstrap",
        "best_index",
        "best_mean",
        "means",
        "alpha",
        "significant",
        "strategy_names",
    ):
        assert key in rc
    assert rc["studentized"] is True
    assert rc["n_bootstrap"] == 200
    assert 0.0 <= rc["p_value"] <= 1.0
    assert 0 <= rc["best_index"] < rc["n_strategies"]
    assert len(rc["means"]) == rc["n_strategies"]
    assert isinstance(rc["significant"], bool)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))


def test_reality_check_family_example_benchmark_subtracted():
    """Benchmark-subtracted Reality Check: H0 no strategy beats buy-and-hold MSFT."""
    module = _import_module("reality_check_family_example_bench", EXAMPLE_PATH)
    rc, family_returns, bench_aligned = module.run_reality_check_family_example_benchmark_subtracted(
        seed=12345, n_bootstrap=200
    )

    assert family_returns.shape[1] == len(module.STRATEGIES) >= 2
    assert rc["n_strategies"] == family_returns.shape[1]
    assert rc["n_observations"] == len(family_returns) == len(bench_aligned)
    assert rc["n_observations"] >= 50
    assert list(family_returns.columns) == rc["strategy_names"]
    assert rc.get("benchmark") == "MSFT"

    assert rc["studentized"] is True
    assert rc["n_bootstrap"] == 200
    assert 0.0 <= rc["p_value"] <= 1.0
    assert 0 <= rc["best_index"] < rc["n_strategies"]
    assert len(rc["means"]) == rc["n_strategies"]
    assert isinstance(rc["significant"], bool)

    # Benchmark subtraction must change the family means (not identical to raw means).
    rc_raw, _ = module.run_reality_check_family_example(seed=12345, n_bootstrap=200)
    assert rc["means"] != rc_raw["means"]


def test_reality_check_family_example_romano_wolf_stepdown():
    """Romano-Wolf stepdown returns a valid FWER-controlled ranking."""
    module = _import_module("reality_check_family_example_rw", EXAMPLE_PATH)
    rw = module.run_romano_wolf_family_stepdown(seed=12345, n_bootstrap=200)

    assert rw["n_strategies"] == len(module.STRATEGIES) >= 2
    assert rw["n_observations"] >= 50
    assert len(rw["ordered_indices"]) == rw["n_strategies"]
    assert sorted(rw["ordered_indices"]) == list(range(rw["n_strategies"]))
    assert rw["strategy_names"] == [name for name, _ in module.STRATEGIES]

    assert len(rw["p_values"]) == rw["n_strategies"]
    assert len(rw["adjusted_p_values"]) == rw["n_strategies"]
    assert len(rw["rejected"]) == rw["n_strategies"]
    assert 0 <= rw["n_rejected"] <= rw["n_strategies"]
    assert all(0.0 <= p <= 1.0 for p in rw["adjusted_p_values"])
    assert all(
        rw["adjusted_p_values"][i] <= rw["adjusted_p_values"][i + 1]
        for i in range(rw["n_strategies"] - 1)
    )
    # Rejections are a prefix of the ordered ranking.
    seen_false = False
    for r in rw["rejected"]:
        if not r:
            seen_false = True
        else:
            assert not seen_false

    # The example path must carry the FWER-adjusted simultaneous bands too.
    assert len(rw["simultaneous_ci_lower"]) == rw["n_strategies"]
    assert len(rw["simultaneous_ci_upper"]) == rw["n_strategies"]
    assert rw["simultaneous_ci_method"] == "max-t"
    assert rw["simultaneous_ci_level"] == 0.95
    for lo, hi, mean in zip(
        rw["simultaneous_ci_lower"], rw["simultaneous_ci_upper"], rw["means"]
    ):
        assert lo <= mean <= hi


def test_reality_check_family_example_romano_wolf_benchmark_subtracted():
    """Benchmark-subtracted Romano-Wolf: aligned lengths, reordering, adjusted p-values change."""
    module = _import_module("reality_check_family_example_rw_bench", EXAMPLE_PATH)
    rw, family_aligned, bench_aligned = module.run_romano_wolf_family_stepdown_benchmark_subtracted(
        seed=12345, n_bootstrap=200
    )

    # Aligned lengths match
    assert rw["n_observations"] == len(family_aligned) == len(bench_aligned)
    assert rw["n_observations"] >= 50
    assert rw["n_strategies"] == family_aligned.shape[1] >= 2
    assert list(family_aligned.columns) == rw["strategy_names"]
    assert rw.get("benchmark") == "MSFT"

    # Adjusted p-values are non-decreasing and rejections form a prefix
    assert len(rw["adjusted_p_values"]) == rw["n_strategies"]
    assert all(0.0 <= p <= 1.0 for p in rw["adjusted_p_values"])
    assert all(
        rw["adjusted_p_values"][i] <= rw["adjusted_p_values"][i + 1]
        for i in range(rw["n_strategies"] - 1)
    )
    seen_false = False
    for r in rw["rejected"]:
        if not r:
            seen_false = True
        else:
            assert not seen_false

    # Benchmark subtraction must change the adjusted p-values (not identical to raw stepdown)
    rw_raw = module.run_romano_wolf_family_stepdown(seed=12345, n_bootstrap=200)
    assert rw["adjusted_p_values"] != rw_raw["adjusted_p_values"]
    # Benchmark subtraction must change the reported mean excess returns.
    assert rw["means"] != rw_raw["means"]


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
