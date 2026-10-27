"""BPR (B2 heuristics, B4): kiểm chứng ứng viên theo ngưỡng khóa trước, what-if tính lại trên log."""

from __future__ import annotations

import pandas as pd
import pytest

from jira_ad.bpr import (
    INSUFFICIENT,
    REJECT,
    SUPPORT,
    check_auto_transition,
    check_duplicate,
    check_early_triage,
    check_fast_track,
    check_investigating_state,
    check_merge,
    check_role_dependency,
    kpi_asis_tobe,
    whatif_auto_transition,
    whatif_cap_state,
    whatif_early_triage,
    whatif_merge,
)

D = 86_400.0
T0 = pd.Timestamp("2022-06-13T08:00:00", tz="UTC")


def visits(case, terminal, states, days, roles=None):
    """Lượt trạng thái liên tiếp từ T0; `days` = dwell (ngày) của mọi lượt trừ lượt cuối."""
    rows, t = [], T0
    for i, s in enumerate(states):
        dwell = days[i] * D if i < len(days) else None
        rows.append({"case_id": case, "terminal_status": terminal, "visit_index": i, "state": s, "t_enter": t,
                     "dwell_work_s": dwell, "dwell_cal_s": dwell,
                     "exit_role": None if dwell is None else (roles[i] if roles else "PO")})
        if dwell is not None:
            t = t + pd.Timedelta(seconds=dwell)
    return rows


def frame(*cases):
    return pd.DataFrame([r for c in cases for r in c])


def cases_of(log):
    g = log.groupby("case_id")
    return pd.DataFrame({"case_id": list(g.groups),
                         "terminal_status": g["terminal_status"].first().to_numpy(),
                         "ct_work_s": g["dwell_work_s"].sum().to_numpy()})


# ----------------------------------------------------------------------------- kiểm chứng


def test_early_triage_supported_when_rejected_cases_take_a_large_share_of_time():
    log = frame(visits("r1", "Rejected", ["__CREATED__", "To Investigate", "Rejected"], [1, 9]),
                visits("r2", "Rejected", ["__CREATED__", "To Investigate", "Rejected"], [2, 18]),
                visits("d1", "DONE", ["__CREATED__", "In Progress", "DONE"], [1, 9]),
                visits("d2", "DONE", ["__CREATED__", "In Progress", "DONE"], [1, 9]))
    out = check_early_triage(cases_of(log), log, min_share=0.2, min_median_days=5)
    assert out["verdict"] == SUPPORT and out["value"] == pytest.approx(30 / 50)
    assert check_early_triage(cases_of(log), log, min_share=0.7, min_median_days=5)["verdict"] == REJECT
    w = whatif_early_triage(cases_of(log), log)
    assert w["asis_rejected_issue_days"] == pytest.approx(30)
    assert w["tobe_rejected_issue_days"] == pytest.approx(3)


def test_auto_transition_counts_commits_linked_before_in_progress():
    log = frame(visits("a", "DONE", ["__CREATED__", "To Do", "In Progress", "DONE"], [1, 5, 2]),
                visits("b", "DONE", ["__CREATED__", "To Do", "In Progress", "DONE"], [1, 5, 2]))
    events = pd.DataFrame({"case_id": ["a", "b"], "activity": ["LINK_COMMIT", "LINK_MERGE_REQUEST"],
                           "timestamp_utc": [T0 + pd.Timedelta(days=3), T0 + pd.Timedelta(days=7)]})
    out = check_auto_transition(log, events, min_share=0.3)
    assert out["verdict"] == SUPPORT and out["value"] == pytest.approx(0.5)
    w = whatif_auto_transition(log, events, work_states=("In Progress", "In Test"))
    assert w["n_cases_changed"] == 1
    assert w["pt_share_tobe"] - w["pt_share_asis"] == pytest.approx(3 / 16)  # 3 ngày To Do thành làm


