#!/usr/bin/env python3
"""
Regression tests for the regime-aware market-impact flag path in
``examples/trading_costs_robustness_example.py``.

The worked example exposes ``--regime-aware``, which switches market-impact
charges from a single constant coefficient to per-regime coefficients keyed by
the labels produced by ``regime_detection.detect_combined_regime`` (e.g.
``bull_high``, ``bear_low``).  Three silent failure modes are easy to introduce
and hard to notice from the printed report:

  * ``main()`` forgets to pass ``regime_impact_coefficients`` into the sweep
    functions, so the flag is accepted but has no effect.
  * the coefficient keys use a different spelling than the detector emits
    (the historical ``*_vol`` suffix bug), so every bar falls back to the base
    coefficient and the "regime-aware" run is a silent no-op.
  * the CPCV summary stops recording ``regime_aware`` / the coefficient model,
    so downstream comparisons cannot tell the two runs apart.

These tests pin the wiring, not any performance result.  They run ``main()``
end-to-end on the shipped synthetic universe but with the cost/validation grids
reduced so the full pipeline completes in seconds (the production grids are a
deliberate multi-minute sensitivity sweep; they are not needed to exercise the
plumbing).  No claim is made about profitability or production readiness -- the
data is synthetic (seed=42) and every number is a property of that fixture.

Run with: python3 skills/quantitative-backtesting/tests/test_trading_costs_robustness_example.py
No third-party test framework is required; uses only the standard library, numpy and pandas.
"""

import contextlib
import io
import json
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

import trading_costs_robustness_example as costs_example  # noqa: E402
from regime_detection import detect_combined_regime  # noqa: E402


# Reduced grids: enough to exercise every section of main() end-to-end while
# keeping runtime in the seconds range.  The production grids (see the example
# module) are a deliberate sensitivity sweep and are not needed to guard the
# regime-aware plumbing.  N_PERIODS / N_ASSETS are intentionally left at the
# module defaults (756 / 8) so the synthetic universe produces every regime
# label; shrinking them starves the trend detector of its 200-bar warmup.
_REDUCED_GRIDS = {
    "COMMISSION_GRID": [0.0, 0.0010],
    "SLIPPAGE_GRID": [0.0],
    "BORROW_COST_GRID": [0.0],
    "FUNDING_COST_GRID": [0.0],
    "CPCV_N_SPLITS": 2,
    "CPCV_PARAM_GRID": {"fast_period": [5, 10], "slow_period": [20, 30]},
    "SWEEP_PARAM_GRID": {"fast_period": [5, 10], "slow_period": [20, 30]},
    "COMMISSION_SWEEP_GRID": [0.0, 0.0010],
    "SLIPPAGE_SWEEP_GRID": [0.0, 0.0005],
    "MC_N_SIMULATIONS": 20,
}

# The coefficient keys main() builds for --regime-aware.  These must match the
# label vocabulary of detect_combined_regime (trend + "_" + volatility).
_EXPECTED_COEFF_KEYS = {
    "bull_high",
    "bull_low",
    "bear_high",
    "bear_low",
    "sideways_high",
    "sideways_low",
}


class _reduced_grids:
    """Temporarily override module-level cost/validation grids, then restore."""

    def __enter__(self):
        self._saved = {name: getattr(costs_example, name) for name in _REDUCED_GRIDS}
        for name, value in _REDUCED_GRIDS.items():
            setattr(costs_example, name, value)
        return self

    def __exit__(self, *exc):
        for name, value in self._saved.items():
            setattr(costs_example, name, value)
        return False


def _run_main(regime_aware, out_path):
    """Run the example's main() with reduced grids and return the parsed JSON."""
    argv = [
        "trading_costs_robustness_example.py",
        "--impact-model",
        "sqrt",
        "--impact-coefficient",
        "0.5",
        "--output",
        str(out_path),
    ]
    if regime_aware:
        argv.append("--regime-aware")
    saved_argv = sys.argv
    sys.argv = argv
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            costs_example.main()
    finally:
        sys.argv = saved_argv
    with open(out_path) as f:
        return json.load(f)


def test_example_exposes_regime_aware_entry_point():
    """The example must import and expose main() and the regime-aware CLI flag."""
    assert hasattr(costs_example, "main")
    assert callable(costs_example.main)
    # parse_args must accept --regime-aware and default to disabled.
    saved_argv = sys.argv
    try:
        sys.argv = ["x", "--regime-aware"]
        assert costs_example.parse_args().regime_aware is True
        sys.argv = ["x"]
        assert costs_example.parse_args().regime_aware is False
    finally:
        sys.argv = saved_argv


