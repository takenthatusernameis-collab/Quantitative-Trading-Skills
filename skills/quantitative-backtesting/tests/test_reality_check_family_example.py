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
    assert hasattr(module, "main")
    assert callable(module.run_reality_check_family_example)
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
