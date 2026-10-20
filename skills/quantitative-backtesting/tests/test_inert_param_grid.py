#!/usr/bin/env python3
"""Regression tests for inert parameter grids on every analysis path.

A grid key whose values do not change the strategy's behaviour is a null
experiment: the "search" over it cannot change any result, yet the artifact
would still report it as a selected parameter. The shipped example makes the
trap easy to hit -- `sma_crossover` reads `fast_period` and `slow_period`, so
a grid over `lookback` prices the same strategy in every combination and the
ranking that comes out is an artefact of the tie-break, not evidence.

These tests guard the behaviour of all four analysis paths:

  * `walk_forward_analysis` records the finding in its summary;
  * `cpcv_analysis` records the finding in its summary;
  * `parameter_optimization` measures it and hands it to the caller;
  * `out_of_sample_validation` records the finding in its summary;
  * every CLI prints the warning exactly once, next to the ranking /
    selection it qualifies, and writes the finding into the artifact;
  * the measurement is a measurement: no return, cost, impact, capacity or
    selection number changes because of it.

Run with: python3 skills/quantitative-backtesting/tests/test_inert_param_grid.py
No third-party test framework is required; uses only the standard library.
"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

import walk_forward as walk_forward_module  # noqa: E402
from walk_forward import (  # noqa: E402
    _INERT_GRID_MAX_COMBINATIONS,
    _inert_grid_report,
    _inert_param_grid_keys,
    _inert_param_grid_keys_measured,
    _make_strategy_factory,
    _same_behaviour,
    _strategy_behaviour_fingerprint,
    cpcv_analysis,
    out_of_sample_validation,
    parameter_optimization,
    walk_forward_analysis,
)

SAMPLE_DATA = SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv"
WALK_FORWARD_CLI = SKILLS_DIR / "scripts" / "walk_forward.py"

# A grid the strategy actually reads. `sma_crossover` uses `fast_period` and
# `slow_period`; a grid over any other name is inert.
MEANINGFUL_GRID = {"fast_period": [5, 10], "slow_period": [20, 30]}
INERT_GRID = {"lookback": [5, 20]}
# One live key and one inert key: only the inert one may be reported.
MIXED_GRID = {"fast_period": [5, 10], "lookback": [5, 20]}

# The verdicts the shipped strategies produced before the check learned to
# look at every combination of the other grid values. None of the shipped
# strategies has parameters that interact, so the exhaustive check must
# reproduce these verdicts exactly: the fix may only remove *false*
# accusations, never add or drop a finding.
SHIPPED_INERT_VERDICTS = [
    ("sma_crossover", {"fast_period": [5, 10], "slow_period": [20, 30]}, []),
    ("sma_crossover", {"lookback": [5, 20]}, ["lookback"]),
    ("sma_crossover", {"fast_period": [5, 10], "lookback": [5, 20]}, ["lookback"]),
    ("sma_crossover", {"fast_period": [5, 10, 20], "slow_period": [20, 30, 40]}, []),
    (
        "sma_crossover",
        {"fast_period": [5, 10], "slow_period": [20, 30], "lookback": [5, 20]},
        ["lookback"],
    ),
    (
        "sma_crossover",
        {"rsi_period": [5, 14, 30], "lookback": [10, 20]},
        ["rsi_period", "lookback"],
    ),
    ("ema_crossover", {"fast_period": [5, 10], "slow_period": [20, 30]}, []),
    ("ema_crossover", {"lookback": [5, 20]}, ["lookback"]),
    ("macd", {"fast_period": [5, 10], "slow_period": [20, 30]}, []),
    (
        "macd",
        {"macd_fast": [5, 12], "macd_slow": [20, 26], "macd_signal": [5, 9]},
        ["macd_fast", "macd_slow", "macd_signal"],
    ),
    (
        "bollinger_bands",
        {"fast_period": [5, 10], "slow_period": [20, 30]},
        ["fast_period", "slow_period"],
    ),
    ("bollinger_bands", {"period": [5, 20], "std_dev": [1.5, 2.0, 2.5]}, []),
    (
        "rsi_mean_reversion",
        {"rsi_period": [5, 14, 30], "lookback": [10, 20]},
        ["rsi_period", "lookback"],
    ),
    ("donchian_breakout", {"lookback": [5, 20]}, ["lookback"]),
    (
        "donchian_breakout",
        {"fast_period": [5, 10], "lookback": [5, 20]},
        ["fast_period", "lookback"],
    ),
]


class InteractingStrategy:
    """A strategy whose ``threshold`` is read only in the ``mode == "b"`` branch.

    ``mode`` "a" is long when the close is above its 3-bar mean; ``mode``
    "b" is long when the close is more than ``threshold`` above that mean.
    A parameter that is read only inside a branch is the ordinary way a
    parameter's effect becomes conditional on another parameter, and it is
    the case the first-value comparison could not see.
    """

    def __init__(self, params):
        self.parameters = dict(params)

    def generate_signals(self, data):
        mode = self.parameters.get("mode", "a")
        threshold = self.parameters.get("threshold", 0.05)
        close = data["close"]
        mid = close.rolling(3).mean()
        if mode == "a":
            signal = (close > mid).astype(float)
        else:
            signal = ((close - mid) > threshold).astype(float)
        return pd.Series(signal.to_numpy(), index=close.index)


def _interacting_factory(params):
    return InteractingStrategy(params)


def _interacting_data() -> pd.DataFrame:
    """Six bars whose last one sits 0.0833 above its 3-bar mean.

    The gap is what makes the interaction observable: it is above the 0.05
    threshold, so the two modes agree there, and below the 0.1 one, so they
    differ there.
    """
    closes = [10.0, 10.0, 10.0, 10.0, 10.0, 10.125]
    index = pd.date_range("2020-01-01", periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1_000_000] * len(closes),
        },
        index=index,
    )


# The grid whose two keys interact: `threshold` is only read when
# `mode == "b"`, so each key looks inert when the other is held at its
# first value.
INTERACTING_GRID = {"mode": ["a", "b"], "threshold": [0.05, 0.1]}


def _first_value_inert_keys(strategy_factory, param_grid, data) -> list:
    """The rule the check used before it looked at every combination.

    Each key is compared with the other grid keys held at their first
    value, so a key whose effect appears only in combination with a
    non-first value of another key is accused of being inert. Kept here as
    the evidence that the demonstration below is a real defect and not a
    hypothetical one.
    """
    inert = []
    for key, values in (param_grid or {}).items():
        if not isinstance(values, (list, tuple)) or len(values) < 2:
            continue
        fingerprints = []
        for value in values:
            params = {}
            for other_key, other_values in (param_grid or {}).items():
                if other_key == key:
                    continue
                if isinstance(other_values, (list, tuple)) and len(other_values) > 0:
                    params[other_key] = other_values[0]
            params[key] = value
            try:
                strategy = strategy_factory(params)
            except Exception:
                fingerprints.append(None)
                continue
            fingerprints.append(_strategy_behaviour_fingerprint(strategy, data))
        if not fingerprints:
            continue
        reference = fingerprints[0]
        if reference is None:
            continue
        if all(_same_behaviour(reference, other) for other in fingerprints[1:]):
            inert.append(key)
    return inert


def _load_sample() -> pd.DataFrame:
    df = pd.read_csv(SAMPLE_DATA, parse_dates=["date"]).set_index("date")
    return df


def _make_ohlcv_data(periods: int = 900, seed: int = 42) -> pd.DataFrame:
    """Long trending sample, used where a 12 + 3 month window does fit."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=periods, freq="B")
    trend = np.linspace(0, 0.5, periods)
    noise = rng.normal(0, 0.01, periods)
    prices = 100 * np.exp(np.cumsum(trend / periods + noise))
    return pd.DataFrame(
        {
            "open": prices * rng.uniform(0.995, 1.005, periods),
            "high": prices * rng.uniform(1.005, 1.02, periods),
            "low": prices * rng.uniform(0.98, 0.995, periods),
            "close": prices,
            "volume": rng.integers(1_000_000, 10_000_000, periods),
        },
        index=dates,
    )


