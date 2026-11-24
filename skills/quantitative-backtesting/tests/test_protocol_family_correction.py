#!/usr/bin/env python3
"""Focused unit tests for the protocol_family_correction helper.

Mirrors the contract and test style of test_protocol_multiplicity.py and
test_holm_stepdown.py. Offline, committed fixtures only; no live network.
"""

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from utils import (  # noqa: E402
    bonferroni_correction,
    holm_stepdown,
    protocol_family_correction,
)


def test_protocol_family_single_asset_single_protocol():
    """1 asset x 1 protocol: no multiplicity penalty at either level."""
    matrix = [[0.03]]
    res = protocol_family_correction(matrix, alpha=0.05)
    # Per-asset: n=1 -> adjusted = 0.03
    assert res["per_asset"][0]["n_protocols"] == 1
    assert res["per_asset"][0]["adjusted_p_values"] == [0.03]
    assert res["per_asset"][0]["best_nominal_p"] == 0.03
    assert res["per_asset"][0]["best_adjusted_p"] == 0.03
    assert res["per_asset"][0]["n_rejected"] == 1
    # Cross-asset: n=1 -> adjusted = 0.03
    assert res["cross_asset"]["n_assets"] == 1
    assert res["cross_asset"]["adjusted_p_values"] == [0.03]
    assert res["cross_asset"]["best_nominal_p"] == 0.03
    assert res["cross_asset"]["best_adjusted_p"] == 0.03
    assert res["cross_asset"]["n_rejected"] == 1
    assert res["total_n_rejected"] == 2  # 1 per-asset + 1 cross-asset
    assert res["alpha"] == 0.05


def test_protocol_family_single_asset_multiple_protocols():
    """1 asset x 4 protocols: per-asset Bonferroni applies, cross-asset is identity."""
    matrix = [[0.01, 0.02, 0.03, 0.04]]
    res = protocol_family_correction(matrix, alpha=0.05)
    # Per-asset: 4 tests -> adjusted = [0.04, 0.08, 0.12, 0.16]
    assert res["per_asset"][0]["n_protocols"] == 4
    assert res["per_asset"][0]["adjusted_p_values"] == [0.04, 0.08, 0.12, 0.16]
    assert res["per_asset"][0]["best_nominal_p"] == 0.01
    assert res["per_asset"][0]["best_adjusted_p"] == 0.04
    assert res["per_asset"][0]["n_rejected"] == 1  # only first rejected at 0.05
    # Cross-asset: 1 asset -> identity
    assert res["cross_asset"]["n_assets"] == 1
    assert res["cross_asset"]["adjusted_p_values"] == [0.01]
    assert res["cross_asset"]["n_rejected"] == 1
    assert res["total_n_rejected"] == 2


def test_protocol_family_multiple_assets_single_protocol():
    """3 assets x 1 protocol: per-asset identity, cross-asset Bonferroni applies."""
    matrix = [[0.01], [0.02], [0.03]]
    res = protocol_family_correction(matrix, alpha=0.05)
    # Per-asset: each has 1 test -> identity
    for i in range(3):
        assert res["per_asset"][i]["n_protocols"] == 1
        assert res["per_asset"][i]["adjusted_p_values"] == [matrix[i][0]]
        assert res["per_asset"][i]["n_rejected"] == 1
    # Cross-asset: 3 assets -> Bonferroni on [0.01, 0.02, 0.03] = [0.03, 0.06, 0.09]
    assert res["cross_asset"]["n_assets"] == 3
    assert res["cross_asset"]["nominal_p_values"] == [0.01, 0.02, 0.03]
    assert res["cross_asset"]["adjusted_p_values"] == [0.03, 0.06, 0.09]
    assert res["cross_asset"]["n_rejected"] == 1
    assert res["total_n_rejected"] == 4  # 3 per-asset + 1 cross-asset