def test_merge_supported_when_most_transitions_pass_through():
    log = frame(*[visits(c, "DONE", ["__CREATED__", "INVESTIGATED", "To Do", "DONE"], [1, d, 1])
                  for c, d in (("a", 0.5), ("b", 0.2), ("c", 3.0))])
    out = check_merge(log, source="INVESTIGATED", target="To Do", max_days=1, min_share=0.5)
    assert out["verdict"] == SUPPORT and out["value"] == pytest.approx(2 / 3)
    w = whatif_merge(log, source="INVESTIGATED", target="To Do")
    assert w["changes_per_case_asis"] == pytest.approx(3) and w["changes_per_case_tobe"] == pytest.approx(2)


def test_role_dependency_uses_exit_role_and_bootstrap_interval():
    longer = [visits(f"p{i}", "DONE", ["__CREATED__", "To Do", "DONE"], [1, 10 + i], ["SQA", "PO"])
              for i in range(8)]
    shorter = [visits(f"e{i}", "DONE", ["__CREATED__", "To Do", "DONE"], [1, 1 + i * 0.1], ["SQA", "Eng"])
               for i in range(8)]
    bots = [visits("b0", "DONE", ["__CREATED__", "To Do", "DONE"], [1, 99], ["SQA", "bot"])]
    out = check_role_dependency(frame(*longer, *shorter, *bots), state="To Do", role="PO", n_boot=500, seed=1)
    assert out["verdict"] == SUPPORT and out["ci_low"] > 0
    same = [visits(f"q{i}", "DONE", ["__CREATED__", "To Do", "DONE"], [1, 1 + i * 0.1], ["SQA", r])
            for i in range(8) for r in ("PO", "Eng")]
    out = check_role_dependency(frame(*same), state="To Do", role="PO", n_boot=500, seed=1)
    assert out["verdict"] == REJECT


def test_duplicate_check_needs_enough_cases():
    events = pd.DataFrame({"case_id": ["r1", "r2"], "raw_action": ["add link to duplicates"] * 2})
    cases = pd.DataFrame({"case_id": ["r1", "r2"], "terminal_status": ["Rejected"] * 2,
                          "ct_work_s": [10 * D, 12 * D]})
    out = check_duplicate(events, cases, pattern="link to duplicates", min_cases=5, min_median_days=5)
    assert out["verdict"] == INSUFFICIENT
    out = check_duplicate(events, cases, pattern="link to duplicates", min_cases=2, min_median_days=5)
    assert out["verdict"] == SUPPORT and out["value"] == pytest.approx(11)
    assert "trung vị 11,0 ngày" in out["evidence"]


def test_investigating_state_supported_when_pt_range_is_driven_by_to_investigate():
    ranges = pd.DataFrame({"variant": ["main", "main+backfill", "sensitivity", "sensitivity+backfill"],
                           "clock": "work", "branch": "all", "pt_share": [0.17, 0.27, 0.57, 0.59]})
    assert check_investigating_state(ranges, min_width_pp=10)["verdict"] == SUPPORT
    flat = ranges.assign(pt_share=[0.28, 0.32, 0.28, 0.32])
    assert check_investigating_state(flat, min_width_pp=10)["verdict"] == REJECT


def test_fast_track_supported_when_skipping_is_not_slower_or_less_clean():
    cases = pd.DataFrame({"case_id": list("abcd"), "terminal_status": ["DONE"] * 4,
                          "ct_work_s": [5 * D, 6 * D, 20 * D, 30 * D], "n_back": [0, 0, 0, 1], "n_reopen": 0})
    flags = pd.DataFrame({"case_id": list("abcd"), "flag": "skip_investigation", "n": [1, 1, 0, 0]})
    out = check_fast_track(cases, flags, max_fpy_drop=0.1)
    assert out["verdict"] == SUPPORT
    slow = cases.assign(ct_work_s=[50 * D, 60 * D, 20 * D, 30 * D])
    assert check_fast_track(slow, flags, max_fpy_drop=0.1)["verdict"] == REJECT


# ------------------------------------------------------------------------------ what-if, KPI


