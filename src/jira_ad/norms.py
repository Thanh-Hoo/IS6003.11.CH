"""Định mức đúng/trễ (B3). Công ty không có SLA: định mức = phân vị của dwell lịch sử theo trạng thái.

Đây là định mức *nội suy từ lịch sử* (Quyết định 3, Ruling 69): với phân vị 0,75 thì khoảng 25%
lượt của mỗi trạng thái trễ theo cấu tạo. Ý nghĩa nằm ở *trễ bao nhiêu, ở đâu, ai chuyển ra*, không
ở tỉ lệ trễ. YAML cho thay bằng SLA thật (`explicit_days`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from jira_ad.process_metrics import is_human

DAY = 86_400.0


def fit_norms(
    status_log: pd.DataFrame, *, percentile: float, min_visits: int, explicit_days: dict[str, float]
) -> pd.DataFrame:
    """Một dòng mỗi trạng thái có lượt đã đóng: định mức (ngày làm việc), nguồn, số lượt."""
    closed = status_log[status_log["dwell_work_s"].notna()]
    rows = []
    for state, v in closed.groupby("state", sort=True):
        days = v["dwell_work_s"] / DAY
        if state in explicit_days:
            norm, source = float(explicit_days[state]), "SLA_cấu_hình"
        elif len(days) >= min_visits:
            norm, source = float(days.quantile(percentile)), f"p{round(percentile * 100)}_lịch_sử"
        else:
            norm, source = np.nan, "quá_ít_lượt"
        rows.append({"state": state, "norm_days": norm, "source": source, "n": len(days),
                     "median_days": float(days.median())})
    return pd.DataFrame(rows)


def late_visits(status_log: pd.DataFrame, norms: pd.DataFrame) -> pd.DataFrame:
    """Lượt đã đóng kèm định mức; trễ ⇔ dwell > định mức (bằng định mức là đúng hạn)."""
    closed = status_log[status_log["dwell_work_s"].notna()].copy()
    closed["dwell_days"] = closed["dwell_work_s"] / DAY
    closed["norm_days"] = closed["state"].map(norms.set_index("state")["norm_days"])
    has_norm = closed["norm_days"].notna()
    closed["is_late"] = pd.Series(pd.NA, index=closed.index, dtype="boolean")
    closed.loc[has_norm, "is_late"] = closed.loc[has_norm, "dwell_days"] > closed.loc[has_norm, "norm_days"]
    excess = (closed["dwell_days"] - closed["norm_days"]).clip(lower=0)
    closed["excess_days"] = excess.where(has_norm)
    return closed


def _summary(group: pd.DataFrame) -> dict:
    judged = group[group["is_late"].notna()]
    n_late = int(judged["is_late"].sum())
    return {"n_visits": len(group), "n_judged": len(judged), "n_late": n_late,
            "late_rate": n_late / len(judged) if len(judged) else np.nan,
            "excess_days": float(judged["excess_days"].sum()),
            "median_dwell_days": float(group["dwell_days"].median())}


def late_by_state(late: pd.DataFrame) -> pd.DataFrame:
    rows = [{"state": s, "norm_days": g["norm_days"].iloc[0], **_summary(g)}
            for s, g in late.groupby("state", sort=True)]
    out = pd.DataFrame(rows)
    total = out["excess_days"].sum()
    out["share_of_excess"] = out["excess_days"] / total if total else np.nan
    return out.sort_values(["excess_days", "state"], ascending=[False, True]).reset_index(drop=True)


def late_by_role(late: pd.DataFrame) -> pd.DataFrame:
    """Theo vai trò chuyển ra khỏi trạng thái (`exit_role`); bot/unknown/thiếu role được đánh dấu."""
    rows = []
    for role, g in late.groupby(late["exit_role"].fillna("__MISSING_ROLE__"), sort=True):
        s = _summary(g)
        rows.append({"role": role, "is_human": is_human(role), "n_exits": s.pop("n_visits"), **s})
    out = pd.DataFrame(rows)
    return out.sort_values(["is_human", "excess_days", "role"], ascending=[False, False, True]).reset_index(
        drop=True)


def late_by_case(late: pd.DataFrame, cases: pd.DataFrame, *, percentile: float) -> pd.DataFrame:
    """Theo ca: số lượt trễ, ngày vượt định mức; CT_work so với phân vị của nhánh kết thúc."""
    per = late.groupby("case_id").apply(lambda g: pd.Series(_summary(g)), include_groups=False)
    out = cases[["case_id", "terminal_status", "ct_work_s"]].merge(
        per.reset_index(), on="case_id", how="left")
    out["ct_work_days"] = out["ct_work_s"] / DAY
    out["ct_norm_days"] = out.groupby("terminal_status")["ct_work_days"].transform(
        lambda s: s.quantile(percentile))
    out["ct_late"] = out["ct_work_days"] > out["ct_norm_days"]
    out["n_late"] = out["n_late"].fillna(0).astype(int)
    return out.drop(columns="ct_work_s").sort_values(
        ["excess_days", "case_id"], ascending=[False, True]).reset_index(drop=True)


def top_late(late: pd.DataFrame, k: int) -> pd.DataFrame:
    cols = ["case_id", "terminal_status", "state", "visit_index", "dwell_days", "norm_days",
            "excess_days", "exit_role"]
    judged = late[late["is_late"].fillna(False).astype(bool)]
    return judged.sort_values(["excess_days", "case_id"], ascending=[False, True])[cols].head(k).reset_index(
        drop=True)
