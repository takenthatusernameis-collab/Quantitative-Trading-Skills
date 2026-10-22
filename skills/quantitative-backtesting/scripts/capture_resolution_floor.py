#!/usr/bin/env python3
"""Capture a measurement of ``measure_resolution_vs_sample_size.py`` with provenance.

WHAT THIS IS
    Every committed capture in ``results/resolution_floor/`` carries a
    ``provenance`` block -- the command that produced the measurement, the
    environment it ran in, the fixture construction, the bounds it compared
    against, the script commit and the time it was measured -- so a reader can
    re-run it. The measurement tool's own ``--json`` output does not include
    that block: it is the *measurement*, and the provenance is the record of
    *how it was measured*. This script runs the tool, wraps its JSON output in
    the provenance block, and writes the result to a file.

    It is the single entry point for committing a capture, so the provenance
    cannot drift from the command that produced the rows: the command is
    passed in and recorded verbatim, and the rows are whatever that command
    printed.

Usage
    python3 skills/quantitative-backtesting/scripts/capture_resolution_floor.py \
        --out results/resolution_floor/cost_sweep_2500_5000_10000.json \
        --sizes 2500,5000,10000 --seeds 7,1,2024 \
        --cost-regimes shipped,2:5:1,5:2:0.5 --series both --json

The capture script's own flags (--out, --description, --note) are parsed
first; everything after them is forwarded to the measurement tool verbatim,
so the command recorded in the provenance is exactly the one that ran.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

SKILLS_DIR = Path(__file__).resolve().parent.parent
MEASUREMENT_SCRIPT = SKILLS_DIR / "scripts" / "measure_resolution_vs_sample_size.py"

# The fixture construction, read from the module that builds it so the capture
# cannot describe a fixture it did not measure.
sys.path.insert(0, str(SKILLS_DIR / "scripts"))
import generate_positive_control_data as control  # noqa: E402


def _git_commit() -> str:
    """The full SHA of the current HEAD, or 'unknown' outside a checkout."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(SKILLS_DIR.parent.parent),
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _environment() -> Dict[str, str]:
    """The versions the measurement ran under, as strings."""
    import numpy as np
    import pandas as pd

    return {
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "python": sys.version.split()[0],
    }


def _fixture_construction() -> Dict[str, Any]:
    """The synthetic control fixture's construction parameters."""
    return control.describe_construction()


def _plausibility_bounds() -> Dict[str, float]:
    """The bounds the measurement compares against, read from the framework."""
    sys.path.insert(0, str(SKILLS_DIR / "scripts"))
    from walk_forward import (  # noqa: E402
        PLAUSIBLE_MAX_ANNUALIZED_ALPHA,
        PLAUSIBLE_MAX_ANNUALIZED_SHARPE,
    )
    return {
        "plausible_max_annualized_sharpe": PLAUSIBLE_MAX_ANNUALIZED_SHARPE,
        "plausible_max_annualized_alpha": PLAUSIBLE_MAX_ANNUALIZED_ALPHA,
    }


def _arg(command: List[str], flag: str) -> str:
    """The value of one flag in a command line, or '' when absent."""
    if flag not in command:
        return ""
    index = command.index(flag)
    if index + 1 >= len(command):
        return ""
    return command[index + 1]


