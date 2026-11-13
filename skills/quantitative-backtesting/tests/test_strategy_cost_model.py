#!/usr/bin/env python3
"""
Unit tests for the strategy-side cost model in `walk_forward._calculate_strategy_returns`.

`_calculate_strategy_returns` prices commission, slippage, market impact,
borrow cost (short exposure) and funding cost (leverage beyond 1x) on top of
the raw signal returns, under both the "net-exposure" and "book" panel
pricing conventions.  These execution-cost assumptions underpin every
cost-sweep and sensitivity analysis in the worked examples
(`trading_costs_robustness_example.py`, `simple_momentum_hypothesis.py`), so a
silent regression here would corrupt every reported net-of-cost figure.

Every test below is deterministic on synthetic seed-fixed data and asserts a
directional, economically meaningful relationship (higher cost -> lower net
return; a cost that the strategy never incurs -> no effect).  None of them is
a claim about any market -- they are regression guards on the cost machinery.

Run with: python3 skills/quantitative-backtesting/tests/test_strategy_cost_model.py
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
from utils import (  # noqa: E402
    build_market_model,
    book_cost_components,
    book_market_impact_cost,
    book_return_from_held,
    held_book_weights,
    market_impact_cost,
)


PERIODS = 252
SEED = 7


def _make_market(periods=PERIODS, seed=SEED):
    """Deterministic single-asset OHLCV frame: a drifted random-walk close and
    constant volume so ADV is stable and the impact model is estimable."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, periods)))
    volume = np.full(periods, 1_000_000)
    return pd.DataFrame({"close": close, "volume": volume}, index=dates)


def _constant_signal(value):
    dates = pd.date_range("2020-01-01", periods=PERIODS, freq="B")
    return pd.Series(float(value), index=dates)


def _total_return(data, signals, **kwargs):
    """Net total return of the strategy at the given cost settings."""
    kwargs.setdefault("commission", 0.0)
    kwargs.setdefault("slippage", 0.0)
    returns = _calculate_strategy_returns(data, signals, **kwargs)
    return float((1 + returns).prod() - 1)


# ---------------------------------------------------------------------------
# Borrow cost: applies to short exposure only
# ---------------------------------------------------------------------------

def test_borrow_cost_reduces_short_returns():
    """A constant short position (signal = -1) must earn less net return when
    borrow_cost > 0; the per-period borrow drag is borrow_cost / ann_factor
    on the absolute short exposure."""
    data = _make_market()
    short = _constant_signal(-1.0)
    base = _total_return(data, short, borrow_cost=0.0)
    with_borrow = _total_return(data, short, borrow_cost=0.03)
    assert with_borrow < base, (
        f"borrow cost must reduce short returns: {with_borrow:.4%} vs {base:.4%}"
    )


def test_borrow_cost_no_effect_on_long_or_flat():
    """Borrow cost applies to short positions only: long (signal = +1) and
    flat (signal = 0) runs must be identical with or without borrow cost."""
    data = _make_market()
    for value in (1.0, 0.0):
        sig = _constant_signal(value)
        with_borrow = _total_return(data, sig, borrow_cost=0.03)
        without = _total_return(data, sig, borrow_cost=0.0)
        assert with_borrow == without, (
            f"borrow cost must not affect signal={value}: {with_borrow} vs {without}"
        )


# ---------------------------------------------------------------------------
# Funding cost: applies to gross leverage beyond 1x only
# ---------------------------------------------------------------------------

def test_funding_cost_reduces_leveraged_returns():
    """A 2x long position (signal = 2) has gross exposure 2, so funding_cost
    > 0 applies to the 1x excess leverage and reduces net return."""
    data = _make_market()
    levered = _constant_signal(2.0)
    base = _total_return(data, levered, funding_cost=0.0)
    with_funding = _total_return(data, levered, funding_cost=0.02)
    assert with_funding < base, (
        f"funding cost must reduce leveraged returns: {with_funding:.4%} vs {base:.4%}"
    )


def test_funding_cost_no_effect_at_or_below_1x():
    """Funding cost applies only to gross exposure beyond 1x: signal = +1
    (gross = 1) and signal = -1 (gross = 1) must be unchanged by funding cost."""
    data = _make_market()
    for value in (1.0, -1.0):
        sig = _constant_signal(value)
        with_funding = _total_return(data, sig, funding_cost=0.02)
        without = _total_return(data, sig, funding_cost=0.0)
        assert with_funding == without, (
            f"funding cost must not affect signal={value}: {with_funding} vs {without}"
        )


# ---------------------------------------------------------------------------
# Commission / slippage: scale with position changes (turnover)
# ---------------------------------------------------------------------------

def test_commission_and_slippage_reduce_returns_with_turnover():
    """With turnover (flipping signal every bar) commission + slippage are
    charged on every position change, so higher cost means lower net return."""
    dates = pd.date_range("2020-01-01", periods=PERIODS, freq="B")
    flipping = pd.Series([1.0 if i % 2 == 0 else -1.0 for i in range(PERIODS)], index=dates)
    data = _make_market()
    free = _total_return(data, flipping, commission=0.0, slippage=0.0)
    costed = _total_return(data, flipping, commission=0.001, slippage=0.0005)
    assert costed < free, (
        f"commission+slippage must reduce returns with turnover: {costed:.4%} vs {free:.4%}"
    )


def test_zero_turnover_pays_no_commission_after_entry():
    """A constant signal changes position only once (at entry), so commission
    and slippage must be identical at any rate for a long vs flat comparison
    once the single entry cost is removed -- i.e. a constant signal incurs no
    ongoing per-bar trading cost."""
    data = _make_market()
    long_sig = _constant_signal(1.0)
    no_cost = _total_return(data, long_sig, commission=0.0, slippage=0.0)
    high_cost = _total_return(data, long_sig, commission=0.01, slippage=0.01)
    # The only difference between the two is the single entry cost; with a
    # constant position there are no further position changes, so the delta
    # must be exactly the entry commission+slippage and not grow with bars.
    assert high_cost <= no_cost
    # No ongoing cost: the per-bar return series (net of the entry cost) is
    # the raw return series scaled by position, identical up to the entry bar.
    r_free = _calculate_strategy_returns(data, long_sig, commission=0.0, slippage=0.0)
    r_cost = _calculate_strategy_returns(data, long_sig, commission=0.01, slippage=0.01)
    # After the warmup/entry bar the two series must differ only by the one-off
    # entry cost, so their non-entry bars match.
    assert (r_free.iloc[3:] == r_cost.iloc[3:]).all(), (
        "constant position must not incur per-bar commission/slippage"
    )


# ---------------------------------------------------------------------------
# Market impact: live and monotone in the coefficient
# ---------------------------------------------------------------------------

def test_market_impact_is_live():
    """With turnover, impact_coefficient > 0 must strictly reduce net return
    vs impact disabled.  The original implementation scaled notional by raw
    price (~$100) instead of portfolio equity (~$100k), making impact a
    silent no-op; this guards that regression."""
    dates = pd.date_range("2020-01-01", periods=PERIODS, freq="B")
    flipping = pd.Series([1.0 if i % 2 == 0 else -1.0 for i in range(PERIODS)], index=dates)
    data = _make_market()
    off = _total_return(data, flipping, impact_coefficient=0.0)
    on = _total_return(data, flipping, impact_coefficient=5.0)
    assert on < off, (
        f"market impact must reduce returns: impact=5.0 -> {on:.4%} vs off -> {off:.4%}"
    )


def test_market_impact_monotone_in_coefficient():
    """Higher impact_coefficient must not increase net return (monotone
    degradation across the swept coefficients)."""
    dates = pd.date_range("2020-01-01", periods=PERIODS, freq="B")
    flipping = pd.Series([1.0 if i % 2 == 0 else -1.0 for i in range(PERIODS)], index=dates)
    data = _make_market()
    rets = [_total_return(data, flipping, impact_coefficient=c) for c in (0.0, 0.1, 1.0, 5.0)]
    for prev, curr in zip(rets, rets[1:]):
        assert curr <= prev, (
            f"market impact must be monotone-decreasing: {prev:.4%} -> {curr:.4%}"
        )


# ---------------------------------------------------------------------------
# Fill rate scales positions and costs elementwise (decided convention)
# ---------------------------------------------------------------------------

def test_fill_rate_scales_positions_and_costs_elementwise():
    """fill_rate = 0.5 halves the achieved position, so gross return halves and
    position-change-based costs (commission/slippage/impact) halve too."""
    dates = pd.date_range("2020-01-01", periods=PERIODS, freq="B")
    flipping = pd.Series([1.0 if i % 2 == 0 else -1.0 for i in range(PERIODS)], index=dates)
    data = _make_market()
    full = _calculate_strategy_returns(data, flipping, commission=0.001, slippage=0.001, fill_rate=1.0)
    half = _calculate_strategy_returns(data, flipping, commission=0.001, slippage=0.001, fill_rate=0.5)
    # Positions halved -> gross (pre-cost) return halved.
    assert np.allclose(half.values, full.values * 0.5, atol=1e-9), (
        "fill_rate=0.5 must halve the position series elementwise"
    )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_deterministic_given_identical_inputs():
    """Same data, signals and cost settings must produce identical returns."""
    data = _make_market()
    sig = _constant_signal(-1.0)
    a = _calculate_strategy_returns(data, sig, commission=0.0002, slippage=0.0001,
                                    borrow_cost=0.03, funding_cost=0.02, impact_coefficient=0.1)
    b = _calculate_strategy_returns(data, sig, commission=0.0002, slippage=0.0001,
                                    borrow_cost=0.03, funding_cost=0.02, impact_coefficient=0.1)
    assert a.equals(b), "cost model must be deterministic on identical inputs"


