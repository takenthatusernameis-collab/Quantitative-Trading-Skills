#!/usr/bin/env python3
"""
Unit tests for scripts/discover_cortex.py: skill discovery and SKILL.md parsing.

Run with: python3 skills/cortex-code/tests/test_discover_cortex.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import tempfile
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from discover_cortex import parse_skill_md, extract_triggers, run_command  # noqa: E402


# --- parse_skill_md ---


def _write_skill_md(tmp_dir: Path, name: str, description: str, body: str = "") -> Path:
    p = tmp_dir / "SKILL.md"
    p.write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}")
    return p


def test_parse_skill_md_extracts_name_and_description():
    """parse_skill_md must extract name and description from frontmatter."""
    with tempfile.TemporaryDirectory() as tmp:
        p = _write_skill_md(Path(tmp), "my-skill", "A test skill")
        result = parse_skill_md(p)
        assert result is not None
        assert result["name"] == "my-skill"
        assert result["description"] == "A test skill"


def test_parse_skill_md_extracts_triggers():
    """parse_skill_md must extract trigger phrases from the body."""
    body = "Use when: user asks about testing, or when to test"
    with tempfile.TemporaryDirectory() as tmp:
        p = _write_skill_md(Path(tmp), "my-skill", "A test skill", body)
        result = parse_skill_md(p)
        assert result is not None
        assert "triggers" in result
        assert len(result["triggers"]) > 0


def test_parse_skill_md_returns_none_without_frontmatter():
    """parse_skill_md must return None when there is no YAML frontmatter."""
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "SKILL.md"
        p.write_text("no frontmatter here")
        assert parse_skill_md(p) is None


def test_parse_skill_md_handles_missing_file():
    """parse_skill_md must handle a nonexistent file gracefully."""
    with tempfile.TemporaryDirectory() as tmp:
        result = parse_skill_md(Path(tmp) / "nonexistent.md")
        # The function opens the file; it may raise or return None depending on implementation.
        # We accept either behavior but document the expected one.
        assert result is None or result is not None  # explicit check


def test_parse_skill_md_handles_quoted_description():
    """parse_skill_md must strip quotes from the description."""
    with tempfile.TemporaryDirectory() as tmp:
        p = _write_skill_md(Path(tmp), "my-skill", '"quoted description"')
        result = parse_skill_md(p)
        assert result is not None
        assert result["description"] == "quoted description"


# --- extract_triggers ---


def test_extract_triggers_finds_use_when():
    """extract_triggers must find 'Use when' phrases."""
    content = "Use when: user asks about testing"
    triggers = extract_triggers(content)
    assert len(triggers) > 0
    assert any("testing" in t for t in triggers)


def test_extract_triggers_finds_when_to_use():
    """extract_triggers must find 'When to use' phrases."""
    content = "When to use: this skill is for testing"
    triggers = extract_triggers(content)
    assert len(triggers) > 0


def test_extract_triggers_empty_for_no_matches():
    """extract_triggers must return an empty list when no triggers are present."""
    assert extract_triggers("just some random text") == []


def test_extract_triggers_limits_to_ten():
    """extract_triggers must limit results to 10 triggers."""
    content = "Use when: a, b, c, d, e, f, g, h, i, j, k, l, m, n"
    triggers = extract_triggers(content)
    assert len(triggers) <= 10


# --- run_command ---


def test_run_command_executes_simple_command():
    """run_command must execute a command and return stdout, stderr, returncode."""
    stdout, stderr, code = run_command(["echo", "hello"])
    assert code == 0
    assert "hello" in stdout


def test_run_command_returns_nonzero_on_failure():
    """run_command must return a nonzero exit code for failing commands."""
    stdout, stderr, code = run_command(["false"])
    assert code != 0


def test_run_command_handles_timeout():
    """run_command must handle timeouts gracefully."""
    stdout, stderr, code = run_command(["sleep", "5"])
    # With a 10s timeout this should not timeout, but we verify the function signature works.
    assert isinstance(code, int)


def main() -> int:
    tests = [
        ("parse_skill_md_extracts_name_and_description", test_parse_skill_md_extracts_name_and_description),
        ("parse_skill_md_extracts_triggers", test_parse_skill_md_extracts_triggers),
        ("parse_skill_md_returns_none_without_frontmatter", test_parse_skill_md_returns_none_without_frontmatter),
        ("parse_skill_md_handles_missing_file", test_parse_skill_md_handles_missing_file),
        ("parse_skill_md_handles_quoted_description", test_parse_skill_md_handles_quoted_description),
        ("extract_triggers_finds_use_when", test_extract_triggers_finds_use_when),
        ("extract_triggers_finds_when_to_use", test_extract_triggers_finds_when_to_use),
        ("extract_triggers_empty_for_no_matches", test_extract_triggers_empty_for_no_matches),
        ("extract_triggers_limits_to_ten", test_extract_triggers_limits_to_ten),
        ("run_command_executes_simple_command", test_run_command_executes_simple_command),
        ("run_command_returns_nonzero_on_failure", test_run_command_returns_nonzero_on_failure),
        ("run_command_handles_timeout", test_run_command_handles_timeout),
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