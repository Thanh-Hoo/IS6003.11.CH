"""Status log: lượt trạng thái, dwell theo đồng hồ lịch/ngày làm việc, cờ cập nhật bù, lùi, mở lại."""

from __future__ import annotations

import math

import pytest
from helpers import stamped_rows, status, write_process_project

from jira_ad.process_config import load_process_config
from jira_ad.status_log import build_status_log, case_table, load_cohort

H = 3600.0
D = 86_400.0

# 2022-06-13 là Thứ Hai. Giờ địa phương −0700.
FLOW = stamped_rows("TI-1", [
    ("2022-06-13T08:00:00", "SQA", "Issue created"),
    ("2022-06-13T10:00:00", "PO", status("To Do")),
    ("2022-06-14T10:00:00", "Eng", status("In Progress")),
    ("2022-06-15T10:00:00", "Eng", status("In Test")),
    ("2022-06-15T16:00:00", "SQA", status("DONE")),
])
BACKFILL = stamped_rows("TI-2", [
    ("2022-06-13T08:00:00", "SQA", "Issue created"),
    ("2022-06-14T08:00:00", "PO", status("To Do")),
    ("2022-06-16T08:00:00", "Eng", status("In Progress")),
    ("2022-06-16T08:00:20", "Eng", status("In Test")),
    ("2022-06-16T08:00:40", "Eng", status("DONE")),
])
BACK = stamped_rows("TI-3", [
    ("2022-06-13T08:00:00", "SQA", "Issue created"),
    ("2022-06-13T09:00:00", "PO", status("To Do")),
    ("2022-06-13T10:00:00", "Eng", status("In Progress")),
    ("2022-06-13T11:00:00", "Eng", status("To Do")),
    ("2022-06-13T12:00:00", "Eng", status("In Progress")),
    ("2022-06-13T13:00:00", "SQA", status("In Test")),
    ("2022-06-13T14:00:00", "SQA", status("DONE")),
])
REOPEN = stamped_rows("TI-4", [
    ("2022-06-13T08:00:00", "SQA", "Issue created"),
    ("2022-06-13T09:00:00", "PO", status("Rejected")),
    ("2022-06-14T09:00:00", "PO", "remove resolution, update status to Inbox"),
    ("2022-06-14T10:00:00", "PO", status("Rejected")),
])
DIRECT_REJECT = stamped_rows("TI-5", [
    ("2022-06-13T08:00:00", "SQA", "Issue created"),
    ("2022-06-13T20:00:00", "PO", status("Rejected")),
])
TRIAGE = stamped_rows("TI-6", [
    ("2022-06-13T08:00:00", "SQA", "Issue created"),
    ("2022-06-13T09:00:00", "unknown", status("Triage")),
    ("2022-06-13T10:00:00", "PO", status("Rejected")),
])
WEEKEND = stamped_rows("TI-7", [
    ("2022-06-18T08:00:00", "SQA", "Issue created"),   # Thứ Bảy
    ("2022-06-19T20:00:00", "PO", status("Rejected")),  # Chủ Nhật
])
SAME_TIME = stamped_rows("TI-8", [
    ("2022-06-13T08:00:00", "SQA", "Issue created"),
    ("2022-06-13T09:00:00", "PO", status("To Do")),
    ("2022-06-13T09:00:00", "PO", status("In Progress")),
    ("2022-06-13T12:00:00", "SQA", status("In Test")),
    ("2022-06-13T13:00:00", "SQA", status("DONE")),
])
ALL_ROWS = FLOW + BACKFILL + BACK + REOPEN + DIRECT_REJECT + TRIAGE + WEEKEND + SAME_TIME


@pytest.fixture
def built(project):
    cfg = load_process_config(write_process_project(project, ALL_ROWS))
    cohort = load_cohort(cfg, "bug")
    log = build_status_log(cohort.events, cohort.traces, cfg)
    return cfg, cohort, log, case_table(log, cohort.traces)


def visits(log, case):
    return log[log.case_id == f"bug:{case}"].reset_index(drop=True)


def test_visits_partition_the_case_and_start_with_created_segment(built):
    _, _, log, cases = built
    v = visits(log, "TI-1")
    assert list(v.state) == ["__CREATED__", "To Do", "In Progress", "In Test", "DONE"]
    assert list(v.state_class) == ["created", "wait", "work", "work", "terminal"]
    assert list(v.dwell_cal_s[:4]) == [2 * H, 24 * H, 24 * H, 6 * H]
    assert math.isnan(v.dwell_cal_s[4])
    assert list(v.exit_role[:4]) == ["PO", "Eng", "Eng", "SQA"]
    row = cases.set_index("case_id").loc["bug:TI-1"]
    assert row.ct_cal_s == 56 * H == v.dwell_cal_s[:4].sum()
    assert row.ct_work_s == 56 * H  # Thứ Hai–Thứ Tư đều là ngày làm việc


