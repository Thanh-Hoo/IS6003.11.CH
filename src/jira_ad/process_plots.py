"""Biểu đồ giai đoạn 2 cho notebook 07–12: nhận bảng artifact, trả `Figure` (không qua pyplot).

Quy ước (skill dataviz): một trục y, nét mảnh, lưới nhạt, chữ màu trung tính; màu phân loại theo
thứ tự Okabe–Ito cố định (validator đạt; cam tương phản thấp nên notebook luôn kèm bảng số); độ
lớn dùng một hue từ nhạt đến đậm.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from jira_ad.plots import _figure

CATEGORICAL = ("#0072B2", "#E69F00", "#009E73", "#D55E00")
INK = "#374151"
VARIANT_LABELS = {"main": "Chính", "main+backfill": "Chính + cận trên bù",
                  "sensitivity": "To Investigate là làm",
                  "sensitivity+backfill": "To Investigate là làm + bù"}
BRANCH_LABELS = {"all": "Tất cả", "DONE": "DONE", "Rejected": "Rejected"}
CLOCK_LABELS = {"cal": "ngày lịch", "work": "ngày làm việc", "work_utc": "ngày làm việc (UTC)"}


def _grouped_barh(ax, labels: list[str], series: dict[str, np.ndarray]) -> None:
    height = 0.8 / len(series)
    y = np.arange(len(labels))
    for k, (name, values) in enumerate(series.items()):
        ax.barh(y + (k - (len(series) - 1) / 2) * height, values, height=height * 0.9,
                color=CATEGORICAL[k], label=name)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.grid(axis="x", color="#e5e7eb", linewidth=0.8)
    ax.grid(axis="y", visible=False)
    ax.figure.legend(*ax.get_legend_handles_labels(), frameon=False, loc="outside lower center",
                     ncol=len(series))


def plot_pt_share_ranges(ranges: pd.DataFrame, *, clock: str = "work") -> Figure:
    """Tỉ trọng PT theo bốn biến thể (phân loại × cập nhật bù), tách nhánh."""
    fig, ax = _figure(7.6, 4.2)
    part = ranges[ranges["clock"] == clock]
    variants = [v for v in VARIANT_LABELS if v in set(part["variant"])]
    series = {}
    for branch in [b for b in BRANCH_LABELS if b in set(part["branch"])]:
        sub = part[part["branch"] == branch].set_index("variant")
        series[BRANCH_LABELS[branch]] = np.array([sub.loc[v, "pt_share"] * 100 for v in variants])
    _grouped_barh(ax, [VARIANT_LABELS[v] for v in variants], series)
    ax.set_xlabel(f"Tỉ trọng PT trong CT (%), {CLOCK_LABELS[clock]}")
    ax.set_title("Tỉ trọng PT trong CT theo bốn biến thể giả định", color=INK)
    return fig


def plot_dwell_by_state(dwell: pd.DataFrame, *, clock: str = "work", branch: str = "all") -> Figure:
    """Trung vị, P75, P90 thời gian nằm ở mỗi trạng thái."""
    fig, ax = _figure(7.6, 4.6)
    part = dwell[(dwell["clock"] == clock) & (dwell["branch"] == branch)].sort_values("p90", ascending=False)
    series = {name: part[col].to_numpy(dtype=float) for name, col in
              (("Trung vị", "median"), ("P75", "p75"), ("P90", "p90"))}
    _grouped_barh(ax, list(part["state"]), series)
    ax.set_xlabel(f"Thời gian nằm ở trạng thái ({CLOCK_LABELS[clock]})")
    ax.set_title(f"Dwell theo trạng thái — nhánh {BRANCH_LABELS.get(branch, branch)}", color=INK)
    return fig


def plot_weekly_flow(weeks: pd.DataFrame) -> Figure:
    """WIP đo được theo tuần so với λ_tuần × CT trung bình (cùng đơn vị: số ca)."""
    fig, ax = _figure(8.0, 3.8)
    x = pd.to_datetime(weeks["week_start"])
    ax.plot(x, weeks["wip_measured"], color=CATEGORICAL[0], linewidth=2, label="WIP đo được")
    ax.plot(x, weeks["lambda_x_ct"], color=CATEGORICAL[1], linewidth=2, label="λ tuần × CT trung bình")
    ax.set_ylabel("Số ca")
    ax.set_title("Định luật Little theo tuần", color=INK)
    ax.legend(frameon=False)
    return fig


def plot_gate_roles(gates: pd.DataFrame) -> Figure:
    """Số lần vai trò người chuyển ca vào mỗi trạng thái (bot/unknown/thiếu role bị bỏ)."""
    human = gates[gates["is_human"]]
    table = human.pivot_table(index="role", columns="target_state", values="n", aggfunc="sum", fill_value=0)
    table = table.loc[table.sum(axis=1).sort_values(ascending=False).index]
    fig, ax = _figure(8.4, 0.6 + 0.45 * len(table) + 1.2)
    ax.grid(False)
    image = ax.imshow(table.to_numpy(), cmap="Blues", aspect="auto")
    ax.set_xticks(range(table.shape[1]), table.columns, rotation=35, ha="right")
    ax.set_yticks(range(table.shape[0]), table.index)
    peak = table.to_numpy().max() or 1
    for i in range(table.shape[0]):
        for j in range(table.shape[1]):
            v = table.iat[i, j]
            if v:
                ax.text(j, i, str(v), ha="center", va="center", fontsize=8,
                        color="white" if v > peak * 0.6 else INK)
    fig.colorbar(image, ax=ax, label="Số lần chuyển vào")
    ax.set_title("Vai trò chuyển ca vào trạng thái (vai trò cổng)", color=INK)
    return fig


def plot_excess_days(table: pd.DataFrame, *, key: str, title: str) -> Figure:
    """Ngày làm việc vượt định mức, sắp giảm dần."""
    part = table[table["excess_days"] > 0].sort_values("excess_days", ascending=False)
    fig, ax = _figure(7.2, 0.8 + 0.42 * max(len(part), 1))
    ax.barh(range(len(part)), part["excess_days"], color=CATEGORICAL[0], height=0.7)
    ax.set_yticks(range(len(part)), part[key].astype(str))
    ax.invert_yaxis()
    ax.grid(axis="x", color="#e5e7eb", linewidth=0.8)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Ngày làm việc vượt định mức P75 (tổng)")
    ax.set_title(title, color=INK)
    return fig


def plot_centrality_vs_delay(joined: pd.DataFrame) -> Figure:
    """Betweenness (DFG trạng thái) so với số ngày vượt định mức, gắn nhãn từng trạng thái."""
    # trạng thái không có định mức (quá ít lượt) không có "độ trễ" để so: bỏ khỏi hình
    subset = ["betweenness", "excess_days"] + (["norm_days"] if "norm_days" in joined else [])
    part = joined.dropna(subset=subset)
    fig, ax = _figure(6.8, 4.4)
    ax.scatter(part["betweenness"], part["excess_days"], s=64, color=CATEGORICAL[0],
               edgecolors="white", linewidths=2, zorder=3)
    for r in part.itertuples():
        ax.annotate("CREATE" if r.state == "__CREATED__" else str(r.state), (r.betweenness, r.excess_days),
                    textcoords="offset points",
                    xytext=(6, 4), fontsize=9, color=INK)
    ax.set_xlabel("Betweenness trên DFG trạng thái")
    ax.set_ylabel("Ngày làm việc vượt định mức (tổng)")
    ax.set_title("Vị trí trung gian so với độ trễ", color=INK)
    return fig


QUALITY_LABELS = {"fitness": "Fitness", "precision": "Precision", "generalization": "Generalization",
                  "simplicity": "Simplicity"}


def plot_discovery_quality(table: pd.DataFrame) -> Figure:
    """Bốn chiều chất lượng của từng mô hình khai phá (B5)."""
    fig, ax = _figure(7.6, 0.9 + 0.9 * len(table))
    series = {label: table[col].to_numpy(dtype=float) for col, label in QUALITY_LABELS.items()}
    _grouped_barh(ax, list(table["id"]), series)
    ax.set_xlim(0, 1.0)
    ax.set_xlabel("Giá trị (0–1)")
    ax.set_title("Chất lượng mô hình khai phá trên log trạng thái", color=INK)
    return fig


def plot_flag_summary(summary: pd.DataFrame) -> Figure:
    """Tỉ lệ ca bị gắn từng cờ (kể cả cờ 0 ca: quy trình được tuân thủ ở điểm đó)."""
    part = summary.sort_values("share_cases", ascending=False)
    fig, ax = _figure(7.6, 0.8 + 0.42 * len(part))
    ax.barh(range(len(part)), part["share_cases"] * 100, color=CATEGORICAL[0], height=0.7)
    ax.set_yticks(range(len(part)), part["label"])
    ax.invert_yaxis()
    ax.grid(axis="x", color="#e5e7eb", linewidth=0.8)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Tỉ lệ ca bị gắn cờ (%)")
    ax.set_title("Cờ quy tắc (đếm, không kết luận lỗi)", color=INK)
    return fig


KPI_LABELS = {"ct_work_median_days": "CT trung vị", "ct_work_p90_days": "CT P90",
              "rejected_issue_days_work": "Ngày-issue của ca Rejected",
              "pt_share_main": "Tỉ trọng PT (đo được)",
              "status_changes_per_case": "Số lần đổi trạng thái/ca",
              "conformance_share_fit": "Tỉ lệ ca khớp mô hình",
              "ct_work_median_days_upper": "CT trung vị (cận trên)",
              "rejected_issue_days_work_upper": "Ngày-issue Rejected (cận trên)"}


def plot_kpi_delta(kpi: pd.DataFrame) -> Figure:
    """% thay đổi TO-BE so với AS-IS của từng KPI (khác đơn vị nên chỉ vẽ %; số tuyệt đối ở bảng)."""
    part = kpi.sort_values("delta_pct")
    fig, ax = _figure(7.6, 0.9 + 0.5 * len(part))
    ax.barh(range(len(part)), part["delta_pct"] * 100, color=CATEGORICAL[0], height=0.7)
    ax.axvline(0, color=INK, linewidth=0.8)
    ax.set_yticks(range(len(part)), [KPI_LABELS.get(k, k) for k in part["kpi"]])
    ax.grid(axis="x", color="#e5e7eb", linewidth=0.8)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Thay đổi so với AS-IS (%)")
    ax.set_title("KPI TO-BE: mục tiêu / kịch bản ước tính (không phải kết quả đo)", color=INK)
    return fig


REPRESENTATION_LABELS = {"node2vec_v1": "Node2Vec (run V1)", "structural": "Bậc + trung tâm",
                         "majority_baseline": "Baseline lớp phổ biến"}


def plot_representation_compare(classify: pd.DataFrame) -> Figure:
    """1-NN leave-one-out: biểu diễn nào đặt activity cùng nhóm nghiệp vụ cạnh nhau (có baseline)."""
    fig, ax = _figure(7.6, 3.4)
    series = {"Accuracy": classify["accuracy"].to_numpy(), "Macro-F1": classify["macro_f1"].to_numpy()}
    _grouped_barh(ax, [REPRESENTATION_LABELS.get(r, r) for r in classify["representation"]], series)
    ax.set_xlim(0, 1)
    ax.set_xlabel("Tìm lại nhóm nghiệp vụ của activity (1-NN, leave-one-out)")
    ax.set_title("Node2Vec so với đặc trưng cấu trúc trên cùng bài toán", color=INK)
    return fig


def plot_cluster_scan(clusters: pd.DataFrame, *, metric: str = "nmi") -> Figure:
    """Độ khớp cụm K-means với nhóm nghiệp vụ theo K, mỗi biểu diễn một đường."""
    fig, ax = _figure(6.8, 3.8)
    for k, (name, part) in enumerate(clusters.groupby("representation", sort=True)):
        part = part.sort_values("k")
        ax.plot(part["k"], part[metric], marker="o", markersize=8, linewidth=2, color=CATEGORICAL[k],
                label=REPRESENTATION_LABELS.get(name, name))
    ax.set_xlabel("Số cụm K")
    ax.set_ylabel(metric.upper())
    ax.set_title(f"K-means: {metric.upper()} với nhóm nghiệp vụ", color=INK)
    ax.legend(frameon=False)
    return fig


def plot_exceed_distribution(ranked: pd.DataFrame, *, top_k: int) -> Figure:
    """Số ca theo số chiều vượt p90 trong nhóm (top-k là các ca đứng đầu bảng xếp hạng)."""
    counts = ranked["n_exceed"].value_counts().reindex(range(int(ranked["n_exceed"].max()) + 1), fill_value=0)
    fig, ax = _figure(6.8, 3.6)
    ax.bar(counts.index, counts.to_numpy(), color=CATEGORICAL[0], width=0.7)
    ax.set_xlabel("Số chiều vượt phân vị 90 trong nhóm cùng nhánh × độ dài")
    ax.set_ylabel("Số ca")
    ax.set_title(f"Phân bố hồ sơ bất thường (top {top_k} ca = nên xem trước)", color=INK)
    return fig
