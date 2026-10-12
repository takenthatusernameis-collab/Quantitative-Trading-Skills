#!/usr/bin/env python3
"""Unit tests for etl_performance_optimizer.py (ETL performance analysis)."""

import contextlib
import io
import json
import logging
import math
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

import etl_performance_optimizer as EPO  # noqa: E402
from etl_performance_optimizer import main as epo_main  # noqa: E402  (alias to avoid shadowing)


# ── Helpers ──────────────────────────────────────────────────


class _ListHandler(logging.Handler):
    """Logging handler that collects records for assertions."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _write_json(tmpdir: Path, name: str, obj) -> Path:
    """Write a JSON file and return its path."""
    path = tmpdir / name
    path.write_text(json.dumps(obj))
    return path


def _run_main(argv: list):
    """Run the script's main() with a patched argv; return ("exit", code) or ("ok", None)."""
    old = sys.argv
    sys.argv = argv
    try:
        try:
            epo_main()
        except SystemExit as e:
            return ("exit", e.code)
        return ("ok", None)
    finally:
        sys.argv = old


def _capture_stdout(func, *args, **kwargs):
    """Run func with stdout captured; return the captured text."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        func(*args, **kwargs)
    return buf.getvalue()


def epo_main_wrapper(argv):
    """Run the real main() with a patched argv (raises SystemExit)."""
    old = sys.argv
    sys.argv = argv
    try:
        epo_main()
    finally:
        sys.argv = old


def _metrics(**overrides) -> EPO.SparkJobMetrics:
    """Build a clean SparkJobMetrics (no recommendations) with optional overrides."""
    base = dict(
        job_id="job_clean",
        duration_ms=100000,
        stages=5,
        tasks=200,
        shuffle_read_bytes=1_000_000,
        shuffle_write_bytes=1_000_000,
        input_bytes=1_000_000_000,
        output_bytes=1_000_000,
        peak_memory_bytes=1_000_000_000,
        gc_time_ms=1000,
        failed_tasks=0,
        speculative_tasks=0,
        skew_ratio=1.0,
    )
    base.update(overrides)
    return EPO.SparkJobMetrics(**base)


def _query_info(**overrides) -> EPO.SQLQueryInfo:
    """Build a minimal SQLQueryInfo (SELECT with one filtered table)."""
    base = dict(
        query_type="SELECT",
        tables=["t"],
        columns=["id"],
        joins=[],
        where_conditions=["id = 1"],
        group_by=[],
        order_by=[],
        aggregations=[],
        subqueries=0,
        distinct=False,
        limit=None,
        ctes=[],
        window_functions=[],
        estimated_complexity="low",
    )
    base.update(overrides)
    return EPO.SQLQueryInfo(**base)


# Shared collaborators (the custom runner instantiates test classes
# without invoking pytest-style setup_method, so fixtures are singletons)
_PARSER = EPO.SQLParser()
_OPTIMIZER = EPO.SQLOptimizer()
_SPARK_ANALYZER = EPO.SparkJobAnalyzer()
_PARTITION_ADVISOR = EPO.PartitionAdvisor()
_COST_ESTIMATOR = EPO.CostEstimator()
_REPORT_GENERATOR = EPO.ReportGenerator()


# ── Dataclasses ──────────────────────────────────────────────


class TestDataclasses:
    def test_sql_query_info_fields(self):
        info = _query_info()
        assert info.query_type == "SELECT"
        assert info.tables == ["t"]
        assert info.columns == ["id"]
        assert info.joins == []
        assert info.where_conditions == ["id = 1"]
        assert info.group_by == []
        assert info.order_by == []
        assert info.aggregations == []
        assert info.subqueries == 0
        assert info.distinct is False
        assert info.limit is None
        assert info.ctes == []
        assert info.window_functions == []
        assert info.estimated_complexity == "low"

    def test_sql_query_info_asdict(self):
        d = asdict(_query_info())
        assert sorted(d.keys()) == [
            "aggregations", "columns", "ctes", "distinct",
            "estimated_complexity", "group_by", "joins", "limit",
            "order_by", "query_type", "subqueries", "tables",
            "where_conditions", "window_functions",
        ]

    def test_optimization_recommendation_default_priority(self):
        r = EPO.OptimizationRecommendation(
            "index", "medium", "Title", "desc", "issue",
            "rec", "improvement", "impl")
        assert r.priority == 1

    def test_optimization_recommendation_explicit_priority(self):
        r = EPO.OptimizationRecommendation(
            "index", "medium", "Title", "desc", "issue",
            "rec", "improvement", "impl", priority=7)
        assert r.priority == 7

    def test_optimization_recommendation_asdict(self):
        r = EPO.OptimizationRecommendation(
            "index", "medium", "Title", "desc", "issue",
            "rec", "improvement", "impl")
        d = asdict(r)
        assert sorted(d.keys()) == [
            "category", "current_issue", "description",
            "expected_improvement", "implementation", "priority",
            "recommendation", "severity", "title",
        ]

    def test_spark_job_metrics_fields(self):
        m = _metrics()
        assert m.job_id == "job_clean"
        assert m.duration_ms == 100000
        assert m.stages == 5
        assert m.tasks == 200
        assert m.shuffle_read_bytes == 1_000_000
        assert m.shuffle_write_bytes == 1_000_000
        assert m.input_bytes == 1_000_000_000
        assert m.output_bytes == 1_000_000
        assert m.peak_memory_bytes == 1_000_000_000
        assert m.gc_time_ms == 1000
        assert m.failed_tasks == 0
        assert m.speculative_tasks == 0
        assert m.skew_ratio == 1.0

    def test_spark_job_metrics_asdict(self):
        d = asdict(_metrics())
        assert sorted(d.keys()) == [
            "duration_ms", "failed_tasks", "gc_time_ms", "input_bytes",
            "job_id", "output_bytes", "peak_memory_bytes",
            "shuffle_read_bytes", "shuffle_write_bytes", "skew_ratio",
            "speculative_tasks", "stages", "tasks",
        ]

    def test_partition_strategy_fields(self):
        s = EPO.PartitionStrategy(
            "created_at", "range", None, 1.5, "reason", "impl")
        assert s.column == "created_at"
        assert s.partition_type == "range"
        assert s.num_partitions is None
        assert s.partition_size_mb == 1.5
        assert s.reasoning == "reason"
        assert s.implementation == "impl"

    def test_cost_estimate_defaults(self):
        c = EPO.CostEstimate("BigQuery", 1.0, 2.0, 3.0, 6.0)
        assert c.warehouse == "BigQuery"
        assert c.compute_cost == 1.0
        assert c.storage_cost == 2.0
        assert c.data_transfer_cost == 3.0
        assert c.total_cost == 6.0
        assert c.currency == "USD"
        assert c.assumptions == []

    def test_cost_estimate_asdict(self):
        c = EPO.CostEstimate("BigQuery", 1.0, 0.0, 0.0, 1.0)
        d = asdict(c)
        assert sorted(d.keys()) == [
            "assumptions", "compute_cost", "currency",
            "data_transfer_cost", "storage_cost", "total_cost",
            "warehouse",
        ]


# ── SQLParser: cleaning and query type ───────────────────────


class TestSQLParserCleaning:
    def test_clean_sql_removes_line_comments(self):
        assert _PARSER._clean_sql("SELECT 1 -- trailing\nFROM t") == "SELECT 1 FROM t"

    def test_clean_sql_removes_block_comments(self):
        assert _PARSER._clean_sql("SELECT /* block */ 1") == "SELECT 1"

    def test_clean_sql_normalizes_whitespace(self):
        assert _PARSER._clean_sql("SELECT   id\n  FROM\t\tt") == "SELECT id FROM t"

    def test_detect_type_select(self):
        assert _PARSER._detect_query_type("SELECT * FROM t") == "SELECT"

    def test_detect_type_with_cte_is_select(self):
        assert _PARSER._detect_query_type("WITH c AS (SELECT 1) SELECT * FROM c") == "SELECT"

    def test_detect_type_insert(self):
        assert _PARSER._detect_query_type("INSERT INTO t VALUES (1)") == "INSERT"

    def test_detect_type_update(self):
        assert _PARSER._detect_query_type("UPDATE t SET x = 1") == "UPDATE"

    def test_detect_type_delete(self):
        assert _PARSER._detect_query_type("DELETE FROM t WHERE x = 1") == "DELETE"

    def test_detect_type_merge(self):
        assert _PARSER._detect_query_type("MERGE INTO t USING s ON t.id = s.id") == "MERGE"

    def test_detect_type_create(self):
        assert _PARSER._detect_query_type("CREATE TABLE t (id INT)") == "CREATE"

    def test_detect_type_create_view(self):
        assert _PARSER._detect_query_type("CREATE VIEW v AS SELECT * FROM t") == "CREATE"

    def test_detect_type_create_index(self):
        assert _PARSER._detect_query_type("CREATE INDEX idx ON t (c)") == "CREATE"

    def test_detect_type_unknown(self):
        assert _PARSER._detect_query_type("EXPLAIN SELECT 1") == "UNKNOWN"

    def test_parse_comment_query(self):
        info = _PARSER.parse("-- comment\nSELECT id FROM t /* block */ WHERE x = 1")
        assert info.tables == ["t"]
        assert info.where_conditions == ["x = 1"]


# ── SQLParser: SELECT clause ─────────────────────────────────


class TestSQLParserSelect:
    def test_simple_select(self):
        info = _PARSER.parse("SELECT id, name FROM users WHERE age > 18")
        assert info.query_type == "SELECT"
        assert info.tables == ["users"]
        assert info.columns == ["id", "name"]
        assert info.where_conditions == ["age > 18"]

    def test_select_star(self):
        info = _PARSER.parse("SELECT * FROM orders")
        assert info.columns == ["*"]

    def test_count_star_not_treated_as_star(self):
        info = _PARSER.parse("SELECT COUNT(*), id FROM t")
        assert "*" not in info.columns
        assert "id" in info.columns

    def test_column_aliases(self):
        info = _PARSER.parse("SELECT a AS alpha, b FROM t")
        assert info.columns == ["alpha", "b"]

    def test_qualified_columns_lose_table_prefix(self):
        info = _PARSER.parse("SELECT t.col, u.col2 FROM t JOIN u ON t.id = u.id")
        assert info.columns == ["col", "col2"]

    def test_where_conditions_split_on_and(self):
        info = _PARSER.parse("SELECT * FROM t WHERE a = 1 AND b = 2")
        assert info.where_conditions == ["a = 1", "b = 2"]

    def test_where_conditions_split_on_or(self):
        info = _PARSER.parse("SELECT * FROM t WHERE a = 1 OR b = 2")
        assert info.where_conditions == ["a = 1", "b = 2"]

    def test_where_conditions_stop_at_group_by(self):
        info = _PARSER.parse("SELECT * FROM t WHERE a = 1 GROUP BY b ORDER BY c LIMIT 5")
        assert info.where_conditions == ["a = 1"]
        assert info.group_by == ["b"]
        assert info.order_by == ["c"]
        assert info.limit == 5

    def test_group_by_multiple_columns(self):
        info = _PARSER.parse("SELECT dept, COUNT(*) FROM emp GROUP BY dept, region")
        assert info.group_by == ["dept", "region"]

    def test_group_by_stops_at_having(self):
        info = _PARSER.parse(
            "SELECT COUNT(*), dept FROM emp GROUP BY dept HAVING COUNT(*) > 5")
        assert info.group_by == ["dept"]
        assert info.aggregations == ["COUNT"]

    def test_order_by_multiple_columns(self):
        info = _PARSER.parse("SELECT * FROM t ORDER BY a, b DESC")
        assert info.order_by == ["a", "b DESC"]

    def test_limit_parsed(self):
        info = _PARSER.parse("SELECT * FROM t LIMIT 10")
        assert info.limit == 10

    def test_no_limit_is_none(self):
        info = _PARSER.parse("SELECT * FROM t")
        assert info.limit is None

    def test_distinct_flag(self):
        info = _PARSER.parse("SELECT DISTINCT name FROM users")
        assert info.distinct is True

    def test_no_distinct_flag(self):
        info = _PARSER.parse("SELECT name FROM users")
        assert info.distinct is False

    def test_aggregations_detected(self):
        sql = "SELECT COUNT(*), SUM(x), AVG(y), MIN(z), MAX(w) FROM t"
        info = _PARSER.parse(sql)
        assert sorted(info.aggregations) == ["AVG", "COUNT", "MAX", "MIN", "SUM"]

    def test_aggregations_extended_functions(self):
        sql = "SELECT MEDIAN(x), PERCENTILE_CONT(y), PERCENTILE_DISC(z), " \
              "STDDEV(a), VARIANCE(b) FROM t"
        info = _PARSER.parse(sql)
        assert sorted(info.aggregations) == [
            "MEDIAN", "PERCENTILE_CONT", "PERCENTILE_DISC", "STDDEV", "VARIANCE"]

    def test_simple_select_is_low_complexity(self):
        info = _PARSER.parse("SELECT id FROM users WHERE age > 18")
        assert info.estimated_complexity == "low"


# ── SQLParser: tables for DML ────────────────────────────────


class TestSQLParserTables:
    def test_insert_tables(self):
        info = _PARSER.parse("INSERT INTO logs VALUES (1)")
        assert info.tables == ["logs"]

    def test_insert_schema_qualified_tables(self):
        info = _PARSER.parse("INSERT INTO analytics.logs SELECT * FROM staging.raw")
        assert sorted(info.tables) == ["analytics.logs", "staging.raw"]

    def test_update_tables(self):
        info = _PARSER.parse("UPDATE users SET x = 1 WHERE id = 2")
        assert info.tables == ["users"]

    def test_update_schema_qualified(self):
        info = _PARSER.parse("UPDATE analytics.users SET x = 1 WHERE id = 2")
        assert info.tables == ["analytics.users"]

    def test_delete_tables(self):
        info = _PARSER.parse("DELETE FROM users WHERE id = 3")
        assert info.tables == ["users"]

    def test_create_has_no_tables(self):
        info = _PARSER.parse("CREATE TABLE foo (id INT)")
        assert info.tables == []

    def test_merge_has_no_tables(self):
        info = _PARSER.parse("MERGE INTO t USING s ON t.id = s.id")
        assert info.tables == []

    def test_tables_are_deduplicated(self):
        info = _PARSER.parse("SELECT * FROM t JOIN t ON t.a = t.b WHERE t.x = 1")
        assert info.tables == ["t"]


# ── SQLParser: joins ─────────────────────────────────────────


class TestSQLParserJoins:
    def test_inner_join_with_alias_and_condition(self):
        sql = ("SELECT o.id, c.name FROM orders o "
               "INNER JOIN customers c ON o.customer_id = c.id "
               "WHERE o.total > 100")
        info = _PARSER.parse(sql)
        assert info.joins == [{
            "type": "INNER", "table": "customers", "alias": "c",
            "condition": "o.customer_id = c.id",
        }]

    def test_multiple_joins_extracted(self):
        sql = ("SELECT o.id FROM orders o "
               "INNER JOIN customers c ON o.customer_id = c.id "
               "LEFT OUTER JOIN items i ON o.id = i.order_id "
               "WHERE o.total > 100")
        info = _PARSER.parse(sql)
        assert len(info.joins) == 2
        assert info.joins[0]["table"] == "customers"
        assert info.joins[1]["type"] == "LEFT OUTER"
        assert info.joins[1]["table"] == "items"

    def test_bare_join_defaults_to_inner(self):
        info = _PARSER.parse("SELECT * FROM a JOIN b ON a.x = b.y WHERE a.id = 1")
        assert info.joins[0]["type"] == "INNER"

    def test_left_outer_join_type(self):
        info = _PARSER.parse("SELECT * FROM a LEFT OUTER JOIN b ON a.x = b.y WHERE a.id = 1")
        assert info.joins[0]["type"] == "LEFT OUTER"

    def test_cross_join_type(self):
        info = _PARSER.parse("SELECT * FROM a CROSS JOIN b WHERE a.x = 1")
        assert info.joins[0]["type"] == "CROSS"
        assert info.joins[0]["table"] == "b"
        assert info.joins[0]["condition"] is None

    def test_cross_join_increases_complexity(self):
        info = _PARSER.parse("SELECT * FROM a CROSS JOIN b WHERE a.x = 1")
        # 2 tables * 10 + CROSS 30 = 50 -> medium
        assert info.estimated_complexity == "medium"

    def test_left_outer_join_increases_complexity(self):
        info = _PARSER.parse("SELECT * FROM a LEFT OUTER JOIN b ON a.x = b.y WHERE a.id = 1")
        # 2 tables * 10 + LEFT OUTER 20 = 40 -> medium
        assert info.estimated_complexity == "medium"

    def test_join_without_condition(self):
        info = _PARSER.parse("SELECT * FROM a JOIN b WHERE a.x = 1")
        assert info.joins[0]["condition"] is None

    # Behavioral quirk: the join-type regex uses OUTER? which reads as
    # "OUTE" + optional "R", so unqualified "LEFT JOIN" / "RIGHT JOIN" /
    # "FULL JOIN" do not match the type alternation and fall back to INNER.
    # Only the fully spelled "LEFT OUTER JOIN" form is detected.
    def test_quirk_unqualified_left_join_parsed_as_inner(self):
        info = _PARSER.parse("SELECT * FROM a LEFT JOIN b ON a.x = b.y WHERE a.id = 1")
        assert info.joins[0]["type"] == "INNER"

    def test_quirk_unqualified_right_join_parsed_as_inner(self):
        info = _PARSER.parse("SELECT * FROM a RIGHT JOIN b ON a.x = b.y WHERE a.id = 1")
        assert info.joins[0]["type"] == "INNER"

    def test_quirk_unqualified_full_join_parsed_as_inner(self):
        info = _PARSER.parse("SELECT * FROM a FULL JOIN b ON a.x = b.y WHERE a.id = 1")
        assert info.joins[0]["type"] == "INNER"

    # Behavioral quirk: the join lookahead requires a following keyword
    # (INNER/LEFT/RIGHT/FULL/CROSS/WHERE/GROUP/ORDER/HAVING/LIMIT or a
    # whitespace-then-end), so a join that ends the query is not extracted.
    def test_quirk_join_at_end_of_string_not_extracted(self):
        info = _PARSER.parse("SELECT * FROM a JOIN b ON a.x = b.y")
        assert info.joins == []


# ── SQLParser: CTEs, subqueries, window functions ────────────


class TestSQLParserAdvanced:
    def test_single_cte(self):
        sql = "WITH cte1 AS (SELECT id FROM t1) SELECT * FROM cte1"
        info = _PARSER.parse(sql)
        assert info.ctes == ["cte1"]

    def test_multiple_ctes(self):
        sql = ("WITH c1 AS (SELECT id FROM t1), c2 AS (SELECT id FROM t2) "
               "SELECT * FROM c1 JOIN c2 ON c1.id = c2.id")
        info = _PARSER.parse(sql)
        assert info.ctes == ["c1", "c2"]

    def test_subquery_counted(self):
        sql = "SELECT * FROM t WHERE id IN (SELECT id FROM u)"
        info = _PARSER.parse(sql)
        assert info.subqueries == 1

    # Behavioral quirk: the subquery pattern counts every "(SELECT",
    # including CTE bodies, so a query with one CTE and one IN-subquery
    # reports two subqueries.
    def test_quirk_cte_body_counted_as_subquery(self):
        sql = ("WITH cte1 AS (SELECT id FROM t1) "
               "SELECT * FROM cte1 WHERE id IN (SELECT id FROM t2)")
        info = _PARSER.parse(sql)
        assert info.subqueries == 2

    def test_window_function_extracted(self):
        sql = "SELECT ROW_NUMBER() OVER (PARTITION BY y) AS rn FROM t"
        info = _PARSER.parse(sql)
        assert info.window_functions == ["ROW_NUMBER"]

    def test_multiple_window_functions(self):
        sql = ("SELECT ROW_NUMBER() OVER (PARTITION BY a), "
               "RANK() OVER (ORDER BY b) FROM t")
        info = _PARSER.parse(sql)
        assert sorted(info.window_functions) == ["RANK", "ROW_NUMBER"]

    # Behavioral quirk: the column extractor matches the first
    # "SELECT ... FROM" in the string, which for a CTE query is the CTE
    # body's SELECT, so the reported columns come from the CTE.
    def test_quirk_cte_select_defines_columns(self):
        sql = "WITH cte1 AS (SELECT id FROM t1) SELECT COUNT(*) FROM cte1"
        info = _PARSER.parse(sql)
        assert info.columns == ["id"]

    def test_complexity_very_high_with_subqueries(self):
        sql = ("WITH c1 AS (SELECT id FROM t1), c2 AS (SELECT id FROM t2) "
               "SELECT * FROM c1 JOIN c2 ON c1.id = c2.id "
               "WHERE id IN (SELECT id FROM t3) AND id IN (SELECT id FROM t4)")
        info = _PARSER.parse(sql)
        assert info.subqueries == 4
        assert info.estimated_complexity == "very_high"

    def test_complexity_medium_with_two_tables(self):
        info = _PARSER.parse("SELECT * FROM a JOIN b ON a.x = b.y WHERE a.id = 1")
        # 2 tables * 10 + INNER join 15 = 35 -> medium
        assert info.estimated_complexity == "medium"

    def test_complexity_high_with_window(self):
        sql = ("SELECT * FROM a JOIN b ON a.x = b.y WHERE a.id = 1 "
               "AND b.y = ROW_NUMBER() OVER (ORDER BY a.z)")
        info = _PARSER.parse(sql)
        assert info.window_functions == ["ROW_NUMBER"]
        # 2 tables * 10 + INNER join 15 + window 15 = 50 -> medium
        assert info.estimated_complexity == "medium"


# ── SQLOptimizer ─────────────────────────────────────────────


class TestSQLOptimizer:
    def test_clean_query_no_recommendations(self):
        info = _PARSER.parse("SELECT 1")
        assert _OPTIMIZER.analyze(info, "SELECT 1") == []

    def test_select_star_recommendation(self):
        sql = "SELECT * FROM orders WHERE id = 1"
        info = _PARSER.parse(sql)
        recs = _OPTIMIZER.analyze(info, sql)
        titles = [r.title for r in recs]
        assert "Avoid SELECT *" in titles
        rec = next(r for r in recs if r.title == "Avoid SELECT *")
        assert rec.category == "query_structure"
        assert rec.severity == "medium"
        assert rec.priority == 2

    def test_missing_where_recommendation(self):
        sql = "SELECT id FROM big_table"
        info = _PARSER.parse(sql)
        recs = _OPTIMIZER.analyze(info, sql)
        rec = next(r for r in recs if r.title == "Add WHERE Clause Filters")
        assert rec.category == "filter"
        assert rec.severity == "high"
        assert rec.priority == 1

    def test_missing_where_not_triggered_without_tables(self):
        info = _PARSER.parse("SELECT 1")
        recs = _OPTIMIZER.analyze(info, "SELECT 1")
        assert all(r.title != "Add WHERE Clause Filters" for r in recs)

    def test_cross_join_recommendations(self):
        sql = "SELECT * FROM a CROSS JOIN b WHERE a.x = 1"
        info = _PARSER.parse(sql)
        recs = _OPTIMIZER.analyze(info, sql)
        by_title = {r.title: r for r in recs}
        assert by_title["Avoid CROSS JOIN"].severity == "critical"
        assert by_title["Avoid CROSS JOIN"].priority == 1
        assert "b" in by_title["Avoid CROSS JOIN"].current_issue
        assert by_title["Missing Join Condition"].severity == "high"

    def test_missing_join_condition_recommendation(self):
        sql = "SELECT * FROM a JOIN b WHERE a.x = 1"
        info = _PARSER.parse(sql)
        recs = _OPTIMIZER.analyze(info, sql)
        rec = next(r for r in recs if r.title == "Missing Join Condition")
        assert rec.category == "join"
        assert rec.severity == "high"
        assert rec.priority == 1

    def test_join_with_condition_no_missing_condition_rec(self):
        sql = "SELECT id FROM a JOIN b ON a.x = b.y WHERE a.id = 1"
        info = _PARSER.parse(sql)
        recs = _OPTIMIZER.analyze(info, sql)
        assert all(r.title != "Missing Join Condition" for r in recs)

    def test_high_number_of_joins(self):
        sql = ("SELECT * FROM a "
               "INNER JOIN b ON a.x = b.x INNER JOIN c ON b.x = c.x "
               "INNER JOIN d ON c.x = d.x INNER JOIN e ON d.x = e.x "
               "INNER JOIN f ON e.x = f.x INNER JOIN g ON f.x = g.x "
               "WHERE a.id = 1")
        info = _PARSER.parse(sql)
        assert len(info.joins) == 6
        recs = _OPTIMIZER.analyze(info, sql)
        rec = next(r for r in recs if r.title == "High Number of Joins")
        assert rec.severity == "medium"
        assert rec.priority == 3
        assert "6 joins" in rec.current_issue

    def test_few_joins_no_high_number_rec(self):
        sql = "SELECT id FROM a JOIN b ON a.x = b.y WHERE a.id = 1"
        info = _PARSER.parse(sql)
        recs = _OPTIMIZER.analyze(info, sql)
        assert all(r.title != "High Number of Joins" for r in recs)

    def test_distinct_recommendation(self):
        sql = "SELECT DISTINCT name FROM users WHERE id = 1"
        info = _PARSER.parse(sql)
        recs = _OPTIMIZER.analyze(info, sql)
        rec = next(r for r in recs if r.title == "Consider Alternatives to DISTINCT")
        assert rec.category == "query_structure"
        assert rec.severity == "medium"
        assert rec.priority == 3

    def test_order_by_without_limit_recommendation(self):
        sql = "SELECT id FROM t WHERE x = 1 ORDER BY id"
        info = _PARSER.parse(sql)
        recs = _OPTIMIZER.analyze(info, sql)
        rec = next(r for r in recs if r.title == "Add LIMIT to ORDER BY")
        assert rec.category == "query_structure"
        assert rec.severity == "low"
        assert rec.priority == 4

    def test_order_by_with_limit_no_rec(self):
        sql = "SELECT id FROM t WHERE x = 1 ORDER BY id LIMIT 10"
        info = _PARSER.parse(sql)
        recs = _OPTIMIZER.analyze(info, sql)
        assert all(r.title != "Add LIMIT to ORDER BY" for r in recs)

    def test_subquery_cte_conversion_recommendation(self):
        sql = "SELECT id FROM t WHERE id IN (SELECT id FROM u) AND x = 1"
        info = _PARSER.parse(sql)
        assert info.subqueries == 1
        recs = _OPTIMIZER.analyze(info, sql)
        rec = next(r for r in recs if r.title == "Convert Subqueries to CTEs")
        assert rec.category == "query_structure"
        assert rec.severity == "medium"
        assert rec.priority == 3

    def test_date_filter_partition_pruning_recommendation(self):
        sql = "SELECT id FROM t WHERE created_at >= '2024-01-01'"
        info = _PARSER.parse(sql)
        recs = _OPTIMIZER.analyze(info, sql)
        rec = next(r for r in recs if r.title == "Leverage Partition Pruning")
        assert rec.category == "partition"
        assert rec.severity == "medium"
        assert rec.priority == 2

    def test_non_date_filter_no_partition_pruning_rec(self):
        sql = "SELECT id FROM t WHERE status = 'active'"
        info = _PARSER.parse(sql)
        recs = _OPTIMIZER.analyze(info, sql)
        assert all(r.title != "Leverage Partition Pruning" for r in recs)

    def test_where_columns_index_recommendation(self):
        sql = "SELECT id FROM t WHERE status = 'a' AND region = 'us'"
        info = _PARSER.parse(sql)
        recs = _OPTIMIZER.analyze(info, sql)
        rec = next(r for r in recs if r.title == "Consider Indexes on Filter Columns")
        assert rec.category == "index"
        assert rec.severity == "medium"
        assert "status" in rec.current_issue
        assert "region" in rec.current_issue

    def test_join_columns_index_recommendation(self):
        sql = "SELECT id FROM a JOIN b ON a.id = b.aid WHERE a.x = 1"
        info = _PARSER.parse(sql)
        recs = _OPTIMIZER.analyze(info, sql)
        rec = next(r for r in recs if r.title == "Index Join Columns")
        assert rec.category == "index"
        assert rec.severity == "high"
        assert rec.priority == 1
        assert "id" in rec.current_issue

    def test_high_cardinality_group_by_recommendation(self):
        sql = "SELECT COUNT(*), SUM(x) FROM t WHERE id = 1 GROUP BY a, b, c, d"
        info = _PARSER.parse(sql)
        assert info.group_by == ["a", "b", "c", "d"]
        recs = _OPTIMIZER.analyze(info, sql)
        rec = next(r for r in recs if r.title == "High Cardinality GROUP BY")
        assert rec.category == "aggregation"
        assert rec.severity == "medium"
        assert "4 columns" in rec.current_issue

    def test_low_cardinality_group_by_no_rec(self):
        sql = "SELECT COUNT(*) FROM t WHERE id = 1 GROUP BY a"
        info = _PARSER.parse(sql)
        recs = _OPTIMIZER.analyze(info, sql)
        assert all(r.title != "High Cardinality GROUP BY" for r in recs)

    def test_count_distinct_recommendation(self):
        sql = "SELECT COUNT(DISTINCT uid), x FROM t WHERE id = 1 GROUP BY x"
        info = _PARSER.parse(sql)
        assert info.aggregations == ["COUNT"]
        assert info.distinct is True
        recs = _OPTIMIZER.analyze(info, sql)
        rec = next(r for r in recs if r.title == "Optimize COUNT DISTINCT")
        assert rec.category == "aggregation"
        assert rec.severity == "medium"
        assert rec.priority == 3

    def test_aggregation_without_group_by_no_aggregation_recs(self):
        sql = "SELECT COUNT(*) FROM t WHERE id = 1"
        info = _PARSER.parse(sql)
        recs = _OPTIMIZER.analyze(info, sql)
        assert all(r.category != "aggregation" for r in recs)

    def test_recommendations_sorted_by_priority(self):
        sql = "SELECT * FROM a CROSS JOIN b WHERE a.x = 1"
        info = _PARSER.parse(sql)
        recs = _OPTIMIZER.analyze(info, sql)
        priorities = [r.priority for r in recs]
        assert priorities == sorted(priorities)


# ── SparkJobAnalyzer ─────────────────────────────────────────


class TestSparkJobAnalyzer:
    def test_clean_job_no_recommendations(self):
        assert _SPARK_ANALYZER.analyze(_metrics()) == []

    def test_severe_skew_recommendation(self):
        m = _metrics(skew_ratio=10.0)
        recs = _SPARK_ANALYZER.analyze(m)
        assert len(recs) == 1
        rec = recs[0]
        assert rec.title == "Severe Data Skew Detected"
        assert rec.category == "skew"
        assert rec.severity == "critical"
        assert rec.priority == 1
        assert "10.0x" in rec.description
        assert "10.0x" in rec.current_issue

    def test_mild_skew_no_recommendation(self):
        m = _metrics(skew_ratio=3.5)
        assert _SPARK_ANALYZER.analyze(m) == []

    def test_excessive_shuffle_recommendation(self):
        m = _metrics(shuffle_write_bytes=3_000_000_000)  # 3x input
        recs = _SPARK_ANALYZER.analyze(m)
        rec = next(r for r in recs if r.title == "Excessive Shuffle Data")
        assert rec.category == "shuffle"
        assert rec.severity == "high"
        assert rec.priority == 1
        assert "3.0x" in rec.description

    def test_low_shuffle_no_recommendation(self):
        m = _metrics(shuffle_write_bytes=1_000_000_000)  # 1x input
        recs = _SPARK_ANALYZER.analyze(m)
        assert all(r.title != "Excessive Shuffle Data" for r in recs)

    def test_gc_overhead_recommendation(self):
        m = _metrics(gc_time_ms=20000)  # 20% of 100s duration
        recs = _SPARK_ANALYZER.analyze(m)
        rec = next(r for r in recs if r.title == "High GC Overhead")
        assert rec.category == "memory"
        assert rec.severity == "high"
        assert rec.priority == 2
        assert "20.0%" in rec.description

    def test_low_gc_no_recommendation(self):
        m = _metrics(gc_time_ms=5000)  # 5% of duration
        recs = _SPARK_ANALYZER.analyze(m)
        assert all(r.title != "High GC Overhead" for r in recs)

    def test_task_failures_high_severity(self):
        m = _metrics(failed_tasks=50, tasks=200)  # 25% failure rate
        recs = _SPARK_ANALYZER.analyze(m)
        rec = next(r for r in recs if r.title == "Task Failures Detected")
        assert rec.category == "reliability"
        assert rec.severity == "high"
        assert rec.priority == 1
        assert "50 tasks failed" in rec.description
        assert "25.0%" in rec.description

    def test_task_failures_medium_severity(self):
        m = _metrics(failed_tasks=10, tasks=200)  # 5% failure rate
        recs = _SPARK_ANALYZER.analyze(m)
        rec = next(r for r in recs if r.title == "Task Failures Detected")
        assert rec.severity == "medium"

    def test_no_failures_no_recommendation(self):
        recs = _SPARK_ANALYZER.analyze(_metrics())
        assert all(r.title != "Task Failures Detected" for r in recs)

    def test_excessive_speculation_recommendation(self):
        m = _metrics(speculative_tasks=50, tasks=200)  # > 10% of tasks
        recs = _SPARK_ANALYZER.analyze(m)
        rec = next(r for r in recs if r.title == "High Speculative Execution")
        assert rec.category == "execution"
        assert rec.severity == "medium"
        assert rec.priority == 3
        assert "50 speculative tasks" in rec.description

    def test_low_speculation_no_recommendation(self):
        m = _metrics(speculative_tasks=5, tasks=200)  # 2.5% < 10%
        recs = _SPARK_ANALYZER.analyze(m)
        assert all(r.title != "High Speculative Execution" for r in recs)

    def test_too_many_tasks_recommendation(self):
        m = _metrics(tasks=20000)
        recs = _SPARK_ANALYZER.analyze(m)
        rec = next(r for r in recs if r.title == "Too Many Tasks")
        assert rec.category == "parallelism"
        assert rec.severity == "medium"
        assert "20000 tasks" in rec.description
        # implementation suggests max(200, tasks // 10) = 2000
        assert "2000" in rec.implementation

    def test_low_parallelism_recommendation(self):
        m = _metrics(tasks=5, input_bytes=2_000_000_000)  # < 10 tasks, > 1GB
        recs = _SPARK_ANALYZER.analyze(m)
        rec = next(r for r in recs if r.title == "Low Parallelism")
        assert rec.category == "parallelism"
        assert rec.severity == "high"
        assert rec.priority == 2
        assert "5 tasks" in rec.description

    def test_low_parallelism_partition_count_math(self):
        m = _metrics(tasks=5, input_bytes=50_000_000_000)  # 50 GB
        recs = _SPARK_ANALYZER.analyze(m)
        rec = next(r for r in recs if r.title == "Low Parallelism")
        # recommended_partitions = max(200, int(50e9 / (128 * 1e6))) = 390
        assert "390" in rec.implementation

    def test_adequate_parallelism_no_recommendation(self):
        m = _metrics(tasks=5, input_bytes=100_000_000)  # small data, few tasks
        recs = _SPARK_ANALYZER.analyze(m)
        assert all(r.title not in ("Low Parallelism", "Too Many Tasks") for r in recs)

    def test_multiple_issues_all_reported(self):
        m = _metrics(skew_ratio=10.0, shuffle_write_bytes=3_000_000_000,
                     gc_time_ms=20000, failed_tasks=50, speculative_tasks=50)
        recs = _SPARK_ANALYZER.analyze(m)
        titles = {r.title for r in recs}
        assert titles == {
            "Severe Data Skew Detected",
            "Excessive Shuffle Data",
            "High GC Overhead",
            "Task Failures Detected",
            "High Speculative Execution",
        }


# ── PartitionAdvisor ───────────────────────────────────────────


class TestPartitionAdvisor:
    def test_date_column_range_partition(self):
        stats = {"total_size_bytes": 365 * 1024 * 1024, "row_count": 100,
                 "columns": {"d": {"data_type": "date",
                                   "cardinality": 365, "null_percentage": 0}}}
        strategies = _PARTITION_ADVISOR.recommend(stats)
        assert len(strategies) == 1
        s = strategies[0]
        assert s.column == "d"
        assert s.partition_type == "range"
        assert s.num_partitions is None
        assert s.partition_size_mb == 1.0
        assert "range partitioning" in s.reasoning

    def test_timestamp_column_range_partition(self):
        stats = {"total_size_bytes": 365 * 1024 * 1024, "row_count": 100,
                 "columns": {"ts": {"data_type": "timestamp",
                                     "cardinality": 1000, "null_percentage": 0}}}
        strategies = _PARTITION_ADVISOR.recommend(stats)
        assert strategies[0].partition_type == "range"

    def test_low_cardinality_list_partition(self):
        stats = {"total_size_bytes": 10 * 1024 * 1024, "row_count": 100,
                 "columns": {"s": {"data_type": "string",
                                   "cardinality": 10, "null_percentage": 0}}}
        strategies = _PARTITION_ADVISOR.recommend(stats)
        s = strategies[0]
        assert s.partition_type == "list"
        assert s.num_partitions == 10
        assert s.partition_size_mb == 1.0

    def test_medium_cardinality_hash_partition(self):
        stats = {"total_size_bytes": 1024 * 1024 * 1024, "row_count": 100,
                 "columns": {"u": {"data_type": "integer",
                                   "cardinality": 5000, "null_percentage": 0}}}
        strategies = _PARTITION_ADVISOR.recommend(stats)
        s = strategies[0]
        assert s.partition_type == "hash"
        # 1GB / 128MB = 8 partitions (already a power of 2)
        assert s.num_partitions == 8
        assert s.partition_size_mb == 128.0

    def test_hash_partition_rounds_to_power_of_two(self):
        stats = {"total_size_bytes": 10 * 1024 * 1024 * 1024, "row_count": 100,
                 "columns": {"u": {"data_type": "integer",
                                   "cardinality": 5000, "null_percentage": 0}}}
        strategies = _PARTITION_ADVISOR.recommend(stats)
        s = strategies[0]
        # 10GB / 128MB = 80 -> 2^int(log2(80) + 0.5) = 2^6 = 64
        assert s.num_partitions == 64
        assert s.partition_size_mb == 160.0

    def test_high_cardinality_column_skipped(self):
        stats = {"total_size_bytes": 1_000_000_000, "row_count": 100,
                 "columns": {"u": {"data_type": "integer",
                                   "cardinality": 50000, "null_percentage": 0}}}
        assert _PARTITION_ADVISOR.recommend(stats) == []

    def test_high_null_column_skipped(self):
        stats = {"total_size_bytes": 1_000_000_000, "row_count": 100,
                 "columns": {"x": {"data_type": "string",
                                   "cardinality": 5, "null_percentage": 21}}}
        assert _PARTITION_ADVISOR.recommend(stats) == []

    def test_null_percentage_boundary_included(self):
        stats = {"total_size_bytes": 10 * 1024 * 1024, "row_count": 100,
                 "columns": {"x": {"data_type": "string",
                                   "cardinality": 5, "null_percentage": 20}}}
        strategies = _PARTITION_ADVISOR.recommend(stats)
        assert len(strategies) == 1

    def test_empty_stats_no_recommendations(self):
        assert _PARTITION_ADVISOR.recommend({}) == []

    def test_missing_column_stats_use_defaults(self):
        # cardinality defaults to 0 (falsy) so the column is skipped
        stats = {"columns": {"s": {}}}
        assert _PARTITION_ADVISOR.recommend(stats) == []

    def test_recommendations_sorted_by_partition_size(self):
        stats = {
            "total_size_bytes": 10 * 1024 * 1024 * 1024,
            "row_count": 1000000,
            "columns": {
                "created_at": {"data_type": "timestamp",
                               "cardinality": 100000, "null_percentage": 0},
                "user_id": {"data_type": "integer",
                            "cardinality": 5000, "null_percentage": 0},
                "region": {"data_type": "string",
                           "cardinality": 50, "null_percentage": 0},
            },
        }
        strategies = _PARTITION_ADVISOR.recommend(stats)
        sizes = [s.partition_size_mb for s in strategies]
        assert sizes == sorted(sizes)
        assert [s.column for s in strategies] == ["created_at", "user_id", "region"]

    def test_only_top_three_returned(self):
        columns = {}
        for i in range(6):
            columns[f"c{i}"] = {"data_type": "string",
                                "cardinality": 10, "null_percentage": 0}
        stats = {"total_size_bytes": 10 * 1024 * 1024, "row_count": 100,
                 "columns": columns}
        strategies = _PARTITION_ADVISOR.recommend(stats)
        assert len(strategies) == 3


# ── CostEstimator ──────────────────────────────────────────────


class TestCostEstimator:
    def test_bigquery_estimate(self):
        info = _PARSER.parse("SELECT * FROM t")
        cost = _COST_ESTIMATOR.estimate(info, "bigquery")
        assert cost.warehouse == "BigQuery"
        assert cost.storage_cost == 0
        assert cost.data_transfer_cost == 0
        assert cost.total_cost == cost.compute_cost
        assert cost.currency == "USD"
        # 1 table, no stats -> 1e9 bytes scanned, no filters, SELECT *
        expected = (1_000_000_000 / (1024 ** 4)) * 5.00
        assert math.isclose(cost.compute_cost, expected, rel_tol=1e-9)
        assert any("Using on-demand pricing" in a for a in cost.assumptions)

    def test_bigquery_minimum_billing(self):
        info = _PARSER.parse("SELECT 1")  # no tables -> 0 bytes scanned
        cost = _COST_ESTIMATOR.estimate(info, "bigquery")
        # Minimum billing of 10 MB
        expected = (10 / (1024 ** 2)) * 5.00
        assert math.isclose(cost.compute_cost, expected, rel_tol=1e-9)

    def test_snowflake_estimate_minimum_billing(self):
        info = _PARSER.parse("SELECT * FROM t")
        cost = _COST_ESTIMATOR.estimate(info, "snowflake")
        assert cost.warehouse == "Snowflake"
        assert cost.total_cost == cost.compute_cost
        # complexity low -> x-small (1 credit/hour); scan is tiny so the
        # 1-minute minimum applies: (1/60) * $2.00
        expected = (1 / 60) * 2.00
        assert math.isclose(cost.compute_cost, expected, rel_tol=1e-9)
        assert any("Warehouse size: x-small" in a for a in cost.assumptions)
        assert any("Minimum 1-minute billing" in a for a in cost.assumptions)

    def test_snowflake_with_stats_and_filters(self):
        info = _PARSER.parse("SELECT id FROM t WHERE x = 1 AND y = 2")
        cost = _COST_ESTIMATOR.estimate(info, "snowflake",
                                        {"total_size_bytes": 1_000_000_000_000})
        assert cost.warehouse == "Snowflake"
        # scanned = 1e12 * 0.5^2 * 0.5 = 1.25e11 bytes
        scanned_tb = 1.25e11 / (1024 ** 4)
        seconds = max(1, scanned_tb * 1024 * 10)
        hours = seconds / 3600
        credits = 1 * hours  # x-small
        expected = max(credits * 2.00, (1 / 60) * 2.00)
        assert math.isclose(cost.compute_cost, expected, rel_tol=1e-9)
        assert any("Estimated runtime: 1164.2 seconds" in a for a in cost.assumptions)

    def test_redshift_estimate(self):
        info = _PARSER.parse("SELECT * FROM t")
        cost = _COST_ESTIMATOR.estimate(info, "redshift")
        assert cost.warehouse == "Redshift"
        scanned_tb = 1_000_000_000 / (1024 ** 4)
        seconds = max(1, scanned_tb * 1024 * 15)
        expected = (seconds / 3600) * 1.086
        assert math.isclose(cost.compute_cost, expected, rel_tol=1e-9)
        assert any("RA3.xlplus" in a for a in cost.assumptions)

    def test_databricks_estimate(self):
        info = _PARSER.parse("SELECT * FROM t")
        cost = _COST_ESTIMATOR.estimate(info, "databricks")
        assert cost.warehouse == "Databricks"
        scanned_tb = 1_000_000_000 / (1024 ** 4)
        seconds = max(1, scanned_tb * 1024 * 12)
        expected = (seconds / 3600) * 0.22
        assert math.isclose(cost.compute_cost, expected, rel_tol=1e-9)
        assert any("SQL warehouse" in a for a in cost.assumptions)

    def test_unknown_warehouse_raises(self):
        info = _PARSER.parse("SELECT * FROM t")
        try:
            _COST_ESTIMATOR.estimate(info, "oracle")
        except ValueError as e:
            assert "Unknown warehouse: oracle" in str(e)
            assert "snowflake" in str(e)
            assert "bigquery" in str(e)
            assert "redshift" in str(e)
            assert "databricks" in str(e)
        else:
            raise AssertionError("expected ValueError")

    def test_warehouse_case_insensitive(self):
        info = _PARSER.parse("SELECT * FROM t")
        cost = _COST_ESTIMATOR.estimate(info, "SNOWFLAKE")
        assert cost.warehouse == "Snowflake"

    def test_estimate_data_scanned_defaults(self):
        info = _PARSER.parse("SELECT * FROM t")
        assert _COST_ESTIMATOR._estimate_data_scanned(info, None) == 1_000_000_000

    def test_estimate_data_scanned_multiple_tables(self):
        info = _PARSER.parse("SELECT * FROM t1 JOIN t2 ON t1.x = t2.x")
        assert _COST_ESTIMATOR._estimate_data_scanned(info, None) == 2_000_000_000

    def test_estimate_data_scanned_uses_stats(self):
        info = _PARSER.parse("SELECT * FROM t")
        assert _COST_ESTIMATOR._estimate_data_scanned(
            info, {"total_size_bytes": 1_000_000_000}) == 1_000_000_000

    def test_estimate_data_scanned_single_filter(self):
        info = _PARSER.parse("SELECT * FROM t WHERE a = 1")
        assert _COST_ESTIMATOR._estimate_data_scanned(
            info, {"total_size_bytes": 1_000_000_000}) == 500_000_000

    def test_estimate_data_scanned_filter_cap_at_three(self):
        info = _PARSER.parse("SELECT * FROM t WHERE a = 1 AND b = 2 AND c = 3 AND d = 4")
        assert _COST_ESTIMATOR._estimate_data_scanned(
            info, {"total_size_bytes": 1_000_000_000}) == 125_000_000

    def test_estimate_data_scanned_projection_discount(self):
        info = _PARSER.parse("SELECT a FROM t WHERE a = 1")
        assert _COST_ESTIMATOR._estimate_data_scanned(
            info, {"total_size_bytes": 1_000_000_000}) == 250_000_000

    def test_estimate_data_scanned_star_no_projection_discount(self):
        info = _PARSER.parse("SELECT * FROM t WHERE a = 1")
        assert _COST_ESTIMATOR._estimate_data_scanned(
            info, {"total_size_bytes": 1_000_000_000}) == 500_000_000


# ── ReportGenerator ──────────────────────────────────────────


class TestReportGenerator:
    def test_text_report_headers(self):
        info = _PARSER.parse("SELECT id FROM t WHERE x = 1")
        recs = _OPTIMIZER.analyze(info, "SELECT id FROM t WHERE x = 1")
        cost = _COST_ESTIMATOR.estimate(info, "bigquery")
        text = _REPORT_GENERATOR.generate_text_report(info, recs, cost)
        assert "ETL PERFORMANCE OPTIMIZATION REPORT" in text
        assert "QUERY ANALYSIS" in text
        assert "Query Type: SELECT" in text
        assert "Tables: t" in text
        assert "Complexity: LOW" in text
        assert "COST ESTIMATE" in text
        assert "Warehouse: BigQuery" in text
        assert "OPTIMIZATION RECOMMENDATIONS (1 found)" in text

    def test_text_report_cost_format(self):
        info = _PARSER.parse("SELECT id FROM t WHERE x = 1")
        cost = _COST_ESTIMATOR.estimate(info, "bigquery")
        text = _REPORT_GENERATOR.generate_text_report(info, [], cost)
        assert f"${cost.total_cost:.4f} USD" in text
        assert "Assumptions:" in text

    def test_text_report_no_recommendations(self):
        info = _PARSER.parse("SELECT 1")
        text = _REPORT_GENERATOR.generate_text_report(info, [])
        assert "No optimization issues detected" in text
        assert "Tables: None" in text
        assert "Aggregations: None" in text

    def test_text_report_severity_icons(self):
        info = _PARSER.parse("SELECT id FROM t WHERE x = 1")
        m = _metrics(skew_ratio=10.0)
        spark_recs = _SPARK_ANALYZER.analyze(m)
        text = _REPORT_GENERATOR.generate_text_report(info, spark_recs)
        assert "🔴" in text  # critical

    def test_text_report_implementation_lines(self):
        info = _PARSER.parse("SELECT id FROM t WHERE x = 1")
        recs = _OPTIMIZER.analyze(info, "SELECT id FROM t WHERE x = 1")
        text = _REPORT_GENERATOR.generate_text_report(info, recs)
        assert "Implementation:" in text

    def test_json_report_structure(self):
        info = _PARSER.parse("SELECT id FROM t WHERE x = 1")
        recs = _OPTIMIZER.analyze(info, "SELECT id FROM t WHERE x = 1")
        cost = _COST_ESTIMATOR.estimate(info, "bigquery")
        report = _REPORT_GENERATOR.generate_json_report(info, recs, cost)
        assert report["report_type"] == "etl_performance_optimization"
        assert "generated_at" in report
        assert report["query_analysis"] == {
            "query_type": "SELECT",
            "tables": ["t"],
            "joins": [],
            "subqueries": 0,
            "aggregations": [],
            "window_functions": [],
            "complexity": "low",
        }
        assert report["cost_estimate"] == asdict(cost)
        assert len(report["recommendations"]) == 1
        assert report["recommendations"][0] == asdict(recs[0])
        assert report["summary"] == {
            "total_recommendations": 1,
            "critical": 0,
            "high": 0,
            "medium": 1,
            "low": 0,
        }

    def test_json_report_summary_counts_severities(self):
        info = _PARSER.parse("SELECT * FROM a CROSS JOIN b WHERE a.x = 1")
        recs = _OPTIMIZER.analyze(info, "SELECT * FROM a CROSS JOIN b WHERE a.x = 1")
        report = _REPORT_GENERATOR.generate_json_report(info, recs)
        assert report["summary"]["total_recommendations"] == len(recs)
        assert report["summary"]["critical"] >= 1
        assert report["summary"]["high"] >= 1

    def test_json_report_no_cost_or_recs(self):
        info = _PARSER.parse("SELECT 1")
        report = _REPORT_GENERATOR.generate_json_report(info, [])
        assert report["cost_estimate"] is None
        assert report["recommendations"] == []
        assert report["summary"] == {
            "total_recommendations": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        }


# ── CLI ────────────────────────────────────────────────────────


class TestCli:
    def test_main_no_command_exits_1(self):
        status, code = _run_main(["etl_performance_optimizer.py"])
        assert status == "exit"
        assert code == 1

    def test_main_bad_subcommand_exits_2(self):
        status, code = _run_main(["etl_performance_optimizer.py", "bogus-command"])
        assert status == "exit"
        assert code == 2

    def test_analyze_sql_inline(self):
        out = _capture_stdout(
            epo_main_wrapper, ["etl_performance_optimizer.py",
                               "analyze-sql", "SELECT id FROM t WHERE x = 1"])
        assert "ETL PERFORMANCE OPTIMIZATION REPORT" in out
        assert "Query Type: SELECT" in out

    def test_analyze_sql_json(self):
        out = _capture_stdout(
            epo_main_wrapper, ["etl_performance_optimizer.py",
                               "analyze-sql", "SELECT id FROM t WHERE x = 1",
                               "--json"])
        report = json.loads(out)
        assert report["report_type"] == "etl_performance_optimization"
        assert report["query_analysis"]["query_type"] == "SELECT"

    def test_analyze_sql_with_warehouse(self):
        out = _capture_stdout(
            epo_main_wrapper, ["etl_performance_optimizer.py",
                               "analyze-sql", "SELECT id FROM t WHERE x = 1",
                               "-w", "bigquery"])
        assert "COST ESTIMATE" in out
        assert "Warehouse: BigQuery" in out

    def test_analyze_sql_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            sql_path = Path(tmp) / "q.sql"
            sql_path.write_text("SELECT id FROM t WHERE x = 1")
            out = _capture_stdout(
                epo_main_wrapper, ["etl_performance_optimizer.py",
                                   "analyze-sql", str(sql_path)])
            assert "ETL PERFORMANCE OPTIMIZATION REPORT" in out

    def test_analyze_sql_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.txt"
            out = _capture_stdout(
                epo_main_wrapper, ["etl_performance_optimizer.py",
                                   "analyze-sql", "SELECT id FROM t WHERE x = 1",
                                   "-o", str(out_path)])
            assert out == ""
            assert "ETL PERFORMANCE OPTIMIZATION REPORT" in out_path.read_text()

    def test_analyze_sql_output_file_logs_saved_message(self):
        handler = _ListHandler()
        logger = EPO.logger
        old_propagate = logger.propagate
        logger.addHandler(handler)
        logger.propagate = False
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out_path = Path(tmp) / "out.txt"
                _capture_stdout(
                    epo_main_wrapper,
                    ["etl_performance_optimizer.py",
                     "analyze-sql", "SELECT id FROM t WHERE x = 1",
                     "-o", str(out_path)])
            messages = [r.getMessage() for r in handler.records]
            assert any("Report saved to" in m for m in messages)
        finally:
            logger.removeHandler(handler)
            logger.propagate = old_propagate

    def test_analyze_spark_single_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = _write_json(Path(tmp), "m.json", {
                "jobId": "job_1", "duration": 300000, "numStages": 5,
                "numTasks": 200, "shuffleReadBytes": 5368709120,
                "shuffleWriteBytes": 2147483648, "inputBytes": 10737418240,
                "outputBytes": 1073741824, "peakMemoryBytes": 4294967296,
                "gcTime": 15000, "failedTasks": 2, "speculativeTasks": 5,
                "skewRatio": 3.5})
            out = _capture_stdout(
                epo_main_wrapper, ["etl_performance_optimizer.py",
                                   "analyze-spark", str(metrics_path)])
            assert "SPARK JOB OPTIMIZATION REPORT" in out
            assert "Jobs Analyzed: 1" in out
            assert "Task Failures Detected" in out

    def test_analyze_spark_array_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = {"jobId": "job_1", "duration": 300000, "numStages": 5,
                   "numTasks": 200, "shuffleReadBytes": 5368709120,
                   "shuffleWriteBytes": 2147483648, "inputBytes": 10737418240,
                   "outputBytes": 1073741824, "peakMemoryBytes": 4294967296,
                   "gcTime": 15000, "failedTasks": 2, "speculativeTasks": 5,
                   "skewRatio": 3.5}
            metrics_path = _write_json(Path(tmp), "m.json", [job, job])
            out = _capture_stdout(
                epo_main_wrapper, ["etl_performance_optimizer.py",
                                   "analyze-spark", str(metrics_path)])
            # identical jobs deduplicate to a single "Task Failures Detected"
            assert "Recommendations: 1" in out

    def test_analyze_spark_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = _write_json(Path(tmp), "m.json", {
                "jobId": "job_1", "duration": 300000, "numStages": 5,
                "numTasks": 200, "shuffleReadBytes": 5368709120,
                "shuffleWriteBytes": 2147483648, "inputBytes": 10737418240,
                "outputBytes": 1073741824, "peakMemoryBytes": 4294967296,
                "gcTime": 15000, "failedTasks": 2, "speculativeTasks": 5,
                "skewRatio": 3.5})
            out = _capture_stdout(
                epo_main_wrapper, ["etl_performance_optimizer.py",
                                   "analyze-spark", str(metrics_path),
                                   "--json"])
            recs = json.loads(out)
            assert isinstance(recs, list)
            assert {r["title"] for r in recs} == {"Task Failures Detected"}

    def test_analyze_spark_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics_path = _write_json(Path(tmp), "m.json", {
                "jobId": "job_1", "duration": 300000, "numStages": 5,
                "numTasks": 200, "shuffleReadBytes": 5368709120,
                "shuffleWriteBytes": 2147483648, "inputBytes": 10737418240,
                "outputBytes": 1073741824, "peakMemoryBytes": 4294967296,
                "gcTime": 15000, "failedTasks": 2, "speculativeTasks": 5,
                "skewRatio": 3.5})
            out_path = Path(tmp) / "out.txt"
            out = _capture_stdout(
                epo_main_wrapper, ["etl_performance_optimizer.py",
                                   "analyze-spark", str(metrics_path),
                                   "-o", str(out_path)])
            assert out == ""
            assert "SPARK JOB OPTIMIZATION REPORT" in out_path.read_text()

    def test_analyze_spark_missing_file_exits_1(self):
        status, code = _run_main(
            ["etl_performance_optimizer.py", "analyze-spark",
             "/nonexistent/path.json"])
        assert status == "exit"
        assert code == 1

    def test_optimize_partition_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            stats_path = _write_json(Path(tmp), "s.json", {
                "total_size_bytes": 10737418240, "row_count": 10000000,
                "columns": {
                    "created_at": {"data_type": "timestamp",
                                   "cardinality": 100000,
                                   "null_percentage": 0},
                    "category": {"data_type": "string",
                                 "cardinality": 50,
                                 "null_percentage": 2}}})
            out = _capture_stdout(
                epo_main_wrapper, ["etl_performance_optimizer.py",
                                   "optimize-partition", str(stats_path)])
            assert "PARTITION STRATEGY RECOMMENDATIONS" in out
            assert "created_at" in out
            assert "range" in out

    def test_optimize_partition_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            stats_path = _write_json(Path(tmp), "s.json", {
                "total_size_bytes": 10737418240, "row_count": 10000000,
                "columns": {"category": {"data_type": "string",
                                         "cardinality": 50,
                                         "null_percentage": 2}}})
            out = _capture_stdout(
                epo_main_wrapper, ["etl_performance_optimizer.py",
                                   "optimize-partition", str(stats_path),
                                   "--json"])
            strategies = json.loads(out)
            assert len(strategies) == 1
            assert strategies[0]["column"] == "category"
            assert strategies[0]["partition_type"] == "list"
            assert strategies[0]["num_partitions"] == 50

    def test_optimize_partition_empty_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            stats_path = _write_json(Path(tmp), "s.json", {"columns": {}})
            out = _capture_stdout(
                epo_main_wrapper, ["etl_performance_optimizer.py",
                                   "optimize-partition", str(stats_path)])
            assert "No partition recommendations" in out

    def test_estimate_cost_text(self):
        out = _capture_stdout(
            epo_main_wrapper, ["etl_performance_optimizer.py",
                               "estimate-cost", "SELECT id FROM t WHERE x = 1",
                               "-w", "snowflake"])
        assert "Cost Estimate for Snowflake" in out
        assert "Compute Cost:" in out
        assert "Total:" in out
        assert "Assumptions:" in out

    def test_estimate_cost_json(self):
        out = _capture_stdout(
            epo_main_wrapper, ["etl_performance_optimizer.py",
                               "estimate-cost", "SELECT id FROM t",
                               "-w", "bigquery", "--json"])
        cost = json.loads(out)
        assert cost["warehouse"] == "BigQuery"
        assert cost["currency"] == "USD"
        assert cost["total_cost"] == cost["compute_cost"]

    def test_estimate_cost_missing_warehouse_exits_2(self):
        status, code = _run_main(
            ["etl_performance_optimizer.py", "estimate-cost", "SELECT 1"])
        assert status == "exit"
        assert code == 2

    def test_estimate_cost_with_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            stats_path = _write_json(Path(tmp), "s.json",
                                     {"total_size_bytes": 1_000_000_000_000})
            out = _capture_stdout(
                epo_main_wrapper, ["etl_performance_optimizer.py",
                                   "estimate-cost", "SELECT id FROM t WHERE x = 1",
                                   "-w", "bigquery", "-s", str(stats_path)])
            assert "Cost Estimate for BigQuery" in out

    def test_estimate_cost_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "cost.txt"
            out = _capture_stdout(
                epo_main_wrapper, ["etl_performance_optimizer.py",
                                   "estimate-cost", "SELECT id FROM t",
                                   "-w", "bigquery", "-o", str(out_path)])
            assert out == ""
            assert "Cost Estimate for BigQuery" in out_path.read_text()

    def test_template_data_stats(self):
        out = _capture_stdout(
            epo_main_wrapper, ["etl_performance_optimizer.py",
                               "template", "data_stats"])
        template = json.loads(out)
        assert sorted(template.keys()) == ["columns", "row_count",
                                           "total_size_bytes"]
        assert template["row_count"] == 10000000
        assert "created_at" in template["columns"]

    def test_template_spark_metrics(self):
        out = _capture_stdout(
            epo_main_wrapper, ["etl_performance_optimizer.py",
                               "template", "spark_metrics"])
        template = json.loads(out)
        assert template["jobId"] == "job_12345"
        assert template["numTasks"] == 200

    def test_template_unknown_exits_2(self):
        status, code = _run_main(
            ["etl_performance_optimizer.py", "template", "bogus"])
        assert status == "exit"
        assert code == 2

    def test_template_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "tpl.json"
            out = _capture_stdout(
                epo_main_wrapper, ["etl_performance_optimizer.py",
                                   "template", "data_stats",
                                   "-o", str(out_path)])
            assert out == ""
            template = json.loads(out_path.read_text())
            assert "total_size_bytes" in template

    def test_main_verbose_flag_accepted(self):
        out = _capture_stdout(
            epo_main_wrapper, ["etl_performance_optimizer.py", "--verbose",
                               "analyze-sql", "SELECT id FROM t WHERE x = 1"])
        assert "ETL PERFORMANCE OPTIMIZATION REPORT" in out


# ── Test runner ────────────────────────────────────────────


def main() -> int:
    classes = [
        TestDataclasses,
        TestSQLParserCleaning,
        TestSQLParserSelect,
        TestSQLParserTables,
        TestSQLParserJoins,
        TestSQLParserAdvanced,
        TestSQLOptimizer,
        TestSparkJobAnalyzer,
        TestPartitionAdvisor,
        TestCostEstimator,
        TestReportGenerator,
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
