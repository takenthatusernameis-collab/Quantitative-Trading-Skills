#!/usr/bin/env python3
"""
Falsifiable hypothesis test with HMM regime-dependent performance reporting.

HYPOTHESIS (pre-registered, bounded):
    On the committed AAPL real-market panel (2020-01-02..2025-12-30), a simple
    SMA crossover strategy (20/50) produces positive out-of-sample risk-adjusted
    performance net of 3 bps round-trip trading costs (2 bps commission + 1 bps
    slippage) AND its net out-of-sample returns are not concentrated solely in
    HMM-identified non-bull regimes.

FALSIFICATION CRITERIA (hypothesis NOT SUPPORTED if ANY fails):
    1. Walk-forward pooled out-of-sample Sharpe ratio (net of costs) > 0.
    2. Walk-forward pooled out-of-sample total return (net of costs) > 0.
    3. HMM regime analysis on the pooled OOS window identifies a 'bull' regime
       with >= MIN_REGIME_OBS observations and bull-regime Sharpe ratio > 0.
    4. HMM regime concentration diagnostic classification is not 'fragile'.

Validation design:
    - Chronological walk-forward analysis on committed real data only (no live
      fetch/network), with train 12 / test 3 / step 3 months.
    - Single pre-registered parameter set (no parameter search/data mining).
    - Point-in-time validation engaged.
    - HMM regime detection uses forward filtering / walk-forward refit
      configuration documented as point-in-time for filtered probabilities;
      state-to-label mapping is post-hoc (as implemented in regime_detection).
    - Secondary CPCV diagnostic (same strategy/costs) reported for robustness
      context; CPCV outcome does not change the pre-registered verdict.

This is a methodology demonstration and falsification report, not evidence of
profitability or production readiness.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from data_loader import load_data  # noqa: E402
from regime_detection import (  # noqa: E402
    HMMConfig,
    fit_hmm_walkforward,
    compute_regime_performance,
    regime_concentration_diagnostic,
)
from walk_forward import (  # noqa: E402
    walk_forward_analysis,
    cpcv_analysis,
    _make_strategy_factory,
    _annualization_factor,
)

DATA_PATH = SKILLS_DIR / "assets" / "example_data" / "real_market_data" / "AAPL.csv"
SYMBOL = "AAPL"
COMMISSION = 0.0002  # 2 bps
SLIPPAGE = 0.0001    # 1 bps
MIN_REGIME_OBS = 21

HYPOTHESIS = (
    "On committed AAPL real-market data (2020-01-02..2025-12-30), an SMA 20/50 "
    "crossover strategy has positive walk-forward out-of-sample Sharpe and total "
    "return net of 3 bps round-trip costs, with positive Sharpe in an "
    "HMM-identified bull regime and non-fragile regime concentration."
)

CRITERIA = [
    ("oos_sharpe_gt_zero", "walk-forward pooled OOS Sharpe ratio > 0 (net of costs)"),
    ("oos_total_return_gt_zero", "walk-forward pooled OOS total return > 0 (net of costs)"),
    ("bull_regime_sharpe_gt_zero", f"HMM bull regime Sharpe > 0 with >= {MIN_REGIME_OBS} observations"),
    ("regime_concentration_not_fragile", "HMM regime concentration classification != 'fragile'"),
]


def _fmt_num(v, nd=4):
    if v is None:
        return "N/A"
    try:
        fv = float(v)
    except Exception:
        return "N/A"
    if not np.isfinite(fv):
        return "N/A"
    return f"{fv:.{nd}f}"


def _fmt_pct(v):
    if v is None:
        return "N/A"
    try:
        fv = float(v)
    except Exception:
        return "N/A"
    if not np.isfinite(fv):
        return "N/A"
    return f"{fv:.2%}"


def _sharpe(returns: pd.Series) -> float | None:
    if returns is None or len(returns) < 2:
        return None
    r = pd.Series(returns).dropna()
    if len(r) < 2:
        return None
    ann = _annualization_factor(r.index)
    mu = float(r.mean() * ann)
    sigma = float(r.std(ddof=1) * np.sqrt(ann))
    if sigma <= 0 or not np.isfinite(sigma):
        return None
    return mu / sigma


def _total_return(returns: pd.Series) -> float | None:
    if returns is None or len(returns) == 0:
        return None
    r = pd.Series(returns).dropna()
    if len(r) == 0:
        return None
    return float((1.0 + r).prod() - 1.0)


def _build_hmm_regime_report(oos_returns: pd.Series, close: pd.Series) -> dict:
    """Compute HMM regime labels/performance on the pooled OOS window."""
    common = oos_returns.index.intersection(close.index)
    if len(common) == 0:
        return {
            "error": "no overlapping dates between OOS returns and close series",
            "regime_performance": {},
            "regime_distribution": {},
            "regime_concentration": {"regime_robustness": "insufficient_data"},
        }
    oos_aligned = oos_returns.loc[common].sort_index()
    close_aligned = close.loc[common].sort_index()

    hmm_config = HMMConfig(
        n_states=3,
        n_iter=100,
        tol=1e-4,
        covariance_type="diag",
        random_state=42,
        refit_window=None,
        train_frac=0.7,
        min_regime_length=MIN_REGIME_OBS,
        use_returns=True,
        use_volatility=True,
        vol_window=21,
        use_trend=False,
    )
    hmm_result = fit_hmm_walkforward(close_aligned, hmm_config)
    regime_perf = compute_regime_performance(
        oos_aligned, hmm_result.regimes, min_period_length=MIN_REGIME_OBS
    )
    concentration = regime_concentration_diagnostic(
        {"combined_regime_performance": regime_perf},
        min_regime_length=MIN_REGIME_OBS,
        min_sharpe=0.0,
        sharpe_spread_threshold=1.0,
    )
    bull = regime_perf.get("bull", {})
    bull_obs = int(bull.get("n_observations", 0) or 0)
    bull_sharpe = bull.get("sharpe_ratio")
    return {
        "config": {
            "n_states": hmm_config.n_states,
            "n_iter": hmm_config.n_iter,
            "tol": hmm_config.tol,
            "covariance_type": hmm_config.covariance_type,
            "refit_window": hmm_config.refit_window,
            "train_frac": hmm_config.train_frac,
            "min_regime_length": hmm_config.min_regime_length,
            "feature_names": hmm_result.feature_names,
            "point_in_time_note": (
                "Filtered probabilities use forward filtering P(state_t|obs_1..obs_t). "
                "State-to-label mapping is post-hoc from fitted state mean returns."
            ),
        },
        "model": {
            "log_likelihood": float(hmm_result.log_likelihood),
            "n_iter": int(hmm_result.n_iter),
            "converged": bool(hmm_result.converged),
        },
        "regime_distribution": {str(k): int(v) for k, v in hmm_result.regimes.value_counts().to_dict().items()},
        "regime_performance": regime_perf,
        "regime_concentration": concentration,
        "bull_regime": {
            "n_observations": bull_obs,
            "sharpe_ratio": float(bull_sharpe) if bull_sharpe is not None else None,
        },
    }


def run_hmm_regime_hypothesis(data_path: Path = DATA_PATH) -> dict:
    if not data_path.exists():
        raise FileNotFoundError(f"Missing committed real-market fixture: {data_path}")

    df = load_data(str(data_path), symbol=SYMBOL)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    factory = _make_strategy_factory("sma_crossover")
    param_grid = {"fast_period": [20], "slow_period": [50]}

    wf = walk_forward_analysis(
        data=df,
        strategy_factory=factory,
        param_grid=param_grid,
        train_months=12,
        test_months=3,
        step_months=3,
        initial_capital=100000.0,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        validate_pit=True,
    )
    cpcv = cpcv_analysis(
        data=df,
        strategy_factory=factory,
        param_grid=param_grid,
        n_splits=5,
        test_size=0.2,
        initial_capital=100000.0,
        commission=COMMISSION,
        slippage=SLIPPAGE,
        validate_pit=True,
    )

    oos_returns = pd.Series(wf.get("oos_returns", pd.Series(dtype=float))).sort_index()
    oos_sharpe = _sharpe(oos_returns)
    oos_total = _total_return(oos_returns)

    hmm_report = _build_hmm_regime_report(oos_returns, df["close"])
    bull = hmm_report.get("bull_regime", {})
    bull_obs = int(bull.get("n_observations", 0) or 0)
    bull_sharpe = bull.get("sharpe_ratio")
    conc_class = (hmm_report.get("regime_concentration") or {}).get("regime_robustness")

    checks = {
        "oos_sharpe_gt_zero": bool(oos_sharpe is not None and np.isfinite(oos_sharpe) and oos_sharpe > 0.0),
        "oos_total_return_gt_zero": bool(oos_total is not None and np.isfinite(oos_total) and oos_total > 0.0),
        "bull_regime_sharpe_gt_zero": bool(
            bull_obs >= MIN_REGIME_OBS
            and bull_sharpe is not None
            and np.isfinite(float(bull_sharpe))
            and float(bull_sharpe) > 0.0
        ),
        "regime_concentration_not_fragile": bool(conc_class is not None and conc_class != "fragile"),
    }
    criteria = [
        {"name": name, "description": desc, "passed": checks[name]}
        for name, desc in CRITERIA
    ]
    all_pass = all(c["passed"] for c in criteria)
    verdict = "SUPPORTED" if all_pass else "NOT SUPPORTED"

    cpcv_summary = cpcv.get("summary", {}) if isinstance(cpcv, dict) else {}
    return {
        "hypothesis": HYPOTHESIS,
        "verdict": verdict,
        "all_pass": all_pass,
        "criteria": criteria,
        "data": {
            "path": str(data_path),
            "symbol": SYMBOL,
            "rows": int(len(df)),
            "start": str(df.index.min().date()),
            "end": str(df.index.max().date()),
        },
        "strategy": {
            "name": "sma_crossover",
            "params": {"fast_period": 20, "slow_period": 50},
            "commission": COMMISSION,
            "slippage": SLIPPAGE,
        },
        "walk_forward": {
            "train_months": 12,
            "test_months": 3,
            "step_months": 3,
            "n_periods": int((wf.get("summary") or {}).get("n_periods", 0) or 0),
            "oos_observations": int(len(oos_returns.dropna())),
            "oos_sharpe": float(oos_sharpe) if oos_sharpe is not None else None,
            "oos_total_return": float(oos_total) if oos_total is not None else None,
            "oos_ann_return": (wf.get("summary") or {}).get("oos_ann_return"),
            "oos_ann_vol": (wf.get("summary") or {}).get("oos_ann_vol"),
            "pit_passed": (wf.get("summary") or {}).get("point_in_time_validation", {}).get("passed")
            if isinstance((wf.get("summary") or {}).get("point_in_time_validation"), dict)
            else ((wf.get("summary") or {}).get("point_in_time_validation")),
        },
        "cpcv_diagnostic": {
            "n_splits": 5,
            "test_size": 0.2,
            "n_folds": int((cpcv_summary or {}).get("n_folds", 0) or 0),
            "oos_sharpe": cpcv_summary.get("oos_sharpe"),
            "oos_total_return": cpcv_summary.get("oos_total_return"),
            "note": "Secondary robustness diagnostic only; does not affect pre-registered verdict.",
        },
        "hmm_regime_analysis": hmm_report,
    }


def _print_report(result: dict) -> None:
    print("=" * 80)
    print("FALSIFIABLE HYPOTHESIS TEST: SMA CROSSOVER + HMM REGIME ANALYSIS")
    print("=" * 80)
    print(f"Hypothesis: {result['hypothesis']}")
    print(f"Data: {result['data']['path']} ({result['data']['rows']} rows, {result['data']['start']}..{result['data']['end']})")
    costs = result["strategy"]
    print(f"Strategy: {costs['name']} {json.dumps(costs['params'], sort_keys=True)}")
    print(f"Costs (net): commission={costs['commission']}, slippage={costs['slippage']} (3 bps round-trip)")

    wf = result["walk_forward"]
    print("\n1. WALK-FORWARD OOS (primary, net of costs)")
    print(f"  periods={wf['n_periods']} observations={wf['oos_observations']} PIT={wf.get('pit_passed')}")
    print(f"  Sharpe={_fmt_num(wf.get('oos_sharpe'))}  Total={_fmt_pct(wf.get('oos_total_return'))}")
    print(f"  AnnReturn={_fmt_pct(wf.get('oos_ann_return'))}  AnnVol={_fmt_pct(wf.get('oos_ann_vol'))}")

    hmm = result.get("hmm_regime_analysis", {})
    print("\n2. HMM REGIME ANALYSIS (pooled OOS window, point-in-time filtered probs)")
    model = hmm.get("model", {})
    print(f"  converged={model.get('converged')} log_likelihood={_fmt_num(model.get('log_likelihood'), 2)} iters={model.get('n_iter')}")
    dist = hmm.get("regime_distribution", {})
    print(f"  distribution={json.dumps(dist, sort_keys=True)}")
    perf = hmm.get("regime_performance", {})
    for regime in sorted(perf):
        m = perf[regime]
        print(
            f"  [{regime}] n={m.get('n_observations')} sharpe={_fmt_num(m.get('sharpe_ratio'))} "
            f"ann_ret={_fmt_pct(m.get('annualized_return'))} ann_vol={_fmt_pct(m.get('annualized_volatility'))} "
            f"max_dd={_fmt_pct(m.get('max_drawdown'))}"
        )
    conc = hmm.get("regime_concentration", {})
    print(f"  concentration={conc.get('regime_robustness')} note={conc.get('note')}")

    cpcv = result.get("cpcv_diagnostic", {})
    print("\n3. CPCV DIAGNOSTIC (secondary, not part of verdict)")
    print(f"  folds={cpcv.get('n_folds')} Sharpe={_fmt_num(cpcv.get('oos_sharpe'))} Total={_fmt_pct(cpcv.get('oos_total_return'))}")

    print("\n4. FALSIFICATION CRITERIA")
    for c in result["criteria"]:
        print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {c['name']}: {c['description']}")

    print("\n" + "=" * 80)
    print(f"VERDICT: {result['verdict']}")
    print("  SUPPORTED = all pre-registered criteria passed on this sample/configuration.")
    print("  NOT SUPPORTED = at least one criterion failed; this is a falsification outcome, not proof of no edge.")
    print("  No claim of profitability or production readiness is made.")
    print("=" * 80)


def main() -> int:
    result = run_hmm_regime_hypothesis()
    _print_report(result)
    return 0 if result["verdict"] in ("SUPPORTED", "NOT SUPPORTED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
