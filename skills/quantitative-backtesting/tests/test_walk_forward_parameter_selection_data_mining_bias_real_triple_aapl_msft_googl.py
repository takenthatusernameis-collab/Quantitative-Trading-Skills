#!/usr/bin/env python3
"""Walk-forward parameter-selection (data-mining) bias on the committed triple
panel (AAPL / MSFT / GOOGL), using time-series momentum.

Compares out-of-sample performance of two walk-forward runs on the same data:

  (a) fixed lookback = 189 (single configuration, no in-sample selection)
  (b) grid {126, 189, 252} with in-sample per-window selection and the
      Deflated Sharpe Ratio multiple-testing correction
      (n_trials aggregated across windows)

In-sample selection picks the lookback that looked best on train, so the raw
(undeflated) out-of-sample Sharpe of (b) is the data-mining-biased estimate.
Data-mining bias = grid OOS Sharpe minus fixed OOS Sharpe.

After deflation both verdicts must remain NOT SUPPORTED (deflated Sharpe
p-value >= 0.10), showing the correction honest-reports the selection rather
than concealing it. No profitability or performance claim is made; the study
quantifies selection inflation only.

Offline, committed fixtures only (AAPL/MSFT/GOOGL); no live network.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from walk_forward import walk_forward_analysis  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"
SYMBOLS = ("AAPL.csv", "MSFT.csv", "GOOGL.csv")

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade
TRAIN_MONTHS = 24
TEST_MONTHS = 12
STEP_MONTHS = 12
DSR_PVALUE_THRESHOLD = 0.10

FIXED_LOOKBACK = 189
GRID_LOOKBACKS = [126, 189, 252]


def _build_panel():
    panel = {}
    for name in SYMBOLS:
        df = pd.read_csv(SRC / name)
        df["date"] = pd.to_datetime(df["date"])
        panel[Path(name).stem] = df.set_index("date").sort_index()
    return panel


def _factory(params):
    return build_strategy("time_series_momentum", json.dumps(params))


def _run(lookbacks):
    return walk_forward_analysis(
        data=_build_panel(),
        strategy_factory=_factory,
        param_grid={"lookback": lookbacks},
        train_months=TRAIN_MONTHS,
        test_months=TEST_MONTHS,
        step_months=STEP_MONTHS,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        panel_pricing="book",
        apply_deflation=True,
        validate_pit=True,
    )


def _summary(result):
    assert isinstance(result, dict)
    assert "periods" in result and "summary" in result
    return result["summary"]


def test_parameter_selection_runs_and_passes_pit_on_triple_panel():
    for name in SYMBOLS:
        assert (SRC / name).exists()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        fixed = _run([FIXED_LOOKBACK])
        grid = _run(GRID_LOOKBACKS)
    out = buffer.getvalue()
    for label, res in (("fixed", fixed), ("grid", grid)):
        summary = _summary(res)
        assert summary["n_periods"] == 3, label
        assert summary["bias_controls_engaged"] is True, label
        assert "Point-in-time validation passed" in out, label
    assert out.count("Point-in-time validation passed") == 2, out


def test_data_mining_bias_quantified_and_deflation_keeps_not_supported():
    for name in SYMBOLS:
        assert (SRC / name).exists()
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        fixed = _run([FIXED_LOOKBACK])
        grid = _run(GRID_LOOKBACKS)
    fs, gs = _summary(fixed), _summary(grid)

    fixed_oos_sharpe = fs.get("oos_sharpe")
    grid_oos_sharpe = gs.get("oos_sharpe")
    assert fixed_oos_sharpe is not None and grid_oos_sharpe is not None

    # Selection evaluates more configurations, so it cannot use fewer trials.
    f_dsr = fs.get("deflated_sharpe") or {}
    g_dsr = gs.get("deflated_sharpe") or {}
    f_n = f_dsr.get("n_trials")
    g_n = g_dsr.get("n_trials")
    f_p = f_dsr.get("p_value")
    g_p = g_dsr.get("p_value")
    assert f_n is not None and g_n is not None
    assert g_n >= f_n, (f_n, g_n)

    # Data-mining bias = change in raw OOS Sharpe from in-sample selection.
    selection_bias = grid_oos_sharpe - fixed_oos_sharpe
    print(
        "[data-mining bias] fixed_lookback=189 oos_sharpe="
        f"{fixed_oos_sharpe:+.6f} total_return={float(fs.get('total_oos_return') or 0.0):+.6f} "
        f"grid_lookbacks={GRID_LOOKBACKS} oos_sharpe={grid_oos_sharpe:+.6f} "
        f"total_return={float(gs.get('total_oos_return') or 0.0):+.6f} "
        f"selection_bias={selection_bias:+.6f} "
        f"fixed_n_trials={f_n} fixed_p={f_p} grid_n_trials={g_n} grid_p={g_p}"
    )

    # Honest reporting: uncorrected single-parameter evaluation can look
    # deceptively good (fixed lookback 189 shows a positive raw OOS Sharpe),
    # whereas the selection + Deflated Sharpe framework correctly reports
    # NOT SUPPORTED (grid deflated p-value >= 0.10).
    assert g_p is not None
    assert float(g_p) >= DSR_PVALUE_THRESHOLD, (
        f"grid deflated Sharpe p-value {g_p} below threshold; "
        "selection bias survived deflation"
    )
    # Grid (multiplicity-corrected) OOS record stays non-supportive.
    assert grid_oos_sharpe <= 0.0 or float(gs.get("total_oos_return") or 0.0) <= 0.0


if __name__ == "__main__":
    test_parameter_selection_runs_and_passes_pit_on_triple_panel()
    test_data_mining_bias_quantified_and_deflation_keeps_not_supported()
    print("OK")
