#!/usr/bin/env python3
"""
Shared utility functions for the quantitative backtesting toolkit.
"""

import numpy as np
import pandas as pd


# Panel pricing modes.
#
# ``net-exposure`` (the default) prices a panel as
# ``net_exposure x mean(asset returns)`` -- one scalar per period, the
# convention every published number in this skill was produced under.
# ``book`` prices the panel as the true book return ``sum_i w_i r_i`` of the
# per-asset weights the strategy exposes through
# ``StrategyBase.generate_target_weights``.
PANEL_PRICING_MODES = ("net-exposure", "book")
DEFAULT_PANEL_PRICING = "net-exposure"


def resolve_panel_pricing(mode) -> str:
    """Normalize and validate a panel pricing mode.

    Args:
        mode: ``"net-exposure"``, ``"book"``, or ``None`` (which means the
            default, ``"net-exposure"``).

    Returns:
        The canonical mode string.

    Raises:
        ValueError: when the mode is not one of :data:`PANEL_PRICING_MODES`.
    """
    if mode is None:
        return DEFAULT_PANEL_PRICING
    normalized = str(mode).strip().lower()
    if normalized not in PANEL_PRICING_MODES:
        raise ValueError(
            f"Unknown panel pricing mode: {mode!r}. "
            f"Use one of: {', '.join(PANEL_PRICING_MODES)}."
        )
    return normalized


def build_market_model(data):
    """Normalize market data into the single representation used by every
    backtest path (``run_backtest.py`` and ``walk_forward.py``).

    The two backtest entry points must price a panel identically, otherwise
    results from the single-backtest CLI and the walk-forward / CPCV /
    out-of-sample CLIs are not comparable. This function is the one place
    where that convention is defined.

    Panel convention (equal-weighted, rebalanced basket)
    ----------------------------------------------------
    A panel is modelled as an equal-weighted basket of its constituents:
    each asset carries ``1 / n_assets`` of the portfolio notional and the
    portfolio return is the **mean of the per-asset returns**
    (``close.pct_change().mean(axis=1)``).

    The alternative -- the return of the mean price series
    (``close.mean(axis=1).pct_change()``) -- is *not* used: it prices a
    price-weighted basket whose weights drift with the relative price moves
    of the constituents, which is a rebalancing rule the position model
    does not represent. The mean-of-returns convention is also the one the
    market-impact model assumes (see :func:`market_impact_cost`).

    Args:
        data: OHLCV data in one of three shapes.
            * ``pd.DataFrame`` with flat columns -- a single asset.
            * ``pd.DataFrame`` with MultiIndex columns -- a panel whose
              level 0 carries the field names and level 1 the symbols.
            * ``dict`` of ``{symbol: OHLCV DataFrame}`` -- a panel; the
              frames are aligned on the intersection of their date indexes.

    Returns:
        dict with the keys:
            ``raw_returns``: ``pd.Series`` of market returns per period.
            ``close``: ``pd.Series`` (single asset) or ``pd.DataFrame``
                with one column per asset (panel).
            ``volume``: same shape as ``close``, or ``None`` when volume is
                unavailable. For a dict panel the volume frame is only
                built when *every* constituent carries a volume column, so
                the impact model never mixes a per-asset ADV with a
                portfolio-level notional.
            ``price``: ``pd.Series`` -- a representative price series for
                trade ledgers (the close for a single asset, the
                equal-weighted mean of the per-asset closes for a panel).
            ``is_panel``: ``bool``.
    """
    if isinstance(data, dict):
        common_index = None
        for df in data.values():
            if common_index is None:
                common_index = df.index
            else:
                common_index = common_index.intersection(df.index)
        common_index = common_index.sort_values()
        close_list = []
        volume_list = []
        for df in data.values():
            aligned = df.reindex(common_index)
            close_list.append(aligned["close"])
            if "volume" in aligned.columns:
                volume_list.append(aligned["volume"])
        asset_keys = list(data.keys())
        close = pd.concat(close_list, axis=1)
        # The concatenated frames carry duplicate "close" labels; rename
        # them to the asset keys so per-asset arithmetic (and the
        # MultiIndex capacity frame built from them) stays well defined.
        close.columns = asset_keys
        raw_returns = close.pct_change().mean(axis=1)
        volume = None
        if len(volume_list) == len(asset_keys):
            volume = pd.concat(volume_list, axis=1)
            volume.columns = asset_keys
        is_panel = True
    elif isinstance(data.columns, pd.MultiIndex):
        close = data["close"]
        raw_returns = close.pct_change().mean(axis=1)
        volume = (
            data["volume"]
            if "volume" in data.columns.get_level_values(0)
            else None
        )
        is_panel = True
    else:
        close = data["close"]
        raw_returns = close.pct_change()
        volume = data["volume"] if "volume" in data.columns else None
        is_panel = False

    price = close.mean(axis=1) if is_panel else close

    return {
        "raw_returns": raw_returns,
        "close": close,
        "volume": volume,
        "price": price,
        "is_panel": is_panel,
    }