# ---------------------------------------------------------------------------
# Book pricing: panel_pricing="book" charges costs on the per-asset book
# (gross turnover, short legs, gross exposure beyond 1x, per-asset market
# impact) rather than on the scalar net exposure.  A market-neutral book that
# rotates in place has flat net exposure but real gross turnover and a real
# short leg; the net-exposure convention cannot see either, so this is a
# distinct cost basis that needs its own regression guards.
# ---------------------------------------------------------------------------

def _make_panel(periods=PERIODS, seed=SEED, n_assets=3):
    """Deterministic multi-asset panel: seed-fixed drifted random walks with
    constant volume, one OHLCV frame per symbol (dict-of-frames panel)."""
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    panel = {}
    for k in range(n_assets):
        rng = np.random.default_rng(seed + 100 + k)
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, periods)))
        panel[f"ASSET_{k}"] = pd.DataFrame(
            {"close": close, "volume": np.full(periods, 1_000_000)}, index=dates
        )
    return panel


def _constant_book(values):
    """Constant per-asset target book: {symbol: weight} -> DataFrame on the
    panel's date index."""
    panel = _make_panel()
    dates = panel[next(iter(panel))].index
    return pd.DataFrame({sym: float(w) for sym, w in values.items()}, index=dates)


def _rotating_book():
    """Market-neutral book that swaps its long and short legs every bar:
    gross turnover of 2.0 per bar with flat net exposure at all times."""
    panel = _make_panel()
    dates = panel[next(iter(panel))].index
    symbols = list(panel.keys())
    weights = pd.DataFrame(0.0, index=dates, columns=symbols)
    long_sym, short_sym = symbols[0], symbols[1]
    weights.loc[dates[::2], long_sym] = 0.5
    weights.loc[dates[::2], short_sym] = -0.5
    weights.loc[dates[1::2], long_sym] = -0.5
    weights.loc[dates[1::2], short_sym] = 0.5
    return weights


def _book_total_return(weights, signals=None, **kwargs):
    """Net total return under book pricing for a target book DataFrame."""
    kwargs.setdefault("commission", 0.0)
    kwargs.setdefault("slippage", 0.0)
    panel = _make_panel()
    dates = panel[next(iter(panel))].index
    if signals is None:
        signals = pd.Series(1.0, index=dates)
    returns = _calculate_strategy_returns(
        panel, signals, panel_pricing="book", book_weights=weights, **kwargs
    )
    return float((1 + returns).prod() - 1)


def test_book_pricing_matches_book_pnl_minus_independently_computed_costs():
    """Under book pricing, net return must equal the lagged held book's P&L
    (sum_i w_i r_i) minus the independently computed book cost components:
    gross-turnover transaction cost, short-leg borrow, funding on gross
    exposure beyond 1x, and per-asset market impact.  The components are
    computed straight from utils.py, so this guards the wiring between
    _calculate_strategy_returns and the book cost engine rather than
    re-asserting it tautologically."""
    weights = _constant_book({"ASSET_0": 0.8, "ASSET_1": -0.4, "ASSET_2": 0.2})
    panel = _make_panel()
    dates = panel[next(iter(panel))].index
    signals = pd.Series(1.0, index=dates)
    market = build_market_model(panel)

    model = _calculate_strategy_returns(
        panel, signals, panel_pricing="book", book_weights=weights,
        commission=0.0002, slippage=0.0001, borrow_cost=0.03, funding_cost=0.02,
        impact_coefficient=0.0,
    )

    held = held_book_weights(
        weights, market, lag=1, fill_rate=1.0, warmup="nan",
    )
    book_ret = book_return_from_held(held, market["close"])
    costs = book_cost_components(
        held, commission=0.0002, slippage=0.0001, borrow_cost=0.03,
        funding_cost=0.02, ann_factor=252,
    )["total"]
    market_impact = book_market_impact_cost(
        held_book=held, raw_returns=market["raw_returns"], close=market["close"],
        volume=market["volume"], impact_coefficient=0.0,
    )
    expected = book_ret - costs
    if market_impact is not None:
        expected = expected + market_impact
    expected = expected.reindex(model.index)
    assert np.allclose(model.values, expected.values, atol=1e-12), (
        "book-priced return must equal book P&L minus the book cost components"
    )


def test_book_pricing_charges_gross_turnover_on_rotation_in_place():
    """A market-neutral book that swaps long/short legs every bar has flat net
    exposure at all times but gross turnover of 2.0 per bar.  Book pricing
    charges commission+slippage on that turnover; the net-exposure convention
    cannot see it.  Higher per-turnover cost must lower net return by roughly
    the total turnover charged."""
    weights = _rotating_book()
    free = _book_total_return(
        weights, commission=0.0, slippage=0.0, borrow_cost=0.0,
        funding_cost=0.0, impact_coefficient=0.0,
    )
    costed = _book_total_return(
        weights, commission=0.0002, slippage=0.0, borrow_cost=0.0,
        funding_cost=0.0, impact_coefficient=0.0,
    )
    assert costed < free - 0.05, (
        f"book pricing must charge gross turnover: {costed:.4%} vs {free:.4%}"
    )


def test_book_borrow_cost_charges_short_legs():
    """Borrow cost applies to the book's short legs: a market-neutral book
    (short leg present) earns less with borrow_cost > 0, while a long-only
    book (no short leg) is unchanged."""
    neutral = _constant_book({"ASSET_0": 0.5, "ASSET_1": -0.5, "ASSET_2": 0.0})
    long_only = _constant_book({"ASSET_0": 0.5, "ASSET_1": 0.5, "ASSET_2": 0.0})
    base = _book_total_return(neutral, borrow_cost=0.0, impact_coefficient=0.0)
    with_borrow = _book_total_return(neutral, borrow_cost=0.05, impact_coefficient=0.0)
    assert with_borrow < base - 0.005, (
        f"borrow cost must reduce book returns with a short leg: "
        f"{with_borrow:.4%} vs {base:.4%}"
    )
    base_long = _book_total_return(long_only, borrow_cost=0.0, impact_coefficient=0.0)
    with_borrow_long = _book_total_return(long_only, borrow_cost=0.05, impact_coefficient=0.0)
    assert with_borrow_long == base_long, (
        "borrow cost must not affect a long-only book"
    )


def test_book_funding_cost_charges_gross_exposure_beyond_1x():
    """Funding cost applies to gross exposure beyond 1x: a 2x gross book pays
    funding on the excess leverage, while a book at exactly 1x gross pays
    nothing."""
    levered = _constant_book({"ASSET_0": 1.0, "ASSET_1": 1.0, "ASSET_2": 0.0})
    unit = _constant_book({"ASSET_0": 0.5, "ASSET_1": 0.5, "ASSET_2": 0.0})
    base = _book_total_return(levered, funding_cost=0.0, impact_coefficient=0.0)
    with_funding = _book_total_return(levered, funding_cost=0.04, impact_coefficient=0.0)
    assert with_funding < base - 0.002, (
        f"funding cost must reduce leveraged book returns: "
        f"{with_funding:.4%} vs {base:.4%}"
    )
    base_unit = _book_total_return(unit, funding_cost=0.0, impact_coefficient=0.0)
    with_unit = _book_total_return(unit, funding_cost=0.04, impact_coefficient=0.0)
    assert with_unit == base_unit, (
        "funding cost must not affect a book at or below 1x gross exposure"
    )


def test_book_market_impact_live_and_monotone():
    """Per-asset market impact on the book must be live (coefficient > 0
    strictly reduces net return vs disabled) and monotone-decreasing in the
    coefficient; every asset is measured against its own ADV."""
    weights = _rotating_book()
    rets = [
        _book_total_return(
            weights, impact_coefficient=c, commission=0.0, slippage=0.0,
            borrow_cost=0.0, funding_cost=0.0,
        )
        for c in (0.0, 0.5, 5.0)
    ]
    assert rets[1] < rets[0], (
        f"market impact must reduce book returns: {rets[1]:.4%} vs {rets[0]:.4%}"
    )
    assert rets[2] < rets[1], (
        f"book market impact must be monotone-decreasing: "
        f"{rets[1]:.4%} -> {rets[2]:.4%}"
    )


