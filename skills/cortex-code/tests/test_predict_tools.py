#!/usr/bin/env python3
"""
Unit tests for predict_tools.py: tool prediction with confidence scoring.

Run with: python3 skills/cortex-code/tests/test_predict_tools.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from predict_tools import predict_tools, BASE_SNOWFLAKE_TOOLS  # noqa: E402


def test_predict_tools_returns_base_tools_for_empty_prompt():
    """An empty prompt must still include the base Snowflake tools."""
    result = predict_tools("")
    assert "tools" in result
    assert "confidence" in result
    assert "reasoning" in result
    for tool in BASE_SNOWFLAKE_TOOLS:
        assert tool in result["tools"], f"base tool {tool} missing"
    assert result["confidence"] == 0.5


def test_predict_tools_detects_sql_keywords():
    """SQL keywords must trigger snowflake_sql_execute."""
    result = predict_tools("select * from snowflake table")
    assert "snowflake_sql_execute" in result["tools"]
    assert result["confidence"] > 0.5
    assert "snowflake_sql_execute" in result["reasoning"]


def test_predict_tools_detects_read_write():
    """Read/write keywords must trigger the corresponding tools."""
    result = predict_tools("read the file and write output")
    assert "read" in result["tools"]
    assert "write" in result["tools"]


def test_predict_tools_detects_glob_grep():
    """Find/search keywords must trigger glob and grep."""
    result = predict_tools("find files matching a pattern")
    assert "glob" in result["tools"]
    assert "grep" in result["tools"]


def test_predict_tools_detects_bash():
    """Run/execute keywords must trigger bash."""
    result = predict_tools("run the install script")
    assert "bash" in result["tools"]


def test_predict_tools_confidence_is_bounded():
    """Confidence must always be within [0, 1]."""
    for prompt in ["", "a", "select * from snowflake table", "x" * 1000]:
        result = predict_tools(prompt)
        assert 0.0 <= result["confidence"] <= 1.0, f"out of range: {result['confidence']}"


def test_predict_tools_short_prompt_lowered_confidence():
    """Very short prompts (<5 words) must have confidence multiplied by 0.8."""
    empty_result = predict_tools("")
    short_result = predict_tools("select")
    # Both have only base tools; short prompt should be 0.5*0.8 = 0.4
    assert short_result["confidence"] < empty_result["confidence"]


def test_predict_tools_envelope_capability_boost():
    """Matching capability descriptions in the envelope must boost confidence."""
    envelope = {
        "capabilities": {
            "data-quality-skill": {
                "description": "Data quality checks for Snowflake tables"
            }
        }
    }
    result = predict_tools("check data quality", envelope)
    # Skill name contains "quality" -> glob, grep, write added; confidence boosted
    assert "glob" in result["tools"]
    assert "grep" in result["tools"]
    assert "write" in result["tools"]
    assert result["confidence"] >= 0.5


def test_predict_tools_envelope_ml_skill_adds_bash():
    """ML/forecast skill names in the envelope must add bash."""
    envelope = {
        "capabilities": {
            "ml-forecast": {
                "description": "Machine learning forecasting models"
            }
        }
    }
    result = predict_tools("build a forecast", envelope)
    assert "bash" in result["tools"]


def test_predict_tools_returns_sorted_tools():
    """The tools list must be sorted alphabetically."""
    result = predict_tools("read write search find run select")
    assert result["tools"] == sorted(result["tools"])


def test_predict_tools_confidence_rounded():
    """Confidence must be rounded to 2 decimal places."""
    result = predict_tools("select * from snowflake table")
    assert result["confidence"] == round(result["confidence"], 2)


def main() -> int:
    tests = [
        ("returns_base_tools_for_empty_prompt", test_predict_tools_returns_base_tools_for_empty_prompt),
        ("detects_sql_keywords", test_predict_tools_detects_sql_keywords),
        ("detects_read_write", test_predict_tools_detects_read_write),
        ("detects_glob_grep", test_predict_tools_detects_glob_grep),
        ("detects_bash", test_predict_tools_detects_bash),
        ("confidence_is_bounded", test_predict_tools_confidence_is_bounded),
        ("short_prompt_lowered_confidence", test_predict_tools_short_prompt_lowered_confidence),
        ("envelope_capability_boost", test_predict_tools_envelope_capability_boost),
        ("envelope_ml_skill_adds_bash", test_predict_tools_envelope_ml_skill_adds_bash),
        ("returns_sorted_tools", test_predict_tools_returns_sorted_tools),
        ("confidence_rounded", test_predict_tools_confidence_rounded),
    ]

    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception:
            failures += 1
            print(f"FAIL  {name}")
            traceback.print_exc()

    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())