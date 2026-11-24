#!/usr/bin/env python3
"""Reproducibility hardening: determinism regression guard for the
family-wise statistical engine.

The Reality Check and Romano-Wolf stepdown procedures draw their stationary
block-bootstrap resamples from ``np.random.default_rng(seed)``. This test
locks the reproducibility invariant: identical inputs plus an identical seed
must produce bit-identical statistics (test statistic, p-value, adjusted
p-values, confidence bounds, rejection counts) across repeated runs. A future
change that introduces a fresh or global RNG into the bootstrap path fails
this guard.

Offline, deterministic synthetic inputs only; no network, no fixtures, no
randomness outside the seeded engine under test.
"""
import sys
from pathlib import Path

import numpy as np

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from utils import reality_check_test, romano_wolf_stepdown

N_OBS = 252
N_STRATEGIES = 4
SEED = 20261123
N_BOOTSTRAP = 400
BLOCK_SIZE = 8
ALPHA = 0.05


def _build_inputs():
    # Fixed input data (not the SUT's randomness): one deterministic draw so
    # the identical matrix is fed to both repeated runs.
    data_rng = np.random.default_rng(777)
    F = data_rng.normal(loc=0.0004, scale=0.015, size=(N_OBS, N_STRATEGIES))
    # Give one strategy a persistent edge so the family is not degenerate.
    F[:, 0] += 0.0012
    benchmark = data_rng.normal(loc=0.0002, scale=0.012, size=N_OBS)
    return F, benchmark


def test_reality_check_deterministic_given_seed():
    F, benchmark = _build_inputs()
    kwargs = dict(
        benchmark=benchmark, n_bootstrap=N_BOOTSTRAP, block_size=BLOCK_SIZE,
        seed=SEED, studentize=True, alpha=ALPHA,
    )
    first = reality_check_test(F, **kwargs)
    second = reality_check_test(F, **kwargs)
    assert first == second, (
        "Reality Check output is not deterministic given seed: "
        f"{first} != {second}"
    )


def test_romano_wolf_deterministic_given_seed():
    F, benchmark = _build_inputs()
    kwargs = dict(
        benchmark=benchmark, n_bootstrap=N_BOOTSTRAP, block_size=BLOCK_SIZE,
        seed=SEED, studentize=True, alpha=ALPHA, ci_level=0.95,
    )
    first = romano_wolf_stepdown(F, **kwargs)
    second = romano_wolf_stepdown(F, **kwargs)
    assert first == second, (
        "Romano-Wolf output is not deterministic given seed: "
        f"{first} != {second}"
    )


def test_reality_check_unseeded_returns_valid_shape():
    F, benchmark = _build_inputs()
    result = reality_check_test(
        F, benchmark=benchmark, n_bootstrap=N_BOOTSTRAP,
        block_size=BLOCK_SIZE, seed=None, studentize=True, alpha=ALPHA,
    )
    assert 0.0 <= result["p_value"] <= 1.0
    assert result["n_observations"] == N_OBS
    assert result["n_strategies"] == N_STRATEGIES


if __name__ == "__main__":
    test_reality_check_deterministic_given_seed()
    test_romano_wolf_deterministic_given_seed()
    test_reality_check_unseeded_returns_valid_shape()
    print("OK")