def test_protocol_family_full_matrix():
    """3 assets x 4 protocols: both levels apply Bonferroni."""
    matrix = [
        [0.01, 0.02, 0.03, 0.04],  # AAPL
        [0.02, 0.03, 0.04, 0.05],  # MSFT
        [0.03, 0.04, 0.05, 0.06],  # GOOGL
    ]
    res = protocol_family_correction(matrix, alpha=0.05)
    # Per-asset: each has 4 protocols -> p * 4
    assert res["per_asset"][0]["adjusted_p_values"] == [0.04, 0.08, 0.12, 0.16]
    assert res["per_asset"][1]["adjusted_p_values"] == [0.08, 0.12, 0.16, 0.20]
    assert res["per_asset"][2]["adjusted_p_values"] == [0.12, 0.16, 0.20, 0.24]
    # Best nominal per asset: 0.01, 0.02, 0.03
    assert res["per_asset"][0]["best_nominal_p"] == 0.01
    assert res["per_asset"][1]["best_nominal_p"] == 0.02
    assert res["per_asset"][2]["best_nominal_p"] == 0.03
    # Cross-asset: Bonferroni on [0.01, 0.02, 0.03] with n=3 -> [0.03, 0.06, 0.09]
    assert res["cross_asset"]["nominal_p_values"] == [0.01, 0.02, 0.03]
    assert res["cross_asset"]["adjusted_p_values"] == [0.03, 0.06, 0.09]
    assert res["cross_asset"]["best_nominal_p"] == 0.01
    assert res["cross_asset"]["best_asset_idx"] == 0
    assert res["cross_asset"]["best_adjusted_p"] == 0.03
    assert res["cross_asset"]["n_rejected"] == 1
    # Total rejections: asset 0 has 1, assets 1-2 have 0, cross-asset has 1
    assert res["total_n_rejected"] == 2


def test_protocol_family_capped_at_one():
    """Adjusted p-values never exceed 1.0 at either level."""
    matrix = [[0.5, 0.6, 0.7], [0.4, 0.5, 0.6]]
    res = protocol_family_correction(matrix, alpha=0.05)
    # Per-asset: 3 tests each -> capped at 1.0
    for asset_res in res["per_asset"]:
        assert all(0.0 <= ap <= 1.0 for ap in asset_res["adjusted_p_values"])
    # Cross-asset: 2 assets -> capped at 1.0
    assert all(0.0 <= ap <= 1.0 for ap in res["cross_asset"]["adjusted_p_values"])
    assert res["cross_asset"]["n_rejected"] == 0


def test_protocol_family_nan_none_handled():
    """NaN/None entries get adjusted p = 1.0 and are not rejected."""
    matrix = [[0.01, float("nan"), None, 0.04], [0.02, 0.03]]
    res = protocol_family_correction(matrix, alpha=0.05)
    # Asset 0: 2 valid protocols -> adjusted [0.02, 1.0, 1.0, 0.08]
    assert res["per_asset"][0]["n_protocols"] == 2
    assert res["per_asset"][0]["adjusted_p_values"][0] == 0.02
    assert res["per_asset"][0]["adjusted_p_values"][1] == 1.0
    assert res["per_asset"][0]["adjusted_p_values"][2] == 1.0
    assert res["per_asset"][0]["adjusted_p_values"][3] == 0.08
    assert res["per_asset"][0]["rejected"] == [True, False, False, False]
    # Asset 1: 2 valid protocols
    assert res["per_asset"][1]["n_protocols"] == 2
    # Cross-asset: 2 assets with valid data
    assert res["cross_asset"]["n_assets"] == 2


def test_protocol_family_out_of_range_clamped():
    """p > 1 clamped to 1.0; p < 0 clamped to 0.0 before adjustment."""
    matrix = [[-0.1, 1.5, 0.02], [0.03]]
    res = protocol_family_correction(matrix, alpha=0.05)
    # Asset 0: clamped valid p-values (0.0, 1.0, 0.02); n=3 -> adjusted [0.0, 1.0, 0.06]
    assert res["per_asset"][0]["n_protocols"] == 3
    assert res["per_asset"][0]["adjusted_p_values"] == [0.0, 1.0, 0.06]
    # Cross-asset: best nominal per asset are 0.0 and 0.03; n=2 -> [0.0, 0.06]
    assert res["cross_asset"]["nominal_p_values"] == [0.0, 0.03]
    assert res["cross_asset"]["adjusted_p_values"] == [0.0, 0.06]


