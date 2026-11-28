#!/usr/bin/env python3
"""Integration guard: the PIT warning band is reachable through run_backtest.

WHAT THIS IS
    A regression/integration test that the ``lookahead_warning_threshold``
    warning band added to ``data_loader.validate_point_in_time`` is actually
    wired through the primary backtest entry point's point-in-time gate
    (``run_backtest._validate_point_in_time``) and is NOT silently dropped by
    that gate's warning filter. It is a check on the wiring, on SYNTHETIC data,
    NOT evidence about any security, strategy, or market.

WHY IT EXISTS
    ``validate_point_in_time`` grew a ``lookahead_warning_threshold`` band
    (unit-tested in test_data_loader.py), but every production caller used the
    default ``None``, so the band could never fire in a real run. The gate also
    filtered out *any* warning mentioning the internal ``_pit_signal`` column,
    which would have suppressed the look-ahead warning-zone message too. This
    test pins both: the band is reachable, and the filter drops only the
    "identical values" artifact while preserving the genuine look-ahead warning.

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

from run_backtest import _validate_point_in_time  # noqa: E402

# --- Fixed construction (stated once; changing these changes the demo).
SEED = 11
PANEL_PERIODS = 600
HARD_THRESHOLD = 0.3          # validate_point_in_time default lookahead_threshold
WARNING_THRESHOLD = 0.25      # lower bound of the warning band
BELOW_BETA = 0.28             # in (0.25, 0.3]: passes, must warn when band set


def _synthetic_panel() -> pd.DataFrame:
    """Driftless random-walk OHLCV panel (the null: no injected effect)."""
    rng = np.random.default_rng(SEED)
    rets = rng.normal(0.0, 0.01, PANEL_PERIODS)
    close = 100.0 * np.exp(np.cumsum(rets))
    return pd.DataFrame(
        {
            "open": close * (1 + rng.normal(0.0, 0.001, PANEL_PERIODS)),
            "high": close * (1 + np.abs(rng.normal(0.0, 0.002, PANEL_PERIODS))),
            "low": close * (1 - np.abs(rng.normal(0.0, 0.002, PANEL_PERIODS))),
            "close": close,
            "volume": rng.integers(1_000_000, 5_000_000, PANEL_PERIODS).astype(float),
        },
        index=pd.date_range("2010-01-01", periods=PANEL_PERIODS, freq="B"),
    )


def _next_returns(df: pd.DataFrame) -> pd.Series:
    return df["close"].pct_change().shift(-1)


def _build_look_ahead_signal(df: pd.DataFrame, beta: float) -> pd.Series:
    """Signal whose changes have Pearson correlation exactly ``beta`` with
    next-period returns (orthogonal-noise construction; see
    test_pit_threshold_boundary_synthetic.py for the full derivation)."""
    r = _next_returns(df)
    valid = r.notna()
    valid.iloc[0] = False  # signal.diff() is NaN at bar 0
    valid_idx = df.index[valid]
    r_valid = r[valid].to_numpy(dtype=float)
    n = len(r_valid)
    rng = np.random.default_rng(SEED + 1)
    z = rng.normal(0.0, 1.0, n)

    def standardize(a: np.ndarray) -> np.ndarray:
        a = a - a.mean()
        return a / a.std(ddof=1)

    x = standardize(r_valid)
    z = standardize(z)
    z = z - x * float(np.dot(x, z) / np.dot(x, x))
    z = standardize(z)
    changes = beta * x + np.sqrt(1.0 - beta ** 2) * z

    signal = pd.Series(0.0, index=df.index, dtype=float)
    signal.loc[valid_idx[0]] = changes[0]
    for j in range(1, n):
        signal.loc[valid_idx[j]] = signal.loc[valid_idx[j - 1]] + changes[j]
    signal.loc[df.index[-1]] = signal.loc[valid_idx[-1]]
    return signal


def _sticky_signal(df: pd.DataFrame) -> pd.Series:
    """A signal with a single long plateau (>10% of bars identical) and no
    look-ahead information: triggers the forward-fill artifact warning only."""
    n = len(df)
    sig = np.zeros(n)
    sig[n // 2:] = 1.0  # one run of length ~n/2 identical values
    return pd.Series(sig, index=df.index)


def _has_warning(result: dict, needle: str) -> bool:
    return any(needle in w for w in result.get("warnings", []))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_warning_band_reachable_through_gate():
    """A sub-threshold look-ahead signal (corr ~0.28) with the band set must
    surface a warning-zone warning through run_backtest's gate -- and must
    still PASS (warning, not violation)."""
    df = _synthetic_panel()
    sig = _build_look_ahead_signal(df, BELOW_BETA)
    result = _validate_point_in_time(
        df, sig, lookahead_warning_threshold=WARNING_THRESHOLD
    )
    assert result["passed"] is True, f"warning-zone signal failed the gate: {result}"
    assert not result["violations"], f"unexpected violations: {result['violations']}"
    assert _has_warning(result, "warning zone"), (
        f"warning-zone warning not surfaced through the gate: {result['warnings']}"
    )


def test_warning_band_disabled_by_default_no_warning():
    """With the default (None) the same signal passes with NO warning-zone
    warning: default behavior is byte-identical to before the band existed."""
    df = _synthetic_panel()
    sig = _build_look_ahead_signal(df, BELOW_BETA)
    result = _validate_point_in_time(df, sig)  # default None
    assert result["passed"] is True, f"clean pass expected: {result}"
    assert not _has_warning(result, "warning zone"), (
        f"warning band fired without being configured: {result['warnings']}"
    )


def test_filter_drops_identical_values_artifact_but_keeps_lookahead():
    """The narrowed filter drops ONLY the forward-fill artifact (identical
    values) while preserving the genuine look-ahead warning-zone message."""
    df = _synthetic_panel()

    # (a) Sticky signal: artifact warning must be filtered out.
    sticky = _sticky_signal(df)
    sticky_res = _validate_point_in_time(
        df, sticky, lookahead_warning_threshold=WARNING_THRESHOLD
    )
    assert not _has_warning(sticky_res, "identical values"), (
        f"forward-fill artifact not filtered: {sticky_res['warnings']}"
    )

    # (b) Look-ahead signal: warning-zone message must survive the filter.
    look = _build_look_ahead_signal(df, BELOW_BETA)
    look_res = _validate_point_in_time(
        df, look, lookahead_warning_threshold=WARNING_THRESHOLD
    )
    assert _has_warning(look_res, "warning zone"), (
        f"look-ahead warning wrongly filtered: {look_res['warnings']}"
    )


if __name__ == "__main__":
    test_warning_band_reachable_through_gate()
    print("PASS  test_warning_band_reachable_through_gate")
    test_warning_band_disabled_by_default_no_warning()
    print("PASS  test_warning_band_disabled_by_default_no_warning")
    test_filter_drops_identical_values_artifact_but_keeps_lookahead()
    print("PASS  test_filter_drops_identical_values_artifact_but_keeps_lookahead")
    print("OK")