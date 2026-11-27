#!/usr/bin/env python3
"""Reproducible statistical-power assessment of single-asset walk-forward tests."""
import importlib.util
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS / "scripts"))
import walk_forward as wf

TESTS = SKILLS / "tests"
FILES = [
    "test_walk_forward_sma_crossover_real_aapl.py",
    "test_walk_forward_time_series_momentum_real_aapl.py",
    "test_walk_forward_zscore_real_aapl_msft.py",
    "test_walk_forward_bollinger_real_aapl.py",
    "test_walk_forward_donchian_real_aapl.py",
    "test_walk_forward_ema_crossover_real_aapl.py",
    "test_walk_forward_kelly_criterion_real_aapl.py",
    "test_walk_forward_macd_real_aapl.py",
    "test_walk_forward_rsi_real_aapl.py",
    "test_walk_forward_rsi_mean_reversion_real_aapl.py",
    "test_walk_forward_simple_momentum_real_aapl.py",
    "test_walk_forward_volatility_targeting_real_aapl.py",
    "test_walk_forward_zscore_mean_reversion_real_aapl.py",
    "test_walk_forward_time_series_momentum_real_googl.py",
    "test_walk_forward_time_series_momentum_real_msft.py",
]

rows = []
for fn in FILES:
    path = TESTS / fn
    spec = importlib.util.spec_from_file_location(fn[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    captured = {}
    orig = mod.walk_forward_analysis if hasattr(mod, "walk_forward_analysis") else None
    # patch after module load by preloading walk_forward symbol
    spec.loader.exec_module(mod)
    orig_wf = mod.walk_forward_analysis

    def patched(*a, **kw):
        s = orig_wf(*a, **kw)
        captured["result"] = s
        return s

    mod.walk_forward_analysis = patched
    # find test runner function
    runners = [n for n in dir(mod) if n.endswith("_runs")]
    print("RUNNERS", fn, runners, file=sys.stderr)
    for r in runners:
        try:
            getattr(mod, r)()
        except Exception as e:
            print("ERR", fn, repr(e), file=sys.stderr)
    s = captured.get("result", {})
    if not isinstance(s, dict):
        s = {}
    summary = s.get("summary", {}) if isinstance(s.get("summary"), dict) else {}
    tr = summary.get("test_resolution", {}) if isinstance(summary, dict) else {}
    rows.append({
        "file": fn,
        "oos_sharpe": summary.get("oos_sharpe") if isinstance(summary, dict) else None,
        "total_oos_return": summary.get("total_oos_return") if isinstance(summary, dict) else None,
        "deflated_sharpe_pvalue": (summary.get("deflated_sharpe", {}) or {}).get("p_value") if isinstance(summary, dict) else None,
        "test_resolution": tr,
    })

out = Path(__file__).resolve().parent.parent / "results" / "single_asset_power_assessment.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(rows, indent=2, default=str))
print(json.dumps(rows, indent=2, default=str)[:4000])