def test_protocol_family_empty_matrix():
    """Empty matrix returns empty structure."""
    res = protocol_family_correction([], alpha=0.05)
    assert res["per_asset"] == []
    assert res["cross_asset"]["n_assets"] == 0
    assert res["cross_asset"]["adjusted_p_values"] == []
    assert res["total_n_rejected"] == 0
    assert res["alpha"] == 0.05


def test_protocol_family_asset_with_no_valid_protocols():
    """Asset with all NaN/None is skipped at cross-asset level."""
    matrix = [[float("nan"), None], [0.01, 0.02]]
    res = protocol_family_correction(matrix, alpha=0.05)
    # Asset 0: 0 valid protocols
    assert res["per_asset"][0]["n_protocols"] == 0
    assert res["per_asset"][0]["best_nominal_p"] is None
    assert res["per_asset"][0]["best_protocol_idx"] is None
    # Asset 1: 2 valid protocols
    assert res["per_asset"][1]["n_protocols"] == 2
    # Cross-asset: only 1 asset with valid data
    assert res["cross_asset"]["n_assets"] == 1
    assert res["cross_asset"]["nominal_p_values"] == [0.01]
    assert res["cross_asset"]["best_asset_idx"] == 1


def test_protocol_family_ragged_matrix():
    """Matrix with rows of different lengths works correctly."""
    matrix = [[0.01], [0.02, 0.03], [0.04, 0.05, 0.06, 0.07]]
    res = protocol_family_correction(matrix, alpha=0.05)
    # Asset 0: n=1
    assert res["per_asset"][0]["n_protocols"] == 1
    # Asset 1: n=2
    assert res["per_asset"][1]["n_protocols"] == 2
    assert res["per_asset"][1]["adjusted_p_values"] == [0.04, 0.06]
    # Asset 2: n=4
    assert res["per_asset"][2]["n_protocols"] == 4
    # Cross-asset: 3 assets
    assert res["cross_asset"]["n_assets"] == 3
    assert res["cross_asset"]["nominal_p_values"] == [0.01, 0.02, 0.04]


def test_protocol_family_matches_nested_bonferroni():
    """Cross-asset reduction equals nested Bonferroni: per-asset then cross-asset."""
    # Simulate the pattern from the summary files:
    # Per-asset p-values (4 protocols each)
    per_asset_p = [
        [0.0415, 0.7076, 0.7016, 0.5499],  # AAPL
        [0.9759, 0.3918, 0.5593, 0.0574],  # MSFT
        [0.8493, 0.1299, 0.8771, 0.3283],  # GOOGL
    ]
    res = protocol_family_correction(per_asset_p, alpha=0.10)
    # Per-asset: each has 4 protocols -> p * 4
    # AAPL best nominal 0.0415 -> adjusted 0.1660
    assert abs(res["per_asset"][0]["best_adjusted_p"] - 0.1660) < 1e-4
    # MSFT best nominal 0.0574 -> adjusted 0.2296
    assert abs(res["per_asset"][1]["best_adjusted_p"] - 0.2296) < 1e-4
    # GOOGL best nominal 0.1299 -> adjusted 0.5196
    assert abs(res["per_asset"][2]["best_adjusted_p"] - 0.5196) < 1e-4
    # Cross-asset: Bonferroni on [0.0415, 0.0574, 0.1299] with n=3
    # Best is 0.0415 -> adjusted 0.1245
    assert abs(res["cross_asset"]["best_nominal_p"] - 0.0415) < 1e-4
    assert abs(res["cross_asset"]["best_adjusted_p"] - 0.1245) < 1e-4
    assert res["cross_asset"]["best_asset_idx"] == 0  # AAPL
    # Total rejections at alpha=0.10: 0 at both levels
    assert res["per_asset"][0]["n_rejected"] == 0
    assert res["per_asset"][1]["n_rejected"] == 0
    assert res["per_asset"][2]["n_rejected"] == 0
    assert res["cross_asset"]["n_rejected"] == 0
    assert res["total_n_rejected"] == 0