def _run_cli(args):
    return subprocess.run(
        [sys.executable, str(WALK_FORWARD_CLI)] + args,
        capture_output=True,
        text=True,
        timeout=1800,
    )


def _capture_stdout(fn, *args, **kwargs):
    """Run `fn` and return (result, stdout)."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = fn(*args, **kwargs)
    return result, buffer.getvalue()


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------

def test_inert_grid_report_flags_a_key_the_strategy_ignores():
    """The report names the inert keys and says why the search is empty."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    report = _inert_grid_report(factory, INERT_GRID, data)
    assert report["inert_grid_params"] == ["lookback"]
    assert "lookback" in report["message"]
    assert "null experiment" in report["message"]
    # The hint names the parameters the strategy actually reads.
    assert report["strategy_parameters"] == ["fast_period", "slow_period"]
    assert "fast_period" in report["message"]


def test_inert_grid_report_does_not_flag_a_live_key():
    """A grid the strategy reads is never reported as inert."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    report = _inert_grid_report(factory, MEANINGFUL_GRID, data)
    assert report["inert_grid_params"] == []
    assert report["message"] is None


def test_inert_grid_report_flags_only_the_inert_key_of_a_mixed_grid():
    """A grid with one live and one inert key reports only the inert one."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    report = _inert_grid_report(factory, MIXED_GRID, data)
    assert report["inert_grid_params"] == ["lookback"]


