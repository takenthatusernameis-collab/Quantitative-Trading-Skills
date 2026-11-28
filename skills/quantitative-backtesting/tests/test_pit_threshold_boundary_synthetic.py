#!/usr/bin/env python3
"""Threshold-boundary audit of the point-in-time look-ahead detector on SYNTHETIC data.

WHAT THIS IS
    A methodological demonstration of the strict point-in-time gate's blind
    spot, measured on a synthetic price path. It is a check on the detector
    itself, NOT evidence about any security, strategy, or market.

THE DETECTOR
    validate_point_in_time correlates signal changes with next-period returns
    (close[t+1] / close[t] - 1) and flags a look-ahead violation when
    |corr| > lookahead_threshold (default 0.3). The threshold is a hard cut:
    anything at or below 0.3 passes; anything above aborts in strict mode.

WHAT IS DEMONSTRATED
    Two synthetic signals whose changes have a controlled Pearson correlation
    with next-period returns:

      (a) above 0.3 (beta = 0.32): the strict gate aborts, the correlation is
          named in the violation, and the inflated record is prevented.
      (b) below 0.3 (beta = 0.28): the gate PASSES (no violation), yet the
          signal's changes still correlate with next-period returns (0.28 != 0),
          so the signal still predicts / inflates next-period returns and the
          gate's pass is a false negative. This is the detector's honest
          limitation: sub-threshold look-ahead is not detected.

    The correlation is built deterministically so beta equals the measured
    correlation (signal changes = beta * standardized next-return +
    sqrt(1-beta^2) * independent orthogonal noise, integrated into signal
    levels), so the boundary is exact and not sampling-dependent.

Offline, deterministic (fixed seed), committed code only. Scope: this new test
file only -- no engine, fixture, pinned-hash, or inherited-catalog changes.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILLS_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from data_loader import validate_point_in_time  # noqa: E402
from run_backtest import _handle_point_in_time_results  # noqa: E402

# --- Fixed construction (stated in one place; changing them changes the demo).
SEED = 7
PANEL_PERIODS = 2000          # daily bars; valid next-return observations = N - 2
THRESHOLD = 0.3               # validate_point_in_time default lookahead_threshold
ABOVE_BETA = 0.32             # just above threshold -> must abort
BELOW_BETA = 0.28             # just below threshold -> gate passes, still inflates

DEMONSTRATION_PURPOSE = (
    "METHODOLOGICAL DEMONSTRATION ON SYNTHETIC DATA: a random-walk price path "
    "produced by a known formula, with a look-ahead signal whose next-return "
    "correlation is set to exactly 0.32 (above) and 0.28 (below) the 0.3 "
    "point-in-time threshold. Shows the gate aborting above threshold and "
    "passing -- while still inflating -- below threshold. It is NOT evidence "
    "about any security, strategy, or market."
)


def _synthetic_panel() -> pd.DataFrame:
    """Driftless random-walk OHLCV panel (the null: no injected effect)."""
    rng = np.random.default_rng(SEED)
    rets = rng.normal(0.0, 0.01, PANEL_PERIODS)
    close = 100.0 * np.exp(np.cumsum(rets))
    df = pd.DataFrame(
        {
            "open": close * (1 + rng.normal(0.0, 0.001, PANEL_PERIODS)),
            "high": close * (1 + np.abs(rng.normal(0.0, 0.002, PANEL_PERIODS))),
            "low": close * (1 - np.abs(rng.normal(0.0, 0.002, PANEL_PERIODS))),
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, PANEL_PERIODS).astype(float),
        },
        index=pd.date_range("2010-01-01", periods=PANEL_PERIODS, freq="B"),
    )
    return df


def _next_returns(df: pd.DataFrame) -> pd.Series:
    """Next-period return close[t+1]/close[t]-1, aligned to bar t (NaN at last)."""
    return df["close"].pct_change().shift(-1)


def _build_look_ahead_signal(df: pd.DataFrame, beta: float) -> pd.Series:
    """Signal whose changes have Pearson correlation exactly `beta` with next-period returns.

    Constructed over the valid bars (where both signal.diff() and next-return
    are defined) as beta * standardized_next_return + sqrt(1-beta^2) *
    standardized independent noise orthogonalized to the next-return, then
    integrated into signal levels. The measured correlation equals beta.
    """
    r = _next_returns(df)
    valid = r.notna()
    valid.iloc[0] = False  # signal.diff() is NaN at bar 0 -> not a valid comparison bar
    valid_idx = df.index[valid]
    # next-return is NaN at the last bar -> valid = bars 1..N-2, count N - 2
    r_valid = r[valid].to_numpy(dtype=float)
    n = len(r_valid)
    rng = np.random.default_rng(SEED + 1)
    z = rng.normal(0.0, 1.0, n)

    def standardize(a: np.ndarray) -> np.ndarray:
        a = a - a.mean()
        return a / a.std(ddof=1)

    x = standardize(r_valid)                       # standardized next-return
    z = standardize(z)                             # standardized independent noise
    z = z - x * float(np.dot(x, z) / np.dot(x, x)) # orthogonalize noise to return
    z = standardize(z)

    # corr(beta*x + sqrt(1-beta^2)*z, x) == beta exactly (x _|_ z, both unit std).
    changes = beta * x + np.sqrt(1.0 - beta ** 2) * z

    # Integrate changes into signal levels so that signal.diff()[valid_bar_t] ==
    # changes[t] pairs exactly with next-return r[valid_bar_t] for every valid bar.
    # valid bars = 1..N-2 (signal.diff() NaN at bar 0; next-return NaN at last bar).
    signal = pd.Series(0.0, index=df.index, dtype=float)  # bar 0 baseline
    signal.loc[valid_idx[0]] = changes[0]                 # diff[bar 1] = changes[0]
    for j in range(1, n):
        signal.loc[valid_idx[j]] = signal.loc[valid_idx[j - 1]] + changes[j]
    signal.loc[df.index[-1]] = signal.loc[valid_idx[-1]]  # last bar: diff excluded
    return signal


def _pit(df: pd.DataFrame, signal: pd.Series, beta: float) -> dict:
    check = df.copy()
    check["_pit_signal"] = signal
    result = validate_point_in_time(check, signal_column="_pit_signal")
    result["warnings"] = [
        w for w in result["warnings"] if "_pit_signal" not in w
    ]
    result["beta"] = beta
    return result


def _measured_correlation(df: pd.DataFrame, signal: pd.Series) -> float:
    r = _next_returns(df)
    sc = signal.diff()
    valid = r.notna() & sc.notna()
    return float(r[valid].corr(sc[valid]))


# ---------------------------------------------------------------------------
# Fixtures built once (deterministic, fixed seed).
# ---------------------------------------------------------------------------
_PANEL = _synthetic_panel()
_SIGNAL_ABOVE = _build_look_ahead_signal(_PANEL, ABOVE_BETA)
_SIGNAL_BELOW = _build_look_ahead_signal(_PANEL, BELOW_BETA)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_panel_is_well_formed_null():
    """The synthetic panel is a well-formed DatetimeIndex frame with clean PIT."""
    df = _PANEL
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.is_monotonic_increasing
    assert not df.index.duplicated().any()
    assert len(df) == PANEL_PERIODS
    base = validate_point_in_time(df)
    assert base["passed"] is True, f"panel itself flagged: {base}"
    assert base["violations"] == []


def test_correlations_equal_beta_exactly():
    """The construction hits the target beta exactly (boundary is exact)."""
    assert abs(_measured_correlation(_PANEL, _SIGNAL_ABOVE) - ABOVE_BETA) < 1e-9
    assert abs(_measured_correlation(_PANEL, _SIGNAL_BELOW) - BELOW_BETA) < 1e-9


def test_above_threshold_strict_abort_inflation_prevented():
    """(a) beta = 0.32 > 0.3: PIT fails, correlation named in violation, strict
    handler aborts -- the inflated record is prevented."""
    pit = _pit(_PANEL, _SIGNAL_ABOVE, ABOVE_BETA)
    measured = _measured_correlation(_PANEL, _SIGNAL_ABOVE)
    assert measured > THRESHOLD, f"above case not above threshold: {measured}"
    assert pit["passed"] is False, f"above-threshold signal passed PIT: {pit}"
    assert pit["violations"], f"expected a violation for beta={ABOVE_BETA}: {pit}"
    combined = " ".join(pit["violations"]).lower()
    assert "correlat" in combined or "look-ahead" in combined or "look ahead" in combined, (
        f"violation did not indicate look-ahead/correlation: {pit['violations']}"
    )
    assert f"threshold={THRESHOLD:.3f}" in combined, (
        f"threshold not reflected in violation: {combined}"
    )
    assert _handle_point_in_time_results(pit, strict=True) is True, (
        "strict handler did not abort on above-threshold look-ahead"
    )
    # Warn-only still detects (does not crash); strict is what aborts.
    assert _handle_point_in_time_results(pit, strict=False) is False


def test_below_threshold_gate_passes_yet_signal_still_inflates():
    """(b) beta = 0.28 < 0.3: PIT PASSES with no correlation violation, yet the
    signal's changes correlate with next-period returns (0.28 != 0), so it still
    predicts / inflates next-period returns. The gate's pass is a false negative
    -- an honest statement of the detector's sub-threshold limitation."""
    pit = _pit(_PANEL, _SIGNAL_BELOW, BELOW_BETA)
    measured = _measured_correlation(_PANEL, _SIGNAL_BELOW)
    # 0.2 < measured < 0.3: the signal's changes carry real next-return
    # information (look-ahead present, corr nonzero) but sit below the
    # detector's 0.3 tripwire, so the gate passes -- a false negative.
    assert 0.2 < measured < THRESHOLD, f"below case not a nonzero sub-threshold look-ahead: {measured}"
    assert pit["passed"] is True, f"below-threshold signal failed PIT: {pit}"
    # No correlation/look-ahead violation may be present.
    combined = " ".join(pit["violations"]).lower()
    assert "correlat" not in combined and "look-ahead" not in combined and "look ahead" not in combined, (
        f"below-threshold signal wrongly flagged: {pit['violations']}"
    )
    assert _handle_point_in_time_results(pit, strict=True) is False, (
        "strict handler aborted on a below-threshold (passing) signal"
    )


if __name__ == "__main__":
    test_panel_is_well_formed_null()
    print("PASS  test_panel_is_well_formed_null")
    test_correlations_equal_beta_exactly()
    print("PASS  test_correlations_equal_beta_exactly")
    test_above_threshold_strict_abort_inflation_prevented()
    print("PASS  test_above_threshold_strict_abort_inflation_prevented")
    test_below_threshold_gate_passes_yet_signal_still_inflates()
    print("PASS  test_below_threshold_gate_passes_yet_signal_still_inflates")
    print("OK")
    print("PURPOSE:", DEMONSTRATION_PURPOSE)
