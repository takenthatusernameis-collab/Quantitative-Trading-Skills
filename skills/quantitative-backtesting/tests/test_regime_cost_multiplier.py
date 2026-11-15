#!/usr/bin/env python3
"""
Unit tests for regime-conditional commission/slippage multipliers.

Transaction costs (commission + slippage) are empirically larger in
stressed/illiquid regimes: spreads widen and fills take longer when volatility
is high or the market is falling. The ``regime_cost_multipliers`` option lets a
caller scale the per-trade commission + slippage cost by a per-regime
multiplier, reusing the same causal regime labels already used for regime-aware
market impact. This file guards that machinery:

  (a) the default (``regime_cost_multipliers=None``) is a bit-identical no-op,
  (b) a multiplier changes only the trades in the matching regime,
  (c) the regime label applied to a trade is point-in-time (known only from
      bars up to and including the trade bar), and
  (d) a cost-sensitivity verdict can flip when the multiplier is large enough,
      on a committed synthetic fixture.

The regime labels are detected *inside* ``_calculate_strategy_returns`` from the
data's own close prices (the same causal detector used for regime-aware market
impact), so the tests map whatever labels the detector actually produces on the
fixture rather than assuming a particular label set.

Every test is deterministic on synthetic seed-fixed data and asserts a
directional, economically meaningful relationship. None of them is a claim
about any market -- they are regression guards on the cost machinery.

Run with: python3 skills/quantitative-backtesting/tests/test_regime_cost_multiplier.py
No third-party test framework is required; uses only the standard library, numpy and pandas.
"""

import sys
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import _calculate_strategy_returns  # noqa: E402
from regime_detection import detect_combined_regime  # noqa: E402
from utils import (  # noqa: E402
    book_cost_components,
    regime_cost_multiplier_series,
)


PERIODS = 252
SEED = 11


def _make_market(periods=PERIODS, seed=SEED):
    """Deterministic single-asset OHLCV frame with a drifted random walk and
    constant volume so ADV is stable and the impact model is estimable."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, periods)))
    volume = np.full(periods, 1_000_000)
    return pd.DataFrame({"close": close, "volume": volume}, index=dates)


def _flipping_signal(periods=PERIODS):
    """Long/short flip every bar: full turnover so every bar pays a trade cost."""
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    return pd.Series([1.0 if i % 2 == 0 else -1.0 for i in range(periods)], index=dates)


def _detected_labels(data):
    """The regime labels the causal detector produces on the fixture's close."""
    return detect_combined_regime(data["close"])


def _all_labels_multiplier(data, mult):
    """A regime mapping that loads every detected label at ``mult``."""
    labels = _detected_labels(data)
    return {lab: float(mult) for lab in labels.unique()}


def _total_return(data, signals, **kwargs):
    kwargs.setdefault("commission", 0.0)
    kwargs.setdefault("slippage", 0.0)
    returns = _calculate_strategy_returns(data, signals, **kwargs)
    return float((1 + returns).prod() - 1)


# ---------------------------------------------------------------------------
# The helper itself: alignment, default fallback, validation
# ---------------------------------------------------------------------------

def test_multiplier_series_is_none_when_disabled():
    """With no mapping, the helper returns None so callers skip the multiply
    entirely and the common path stays bit-identical."""
    dates = pd.date_range("2020-01-01", periods=5, freq="B")
    regimes = pd.Series(["a"] * 5, index=dates)
    assert regime_cost_multiplier_series(regimes, None) is None
    assert regime_cost_multiplier_series(regimes, {}) is None
    # No regimes to map either -> None (nothing to apply).
    assert regime_cost_multiplier_series(None, {"a": 2.0}) is None


def test_multiplier_series_maps_labels_and_defaults_unmapped():
    """Mapped labels get their multiplier; unmapped labels fall back to the
    default (1.0 -> no change)."""
    dates = pd.date_range("2020-01-01", periods=4, freq="B")
    regimes = pd.Series(["hot", "cold", "hot", "warm"], index=dates)
    mult = regime_cost_multiplier_series(regimes, {"hot": 2.0, "cold": 0.5})
    assert mult is not None
    assert list(np.round(mult.values, 6)) == [2.0, 0.5, 2.0, 1.0]


