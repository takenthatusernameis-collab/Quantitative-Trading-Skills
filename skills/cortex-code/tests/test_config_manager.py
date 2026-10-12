#!/usr/bin/env python3
"""
Unit tests for security/config_manager.py: 3-layer config precedence and validation.

Run with: python3 skills/cortex-code/tests/test_config_manager.py
No third-party test framework is required; uses only the standard library.
"""

import sys
import tempfile
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "security"))

from config_manager import ConfigManager, ConfigValidationError  # noqa: E402


def _write_yaml(tmp_dir: Path, name: str, content: str) -> Path:
    p = tmp_dir / name
    p.write_text(content)
    return p


def test_default_config_values():
    """A ConfigManager with no config files must return documented defaults."""
    cm = ConfigManager()
    assert cm.get("security.approval_mode") == "prompt"
    assert cm.get("security.tool_prediction_confidence_threshold") == 0.7
    assert cm.get("security.cache_dir") is not None
    assert "RO" in cm.get("security.allowed_envelopes")


def test_user_config_overrides_defaults():
    """User config values must override defaults for non-security-floor fields."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _write_yaml(Path(tmp), "user.yaml",
                          "security:\n  tool_prediction_confidence_threshold: 0.5")
        cm = ConfigManager(config_path=cfg)
        assert cm.get("security.tool_prediction_confidence_threshold") == 0.5


def test_invalid_approval_mode_raises():
    """An unknown approval_mode must raise ConfigValidationError."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _write_yaml(Path(tmp), "bad.yaml",
                          "security:\n  approval_mode: invalid_mode")
        try:
            ConfigManager(config_path=cfg)
            assert False, "Expected ConfigValidationError"
        except ConfigValidationError:
            pass


def test_invalid_confidence_threshold_raises():
    """A confidence threshold outside [0, 1] must raise ConfigValidationError."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _write_yaml(Path(tmp), "bad.yaml",
                          "security:\n  tool_prediction_confidence_threshold: 1.5")
        try:
            ConfigManager(config_path=cfg)
            assert False, "Expected ConfigValidationError"
        except ConfigValidationError:
            pass


def test_invalid_retention_raises():
    """A negative audit_log_retention must raise ConfigValidationError."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _write_yaml(Path(tmp), "bad.yaml",
                          "security:\n  audit_log_retention: -5")
        try:
            ConfigManager(config_path=cfg)
            assert False, "Expected ConfigValidationError"
        except ConfigValidationError:
            pass


def test_invalid_envelope_raises():
    """An unknown envelope value must raise ConfigValidationError."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _write_yaml(Path(tmp), "bad.yaml",
                          "security:\n  allowed_envelopes: [INVALID]")
        try:
            ConfigManager(config_path=cfg)
            assert False, "Expected ConfigValidationError"
        except ConfigValidationError:
            pass


def test_security_floor_prevents_relaxing_approval_mode():
    """User config cannot relax approval_mode without org policy authorization."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _write_yaml(Path(tmp), "user.yaml",
                          "security:\n  approval_mode: auto")
        cm = ConfigManager(config_path=cfg)
        assert cm.get("security.approval_mode") == "prompt"


def test_org_policy_overrides_user_config():
    """Org policy must take precedence over user config."""
    with tempfile.TemporaryDirectory() as tmp:
        user_cfg = _write_yaml(Path(tmp), "user.yaml",
                               "security:\n  tool_prediction_confidence_threshold: 0.5")
        org_cfg = _write_yaml(Path(tmp), "org.yaml",
                              "security:\n  tool_prediction_confidence_threshold: 0.9")
        cm = ConfigManager(config_path=user_cfg, org_policy_path=org_cfg)
        assert cm.get("security.tool_prediction_confidence_threshold") == 0.9


def test_org_policy_allows_relaxing_approval_mode():
    """Org policy must be able to authorize a non-default approval_mode."""
    with tempfile.TemporaryDirectory() as tmp:
        user_cfg = _write_yaml(Path(tmp), "user.yaml",
                               "security:\n  approval_mode: auto")
        org_cfg = _write_yaml(Path(tmp), "org.yaml",
                              "security:\n  approval_mode: prompt\n  override_user_config: true")
        cm = ConfigManager(config_path=user_cfg, org_policy_path=org_cfg)
        assert cm.get("security.approval_mode") == "prompt"


def test_get_with_default_for_missing_key():
    """get() must return the provided default for missing dot-notation keys."""
    cm = ConfigManager()
    assert cm.get("security.nonexistent", "fallback") == "fallback"
    assert cm.get("totally.missing.path") is None


def test_malformed_user_yaml_does_not_crash():
    """Malformed YAML must produce a warning and fall back to defaults."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _write_yaml(Path(tmp), "bad.yaml", "security: [unclosed")
        cm = ConfigManager(config_path=cfg)
        assert cm.get("security.approval_mode") == "prompt"


def test_dot_notation_access():
    """get() must support dot-notation key access."""
    cm = ConfigManager()
    assert cm.get("security.approval_mode") == "prompt"
    assert cm.get("security.cache_dir") is not None


def main() -> int:
    tests = [
        ("default_config_values", test_default_config_values),
        ("user_config_overrides_defaults", test_user_config_overrides_defaults),
        ("invalid_approval_mode_raises", test_invalid_approval_mode_raises),
        ("invalid_confidence_threshold_raises", test_invalid_confidence_threshold_raises),
        ("invalid_retention_raises", test_invalid_retention_raises),
        ("invalid_envelope_raises", test_invalid_envelope_raises),
        ("security_floor_prevents_relaxing_approval_mode", test_security_floor_prevents_relaxing_approval_mode),
        ("org_policy_overrides_user_config", test_org_policy_overrides_user_config),
        ("org_policy_allows_relaxing_approval_mode", test_org_policy_allows_relaxing_approval_mode),
        ("get_with_default_for_missing_key", test_get_with_default_for_missing_key),
        ("malformed_user_yaml_does_not_crash", test_malformed_user_yaml_does_not_crash),
        ("dot_notation_access", test_dot_notation_access),
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