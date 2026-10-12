#!/usr/bin/env python3
"""Unit tests for nifi_layout.py (NiFi canvas audit/beautify geometry)."""

import logging
import sys
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR / "scripts"))

import nifi_layout as N  # noqa: E402
from nifi_layout import (  # noqa: E402
    BUS_GAP,
    CONNECTION_BACKPRESSURE_HEIGHT,
    CONNECTION_LABEL_WIDTH,
    CONNECTION_ROW_HEIGHT,
    LABEL,
    LABEL_CLEARANCE,
    LANE_GAP,
    LINE_SPACING,
    MAIN_X,
    PAD,
    PREFERRED_LANE_SPACING,
    SIZE,
    OUTER_LABEL_LANE_GAP,
    COMPONENT_CLEARANCE,
)
from nifi_layout import main as nifi_main  # noqa: E402  (alias to avoid shadowing)


# ── Helpers ──────────────────────────────────────────────────────────

def proc(name="P", x=0.0, y=0.0, comments=""):
    return N.Node(name, "PROCESSOR", name, x, y, comments)


def pg(name="G", x=0.0, y=0.0, comments=""):
    return N.Node(name, "PROCESS_GROUP", name, x, y, comments)


def port(kind, name="Port", x=0.0, y=0.0, comments=""):
    return N.Node(name, kind, name, x, y, comments)


def conn(cid, src, dst, name="", relationships=("success",)):
    return N.Conn(cid, src, dst, "PROCESSOR", "PROCESSOR", None, None, src, dst, relationships, name=name)


# ── Rect ─────────────────────────────────────────────────────────────

class TestRect:
    def test_construct_and_accessors(self):
        r = N.Rect(10, 20, 30, 40)
        assert r.left == 10
        assert r.right == 40
        assert r.top == 20
        assert r.bottom == 60
        assert r.cx == 25
        assert r.cy == 40

    def test_inflate_grows_evenly(self):
        r = N.Rect(0, 0, 10, 10).inflate(5)
        assert (r.x, r.y, r.w, r.h) == (-5, -5, 20, 20)
        assert r.left == -5 and r.right == 15

    def test_intersects_overlapping(self):
        a = N.Rect(0, 0, 10, 10)
        assert a.intersects(N.Rect(5, 5, 5, 5))
        assert a.intersects(N.Rect(9, 9, 5, 5))  # corner touch
        assert not a.intersects(N.Rect(11, 11, 5, 5))
        assert not a.intersects(N.Rect(10, 0, 5, 5))  # flush edge

    def test_as_dict_rounds(self):
        d = N.Rect(1.23456, 2.34567, 3.0, 4.0).as_dict()
        assert d == {"x": 1.235, "y": 2.346, "w": 3.0, "h": 4.0}


# ── Node / Conn ──────────────────────────────────────────────────────

class TestDataclasses:
    def test_node_size_defaults_to_processor(self):
        n = N.Node("a", "PROCESSOR", "A", 0, 0)
        assert n.size() == SIZE["PROCESSOR"]
        assert n.rect().w == SIZE["PROCESSOR"][0]

    def test_node_size_by_kind(self):
        for kind, expected in SIZE.items():
            assert N.Node("a", kind, "A", 0, 0).size() == expected

    def test_node_with_pos_is_immutable(self):
        n = N.Node("a", "PROCESSOR", "A", 0, 0)
        m = n.with_pos(100, 200)
        assert (n.x, n.y) == (0, 0)
        assert (m.x, m.y) == (100, 200)
        assert m.id == n.id and m.name == n.name

    def test_conn_defaults(self):
        c = N.Conn("c", "a", "b", "PROCESSOR", "PROCESSOR", None, None, "a", "b", ("success",))
        assert c.name == ""
        assert c.bends == []
        assert c.label_index == 0
        assert c.relationships == ("success",)

# ── Constants ────────────────────────────────────────────────────────

class TestConstants:
    def test_sizes_match_canvas_constants(self):
        assert SIZE["PROCESSOR"] == (350.0, 130.0)
        assert SIZE["PROCESS_GROUP"] == (384.0, 176.0)
        assert SIZE["INPUT_PORT"] == (240.0, 48.0)
        assert SIZE["OUTPUT_PORT"] == (240.0, 48.0)
        assert SIZE["FUNNEL"] == (48.0, 48.0)

    def test_label_size_formula(self):
        assert LABEL == (CONNECTION_LABEL_WIDTH, CONNECTION_ROW_HEIGHT * 2 + CONNECTION_BACKPRESSURE_HEIGHT)
        assert CONNECTION_LABEL_WIDTH == 240.0
        assert CONNECTION_ROW_HEIGHT == 19.0
        assert CONNECTION_BACKPRESSURE_HEIGHT == 3.0

    def test_main_x_offsets(self):
        assert MAIN_X["PROCESSOR"] == 160.0
        assert MAIN_X["PROCESS_GROUP"] == 144.0
        assert MAIN_X["INPUT_PORT"] == 215.0
        assert MAIN_X["OUTPUT_PORT"] == 215.0
        assert MAIN_X["FUNNEL"] == 240.0

    def test_outer_label_lane_gap_formula(self):
        assert OUTER_LABEL_LANE_GAP == CONNECTION_LABEL_WIDTH / 2.0 + LABEL_CLEARANCE


# ── node_from / conn_from / parse_group ──────────────────────────────