def test_inert_grid_report_agrees_with_the_key_detector():
    """The report is a thin layer over the key detector, not a second rule."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")
    for grid in (INERT_GRID, MEANINGFUL_GRID, MIXED_GRID):
        report = _inert_grid_report(factory, grid, data)
        assert report["inert_grid_params"] == _inert_param_grid_keys(factory, grid, data)


# ---------------------------------------------------------------------------
# The combination defect: a parameter that matters only in combination
# ---------------------------------------------------------------------------

def test_the_interacting_grid_really_interacts():
    """The demonstration rests on a behavioural fact, not on a guess."""
    data = _interacting_data()

    def signals(params):
        strategy = _interacting_factory(params)
        return np.asarray(strategy.generate_signals(data), dtype=float)

    # The two modes agree at the first threshold ...
    assert np.array_equal(
        signals({"mode": "a", "threshold": 0.05}),
        signals({"mode": "b", "threshold": 0.05}),
    )
    # ... and differ at the second one, so `mode` is live.
    assert not np.array_equal(
        signals({"mode": "a", "threshold": 0.1}),
        signals({"mode": "b", "threshold": 0.1}),
    )
    # The two thresholds agree in mode "a" ...
    assert np.array_equal(
        signals({"mode": "a", "threshold": 0.05}),
        signals({"mode": "a", "threshold": 0.1}),
    )
    # ... and differ in mode "b", so `threshold` is live.
    assert not np.array_equal(
        signals({"mode": "b", "threshold": 0.05}),
        signals({"mode": "b", "threshold": 0.1}),
    )


def test_the_first_value_rule_would_have_accused_both_keys():
    """The defect the fix removes: a false accusation, twice over.

    Comparing each key with the other one held at its first value finds no
    difference in either direction, so the old rule accused two live
    parameters of being inert.
    """
    data = _interacting_data()
    assert _first_value_inert_keys(
        _interacting_factory, INTERACTING_GRID, data
    ) == ["mode", "threshold"]


def test_a_key_that_matters_only_in_combination_is_not_accused():
    """Neither key is accused: each is live in a combination of the other."""
    data = _interacting_data()

    assert _inert_param_grid_keys(
        _interacting_factory, INTERACTING_GRID, data
    ) == []
    report = _inert_grid_report(_interacting_factory, INTERACTING_GRID, data)
    assert report["inert_grid_params"] == []
    assert report["message"] is None


def test_a_key_that_is_inert_in_every_combination_is_still_accused():
    """The exhaustive check does not exonerate a genuinely inert key.

    ``lookback`` is ignored by the strategy in every mode, so it is inert
    in every combination of ``mode``'s values -- not only in the first one.
    """
    data = _interacting_data()
    grid = {"mode": ["a", "b"], "lookback": [5, 20]}

    keys = _inert_param_grid_keys(_interacting_factory, grid, data)
    assert "lookback" in keys
    # `mode` is inert too: the ignored `lookback` cannot change whether
    # the two modes agree, so they agree in every combination.
    assert "mode" in keys


def test_the_shipped_strategies_keep_their_inert_verdicts():
    """The fix removes false accusations; it does not move a true finding.

    None of the shipped strategies has interacting parameters, so every
    verdict below is the one the first-value rule produced as well.
    """
    data = _load_sample()
    for strategy, grid, expected in SHIPPED_INERT_VERDICTS:
        factory = _make_strategy_factory(strategy)
        assert _inert_param_grid_keys(factory, grid, data) == expected, (
            f"{strategy} {grid}: the verdict changed"
        )
        assert _first_value_inert_keys(factory, grid, data) == expected, (
            f"{strategy} {grid}: the pinned verdict is not the historical one"
        )


# ---------------------------------------------------------------------------
# The bound on the exhaustive comparison
# ---------------------------------------------------------------------------

def test_a_bounded_check_says_so_in_the_message():
    """A truncated check accuses on incomplete evidence and says so."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")
    # A grid whose combinations of the other keys exceed the bound: every
    # key of two values multiplies the combination count by two, so enough
    # keys push it past the bound whatever the bound is.
    n_keys = 2
    while 2 ** (n_keys - 1) <= _INERT_GRID_MAX_COMBINATIONS:
        n_keys += 1
    grid = {"lookback": [5, 20]}
    grid.update({f"f{i}": [1, 2] for i in range(n_keys)})
    measured = _inert_param_grid_keys_measured(factory, grid, data)
    assert measured["bounded"], "the bound was not reached"
    assert set(measured["bounded"]) <= set(measured["inert"])
    # The bound falls back to the first combination, not to a partial
    # answer over the combinations it did evaluate.
    assert all(
        count == 1 for count in measured["combinations_evaluated"].values()
    )

    report = _inert_grid_report(factory, grid, data)
    assert report["inert_grid_params"] == measured["inert"]
    assert "bounded" in report["message"]
    assert "may have missed an interaction between parameters" in report["message"]


