#!/usr/bin/env python3
"""
Unit tests for route_request.py: routing logic and credential allowlist checks.

Run with: python3 skills/cortex-code/tests/test_route_request.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from route_request import (  # noqa: E402
    analyze_with_llm_logic,
    check_credential_allowlist,
    SNOWFLAKE_INDICATORS,
    CODING_AGENT_INDICATORS,
)


# --- analyze_with_llm_logic ---


def test_analyze_routes_snowflake_queries_to_cortex():
    """Snowflake queries must route to Cortex with high confidence."""
    route, confidence = analyze_with_llm_logic("query the snowflake warehouse", {})
    assert route == "cortex"
    assert confidence > 0.5


def test_analyze_routes_local_tasks_to_coding_agent():
    """Generic local tasks must route to the host coding agent."""
    route, confidence = analyze_with_llm_logic("read the local file", {})
    assert route == "__CODING_AGENT__"
    assert confidence > 0.5


def test_analyze_empty_prompt_defaults_to_coding_agent():
    """An empty prompt must default to the coding agent with 0.5 confidence."""
    route, confidence = analyze_with_llm_logic("", {})
    assert route == "__CODING_AGENT__"
    assert confidence == 0.5


def test_analyze_sql_without_snowflake_context_routes_to_coding_agent():
    """Generic SQL without Snowflake context must route to the coding agent."""
    route, confidence = analyze_with_llm_logic("select * from users", {})
    assert route == "__CODING_AGENT__"


def test_analyze_snowflake_keyword_scores_higher_than_coding():
    """Explicit 'snowflake' mention must produce a higher snowflake score."""
    route, _ = analyze_with_llm_logic("snowflake and git commit", {})
    # snowflake (3) + coding (git commit = 2) -> snowflake wins
    assert route == "cortex"


def test_analyze_capability_triggers_boost_route():
    """Cortex skill triggers in the prompt must boost the snowflake score."""
    capabilities = {
        "my-skill": {
            "triggers": ["data quality checks", "governance"]
        }
    }
    route, confidence = analyze_with_llm_logic("do data quality checks", capabilities)
    assert route == "cortex"
    assert confidence > 0.5


def test_analyze_confidence_between_zero_and_one():
    """Confidence must always be in [0, 1]."""
    for prompt in ["", "snowflake", "read file", "x" * 500]:
        _, confidence = analyze_with_llm_logic(prompt, {})
        assert 0.0 <= confidence <= 1.0


# --- check_credential_allowlist ---


def test_check_blocks_ssh_credentials():
    """~/.ssh paths must be blocked."""
    result = check_credential_allowlist("check ~/.ssh/id_rsa")
    assert result["blocked"] is True
    assert result["route"] == "blocked"
    assert result["confidence"] == 1.0
    assert "pattern_matched" in result


def test_check_blocks_aws_credentials():
    """~/.aws/credentials paths must be blocked."""
    result = check_credential_allowlist("read ~/.aws/credentials")
    assert result["blocked"] is True


def test_check_blocks_snowflake_credentials():
    """~/.snowflake paths must be blocked."""
    result = check_credential_allowlist("show ~/.snowflake/config.json")
    assert result["blocked"] is True


def test_check_blocks_env_files():
    """.env file paths must be blocked."""
    result = check_credential_allowlist("cat .env")
    assert result["blocked"] is True


def test_check_blocks_credentials_json():
    """credentials.json paths must be blocked."""
    result = check_credential_allowlist("read credentials.json")
    assert result["blocked"] is True


def test_check_allows_non_credential_paths():
    """Non-credential paths must not be blocked."""
    result = check_credential_allowlist("read the README.md file")
    assert result["blocked"] is False
    assert "pattern_matched" not in result


def test_check_returns_dict_with_blocked_key():
    """The result must always contain a 'blocked' boolean key."""
    for prompt in ["hello", "check ~/.ssh/id_rsa", "read file.txt"]:
        result = check_credential_allowlist(prompt)
        assert "blocked" in result
        assert isinstance(result["blocked"], bool)


def main() -> int:
    tests = [
        ("routes_snowflake_queries_to_cortex", test_analyze_routes_snowflake_queries_to_cortex),
        ("routes_local_tasks_to_coding_agent", test_analyze_routes_local_tasks_to_coding_agent),
        ("empty_prompt_defaults_to_coding_agent", test_analyze_empty_prompt_defaults_to_coding_agent),
        ("sql_without_snowflake_context_routes_to_coding_agent", test_analyze_sql_without_snowflake_context_routes_to_coding_agent),
        ("snowflake_keyword_scores_higher", test_analyze_snowflake_keyword_scores_higher_than_coding),
        ("capability_triggers_boost_route", test_analyze_capability_triggers_boost_route),
        ("confidence_between_zero_and_one", test_analyze_confidence_between_zero_and_one),
        ("blocks_ssh_credentials", test_check_blocks_ssh_credentials),
        ("blocks_aws_credentials", test_check_blocks_aws_credentials),
        ("blocks_snowflake_credentials", test_check_blocks_snowflake_credentials),
        ("blocks_env_files", test_check_blocks_env_files),
        ("blocks_credentials_json", test_check_blocks_credentials_json),
        ("allows_non_credential_paths", test_check_allows_non_credential_paths),
        ("returns_dict_with_blocked_key", test_check_returns_dict_with_blocked_key),
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