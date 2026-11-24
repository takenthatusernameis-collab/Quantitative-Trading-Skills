#!/usr/bin/env python3
"""Focused unit tests for the Holm (1979) step-down FWER correction helper.

Mirrors the contract and test style of test_protocol_multiplicity.py and
test_romano_wolf_stepdown.py. Offline, committed fixtures only; no live network.
"""

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from utils import bonferroni_correction, holm_stepdown  # noqa: E402


def test_holm_single_test_no_penalty():
    """With 1 valid test, adjusted p equals the raw p (no multiplicity penalty)."""
    res = holm_stepdown([0.03], alpha=0.05)
    assert res["n_tests"] == 1
    assert res["adjusted_p_values"] == [0.03]
    assert res["rejected"] == [True]
    assert res["n_rejected"] == 1
    assert res["alpha"] == 0.05


def test_holm_zero_tests():
    """Empty input returns no adjusted p-values and no rejections."""
    res = holm_stepdown([], alpha=0.05)
    assert res["n_tests"] == 0
    assert res["adjusted_p_values"] == []
    assert res["rejected"] == []
    assert res["n_rejected"] == 0


def test_holm_multiple_tests_adjusted_and_monotone():
    """Adjusted p = monotone-cummin of (m - k + 1) * p_(k), capped at 1.

    For [0.01, 0.02, 0.03] (m=3) the raw step-down values are
    3*0.01=0.03, 2*0.02=0.04, 1*0.03=0.03; the cumulative max makes the
    last entry 0.04 so the adjusted p-values are non-decreasing.
    """
    res = holm_stepdown([0.01, 0.02, 0.03], alpha=0.05)
    assert res["n_tests"] == 3
    assert res["adjusted_p_values"] == [0.03, 0.04, 0.04]
    adj = res["adjusted_p_values"]
    assert all(adj[i] <= adj[i + 1] for i in range(len(adj) - 1))


def test_holm_capped_at_one():
    """Adjusted p-values never exceed 1.0."""
    res = holm_stepdown([0.5, 0.6, 0.7], alpha=0.05)
    assert res["n_tests"] == 3
    assert all(0.0 <= ap <= 1.0 for ap in res["adjusted_p_values"])
    assert res["adjusted_p_values"] == [1.0, 1.0, 1.0]


def test_holm_nan_none_handled():
    """NaN/None entries get adjusted p = 1.0 and are not rejected."""
    res = holm_stepdown([0.01, float("nan"), None, 0.04], alpha=0.05)
    assert res["n_tests"] == 2  # only the finite ones count
    # m=2 over the two valid p-values (0.01, 0.04):
    #   0.01 -> 2*0.01 = 0.02 ; 0.04 -> 1*0.04 = 0.04
    assert res["adjusted_p_values"][0] == 0.02
    assert res["adjusted_p_values"][1] == 1.0
    assert res["adjusted_p_values"][2] == 1.0
    assert res["adjusted_p_values"][3] == 0.04
    assert res["rejected"] == [True, False, False, True]


def test_holm_out_of_range_clamped():
    """p > 1 clamped to 1.0; p < 0 clamped to 0.0 before adjustment."""
    res = holm_stepdown([-0.1, 1.5, 0.02], alpha=0.05)
    assert res["n_tests"] == 3
    # clamped valid p-values (0.0, 1.0, 0.02); ascending: 0.0*3, 0.02*2, 1.0*1
    assert res["adjusted_p_values"] == [0.0, 1.0, 0.04]


def test_holm_rejection_threshold():
    """Reject iff adjusted_p <= alpha."""
    res = holm_stepdown([0.01, 0.02, 0.03], alpha=0.05)
    # adjusted: 0.03, 0.04, 0.04 -> all <= 0.05
    assert res["rejected"] == [True, True, True]
    assert res["n_rejected"] == 3

    res2 = holm_stepdown([0.01, 0.02, 0.03], alpha=0.03)
    # adjusted: 0.03, 0.04, 0.04 -> only first <= 0.03
    assert res2["rejected"] == [True, False, False]
    assert res2["n_rejected"] == 1


def test_holm_n_equals_one_noop():
    """n=1 is a no-op beyond the single test itself."""
    res = holm_stepdown([0.04], alpha=0.05)
    assert res["adjusted_p_values"] == [0.04]
    assert res["rejected"] == [True]


def test_holm_alpha_parameter_respected():
    """Different alpha thresholds change rejections, not adjusted p-values."""
    res1 = holm_stepdown([0.02, 0.03], alpha=0.05)
    res2 = holm_stepdown([0.02, 0.03], alpha=0.01)
    assert res1["adjusted_p_values"] == res2["adjusted_p_values"]
    assert res1["alpha"] == 0.05
    assert res2["alpha"] == 0.01


def test_holm_return_keys_match_contract():
    """Return dict has exactly the keys specified in the docstring."""
    res = holm_stepdown([0.01, 0.02])
    expected_keys = {"adjusted_p_values", "rejected", "alpha", "n_tests", "n_rejected"}
    assert set(res.keys()) == expected_keys


def test_holm_dominates_bonferroni():
    """Holm adjusted p-values are <= Bonferroni's for every input, so Holm
    rejects at least as many hypotheses at the same alpha (uniformly more
    powerful single-step vs step-down FWER control)."""
    families = [
        [0.01, 0.02, 0.03],
        [0.04, 0.04, 0.04, 0.04],
        [0.001, 0.2, 0.5, 0.9],
        [0.5, 0.6, 0.7],
    ]
    for fam in families:
        h = holm_stepdown(fam, alpha=0.05)
        b = bonferroni_correction(fam, alpha=0.05)
        for hp, bp in zip(h["adjusted_p_values"], b["adjusted_p_values"]):
            assert hp <= bp + 1e-12, (fam, hp, bp)
        assert h["n_rejected"] >= b["n_rejected"], fam


def test_holm_stepdown_decision_matches_ordered_procedure():
    """Adjusted-p rejection reproduces the classic ordered step-down decision:
    walk p-values ascending, reject while p_(k) <= alpha / (m - k + 1),
    stop at the first failure."""
    p = [0.01, 0.015, 0.04, 0.2]
    alpha = 0.05
    m = len(p)
    ordered = sorted(p)
    expected = [False] * m
    for k, pv in enumerate(ordered):
        if pv <= alpha / (m - k):
            expected[k] = True
        else:
            break
    # Map back to original order
    exp_by_value = {}
    for k, pv in enumerate(ordered):
        exp_by_value[pv] = expected[k]
    expected_original = [exp_by_value[v] for v in p]

    res = holm_stepdown(p, alpha=alpha)
    assert res["rejected"] == expected_original


if __name__ == "__main__":
    _fns = [
        test_holm_single_test_no_penalty,
        test_holm_zero_tests,
        test_holm_multiple_tests_adjusted_and_monotone,
        test_holm_capped_at_one,
        test_holm_nan_none_handled,
        test_holm_out_of_range_clamped,
        test_holm_rejection_threshold,
        test_holm_n_equals_one_noop,
        test_holm_alpha_parameter_respected,
        test_holm_return_keys_match_contract,
        test_holm_dominates_bonferroni,
        test_holm_stepdown_decision_matches_ordered_procedure,
    ]
    for _fn in _fns:
        _fn()
    print("ALL TESTS PASSED")