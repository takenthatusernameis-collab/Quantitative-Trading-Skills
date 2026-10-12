#!/usr/bin/env python3
"""
Unit tests for quick_validate.py: skill structure validation.

Run with: python3 skills/skill-creator/tests/test_quick_validate.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import tempfile
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from init_skill import init_skill  # noqa: E402
from quick_validate import validate_skill  # noqa: E402


def _make_skill(tmpdir, name="my-new-skill"):
    """Helper: scaffold a valid skill and return its path."""
    return init_skill(name, tmpdir)


def test_validate_skill_accepts_valid_skill():
    """A freshly scaffolded skill must pass validation."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_path = _make_skill(tmp)
        valid, message = validate_skill(skill_path)
        assert valid is True, f"expected valid, got: {message}"
        assert "valid" in message.lower()


def test_validate_skill_rejects_missing_skill_md():
    """A directory without SKILL.md must fail validation."""
    with tempfile.TemporaryDirectory() as tmp:
        valid, message = validate_skill(Path(tmp))
        assert valid is False
        assert "SKILL.md" in message


def test_validate_skill_rejects_missing_frontmatter():
    """A SKILL.md without YAML frontmatter must fail."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_dir = Path(tmp) / "bad-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# No frontmatter here\n")
        valid, message = validate_skill(skill_dir)
        assert valid is False
        assert "frontmatter" in message.lower()


def test_validate_skill_rejects_missing_name():
    """Frontmatter without a name field must fail."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_dir = Path(tmp) / "bad-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\ndescription: A skill without a name\n---\n# Bad\n"
        )
        valid, message = validate_skill(skill_dir)
        assert valid is False
        assert "name" in message.lower()


def test_validate_skill_rejects_missing_description():
    """Frontmatter without a description field must fail."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_dir = Path(tmp) / "bad-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: bad-skill\n---\n# Bad\n"
        )
        valid, message = validate_skill(skill_dir)
        assert valid is False
        assert "description" in message.lower()


def test_validate_skill_rejects_non_hyphen_case_name():
    """Names with uppercase letters or underscores must fail."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_dir = Path(tmp) / "BadSkill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: BadSkill\ndescription: Bad name\n---\n# Bad\n"
        )
        valid, message = validate_skill(skill_dir)
        assert valid is False
        assert "hyphen-case" in message.lower() or "lowercase" in message.lower()


def test_validate_skill_rejects_leading_hyphen_in_name():
    """Names that start or end with a hyphen must fail."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_dir = Path(tmp) / "-leading"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: -leading\ndescription: Bad name\n---\n# Bad\n"
        )
        valid, message = validate_skill(skill_dir)
        assert valid is False


def test_validate_skill_rejects_angle_brackets_in_description():
    """Descriptions containing angle brackets must fail."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_dir = Path(tmp) / "bad-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: bad-skill\ndescription: A <weird> description\n---\n# Bad\n"
        )
        valid, message = validate_skill(skill_dir)
        assert valid is False
        assert "angle bracket" in message.lower() or "<" in message


def main() -> int:
    tests = [
        ("validate_skill_accepts_valid_skill", test_validate_skill_accepts_valid_skill),
        ("validate_skill_rejects_missing_skill_md", test_validate_skill_rejects_missing_skill_md),
        ("validate_skill_rejects_missing_frontmatter", test_validate_skill_rejects_missing_frontmatter),
        ("validate_skill_rejects_missing_name", test_validate_skill_rejects_missing_name),
        ("validate_skill_rejects_missing_description", test_validate_skill_rejects_missing_description),
        ("validate_skill_rejects_non_hyphen_case_name", test_validate_skill_rejects_non_hyphen_case_name),
        ("validate_skill_rejects_leading_hyphen_in_name", test_validate_skill_rejects_leading_hyphen_in_name),
        ("validate_skill_rejects_angle_brackets_in_description", test_validate_skill_rejects_angle_brackets_in_description),
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
