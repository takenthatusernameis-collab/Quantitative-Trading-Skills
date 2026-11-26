#!/usr/bin/env python3
"""Participation-rate cap propagated into the capacity *trend* distribution on
the committed three-asset panel (AAPL / MSFT / GOOGL).

``estimate_capacity`` reports two liquidity views:

- a point-in-time ``estimated_capacity`` (the ADV of the *last* bar only), and
- a ``capacity_trend`` distribution (min / median / max / last plus ratios)
  built from the per-period capacity series, which exists precisely so an
  intra-window liquidity squeeze that the single last-bar reading hides becomes
  visible.

The companion sweep test
(``test_walk_forward_capacity_participation_rate_sweep_real_triple_aapl_msft_googl.py``)
verifies the participation-rate cap on the *point-in-time* estimate only. It
never checks that the cap propagates into the *trend* distribution on real
data. That is the gap this test closes: the whole purpose of ``capacity_trend``
is intra-window realism, so the participation cap must be shown to bind (scale
the distribution down) at tight rates and to leave it unchanged (slack) at loose
rates, with the same binding/slack crossover as the point estimate.

Verified properties (real committed fixtures, offline):

- ``capacity_trend["last_capacity"] == estimated_capacity`` for the baseline and
  every swept rate (the distribution's end reading is the point estimate);
- ``n_periods`` is identical across the baseline and every rate (same window);
- ``min_capacity <= median_capacity <= max_capacity`` and the ratio fields are
  finite and positive;
- at a binding rate the whole distribution is scaled by
  ``rate / (max_impact / impact_coefficient)`` relative to the baseline (the
  impact-model-independent participation factor), and the scale-invariant
  ``min_to_median_ratio`` / ``last_to_median_ratio`` are unchanged;
- at a slack rate the trend is byte-identical to the baseline trend;
- ``median_capacity`` is non-decreasing as the cap loosens;
- a real binding/slack crossover exists across the swept levels.

No profitability or capacity claim is made; capacity is an execution-side
control. Offline, committed fixtures only
(assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv). No live network.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import _dict_to_multiindex, estimate_capacity  # noqa: E402

ASSETS_DIR = SKILLS_DIR / "assets" / "example_data" / "real_market_data"
SYMBOLS = ("AAPL", "MSFT", "GOOGL")

# Fixed impact coefficient / target impact / ADV window, matching the companion
# point-in-time sweep so the only varying input is the participation-rate cap.
IMPACT_COEFFICIENT = 0.5
MAX_IMPACT = 0.0005
ADV_WINDOW = 20

# Ascending participation-rate levels (fraction of ADV). The tight end binds the
# impact-based capacity at every period; the loose end is slack at every period.
PARTICIPATION_LEVELS = (0.0001, 0.0002, 0.0005, 0.001, 0.005, 0.01, 0.05)

# Impact-implied participation rate: the rate at which the participation limit
# equals the linear impact capacity (max_impact / impact_coefficient). A cap
# below this binds at every period; above it is slack at every period.
IMPACT_PARTICIPATION_RATE = MAX_IMPACT / IMPACT_COEFFICIENT

TREND_KEYS = ("min_capacity", "median_capacity", "max_capacity", "last_capacity")


def _build_real_triple_panel() -> pd.DataFrame:
    for name in SYMBOLS:
        assert (ASSETS_DIR / f"{name}.csv").exists(), f"missing fixture {name}.csv"
    data = {}
    for symbol in SYMBOLS:
        df = pd.read_csv(ASSETS_DIR / f"{symbol}.csv")
        df["date"] = pd.to_datetime(df["date"])
        data[symbol] = df.set_index("date").sort_index()
    return _dict_to_multiindex(data)


def _capacity(panel, rate):
    return estimate_capacity(
        panel,
        IMPACT_COEFFICIENT,
        max_impact=MAX_IMPACT,
        adv_window=ADV_WINDOW,
        max_participation_rate=rate,
    )


def _assert_trend_invariants(trend, expected_last, n_periods):
    assert isinstance(trend, dict), f"capacity_trend must be a dict, got {type(trend)}"
    assert trend["n_periods"] == n_periods, (
        f"n_periods {trend['n_periods']} != {n_periods} (window changed with the cap)"
    )
    # The distribution's end reading is the point-in-time estimate.
    assert abs(trend["last_capacity"] - expected_last) < 1e-6 * max(1.0, abs(expected_last)), (
        f"last_capacity {trend['last_capacity']} != estimated_capacity {expected_last}"
    )
    mn, med, mx = trend["min_capacity"], trend["median_capacity"], trend["max_capacity"]
    assert mn <= med <= mx, f"trend ordering broken: min {mn} <= median {med} <= max {mx}"
    assert mn > 0 and med > 0 and mx > 0, f"non-positive trend capacity: {trend}"
    for ratio_key in ("min_to_median_ratio", "last_to_median_ratio"):
        ratio = trend[ratio_key]
        assert ratio is not None and np.isfinite(ratio) and ratio > 0, (
            f"{ratio_key} must be finite and positive, got {ratio}"
        )


def test_participation_rate_cap_propagates_into_capacity_trend_real_triple_panel():
    panel = _build_real_triple_panel()

    baseline = estimate_capacity(
        panel, IMPACT_COEFFICIENT, max_impact=MAX_IMPACT, adv_window=ADV_WINDOW
    )
    assert baseline["estimable"] is True
    assert baseline["participation_capacity"] is None
    base_trend = baseline["capacity_trend"]
    n_periods = base_trend["n_periods"]
    _assert_trend_invariants(base_trend, baseline["estimated_capacity"], n_periods)

    rows = []
    for rate in PARTICIPATION_LEVELS:
        r = _capacity(panel, rate)
        assert r["estimable"] is True
        assert r["participation_capacity"] is not None
        trend = r["capacity_trend"]
        _assert_trend_invariants(trend, r["estimated_capacity"], n_periods)
        rows.append((rate, r, trend))

    # Median capacity is non-decreasing as the cap loosens (a looser cap can
    # only raise, never lower, the per-period capacity that feeds the trend).
    for (prev_rate, _, prev_trend), (curr_rate, _, curr_trend) in zip(rows, rows[1:]):
        assert curr_trend["median_capacity"] >= prev_trend["median_capacity"] - 1e-6, (
            "trend median decreased as the participation cap loosened: "
            f"{prev_rate} -> {prev_trend['median_capacity']:,.0f}, "
            f"{curr_rate} -> {curr_trend['median_capacity']:,.0f}"
        )

    # Binding rates scale the WHOLE distribution by rate / impact_participation_rate
    # relative to the baseline, and leave the scale-invariant ratios unchanged.
    binding = [(rate, trend) for rate, _, trend in rows if rate < IMPACT_PARTICIPATION_RATE]
    assert binding, "expected at least one binding rate below the impact participation rate"
    for rate, trend in binding:
        scale = rate / IMPACT_PARTICIPATION_RATE
        assert scale < 1.0
        for key in TREND_KEYS:
            expected = base_trend[key] * scale
            assert abs(trend[key] - expected) < 1e-6 * max(1.0, abs(expected)), (
                f"binding rate {rate}: trend {key} {trend[key]} != baseline*scale {expected}"
            )
        # Scale invariance of the ratio fields under a binding cap.
        assert abs(trend["min_to_median_ratio"] - base_trend["min_to_median_ratio"]) < 1e-9, (
            "min_to_median_ratio changed under a binding cap (should be scale-invariant)"
        )
        assert abs(trend["last_to_median_ratio"] - base_trend["last_to_median_ratio"]) < 1e-9, (
            "last_to_median_ratio changed under a binding cap (should be scale-invariant)"
        )

    # Slack rates leave the entire trend byte-identical to the baseline.
    slack = [(rate, trend) for rate, _, trend in rows if rate > IMPACT_PARTICIPATION_RATE]
    assert slack, "expected at least one slack rate above the impact participation rate"
    for rate, trend in slack:
        for key in TREND_KEYS:
            assert abs(trend[key] - base_trend[key]) < 1e-6 * max(1.0, abs(base_trend[key])), (
                f"slack rate {rate}: trend {key} {trend[key]} != baseline {base_trend[key]}"
            )

    # A real binding/slack crossover exists across the swept levels.
    scales = [trend["max_capacity"] / base_trend["max_capacity"] for _, _, trend in rows]
    assert any(s < 1.0 - 1e-9 for s in scales), "no binding rate scaled the trend down"
    assert any(abs(s - 1.0) < 1e-9 for s in scales), "no slack rate left the trend unchanged"


def test_participation_rate_cap_propagates_into_capacity_trend_sqrt_impact_model_real_triple_panel():
    """Square-root impact model companion to the linear trend test.

    Under the square-root model with these fixed parameters
    (coefficient=0.5, max_impact=0.0005),
    ``impact_capacity = n_assets * (max_impact / impact_coefficient)^2 *
    binding_adv_notional`` is far below the participation-rate limit at every
    swept level. Impact therefore binds at all rates under the square-root model
    (unlike linear, which shows a binding/slack crossover), so
    ``estimated_capacity == impact_capacity`` everywhere and the participation
    cap is slack at all levels. The key model-independent claims are:

    - ``participation_capacity`` is unchanged by the impact model (matches linear).
    - ``capacity_trend`` is byte-identical to the baseline sqrt trend at all
      rates (the cap never binds).
    - ``last_capacity == estimated_capacity`` at all rates.
    - ``median_capacity`` is non-decreasing (constant here) as the cap loosens.
    - No binding/slack crossover exists (all rates are slack).
    """
    panel = _build_real_triple_panel()

    baseline = estimate_capacity(
        panel,
        IMPACT_COEFFICIENT,
        impact_model="sqrt",
        max_impact=MAX_IMPACT,
        adv_window=ADV_WINDOW,
    )
    assert baseline["estimable"] is True
    assert baseline["impact_model"] == "sqrt"
    assert baseline["participation_capacity"] is None
    base_trend = baseline["capacity_trend"]
    n_periods = base_trend["n_periods"]
    _assert_trend_invariants(base_trend, baseline["estimated_capacity"], n_periods)

    # Expected impact capacity under sqrt (model-dependent, constant across rates).
    sqrt_impact_capacity = baseline["impact_capacity"]
    assert sqrt_impact_capacity is not None and sqrt_impact_capacity > 0

    rows = []
    for rate in PARTICIPATION_LEVELS:
        r = estimate_capacity(
            panel,
            IMPACT_COEFFICIENT,
            impact_model="sqrt",
            max_impact=MAX_IMPACT,
            adv_window=ADV_WINDOW,
            max_participation_rate=rate,
        )
        assert r["estimable"] is True
        assert r["impact_model"] == "sqrt"
        assert r["estimated_capacity"] is not None and r["estimated_capacity"] > 0
        assert r["impact_capacity"] is not None
        assert r["participation_capacity"] is not None
        trend = r["capacity_trend"]
        assert trend["n_periods"] == n_periods
        _assert_trend_invariants(trend, r["estimated_capacity"], n_periods)
        rows.append((rate, r, trend))

    # participation_capacity is impact-model independent (matches linear baseline).
    linear_baseline = estimate_capacity(
        panel, IMPACT_COEFFICIENT, max_impact=MAX_IMPACT, adv_window=ADV_WINDOW
    )
    # Get binding asset ADV notional from linear baseline (same panel, same last bar).
    binding_adv_notional = linear_baseline["adv_notional"]
    n_assets = linear_baseline["n_assets"]
    for rate, r, _ in rows:
        expected_part = n_assets * rate * binding_adv_notional
        assert abs(r["participation_capacity"] - expected_part) < 1e-6 * max(
            1.0, expected_part
        ), (
            f"sqrt participation_capacity {r['participation_capacity']} != "
            f"linear equivalent {expected_part} at rate {rate}"
        )

    # Impact capacity follows the square-root formula and is constant across rates.
    for rate, r, _ in rows:
        assert abs(r["impact_capacity"] - sqrt_impact_capacity) < 1e-6 * max(
            1.0, sqrt_impact_capacity
        ), f"sqrt impact_capacity changed across rates at {rate}"

    # Under sqrt with these params, impact binds at every level (impact_capacity
    # < participation_capacity), so estimated_capacity == impact_capacity and the
    # cap is slack everywhere. The trend is byte-identical to the baseline.
    for rate, r, trend in rows:
        assert r["impact_capacity"] < r["participation_capacity"], (
            f"expected impact to bind at rate {rate} under sqrt model"
        )
        assert r["estimated_capacity"] == r["impact_capacity"], (
            f"estimated_capacity should equal impact_capacity at rate {rate}"
        )
        for key in TREND_KEYS:
            assert abs(trend[key] - base_trend[key]) < 1e-6 * max(1.0, abs(base_trend[key])), (
                f"slack rate {rate}: trend {key} {trend[key]} != baseline {base_trend[key]}"
            )

    # Median capacity is non-decreasing (constant here) as the cap loosens.
    for (prev_rate, _, prev_trend), (curr_rate, _, curr_trend) in zip(rows, rows[1:]):
        assert curr_trend["median_capacity"] >= prev_trend["median_capacity"] - 1e-6, (
            "trend median decreased as the participation cap loosened under sqrt: "
            f"{prev_rate} -> {prev_trend['median_capacity']:,.0f}, "
            f"{curr_rate} -> {curr_trend['median_capacity']:,.0f}"
        )

    # No binding/slack crossover: all rates are slack (scale == 1.0).
    scales = [trend["max_capacity"] / base_trend["max_capacity"] for _, _, trend in rows]
    assert all(abs(s - 1.0) < 1e-9 for s in scales), (
        "expected all rates to be slack under sqrt model (scale == 1.0)"
    )
    assert not any(s < 1.0 - 1e-9 for s in scales), (
        "unexpected binding rate under sqrt model with these params"
    )


if __name__ == "__main__":
    test_participation_rate_cap_propagates_into_capacity_trend_real_triple_panel()
    test_participation_rate_cap_propagates_into_capacity_trend_sqrt_impact_model_real_triple_panel()
    print("OK")