class TestParsing:
    def test_node_from_basic(self):
        e = {"component": {"id": "p1", "name": "Fetch", "position": {"x": 10, "y": 20}, "comments": "hi"}, "revision": {"version": 5}}
        n = N.node_from(e, "PROCESSOR")
        assert (n.id, n.name, n.x, n.y, n.comments, n.revision) == ("p1", "Fetch", 10, 20, "hi", 5)

    def test_node_from_missing_comments_and_name(self):
        e = {"component": {"id": "p2", "position": {"x": 1, "y": 2}}}
        n = N.node_from(e, "PROCESSOR")
        assert n.name == "" and n.comments == "" and n.revision == 0

    def test_node_from_comments_from_config(self):
        e = {"component": {"id": "p3", "name": "X", "position": {"x": 0, "y": 0}, "config": {"comments": "cfg comment"}}}
        assert N.node_from(e, "PROCESSOR").comments == "cfg comment"

    def test_conn_from_full(self):
        e = {"component": {"id": "c1", "source": {"id": "a", "type": "PROCESSOR", "name": "A", "groupId": "g1"},
                           "destination": {"id": "b", "type": "PROCESSOR", "name": "B"},
                           "selectedRelationships": ["success", "failure"],
                           "name": "labeled", "bends": [{"x": 1, "y": 2}], "labelIndex": 2},
               "revision": {"version": 7}}
        c = N.conn_from(e)
        assert (c.id, c.source_id, c.dest_id, c.source_name, c.dest_name) == ("c1", "a", "b", "A", "B")
        assert c.source_group_id == "g1" and c.dest_group_id is None
        assert c.relationships == ("success", "failure")
        assert c.name == "labeled" and c.bends == [{"x": 1, "y": 2}] and c.label_index == 2
        assert c.revision == 7

    def test_conn_from_defaults(self):
        e = {"component": {"id": "c2", "source": {"id": "a", "type": "PROCESSOR", "name": "A"},
                           "destination": {"id": "b", "type": "PROCESSOR", "name": "B"}}}
        c = N.conn_from(e)
        assert c.name == "" and c.bends == [] and c.label_index == 0 and c.relationships == ()
        assert c.source_group_id is None and c.dest_group_id is None

    def test_parse_group_collects_all_kinds(self):
        flow = {
            "processors": [{"component": {"id": "p", "name": "P", "position": {"x": 0, "y": 0}}}],
            "processGroups": [{"component": {"id": "g", "name": "G", "position": {"x": 0, "y": 0}}}],
            "inputPorts": [{"component": {"id": "ip", "name": "IP", "position": {"x": 0, "y": 0}}}],
            "outputPorts": [{"component": {"id": "op", "name": "OP", "position": {"x": 0, "y": 0}}}],
            "funnels": [{"component": {"id": "f", "name": "F", "position": {"x": 0, "y": 0}}}],
            "connections": [{"component": {"id": "c", "source": {"id": "p", "type": "PROCESSOR", "name": "P"},
                                            "destination": {"id": "g", "type": "PROCESS_GROUP", "name": "G"}}}],
        }
        nodes, conns = N.parse_group(flow)
        assert set(nodes) == {"p", "g", "ip", "op", "f"}
        assert nodes["ip"].kind == "INPUT_PORT"
        assert nodes["op"].kind == "OUTPUT_PORT"
        assert nodes["f"].kind == "FUNNEL"
        assert len(conns) == 1 and conns[0].id == "c"

    def test_parse_group_empty(self):
        nodes, conns = N.parse_group({})
        assert nodes == {} and conns == []


# ── visual_id / terminal_is_group_port ───────────────────────────────

class TestVisualId:
    def test_source_in_nodes(self):
        c = conn("c", "a", "b")
        assert N.visual_id(c, "source", "g", {"a": proc("a"), "b": proc("b")}) == "a"

    def test_dest_falls_back_to_group_id(self):
        c = N.Conn("c", "a", "b", "PROCESSOR", "PROCESSOR", None, "other_group", "a", "b", ("success",))
        # dest not in nodes, dest_group_id != current_group and in nodes -> use group id
        nodes = {"a": proc("a"), "other_group": pg("other_group")}
        assert N.visual_id(c, "dest", "g", nodes) == "other_group"

    def test_dest_falls_back_to_id(self):
        c = conn("c", "a", "b")
        nodes = {"a": proc("a")}
        assert N.visual_id(c, "dest", "g", nodes) == "b"


class TestTerminalIsGroupPort:
    def test_port_inside_other_group(self):
        assert N.terminal_is_group_port("INPUT_PORT", "g2", "g1") is True
        assert N.terminal_is_group_port("OUTPUT_PORT", "g2", "g1") is True

    def test_port_in_same_group_or_none(self):
        assert N.terminal_is_group_port("INPUT_PORT", "g1", "g1") is False
        assert N.terminal_is_group_port("INPUT_PORT", None, "g1") is False
        assert N.terminal_is_group_port("PROCESSOR", "g2", "g1") is False


# ── Text classification ──────────────────────────────────────────────

class TestTextClassification:
    def test_is_failureish_text_matches(self):
        assert N.is_failureish_text("my error handler")
        assert N.is_failureish_text("FailureRoute")
        assert N.is_failureish_text("dead-letter")
        assert N.is_failureish_text("unmatched flow")
        assert N.is_failureish_text("waiting for data")
        assert N.is_failureish_text("ошибки обработка")

    def test_is_failureish_text_negative(self):
        assert not N.is_failureish_text("normal success path")
        assert not N.is_failureish_text("fetch data")

    def test_is_sideish_text_adds_more_words(self):
        assert N.is_sideish_text("fallback branch")
        assert N.is_sideish_text("teams notification")
        assert N.is_sideish_text("лог ошибки collector")
        assert N.is_sideish_text("error handler")  # via failureish
        assert not N.is_sideish_text("main success")

    def test_is_errorish_excludes_side_words(self):
        assert N.is_errorish(proc("e", comments="error handler"))
        assert N.is_errorish(proc(name="dead-letter route"))
        assert N.is_errorish(proc("e", comments="лог ошибки"))
        assert not N.is_errorish(proc("e", comments="fallback branch"))
        assert not N.is_errorish(proc(name="fetch data"))


# ── strip_number / comment_for ───────────────────────────────────────

class TestStripAndComment:
    def test_strip_number_removes_leading_numbers(self):
        assert N.strip_number("10 Fetch Data") == "Fetch Data"
        assert N.strip_number("30.20.10 Build") == "Build"
        assert N.strip_number("Fetch") == "Fetch"
        assert N.strip_number("  20  Something ") == "Something"
        # Requires trailing whitespace to strip pure numbers
        assert N.strip_number("100 ") == ""

    def test_comment_for_uses_existing_comments(self):
        n = proc("x", comments="  keep me  ")
        assert N.comment_for(n) == "keep me"

    def test_comment_for_input_port(self):
        n = port("INPUT_PORT", "10 In", 0, 0)
        c = N.comment_for(n)
        assert "Вход" in c and "FlowFile" in c

    def test_comment_for_output_port(self):
        n = port("OUTPUT_PORT", "20 Out", 0, 0)
        c = N.comment_for(n)
        assert "Выход" in c and "FlowFile" in c

    def test_comment_for_process_group(self):
        n = pg("30 Group", 0, 0)
        assert "Группа" in N.comment_for(n)

    def test_comment_for_errorish(self):
        n = proc("error handler", comments="")
        c = N.comment_for(n)
        assert "ошибочном" in c or "error" in c.lower()

    def test_comment_for_plain_processor(self):
        n = proc("Fetch Data", comments="")
        assert "Fetch Data" in N.comment_for(n)


# ── relation_text / processor_has_side_hint ──────────────────────────

class TestRelationAndSideHint:
    def test_relation_text_lowercases_all_fields(self):
        c = conn("c", "a", "b", name="MyLabel", relationships=("SUCCESS", "Failure"))
        assert N.relation_text(c) == "mylabel success failure a b"

    def test_side_hint_from_name(self):
        n = proc("fallback route", comments="")
        assert N.processor_has_side_hint(n, None) is True

    def test_side_hint_from_relation(self):
        n = proc("normal", comments="")
        c = conn("c", "normal", "b", name="", relationships=("failure",))
        assert N.processor_has_side_hint(n, [c]) is True

    def test_no_side_hint(self):
        n = proc("fetch data", comments="")
        c = conn("c", "a", "b", name="", relationships=("success",))
        assert N.processor_has_side_hint(n, [c]) is False


