#!/usr/bin/env python3
"""Regime-aware capacity: the capacity estimate reflects the regime mix.

The basket capacity from :func:`walk_forward.estimate_capacity` is a pure
liquidity property: ``capacity = max_impact * ADV_notional / impact_coefficient``
(linear) or ``(max_impact / impact_coefficient) ** 2 * ADV_notional`` (sqrt).
Historically the ``impact_coefficient`` was a single flat number, so the
reported capacity was BLIND to the market regime the strategy traded through --
even when the caller passed ``regime_impact_coefficients`` to make the *return*
path charge more impact in stressed/illiquid regimes, the capacity number did
not move.

This test pins the fix:

* ``estimate_capacity`` now accepts an optional ``regime_impact_coefficients``
  dict. When provided, the flat coefficient is replaced by the ADV-weighted
  mean of the per-period regime-specific coefficients over the window (each
  period's coefficient is the mapped regime coefficient, falling back to the
  base ``impact_coefficient`` for unmapped regimes; weights are the per-period
  binding ADV notional). A stressed regime with a higher coefficient therefore
  LOWERS the reported capacity.
* The default (``None`` / empty dict) leaves ``impact_coefficient`` unchanged,
  so every published number is byte-identical -- asserted here against the
  committed flat value.
* ``walk_forward_analysis`` wires the same ``regime_impact_coefficients`` into
  the capacity estimate, so ``summary["capacity"]`` reflects the regime mix.

No profitability claim is made: capacity is an execution-side control, and the
committed fixtures are regression guards on committed data, NOT evidence about
real securities (see PROVENANCE.json).

Offline, committed fixtures only
(assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv). No live network.
"""
import json
import sys
import warnings
import contextlib
import io
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

import pandas as pd  # noqa: E402

from walk_forward import walk_forward_analysis, estimate_capacity  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402
from regime_detection import detect_combined_regime  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade
IMPACT_COEFFICIENT = 0.1

# Pre-registered narrow grid around the cross-sectional momentum settings.
# Matches test_cross_method_capacity_pricing_invariance_real_triple_aapl_msft_googl.py.
PARAM_GRID = {
    "lookback": [10, 20],
    "top_quantile": [0.4],
    "bottom_quantile": [0.2],
}

TRAIN_MONTHS = 12
TEST_MONTHS = 12
STEP_MONTHS = 12

# Stressed regimes = high volatility or bear (lower liquidity -> higher impact).
# Labels are ``{bull,bear,sideways}_{high,low}`` from detect_combined_regime.
STRESSED_IMPACT = 0.5
STRESSED_REGIMES = ("bear_high", "bear_low", "sideways_high", "bull_high")
REGIME_DICT = {label: STRESSED_IMPACT for label in STRESSED_REGIMES}

# Measured on the committed triple panel at IMPACT_COEFFICIENT=0.1.
#   flat   : regime_impact_coefficients=None (default path, byte-identical).
#   regime : the stressed-regime dict above (ADV-weighted effective coeff
#            ~0.2375 > 0.1, so capacity falls to ~42.1% of flat).
EXPECTED_FLAT_CAPACITY = 146092783.94110104
EXPECTED_REGIME_CAPACITY = 61518711.016243525
EXPECTED_REGIME_EFFECTIVE_COEFF = 0.23747699119138962
REL_TOL = 1e-6


def _build_panel():
    panel = {}
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        panel[Path(name).stem] = df
    return panel


def _panel_frame(panel):
    """MultiIndex panel DataFrame for the direct estimate_capacity call."""
    return pd.concat(panel, axis=1)


def _factory(params):
    return build_strategy("cross_sectional_momentum", json.dumps(params))


def _run_walk_forward(regime_dict):
    buffer = io.StringIO()
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        with contextlib.redirect_stdout(buffer):
            return walk_forward_analysis(
                data=_build_panel(),
                strategy_factory=_factory,
                param_grid=PARAM_GRID,
                train_months=TRAIN_MONTHS,
                test_months=TEST_MONTHS,
                step_months=STEP_MONTHS,
                commission=COMMISSION,
                slippage=SLIPPAGE,
                impact_coefficient=IMPACT_COEFFICIENT,
                panel_pricing="net-exposure",
                apply_deflation=True,
                validate_pit=True,
                regime_impact_coefficients=regime_dict,
            )


def _basket_capacity(summary):
    capacity = summary.get("capacity")
    if isinstance(capacity, dict):
        capacity = capacity.get("cost_adjusted_capacity")
    return capacity


