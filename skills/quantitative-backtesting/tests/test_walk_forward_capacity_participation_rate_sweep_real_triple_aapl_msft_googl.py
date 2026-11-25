#!/usr/bin/env python3
"""Participation-rate capacity cap swept on the committed three-asset panel
(AAPL / MSFT / GOOGL).

The market-impact capacity model (``walk_forward.estimate_capacity``) accepts an
optional ``max_participation_rate`` that hard-caps per-trade notional at
``max_participation_rate * ADV_notional`` (scaled by ``n_assets`` for a panel),
independent of the impact model. The reported capacity is the minimum of the
impact-based capacity and the participation-based capacity.

That cap is only unit-tested on synthetic frames
(``test_run_backtest.py`` / ``test_walk_forward.py``); it has never been swept
on the real committed panel. This test closes that execution-realism gap:

- the participation cap binds (is the minimum) at low participation rates and
  goes slack at high rates, with a real crossover in between;
- reported capacity is non-decreasing in the participation rate;
- the reported ``participation_capacity`` equals
  ``n_assets * max_participation_rate * binding_adv_notional``;
- the binding constituent is the least-liquid asset (min last-bar ADV notional);
- with impact disabled the cap is ignored (capacity unconstrained / None).

No profitability or capacity claim is made; capacity is an execution-side
control. Offline, committed fixtures only
(assets/example_data/real_market_data/{AAPL,MSFT,GOOGL}.csv). No live network.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import _dict_to_multiindex, estimate_capacity  # noqa: E402

ASSETS_DIR = SKILLS_DIR / "assets" / "example_data" / "real_market_data"
SYMBOLS = ("AAPL", "MSFT", "GOOGL")

# Fixed impact coefficient (matches the synthetic panel unit test) and the
# default target impact / ADV window, so the only varying input is the
# participation-rate cap.
IMPACT_COEFFICIENT = 0.5
MAX_IMPACT = 0.0005
ADV_WINDOW = 20

# Ascending participation-rate levels (fraction of ADV). The low end binds the
# impact-based capacity; the high end is slack.
PARTICIPATION_LEVELS = (0.0001, 0.0002, 0.0005, 0.001, 0.005, 0.01, 0.05)


def _build_real_triple_panel() -> pd.DataFrame:
    for name in SYMBOLS:
        assert (ASSETS_DIR / f"{name}.csv").exists(), f"missing fixture {name}.csv"
    data = {}
    for symbol in SYMBOLS:
        df = pd.read_csv(ASSETS_DIR / f"{symbol}.csv")
        df["date"] = pd.to_datetime(df["date"])
        data[symbol] = df.set_index("date").sort_index()
    return _dict_to_multiindex(data)


def _last_bar_binding(panel: pd.DataFrame) -> tuple[str, float, int]:
    """Return (binding_asset, binding_adv_notional, n_assets) for the panel's
    last bar, mirroring estimate_capacity's least-liquid-binds rule."""
    close = panel["close"]
    volume = panel["volume"]
    adv_notional = (volume.rolling(window=ADV_WINDOW, min_periods=1).mean() * close).iloc[-1]
    valid = adv_notional[np.isfinite(adv_notional) & (adv_notional > 0)]
    binding_asset = str(valid.idxmin())
    return binding_asset, float(valid.min()), int(close.shape[1])


