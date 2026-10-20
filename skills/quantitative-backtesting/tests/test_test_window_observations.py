#!/usr/bin/env python3
"""
Parity harness for the `test_n_periods` -> `test_n_observations` rename.

The held-out window used to be reported under the name `test_n_periods`
while its value was the number of return OBSERVATIONS in that window
(`len(test_returns)`).  "100" daily bars are not 100 independent periods,
and the resolution arithmetic (minimum detectable Sharpe / alpha) needs the
observation count, so the name was the thing that was wrong.  The rename is
a breaking API change, so it needs a harness that proves three things:

  1. the key is renamed EVERYWHERE it is produced or read -- no production
     code emits or consumes `test_n_periods` any more, so nothing can break
     silently on a stale read;
  2. the rename moved nothing but the key NAME -- every other metric of the
     held-out window, and the whole test return series, are bit-identical to
     the pre-rename output (pinned in
     `tests/fixtures/test_performance_pre_rename_baseline.json`, captured
     from the pre-rename source);
  3. the neighbouring, CORRECTLY named period count was not touched --
     `validation_results["summary"]["n_periods"]` still counts walk-forward
     periods, and the walk-forward report row still reads `n_periods`.  An
     over-broad rename would have been just as wrong as no rename.

The baseline fixture was captured from commit
6074e3b4ac9a6591e5694c8a1dd8d4f0c8989e21 with this recipe:

    git show 6074e3b:skills/quantitative-backtesting/scripts/walk_forward.py \
        > /tmp/walk_forward_pre_rename.py
    # load it with importlib and call out_of_sample_validation() with the
    # same data / grid / split recorded in the fixture's "provenance" block.

Run with: python3 skills/quantitative-backtesting/tests/test_test_window_observations.py
No third-party test framework is required; uses only the standard library.
"""

import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import (  # noqa: E402
    _make_strategy_factory,
    out_of_sample_validation,
)

SAMPLE_DATA = SKILLS_DIR / "assets" / "example_data" / "sample_ohlcv.csv"
WALK_FORWARD_CLI = SKILLS_DIR / "scripts" / "walk_forward.py"
BASELINE = (
    SKILLS_DIR / "tests" / "fixtures" / "test_performance_pre_rename_baseline.json"
)

PARAM_GRID = {"fast_period": [5, 10], "slow_period": [20, 30]}


def _load_sample() -> pd.DataFrame:
    return pd.read_csv(SAMPLE_DATA, parse_dates=["date"]).set_index("date")


def _run_validation() -> dict:
    """The shipped 0.6/0.2/0.2 split on the shipped sample data."""
    return out_of_sample_validation(
        data=_load_sample(),
        strategy_factory=_make_strategy_factory("sma_crossover"),
        param_grid=PARAM_GRID,
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        validation_method="walk_forward",
        walk_forward_train_months=6,
        walk_forward_test_months=2,
        walk_forward_step_months=2,
        apply_deflation=True,
    )


def _baseline() -> dict:
    return json.loads(BASELINE.read_text())


def test_the_framework_reports_the_held_out_window_in_observations():
    """The held-out window is reported as observations, and the old key is
    gone: a consumer that still reads `test_n_periods` must fail loudly
    rather than silently receive None."""
    results = _run_validation()
    test_performance = results["test_performance"]

    assert "test_n_observations" in test_performance, (
        "the framework no longer reports the held-out window at all"
    )
    assert "test_n_periods" not in test_performance, (
        "the mislabelled key is still emitted: the rename is not complete"
    )
    # The break is explicit, not silent.
    try:
        test_performance["test_n_periods"]
    except KeyError:
        pass
    else:
        raise AssertionError(
            "reading the old key must raise KeyError, not return a value"
        )


def test_the_observation_count_is_the_number_of_return_observations():
    """The count is the number of return observations the statistics were
    computed on (`len(test_returns)`), which is what the resolution
    arithmetic needs.

    It is NOT the number of rows in the held-out window: the window's warmup
    rows produce no return, so the observation count is smaller than the
    window size.  Reporting the row count instead would overstate the
    resolution of the test."""
    results = _run_validation()
    test_performance = results["test_performance"]
    split = results["train_val_test_split"]

    observations = test_performance["test_n_observations"]
    assert observations == len(test_performance["test_returns"]), (
        "the observation count must be the number of return observations the "
        "test statistics were computed on"
    )
    assert observations == 100, (
        f"the shipped sample's held-out window changed size: {observations}"
    )
    assert observations <= split["test_size"], (
        "there cannot be more return observations than rows in the window"
    )
    # The warmup rows are what make the two differ; pin that they do, so a
    # future change that silently swaps the window size for the observation
    # count is caught here.
    assert observations < split["test_size"], (
        "the warmup rows no longer separate the window size from the "
        "observation count; re-check what this key means"
    )
    # The walk-forward PERIOD count is a different quantity from the held-out
    # observation count; the two must never be conflated.
    walk_periods = results["validation_results"]["summary"]["n_periods"]
    assert walk_periods != observations, (
        "the walk-forward period count and the held-out observation count "
        "must be different quantities"
    )


