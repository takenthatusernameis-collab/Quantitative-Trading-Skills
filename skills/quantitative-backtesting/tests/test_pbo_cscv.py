#!/usr/bin/env python3
"""Focused tests for the Probability of Backtest Overfitting (CSCV / PBO).

PBO (Bailey, Borwein, Lopez de Prado & Zhu, 2017) estimates how often the
configuration that wins in-sample ranks at or below the out-of-sample median.
It complements the Deflated Sharpe Ratio (which corrects a single selected
Sharpe) by measuring the selection procedure's own generalization behaviour.

The tests use constructed matrices with known answers so the estimate is
pinned exactly, plus one check on the committed family-returns fixture.
Offline, committed fixtures only; no live network.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import pbo_cscv  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _panel(values, n_obs, noise=1e-5, seed=3):
    """Build a (n_obs, N) panel from per-block offsets plus tiny noise."""
    rng = np.random.default_rng(seed)
    arr = np.repeat(np.asarray(values, dtype=float), n_obs, axis=0)
    return pd.DataFrame(arr + rng.normal(0.0, noise, arr.shape))


def test_pbo_returns_required_keys_and_bounds():
    rng = np.random.default_rng(7)
    returns = pd.DataFrame(rng.normal(0.0, 0.01, (320, 6)))
    out = pbo_cscv(returns, n_splits=8)

    for key in (
        "pbo",
        "is_overfit",
        "n_splits",
        "n_partitions",
        "n_partitions_evaluated",
        "n_trials",
        "n_observations",
        "mean_logit",
        "logits",
        "mean_oos_rank",
    ):
        assert key in out, key

    assert out["n_splits"] == 8
    assert out["n_partitions"] == 70  # C(8, 4)
    assert out["n_partitions_evaluated"] == 70
    assert out["n_trials"] == 6
    assert out["n_observations"] == 320
    assert 0.0 <= out["pbo"] <= 1.0
    assert 0.0 < out["mean_oos_rank"] < 1.0
    assert isinstance(out["is_overfit"], bool)
    assert out["is_overfit"] == (out["pbo"] > 0.5)
    assert len(out["logits"]) == out["n_partitions_evaluated"]


def test_pbo_zero_for_dominant_strategy():
    """A strategy with a large, stationary edge wins IS and OOS every time."""
    rng = np.random.default_rng(11)
    n_obs, n_noise = 400, 9
    panel = rng.normal(0.0, 0.02, (n_obs, n_noise + 1))
    panel[:, 0] = rng.normal(0.002, 0.001, n_obs)  # per-period Sharpe ~2
    out = pbo_cscv(pd.DataFrame(panel), n_splits=8)

    assert out["pbo"] == 0.0
    assert out["is_overfit"] is False
    assert out["mean_logit"] > 0.0


def test_pbo_one_for_anti_persistent_selection():
    """Whichever column wins in-sample loses out-of-sample in every split.

    Column A is strongly positive in block 0 and mildly negative in blocks
    1-3. Column B is flat. Partitions that include block 0 in-sample select A
    and see A lose out-of-sample; partitions that exclude block 0 select B
    and see A dominate out-of-sample. Either way the in-sample winner ends
    up at the out-of-sample bottom, so the PBO must be exactly 1.
    """
    block = 40
    offsets = [
        [0.02] * block,
        [-0.001] * block,
        [-0.001] * block,
        [-0.001] * block,
    ]
    col_a = np.concatenate(offsets)
    rng = np.random.default_rng(5)
    col_b = rng.normal(0.0, 1e-6, col_a.shape[0])
    panel = pd.DataFrame({"overfit": col_a, "flat": col_b})

    out = pbo_cscv(panel, n_splits=4)

    assert out["n_partitions"] == 6  # C(4, 2)
    assert out["pbo"] == 1.0
    assert out["is_overfit"] is True
    assert all(lam < 0.0 for lam in out["logits"])


def test_pbo_mean_metric_supported():
    rng = np.random.default_rng(13)
    returns = pd.DataFrame(rng.normal(0.0, 0.01, (160, 4)))
    out = pbo_cscv(returns, n_splits=4, metric="mean")
    assert 0.0 <= out["pbo"] <= 1.0


def test_pbo_committed_family_fixture_is_evaluable():
    matrix = pd.read_csv(FIXTURES / "family_returns.csv", index_col=0)
    out = pbo_cscv(matrix, n_splits=8)
    assert out["n_trials"] == matrix.shape[1]
    assert out["n_partitions_evaluated"] == out["n_partitions"] == 70
    assert np.isfinite(out["pbo"])
    assert 0.0 <= out["pbo"] <= 1.0


def test_pbo_rejects_invalid_inputs():
    panel = pd.DataFrame(np.zeros((100, 3)))
    with pytest.raises(ValueError):
        pbo_cscv(panel, n_splits=3)  # odd
    with pytest.raises(ValueError):
        pbo_cscv(panel, n_splits=2)  # too small
    with pytest.raises(ValueError):
        pbo_cscv(pd.DataFrame(np.zeros((100, 1))))  # one column
    with pytest.raises(ValueError):
        pbo_cscv(panel, n_splits=8, metric="sortino")
    with pytest.raises(ValueError):
        pbo_cscv(panel.iloc[:4], n_splits=8)  # too few observations


def test_pbo_drops_nan_rows():
    rng = np.random.default_rng(17)
    panel = pd.DataFrame(rng.normal(0.0, 0.01, (200, 4)))
    panel.iloc[5, 1] = np.nan
    out = pbo_cscv(panel, n_splits=4)
    assert out["n_observations"] == 199 - (199 % 4)
