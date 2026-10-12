#!/usr/bin/env python3
"""Unit tests for render_assets.py."""

import sys
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from render_assets import (  # noqa: E402
    parse_spec_list,
    safe_name,
    split_specs,
    csv_list,
    validate_secret_fields,
)


def test_csv_list_strips_and_drops_empty():
    result = csv_list("a, b , ,c")
    assert result == ["a", "b", "c"]


def test_csv_list_empty_string():
    assert csv_list("") == []


def test_split_specs_passes_through_csv_list():
    assert split_specs("a,b") == ["a", "b"]


def test_safe_name_replaces_whitespace_and_symbols():
    assert safe_name("My Source Type!") == "My_Source_Type_"


def test_safe_name_preserves_allowed_chars():
    assert safe_name("aws:cloudtrail") == "aws:cloudtrail"


def test_safe_name_empty_falls_back():
    assert safe_name("   ") == "unnamed"


def test_parse_spec_list_basic_name_and_fields():
    specs = parse_spec_list("redact_auth=template=redact;sourcetype=json_app;destination=splunk_indexer")
    assert len(specs) == 1
    spec = specs[0]
    assert spec["name"] == "redact_auth"
    assert spec["template"] == "redact"
    assert spec["sourcetype"] == "json_app"
    assert spec["destination"] == "splunk_indexer"


def test_parse_spec_list_first_chunk_without_equals_is_name():
    specs = parse_spec_list("plain_name;foo=bar")
    assert specs[0]["name"] == "plain_name"
    assert specs[0]["foo"] == "bar"


def test_parse_spec_list_implicit_true_for_bare_field():
    specs = parse_spec_list("pipe;default")
    assert specs[0]["default"] == "true"


def test_parse_spec_list_multiple_specs_split_by_comma():
    specs = parse_spec_list("a=1;b=2, c=3")
    assert len(specs) == 2
    assert specs[0]["name"] == "a"
    assert specs[1]["name"] == "c"


def test_parse_spec_list_drops_empty_items():
    assert parse_spec_list("") == []


def test_validate_secret_fields_allows_plain_keys():
    validate_secret_fields({"name": "ok", "template": "filter"})


def test_validate_secret_fields_rejects_raw_password_key():
    try:
        validate_secret_fields({"password": "hunter2"})
        assert False, "expected ValueError"
    except ValueError as e:
        assert "password" in str(e)


def test_validate_secret_fields_allows_password_file_suffix():
    validate_secret_fields({"password_file": "/etc/secret"})


def test_validate_secret_fields_rejects_secret_value():
    try:
        validate_secret_fields({"name": "x", "token": "raw-token-value"})
        assert False, "expected ValueError"
    except ValueError as e:
        assert "secret" in str(e).lower()


def test_validate_secret_fields_allows_bool_like_values():
    # bool-like values are accepted even when the value text matches the secret regex
    validate_secret_fields({"name": "x", "note": "true"})
    validate_secret_fields({"name": "x", "note": "FALSE"})


def test_validate_secret_fields_rejects_raw_secret_value():
    try:
        validate_secret_fields({"name": "x", "note": "raw-token-value"})
        assert False, "expected ValueError"
    except ValueError as e:
        assert "secret" in str(e).lower()


def test_validate_secret_fields_allows_path_like_value():
    # values containing "/" are treated as file paths and allowed
    validate_secret_fields({"name": "x", "note": "aws/secret/token"})


def main() -> int:
    tests = [
        ("csv_list_strips_and_drops_empty", test_csv_list_strips_and_drops_empty),
        ("csv_list_empty_string", test_csv_list_empty_string),
        ("split_specs_passes_through_csv_list", test_split_specs_passes_through_csv_list),
        ("safe_name_replaces_whitespace_and_symbols", test_safe_name_replaces_whitespace_and_symbols),
        ("safe_name_preserves_allowed_chars", test_safe_name_preserves_allowed_chars),
        ("safe_name_empty_falls_back", test_safe_name_empty_falls_back),
        ("parse_spec_list_basic_name_and_fields", test_parse_spec_list_basic_name_and_fields),
        ("parse_spec_list_first_chunk_without_equals_is_name", test_parse_spec_list_first_chunk_without_equals_is_name),
        ("parse_spec_list_implicit_true_for_bare_field", test_parse_spec_list_implicit_true_for_bare_field),
        ("parse_spec_list_multiple_specs_split_by_comma", test_parse_spec_list_multiple_specs_split_by_comma),
        ("parse_spec_list_drops_empty_items", test_parse_spec_list_drops_empty_items),
        ("validate_secret_fields_allows_plain_keys", test_validate_secret_fields_allows_plain_keys),
        ("validate_secret_fields_rejects_raw_password_key", test_validate_secret_fields_rejects_raw_password_key),
        ("validate_secret_fields_allows_password_file_suffix", test_validate_secret_fields_allows_password_file_suffix),
        ("validate_secret_fields_rejects_secret_value", test_validate_secret_fields_rejects_secret_value),
        ("validate_secret_fields_allows_bool_like_values", test_validate_secret_fields_allows_bool_like_values),
        ("validate_secret_fields_rejects_raw_secret_value", test_validate_secret_fields_rejects_raw_secret_value),
        ("validate_secret_fields_allows_path_like_value", test_validate_secret_fields_allows_path_like_value),
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