def market_impact_cost(
    position_changes,
    raw_returns,
    close,
    volume,
    is_panel,
    impact_coefficient,
    adv_window=20,
    initial_capital=100000.0,
):
    """Per-period market-impact cost, expressed as a fraction of the
    portfolio notional traded.

    The model is linear::

        impact = (position_notional / ADV_notional) * impact_coefficient

    with ``ADV_notional = rolling_mean(volume) * close`` and
    ``position_notional = |position_change| * equity``, the equity being
    approximated by ``initial_capital * cumprod(1 + raw_returns)``.

    Panel convention
    ----------------
    A panel is an equal-weighted basket: a position change of ``|d|``
    trades ``|d| * equity / n_assets`` in each constituent, every
    constituent is measured against **its own** ADV, and the portfolio
    impact cost is the equal-weighted mean of the per-asset impacts.

    This matters: charging the whole portfolio notional against a single
    (or aggregated pseudo-asset) ADV overstates the impact by roughly
    ``n_assets``, and -- because the resulting cost is a DataFrame rather
    than a Series -- silently empties the return series of a MultiIndex
    panel (every panel run with impact enabled then reports "no signal").

    Args:
        position_changes: ``pd.Series`` of ``|position_change|`` per period.
        raw_returns: ``pd.Series`` of market returns per period (the market
            model the portfolio is marked against).
        close: close prices -- ``pd.Series`` (single asset) or ``pd.DataFrame``
            with one column per asset (panel).
        volume: volumes, same shape as ``close``, or ``None``.
        is_panel: whether ``close``/``volume`` are per-asset frames.
        impact_coefficient: linear impact coefficient; ``0`` disables impact.
        adv_window: rolling window (in periods) for the ADV.
        initial_capital: starting portfolio value used to scale notional.

    Returns:
        ``pd.Series`` of impact cost per period, or ``None`` when impact is
        disabled (no volume, or a zero coefficient).
    """
    if impact_coefficient <= 0 or volume is None:
        return None

    # Average Daily Volume in shares (rolling)
    adv_shares = volume.rolling(window=adv_window, min_periods=1).mean()
    # Average Daily Volume in notional (shares * price)
    adv_notional = adv_shares * close
    # Equity value of the position at risk, scaled by initial_capital so
    # that a 100% position change on a $100k account is ~$100k notional.
    equity = initial_capital * (1 + raw_returns).cumprod()
    position_notional = position_changes * equity

    if is_panel:
        n_assets = max(close.shape[1], 1)
        per_asset_notional = position_notional / n_assets
        # `adv_denominator.rdiv(traded, axis=0)` computes traded_notional /
        # ADV for every (row, asset) pair (a plain Series/DataFrame
        # division would align the Series to the columns instead). A zero
        # traded notional means "no trade", so the impact is zero rather
        # than infinite; a zero ADV is treated as missing.
        traded = per_asset_notional.replace(0, np.nan)
        adv_denominator = adv_notional.replace(0, np.nan)
        market_impact = adv_denominator.rdiv(traded, axis=0) * impact_coefficient
        market_impact = market_impact.fillna(0).mean(axis=1)
    else:
        # Market impact as fraction of notional traded
        market_impact = (
            position_notional / adv_notional.replace(0, np.nan)
        ) * impact_coefficient
        market_impact = market_impact.fillna(0)
    return market_impact


def strategy_target_weights(strategy, data):
    """Per-asset target book of a strategy, or ``None`` when it has none.

    The accessor is optional by design: ``StrategyBase.generate_target_weights``
    returns ``None`` by default, so every strategy that does not model an
    explicit book keeps its current behaviour (and single-asset runs never
    produce a book).

    Args:
        strategy: a strategy instance.
        data: the same market data the strategy's signals were generated from.

    Returns:
        A ``pd.DataFrame`` of portfolio weights (rows = dates, columns =
        symbols) or ``None``.
    """
    getter = getattr(strategy, "generate_target_weights", None)
    if getter is None:
        return None
    weights = getter(data)
    if weights is None or not isinstance(weights, pd.DataFrame) or weights.empty:
        return None
    return weights


def held_book_weights(
    weights,
    market,
    lag: int = 1,
    fill_rate: float = 1.0,
    warmup: str = "zero",
):
    """The per-asset book actually held on each bar of the market model.

    The target book is lagged by the execution convention (``lag = 1 +
    latency`` periods) and scaled by the fill rate -- exactly the convention
    the framework's position series uses -- so the book and the positions are
    measured on the same bars.

    Args:
        weights: per-asset target weights (rows = dates, columns = symbols)
            as returned by :func:`strategy_target_weights`, or ``None``.
        market: the market model returned by :func:`build_market_model`.
        lag: execution lag in periods (1 + latency).
        fill_rate: fraction of each targeted change that is filled.
        warmup: how the bars before the first executable one are represented.

            * ``"zero"`` (default): a flat book (weight 0). The book is
              *defined* but empty, so its return contribution is 0 and its
              turnover is 0.
            * ``"nan"``: the book is *undefined* before the first executable
              bar, mirroring a position series that is NaN there. The
              difference is observable in the cost model: with a NaN warmup
              the first book change is not charged and the bar it happens on
              is dropped from the return series, which is exactly what the
              framework's net-exposure path does with a NaN position series.

    Returns:
        A ``pd.DataFrame`` of held weights on the market model's index and
        columns, or ``None`` when there is no usable book (no weights, a
        single-asset path, or a book over a different universe).
    """
    if weights is None or not isinstance(weights, pd.DataFrame) or weights.empty:
        return None
    close = market.get("close")
    if not isinstance(close, pd.DataFrame) or close.shape[1] == 0:
        return None
    # The strategy's book and the market model must describe the same
    # universe; otherwise the book would silently measure as flat.
    if not set(weights.columns).intersection(set(close.columns)):
        return None
    target = weights.reindex(columns=close.columns).reindex(close.index).fillna(0.0)
    held = target.shift(lag) * fill_rate
    if warmup == "nan":
        return held
    if warmup != "zero":
        raise ValueError(
            f"Unknown book warmup convention: {warmup!r}. "
            "Use one of: 'zero', 'nan'."
        )
    return held.fillna(0.0)


