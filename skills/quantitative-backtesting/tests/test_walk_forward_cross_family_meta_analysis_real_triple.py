#!/usr/bin/env python3
"""Cross-family *protocol-sensitivity* meta-analysis on the committed triple
panel (AAPL, MSFT, GOOGL).

Motivation
----------
The per-family cross-asset protocol-sensitivity summaries (volatility targeting,
time-series momentum, RSI mean reversion, SMA crossover) each apply a
two-level Bonferroni (per-asset across protocols, then cross-asset across the
three assets) and all conclude NOT SUPPORTED within their family. None of them
answers the decision-relevant question:

    Does ANY signal family show a real edge when ALL families are tested
    together?

This study closes that loop. It re-runs each family's pinned best-nominal
per-asset cell (one cell per asset per family, 4 families x 3 assets = 12
per-asset best-nominal DSR p-values) and applies a single Bonferroni
correction across the 12 asset-family hypotheses. The question is therefore
"did we find anything anywhere across all 12 looks?" rather than "is this one
family robust?" -- the honest family-wise analogue of the per-family studies.

Design (pre-registered before any number is inspected)
------------------------------------------------------
* Four families on the committed triple panel (AAPL, MSFT, GOOGL):
    - time_series_momentum   : PARAM_GRID {"lookback": [126, 189, 252]}
    - volatility_targeting   : PARAM_GRID {"target_vol": [0.15], "lookback": [63]}
    - rsi_mean_reversion     : PARAM_GRID {"period": [14], "oversold": [30],
                                     "overbought": [70], "neutral": [50]}
    - sma_crossover          : PARAM_GRID {"fast_period": [20], "slow_period": [50]}
* Costs: commission 2 bps + slippage 1 bps per trade (shipped default).
* Deflated Sharpe Ratio applied within each per-asset protocol cell
  (across that family's configurations and walk-forward periods).
* One cell per family per asset: the pinned best-nominal protocol for that
  asset (the protocol with the minimum within-protocol DSR p-value). This is
  the per-asset best-nominal p-value each cross-asset summary already reports.
* 12 per-asset best-nominal DSR p-values total; one Bonferroni correction
  across all 12 (FWER across every asset-family hypothesis tested).
* Pre-registered falsification criterion: Deflated Sharpe p-value < 0.10
  *after* the 12-way correction.

Honest finding (all committed fixtures, offline; pinned by the run below)
-------------------------------------------------------------------------
Nominal per-asset best DSR p-values (from the pinned per-family studies):
    TSMOM:     AAPL 0.1021  MSFT 0.0696  GOOGL 0.5814   (best 0.0696, MSFT)
    Vol tgt:   AAPL 0.4792  MSFT 0.3918  GOOGL 0.2782   (best 0.2782, GOOGL)
    RSI MR:    AAPL 0.5335  MSFT 0.2090  GOOGL 0.1726   (best 0.1726, GOOGL)
    SMA xover: AAPL 0.0415  MSFT 0.0574  GOOGL 0.1299   (best 0.0415, AAPL)

Best nominal cell overall: SMA crossover on AAPL @ (36, 12, 12), DSR p = 0.0415.
Bonferroni across 12 asset-family hypotheses: adjusted p = 0.0415 x 12 = 0.4980.
Total n_rejected at alpha = 0.10: 0.
Overall verdict: NOT SUPPORTED. No signal family survives when all four
families (all twelve asset-family hypotheses) are tested together. The best
nominal pass (SMA crossover on AAPL) is consistent with selection noise across
protocols, assets, and families, not a demonstrated edge.

Limitation: each per-asset best p-value is itself a minimum over that asset's
protocols (within-family selection), so the 12-way Bonferroni corrects the
across-family/across-asset look count but does not further correct the
within-asset protocol selection. It is therefore a transparent, not fully
exhaustive, family-wise correction; the conclusion is robust either way because
even the raw best p-value (0.0415) multiplied by 12 is far above 0.10.

A sharper cross-family test (White's reality_check_test /
romano_wolf_stepdown on aligned per-period return series) is left as a
follow-up: the four families' best cells use different protocol dates, so they
do not share a common time index and cannot be assembled into one
(T, K) performance matrix without re-aligning on a common calendar.

Offline, committed fixtures only; no live network. Test-only.
"""
import contextlib
import io
import json
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

