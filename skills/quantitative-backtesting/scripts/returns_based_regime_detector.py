#!/usr/bin/env python3
"""
Returns-based regime detector for fat_tail_crash at uniform tv=0.20.

Detects bear_high from cumulative negative returns instead of volatility
quantiles. Reuses detect_combined_regime machinery for trend/vol labels,
overwriting bear_high based on a cumulative-return threshold, then runs
walk_forward_analysis at uniform target_vol=0.20.

This script sweeps a small, pre-declared set of (window, threshold) settings so
we can check two things:
  1. Whether a sparse, crash-focused bear_high regime is achievable (report
     bear_high fraction and crash alignment: precision/recall vs the true
     jump-diffusion crash days recovered from the generator RNG).
  2. Whether the OOS Sharpe delta vs the uniform-tv=0.20 baseline changes with
     the regime labels. Because target_vol is uniform across all regimes, the
     position sizing is regime-independent; this sweep tests that invariance
     empirically rather than assuming it.

No profitability or statistical-significance claims; synthetic adversarial data.
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_adversarial_scenarios import ScenarioConfig, generate_fat_tail_crash  # noqa: E402
from regime_detection import (  # noqa: E402
    TrendRegime,
    VolatilityRegime,
    detect_trend_regime,
    detect_volatility_regime,
    regime_aware_position_size,
)
from strategy_builder import build_strategy  # noqa: E402
from walk_forward import walk_forward_analysis  # noqa: E402

BASELINE_PATH = Path(__file__).resolve().parent.parent.parent.parent / "adversarial_stress_test_results.json"
TARGET_VOL = 0.20
STRATEGIES = ["sma_crossover", "ema_crossover"]
RECOVERY_DAYS = 20  # bear_high persistence after a trigger, matches generator

STRATEGY_GRIDS = {
    "sma_crossover": {"param_grid": {"fast_period": [3, 5, 8], "slow_period": [10, 15, 20]}},
    "ema_crossover": {"param_grid": {"fast_period": [3, 5, 8], "slow_period": [10, 15, 20]}},
}


def _true_crash_days(config: ScenarioConfig) -> List[int]:
    """Replicate the generator's RNG stream to recover exact crash-day indices.

    Mirrors generate_fat_tail_crash's draw order (normal / recovery / crash).
    Used only for diagnostics (precision/recall), never for sizing.
    """
    rng = np.random.default_rng(config.seed)
    n = config.periods
    crash_days: List[int] = []
    in_recovery = 0
    for i in range(n):
        if in_recovery > 0:
            rng.normal(0.0, 0.015 * 2.0)
            in_recovery -= 1
        elif rng.random() < 0.002:
            rng.normal(-0.15, 0.05)
            in_recovery = 20
            crash_days.append(i)
        else:
            rng.normal(0.0005, 0.015)
    return crash_days


def detect_returns_based_regime(
    close: pd.Series,
    cum_return_window: int = 21,
    cum_return_threshold: float = -0.20,
    recovery_days: int = RECOVERY_DAYS,
    trend_ma_short: int = 50,
    trend_ma_long: int = 200,
    trend_threshold: float = 0.02,
    vol_quantile_high: float = 0.75,
    vol_quantile_low: float = 0.25,
    vol_window: int = 63,
) -> pd.Series:
    """
    Returns-based detector: standard combined regime, but bear_high is set
    whenever cumulative return over cum_return_window falls below
    cum_return_threshold. Other regimes from detect_combined_regime retained.
    """
    trend = detect_trend_regime(close, trend_ma_short, trend_ma_long, trend_threshold)
    vol = detect_volatility_regime(close, vol_window, vol_quantile_high, vol_quantile_low)

    combined = pd.Series("unknown", index=close.index)
    mask_known = (trend != TrendRegime.UNKNOWN.value) & (vol != VolatilityRegime.UNKNOWN.value)
    combined[mask_known] = trend[mask_known] + "_" + vol[mask_known]

    # Remove standard bear_* labels; re-derive bear_high from cumulative returns.
    combined = combined.where(~(combined.str.startswith("bear")), "unknown")

    # Fill warmup / medium-vol "unknown" gaps with the last known NON-bear regime
    # BEFORE stamping bear_high spans. Stamping bear_high first and ffill-ing
    # afterwards smeared the bear_high label forward through every trailing
    # "unknown" gap (e.g. the 200-bar trend warmup), inflating the bear_high
    # fraction and defeating the "sparse / crash-focused" goal.
    combined = combined.replace("unknown", np.nan).ffill().fillna("unknown")

    rets = close.pct_change()
    cum_ret = rets.rolling(cum_return_window).apply(lambda r: np.prod(1 + r) - 1, raw=True)
    crash_mask = (cum_ret < cum_return_threshold).fillna(False)
    crash_indices = crash_mask[crash_mask].index

    for crash_idx in crash_indices:
        crash_pos = close.index.get_loc(crash_idx)
        end_pos = min(crash_pos + recovery_days, len(close))
        combined.iloc[crash_pos:end_pos] = "bear_high"

    return combined


def _bear_stats(regimes: pd.Series, crash_days: List[int], window: int) -> Dict:
    """Sparse + crash-focused diagnostics for a candidate regime series."""
    n = len(regimes)
    bear_mask = (regimes == "bear_high").fillna(False)
    n_bars = int(bear_mask.sum())
    frac = 100.0 * n_bars / n if n else float("nan")

    # Trigger bars = bars where a new bear_high span begins.
    starts = bear_mask & ~bear_mask.shift(1, fill_value=False)
    trig_idx = np.where(starts.values)[0]

    crash_set = set(crash_days)
    tp = sum(1 for ti in trig_idx if any((ti - k) in crash_set for k in range(window)))
    precision = tp / len(trig_idx) if len(trig_idx) else float("nan")

    rec = sum(
        1 for cd in crash_days
        if any(ti <= cd <= ti + RECOVERY_DAYS - 1 for ti in trig_idx)
    )
    recall = rec / len(crash_days) if crash_days else float("nan")

    first = int(bear_mask.values.argmax()) if n_bars else None
    return {
        "bear_high_count": n_bars,
        "bear_high_fraction_pct": round(frac, 4),
        "trigger_count": int(len(trig_idx)),
        "first_bear_high_idx": first,
        "crash_precision": round(precision, 4) if precision == precision else None,
        "crash_recall": round(recall, 4) if recall == recall else None,
    }


def _run_strategy(strategy_name: str, data: pd.DataFrame, regimes: pd.Series,
                  baseline_sharpe, bear_high_vol=None) -> Dict:
    """Run one strategy through walk_forward with the regime overlay.

    If ``bear_high_vol`` is None, every regime gets ``TARGET_VOL`` (uniform,
    regime-independent sizing). Otherwise bear_high gets ``bear_high_vol`` and
    all other regimes get ``TARGET_VOL`` (differential, crash de-risking).
    """
    unique_regimes = [str(l) for l in pd.unique(regimes.dropna())]
    if bear_high_vol is None:
        target_by_regime = {label: TARGET_VOL for label in unique_regimes}
    else:
        target_by_regime = {
            label: (bear_high_vol if label == "bear_high" else TARGET_VOL)
            for label in unique_regimes
        }

    class RegimeAware:
        def __init__(self, base_strategy, regimes, target_by_regime):
            self.base = base_strategy
            self.config = base_strategy.config
            self.name = base_strategy.name
            self.parameters = base_strategy.parameters
            self.regimes = regimes
            self.target_by_regime = target_by_regime

        def generate_signals(self, d):
            base_sig = self.base.generate_signals(d)
            regimes_sub = self.regimes.reindex(d.index)
            return regime_aware_position_size(
                base_sig, d["close"], regimes_sub, self.target_by_regime,
                lookback=20, default_target_vol=TARGET_VOL,
                min_leverage=0.0, max_leverage=2.0,
            )

        def generate_target_weights(self, d=None):
            return None

    def factory(params, sn=strategy_name, rg=regimes, tb=target_by_regime):
        return RegimeAware(build_strategy(sn, json.dumps(params)), rg, tb)

    wf = walk_forward_analysis(
        data=data,
        strategy_factory=factory,
        param_grid=STRATEGY_GRIDS[strategy_name]["param_grid"],
        train_months=3, test_months=3, step_months=3,
        apply_deflation=True, validate_pit=True,
    )
    sharpe = wf["summary"].get("oos_sharpe")
    delta = (sharpe - baseline_sharpe) if (baseline_sharpe is not None and sharpe is not None) else None
    return {"oos_sharpe": sharpe, "delta": delta}


def run(sweep: bool = True) -> Dict:
    print("=" * 80)
    print("RETURNS-BASED REGIME DETECTION ON fat_tail_crash (uniform tv=0.20)")
    print("=" * 80)

    baseline_index = {}
    if BASELINE_PATH.exists():
        with open(BASELINE_PATH) as f:
            records = json.load(f)
        baseline_index = {
            (r["scenario"], r["strategy"]): r["walk_forward"]
            for r in records
            if r.get("walk_forward", {}).get("success")
        }
        print(f"Loaded baseline for {len(baseline_index)} pairs")

    config = ScenarioConfig(seed=42, periods=5000)
    data = generate_fat_tail_crash(config)
    if isinstance(data, pd.DataFrame) and "date" in data.columns:
        data = data.set_index("date")
        data.index = pd.DatetimeIndex(data.index)
    close = data["close"]

    crash_days = _true_crash_days(config)
    print(f"True crash days: {len(crash_days)} -> {crash_days}")

    # Settings: (window, threshold, label). First is the previous degenerate
    # setting reproduced for reference; the rest are sparser/crash-focused.
    settings: List[Tuple[int, float, str]] = [
        (63, -0.10, "prior_degenerate"),
        (21, -0.20, "sparse_21d_m20"),
        (21, -0.18, "sparse_21d_m18"),
        (10, -0.15, "sparse_10d_m15"),
    ]
    if not sweep:
        settings = [s for s in settings if s[2] == "sparse_21d_m20"]

    results = []
    for window, thr, label in settings:
        print(f"\n--- setting {label}: window={window}, threshold={thr} ---")
        regimes = detect_returns_based_regime(
            close, cum_return_window=window, cum_return_threshold=thr,
        )
        stats = _bear_stats(regimes, crash_days, window)
        print(f"    bear_high: count={stats['bear_high_count']} "
              f"frac={stats['bear_high_fraction_pct']}% "
              f"first={stats['first_bear_high_idx']} "
              f"precision={stats['crash_precision']} recall={stats['crash_recall']}")

        entry = {
            "setting": label,
            "cum_return_window": window,
            "cum_return_threshold": thr,
            "target_vol": TARGET_VOL,
            **stats,
            "strategies": {},
        }
        for strategy_name in STRATEGIES:
            base_wf = baseline_index.get(("fat_tail_crash", strategy_name), {})
            base_sharpe = base_wf.get("oos_sharpe") if isinstance(base_wf, dict) else None
            res = _run_strategy(strategy_name, data, regimes, base_sharpe)
            res["baseline_sharpe"] = base_sharpe
            entry["strategies"][strategy_name] = res
            print(f"    {strategy_name}: OOS Sharpe={res['oos_sharpe']}, "
                  f"baseline={base_sharpe}, delta={res['delta']}")
        results.append(entry)

    # --- Differential (per-regime) test on the sparse, crash-focused setting ---
    # The uniform sweep above shows OOS Sharpe is invariant to the regime labels
    # (target_vol is 0.20 for every regime). The remaining question is whether a
    # SPARSE, crash-focused bear_high with a LOWER target_vol during the crash
    # de-risks enough to beat uniform 0.20. Session 148 tested per-regime only
    # with a non-sparse detector; this isolates the sparse case.
    per_regime = []
    if sweep:
        primary = next(s for s in settings if s[2] == "sparse_21d_m20")
        window, thr, label = primary
        print(f"\n--- per-regime test on {label}: bear_high_vol=0.10, else 0.20 ---")
        regimes = detect_returns_based_regime(
            close, cum_return_window=window, cum_return_threshold=thr,
        )
        stats = _bear_stats(regimes, crash_days, window)
        print(f"    bear_high frac={stats['bear_high_fraction_pct']}% "
              f"precision={stats['crash_precision']} recall={stats['crash_recall']}")
        entry = {
            "setting": f"{label}_per_regime_bear010",
            "cum_return_window": window,
            "cum_return_threshold": thr,
            "bear_high_target_vol": 0.10,
            "other_target_vol": TARGET_VOL,
            **stats,
            "strategies": {},
        }
        for strategy_name in STRATEGIES:
            base_wf = baseline_index.get(("fat_tail_crash", strategy_name), {})
            base_sharpe = base_wf.get("oos_sharpe") if isinstance(base_wf, dict) else None
            res = _run_strategy(strategy_name, data, regimes, base_sharpe,
                                bear_high_vol=0.10)
            res["baseline_sharpe"] = base_sharpe
            entry["strategies"][strategy_name] = res
            print(f"    {strategy_name}: OOS Sharpe={res['oos_sharpe']}, "
                  f"baseline={base_sharpe}, delta={res['delta']}")
        per_regime.append(entry)

    out = {"fat_tail_crash_returns_based_sweep": results}
    if per_regime:
        out["fat_tail_crash_returns_based_per_regime"] = per_regime
    out_path = Path(__file__).resolve().parent.parent / "examples" / "returns_based_regime_results.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nResults saved to: {out_path}")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--single", action="store_true",
                        help="run only the primary sparse_21d_m20 setting")
    args = parser.parse_args()
    run(sweep=not args.single)