def book_gross_turnover(held_book):
    """Per-period gross turnover of a book: ``sum_i |dw_i|``.

    The book's turnover is the total notional weight that changes hands in a
    period, summed over the assets. It is the quantity a transaction-cost
    model must charge: the net-exposure convention can only see
    ``|d sum_i w_i|``, which is zero for a book that rotates in place (a
    market-neutral book in particular).

    ``min_count=1`` keeps a row whose per-asset changes are all undefined
    (the warmup bars of a NaN-warmup book) as ``NaN`` instead of collapsing
    it to 0, so the book cost basis can drop exactly the same bars the
    net-exposure path drops.

    Args:
        held: held per-asset weights (rows = dates, columns = symbols).

    Returns:
        A ``pd.Series`` of gross turnover per period.
    """
    return held_book.diff().abs().sum(axis=1, min_count=1)


def book_cost_components(
    held_book,
    commission: float = 0.0,
    slippage: float = 0.0,
    borrow_cost: float = 0.0,
    funding_cost: float = 0.0,
    ann_factor: int = 252,
):
    """The transaction, borrow and funding costs of a per-asset book.

    This is the book-mode counterpart of the net-exposure cost model: every
    term is charged on the *book* rather than on the scalar net exposure.

    ==================  ==================================================
    term                basis
    ==================  ==================================================
    transaction         gross turnover ``sum_i |dw_i|``
    borrow              short legs ``sum_i max(-w_i, 0)``
    funding             gross exposure ``sum_i |w_i|`` above 1x
    ==================  ==================================================

    The fill rate is already inside ``held`` (the book is scaled by it), so
    every term scales with the fill rate exactly like the net-exposure cost
    model does.

    Args:
        held: held per-asset weights (rows = dates, columns = symbols).
        commission: commission rate per trade (as a decimal).
        slippage: slippage rate per trade (as a decimal).
        borrow_cost: annual borrow cost rate for short legs (as a decimal).
        funding_cost: annual funding cost rate for leverage (as a decimal).
        ann_factor: periods per year, used to convert the annual rates to
            per-period rates.

    Returns:
        A dict of ``pd.Series`` with the keys ``turnover``, ``transaction``,
        ``short_exposure``, ``gross_exposure``, ``borrow``, ``funding`` and
        ``total``, or ``None`` when there is no usable book.
    """
    if held_book is None or not isinstance(held_book, pd.DataFrame) or held_book.empty:
        return None

    turnover = book_gross_turnover(held_book)
    transaction = turnover * (commission + slippage)
    # Short legs: the absolute short exposure of the book, summed over the
    # assets. A market-neutral book has a flat *net* exposure but a real
    # short leg, which the net-exposure cost model cannot see.
    short_exposure = held_book.clip(upper=0).abs().sum(axis=1, min_count=1)
    gross_exposure = held_book.abs().sum(axis=1, min_count=1)

    borrow = short_exposure * (borrow_cost / ann_factor)
    # Funding is charged on the leverage used beyond 100% of equity, where
    # the leverage of a book is its gross exposure.
    leverage_excess = (gross_exposure - 1.0).clip(lower=0)
    funding = leverage_excess * (funding_cost / ann_factor)

    return {
        "turnover": turnover,
        "transaction": transaction,
        "short_exposure": short_exposure,
        "gross_exposure": gross_exposure,
        "borrow": borrow,
        "funding": funding,
        "total": transaction + borrow + funding,
    }


def book_market_impact_cost(
    held_book,
    raw_returns,
    close,
    volume,
    impact_coefficient,
    adv_window=20,
    initial_capital=100000.0,
):
    """Per-period market-impact cost of trading a per-asset book.

    The model is linear and per asset::

        impact_i = (traded_notional_i / ADV_notional_i) * impact_coefficient

    with ``traded_notional_i = |dw_i| * equity`` (the weight change of that
    asset times the portfolio equity) and ``ADV_notional_i = rolling_mean(
    volume_i) * close_i``. The portfolio cost is the **equal-weighted mean
    of the per-asset impacts**, the same panel convention the net-exposure
    impact model uses, so the two pricing modes stay on the same scale.

    Two properties follow from the model and are asserted by the test suite:

    * the cost scales with the fill rate (the fill rate is inside ``held``);
    * every asset is measured against **its own** ADV, so a book that
      concentrates in an illiquid name pays for it.

    The mean-over-assets convention is a simplification: a period in which
    only ``k`` of ``n`` names trade is charged the mean over ``n`` names, so
    the drag is diluted relative to the participation actually consumed. The
    convention is kept identical to the net-exposure path (where every
    constituent always trades ``1 / n`` of the notional) so that the two
    modes remain comparable.

    Args:
        held: held per-asset weights (rows = dates, columns = symbols).
        raw_returns: ``pd.Series`` of market returns per period.
        close: close prices -- ``pd.DataFrame`` with one column per asset.
        volume: volumes, same shape as ``close``, or ``None``.
        impact_coefficient: linear impact coefficient; ``0`` disables impact.
        adv_window: rolling window (in periods) for the ADV.
        initial_capital: starting portfolio value used to scale notional.

    Returns:
        A ``pd.Series`` of impact cost per period, or ``None`` when impact is
        disabled (no volume, or a zero coefficient).
    """
    if impact_coefficient <= 0 or volume is None:
        return None
    if held_book is None or not isinstance(held_book, pd.DataFrame) or held_book.empty:
        return None

    # Average Daily Volume in shares (rolling), then in notional.
    adv_shares = volume.rolling(window=adv_window, min_periods=1).mean()
    adv_notional = adv_shares * close
    # Equity value of the portfolio, scaled by initial_capital so that a
    # 100% weight change on a $100k account is ~$100k notional. Same
    # approximation as the net-exposure impact model.
    equity = initial_capital * (1 + raw_returns).cumprod()

    # The notional traded per asset: the absolute weight change times equity.
    traded_weight = held_book.diff().abs()
    traded_notional = traded_weight.mul(equity, axis=0)

    # A zero traded notional means "no trade", so the impact is zero rather
    # than infinite; a zero ADV is treated as missing.
    traded = traded_notional.replace(0, np.nan)
    adv_denominator = adv_notional.replace(0, np.nan)
    market_impact = adv_denominator.rdiv(traded, axis=0) * impact_coefficient
    return market_impact.fillna(0).mean(axis=1)