def test_an_unbounded_check_does_not_mention_the_bound():
    """The message is unchanged when the check was exhaustive."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    measured = _inert_param_grid_keys_measured(factory, INERT_GRID, data)
    assert not measured["bounded"]
    report = _inert_grid_report(factory, INERT_GRID, data)
    assert "bounded" not in report["message"]
    # The wording the artifacts and the console already carry.
    assert report["message"] == (
        "the parameter grid did not change the strategy's behaviour over the "
        "full sample for: lookback. The search over those parameters is a "
        "null experiment, not evidence. The strategy reads: fast_period, "
        "slow_period."
    )


def test_the_bound_is_a_bound_and_not_a_silent_truncation():
    """A small bound reproduces the first-value answer, and says so."""
    data = _interacting_data()
    # With one combination the check is the first-value rule, which accuses
    # both keys of the interacting grid.
    measured = _inert_param_grid_keys_measured(
        _interacting_factory, INTERACTING_GRID, data, max_combinations=1
    )
    assert measured["inert"] == ["mode", "threshold"]
    assert measured["bounded"] == ["mode", "threshold"]
    assert measured["max_combinations"] == 1

    report = _inert_grid_report(
        _interacting_factory, INTERACTING_GRID, data, max_combinations=1
    )
    assert report["inert_grid_params"] == ["mode", "threshold"]
    assert "bounded" in report["message"]
    # With the bound lifted, the same grid accuses nobody.
    measured = _inert_param_grid_keys_measured(
        _interacting_factory, INTERACTING_GRID, data
    )
    assert measured["inert"] == []
    assert measured["bounded"] == []


def test_a_bounded_check_that_finds_a_difference_never_accuses():
    """A difference proves liveness, so a bounded check cannot accuse."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")
    # `fast_period` changes the signals at the first combination, so no
    # bound can turn it into an inert key.
    measured = _inert_param_grid_keys_measured(
        factory, MEANINGFUL_GRID, data, max_combinations=1
    )
    assert "fast_period" not in measured["inert"]
    assert "fast_period" not in measured["bounded"]
    assert "slow_period" not in measured["inert"]


