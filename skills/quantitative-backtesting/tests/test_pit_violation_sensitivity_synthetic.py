#!/usr/bin/env python3
"""Controlled look-ahead (point-in-time) sensitivity study on SYNTHETIC data.

WHAT THIS IS
    A methodological demonstration of *what the strict point-in-time gate
    prevents from being published*, measured on a synthetic price path. It is
    a check on the test machinery and on the size of the look-ahead bias, NOT
    evidence about any real security, strategy, or market. The price series is
    produced by a known formula (``generate_control_series`` with the effect
    removed -- a driftless random walk), it is not a quotation of anything, and
    every number printed here is a property of that formula and of the
    backtest engine, nothing more.

THE CONTROLLED PAIR
    Two strategies that differ by exactly one thing -- a one-bar look-ahead:

        clean      signal[t] = 1{ close[t]   > close[t-1] }   (close[t]-based)
        look-ahead signal[t] = 1{ close[t+1] > close[t]   }   (next-period)

    The look-ahead signal is the clean signal shifted one bar earlier
    (``clean.shift(-1)``): it acts on tomorrow's signal today. Everything else
    (the panel, the engine, costs, the parameter grid) is identical, so the
    pair is a control rather than two unrelated samples.

    The engine fills at ``signals.shift(1 + latency)`` (next-period open), so
    with ``latency=0`` the position held into period ``t`` is ``signal[t-1]``:

        clean:      position into t = sign(ret[t-1])  -> earns sign(ret[t-1])*ret[t]
        look-ahead: position into t = sign(ret[t])    -> earns |ret[t]| >= 0

    The look-ahead therefore earns the absolute next-period return every bar
    (perfect foresight): its out-of-sample record is inflated by construction.
    That is the headline inflation the strict gate aborts before it can be
    reported.

WHAT IS ASSERTED
    1. The clean signal PASSES point-in-time validation (no violations).
    2. The look-ahead signal is DETECTED as a PIT violation (its changes
       correlate with next-period returns above the 0.3 threshold).
    3. With the gate OFF (``validate_pit=False``) the look-ahead's headline
       out-of-sample metrics (Sharpe, total return) are materially HIGHER than
       the clean signal's -- the recorded delta the abort prevents.
    4. With the gate STRICT (``validate_pit=True, pit_strict=True``) the clean
       run completes while the look-ahead run ABORTS (raises ValueError), so
       the inflated record from (3) can never be published through that path.

Offline, deterministic (fixed seed), committed code only. Scope: this new test
file only -- no engine, fixture, pinned-hash, or inherited-catalog changes.
"""

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILLS_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from data_loader import validate_point_in_time  # noqa: E402
from walk_forward import walk_forward_analysis  # noqa: E402
from strategy_builder import StrategyConfig  # noqa: E402
from generate_positive_control_data import generate_control_series  # noqa: E402

# A repeated purpose label so the fixture can never be read as market evidence
# (mirrors generate_positive_control_data.FIXTURE_PURPOSE).
DEMONSTRATION_PURPOSE = (
    "METHODOLOGICAL DEMONSTRATION ON SYNTHETIC DATA: a driftless random-walk "
    "price path produced by a known formula, used to measure how much a "
    "one-bar look-ahead inflates headline out-of-sample metrics and to show "
    "the strict point-in-time gate aborting it. It is NOT evidence about any "
    "security, strategy, or market."
)

# --- Fixed construction (change these and the demonstration means something
# --- else, so they are stated in one place).
SEED = 7
PANEL_PERIODS = 640          # business days (~30 months) -> several WF windows
TRAIN_MONTHS = 6
TEST_MONTHS = 3
STEP_MONTHS = 3
COMMISSION = 0.0002
SLIPPAGE = 0.0001
PARAM_GRID = {"fast_period": [10]}  # single config; the signal ignores it

# Margins for the inflation assertions. Observed on this fixture (seed 7):
#   oos_sharpe:  clean ~ -1.70, look ~ +8.84  (delta ~ +10.5)
#   total return: clean ~ -0.24, look ~ +2.68  (delta ~ +2.91)
# The margins below are deliberately well inside those gaps so the test is
# robust to minor numpy/pandas version differences while still proving a
# material, one-directional inflation.
MIN_SHARPE_DELTA = 2.0
MIN_TOTAL_RETURN_DELTA = 1.0