def test_book_pricing_deterministic_given_identical_inputs():
    """Book pricing must be deterministic on identical inputs."""
    weights = _constant_book({"ASSET_0": 0.8, "ASSET_1": -0.4, "ASSET_2": 0.2})
    panel = _make_panel()
    dates = panel[next(iter(panel))].index
    signals = pd.Series(1.0, index=dates)
    kwargs = dict(
        panel_pricing="book", book_weights=weights, commission=0.0002,
        slippage=0.0001, borrow_cost=0.03, funding_cost=0.02,
        impact_coefficient=0.1,
    )
    a = _calculate_strategy_returns(panel, signals, **kwargs)
    b = _calculate_strategy_returns(panel, signals, **kwargs)
    assert a.equals(b), "book pricing must be deterministic on identical inputs"


# ---------------------------------------------------------------------------
# Market-neutral pairs (net-exposure / dict panel) with market impact
# ---------------------------------------------------------------------------

def test_market_impact_reduces_returns_market_neutral_pairs_portfolio():
    """Market impact must reduce returns vs zero for a dict-panel portfolio.
    Regression guard for the position_notional scaling bug where impact was
    scaled by raw price (~$100) instead of portfolio equity (~$100k), making
    the impact a silent no-op at coefficient 5.0.

    The dict-panel path of `market_impact_cost` divides the portfolio notional
    across ``n_assets`` and measures each constituent against its own ADV, so
    this is the panel branch (``is_panel=True``), distinct from the single-asset
    guard `test_market_impact_is_live`.  A signal that flips long/short every
    bar has full turnover, so the per-asset impact machinery is actually
    exercised; a constant-zero position (the earlier version of this test,
    ``sig_a - sig_b`` with both equal to 1.0) trades nothing and can never
    show impact, which is why it failed.
    """
    panel = _make_panel(periods=PERIODS, seed=SEED, n_assets=2)
    dates = panel[next(iter(panel))].index
    # Flipping long/short every bar: full turnover on a 2-asset dict panel,
    # so the per-asset ADV impact path is exercised every bar.
    positions = pd.Series([1.0 if i % 2 == 0 else -1.0 for i in range(PERIODS)],
                          index=dates)
    data_mn = {sym: panel[sym] for sym in panel.keys()}

    off = _total_return(data_mn, positions, impact_coefficient=0.0)
    on = _total_return(data_mn, positions, impact_coefficient=5.0)
    assert on < off, (
        f"market impact (coeff=5.0) must reduce returns on the dict-panel "
        f"portfolio: impact=5.0 -> {on:.4%} vs off -> {off:.4%}"
    )


def test_dict_panel_constant_position_pays_no_per_bar_impact_after_entry():
    """A constant non-zero position on a dict panel trades only once (at
    entry), so per-bar market impact after the entry bar must be zero even at
    a large coefficient -- the per-asset ADV division must not manufacture
    spurious impact from a static position."""
    panel = _make_panel(periods=PERIODS, seed=SEED + 3, n_assets=2)
    dates = panel[next(iter(panel))].index
    positions = pd.Series(1.0, index=dates)
    data_mn = {sym: panel[sym] for sym in panel.keys()}

    rets = _calculate_strategy_returns(
        data_mn, positions, commission=0.0, slippage=0.0,
        impact_coefficient=5.0,
    )
    # No commission/slippage/borrow/funding and no turnover, so the net
    # return must equal the raw panel return (positions * raw_returns) on
    # every bar after the execution warmup -- impact must be a no-op.
    market = build_market_model(data_mn)
    expected = (positions * market["raw_returns"]).reindex(rets.index)
    assert np.allclose(rets.values, expected.values, atol=1e-12), (
        "constant dict-panel position must not incur per-bar market impact"
    )


# ---------------------------------------------------------------------------
# Square-root market-impact model: end-to-end selection + closed-form formula
# ---------------------------------------------------------------------------

def test_market_impact_sqrt_model_differs_from_linear_single_asset():
    """Square-root impact must be selectable and produce a different net
    return than linear impact for the same coefficient on a traded series.

    The square-root model (impact = coeff * sqrt(participation)) is more
    empirically supported for large orders than linear impact. This guards
    the core model selection so cost/impact sensitivity studies can choose
    the model explicitly instead of being limited to linear.
    """
    data = _make_market()
    # A toggling long/flat signal generates repeated position changes with
    # stable ADV, so participation is well-defined and the two models differ.
    sig = pd.Series([1.0 if i % 10 < 5 else 0.0 for i in range(PERIODS)], index=data.index)
    linear = _calculate_strategy_returns(
        data, sig, commission=0.0, slippage=0.0,
        impact_coefficient=0.8, impact_model="linear",
    )
    sqrt = _calculate_strategy_returns(
        data, sig, commission=0.0, slippage=0.0,
        impact_coefficient=0.8, impact_model="sqrt",
    )
    assert not np.allclose(linear.values, sqrt.values), (
        "sqrt impact model must produce different per-period returns than linear"
    )
    assert float((1 + sqrt).prod() - 1) != float((1 + linear).prod() - 1), (
        "sqrt and linear impact totals must differ for the same coefficient"
    )
    no_impact = _calculate_strategy_returns(
        data, sig, commission=0.0, slippage=0.0,
        impact_coefficient=0.0, impact_model="linear",
    )
    assert not np.allclose(linear.values, no_impact.values)
    assert not np.allclose(sqrt.values, no_impact.values)


def test_sqrt_market_impact_matches_closed_form():
    """The square-root impact cost returned by ``market_impact_cost`` must equal
    the closed-form ``coefficient * sqrt(position_notional / ADV_notional)``.

    ``test_market_impact_sqrt_model_differs_from_linear_single_asset`` only
    proves the sqrt branch is *reachable*; it would still pass if the sqrt
    formula were silently wrong (e.g. a missing coefficient, a linear term, or
    a mis-scaled participation). This test pins the formula itself on a
    constant-volume, zero-return frame where the closed form is exact, so a
    regression in the empirically-grounded square-root law is caught directly.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0], index=dates)
    volume = pd.Series(np.full(periods, 1_000_000.0), index=dates)
    # Zero market return -> equity is flat at initial_capital, so the closed
    # form is simply coeff * sqrt(|d| * initial_capital / (volume * close)).
    raw_returns = pd.Series(np.zeros(periods), index=dates)
    position_changes = pd.Series([0.0, 1.0, 0.0, 0.5, 0.0, 1.0], index=dates)

    coefficient = 0.5
    initial_capital = 100_000.0
    result = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=False, impact_coefficient=coefficient,
        adv_window=20, initial_capital=initial_capital, impact_model="sqrt",
    )
    assert result is not None, "sqrt impact must be live for coefficient > 0"

    equity = initial_capital * (1 + raw_returns).cumprod()
    adv_notional = volume.rolling(window=20, min_periods=1).mean() * close
    participation = (position_changes * equity) / adv_notional
    expected = coefficient * np.sqrt(participation)
    assert np.allclose(result.values, expected.values, atol=1e-12), (
        f"sqrt impact must equal coeff*sqrt(participation): "
        f"got {result.values}, expected {expected.values}"
    )


def test_single_asset_notional_weighted_sqrt_matches_closed_form():
    """The single-asset (``is_panel=False``) square-root impact under
    ``notional-weighted`` aggregation must equal the closed-form
    ``coefficient * sqrt(participation) * |d|``.

    ``test_sqrt_market_impact_matches_closed_form`` pins only the default
    "panel" aggregation for a single asset, where ``market_impact = rate``
    (the price concession rate itself). Under ``notional-weighted`` the cost
    is charged as a fraction of equity: the rate times the fraction of equity
    traded (|d|), i.e. ``rate * position_changes``. A regression that drops
    the ``|d|`` factor, or that applies the panel mean instead, would silently
    over/under-state single-asset cost. This pins the formula on the same
    constant-volume, zero-return frame where the closed form is exact.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0], index=dates)
    volume = pd.Series(np.full(periods, 1_000_000.0), index=dates)
    raw_returns = pd.Series(np.zeros(periods), index=dates)
    position_changes = pd.Series([0.0, 1.0, 0.0, 0.5, 0.0, 1.0], index=dates)

    coefficient = 0.5
    initial_capital = 100_000.0
    adv_window = 20

    result = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=False, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="sqrt", impact_aggregation="notional-weighted",
    )
    assert result is not None, "single-asset notional-weighted sqrt impact must be live for coefficient > 0"

    equity = initial_capital * (1 + raw_returns).cumprod()
    adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
    participation = (position_changes * equity) / adv_notional
    expected = coefficient * np.sqrt(participation) * position_changes
    assert np.allclose(result.values, expected.values, atol=1e-12), (
        f"single-asset notional-weighted sqrt impact must equal "
        f"coeff*sqrt(participation)*|d|: "
        f"got {result.values}, expected {expected.values}"
    )