def test_the_report_keeps_its_keys():
    """The reporting surface is unchanged: the same three keys."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")
    report = _inert_grid_report(factory, INERT_GRID, data)
    assert set(report) == {"inert_grid_params", "strategy_parameters", "message"}


# ---------------------------------------------------------------------------
# The library paths
# ---------------------------------------------------------------------------

def test_walk_forward_analysis_records_the_inert_grid():
    """The walk-forward summary says which grid keys were never searched."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    results, stdout = _capture_stdout(
        walk_forward_analysis,
        data=data,
        strategy_factory=factory,
        param_grid=INERT_GRID,
    )
    summary = results["summary"]
    assert summary["inert_grid_params"] == ["lookback"]
    assert "lookback" in summary["inert_grid_message"]
    # The analysis function never prints: the CLI decides where the warning
    # goes, so it appears exactly once and next to the numbers it qualifies.
    assert "WARNING" not in stdout


def test_walk_forward_analysis_records_no_inert_grid_for_a_live_grid():
    """A meaningful grid is not reported as inert (no false positives)."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    results, _ = _capture_stdout(
        walk_forward_analysis,
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
    )
    assert results["summary"]["inert_grid_params"] == []
    assert results["summary"]["inert_grid_message"] is None


def test_cpcv_analysis_records_the_inert_grid():
    """The CPCV summary says which grid keys were never searched."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    results, stdout = _capture_stdout(
        cpcv_analysis,
        data=data,
        strategy_factory=factory,
        param_grid=INERT_GRID,
    )
    summary = results["summary"]
    assert summary["inert_grid_params"] == ["lookback"]
    assert "lookback" in summary["inert_grid_message"]
    assert "WARNING" not in stdout


def test_parameter_optimization_hands_the_inert_grid_to_the_caller():
    """The optimization measures the inert grid without printing it."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    report = {}
    results, stdout = _capture_stdout(
        parameter_optimization,
        data=data,
        strategy_factory=factory,
        param_grid=INERT_GRID,
        inert_grid_report=report,
    )
    assert report["inert_grid_params"] == ["lookback"]
    assert "lookback" in report["message"]
    # The function is silent: a cost sweep calls it once per coefficient and
    # must not repeat the warning.
    assert "WARNING" not in stdout
    # The measurement changes no number: the ranking is the one the search
    # produced, with the same sharpe and return.
    assert len(results) == 2
    assert results[0]["sharpe_ratio"] == results[1]["sharpe_ratio"]
    assert results[0]["total_return"] == results[1]["total_return"]


def test_parameter_optimization_is_unchanged_by_the_measurement():
    """Requesting the report does not change a single returned number."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    without, _ = _capture_stdout(
        parameter_optimization,
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
    )
    with_report, _ = _capture_stdout(
        parameter_optimization,
        data=data,
        strategy_factory=factory,
        param_grid=MEANINGFUL_GRID,
        inert_grid_report={},
    )
    assert without == with_report


