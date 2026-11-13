#!/usr/bin/env python3
"""
Regression tests for the HMM regime falsifiable hypothesis example
(skills/quantitative-backtesting/examples/hmm_regime_hypothesis_example.py).

Guards the pre-registered methodology as executable and well-formed:
- runs end-to-end on committed real AAPL fixture (offline)
- emits explicit hypothesis, criteria, and verdict
- reports walk-forward OOS metrics, HMM regime performance/concentration,
  and a secondary CPCV diagnostic
- verdict is the conjunction of pre-registered criteria (both outcomes valid)

No claim is made about profitability; this is a methodology/reporting guard.
"""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
sys.path.insert(0, str(SKILLS_DIR / "examples"))

from hmm_regime_hypothesis import run_hmm_regime_hypothesis  # noqa: E402


def test_hmm_regime_hypothesis_example_runs_end_to_end():
    result = run_hmm_regime_hypothesis()

    assert isinstance(result, dict)
    assert result["hypothesis"]
    assert result["verdict"] in ("SUPPORTED", "NOT SUPPORTED")
    assert isinstance(result["all_pass"], bool)
    assert result["all_pass"] == (result["verdict"] == "SUPPORTED")

    criteria = result["criteria"]
    assert isinstance(criteria, list) and len(criteria) == 4
    names = {c["name"] for c in criteria}
    assert names == {
        "oos_sharpe_gt_zero",
        "oos_total_return_gt_zero",
        "bull_regime_sharpe_gt_zero",
        "regime_concentration_not_fragile",
    }
    for c in criteria:
        assert isinstance(c["passed"], bool)
        assert c["description"]
    assert result["all_pass"] == all(c["passed"] for c in criteria)


def test_hmm_regime_hypothesis_reports_required_sections():
    result = run_hmm_regime_hypothesis()

    data = result["data"]
    assert data["symbol"] == "AAPL"
    assert data["rows"] > 0
    assert data["start"] == "2020-01-02"
    assert data["end"] == "2025-12-30"

    wf = result["walk_forward"]
    assert wf["n_periods"] > 0
    assert wf["oos_observations"] > 0
    assert wf["oos_sharpe"] is not None and np.isfinite(wf["oos_sharpe"])
    assert wf["oos_total_return"] is not None and np.isfinite(wf["oos_total_return"])

    hmm = result["hmm_regime_analysis"]
    assert isinstance(hmm, dict)
    assert "regime_performance" in hmm and isinstance(hmm["regime_performance"], dict)
    assert "regime_distribution" in hmm and isinstance(hmm["regime_distribution"], dict)
    assert "regime_concentration" in hmm and isinstance(hmm["regime_concentration"], dict)
    assert hmm["regime_concentration"].get("regime_robustness") in (
        "robust",
        "moderate",
        "fragile",
        "insufficient_data",
    )
    assert "model" in hmm and isinstance(hmm["model"], dict)
    assert hmm["model"].get("converged") in (True, False)

    cpcv = result["cpcv_diagnostic"]
    assert cpcv["n_folds"] >= 0
    assert "note" in cpcv


def test_hmm_regime_hypothesis_example_cli_runs():
    example_path = SKILLS_DIR / "examples" / "hmm_regime_hypothesis.py"
    proc = subprocess.run(
        [sys.executable, str(example_path)],
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert proc.returncode == 0, (
        f"example exited {proc.returncode}\nstdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}"
    )
    out = proc.stdout
    assert "FALSIFIABLE HYPOTHESIS TEST: SMA CROSSOVER + HMM REGIME ANALYSIS" in out
    assert "HMM REGIME ANALYSIS" in out
    assert "FALSIFICATION CRITERIA" in out
    assert "VERDICT:" in out
    assert "NOT SUPPORTED" in out or "SUPPORTED" in out


if __name__ == "__main__":
    for name in sorted(globals()):
        if name.startswith("test_") and callable(globals()[name]):
            try:
                globals()[name]()
                print(f"PASS {name}")
            except Exception:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                print(f"FAIL {name}")
                raise
    print("OK")