def test_panel_sqrt_market_impact_matches_closed_form():
    """The panel (``is_panel=True``) square-root impact must equal the
    equal-weighted mean over constituents of
    ``coefficient * sqrt(per_asset_notional / ADV_notional)``, and the
    ``notional-weighted`` aggregation must equal ``|d| * mean(rate)``.

    ``test_sqrt_market_impact_matches_closed_form`` pins only the single-asset
    path. The panel path scales each constituent's notional by ``1 / n_assets``
    and divides by *that constituent's* ADV, so a regression there (measuring
    the whole basket against one ADV, or dropping the ``1 / n`` split) would
    slip past the single-asset test. This pins both panel aggregations on a
    constant-volume, zero-return frame where the closed form is exact, with
    asset-specific close/volume so the mean over assets differs from any single
    name.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    symbols = ["AAA", "BBB", "CCC"]
    # Constant-in-time but asset-specific close and volume so each name has a
    # different ADV notional and the mean over assets differs from any single
    # name (a guard against measuring the basket against one ADV).
    close = pd.DataFrame(
        {sym: np.full(periods, px)
         for sym, px in zip(symbols, [100.0, 200.0, 50.0])},
        index=dates,
    )
    volume = pd.DataFrame(
        {sym: np.full(periods, vol)
         for sym, vol in zip(symbols, [1_000_000.0, 2_000_000.0, 500_000.0])},
        index=dates,
    )
    # Zero market return -> equity is flat at initial_capital, so the closed
    # form is simply coeff * sqrt(|d| * equity / n_assets / (volume_i * close_i)).
    raw_returns = pd.Series(np.zeros(periods), index=dates)
    position_changes = pd.Series([0.0, 1.0, 0.0, 0.5, 0.0, 1.0], index=dates)

    coefficient = 0.5
    initial_capital = 100_000.0
    adv_window = 20

    result = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=True, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="sqrt",
    )
    assert result is not None, "sqrt panel impact must be live for coefficient > 0"

    n_assets = len(symbols)
    equity = initial_capital * (1 + raw_returns).cumprod()
    per_asset_notional = (position_changes * equity) / n_assets
    adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
    participation = per_asset_notional.values[:, None] / adv_notional.values
    rate = coefficient * np.sqrt(participation)
    expected = rate.mean(axis=1)

    assert np.allclose(result.values, expected, atol=1e-12), (
        f"panel sqrt impact must equal mean_i(coeff*sqrt(notional_i/ADV_i)): "
        f"got {result.values}, expected {expected}"
    )

    # Notional-weighted aggregation applies each name's rate to the notional
    # traded in that name and divides by equity; here every constituent trades
    # the same notional, so it reduces to |d| * mean(rate).
    result_nw = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=True, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="sqrt", impact_aggregation="notional-weighted",
    )
    assert result_nw is not None
    expected_nw = position_changes.values * expected
    assert np.allclose(result_nw.values, expected_nw, atol=1e-12), (
        f"notional-weighted panel impact must equal |d|*mean(rate): "
        f"got {result_nw.values}, expected {expected_nw}"
    )


def test_book_sqrt_market_impact_matches_closed_form():
    """The book-pricing square-root impact must equal the equal-weighted mean
    over assets of ``coefficient * sqrt(|dw_i| * equity / ADV_notional_i)``,
    and the ``notional-weighted`` aggregation must equal
    ``sum_i rate_i * |dw_i|``.

    ``book_market_impact_cost`` measures each name against its own ADV on the
    *weight change*; a regression (charging the book notional once, or using the
    weight instead of the weight change) would not be caught by the
    net-exposure sqrt test. This pins both aggregations on a constant-volume,
    zero-return frame where the closed form is exact.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    symbols = ["AAA", "BBB", "CCC"]
    close = pd.DataFrame(
        {sym: np.full(periods, px)
         for sym, px in zip(symbols, [100.0, 200.0, 50.0])},
        index=dates,
    )
    volume = pd.DataFrame(
        {sym: np.full(periods, vol)
         for sym, vol in zip(symbols, [1_000_000.0, 2_000_000.0, 500_000.0])},
        index=dates,
    )
    # A rotating long/short book: flat net exposure, weight changes of 1.0 in
    # AAA and BBB on the flip bars, no trade in CCC.
    held_book = pd.DataFrame(
        {
            "AAA": [0.5, 0.5, 0.5, -0.5, -0.5, 0.5],
            "BBB": [-0.5, -0.5, -0.5, 0.5, 0.5, -0.5],
            "CCC": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        },
        index=dates,
    )
    raw_returns = pd.Series(np.zeros(periods), index=dates)

    coefficient = 0.5
    initial_capital = 100_000.0
    adv_window = 20

    result = book_market_impact_cost(
        held_book=held_book, raw_returns=raw_returns, close=close,
        volume=volume, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="sqrt",
    )
    assert result is not None, "sqrt book impact must be live for coefficient > 0"

    equity = initial_capital * (1 + raw_returns).cumprod()
    traded_weight = held_book.diff().abs()
    adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
    # The first diff row is NaN -> treated as no trade (zero impact).
    traded_notional = traded_weight.mul(equity, axis=0).fillna(0.0)
    participation = traded_notional.values / adv_notional.values
    rate = coefficient * np.sqrt(participation)
    expected = rate.mean(axis=1)

    assert np.allclose(result.values, expected, atol=1e-12), (
        f"book sqrt impact must equal mean_i(coeff*sqrt(|dw_i|*equity/ADV_i)): "
        f"got {result.values}, expected {expected}"
    )

    result_nw = book_market_impact_cost(
        held_book=held_book, raw_returns=raw_returns, close=close,
        volume=volume, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="sqrt", impact_aggregation="notional-weighted",
    )
    assert result_nw is not None
    expected_nw = (rate * traded_weight.fillna(0.0).values).sum(axis=1)
    assert np.allclose(result_nw.values, expected_nw, atol=1e-12), (
        f"notional-weighted book impact must equal sum_i rate_i*|dw_i|: "
        f"got {result_nw.values}, expected {expected_nw}"
    )


def test_single_asset_regime_aware_sqrt_matches_closed_form():
    """The single-asset (``is_panel=False``) regime-aware square-root impact
    must equal ``sqrt(participation) * regime_coefficient`` per period, and an
    unknown regime label must fall back to the base ``impact_coefficient``.

    Regime-aware impact exists because impact is empirically larger in
    stressed/illiquid regimes. ``test_sqrt_market_impact_matches_closed_form``
    pins only the constant-coefficient path, so a regression that mis-aligns
    the regime series, applies the regime coefficient before the square root,
    or drops the fallback for unknown regimes would pass the existing tests
    while silently mispricing cost in exactly the regimes the model exists to
    capture. This pins the per-period coefficient application and the
    fallback on a constant-volume, zero-return frame where the closed form is
    exact.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0], index=dates)
    volume = pd.Series(np.full(periods, 1_000_000.0), index=dates)
    raw_returns = pd.Series(np.zeros(periods), index=dates)
    position_changes = pd.Series([0.0, 1.0, 0.0, 0.5, 0.0, 1.0], index=dates)
    regimes = pd.Series(["hi", "lo", "hi", "hi", "lo", "hi"], index=dates)
    regime_impact_coefficients = {"hi": 0.8, "lo": 0.2}

    coefficient = 0.5
    adv_window = 20
    initial_capital = 100_000.0

    result = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=False, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="sqrt", regimes=regimes,
        regime_impact_coefficients=regime_impact_coefficients,
    )
    assert result is not None, "regime-aware sqrt impact must be live for coefficient > 0"

    equity = initial_capital * (1 + raw_returns).cumprod()
    adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
    participation = (position_changes * equity) / adv_notional
    period_coeff = regimes.map(regime_impact_coefficients)
    expected = np.sqrt(participation) * period_coeff
    assert np.allclose(result.values, expected.values, atol=1e-12), (
        f"regime-aware sqrt impact must equal sqrt(participation)*regime_coeff: "
        f"got {result.values}, expected {expected.values}"
    )

    # An unknown regime label falls back to the base coefficient, not NaN/0.
    unknown_regimes = pd.Series(["not_a_regime"] * periods, index=dates)
    fallback = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=False, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="sqrt", regimes=unknown_regimes,
        regime_impact_coefficients=regime_impact_coefficients,
    )
    expected_fallback = np.sqrt(participation) * coefficient
    assert np.allclose(fallback.values, expected_fallback.values, atol=1e-12), (
        f"unknown regime must fall back to the base coefficient: "
        f"got {fallback.values}, expected {expected_fallback.values}"
    )


def test_panel_regime_aware_sqrt_matches_closed_form():
    """The panel (``is_panel=True``) regime-aware square-root impact must equal
    the equal-weighted mean over constituents of
    ``sqrt(per_asset_notional / ADV_notional_i) * regime_coeff_t``.

    The panel path divides each constituent's notional by its own ADV and
    applies one regime coefficient per period (broadcast across names). A
    regression that broadcasts the coefficient along the wrong axis, or that
    applies it to the mean instead of each asset, would only be visible when
    assets have different ADV and the coefficient varies by period. This pins
    the formula on a constant-volume, zero-return frame where the closed form
    is exact.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    symbols = ["AAA", "BBB", "CCC"]
    close = pd.DataFrame(
        {sym: np.full(periods, px)
         for sym, px in zip(symbols, [100.0, 200.0, 50.0])},
        index=dates,
    )
    volume = pd.DataFrame(
        {sym: np.full(periods, vol)
         for sym, vol in zip(symbols, [1_000_000.0, 2_000_000.0, 500_000.0])},
        index=dates,
    )
    raw_returns = pd.Series(np.zeros(periods), index=dates)
    position_changes = pd.Series([0.0, 1.0, 0.0, 0.5, 0.0, 1.0], index=dates)
    regimes = pd.Series(["hi", "lo", "hi", "lo", "hi", "lo"], index=dates)
    regime_impact_coefficients = {"hi": 0.8, "lo": 0.2}

    coefficient = 0.5
    adv_window = 20
    initial_capital = 100_000.0

    result = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=True, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="sqrt", regimes=regimes,
        regime_impact_coefficients=regime_impact_coefficients,
    )
    assert result is not None

    n_assets = len(symbols)
    equity = initial_capital * (1 + raw_returns).cumprod()
    per_asset_notional = (position_changes * equity) / n_assets
    adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
    participation = per_asset_notional.values[:, None] / adv_notional.values
    period_coeff = regimes.map(regime_impact_coefficients).values[:, None]
    rate = np.sqrt(participation) * period_coeff
    expected = rate.mean(axis=1)

    assert np.allclose(result.values, expected, atol=1e-12), (
        f"regime-aware panel sqrt impact must equal "
        f"mean_i(sqrt(notional_i/ADV_i)*regime_coeff_t): "
        f"got {result.values}, expected {expected}"
    )