# ── classify_main / target_layout ────────────────────────────────────

class TestClassifyMain:
    def test_empty_returns_empty(self):
        assert N.classify_main({}) == ([], [])

    def test_central_processor_is_main(self):
        a = proc("a", 160, 0)
        b = proc("b", 160, 220)
        main, side = N.classify_main({"a": a, "b": b})
        assert len(main) == 2 and side == []

    def test_far_right_without_hint_is_side(self):
        # base_x is median x; with 3 nodes at 160, 160, 1200 -> median 160
        main_p = proc("m", 160, 0)
        mid_p = proc("mid", 160, 220)
        side_p = proc("s", 1200, 0)
        main, side = N.classify_main({"m": main_p, "mid": mid_p, "s": side_p})
        assert side_p in side and main_p in main

    def test_far_left_with_side_hint_is_side(self):
        main_p = proc("m", 160, 0)
        side_p = proc("s", -600, 0, comments="error fallback")
        main, side = N.classify_main({"m": main_p, "s": side_p}, [])
        assert side_p in side and main_p in main

    def test_far_left_without_hint_is_main(self):
        main_p = proc("m", 160, 0)
        left_p = proc("l", -600, 0)
        main, side = N.classify_main({"m": main_p, "l": left_p}, [])
        assert left_p in main and side == []

    def test_sorted_by_y_then_x(self):
        a = proc("a", 200, 300)
        b = proc("b", 100, 100)
        main, _ = N.classify_main({"a": a, "b": b})
        assert [n.id for n in main] == ["b", "a"]


class TestTargetLayout:
    def test_empty_returns_empty(self):
        assert N.target_layout({}) == {}

    def test_single_processor_gets_main_x(self):
        n = proc("p", 999, 999)
        t = N.target_layout({"p": n})
        assert t["p"] == (MAIN_X["PROCESSOR"], 0.0)

    def test_vertical_chain_stacks_downward(self):
        a = proc("a", 0, 0)
        b = proc("b", 0, 220)
        c = proc("c", 0, 440)
        t = N.target_layout({"a": a, "b": b, "c": c})
        assert t["a"][1] < t["b"][1] < t["c"][1]
        assert t["a"][0] == MAIN_X["PROCESSOR"]

    def test_source_like_first(self):
        # input port has no incoming -> source_like -> ordered before processors
        ip = port("INPUT_PORT", "in", 0, 0)
        p = proc("p", 0, 500)
        t = N.target_layout({"p": p, "in": ip})
        assert t["in"][1] < t["p"][1]

    def test_final_output_placed_below(self):
        p = proc("p", 0, 0)
        out = port("OUTPUT_PORT", "out", 0, 1000)
        c = conn("c", "p", "out")
        t = N.target_layout({"p": p, "out": out}, [c])
        assert t["out"][1] > t["p"][1]
        assert t["out"][1] > p.y

    def test_failure_output_goes_right(self):
        p = proc("p", 0, 0)
        good = port("OUTPUT_PORT", "good", 0, 1000)
        fail = port("OUTPUT_PORT", "fail", 0, 1000)
        conns = [conn("good", "p", "good"), conn("fail", "p", "fail", name="", relationships=("failure",))]
        t = N.target_layout({"p": p, "good": good, "fail": fail}, conns)
        assert t["fail"][0] > t["good"][0]

    def test_with_targets_replaces_only_listed(self):
        a = proc("a", 0, 0)
        b = proc("b", 10, 10)
        out = N.with_targets({"a": a, "b": b}, {"a": (100, 200)})
        assert (out["a"].x, out["a"].y) == (100, 200)
        assert (out["b"].x, out["b"].y) == (10, 10)


# ── rects / rects_actual / segment_rect ──────────────────────────────

class TestRectHelpers:
    def test_rects_inflate_by_pad(self):
        n = proc("p", 0, 0)
        r = N.rects({"p": n})[0][1]
        assert r.x == -PAD and r.w == SIZE["PROCESSOR"][0] + 2 * PAD

    def test_rects_exclude(self):
        a = proc("a", 0, 0)
        b = proc("b", 10, 10)
        got = N.rects({"a": a, "b": b}, exclude=["a"])
        assert [i for i, _ in got] == ["b"]

    def test_rects_actual_no_inflation(self):
        n = proc("p", 5, 6)
        r = N.rects_actual({"p": n})[0][1]
        assert (r.x, r.y, r.w, r.h) == (5, 6, SIZE["PROCESSOR"][0], SIZE["PROCESSOR"][1])

    def test_segment_rect_vertical(self):
        r = N.segment_rect((10, 0), (10, 100), 2.0)
        assert (r.x, r.y, r.w, r.h) == (8.0, -2.0, 4.0, 104.0)

    def test_segment_rect_horizontal(self):
        r = N.segment_rect((0, 5), (100, 5), 3.0)
        assert (r.x, r.y, r.w, r.h) == (-3.0, 2.0, 106.0, 6.0)


# ── orthogonal_segment / overlap helpers ─────────────────────────────

class TestOrthogonalSegment:
    def test_vertical_segment(self):
        s = N.orthogonal_segment((10, 0), (10, 100))
        assert s == ("v", 10.0, 0.0, 100.0)

    def test_horizontal_segment(self):
        s = N.orthogonal_segment((0, 5), (100, 5))
        assert s == ("h", 5.0, 0.0, 100.0)

    def test_short_segment_returns_none(self):
        # both dx and dy < 1.0 -> neither vertical nor horizontal
        assert N.orthogonal_segment((10, 10), (10.5, 10.5)) is None
        # vertical but too short (< 1.0 in y)
        assert N.orthogonal_segment((10, 10), (10, 10.5)) is None

    def test_collinear_overlap(self):
        a = ("v", 10.0, 0.0, 100.0)
        b = ("v", 10.0, 50.0, 150.0)
        assert N.segment_overlap_amount(a, b) == 50.0

    def test_no_overlap_when_disjoint(self):
        a = ("v", 10.0, 0.0, 50.0)
        b = ("v", 10.0, 60.0, 100.0)
        assert N.segment_overlap_amount(a, b) == 0.0

    def test_different_orientation_no_overlap(self):
        assert N.segment_overlap_amount(("v", 10, 0, 100), ("h", 5, 0, 100)) == 0.0

    def test_parallel_overlap_different_lanes(self):
        a = ("v", 10.0, 0.0, 100.0)
        b = ("v", 40.0, 50.0, 150.0)
        assert N.segment_parallel_overlap(a, b) == 50.0

    def test_parallel_overlap_opposite_orientation(self):
        assert N.segment_parallel_overlap(("v", 10, 0, 100), ("h", 5, 0, 100)) == 0.0