def impact_participation_dilution(
    held_book,
    raw_returns,
    close,
    volume,
    impact_coefficient,
    adv_window=20,
    initial_capital=100000.0,
):
    """Measure how much the panel impact model dilutes participation.

    The charged impact (``book_market_impact_cost``) is the equal-weighted
    mean over **all** panel names, including names that did not trade in a
    period (their impact is zero). The traded-only impact is the same per-asset
    model but averaged over the names that actually traded. Their difference
    is the participation dilution: how much less the model charges than the
    traded names would have paid.

    This is a **measurement only**: it does not change any charged cost,
    return, capacity or Sharpe number.

    Returns a dict with ``charged`` and ``traded_only`` (per-period Series),
    ``difference_bps`` (per-period Series, charged - traded_only in bps) and
    ``mean_difference_bps``, or ``None`` when impact is disabled.
    """
    if impact_coefficient <= 0 or volume is None:
        return None
    if held_book is None or not isinstance(held_book, pd.DataFrame) or held_book.empty:
        return None
    charged = book_market_impact_cost(
        held_book, raw_returns, close, volume, impact_coefficient,
        adv_window=adv_window, initial_capital=initial_capital,
    )
    if charged is None:
        return None

    adv_shares = volume.rolling(window=adv_window, min_periods=1).mean()
    adv_notional = adv_shares * close
    equity = initial_capital * (1 + raw_returns).cumprod()
    traded_weight = held_book.diff().abs()
    traded_notional = traded_weight.mul(equity, axis=0)
    traded = traded_notional.replace(0, np.nan)
    adv_denominator = adv_notional.replace(0, np.nan)
    per_asset = adv_denominator.rdiv(traded, axis=0) * impact_coefficient
    # traded-only mean: average over names that actually traded
    traded_only = per_asset.where(per_asset.notna() & (traded_notional != 0)).mean(axis=1, skipna=True).fillna(0.0)
    difference_bps = (charged - traded_only) * 1e4
    return {
        "charged": charged,
        "traded_only": traded_only,
        "difference_bps": difference_bps,
        "mean_difference_bps": float(difference_bps.mean()),
    }


def book_trade_ledger(held_book, close):
    """Per-asset round trips of a book, priced at each asset's own close.

    The net-exposure ledger is a single position series marked on the mean
    price of the panel, so it cannot describe a book: a market-neutral book
    has a flat net exposure and would produce no trade record at all. This
    builds the ledger from the book instead -- one round trip per asset per
    direction.

    A trade for an asset opens on the bar where its weight becomes non-zero
    (or flips sign) and closes on the bar where the weight returns to zero
    (or flips sign again). A *size* change inside a trade does not close it:
    the cross-sectional book resizes its weights whenever the number of
    valid constituents changes, and treating every resize as a new trade
    would bury the ledger in one-bar, zero-P&L records.

    The P&L of a leg is the average weight over the trade times the price
    move, ``w_avg * (exit_price - entry_price)``, which is the leg's
    contribution to the portfolio P&L. The sign is carried by the weight
    itself (a short leg has a negative average weight), so a short leg that
    loses money records a negative P&L. The ``return`` field is that P&L
    divided by the entry price, i.e. the leg's contribution to the portfolio
    *return*; summed over the ledger it approximates the pre-cost book
    return (it does not include compounding or transaction costs, and the
    ``pnl`` field is in price units, not currency).

    Args:
        held: held per-asset weights (rows = dates, columns = symbols).
        close: close prices -- ``pd.DataFrame`` with one column per asset.

    Returns:
        A list of trade dicts with the keys ``pnl``, ``return``,
        ``entry_date``, ``exit_date``, ``symbol``, ``weight`` and (for a
        leg still open at the end of the sample) ``closed_at_end``.
    """
    trades: list = []
    if held_book is None or not isinstance(held_book, pd.DataFrame) or held_book.empty:
        return trades
    if not isinstance(close, pd.DataFrame):
        return trades

    index = held_book.index
    for symbol in held_book.columns:
        if symbol not in close.columns:
            continue
        weights = held_book[symbol].reindex(index).fillna(0.0)
        prices = close[symbol].reindex(index)
        if prices.isna().all():
            continue

        entry_idx = None
        entry_price = None
        entry_date = None
        entry_direction = 0
        weight_sum = 0.0
        n_bars = 0

        for i in range(len(index)):
            weight = float(weights.iloc[i])
            direction = 0 if weight == 0 else (1 if weight > 0 else -1)
            price = prices.iloc[i]
            if pd.isna(price):
                # No price for this bar: the leg cannot be marked. Leave the
                # trade open and continue (it is closed at the next priced
                # bar or at the end of the sample).
                continue

            if direction == 0:
                if entry_idx is not None:
                    w_avg = weight_sum / n_bars if n_bars else 0.0
                    pnl = w_avg * (float(price) - entry_price)
                    trades.append({
                        "pnl": float(pnl),
                        "return": float(pnl / entry_price) if entry_price else 0.0,
                        "entry_date": str(pd.Timestamp(entry_date).date()),
                        "exit_date": str(pd.Timestamp(index[i]).date()),
                        "symbol": str(symbol),
                        "weight": float(w_avg),
                    })
                    entry_idx = None
                    entry_price = None
                    entry_date = None
                    entry_direction = 0
                    weight_sum = 0.0
                    n_bars = 0
                continue

            if entry_idx is None:
                entry_idx = i
                entry_price = float(price)
                entry_date = index[i]
                entry_direction = direction
                weight_sum = weight
                n_bars = 1
            elif direction != entry_direction:
                # A flip: close the old leg and open the new one at the
                # same price.
                w_avg = weight_sum / n_bars if n_bars else 0.0
                pnl = w_avg * (float(price) - entry_price)
                trades.append({
                    "pnl": float(pnl),
                    "return": float(pnl / entry_price) if entry_price else 0.0,
                    "entry_date": str(pd.Timestamp(entry_date).date()),
                    "exit_date": str(pd.Timestamp(index[i]).date()),
                    "symbol": str(symbol),
                    "weight": float(w_avg),
                })
                entry_idx = i
                entry_price = float(price)
                entry_date = index[i]
                entry_direction = direction
                weight_sum = weight
                n_bars = 1
            else:
                weight_sum += weight
                n_bars += 1

        # Mark a leg that is still open at the end of the sample to market.
        # Its P&L is in the equity curve but would otherwise be missing from
        # the ledger, so the trade-level statistics would understate the
        # activity. The exit is forced by the end of the sample, not by a
        # signal, and is flagged via `closed_at_end`.
        if entry_idx is not None and entry_idx < len(index) - 1:
            last_price = prices.iloc[-1]
            if not pd.isna(last_price):
                w_avg = weight_sum / n_bars if n_bars else 0.0
                pnl = w_avg * (float(last_price) - entry_price)
                trades.append({
                    "pnl": float(pnl),
                    "return": float(pnl / entry_price) if entry_price else 0.0,
                    "entry_date": str(pd.Timestamp(entry_date).date()),
                    "exit_date": str(pd.Timestamp(index[-1]).date()),
                    "symbol": str(symbol),
                    "weight": float(w_avg),
                    "closed_at_end": True,
                })

    return trades


