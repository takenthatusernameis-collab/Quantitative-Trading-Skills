#!/usr/bin/env python3
"""
Diagnostic: characterize cumulative-return distribution on fat_tail_crash and
evaluate candidate (window, threshold) settings for a returns-based bear_high
detector.

Goal: choose settings where bear_high is SPARSE (small fraction of bars) and
crash-focused (concentrated around true crash events), not triggered by ordinary
Gaussian drawdowns. No profitability claim; synthetic adversarial data only.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_adversarial_scenarios import ScenarioConfig, generate_fat_tail_crash


def true_crash_days(config, normal_drift=0.0005, normal_vol=0.015,
                    crash_probability=0.002, crash_mean=-0.15, crash_vol=0.05,
                    recovery_days=20):
    """Replicate the generator's RNG stream to recover exact crash-day indices."""
    rng = np.random.default_rng(config.seed)
    n = config.periods
    crash_days = []
    in_recovery = 0
    for i in range(n):
        if in_recovery > 0:
            rng.normal(0.0, normal_vol * 2.0)  # recovery_vol_multiplier=2.0
            in_recovery -= 1
        elif rng.random() < crash_probability:
            rng.normal(crash_mean, crash_vol)
            in_recovery = recovery_days
            crash_days.append(i)
        else:
            rng.normal(normal_drift, normal_vol)
    return crash_days


def main():
    config = ScenarioConfig(seed=42, periods=5000)
    data = generate_fat_tail_crash(config)
    if isinstance(data, pd.DataFrame) and "date" in data.columns:
        data = data.set_index("date")
        data.index = pd.DatetimeIndex(data.index)
    close = data["close"]
    n = len(close)

    crash_days = true_crash_days(config)
    print(f"n={n} bars; true crash days detected: {len(crash_days)}")
    print(f"crash day indices (first 20): {crash_days[:20]}")

    rets = close.pct_change()

    # Candidate windows/thresholds to evaluate.
    candidates = []
    for window in [10, 21, 42, 63]:
        for thr in [-0.08, -0.10, -0.12, -0.15, -0.18, -0.20, -0.25]:
            candidates.append((window, thr))

    print("\nDistribution of cumulative returns by window (normal vs all):")
    cum_by_window = {}
    for window in [10, 21, 42, 63]:
        cum = rets.rolling(window).apply(lambda r: np.prod(1 + r) - 1, raw=True)
        cum_by_window[window] = cum
        q = cum.quantile([0.001, 0.01, 0.05, 0.10, 0.25, 0.5]).to_dict()
        print(f"  window={window:>2}: " + "  ".join(f"q{int(k*100):>2}={v:+.3f}" for k, v in q.items()))

    # Recovery window (recovery_days=20) applied per trigger, matching detector.
    recovery_days = 20

    print("\nCandidate (window, threshold) -> bear_high stats:")
    print(f"{'win':>3} {'thr':>6} {'trig':>5} {'bars':>6} {'frac%':>6} {'precision':>9} {'recall':>7}")
    # A trigger bar is "true positive" if a crash occurred within
    # [trigger-window+1 .. trigger] (crash is inside the lookback window).
    for window, thr in candidates:
        cum = cum_by_window[window]
        crash_mask = cum < thr
        crash_mask = crash_mask.fillna(False)
        trig_idx = np.where(crash_mask.values)[0]

        # Build bear_high bar mask (expand each trigger by recovery_days).
        bear = np.zeros(n, dtype=bool)
        for ti in trig_idx:
            bear[ti:min(ti + recovery_days, n)] = True

        n_trig = len(trig_idx)
        n_bars = int(bear.sum())
        frac = 100.0 * n_bars / n

        # precision: fraction of triggers whose lookback window contains a crash
        crash_set = set(crash_days)
        tp = 0
        for ti in trig_idx:
            window_contains_crash = any((ti - k) in crash_set for k in range(window))
            if window_contains_crash:
                tp += 1
        precision = tp / n_trig if n_trig else float("nan")

        # recall: fraction of crash days that fall inside at least one bear_high span
        rec = 0
        for cd in crash_days:
            # is there a trigger t with t <= cd <= t+recovery_days-1 and crash in [t-window+1,t]?
            hit = False
            for ti in trig_idx:
                if ti <= cd <= ti + recovery_days - 1:
                    hit = True
                    break
            if hit:
                rec += 1
        recall = rec / len(crash_days) if crash_days else float("nan")

        print(f"{window:>3} {thr:>+6.2f} {n_trig:>5} {n_bars:>6} {frac:>6.2f} {precision:>9.2f} {recall:>7.2f}")

    # Focused view: sparse candidates only (frac <= ~10%).
    print("\nSparse candidates (bear_high fraction <= 12%):")
    print(f"{'win':>3} {'thr':>6} {'trig':>5} {'bars':>6} {'frac%':>6} {'precision':>9} {'recall':>7}")
    for window, thr in candidates:
        cum = cum_by_window[window]
        crash_mask = (cum < thr).fillna(False)
        trig_idx = np.where(crash_mask.values)[0]
        bear = np.zeros(n, dtype=bool)
        for ti in trig_idx:
            bear[ti:min(ti + recovery_days, n)] = True
        frac = 100.0 * bear.sum() / n
        if frac <= 12.0:
            n_trig = len(trig_idx)
            crash_set = set(crash_days)
            tp = sum(1 for ti in trig_idx if any((ti - k) in crash_set for k in range(window)))
            precision = tp / n_trig if n_trig else float("nan")
            rec = 0
            for cd in crash_days:
                if any(ti <= cd <= ti + recovery_days - 1 for ti in trig_idx):
                    rec += 1
            recall = rec / len(crash_days)
            print(f"{window:>3} {thr:>+6.2f} {n_trig:>5} {int(bear.sum()):>6} {frac:>6.2f} {precision:>9.2f} {recall:>7.2f}")


if __name__ == "__main__":
    main()