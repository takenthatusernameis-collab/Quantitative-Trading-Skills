import json
from pathlib import Path

p = Path("skills/quantitative-backtesting/examples/adversarial_stress_test_regime_aware_extended.json")
d = json.loads(p.read_text())
print("Per-regime attribution: regime_sized vs baseline combined-regime Sharpe")
print(f"{'scenario':22}{'strategy':16}{'regime':14}{'base_sharpe':>12}{'sized_sharpe':>14}{'delta':>10}{'n_base':>8}{'n_sized':>9}")
for v in d["variants"]:
    b = v["baseline"].get("regime_analysis", {}).get("combined_regime_performance", {})
    r = v["regime_sized"].get("regime_analysis", {}).get("combined_regime_performance", {})
    for regime in sorted(set(b) | set(r)):
        bs = b.get(regime, {}).get("sharpe_ratio")
        rs = r.get(regime, {}).get("sharpe_ratio")
        nb = b.get(regime, {}).get("n_observations")
        nr = r.get(regime, {}).get("n_observations")
        delta = (rs - bs) if (bs is not None and rs is not None) else None
        print(f"{v['scenario']:22}{v['strategy']:16}{regime:14}{str(round(bs,3) if bs is not None else None):>12}{str(round(rs,3) if rs is not None else None):>14}{str(round(delta,3) if delta is not None else None):>10}{str(nb):>8}{str(nr):>9}")
