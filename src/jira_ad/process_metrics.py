"""Phân tích định lượng quy trình (B2): CT = PT + WT, CTE, định luật Little, FPY, vai trò cổng.

PT/WT là xấp xỉ: Jira chỉ ghi thời điểm đổi trạng thái, nên "làm" = thời gian nằm ở trạng thái
được phân loại là làm (`states.work`), "chờ" = phần còn lại của CT. Vì phân loại và cập nhật bù
đều là giả định, PT/WT/CTE được báo thành khoảng giữa bốn biến thể (Ruling 68).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from jira_ad.process_config import ProcessConfig
from jira_ad.status_log import NO_BURST
from jira_ad.types import UNDETERMINED_ROLES

DAY = 86_400.0
WEEK = pd.Timedelta(days=7)
NON_HUMAN_ROLES = frozenset({"bot"}) | UNDETERMINED_ROLES
CLOCKS = {"cal": "dwell_cal_s", "work": "dwell_work_s", "work_utc": "dwell_work_utc_s"}
BRANCHES = ("all", "DONE", "Rejected")


def is_human(role) -> bool:
    return isinstance(role, str) and role not in NON_HUMAN_ROLES


def _branch(frame: pd.DataFrame, branch: str) -> pd.DataFrame:
    return frame if branch == "all" else frame[frame["terminal_status"] == branch]


def _backfill_promoted(status_log: pd.DataFrame, work_states: set[str], threshold_s: float) -> pd.Series:
    """Lượt ngay trước một chuỗi lượt ngắn (< ngưỡng) có đi qua trạng thái làm: cận trên do bù."""
    promoted = pd.Series(False, index=status_log.index)
    for _, v in status_log.groupby("case_id", sort=False):
        idx = list(v.index)
        short = (v["dwell_cal_s"] < threshold_s).to_numpy()
        i = 0
        while i < len(idx):
            if short[i] and i > 0 and not short[i - 1]:
                j = i
                while j < len(idx) and short[j]:
                    j += 1
                if status_log.loc[idx[i:j], "state"].isin(work_states).any():
                    promoted[idx[i - 1]] = True
                i = j
            else:
                i += 1
    return promoted


def time_split(
    status_log: pd.DataFrame, work_states, *, backfill_upper: bool, clock: str, threshold_s: float
) -> pd.DataFrame:
    """PT, WT, CT và CTE từng ca theo một phân loại làm/chờ và một đồng hồ."""
    work_states = set(work_states)
    dwell = status_log[CLOCKS[clock]].fillna(0.0)
    is_work = status_log["state"].isin(work_states)
    if backfill_upper:
        is_work = is_work | _backfill_promoted(status_log, work_states, threshold_s)
    frame = pd.DataFrame({
        "case_id": status_log["case_id"], "terminal_status": status_log["terminal_status"],
        "pt_s": dwell.where(is_work, 0.0), "ct_s": dwell,
    })
    out = frame.groupby("case_id", sort=False).agg(
        terminal_status=("terminal_status", "first"), pt_s=("pt_s", "sum"), ct_s=("ct_s", "sum")
    ).reset_index()
    out["wt_s"] = out["ct_s"] - out["pt_s"]
    out["cte"] = np.where(out["ct_s"] > 0, out["pt_s"] / out["ct_s"].where(out["ct_s"] > 0), np.nan)
    return out


VARIANTS = (
    ("main", "work", False),
    ("main+backfill", "work", True),
    ("sensitivity", "sensitivity_work", False),
    ("sensitivity+backfill", "sensitivity_work", True),
)


def pt_wt_ranges(status_log: pd.DataFrame, cfg: ProcessConfig) -> pd.DataFrame:
    """Bốn biến thể (phân loại × cập nhật bù) × ba đồng hồ × ba nhánh; tỉ trọng PT = ΣPT/ΣCT."""
    rows = []
    for name, attr, upper in VARIANTS:
        work = getattr(cfg.states, attr)
        for clock in CLOCKS:
            split = time_split(status_log, work, backfill_upper=upper, clock=clock,
                               threshold_s=cfg.backfill.threshold_seconds)
            for branch in BRANCHES:
                part = _branch(split, branch)
                rows.append({
                    "variant": name, "clock": clock, "branch": branch, "n_cases": len(part),
                    "pt_share": part["pt_s"].sum() / part["ct_s"].sum() if part["ct_s"].sum() else np.nan,
                    "pt_median_days": part["pt_s"].median() / DAY,
                    "wt_median_days": part["wt_s"].median() / DAY,
                    "ct_median_days": part["ct_s"].median() / DAY,
                    "cte_median": part["cte"].median(), "cte_mean": part["cte"].mean(),
                    "n_cte_undefined": int(part["cte"].isna().sum()),
                })
    return pd.DataFrame(rows)


def dwell_by_state(status_log: pd.DataFrame) -> pd.DataFrame:
    """Dwell (ngày) theo trạng thái × nhánh × đồng hồ; bỏ lượt cuối (không có dwell)."""
    rows = []
    closed = status_log[status_log["dwell_cal_s"].notna()]
    for branch in BRANCHES:
        part = _branch(closed, branch)
        for (state, cls), v in part.groupby(["state", "state_class"], sort=True):
            for clock, column in CLOCKS.items():
                d = v[column] / DAY
                rows.append({
                    "state": state, "state_class": cls, "branch": branch, "clock": clock,
                    "n": len(d), "n_cases": v["case_id"].nunique(), "mean": d.mean(),
                    "median": d.median(), "p75": d.quantile(0.75), "p90": d.quantile(0.90),
                    "total_days": d.sum(),
                })
    return pd.DataFrame(rows)


def little_window(cases: pd.DataFrame) -> dict:
    """L = λ·W trên cửa sổ [CREATE đầu, kết thúc cuối]: đồng nhất thức khi mọi ca đều đã đóng."""
    start, end = cases["t_create"].min(), cases["t_end"].max()
    window = (end - start).total_seconds() / DAY
    ct = (cases["t_end"] - cases["t_create"]).dt.total_seconds() / DAY
    lam = len(cases) / window
    half = start + (end - start) / 2
    first = cases["t_create"] < half
    return {
        "window_start": start.isoformat(), "window_end": end.isoformat(), "window_days": window,
        "n_cases": len(cases), "lambda_per_day": lam, "W_days": ct.mean(),
        "L_measured": ct.sum() / window, "L_little": lam * ct.mean(),
        "arrivals_first_half": int(first.sum()), "arrivals_second_half": int((~first).sum()),
        "W_days_first_half": float(ct[first].mean()), "W_days_second_half": float(ct[~first].mean()),
        "note": "Chỉ có ca đã đóng nên L = λ·W đúng theo định nghĩa trên cả cửa sổ; độ lệch theo "
                "tuần và giữa hai nửa kỳ mới mang thông tin về tính dừng.",
    }


def weekly_little(cases: pd.DataFrame) -> pd.DataFrame:
    """Theo tuần UTC (Thứ Hai): ca đến, ca xong, WIP đo (trung bình theo thời gian), λ_tuần × CT TB."""
    start = cases["t_create"].min().normalize()
    start -= pd.Timedelta(days=start.weekday())
    end = cases["t_end"].max()
    ct_mean_days = ((cases["t_end"] - cases["t_create"]).dt.total_seconds() / DAY).mean()
    rows = []
    week = start
    while week <= end:
        nxt = week + WEEK
        lo = cases["t_create"].clip(lower=week)
        hi = cases["t_end"].clip(upper=nxt)
        open_s = (hi - lo).dt.total_seconds().clip(lower=0).sum()
        arrivals = int(((cases["t_create"] >= week) & (cases["t_create"] < nxt)).sum())
        rows.append({
            "week_start": week, "arrivals": arrivals,
            "completions": int(((cases["t_end"] >= week) & (cases["t_end"] < nxt)).sum()),
            "wip_measured": open_s / WEEK.total_seconds(),
            "lambda_x_ct": arrivals / 7 * ct_mean_days,
        })
        week = nxt
    return pd.DataFrame(rows)


def fpy(status_log: pd.DataFrame) -> dict:
    """First-pass yield: ca không lùi, không mở lại (strict); bỏ qua lần lùi trong đợt bù (adjusted)."""
    rework = status_log["is_back"] | status_log["is_reopen"]
    in_burst = status_log["burst_id"] != NO_BURST  # lần đổi thuộc một đợt bù (kể cả lần mở đầu đợt)
    real = rework & ~in_burst
    per_case = pd.DataFrame({"case_id": status_log["case_id"], "rework": rework, "real": real,
                             "terminal_status": status_log["terminal_status"]})
    agg = per_case.groupby("case_id").agg(rework=("rework", "any"), real=("real", "any"),
                                          terminal_status=("terminal_status", "first"))
    done = agg[agg["terminal_status"] == "DONE"]
    return {
        "n_cases": len(agg), "fpy_strict": float((~agg["rework"]).mean()),
        "fpy_adjusted": float((~agg["real"]).mean()),
        "fpy_strict_done": float((~done["rework"]).mean()) if len(done) else float("nan"),
        "fpy_adjusted_done": float((~done["real"]).mean()) if len(done) else float("nan"),
        "n_cases_rework": int(agg["rework"].sum()),
        "n_cases_rework_outside_backfill": int(agg["real"].sum()),
        "definition": "Lùi = sang trạng thái có thứ tự nhỏ hơn (states.order); mở lại = rời DONE/Rejected; "
                      "adjusted bỏ qua lần lùi/mở lại thuộc một đợt cập nhật bù "
                      "(chuỗi đổi trạng thái < 60 s).",
    }


def rejected_cost(cases: pd.DataFrame) -> pd.DataFrame:
    """Ngày-issue tiêu tốn trước khi Rejected; tách nhóm đã vào In Progress (công sức bị bỏ)."""
    rejected = cases[cases["terminal_status"] == "Rejected"]
    groups = {"all": rejected, "after_in_progress": rejected[rejected["reached_in_progress"]],
              "before_in_progress": rejected[~rejected["reached_in_progress"]]}
    rows = []
    for name, part in groups.items():
        rows.append({
            "group": name, "n_cases": len(part),
            "issue_days_cal": part["ct_cal_s"].sum() / DAY,
            "issue_days_work": part["ct_work_s"].sum() / DAY,
            "median_days_cal": part["ct_cal_s"].median() / DAY if len(part) else np.nan,
            "median_days_work": part["ct_work_s"].median() / DAY if len(part) else np.nan,
        })
    return pd.DataFrame(rows)


def gate_roles(status_log: pd.DataFrame) -> pd.DataFrame:
    """Số lần đổi trạng thái theo vai trò × trạng thái đích; vai trò cổng = vai trò người nhiều nhất."""
    changes = status_log[status_log["visit_index"] > 0]
    table = (changes.groupby(["state", "enter_role"]).size().rename("n").reset_index()
             .rename(columns={"state": "target_state", "enter_role": "role"}))
    table["share_of_target"] = table["n"] / table.groupby("target_state")["n"].transform("sum")
    table["is_human"] = table["role"].map(is_human)
    human = table[table["is_human"]].sort_values(["target_state", "n", "role"],
                                                 ascending=[True, False, True])
    top = set(human.groupby("target_state").head(1).index)
    table["is_top_human"] = table.index.isin(top)
    ordered = table.sort_values(["target_state", "n", "role"], ascending=[True, False, True])
    return ordered.reset_index(drop=True)


def kpi_asis(status_log: pd.DataFrame, cases: pd.DataFrame, cfg: ProcessConfig) -> pd.DataFrame:
    """Bảng KPI AS-IS (đo được); khoảng PT/CTE lấy min–max giữa bốn biến thể, đồng hồ ngày làm việc."""
    ranges = pt_wt_ranges(status_log, cfg)
    work_all = ranges[(ranges["clock"] == "work") & (ranges["branch"] == "all")]
    q = fpy(status_log)
    rej = rejected_cost(cases).set_index("group")
    weeks = weekly_little(cases)
    changes = status_log[status_log["visit_index"] > 1]
    rows = [
        ("n_cases", len(cases), "ca", "đo"),
        ("share_done", float((cases["terminal_status"] == "DONE").mean()), "tỉ lệ", "đo"),
        ("share_rejected", float((cases["terminal_status"] == "Rejected").mean()), "tỉ lệ", "đo"),
        ("ct_cal_median_days", cases["ct_cal_s"].median() / DAY, "ngày lịch", "đo"),
        ("ct_cal_p90_days", cases["ct_cal_s"].quantile(0.9) / DAY, "ngày lịch", "đo"),
        ("ct_work_median_days", cases["ct_work_s"].median() / DAY, "ngày làm việc", "đo"),
        ("ct_work_p90_days", cases["ct_work_s"].quantile(0.9) / DAY, "ngày làm việc", "đo"),
        ("pt_share_min", work_all["pt_share"].min(), "tỉ lệ", "xấp xỉ (khoảng)"),
        ("pt_share_max", work_all["pt_share"].max(), "tỉ lệ", "xấp xỉ (khoảng)"),
        ("cte_median_min", work_all["cte_median"].min(), "tỉ lệ", "xấp xỉ (khoảng)"),
        ("cte_median_max", work_all["cte_median"].max(), "tỉ lệ", "xấp xỉ (khoảng)"),
        ("fpy_strict", q["fpy_strict"], "tỉ lệ", "đo"),
        ("fpy_adjusted", q["fpy_adjusted"], "tỉ lệ", "đo"),
        ("rejected_issue_days_work", rej.loc["all", "issue_days_work"], "ngày làm việc", "đo"),
        ("rejected_after_in_progress", rej.loc["after_in_progress", "n_cases"], "ca", "đo"),
        ("throughput_per_week_mean", weeks["completions"].mean(), "ca/tuần", "đo"),
        ("wip_mean", weeks["wip_measured"].mean(), "ca", "đo"),
        ("backfill_share_of_changes",
         float(changes["is_backfill_entry"].mean()) if len(changes) else np.nan, "tỉ lệ", "đo"),
    ]
    return pd.DataFrame(rows, columns=["kpi", "value", "unit", "kind"])
