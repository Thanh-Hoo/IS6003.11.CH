"""Biểu đồ dùng lại cho notebook: nhận DataFrame/đồ thị, trả `matplotlib.figure.Figure`.

Hàm không tự gọi `plt.show()` và không tạo figure trong pyplot (không rò bộ nhớ). Mỗi biểu đồ có
tiêu đề và nhãn trục; dữ liệu để vẽ do người gọi xuất ra bảng khi hình đưa vào kết quả. Màu của
bốn phương pháp cố định (bảng màu Okabe–Ito, an toàn cho người mù màu).
"""

from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator

METHOD_COLORS = {
    "A_stats": "#0072B2",
    "B_ngrams": "#E69F00",
    "C_embedding": "#009E73",
    "D_hybrid": "#D55E00",
    "E_score_fusion": "#CC79A7",
    "F_edge_hybrid": "#56B4E9",
    "M_markov": "#4D4D4D",
}
NEUTRAL = "#6b7280"
ACCENT = "#0072B2"
BOUNDARY_COLOR = "#CC79A7"
METRIC_LABELS = {
    "auroc": "AUROC",
    "average_precision": "Average Precision",
    "paired_win_rate": "Paired win rate",
}
FUNNEL_LABELS = {
    "n_events_full": "Full view",
    "n_events_in_excluded_cases": "Trong ca bị loại",
    "n_events_post_terminal": "Sau terminal cuối",
    "n_events_dropped_noise": "Nhiễu theo policy",
    "n_events_core": "Core view",
}


def _figure(width: float = 7.2, height: float = 4.2) -> tuple[Figure, Axes]:
    fig = Figure(figsize=(width, height), layout="constrained")
    ax = fig.subplots()
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#e5e7eb", linewidth=0.8)
    ax.set_axisbelow(True)
    return fig, ax


def plot_histogram(values: pd.Series, xlabel: str, title: str, bins: int = 30,
                   log_x: bool = False) -> Figure:
    """Histogram một đại lượng (ví dụ số event mỗi issue); `log_x` dùng khoảng chia log."""
    fig, ax = _figure()
    data = pd.Series(values).dropna().to_numpy(dtype=float)
    if log_x and (data > 0).all():
        edges = np.logspace(np.log10(data.min()), np.log10(data.max() + 1e-9), bins + 1)
        ax.set_xscale("log")
    else:
        edges = bins
    ax.hist(data, bins=edges, color=ACCENT, edgecolor="white")
    ax.axvline(float(np.median(data)), color=NEUTRAL, linestyle="--", linewidth=1)
    ax.text(float(np.median(data)), ax.get_ylim()[1] * 0.95, f" trung vị={np.median(data):g}",
            color=NEUTRAL, fontsize=9, va="top")
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Số issue")
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_title(title)
    return fig


def plot_funnel(funnel: dict[str, int], title: str = "Từ full view đến core view (số event)") -> Figure:
    """Phễu số event: full → bị loại theo từng lý do → core (cộng lại bằng full)."""
    fig, ax = _figure(7.2, 3.6)
    keys = [k for k in FUNNEL_LABELS if k in funnel]
    values = [funnel[k] for k in keys]
    colors = [NEUTRAL, "#D55E00", "#D55E00", "#D55E00", ACCENT]
    bars = ax.barh([FUNNEL_LABELS[k] for k in keys], values, color=colors[: len(keys)])
    ax.invert_yaxis()
    total = max(funnel.get("n_events_full", 1), 1)
    for bar, value in zip(bars, values, strict=True):
        ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2,
                f" {value:,} ({value / total:.0%})", va="center", fontsize=9)
    ax.set_xlim(0, max(values) * 1.25)
    ax.set_xlabel("Số event")
    ax.set_ylabel("Giai đoạn")
    ax.set_title(title)
    ax.grid(axis="y", visible=False)
    return fig


def plot_variant_frequencies(variants: pd.DataFrame, top: int = 10) -> Figure:
    """Tần suất các biến thể trace (chuỗi activity giống hệt); thanh gắn mã V01, V02…"""
    fig, ax = _figure(7.2, 3.8)
    part = variants.head(top)
    bars = ax.barh(part["variant_id"], part["n_cases"], color=ACCENT)
    ax.invert_yaxis()
    for bar, share, length in zip(bars, part["share"], part["length"], strict=True):
        ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2,
                f" {share:.1%} · {length} event", va="center", fontsize=9)
    ax.set_xlim(0, part["n_cases"].max() * 1.3)
    ax.set_xlabel("Số issue")
    ax.set_ylabel("Biến thể")
    ax.set_title(f"{len(part)} biến thể trace phổ biến nhất")
    ax.grid(axis="y", visible=False)
    return fig


