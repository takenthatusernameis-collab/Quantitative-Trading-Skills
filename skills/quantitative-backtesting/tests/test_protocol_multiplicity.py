#!/usr/bin/env python3
"""Focused unit tests for the Bonferroni FWER correction helper.

Mirrors the contract and test style of test_romano_wolf_stepdown.py and
benjamini_hochberg. Offline, committed fixtures only; no live network.
"""

import sys
from pathlib import Path

import numpy as np

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from utils import bonferroni_correction  # noqa: E402


def test_bonferroni_single_test_no_penalty():
    """With 1 valid test, adjusted p equals the raw p (no multiplicity penalty)."""
    res = bonferroni_correction([0.03], alpha=0.05)
    assert res["n_tests"] == 1
    assert res["adjusted_p_values"] == [0.03]
    assert res["rejected"] == [True]
    assert res["n_rejected"] == 1
    assert res["alpha"] == 0.05


def test_bonferroni_zero_tests():
    """Empty input returns zeros and no rejections."""
    res = bonferroni_correction([], alpha=0.05)
    assert res["n_tests"] == 0
    assert res["adjusted_p_values"] == []
    assert res["rejected"] == []
    assert res["n_rejected"] == 0


def test_bonferroni_multiple_tests_adjusted_and_monotone():
    """Adjusted p = min(1, p * n_tests); monotonicity preserved."""
    res = bonferroni_correction([0.01, 0.02, 0.03], alpha=0.05)
    assert res["n_tests"] == 3
    assert res["adjusted_p_values"] == [0.03, 0.06, 0.09]
    # Monotonicity: adjusted p-values are non-decreasing with input p-values
    adj = res["adjusted_p_values"]
    assert all(adj[i] <= adj[i + 1] for i in range(len(adj) - 1))


def test_bonferroni_capped_at_one():
    """Adjusted p-values never exceed 1.0."""
    res = bonferroni_correction([0.5, 0.6, 0.7], alpha=0.05)
    assert res["n_tests"] == 3
    assert all(0.0 <= ap <= 1.0 for ap in res["adjusted_p_values"])
    assert res["adjusted_p_values"] == [1.0, 1.0, 1.0]


def test_bonferroni_nan_none_handled():
    """NaN/None entries get adjusted p = 1.0 and not rejected."""
    res = bonferroni_correction([0.01, float("nan"), None, 0.04], alpha=0.05)
    assert res["n_tests"] == 2  # only the finite ones count
    assert res["adjusted_p_values"][0] == 0.02
    assert res["adjusted_p_values"][1] == 1.0
    assert res["adjusted_p_values"][2] == 1.0
    assert res["adjusted_p_values"][3] == 0.08
    assert res["rejected"] == [True, False, False, False]


def test_bonferroni_out_of_range_clamped():
    """p > 1 clamped to 1.0; p < 0 clamped to 0.0 before adjustment."""
    res = bonferroni_correction([-0.1, 1.5, 0.02], alpha=0.05)
    assert res["n_tests"] == 3
    assert res["adjusted_p_values"] == [0.0, 1.0, 0.06]


def test_bonferroni_rejection_threshold():
    """Reject iff adjusted_p <= alpha."""
    res = bonferroni_correction([0.01, 0.02, 0.03], alpha=0.05)
    # adjusted: 0.03, 0.06, 0.09 -> only first rejected
    assert res["rejected"] == [True, False, False]
    assert res["n_rejected"] == 1

    res2 = bonferroni_correction([0.01, 0.02, 0.03], alpha=0.10)
    # adjusted: 0.03, 0.06, 0.09 -> all rejected at alpha=0.10
    assert res2["rejected"] == [True, True, True]
    assert res2["n_rejected"] == 3


def test_bonferroni_n_equals_one_noop():
    """n=1 is a no-op beyond the single test itself."""
    res = bonferroni_correction([0.04], alpha=0.05)
    assert res["adjusted_p_values"] == [0.04]
    assert res["rejected"] == [True]


def test_bonferroni_alpha_parameter_respected():
    """Different alpha thresholds change rejections, not adjusted p-values."""
    res1 = bonferroni_correction([0.02, 0.03], alpha=0.05)
    res2 = bonferroni_correction([0.02, 0.03], alpha=0.01)
    assert res1["adjusted_p_values"] == res2["adjusted_p_values"]
    assert res1["alpha"] == 0.05
    assert res2["alpha"] == 0.01


def test_bonferroni_return_keys_match_contract():
    """Return dict has exactly the keys specified in the docstring."""
    res = bonferroni_correction([0.01, 0.02])
    expected_keys = {"adjusted_p_values", "rejected", "alpha", "n_tests", "n_rejected"}
    assert set(res.keys()) == expected_keys


def test_bonferroni_matches_inline_calculation():
    """The helper produces the same result as the inline p * n_protocols pattern."""
    p = 0.5896
    n_protocols = 4
    inline = min(1.0, p * n_protocols)
    res = bonferroni_correction([p], alpha=0.10, )  # n_tests=1 -> adjusted = p
    # For n=1, Bonferroni is identity
    assert res["adjusted_p_values"][0] == p

    # With the full family of 4 protocols
    res_family = bonferroni_correction([p, 0.9988, 0.9819, 0.9661], alpha=0.10)
    assert res_family["n_tests"] == 4
    # The best p-value (0.5896) adjusted by 4
    assert abs(res_family["adjusted_p_values"][0] - 1.0) < 1e-10  # capped at 1.0


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))