"""Định mức thống kê (B3): P75 dwell ngày làm việc theo trạng thái; trễ theo trạng thái, vai trò, ca."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from jira_ad.norms import fit_norms, late_by_case, late_by_role, late_by_state, late_visits, top_late

D = 86_400.0


def log_of(rows):
    """rows = [(case, terminal, state, dwell_days | None, exit_role)] theo thứ tự lượt."""
    out = []
    counters: dict[str, int] = {}
    for case, terminal, state, days, role in rows:
        i = counters.get(case, 0)
        counters[case] = i + 1
        out.append({"case_id": case, "terminal_status": terminal, "visit_index": i, "state": state,
                    "dwell_work_s": None if days is None else days * D, "exit_role": role})
    return pd.DataFrame(out)


LOG = log_of([
    ("a", "DONE", "A", 1, "PO"), ("a", "DONE", "B", 1, "Eng"), ("a", "DONE", "DONE", None, None),
    ("b", "DONE", "A", 2, "PO"), ("b", "DONE", "B", 9, "bot"), ("b", "DONE", "DONE", None, None),
    ("c", "Rejected", "A", 3, "PO"), ("c", "Rejected", "Rejected", None, None),
    ("d", "Rejected", "A", 4, "unknown"), ("d", "Rejected", "Rejected", None, None),
    ("e", "Rejected", "A", 5, "SQA"), ("e", "Rejected", "Rejected", None, None),
])


def test_norm_is_p75_of_working_dwell():
    norms = fit_norms(LOG, percentile=0.75, min_visits=3, explicit_days={}).set_index("state")
    assert norms.loc["A", "norm_days"] == pytest.approx(4.0)   # P75 của 1..5
    assert norms.loc["A", "source"] == "p75_lịch_sử" and norms.loc["A", "n"] == 5


def test_state_with_too_few_visits_has_no_norm():
    norms = fit_norms(LOG, percentile=0.75, min_visits=3, explicit_days={}).set_index("state")
    assert math.isnan(norms.loc["B", "norm_days"]) and norms.loc["B", "source"] == "quá_ít_lượt"
    assert "DONE" not in norms.index  # lượt kết thúc cuối không có dwell


def test_explicit_sla_overrides_percentile():
    norms = fit_norms(LOG, percentile=0.75, min_visits=3, explicit_days={"A": 2.0}).set_index("state")
    assert norms.loc["A", "norm_days"] == 2.0 and norms.loc["A", "source"] == "SLA_cấu_hình"


def test_late_is_strictly_greater_and_excess_is_time_beyond_norm():
    norms = fit_norms(LOG, percentile=0.75, min_visits=3, explicit_days={})
    late = late_visits(LOG, norms)
    a = late[late.state == "A"].set_index("case_id")
    assert not a.loc["d", "is_late"]            # 4 == định mức ⇒ đúng hạn
    assert a.loc["e", "is_late"] and a.loc["e", "excess_days"] == pytest.approx(1.0)
    assert late[late.state == "B"].is_late.isna().all()  # không có định mức ⇒ không phán xét


def test_late_by_state_rates():
    late = late_visits(LOG, fit_norms(LOG, percentile=0.75, min_visits=3, explicit_days={}))
    row = late_by_state(late).set_index("state").loc["A"]
    assert (row.n_visits, row.n_late) == (5, 1) and row.late_rate == pytest.approx(0.2)


def test_late_by_role_uses_exit_role_and_flags_non_human():
    late = late_visits(LOG, fit_norms(LOG, percentile=0.75, min_visits=1, explicit_days={}))
    roles = late_by_role(late).set_index("role")
    assert roles.loc["SQA", "n_exits"] == 1 and roles.loc["SQA", "n_late"] == 1
    assert not roles.loc["unknown", "is_human"] and not roles.loc["bot", "is_human"]
    assert roles.loc["PO", "is_human"] and roles.loc["PO", "n_exits"] == 3


def test_late_by_case_counts_late_visits_and_compares_ct_with_branch_norm():
    late = late_visits(LOG, fit_norms(LOG, percentile=0.75, min_visits=3, explicit_days={}))
    cases = pd.DataFrame({"case_id": list("abcde"),
                          "terminal_status": ["DONE", "DONE", "Rejected", "Rejected", "Rejected"],
                          "ct_work_s": [2 * D, 11 * D, 3 * D, 4 * D, 5 * D]})
    out = late_by_case(late, cases, percentile=0.75).set_index("case_id")
    assert out.loc["e", "n_late"] == 1 and out.loc["a", "n_late"] == 0
    # P75 nhánh Rejected của 3,4,5 = 4,5 ⇒ chỉ e trễ
    assert out.loc["e", "ct_late"] and not out.loc["d", "ct_late"]
    assert out.loc["e", "ct_norm_days"] == pytest.approx(4.5)


def test_top_late_sorted_by_excess():
    dwell = [1, 1, 1, 1, 1, 1, 9, 5]
    log = log_of([(c, "DONE", "A", d, "PO") for c, d in zip("abcdefgh", dwell, strict=True)])
    late = late_visits(log, fit_norms(log, percentile=0.75, min_visits=3, explicit_days={}))
    top = top_late(late, k=2)
    assert list(top.case_id) == ["g", "h"]


def test_on_time_visits_contribute_zero_excess():
    late = late_visits(LOG, fit_norms(LOG, percentile=0.75, min_visits=3, explicit_days={}))
    a = late[late.state == "A"].set_index("case_id")
    assert a.loc["a", "excess_days"] == 0
    assert late_by_state(late).set_index("state").loc["A", "excess_days"] == pytest.approx(1.0)