def test_multiplier_series_rejects_negative_or_nonfinite():
    """A negative or non-finite multiplier is a configuration error and must
    raise rather than silently producing a negative/invalid cost."""
    dates = pd.date_range("2020-01-01", periods=3, freq="B")
    regimes = pd.Series(["a", "a", "a"], index=dates)
    for bad in ({"a": -1.0}, {"a": float("nan")}, {"a": float("inf")}):
        try:
            regime_cost_multiplier_series(regimes, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {bad}")


# ---------------------------------------------------------------------------
# (a) Default is a bit-identical no-op
# ---------------------------------------------------------------------------

def test_default_none_matches_no_multiplier_exactly():
    """Passing regime_cost_multipliers=None must produce a bit-identical return
    series to not passing the argument at all."""
    data = _make_market()
    sig = _flipping_signal()
    base = _calculate_strategy_returns(
        data, sig, commission=0.0002, slippage=0.0001,
    )
    explicit_none = _calculate_strategy_returns(
        data, sig, commission=0.0002, slippage=0.0001,
        regime_cost_multipliers=None,
    )
    assert base.equals(explicit_none), (
        "regime_cost_multipliers=None must be a bit-identical no-op"
    )


def test_mapping_every_detected_label_to_one_is_noop():
    """Mapping every detected label to 1.0 must be a no-op even when the
    mapping is non-empty, because the multiplier only changes cost when != 1."""
    data = _make_market()
    sig = _flipping_signal()
    ones = _all_labels_multiplier(data, 1.0)
    with_ones = _total_return(
        data, sig, commission=0.001, slippage=0.0005,
        regime_cost_multipliers=ones,
    )
    baseline = _total_return(data, sig, commission=0.001, slippage=0.0005)
    assert abs(with_ones - baseline) < 1e-15, (
        "mapping every regime to 1.0 must be a no-op"
    )


# ---------------------------------------------------------------------------
# (b) A multiplier changes only the matching regime's trades
# ---------------------------------------------------------------------------

def test_multiplier_reduces_returns_when_all_regimes_loaded():
    """If every detected regime is charged above 1x, every trade costs more and
    net return must fall vs the no-multiplier baseline."""
    data = _make_market()
    sig = _flipping_signal()
    mapping = _all_labels_multiplier(data, 3.0)
    base = _total_return(data, sig, commission=0.001, slippage=0.0005)
    loaded = _total_return(
        data, sig, commission=0.001, slippage=0.0005,
        regime_cost_multipliers=mapping,
    )
    assert loaded < base, (
        f"a 3x multiplier on every bar must reduce net return: "
        f"{loaded:.6%} vs {base:.6%}"
    )


def test_multiplier_is_monotone_in_the_multiplier():
    """Across a sweep of a single regime's multiplier, net return must be
    non-increasing: higher loaded cost cannot help."""
    data = _make_market()
    sig = _flipping_signal()
    labels = list(_detected_labels(data).unique())
    rets = []
    for m in (1.0, 2.0, 5.0, 10.0):
        mapping = {lab: m for lab in labels}
        rets.append(_total_return(
            data, sig, commission=0.001, slippage=0.0005,
            regime_cost_multipliers=mapping,
        ))
    for prev, curr in zip(rets, rets[1:]):
        assert curr <= prev + 1e-15, (
            f"net return must be non-increasing in the multiplier: "
            f"{prev:.6%} -> {curr:.6%}"
        )


# ---------------------------------------------------------------------------
# (c) Point-in-time: the multiplier for a trade depends only on the regime
# label known at the trade bar, not on future bars.
# ---------------------------------------------------------------------------

def test_multiplier_is_point_in_time_under_future_mutation():
    """Mutating prices *after* a trade bar must not change the cost charged on
    that trade. Regimes are detected causally inside the backtest from the
    close series; the detector uses only bars up to and including the current
    bar, so per-period cost before the mutation must be unchanged."""
    data = _make_market()
    sig = _flipping_signal()
    mapping = _all_labels_multiplier(data, 2.0)
    kwargs = dict(commission=0.001, slippage=0.0005,
                  regime_cost_multipliers=mapping)

    full = _calculate_strategy_returns(data, sig, **kwargs)

    split = len(data) // 2
    mutated = data.copy()
    # Change every close after the split: a huge jump that would alter any
    # look-ahead regime detection or future-bar cost if the model peeked.
    mutated.iloc[split:, mutated.columns.get_loc("close")] *= 10.0
    pert = _calculate_strategy_returns(mutated, sig, **kwargs)

    base_free = _calculate_strategy_returns(data, sig, commission=0.0, slippage=0.0)
    pert_free = _calculate_strategy_returns(mutated, sig, commission=0.0, slippage=0.0)
    cost_full = base_free - full
    cost_pert = pert_free - pert
    pre = slice(0, split)
    assert np.allclose(cost_full.values[pre], cost_pert.values[pre], atol=1e-12), (
        "per-period cost before the mutation must be unchanged: the multiplier "
        "must not look at future bars"
    )


# ---------------------------------------------------------------------------
# Book-pricing path: the multiplier also scales gross-turnover cost
# ---------------------------------------------------------------------------

def test_book_pricing_multiplier_scales_gross_turnover_cost():
    """Under book pricing, a regime multiplier > 1 on every bar must scale the
    gross-turnover transaction cost, so net return falls vs the no-multiplier
    run on a rotating market-neutral book."""
    panel = {}
    dates = pd.date_range("2020-01-01", periods=PERIODS, freq="B")
    for k in range(3):
        rng = np.random.default_rng(SEED + 100 + k)
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, PERIODS)))
        panel[f"ASSET_{k}"] = pd.DataFrame(
            {"close": close, "volume": np.full(PERIODS, 1_000_000)}, index=dates
        )
    symbols = list(panel.keys())
    weights = pd.DataFrame(0.0, index=dates, columns=symbols)
    weights.loc[dates[::2], symbols[0]] = 0.5
    weights.loc[dates[::2], symbols[1]] = -0.5
    weights.loc[dates[1::2], symbols[0]] = -0.5
    weights.loc[dates[1::2], symbols[1]] = 0.5
    signals = pd.Series(1.0, index=dates)

    # The book path detects regimes from the first asset's close.
    labels = list(detect_combined_regime(panel[symbols[0]]["close"]).unique())
    mapping = {lab: 4.0 for lab in labels}

    def _run(**extra):
        r = _calculate_strategy_returns(
            panel, signals, panel_pricing="book", book_weights=weights,
            commission=0.001, slippage=0.0005, impact_coefficient=0.0,
            borrow_cost=0.0, funding_cost=0.0, **extra
        )
        return float((1 + r).prod() - 1)

    base = _run()
    loaded = _run(regime_cost_multipliers=mapping)
    assert loaded < base, (
        f"book-pricing multiplier must scale gross-turnover cost: "
        f"{loaded:.6%} vs {base:.6%}"
    )


