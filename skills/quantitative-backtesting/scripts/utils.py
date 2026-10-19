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