def book_return_from_held(held_book, close):
    """The book return per period of an already-held book: ``sum_i w_i r_i``.

    The first bar has no per-asset return and is therefore ``NaN`` (not 0),
    so the book-priced return series has the same index as the net-exposure
    one.

    Args:
        held: held per-asset weights (rows = dates, columns = symbols).
        close: close prices -- ``pd.DataFrame`` with one column per asset.

    Returns:
        A ``pd.Series`` of book returns.
    """
    asset_returns = close.pct_change()
    # `min_count=1` keeps an all-NaN row (the first bar, which has no
    # return) as NaN instead of collapsing it to 0, so the book-priced
    # series has exactly the same index as the net-exposure series.
    return (held_book * asset_returns).sum(axis=1, min_count=1)


def book_return_series(weights, market, lag: int = 1, fill_rate: float = 1.0):
    """The true book return per period: ``sum_i w_i r_i``.

    This is the P&L of the per-asset book the strategy holds, as opposed to
    the net-exposure pricing (``net_exposure x mean(asset returns)``) the
    framework uses by default. The first bar has no per-asset return and is
    therefore ``NaN`` (not 0), so the book-priced return series has the same
    index as the net-exposure one.

    Args:
        weights: per-asset target weights, or ``None``.
        market: the market model returned by :func:`build_market_model`.
        lag: execution lag in periods (1 + latency).
        fill_rate: fraction of each targeted change that is filled.

    Returns:
        A ``pd.Series`` of book returns, or ``None`` when there is no usable
        book.
    """
    held = held_book_weights(weights, market, lag=lag, fill_rate=fill_rate)
    if held is None:
        return None
    return book_return_from_held(held, market["close"])


def book_is_active(weights, market, lag: int = 1, fill_rate: float = 1.0) -> bool:
    """True when the book holds a non-zero position on at least one bar.

    A market-neutral book (equal long and short legs) is *not* flat: its
    gross exposure is positive even though its net exposure is zero. The
    net-exposure pricing convention cannot tell the two apart, so the
    book-aware "does this strategy take a position?" test must look at the
    gross book.

    Args:
        weights: per-asset target weights, or ``None``.
        market: the market model returned by :func:`build_market_model`.
        lag: execution lag in periods (1 + latency).
        fill_rate: fraction of each targeted change that is filled.

    Returns:
        ``True`` when the held book is non-empty on any bar.
    """
    held = held_book_weights(weights, market, lag=lag, fill_rate=fill_rate)
    if held is None:
        return False
    return bool((held.abs().sum(axis=1) > 0).any())


