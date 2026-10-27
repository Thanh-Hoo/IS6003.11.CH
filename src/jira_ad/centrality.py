"""DFG và độ đo trung tâm (B3), ghép với độ trễ định mức để ra danh sách ưu tiên cải tiến.

- DFG trạng thái: dựng từ status log của cả 161 ca (mô tả, không có bước học); nút `CREATE` là
  đoạn từ lúc tạo đến lần đổi trạng thái đầu.
- DFG activity: **chỉ train** (split V1, seed 42), dùng lại `graph.build_dfg`; bỏ nút biên
  `__START__`/`__END__` khi tính trung tâm vì chúng nối với mọi activity đầu/cuối.
Vòng tự thân (A → A) là lặp lại, không phải kết nối: bỏ khi tính bậc và trung tâm, giữ trong strength.
"""

from __future__ import annotations

import networkx as nx
import pandas as pd

from jira_ad.graph import build_dfg
from jira_ad.splits import make_case_splits
from jira_ad.status_log import CREATED, CohortData

DAY = 86_400.0
CREATE_NODE = "CREATE"
BOUNDARY = ("__START__", "__END__")


def status_dfg(status_log: pd.DataFrame) -> nx.DiGraph:
    """Cạnh A→B = số lần lượt B ngay sau lượt A; `median_wait_days` = dwell (ngày làm việc) của lượt A."""
    g = nx.DiGraph()
    rows = []
    for _, v in status_log.sort_values(["case_id", "visit_index"]).groupby("case_id", sort=False):
        states = [CREATE_NODE if s == CREATED else s for s in v["state"]]
        waits = list(v["dwell_work_s"] / DAY)
        pairs = zip(states, states[1:], waits, v["case_id"], strict=False)  # cặp kề nhau: ngắn hơn 1
        rows += list(pairs)
    edges = pd.DataFrame(rows, columns=["source", "target", "wait", "case_id"])
    for (a, b), e in edges.groupby(["source", "target"], sort=True):
        g.add_edge(a, b, count=len(e), n_cases=e["case_id"].nunique(),
                   median_wait_days=float(e["wait"].median()))
    return g


def activity_dfg_train(cohort: CohortData) -> tuple[nx.DiGraph, set[str]]:
    """DFG activity của tập train V1 (cùng split seed 42, cùng hàm `build_dfg`)."""
    splits = make_case_splits(cohort.traces, cohort.base.split)
    train_ids = set(splits.train_ids)
    train = [t for t in cohort.traces if t.trace_id in train_ids]
    g = build_dfg(train, cohort.base.graph)
    for _, _, data in g.edges(data=True):
        data["count"] = data["weight"]  # build_dfg lưu số lần ở `weight`; centrality đọc `count`
    return g, train_ids


def _undirected(g: nx.DiGraph) -> nx.Graph:
    u = nx.Graph()
    u.add_nodes_from(g.nodes)
    for a, b, data in g.edges(data=True):
        if a == b:
            continue
        w = data.get("count", 1) + (u[a][b]["count"] if u.has_edge(a, b) else 0)
        u.add_edge(a, b, count=w)
    return u


def centrality_table(g: nx.DiGraph, *, pagerank_alpha: float, drop_nodes=()) -> pd.DataFrame:
    """Bậc vào/ra (không tính vòng tự thân), strength theo `count`, betweenness có hướng (tôpô),
    closeness và eigenvector trên bản vô hướng, PageRank có trọng số `count`."""
    g = g.copy()
    g.remove_nodes_from([n for n in drop_nodes if n in g])
    strength_in = dict(g.in_degree(weight="count"))
    strength_out = dict(g.out_degree(weight="count"))
    g.remove_edges_from(list(nx.selfloop_edges(g)))
    und = _undirected(g)
    between = nx.betweenness_centrality(g, normalized=True)
    close = nx.closeness_centrality(und)
    eigen = nx.eigenvector_centrality(und, weight="count", max_iter=10_000, tol=1e-10)
    rank = nx.pagerank(g, alpha=pagerank_alpha, weight="count")
    rows = [{
        "node": n, "in_degree": g.in_degree(n), "out_degree": g.out_degree(n),
        "in_strength": strength_in[n], "out_strength": strength_out[n],
        "betweenness": between[n], "closeness_undirected": close[n],
        "eigenvector_undirected": eigen[n], "pagerank": rank[n],
    } for n in sorted(g.nodes)]
    return pd.DataFrame(rows)


def centrality_vs_delay(centrality: pd.DataFrame, late_state: pd.DataFrame) -> pd.DataFrame:
    """Ghép trung tâm của DFG trạng thái với độ trễ theo trạng thái (`CREATE` ↔ `__CREATED__`)."""
    cent = centrality.assign(state=centrality["node"].replace({CREATE_NODE: CREATED})).drop(columns="node")
    return late_state.merge(cent, on="state", how="left")


def improvement_priorities(
    joined: pd.DataFrame, gates: pd.DataFrame, late: pd.DataFrame, *, top_n_cases: int
) -> pd.DataFrame:
    """Trạng thái xếp theo số ngày vượt định mức (bằng chứng), kèm vai trò cổng và ca ví dụ."""
    top_gate = gates[gates["is_top_human"]].set_index("target_state")
    judged = late[late["is_late"].fillna(False).astype(bool)]
    rows = []
    for _, r in joined[joined["excess_days"] > 0].iterrows():
        examples = judged[judged["state"] == r["state"]].sort_values(
            ["excess_days", "case_id"], ascending=[False, True])["case_id"].head(top_n_cases)
        has_gate = r["state"] in top_gate.index
        rows.append({
            "state": r["state"], "excess_days": r["excess_days"], "share_of_excess": r["share_of_excess"],
            "n_late": r["n_late"], "late_rate": r["late_rate"], "norm_days": r["norm_days"],
            "median_dwell_days": r["median_dwell_days"], "betweenness": r.get("betweenness"),
            "pagerank": r.get("pagerank"),
            "gate_role": top_gate.loc[r["state"], "role"] if has_gate else None,
            "gate_share": top_gate.loc[r["state"], "share_of_target"] if has_gate else None,
            "example_cases": ", ".join(examples),
        })
    out = pd.DataFrame(rows).sort_values(["excess_days", "state"], ascending=[False, True])
    out.insert(0, "rank", range(1, len(out) + 1))
    return out.reset_index(drop=True)
