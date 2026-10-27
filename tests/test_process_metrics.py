"""Phân tích định lượng (B2): PT/WT/CTE theo khoảng, Little, FPY, chi phí Rejected, vai trò cổng."""

from __future__ import annotations

import math

import pandas as pd
import pytest
from helpers import write_process_project
from test_status_log import ALL_ROWS

from jira_ad.process_config import load_process_config
from jira_ad.process_metrics import (
    dwell_by_state,
    fpy,
    gate_roles,
    kpi_asis,
    little_window,
    pt_wt_ranges,
    rejected_cost,
    time_split,
    weekly_little,
)
from jira_ad.status_log import build_status_log, case_table, load_cohort

H = 3600.0
D = 86_400.0
MAIN = ("In Progress", "In Test")


@pytest.fixture
def built(project):
    cfg = load_process_config(write_process_project(project, ALL_ROWS))
    cohort = load_cohort(cfg, "bug")
    log = build_status_log(cohort.events, cohort.traces, cfg)
    return cfg, log, case_table(log, cohort.traces)


def row(frame, case):
    return frame.set_index("case_id").loc[f"bug:{case}"]


def test_pt_is_time_in_work_states_and_cte_is_pt_over_ct(built):
    cfg, log, _ = built
    split = time_split(log, MAIN, backfill_upper=False, clock="cal", threshold_s=60)
    r = row(split, "TI-1")
    assert r.pt_s == 30 * H and r.wt_s == 26 * H and r.cte == pytest.approx(30 / 56)
    assert (split.pt_s + split.wt_s - split.ct_s).abs().max() < 1e-6


def test_sensitivity_classification_moves_to_investigate_into_work(built):
    _, log, _ = built
    main = time_split(log, MAIN, backfill_upper=False, clock="cal", threshold_s=60)
    sens = time_split(log, ("To Investigate", *MAIN), backfill_upper=False, clock="cal", threshold_s=60)
    assert (sens.pt_s >= main.pt_s).all()


def test_direct_reject_has_zero_pt_and_zero_cte(built):
    _, log, _ = built
    r = row(time_split(log, MAIN, backfill_upper=False, clock="cal", threshold_s=60), "TI-5")
    assert r.pt_s == 0 and r.cte == 0


def test_backfill_upper_counts_the_visit_before_a_burst_through_work_as_work(built):
    _, log, _ = built
    raw = row(time_split(log, MAIN, backfill_upper=False, clock="cal", threshold_s=60), "TI-2")
    upper = row(time_split(log, MAIN, backfill_upper=True, clock="cal", threshold_s=60), "TI-2")
    assert raw.pt_s == 40
    assert upper.pt_s == 48 * H + 40
    # ca không có đợt bù: không đổi
    a = row(time_split(log, MAIN, backfill_upper=False, clock="cal", threshold_s=60), "TI-1")
    b = row(time_split(log, MAIN, backfill_upper=True, clock="cal", threshold_s=60), "TI-1")
    assert a.pt_s == b.pt_s


def test_cte_on_working_clock_is_undefined_when_ct_work_is_zero(built):
    _, log, _ = built
    r = row(time_split(log, MAIN, backfill_upper=False, clock="work", threshold_s=60), "TI-7")
    assert r.ct_s == 0 and math.isnan(r.cte)


def test_pt_wt_ranges_cover_four_variants_and_three_clocks(built):
    cfg, log, _ = built
    ranges = pt_wt_ranges(log, cfg)
    assert set(ranges.variant) == {"main", "main+backfill", "sensitivity", "sensitivity+backfill"}
    assert set(ranges.clock) == {"cal", "work", "work_utc"}
    assert set(ranges.branch) == {"all", "DONE", "Rejected"}
    one = ranges[(ranges.clock == "cal") & (ranges.branch == "all")].set_index("variant")
    assert one.loc["main+backfill", "pt_share"] >= one.loc["main", "pt_share"]
    assert one.loc["main", "n_cte_undefined"] == 0


