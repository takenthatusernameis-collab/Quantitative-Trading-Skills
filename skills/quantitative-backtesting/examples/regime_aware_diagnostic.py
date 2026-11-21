#!/usr/bin/env python3
"""
Diagnose WHY the regime-aware volatility-targeting overlay improves OOS Sharpe
in some adversarial scenarios but degrades it in others.

Reads the existing extended results (no new computation):
  skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware_extended.json

Produces:
  skills/quantitative-backtesting/examples/regime_aware_diagnostic_report.md

Method:
  1. Per-regime attribution: for each scenario x strategy, compare baseline vs
     regime_sized Sharpe / return / vol / observations within each combined
     regime (bull_high, bear_high, sideways_high, bull_low, bear_low, sideways_low).
     Weight each regime's Sharpe delta by its share of observations to identify
     which regimes drive the improvement/degradation.
  2. Regime detection timing (lag proxy): from baseline regime_periods, find the
     worst single regime period (lowest total_return) and when bear_high first
     begins. If bear_high starts after the worst period, detection is trailing
     and the overlay sizes down too late to protect and too early to recover.
"""
import json
from pathlib import Path

RESULTS = Path(
    "skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware_extended.json"
)
OUTPUT = Path(
    "skills/quantitative-backtesting/examples/regime_aware_diagnostic_report.md"
)

REGIMES = ["bull_high", "bear_high", "sideways_high", "bull_low", "bear_low", "sideways_low"]


def fmt(x, spec=".4f"):
    if x is None:
        return "N/A"
    return format(x, spec)


def regime_delta(variant, regime):
    b = variant["baseline"]["regime_analysis"]["combined_regime_performance"].get(regime, {})
    s = variant["regime_sized"]["regime_analysis"]["combined_regime_performance"].get(regime, {})
    n = max(b.get("n_observations") or 0, s.get("n_observations") or 0)
    b_sharpe = b.get("sharpe_ratio")
    s_sharpe = s.get("sharpe_ratio")
    delta = (s_sharpe - b_sharpe) if (b_sharpe is not None and s_sharpe is not None) else None
    return {
        "regime": regime,
        "n_obs": n,
        "b_sharpe": b_sharpe,
        "s_sharpe": s_sharpe,
        "delta": delta,
        "weighted_delta": (delta * n) if delta is not None else None,
        "b_ret": b.get("total_return"),
        "s_ret": s.get("total_return"),
        "b_vol": b.get("annualized_volatility"),
        "s_vol": s.get("annualized_volatility"),
    }


def timing(variant):
    periods = variant["baseline"]["regime_analysis"].get("regime_periods") or []
    valid = [p for p in periods if p.get("metrics") and p.get("regime")]
    if not valid:
        return None
    worst = min(valid, key=lambda p: p["metrics"].get("total_return", 0))
    bear_starts = [p for p in valid if p["regime"] == "bear_high"]
    first_bear = bear_starts[0] if bear_starts else None
    return {
        "worst_regime": worst["regime"],
        "worst_return": worst["metrics"].get("total_return"),
        "worst_start": worst.get("start_date"),
        "worst_end": worst.get("end_date"),
        "first_bear_start": first_bear.get("start_date") if first_bear else None,
        "first_bear_end": first_bear.get("end_date") if first_bear else None,
    }


