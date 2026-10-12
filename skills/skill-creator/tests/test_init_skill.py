#!/usr/bin/env python3
"""
Unit tests for init_skill.py: skill directory scaffolding.

Run with: python3 skills/skill-creator/tests/test_init_skill.py
No third-party test framework is required; uses only the standard library.
"""

import os
import sys
import tempfile
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from init_skill import init_skill, title_case_skill_name  # noqa: E402


def test_init_skill_creates_directory():
    """init_skill.py must create the target skill directory."""
    with tempfile.TemporaryDirectory() as tmp:
        result = init_skill("my-new-skill", tmp)
        assert result is not None, "init_skill should return a path"
        assert result.exists() and result.is_dir()
        assert result.name == "my-new-skill"


def test_init_skill_creates_skill_md():
    """The scaffolded skill must contain a SKILL.md with frontmatter."""
    with tempfile.TemporaryDirectory() as tmp:
        result = init_skill("my-new-skill", tmp)
        skill_md = result / "SKILL.md"
        assert skill_md.exists(), "SKILL.md missing"
        content = skill_md.read_text()
        assert content.startswith("---"), "SKILL.md must start with YAML frontmatter"
        assert "name: my-new-skill" in content
        assert "description:" in content


def test_init_skill_creates_resource_dirs():
    """scripts/, references/, and assets/ must be created with example files."""
    with tempfile.TemporaryDirectory() as tmp:
        result = init_skill("my-new-skill", tmp)
        for sub in ("scripts", "references", "assets"):
            sub_dir = result / sub
            assert sub_dir.exists() and sub_dir.is_dir(), f"{sub}/ missing"
        assert (result / "scripts" / "example.py").exists()
        assert (result / "references" / "api_reference.md").exists()
        assert (result / "assets" / "example_asset.txt").exists()


def test_init_skill_example_script_is_executable():
    """The generated example script must be executable."""
    with tempfile.TemporaryDirectory() as tmp:
        result = init_skill("my-new-skill", tmp)
        example = result / "scripts" / "example.py"
        assert example.exists()
        mode = example.stat().st_mode
        assert mode & 0o111, "example.py should be executable"


def test_init_skill_rejects_existing_directory():
    """Re-running init on an existing skill must fail rather than overwrite."""
    with tempfile.TemporaryDirectory() as tmp:
        first = init_skill("my-new-skill", tmp)
        assert first is not None
        second = init_skill("my-new-skill", tmp)
        assert second is None, "init_skill should refuse to overwrite an existing skill"


def test_title_case_skill_name():
    """title_case_skill_name must convert hyphen-case to Title Case."""
    assert title_case_skill_name("my-cool-skill") == "My Cool Skill"
    assert title_case_skill_name("single") == "Single"
    assert title_case_skill_name("a-b") == "A B"


def main() -> int:
    tests = [
        ("init_skill_creates_directory", test_init_skill_creates_directory),
        ("init_skill_creates_skill_md", test_init_skill_creates_skill_md),
        ("init_skill_creates_resource_dirs", test_init_skill_creates_resource_dirs),
        ("init_skill_example_script_is_executable", test_init_skill_example_script_is_executable),
        ("init_skill_rejects_existing_directory", test_init_skill_rejects_existing_directory),
        ("title_case_skill_name", test_title_case_skill_name),
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
