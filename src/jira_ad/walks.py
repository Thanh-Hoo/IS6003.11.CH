"""Sampler random walk kiểu Node2Vec có thể kiểm chứng (spec §5.3).

Viết riêng để quan sát được phân phối bước đi; phần tối ưu embedding tái dùng Gensim Skip-gram.
Quy ước proximity cho biến thể có hướng (ghi rõ trong README/test, không ngầm thay bằng
shortest-path vô hướng): sau cạnh `t -> v`, xác suất chọn cạnh ra `v -> x` tỷ lệ với
`w(v, x) * bias(t, x)` với
  - `x == t`                          : `bias = 1/p`  (chỉ khi cạnh `v -> t` thật sự tồn tại)
  - `x != t` và có cạnh `x -> t`      : `bias = 1`
  - còn lại                           : `bias = 1/q`
Không tạo cạnh ngược giả; nút không có cạnh ra thì walk dừng.
"""

from __future__ import annotations

from typing import Any

import networkx as nx
import numpy as np

from jira_ad.config import WalkConfig


def walk_graph(graph: nx.DiGraph, directed: bool) -> nx.DiGraph:
    """Đồ thị dùng để lấy mẫu walk. `directed=False` gộp hai chiều bằng tổng trọng số.

    Biến thể vô hướng (ablation): mỗi cặp {u, v} có trọng số `w(u->v) + w(v->u)` ở cả hai chiều;
    self-loop chỉ giữ một lần với trọng số cũ. Cùng quy tắc proximity áp lên đồ thị này.
    """
    if directed:
        return graph
    merged = nx.DiGraph()
    merged.add_nodes_from(graph.nodes(data=True))
    merged.graph.update(graph.graph)
    for u, v, weight in graph.edges(data="weight", default=1.0):
        if u == v:
            merged.add_edge(u, u, weight=weight)
            continue
        total = weight + (graph[v][u].get("weight", 1.0) if graph.has_edge(v, u) else 0.0)
        merged.add_edge(u, v, weight=total)
        merged.add_edge(v, u, weight=total)
    return merged


def transition_probabilities(
    graph: nx.DiGraph, previous: str | None, node: str, p: float, q: float
) -> dict[str, float]:
    """Phân phối bước kế tiếp từ `node`, có điều kiện nút trước `previous` (None = bước đầu)."""
    successors = sorted(graph.successors(node))  # thứ tự cố định để lấy mẫu tái lập
    weights = []
    for x in successors:
        weight = float(graph[node][x].get("weight", 1.0))
        if previous is not None:
            if x == previous:
                weight *= 1.0 / p
            elif graph.has_edge(x, previous):
                weight *= 1.0
            else:
                weight *= 1.0 / q
        weights.append(weight)
    total = sum(weights)
    return {x: w / total for x, w in zip(successors, weights, strict=True)}


def generate_walks(graph: nx.DiGraph, cfg: WalkConfig, seed: int) -> list[list[str]]:
    """`walks_per_node` walk từ mỗi nút, dài tối đa `length` nút, bằng RNG cục bộ theo `seed`."""
    if graph.number_of_nodes() == 0:
        raise ValueError("Đồ thị rỗng (empty): không có nút để lấy walk")
    rng = np.random.default_rng(seed)
    nodes = sorted(graph.nodes)
    cache: dict[tuple[str | None, str], tuple[list[str], np.ndarray] | None] = {}

    def step_distribution(previous: str | None, node: str):
        key = (previous, node)
        if key not in cache:
            if graph.out_degree(node) == 0:
                cache[key] = None
            else:
                probs = transition_probabilities(graph, previous, node, cfg.p, cfg.q)
                cache[key] = (list(probs), np.fromiter(probs.values(), dtype=float))
        return cache[key]

    walks: list[list[str]] = []
    for _ in range(cfg.walks_per_node):
        for index in rng.permutation(len(nodes)):
            walk = [nodes[index]]
            previous = None
            while len(walk) < cfg.length:
                distribution = step_distribution(previous, walk[-1])
                if distribution is None:
                    break  # sink: walk dừng
                successors, probabilities = distribution
                previous = walk[-1]
                walk.append(successors[int(rng.choice(len(successors), p=probabilities))])
            walks.append(walk)
    return walks


def walk_diagnostics(walks: list[list[str]], graph: nx.DiGraph) -> dict[str, Any]:
    """Thống kê walk; walk một token và nút không có ngữ cảnh không nên được diễn giải mạnh."""
    lengths = [len(w) for w in walks]
    in_context = {node for walk in walks if len(walk) >= 2 for node in walk}
    return {
        "n_walks": len(walks),
        "mean_walk_length": float(np.mean(lengths)) if lengths else 0.0,
        "max_walk_length": max(lengths) if lengths else 0,
        "n_single_token_walks": sum(length == 1 for length in lengths),
        "n_nodes_without_context": sum(node not in in_context for node in graph.nodes),
    }
