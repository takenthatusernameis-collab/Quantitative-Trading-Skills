#!/usr/bin/env python3
"""Unit tests for nifi_layout.py (NiFi canvas audit/beautify geometry)."""

import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

import nifi_layout as N  # noqa: E402