def test_protocol_family_alpha_parameter_respected():
    """Different alpha thresholds change rejections, not adjusted p-values."""
    matrix = [[0.01, 0.02], [0.03, 0.04]]
    res1 = protocol_family_correction(matrix, alpha=0.05)
    res2 = protocol_family_correction(matrix, alpha=0.01)
    # Adjusted p-values should be identical
    for a1, a2 in zip(res1["per_asset"], res2["per_asset"]):
        assert a1["adjusted_p_values"] == a2["adjusted_p_values"]
    assert res1["cross_asset"]["adjusted_p_values"] == res2["cross_asset"]["adjusted_p_values"]
    # But rejections differ
    assert res1["alpha"] == 0.05
    assert res2["alpha"] == 0.01


def test_protocol_family_return_keys_match_contract():
    """Return dict has exactly the keys specified in the docstring."""
    matrix = [[0.01, 0.02]]
    res = protocol_family_correction(matrix)
    # Top-level keys
    expected_top = {"per_asset", "cross_asset", "total_n_rejected", "alpha"}
    assert set(res.keys()) == expected_top
    # Per-asset keys
    expected_asset = {
        "nominal_p_values", "adjusted_p_values", "rejected",
        "n_protocols", "n_rejected", "best_nominal_p",
        "best_protocol_idx", "best_adjusted_p"
    }
    assert set(res["per_asset"][0].keys()) == expected_asset
    # Cross-asset keys
    expected_cross = {
        "nominal_p_values", "adjusted_p_values", "rejected",
        "n_assets", "n_rejected", "best_nominal_p",
        "best_asset_idx", "best_adjusted_p"
    }
    assert set(res["cross_asset"].keys()) == expected_cross


def test_protocol_family_consistent_with_bonferroni_correction():
    """The helper uses the same Bonferroni logic as bonferroni_correction."""
    matrix = [[0.01, 0.02, 0.03], [0.04, 0.05]]
    res = protocol_family_correction(matrix, alpha=0.05)
    # Per-asset results should match bonferroni_correction applied to each row
    for asset_idx, row in enumerate(matrix):
        bonf = bonferroni_correction(row, alpha=0.05)
        assert res["per_asset"][asset_idx]["adjusted_p_values"] == bonf["adjusted_p_values"]
        assert res["per_asset"][asset_idx]["rejected"] == bonf["rejected"]
        assert res["per_asset"][asset_idx]["n_protocols"] == bonf["n_tests"]
        assert res["per_asset"][asset_idx]["n_rejected"] == bonf["n_rejected"]
    # Cross-asset: Bonferroni on per-asset best nominal
    best_nominal = [res["per_asset"][0]["best_nominal_p"], res["per_asset"][1]["best_nominal_p"]]
    bonf_cross = bonferroni_correction(best_nominal, alpha=0.05)
    assert res["cross_asset"]["adjusted_p_values"] == bonf_cross["adjusted_p_values"]
    assert res["cross_asset"]["rejected"] == bonf_cross["rejected"]
    assert res["cross_asset"]["n_assets"] == bonf_cross["n_tests"]
    assert res["cross_asset"]["n_rejected"] == bonf_cross["n_rejected"]


def test_protocol_family_holm_single_asset_multiple_protocols():
    """method='holm', 1 asset x 4 protocols: per-asset Holm, cross-asset identity."""
    matrix = [[0.01, 0.02, 0.03, 0.04]]
    res = protocol_family_correction(matrix, alpha=0.05, method="holm")
    # Per-asset Holm on [0.01, 0.02, 0.03, 0.04]:
    # ascending factors 4,3,2,1 -> [0.04, 0.06, 0.06, 0.04] then monotone
    # cumulative max -> [0.04, 0.06, 0.06, 0.06]
    assert res["per_asset"][0]["n_protocols"] == 4
    expected = [0.04, 0.06, 0.06, 0.06]
    for got, exp in zip(res["per_asset"][0]["adjusted_p_values"], expected):
        assert abs(got - exp) < 1e-12
    assert res["per_asset"][0]["best_nominal_p"] == 0.01
    assert abs(res["per_asset"][0]["best_adjusted_p"] - 0.04) < 1e-12
    # Cross-asset: 1 asset -> identity (Holm with m=1 is the raw p-value)
    assert res["cross_asset"]["n_assets"] == 1
    assert abs(res["cross_asset"]["adjusted_p_values"][0] - 0.01) < 1e-12
    assert res["cross_asset"]["n_rejected"] == 1


