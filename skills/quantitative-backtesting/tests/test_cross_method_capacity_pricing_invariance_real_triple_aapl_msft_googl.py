#!/usr/bin/env python3
"""Cross-method capacity comparison: basket vs book, net-exposure vs book.

Runs the SAME market-neutral cross-sectional momentum strategy on the committed
three-asset panel (AAPL / MSFT / GOOGL) under both panel-pricing conventions
(``net-exposure`` and ``book``) and pins the relationship between the two
capacity estimators:

* ``summary["capacity"]`` is the *basket* rule from
  :func:`walk_forward.estimate_capacity` (equal-weight basket; the least
  liquid constituent binds). It is a pure liquidity property of the panel and
  the impact model -- it does NOT depend on how the portfolio return is priced.
  The test asserts it is IDENTICAL across the two pricing modes.
* ``summary["capacity_book"]`` is the *book* rule from
  :func:`utils.book_capacity_estimate` (the strategy's own per-period trade
  sizes). It is only reported in book mode (it needs ``generate_target_weights``)
  and is ``None`` under net-exposure.

For a cross-sectional book that only rotates when its constituent set changes,
the per-period trade sizes differ from the equal-weight ``1 / n_assets`` basket
assumption, so ``capacity_book`` differs from the basket ``capacity``. This test
quantifies that gap (ratio + direction) and pins both numbers so a regression in
either estimator is caught.

No profitability or capacity claim is made: capacity is an execution-side
control, and the committed fixtures are placeholders (see PROVENANCE.json).

Offline, committed fixtures only
(assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv). No live network.
"""
import contextlib
import io
import json
import sys
import warnings
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

import pandas as pd  # noqa: E402

from walk_forward import walk_forward_analysis  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade
IMPACT_COEFFICIENT = 0.1

# Pre-registered narrow grid around the cross-sectional momentum settings
# (lookback, top_quantile=0.4, bottom_quantile=0.2). Asymmetric quantiles so
# the long and short books differ in size and the portfolio signal is non-zero
# by construction. Fixed before any result is inspected; small enough to stay
# fast in CI. Matches
# test_cross_sectional_momentum_capacity_sensitivity_real_triple_aapl_msft_googl.py.
PARAM_GRID = {
    "lookback": [10, 20],
    "top_quantile": [0.4],
    "bottom_quantile": [0.2],
}

TRAIN_MONTHS = 12
TEST_MONTHS = 12
STEP_MONTHS = 12

# Measured on the committed triple panel at IMPACT_COEFFICIENT=0.1. The basket
# capacity is pricing-independent; the book capacity reflects the strategy's
# own (concentrated) rebalance pattern and is strictly below the basket here.
EXPECTED_BASKET_CAPACITY = 146092783.94110104
EXPECTED_BOOK_CAPACITY = 70135726.87072335
REL_TOL = 1e-6


def _build_panel():
    panel = {}
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date").sort_index()
        panel[Path(name).stem] = df
    return panel


def _factory(params):
    return build_strategy("cross_sectional_momentum", json.dumps(params))


def _run_walk_forward(panel_pricing):
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
        panel_pricing=panel_pricing,
        apply_deflation=True,
        validate_pit=True,
    )


def _basket_capacity(summary):
    capacity = summary.get("capacity")
    if isinstance(capacity, dict):
        capacity = capacity.get("cost_adjusted_capacity")
    return capacity


def test_cross_method_capacity_pricing_invariance_and_book_gap_real_triple_panel():
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists(), f"missing fixture {name}"

    buffer = io.StringIO()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with contextlib.redirect_stdout(buffer):
            ne = _run_walk_forward("net-exposure")
            bk = _run_walk_forward("book")

    ne_summary = ne["summary"]
    bk_summary = bk["summary"]

    ne_capacity = _basket_capacity(ne_summary)
    bk_capacity = _basket_capacity(bk_summary)
    bk_capacity_book = bk_summary.get("capacity_book")

    print(
        "CROSS-METHOD CAPACITY COMPARISON: "
        f"net-exposure basket capacity=${ne_capacity:,.0f} "
        f"book basket capacity=${bk_capacity:,.0f} "
        f"book capacity_book=${bk_capacity_book:,.0f} "
        f"(book/basket ratio={bk_capacity_book / bk_capacity:.4f})"
    )

    # The reported pricing mode must match what was requested.
    assert ne_summary.get("panel_pricing") == "net-exposure"
    assert bk_summary.get("panel_pricing") == "book"

    # 1. Basket capacity is a liquidity property: identical across pricing modes.
    assert ne_capacity is not None and bk_capacity is not None, (
        "basket capacity must be reported under both pricing modes"
    )
    assert abs(ne_capacity - bk_capacity) <= REL_TOL * abs(bk_capacity), (
        "basket capacity must be pricing-independent: "
        f"net-exposure={ne_capacity} vs book={bk_capacity}"
    )

    # 2. The book-based capacity is only defined in book mode.
    assert ne_summary.get("capacity_book") is None, (
        "capacity_book must be None under net-exposure pricing, got "
        f"{ne_summary.get('capacity_book')}"
    )
    assert bk_capacity_book is not None and float(bk_capacity_book) > 0, (
        f"book mode must report a positive capacity_book, got {bk_capacity_book}"
    )

    # 3. Quantify the gap: the concentrated cross-sectional book trades a
    #    different amount per period than the equal-weight basket, so its
    #    book capacity is strictly below the basket capacity here.
    assert float(bk_capacity_book) < float(bk_capacity), (
        "book capacity must be below the basket capacity for this concentrated "
        f"book: capacity_book={bk_capacity_book} vs basket={bk_capacity}"
    )
    ratio = float(bk_capacity_book) / float(bk_capacity)
    print(f"  Book/basket capacity ratio = {ratio:.4f}")

    # 4. Pin both estimators so a regression in either is caught.
    assert abs(ne_capacity - EXPECTED_BASKET_CAPACITY) <= REL_TOL * abs(
        EXPECTED_BASKET_CAPACITY
    ), f"net-exposure basket capacity drifted: {ne_capacity}"
    assert abs(bk_capacity - EXPECTED_BASKET_CAPACITY) <= REL_TOL * abs(
        EXPECTED_BASKET_CAPACITY
    ), f"book basket capacity drifted: {bk_capacity}"
    assert abs(float(bk_capacity_book) - EXPECTED_BOOK_CAPACITY) <= REL_TOL * abs(
        EXPECTED_BOOK_CAPACITY
    ), f"book capacity_book drifted: {bk_capacity_book}"

    flat_warnings = [
        str(w.message)
        for w in caught
        if "flat (zero) portfolio signal" in str(w.message)
    ]
    assert flat_warnings == [], f"unexpected flat-signal warning: {flat_warnings}"


if __name__ == "__main__":
    test_cross_method_capacity_pricing_invariance_and_book_gap_real_triple_panel()
    print("OK")