def test_book_cost_components_applies_multiplier_to_transaction_leg():
    """book_cost_components must scale only the ``transaction`` component by the
    per-period multiplier, leaving borrow/funding untouched."""
    dates = pd.date_range("2020-01-01", periods=6, freq="B")
    held_book = pd.DataFrame(
        {"AAA": [0.5, 0.5, -0.5, -0.5, 0.5, 0.5],
         "BBB": [-0.5, -0.5, 0.5, 0.5, -0.5, -0.5]},
        index=dates,
    )
    regimes = pd.Series(["hot"] * 6, index=dates)
    base = book_cost_components(
        held_book, commission=0.001, slippage=0.0005, borrow_cost=0.03,
        funding_cost=0.02, ann_factor=252,
    )
    loaded = book_cost_components(
        held_book, commission=0.001, slippage=0.0005, borrow_cost=0.03,
        funding_cost=0.02, ann_factor=252,
        regime_cost_multipliers={"hot": 3.0}, regimes=regimes,
    )
    # Transaction cost triples on every non-NaN bar; borrow/funding are
    # exposure-based, not turnover-based, so they are unchanged.
    assert np.allclose(
        loaded["transaction"].values[1:], base["transaction"].values[1:] * 3.0,
        atol=1e-12,
    ), "regime multiplier must scale the transaction component exactly"
    assert np.allclose(loaded["borrow"].values, base["borrow"].values, atol=1e-15), (
        "regime multiplier must not affect the borrow component"
    )
    assert np.allclose(loaded["funding"].values, base["funding"].values, atol=1e-15), (
        "regime multiplier must not affect the funding component"
    )