def test_regime_aware_capacity_reflects_stressed_regime_mix_real_triple_panel():
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists(), f"missing fixture {name}"

    panel = _build_panel()

    # The stressed labels must actually occur in the committed data, otherwise
    # the regime dict would be a silent no-op and the test would prove nothing.
    regimes = detect_combined_regime(panel["AAPL"]["close"])
    present = set(regimes.unique())
    missing = [label for label in STRESSED_REGIMES if label not in present]
    assert not missing, f"stressed regimes absent from committed data: {missing}"

    flat_summary = _run_walk_forward(None)["summary"]
    regime_summary = _run_walk_forward(REGIME_DICT)["summary"]

    flat_capacity = _basket_capacity(flat_summary)
    regime_capacity = _basket_capacity(regime_summary)

    print(
        "REGIME-AWARE CAPACITY: "
        f"flat=${flat_capacity:,.0f} regime=${regime_capacity:,.0f} "
        f"(regime/flat ratio={regime_capacity / flat_capacity:.4f})"
    )

    # 1. Default path is byte-identical: None leaves the published flat number
    #    unchanged (no regression in the common path).
    assert flat_capacity is not None, "flat basket capacity must be reported"
    assert abs(flat_capacity - EXPECTED_FLAT_CAPACITY) <= REL_TOL * abs(
        EXPECTED_FLAT_CAPACITY
    ), f"flat basket capacity drifted: {flat_capacity}"

    # 2. Regime-aware capacity is reported and strictly below flat: a stressed
    #    regime with a higher impact coefficient lowers the capacity.
    assert regime_capacity is not None, "regime basket capacity must be reported"
    assert regime_capacity < flat_capacity, (
        "regime-aware capacity must be below flat capacity when the stressed "
        f"regime coefficient is higher: regime={regime_capacity} vs "
        f"flat={flat_capacity}"
    )

    # 3. Pin the regime-aware number so a regression in the effective-
    #    coefficient aggregation is caught.
    assert abs(regime_capacity - EXPECTED_REGIME_CAPACITY) <= REL_TOL * abs(
        EXPECTED_REGIME_CAPACITY
    ), f"regime basket capacity drifted: {regime_capacity}"


def test_estimate_capacity_regime_effective_coefficient_default_invariant():
    panel = _build_panel()
    panel_df = _panel_frame(panel)

    # Default (None): effective coefficient == flat coefficient, no regime dict.
    flat = estimate_capacity(panel_df, IMPACT_COEFFICIENT)
    assert flat["effective_impact_coefficient"] == IMPACT_COEFFICIENT, (
        "default effective coefficient must equal the flat coefficient, got "
        f"{flat['effective_impact_coefficient']}"
    )
    assert flat["regime_impact_coefficients"] is None

    # Empty dict is also a no-op (byte-identical to None).
    empty = estimate_capacity(panel_df, IMPACT_COEFFICIENT, regime_impact_coefficients={})
    assert empty["cost_adjusted_capacity"] == flat["cost_adjusted_capacity"], (
        "empty regime dict must leave capacity byte-identical to the default"
    )
    assert empty["effective_impact_coefficient"] == IMPACT_COEFFICIENT

    # Stressed dict: effective coefficient is the ADV-weighted mean of the
    # per-period regime coefficients, strictly above the flat coefficient here,
    # and the capacity falls accordingly.
    regime = estimate_capacity(
        panel_df, IMPACT_COEFFICIENT, regime_impact_coefficients=REGIME_DICT
    )
    eff = regime["effective_impact_coefficient"]
    assert eff > IMPACT_COEFFICIENT, (
        f"stressed-regime effective coefficient must exceed flat, got {eff}"
    )
    assert abs(eff - EXPECTED_REGIME_EFFECTIVE_COEFF) <= REL_TOL * abs(
        EXPECTED_REGIME_EFFECTIVE_COEFF
    ), f"effective coefficient drifted: {eff}"
    assert regime["regime_impact_coefficients"] == REGIME_DICT
    assert regime["cost_adjusted_capacity"] < flat["cost_adjusted_capacity"], (
        "regime-aware capacity must be below flat capacity"
    )
    assert abs(regime["cost_adjusted_capacity"] - EXPECTED_REGIME_CAPACITY) <= REL_TOL * abs(
        EXPECTED_REGIME_CAPACITY
    ), f"regime cost_adjusted_capacity drifted: {regime['cost_adjusted_capacity']}"

    # Invalid coefficients are rejected (positive and finite required).
    for bad in ({"bear_high": 0.0}, {"bear_high": -0.1}, {"bear_high": float("nan")}):
        try:
            estimate_capacity(panel_df, IMPACT_COEFFICIENT, regime_impact_coefficients=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for regime dict {bad}")


if __name__ == "__main__":
    test_regime_aware_capacity_reflects_stressed_regime_mix_real_triple_panel()
    test_estimate_capacity_regime_effective_coefficient_default_invariant()
    print("OK")