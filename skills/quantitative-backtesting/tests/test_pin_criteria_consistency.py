#!/usr/bin/env python3
"""Static guard: pinned benchmark-aware criteria must follow from pinned metrics.

WHY THIS EXISTS
---------------
The benchmark-aware falsification tests pin two things:

* ``EXPECTED`` -- the measured out-of-sample metrics (Sharpe, total return,
  benchmark return, Deflated Sharpe p-value, benchmark-alpha p-value); and
* ``expected_criteria`` -- the boolean verdict of each pre-registered
  falsification criterion.

The two are redundant: every criterion is a threshold comparison of a metric
in ``EXPECTED`` (``oos_sharpe > 0``, ``total_return > benchmark_total_return``,
``deflated_sharpe_pvalue < 0.10``, ``benchmark_alpha_pvalue < 0.05``). A test
therefore contradicts itself when a metric pin is refreshed but the criterion
boolean is not -- for example a pinned ``oos_sharpe = +0.695`` next to
``"oos_sharpe_gt_zero": False``. That is exactly the class of stale pin that
had to be reconciled by hand after ``regenerate_pins.py`` re-based the metric
dicts (it deliberately does not touch verdict criteria). The test suite then
asserts a verdict that its own pinned evidence refutes, which is worse than a
missing guard: it looks like a regression test while enforcing the wrong
outcome.

This module parses the AST of every ``test_*benchmark_aware*.py`` file (no
imports, no backtests, standard library only) and checks the redundant pair
against each other. It is a *consistency* guard, not a profitability claim: it
never decides whether a strategy is good, only whether the pinned verdict is
the one the pinned numbers imply.

SCOPE
-----
The guard checks files that pin an ``EXPECTED`` metrics dict together with
either an ``expected_criteria`` booleans dict (benchmark-aware style) or
runtime ``assert passes["NAME"] is <bool>`` / ``assert criteria["NAME"] is
<bool>`` statements (walk-forward / CPCV style). For every asserted criterion
it derives the boolean from the pinned metrics
(``oos_sharpe > 0``, ``total_oos_return > 0``,
``total_return > benchmark_total_return``, ``deflated_sharpe_pvalue < 0.10``,
``benchmark_alpha_pvalue < 0.05``) and fails on mismatch. Criteria whose
metric is absent from ``EXPECTED`` (e.g. a Deflated Sharpe p-value pinned only
inline) are skipped with a recorded reason rather than guessed at.

Files that pin metrics inline without an ``EXPECTED`` literal are reported as
skipped; the ``test_guard_covers_expected_number_of_files`` check fails if the
statically checkable set ever shrinks below a floor, so the guard cannot
silently become vacuous as tests are added or refactored.

Run with: python3 skills/quantitative-backtesting/tests/test_pin_criteria_consistency.py
No third-party test framework is required; uses only the standard library.
"""

import ast
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
TESTS_DIR = SKILLS_DIR / "tests"
BENCHMARK_AWARE_GLOB = "test_*benchmark_aware*.py"

# The guard must keep covering a meaningful number of files. If a refactor
# moves the benchmark-aware tests off the ``EXPECTED`` + ``expected_criteria``
# pattern, this floor forces the guard to be updated rather than silently
# passing on zero files.
MIN_CHECKABLE_FILES = 15


def _first(mapping, *keys):
    """Return the first present key's value, else None."""
    for key in keys:
        if key in mapping:
            return mapping[key]
    return None


def derive_criteria(metrics):
    """Derive the four benchmark-aware criterion booleans from pinned metrics.

    Returns a dict with only the criteria whose inputs are present. The key
    aliases (``sharpe_ratio`` / ``oos_sharpe``, ``total_return`` /
    ``total_oos_return``, ``benchmark_alpha_pvalue`` / ``alpha_pvalue``)
    cover both the single-backtest and walk-forward/CPCV pin conventions.

    This mirrors the threshold definitions used by the hypothesis runners and
    the walk-forward/CPCV summaries; it is intentionally the only place the
    thresholds are restated for the guard.
    """
    derived = {}

    sharpe = _first(metrics, "sharpe_ratio", "oos_sharpe")
    if sharpe is not None:
        derived["oos_sharpe_gt_zero"] = bool(sharpe > 0.0)

    total_return = _first(metrics, "total_return", "total_oos_return")
    if total_return is not None:
        derived["oos_total_return_positive"] = bool(total_return > 0.0)
    benchmark_return = metrics.get("benchmark_total_return")
    if total_return is not None and benchmark_return is not None:
        derived["oos_total_return_gt_benchmark"] = bool(
            total_return > benchmark_return
        )

    dsr_pvalue = metrics.get("deflated_sharpe_pvalue")
    if dsr_pvalue is not None:
        derived["deflated_sharpe_pvalue_lt_0.10"] = bool(dsr_pvalue < 0.10)

    alpha_pvalue = _first(metrics, "benchmark_alpha_pvalue", "alpha_pvalue")
    if alpha_pvalue is not None:
        derived["benchmark_alpha_pvalue_lt_0.05"] = bool(alpha_pvalue < 0.05)

    return derived


