from __future__ import annotations

from collections import Counter

import networkx as nx
import pytest

from jira_ad.config import WalkConfig
from jira_ad.walks import (
    generate_walks,
    transition_probabilities,
    walk_diagnostics,
    walk_graph,
)


def graph_of(edges):
    graph = nx.DiGraph()
    for source, target, weight in edges:
        graph.add_edge(source, target, weight=weight)
    return graph


def cfg(p=1.0, q=1.0, length=20, walks_per_node=50):
    return WalkConfig(p=p, q=q, length=length, walks_per_node=walks_per_node)


def test_first_step_is_proportional_to_edge_weight():
    graph = graph_of([("v", "a", 1), ("v", "b", 3)])

    probs = transition_probabilities(graph, None, "v", p=0.5, q=4.0)  # p, q không tác động bước đầu

    assert probs == pytest.approx({"a": 0.25, "b": 0.75})


def test_second_order_bias_on_the_undirected_variant_is_p_inverse_one_q_inverse():
    # t-v, v-x, t-x, v-y: quay lại t = 1/p = 0.5, láng giềng của t (x) = 1, ra xa (y) = 1/q = 2
    directed = graph_of([("t", "v", 1), ("v", "x", 1), ("t", "x", 1), ("v", "y", 1)])
    graph = walk_graph(directed, directed=False)

    probs = transition_probabilities(graph, "t", "v", p=2.0, q=0.5)

    total = 0.5 + 1 + 2
    assert probs == pytest.approx({"t": 0.5 / total, "x": 1 / total, "y": 2 / total})


def test_edge_weights_multiply_the_bias():
    directed = graph_of([("t", "v", 1), ("v", "x", 1), ("t", "x", 1), ("v", "y", 1)])
    graph = walk_graph(directed, directed=False)
    graph["v"]["x"]["weight"] = 4
    graph["v"]["y"]["weight"] = 3

    probs = transition_probabilities(graph, "t", "v", p=2.0, q=0.5)

    raw = {"t": 1 * 0.5, "x": 4 * 1.0, "y": 3 * 2.0}
    total = sum(raw.values())
    assert probs == pytest.approx({k: v / total for k, v in raw.items()})


def test_directed_variant_uses_the_x_to_t_edge_and_never_invents_a_return_edge():
    # t->v, v->x, x->t, v->y; KHÔNG có v->t: không được ép xác suất quay lui
    graph = graph_of([("t", "v", 1), ("v", "x", 1), ("x", "t", 1), ("v", "y", 1)])

    probs = transition_probabilities(graph, "t", "v", p=2.0, q=0.5)

    assert set(probs) == {"x", "y"}
    assert probs == pytest.approx({"x": 1 / 3, "y": 2 / 3})  # x->t tồn tại: bias 1; y: 1/q = 2
    assert not graph.has_edge("v", "t")


def test_directed_return_edge_gets_one_over_p_when_it_exists():
    graph = graph_of([("t", "v", 1), ("v", "t", 1), ("v", "y", 1)])

    probs = transition_probabilities(graph, "t", "v", p=4.0, q=1.0)

    assert probs == pytest.approx({"t": 0.25 / 1.25, "y": 1 / 1.25})


def test_p_and_q_equal_one_reduce_to_a_first_order_walk():
    graph = graph_of([("t", "v", 1), ("v", "t", 2), ("v", "x", 5), ("v", "y", 3)])

    second = transition_probabilities(graph, "t", "v", p=1.0, q=1.0)
    first = transition_probabilities(graph, None, "v", p=1.0, q=1.0)

    assert second == pytest.approx(first)


def test_undirected_view_sums_both_directions_and_keeps_one_self_loop():
    directed = graph_of([("a", "b", 2), ("b", "a", 3), ("a", "c", 4), ("c", "c", 5)])

    graph = walk_graph(directed, directed=False)

    assert graph["a"]["b"]["weight"] == 5 and graph["b"]["a"]["weight"] == 5
    assert graph["a"]["c"]["weight"] == 4 and graph["c"]["a"]["weight"] == 4
    assert graph["c"]["c"]["weight"] == 5  # self-loop giữ trọng số cũ, không nhân đôi
    assert walk_graph(directed, directed=True) is directed