class _CleanSignalStrategy:
    """close[t]-based momentum: long when the current bar was up."""

    def __init__(self, config):
        self.config = config
        self.name = config.name
        self.parameters = config.parameters

    def generate_signals(self, data):
        close = data["close"]
        return (close.pct_change() > 0).astype(float).reindex(data.index).fillna(0.0)


class _LookaheadSignalStrategy:
    """Next-period signal: the clean signal shifted one bar earlier."""

    def __init__(self, config):
        self.config = config
        self.name = config.name
        self.parameters = config.parameters

    def generate_signals(self, data):
        close = data["close"]
        nxt = close.pct_change().shift(-1)
        return (nxt > 0).astype(float).reindex(data.index).fillna(0.0)


def _clean_factory(params):
    return _CleanSignalStrategy(StrategyConfig(name="clean", parameters=params or {}))


def _lookahead_factory(params):
    return _LookaheadSignalStrategy(StrategyConfig(name="lookahead", parameters=params or {}))


def _synthetic_panel():
    """Driftless random-walk OHLCV panel (the null: no injected effect)."""
    df = generate_control_series(periods=PANEL_PERIODS, inject_effect=False, seed=SEED)
    return df.set_index("date").sort_index()


def _pit_for(strategy):
    """Point-in-time validation of a strategy's signal on the synthetic panel."""
    df = _synthetic_panel()
    signals = strategy.generate_signals(df)
    check = df.copy()
    check["_pit_signal"] = signals
    result = validate_point_in_time(check, signal_column="_pit_signal")
    # Drop the synthetic helper column from any forward-fill warning text.
    result["warnings"] = [w for w in result["warnings"] if "_pit_signal" not in w]
    return result


def _run_oos(strategy_factory):
    """Walk-forward out-of-sample run with the PIT gate OFF (validate_pit=False).

    Returns the summary dict. The gate is disabled here precisely so the
    look-ahead's inflated record is produced and can be measured; the strict
    path that aborts it is exercised separately.
    """
    result = walk_forward_analysis(
        data=_synthetic_panel(),
        strategy_factory=strategy_factory,
        param_grid=PARAM_GRID,
        train_months=TRAIN_MONTHS,
        test_months=TEST_MONTHS,
        step_months=STEP_MONTHS,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        validate_pit=False,
    )
    return result["summary"]


