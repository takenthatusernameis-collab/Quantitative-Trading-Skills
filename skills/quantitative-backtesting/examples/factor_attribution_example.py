#!/usr/bin/env python3
"""
Worked example: Fama-MacBeth cross-sectional factor attribution on committed real data.

Loads the committed real-market triple panel (AAPL / MSFT / GOOGL), runs a
Fama-MacBeth (1973) two-step cross-sectional regression of each asset's
next-period return on its lagged return (a naive momentum/reversal exposure
known one bar in advance, so the test is point-in-time correct), and reports:

  * the average cross-sectional factor premium (lambda_hat) with t-statistic
    (Newey-West HAC standard error),
  * the number of valid periods,
  * a factor-vs-idiosyncratic return decomposition (explained variance ratio).

This is a demonstration of the factor-models machinery
(skills/quantitative-backtesting/scripts/factor_models.py) on real committed
data. With only three assets the cross-section is thin, so the numbers are
illustrative and underpowered: they describe the sample, not a tradable edge.
No profitability or robustness claim is made. All inputs are committed local
files; no network access is required.

Outputs a JSON artifact to --output (defaults to a temporary directory) and
prints a human-readable report to stdout.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

from data_loader import load_data  # noqa: E402
from factor_models import (  # noqa: E402
    fama_macbeth,
    factor_contribution_decomposition,
)

SYMBOLS = ["AAPL", "MSFT", "GOOGL"]
DATA_DIR = Path(__file__).resolve().parent.parent / "assets" / "example_data" / "real_market_data"


def load_panel(symbols, data_dir):
    """Load one file per symbol and align closes on their common date index."""
    closes = {}
    for sym in symbols:
        df = load_data(str(data_dir / f"{sym}.csv"), symbol=sym)
        closes[sym] = df["close"]
    close = pd.DataFrame(closes).sort_index()
    close = close.dropna(how="any")
    return close


def build_exposures(returns):
    """Point-in-time factor exposures: each asset's lagged one-day return.

    The exposure used to explain return[t] is return[t-1], so no future
    information leaks into the cross-sectional regression at time t.
    """
    lagged = returns.shift(1)
    aligned = pd.concat(
        [returns.rename_axis("date"), lagged.rename_axis("date")],
        axis=1,
        keys=["returns", "exposure"],
    ).dropna()
    rets = aligned.xs("returns", axis=1, level=0).sort_index()
    exps = aligned.xs("exposure", axis=1, level=0).sort_index()
    return rets.values, exps.values


def run_factor_attribution(symbols=SYMBOLS, data_dir=DATA_DIR, output=None):
    """Execute the factor-attribution worked example and return the results."""
    close = load_panel(symbols, data_dir)
    returns = close.pct_change()

    asset_returns, exposures = build_exposures(returns)
    exposures_3d = exposures[:, :, None]

    # Cross-sectional OLS per period, then time-series mean + Newey-West t-stat.
    result = fama_macbeth(asset_returns, exposures_3d, newey_west=True)

    # Decompose returns into factor contribution vs idiosyncratic residual.
    decomposition = factor_contribution_decomposition(
        asset_returns, exposures_3d, result["lambda_hat"]
    )

    summary = {
        "symbols": symbols,
        "n_periods": int(result["n_periods"]),
        "n_assets": int(asset_returns.shape[1]),
        "n_factors": int(exposures_3d.shape[2]),
        "lambda_hat": [float(v) for v in result["lambda_hat"]],
        "t_stats": [float(v) if v is not None and np.isfinite(v) else None
                    for v in result["t_stats"]],
        "se": [float(v) if v is not None and np.isfinite(v) else None
               for v in result["se"]],
        "bandwidth": result["bandwidth"],
        "explained_variance_ratio": float(decomposition["explained_variance_ratio"]),
        "residual_std": float(decomposition["residual_std"]),
        "data_range": [str(close.index.min()), str(close.index.max())],
        "note": ("Illustrative only: three-asset cross-section is thin and "
                 "underpowered; no profitability claim."),
    }

    if output is not None:
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        artifact = output / "factor_attribution.json"
        artifact.write_text(json.dumps(summary, indent=2) + "\n")
        summary["artifact"] = str(artifact)

    return summary


def print_report(summary):
    print("=" * 72)
    print("FAMA-MACBETH CROSS-SECTIONAL FACTOR ATTRIBUTION (WORKED EXAMPLE)")
    print("=" * 72)
    print(f"Symbols:        {', '.join(summary['symbols'])}")
    print(f"Data range:     {summary['data_range'][0]} -> {summary['data_range'][1]}")
    print(f"N assets:       {summary['n_assets']}")
    print(f"N periods:      {summary['n_periods']}")
    print(f"N factors:      {summary['n_factors']}")
    print()
    print("Factor premium (lambda_hat) and Newey-West t-statistic:")
    for k in range(summary["n_factors"]):
        lam = summary["lambda_hat"][k]
        t = summary["t_stats"][k]
        se = summary["se"][k]
        t_str = f"{t: .3f}" if t is not None else "n/a"
        se_str = f"{se:.6f}" if se is not None else "n/a"
        print(f"  factor {k}: lambda = {lam:+.6f},  t = {t_str},  se = {se_str}")
    print()
    print(f"Bandwidth:      {summary['bandwidth']}")
    print(f"Explained var.: {summary['explained_variance_ratio']:.4f}")
    print(f"Residual std:   {summary['residual_std']:.6f}")
    print()
    print("NOTE: illustrative only -- three-asset cross-section is thin and "
          "underpowered; no profitability claim.")
    if summary.get("artifact"):
        print(f"Artifact:       {summary['artifact']}")
    print("=" * 72)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Fama-MacBeth factor attribution worked example (committed real data)."
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Directory to write factor_attribution.json (default: temp dir).",
    )
    args = parser.parse_args(argv)

    output = args.output
    if output is None:
        output = tempfile.mkdtemp(prefix="factor_attribution_")

    summary = run_factor_attribution(output=output)
    print_report(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