def test_cap_state_never_increases_ct_and_only_touches_that_state():
    log = frame(visits("a", "DONE", ["__CREATED__", "To Do", "DONE"], [1, 10]),
                visits("b", "DONE", ["__CREATED__", "To Do", "DONE"], [1, 2]))
    out = whatif_cap_state(log, state="To Do", cap_days=4).set_index("case_id")
    assert out.loc["a", "ct_work_s_tobe"] == 5 * D and out.loc["b", "ct_work_s_tobe"] == 3 * D
    assert (out["ct_work_s_tobe"] <= out["ct_work_s_asis"]).all()


def test_kpi_table_labels_every_tobe_value_as_target():
    rows = [{"kpi": "ct", "asis": 10.0, "tobe": 8.0, "unit": "ngày", "scenario": "s", "assumption": "a"}]
    table = kpi_asis_tobe(rows)
    assert (table["tobe_label"] == "mục tiêu / kịch bản ước tính").all()
    assert table.iloc[0]["delta"] == pytest.approx(-2.0) and table.iloc[0]["delta_pct"] == pytest.approx(-0.2)


def test_early_triage_needs_both_share_and_a_slow_median():
    quick = frame(*[visits(f"r{i}", "Rejected", ["__CREATED__", "Rejected"], [1]) for i in range(5)],
                  visits("d1", "DONE", ["__CREATED__", "In Progress", "DONE"], [1, 1]))
    out = check_early_triage(cases_of(quick), quick, min_share=0.2, min_median_days=5)
    assert out["value"] > 0.2 and out["verdict"] == REJECT  # nhiều ca Rejected nhưng bị loại nhanh


def test_role_dependency_ignores_bots_even_when_they_dominate():
    po = [visits(f"p{i}", "DONE", ["__CREATED__", "To Do", "DONE"], [1, 5 + i * 0.1], ["SQA", "PO"])
          for i in range(8)]
    eng = [visits(f"e{i}", "DONE", ["__CREATED__", "To Do", "DONE"], [1, 1 + i * 0.1], ["SQA", "Eng"])
           for i in range(8)]
    bots = [visits(f"b{i}", "DONE", ["__CREATED__", "To Do", "DONE"], [1, 50], ["SQA", "bot"])
            for i in range(30)]
    assert check_role_dependency(frame(*po, *eng, *bots), state="To Do", role="PO", n_boot=300,
                                 seed=1)["verdict"] == SUPPORT


def test_investigating_state_rejected_when_range_comes_from_backfill_only():
    ranges = pd.DataFrame({"variant": ["main", "main+backfill", "sensitivity", "sensitivity+backfill"],
                           "clock": "work", "branch": "all", "pt_share": [0.17, 0.40, 0.17, 0.40]})
    assert check_investigating_state(ranges, min_width_pp=10)["verdict"] == REJECT


def test_cap_state_leaves_other_states_untouched():
    log = frame(visits("a", "DONE", ["__CREATED__", "To Do", "In Progress", "DONE"], [1, 10, 10]))
    out = whatif_cap_state(log, state="To Do", cap_days=4).set_index("case_id")
    assert out.loc["a", "ct_work_s_tobe"] == 15 * D


def test_state_excess_by_role_shares_tail_days_among_exit_roles():
    from jira_ad.bpr import state_excess_by_role

    late = pd.DataFrame({"state": ["To Do"] * 4 + ["In Test"], "exit_role": ["PO", "PO", "Eng", "bot", "PO"],
                         "excess_days": [6.0, 0.0, 2.0, 2.0, 9.0],
                         "is_late": [True, False, True, True, True]})
    out = state_excess_by_role(late, state="To Do").set_index("role")
    assert out.loc["PO", "excess_days"] == 6.0
    assert out.loc["PO", "share_of_state_excess"] == pytest.approx(0.6)
    assert out.loc["PO", "n_visits"] == 2 and out.loc["PO", "n_late"] == 1
    assert not out.loc["bot", "is_human"]


