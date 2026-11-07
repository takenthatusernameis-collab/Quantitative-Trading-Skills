#!/usr/bin/env python3
"""CLI-level regression guard: --point-in-time-strict must abort on a
look-ahead signal via walk_forward.py subcommands.

Positive control: out-of-sample with a test-only look-ahead strategy
(signal[t] = sign of next-period return) + --point-in-time-strict exits
non-zero and surfaces the PIT violation. Guards against a strict flag that
does not actually abort at the CLI level.

Negative controls:
  - clean sma_crossover + --point-in-time-strict passes (exit 0, no false
    abort on legitimate close[t]-based signals).
  - look-ahead strategy WITHOUT --point-in-time-strict completes (warn only).

The look-ahead strategy is registered only inside the test harness wrapper
(_cli_pit_lookahead.py); it is not added to the production STRATEGY_REGISTRY.

This complements test_point_in_time_strict_abort_on_violation.py, which
covers the programmatic walk_forward_analysis / out_of_sample_validation
gates. Here the enforcement is exercised through the real CLI entry point.

Offline, committed fixtures only (AAPL.csv); no live network. Audit of the
PIT control, not a profitability claim.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILLS_DIR / "scripts"
DATA = SKILLS_DIR / "assets" / "example_data" / "real_market_data" / "AAPL.csv"
WRAPPER = SKILLS_DIR / "tests" / "_cli_pit_lookahead.py"

PARAM_GRID = '{"fast_period": [10], "slow_period": [30]}'
BASE_ARGS = [
    "--data", str(DATA),
    "--param-grid", PARAM_GRID,
    "--commission", "0.0002",
    "--slippage", "0.0001",
    "--validate-point-in-time",
]


def _run_wf(subcommand, strategy, strict=True, extra=None):
    # Write output to a temp dir so the tracked scripts/results/ fixtures are
    # not touched by test runs.
    output_dir = tempfile.mkdtemp(prefix="pit_cli_wf_")
    cmd = [
        sys.executable,
        str(WRAPPER),
        subcommand,
        "--strategy", strategy,
        "--output", output_dir,
    ] + BASE_ARGS
    if strict:
        cmd.append("--point-in-time-strict")
    if extra:
        cmd += extra
    return subprocess.run(cmd, cwd=str(SCRIPTS_DIR), capture_output=True, text=True)


def _assert_strict_abort(result, label):
    assert result.returncode != 0, (
        f"{label}: expected non-zero exit under --point-in-time-strict, "
        f"got {result.returncode}\nstdout:\n{result.stdout[-1500:]}\nstderr:\n{result.stderr[-1500:]}"
    )
    text = (result.stdout + result.stderr).lower()
    assert "strict mode" in text or "correlates with next-period returns" in text, (
        f"{label}: non-zero exit but no PIT strict abort signalled\n"
        f"stdout:\n{result.stdout[-1500:]}\nstderr:\n{result.stderr[-1500:]}"
    )


def test_out_of_sample_strict_aborts_on_lookahead():
    """Look-ahead strategy + --point-in-time-strict must abort via the CLI."""
    result = _run_wf("out-of-sample", "pit_lookahead", strict=True)
    _assert_strict_abort(result, "out-of-sample look-ahead strict")


def test_out_of_sample_strict_passes_on_clean_data():
    """Clean sma_crossover + --point-in-time-strict must pass (no false abort)."""
    result = _run_wf("out-of-sample", "sma_crossover", strict=True)
    assert result.returncode == 0, (
        f"out-of-sample clean strict aborted (exit {result.returncode})\n"
        f"stdout:\n{result.stdout[-1500:]}\nstderr:\n{result.stderr[-1500:]}"
    )
    assert "point-in-time validation passed" in result.stdout.lower(), (
        f"PIT result not surfaced on clean data:\n{result.stdout[-1500:]}"
    )


def test_out_of_sample_lookahead_non_strict_completes():
    """Look-ahead strategy without --point-in-time-strict completes (warn only)."""
    result = _run_wf("out-of-sample", "pit_lookahead", strict=False)
    assert result.returncode == 0, (
        f"out-of-sample look-ahead warn-only failed (exit {result.returncode})\n"
        f"stderr:\n{result.stderr[-1500:]}"
    )


def test_walk_forward_strict_passes_on_clean_data():
    """walk-forward subcommand: clean sma_crossover + strict passes (no false abort)."""
    result = _run_wf("walk-forward", "sma_crossover", strict=True)
    assert result.returncode == 0, (
        f"walk-forward clean strict aborted (exit {result.returncode})\n"
        f"stdout:\n{result.stdout[-1500:]}\nstderr:\n{result.stderr[-1500:]}"
    )


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS  {name}")
    print("OK")
