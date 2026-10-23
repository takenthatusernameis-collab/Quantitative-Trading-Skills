#!/usr/bin/env python3
"""Deterministic synthetic fixture: a COINTEGRATED pair and a no-effect pair.

WHAT THIS IS
    A check on the *test machinery*, not on any strategy, security or market.

    The worked example ``examples/zscore_mean_reversion_hypothesis.py`` tests a
    bounded, pre-registered hypothesis: a Z-Score mean-reversion (pairs)
    strategy produces positive out-of-sample risk-adjusted returns net of
    trading costs on a held-out test split. On a synthetic pair whose spread
    is genuinely stationary (cointegrated) the machinery should be able to say
    SUPPORTED; on a no-effect pair (two independent random walks, no
    cointegration) the same machinery should say NOT SUPPORTED.

    Nothing here is evidence about a real security. The series are produced by
    the formulas below, which are written out in full so anyone can recompute
    them. The files are labelled synthetic and carry no security identifier.

THE CONSTRUCTION (cointegrated pair, ``inject_effect=True``)
    Two assets that are each a random walk (individually non-stationary) but
    whose log-price spread is stationary and mean-reverting -- the textbook
    definition of a cointegrated pair:

        * A common trend ``T`` is a random walk: ``T_t = T_{t-1} + trend_t``
          with ``trend_t ~ N(0, TREND_VOL)``.
        * A stationary spread ``S`` is an AR(1): ``S_t = RHO * S_{t-1} +
          spread_t`` with ``spread_t ~ N(0, SPREAD_SIGMA)`` and |RHO| < 1,
          so the spread reverts to zero.
        * ``log(P1_t) = T_t + 0.5 * S_t`` and ``log(P2_t) = T_t - 0.5 * S_t``,
          hence ``log(P1) - log(P2) = S`` (stationary): the two assets
          cointegrate with hedge ratio 1.
        * Each asset alone is a random walk (non-stationary); only the spread
          is mean-reverting. That is the edge the Z-Score strategy can harvest.

    A Z-Score mean-reversion strategy that goes long the spread when its
    z-score is below ``-entry_z`` and short when above ``+entry_z`` (exiting
    near zero) captures this mean reversion; buy-and-hold on either leg pays
    for the full random-walk trend plus the spread.

THE NO-EFFECT CONTROL (``inject_effect=False``)
    Two *independent* random walks with no shared trend and no stationary
    spread:

        * ``log(P1_t)`` and ``log(P2_t)`` are independent random walks.
        * The spread ``log(P1) - log(P2)`` is itself a random walk
          (non-stationary): there is no cointegration and no mean-reverting
          edge to harvest. A Z-Score mean-reversion rule trading this spread
          is trading noise and should not be profitable net of costs.

    The control is the same OHLC micro-structure and the same per-bar draw
    count as the effect pair; the difference is the absence of the common
    trend and the stationary spread.

FILE NAMES
    The example reads a single multi-symbol CSV (a ``symbol``/``ticker``
    column) via ``run_backtest.py --multi-symbol``. Each fixture file
    therefore contains exactly two symbols (``ASSET_A``, ``ASSET_B``) with
    columns ``date, open, high, low, close, volume, symbol``.

    * ``sample_pair_ohlcv.csv`` -- cointegrated pair (the effect).
    * ``sample_pair_no_effect_ohlcv.csv`` -- two independent random walks.

Run it directly to materialize the fixtures for inspection:

    python3 skills/quantitative-backtesting/scripts/generate_synthetic_pair.py \
        --out skills/quantitative-backtesting/assets/example_data
"""

import argparse
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Purpose label. Repeated in the console banner so the fixture can never be
# read as market evidence.
# ---------------------------------------------------------------------------
FIXTURE_PURPOSE = (
    "TEST-MACHINERY CHECK ON SYNTHETIC DATA: two price series produced by a "
    "known formula (a cointegrated pair and a no-effect pair), used to check "
    "that the Z-Score mean-reversion hypothesis machinery can return "
    "SUPPORTED on a genuine spread and NOT SUPPORTED on noise. It is not "
    "evidence about any security or market."
)