def test_offset_minutes_come_from_raw_timestamp(built):
    _, _, log, _ = built
    assert set(log.offset_min) == {-420}


def test_backfill_entries_and_burst(built):
    _, _, log, cases = built
    v = visits(log, "TI-2")
    assert list(v.is_backfill_entry) == [False, False, False, True, True]
    assert v.burst_id[3] == v.burst_id[4] == v.burst_id[2] != -1
    assert v.burst_id[1] == -1
    assert cases.set_index("case_id").loc["bug:TI-2"].n_backfill == 2


def test_same_timestamp_gives_zero_dwell_in_csv_order(built):
    _, _, log, _ = built
    v = visits(log, "TI-8")
    assert list(v.state) == ["__CREATED__", "To Do", "In Progress", "In Test", "DONE"]
    assert v.dwell_cal_s[1] == 0
    assert (v.dwell_cal_s.dropna() >= 0).all()


def test_back_transition_and_reopen(built):
    _, _, log, cases = built
    back = visits(log, "TI-3")
    assert list(back.is_back) == [False, False, False, True, False, False, False]
    reopen = visits(log, "TI-4")
    assert list(reopen.state) == ["__CREATED__", "Rejected", "Inbox", "Rejected"]
    assert list(reopen.is_reopen) == [False, False, True, False]
    assert reopen.state_class[1] == "terminal" and reopen.dwell_cal_s[1] == 24 * H
    by_case = cases.set_index("case_id")
    assert by_case.loc["bug:TI-3"].n_back == 1 and by_case.loc["bug:TI-4"].n_reopen == 1


def test_undeclared_state_is_other(built):
    _, _, log, _ = built
    assert visits(log, "TI-6").state_class[1] == "other"


def test_direct_reject_has_only_created_segment(built):
    _, _, log, cases = built
    v = visits(log, "TI-5")
    assert list(v.state) == ["__CREATED__", "Rejected"]
    row = cases.set_index("case_id").loc["bug:TI-5"]
    assert row.ct_cal_s == 12 * H and not row.reached_in_progress


def test_weekend_case_has_zero_working_time_but_positive_calendar_time(built):
    _, _, log, cases = built
    row = cases.set_index("case_id").loc["bug:TI-7"]
    assert row.ct_cal_s == 36 * H and row.ct_work_s == 0
    # theo UTC, 20:00 Chủ Nhật −0700 = 03:00 Thứ Hai: có 3 giờ làm việc
    assert row.ct_work_utc_s == 3 * H


def test_variant_and_terminal(built):
    _, _, _, cases = built
    row = cases.set_index("case_id").loc["bug:TI-1"]
    assert row.variant == "To Do > In Progress > In Test > DONE"
    assert row.terminal_status == "DONE" and row.reached_in_progress


def test_status_log_uses_only_core_events(project):
    rows = FLOW + [("TI-1", "2022-06-16T09:00:00.000-0700", "bot", "update RemoteIssueLink")]
    cfg = load_process_config(write_process_project(project, rows))
    cohort = load_cohort(cfg, "bug")
    log = build_status_log(cohort.events, cohort.traces, cfg)
    assert len(log) == 5 and set(cohort.events.event_id) == set(cohort.traces[0].event_ids)


def test_first_status_change_right_after_create_is_not_backfill(project):
    # 553 khoảng = giữa hai lần ĐỔI TRẠNG THÁI; CREATE → lần đổi đầu không tính.
    rows = stamped_rows("TI-1", [
        ("2022-06-13T08:00:00", "SQA", "Issue created"),
        ("2022-06-13T08:00:30", "PO", status("To Do")),
        ("2022-06-14T08:00:00", "PO", status("Rejected")),
    ])
    cfg = load_process_config(write_process_project(project, rows))
    cohort = load_cohort(cfg, "bug")
    log = build_status_log(cohort.events, cohort.traces, cfg)
    assert not log.is_backfill_entry.any()


def test_repeated_same_state_is_not_a_back_transition(project):
    rows = stamped_rows("TI-1", [
        ("2022-06-13T08:00:00", "SQA", "Issue created"),
        ("2022-06-13T09:00:00", "PO", status("To Do")),
        ("2022-06-13T10:00:00", "PO", status("To Do")),
        ("2022-06-13T11:00:00", "PO", status("Rejected")),
    ])
    cfg = load_process_config(write_process_project(project, rows))
    cohort = load_cohort(cfg, "bug")
    log = build_status_log(cohort.events, cohort.traces, cfg)
    assert not log.is_back.any()
