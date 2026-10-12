#!/usr/bin/env python3
"""Unit tests for spl2_pipeline_kit.py: argument parsing, rendering, and orchestration.

Run with: python3 skills/splunk-spl2-pipeline-kit/tests/test_kit_render.py
No third-party test framework is required; uses only the standard library.
"""

import contextlib
import io
import json
import sys
import tempfile
import traceback
from argparse import Namespace
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

from spl2_pipeline_kit import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    EDGE_ONLY_COMMANDS,
    INGEST_ONLY_COMMANDS,
    PROFILES,
    PROFILE_COMMANDS,
    TEMPLATES,
    collect_lint_targets,
    main as kit_main,
    parse_args,
    profiles_for,
    render_coverage,
    render_lint_reports,
    render_readme,
    render_templates,
    run_lint,
    run_smoke,
)


VALID_IP = """$pipeline = | from $source
              | where sourcetype != "noisy:type"
              | into $destination;
"""


def test_parse_args_defaults():
    args = parse_args([])
    assert args.phase == "render"
    assert args.profile == "ingestProcessor"
    assert args.pipeline_file == []
    assert args.strict is False
    assert args.json is False
    assert args.output_dir == str(DEFAULT_OUTPUT_DIR)


def test_parse_args_all_profile_both_strict_json():
    args = parse_args(["--phase", "all", "--profile", "both", "--strict", "--json"])
    assert args.phase == "all"
    assert args.profile == "both"
    assert args.strict is True
    assert args.json is True


def test_parse_args_pipeline_file_appends():
    args = parse_args(
        ["--pipeline-file", "a.spl2", "--pipeline-file", "b.spl2"]
    )
    assert args.pipeline_file == ["a.spl2", "b.spl2"]


def test_profiles_for_resolves_both():
    assert profiles_for("both") == ["ingestProcessor", "edgeProcessor"]
    assert profiles_for("ingestProcessor") == ["ingestProcessor"]
    assert profiles_for("edgeProcessor") == ["edgeProcessor"]


def test_profile_definitions_are_consistent():
    assert PROFILES == ("ingestProcessor", "edgeProcessor")
    assert set(PROFILE_COMMANDS) == set(PROFILES)
    assert INGEST_ONLY_COMMANDS.isdisjoint(PROFILE_COMMANDS["edgeProcessor"])
    assert EDGE_ONLY_COMMANDS.isdisjoint(PROFILE_COMMANDS["ingestProcessor"])


def test_templates_defined_for_both_profiles():
    assert set(TEMPLATES) == set(PROFILES)
    assert len(TEMPLATES["ingestProcessor"]) >= 1
    assert len(TEMPLATES["edgeProcessor"]) >= 1


def test_render_templates_writes_all_starter_files():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        rendered = render_templates(out, list(PROFILES))
        expected = sum(len(TEMPLATES[p]) for p in PROFILES)
        assert len(rendered) == expected
        assert all(path.is_file() for path in rendered)
        assert (out / "templates/ingestProcessor/metrics.spl2").is_file()
        assert (out / "templates/ingestProcessor/decrypt.spl2").is_file()
        assert (out / "templates/edgeProcessor/route.spl2").is_file()
        assert (out / "custom-template-app/default/data/spl2/ip_route_redact_template.spl2").is_file()


def test_render_coverage_json_structure():
    with tempfile.TemporaryDirectory() as tmp:
        render_coverage(Path(tmp), ["ingestProcessor", "edgeProcessor"])
        data = json.loads((Path(tmp) / "coverage-report.json").read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) > 0
    statuses = {row["coverage_status"] for row in data}
    assert statuses <= {"rendered", "lint"}
    features = {row["feature"] for row in data}
    for name in ("filter", "route", "decrypt", "stats", "ocsf", "spl_to_spl2_lint", "pcre2_lint"):
        assert name in features
    for row in data:
        assert "profiles" in row