def test_the_measurement_changes_no_number_in_the_walk_forward_summary():
    """Only the finding itself differs; every number is the same.

    The measurement is a measurement: with the inert-grid check replaced by
    one that finds nothing, the summary's returns, Sharpe, capacity and
    selection numbers must be identical, and the only keys that may differ
    are the two that carry the finding.
    """
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    with_finding, _ = _capture_stdout(
        walk_forward_analysis,
        data=data,
        strategy_factory=factory,
        param_grid=INERT_GRID,
    )
    original = walk_forward_module._inert_grid_report
    walk_forward_module._inert_grid_report = lambda *args, **kwargs: {
        "inert_grid_params": [],
        "strategy_parameters": [],
        "message": None,
    }
    try:
        without_finding, _ = _capture_stdout(
            walk_forward_analysis,
            data=data,
            strategy_factory=factory,
            param_grid=INERT_GRID,
        )
    finally:
        walk_forward_module._inert_grid_report = original

    measured = with_finding["summary"]
    blank = without_finding["summary"]
    assert measured["inert_grid_params"] == ["lookback"]
    assert blank["inert_grid_params"] == []
    differing = {
        key
        for key in set(measured) | set(blank)
        if measured.get(key) != blank.get(key)
    }
    assert differing <= {"inert_grid_params", "inert_grid_message"}, (
        f"the measurement moved a number: {sorted(differing)}"
    )
    # The selection itself is untouched: the same periods, the same
    # selections, the same out-of-sample numbers.
    assert measured["total_oos_return"] == blank["total_oos_return"]
    assert measured["oos_sharpe"] == blank["oos_sharpe"]
    assert measured["n_periods"] == blank["n_periods"]
    assert with_finding["best_params_per_period"] == without_finding["best_params_per_period"]
    assert len(with_finding["oos_returns"]) == len(without_finding["oos_returns"])
    for left, right in zip(with_finding["oos_returns"], without_finding["oos_returns"]):
        assert np.array_equal(np.asarray(left, dtype=float), np.asarray(right, dtype=float))


def test_out_of_sample_validation_records_the_inert_grid():
    """The out-of-sample summary keeps the finding (training split scope)."""
    data = _load_sample()
    factory = _make_strategy_factory("sma_crossover")

    results, stdout = _capture_stdout(
        out_of_sample_validation,
        data=data,
        strategy_factory=factory,
        param_grid=INERT_GRID,
        train_frac=0.5,
        val_frac=0.25,
        test_frac=0.25,
        validation_method="walk_forward",
    )
    summary = results["summary"]
    assert summary["inert_grid_params"] == ["lookback"]
    assert "training split" in summary["inert_grid_message"]
    assert "WARNING" not in stdout


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------