class TestPerpendicularCrossPoint:
    def test_cross_inside(self):
        assert N.perpendicular_cross_point(("v", 50, 0, 100), ("h", 40, 0, 100)) == (50, 40)

    def test_cross_outside_margin(self):
        # vertical ends at y=100, horizontal at y=0 with margin 3 -> no cross
        assert N.perpendicular_cross_point(("v", 50, 0, 100), ("h", 0, 0, 100)) is None

    def test_same_orientation_no_cross(self):
        assert N.perpendicular_cross_point(("v", 10, 0, 100), ("v", 40, 0, 100)) is None

    def test_custom_margin(self):
        # vertical 0..100, horizontal at y=50 spanning 40..60 -> cross at (50, 50)
        # with margin=3: h[2]+3=43 < 50 < h[3]-3=57, v[2]+3=3 < 50 < v[3]-3=97
        assert N.perpendicular_cross_point(("v", 50, 0, 100), ("h", 50, 40, 60), margin=3.0) == (50, 50)


class TestDistinctRouteSegmentPair:
    def test_same_connection_adjacent_not_distinct(self):
        assert N.distinct_route_segment_pair("c", 0, "c", 1) is False
        assert N.distinct_route_segment_pair("c", 5, "c", 6) is False

    def test_same_connection_non_adjacent_distinct(self):
        assert N.distinct_route_segment_pair("c", 0, "c", 2) is True
        assert N.distinct_route_segment_pair("c", 1, "c", 3) is True

    def test_different_connection_always_distinct(self):
        assert N.distinct_route_segment_pair("a", 0, "b", 0) is True
        assert N.distinct_route_segment_pair("a", 100, "b", 200) is True


# ── route_points ─────────────────────────────────────────────────────

class TestRoutePoints:
    def test_no_bends_vertical_down(self):
        src = proc("s", 0, 0)
        dst = proc("d", 0, 300)
        pts = N.route_points(src, dst, [])
        assert len(pts) == 2
        assert pts[0][0] == src.rect().cx
        assert pts[1][0] == dst.rect().cx

    def test_no_bends_horizontal(self):
        src = proc("s", 0, 0)
        dst = proc("d", 500, 0)
        pts = N.route_points(src, dst, [])
        assert pts[0][1] == src.rect().cy
        assert pts[1][1] == dst.rect().cy

    def test_with_bends_preserved_in_order(self):
        src = proc("s", 0, 0)
        dst = proc("d", 0, 500)
        bends = [{"x": 100, "y": 100}, {"x": 100, "y": 400}]
        pts = N.route_points(src, dst, bends)
        assert pts[1] == (100, 100)
        assert pts[2] == (100, 400)
        # first point is on the source perimeter, last on the destination perimeter
        assert pts[0][0] == src.rect().cx
        assert pts[-1][1] == dst.rect().top

    def test_empty_bends_returns_two_points(self):
        pts = N.route_points(proc("a"), proc("b", 0, 100), [])
        assert len(pts) == 2


# ── connection_label_size / label_rect ───────────────────────────────

class TestLabelSizing:
    def test_minimal_label_size(self):
        # No relationships, no group ports -> 1 row (queued only)
        c = N.Conn("c", "a", "b", "PROCESSOR", "PROCESSOR", None, None, "a", "b", ())
        w, h = N.connection_label_size(c, "root")
        assert w == CONNECTION_LABEL_WIDTH
        assert h == CONNECTION_ROW_HEIGHT + CONNECTION_BACKPRESSURE_HEIGHT

    def test_group_port_adds_row(self):
        # Group port + relationships=("success",) -> 3 rows (queued + group port + relationships)
        c = N.Conn("c", "a", "b", "PROCESSOR", "OUTPUT_PORT", None, "other", "a", "b", ("success",))
        w, h = N.connection_label_size(c, "root")
        assert h == 3 * CONNECTION_ROW_HEIGHT + CONNECTION_BACKPRESSURE_HEIGHT

    def test_relationships_add_row(self):
        c = conn("c", "a", "b", relationships=("success", "failure"))
        w, h = N.connection_label_size(c, "root")
        assert h == 2 * CONNECTION_ROW_HEIGHT + CONNECTION_BACKPRESSURE_HEIGHT

    def test_both_add_two_rows(self):
        c = N.Conn("c", "a", "b", "PROCESSOR", "OUTPUT_PORT", None, "other", "a", "b", ("success", "failure"))
        w, h = N.connection_label_size(c, "root")
        assert h == 3 * CONNECTION_ROW_HEIGHT + CONNECTION_BACKPRESSURE_HEIGHT

    def test_label_rect_with_bends_centers_on_bend(self):
        bends = [{"x": 50, "y": 60}, {"x": 200, "y": 60}]
        pts = N.route_points(proc("s", 0, 0), proc("d", 400, 0), bends)
        lr = N.label_rect(pts, 1, (100, 20), bends)
        assert (lr.cx, lr.cy) == (200, 60)
        assert lr.w == 100 and lr.h == 20

    def test_label_rect_no_bends_centers_on_segment(self):
        pts = N.route_points(proc("s", 0, 0), proc("d", 400, 0), [])
        lr = N.label_rect(pts, 0, (100, 20), [])
        assert lr.cx == (pts[0][0] + pts[-1][0]) / 2

    def test_label_rect_short_points_returns_zero_rect(self):
        lr = N.label_rect([(0, 0)], 0, (100, 20))
        assert (lr.x, lr.y, lr.w, lr.h) == (0, 0, 100, 20)


# ── edge_slot / source_exit_point / spread_coord ─────────────────────

class TestEdgeSlots:
    def test_edge_slot_left(self):
        r = N.Rect(100, 50, 350, 130)
        x, y = N.edge_slot(r, "left", 0, 1)
        assert x == r.left - 48.0
        assert r.top + 26.0 < y < r.bottom - 18.0

    def test_edge_slot_right_spreads(self):
        r = N.Rect(100, 50, 350, 130)
        y0 = N.edge_slot(r, "right", 0, 3)[1]
        y1 = N.edge_slot(r, "right", 1, 3)[1]
        y2 = N.edge_slot(r, "right", 2, 3)[1]
        assert y0 < y1 < y2

    def test_edge_slot_top(self):
        r = N.Rect(100, 50, 350, 130)
        x, y = N.edge_slot(r, "top", 0, 1)
        assert y == r.top - 48.0
        assert r.left + 30.0 < x < r.right - 30.0

    def test_edge_slot_bottom(self):
        r = N.Rect(100, 50, 350, 130)
        x, y = N.edge_slot(r, "bottom", 0, 1)
        assert y == r.bottom + 48.0

    def test_edge_slot_clamps_lane(self):
        r = N.Rect(100, 50, 350, 130)
        # lane beyond total-1 is clamped
        x, y = N.edge_slot(r, "left", 99, 3)
        x2, y2 = N.edge_slot(r, "left", 2, 3)
        assert (x, y) == (x2, y2)

    def test_source_exit_point_left(self):
        n = proc("p", 100, 50)
        x, y = N.source_exit_point(n, "left", 0, 1)
        assert x == n.rect().left - 48.0

    def test_source_exit_point_right(self):
        n = proc("p", 100, 50)
        x, y = N.source_exit_point(n, "right", 0, 1)
        assert x == n.rect().right + 48.0

    def test_source_exit_point_top_bottom(self):
        n = proc("p", 100, 50)
        _, y = N.source_exit_point(n, "top", 0, 1)
        assert y == n.rect().top - 48.0
        _, y = N.source_exit_point(n, "bottom", 0, 1)
        assert y == n.rect().bottom + 48.0