import pandas as pd  # noqa: E402

from walk_forward import walk_forward_analysis  # noqa: E402
from strategy_builder import build_strategy  # noqa: E402
from utils import bonferroni_correction  # noqa: E402

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"

SYMBOLS = ["AAPL", "MSFT", "GOOGL"]

COMMISSION = 0.0002   # 2 bps per trade
SLIPPAGE = 0.0001     # 1 bps per trade
DSR_PVALUE_THRESHOLD = 0.10

# Informative protocols: 12-month test windows.
INFORMATIVE_PROTOCOLS = [(24, 12, 12), (36, 12, 12), (18, 12, 12), (30, 12, 12)]

# A cell is "informative" when the strategy actually held a position for at
# least this many walk-forward periods.
MIN_INFORMATIVE_PERIODS = 2

ABS_TOL = 1e-3

# Family configurations: signal name, parameter grid, and the pinned
# best-nominal protocol per asset (from each family's cross-asset summary).
# EXPECTED_BEST_P is the pinned per-asset best-nominal DSR p-value (regression
# guard, not a profitability claim).
FAMILIES = {
    "time_series_momentum": dict(
        signal="time_series_momentum",
        param_grid={"lookback": [126, 189, 252]},
        best_protocol={
            "AAPL": (36, 12, 12),
            "MSFT": (30, 12, 12),
            "GOOGL": (30, 12, 12),
        },
        expected_best_p={"AAPL": 0.1021, "MSFT": 0.0696, "GOOGL": 0.5814},
    ),
    "volatility_targeting": dict(
        signal="volatility_targeting",
        param_grid={"target_vol": [0.15], "lookback": [63]},
        best_protocol={
            "AAPL": (30, 12, 12),
            "MSFT": (30, 12, 12),
            "GOOGL": (36, 12, 12),
        },
        expected_best_p={"AAPL": 0.4792, "MSFT": 0.3918, "GOOGL": 0.2782},
    ),
    "rsi_mean_reversion": dict(
        signal="rsi_mean_reversion",
        param_grid={"period": [14], "oversold": [30], "overbought": [70],
                    "neutral": [50]},
        best_protocol={
            "AAPL": (30, 12, 12),
            "MSFT": (24, 12, 12),
            "GOOGL": (36, 12, 12),
        },
        expected_best_p={"AAPL": 0.5335, "MSFT": 0.2090, "GOOGL": 0.1726},
    ),
    "sma_crossover": dict(
        signal="sma_crossover",
        param_grid={"fast_period": [20], "slow_period": [50]},
        best_protocol={
            "AAPL": (36, 12, 12),
            "MSFT": (30, 12, 12),
            "GOOGL": (36, 12, 12),
        },
        expected_best_p={"AAPL": 0.0415, "MSFT": 0.0574, "GOOGL": 0.1299},
    ),
}

FAMILY_ORDER = ["time_series_momentum", "volatility_targeting",
                "rsi_mean_reversion", "sma_crossover"]


def _build_data(symbol):
    df = pd.read_csv(SRC / f"{symbol}.csv")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").sort_index()


def _factory(signal, params):
    return build_strategy(signal, json.dumps(params))


def _run_best_cell(family_name, symbol):
    """Run the pinned best-nominal protocol cell for one (family, asset).

    Returns the cell summary dict (oos_sharpe, total_oos_return,
    deflated_sharpe.p_value, n_periods, periods_with_position).
    """
    cfg = FAMILIES[family_name]
    protocol = cfg["best_protocol"][symbol]
    train_months, test_months, step_months = protocol
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        result = walk_forward_analysis(
            data=_build_data(symbol),
            strategy_factory=lambda params: _factory(cfg["signal"], params),
            param_grid=cfg["param_grid"],
            train_months=train_months,
            test_months=test_months,
            step_months=step_months,
            commission=COMMISSION,
            slippage=SLIPPAGE,
            apply_deflation=True,
            validate_pit=True,
        )
    summary = result["summary"]
    assert summary.get("bias_controls_engaged") is True, (
        f"{family_name} {symbol} {protocol}: point-in-time validation not engaged"
    )
    dsr = summary.get("deflated_sharpe") or {}
    return {
        "family": family_name,
        "symbol": symbol,
        "protocol": protocol,
        "oos_sharpe": summary.get("oos_sharpe"),
        "total_oos_return": summary.get("total_oos_return"),
        "dsr_p": dsr.get("p_value"),
        "n_periods": summary.get("n_periods"),
        "periods_with_position": summary.get("periods_with_position"),
    }