def test_optimize_cli_warns_next_to_the_ranking_and_records_it():
    """The ranking says, next to itself, that it ranked nothing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_cli(
            [
                "optimize",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(INERT_GRID),
                "--output", tmpdir,
            ]
        )
        assert result.returncode == 0, result.stderr[-3000:]
        # The warning is printed once, next to the ranking.
        assert result.stdout.count("WARNING: the parameter grid") == 1
        lines = result.stdout.splitlines()
        warning_idx = [
            i for i, line in enumerate(lines)
            if "WARNING: the parameter grid" in line
        ]
        ranking_idx = [i for i, line in enumerate(lines) if line.startswith("Rank")]
        assert warning_idx and ranking_idx, "the warning or the ranking is missing"
        # The warning follows the ranking table, so a reader meets it while
        # looking at the ranking it qualifies.
        assert warning_idx[0] > ranking_idx[0]
        # The finding is recorded next to the ranking artifact.
        record_path = Path(tmpdir) / "parameter_optimization_inert_grid.json"
        assert record_path.exists(), "the inert-grid record was not written"
        record = json.loads(record_path.read_text())
        assert record["inert_grid_params"] == ["lookback"]
        assert record["param_grid"] == INERT_GRID
        assert record["strategy"] == "sma_crossover"
        assert record["n_ranked_combinations"] == 2
        # The ranking artifact itself is unchanged (a plain ranked list).
        ranking = json.loads(
            (Path(tmpdir) / "parameter_optimization.json").read_text()
        )
        assert isinstance(ranking, list)
        assert ranking[0]["params"] == {"lookback": 5}
        assert ranking[0]["sharpe_ratio"] == ranking[1]["sharpe_ratio"]


def test_optimize_cli_does_not_warn_for_a_live_grid():
    """No false positive: a grid the strategy reads is never called inert."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_cli(
            [
                "optimize",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(MEANINGFUL_GRID),
                "--output", tmpdir,
            ]
        )
        assert result.returncode == 0, result.stderr[-3000:]
        assert "WARNING: the parameter grid" not in result.stdout
        record = json.loads(
            (Path(tmpdir) / "parameter_optimization_inert_grid.json").read_text()
        )
        assert record["inert_grid_params"] == []
        assert record["inert_grid_message"] is None


def test_walk_forward_cli_warns_and_records_the_inert_grid():
    """The walk-forward console and artifact agree."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_cli(
            [
                "walk-forward",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(INERT_GRID),
                "--output", tmpdir,
            ]
        )
        assert result.returncode == 0, result.stderr[-3000:]
        assert result.stdout.count("WARNING: the parameter grid") == 1
        artifact = json.loads(
            (Path(tmpdir) / "walk_forward_summary.json").read_text()
        )
        assert artifact["summary"]["inert_grid_params"] == ["lookback"]
        assert "lookback" in artifact["summary"]["inert_grid_message"]


def test_cpcv_cli_warns_and_records_the_inert_grid():
    """The CPCV console and artifact agree."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_cli(
            [
                "cpcv",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(INERT_GRID),
                "--output", tmpdir,
            ]
        )
        assert result.returncode == 0, result.stderr[-3000:]
        assert result.stdout.count("WARNING: the parameter grid") == 1
        artifact = json.loads((Path(tmpdir) / "cpcv_summary.json").read_text())
        assert artifact["summary"]["inert_grid_params"] == ["lookback"]
        assert "lookback" in artifact["summary"]["inert_grid_message"]


def test_out_of_sample_cli_prints_the_warning_once():
    """The warning is printed by the CLI only, so it never repeats."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_cli(
            [
                "out-of-sample",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--validation-method", "walk_forward",
                "--train-frac", "0.5",
                "--val-frac", "0.25",
                "--test-frac", "0.25",
                "--param-grid", json.dumps(INERT_GRID),
                "--output", tmpdir,
            ]
        )
        assert result.returncode == 0, result.stderr[-3000:]
        assert result.stdout.count("WARNING: the parameter grid") == 1
        artifact = json.loads(
            (Path(tmpdir) / "out_of_sample_summary.json").read_text()
        )
        assert artifact["summary"]["inert_grid_params"] == ["lookback"]


def test_the_sweep_artifacts_record_the_inert_grid():
    """A cost sweep records the finding too, not only the single run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_cli(
            [
                "optimize",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--param-grid", json.dumps(INERT_GRID),
                "--impact-coefficients", "0.0", "0.0001",
                "--output", tmpdir,
            ]
        )
        assert result.returncode == 0, result.stderr[-3000:]
        sweep = json.loads(
            (Path(tmpdir) / "parameter_optimization_impact_sweep.json").read_text()
        )
        assert sweep["results"], "the sweep artifact has no rows"
        for row in sweep["results"]:
            assert row["inert_grid_params"] == ["lookback"]


# ---------------------------------------------------------------------------
# Test registry
# ---------------------------------------------------------------------------

