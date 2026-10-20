#!/usr/bin/env python3
"""Deterministic synthetic fixture for the falsifiable-hypothesis POSITIVE CONTROL.

WHAT THIS IS
    A check on the *test machinery*, not on any strategy, security or market.

    The worked example ``examples/falsifiable_hypothesis_example.py`` reports a
    verdict ("SUPPORTED" / "NOT SUPPORTED") from five pre-registered criteria
    and, beside it, the *resolution* of the significance tests: the smallest
    effect each test could have confirmed at the sample size available. On
    every shipped sample those thresholds sit beyond the plausibility bound,
    so the shipped verdicts are, in substance, statements about the size of
    the sample. That shows the machinery can only fail. It does not show the
    machinery *can* say yes.

    This module supplies the data for the missing half: a synthetic series
    with a **known, injected effect** whose construction is written out below
    and can be recomputed by anyone. Running the example's own criteria
    machinery against it must return "SUPPORTED"; running the identical
    construction with the effect removed must return "NOT SUPPORTED".

    Nothing here is evidence about a real security. The series is produced by
    the formula below, it is not a quotation of anything, and the numbers the
    example prints on it are properties of a formula and of the test
    machinery, nothing more.

THE CONSTRUCTION
    A single synthetic price series, built as an alternating sequence of
    trend regimes:

        * ``CONTROL_REGIME_BARS`` (126) bars per regime -- about six months,
          which is also the length of the walk-forward training window the
          example uses, so every validation window contains the same mix of
          one rising and one falling regime;
        * regime ``k`` has a constant per-bar log drift of
          ``+CONTROL_DRIFT`` when ``k`` is even and ``-CONTROL_DRIFT`` when
          ``k`` is odd -- the injected effect, a rising and a falling leg in
          alternation;
        * every bar adds an independent ``N(0, CONTROL_VOLATILITY)`` log
          return on top of the regime drift;
        * the close is ``100 * exp(cumsum(log returns))``; open/high/low are
          built from it so the OHLC relationships hold.

    A crossover captures the rising legs and sits out the falling ones, while
    buy-and-hold pays for both. That is the edge the control injects.

    The no-effect control is the SAME construction with the regime drift
    removed (``inject_effect=False``): the identical noise draws, the
    identical OHLC micro-structure, and a random walk instead of a trending
    path. The two fixtures therefore differ by exactly one thing -- the
    injected effect -- which is what makes the pair a control rather than two
    unrelated samples.

WHY THE EFFECT IS THIS LARGE
    The example's criterion 2 is a *deflated* Sharpe test, and the deflation
    benchmark (the expected maximum Sharpe over the parameter grid) is
    estimated from the dispersion of the trial Sharpes. That dispersion is
    not small, so the deflated test needs an effect well above an ordinary
    strategy's to be confirmed at all. The control's effect size is therefore
    a *test-machinery* choice, not a claim about what a strategy can earn:
    it is set where the framework's own reported minimum detectable effect
    can be cleared, so the control measures whether the machinery can say yes
    -- not whether any plausible strategy could.

FILE NAMES
    The example resolves its benchmark set from ``BENCHMARK_FILES`` relative
    to the directory of the data file it is given, so a fixture directory
    must contain files named ``sample_ohlcv.csv`` (the strategy's own series,
    which is also the primary benchmark) and ``sample_benchmark.csv`` (the
    alternative benchmark). The names are dictated by the example; the
    directory is what identifies the fixture as synthetic.

Run it directly to materialize the fixture for inspection:

    python3 skills/quantitative-backtesting/scripts/generate_positive_control_data.py \
        --out /tmp/positive_control
"""

import argparse
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Purpose label. Repeated in the console banner and in the test module's
# docstring so the fixture can never be read as market evidence.
# ---------------------------------------------------------------------------
FIXTURE_PURPOSE = (
    "TEST-MACHINERY CHECK ON SYNTHETIC DATA: a series produced by a known "
    "formula, used to check that the falsifiable-hypothesis machinery can "
    "return SUPPORTED. It is not evidence about any security or market."
)

# ---------------------------------------------------------------------------
# Construction parameters (the fixture's definition -- change them and the
# control means something else, so they are stated in one place).
# ---------------------------------------------------------------------------
CONTROL_PERIODS = 5040          # business days (~20 years)
CONTROL_REGIME_BARS = 126       # bars per trend regime (~6 months)
CONTROL_DRIFT = 0.004           # injected per-bar log drift (+/-) per regime
CONTROL_VOLATILITY = 0.01       # per-bar idiosyncratic log-return sd
CONTROL_STRATEGY_SEED = 7
CONTROL_BENCHMARK_SEED = 1007
CONTROL_START_DATE = "2000-01-03"
CONTROL_INITIAL_PRICE = 100.0

# The file names the example's BENCHMARK_FILES list expects inside a fixture
# directory.
CONTROL_STRATEGY_FILENAME = "sample_ohlcv.csv"
CONTROL_BENCHMARK_FILENAME = "sample_benchmark.csv"


