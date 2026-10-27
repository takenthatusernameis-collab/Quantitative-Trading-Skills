#!/usr/bin/env python3
"""
Unit tests for the strategy-side cost model in `walk_forward._calculate_strategy_returns`.

`_calculate_strategy_returns` prices commission, slippage, market impact,
borrow cost (short exposure) and funding cost (leverage beyond 1x) on top of
the raw signal returns.  These execution-cost assumptions underpin every
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
