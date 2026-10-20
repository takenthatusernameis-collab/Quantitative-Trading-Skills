#!/usr/bin/env python3
"""Regression test for the pinned panel book-pricing reference.

Pins the panel/book/impact/capacity numbers produced by
``walk_forward_analysis`` on the committed multi-asset fixture
(``assets/example_data/sample_panel_ohlcv.csv``) under
``--panel-pricing book`` with ``impact_coefficient > 0``.

The numbers are written as literals (and mirrored in
``examples/example_panel_output/panel_reference.json``) on purpose: the test
pins what the framework *does*, so a silent change to the pricing/cost model
is caught here instead of being silently mirrored by the assertions.

Run with: python3 skills/quantitative-backtesting/tests/test_panel_reference_pinned.py
"""

import json
import sys
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from data_loader import load_multi_symbol  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402
from walk_forward import walk_forward_analysis  # noqa: E402

DATA_PATH = SKILLS_DIR / "assets" / "example_data" / "sample_panel_ohlcv.csv"
REFERENCE_PATH = SKILLS_DIR / "examples" / "example_panel_output" / "panel_reference.json"

PARAM_GRID = {"lookback": [20], "top_quantile": [0.4], "bottom_quantile": [0.2]}

# Convention used to produce the reference artifact, written as literals.
IMPACT_COEFFICIENT = 1.0
COMMISSION = 0.0002
SLIPPAGE = 0.0001
INITIAL_CAPITAL = 100000
ADV_WINDOW = 20
TRAIN_MONTHS = 8
TEST_MONTHS = 3
STEP_MONTHS = 3


def _load_reference():
    with open(REFERENCE_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _run_panel():
    data = load_multi_symbol(DATA_PATH)
    factory = lambda params: build_strategy(
        "cross_sectional_momentum", json.dumps(params)
    )
    return walk_forward_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=PARAM_GRID,
        train_months=TRAIN_MONTHS,
        test_months=TEST_MONTHS,
        step_months=STEP_MONTHS,
        initial_capital=INITIAL_CAPITAL,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        impact_coefficient=IMPACT_COEFFICIENT,
        adv_window=ADV_WINDOW,
        panel_pricing="book",
        impact_aggregation="panel",
    )


def _close(a, b, rel_tol, abs_tol):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= abs_tol + rel_tol * abs(b)


def test_panel_reference_impact_numbers_are_not_null():
    """With impact_coefficient > 0 the book diagnostic must report real
    impact and capacity figures, not nulls."""
    res = _run_panel()
    diag = res["summary"].get("book_diagnostic")
    assert diag is not None, "book_diagnostic must be present for a panel book run"
    for key in (
        "impact_charged_bps",
        "impact_traded_only_bps",
        "impact_dilution_bps",
        "impact_participation_ratio",
    ):
        assert diag.get(key) is not None, f"{key} must not be null with impact enabled"
    assert res["summary"].get("capacity") is not None, "capacity must be reported"
    assert res["summary"].get("oos_min_capacity") is not None


def test_panel_reference_matches_the_committed_artifact():
    """Re-running the convention must reproduce the committed reference
    numbers within a tight tolerance."""
    reference = _load_reference()
    pinned = reference["pinned"]
    rel_tol = reference.get("rel_tol", 1e-9)
    abs_tol = reference.get("abs_tol", 1e-12)

    res = _run_panel()
    diag = res["summary"].get("book_diagnostic")
    assert diag is not None

    checks = {
        "impact_charged_bps": diag.get("impact_charged_bps"),
        "impact_traded_only_bps": diag.get("impact_traded_only_bps"),
        "impact_dilution_bps": diag.get("impact_dilution_bps"),
        "impact_participation_ratio": diag.get("impact_participation_ratio"),
        "capacity": res["summary"].get("capacity"),
        "oos_min_capacity": res["summary"].get("oos_min_capacity"),
        "gross_book": diag.get("gross_book"),
        "gross_turnover": diag.get("gross_turnover"),
        "return_gap_bps": diag.get("return_gap_bps"),
        "book_total_return": diag.get("book_total_return"),
    }
    for key, actual in checks.items():
        expected = pinned[key]
        assert _close(actual, expected, rel_tol, abs_tol), (
            f"{key}: expected {expected}, got {actual}"
        )


TEST_REGISTRY = [
    ("panel_reference_impact_numbers_are_not_null", test_panel_reference_impact_numbers_are_not_null),
    ("panel_reference_matches_the_committed_artifact", test_panel_reference_matches_the_committed_artifact),
]


def main() -> int:
    failures = 0
    for name, fn in TEST_REGISTRY:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(TEST_REGISTRY) - failures}/{len(TEST_REGISTRY)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