def test_book_regime_aware_sqrt_matches_closed_form():
    """The book-pricing regime-aware square-root impact must equal the
    equal-weighted mean over assets of
    ``sqrt(|dw_i| * equity / ADV_notional_i) * regime_coeff_t``.

    The book path measures each name against its own ADV on the weight change
    and applies one regime coefficient per period. A regression that applies
    the coefficient to the mean rather than each asset, or mis-aligns the
    regime series against the book index, would not be caught by the
    constant-coefficient book test. This pins the formula on a constant-volume,
    zero-return frame where the closed form is exact.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    symbols = ["AAA", "BBB", "CCC"]
    close = pd.DataFrame(
        {sym: np.full(periods, px)
         for sym, px in zip(symbols, [100.0, 200.0, 50.0])},
        index=dates,
    )
    volume = pd.DataFrame(
        {sym: np.full(periods, vol)
         for sym, vol in zip(symbols, [1_000_000.0, 2_000_000.0, 500_000.0])},
        index=dates,
    )
    held_book = pd.DataFrame(
        {
            "AAA": [0.5, 0.5, 0.5, -0.5, -0.5, 0.5],
            "BBB": [-0.5, -0.5, -0.5, 0.5, 0.5, -0.5],
            "CCC": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        },
        index=dates,
    )
    raw_returns = pd.Series(np.zeros(periods), index=dates)
    regimes = pd.Series(["hi", "lo", "hi", "lo", "hi", "lo"], index=dates)
    regime_impact_coefficients = {"hi": 0.8, "lo": 0.2}

    coefficient = 0.5
    adv_window = 20
    initial_capital = 100_000.0

    result = book_market_impact_cost(
        held_book=held_book, raw_returns=raw_returns, close=close,
        volume=volume, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="sqrt", regimes=regimes,
        regime_impact_coefficients=regime_impact_coefficients,
    )
    assert result is not None, "regime-aware sqrt book impact must be live for coefficient > 0"

    equity = initial_capital * (1 + raw_returns).cumprod()
    traded_weight = held_book.diff().abs()
    adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
    traded_notional = traded_weight.mul(equity, axis=0).fillna(0.0)
    participation = traded_notional.values / adv_notional.values
    period_coeff = regimes.map(regime_impact_coefficients).values[:, None]
    rate = np.sqrt(participation) * period_coeff
    expected = rate.mean(axis=1)

    assert np.allclose(result.values, expected, atol=1e-12), (
        f"regime-aware book sqrt impact must equal "
        f"mean_i(sqrt(|dw_i|*equity/ADV_i)*regime_coeff_t): "
        f"got {result.values}, expected {expected}"
    )


# ---------------------------------------------------------------------------
# Regime-aware LINEAR market-impact model: closed-form formula pin
# ---------------------------------------------------------------------------

def test_single_asset_regime_aware_linear_matches_closed_form():
    """The single-asset (``is_panel=False``) regime-aware linear impact
    must equal ``participation * regime_coefficient`` per period, and an
    unknown regime label must fall back to the base ``impact_coefficient``.

    Mirrors ``test_single_asset_regime_aware_sqrt_matches_closed_form`` but
    for the linear branch. A regression that mis-aligns the regime series,
    applies the regime coefficient incorrectly, or drops the fallback for
    unknown regimes would silently misprice cost in exactly the regimes the
    model exists to capture.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0], index=dates)
    volume = pd.Series(np.full(periods, 1_000_000.0), index=dates)
    raw_returns = pd.Series(np.zeros(periods), index=dates)
    position_changes = pd.Series([0.0, 1.0, 0.0, 0.5, 0.0, 1.0], index=dates)
    regimes = pd.Series(["hi", "lo", "hi", "hi", "lo", "hi"], index=dates)
    regime_impact_coefficients = {"hi": 0.8, "lo": 0.2}

    coefficient = 0.5
    adv_window = 20
    initial_capital = 100_000.0

    result = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=False, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="linear", regimes=regimes,
        regime_impact_coefficients=regime_impact_coefficients,
    )
    assert result is not None, "regime-aware linear impact must be live for coefficient > 0"

    equity = initial_capital * (1 + raw_returns).cumprod()
    adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
    participation = (position_changes * equity) / adv_notional
    period_coeff = regimes.map(regime_impact_coefficients)
    expected = participation * period_coeff
    assert np.allclose(result.values, expected.values, atol=1e-12), (
        f"regime-aware linear impact must equal participation*regime_coeff: "
        f"got {result.values}, expected {expected.values}"
    )

    # An unknown regime label falls back to the base coefficient, not NaN/0.
    unknown_regimes = pd.Series(["not_a_regime"] * periods, index=dates)
    fallback = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=False, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="linear", regimes=unknown_regimes,
        regime_impact_coefficients=regime_impact_coefficients,
    )
    expected_fallback = participation * coefficient
    assert np.allclose(fallback.values, expected_fallback.values, atol=1e-12), (
        f"unknown regime must fall back to the base coefficient: "
        f"got {fallback.values}, expected {expected_fallback.values}"
    )


def test_panel_regime_aware_linear_matches_closed_form():
    """The panel (``is_panel=True``) regime-aware linear impact must equal
    the equal-weighted mean over constituents of
    ``(per_asset_notional / ADV_notional_i) * regime_coeff_t``.

    The panel path divides each constituent's notional by its own ADV and
    applies one regime coefficient per period (broadcast across names).
    A regression that broadcasts the coefficient along the wrong axis, or that
    applies it to the mean instead of each asset, would only be visible when
    assets have different ADV and the coefficient varies by period.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    symbols = ["AAA", "BBB", "CCC"]
    close = pd.DataFrame(
        {sym: np.full(periods, px)
         for sym, px in zip(symbols, [100.0, 200.0, 50.0])},
        index=dates,
    )
    volume = pd.DataFrame(
        {sym: np.full(periods, vol)
         for sym, vol in zip(symbols, [1_000_000.0, 2_000_000.0, 500_000.0])},
        index=dates,
    )
    raw_returns = pd.Series(np.zeros(periods), index=dates)
    position_changes = pd.Series([0.0, 1.0, 0.0, 0.5, 0.0, 1.0], index=dates)
    regimes = pd.Series(["hi", "lo", "hi", "lo", "hi", "lo"], index=dates)
    regime_impact_coefficients = {"hi": 0.8, "lo": 0.2}

    coefficient = 0.5
    adv_window = 20
    initial_capital = 100_000.0

    result = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=True, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="linear", regimes=regimes,
        regime_impact_coefficients=regime_impact_coefficients,
    )
    assert result is not None

    n_assets = len(symbols)
    equity = initial_capital * (1 + raw_returns).cumprod()
    per_asset_notional = (position_changes * equity) / n_assets
    adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
    participation = per_asset_notional.values[:, None] / adv_notional.values
    period_coeff = regimes.map(regime_impact_coefficients).values[:, None]
    rate = participation * period_coeff
    expected = rate.mean(axis=1)

    assert np.allclose(result.values, expected, atol=1e-12), (
        f"regime-aware panel linear impact must equal "
        f"mean_i(notional_i/ADV_i*regime_coeff_t): "
        f"got {result.values}, expected {expected}"
    )


def test_book_regime_aware_linear_matches_closed_form():
    """The book-pricing regime-aware linear impact must equal the
    equal-weighted mean over assets of
    ``(|dw_i| * equity / ADV_notional_i) * regime_coeff_t``.

    The book path measures each name against its own ADV on the weight change
    and applies one regime coefficient per period. A regression that applies
    the coefficient to the mean rather than each asset, or mis-aligns the
    regime series against the book index, would not be caught by the
    constant-coefficient book test.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    symbols = ["AAA", "BBB", "CCC"]
    close = pd.DataFrame(
        {sym: np.full(periods, px)
         for sym, px in zip(symbols, [100.0, 200.0, 50.0])},
        index=dates,
    )
    volume = pd.DataFrame(
        {sym: np.full(periods, vol)
         for sym, vol in zip(symbols, [1_000_000.0, 2_000_000.0, 500_000.0])},
        index=dates,
    )
    held_book = pd.DataFrame(
        {
            "AAA": [0.5, 0.5, 0.5, -0.5, -0.5, 0.5],
            "BBB": [-0.5, -0.5, -0.5, 0.5, 0.5, -0.5],
            "CCC": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        },
        index=dates,
    )
    raw_returns = pd.Series(np.zeros(periods), index=dates)
    regimes = pd.Series(["hi", "lo", "hi", "lo", "hi", "lo"], index=dates)
    regime_impact_coefficients = {"hi": 0.8, "lo": 0.2}

    coefficient = 0.5
    adv_window = 20
    initial_capital = 100_000.0

    result = book_market_impact_cost(
        held_book=held_book, raw_returns=raw_returns, close=close,
        volume=volume, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="linear", regimes=regimes,
        regime_impact_coefficients=regime_impact_coefficients,
    )
    assert result is not None, "regime-aware linear book impact must be live for coefficient > 0"

    equity = initial_capital * (1 + raw_returns).cumprod()
    traded_weight = held_book.diff().abs()
    adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
    traded_notional = traded_weight.mul(equity, axis=0).fillna(0.0)
    participation = traded_notional.values / adv_notional.values
    period_coeff = regimes.map(regime_impact_coefficients).values[:, None]
    rate = participation * period_coeff
    expected = rate.mean(axis=1)

    assert np.allclose(result.values, expected, atol=1e-12), (
        f"regime-aware book linear impact must equal "
        f"mean_i(|dw_i|*equity/ADV_i*regime_coeff_t): "
        f"got {result.values}, expected {expected}"
    )