def generate_control_series(
    periods: int = CONTROL_PERIODS,
    regime_bars: int = CONTROL_REGIME_BARS,
    drift: float = CONTROL_DRIFT,
    volatility: float = CONTROL_VOLATILITY,
    seed: int = CONTROL_STRATEGY_SEED,
    inject_effect: bool = True,
    start: str = CONTROL_START_DATE,
    initial_price: float = CONTROL_INITIAL_PRICE,
) -> pd.DataFrame:
    """Build the synthetic control series.

    Args:
        periods: Number of business days to generate.
        regime_bars: Bars per trend regime. Regimes alternate rising /
            falling; the regime boundary is aligned to the start of the
            series, so the first regime is a rising one.
        drift: Per-bar log drift applied inside a regime (the injected
            effect). Ignored when ``inject_effect`` is False, in which case
            the series is a driftless random walk.
        volatility: Per-bar standard deviation of the idiosyncratic log
            return.
        seed: Seed for the return draws. The no-effect control uses the same
            seed, so the two series carry the *same* noise and differ only
            by the injected drift.
        inject_effect: When False the regime drift is removed and the series
            becomes a driftless random walk built from the same draws.
        start: First date of the index.
        initial_price: Price before the first bar.

    Returns:
        A DataFrame with ``date, open, high, low, close, volume`` columns.
    """
    if periods < 2:
        raise ValueError("periods must be at least 2")
    if regime_bars < 2:
        raise ValueError("regime_bars must be at least 2")
    if volatility <= 0:
        raise ValueError("volatility must be positive")

    dates = pd.date_range(start, periods=periods, freq="B")

    # The effect: alternating rising and falling regimes. The regime index is
    # derived from the bar index, so the construction is deterministic and
    # the boundaries are aligned to the start of the series.
    n_regimes = int(np.ceil(periods / regime_bars))
    regime_sign = np.where(np.arange(n_regimes) % 2 == 0, 1.0, -1.0)
    regime_drift = np.repeat(regime_sign * float(drift), regime_bars)[:periods]
    if not inject_effect:
        regime_drift = np.zeros(periods, dtype=float)

    # The noise is drawn from a dedicated stream so that the OHLC
    # micro-structure below cannot change the return path.
    rng = np.random.default_rng(seed)
    log_returns = regime_drift + rng.normal(0.0, float(volatility), periods)

    close = float(initial_price) * np.exp(np.cumsum(log_returns))
    open_ = np.concatenate([[float(initial_price)], close[:-1]])

    rng_micro = np.random.default_rng(seed + 1)
    high = np.maximum(open_, close) * rng_micro.uniform(1.001, 1.010, periods)
    low = np.minimum(open_, close) * rng_micro.uniform(0.990, 0.999, periods)
    volume = rng_micro.integers(1_000_000, 10_000_000, periods)

    return pd.DataFrame({
        "date": dates,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def write_control_fixture(
    directory,
    strategy_seed: int = CONTROL_STRATEGY_SEED,
    benchmark_seed: int = CONTROL_BENCHMARK_SEED,
    inject_effect: bool = True,
    **series_kwargs,
) -> Dict[str, Path]:
    """Write the control fixture into ``directory``.

    The directory receives the two files the example's ``BENCHMARK_FILES``
    list resolves relative to the strategy data file:

    * ``sample_ohlcv.csv`` -- the strategy's own series, which is also the
      primary (buy-and-hold) benchmark;
    * ``sample_benchmark.csv`` -- an alternative benchmark drawn from the
      same construction with a different seed.

    Args:
        directory: Destination directory (created if missing).
        strategy_seed: Seed of the strategy series.
        benchmark_seed: Seed of the alternative benchmark series.
        inject_effect: When False the *effect* is removed from both files,
            which is the no-effect control.
        **series_kwargs: Forwarded to :func:`generate_control_series`.

    Returns:
        A dict with the written paths keyed ``"strategy"`` and ``"benchmark"``.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    strategy = generate_control_series(
        seed=strategy_seed, inject_effect=inject_effect, **series_kwargs
    )
    benchmark = generate_control_series(
        seed=benchmark_seed, inject_effect=inject_effect, **series_kwargs
    )

    strategy_path = directory / CONTROL_STRATEGY_FILENAME
    benchmark_path = directory / CONTROL_BENCHMARK_FILENAME
    strategy.to_csv(strategy_path, index=False)
    benchmark.to_csv(benchmark_path, index=False)
    return {"strategy": strategy_path, "benchmark": benchmark_path}


def describe_construction() -> Dict[str, object]:
    """The fixture's parameters, for documentation and for tests that assert
    the control was built from the documented construction."""
    return {
        "purpose": FIXTURE_PURPOSE,
        "periods": CONTROL_PERIODS,
        "regime_bars": CONTROL_REGIME_BARS,
        "drift": CONTROL_DRIFT,
        "volatility": CONTROL_VOLATILITY,
        "strategy_seed": CONTROL_STRATEGY_SEED,
        "benchmark_seed": CONTROL_BENCHMARK_SEED,
        "start_date": CONTROL_START_DATE,
        "initial_price": CONTROL_INITIAL_PRICE,
    }


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize the synthetic positive-control fixture. "
            + FIXTURE_PURPOSE
        )
    )
    parser.add_argument(
        "--out", required=True,
        help="Directory to write the fixture into (created if missing).",
    )
    parser.add_argument(
        "--no-effect", action="store_true",
        help="Write the no-effect control (the same construction with the "
             "injected drift removed) instead of the effect series.",
    )
    args = parser.parse_args(argv)

    paths = write_control_fixture(args.out, inject_effect=not args.no_effect)
    print(FIXTURE_PURPOSE)
    print(f"Construction: {describe_construction()}")
    for key, path in paths.items():
        print(f"  {key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
