#!/usr/bin/env python3
"""Parameter sensitivity on the committed real-market three-asset panel
(AAPL / MSFT / GOOGL).

Sweeps dual momentum (absolute + relative momentum, long-only) parameters
across a narrow pre-registered grid on the three-asset panel and reports an
explicit falsification verdict at each setting. Reports how the per-criterion
pass/fail and overall verdict change as parameters are perturbed around the
advertised setting (lookback=252, top_quantile=0.5, risk_free_rate=0.0),
holding commission/slippage fixed at the advertised level. This is a
robustness/sensitivity analysis on committed fixtures, not evidence about
any market. No claim is made about which setting is "best"; verdict flips
across the grid are the signal that the result is not robust to small
parameter changes.

Offline, committed fixtures only (assets/example_data/real_market_data/
{AAPL,MSFT,GOOGL}.csv). No live network.
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from dual_momentum_hypothesis import (  # noqa: E402
    COMMISSION,
    SLIPPAGE,
    PARAM_SENSITIVITY_GRID,
    run_param_sensitivity_sweep,
)

SRC = SKILLS_DIR / "assets" / "example_data" / "real_market_data"


def _build_triple_csv(dest: Path) -> Path:
    frames = []
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        frame = pd.read_csv(SRC / name)
        frame["symbol"] = Path(name).stem
        frames.append(frame)
    combined = pd.concat(frames, ignore_index=True)
    out = dest / "aapl_msft_googl_triple.csv"
    combined.to_csv(out, index=False)
    return out


def test_param_sensitivity_runs_on_triple_real_window_dual_momentum():
    for name in ("AAPL.csv", "MSFT.csv", "GOOGL.csv"):
        assert (SRC / name).exists()

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        data_path = _build_triple_csv(d)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = run_param_sensitivity_sweep(data_path)

    assert isinstance(rows, list) and len(rows) == len(PARAM_SENSITIVITY_GRID)
    for r, (lookback, top_q, risk_free_rate) in zip(rows, PARAM_SENSITIVITY_GRID):
        assert r["lookback"] == int(lookback)
        assert r["top_quantile"] == float(top_q)
        assert r["risk_free_rate"] == float(risk_free_rate)
        assert r["commission"] == COMMISSION
        assert r["slippage"] == SLIPPAGE
        assert r["commission_bps"] == COMMISSION * 10_000
        assert r["slippage_bps"] == SLIPPAGE * 10_000
        assert r["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
        assert r["all_pass"] == all(c["passed"] for c in r["criteria"])
        assert r["verdict"] == ("SUPPORTED" if r["all_pass"] else "NOT SUPPORTED")
        assert len(r["criteria"]) == 2
        assert {c["name"] for c in r["criteria"]} == {
            "oos_sharpe_gt_zero",
            "oos_total_return_positive",
        }

    # Regression guard: pin the observed out-of-sample metrics per parameter
    # setting so the robustness evidence (SUPPORTED across the whole
    # pre-registered grid) is reproducible and any silent change to the
    # backtest numbers is caught. Compared with a relative tolerance (never
    # exact equality, since the last decimals depend on the numpy/pandas
    # build). Note: top_quantile 0.4 and 0.5 produce identical metrics on a
    # 3-asset panel because both round up to 2 assets in the long book
    # (ceil(3 * 0.4) == ceil(3 * 0.5) == 2); that is a structural property
    # of the quantile selection, not a regression.
    EXPECTED_METRICS = {
        (252, 0.5, 0.0): (1.1676593094877479, 0.40834454698372635),
        (189, 0.5, 0.0): (0.9194386277737749, 0.42993181642557343),
        (315, 0.5, 0.0): (1.242023295571937, 0.38316601159509656),
        (252, 0.4, 0.0): (1.1676593094877479, 0.40834454698372635),
        (252, 0.6, 0.0): (1.2250203713496854, 0.43508755342027494),
        (252, 0.5, 0.02): (1.3044258190300417, 0.46055895420767823),
    }
    REL_TOL = 1e-3
    for r in rows:
        key = (r["lookback"], r["top_quantile"], r["risk_free_rate"])
        assert key in EXPECTED_METRICS, f"unexpected parameter setting {key}"
        exp_sharpe, exp_ret = EXPECTED_METRICS[key]
        assert r["sharpe_ratio"] is not None, f"missing sharpe at {key}"
        assert r["total_return"] is not None, f"missing total_return at {key}"
        assert abs(r["sharpe_ratio"] - exp_sharpe) <= REL_TOL * max(
            abs(exp_sharpe), 1e-9
        ), f"sharpe regression at {key}: got {r['sharpe_ratio']}, expected {exp_sharpe}"
        assert abs(r["total_return"] - exp_ret) <= REL_TOL * max(
            abs(exp_ret), 1e-9
        ), f"total_return regression at {key}: got {r['total_return']}, expected {exp_ret}"

    out = buffer.getvalue()
    assert "PARAMETER SENSITIVITY SWEEP" in out
    assert "VERDICT" in out


if __name__ == "__main__":
    test_param_sensitivity_runs_on_triple_real_window_dual_momentum()
    print("OK")