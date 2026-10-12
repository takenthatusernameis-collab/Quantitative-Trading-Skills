---
name: splunk-spl2-pipeline-kit
description: >-
  Render and lint reusable SPL2 pipeline templates for Cisco Data Fabric, Splunk
  Ingest Processor, and Edge Processor, including routing, redaction, sampling,
  lookups, metrics, OCSF, decrypt, stats, custom templates, SPL-to-SPL2
  compatibility, and PCRE2 migration checks. Use when the user needs SPL2
  pipeline authoring, conversion review, compatibility linting, or shared
  templates for Ingest Processor or Edge Processor workflows, including Cisco
  Data Fabric or telemetry pipeline management requests that need reusable SPL2
  pipeline logic.
metadata:
  category: observability
  source:
    repository: 'https://github.com/chambear2809/splunk-cisco-skills'
    path: skills/splunk-spl2-pipeline-kit
    license_path: LICENSE
    commit: 99b2c778dbeaad84023765d24e1a13f414009f6a
---

# Splunk SPL2 Pipeline Kit

This skill is the shared SPL2 authoring and validation surface for
`splunk-ingest-processor-setup` and `splunk-edge-processor-setup`. It is
offline-only: it renders starter SPL2, lints pipeline files, and reports
profile compatibility issues without calling Splunk APIs.

For newer Cisco Data Fabric wording, this is the reusable SPL2 authoring route.
Native Observability Metrics Pipeline Management remains a separate UI workflow
covered by `splunk-observability-deep-native-workflows`.

## Agent Behavior

- Use `ingestProcessor` for Splunk-hosted Ingest Processor pipelines.
- Use `edgeProcessor` for Edge Processor pipelines.
- Keep real samples, private keys, HEC tokens, Observability tokens, and lookup
  contents out of chat and rendered files. Render placeholders and file-path
  handoffs only.
- Treat SPL-to-SPL2 conversion as review assistance. Splunk's in-product
  conversion tool remains the authoritative conversion workflow.
- Read `reference.md` before changing supported commands, templates, or lint
  rules.

## Quick Start

Render every template and lint the rendered output:

```bash
bash skills/splunk-spl2-pipeline-kit/scripts/setup.sh --phase all --profile both
```

Lint a user-provided pipeline:

```bash
bash skills/splunk-spl2-pipeline-kit/scripts/setup.sh \
  --phase lint \
  --profile ingestProcessor \
  --pipeline-file pipelines/my_pipeline.spl2
```

Run the offline smoke test:

```bash
bash skills/splunk-spl2-pipeline-kit/scripts/smoke_offline.sh
```

## Outputs

The default output directory is `splunk-spl2-pipeline-kit-rendered/`:

- `templates/<profile>/*.spl2` - route, branch, redact, sample, lookup,
  extract, timestamp, JSON/XML, OCSF, decrypt, metrics, stats, S3, and
  compatibility starters where supported.
- `custom-template-app/default/data/spl2/*.spl2` - SPL2 custom template module
  examples using `@template` and runtime profile metadata.
- `lint-report.json` and `lint-report.md`.
- `coverage-report.json`.

## Guardrails

- `logs_to_metrics` requires an `import logs_to_metrics from
  /splunk.ingest.commands` style import and is Ingest Processor-only.
- `decrypt` is Ingest Processor-only and must be treated as a private-key
  lookup handoff. Do not render private-key material.
- `stats` linting rejects `avg()` because Ingest Processor documents
  `sum()/count()` as the supported average pattern. Edge Processor `stats` is
  supported and includes newer state-window behavior on current EP versions.
- `object_to_array()` is deprecated in SPL2 release notes; use
  `json_entries()`.
- Regex guidance is PCRE2-oriented. Prefer named captures like
  `(?P<fieldName>...)`.
- Edge Processor-only and Ingest Processor-only differences are reported in
  the lint output rather than hidden in comments.

## Test Coverage

This skill bundles a standard-library unit-test suite (no third-party test
framework) under `tests/`, following the pattern established by
`skills/quantitative-backtesting/tests/`. Run either file directly with Python:

```bash
python3 skills/splunk-spl2-pipeline-kit/tests/test_kit_lint.py
python3 skills/splunk-spl2-pipeline-kit/tests/test_kit_render.py
```

- `test_kit_lint.py` - pure lint/parsing helpers:
  - `strip_comments` removes `//` comments inline while preserving pipeline text
  - `command_names` extracts piped commands and ignores commented-out pipes
  - `import_names` parses `import <name> from` blocks
  - `LintFinding.as_dict` serializes severity/code/message
  - `lint_text` emits each finding branch: `SPL2-MISSING-PIPELINE`,
    `SPL2-MISSING-SOURCE`, `SPL2-MISSING-DESTINATION`, `SPL2-PROFILE-INCOMPATIBLE`
    (ingest-only command under `edgeProcessor`), `SPL2-METRICS-IMPORT`,
    `SPL2-UNKNOWN-COMMAND` (warning vs. error under `--strict`), `SPL2-STATS-AVG`,
    `SPL2-STATS-FUNCTION`, `SPL2-DEPRECATED-FUNCTION`, `SPL2-PCRE2-NAMED-CAPTURE`
    (rejects bare `(?<`) while accepting Splunk `(?P<`, and
    `SPL2-PCRE2-BACKREFERENCE`)
  - `lint_file` returns `PASS` for a clean template and `FAIL` for one missing `$pipeline`
  - `status_from_reports` rolls up `PASS` / `PASS_WITH_WARNINGS` / `FAIL`
- `test_kit_render.py` - argument parsing, rendering, and orchestration:
  - `parse_args` defaults, `--profile both`, `--strict`/`--json`, and
    `--pipeline-file` append behavior
  - `profiles_for` and the profile-command catalog definitions stay consistent
  - `render_templates` writes every starter and the custom template app
  - `render_coverage` emits a JSON array with `rendered`/`lint` statuses
  - `render_lint_reports` writes JSON and Markdown and renders findings
  - `render_readme` lists profiles and the secret-policy notice
  - `collect_lint_targets` prefers `--pipeline-file`, then rendered assets,
    then globs `templates/**/*.spl2`
  - `run_lint` reports `SPL2-FILE-MISSING` for absent files, `PASS` for clean
    files, and detects the profile from the template path
  - `main` flows for `--phase all`, `--phase render`, `--phase lint`, and
    `--json` output, plus the offline `run_smoke` integration check

The end-to-end path (`main` invoking the kit) is also exercised via
`scripts/smoke_offline.sh` and `scripts/validate.sh`; those remain the
authoritative offline regression gates.