def test_regime_aware_flag_populates_metadata_and_cpcv():
    """--regime-aware must record regime_aware + coefficients in metadata and CPCV."""
    with _reduced_grids(), tempfile.TemporaryDirectory() as td:
        summary = _run_main(True, Path(td) / "on.json")

    meta = summary["metadata"]
    assert meta["regime_aware"] is True
    coeffs = meta["regime_impact_coefficients"]
    assert set(coeffs) == _EXPECTED_COEFF_KEYS, (
        f"regime coefficient keys {sorted(coeffs)} do not match the detector vocabulary"
    )
    assert all(isinstance(v, (int, float)) and v > 0 for v in coeffs.values())

    cpcv = summary["cpcv_robustness"]
    for scenario in ("low_cost", "high_cost"):
        costs = cpcv[scenario]["strategy_costs"]
        assert costs["regime_aware"] is True, f"{scenario} CPCV did not record regime_aware"
        assert costs["impact_model"] == "sqrt"
    assert cpcv["high_cost"]["strategy_costs"]["impact_coefficient"] == 0.5


def test_regime_coefficient_keys_match_detected_labels():
    """Coefficient keys must overlap the labels the detector actually emits.

    This is the guard against the historical ``*_vol`` suffix bug: if the keys
    do not match the detector vocabulary every bar silently falls back to the
    base coefficient and ``--regime-aware`` becomes a no-op.
    """
    strategy_df, _benchmarks, _symbols = costs_example._make_universe()
    detected = set(detect_combined_regime(strategy_df["close"]).unique())
    # The fixture must actually contain more than one tradable regime, otherwise
    # the "different results" assertion below could pass trivially.
    tradable = detected - {"unknown"}
    assert len(tradable) >= 2, f"fixture has too few regimes: {sorted(detected)}"

    with _reduced_grids(), tempfile.TemporaryDirectory() as td:
        summary = _run_main(True, Path(td) / "on.json")
    coeff_keys = set(summary["metadata"]["regime_impact_coefficients"])

    overlap = coeff_keys & detected
    assert overlap, (
        "regime coefficient keys do not match any detected label; "
        f"keys={sorted(coeff_keys)} detected={sorted(detected)}"
    )


def test_regime_aware_changes_net_results_vs_constant():
    """Regime-aware coefficients must change net results vs a constant coefficient."""
    with _reduced_grids(), tempfile.TemporaryDirectory() as td:
        on = _run_main(True, Path(td) / "on.json")
        off = _run_main(False, Path(td) / "off.json")

    assert on["metadata"]["regime_aware"] is True
    assert off["metadata"]["regime_aware"] is False
    assert off["metadata"]["regime_impact_coefficients"] is None

    # The constant-coefficient baseline charges impact_coefficient=0.5 in every
    # regime; the regime-aware run charges more in stressed regimes and less in
    # calm ones, so the same (commission=0, slippage=0) bar must price differently.
    on_first = on["strategy_cost_sweep"][0]
    off_first = off["strategy_cost_sweep"][0]
    assert on_first["total_return"] != off_first["total_return"], (
        "regime-aware and constant-coefficient runs produced identical net "
        "returns; the regime path may be a silent no-op"
    )

    # The market-impact sensitivity demonstration must also differ at a non-zero
    # coefficient, confirming per-regime coefficients reach the impact model.
    def _impact_return(summary, coeff):
        rows = summary["strategy_exposure_demonstrations"]["market_impact"]["rows"]
        row = next(r for r in rows if abs(r["coeff"] - coeff) < 1e-9)
        return row["return"]

    assert _impact_return(on, 0.5) != _impact_return(off, 0.5), (
        "market-impact demonstration identical under regime-aware vs constant "
        "coefficients at coeff=0.5"
    )