def test_fpy_strict_and_adjusted():
    log = pd.DataFrame({
        "case_id": ["a", "a", "b", "b", "c", "c", "d"],
        "is_back": [False, True, False, True, False, False, False],
        "is_reopen": [False, False, False, False, False, True, False],
        # Định nghĩa thống nhất (rà soát độc lập I1): lần lùi "trong đợt bù" = lần đổi đó THUỘC một đợt bù
        # (burst_id != -1), kể cả khi nó là lần đổi mở đầu đợt (is_backfill_entry = False).
        "is_backfill_entry": [False, False, False, False, False, False, False],
        "burst_id": [-1, -1, -1, 0, -1, -1, -1],
        "terminal_status": ["DONE", "DONE", "DONE", "DONE", "Rejected", "Rejected", "DONE"],
    })
    out = fpy(log)
    assert out["fpy_strict"] == 0.25          # chỉ d
    assert out["fpy_adjusted"] == 0.5         # b lùi ở lần đổi mở đầu một đợt bù nên được bỏ qua
    assert out["fpy_strict_done"] == pytest.approx(1 / 3)
    assert out["n_cases"] == 4


def test_little_window_identity():
    t0 = pd.Timestamp("2022-01-03", tz="UTC")
    cases = pd.DataFrame({
        "t_create": [t0, t0 + pd.Timedelta(days=2), t0 + pd.Timedelta(days=4)],
        "t_end": [t0 + pd.Timedelta(days=2), t0 + pd.Timedelta(days=6), t0 + pd.Timedelta(days=10)],
    })
    out = little_window(cases)
    assert out["window_days"] == 10 and out["lambda_per_day"] == pytest.approx(0.3)
    assert out["W_days"] == pytest.approx(4.0)
    assert out["L_measured"] == pytest.approx(1.2) == pytest.approx(out["L_little"])


def test_weekly_little_counts_arrivals_completions_and_time_average_wip():
    t0 = pd.Timestamp("2022-01-03", tz="UTC")  # Thứ Hai
    cases = pd.DataFrame({
        "t_create": [t0, t0 + pd.Timedelta(days=3, hours=12)],
        "t_end": [t0 + pd.Timedelta(days=7), t0 + pd.Timedelta(days=8, hours=12)],
        "ct_cal_s": [7 * D, 5 * D],
    })
    weeks = weekly_little(cases).set_index("week_start")
    w1, w2 = weeks.loc[t0], weeks.loc[t0 + pd.Timedelta(days=7)]
    assert (w1.arrivals, w1.completions) == (2, 0)
    assert w1.wip_measured == pytest.approx(1 + 3.5 / 7)
    assert (w2.arrivals, w2.completions) == (0, 2)
    assert w2.wip_measured == pytest.approx(1.5 / 7)
    assert w1.lambda_x_ct == pytest.approx(2 / 7 * 6.0)


def test_dwell_by_state_excludes_open_final_visit(built):
    _, log, _ = built
    table = dwell_by_state(log)
    done = table[(table.state == "DONE") & (table.branch == "all") & (table.clock == "cal")]
    assert done.empty  # trạng thái DONE chỉ là điểm kết thúc, không có dwell
    in_test = table[(table.state == "In Test") & (table.branch == "all") & (table.clock == "cal")].iloc[0]
    assert in_test.n == 4  # TI-1, TI-2, TI-3, TI-8


def test_gate_roles_mark_non_human_and_pick_top_human(built):
    _, log, _ = built
    gates = gate_roles(log)
    assert set(gates.columns) >= {"role", "target_state", "n", "is_human", "is_top_human"}
    triage = gates[gates.target_state == "Triage"]
    assert not triage.is_human.any() and not triage.is_top_human.any()
    done = gates[(gates.target_state == "DONE") & gates.is_top_human]
    assert list(done.role) == ["SQA"]


def test_rejected_cost(built):
    _, _, cases = built
    cost = rejected_cost(cases).set_index("group")
    assert cost.loc["all", "n_cases"] == 4
    assert cost.loc["after_in_progress", "n_cases"] == 0
    # TI-4, TI-5, TI-6, TI-7
    assert cost.loc["all", "issue_days_cal"] == pytest.approx((26 + 12 + 2 + 36) / 24)


def test_kpi_asis_has_measured_rows(built):
    cfg, log, cases = built
    kpi = kpi_asis(log, cases, cfg).set_index("kpi")
    assert kpi.loc["n_cases", "value"] == 8
    assert kpi.loc["share_rejected", "value"] == 0.5
    assert {"ct_cal_median_days", "ct_work_median_days", "pt_share_min", "pt_share_max",
            "fpy_strict", "fpy_adjusted", "backfill_share_of_changes"} <= set(kpi.index)