def compute_book_diagnostic(
    weights,
    market,
    positions,
    framework_returns,
    lag: int = 1,
    fill_rate: float = 1.0,
    pricing_mode: str = "net-exposure",
):
    """Measure the per-asset book against the framework's net-exposure pricing.

    The panel path prices a multi-asset portfolio as
    ``net_exposure x mean(asset returns)``: one scalar per period. A strategy
    that holds a long/short book cannot be represented that way:

    - a market-neutral book has net exposure 0 and is priced as if it were
      flat, so its P&L is reported as 0;
    - a book that rotates while its net exposure stays constant is charged
      no market impact, because the impact model only sees ``|d net
      exposure|``.

    This function *measures* that gap. It changes nothing: no return, cost,
    impact or capacity number is touched. The reported P&L convention stays
    the net-exposure one.

    The book held in a period is the target book lagged by the execution
    convention (``lag = 1 + latency`` periods) and scaled by the fill rate,
    exactly like the framework's position series, so the two are measured on
    the same bars.

    Args:
        weights: per-asset target weights (rows = dates, columns = symbols)
            as returned by :func:`strategy_target_weights`, or ``None``.
        market: the market model returned by :func:`build_market_model`.
        positions: the framework's position series *before* the return
            series is truncated, as computed by the calling path.
        framework_returns: the framework's reported per-period returns; its
            index defines the window the diagnostic is measured on. When
            ``None`` the whole sample is used and the return-gap keys are
            ``None`` (the exposure statistics are still measured).
        lag: execution lag in periods (1 + latency).
        fill_rate: fraction of each targeted change that is filled.
        pricing_mode: the panel pricing convention the run used
            (``"net-exposure"`` or ``"book"``). It selects which turnover the
            cost model actually charges, which the diagnostic reports as
            ``charged_turnover``.

    Returns:
        A dict of diagnostics, or ``None`` when there is no book to measure
        (single-asset path, a strategy that does not expose weights, or a
        window with no returns).
    """
    if weights is None or not isinstance(weights, pd.DataFrame) or weights.empty:
        return None
    if not market.get("is_panel"):
        return None

    close = market["close"]
    raw_returns = market["raw_returns"]
    if not isinstance(close, pd.DataFrame) or close.shape[1] == 0:
        return None

    # The strategy's book and the market model must describe the same
    # universe; otherwise the diagnostic would silently measure a flat book.
    if not set(weights.columns).intersection(set(close.columns)):
        return None

    has_returns = framework_returns is not None and len(framework_returns) > 0
    index = framework_returns.index if has_returns else close.index

    # The book actually held: the target book lagged by the execution
    # convention and scaled by the fill rate, exactly like the framework's
    # position series. The bars before the first executable one hold a flat
    # book.
    held_full = held_book_weights(weights, market, lag=lag, fill_rate=fill_rate)
    if held_full is None:
        return None
    held = held_full.reindex(index).fillna(0.0)

    # Per-asset returns over the framework's window. The first bar of the
    # close frame has no return and never appears in the framework's return
    # series, so the fill is a safety net only.
    asset_returns = close.pct_change().reindex(index).fillna(0.0)

    # The true book return: the weighted sum of the per-asset returns.
    book_return = (held * asset_returns).sum(axis=1)

    # The framework's own pricing, before costs: net exposure x the mean
    # asset return. Comparing it with the book return isolates the
    # exposure-convention gap from the transaction-cost gap.
    pos = positions.reindex(index)
    framework_pre_cost = pos * raw_returns.reindex(index)

    gross = held.abs().sum(axis=1)
    net = held.sum(axis=1)

    # Book turnover: the change in the held book. The pre-sample book is
    # flat, so the establishment of the book counts as a trade; the bars
    # before the first executable one contribute nothing.
    turnover_full = held_full.diff().abs().sum(axis=1).fillna(0.0)
    turnover = turnover_full.reindex(index).fillna(0.0)

    # What the cost/impact model actually charges: the change in the net
    # exposure. A book that rotates without changing its net exposure is
    # charged nothing.
    framework_turnover = positions.diff().abs().reindex(index).fillna(0.0)

    n_periods = int(len(index))
    if has_returns:
        framework_total = float((1 + framework_pre_cost).prod() - 1)
        book_total = float((1 + book_return).prod() - 1)
        after_costs = float((1 + framework_returns).prod() - 1)
        return_gap_bps = float((framework_pre_cost - book_return).mean() * 1e4)
        return_gap_total = float(framework_total - book_total)
    else:
        framework_total = None
        book_total = None
        after_costs = None
        return_gap_bps = None
        return_gap_total = None
    return {
        "n_periods": n_periods,
        "n_periods_with_book": int((gross > 0).sum()),
        "n_assets": int(close.shape[1]),
        # Mean gross exposure: sum |w_i| per period. Zero means the
        # strategy holds nothing, even when the framework reports a
        # position.
        "gross_book": float(gross.mean()),
        # Mean net exposure of the book, and the net exposure the framework
        # priced. They are equal by construction for a book built to match
        # the scalar signal (e.g. cross-sectional momentum); they differ
        # when the strategy's own book is more invested than the scalar
        # signal (e.g. dual momentum).
        "net_exposure": float(net.mean()),
        "framework_net_exposure": float(pos.mean()),
        # Mean turnover of the book against the turnover the cost model
        # charges.
        "gross_turnover": float(turnover.mean()),
        "framework_turnover": float(framework_turnover.mean()),
        # The turnover the cost model actually charges: the net exposure's
        # under the "net-exposure" convention, the book's own gross turnover
        # under the "book" convention (where the costs are charged on the
        # book). The two differ whenever the book rotates in place, which is
        # exactly the gap the "book" mode closes.
        "charged_turnover": (
            float(turnover.mean())
            if pricing_mode == "book"
            else float(framework_turnover.mean())
        ),
        # Which basis the costs were charged on, so a reader never has to
        # guess whether the reported numbers are net-exposure or book based.
        "cost_basis": pricing_mode,
        # Per-period gap between the framework's net-exposure pricing and
        # the true book return, in basis points, and the cumulative gap.
        "return_gap_bps": return_gap_bps,
        "return_gap_total": return_gap_total,
        "book_total_return": book_total,
        "framework_total_return": framework_total,
        "framework_total_return_after_costs": after_costs,
        # The cumulative return the run actually reported. Under the
        # "net-exposure" convention this is the framework's costed return;
        # under the "book" convention it is the book's costed return (the
        # costed number is the one a reader must use). The two keys above
        # are always *pre-cost*.
        "reported_total_return": after_costs,
    }