def test_problem_table_joins_candidates_with_check_evidence_and_verdict():
    from jira_ad.bpr import problem_table
    from jira_ad.process_config import CandidateConfig

    checks = pd.DataFrame([{"candidate": "early_triage", "verdict": SUPPORT, "evidence": "e1", "metric": "m",
                            "value": 0.4, "threshold": "t"},
                           {"candidate": "fast_track", "verdict": REJECT, "evidence": "e2", "metric": "m",
                            "value": 1.0, "threshold": "t"}])
    cands = (CandidateConfig("early_triage", "p1", "h1"), CandidateConfig("fast_track", "p2", "h2"))
    out = problem_table(cands, checks).set_index("candidate")
    assert out.loc["early_triage", "evidence"] == "e1" and out.loc["early_triage", "in_tobe"]
    assert not out.loc["fast_track", "in_tobe"] and out.loc["fast_track", "heuristic"] == "h2"


def test_pilot_plan_fills_baseline_and_target_from_kpi_table():
    from jira_ad.bpr import pilot_plan
    from jira_ad.process_config import PilotPhase

    kpi = kpi_asis_tobe([{"kpi": "ct_work_median_days", "asis": 17.0, "tobe": 12.0, "unit": "ngày",
                          "scenario": "s", "assumption": "a"}])
    out = pilot_plan((PilotPhase("p1", "1–2", "làm", ("ct_work_median_days",)),), kpi)
    row = out.iloc[0]
    assert (row.baseline_asis, row.target_tobe) == (17.0, 12.0)
    assert row.tobe_label == "mục tiêu / kịch bản ước tính"


def test_early_triage_whatif_returns_per_case_ct_for_combining_scenarios():
    log = frame(visits("r1", "Rejected", ["__CREATED__", "To Investigate", "Rejected"], [1, 9]),
                visits("d1", "DONE", ["__CREATED__", "In Progress", "DONE"], [1, 9]))
    per_case = whatif_early_triage(cases_of(log), log)["per_case"].set_index("case_id")["ct_work_s_tobe"]
    assert per_case["r1"] == 1 * D and per_case["d1"] == 10 * D


def test_pilot_plan_marks_kpis_not_measured_in_this_run():
    from jira_ad.bpr import pilot_plan
    from jira_ad.process_config import PilotPhase

    kpi = kpi_asis_tobe([{"kpi": "ct_work_median_days", "asis": 17.0, "tobe": 12.0, "unit": "ngày",
                          "scenario": "s", "assumption": "a"}])
    out = pilot_plan((PilotPhase("p1", "1–2", "làm", ("conformance_share_fit",)),), kpi)
    assert out.iloc[0]["baseline_asis"] != out.iloc[0]["baseline_asis"]  # NaN
    assert "chưa đo" in out.iloc[0]["note"]


def test_reject_at_investigation_end_keeps_investigation_and_drops_later_waits():
    from jira_ad.bpr import whatif_reject_at_investigation_end

    inv = ["__CREATED__", "To Investigate", "INVESTIGATED"]
    log = frame(visits("r1", "Rejected", [*inv, "Rejected"], [1, 5, 3]),
                visits("r2", "Rejected", [*inv, "To Do", "Rejected"], [1, 4, 1, 30]),
                visits("r3", "Rejected", ["__CREATED__", "Rejected"], [2]),
                visits("d1", "DONE", ["__CREATED__", "In Progress", "DONE"], [1, 9]))
    w = whatif_reject_at_investigation_end(cases_of(log), log)
    per_case = w["per_case"].set_index("case_id")["ct_work_s_tobe"]
    assert per_case["r1"] == 6 * D and per_case["r2"] == 5 * D       # quyết ngay khi rời To Investigate
    assert per_case["r3"] == 2 * D and per_case["d1"] == 10 * D  # không điều tra / không Rejected: giữ nguyên
    assert w["asis_rejected_issue_days"] == pytest.approx(9 + 36 + 2)
    assert w["tobe_rejected_issue_days"] == pytest.approx(6 + 5 + 2)


def test_early_triage_evidence_counts_rejections_right_after_investigation():
    inv = ["__CREATED__", "To Investigate", "INVESTIGATED"]
    log = frame(visits("r1", "Rejected", [*inv, "Rejected"], [1, 9, 1]),
                visits("r2", "Rejected", ["__CREATED__", "Rejected"], [12]),
                visits("d1", "DONE", ["__CREATED__", "In Progress", "DONE"], [1, 9]))
    out = check_early_triage(cases_of(log), log, min_share=0.2, min_median_days=5)
    assert out["n_after_investigated"] == 1 and "1/2 ca bị loại ngay sau INVESTIGATED" in out["evidence"]