def _collect_best_p_values():
    """Run all 12 best-nominal cells, return list of (family, symbol, p)."""
    results = []
    for family in FAMILY_ORDER:
        for symbol in SYMBOLS:
            results.append(_run_best_cell(family, symbol))
    return results


def _assert_close(got, exp, label):
    assert got is not None, f"{label}: missing value (expected ~{exp})"
    assert abs(float(got) - float(exp)) <= ABS_TOL, (
        f"{label}: got {got!r}, expected ~{exp} (abs tol {ABS_TOL})"
    )


def test_per_asset_best_p_values_regress():
    """Regression guard: each family's pinned best-nominal per-asset DSR
    p-value is re-verified live against the cross-asset summary pins.

    This confirms the 12 input p-values to the meta-analysis are still
    accurate, not stale.
    """
    results = _collect_best_p_values()
    for cell in results:
        fam = cell["family"]
        sym = cell["symbol"]
        exp_p = FAMILIES[fam]["expected_best_p"][sym]
        assert cell["periods_with_position"] >= MIN_INFORMATIVE_PERIODS, (
            f"{fam} {sym}: cell not informative"
        )
        _assert_close(cell["dsr_p"], exp_p,
                      f"{fam} {sym} {cell['protocol']} dsrc_p")
        p = cell["dsr_p"]
        assert p is not None and 0.0 <= float(p) <= 1.0, (
            f"{fam} {sym}: DSR p-value out of range: {p!r}"
        )
    print(f"Cross-family: re-verified {len(results)} per-asset best-nominal "
          f"DSR p-values against pins")


def test_cross_family_bonferroni_all_cells():
    """Core finding: one Bonferroni correction across all 12 per-asset
    best-nominal DSR p-values (FWER across every asset-family hypothesis).

    The best nominal cell overall is SMA crossover on AAPL (p = 0.0415);
    adjusted p = 0.0415 x 12 = 0.4980 > 0.10, so nothing is rejected and the
    cross-family verdict is NOT SUPPORTED. Reported honestly; no forcing.
    """
    results = _collect_best_p_values()
    p_values = [cell["dsr_p"] for cell in results]
    assert all(p is not None for p in p_values), "missing DSR p-value"

    best_idx = min(range(len(p_values)), key=lambda i: p_values[i])
    best_cell = results[best_idx]
    best_p = p_values[best_idx]

    res = bonferroni_correction(p_values, alpha=DSR_PVALUE_THRESHOLD)
    best_adjusted = res["adjusted_p_values"][best_idx]

    print(f"Cross-family best nominal cell: {best_cell['family']} on "
          f"{best_cell['symbol']} @ {best_cell['protocol']} "
          f"(DSR p = {best_p:.4f})")
    print(f"Bonferroni across {len(p_values)} asset-family hypotheses: "
          f"adjusted p = {best_adjusted:.4f}, n_rejected = {res['n_rejected']}")

    # Nothing survives a 12-way correction.
    assert best_adjusted > DSR_PVALUE_THRESHOLD, (
        f"cross-family: best DSR p={best_p} Bonferroni-adjusted = {best_adjusted} "
        f"should exceed {DSR_PVALUE_THRESHOLD}"
    )
    assert res["n_rejected"] == 0, (
        f"cross-family: expected 0 rejections at alpha={DSR_PVALUE_THRESHOLD}, "
        f"got {res['n_rejected']}"
    )