def plot_status_durations(durations: pd.DataFrame, min_n: int = 5) -> Figure:
    """Thời gian lưu mỗi trạng thái (giờ, thang log) — thời gian lịch, không phải công sức."""
    fig, ax = _figure(7.6, 4.2)
    counts = durations.groupby("status").size()
    statuses = [s for s in counts.sort_values(ascending=False).index if counts[s] >= min_n]
    data = [durations.loc[durations.status == s, "seconds"].clip(lower=1) / 3600 for s in statuses]
    ax.boxplot(data, patch_artist=True, boxprops={"facecolor": "#cfe3f1"},
               medianprops={"color": "#D55E00"})
    ax.set_xticks(range(1, len(statuses) + 1),
                  [f"{s}\n(n={counts[s]})" for s in statuses], fontsize=8)
    ax.set_yscale("log")
    ax.set_xlabel("Trạng thái (từ cập nhật status đến cập nhật status kế tiếp)")
    ax.set_ylabel("Thời gian lưu (giờ, thang log)")
    ax.set_title(f"Thời gian lưu theo trạng thái (chỉ trạng thái có n ≥ {min_n})")
    return fig


def _wrap_label(name: str, width: int = 11) -> str:
    """Gập nhãn activity theo dấu gạch dưới để không đè lên nhãn bên cạnh."""
    name = name.replace("STATUS_", "S:").replace("__START__", "START").replace("__END__", "END")
    lines, current = [], ""
    for token in name.split("_"):
        if current and len(current) + len(token) + 1 > width:
            lines.append(current)
            current = token
        else:
            current = f"{current}_{token}" if current else token
    lines.append(current)
    return "\n".join(lines)


def dfg_layout(edges: pd.DataFrame) -> dict[str, tuple[float, float]]:
    """Vị trí nút theo tầng trái → phải: tầng = khoảng cách ngắn nhất từ `__START__`; `__END__` ở cuối."""
    graph = nx.DiGraph()
    for row in edges.itertuples():
        graph.add_edge(row.source, row.target)
    depth = (nx.single_source_shortest_path_length(graph, "__START__")
             if "__START__" in graph else {})
    last = max(depth.values(), default=0) + 1
    for node in graph:
        graph.nodes[node]["layer"] = depth.get(node, last)
    if "__END__" in graph:
        graph.nodes["__END__"]["layer"] = max(d["layer"] for _, d in graph.nodes(data=True)) + 1
    raw = nx.multipartite_layout(graph, subset_key="layer", align="vertical", scale=1.0)
    return {node: (float(x), float(y)) for node, (x, y) in raw.items()}


def plot_dfg(edges: pd.DataFrame, title: str | None = None) -> Figure:
    """Các cạnh nặng nhất của DFG có hướng, bố cục theo tầng (độ dày ∝ số lần). Không phải BPMN."""
    fig = Figure(figsize=(11.5, 7.2), layout="constrained")
    ax = fig.subplots()
    graph = nx.DiGraph()
    for row in edges.itertuples():
        graph.add_edge(row.source, row.target, weight=row.weight)
    layout = dfg_layout(edges)
    weights = np.array([d["weight"] for _, _, d in graph.edges(data=True)], dtype=float)
    widths = 0.7 + 4.5 * weights / weights.max()
    nx.draw_networkx_edges(graph, layout, width=widths, edge_color="#9ca3af", arrows=True,
                           arrowsize=13, connectionstyle="arc3,rad=0.1", node_size=140, ax=ax)
    colors = [BOUNDARY_COLOR if n.startswith("__") else "#fde68a" if n.startswith("STATUS_")
              else "#cfe3f1" for n in graph.nodes]
    nx.draw_networkx_nodes(graph, layout, node_color=colors, edgecolors=NEUTRAL, node_size=140, ax=ax)
    labels = {n: _wrap_label(n) for n in graph.nodes}
    nx.draw_networkx_labels(graph, {n: (x, y + 0.06) for n, (x, y) in layout.items()},
                            labels=labels, font_size=7, ax=ax, verticalalignment="bottom",
                            bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "none",
                                  "alpha": 0.85})
    ax.margins(0.12)
    ax.set_axis_off()
    ax.set_title(title or f"DFG train: {graph.number_of_edges()} cạnh nặng nhất "
                          "(trái → phải theo khoảng cách từ START; độ dày ∝ số lần; vàng = status)")
    return fig