# ---------------------------------------------------------------------------
# Regime-aware NOTIONAL-WEIGHTED market-impact model: closed-form formula pin
# ---------------------------------------------------------------------------

def test_single_asset_regime_aware_sqrt_notional_weighted_matches_closed_form():
    """The single-asset (``is_panel=False``) regime-aware square-root impact under
    ``notional-weighted`` aggregation must equal the closed-form
    ``coefficient * sqrt(participation) * |d|`` with regime coefficient per period.

    Mirrors ``test_single_asset_notional_weighted_sqrt_matches_closed_form`` but
    for the regime-aware sqrt branch. A regression that drops the ``|d|`` factor,
    mis-aligns the regime series, or drops the fallback for unknown regimes
    would silently misprice cost in exactly the regimes the model exists to
    capture.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0], index=dates)
    volume = pd.Series(np.full(periods, 1_000_000.0), index=dates)
    raw_returns = pd.Series(np.zeros(periods), index=dates)
    position_changes = pd.Series([0.0, 1.0, 0.0, 0.5, 0.0, 1.0], index=dates)
    regimes = pd.Series(["hi", "lo", "hi", "hi", "lo", "hi"], index=dates)
    regime_impact_coefficients = {"hi": 0.8, "lo": 0.2}

    coefficient = 0.5
    adv_window = 20
    initial_capital = 100_000.0

    result = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=False, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="sqrt", impact_aggregation="notional-weighted",
        regimes=regimes, regime_impact_coefficients=regime_impact_coefficients,
    )
    assert result is not None, "regime-aware notional-weighted sqrt impact must be live for coefficient > 0"

    equity = initial_capital * (1 + raw_returns).cumprod()
    adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
    participation = (position_changes * equity) / adv_notional
    period_coeff = regimes.map(regime_impact_coefficients)
    expected = np.sqrt(participation) * period_coeff * position_changes
    assert np.allclose(result.values, expected.values, atol=1e-12), (
        f"regime-aware notional-weighted sqrt impact must equal "
        f"sqrt(participation)*regime_coeff*|d|: "
        f"got {result.values}, expected {expected.values}"
    )

    # An unknown regime label falls back to the base coefficient, not NaN/0.
    unknown_regimes = pd.Series(["not_a_regime"] * periods, index=dates)
    fallback = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=False, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="sqrt", impact_aggregation="notional-weighted",
        regimes=unknown_regimes,
        regime_impact_coefficients=regime_impact_coefficients,
    )
    expected_fallback = np.sqrt(participation) * coefficient * position_changes
    assert np.allclose(fallback.values, expected_fallback.values, atol=1e-12), (
        f"unknown regime must fall back to the base coefficient: "
        f"got {fallback.values}, expected {expected_fallback.values}"
    )


def test_single_asset_regime_aware_linear_notional_weighted_matches_closed_form():
    """The single-asset (``is_panel=False``) regime-aware linear impact under
    ``notional-weighted`` aggregation must equal the closed-form
    ``coefficient * participation * |d|`` with regime coefficient per period.

    Mirrors ``test_single_asset_regime_aware_linear_matches_closed_form`` but
    for the notional-weighted linear branch. A regression that drops the ``|d|``
    factor, mis-aligns the regime series, or drops the fallback for unknown
    regimes would silently misprice cost in exactly the regimes the model exists
    to capture.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0], index=dates)
    volume = pd.Series(np.full(periods, 1_000_000.0), index=dates)
    raw_returns = pd.Series(np.zeros(periods), index=dates)
    position_changes = pd.Series([0.0, 1.0, 0.0, 0.5, 0.0, 1.0], index=dates)
    regimes = pd.Series(["hi", "lo", "hi", "hi", "lo", "hi"], index=dates)
    regime_impact_coefficients = {"hi": 0.8, "lo": 0.2}

    coefficient = 0.5
    adv_window = 20
    initial_capital = 100_000.0

    result = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=False, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="linear", impact_aggregation="notional-weighted",
        regimes=regimes, regime_impact_coefficients=regime_impact_coefficients,
    )
    assert result is not None, "regime-aware notional-weighted linear impact must be live for coefficient > 0"

    equity = initial_capital * (1 + raw_returns).cumprod()
    adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
    participation = (position_changes * equity) / adv_notional
    period_coeff = regimes.map(regime_impact_coefficients)
    expected = participation * period_coeff * position_changes
    assert np.allclose(result.values, expected.values, atol=1e-12), (
        f"regime-aware notional-weighted linear impact must equal "
        f"participation*regime_coeff*|d|: "
        f"got {result.values}, expected {expected.values}"
    )

    # An unknown regime label falls back to the base coefficient, not NaN/0.
    unknown_regimes = pd.Series(["not_a_regime"] * periods, index=dates)
    fallback = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=False, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="linear", impact_aggregation="notional-weighted",
        regimes=unknown_regimes,
        regime_impact_coefficients=regime_impact_coefficients,
    )
    expected_fallback = participation * coefficient * position_changes
    assert np.allclose(fallback.values, expected_fallback.values, atol=1e-12), (
        f"unknown regime must fall back to the base coefficient: "
        f"got {fallback.values}, expected {expected_fallback.values}"
    )


