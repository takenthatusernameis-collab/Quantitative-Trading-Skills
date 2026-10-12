#!/usr/bin/env python3
"""Unit tests for pipeline_orchestrator.py (Airflow/Prefect/Dagster codegen)."""

import contextlib
import io
import json
import sys
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

import pipeline_orchestrator as PO  # noqa: E402
from pipeline_orchestrator import main as po_main  # noqa: E402  (alias to avoid shadowing)

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


# ── Helpers ──────────────────────────────────────────────────


def _run_main(argv):
    """Run po_main() with a patched argv.

    Unlike etl_performance_optimizer's main(), pipeline_orchestrator.main()
    always calls sys.exit() on every code path (including success via
    ``sys.exit(0)``), so every CLI invocation raises SystemExit. Returns
    ``(status, code, stdout)`` where ``status`` is ``"exit"`` or ``"ok"``.
    """
    old = sys.argv
    sys.argv = argv
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            try:
                po_main()
                return ("ok", None, buf.getvalue())
            except SystemExit as e:
                return ("exit", e.code, buf.getvalue())
    finally:
        sys.argv = old


def _capture_main(argv):
    """Run the CLI and return only the captured stdout."""
    _, _, out = _run_main(argv)
    return out


def _write_yaml(tmpdir, name, obj):
    path = tmpdir / name
    path.write_text(yaml.safe_dump(obj))
    return path


def _write_json(tmpdir, name, obj):
    path = tmpdir / name
    path.write_text(json.dumps(obj))
    return path


def _base_config(**overrides):
    """A minimal two-task ETL config (postgres -> snowflake)."""
    base = dict(
        name="etl-dag",
        description="ETL pipeline",
        schedule="@daily",
        source=PO.SourceConfig(type="postgres", connection_id="pg"),
        destination=PO.DestinationConfig(type="snowflake", connection_id="sf"),
        tasks=[
            PO.TaskConfig(task_id="extract_data", operator="python_operator",
                          params={"callable": "extract"}),
            PO.TaskConfig(task_id="load_data", operator="python_operator",
                          params={"callable": "load"},
                          dependencies=["extract_data"]),
        ],
    )
    base.update(overrides)
    return PO.PipelineConfig(**base)


# Shared collaborators (the custom runner instantiates test classes
# without invoking pytest-style setup_method, so fixtures are singletons)
_AIRFLOW = PO.AirflowGenerator()
_PREFECT = PO.PrefectGenerator()
_DAGSTER = PO.DagsterGenerator()
_ETL = PO.ETLPatternGenerator


# ── Dataclasses ──────────────────────────────────────────────


class TestDataclasses:
    def test_source_config_required_fields(self):
        sc = PO.SourceConfig(type="postgres", connection_id="c1")
        assert sc.type == "postgres"
        assert sc.connection_id == "c1"

    def test_source_config_defaults(self):
        sc = PO.SourceConfig(type="s3", connection_id="c")
        assert sc.schema is None
        assert sc.tables == []
        assert sc.query is None
        assert sc.incremental_column is None
        assert sc.incremental_strategy == "timestamp"

    def test_source_config_asdict_keys(self):
        sc = PO.SourceConfig(type="mysql", connection_id="c")
        assert sorted(asdict(sc).keys()) == [
            "connection_id", "incremental_column", "incremental_strategy",
            "query", "schema", "tables", "type",
        ]

    def test_destination_config_required_fields(self):
        dc = PO.DestinationConfig(type="snowflake", connection_id="c2")
        assert dc.type == "snowflake"
        assert dc.connection_id == "c2"

    def test_destination_config_defaults(self):
        dc = PO.DestinationConfig(type="bigquery", connection_id="c")
        assert dc.schema == "raw"
        assert dc.write_mode == "append"
        assert dc.partition_by is None
        assert dc.cluster_by == []

    def test_destination_config_asdict_keys(self):
        dc = PO.DestinationConfig(type="s3", connection_id="c")
        assert sorted(asdict(dc).keys()) == [
            "cluster_by", "connection_id", "partition_by", "schema",
            "type", "write_mode",
        ]

    def test_task_config_required_fields(self):
        tc = PO.TaskConfig(task_id="t1", operator="python_operator")
        assert tc.task_id == "t1"
        assert tc.operator == "python_operator"

    def test_task_config_defaults(self):
        tc = PO.TaskConfig(task_id="t", operator="bash_operator")
        assert tc.dependencies == []
        assert tc.params == {}
        assert tc.retries == 2
        assert tc.retry_delay_minutes == 5
        assert tc.timeout_minutes == 60
        assert tc.pool is None
        assert tc.priority_weight == 1

    def test_task_config_asdict_keys(self):
        tc = PO.TaskConfig(task_id="t", operator="python_operator")
        assert sorted(asdict(tc).keys()) == [
            "dependencies", "operator", "params", "pool",
            "priority_weight", "retries", "retry_delay_minutes",
            "task_id", "timeout_minutes",
        ]

    def test_pipeline_config_required_fields(self):
        pc = PO.PipelineConfig(name="n", description="d", schedule="@daily")
        assert pc.name == "n"
        assert pc.description == "d"
        assert pc.schedule == "@daily"

    def test_pipeline_config_defaults(self):
        pc = PO.PipelineConfig(name="n", description="d", schedule="@daily")
        assert pc.owner == "data-team"
        assert pc.tags == []
        assert pc.catchup is False
        assert pc.max_active_runs == 1
        assert pc.default_retries == 2
        assert pc.source is None
        assert pc.destination is None
        assert pc.tasks == []

    def test_pipeline_config_asdict_keys(self):
        pc = PO.PipelineConfig(name="n", description="d", schedule="@daily")
        assert sorted(asdict(pc).keys()) == [
            "catchup", "default_retries", "description", "destination",
            "max_active_runs", "name", "owner", "schedule", "source",
            "tags", "tasks",
        ]

    def test_all_four_dataclasses_are_dataclass(self):
        assert is_dataclass(PO.SourceConfig)
        assert is_dataclass(PO.DestinationConfig)
        assert is_dataclass(PO.TaskConfig)
        assert is_dataclass(PO.PipelineConfig)


