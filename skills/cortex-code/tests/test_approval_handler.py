#!/usr/bin/env python3
"""
Unit tests for security/approval_handler.py: tool prediction and approval flow.

Run with: python3 skills/cortex-code/tests/test_approval_handler.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from security.approval_handler import ApprovalHandler, ApprovalResult  # noqa: E402


def test_parse_approve():
    """'approve' must return an approved result with empty allowed_tools."""
    result = ApprovalHandler().parse_user_response("approve")
    assert isinstance(result, ApprovalResult)
    assert result.approved is True
    assert result.allowed_tools == []
    assert result.user_response == "approve"


def test_parse_approve_all():
    """'approve_all' must return an approved result with ['*'] as allowed_tools."""
    result = ApprovalHandler().parse_user_response("approve_all")
    assert result.approved is True
    assert result.allowed_tools == ["*"]
    assert result.user_response == "approve_all"


def test_parse_deny():
    """'deny' must return a denied result with empty allowed_tools."""
    result = ApprovalHandler().parse_user_response("deny")
    assert result.approved is False
    assert result.allowed_tools == []
    assert result.user_response == "deny"


def test_parse_unknown_treated_as_deny():
    """Unknown responses must be treated as deny for safety."""
    result = ApprovalHandler().parse_user_response("maybe later")
    assert result.approved is False
    assert result.allowed_tools == []
    assert result.user_response == "maybe later"


def test_parse_response_is_case_insensitive():
    """Response parsing must be case-insensitive and trim whitespace."""
    ah = ApprovalHandler()
    assert ah.parse_user_response("  APPROVE  ").approved is True
    assert ah.parse_user_response("Deny").approved is False


def test_format_approval_prompt_contains_request():
    """The formatted prompt must include the user request."""
    ah = ApprovalHandler()
    prompt = ah.format_approval_prompt(
        ["Read"], 0.8, {"user_prompt": "test prompt"}, "matched read"
    )
    assert "test prompt" in prompt
    assert "Read" in prompt
    assert "80%" in prompt


def test_format_approval_prompt_no_warning_above_threshold():
    """No warning must appear when confidence is at or above threshold."""
    ah = ApprovalHandler(confidence_threshold=0.7)
    prompt = ah.format_approval_prompt(
        ["Read"], 0.8, {"user_prompt": "test"}, "matched read"
    )
    assert "WARNING" not in prompt


def test_format_approval_prompt_warning_below_threshold():
    """A warning must appear when confidence is below threshold."""
    ah = ApprovalHandler(confidence_threshold=0.7)
    prompt = ah.format_approval_prompt(
        ["Read"], 0.5, {"user_prompt": "test"}, "matched read"
    )
    assert "WARNING" in prompt
    assert "50%" in prompt


def test_format_approval_prompt_includes_options():
    """The formatted prompt must list approve/approve_all/deny options."""
    ah = ApprovalHandler()
    prompt = ah.format_approval_prompt(
        ["Read"], 0.5, {"user_prompt": "test"}, "matched read"
    )
    assert "approve" in prompt
    assert "approve_all" in prompt
    assert "deny" in prompt


def test_predict_tools_returns_dict_with_required_keys():
    """predict_tools must return tools, confidence, and reasoning."""
    ah = ApprovalHandler()
    result = ah.predict_tools("select from snowflake", None)
    assert "tools" in result
    assert "confidence" in result
    assert "reasoning" in result


def test_predict_tools_uses_envelope():
    """predict_tools must accept an envelope dict."""
    ah = ApprovalHandler()
    envelope = {"capabilities": {}}
    result = ah.predict_tools("hello", envelope)
    assert "tools" in result


def test_confidence_threshold_stored():
    """The confidence_threshold passed to the constructor must be stored."""
    ah = ApprovalHandler(confidence_threshold=0.9)
    assert ah.confidence_threshold == 0.9


def test_default_confidence_threshold_is_0_7():
    """The default confidence_threshold must be 0.7."""
    assert ApprovalHandler().confidence_threshold == 0.7


def main() -> int:
    tests = [
        ("parse_approve", test_parse_approve),
        ("parse_approve_all", test_parse_approve_all),
        ("parse_deny", test_parse_deny),
        ("parse_unknown_treated_as_deny", test_parse_unknown_treated_as_deny),
        ("parse_response_is_case_insensitive", test_parse_response_is_case_insensitive),
        ("format_approval_prompt_contains_request", test_format_approval_prompt_contains_request),
        ("format_approval_prompt_no_warning_above_threshold", test_format_approval_prompt_no_warning_above_threshold),
        ("format_approval_prompt_warning_below_threshold", test_format_approval_prompt_warning_below_threshold),
        ("format_approval_prompt_includes_options", test_format_approval_prompt_includes_options),
        ("predict_tools_returns_dict_with_required_keys", test_predict_tools_returns_dict_with_required_keys),
        ("predict_tools_uses_envelope", test_predict_tools_uses_envelope),
        ("confidence_threshold_stored", test_confidence_threshold_stored),
        ("default_confidence_threshold_is_0_7", test_default_confidence_threshold_is_0_7),
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