def test_auto_transition_reports_where_the_first_link_falls():
    path = ["__CREATED__", "To Investigate", "To Do", "In Progress", "DONE"]
    log = frame(visits("a", "DONE", path, [1, 4, 2, 2]),
                visits("b", "DONE", ["__CREATED__", "To Do", "In Progress", "DONE"], [1, 5, 2]))
    events = pd.DataFrame({"case_id": ["a", "b"], "activity": ["LINK_COMMIT", "LINK_COMMIT"],
                           "timestamp_utc": [T0 + pd.Timedelta(days=2), T0 + pd.Timedelta(days=3)]})
    out = check_auto_transition(log, events, min_share=0.3)
    assert out["link_state_counts"] == {"To Investigate": 1, "To Do": 1}
    assert out["n_in_automated_state"] == 1 and "To Investigate 1" in out["evidence"]


def test_tobe_path_counts_status_changes_on_the_redesigned_route():
    from jira_ad.bpr import whatif_tobe_path

    log = frame(visits("a", "DONE", ["__CREATED__", "To Investigate", "INVESTIGATED", "To Do", "In Progress",
                                     "In Test", "DONE"], [1, 1, 1, 1, 1, 1]),
                visits("b", "Rejected", ["__CREATED__", "Rejected"], [1]),
                visits("c", "DONE", ["__CREATED__", "Inbox", "To Do", "In Progress", "In Test", "DONE"],
                       [1, 1, 1, 1, 1]))
    w = whatif_tobe_path(log, drop=("INVESTIGATED",), insert_after={"To Investigate": "Investigating"},
                         entry="Inbox")
    # a: 6 → Inbox, To Investigate, Investigating, To Do, In Progress, In Test, DONE = 7; b: 1 → 2; c: 5 → 5
    assert w["changes_per_case_asis"] == pytest.approx(12 / 3)
    assert w["changes_per_case_tobe"] == pytest.approx(14 / 3)


def test_state_excess_by_role_and_target_splits_backlog_cleanup():
    from jira_ad.bpr import state_excess_by_role_and_target

    log = frame(visits("a", "Rejected", ["__CREATED__", "To Do", "Rejected"], [1, 100], ["SQA", "PO"]),
                visits("b", "DONE", ["__CREATED__", "To Do", "In Progress", "DONE"], [1, 20, 1],
                       ["SQA", "PO", "Eng"]),
                visits("c", "DONE", ["__CREATED__", "To Do", "In Progress", "DONE"], [1, 2, 1],
                       ["SQA", "Eng", "Eng"]))
    late = log.assign(excess_days=[0, 90, None, 0, 10, 0, None, 0, 0, 0, None],
                      is_late=[False, True, None, False, True, False, None, False, False, False, None])
    out = state_excess_by_role_and_target(late, log, state="To Do").set_index(["role", "target_state"])
    assert out.loc[("PO", "Rejected"), "excess_days"] == 90 and out.loc[("PO", "Rejected"), "n_visits"] == 1
    assert out.loc[("PO", "In Progress"), "excess_days"] == 10
    assert out.loc[("PO", "Rejected"), "share_of_role_excess"] == pytest.approx(0.9)


def test_reject_at_investigation_end_uses_the_last_investigation_round():
    from jira_ad.bpr import whatif_reject_at_investigation_end

    states = ["__CREATED__", "To Investigate", "INVESTIGATED", "To Investigate", "INVESTIGATED", "Rejected"]
    log = frame(visits("r", "Rejected", states, [1, 2, 1, 3, 1]))
    per_case = whatif_reject_at_investigation_end(cases_of(log), log)["per_case"]
    assert per_case.set_index("case_id").loc["r", "ct_work_s_tobe"] == 7 * D


def test_small_negative_values_never_print_as_negative_zero():
    from jira_ad.bpr import _days

    assert _days(-0.03) == "0,0" and _days(-0.0) == "0,0" and _days(-1.26) == "-1,3"