class TestSpreadCoord:
    def test_wide_corridor_uses_fraction(self):
        # Formula: lo + (hi-lo) * (lane+1) / (total+1)
        assert N.spread_coord(0.0, 200.0, 0, 1) == 100.0
        assert abs(N.spread_coord(0.0, 200.0, 1, 2) - 200.0 * 2.0 / 3.0) < 1e-9

    def test_narrow_corridor_creates_outside_lanes(self):
        # gap < 120 -> fallback outside
        v = N.spread_coord(0.0, 50.0, 0, 3)
        assert v != 12.5  # not the naive midpoint fraction


# ── branch_target_side / dense_fanin_target_side ─────────────────────

class TestTargetSides:
    def test_branch_target_left_when_src_right_of_dst(self):
        # src at 500 (right), dst at 0 (left) -> connection enters dst from right
        src = proc("s", 500, 0)
        dst = proc("d", 0, 0)
        assert N.branch_target_side(src, dst) == "right"

    def test_branch_target_right_when_src_left_of_dst(self):
        # src at 0 (left), dst at 500 (right) -> connection enters dst from left
        src = proc("s", 0, 0)
        dst = proc("d", 500, 0)
        assert N.branch_target_side(src, dst) == "left"

    def test_branch_target_top_when_src_below(self):
        # src at y=500 (below), dst at y=0 (above) -> connection enters dst from bottom
        src = proc("s", 300, 500)
        dst = proc("d", 300, 0)
        assert N.branch_target_side(src, dst) == "bottom"

    def test_branch_target_bottom_when_src_above(self):
        # src at y=0 (above), dst at y=500 (below) -> connection enters dst from top
        src = proc("s", 300, 0)
        dst = proc("d", 300, 500)
        assert N.branch_target_side(src, dst) == "top"

    def test_dense_fanin_split_by_row(self):
        # src far to the left, above dst -> left
        src = proc("s", 0, 0)
        dst = proc("d", 500, 200)
        assert N.dense_fanin_target_side(src, dst) == "left"
        # src far to the left, below dst -> right
        src = proc("s", 0, 500)
        dst = proc("d", 500, 200)
        assert N.dense_fanin_target_side(src, dst) == "right"

    def test_dense_fanin_near_column_uses_vertical(self):
        # same column, src above -> top
        src = proc("s", 300, 0)
        dst = proc("d", 310, 300)
        assert N.dense_fanin_target_side(src, dst) == "top"
        # same column, src below -> bottom
        src = proc("s", 300, 600)
        dst = proc("d", 310, 300)
        assert N.dense_fanin_target_side(src, dst) == "bottom"


# ── candidate_routes / choose_route ──────────────────────────────────

class TestCandidateRoutes:
    def test_candidate_routes_count(self):
        src = proc("s", 0, 0)
        dst = proc("d", 0, 500)
        cands = N.candidate_routes(src, dst, 0)
        assert len(cands) >= 5
        for bends, li in cands:
            assert isinstance(bends, list)
            assert isinstance(li, int)

    def test_choose_route_returns_bends_and_index(self):
        src = proc("s", 0, 0)
        dst = proc("d", 500, 300)
        nodes = {"s": src, "d": dst}
        bends, li = N.choose_route(src, dst, nodes, LABEL)
        assert isinstance(bends, list)
        assert isinstance(li, int)
        assert li >= 0

    def test_choose_route_direct_when_aligned(self):
        # directly below, no obstacles -> direct route (no bends)
        src = proc("s", 0, 0)
        dst = proc("d", 0, 500)
        nodes = {"s": src, "d": dst}
        bends, li = N.choose_route(src, dst, nodes, LABEL)
        assert bends == [] and li == 0


# ── route_to_side / route_to_output ──────────────────────────────────

class TestRouteToSide:
    def _nodes(self):
        src = proc("s", 300, 0)
        dst = proc("d", 300, 500)
        return src, dst, {"s": src, "d": dst}

    def test_returns_bends_and_label_index(self):
        src, dst, nodes = self._nodes()
        bends, li = N.route_to_side(src, dst, LABEL, 0, 1, "left", nodes)
        assert isinstance(bends, list) and isinstance(li, int)
        assert len(bends) >= 1

    def test_default_side_uses_branch_target_side(self):
        src, dst, nodes = self._nodes()
        bends, li = N.route_to_side(src, dst, LABEL)
        assert isinstance(bends, list)

    def test_top_and_bottom_vertical_branches(self):
        src, dst, nodes = self._nodes()
        for side in ("top", "bottom"):
            bends, li = N.route_to_side(src, dst, LABEL, 0, 1, side, nodes)
            assert len(bends) >= 2


class TestRouteToOutput:
    def test_returns_bends_and_label_index(self):
        src = proc("s", 300, 0)
        dst = port("OUTPUT_PORT", "d", 300, 500)
        nodes = {"s": src, "d": dst}
        bends, li = N.route_to_output(src, dst, nodes, LABEL, 0, 1)
        assert isinstance(bends, list) and isinstance(li, int)

    def test_far_right_source_uses_side_processor_route(self):
        src = proc("s", 1200, 0)
        dst = port("OUTPUT_PORT", "d", 300, 500)
        nodes = {"s": src, "d": dst}
        bends, li = N.route_to_output(src, dst, nodes, LABEL, 0, 1)
        assert len(bends) >= 1


# ── route_has_component_hit / clear_same_column_route ────────────────

class TestRouteHits:
    def test_clear_route_no_hit(self):
        src = proc("s", 0, 0)
        dst = proc("d", 0, 500)
        nodes = {"s": src, "d": dst}
        assert N.route_has_component_hit(src, dst, [], nodes) is False

    def test_route_through_block_is_hit(self):
        src = proc("s", 0, 0)
        block = proc("block", 0, 250)
        dst = proc("d", 0, 500)
        nodes = {"s": src, "block": block, "d": dst}
        assert N.route_has_component_hit(src, dst, [], nodes) is True

    def test_clear_same_column_route_aligned(self):
        src = proc("s", 100, 0)
        dst = proc("d", 104, 500)
        nodes = {"s": src, "d": dst}
        assert N.clear_same_column_route(src, dst, nodes) is True

    def test_clear_same_column_route_offset_returns_false(self):
        src = proc("s", 0, 0)
        dst = proc("d", 200, 500)  # cx differs by > 80
        nodes = {"s": src, "d": dst}
        assert N.clear_same_column_route(src, dst, nodes) is False

    def test_clear_same_column_route_blocked_by_intermediate(self):
        src = proc("s", 100, 0)
        mid = proc("mid", 100, 250)
        dst = proc("d", 100, 500)
        nodes = {"s": src, "mid": mid, "d": dst}
        assert N.clear_same_column_route(src, dst, nodes) is False


