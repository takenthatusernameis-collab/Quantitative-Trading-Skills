#!/usr/bin/env python3
"""
Shared utility functions for the quantitative backtesting toolkit.
"""

import numpy as np
import pandas as pd


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


def compute_book_diagnostic(
    weights,
    market,
    positions,
    framework_returns,
    lag: int = 1,
    fill_rate: float = 1.0,
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

    # Target book on the market model's grid, then the book actually held:
    # lagged by the execution convention and scaled by the fill rate, exactly
    # like the framework's position series. The bars before the first
    # executable one hold a flat book.
    target = weights.reindex(columns=close.columns).reindex(close.index).fillna(0.0)
    held_full = (target.shift(lag) * fill_rate).fillna(0.0)
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
        # Per-period gap between the framework's net-exposure pricing and
        # the true book return, in basis points, and the cumulative gap.
        "return_gap_bps": return_gap_bps,
        "return_gap_total": return_gap_total,
        "book_total_return": book_total,
        "framework_total_return": framework_total,
        "framework_total_return_after_costs": after_costs,
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

    return {
        "n_periods": n_periods,
        "n_periods_with_book": sum(int(d.get("n_periods_with_book") or 0) for d in valid),
        "n_assets": max(int(d.get("n_assets") or 0) for d in valid),
        "gross_book": _weighted_mean("gross_book"),
        "net_exposure": _weighted_mean("net_exposure"),
        "framework_net_exposure": _weighted_mean("framework_net_exposure"),
        "gross_turnover": _weighted_mean("gross_turnover"),
        "framework_turnover": _weighted_mean("framework_turnover"),
        "return_gap_bps": _weighted_mean("return_gap_bps"),
        "return_gap_total": return_gap_total,
        "book_total_return": book_total,
        "framework_total_return": framework_total,
        "framework_total_return_after_costs": _compound("framework_total_return_after_costs"),
    }


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
