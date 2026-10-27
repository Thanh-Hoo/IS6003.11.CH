"""Hình quy trình bằng Graphviz: nguồn DOT tất định, render PNG/SVG."""

from __future__ import annotations

import shutil

import networkx as nx
import pytest

from jira_ad.process_figures import bpmn_dot, petri_dot, render_dot, status_dfg_dot


def graph() -> nx.DiGraph:
    g = nx.DiGraph()
    g.add_edge("CREATE", "To Do", count=5, median_wait_days=1.25)
    g.add_edge("To Do", "DONE", count=3, median_wait_days=0.5)
    return g


def test_dot_source_labels_edges_with_count_and_wait_and_is_deterministic():
    src = status_dfg_dot(graph(), title="DFG")
    assert '"CREATE" -> "To Do"' in src and "5 lần" in src and "1,2 ngày" in src
    assert src == status_dfg_dot(graph(), title="DFG")


@pytest.mark.skipif(shutil.which("dot") is None, reason="cần Graphviz `dot`")
def test_render_writes_png_and_svg(tmp_path):
    paths = render_dot(status_dfg_dot(graph(), title="DFG"), tmp_path / "dfg")
    assert {p.suffix for p in paths} == {".dot", ".png", ".svg"}
    assert (tmp_path / "dfg.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_petri_dot_is_deterministic_and_marks_invisible_transitions():
    pytest.importorskip("pm4py")
    from jira_ad.conformance import ReferenceModel, reference_net

    model = ReferenceModel.from_strings(("CREATE -> A", "A -> DONE"), start="CREATE", ends=("DONE",))
    net, im, fm = reference_net(model)
    src = petri_dot(net, im, fm, title="Petri net")
    assert src == petri_dot(*reference_net(model), title="Petri net")
    assert 'label="A"' in src and "shape=circle" in src and 'label="τ"' not in src
    assert src.count("fillcolor=black") == 3  # 2 cung + 1 về sink


def test_bpmn_dot_groups_tasks_into_lane_clusters_with_xor_gateways():
    from jira_ad.conformance import ReferenceModel

    model = ReferenceModel.from_strings(("CREATE -> A", "CREATE -> Rejected", "A -> DONE"),
                                        start="CREATE", ends=("DONE", "Rejected"))
    src = bpmn_dot(model, {"A": "Eng"}, title="BPMN")
    assert "subgraph cluster_" in src and 'label="Eng"' in src
    assert "shape=diamond" in src and src.count("shape=diamond") == 1


def test_petri_dot_does_not_depend_on_place_names():
    # pm4py đặt tên place của Alpha bằng repr của set ⇒ thứ tự đổi theo PYTHONHASHSEED.
    pytest.importorskip("pm4py")
    from jira_ad.conformance import ReferenceModel, reference_net

    model = ReferenceModel.from_strings(("CREATE -> A", "CREATE -> B", "A -> DONE", "B -> DONE"),
                                        start="CREATE", ends=("DONE",))
    net, im, fm = reference_net(model)
    before = petri_dot(net, im, fm, title="P")
    for i, place in enumerate(sorted(net.places, key=lambda p: str(p.name), reverse=True)):
        place.name = f"zz_{i}"
    # tên transition ẩn của Heuristics Miner cũng đổi theo thứ tự băm
    for i, tr in enumerate(sorted(net.transitions, key=lambda t: str(t.name), reverse=True)):
        if tr.label is None:
            tr.name = f"hid_{i}"
    assert petri_dot(net, im, fm, title="P") == before
