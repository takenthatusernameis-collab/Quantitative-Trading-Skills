#!/usr/bin/env python3
"""Out-of-sample validation with CPCV validation method on the committed
real-market three-asset panel (AAPL / MSFT / GOOGL) for time-series
momentum (TSMOM).

Runs the three-phase train/validation/test framework using CPCV for the
validation phase on the committed real market data with the same cost model
as the walk-forward tests (3 bps round-trip commission+slippage,
panel_pricing="book", borrow_cost=0.03, funding_cost=0.03, PIT validation
engaged). Reports the selected parameters, validation performance, and
held-out test performance. This is a methodological test of the CPCV
validation path on real market data with realistic costs.
"""
import sys
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILLS_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from time_series_momentum_hypothesis import (  # noqa: E402
    COMMISSION,
    SLIPPAGE,
    PARAM_GRID,
    _build_triple_panel,
)

from walk_forward import out_of_sample_validation  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402
import json


def _make_factory():
    def factory(params):
        return build_strategy("time_series_momentum", json.dumps(params))
    return factory


def test_out_of_sample_cpcv_validation_real_triple_panel_time_series_momentum():
    """Run out-of-sample validation with CPCV on the triple panel with TSMOM.

    Verifies that:
    1. The three-phase split is chronologically ordered and disjoint.
    2. The CPCV validation phase selects parameters from the training split.
    3. The validation performance is reported on the validation window.
    4. The held-out test performance is reported on the test window.
    5. The panel_pricing="book" mode works with real market data.
    4. Point-in-time validation passes on clean real market data.
    5. Realistic costs (commission, slippage, borrow, funding) are applied.
    """
    panel = _build_triple_panel()
    factory = _make_factory()

    result = out_of_sample_validation(
        data=panel,
        strategy_factory=factory,
        param_grid=PARAM_GRID,
        train_frac=0.6,
        val_frac=0.2,
        test_frac=0.2,
        validation_method="cpcv",
        cpcv_n_splits=5,
        cpcv_test_size=0.2,
        cpcv_purge_size=0.0,
        cpcv_embargo_size=0.0,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        borrow_cost=0.03,
        funding_cost=0.03,
        panel_pricing="book",
        apply_deflation=True,
        validate_pit=True,
        pit_strict=False,
    )

    # 1. Three-phase separation check
    sep = result["train_val_test_split"]["separation_check"]
    assert sep["disjoint"] is True, f"splits are not disjoint: {sep}"
    assert sep["chronological"] is True, f"splits not chronological: {sep}"

    # 2. A parameter was selected from the validation phase
    assert result["selected_params"] is not None, (
        f"no parameter selected: {result['summary'].get('error')}"
    )
    assert "lookback" in result["selected_params"]

    # 3. Validation performance reported
    val_perf = result["validation_performance"]
    assert val_perf["val_n_observations"] > 0
    assert "val_sharpe" in val_perf
    assert "val_volatility" in val_perf
    assert "val_total_return" in val_perf

    # 4. Held-out test performance reported
    test_perf = result["test_performance"]
    assert test_perf["test_n_observations"] > 0
    assert "test_sharpe" in test_perf
    assert "test_volatility" in test_perf
    assert "test_total_return" in test_perf

    # 5. Panel pricing mode recorded
    assert result["summary"]["panel_pricing"] == "book"

    # 6. Point-in-time validation passed
    pit = result.get("point_in_time_validation") or result.get("pit_validation") or {}
    assert pit.get("passed") is True, f"PIT validation failed: {pit}"

    # 7. Costs were applied (check that summary has cost-affected metrics)
    summary = result["summary"]
    assert "validation_total_return" in summary
    assert "validation_sharpe" in summary
    assert "test_total_return" in summary
    assert "test_sharpe" in summary

    # CPCV configuration recorded
    assert result["summary"]["validation_method"] == "cpcv"
    # CPCV details are in the validation_results summary
    val_summary = result["validation_results"]["summary"]
    assert val_summary.get("n_folds") == 5
    # The partial_selection_diagnosis has the CPCV config
    psd = val_summary.get("partial_selection_diagnosis", {})
    assert psd.get("details", {}).get("cpcv_n_splits") == 5
    assert psd.get("details", {}).get("cpcv_test_size") == 0.2

    print(f"Selected params: {result['selected_params']}")
    print(f"Validation Sharpe: {val_perf['val_sharpe']:.4f}")
    print(f"Test Sharpe: {test_perf['test_sharpe']:.4f}")
    print(f"PIT passed: {pit.get('passed')}")
    print(f"Separation check: disjoint={sep['disjoint']}, chronological={sep['chronological']}")


if __name__ == "__main__":
    test_out_of_sample_cpcv_validation_real_triple_panel_time_series_momentum()
    print("OK")