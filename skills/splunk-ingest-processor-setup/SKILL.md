---
name: splunk-ingest-processor-setup
description: >-
  Render Cisco Data Fabric ingest-time routing workflows and Splunk Cloud
  Platform Ingest Processor setup plans with SPL2 pipelines, source types,
  destinations, lifecycle handoffs, queue and monitoring searches, metrics,
  OCSF, decrypt, S3 archive, custom pipeline templates, AI-powered data
  management readiness, and downstream readiness checks. Use when the user asks
  to configure Ingest Processor, author Ingest Processor pipelines, route or
  transform data at ingest time, validate Ingest Processor readiness, or compare
  Ingest Processor with Edge Processor and Data Manager, including Cisco Data
  Fabric or telemetry pipeline management requests that involve Splunk Cloud
  ingest-time routing and transformation.
metadata:
  category: observability
  source:
    repository: 'https://github.com/chambear2809/splunk-cisco-skills'
    path: skills/splunk-ingest-processor-setup
    license_path: LICENSE
    commit: 99b2c778dbeaad84023765d24e1a13f414009f6a
---

# Splunk Ingest Processor Setup

This skill is a render-first workflow for Splunk Cloud Platform Ingest
Processor. It prepares the complete operator packet for IP readiness,
source-type and destination setup, SPL2 pipeline authoring, monitoring, and
post-ingest data usability.

For newer Cisco Data Fabric wording, this is the Splunk Cloud ingest-time
pipeline route. Keep native Observability Metrics Pipeline Management requests
in `splunk-observability-deep-native-workflows` unless the user needs
source-type, destination, or SPL2 pipeline assets.

## Agent Behavior

- Do not claim private or undocumented Ingest Processor CRUD APIs. The apply
  path is a UI/support handoff unless Splunk publishes a stable public API.
- Keep credentials out of chat and rendered files. Use local chmod 600 files
  for HEC tokens, Observability access tokens, cloud keys, and private keys.
- Use `splunk-spl2-pipeline-kit` for SPL2 templates and compatibility linting.
- Hand off Splunk Enterprise destinations to `splunk-edge-processor-setup`;
  Ingest Processor destinations are Splunk Cloud, Observability Cloud, metrics
  indexes, and Amazon S3.
- Hand off post-ingest ES/ITSI/ARI/CIM/OCSF/dashboard validation to
  `splunk-data-source-readiness-doctor` when that skill is present.
- Read `reference.md` before changing coverage, limits, or lifecycle behavior.

## Quick Start

Render a complete offline packet:

```bash
bash skills/splunk-ingest-processor-setup/scripts/setup.sh \
  --phase all \
  --tenant-name acme-prod \
  --stack-url https://acme-prod.scs.splunk.com \
  --source-types "aws:cloudtrail,crowdstrike:fdr,json_app" \
  --destinations "splunk_indexer=type=splunk_cloud;default=true,metrics=type=metrics_index;index=metrics,s3_archive=type=s3;format=parquet;bucket=example-bucket" \
  --pipelines "redact_auth=template=redact;sourcetype=json_app;destination=splunk_indexer,http_metrics=template=metrics;destination=metrics"
```

Validate the skill offline:

```bash
bash skills/splunk-ingest-processor-setup/scripts/validate.sh
```

## Outputs

The default output directory is `splunk-ingest-processor-rendered/`:

- `readiness-report.md` and `coverage-report.json`.
- `apply-plan.json` with `ui_handoff` actions only.
- `source-types/*.json`, `destinations/*.json`, and `pipelines/*.spl2`.
- `spl2-pipeline-kit/` rendered by `splunk-spl2-pipeline-kit`.
- `monitoring/searches.spl` and `monitoring/usage-summary-handoff.md`.
- `lifecycle/*.md` for apply, edit, remove, refresh, delete, and rollback
  review.
- `handoffs/*.md` for HEC, Edge Processor, S3 Federated Search, and data-source
  readiness workflows.

## Coverage Rules

- Ingest Processor is Splunk Cloud Platform Victoria Experience only.
- Verify provisioning, subscription/tier, roles, service account access,
  indexes, lookups, and connection refresh before authoring pipelines.
- Confirm default destination behavior in the UI before applying a pipeline.
- Validate source-type event breaking, sample data, and preview results before
  apply.
- Treat Automated Field Extraction as region-gated UI assistance, not an API
  automation path.
- Treat AI-powered data management as UI assistance for onboarding, schema, and
  pipeline recommendations until Splunk publishes a stable public API.
- Treat decrypt as a private-key lookup workflow and warn about throughput.
- Treat S3 Object Lock as unsupported for rendered IP destination plans.
- Render and review known issue guardrails: tenant-admin-only editing, no data
  delivery guarantees under high back pressure or destination outages,
  single-browser-session editing, forwarder `useACK=false`, HEC indexer
  acknowledgement off, and CIDR lookup matching unsupported.

## Test Coverage

The `tests/` directory contains unit tests for `scripts/render_assets.py`,
using only the Python standard library (no third-party test framework
required). The bundled shell scripts (`setup.sh`, `validate.sh`,
`smoke_offline.sh`) are exercised by `validate.sh` itself.

Run the full suite with:

```bash
python3 skills/splunk-ingest-processor-setup/tests/test_render_assets.py
python3 skills/splunk-ingest-processor-setup/tests/test_render_helpers.py
```

### test_render_assets Tests
**File:** `tests/test_render_assets.py`

Tests cover:
- `csv_list` strips whitespace and drops empty entries
- `split_specs` passes through to `csv_list`
- `safe_name` replaces whitespace and symbols, preserves allowed chars
  (`:` `.` `-` `_`), and falls back to `unnamed` for blank input
- `parse_spec_list` parses name + key=value fields, treats bare fields as
  `true`, splits multiple specs by comma, and drops empty items
- `validate_secret_fields` rejects raw `password`/`secret`/`token` keys,
  allows `*_file` suffixes, rejects raw secret-like values, and accepts
  bool-like values and path-like values

### test_render_helpers Tests
**File:** `tests/test_render_helpers.py`

Tests cover:
- `render_source_type` includes the name and sample raw/csv paths, and
  sanitizes unsafe characters
- `render_lifecycle` produces apply and rollback runbooks
- `render_known_issues` lists every known issue guardrail and every AFE region
- `render_coverage` emits a JSON array of feature/coverage rows with valid
  statuses
- `render_readiness` renders findings (or the no-blocking-findings line)
- `render_ui_handoff` lists source types, destinations, and pipelines
- `render_monitoring_searches` includes sourcetype and index clauses plus
  mstats aggregation
- `render_usage_handoff` mentions DLQ and branch fan-out

All 30 tests (18 + 12) pass.