# ── Abstract base class ──────────────────────────────────────


class TestAbstractBaseClass:
    def test_pipeline_generator_is_abstract(self):
        import abc
        assert issubclass(PO.PipelineGenerator, abc.ABC)

    def test_cannot_instantiate_abstract(self):
        try:
            PO.PipelineGenerator()
            assert False, "expected TypeError"
        except TypeError:
            pass

    def test_subclasses_are_abstract_methods(self):
        assert "generate" in PO.PipelineGenerator.__abstractmethods__
        assert "validate" in PO.PipelineGenerator.__abstractmethods__


# ── AirflowGenerator: imports ────────────────────────────────


class TestAirflowImports:
    def test_collect_imports_base_order(self):
        imports = _AIRFLOW._collect_imports(_base_config())
        # The three base imports always come first, in this order.
        assert imports[:3] == [
            "from airflow import DAG",
            "from airflow.utils.dates import days_ago",
            "from datetime import datetime, timedelta",
        ]

    def test_collect_imports_includes_postgres_operator(self):
        imports = _AIRFLOW._collect_imports(_base_config())
        assert "from airflow.providers.postgres.operators.postgres import PostgresOperator" in imports

    def test_collect_imports_includes_snowflake_operator(self):
        imports = _AIRFLOW._collect_imports(_base_config())
        assert "from airflow.providers.snowflake.operators.snowflake import SnowflakeOperator" in imports

    def test_collect_imports_python_operator(self):
        imports = _AIRFLOW._collect_imports(_base_config())
        assert "from airflow.operators.python import PythonOperator" in imports

    def test_collect_imports_bash_operator(self):
        cfg = _base_config(tasks=[
            PO.TaskConfig(task_id="b", operator="bash_operator",
                          params={"command": "echo hi"})])
        imports = _AIRFLOW._collect_imports(cfg)
        assert "from airflow.operators.bash import BashOperator" in imports

    def test_collect_imports_email_operator_when_email_task(self):
        cfg = _base_config(tasks=[
            PO.TaskConfig(task_id="e", operator="email_operator")])
        imports = _AIRFLOW._collect_imports(cfg)
        assert "from airflow.operators.email import EmailOperator" in imports

    def test_collect_imports_no_duplicate_base(self):
        imports = _AIRFLOW._collect_imports(_base_config())
        assert imports.count("from airflow import DAG") == 1

    def test_collect_imports_s3_uses_provider(self):
        cfg = _base_config(source=PO.SourceConfig(type="s3", connection_id="s"),
                           tasks=[PO.TaskConfig(task_id="p", operator="python_operator")])
        imports = _AIRFLOW._collect_imports(cfg)
        assert "from airflow.providers.amazon.aws.operators.s3 import S3CreateBucketOperator" in imports

    def test_collect_imports_no_source_no_extra(self):
        cfg = _base_config(source=None, destination=None,
                           tasks=[PO.TaskConfig(task_id="p", operator="python_operator")])
        imports = _AIRFLOW._collect_imports(cfg)
        assert "from airflow import DAG" in imports
        assert "from airflow.providers" not in " ".join(imports)


# ── AirflowGenerator: task generation ────────────────────────