def test_render_lint_reports_writes_json_and_markdown():
    reports = [
        {
            "path": "/tmp/x.spl2",
            "profile": "ingestProcessor",
            "status": "PASS",
            "commands": ["from"],
            "imports": [],
            "findings": [],
        }
    ]
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        render_lint_reports(out, reports)
        loaded = json.loads((out / "lint-report.json").read_text(encoding="utf-8"))
        md = (out / "lint-report.md").read_text(encoding="utf-8")
    assert loaded == reports
    assert "# SPL2 Lint Report" in md
    assert "## /tmp/x.spl2" in md
    assert "Status:" in md


def test_render_lint_reports_renders_findings():
    reports = [
        {
            "path": "a.spl2",
            "profile": "ingestProcessor",
            "status": "FAIL",
            "commands": [],
            "imports": [],
            "findings": [
                {"severity": "error", "code": "SPL2-X", "message": "boom"}
            ],
        }
    ]
    with tempfile.TemporaryDirectory() as tmp:
        render_lint_reports(Path(tmp), reports)
        md = (Path(tmp) / "lint-report.md").read_text(encoding="utf-8")
    assert "ERROR SPL2-X: boom" in md


def test_render_readme_lists_profiles_and_secret_policy():
    with tempfile.TemporaryDirectory() as tmp:
        render_readme(Path(tmp), ["ingestProcessor", "edgeProcessor"])
        md = (Path(tmp) / "README.md").read_text(encoding="utf-8")
    assert "Profiles: ingestProcessor, edgeProcessor" in md
    assert "Secret policy" in md
    assert "lookup" in md.lower()


def test_collect_lint_targets_prefers_pipeline_file():
    with tempfile.TemporaryDirectory() as tmp:
        args = Namespace(pipeline_file=["/a/b.spl2"], output_dir=tmp)
        targets = collect_lint_targets(args, [])
    assert targets == [Path("/a/b.spl2").expanduser().resolve()]


def test_collect_lint_targets_falls_back_to_rendered():
    rendered = [Path("/tmp/rendered.spl2")]
    args = Namespace(pipeline_file=[], output_dir="/tmp")
    assert collect_lint_targets(args, rendered) == rendered


def test_collect_lint_targets_globs_templates_when_none_given():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        (out / "templates" / "ingestProcessor").mkdir(parents=True)
        (out / "templates" / "ingestProcessor" / "a.spl2").write_text("x")
        (out / "templates" / "edgeProcessor").mkdir(parents=True)
        (out / "templates" / "edgeProcessor" / "b.spl2").write_text("x")
        args = Namespace(pipeline_file=[], output_dir=str(out))
        targets = collect_lint_targets(args, [])
    positions = {t.name for t in targets}
    assert positions == {"a.spl2", "b.spl2"}


def test_run_lint_missing_file_reports_fail():
    args = Namespace(profile="ingestProcessor", strict=False)
    reports = run_lint(args, [Path("/nonexistent.spl2")])
    assert len(reports) == 1
    assert reports[0]["status"] == "FAIL"
    assert reports[0]["findings"][0]["code"] == "SPL2-FILE-MISSING"


def test_run_lint_existing_valid_file_passes():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "ok.spl2"
        path.write_text(VALID_IP, encoding="utf-8")
        args = Namespace(profile="ingestProcessor", strict=False)
        reports = run_lint(args, [path])
    assert reports[0]["status"] == "PASS"


def test_run_lint_detects_template_profile_from_path():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "templates" / "ingestProcessor" / "ok.spl2"
        path.parent.mkdir(parents=True)
        path.write_text(VALID_IP, encoding="utf-8")
        args = Namespace(profile="both", strict=False)
        reports = run_lint(args, [path])
    assert len(reports) == 1
    assert reports[0]["profile"] == "ingestProcessor"
    assert reports[0]["status"] == "PASS"