KNOWN_CRITERIA = frozenset(
    {
        "oos_sharpe_gt_zero",
        "oos_total_return_gt_benchmark",
        "oos_total_return_positive",
        "deflated_sharpe_pvalue_lt_0.10",
        "benchmark_alpha_pvalue_lt_0.05",
    }
)


def _dict_assignments(tree):
    """Collect top-level/local ``NAME = { ... }`` literal dicts by name.

    Only literal dicts are returned; a dynamically built dict is ignored so
    the guard never guesses at a value it cannot see.
    """
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id not in ("EXPECTED", "expected_criteria"):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            continue
        if isinstance(value, dict) and target.id not in found:
            found[target.id] = value
    return found


def _runtime_asserts(tree):
    """Collect ``(name, asserted_bool)`` from ``assert passes["NAME"] is <bool>``
    and ``assert criteria["NAME"] is <bool>`` statements.

    Walk-forward and CPCV tests build the criteria dict at runtime from the
    backtest summary and assert each boolean individually rather than pinning
    an ``expected_criteria`` dict. The asserted boolean is comparable to the
    value derived from the pinned ``EXPECTED`` metrics.
    """
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        test = node.test
        if not isinstance(test, ast.Compare) or len(test.ops) != 1:
            continue
        if not isinstance(test.ops[0], ast.Is):
            continue
        if len(test.comparators) != 1:
            continue
        left = test.left
        if not isinstance(left, ast.Subscript):
            continue
        if not isinstance(left.value, ast.Name) or left.value.id not in (
            "passes",
            "criteria",
        ):
            continue
        if not isinstance(left.slice, ast.Constant) or not isinstance(
            left.slice.value, str
        ):
            continue
        comp = test.comparators[0]
        if not isinstance(comp, ast.Constant) or not isinstance(comp.value, bool):
            continue
        found.append((left.slice.value, comp.value))
    return found


def check_file(path):
    """Return ``(problems, skips)`` for one test file.

    ``problems`` are inconsistencies that must fail the guard. ``skips`` are
    criteria asserted at runtime whose metric is absent from ``EXPECTED``;
    they are recorded but not failed, since the guard must not guess at a
    value it cannot see. An empty problem list means either the file is
    consistent or it is not statically checkable.
    """
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except SyntaxError as exc:  # pragma: no cover - defensive
        return [f"{path}: could not parse: {exc}"], []

    dicts = _dict_assignments(tree)
    metrics = dicts.get("EXPECTED")
    criteria = dicts.get("expected_criteria")
    derived = derive_criteria(metrics) if metrics else {}
    problems = []
    skips = []

    if metrics is None:
        # Metrics are pinned inline or asserted at runtime without an
        # EXPECTED literal: nothing to derive criteria from, so skip.
        return [], []

    for name, pinned in (criteria or {}).items():
        if name not in KNOWN_CRITERIA:
            problems.append(
                f"{Path(path).name}: criterion {name!r} is not covered by this "
                f"guard; add it to derive_criteria if it is a real threshold"
            )
            continue
        if name not in derived:
            problems.append(
                f"{Path(path).name}: criterion {name!r} is pinned but its "
                f"metric is absent from EXPECTED"
            )
            continue
        if bool(pinned) != bool(derived[name]):
            problems.append(
                f"{Path(path).name}: criterion {name!r} pinned {pinned} but "
                f"EXPECTED metrics imply {derived[name]}"
            )

    for name, asserted in _runtime_asserts(tree):
        if name not in KNOWN_CRITERIA:
            problems.append(
                f"{Path(path).name}: runtime criterion {name!r} is not covered "
                f"by this guard; add it to derive_criteria if it is a real "
                f"threshold"
            )
            continue
        if metrics is None or name not in derived:
            skips.append(
                f"{Path(path).name}: runtime criterion {name!r} asserted "
                f"{asserted} but its metric is absent from EXPECTED; skipped"
            )
            continue
        if bool(asserted) != bool(derived[name]):
            problems.append(
                f"{Path(path).name}: runtime criterion {name!r} asserted "
                f"{asserted} but EXPECTED metrics imply {derived[name]}"
            )
    return problems, skips