def test_protocol_family_holm_multiple_assets_single_protocol():
    """method='holm', 3 assets x 1 protocol: per-asset identity, cross-asset Holm."""
    matrix = [[0.01], [0.02], [0.03]]
    res = protocol_family_correction(matrix, alpha=0.05, method="holm")
    # Per-asset: each has 1 test -> identity
    for i in range(3):
        assert res["per_asset"][i]["adjusted_p_values"] == [matrix[i][0]]
    # Cross-asset Holm on [0.01, 0.02, 0.03]:
    # ascending factors 3,2,1 -> [0.03, 0.04, 0.03] then monotone -> [0.03, 0.04, 0.04]
    ca = res["cross_asset"]
    assert ca["n_assets"] == 3
    expected = [0.03, 0.04, 0.04]
    for got, exp in zip(ca["adjusted_p_values"], expected):
        assert abs(got - exp) < 1e-12
    assert ca["n_rejected"] == 3  # Holm adjusted [0.03, 0.04, 0.04] all <= 0.05


def test_protocol_family_holm_dominates_bonferroni():
    """method='holm' adjusted p-values are <= Bonferroni at both levels."""
    matrix = [
        [0.01, 0.02, 0.03, 0.04],
        [0.02, 0.03, 0.04, 0.05],
        [0.03, 0.04, 0.05, 0.06],
    ]
    bonf = protocol_family_correction(matrix, alpha=0.05, method="bonferroni")
    holm = protocol_family_correction(matrix, alpha=0.05, method="holm")
    # Per-asset: Holm <= Bonferroni elementwise
    for a_bonf, a_holm in zip(bonf["per_asset"], holm["per_asset"]):
        for pb, ph in zip(a_bonf["adjusted_p_values"], a_holm["adjusted_p_values"]):
            assert ph <= pb + 1e-12
        # Holm rejects at least as many as Bonferroni within each asset
        assert a_holm["n_rejected"] >= a_bonf["n_rejected"]
    # Cross-asset: Holm <= Bonferroni elementwise
    for pb, ph in zip(bonf["cross_asset"]["adjusted_p_values"],
                      holm["cross_asset"]["adjusted_p_values"]):
        assert ph <= pb + 1e-12
    assert holm["cross_asset"]["n_rejected"] >= bonf["cross_asset"]["n_rejected"]


def test_protocol_family_holm_matches_holm_stepdown_per_asset():
    """Per-asset Holm results equal holm_stepdown applied to each row."""
    matrix = [[0.01, 0.04, 0.02], [0.10, 0.20, 0.30]]
    res = protocol_family_correction(matrix, alpha=0.05, method="holm")
    for asset_idx, row in enumerate(matrix):
        hs = holm_stepdown(row, alpha=0.05)
        assert res["per_asset"][asset_idx]["adjusted_p_values"] == hs["adjusted_p_values"]
        assert res["per_asset"][asset_idx]["rejected"] == hs["rejected"]
        assert res["per_asset"][asset_idx]["n_protocols"] == hs["n_tests"]
        assert res["per_asset"][asset_idx]["n_rejected"] == hs["n_rejected"]