class TestSameColumnBlocked:
    def test_not_blocked_when_far_apart_x(self):
        src = proc("s", 0, 0)
        dst = proc("d", 300, 500)
        nodes = {"s": src, "d": dst}
        assert N.same_column_blocked(src, dst, nodes) is False

    def test_blocked_by_intermediate(self):
        src = proc("s", 100, 0)
        mid = proc("mid", 100, 250)
        dst = proc("d", 100, 500)
        nodes = {"s": src, "mid": mid, "d": dst}
        assert N.same_column_blocked(src, dst, nodes) is True

    def test_not_blocked_when_no_overlap_y(self):
        # dst above src -> y2 <= y1
        src = proc("s", 100, 500)
        dst = proc("d", 100, 0)
        nodes = {"s": src, "d": dst}
        assert N.same_column_blocked(src, dst, nodes) is False


# ── same_column_around_route ─────────────────────────────────────────

class TestSameColumnAround:
    def test_returns_bends_and_label_index(self):
        src = proc("rs1", 1200, 0)
        dst = proc("rs2", 1200, 420)
        nodes = {"rs1": src, "rs2": dst, "mid": proc("mid", 1200, 210)}
        bends, li = N.same_column_around_route(src, dst, nodes, 0, 1)
        assert isinstance(bends, list) and len(bends) >= 2
        assert isinstance(li, int)

    def test_right_column_goes_outside_right(self):
        src = proc("rs1", 1200, 0)
        dst = proc("rs2", 1200, 420)
        nodes = {"rs1": src, "rs2": dst, "mid": proc("mid", 1200, 210)}
        bends, _ = N.same_column_around_route(src, dst, nodes, 0, 1)
        max_x = max(b["x"] for b in bends)
        assert max_x > 1200 + SIZE["PROCESSOR"][0]


# ── nudge_segment_coordinate / label_clearance_rect ──────────────────

class TestNudgeSegment:
    def _bends(self):
        return [{"x": 100, "y": 50}, {"x": 200, "y": 50}]

    def test_nudge_horizontal_run(self):
        bends = self._bends()
        src = proc("s", 0, 0)
        dst = proc("d", 400, 0)
        pts = N.route_points(src, dst, bends)
        changed = N.nudge_segment_coordinate(bends, pts, 0, "h", 90.0)
        assert changed is True
        assert all(b["y"] == 90.0 for b in bends)

    def test_nudge_no_bends_returns_false(self):
        src = proc("s", 0, 0)
        dst = proc("d", 0, 500)
        pts = N.route_points(src, dst, [])
        assert N.nudge_segment_coordinate([], pts, 0, "v", 999.0) is False

    def test_nudge_same_coord_returns_false(self):
        bends = self._bends()
        src = proc("s", 0, 0)
        dst = proc("d", 400, 0)
        pts = N.route_points(src, dst, bends)
        # already at y=50
        assert N.nudge_segment_coordinate(bends, pts, 0, "h", 50.0) is False


class TestLabelClearanceRect:
    def test_vertical(self):
        r = N.label_clearance_rect(("v", 50, 0, 100))
        assert (r.x, r.y, r.w, r.h) == (47.0, 0.0, 6.0, 100.0)

    def test_horizontal(self):
        r = N.label_clearance_rect(("h", 40, 0, 100))
        assert (r.x, r.y, r.w, r.h) == (0.0, 37.0, 100.0, 6.0)


# ── route_cost ───────────────────────────────────────────────────────

class TestRouteCost:
    def test_direct_aligned_no_collisions(self):
        src = proc("s", 0, 0)
        dst = proc("d", 0, 500)
        nodes = {"s": src, "d": dst}
        collisions, length = N.route_cost(src, dst, [], 0, nodes, LABEL)
        assert collisions == 0
        assert length > 0

    def test_diagonal_segment_heavily_penalized(self):
        # bends that force a diagonal between route points
        src = proc("s", 0, 0)
        dst = proc("d", 500, 500)
        nodes = {"s": src, "d": dst}
        bends = [{"x": 0, "y": 500}, {"x": 500, "y": 0}]
        collisions, _ = N.route_cost(src, dst, bends, 0, nodes, LABEL)
        assert collisions >= 80

    def test_label_on_component_adds_collisions(self):
        src = proc("s", 0, 0)
        block = proc("block", 200, 200)
        dst = proc("d", 400, 400)
        nodes = {"s": src, "block": block, "d": dst}
        # place a bend whose label rect lands on the block
        bends = [{"x": 200, "y": 200}]
        collisions, _ = N.route_cost(src, dst, bends, 0, nodes, LABEL)
        assert collisions > 0

    def test_negative_label_index_uses_best_label_index(self):
        src = proc("s", 0, 0)
        dst = proc("d", 500, 300)
        nodes = {"s": src, "d": dst}
        bends = [{"x": 410, "y": 65}, {"x": 410, "y": 365}]
        collisions, length = N.route_cost(src, dst, bends, -1, nodes, LABEL)
        assert isinstance(collisions, int) and length >= 0


# ── best_label_index / best_label_index_avoiding ─────────────────────

class TestBestLabelIndex:
    def test_no_bends_returns_zero(self):
        src = proc("s", 0, 0)
        dst = proc("d", 0, 500)
        assert N.best_label_index(src, dst, [], {}, LABEL) == 0

    def test_picks_index_within_range(self):
        src = proc("s", 0, 0)
        dst = proc("d", 500, 300)
        nodes = {"s": src, "d": dst}
        bends = [{"x": 410, "y": 65}, {"x": 410, "y": 365}]
        li = N.best_label_index(src, dst, bends, nodes, LABEL)
        assert 0 <= li < len(bends)

    def test_avoids_component_blocking_bend(self):
        src = proc("s", 0, 0)
        block = proc("block", 100, 50)
        dst = proc("d", 500, 300)
        nodes = {"s": src, "block": block, "d": dst}
        bends = [{"x": 150, "y": 65}, {"x": 410, "y": 65}, {"x": 410, "y": 365}]
        li = N.best_label_index(src, dst, bends, nodes, LABEL)
        assert 0 <= li < len(bends)

    def test_avoiding_no_bends_returns_zero(self):
        src = proc("s", 0, 0)
        dst = proc("d", 0, 500)
        assert N.best_label_index_avoiding(src, dst, [], {}, LABEL, [], None, "") == 0


# ── far_side_entry_is_clear ──────────────────────────────────────────

