"""DFG chỉ từ train, trọng số, xác suất chuyển tiếp làm mượt và diagnostics (spec §5.2).

DFG luôn có hướng: `GraphConfig.directed` chỉ điều khiển cách `walks.py` đọc đồ thị (biến thể vô
hướng cho ablation), không đổi số đếm directly-follows dùng để tính surprisal.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any

import networkx as nx

from jira_ad.config import GraphConfig
from jira_ad.types import Trace

START = "__START__"
END = "__END__"
ROLE_SEPARATOR = "@@"


def trace_tokens(trace: Trace, encoding: str) -> list[str]:
    """Mỗi event thành đúng một token (không tách từ trong tên activity).

    `activity`: token là activity. `activity_role`: `activity@@role`, nên cùng activity khác role
    là hai nút khác nhau (thực nghiệm bổ sung, spec §5.2).
    """
    if encoding == "activity":
        return list(trace.activities)
    if encoding == "activity_role":
        pairs = zip(trace.activities, trace.roles, strict=True)
        return [f"{activity}{ROLE_SEPARATOR}{role}" for activity, role in pairs]
    raise ValueError(f"encoding không hỗ trợ: {encoding!r}")


def trace_transitions(tokens: list[str], add_boundaries: bool) -> list[tuple[str, str]]:
    """Các cặp directly-follows của MỘT trace; không bao giờ nối trace này với trace khác."""
    path = [START, *tokens, END] if add_boundaries else list(tokens)
    return list(zip(path, path[1:], strict=False))


def build_dfg(traces: list[Trace], cfg: GraphConfig) -> nx.DiGraph:
    """DFG có trọng số = số lần directly-follows đếm theo từng trace trong tập `traces` (train).

    Nút activity có thuộc tính `count` (số lần xuất hiện) và `boundary=False`; `__START__` và
    `__END__` (nếu `add_boundaries`) có `boundary=True` và không thuộc `vocabulary`, nên không
    tính vào độ dài hay pooling. Mỗi nút có `out_count` = tổng trọng số cạnh ra. Thứ tự nút và
    cạnh cố định (START, activity theo thứ tự chữ, END) để lấy mẫu walk tái lập được.
    """
    if not traces:
        raise ValueError("Tập train rỗng (empty): không thể dựng DFG")
    node_counts: Counter[str] = Counter()
    edge_counts: Counter[tuple[str, str]] = Counter()
    for trace in traces:
        tokens = trace_tokens(trace, cfg.encoding)
        node_counts.update(tokens)
        edge_counts.update(trace_transitions(tokens, cfg.add_boundaries))
    vocabulary = tuple(sorted(node_counts))

    graph = nx.DiGraph()
    if cfg.add_boundaries:
        graph.add_node(START, count=len(traces), boundary=True)
    for token in vocabulary:
        graph.add_node(token, count=node_counts[token], boundary=False)
    if cfg.add_boundaries:
        graph.add_node(END, count=len(traces), boundary=True)
    for (source, target), weight in sorted(edge_counts.items()):
        graph.add_edge(source, target, weight=weight)
    for node in graph.nodes:
        graph.nodes[node]["out_count"] = sum(w for _, _, w in graph.out_edges(node, data="weight"))
    graph.graph.update(
        vocabulary=vocabulary,
        n_train_traces=len(traces),
        add_boundaries=cfg.add_boundaries,
        encoding=cfg.encoding,
        # số nút đích khả dĩ |V|: activity train (+ __END__); START không bao giờ là đích
        n_targets=len(vocabulary) + (1 if cfg.add_boundaries else 0),
    )
    return graph


@dataclass(frozen=True)
class TransitionInfo:
    surprisal: float
    unseen_source: bool  # nguồn không có trong train hoặc không có cạnh ra
    unseen_transition: bool  # train chưa từng thấy cạnh source -> target


def transition_info(graph: nx.DiGraph, source: str, target: str, alpha: float) -> TransitionInfo:
    """`P(b|a) = (count(a,b)+alpha) / (out(a)+alpha*(|V|+1))`, surprisal = `-ln P`.

    `|V|+1` gồm một nhóm UNK cho đích chưa thấy. Nguồn không biết hoặc không có cạnh ra dùng
    phân phối đều trên `|V|+1` và được gắn cờ. Đây là xác suất thống kê trên DFG train, không phải
    cosine hay điểm của mô hình.
    """
    if not alpha > 0:
        raise ValueError(f"alpha phải > 0, nhận {alpha}")
    size = graph.graph["n_targets"] + 1
    out_count = graph.nodes[source]["out_count"] if source in graph else 0
    if out_count == 0:
        return TransitionInfo(math.log(size), unseen_source=True, unseen_transition=True)
    count = graph[source][target]["weight"] if graph.has_edge(source, target) else 0
    probability = (count + alpha) / (out_count + alpha * size)
    return TransitionInfo(-math.log(probability), unseen_source=False, unseen_transition=count == 0)


def transition_surprisal(graph: nx.DiGraph, source: str, target: str, alpha: float) -> float:
    return transition_info(graph, source, target, alpha).surprisal


def graph_diagnostics(graph: nx.DiGraph) -> dict[str, Any]:
    """Thống kê mô tả DFG đã fit (JSON được), để notebook và kiểm tra đọc lại."""
    activities = list(graph.graph["vocabulary"])
    weights = [w for _, _, w in graph.edges(data="weight")]
    boundary = {START, END}
    successors = {a: [t for t in graph.successors(a)] for a in activities}
    return {
        "n_nodes": graph.number_of_nodes(),
        "n_activity_nodes": len(activities),
        "n_edges": graph.number_of_edges(),
        "n_self_loops": nx.number_of_selfloops(graph),
        "density": nx.density(graph),
        "n_train_traces": graph.graph["n_train_traces"],
        "total_transitions": int(sum(weights)),
        "max_edge_weight": max(weights) if weights else 0,
        "n_activities_with_single_successor": sum(len(s) == 1 for s in successors.values()),
        "n_activities_without_successor": sum(len(s) == 0 for s in successors.values()),
        "n_activities_leading_only_to_end": sum(
            set(s) <= boundary and len(s) > 0 for s in successors.values()
        ),
    }