def plot_pca(
    coords: pd.DataFrame, explained: list[float], title: str | None = None,
    label_nodes: set[str] | None = None,
) -> Figure:
    """Chiếu 2D vector nút bằng PCA — chỉ để minh họa, không dùng để khẳng định hiệu quả.

    `label_nodes` giới hạn các nút được gắn nhãn (mặc định: tất cả) để hình không bị chữ đè nhau.
    """
    fig, ax = _figure(7.4, 5.4)
    ax.grid(axis="x", color="#e5e7eb", linewidth=0.8)
    boundary = coords["node"].str.startswith("__")
    ax.scatter(coords.loc[~boundary, "pc1"], coords.loc[~boundary, "pc2"], color=ACCENT, s=36)
    ax.scatter(coords.loc[boundary, "pc1"], coords.loc[boundary, "pc2"], color=BOUNDARY_COLOR, s=46)
    for row in coords.itertuples():
        if label_nodes is None or row.node in label_nodes:
            ax.annotate(row.node.replace("STATUS_", "S:").replace("__START__", "START")
                        .replace("__END__", "END"), (row.pc1, row.pc2), fontsize=7,
                        xytext=(3, 3), textcoords="offset points")
    ax.set_xlabel(f"PC1 ({explained[0]:.0%} phương sai)")
    ax.set_ylabel(f"PC2 ({explained[1]:.0%} phương sai)")
    ax.set_title(title or "Vector nút Node2Vec (PCA 2D) — minh họa, không phải bằng chứng hiệu quả")
    return fig


def plot_metric_by_type(
    metrics: pd.DataFrame, metric: str = "auroc", split: str = "test", title: str | None = None
) -> Figure:
    """Cột nhóm theo loại mutation, màu theo phương pháp; đường ngẫu nhiên 0,5 và n mỗi loại."""
    fig, ax = _figure(8.0, 4.4)
    types = sorted(metrics["mutation_type"].unique())
    methods = [m for m in METHOD_COLORS if m in set(metrics["method"])]
    width = 0.8 / max(len(methods), 1)
    for i, method in enumerate(methods):
        part = metrics[metrics["method"] == method].set_index("mutation_type").reindex(types)
        xs = np.arange(len(types)) + (i - (len(methods) - 1) / 2) * width
        ax.bar(xs, part[metric].astype(float), width=width * 0.92, color=METHOD_COLORS[method],
               label=method)
    ax.axhline(0.5, color="black", linewidth=1, linestyle="--")
    ax.text(len(types) - 0.5, 0.505, "mức ngẫu nhiên 0,5", ha="right", va="bottom", fontsize=8)
    for x, mutation_type in enumerate(types):
        n = int(metrics.loc[metrics["mutation_type"] == mutation_type, "n_mutant"].max())
        ax.text(x, 1.01, f"n={n}", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(range(len(types)), types)
    ax.set_ylim(0, 1.08)
    ax.set_xlabel("Loại mutation (n = số cặp parent/mutant)")
    ax.set_ylabel(METRIC_LABELS.get(metric, metric))
    ax.set_title(title or f"{METRIC_LABELS.get(metric, metric)} theo loại mutation — split {split}")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=len(methods), frameon=False)
    return fig


def plot_paired_deltas(paired: pd.DataFrame) -> Figure:
    """Phân bố delta_score = điểm mutant − điểm parent, theo loại và phương pháp (0 = không đổi)."""
    fig, ax = _figure(8.4, 4.4)
    types = sorted(paired["mutation_type"].unique())
    methods = [m for m in METHOD_COLORS if m in set(paired["method"])]
    width = 0.8 / max(len(methods), 1)
    for i, method in enumerate(methods):
        for x, mutation_type in enumerate(types):
            values = paired.loc[(paired.method == method) & (paired.mutation_type == mutation_type),
                                "delta_score"].to_numpy(dtype=float)
            if values.size == 0:
                continue
            pos = x + (i - (len(methods) - 1) / 2) * width
            box = ax.boxplot([values], positions=[pos], widths=width * 0.8, patch_artist=True,
                             medianprops={"color": "black"}, manage_ticks=False)
            box["boxes"][0].set(facecolor=METHOD_COLORS[method], alpha=0.8)
    ax.axhline(0, color="black", linewidth=1, linestyle="--")
    ax.set_xticks(range(len(types)), types)
    ax.set_xlabel("Loại mutation")
    ax.set_ylabel("delta_score = điểm mutant − điểm parent")
    ax.set_title("Thay đổi điểm theo từng parent (trên 0: mutant bị chấm khác thường hơn)")
    ax.legend(handles=[Line2D([0], [0], color=METHOD_COLORS[m], lw=6, label=m) for m in methods],
              loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=len(methods), frameon=False)
    return fig


