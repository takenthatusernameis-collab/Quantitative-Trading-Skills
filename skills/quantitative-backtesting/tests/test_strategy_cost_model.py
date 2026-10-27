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