class TestAirflowTasks:
    def test_python_task_uses_callable_from_params(self):
        task = PO.TaskConfig(task_id="extract_data", operator="python_operator",
                             params={"callable": "extract"})
        code = _AIRFLOW._generate_python_task(task)
        assert "def extract(**kwargs):" in code
        assert "task_id='extract_data'" in code
        assert "python_callable=extract" in code
        assert "retries=2" in code
        assert "retry_delay=timedelta(minutes=5)" in code
        assert "execution_timeout=timedelta(minutes=60)" in code

    def test_python_task_default_callable(self):
        task = PO.TaskConfig(task_id="t", operator="python_operator")
        code = _AIRFLOW._generate_python_task(task)
        assert "def process_data(**kwargs):" in code
        assert "python_callable=process_data" in code

    def test_bash_task_uses_command_from_params(self):
        task = PO.TaskConfig(task_id="b", operator="bash_operator",
                             params={"command": "echo hi"})
        code = _AIRFLOW._generate_bash_task(task)
        assert "bash_command='echo hi'" in code
        assert "task_id='b'" in code
        assert "BashOperator(" in code

    def test_bash_task_default_command(self):
        task = PO.TaskConfig(task_id="b", operator="bash_operator")
        code = _AIRFLOW._generate_bash_task(task)
        assert "bash_command='echo \"Hello World\"'" in code

    def test_sql_task_uses_source_connection(self):
        task = PO.TaskConfig(task_id="q", operator="sql_operator",
                             params={"sql": "SELECT 1"})
        cfg = _base_config()
        code = _AIRFLOW._generate_sql_task(task, cfg)
        assert "PostgresOperator(" in code
        assert "postgres_conn_id='pg'" in code
        assert 'sql="""SELECT 1"""' in code

    def test_sql_task_falls_back_to_default_conn(self):
        task = PO.TaskConfig(task_id="q", operator="sql_operator",
                             params={"sql": "SELECT 1"})
        cfg = _base_config(source=None)
        code = _AIRFLOW._generate_sql_task(task, cfg)
        assert "postgres_conn_id='default_conn'" in code

    def test_snowflake_task_uses_default_conn_id(self):
        task = PO.TaskConfig(task_id="sf", operator="snowflake_operator",
                             params={"sql": "SELECT 2"})
        code = _AIRFLOW._generate_snowflake_task(task)
        assert "SnowflakeOperator(" in code
        assert "snowflake_conn_id='snowflake_default'" in code
        assert 'sql="""SELECT 2"""' in code

    def test_generic_task_for_unknown_operator(self):
        task = PO.TaskConfig(task_id="custom_task", operator="email_operator")
        code = _AIRFLOW._generate_generic_task(task)
        assert "# TODO: Implement email_operator for custom_task" in code
        assert "custom_task = PythonOperator(" in code
        assert 'python_callable=lambda: print("custom_task")' in code

    def test_task_operator_dispatch_sql_via_postgres(self):
        cfg = _base_config(tasks=[
            PO.TaskConfig(task_id="run_sql", operator="sql_operator",
                          params={"sql": "SELECT 1"},
                          dependencies=["extract_data"])])
        code = _AIRFLOW.generate(cfg)
        assert "run_sql = PostgresOperator(" in code

    def test_task_operator_dispatch_snowflake(self):
        cfg = _base_config(tasks=[
            PO.TaskConfig(task_id="s", operator="snowflake_operator",
                          params={"sql": "SELECT 2"})])
        code = _AIRFLOW.generate(cfg)
        assert "SnowflakeOperator(" in code

    def test_task_operator_dispatch_bash(self):
        cfg = _base_config(tasks=[
            PO.TaskConfig(task_id="b", operator="bash", params={"command": "ls"})])
        code = _AIRFLOW.generate(cfg)
        assert "BashOperator(" in code


# ── AirflowGenerator: definitions ───────────────────────────


class TestAirflowDefinitions:
    def test_dag_definition_contains_required_keys(self):
        code = _AIRFLOW._generate_dag_definition(_base_config())
        assert "with DAG(" in code
        assert "dag_id='etl-dag'" in code
        assert "schedule_interval='@daily'" in code
        assert "start_date=days_ago(1)" in code
        assert "catchup=False" in code
        assert "max_active_runs=1" in code

    def test_dag_definition_tags_empty_list(self):
        code = _AIRFLOW._generate_dag_definition(_base_config())
        assert "tags=[]" in code

    def test_dag_definition_tags_rendered(self):
        cfg = _base_config(tags=["etl", "daily"])
        code = _AIRFLOW._generate_dag_definition(cfg)
        assert "tags=['etl', 'daily']" in code

    def test_default_args_owner_and_retries(self):
        code = _AIRFLOW._generate_default_args(_base_config())
        assert "'owner': 'data-team'" in code
        assert "'retries': 2" in code
        assert "'retry_delay': timedelta(minutes=5)" in code
        assert "'depends_on_past': False" in code
        assert "'email_on_failure': True" in code

    def test_default_args_honors_config_owner(self):
        cfg = _base_config(owner="ops")
        code = _AIRFLOW._generate_default_args(cfg)
        assert "'owner': 'ops'" in code

    def test_header_contains_docstring_and_dag_import(self):
        code = _AIRFLOW._generate_header(_AIRFLOW._collect_imports(_base_config()))
        assert "Auto-generated Airflow DAG" in code
        assert "from airflow import DAG" in code


# ── AirflowGenerator: dependencies ──────────────────────────


class TestAirflowDependencies:
    def test_dependency_line_format(self):
        deps = _AIRFLOW._generate_dependencies(_base_config())
        assert "    extract_data >> load_data" in deps

    def test_dependencies_header_always_present(self):
        deps = _AIRFLOW._generate_dependencies(_base_config())
        assert "# Task dependencies" in deps

    def test_multiple_dependencies_all_rendered(self):
        cfg = _base_config(tasks=[
            PO.TaskConfig(task_id="a", operator="python_operator"),
            PO.TaskConfig(task_id="c", operator="python_operator",
                          dependencies=["a", "b"])])
        deps = _AIRFLOW._generate_dependencies(cfg)
        assert "    a >> c" in deps
        assert "    b >> c" in deps

    def test_no_dependencies_no_arrow(self):
        cfg = _base_config(tasks=[
            PO.TaskConfig(task_id="solo", operator="python_operator")])
        deps = _AIRFLOW._generate_dependencies(cfg)
        assert ">>" not in deps


# ── AirflowGenerator: full generate ─────────────────────────


