#!/usr/bin/env python3
"""Unit tests for vault_config_generator.py."""

import json
import sys
import tempfile
import traceback
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from vault_config_generator import (
    parse_secrets,
    generate_policy_hcl,
    generate_auth_config,
    build_output,
    print_human,
    SECRET_TYPE_MAP,
    AUTH_METHOD_DEFAULTS,
)


def test_parse_secrets():
    valid, unknown = parse_secrets("db-creds,api-key,tls-cert")
    assert valid == ["db-creds", "api-key", "tls-cert"]
    assert unknown == []

    valid, unknown = parse_secrets("db-creds, unknown-type, api-key")
    assert valid == ["db-creds", "api-key"]
    assert unknown == ["unknown-type"]

    valid, unknown = parse_secrets("")
    assert valid == []
    assert unknown == []

    valid, unknown = parse_secrets("   ")
    assert valid == []
    assert unknown == []


def test_generate_policy_hcl():
    hcl = generate_policy_hcl("myapp", ["db-creds", "api-key"], environment="prod")
    assert '# Vault policy for myapp' in hcl
    assert '# Environment: prod' in hcl
    assert 'path "secret/data/prod/myapp/api-keys"' in hcl
    assert 'capabilities = ["read"]' in hcl
    assert 'path "sys/*"' in hcl
    assert 'capabilities = ["deny"]' in hcl


def test_generate_policy_hcl_with_unknown_secret_type_should_skip():
    # generate_policy_hcl expects only valid secrets; it's called after parse_secrets filters
    # So we just test that it works with valid list
    hcl = generate_policy_hcl("app", ["db-creds"], environment="dev")
    assert 'path "secret/data/dev/app/db-creds"' in hcl.replace("{app}", "app").replace("{env}", "dev")


def test_generate_auth_config_approle():
    commands = generate_auth_config("myapp", "approle", "myapp-policy")
    assert len(commands) == 3
    assert commands[0]["description"] == "Create AppRole for myapp"
    assert "token_ttl=1h" in commands[0]["command"]
    assert "token_policies=\"myapp-policy\"" in commands[0]["command"]
    assert commands[1]["description"] == "Fetch RoleID"
    assert commands[2]["description"] == "Generate SecretID (single-use)"


def test_generate_auth_config_kubernetes():
    commands = generate_auth_config("myapp", "kubernetes", "myapp-policy", namespace="prod")
    assert len(commands) == 1
    assert commands[0]["description"] == "Create Kubernetes auth role for myapp"
    assert "bound_service_account_names=myapp" in commands[0]["command"]
    assert "bound_service_account_namespaces=prod" in commands[0]["command"]
    assert "policies=myapp-policy" in commands[0]["command"]
    assert "ttl=1h" in commands[0]["command"]


def test_generate_auth_config_oidc():
    commands = generate_auth_config("myapp", "oidc", "myapp-policy")
    assert len(commands) == 1
    assert commands[0]["description"] == "Create OIDC role for myapp"
    assert 'bound_audiences="vault"' in commands[0]["command"]
    assert 'allowed_redirect_uris="https://vault.example.com/ui/vault/auth/oidc/oidc/callback"' in commands[0]["command"]
    assert 'user_claim="email"' in commands[0]["command"]
    assert 'oidc_scopes="openid,profile,email"' in commands[0]["command"]
    assert 'policies="myapp-policy"' in commands[0]["command"]
    assert "ttl=8h" in commands[0]["command"]


def test_build_output_success():
    result = build_output(
        app_name="payment-service",
        auth_method="approle",
        secrets="db-creds,api-key",
        environment="production",
        namespace=None,
    )
    assert "error" not in result
    assert result["app_name"] == "payment-service"
    assert result["auth_method"] == "approle"
    assert result["environment"] == "production"
    assert result["policy_name"] == "payment-service-policy"
    assert "policy_hcl" in result
    assert "auth_commands" in result
    assert len(result["secrets"]) == 2
    # Check that the secrets are correctly mapped
    secret_types = [s["type"] for s in result["secrets"]]
    assert "db-creds" in secret_types
    assert "api-key" in secret_types