# ---------------------------------------------------------------------------
# Construction parameters (the fixtures' definition -- change them and the
# control means something else, so they are stated in one place).
# ---------------------------------------------------------------------------
PAIR_PERIODS = 1000            # business days (~4 years)
PAIR_START_DATE = "2015-01-01"
PAIR_INITIAL_PRICE = 100.0
TREND_VOL = 0.01               # per-bar vol of the common random-walk trend
SPREAD_RHO = 0.80              # AR(1) persistence of the stationary spread (faster mean reversion)
SPREAD_SIGMA = 0.006           # per-bar innovation vol of the spread
SPREAD_MEAN = 0.0              # long-run mean of the spread
TREND_SEED = 11
SPREAD_SEED = 22
NO_EFFECT_SEED_1 = 1011
NO_EFFECT_SEED_2 = 2022

# The two symbols the pair fixtures contain (exactly two, as the pairs
# strategy requires a two-asset panel).
SYMBOL_A = "ASSET_A"
SYMBOL_B = "ASSET_B"

# The file names the hypothesis example resolves relative to its data file.
PAIR_STRATEGY_FILENAME = "sample_pair_ohlcv.csv"
PAIR_NO_EFFECT_FILENAME = "sample_pair_no_effect_ohlcv.csv"


def _ohlcv_from_close(close: np.ndarray, dates, volume_seed: int,
                      initial_price: float) -> pd.DataFrame:
    """Build OHLCV frames from a close path so OHLC relationships hold."""
    open_ = np.concatenate([[float(initial_price)], close[:-1]])
    rng_micro = np.random.default_rng(volume_seed + 1)
    high = np.maximum(open_, close) * rng_micro.uniform(1.001, 1.010, len(close))
    low = np.minimum(open_, close) * rng_micro.uniform(0.990, 0.999, len(close))
    volume = rng_micro.integers(1_000_000, 10_000_000, len(close))
    return pd.DataFrame({
        "date": dates,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def generate_pair_series(
    periods: int = PAIR_PERIODS,
    start: str = PAIR_START_DATE,
    initial_price: float = PAIR_INITIAL_PRICE,
    trend_vol: float = TREND_VOL,
    spread_rho: float = SPREAD_RHO,
    spread_sigma: float = SPREAD_SIGMA,
    spread_mean: float = SPREAD_MEAN,
    trend_seed: int = TREND_SEED,
    spread_seed: int = SPREAD_SEED,
    inject_effect: bool = True,
) -> Dict[str, pd.DataFrame]:
    """Build a two-asset pair.

    Args:
        periods: Number of business days to generate.
        start: First date of the index.
        initial_price: Price before the first bar.
        trend_vol: Per-bar volatility of the common random-walk trend.
        spread_rho: AR(1) persistence of the stationary spread (|rho| < 1).
        spread_sigma: Per-bar volatility of the spread innovation.
        spread_mean: Long-run mean of the stationary spread.
        trend_seed: Seed for the common trend draws.
        spread_seed: Seed for the spread innovation draws.
        inject_effect: When True the pair is cointegrated (common trend +
            stationary spread). When False the two assets are independent
            random walks (no cointegration, no mean-reverting edge).

    Returns:
        A dict keyed by symbol (``ASSET_A``, ``ASSET_B``), each value a
        DataFrame with ``date, open, high, low, close, volume`` columns.
    """
    if periods < 3:
        raise ValueError("periods must be at least 3")
    if not 0.0 < spread_rho < 1.0:
        raise ValueError("spread_rho must be in (0, 1) for a stationary spread")
    if trend_vol <= 0:
        raise ValueError("trend_vol must be positive")
    if spread_sigma <= 0:
        raise ValueError("spread_sigma must be positive")

    dates = pd.date_range(start, periods=periods, freq="B")

    rng_trend = np.random.default_rng(trend_seed)
    trend_innov = rng_trend.normal(0.0, float(trend_vol), periods)
    trend = np.cumsum(trend_innov)

    if inject_effect:
        # Stationary AR(1) spread reverting to spread_mean.
        rng_spread = np.random.default_rng(spread_seed)
        spread = np.empty(periods, dtype=float)
        spread[0] = spread_mean
        for t in range(1, periods):
            spread[t] = (spread_mean
                         + float(spread_rho) * (spread[t - 1] - spread_mean)
                         + rng_spread.normal(0.0, float(spread_sigma)))
        log_p1 = trend + 0.5 * spread
        log_p2 = trend - 0.5 * spread
    else:
        # No effect: two independent random walks, no shared trend, no
        # stationary spread. The spread log(P1) - log(P2) is itself a random
        # walk (non-stationary), so there is no cointegration edge.
        rng_walk_1 = np.random.default_rng(NO_EFFECT_SEED_1)
        rng_walk_2 = np.random.default_rng(NO_EFFECT_SEED_2)
        log_p1 = np.cumsum(rng_walk_1.normal(0.0, float(trend_vol), periods))
        log_p2 = np.cumsum(rng_walk_2.normal(0.0, float(trend_vol), periods))

    close_1 = float(initial_price) * np.exp(log_p1)
    close_2 = float(initial_price) * np.exp(log_p2)

    return {
        SYMBOL_A: _ohlcv_from_close(close_1, dates, trend_seed, initial_price),
        SYMBOL_B: _ohlcv_from_close(close_2, dates, spread_seed, initial_price),
    }


def write_pair_fixtures(directory: Path, inject_effect: bool = True,
                        **series_kwargs) -> Dict[str, Path]:
    """Write a two-symbol multi-symbol fixture CSV into ``directory``.

    The file contains exactly two symbols (``ASSET_A``, ``ASSET_B``) with a
    ``symbol`` column, loadable by ``run_backtest.py --multi-symbol``.

    Args:
        directory: Destination directory (created if missing).
        inject_effect: When True the pair is cointegrated; when False the two
            assets are independent random walks (the no-effect control).
        **series_kwargs: Forwarded to :func:`generate_pair_series`.

    Returns:
        A dict keyed by fixture role (``"pair"`` or ``"no_effect_pair"``)
        with the written path.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    frames = generate_pair_series(inject_effect=inject_effect, **series_kwargs)

    rows = []
    for symbol, df in frames.items():
        df = df.copy()
        df["symbol"] = symbol
        rows.append(df)
    panel = pd.concat(rows, ignore_index=True)
    # Deterministic ordering: date then symbol.
    panel = panel.sort_values(["date", "symbol"]).reset_index(drop=True)

    role = "pair" if inject_effect else "no_effect_pair"
    filename = (PAIR_STRATEGY_FILENAME if inject_effect
                else PAIR_NO_EFFECT_FILENAME)
    path = directory / filename
    panel.to_csv(path, index=False)
    return {role: path}


def describe_construction() -> Dict[str, object]:
    """The fixture parameters, for documentation and for tests that assert the
    fixtures were built from the documented construction."""
    return {
        "purpose": FIXTURE_PURPOSE,
        "periods": PAIR_PERIODS,
        "start_date": PAIR_START_DATE,
        "initial_price": PAIR_INITIAL_PRICE,
        "trend_vol": TREND_VOL,
        "spread_rho": SPREAD_RHO,
        "spread_sigma": SPREAD_SIGMA,
        "spread_mean": SPREAD_MEAN,
        "trend_seed": TREND_SEED,
        "spread_seed": SPREAD_SEED,
        "no_effect_seed_1": NO_EFFECT_SEED_1,
        "no_effect_seed_2": NO_EFFECT_SEED_2,
        "symbols": [SYMBOL_A, SYMBOL_B],
    }


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize the synthetic pair fixtures. " + FIXTURE_PURPOSE
        )
    )
    parser.add_argument(
        "--out", required=True,
        help="Directory to write the fixture CSVs into (created if missing).",
    )
    parser.add_argument(
        "--no-effect", action="store_true",
        help="Write the no-effect control (two independent random walks, no "
             "cointegration) instead of the cointegrated pair.",
    )
    args = parser.parse_args(argv)

    paths = write_pair_fixtures(Path(args.out), inject_effect=not args.no_effect)
    print(FIXTURE_PURPOSE)
    print(f"Construction: {describe_construction()}")
    for key, path in paths.items():
        print(f"  {key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