def aggregate_book_diagnostics(diagnostics):
    """Aggregate per-window book diagnostics into one summary record.

    The means are weighted by the number of periods in each window, so a
    long window counts more than a short one. The cumulative returns are
    compounded across the windows, which is the right aggregation for
    consecutive out-of-sample windows.

    Args:
        diagnostics: a list of per-window diagnostic dicts (as returned by
            :func:`compute_book_diagnostic`); ``None`` entries are ignored.

    Returns:
        A summary dict, or ``None`` when no window produced a diagnostic.
    """
    valid = [
        d for d in (diagnostics or [])
        if isinstance(d, dict) and d.get("n_periods")
    ]
    if not valid:
        return None

    n_periods = sum(int(d["n_periods"]) for d in valid)

    def _weighted_mean(key: str) -> float:
        total = 0.0
        for d in valid:
            value = d.get(key)
            if value is None:
                continue
            total += float(value) * int(d["n_periods"])
        return total / n_periods

    def _compound(key: str):
        product = 1.0
        for d in valid:
            value = d.get(key)
            if value is None:
                return None
            product *= 1.0 + float(value)
        return product - 1.0

    framework_total = _compound("framework_total_return")
    book_total = _compound("book_total_return")
    return_gap_total = (
        None
        if framework_total is None or book_total is None
        else float(framework_total - book_total)
    )
    # The cost basis is a property of the run, not of a window: report it
    # when every window agrees, and say "mixed" when they do not.
    _bases = {d.get("cost_basis") for d in valid if d.get("cost_basis")}
    cost_basis = _bases.pop() if len(_bases) == 1 else ("mixed" if _bases else None)

    return {
        "n_periods": n_periods,
        "n_periods_with_book": sum(int(d.get("n_periods_with_book") or 0) for d in valid),
        "n_assets": max(int(d.get("n_assets") or 0) for d in valid),
        "gross_book": _weighted_mean("gross_book"),
        "net_exposure": _weighted_mean("net_exposure"),
        "framework_net_exposure": _weighted_mean("framework_net_exposure"),
        "gross_turnover": _weighted_mean("gross_turnover"),
        "framework_turnover": _weighted_mean("framework_turnover"),
        "charged_turnover": _weighted_mean("charged_turnover"),
        "cost_basis": cost_basis,
        "return_gap_bps": _weighted_mean("return_gap_bps"),
        "return_gap_total": return_gap_total,
        "book_total_return": book_total,
        "framework_total_return": framework_total,
        "framework_total_return_after_costs": _compound("framework_total_return_after_costs"),
        "reported_total_return": _compound("reported_total_return"),
    }


def _capacity_trend_from_series(
    capacity_series: pd.Series,
    point_in_time_capacity: float,
):
    """Summarise the distribution of per-period capacity readings.

    The point-in-time ``estimated_capacity`` is a *single* reading: the ADV
    of the last bar of the window. A drying-up liquidity regime *inside* the
    window is invisible to it. This helper turns the per-period capacity
    series into the distribution that the single reading hides:

        min_capacity      worst liquidity point inside the window
        median_capacity   typical liquidity point inside the window
        max_capacity      best liquidity point inside the window
        last_capacity     the point-in-time reading (= estimated_capacity)

    The two ratios express how the extremes relate to the typical reading:

        min_to_median_ratio  worst / typical  (<= 1; a mid-window squeeze)
        last_to_median_ratio end-of-window / typical (<= 1 when liquidity
                              dried up towards the end of the window)

    Both ratios are relative to the median, so they are comparable across
    windows with different absolute capacity levels.
    """
    series = pd.Series(capacity_series, dtype=float)
    valid = series.replace([np.inf, -np.inf], np.nan).dropna()
    valid = valid[np.isfinite(valid)]

    last_capacity = float(point_in_time_capacity)

    if len(valid) == 0:
        return {
            "n_periods": 0,
            "min_capacity": None,
            "median_capacity": None,
            "max_capacity": None,
            "last_capacity": last_capacity,
            "min_to_median_ratio": None,
            "last_to_median_ratio": None,
        }

    min_capacity = float(valid.min())
    median_capacity = float(valid.median())
    max_capacity = float(valid.max())

    return {
        "n_periods": int(len(valid)),
        "min_capacity": min_capacity,
        "median_capacity": median_capacity,
        "max_capacity": max_capacity,
        "last_capacity": last_capacity,
        "min_to_median_ratio": (
            float(min_capacity / median_capacity) if median_capacity > 0 else None
        ),
        "last_to_median_ratio": (
            float(last_capacity / median_capacity) if median_capacity > 0 else None
        ),
    }