class TestAirflowGenerate:
    def test_generate_contains_header_and_dag(self):
        code = _AIRFLOW.generate(_base_config())
        assert "Auto-generated Airflow DAG" in code
        assert "with DAG(" in code
        assert "default_args = {" in code

    def test_generate_includes_all_task_bodies(self):
        code = _AIRFLOW.generate(_base_config())
        assert "extract_data = PythonOperator(" in code
        assert "def extract(**kwargs):" in code
        assert "load_data = PythonOperator(" in code
        assert "def load(**kwargs):" in code

    def test_generate_includes_dependency_arrow(self):
        code = _AIRFLOW.generate(_base_config())
        assert "extract_data >> load_data" in code

    def test_generate_compiles(self):
        code = _AIRFLOW.generate(_base_config())
        compile(code, "<gen>", "exec")

    def test_generate_without_source(self):
        cfg = _base_config(source=None, destination=None)
        code = _AIRFLOW.generate(cfg)
        assert "with DAG(" in code
        assert "PythonOperator(" in code

    def test_generate_uses_config_name_for_dag_id(self):
        cfg = _base_config(name="custom-name")
        code = _AIRFLOW.generate(cfg)
        assert "dag_id='custom-name'" in code

    def test_generate_uses_config_schedule(self):
        cfg = _base_config(schedule="@hourly")
        code = _AIRFLOW.generate(cfg)
        assert "schedule_interval='@hourly'" in code


# ── AirflowGenerator: validate ──────────────────────────────


class TestAirflowValidate:
    def test_valid_dag_passes(self):
        code = _AIRFLOW.generate(_base_config())
        result = _AIRFLOW.validate(code)
        assert result["valid"] is True
        assert result["issues"] == []

    def test_missing_default_args_is_issue(self):
        result = _AIRFLOW.validate("with DAG() as dag:\n    pass")
        assert result["valid"] is False
        assert any("default_args" in i for i in result["issues"])

    def test_missing_dag_context_is_issue(self):
        result = _AIRFLOW.validate("default_args = {}")
        assert result["valid"] is False
        assert any("DAG context manager" in i for i in result["issues"])

    def test_missing_schedule_interval_is_warning(self):
        result = _AIRFLOW.validate("default_args = {}\nwith DAG() as dag:\n    pass")
        assert result["warnings"]
        assert any("schedule_interval" in w for w in result["warnings"])

    def test_syntax_error_reported(self):
        result = _AIRFLOW.validate("default_args = {}\nwith DAG(\n")
        assert result["valid"] is False
        assert any("Syntax error" in i for i in result["issues"])

    def test_validate_returns_dict_keys(self):
        result = _AIRFLOW.validate(_AIRFLOW.generate(_base_config()))
        assert sorted(result.keys()) == ["issues", "valid", "warnings"]

    def test_empty_tasks_dag_fails_compile_quirk(self):
        """Quirk: an AirflowGenerator.generate() with an empty tasks list
        produces a ``with DAG(...) as dag:`` block whose body is only a
        comment, so compile() raises SyntaxError."""
        cfg = _base_config(tasks=[])
        code = _AIRFLOW.generate(cfg)
        result = _AIRFLOW.validate(code)
        assert result["valid"] is False
        assert any("Syntax error" in i for i in result["issues"])


# ── PrefectGenerator ─────────────────────────────────────────


class TestPrefectGenerate:
    def test_generate_contains_header(self):
        code = _PREFECT.generate(_base_config())
        assert "Auto-generated Prefect Flow" in code
        assert "from prefect import flow, task, get_run_logger" in code

    def test_flow_name_replaces_dashes(self):
        code = _PREFECT.generate(_base_config())
        assert "def etl_dag_flow():" in code

    def test_flow_name_with_underscores_unchanged(self):
        cfg = _base_config(name="etl_dag")
        code = _PREFECT.generate(cfg)
        assert "def etl_dag_flow():" in code

    def test_task_decorator_name(self):
        code = _PREFECT.generate(_base_config())
        assert 'name="extract_data"' in code
        assert 'name="load_data"' in code

    def test_task_retries_and_retry_delay(self):
        code = _PREFECT.generate(_base_config())
        assert "retries=2" in code
        assert "retry_delay_seconds=300" in code

    def test_task_cache_expiration_default_hour(self):
        code = _PREFECT.generate(_base_config())
        assert "cache_expiration=timedelta(hours=1)" in code

    def test_task_function_signature(self):
        code = _PREFECT.generate(_base_config())
        assert "def extract_data(input_data=None):" in code
        assert "def load_data(input_data=None):" in code

    def test_flow_no_dependency_call(self):
        code = _PREFECT.generate(_base_config())
        assert "result_0 = extract_data()" in code

    def test_flow_dependency_call_uses_first_dep(self):
        code = _PREFECT.generate(_base_config())
        assert "result_1 = load_data(result_0)" in code

    def test_flow_main_guard(self):
        code = _PREFECT.generate(_base_config())
        assert 'if __name__ == "__main__":' in code
        assert "etl_dag_flow()" in code

    def test_generate_compiles(self):
        code = _PREFECT.generate(_base_config())
        compile(code, "<gen>", "exec")

    def test_custom_cache_hours(self):
        cfg = _base_config(tasks=[
            PO.TaskConfig(task_id="t", operator="python_operator",
                          params={"cache_hours": 72})])
        code = _PREFECT.generate(cfg)
        assert "cache_expiration=timedelta(hours=72)" in code

    def test_custom_retries_propagated(self):
        cfg = _base_config(tasks=[
            PO.TaskConfig(task_id="t", operator="python_operator", retries=5)])
        code = _PREFECT.generate(cfg)
        assert "retries=5" in code


class TestPrefectValidate:
    def test_valid_flow_passes(self):
        result = _PREFECT.validate(_PREFECT.generate(_base_config()))
        assert result["valid"] is True
        assert result["issues"] == []

    def test_missing_flow_decorator(self):
        result = _PREFECT.validate("def f(): pass")
        assert result["valid"] is False
        assert any("@flow" in i for i in result["issues"])

    def test_missing_task_decorator(self):
        result = _PREFECT.validate("@flow\ndef f(): pass")
        assert result["valid"] is False
        assert any("@task" in i for i in result["issues"])

    def test_syntax_error_reported(self):
        result = _PREFECT.validate("@flow\n(")
        assert result["valid"] is False
        assert any("Syntax error" in i for i in result["issues"])

    def test_validate_returns_dict_keys(self):
        result = _PREFECT.validate(_PREFECT.generate(_base_config()))
        assert sorted(result.keys()) == ["issues", "valid", "warnings"]


