#!/usr/bin/env python3
"""
Hierarchical Risk Parity (HRP) portfolio allocation example.

Demonstrates a reproducible portfolio-construction workflow using
``hierarchical_risk_parity`` from ``scripts/utils.py`` on the committed
multi-asset panel fixture ``assets/example_data/sample_panel_ohlcv.csv``.

This is an allocation-layer utility (weights from historical returns), not a
trading-strategy backtest and not evidence of profitability. HRP (Lopez de
Prado, 2016) clusters assets by correlation distance and allocates by
inverse-variance within clusters; it is compared here to equal-weight and
inverse-volatility allocations on the same in-sample window purely as a
methodological illustration.

Offline only: all data is committed in the repository.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from data_loader import load_multi_symbol  # noqa: E402
from utils import hierarchical_risk_parity  # noqa: E402

DATA_PATH = SKILLS_DIR / "assets" / "example_data" / "sample_panel_ohlcv.csv"
OUT_DIR = Path(__file__).resolve().parent / "example_output"
OUT_JSON = OUT_DIR / "hrp_portfolio_allocation_example.json"


def _equal_weight(symbols):
    w = 1.0 / len(symbols)
    return pd.Series(w, index=symbols, dtype=float)


def _inverse_volatility(returns: pd.DataFrame) -> pd.Series:
    vol = returns.std().replace(0.0, np.nan)
    inv = 1.0 / vol
    inv = inv / inv.sum()
    return inv.fillna(0.0)


def _portfolio_stats(returns: pd.DataFrame, weights: pd.Series) -> dict:
    w = weights.reindex(returns.columns).fillna(0.0)
    port = (returns * w).sum(axis=1)
    ann_factor = 252.0
    mean = float(port.mean() * ann_factor)
    vol = float(port.std(ddof=1) * np.sqrt(ann_factor))
    sharpe = mean / vol if vol > 0 else 0.0
    cum = float((1.0 + port).prod() - 1.0)
    return {
        "annualized_return": mean,
        "annualized_volatility": vol,
        "sharpe_ratio": sharpe,
        "cumulative_return": cum,
    }


def main() -> int:
    panel, prov = load_multi_symbol(str(DATA_PATH), return_provenance=True)
    if not panel:
        raise SystemExit("No symbols loaded from panel fixture")

    closes = pd.DataFrame({sym: df["close"] for sym, df in panel.items()}).sort_index()
    returns = closes.pct_change().dropna(how="any")
    symbols = list(returns.columns)

    hrp = hierarchical_risk_parity(returns)
    ew = _equal_weight(symbols)
    iv = _inverse_volatility(returns)

    # Weight sanity checks (falsifiable properties of the allocator)
    assert abs(float(hrp.sum()) - 1.0) < 1e-10, f"HRP weights must sum to 1, got {hrp.sum()}"
    assert (hrp >= -1e-12).all(), f"HRP weights must be non-negative by default: {hrp.to_dict()}"

    corr = returns.corr()
    allocations = {
        "hrp": {"weights": hrp.to_dict(), "stats": _portfolio_stats(returns, hrp)},
        "equal_weight": {"weights": ew.to_dict(), "stats": _portfolio_stats(returns, ew)},
        "inverse_volatility": {"weights": iv.to_dict(), "stats": _portfolio_stats(returns, iv)},
    }

    result = {
        "example": "hrp_portfolio_allocation_example",
        "data_path": str(DATA_PATH.relative_to(SKILLS_DIR.parent)),
        "n_observations": int(len(returns)),
        "n_assets": int(len(symbols)),
        "symbols": symbols,
        "date_range": [str(returns.index.min()), str(returns.index.max())],
        "correlation_matrix": corr.round(6).to_dict(),
        "allocations": allocations,
        "notes": [
            "Illustrative in-sample allocation on a committed synthetic panel; not a backtest, not OOS, not evidence of profitability.",
            "HRP uses correlation-distance clustering and recursive inverse-variance bisection (Lopez de Prado, 2016).",
        ],
        "provenance_symbols_loaded": sorted(panel.keys()),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)

    print("HRP PORTFOLIO ALLOCATION EXAMPLE")
    print(f"Assets: {', '.join(symbols)}  |  Observations: {len(returns)}")
    print("\nWeights:")
    for name, payload in allocations.items():
        ws = payload["weights"]
        wstr = ", ".join(f"{k}={v:.4f}" for k, v in ws.items())
        s = payload["stats"]
        print(f"  {name}: {wstr}")
        print(f"    ann_ret={s['annualized_return']:.4f} ann_vol={s['annualized_volatility']:.4f} sharpe={s['sharpe_ratio']:.4f}")
    print(f"\nOutput: {OUT_JSON.relative_to(SKILLS_DIR)}")
    print("EXAMPLE COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