# ---------------------------------------------------------------------------
# (d) A cost-sensitivity verdict can flip when the multiplier is large enough
# ---------------------------------------------------------------------------

def test_cost_sensitivity_verdict_flips_under_large_multiplier():
    """On a fixed synthetic fixture, a strategy that clears a 10% total-return
    hurdle at base cost fails it once a large stressed-regime multiplier is
    applied. This proves the multiplier is a first-class cost lever for
    sensitivity analysis, not a cosmetic no-op.

    This is a fixture-specific non-falsification of the *machinery* (the
    multiplier changes the verdict), not a claim that any market strategy is
    profitable.
    """
    data = _make_market(seed=3)
    dates = data.index
    sig = pd.Series([1.0 if (i // 10) % 2 == 0 else 0.0 for i in range(PERIODS)],
                    index=dates)
    mapping = _all_labels_multiplier(data, 50.0)
    base = _total_return(data, sig, commission=0.0002, slippage=0.0001)
    loaded = _total_return(
        data, sig, commission=0.0002, slippage=0.0001,
        regime_cost_multipliers=mapping,
    )
    hurdle = 0.10
    assert base > hurdle, (
        f"fixture must clear the hurdle at base cost for the flip to be "
        f"meaningful: {base:.4%} vs {hurdle:.4%}"
    )
    assert loaded < hurdle, (
        f"a 50x stressed-regime multiplier must break the hurdle: "
        f"{loaded:.4%} vs {hurdle:.4%}"
    )


TEST_REGISTRY = [
    ("test_multiplier_series_is_none_when_disabled",
     test_multiplier_series_is_none_when_disabled),
    ("test_multiplier_series_maps_labels_and_defaults_unmapped",
     test_multiplier_series_maps_labels_and_defaults_unmapped),
    ("test_multiplier_series_rejects_negative_or_nonfinite",
     test_multiplier_series_rejects_negative_or_nonfinite),
    ("test_default_none_matches_no_multiplier_exactly",
     test_default_none_matches_no_multiplier_exactly),
    ("test_mapping_every_detected_label_to_one_is_noop",
     test_mapping_every_detected_label_to_one_is_noop),
    ("test_multiplier_reduces_returns_when_all_regimes_loaded",
     test_multiplier_reduces_returns_when_all_regimes_loaded),
    ("test_multiplier_is_monotone_in_the_multiplier",
     test_multiplier_is_monotone_in_the_multiplier),
    ("test_multiplier_is_point_in_time_under_future_mutation",
     test_multiplier_is_point_in_time_under_future_mutation),
    ("test_book_pricing_multiplier_scales_gross_turnover_cost",
     test_book_pricing_multiplier_scales_gross_turnover_cost),
    ("test_book_cost_components_applies_multiplier_to_transaction_leg",
     test_book_cost_components_applies_multiplier_to_transaction_leg),
    ("test_cost_sensitivity_verdict_flips_under_large_multiplier",
     test_cost_sensitivity_verdict_flips_under_large_multiplier),
]


def main() -> int:
    failures = 0
    for name, fn in TEST_REGISTRY:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(TEST_REGISTRY) - failures}/{len(TEST_REGISTRY)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())