def test_best_nominal_cell_honest_report():
    """Honest report of the best nominal cell: it passes the raw DSR
    criterion (p = 0.0415 < 0.10) but does NOT survive the 12-way Bonferroni
    (adjusted p = 0.4980 > 0.10). No verdict is forced; the multiplicity
    correction governs the conclusion.
    """
    results = _collect_best_p_values()
    p_values = [cell["dsr_p"] for cell in results]
    best_idx = min(range(len(p_values)), key=lambda i: p_values[i])
    best_cell = results[best_idx]
    best_p = float(p_values[best_idx])

    # The best nominal cell passes the raw criterion.
    assert best_p < DSR_PVALUE_THRESHOLD, (
        f"best nominal DSR p={best_p} should be < {DSR_PVALUE_THRESHOLD}"
    )
    assert best_cell["family"] == "sma_crossover", (
        f"expected best nominal family sma_crossover, got {best_cell['family']}"
    )
    assert best_cell["symbol"] == "AAPL", (
        f"expected best nominal symbol AAPL, got {best_cell['symbol']}"
    )

    # It does not survive correction across all 12 asset-family hypotheses.
    adjusted = best_p * len(p_values)
    assert adjusted > DSR_PVALUE_THRESHOLD, (
        f"best nominal DSR p={best_p} x 12 = {adjusted} should exceed "
        f"{DSR_PVALUE_THRESHOLD} (not robust to cross-family multiplicity)"
    )
    print(f"Best nominal cell: {best_cell['family']} on {best_cell['symbol']} "
          f"@{best_cell['protocol']} raw p={best_p:.4f} x12-adjusted={adjusted:.4f}")


def test_no_family_survives_cross_family_multiplicity():
    """Family-level question: does ANY family survive when all four are
    tested together?

    Take each family's best per-asset nominal p-value (minimum over its 3
    assets) and apply Bonferroni across the 4 families. All four families
    individually conclude NOT SUPPORTED; this test confirms none survives a
    further 4-way correction either.
    """
    family_best = {}
    results = _collect_best_p_values()
    for cell in results:
        fam = cell["family"]
        p = cell["dsr_p"]
        if fam not in family_best or p < family_best[fam]:
            family_best[fam] = p

    family_names = FAMILY_ORDER
    family_p_values = [family_best[f] for f in family_names]
    best_fam = min(range(len(family_p_values)),
                   key=lambda i: family_p_values[i])

    res = bonferroni_correction(family_p_values, alpha=DSR_PVALUE_THRESHOLD)
    best_adjusted = res["adjusted_p_values"][best_fam]

    for f in family_names:
        print(f"Family {f}: best per-asset nominal DSR p = {family_best[f]:.4f}")
    print(f"Cross-family Bonferroni across 4 families: best family "
          f"{family_names[best_fam]} p={family_p_values[best_fam]:.4f} "
          f"adjusted={best_adjusted:.4f}, n_rejected={res['n_rejected']}")

    assert best_adjusted > DSR_PVALUE_THRESHOLD, (
        f"cross-family: best family DSR p={family_p_values[best_fam]} "
        f"Bonferroni-adjusted={best_adjusted} should exceed "
        f"{DSR_PVALUE_THRESHOLD}"
    )
    assert res["n_rejected"] == 0, (
        f"cross-family: expected 0 rejections at alpha={DSR_PVALUE_THRESHOLD}, "
        f"got {res['n_rejected']}"
    )


def test_main_registers_every_module_level_test():
    """main() must register every module-level ``test_*`` function."""
    import inspect

    module_tests = {
        obj
        for name, obj in list(globals().items())
        if name.startswith("test_")
        and inspect.isfunction(obj)
        and obj.__module__ == __name__
    }
    registered = {fn for _, fn in TEST_REGISTRY}

    missing = module_tests - registered
    assert not missing, (
        f"test functions defined but not registered in TEST_REGISTRY: "
        f"{sorted(f.__name__ for f in missing)}"
    )
    phantom = registered - module_tests
    assert not phantom, (
        f"entries in TEST_REGISTRY that are not module-level test_* "
        f"functions: {sorted(f.__name__ for f in phantom)}"
    )
    labels = [name for name, _ in TEST_REGISTRY]
    assert len(labels) == len(set(labels)), (
        f"TEST_REGISTRY has duplicate labels: "
        f"{[l for l in labels if labels.count(l) > 1]}"
    )


TEST_REGISTRY = [
    ("per_asset_best_p_values_regress", test_per_asset_best_p_values_regress),
    ("cross_family_bonferroni_all_cells", test_cross_family_bonferroni_all_cells),
    ("best_nominal_cell_honest_report", test_best_nominal_cell_honest_report),
    ("no_family_survives_cross_family_multiplicity",
     test_no_family_survives_cross_family_multiplicity),
    ("main_registers_every_module_level_test", test_main_registers_every_module_level_test),
]


def main() -> int:
    import traceback

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