class TestFarSideEntry:
    def test_non_horizontal_side_always_clear(self):
        src = proc("s", 0, 0)
        dst = proc("d", 500, 300)
        nodes = {"s": src, "d": dst}
        assert N.far_side_entry_is_clear(src, dst, nodes, "top", LABEL, 1) is True
        assert N.far_side_entry_is_clear(src, dst, nodes, "bottom", LABEL, 1) is True

    def test_returns_bool_for_horizontal_sides(self):
        src = proc("s", 0, 0)
        dst = proc("d", 500, 300)
        nodes = {"s": src, "d": dst}
        assert isinstance(N.far_side_entry_is_clear(src, dst, nodes, "left", LABEL, 1), bool)
        assert isinstance(N.far_side_entry_is_clear(src, dst, nodes, "right", LABEL, 1), bool)


# ── find_clear_horizontal_lane ───────────────────────────────────────

class TestFindClearLane:
    def test_none_nodes_returns_preferred(self):
        assert N.find_clear_horizontal_lane(None, 0, 100, 50.0, 0.0, 100.0, []) == 50.0

    def test_y_max_le_y_min_returns_preferred(self):
        nodes = {"a": proc("a", 0, 0)}
        assert N.find_clear_horizontal_lane(nodes, 0, 100, 50.0, 100.0, 0.0, []) == 50.0

    def test_finds_clear_lane_away_from_block(self):
        block = proc("block", 50, 45)  # occupies y ~45..175
        nodes = {"block": block}
        # preferred 50 is blocked; should pick a clear y outside the block
        y = N.find_clear_horizontal_lane(nodes, 0, 300, 50.0, 0.0, 300.0, [])
        assert not N.segment_rect((0, y), (300, y), 6.0).intersects(block.rect().inflate(N.PAD))

    def test_returns_closest_clear_lane_when_preferred_outside_range(self):
        # block spans y=150..280; preferred 999 is outside scan range 0..300
        # function returns closest clear lane within range to preferred_y
        # with step=8, candidates are 0,8,16...296; 296,288...136 blocked; 128 clear
        block = proc("block", 150, 150)
        nodes = {"block": block}
        y = N.find_clear_horizontal_lane(nodes, 0, 300, 999.0, 0.0, 300.0, [])
        assert y == 128.0


# ── audit_names_comments ─────────────────────────────────────────────

class TestAuditNamesComments:
    def _nodes(self):
        return {
            "a": N.Node("a", "PROCESSOR", "10 Fetch", 0, 0),
            "b": N.Node("b", "PROCESSOR", "20.00 Build", 0, 220, comments="c"),
            "f": N.Node("f", "FUNNEL", "funnel", 0, 400),
        }

    def test_missing_comments_excludes_funnels(self):
        r = N.audit_names_comments(self._nodes(), [])
        kinds = [k for k, _, _ in r["missing_comments"]]
        assert "PROCESSOR" in kinds
        assert all(k != "FUNNEL" for k in kinds)

    def test_dot00_detected(self):
        r = N.audit_names_comments(self._nodes(), [])
        assert any(name == "20.00 Build" for _, _, name in r["dot00_names"])

    def test_named_connections_reported(self):
        c = N.Conn("c", "a", "b", "PROCESSOR", "PROCESSOR", None, None, "a", "b", ("success",), name="Labeled")
        r = N.audit_names_comments({"a": proc("a"), "b": proc("b")}, [c])
        assert r["named_connections"] == [("c", "Labeled")]

    def test_clean_flow(self):
        r = N.audit_names_comments({"a": proc("a", comments="ok")}, [])
        assert r["missing_comments"] == []
        assert r["named_connections"] == []
        assert r["dot00_names"] == []


# ── route_report ─────────────────────────────────────────────────────

class TestRouteReport:
    def test_clean_aligned_route_has_no_issues(self):
        src = proc("s", 0, 0)
        dst = proc("d", 0, 500)
        c = N.Conn("c", "s", "d", "PROCESSOR", "PROCESSOR", None, None, "s", "d", ("success",))
        issues = N.route_report("root", {"s": src, "d": dst}, [c], {"c": ([], 0)})
        assert issues == []

    def test_crossing_segments_reported(self):
        left = proc("left", 0, 0)
        right = proc("right", 700, 0)
        top = proc("top", 320, -260)
        bottom = proc("bottom", 320, 260)
        nodes = {n.id: n for n in (left, right, top, bottom)}
        h = N.Conn("h", "left", "right", "PROCESSOR", "PROCESSOR", None, None, "left", "right", ("success",))
        v = N.Conn("v", "top", "bottom", "PROCESSOR", "PROCESSOR", None, None, "top", "bottom", ("success",))
        routes = {
            "h": ([{"x": 300.0, "y": left.rect().cy}, {"x": 400.0, "y": right.rect().cy}], 0),
            "v": ([{"x": top.rect().cx, "y": -40.0}, {"x": bottom.rect().cx, "y": 240.0}], 0),
        }
        issues = N.route_report("root", nodes, [h, v], routes)
        assert any(i["type"] == "segments_cross_segment" for i in issues)

    def test_segment_intersects_component_reported(self):
        src = proc("s", 0, 0)
        block = proc("block", 0, 250)
        dst = proc("d", 0, 500)
        nodes = {"s": src, "block": block, "d": dst}
        c = N.Conn("c", "s", "d", "PROCESSOR", "PROCESSOR", None, None, "s", "d", ("success",))
        # route straight through the block
        issues = N.route_report("root", nodes, [c], {"c": ([], 0)})
        assert any(i["type"] == "segment_intersects_component" for i in issues)


# ── infer_topology_blockers ──────────────────────────────────────────

class TestTopologyBlockers:
    def test_no_issues_returns_empty(self):
        assert N.infer_topology_blockers({"a": proc("a")}, [], []) == []

    def test_dense_fanin_output_reported(self):
        nodes = {"main": N.Node("main", "PROCESSOR", "main", 0, 0),
                 "out": N.Node("out", "OUTPUT_PORT", "out", 0, 1000)}
        conns = []
        for i in range(4):
            b = N.Node(f"b{i}", "PROCESSOR", f"b{i}", i * 100, 200)
            nodes[f"b{i}"] = b
            conns.append(N.Conn(f"c{i}", f"b{i}", "out", "PROCESSOR", "OUTPUT_PORT", None, None, f"b{i}", "out", ("success",)))
        blockers = N.infer_topology_blockers(
            nodes, conns, [{"type": "segment_too_close_to_connection_label", "connection": "c0"}]
        )
        assert blockers and blockers[0]["kind"] == "dense_terminal_fanin_requires_topology_decision"
        assert blockers[0]["incoming_connections"] == 4

    def test_sparse_output_not_reported(self):
        nodes = {"main": N.Node("main", "PROCESSOR", "main", 0, 0),
                 "out": N.Node("out", "OUTPUT_PORT", "out", 0, 1000)}
        conns = [N.Conn("c0", "main", "out", "PROCESSOR", "OUTPUT_PORT", None, None, "main", "out", ("success",))]
        assert N.infer_topology_blockers(nodes, conns, [{"type": "segment_too_close_to_connection_label", "connection": "c0"}]) == []