def book_capacity_estimate(
    held_book,
    close,
    volume,
    impact_coefficient: float,
    max_impact: float = 0.0005,
    adv_window: int = 20,
):
    """Capacity implied by the strategy's own rebalance pattern.

    The basket rule (:func:`walk_forward.estimate_capacity`) assumes an
    equal-weight basket: every constituent carries ``1 / n_assets`` of the
    notional and the *least liquid* constituent binds the portfolio
    capacity. A book whose weights differ trades a different amount in
    every constituent, so the basket rule mis-states the capacity of such a
    book: a book that trades *more* per period than ``1 / n_assets`` (a
    rotation through one name) supports less capital, and a book that
    trades *less* per period (a cross-sectional book that only rotates when
    its constituent set changes) supports more.

    This estimator uses the strategy's own trade sizes. The impact model
    charges asset ``i`` with::

        impact_i = (|dw_i| * equity / ADV_i) * impact_coefficient

    so the equity level at which that trade reaches the ``max_impact``
    threshold is::

        equity_i = max_impact * ADV_i / (|dw_i| * impact_coefficient)

    and the capacity of the book is the level at which *every* traded
    constituent stays inside the threshold::

        capacity = min_i ( max_impact * ADV_i / (|dw_i| * impact_coefficient) )

    The two rules agree exactly for a book that rebalances ``1 / n_assets``
    per constituent every period (the basket rule is that special case);
    they differ for every other book.

    The estimate is reported per period (each period's own trade sizes
    against that period's own ADV), so a liquidity squeeze inside the
    window is visible instead of being hidden behind a single reading:

        estimated_capacity  the point-in-time reading: the capacity of the
                            most recent bar on which the book actually
                            traded. Bars on which the book did not trade
                            impose no constraint, so the reading is the
                            last *defined* one.
        capacity_trend      the distribution of the per-period readings
                            (see :func:`_capacity_trend_from_series`).
        capacity_series     the per-period readings themselves, so a
                            caller can merge the series of several windows
                            without recomputing them.

    Args:
        held_book: held per-asset weights (rows = dates, columns = symbols).
        close: close prices -- ``pd.DataFrame`` with one column per asset.
        volume: volumes, same shape as ``close``, or ``None``.
        impact_coefficient: linear impact coefficient; ``0`` disables impact.
        max_impact: maximum acceptable market impact per trade (default
            0.0005 = 5 bps), the same threshold the basket rule uses.
        adv_window: rolling window (in periods) for the ADV.

    Returns:
        A dict with the keys ``estimated_capacity``, ``capacity_trend``,
        ``capacity_series``, ``n_assets``, ``binding_asset``,
        ``n_periods_measured``, ``point_in_time_bar``, ``unconstrained``,
        ``estimable``, ``impact_coefficient``, ``max_impact`` and
        ``adv_window``. ``estimated_capacity`` is ``None`` when impact is
        disabled, when the book never traded, or when ADV is not estimable.
    """
    result = {
        "estimated_capacity": None,
        "capacity_trend": None,
        "capacity_series": None,
        "n_assets": None,
        "binding_asset": None,
        "n_periods_measured": 0,
        "point_in_time_bar": None,
        "unconstrained": False,
        "estimable": False,
        "impact_coefficient": float(impact_coefficient),
        "max_impact": float(max_impact),
        "adv_window": int(adv_window),
    }

    if impact_coefficient <= 0:
        result["unconstrained"] = True
        return result
    if held_book is None or not isinstance(held_book, pd.DataFrame) or held_book.empty:
        return result
    if not isinstance(close, pd.DataFrame) or not isinstance(volume, pd.DataFrame):
        return result
    if close.shape[1] == 0 or volume.shape[1] == 0:
        return result

    # Only the constituents the book, the prices and the volumes all share
    # can be priced.
    columns = [
        c for c in held_book.columns
        if c in close.columns and c in volume.columns
    ]
    if not columns:
        return result
    held = held_book.reindex(columns=columns)
    prices = close.reindex(columns=columns)
    volumes = volume.reindex(columns=columns)

    # Average Daily Volume in shares (rolling), then in notional -- the same
    # convention the impact model uses.
    adv_shares = volumes.rolling(window=adv_window, min_periods=1).mean()
    adv_notional = adv_shares * prices

    # The traded weight per asset per period. The first bar of the book has
    # no change (nothing was held before it), so it is not a trade.
    traded_weight = held.diff().abs()

    # The per-asset capacity at the impact threshold. A constituent that did
    # not trade (|dw_i| = 0) imposes no constraint, so it is excluded (NaN)
    # and skipped by the per-period minimum.
    traded = traded_weight.replace(0.0, np.nan)
    per_asset_capacity = (
        (max_impact * adv_notional) / (traded * float(impact_coefficient))
    )
    per_asset_capacity = per_asset_capacity.where(
        np.isfinite(per_asset_capacity) & (per_asset_capacity > 0)
    )

    capacity_series = per_asset_capacity.min(axis=1, skipna=True)
    valid = capacity_series.replace([np.inf, -np.inf], np.nan).dropna()
    valid = valid[np.isfinite(valid)]
    if len(valid) == 0:
        # The book never traded inside the window: it imposes no capacity
        # constraint of its own.
        return result

    result["estimable"] = True
    result["n_assets"] = int(len(columns))
    result["n_periods_measured"] = int(len(valid))
    result["capacity_series"] = capacity_series

    # The point-in-time reading: the capacity of the most recent bar on
    # which the book actually traded.
    point_in_time = float(valid.iloc[-1])
    result["estimated_capacity"] = point_in_time
    point_in_time_bar = valid.index[-1]
    result["point_in_time_bar"] = str(pd.Timestamp(point_in_time_bar).date())
    binding_row = per_asset_capacity.loc[point_in_time_bar]
    if isinstance(binding_row, pd.DataFrame):
        # A duplicated timestamp would make .loc return a frame.
        binding_row = binding_row.iloc[-1]
    binding_row = binding_row.dropna()
    if len(binding_row):
        result["binding_asset"] = str(binding_row.idxmin())
    result["capacity_trend"] = _capacity_trend_from_series(
        capacity_series, point_in_time
    )
    return result


def _annualization_factor(index: pd.Index) -> float:
    """Estimate the number of periods per year from a DatetimeIndex."""
    if not isinstance(index, pd.DatetimeIndex):
        return 252  # Default trading days
    try:
        freq = pd.infer_freq(index)
        if freq is None:
            return 252
        # Normalize to the lowercase base alias (pandas 3.x returns e.g.
        # "h", "min", "ms", "ME", "QE-DEC"). Match on the full base alias
        # rather than freq[0]: "min" (minute), "M"/"ME" (month), and "ms"
        # (millisecond) all start with "m", so first-char matching collides.
        base = freq.lower().split("-")[0]
        freq_map = {
            "b": 252,
            "d": 365,
            "w": 52,
            "me": 12,
            "ms": 12,
            "qe": 4,
            "ye": 1,
            "h": int(252 * 6.5),
            "min": int(252 * 6.5 * 60),
        }
        return freq_map.get(base, 252)
    except Exception:
        return 252