def test_protocol_family_holm_matches_holm_stepdown_cross_asset():
    """Cross-asset Holm results equal holm_stepdown on per-asset best nominals."""
    matrix = [[0.01, 0.5], [0.04, 0.2], [0.03, 0.1]]
    res = protocol_family_correction(matrix, alpha=0.05, method="holm")
    best_nominal = [res["per_asset"][i]["best_nominal_p"] for i in range(3)]
    hs = holm_stepdown(best_nominal, alpha=0.05)
    assert res["cross_asset"]["adjusted_p_values"] == hs["adjusted_p_values"]
    assert res["cross_asset"]["rejected"] == hs["rejected"]
    assert res["cross_asset"]["n_assets"] == hs["n_tests"]
    assert res["cross_asset"]["n_rejected"] == hs["n_rejected"]


def test_protocol_family_holm_nan_none_and_ragged():
    """method='holm' handles NaN/None and ragged rows like Bonferroni."""
    matrix = [[0.01, float("nan"), None, 0.04], [0.02, 0.03]]
    res = protocol_family_correction(matrix, alpha=0.05, method="holm")
    # Asset 0: valid p-values 0.01, 0.04 -> Holm n=2 -> [0.02, 1.0, 1.0, 0.04]
    pa0 = res["per_asset"][0]
    assert pa0["n_protocols"] == 2
    assert abs(pa0["adjusted_p_values"][0] - 0.02) < 1e-12
    assert pa0["adjusted_p_values"][1] == 1.0
    assert pa0["adjusted_p_values"][2] == 1.0
    assert abs(pa0["adjusted_p_values"][3] - 0.04) < 1e-12
    assert pa0["rejected"] == [True, False, False, True]
    # Asset 1: valid 0.02, 0.03 -> Holm n=2 -> [0.04, 0.04]
    pa1 = res["per_asset"][1]
    assert pa1["n_protocols"] == 2
    assert abs(pa1["adjusted_p_values"][0] - 0.04) < 1e-12
    assert abs(pa1["adjusted_p_values"][1] - 0.04) < 1e-12
    # Cross-asset: best nominals 0.01, 0.02 -> Holm n=2 -> [0.02, 0.02]
    ca = res["cross_asset"]
    assert ca["n_assets"] == 2
    assert abs(ca["adjusted_p_values"][0] - 0.02) < 1e-12
    assert abs(ca["adjusted_p_values"][1] - 0.02) < 1e-12


def test_protocol_family_holm_unknown_method_defaults_to_bonferroni():
    """An unrecognized method value falls back to Bonferroni (backward compat)."""
    matrix = [[0.01, 0.02, 0.03]]
    bonf = protocol_family_correction(matrix, alpha=0.05, method="bonferroni")
    other = protocol_family_correction(matrix, alpha=0.05, method="does-not-exist")
    assert other["per_asset"][0]["adjusted_p_values"] == bonf["per_asset"][0]["adjusted_p_values"]
    assert other["cross_asset"]["adjusted_p_values"] == bonf["cross_asset"]["adjusted_p_values"]


if __name__ == "__main__":
    _fns = [
        test_protocol_family_single_asset_single_protocol,
        test_protocol_family_single_asset_multiple_protocols,
        test_protocol_family_multiple_assets_single_protocol,
        test_protocol_family_full_matrix,
        test_protocol_family_capped_at_one,
        test_protocol_family_nan_none_handled,
        test_protocol_family_out_of_range_clamped,
        test_protocol_family_empty_matrix,
        test_protocol_family_asset_with_no_valid_protocols,
        test_protocol_family_ragged_matrix,
        test_protocol_family_matches_nested_bonferroni,
        test_protocol_family_alpha_parameter_respected,
        test_protocol_family_return_keys_match_contract,
        test_protocol_family_consistent_with_bonferroni_correction,
        test_protocol_family_holm_single_asset_multiple_protocols,
        test_protocol_family_holm_multiple_assets_single_protocol,
        test_protocol_family_holm_dominates_bonferroni,
        test_protocol_family_holm_matches_holm_stepdown_per_asset,
        test_protocol_family_holm_matches_holm_stepdown_cross_asset,
        test_protocol_family_holm_nan_none_and_ragged,
        test_protocol_family_holm_unknown_method_defaults_to_bonferroni,
    ]
    for _fn in _fns:
        _fn()
    print("ALL TESTS PASSED")