def test_panel_regime_aware_sqrt_notional_weighted_matches_closed_form():
    """The panel (``is_panel=True``) regime-aware square-root impact under
    ``notional-weighted`` aggregation must equal ``|d| * mean(rate_i)`` where
    ``rate_i = sqrt(per_asset_notional / ADV_notional_i) * regime_coeff_t``.

    The panel path divides each constituent's notional by its own ADV and
    applies one regime coefficient per period (broadcast across names). A
    regression that broadcasts the coefficient along the wrong axis, or that
    applies it to the mean instead of each asset, would only be visible when
    assets have different ADV and the coefficient varies by period. This pins
    the formula on a constant-volume, zero-return frame where the closed form
    is exact.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    symbols = ["AAA", "BBB", "CCC"]
    close = pd.DataFrame(
        {sym: np.full(periods, px)
         for sym, px in zip(symbols, [100.0, 200.0, 50.0])},
        index=dates,
    )
    volume = pd.DataFrame(
        {sym: np.full(periods, vol)
         for sym, vol in zip(symbols, [1_000_000.0, 2_000_000.0, 500_000.0])},
        index=dates,
    )
    raw_returns = pd.Series(np.zeros(periods), index=dates)
    position_changes = pd.Series([0.0, 1.0, 0.0, 0.5, 0.0, 1.0], index=dates)
    regimes = pd.Series(["hi", "lo", "hi", "lo", "hi", "lo"], index=dates)
    regime_impact_coefficients = {"hi": 0.8, "lo": 0.2}

    coefficient = 0.5
    adv_window = 20
    initial_capital = 100_000.0

    result = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=True, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="sqrt", impact_aggregation="notional-weighted",
        regimes=regimes, regime_impact_coefficients=regime_impact_coefficients,
    )
    assert result is not None

    n_assets = len(symbols)
    equity = initial_capital * (1 + raw_returns).cumprod()
    per_asset_notional = (position_changes * equity) / n_assets
    adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
    participation = per_asset_notional.values[:, None] / adv_notional.values
    period_coeff = regimes.map(regime_impact_coefficients).values[:, None]
    rate = np.sqrt(participation) * period_coeff
    expected = position_changes.values * rate.mean(axis=1)

    assert np.allclose(result.values, expected, atol=1e-12), (
        f"regime-aware notional-weighted panel sqrt impact must equal "
        f"|d|*mean_i(sqrt(notional_i/ADV_i)*regime_coeff_t): "
        f"got {result.values}, expected {expected}"
    )


def test_panel_regime_aware_linear_notional_weighted_matches_closed_form():
    """The panel (``is_panel=True``) regime-aware linear impact under
    ``notional-weighted`` aggregation must equal ``|d| * mean(rate_i)`` where
    ``rate_i = (per_asset_notional / ADV_notional_i) * regime_coeff_t``.

    The panel path divides each constituent's notional by its own ADV and
    applies one regime coefficient per period (broadcast across names).
    A regression that broadcasts the coefficient along the wrong axis, or that
    applies it to the mean instead of each asset, would only be visible when
    assets have different ADV and the coefficient varies by period.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    symbols = ["AAA", "BBB", "CCC"]
    close = pd.DataFrame(
        {sym: np.full(periods, px)
         for sym, px in zip(symbols, [100.0, 200.0, 50.0])},
        index=dates,
    )
    volume = pd.DataFrame(
        {sym: np.full(periods, vol)
         for sym, vol in zip(symbols, [1_000_000.0, 2_000_000.0, 500_000.0])},
        index=dates,
    )
    raw_returns = pd.Series(np.zeros(periods), index=dates)
    position_changes = pd.Series([0.0, 1.0, 0.0, 0.5, 0.0, 1.0], index=dates)
    regimes = pd.Series(["hi", "lo", "hi", "lo", "hi", "lo"], index=dates)
    regime_impact_coefficients = {"hi": 0.8, "lo": 0.2}

    coefficient = 0.5
    adv_window = 20
    initial_capital = 100_000.0

    result = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=True, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="linear", impact_aggregation="notional-weighted",
        regimes=regimes, regime_impact_coefficients=regime_impact_coefficients,
    )
    assert result is not None

    n_assets = len(symbols)
    equity = initial_capital * (1 + raw_returns).cumprod()
    per_asset_notional = (position_changes * equity) / n_assets
    adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
    participation = per_asset_notional.values[:, None] / adv_notional.values
    period_coeff = regimes.map(regime_impact_coefficients).values[:, None]
    rate = participation * period_coeff
    expected = position_changes.values * rate.mean(axis=1)

    assert np.allclose(result.values, expected, atol=1e-12), (
        f"regime-aware notional-weighted panel linear impact must equal "
        f"|d|*mean_i(notional_i/ADV_i*regime_coeff_t): "
        f"got {result.values}, expected {expected}"
    )


def test_book_regime_aware_sqrt_notional_weighted_matches_closed_form():
    """The book-pricing regime-aware square-root impact under
    ``notional-weighted`` aggregation must equal ``sum_i rate_i * |dw_i|`` where
    ``rate_i = sqrt(|dw_i| * equity / ADV_notional_i) * regime_coeff_t``.

    The book path measures each name against its own ADV on the weight change
    and applies one regime coefficient per period. A regression that applies
    the coefficient to the mean rather than each asset, or mis-aligns the
    regime series against the book index, would not be caught by the
    constant-coefficient book test. This pins the formula on a constant-volume,
    zero-return frame where the closed form is exact.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    symbols = ["AAA", "BBB", "CCC"]
    close = pd.DataFrame(
        {sym: np.full(periods, px)
         for sym, px in zip(symbols, [100.0, 200.0, 50.0])},
        index=dates,
    )
    volume = pd.DataFrame(
        {sym: np.full(periods, vol)
         for sym, vol in zip(symbols, [1_000_000.0, 2_000_000.0, 500_000.0])},
        index=dates,
    )
    held_book = pd.DataFrame(
        {
            "AAA": [0.5, 0.5, 0.5, -0.5, -0.5, 0.5],
            "BBB": [-0.5, -0.5, -0.5, 0.5, 0.5, -0.5],
            "CCC": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        },
        index=dates,
    )
    raw_returns = pd.Series(np.zeros(periods), index=dates)
    regimes = pd.Series(["hi", "lo", "hi", "lo", "hi", "lo"], index=dates)
    regime_impact_coefficients = {"hi": 0.8, "lo": 0.2}

    coefficient = 0.5
    adv_window = 20
    initial_capital = 100_000.0

    result = book_market_impact_cost(
        held_book=held_book, raw_returns=raw_returns, close=close,
        volume=volume, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="sqrt", impact_aggregation="notional-weighted",
        regimes=regimes, regime_impact_coefficients=regime_impact_coefficients,
    )
    assert result is not None, "regime-aware notional-weighted sqrt book impact must be live for coefficient > 0"

    equity = initial_capital * (1 + raw_returns).cumprod()
    traded_weight = held_book.diff().abs()
    adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
    traded_notional = traded_weight.mul(equity, axis=0).fillna(0.0)
    participation = traded_notional.values / adv_notional.values
    period_coeff = regimes.map(regime_impact_coefficients).values[:, None]
    rate = np.sqrt(participation) * period_coeff
    expected = (rate * traded_weight.fillna(0.0).values).sum(axis=1)

    assert np.allclose(result.values, expected, atol=1e-12), (
        f"regime-aware notional-weighted book sqrt impact must equal "
        f"sum_i rate_i*|dw_i|: "
        f"got {result.values}, expected {expected}"
    )


def test_book_regime_aware_linear_notional_weighted_matches_closed_form():
    """The book-pricing regime-aware linear impact under
    ``notional-weighted`` aggregation must equal ``sum_i rate_i * |dw_i|`` where
    ``rate_i = (|dw_i| * equity / ADV_notional_i) * regime_coeff_t``.

    The book path measures each name against its own ADV on the weight change
    and applies one regime coefficient per period. A regression that applies
    the coefficient to the mean rather than each asset, or mis-aligns the
    regime series against the book index, would not be caught by the
    constant-coefficient book test.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    symbols = ["AAA", "BBB", "CCC"]
    close = pd.DataFrame(
        {sym: np.full(periods, px)
         for sym, px in zip(symbols, [100.0, 200.0, 50.0])},
        index=dates,
    )
    volume = pd.DataFrame(
        {sym: np.full(periods, vol)
         for sym, vol in zip(symbols, [1_000_000.0, 2_000_000.0, 500_000.0])},
        index=dates,
    )
    held_book = pd.DataFrame(
        {
            "AAA": [0.5, 0.5, 0.5, -0.5, -0.5, 0.5],
            "BBB": [-0.5, -0.5, -0.5, 0.5, 0.5, -0.5],
            "CCC": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        },
        index=dates,
    )
    raw_returns = pd.Series(np.zeros(periods), index=dates)
    regimes = pd.Series(["hi", "lo", "hi", "lo", "hi", "lo"], index=dates)
    regime_impact_coefficients = {"hi": 0.8, "lo": 0.2}

    coefficient = 0.5
    adv_window = 20
    initial_capital = 100_000.0

    result = book_market_impact_cost(
        held_book=held_book, raw_returns=raw_returns, close=close,
        volume=volume, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="linear", impact_aggregation="notional-weighted",
        regimes=regimes, regime_impact_coefficients=regime_impact_coefficients,
    )
    assert result is not None, "regime-aware notional-weighted linear book impact must be live for coefficient > 0"

    equity = initial_capital * (1 + raw_returns).cumprod()
    traded_weight = held_book.diff().abs()
    adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
    traded_notional = traded_weight.mul(equity, axis=0).fillna(0.0)
    participation = traded_notional.values / adv_notional.values
    period_coeff = regimes.map(regime_impact_coefficients).values[:, None]
    rate = participation * period_coeff
    expected = (rate * traded_weight.fillna(0.0).values).sum(axis=1)

    assert np.allclose(result.values, expected, atol=1e-12), (
        f"regime-aware notional-weighted book linear impact must equal "
        f"sum_i rate_i*|dw_i|: "
        f"got {result.values}, expected {expected}"
    )


# ---------------------------------------------------------------------------
# Regime-aware NOTIONAL-WEIGHTED market-impact model: closed-form formula pin
# (single-asset regime-aware + notional-weighted combined)
# ---------------------------------------------------------------------------

