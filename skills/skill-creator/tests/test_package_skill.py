#!/usr/bin/env python3
"""
Unit tests for package_skill.py: skill packaging into a zip archive.

Run with: python3 skills/skill-creator/tests/test_package_skill.py
No third-party test framework is required; uses only the standard library.
"""

import os
import sys
import tempfile
import traceback
import zipfile
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from init_skill import init_skill  # noqa: E402
from package_skill import package_skill  # noqa: E402


def test_package_skill_creates_zip_for_valid_skill():
    """A valid skill must be packaged into a zip file."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_path = init_skill("my-new-skill", tmp)
        out_dir = Path(tmp) / "dist"
        result = package_skill(skill_path, str(out_dir))
        assert result is not None, "package_skill should return a zip path"
        assert result.exists(), f"zip not found at {result}"
        assert result.suffix == ".zip"
        assert result.name == "my-new-skill.zip"


def test_package_skill_zip_contains_expected_files():
    """The produced zip must contain SKILL.md and resource directories."""
    with tempfile.TemporaryDirectory() as tmp:
        skill_path = init_skill("my-new-skill", tmp)
        out_dir = Path(tmp) / "dist"
        result = package_skill(skill_path, str(out_dir))
        with zipfile.ZipFile(result) as zf:
            names = zf.namelist()
        assert any(n.endswith("SKILL.md") for n in names), f"SKILL.md missing: {names}"
        assert any(n.endswith("scripts/example.py") for n in names), f"example.py missing: {names}"
        assert any(n.endswith("references/api_reference.md") for n in names)
        assert any(n.endswith("assets/example_asset.txt") for n in names)


def test_package_skill_rejects_nonexistent_path():
    """Packaging a path that does not exist must fail."""
    with tempfile.TemporaryDirectory() as tmp:
        result = package_skill(Path(tmp) / "does-not-exist")
        assert result is None, "package_skill should return None for missing path"


def test_package_skill_rejects_file_not_directory():
    """Packaging a file path (not a directory) must fail."""
    with tempfile.TemporaryDirectory() as tmp:
        some_file = Path(tmp) / "file.txt"
        some_file.write_text("hello")
        result = package_skill(some_file)
        assert result is None, "package_skill should return None for a file path"


def test_package_skill_rejects_missing_skill_md():
    """A directory without SKILL.md must fail packaging."""
    with tempfile.TemporaryDirectory() as tmp:
        bare_dir = Path(tmp) / "bare"
        bare_dir.mkdir()
        result = package_skill(bare_dir)
        assert result is None, "package_skill should return None when SKILL.md is missing"


def test_package_skill_rejects_invalid_skill():
    """An invalid skill (bad frontmatter) must fail packaging."""
    with tempfile.TemporaryDirectory() as tmp:
        bad_dir = Path(tmp) / "bad-skill"
        bad_dir.mkdir()
        (bad_dir / "SKILL.md").write_text("no frontmatter at all")
        result = package_skill(bad_dir)
        assert result is None, "package_skill should return None for invalid skill"


def test_package_skill_default_output_dir():
    """When no output dir is given, the zip is written to the current directory."""
    with tempfile.TemporaryDirectory() as tmp:
        cwd = Path.cwd()
        try:
            os_chdir = Path(tmp)
            os.chdir(os_chdir)
            skill_path = init_skill("my-new-skill", str(Path(tmp) / "src"))
            result = package_skill(skill_path)
            assert result is not None
            assert result.parent == os_chdir
        finally:
            os.chdir(cwd)


def main() -> int:
    tests = [
        ("package_skill_creates_zip_for_valid_skill", test_package_skill_creates_zip_for_valid_skill),
        ("package_skill_zip_contains_expected_files", test_package_skill_zip_contains_expected_files),
        ("package_skill_rejects_nonexistent_path", test_package_skill_rejects_nonexistent_path),
        ("package_skill_rejects_file_not_directory", test_package_skill_rejects_file_not_directory),
        ("package_skill_rejects_missing_skill_md", test_package_skill_rejects_missing_skill_md),
        ("package_skill_rejects_invalid_skill", test_package_skill_rejects_invalid_skill),
        ("package_skill_default_output_dir", test_package_skill_default_output_dir),
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