# ── route_connections ────────────────────────────────────────────────

class TestRouteConnections:
    def test_empty_returns_empty(self):
        assert N.route_connections("root", {}, []) == {}

    def test_simple_vertical_chain_is_direct(self):
        a = proc("a", 0, 0)
        b = proc("b", 0, 220)
        c = proc("c", 0, 440)
        nodes = {"a": a, "b": b, "c": c}
        conns = [
            N.Conn("ab", "a", "b", "PROCESSOR", "PROCESSOR", None, None, "a", "b", ("success",)),
            N.Conn("bc", "b", "c", "PROCESSOR", "PROCESSOR", None, None, "b", "c", ("success",)),
        ]
        r = N.route_connections("root", nodes, conns)
        assert r["ab"] == ([], 0)
        assert r["bc"] == ([], 0)

    def test_side_handler_gets_bends(self):
        a = proc("a", 0, 0)
        b = proc("b", 0, 220)
        err = proc("err", 1200, 200, comments="error fallback")
        nodes = {"a": a, "b": b, "err": err}
        conns = [
            N.Conn("ab", "a", "b", "PROCESSOR", "PROCESSOR", None, None, "a", "b", ("success",)),
            N.Conn("aerr", "a", "err", "PROCESSOR", "PROCESSOR", None, None, "a", "err", ("failure",)),
            N.Conn("errb", "err", "b", "PROCESSOR", "PROCESSOR", None, None, "err", "b", ("success",)),
        ]
        r = N.route_connections("root", nodes, conns)
        assert len(r["aerr"][0]) >= 1
        for bends, li in r.values():
            assert isinstance(bends, list) and isinstance(li, int)

    def test_stacked_right_column_blocked_routes_around(self):
        h1 = proc("h1", 1200, 0)
        h2 = proc("h2", 1200, 800)
        mid = proc("mid", 1200, 400)
        nodes = {"h1": h1, "h2": h2, "mid": mid}
        c = N.Conn("c", "h1", "h2", "PROCESSOR", "PROCESSOR", None, None, "h1", "h2", ("success",))
        r = N.route_connections("root", nodes, [c])
        bends, li = r["c"]
        assert len(bends) >= 3
        max_x = max(b["x"] for b in bends)
        assert max_x > 1200 + SIZE["PROCESSOR"][0]


# ── p12_cert_pair ────────────────────────────────────────────────────

class TestP12CertPair:
    def test_no_p12_yields_none(self):
        with N.p12_cert_pair(None, None) as cert:
            assert cert is None

    def test_missing_p12_file_raises(self):
        # A nonexistent p12 path raises inside the context manager.
        raised = False
        try:
            with N.p12_cert_pair("/nonexistent/file.p12", None):
                pass
        except (RuntimeError, FileNotFoundError, OSError):
            raised = True
        assert raised


# ── iter_groups ──────────────────────────────────────────────────────

class _FakeApi:
    def __init__(self, flow):
        self._flow = flow

    def flow(self, gid):
        return self._flow if gid == "root" else {"processGroups": []}


class TestIterGroups:
    def _flow(self):
        return {
            "processGroups": [
                {"component": {"id": "lower", "name": "lower", "position": {"x": 0, "y": 200}}},
                {"component": {"id": "upper", "name": "upper", "position": {"x": 0, "y": 10}}},
            ]
        }

    def test_recursive_default_includes_root(self):
        gids = [g for g, _ in N.iter_groups(_FakeApi(self._flow()), "root", True)]
        assert "root" in gids and "upper" in gids and "lower" in gids

    def test_top_down_order(self):
        gids = [g for g, _ in N.iter_groups(_FakeApi(self._flow()), "root", True, order="top-down")]
        assert gids[:3] == ["root", "upper", "lower"]

    def test_api_order(self):
        gids = [g for g, _ in N.iter_groups(_FakeApi(self._flow()), "root", True, order="api")]
        assert gids[0] == "root"

    def test_not_recursive_only_root(self):
        gids = [g for g, _ in N.iter_groups(_FakeApi(self._flow()), "root", False)]
        assert gids == ["root"]

    def test_exclude_root(self):
        gids = [g for g, _ in N.iter_groups(_FakeApi(self._flow()), "root", True, include_root=False)]
        assert "root" not in gids
        assert "upper" in gids and "lower" in gids


# ── main / CLI ───────────────────────────────────────────────────────

class TestMainCli:
    def test_self_test_mode_prints_ok(self):
        import io
        import contextlib
        import sys as _sys
        buf = io.StringIO()
        old = _sys.argv
        _sys.argv = ["nifi_layout.py", "--mode", "self-test"]
        try:
            with contextlib.redirect_stdout(buf):
                nifi_main()
        finally:
            _sys.argv = old
        assert "self-test ok" in buf.getvalue()

    def test_missing_args_errors(self):
        import sys as _sys
        old = _sys.argv
        _sys.argv = ["nifi_layout.py"]
        try:
            try:
                nifi_main()
            except SystemExit as e:
                assert e.code != 0
            else:
                raise AssertionError("expected SystemExit")
        finally:
            _sys.argv = old


# ── Test runner ──────────────────────────────────────────────────────

def _run_class(cls):
    instance = cls()
    failed = []
    for name in sorted(dir(cls)):
        if not name.startswith("test_"):
            continue
        method = getattr(instance, name)
        try:
            method()
        except Exception as e:  # noqa: BLE001
            failed.append((cls.__name__, name, repr(e)))
    return failed


def main() -> int:
    classes = [
        TestRect,
        TestDataclasses,
        TestConstants,
        TestParsing,
        TestVisualId,
        TestTerminalIsGroupPort,
        TestTextClassification,
        TestStripAndComment,
        TestRelationAndSideHint,
        TestClassifyMain,
        TestTargetLayout,
        TestRectHelpers,
        TestOrthogonalSegment,
        TestPerpendicularCrossPoint,
        TestDistinctRouteSegmentPair,
        TestRoutePoints,
        TestLabelSizing,
        TestEdgeSlots,
        TestSpreadCoord,
        TestTargetSides,
        TestCandidateRoutes,
        TestRouteToSide,
        TestRouteToOutput,
        TestRouteHits,
        TestSameColumnBlocked,
        TestSameColumnAround,
        TestNudgeSegment,
        TestLabelClearanceRect,
        TestRouteCost,
        TestBestLabelIndex,
        TestFarSideEntry,
        TestFindClearLane,
        TestAuditNamesComments,
        TestRouteReport,
        TestTopologyBlockers,
        TestRouteConnections,
        TestP12CertPair,
        TestIterGroups,
        TestMainCli,
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