def test_participation_rate_cap_sweeps_on_real_triple_panel():
    panel = _build_real_triple_panel()
    binding_asset, binding_adv_notional, n_assets = _last_bar_binding(panel)

    baseline = estimate_capacity(
        panel, IMPACT_COEFFICIENT, max_impact=MAX_IMPACT, adv_window=ADV_WINDOW
    )
    assert baseline["estimable"] is True
    assert baseline["estimated_capacity"] is not None
    assert baseline["estimated_capacity"] > 0
    assert baseline["participation_capacity"] is None
    assert baseline["binding_asset"] == binding_asset
    assert baseline["n_assets"] == n_assets

    rows = []
    for rate in PARTICIPATION_LEVELS:
        r = estimate_capacity(
            panel,
            IMPACT_COEFFICIENT,
            max_impact=MAX_IMPACT,
            adv_window=ADV_WINDOW,
            max_participation_rate=rate,
        )
        assert r["estimable"] is True
        assert r["estimated_capacity"] is not None, f"capacity None at rate {rate}"
        assert r["estimated_capacity"] > 0, f"non-positive capacity at rate {rate}"
        assert r["participation_capacity"] is not None
        assert r["impact_capacity"] is not None
        assert r["binding_asset"] == binding_asset
        assert r["n_assets"] == n_assets

        # participation_capacity == n_assets * rate * binding_adv_notional
        expected_part = n_assets * rate * binding_adv_notional
        assert abs(r["participation_capacity"] - expected_part) < 1e-6 * max(1.0, expected_part), (
            f"participation_capacity {r['participation_capacity']} != "
            f"n_assets*rate*ADV {expected_part} at rate {rate}"
        )

        # reported capacity is min(impact, participation) (zero cost drag here)
        expected_cap = min(r["impact_capacity"], r["participation_capacity"])
        assert abs(r["estimated_capacity"] - expected_cap) < 1e-6 * max(1.0, expected_cap), (
            f"estimated_capacity {r['estimated_capacity']} != "
            f"min(impact, participation) {expected_cap} at rate {rate}"
        )

        rows.append(r)

    # Capacity is non-decreasing in the participation rate (a looser cap can
    # only raise, never lower, the min(impact, participation) capacity).
    for prev, curr in zip(rows, rows[1:]):
        assert curr["estimated_capacity"] >= prev["estimated_capacity"] - 1e-6, (
            "capacity decreased as the participation cap loosened: "
            f"{prev['max_participation_rate']} -> {prev['estimated_capacity']:,.0f}, "
            f"{curr['max_participation_rate']} -> {curr['estimated_capacity']:,.0f}"
        )

    # The cap binds at the tightest rate and is slack at the loosest rate.
    tight = rows[0]
    loose = rows[-1]
    assert tight["participation_capacity"] < tight["impact_capacity"], (
        "participation cap does not bind at the tightest rate"
    )
    assert abs(tight["estimated_capacity"] - tight["participation_capacity"]) < 1e-6 * max(
        1.0, tight["participation_capacity"]
    ), "tight-capacity should equal the participation limit"

    assert loose["participation_capacity"] > loose["impact_capacity"], (
        "participation cap still binds at the loosest rate; no crossover observed"
    )
    assert abs(loose["estimated_capacity"] - loose["impact_capacity"]) < 1e-6 * max(
        1.0, loose["impact_capacity"]
    ), "loose-capacity should equal the impact-based capacity"
    # Slack cap must not change capacity versus the no-cap baseline.
    assert abs(loose["estimated_capacity"] - baseline["estimated_capacity"]) < 1e-6 * max(
        1.0, baseline["estimated_capacity"]
    ), "slack participation cap altered the baseline capacity"

    # There is a real crossover: at least one level binds and at least one does not.
    binds = [r["participation_capacity"] < r["impact_capacity"] for r in rows]
    assert any(binds) and not all(binds), "expected a binding/slack crossover across levels"


def test_participation_rate_cap_ignored_when_impact_disabled():
    panel = _build_real_triple_panel()
    r = estimate_capacity(
        panel, 0.0, max_impact=MAX_IMPACT, adv_window=ADV_WINDOW, max_participation_rate=0.0001
    )
    assert r["unconstrained"] is True
    assert r["estimated_capacity"] is None
    assert r["participation_capacity"] is None


if __name__ == "__main__":
    test_participation_rate_cap_sweeps_on_real_triple_panel()
    test_participation_rate_cap_ignored_when_impact_disabled()
    print("OK")