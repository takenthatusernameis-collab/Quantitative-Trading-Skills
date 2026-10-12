---
name: senior-data-engineer
description: >-
  Data engineering skill for building scalable data pipelines, ETL/ELT systems,
  and data infrastructure. Expertise in Python, SQL, Spark, Airflow, dbt, Kafka,
  and modern data stack. Includes data modeling, pipeline orchestration, data
  quality, and DataOps. Use when designing data architectures, building data
  pipelines, optimizing data workflows, implementing data governance, or
  troubleshooting data issues.
metadata:
  category: data
  source:
    repository: 'https://github.com/alirezarezvani/claude-skills'
    path: engineering-team/skills/senior-data-engineer
    license_path: LICENSE
    commit: 4a3c05b69e64f4925f7fc65c88890f614f79caf0
---

# Senior Data Engineer

Production-grade data engineering skill for building scalable, reliable data systems.

## Table of Contents

1. [Trigger Phrases](#trigger-phrases)
2. [Quick Start](#quick-start)
3. [Workflows](#workflows)
4. [Architecture Decision Framework](#architecture-decision-framework)
5. [Tech Stack](#tech-stack)
6. [Reference Documentation](#reference-documentation)
7. [Troubleshooting](#troubleshooting)

---

## Trigger Phrases

Activate this skill when you see:

**Pipeline Design:**
- "Design a data pipeline for..."
- "Build an ETL/ELT process..."
- "How should I ingest data from..."
- "Set up data extraction from..."

**Architecture:**
- "Should I use batch or streaming?"
- "Lambda vs Kappa architecture"
- "How to handle late-arriving data"
- "Design a data lakehouse"

**Data Modeling:**
- "Create a dimensional model..."
- "Star schema vs snowflake"
- "Implement slowly changing dimensions"
- "Design a data vault"

**Data Quality:**
- "Add data validation to..."
- "Set up data quality checks"
- "Monitor data freshness"
- "Implement data contracts"

**Performance:**
- "Optimize this Spark job"
- "Query is running slow"
- "Reduce pipeline execution time"
- "Tune Airflow DAG"

---

## Quick Start

### Core Tools

```bash
# Generate pipeline orchestration config
python scripts/pipeline_orchestrator.py generate \
  --type airflow \
  --source postgres \
  --destination snowflake \
  --schedule "0 5 * * *"

# Validate data quality
python scripts/data_quality_validator.py validate \
  --input data/sales.parquet \
  --schema schemas/sales.json \
  --checks freshness,completeness,uniqueness

# Optimize ETL performance
python scripts/etl_performance_optimizer.py analyze \
  --query queries/daily_aggregation.sql \
  --engine spark \
  --recommend
```

---

## Workflows
→ See references/workflows.md for details

## Architecture Decision Framework

Use this framework to choose the right approach for your data pipeline.

### Batch vs Streaming

| Criteria | Batch | Streaming |
|----------|-------|-----------|
| **Latency requirement** | Hours to days | Seconds to minutes |
| **Data volume** | Large historical datasets | Continuous event streams |
| **Processing complexity** | Complex transformations, ML | Simple aggregations, filtering |
| **Cost sensitivity** | More cost-effective | Higher infrastructure cost |
| **Error handling** | Easier to reprocess | Requires careful design |

**Decision Tree:**
```
Is real-time insight required?
├── Yes → Use streaming
│   └── Is exactly-once semantics needed?
│       ├── Yes → Kafka + Flink/Spark Structured Streaming
│       └── No → Kafka + consumer groups
└── No → Use batch
    └── Is data volume > 1TB daily?
        ├── Yes → Spark/Databricks
        └── No → dbt + warehouse compute
```

### Lambda vs Kappa Architecture

| Aspect | Lambda | Kappa |
|--------|--------|-------|
| **Complexity** | Two codebases (batch + stream) | Single codebase |
| **Maintenance** | Higher (sync batch/stream logic) | Lower |
| **Reprocessing** | Native batch layer | Replay from source |
| **Use case** | ML training + real-time serving | Pure event-driven |

**When to choose Lambda:**
- Need to train ML models on historical data
- Complex batch transformations not feasible in streaming
- Existing batch infrastructure

**When to choose Kappa:**
- Event-sourced architecture
- All processing can be expressed as stream operations
- Starting fresh without legacy systems

### Data Warehouse vs Data Lakehouse

| Feature | Warehouse (Snowflake/BigQuery) | Lakehouse (Delta/Iceberg) |
|---------|-------------------------------|---------------------------|
| **Best for** | BI, SQL analytics | ML, unstructured data |
| **Storage cost** | Higher (proprietary format) | Lower (open formats) |
| **Flexibility** | Schema-on-write | Schema-on-read |
| **Performance** | Excellent for SQL | Good, improving |
| **Ecosystem** | Mature BI tools | Growing ML tooling |

---

## Tech Stack

| Category | Technologies |
|----------|--------------|
| **Languages** | Python, SQL, Scala |
| **Orchestration** | Airflow, Prefect, Dagster |
| **Transformation** | dbt, Spark, Flink |
| **Streaming** | Kafka, Kinesis, Pub/Sub |
| **Storage** | S3, GCS, Delta Lake, Iceberg |
| **Warehouses** | Snowflake, BigQuery, Redshift, Databricks |
| **Quality** | Great Expectations, dbt tests, Monte Carlo |
| **Monitoring** | Prometheus, Grafana, Datadog |

---

## Reference Documentation

### 1. Data Pipeline Architecture
See `references/data_pipeline_architecture.md` for:
- Lambda vs Kappa architecture patterns
- Batch processing with Spark and Airflow
- Stream processing with Kafka and Flink
- Exactly-once semantics implementation
- Error handling and dead letter queues

### 2. Data Modeling Patterns
See `references/data_modeling_patterns.md` for:
- Dimensional modeling (Star/Snowflake)
- Slowly Changing Dimensions (SCD Types 1-6)
- Data Vault modeling
- dbt best practices
- Partitioning and clustering

### 3. DataOps Best Practices
See `references/dataops_best_practices.md` for:
- Data testing frameworks
- Data contracts and schema validation
- CI/CD for data pipelines
- Observability and lineage
- Incident response

---

## Troubleshooting
→ See references/troubleshooting.md for details

## Test Coverage

This skill bundles a standard-library unit-test suite (no third-party
test framework) under `tests/`, following the pattern established by
`skills/quantitative-backtesting/tests/`. Run the test files directly
with Python:

```bash
python3 skills/senior-data-engineer/tests/test_data_quality_validator.py
python3 skills/senior-data-engineer/tests/test_etl_performance_optimizer.py
python3 skills/senior-data-engineer/tests/test_pipeline_orchestrator.py
```

- `test_data_quality_validator.py` - stdlib-only tests for `scripts/data_quality_validator.py` (129 tests):
  - Dataclasses: `ColumnSchema`, `DataSchema`, `ValidationResult`, `ColumnProfile`, `QualityScore` construction, defaults, and `asdict` serialization
  - `TypeDetector`: type inference for email, uuid, phone, url, ipv4, datetime, integer, float, boolean, and string samples; pattern-detection thresholds
  - `SchemaValidator`: not-null, uniqueness, data-type, value-range, string-length, pattern, allowed-values, primary-key, row-count, and missing-column checks, plus the `_validate_type`/`_validate_range`/`_validate_length`/`_validate_pattern`/`_validate_primary_key` helpers
  - `AnomalyDetector`: z-score and IQR outlier detection, custom thresholds, non-numeric columns, and small-sample guards
  - `DataProfiler`: null/unique statistics, numeric and string stats, top values, duplicate-row counting, and memory estimation
  - `GreatExpectationsGenerator`: suite structure, table-level expectations, and type-specific column expectations (integer, float, email, date, string length, categorical sets, `mostly` computation)
  - `QualityScoreCalculator`: completeness, uniqueness, validity, consistency, accuracy, and weighted overall scoring for populated and empty profiles
  - `DataContractValidator`: contract validation (type mismatch, missing columns, nullability, SLA row bounds), type-compatibility groups, simple YAML parsing, and JSON/YAML contract loading
  - `ReportGenerator`: text report sections and JSON report structure
  - `DataLoader`: CSV, JSON (list/object/data-key/scalar), and JSONL loading, plus missing-file and unsupported-format errors
  - `SchemaLoader`: full schema loading and default values
  - CLI: subcommand exit codes, `--detect-anomalies` flag, text/JSON output, and log-message capture via a custom logging handler
- `test_etl_performance_optimizer.py` - stdlib-only tests for `scripts/etl_performance_optimizer.py` (172 tests):
  - Dataclasses: `SQLQueryInfo`, `OptimizationRecommendation`, `SparkJobMetrics`, `PartitionStrategy`, `CostEstimate` construction, defaults, and `asdict` serialization
  - `SQLParser`: SQL cleaning (line/block comments, whitespace), query-type detection (SELECT/INSERT/UPDATE/DELETE/MERGE/CREATE/UNKNOWN), SELECT-clause extraction (columns, aliases, `SELECT *`, `COUNT(*)`, qualified columns), WHERE/AND/OR splitting, GROUP BY/ORDER BY/LIMIT, DISTINCT, aggregations (including MEDIAN/PERCENTILE_CONT), CTEs, subqueries, and window functions
  - `SQLParser` complexity scoring: low/medium/high/very_high thresholds across tables, join types, subqueries, aggregations, and window functions
  - `SQLOptimizer`: recommendation triggers for SELECT *, missing WHERE, CROSS JOIN, missing join condition, many joins, DISTINCT, ORDER BY without LIMIT, subquery-to-CTE conversion, partition pruning, index opportunities (filter and join columns), high-cardinality GROUP BY, and COUNT DISTINCT, plus priority sorting
  - `SparkJobAnalyzer`: skew, shuffle, GC-overhead, task-failure (high/medium severity boundary), speculation, too-many-tasks, and low-parallelism recommendations with threshold boundaries and implementation math
  - `PartitionAdvisor`: range (date/timestamp), list (low cardinality), and hash (medium cardinality, power-of-two rounding) strategies, null-percentage and high-cardinality skips, top-3 selection, and partition-size ordering
  - `CostEstimator`: BigQuery/Snowflake/Redshift/Databricks estimates, minimum-billing floors, warehouse case-insensitivity, unknown-warehouse `ValueError`, and `_estimate_data_scanned` filter/projection discounts
  - `ReportGenerator`: text report sections, severity icons, and JSON report structure with severity summary counts
  - CLI: subcommand exit codes (1 for no-command/error, 2 for argparse errors), inline and file-based SQL input, text/JSON output, output-file writing with log-message capture, Spark job arrays with deduplication, partition recommendations, cost estimates, and template generation
- `test_pipeline_orchestrator.py` - stdlib-only tests for `scripts/pipeline_orchestrator.py` (150 tests):
  - Dataclasses: `SourceConfig`, `DestinationConfig`, `TaskConfig`, and `PipelineConfig` construction, defaults, `asdict` serialization, and dataclass-type checks
  - `PipelineGenerator` (ABC): abstractness, non-instantiability, and required abstract methods (`generate`/`validate`)
  - `AirflowGenerator`: import collection (base imports ordering, source/destination-driven operator imports, no duplicates, S3/Bash/Email operators), per-operator task generation (Python/Bash/SQL/Snowflake/generic), DAG definition and `default_args` rendering, dependency-arrow (`dep >> task`) generation, full codegen structure, `compile` correctness, and `validate` (missing `default_args`, missing DAG context, missing `schedule_interval` warning, syntax errors, dict-key shape, and the empty-tasks compile quirk where the `with DAG` body is only a comment)
  - `PrefectGenerator`: header imports, flow-name dash replacement (`-`/`_`), `@task` decorators, retries/retry-delay/cache-expiration params, task function signatures, flow call-graph (root task vs. first-dependency input), `__main__` guard, `compile` correctness, custom `cache_hours`/`retries`, and `validate` (missing `@flow`/`@task`, syntax errors)
  - `DagsterGenerator`: header imports, job-name dash replacement, ops with/without input (signature and `In`/`Out` declarations), asset-materialization blocks (with `row_count` metadata for input ops, bare for leaf ops), job call-graph, `result = {}` vs `result = input_data` rendering, `compile` correctness, and `validate` (missing `@job`/`@op`, syntax errors)
  - `ETLPatternGenerator.generate_extract_load`: name/description/schedule/tags, source/destination configs and connection-id naming, incremental/full mode write-mode and `incremental_strategy` differences, extract/load/quality-check task naming and dependencies (2 tables -> 5 tasks, ordered), extract SQL (`prev_ds` incremental template vs. plain `SELECT *` for full)
  - `ETLPatternGenerator.generate_transform_pipeline`: name/description/schedule/tags, per-source freshness sensors, `dbt_run` (120-min timeout, `wait_for_*` dependencies, `dbt run --select` command) and `dbt_test` (depends on `dbt_run`, `dbt test` command), task ordering, and absence of source/destination
  - CLI: no-command and invalid/missing-argument exit codes (1 and 2), `generate` for all three frameworks with stdout and `--output`/`--name`/`--schedule`/`--mode`/`--tables` overrides, `generate --config` with scalar-only YAML (works) and nested-dict configs (quirk: exits 1 because nested dataclasses are not reconstructed), `validate` with valid/invalid DAGs and missing args producing JSON with exit codes, and `template` for `extract-load`/`transform`/`cdc` (including the unimplemented `cdc` exit-1 quirk and missing-required-args exit 2)