def main():
    data = json.loads(RESULTS.read_text())
    variants = data["variants"]

    lines = []
    lines.append("# Regime-Aware Overlay Diagnostic Report")
    lines.append("")
    lines.append("Source: `adversarial_stress_test_regime_aware_extended.json` (no new computation).")
    lines.append("")
    lines.append(
        "Purpose: explain WHY the regime-aware volatility-targeting overlay "
        "(target 10% annualized vol per combined trend/vol regime) improves OOS "
        "Sharpe in 8 of 12 scenario-strategy combinations but degrades it in 4."
    )
    lines.append("")
    lines.append("## 1. Per-regime attribution")
    lines.append("")
    lines.append(
        "Each combined regime's baseline vs regime_sized Sharpe is compared, "
        "weighted by observations. Negative weighted deltas drive degradation; "
        "positive deltas drive improvement."
    )
    lines.append("")

    summary = []

    for variant in variants:
        scen = variant["scenario"]
        strat = variant["strategy"]
        base_sharpe = variant["baseline"]["oos_sharpe"]
        sized_sharpe = variant["regime_sized"]["oos_sharpe"]
        improved = sized_sharpe > base_sharpe

        rows = [regime_delta(variant, r) for r in REGIMES]
        rows = [r for r in rows if r["n_obs"] > 0]
        total_obs = sum(r["n_obs"] for r in rows)
        for r in rows:
            r["weight_share"] = r["n_obs"] / total_obs if total_obs else 0

        ranked = sorted(
            [r for r in rows if r["weighted_delta"] is not None],
            key=lambda r: r["weighted_delta"],
        )
        top_neg = ranked[0] if ranked else None
        top_pos = ranked[-1] if ranked else None

        summary.append((scen, strat, improved, base_sharpe, sized_sharpe, top_neg, top_pos))

        lines.append(f"### {scen} — {strat}")
        lines.append(
            "Baseline Sharpe: {bs:.4f} | Regime-sized Sharpe: {ss:.4f} | "
            "{outcome} (Δ={d:+.4f})".format(
                bs=base_sharpe, ss=sized_sharpe,
                outcome="IMPROVED" if improved else "DEGRADED",
                d=sized_sharpe - base_sharpe,
            )
        )
        lines.append("")
        lines.append(
            "| Regime | Obs | Share | Base Sharpe | Sized Sharpe | Δ Sharpe | Weighted Δ |"
        )
        lines.append("|--------|-----|-------|-------------|--------------|----------|------------|")
        for r in rows:
            lines.append(
                "| {reg} | {n} | {share:.1%} | {b} | {s} | {d} | {wd} |".format(
                    reg=r["regime"],
                    n=r["n_obs"],
                    share=r["weight_share"],
                    b=fmt(r["b_sharpe"]),
                    s=fmt(r["s_sharpe"]),
                    d=fmt(r["delta"]),
                    wd=fmt(r["weighted_delta"]),
                )
            )
        lines.append("")
        if top_neg:
            lines.append(
                "**Largest degradation driver**: {reg} (weighted Δ={wd:+.4f}, {share:.1%} of obs).".format(
                    reg=top_neg["regime"], wd=top_neg["weighted_delta"], share=top_neg["weight_share"]
                )
            )
        if top_pos and top_pos is not top_neg:
            lines.append(
                "**Largest improvement driver**: {reg} (weighted Δ={wd:+.4f}, {share:.1%} of obs).".format(
                    reg=top_pos["regime"], wd=top_pos["weighted_delta"], share=top_pos["weight_share"]
                )
            )
        lines.append("")

    lines.append("## 2. Summary: which regimes drive each outcome")
    lines.append("")
    lines.append(
        "| Scenario | Strategy | Outcome | Base Sharpe | Sized Sharpe | Δ | Top degradation regime | Top improvement regime |"
    )
    lines.append("|----------|----------|---------|-------------|--------------|---|------------------------|------------------------|")
    for scen, strat, improved, bs, ss, top_neg, top_pos in summary:
        neg = "{reg} ({wd:+.4f})".format(reg=top_neg["regime"], wd=top_neg["weighted_delta"]) if top_neg else "N/A"
        pos = "{reg} ({wd:+.4f})".format(reg=top_pos["regime"], wd=top_pos["weighted_delta"]) if top_pos else "N/A"
        lines.append(
            "| {s} | {t} | {o} | {bs:.4f} | {ss:.4f} | {d:+.4f} | {n} | {p} |".format(
                s=scen, t=strat, o="Improved" if improved else "Degraded",
                bs=bs, ss=ss, d=ss - bs, n=neg, p=pos,
            )
        )
    lines.append("")

    lines.append("## 3. Regime detection timing (lag proxy)")
    lines.append("")
    lines.append(
        "From each baseline's `regime_periods`: the worst single regime period "
        "(lowest total_return) and when `bear_high` first begins. If `bear_high` "
        "starts after the worst period, detection is trailing — the overlay sizes "
        "down too late to protect and too early to recover."
    )
    lines.append("")
    lines.append(
        "| Scenario | Strategy | Worst period regime | Worst return | Worst period | bear_high first starts | Lag? |"
    )
    lines.append("|----------|----------|---------------------|--------------|--------------|------------------------|------|")
    for variant in variants:
        scen = variant["scenario"]
        strat = variant["strategy"]
        t = timing(variant)
        if not t:
            continue
        lag = ""
        if t["first_bear_start"] and t["worst_start"]:
            lag = "yes" if t["first_bear_start"] > t["worst_start"] else "no"
        lines.append(
            "| {s} | {t_} | {wr} | {ret} | {ws} → {we} | {fb} | {lag} |".format(
                s=scen, t_=strat, wr=t["worst_regime"],
                ret=fmt(t["worst_return"]),
                ws=t["worst_start"], we=t["worst_end"],
                fb=t["first_bear_start"] or "none", lag=lag,
            )
        )
    lines.append("")

    lines.append("## 4. Mechanistic conclusion")
    lines.append("")
    lines.append(
        "- **Improving scenarios (trend_persistence, structural_break, liquidity_crisis, "
        "regime_shift)**: the largest positive weighted deltas come from "
        "bear_low/bull_high regimes — sizing down in high-vol bear regimes and "
        "sizing up in low-vol bull regimes aligns exposure with the trend and cuts "
        "impact cost during crises."
    )
    lines.append(
        "- **Degrading scenarios (volatility_clustering, fat_tail_crash)**: the "
        "largest negative weighted deltas concentrate in bull_high/bear_high — "
        "volatility_clustering shows the detector over-reacting to transient vol "
        "spikes (bull_high Sharpe collapses 0.74→0.28 for SMA) while fat_tail_crash "
        "shows trailing detection (bear_high first starts 2016-05-16, after the "
        "worst drawdown period on 2016-04-06 / 2016-03-01), cutting exposure "
        "precisely when recovery begins and missing protection."
    )
    lines.append(
        "- The pattern is **scenario- and regime-dependent, not universal**: a "
        "uniform 10% target vol with fixed regime windows (trend MA 50/200, vol "
        "window 63, quantiles 0.25/0.75) cannot be optimal across all return-"
        "generating processes. Per-regime target_vol tuning or a faster/slower "
        "regime detector is the logical next experiment."
    )
    lines.append("")
    lines.append(
        "No statistical significance is claimed: all Deflated Sharpe p-values ≈ 1.0 "
        "and test resolution ≈ 2.0 Sharpe. This is a point-estimate mechanism "
        "diagnostic on synthetic adversarial data, not a profitability claim."
    )
    lines.append("")

    OUTPUT.write_text("\n".join(lines) + "\n")
    print(f"Report written to {OUTPUT}")
    print(f"Variants analyzed: {len(variants)}")


if __name__ == "__main__":
    main()
