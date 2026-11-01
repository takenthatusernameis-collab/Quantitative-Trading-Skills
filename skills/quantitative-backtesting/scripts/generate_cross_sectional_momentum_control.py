#!/usr/bin/env python3
"""Deterministic synthetic fixture for the cross-sectional momentum hypothesis.

WHAT THIS IS
    A check on the *test machinery*, not on any strategy, security or market.

    The worked example ``examples/cross_sectional_momentum_hypothesis.py`` tests
    a bounded, pre-registered hypothesis: a cross-sectional momentum strategy
    on a multi-asset panel produces positive out-of-sample risk-adjusted
    returns net of trading costs on a held-out test split. The example runs on
    committed real-market fixtures (MSFT/GOOGL, AAPL/GOOGL, AAPL/MSFT, and the
    AAPL/MSFT/GOOGL triple) and reports a verdict for each. Every shipped
    verdict is NOT SUPPORTED.

    A verdict that can only ever be NOT SUPPORTED would be no evidence of a
    test at all. This module supplies the missing half: a synthetic panel with
    a **known, injected cross-sectional momentum effect** whose construction is
    written out below and can be recomputed by anyone. Running the example's
    own criteria machinery against it must return SUPPORTED; running the
    identical construction with the effect removed must return NOT SUPPORTED.

    Nothing here is evidence about a real security. The series are produced by
    the formulas below, which are written out in full so anyone can recompute
    them. The files are labelled synthetic and carry no security identifier.

THE CONSTRUCTION
    A panel of N assets, each a random walk with a per-asset constant log
    drift:

        * The assets are split into two halves: the first half carry
          ``+DRIFT`` per bar, the second half carry ``-DRIFT`` per bar.
          This is the injected effect: a persistent cross-sectional spread
          between the two halves that cross-sectional momentum can rank and
          trade.
        * Every bar adds an independent ``N(0, VOLATILITY)`` log return on
          top of the drift, drawn from a per-asset stream so the noise is
          independent across assets.
        * The close is ``INITIAL_PRICE * exp(cumsum(log returns))``; open,
          high and low are built from it so the OHLC relationships hold.

    A cross-sectional momentum rule that goes long the top-ranked half and
    short the bottom-ranked half captures the persistent spread; a
    buy-and-hold on any single asset pays for the full random-walk noise plus
    its drift. That is the edge the control injects.

    THE NO-EFFECT CONTROL (``inject_effect=False``)
    The SAME construction with every asset's drift removed: the identical
    noise draws, the identical OHLC micro-structure, and N independent
    driftless random walks instead of a ranked panel. The two fixtures
    therefore differ by exactly one thing -- the injected cross-sectional
    spread -- which is what makes the pair a control rather than two
    unrelated samples.

WHY THE EFFECT IS THIS LARGE
    The example's criteria are evaluated on the held-out test window, a fifth
    of the sample. A cross-sectional momentum rule on a persistent drift
    spread earns roughly the drift per bar over the whole window, so the
    effect is large relative to noise and clears the criteria comfortably.
    The magnitude is a *test-machinery* choice, not a claim about what a
    strategy can earn: it is set where the framework's own reported minimum
    detectable effect can be cleared, so the control measures whether the
    machinery can say yes -- not whether any plausible strategy could.

FILE NAMES
    The example resolves its data file relative to the directory it is given,
    so a fixture directory must contain a single multi-symbol CSV with a
    ``symbol`` column. The names are dictated by the example; the directory
    is what identifies the fixture as synthetic.

    * ``cs_momentum_effect_ohlcv.csv`` -- the effect panel (ranked drift).
    * ``cs_momentum_no_effect_ohlcv.csv`` -- the no-effect panel (driftless).

Run it directly to materialize the fixtures for inspection:
    python3 skills/quantitative-backtesting/scripts/generate_cross_sectional_momentum_control.py \
        --out /tmp/cs_momentum_control
"""