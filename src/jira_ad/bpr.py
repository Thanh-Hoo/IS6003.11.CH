"""Tái thiết kế quy trình (B2 BPR heuristics, B4 AS-IS/TO-BE): kiểm chứng ứng viên và what-if trên log.

- Mỗi ứng viên được **kiểm chứng** bằng một câu hỏi đo được trên dữ liệu và ngưỡng **khóa trước** trong
  `configs/process.yaml` (`bpr`); phán quyết: ủng hộ / không ủng hộ / không đủ dữ liệu.
- **What-if** tính lại trên chính log (không mô phỏng): kết quả là *mục tiêu / kịch bản ước tính*, kèm
  giả định, không bao giờ là kết quả đo của một thay đổi đã triển khai.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from jira_ad.process_metrics import is_human

DAY = 86_400.0
SUPPORT, REJECT, INSUFFICIENT = "ủng hộ", "không ủng hộ", "không đủ dữ liệu"
TOBE_LABEL = "mục tiêu / kịch bản ước tính"
LINK_ACTIVITIES = ("LINK_COMMIT", "LINK_MERGE_REQUEST")


def _result(candidate, question, metric, value, threshold, verdict, evidence, **extra) -> dict:
    return {"candidate": candidate, "question": question, "metric": metric, "value": value,
            "threshold": threshold, "verdict": verdict, "evidence": evidence, **extra}


def _days(x: float) -> str:
    return f"{round(x, 1) + 0.0:.1f}".replace(".", ",")  # + 0.0: không in "-0,0"


def _dec(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


# ------------------------------------------------------------------------------------ kiểm chứng


def check_early_triage(cases: pd.DataFrame, log: pd.DataFrame, *, min_share: float,
                       min_median_days: float) -> dict:
    rejected = cases[cases["terminal_status"] == "Rejected"]
    share = rejected["ct_work_s"].sum() / cases["ct_work_s"].sum()
    median = rejected["ct_work_s"].median() / DAY if len(rejected) else float("nan")
    ok = share >= min_share and median >= min_median_days
    ordered = log.sort_values(["case_id", "visit_index"])
    before_last = ordered.groupby("case_id")["state"].apply(lambda s: s.iloc[-2] if len(s) > 1 else None)
    after_inv = int((before_last.reindex(rejected["case_id"]) == "INVESTIGATED").sum())
    return _result(
        "early_triage", "Ca Rejected có tốn phần đáng kể thời gian trước khi bị loại không?",
        "tỉ trọng ngày-issue làm việc của ca Rejected", share,
        f">= {min_share} và trung vị >= {min_median_days} ngày", SUPPORT if ok else REJECT,
        f"{len(rejected)} ca Rejected; trung vị {_days(median)} ngày làm việc tới khi bị loại; "
        f"{after_inv}/{len(rejected)} ca bị loại ngay sau INVESTIGATED (phép kiểm đo quy mô vấn đề, "
        "không đo được bao nhiêu ca có thể quyết sớm hơn)",
        median_days=median, n_after_investigated=after_inv)


def check_auto_transition(log: pd.DataFrame, events: pd.DataFrame, *, min_share: float) -> dict:
    """Ca có commit/MR liên kết: lần liên kết đầu tiên có xảy ra trước khi vào In Progress không."""
    first_link = (events[events["activity"].isin(LINK_ACTIVITIES)]
                  .groupby("case_id")["timestamp_utc"].min())
    enter = log[log["state"] == "In Progress"].groupby("case_id")["t_enter"].min()
    both = pd.concat([first_link.rename("link"), enter.rename("enter")], axis=1, join="inner")
    if both.empty:
        return _result("auto_transition", "Commit/MR có xuất hiện trước khi chuyển In Progress không?",
                       "tỉ lệ ca liên kết trước In Progress", float("nan"), f">= {min_share}", INSUFFICIENT,
                       "không có ca nào vừa có liên kết commit/MR vừa vào In Progress")
    early = both["link"] < both["enter"]
    lag = ((both["enter"] - both["link"])[early].dt.total_seconds() / DAY)
    share = float(early.mean())
    # Trạng thái đang mở lúc có liên kết đầu tiên (lượt cuối cùng bắt đầu trước thời điểm đó).
    ordered = log.sort_values(["case_id", "visit_index"])
    where = {}
    for case_id, link in both.loc[early, "link"].items():
        v = ordered[(ordered["case_id"] == case_id) & (ordered["t_enter"] <= link)]
        where[case_id] = v["state"].iloc[-1] if len(v) else "__CREATED__"
    tally = pd.Series(where, dtype=object).value_counts().items()
    counts = dict(sorted(tally, key=lambda kv: (-kv[1], kv[0])))
    in_todo = int(counts.get("To Do", 0))
    return _result(
        "auto_transition", "Commit/MR có xuất hiện trước khi chuyển In Progress không?",
        "tỉ lệ ca liên kết commit/MR trước khi vào In Progress", share, f">= {min_share}",
        SUPPORT if share >= min_share else REJECT,
        f"{int(early.sum())}/{len(both)} ca; "
        f"trễ trung vị {_days(lag.median() if len(lag) else 0.0)} ngày lịch "
        "giữa liên kết đầu tiên và lúc chuyển In Progress; liên kết đầu rơi vào: "
        + ", ".join(f"{k} {n}" for k, n in counts.items())
        + f" (cung tự động To Do → In Progress chỉ áp dụng cho {in_todo} ca)",
        n_cases=len(both), link_state_counts=counts, n_in_automated_state=in_todo)


def check_merge(log: pd.DataFrame, *, source: str, target: str, max_days: float, min_share: float) -> dict:
    ordered = log.sort_values(["case_id", "visit_index"])
    nxt = ordered.groupby("case_id")["state"].shift(-1)
    hops = ordered[(ordered["state"] == source) & (nxt == target)]
    if hops.empty:
        return _result("merge_investigated", f"{source} → {target} có chỉ là bước đi xuyên qua không?",
                       "tỉ lệ đi xuyên qua", float("nan"), f">= {min_share}", INSUFFICIENT,
                       "không có lần chuyển nào")
    fast = (hops["dwell_work_s"] / DAY) <= max_days
    share = float(fast.mean())
    return _result(
        "merge_investigated", f"{source} → {target} có chỉ là bước đi xuyên qua không?",
        f"tỉ lệ lần {source} → {target} trong <= {max_days} ngày làm việc", share, f">= {min_share}",
        SUPPORT if share >= min_share else REJECT,
        f"{int(fast.sum())}/{len(hops)} lần chuyển; "
        f"trung vị {_days(hops['dwell_work_s'].median() / DAY)} ngày")


def check_role_dependency(log: pd.DataFrame, *, state: str, role: str, n_boot: int, seed: int) -> dict:
    """Chờ ở `state` khi `role` chuyển ra có dài hơn khi vai trò người khác chuyển ra không (bootstrap)."""
    v = log[(log["state"] == state) & log["dwell_work_s"].notna() & log["exit_role"].map(is_human)]
    a = (v.loc[v["exit_role"] == role, "dwell_work_s"] / DAY).to_numpy()
    b = (v.loc[v["exit_role"] != role, "dwell_work_s"] / DAY).to_numpy()
    question = f"Chờ ở {state} có gắn với {role} (vai trò chuyển ra) không?"
    if len(a) < 5 or len(b) < 5:
        return _result("reduce_po_dependency", question, "chênh trung vị (ngày)", float("nan"),
                       "CI 95% > 0", INSUFFICIENT, f"{len(a)} lượt {role}, {len(b)} lượt vai trò khác")
    rng = np.random.default_rng(seed)
    diffs = np.array([np.median(rng.choice(a, len(a))) - np.median(rng.choice(b, len(b)))
                      for _ in range(n_boot)])
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    diff = float(np.median(a) - np.median(b))
    return _result(
        "reduce_po_dependency", question, f"trung vị dwell ({role} chuyển ra) − (vai trò khác)", diff,
        "CI 95% > 0", SUPPORT if lo > 0 else REJECT,
        f"{len(a)} lượt {role} (trung vị {_days(np.median(a))} ngày) so với {len(b)} lượt vai trò khác "
        f"(trung vị {_days(np.median(b))} ngày); CI 95% [{_days(lo)}; {_days(hi)}]",
        ci_low=float(lo), ci_high=float(hi))


def check_duplicate(events: pd.DataFrame, cases: pd.DataFrame, *, pattern: str, min_cases: int,
                    min_median_days: float) -> dict:
    dup_ids = set(events.loc[events["raw_action"].str.contains(pattern, case=False, regex=False), "case_id"])
    dup = cases[cases["case_id"].isin(dup_ids) & (cases["terminal_status"] == "Rejected")]
    question = "Ca bị loại vì trùng có bị phát hiện muộn không?"
    if len(dup) < min_cases:
        return _result("early_duplicate_detection", question, "trung vị ngày tới khi Rejected", float("nan"),
                       f">= {min_cases} ca và trung vị >= {min_median_days} ngày", INSUFFICIENT,
                       f"chỉ {len(dup)} ca Rejected có liên kết '{pattern}' ({len(dup_ids)} ca có liên kết)")
    median = dup["ct_work_s"].median() / DAY
    return _result(
        "early_duplicate_detection", question, "trung vị ngày làm việc tới khi Rejected (ca trùng)", median,
        f">= {min_median_days} ngày", SUPPORT if median >= min_median_days else REJECT,
        f"{len(dup)} ca Rejected có liên kết '{pattern}'; "
        f"trung vị {_days(median)} ngày làm việc tới khi bị loại")


def check_investigating_state(ranges: pd.DataFrame, *, min_width_pp: float) -> dict:
    work = ranges[(ranges["clock"] == "work") & (ranges["branch"] == "all")].set_index("variant")["pt_share"]
    width = (work.max() - work.min()) * 100
    driver = abs(work["sensitivity"] - work["main"]) * 100
    ok = width > min_width_pp and driver > min_width_pp / 2
    return _result(
        "add_investigating_state",
        "Công sức điều tra có bị Jira che khuất (PT phụ thuộc cách xếp To Investigate)?",
        "độ rộng khoảng PT (điểm %)", width, f"> {min_width_pp} và do cách xếp To Investigate",
        SUPPORT if ok else REJECT,
        f"PT chính {work['main'] * 100:.1f}%, nếu To Investigate là làm {work['sensitivity'] * 100:.1f}%"
        .replace(".", ","))


def check_fast_track(cases: pd.DataFrame, flags: pd.DataFrame, *, max_fpy_drop: float) -> dict:
    skip = set(flags.loc[(flags["flag"] == "skip_investigation") & (flags["n"] > 0), "case_id"])
    done = cases[cases["terminal_status"] == "DONE"].copy()
    done["skip"] = done["case_id"].isin(skip)
    done["clean"] = (done["n_back"] == 0) & (done["n_reopen"] == 0)
    g = done.groupby("skip")
    question = "Ca DONE bỏ pha điều tra có chậm hơn hoặc nhiều làm lại hơn không?"
    if set(g.groups) != {True, False}:
        return _result("fast_track", question, "trung vị CT (ngày)", float("nan"), "", INSUFFICIENT,
                       "thiếu một trong hai nhóm")
    ct = g["ct_work_s"].median() / DAY
    fpy = g["clean"].mean()
    ok = ct[True] <= ct[False] and fpy[False] - fpy[True] <= max_fpy_drop
    evidence = (f"{int(g.size()[True])} ca bỏ điều tra: CT {_days(ct[True])} ngày, FPY {_dec(fpy[True])}; "
                f"{int(g.size()[False])} ca có điều tra: CT {_days(ct[False])} ngày, FPY {_dec(fpy[False])}")
    return _result(
        "fast_track", question, "trung vị CT ngày làm việc (bỏ điều tra − có điều tra)", ct[True] - ct[False],
        f"<= 0 và FPY giảm <= {max_fpy_drop}", SUPPORT if ok else REJECT, evidence)


# ------------------------------------------------------------------------------------- what-if


def whatif_early_triage(cases: pd.DataFrame, log: pd.DataFrame) -> dict:
    """Ca Rejected được quyết ngay ở lần đổi trạng thái đầu: CT = đoạn từ tạo tới lần đổi đầu (cận trên)."""
    created = log[log["visit_index"] == 0].set_index("case_id")["dwell_work_s"]
    rejected = cases[cases["terminal_status"] == "Rejected"]
    tobe_rej = rejected["case_id"].map(created).fillna(rejected["ct_work_s"])
    tobe_all = cases.set_index("case_id")["ct_work_s"].copy()
    tobe_all.loc[rejected["case_id"]] = tobe_rej.to_numpy()
    return {"asis_rejected_issue_days": rejected["ct_work_s"].sum() / DAY,
            "tobe_rejected_issue_days": tobe_rej.sum() / DAY,
            "asis_ct_median_days": cases["ct_work_s"].median() / DAY,
            "tobe_ct_median_days": tobe_all.median() / DAY,
            "per_case": tobe_all.rename("ct_work_s_tobe").reset_index()}


def whatif_reject_at_investigation_end(cases: pd.DataFrame, log: pd.DataFrame) -> dict:
    """Ca Rejected đã qua điều tra được quyết ngay khi rời To Investigate (bỏ chờ ở INVESTIGATED và sau đó);
    ca không qua điều tra giữ nguyên. Nhất quán với TO-BE (vẫn có Investigating → Rejected)."""
    rejected = cases[cases["terminal_status"] == "Rejected"]
    tobe_all = cases.set_index("case_id")["ct_work_s"].copy()
    ordered = log.sort_values(["case_id", "visit_index"])
    for case_id in rejected["case_id"]:
        v = ordered[ordered["case_id"] == case_id]
        investigated = v.index[v["state"] == "To Investigate"]
        if len(investigated):
            upto = v.loc[:investigated[-1], "dwell_work_s"].fillna(0.0)
            tobe_all[case_id] = upto.sum()
    tobe_rej = tobe_all.loc[rejected["case_id"]]
    return {"asis_rejected_issue_days": rejected["ct_work_s"].sum() / DAY,
            "tobe_rejected_issue_days": tobe_rej.sum() / DAY,
            "asis_ct_median_days": cases["ct_work_s"].median() / DAY,
            "tobe_ct_median_days": tobe_all.median() / DAY,
            "per_case": tobe_all.rename("ct_work_s_tobe").reset_index()}


def whatif_cap_state(log: pd.DataFrame, *, state: str, cap_days: float) -> pd.DataFrame:
    """Chờ ở `state` không quá `cap_days` ngày làm việc (vd định mức P75); CT các ca tính lại."""
    dwell = log["dwell_work_s"].fillna(0.0)
    capped = dwell.where(log["state"] != state, dwell.clip(upper=cap_days * DAY))
    out = pd.DataFrame({"case_id": log["case_id"], "asis": dwell, "tobe": capped})
    out = out.groupby("case_id", sort=False).sum().reset_index()
    return out.rename(columns={"asis": "ct_work_s_asis", "tobe": "ct_work_s_tobe"})


def whatif_auto_transition(log: pd.DataFrame, events: pd.DataFrame, *, work_states) -> dict:
    """Chuyển In Progress tự động tại liên kết commit/MR đầu tiên: phần To Do sau liên kết thành 'làm'."""
    work_states = set(work_states)
    first_link = events[events["activity"].isin(LINK_ACTIVITIES)].groupby("case_id")["timestamp_utc"].min()
    dwell = log["dwell_work_s"].fillna(0.0)
    pt_asis = dwell.where(log["state"].isin(work_states), 0.0).sum()
    extra, changed = 0.0, set()
    todo = log[(log["state"] == "To Do") & log["dwell_work_s"].notna()]
    for r in todo.itertuples():
        link = first_link.get(r.case_id)
        t_exit = r.t_enter + pd.Timedelta(seconds=r.dwell_cal_s)
        if link is not None and r.t_enter <= link < t_exit:
            extra += r.dwell_work_s * (t_exit - link).total_seconds() / r.dwell_cal_s
            changed.add(r.case_id)
    total = dwell.sum()
    return {"pt_share_asis": pt_asis / total, "pt_share_tobe": (pt_asis + extra) / total,
            "n_cases_changed": len(changed)}


def whatif_merge(log: pd.DataFrame, *, source: str, target: str) -> dict:
    ordered = log.sort_values(["case_id", "visit_index"])
    nxt = ordered.groupby("case_id")["state"].shift(-1)
    n_cases = ordered["case_id"].nunique()
    changes = int((ordered["visit_index"] > 0).sum())
    merged = int(((ordered["state"] == source) & (nxt == target)).sum())
    return {"changes_per_case_asis": changes / n_cases, "changes_per_case_tobe": (changes - merged) / n_cases,
            "n_merged_transitions": merged}


def whatif_tobe_path(log: pd.DataFrame, *, drop, insert_after: dict[str, str], entry: str) -> dict:
    """Biến đường trạng thái AS-IS mỗi ca thành đường TO-BE (bỏ trạng thái bị gộp, thêm trạng thái mới, đi
    qua trạng thái vào tường minh) rồi đếm số lần đổi trạng thái (rà soát độc lập I4)."""
    ordered = log.sort_values(["case_id", "visit_index"])
    asis, tobe = [], []
    for _, v in ordered.groupby("case_id", sort=False):
        states = list(v["state"].iloc[1:])
        route = []
        for st in states:
            if st in set(drop):
                continue
            route.append(st)
            if st in insert_after:
                route.append(insert_after[st])
        if not route or route[0] != entry:
            route.insert(0, entry)
        asis.append(len(states))
        tobe.append(len(route))
    return {"changes_per_case_asis": float(np.mean(asis)), "changes_per_case_tobe": float(np.mean(tobe))}


def kpi_asis_tobe(rows: list[dict]) -> pd.DataFrame:
    table = pd.DataFrame(rows)
    table["delta"] = table["tobe"] - table["asis"]
    table["delta_pct"] = table["delta"] / table["asis"].where(table["asis"] != 0)
    table["tobe_label"] = TOBE_LABEL
    return table


def state_excess_by_role(late: pd.DataFrame, *, state: str) -> pd.DataFrame:
    """Mô tả (không phải phán quyết): ngày vượt định mức của một trạng thái chia theo vai trò chuyển ra."""
    part = late[late["state"] == state].copy()
    part["exit_role"] = part["exit_role"].fillna("__MISSING_ROLE__")
    out = part.groupby("exit_role").agg(n_visits=("state", "size"),
                                        n_late=("is_late", lambda s: int(s.fillna(False).astype(bool).sum())),
                                        excess_days=("excess_days", "sum")).reset_index()
    out = out.rename(columns={"exit_role": "role"})
    out["is_human"] = out["role"].map(is_human)
    total = out["excess_days"].sum()
    out["share_of_state_excess"] = out["excess_days"] / total if total else np.nan
    return out.sort_values(["excess_days", "role"], ascending=[False, True]).reset_index(drop=True)


def problem_table(candidates, checks: pd.DataFrame) -> pd.DataFrame:
    """Vấn đề → bằng chứng → thủ pháp BPR → phán quyết; chỉ ứng viên 'ủng hộ' vào TO-BE."""
    by = checks.set_index("candidate")
    rows = [{"candidate": c.id, "problem": c.problem, "evidence": by.loc[c.id, "evidence"],
             "metric": by.loc[c.id, "metric"], "value": by.loc[c.id, "value"],
             "threshold": by.loc[c.id, "threshold"], "heuristic": c.heuristic,
             "verdict": by.loc[c.id, "verdict"], "in_tobe": by.loc[c.id, "verdict"] == SUPPORT}
            for c in candidates]
    return pd.DataFrame(rows)


def pilot_plan(phases, kpi: pd.DataFrame) -> pd.DataFrame:
    """Kế hoạch pilot: mỗi giai đoạn × KPI theo dõi, kèm mốc AS-IS (đo) và mục tiêu TO-BE (ước tính)."""
    by = kpi.set_index("kpi")
    rows = []
    for p in phases:
        for name in p.kpis:
            measured = name in by.index
            rows.append({"phase": p.id, "weeks": p.weeks, "action": p.action, "kpi": name,
                         "baseline_asis": by.loc[name, "asis"] if measured else np.nan,
                         "target_tobe": by.loc[name, "tobe"] if measured else np.nan,
                         "unit": by.loc[name, "unit"] if measured else "", "tobe_label": TOBE_LABEL,
                         "note": "" if measured else "chưa đo trong run này (vd replay chưa duyệt)"})
    return pd.DataFrame(rows)


def state_excess_by_role_and_target(late: pd.DataFrame, log: pd.DataFrame, *, state: str) -> pd.DataFrame:
    """Mô tả: ngày vượt định mức của `state` theo (vai trò chuyển ra, trạng thái đích) — tách việc dọn backlog
    (chuyển thẳng sang Rejected) khỏi chờ trước khi sửa (rà soát độc lập I5)."""
    ordered = log.sort_values(["case_id", "visit_index"])
    target = ordered.groupby("case_id")["state"].shift(-1)
    key = ordered[["case_id", "visit_index"]].assign(target_state=target.to_numpy())
    part = late[late["state"] == state].merge(key, on=["case_id", "visit_index"], how="left")
    part["role"] = part["exit_role"].fillna("__MISSING_ROLE__")
    out = part.groupby(["role", "target_state"]).agg(n_visits=("state", "size"),
                                                     excess_days=("excess_days", "sum")).reset_index()
    out["share_of_role_excess"] = out["excess_days"] / out.groupby("role")["excess_days"].transform("sum")
    out["is_human"] = out["role"].map(is_human)
    return out.sort_values(["excess_days", "role"], ascending=[False, True]).reset_index(drop=True)