# ── DagsterGenerator ─────────────────────────────────────────


class TestDagsterGenerate:
    def test_generate_contains_header(self):
        code = _DAGSTER.generate(_base_config())
        assert "Auto-generated Dagster Job" in code
        assert "from dagster import op, job, In, Out, Output, DynamicOut, graph" in code

    def test_job_name_replaces_dashes(self):
        code = _DAGSTER.generate(_base_config())
        assert "def etl_dag_job():" in code

    def test_op_without_dependencies(self):
        code = _DAGSTER.generate(_base_config())
        assert "@op(out=Out())" in code
        assert "def extract_data(context):" in code

    def test_op_with_dependencies(self):
        code = _DAGSTER.generate(_base_config())
        assert "ins={\"input_data\": In()}" in code
        assert "out=Out()," in code
        assert "def load_data(context, input_data):" in code

    def test_op_with_deps_yields_asset_materialization_with_metadata(self):
        code = _DAGSTER.generate(_base_config())
        assert '"row_count": MetadataValue.int(' in code

    def test_op_without_deps_yields_asset_materialization(self):
        code = _DAGSTER.generate(_base_config())
        assert 'asset_key="extract_data"' in code
        assert 'asset_key="load_data"' in code

    def test_job_calls_no_dependency_op(self):
        code = _DAGSTER.generate(_base_config())
        assert "extract_data_output = extract_data()" in code

    def test_job_calls_dependency_op_with_output(self):
        code = _DAGSTER.generate(_base_config())
        assert "load_data_output = load_data(extract_data_output)" in code

    def test_generate_compiles(self):
        code = _DAGSTER.generate(_base_config())
        compile(code, "<gen>", "exec")

    def test_op_no_deps_result_is_empty_dict(self):
        cfg = _base_config(tasks=[
            PO.TaskConfig(task_id="solo", operator="python_operator")])
        code = _DAGSTER.generate(cfg)
        assert "result = {}" in code

    def test_op_with_deps_result_is_input_data(self):
        code = _DAGSTER.generate(_base_config())
        assert "result = input_data" in code


class TestDagsterValidate:
    def test_valid_job_passes(self):
        result = _DAGSTER.validate(_DAGSTER.generate(_base_config()))
        assert result["valid"] is True
        assert result["issues"] == []

    def test_missing_job_decorator(self):
        result = _DAGSTER.validate("def j(): pass")
        assert result["valid"] is False
        assert any("@job" in i for i in result["issues"])

    def test_missing_op_decorator(self):
        result = _DAGSTER.validate("@job\ndef j(): pass")
        assert result["valid"] is False
        assert any("@op" in i for i in result["issues"])

    def test_syntax_error_reported(self):
        result = _DAGSTER.validate("@job\n(")
        assert result["valid"] is False
        assert any("Syntax error" in i for i in result["issues"])

    def test_validate_returns_dict_keys(self):
        result = _DAGSTER.validate(_DAGSTER.generate(_base_config()))
        assert sorted(result.keys()) == ["issues", "valid", "warnings"]


# ── ETLPatternGenerator: extract-load ──────────────────────