def classify_file(path):
    """Return ``(checkable, problems, skips)`` for one test file.

    A file is checkable when it pins an ``EXPECTED`` metrics dict and either
    an ``expected_criteria`` dict or runtime ``passes``/``criteria`` asserts
    that the guard can derive criteria from.
    """
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except SyntaxError as exc:  # pragma: no cover - defensive
        return False, [f"{path}: could not parse: {exc}"], []
    dicts = _dict_assignments(tree)
    metrics = dicts.get("EXPECTED")
    criteria = dicts.get("expected_criteria")
    runtime_asserts = _runtime_asserts(tree)
    checkable = bool(metrics) and (bool(criteria) or bool(runtime_asserts))
    problems, skips = check_file(path) if checkable else ([], [])
    return checkable, problems, skips


def benchmark_aware_files():
    return sorted(TESTS_DIR.glob(BENCHMARK_AWARE_GLOB))


def test_guard_covers_expected_number_of_files():
    """The guard must keep covering a meaningful, non-zero set of files."""
    files = benchmark_aware_files()
    assert files, "no benchmark-aware test files found"
    checkable = [f for f in files if classify_file(f)[0]]
    assert len(checkable) >= MIN_CHECKABLE_FILES, (
        f"only {len(checkable)} benchmark-aware files pin both EXPECTED and "
        f"expected_criteria; the guard covers too little to be meaningful "
        f"(floor {MIN_CHECKABLE_FILES})"
    )


def test_every_pinned_criterion_matches_its_pinned_metrics():
    """No benchmark-aware test may pin a verdict its own metrics contradict."""
    problems = []
    for path in benchmark_aware_files():
        file_problems, _ = check_file(path)
        problems.extend(file_problems)
    assert not problems, (
        "pinned criteria contradict pinned metrics:\n  " + "\n  ".join(problems)
    )


def test_derive_criteria_covers_the_known_set():
    """The derivation and the known-criterion set must stay in lockstep.

    If a new threshold is added to ``derive_criteria`` but not to
    ``KNOWN_CRITERIA`` (or vice versa), the guard would either reject a real
    criterion or silently ignore one. This pins the coupling.
    """
    full_metrics = {
        "sharpe_ratio": 1.0,
        "total_return": 1.0,
        "benchmark_total_return": 0.0,
        "deflated_sharpe_pvalue": 1.0,
        "benchmark_alpha_pvalue": 1.0,
    }
    assert set(derive_criteria(full_metrics)) == set(KNOWN_CRITERIA)


def test_guard_detects_an_injected_inconsistency():
    """The guard must fail on the exact historical bug shape.

    A pinned positive Sharpe next to ``oos_sharpe_gt_zero: False`` is the
    contradiction that motivated this guard. A consistent pair must produce no
    problems, so the guard is not simply always failing.
    """
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "test_injected_bad.py"
        bad.write_text(
            "def test_x():\n"
            "    expected_criteria = {\n"
            "        'oos_sharpe_gt_zero': False,\n"
            "        'oos_total_return_gt_benchmark': False,\n"
            "        'deflated_sharpe_pvalue_lt_0.10': False,\n"
            "        'benchmark_alpha_pvalue_lt_0.05': False,\n"
            "    }\n"
            "    EXPECTED = {\n"
            "        'sharpe_ratio': 0.695,\n"
            "        'total_return': 0.10,\n"
            "        'benchmark_total_return': 0.20,\n"
            "        'deflated_sharpe_pvalue': 0.5,\n"
            "        'benchmark_alpha_pvalue': 0.5,\n"
            "    }\n",
            encoding="utf-8",
        )
        bad_problems, _ = check_file(bad)
        assert bad_problems, "guard failed to flag an injected contradiction"
        assert any("oos_sharpe_gt_zero" in p for p in bad_problems), (
            f"guard flagged the wrong criterion: {bad_problems}"
        )

        good = Path(td) / "test_injected_good.py"
        good.write_text(
            "def test_x():\n"
            "    expected_criteria = {\n"
            "        'oos_sharpe_gt_zero': True,\n"
            "        'oos_total_return_gt_benchmark': False,\n"
            "        'deflated_sharpe_pvalue_lt_0.10': False,\n"
            "        'benchmark_alpha_pvalue_lt_0.05': False,\n"
            "    }\n"
            "    EXPECTED = {\n"
            "        'sharpe_ratio': 0.695,\n"
            "        'total_return': 0.10,\n"
            "        'benchmark_total_return': 0.20,\n"
            "        'deflated_sharpe_pvalue': 0.5,\n"
            "        'benchmark_alpha_pvalue': 0.5,\n"
            "    }\n",
            encoding="utf-8",
        )
        assert check_file(good) == ([], []), "guard flagged a consistent pair"


