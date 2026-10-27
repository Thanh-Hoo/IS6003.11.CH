from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from matplotlib.figure import Figure

from jira_ad import plots

METHODS = ["A_stats", "B_ngrams", "C_embedding", "D_hybrid"]


@pytest.fixture(autouse=True)
def forbid_show(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("plots không được tự gọi plt.show()")

    monkeypatch.setattr(plt, "show", boom)


def assert_labelled(fig: Figure, axes_have_labels: bool = True) -> None:
    assert isinstance(fig, Figure) and fig.axes
    assert any(ax.get_title() for ax in fig.axes) or fig._suptitle is not None
    if axes_have_labels:
        for ax in fig.axes:
            if ax.get_visible() and ax.has_data():
                assert ax.get_xlabel() and ax.get_ylabel(), "mỗi trục phải có nhãn"


def metrics_frame() -> pd.DataFrame:
    rows = [{"method": m, "mutation_type": t, "auroc": 0.5 + 0.02 * i + 0.01 * j,
             "average_precision": 0.5, "paired_win_rate": 0.6, "n_original": 31, "n_mutant": 31}
            for i, m in enumerate(METHODS) for j, t in enumerate(["delete", "duplicate", "swap"])]
    return pd.DataFrame(rows)


def test_histogram_funnel_and_bar_have_titles_and_axis_labels():
    fig = plots.plot_histogram(pd.Series([1, 2, 2, 3, 10, 40]), "Số event", "Phân bố số event", log_x=True)
    assert_labelled(fig)
    funnel = {"n_events_full": 100, "n_events_in_excluded_cases": 5, "n_events_post_terminal": 20,
              "n_events_dropped_noise": 15, "n_events_core": 60}
    assert_labelled(plots.plot_funnel(funnel))


def test_variant_and_status_duration_plots():
    variants = pd.DataFrame({"variant_id": ["V01", "V02", "V03"], "variant": ["A → B", "A → C", "A"],
                             "n_cases": [5, 3, 1], "share": [5 / 9, 3 / 9, 1 / 9], "length": [2, 2, 1]})
    assert_labelled(plots.plot_variant_frequencies(variants, top=2))
    durations = pd.DataFrame({"status": ["To Do"] * 6 + ["In Progress"] * 6,
                              "seconds": [60, 3600, 7200, 86400, 400, 5000, 30, 90, 4000, 9000, 700, 80]})
    assert_labelled(plots.plot_status_durations(durations, min_n=5))


def test_dfg_and_pca_plots_do_not_claim_to_be_a_process_model():
    edges = pd.DataFrame({"source": ["__START__", "A", "B"], "target": ["A", "B", "__END__"],
                          "weight": [5, 4, 3], "probability": [1, 0.8, 0.6], "self_loop": [False] * 3})
    fig = plots.plot_dfg(edges)
    assert isinstance(fig, Figure) and "DFG" in fig.axes[0].get_title()
    assert "BPMN" not in fig.axes[0].get_title()
    coords = pd.DataFrame({"node": list("ABC"), "pc1": [0.0, 1.0, -1.0], "pc2": [0.5, -0.5, 0.0]})
    assert_labelled(plots.plot_pca(coords, [0.6, 0.3]))
    only_a = plots.plot_pca(coords, [0.6, 0.3], label_nodes={"A"})
    assert [t.get_text() for t in only_a.axes[0].texts] == ["A"]


def test_dfg_layout_is_layered_and_nodes_do_not_overlap():
    rows = [("__START__", "CREATE", 9), ("CREATE", "A", 6), ("CREATE", "B", 3), ("A", "C", 4),
            ("A", "D", 2), ("B", "C", 3), ("C", "STATUS_DONE", 7), ("D", "STATUS_DONE", 2),
            ("STATUS_DONE", "__END__", 9), ("A", "A", 2)]
    edges = pd.DataFrame(rows, columns=["source", "target", "weight"])
    edges["probability"], edges["self_loop"] = 0.5, edges.source == edges.target

    positions = plots.dfg_layout(edges)

    assert set(positions) == {n for r in rows for n in r[:2]}
    xs = {n: positions[n][0] for n in positions}
    assert xs["__START__"] < xs["CREATE"] < xs["A"] < xs["C"] < xs["STATUS_DONE"] < xs["__END__"]
    pts = np.array(list(positions.values()))
    gaps = [np.hypot(*(pts[i] - pts[j])) for i in range(len(pts)) for j in range(i)]
    assert min(gaps) > 0.12  # không có hai nút chồng lên nhau


def test_count_axes_use_whole_numbers():
    fig = plots.plot_histogram(pd.Series([1, 2]), "x", "y")  # đếm tối đa 1 ⇒ tick mặc định là số thực
    ticks = fig.axes[0].get_yticks()
    assert all(float(t).is_integer() for t in ticks)


def test_metric_bars_show_the_chance_line_and_sample_size_per_type():
    fig = plots.plot_metric_by_type(metrics_frame(), "auroc", split="test")

    assert_labelled(fig)
    ax = fig.axes[0]
    assert any(abs(line.get_ydata()[0] - 0.5) < 1e-9 for line in ax.lines)  # đường ngẫu nhiên
    assert "AUROC" in ax.get_ylabel() and "test" in ax.get_title()
    texts = " ".join(t.get_text() for t in ax.texts)
    assert "n=31" in texts
    assert ax.get_ylim()[0] <= 0.0 + 1e-9 and ax.get_ylim()[1] >= 1.0 - 1e-9


def test_paired_delta_and_score_distribution_plots():
    rng = np.random.default_rng(0)
    paired = pd.DataFrame([{"method": m, "mutation_type": t, "delta_score": rng.normal(0.01, 0.02)}
                           for m in METHODS for t in ["delete", "swap"] for _ in range(8)])
    assert_labelled(plots.plot_paired_deltas(paired))
    orig = pd.DataFrame({"method": np.repeat(METHODS, 10), "anomaly_score": rng.normal(0.45, 0.03, 40)})
    mut = pd.DataFrame({"method": np.repeat(METHODS, 10), "anomaly_score": rng.normal(0.47, 0.03, 40)})
    fig = plots.plot_score_distributions(orig, mut)
    assert_labelled(fig)
    assert len([ax for ax in fig.axes if ax.has_data()]) == 4
    legend = " ".join(t.get_text() for t in fig.axes[0].get_legend().get_texts())
    assert "n=10" in legend  # cỡ mẫu từng nhóm hiện trong chú giải; vẽ mật độ nên không bị lệch cỡ


def test_case_surprisal_plot_lists_the_transitions_it_was_given():
    transitions = [
        {"position": 3, "source": "A", "target": "B", "surprisal": 4.2, "count": 0,
         "unseen_source": False, "unseen_transition": True},
        {"position": 1, "source": "__START__", "target": "A", "surprisal": 1.1, "count": 40,
         "unseen_source": False, "unseen_transition": False},
    ]

    fig = plots.plot_case_surprisal(transitions, "bug:TI-1")

    assert_labelled(fig)
    assert "bug:TI-1" in fig.axes[0].get_title()
    labels = [t.get_text() for t in fig.axes[0].get_yticklabels()]
    assert any("A → B" in label for label in labels)


def test_ablation_plot_shows_seed_spread_and_the_chance_band():
    rows = [{"experiment": e, "method": m, "mean": 0.5 + 0.01 * i, "std": 0.005}
            for i, e in enumerate(["baseline", "q_half", "dim_32"]) for m in METHODS]
    summary = pd.DataFrame(rows)

    fig = plots.plot_ablation(summary, chance_halfwidth=0.07)

    assert_labelled(fig)
    ax = fig.axes[0]
    assert "AUROC" in ax.get_ylabel() and ax.patches  # dải quanh 0,5 là một patch
    band = ax.patches[0]
    assert band.get_y() == pytest.approx(0.5 - 0.07) and band.get_height() == pytest.approx(0.14)
    assert [t.get_text() for t in ax.get_xticklabels()] == ["baseline", "q_half", "dim_32"]
    legend = [t.get_text() for t in ax.get_legend().get_texts()]
    assert legend == METHODS


def test_runtime_and_coverage_plots():
    summary = pd.DataFrame({"method": METHODS, "fit_seconds": [0.1, 0.1, 0.8, 0.8],
                            "n_features": [10, 442, 33, 42]})
    assert_labelled(plots.plot_runtime(summary))
    cov = pd.DataFrame({"split": ["validation", "test"], "unseen_transition_ratio": [0.05, 0.04],
                        "unseen_node_ratio": [0.0, 0.0]})
    assert_labelled(plots.plot_unseen_coverage(cov))


def test_method_colours_are_fixed_and_distinct():
    colours = [plots.METHOD_COLORS[m] for m in METHODS]
    assert len(set(colours)) == 4


def test_plot_functions_do_not_leave_pyplot_figures_open():
    before = len(plt.get_fignums())
    plots.plot_metric_by_type(metrics_frame(), "auroc", split="test")
    plots.plot_funnel({"n_events_full": 1, "n_events_in_excluded_cases": 0,
                       "n_events_post_terminal": 0, "n_events_dropped_noise": 0, "n_events_core": 1})
    assert len(plt.get_fignums()) == before


# ---- hình ablation phải đọc được khi có nhiều thí nghiệm (kiểm tra bằng mắt ở Task 15 thấy chồng nhãn)


def _render(fig):
    """Ép vẽ thật (canvas.draw() của Figure trần không làm gì) để vị trí nhãn/chú giải được cập nhật."""
    import io

    fig.savefig(io.BytesIO(), format="png")


def _ablation_summary(names, last_extra=None):
    rows = []
    for i, name in enumerate(names):
        for m in METHODS:
            mean = 0.52 + 0.001 * i
            if last_extra is not None and i == len(names) - 1:
                mean = last_extra
            rows.append({"experiment": name, "method": m, "mean": mean, "std": 0.004})
    return pd.DataFrame(rows)


def test_ablation_plot_tick_labels_do_not_overlap_with_many_long_experiment_names():
    names = ["baseline", "undirected_walk", "activity_role_nodes", "q_half", "q_double", "dim_32",
             "cross_fit_5", "dim_4", "dim_8"]

    fig = plots.plot_ablation(_ablation_summary(names), chance_halfwidth=0.03)
    _render(fig)

    boxes = [t.get_window_extent() for t in fig.axes[0].get_xticklabels()]
    assert len(boxes) == len(names)
    for left, right in zip(boxes, boxes[1:], strict=False):
        assert not left.overlaps(right), "nhãn trục x chồng lên nhau"


def test_ablation_plot_band_caption_does_not_sit_on_top_of_a_data_point():
    names = ["baseline", "q_half", "dim_32", "dim_4"]
    halfwidth = 0.07
    fig = plots.plot_ablation(_ablation_summary(names, last_extra=0.5 + halfwidth + 0.004),
                              chance_halfwidth=halfwidth)
    _render(fig)
    ax = fig.axes[0]

    caption = next(t for t in ax.texts if "ngẫu nhiên" in t.get_text())
    box = caption.get_window_extent()
    for line in ax.lines:
        points = ax.transData.transform(np.column_stack([line.get_xdata(), line.get_ydata()]))
        inside = [p for p in points if box.contains(*p)]
        assert not inside, "chú thích dải xám đè lên điểm dữ liệu"


@pytest.mark.parametrize("n_experiments", [3, 9])
def test_ablation_plot_legend_does_not_cover_the_x_axis_label(n_experiments):
    names = ["baseline", "undirected_walk", "activity_role_nodes", "q_half", "q_double", "dim_32",
             "cross_fit_5", "dim_4", "dim_8"][:n_experiments]

    fig = plots.plot_ablation(_ablation_summary(names), chance_halfwidth=0.03)
    _render(fig)
    ax = fig.axes[0]

    legend_box = ax.get_legend().get_window_extent()
    label_box = ax.xaxis.label.get_window_extent()
    assert not legend_box.overlaps(label_box), "chú giải đè lên nhãn trục x"