def test_main_all_profile_both_renders_and_lints_clean():
    with tempfile.TemporaryDirectory() as tmp:
        args = parse_args(["--phase", "all", "--profile", "both", "--output-dir", tmp])
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = kit_main(args)
        reports = json.loads((Path(tmp) / "lint-report.json").read_text(encoding="utf-8"))
        assert code == 0
        assert (Path(tmp) / "README.md").is_file()
        assert (Path(tmp) / "coverage-report.json").is_file()
        assert all(report["status"] == "PASS" for report in reports)


def test_main_render_phase_writes_templates_and_reports():
    with tempfile.TemporaryDirectory() as tmp:
        args = parse_args(["--phase", "render", "--profile", "ingestProcessor", "--output-dir", tmp])
        code = kit_main(args)
        assert (Path(tmp) / "templates/ingestProcessor/filter.spl2").is_file()
        assert (Path(tmp) / "coverage-report.json").is_file()
        assert (Path(tmp) / "lint-report.json").is_file()
    assert code == 0


def test_main_json_output_reports_status():
    with tempfile.TemporaryDirectory() as tmp:
        args = parse_args(
            ["--phase", "render", "--profile", "ingestProcessor", "--output-dir", tmp, "--json"]
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = kit_main(args)
        data = json.loads(buf.getvalue().strip())
    assert code == 0
    assert data["status"] == "PASS"
    assert "output_dir" in data


def test_main_lint_missing_pipeline_exits_fail():
    with tempfile.TemporaryDirectory() as tmp:
        args = parse_args(
            [
                "--phase", "lint",
                "--profile", "ingestProcessor",
                "--output-dir", tmp,
                "--pipeline-file", "/no/such/pipeline.spl2",
            ]
        )
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = kit_main(args)
    assert code == 1
    assert "FAIL" in buf.getvalue()


def test_run_smoke_returns_ok():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = run_smoke()
    assert code == 0
    assert "smoke_offline: OK" in buf.getvalue()


def main() -> int:
    tests = [
        ("parse_args_defaults", test_parse_args_defaults),
        ("parse_args_all_profile_both_strict_json", test_parse_args_all_profile_both_strict_json),
        ("parse_args_pipeline_file_appends", test_parse_args_pipeline_file_appends),
        ("profiles_for_resolves_both", test_profiles_for_resolves_both),
        ("profile_definitions_are_consistent", test_profile_definitions_are_consistent),
        ("templates_defined_for_both_profiles", test_templates_defined_for_both_profiles),
        ("render_templates_writes_all_starter_files", test_render_templates_writes_all_starter_files),
        ("render_coverage_json_structure", test_render_coverage_json_structure),
        ("render_lint_reports_writes_json_and_markdown", test_render_lint_reports_writes_json_and_markdown),
        ("render_lint_reports_renders_findings", test_render_lint_reports_renders_findings),
        ("render_readme_lists_profiles_and_secret_policy", test_render_readme_lists_profiles_and_secret_policy),
        ("collect_lint_targets_prefers_pipeline_file", test_collect_lint_targets_prefers_pipeline_file),
        ("collect_lint_targets_falls_back_to_rendered", test_collect_lint_targets_falls_back_to_rendered),
        ("collect_lint_targets_globs_templates_when_none_given", test_collect_lint_targets_globs_templates_when_none_given),
        ("run_lint_missing_file_reports_fail", test_run_lint_missing_file_reports_fail),
        ("run_lint_existing_valid_file_passes", test_run_lint_existing_valid_file_passes),
        ("run_lint_detects_template_profile_from_path", test_run_lint_detects_template_profile_from_path),
        ("main_all_profile_both_renders_and_lints_clean", test_main_all_profile_both_renders_and_lints_clean),
        ("main_render_phase_writes_templates_and_reports", test_main_render_phase_writes_templates_and_reports),
        ("main_json_output_reports_status", test_main_json_output_reports_status),
        ("main_lint_missing_pipeline_exits_fail", test_main_lint_missing_pipeline_exits_fail),
        ("run_smoke_returns_ok", test_run_smoke_returns_ok),
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