def test_guard_detects_injected_runtime_inconsistency():
    """The guard must flag an asserted runtime boolean that EXPECTED refutes.

    Mirrors the historical bug shape for the ``passes["..."] is <bool>``
    pattern used by walk-forward / CPCV tests.
    """
    with tempfile.TemporaryDirectory() as td:
        bad = Path(td) / "test_injected_bad_runtime.py"
        bad.write_text(
            "def test_x():\n"
            "    EXPECTED = {\n"
            "        'oos_sharpe': 0.695,\n"
            "        'total_oos_return': 0.10,\n"
            "    }\n"
            "    passes = {\n"
            "        'oos_sharpe_gt_zero': bool(False),\n"
            "        'oos_total_return_positive': bool(True),\n"
            "    }\n"
            "    assert passes['oos_sharpe_gt_zero'] is False\n"
            "    assert passes['oos_total_return_positive'] is True\n",
            encoding="utf-8",
        )
        bad_problems, _ = check_file(bad)
        assert bad_problems, "guard failed to flag an injected runtime contradiction"
        assert any("oos_sharpe_gt_zero" in p for p in bad_problems), (
            f"guard flagged the wrong criterion: {bad_problems}"
        )

        good = Path(td) / "test_injected_good_runtime.py"
        good.write_text(
            "def test_x():\n"
            "    EXPECTED = {\n"
            "        'oos_sharpe': 0.695,\n"
            "        'total_oos_return': 0.10,\n"
            "    }\n"
            "    passes = {\n"
            "        'oos_sharpe_gt_zero': bool(True),\n"
            "        'oos_total_return_positive': bool(True),\n"
            "    }\n"
            "    assert passes['oos_sharpe_gt_zero'] is True\n"
            "    assert passes['oos_total_return_positive'] is True\n",
            encoding="utf-8",
        )
        assert check_file(good) == ([], []), "guard flagged a consistent runtime pair"


def _coverage_counts():
    """Return (benchmark_aware_files, checkable, skips, runtime_only_checkable)."""
    files = benchmark_aware_files()
    checkable = 0
    skips = 0
    runtime_only = 0
    for path in files:
        checkable_flag, problems, file_skips = classify_file(path)
        if checkable_flag:
            checkable += 1
            skips += len(file_skips)
            dicts = _dict_assignments(ast.parse(path.read_text(encoding="utf-8")))
            if "expected_criteria" not in dicts and _runtime_asserts(
                ast.parse(path.read_text(encoding="utf-8"))
            ):
                runtime_only += 1
    return files, checkable, skips, runtime_only


def main() -> int:
    failures = 0
    for name, fn in (
        ("test_guard_covers_expected_number_of_files",
         test_guard_covers_expected_number_of_files),
        ("test_every_pinned_criterion_matches_its_pinned_metrics",
         test_every_pinned_criterion_matches_its_pinned_metrics),
        ("test_derive_criteria_covers_the_known_set",
         test_derive_criteria_covers_the_known_set),
        ("test_guard_detects_an_injected_inconsistency",
         test_guard_detects_an_injected_inconsistency),
        ("test_guard_detects_injected_runtime_inconsistency",
         test_guard_detects_injected_runtime_inconsistency),
    ):
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as exc:  # noqa: BLE001 - standalone runner reports all
            failures += 1
            print(f"FAIL  {name}: {exc}")
    files, checkable, skips, runtime_only = _coverage_counts()
    total = len(files)
    print(
        f"\nstatic pin/criteria guard: {checkable}/{total} benchmark-aware files "
        f"checkable ({runtime_only} via the runtime ``passes``/``criteria`` "
        f"pattern), {skips} runtime criteria skipped (metric absent from "
        f"EXPECTED)"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())