class TestExtractLoad:
    def test_name_format(self):
        cfg = PO.ETLPatternGenerator.generate_extract_load("postgres", "snowflake", ["o"])
        assert cfg.name == "el_postgres_to_snowflake"

    def test_description_format(self):
        cfg = PO.ETLPatternGenerator.generate_extract_load("s3", "bigquery", ["o"])
        assert cfg.description == "Extract from s3, load to bigquery"

    def test_schedule_is_daily_5am(self):
        cfg = PO.ETLPatternGenerator.generate_extract_load("postgres", "snowflake", ["o"])
        assert cfg.schedule == "0 5 * * *"

    def test_tags_include_etl_source_dest(self):
        cfg = PO.ETLPatternGenerator.generate_extract_load("postgres", "snowflake", ["o"])
        assert cfg.tags == ["etl", "postgres", "snowflake"]

    def test_source_config(self):
        cfg = PO.ETLPatternGenerator.generate_extract_load("postgres", "snowflake", ["orders"])
        assert cfg.source.type == "postgres"
        assert cfg.source.connection_id == "postgres_default"
        assert cfg.source.tables == ["orders"]
        assert cfg.source.incremental_strategy == "timestamp"

    def test_source_incremental_strategy_for_full_mode(self):
        cfg = PO.ETLPatternGenerator.generate_extract_load("mysql", "bigquery", ["t"], mode="full")
        assert cfg.source.incremental_strategy == "full"

    def test_destination_config(self):
        cfg = PO.ETLPatternGenerator.generate_extract_load("postgres", "snowflake", ["orders"])
        assert cfg.destination.type == "snowflake"
        assert cfg.destination.connection_id == "snowflake_default"
        assert cfg.destination.schema == "raw"

    def test_destination_write_mode_incremental(self):
        cfg = PO.ETLPatternGenerator.generate_extract_load("postgres", "snowflake", ["o"], mode="incremental")
        assert cfg.destination.write_mode == "append"

    def test_destination_write_mode_full(self):
        cfg = PO.ETLPatternGenerator.generate_extract_load("postgres", "snowflake", ["o"], mode="full")
        assert cfg.destination.write_mode == "overwrite"

    def test_tasks_count_two_tables(self):
        cfg = PO.ETLPatternGenerator.generate_extract_load("postgres", "snowflake", ["orders", "customers"])
        assert len(cfg.tasks) == 5  # 2 extract + 2 load + 1 quality

    def test_extract_task_naming_and_callable(self):
        cfg = PO.ETLPatternGenerator.generate_extract_load("postgres", "snowflake", ["orders"])
        extract = cfg.tasks[0]
        assert extract.task_id == "extract_orders"
        assert extract.operator == "python_operator"
        assert extract.params["callable"] == "extract_orders"

    def test_extract_sql_incremental_contains_prev_ds(self):
        cfg = PO.ETLPatternGenerator.generate_extract_load("postgres", "snowflake", ["orders"])
        sql = cfg.tasks[0].params["sql"]
        assert "SELECT * FROM orders" in sql
        assert "prev_ds" in sql

    def test_extract_sql_full_no_where(self):
        cfg = PO.ETLPatternGenerator.generate_extract_load("postgres", "snowflake", ["orders"], mode="full")
        sql = cfg.tasks[0].params["sql"]
        assert sql == "SELECT * FROM orders"

    def test_load_task_dependency(self):
        cfg = PO.ETLPatternGenerator.generate_extract_load("postgres", "snowflake", ["orders"])
        load = [t for t in cfg.tasks if t.task_id == "load_orders"][0]
        assert load.dependencies == ["extract_orders"]
        assert load.params["callable"] == "load_orders"

    def test_quality_check_dependencies(self):
        cfg = PO.ETLPatternGenerator.generate_extract_load("postgres", "snowflake", ["orders", "customers"])
        qc = [t for t in cfg.tasks if t.task_id == "quality_check"][0]
        assert qc.dependencies == ["load_orders", "load_customers"]
        assert qc.params["callable"] == "run_quality_checks"

    def test_default_mode_is_incremental(self):
        cfg = PO.ETLPatternGenerator.generate_extract_load("postgres", "snowflake", ["o"])
        assert cfg.source.incremental_strategy == "timestamp"
        assert cfg.destination.write_mode == "append"

    def test_extract_tasks_first_then_loads(self):
        cfg = PO.ETLPatternGenerator.generate_extract_load("postgres", "snowflake", ["orders", "customers"])
        ids = [t.task_id for t in cfg.tasks]
        assert ids == ["extract_orders", "extract_customers", "load_orders", "load_customers", "quality_check"]


# ── ETLPatternGenerator: transform ─────────────────────────


class TestTransform:
    def test_name_format(self):
        cfg = PO.ETLPatternGenerator.generate_transform_pipeline(["o"], "fct_output", ["stg_*"])
        assert cfg.name == "transform_fct_output"

    def test_description_format(self):
        cfg = PO.ETLPatternGenerator.generate_transform_pipeline(["o"], "fct_output", ["stg_*"])
        assert cfg.description == "Transform data into fct_output using dbt"

    def test_schedule_is_daily_6am(self):
        cfg = PO.ETLPatternGenerator.generate_transform_pipeline(["o"], "fct_output", ["stg_*"])
        assert cfg.schedule == "0 6 * * *"

    def test_tags(self):
        cfg = PO.ETLPatternGenerator.generate_transform_pipeline(["o"], "fct_output", ["stg_*"])
        assert cfg.tags == ["transform", "dbt"]

    def test_sensor_tasks_for_each_source(self):
        cfg = PO.ETLPatternGenerator.generate_transform_pipeline(["orders", "users"], "fct_output", ["stg_*"])
        sensors = [t for t in cfg.tasks if t.task_id.startswith("wait_for_")]
        assert [t.task_id for t in sensors] == ["wait_for_orders", "wait_for_users"]
        for s in sensors:
            assert s.operator == "sql_sensor"
            assert "prev_ds" not in s.params["sql"]  # uses {{ ds }}

    def test_sensor_sql_uses_ds_template(self):
        cfg = PO.ETLPatternGenerator.generate_transform_pipeline(["orders"], "fct", ["m"])
        sql = [t for t in cfg.tasks if t.task_id == "wait_for_orders"][0].params["sql"]
        assert "SELECT MAX(updated_at) FROM orders" in sql
        assert "ds" in sql

    def test_dbt_run_task(self):
        cfg = PO.ETLPatternGenerator.generate_transform_pipeline(["a", "b"], "fct", ["stg_*", "fct_*"])
        dbt_run = [t for t in cfg.tasks if t.task_id == "dbt_run"][0]
        assert dbt_run.operator == "bash_operator"
        assert dbt_run.dependencies == ["wait_for_a", "wait_for_b"]
        assert dbt_run.timeout_minutes == 120
        assert "dbt run --select stg_* fct_*" in dbt_run.params["command"]

    def test_dbt_test_task(self):
        cfg = PO.ETLPatternGenerator.generate_transform_pipeline(["a"], "fct", ["stg_*"])
        dbt_test = [t for t in cfg.tasks if t.task_id == "dbt_test"][0]
        assert dbt_test.operator == "bash_operator"
        assert dbt_test.dependencies == ["dbt_run"]
        assert "dbt test --select stg_*" in dbt_test.params["command"]

    def test_task_order(self):
        cfg = PO.ETLPatternGenerator.generate_transform_pipeline(["a", "b"], "fct", ["m"])
        ids = [t.task_id for t in cfg.tasks]
        assert ids == ["wait_for_a", "wait_for_b", "dbt_run", "dbt_test"]

    def test_no_source_or_destination(self):
        cfg = PO.ETLPatternGenerator.generate_transform_pipeline(["o"], "fct", ["m"])
        assert cfg.source is None
        assert cfg.destination is None