def plot_score_distributions(originals: pd.DataFrame, mutants: pd.DataFrame) -> Figure:
    """Mật độ điểm của trace gốc (đường viền) và mutant (tô màu) theo từng phương pháp (lưới 2×2).

    Dùng mật độ vì số mutant thường nhiều hơn số trace gốc.
    """
    methods = [m for m in METHOD_COLORS if m in set(originals["method"])]
    fig = Figure(figsize=(8.4, 5.6), layout="constrained")
    axes = np.atleast_1d(fig.subplots(2, 2, sharey=False)).ravel()
    for ax, method in zip(axes, methods, strict=False):
        o = originals.loc[originals.method == method, "anomaly_score"]
        m = mutants.loc[mutants.method == method, "anomaly_score"]
        lo, hi = min(o.min(), m.min()), max(o.max(), m.max())
        bins = np.linspace(lo, hi + 1e-9, 16)
        ax.hist(m, bins=bins, density=True, alpha=0.6, color=METHOD_COLORS[method],
                label=f"mutant (n={len(m)})")
        ax.hist(o, bins=bins, density=True, histtype="step", linewidth=2, color="black",
                label=f"trace gốc (n={len(o)})")
        ax.set_title(method)
        ax.set_xlabel("anomaly_score")
        ax.set_ylabel("Mật độ")
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(frameon=False, fontsize=8)
    for ax in axes[len(methods):]:
        ax.set_visible(False)
    fig.suptitle("Phân bố điểm: trace gốc so với mutant (cùng split)")
    return fig


def plot_runtime(summary: pd.DataFrame) -> Figure:
    """Thời gian fit và số chiều đặc trưng của từng phương pháp."""
    fig, ax = _figure(7.0, 3.8)
    colors = [METHOD_COLORS.get(m, NEUTRAL) for m in summary["method"]]
    bars = ax.bar(summary["method"], summary["fit_seconds"], color=colors)
    for bar, n_features in zip(bars, summary["n_features"], strict=True):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{n_features} chiều",
                ha="center", va="bottom", fontsize=9)
    ax.set_xlabel("Phương pháp")
    ax.set_ylabel("Thời gian fit (giây, CPU một luồng)")
    ax.set_title("Chi phí fit và số chiều đặc trưng")
    return fig


def plot_unseen_coverage(coverage: pd.DataFrame) -> Figure:
    """Tỷ lệ chuyển tiếp chưa thấy ở train theo split (độ phủ OOV)."""
    fig, ax = _figure(6.4, 3.8)
    bars = ax.bar(coverage["split"], coverage["unseen_transition_ratio"], color=ACCENT)
    for bar, value in zip(bars, coverage["unseen_transition_ratio"], strict=True):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{value:.3f}", ha="center",
                va="bottom", fontsize=9)
    ax.set_xlabel("Split")
    ax.set_ylabel("Tỷ lệ chuyển tiếp chưa thấy ở train (trung bình)")
    ax.set_title("Độ phủ chuyển tiếp của đồ thị train")
    return fig