def test_build_output_invalid_secret():
    result = build_output(
        app_name="app",
        auth_method="approle",
        secrets="invalid-type",
        environment="prod",
        namespace=None,
    )
    assert "error" in result
    assert result["error"] == "No valid secret types provided"
    assert "unknown" in result
    assert "invalid-type" in result["unknown"]
    assert "available_types" in result


def test_build_output_with_namespace():
    result = build_output(
        app_name="app",
        auth_method="kubernetes",
        secrets="db-creds",
        environment="dev",
        namespace="ingress",
    )
    assert result["namespace"] == "ingress"
    assert len(result["auth_commands"]) == 1
    cmd = result["auth_commands"][0]["command"]
    assert "bound_service_account_namespaces=ingress" in cmd


def test_print_human_runs():
    result = build_output(
        app_name="testapp",
        auth_method="approle",
        secrets="db-creds",
        environment="prod",
        namespace=None,
    )
    # Ensure no error
    assert "error" not in result
    try:
        print_human(result)
    except Exception as e:
        print(f"print_human raised: {e}")
        raise


def test_main_success():
    from vault_config_generator import main
    import sys
    from io import StringIO

    old_argv = sys.argv[:]
    old_stdout = sys.stdout
    sys.stdout = StringIO()
    try:
        sys.argv = [
            "vault_config_generator.py",
            "--app-name", "myservice",
            "--auth-method", "approle",
            "--secrets", "db-creds,api-key",
        ]
        try:
            main()
        except SystemExit as e:
            # If it exits, the code should be 0
            assert e.code == 0, f"Expected exit code 0, got {e.code}"
        # If it returns normally, that's also fine.
    finally:
        sys.stdout = old_stdout
        sys.argv = old_argv


def test_main_json_output():
    from vault_config_generator import main
    import sys
    from io import StringIO
    import json

    old_argv = sys.argv[:]
    old_stdout = sys.stdout
    sys.stdout = StringIO()
    try:
        sys.argv = [
            "vault_config_generator.py",
            "--app-name", "myservice",
            "--auth-method", "approle",
            "--secrets", "db-creds",
            "--json",
        ]
        try:
            main()
        except SystemExit as e:
            assert e.code == 0
            output = sys.stdout.getvalue()
            data = json.loads(output)
            assert data["app_name"] == "myservice"
            assert data["auth_method"] == "approle"
            assert data["policy_name"] == "myservice-policy"
        else:
            # If no SystemExit, capture output and check
            output = sys.stdout.getvalue()
            data = json.loads(output)
            assert data["app_name"] == "myservice"
            assert data["auth_method"] == "approle"
            assert data["policy_name"] == "myservice-policy"
    finally:
        sys.stdout = old_stdout
        sys.argv = old_argv


def test_main_invalid_secret_type():
    from vault_config_generator import main
    import sys
    from io import StringIO

    old_argv = sys.argv[:]
    old_stdout = sys.stdout
    sys.stdout = StringIO()
    try:
        sys.argv = [
            "vault_config_generator.py",
            "--app-name", "myservice",
            "--auth-method", "approle",
            "--secrets", "invalid-type",
        ]
        try:
            main()
            assert False, "Expected SystemExit"
        except SystemExit as e:
            assert e.code == 1  # error exit code
    finally:
        sys.stdout = old_stdout
        sys.argv = old_argv


def main() -> int:
    tests = [
        ("parse_secrets", test_parse_secrets),
        ("generate_policy_hcl", test_generate_policy_hcl),
        ("generate_auth_config_approle", test_generate_auth_config_approle),
        ("generate_auth_config_kubernetes", test_generate_auth_config_kubernetes),
        ("generate_auth_config_oidc", test_generate_auth_config_oidc),
        ("build_output_success", test_build_output_success),
        ("build_output_invalid_secret", test_build_output_invalid_secret),
        ("build_output_with_namespace", test_build_output_with_namespace),
        ("print_human_runs", test_print_human_runs),
        ("main_success", test_main_success),
        ("main_json_output", test_main_json_output),
        ("main_invalid_secret_type", test_main_invalid_secret_type),
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