"""DFG trạng thái, DFG activity train và độ đo trung tâm (B3)."""

from __future__ import annotations

import networkx as nx
import pandas as pd
import pytest
from helpers import write_process_project
from test_status_log import ALL_ROWS

from jira_ad.centrality import (
    activity_dfg_train,
    centrality_table,
    centrality_vs_delay,
    improvement_priorities,
    status_dfg,
)
from jira_ad.process_config import load_process_config
from jira_ad.status_log import load_cohort

D = 86_400.0


def chain() -> nx.DiGraph:
    g = nx.DiGraph()
    for u, v in [("a", "b"), ("b", "c"), ("c", "d")]:
        g.add_edge(u, v, count=1)
    return g


def test_centrality_on_directed_chain_matches_hand_values():
    t = centrality_table(chain(), pagerank_alpha=0.85).set_index("node")
    assert (t.loc["a", "in_degree"], t.loc["a", "out_degree"]) == (0, 1)
    # betweenness có hướng, chuẩn hóa 1/((n-1)(n-2)) = 1/6: b nằm trên a→c, a→d
    assert t.loc["b", "betweenness"] == pytest.approx(2 / 6) == t.loc["c", "betweenness"]
    assert t.loc["a", "betweenness"] == 0
    # closeness bản vô hướng: a có tổng khoảng cách 6 ⇒ 3/6; b có 4 ⇒ 3/4
    assert t.loc["a", "closeness_undirected"] == pytest.approx(0.5)
    assert t.loc["b", "closeness_undirected"] == pytest.approx(0.75)
    assert t["pagerank"].sum() == pytest.approx(1.0)
    assert t.loc["b", "eigenvector_undirected"] == pytest.approx(t.loc["c", "eigenvector_undirected"])
    assert t.loc["b", "eigenvector_undirected"] > t.loc["a", "eigenvector_undirected"]


def test_weighted_strength_uses_counts():
    g = chain()
    g["a"]["b"]["count"] = 5
    t = centrality_table(g, pagerank_alpha=0.85).set_index("node")
    assert t.loc["a", "out_strength"] == 5 and t.loc["b", "in_strength"] == 5


def test_status_dfg_counts_consecutive_visits_and_median_wait():
    log = pd.DataFrame({
        "case_id": ["x", "x", "x", "y", "y", "y"], "visit_index": [0, 1, 2, 0, 1, 2],
        "state": ["__CREATED__", "To Do", "DONE", "__CREATED__", "To Do", "Rejected"],
        "dwell_work_s": [1 * D, 2 * D, None, 3 * D, 4 * D, None],
    })
    g = status_dfg(log)
    assert set(g.nodes) == {"CREATE", "To Do", "DONE", "Rejected"}
    assert g["CREATE"]["To Do"]["count"] == 2
    assert g["CREATE"]["To Do"]["median_wait_days"] == pytest.approx(2.0)
    assert g["To Do"]["DONE"]["count"] == 1 and g["To Do"]["Rejected"]["median_wait_days"] == 4.0


def test_activity_dfg_uses_train_cases_only(project):
    cfg = load_process_config(write_process_project(project, ALL_ROWS))
    cohort = load_cohort(cfg, "bug")
    g, train_ids = activity_dfg_train(cohort)
    assert 0 < len(train_ids) < len(cohort.traces)
    train_tokens = {a for t in cohort.traces if t.trace_id in train_ids for a in t.activities}
    assert {n for n in g.nodes if not n.startswith("__")} == train_tokens


def test_centrality_vs_delay_and_priorities_rank_by_excess():
    cent = pd.DataFrame({"node": ["A", "B", "CREATE"], "betweenness": [0.1, 0.5, 0.0],
                         "pagerank": [0.3, 0.4, 0.3]})
    late_state = pd.DataFrame({"state": ["A", "B", "__CREATED__"], "excess_days": [10.0, 30.0, 5.0],
                               "n_late": [2, 3, 1], "late_rate": [0.2, 0.3, 0.1],
                               "median_dwell_days": [1.0, 2.0, 0.5], "share_of_excess": [0.2, 0.7, 0.1],
                               "norm_days": [3.0, 4.0, 1.0]})
    joined = centrality_vs_delay(cent, late_state).set_index("state")
    assert joined.loc["__CREATED__", "betweenness"] == 0.0  # CREATE ↔ __CREATED__
    gates = pd.DataFrame({"target_state": ["A", "B"], "role": ["PO", "Eng"], "is_top_human": [True, True],
                          "share_of_target": [0.9, 0.5]})
    late = pd.DataFrame({"state": ["B", "B", "A"], "case_id": ["k1", "k2", "k3"],
                         "excess_days": [20.0, 10.0, 10.0], "is_late": [True, True, True]})
    pri = improvement_priorities(joined.reset_index(), gates, late, top_n_cases=1)
    assert list(pri.state[:2]) == ["B", "A"]
    assert pri.set_index("state").loc["B", "example_cases"] == "k1"
    assert pri.set_index("state").loc["B", "gate_role"] == "Eng"


def test_activity_dfg_centrality_is_weighted_by_transition_counts(project):
    # build_dfg lưu số lần ở thuộc tính `weight`; centrality phải dùng đúng số lần đó.
    cfg = load_process_config(write_process_project(project, ALL_ROWS))
    g, _ = activity_dfg_train(load_cohort(cfg, "bug"))
    t = centrality_table(g, pagerank_alpha=0.85).set_index("node")
    expected = sum(d["weight"] for _, _, d in g.in_edges("CREATE", data=True))
    assert expected > 1 and t.loc["CREATE", "in_strength"] == expected