def plot_case_surprisal(transitions: list[dict], case_id: str, top: int = 8) -> Figure:
    """Các chuyển tiếp có surprisal cao nhất của một ca; thanh đậm là chuyển tiếp train chưa từng thấy.

    Đây là bằng chứng mô tả hành vi so với đồ thị train, không phải giải thích nhân quả của
    Isolation Forest.
    """
    fig, ax = _figure(7.4, 3.8)
    rows = sorted(transitions, key=lambda r: -r["surprisal"])[:top]
    labels = [f"{r['source']} → {r['target']}".replace("STATUS_", "S:").replace("__START__", "START")
              .replace("__END__", "END") for r in rows]
    colors = [ "#D55E00" if r["unseen_transition"] else ACCENT for r in rows]
    ax.barh(range(len(rows)), [r["surprisal"] for r in rows], color=colors)
    ax.set_yticks(range(len(rows)), labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Surprisal −ln P(đích | nguồn) trên đồ thị train (cam: chuyển tiếp chưa từng thấy)")
    ax.set_ylabel("Chuyển tiếp")
    ax.set_title(f"Chuyển tiếp đáng chú ý của {case_id}")
    ax.grid(axis="y", visible=False)
    return fig


def plot_ablation(
    summary: pd.DataFrame, chance_halfwidth: float | None = None, title: str | None = None
) -> Figure:
    """Macro AUROC theo thí nghiệm và phương pháp (điểm = trung bình, thanh = ±1 std theo model seed).

    `chance_halfwidth` vẽ dải quanh 0,5 mà AUROC trong đó chưa phân biệt được với ngẫu nhiên ở cỡ mẫu
    hiện có. Thanh lỗi chỉ là độ ổn định của bước học, không phải khoảng tin cậy quần thể.
    """
    experiments = list(dict.fromkeys(summary["experiment"]))
    fig, ax = _figure(max(9.0, 1.1 * len(experiments) + 2.0), 4.8)
    methods = [m for m in METHOD_COLORS if m in set(summary["method"])]
    if chance_halfwidth is not None:
        ax.axhspan(0.5 - chance_halfwidth, 0.5 + chance_halfwidth, color="#e5e7eb", zorder=0,
                   label="_nolegend_")
        # Chú thích đặt ở đáy dải (phía trái) để không đè lên điểm dữ liệu, thường nằm trên 0,5.
        ax.text(0.01, 0.5 - chance_halfwidth + 0.002, "vùng chưa phân biệt được với ngẫu nhiên",
                transform=ax.get_yaxis_transform(), ha="left", va="bottom", fontsize=8, color=NEUTRAL)
    ax.axhline(0.5, color="black", linewidth=1, linestyle="--")
    width = 0.7 / max(len(methods), 1)
    for i, method in enumerate(methods):
        part = summary[summary["method"] == method].set_index("experiment").reindex(experiments)
        xs = np.arange(len(experiments)) + (i - (len(methods) - 1) / 2) * width
        ax.errorbar(xs, part["mean"], yerr=part["std"].fillna(0.0), fmt="o", color=METHOD_COLORS[method],
                    capsize=3, label=method)
    ax.set_xticks(range(len(experiments)), experiments, fontsize=8)
    ax.set_xlabel("Thí nghiệm (mỗi thí nghiệm đổi một yếu tố so với baseline)")
    ax.set_ylabel("Macro AUROC (trung bình ± std theo model seed)")
    ax.set_title(title or "Độ nhạy theo thí nghiệm — split test (khám phá, không dùng để chọn cấu hình)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22), ncol=len(methods), frameon=False)
    return fig



def plot_interval_forest(intervals: pd.DataFrame, title: str, chance: float = 0.5) -> Figure:
    """Ước lượng và khoảng tin cậy (`estimate`, `ci_low`, `ci_high`) theo phương pháp; đứt = ngẫu nhiên."""
    part = intervals.reset_index(drop=True)
    fig, ax = _figure(7.2, 0.5 * len(part) + 1.4)
    y = np.arange(len(part))
    for i, row in part.iterrows():
        color = METHOD_COLORS.get(row["method"], NEUTRAL)
        ax.plot([row["ci_low"], row["ci_high"]], [i, i], color=color, linewidth=2.5)
        ax.plot(row["estimate"], i, "o", color=color, markersize=7)
        ax.text(row["ci_high"], i, f"  {row['estimate']:.3f}", va="center", fontsize=9)
    ax.axvline(chance, color=NEUTRAL, linestyle="--", linewidth=1)
    ax.set_yticks(y, part["method"])
    ax.invert_yaxis()
    ax.set_xlabel("AUROC (0,5 = ngẫu nhiên)")
    ax.set_title(title)
    ax.grid(axis="y", visible=False)
    return fig


def plot_auroc_heatmap(intervals: pd.DataFrame, title: str) -> Figure:
    """Bảng màu AUROC theo (phương pháp × loại mutant) với số ghi trong ô; thang màu quanh 0,5."""
    table = intervals.pivot(index="method", columns="scope", values="estimate")
    table = table.reindex([m for m in METHOD_COLORS if m in table.index] or list(table.index))
    fig, ax = _figure(1.4 * table.shape[1] + 3.0, 0.5 * table.shape[0] + 1.6)
    image = ax.imshow(table.to_numpy(dtype=float), cmap="RdBu_r", vmin=0.3, vmax=0.7, aspect="auto")
    for (i, j), value in np.ndenumerate(table.to_numpy(dtype=float)):
        ax.text(j, i, "–" if np.isnan(value) else f"{value:.2f}", ha="center", va="center", fontsize=9)
    ax.set_xticks(range(table.shape[1]), table.columns, rotation=20, ha="right")
    ax.set_yticks(range(table.shape[0]), table.index)
    ax.grid(visible=False)
    fig.colorbar(image, ax=ax, label="AUROC")
    ax.set_title(title)
    return fig
