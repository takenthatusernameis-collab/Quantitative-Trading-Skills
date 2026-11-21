#!/usr/bin/env python3
"""
Diagnose WHY the regime-aware volatility-targeting overlay improves OOS
Sharpe on some adversarial scenarios but degrades it on others.

Part A (no recomputation): per-regime attribution from the committed
extended results -- baseline vs regime-sized Sharpe per combined regime,
with each regime's contribution to the total Sharpe delta.

Part B (cheap recomputation): regime detection lag -- regenerate each
scenario (seed=42, periods=5000, matching the sweep), run
detect_combined_regime with the shipped RegimeConfig, and compare detected
regime changes against each scenario's known truth transition.

Outputs are printed only; nothing is committed.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from generate_adversarial_scenarios import (  # noqa: E402
    generate_fat_tail_crash,
    generate_liquidity_crisis,
    generate_regime_shift,
    generate_structural_break,
    generate_trend_persistence,
    generate_volatility_clustering,
    ScenarioConfig,
)
from regime_detection import RegimeConfig, detect_combined_regime  # noqa: E402

EXTENDED = SKILLS_DIR / "examples" / "adversarial_stress_test_regime_aware_extended.json"

COMBINED_REGIMES = ["bull_low", "bull_high", "bear_low", "bear_high",
                    "sideways_low", "sideways_high"]

# Scenario-truth anchors (index in 5000-bar sample, seed=42)
TRUTH = {
    "regime_shift": {"bull_end": 18 * 21, "trans_end": (18 + 3) * 21,
                     "note": "bull 0-378, transition 378-441 (3x vol), bear after 441"},
    "structural_break": {"break": 2500,
                         "note": "pre drift +0.0005/vol 0.015; post drift -0.0003/vol 0.025"},
    "liquidity_crisis": {"crisis_start": 3000, "crisis_end": 3126,
                         "note": "crisis 3000-3126 (5x vol, decaying volume)"},
    "trend_persistence": {"note": "single regime: drift 0.001, vol 0.008; no truth change"},
    "fat_tail_crash": {"note": "~1 crash/500 days (p=0.002), crash mean -0.15, 20-day 2x recovery"},
    "volatility_clustering": {"note": "Markov clusters p=0.02, persistence 0.95, cluster vol 0.03 vs base 0.01"},
}

IMPROVING = ["regime_shift", "liquidity_crisis", "structural_break", "trend_persistence"]
DEGRADING = ["volatility_clustering", "fat_tail_crash"]


def fmt(x):
    return "n/a" if x is None else f"{x:+.4f}"


def part_a_attribution(extended):
    print("=" * 100)
    print("PART A -- PER-REGIME ATTRIBUTION (baseline vs regime-sized, target_vol=0.10)")
    print("=" * 100)

    agg = {r: {"improving": [], "degrading": []} for r in COMBINED_REGIMES}

    for rec in extended["variants"]:
        sc, st = rec["scenario"], rec["strategy"]
        base_ra = rec["baseline"].get("regime_analysis", {}) or {}
        ra_ra = rec["regime_sized"].get("regime_analysis", {}) or {}
        base_crp = base_ra.get("combined_regime_performance", {}) or {}
        ra_crp = ra_ra.get("combined_regime_performance", {}) or {}

        base_sharpe = rec["baseline"].get("oos_sharpe")
        ra_sharpe = rec["regime_sized"].get("oos_sharpe")
        total_delta = (ra_sharpe - base_sharpe) if (base_sharpe is not None and ra_sharpe is not None) else 0.0

        print(f"\n[{sc:22s} | {st:14s}] baseline Sharpe {fmt(base_sharpe)}  "
              f"regime-sized Sharpe {fmt(ra_sharpe)}  delta {fmt(total_delta)}")
        print(f"  {'regime':<14} {'base Sharpe':>12} {'ra Sharpe':>12} {'delta':>10} "
              f"{'n_obs':>8} {'weight':>8} {'contrib':>10}")

        total_n = 0
        for r in COMBINED_REGIMES:
            bm = base_crp.get(r, {}) or {}
            rm = ra_crp.get(r, {}) or {}
            n_obs = rm.get("n_observations", bm.get("n_observations", 0))
            total_n += n_obs

        for r in COMBINED_REGIMES:
            bm = base_crp.get(r, {}) or {}
            rm = ra_crp.get(r, {}) or {}
            b_sharpe = bm.get("sharpe_ratio")
            r_sharpe = rm.get("sharpe_ratio")
            n_obs = rm.get("n_observations", bm.get("n_observations", 0))
            weight = n_obs / total_n if total_n else 0.0
            delta = (r_sharpe - b_sharpe) if (b_sharpe is not None and r_sharpe is not None) else None
            contrib = delta * weight if delta is not None else None
            group = "improving" if sc in IMPROVING else "degrading"
            if delta is not None:
                agg[r][group].append(delta)
            print(f"  {r:<14} {fmt(b_sharpe):>12} {fmt(r_sharpe):>12} "
                  f"{fmt(delta):>10} {n_obs:>8} {weight:>8.3f} {fmt(contrib):>10}")

    print("\n" + "=" * 100)
    print("AGGREGATE: mean per-regime Sharpe delta, improving vs degrading scenarios")
    print("=" * 100)
    print(f"  {'regime':<14} {'improving mean dSharpe':>24} {'n':>4} | {'degrading mean dSharpe':>24} {'n':>4}")
    for r in COMBINED_REGIMES:
        inc = agg[r]["improving"]
        dec = agg[r]["degrading"]
        im = np.mean(inc) if inc else None
        dm = np.mean(dec) if dec else None
        print(f"  {r:<14} {fmt(im):>24} {len(inc):>4} | {fmt(dm):>24} {len(dec):>4}")


def part_b_lag():
    print("\n" + "=" * 100)
    print("PART B -- REGIME DETECTION LAG (regenerated, seed=42, periods=5000)")
    print("=" * 100)

    gens = {
        "regime_shift": lambda cfg: generate_regime_shift(cfg, bull_months=18, bear_months=18, transition_months=3),
        "structural_break": lambda cfg: generate_structural_break(cfg),
        "liquidity_crisis": lambda cfg: generate_liquidity_crisis(cfg),
        "trend_persistence": lambda cfg: generate_trend_persistence(cfg),
        "fat_tail_crash": lambda cfg: generate_fat_tail_crash(cfg),
        "volatility_clustering": lambda cfg: generate_volatility_clustering(cfg),
    }

    cfg = ScenarioConfig(seed=42, periods=5000)
    for sc, gen in gens.items():
        data = gen(cfg)
        if isinstance(data, pd.DataFrame) and "date" in data.columns:
            data = data.set_index("date")
        close = data["close"]
        rets = close.pct_change().dropna()

        regimes = detect_combined_regime(close, config=RegimeConfig())
        changes = regimes[regimes != regimes.shift()].index
        labels = regimes.loc[changes].tolist()

        print(f"\n--- {sc}: {TRUTH[sc]['note']}")
        print(f"  detected regime changes: {len(changes)}")
        for dt, lab in list(zip(changes, labels))[:12]:
            pos = close.index.get_loc(dt)
            print(f"    {dt.date()} (bar {pos:5d}) -> {lab}")
        if len(changes) > 12:
            print(f"    ... ({len(changes)-12} more changes)")

        # Truth anchors
        if sc == "regime_shift":
            for anchor, label in [(378, "transition start"), (441, "bear start")]:
                dt = close.index[anchor]
                print(f"  truth {label} at bar {anchor} ({dt.date()}); detected regime there: {regimes.iloc[anchor]}")
        elif sc == "structural_break":
            anchor = 2500
            dt = close.index[anchor]
            print(f"  truth break at bar {anchor} ({dt.date()}); detected regime there: {regimes.iloc[anchor]}")
        elif sc == "liquidity_crisis":
            for anchor, label in [(3000, "crisis start"), (3126, "crisis end")]:
                dt = close.index[min(anchor, len(close) - 1)]
                print(f"  truth {label} at bar {anchor} ({dt.date()}); detected regime there: {regimes.iloc[min(anchor, len(close) - 1)]}")

        # Fat-tail: crash-day detection lag
        if sc == "fat_tail_crash":
            crash_days = rets.index[rets < -0.05]
            print(f"  crash days (<-5%): {len(crash_days)}")
            for dt in crash_days[:6]:
                pos = close.index.get_loc(dt)
                lab_at = regimes.iloc[pos]
                lab_after = regimes.iloc[min(pos + 5, len(regimes) - 1)]
                print(f"    crash {dt.date()} (bar {pos}); regime at crash: {lab_at}, +5d: {lab_after}")

        # Vol clustering: high-regime persistence
        if sc == "volatility_clustering":
            high = regimes.str.contains("_high", na=False)
            runs = (high != high.shift()).cumsum()[high]
            run_lengths = runs.value_counts().sort_index() if len(runs) else pd.Series(dtype=int)
            print(f"  high-vol runs: {len(run_lengths)}, median length {run_lengths.median():.0f} bars "
                  f"(expected ~20 at persistence 0.95), total high-vol bars {int(high.sum())}")


def main():
    with open(EXTENDED) as f:
        extended = json.load(f)
    print(f"Loaded {len(extended['variants'])} variants; target_vol={extended['target_vol']}")
    print(f"Verdict: {extended['verdict']} (improved {extended['n_improved']}/{extended['n_evaluable']})")
    part_a_attribution(extended)
    part_b_lag()


if __name__ == "__main__":
    main()