TEST_REGISTRY = [
    ("test_inert_grid_report_flags_a_key_the_strategy_ignores",
     test_inert_grid_report_flags_a_key_the_strategy_ignores),
    ("test_inert_grid_report_does_not_flag_a_live_key",
     test_inert_grid_report_does_not_flag_a_live_key),
    ("test_inert_grid_report_flags_only_the_inert_key_of_a_mixed_grid",
     test_inert_grid_report_flags_only_the_inert_key_of_a_mixed_grid),
    ("test_inert_grid_report_agrees_with_the_key_detector",
     test_inert_grid_report_agrees_with_the_key_detector),
    ("test_the_interacting_grid_really_interacts",
     test_the_interacting_grid_really_interacts),
    ("test_the_first_value_rule_would_have_accused_both_keys",
     test_the_first_value_rule_would_have_accused_both_keys),
    ("test_a_key_that_matters_only_in_combination_is_not_accused",
     test_a_key_that_matters_only_in_combination_is_not_accused),
    ("test_a_key_that_is_inert_in_every_combination_is_still_accused",
     test_a_key_that_is_inert_in_every_combination_is_still_accused),
    ("test_the_shipped_strategies_keep_their_inert_verdicts",
     test_the_shipped_strategies_keep_their_inert_verdicts),
    ("test_a_bounded_check_says_so_in_the_message",
     test_a_bounded_check_says_so_in_the_message),
    ("test_an_unbounded_check_does_not_mention_the_bound",
     test_an_unbounded_check_does_not_mention_the_bound),
    ("test_the_bound_is_a_bound_and_not_a_silent_truncation",
     test_the_bound_is_a_bound_and_not_a_silent_truncation),
    ("test_a_bounded_check_that_finds_a_difference_never_accuses",
     test_a_bounded_check_that_finds_a_difference_never_accuses),
    ("test_the_report_keeps_its_keys",
     test_the_report_keeps_its_keys),
    ("test_walk_forward_analysis_records_the_inert_grid",
     test_walk_forward_analysis_records_the_inert_grid),
    ("test_walk_forward_analysis_records_no_inert_grid_for_a_live_grid",
     test_walk_forward_analysis_records_no_inert_grid_for_a_live_grid),
    ("test_cpcv_analysis_records_the_inert_grid",
     test_cpcv_analysis_records_the_inert_grid),
    ("test_parameter_optimization_hands_the_inert_grid_to_the_caller",
     test_parameter_optimization_hands_the_inert_grid_to_the_caller),
    ("test_parameter_optimization_is_unchanged_by_the_measurement",
     test_parameter_optimization_is_unchanged_by_the_measurement),
    ("test_the_measurement_changes_no_number_in_the_walk_forward_summary",
     test_the_measurement_changes_no_number_in_the_walk_forward_summary),
    ("test_out_of_sample_validation_records_the_inert_grid",
     test_out_of_sample_validation_records_the_inert_grid),
    ("test_optimize_cli_warns_next_to_the_ranking_and_records_it",
     test_optimize_cli_warns_next_to_the_ranking_and_records_it),
    ("test_optimize_cli_does_not_warn_for_a_live_grid",
     test_optimize_cli_does_not_warn_for_a_live_grid),
    ("test_walk_forward_cli_warns_and_records_the_inert_grid",
     test_walk_forward_cli_warns_and_records_the_inert_grid),
    ("test_cpcv_cli_warns_and_records_the_inert_grid",
     test_cpcv_cli_warns_and_records_the_inert_grid),
    ("test_out_of_sample_cli_prints_the_warning_once",
     test_out_of_sample_cli_prints_the_warning_once),
    ("test_the_sweep_artifacts_record_the_inert_grid",
     test_the_sweep_artifacts_record_the_inert_grid),
]


def main() -> int:
    failures = 0
    for name, fn in TEST_REGISTRY:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {name}: {e}")
            traceback.print_exc()

    print(f"\n{len(TEST_REGISTRY) - failures}/{len(TEST_REGISTRY)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