def test_single_asset_notional_weighted_regime_aware_sqrt_matches_closed_form():
    """The single-asset (``is_panel=False``) square-root impact under
    ``notional-weighted`` aggregation with regime-aware coefficients must equal
    ``sqrt(participation) * period_impact_coeff * position_changes``.

    Pins the combined ``is_panel=False`` + ``impact_aggregation="notional-weighted"``
    + ``regimes``/``regime_impact_coefficients`` branch, where the concession rate
    is scaled by a per-period regime coefficient and then charged as a fraction of
    equity (rate * |d|). Mirrors the existing single-asset regime-aware and
    notional-weighted tests but exercises both together. Unknown regime labels must
    fall back to the base ``impact_coefficient``.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0], index=dates)
    volume = pd.Series(np.full(periods, 1_000_000.0), index=dates)
    raw_returns = pd.Series(np.zeros(periods), index=dates)
    position_changes = pd.Series([0.0, 1.0, 0.0, 0.5, 0.0, 1.0], index=dates)
    regimes = pd.Series(["hi", "lo", "hi", "hi", "lo", "hi"], index=dates)
    regime_impact_coefficients = {"hi": 0.8, "lo": 0.2}

    coefficient = 0.5
    adv_window = 20
    initial_capital = 100_000.0

    result = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=False, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="sqrt", impact_aggregation="notional-weighted",
        regimes=regimes, regime_impact_coefficients=regime_impact_coefficients,
    )
    assert result is not None, "notional-weighted regime-aware sqrt impact must be live for coefficient > 0"

    equity = initial_capital * (1 + raw_returns).cumprod()
    adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
    participation = (position_changes * equity) / adv_notional
    period_coeff = regimes.map(regime_impact_coefficients)
    expected = np.sqrt(participation) * period_coeff * position_changes
    assert np.allclose(result.values, expected.values, atol=1e-12), (
        f"single-asset notional-weighted regime-aware sqrt impact must equal "
        f"sqrt(participation)*regime_coeff*|d|: "
        f"got {result.values}, expected {expected.values}"
    )

    unknown_regimes = pd.Series(["not_a_regime"] * periods, index=dates)
    fallback = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=False, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="sqrt", impact_aggregation="notional-weighted",
        regimes=unknown_regimes, regime_impact_coefficients=regime_impact_coefficients,
    )
    expected_fallback = np.sqrt(participation) * coefficient * position_changes
    assert np.allclose(fallback.values, expected_fallback.values, atol=1e-12), (
        f"unknown regime must fall back to the base coefficient: "
        f"got {fallback.values}, expected {expected_fallback.values}"
    )


def test_single_asset_notional_weighted_regime_aware_linear_matches_closed_form():
    """The single-asset (``is_panel=False``) linear impact under
    ``notional-weighted`` aggregation with regime-aware coefficients must equal
    ``participation * period_impact_coeff * position_changes``.

    Mirrors ``test_single_asset_notional_weighted_regime_aware_sqrt_matches_closed_form``
    for the linear branch. Unknown regime labels must fall back to the base
    ``impact_coefficient``.
    """
    periods = 6
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0], index=dates)
    volume = pd.Series(np.full(periods, 1_000_000.0), index=dates)
    raw_returns = pd.Series(np.zeros(periods), index=dates)
    position_changes = pd.Series([0.0, 1.0, 0.0, 0.5, 0.0, 1.0], index=dates)
    regimes = pd.Series(["hi", "lo", "hi", "hi", "lo", "hi"], index=dates)
    regime_impact_coefficients = {"hi": 0.8, "lo": 0.2}

    coefficient = 0.5
    adv_window = 20
    initial_capital = 100_000.0

    result = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=False, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="linear", impact_aggregation="notional-weighted",
        regimes=regimes, regime_impact_coefficients=regime_impact_coefficients,
    )
    assert result is not None, "notional-weighted regime-aware linear impact must be live for coefficient > 0"

    equity = initial_capital * (1 + raw_returns).cumprod()
    adv_notional = volume.rolling(window=adv_window, min_periods=1).mean() * close
    participation = (position_changes * equity) / adv_notional
    period_coeff = regimes.map(regime_impact_coefficients)
    expected = participation * period_coeff * position_changes
    assert np.allclose(result.values, expected.values, atol=1e-12), (
        f"single-asset notional-weighted regime-aware linear impact must equal "
        f"participation*regime_coeff*|d|: "
        f"got {result.values}, expected {expected.values}"
    )

    unknown_regimes = pd.Series(["not_a_regime"] * periods, index=dates)
    fallback = market_impact_cost(
        position_changes, raw_returns, close, volume,
        is_panel=False, impact_coefficient=coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
        impact_model="linear", impact_aggregation="notional-weighted",
        regimes=unknown_regimes, regime_impact_coefficients=regime_impact_coefficients,
    )
    expected_fallback = participation * coefficient * position_changes
    assert np.allclose(fallback.values, expected_fallback.values, atol=1e-12), (
        f"unknown regime must fall back to the base coefficient: "
        f"got {fallback.values}, expected {expected_fallback.values}"
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TEST_REGISTRY = [
    ("test_borrow_cost_reduces_short_returns", test_borrow_cost_reduces_short_returns),
    ("test_borrow_cost_no_effect_on_long_or_flat", test_borrow_cost_no_effect_on_long_or_flat),
    ("test_funding_cost_reduces_leveraged_returns", test_funding_cost_reduces_leveraged_returns),
    ("test_funding_cost_no_effect_at_or_below_1x", test_funding_cost_no_effect_at_or_below_1x),
    ("test_commission_and_slippage_reduce_returns_with_turnover", test_commission_and_slippage_reduce_returns_with_turnover),
    ("test_zero_turnover_pays_no_commission_after_entry", test_zero_turnover_pays_no_commission_after_entry),
    ("test_market_impact_is_live", test_market_impact_is_live),
    ("test_market_impact_monotone_in_coefficient", test_market_impact_monotone_in_coefficient),
    ("test_fill_rate_scales_positions_and_costs_elementwise", test_fill_rate_scales_positions_and_costs_elementwise),
    ("test_deterministic_given_identical_inputs", test_deterministic_given_identical_inputs),
    ("test_book_pricing_matches_book_pnl_minus_independently_computed_costs",
     test_book_pricing_matches_book_pnl_minus_independently_computed_costs),
    ("test_book_pricing_charges_gross_turnover_on_rotation_in_place",
     test_book_pricing_charges_gross_turnover_on_rotation_in_place),
    ("test_book_borrow_cost_charges_short_legs", test_book_borrow_cost_charges_short_legs),
    ("test_book_funding_cost_charges_gross_exposure_beyond_1x",
     test_book_funding_cost_charges_gross_exposure_beyond_1x),
    ("test_book_market_impact_live_and_monotone", test_book_market_impact_live_and_monotone),
    ("test_book_pricing_deterministic_given_identical_inputs",
     test_book_pricing_deterministic_given_identical_inputs),
    ("test_market_impact_reduces_returns_market_neutral_pairs_portfolio",
     test_market_impact_reduces_returns_market_neutral_pairs_portfolio),
    ("test_dict_panel_constant_position_pays_no_per_bar_impact_after_entry",
     test_dict_panel_constant_position_pays_no_per_bar_impact_after_entry),
    ("test_market_impact_sqrt_model_differs_from_linear_single_asset",
     test_market_impact_sqrt_model_differs_from_linear_single_asset),
    ("test_sqrt_market_impact_matches_closed_form",
     test_sqrt_market_impact_matches_closed_form),
    ("test_single_asset_notional_weighted_sqrt_matches_closed_form",
     test_single_asset_notional_weighted_sqrt_matches_closed_form),
    ("test_panel_sqrt_market_impact_matches_closed_form",
     test_panel_sqrt_market_impact_matches_closed_form),
    ("test_book_sqrt_market_impact_matches_closed_form",
     test_book_sqrt_market_impact_matches_closed_form),
    ("test_single_asset_regime_aware_sqrt_matches_closed_form",
     test_single_asset_regime_aware_sqrt_matches_closed_form),
    ("test_panel_regime_aware_sqrt_matches_closed_form",
     test_panel_regime_aware_sqrt_matches_closed_form),
    ("test_book_regime_aware_sqrt_matches_closed_form",
     test_book_regime_aware_sqrt_matches_closed_form),
    ("test_single_asset_regime_aware_linear_matches_closed_form",
     test_single_asset_regime_aware_linear_matches_closed_form),
    ("test_panel_regime_aware_linear_matches_closed_form",
     test_panel_regime_aware_linear_matches_closed_form),
    ("test_book_regime_aware_linear_matches_closed_form",
     test_book_regime_aware_linear_matches_closed_form),
    ("test_single_asset_regime_aware_sqrt_notional_weighted_matches_closed_form",
     test_single_asset_regime_aware_sqrt_notional_weighted_matches_closed_form),
    ("test_single_asset_regime_aware_linear_notional_weighted_matches_closed_form",
     test_single_asset_regime_aware_linear_notional_weighted_matches_closed_form),
    ("test_panel_regime_aware_sqrt_notional_weighted_matches_closed_form",
     test_panel_regime_aware_sqrt_notional_weighted_matches_closed_form),
    ("test_panel_regime_aware_linear_notional_weighted_matches_closed_form",
     test_panel_regime_aware_linear_notional_weighted_matches_closed_form),
    ("test_book_regime_aware_sqrt_notional_weighted_matches_closed_form",
     test_book_regime_aware_sqrt_notional_weighted_matches_closed_form),
("test_book_regime_aware_linear_notional_weighted_matches_closed_form",
      test_book_regime_aware_linear_notional_weighted_matches_closed_form),
    ("test_single_asset_notional_weighted_regime_aware_sqrt_matches_closed_form",
      test_single_asset_notional_weighted_regime_aware_sqrt_matches_closed_form),
    ("test_single_asset_notional_weighted_regime_aware_linear_matches_closed_form",
      test_single_asset_notional_weighted_regime_aware_linear_matches_closed_form),
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
