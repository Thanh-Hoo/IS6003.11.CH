"""Biểu đồ giai đoạn 2: nhận bảng artifact, trả Figure (không pyplot), một trục y, có nhãn."""

from __future__ import annotations

import pandas as pd
from matplotlib.figure import Figure

from jira_ad.process_plots import (
    plot_centrality_vs_delay,
    plot_dwell_by_state,
    plot_excess_days,
    plot_gate_roles,
    plot_pt_share_ranges,
    plot_weekly_flow,
)


def test_pt_share_ranges_one_bar_per_variant_and_branch():
    rows = [{"variant": v, "clock": "work", "branch": b, "pt_share": 0.1 * (i + 1)}
            for i, v in enumerate(["main", "main+backfill", "sensitivity", "sensitivity+backfill"])
            for b in ("all", "DONE", "Rejected")]
    fig = plot_pt_share_ranges(pd.DataFrame(rows), clock="work")
    ax = fig.axes[0]
    assert isinstance(fig, Figure) and len(fig.axes) == 1
    assert len(ax.patches) == 12 and "%" in ax.get_xlabel()
    assert len(fig.legends) == 1


def test_dwell_by_state_plots_median_p75_p90_for_chosen_clock():
    rows = [{"state": s, "branch": "all", "clock": c, "median": 1.0, "p75": 2.0, "p90": 3.0, "n": 5}
            for s in ("To Do", "In Test") for c in ("cal", "work")]
    fig = plot_dwell_by_state(pd.DataFrame(rows), clock="work", branch="all")
    ax = fig.axes[0]
    assert len(ax.patches) == 6 and "ngày làm việc" in ax.get_xlabel()


def test_weekly_flow_draws_measured_wip_and_lambda_x_ct_on_one_axis():
    weeks = pd.DataFrame({"week_start": pd.date_range("2022-01-03", periods=4, freq="7D", tz="UTC"),
                          "wip_measured": [1, 2, 3, 2], "lambda_x_ct": [1.5, 1.5, 2.5, 2.0]})
    fig = plot_weekly_flow(weeks)
    assert len(fig.axes) == 1 and len(fig.axes[0].lines) == 2


def test_gate_roles_heatmap_uses_human_roles_only():
    gates = pd.DataFrame({"target_state": ["To Do", "To Do", "DONE"], "role": ["PO", "bot", "SQA"],
                          "n": [5, 9, 3], "is_human": [True, False, True]})
    fig = plot_gate_roles(gates)
    labels = [t.get_text() for t in fig.axes[0].get_yticklabels()]
    assert labels == ["PO", "SQA"]


def test_excess_days_bars_sorted_descending():
    table = pd.DataFrame({"state": ["A", "B", "C"], "excess_days": [5.0, 20.0, 1.0]})
    fig = plot_excess_days(table, key="state", title="t")
    labels = [t.get_text() for t in fig.axes[0].get_yticklabels()]
    assert labels == ["B", "A", "C"]


def test_centrality_vs_delay_labels_points():
    joined = pd.DataFrame({"state": ["A", "B"], "betweenness": [0.1, 0.4], "excess_days": [3.0, 9.0]})
    fig = plot_centrality_vs_delay(joined)
    texts = [t.get_text() for t in fig.axes[0].texts]
    assert texts == ["A", "B"]


def test_grouped_bar_legend_sits_outside_the_plot_area():
    rows = [{"variant": "main", "clock": "work", "branch": b, "pt_share": 0.5} for b in ("all", "DONE")]
    fig = plot_pt_share_ranges(pd.DataFrame(rows), clock="work")
    assert fig.axes[0].get_legend() is None and len(fig.legends) == 1


def test_centrality_vs_delay_skips_states_without_norm_and_renames_created():
    joined = pd.DataFrame({"state": ["__CREATED__", "DONE", "B"], "betweenness": [0.0, 0.0, 0.4],
                           "excess_days": [3.0, 0.0, 9.0], "norm_days": [1.0, float("nan"), 2.0]})
    texts = [t.get_text() for t in plot_centrality_vs_delay(joined).axes[0].texts]
    assert texts == ["CREATE", "B"]


def test_discovery_quality_grouped_by_miner_and_metric():
    from jira_ad.process_plots import plot_discovery_quality

    table = pd.DataFrame({"id": ["alpha", "inductive"], "fitness": [0.6, 1.0], "precision": [0.4, 0.5],
                          "generalization": [0.7, 0.8], "simplicity": [0.4, 0.6]})
    ax = plot_discovery_quality(table).axes[0]
    assert len(ax.patches) == 8 and [t.get_text() for t in ax.get_yticklabels()] == ["alpha", "inductive"]


def test_flag_summary_bars_show_share_of_cases_including_zero_flags():
    from jira_ad.process_plots import plot_flag_summary

    summary = pd.DataFrame({"label": ["A", "B", "C"], "share_cases": [0.2, 0.0, 0.5]})
    ax = plot_flag_summary(summary).axes[0]
    assert [t.get_text() for t in ax.get_yticklabels()] == ["C", "A", "B"] and "%" in ax.get_xlabel()


def test_kpi_delta_plots_percent_change_on_one_axis_and_says_target():
    from jira_ad.process_plots import plot_kpi_delta

    kpi = pd.DataFrame({"kpi": ["a", "b"], "delta_pct": [-0.5, 0.2]})
    fig = plot_kpi_delta(kpi)
    ax = fig.axes[0]
    assert len(fig.axes) == 1 and len(ax.patches) == 2 and "%" in ax.get_xlabel()
    assert "mục tiêu" in ax.get_title()


def test_representation_compare_shows_baseline_and_both_metrics():
    from jira_ad.process_plots import plot_representation_compare

    classify = pd.DataFrame({"representation": ["node2vec_v1", "structural", "majority_baseline"],
                             "accuracy": [0.45, 0.29, 0.25], "macro_f1": [0.35, 0.2, 0.05]})
    ax = plot_representation_compare(classify).axes[0]
    assert len(ax.patches) == 6 and len(ax.get_yticklabels()) == 3


def test_cluster_scan_plot_one_line_per_representation():
    from jira_ad.process_plots import plot_cluster_scan

    clusters = pd.DataFrame({"k": [2, 3, 2, 3], "nmi": [0.1, 0.3, 0.1, 0.2],
                             "representation": ["node2vec_v1"] * 2 + ["structural"] * 2})
    fig = plot_cluster_scan(clusters, metric="nmi")
    assert len(fig.axes) == 1 and len(fig.axes[0].lines) == 2


def test_exceed_distribution_counts_cases():
    from jira_ad.process_plots import plot_exceed_distribution

    ranked = pd.DataFrame({"n_exceed": [0, 0, 1, 3]})
    ax = plot_exceed_distribution(ranked, top_k=1).axes[0]
    assert [round(p.get_height()) for p in ax.patches] == [2, 1, 0, 1]