def test_every_step_is_an_existing_edge_and_walks_stop_at_sinks():
    graph = graph_of([("s", "a", 2), ("a", "b", 1), ("a", "a", 1), ("b", "e", 1)])  # e là sink

    walks = generate_walks(graph, cfg(p=2.0, q=0.5, length=12, walks_per_node=30), seed=1)

    for walk in walks:
        assert 1 <= len(walk) <= 12
        for source, target in zip(walk, walk[1:], strict=False):
            assert graph.has_edge(source, target)
        if len(walk) < 12:
            assert graph.out_degree(walk[-1]) == 0  # chỉ dừng sớm tại sink
    assert [w for w in walks if w[0] == "e"] == [["e"]] * 30  # walk một token từ sink


def test_walk_counts_follow_the_config_and_all_nodes_start_walks():
    graph = graph_of([("s", "a", 1), ("a", "b", 1), ("b", "e", 1)])

    walks = generate_walks(graph, cfg(walks_per_node=7), seed=3)

    assert len(walks) == 4 * 7
    assert Counter(w[0] for w in walks) == {"s": 7, "a": 7, "b": 7, "e": 7}


def test_walks_are_deterministic_per_seed_and_independent_of_edge_insertion_order():
    edges = [("s", "a", 2), ("s", "b", 1), ("a", "b", 3), ("b", "a", 1), ("a", "e", 1),
             ("b", "e", 2)]
    one = graph_of(edges)
    two = graph_of(list(reversed(edges)))

    assert generate_walks(one, cfg(2.0, 0.5), seed=7) == generate_walks(one, cfg(2.0, 0.5), seed=7)
    assert generate_walks(one, cfg(2.0, 0.5), seed=7) == generate_walks(two, cfg(2.0, 0.5), seed=7)
    assert generate_walks(one, cfg(2.0, 0.5), seed=7) != generate_walks(one, cfg(2.0, 0.5), seed=8)


def test_sampled_frequencies_match_the_second_order_distribution():
    graph = graph_of([("t", "v", 1), ("v", "x", 2), ("x", "t", 1), ("v", "y", 4), ("v", "t", 1)])
    walks = generate_walks(graph, cfg(p=2.0, q=0.5, length=3, walks_per_node=6000), seed=11)

    third = Counter(w[2] for w in walks if w[:2] == ["t", "v"])
    n = sum(third.values())
    raw = {"t": 1 * 0.5, "x": 2 * 1.0, "y": 4 * 2.0}  # t: 1/p; x->t có: 1; y: 1/q
    expected = {k: v / sum(raw.values()) for k, v in raw.items()}

    assert n > 4000
    for node, probability in expected.items():
        assert third[node] / n == pytest.approx(probability, abs=0.025)


def test_weighted_first_step_frequencies_follow_edge_weights():
    graph = graph_of([("v", "a", 1), ("v", "b", 3)])
    walks = generate_walks(graph, cfg(length=2, walks_per_node=8000), seed=5)

    first = Counter(w[1] for w in walks if w[0] == "v" and len(w) == 2)

    assert first["b"] / sum(first.values()) == pytest.approx(0.75, abs=0.02)


def test_diagnostics_count_single_token_walks_and_unreached_nodes():
    graph = graph_of([("s", "a", 1), ("a", "e", 1)])
    walks = generate_walks(graph, cfg(length=5, walks_per_node=4), seed=0)

    d = walk_diagnostics(walks, graph)

    assert d["n_walks"] == 12
    assert d["n_single_token_walks"] == 4  # chỉ walk bắt đầu từ sink e
    assert d["max_walk_length"] == 3
    assert d["n_nodes_without_context"] == 0
    assert d["mean_walk_length"] == pytest.approx((3 * 4 + 2 * 4 + 1 * 4) / 12)


def test_empty_graph_is_rejected():
    with pytest.raises(ValueError, match="rỗng|empty"):
        generate_walks(nx.DiGraph(), cfg(), seed=0)