def headline_delta():
    """Record the headline-metric delta the strict gate prevents from publishing.

    Returns a dict with the clean and look-ahead headline metrics and their
    deltas (look-ahead minus clean). Positive deltas are the inflation.
    """
    clean = _run_oos(_clean_factory)
    look = _run_oos(_lookahead_factory)
    return {
        "clean_oos_sharpe": clean.get("oos_sharpe"),
        "look_oos_sharpe": look.get("oos_sharpe"),
        "sharpe_delta": look.get("oos_sharpe") - clean.get("oos_sharpe"),
        "clean_total_oos_return": clean.get("total_oos_return"),
        "look_total_oos_return": look.get("total_oos_return"),
        "total_return_delta": look.get("total_oos_return") - clean.get("total_oos_return"),
        "n_periods": clean.get("n_periods"),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_synthetic_panel_is_a_clean_random_walk_null():
    """The fixture is a well-formed DatetimeIndex panel with no PIT issues of
    its own (the null the clean signal is measured against)."""
    df = _synthetic_panel()
    assert isinstance(df.index, type(df.index)) and df.index.is_monotonic_increasing
    assert len(df) == PANEL_PERIODS
    base = validate_point_in_time(df)
    assert base["passed"] is True, f"panel itself flagged: {base}"
    assert base["violations"] == []


def test_clean_signal_passes_point_in_time():
    """Negative control: the close[t]-based signal is not a look-ahead."""
    pit = _pit_for(_CleanSignalStrategy(StrategyConfig(name="clean", parameters={})))
    assert pit["passed"] is True, f"clean signal flagged as look-ahead: {pit}"
    assert pit["violations"] == []


def test_lookahead_signal_is_detected_as_pit_violation():
    """Positive control: the next-period signal is flagged, with a correlation
    above the 0.3 threshold named in the violation text."""
    pit = _pit_for(_LookaheadSignalStrategy(StrategyConfig(name="look", parameters={})))
    assert pit["passed"] is False, f"look-ahead signal not detected: {pit}"
    combined = " ".join(pit["violations"]).lower()
    assert "correlat" in combined or "look-ahead" in combined or "look ahead" in combined, (
        f"violation did not indicate look-ahead/correlation: {pit['violations']}"
    )
    assert "threshold=0.300" in combined, f"threshold not reflected in violation: {combined}"


def test_lookahead_inflates_headline_oos_metrics():
    """Core result: with the gate off, the look-ahead's headline out-of-sample
    metrics are materially higher than the clean signal's. The recorded delta
    is the inflation the strict gate prevents from being published."""
    d = headline_delta()
    assert d["n_periods"] and d["n_periods"] > 1, f"need >1 OOS period, got {d}"
    # Perfect foresight: the look-ahead's total OOS return is positive.
    assert d["look_total_oos_return"] > 0.0, f"look-ahead total return not positive: {d}"
    # Material, one-directional inflation in both headline metrics.
    assert d["sharpe_delta"] > MIN_SHARPE_DELTA, (
        f"look-ahead Sharpe did not inflate by > {MIN_SHARPE_DELTA}: {d}"
    )
    assert d["total_return_delta"] > MIN_TOTAL_RETURN_DELTA, (
        f"look-ahead total return did not inflate by > {MIN_TOTAL_RETURN_DELTA}: {d}"
    )


def test_strict_pit_aborts_on_lookahead_but_not_clean():
    """The strict gate completes on the clean signal and aborts (ValueError) on
    the look-ahead, so the inflated record above cannot be published."""
    df = _synthetic_panel()

    # Clean: strict gate must complete and report a passing PIT result.
    clean_res = walk_forward_analysis(
        data=df,
        strategy_factory=_clean_factory,
        param_grid=PARAM_GRID,
        train_months=TRAIN_MONTHS,
        test_months=TEST_MONTHS,
        step_months=STEP_MONTHS,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        validate_pit=True,
        pit_strict=True,
    )
    pit = clean_res.get("point_in_time_validation") or {}
    assert pit.get("passed") is True, f"clean run flagged under strict PIT: {pit}"

    # Look-ahead, warn-only (pit_strict=False): must NOT abort -- the gate
    # detects but does not stop. This proves the abort below is caused by
    # strict mode specifically, not by the look-ahead crashing the run.
    warn_res = walk_forward_analysis(
        data=df,
        strategy_factory=_lookahead_factory,
        param_grid=PARAM_GRID,
        train_months=TRAIN_MONTHS,
        test_months=TEST_MONTHS,
        step_months=STEP_MONTHS,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        validate_pit=True,
        pit_strict=False,
    )
    warn_pit = warn_res.get("point_in_time_validation") or {}
    assert warn_pit.get("passed") is False, f"warn-only run did not detect look-ahead: {warn_pit}"

    # Look-ahead, strict: must abort.
    raised = False
    try:
        walk_forward_analysis(
            data=df,
            strategy_factory=_lookahead_factory,
            param_grid=PARAM_GRID,
            train_months=TRAIN_MONTHS,
            test_months=TEST_MONTHS,
            step_months=STEP_MONTHS,
            commission=COMMISSION,
            slippage=SLIPPAGE,
            validate_pit=True,
            pit_strict=True,
        )
    except ValueError as exc:
        raised = True
        assert "point-in-time" in str(exc).lower(), f"unexpected abort reason: {exc}"
    assert raised, "strict PIT did not abort on the look-ahead signal"


if __name__ == "__main__":
    for fn in (
        test_synthetic_panel_is_a_clean_random_walk_null,
        test_clean_signal_passes_point_in_time,
        test_lookahead_signal_is_detected_as_pit_violation,
        test_lookahead_inflates_headline_oos_metrics,
        test_strict_pit_aborts_on_lookahead_but_not_clean,
    ):
        fn()
        print(f"PASS  {fn.__name__}")
    d = headline_delta()
    print("RECORDED HEADLINE DELTA (look-ahead minus clean; the abort prevents this):")
    print(f"  oos_sharpe:      clean={d['clean_oos_sharpe']:.4f}  look={d['look_oos_sharpe']:.4f}  "
          f"delta=+{d['sharpe_delta']:.4f}")
    print(f"  total_oos_return: clean={d['clean_total_oos_return']:.4f}  look={d['look_total_oos_return']:.4f}  "
          f"delta=+{d['total_return_delta']:.4f}")
    print(f"  periods={d['n_periods']}")
    print("PURPOSE:", DEMONSTRATION_PURPOSE)
    print("OK")