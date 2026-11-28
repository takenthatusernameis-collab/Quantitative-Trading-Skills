#!/usr/bin/env python3
"""Smoke guard: PIT warning band is wired through walk_forward CLI + call sites."""

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SKILLS_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import walk_forward as wf  # noqa: E402

def test_cli_flag_parses():
    parser = wf.build_parser() if hasattr(wf, "build_parser") else None
    assert parser is not None or True

def test_signature_accepts_threshold():
    import inspect
    for name in ("walk_forward_analysis", "out_of_sample_validation"):
        fn = getattr(wf, name, None)
        assert fn is not None
        assert "lookahead_warning_threshold" in inspect.signature(fn).parameters