# ── CLI ────────────────────────────────────────────────────


class TestCli:
    def test_no_command_exits_1(self):
        status, code, _ = _run_main(["pipeline_orchestrator.py"])
        assert status == "exit"
        assert code == 1

    def test_no_command_prints_help(self):
        _, _, out = _run_main(["pipeline_orchestrator.py"])
        assert "usage" in out.lower()

    def test_generate_invalid_type_exits_2(self):
        status, code, _ = _run_main(["pipeline_orchestrator.py", "generate", "--type", "invalid"])
        assert status == "exit"
        assert code == 2

    def test_generate_missing_type_exits_2(self):
        status, code, _ = _run_main(["pipeline_orchestrator.py", "generate"])
        assert status == "exit"
        assert code == 2

    def test_generate_airflow_stdout(self):
        out = _capture_main(["pipeline_orchestrator.py", "generate", "--type", "airflow",
                             "--source", "postgres", "--destination", "snowflake",
                             "--tables", "orders,customers"])
        assert "with DAG(" in out
        assert "dag_id='el_postgres_to_snowflake'" in out
        assert "default_args" in out

    def test_generate_prefect_stdout(self):
        out = _capture_main(["pipeline_orchestrator.py", "generate", "--type", "prefect",
                             "--source", "s3", "--destination", "bigquery",
                             "--tables", "t1"])
        assert "@flow" in out
        assert "@task" in out

    def test_generate_dagster_stdout(self):
        out = _capture_main(["pipeline_orchestrator.py", "generate", "--type", "dagster",
                             "--source", "postgres", "--destination", "redshift",
                             "--tables", "t1,t2"])
        assert "@job" in out
        assert "@op" in out

    def test_generate_defaults_to_postgres_snowflake(self):
        out = _capture_main(["pipeline_orchestrator.py", "generate", "--type", "airflow"])
        assert "dag_id='el_postgres_to_snowflake'" in out
        assert "default_args" in out

    def test_generate_name_override(self):
        out = _capture_main(["pipeline_orchestrator.py", "generate", "--type", "airflow",
                             "--source", "postgres", "--destination", "snowflake",
                             "--tables", "orders", "--name", "custom-name"])
        assert "dag_id='custom-name'" in out

    def test_generate_schedule_override(self):
        out = _capture_main(["pipeline_orchestrator.py", "generate", "--type", "airflow",
                             "--source", "postgres", "--destination", "snowflake",
                             "--tables", "orders", "--schedule", "@hourly"])
        assert "schedule_interval='@hourly'" in out

    def test_generate_mode_full(self):
        out = _capture_main(["pipeline_orchestrator.py", "generate", "--type", "airflow",
                             "--source", "postgres", "--destination", "snowflake",
                             "--tables", "orders", "--mode", "full"])
        assert "with DAG(" in out

    def test_generate_output_to_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "dag.py"
            status, code, out = _run_main(["pipeline_orchestrator.py", "generate", "--type", "airflow",
                                           "--source", "postgres", "--destination", "snowflake",
                                           "--tables", "orders", "--output", str(out_path)])
            assert status == "exit" and code == 0
            assert out == ""
            assert out_path.exists()
            assert "with DAG(" in out_path.read_text()

    def test_generate_output_to_file_uses_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "flow.py"
            _run_main(["pipeline_orchestrator.py", "generate", "--type", "prefect",
                       "--source", "postgres", "--destination", "snowflake",
                       "--tables", "orders", "--name", "nightly", "--output", str(out_path)])
            assert "def nightly_flow():" in out_path.read_text()

    def test_generate_config_yaml_scalar_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _write_yaml(Path(tmp), "cfg.yaml",
                                   {"name": "from-yaml", "description": "d",
                                    "schedule": "@daily"})
            out = _capture_main(["pipeline_orchestrator.py", "generate", "--type", "airflow",
                                 "--config", str(cfg_path)])
            assert "dag_id='from-yaml'" in out

    def test_generate_config_nested_dicts_fail_quirk(self):
        """Quirk: --config does not reconstruct nested dataclasses
        (source/destination/tasks arrive as plain dicts), so a config
        containing them raises ``'dict' object has no attribute 'operator'``
        and the CLI exits 1. Only scalar-only configs are supported."""
        data = {"name": "nested", "description": "d", "schedule": "@daily",
                "source": {"type": "postgres", "connection_id": "c"},
                "destination": {"type": "snowflake", "connection_id": "c"},
                "tasks": [{"task_id": "t", "operator": "python_operator"}]}
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = _write_json(Path(tmp), "cfg.json", data)
            status, code, _ = _run_main(["pipeline_orchestrator.py", "generate", "--type", "airflow",
                                         "--config", str(cfg_path)])
            assert status == "exit"
            assert code == 1

    def test_validate_good_dag_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            dag_path = Path(tmp) / "dag.py"
            _run_main(["pipeline_orchestrator.py", "generate", "--type", "airflow",
                       "--source", "postgres", "--destination", "snowflake",
                       "--tables", "orders", "--output", str(dag_path)])
            status, code, out = _run_main(["pipeline_orchestrator.py", "validate",
                                           "--dag", str(dag_path), "--type", "airflow"])
            assert status == "exit" and code == 0
            result = json.loads(out)
            assert result["valid"] is True
            assert sorted(result.keys()) == ["issues", "valid", "warnings"]

    def test_validate_bad_dag_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad_path = Path(tmp) / "bad.py"
            bad_path.write_text("print('no dag')")
            status, code, out = _run_main(["pipeline_orchestrator.py", "validate",
                                           "--dag", str(bad_path), "--type", "airflow"])
            assert status == "exit" and code == 1
            result = json.loads(out)
            assert result["valid"] is False
            assert any("DAG context manager" in i for i in result["issues"])

    def test_validate_missing_dag_exits_2(self):
        status, code, _ = _run_main(["pipeline_orchestrator.py", "validate", "--type", "airflow"])
        assert status == "exit" and code == 2

    def test_validate_missing_type_exits_2(self):
        status, code, _ = _run_main(["pipeline_orchestrator.py", "validate", "--dag", "x"])
        assert status == "exit" and code == 2

    def test_validate_prefect_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "f.py"
            _run_main(["pipeline_orchestrator.py", "generate", "--type", "prefect",
                       "--source", "postgres", "--destination", "snowflake",
                       "--tables", "orders", "--output", str(f)])
            status, code, out = _run_main(["pipeline_orchestrator.py", "validate",
                                           "--dag", str(f), "--type", "prefect"])
            assert status == "exit" and code == 0
            assert json.loads(out)["valid"] is True

    def test_validate_dagster_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "f.py"
            _run_main(["pipeline_orchestrator.py", "generate", "--type", "dagster",
                       "--source", "postgres", "--destination", "snowflake",
                       "--tables", "orders", "--output", str(f)])
            status, code, out = _run_main(["pipeline_orchestrator.py", "validate",
                                           "--dag", str(f), "--type", "dagster"])
            assert status == "exit" and code == 0
            assert json.loads(out)["valid"] is True

    def test_template_extract_load(self):
        out = _capture_main(["pipeline_orchestrator.py", "template", "--pattern", "extract-load",
                             "--type", "airflow", "--source", "postgres",
                             "--destination", "snowflake", "--tables", "orders"])
        assert "with DAG(" in out
        assert "dag_id='el_postgres_to_snowflake'" in out

    def test_template_transform(self):
        out = _capture_main(["pipeline_orchestrator.py", "template", "--pattern", "transform",
                             "--type", "prefect", "--source", "postgres",
                             "--destination", "bigquery", "--tables", "orders"])
        assert "@flow" in out

    def test_template_cdc_not_implemented_exits_1(self):
        status, code, _ = _run_main(["pipeline_orchestrator.py", "template", "--pattern", "cdc",
                                     "--type", "airflow", "--source", "postgres",
                                     "--destination", "snowflake", "--tables", "orders"])
        assert status == "exit" and code == 1

    def test_template_missing_required_args_exits_2(self):
        status, code, _ = _run_main(["pipeline_orchestrator.py", "template", "--pattern", "transform",
                                     "--type", "prefect"])
        assert status == "exit" and code == 2

    def test_template_output_to_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "j.py"
            _run_main(["pipeline_orchestrator.py", "template", "--pattern", "transform",
                       "--type", "dagster", "--source", "postgres",
                       "--destination", "bigquery", "--tables", "orders", "--output", str(out_path)])
            assert "@job" in out_path.read_text()

    def test_template_extract_load_uses_tables(self):
        out = _capture_main(["pipeline_orchestrator.py", "template", "--pattern", "extract-load",
                             "--type", "airflow", "--source", "postgres",
                             "--destination", "snowflake", "--tables", "orders,customers"])
        assert "extract_orders" in out
        assert "extract_customers" in out
        assert "quality_check" in out

    def test_template_transform_dbt_ops(self):
        out = _capture_main(["pipeline_orchestrator.py", "template", "--pattern", "transform",
                             "--type", "dagster", "--source", "postgres",
                             "--destination", "bigquery", "--tables", "orders"])
        assert "def dbt_run(context, input_data):" in out
        assert "def dbt_test(context, input_data):" in out
        assert "@job" in out

    def test_generate_invalid_command_exits_2(self):
        # 'generate' accepts only airflow/prefect/dagster; unknown subcommand is 2
        status, code, _ = _run_main(["pipeline_orchestrator.py", "frobnicate", "--type", "airflow"])
        assert status == "exit" and code == 2


# ── Test runner ────────────────────────────────────────────


def main() -> int:
    classes = [
        TestDataclasses,
        TestAbstractBaseClass,
        TestAirflowImports,
        TestAirflowTasks,
        TestAirflowDefinitions,
        TestAirflowDependencies,
        TestAirflowGenerate,
        TestAirflowValidate,
        TestPrefectGenerate,
        TestPrefectValidate,
        TestDagsterGenerate,
        TestDagsterValidate,
        TestExtractLoad,
        TestTransform,
        TestCli,
    ]
    total = 0
    passed = 0
    failures = []
    for cls in classes:
        for name in sorted(dir(cls)):
            if not name.startswith("test_"):
                continue
            total += 1
            try:
                getattr(cls(), name)()
                passed += 1
            except Exception as e:  # noqa: BLE001
                failures.append(f"{cls.__name__}.{name}: {e!r}")
    print(f"{passed}/{total} tests passed")
    for f in failures:
        print("FAIL", f)
    return 0 if not failures else 1


if __name__ == "__main__":
    import sys as _sys

    _sys.exit(main())
