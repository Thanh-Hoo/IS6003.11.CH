from __future__ import annotations

import math

import pytest

from jira_ad.config import GraphConfig
from jira_ad.graph import (
    END,
    START,
    build_dfg,
    graph_diagnostics,
    trace_tokens,
    trace_transitions,
    transition_info,
    transition_surprisal,
)

CFG = GraphConfig(directed=True, encoding="activity", add_boundaries=True, transition_alpha=1.0)
NO_BOUNDARY = GraphConfig(directed=True, encoding="activity", add_boundaries=False,
                          transition_alpha=1.0)
ROLE_CFG = GraphConfig(directed=True, encoding="activity_role", add_boundaries=True,
                       transition_alpha=1.0)


@pytest.fixture
def two_traces(trace_of):
    return [trace_of("t1", ["A", "B"]), trace_of("t2", ["A", "C"])]


def weights(graph):
    return {(u, v): d["weight"] for u, v, d in graph.edges(data=True)}


def test_directly_follows_is_counted_per_trace_and_never_bridges_traces(two_traces):
    graph = build_dfg(two_traces, CFG)

    assert weights(graph) == {
        (START, "A"): 2, ("A", "B"): 1, ("A", "C"): 1, ("B", END): 1, ("C", END): 1,
    }
    assert not graph.has_edge("B", "A") and not graph.has_edge("C", "A")  # không nối cuối->đầu
    assert not graph.has_edge(END, START)


def test_boundaries_can_be_switched_off(two_traces):
    graph = build_dfg(two_traces, NO_BOUNDARY)

    assert weights(graph) == {("A", "B"): 1, ("A", "C"): 1}
    assert START not in graph and END not in graph


def test_self_loops_and_repeated_transitions_are_kept_and_accumulate(trace_of):
    graph = build_dfg([trace_of("t1", ["A", "A", "B"]), trace_of("t2", ["A", "B", "A", "B"])], CFG)

    assert graph["A"]["A"]["weight"] == 1
    assert graph["A"]["B"]["weight"] == 3
    assert graph["B"]["A"]["weight"] == 1


def test_node_counts_exclude_boundaries_from_activity_totals(two_traces):
    graph = build_dfg(two_traces, CFG)

    assert graph.nodes["A"]["count"] == 2 and graph.nodes["B"]["count"] == 1
    assert graph.nodes[START]["boundary"] is True and graph.nodes["A"]["boundary"] is False
    assert graph.graph["vocabulary"] == ("A", "B", "C")


def test_surprisal_follows_the_smoothing_formula(two_traces):
    graph = build_dfg(two_traces, CFG)
    # V = {A, B, C, END} nên |V| + 1 = 5; out(A) = 2; count(A,B) = 1; alpha = 1
    assert transition_surprisal(graph, "A", "B", 1.0) == pytest.approx(-math.log(2 / 7))
    # out(START) = 2; count(START, A) = 2
    assert transition_surprisal(graph, START, "A", 1.0) == pytest.approx(-math.log(3 / 7))
    assert transition_surprisal(graph, "A", "B", 0.5) == pytest.approx(-math.log(1.5 / 4.5))


def test_unseen_target_from_a_known_source_uses_the_unk_mass(two_traces):
    graph = build_dfg(two_traces, CFG)

    info = transition_info(graph, "A", "NEVER_SEEN", 1.0)

    assert info.surprisal == pytest.approx(-math.log(1 / 7))
    assert info.unseen_transition is True and info.unseen_source is False
    # đích đã biết nhưng chưa có cạnh cũng là chuyển tiếp chưa thấy
    assert transition_info(graph, "B", "C", 1.0).unseen_transition is True


def test_unknown_source_and_source_without_outgoing_edges_are_uniform(two_traces):
    graph = build_dfg(two_traces, CFG)

    for source in ("NEVER_SEEN", END):
        info = transition_info(graph, source, "A", 1.0)
        assert info.surprisal == pytest.approx(math.log(5))
        assert info.unseen_source is True and info.unseen_transition is True


def test_distribution_over_targets_plus_unk_sums_to_one(two_traces):
    graph = build_dfg(two_traces, CFG)

    for source in (START, "A", "B", "C"):
        targets = [n for n in graph.nodes if n != START] + ["__UNK_GROUP__"]
        total = sum(math.exp(-transition_surprisal(graph, source, t, 1.0)) for t in targets)
        assert total == pytest.approx(1.0)


def test_alpha_must_be_positive(two_traces):
    graph = build_dfg(two_traces, CFG)

    with pytest.raises(ValueError, match="alpha"):
        transition_surprisal(graph, "A", "B", 0.0)


def test_empty_training_set_is_rejected():
    with pytest.raises(ValueError, match="rỗng|empty"):
        build_dfg([], CFG)


def test_activity_role_encoding_separates_nodes_by_role(trace_of):
    trace = trace_of("t1", ["A", "A"], roles=["PO", "Eng"])

    assert trace_tokens(trace, "activity") == ["A", "A"]
    tokens = trace_tokens(trace, "activity_role")
    assert tokens[0] != tokens[1]
    graph = build_dfg([trace], ROLE_CFG)
    assert len(graph.graph["vocabulary"]) == 2


def test_transitions_include_boundaries_only_when_enabled():
    assert trace_transitions(["A", "B"], True) == [(START, "A"), ("A", "B"), ("B", END)]
    assert trace_transitions(["A", "B"], False) == [("A", "B")]
    assert trace_transitions(["A"], False) == []


def test_diagnostics_describe_the_fitted_graph(trace_of):
    graph = build_dfg([trace_of("t1", ["A", "A", "B"]), trace_of("t2", ["C"])], CFG)

    d = graph_diagnostics(graph)

    assert d["n_activity_nodes"] == 3
    assert d["n_edges"] == 6  # START->A, A->A, A->B, B->END, START->C, C->END
    assert d["n_self_loops"] == 1
    assert d["n_train_traces"] == 2
    assert d["total_transitions"] == 6
    assert d["n_activities_with_single_successor"] >= 1