def test_book_regime_aware_changes_net_results_vs_constant():
    """Regime-aware coefficients must change net results under book pricing.

    The example's SMA-crossover strategy is long-only and has a flat net exposure
    when priced as a panel. To exercise book pricing with regime-aware impact,
    we construct a market-neutral multi-asset book (long/short with gross
    turnover) and assert that switching on regime_impact_coefficients changes
    the net return vs the constant-coefficient baseline. This mirrors
    test_book_regime_aware_sqrt_matches_closed_form in test_strategy_cost_model.py
    but uses the example's synthetic universe and the same coefficient keys.
    """
    with _reduced_grids():
        # Build the same synthetic panel the example uses.
        raw = costs_example.generate_multi_asset_data(
            n_assets=costs_example.N_ASSETS, periods=costs_example.N_PERIODS, seed=42
        )
        panel = {sym: df.set_index("date") for sym, df in raw.items()}
        symbols = sorted(panel.keys())

        # Construct a market-neutral book that rotates its long/short legs.
        # This mirrors the "Market-neutral leveraged variant" in Section 1 of
        # trading_costs_robustness_example.py (lines ~408-418).
        sig_a = costs_example._strategy_signals(panel[symbols[3]])
        sig_b = costs_example._strategy_signals(panel[symbols[4]])
        common = panel[symbols[3]].index.intersection(panel[symbols[4]].index)
        pos_a = sig_a.reindex(common).fillna(0)
        pos_b = -sig_b.reindex(common).fillna(0)
        # Book weights: DataFrame with per-asset weights (long A, short B, 2x gross exposure).
        book_weights = pd.DataFrame({
            symbols[3]: pos_a * 1.0,
            symbols[4]: pos_b * 1.0,
        })
        # Net exposure signal for the engine (flat for market-neutral book).
        signals = pd.Series(0.0, index=common)

        # Constant-coefficient regime-impact dict (matches --regime-aware keys).
        base_coeff = 0.5
        regime_impact_coefficients = {
            "bull_high": base_coeff * 1.5,
            "bull_low": base_coeff * 0.5,
            "bear_high": base_coeff * 2.0,
            "bear_low": base_coeff * 1.5,
            "sideways_high": base_coeff * 1.5,
            "sideways_low": base_coeff * 0.8,
        }

        # Panel data for the two assets in the book.
        data_mn = {
            symbols[3]: panel[symbols[3]].reindex(common),
            symbols[4]: panel[symbols[4]].reindex(common),
        }

        # Run with regime-aware coefficients.
        returns_regime = costs_example._calculate_strategy_returns(
            data_mn,
            signals,
            panel_pricing="book",
            book_weights=book_weights,
            commission=0.0,
            slippage=0.0,
            borrow_cost=0.0,
            funding_cost=0.0,
            impact_coefficient=base_coeff,
            impact_model="sqrt",
            regime_impact_coefficients=regime_impact_coefficients,
        )

        # Run with constant coefficient (no regime dict).
        returns_constant = costs_example._calculate_strategy_returns(
            data_mn,
            signals,
            panel_pricing="book",
            book_weights=book_weights,
            commission=0.0,
            slippage=0.0,
            borrow_cost=0.0,
            funding_cost=0.0,
            impact_coefficient=base_coeff,
            impact_model="sqrt",
            regime_impact_coefficients=None,
        )

        # Total returns must differ; regime-aware charges more in stressed
        # regimes and less in calm ones, so the compounded result cannot be
        # identical to the constant-coefficient run.
        total_regime = float((1 + returns_regime).prod() - 1)
        total_constant = float((1 + returns_constant).prod() - 1)
        assert total_regime != total_constant, (
            "book pricing with regime-aware vs constant coefficients produced "
            f"identical net returns ({total_regime:.4%} vs {total_constant:.4%}); "
            "the regime path may be a silent no-op for book pricing"
        )


def test_main_handles_none_cpcv_metrics():
    """main() KEY FINDINGS must not crash when CPCV OOS metrics are None.

    Regression guard: the CPCV cost-impact line and the KEY FINDINGS block
    format OOS Sharpe values that can be ``None`` (e.g. a very short synthetic
    series or a degenerate validation fold).  Formatting ``None`` with a
    ``:.3f`` specifier raises ``TypeError: unsupported format string passed to
    NoneType.__format__``.  This stubs ``run_cpcv_robustness`` so the None path
    is exercised in seconds instead of a full multi-minute sensitivity sweep.
    """
    def _stub_cpcv(*_args, **_kwargs):
        return {
            "low_cost": {"oos_sharpe": None},
            "high_cost": {"oos_sharpe": None},
        }

    saved_cpcv = costs_example.run_cpcv_robustness
    saved_argv = sys.argv
    buf = io.StringIO()
    try:
        costs_example.run_cpcv_robustness = _stub_cpcv
        with _reduced_grids(), tempfile.TemporaryDirectory() as td:
            sys.argv = [
                "trading_costs_robustness_example.py",
                "--regime-aware",
                "--output",
                str(Path(td) / "none.json"),
            ]
            with contextlib.redirect_stdout(buf):
                costs_example.main()
    finally:
        costs_example.run_cpcv_robustness = saved_cpcv
        sys.argv = saved_argv

    out = buf.getvalue()
    assert "3. CPCV OOS Sharpe: low-cost=N/A vs high-cost=N/A." in out, (
        "KEY FINDINGS did not render the None CPCV Sharpe as N/A; "
        f"captured tail:\n{out[-800:]}"
    )


TEST_REGISTRY = [
    ("test_example_exposes_regime_aware_entry_point", test_example_exposes_regime_aware_entry_point),
    ("test_regime_aware_flag_populates_metadata_and_cpcv", test_regime_aware_flag_populates_metadata_and_cpcv),
    ("test_regime_coefficient_keys_match_detected_labels", test_regime_coefficient_keys_match_detected_labels),
    ("test_regime_aware_changes_net_results_vs_constant", test_regime_aware_changes_net_results_vs_constant),
    ("test_book_regime_aware_changes_net_results_vs_constant", test_book_regime_aware_changes_net_results_vs_constant),
    ("test_main_handles_none_cpcv_metrics", test_main_handles_none_cpcv_metrics),
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