def test_the_rename_moved_no_metric_and_no_verdict():
    """The rename is a key rename and nothing else: every other metric of the
    held-out window, and the whole test return series, are identical to the
    pre-rename output."""
    baseline = _baseline()
    results = _run_validation()
    test_performance = results["test_performance"]

    expected = dict(baseline["test_performance"])
    old_count = expected.pop("test_n_periods")

    # Same key set, modulo the rename.
    current_keys = set(test_performance) - {"test_n_observations", "test_returns"}
    assert set(expected) == current_keys, (
        "the rename added or removed a key beyond the rename itself"
    )
    # Same value for the renamed key.
    assert test_performance["test_n_observations"] == old_count, (
        "the renamed key carries a different number than before the rename"
    )
    # Same values for everything else.
    for key, value in expected.items():
        assert test_performance[key] == value, (
            f"the rename changed the value of `{key}`"
        )
    # Same returns, element by element.
    baseline_returns = baseline["test_returns"]
    current_returns = [float(x) for x in test_performance["test_returns"]]
    assert current_returns == baseline_returns, (
        "the rename changed the held-out return series"
    )
    # ...and the summary metrics that are computed from it.
    summary = results["summary"]
    assert summary["test_sharpe"] == 0.8808669371583469
    assert summary["test_total_return"] == 0.06344946287138331
    assert summary["test_volatility"] == 0.16945885429210353


def test_no_production_code_reads_or_emits_the_old_key():
    """No production code emits or reads `test_n_periods` any more: the
    rename is complete across the framework and the worked example, so
    nothing can keep a stale read alive."""
    pattern = re.compile(r"""["']test_n_periods["']""")
    offenders = []
    for path in sorted((SKILLS_DIR / "scripts").glob("*.py")) + sorted(
        (SKILLS_DIR / "examples").glob("*.py")
    ):
        for lineno, line in enumerate(
            path.read_text().splitlines(), start=1
        ):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(SKILLS_DIR)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "the old key is still used in production code:\n" + "\n".join(offenders)
    )


def test_the_walk_forward_period_count_is_still_counted_in_periods():
    """The neighbouring count was NOT renamed: the walk-forward PERIOD count
    is a different quantity and keeps its (correct) name, so the two counts
    cannot be confused with each other."""
    results = _run_validation()
    periods = results["validation_results"]["periods"]
    walk_summary = results["validation_results"]["summary"]

    assert "n_periods" in walk_summary, (
        "the walk-forward period count was renamed or dropped"
    )
    assert walk_summary["n_periods"] == len(periods), (
        "the walk-forward period count no longer counts the periods"
    )

    # ...and the walk-forward report row still reads that key.
    reporting = (SKILLS_DIR / "scripts" / "reporting.py").read_text()
    assert '("Number of Periods", "n_periods"' in reporting, (
        "the walk-forward report row no longer reads the `n_periods` summary key"
    )


def test_the_json_artifact_reports_the_observation_count():
    """The saved artifact carries the renamed key too: the CLI writes a
    re-projected `test_performance` block, and that projection must not keep
    the old name."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [
                sys.executable,
                str(WALK_FORWARD_CLI),
                "out-of-sample",
                "--data", str(SAMPLE_DATA),
                "--strategy", "sma_crossover",
                "--validation-method", "walk_forward",
                "--train-frac", "0.6",
                "--val-frac", "0.2",
                "--test-frac", "0.2",
                "--param-grid", json.dumps(PARAM_GRID),
                "--output", tmpdir,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        assert result.returncode == 0, (
            f"out-of-sample CLI exited {result.returncode}\n"
            f"stdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
        )
        artifact = json.loads(
            (Path(tmpdir) / "out_of_sample_summary.json").read_text()
        )

    test_performance = artifact["test_performance"]
    assert "test_n_observations" in test_performance, (
        "the saved artifact does not carry the renamed key"
    )
    assert "test_n_periods" not in test_performance, (
        "the saved artifact still carries the old key"
    )
    # The artifact and the programmatic API report the same number.
    assert test_performance["test_n_observations"] == 100


def test_the_example_reports_the_same_number_under_the_same_name():
    """End-to-end parity: the worked example, the programmatic API and the
    saved artifact all report the held-out window under the same name and
    with the same number, so the count cannot be read as a period count by
    one path and an observation count by another."""
    sys.path.insert(0, str(SKILLS_DIR / "examples"))
    from falsifiable_hypothesis_example import run_hypothesis_test

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = run_hypothesis_test(str(SAMPLE_DATA))

    observed = result["observed"]
    assert observed["test_n_observations"] == 100, (
        "the example no longer reports 100 held-out observations"
    )
    assert "test_n_periods" not in observed, (
        "the example still reports the old key name"
    )
    assert observed["test_n_observations"] == _run_validation()[
        "test_performance"
    ]["test_n_observations"]


def main() -> int:
    tests = TEST_REGISTRY
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return 1 if failures else 0


TEST_REGISTRY = [
    ("test_the_framework_reports_the_held_out_window_in_observations",
     test_the_framework_reports_the_held_out_window_in_observations),
    ("test_the_observation_count_is_the_number_of_return_observations",
     test_the_observation_count_is_the_number_of_return_observations),
    ("test_the_rename_moved_no_metric_and_no_verdict",
     test_the_rename_moved_no_metric_and_no_verdict),
    ("test_no_production_code_reads_or_emits_the_old_key",
     test_no_production_code_reads_or_emits_the_old_key),
    ("test_the_walk_forward_period_count_is_still_counted_in_periods",
     test_the_walk_forward_period_count_is_still_counted_in_periods),
    ("test_the_json_artifact_reports_the_observation_count",
     test_the_json_artifact_reports_the_observation_count),
    ("test_the_example_reports_the_same_number_under_the_same_name",
     test_the_example_reports_the_same_number_under_the_same_name),
]


if __name__ == "__main__":
    sys.exit(main())