def _measured_block(command: List[str]) -> Dict[str, Any]:
    """The part of the command that describes what was measured.

    The measurement tool prints its own banner to stderr with the source and
    the series; the provenance block records the same facts from the command
    line so the two cannot disagree. The shape mirrors the provenance blocks
    the committed captures carry, so a reader who knows one capture knows this
    one.
    """
    block: Dict[str, Any] = {}
    sizes = _arg(command, "--sizes")
    seeds = _arg(command, "--seeds")
    series = _arg(command, "--series")
    data = _arg(command, "--data")
    cost_regimes = _arg(command, "--cost-regimes")
    test_fracs = _arg(command, "--test-fracs")
    wf_windows = _arg(command, "--wf-windows")
    cpcv_splits = _arg(command, "--cpcv-splits")
    paths = _arg(command, "--paths")

    if sizes:
        block["sizes"] = [int(s) for s in sizes.split(",") if s.strip()]
    if seeds:
        block["seeds"] = [int(s) for s in seeds.split(",") if s.strip()]
    if series:
        block["series"] = [series] if series == "real_history_prefix" else (
            ["no_effect", "effect"] if series == "both" else [series]
        )
    if data:
        block["source_file"] = data
    if cost_regimes:
        block["cost_regimes"] = [
            r.split(":")[0] for r in cost_regimes.split(",") if r.strip()
        ]
    if test_fracs:
        block["test_fracs"] = [
            float(t) for t in test_fracs.split(",") if t.strip()
        ]
    if wf_windows:
        windows = [
            [int(p) for p in w.split(":")]
            for w in wf_windows.split(",") if w.strip()
        ]
        block["windows"] = windows
        block["step"] = "follows the test window (non-overlapping out-of-sample windows)"
        block["path"] = "walk_forward"
        block["configurations_per_series"] = len(windows)
        block["draws_per_configuration"] = (
            len(block.get("seeds", [])) * len(block.get("series", []))
        )
    if cpcv_splits:
        splits = [
            [float(p) for p in w.split(":")]
            for w in cpcv_splits.split(",") if w.strip()
        ]
        block["splits"] = splits
        block["test_size"] = (
            "the fraction of each group used as that group's test set "
            "(effective oos fraction = test_size / n_splits)"
        )
        block["path"] = "cpcv"
        block["configurations_per_series"] = len(splits)
        block["draws_per_configuration"] = (
            len(block.get("seeds", [])) * len(block.get("series", []))
        )
    if paths:
        block["paths"] = [p for p in paths.split(",") if p.strip()]
    if test_fracs and not wf_windows and not cpcv_splits:
        block["path"] = "out_of_sample"
        block["configurations_per_series"] = len(
            [t for t in test_fracs.split(",") if t.strip()]
        )
        block["draws_per_configuration"] = (
            len(block.get("seeds", [])) * len(block.get("series", []))
        )
    if cost_regimes:
        block["cost_regimes"] = [
            r.split(":")[0] for r in cost_regimes.split(",") if r.strip()
        ]
    if not block.get("path") and not test_fracs:
        # A plain ladder (optionally at several cost regimes): the
        # out-of-sample path is always measured and the paths flag says which
        # others are reported.
        block["path"] = "out_of_sample"
        if not paths:
            block["paths"] = ["out_of_sample", "walk_forward", "cpcv"]
        block["draws_per_rung"] = (
            len(block.get("seeds", [])) * len(block.get("series", []))
        )
        block["split"] = {"train_frac": 0.6, "val_frac": 0.2, "test_frac": 0.2}
    return block


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run measure_resolution_vs_sample_size.py and write its --json "
            "output wrapped in a provenance block."
        )
    )
    parser.add_argument("--out", required=True, help="Output JSON path.")
    parser.add_argument(
        "--description",
        default=None,
        help="Human description of the measurement. Defaults to a generic one.",
    )
    parser.add_argument(
        "--note",
        default=None,
        help="Optional note recorded alongside the capture.",
    )
    args, tool_args = parser.parse_known_args(argv)
    if not tool_args or tool_args[0] != "--sizes":
        parser.error(
            "the first forwarded argument must be --sizes (the measurement "
            "tool's first flag), so the command is recorded verbatim"
        )
    if "--json" not in tool_args:
        parser.error("the measurement tool must be run with --json")

    command = ["python3", str(MEASUREMENT_SCRIPT)] + tool_args
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=3600,
        cwd=str(SKILLS_DIR.parent.parent),
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        return result.returncode

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"the tool's stdout was not JSON: {exc}\n")
        sys.stderr.write(result.stdout)
        return 1

    description = args.description or (
        "A measurement of the decision machinery on the synthetic control "
        "fixture, captured with its provenance so it can be re-run."
    )

    capture = {
        "provenance": {
            "command": " ".join(command),
            "description": description,
            "environment": _environment(),
            "fixture_construction": _fixture_construction(),
            "measured": _measured_block(tool_args),
            "measured_at_utc": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "plausibility_bounds": _plausibility_bounds(),
            "script_commit": _git_commit(),
        },
        **payload,
    }
    if args.note:
        capture["provenance"]["note"] = args.note

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as handle:
        json.dump(capture, handle, indent=2, default=str)
        handle.write("\n")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())